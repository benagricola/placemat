"""rotations= on a place that is a point (a Pin on a cell's member origin or a part's
pad, a Location): the item stays on the point and its turn is searched, scored as any
search is. rotations= takes a list of angles, a step in degrees or Turns.ANY. Pure:
synthetic boards."""
import math

import pytest

from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Cell, Location, Near, PadRef, Part, Pin, Turns
from tests.fixtures import board_geometry, footprint

POINT = Location(40.0, 40.0)


def _board(settings=None, link=True, **kw):
    """Cell `c`: member w1 (pad 1 on A at its west end) and w2, 4 mm along w1's local y. `r1` stands
    east of the point with its pad 1 on A, so the bearing that shortens the link has w1's pad 1 east."""
    fps = [footprint("W1", 40, 40, w=4, h=1, inst="c.w1", nets=("A", "C"), cell="c"),
           footprint("W2", 40, 44, w=4, h=1, inst="c.w2", nets=("D", "E"), cell="c"),
           footprint("R1", 60, 40, w=3, h=1.3, inst="r1", nets=("A" if link else "Z", "GND"))]
    b = Board(board_geometry(fps, cells=["c"], width=80, height=80, **kw), edge_margin=1.0, keep_going=True,
              **({"settings": settings} if settings else {}))
    b.place(Part("r1"), at=Location(60, 40))
    return b


def _pad(plan, ref, number):
    return plan.occupancy.pad_location(ref, number)


def _gap(plan):
    a, b = _pad(plan, "W1", "1"), _pad(plan, "R1", "1")
    return math.hypot(a.x - b.x, a.y - b.y)


def _origin(plan, ref):
    at = plan.occupancy.items[ref].reference.location
    return Location(round(at.x, 5), round(at.y, 5))


# --------------------------------------------------------------- the turns

def test_a_step_and_turns_any_and_a_range_are_the_same_turns():
    seen = []
    for rotations in (5, Turns.ANY, range(0, 360, 5)):
        b = _board()
        b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=rotations)
        seen.append(b._intents[-1].rotations)
    assert seen[0] == seen[1] == seen[2] == tuple(float(r) for r in range(0, 360, 5))


def test_the_step_of_turns_any_is_a_setting():
    b = _board(Settings(place_bearing_step=90.0))
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=Turns.ANY)
    assert b._intents[-1].rotations == (0.0, 90.0, 180.0, 270.0)


@pytest.mark.parametrize("bad", [0, -5, 361, True])
def test_a_step_that_cannot_walk_the_circle_is_refused(bad):
    b = _board()
    with pytest.raises(ValueError, match="step"):
        b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=bad)


def test_a_near_hint_takes_a_step_too():
    b = _board()
    b.place(Part("c.w1"), at=Near(Location(40, 40), rotations=90))
    assert b._intents[-1].rotations == (0.0, 90.0, 180.0, 270.0)


# --------------------------------------------------------------- a cell on a point

def test_a_cell_pinned_by_a_members_origin_takes_the_bearing_that_shortens_its_link():
    b = _board()
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=range(0, 360, 5))
    plan = b.resolve()
    assert plan.placement("c").rotation == 180
    assert _origin(plan, "W1") == POINT
    assert _pad(plan, "W1", "1").x > 40.0
    assert not [f for f in plan.findings if "unplaced" in str(f)]


def test_a_bearing_between_the_right_angles_can_win():
    """R1 is set off the point's row, so the best bearing is not a multiple of 90."""
    fps = [footprint("W1", 40, 40, w=4, h=1, inst="c.w1", nets=("A", "C"), cell="c"),
           footprint("R1", 60, 55, w=3, h=1.3, inst="r1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, cells=["c"], width=80, height=80), edge_margin=1.0, keep_going=True)
    b.place(Part("r1"), at=Location(60, 55))
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=Turns.ANY)
    plan = b.resolve()
    turn = plan.placement("c").rotation
    assert turn % 90 != 0
    assert _origin(plan, "W1") == POINT
    a, r = _pad(plan, "W1", "1"), _pad(plan, "R1", "1")
    # the pad stands on the line from the point toward R1's pad, within a step
    want = math.degrees(math.atan2(r.y - 40.0, r.x - 40.0))
    got = math.degrees(math.atan2(a.y - 40.0, a.x - 40.0))
    assert abs((want - got + 180) % 360 - 180) <= 5.0 + 1e-6


def test_with_nothing_to_pull_it_the_declared_turn_stays():
    b = _board(link=False)
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotation=90, rotations=Turns.ANY)
    assert b.resolve().placement("c").rotation == 90


def test_a_keepout_over_a_bearing_bars_it():
    free = _board()
    free.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=range(0, 360, 5))
    best = free.resolve()
    assert best.placement("c").rotation == 180
    w2 = best.occupancy.items["W2"].body.center             # where the cell's other member lies at the best bearing
    b = _board()
    b.keepout(Circle(3.0), "arms", at=w2, why="where the arms join")
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=range(0, 360, 5))
    plan = b.resolve()
    turn = plan.placement("c").rotation
    assert turn != 180
    assert _origin(plan, "W1") == POINT
    assert not [f for f in plan.findings if "keepout" in str(f) or "unplaced" in str(f)]
    # still leaning to R1 rather than away from it
    assert _gap(plan) < _gap(_resolved_at(0))


def _resolved_at(turn):
    b = _board()
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotation=turn)
    return b.resolve()


