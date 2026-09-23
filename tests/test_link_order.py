"""Of two linked items not yet placed, the one with more placed connections
goes first, so the other is seeded on it rather than on whatever else it
touches."""
from placemat.layout import Board
from placemat.values import Location, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("Y1", 30, 30, w=2, h=1, inst="y1", nets=("A", "B")),        # pulled by j1
           footprint("X1", 40, 30, w=6, h=4, inst="x1", nets=("B", "C"))]        # larger: ranks first, pulled by nothing placed
    b = Board(board_geometry(fps, width=50, height=40), edge_margin=0.5)
    b.place(Part("j1"), at=Location(5, 20))
    return b


def _order(plan):
    return [s.item for s in plan.steps if s.item in ("x1", "y1")]


def test_without_a_link_the_rank_decides():
    b = _board()
    b.place(Part("x1"))
    b.place(Part("y1"))
    assert _order(b.resolve()) == ["x1", "y1"]


def test_a_linked_item_waits_for_the_partner_that_has_somewhere_to_go():
    b = _board()
    b.link(PadRef(Part("x1"), "B"), PadRef(Part("y1"), "B"))
    b.place(Part("x1"))
    b.place(Part("y1"))
    plan = b.resolve()
    assert _order(plan) == ["y1", "x1"]
    assert "seeded on B" in next(s for s in plan.steps if s.item == "x1").note
    assert "waited for y1" in next(s for s in plan.steps if s.item == "x1").note


def test_linked_items_pulled_equally_keep_the_rank_order():
    fps = [footprint("Y1", 30, 30, w=2, h=1, inst="y1", nets=("A", "B")),
           footprint("X1", 40, 30, w=6, h=4, inst="x1", nets=("B", "C"))]
    b = Board(board_geometry(fps, width=50, height=40), edge_margin=0.5)
    b.link(PadRef(Part("x1"), "B"), PadRef(Part("y1"), "B"))
    b.place(Part("x1"))
    b.place(Part("y1"))
    assert _order(b.resolve()) == ["x1", "y1"]
