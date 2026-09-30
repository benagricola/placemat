"""A label on an item that found no place is not drawn: a finding says so,
and the run goes on, as the item's own refusal does."""
from placemat.layout import Board
from placemat.values import Location, Near, Part
from tests.fixtures import board_geometry, footprint


def test_a_label_on_an_unplaced_part_is_a_finding_not_an_error():
    fps = [footprint("U1", 10, 10, w=30, h=30, inst="u1", nets=("A", "B")),         # larger than the board
           footprint("R1", 10, 10, w=2, h=1, inst="r1", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=20, height=20), edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Near(Location(10, 10), radius=2))
    b.place(Part("r1"), at=Location(10, 10))
    b.label(Part("u1"), "BOOT")
    plan = b.resolve()
    assert plan.step("u1").placement is None
    assert [f for f in plan.findings if f.kind == "label" and "BOOT" in f and "no place" in f], list(plan.findings)
