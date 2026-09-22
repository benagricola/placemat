"""A searched item's place in the queue is worked out from what it is: how
much board its courtyard needs and how many pins it has, against the rest of
this board. The script may say otherwise. Either way the step says the rank
and the numbers behind it."""
import pytest

from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Cell, Freedom, Location, Part, Priority
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    fps = [footprint("U1", 10, 10, w=14, h=14, cell="mcu", inst="mcu.u", nets=("N0", "N1"))]
    fps += [footprint("C%d" % i, 30 + i, 10, w=1, h=0.5, cell="mcu", inst="mcu.c%d" % i,
                      nets=("N%d" % (2 + i), "GND")) for i in range(8)]
    fps += [footprint("J1", 60, 60, w=8, h=3, inst="j1", nets=("N0", "N2")),
            footprint("J2", 60, 70, w=8, h=3, inst="j2", nets=("N1", "N3")),
            footprint("R1", 80, 80, w=2, h=1, inst="r1", nets=("N9", "GND")),
            footprint("R2", 80, 85, w=2, h=1, inst="r2", nets=("N9", "N30"))]
    return Board(board_geometry(fps, cells=["mcu"], width=80, height=80), edge_margin=1.0, **kw)


def test_the_big_complex_cell_goes_first_and_the_lone_passive_goes_last():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Part("j2"), at=Location(40, 75))
    b.place(Cell("mcu"))
    b.place(Part("r1"))
    b.place(Part("r2"))
    plan = b.resolve()
    order = [s.item for s in plan.steps if s.item in ("mcu", "r1", "r2")]
    assert order[0] == "mcu"


def test_the_step_says_the_rank_and_the_two_measurements():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Cell("mcu"))
    b.place(Part("r1"))
    note = b.resolve().step("mcu").note
    assert "rank 1/" in note and "mm2" in note and "pins" in note


def test_no_percentage_of_the_board_appears_in_a_step():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Cell("mcu"))
    b.place(Part("r1"))
    for s in b.resolve().steps:
        assert "of the board" not in s.note


def test_a_large_sparse_part_outranks_a_small_well_connected_one():
    """The case that stranded two power inductors, a flag tab and a TVS: a big
    part with two pins must not wait behind a shelf of passives that happen to
    sit on a busy net."""
    fps = [footprint("L1", 10, 10, w=6, h=5, inst="l1", nets=("SW", "VOUT"))]
    fps += [footprint("C%d" % i, 30 + i * 2, 40, w=1, h=0.5, inst="c%d" % i, nets=("BUS", "GND"))
            for i in range(10)]
    fps += [footprint("U1", 50, 10, w=4, h=4, inst="u1", nets=("SW", "BUS"))]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=1.0)
    b.place(Part("u1"), at=Location(50, 10))
    b.place(Part("l1"))
    for i in range(10):
        b.place(Part("c%d" % i))
    plan = b.resolve()
    order = [s.item for s in plan.steps if s.kind == "part" and s.item != "u1"]
    assert order[0] == "l1", order


def test_the_script_may_say_otherwise_and_the_step_says_so():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Cell("mcu"), priority=Priority.LOW)
    b.place(Part("r1"), priority=Priority.HIGH)
    plan = b.resolve()
    assert plan.step("mcu").priority is Priority.LOW and "script: low" in plan.step("mcu").note
    assert plan.step("r1").priority is Priority.HIGH and "script: high" in plan.step("r1").note
    order = [s.item for s in plan.steps if s.item in ("mcu", "r1")]
    assert order[0] == "r1"


def test_the_rank_weights_come_from_the_settings():
    fps = [footprint("BIG", 10, 10, w=8, h=8, inst="big", nets=("A", "B")),
           footprint("MANY", 40, 10, w=2, h=2, inst="many", nets=("N0", "N1")),
           footprint("J1", 60, 60, inst="j1", nets=("A", "N0"))]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=1.0,
              settings=Settings(rank_area=1.0, rank_pins=0.0))
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Part("big"))
    b.place(Part("many"))
    order = [s.item for s in b.resolve().steps if s.item in ("big", "many")]
    assert order[0] == "big"


def test_a_decided_placement_has_no_rank_and_no_priority():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    step = b.resolve().step("j1")
    assert step.freedom is Freedom.FIXED and step.priority is None and step.rank is None
