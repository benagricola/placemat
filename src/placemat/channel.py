"""The live channel: a placemat command streams what it does on a socket it owns, for any reader that wants to follow it.

A command that resolves a board (run, preview, an explore inside them, route, check) listens, from its first resolve and
for as long as it runs, on `<project root>/.placemat/sockets/<pid>.sock`, with `<pid>.json` beside it (pid, socket,
command, script, arguments, started, label, the path of its progress file). Readers - the studio, `placemat watch`, an
agent - look in that folder and connect to whichever they want. One that connects mid-run is sent a catch-up first
(`hello`, the board, the steps and the plan so far) and then the live events, newline-delimited JSON: `hello`, `resolve`,
`board`, `item`, `begin`, `plan`, for an explore `explore`, `variant` and `explore_done`, for a probe of a searched suggestion `probe`, `candidate` and `probe_done`, and at the end `done` (the
record's path) or `error`.

What is sent is records, never sentences: an event is numbers, names, enums and the facts of what happened (a step's `notes`, an
`error`'s `kind` and fields), and `describe` and the studio (present.py) are the places that turn them into words. `FORMAT` is the
version of that: `hello` carries it, and a reader that finds none reads format 1, which had sentences in `item`, `error` and `route_off`.

The command never waits on a reader: each has a bounded queue that drops what does not fit, and a reader that goes
away is dropped. Its events are also mirrored, in short form, into an append-only progress file flushed as it goes, so a
command that dies leaves its last state; it is read only for a command that ended or died, never as the live feed. A
command that starts deletes the progress files that earlier commands of its script left, once they are no longer
running. Linux and macOS (Unix sockets): elsewhere nothing is done. The studio reads only these events and the records a
command writes, never its printed text."""
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

SOCKETS = (".placemat", "sockets")
FORMAT = 2                          # of the events: 2 has records where 1 had sentences (item `note`, error `message`, route_off `why`, probe `text`)
QUEUE_SIZE = 256                    # a reader's events beyond its catch-up
MAX_LOG = 6000                      # events kept for a catch-up
MAX_ROUTE_LOG = 60000               # a route's events (its copper, net by net) kept for a catch-up: far more of them, each small
_state = {"checked": False, "reporter": None, "off": False, "hint": None}


def disable() -> None:
    """This process never reports (an explore's worker processes, the studio's own resolve worker)."""
    _state["off"] = True
    _state["reporter"] = None


class paused:
    """With it, this process reports nothing: the resolves a probe makes of each candidate are not the command's own plan, so they
    are not sent to the readers (the probe's own events are, after it)."""

    def __enter__(self):
        self.held = _state["reporter"]
        _state["reporter"] = None
        _state["was_checked"] = _state["checked"]
        _state["checked"] = True
        return self

    def __exit__(self, *exc):
        _state["reporter"] = self.held
        _state["checked"] = _state.pop("was_checked", _state["checked"])


def send(event: dict) -> None:
    """Tell the readers an event of this command's own (a probe's), if it has a beacon."""
    rep = _state["reporter"]
    if rep is not None:
        rep.send(event)


def hint_progress(path) -> None:
    """Where this command's progress file goes (a run's folder), said before its first resolve."""
    _state["hint"] = Path(path)


# ------------------------------------------------------------------ for readers: finding the sockets
def sockets_dir(root) -> Path:
    return Path(root).joinpath(*SOCKETS)


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, OSError):
        return True
    return True


def scan(directory) -> tuple:
    """(live, dead): the entries in a sockets folder, the commands whose pid is gone apart from those still there."""
    live, dead = [], []
    try:
        names = sorted(Path(directory).glob("*.json"))
    except OSError:
        return live, dead
    for f in names:
        try:
            entry = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        entry["_file"] = str(f)
        (live if pid_alive(entry.get("pid", -1)) else dead).append(entry)
    return live, dead


def clean(entry) -> None:
    """Remove a dead command's entry and socket."""
    for p in (entry.get("_file"), entry.get("socket")):
        if p:
            try:
                Path(p).unlink()
            except OSError:
                pass


def last_state(path, limit: int = 400) -> list:
    """The events a command mirrored into its progress file, in order (the last `limit`), for one that has ended or died."""
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-limit:]


