"""One routing phase's router calls, in order, each on the board the one before it left with its copper locked, and the
phase's own judgement: each of its obligations (the pad pairs it is asked to join, fixed from the input board before
any phase runs) judged on a DRC of the board after the phase. The calls are planned here from a Selection
(kicad/phase_select.py); a phase holding nets of several clearances routes one call per clearance, widest first,
because KRT spaces a whole call at the largest clearance among its nets (py_router/routing_config.py:485-509,
set_net_clearances)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
from pathlib import Path
import shutil
import time

from .drc import run_drc
from .route import (RouteRefused, RouterFailed, _copy_project, run_router, clearance_groups, fill_zones,
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
    from .phase_select import end_record
    # an end names its footprint's uuid ("fp") only when another footprint has its reference: an ordinary board's
    # file is as before
    path.write_text(json.dumps([{"net": t.net, "from": end_record(t.start), "to": end_record(t.end),
                                 "widths": dict(t.widths)} for t in tasks],
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
    return run_router(cmd, log, ctx.router_dir, ctx.env, ctx.timeout)


def _failed(rc, log, what):
    tail = "\n".join(Path(log).read_text(errors="replace").splitlines()[-8:])
    raise RouterFailed("the router exited %s routing %s" % (rc, what), rc, log, tail)


def joined_pairs(pcb_path, pairs) -> list:
    """Whether each pair's two ends are joined on the board, by KiCad's own connectivity (BuildConnectivity, the same
    test route_cleanup.pad_groups makes): an end, (ref, pad) or (ref, pad, footprint uuid), is every pad of that
    footprint with that number; without the uuid, of every footprint with that reference."""
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
        fp = p.GetParentFootprint()
        pads.setdefault((fp.GetReference(), p.GetNumber()), []).append((fp.m_Uuid.AsString(), p))

    def end_pads(end):
        fp = end[2] if len(end) > 2 else None
        return [p for u, p in pads.get((end[0], end[1]), ()) if fp is None or u == fp]
    out = []
    for a, b in pairs:
        ends_b = {p.m_Uuid.AsString() for p in end_pads(tuple(b))}
        joined = False
        for pa in end_pads(tuple(a)):
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
    return (e.get("ref"), e.get("pad"), e.get("fp"), tuple(e.get("at") or ()))


def _end_pair(e) -> tuple:
    """An end as joined_pairs takes it: (ref, pad), with the footprint's uuid when the end names one."""
    return (e["ref"], e["pad"], e["fp"]) if e.get("fp") else (e["ref"], e["pad"])


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


def judge_obligations(pcb_path, obligations, drc_json, neck_mm=0.0, is_real=None) -> list:
    """Each obligation on a board, in order: {"joined", "violated", "under"}. joined: KiCad's connectivity joins the two
    ends' pads (joined_pairs); an obligation with an end that is no pad is joined when its net has no open connection
    in `drc_json`. violated: its net is in a real error of `drc_json` (drc.real_errors: the `real` bucket at severity
    error, as drc_new counts them; `is_real` is the board's DrcReport.is_real, None: the bound `[drc] real_kinds`).
    under: for a joined obligation with widths, the narrowest copper per layer on its joining path (joining_spans:
    tracks, and the fills and pads it passes through, measured) under the width asked there, past `neck_mm` at
    either end (width_shortfall); {} when it meets them or has no widths. width_unknown: joined, with widths, but no
    copper path between its ends could be measured. The DRC is the board's own."""
    from .drc import real_errors
    from .read import read_board
    data = json.loads(Path(drc_json).read_text())
    if is_real is None:
        from ..settings import active
        kinds = set(active().drc_real_kinds)
        is_real = kinds.__contains__
    violated = {n for e in real_errors(data, is_real) for n in e["nets"]}
    pads = [o for o in obligations if o["from"].get("ref") and o["to"].get("ref")]
    joined = dict(zip(map(_ob_key, pads), joined_pairs(pcb_path, [(_end_pair(o["from"]), _end_pair(o["to"]))
                                                                   for o in pads])))
    loose = [o for o in obligations if _ob_key(o) not in joined]
    open_nets = {c["net"] for c in open_connections(pcb_path, drc_json)} if loose else set()
    geometry = (read_board(str(pcb_path)) if any(o.get("widths") and joined.get(_ob_key(o)) for o in obligations)
                else None)
    rasters = {}                                    # the fills' rasters, shared by the obligations on this board
    out = []
    for o in obligations:
        j = joined[_ob_key(o)] if _ob_key(o) in joined else o["net"] not in open_nets
        under, spans = {}, None
        if j and o.get("widths") and geometry is not None:
            spans = joining_spans(geometry, o, full_width=True, cache=rasters)
            if spans is None and neck_mm > 0:
                spans = joining_spans(geometry, o, full_width=True, neck_mm=neck_mm, cache=rasters)
            if spans is None:
                spans = joining_spans(geometry, o, cache=rasters)
            under = width_shortfall(spans, o["widths"], neck_mm) if spans is not None else {}
        # unknown only where no joining path could be measured; a measured shortfall is `under` alone
        unknown = bool(j and (o.get("width_policy_unknown") or
                              (o.get("widths") and spans is None)))
        out.append({"joined": j, "violated": o["net"] in violated, "under": under, **({"width_unknown": True} if unknown else {})})
    return out


