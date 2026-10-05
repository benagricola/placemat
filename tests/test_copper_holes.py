# tests/test_copper_holes.py
"""Declared copper nearer a part's drilled hole than the hole clearance is copper.meets, as a via's hole against copper
already is: a plated hole of another net (hole_copper, KiCad's HOLE_CLEARANCE_CONSTRAINT, the copper's own net
waived) and an unplated hole (npth_near under the clearance, npth_cuts over it). Placement asks what it asked before.
Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Track
from placemat.layout import Board, _shape_of
from placemat.values import Box, CopperLayer, Face, Location, Net, Part
from tests.fixtures import board_geometry, pad


def _through_part(net, cx=30.0, cy=15.0):
    """A 1 mm ring with a 0.5 mm drill: the drill's edge 0.25 from the centre, the ring's 0.5."""
    p = pad("H1", "h1", 1, net, cx, cy, 1.0, 1.0, through=True)
    body = Box(cx - 0.5, cy - 0.5, cx + 0.5, cy + 0.5)
    return Footprint("H1", "h1", None, "H1", Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _npth_part(cx=20.0, cy=15.0, drill=1.0):
    body = Box(cx - 1.0, cy - 1.0, cx + 1.0, cy + 1.0)
    return Footprint("M1", "m1", None, "M1", Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (),
                     npth=((Location(cx, cy), drill),))


def _board(fps, hole_clearance):
    g = dataclasses.replace(board_geometry(fps, width=40, height=30, extra_nets=["SIG", "A"]), hole_clearance=hole_clearance)
    b = Board(g, edge_margin=0.4)
    b.rect(width=40.0, height=30.0)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b


def _meets(plan):
    return [f.facts["hit"] for f in plan.findings if f.cause.value == "copper.meets"]


def test_a_track_under_the_hole_clearance_from_an_npth_is_copper_meets():
    b = _board([_npth_part()], hole_clearance=0.3)
    # the hole's edge at x = 19.5; the 0.2 mm track's east edge at 19.3: 0.2 from it, under 0.3
    b.track(Net("SIG"), [Location(19.2, 5.0), Location(19.2, 25.0)], layer=CopperLayer.F)
    (hit,) = _meets(b.resolve())
    assert hit["code"] == "npth_near" and hit["gap_mm"] == pytest.approx(0.2, abs=0.01) and hit["need_mm"] == 0.3


def test_a_track_over_an_npth_is_copper_meets_npth_cuts():
    b = _board([_npth_part()], hole_clearance=0.3)
    b.track(Net("SIG"), [Location(20.0, 5.0), Location(20.0, 25.0)], layer=CopperLayer.F)
    assert [h["code"] for h in _meets(b.resolve())] == ["npth_cuts"]


@pytest.mark.parametrize("net, codes", [("A", ["hole_copper"]), ("SIG", [])], ids=["another net", "its own net"])
def test_a_track_under_the_hole_clearance_from_a_plated_hole(net, codes):
    b = _board([_through_part(net)], hole_clearance=0.6)
    # the ring's west edge at 29.5, the drill's at 29.75; the track's east edge at 29.2: 0.3 from the ring (the 0.2
    # copper clearance holds) and 0.55 from the drill, under 0.6
    b.track(Net("SIG"), [Location(29.1, 5.0), Location(29.1, 25.0)], layer=CopperLayer.F)
    assert [h["code"] for h in _meets(b.resolve())] == codes


def test_placement_asks_what_it_asked_before():
    b = _board([_npth_part()], hole_clearance=0.3)
    occ = b.resolve().occupancy
    shape = _shape_of(Track("SIG", CopperLayer.F, 0.2, Location(19.2, 5.0), Location(19.2, 25.0)))
    assert occ.copper_conflicts(shape) == []
    assert [r.code.value for r in occ.copper_conflicts(shape, check=True)] == ["npth_near"]
