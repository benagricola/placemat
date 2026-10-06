"""One argument says where a thing goes: `at=`, taking a place of some
kind. Each kind of place carries its own degrees of freedom: a Location
with both axes (none), with one axis (one), on an edge at a distance
(none) or anywhere along it (one), near a hint (two, searched), or
nothing (two, seeded from its links)."""
import dataclasses

import pytest

from placemat.layout import Board, PlacementCollision
from placemat.values import Freedom, Along, Cell, Centre, Edge, Fraction, Location, Mid, Near, OnEdge, PadRef, Part, Priority, X, Y
from tests.fixtures import board_geometry, footprint, pad, placement_findings


def make_board():
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j1", nets=("A", "B")),
           footprint("J2", 5, 15, w=8, h=3, inst="j2", nets=("C", "D")),
           footprint("U1", 40, 40, w=20, h=10, cell="mcu", inst="mcu.u", nets=("A", "C"))]
    return Board(board_geometry(fps, cells=["mcu"], width=60, height=60), edge_margin=1.0)


def test_a_location_fixes_the_origin_and_a_centre_fixes_the_body_centre():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("j2"), at=Centre(40, 20, coordinates=True))
    plan = b.resolve()
    assert plan.placement("j1").location == Location(20, 20) and plan.step("j1").freedom is Freedom.FIXED
    assert plan.box("j2").center == Location(40, 20) and plan.step("j2").freedom is Freedom.FIXED


def test_a_centre_may_be_said_in_pads_and_with_one_axis_free():
    b = make_board()
    b.place(Part("j1"), at=Location(10, 10))
    b.place(Part("j2"), at=Centre(X(Mid(PadRef(Part("j1"), "A"), PadRef(Part("j1"), "B"))), Y(PadRef(Part("j1"), "A"), 6.0)))
    b.place(Cell("mcu"), at=Centre(30, None, coordinates=True))                     # x pinned, y free
    plan = b.resolve()
    pa, pb = plan.occupancy.pad_location("J1", "1"), plan.occupancy.pad_location("J1", "2")
    assert plan.box("j2").center.x == pytest.approx((pa.x + pb.x) / 2) and plan.box("j2").center.y == pytest.approx(pa.y + 6.0)
    assert plan.box("mcu").center.x == pytest.approx(30.0) and plan.step("mcu").freedom is not Freedom.FIXED


def test_on_an_edge_at_a_distance_is_fixed_and_on_an_edge_alone_slides():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=Along.MID))
    b.place(Part("j2"), at=OnEdge(Edge.NORTH))
    b.place(Cell("mcu"), at=OnEdge(Edge.EAST, along=Fraction(0.25), overhang=0.5))
    plan = b.resolve()
    assert plan.step("j1").freedom is Freedom.EDGE and plan.box("j1").center.x == pytest.approx(30.0)
    assert plan.step("j2").priority is Priority.DEFAULT and plan.box("j2").top == pytest.approx(1.0)
    assert not plan.box("j2").overlaps(plan.box("j1"))
    assert plan.box("mcu").right == pytest.approx(60.5) and plan.box("mcu").center.y == pytest.approx(1.0 + 58.0 * 0.25)


def test_along_start_and_end_put_the_item_flush_with_the_ends_of_the_usable_edge():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=Along.START))
    b.place(Part("j2"), at=OnEdge(Edge.NORTH, along=Along.END))
    plan = b.resolve()
    assert plan.box("j1").left == pytest.approx(1.0) and plan.box("j2").right == pytest.approx(59.0)


def test_near_a_hint_is_searched_round_it():
    b = make_board()
    b.place(Part("j1"), at=Near(Location(20, 20), radius=2.0, step=0.5, rotations=(0, 90)))
    plan = b.resolve()
    assert plan.box("j1").center.distance(Location(20, 20)) < 3.0 and plan.step("j1").priority is Priority.DEFAULT


def test_the_old_keywords_are_gone_and_a_wrong_kind_of_place_is_refused():
    b = make_board()
    for kw in ({"center": Location(1, 1)}, {"edge": Edge.NORTH}, {"near": Location(1, 1)}, {"along": 3.0}):
        with pytest.raises(TypeError):
            b.place(Part("j1"), **kw)
    with pytest.raises(TypeError):
        b.place(Part("j1"), at="north")
    with pytest.raises(TypeError):
        b.place(Part("j1"), at=OnEdge(Edge.NORTH, along="mid"))


HOLE_YARD = 9.1         # a mounting hole's courtyard, square here
HOLE_LAND = 6.0         # its plated land
HOLE_INSET = 3.81       # its centre from each of two edges: the courtyard crosses both by 0.74 mm
KEEP_IN = 0.5


