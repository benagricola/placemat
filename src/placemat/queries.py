"""What is at a point, what is in a box, and where a via may stand.

Pure: a board is a `BoardGeometry`, whichever way it was read. A via joins
every copper layer at one point, so it is judged against every layer; a zone
fill of another net is not an obstacle, because KiCad refills a zone and pulls
it back round a new via, and is reported as giving way instead."""
from __future__ import annotations

import bisect
from collections import Counter, deque
from dataclasses import dataclass
import heapq
import math
import re

from .geometry import (circle_polygon, gap_texts, via_ring, distance_to_boundary, point_in_polygon, point_segment_distance,
                       poly_distance, polys_overlap)
from .copper import _segment_polygon
from .values import Box, Location

_HARD = ("pad", "track", "via", "poly")


@dataclass(frozen=True)
class ViaVerdict:
    hard: tuple = ()        # what stops a via standing here
    soft: tuple = ()        # what would give way to it: another net's pour

    @property
    def clear(self) -> bool:
        return not self.hard


def _holes(geometry):
    """Every drilled hole on the board as (centre, diameter, what)."""
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.through and p.drill_mm:
                yield p.box.center, p.drill_mm, "%s pad %s" % (fp.ref, p.number)
        for at, dia in fp.npth:
            yield at, dia, "%s hole" % fp.ref
    for c in geometry.copper:
        if c.kind == "via" and c.drill_mm:
            yield c.box.center, c.drill_mm, "via %s" % c.net


def _edge_rings(geometry):
    return tuple(geometry.board_polygon) or tuple(geometry.outline)


def judge_via(geometry, at: Location, net: str, size: float, drill: float) -> ViaVerdict:
    poly = via_ring(at, size)
    box = Box(at.x - size / 2.0, at.y - size / 2.0, at.x + size / 2.0, at.y + size / 2.0)
    hard, soft = [], []
    rings = _edge_rings(geometry)
    if rings and not point_in_polygon((at.x, at.y), rings[0]):
        hard.append("off the board")
    elif rings:
        gap = min(distance_to_boundary(poly, r) for r in rings)
        if gap < geometry.edge_clearance - 1e-9:
            hard.append("%s mm from the board edge (needs %s)" % gap_texts(gap, geometry.edge_clearance))
    for c in geometry.copper:
        if c.net == net or not c.outlines:
            continue
        reach = geometry.clearance(net, c.net) if (net in geometry.nets and c.net in geometry.nets) \
            else geometry.default_clearance
        if not box.overlaps(c.box, gap=reach):
            continue
        gap = min(poly_distance(poly, o) for o in c.outlines)
        if gap >= reach - 1e-9:
            continue
        where = "/".join(sorted(l.value for l in c.layers))
        if c.kind == "zone":
            soft.append("the %s pour on %s would give way" % (c.net, where))
        elif c.kind in _HARD:
            got, want = gap_texts(gap, reach)
            hard.append("%s mm from %s %s on %s (needs %s)" % (got, c.net or "-", c.kind, where, want))
    for fp in geometry.footprints:                   # a footprint's own copper graphics: copper of no net
        for layer, art in fp.copper:
            if not box.overlaps(Box.of_points(art), gap=geometry.default_clearance):
                continue
            gap = poly_distance(poly, art)
            if gap < geometry.default_clearance - 1e-9:
                got, want = gap_texts(gap, geometry.default_clearance)
                hard.append("%s mm from %s's own copper on %s (needs %s)" % (got, fp.ref, layer.value, want))
    for centre, dia, what in _holes(geometry):
        gap = at.distance(centre) - (drill + dia) / 2.0
        if gap < geometry.hole_to_hole - 1e-9:
            got, want = gap_texts(gap, geometry.hole_to_hole)
            hard.append("hole %s mm from the %s hole (needs %s)" % (got, what, want))
    for fp in geometry.footprints:                   # an unplated hole has no copper: the via's copper keeps off its edge
        for centre, dia in fp.npth:
            edge = at.distance(centre) - (size + dia) / 2.0
            if edge < geometry.hole_clearance - 1e-9:
                got, want = gap_texts(edge, geometry.hole_clearance)
                hard.append("copper %s mm from %s's unplated hole (needs %s)" % (got, fp.ref, want))
    for ra in geometry.rule_areas:
        if "vias" in ra.excludes and ra.layers and net not in ra.allow and polys_overlap(poly, ra.polygon):
            hard.append("inside %s, which forbids vias" % ra.base)
    return ViaVerdict(tuple(hard), tuple(dict.fromkeys(soft)))


