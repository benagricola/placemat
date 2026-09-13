from placemat.occupancy import Occupancy
import pytest
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


def test_two_cells_may_overlap_by_box_when_their_parts_do_not():
    # an L-shaped cell: a wide part at the top, a narrow one below it on the left
    fps = [footprint("U1", 10, 10, w=10, h=2, cell="a", inst="a.u"),
           footprint("R1", 6, 14, w=2, h=2, cell="a", inst="a.r"),
           footprint("R2", 30, 30, w=2, h=2, cell="b", inst="b.r")]
    occ = Occupancy(board_geometry(fps, cells=["a", "b"], width=50, height=50), edge_margin=0.0)
    a, b = occ.geometry.cell("a"), occ.geometry.cell("b")
    # drop b's part into the empty corner of a's box (right of R1, below U1)
    inside_a = Location(12.0, 14.0)
    assert a.box.contains_point(inside_a)
    assert occ.legal(b, Placement(inside_a, 0, Face.FRONT)) is None


def test_a_zone_fill_never_blocks_a_placement():
    """A board read back with a ground fill on it must still accept a part
    where the fill is: the fill pulls back round the part when refilled."""
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.board_geometry import CopperItem
    from placemat.values import CopperLayer, Face, Location
    from tests.fixtures import board_geometry, footprint, rect
    fp = footprint("R1", 10, 10, inst="r1", nets=("A", "B"))
    fill = rect(25, 25, 40, 40)
    zone = CopperItem("zone", "GND", frozenset([CopperLayer.F]), (fill,), __import__("placemat.values", fromlist=["Box"]).Box.of_points(fill), None)
    g = board_geometry([fp], copper=[zone], width=50, height=50)
    occ = Occupancy(g, 1.0)
    assert occ.legal(fp, Placement(Location(25, 25), 0, Face.FRONT)) is None


def test_a_scan_may_hand_legal_a_prefiltered_obstacle_list_and_get_the_same_answer():
    """The obstacles near a search region are gathered once per scan; a
    candidate is then checked against those only, with the same verdict."""
    from placemat.placement import Placement
    from placemat.values import Face
    fps = [footprint("U1", 10, 10, w=4, h=2), footprint("R1", 13, 10, w=2, h=1), footprint("R9", 40, 40, w=2, h=1)]
    g = board_geometry(fps, width=50, height=50)
    occ = Occupancy(g, edge_margin=0.0, board_box=g.outline_box)
    geom = occ._geometry(fps[0])
    near = occ.obstacles(geom, Box(5, 5, 20, 15))
    assert {s.owner for s in near} == {"R1"}                       # R9 is far from the region
    p = Placement(Location(11.5, 10), 0, Face.FRONT)
    assert occ.legal(fps[0], p) == occ.legal(fps[0], p, others=near) and occ.legal(fps[0], p)
    far = Placement(Location(20, 30), 0, Face.FRONT)
    assert occ.legal(fps[0], far) is None and occ.legal(fps[0], far, others=near) is None


def test_candidate_pad_locations_are_the_transformed_pad_centres():
    from placemat.placement import Placement
    from placemat.values import Face
    fps = [footprint("U1", 10, 10, w=4, h=2)]
    occ = Occupancy(board_geometry(fps, width=50, height=50), edge_margin=0.0)
    pads = occ.candidate_pad_locations(fps[0], Placement(Location(20, 20), 90, Face.FRONT))
    # pad 1 sits 1.4 west of the origin at rotation 0; at 90 (KiCad's sense) it turns onto the y axis
    assert pads[("U1", "1")].distance(Location(20, 20)) == pytest.approx(1.4)
    assert pads[("U1", "1")].x == pytest.approx(20.0)


def test_a_declared_part_not_yet_placed_is_not_an_obstacle_where_the_generator_left_it():
    """A fresh generation drops every part somewhere. A part the script
    will place later must not block a firm item now; an undeclared part
    stays where it is and does block."""
    from placemat.layout import Board
    from placemat.values import Part
    fps = [footprint("U1", 10, 10, w=4, h=2), footprint("R1", 20, 20, w=2, h=1), footprint("R2", 30, 30, w=2, h=1)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))                  # where R1 sits now
    b.place(Part("r1"))                                       # R1 will be searched later
    plan = b.resolve()
    assert plan.findings == [] and plan.box("r1").overlaps(plan.box("u1")) is False
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(30, 30))                  # where the undeclared R2 sits
    import pytest
    from placemat.layout import PlacementCollision
    with pytest.raises(PlacementCollision):
        b.resolve()
