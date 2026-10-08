"""One routing phase's router calls, in order, each on the board the one before it left with its copper locked, and the
phase's own judgement: each of its obligations (the pad pairs it is asked to join, fixed from the input board before
any phase runs) judged on a DRC of the board after the phase. The calls are planned here from a Selection
(kicad/phase_select.py); a phase holding nets of several clearances routes one call per clearance, widest first,
because KRT spaces a whole call at the largest clearance among its nets (py_router/routing_config.py:485-509,
set_net_clearances)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import shutil
import subprocess
import time

from .. import route_progress
from .drc import run_drc
from .route import (RouteRefused, RouterFailed, _copy_project, clearance_groups, fill_zones,
                    group_clearance, lock_copper, main_pass_nets, remove_guards, route_pairs, route_pour_net,
                    router_command)


@dataclass(frozen=True)
class Call:
    kind: str                       # "pairs" | "pour" | "bus" | "nets" | "tasks" | "rest"
    nets: tuple = ()                # the nets it routes; for "rest" the ones it may route
    excluded: tuple = ()            # for "rest": the nets its `*` leaves out
    tasks: tuple = ()               # Task: a "tasks" call's pad pairs; a "pour" call's tasks on its net
    width: float | None = None
    clearance: float | None = None


def write_connections(tasks, path, layers) -> Path:
    """The --connections file of one call (KRT docs/connections.md). Each task names a width on every layer the call
    routes and no other, as KRT requires (`layer_width_missing`, `layer_not_routed`); a task that does not is
    placemat's own mistake and raises ValueError(code, task.record()) before anything is written."""
    for t in tasks:
        named = {layer for layer, _ in t.widths}
        if named != set(layers):
            raise ValueError("layer_width_missing" if set(layers) - named else "layer_not_routed", t.record())
    path = Path(path)
    path.write_text(json.dumps([{"net": t.net, "from": {"ref": t.start[0], "pad": t.start[1]},
                                 "to": {"ref": t.end[0], "pad": t.end[1]}, "widths": dict(t.widths)} for t in tasks],
                               indent=1) + "\n")
    return path


def refused_records(records) -> list:
    """The tasks the router refused, each {net, from, to, reason}. placemat selected every task from the board, so a
    refusal means the two disagree about the board; Task 13 stops the route naming them."""
    return [{"net": r["net"], "from": r["from"], "to": r["to"], "reason": r.get("reason")}
            for r in records if r.get("status") == "refused"]


def plan_calls(sel, clearance_map: dict, base: float, excluded: set) -> list:
    """The router calls of one Selection, in order: the pairs; each pour net alone (sorted), its pour handed to the
    router as a zone (D15); each bus; the pad-pair tasks grouped by (clearance, widths), widest clearance first, then
    widest width first (D5); whole nets per clearance group widest first, then the Default-clearance rest - for a
    rest selection one `*` call leaving out `excluded` and the nets routed by name.

    A task set's pour nets (Selection.pour_nets) route in their pour call, not a task call (ruling S5): the call
    carries that net's tasks, and, when the phase sets no numeric width, the widest width any of them asks; each
    task is still judged on its own path (Task 15)."""
    calls = []
    if sel.pairs:
        calls.append(Call("pairs", tuple(n for pair in sel.pairs for n in pair)))
    pours = set(sel.pour_nets)
    for n in sorted(pours):
        own = tuple(t for t in sel.tasks if t.net == n)
        width = sel.width
        if width is None and own:
            width = max(w for t in own for _, w in t.widths)
        calls.append(Call("pour", (n,), tasks=own, width=width))
    bus_nets = {n for b in sel.buses for n in b}
    for bus in sel.buses:
        own = tuple(t for t in sel.tasks if t.net in bus and t.net not in pours)
        if own:
            calls.append(Call("bus_tasks", tuple(n for n in bus if n not in pours), tasks=own))
        elif not sel.tasks:
            calls.append(Call("bus", tuple(bus), width=sel.width))
    tasks = [t for t in sel.tasks if t.net not in pours and t.net not in bus_nets]
    if tasks:
        def clr(t):                                 # the same groups as whole nets' (clearance_groups)
            c = group_clearance(clearance_map, t.net, base)
            return base if c is None else c
        # the widths tuple last breaks ties between groups of the same widest width, so the order is the same every run
        keys = sorted({(clr(t), t.widths) for t in tasks}, key=lambda k: (-k[0], -max(w for _, w in k[1]), k[1]))
        calls += [Call("tasks", tasks=tuple(t for t in tasks if (clr(t), t.widths) == k), clearance=k[0]) for k in keys]
    if sel.nets:
        groups = clearance_groups(clearance_map, base, sel.nets)
        wide = {n for _, ns in groups for n in ns}
        calls += [Call("nets", tuple(ns), width=sel.width, clearance=c) for c, ns in groups]
        rest = tuple(n for n in sel.nets if n not in wide)
        if sel.rest:
            calls.append(Call("rest", rest, excluded=tuple(sorted(set(excluded) | wide)), width=sel.width,
                              clearance=base))
        elif rest:
            calls.append(Call("nets", rest, width=sel.width, clearance=base))
    return calls


@dataclass
class PhaseContext:
    """What every phase of one route shares: the router and how it is run, the board as read, the clearance map, and
    what the route leaves out (`excluded`) or serves by a pour (`pour_nets`)."""
    rpy: Path
    script: str
    router_dir: str
    work: Path
    layers: list
    iterations: int | None
    probe: int | None
    quick: bool
    timeout: int
    env: dict
    cfg: object
    geometry: object
    clearance_map: dict
    base_clearance: float
    clearances_file: Path | None
    excluded: set
    pour_nets: set
    events: object
    class_clearances: dict = field(default_factory=dict)
    stated_clearances: dict = field(default_factory=dict)
    execution: object = None