def _segment(a: Location, b: Location, width: float):
    """A straight track as a polygon, as the drawn track claims it: a
    rectangle along the segment, reaching half the width past each end over
    KiCad's round caps."""
    return _segment_polygon(a, b, width)


def _narrow_side(poly) -> float:
    """A convex outline's least width: its extent across each edge's normal,
    the least of them. A pad at an angle is as narrow as it is square on."""
    best = math.inf
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        n = math.hypot(x1 - x0, y1 - y0)
        if n < 1e-12:
            continue
        nx, ny = -(y1 - y0) / n, (x1 - x0) / n
        d = [x * nx + y * ny for x, y in poly]
        best = min(best, max(d) - min(d))
    return best


def tail_width(width: float, pad_outlines) -> float:
    """The width of a via's tail: its class's track width, necked down to
    the narrower side of its pad, as a hand-drawn tail from a small pad on a
    wide power class is; a tail wider than its pad reaches its neighbours."""
    return min([width] + [_narrow_side(tuple(o)) for o in pad_outlines])


def judge_tail(geometry, start: Location, end: Location, net: str, width: float, layer) -> tuple:
    """What a straight track from the pad to the via would touch on its layer.
    The source pad needs no exemption: it is the via's own net. Exempting its
    whole part let a tail run over the pin beside it on another net."""
    poly = _segment(start, end, width)
    box = Box.of_points(poly)
    out = []
    for c in geometry.copper:
        if c.net == net or layer not in c.layers or c.kind not in _HARD:
            continue
        reach = geometry.clearance(net, c.net) if (net in geometry.nets and c.net in geometry.nets) \
            else geometry.default_clearance
        if not box.overlaps(c.box, gap=reach):
            continue
        gap = min(poly_distance(poly, o) for o in c.outlines)
        if gap < reach - 1e-9:
            got, want = gap_texts(gap, reach)
            out.append("tail %s mm from %s %s on %s (needs %s)" % (got, c.net or "-", c.kind, layer.value, want))
    return tuple(out)


@dataclass(frozen=True)
class Spot:
    at: Location
    distance: float
    soft: tuple = ()


_COPPER_REASON = re.compile(r"mm from \S+ (pad|track|via|poly) on ")


def _kind(reason: str) -> str:
    """A reason's tally bucket, read from its shape. Matching the first word
    that looks like a kind put a track of a net called /mcu/edge_led under
    "edge"."""
    if reason.startswith("tail "):
        return "tail"
    if reason.startswith("hole "):
        return "hole"
    if reason.startswith("off the board") or " from the board edge" in reason:
        return "edge"
    if reason.startswith("inside ") and "forbids" in reason:
        return "keepout"
    if reason == "in the source pad":
        return "pad"
    m = _COPPER_REASON.search(reason)
    return m.group(1) if m else reason.split()[0]


def free_spot(start: Location, judge, radius: float = 2.0, step: float = 0.05) -> tuple:
    """The nearest candidate the judge passes, walking rings outward from
    `start`: radius first, then angle from east, anticlockwise, so the same
    board always gives the same spot. Returns (spot, tally, tried)."""
    tally, tried = Counter(), 0
    rings = int(round(radius / step))
    for i in range(0, rings + 1):
        r = i * step
        count = 1 if r == 0 else max(8, int(math.ceil(2 * math.pi * r / step)))
        for k in range(count):
            a = 2 * math.pi * k / count
            c = Location(round(start.x + r * math.cos(a), 4), round(start.y - r * math.sin(a), 4))
            tried += 1
            why, soft = judge(c)
            if why is None:
                return Spot(c, round(r, 4), tuple(soft)), tally, tried
            tally[_kind(why)] += 1
    return None, tally, tried


