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

The last `keep` resolves are kept so the page can compare any two (`/diff`).

The page lists the project's layout scripts (files that call `board.` at module
level and that the runner can run) and POST /switch makes the studio watch
another of them: only a layout script under the project root is accepted."""
from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass, field
import hmac
import http.server
import json
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

from . import channel
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
        self.log_start = 0                      # where this process's lines begin in the log (it is appended to)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        self.serial += 1
        serial = self.serial
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_start = self.log_path.stat().st_size if self.log_path.exists() else 0
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

    def log_text(self) -> str:
        """What this process wrote to the log."""
        try:
            with open(self.log_path, "rb") as f:
                f.seek(self.log_start)
                return f.read().decode(errors="replace")
        except OSError:
            return ""

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


_SKIP_DIRS = {".git", ".placemat", "__pycache__", "node_modules", ".venv", "venv", "generated"}
_SCAN_LIMIT = 20000         # files looked at when listing the layout scripts


def project_root(board_dir) -> Path:
    """The project a board belongs to: the folder of the outermost placemat.toml above it (what settings and script
    imports treat as the root), else the workspace pcb.toml's, else the board's own folder."""
    from .settings import _files
    board_dir = Path(board_dir).resolve()
    found = _files(board_dir)
    if found:
        return found[0].parent.resolve()
    d = board_dir
    while True:
        pt = d / "pcb.toml"
        if pt.is_file() and "[workspace]" in pt.read_text(errors="replace"):
            return d
        if d.parent == d:
            return board_dir
        d = d.parent


def _module_level(node):
    """The nodes that run when a module loads: everything but the bodies of functions, classes and lambdas."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from _module_level(child)