def follow(entry, timeout: float = 2.0):
    """The events of a live command, from its catch-up on, until it ends. Yields dicts."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(entry["socket"])
    s.settimeout(None)
    try:
        with s.makefile("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    yield ev
    except OSError:
        return
    finally:
        s.close()


class Watcher:
    """Follows every command of a project: each live socket gets a reader thread whose events go to `on_event(connection id,
    event)` (a connection that ends is told as `{"ev": "lost"}`); a command found dead is given to `on_dead(connection id, entry, events)`
    with its last state from its progress file, and its entry is cleaned away."""

    def __init__(self, root, on_event, on_dead=None, interval: float = 1.0):
        self.dir, self.on_event, self.on_dead, self.interval = sockets_dir(root), on_event, on_dead, interval
        self._seen: set = set()
        self._next = 0
        self._stop = threading.Event()
        self.thread = None

    def _new_id(self) -> int:
        self._next += 1
        return self._next

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, daemon=True, name="placemat-channel-watch")
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll(self) -> None:
        live, dead = scan(self.dir)
        for e in live:
            key = (e.get("pid"), e.get("started"))
            if key in self._seen:
                continue
            self._seen.add(key)
            threading.Thread(target=self._read, args=(e, self._new_id()), daemon=True, name="placemat-channel-follow").start()
        for e in dead:
            key = (e.get("pid"), e.get("started"))
            if key not in self._seen:
                self._seen.add(key)
                if self.on_dead is not None:
                    self.on_dead(self._new_id(), e, last_state(e["progress"]) if e.get("progress") else [])
            clean(e)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception as e:                                      # a reader of a folder does not die of what is in it
                print("channel: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            self._stop.wait(self.interval)

    def _read(self, entry, cid: int) -> None:
        try:
            for ev in follow(entry):
                self.on_event(cid, ev)
        except OSError:
            pass
        self.on_event(cid, {"ev": "lost"})


# ------------------------------------------------------------------ the command's side
def compact(ev: dict):
    """An event in the short form kept in a progress file: what says where the command was, not the drawing."""
    kind = ev.get("ev")
    if kind in ("hello", "resolve", "done", "error", "explore_done"):
        return {k: v for k, v in ev.items() if k not in ("doc",)}
    if kind == "begin":
        if ev.get("kind") == "phase":
            return None
        return {k: ev[k] for k in ("ev", "kind", "item", "what", "rank", "of", "replaying", "n", "items", "searched", "copper", "at") if k in ev}
    if kind == "item":
        it = ev.get("item") or {}
        return {"ev": "item", "key": it.get("key"), "kind": it.get("kind"), "placed": it.get("placed"),
                "seconds": it.get("seconds"), "first_seconds": it.get("first_seconds"), "notes": it.get("notes") or [],
                **({"unplaced": it["unplaced"]} if it.get("unplaced") is not None else {})}
    if kind == "plan":
        doc = ev.get("doc") or {}
        return {"ev": "plan", "items": len(doc.get("items", ())), "findings": len(doc.get("findings", ())), "copper": len(doc.get("copper", ()))}
    if kind == "explore":
        return {"ev": "explore", "focus": len(ev.get("focus", ())), "baseline": ev.get("baseline"), "jobs": ev.get("jobs")}
    if kind == "route_queue":
        return {"ev": "route_queue", "nets": len(ev.get("nets", ())), "stage": ev.get("stage")}
    if kind in ("route_stage", "route_net_end", "route_queue_end", "route_off"):
        return {k: v for k, v in ev.items() if k != "doc"}
    if kind == "variant":
        return {k: ev[k] for k in ("ev", "seed", "score", "t") if k in ev}
    if kind in ("probe", "candidate", "probe_done"):
        return {k: v for k, v in ev.items() if k not in ("candidates",) or kind == "probe"}
    return None


class _Reader:
    """One connected reader: a bounded queue and a thread that writes it; dropped when its socket fails."""

    def __init__(self, conn, beacon, backlog: list):
        self.conn, self.beacon, self.dropped = conn, beacon, 0
        self.queue: queue.Queue = queue.Queue(maxsize=len(backlog) + QUEUE_SIZE)
        for ev in backlog:
            self.queue.put_nowait(ev)
        self.thread = threading.Thread(target=self._run, daemon=True, name="placemat-channel-reader")
        self.thread.start()

    def put(self, ev) -> None:
        try:
            self.queue.put_nowait(ev)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        self.conn.settimeout(1.0)
        while True:
            ev = self.queue.get()
            if ev is None:
                break
            try:
                self.conn.sendall((json.dumps(ev, separators=(",", ":"), default=str) + "\n").encode())
            except OSError:
                break
        self.beacon._drop(self)
        try:
            self.conn.close()
        except OSError:
            pass


class Beacon:
    """The command's socket, its registry entry, its readers, the catch-up it keeps and its progress file."""

    def __init__(self, root, board_dir, hello: dict, progress=None):
        self.root, self.board_dir = Path(root), Path(board_dir)
        self.directory = sockets_dir(self.root)
        self.hello = dict(hello, ev="hello", format=FORMAT)
        self.pid = os.getpid()
        self.lock = threading.Lock()
        self.log: list = []
        self.route_log: list = []                                       # a route's events, apart from `log`: there are many and each is small
        self.route_truncated = False
        self.readers: list = []
        self.record = None
        self.error_sent = False
        self._finished = False
        self._resolves = 0
        self.server = None
        self.sock_path = self.entry = None
        self.progress_path = Path(progress) if progress else self._default_progress()
        self._progress = None
        self.hello["progress"] = str(self.progress_path)

    def _default_progress(self) -> Path:
        name = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(self.hello.get("command") or "command")) or "command"
        return self.board_dir / ".placemat" / "views" / name / ("progress-%d.jsonl" % self.pid)

    def start(self) -> None:
        self._clean_progress()
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / ("%d.sock" % self.pid)
        if len(str(path).encode()) > 100:                               # a socket address is short: a short path elsewhere, named in the entry
            short = Path(tempfile.gettempdir()) / ("placemat-sockets-%d" % os.getuid())
            short.mkdir(mode=0o700, exist_ok=True)
            path = short / ("%d.sock" % self.pid)
        try:
            path.unlink()
        except OSError:
            pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        os.chmod(str(path), 0o600)
        self.server.listen(8)
        self.sock_path = path
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self._progress = open(self.progress_path, "a", encoding="utf-8")
        self._mirror(self.hello)
        self.entry = self.directory / ("%d.json" % self.pid)
        self.entry.write_text(json.dumps({k: self.hello.get(k) for k in ("pid", "command", "script", "args", "started", "label", "progress")} |
                                         {"socket": str(path)}))
        threading.Thread(target=self._accept, daemon=True, name="placemat-channel-accept").start()

    def _clean_progress(self) -> None:
        """Delete the progress files that earlier commands of this script left, once they are no longer running: what a
        command that died left stays until the script's next command, and nothing piles up."""
        base = self.board_dir / ".placemat"
        script = self.hello.get("script")
        for pattern in ("runs/*/progress.jsonl", "views/*/progress-*.jsonl"):
            for f in base.glob(pattern):
                if f == self.progress_path:
                    continue
                try:
                    with open(f, "r", encoding="utf-8", errors="replace") as fh:
                        first = json.loads(fh.readline() or "{}")
                except (OSError, ValueError):
                    continue
                if first.get("script") == script and not pid_alive(first.get("pid", -1)):
                    try:
                        f.unlink()
                    except OSError:
                        pass

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with self.lock:                                             # the catch-up and the join to live events are one step
                backlog = [self.hello] + list(self.log) + list(self.route_log)
                self.readers.append(_Reader(conn, self, backlog))

    def _drop(self, reader) -> None:
        with self.lock:
            if reader in self.readers:
                self.readers.remove(reader)

    # ---- the events
    def send(self, event: dict) -> None:
        """Tell the readers and the progress file; never waits."""
        kind = event.get("ev")
        keep = not (kind == "begin" and event.get("kind") == "phase")
        with self.lock:
            if kind == "resolve":
                self.log = [e for e in self.log if e.get("ev") not in ("board", "item", "plan", "begin")]
            if kind and kind.startswith("route_"):
                if len(self.route_log) < MAX_ROUTE_LOG:
                    self.route_log.append(event)
                elif not self.route_truncated:
                    self.route_truncated = True
                    self.route_log.append({"ev": "route_truncated", "at": len(self.route_log)})
            elif keep and len(self.log) < MAX_LOG:
                self.log.append(event)
            for r in self.readers:
                r.put(event)
        self._mirror(event)

    def _mirror(self, event: dict) -> None:
        if self._progress is None:
            return
        short = compact(event)
        if short is None:
            return
        try:
            self._progress.write(json.dumps(short, separators=(",", ":"), default=str) + "\n")
            self._progress.flush()
        except (OSError, ValueError):
            self._progress = None

    def error(self, kind: str, file: str = "", line=None, **fields) -> None:
        """The command failed: an `error` event of this `kind` (`failure_text` says what each is) and its fields."""
        self.error_sent = True
        self.send({"ev": "error", "kind": kind, "file": file, "line": line, **fields})

    def stopped(self, record: dict) -> None:
        """The command was stopped (stop.record): an error event carrying the record, not a sentence; `describe` renders it."""
        self.error_sent = True
        self.send({"ev": "error", **record})

    def finish(self, record=None) -> None:
        if self._finished:
            return
        self._finished = True
        if not self.error_sent:
            self.send({"ev": "done", "record": str(record or self.record or "")})
        with self.lock:
            readers = list(self.readers)
            for r in readers:
                r.put(None)
        for r in readers:
            r.thread.join(timeout=1.0)
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
        if self._progress is not None:
            try:
                self._progress.close()
            except OSError:
                pass

    @property
    def dropped(self) -> int:
        with self.lock:
            return sum(r.dropped for r in self.readers)

    # ---- the resolve's events, the same the studio's worker sends
    def hooks(self, board, on_step, on_begin):
        """`on_step` and `on_begin` for a resolve that also tell the readers."""
        from .preview_json import board_json, declared_sites, item_json, step_extras
        self._resolves += 1
        self.send({"ev": "resolve", "n": self._resolves})
        state = {"sites": declared_sites(board), "board": False, "phase": 0.0, "models": None, "sent": set()}

        def step(plan, s):
            if on_step is not None:
                on_step(plan, s)
            if not state["board"]:
                state["board"] = True
                self.send({"ev": "board", **board_json(plan)})
            if state["models"] is None:
                state["models"] = _model_context(plan) or False
            ctx = state["models"] or None
            ev = {"ev": "item", "item": item_json(plan, s, state["sites"], ctx), **step_extras(plan, s)}
            if ctx is not None:                                       # the models this item uses that the studio has not been told of: for its converter
                jobs = ctx.new_jobs(state["sent"])
                if jobs:
                    ev["model_jobs"] = jobs
            self.send(ev)

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
            self.send({"ev": "plan", "doc": plan_json(plan, declared_sites(board), None, _model_context(plan))})
        except Exception as e:                                          # a courtesy: the command is not to fail for it
            print("channel: plan: %s: %s" % (type(e).__name__, e), file=sys.stderr)


