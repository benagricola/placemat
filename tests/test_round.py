"""A round board: the disc outline, places said as a bearing and a radius,
and the ring that is a row's circular equivalent. Bearings are degrees
clockwise from the top, so they read like a compass and like a clock."""
import math

import pytest

from placemat.copper import Zone
from placemat.layout import Board
from placemat.values import (CopperLayer, Disc, Edge, Fraction, Location, Net, OnBore, OnEdge, OnRim,
                             Part, Polar, Priority)
from tests.fixtures import board_geometry, footprint

SHAPES = {"j1": ("J1", 6.0, 4.0), "r1": ("R1", 2.0, 1.2), "u1": ("U1", 4.0, 4.0),
          "d1": ("D1", 1.6, 0.8), "d2": ("D2", 1.6, 0.8), "d3": ("D3", 1.6, 0.8), "d4": ("D4", 1.6, 0.8)}


def make_board(*insts, margin=0.5, keep_going=False):
    """A 40 mm disc's worth of board with only the parts a test places. The
    generator drops them east of the disc, so a part the script never places
    is not an obstacle inside it."""
    fps = [footprint(SHAPES[i][0], 50.0, 3.0 + n * 6.0, w=SHAPES[i][1], h=SHAPES[i][2], inst=i, nets=("M", "GND"))
           for n, i in enumerate(insts)]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=margin, keep_going=keep_going)


def corners(box):
    return [Location(box.left, box.top), Location(box.right, box.top),
            Location(box.right, box.bottom), Location(box.left, box.bottom)]


def reach_of(plan, ref):
    g = plan.occupancy.items[ref]
    return g.reach or g.body


def far_from(plan, ref, centre):
    return max(c.distance(centre) for c in corners(reach_of(plan, ref)))


def bearing_at(plan, key, centre):
    c = plan.box(key).center
    return math.degrees(math.atan2(c.x - centre.x, centre.y - c.y)) % 360.0


def test_a_disc_is_a_round_board_at_the_origin():
    b = make_board()
    b.disc(diameter=40.0, hole=6.0)
    assert b.centre == Location(20.0, 20.0) and b.radius == 20.0 and b.bore == 3.0
    plan = b.resolve()
    assert plan.shape == Disc(Location(20.0, 20.0), 40.0, 6.0)
    assert (b.width, b.height) == (40.0, 40.0)         # the frame round it, for anything that measures a box


def test_an_item_on_the_rim_sits_at_the_keep_in_on_its_bearing():
    b = make_board("j1")
    b.disc(diameter=40.0)
    b.place(Part("j1"), at=OnRim(Edge.EAST))
    plan = b.resolve()
    assert far_from(plan, "J1", b.centre) == pytest.approx(19.5, abs=1e-6)   # its reach at the board's keep-in
    assert plan.box("j1").center.y == pytest.approx(20.0)
    assert plan.box("j1").center.x > 20.0              # due east of the centre
    assert plan.step("j1").priority is Priority.EDGE


def test_a_rim_item_turns_to_face_outward():
    for angle, rotation in [(Edge.NORTH, 180.0), (Edge.EAST, 90.0), (Edge.SOUTH, 0.0), (135.0, 45.0)]:
        b = make_board("j1")
        b.disc(diameter=40.0)
        b.place(Part("j1"), at=OnRim(angle))
        assert b.resolve().placement("j1").rotation == pytest.approx(rotation)


def test_a_bearing_may_be_a_number_an_edge_or_a_fraction_of_the_turn():
    places = []
    for angle in (180.0, Edge.SOUTH, Fraction(0.5)):
        b = make_board("j1")
        b.disc(diameter=40.0)
        b.place(Part("j1"), at=OnRim(angle))
        places.append(b.resolve().placement("j1"))
    assert places[0] == places[1] == places[2]


def test_an_item_may_overhang_the_rim():
    b = make_board("j1")
    b.disc(diameter=40.0)
    b.place(Part("j1"), at=OnRim(Edge.EAST, overhang=0.5))
    plan = b.resolve()
    assert far_from(plan, "J1", b.centre) == pytest.approx(20.5, abs=1e-6)
    assert plan.findings == []                          # declared to overhang, so the keep-in does not refuse it


def test_polar_puts_a_body_centre_at_a_radius_and_bearing():
    b = make_board("r1")
    b.disc(diameter=40.0)
    b.place(Part("r1"), at=Polar(10.0, Edge.EAST))
    plan = b.resolve()
    assert plan.box("r1").center == Location(30.0, 20.0)
    assert plan.placement("r1").rotation == 0.0        # a coordinate, not an edge: it is not turned
    assert plan.step("r1").priority is Priority.FIXED


