"""What is at a point, what is in a box, and where a via may stand.

Pure: a board is a `BoardGeometry`, whichever way it was read. A via joins
every copper layer at one point, so it is judged against every layer; a zone
fill of another net is not an obstacle, because KiCad refills a zone and pulls
it back round a new via, and is reported as giving way instead."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

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