def hole(ref, cx, cy):
    """A mounting hole: one plated land in the middle of a wider courtyard."""
    fp = footprint(ref, cx, cy, w=HOLE_YARD, h=HOLE_YARD, nets=("GND", "GND"), excess=0.0)
    return dataclasses.replace(fp, pads=(pad(ref, ref.lower(), 1, "GND", cx, cy, HOLE_LAND, HOLE_LAND, through=True),))


def hole_board():
    return Board(board_geometry([hole("H1", 25, 25)], width=50, height=50, edge_clearance=KEEP_IN), edge_margin=KEEP_IN)


def test_a_firm_part_whose_courtyard_crosses_the_edge_is_refused_without_an_overhang():
    b = hole_board()
    b.place(Part("h1"), at=Centre(HOLE_INSET, HOLE_INSET, coordinates=True))
    with pytest.raises(PlacementCollision, match="h1 .*body box -0.74,-0.74..8.36,8.36 crosses the board edge"):
        b.resolve()


def test_a_firm_part_may_state_how_far_its_courtyard_overhangs_the_edge():
    """overhang= lets the courtyard and body reach that far past the edge, on any side; it does not move the part."""
    b = hole_board()
    b.place(Part("h1"), at=Centre(HOLE_INSET, HOLE_INSET, coordinates=True), overhang=0.8,
            why="the corner holes sit where the enclosure's bosses are")
    plan = b.resolve()
    centre = plan.box("h1").center
    assert (centre.x, centre.y) == pytest.approx((HOLE_INSET, HOLE_INSET)) and plan.step("h1").freedom is Freedom.FIXED
    assert placement_findings(plan) == []


def test_a_courtyard_past_the_stated_overhang_is_refused_saying_how_far_it_crosses():
    b = hole_board()
    b.place(Part("h1"), at=Centre(HOLE_INSET, HOLE_INSET, coordinates=True), overhang=0.5,
            why="the corner holes sit where the enclosure's bosses are")
    with pytest.raises(PlacementCollision, match=r"h1 .*body box -0.74,-0.74..8.36,8.36 crosses the board edge "
                                                 r"by 0.74 mm, more than its overhang \(0.50 mm\)"):
        b.resolve()


def test_an_overhang_leaves_pads_held_to_the_keep_in():
    b = hole_board()
    b.place(Part("h1"), at=Centre(3.3, 25.0, coordinates=True), overhang=1.5, why="a boss at the edge")   # land 0.3 mm in
    with pytest.raises(PlacementCollision, match=r"h1 .*copper to edge: box 0.30,22.00..6.30,28.00 crosses the board edge "
                                                 r"margin \(0.50 mm\)"):
        b.resolve()


def test_an_overhang_says_why():
    b = hole_board()
    with pytest.raises(ValueError, match="h1: overhang= says why"):
        b.place(Part("h1"), at=Centre(HOLE_INSET, HOLE_INSET, coordinates=True), overhang=0.8)


def test_an_overhang_is_for_a_firm_placement():
    """A searched item would take the allowance wherever the search put it; an edge place says its own overhang."""
    b = hole_board()
    with pytest.raises(ValueError, match="h1: overhang= is for a firm placement"):
        b.place(Part("h1"), overhang=0.8, why="a boss at the edge")
    with pytest.raises(ValueError, match="h1: overhang= is for a firm placement"):
        b.place(Part("h1"), at=OnEdge(Edge.NORTH), overhang=0.8, why="a boss at the edge")
    with pytest.raises(ValueError, match="overhang= is a distance of at least 0"):
        b.place(Part("h1"), at=Centre(HOLE_INSET, HOLE_INSET, coordinates=True), overhang=-0.1, why="a boss")


def test_an_edge_place_with_its_own_overhang_takes_no_second_one():
    b = hole_board()
    with pytest.raises(ValueError, match="h1: OnEdge.* says its own overhang"):
        b.place(Part("h1"), at=OnEdge(Edge.NORTH, along=10.0, overhang=0.5), overhang=0.8, why="a boss at the edge")


def test_an_edge_place_may_overhang_the_edge_it_turns_the_corner_onto():
    """On an edge at the keep-in, overhang= lets the courtyard cross the other edge at the corner."""
    b = hole_board()
    b.place(Part("h1"), at=OnEdge(Edge.NORTH, along=HOLE_INSET), rotation=0, overhang=0.8, why="a boss in the corner")
    plan = b.resolve()
    assert plan.box("h1").center.x == pytest.approx(HOLE_INSET) and placement_findings(plan) == []