def test_polar_may_leave_the_ring_or_the_spoke_free():
    b = make_board("u1", "r1")
    b.disc(diameter=40.0)
    b.place(Part("u1"), at=Polar(12.0, Edge.NORTH))
    b.place(Part("r1"), at=Polar(12.0))                # somewhere on that ring
    plan = b.resolve()
    assert plan.box("r1").center.distance(b.centre) == pytest.approx(12.0, abs=1e-6)
    assert plan.findings == []
    b2 = make_board("r1")
    b2.disc(diameter=40.0, hole=8.0)
    b2.place(Part("r1"), at=Polar(None, Edge.EAST))    # out along that spoke
    plan2 = b2.resolve()
    assert plan2.box("r1").center.y == pytest.approx(20.0)
    assert 4.5 < plan2.box("r1").center.x - 20.0 < 19.5


def test_the_rim_and_the_bore_each_keep_the_boards_margin():
    b = make_board("u1", keep_going=True)
    b.disc(diameter=40.0, hole=10.0)
    b.place(Part("u1"), at=Polar(0.0, 0.0))            # dead centre: inside the bore
    assert any("bore" in f for f in b.resolve().findings)
    b2 = make_board("u1", keep_going=True)
    b2.disc(diameter=40.0, hole=10.0)
    b2.place(Part("u1"), at=Polar(19.5, 0.0))          # its body past the rim's keep-in
    assert any("rim" in f for f in b2.resolve().findings)


def test_an_item_at_the_bore_stands_off_it_and_faces_it():
    b = make_board("d1")
    b.disc(diameter=40.0, hole=10.0)
    b.place(Part("d1"), at=OnBore(Edge.NORTH))
    plan = b.resolve()
    box = reach_of(plan, "D1")                          # the nearest POINT of it, an edge when it straddles the bore
    dx = max(box.left - b.centre.x, 0.0, b.centre.x - box.right)
    dy = max(box.top - b.centre.y, 0.0, b.centre.y - box.bottom)
    assert math.hypot(dx, dy) == pytest.approx(5.5, abs=1e-6)   # the bore's radius plus the keep-in
    assert plan.box("d1").center.y < 20.0              # north of the centre
    assert plan.placement("d1").rotation == pytest.approx(0.0)   # its outward side turned to face the bore, southward
    assert plan.findings == []


def test_a_free_rim_item_slides_round_the_rim_to_the_room_that_is_left():
    b = make_board("j1", "u1")
    b.disc(diameter=40.0)
    b.place(Part("j1"), at=OnRim(Edge.NORTH))
    b.place(Part("u1"), at=OnRim())
    plan = b.resolve()
    assert plan.findings == []                          # it found a place, and nothing is on anything
    assert far_from(plan, "U1", b.centre) == pytest.approx(19.5, abs=1e-6)   # still hard against the keep-in
    landed = bearing_at(plan, "u1", b.centre)
    assert min(landed, 360.0 - landed) > 5.0                                 # it moved off the top, where J1 sits
    assert plan.placement("u1").rotation == pytest.approx((180.0 - landed) % 360.0, abs=1.0)   # facing out where it landed
    assert "round the rim" in plan.step("u1").note


def test_a_ring_spaces_its_items_round_the_arc_by_what_they_claim():
    b = make_board("d1", "d2", "d3")
    b.disc(diameter=40.0)
    ring = b.ring([Part("d1"), Part("d2"), Part("d3")], radius=15.0)
    plan = b.resolve()
    assert plan.findings == []
    for key in ("d1", "d2", "d3"):
        assert plan.box(key).center.distance(b.centre) == pytest.approx(15.0, abs=1e-6)
    steps = [ring.angles[1] - ring.angles[0], ring.angles[2] - ring.angles[1]]
    assert steps[0] == pytest.approx(steps[1], abs=1e-9)          # the same part, so the same step
    # a claim 1.8 wide is held apart at its inner corners, 15 - 0.5 out
    claim = b.claim(Part("d1"))                                   # 1.8 x 1.0: the part and its courtyard
    half = math.degrees(math.atan2(claim.width / 2.0, 15.0 - claim.height / 2.0))
    assert steps[0] == pytest.approx(2 * half + math.degrees(0.02 / 15.0), abs=1e-9)
    assert ring.radius == 15.0 and len(ring.angles) == 3


