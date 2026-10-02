"""`placemat studio <script>`: a local page that shows a layout as it is made.

A server on 127.0.0.1 (standard library only), a random token required on
every request, Server-Sent Events for what the page shows. It watches the
script, what it imports, the board's placemat.toml files, the lock and the
cached generation (studio_watch.py); after `debounce_ms` of quiet it asks a
warm worker process (studio_worker.py) to resolve the script as `placemat
preview` does, and relays the worker's events: `started` with the changed
files and their diffs, a `step` for each item as it settles, then `copper`,
`links`, `congestion`, `findings`, the final `items`, `finished` and a
`compare` with the previous resolve. A change while a resolve runs cancels
it; the page is told at once (`changed`), so a plan that no longer matches the
files is never shown as current.

The last `keep` resolves are kept so the page can compare any two (`/diff`)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hmac
import http.server
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

from .console import console
from .studio_diff import diff_plans, line_diff, trace, unified_diff, with_spans
from .studio_watch import Debounce, Poller

KEEPALIVE_S = 15.0         # a comment on an idle stream, so a proxy or a browser does not drop it
PAGE = Path(__file__).with_name("studio_page.html")


@dataclass
class Record:
    """One finished resolve, as kept for comparing."""
    id: int
    at: float                                   # epoch seconds it finished
    texts: dict                                 # file name -> text at its start
    doc: dict                                   # preview_json.plan_json, items with their spans
    changed: list                               # what changed from the resolve before (as `started` said)
    timing: dict = field(default_factory=dict)
    reused: str = ""
    notes: list = field(default_factory=list)

    def summary(self) -> dict:
        return {"id": self.id, "at": self.at, "changed": [c["file"] for c in self.changed], "timing": self.timing,
                "counts": self.doc["counts"], "score": (self.doc.get("score") or {}).get("total"), "reused": self.reused}


class Hub:
    """The page's streams: each client a queue, and the events of the resolve
    in flight, kept to replay to a page that connects part-way through it."""

    def __init__(self, lock):
        self.lock = lock                        # the studio's own: one order of locking, whoever calls
        self.clients: list = []
        self.log: list = []

    def emit(self, name: str, data, keep: bool = False) -> None:
        text = json.dumps(data, separators=(",", ":"))
        with self.lock:
            if keep:
                self.log.append((name, text))
            for q in self.clients:
                q.put((name, text))

    def subscribe(self, first) -> "queue.Queue":
        """A new client's queue, primed with `first()`'s events and then the
        in-flight log, atomically with its registration: it misses nothing."""
        q: queue.Queue = queue.Queue()
        with self.lock:
            for name, text in first():
                q.put((name, text))
            for item in self.log:
                q.put(item)
            self.clients.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)


class WorkerProcess:
    """The warm resolve process, spoken to in JSON lines. Restartable: a
    resolve that will not stop is killed and the next one starts a new one."""

    def __init__(self, on_event, log_path: Path):
        self.on_event, self.log_path = on_event, log_path
        self.proc = None
        self.serial = 0

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        self.serial += 1
        serial = self.serial
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, "ab")
        self.proc = subprocess.Popen([sys.executable, "-m", "placemat.studio_worker"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
        log.close()
        threading.Thread(target=self._read, args=(self.proc, serial), daemon=True).start()

    def _read(self, proc, serial) -> None:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            self.on_event(ev, serial)
        self.on_event({"ev": "exited", "code": proc.wait()}, serial)

    def send(self, cmd: dict) -> bool:
        if not self.alive():
            self.start()
        try:
            self.proc.stdin.write(json.dumps(cmd) + "\n")
            self.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def kill(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        self.serial += 1                        # what the old process still says is not heard
        proc.kill()
        proc.wait()

    def stop(self) -> None:
        proc = self.proc
        if proc is None:
            return
        try:
            proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=3)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            pass
        self.kill()


class Studio:
    def __init__(self, script, port: int | None = None, open_browser: bool | None = None, **settings):
        from . import settings as settings_mod
        from .project import find_board
        self.script = Path(script).resolve()
        if not self.script.is_file():
            raise ValueError("%s is not a file" % script)
        self.src = find_board(self.script)
        cfg = settings_mod.load(self.src.board_dir, script=self.script)
        get = lambda name, given: given if given is not None else settings.get(name, getattr(cfg, "studio_" + name))
        self.port = get("port", port)
        self.open_browser = get("open", open_browser)
        self.debounce_s = get("debounce_ms", None) / 1000.0
        self.poll_s = get("poll_ms", None) / 1000.0
        self.grace_s = get("cancel_grace_ms", None) / 1000.0
        self.keep = get("keep", None)
        self.token = secrets.token_urlsafe(16)
        self.lock = threading.RLock()
        self.hub = Hub(self.lock)
        self.history: deque = deque(maxlen=max(1, self.keep))
        self.debounce = Debounce(self.debounce_s)
        self.server = None
        self.url = ""
        self._stopping = threading.Event()
        self._threads: list = []
        self._files: list = []
        self._poller = None
        self._next_id = 0
        self._cur = None                        # the resolve in flight: {"id", "texts", "changed"}
        self._dirty = False                     # a file changed since the resolve in flight began
        self._cancel_at = None
        self._initial = True
        self._error = None
        views = self.src.board_dir / ".placemat" / "views" / "studio"
        self.worker = WorkerProcess(self._on_worker, views / "worker.log")

    # ------------------------------------------------------------ files
    def name_of(self, path) -> str:
        return os.path.relpath(path, self.script.parent)

    def watched(self) -> list:
        """What a resolve depends on: the script and what it imports, its lock
        and routes, every placemat.toml above the board, the fab profile and
        the cached generation."""
        from .project import fab_profile, script_files
        from .runner import cached_generation
        from .settings import _files
        files = list(script_files(self.script, missing=True))
        files += _files(self.script.parent)
        try:
            fab = fab_profile(self.src.board_dir)
            if fab.path:
                files.append(Path(fab.path))
        except (ValueError, OSError):
            pass
        files.append(cached_generation(self.src) / self.src.pcb.name)
        seen, out = set(), []
        for f in files:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def snapshot_texts(self) -> dict:
        out = {}
        for f in self._files:
            if f.suffix == ".kicad_pcb" or not f.is_file():
                continue
            try:
                out[self.name_of(f)] = f.read_text(errors="replace")
            except OSError:
                pass
        return out

    # ------------------------------------------------------------ lifecycle
    def start(self) -> str:
        handler = _handler(self)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:%d/?t=%s" % (self.port, self.token)
        self._files = self.watched()
        self._poller = Poller(lambda: self._files)
        for target in (self.server.serve_forever, self._watch):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)
        return self.url

    def stop(self) -> None:
        self._stopping.set()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        self.worker.stop()
        for t in self._threads:
            t.join(timeout=5)

    def wait(self) -> None:
        while not self._stopping.wait(0.5):
            pass

    # ------------------------------------------------------------ the watch loop
    def _watch(self) -> None:
        while True:
            try:
                self._tick(time.monotonic())
            except Exception as e:              # a failure in one tick does not end the watch
                print("studio: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            if self._stopping.wait(self.poll_s):
                return

    def _tick(self, now: float) -> None:
        changed = self._poller.scan()
        if changed:
            self._files = self.watched()        # an import added or dropped changes what is watched
            self._on_change(now, changed)
        with self.lock:
            if self._cancel_at is not None and now - self._cancel_at > self.grace_s and self._cur is not None:
                self.worker.kill()              # it did not reach a step to stop at
                self._finish_cancel()
            if self._initial:
                self._initial = False
                self._begin(set())
                return
            due = self.debounce.due(now)
            if due:
                self._begin(due)

    def _on_change(self, now: float, changed: set) -> None:
        names = sorted(self.name_of(p) for p in changed)
        with self.lock:
            self.hub.emit("changed", {"files": names, "at": time.time()})
            if self.debounce.changed(now, changed):
                self._dirty = True
                if self._cur is not None and self._cancel_at is None:
                    self._cancel_at = now
                    self.worker.send({"cmd": "cancel", "id": self._cur["id"]})

    def _begin(self, changed_paths) -> None:
        """Start a resolve: snapshot the files, say what changed from the
        last finished resolve, hand the script to the worker."""
        with self.lock:
            self._next_id += 1
            rid = self._next_id
            texts = self.snapshot_texts()
            last = self.history[-1] if self.history else None
            changed = []
            if last is not None:
                for name in sorted(set(texts) | set(last.texts)):
                    old, new = last.texts.get(name), texts.get(name)
                    if old == new:
                        continue
                    ld = line_diff(old or "", new or "")
                    changed.append({"file": name, "status": "added" if old is None else "removed" if new is None else "modified",
                                    "unified": unified_diff(old or "", new or "", name), "added": ld["added"], "removed": ld["removed"]})
            self._cur = {"id": rid, "texts": texts, "changed": changed, "t0": time.monotonic()}
            self._dirty, self._cancel_at = False, None
            self.debounce.started()
            self.hub.log.clear()
            self.hub.emit("started", {"id": rid, "script": self.script.name, "at": time.time(), "texts": texts,
                                      "changed": changed, "stale_files": sorted(self.name_of(p) for p in changed_paths)},
                          keep=True)
            if not self.worker.send({"cmd": "resolve", "id": rid, "script": str(self.script)}):
                self._fail(rid, "the resolve worker could not be started")

    def _finish_cancel(self) -> None:
        cur = self._cur
        self._cur, self._cancel_at = None, None
        self.debounce.stopped()
        if cur is not None:
            self.hub.emit("cancelled", {"id": cur["id"]})
            self.hub.log.clear()

    def _fail(self, rid, message, **extra) -> None:
        self._cur, self._cancel_at = None, None
        self.debounce.stopped()
        self._error = {"id": rid, "message": message, **extra}
        self.hub.emit("error", self._error)
        self.hub.log.clear()

    # ------------------------------------------------------------ worker events
    def _on_worker(self, ev: dict, serial: int) -> None:
        with self.lock:
            if serial != self.worker.serial:
                return                          # from a worker that has been killed
            kind = ev.get("ev")
            cur = self._cur
            if kind == "exited":
                if cur is not None:
                    self._fail(cur["id"], "the resolve worker stopped (exit %s); see %s" % (ev.get("code"), self.worker.log_path))
                return
            if cur is None or ev.get("id") != cur["id"]:
                return
            rid = cur["id"]
            if kind == "board":
                self.hub.emit("board", {k: v for k, v in ev.items() if k not in ("ev", "id")} | {"id": rid}, keep=True)
            elif kind == "item":
                self.hub.emit("step", {"id": rid, "item": self._named(ev["item"])}, keep=True)
            elif kind == "cancelled":
                self._finish_cancel()
            elif kind == "error":
                self._fail(rid, ev["message"], file=self.name_of(ev["file"]) if ev.get("file") else "", line=ev.get("line"),
                           source=ev.get("source"), detail=ev.get("detail", ""))
            elif kind == "done":
                if self._dirty:
                    self._cur, self._cancel_at = None, None
                    self.debounce.stopped()
                    self.hub.emit("superseded", {"id": rid})
                    self.hub.log.clear()
                else:
                    self._finish(cur, ev)

    def _named(self, item: dict) -> dict:
        if item.get("file"):
            item = dict(item, file=self.name_of(item["file"]))
        return item

    def _finish(self, cur: dict, ev: dict) -> None:
        rid = cur["id"]
        doc = ev["doc"]
        for item in doc["items"]:
            item["file"] = self.name_of(item["file"]) if item.get("file") else ""
        doc = with_spans(doc, cur["texts"])
        rec = Record(rid, time.time(), cur["texts"], doc, cur["changed"], ev["timing"], ev.get("reused", ""), ev.get("notes", []))
        previous = self.history[-1] if self.history else None
        self.history.append(rec)
        self._cur, self._cancel_at, self._error = None, None, None
        self.debounce.stopped()
        emit = self.hub.emit
        emit("copper", {"id": rid, "copper": doc["copper"]}, keep=True)
        emit("links", {"id": rid, "links": doc["links"]}, keep=True)
        emit("congestion", {"id": rid, "congestion": doc["congestion"]}, keep=True)
        emit("findings", {"id": rid, "findings": doc["findings"]}, keep=True)
        emit("items", {"id": rid, "items": doc["items"], "steps": doc["steps"], "unplaced": doc["unplaced"],
                       "pocketed": doc["pocketed"], "board": doc["board"], "keepouts": doc["keepouts"],
                       "reservations": doc["reservations"]}, keep=True)
        emit("finished", {"id": rid, "counts": doc["counts"], "timing": rec.timing, "reused": rec.reused, "notes": rec.notes,
                          "score": doc.get("score"), "history": [r.summary() for r in self.history]}, keep=True)
        if previous is not None:
            emit("compare", self.compare(previous, rec), keep=True)
        self.hub.log.clear()                    # a page that connects now is given the whole of it by hello()

    # ------------------------------------------------------------ comparing
    @staticmethod
    def compare(a: Record, b: Record) -> dict:
        """What `b` changed from `a`: the plans' diff, each changed file's
        lines, and the trace between them."""
        d = diff_plans(a.doc, b.doc)
        files = {n: line_diff(a.texts.get(n, ""), b.texts.get(n, "")) for n in sorted(set(a.texts) | set(b.texts))
                 if a.texts.get(n) != b.texts.get(n)}
        return {"a": a.id, "b": b.id, "diff": d, "files": files, "trace": trace(d, a.doc, b.doc, files)}

    def record(self, rid: int):
        with self.lock:
            return next((r for r in self.history if r.id == rid), None)

    def hello(self) -> list:
        """What a page that connects now is told before the live stream: the
        studio's state, and the latest finished resolve whole."""
        with self.lock:
            out = [("hello", json.dumps({"script": self.script.name, "keep": self.keep,
                                         "history": [r.summary() for r in self.history],
                                         "resolving": self._cur["id"] if self._cur else None,
                                         "error": self._error}, separators=(",", ":")))]
            if self.history:
                last = self.history[-1]
                prev = self.history[-2] if len(self.history) > 1 else None
                out.append(("state", json.dumps({"id": last.id, "doc": last.doc, "texts": last.texts, "changed": last.changed,
                                                 "timing": last.timing, "reused": last.reused, "notes": last.notes,
                                                 "compare": self.compare(prev, last) if prev else None}, separators=(",", ":"))))
            return out


