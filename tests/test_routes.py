"""Routed copper kept relative to its pads: adopted from a routed copy,
written beside the script, and drawn again while the parts it joins stand
as they did. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat import routes
from placemat.board_geometry import CopperItem
from placemat.copper import Track, Via
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Location, Part
from tests.fixtures import board_geometry, footprint, rect

F = CopperLayer.F


def _track(net, a, b, w=0.2):
    poly = rect((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, abs(b[0] - a[0]) + w, abs(b[1] - a[1]) + w)
    return CopperItem("track", net, frozenset([F]), (poly,), Box.of_points(poly), None, w, 0.0,
                      (a, b))


def _via(net, at, size=0.6, drill=0.3):
    ring = circle_polygon(Location(*at), size / 2)
    return CopperItem("via", net, frozenset([F, CopperLayer.B]), (ring,), Box.of_points(ring), None, 0.0, drill,
                      (at,))


def _parts():
    return [footprint("U1", 10, 10, w=4, h=1, inst="u1", nets=("A", "X")),       # X on pad 2 at (11.4, 10)
            footprint("R1", 20, 16, w=2, h=1, inst="r1", nets=("X", "B"))]       # X on pad 1 at (19.4, 16)


def _routed():
    placed = board_geometry(_parts(), width=40, height=40)
    routed = dataclasses.replace(placed, copper=tuple(placed.copper) + (
        _track("X", (11.4, 10.0), (15.0, 10.0)), _track("X", (15.0, 10.0), (19.4, 16.0)), _via("X", (15.0, 10.0))))
    return placed, routed


def test_new_copper_is_adopted_bound_to_its_pads():
    placed, routed = _routed()
    (e,) = routes.entries_from(placed, routed, ["X"])
    assert e.net == "X" and len(e.tracks) == 2 and len(e.vias) == 1
    ends = [t["a"] for t in e.tracks] + [t["b"] for t in e.tracks]
    assert ["U1", "2"] in [p.get("pad") for p in ends] and ["R1", "1"] in [p.get("pad") for p in ends]
    bend = [p for p in ends if "anchor" in p][0]
    assert bend["anchor"] == ["U1", "2"] and bend["offset"] == pytest.approx([3.6, 0.0])
    assert set(e.parts) == {"U1", "R1"}


def test_the_file_round_trips_and_a_new_entry_replaces_its_net(tmp_path):
    placed, routed = _routed()
    entries = routes.entries_from(placed, routed, ["X"])
    p = tmp_path / "Board_layout.routes.json"
    routes.write(p, entries)
    assert routes.read(p) == entries
    again = dataclasses.replace(entries[0], adopted="later")
    assert routes.merged(entries, [again]) == [again]


def _occupancy(u1_at=(10, 10), r1_at=(20, 16), u1_rot=0.0, r1_rot=0.0):
    b = Board(board_geometry(_parts(), width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(*u1_at), rotation=u1_rot)
    b.place(Part("r1"), at=Location(*r1_at), rotation=r1_rot)
    return b.resolve().occupancy


def test_an_entry_resolves_to_the_same_copper_where_its_parts_stand():
    placed, routed = _routed()
    (e,) = routes.entries_from(placed, routed, ["X"])
    tracks, vias = routes.resolve(e, _occupancy(), 0.001)
    ends = sorted((round(p.x, 6), round(p.y, 6)) for t in tracks for p in (t.start, t.end))
    assert ends == sorted([(11.4, 10.0), (15.0, 10.0), (15.0, 10.0), (19.4, 16.0)])
    assert [(round(v.at.x, 6), round(v.at.y, 6)) for v in vias] == [(15.0, 10.0)]


def test_parts_moved_and_turned_together_carry_the_copper_with_them():
    placed, routed = _routed()
    (e,) = routes.entries_from(placed, routed, ["X"])
    # U1 to (20, 20) turned 90; R1's offset from it, (10, 6), turns to (6, -10): R1 at (26, 10), turned 90
    occ = _occupancy(u1_at=(20, 20), u1_rot=90, r1_at=(26, 10), r1_rot=90)
    tracks, vias = routes.resolve(e, occ, 0.001)
    assert len(tracks) == 2 and len(vias) == 1
    u1, r1 = occ.pad_location("U1", "2"), occ.pad_location("R1", "1")
    ends = [p for t in tracks for p in (t.start, t.end)]
    # the U1 end was on its pad's centre; the R1 end 0.2 mm off its pad's, and stays so, turned with it
    assert any(p.distance(u1) < 1e-6 for p in ends) and any(abs(p.distance(r1) - 0.2) < 1e-6 for p in ends)


def test_a_part_moved_alone_drops_the_net_naming_it():
    placed, routed = _routed()
    (e,) = routes.entries_from(placed, routed, ["X"])
    why = routes.resolve(e, _occupancy(r1_at=(21, 16)), 0.001)
    assert isinstance(why, str) and "R1" in why


def test_a_point_over_another_nets_pad_binds_to_its_own_net():
    parts = _parts() + [footprint("Q1", 15, 10, w=2, h=1, inst="q1", nets=("Y", "Y"))]
    placed = board_geometry(parts, width=40, height=40)
    routed = dataclasses.replace(placed, copper=tuple(placed.copper) + (
        _track("X", (11.4, 10.0), (14.4, 10.0)), _track("X", (14.4, 10.0), (19.4, 16.0))))
    (e,) = routes.entries_from(placed, routed, ["X"])
    ends = [t["a"] for t in e.tracks] + [t["b"] for t in e.tracks]
    assert not any(p.get("pad", [None])[0] == "Q1" for p in ends)


def _resolved(r1_at):
    placed, routed = _routed()
    (e,) = routes.entries_from(placed, routed, ["X"])
    b = Board(board_geometry(_parts(), width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"), at=Location(*r1_at))
    return b.resolve(routes=[e])


def test_a_run_draws_an_adopted_route_where_its_parts_stand():
    plan = _resolved((20, 16))
    assert plan.adopted == {"X": "held"}
    assert len([c for c in plan.copper if isinstance(c, Track) and c.net == "X"]) == 2
    assert len([c for c in plan.copper if isinstance(c, Via) and c.net == "X"]) == 1


def test_a_run_drops_an_adopted_route_whose_part_moved():
    plan = _resolved((21, 16))
    assert "R1" in plan.adopted["X"]
    assert not [c for c in plan.copper if getattr(c, "net", None) == "X"]
    assert any("adopted route X dropped" in f and "R1" in f for f in plan.findings)


def test_the_routes_file_is_part_of_the_scripts_fingerprint(tmp_path):
    from placemat.project import script_fingerprint
    script = tmp_path / "Board_layout.py"
    script.write_text("x = 1\n")
    before = script_fingerprint(script)
    placed, routed = _routed()
    routes.write(routes.path_for(script), routes.entries_from(placed, routed, ["X"]))
    assert script_fingerprint(script) != before
