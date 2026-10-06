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

from . import channel, present
from .childenv import child_env
from .console import console
from .studio_diff import diff_plans, line_diff, trace, unified_diff, with_spans
from .studio_watch import Debounce, Poller

KEEPALIVE_S = 15.0         # a comment on an idle stream, so a proxy or a browser does not drop it
PAGE = Path(__file__).with_name("studio_page.html")
BUILDER_JS = Path(__file__).with_name("studio_builder.js")


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
    stale: dict | None = None                   # why the cached generation is out of date (runner.stale_record), None when it is not
    applied: str = ""                           # the suggestion whose edit this resolve followed ("applied from a suggestion: ...")

    def summary(self) -> dict:
        return {"id": self.id, "at": self.at, "changed": [c["file"] for c in self.changed], "timing": self.timing,
                "counts": self.doc["counts"], "score": (self.doc.get("score") or {}).get("total"), "reused": self.reused,
                "applied": self.applied}


@dataclass(frozen=True)
class PastView:
    """A view the page shows in place of a resolve of this studio, whose suggestion is acted on: `kind` and `ref` as the page names it
    ("run" and its id, "build" and the run's id, "route" and its record, "explore" and its record, "cmd" and the command's id), `noun`
    what the refusals call it, `script` the layout script it is of ("" when it does not say), `running` whether it is a command
    still running (its plan is not its last: Try, Apply and Search wait for it to finish)."""
    kind: str
    ref: str
    noun: str
    script: str
    running: bool = False