# ------------------------------------------------------------------ HTTP
def _handler(studio: Studio):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "placemat-studio"

        def log_message(self, *args):
            pass

        def _refuse(self, code: int, text: str) -> None:
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self, query: dict) -> bool:
            host = (self.headers.get("Host") or "").lower()
            if host not in ("127.0.0.1:%d" % studio.port, "localhost:%d" % studio.port):
                return False
            given = (query.get("t") or [self.headers.get("X-Studio-Token") or ""])[0]
            return hmac.compare_digest(given.encode(), studio.token.encode())

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if not self._allowed(query):
                return self._refuse(403, "forbidden: open the address `placemat studio` printed")
            path = url.path
            if path == "/":
                return self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
            if path == "/events":
                return self._events()
            if path.startswith("/resolve/"):
                rec = studio.record(_int(path[len("/resolve/"):]))
                if rec is None:
                    return self._refuse(404, "no such resolve (the last %d are kept)" % studio.keep)
                return self._json({"id": rec.id, "doc": rec.doc, "texts": rec.texts, "changed": rec.changed,
                                   "timing": rec.timing, "reused": rec.reused, "notes": rec.notes})
            if path == "/diff":
                a, b = studio.record(_int(query.get("a", [""])[0])), studio.record(_int(query.get("b", [""])[0]))
                if a is None or b is None:
                    return self._refuse(404, "no such resolve (the last %d are kept)" % studio.keep)
                return self._json(studio.compare(a, b))
            if path == "/history":
                return self._json([r.summary() for r in studio.history])
            return self._refuse(404, "not found")

        def _no(self):
            self._refuse(405, "this server only answers GET")

        do_POST = do_PUT = do_DELETE = do_PATCH = _no

        def _send(self, code, ctype, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, doc):
            self._send(200, "application/json", json.dumps(doc, separators=(",", ":")).encode())

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            q = studio.hub.subscribe(studio.hello)
            last = time.monotonic()
            try:
                while not studio._stopping.is_set():
                    try:
                        name, text = q.get(timeout=1.0)
                    except queue.Empty:
                        if time.monotonic() - last >= KEEPALIVE_S:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            last = time.monotonic()
                        continue
                    self.wfile.write(("event: %s\ndata: %s\n\n" % (name, text)).encode())
                    self.wfile.flush()
                    last = time.monotonic()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                studio.hub.unsubscribe(q)

    return Handler


def _int(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return -1


# ------------------------------------------------------------------ command
def run(script, port: int | None = None, open_browser: bool | None = None) -> int:
    try:
        studio = Studio(script, port=port, open_browser=open_browser)
    except ValueError as e:
        console.say("studio", str(e), level="fail")
        return 2
    url = studio.start()
    console.say("studio", "watching %s" % studio.script.name)
    console.say("studio", url)
    if studio.open_browser:
        import webbrowser
        webbrowser.open(url)
    import signal
    signal.signal(signal.SIGTERM, lambda *a: studio._stopping.set())      # stopped like Ctrl-C: the worker goes too
    try:
        studio.wait()
    except KeyboardInterrupt:
        pass
    finally:
        studio.stop()
    return 0
