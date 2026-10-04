"""Progress events from inside the router's own process.

Run by the wrappers (`route_one_round.py`, `route_hooked.py`) under the router's interpreter before the router's entry script: it hooks the
router's own functions, from its own source, so a placemat that is watching can draw the copper net by net. Nothing in the router's checkout
is modified and no printed router output is read.

What is hooked (each checked first; if any anchor is missing nothing is patched, the router runs as it would have, and the reason is written
as a `route_off` event, a record (`reason`, below), and on stderr in words):

- `pcb_modification.add_route_to_pcb_data` and `remove_route_from_pcb_data`, the router's copper choke points: a net's copper committed (or
  restored after a rip) and ripped: events `commit` and `rip` with the segments and vias;
- `single_ended_routing.route_net_with_obstacles`, `route_multipoint_main` and `route_oracle_links`, one net's search: `net_begin`, `net_end`
  (found a route or not; the outermost call only);
- `single_ended_loop.route_single_ended_nets`, the loop over the nets: `queue` (the nets, in the order the loop was given) and `queue_end`;
- for the pair router only (`pairs=True`, the entry script `route_diff.py`): `diff_pair_loop.route_diff_pairs`, the loop over the pairs, gives
  `queue` (the pair names) and `queue_end`, and its per-pair step `get_diff_pair_terminals`, called once as each pair is taken up, gives
  `net_begin` for that pair and, when the next pair or the end of the loop comes, `net_end` with `ok` read from `state.routed_net_ids` (the
  pair's nets were routed coupled). A pair is one net of the events, named by the pair router's own pair name.

Each event is one JSON line written to the pipe whose write end is the file descriptor named by $PLACEMAT_ROUTE_EVENTS_FD (nothing happens
when it is unset, or when $PLACEMAT_ROUTE_EVENTS is "off"). A writer thread with a bounded queue does the writing: the router never waits on
the reader, an event that does not fit the queue is dropped and counted (the writer says so with a `dropped` event, `n` events lost, as soon as
it has room), and a pipe that closes ends the events silently. A failure in this module never
reaches the router: it stops writing events and says so once.

This file imports nothing of placemat's: it runs in the router's environment."""
from __future__ import annotations

import functools
import inspect
import json
import atexit
import os
import queue
import sys
import threading
import time

VERSION = 3                             # 2: `route_off` carries a `reason` record, not a sentence; 3: `dropped`, and the pair router's queue and nets
QUEUE_MAX = 20000                       # events waiting for the pipe; more are dropped, never waited for
FLUSH_S = 3.0                           # at exit: how long the writer may take to pass on what is queued
_state = {"fd": None, "q": None, "t0": time.monotonic(), "dead": False, "thread": None, "dropped": 0}


def _lost_line() -> str | None:
    """The `dropped` event for the events the queue turned away since the last one (None: none were)."""
    n, _state["dropped"] = _state["dropped"], 0
    if not n:
        return None
    return json.dumps({"ev": "dropped", "n": n, "t": round(time.monotonic() - _state["t0"], 3)}, separators=(",", ":")) + "\n"


def _writer() -> None:
    q, fd = _state["q"], _state["fd"]
    while True:
        line = q.get()
        try:
            for text in (_lost_line(), line):
                data = (text or "").encode("utf-8")
                while data:
                    data = data[os.write(fd, data):]
        except OSError:                                                # the reader has gone: no more events, silently
            _state["dead"] = True
            return
        if line is None:
            return


def _emit(event: dict) -> None:
    """Queue `event` for the pipe; a full queue drops it, a failure turns the events off for the rest of the run."""
    if _state["dead"] or _state["q"] is None:
        return
    try:
        event["t"] = round(time.monotonic() - _state["t0"], 3)
        _state["q"].put_nowait(json.dumps(event, separators=(",", ":"), default=str) + "\n")
    except queue.Full:
        _state["dropped"] += 1
    except Exception as e:                                             # progress is a courtesy: the route goes on without it
        _state["dead"] = True
        print("route progress stopped: %s: %s" % (type(e).__name__, e), file=sys.stderr)


def _flush() -> None:
    """At exit: let the writer pass on what is queued (the router may be about to exit with events still waiting)."""
    th = _state["thread"]
    if th is None or _state["dead"]:
        return
    try:
        _state["q"].put(None, timeout=FLUSH_S)
        th.join(FLUSH_S)
    except Exception:
        pass


