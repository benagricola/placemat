"""Beside(item, side, slide=True): a part whose aligned spot is taken by something already placed keeps its standoff and
its rotation and slides along the side to the nearest spot that stands, either way, within place.beside_slide_reach.
Pure: synthetic boards."""
import dataclasses

import pytest

from placemat import lock as L
from placemat import reuse
from placemat.board_geometry import NetClass
from placemat.geometry import Transform
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Beside, Edge, Location, Mid, PadRef, Part, SideOf, Turned
from tests.escape_fixtures import CLEAR, DRILL, TRACK, VIA, qfn
from tests.fixtures import board_geometry, footprint

# ------------------------------------------------------------------ compass side


def _compass(blocker_y, blocker_h=1.0, slide=True, settings=None):
    """U1 at (20, 20), R1 east of it aligned on its middle (y 20); a blocker over the north part of where R1 stands (its
    south edge at blocker_y + blocker_h / 2)."""
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 40, 40, w=3, h=1.3, inst="r1", nets=("C", "GND")),
           footprint("T1", 23.7, blocker_y, w=0.4, h=blocker_h, inst="t1", nets=("D", "E"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=settings or Settings(), keep_going=True)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("t1"), at=Location(23.7, blocker_y))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST, slide=slide))
    return b


def test_a_blocked_part_slides_along_the_side_to_the_nearest_clear_spot_keeping_its_standoff():
    free = _compass(blocker_y=100.0, slide=False).resolve()           # the blocker off the board's reach: the aligned spot
    plain = _compass(blocker_y=19.6)
    plan = plain.resolve()
    assert plan.step("r1").unplaced is None
    free_box, box, t1 = free.box("r1"), plan.box("r1"), plan.box("t1")
    assert box.left == pytest.approx(free_box.left, abs=1e-6)         # the standoff from u1 is unchanged
    assert box.center.y != pytest.approx(free_box.center.y, abs=1e-3)
    # the blocker reaches 0.5 mm north of the aligned spot's middle, 0.1 mm south of it: the nearer way is south
    assert box.center.y > free_box.center.y
    assert box.top > t1.bottom
    assert plan.placement("r1").rotation == 0.0
    assert not [f for f in plan.findings if f.kind in ("fixed", "unplaced")]


def test_a_part_with_both_ways_as_near_slides_the_positive_way():
    plan = _compass(blocker_y=20.0).resolve()
    free = _compass(blocker_y=100.0, slide=False).resolve()
    assert plan.box("r1").center.y > free.box("r1").center.y
    assert plan.box("r1").top > plan.box("t1").bottom


def test_without_slide_the_part_is_moved_out_as_before():
    wide = dataclasses.replace(Settings(), place_beside_reach=4.0)
    plan = _compass(blocker_y=19.6, slide=False, settings=wide).resolve()
    free = _compass(blocker_y=100.0, slide=False).resolve()
    assert plan.box("r1").center.y == pytest.approx(free.box("r1").center.y, abs=1e-6)
    assert plan.box("r1").left > free.box("r1").left + 0.1
    assert "slid" not in plan.step("r1").note


def test_nothing_within_reach_falls_back_to_the_move_out_and_reports_as_without_slide():
    plans = [_compass(blocker_y=20.0, blocker_h=20.0, slide=s).resolve() for s in (False, True)]
    assert plans[0].placement("r1") == plans[1].placement("r1")
    assert [str(f) for f in plans[0].findings] == [str(f) for f in plans[1].findings]
    assert "slid" not in plans[1].step("r1").note


def test_the_reach_is_a_setting():
    near = dataclasses.replace(Settings(), place_beside_slide_reach=0.1)
    plan = _compass(blocker_y=19.6, settings=near).resolve()
    assert "slid" not in plan.step("r1").note


def test_the_step_note_says_how_far_it_slid_and_what_was_in_the_way():
    plan = _compass(blocker_y=19.6).resolve()
    free = _compass(blocker_y=100.0, slide=False).resolve()
    moved = abs(plan.box("r1").center.y - free.box("r1").center.y)
    (n,) = [n for n in plan.step("r1").notes if n["kind"] == "beside_slid"]
    assert n["mm"] == pytest.approx(moved, abs=1e-5)
    assert n["clear_of"] == ["T1"]
    assert "slid %.2f mm along its side, clear of T1" % moved in plan.step("r1").note