@dataclass
class PhaseOutcome:
    board: Path                                         # the board the phase left, its copper locked
    record: dict                                        # phase_record
    open_nets: dict                                     # {net: open items} on that board, from the phase's DRC
    summaries: list = field(default_factory=list)       # (phase name, call index, summary path)
    calls: list = field(default_factory=list)           # (Call, board in, board out) (ruling S1, Task 15)
    routed: dict = field(default_factory=dict)          # Routed.record(): what the calls left, kept before judging


@dataclass
class Routed:
    """What a phase's router calls left, before its judgement: kept in the route's state as soon as the calls end, so a
    failure judging it (its DRC) costs only the judgement on a rerun."""
    board: Path
    seconds: float
    ncalls: int
    pairs: dict | None = None
    connections: list = field(default_factory=list)
    bus_groups: list = field(default_factory=list)
    summaries: list = field(default_factory=list)       # (phase name, call index, summary path as str)

    widths: list = field(default_factory=list)

    def record(self) -> dict:
        return {"widths": list(self.widths), "board": Path(self.board).name, "seconds": round(self.seconds, 1), "ncalls": self.ncalls,
                "pairs": self.pairs, "connections": list(self.connections), "bus_groups": list(self.bus_groups),
                "summaries": [list(s) for s in self.summaries]}

    @staticmethod
    def of(doc: dict, work) -> "Routed":
        return Routed(Path(work) / doc["board"], doc["seconds"], doc["ncalls"], doc.get("pairs"),
                      list(doc.get("connections") or ()), list(doc.get("bus_groups") or ()),
                      [tuple(s) for s in doc.get("summaries") or ()], list(doc.get("widths") or ()))


def _run(cmd, log: Path, ctx) -> int:
    with open(log, "w") as f:
        f.write("$ %s\n\n" % " ".join(str(c) for c in cmd))
        f.flush()
        env = dict(ctx.env)
        deadline = time.time() + ctx.timeout
        if "KRT_ROUTE_DEADLINE_UTC" in env:
            import math
            try:
                earlier = float(env["KRT_ROUTE_DEADLINE_UTC"])
                if not math.isfinite(earlier):
                    raise ValueError
            except (TypeError, ValueError):
                raise RouterFailed("invalid router deadline", None, log, "", code="invalid_deadline",
                                   facts={"variable": "KRT_ROUTE_DEADLINE_UTC"}) from None
            deadline = min(deadline, earlier)
        env["KRT_ROUTE_DEADLINE_UTC"] = str(deadline)
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(ctx.router_dir), env=env,
                              timeout=ctx.timeout, pass_fds=route_progress.pass_fds()).returncode


def _failed(rc, log, what):
    tail = "\n".join(Path(log).read_text(errors="replace").splitlines()[-8:])
    raise RouterFailed("the router exited %s routing %s" % (rc, what), rc, log, tail)


def joined_pairs(pcb_path, pairs) -> list:
    """Whether each pair's two ends are joined on the board, by KiCad's own connectivity (BuildConnectivity, the same
    test route_cleanup.pad_groups makes): an end is every pad of that footprint with that number."""
    from .quiet import import_pcbnew, quiet_stderr
    from .write import load_board
    import_pcbnew()
    if not pairs:
        return []
    with quiet_stderr():
        board = load_board(str(pcb_path))
    board.BuildConnectivity()
    cn = board.GetConnectivity()
    pads = {}
    for p in board.GetPads():
        pads.setdefault((p.GetParentFootprint().GetReference(), p.GetNumber()), []).append(p)
    out = []
    for a, b in pairs:
        ends_b = {p.m_Uuid.AsString() for p in pads.get(tuple(b), ())}
        joined = False
        for pa in pads.get(tuple(a), ()):
            if pa.m_Uuid.AsString() in ends_b:
                joined = True
                break
            reach = {i.m_Uuid.AsString() for i in cn.GetConnectedItems(pa) if i.GetClass() == "PAD"}
            if reach & ends_b:
                joined = True
                break
        out.append(joined)
    return out


def joined_ends(pcb_path, tasks) -> list:
    """joined_pairs for phase_select.Task records."""
    return joined_pairs(pcb_path, [(t.start, t.end) for t in tasks])


def _end_key(e) -> tuple:
    return (e.get("ref"), e.get("pad"), tuple(e.get("at") or ()))


def _ob_key(o) -> tuple:
    return (o["net"], _end_key(o["from"]), _end_key(o["to"]))


def _pair_key(o) -> tuple:
    return (o["net"],) + tuple(sorted((_end_key(o["from"]), _end_key(o["to"])), key=repr))


def _unique(obs) -> list:
    """The obligations with each pad pair once (the first): the DRC can list two open connections between the same two
    pads, and a phase may state a task twice."""
    seen, out = set(), []
    for o in obs:
        k = _pair_key(o)
        if k not in seen:
            seen.add(k)
            out.append(o)
    return out


def obligations_of(selections, input_open, skip) -> list:
    """Each phase's asked set, fixed from the input board before any phase runs (ruling S6): a candidate route cannot
    change its own denominator. One list per selection, in phase order. An obligation is {"net", "from", "to",
    "widths": {layer: mm} | None}: a task phase's tasks at their widths; a net-level phase's input-board open
    connections (`input_open`, open_connections) on the nets it names, at its numeric width on its layers; the rest
    phase's, every input-board open connection whose net is not in `skip` and that no earlier phase names (ruling
    S10: a rest phase takes every connection still open when it runs, so one before the others asks for theirs too).
    Pure: selections are phase_select.Selection."""
    out, named = [], set()
    for sel in selections:
        if sel.tasks:
            obs = [dict({k: v for k, v in t.record().items() if k in ("net", "from", "to")}, widths=dict(t.widths))
                   for t in sel.tasks]
        elif sel.rest:
            obs = [dict(o, widths={layer: sel.width for layer in sel.layers} if sel.width else None) for o in input_open if o["net"] not in skip and o["net"] not in named]
        else:
            nets = (set(sel.nets) | set(sel.pour_nets) | {n for b in sel.buses for n in b}
                    | {n for q in sel.pairs for n in q})
            widths = {layer: sel.width for layer in sel.layers} if sel.width and sel.layers else None
            obs = [dict(o, widths=dict(widths) if widths else None) for o in input_open if o["net"] in nets]
        obs = _unique(obs)
        named |= {o["net"] for o in obs}
        out.append(obs)
    return out



