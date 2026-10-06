"""board.track(..., bend=Bend.START/END/BOTH): which end of an off-grid leg
takes its 45. Unset, the planner's own choice (route_leg's scoring) stays
exactly as before - test_copper.py already covers that. Pure."""
from placemat.copper import route_leg
from placemat.layout import Board
from placemat.copper import Track
from placemat.values import Bend, CopperLayer, Location, Net
from tests.fixtures import board_geometry


def _legs(b):
    return [op for op in b.resolve().copper if isinstance(op, Track)]


def test_unset_bend_keeps_the_planners_own_choice():
    """(0,0) to (10,3): with no bend, and nothing else deciding, the tool
    already prefers the 45 at the start (test_copper.py pins this)."""
    b = Board(board_geometry([], width=60, height=60, extra_nets=["MID"]), edge_margin=1.0)
    b.track(Net("MID"), [Location(0, 0), Location(10, 3)], layer=CopperLayer.F, width=0.3)
    assert [(t.start, t.end) for t in _legs(b)] == [(Location(0, 0), Location(3, 3)), (Location(3, 3), Location(10, 3))]


def test_bend_start_puts_the_45_at_the_first_point():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["MID"]), edge_margin=1.0)
    b.track(Net("MID"), [Location(0, 0), Location(10, 3)], layer=CopperLayer.F, width=0.3, bend=Bend.START)
    legs = _legs(b)
    assert [(t.start, t.end) for t in legs] == [(Location(0, 0), Location(3, 3)), (Location(3, 3), Location(10, 3))]
    diag = legs[0]
    assert abs(abs(diag.end.x - diag.start.x) - abs(diag.end.y - diag.start.y)) < 1e-9


def test_bend_end_puts_the_45_at_the_last_point_instead():
    """Forced against the planner's own default (START, above): the shape
    is genuinely different, not a no-op keyword."""
    b = Board(board_geometry([], width=60, height=60, extra_nets=["MID"]), edge_margin=1.0)
    b.track(Net("MID"), [Location(0, 0), Location(10, 3)], layer=CopperLayer.F, width=0.3, bend=Bend.END)
    legs = _legs(b)
    assert [(t.start, t.end) for t in legs] == [(Location(0, 0), Location(7, 0)), (Location(7, 0), Location(10, 3))]
    diag = legs[1]
    assert abs(abs(diag.end.x - diag.start.x) - abs(diag.end.y - diag.start.y)) < 1e-9


def test_bend_both_puts_a_45_at_each_end_with_a_straight_between():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["MID"]), edge_margin=1.0)
    b.track(Net("MID"), [Location(0, 0), Location(10, 3)], layer=CopperLayer.F, width=0.3, bend=Bend.BOTH)
    legs = _legs(b)
    assert len(legs) == 3
    diag0 = abs(abs(legs[0].end.x - legs[0].start.x) - abs(legs[0].end.y - legs[0].start.y)) < 1e-9
    diag2 = abs(abs(legs[2].end.x - legs[2].start.x) - abs(legs[2].end.y - legs[2].start.y)) < 1e-9
    straight1 = legs[1].start.y == legs[1].end.y or legs[1].start.x == legs[1].end.x
    assert diag0 and diag2 and straight1
    assert legs[0].start == Location(0, 0) and legs[2].end == Location(10, 3)


def test_bend_has_no_effect_on_a_leg_already_on_the_45_grid():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["MID"]), edge_margin=1.0)
    b.track(Net("MID"), [Location(0, 0), Location(10, 10)], layer=CopperLayer.F, width=0.3, bend=Bend.END)
    assert len(_legs(b)) == 1                # a true 45 needs no bend at all


def test_a_bend_that_is_not_the_enum_is_refused():
    import pytest
    b = Board(board_geometry([], width=60, height=60, extra_nets=["MID"]), edge_margin=1.0)
    with pytest.raises(TypeError):
        b.track(Net("MID"), [Location(0, 0), Location(10, 3)], layer=CopperLayer.F, bend="start")


def test_route_leg_bend_matches_only_the_candidates_that_fit():
    """Unit-level: bend restricts route_leg's own candidate pool before its
    usual turns/length/tie scoring runs."""
    start = route_leg(Location(0, 0), Location(10, 4), False, False, None, None, None, Bend.START)
    end = route_leg(Location(0, 0), Location(10, 4), False, False, None, None, None, Bend.END)
    both = route_leg(Location(0, 0), Location(10, 4), False, False, None, None, None, Bend.BOTH)
    assert len(start) == 3 and start[1] == Location(4, 4)
    assert len(end) == 3 and end[1] == Location(6, 0)
    assert len(both) == 4


def _off(point, r):
    """A leg predicate: every leg stays `r` from `point`."""
    import math

    def keeps(p, q):
        dx, dy = q.x - p.x, q.y - p.y
        t = max(0.0, min(1.0, ((point[0] - p.x) * dx + (point[1] - p.y) * dy) / (dx * dx + dy * dy or 1.0)))
        return math.hypot(p.x + t * dx - point[0], p.y + t * dy - point[1]) >= r
    return keeps


def test_route_leg_weighs_the_edge_with_other_copper_down_to_a_finer_detour():
    """Unit-level: a pad at (2.2, -0.3) and an edge corner at (0.3, 0.6) leave no way at the quarters that keeps clear
    of both; a straight out along x of a sixteenth of the diagonal's reach, then the 45, does."""
    a, b = Location(0, 0), Location(8, 9)
    pad, corner = _off((2.2, -0.3), 0.6), _off((0.3, 0.6), 0.6)
    got = route_leg(a, b, False, False, None, None, pad, edge=corner)
    assert [(p.x, p.y) for p in got] == [(0, 0), (1.0, 0.0), (8.0, 7.0), (8, 9)]
    # without the edge, the planner's own way is kept: one clear of the pad
    alone = route_leg(a, b, False, False, None, None, pad)
    assert all(pad(p, q) for p, q in zip(alone, alone[1:])) and not all(corner(p, q) for p, q in zip(alone, alone[1:]))