# ------------------------------------------------------------------ turned frame

NETS = {21: "SIG_A", 22: "SIG_B", 23: "SIG_C", 24: "SIG_D"}
MCU = Part("pd")
SIDE = SideOf(PadRef(MCU, 22))
MID = Mid(PadRef(MCU, 22), PadRef(MCU, 23))


def _turned(turn, blocker=None, slide=True, settings=None):
    fps = [qfn(nets=NETS), footprint("C1", 5, 5, w=2.0, h=1.0, inst="cap", nets=("SIG_B", "GND"))]
    if blocker is not None:
        fps.append(footprint("T1", 5, 20, w=1.0, h=0.6, inst="blk", nets=("N1", "N2")))
    geom = board_geometry(fps, width=80, height=80, clearance=CLEAR)
    classes = {n: NetClass("Default", TRACK, CLEAR, VIA, DRILL) for n in geom.nets}
    b = Board(dataclasses.replace(geom, netclasses=classes), edge_margin=1.0, via_size=VIA, via_drill=DRILL,
              settings=settings or Settings(), keep_going=True)
    b.place(MCU, at=Location(40, 40), rotation=turn)
    if blocker is not None:
        b.place(Part("blk"), at=Location(*blocker))
    b.place(Part("cap"), at=Beside(MCU, SIDE, align=(Mid(1, 2), MID), gap=0.5, slide=slide), rotation=Turned(MCU, 0.0))
    return b


def _frame(turn, p):
    return Transform.rotate(-turn).apply((p.x, p.y))


@pytest.mark.parametrize("turn", [0.0, 45.0])
def test_a_turned_part_slides_along_the_row_keeping_its_rotation_and_its_standoff(turn):
    free = _turned(turn).resolve()
    spot = free.placement("cap").location
    # a blocker a little north of the row's middle, in the row's frame, so the nearer way is south of it
    bx, by = Transform.rotate(turn).apply((_frame(turn, spot)[0], _frame(turn, spot)[1] - 0.5))
    plan = _turned(turn, blocker=(bx, by)).resolve()
    assert not [f for f in plan.findings if f.kind in ("fixed", "unplaced")], plan.findings
    assert plan.placement("cap").rotation == pytest.approx(turn)
    a, c = _frame(turn, spot), _frame(turn, plan.placement("cap").location)
    assert c[0] == pytest.approx(a[0], abs=1e-5)                     # the standoff in the part's frame
    assert c[1] > a[1] + 0.1                                         # slid along the row, away from the blocker
    (n,) = [n for n in plan.step("cap").notes if n["kind"] == "beside_slid"]
    assert n["mm"] == pytest.approx(c[1] - a[1], abs=1e-4)
    assert n["clear_of"] == ["T1"]


def test_a_turned_part_with_nothing_clear_within_reach_is_as_without_slide():
    free = _turned(45.0).resolve()
    spot = free.placement("cap").location
    plans = [_turned(45.0, blocker=(spot.x, spot.y), slide=s, settings=dataclasses.replace(
        Settings(), place_beside_slide_reach=0.05)).resolve() for s in (False, True)]
    assert plans[0].placement("cap") == plans[1].placement("cap")
    assert "slid" not in plans[1].step("cap").note


# ------------------------------------------------------------------ declaration


def test_slide_is_checked_and_left_out_of_a_declaration_that_does_not_use_it():
    with pytest.raises(TypeError, match="slide"):
        Beside(Part("u1"), Edge.EAST, slide="yes")
    plain = reuse.canonical(Beside(Part("u1"), Edge.EAST))
    assert "slide" not in plain
    assert reuse.canonical(Beside(Part("u1"), Edge.EAST, slide=True)) != plain
    assert Beside(Part("u1"), Edge.EAST, slide=False) == Beside(Part("u1"), Edge.EAST)


def test_a_lock_entry_digest_of_a_beside_without_slide_does_not_carry_the_field():
    plain, slid = (_compass(blocker_y=100.0, slide=s) for s in (False, True))
    key = "r1"
    digests = []
    for b in (plain, slid):
        i = next(x for x in b._placements() if x.key == key)
        digests.append(L.declaration_digest(b, i))
    assert digests[0] != digests[1]
    i = next(x for x in plain._placements() if x.key == key)
    assert not [f for f in dataclasses.fields(i.beside) if f.name == "slide" and not reuse.omitted(i.beside, f)]
