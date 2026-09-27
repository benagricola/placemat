"""A searched item placed relative to another searched item's pad goes after
it, whatever their ranks, so its hint is where that pad landed and not where
the generator parked it. Pure: synthetic boards."""
from placemat.layout import Board
from placemat.values import Location, Near, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint


def _board():
    """cin, the larger, would rank before the block whose anchor it is Near."""
    fps = [footprint("U1", 90, 90, w=2, h=2, inst="buck", nets=("VIN", "SW")),
           footprint("L1", 95, 95, w=1, h=1, inst="coil", nets=("SW", "OUT")),
           footprint("C1", 99, 99, w=8, h=6, inst="cin", nets=("VIN", "GND")),
           footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("VIN", "GND"))]
    b = Board(board_geometry(fps, width=60, height=40), edge_margin=0.5)
    b.place(Part("j1"), at=Location(5, 20))
    return b


def _order(plan):
    return [s.item for s in plan.steps]


def test_near_a_block_members_pad_waits_for_the_block():
    b = _board()
    b.place(b.block(Part("buck"), satellites=[(Part("coil"), "SW")], gap=0.5), priority=Priority.HIGH)
    b.place(Part("cin"), at=Near(PadRef(Part("buck"), 1), radius=10.0), priority=Priority.HIGH)
    plan = b.resolve()
    assert _order(plan).index("block buck") < _order(plan).index("cin")
    assert plan.placement("cin") is not None
    assert plan.placement("cin").location.distance(plan.occupancy.pad_location("U1", "1")) <= 10.0 + 1e-6


def test_near_a_searched_parts_pad_waits_for_the_part():
    b = _board()
    b.place(Part("buck"), priority=Priority.HIGH)
    b.place(Part("cin"), at=Near(PadRef(Part("buck"), 1), radius=10.0), priority=Priority.HIGH)
    plan = b.resolve()
    assert _order(plan).index("buck") < _order(plan).index("cin")
    assert plan.placement("cin") is not None
