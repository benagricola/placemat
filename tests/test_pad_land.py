"""One land of a pin drawn as several lands: PadRef(part, n, land=Land.LARGEST)
or land=k (1-based, in the footprint's order for that number) locates at
that land's centre, and wherever the pad's shapes are read only that land
counts. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat import Land
from placemat import reuse
from placemat.board_geometry import Footprint
from placemat.copper import Track, Via
from placemat.layout import Board, _locate, _pad_shapes
from placemat.values import Box, CopperLayer, Edge, Face, Location, Net, PadRef, Part, Past
from tests.fixtures import board_geometry, footprint, pad


def _part():
    """Pin 1 drawn as two lands: a 1.2 mm square at x = -3 and a 2 mm square
    at x = +2 (the centre of the two is bare board); pin 2 a 1 mm square at
    (0, 3). The footprint's origin at 0, 0."""
    lands = [pad("U1", "u1", 1, "GND", -3.0, 0.0, 1.2, 1.2), pad("U1", "u1", 1, "GND", 2.0, 0.0, 2.0, 2.0),
             pad("U1", "u1", 2, "SIG", 0.0, 3.0, 1.0, 1.0)]
    body = Box.union([p.box for p in lands]).inflate(0.5)
    return Footprint("U1", "u1", None, "U1", Location(0.0, 0.0), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                     tuple(lands))


def _board():
    g = board_geometry([_part(), footprint("R1", 5, 5, w=2, h=1, inst="r1", nets=("GND", "SIG"))],
                       width=50, height=50)
    b = Board(dataclasses.replace(g, hole_to_hole=0.25), edge_margin=0.5)
    b.place(Part("r1"), at=Location(5, 5))
    return b


def _placed():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    return b


def _of(plan, kind):
    return [c for c in plan.copper if isinstance(c, kind)]


def test_largest_locates_at_the_largest_lands_centre():
    b = _placed()
    b.track(Net("GND"), [PadRef(Part("u1"), 1, land=Land.LARGEST), Location(30, 20)], layer=CopperLayer.F)
    (t,) = _of(b.resolve(), Track)
    assert (t.start.x, t.start.y) == pytest.approx((22.0, 20.0))


def test_an_index_names_the_footprints_nth_land_of_that_number():
    b = _placed()
    b.track(Net("GND"), [PadRef(Part("u1"), 1, land=1), Location(17, 28)], layer=CopperLayer.F)
    plan = b.resolve()
    (t,) = _of(plan, Track)
    assert (t.start.x, t.start.y) == pytest.approx((17.0, 20.0))
    assert _locate(b, plan.occupancy, PadRef(Part("u1"), 1, land=2)) == Location(22.0, 20.0)


def test_a_via_grid_fills_one_land_only():
    b = _placed()
    b.vias(Net("GND"), PadRef(Part("u1"), 1, land=Land.LARGEST), size=0.6, drill=0.3)
    vias = _of(b.resolve(), Via)
    assert vias and all(21.0 <= v.at.x <= 23.0 for v in vias)


def test_without_land_the_via_grid_fills_every_land():
    b = _placed()
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    xs = {round(v.at.x) for v in _of(b.resolve(), Via)}
    assert 17 in xs and any(21 <= x <= 23 for x in xs)


def test_past_stands_off_one_land():
    """Past east of land 1 stands the via off that land's east side, between
    the lands, not off the whole pin's (land 2's)."""
    b = _placed()
    b.via(Net("GND"), at=Past([PadRef(Part("u1"), 1, land=1)], Edge.EAST), size=0.6, drill=0.3)
    (v,) = _of(b.resolve(), Via)
    assert 17.6 < v.at.x < 21.0 and v.at.y == pytest.approx(20.0)


def test_a_via_at_a_land_of_a_searched_part_is_carried_there():
    b = _board()
    b.place(Part("u1"))
    b.via(Net("GND"), at=PadRef(Part("u1"), 1, land=1), size=0.6, drill=0.3)
    plan = b.resolve()
    (v,) = _of(plan, Via)
    land = plan.occupancy.pad_location("U1", "1", 0)
    assert (v.at.x, v.at.y) == pytest.approx((land.x, land.y))
    carried = [s for s in plan.occupancy.items["U1"].shapes if s.owner.startswith("via at") and s.kind == "through"]
    assert carried and (carried[0].box.center.x, carried[0].box.center.y) == pytest.approx((land.x, land.y), abs=1e-3)


def test_a_land_past_the_count_is_refused_naming_the_count():
    b = _placed()
    with pytest.raises(ValueError, match="2 lands"):
        b.track(Net("GND"), [PadRef(Part("u1"), 1, land=3), Location(30, 20)], layer=CopperLayer.F)


def test_a_land_is_counted_from_one():
    with pytest.raises(ValueError, match="from 1"):
        PadRef(Part("u1"), 1, land=0)
    with pytest.raises(TypeError, match="Land"):
        PadRef(Part("u1"), 1, land="largest")


def test_a_land_on_a_pin_of_one_land_is_the_pin():
    b = _placed()
    plan = b.resolve()
    plain = PadRef(Part("u1"), 2)
    for ref in (PadRef(Part("u1"), 2, land=Land.LARGEST), PadRef(Part("u1"), 2, land=1)):
        assert _locate(b, plan.occupancy, ref) == _locate(b, plan.occupancy, plain)
        assert _pad_shapes(b, plan.occupancy, ref) == _pad_shapes(b, plan.occupancy, plain)


def test_offset_and_local_keep_the_land():
    ref = PadRef(Part("u1"), 1, land=Land.LARGEST)
    assert ref.offset(1.0, 0.0).land is Land.LARGEST and ref.local(0.0, 1.0).land is Land.LARGEST


def test_a_pad_ref_without_land_digests_as_before():
    assert reuse.canonical(PadRef(Part("u1"), 1)) == \
        "PadRef(part=Part(inst='u1'),key=1,dx=0.0,dy=0.0,pin=None)"
    assert "land=" in reuse.canonical(PadRef(Part("u1"), 1, land=Land.LARGEST))


def test_a_pours_corners_take_one_land():
    from placemat.copper import Pour
    from placemat.values import Cover
    b = _placed()
    b.pour(Net("GND"), [PadRef(Part("u1"), 1, land=2), Location(24, 24), Location(22, 24)], layer=CopperLayer.F,
           cover=Cover.BOX)
    (p,) = _of(b.resolve(), Pour)
    assert Box.of_points(p.points).left == pytest.approx(21.0)      # land 2's west edge, not land 1's


def test_a_cell_placed_by_a_members_land_is_refused():
    from placemat.values import Cell, Pin
    member = dataclasses.replace(_part(), inst="mod.u1", cell="mod",
                                 pads=tuple(dataclasses.replace(p, inst="mod.u1") for p in _part().pads))
    b = Board(board_geometry([member], cells=["mod"], width=50, height=50), edge_margin=0.5)
    with pytest.raises(ValueError, match="land="):
        b.place(Cell("mod"), at=Pin(PadRef(Part("mod.u1"), 1, land=1), 20.0, 20.0))


def test_a_link_to_one_land_is_refused():
    b = _placed()
    with pytest.raises(ValueError, match="land="):
        b.link(PadRef(Part("u1"), 1, land=Land.LARGEST), PadRef(Part("r1"), 1))
