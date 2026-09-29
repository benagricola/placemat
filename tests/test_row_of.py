"""board.row(items, edge, of=Part(...)|Cell(...)): a row measured off a
part's or cell's own drawn envelope, not the board's edge - the row
machinery's gap, align and line, reused; accepted on a fit frame. Pure:
synthetic boards."""
import pytest

from placemat.layout import Board
from placemat.values import Along, Edge, Line, Location, Part
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 0, 0, w=2, h=1, inst="r1", nets=("A", "GND")),
           footprint("R2", 0, 0, w=2, h=1, inst="r2", nets=("B", "GND"))]
    return Board(board_geometry(fps, width=80, height=80), edge_margin=1.0, **kw)


def test_row_of_a_part_align_start_stacks_flush_with_its_near_end():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.EAST, of=Part("u1"), align=Along.START, rotation=0)
    plan = b.resolve()
    r1, r2 = plan.box("r1"), plan.box("r2")
    assert (r1.left, r1.top, r1.right, r1.bottom) == pytest.approx((22.2, 19.0, 24.2, 20.0))
    assert (r2.left, r2.top, r2.right, r2.bottom) == pytest.approx((22.2, 20.2, 24.2, 21.2))
    assert r2.top - r1.bottom == pytest.approx(0.2)   # courtyards touching (gap=0 default)


def test_row_of_align_mid_centres_within_the_items_side():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.EAST, of=Part("u1"), align=Along.MID, rotation=0)
    plan = b.resolve()
    r1, r2 = plan.box("r1"), plan.box("r2")
    u1 = plan.box("u1")
    span_lo, span_hi = u1.top - 0.1, u1.bottom + 0.1     # u1's envelope side
    assert (r1.top - 0.1 + r2.bottom + 0.1) / 2 == pytest.approx((span_lo + span_hi) / 2)


def test_row_of_align_end_stacks_flush_with_its_far_end():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.EAST, of=Part("u1"), align=Along.END, rotation=0)
    plan = b.resolve()
    r2 = plan.box("r2")
    assert r2.bottom + 0.1 == pytest.approx(21.1)      # u1's envelope's far (south) edge


def test_row_of_explicit_gap():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1")], Edge.EAST, of=Part("u1"), align=Along.START, rotation=0, gap=1.0)
    plan = b.resolve()
    r1 = plan.box("r1")
    assert r1.left - 22.1 == pytest.approx(1.0 + 0.1)    # u1's envelope east edge, the gap, and r1's own courtyard excess


def test_row_of_shares_one_line_across_items_with_different_courtyard_margins():
    """The line (line=Line.CENTRE, the default) is measured by the same
    envelope box the row places by - as Beside is - not by reach: two items
    whose courtyards differ still share it."""
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 0, 0, w=2, h=1, inst="r1", nets=("A", "GND"), excess=0.1),
           footprint("R2", 0, 0, w=2, h=1, inst="r2", nets=("B", "GND"), excess=0.5)]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.EAST, of=Part("u1"), align=Along.START, rotation=0)
    plan = b.resolve()
    r1, r2 = plan.box("r1"), plan.box("r2")
    assert r1.center.x == pytest.approx(r2.center.x)


def test_row_of_accepts_a_fit_frame():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 0, 0, w=2, h=1, inst="r1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=1.0)
    b.size(fit=True, draw=False)
    b.place(Part("u1"), at=Location(0, 0))
    b.row([Part("r1")], Edge.EAST, of=Part("u1"), align=Along.START, rotation=0)
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.left - u1.right == pytest.approx(0.2)


def test_row_of_waits_for_the_part_declared_later():
    b = make_board()
    b.row([Part("r1")], Edge.EAST, of=Part("u1"), align=Along.START, rotation=0)
    b.place(Part("u1"), at=Location(20, 20))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.left - u1.right == pytest.approx(0.2)
    assert plan.steps[0].item == "u1"


def test_row_of_keeps_the_boards_own_edge_margin():
    """A row off a part keeps the board's edge margin, as Beside does: its
    own small item-to-item gap is not an edge standoff, and must not read
    as one and switch the margin off."""
    fps = [footprint("U1", 56.5, 30, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 0, 0, w=2, h=1, inst="r1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)
    b.place(Part("u1"), at=Location(56.5, 30))
    b.row([Part("r1")], Edge.EAST, of=Part("u1"))
    plan = b.resolve()
    assert [f for f in plan.findings if "r1" in f]


def test_row_of_refuses_a_board_anchor_together_with_it():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    with pytest.raises(ValueError, match="not with it"):
        b.row([Part("r1")], Edge.EAST, of=Part("u1"), start=5.0)


def test_row_of_refuses_a_run():
    b = make_board()
    with pytest.raises(TypeError, match="Edge"):
        b.row([Part("r1")], "not-an-edge", of=Part("u1"))
