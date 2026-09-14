"""A row: cells or parts down one board edge, in order, equally gapped, each
flush to the edge with its outward side out. The script names the row and
the gap; the row does the arithmetic and lends its geometry to copper."""
import pytest

from placemat.layout import Board
from placemat.values import OnEdge, Cell, CopperLayer, Edge, Location, Net, PadRef, Part, Y
from tests.fixtures import board_geometry, footprint


def make_board():
    # three cells, each one part 8 wide (along, at rotation 0) x 4 deep
    fps = [footprint("U1", 10, 10, w=8, h=4, cell="a", inst="a.u", nets=("A", "GND")),
           footprint("U2", 30, 10, w=8, h=6, cell="b", inst="b.u", nets=("B", "GND")),
           footprint("U3", 50, 10, w=8, h=4, cell="c", inst="c.u", nets=("C", "GND")),
           footprint("J1", 80, 80, w=10, h=3, inst="j1", nets=("A", "B"))]     # off the west edge: undeclared, it stays put
    b = Board(board_geometry(fps, cells=["a", "b", "c"], width=100, height=100), edge_margin=2.0)
    return b


def test_cells_stack_down_an_edge_in_order_with_the_gap():
    b = make_board()
    row = b.row([Cell("a"), Cell("b"), Cell("c")], Edge.WEST, gap=3.0, start=10.0, line="outer")   # connectors: edge-hard
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


def test_a_row_may_align_its_items_on_their_centre_line():
    """Small parts of different heights in one row: aligned on their centres,
    not on the edge line, so a jumper and a resistor read as one row."""
    b = make_board()
    fps = [footprint("R1", 5, 5, w=3, h=1.3, inst="r1", nets=("A", "B")),
           footprint("H1", 9, 5, w=4, h=2.0, inst="h1", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=2.0)
    row = b.row([Part("r1"), Part("h1")], Edge.NORTH, gap=1.5, rotation=0, line="centre")
    plan = b.resolve()
    assert plan.box("r1").center.y == pytest.approx(plan.box("h1").center.y)
    assert plan.box("h1").top == pytest.approx(2.0)                  # the deepest sets the line: the keep-in + 2.0 / 2
    assert plan.box("r1").center.y == pytest.approx(3.0)


def test_rows_align_on_centres_by_default_and_a_butted_row_shares_the_line():
    """A jumper butted before two resistors sits on the resistors' centre
    line, not on its own; `line="outer"` aligns the edges instead."""
    fps = [footprint("R1", 5, 5, w=3, h=1.3, inst="r1", nets=("A", "B")),
           footprint("R2", 9, 5, w=3, h=1.3, inst="r2", nets=("B", "C")),
           footprint("H1", 15, 5, w=4, h=2.0, inst="h1", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=2.0)
    pair = b.row([Part("r1"), Part("r2")], Edge.NORTH, gap=1.5, rotation=0, start=20.0)
    b.row([Part("h1")], Edge.NORTH, gap=1.5, rotation=0, before=pair)
    plan = b.resolve()
    assert plan.box("h1").center.y == pytest.approx(plan.box("r1").center.y)
    assert plan.box("r1").center.y == pytest.approx(2.0 + 1.3 / 2)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=2.0)
    b.row([Part("r1"), Part("h1")], Edge.NORTH, gap=1.5, rotation=0, start=20.0, line="outer")
    plan = b.resolve()
    assert plan.box("r1").top == pytest.approx(2.0) and plan.box("h1").top == pytest.approx(2.0)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=2.0)
    b.row([Part("r1"), Part("h1")], Edge.NORTH, gap=1.5, rotation=0, start=20.0, line="inner")
    plan = b.resolve()
    assert plan.box("r1").bottom == pytest.approx(plan.box("h1").bottom)


def test_a_row_may_sit_behind_another_on_the_same_edge():
    """Inboard of an edge row, one gap away: the relationship the design
    has, said without a number."""
    b = make_board()
    front = b.row([Part("j1")], Edge.NORTH, gap=3.0, align="center")
    back = b.row([Cell("a"), Cell("b"), Cell("c")], Edge.NORTH, gap=1.0, behind=front, inboard=2.0, align="center", line="outer")
    plan = b.resolve()
    assert plan.box("a").top == pytest.approx(plan.box("j1").bottom + 2.0)
    assert back.standoff == pytest.approx(front.standoff + front.depth + 2.0)


def test_a_connector_may_overhang_the_edge():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=20.0, overhang=1.5), why="the mating face stands proud of the case wall")
    plan = b.resolve()
    assert plan.box("j1").top == pytest.approx(-1.5)


def test_a_row_may_start_at_a_reference():
    """After a mounting hole, one gap away: no hand arithmetic on a courtyard radius."""
    b = make_board()
    b.place(Part("j1"), at=Location(10.0, 10.0))
    row = b.row([Cell("a"), Cell("b")], Edge.WEST, gap=3.0, start=Y(PadRef(Part("j1"), "B"), 4.0))
    plan = b.resolve()
    jb = plan.occupancy.pad_location("J1", "2")
    assert plan.box("a").top == pytest.approx(jb.y + 4.0)


def test_a_rows_depth_and_the_edge_standoff_measure_the_parts_reach_not_its_body():
    """A terminal's silk runs past its body: the silk sits at the keep-in
    and the body that much further in, and the row is that much deeper."""
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j1", silk=(0, 3.0, 0, 0))]     # 3 mm of silk north of the body
    b = Board(board_geometry(fps, width=60, height=60, edge_clearance=0.4))
    row = b.row([Part("j1")], Edge.NORTH, gap=1.0, align="center", rotation=0)
    plan = b.resolve()
    assert plan.box("j1").top == pytest.approx(0.4 + 3.0)
    assert row.depth == pytest.approx(3.0 + 3.0)
    assert b.keep_in == pytest.approx(0.4)
