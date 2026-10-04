# tests/test_arrangement_occupancy.py
import dataclasses

from placemat import reuse
from placemat.board_geometry import CopperItem
from placemat.copper import Track, Zone
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Box, CopperLayer, Face, Location
from tests.arrangement_support import east_doc, stamped_geometry, with_arrangement, footprint, board_geometry


def pads(geom, owner=None):
    return sorted((s.net, round(s.box.center.x, 3), round(s.box.center.y, 3)) for s in geom.shapes
                  if s.kind == "pad" and (owner is None or s.owner == owner))


def test_a_placement_serialises_as_it_did_and_gains_an_element_only_for_an_arrangement():
    p = Placement(Location(1.0, 2.0), 90.0, Face.FRONT)
    assert reuse.placement_to_json(p) == [1.0, 2.0, 90.0, "front"]
    q = dataclasses.replace(p, arrangement="c_in.east")
    assert reuse.placement_to_json(q) == [1.0, 2.0, 90.0, "front", "c_in.east"]
    assert reuse.placement_from_json([1.0, 2.0, 90.0, "front"]) == p and reuse.placement_from_json(reuse.placement_to_json(q)) == q
    assert q.moved(1.0, 0.0).arrangement == "c_in.east" and q.at(Location(0, 0)).arrangement == "c_in.east"


def test_an_arranged_cells_geometry_is_its_members_moved_by_their_delta():
    g = with_arrangement()
    occ = Occupancy(g)
    cell = g.cells["mod"]
    default = occ._geometry(cell)
    arranged = occ._geometry(cell.arranged("c_in.east"))
    assert default is occ._geometry(cell) and arranged is occ._geometry(cell.arranged("c_in.east")) and arranged is not default
    assert [p[0] for p in sorted(pads(default, "C1"), key=lambda p: p[1])] == ["mod.VIN", "mod.GND"]
    assert [p[0] for p in sorted(pads(arranged, "C1"), key=lambda p: p[1])] == ["mod.GND", "mod.VIN"]      # turned half way round
    assert min(p[1] for p in pads(arranged, "C1")) > max(p[1] for p in pads(arranged, "U1"))                  # and east of u1
    assert pads(arranged, "U1") == pads(default, "U1")
    assert arranged.body.center.x > default.body.center.x


def test_it_equals_the_geometry_of_a_cell_stamped_from_a_fragment_whose_default_is_that_arrangement():
    g = with_arrangement()
    arranged = Occupancy(g)._geometry(g.cells["mod"].arranged("c_in.east"))
    fps = [footprint("C1", 41.0, 13.0, w=3, h=1.6, nets=("mod.GND", "mod.VIN"), cell="mod", inst="mod.c_in", rotation=180.0),
           footprint("U1", 36.0, 13.0, w=6, h=4, nets=("mod.VIN", "mod.OUT"), cell="mod", inst="mod.u1"),
           footprint("R9", 5, 5, nets=("mod.OUT", "GND"))]
    stamped = board_geometry(fps, cells=["mod"], extra_nets=("mod.GND", "GND"), width=80, height=60)
    direct = Occupancy(stamped)._geometry(stamped.cells["mod"])
    assert pads(arranged) == pads(direct)
    assert abs(arranged.body.left - direct.body.left) < 1e-3 and abs(arranged.body.right - direct.body.right) < 1e-3


def test_committing_an_arranged_cell_leaves_its_members_where_the_arrangement_puts_them():
    g = with_arrangement()
    occ = Occupancy(g)
    cell = g.cells["mod"]
    arr = cell.arranged("c_in.east")
    placement = Placement(Location(50.0, 20.0), 0.0, Face.FRONT, "c_in.east")
    occ.commit(cell, placement)                                 # the default item and a placement that names the arrangement
    moved = occ.items["C1"].reference
    base = occ._geometry(arr).reference                         # the cell's reference point is the arranged box centre
    assert moved.rotation == 180.0 and abs(moved.location.x - (50.0 + dict(arr.poses)["C1"].location.x - base.location.x)) < 1e-6
    assert occ.items["U1"].reference.rotation == 0.0


def test_the_default_cell_is_committed_as_before():
    g = stamped_geometry()
    a, b = Occupancy(g), Occupancy(g)
    cell = g.cells["mod"]
    a.commit(cell, Placement(Location(50.0, 20.0)))
    b.commit(cell, Placement(Location(50.0, 20.0), 0.0, Face.FRONT, ""))
    assert a.items["C1"].reference == b.items["C1"].reference