def is_clean(j: dict, outcome) -> bool:
    """Joined, not violated, not under its width, and not a `joined_narrow` outcome (ruling S6): a short a later phase
    laid, or a join narrower than asked, never reads clean."""
    return bool(j["joined"]) and not j["violated"] and not j["under"] and not j.get("width_unknown", False) and outcome != "joined_narrow"


def joining_path(geometry, o):
    """The tracks (CopperItems) of the shortest copper path joining an obligation's two end pads (joining_spans), each
    once, ordered from the "to" end; None when no copper path joins them."""
    spans = joining_spans(geometry, o)
    if spans is None:
        return None
    path = []
    for t, _ in spans:
        if t.kind == "track" and (not path or path[-1] is not t):
            path.append(t)
    return path


@dataclass(frozen=True)
class FillStretch:
    """A stretch of a joining path through filled copper - a zone's fill, a filled drawn polygon or a pad the path
    passes through - as width_shortfall reads a track: its layer, its width there, and where it is narrowest. The
    width is the widest disc that travels through the copper from the copper the path enters it by to the copper it
    leaves it by (checks._Fill.width, the current-path check's measure); `tolerance_mm` is that measure's resolution
    (one `[check] zone_step`)."""
    kind: str                       # "zone" | "poly" | "pad"
    layers: frozenset
    width_mm: float
    at: tuple
    tolerance_mm: float = 0.0


def _fill_need(fill, need):
    """The width a fill is judged at for `need`: one raster step less, the measure's own resolution (a fill exactly
    `need` wide reads up to one step narrower)."""
    return None if need is None else max(need - fill.s, 0.0)


def _crossing(fill, kind, layer, entry, exit_, need) -> list:
    """The (FillStretch, length) pieces of a path through `fill` from the copper `entry` to the copper `exit_` (tuples
    of polygons), entry first: its narrow runs under `need` (`_Fill.narrow_runs`, judged at `_fill_need`) each at its
    narrowest width, and the stretches between them at `need`. [] when the two touch each other."""
    got = fill.narrow_runs(entry, exit_, _fill_need(fill, need) or 0.0)
    if got is None:
        return []
    layers = frozenset((layer,))
    if need is None or not got["runs"]:
        return [(FillStretch(kind, layers, got["width_mm"], got["at"], fill.s), got["length_mm"])]
    out, done, total = [], 0.0, got["length_mm"]
    for r in got["runs"]:
        # the narrow stretch, `narrow_mm` long, inside the run's extent: against the path's end for a run at an end,
        # else in the middle of it
        span = r["to_mm"] - r["from_mm"]
        if r["from_mm"] <= 0.0:
            lo = r["from_mm"]
        elif r["to_mm"] >= total:
            lo = r["to_mm"] - r["narrow_mm"]
        else:
            lo = r["from_mm"] + (span - r["narrow_mm"]) / 2.0
        if lo > done:
            out.append((FillStretch(kind, layers, need, r["at"], fill.s), lo - done))
        out.append((FillStretch(kind, layers, r["width_mm"], r["at"], fill.s), r["narrow_mm"]))
        done = lo + r["narrow_mm"]
    if got["length_mm"] > done:
        out.append((FillStretch(kind, layers, need, got["at"], fill.s), got["length_mm"] - done))
    return out


