"""A block: a part and the satellites that sit at its pins by rule. The
block is laid out from the anchor's real pads at every candidate, so its
envelope is exact, and searched as one thing."""
from placemat.layout import Board
from placemat.values import Cell, Location, Part, PadRef
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("U1", 30, 30, w=6, h=3, inst="ldo", nets=("VIN", "VOUT")),      # pad 1 west (VIN), pad 2 east (VOUT)
           footprint("C1", 60, 60, inst="cin", nets=("VIN", "GND")),
           footprint("C2", 60, 65, inst="cout", nets=("VOUT", "GND")),
           footprint("J1", 5, 5, w=8, h=3, inst="j1", nets=("VIN", "GND")),
           footprint("W1", 30, 20, w=20, h=6, inst="wall", excess=0.0)]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def test_satellites_sit_on_their_pins_axis_one_gap_out():
    b = make_board()
    b.place(Part("wall"), at=Location(30, 20))
    blk = b.block(Part("ldo"), satellites=[(Part("cin"), "VIN"), (Part("cout"), "VOUT")], gap=0.5)
    b.place(blk, at=Location(30, 40))
    plan = b.resolve()
    ldo_vin = plan.occupancy.pad_location("U1", "1")
    ldo_vout = plan.occupancy.pad_location("U1", "2")
    cin_vin = plan.occupancy.pad_location("C1", "1")
    cout_vout = plan.occupancy.pad_location("C2", "1")
    assert abs(cin_vin.y - ldo_vin.y) < 1e-6 and cin_vin.x < ldo_vin.x          # west of the west pin, on its axis
    assert abs(cout_vout.y - ldo_vout.y) < 1e-6 and cout_vout.x > ldo_vout.x    # east of the east pin
    assert plan.occupancy.legal(plan.geometry.footprint("C1"), plan.placement("cin")) is None


def test_a_block_is_searched_as_one_and_reports_its_envelope():
    b = make_board()
    b.place(Part("wall"), at=Location(30, 20))
    b.place(Part("j1"), at=Location(10, 40))
    blk = b.block(Part("ldo"), satellites=[(Part("cin"), "VIN"), (Part("cout"), "VOUT")], gap=0.5)
    b.place(blk, near=Location(30, 22), radius=8.0, step=0.5)     # hint on the wall: the whole block moves off it
    plan = b.resolve()
    for name in ("ldo", "cin", "cout"):
        assert plan.placement(name) is not None
    box = plan.box("block ldo")
    assert not box.overlaps(plan.box("wall"))
    assert box.width > 6.0                                       # wider than the anchor alone
    assert "block" in plan.step("block ldo").note or plan.step("block ldo").kind == "block"


def test_a_block_goes_down_after_cells_and_before_loose_parts():
    fps = [footprint("U1", 30, 30, w=6, h=3, inst="ldo", nets=("VIN", "VOUT")),
           footprint("C1", 60, 60, inst="cin", nets=("VIN", "GND")),
           footprint("R1", 50, 50, inst="r1", nets=("VOUT", "X")),
           footprint("U2", 10, 10, w=8, h=4, cell="c", inst="c.u", nets=("VIN", "Y"))]
    b = Board(board_geometry(fps, cells=["c"], width=60, height=60), edge_margin=1.0)
    b.place(Part("r1"))
    b.place(b.block(Part("ldo"), satellites=[(Part("cin"), "VIN")]))
    b.place(Cell("c"))
    order = [s.item for s in b.resolve().steps if s.placement is not None]
    assert order.index("c") < order.index("block ldo") < order.index("r1")


def test_a_block_with_nothing_placed_to_pull_it_starts_from_the_board_not_where_the_generator_left_it():
    """A fresh generation drops parts off the outline; a block with no
    placed neighbour and no hint searches from the board's centre."""
    fps = [footprint("U9", 150, 60, w=4, h=2, inst="ldo", nets=("VIN", "VOUT")),
           footprint("C8", 160, 60, w=2, h=1, inst="cin", nets=("VIN", "GND"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0)
    b.place(b.block(Part("ldo"), satellites=[(Part("cin"), "VIN")]))
    plan = b.resolve()
    assert plan.findings == []
    assert 0 < plan.box("ldo").center.x < 50 and 0 < plan.box("ldo").center.y < 50


def test_a_block_with_a_placed_neighbour_searches_from_that_neighbour():
    fps = [footprint("U9", 150, 60, w=4, h=2, inst="ldo", nets=("VIN", "VOUT")),
           footprint("C8", 160, 60, w=2, h=1, inst="cin", nets=("VIN", "GND")),
           footprint("J1", 5, 5, w=4, h=2, inst="j1", nets=("VIN", "GND"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0)
    b.place(Part("j1"), at=Location(40, 40))
    b.place(b.block(Part("ldo"), satellites=[(Part("cin"), "VIN")]), radius=4.0)
    plan = b.resolve()
    assert plan.findings == [] and plan.box("ldo").center.distance(Location(40, 40)) < 10
