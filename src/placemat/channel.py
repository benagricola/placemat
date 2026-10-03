"""The live channel: how a placemat command tells the studios of its project what it is doing.

Each studio listens on a Unix socket in its project, `<project root>/.placemat/studio/<pid>.sock`, with a registry
entry beside it, `<pid>.json` (pid, socket, started, address, script). A command that resolves a board looks, the
first time it does, for that directory; with studios in it, it connects to all of them and sends newline-delimited JSON:
`hello`, then what the studio's own worker sends (`board`, `item`, `begin`), a `plan` for each finished resolve, for an
explore `explore`, a `variant` each and `explore_done`, and at the end `done` (the record's path) or `error`.

The command is never in the way. With no studio there is one directory check, once. With one, a thread takes the
events from a small bounded queue and writes them; a full queue drops the event, and a socket that goes away is
dropped silently. Linux and macOS (Unix sockets) only: elsewhere nothing is looked for. The studio reads only these
events and the records a command writes, never its printed text."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import queue
import socket
import sys
import tempfile
import threading
import time

REGISTRY = (".placemat", "studio")
QUEUE_SIZE = 512
_state = {"checked": False, "reporter": None, "off": False}


def disable() -> None:
    """This process never reports (an explore's worker processes, the studio's own resolve worker)."""
    _state["off"] = True
    _state["reporter"] = None


# ------------------------------------------------------------------ the registry
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, OSError):
        return True
    return True


def registry_dir(start) -> Path | None:
    """The nearest `.placemat/studio` directory at or above `start`: the project's, where a studio listens."""
    d = Path(start).resolve()
    for p in [d, *d.parents]:
        cand = p.joinpath(*REGISTRY)
        if cand.is_dir():
            return cand
    return None


def live_entries(directory: Path) -> list:
    """The registry's entries whose studio is alive; the dead ones' files are removed as they are found."""
    out = []
    try:
        names = sorted(directory.glob("*.json"))
    except OSError:
        return out
    for f in names:
        try:
            entry = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if _pid_alive(entry.get("pid", -1)) and entry.get("socket"):
            out.append(entry)
            continue
        for path in (f, Path(str(entry.get("socket", "")))):
            try:
                path.unlink()
            except OSError:
                pass
    return out