def _closest_points(a, b) -> tuple:
    """The closest points of segments a and b (each two points) and their distance: (p on a, q on b, distance)."""
    (ax, ay), (bx, by) = a
    (cx, cy), (dx, dy) = b
    ux, uy, vx, vy, wx, wy = bx - ax, by - ay, dx - cx, dy - cy, ax - cx, ay - cy
    A, B, C, D, E = ux * ux + uy * uy, ux * vx + uy * vy, vx * vx + vy * vy, ux * wx + uy * wy, vx * wx + vy * wy
    best = None
    cands = []
    den = A * C - B * B
    if den > 1e-12:
        cands.append(((B * E - C * D) / den, (A * E - B * D) / den))
    for s_ in (0.0, 1.0):                           # each end of a against b, and of b against a
        t_ = (B * s_ + E) / C if C > 1e-12 else 0.0
        cands.append((s_, t_))
    for t_ in (0.0, 1.0):
        s_ = (B * t_ - D) / A if A > 1e-12 else 0.0
        cands.append((s_, t_))
    for s_, t_ in cands:
        s_, t_ = min(max(s_, 0.0), 1.0), min(max(t_, 0.0), 1.0)
        p, q = (ax + s_ * ux, ay + s_ * uy), (cx + t_ * vx, cy + t_ * vy)
        d = math.dist(p, q)
        if best is None or d < best[2] - 1e-12:
            best = (p, q, d)
    return best


def _nearest_on_segment(seg, poly, within=math.inf) -> tuple:
    """The point of segment `seg` nearest polygon `poly` and its distance (0 inside it or on its edge), looking only
    at the edges whose box comes within `within` of the segment's; (None, inf) when none is that near."""
    from ..geometry import point_in_polygon, segments_intersect
    a, b = seg
    for p in (a, b):
        if point_in_polygon(p, poly):
            return p, 0.0
    x0, x1 = min(a[0], b[0]) - within, max(a[0], b[0]) + within
    y0, y1 = min(a[1], b[1]) - within, max(a[1], b[1]) + within
    best = (None, math.inf)
    for q1, q2 in zip(poly, poly[1:] + poly[:1]):
        if max(q1[0], q2[0]) < x0 or min(q1[0], q2[0]) > x1 or max(q1[1], q2[1]) < y0 or min(q1[1], q2[1]) > y1:
            continue
        if segments_intersect(a, b, q1, q2):
            return _closest_points((a, b), (q1, q2))[0], 0.0
        p, _, d = _closest_points((a, b), (q1, q2))
        if d < best[1]:
            best = (p, d)
    return best


