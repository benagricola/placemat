"""A route's progress, on placemat's side: the events the hooked router sends (kicad/route_events.py) over a pipe while it runs, forwarded on the
command's own socket, and kept as the route's record.

For each stage (`pairs`, `islands`, `main`) `RouteEvents` opens a pipe and gives its write end to the router's process (the descriptor's number in
$PLACEMAT_ROUTE_EVENTS_FD); a thread reads newline-delimited JSON from the read end, sends each event with the channel's sender (`Beacon.send`,
which never blocks the route) and keeps it. The record, `route_record.json`, is the only file: it holds every stage's events in laid order with
the board it routed, is written when each stage ends and again at the end of the route, and is what the studio replays a finished route from. A
stage taken from an earlier route takes its events from that route's record. A record says whether it is whole: `complete` is true only for the
one written when the route finished, and each stage says whether it ran to its end (`complete`) and how many of its events were lost (`dropped`:
the router's queue was full, or a line could not be read). Nothing here parses the router's printed output."""
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
_active: tuple = ()                       # the write end a router launched now is given (route.py passes it as pass_fds)


def pass_fds() -> tuple:
    return _active


def enabled() -> bool:
    return os.environ.get("PLACEMAT_ROUTE_EVENTS") != "off"


def _renamed(ev: dict, names: dict) -> dict:
    """The event with the router's net names turned back to the board's (the pair router routes under aliases)."""
    if not names:
        return ev
    if "nets" in ev:
        ev = dict(ev, nets=[names.get(x, x) for x in ev["nets"]])
    if "net" not in ev:
        return ev
    n = ev["net"]
    return dict(ev, net=[names.get(x, x) for x in n] if isinstance(n, list) else names.get(n, n))


class _Reader(threading.Thread):
    """Reads an events pipe to its end and hands each event on; `finish` waits for the end (every holder of the write end has closed it)."""

    def __init__(self, fd: int, give):
        super().__init__(daemon=True, name="placemat-route-events")
        self.fd, self.give, self.events = fd, give, []
        self.unreadable = 0                   # lines that were not an event (a write cut short by the router's end)

    def _line(self, raw: bytes) -> None:
        try:
            ev = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            self.unreadable += 1
            return
        if isinstance(ev, dict) and ev.get("ev"):
            self.events.append(ev)
            self.give(ev)

    def run(self) -> None:
        rest = b""
        try:
            while True:
                chunk = os.read(self.fd, 65536)
                if not chunk:
                    break
                *lines, rest = (rest + chunk).split(b"\n")
                for line in lines:
                    self._line(line)
        except OSError:
            pass
        if rest.strip():
            self._line(rest)

    def finish(self) -> list:
        self.join(timeout=10)
        try:
            os.close(self.fd)
        except OSError:
            pass
        return self.events