def declares_board(path) -> bool:
    """Whether a Python file lays a board out: it calls `board.<something>(...)` as it loads, which a helper module
    of functions does not. Not the file's name."""
    try:
        text = Path(path).read_text(errors="replace")
        if "board." not in text:
            return False
        tree = ast.parse(text)
    except (SyntaxError, ValueError, OSError):
        return False
    for node in _module_level(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "board":
            return True
    return False


def script_titles(path, src) -> tuple:
    """(title, subtitle) of a layout script: the name placemat knows the board or module by (the .zen's name), and
    the first line of the script's docstring, without a leading "<name>:"; the folder's name when there is no name."""
    title = src.name or src.board_dir.name
    sub = ""
    try:
        doc = ast.get_docstring(ast.parse(Path(path).read_text(errors="replace")))
    except (SyntaxError, ValueError, OSError):
        doc = None
    if doc and doc.strip():
        sub = doc.strip().splitlines()[0].strip()
        m = re.match(r"%s\s*[:\-]\s*(.*)" % re.escape(title), sub, re.I)
        if m:
            sub = m.group(1).strip()
    return title, sub


def layout_scripts(root) -> list:
    """The layout scripts under a project root, sorted: Python files that declare a board and that find_board can
    resolve (so `placemat run` can run them)."""
    from .project import find_board
    root, out, seen = Path(root), [], 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            seen += 1
            if seen > _SCAN_LIMIT:
                return out
            if not name.endswith(".py"):
                continue
            path = Path(folder, name)
            if not declares_board(path):
                continue
            try:
                src = find_board(path)
            except (FileNotFoundError, ValueError, OSError):
                continue
            out.append((path.resolve(), src))
    return out


_FATAL = re.compile(r"^Fatal Python error: (.*)$", re.M)
_FRAME = re.compile(r'^\s+File "(.*)", line (\d+) in (.*)$')


def parse_fatal(text: str):
    """The last fatal error faulthandler wrote in `text`: {"what": "Segmentation fault", "frames": [(file, line,
    function), ...]} with the innermost frame first, or None. Frames are those of the current thread, else the first
    thread listed."""
    last = None
    for last in _FATAL.finditer(text):
        pass
    if last is None:
        return None
    blocks, cur = [], None                  # (is_current, frames) for each thread listed
    for line in text[last.end():].splitlines():
        head = re.match(r"^(Current thread|Thread) .*\(most recent call first\):", line)
        if head:
            cur = (head.group(1) == "Current thread", [])
            blocks.append(cur)
            continue
        m = _FRAME.match(line)
        if cur is not None and m:
            cur[1].append((m.group(1), int(m.group(2)), m.group(3)))
        elif cur is not None and not line.strip() and cur[1]:
            cur = None
    chosen = next((b for b in blocks if b[0]), blocks[0] if blocks else (False, []))
    frames = chosen[1]
    return {"what": last.group(1).strip(), "frames": frames}


def _source_line(frame) -> str | None:
    try:
        return Path(frame[0]).read_text(errors="replace").splitlines()[frame[1] - 1].strip()
    except (OSError, IndexError):
        return None


class Studio:
    def __init__(self, script=None, port: int | None = None, open_browser: bool | None = None, host: str = "127.0.0.1",
                 root=None, **settings):
        """Watch `script`; with none, the studio is a picker over the layout scripts found under `root` (default the
        current directory's project) and watches nothing until one is chosen."""
        self.host = host            # the address listened on: 127.0.0.1 unless --host widens it
        from . import settings as settings_mod
        from .project import find_board
        self._scripts = None
        if script is None:
            self.root = project_root(Path(root) if root else Path.cwd())
            found = layout_scripts(self.root)
            if not found:
                raise ValueError("no layout scripts found under %s (a layout script is a Python file that calls board.<...> "
                                 "as it loads, beside its board's .zen)" % self.root)
            self.script, self.src = None, None
            self._scripts = self._entries(found)
            cfg = settings_mod.load(self.root)
        else:
            self.script = Path(script).resolve()
            if not self.script.is_file():
                raise ValueError("%s is not a file" % script)
            self.src = find_board(self.script)
            self.root = project_root(self.src.board_dir)
            cfg = settings_mod.load(self.src.board_dir, script=self.script)
        self.cfg = cfg
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
        self._initial = self.script is not None
        self._error = None
        self._fresh_next = False                # the next resolve replays nothing from an earlier one
        self.cmds: dict = {}                    # the commands of the project that report over the channel, by connection id
        self.watcher = None
        self._run = None                        # the checked run in progress: {"id", "lines"}
        self._run_cache: dict = {}              # run.json path -> (mtime, summary)
        self.worker = WorkerProcess(self._on_worker, self._views() / "worker.log")

    def _views(self) -> Path:
        return (self.src.board_dir if self.src else self.root) / ".placemat" / "views" / "studio"

    # ------------------------------------------------------------ the layout scripts
    def _entries(self, found) -> list:
        return [{"id": Path(os.path.relpath(p, self.root)).as_posix(), "path": p, "src": s} for p, s in sorted(found, key=lambda x: str(x[0]))]

    def scripts(self) -> list:
        """The project's layout scripts as the page lists them, scanned once and kept."""
        if self._scripts is None:
            found = layout_scripts(self.root)
            with self.lock:
                if self.script is not None and self.script not in {p for p, _ in found}:
                    found.append((self.script, self.src))
                self._scripts = self._entries(found)
        return self._scripts

    def _scan_scripts(self) -> None:
        """The listing, made off the request threads and sent to the pages when it is ready."""
        try:
            self.scripts()
        except Exception as e:                  # a project the scan cannot read leaves the list at the current script
            print("studio: listing the layout scripts: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            return
        with self.lock:
            self.hub.emit("scripts", {"scripts": self.script_list()})

    def script_list(self) -> list:
        out = []
        for s in self._scripts or ([{"id": self.script.name, "path": self.script, "src": self.src}] if self.script else []):
            title, sub = script_titles(s["path"], s["src"])
            out.append({"id": s["id"], "title": title, "subtitle": sub, "current": s["path"] == self.script})
        return out

    def switch(self, rel: str) -> None:
        """Watch and resolve another layout script of the project. Only one the listing offers is accepted."""
        from .project import find_board
        target = next((s for s in self.scripts() if s["id"] == rel), None)
        if target is None:
            raise ValueError("%s is not a layout script of this project" % rel)
        with self.lock:
            if target["path"] == self.script:
                return
            self.worker.kill()                  # whatever it was resolving is of the old script
            self.script, self.src = target["path"], find_board(target["path"])
            from . import settings as settings_mod
            self.cfg = settings_mod.load(self.src.board_dir, script=self.script)
            self.worker.log_path = self._views() / "worker.log"
            self.history.clear()
            self._run_cache.clear()
            self._cur, self._cancel_at, self._error, self._dirty = None, None, None, False
            self.debounce.stopped()
            self.hub.log.clear()
            self._files = self.watched()
            self._poller = Poller(lambda: self._files)
            self._initial = True                # the next tick resolves it
            self.hub.emit("switched", self._hello_data())

    # ------------------------------------------------------------ files
    def name_of(self, path) -> str:
        return os.path.relpath(path, self.script.parent if self.script else self.root)

    def watched(self) -> list:
        """What a resolve depends on: the script and what it imports, its lock
        and routes, every placemat.toml above the board, the fab profile and
        the cached generation."""
        from .project import fab_profile, script_files
        from .runner import cached_generation
        from .settings import _files
        if self.script is None:
            return []
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

    def allowed_hosts(self) -> set:
        """The Host headers a request may carry: localhost always, and with --host the address listened on and,
        listening on all addresses, this machine's own names and LAN addresses (the token still guards every
        request)."""
        hosts = {"127.0.0.1", "localhost"}
        if self.host not in ("127.0.0.1", "localhost"):
            hosts |= {self.host} | _own_addresses()
        return {"%s:%d" % (h.lower(), self.port) for h in hosts}

    # ------------------------------------------------------------ lifecycle
    def start(self) -> str:
        handler = _handler(self)
        self.server = http.server.ThreadingHTTPServer((self.host, self.port), handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = "http://%s:%d/?t=%s" % (_url_host(self.host), self.port, self.token)
        self._files = self.watched()
        self._poller = Poller(lambda: self._files)
        self.watcher = channel.Watcher(self.root, self._on_channel, self._on_dead)
        self.watcher.start()
        for target in (self.server.serve_forever, self._watch, self._scan_scripts):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)
        return self.url

    def stop(self) -> None:
        self._stopping.set()
        if self.watcher is not None:
            self.watcher.stop()
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
        if self.script is None:
            return                              # a picker: nothing is watched until a script is chosen
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
            self._cur = {"id": rid, "texts": texts, "changed": changed, "t0": time.monotonic(), "at": time.time(),
                         "total": None, "now": None, "replayed": 0}
            self._dirty, self._cancel_at = False, None
            self.debounce.started()
            self.hub.log.clear()
            self.hub.emit("started", {"id": rid, "script": self.script.name, "at": time.time(), "texts": texts,
                                      "changed": changed, "stale_files": sorted(self.name_of(p) for p in changed_paths)},
                          keep=True)
            fresh, self._fresh_next = self._fresh_next, False
            if not self.worker.send({"cmd": "resolve", "id": rid, "script": str(self.script), "fresh": fresh}):
                self._fail(rid, "the resolve worker could not be started")

    def resolve_now(self, fresh: bool = False) -> dict:
        """Cancel a resolve in progress and start a new one now, without a file having changed. `fresh` resolves every step
        again instead of replaying those an earlier resolve did the same."""
        with self.lock:
            if self.script is None:
                raise ValueError("choose a layout script first")
            now = time.monotonic()
            self._fresh_next = bool(fresh)
            self.debounce.changed(now, {self.script})
            self.debounce.expedite()
            self._dirty = True                  # what finishes while this is asked for is not shown as current
            if self._cur is not None and self._cancel_at is None:
                self._cancel_at = now
                self.worker.send({"cmd": "cancel", "id": self._cur["id"]})
        return {"fresh": bool(fresh)}

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
                if cur is not None and not self._stopping.is_set():
                    self._fail(cur["id"], **self.worker_death(ev.get("code")))
                return
            if cur is None or ev.get("id") != cur["id"]:
                return
            for key, value in (("now", None), ("total", None), ("replayed", 0)):
                cur.setdefault(key, value)
            rid = cur["id"]
            if kind == "board":
                self.hub.emit("board", {k: v for k, v in ev.items() if k not in ("ev", "id")} | {"id": rid}, keep=True)
            elif kind == "item":
                cur["last"] = ev["item"].get("key")
                if cur["now"] is not None and cur["now"].get("replaying"):
                    cur["replayed"] += 1
                cur["now"] = None
                self.hub.emit("step", {"id": rid, "item": self._named(ev["item"]), **{k: ev[k] for k in ("ops", "cutout") if k in ev}}, keep=True)
            elif kind == "begin":
                info = {k: v for k, v in ev.items() if k != "ev"} | {"at": time.time()}        # when, by the server's clock
                if info["kind"] == "total":
                    cur["total"] = info
                elif info["kind"] == "begin":
                    cur["now"] = dict(info, phase="")
                elif cur["now"] is not None:
                    cur["now"]["phase"] = info.get("text", "")
                    if info.get("hint"):
                        cur["now"]["hint"] = info["hint"]
                # the queue's size is kept for a page that joins part-way; what an item is doing is transient
                self.hub.emit("begin", info, keep=info["kind"] == "total")
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

    def worker_death(self, code) -> dict:
        """The `error` fields for a worker that died with exit `code`: a signal by name, and for a crash the Python
        traceback faulthandler left in the log, as the innermost frame of the user's own files (file, line, source
        line) with the last frames inside placemat as the detail."""
        sig = None
        if isinstance(code, int) and code < 0:
            try:
                sig = signal.Signals(-code).name
            except ValueError:
                sig = "signal %d" % -code
        fatal = parse_fatal(self.worker.log_text())
        if fatal is None:
            if sig in ("SIGTERM", "SIGKILL", "SIGINT", "SIGHUP"):
                return {"message": "the resolve worker was stopped by %s from outside the studio; the next change resolves again" % sig}
            if sig:
                return {"message": "the resolve worker was stopped by %s%s" % (sig, self._last_step_note())}
            return {"message": "the resolve worker exited (code %s) without an error%s" % (code, self._last_step_note())}
        mine = self.user_frame(fatal["frames"])
        message = "the resolve worker crashed: %s%s%s" % (fatal["what"], " (%s)" % sig if sig else "", self._last_step_note())
        extra = {"file": self.name_of(mine[0]) if mine else "", "line": mine[1] if mine else None, "source": _source_line(mine) if mine else None}
        extra["detail"] = "\n".join('  File "%s", line %d in %s' % f for f in fatal["frames"][:12])
        return {"message": message, **extra}

    def _last_step_note(self) -> str:
        """What the worker last reported before it was lost: the item it was working on, and the last it settled. A lost
        connection and these are the crash report; the traceback is detail where there is one."""
        c = self._cur or {}
        now, last = (c.get("now") or {}).get("item"), c.get("last")
        bits = (["while working on %s" % now] if now else []) + (["the last step it settled was %s" % last] if last else [])
        return (" " + ", ".join(bits)) if bits else ""

    def user_frame(self, frames):
        """The innermost of `frames` ((file, line, function), innermost first) that is in the script or a module it
        imports, else in the project but not placemat's or the environment's own."""
        mine = {str(Path(f).resolve()) for f in self.watched() if str(f).endswith(".py")}
        for f in frames:
            p = str(Path(f[0]).resolve()) if f[0].startswith("/") else f[0]
            if p in mine:
                return f
        own = str(Path(__file__).resolve().parent)
        for f in frames:
            p = f[0]
            if p.startswith(str(self.root)) and not p.startswith(own) and "site-packages" not in p and ".venv" not in p:
                return f
        return None

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
                       "reservations": doc["reservations"], "layers": doc["layers"]}, keep=True)
        emit("finished", {"id": rid, "counts": doc["counts"], "timing": rec.timing, "reused": rec.reused, "notes": rec.notes,
                          "score": doc.get("score"), "history": [r.summary() for r in self.history]}, keep=True)
        if previous is not None:
            emit("compare", self.compare(previous, rec), keep=True)
        self.hub.log.clear()                    # a page that connects now is given the whole of it by hello()

    # ------------------------------------------------------------ the live channel
    MAX_EVENTS = 6000                           # kept for a command: what a page opening it late is given
    MAX_CMDS = 30

    @staticmethod
    def _cmd_summary(c: dict) -> dict:
        return {k: c.get(k) for k in ("id", "pid", "command", "script", "args", "started", "state", "message", "record", "last", "items",
                                      "variants", "ended", "own_run", "best", "baseline", "kept", "resolves", "truncated")}

    def commands(self) -> list:
        with self.lock:
            return [self._cmd_summary(c) for c in self.cmds.values()]

    def _rel(self, c: dict, text):
        """A file an event names, as the page names files: relative to the script's folder."""
        if not text or not c.get("script"):
            return text
        try:
            return os.path.relpath(text, Path(c["script"]).parent)
        except ValueError:
            return text

    def _on_channel(self, cid: int, ev: dict) -> None:
        """An event from a command reporting over the socket (any thread)."""
        kind = ev.get("ev")
        with self.lock:
            c = self.cmds.get(cid)
            if kind == "hello":
                run = self._run
                c = {"id": cid, "pid": ev.get("pid"), "command": ev.get("command", ""), "script": ev.get("script", ""), "args": ev.get("args", []),
                     "started": time.time(), "state": "running", "items": 0, "variants": 0, "resolves": 0, "log": [], "plan": None, "explore": None,
                     "own_run": run["id"] if run is not None and run.get("pid") == ev.get("pid") else None}
                self.cmds[cid] = c
                for old in [k for k, v in self.cmds.items() if v["state"] != "running"][:-self.MAX_CMDS]:
                    del self.cmds[old]
                self.hub.emit("cmd", self._cmd_summary(c))
                return
            if c is None:
                return
            if kind == "lost":
                if c["state"] == "running":
                    c.update(state="lost", ended=time.time(), message="the command stopped without saying it was done" +
                             ((" (the last step it reported: %s)" % c["last"]) if c.get("last") else ""))
                self.hub.emit("cmd", self._cmd_summary(c))
                return
            if kind == "item":
                it = ev.get("item") or {}
                if it.get("file"):
                    it["file"] = self._rel(c, it["file"])
                c["last"] = it.get("key") or c.get("last")
                c["items"] += 1
            elif kind == "resolve":
                c["resolves"] = ev.get("n", c["resolves"] + 1)
                c["plan"] = None
            elif kind == "plan":
                doc = ev.get("doc") or {}
                for it in doc.get("items", ()):
                    if it.get("file"):
                        it["file"] = self._rel(c, it["file"])
                c["plan"] = ev
            elif kind == "explore":
                c["explore"] = {"start": ev, "variants": [], "done": None}
            elif kind == "variant":
                c["variants"] += 1
                if c["explore"] is not None:
                    c["explore"]["variants"].append(ev)
                    c["best"] = min([c.get("best") if c.get("best") is not None else ev["score"], ev["score"]])
            elif kind == "explore_done":
                if c["explore"] is not None:
                    c["explore"]["done"] = ev
                c["best"], c["baseline"], c["kept"] = ev.get("best"), ev.get("baseline"), ev.get("kept")
                if ev.get("record"):
                    c["record"] = ev["record"]
            elif kind == "done":
                c.update(state="done", ended=time.time(), record=ev.get("record") or c.get("record"))
            elif kind == "error":
                c.update(state="error", ended=time.time(), message=ev.get("message", ""), error=ev)
            if kind in ("explore", "variant", "explore_done"):
                pass
            n = len(c["log"])
            if kind not in ("plan", "explore", "variant", "explore_done"):
                if n < self.MAX_EVENTS:
                    c["log"].append(ev)
                else:
                    c["truncated"] = True
            self.hub.emit("cmdev", {"id": cid, "n": n, "ev": ev})
            if kind in ("done", "error"):
                self.hub.emit("cmd", self._cmd_summary(c))
                if c.get("own_run") is not None and kind == "error":
                    self._run_note = ev.get("message", "")
            elif c.get("own_run") is not None and kind in ("item", "begin"):
                self.hub.emit("run_progress", {"id": c["own_run"], "item": c.get("last") or "", "n": c["items"]})

    def _on_dead(self, cid: int, entry: dict, events: list) -> None:
        """A command found dead (its pid gone, its entry left behind): shown with the last state in its progress file."""
        done = next((e for e in reversed(events) if e.get("ev") in ("done", "error")), None)
        items = [e for e in events if e.get("ev") == "item"]
        last = items[-1].get("key") if items else None
        c = {"id": cid, "pid": entry.get("pid"), "command": entry.get("command", ""), "script": entry.get("script", ""),
             "args": entry.get("args", []), "started": entry.get("started") or time.time(), "ended": time.time(), "items": len(items),
             "variants": sum(1 for e in events if e.get("ev") == "variant"), "resolves": sum(1 for e in events if e.get("ev") == "resolve"),
             "log": [], "plan": None, "explore": None, "last": last, "own_run": None}
        if done is not None and done.get("ev") == "done":
            c.update(state="done", record=done.get("record"))
        elif done is not None:
            c.update(state="error", message=done.get("message", ""))
        else:
            c.update(state="lost", message="the command stopped without saying it was done" +
                     ((" (the last step it reported: %s)" % last) if last else ""))
        with self.lock:
            self.cmds[cid] = c
        self.hub.emit("cmd", self._cmd_summary(c))

    def cmd_detail(self, cid: int):
        """A command's events so far, its latest plan and, for an explore, its variants: what a page that opens it is given."""
        with self.lock:
            c = self.cmds.get(cid)
            if c is None:
                return None
            return {"summary": self._cmd_summary(c), "events": list(c["log"]), "plan": c["plan"], "explore": c["explore"]}

    def explores(self, limit: int = 20) -> list:
        """The recorded explores of the project's boards (their result files), newest first, as the page lists them."""
        dirs = set()
        if self.src is not None:
            dirs.add(self.src.board_dir / ".placemat" / "views" / "explore")
        with self.lock:
            for c in self.cmds.values():
                if c.get("record") and "views" in c["record"] and "explore" in c["record"]:
                    dirs.add(Path(c["record"]).parent)
        out = []
        for d in dirs:
            try:
                files = [f for f in d.glob("*.json")]
            except OSError:
                continue
            for f in files:
                try:
                    doc = json.loads(f.read_text())
                except (OSError, ValueError):
                    continue
                if doc.get("version") != 1:
                    continue
                out.append({"file": str(f), "script": doc.get("script", ""), "at": doc.get("at"), "pid": doc.get("pid"), "tried": len(doc.get("variants", ())),
                            "best": doc.get("best"), "baseline": doc.get("baseline"), "kept": doc.get("kept"), "focus": len(doc.get("focus", ()))})
        out.sort(key=lambda e: -(e["at"] or 0))
        return out[:limit]

    def explore_record(self, path: str):
        """One explore's result file, if it is one of this project's."""
        p = Path(path).resolve()
        if p.suffix != ".json" or p.parent.name != "explore" or p.parent.parent.name != "views":
            return None
        try:
            if self.root.resolve() not in p.parents:
                return None
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------ checked runs
    def runs_dir(self) -> Path:
        return self.src.board_dir / ".placemat" / "runs"

    def run_summary(self, run_json: Path) -> dict | None:
        """One recorded run, as the page lists it: status, score, DRC by kind, the checks, the findings by severity and
        the failure's line when it failed. Kept by modification time, so a listing re-reads only what changed."""
        from .report import RunRecord
        try:
            mtime = run_json.stat().st_mtime
        except OSError:
            return None
        hit = self._run_cache.get(run_json)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        try:
            rec = RunRecord.load(run_json)
        except (OSError, ValueError, TypeError, KeyError):
            return None
        m = rec.metrics or {}
        score = None
        if "measures" in m:
            from . import score as score_mod
            try:
                score = round(score_mod.total(m["measures"], self.cfg), 3)
            except Exception:
                score = None
        sev: dict = {}
        for d in rec.findings_with_severity():
            sev[d["severity"]] = sev.get(d["severity"], 0) + 1
        fail = rec.failure or None
        out = {"id": run_json.parent.name, "run_id": rec.run_id, "label": rec.paths.get("label", "") if isinstance(rec.paths, dict) else "", "status": rec.status, "at": mtime,
               "board": rec.board, "script": rec.paths.get("script", "") if isinstance(rec.paths, dict) else "",
               "score": score, "findings": len(rec.findings), "severities": sev,
               "drc": {k: m.get(k) for k in ("drc_real", "outstanding", "other", "permitted", "unconnected") if k in m},
               "airwire_mm": m.get("airwire_mm"), "open_nets": len(m.get("open_nets") or {}),
               "checks": {k: m.get(k) for k in ("checks_failed", "checks_unjudged", "checks_accepted") if k in m},
               "verdicts": [{"check": v.get("check"), "subject": v.get("subject"), "ok": v.get("ok"), "note": v.get("note", "")}
                            for v in (rec.verdicts or []) if v.get("ok") is False][:20],
               "timing": rec.timing_s,
               "failure": {"message": fail.get("message", ""), "file": fail.get("script", ""), "line": fail.get("line"), "source": fail.get("source")} if fail else None}
        self._run_cache[run_json] = (mtime, out)
        return out

    def runs(self, limit: int = 40) -> list:
        """The recorded runs of the script being watched, newest first."""
        if self.src is None:
            return []
        out = []
        try:
            dirs = sorted((d for d in self.runs_dir().iterdir() if (d / "run.json").is_file()), key=lambda d: -(d / "run.json").stat().st_mtime)
        except OSError:
            return []
        for d in dirs:
            s = self.run_summary(d / "run.json")
            if s is None or (s["script"] and Path(s["script"]).resolve() != self.script):
                continue
            out.append(s)
            if len(out) >= limit:
                break
        return out

    def _run_state(self):
        with self.lock:
            r = self._run
            return None if r is None else {"id": r["id"], "lines": r["lines"][-40:], "t0": r["t0"]}

    def start_run(self) -> dict:
        """A checked run of the script (`placemat run --no-render`: the design checks, KiCad's DRC and the score, a run
        record), started on a thread; its progress and result go to the pages as `run_line` and `run_done`."""
        with self.lock:
            if self.script is None:
                raise ValueError("choose a layout script first")
            if self._run is not None:
                raise ValueError("a run is already in progress")
            self._next_run = getattr(self, "_next_run", 0) + 1
            self._run = {"id": self._next_run, "lines": [], "t0": time.time()}
            rid = self._run["id"]
        threading.Thread(target=self._do_run, args=(rid,), daemon=True).start()
        return {"id": rid}

    def _do_run(self, rid: int) -> None:
        t0 = time.time()
        cmd = [sys.executable, "-m", "placemat", "run", str(self.script), "--no-render"]
        code, tail = None, []
        try:
            # the run is a command like any other: it reports over the channel (its steps reach the page as the command's
            # events), and what it leaves is its record. Its printed text is not read.
            proc = subprocess.Popen(cmd, cwd=str(self.src.board_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._run_proc = proc
            with self.lock:
                if self._run is not None:
                    self._run["pid"] = proc.pid
                for c in self.cmds.values():
                    if c.get("pid") == proc.pid:
                        c["own_run"] = rid
            self.hub.emit("run_started", {"id": rid, "at": t0, "pid": proc.pid})
            code = proc.wait()
        except OSError as e:
            tail.append("could not start the run: %s" % e)
        newest = None
        for r in self.runs(limit=5):
            if r["at"] >= t0 - 1:
                newest = r
                break
        with self.lock:
            self._run = None
            note = next((c.get("message") for c in self.cmds.values() if c.get("own_run") == rid and c.get("message")), "")
        if note:
            tail.append(note)
        self.hub.emit("run_done", {"id": rid, "code": code, "run": newest, "tail": tail[-25:], "runs": self.runs()})

    def run_doc(self, run_id: str) -> dict | None:
        """A recorded run as a plan document for the compare: its placements as items, its findings and score."""
        from .report import RunRecord
        path = self.runs_dir() / run_id / "run.json"
        if not path.is_file():
            return None
        rec = RunRecord.load(path)
        summary = self.run_summary(path) or {}
        items = [{"key": k, "at": [v["x"], v["y"]], "rotation": v["rotation"], "face": v["face"]} for k, v in rec.placements.items()]
        findings = [{"text": d["text"], "kind": d.get("kind", ""), "severity": d.get("severity", "warning"), "at": None, "item": ""}
                    for d in rec.findings_with_severity()]
        return {"items": items, "findings": findings, "unplaced": [], "score": {"total": summary["score"]} if summary.get("score") is not None else None}

    def compare_run(self, run_id: str) -> dict | None:
        """The newest resolve against a recorded run: what moved, was added or removed among the items the run placed,
        the findings gained and lost and the score. A run records no copper or links, so those are not compared."""
        from .studio_diff import _findings, _texts
        from collections import Counter
        with self.lock:
            b = self.history[-1] if self.history else None
        a = self.run_doc(run_id)
        if a is None or b is None:
            return None
        d = diff_plans(a, b.doc, partial=True)
        ia = {i["key"] for i in a["items"]}
        for it in b.doc.get("items", ()):
            if it["key"] not in ia and it.get("placed"):
                d["added"].append({"key": it["key"], "at": it.get("at"), "rotation": it.get("rotation"), "face": it.get("face"),
                                   "file": it.get("file", ""), "line": it.get("line", 0), "was_unplaced": False})
        ib = {i["key"] for i in b.doc.get("items", ())}
        for it in a["items"]:
            if it["key"] not in ib:
                d["removed"].append({**it, "file": "", "line": 0, "now_unplaced": False})
        ta, tb = _texts(a), _texts(b.doc)
        d["findings"] = {"gained": _findings(b.doc, tb - ta), "lost": _findings(a, ta - tb)}
        sa, sb = a.get("score"), b.doc.get("score")
        if sa and sb and "total" in sa and "total" in sb:
            d["score"] = {"a": sa["total"], "b": sb["total"], "delta": round(sb["total"] - sa["total"], 3)}
        d["empty"] = not (d["moved"] or d["added"] or d["removed"] or d["findings"]["gained"] or d["findings"]["lost"]
                          or d["score"] and d["score"]["delta"])
        return {"a": "run " + run_id, "b": b.id, "diff": d, "files": {}, "trace": {"items": {}, "lines": {}}, "run": run_id}

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

    def origin(self) -> str | None:
        """The address another device reaches this studio at, without the token: None while it listens on 127.0.0.1 only."""
        if self.host in ("127.0.0.1", "localhost"):
            return None
        return "http://%s:%d" % (_url_host(self.host), self.port)

    def _work_state(self):
        """The resolve in progress as a page that joins late needs it: when it began, the queue, the item under way, by
        the server's clock, so the time shown is the time since the resolve began and not since the page did."""
        c = self._cur
        if c is None:
            return None
        return {"t0": c.get("at", time.time()), "total": c.get("total"), "cur": c.get("now"), "replayed": c.get("replayed", 0)}

    def _hello_data(self) -> dict:
        common = {"now": time.time(), "origin": self.origin(), "port": self.port, "commands": [self._cmd_summary(c) for c in self.cmds.values()],
                  "explores": self.explores(), "explore_fps": self.cfg.studio_explore_fps}
        if self.script is None:
            return {**common, "script": "", "picker": True, "root": str(self.root), "keep": self.keep, "title": "", "subtitle": "",
                    "scripts": self.script_list(), "history": [], "resolving": None, "error": None, "runs": [], "run": None}
        title, sub = script_titles(self.script, self.src)
        return {**common, "work": self._work_state(), "script": self.script.name, "keep": self.keep, "title": title, "subtitle": sub,
                "scripts": self.script_list(), "history": [r.summary() for r in self.history],
                "resolving": self._cur["id"] if self._cur else None, "error": self._error,
                "runs": self.runs(), "run": self._run_state()}

    def hello(self) -> list:
        """What a page that connects now is told before the live stream: the
        studio's state, and the latest finished resolve whole."""
        with self.lock:
            out = [("hello", json.dumps(self._hello_data(), separators=(",", ":")))]
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
            if host not in studio.allowed_hosts():
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
            if path == "/qr":
                u = query.get("u", [""])[0]
                own = [o for o in (studio.origin(), "http://127.0.0.1:%d" % studio.port) if o]
                if len(u) > 1000 or not any(u.startswith(o + "/") for o in own):
                    return self._refuse(400, "only an address of this studio can be drawn")
                try:
                    from . import qr
                    return self._send(200, "image/svg+xml", qr.to_svg(qr.encode(u)).encode())
                except ValueError as e:
                    return self._refuse(400, str(e))
            if path.startswith("/cmd/"):
                d = studio.cmd_detail(_int(path[len("/cmd/"):]))
                return self._json(d) if d is not None else self._refuse(404, "no such command")
            if path == "/explore":
                doc = studio.explore_record(query.get("f", [""])[0])
                return self._json(doc) if doc is not None else self._refuse(404, "no such explore record")
            if path == "/runs":
                return self._json(studio.runs())
            if path == "/runcompare":
                out = studio.compare_run(query.get("run", [""])[0])
                if out is None:
                    return self._refuse(404, "no such run, or no resolve yet to compare it with")
                return self._json(out)
            return self._refuse(404, "not found")

        def _no(self):
            self._refuse(405, "this server only answers GET")

        def do_POST(self):
            """/switch, with the token: it changes which layout script is watched; and /run, a checked run of it."""
            url = urlparse(self.path)
            if url.path not in ("/switch", "/run", "/resolve"):
                return self._no()
            if not self._allowed(parse_qs(url.query)):
                return self._refuse(403, "forbidden: open the address `placemat studio` printed")
            if url.path == "/run":
                try:
                    return self._json(studio.start_run())
                except ValueError as e:
                    return self._refuse(409, str(e))
            if url.path == "/resolve":
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4096)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    return self._json(studio.resolve_now(bool(body.get("fresh"))))
                except (ValueError, TypeError) as e:
                    return self._refuse(409, str(e))
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 4096)
                body = json.loads(self.rfile.read(n) or b"{}")
                studio.switch(str(body.get("script", "")))
            except (ValueError, FileNotFoundError, TypeError) as e:
                return self._refuse(400, str(e))
            return self._json({"ok": True})

        do_PUT = do_DELETE = do_PATCH = _no

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
def _own_addresses() -> set:
    """This machine's host name and the addresses it is reached on."""
    import socket
    names = {socket.gethostname(), socket.getfqdn()}
    try:
        names |= set(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("192.0.2.1", 9))      # no packet is sent: this only picks the outward interface
            names.add(sk.getsockname()[0])
    except OSError:
        pass
    return {n.lower() for n in names if n}


