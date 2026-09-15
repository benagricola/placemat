"""A board outline of any shape: arcs that pass through a point, the runs of
an edge that face a direction, and what the board holds."""
import math

import pytest

from placemat.outline import Arc, Outline, rect_outline
from placemat.values import Box, Edge, Location


def test_an_arc_passes_through_its_via_point_and_ends_where_told():
    o = Outline.of([(0.0, 20.0), Arc(to=(40.0, 20.0), via=(20.0, 0.0)), (40.0, 40.0), (0.0, 40.0)])
    loop = o.loops[0]
    assert loop[0] == (0.0, 20.0)
    assert (40.0, 20.0) in loop and (40.0, 40.0) in loop
    apex = min(loop, key=lambda p: p[1])
    assert apex[1] == pytest.approx(0.0, abs=0.02)          # it really goes up through the via
    for x, y in loop[:len(loop) - 2]:                        # every arc point on the circle through the three
        assert math.hypot(x - 20.0, y - 20.0) == pytest.approx(20.0, abs=0.02)


def test_a_rectangle_has_one_run_per_side_facing_its_own_way():
    o = rect_outline(Box(0.0, 0.0, 40.0, 30.0))
    for edge, facing, length in [(Edge.NORTH, 0.0, 40.0), (Edge.EAST, 90.0, 30.0),
                                 (Edge.SOUTH, 180.0, 40.0), (Edge.WEST, 270.0, 30.0)]:
        (run,) = o.runs(edge)
        assert run.facing == pytest.approx(facing) and run.length == pytest.approx(length)
        assert run.straight
    (north,) = o.runs(Edge.NORTH)
    point, out = north.at(north.length / 2.0)
    assert point == Location(20.0, 0.0) and out == pytest.approx(0.0)


def test_a_rounded_top_is_one_run_that_faces_north_and_bends():
    o = Outline.of([(0.0, 20.0), Arc(to=(40.0, 20.0), via=(20.0, 0.0)), (40.0, 40.0), (0.0, 40.0)])
    runs = o.runs(Edge.NORTH)
    assert len(runs) == 1
    run = runs[0]
    assert not run.straight
    assert run.length == pytest.approx(math.pi * 20.0 / 2.0, rel=0.02)   # the northern half of the arc
    point, out = run.at(run.length / 2.0)
    assert point.x == pytest.approx(20.0, abs=0.1) and point.y == pytest.approx(0.0, abs=0.1)
    assert out == pytest.approx(0.0, abs=0.2)                             # its outward side points north
    assert run.curvature(run.length / 2.0) == pytest.approx(1.0 / 20.0, rel=0.1)


def test_a_direction_may_select_several_runs():
    """A board with a notch in its top edge has two stretches facing north."""
    o = Outline.of([(0.0, 0.0), (15.0, 0.0), (15.0, 8.0), (25.0, 8.0), (25.0, 0.0),
                    (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)])
    runs = o.runs(Edge.NORTH, within=20.0)
    # three, not two: the notch's own floor faces north as much as the top does,
    # which is why a direction picks runs and a script says which it meant.
    assert [round(r.length, 3) for r in runs] == [15.0, 10.0, 15.0]
    assert all(r.facing == pytest.approx(0.0) for r in runs)
    (foot,) = o.runs(Edge.SOUTH, within=20.0)
    assert round(foot.length, 3) == 40.0
    assert [round(r.length, 3) for r in o.runs(Edge.EAST, within=20.0)] == [8.0, 30.0]   # a notch wall, then the side: path order


def test_an_outline_says_what_it_holds():
    o = Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)],
                   holes=[[(18.0, 13.0), (22.0, 13.0), (22.0, 17.0), (18.0, 17.0)]])
    assert o.why_not(Box(5.0, 5.0, 10.0, 10.0), 0.5) is None
    assert "outside" in o.why_not(Box(45.0, 5.0, 50.0, 10.0), 0.5)
    assert "board" in o.why_not(Box(0.2, 5.0, 4.0, 10.0), 0.5)            # inside, but into the keep-in
    assert "cutout" in o.why_not(Box(14.0, 14.0, 17.9, 16.0), 0.5)        # up against the hole
    assert "cutout" in o.why_not(Box(19.0, 14.0, 21.0, 16.0), 0.5)        # in the hole
    assert o.area == pytest.approx(40.0 * 30.0 - 16.0)