class SuggestRefused(Exception):
    """A suggestion request the studio does not carry out: `status` is the HTTP status, the message a sentence for the page."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


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
                                     stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1,
                                     env=child_env(headless=False))
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
    """The project a board belongs to: the outermost folder above it (or itself) holding a placemat.toml or a workspace
    pcb.toml, else the board's own folder. One place per project: the command's socket (channel.py), `placemat watch`
    and the studio all look under it, whichever folder of the project they start in."""
    from .settings import _files
    board_dir = Path(board_dir).resolve()
    found = [f.parent.resolve() for f in _files(board_dir)]
    outer = None
    d = board_dir
    while True:
        pt = d / "pcb.toml"
        if pt.is_file() and "[workspace]" in pt.read_text(errors="replace"):
            outer = d
        if d.parent == d:
            break
        d = d.parent
    candidates = found + ([outer] if outer else [])
    if not candidates:
        return board_dir
    return min(candidates, key=lambda p: len(p.parts))


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
            self.script, self.src = None, None
            self._scripts = self._entries(found)
            cfg = settings_mod.load(self.root)
            from .studio_builder import BuilderService
            self.builder = BuilderService(self)
            self.cfg = cfg
            if not found and not self.builder.unbuilt():
                raise ValueError("no layout scripts found under %s (a layout script is a Python file that calls board.<...> "
                                 "as it loads, beside its board's .zen), and no .zen declares a board without one" % self.root)
        else:
            self.script = Path(script).resolve()
            if not self.script.is_file():
                raise ValueError("%s is not a file" % script)
            self.src = find_board(self.script)
            self.root = project_root(self.src.board_dir)
            cfg = settings_mod.load(self.src.board_dir, script=self.script)
        self.cfg = cfg
        if script is not None:
            from .studio_builder import BuilderService
            self.builder = BuilderService(self)
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
        self._try = None                        # the try of a suggestion in flight: {"id", "rid", "event", "result", ...}
        self._probe = None                      # the probe of a searched suggestion in flight: {"sid", "proc", "started"}
        self._applied_dir = None                # with no script chosen, the board a followed command's suggestion was last applied to
        self._applied_text = ""                 # what the next resolve is said to follow: an applied (or undone) suggestion
        self._notes: list = []                  # the notes of the project's scripts (notes.py), oldest first, each with its script's `path`
        self._notes_stamp = None                # {board folder: (mtime_ns, size)} of the notes files when they were last read
        self.cmds: dict = {}                    # the commands of the project that report over the channel, by connection id
        self.watcher = None
        self._run = None                        # the checked run in progress: {"id", "lines"}
        self._run_cache: dict = {}              # run.json path -> (mtime, summary)
        self._models_cache: dict = {}           # a recorded board's 3D models: (path, mtime_ns, project folder) -> _board_models
        self._models_lock = threading.Lock()    # one board read at a time (pcbnew), whatever the request threads
        self.worker = WorkerProcess(self._on_worker, self._views() / "worker.log")
        from . import studio_3d
        self.m3d = studio_3d.Models3D(self.cfg, self._emit_3d, self._views() / "models3d.log")      # the 3D view's converter (studio_3d.py)

    def _emit_3d(self, name: str, data: dict) -> None:
        with self.lock:
            self.hub.emit(name, data)

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
            self._notes, self._notes_stamp = [], None
            self._run_cache.clear()
            self._cur, self._cancel_at, self._error, self._dirty = None, None, None, False
            self.debounce.stopped()
            self.hub.log.clear()
            self._files = self.watched()
            self._poller = Poller(lambda: self._files)
            self._initial = True                # the next tick resolves it
            self.hub.emit("switched", self._hello_data())

    def leave_script(self) -> None:
        """Watch no script: the one being watched is gone (the builder's first write was undone), so the studio is a picker again."""
        with self.lock:
            self.worker.kill()
            self.script, self.src = None, None
            self.history.clear()
            self._notes, self._notes_stamp = [], None
            self._cur, self._cancel_at, self._error, self._dirty = None, None, None, False
            self.debounce.stopped()
            self.hub.log.clear()
            self._files = []
            self._poller = Poller(lambda: self._files)
            self._initial = False
            self._scripts = self._entries(layout_scripts(self.root))
            self.hub.emit("switched", self._hello_data())

    # ------------------------------------------------------------ files
    def name_of(self, path, base=None) -> str:
        """`path` as the page names files: relative to `base` (a folder), by default the watched script's folder."""
        return os.path.relpath(path, base or (self.script.parent if self.script else self.root))

    def watched(self) -> list:
        """What a resolve depends on: the script and what it imports, its lock
        and routes, every placemat.toml above the board, the fab profile and
        the cached generation."""
        return self.watched_of(self.script, self.src)

    @staticmethod
    def watched_of(script, src) -> list:
        """What a resolve of `script` (its board `src`) depends on: `watched` for a script the studio is not watching."""
        from .project import fab_profile, script_files
        from .runner import cached_generation
        from .settings import _files
        if script is None:
            return []
        files = list(script_files(script, missing=True))
        files += _files(script.parent)
        try:
            fab = fab_profile(src.board_dir)
            if fab.path:
                files.append(Path(fab.path))
        except (ValueError, OSError):
            pass
        files.append(cached_generation(src) / src.pcb.name)
        seen, out = set(), []
        for f in files:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def snapshot_texts(self, files=None, base=None) -> dict:
        """The texts of `files` (default the watched ones), by their names relative to `base` (name_of)."""
        out = {}
        for f in self._files if files is None else files:
            if f.suffix == ".kicad_pcb" or not f.is_file():
                continue
            try:
                out[self.name_of(f, base)] = f.read_text(errors="replace")
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
        self.m3d.stop()
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

    def _note_dirs(self) -> list:
        """The board folders whose notes are read: every board of the project's layout scripts once they are listed, and the
        watched script's. A followed command or a past run of any of them shows its own script's notes."""
        dirs = [s["src"].board_dir for s in (self._scripts or [])] + ([self.src.board_dir] if self.src is not None else [])
        return list(dict.fromkeys(dirs))

    def _check_notes(self) -> None:
        """Read the notes files when one has changed and tell the pages of the notes they have not been told of. Each note
        carries `path`, its script's full path, by which the page shows it on the board of that script only."""
        from . import notes as notes_mod
        dirs = self._note_dirs()
        stamps = {}
        for d in dirs:
            try:
                st = notes_mod.path_for(d).stat()
                stamps[str(d)] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
        if stamps == self._notes_stamp:
            return
        self._notes_stamp = stamps
        fresh = sorted((dict(n, path=str(Path(d) / str(n.get("script") or ""))) for d in dirs for n in notes_mod.read(d)),
                       key=lambda n: float(n.get("at") or 0))
        with self.lock:
            seen = {n["id"] for n in self._notes}
            new = [n for n in fresh if n["id"] not in seen]
            self._notes = fresh
            for n in new:
                self.hub.emit("note", n)

    def notes_list(self) -> list:
        """The notes of the project's scripts that have not expired, oldest first, as a page that joins is given them."""
        from . import notes as notes_mod
        with self.lock:
            return notes_mod.live(self._notes, self.cfg.studio_note_age_s)

    def _tick(self, now: float) -> None:
        self._check_notes()                     # a followed command or past run shows its own script's notes, chosen or not
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
            self._cancel_try("a file changed")
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
                         "total": None, "now": None, "replayed": 0, "applied": self._applied_text}
            self._applied_text = ""
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
            self._cancel_try("a resolve was asked for")
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
                if self._try is not None:
                    self._end_try({"state": "error", "message": "the resolve worker stopped during the try"})
                if cur is not None and not self._stopping.is_set():
                    self._fail(cur["id"], **self.worker_death(ev.get("code")))
                return
            if kind in ("try_done", "try_cancelled", "try_error"):
                self._on_try(ev)
                return
            if kind == "model_jobs":                    # the models a resolve's items use, for the converter (studio_3d.py)
                self.m3d.submit(ev.get("jobs"))
                return
            if cur is None or ev.get("id") != cur["id"]:
                return
            for key, value in (("now", None), ("total", None), ("replayed", 0)):
                cur.setdefault(key, value)
            rid = cur["id"]
            if kind == "board":
                self.hub.emit("board", present.board({k: v for k, v in ev.items() if k not in ("ev", "id")}) | {"id": rid}, keep=True)
            elif kind == "item":
                cur["last"] = ev["item"].get("key")
                if cur["now"] is not None and cur["now"].get("replaying"):
                    cur["replayed"] += 1
                cur["now"] = None
                self.hub.emit("step", {"id": rid, "item": self._named(present.item(ev["item"])), **{k: ev[k] for k in ("ops", "cutout") if k in ev}}, keep=True)
            elif kind == "begin":
                info = {k: v for k, v in ev.items() if k != "ev"} | {"at": time.time()}        # when, by the server's clock
                if info["kind"] == "total":
                    cur["total"] = info
                elif info["kind"] == "begin":
                    cur["now"] = dict(info, stage="")
                elif cur["now"] is not None:
                    cur["now"]["stage"] = info.get("stage", "")
                    cur["now"]["face"] = info.get("face")
                    cur["now"]["within"] = info.get("within")
                    if info.get("hint"):
                        cur["now"]["hint"] = info["hint"]
                # the queue's size is kept for a page that joins part-way; what an item is doing is transient
                self.hub.emit("begin", info, keep=info["kind"] == "total")
            elif kind == "cancelled":
                self._finish_cancel()
            elif kind == "error":
                self._fail(rid, channel.failure_text(ev), file=self.name_of(ev["file"]) if ev.get("file") else "", line=ev.get("line"),
                           source=ev.get("source"), detail=ev.get("traceback", ""))
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
        doc = present.plan(ev["doc"])
        for item in doc["items"]:
            item["file"] = self.name_of(item["file"]) if item.get("file") else ""
        doc = with_spans(doc, cur["texts"])
        from . import reuse as reuse_mod
        rec = Record(rid, time.time(), cur["texts"], doc, cur["changed"], ev["timing"], reuse_mod.summary_text(ev.get("reused")),
                     ev.get("stale"), cur.get("applied", ""))
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
                       "reservations": doc["reservations"], "layers": doc["layers"], "seconds": doc.get("seconds")}, keep=True)
        emit("finished", {"id": rid, "counts": doc["counts"], "timing": rec.timing, "reused": rec.reused, "stale": rec.stale,
                          "score": doc.get("score"), "history": [r.summary() for r in self.history]}, keep=True)
        if previous is not None:
            emit("compare", self.compare(previous, rec), keep=True)
        self.hub.log.clear()                    # a page that connects now is given the whole of it by hello()

    # ------------------------------------------------------------ suggestions
    # The finding's suggestions are in the plan the page was sent; these take {resolve, id}, look the suggestion up in that
    # resolve's findings and call suggestions.apply_suggestion. The page never sends source text. A past run, explore or command
    # the page shows in place of a resolve of its own is named by {view: {kind, ref}} in place of `resolve` (_view_suggestion).
    def _suggestion(self, rid, sid, view=None):
        """(record, pool, finding, past): `past` is None for a resolve of this studio, else the PastView the suggestion is of."""
        from . import suggestions as sg
        if view is not None:
            return self._view_suggestion(view, sid)
        built = self.builder.suggestion(rid, sid)
        if built is not None:
            return built + (None,)
        rec = self.record(_int(str(rid)))
        if rec is None:
            raise SuggestRefused(404, "no such resolve (the last %d are kept)" % self.keep)
        findings = rec.doc.get("findings", [])
        finding = next((f for f in findings if any(s.get("id") == sid for s in f.get("suggestions", ()))), None)
        found = []
        if finding is None and "." in sid:                  # `s3a.1`: what a probe of s3a found, kept in the store, not in the plan
            parent = sid.rsplit(".", 1)[0]
            finding = next((f for f in findings if any(s.get("id") == parent for s in f.get("suggestions", ()))), None)
            found = [s for s in self._found_all() if s.id == sid] if finding is not None else []
            if not found:
                finding = None
        if finding is None:
            raise SuggestRefused(404, "resolve #%d has no suggestion %r" % (rec.id, sid))
        pool = sg.from_json([s for f in findings for s in f.get("suggestions", ())]) + found
        return rec, pool, finding, None

    def _view_doc(self, kind: str, ref: str):
        """(doc, script, noun) of a view the page shows in place of a resolve of its own, made by the call the page opened it with:
        a recorded run (/runview), a routed run's build or a route (/build, /route), an explore's best variant (/exploreview) or a
        command's last plan (/cmd). `noun` is what the page calls it. None when it is not there."""
        if kind == "run":
            v = self.run_view(ref)
            return None if v is None else (v["doc"], v["summary"].get("script") or "", "run")
        if kind in ("build", "route"):
            v = self.build_record(ref) if kind == "build" else self.route_record(ref)
            return None if v is None else (v["doc"], ((v.get("board") or {}).get("script")) or "", "run" if kind == "build" else "route")
        if kind == "explore":
            v = self.explore_view(ref)
            return None if v is None or v["doc"] is None else (v["doc"], (v["record"] or {}).get("script") or "", "explore")
        if kind == "cmd":
            with self.lock:
                c = self.cmds.get(_int(ref))
                if c is None or not c.get("plan"):
                    return None
                noun = channel.kind_of(c.get("command", ""), c.get("args"), c.get("explore") is not None) or "command"
                return present.plan(c["plan"].get("doc") or {}), c.get("script") or "", noun
        return None

    def _view_at(self, kind: str, ref: str) -> float | None:
        """When a view's run read its files (epoch seconds), for saying a file has changed since: a command's start, a recorded run's
        record less the time it took, a route's or an explore's record. None when it is not known."""
        if kind == "cmd":
            with self.lock:
                return (self.cmds.get(_int(ref)) or {}).get("started")
        try:
            if kind in ("run", "build"):
                folder = self.run_folder(ref)
                if folder is None:
                    return None
                at = (folder / "run.json").stat().st_mtime
                try:
                    took = json.loads((folder / "run.json").read_text()).get("timing_s") or {}
                    at -= sum(v for v in took.values() if isinstance(v, (int, float)))
                except (OSError, ValueError, AttributeError):
                    pass
                return at
            if kind in ("route", "explore"):
                return Path(ref).stat().st_mtime
        except OSError:
            return None
        return None

    def view_source(self, kind: str, ref: str, file: str) -> dict:
        """A source file of a view the page shows in place of a resolve of its own (a followed command, a past run, route or
        explore), for its code view: the view's own script and its inputs (watched_of, the rule a suggestion of the view acts on)
        and any other file the view's plan names by a source link (a module's script, say), inside the project only.
        {file, name, text, changed, files: [{file, name}]}: `file` as asked, `name` relative to the view's script's folder,
        `changed` whether it was modified after the view's run read it, `files` the view's Python files. Refused (SuggestRefused,
        `reason`) when the view is not there ("no_view"), the file is not one of it ("not_of_view"), lies outside the project
        ("outside") or cannot be read ("gone")."""
        from .project import find_board, script_files
        got = self._view_doc(kind, ref)
        if got is None:
            raise SuggestRefused(404, "no such %s, or it kept no plan" % {"cmd": "command", "build": "run"}.get(kind, kind or "view"), reason="no_view")
        doc, script_name, noun = got
        script = Path(script_name).resolve() if script_name else None
        base = script.parent if script is not None else self.root

        def resolved(f) -> Path:
            p = Path(f)
            return (p if p.is_absolute() else base / p).resolve()

        named: dict = {}                                    # resolved path -> the name the view's plan gives it
        def walk(v):
            if isinstance(v, dict):
                f = v.get("file")
                if isinstance(f, str) and f.endswith(".py"):
                    named.setdefault(resolved(f), f)
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        walk(doc)
        inputs = []
        if script is not None:
            try:
                inputs = self.watched_of(script, find_board(script))
            except (ValueError, OSError):
                inputs = script_files(script)
        allowed = {Path(f).resolve(): named.get(Path(f).resolve(), str(f)) for f in inputs}
        for p, f in named.items():
            allowed.setdefault(p, f)
        want = resolved(file) if file else script
        if want is None or want not in allowed:
            raise SuggestRefused(404, "%s is not a file of this %s" % (Path(file).name or "the file", noun), reason="not_of_view")
        root = self.root.resolve()
        if root not in want.parents:
            raise SuggestRefused(403, "%s lies outside the project (%s), so it is not shown" % (want, root), reason="outside")
        try:
            text = want.read_text(errors="replace")
            mtime = want.stat().st_mtime
        except OSError:
            raise SuggestRefused(404, "%s could not be read: it is no longer there" % want, reason="gone") from None
        at = self._view_at(kind, ref)
        files = sorted(((p, f) for p, f in allowed.items() if p.suffix == ".py" and root in p.parents and p.is_file()),
                       key=lambda pf: (pf[0] != script, str(pf[0])))
        return {"file": file or str(want), "name": self.name_of(want, base), "text": text, "changed": at is not None and mtime > at,
                "files": [{"file": f, "name": self.name_of(p, base)} for p, f in files]}

    def _view_suggestion(self, view, sid):
        """A suggestion of a view that is not a resolve of this studio (a past run, an explore, a command), found in the plan the view
        shows, as `placemat apply` finds one in the plan its run kept. The record it is compared with in a try is that plan, with the
        watched files' texts as they are now: the suggestion's digests (checked when it is shown, tried or applied) say the files it
        edits are as the run saw them."""
        from . import suggestions as sg
        past, doc = self._past(view)
        kind, ref, noun = past.kind, past.ref, past.noun
        findings = doc.get("findings", [])
        finding = next((f for f in findings if any(s.get("id") == sid for s in f.get("suggestions", ()))), None)
        found = []
        if finding is None and "." in sid:                  # `s3a.1`: what a probe of s3a found, kept in the store of the view's script
            parent = sid.rsplit(".", 1)[0]
            finding = next((f for f in findings if any(s.get("id") == parent for s in f.get("suggestions", ()))), None)
            found = [s for s in self._found_all(past) if s.id == sid] if finding is not None else []
            if not found:
                finding = None
        if finding is None:
            raise SuggestRefused(404, "this %s has no suggestion %r" % (noun, sid))
        target, src = self._target(past)
        base = target.parent if target is not None and target != self.script else None
        doc = dict(doc, items=[dict(it, file=self.name_of(it["file"], base)) if it.get("file") and os.path.isabs(it["file"]) else it
                               for it in doc.get("items", ())])
        texts = self.snapshot_texts(None if base is None else self.watched_of(target, src), base)
        label = "%s %s" % (noun, Path(ref).name if kind in ("explore", "route") else ref)
        rec = Record(label, time.time(), texts, with_spans(doc, texts), [], {})
        pool = sg.from_json([s for f in findings for s in f.get("suggestions", ())]) + found
        return rec, pool, finding, past

    def _past(self, view):
        """(PastView, doc) of a view named as the page names it ({kind, ref}); refused when it is not there."""
        if not isinstance(view, dict):
            raise SuggestRefused(400, "a view is {kind, ref}")
        kind, ref = str(view.get("kind") or ""), str(view.get("ref") or "")
        got = self._view_doc(kind, ref)
        if got is None:
            raise SuggestRefused(404, "no such %s, or it kept no plan" % {"cmd": "command", "build": "run"}.get(kind, kind or "view"))
        doc, script, noun = got
        running = False
        if kind == "cmd":
            with self.lock:
                running = (self.cmds.get(_int(ref)) or {}).get("state") == "running"
        return PastView(kind, ref, noun, script, running), doc

    def _target(self, past):
        """(script, src) a suggestion of `past` acts on: the script of the view it is of, as if it had been chosen, or with no view
        (or a view that does not say) the script this studio watches. (None, None) when neither is there."""
        from .project import find_board
        with self.lock:
            if past is None or not past.script or (self.script is not None and Path(past.script).resolve() == self.script):
                return self.script, self.src
        script = Path(past.script).resolve()
        try:
            return (script, find_board(script)) if script.is_file() else (None, None)
        except (ValueError, OSError):
            return None, None

    def _target_or_refuse(self, past):
        script, src = self._target(past)
        if script is None or src is None:
            raise SuggestRefused(409, "choose a layout script first", reason="no_script")
        return script, src

    def _base(self, past):
        """The folder a suggestion's files are named relative to: None (the watched script's) unless it acts on another script (_target)."""
        script, _ = self._target(past)
        return script.parent if script is not None and script != self.script else None

    @staticmethod
    def _not_running(past) -> None:
        """A command still running has not made its last plan: its suggestions are tried, applied and searched once it has finished.
        A run started elsewhere is never stopped for it."""
        if past is not None and past.running:
            raise SuggestRefused(409, "this %s is still running: its suggestions can be tried, applied and searched when it has finished" % past.noun,
                                 reason="running", cmd=_int(past.ref))

    def _same_script(self, past) -> None:
        """A try or a search of a past view's suggestion resolves the watched script: the view must be of it."""
        if past is not None and past.script and self.script is not None and Path(past.script).resolve() != self.script.resolve():
            raise SuggestRefused(409, "this %s is of %s, not the script this studio watches: choose it to try its suggestions"
                                 % (past.noun, Path(past.script).name))

    def _found_all(self, past=None) -> list:
        """The suggestions probes found for this script, or for the script of the view `past` (`<id>.<n>`), from the store
        `placemat apply` reads."""
        from . import suggestions as sg
        script, src = self._target(past)
        if script is None or src is None:
            return []
        plans = sg.recall(src.board_dir, script)
        return [s for entry in plans.values() for s in entry["suggestions"] if "." in s.id]

    def suggest_found(self, sid: str, view=None) -> dict:
        """What a probe found for a searched suggestion, as an instant suggestion (the plan does not know it: the page asks). `view`
        names the view the suggestion is of, whose script's store is read."""
        past = self._past(view)[0] if view else None
        s = next((x for x in self._found_all(past) if x.id == sid), None)
        if s is None:
            raise SuggestRefused(404, "no found suggestion %r" % sid)
        return s.to_json()

    def _sg_refusal(self, e, past=None) -> SuggestRefused:
        from . import suggestions as sg
        status = 404 if isinstance(e, sg.UnknownSuggestion) else 422 if isinstance(e, sg.EditRefused) else 409
        files = [self.name_of(f) for f in getattr(e, "files", ()) or ()]
        if past is not None and isinstance(e, sg.StaleSuggestion):
            return SuggestRefused(409, "this %s's script has changed since; re-run to act on its suggestions" % past.noun, files=files)
        return SuggestRefused(status, str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e), files=files)

    def _applied_json(self, done, base=None) -> dict:
        files = []
        for path, ch in done.files.items():
            files.append({"file": self.name_of(path, base), "path": str(path), "diff": ch.diff, "old_lines": list(ch.old_lines),
                          "new_lines": list(ch.new_lines), "hunks": line_diff(ch.before or "", ch.after or "")["hunks"],     # a created or removed file has no text on one side
                          "added": len(ch.new_lines), "removed": len(ch.old_lines)})
        return {"id": done.id, "text": done.text, "dry_run": done.dry_run, "files": files, "diff": done.diff()}

    def applied_list(self, limit: int = 12, past=None) -> list:
        """The suggestions applied here (oldest first), as the page lists them: its Undo and its history rows. With `past`, those of
        the view's board."""
        log_dir = self._log_dir(past)
        if log_dir is None:
            return []
        from . import suggestions as sg
        try:
            entries = sg.applied_entries(sg.log_path(log_dir))
        except (OSError, ValueError):
            return []
        return [{"seq": e["seq"], "id": e.get("id"), "text": e.get("text", ""), "at": e.get("at"), "undone": bool(e.get("undone")),
                 "op": e.get("op"), "files": [self.name_of(f["file"]) for f in e.get("files", ())]} for e in entries[-limit:]]

    def _log_dir(self, past=None):
        """The board folder whose applied log the page's undo and redo use: that of the view `past` when one is shown, else the
        script's, or before there is one the board the builder is making, or with neither the board of the followed command a
        suggestion was last applied to."""
        if past is not None:
            _, src = self._target(past)
            if src is not None:
                return src.board_dir
        if self.src is not None:
            return self.src.board_dir
        sess = self.builder.session
        return sess["board_dir"] if sess else self._applied_dir

    def redo_text(self, past=None) -> str:
        """What a redo would make again (the apply the last undo took back), or "" when there is nothing to redo."""
        log_dir = self._log_dir(past)
        if log_dir is None or not self.cfg.studio_apply:
            return ""
        from . import suggestions as sg
        try:
            return sg.redo_last(sg.log_path(log_dir), dry_run=True).text
        except sg.NothingToRedo:
            return ""
        except (sg.SuggestionError, OSError, ValueError):
            return ""

    def suggest_show(self, rid, sid, view=None) -> dict:
        """The dry run: the unified diff and the lines it changes; nothing is written."""
        from . import suggestions as sg
        rec, pool, finding, past = self._suggestion(rid, sid, view)
        try:
            done = sg.apply_suggestion(pool, sid, dry_run=True)
        except sg.SuggestionError as e:
            raise self._sg_refusal(e, past)
        base = self._base(past)
        out = self._applied_json(done, base)
        s = next(x for x in pool if x.id == sid)
        targets = []
        for e in s.edits:                                              # a suggestion may make several edits; each names its declaration
            if e.target is not None:
                targets.append(("target", e.target))
            targets += [("refers to", r) for r in (e.refs or {}).values()]
        out["targets"] = [{"role": role, "key": tg.key, "file": self.name_of(tg.file, base), "line": tg.line} for role, tg in targets if tg.file]
        out["resolve"] = rec.id
        return out

    def suggest_apply(self, rid, sid, view=None) -> dict:
        from . import suggestions as sg
        if not self.cfg.studio_apply:
            raise SuggestRefused(403, "this studio shows suggestions but does not write them ([studio] apply is false)")
        rec, pool, finding, past = self._suggestion(rid, sid, view)
        self._not_running(past)
        self._same_script(past)
        script, src = self._target_or_refuse(past)
        base = self._base(past)
        root = sg.project_root(src.board_dir)
        try:
            dry = sg.apply_suggestion(pool, sid, dry_run=True)
            watched = {Path(f).resolve() for f in self.watched_of(script, src)}       # the followed command's script and its inputs when none is chosen
            outside = [self.name_of(p, base) for p in dry.files if Path(p).resolve() not in watched]
            if outside:
                raise SuggestRefused(422, "the edit would write %s, which this studio does not watch" % ", ".join(outside))
            done = sg.apply_suggestion(pool, sid, root=root, log=sg.log_path(src.board_dir))
        except sg.SuggestionError as e:
            raise self._sg_refusal(e, past)
        with self.lock:
            self._applied_text = "applied from a suggestion: " + done.text
            if script != self.script:
                self._applied_dir = src.board_dir                  # undo and redo use that board's log while no script is chosen
        out = self._applied_json(done, base)
        out["undo"] = True
        self.hub.emit("applied", {"applied": self.applied_list(past=past), "text": done.text, "id": sid, "redo": ""})
        return out

    def _undo_log(self, view):
        """(past, the applied log) an undo or a redo acts on: the board of the view shown, else the studio's (_log_dir)."""
        from . import suggestions as sg
        if not self.cfg.studio_apply:
            raise SuggestRefused(403, "this studio does not write ([studio] apply is false)")
        past = self._past(view)[0] if view else None
        log_dir = self._log_dir(past)
        if log_dir is None:
            raise SuggestRefused(409, "nothing has been applied here")
        return past, sg.log_path(log_dir)

    def applied_state(self, view=None) -> dict:
        """The applied list and the redo of the view shown (or the studio's), for a page that opens a view."""
        past = self._past(view)[0] if view else None
        return {"applied": self.applied_list(past=past), "redo": self.redo_text(past)}

    def suggest_undo(self, view=None) -> dict:
        from . import suggestions as sg
        past, log = self._undo_log(view)
        try:
            done = sg.undo_last(log, root=self.root)
        except sg.SuggestionError as e:
            raise self._sg_refusal(e)
        with self.lock:
            self._applied_text = "undid: " + done.text
        self.builder.after_undo(done)
        out = self._applied_json(done)
        self.hub.emit("applied", {"applied": self.applied_list(past=past), "text": done.text, "undone": True, "redo": self.redo_text(past)})
        return out

    def suggest_redo(self, view=None) -> dict:
        """Make again the apply the last undo took back (refused when a file has moved on since)."""
        from . import suggestions as sg
        past, log = self._undo_log(view)
        try:
            done = sg.redo_last(log, root=self.root)
        except sg.SuggestionError as e:
            raise self._sg_refusal(e)
        with self.lock:
            self._applied_text = "redid: " + done.text
        self.builder.after_undo(done)
        out = self._applied_json(done)
        out["undo"] = True
        self.hub.emit("applied", {"applied": self.applied_list(past=past), "text": done.text, "redone": True, "redo": self.redo_text(past)})
        return out

    def _cancel_try(self, why: str) -> None:
        """Stop the try in flight (a watched file changed, or a resolve was asked for): the worker honours it at its next step."""
        tr = self._try
        if tr is not None and not tr.get("cancel"):
            tr["cancel"] = why
            self.worker.send({"cmd": "cancel", "id": tr["id"]})

    def _end_try(self, result: dict) -> None:
        tr, self._try = self._try, None
        if tr is not None:
            tr["result"] = result
            tr["event"].set()

    def suggest_try(self, rid, sid, view=None) -> dict:
        """Resolve the dry-run text in the warm worker, with the edited files read from an overlay and nothing written; the answer
        is compared with the resolve the suggestion was made on. Runs only when asked, only when no resolve is running or pending,
        one at a time; a change to a watched file cancels it."""
        from . import suggestions as sg
        rec, pool, finding, past = self._suggestion(rid, sid, view)
        self._not_running(past)
        try:
            done = sg.apply_suggestion(pool, sid, dry_run=True)
        except sg.SuggestionError as e:
            raise self._sg_refusal(e, past)
        self._same_script(past)
        script, _ = self._target_or_refuse(past)
        base = self._base(past)
        overlay = {str(p): ch.after for p, ch in done.files.items()}
        with self.lock:
            if self._cur is not None or self._dirty or self._initial:
                raise SuggestRefused(409, "a resolve is running or pending: try again when it has finished")
            if self._try is not None:
                raise SuggestRefused(409, "another try is running")
            self._next_id += 1
            tr = self._try = {"id": self._next_id, "rid": rec.id, "event": threading.Event(), "result": None, "overlay": overlay,
                              "finding": finding, "text": done.text, "sid": sid, "applied": self._applied_json(done, base),
                              "past": past, "base": rec if past is not None else None, "names": base}
            if not self.worker.send({"cmd": "try", "id": tr["id"], "script": str(script), "overlay": overlay}):
                self._try = None
                raise SuggestRefused(409, "the resolve worker could not be started")
        limit = float(self.cfg.studio_try_timeout_s)
        if not tr["event"].wait(limit):
            with self.lock:
                self._cancel_try("the try took longer than [studio] try_timeout_s (%g s)" % limit)
            if not tr["event"].wait(max(self.grace_s, 1.0)):                 # it did not reach a step to stop at
                with self.lock:
                    self.worker.kill()
                    self._end_try({"state": "timeout", "message": "the try took longer than [studio] try_timeout_s (%g s) and was stopped" % limit})
        return tr["result"]

    # ------------------------------------------------------------ the probe of a searched suggestion
    # A probe is `placemat apply <id> --search --yes` run as a command of its own: it resolves the edited script in its own
    # process, so the studio's worker stays free, and reports over the live channel like any command (`probe`, `candidate`,
    # `probe_done` reach the page as the command's events, and the command's summary has `probe`). The studio starts it
    # (after a confirmation where every candidate resolves the whole board) and stops it (SIGTERM: the probe keeps what it
    # found and says "stopped by you").
    def probe_start(self, rid, sid, yes: bool = False, view=None) -> dict:
        from . import probe, suggestions as sg
        rec, pool, finding, past = self._suggestion(rid, sid, view)
        self._not_running(past)
        s = sg.find(pool, sid)
        if s.how != "searched":
            raise SuggestRefused(422, "%s is not a searched suggestion: it has a value to apply or try" % sid)
        self._same_script(past)
        script, src = self._target_or_refuse(past)
        board_dir = src.board_dir
        with self.lock:
            if self._probe is not None and self._probe["proc"].poll() is None:
                raise SuggestRefused(409, "a probe is already running (%s): stop it first" % self._probe["sid"])
        est = probe.estimate(s, board_dir, script, self.cfg.studio_probe_candidates, self.cfg.studio_probe_budget_s)
        if est["board_wide"] and not yes:
            return {"state": "confirm", "estimate": est, "line": probe.estimate_line(est)}
        sg.keep(board_dir, script, "studio resolve #%d" % rec.id if past is None else "studio, " + rec.id, pool)       # the store the command reads: the plan the page was shown
        cmd = [sys.executable, "-m", "placemat", "apply", sid, "--search", "--yes", "--script", str(script)]
        try:
            proc = subprocess.Popen(cmd, cwd=str(board_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env(headless=False))
        except OSError as e:
            raise SuggestRefused(409, "could not start the probe: %s" % e)
        with self.lock:
            self._probe = {"sid": sid, "proc": proc, "started": time.time()}
        return {"state": "started", "pid": proc.pid, "estimate": est, "line": probe.estimate_line(est)}

    def probe_stop(self) -> dict:
        """Ask the running probe to stop (SIGTERM); it keeps its results and says what it found."""
        with self.lock:
            p = self._probe
        if p is None or p["proc"].poll() is not None:
            raise SuggestRefused(409, "no probe is running")
        p["proc"].terminate()
        return {"state": "stopping", "pid": p["proc"].pid}

    def _on_try(self, ev: dict) -> None:
        tr = self._try
        if tr is None or ev.get("id") != tr["id"]:
            return
        kind = ev["ev"]
        if kind == "try_cancelled":
            self._end_try({"state": "cancelled", "message": "the try was stopped: %s" % (tr.get("cancel") or "cancelled")})
        elif kind == "try_error":
            self._end_try({"state": "error", "message": "the edited script does not run: %s" % channel.failure_text(ev),
                           "file": self.name_of(ev["file"], tr.get("names")) if ev.get("file") else "", "line": ev.get("line")})
        else:
            from . import suggestions as sg
            rec = tr["base"] or self.record(tr["rid"])
            if rec is None:
                self._end_try({"state": "error", "message": "the resolve this suggestion was made on is no longer kept"})
                return
            texts = dict(rec.texts)
            for path, after in tr["overlay"].items():
                texts[self.name_of(path, tr.get("names"))] = after
            doc = present.plan(ev["doc"])
            for item in doc["items"]:
                item["file"] = self.name_of(item["file"], tr.get("names")) if item.get("file") else ""
            for f in doc.get("findings", ()):
                f["suggestions"] = []                      # their digests are of the overlay: a try's suggestions are never applied
            doc = with_spans(doc, texts)
            trec = Record(tr["id"], time.time(), texts, doc, [], ev.get("timing", {}))
            cmp = self.compare(rec, trec)
            d = cmp["diff"]
            self._end_try({"state": "done", "id": tr["id"], "base": rec.id, "suggestion": {"id": tr["sid"], "text": tr["text"]},
                           "finding": {"text": tr["finding"].get("text", ""), "kind": tr["finding"].get("kind", ""), "item": tr["finding"].get("item", "")},
                           "cleared": sg.cleared(tr["finding"], doc["findings"]), "gained": d["findings"]["gained"], "lost": d["findings"]["lost"],
                           "moved": len(d["moved"]), "score": d.get("score"), "compare": cmp, "doc": doc, "texts": texts,
                           "timing": trec.timing, "applied": tr["applied"],
                           **({"view": {"kind": tr["past"].kind, "ref": tr["past"].ref}} if tr["past"] is not None else {})})

    # ------------------------------------------------------------ the live channel
    MAX_EVENTS = 6000                           # kept for a command: what a page opening it late is given
    MAX_CMDS = 30

    @staticmethod
    def _cmd_summary(c: dict) -> dict:
        """A command as the page lists it. `kind` is what it is (channel.kind_of: preview, run, explore, route); `command` the name it was typed as."""
        return {k: c.get(k) for k in ("id", "pid", "command", "script", "args", "started", "state", "message", "record", "last", "items",
                                      "variants", "ended", "own_run", "best", "baseline", "kept", "resolves", "truncated", "probe", "slow", "label")} | \
            {"kind": channel.kind_of(c.get("command", ""), c.get("args"), c.get("explore") is not None),
             "stopped": (c.get("error") or {}).get("kind") == "stopped",          # ended on purpose (--max-time, a stop, a signal), not by a failure
             "route": None if not c.get("route") else {k: v for k, v in c["route"].items() if k not in ("log", "results", "in_stage")},
             "build": Studio._built_run(c.get("record"))}

    @staticmethod
    def _built_run(record) -> str | None:
        """The run a finished command wrote, when that run routed and kept its placement (its build, build_record): the page reads the
        route's copper and open nets from the run's own records once the command is done. None for any other command."""
        from . import route_progress
        if not record:
            return None
        p = Path(record)
        if p.name != "run.json" or p.parent.parent.name != "runs":
            return None
        d = p.parent
        return d.name if (d / "route" / route_progress.RECORD).is_file() and (d / "plan.json").is_file() else None

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
                     "label": ev.get("label") or "", "started": time.time(), "state": "running", "items": 0, "variants": 0, "resolves": 0, "log": [], "plan": None, "explore": None,
                     "own_run": run["id"] if run is not None and run.get("pid") == ev.get("pid") else None}
                self.cmds[cid] = c
                for old in [k for k, v in self.cmds.items() if v["state"] != "running"][:-self.MAX_CMDS]:
                    del self.cmds[old]
                self.hub.emit("cmd", self._cmd_summary(c))
                return
            if c is None:
                return
            ev = present.event(ev)
            if kind and kind.startswith("route_"):
                return self._on_route(cid, c, ev)
            if kind == "lost":
                if c["state"] == "running":
                    c.update(state="lost", ended=time.time(), message="the command stopped without saying it was done" +
                             ((" (the last step it reported: %s)" % c["last"]) if c.get("last") else ""))
                self.hub.emit("cmd", self._cmd_summary(c))
                return
            if kind == "item":
                if "model_jobs" in ev:                  # the models the item uses, for the converter (studio_3d.py): not for the page
                    self.m3d.submit(ev.pop("model_jobs"))
                it = ev.get("item") or {}
                if it.get("file"):
                    it["file"] = self._rel(c, it["file"])
                c["last"] = it.get("key") or c.get("last")
                c["items"] += 1
            elif kind == "resolve":
                c["resolves"] = ev.get("n", c["resolves"] + 1)
                c["plan"] = None
                c["slow"] = []
            elif kind in ("step_warn", "step_limit"):             # a step past its time (timecap.py): the page says which, and in what pass
                c["slow"] = (c.get("slow") or [])[-49:] + [{k: v for k, v in ev.items() if k != "ev"} | {"kind": kind}]
                self.hub.emit("slow", {"id": cid, "command": c.get("command"), **ev})
            elif kind == "plan":
                doc = ev.get("doc") or {}
                for it in doc.get("items", ()):
                    if it.get("file"):
                        it["file"] = self._rel(c, it["file"])
                c["plan"] = ev
            elif kind == "explore":
                c["explore"] = {"start": ev, "variants": [], "routes": [], "budget_passed": None, "search_done": None, "done": None}
            elif kind == "variant":
                c["variants"] += 1
                if c["explore"] is not None:
                    c["explore"]["variants"].append(ev)
                    c["best"] = min([c.get("best") if c.get("best") is not None else ev["score"], ev["score"]])
            elif kind == "explore_route":
                if c["explore"] is not None:
                    c["explore"].setdefault("routes", []).append(ev)
            elif kind == "explore_budget_passed":         # the time is up, variants in hand finishing: which (explore.budget_passed_line)
                if c["explore"] is not None:
                    c["explore"]["budget_passed"] = ev
            elif kind == "explore_search_done":           # the search is over, routes outstanding: which (explore.search_done_line)
                if c["explore"] is not None:
                    c["explore"]["search_done"] = ev
            elif kind == "explore_done":
                if c["explore"] is not None:
                    c["explore"]["done"] = ev
                c["best"], c["baseline"], c["kept"] = ev.get("best"), ev.get("baseline"), ev.get("kept")
                if ev.get("record"):
                    c["record"] = ev["record"]
            elif kind == "probe":
                c["probe"] = {"start": ev, "candidates": [], "done": None}
            elif kind == "candidate":
                if c.get("probe") is not None:
                    c["probe"]["candidates"].append(ev)
            elif kind == "probe_done":
                if c.get("probe") is not None:
                    c["probe"]["done"] = ev
            elif kind == "done":
                c.update(state="done", ended=time.time(), record=ev.get("record") or c.get("record"))
            elif kind == "error":
                c.update(state="error", ended=time.time(), message=ev.get("message", ""), error=ev)
            n = len(c["log"])
            if kind not in ("plan", "explore", "variant", "explore_route", "explore_budget_passed", "explore_search_done", "explore_done"):
                if n < self.MAX_EVENTS:
                    c["log"].append(ev)
                else:
                    c["truncated"] = True
            self.hub.emit("cmdev", {"id": cid, "n": n, "ev": ev})
            if kind in ("done", "error"):
                self.hub.emit("cmd", self._cmd_summary(c))
            elif c.get("own_run") is not None and kind in ("item", "begin"):
                self.hub.emit("run_progress", {"id": c["own_run"], "item": c.get("last") or "", "n": c["items"]})

    def _on_dead(self, cid: int, entry: dict, events: list) -> None:
        """A command found dead (its pid gone, its entry left behind): shown with the last state in its progress file."""
        done = next((e for e in reversed(events) if e.get("ev") in ("done", "error")), None)
        items = [e for e in events if e.get("ev") == "item"]
        last = items[-1].get("key") if items else None
        c = {"id": cid, "pid": entry.get("pid"), "command": entry.get("command", ""), "script": entry.get("script", ""),
             "args": entry.get("args", []), "label": entry.get("label") or "", "started": entry.get("started") or time.time(), "ended": time.time(), "items": len(items),
             "variants": sum(1 for e in events if e.get("ev") == "variant"), "resolves": sum(1 for e in events if e.get("ev") == "resolve"),
             "log": [], "plan": None, "explore": None, "last": last, "own_run": None}
        if done is not None and done.get("ev") == "done":
            c.update(state="done", record=done.get("record"))
        elif done is not None:
            c.update(state="error", message=channel.failure_text(done))
        else:
            c.update(state="lost", message="the command stopped without saying it was done" +
                     ((" (the last step it reported: %s)" % last) if last else ""))
        with self.lock:
            self.cmds[cid] = c
        self.hub.emit("cmd", self._cmd_summary(c))

    MAX_ROUTE_EVENTS = 60000                    # a route's events kept for a page that opens it late (the copper, net by net)

    def _on_route(self, cid: int, c: dict, ev: dict) -> None:
        """A route's event (route_progress.py: the router's hooks): the counts and the current net are kept here, the events themselves for a late
        page and sent to the open ones. Called with the lock held."""
        kind, r = ev["ev"], c.setdefault("route", {"total": 0, "seen": 0, "done": 0, "failed": 0, "current": "", "stage": "", "off": "", "dropped": 0, "truncated": False, "finished": False, "log": [], "results": {}, "in_stage": set(), "fixed": False})
        if kind == "route_stage":
            # `total` and `seen` are of the stage: its own nets (a stage that says how many it will take, else what its queues add up to), not the whole route's
            r["stage"] = ev.get("stage", "")
            r["total"], r["fixed"], r["seen"] = ev.get("nets") or 0, ev.get("nets") is not None, 0
            r["in_stage"] = set()
        elif kind == "route_queue":
            if not r["fixed"]:
                r["total"] += len(ev.get("nets", ()))
        elif kind == "route_net_begin":
            r["current"] = ev.get("net", "")
        elif kind == "route_net_end":
            r["results"][ev.get("net", "")] = bool(ev.get("ok"))
            r["in_stage"].add(ev.get("net", ""))
            r["seen"] = len(r["in_stage"])
            r["done"] = sum(1 for v in r["results"].values() if v)
            r["failed"] = sum(1 for v in r["results"].values() if not v)
        elif kind == "route_dropped":
            r["dropped"] += int(ev.get("n") or 0)
        elif kind == "route_queue_end":
            r["current"] = ""                        # one stage's queue: the route is over when its command is
        elif kind == "route_off":
            from .kicad import route_events
            r["off"] = route_events.reason_text(ev.get("reason") or {})
        if len(r["log"]) < self.MAX_ROUTE_EVENTS:
            r["log"].append(ev)
        elif not r["truncated"]:
            r["truncated"] = True
        self.hub.emit("cmdev", {"id": cid, "n": len(r["log"]), "ev": ev})
        if kind != "route_commit" and kind != "route_rip":
            self.hub.emit("cmd", self._cmd_summary(c))

    def cmd_detail(self, cid: int):
        """A command's events so far, its latest plan and, for an explore, its variants: what a page that opens it is given."""
        with self.lock:
            c = self.cmds.get(cid)
            if c is None:
                return None
            return {"summary": self._cmd_summary(c), "events": list(c["log"]) + list((c.get("route") or {}).get("log", ())), "plan": c["plan"], "explore": c["explore"]}

    def explores(self, limit: int = 20) -> list:
        """The recorded explores of the project's boards (their result files), newest first, as the page lists them."""
        dirs = {d / ".placemat" / "views" / "explore" for d in self.board_dirs()}
        with self.lock:
            for c in self.cmds.values():
                if c.get("record") and "views" in c["record"] and "explore" in c["record"]:
                    dirs.add(Path(c["record"]).parent)
        out, files = [], []
        for d in dirs:
            try:
                files += [(f.stat().st_mtime, f) for f in d.glob("*.json")]
            except OSError:
                continue
        for _, f in sorted(files, key=lambda x: -x[0])[:limit * 2]:
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

    def routes(self, limit: int = 20) -> list:
        """The recorded routes of the project's boards (`.placemat/route/` and each run's `route/`), newest first: each from its small summary file."""
        from . import route_progress
        out, recs = [], []
        for d in self.board_dirs():
            base = d / ".placemat"
            recs += [base / "route" / route_progress.RECORD] + sorted(base.glob("runs/*/route/" + route_progress.RECORD))
        for rec in recs:
            summ = rec.with_name(route_progress.SUMMARY)
            try:
                doc = json.loads(summ.read_text())
                at = doc.get("at") or rec.stat().st_mtime
            except (OSError, ValueError):
                continue
            run = doc.get("run") or ""
            out.append({"file": str(rec), "run": run, "at": at, "nets": doc.get("nets"), "routed": doc.get("routed"), "failed": doc.get("failed"),
                        "closure": doc.get("closure"), "seconds": doc.get("seconds"), "complete": doc.get("complete", True), "dropped": doc.get("dropped", 0), "script": doc.get("script") or doc.get("pcb", ""),
                        "build": bool(run) and (rec.parent.parent / "plan.json").is_file()})
        out.sort(key=lambda e: -(e["at"] or 0))
        return out[:limit]

    def _route_doc(self, record_path: Path, plan_path: Path | None = None, pcb: Path | None = None, project_dir=None, shape=None):
        """A route's replay document; `pcb` is the board its parts' 3D models are read from (default the board the route was given).
        `shape`, given, makes the board under the route over before the route is laid on it (a past explore gathers its focused items)."""
        from . import route_progress, route_view
        record = route_progress.read_record(record_path)
        if record is None:
            return None
        if pcb is None:
            pcb = record_path.parent / "in.kicad_pcb"
            given = (record.get("board") or {}).get("pcb")
            project_dir = Path(given).parent if given and Path(given).parent.is_dir() else None
        board = None
        if plan_path is not None:
            try:
                board = json.loads(plan_path.read_text())
            except (OSError, ValueError):
                board = None
        if board is None:
            try:
                board = json.loads((record_path.parent / route_progress.BOARD).read_text())
            except (OSError, ValueError):
                board = {}
        if shape is not None:
            board = shape(board)
        doc = route_view.route_doc(record, board, self._route_opens(record_path.parent))
        self._with_models(doc, pcb, project_dir)
        return {"doc": present.plan(doc), "summary": record.get("report", {}), "board": record.get("board", {})}

    @staticmethod
    def _route_opens(work: Path) -> list:
        """The connections a route left open, from the DRC it ran on the routed board (drc_after.json in its own folder); none without it."""
        from . import route_view
        from .kicad.drc import unconnected_items
        try:
            data = json.loads((work / "drc_after.json").read_text())
        except (OSError, ValueError):
            return []
        return route_view.open_connections(unconnected_items(data)) if isinstance(data, dict) else []

    def route_record(self, path: str):
        """One route's replay document from its record, if it is one of this project's."""
        from . import route_progress
        p = Path(path).resolve()
        if p.name != route_progress.RECORD or self.root.resolve() not in p.parents:
            return None
        return self._route_doc(p)

    def build_record(self, run: str, shape=None):
        """A run's whole build: its placement (plan.json) and then its route, from the run folder's records. `shape` as _route_doc's."""
        from . import route_progress
        d = self.run_folder(run, record=False)
        if d is None or self.root.resolve() not in d.resolve().parents:
            return None
        d = d.resolve()
        out = self._route_doc(d / "route" / route_progress.RECORD, d / "plan.json" if (d / "plan.json").is_file() else None, *self._run_board(d), shape=shape)
        if out is not None and out["doc"].get("score") is None:
            summary = self.run_summary(d / "run.json") if (d / "run.json").is_file() else None
            if summary and summary.get("score") is not None:
                out["doc"]["score"] = {"total": summary["score"]}          # the build is the run's: its score is the run's
        return out

    def _run_board(self, folder: Path) -> tuple:
        """(the board a run wrote, the folder its model paths are relative to): the run keeps a copy of the board it wrote in its folder,
        and `${KIPRJMOD}` in it names the board's own folder, which the run record gives."""
        project_dir = None
        try:
            given = json.loads((folder / "run.json").read_text()).get("paths", {}).get("pcb")
            if given and Path(given).parent.is_dir():
                project_dir = Path(given).parent
        except (OSError, ValueError, AttributeError):
            pass
        return folder / "layout.kicad_pcb", project_dir

    # ------------------------------------------------------------ the 3D models of a recorded board
    def _board_models(self, pcb: Path, project_dir=None) -> dict | None:
        """The 3D models of a board a run or a route wrote, as model_plan gives them for a live resolve: each footprint's entries by
        reference, the table of distinct models, the stackup and the converter's jobs. A record carries no models, so a page opening one
        gets them from here. Kept by file and modification time; None when the board cannot be read."""
        try:
            key = (str(pcb), pcb.stat().st_mtime_ns, str(project_dir or ""))
        except OSError:
            return None
        with self._models_lock:
            hit = self._models_cache.get(key)
            if hit is not None:
                return hit
            from .kicad.read import read_board
            from .model_convert import find_kicad_cli
            from .model_plan import ModelContext
            try:
                geometry = read_board(str(pcb))
            except (OSError, ValueError, RuntimeError):
                return None
            ctx = ModelContext(pcb, [d for d in (self.cfg.studio_3d_model_dirs or "").split(os.pathsep) if d], find_kicad_cli(self.cfg.studio_3d_kicad_cli),
                               project_dir=project_dir)
            refs = {fp.ref: ctx.written(fp) for fp in geometry.footprints}
            got = {"refs": refs, "table": ctx.table(), "stackup": ctx.stackup(geometry), "jobs": ctx.new_jobs(set())}
            for old in [k for k in self._models_cache if k[0] == key[0]]:
                del self._models_cache[old]
            self._models_cache[key] = got
            return got

    def _with_models(self, doc: dict, pcb: Path | None, project_dir=None) -> None:
        """Give a recorded document's members the 3D models of the board `pcb` (by reference) and queue the models for the converter, as a
        live resolve's items do (studio_3d.py)."""
        got = self._board_models(pcb, project_dir) if pcb is not None and pcb.is_file() else None
        if got is None:
            return
        for it in doc.get("items", ()):
            for m in it.get("members", ()):
                if m.get("ref") in got["refs"]:
                    m["models"] = [dict(e) for e in got["refs"][m["ref"]]]
        doc["models"], doc["stackup"] = got["table"], got["stackup"]
        self.m3d.submit(got["jobs"])

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
        explored = m.get("explore") if isinstance(m.get("explore"), dict) else {}
        kept = run_json.parent.parent.parent / "views" / "explore" / Path(str(explored.get("record") or "")).name if explored.get("record") else None
        out = {"id": run_json.parent.name, "run_id": rec.run_id, "label": rec.paths.get("label", "") if isinstance(rec.paths, dict) else "", "status": rec.status, "at": mtime,
               "board": rec.board, "script": rec.paths.get("script", "") if isinstance(rec.paths, dict) else "",
               "score": score, "findings": len(rec.findings), "severities": sev, "pid": rec.pid,
               "drc": {k: m.get(k) for k in ("drc_real", "outstanding", "other", "permitted", "unconnected") if k in m},
               "airwire_mm": m.get("airwire_mm"), "open_nets": len(m.get("open_nets") or {}),
               "checks": {k: m.get(k) for k in ("checks_failed", "checks_unjudged", "checks_accepted") if k in m},
               "verdicts": [{"check": v.get("check"), "subject": v.get("subject"), "ok": v.get("ok"), "note": v.get("note", "")}
                            for v in (rec.verdicts or []) if v.get("ok") is False][:20],
               "arrangements": [{"id": a["id"], "offered": a["offered"], "refused": len(a.get("refused") or ()),
                                 **({"duplicate_of": a["duplicate_of"]} if a.get("duplicate_of") else {}),
                                 **({"excluded": True} if a.get("excluded") else {})} for a in (rec.arrangements or [])],
               "timing": rec.timing_s, "explore": str(kept.resolve()) if kept is not None and kept.is_file() else "",
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
            return None if r is None else {"id": r["id"], "lines": r["lines"][-40:], "t0": r["t0"], "regenerate": r.get("regenerate", False)}

    def start_run(self, regenerate: bool = False) -> dict:
        """A checked run of the script (`placemat run --no-render`: the design checks, KiCad's DRC and the score, a run
        record), started on a thread; its progress and result go to the pages as `run_line` and `run_done`. A run generates
        the board again when its cached generation is out of date; `regenerate` says it is started for that, so the pages
        say so. A run that ends well with the last resolve showing an out of date generation is followed by a resolve."""
        with self.lock:
            if self.script is None:
                raise ValueError("choose a layout script first")
            if self._run is not None:
                raise ValueError("a run is already in progress")
            self._next_run = getattr(self, "_next_run", 0) + 1
            self._run = {"id": self._next_run, "lines": [], "t0": time.time(), "regenerate": bool(regenerate)}
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
            proc = subprocess.Popen(cmd, cwd=str(self.src.board_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env(headless=False))
            with self.lock:
                if self._run is not None:
                    self._run["pid"] = proc.pid
                for c in self.cmds.values():
                    if c.get("pid") == proc.pid:
                        c["own_run"] = rid
            self.hub.emit("run_started", {"id": rid, "at": t0, "pid": proc.pid, "regenerate": bool(self._run and self._run.get("regenerate"))})
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
        with self.lock:
            shown_stale = bool(self.history and self.history[-1].stale)
        if code == 0 and shown_stale:           # the run generated the board again: what is shown is from the old generation
            try:
                self.resolve_now()
            except ValueError:
                pass

    def run_doc(self, run_id: str) -> dict | None:
        """A recorded run as a plan document for the compare: its placements as items, its findings and score."""
        from .report import RunRecord
        if self.src is None or not run_id or "/" in run_id or run_id.startswith("."):
            return None                         # with no script chosen there is no resolve to compare a run with
        path = self.runs_dir() / run_id / "run.json"
        if not path.is_file():
            return None
        rec = RunRecord.load(path)
        summary = self.run_summary(path) or {}
        items = [{"key": k, "at": [v["x"], v["y"]], "rotation": v["rotation"], "face": v["face"],
                  **({"arrangement": v["arrangement"]} if v.get("arrangement") else {})} for k, v in rec.placements.items()]
        findings = [{"text": d["text"], "kind": d.get("kind", ""), "severity": d.get("severity", "warning"), "at": None, "item": ""}
                    for d in rec.findings_with_severity()]
        return {"items": items, "findings": findings, "unplaced": [], "score": {"total": summary["score"]} if summary.get("score") is not None else None}

    def compare_run(self, run_id: str) -> dict | None:
        """The newest resolve against a recorded run: what moved, was added or removed among the items the run placed,
        the findings gained and lost and the score. A run records no copper or links, so those are not compared."""
        from .studio_diff import _findings, _texts
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

    # ------------------------------------------------------------ the project's past runs
    def board_dirs(self) -> list:
        """The board folders of the project's layout scripts (and of the one watched), each once."""
        seen = []
        for s in self.scripts():
            if s["src"].board_dir not in seen:
                seen.append(s["src"].board_dir)
        if self.src is not None and self.src.board_dir not in seen:
            seen.append(self.src.board_dir)
        return seen

    def project_runs(self, limit: int = 40) -> list:
        """The recorded runs of every board of the project, newest first, as `runs()` lists a script's, each with its `kind` ("run")."""
        found = []
        for d in self.board_dirs():
            try:
                for r in (d / ".placemat" / "runs").iterdir():
                    if r.name.startswith(".") or r.is_symlink():          # a run still being staged; a label that names a run's folder
                        continue
                    rj = r / "run.json"
                    if rj.is_file():
                        found.append((rj.stat().st_mtime, rj))
            except OSError:
                continue
        out = []
        for _, rj in sorted(found, key=lambda f: -f[0]):
            s = self.run_summary(rj)
            if s is None or (s["status"] == "running" and s["pid"] and channel.pid_alive(s["pid"])):       # a run under way is a command running, not a past run
                continue
            out.append({**s, "kind": "run", "died": s["status"] == "running"})            # a record still "running" whose process is gone is a run that died
            if len(out) >= limit:
                break
        return out

    def run_folder(self, run_id: str, record: bool = True) -> Path | None:
        """A run's folder, if it is one of this project's boards'; with `record`, one that has its run.json."""
        if not run_id or "/" in run_id or run_id.startswith("."):
            return None
        for d in self.board_dirs():
            f = d / ".placemat" / "runs" / run_id
            if (f / "run.json").is_file() if record else f.is_dir():
                return f
        return None

    def run_view(self, run_id: str) -> dict | None:
        """A recorded run as the page shows a board it has not resolved: the run's build when it routed (build_record: its placement and the
        router's copper, from the run's own records), else the plan the run kept (plan.json) or the board the run wrote, and the run's findings
        and score. A run whose route record cannot be read is shown without the route, its doc's `route` saying why. Nothing is resolved.
        None when the run is not there or kept no board."""
        from . import route_progress, route_view
        from .report import RunRecord
        folder = self.run_folder(run_id)
        if folder is None:
            return None
        summary = self.run_summary(folder / "run.json")
        if summary is None:
            return None
        routed = (folder / "route" / route_progress.RECORD).is_file()
        if routed:
            b = self.build_record(run_id)
            if b is not None:
                return {"doc": b["doc"], "summary": summary}
        base = None
        try:
            base = json.loads((folder / "plan.json").read_text())
        except (OSError, ValueError):
            pass
        if base is None:
            pcb = folder / "layout.kicad_pcb"
            if not pcb.is_file():
                return None
            from .kicad.read import read_board
            base = route_view.board_doc(read_board(str(pcb)))
        findings = RunRecord.load(folder / "run.json").findings_with_severity()
        doc = route_view.run_doc(base, findings, summary.get("score"))
        if routed:
            doc["route"] = {"unread": {"code": "record_unreadable"}}
        self._with_models(doc, *self._run_board(folder))
        return {"doc": present.plan(doc), "summary": summary}

    # ------------------------------------------------------------ a past explore
    def explore_view(self, path: str = "", run: str = "") -> dict | None:
        """A finished explore as the page shows it: its record (`path`, or the one the run `run` made) and the board of its best variant.
        The board is, in turn: the run's build when the run kept the best and routed; the best variant's own plan, which a newer explore
        keeps (explore_view.BEST_DIR); the board the run wrote, as it is when the run kept the best, else with the focused items moved
        from the plain placement to the best's (explore_view.py). `source` says which ("build", "plan", "run", "moved"; "" and no `doc`
        when the explore left none of them), `drawn` where the board has each focused item and `unmoved` the focused items the move could
        not place as the best did. Nothing is resolved. None when the record is not one of this project's."""
        from . import explore_view, route_progress
        if run:
            folder = self.run_folder(run)
            path = ((self.run_summary(folder / "run.json") if folder is not None else None) or {}).get("explore") or ""
        record = self.explore_record(path)
        if record is None:
            return None
        p = Path(path).resolve()
        focus = list(record.get("focus") or ())
        plain = record.get("plain") or {}
        shown = record.get("taken_seed") if record.get("taken_seed") is not None else record.get("best_seed")     # what its routes took
        best = next((v.get("placements") or {} for v in record.get("variants", ()) if v.get("seed") == shown), None)
        best = plain if best is None or not shown else best
        at = {k: best.get(k) for k in focus}
        folder = self._explore_run(p, record)
        out = {"record": record, "file": str(p), "run": folder.name if folder is not None else "", "doc": None, "source": "", "drawn": at, "unmoved": [],
               "summary": self.run_summary(folder / "run.json") if folder is not None else None}
        kept = bool(record.get("kept"))
        gather = lambda board: explore_view.group_focus(board, focus, at)
        if folder is not None and kept and (folder / "route" / route_progress.RECORD).is_file():
            b = self.build_record(folder.name, shape=gather)
            if b is not None:
                return dict(out, doc=b["doc"], source="build", route=b["summary"])
        own = p.parent / explore_view.BEST_DIR / p.name
        if own.is_file():
            try:
                doc = json.loads(own.read_text())
            except (OSError, ValueError):
                doc = None
            if isinstance(doc, dict):
                self.m3d.submit(doc.pop("model_jobs", None) or [])
                return dict(out, doc=present.plan(doc), source="plan")
        if folder is None:
            return out
        if kept:
            view = self._run_doc(folder, gather)
            return out if view is None else dict(out, doc=present.plan(view), source="run")
        moves = {k: (plain.get(k), best.get(k)) for k in focus if plain.get(k) != best.get(k)}
        doc = self._run_doc(folder, lambda board: explore_view.group_focus(board, focus, plain), findings=False, score=record.get("best"))
        if doc is None:
            return out
        doc, moved = explore_view.move_items(doc, moves, (doc.get("stackup") or {}).get("thickness") or 1.6)
        drawn = {k: (best.get(k) if k in moved or k not in moves else plain.get(k)) for k in focus}
        return dict(out, doc=present.plan(doc), source="moved", drawn=drawn, unmoved=sorted(set(moves) - set(moved)))

    def _run_doc(self, folder: Path, shape, findings: bool = True, score=None) -> dict | None:
        """A run's board as run_view gives it, made over by `shape` first; without `findings` the run's findings are left out (they are
        of another placement), and `score` stands for the run's. None when the run kept no board."""
        from . import route_view
        from .report import RunRecord
        base = None
        try:
            base = json.loads((folder / "plan.json").read_text()) if findings else None
        except (OSError, ValueError):
            pass
        if base is None:
            pcb = folder / "layout.kicad_pcb"
            if not pcb.is_file():
                return None
            from .kicad.read import read_board
            base = route_view.board_doc(read_board(str(pcb)))
        summary = self.run_summary(folder / "run.json") or {}
        found = RunRecord.load(folder / "run.json").findings_with_severity() if findings else ()
        doc = route_view.run_doc(shape(base), found, summary.get("score") if score is None else score)
        if not findings:
            doc["findings"], doc["counts"] = [], dict(doc["counts"], findings=0)
        self._with_models(doc, *self._run_board(folder))
        return doc

    def _explore_run(self, record_path: Path, record: dict) -> Path | None:
        """The run an explore was part of: the one its record names, else the first run of its board recorded after it that names it."""
        if record.get("run"):
            return self.run_folder(str(record["run"]))
        runs = record_path.parent.parent.parent / "runs"
        at = float(record.get("at") or 0)
        found = []
        try:
            for d in runs.iterdir():
                rj = d / "run.json"
                if d.name.startswith(".") or d.is_symlink() or not rj.is_file():
                    continue
                t = rj.stat().st_mtime
                if t >= at - 1:
                    found.append((t, d))
        except OSError:
            return None
        for _, d in sorted(found)[:50]:
            s = self.run_summary(d / "run.json")
            if s and s.get("explore") == str(record_path):
                return d
        return None

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
        from .geometry import native_status
        from .finding_text import native_text
        status = native_status()
        common = {"native": status.facts(), "native_text": native_text(status.facts()) if status.warns else "", "now": time.time(), "origin": self.origin(), "port": self.port, "commands": [self._cmd_summary(c) for c in self.cmds.values()],
                  "explores": self.explores(), "routes": self.routes(), "project_runs": self.project_runs(), "explore_fps": self.cfg.studio_explore_fps, "follow_hold_s": self.cfg.studio_follow_hold_s,
                  "models3d": self.m3d.status(), "models": self.m3d.table(),
                  "applied": self.applied_list(), "can_apply": bool(self.cfg.studio_apply), "redo": self.redo_text(),
                  "notes": self.notes_list(), "note_age_s": self.cfg.studio_note_age_s, "builder": self.builder.hello()}
        if self.script is None:
            return {**common, "script": "", "picker": True, "root": str(self.root), "keep": self.keep, "title": "", "subtitle": "",
                    "scripts": self.script_list(), "history": [], "resolving": None, "error": None, "runs": [], "run": None}
        title, sub = script_titles(self.script, self.src)
        return {**common, "work": self._work_state(), "script": self.script.name, "script_path": str(self.script), "keep": self.keep, "title": title, "subtitle": sub,
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
                                                 "timing": last.timing, "reused": last.reused, "stale": last.stale,
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

        def _lib(self, path: str):
            """/3d/lib/<token>/<file>: the 3D view's script and the vendored three.js. The token is in the path so the modules the viewer
            imports by a relative name come with it."""
            from . import studio_3d
            host = (self.headers.get("Host") or "").lower()
            token, _, rest = path[len("/3d/lib/"):].partition("/")
            if host not in studio.allowed_hosts() or not hmac.compare_digest(token.encode(), studio.token.encode()):
                return self._refuse(403, "forbidden: open the address `placemat studio` printed")
            found = studio_3d.lib_file(rest)
            if found is None:
                return self._refuse(404, "not found")
            body = found[0].read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", found[1])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if rest == "viewer.js" else "private, max-age=86400")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path.startswith("/3d/lib/"):
                return self._lib(url.path)
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
                                   "timing": rec.timing, "reused": rec.reused, "stale": rec.stale})
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
            if path == "/route":
                doc = studio.route_record(query.get("f", [""])[0])
                return self._json(doc) if doc is not None else self._refuse(404, "no such route record")
            if path == "/build":
                doc = studio.build_record(query.get("run", [""])[0])
                return self._json(doc) if doc is not None else self._refuse(404, "no such run, or it did not route")
            if path == "/suggest/applied":
                try:
                    kind, ref = query.get("kind", [""])[0], query.get("ref", [""])[0]
                    return self._json(studio.applied_state({"kind": kind, "ref": ref} if kind else None))
                except SuggestRefused as e:
                    return self._send(e.status, "application/json", json.dumps({"error": str(e), **e.extra}).encode())
            if path == "/suggest/found":
                try:
                    kind, ref = query.get("kind", [""])[0], query.get("ref", [""])[0]
                    return self._json(studio.suggest_found(query.get("id", [""])[0], {"kind": kind, "ref": ref} if kind else None))
                except SuggestRefused as e:
                    return self._refuse(e.status, str(e))
            if path == "/viewsource":
                try:
                    return self._json(studio.view_source(query.get("kind", [""])[0], query.get("ref", [""])[0], query.get("file", [""])[0]))
                except SuggestRefused as e:
                    return self._send(e.status, "application/json", json.dumps({"error": str(e), **e.extra}).encode())
            if path == "/routes":
                return self._json(studio.routes())
            if path == "/3d/models":
                return self._json({"status": studio.m3d.status(), "models": studio.m3d.table()})
            if path.startswith("/3d/model/") and path.endswith(".pmm"):
                f = studio.m3d.mesh_path(path[len("/3d/model/"):-len(".pmm")])
                if f is None:
                    return self._refuse(404, "no such model")
                try:
                    body = f.read_bytes()
                except OSError:
                    return self._refuse(404, "no such model")
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "private, max-age=31536000, immutable")     # the id is the content
                self.send_header("ETag", '"%s"' % f.stem.split("-", 1)[1])
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/exploreview":
                doc = studio.explore_view(query.get("f", [""])[0], query.get("run", [""])[0])
                return self._json(doc) if doc is not None else self._refuse(404, "no such explore record")
            if path == "/explore":
                doc = studio.explore_record(query.get("f", [""])[0])
                return self._json(doc) if doc is not None else self._refuse(404, "no such explore record")
            if path == "/builder.js":
                return self._send(200, "text/javascript; charset=utf-8", BUILDER_JS.read_bytes())
            if path.startswith("/build/"):
                return self._build(path, query, None)
            if path == "/runs":
                return self._json(studio.runs())
            if path == "/explores":
                return self._json(studio.explores())
            if path == "/projectruns":
                return self._json(studio.project_runs())
            if path == "/runview":
                doc = studio.run_view(query.get("run", [""])[0])
                return self._json(doc) if doc is not None else self._refuse(404, "no such run, or it kept no board")
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
            if url.path.startswith("/build/"):
                if not self._allowed(parse_qs(url.query)):
                    return self._refuse(403, "forbidden: open the address `placemat studio` printed")
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 65536)
                    body = json.loads(self.rfile.read(n) or b"{}")
                except (ValueError, TypeError) as e:
                    return self._send(400, "application/json", json.dumps({"error": str(e)}).encode())
                return self._build(url.path, parse_qs(url.query), body)
            if url.path not in ("/switch", "/run", "/resolve", "/suggest/show", "/suggest/try", "/suggest/apply", "/suggest/undo", "/suggest/redo", "/suggest/probe", "/suggest/probe/stop", "/3d/retry"):
                return self._no()
            if not self._allowed(parse_qs(url.query)):
                return self._refuse(403, "forbidden: open the address `placemat studio` printed")
            if url.path.startswith("/suggest/"):
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4096)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    call = {"/suggest/show": studio.suggest_show, "/suggest/try": studio.suggest_try, "/suggest/apply": studio.suggest_apply}
                    if url.path == "/suggest/undo":
                        return self._json(studio.suggest_undo(body.get("view")))
                    if url.path == "/suggest/redo":
                        return self._json(studio.suggest_redo(body.get("view")))
                    if url.path == "/suggest/probe/stop":
                        return self._json(studio.probe_stop())
                    if url.path == "/suggest/probe":
                        return self._json(studio.probe_start(body.get("resolve"), str(body.get("id", "")), bool(body.get("yes")), body.get("view")))
                    return self._json(call[url.path](body.get("resolve"), str(body.get("id", "")), body.get("view")))
                except SuggestRefused as e:
                    return self._send(e.status, "application/json", json.dumps({"error": str(e), **e.extra}).encode())
                except (ValueError, TypeError, AttributeError) as e:
                    return self._send(400, "application/json", json.dumps({"error": str(e)}).encode())
            if url.path == "/3d/retry":
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4096)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    rid = body.get("id")
                    return self._json({"queued": studio.m3d.retry(rid if isinstance(rid, str) else None)})
                except (ValueError, TypeError) as e:
                    return self._refuse(400, str(e))
            if url.path == "/run":
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4096)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    return self._json(studio.start_run(bool(body.get("regenerate"))))
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

        def _build(self, path, query, body):
            """The board builder's endpoints (studio_builder.BuilderService): GET reads, POST acts; a refusal is JSON with the rule."""
            from .studio_builder import BuildRefused
            if not self._allowed(query):
                return self._refuse(403, "forbidden: open the address `placemat studio` printed")
            try:
                return self._json(studio.builder.handle(path, query, body))
            except BuildRefused as e:
                return self._send(e.status, "application/json", json.dumps({"error": str(e), **e.extra}).encode())
            except (ValueError, TypeError, KeyError, AttributeError) as e:
                return self._send(400, "application/json", json.dumps({"error": "%s: %s" % (type(e).__name__, e)}).encode())

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
            code = qr.to_terminal(qr.encode(url))
            console.say("studio", "share link: scan this code to open the studio on another device on this network")
            console.data("\n" + "\n".join("  " + line for line in code.splitlines()) + "\n")     # set off from the log lines
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
