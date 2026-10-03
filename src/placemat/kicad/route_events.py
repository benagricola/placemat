"""Progress events from inside the router's own process.

Run by the wrappers (`route_one_round.py`, `route_hooked.py`) under the router's interpreter before the router's entry script: it hooks the
router's own functions, from its own source, so a placemat that is watching can draw the copper net by net. Nothing in the router's checkout
is modified and no printed router output is read.

What is hooked (each checked first; if any anchor is missing nothing is patched, the router runs as it would have, and the reason is written
as a `route_off` event and on stderr):

- `pcb_modification.add_route_to_pcb_data` and `remove_route_from_pcb_data`, the router's copper choke points: a net's copper committed (or
  restored after a rip) and ripped: events `commit` and `rip` with the segments and vias;
- `single_ended_routing.route_net_with_obstacles`, `route_multipoint_main` and `route_oracle_links`, one net's search: `net_begin`, `net_end`
  (found a route or not; the outermost call only);
- `single_ended_loop.route_single_ended_nets`, the loop over the nets: `queue` (the nets, in the order the loop was given) and `queue_end`.

Each event is one JSON line appended to the file named by $PLACEMAT_ROUTE_EVENTS (nothing happens when it is unset or "off") and flushed; the
router never waits on anyone. A failure in this module never reaches the router: it stops writing events and says so once.

This file imports nothing of placemat's: it runs in the router's environment."""
from __future__ import annotations

import functools
import inspect
import json
import os
import sys
import threading
import time

VERSION = 1
_state = {"out": None, "lock": threading.Lock(), "t0": time.monotonic(), "dead": False}


def _emit(event: dict) -> None:
    """Append `event` to the events file, flushed; any failure turns the events off for the rest of the run."""
    if _state["dead"] or _state["out"] is None:
        return
    try:
        event["t"] = round(time.monotonic() - _state["t0"], 3)
        line = json.dumps(event, separators=(",", ":"), default=str) + "\n"
        with _state["lock"]:
            _state["out"].write(line)
            _state["out"].flush()
    except Exception as e:                                             # progress is a courtesy: the route goes on without it
        _state["dead"] = True
        print("route progress stopped: %s: %s" % (type(e).__name__, e), file=sys.stderr)


def _params(fn) -> list:
    try:
        return list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return []


def _missing(module, name: str, wanted: tuple) -> str:
    """Why `module.name` is not what the hooks read (empty when it is)."""
    fn = getattr(module, name, None)
    if not callable(fn):
        return "%s has no %s" % (module.__name__, name)
    have = _params(fn)
    gone = [p for p in wanted if p not in have]
    return ("%s.%s has no parameter %s" % (module.__name__, name, ", ".join(gone))) if gone else ""


def _net_name(pcb_data, net_id) -> str:
    try:
        return str(pcb_data.nets[net_id].name)
    except Exception:
        return str(net_id)


def _r(v) -> float:
    return round(float(v), 3)


def _copper(pcb_data, result) -> tuple:
    """(net_id, segments, vias) of a result as the events carry them: [x1, y1, x2, y2, layer, width] and [x, y, size, drill, layers]."""
    segs = [[_r(s.start_x), _r(s.start_y), _r(s.end_x), _r(s.end_y), s.layer, _r(s.width)] for s in (result.get("new_segments") or ())]
    vias = [[_r(v.x), _r(v.y), _r(v.size), _r(v.drill), list(v.layers)] for v in (result.get("new_vias") or ())]
    ids = {s.net_id for s in (result.get("new_segments") or ())} | {v.net_id for v in (result.get("new_vias") or ())}
    return (sorted(ids)[0] if len(ids) == 1 else None), segs, vias, sorted(ids)


