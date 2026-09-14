"""A searched item's priority is worked out from what it is: how much of
the board it needs, how many parts it holds, how many connections tie it
to the rest. The script may say otherwise. Either way the step says the
priority and where it came from, so a wrong one can be seen and set."""
import pytest

from placemat.layout import Board
from placemat.values import Cell, Location, Part, Priority
from tests.fixtures import board_geometry, footprint


def make_board():
    nets = ["N%d" % i for i in range(40)]
    fps = [footprint("U1", 10, 10, w=14, h=14, cell="mcu", inst="mcu.u", nets=("N0", "N1"))]
    fps += [footprint("C%d" % i, 30 + i, 10, w=1, h=0.5, cell="mcu", inst="mcu.c%d" % i, nets=("N%d" % (2 + i), "GND"))
            for i in range(8)]
    fps += [footprint("J1", 60, 60, w=8, h=3, inst="j1", nets=("N0", "N2")),
            footprint("J2", 60, 70, w=8, h=3, inst="j2", nets=("N1", "N3")),
            footprint("R1", 80, 80, w=2, h=1, inst="r1", nets=("N9", "GND")),
            footprint("R2", 80, 85, w=2, h=1, inst="r2", nets=("N9", "N30"))]
    return Board(board_geometry(fps, cells=["mcu"], width=80, height=80), edge_margin=1.0)


def test_a_big_well_connected_cell_is_high_by_itself_and_a_lone_part_is_low():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Part("j2"), at=Location(40, 75))
    b.place(Cell("mcu"))
    b.place(Part("r1"))
    b.place(Part("r2"))
    plan = b.resolve()
    assert plan.step("mcu").priority is Priority.HIGH
    assert "priority high (auto:" in plan.step("mcu").note
    assert plan.step("r1").priority is Priority.LOW and "priority low (auto:" in plan.step("r1").note
    order = [s.item for s in plan.steps if s.item in ("mcu", "r1", "r2")]
    assert order[0] == "mcu"


def test_the_script_may_say_otherwise_and_the_step_says_so():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Cell("mcu"), priority=Priority.LOW)
    b.place(Part("r1"), priority=Priority.HIGH)
    plan = b.resolve()
    assert plan.step("mcu").priority is Priority.LOW and "priority low (script" in plan.step("mcu").note
    assert plan.step("r1").priority is Priority.HIGH and "priority high (script" in plan.step("r1").note


def test_an_unplaced_item_reports_its_priority_and_the_reason_for_it():
    fps = [footprint("U1", 10, 10, w=30, h=30, cell="mcu", inst="mcu.u", nets=("A", "B")),
           footprint("J1", 50, 50, w=8, h=3, inst="j1", nets=("A", "C"))]
    b = Board(board_geometry(fps, cells=["mcu"], width=40, height=40), edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Cell("mcu"), priority=Priority.DEFAULT)
    plan = b.resolve()
    note = plan.step("mcu").note
    assert "UNPLACED" in note and "priority default (script" in note and "would be high" in note