def _net_copper(geometry, net, cache) -> dict | None:
    """One net's copper as joining_spans searches it, the same for every obligation on the net (kept in `cache`):
    "adj", the track pieces between joints (track ends, vias, and the points where copper overlaps a track; a track
    split at every joint whose copper overlaps it) and the vias joining their layers; "at_joint", the copper meeting at each joint; "regions", each filled polygon on
    each layer, (key, kind, layer, polygon, (ref, pad, footprint uuid) for a pad, pad identity for a pad); "inside", the joints
    joined to each region; "touching", the regions on one layer that touch; "layer_pairs", one pad's regions on two layers; "own",
    each region's polygon as a tuple."""
    from ..geometry import circle_polygon, point_in_polygon, point_segment_distance, poly_distance
    from ..values import Box, Location
    key = ("net", net)
    if key in cache:
        return cache[key]

    def pt(p):
        return (round(p[0], 3), round(p[1], 3))

    tracks = [c for c in geometry.copper if c.net == net and c.kind == "track" and len(c.anchors) == 2]
    # a curved track (an arc: longer than its chord) is one piece between its two ends at its own length and width;
    # it is not split at a joint along it, which can leave such a joint unjoined, never a path falsely clean
    arcs = [t for t in tracks if abs(t.length_mm - math.dist(*t.anchors)) > 1e-3]
    vias = [c for c in geometry.copper if c.net == net and c.kind == "via" and c.anchors]
    adj = {}

    def link(a, b, length, piece):
        adj.setdefault(a, []).append((b, length, piece))
        adj.setdefault(b, []).append((a, length, piece))

    joints, at_joint = {}, {}                       # layer -> joints on it; joint -> the copper that meets there
    reach = {}                                      # joint -> half the widest copper meeting there
    for t in tracks:
        layer = next(iter(t.layers))
        for a in t.anchors:
            joints.setdefault(layer, set()).add(pt(a))
            at_joint.setdefault((pt(a), layer), []).extend(t.outlines)
            reach[(pt(a), layer)] = max(reach.get((pt(a), layer), 0.0), t.width_mm / 2)
    for v in vias:
        for layer in v.layers:
            joints.setdefault(layer, set()).add(pt(v.anchors[0]))
            at_joint.setdefault((pt(v.anchors[0]), layer), []).extend(v.outlines)
            reach[(pt(v.anchors[0]), layer)] = max(reach.get((pt(v.anchors[0]), layer), 0.0), v.width_mm / 2)
    # a track's round end is copper too: a disc of its half width at each joint
    at_joint = {k: tuple(v) + (circle_polygon(Location(*k[0]), reach[k]),) if reach.get(k) else tuple(v)
                for k, v in at_joint.items()}
    # filled copper: each polygon on each layer a region. An end pad's regions are that end; any other region is
    # passed through and measured (`_crossing`).
    regions = []
    for fp in geometry.footprints:
        for i, pad in enumerate(fp.pads):
            if pad.net != net:
                continue
            for layer in pad.layers:
                for j, poly in enumerate(pad.outlines):
                    regions.append((("pad", fp.ref, fp.uuid, pad.number, i, layer.value, j), "pad", layer, poly,
                                    (fp.ref, pad.number, fp.uuid), (fp.ref, fp.uuid, i, j)))
    for i, copper in enumerate(geometry.copper):
        if copper.net == net and copper.kind in ("poly", "zone") and copper.filled:
            regions += [(("fill", i, layer.value, j), copper.kind, layer, poly, None, None)
                        for layer in copper.layers for j, poly in enumerate(copper.outlines)]
    boxes = {r[0]: Box.of_points(r[3]) for r in regions}
    curved = {id(t) for t in arcs}
    straight = [t for t in tracks if id(t) not in curved]
    # KiCad joins same-net copper wherever it overlaps (CN_VISITOR: the items' shapes collide), not only at track
    # ends: where two tracks overlap with no joint between them, each gets a joint at the closest points of their
    # centrelines, and the two are joined; where a track overlaps a region, it gets a joint at the point of its
    # centreline nearest the region, which the region joins
    extra, forced, bridges = {}, {}, []
    tbox = {id(t): Box.of_points(t.anchors).inflate(t.width_mm / 2) for t in straight}   # its centreline, grown
    straight.sort(key=lambda t: tbox[id(t)].left)  # swept by left edge: a pair is tried only where boxes meet
    for x, t in enumerate(straight):
        layer = next(iter(t.layers))
        for u in straight[x + 1:]:
            if tbox[id(u)].left > tbox[id(t)].right + 1e-6:
                break
            if next(iter(u.layers)) != layer or not tbox[id(t)].overlaps(tbox[id(u)], 1e-6):
                continue
            p, q, d = _closest_points(t.anchors, u.anchors)
            if d <= (t.width_mm + u.width_mm) / 2 + 1e-6:
                extra.setdefault(id(t), []).append(p)
                extra.setdefault(id(u), []).append(q)
                bridges.append(((pt(p), layer), (pt(q), layer), t, u))
        for r in regions:
            if r[2] != layer or not tbox[id(t)].overlaps(boxes[r[0]], 1e-6):
                continue
            p, d = _nearest_on_segment(t.anchors, r[3], t.width_mm / 2 + 1e-6)
            if p is not None and d <= t.width_mm / 2 + 1e-6:
                extra.setdefault(id(t), []).append(p)
                forced.setdefault(r[0], set()).add((pt(p), layer))
    for t in straight:
        layer = next(iter(t.layers))
        for p in extra.get(id(t), ()):
            k = (pt(p), layer)
            reach[k] = max(reach.get(k, 0.0), t.width_mm / 2)
            at_joint[k] = tuple(at_joint.get(k, ())) + tuple(t.outlines) + (circle_polygon(Location(*k[0]), t.width_mm / 2),)
    for t in arcs:
        layer = next(iter(t.layers))
        link((pt(t.anchors[0]), layer), (pt(t.anchors[1]), layer), t.length_mm, t)
    for t in tracks:                                # a track is split at every joint on it (a T, a via mid-track)
        if id(t) in curved:
            continue
        layer = next(iter(t.layers))
        (ax, ay), (bx, by) = t.anchors
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        stops = []
        for p in list(joints.get(layer, ())) + [pt(e) for e in extra.get(id(t), ())]:
            # on the track where the copper meeting there overlaps it: the joint within half the track's width
            # plus half its own copper's of the centreline; u is clamped, so a joint rounded just past the track's
            # end is that end
            u = min(max(((p[0] - ax) * dx + (p[1] - ay) * dy) / span, 0.0), 1.0) if span else 0.0
            if math.hypot(ax + u * dx - p[0], ay + u * dy - p[1]) <= t.width_mm / 2 + reach.get((p, layer), 0.0) + 1e-6:
                stops.append((u, p))
        stops.sort()
        for (u0, p0), (u1, p1) in zip(stops, stops[1:]):
            link((p0, layer), (p1, layer), (u1 - u0) * t.length_mm, t)
    for v in vias:
        layers = sorted(v.layers, key=lambda l: str(l.value))
        for a, b in zip(layers, layers[1:]):
            link((pt(v.anchors[0]), a), (pt(v.anchors[0]), b), 0.0, None)
    for a_, b_, _, _ in bridges:
        if a_ != b_:
            link(a_, b_, 0.0, None)

    def near(a, b, gap=1e-6):
        return not (a.right + gap < b.left or b.right + gap < a.left or a.bottom + gap < b.top or
                    b.bottom + gap < a.top)
    nodes = list(adj)
    edges_of = {}

    def joins(n, k, poly):
        """A joint joins a region inside it, or within half its copper's width of its edge: their copper overlaps."""
        if point_in_polygon(n[0], poly):
            return True
        if k not in edges_of:
            edges_of[k] = list(zip(poly, poly[1:] + poly[:1]))
        r = reach.get(n, 0.0) + 1e-6
        return any(point_segment_distance(n[0], a, b) <= r for a, b in edges_of[k])
    inside = {}
    for k, _, layer, poly, _, _ in regions:
        bx = boxes[k]
        inside[k] = [n for n in nodes if n[1] == layer and bx.left - reach.get(n, 0.0) <= n[0][0] <= bx.right +
                     reach.get(n, 0.0) and bx.top - reach.get(n, 0.0) <= n[0][1] <= bx.bottom + reach.get(n, 0.0)
                     and joins(n, k, poly)]
        inside[k] += sorted(forced.get(k, set()) - set(inside[k]), key=repr)
    touching = [(a[0], b[0]) for x, a in enumerate(regions) for b in regions[:x]
                if a[2] == b[2] and near(boxes[a[0]], boxes[b[0]]) and poly_distance(a[3], b[3]) <= 1e-6]
    layer_pairs = [(a[0], b[0]) for x, a in enumerate(regions) for b in regions[:x]
                   if a[5] is not None and a[5] == b[5] and a[2] != b[2]]      # a plated pad joins its layers
    cache[key] = {"adj": adj, "at_joint": at_joint, "reach": reach, "regions": regions, "inside": inside, "touching": touching,
                  "layer_pairs": layer_pairs, "own": {r[0]: (r[3],) for r in regions}}
    return cache[key]