def comparison_obligations(selections, geometry, skip) -> list:
    """Stable electrical obligations for comparing placements, independent of DRC airwire topology.

    Explicit tasks retain their declared ends and widths. Whole-net selections are judged by a deterministic
    spanning set of all selected pads. These pairs are used only to judge connectivity, never to direct routing.
    """
    from .phase_select import validate_terminals
    out = []
    for sel in selections:
        validate_terminals(sel.phase, sel, geometry, excluded=skip if not sel.tasks else ())
        if sel.tasks:
            out.append(_unique([t.record() for t in sel.tasks]))
            continue
        nets = (set(sel.nets) | set(sel.pour_nets) | {n for b in sel.buses for n in b}
                | {n for pair in sel.pairs for n in pair}) - set(skip)
        obs = []
        for net in sorted(nets):
            pads = sorted({(fp.ref, p.number) for fp in geometry.footprints for p in fp.pads if p.net == net})
            if len(pads) < 2:
                continue
            widths = {layer: sel.width for layer in sel.layers} if sel.width else None
            a = pads[0]
            obs += [{"net": net, "from": {"ref": a[0], "pad": a[1]}, "to": {"ref": b[0], "pad": b[1]},
                     "widths": dict(widths) if widths else None} for b in pads[1:]]
        out.append(obs)
    return out


def comparison_contract(phase, obligations) -> str:
    """The phase definition and stable electrical obligations, excluding every placement coordinate."""
    from .route_state import digest
    stable = sorted(({k: v for k, v in o.items() if k != 'width_policy_reason'} for o in obligations),
                    key=lambda o: repr(_pair_key(o)))
    return digest(phase.record(), stable)

def judge_obligations(pcb_path, obligations, drc_json, neck_mm=0.0, is_real=None) -> list:
    """Each obligation on a board, in order: {"joined", "violated", "under"}. joined: KiCad's connectivity joins the two
    ends' pads (joined_pairs); an obligation with an end that is no pad is joined when its net has no open connection
    in `drc_json`. violated: its net is in a real error of `drc_json` (drc.real_errors: the `real` bucket at severity
    error, as drc_new counts them; `is_real` is the board's DrcReport.is_real, None: the bound `[drc] real_kinds`). under: for a joined
    obligation with widths, the narrowest track per layer on its joining path (joining_path) under the width asked
    there, past `neck_mm` at either end (width_shortfall); {} when it meets them or has no widths. Unmeasured copper interiors set width_unknown. The DRC is the board's own."""
    from .drc import real_errors
    from .read import read_board
    data = json.loads(Path(drc_json).read_text())
    if is_real is None:
        from ..settings import active
        kinds = set(active().drc_real_kinds)
        is_real = kinds.__contains__
    violated = {n for e in real_errors(data, is_real) for n in e["nets"]}
    pads = [o for o in obligations if o["from"].get("ref") and o["to"].get("ref")]
    joined = dict(zip(map(_ob_key, pads), joined_pairs(pcb_path, [((o["from"]["ref"], o["from"]["pad"]),
                                                                    (o["to"]["ref"], o["to"]["pad"])) for o in pads])))
    loose = [o for o in obligations if _ob_key(o) not in joined]
    open_nets = {c["net"] for c in open_connections(pcb_path, drc_json)} if loose else set()
    geometry = (read_board(str(pcb_path)) if any(o.get("widths") and joined.get(_ob_key(o)) for o in obligations)
                else None)
    out = []
    for o in obligations:
        j = joined[_ob_key(o)] if _ob_key(o) in joined else o["net"] not in open_nets
        under = {}
        if j and o.get("widths") and geometry is not None:
            spans = joining_spans(geometry, o, full_width=True)
            if spans is None and neck_mm > 0:
                spans = joining_spans(geometry, o, full_width=True, neck_mm=neck_mm)
            if spans is None:
                spans = joining_spans(geometry, o)
            under = width_shortfall(spans, o["widths"], neck_mm) if spans is not None else {}
        unknown = bool(j and (o.get("width_policy_unknown") or
                              (o.get("widths") and (geometry is None or spans is None or
                                                    getattr(spans, "width_unknown", False) or bool(under)))))
        out.append({"joined": j, "violated": o["net"] in violated, "under": under, **({"width_unknown": True} if unknown else {})})
    return out


def is_clean(j: dict, outcome) -> bool:
    """Joined, not violated, not under its width, and not a `joined_narrow` outcome (ruling S6): a short a later phase
    laid, or a join narrower than asked, never reads clean."""
    return bool(j["joined"]) and not j["violated"] and not j["under"] and not j.get("width_unknown", False) and outcome != "joined_narrow"


def joining_path(geometry, o):
    """The tracks (CopperItems) of the shortest track path joining an obligation's two end pads (joining_spans), each
    once, ordered from the "to" end; None when no track path joins them."""
    spans = joining_spans(geometry, o)
    if spans is None or getattr(spans, "width_unknown", False):
        return None
    path = []
    for t, _ in spans:
        if not path or path[-1] is not t:
            path.append(t)
    return path


class _JoiningSpans(list):
    """Measured track spans, with an explicit flag for unmeasured interior bridges."""
    width_unknown = False


