"""A rotation relative to a part: settled when the item is placed, after
that part. Pure: synthetic boards."""
from placemat import Turned
from placemat.layout import Board
from placemat.values import Location, Near, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("C1", 30, 30, w=2, h=1, inst="c1", nets=("A", "GND")),
           footprint("J1", 5, 5, w=2, h=2, inst="j1", nets=("B", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("j1"), at=Location(5, 5))
    return b


def test_a_turned_rotation_follows_its_part():
    for turn in (0, 90, 270):
        b = _board()
        b.place(Part("u1"), at=Location(20, 20), rotation=turn)
        b.place(Part("c1"), at=Near(PadRef(Part("u1"), 1).local(0.0, -2.5), radius=0),
                rotation=Turned(Part("u1"), 90))
        plan = b.resolve()
        assert plan.placement("c1").rotation == (turn + 90) % 360


def test_an_item_turned_by_a_searched_part_waits_for_it():
    b = _board()
    b.place(Part("c1"), at=Near(PadRef(Part("u1"), 1).local(0.0, -2.5), radius=0),
            rotation=Turned(Part("u1"), 0), priority=Priority.HIGH)
    b.place(Part("u1"), rotations=(90,))
    plan = b.resolve()
    order = [s.item for s in plan.steps]
    assert order.index("u1") < order.index("c1")
    assert plan.placement("c1").rotation == 90