def _model_context(plan):
    """The 3D view's model context for the board `plan` was read from (model_plan.py), or None when it cannot be made."""
    try:
        from .model_convert import find_kicad_cli
        from .model_plan import ModelContext
        from .settings import active
        s = active()
        return ModelContext(plan.geometry.path, [d for d in (s.studio_3d_model_dirs or "").split(os.pathsep) if d], find_kicad_cli(s.studio_3d_kicad_cli))
    except Exception:
        return None


def reporter(script=None):
    """The command's beacon, or None: for a board with no script (a bench, a test), where reporting is off, or where the
    socket cannot be made. Made once, at the first resolve."""
    if _state["checked"]:
        return _state["reporter"]
    _state["checked"] = True
    if _state["off"] or script is None or os.environ.get("PLACEMAT_CHANNEL") == "off" or not hasattr(socket, "AF_UNIX"):
        return None
    try:
        from .studio import project_root
        script = Path(script).resolve()
        board_dir = script.parent                                       # a layout script sits beside its board
        root = project_root(board_dir)
        argv = sys.argv[1:]
        command = next((a for a in argv if not a.startswith("-")), Path(sys.argv[0]).name if sys.argv else "placemat")
        label = ""
        if "--label" in argv and argv.index("--label") + 1 < len(argv):
            label = argv[argv.index("--label") + 1]
        hello = {"command": command, "pid": os.getpid(), "script": str(script), "args": argv[:20], "started": time.time(), "label": label,
                 "cwd": os.getcwd()}
        rep = Beacon(root, board_dir, hello, progress=_state["hint"])
        rep.start()
    except Exception as e:                                              # a project that cannot be listened in is run as without
        print("channel: not reporting: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return None
    _state["reporter"] = rep
    atexit.register(rep.finish)
    return rep


def current():
    """The beacon if this command has one (never starts one)."""
    return _state["reporter"]


def error(kind: str, file: str = "", line=None, **fields) -> None:
    rep = _state["reporter"]
    if rep is not None:
        rep.error(kind, file, line, **fields)


def exception(e: BaseException, file: str = "", line=None) -> None:
    """The command failed with `e`: its type and its own text, beside the file and line it names."""
    error("exception", file, line, type=type(e).__name__, detail=str(e))


def stopped(record: dict) -> None:
    rep = _state["reporter"]
    if rep is not None:
        rep.stopped(record)


def finish(record=None) -> None:
    rep = _state["reporter"]
    if rep is not None:
        rep.finish(record)


def reset() -> None:
    """Forget what was decided (tests)."""
    rep = _state["reporter"]
    if rep is not None:
        rep.finish()
    _state.update({"checked": False, "reporter": None, "off": False, "hint": None})


# ------------------------------------------------------------------ placemat watch
def describe(ev: dict) -> str:
    """One line for an event, for `placemat watch`."""
    kind = ev.get("ev")
    if kind == "hello":
        return "%s %s%s" % (ev.get("command", ""), Path(ev.get("script") or "").name, (" (%s)" % ev["label"]) if ev.get("label") else "")
    if kind == "resolve":
        return "resolve %s" % ev.get("n", "")
    if kind == "begin":
        if ev.get("kind") == "total":
            return "%s steps" % ev.get("n", "")
        return "begin %s" % " ".join(str(ev[k]) for k in ("kind", "item", "what") if ev.get(k))
    if kind == "item":
        it = ev.get("item") or ev
        from . import step_text
        note = step_text.render_all(it.get("notes") or (), it.get("unplaced"))
        return "%s %s%s" % (it.get("key", "?"), it.get("kind", ""), (": %s" % note) if note else "")
    if kind == "plan":
        doc = ev.get("doc") or {}
        n = len(doc["items"]) if "items" in doc else ev.get("items", 0)
        f = len(doc["findings"]) if "findings" in doc else ev.get("findings", 0)
        return "plan: %d items, %d findings" % (n, f)
    if kind == "explore":
        return "explore: %s" % (("baseline %s" % ev["baseline"]) if ev.get("baseline") is not None else "started")
    if kind == "variant":
        return "variant seed %s score %s" % (ev.get("seed"), ev.get("score"))
    if kind == "explore_done":
        return "explore done: best %s of baseline %s, kept %s" % (ev.get("best"), ev.get("baseline"), ev.get("kept"))
    if kind in ("route_commit", "route_rip", "route_net_begin", "route_board"):
        return ""                                          # the copper itself: the studio draws it, `watch` says each net's result
    if kind == "route_stage":
        return "route %s%s" % (ev.get("stage", ""), " (taken from an earlier route)" if ev.get("resumed") else "")
    if kind == "route_queue":
        return "route: %d nets to route" % len(ev.get("nets", ()))
    if kind == "route_net_end":
        return "net %s: %s" % (ev.get("net"), "routed" if ev.get("ok") else "no route found")
    if kind == "route_queue_end":
        return "route: %s routed, %s failed" % (ev.get("routed"), ev.get("failed"))
    if kind == "route_off":
        from .kicad import route_events
        return "no progress for this route: %s" % route_events.reason_text(ev.get("reason") or {})
    if kind == "route_truncated":
        return "route: more events than are kept for a late reader"
    if kind in ("probe", "candidate", "probe_done"):
        from . import probe
        return probe.line(ev)
    if kind == "done":
        return "done%s" % ((" " + ev["record"]) if ev.get("record") else "")
    if kind == "error" and ev.get("kind") == "stopped":
        from . import stop
        return stop.line(ev)
    if kind == "error":
        return "error: %s%s" % (failure_text(ev), (" (%s:%s)" % (ev.get("file"), ev.get("line"))) if ev.get("file") else "")
    return str(kind)


FAILURES = {"generation": "Schematic generation failed", "script": "Layout script failed",
            "placement": "Firm placements collide; fix the script (or --keep-going to see the rest)"}


def failure_text(ev: dict) -> str:
    """What an `error` event says, as a person reads it. Its `kind`: `run_failure` (`failure` is the stage, `detail` the free text of
    what raised it, `item` the item a placement failure names), `exception` (`type`, `detail`), `probe_refused` (probe.refusal_text),
    `lost` (the connection ended with no `done`; `last` is the last event seen), `died` (the same, from the trail), `cannot_follow`
    (`detail`)."""
    kind = ev.get("kind")
    if kind == "stopped":
        from . import stop
        return stop.line(ev)
    if kind == "run_failure":
        failure, detail = ev.get("failure", ""), ev.get("detail", "")
        base = None if ev.get("item") else FAILURES.get(failure)
        if base is None:
            return detail or failure
        return base + ((": " + detail) if detail else "")
    if kind == "exception":
        return "%s: %s" % (ev.get("type", ""), ev["detail"]) if ev.get("detail") else ev.get("type", "")
    if kind == "probe_refused":
        from . import probe
        return probe.refusal_text(ev)
    if kind == "lost":
        last = ev.get("last")
        return "the command stopped without saying it was done" + ((" (last: %s)" % describe(last)) if last else "")
    if kind == "died":
        return "the command died without saying it was done"
    if kind == "cannot_follow":
        return "cannot follow: %s" % ev.get("detail", "")
    if kind == "no_answer":
        return "the board reader ended without an answer"
    return kind or "failed"


def watch(root, selector=None, as_json: bool = False, out=None) -> int:
    """Follow one command of the project (by pid or label), or every live one, printing a line per event until they end.
    Exit 0 when what was followed is done, 1 for an error, 2 for one that died (its last state is printed from its
    progress file) or when the named command is not there."""
    out = out or sys.stdout
    directory = sockets_dir(root)
    live, dead = scan(directory)

    def chosen(e) -> bool:
        return selector is None or str(e.get("pid")) == str(selector) or (e.get("label") and e.get("label") == selector)

    live, dead = [e for e in live if chosen(e)], [e for e in dead if chosen(e)]
    lock = threading.Lock()
    codes = []

    def emit(e, ev) -> None:
        with lock:
            if as_json:
                print(json.dumps(ev, default=str), file=out, flush=True)
            elif describe(ev):
                print("%s%s" % (("[%s] " % e.get("pid")) if selector is None else "", describe(ev)), file=out, flush=True)

    def follow_one(e) -> None:
        code = 2
        try:
            for ev in follow(e):
                emit(e, ev)
                if ev.get("ev") == "done":
                    code = 0
                elif ev.get("ev") == "error":
                    code = 1
        except OSError as err:
            emit(e, {"ev": "error", "kind": "cannot_follow", "detail": str(err)})
        if code == 2:
            ended = last_state(e["progress"]) if e.get("progress") else []
            emit(e, {"ev": "error", "kind": "lost", **({"last": ended[-1]} if ended else {})})
        codes.append(code)

    if not live and selector is not None and dead:
        e = dead[0]
        events = last_state(e["progress"]) if e.get("progress") else []
        for ev in events:
            emit(e, ev)
        final = next((x for x in reversed(events) if x.get("ev") in ("done", "error")), None)
        clean(e)
        if final is None:
            emit(e, {"ev": "error", "kind": "died"})
            return 2
        return 0 if final["ev"] == "done" else 1
    if not live:
        print("no command is running in %s" % root if selector is None else "no command %r in %s" % (selector, root), file=out, flush=True)
        return 0 if selector is None else 2
    threads = [threading.Thread(target=follow_one, args=(e,), daemon=True) for e in live]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return max(codes) if codes else 0