def test_a_ring_may_spread_its_items_evenly_round_the_turn():
    b = make_board("d1", "d2", "d3", "d4")
    b.disc(diameter=40.0)
    ring = b.ring([Part("d1"), Part("d2"), Part("d3"), Part("d4")], radius=16.0, spread=True)
    assert ring.angles == pytest.approx([0.0, 90.0, 180.0, 270.0])
    plan = b.resolve()
    assert plan.box("d1").center == Location(20.0, 4.0)           # at the top, 16 out
    assert plan.box("d3").center == Location(20.0, 36.0)
    assert plan.findings == []


def test_a_ring_with_no_radius_puts_every_item_at_the_rim():
    b = make_board("d1", "d2", "d3")
    b.disc(diameter=40.0)
    b.ring([Part("d1"), Part("d2"), Part("d3")], radius=None, start=Edge.SOUTH)
    plan = b.resolve()
    assert plan.findings == []
    for ref in ("D1", "D2", "D3"):
        assert far_from(plan, ref, b.centre) == pytest.approx(19.5, abs=1e-6)


def test_a_disc_has_no_edges_and_a_rectangle_has_no_rim():
    b = make_board("d1")
    b.disc(diameter=40.0)
    with pytest.raises(ValueError, match="ring"):
        b.row([Part("d1")], Edge.NORTH)
    with pytest.raises(ValueError, match="rim"):
        b.place(Part("d1"), at=OnEdge(Edge.NORTH))
    flat = make_board("d1")
    flat.size(40.0, 40.0)
    with pytest.raises(ValueError, match="disc"):
        flat.place(Part("d1"), at=OnRim(Edge.NORTH))
    with pytest.raises(ValueError, match="disc"):
        flat.ring([Part("d1")], radius=None)        # a ring AT THE RIM needs a rim; one at a radius does not


def test_the_plane_of_a_round_board_is_a_disc_inset_from_the_rim():
    b = make_board("d1")
    b.disc(diameter=40.0)
    b.plane(Net("GND"), layers=(CopperLayer.B,), inset=0.4)
    plan = b.resolve()
    (zone,) = [op for op in plan.copper if isinstance(op, Zone)]
    radii = {round(math.hypot(x - 20.0, y - 20.0), 6) for x, y in zone.points}
    assert radii == {19.6}
    assert len(zone.points) >= 32                                  # a circle drawn as a polygon


def test_a_round_board_still_takes_plain_coordinates():
    """A disc changes what an EDGE means, nothing else: an origin, a body
    centre said in references, and a pinned axis all work as they do on a
    rectangle, so one board can mix the two."""
    from placemat.values import Centre, X, Y
    b = make_board("j1", "r1", "u1")
    b.disc(diameter=40.0)
    b.place(Part("j1"), at=Location(18.0, 6.0))                     # an origin, exactly as on any board
    b.place(Part("r1"), at=Centre(X(b.centre), Y(b.centre, 6.0)))   # 6 mm south of the board's centre
    b.place(Part("u1"), at=Centre(X(b.centre, -8.0), None))         # pinned in x, free to slide in y
    plan = b.resolve()
    assert plan.findings == []
    assert plan.placement("j1").location == Location(18.0, 6.0)
    assert plan.box("r1").center == Location(20.0, 26.0)
    assert plan.box("u1").center.x == pytest.approx(12.0)
    assert 0.5 < plan.box("u1").center.y < 39.5


def test_polar_measures_from_a_centre_so_it_works_on_any_board():
    b = make_board("d1", "d2")
    b.size(40.0, 40.0)
    b.place(Part("d1"), at=Polar(10.0, Edge.EAST))                  # about the board's centre
    b.place(Part("d2"), at=Polar(5.0, Edge.NORTH, about=Location(10.0, 30.0)))
    plan = b.resolve()
    assert plan.box("d1").center == Location(30.0, 20.0)
    assert plan.box("d2").center == Location(10.0, 25.0)
    assert plan.findings == []


def test_a_ring_may_sit_about_a_point_on_a_square_board():
    b = make_board("d1", "d2", "d3", "d4")
    b.size(40.0, 40.0)
    ring = b.ring([Part("d1"), Part("d2"), Part("d3"), Part("d4")], radius=8.0,
                  about=Location(12.0, 12.0), spread=True)
    plan = b.resolve()
    assert ring.angles == pytest.approx([0.0, 90.0, 180.0, 270.0])
    assert plan.box("d1").center == Location(12.0, 4.0)
    assert plan.box("d2").center == Location(20.0, 12.0)
    assert plan.findings == []