def pad_copper(fp, number: str) -> tuple:
    """Every outline of the part's pads numbered `number`: a pin drawn as
    several primitives is all of them, and a via belongs in none."""
    return tuple(o for q in fp.pads if q.number == number for o in q.outlines)


def via_judge(geometry, start: Location, net: str, size: float, drill: float, width: float,
              layer, source=()):
    """The judge `free_spot` calls for a via of `net` fed from `start` by a
    straight tail on `layer`. `source` is the pad's own copper: a via may not
    overlap it. An SMD pad's centre passes every other rule, so without this
    the answer was a via in the pad nearly every time - which needs plugging
    to stop solder wicking, and is not a tap reached by a tail. Pass no
    source to allow a via in the pad."""
    def judge(c):
        if source:
            ring = via_ring(c, size)
            if any(polys_overlap(ring, o) for o in source):
                return "in the source pad", ()
        v = judge_via(geometry, c, net, size, drill)
        if not v.clear:
            return v.hard[0], v.soft
        tail = judge_tail(geometry, start, c, net, width, layer) if c.distance(start) > 1e-9 else ()
        if tail:
            return tail[0], v.soft
        return None, v.soft
    return judge


def copper_at(geometry, at: Location) -> dict:
    """The copper covering a point, per layer."""
    out = {l: [] for l in geometry.layers}
    for c in geometry.copper:
        b = c.box
        if not (b.left <= at.x <= b.right and b.top <= at.y <= b.bottom):
            continue
        if any(point_in_polygon((at.x, at.y), o) for o in c.outlines):
            for l in c.layers:
                out.setdefault(l, []).append(c)
    return out


def _point_to_polygon(at: Location, poly) -> float:
    """0 inside the polygon, else the distance to its nearest edge."""
    if point_in_polygon((at.x, at.y), poly):
        return 0.0
    n = len(poly)
    return min(point_segment_distance((at.x, at.y), poly[i], poly[(i + 1) % n]) for i in range(n))


def nearest_foreign(geometry, at: Location, layer, net: str):
    """How far the nearest copper of another net is from the point on a layer."""
    best = None
    for c in geometry.copper:
        if c.net == net or layer not in c.layers or not c.outlines:
            continue
        d = min(_point_to_polygon(at, o) for o in c.outlines)
        best = d if best is None or d < best else best
    return best


def copper_in(geometry, box: Box) -> dict:
    """The copper inside a box, counted by (net, kind) per layer."""
    out = {l: Counter() for l in geometry.layers}
    region = ((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom))
    for c in geometry.copper:
        if not c.box.overlaps(box):
            continue
        if any(polys_overlap(region, o) for o in c.outlines):
            for l in c.layers:
                out.setdefault(l, Counter())[(c.net, c.kind)] += 1
    return out


def _ordered(layers):
    from .board_geometry import stackup_order
    return sorted(layers, key=stackup_order)


def at_lines(geometry, at: Location, net: str | None = None, size: float = 0.0, drill: float = 0.0) -> list:
    """Per layer, the copper under a point and the nearest copper of another
    net; then whether a via of `net` could stand there."""
    under = copper_at(geometry, at)
    out = ["at (%.3f, %.3f)" % (at.x, at.y)]
    for layer in _ordered(geometry.layers):
        here = under.get(layer, [])
        what = ", ".join("%s %s%s" % (c.kind, c.net or "-", (" (%s)" % c.owner) if c.owner else "")
                         for c in here) or "nothing"
        near = nearest_foreign(geometry, at, layer, net if net is not None else (here[0].net if here else ""))
        out.append("  %-7s %s%s" % (layer.value, what,
                                     "" if near is None else "; nearest other net %.2f mm" % near))
    if net is not None:
        v = judge_via(geometry, at, net, size, drill)
        out.append("  via of %s: %s" % (net or "no net", "can stand here" if v.clear else "blocked"))
        out += ["    %s" % h for h in v.hard] + ["    %s" % s for s in v.soft]
    return out