def joining_spans(geometry, o, *, full_width=False, neck_mm=0.0):
    """A joining path as (track, length) pieces with width_unknown for unmeasured interior bridges.

    Tracks split at ends and vias on their straight centreline. Full-width search removes narrow edges except
    spans reachable within an endpoint neck budget. The caller checks the recovered path's actual neck lengths.
    Full-width search excludes filled-region and intermediate-pad bridges: their interior corridor widths
    are unproved. Fallback retains measured tracks and marks width_unknown. Curved or absent paths return None.
    """
    import heapq
    import math
    from ..geometry import point_in_polygon, poly_distance
    net = o["net"]

    def pt(p):
        return (round(p[0], 3), round(p[1], 3))

    def pads_of(end):
        return [p for fp in geometry.footprints if fp.ref == end.get("ref") for p in fp.pads
                if p.number == end.get("pad") and p.net == net]

    start, goal = pads_of(o["from"]), pads_of(o["to"])
    if not start or not goal:
        return None
    adj = {}

    def link(a, b, length, track):
        adj.setdefault(a, []).append((b, length, track))
        adj.setdefault(b, []).append((a, length, track))

    tracks = [c for c in geometry.copper if c.net == net and c.kind == "track" and len(c.anchors) == 2]
    # Curved tracks need their actual centreline, not the endpoint chord. Leave their proof unknown.
    if any(abs(t.length_mm - math.dist(*t.anchors)) > 1e-3 for t in tracks):
        return None
    vias = [c for c in geometry.copper if c.net == net and c.kind == "via" and c.anchors]
    ends = {}                                       # layer -> the track ends and vias on it: where copper joins
    for t in tracks:
        ends.setdefault(next(iter(t.layers)), set()).update(pt(a) for a in t.anchors)
    for v in vias:
        for layer in v.layers:
            ends.setdefault(layer, set()).add(pt(v.anchors[0]))
    for t in tracks:                                # a track is split at every joint on it (a T, a via mid-track)
        layer = next(iter(t.layers))
        (ax, ay), (bx, by) = t.anchors
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        stops = []
        for p in ends.get(layer, ()):
            u = ((p[0] - ax) * dx + (p[1] - ay) * dy) / span if span else 0.0
            if -1e-6 <= u <= 1 + 1e-6 and math.hypot(ax + u * dx - p[0], ay + u * dy - p[1]) <= t.width_mm / 2:
                stops.append((u, p))
        stops.sort()
        for (u0, p0), (u1, p1) in zip(stops, stops[1:]):
            link((p0, layer), (p1, layer), (u1 - u0) * t.length_mm, t)
    for v in vias:
        layers = sorted(v.layers, key=lambda l: str(l.value))
        for a, b in zip(layers, layers[1:]):
            link((pt(v.anchors[0]), a), (pt(v.anchors[0]), b), 0.0, None)
    # Polygon connectivity cannot certify a corridor's width. Separate outlines and layers; only
    # an endpoint's anchor-containing pad polygon is a terminal. Other interiors remain unmeasured.
    unmeasured = object()
    regions = []
    for fp in geometry.footprints:
        for i, pad in enumerate(fp.pads):
            if pad.net != net:
                continue
            anchor = tuple(pad.airwire_end)
            for layer in pad.layers:
                for j, poly in enumerate(pad.outlines):
                    terminals = [tag for tag, end in (("A", o["from"]), ("B", o["to"]))
                                 if (fp.ref, pad.number) == (end.get("ref"), end.get("pad"))
                                 and point_in_polygon(anchor, poly)]
                    regions.append((poly, layer, ("pad", fp.ref, pad.number, i, layer, j), terminals, anchor))
    for i, copper in enumerate(geometry.copper):
        if copper.net == net and copper.kind in ("poly", "zone") and copper.filled:
            regions += [(poly, layer, ("region", i, layer, j), [], None)
                        for layer in copper.layers for j, poly in enumerate(copper.outlines)]
    nodes = list(adj)
    for poly, layer, tag, terminals, anchor in regions:
        for node in nodes:
            if node[1] == layer and point_in_polygon(node[0], poly):
                link(tag, node, 0.0, None if terminals and math.dist(node[0], anchor) <= 1e-3 else unmeasured)
        for terminal in terminals:
            link(terminal, tag, 0.0, None)
    for i, (poly, layer, tag, _, _) in enumerate(regions):
        for other, other_layer, other_tag, _, _ in regions[:i]:
            if layer == other_layer and poly_distance(poly, other) <= 1e-6:
                link(tag, other_tag, 0.0, unmeasured)
    if full_width:
        # End distances bound permitted pad necks. Every narrow graph span must fit wholly within one end's
        # neck budget; the recovered path is checked again by its own length, including the half-path cap.
        def end_distances(tag):
            dist, heap, seq = {tag: 0.0}, [(0.0, 0, tag)], 0
            while heap:
                d, _, u = heapq.heappop(heap)
                if d > dist.get(u, math.inf):
                    continue
                for v, length, track in adj.get(u, ()):
                    if track is unmeasured:
                        continue
                    if d + length <= neck_mm and d + length < dist.get(v, math.inf):
                        seq += 1
                        dist[v] = d + length
                        heapq.heappush(heap, (d + length, seq, v))
            return dist
        ends_dist = [end_distances(tag) for tag in ("A", "B")]
        def allowed(u, v, length, track):
            if track is unmeasured:
                return False
            if track is None:
                return True
            need = (o.get("widths") or {}).get(next(iter(track.layers)).value, 0.0)
            if track.width_mm >= need - 1e-3:
                return True
            return neck_mm > 0 and any(
                min(min(d.get(u, math.inf), d.get(v, math.inf)) + length,
                    (d.get(u, math.inf) + d.get(v, math.inf) + length) / 2) <= neck_mm + 1e-6
                for d in ends_dist)
        adj = {u: [(v, length, track) for v, length, track in edges if allowed(u, v, length, track)]
               for u, edges in adj.items()}
    dist, prev, heap, n = {"A": 0.0}, {}, [(0.0, 0, "A")], 0
    while heap:
        d, _, u = heapq.heappop(heap)
        if u == "B":
            break
        if d > dist.get(u, float("inf")):
            continue
        for v, length, track in adj.get(u, ()):
            if d + length < dist.get(v, float("inf")):
                n += 1
                dist[v], prev[v] = d + length, (u, track)
                heapq.heappush(heap, (d + length, n, v))
    if "B" not in dist:
        return None
    spans, u = _JoiningSpans(), "B"
    while u != "A":
        v = u
        u, track = prev[u]
        if track is unmeasured:
            spans.width_unknown = True
        elif track is not None:
            spans.append((track, dist[v] - dist[u]))
    return spans


