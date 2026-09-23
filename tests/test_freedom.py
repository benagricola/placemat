"""Degrees of freedom. OnEdge with along is fixed on that edge: zero
freedom, it never moves and two such things that meet are an invalid
layout. OnEdge alone is one degree of freedom: it slides along its edge,
sits at the edge's midpoint when alone, spreads evenly with its fellows,
and moves aside for anything already there. A searched item has two."""
import pytest

from placemat.layout import Board, PlacementCollision
from placemat.values import Freedom, Near, OnEdge, Centre, Cell, Edge, Location, Part, Priority
from tests.fixtures import board_geometry, footprint, declared_findings


def make_board():
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j1", nets=("A", "B")),
           footprint("J2", 5, 15, w=8, h=3, inst="j2", nets=("C", "D")),
           footprint("J3", 5, 25, w=8, h=3, inst="j3", nets=("E", "F")),
           footprint("U1", 40, 40, w=20, h=10, cell="mcu", inst="mcu.u", nets=("A", "C"))]
    return Board(board_geometry(fps, cells=["mcu"], width=60, height=60), edge_margin=1.0)


def test_an_edge_item_with_no_position_sits_at_the_midpoint_of_its_edge():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH))
    plan = b.resolve()
    box = plan.box("j1")
    assert box.center.x == pytest.approx(30.0) and box.top == pytest.approx(1.0)
    assert plan.step("j1").priority is Priority.DEFAULT           # it is searched, along its edge


def test_edge_items_with_no_position_spread_evenly_along_their_edge():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH))
    b.place(Part("j2"), at=OnEdge(Edge.NORTH))
    b.place(Part("j3"), at=OnEdge(Edge.NORTH))
    plan = b.resolve()
    xs = sorted(plan.box(k).center.x for k in ("j1", "j2", "j3"))
    usable = 60.0 - 2 * 1.0
    assert xs == pytest.approx([1.0 + usable / 4, 1.0 + usable / 2, 1.0 + 3 * usable / 4])


def test_a_free_edge_item_slides_aside_for_a_fixed_one_at_the_midpoint():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=30.0))              # zero freedom: the midpoint is taken
    b.place(Part("j2"), at=OnEdge(Edge.NORTH))
    b.place(Part("j3"), at=OnEdge(Edge.NORTH))
    plan = b.resolve()
    j1, j2, j3 = plan.box("j1"), plan.box("j2"), plan.box("j3")
    assert declared_findings(plan) == []
    assert j1.center.x == pytest.approx(30.0)
    left, right = sorted((j2, j3), key=lambda x: x.center.x)
    assert right.left >= j1.right and left.right <= j1.left          # one each side, off the fixed one
    assert left.top == pytest.approx(1.0) and right.top == pytest.approx(1.0)


def test_two_fixed_edge_items_that_meet_are_an_invalid_layout():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=30.0))
    b.place(Part("j2"), at=OnEdge(Edge.NORTH, along=32.0))
    with pytest.raises(PlacementCollision):
        b.resolve()


def test_a_critical_searched_cell_goes_before_free_edge_furniture_and_the_furniture_moves_aside():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH))                            # furniture: one degree of freedom
    b.place(Part("j2"), at=OnEdge(Edge.NORTH))
    b.place(Cell("mcu"), at=Near(Location(30, 7), radius=1.0), priority=Priority.HIGH)   # wants the north middle
    plan = b.resolve()
    order = [s.item for s in plan.steps]
    assert order.index("mcu") < order.index("j1") and order.index("mcu") < order.index("j2")
    mcu = plan.box("mcu")
    assert declared_findings(plan) == []
    for k in ("j1", "j2"):
        assert not plan.box(k).overlaps(mcu)


def test_a_location_with_one_axis_pins_that_coordinate_and_the_item_slides_on_the_other():
    """at=Location(30, None): x fixed at 30, y free. It sits at the middle
    of the free axis alone, and slides past whatever is already on that line."""
    b = make_board()
    b.place(Part("j1"), at=Location(30.0, None))
    plan = b.resolve()
    box = plan.box("j1")
    assert box.center.x == pytest.approx(30.0) and box.center.y == pytest.approx(30.0)
    assert plan.step("j1").freedom is not Freedom.FIXED                 # one freedom left: it is searched
    b = make_board()
    b.place(Cell("mcu"), at=Centre(30, 30))                    # holds the middle of the x = 30 line
    b.place(Part("j1"), at=Centre(30.0, None))
    b.place(Part("j2"), at=Centre(30.0, None))
    plan = b.resolve()
    mcu, j1, j2 = plan.box("mcu"), plan.box("j1"), plan.box("j2")
    assert declared_findings(plan) == []
    assert j1.center.x == pytest.approx(30.0) and j2.center.x == pytest.approx(30.0)
    assert not j1.overlaps(mcu) and not j2.overlaps(mcu) and not j1.overlaps(j2)
    b = make_board()
    b.place(Part("j1"), at=Location(10.0, 40.0))
    b.place(Part("j2"), at=Centre(None, 40.0))                 # y pinned, x free
    plan = b.resolve()
    assert plan.box("j2").center.y == pytest.approx(40.0) and not plan.box("j2").overlaps(plan.box("j1"))