def install(out_path: str | None = None) -> str:
    """Hook the router for this process. Returns "" when the hooks are in (or events are not asked for: no path), else why they are not."""
    path = out_path or os.environ.get("PLACEMAT_ROUTE_EVENTS", "")
    if not path or path == "off":
        return ""
    try:
        import importlib
        pm = importlib.import_module("pcb_modification")
        ser = importlib.import_module("single_ended_routing")
        loop = importlib.import_module("single_ended_loop")
        parser = importlib.import_module("kicad_parser")
    except Exception as e:
        return "the router's modules are not where the hooks expect them (%s: %s)" % (type(e).__name__, e)
    why = (_missing(pm, "add_route_to_pcb_data", ("pcb_data", "result")) or _missing(pm, "remove_route_from_pcb_data", ("pcb_data", "result")) or
           _missing(ser, "route_net_with_obstacles", ("pcb_data", "net_id")) or _missing(ser, "route_multipoint_main", ("pcb_data", "net_id")) or
           _missing(ser, "route_oracle_links", ("pcb_data", "net_id")) or _missing(loop, "route_single_ended_nets", ("state", "single_ended_nets")))
    if not why:
        for cls, fields in (("Segment", ("start_x", "start_y", "end_x", "end_y", "width", "layer", "net_id")), ("Via", ("x", "y", "size", "drill", "layers", "net_id"))):
            have = set(getattr(getattr(parser, cls, None), "__dataclass_fields__", {}) or ())
            gone = [f for f in fields if f not in have]
            if gone:
                why = "kicad_parser.%s has no field %s" % (cls, ", ".join(gone))
                break
    if why:
        return why
    try:
        _state["out"] = open(path, "a", encoding="utf-8")
    except OSError as e:
        return "the events file cannot be written (%s)" % e
    _state["t0"] = time.monotonic()
    originals = {"add": pm.add_route_to_pcb_data, "remove": pm.remove_route_from_pcb_data,
                 "net": ser.route_net_with_obstacles, "multi": ser.route_multipoint_main, "oracle": ser.route_oracle_links,
                 "loop": loop.route_single_ended_nets}
    depth = {"n": 0}

    @functools.wraps(originals["add"])
    def add_route_to_pcb_data(pcb_data, result, *a, **k):
        out = originals["add"](pcb_data, result, *a, **k)
        try:
            how = k.get("trace_event") or (a[1] if len(a) > 1 else "route")
            net, segs, vias, ids = _copper(pcb_data, result)
            if segs or vias:
                _emit({"ev": "commit", "net": _net_name(pcb_data, net) if net is not None else [_net_name(pcb_data, i) for i in ids],
                       "how": how, "seg": segs, "via": vias})
        except Exception as e:
            _state["dead"] = True
            print("route progress stopped: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return out

    @functools.wraps(originals["remove"])
    def remove_route_from_pcb_data(pcb_data, result, *a, **k):
        try:                                                               # before it goes: the call may empty the result
            net, segs, vias, ids = _copper(pcb_data, result)
        except Exception:
            net, segs, vias, ids = None, [], [], []
        out = originals["remove"](pcb_data, result, *a, **k)
        if segs or vias:
            _emit({"ev": "rip", "net": _net_name(pcb_data, net) if net is not None else [_net_name(pcb_data, i) for i in ids], "seg": segs, "via": vias})
        return out

    def attempt(original):
        """One net's search (a two-pad net, a multipoint net, an oracle link set): begin and end, the outermost call only."""
        @functools.wraps(original)
        def route_attempt(pcb_data, net_id, *a, **k):
            outer = depth["n"] == 0
            depth["n"] += 1
            if outer:
                _emit({"ev": "net_begin", "net": _net_name(pcb_data, net_id)})
            try:
                result = original(pcb_data, net_id, *a, **k)
            finally:
                depth["n"] -= 1
            if outer:
                try:
                    _emit({"ev": "net_end", "net": _net_name(pcb_data, net_id), "ok": bool(result) and bool(result.get("new_segments") or result.get("new_vias"))})
                except Exception:
                    pass
            return result
        return route_attempt

    @functools.wraps(originals["loop"])
    def route_single_ended_nets(state, single_ended_nets, *a, **k):
        try:
            _emit({"ev": "queue", "nets": [str(n[0]) for n in single_ended_nets]})
        except Exception:
            pass
        out = originals["loop"](state, single_ended_nets, *a, **k)
        try:
            _emit({"ev": "queue_end", "routed": out[0], "failed": out[1]})
        except Exception:
            pass
        return out

    patched = {"add": add_route_to_pcb_data, "remove": remove_route_from_pcb_data, "net": attempt(originals["net"]), "multi": attempt(originals["multi"]),
               "oracle": attempt(originals["oracle"]), "loop": route_single_ended_nets}
    pm.add_route_to_pcb_data, pm.remove_route_from_pcb_data = patched["add"], patched["remove"]
    ser.route_net_with_obstacles, ser.route_multipoint_main, ser.route_oracle_links = patched["net"], patched["multi"], patched["oracle"]
    loop.route_single_ended_nets = patched["loop"]
    for module in list(sys.modules.values()):                              # a module that bound the originals before this ran
        for key, name in (("add", "add_route_to_pcb_data"), ("remove", "remove_route_from_pcb_data"), ("net", "route_net_with_obstacles"),
                          ("multi", "route_multipoint_main"), ("oracle", "route_oracle_links"), ("loop", "route_single_ended_nets")):
            try:
                if getattr(module, name, None) is originals[key]:
                    setattr(module, name, patched[key])
            except Exception:
                continue
    return ""


def report_off(why: str, out_path: str | None = None) -> None:
    """Say why the route has no progress: one `route_off` event in the events file and one line on stderr."""
    path = out_path or os.environ.get("PLACEMAT_ROUTE_EVENTS", "")
    print("route progress is off for this route: %s" % why, file=sys.stderr)
    if path and path != "off":
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ev": "route_off", "why": why, "t": 0.0}) + "\n")
        except OSError:
            pass