def joining_spans(geometry, o, *, full_width=False, neck_mm=0.0, step=None, cache=None):
    """The shortest copper path joining an obligation's two end pads, as (piece, length) pieces from the "to" end: a
    piece is a track (a CopperItem, split where other copper meets it) or a FillStretch
    where the path passes through filled copper - a zone's filled polygons as KiCad filled them (the copper a
    fabricator gets), a filled drawn polygon, or a pad that is not one of the obligation's ends. Copper on one layer
    joins wherever it overlaps, as KiCad 10's connectivity joins it; vias join the layers they span. None when no
    such path joins the two ends.

    `full_width`: only copper at the obligation's width on its layer, apart from narrow tracks wholly within `neck_mm`
    of an end (the neck budget below); a fill or pad is passed only where a disc that wide travels through it.
    `step` is the fill raster's cell (None: `[check] zone_step`); `cache` keeps the rasters across the obligations
    of one board."""
    import heapq
    from ..checks import _Fill
    net = o["net"]
    widths = o.get("widths") or {}
    if step is None:
        from ..settings import active
        step = active().check_zone_step
    cache = {} if cache is None else cache
    fills = cache.setdefault(("fills", step), {})

    ends = {"A": o["from"], "B": o["to"]}

    def names(end, pad_end):                        # pad_end: (ref, pad number, footprint uuid)
        return (end.get("ref"), end.get("pad")) == pad_end[:2] and end.get("fp") in (None, pad_end[2])
    if not any(names(ends["A"], (fp.ref, p.number, fp.uuid)) and p.net == net for fp in geometry.footprints
               for p in fp.pads) or \
            not any(names(ends["B"], (fp.ref, p.number, fp.uuid)) and p.net == net for fp in geometry.footprints
                    for p in fp.pads):
        return None
    laid = _net_copper(geometry, net, cache)
    if laid is None:
        return None
    adj = {u: list(edges) for u, edges in laid["adj"].items()}

    def link(a, b, length, piece):
        adj.setdefault(a, []).append((b, length, piece))
        adj.setdefault(b, []).append((a, length, piece))

    at_joint, inside, own = laid["at_joint"], laid["inside"], laid["own"]
    regions = [(key, kind, layer, poly, next((t for t, e in ends.items() if names(e, end)), None) if end else None,
                ident) for key, kind, layer, poly, end, ident in laid["regions"]]
    by_key = {r[0]: r for r in regions}
    touching = [(by_key[a], by_key[b]) for a, b in laid["touching"]]
    layer_pairs = [(by_key[a], by_key[b]) for a, b in laid["layer_pairs"]]

    def fill_of(region):
        key = region[0]
        if key not in fills:
            fills[key] = _Fill(region[3], step)
        return fills[key]

    def need_of(region):
        return None if region[4] else widths.get(region[2].value)

    def hubs(region, polys):
        """The region's nodes `polys` reaches: the region itself, or with `full_width` each part of it that a disc of
        the width asked on its layer can travel through (none when that disc reaches no copper of `polys`)."""
        need = need_of(region)
        if not full_width or need is None:
            return [("r", region[0])]
        fill = fill_of(region)
        tau = fill.level(_fill_need(fill, need))
        memo = cache.setdefault(("hubs", step, region[0], tau), {})
        if id(polys) in memo:
            return memo[id(polys)]
        out = {("r", region[0], fill.part(c, tau)) for c in fill.touching(polys, tau)}
        memo[id(polys)] = sorted(out)               # polys are _net_copper's own tuples, kept by the cache
        return memo[id(polys)]

    def joint_hubs(region, n):
        """hubs for a joint: its copper taken as the disc of its half width there (laid["reach"])."""
        need = need_of(region)
        if not full_width or need is None:
            return [("r", region[0])]
        fill = fill_of(region)
        tau = fill.level(_fill_need(fill, need))
        memo = cache.setdefault(("joint hubs", step, region[0], tau), {})
        if n not in memo:
            memo[n] = sorted({("r", region[0], fill.part(c, tau))
                              for c in fill.touching_disc(n[0], laid["reach"].get(n, 0.0), tau)})
        return memo[n]

    for region in regions:
        key, _, _, poly, tag, _ = region
        if tag:
            for h in hubs(region, own[key]):
                link(tag, h, 0.0, None)
        for n in inside[key]:
            for h in joint_hubs(region, n):
                link(n, h, 0.0, None)
    for a, b in touching + layer_pairs:
        for ha in hubs(a, own[b[0]]):
            for hb in hubs(b, own[a[0]]):
                link(ha, hb, 0.0, None)
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
                    if d + length <= neck_mm and d + length < dist.get(v, math.inf):
                        seq += 1
                        dist[v] = d + length
                        heapq.heappush(heap, (d + length, seq, v))
            return dist
        ends_dist = [end_distances(tag) for tag in ("A", "B")]

        def allowed(u, v, length, track):
            if track is None:
                return True
            need = widths.get(next(iter(track.layers)).value, 0.0)
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
    walk, u = ["B"], "B"                            # the path's nodes from the "to" end, and the track into each
    into = []
    while u != "A":
        u, track = prev[u]
        walk.append(u)
        into.append(track)

    def cells_at(fill, node, tau):
        """The cells of `fill` at least `tau` deep that a node's copper reaches: a region's polygon, or a joint's disc."""
        if node[0] == "r":
            return fill.touching(own[node[1]], tau)
        return fill.touching_disc(node[0], laid["reach"].get(node, 0.0), tau)

    def copper_of(node):
        if node in ("A", "B"):
            return None
        if node[0] == "r":
            return own[node[1]]
        return at_joint.get(node)
    spans = []
    for k, node in enumerate(walk):
        if k and into[k - 1] is not None:
            spans.append((into[k - 1], dist[walk[k - 1]] - dist[node]))
        if node in ("A", "B") or node[0] != "r" or k in (0, len(walk) - 1):
            continue
        region = by_key[node[1]]
        before, after = copper_of(walk[k - 1]), copper_of(walk[k + 1])
        if region[4] or before is None or after is None:    # an end pad itself: the join starts or stops there
            continue
        if walk[k + 1][0] == "r" and walk[k + 1][1] == node[1] or walk[k - 1][0] == "r" and walk[k - 1][1] == node[1]:
            continue
        memo = cache.setdefault(("crossings", step), {})
        need = need_of(region)
        if full_width and need is not None:
            # the full-width search passed it at its width: its length at that width, with no width search
            mk = ("wide", region[0], walk[k - 1], walk[k + 1], need)
            if mk not in memo:
                fill = fill_of(region)
                tau = fill.level(_fill_need(fill, need))
                length = fill.path_length(cells_at(fill, walk[k - 1], tau), cells_at(fill, walk[k + 1], tau), tau)
                # no path at that width between the two (the search's parts and these cells disagree): measured as
                # any other crossing below, never taken as no length
                memo[mk] = None if length is None else [
                    (FillStretch(region[1], frozenset((region[2],)), need, None, fill.s), length)]
            if memo[mk] is not None:
                spans += memo[mk]
                continue
        mk = (region[0], id(before), id(after), need)               # before and after are _net_copper's own tuples
        if mk not in memo:
            memo[mk] = _crossing(fill_of(region), region[1], region[2], before, after, need)
        spans += memo[mk]
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
        narrow = layer is not None and t.width_mm < widths[layer] - max(_UNDER_MM, getattr(t, "tolerance_mm", 0.0))
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


