"""The script-facing surface: a Board records intents, validates them when
they are declared, and resolves them in priority order, never file order."""
import pytest

from placemat.layout import Board
from placemat.values import Near, OnEdge, Centre, Box, Cell, Edge, Face, Location, Part, Priority
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j_in"),
           footprint("R1", 20, 20, inst="r1"),
           footprint("R2", 25, 20, inst="r2"),
           footprint("U1", 40, 40, w=6, h=2, cell="pd", inst="pd.conn"),
           footprint("F1", 40, 44, w=6, h=2, cell="pd", inst="pd.fuse")]
    return Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=1.0, **kw)


def test_an_unknown_part_is_refused_when_declared():
    b = make_board()
    with pytest.raises(KeyError):
        b.place(Part("nope"), at=Location(1, 1))


def test_declaration_order_does_not_decide_execution_order():
    b = make_board()
    b.place(Part("r1"), at=Near(Location(30, 30)))                           # searched: last
    b.place(Cell("pd"), at=Centre(30, 30))                          # fixed cell
    b.place(Part("j_in"), at=OnEdge(Edge.NORTH, along=30.0))     # edge
    b.place(Part("r2"), at=Location(10, 50))                              # fixed part
    plan = b.resolve()
    order = [step.item for step in plan.steps]
    assert set(order[:2]) == {"r2", "pd"} and order[2:] == ["j_in", "r1"]
    assert [step.priority for step in plan.steps] == [Priority.FIXED, Priority.FIXED, Priority.EDGE, Priority.DEFAULT]


def test_a_fixed_part_lands_exactly_where_asked():
    b = make_board()
    b.place(Part("r2"), at=Location(10, 50), rotation=90)
    plan = b.resolve()
    assert plan.placement("r2") == pytest.approx_placement if False else plan.placement("r2").location == Location(10, 50)
    assert plan.placement("r2").rotation == 90


def test_a_cell_placed_by_centre_puts_its_box_centre_there():
    b = make_board()
    b.place(Cell("pd"), at=Centre(30, 30), rotation=90)
    plan = b.resolve()
    box = plan.box("pd")
    assert box.center == Location(30, 30)
    assert abs(box.width - 6.0) < 1e-9 and abs(box.height - 6.0) < 1e-9   # 6x6 either way here


def test_a_searched_part_moves_off_a_fixed_one_and_says_so():
    b = make_board()
    b.place(Part("r2"), at=Location(10, 50))
    b.place(Part("r1"), at=Near(Location(10, 50), radius=4.0, step=0.5))
    plan = b.resolve()
    step = plan.step("r1")
    assert step.placement.location != Location(10, 50)
    assert step.moved_mm > 0 and "courtyard" in step.note


def test_a_fixed_part_that_collides_stops_the_run_or_is_reported_not_moved():
    import pytest
    from placemat.layout import PlacementCollision
    b = make_board()
    b.place(Part("r2"), at=Location(10, 50))
    b.place(Part("r1"), at=Location(10, 50))
    with pytest.raises(PlacementCollision):
        b.resolve()
    b = make_board(keep_going=True)
    b.place(Part("r2"), at=Location(10, 50))
    b.place(Part("r1"), at=Location(10, 50))
    plan = b.resolve()
    assert plan.placement("r1").location == Location(10, 50)
    assert any("r1" in f and "R2" in f for f in plan.findings)


def test_the_board_size_is_a_declaration_and_bounds_the_search():
    b = make_board()
    b.size(width=40.0, height=30.0, chamfer=2.0)
    b.place(Part("r1"), at=Near(Location(39, 15), radius=3.0, step=0.5))
    plan = b.resolve()
    assert plan.outline == Box(0, 0, 40.0, 30.0) and plan.chamfer == 2.0
    assert plan.box("r1").right <= 40.0 - 1.0 + 1e-9


def test_extent_answers_size_at_a_rotation_without_placing():
    b = make_board()
    e = b.extent(Cell("pd"), rotation=90)
    assert abs(e.width - 6.0) < 1e-9 and abs(e.height - 6.0) < 1e-9
    e = b.extent(Part("j_in"), rotation=90)
    assert abs(e.width - 3.0) < 1e-9 and abs(e.height - 8.0) < 1e-9


def test_placing_the_same_item_twice_is_an_error():
    b = make_board()
    b.place(Part("r1"), at=Location(1, 1))
    with pytest.raises(ValueError):
        b.place(Part("r1"), at=Location(2, 2))


def test_a_fragment_may_have_a_frame_for_rows_and_edges_that_is_not_drawn():
    """A module fragment has no outline of its own, but its script may
    still want rows against an edge: size(..., draw=False) gives the
    placer a frame and writes no Edge.Cuts."""
    from placemat.values import OnEdge
    b = make_board()
    b.size(width=40.0, height=30.0, draw=False)
    b.place(Part("j_in"), at=OnEdge(Edge.NORTH))
    plan = b.resolve()
    assert plan.outline is not None and plan.draw_outline is False
    assert plan.box("j_in").top == pytest.approx(1.0)
