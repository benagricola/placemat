"""A pour whose corners are pads covers the pads' copper, not a polygon
through their centres: over three pads in a row that polygon is a line,
and the pour was as thin as its stroke. Cover.HULL (the default for a pour
over pads whose corners are all pads) is the convex hull of the pads'
copper; Cover.BOX the box round it; Cover.CENTRES the points as given.
Pure: synthetic boards."""
import pytest

from placemat.copper import Pour
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Cover, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    # three parts in a row, each a 1 x 1 mm pad on SW at x = 9.6, 13.6, 17.6 (y 10)
    fps = [footprint("U%d" % i, 10 + 4 * i, 10, w=2, h=1, inst="u%d" % i, nets=("SW", "X%d" % i)) for i in range(3)]
    b = Board(board_geometry(fps, width=40, height=30), edge_margin=0.5)
    for i in range(3):
        b.place(Part("u%d" % i), at=Location(10 + 4 * i, 10))
    return b


def _pads():
    return [PadRef(Part("u%d" % i), "SW") for i in range(3)]


def _pour(plan):
    (p,) = [c for c in plan.copper if isinstance(c, Pour)]
    return p


def test_a_pour_over_pads_covers_their_copper_by_default():
    b = _board()
    b.pour(Net("SW"), _pads(), layer=CopperLayer.F, swallow_pads=True)
    box = Box.of_points(_pour(b.resolve()).points)
    # the pads' copper: x 8.6..18.6 (pads 1 mm round centres 9.1, 13.1, 17.1... read off the plan), y 9.5..10.5
    assert box.height == pytest.approx(1.0, abs=1e-6)         # the pads' own height, not a line through centres
    assert box.width > 8.0


def test_cover_centres_keeps_the_polygon_through_the_pads():
    b = _board()
    b.pour(Net("SW"), _pads(), layer=CopperLayer.F, swallow_pads=True, cover=Cover.CENTRES)
    box = Box.of_points(_pour(b.resolve()).points)
    assert box.height == pytest.approx(0.0, abs=1e-6)


def test_cover_box_is_the_box_round_the_pads_copper():
    b = _board()
    b.pour(Net("SW"), _pads(), layer=CopperLayer.F, swallow_pads=True, cover=Cover.BOX)
    pts = _pour(b.resolve()).points
    assert len(pts) == 4
    plan = b.resolve()
    want = Box.union([sh.box for i in range(3) for sh in plan.occupancy.items["U%d" % i].shapes
                      if sh.kind == "pad" and sh.net == "SW"])
    got = Box.of_points(pts)
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx((want.left, want.top, want.right, want.bottom))


def test_cover_needs_an_enum():
    b = _board()
    with pytest.raises(TypeError):
        b.pour(Net("SW"), _pads(), layer=CopperLayer.F, swallow_pads=True, cover="hull")