class RouteEvents:
    """The events of one route: per stage, read live from the router's pipe (`begin`, `end`) or taken from an earlier route's record
    (`resumed`), each sent to `send` (None: not sent anywhere, still kept) and kept in `stages`."""

    def __init__(self, work, send=None, info=None):
        self.work, self.send, self.info = Path(work).resolve(), send, info or {}       # absolute: the router runs in its own folder
        self.stages: list = []                # [{"stage", "resumed", "seconds", "events"}] in order
        self.names: dict = {}                 # the pair router's aliases -> the board's names, for the pairs stage
        prior = read_record(self.work / RECORD)
        self._prior_stage = {st["stage"]: st for st in (prior or {}).get("stages", ())}
        self._prior = {k: st.get("events", []) for k, st in self._prior_stage.items()}      # what a resumed stage had made
        self._reader = None
        self._w = None
        self._t0 = 0.0

    def _forward(self, stage: str):
        def give(ev):
            if stage == "pairs":
                ev = _renamed(ev, self.names)
            if self.send is not None:
                self.send(dict(ev, ev=ev["ev"] if ev["ev"].startswith("route_") else "route_" + ev["ev"], stage=stage))
        return give

    def env(self, stage: str) -> dict:
        """What the router's process is given so its hooks write to this stage's pipe."""
        return {"PLACEMAT_ROUTE_EVENTS_FD": str(self._w)} if self._w is not None else {}

    def begin(self, stage: str, nets: int | None = None) -> None:
        """A stage starts. `nets`: how many nets it will take up when that is known before the router says (a stage that launches the router
        once a net, as the islands do): the stage's count of nets is then this, not what each launch's queue adds up to."""
        global _active
        if self.send is not None:
            self.send(dict({"ev": "route_stage", "stage": stage, "resumed": False}, **({"nets": nets} if nets is not None else {})))
        self._t0 = time.time()
        if enabled():
            r, self._w = os.pipe()
            _active = (self._w,)
            self._reader = _Reader(r, self._forward(stage))
            self._reader.start()

    def end(self, stage: str, complete: bool = True) -> list:
        """A stage ends. `complete`: it ran to its end (False: the router failed or the route was stopped part-way, and the events are what
        came before)."""
        global _active
        events, unreadable = [], 0
        if self._reader is not None:
            _active = ()
            try:
                os.close(self._w)                  # the router's copies went with its processes: the reader reaches the end
            except OSError:
                pass
            self._w = None
            events = self._reader.finish()
            unreadable, self._reader = self._reader.unreadable, None
        if stage == "pairs":
            events = [_renamed(e, self.names) for e in events]
        lost = unreadable + sum(int(e.get("n") or 0) for e in events if e.get("ev") == "dropped")
        self.stages.append({"stage": stage, "resumed": False, "complete": complete, "dropped": lost, "seconds": round(time.time() - self._t0, 1), "events": events})
        self.save()
        return events

    def resumed(self, stage: str, seconds: float = 0.0) -> list:
        """A stage taken from the earlier route: its events from that route's record are sent at once and kept."""
        events = list(self._prior.get(stage, ()))
        if self.send is not None:
            self.send({"ev": "route_stage", "stage": stage, "resumed": True})
            give = self._forward(stage)
            for ev in events:
                give(ev)
        prior = self._prior_stage.get(stage, {})
        self.stages.append({"stage": stage, "resumed": True, "complete": prior.get("complete", True), "dropped": prior.get("dropped", 0), "seconds": seconds, "events": events})
        self.save()
        return events

    def save(self, report: dict | None = None, complete: bool = False) -> None:
        """The record as it stands (a stage ended): a route that is stopped leaves what it made, for a rerun to resume from. `complete`: the
        route finished (`write_record`)."""
        if enabled() and self.info:
            try:
                write_record(self.work, self.info, self.stages, report or {}, complete)
            except OSError:
                pass


def write_record(work, board: dict, stages: list, report: dict, complete: bool = False) -> Path:
    """`route_record.json`: the board a route was made on, each stage's events in laid order and the report's result. Written whole. `complete`:
    the route ran to its end; a record written when a stage ends, for a route that may be stopped, is not."""
    path = Path(work) / RECORD
    doc = {"version": 1, "complete": bool(complete), "board": board, "stages": stages, "report": {k: report[k] for k in ("closure", "closure_clean", "open_before", "open_after", "open_nets", "shorted", "seconds", "quick", "resumed", "widths") if k in report}}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), default=str))
    os.replace(tmp, path)
    from .route_view import lay
    laid = lay([ev for st in stages for ev in st.get("events", ())])
    lost = sum(int(st.get("dropped") or 0) for st in stages)
    summary = {"complete": bool(complete), "dropped": lost, "nets": len(laid["order"]), "routed": sum(1 for n in laid["order"] if laid["result"][n] == "routed"),
               "failed": sum(1 for n in laid["order"] if laid["result"][n] in ("no route found", "ripped")), "closure": doc["report"].get("closure_clean", doc["report"].get("closure")),
               "seconds": doc["report"].get("seconds"), "run": board.get("run", ""), "script": board.get("script", ""), "pcb": board.get("pcb", ""),
               "under_width": doc["report"].get("widths", []), "at": round(time.time(), 1)}
    (Path(work) / SUMMARY).write_text(json.dumps(summary, separators=(",", ":")))
    return path


def read_record(path) -> dict | None:
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("version") == 1 and "stages" in doc else None
