"""What is at a point, what is in a box, and where a via may stand.

Pure: a board is a `BoardGeometry`, whichever way it was read. A via joins
every copper layer at one point, so it is judged against every layer; a zone
fill of another net is not an obstacle, because KiCad refills a zone and pulls
it back round a new via, and is reported as giving way instead."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re

from .geometry import (circle_polygon, distance_to_boundary, point_in_polygon, point_segment_distance,
                       poly_distance, polys_overlap)
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
    poly = circle_polygon(at, size / 2.0)
    box = Box(at.x - size / 2.0, at.y - size / 2.0, at.x + size / 2.0, at.y + size / 2.0)
    hard, soft = [], []
    rings = _edge_rings(geometry)
    if rings and not point_in_polygon((at.x, at.y), rings[0]):
        hard.append("off the board")
    elif rings:
        gap = min(distance_to_boundary(poly, r) for r in rings)
        if gap < geometry.edge_clearance - 1e-9:
            hard.append("%.2f mm from the board edge (needs %.2f)" % (gap, geometry.edge_clearance))
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
            hard.append("%.2f mm from %s %s on %s (needs %.2f)" % (gap, c.net or "-", c.kind, where, reach))
    for centre, dia, what in _holes(geometry):
        gap = at.distance(centre) - (drill + dia) / 2.0
        if gap < geometry.hole_to_hole - 1e-9:
            hard.append("hole %.2f mm from the %s hole (needs %.2f)" % (max(gap, 0.0), what, geometry.hole_to_hole))
    for ra in geometry.rule_areas:
        if "vias" in ra.excludes and ra.layers and polys_overlap(poly, ra.polygon):
            hard.append("inside %s, which forbids vias" % ra.base)
    return ViaVerdict(tuple(hard), tuple(dict.fromkeys(soft)))


def _segment(a: Location, b: Location, width: float):
    """A straight track as a polygon: a rectangle along the segment, capped."""
    dx, dy = b.x - a.x, b.y - a.y
    n = math.hypot(dx, dy) or 1.0
    ox, oy = -dy / n * width / 2.0, dx / n * width / 2.0
    return ((a.x + ox, a.y + oy), (b.x + ox, b.y + oy), (b.x - ox, b.y - oy), (a.x - ox, a.y - oy))


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
            out.append("tail %.2f mm from %s %s on %s (needs %.2f)" % (gap, c.net or "-", c.kind, layer.value, reach))
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
            ring = circle_polygon(c, size / 2.0)
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


def spot_lines(spot, tally, tried, net: str, pad_label: str) -> list:
    rest = ", ".join("%s x%d" % kv for kv in tally.most_common()) or "none"
    if spot is None:
        return ["via of %s near %s: nowhere, %d spot(s) tried: %s" % (net, pad_label, tried, rest)]
    out = ["via of %s near %s: (%.3f, %.3f), %.2f mm from the pad" % (
        net, pad_label, spot.at.x, spot.at.y, spot.distance)]
    out += ["  %s" % s for s in spot.soft]
    out.append("  nearer spots that failed: %s" % rest)
    return out
