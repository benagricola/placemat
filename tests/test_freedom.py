"""Degrees of freedom. `edge=` with `along=` is fixed on that edge: zero
freedom, it never moves and two such things that meet are an invalid
layout. `edge=` alone is one degree of freedom: it slides along its edge,
sits at the edge's midpoint when alone, spreads evenly with its fellows,
and moves aside for anything already there. A searched item has two."""
import pytest

from placemat.layout import Board, PlacementCollision
from placemat.values import Cell, Edge, Location, Part, Priority
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j1", nets=("A", "B")),
           footprint("J2", 5, 15, w=8, h=3, inst="j2", nets=("C", "D")),
           footprint("J3", 5, 25, w=8, h=3, inst="j3", nets=("E", "F")),
           footprint("U1", 40, 40, w=20, h=10, cell="mcu", inst="mcu.u", nets=("A", "C"))]
    return Board(board_geometry(fps, cells=["mcu"], width=60, height=60), edge_margin=1.0)


def test_an_edge_item_with_no_position_sits_at_the_midpoint_of_its_edge():
    b = make_board()
    b.place(Part("j1"), edge=Edge.NORTH)
    plan = b.resolve()
    box = plan.box("j1")
    assert box.center.x == pytest.approx(30.0) and box.top == pytest.approx(1.0)
    assert plan.step("j1").priority is Priority.DEFAULT           # it is searched, along its edge


def test_edge_items_with_no_position_spread_evenly_along_their_edge():
    b = make_board()
    b.place(Part("j1"), edge=Edge.NORTH)
    b.place(Part("j2"), edge=Edge.NORTH)
    b.place(Part("j3"), edge=Edge.NORTH)
    plan = b.resolve()
    xs = sorted(plan.box(k).center.x for k in ("j1", "j2", "j3"))
    usable = 60.0 - 2 * 1.0
    assert xs == pytest.approx([1.0 + usable / 4, 1.0 + usable / 2, 1.0 + 3 * usable / 4])


def test_a_free_edge_item_slides_aside_for_a_fixed_one_at_the_midpoint():
    b = make_board()
    b.place(Part("j1"), edge=Edge.NORTH, along=30.0)              # zero freedom: the midpoint is taken
    b.place(Part("j2"), edge=Edge.NORTH)
    b.place(Part("j3"), edge=Edge.NORTH)
    plan = b.resolve()
    j1, j2, j3 = plan.box("j1"), plan.box("j2"), plan.box("j3")
    assert plan.findings == []
    assert j1.center.x == pytest.approx(30.0)
    left, right = sorted((j2, j3), key=lambda x: x.center.x)
    assert right.left >= j1.right and left.right <= j1.left          # one each side, off the fixed one
    assert left.top == pytest.approx(1.0) and right.top == pytest.approx(1.0)


def test_two_fixed_edge_items_that_meet_are_an_invalid_layout():
    b = make_board()
    b.place(Part("j1"), edge=Edge.NORTH, along=30.0)
    b.place(Part("j2"), edge=Edge.NORTH, along=32.0)
    with pytest.raises(PlacementCollision):
        b.resolve()


def test_a_critical_searched_cell_goes_before_free_edge_furniture_and_the_furniture_moves_aside():
    b = make_board()
    b.place(Part("j1"), edge=Edge.NORTH)                            # furniture: one degree of freedom
    b.place(Part("j2"), edge=Edge.NORTH)
    b.place(Cell("mcu"), near=Location(30, 7), radius=1.0, priority=Priority.HIGH)   # wants the north middle
    plan = b.resolve()
    order = [s.item for s in plan.steps]
    assert order.index("mcu") < order.index("j1") and order.index("mcu") < order.index("j2")
    mcu = plan.box("mcu")
    assert plan.findings == []
    for k in ("j1", "j2"):
        assert not plan.box(k).overlaps(mcu)
