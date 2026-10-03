"""A pad filled with vias: a square grid at the hole-to-hole rule, in the
part's frame, kept where the whole via lies in the pad's copper. Pure."""
import dataclasses

import pytest

from placemat import FreeSpot
from placemat.board_geometry import Footprint, PadGeom
from placemat.copper import Via
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Face, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint, pad


def _part(lands, inst="u1", ref="U1"):
    body = Box.union([p.box for p in lands]).inflate(0.5)
    c = body.center
    return Footprint(ref, inst, None, ref, c, 0.0, Face.FRONT, body, body.inflate(0.1), body, tuple(lands))


def _board(lands, **kw):
    g = board_geometry([_part(lands), footprint("R1", 5, 5, w=2, h=1, inst="r1", nets=("GND", "SIG"))],
                       width=40, height=40)
    g = dataclasses.replace(g, hole_to_hole=0.25)
    return Board(g, edge_margin=0.5), g


def _vias(plan):
    return [c for c in plan.copper if isinstance(c, Via)]


def _square(size=3.0):
    return [pad("U1", "u1", 1, "GND", 20, 20, size, size), pad("U1", "u1", 2, "SIG", 20, 23, 1, 1)]


def test_a_square_pad_is_filled_at_the_rule():
    b, g = _board(_square())
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    plan = b.resolve()
    vias = _vias(plan)
    c = plan.occupancy.pad_location("U1", "1")
    offsets = sorted({round(v.at.x - c.x, 3) for v in vias})
    assert offsets == [-1.2, -0.6, 0.0, 0.6, 1.2] and len(vias) == 25     # the outer vias' copper reaches the edge
    assert "in the pad" in plan.step("vias GND").note and "fab" in plan.step("vias GND").note
    assert all(abs(v.at.x - c.x) + 0.3 <= 1.5 + 1e-6 and abs(v.at.y - c.y) + 0.3 <= 1.5 + 1e-6 for v in vias)


def test_the_grid_turns_with_its_part():
    b, g = _board(_square(3.0)[:1] + [pad("U1", "u1", 2, "SIG", 22.5, 20, 1, 1)])
    b.place(Part("u1"), at=Location(21.25, 20), rotation=90)
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    plan = b.resolve()
    c = plan.occupancy.pad_location("U1", "1")
    assert sorted({round(v.at.y - c.y, 3) for v in _vias(plan)}) == [-1.2, -0.6, 0.0, 0.6, 1.2]


def test_a_round_pad_keeps_only_whole_vias():
    ring = circle_polygon(Location(20, 20), 1.2, 32)
    round_pad = PadGeom("U1", "u1", "1", "GND", frozenset([CopperLayer.F]), (ring,), Box.of_points(ring), False, 0.0)
    b, g = _board([round_pad, pad("U1", "u1", 2, "SIG", 20, 23, 1, 1)])
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    vias = _vias(b.resolve())
    assert vias and all(v.at.distance(Location(20, 20)) + 0.3 <= 1.2 + 1e-6 for v in vias)


def test_a_pad_too_small_for_a_via_is_a_finding():
    b, g = _board(_square(0.4))
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    plan = b.resolve()
    assert not _vias(plan) and any("no via fits" in f for f in plan.findings)


def test_a_pitch_under_the_hole_to_hole_rule_is_refused():
    b, g = _board(_square())
    with pytest.raises(ValueError, match="hole-to-hole"):
        b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.4, drill=0.3, pitch=0.4)


def test_each_land_of_a_pin_is_filled_and_nothing_between():
    lands = [pad("U1", "u1", 1, "GND", 19, 20, 1.0, 1.0), pad("U1", "u1", 1, "GND", 21, 20, 1.0, 1.0),
             pad("U1", "u1", 2, "SIG", 20, 23, 1, 1)]
    b, g = _board(lands)
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    vias = _vias(b.resolve())
    assert {round(v.at.x) for v in vias} == {19, 21}


def test_a_later_free_spot_keeps_the_rule_from_the_grid():
    b, g = _board(_square())
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    b.via(Net("SIG"), at=FreeSpot(near=PadRef(Part("u1"), 2)), why="tap")
    vias = _vias(b.resolve())
    sig = [v for v in vias if v.net == "SIG"]
    assert sig and all(s.at.distance(v.at) - (s.drill + v.drill) / 2 >= 0.25 - 1e-6 for s in sig for v in vias if v is not s)