def test_the_centre_of_a_board_is_its_box_and_the_centroid_is_its_area():
    """An L: the middle of the box is not where the copper is, so a script
    can ask for either."""
    o = Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 10.0), (10.0, 10.0), (10.0, 30.0), (0.0, 30.0)])
    assert o.centre == Location(20.0, 15.0)
    assert o.centroid.x < 20.0 and o.centroid.y < 15.0
    assert o.area == pytest.approx(40.0 * 10.0 + 10.0 * 20.0)


def test_a_plane_follows_the_outline_inset():
    o = rect_outline(Box(0.0, 0.0, 40.0, 30.0))
    assert set(o.polygon(0.4)) == {(0.4, 0.4), (39.6, 0.4), (39.6, 29.6), (0.4, 29.6)}


def walk_every_segment(o, box, margin):
    """What the keep-in test means, written out: the box centre inside the
    board and outside every cutout, and no segment of any loop nearer than
    the margin. The reference the fast path must agree with."""
    from placemat.outline import _inside, _segment_box
    if not _inside(o.loops[0], box.center):
        return "outside the board"
    for hole in o.loops[1:]:
        if _inside(hole, box.center):
            return "inside a cutout"
    for n, loop in enumerate(o.loops):
        for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]):
            if _segment_box(x1, y1, x2, y2, box) < margin - 1e-5:
                return "past the %s keep-in (%.2f mm)" % ("board's" if n == 0 else "cutout's", margin)
    return None


def shapes_to_try():
    from placemat.outline import Arc
    disc = [(0.0, 18.5), Arc(to=(37.0, 18.5), via=(18.5, 0.0)), Arc(to=(0.0, 18.5), via=(18.5, 37.0))]
    notched = [(0.0, 18.5), Arc(to=(37.0, 18.5), via=(18.5, 0.0)),
               (24.0, 30.0), (24.0, 37.0), (13.0, 37.0), (13.0, 30.0), Arc(to=(0.0, 18.5), via=(2.0, 28.0))]
    return [("a disc", Outline.of(disc)),
            ("a notched disc", Outline.of(notched)),
            ("a disc with a bore", Outline.of(disc, holes=[list(rect_outline(Box(16.0, 16.0, 21.0, 21.0)).loops[0])])),
            ("an L", Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 10.0), (10.0, 10.0), (10.0, 30.0), (0.0, 30.0)]))]


def test_the_keep_in_test_says_what_walking_every_segment_says():
    """Whatever the shape, and wherever the box: inside, outside, over the
    edge, in a cutout, or past the board's own bbox."""
    for name, o in shapes_to_try():
        b = o.box
        for i in range(-1, 22):
            for j in range(-1, 22):
                x = b.left + (b.width + 6.0) * i / 21.0 - 3.0
                y = b.top + (b.height + 6.0) * j / 21.0 - 3.0
                for w, h in ((3.0, 2.0), (0.4, 0.4), (9.0, 6.0)):
                    box = Box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
                    for margin in (0.0, 0.5, 2.0):
                        assert o.why_not(box, margin) == walk_every_segment(o, box, margin), \
                            "%s: %s at margin %g" % (name, box, margin)


def test_the_keep_in_test_costs_little_enough_to_search_with():
    """A search tries tens of thousands of candidates, and every one of them
    asks this question, so walking the whole outline each time is what makes
    a run take minutes. The board's shape never changes during a run."""
    import time
    o = dict(shapes_to_try())["a disc"]
    box = Box(14.0, 14.0, 17.0, 16.0)                     # well inside: nothing near it
    o.why_not(box, 0.5)                                   # whatever it builds, build it now
    n = 2000
    start = time.perf_counter()
    for _ in range(n):
        o.why_not(box, 0.5)
    each = (time.perf_counter() - start) / n * 1e6
    assert each < 25.0, "%.1f us per candidate: %d segments are being walked" % (each, len(o.loops[0]))