def box_lines(geometry, box: Box) -> list:
    got = copper_in(geometry, box)
    out = ["box (%.3f, %.3f)..(%.3f, %.3f)" % (box.left, box.top, box.right, box.bottom)]
    for layer in _ordered(geometry.layers):
        counts = got.get(layer)
        if not counts:
            out.append("  %-7s nothing" % layer.value)
            continue
        out.append("  %-7s %s" % (layer.value, ", ".join(
            "%s %s x%d" % (net or "-", kind, n) for (net, kind), n in counts.most_common())))
    return out


def spot_lines(spot, tally, tried, net: str, pad_label: str, tail=None) -> list:
    """The answer as text; `tail` is the (width, layer) its straight tail was
    judged at, which a tail drawn by hand must not exceed."""
    rest = ", ".join("%s x%d" % kv for kv in tally.most_common()) or "none"
    if spot is None:
        return ["via of %s near %s: nowhere, %d spot(s) tried: %s" % (net, pad_label, tried, rest)]
    out = ["via of %s near %s: (%.3f, %.3f), %.2f mm from the pad" % (
        net, pad_label, spot.at.x, spot.at.y, spot.distance)]
    if tail is not None:
        out.append("  tail %.2f mm on %s, judged straight from the pad's centre" % (tail[0], tail[1].value))
    out += ["  %s" % s for s in spot.soft]
    out.append("  nearer spots that failed: %s" % rest)
    return out


# ------------------------------------------------------------------ corridor
# The clear octilinear paths on one layer between two pads: `judge_via` and
# `judge_tail` above answer one candidate at a time, which is fine near a
# pad but too slow over the reach of a corridor query. This builds one
# occupancy - a bucketed index of what a track of `width` may not come
# within clearance of, and the board's own edge and cutouts - and searches
# an octilinear grid over it instead.

GRID_MM = 0.1                      # the router's default grid
_STEPS = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0))
_DIAGONAL = math.sqrt(2.0)


def _squeezes(cur: tuple, dx: int, dy: int, blocked) -> bool:
    """Whether a diagonal step passes between two blocked cells meeting at
    a corner: a wall, which the step would cross within their clearance."""
    return bool(dx and dy) and blocked((cur[0] + dx, cur[1])) is not None \
        and blocked((cur[0], cur[1] + dy)) is not None


@dataclass(frozen=True)
class CorridorPath:
    points: tuple           # corner points (x, y) mm, A to B, octilinear
    length: float            # mm, along the corners
    turns: int


@dataclass(frozen=True)
class CorridorResult:
    paths: tuple = ()                 # the shortest, then up to two disjoint alternatives
    blockers: tuple = ()              # named, across the narrowest cut, when paths is empty


def _snap(at: Location) -> tuple:
    return (round(at.x / GRID_MM), round(at.y / GRID_MM))


def _grid_point(idx: tuple) -> tuple:
    return (round(idx[0] * GRID_MM, 4), round(idx[1] * GRID_MM, 4))


def _row_crossings(ring, gy0: int, gy1: int) -> dict:
    """Every grid row in [gy0, gy1] paired with `ring`'s x-crossings there,
    sorted: `point_in_polygon`'s own rule (an edge crosses row y when y sits
    in [min(y1, y2), max(y1, y2)); `x < xin` toggles inside), done once a
    row instead of once a point - a ring with hundreds of vertices otherwise
    makes the per-point test the query's own cost."""
    rows: dict = {}
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if y1 == y2:
            continue
        lo, hi = (y1, y2) if y1 < y2 else (y2, y1)
        r0 = max(gy0, math.ceil(lo / GRID_MM - 1e-9))
        r1 = min(gy1, math.ceil(hi / GRID_MM - 1e-9) - 1)
        for gy in range(r0, r1 + 1):
            y = gy * GRID_MM
            rows.setdefault(gy, []).append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    for xs in rows.values():
        xs.sort()
    return rows