def _ref_pad(end):
    """An end as the router's records name it: (ref, pad)."""
    return (end.get("ref"), end.get("pad")) if isinstance(end, dict) else None


def _task_key(o) -> tuple:
    return (o.get("net"), _ref_pad(o.get("from")), _ref_pad(o.get("to")))


def _fp_agrees(record_end, end) -> bool:
    """A record's end names the same footprint as the obligation's: it names none, or the same uuid."""
    fp = (record_end or {}).get("fp")
    return fp is None or fp == (end or {}).get("fp")


def records_of(obligations, connections) -> list:
    """The router's record of each obligation's task, in order (None for an obligation no record names: a whole-net
    call). A record is matched by net and each end's ref and pad, and by the footprint uuid ("fp") on an end where the
    record names one: route_calls gives each record its task's own ends (`answered`), so tasks on a shared reference
    are told apart whatever call or order they were sent in. Records nothing else tells apart are the answers to one
    task stated more than once, taken in order."""
    connections = list(connections)
    seen, out = {}, []
    for o in obligations:
        key = _task_key(o)
        fits = [r for r in connections if _task_key(r) == key and _fp_agrees(r.get("from"), o.get("from"))
                and _fp_agrees(r.get("to"), o.get("to"))]
        if any((r.get("from") or {}).get("fp") or (r.get("to") or {}).get("fp") for r in fits):
            fits = [r for r in fits if (r.get("from") or {}).get("fp") or (r.get("to") or {}).get("fp")]
            out.append(fits[0] if fits else None)
            continue
        i = seen.get(key, 0)
        seen[key] = i + 1
        out.append(fits[i] if i < len(fits) else (fits[0] if fits else None))
    return out


