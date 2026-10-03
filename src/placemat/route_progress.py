"""A route's progress, on placemat's side: the events the hooked router writes (kicad/route_events.py), tailed while the router runs and sent
on the command's own socket, and kept as the route's record.

The router's process appends one JSON line per event to `events-<stage>.jsonl` in the route's work folder (stage: `pairs`, `islands`,
`main`). `RouteEvents` reads that file while the stage runs and sends each event with the channel's sender (`Beacon.send`, which never blocks
the route), and after the stage hands back its events in laid order. A stage taken from an earlier route is read from the file it left. At the
end `write_record` puts every stage's events, with the board it routed, in `route_record.json`: what the studio replays a finished route
from. Nothing here parses the router's printed output."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

STAGES = ("pairs", "islands", "main")
RECORD = "route_record.json"
BOARD = "route_board.json"
SUMMARY = "route_summary.json"
POLL_S = 0.05


def events_path(work, stage: str) -> Path:
    return Path(work) / ("events-%s.jsonl" % stage)


def enabled() -> bool:
    return os.environ.get("PLACEMAT_ROUTE_EVENTS") != "off"


def read_events(path) -> list:
    """The events in an events file, in the order written; a line that is not one (a write cut short) is skipped."""
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("ev"):
                    out.append(ev)
    except OSError:
        pass
    return out


def _renamed(ev: dict, names: dict) -> dict:
    """The event with the router's net names turned back to the board's (the pair router routes under aliases)."""
    if not names or "net" not in ev:
        return ev
    n = ev["net"]
    return dict(ev, net=[names.get(x, x) for x in n] if isinstance(n, list) else names.get(n, n))


class _Tail(threading.Thread):
    """Reads an events file as it grows and hands each new event on; `stop` reads what is left and ends."""

    def __init__(self, path: Path, give):
        super().__init__(daemon=True, name="placemat-route-tail")
        self.path, self.give, self.events = Path(path), give, []
        self._stop_event = threading.Event()
        self._pos = 0
        self._partial = ""

    def _drain(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._pos)
                text = f.read()
                self._pos = f.tell()
        except OSError:
            return
        if not text:
            return
        text = self._partial + text
        *lines, self._partial = text.split("\n")
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("ev"):
                self.events.append(ev)
                self.give(ev)

    def run(self) -> None:
        while not self._stop_event.wait(POLL_S):
            self._drain()
        self._drain()

    def stop(self) -> list:
        self._stop_event.set()
        self.join(timeout=5)
        return self.events


class RouteEvents:
    """The events of one route: per stage, tailed live (`begin`, `end`) or taken from an earlier route's file (`resumed`), each sent to
    `send` (None: not sent anywhere, still kept) and kept."""

    def __init__(self, work, send=None):
        self.work, self.send = Path(work).resolve(), send       # absolute: the router runs in its own folder
        self.stages: list = []                # [{"stage", "resumed", "seconds", "events"}] in order
        self.names: dict = {}                 # the pair router's aliases -> the board's names, for the pairs stage
        self._tail = None
        self._t0 = 0.0

    def _forward(self, stage: str):
        def give(ev):
            if stage == "pairs":
                ev = _renamed(ev, self.names)
            if self.send is not None:
                self.send(dict(ev, ev=ev["ev"] if ev["ev"].startswith("route_") else "route_" + ev["ev"], stage=stage))
        return give

    def path(self, stage: str) -> Path:
        return events_path(self.work, stage)

    def env(self, stage: str) -> dict:
        """What the router's process is given so its hooks write this stage's events."""
        return {"PLACEMAT_ROUTE_EVENTS": str(self.path(stage))} if enabled() else {}

    def begin(self, stage: str) -> None:
        self.path(stage).unlink(missing_ok=True)
        if self.send is not None:
            self.send({"ev": "route_stage", "stage": stage, "resumed": False})
        self._t0 = time.time()
        self._tail = _Tail(self.path(stage), self._forward(stage)) if enabled() else None
        if self._tail is not None:
            self._tail.start()

    def end(self, stage: str) -> list:
        events = self._tail.stop() if self._tail is not None else []
        self._tail = None
        if stage == "pairs":
            events = [_renamed(e, self.names) for e in events]
        self.stages.append({"stage": stage, "resumed": False, "seconds": round(time.time() - self._t0, 1), "events": events})
        return events

    def resumed(self, stage: str, seconds: float = 0.0) -> list:
        """A stage taken from the earlier route: its saved events are sent at once and kept."""
        events = [_renamed(e, self.names) for e in read_events(self.path(stage))] if stage == "pairs" else read_events(self.path(stage))
        if self.send is not None:
            self.send({"ev": "route_stage", "stage": stage, "resumed": True})
            give = self._forward(stage)
            for ev in events:
                give(ev)
        self.stages.append({"stage": stage, "resumed": True, "seconds": seconds, "events": events})
        return events


def write_record(work, board: dict, stages: list, report: dict) -> Path:
    """`route_record.json`: the board a route was made on, each stage's events in laid order and the report's result. Written whole."""
    path = Path(work) / RECORD
    doc = {"version": 1, "board": board, "stages": stages, "report": {k: report[k] for k in ("closure", "closure_clean", "open_before", "open_after", "open_nets", "shorted", "seconds", "quick", "resumed") if k in report}}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), default=str))
    os.replace(tmp, path)
    from .route_view import lay
    laid = lay([ev for st in stages for ev in st.get("events", ())])
    summary = {"nets": len(laid["order"]), "routed": sum(1 for n in laid["order"] if laid["result"][n] == "routed"),
               "failed": sum(1 for n in laid["order"] if laid["result"][n] != "routed"), "closure": doc["report"].get("closure_clean", doc["report"].get("closure")),
               "seconds": doc["report"].get("seconds"), "run": board.get("run", ""), "script": board.get("script", ""), "pcb": board.get("pcb", ""),
               "at": round(time.time(), 1)}
    (Path(work) / SUMMARY).write_text(json.dumps(summary, separators=(",", ":")))
    return path


def read_record(path) -> dict | None:
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("version") == 1 and "stages" in doc else None