def width_shortfall(path, widths, neck_mm) -> dict:
    """{layer name: narrowest mm} of the copper on `path` under the width asked on its layer, past the neck allowance;
    {} when the path meets its widths. `path` is joining_spans' (track, length) pieces, or tracks taken whole.

    The rule is on points of the path, not on how its copper is split into tracks (route_widths._neck_lengths also
    judges by distance along the copper, but with no cap at half the path): with L the path's length and a =
    min(neck_mm, L / 2), copper at a distance under `a` from either end is the router's pad neck-down and is not
    counted; copper strictly between a and L - a must be at full width. So every connection keeps copper at full width
    (the user's decision of 2026-10-07): on a path too short to hold both necks (a = L / 2) its middle point must lie on
    full-width copper. neck_mm 0 (`neckdown = false`): no allowance."""
    from ..values import CopperLayer
    from .route_widths import _UNDER_MM
    eps = 1e-6
    pieces = [p if isinstance(p, tuple) else (p, p.length_mm) for p in path]
    names = {CopperLayer.of(name): name for name in widths}
    spans, run = [], 0.0
    for t, length in pieces:
        layer = names.get(next(iter(t.layers)))
        narrow = layer is not None and t.width_mm < widths[layer] - _UNDER_MM
        spans.append((run, run + length, t, layer, narrow))
        run += length
    total = run
    a = min(max(neck_mm, 0.0), total / 2)
    if total - 2 * a > eps:                             # an open stretch at full width: no narrow copper inside it
        counted = [sp for sp in spans if sp[4] and sp[1] > a + eps and sp[0] < total - a - eps]
    else:                                               # too short for both necks: the middle point decides
        mid = total / 2
        at_mid = [sp for sp in spans if sp[0] - eps <= mid <= sp[1] + eps]
        counted = [sp for sp in at_mid if sp[4]] if all(sp[4] for sp in at_mid) else []
    out = {}
    for _, _, t, layer, _ in counted:
        out[layer] = min(out.get(layer, t.width_mm), t.width_mm)
    return out


def _record_of(o, connections):
    return next((r for r in connections if r.get("net") == o["net"] and r.get("from") == o["from"]
                 and r.get("to") == o["to"]), None)


def outcome_of(o, connections):
    """The status of the obligation's --connections record; None when no record names it (a whole-net call)."""
    rec = _record_of(o, connections)
    return rec.get("status") if rec else None


def open_entry(o, j, connections, net_evidence) -> dict:
    """An obligation left open, with what the router said of it: its record's `outcome` and `evidence`, or the net's
    `net_evidence`; None when the router gave none. Router facts only: placemat infers no cause here (Task 6a)."""
    rec = _record_of(o, connections)
    out = dict(o, outcome=rec.get("status") if rec else None,
               evidence=rec.get("evidence") if rec else (net_evidence or {}).get(o["net"]))
    if j["joined"] and j["violated"]:
        out["violated"] = True
    if j.get("width_unknown"):
        out["width_unknown"] = True
    if j["joined"] and j["under"]:
        out["under"] = dict(j["under"])
    return out


def phase_record(phase, index, sel, obligations, judged, seconds, calls, pairs=None, connections=(), bus_groups=(),
                 net_evidence=None) -> dict:
    """What one phase did: its definition, `asked` (its obligations), `joined` (those clean on the board after it),
    `closure_clean` (joined / asked, 1.0 when nothing is asked), `open` (open_entry of each one not clean), its time,
    router calls, pair outcome, --connections records and bus groups. `reused` is set by the route."""
    connections = list(connections)
    rec = dict(phase.record(), index=index, seconds=round(seconds, 1), reused=False, calls=calls, pairs=pairs,
               connections=connections, bus_groups=list(bus_groups), widths=[])
    clean = [is_clean(j, outcome_of(o, connections)) for o, j in zip(obligations, judged)]
    rec.update(asked=len(obligations), joined=sum(clean),
               closure_clean=round(sum(clean) / len(obligations), 4) if obligations else 1.0,
               open=[open_entry(o, j, connections, net_evidence or {})
                     for o, j, ok in zip(obligations, judged, clean) if not ok])
    return rec


def open_connections(pcb_path, drc_json) -> list:
    """Each connection the DRC reports open (`unconnected_items`), named by its two ends' pads. KiCad gives each item's
    uuid; a pad end is that pad, a track, via or zone end is the first pad (by ref, pad) joined to it through copper
    (CONNECTIVITY_DATA.GetConnectedPads), and an end that is no pad and joins none is {"ref": None, "pad": None,
    "at": [x, y]} (mm, the DRC's position). The net is the item's own, never read from the description. Ends are in
    (ref, pad) order."""
    from .quiet import import_pcbnew, quiet_stderr
    from .write import load_board
    import_pcbnew()
    raw_items = json.loads(Path(drc_json).read_text()).get("unconnected_items", [])
    if not raw_items:
        return []
    with quiet_stderr():
        board = load_board(str(pcb_path))
    board.BuildConnectivity()
    cn = board.GetConnectivity()
    items = {}
    for it in list(board.GetPads()) + list(board.GetTracks()) + list(board.Zones()):
        items[it.m_Uuid.AsString()] = it

    def key(pad):
        return (pad.GetParentFootprint().GetReference(), pad.GetNumber())

    def end(raw):
        pos = raw.get("pos") or {}
        loose = {"ref": None, "pad": None, "at": [pos.get("x", 0.0), pos.get("y", 0.0)]}
        it = items.get(raw.get("uuid", ""))
        if it is None:
            return "", loose
        if it.GetClass() == "PAD":
            ref, pad = key(it)
            return it.GetNetname(), {"ref": ref, "pad": pad}
        joined = sorted(key(p) for p in cn.GetConnectedPads(it))
        return it.GetNetname(), ({"ref": joined[0][0], "pad": joined[0][1]} if joined else loose)

    out = []
    for u in raw_items:
        raw = u.get("items", [])
        if len(raw) < 2:
            continue
        (na, a), (nb, b) = end(raw[0]), end(raw[1])
        a, b = sorted((a, b), key=lambda e: (e["ref"] is None, e["ref"] or "", e["pad"] or ""))
        out.append({"net": na or nb, "from": a, "to": b})
    return out