def pipe_fd() -> int | None:
    """The events pipe's descriptor, from $PLACEMAT_ROUTE_EVENTS_FD (None: events are not asked for)."""
    if os.environ.get("PLACEMAT_ROUTE_EVENTS") == "off":
        return None
    try:
        return int(os.environ.get("PLACEMAT_ROUTE_EVENTS_FD", ""))
    except ValueError:
        return None


def _params(fn) -> list:
    try:
        return list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return []


def _missing(module, name: str, wanted: tuple):
    """Why `module.name` is not what the hooks read, as a reason record (`reason_text` says it), or None when it is."""
    fn = getattr(module, name, None)
    if not callable(fn):
        return {"code": "no_function", "module": module.__name__, "name": name}
    have = _params(fn)
    gone = [p for p in wanted if p not in have]
    return {"code": "no_parameter", "module": module.__name__, "name": name, "parameters": gone} if gone else None


def reason_text(reason: dict) -> str:
    """A `route_off` reason in words: {"code": "no_function" (module, name) | "no_parameter" (module, name, parameters) | "no_field"
    (class, fields) | "import_failed" (type, detail) | "pipe_closed" (detail)}."""
    code = reason.get("code")
    if code == "no_function":
        return "%s has no %s" % (reason["module"], reason["name"])
    if code == "no_parameter":
        return "%s.%s has no parameter %s" % (reason["module"], reason["name"], ", ".join(reason["parameters"]))
    if code == "no_field":
        return "kicad_parser.%s has no field %s" % (reason["class"], ", ".join(reason["fields"]))
    if code == "import_failed":
        return "the router's modules are not where the hooks expect them (%s: %s)" % (reason.get("type", ""), reason.get("detail", ""))
    if code == "pipe_closed":
        return "the events pipe is not open (%s)" % reason.get("detail", "")
    return str(code)


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