def open_entry(o, j, record, net_evidence) -> dict:
    """An obligation left open, with what the router said of it: its `record` (records_of; None for a whole-net call)
    gives `outcome` and `evidence`, or the net's `net_evidence` does; None when the router gave none. Router facts
    only: placemat infers no cause here (Task 6a)."""
    out = dict(o, outcome=record.get("status") if record else None,
               evidence=record.get("evidence") if record else (net_evidence or {}).get(o["net"]))
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
    records = records_of(obligations, connections)
    clean = [is_clean(j, r.get("status") if r else None) for j, r in zip(judged, records)]
    rec.update(asked=len(obligations), joined=sum(clean),
               closure_clean=round(sum(clean) / len(obligations), 4) if obligations else 1.0,
               open=[open_entry(o, j, r, net_evidence or {})
                     for o, j, r, ok in zip(obligations, judged, records, clean) if not ok])
    return rec


def open_connections(pcb_path, drc_json) -> list:
    """Each connection the DRC reports open (`unconnected_items`), named by its two ends' pads. KiCad gives each item's
    uuid; a pad end is that pad, a track, via or zone end is the first pad (by ref, pad) joined to it through copper
    (CONNECTIVITY_DATA.GetConnectedPads), and an end that is no pad and joins none is {"ref": None, "pad": None,
    "at": [x, y]} (mm, the DRC's position). A pad end of a footprint whose reference another footprint shares also
    names the footprint's uuid, {"ref", "pad", "fp"}. The net is the item's own, never read from the description. Ends
    are in (ref, pad) order."""
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

    refs = {}
    for fp in board.GetFootprints():
        refs[fp.GetReference()] = refs.get(fp.GetReference(), 0) + 1

    def key(pad):
        fp = pad.GetParentFootprint()
        return (fp.GetReference(), pad.GetNumber(), fp.m_Uuid.AsString())

    def named(k):
        """An end by its pad; with its footprint's uuid when another footprint has the same reference."""
        return {"ref": k[0], "pad": k[1], "fp": k[2]} if refs.get(k[0], 0) > 1 else {"ref": k[0], "pad": k[1]}

    def end(raw):
        pos = raw.get("pos") or {}
        loose = {"ref": None, "pad": None, "at": [pos.get("x", 0.0), pos.get("y", 0.0)]}
        it = items.get(raw.get("uuid", ""))
        if it is None:
            return "", loose
        if it.GetClass() == "PAD":
            return it.GetNetname(), named(key(it))
        joined = sorted(key(p) for p in cn.GetConnectedPads(it))
        return it.GetNetname(), (named(joined[0]) if joined else loose)

    out = []
    for u in raw_items:
        raw = u.get("items", [])
        if len(raw) < 2:
            continue
        (na, a), (nb, b) = end(raw[0]), end(raw[1])
        a, b = sorted((a, b), key=lambda e: (e["ref"] is None, e["ref"] or "", e["pad"] or "", e.get("fp") or ""))
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
                # the router echoes an end as {ref, pad}: an "fp" placemat gave is not compared
                if not isinstance(record, dict) or any(record.get(k) != asked[k] for k in ("net", "widths")) or \
                        any(_ref_pad(record.get(k)) != _ref_pad(asked[k]) for k in ("from", "to")):
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


