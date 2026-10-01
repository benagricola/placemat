"""A pour whose corners are pads covers the pads' copper, not a polygon
through their centres: over three pads in a row that polygon is a line,
and the pour was as thin as its stroke. A pour over pads with swallow_pads
is fitted and takes no cover (test_pour_fitted.py); one drawn as declared
takes Cover.HULL, the convex hull of the pads' copper, Cover.BOX the box
round it, or Cover.CENTRES (the default) the points as given.
Pure: synthetic boards."""
import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Pour
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Cover, Face, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, pad


def _one_pad_part(i):
    cx, cy = 10 + 4 * i, 10
    p = pad("U%d" % i, "u%d" % i, 1, "SW", cx, cy, 1.0, 1.0)
    body = Box(cx - 1.0, cy - 1.0, cx + 1.0, cy + 1.0)
    return Footprint("U%d" % i, "u%d" % i, None, "U%d" % i, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1),
                     body, (p,))


def _board():
    # three parts in a row, each a 1 x 1 mm pad on SW at x = 10, 14, 18 (y 10)
    return Board(board_geometry([_one_pad_part(i) for i in range(3)], width=40, height=30), edge_margin=0.5)


def _pads():
    return [PadRef(Part("u%d" % i), 1) for i in range(3)]


def _pour(plan):
    (p,) = [c for c in plan.copper if isinstance(c, Pour)]
    return p


def test_a_fitted_pour_over_pads_with_nothing_in_the_way_is_the_hull_of_their_copper():
    b = _board()
    b.pour(Net("SW"), _pads(), layer=CopperLayer.F, swallow_pads=True)
    p = _pour(b.resolve())
    box = Box.of_points(p.points)
    assert p.fitted
    assert (box.left, box.top, box.right, box.bottom) == pytest.approx((9.5, 9.5, 18.5, 10.5))     # the pads' own height, not a line through centres


def test_a_declared_pour_over_pads_covers_the_hull_of_their_copper_with_cover_hull():
    b = _board()
    b.pour(Net("SW"), _pads(), layer=CopperLayer.F, cover=Cover.HULL)
    p = _pour(b.resolve())
    box = Box.of_points(p.points)
    assert not p.fitted
    assert (box.left, box.top, box.right, box.bottom) == pytest.approx((9.5, 9.5, 18.5, 10.5))


def test_cover_centres_keeps_the_polygon_through_the_pads():
    b = _board()
    b.pour(Net("SW"), _pads(), layer=CopperLayer.F, cover=Cover.CENTRES)
    box = Box.of_points(_pour(b.resolve()).points)
    assert box.height == pytest.approx(0.0, abs=1e-6)


def test_a_pour_over_pads_covers_their_centres_unless_told_otherwise():
    b = _board()
    b.pour(Net("SW"), _pads(), layer=CopperLayer.F)
    box = Box.of_points(_pour(b.resolve()).points)
    assert box.height == pytest.approx(0.0, abs=1e-6)


def test_cover_box_is_the_box_round_the_pads_copper():
    b = _board()
    b.pour(Net("SW"), _pads(), layer=CopperLayer.F, cover=Cover.BOX)
    plan = b.resolve()
    pts = _pour(plan).points
    assert len(pts) == 4
    want = Box.union([sh.box for i in range(3) for sh in plan.occupancy.items["U%d" % i].shapes
                      if sh.kind == "pad" and sh.net == "SW"])
    got = Box.of_points(pts)
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx((want.left, want.top, want.right, want.bottom))


def test_cover_needs_an_enum():
    b = _board()
    with pytest.raises(TypeError):
        b.pour(Net("SW"), _pads(), layer=CopperLayer.F, cover="hull")