def _ring_inside(rows: dict, gy: int, x: float) -> bool:
    xs = rows.get(gy)
    if not xs:
        return False
    return (len(xs) - bisect.bisect_right(xs, x)) % 2 == 1


def _edge_buckets(ring, reach: float, bucket_mm: float) -> dict:
    """`ring`'s edges, bucketed by `bucket_mm`: an edge stands in every
    bucket its box grown by `reach` touches, so a point's own bucket holds
    every edge that could be nearer than `reach` to it - the same idea as
    `_CorridorOccupancy._index`, for a ring instead of a copper outline."""
    buckets: dict = {}
    n = len(ring)
    for i in range(n):
        p1, p2 = ring[i], ring[(i + 1) % n]
        x0, x1 = sorted((p1[0], p2[0]))
        y0, y1 = sorted((p1[1], p2[1]))
        for gx in range(math.floor((x0 - reach) / bucket_mm), math.floor((x1 + reach) / bucket_mm) + 1):
            for gy in range(math.floor((y0 - reach) / bucket_mm), math.floor((y1 + reach) / bucket_mm) + 1):
                buckets.setdefault((gx, gy), []).append((p1, p2))
    return buckets


def _edge_near(buckets: dict, pt: Location, reach: float, bucket_mm: float) -> bool:
    gx, gy = math.floor(pt.x / bucket_mm), math.floor(pt.y / bucket_mm)
    return any(point_segment_distance((pt.x, pt.y), p1, p2) < reach - 1e-9
               for p1, p2 in buckets.get((gx, gy), ()))


def _is_box(ring) -> bool:
    """Whether `ring` is exactly its own axis-aligned bounding box: a plain
    rectangular outline, which most boards draw."""
    return len(ring) == 4 and len({round(p[0], 6) for p in ring}) == 2 and len({round(p[1], 6) for p in ring}) == 2


