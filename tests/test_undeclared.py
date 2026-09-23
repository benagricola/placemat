"""A part in the netlist that no declaration places is left where the
generator put it: the run says so rather than leaving it to the airwire."""
from placemat.layout import Board
from placemat.values import Cell, Location, Part
from tests.fixtures import board_geometry, footprint


def test_a_part_with_no_declaration_is_a_finding():
    fps = [footprint("C1", 20, 20, inst="ca", nets=("VIN", "GND")),
           footprint("C2", 160, 65, inst="cb", nets=("VIN", "GND"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("ca"), at=Location(20, 20))
    plan = b.resolve()
    assert [f for f in plan.findings if "cb" in f and "C2" in f and "no declaration" in f]


def test_a_part_placed_as_a_cell_or_block_member_is_declared():
    fps = [footprint("U1", 30, 30, w=6, h=3, inst="ldo", nets=("VIN", "VOUT")),
           footprint("C1", 60, 60, inst="cin", nets=("VIN", "GND")),
           footprint("U2", 10, 10, w=8, h=4, cell="c", inst="c.u", nets=("VIN", "Y"))]
    b = Board(board_geometry(fps, cells=["c"], width=60, height=60), edge_margin=1.0)
    b.place(b.block(Part("ldo"), satellites=[(Part("cin"), "VIN")]))
    b.place(Cell("c"))
    plan = b.resolve()
    assert not [f for f in plan.findings if "no declaration" in f]