def connection_summary(path, pending, phase, log):
    """Ordered task results must identify every submitted task before any widths or deferrals are consumed."""
    reason, index = None, None
    try:
        data = json.loads(Path(path).read_text())
        recs = data.get("connections")
        if not isinstance(recs, list) or len(recs) != len(pending):
            reason = "task_count"
        else:
            for index, (task, record) in enumerate(zip(pending, recs)):
                asked = task.record()
                if not isinstance(record, dict) or any(record.get(k) != asked[k] for k in ("net", "from", "to", "widths")):
                    reason = "task_identity"
                    break
                if record.get("status") not in {"routed", "joined_before", "joined_narrow", "failed", "deferred", "refused"}:
                    reason = "task_status"
                    break
    except (OSError, ValueError, AttributeError, TypeError):
        reason, data = "unreadable", {}
    if reason:
        facts = {"phase": phase, "summary": str(path), "reason": reason, "asked": len(pending)}
        if index is not None:
            facts["index"] = index
        raise RouterFailed("the router wrote malformed connection results for phase %s (%s)" % (phase, reason),
                           0, log, "", code="malformed_summary", facts=facts)
    return data


def _completed_single_call(ctx, cmd, log, what, source, output, token, *, run=None):
    """One existing single-call lifecycle, including its actual restoration.

    A private proposal callback must encompass this whole operation. The raw
    snapshot is retained before companion restoration and locking; completion
    evidence is retained only after those existing operations finish.
    """
    rc = (run or _run)(cmd, log, ctx)
    if ctx.execution is not None:
        ctx.execution.raw_call(token, rc)
    if rc != 0 or not output.exists():
        _failed(rc, log, what)
    _copy_project(source, output)
    lock_copper(str(output))
    if ctx.execution is not None:
        ctx.execution.restored_call(token)
    return rc


