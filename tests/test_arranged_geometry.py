import dataclasses

import pytest

from placemat import arrangement_note as N
from placemat.arranged_geometry import attach, build
from placemat.geometry import pose_transform
from placemat.layout import PlacedKeepout
from placemat.placement import Placement
from placemat.values import CopperLayer, Face, Location
from tests.arrangement_support import east_doc, stamped_geometry, still_doc, with_arrangement
from tests.conftest import needs_kicad

NETS = lambda g: frozenset(g.nets)


def test_the_pose_transform_is_the_one_the_occupancy_has_always_used():
    from placemat.occupancy import Occupancy, ItemGeometry
    ref = Placement(Location(3.0, 4.0), 90.0, Face.FRONT)
    g = ItemGeometry(frozenset(["a"]), ref, (), None, frozenset())
    for to in (Placement(Location(9.0, 1.0), 270.0, Face.FRONT), Placement(Location(9.0, 1.0), 10.0, Face.BACK)):
        a, b = Occupancy._transform(g, to), pose_transform(ref, to)
        assert (a.a, a.b, a.c, a.d, a.tx, a.ty) == (b.a, b.b, b.c, b.d, b.tx, b.ty)


def test_a_note_becomes_an_arrangement_of_the_stamped_cell_in_the_stamped_frame():
    g = stamped_geometry()
    arr, problem = build(g.cells["mod"], east_doc(), NETS(g), g.layers)
    assert problem is None and arr.id == "c_in.east" and arr.choices == {"c_in": "east"}
    c_in = next(m for m in arr.members if m.inst == "c_in")
    assert c_in.ref == "C1" and c_in.pose == Placement(Location(41.0, 13.0), 180.0, Face.FRONT)
    assert c_in.default == Placement(Location(31.0, 13.0), 0.0, Face.FRONT)
    geom = arr.geom
    assert geom.arrangement == "c_in.east" and dict(geom.poses)["C1"] == c_in.pose and geom.members == g.cells["mod"].members
    assert geom.box.center.x > g.cells["mod"].box.center.x                      # c_in moved east of u1
    (track,) = [c for c in geom.own_copper if c.kind == "track"]
    assert track.net == "mod.VIN" and track.owner == "mod" and abs(track.anchors[0][0] - 41.9) < 1e-6   # shifted into the stamped frame
    assert g.cells["mod"].arrangements == ()                                      # the default cell is untouched


def test_the_cell_offers_its_arrangements_in_the_modules_order_and_answers_arranged():
    g = with_arrangement()
    cell = g.cells["mod"]
    assert cell.offered() == ("c_in.east",) and cell.arranged("") is cell and cell.arranged("default") is cell
    assert cell.arranged("c_in.east").arrangement == "c_in.east"
    with pytest.raises(KeyError) as e:
        cell.arranged("nope")
    assert "c_in.east" in str(e.value)
    two = N.encode(east_doc("c_in.a", 2), 4000) + N.encode(east_doc("c_in.b", 1), 4000)
    both = attach(stamped_geometry().cells["mod"], two, NETS(stamped_geometry()), stamped_geometry().layers)
    assert both.offered() == ("c_in.b", "c_in.a")                                # the module's order, not the ids'"


def test_an_arranged_cell_answers_only_for_itself():
    """"" and "default" give the cell itself on any geometry, as does its own id; another id is the base cell's to answer."""
    two = N.encode(east_doc("c_in.a", 1), 4000) + N.encode(east_doc("c_in.b", 2), 4000)
    g = stamped_geometry()
    base = attach(g.cells["mod"], two, NETS(g), g.layers)
    a = base.arranged("c_in.a")
    assert a.arranged("") is a and a.arranged("default") is a and a.arranged("c_in.a") is a and a.offered() == ()
    with pytest.raises(KeyError) as e:
        a.arranged("c_in.b")
    assert "c_in.a" in str(e.value) and "c_in.b" in str(e.value)


def test_a_cell_with_no_note_is_returned_as_it_is():
    g = stamped_geometry()
    assert attach(g.cells["mod"], [], NETS(g), g.layers) is g.cells["mod"]