def _url_host(host: str) -> str:
    """The address to print for a listening address: the LAN address when listening on all of them."""
    if host in ("0.0.0.0", ""):
        own = sorted(a for a in _own_addresses() if a[:1].isdigit() and not a.startswith("127."))
        return own[0] if own else "127.0.0.1"
    return host


def _in_use(port: int, host: str) -> str:
    """What to say when the port is taken: by another studio, when it answers as one."""
    import http.client
    who = ""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/")
        r = conn.getresponse()
        if "placemat-studio" in (r.getheader("Server") or ""):
            who = ": another studio is running at http://%s:%d/ (its address with the token was printed when it started)" % (_url_host(host), port)
        conn.close()
    except OSError:
        pass
    return "port %d is in use%s; use --port to choose another" % (port, who or ": another program, or another studio, may be using it")


def run(script=None, port: int | None = None, open_browser: bool | None = None, host: str = "127.0.0.1") -> int:
    try:
        studio = Studio(script, port=port, open_browser=open_browser, host=host)
    except (ValueError, FileNotFoundError) as e:
        console.say("studio", str(e), level="fail")
        return 2
    try:
        url = studio.start()
    except OSError as e:
        if e.errno not in (98, 48, 10048):          # address already in use, on Linux, macOS and Windows
            raise
        console.say("studio", _in_use(studio.port, host), level="fail")
        return 2
    console.say("studio", "watching %s" % studio.script.name if studio.script else
                "%d layout scripts under %s: choose one in the page" % (len(studio.scripts()), studio.root))
    console.say("studio", url)
    if studio.origin() is not None:                 # listening for another device: the first open there is a scan
        from . import qr
        try:
            console.data(qr.to_terminal(qr.encode(url)))
        except ValueError:
            pass
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