def test_a_push_costs_the_bearings_that_stand_near_the_source():
    fps = [footprint("W1", 40, 40, w=4, h=1, inst="c.w1", nets=("A", "C"), cell="c"),
           footprint("M1", 46, 40, w=1, h=1, inst="m1", nets=("X", "Y"))]
    b = Board(board_geometry(fps, cells=["c"], width=80, height=80), edge_margin=1.0, keep_going=True)
    b.place(Part("m1"), at=Location(46, 40))
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=Turns.ANY)
    b.push(PadRef(Part("c.w1"), 2), from_=Part("m1"), falloff=2, reference=(1.0, 1.0), limit=0.1)
    plan = b.resolve()
    pad = _pad(plan, "W1", "2")
    assert math.hypot(pad.x - 46.0, pad.y - 40.0) > 5.9      # at 0 degrees it is 4.6 from the source


def test_with_every_bearing_refused_the_cell_is_unplaced():
    b = _board()
    b.keepout(Circle(12.0), "all", at=POINT, why="nothing may stand here")
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=Turns.ANY)
    plan = b.resolve()
    assert plan.placement("c") is None
    assert [f for f in plan.findings if f.startswith("c: no bearing")]


def test_a_rule_area_of_the_cells_own_follows_the_bearing_taken():
    """A region the cell's module brings (a rule area on its generated board) is moved with the cell
    to the bearing the search takes, as it is with any placed cell."""
    import dataclasses

    from placemat.board_geometry import RuleArea
    from placemat.values import CopperLayer
    fps = [footprint("W1", 40, 40, w=4, h=1, inst="c.w1", nets=("A", "C"), cell="c"),
           footprint("W2", 40, 44, w=4, h=1, inst="c.w2", nets=("D", "E"), cell="c"),
           footprint("R1", 60, 40, w=3, h=1.3, inst="r1", nets=("A", "GND"))]
    g = board_geometry(fps, cells=["c"], width=80, height=80)
    around_w2 = ((38.0, 43.0), (42.0, 43.0), (42.0, 45.0), (38.0, 45.0))
    g = dataclasses.replace(g, rule_areas=(RuleArea("keepout near_w2_1", "c", around_w2, frozenset([CopperLayer.F]),
                                                    frozenset(["parts"])),))
    b = Board(g, edge_margin=1.0, keep_going=True)
    b.place(Part("r1"), at=Location(60, 40))
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=range(0, 360, 5))
    plan = b.resolve()
    assert plan.placement("c").rotation == 180
    (res,) = [r for r in plan.occupancy.reservations if r.source == "cell:c"]
    xs, ys = [p[0] for p in res.poly], [p[1] for p in res.poly]
    body = plan.occupancy.items["W2"].body.center
    assert (sum(xs) / len(xs), sum(ys) / len(ys)) == pytest.approx((body.x, body.y), abs=0.01)


# --------------------------------------------------------------- a part on a point

def test_a_part_pinned_by_its_pad_on_a_point_takes_the_bearing_too():
    fps = [footprint("L1", 30, 30, w=4, h=1, inst="l1", nets=("A", "C")),
           footprint("R1", 60, 40, w=3, h=1.3, inst="r1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=1.0, keep_going=True)
    b.place(Part("r1"), at=Location(60, 40))
    b.place(Part("l1"), at=Pin(1, 30.0, 30.0), rotations=Turns.ANY)
    plan = b.resolve()
    pad = _pad(plan, "L1", "1")
    assert (pad.x, pad.y) == pytest.approx((30.0, 30.0), abs=1e-6)
    far = _pad(plan, "L1", "2")
    assert math.hypot(pad.x - 60, pad.y - 40) < math.hypot(far.x - 60, far.y - 40)      # its far pad is the one turned away


# --------------------------------------------------------------- what stays as it was

def test_a_fixed_turn_without_rotations_is_laid_once_as_before():
    b = _board()
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotation=90)
    plan = b.resolve()
    assert plan.placement("c").rotation == 90
    assert _origin(plan, "W1") == POINT


def test_the_item_waits_its_turn_like_any_searched_item():
    b = _board()
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=Turns.ANY)
    assert not b._intents[-1].freedom.decided


def test_an_item_placed_beside_the_cell_rides_it_to_the_bearing_it_takes():
    from placemat.values import Beside, Edge
    fps = [footprint("W1", 40, 40, w=4, h=1, inst="c.w1", nets=("A", "C"), cell="c"),
           footprint("R1", 60, 40, w=3, h=1.3, inst="r1", nets=("A", "GND")),
           footprint("R2", 10, 10, w=2, h=1, inst="r2", nets=("Q", "GND"))]
    b = Board(board_geometry(fps, cells=["c"], width=80, height=80), edge_margin=1.0, keep_going=True)
    b.place(Part("r1"), at=Location(60, 40))
    b.place(Cell("c"), at=Pin(Part("c.w1"), 40.0, 40.0), rotations=range(0, 360, 5))
    b.place(Part("r2"), at=Beside(Cell("c"), Edge.NORTH, gap=0.5))
    plan = b.resolve()
    assert plan.placement("c").rotation == 180
    cell, r2 = plan.occupancy.reach_box(b._intents[1].item, plan.placement("c")), plan.occupancy.items["R2"].body
    assert r2.bottom <= cell.top + 1e-6
    assert not [f for f in plan.findings if "unplaced" in f.kind or "rider" in str(f)]