def stale(g, doc, cell=None):
    return build(cell or g.cells["mod"], doc, NETS(g), g.layers)


def test_a_note_that_cannot_stand_is_stale_with_its_reason():
    """Review focus 2."""
    g = stamped_geometry()
    assert stale(g, dict(east_doc(), v=2))[1] == {"reason": "version", "ids": ["c_in.east"]}
    assert stale(g, dict(east_doc(), base="0000"))[1]["reason"] == "base"
    moved = east_doc()
    moved["members"][1]["from"] = [6.5, 3.0, 0.0, "front"]
    moved["base"] = N.base_digest([(m["inst"], N.pose_from_json(m["from"])) for m in moved["members"]])
    assert stale(g, moved)[1]["reason"] == "offset"                                # u1 would stand at another offset than c_in
    gone = east_doc()
    gone["members"] = gone["members"][:1]
    assert stale(g, gone)[1]["reason"] == "member"                                  # the cell has u1, the note has not
    extra = east_doc()
    extra["members"].append(dict(extra["members"][0], inst="nowhere"))
    assert stale(g, extra)[1]["reason"] == "member"
    twice = east_doc()
    twice["members"].append(dict(twice["members"][0]))
    assert stale(g, twice)[1]["reason"] == "member"                                 # c_in listed twice
    from placemat.copper import Via
    nonet = east_doc(ops=[Via("NOPE", Location(1, 1), 0.3, 0.6)])
    assert stale(g, nonet)[1]["reason"] == "net"


def test_attach_keeps_the_good_arrangements_and_records_the_stale_ones():
    g = stamped_geometry()
    texts = N.encode(east_doc("c_in.east", 1), 4000) + N.encode(dict(east_doc("c_in.old", 2), v=2), 4000) + \
        N.encode(east_doc("c_in.t", 3), 40)[:-1]                                    # one truncated numbered note
    cell = attach(g.cells["mod"], texts, NETS(g), g.layers)
    assert cell.offered() == ("c_in.east",)
    assert sorted(p["reason"] for p in cell.arrangement_problems) == ["text", "version"]


def test_a_note_keepout_becomes_a_rule_area_of_the_cell_as_the_stamped_board_reads_one():
    """Named as the fragment's zone is ("keepout <name>"), shifted into the stamped frame, its allow nets in the board's names
    and the copper types they keep relaxed, as kicad/read.py reads a stamped cell's rule area."""
    k = PlacedKeepout("quiet", ((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)), Location(1.0, 0.5), 0.0, ("tracks", "vias"),
                      None, frozenset({"GND"}), frozenset(), "a quiet patch")
    g = stamped_geometry()
    arr, problem = build(g.cells["mod"], east_doc(keepouts=[k]), NETS(g), g.layers)
    assert problem is None
    (ra,) = arr.rule_areas
    assert ra.name == "keepout quiet" and ra.base == "keepout quiet" and ra.cell == "mod"
    assert ra.polygon == ((30.0, 10.0), (32.0, 10.0), (32.0, 11.0), (30.0, 11.0))
    assert ra.layers == frozenset(g.layers) and ra.excludes == frozenset({"tracks", "vias"})
    assert ra.allow == frozenset({"mod.GND"}) and ra.relaxed == ("tracks", "vias") and ra.missing == ()
    inner = dataclasses.replace(k, layers=(CopperLayer.of("In1.Cu"),), allow=frozenset())
    (ra,) = build(g.cells["mod"], east_doc(keepouts=[inner]), NETS(g), g.layers)[0].rule_areas
    assert ra.layers == frozenset() and ra.missing == (CopperLayer.of("In1.Cu"),) and ra.relaxed == ()


@pytest.mark.parametrize("spoil", ["members", "op kind", "face"])
def test_a_note_that_parses_but_is_malformed_is_a_text_problem(spoil):
    doc = east_doc()
    if spoil == "members":
        del doc["members"]
    elif spoil == "op kind":
        doc["ops"][0]["kind"] = "spiral"
    else:
        doc["members"][0]["face"] = "side"
    g = stamped_geometry()
    cell = attach(g.cells["mod"], N.encode(doc, 4000), NETS(g), g.layers)
    assert cell.offered() == () and list(cell.arrangement_problems) == [{"reason": "text", "ids": ["c_in.east"]}]


