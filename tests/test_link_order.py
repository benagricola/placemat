"""Of two linked items not yet placed, the one with more placed connections
goes first, so the other is seeded on it rather than on whatever else it
touches."""
from placemat.layout import Board
from placemat.values import Location, PadRef, Part, Priority
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


# ---------------------------------------------------------------- priority tiers
def _tiered_board():
    """f1 fixed, sharing nets P and Q with lo; f2 fixed, sharing P2 with de;
    hi shares nothing placed. So lo pulls hardest, then de, then hi."""
    fps = [footprint("F1", 5, 5, w=2, h=1, inst="f1", nets=("P", "Q")),
           footprint("F2", 5, 35, w=2, h=1, inst="f2", nets=("P2", "R")),
           footprint("HI", 30, 10, w=2, h=1, inst="hi", nets=("M", "N")),
           footprint("DE", 30, 20, w=2, h=1, inst="de", nets=("P2", "M")),
           footprint("LO", 30, 30, w=2, h=1, inst="lo", nets=("P", "Q"))]
    b = Board(board_geometry(fps, width=50, height=40), edge_margin=0.5)
    b.place(Part("f1"), at=Location(5, 5))
    b.place(Part("f2"), at=Location(5, 35))
    return b


def _searched(plan):
    return [s.item for s in plan.steps if s.item in ("hi", "de", "lo", "x1")]


def test_a_high_item_linked_to_a_default_one_with_more_pull_goes_down_with_the_high_tier():
    b = _tiered_board()
    b.place(Part("hi"), priority=Priority.HIGH)
    b.place(Part("de"))
    b.link(PadRef(Part("hi"), 1), PadRef(Part("de"), 2))
    plan = b.resolve()
    assert _searched(plan) == ["hi", "de"]
    note = plan.step("hi").note
    assert "waited" not in note and "set aside" not in note, note


def test_three_tiers_none_waits_for_a_lower_tier():
    """hi is linked to de and de to lo, each partner with more pull. Waits by
    pull alone put lo down first; by tier, none of them waits."""
    b = _tiered_board()
    b.place(Part("hi"), priority=Priority.HIGH)
    b.place(Part("de"))
    b.place(Part("lo"), priority=Priority.LOW)
    b.link(PadRef(Part("hi"), 1), PadRef(Part("de"), 2))
    b.link(PadRef(Part("de"), 1), PadRef(Part("lo"), 1))
    plan = b.resolve()
    assert _searched(plan) == ["hi", "de", "lo"]
    assert not any("waited" in plan.step(k).note for k in ("hi", "de"))