def route_calls(ctx, index, phase, sel, board) -> PhaseOutcome:
    """Route one phase's calls (plan_calls) on `board`, in order, each on the board the one before left, its copper
    locked. The outcome's `routed` is what judge_phase needs. A task the router refuses stops the route (RouteRefused
    "router_refused"); a call that fails raises RouterFailed."""
    t0 = time.time()
    from . import net_clearance
    from .route import routing_clearance
    args = tuple(ctx.cfg.route_router_args) + tuple(phase.router_args)
    phase_map = net_clearance.merged(ctx.class_clearances, ctx.stated_clearances,
                                    net_clearance.ceiling(args, ctx.env))
    phase_file = None
    if ctx.stated_clearances:
        phase_file = ctx.work / ("p%d_net_clearances.json" % index)
        phase_file.write_text(json.dumps(phase_map, sort_keys=True) + "\n")
    ctx = replace(ctx, clearance_map=phase_map, clearances_file=phase_file,
                  base_clearance=routing_clearance(ctx.geometry.default_clearance, args, ctx.env))
    calls = plan_calls(sel, ctx.clearance_map, ctx.base_clearance, set(ctx.excluded) | set(ctx.pour_nets))
    layers = list(sel.layers)
    if ctx.execution is not None:
        ctx.execution.plan_calls(phase=index, calls=calls, layers=layers, input_board=board)
    out = PhaseOutcome(board, {}, {})
    pairs, connections, bus_groups = None, [], []
    common = dict(iterations=ctx.iterations, probe=ctx.probe, quick=ctx.quick, clearances=ctx.clearances_file,
                  neckdown=phase.neckdown, extra_args=tuple(phase.router_args))
    what = "phase %s" % phase.name
    for k, call in enumerate(calls):
        stem = "p%d_%d" % (index, k)
        nxt = ctx.work / (stem + ".kicad_pcb")
        summary = ctx.work / (stem + "_summary.json")
        single_token = None
        single_restored = False
        if call.kind == "pairs":
            # the phase's own router flags go to the pair router too; its neck-down is route.py's only (route_diff.py
            # has no --no-power-tap-neckdown), so `neckdown` does not reach a pair call
            got, found = route_pairs(ctx.rpy, ctx.router_dir, board, ctx.work, list(sel.pairs), layers, ctx.cfg,
                                     ctx.iterations, ctx.probe, ctx.timeout, ctx.env, events=ctx.events, stem=stem,
                                     extra_args=tuple(phase.router_args),
                                     clearances=ctx.stated_clearances or None)
            pairs = found.as_dict()
            if Path(got) != nxt:
                shutil.copy(got, nxt)
                _copy_project(got, nxt)
        elif call.kind == "pour":
            route_pour_net(ctx, board, nxt, call.nets[0], call.width, layers, stem, phase.neckdown,
                           tuple(phase.router_args),
                           _issued_scope=(index, k, call.tasks) if ctx.execution is not None else None)
            out.summaries.append((phase.name, k, summary))
        elif call.kind in ("tasks", "bus_tasks"):
            pending, j, src = list(call.tasks), 0, board
            while pending:
                cfile = write_connections(pending, ctx.work / ("%s_%d_connections.json" % (stem, j)), layers)
                part = ctx.work / ("%s_%d.kicad_pcb" % (stem, j))
                psum = ctx.work / ("%s_%d_summary.json" % (stem, j))
                cmd = router_command(ctx.rpy, ctx.script, src, part, set(), layers, psum, connections=cfile,
                                     bus_nets=list(call.nets) if call.kind == "bus_tasks" else None, **common)
                log = ctx.work / ("%s_%d.log" % (stem, j))
                token = None
                if ctx.execution is not None:
                    constraints = (ctx.clearances_file,) if ctx.clearances_file else ()
                    token = ctx.execution.issue_call(
                        phase=index, call=k, wave=j, kind='connections', command=cmd,
                        source=src, input_board=src, output_board=part, summary=psum,
                        layers=layers, nets=sorted({task.net for task in pending}),
                        tasks=[task.record() for task in pending], constraint_files=constraints,
                        task_file=cfile, environment=ctx.env)
                rc = _run(cmd, log, ctx)
                if ctx.execution is not None:
                    ctx.execution.raw_call(token, rc)
                if rc != 0 or not part.exists():
                    _failed(rc, log, what)
                _copy_project(src, part)
                lock_copper(str(part))
                out.summaries.append((phase.name, k, psum))
                data = connection_summary(psum, pending, phase.name, log)
                if ctx.execution is not None:
                    ctx.execution.restored_call(token)
                recs = data.get("connections") or []
                if call.kind == "bus_tasks":
                    bus_groups += data.get("bus_groups") or []
                refused = refused_records(recs)
                if refused:
                    raise RouteRefused("router_refused", phase=phase.name, tasks=refused)
                attempted = tuple(t for t, r in zip(pending, recs) if r.get("status") != "deferred")
                if attempted:
                    out.calls.append((replace(call, tasks=attempted), src, part))
                deferred = [t for t, r in zip(pending, recs) if r.get("status") == "deferred"]
                connections += [r for r in recs if r.get("status") != "deferred"]
                if len(deferred) == len(pending):     # nothing moved: the router deferred every task; they stay so
                    connections += [r for r in recs if r.get("status") == "deferred"]
                    break
                pending, src, j = deferred, part, j + 1
            shutil.copy(src, nxt)
            _copy_project(src, nxt)
        else:
            if call.kind == "rest":
                # the router refuses a `*` that matches no net (exit 1, "No nets matched the given patterns!"):
                # with none left, the board stands as it is
                if not main_pass_nets(ctx.geometry.nets, set(call.excluded)):
                    shutil.copy(board, nxt)
                    _copy_project(board, nxt)
                    out.calls.append((call, board, nxt))
                    board = nxt
                    continue
                cmd = router_command(ctx.rpy, ctx.script, board, nxt, set(call.excluded), layers, summary,
                                     widths={n: call.width for n in call.nets} if call.width else None, **common)
            else:
                widths = {n: call.width for n in call.nets} if call.width else None
                cmd = router_command(ctx.rpy, ctx.script, board, nxt, set(), layers, summary, nets=list(call.nets),
                                     widths=widths, bus_nets=list(call.nets) if call.kind == "bus" else None, **common)
            log = ctx.work / (stem + ".log")
            if ctx.execution is not None and call.kind in ('nets', 'rest'):
                constraints = (ctx.clearances_file,) if ctx.clearances_file else ()
                issued_nets = (sorted(main_pass_nets(ctx.geometry.nets, set(call.excluded)))
                               if call.kind == 'rest' else list(call.nets))
                single_token = ctx.execution.issue_call(
                    phase=index, call=k, wave=0, kind='single', command=cmd,
                    source=board, input_board=board, output_board=nxt, summary=summary,
                    layers=layers, nets=issued_nets, tasks=[], constraint_files=constraints, environment=ctx.env)
            if call.kind in ('nets', 'rest'):
                _completed_single_call(ctx, cmd, log, what, board, nxt, single_token)
                single_restored = True
            else:
                rc = _run(cmd, log, ctx)
                if ctx.execution is not None:
                    ctx.execution.raw_call(single_token, rc)
                if rc != 0 or not nxt.exists():
                    _failed(rc, log, what)
                _copy_project(board, nxt)
            out.summaries.append((phase.name, k, summary))
            if call.kind == "bus" and summary.exists():
                bus_groups += json.loads(summary.read_text()).get("bus_groups") or []
        if not single_restored:
            lock_copper(str(nxt))
            if ctx.execution is not None:
                ctx.execution.restored_call(single_token)
        if call.kind not in ("tasks", "bus_tasks"):
            out.calls.append((call, board, nxt))
        board = nxt
    if not calls:                                   # a phase that selected nothing open: its board is its input
        nxt = ctx.work / ("p%d_0.kicad_pcb" % index)
        shutil.copy(board, nxt)
        _copy_project(board, nxt)
        board = nxt
    out.board = board
    out.routed = Routed(board, time.time() - t0, len(calls), pairs, connections, bus_groups,
                        [(n, k, str(sp)) for n, k, sp in out.summaries],
                        phase_widths(phase, out.calls, ctx.cfg)
                        + narrow_join_widths(phase, sel, connections, board, ctx.cfg)
                        + task_widths(phase, sel, connections)).record()
    return out


def judge_phase(ctx, index, phase, sel, routed: Routed, obligations) -> tuple:
    """A phase's judgement on the board its calls left: a DRC of a copy (guards off, zones filled), then each obligation
    judged on it. Returns (phase_record, {net: open items} from that DRC)."""
    t0 = time.time()
    judged = ctx.work / ("p%d_drc.kicad_pcb" % index)
    drc_json = ctx.work / ("p%d_drc.json" % index)
    shutil.copy(routed.board, judged)
    _copy_project(routed.board, judged)
    remove_guards(str(judged))
    fill_zones(str(judged))
    drc = run_drc(judged, drc_json, refill_zones=False)
    net_evidence = {}
    for _, _, path in routed.summaries:             # a later call's record of a net wins
        if Path(path).exists():
            try:
                net_evidence.update(json.loads(Path(path).read_text()).get("net_evidence") or {})
            except ValueError:
                pass
    neck = phase_neck(ctx.cfg, phase)
    record = phase_record(phase, index, sel, obligations,
                          judge_obligations(judged, obligations, drc_json, neck, drc.is_real),
                          routed.seconds + time.time() - t0, routed.ncalls, routed.pairs, routed.connections,
                          routed.bus_groups, net_evidence)
    record["widths"] = list(routed.widths)
    return record, dict(drc.open_nets)


