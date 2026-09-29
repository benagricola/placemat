"""A keepout inside a part's pad ring: Inside(Part(...), margin) is the box
bounded by the inner edges of the part's pads, in the part's own frame,
moving, turning and mirroring with it as keepout(Part) does. Pure:
synthetic boards."""
import pytest

from placemat import Inside
from placemat.board_geometry import Footprint
from placemat.values import Box, Face, Location, Part
from placemat.layout import Board
from tests.fixtures import board_geometry, pad


def _part(pads, body=None):
    """A part at the origin (its footprint origin at 0, 0) with `pads`; its
    body the pads' box grown by 0.5 unless given."""
    body = body or Box.union([p.box for p in pads]).inflate(0.5)
    return Footprint("U1", "u1", None, "U1", Location(0.0, 0.0), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                     tuple(pads))


def _columns():
    """Two columns of three pads, 1 x 0.5 mm, at x = -2 and +2, y = -1, 0, 1:
    no pads north or south."""
    return [pad("U1", "u1", n, "N%d" % n, x, y, 1.0, 0.5)
            for n, (x, y) in enumerate(((-2, -1), (-2, 0), (-2, 1), (2, 1), (2, 0), (2, -1)), start=1)]


def _ring():
    """A ring asymmetric on both axes, with a centre pad taller than it is
    wide that sits across the centre:
    - west column at x = -2 (right edge -1.5), east at x = 2.5 (left edge 2.0);
    - north row at y = -3 (bottom edge -2.5), south row at y = 2 (top edge 1.5);
    - the centre pad 1.2 x 1.4 at the origin, on neither side of the body centre."""
    side = [(-2, -0.5, 1.0, 0.4), (-2, 0.5, 1.0, 0.4), (2.5, -0.5, 1.0, 0.4), (2.5, 0.5, 1.0, 0.4),
            (-0.5, -3, 0.4, 1.0), (0.5, -3, 0.4, 1.0), (-0.5, 2, 0.4, 1.0), (0.5, 2, 0.4, 1.0)]
    pads = [pad("U1", "u1", n, "N%d" % n, x, y, w, h) for n, (x, y, w, h) in enumerate(side, start=1)]
    return pads + [pad("U1", "u1", 9, "GND", 0.0, 0.0, 1.2, 1.4)]


def _board(pads):
    return Board(board_geometry([_part(pads)], width=60.0, height=60.0), edge_margin=0.5)


def _box(plan, name="in") -> tuple:
    b = Box.of_points(plan.keepouts[name].poly)
    return (b.left, b.top, b.right, b.bottom)


def test_between_two_columns_the_box_spans_their_north_south_extent():
    b = _board(_columns())
    b.keepout(Inside(Part("u1")), "in", why="no copper between the columns")
    b.place(Part("u1"), at=Location(30.0, 25.0))
    # the columns' inner edges at -1.5 and 1.5; no rows, so the pads' own extent -1.25 .. 1.25
    assert _box(b.resolve()) == pytest.approx((28.5, 23.75, 31.5, 26.25), abs=1e-6)


def test_inside_a_ring_each_side_is_its_own_rows_inner_edge():
    b = _board(_ring())
    b.keepout(Inside(Part("u1")), "in", why="nothing under the part")
    b.place(Part("u1"), at=Location(30.0, 25.0))
    assert _box(b.resolve()) == pytest.approx((28.5, 22.5, 32.0, 26.5), abs=1e-6)


def test_it_turns_with_its_part():
    """Turned 90 as a part turns (counter-clockwise on screen): the part's
    own x runs up the board and its own y runs east, (x, y) -> (y, -x)."""
    b = _board(_ring())
    b.keepout(Inside(Part("u1")), "in", why="nothing under the part")
    b.place(Part("u1"), at=Location(30.0, 25.0), rotation=90)
    assert _box(b.resolve()) == pytest.approx((27.5, 23.0, 31.5, 26.5), abs=1e-6)


def test_on_the_back_it_mirrors_with_its_part():
    b = _board(_ring())
    b.keepout(Inside(Part("u1")), "in", why="nothing under the part")
    b.place(Part("u1"), at=Location(30.0, 25.0), face=Face.BACK)
    assert _box(b.resolve()) == pytest.approx((28.0, 22.5, 31.5, 26.5), abs=1e-6)


def test_a_negative_margin_shrinks_it():
    b = _board(_columns())
    b.keepout(Inside(Part("u1"), margin=-0.25), "in", why="clear of the columns")
    b.place(Part("u1"), at=Location(30.0, 25.0))
    assert _box(b.resolve()) == pytest.approx((28.75, 24.0, 31.25, 26.0), abs=1e-6)


def test_a_positive_margin_grows_it():
    b = _board(_columns())
    b.keepout(Inside(Part("u1"), margin=0.1), "in", why="over the columns' inner edges")
    b.place(Part("u1"), at=Location(30.0, 25.0))
    assert _box(b.resolve()) == pytest.approx((28.4, 23.65, 31.6, 26.35), abs=1e-6)


def test_an_empty_box_is_refused_naming_the_part():
    b = _board(_columns())
    with pytest.raises(ValueError, match="U1"):
        b.keepout(Inside(Part("u1"), margin=-1.5), "in", why="shrunk to nothing")


def test_inside_takes_its_margin_not_keepouts():
    b = _board(_columns())
    with pytest.raises(ValueError, match="Inside"):
        b.keepout(Inside(Part("u1")), "in", margin=0.5, why="x")


def test_inside_refuses_at():
    b = _board(_columns())
    with pytest.raises(ValueError, match="an item shapes its own region"):
        b.keepout(Inside(Part("u1")), "in", at=Location(20.0, 20.0), why="x")


def test_inside_is_of_a_part():
    with pytest.raises(TypeError, match="Part"):
        Inside("u1")
