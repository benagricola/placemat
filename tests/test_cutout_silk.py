"""A cutout keeps the board's silk clearance from a part's silk, on either face: KiCad judges silk against Edge.Cuts by
the silk clearance (drc_test_provider_edge_clearance.cpp, SILK_CLEARANCE_CONSTRAINT, DRCE_SILK_EDGE_CLEARANCE), a hole's
edge included, whichever face the silk is printed on."""
import math

import pytest

from placemat.cutouts import Circle
from placemat.geometry import point_segment_distance
from placemat.layout import Board
from placemat.values import Centre, Cutout, Face, Location, Near, PadRef, Part, X, Y
from tests.fixtures import board_geometry, footprint

SILK = 0.2


def _gap_to_circle(centre, radius, poly) -> float:
    """How far a polygon is from a circle's edge, the circle being the hole."""
    n = len(poly)
    d = min(point_segment_distance(centre, poly[i], poly[(i + 1) % n]) for i in range(n))
    return d - radius


def _plan(face, silk_clearance=SILK):
    # a silk line down the part's east end, 0.1 mm outside its body: the nearest spot east of the pad that clears
    # the part's reach (pads and drawn graphics) leaves the hole 0.15 mm from that line
    fp = footprint("U1", 20.0, 20.0, w=4.0, h=2.0, inst="u1", face=face, silk_boxes=[(22.0, 19.0, 22.1, 21.0)])
    g = board_geometry([fp], width=40, height=40, silk_clearance=silk_clearance)
    b = Board(g, edge_margin=0.5)
    b.rect(width=40.0, height=40.0, holes=[Cutout(Circle(1.5), "vent", at=Near(PadRef(Part("u1"), 2)), why="air")])
    b.place(Part("u1"), at=Location(20.0, 20.0), face=face)
    plan = b.resolve()
    return plan, g


@pytest.mark.parametrize("face", [Face.FRONT, Face.BACK], ids=["front", "back"])
def test_a_cutout_searched_by_a_pad_keeps_the_silk_clearance_from_the_parts_silk(face):
    plan, g = _plan(face)
    vent = plan.cutouts_placed["vent"]
    silk = [s for s in plan.occupancy.items["U1"].shapes if s.kind == "silk"] or \
        [poly for _f, poly in g.footprint("U1").silk]
    polys = [getattr(s, "poly", s) for s in silk]
    centre = (vent.centre.x, vent.centre.y)
    gap = min(_gap_to_circle(centre, 0.75, p) for p in polys)
    assert gap >= SILK - 1e-9, (vent.centre, gap)
    # and no further than the search's step needs: the hole still stands by the pad
    assert math.hypot(vent.centre.x - 21.4, vent.centre.y - 20.0) < 2.5, vent.centre


def test_a_board_with_no_silk_clearance_lets_the_hole_stand_by_the_silk():
    plan, g = _plan(Face.FRONT, silk_clearance=0.0)
    vent = plan.cutouts_placed["vent"]
    assert vent.centre.x == pytest.approx(23.0, abs=1e-6), vent.centre


def test_a_cutout_whose_place_is_decided_is_cut_there_by_the_silk():
    """Placed off the part, 0.1 mm from its silk: the script decided the place, and the hole is cut there."""
    fp = footprint("U1", 20.0, 20.0, w=4.0, h=2.0, inst="u1", silk_boxes=[(22.4, 19.0, 22.5, 21.0)])
    g = board_geometry([fp], width=40, height=40, silk_clearance=SILK)
    b = Board(g, edge_margin=0.5)
    b.rect(width=40.0, height=40.0,
           holes=[Cutout(Circle(1.5), "vent", at=Centre(X(Part("u1"), 3.35), Y(Part("u1"))), why="air")])
    b.place(Part("u1"), at=Location(20.0, 20.0))
    plan = b.resolve()
    vent = plan.cutouts_placed["vent"].centre
    assert vent.x == pytest.approx(23.35) and vent.y == pytest.approx(20.0)
    assert not plan.findings, plan.findings


@pytest.mark.parametrize("face", [Face.FRONT, Face.BACK], ids=["front", "back"])
def test_placed_silk_is_where_the_physical_envelope_puts_the_parts_silk(face):
    """The silk a hole is judged against, in any envelope, stands where the part's own silk shapes do once moved,
    turned and flipped."""
    import dataclasses
    from placemat.settings import Settings
    fp = footprint("U1", 30.0, 30.0, w=4.0, h=2.0, inst="u1", silk_boxes=[(32.0, 29.0, 32.1, 31.0)])
    g = board_geometry([fp], width=60, height=60, silk_clearance=SILK)
    b = Board(g, edge_margin=0.5, settings=dataclasses.replace(Settings(), place_envelope="physical"))
    b.place(Part("u1"), at=Location(20.0, 25.0), rotation=90.0, face=face)
    occ = b.resolve().occupancy
    want = sorted(tuple(sorted(s.poly)) for s in occ.items["U1"].shapes if s.kind == "silk")
    got = sorted(tuple(sorted(p)) for p in occ.placed_silk("U1"))
    assert len(got) == len(want) == 1
    assert all(a == pytest.approx(b, abs=1e-9) for a, b in zip(got[0], want[0])), (got, want)
