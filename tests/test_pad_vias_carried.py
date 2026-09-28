"""A via the script declares at a part's pad goes with the part through its
search: the part lands where the via clears the other face."""
import dataclasses

from placemat.copper import Via
from placemat.geometry import poly_distance, via_ring
from placemat.layout import Board
from placemat.values import Face, Location, Near, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board(with_via, back_face_searched=False):
    """u1 (front, GND on pad 1) is searched near a spot where its pad 1 lies
    over r9's pads on the back."""
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="u1", nets=("GND", "X")),
           footprint("R9", 20, 20, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    b = Board(board_geometry(fps, width=50, height=50, extra_nets=("GND",)), edge_margin=0.5)
    b.place(Part("r9"), at=Location(20, 20), face=Face.BACK)
    b.place(Part("u1"), at=Near(Location(20.9, 20), radius=4))      # there, u1's pad 1 is on r9's pad 1
    if with_via:
        b.via(Net("GND"), PadRef(Part("u1"), 1), size=0.45, drill=0.2)
    return b


def _gap_to_r9(plan):
    at = plan.occupancy.pad_location("U1", "1")
    ring = via_ring(at, 0.45)
    return min(poly_distance(ring, s.poly) for s in plan.occupancy.items["R9"].shapes if s.kind == "pad")


def test_without_the_via_the_part_lands_over_the_other_faces_pads():
    assert _gap_to_r9(_board(False).resolve()) < 0.2          # the case the via must change


def test_with_a_via_at_its_pad_the_part_lands_where_the_via_clears_them():
    plan = _board(True).resolve()
    assert _gap_to_r9(plan) >= 0.2 - 1e-6
    assert not [f for f in plan.findings if f.kind == "copper"], list(plan.findings)


def test_a_fixed_parts_via_is_neither_doubled_nor_judged_against_itself():
    fps = [footprint("U1", 10, 10, w=3, h=1, inst="u1", nets=("GND", "X"))]
    b = Board(board_geometry(fps, width=30, height=30, extra_nets=("GND",)), edge_margin=0.5)
    b.place(Part("u1"), at=Location(10, 10))
    b.via(Net("GND"), PadRef(Part("u1"), 1), size=0.45, drill=0.2)
    plan = b.resolve()
    assert len([c for c in plan.copper if isinstance(c, Via)]) == 1
    assert not plan.findings, list(plan.findings)


def test_a_via_at_a_pad_named_by_its_net_is_carried_too():
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="u1", nets=("GND", "X")),
           footprint("R9", 20, 20, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    b = Board(board_geometry(fps, width=50, height=50, extra_nets=("GND",)), edge_margin=0.5)
    b.place(Part("r9"), at=Location(20, 20), face=Face.BACK)
    b.place(Part("u1"), at=Near(Location(20.9, 20), radius=4))
    b.via(Net("GND"), PadRef(Part("u1"), "GND"), size=0.45, drill=0.2)
    assert _gap_to_r9(b.resolve()) >= 0.2 - 1e-6


def test_a_cell_carries_the_vias_at_its_members_pads():
    from placemat.values import Cell, Centre
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m"),
           footprint("R9", 20, 20, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    b = Board(board_geometry(fps, cells=["m"], width=50, height=50, extra_nets=("GND",)), edge_margin=0.5)
    b.place(Part("r9"), at=Location(20, 20), face=Face.BACK)
    b.place(Cell("m"), at=Near(Location(20, 20), radius=4))           # the cell's centre, u1's pad 1 then over r9
    b.via(Net("GND"), PadRef(Part("m.u1"), 1), size=0.45, drill=0.2)
    assert _gap_to_r9(b.resolve()) >= 0.2 - 1e-6


def test_a_planned_via_over_another_nets_pad_is_named_as_a_via():
    fps = [footprint("U1", 10, 10, w=3, h=1, inst="u1", nets=("GND", "X")),
           footprint("R9", 10.1, 10, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    b = Board(board_geometry(fps, width=30, height=30, extra_nets=("GND",)), edge_margin=0.5, keep_going=True)
    b.place(Part("r9"), at=Location(10.1, 10), face=Face.BACK)
    b.via(Net("GND"), Location(9.5, 10), size=0.45, drill=0.2)       # on r9's pad 1, through the board
    plan = b.resolve()
    copper = [f for f in plan.findings if f.kind == "copper"]
    assert copper and all("via GND at (9.50, 10.00)" in f for f in copper), copper


def test_a_part_placed_after_a_cell_keeps_off_the_cells_carried_via():
    from placemat.values import Cell, Priority
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m"),
           footprint("R9", 5, 5, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    b = Board(board_geometry(fps, cells=["m"], width=50, height=50, extra_nets=("GND",)), edge_margin=0.5)
    b.place(Cell("m"), at=Near(Location(20, 20), radius=0.2), priority=Priority.HIGH)   # searched, and first
    b.via(Net("GND"), PadRef(Part("m.u1"), 1), size=0.45, drill=0.2)
    b.place(Part("r9"), at=Near(Location(18.9, 20), radius=4), face=Face.BACK)    # searched after, onto the via
    plan = b.resolve()
    assert not [f for f in plan.findings if f.kind == "copper"], list(plan.findings)


def test_a_fixed_parts_via_over_the_other_face_is_a_finding_not_a_stop():
    fps = [footprint("U1", 10, 10, w=3, h=1, inst="u1", nets=("GND", "X")),
           footprint("R9", 9.1, 10, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    b = Board(board_geometry(fps, width=30, height=30, extra_nets=("GND",)), edge_margin=0.5)
    b.place(Part("r9"), at=Location(9.1, 10), face=Face.BACK)
    b.place(Part("u1"), at=Location(10, 10))
    b.via(Net("GND"), PadRef(Part("u1"), 1), size=0.45, drill=0.2)
    plan = b.resolve()                                                   # no PlacementCollision
    assert [f for f in plan.findings if f.kind == "copper"]


def test_a_back_face_searched_part_carries_its_pad_via():
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="u1", nets=("GND", "X"), face=Face.BACK),
           footprint("R9", 20, 20, w=2, h=1, inst="r9", nets=("S", "T"))]
    b = Board(board_geometry(fps, width=50, height=50, extra_nets=("GND",)), edge_margin=0.5)
    b.place(Part("r9"), at=Location(20, 20))
    b.place(Part("u1"), at=Near(Location(20.9, 20), radius=4), face=Face.BACK)
    b.via(Net("GND"), PadRef(Part("u1"), 1), size=0.45, drill=0.2)
    plan = b.resolve()
    at = plan.occupancy.pad_location("U1", "1")
    ring = via_ring(at, 0.45)
    assert min(poly_distance(ring, s.poly) for s in plan.occupancy.items["R9"].shapes if s.kind == "pad") >= 0.2 - 1e-6
