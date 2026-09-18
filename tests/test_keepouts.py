"""A region that forbids: what may not sit in it, fill it, route through it
or via it, and how a script says so."""
import math

import pytest

from placemat.cutouts import Arc, Circle, Cutouts, Path, Slot
from placemat.values import Box, CopperLayer, Location


def loop_of(shape, at, rotation=0.0):
    return Cutouts([shape.path_at(at, rotation)]).loops[0]


def centre_of(loop):
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def test_a_shape_with_no_anchor_still_lands_on_its_middle():
    """The default is what cutouts already do, and they must not move."""
    for shape in (Slot(13.0, 3.0), Circle(8.0),
                  Path([(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)])):
        got = centre_of(loop_of(shape, Location(20.0, 30.0)))
        assert got == pytest.approx((20.0, 30.0), abs=0.02)


def test_an_anchor_is_the_point_that_lands_on_the_place():
    """A datasheet figure is transcribed in its own coordinates and anchored
    at the feature it is organised around - a feed pad, an outer edge."""
    p = Path([(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)], anchor=(0.0, 0.0))
    loop = loop_of(p, Location(20.0, 30.0))
    xs, ys = [q[0] for q in loop], [q[1] for q in loop]
    assert (min(xs), min(ys)) == pytest.approx((20.0, 30.0), abs=0.02)
    assert (max(xs), max(ys)) == pytest.approx((30.0, 34.0), abs=0.02)


def test_an_anchored_shape_turns_about_its_anchor():
    p = Path([(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)], anchor=(0.0, 0.0))
    loop = loop_of(p, Location(20.0, 30.0), 90.0)
    xs, ys = [q[0] for q in loop], [q[1] for q in loop]
    assert min(xs) == pytest.approx(16.0, abs=0.02)      # 4 wide, now vertical
    assert max(ys) == pytest.approx(40.0, abs=0.02)      # 10 long, now south
    assert (20.0, 30.0) == pytest.approx((max(xs), min(ys)), abs=0.02)


def test_a_slot_and_a_circle_take_an_anchor_too():
    s = Slot(13.0, 3.0, anchor=(-6.5, 0.0))              # its west tip
    loop = loop_of(s, Location(20.0, 20.0))
    assert min(q[0] for q in loop) == pytest.approx(20.0, abs=0.02)
    c = Circle(8.0, anchor=(0.0, -4.0))                  # its north point
    loop = loop_of(c, Location(20.0, 20.0))
    assert min(q[1] for q in loop) == pytest.approx(20.0, abs=0.02)


from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Face, Part
from tests.fixtures import board_geometry, footprint


def _occ(*insts):
    fps = [footprint(i.upper(), 10.0 + n * 8.0, 10.0, w=4.0, h=4.0, inst=i, nets=("SIG", "GND"))
           for n, i in enumerate(insts)]
    g = board_geometry(fps, width=60, height=60)
    occ = Occupancy(g, edge_margin=0.0, board_box=None)
    for fp in fps:
        occ.commit(fp, Placement(fp.location, 0.0, Face.FRONT))
    return g, occ


def test_a_reservation_can_be_a_polygon_not_just_a_box():
    """An antenna clearance is a stepped polygon, and a box round it would
    forbid board the datasheet allows."""
    g, occ = _occ("u1")
    # a C whose bite faces the part: a box would hit it and the polygon must not
    occ.reserve([(6.0, 6.0), (14.0, 6.0), (14.0, 7.0), (8.0, 7.0),
                 (8.0, 13.0), (14.0, 13.0), (14.0, 14.0), (6.0, 14.0)],
                "the clearance")
    fp = g.footprints[0]
    assert occ.legal(fp, Placement(Location(11.0, 10.0), 0.0, Face.FRONT)) is None


def test_a_part_in_a_reservation_is_refused_by_its_why():
    g, occ = _occ("u1")
    occ.reserve(Box(6.0, 6.0, 14.0, 14.0), "the clearance")
    why = occ.legal(g.footprints[0], Placement(Location(10.0, 10.0), 0.0, Face.FRONT))
    assert why is not None and "the clearance" in why


def test_a_named_part_may_sit_in_a_reservation():
    """An antenna's own matching network lives inside its clearance, and
    those parts are named individually: allowing their NETS would admit
    every part that carries GND."""
    g, occ = _occ("u1")
    occ.reserve(Box(6.0, 6.0, 14.0, 14.0), "the clearance", owners=("U1",))
    assert occ.legal(g.footprints[0], Placement(Location(10.0, 10.0), 0.0, Face.FRONT)) is None


def test_a_box_reservation_still_works():
    """Labels reserve their own text box and must not change."""
    g, occ = _occ("u1")
    occ.reserve(Box(40.0, 40.0, 50.0, 50.0), "a label")
    assert occ.legal(g.footprints[0], Placement(Location(10.0, 10.0), 0.0, Face.FRONT)) is None
