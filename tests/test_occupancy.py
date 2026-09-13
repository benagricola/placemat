from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint, track


def occ_with(*fps, **kw):
    return Occupancy(board_geometry(list(fps), **kw), edge_margin=1.0)


def test_a_part_may_sit_where_nothing_else_is():
    occ = occ_with(footprint("R1", 10, 10))
    r2 = footprint("R2", 30, 30)
    assert occ.legal(r2, Placement(Location(30, 30), 0, Face.FRONT)) is None


def test_courtyards_on_the_same_face_may_not_overlap():
    occ = occ_with(footprint("R1", 10, 10))
    r2 = footprint("R2", 30, 30)
    why = occ.legal(r2, Placement(Location(12, 10), 0, Face.FRONT))
    assert why is not None and "R1" in why and "courtyard" in why


def test_smd_parts_on_opposite_faces_may_share_an_xy():
    occ = occ_with(footprint("R1", 10, 10))
    r2 = footprint("R2", 30, 30, face=Face.BACK)
    assert occ.legal(r2, Placement(Location(10, 10), 0, Face.BACK)) is None


def test_a_through_hole_part_blocks_both_faces():
    occ = occ_with(footprint("J1", 10, 10, through=True))
    r2 = footprint("R2", 30, 30, face=Face.BACK)
    why = occ.legal(r2, Placement(Location(10, 10), 0, Face.BACK))
    assert why is not None and "J1" in why


def test_a_pad_may_not_come_within_clearance_of_foreign_copper():
    occ = Occupancy(board_geometry([footprint("R1", 10, 10)],
                             copper=[track("X", 20, 5, 20, 40)]), edge_margin=1.0)
    r2 = footprint("R2", 30, 30)
    # pad 2's east edge would land 0.1 mm short of the track: inside the 0.2 clearance
    why = occ.legal(r2, Placement(Location(18.0 - 0.15 + 0.1, 20), 0, Face.FRONT))
    assert why is not None and "X" in why
    assert occ.legal(r2, Placement(Location(15, 20), 0, Face.FRONT)) is None


def test_same_net_copper_is_not_an_obstacle_to_a_pad():
    occ = Occupancy(board_geometry([footprint("R1", 10, 10)],
                             copper=[track("B", 20, 5, 20, 40)]), edge_margin=1.0)
    r2 = footprint("R2", 30, 30)          # pad 2 carries net B
    assert occ.legal(r2, Placement(Location(18.0, 20), 0, Face.FRONT)) is None


def test_the_board_edge_margin_is_enforced():
    occ = occ_with(footprint("R1", 10, 10))
    r2 = footprint("R2", 30, 30)
    assert "edge" in occ.legal(r2, Placement(Location(2.0, 30), 0, Face.FRONT))
    assert occ.legal(r2, Placement(Location(3.1, 30), 0, Face.FRONT)) is None


def test_a_part_does_not_collide_with_its_own_current_geometry():
    r1 = footprint("R1", 10, 10)
    occ = occ_with(r1)
    assert occ.legal(r1, Placement(Location(10.5, 10), 0, Face.FRONT)) is None


def test_rotation_is_applied_to_the_candidate():
    occ = occ_with(footprint("R1", 10, 10, w=1, h=1))
    r2 = footprint("R2", 30, 30, w=6, h=1)       # 6 wide: at rotation 0 it reaches R1
    assert occ.legal(r2, Placement(Location(13.5, 10), 0, Face.FRONT)) is not None
    assert occ.legal(r2, Placement(Location(13.5, 10), 90, Face.FRONT)) is None


def test_a_reservation_blocks_parts_but_lets_its_own_nets_through():
    occ = occ_with(footprint("R1", 10, 10))
    occ.reserve(Box(20, 20, 30, 30), why="the V48 bar", allow=("A",), layer=None)
    r2 = footprint("R2", 30, 30, nets=("C", "D"))
    assert "V48 bar" in occ.legal(r2, Placement(Location(25, 25), 0, Face.FRONT))
    r3 = footprint("R3", 30, 30, nets=("A", "GND"))
    assert occ.legal(r3, Placement(Location(25, 25), 0, Face.FRONT)) is None


from placemat.values import Box  # noqa: E402  (used by the reservation test)


def test_free_area_is_the_board_less_the_courtyards_on_a_face():
    occ = Occupancy(board_geometry([footprint("R1", 10, 10, w=4, h=2), footprint("R2", 30, 30, w=4, h=2, face=Face.BACK)],
                                   width=50, height=40), edge_margin=0.0)
    # courtyard = body inflated by 0.1: (4.2 x 2.2) = 9.24 mm2 each
    assert abs(occ.free_area(Face.FRONT) - (2000.0 - 9.24)) < 1e-6
    assert abs(occ.free_area(Face.BACK) - (2000.0 - 9.24)) < 1e-6
    assert abs(occ.free_area() - (4000.0 - 18.48)) < 1e-6
