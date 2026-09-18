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
