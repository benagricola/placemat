"""Design checks on a generated board.

The capture writes what each part is as `Pm.*` footprint fields (the
placemat-design skill lists them): the loop a part closes, whether its
copper is an aggressor, the net it senses, the current through it, its
dissipation and junction limit. This module reads those facts off the
board with its copper and reports, per check, a number, the limit it is
judged against and a verdict. A check whose fact is missing says so
instead of guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .board_geometry import BoardGeometry, CopperItem, Footprint
from .geometry import poly_distance, polys_overlap
from .values import Box

AMBIENT_C = 100.0
"""Board temperature the junction estimate starts from: a sealed driver
case at full load; a board states its own when it knows better.
The default for `[check] ambient_c` and `--ambient`."""

KEEP_OUT_MM = 2.0
"""How far sense copper stays from a switch node: a bare clearance still
couples the edge field, two millimetres is the datasheet "keep FB away
from SW" with room for the pour clearance.
The default for `[check] keep_out_mm` and `--keep-out`."""

TRACK_RISE_C = 10.0
"""Temperature rise a current path is sized for, on top of the board's
ambient: the IPC-2221 curve the fab tables quote.
The default for `[check] rise_c` and `--rise`."""

COPPER_OZ = 1.0
"""Outer copper weight the width is sized for, until the board's stackup
is read. The default for `[check] copper_oz` and `--copper-oz`."""

_IPC_K_OUTER = 0.048            # IPC-2221 external layer constant
_MIL_PER_OZ = 1.378             # copper thickness per ounce, in mil
_MM_PER_MIL = 0.0254

_PREFIX = {"": 1.0, "m": 1e-3, "u": 1e-6, "k": 1e3}


@dataclass(frozen=True)
class Facts:
    ref: str
    role: str | None = None
    loop: str | None = None
    aggressor: bool = False
    sensitive: str | None = None        # the net the part senses, by name
    current_a: float | None = None      # `Pm.I: 3A`, through every pad of the part
    currents: dict | None = None        # `Pm.I: vin:3A fb:1mA`, per net (lower-cased names)
    dissipation_w: float | None = None
    tj_max_c: float | None = None
    theta_ja_c_per_w: float | None = None       # junction to ambient, the datasheet's JEDEC-board figure
    theta_jb_c_per_w: float | None = None       # junction to board: the figure a board temperature wants


@dataclass(frozen=True)
class Loop:
    name: str
    parts: tuple[str, ...]
    nets: tuple[str, ...]               # the nets two or more of its parts share
    area_mm2: float                     # the hull of their pads on those nets
    longest_leg_mm: float               # the longest pad-to-pad reach on one shared net


@dataclass(frozen=True)
class SwitchNode:
    net: str
    parts: tuple[str, ...]
    area_mm2: float                     # every pad, track and pour on the net
    extent_mm: float                    # the longer side of its bounding box


@dataclass(frozen=True)
class Verdict:
    check: str
    subject: str
    value: float
    unit: str
    limit: float | None = None
    ok: bool | None = None              # None: not judged (no limit, or a fact is missing)
    note: str = ""

    def line(self) -> str:
        judged = "" if self.ok is None else (" ok" if self.ok else " FAIL")
        lim = "" if self.limit is None else " (limit %g)" % self.limit
        note = " - " + self.note if self.note else ""
        return "%-15s %-12s %8.3g %s%s%s%s" % (self.check, self.subject, self.value, self.unit, lim, judged, note)


# ----------------------------------------------------------------- facts

def _quantity(text: str) -> float:
    """`3A`, `250mA`, `0.6W`, `125C`, `80C/W` as a number in base units."""
    m = re.fullmatch(r"\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([mukMK]?)\s*[A-Za-z/]*\s*", text)
    if not m:
        raise ValueError("not a quantity: %r" % text)
    prefix = m.group(2)
    if prefix in ("M", "K"):
        prefix = prefix.lower() if prefix == "K" else "M"
    scale = _PREFIX.get(prefix, None)
    if scale is None:
        raise ValueError("unit prefix %r in %r" % (prefix, text))
    return float(m.group(1)) * scale


def _facts_of(fp: Footprint) -> Facts:
    low = {k.lower(): v for k, v in fp.fields.items() if k.lower().startswith("pm.")}

    def get(key):
        v = low.get("pm." + key)
        return v.strip() if v is not None and v.strip() else None

    def number(key):
        v = get(key)
        return _quantity(v) if v is not None else None

    current_a, currents = None, None
    if get("i") is not None:
        if ":" in get("i"):
            currents = {}
            for item in re.split(r"[\s,]+", get("i").strip()):
                net, _, amps = item.partition(":")
                currents[net.lower()] = _quantity(amps)
        else:
            current_a = _quantity(get("i"))
    return Facts(ref=fp.ref, role=get("role"), loop=get("loop"),
                 aggressor=(get("aggressor") or "").lower() in ("true", "yes", "1"),
                 sensitive=get("sensitive"), current_a=current_a, currents=currents, dissipation_w=number("pd"),
                 tj_max_c=number("tjmax"), theta_ja_c_per_w=number("thetaja"), theta_jb_c_per_w=number("thetajb"))


def facts(geometry: BoardGeometry) -> dict[str, Facts]:
    return {fp.ref: _facts_of(fp) for fp in geometry.footprints}


# -------------------------------------------------------------- geometry

def _area(poly) -> float:
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2.0


def _hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def neck_mm(poly) -> float:
    """A polygon's narrowest section: from points along each edge, the
    distance across the interior along the edge's inward normal to the
    boundary opposite. A rectangle's neck is its short side; a rounded
    corner, whose short edges sit close together, does not read as one."""
    n = len(poly)
    signed = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    inward = 1.0 if signed > 0 else -1.0             # left of the edge when the ring is counter-clockwise
    best = math.inf
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        length = math.hypot(ex, ey)
        if length < 1e-9:
            continue
        nx, ny = -ey / length * inward, ex / length * inward
        for f in (0.25, 0.5, 0.75):
            mx, my = a[0] + ex * f, a[1] + ey * f
            for j in range(n):
                if j == i:
                    continue
                t = _ray_hits(mx, my, nx, ny, poly[j], poly[(j + 1) % n])
                if t is not None and t > 1e-6:
                    best = min(best, t)
    return best


def _ray_hits(px, py, dx, dy, c, d):
    """Distance along the ray (px, py) + t (dx, dy) to segment c-d, or None."""
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = dx * sy - dy * sx
    if abs(den) < 1e-12:
        return None
    qx, qy = c[0] - px, c[1] - py
    t = (qx * sy - qy * sx) / den
    u = (qx * dy - qy * dx) / den
    return t if t >= 0 and -1e-9 <= u <= 1 + 1e-9 else None


def _copper_on(geometry: BoardGeometry, net: str, kinds=("pad", "track", "via", "poly")) -> list[CopperItem]:
    return [c for c in geometry.copper if c.net == net and c.kind in kinds]



# ------------------------------------------------------------- hot loops

def hot_loops(geometry: BoardGeometry) -> list[Loop]:
    f = facts(geometry)
    by_loop: dict[str, list[Footprint]] = {}
    for fp in geometry.footprints:
        if f[fp.ref].loop:
            by_loop.setdefault(f[fp.ref].loop, []).append(fp)
    loops = []
    for name, parts in sorted(by_loop.items()):
        owners: dict[str, set[str]] = {}
        for fp in parts:
            for p in fp.pads:
                owners.setdefault(p.net, set()).add(fp.ref)
        shared = sorted(n for n, refs in owners.items() if len(refs) >= 2)
        points = [(p.location.x, p.location.y) for fp in parts for p in fp.pads if p.net in shared]
        longest = 0.0
        for net in shared:
            pads = [p for fp in parts for p in fp.pads if p.net == net]
            for a in pads:
                for b in pads:
                    if a.owner != b.owner:
                        longest = max(longest, a.location.distance(b.location))
        hull = _hull(points)
        loops.append(Loop(name, tuple(fp.ref for fp in parts), tuple(shared),
                          _area(hull) if len(hull) >= 3 else 0.0, longest))
    return loops


# ---------------------------------------------------------- switch nodes

def switch_nodes(geometry: BoardGeometry) -> list[SwitchNode]:
    f = facts(geometry)
    owners: dict[str, set[str]] = {}
    for fp in geometry.footprints:
        for p in fp.pads:
            owners.setdefault(p.net, set()).add(fp.ref)
    nodes = []
    for net, refs in sorted(owners.items()):
        if len(refs) >= 2 and all(f[r].aggressor for r in refs):
            items = _copper_on(geometry, net)
            area = sum(_area(o) for c in items for o in c.outlines)
            box = Box.union([c.box for c in items]) if items else None
            extent = max(box.width, box.height) if box else 0.0
            nodes.append(SwitchNode(net, tuple(sorted(refs)), area, extent))
    return nodes


# -------------------------------------------------------- sensitive nets

def _sensitive_nets(geometry: BoardGeometry) -> dict[str, str]:
    """net -> how it was found. `Pm.Sensitive` names the net; when no pad
    of the part carries that name, the part's least-connected net is taken
    (the local node, not the rail) and the verdict says so."""
    f = facts(geometry)
    owners: dict[str, set[str]] = {}
    for fp in geometry.footprints:
        for p in fp.pads:
            owners.setdefault(p.net, set()).add(fp.ref)
    out = {}
    for fp in geometry.footprints:
        want = f[fp.ref].sensitive
        if not want:
            continue
        nets = {p.net for p in fp.pads}
        match = [n for n in nets if n.lower() == want.lower()]
        how = "sensed by %s" % fp.ref
        if not match:
            match = sorted(nets, key=lambda n: (len(owners[n]), n))[:1]
            how = "no pad of %s is on a net called %s; took its least-connected net" % (fp.ref, want)
        if match:
            out[match[0]] = how
    return out


@dataclass(frozen=True)
class _NamedCopper:
    """One piece of copper as a keep-out candidate: a pad by its part and
    number, a track or via by its net and ends (`_copper_on`'s items, with a
    pad's number recovered from its footprint, since `CopperItem` does not
    carry one)."""
    kind: str
    owner: str | None
    net: str
    outlines: tuple
    number: str | None = None
    anchors: tuple = ()


def _keep_out_copper(geometry: BoardGeometry, net: str) -> list[_NamedCopper]:
    out = [_NamedCopper("pad", fp.ref, net, p.outlines, number=p.number)
           for fp in geometry.footprints for p in fp.pads if p.net == net]
    out += [_NamedCopper(c.kind, c.owner, net, c.outlines, anchors=c.anchors)
            for c in _copper_on(geometry, net, kinds=("track", "via", "poly"))]
    return out


def _closest_on_segment(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return a
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return (ax + t * dx, ay + t * dy)


def _nearest_points(a, b) -> tuple:
    """The point of polygon `a` nearest `b`, the point of `b` nearest `a`,
    and the gap between them - the pair of points `poly_distance` measures,
    recovered by the same walk (every vertex of one against every edge of
    the other), since `poly_distance` gives only the distance."""
    best = (math.inf, a[0], b[0])
    for p in a:
        for i in range(len(b)):
            n = _closest_on_segment(p, b[i], b[(i + 1) % len(b)])
            d = math.hypot(p[0] - n[0], p[1] - n[1])
            if d < best[0]:
                best = (d, p, n)
    for p in b:
        for i in range(len(a)):
            n = _closest_on_segment(p, a[i], a[(i + 1) % len(a)])
            d = math.hypot(p[0] - n[0], p[1] - n[1])
            if d < best[0]:
                best = (d, n, p)
    return best[1], best[2], best[0]


def _keep_out_text(item: _NamedCopper, point: tuple) -> str:
    if item.kind == "pad":
        return "%s pad %s (%s) at (%.2f, %.2f)" % (item.owner, item.number, item.net, point[0], point[1])
    if item.kind == "track" and len(item.anchors) >= 2:
        return "track %s (%.2f, %.2f)-(%.2f, %.2f)" % (
            item.net, item.anchors[0][0], item.anchors[0][1], item.anchors[-1][0], item.anchors[-1][1])
    if item.kind == "via" and item.anchors:
        return "via %s at (%.2f, %.2f)" % (item.net, item.anchors[0][0], item.anchors[0][1])
    return "%s %s at (%.2f, %.2f)" % (item.kind, item.net, point[0], point[1])


def keep_out(geometry: BoardGeometry, limit_mm: float = KEEP_OUT_MM) -> list[Verdict]:
    sensitive = _sensitive_nets(geometry)
    out = []
    for node in switch_nodes(geometry):
        node_items = _keep_out_copper(geometry, node.net)
        sense_items = [c for net in sensitive for c in _keep_out_copper(geometry, net)]
        if not node_items or not sense_items:
            continue
        # a part's own pins are package, not layout: judged apart, and said when nearer
        best, own = None, None
        for a in node_items:
            for b in sense_items:
                same = a.kind == "pad" and b.kind == "pad" and a.owner == b.owner
                for oa in a.outlines:
                    for ob in b.outlines:
                        d = poly_distance(oa, ob)
                        if same:
                            if own is None or d < own[0]:
                                own = (d, a)
                        elif best is None or d < best[0]:
                            best = (d, a, b, oa, ob)
        if best is None:
            continue
        d, a, b, oa, ob = best
        pa, pb, _ = _nearest_points(oa, ob)
        note = "%s to %s" % (_keep_out_text(a, pa), _keep_out_text(b, pb))
        if own is not None and own[0] < d:
            note += "; %s's own pads are %.2f mm apart, a distance its footprint sets" % (own[1].owner, own[0])
        out.append(Verdict("keep-out", node.net, d, "mm", limit_mm, d >= limit_mm, note))
    return out


def crossings_under(geometry: BoardGeometry) -> list[Verdict]:
    out = []
    for net, how in sorted(_sensitive_nets(geometry).items()):
        tracks = [c for c in geometry.copper if c.net == net and c.kind == "track"]
        count = 0
        for t in tracks:
            for c in geometry.copper:
                if c.net == net or c.kind in ("zone", "via") or c.layers & t.layers:
                    continue
                if t.box.overlaps(c.box) and any(polys_overlap(a, b) for a in t.outlines for b in c.outlines):
                    count += 1
        out.append(Verdict("crossings-under", net, count, "crossings", 0, count == 0,
                           "other nets' copper on the other face under %s's tracks (%s)" % (net, how)))
    return out


# --------------------------------------------------------- current paths

def ipc2221_width_mm(current_a: float, rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ) -> float:
    """IPC-2221 external-layer width for a current at a temperature rise."""
    area_milsq = (current_a / (_IPC_K_OUTER * rise_c ** 0.44)) ** (1 / 0.725)
    return area_milsq / (_MIL_PER_OZ * copper_oz) * _MM_PER_MIL


def _net_graph(geometry: BoardGeometry, net: str):
    """A net's copper as a graph: (nodes, neighbours). A node is (label, the
    width current can pass through it, polygons, box, layers, its ends): a
    pad or via passes any, a track its width, a drawn pour or a zone's fill
    its narrowest neck. `ends` is a track's two endpoints, for the neck a
    current-path verdict names; other kinds carry none. Two nodes touch
    when their copper does on a layer they share."""
    nodes = []
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.net == net and p.outlines:
                nodes.append(("%s.%s" % (fp.ref, p.number), math.inf, p.outlines, p.box, p.layers, ()))
    for c in geometry.copper:
        if c.net != net or not c.outlines:
            continue
        if c.kind == "zone":
            # a fill passes any width here: as KiCad stores it each hole is slit to the outline, and its
            # narrowest neck is a slit, or a thermal spoke to another part - not what the load passes through
            for o in c.outlines:
                nodes.append(("zone", math.inf, (o,), Box.of_points(o), c.layers, ()))
            continue
        if c.kind not in ("track", "via", "poly"):
            continue
        cap = c.width_mm if c.kind == "track" else (min(neck_mm(o) for o in c.outlines) if c.kind == "poly" else math.inf)
        ends = c.anchors if c.kind == "track" and len(c.anchors) >= 2 else ()
        nodes.append((c.kind, cap, c.outlines, c.box, c.layers, ends))
    near = {i: [] for i in range(len(nodes))}
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            if a[4] & b[4] and a[3].overlaps(b[3], gap=1e-6) and \
                    any(polys_overlap(x, y) or poly_distance(x, y) <= 1e-6 for x in a[2] for y in b[2]):
                near[i].append(j)
                near[j].append(i)
    return nodes, near


def _widest_from(nodes, near, sources) -> dict:
    """{node: (the widest bottleneck of any route to it from `sources`, the
    source it set out from, whether it passed through a zone fill, the node
    before it on that route)}: the route current would take, judged by its
    narrowest point. The parent lets `_neck` retrace the route to find where
    its bottleneck lies."""
    import heapq
    best = {i: (nodes[i][1], i, nodes[i][0] == "zone", None) for i in sources}
    heap = [(-best[i][0], i) for i in sources]
    heapq.heapify(heap)
    while heap:
        w, i = heapq.heappop(heap)
        w = -w
        if w < best[i][0]:
            continue
        for j in near[i]:
            cand = min(w, nodes[j][1])
            if cand > best.get(j, (-1.0,))[0]:
                best[j] = (cand, best[i][1], best[i][2] or nodes[j][0] == "zone", i)
                heapq.heappush(heap, (-cand, j))
    return best


def _neck(nodes, best, end_i: int, w: float) -> tuple:
    """The bottleneck's point and how far the route stays within 10% of it:
    the run of consecutive track nodes around the bottleneck this narrow,
    stopped each way by a pad, via, pour or wider track."""
    path, i = [], end_i
    while i is not None:
        path.append(i)
        i = best[i][3]
    path.reverse()                                       # source -> target
    pos = next(k for k, idx in enumerate(path) if abs(nodes[idx][1] - w) < 1e-6)
    neck_i = path[pos]

    def length(idx):
        ends = nodes[idx][5]
        return math.hypot(ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]) if ends else 0.0

    def narrow(idx):
        return nodes[idx][0] == "track" and nodes[idx][1] <= w * 1.1 + 1e-9
    total = length(neck_i)
    k = pos - 1
    while k >= 0 and narrow(path[k]):
        total += length(path[k])
        k -= 1
    k = pos + 1
    while k < len(path) and narrow(path[k]):
        total += length(path[k])
        k += 1
    ends = nodes[neck_i][5]
    point = ((ends[0][0] + ends[1][0]) / 2.0, (ends[0][1] + ends[1][1]) / 2.0) if ends \
        else (nodes[neck_i][3].center.x, nodes[neck_i][3].center.y)
    return point, total


def _pairs(geometry: BoardGeometry, net: str, carriers: dict, rise_c: float, copper_oz: float):
    """The routes the load takes on `net`, carriers being {ref: amps}: for
    each two carriers, the widest route from any pad of one to any pad of the
    other, at the lesser current - what can flow between them; with one
    carrier, its widest route to any other part's pad at its own current.
    Returns (judged: [(width, need, amps, from, to, through a zone, the
    neck's point, how far the route stays that narrow)], unmeasured: [(from,
    to, why)] - a route through a zone fill or pads and vias alone, which
    has no copper width to judge - and apart: the pairs no copper joins
    yet)."""
    nodes, near = _net_graph(geometry, net)
    owner = {i: n[0].split(".")[0] for i, n in enumerate(nodes) if n[0] != "zone" and "." in n[0]
             and math.isinf(n[1])}
    pads = {ref: [i for i, o in owner.items() if o == ref] for ref in set(owner.values())}
    refs = sorted(carriers)
    pairs = [(a, b) for k, a in enumerate(refs) for b in refs[k + 1:]] if len(refs) > 1 else \
        [(refs[0], None)]
    searched = {}
    judged, unmeasured, apart = [], [], []
    for a, b in pairs:
        if not pads.get(a):
            apart.append((a, b))
            continue
        if a not in searched:               # one search a carrier, whoever it is paired with
            searched[a] = _widest_from(nodes, near, pads[a])
        best = searched[a]
        ends = pads.get(b, ()) if b is not None else [i for r, ii in pads.items() if r != a for i in ii]
        reach = [(best[i][0], nodes[i][0], nodes[best[i][1]][0], best[i][2], i) for i in ends if i in best]
        if not reach:
            apart.append((a, b))
            continue
        w, to, start, zoned, end_i = max(reach, key=lambda r: r[0])       # the other end's widest-joined pad
        if math.isinf(w):
            unmeasured.append((start, to, "through a zone fill, whose width is not measured" if zoned
                               else "joined only through pads and vias"))
            continue
        amps = carriers[a] if b is None else min(carriers[a], carriers[b])
        point, length = _neck(nodes, best, end_i, w)
        judged.append((w, ipc2221_width_mm(amps, rise_c, copper_oz), amps, start, to, zoned, point, length))
    return judged, unmeasured, apart


def current_paths(geometry: BoardGeometry, rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ) -> list[Verdict]:
    f = facts(geometry)
    carriers: dict[str, dict] = {}
    for fp in geometry.footprints:
        fact = f[fp.ref]
        for p in fp.pads:
            amps = fact.current_a if fact.currents is None else fact.currents.get(p.net.lower())
            if amps is not None and amps > 0:          # a net given no current, or 0, is not one it carries
                on = carriers.setdefault(p.net, {})
                on[fp.ref] = max(on.get(fp.ref, 0.0), amps)
    out = []
    for net, on in sorted(carriers.items()):
        judged, unmeasured, apart = _pairs(geometry, net, on, rise_c, copper_oz)
        said = ["no copper joins %s %s on %s yet" % (a, "and %s" % b if b else "to another part", net)
                for a, b in apart]
        said += ["%s to %s: %s" % (a, b, why) for a, b, why in unmeasured]
        if not judged:
            amps = max(on.values())
            out.append(Verdict("current-path", net, 0.0, "mm", ipc2221_width_mm(amps, rise_c, copper_oz), None,
                               "not judged (%g A): %s" % (amps, "; ".join(said))))
            continue
        w, need, amps, a, b, zoned, point, length = min(judged, key=lambda j: j[0] / j[1])
        note = "narrowest point of the load's widest route, %s to %s, for %g A at %g C rise on %g oz" % (
            a, b, amps, rise_c, copper_oz)
        if zoned:
            note += " (through a zone fill, whose width is not measured)"
        else:
            note += "; neck at (%.2f, %.2f), %.2f mm long" % (point[0], point[1], length)
        out.append(Verdict("current-path", net, w, "mm", need, w >= need, note + ("; " + "; ".join(said) if said else "")))
    return out


# ------------------------------------------------------------------ heat

def heat(geometry: BoardGeometry, ambient_c: float = AMBIENT_C) -> list[Verdict]:
    out = []
    for fp in geometry.footprints:
        fact = _facts_of(fp)
        if fact.dissipation_w is None:
            continue
        if fact.theta_jb_c_per_w is not None:
            theta, how = fact.theta_jb_c_per_w, "junction-to-board from a %g C board" % ambient_c
        elif fact.theta_ja_c_per_w is not None:
            theta, how = fact.theta_ja_c_per_w, "junction-to-ambient (the JEDEC board figure, pessimistic on a real board) from %g C" % ambient_c
        else:
            out.append(Verdict("heat", fp.ref, fact.dissipation_w, "W", fact.tj_max_c, None,
                               "no Pm.ThetaJb or Pm.ThetaJa on the part: junction rise not estimated"))
            continue
        tj = ambient_c + fact.dissipation_w * theta
        note = "%g W at %g C/W, %s" % (fact.dissipation_w, theta, how)
        if fact.tj_max_c is None:
            out.append(Verdict("heat", fp.ref, tj, "C", None, None, note + "; no Pm.TjMax to judge against"))
        else:
            out.append(Verdict("heat", fp.ref, tj, "C", fact.tj_max_c, tj <= fact.tj_max_c, note))
    return out


# ------------------------------------------------------------------- all

def run_checks(geometry: BoardGeometry, ambient_c: float = AMBIENT_C, keep_out_mm: float = KEEP_OUT_MM,
               rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ,
               limits: dict[str, float] | None = None) -> list[Verdict]:
    """Every check the board's facts allow. `limits` may name a bound for
    `hot-loop` (mm2) and `switch-node` (mm2); without one they report."""
    limits = limits or {}
    out = []
    for loop in hot_loops(geometry):
        lim = limits.get("hot-loop")
        out.append(Verdict("hot-loop", loop.name, loop.area_mm2, "mm2", lim,
                           None if lim is None else loop.area_mm2 <= lim,
                           "longest leg %.2f mm on %s across %s" % (
                               loop.longest_leg_mm, ", ".join(loop.nets) or "no shared net", ", ".join(loop.parts))))
    for node in switch_nodes(geometry):
        lim = limits.get("switch-node")
        out.append(Verdict("switch-node", node.net, node.area_mm2, "mm2", lim,
                           None if lim is None else node.area_mm2 <= lim,
                           "extent %.2f mm, owned by %s" % (node.extent_mm, ", ".join(node.parts))))
    out += keep_out(geometry, keep_out_mm)
    out += crossings_under(geometry)
    out += current_paths(geometry, rise_c, copper_oz)
    out += heat(geometry, ambient_c)
    return out


def kwargs_from(settings) -> dict:
    """The arguments `run_checks` takes, from the resolved settings. One home,
    so `placemat check` and `placemat run` judge a board by the same numbers."""
    return {"ambient_c": settings.check_ambient_c, "keep_out_mm": settings.check_keep_out_mm,
            "rise_c": settings.check_rise_c, "copper_oz": settings.check_copper_oz,
            "limits": dict(settings.check_limits)}


def record(rec, verdicts) -> list:
    """Put a board's verdicts on its run record and return the lines to print.

    A verdict with `ok` None was not judged - no limit was set, or a fact the
    check needs is missing - and it is counted as such rather than as a pass:
    a check that passes because a footprint lacks `Pm.Pd` is worse than none."""
    rec.verdicts = [dict(v.__dict__) for v in verdicts]
    failed = [v for v in verdicts if v.ok is False]
    unjudged = [v for v in verdicts if v.ok is None]
    rec.metrics["checks_failed"] = len(failed)
    rec.metrics["checks_unjudged"] = len(unjudged)
    if not verdicts:
        return ["no Pm.* facts on this board: no design checks ran"]
    head = "%d check(s): %d failed, %d passed, %d not judged" % (
        len(verdicts), len(failed), len(verdicts) - len(failed) - len(unjudged), len(unjudged))
    return [head] + [v.line() for v in failed]