# ------------------------------------------------------------------ the studio's side
class Listener:
    """A studio's socket: events arrive as `on_event(connection id, event)`; a connection that closes is told as
    `{"ev": "lost"}`."""

    def __init__(self, root, on_event, address: str = "", script: str = ""):
        self.root, self.on_event, self.address, self.script = Path(root), on_event, address, script
        self.pid = os.getpid()
        self.directory = self.root.joinpath(*REGISTRY)
        self.sock_path: Path | None = None
        self.entry: Path | None = None
        self.server: socket.socket | None = None
        self._next = 0
        self._stopped = False

    def start(self) -> None:
        if not hasattr(socket, "AF_UNIX"):
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        live_entries(self.directory)                                    # whoever died here is cleaned away
        path = self.directory / ("%d.sock" % self.pid)
        if len(str(path).encode()) > 100:                               # a socket address is short: a short path elsewhere, named in the entry
            short = Path(tempfile.gettempdir()) / ("placemat-studio-%d" % os.getuid())
            short.mkdir(mode=0o700, exist_ok=True)
            path = short / ("%d.sock" % self.pid)
        try:
            path.unlink()
        except OSError:
            pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        os.chmod(str(path), 0o600)
        self.server.listen(16)
        self.sock_path = path
        self.entry = self.directory / ("%d.json" % self.pid)
        self.entry.write_text(json.dumps({"pid": self.pid, "socket": str(path), "started": time.time(), "address": self.address,
                                          "script": self.script}))
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while not self._stopped:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self._next += 1
            threading.Thread(target=self._read, args=(conn, self._next), daemon=True).start()

    def _read(self, conn, cid: int) -> None:
        try:
            with conn, conn.makefile("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(ev, dict):
                        self.on_event(cid, ev)
        except OSError:
            pass
        self.on_event(cid, {"ev": "lost"})

    def stop(self) -> None:
        self._stopped = True
        if self.server is not None:
            try:
                self.server.close()
            except OSError:
                pass
        for p in (self.sock_path, self.entry):
            if p is not None:
                try:
                    p.unlink()
                except OSError:
                    pass


# ------------------------------------------------------------------ a command's side
class Reporter:
    """The command's connection to the studios: `send` never waits."""

    def __init__(self, entries: list, hello: dict):
        self.entries, self.hello = entries, hello
        self.queue: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        self.dropped = 0
        self.record = None
        self.error_sent = False
        self._finished = False
        self._conns: list = []
        self._resolves = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.send(dict(hello, ev="hello"))

    def send(self, event: dict) -> None:
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1                                           # backpressure: the event is lost, the command goes on

    def _connect(self) -> None:
        for e in self.entries:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.25)
            try:
                s.connect(e["socket"])
            except OSError:
                s.close()
                continue
            self._conns.append(s)

    def _run(self) -> None:
        try:
            self._connect()
        except Exception:
            self._conns = []
        while True:
            ev = self.queue.get()
            if ev is None:
                break
            if not self._conns:
                continue                                                # nobody is listening any more: events are dropped as they come
            line = (json.dumps(ev, separators=(",", ":"), default=str) + "\n").encode()
            for s in list(self._conns):
                try:
                    s.sendall(line)
                except OSError:
                    self._conns.remove(s)
                    try:
                        s.close()
                    except OSError:
                        pass
        for s in self._conns:
            try:
                s.close()
            except OSError:
                pass

    # ---- what a command says about itself
    def error(self, message: str, file: str = "", line=None) -> None:
        self.error_sent = True
        self.send({"ev": "error", "message": message, "file": file, "line": line})

    def finish(self, record=None) -> None:
        if self._finished:
            return
        self._finished = True
        if not self.error_sent:
            self.send({"ev": "done", "record": str(record or self.record or ""), "dropped": self.dropped})
        try:
            self.queue.put(None, timeout=0.5)
        except queue.Full:
            return
        self.thread.join(timeout=1.0)

    # ---- the resolve's events, the same the studio's worker sends
    def hooks(self, board, on_step, on_begin):
        """`on_step` and `on_begin` for a resolve that also tell the studios."""
        from .preview_json import board_json, declared_sites, item_json, step_extras
        self._resolves += 1
        self.send({"ev": "resolve", "n": self._resolves})
        state = {"sites": declared_sites(board), "board": False, "phase": 0.0}

        def step(plan, s):
            if on_step is not None:
                on_step(plan, s)
            if not state["board"]:
                state["board"] = True
                self.send({"ev": "board", **board_json(plan)})
            self.send({"ev": "item", "item": item_json(plan, s, state["sites"]), **step_extras(plan, s)})

        def begin(plan, info):
            if on_begin is not None:
                on_begin(plan, info)
            if info.get("kind") == "phase":
                now = time.monotonic()
                if now - state["phase"] < 0.25:
                    return
                state["phase"] = now
            self.send({"ev": "begin", **info, "at": time.time()})

        return step, begin

    def plan(self, board, plan) -> None:
        """The finished plan of a resolve: copper, links, findings, the steps in order."""
        from .preview_json import declared_sites, plan_json
        try:
            self.send({"ev": "plan", "doc": plan_json(plan, declared_sites(board))})
        except Exception as e:                                          # a courtesy: the command is not to fail for it
            print("channel: plan: %s: %s" % (type(e).__name__, e), file=sys.stderr)


def reporter(script=None):
    """The command's reporter, or None: when no studio listens in its project (decided once), or reporting is off."""
    if _state["checked"]:
        return _state["reporter"]
    _state["checked"] = True
    if _state["off"] or os.environ.get("PLACEMAT_CHANNEL") == "off" or not hasattr(socket, "AF_UNIX"):
        return None
    start = Path(script).resolve().parent if script else _script_from_argv()
    d = registry_dir(start) if start is not None else None
    if d is None:
        return None
    entries = live_entries(d)
    if not entries:
        return None
    argv = sys.argv[1:]
    command = next((a for a in argv if not a.startswith("-")), Path(sys.argv[0]).name if sys.argv else "placemat")
    hello = {"command": command, "pid": os.getpid(), "script": str(Path(script).resolve()) if script else _first_script(argv),
             "args": argv[:20], "started": time.time(), "cwd": os.getcwd()}
    rep = Reporter(entries, hello)
    _state["reporter"] = rep
    atexit.register(rep.finish)
    return rep


def _first_script(argv):
    for a in argv:
        if a.endswith(".py") and Path(a).is_file():
            return str(Path(a).resolve())
    return ""


def _script_from_argv():
    s = _first_script(sys.argv[1:])
    return Path(s).parent if s else Path.cwd()


def current():
    """The reporter if this command has one (never starts one)."""
    return _state["reporter"]


def error(message: str, file: str = "", line=None) -> None:
    rep = _state["reporter"]
    if rep is not None:
        rep.error(message, file, line)


def finish(record=None) -> None:
    rep = _state["reporter"]
    if rep is not None:
        rep.finish(record)


def reset() -> None:
    """Forget what was decided (tests)."""
    rep = _state["reporter"]
    if rep is not None:
        rep.finish()
    _state.update({"checked": False, "reporter": None, "off": False})