def test_an_arranged_cells_own_copper_replaces_the_defaults_when_committed():
    """The default's stamped track goes with the cell; the arrangement's own track stands in its place, moved with the cell."""
    track = Track("mod.GND", CopperLayer.F, 0.3, Location(30.0, 14.0), Location(32.0, 14.0))
    item = CopperItem("track", track.net, frozenset([track.layer]), (track.polygon,), track.box, "mod", track.width, 0.0,
                      ((30.0, 14.0), (32.0, 14.0)), track.length)
    g = with_arrangement(stamped_geometry(copper=(item,)))
    occ = Occupancy(g)
    cell = g.cells["mod"]
    arr = cell.arranged("c_in.east")
    base = occ._geometry(arr).reference.location
    occ.commit(cell, Placement(Location(50.0, 20.0), 0.0, Face.FRONT, "c_in.east"))
    own = [s for s in occ.copper if s.owner == "mod"]
    assert [s.net for s in own] == ["mod.VIN"]             # the note's VIN track, from (9.0, 3.0) to (10.1, 3.0) in the fragment
    dx, dy = 50.0 - base.x, 20.0 - base.y
    assert abs(own[0].box.left - (39.0 + dx)) < 0.2 and abs(own[0].box.center.y - (13.0 + dy)) < 1e-6


def test_an_arranged_zone_is_left_to_the_boards_copper_and_held_no_more_often_than_the_defaults():
    """A zone is no cell's: the stamped default's is on the board with no owner, and an arranged one is not added a second time."""
    pts = ((0.0, 0.0), (12.0, 0.0), (12.0, 6.0), (0.0, 6.0))
    zone = Zone("GND", CopperLayer.F, pts)
    stamped = tuple((x + 30.0, y + 10.0) for x, y in pts)
    item = CopperItem("zone", "mod.GND", frozenset([CopperLayer.F]), (stamped,), Box.of_points(stamped), None)
    g = with_arrangement(stamped_geometry(copper=(item,)),
                         east_doc(ops=[Track("VIN", CopperLayer.F, 0.3, Location(9.0, 3.0), Location(10.1, 3.0)), zone]))
    cell = g.cells["mod"]
    arr = cell.arranged("c_in.east")
    assert [c.kind for c in arr.own_copper].count("zone") == 1

    def held(occ):
        return [s for s in occ.copper if s.net == "mod.GND" and abs(s.box.width - 12.0) < 1e-6 and abs(s.box.height - 6.0) < 1e-6]

    a, b = Occupancy(g), Occupancy(g)
    before = held(a)
    a.commit(cell, Placement(Location(50.0, 20.0)))
    b.commit(cell, Placement(Location(50.0, 20.0), 0.0, Face.FRONT, "c_in.east"))
    assert len(held(b)) == len(held(a)) == len(before)
    assert not any(s.net == "mod.GND" and s.kind == "copper" for s in b._geometry(arr).shapes)
    assert b._geometry(arr).body.height < 6.0


def test_committed_turned_and_flipped_it_stands_as_the_cell_stamped_in_that_arrangement_would():
    g = with_arrangement()
    fps = [footprint("C1", 41.0, 13.0, w=3, h=1.6, nets=("mod.GND", "mod.VIN"), cell="mod", inst="mod.c_in", rotation=180.0),
           footprint("U1", 36.0, 13.0, w=6, h=4, nets=("mod.VIN", "mod.OUT"), cell="mod", inst="mod.u1"),
           footprint("R9", 5, 5, nets=("mod.OUT", "GND"))]
    stamped = board_geometry(fps, cells=["mod"], extra_nets=("mod.GND", "GND"), width=80, height=60)
    for rotation, face in ((90.0, Face.FRONT), (270.0, Face.BACK)):
        a, b = Occupancy(g), Occupancy(stamped)
        a.commit(g.cells["mod"], Placement(Location(50.0, 20.0), rotation, face, "c_in.east"))
        b.commit(stamped.cells["mod"], Placement(Location(50.0, 20.0), rotation, face))
        for ref in ("C1", "U1"):
            ra, rb = a.items[ref].reference, b.items[ref].reference
            assert ra.face == rb.face and abs((ra.rotation - rb.rotation) % 360.0) < 1e-6
            assert abs(ra.location.x - rb.location.x) < 1e-6 and abs(ra.location.y - rb.location.y) < 1e-6
            assert pads(a.items[ref]) == pads(b.items[ref])