def phase_neck(cfg, phase) -> float:
    """The neck allowance a phase's widths are judged with: the router's (route_widths.neck_allowance, from
    `[route] router_args` and the phase's), none with `neckdown = false`."""
    from .route_widths import neck_allowance
    return neck_allowance(tuple(cfg.route_router_args) + tuple(phase.router_args)) if phase.neckdown else 0.0


def run_phase(ctx, index, phase, sel, board, obligations) -> PhaseOutcome:
    """Route one phase on `board` (route_calls), then judge its obligations on the board it left (judge_phase)."""
    out = route_calls(ctx, index, phase, sel, board)
    out.record, out.open_nets = judge_phase(ctx, index, phase, sel, Routed.of(out.routed, ctx.work), obligations)
    return out


def phase_widths(phase, calls, cfg) -> list:
    """The width judgement of one phase (D17): for each call that asked a width, the copper it added (its board out
    against its board in) judged against what it asked, per layer."""
    from ..board_geometry import added_copper
    from ..values import CopperLayer
    from .read import read_board
    from .route_widths import board_widths, neck_allowance
    neck = neck_allowance(tuple(cfg.route_router_args) + tuple(phase.router_args)) if phase.neckdown else 0.0
    out = []
    for call, before, after in calls:
        if call.kind in ("tasks", "bus_tasks"):
            asks = {}
            for task in call.tasks:
                widths = asks.setdefault(task.net, {})
                for layer, width in task.widths:
                    key = CopperLayer.of(layer)
                    widths[key] = max(widths.get(key, 0.0), width)
            by = "current" if any(t.amps is not None for t in call.tasks) else "asked"
        elif call.width:
            asks = {n: {CopperLayer.of(l): call.width for l in phase.layers or ()} or None for n in call.nets}
            by = "asked"
        else:
            continue
        given, routed = read_board(str(before)), read_board(str(after))
        new = added_copper(given.copper, routed.copper)
        asks = {n: a or {l: call.width for l in routed.layers} for n, a in asks.items()}
        out += board_widths(routed, asks, phase.name, cfg.check_rise_c, None, neck, only=new, by=by)
    return out


def narrow_join_widths(phase, sel, connections, routed_pcb, cfg) -> list:
    """A task KRT reported `joined_narrow` and left unrouted (D3's fallback): the joining path its record names is
    judged against the task's asked widths, so the phase raises route.width on it. The path is matched to the routed
    board's tracks of the net by layer and both ends (to the micrometre)."""
    from ..values import CopperLayer
    from .read import read_board
    from .route_widths import board_widths, neck_allowance
    narrow = [r for r in connections if r.get("status") == "joined_narrow" and r.get("path")]
    if not narrow:
        return []
    tasks = {(t.net, tuple(t.start), tuple(t.end)): t for t in sel.tasks}
    routed = read_board(str(routed_pcb))
    neck = neck_allowance(tuple(cfg.route_router_args) + tuple(phase.router_args)) if phase.neckdown else 0.0
    out = []
    for r in narrow:
        t = tasks.get((r["net"], (r["from"]["ref"], r["from"]["pad"]), (r["to"]["ref"], r["to"]["pad"])))
        if t is None:
            continue
        path = {(CopperLayer.of(s["layer"]), _ends(s["start"], s["end"])) for s in r["path"]}
        only = [c for c in routed.copper if c.kind == "track" and c.net == t.net and len(c.anchors) == 2
                and any((layer, _ends(*c.anchors)) in path for layer in c.layers)]
        asks = {t.net: {CopperLayer.of(layer): w for layer, w in t.widths}}
        out += board_widths(routed, asks, phase.name, cfg.check_rise_c, None, neck, only=only,
                            by="current" if t.amps is not None else "asked")
    return out


def _ends(a, b) -> frozenset:
    return frozenset((round(p[0], 3), round(p[1], 3)) for p in (a, b))


def task_widths(phase, sel, connections) -> list:
    """KRT's own narrowest width per layer of each routed task (`min_width_mm`) against the task's asked width, for a
    phase with `neckdown = false`, whose calls carry --no-power-tap-neckdown: the router laid no tap neck, so a layer
    under its width is a shortfall. With neck-down on, nothing: a neck under the width is expected within the
    allowance, and phase_widths judges the length past it on the board."""
    from .route_widths import _UNDER_MM
    if phase.neckdown:
        return []
    tasks = {(t.net, tuple(t.start), tuple(t.end)): t for t in sel.tasks}
    out = []
    for r in connections:
        if r.get("status") != "routed":
            continue
        t = tasks.get((r["net"], (r["from"]["ref"], r["from"]["pad"]), (r["to"]["ref"], r["to"]["pad"])))
        if t is None:
            continue
        asked = dict(t.widths)
        rows = [{"layer": layer, "need_mm": asked[layer], "min_mm": got, "by": "current" if t.amps is not None else "asked"}
                for layer, got in sorted((r.get("min_width_mm") or {}).items())
                if layer in asked and got < asked[layer] - _UNDER_MM]
        if rows:
            out.append({"net": t.net, "stage": phase.name, "from": dict(r["from"]), "to": dict(r["to"]),
                        "requested_mm": max(asked.values()), "delivered_min_mm": min(x["min_mm"] for x in rows),
                        "length_under_mm": None, "length_mm": r.get("length_mm"), "share": None, "declared": True,
                        "max_a": None, "bottleneck_mm": None, "layers": rows, "source": "router"})
    return out


def widths_failed(records, asked, final_judged) -> int:
    """Obligations joined on the final board under their width on their joining path, and joined_narrow outcomes."""
    n = 0
    for rec, obs, got in zip(records, asked, final_judged):
        for o, j in zip(obs, got):
            if j["joined"] and (j["under"] or j.get("width_unknown", False) or outcome_of(o, rec.get("connections") or []) == "joined_narrow"):
                n += 1
    return n
