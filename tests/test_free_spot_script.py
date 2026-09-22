"""A via written at the nearest legal spot to a pad, resolved when the pad's
part is placed, against the copper planned before it. Pure."""
from placemat import FreeSpot
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("GND", "SIG")),
           footprint("R1", 20, 26, w=2, h=1, inst="r1", nets=("SIG", "V3"))]
    return Board(board_geometry(fps, width=40, height=40, extra_nets=("GND",)), edge_margin=0.5)


def test_a_free_spot_resolves_to_a_clear_position_near_its_pad():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    (via,) = [c for c in plan.copper if type(c).__name__ == "Via"]
    pad = plan.occupancy.pad_location("U1", "1")
    assert via.at.distance(pad) <= 2.0 + 1e-6
    assert not any("via" in f and "nowhere" in f for f in plan.findings)


def test_a_second_via_near_the_same_pad_lands_clear_of_the_first():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    ref = PadRef(Part("u1"), "GND")
    b.via(Net("GND"), at=FreeSpot(near=ref), why="tap one")
    b.via(Net("SIG"), at=FreeSpot(near=PadRef(Part("u1"), "SIG")), why="tap two")
    plan = b.resolve()
    vias = [c for c in plan.copper if type(c).__name__ == "Via"]
    assert len(vias) == 2
    gap = vias[0].at.distance(vias[1].at) - (vias[0].size + vias[1].size) / 2.0
    assert gap >= 0.2 - 1e-6                       # the class clearance between the two nets


def test_a_free_spot_with_nowhere_to_go_is_a_finding_and_draws_nothing():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND"), radius=0.05), why="tap")
    plan = b.resolve()
    assert not [c for c in plan.copper if type(c).__name__ == "Via"]
    assert any("nowhere" in f for f in plan.findings)


def test_a_free_spot_stays_out_of_its_own_pad():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    (via,) = [c for c in plan.copper if type(c).__name__ == "Via"]
    assert via.at.distance(plan.occupancy.pad_location("U1", "1")) > 0.4
