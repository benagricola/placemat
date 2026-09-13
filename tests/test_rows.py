"""A row: cells or parts down one board edge, in order, equally gapped, each
flush to the edge with its outward side out. The script names the row and
the gap; the row does the arithmetic and lends its geometry to copper."""
import pytest

from placemat.layout import Board
from placemat.values import Cell, CopperLayer, Edge, Location, Net, Part
from tests.fixtures import board_geometry, footprint


def make_board():
    # three cells, each one part 8 wide (along, at rotation 0) x 4 deep
    fps = [footprint("U1", 10, 10, w=8, h=4, cell="a", inst="a.u", nets=("A", "GND")),
           footprint("U2", 30, 10, w=8, h=6, cell="b", inst="b.u", nets=("B", "GND")),
           footprint("U3", 50, 10, w=8, h=4, cell="c", inst="c.u", nets=("C", "GND")),
           footprint("J1", 5, 40, w=10, h=3, inst="j1", nets=("A", "B"))]
    b = Board(board_geometry(fps, cells=["a", "b", "c"], width=100, height=100), edge_margin=2.0)
    return b


def test_cells_stack_down_an_edge_in_order_with_the_gap():
    b = make_board()
    row = b.row([Cell("a"), Cell("b"), Cell("c")], Edge.WEST, gap=3.0, start=10.0)
    plan = b.resolve()
    a, bb, c = plan.box("a"), plan.box("b"), plan.box("c")
    assert a.left == pytest.approx(2.0) and bb.left == pytest.approx(2.0) and c.left == pytest.approx(2.0)
    assert a.top == pytest.approx(10.0)
    assert bb.top == pytest.approx(a.bottom + 3.0) and c.top == pytest.approx(bb.bottom + 3.0)
    assert plan.placement("a").rotation == 270            # outward (local +Y) faces west


def test_a_row_knows_its_depth_and_length_at_declaration():
    b = make_board()
    row = b.row([Cell("a"), Cell("b"), Cell("c")], Edge.WEST, gap=3.0, start=10.0)
    assert row.depth == pytest.approx(6.0)                # the deepest cell, turned onto the edge
    assert row.length == pytest.approx(8 + 3 + 8 + 3 + 8)


def test_copper_may_refer_to_a_rows_inner_boundary_and_ends():
    b = make_board()
    row = b.row([Cell("a"), Cell("b"), Cell("c")], Edge.WEST, gap=3.0, start=10.0)
    b.track(Net("GND"), [(row.inner, row.start), (row.inner, row.end)], layer=CopperLayer.B, width=0.5)
    plan = b.resolve()
    t = [op for op in plan.copper if op.net == "GND"][0]
    assert t.start == Location(8.0, 10.0) and t.end == Location(8.0, 40.0)


def test_a_row_may_be_centred_on_its_edge():
    b = make_board()
    row = b.row([Part("j1")], Edge.NORTH, gap=3.0, align="center")
    plan = b.resolve()
    box = plan.box("j1")
    assert box.center.x == pytest.approx(50.0) and box.top == pytest.approx(2.0)
    assert plan.placement("j1").rotation == 180           # outward faces north


def test_a_row_after_another_starts_where_it_ends():
    b = make_board()
    first = b.row([Cell("a"), Cell("b")], Edge.WEST, gap=3.0, start=10.0)
    second = b.row([Cell("c")], Edge.WEST, gap=3.0, start=first.end + 5.0)
    plan = b.resolve()
    assert plan.box("c").top == pytest.approx(plan.box("b").bottom + 5.0)


def test_a_centred_row_may_be_declared_before_the_board_size():
    """A board's size is often derived from its rows, so a row centred on an
    edge is placed when the outline is known, at resolve."""
    b = make_board()
    row = b.row([Part("j1")], Edge.SOUTH, gap=3.0, align="center")
    assert row.depth == pytest.approx(3.0)
    b.size(width=80, height=60)
    plan = b.resolve()
    box = plan.box("j1")
    assert box.center.x == pytest.approx(40.0) and box.bottom == pytest.approx(58.0)
    assert plan.placement("j1").rotation == 0                   # outward faces south