class _CorridorOccupancy:
    """What a track of `width` on `layer`, net `net`, may not come within
    clearance of, inside `box`: foreign copper (pads that reach the layer,
    vias, tracks, polys and - unlike a via, which a pour gives way to -
    zones), a footprint's own copper graphics, a rule area that forbids
    tracks on the layer (unless its `allow=` names `net`), the board edge
    and cutouts. Bucketed once so a grid node's blockers are a lookup."""
    BUCKET_MM = 2.0

    def __init__(self, geometry, net: str, width: float, layer, box: Box):
        half = width / 2.0
        self.rings = tuple(geometry.board_polygon) or tuple(geometry.outline)
        self.edge_need = geometry.edge_clearance + half
        # A rectangular outline with the whole query box, grown by `edge_need`,
        # well inside it, and no cutout anywhere near: every node is on the
        # board, so `blocked` need not measure its distance to the outline's
        # every edge for each one - the cost that dominated a wide query on a
        # real board (mostly clear copper, so a flood fill visits most nodes).
        self._edge_always_clear = False
        if self.rings and _is_box(self.rings[0]):
            ob = Box.of_points(self.rings[0])
            if (ob.left <= box.left - self.edge_need and ob.top <= box.top - self.edge_need
                    and ob.right >= box.right + self.edge_need and ob.bottom >= box.bottom + self.edge_need
                    and not any(Box.of_points(h).overlaps(box, gap=self.edge_need) for h in self.rings[1:])):
                self._edge_always_clear = True
        # A ring with many vertices (a round board) makes point_in_polygon and
        # an edge-by-edge distance the query's own cost if run per node, over
        # every node a flood fill visits to prove no path. Row crossings and a
        # bucket index of the edges - point_in_polygon's own rule, and
        # `_index`'s own idea, each done once - turn that into a lookup.
        self._ring_rows, self._ring_edges = [], []
        if self.rings and not self._edge_always_clear:
            gy0, gy1 = math.floor(box.top / GRID_MM), math.ceil(box.bottom / GRID_MM)
            for ring in self.rings:
                self._ring_rows.append(_row_crossings(ring, gy0, gy1))
                self._ring_edges.append(_edge_buckets(ring, self.edge_need, self.BUCKET_MM))
        self._buckets: dict = {}
        for c in geometry.copper:
            if c.net == net or layer not in c.layers or c.kind not in _HARD + ("zone",):
                continue
            reach = geometry.clearance(net, c.net) if (net in geometry.nets and c.net in geometry.nets) \
                else geometry.default_clearance
            gap = reach + half
            if not c.box.overlaps(box, gap=gap):
                continue
            label = "%s %s%s" % (c.kind, c.net or "-", (" (%s)" % c.owner) if c.owner else "")
            self._index(c.outlines, gap, label)
        for fp in geometry.footprints:
            for l, art in fp.copper:
                if l != layer:
                    continue
                gap = geometry.default_clearance + half
                if not Box.of_points(art).overlaps(box, gap=gap):
                    continue
                self._index((art,), gap, "%s's own copper" % fp.ref)
        for ra in geometry.rule_areas:
            if "tracks" not in ra.excludes or layer not in ra.layers or net in ra.allow:
                continue
            if not Box.of_points(ra.polygon).overlaps(box, gap=half):
                continue
            self._index((ra.polygon,), half, ra.base)

    def _index(self, outlines, gap: float, label: str) -> None:
        b = Box.of_points([p for o in outlines for p in o])
        b = Box(b.left - gap, b.top - gap, b.right + gap, b.bottom + gap)
        entry = (outlines, gap, label)
        for gx in range(math.floor(b.left / self.BUCKET_MM), math.floor(b.right / self.BUCKET_MM) + 1):
            for gy in range(math.floor(b.top / self.BUCKET_MM), math.floor(b.bottom / self.BUCKET_MM) + 1):
                self._buckets.setdefault((gx, gy), []).append(entry)

    def blocked(self, idx: tuple) -> str | None:
        """None when a track of `width` may run through this grid node; else
        a short name of what stops it."""
        pt = Location(*_grid_point(idx))
        if self.rings and not self._edge_always_clear:
            if not _ring_inside(self._ring_rows[0], idx[1], pt.x):
                return "off the board"
            if _edge_near(self._ring_edges[0], pt, self.edge_need, self.BUCKET_MM):
                return "the board edge"
            for rows, edges in zip(self._ring_rows[1:], self._ring_edges[1:]):
                if _ring_inside(rows, idx[1], pt.x) or _edge_near(edges, pt, self.edge_need, self.BUCKET_MM):
                    return "a cutout"
        bucket = (math.floor(pt.x / self.BUCKET_MM), math.floor(pt.y / self.BUCKET_MM))
        for outlines, gap, label in self._buckets.get(bucket, ()):
            if any(_point_to_polygon(pt, o) < gap - 1e-9 for o in outlines):
                return label
        return None


def _flood(start: tuple, in_box, blocked) -> tuple:
    """Clear grid nodes (8-connected) reachable from `start`, bounded to
    `in_box`, and the reason of every blocked node touching that region."""
    seen = {start}
    frontier: dict = {}
    stack = [start]
    while stack:
        cur = stack.pop()
        for dx, dy in _STEPS:
            nb = (cur[0] + dx, cur[1] + dy)
            if nb in seen or not in_box(nb):
                continue
            reason = blocked(nb)
            if reason is None:
                if _squeezes(cur, dx, dy, blocked):
                    continue
                seen.add(nb)
                stack.append(nb)
            else:
                frontier.setdefault(nb, reason)
    return seen, frontier