def answered(pending, recs) -> list:
    """The router's records of one call, each naming the task it answers: the router writes one record per task it
    was sent, in order (connection_summary checks the count and each end's ref and pad), so an end of record i takes
    task i's footprint uuid ("fp") where that task's end has one; what the router said of each end is kept. A task
    stated twice, or tasks on a shared reference split across calls, keep their own records."""
    from .phase_select import end_record

    def end(said, task_end):
        fp = end_record(task_end).get("fp")
        return dict(said or {}, fp=fp) if fp else said
    return [dict(r, **{"from": end(r.get("from"), t.start), "to": end(r.get("to"), t.end)})
            for t, r in zip(pending, recs)]


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
    out = PhaseOutcome(board, {}, {})
    pairs, connections, bus_groups = None, [], []
    common = dict(iterations=ctx.iterations, probe=ctx.probe, quick=ctx.quick, clearances=ctx.clearances_file,
                  neckdown=phase.neckdown, extra_args=tuple(phase.router_args))
    what = "phase %s" % phase.name
    for k, call in enumerate(calls):
        stem = "p%d_%d" % (index, k)
        nxt = ctx.work / (stem + ".kicad_pcb")
        summary = ctx.work / (stem + "_summary.json")
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
                           tuple(phase.router_args))
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
                rc = _run(cmd, log, ctx)
                if rc != 0 or not part.exists():
                    _failed(rc, log, what)
                _copy_project(src, part)
                lock_copper(str(part))
                out.summaries.append((phase.name, k, psum))
                data = connection_summary(psum, pending, phase.name, log)
                recs = answered(pending, data.get("connections") or [])
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
            rc = _run(cmd, log, ctx)
            if rc != 0 or not nxt.exists():
                _failed(rc, log, what)
            _copy_project(board, nxt)
            out.summaries.append((phase.name, k, summary))
            if call.kind == "bus" and summary.exists():
                bus_groups += json.loads(summary.read_text()).get("bus_groups") or []
        lock_copper(str(nxt))
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
    tasks = {(t.net, tuple(t.start[:2]), tuple(t.end[:2])): t for t in sel.tasks}
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
    tasks = {(t.net, tuple(t.start[:2]), tuple(t.end[:2])): t for t in sel.tasks}
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
        for j, r in zip(got, records_of(obs, rec.get("connections") or [])):
            if j["joined"] and (j["under"] or j.get("width_unknown", False) or (r or {}).get("status") == "joined_narrow"):
                n += 1
    return n