def install(fd: int | None = None, pairs: bool = False):
    """Hook the router for this process (`pairs`: it is the pair router, whose loop over the pairs is hooked too). Returns None when the hooks
    are in (or events are not asked for: no pipe), else the reason they are not, a record (`reason_text`)."""
    fd = pipe_fd() if fd is None else fd
    if fd is None:
        return None
    try:
        import importlib
        pm = importlib.import_module("pcb_modification")
        ser = importlib.import_module("single_ended_routing")
        loop = importlib.import_module("single_ended_loop")
        parser = importlib.import_module("kicad_parser")
        dpl = importlib.import_module("diff_pair_loop") if pairs else None
    except Exception as e:
        return {"code": "import_failed", "type": type(e).__name__, "detail": str(e)}
    why = (_missing(pm, "add_route_to_pcb_data", ("pcb_data", "result")) or _missing(pm, "remove_route_from_pcb_data", ("pcb_data", "result")) or
           _missing(ser, "route_net_with_obstacles", ("pcb_data", "net_id")) or _missing(ser, "route_multipoint_main", ("pcb_data", "net_id")) or
           _missing(ser, "route_oracle_links", ("pcb_data", "net_id")) or _missing(loop, "route_single_ended_nets", ("state", "single_ended_nets")))
    if not why and pairs:
        why = (_missing(dpl, "route_diff_pairs", ("state", "diff_pair_ids_to_route")) or
               _missing(dpl, "get_diff_pair_terminals", ("pcb_data", "p_net_id", "n_net_id")))
    if not why:
        for cls, fields in (("Segment", ("start_x", "start_y", "end_x", "end_y", "width", "layer", "net_id")), ("Via", ("x", "y", "size", "drill", "layers", "net_id"))):
            have = set(getattr(getattr(parser, cls, None), "__dataclass_fields__", {}) or ())
            gone = [f for f in fields if f not in have]
            if gone:
                why = {"code": "no_field", "class": cls, "fields": gone}
                break
    if why:
        return why
    try:
        os.fstat(fd)
    except OSError as e:
        return {"code": "pipe_closed", "detail": str(e)}
    _state.update(fd=fd, q=queue.Queue(QUEUE_MAX), dead=False, t0=time.monotonic())
    th = threading.Thread(target=_writer, daemon=True, name="placemat-route-events")
    th.start()
    _state["thread"] = th
    atexit.register(_flush)
    originals = {"add": pm.add_route_to_pcb_data, "remove": pm.remove_route_from_pcb_data,
                 "net": ser.route_net_with_obstacles, "multi": ser.route_multipoint_main, "oracle": ser.route_oracle_links,
                 "loop": loop.route_single_ended_nets}
    if pairs:
        originals.update(pairs=dpl.route_diff_pairs, terminals=dpl.get_diff_pair_terminals)
    depth = {"n": 0}
    pair = {"state": None, "names": {}, "open": None}      # the pair router's loop: its state, pair name by net id, the pair taken up now

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
            outer = depth["n"] == 0 and pair["open"] is None
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

    def close_pair(ok: bool | None = None) -> None:
        """The pair taken up ends: `ok` (None: read from the loop's state) is whether its nets are among the ones routed."""
        taken, pair["open"] = pair["open"], None
        if taken is None:
            return
        name, p_id, n_id = taken
        try:
            if ok is None:
                routed = pair["state"].routed_net_ids
                ok = p_id in routed and n_id in routed
            _emit({"ev": "net_end", "net": name, "ok": bool(ok)})
        except Exception:
            pass

    def get_diff_pair_terminals(pcb_data, p_net_id, n_net_id, *a, **k):
        """Called once as the loop takes a pair up (and again, inside the multipoint router, for the same pair: that one is not a new pair)."""
        try:
            if pair["state"] is not None and not (pair["open"] and pair["open"][1:] == (p_net_id, n_net_id)):
                close_pair()
                name = pair["names"].get(p_net_id)
                if name is not None:
                    pair["open"] = (name, p_net_id, n_net_id)
                    _emit({"ev": "net_begin", "net": name})
        except Exception:
            pass
        return originals["terminals"](pcb_data, p_net_id, n_net_id, *a, **k)

    def route_diff_pairs(state, diff_pair_ids_to_route, *a, **k):
        try:
            for name, p in diff_pair_ids_to_route:
                pair["names"][p.p_net_id] = pair["names"][p.n_net_id] = str(name)
            _emit({"ev": "queue", "nets": [str(name) for name, _ in diff_pair_ids_to_route]})
        except Exception:
            pass
        outer, pair["state"] = pair["state"], state
        try:
            out = originals["pairs"](state, diff_pair_ids_to_route, *a, **k)
        finally:
            close_pair()
            pair["state"] = outer
        try:
            _emit({"ev": "queue_end", "routed": out[0], "failed": out[1]})
        except Exception:
            pass
        return out

    patched = {"add": add_route_to_pcb_data, "remove": remove_route_from_pcb_data, "net": attempt(originals["net"]), "multi": attempt(originals["multi"]),
               "oracle": attempt(originals["oracle"]), "loop": route_single_ended_nets}
    where = {"add": "add_route_to_pcb_data", "remove": "remove_route_from_pcb_data", "net": "route_net_with_obstacles",
             "multi": "route_multipoint_main", "oracle": "route_oracle_links", "loop": "route_single_ended_nets"}
    pm.add_route_to_pcb_data, pm.remove_route_from_pcb_data = patched["add"], patched["remove"]
    ser.route_net_with_obstacles, ser.route_multipoint_main, ser.route_oracle_links = patched["net"], patched["multi"], patched["oracle"]
    loop.route_single_ended_nets = patched["loop"]
    if pairs:
        patched.update(pairs=route_diff_pairs, terminals=get_diff_pair_terminals)
        where.update(pairs="route_diff_pairs", terminals="get_diff_pair_terminals")
        dpl.route_diff_pairs, dpl.get_diff_pair_terminals = patched["pairs"], patched["terminals"]
    for module in list(sys.modules.values()):                              # a module that bound the originals before this ran
        for key, name in where.items():
            try:
                if getattr(module, name, None) is originals[key]:
                    setattr(module, name, patched[key])
            except Exception:
                continue
    return None


def report_off(reason: dict, fd: int | None = None) -> None:
    """Say why the route has no progress: one `route_off` event (`reason`, a record) on the pipe and one line on stderr."""
    fd = pipe_fd() if fd is None else fd
    print("route progress is off for this route: %s" % reason_text(reason), file=sys.stderr)
    if fd is not None:
        try:
            os.write(fd, (json.dumps({"ev": "route_off", "reason": reason, "t": 0.0}) + "\n").encode("utf-8"))
        except OSError:
            pass
