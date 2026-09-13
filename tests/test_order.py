"""The placer decides the order things go down in, never the script:
FIXED, EDGE, then cells largest and most awkward first pulled by their
links, then blocks, then loose parts by link pull. Every choice carries
the sentence that made it."""
from placemat.layout import Board
from placemat.values import Cell, Edge, LinkWeight, Location, Part, PadRef
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j1", nets=("A", "GND")),
           footprint("U1", 40, 40, w=12, h=8, cell="big", inst="big.u", nets=("A", "B")),
           footprint("C1", 40, 46, w=3, h=1.5, cell="big", inst="big.c", nets=("B", "GND")),
           footprint("U2", 70, 70, w=4, h=3, cell="small", inst="small.u", nets=("B", "C")),
           footprint("U3", 80, 80, w=10, h=2, cell="strip", inst="strip.u", nets=("C", "D")),
           footprint("R1", 90, 90, inst="r1", nets=("D", "GND")),
           footprint("R2", 90, 95, inst="r2", nets=("A", "GND")),
           footprint("MH", 2, 2, w=2, h=2, inst="mh", nets=("GND", "GND"))]
    return Board(board_geometry(fps, cells=["big", "small", "strip"], width=100, height=100), edge_margin=1.0)


def order_of(plan):
    return [s.item for s in plan.steps if s.kind != "part" or s.placement is not None or "UNPLACED" in s.note]


def test_fixed_then_edge_then_cells_then_loose_whatever_the_file_order():
    b = make_board()
    b.place(Part("r1"))                                                  # loose
    b.place(Cell("small"))                                               # cell
    b.place(Part("j1"), edge=Edge.NORTH, along=50.0, clearance=2.0)      # edge
    b.place(Part("mh"), at=Location(3, 3))                               # fixed
    b.place(Cell("big"))
    order = order_of(b.resolve())
    assert order[0] == "mh" and order[1] == "j1"
    assert order.index("big") < order.index("r1") and order.index("small") < order.index("r1")


def test_among_cells_the_largest_goes_first_and_the_choice_is_explained():
    b = make_board()
    b.place(Cell("small"))
    b.place(Cell("strip"))
    b.place(Cell("big"))
    plan = b.resolve()
    cells = [s for s in plan.steps if s.kind == "cell"]
    assert [s.item for s in cells][0] == "big"
    assert "largest" in cells[0].why or "largest" in cells[0].note


def test_a_cell_pulled_by_a_placed_partner_goes_before_one_that_is_not():
    b = make_board()
    b.place(Part("j1"), at=Location(10, 10))          # net A: pulls the big cell's U1
    b.place(Cell("strip"))                            # nets C, D: nothing placed yet
    b.place(Cell("small"))                            # net B (big) and C
    b.place(Cell("big"))                              # net A (j1) and B
    order = order_of(b.resolve())
    assert order.index("big") < order.index("small") < order.index("strip")


def test_loose_parts_go_down_heaviest_link_first():
    b = make_board()
    b.place(Part("j1"), at=Location(10, 10))
    b.place(Part("r1"))
    b.place(Part("r2"))
    b.link(PadRef(Part("r2"), "A"), PadRef(Part("j1"), "A"), weight=LinkWeight.SHORT, limit_mm=3.0)
    order = order_of(b.resolve())
    assert order.index("r2") < order.index("r1")


def test_the_order_is_the_same_whatever_the_declaration_order():
    def run(seq):
        b = make_board()
        b.place(Part("j1"), at=Location(10, 10))
        for name in seq:
            b.place(Cell(name))
        return order_of(b.resolve())
    assert run(("small", "strip", "big")) == run(("big", "small", "strip")) == run(("strip", "big", "small"))
