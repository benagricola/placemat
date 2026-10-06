"""A fitted pour round another net's via or plated-through pad standing wholly inside its outline: the item becomes a
clearance hole in the pour, as KiCad's zone filler cuts one (zone_filler.cpp), and the pour is drawn where, with the
hole, it still meets its need - Reach.CURRENT its current, otherwise one piece joining every member. Otherwise it is
refused and the finding names the via. Any other copper standing inside (a track, an SMD pad) refuses it as before.

Synthetic four-layer boards: two parts' plated-through VB pins on one row, the pour on In2 between them."""
import dataclasses

import pytest

from placemat.board_geometry import CopperItem, Footprint, PadGeom
from placemat.copper import Pour
from placemat.geometry import circle_polygon, point_in_polygon
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Face, Location, Net, PadRef, Part, Reach
from tests.fixtures import board_geometry, rect
from tests.test_pour_fitted import CLEARANCE

F, IN1, IN2, B = CopperLayer.F, CopperLayer.IN1, CopperLayer.IN2, CopperLayer.B
FOUR = frozenset((F, IN1, IN2, B))
Y = 25.0
VIA = (11.0, Y)


def _pin(ref, x, h, amps):
    o = rect(x, Y, 1.7, h)
    p = PadGeom(ref, ref.lower(), "1", "VB", FOUR, (o,), Box.of_points(o), True, 1.0)
    body = p.box.inflate(0.3)
    return Footprint(ref, ref.lower(), None, ref, body.center, 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,),
                     fields={"Pm.I": amps} if amps else {})


def _via(x, y, net="G"):
    ring = circle_polygon(Location(x, y), 0.225)
    return CopperItem("via", net, FOUR, (ring,), Box.of_points(ring), None, width_mm=0.45, drill_mm=0.2, anchors=((x, y),))


def _track(net="G"):
    o = rect(VIA[0], Y, 0.6, 0.2)
    return CopperItem("track", net, frozenset([IN2]), (o,), Box.of_points(o), None, 0.2,
                      anchors=((VIA[0] - 0.2, Y), (VIA[0] + 0.2, Y)), length_mm=0.4)


def _board(h=4.0, amps=None, copper=None):
    """J1's pin at x 8 and J2's at x 14, each 1.7 mm across and `h` tall, a G via standing between them."""
    parts = [_pin("J1", 8.0, h, amps), _pin("J2", 14.0, h, amps)]
    g = board_geometry(parts, copper=[_via(*VIA)] if copper is None else copper, width=40, height=50,
                       clearance=CLEARANCE, extra_nets=("G",))
    g = dataclasses.replace(g, layers=(F, IN1, IN2, B))
    b = Board(g, edge_margin=1.0, keep_going=True)
    for fp in parts:
        b.place(Part(fp.inst), at=fp.location)
    return b


def _pour(b, reach=None):
    b.pour(Net("VB"), [PadRef(Part("j1"), 1), PadRef(Part("j2"), 1)], layer=IN2, swallow_pads=True, reach=reach)
    return b.resolve()


def _pours(plan):
    return [c for c in plan.copper if isinstance(c, Pour)]


def _refusal(plan):
    (f,) = [f for f in plan.findings if f.facts.get("variant") in ("pour_enclosed", "pour_hole")]
    return f


def _holds(points, p) -> bool:
    return point_in_polygon(p, points)


def test_a_via_wholly_inside_is_a_clearance_hole_in_the_pour():
    plan = _pour(_board())
    (p,) = _pours(plan)
    assert not _holds(p.points, VIA)                     # the via stands in a hole
    assert _holds(p.points, (8.0, Y)) and _holds(p.points, (14.0, Y))
    for dy in (-1.5, 1.5):                               # copper either side of it
        assert _holds(p.points, (VIA[0], Y + dy))
    # the hole keeps the clearance and half the stroke: no outline point nearer the via
    near = min(((x - VIA[0]) ** 2 + (y - Y) ** 2) ** 0.5 for x, y in p.points)
    assert near >= 0.225 + CLEARANCE + p.stroke / 2.0 - 1e-3


def test_a_hole_that_would_cut_the_pour_in_two_is_refused_naming_the_via():
    plan = _pour(_board(h=1.3))
    assert not _pours(plan)
    f = _refusal(plan)
    assert f.facts["what"]["form"] == "via" and f.facts["what"]["at"] == pytest.approx(list(VIA))
    assert "via G at (11.00, 25.00)" in str(f), str(f)


def test_an_enclosed_track_is_still_refused():
    plan = _pour(_board(copper=[_track()]))
    assert not _pours(plan)
    f = _refusal(plan)
    assert f.facts["variant"] == "pour_enclosed"


def test_a_pour_to_current_round_a_via_is_drawn_where_it_meets_the_current():
    plan = _pour(_board(amps="1A"), reach=Reach.CURRENT)
    (p,) = _pours(plan)
    assert not _holds(p.points, VIA)
    assert not [f for f in plan.findings if f.facts.get("variant") in ("pour_neck", "pour_hole", "pour_enclosed")]


def test_a_pour_to_current_whose_hole_leaves_it_short_is_refused_naming_the_via():
    plan = _pour(_board(amps="40A"), reach=Reach.CURRENT)
    assert not _pours(plan)
    f = _refusal(plan)
    assert f.facts["variant"] == "pour_hole" and f.facts["what"]["form"] == "via"
    assert f.facts["width_mm"] < f.facts["need_mm"]
    assert "via G at (11.00, 25.00)" in str(f), str(f)