def test_a_pinned_coordinate_may_be_a_reference():
    from placemat.values import X, PadRef, Mid
    b = make_board()
    b.place(Part("j1"), at=Location(10.0, 10.0))
    b.place(Part("j2"), at=Centre(X(Mid(PadRef(Part("j1"), "A"), PadRef(Part("j1"), "B"))), None))
    plan = b.resolve()
    pa, pb = plan.occupancy.pad_location("J1", "1"), plan.occupancy.pad_location("J1", "2")
    assert plan.box("j2").center.x == pytest.approx((pa.x + pb.x) / 2)


def test_a_location_needs_at_least_one_axis_and_x_y_keywords_are_gone():
    b = make_board()
    with pytest.raises(ValueError):
        Location(None, None)
    with pytest.raises(TypeError):
        b.place(Part("j1"), x=30.0)


def test_along_is_a_distance_on_whichever_edge_a_named_place_or_a_fraction_and_needs_an_edge():
    from placemat.values import Along, Fraction
    b = make_board()
    with pytest.raises(TypeError):
        b.place(Part("j1"), along=5.0)                            # along lives inside OnEdge, not on place()
    b.place(Part("j1"), at=OnEdge(Edge.EAST, along=20.0))               # on the east edge, 20 down
    b.place(Part("j2"), at=OnEdge(Edge.NORTH, along=Along.MID))         # the north edge's midpoint
    b.place(Part("j3"), at=OnEdge(Edge.SOUTH, along=Fraction(0.25)))    # a quarter of the usable south edge
    plan = b.resolve()
    assert plan.box("j1").center.y == pytest.approx(20.0) and plan.box("j1").right == pytest.approx(59.0)
    assert plan.box("j2").center.x == pytest.approx(30.0) and plan.box("j2").top == pytest.approx(1.0)
    assert plan.box("j3").center.x == pytest.approx(1.0 + 58.0 * 0.25)
    assert all(plan.step(k).freedom is Freedom.EDGE for k in ("j1", "j2", "j3"))
    with pytest.raises(TypeError):
        b.place(Cell("mcu"), at=OnEdge(Edge.WEST, along="mid"))         # a string is a typo waiting to happen
    with pytest.raises(ValueError):
        Fraction(1.5)                                             # a fraction of the edge is between 0 and 1


def test_along_start_and_end_are_the_ends_of_the_usable_edge():
    from placemat.values import Along
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=Along.START))
    b.place(Part("j2"), at=OnEdge(Edge.NORTH, along=Along.END))
    plan = b.resolve()
    assert plan.box("j1").left == pytest.approx(1.0) and plan.box("j2").right == pytest.approx(59.0)




def test_a_point_is_fixed_and_a_distance_along_an_edge_is_edge():
    from placemat.values import Freedom
    fps = [footprint("J1", 10, 10, inst="j1"), footprint("J2", 30, 10, inst="j2"),
           footprint("R1", 50, 10, inst="r1")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    a = b.place(Part("j1"), at=Location(20, 20))
    e = b.place(Part("j2"), at=OnEdge(Edge.NORTH, along=30.0))
    s = b.place(Part("r1"))
    assert a.freedom is Freedom.FIXED and a.freedom.decided
    assert e.freedom is Freedom.EDGE and e.freedom.decided
    assert s.freedom is Freedom.SEARCHED and not s.freedom.decided


def test_a_freedom_left_in_the_place_makes_it_searched():
    from placemat.values import Freedom
    fps = [footprint("J1", 10, 10, inst="j1"), footprint("J2", 30, 10, inst="j2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    slide = b.place(Part("j1"), at=OnEdge(Edge.NORTH))          # no along=
    line = b.place(Part("j2"), at=Location(30, None))           # one axis pinned
    assert slide.freedom is Freedom.SEARCHED
    assert line.freedom is Freedom.SEARCHED


def test_decided_items_still_go_down_before_searched_ones():
    fps = [footprint("U1", 10, 10, w=6, h=6, inst="u1", nets=("A", "B")),
           footprint("J1", 40, 40, inst="j1", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"))                                          # searched
    b.place(Part("j1"), at=Location(20, 20))                     # decided, declared second
    order = [s.item for s in b.resolve().steps if s.kind == "part"]
    assert order.index("j1") < order.index("u1")


def test_a_finding_still_names_the_freedom_the_way_it_always_did():
    fps = [footprint("J1", 10, 10, w=8, h=8, inst="j1"), footprint("J2", 30, 10, w=8, h=8, inst="j2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("j2"), at=Location(20, 20))                      # right on top
    plan = b.resolve()
    assert any(f.split(" ")[1] == "(fixed):" for f in plan.findings), plan.findings