def test_a_zone_belongs_to_no_cell_and_stays_out_of_the_cells_boxes():
    """As kicad/read.py reads a stamped zone: no owner, and not in the cell's extents."""
    from placemat.copper import Zone
    g = stamped_geometry()
    zone = Zone("GND", CopperLayer.F, ((-10.0, -10.0), (20.0, -10.0), (20.0, 20.0), (-10.0, 20.0)))
    arr, problem = build(g.cells["mod"], still_doc([zone]), NETS(g), g.layers)
    assert problem is None
    (item,) = arr.geom.own_copper
    assert item.kind == "zone" and item.owner is None and item.net == "mod.GND"
    cell = g.cells["mod"]
    assert (arr.geom.box, arr.geom.phys_box, arr.geom.courtyard_box, arr.geom.copper_box) == \
        (cell.box, cell.phys_box, cell.courtyard_box, cell.copper_box)


def _kicad_board(nets=()):
    import pcbnew
    board = pcbnew.CreateEmptyBoard()
    for n in nets:
        board.Add(pcbnew.NETINFO_ITEM(board, n))
    return board


@needs_kicad
def test_a_pour_stands_as_the_reader_reads_the_same_pour_in_the_default_cell():
    """The stamped pour read by kicad/read.py, owned by the cell, against the note's pour: one outline, box and extents."""
    from placemat.copper import Pour
    from placemat.kicad import read
    from placemat.kicad.write import _draw_pour
    pour = Pour("VIN", CopperLayer.F, ((8.0, 1.0), (10.0, 1.0), (10.0, 5.0), (8.0, 5.0)), 0.25)
    board = _kicad_board(["mod.VIN"])
    _draw_pour(board, dataclasses.replace(pour, net="mod.VIN", points=tuple((x + 30.0, y + 10.0) for x, y in pour.points)))
    (shape,) = list(board.GetDrawings())
    from placemat.settings import active
    (read_item,) = read._copper(board, {read._kiid(shape): "mod"}, active().geometry_arc_error_nm)
    g = stamped_geometry(copper=[read_item])
    arr, problem = build(g.cells["mod"], still_doc([pour]), NETS(g), g.layers)
    assert problem is None
    (item,) = arr.geom.own_copper
    assert item.box == read_item.box and item.vertices == read_item.vertices and item.width_mm == read_item.width_mm
    cell = g.cells["mod"]
    assert (arr.geom.box, arr.geom.phys_box, arr.geom.courtyard_box, arr.geom.copper_box) == \
        (cell.box, cell.phys_box, cell.courtyard_box, cell.copper_box)


@needs_kicad
def test_a_keepout_that_admits_parts_stands_as_the_reader_reads_its_stamped_zone():
    """A keepout with owners is written as a zone that allows footprints: the note carries the excludes the zone is
    written with, so the arranged rule area is the default's."""
    from types import SimpleNamespace
    from placemat.kicad import read
    from placemat.kicad.write import _draw_keepouts
    poly = ((2.0, 0.0), (6.0, 0.0), (6.0, 2.0), (2.0, 2.0))
    k = PlacedKeepout("near", poly, Location(4.0, 1.0), 0.0, ("parts", "tracks", "vias"), (CopperLayer.F, CopperLayer.B),
                      frozenset(), frozenset({"C1"}), "the bypass may sit here")
    board = _kicad_board()
    stamped = dataclasses.replace(k, poly=tuple((x + 30.0, y + 10.0) for x, y in poly))
    _draw_keepouts(board, SimpleNamespace(keepouts={k.name: stamped}))
    (zone,) = [z for z in board.Zones() if z.GetIsRuleArea()]
    (default,) = read._rule_areas(board, {read._kiid(zone): "mod"})
    assert "parts" not in default.excludes
    g = stamped_geometry()
    arr, problem = build(g.cells["mod"], still_doc(keepouts=[k]), NETS(g), g.layers)
    assert problem is None and arr.rule_areas == (default,)