def _cut(frontier: dict, reachable_b: set, in_box, blocked) -> list | None:
    """The shortest chain of blocked nodes (8-connected) from `frontier`
    (blocked nodes already touching A's reachable region) to one touching
    `reachable_b`: the narrowest wall separating A from B."""
    came: dict = {idx: None for idx in frontier}
    q = deque(frontier)
    while q:
        cur = q.popleft()
        for dx, dy in _STEPS:
            nb = (cur[0] + dx, cur[1] + dy)
            if nb in came or not in_box(nb):
                continue
            if nb in reachable_b:
                chain = [cur]
                while came[chain[-1]] is not None:
                    chain.append(came[chain[-1]])
                chain.reverse()
                return chain
            reason = blocked(nb)
            if reason is None:
                continue
            came[nb] = cur
            q.append(nb)
    return None


def _astar(start: tuple, goal: tuple, in_box, blocked, avoid: frozenset) -> list | None:
    """The shortest octilinear path from `start` to `goal` over clear grid
    nodes, `avoid` (an earlier path's own cells) refused except at the
    endpoints, which every path shares."""
    def h(idx):
        dx, dy = abs(idx[0] - goal[0]), abs(idx[1] - goal[1])
        return GRID_MM * (max(dx, dy) + (_DIAGONAL - 1.0) * min(dx, dy))
    best = {start: 0.0}
    came: dict = {}
    open_heap = [(h(start), 0.0, start)]
    while open_heap:
        f, g, cur = heapq.heappop(open_heap)
        if cur == goal:
            path = [cur]
            while path[-1] != start:
                path.append(came[path[-1]])
            path.reverse()
            return path
        if g > best.get(cur, math.inf) + 1e-12:
            continue
        for dx, dy in _STEPS:
            nb = (cur[0] + dx, cur[1] + dy)
            if not in_box(nb):
                continue
            if nb != start and nb != goal:
                if nb in avoid or blocked(nb) is not None:
                    continue
            if _squeezes(cur, dx, dy, blocked):
                continue
            ng = g + GRID_MM * (_DIAGONAL if dx and dy else 1.0)
            if ng < best.get(nb, math.inf) - 1e-12:
                best[nb] = ng
                came[nb] = cur
                heapq.heappush(open_heap, (ng + h(nb), ng, nb))
    return None


def _corners(path: list) -> tuple:
    """`path`'s own corner points: where its direction changes, plus its
    ends - a straight run collapsed to its two ends, as a drawn track is."""
    pts = [_grid_point(idx) for idx in path]
    if len(path) <= 2:
        return tuple(pts)
    out = [pts[0]]
    for i in range(1, len(path) - 1):
        before = (path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
        after = (path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
        if before != after:
            out.append(pts[i])
    out.append(pts[-1])
    return tuple(out)


def _path_length(points: tuple) -> float:
    return round(sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])), 4)


def _dilate(cells, radius: int) -> frozenset:
    """`cells` grown by `radius` grid steps in every direction (Chebyshev):
    the room another track needs to keep its own clearance from one drawn
    along `cells`, so an "alternative" avoiding only this is a genuinely
    different corridor, not the same one shifted a cell."""
    if radius <= 0:
        return frozenset(cells)
    return frozenset((x + dx, y + dy) for x, y in cells
                     for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1))


def _far_from_ends(cells, a_idx: tuple, b_idx: tuple, radius: int) -> set:
    """`cells` further than `radius` (Chebyshev) from both `a_idx` and
    `b_idx`: what an alternative may be kept off. Growing the path's own
    cells right at the pads it leaves from would wall each pad in on every
    side - every path shares that one point, and cannot keep a clearance
    from itself there."""
    def far(idx, centre) -> bool:
        return max(abs(idx[0] - centre[0]), abs(idx[1] - centre[1])) > radius
    return {c for c in cells if far(c, a_idx) and far(c, b_idx)}