def test_a_via_in_the_pad_keeps_off_another_nets_copper_on_the_far_side():
    """A via goes through every layer: a pad of another net on the back,
    under the filled pad, keeps the vias off it."""
    under = footprint("C9", 20, 20, w=1.2, h=0.6, inst="c9", nets=("SIG", "SIG"), face=Face.BACK)
    g = board_geometry([_part(_square()), under, footprint("R1", 5, 5, w=2, h=1, inst="r1", nets=("GND", "SIG"))],
                       width=40, height=40)
    b = Board(dataclasses.replace(g, hole_to_hole=0.25), edge_margin=0.5)
    b.plane(Net("GND"), [CopperLayer.B])        # a plane net's vias may be dropped for the pad
    b.place(Part("u1"), at=Location(20, 21.5))
    b.place(Part("c9"), at=Location(20, 20.5), face=Face.BACK)
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    plan = b.resolve()
    from placemat.geometry import poly_distance
    backs = [sh.poly for sh in plan.occupancy.items["C9"].shapes if sh.kind == "pad"]
    vias = _vias(plan)
    assert vias and all(poly_distance(v.polygon, q) >= 0.2 - 1e-6 for v in vias for q in backs)


def _clear_of_holes(vias, holes, rule):
    return all(v.at.distance(h) - (v.drill + d) / 2.0 >= rule - 1e-6 for v in vias for h, d in holes)


def test_vias_keep_off_another_nets_track_declared_in_the_same_batch():
    from placemat.copper import Track
    from placemat.geometry import poly_distance
    b, g = _board(_square())
    b.place(Part("u1"), at=Location(20, 21.5))
    b.track(Net("SIG"), [PadRef(Part("u1"), 2), Location(20, 23.5), Location(20, 17.5)], layer=CopperLayer.B)
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    plan = b.resolve()
    sig = [t for t in plan.copper if isinstance(t, Track) and t.net == "SIG"]
    vias = _vias(plan)
    assert vias and sig and all(poly_distance(v.polygon, t.polygon) >= 0.2 - 1e-6 for v in vias for t in sig)


def test_a_pin_with_its_own_holes_keeps_the_rule_from_each():
    """An exposed pad drawn with thermal holes, numbered as the same pin: the
    grid keeps the hole-to-hole rule from each of the pin's own holes."""
    lands = [pad("U1", "u1", 1, "GND", 20, 20, 3.0, 3.0)] + [
        pad("U1", "u1", 1, "GND", 20 + dx, 20 + dy, 0.6, 0.6, True) for dx in (-1.0, 1.0) for dy in (-1.0, 1.0)] + [
        pad("U1", "u1", 2, "SIG", 20, 23, 1, 1)]
    lands = [dataclasses.replace(p, drill_mm=0.3) if p.through else p for p in lands]
    b, g = _board(lands)
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    plan = b.resolve()
    own = [(sh.box.center, 0.3) for sh in plan.occupancy.items["U1"].shapes if sh.kind == "through" and not sh.carried]
    vias = _vias(plan)
    assert vias and len(own) == 4 and _clear_of_holes(vias, own, 0.25)


def test_two_lands_of_a_pin_on_both_faces_do_not_stack_drills():
    front = pad("U1", "u1", 1, "GND", 20, 20, 3.0, 3.0)
    back = dataclasses.replace(front, layers=frozenset([CopperLayer.B]))
    b, g = _board([front, back, pad("U1", "u1", 2, "SIG", 20, 23, 1, 1)])
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    vias = _vias(b.resolve())
    assert len({(round(v.at.x, 4), round(v.at.y, 4)) for v in vias}) == len(vias) == 25


def test_a_part_at_an_odd_angle_gets_the_same_grid_in_its_own_frame():
    rect = [pad("U1", "u1", 1, "GND", 20, 20, 3.0, 2.0), pad("U1", "u1", 2, "SIG", 20, 23, 1, 1)]
    counts = {}
    for rot in (0, 30, 45):
        b, g = _board(rect)
        b.place(Part("u1"), at=Location(20, 21.5), rotation=rot)
        b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
        counts[rot] = len(_vias(b.resolve()))
    assert counts == {0: 15, 30: 15, 45: 15}


def test_a_free_spot_after_the_grid_keeps_a_binding_hole_to_hole_rule():
    b, g = _board(_square())
    b = Board(dataclasses.replace(g, hole_to_hole=0.9), edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3, pitch=1.2)
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), 1), in_pad=True, tail=False), why="one more")
    vias = _vias(b.resolve())
    assert len(vias) >= 2
    assert all(a.at.distance(c.at) - 0.3 >= 0.9 - 1e-6 for a in vias for c in vias if a is not c)


def test_a_negative_inset_is_refused():
    b, g = _board(_square())
    with pytest.raises(ValueError, match="inset"):
        b.vias(Net("GND"), PadRef(Part("u1"), 1), inset=-0.1)
