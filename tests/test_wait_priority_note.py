"""An item never waits for a linked partner of a lower priority tier, so its
step has no wait to explain and no priority set aside."""
from placemat.layout import Board
from placemat.values import LinkWeight, Location, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint


def test_a_high_item_linked_to_a_default_partner_goes_first_and_says_no_wait():
    fps = [footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("B", "C")),
           footprint("C1", 40, 40, w=2, h=1, inst="c1", nets=("C", "D"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=0.5)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), priority=Priority.HIGH)
    b.place(Part("r1"))
    b.link(PadRef(Part("c1"), 1), PadRef(Part("r1"), 2), weight=LinkWeight.SHORT)
    plan = b.resolve()
    assert [s.item for s in plan.steps if s.item in ("c1", "r1")] == ["c1", "r1"]
    note = plan.step("c1").note
    assert "waited" not in note and "set aside" not in note, note