def _with_pad_ends(points: tuple, a: Location, b: Location) -> tuple:
    """`points` with its first and last corner `a` and `b` themselves: the
    search snaps to the 0.1 mm grid, so without this the reported ends can
    stand up to half a grid step - about 0.07 mm on the diagonal - off the
    pads' own centres."""
    if len(points) <= 1:
        return ((a.x, a.y),)
    return ((a.x, a.y),) + points[1:-1] + ((b.x, b.y),)


def corridor(geometry, a: Location, b: Location, net: str, width: float, layer, margin: float = 10.0) -> CorridorResult:
    """The clear octilinear paths on `layer` from `a` to `b` for a track of
    `width` on `net`: the shortest, plus up to two more that keep at least a
    track-and-clearance gap from it and each other - not the same corridor
    shifted a cell - on a 0.1 mm grid over the box round `a` and `b` grown by
    `margin`. Each path's first and last corner is `a` and `b` themselves,
    not the grid node the search snapped them to. With none, the blockers
    across the narrowest cut between them - a rule area forbidding tracks on
    the layer is named among them too, unless its `allow=` names `net`."""
    a_idx, b_idx = _snap(a), _snap(b)
    box = Box.of_points([(a.x, a.y), (b.x, b.y)])
    box = Box(box.left - margin, box.top - margin, box.right + margin, box.bottom + margin)
    gx0, gy0 = math.floor(box.left / GRID_MM), math.floor(box.top / GRID_MM)
    gx1, gy1 = math.ceil(box.right / GRID_MM), math.ceil(box.bottom / GRID_MM)

    def in_box(idx):
        return gx0 <= idx[0] <= gx1 and gy0 <= idx[1] <= gy1

    occ = _CorridorOccupancy(geometry, net, width, layer, box)
    cache: dict = {}

    def blocked(idx):
        hit = cache.get(idx, False)
        if hit is False:
            hit = cache[idx] = occ.blocked(idx)
        return hit
    # A* first, goal-directed: it need not touch most of a wide-open box. The
    # flood fill below - which does, to prove a negative - only runs when it
    # finds nothing.
    reach = geometry.clearance(net) if net in geometry.nets else geometry.default_clearance
    keep_off = math.ceil((width + reach) / GRID_MM)
    paths, avoid = [], frozenset()
    for _ in range(3):
        raw = _astar(a_idx, b_idx, in_box, blocked, avoid)
        if raw is None:
            break
        points = _with_pad_ends(_corners(raw), a, b)
        paths.append(CorridorPath(points, _path_length(points), max(0, len(points) - 2)))
        grow = _far_from_ends(set(raw) - {a_idx, b_idx}, a_idx, b_idx, keep_off)
        avoid = avoid | _dilate(grow, keep_off)
    if paths:
        return CorridorResult(paths=tuple(paths))
    seen_a, frontier_a = _flood(a_idx, in_box, blocked)
    seen_b, _ = _flood(b_idx, in_box, blocked)
    chain = _cut(frontier_a, seen_b, in_box, blocked)
    if chain is None:
        return CorridorResult(blockers=("no path within the box; a larger --margin may find one",))
    labels = []
    for idx in chain:
        r = blocked(idx)
        if r and r not in labels:
            labels.append(r)
    return CorridorResult(blockers=tuple(labels))


def corridor_lines(result: CorridorResult, a_label: str, b_label: str, net: str, width: float, layer) -> list:
    out = ["corridor %s -> %s on %s, %.2f mm wide (net %s)" % (a_label, b_label, layer.value, width, net or "-")]
    if not result.paths:
        out.append("  no path; the narrowest cut:")
        out += ["    %s" % b for b in result.blockers]
        return out
    for i, p in enumerate(result.paths):
        out.append("  %s: %.3f mm, %d turn(s)" % ("shortest" if i == 0 else "alternative %d" % i, p.length, p.turns))
        out += ["    (%.3f, %.3f)" % pt for pt in p.points]
    return out
