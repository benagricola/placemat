"""A cell flipped to the back swaps its own F and B copper and keeps its
inner copper on the layer it was drawn on, so a module keeps the layer roles
it was laid out for (a pour on the In2 power layer stays on In2). This
diverges from KiCad's own flip, which mirrors inner layers through the
stack. A via that reaches a face (micro or blind) mirrors, since its face
end must move with the face: F-In1 becomes B-In4. A buried via stays. A
footprint's own copper flips as KiCad flips it: a footprint is one part
drawn for a face (a coil wound on every layer), so its whole stack mirrors.
The step notes a flipped via whose inner end may no longer join its net."""
import dataclasses

import pytest

from placemat.board_geometry import CopperItem
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.values import Box, Cell, CopperLayer, Face, Location, Net, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint, rect

F, B = CopperLayer.F, CopperLayer.B
IN1, IN2, IN3, IN4 = CopperLayer.IN1, CopperLayer.IN2, CopperLayer.IN3, CopperLayer.IN4
SIX = (F, IN1, IN2, IN3, IN4, B)
TYPES = {F: "mixed", IN1: "power", IN2: "power", IN3: "mixed", IN4: "power", B: "mixed"}


@pytest.fixture(autouse=True)
def _fab_makes_every_via(monkeypatch):
    monkeypatch.setattr(Board, "fab_via_tiers", {"micro": "yes", "blind": "yes", "buried": "yes"})


def _pour(layer, net, cx=10):
    poly = rect(cx, 10, 2, 2)
    return CopperItem("poly", net, frozenset({layer}), (poly,), Box.of_points(poly), "k")


def _via(layers, net, x):
    ring = circle_polygon(Location(x, 12), 0.225)
    return CopperItem("via", net, frozenset(layers), (ring,), Box.of_points(ring), "k",
                      width_mm=0.45, drill_mm=0.2, anchors=((x, 12.0),))


def _board(copper, fps=None):
    fps = fps or [footprint("U1", 10, 14, inst="k.u1", cell="k", nets=("GND", "A"))]
    g = board_geometry(fps, cells=("k",), copper=copper, width=40, height=40,
                       extra_nets=("GND", "V3V3", "VIN"))
    g = dataclasses.replace(g, layers=SIX, layer_types=dict(TYPES))
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.plane(Net("GND"), layers=(IN1, IN4))
    b.plane(Net("V3V3"), layers=(IN3,))
    return b


def _cell_copper(plan, kind):
    return [s for s in plan.occupancy.copper if s.owner == "k" and s.kind == kind]


def test_flip_layers_swaps_the_faces_and_keeps_inner_layers():
    occ = Occupancy(dataclasses.replace(board_geometry([], width=30, height=30), layers=SIX), edge_margin=0.5)
    assert occ._flip_layers(frozenset((F,))) == frozenset((B,))
    assert occ._flip_layers(frozenset((IN2,))) == frozenset((IN2,))
    assert occ._flip_layers(frozenset((F, IN1))) == frozenset((B, IN1))


def test_flip_span_mirrors_a_face_anchored_via_and_keeps_a_buried_one():
    """KiCad's own flip of a via reaching a face: B-In4 to F-In1, B-In2 to
    F-In3. A buried via (In1-In2) keeps its layers, as the copper it joins
    does."""
    occ = Occupancy(dataclasses.replace(board_geometry([], width=30, height=30), layers=SIX), edge_margin=0.5)
    assert occ._flip_span(frozenset((B, IN4))) == frozenset((F, IN1))
    assert occ._flip_span(frozenset((B, IN4, IN3, IN2))) == frozenset((F, IN1, IN2, IN3))
    assert occ._flip_span(frozenset((IN1, IN2))) == frozenset((IN1, IN2))
    assert occ._flip_span(frozenset(CopperLayer)) == frozenset(CopperLayer)


def test_a_flipped_cells_inner_pour_keeps_its_layer():
    """The flip the old refusal named (a power pour on In2 would have landed
    on In3, V3V3's plane) is placed, with the pour still on In2."""
    b = _board([_pour(IN2, "VIN"), _pour(F, "GND", cx=14)])
    b.place(Cell("k"), at=Location(20, 20), face=Face.BACK)
    plan = b.resolve()
    layers = sorted(tuple(sorted(l.value for l in s.layers)) for s in _cell_copper(plan, "copper"))
    assert layers == [("B.Cu",), ("In2.Cu",)]


def test_a_flipped_cells_vias_mirror_only_when_they_reach_a_face():
    b = _board([_via((F, IN1), "GND", 9), _via((IN1, IN2), "GND", 11)])
    b.place(Cell("k"), at=Location(20, 20), face=Face.BACK)
    plan = b.resolve()
    spans = sorted(tuple(sorted(l.value for l in s.layers)) for s in _cell_copper(plan, "through"))
    assert spans == [("B.Cu", "In4.Cu"), ("In1.Cu", "In2.Cu")]


def test_a_flipped_parts_inner_copper_mirrors_as_kicad_flips_it():
    fp = footprint("U1", 10, 14, inst="u1", nets=("GND", "A"))
    fp = dataclasses.replace(fp, copper=((IN1, rect(10, 14, 1, 1)),))
    b = _board([], fps=[fp])
    b.place(Part("u1"), at=Location(20, 20), face=Face.BACK)
    plan = b.resolve()
    (s,) = [s for s in plan.occupancy.items["U1"].shapes if s.kind == "copper"]
    assert s.layers == frozenset((IN4,))


def test_a_flipped_via_whose_inner_end_changes_role_is_noted():
    """F-In2 on VIN: In2 is a power layer of no declared plane, and the
    flip lands its inner end on In3, V3V3's plane."""
    b = _board([_via((F, IN1, IN2), "VIN", 9)])
    b.place(Cell("k"), at=Location(20, 20), face=Face.BACK)
    note = b.resolve().step("k").note
    assert "In2.Cu" in note and "In3.Cu" in note, note


def test_a_flipped_via_from_its_nets_plane_to_its_nets_plane_is_not_noted():
    b = _board([_via((F, IN1), "GND", 9)])
    b.place(Cell("k"), at=Location(20, 20), face=Face.BACK)
    assert "In4.Cu" not in (b.resolve().step("k").note or "")


def test_a_flipped_via_that_fed_an_inner_track_is_noted():
    """F-In1 on A, a net with no plane: In1 and In4 are both power layers
    of GND's plane, but the via fed A's copper on In1, which stays on In1
    while the via's inner end moves to In4."""
    b = _board([_via((F, IN1), "A", 9)])
    b.place(Cell("k"), at=Location(20, 20), face=Face.BACK)
    note = b.resolve().step("k").note
    assert "In1.Cu" in note and "In4.Cu" in note, note


def test_a_cell_on_its_own_face_is_not_noted():
    b = _board([_via((F, IN1, IN2), "VIN", 9)])
    b.place(Cell("k"), at=Location(20, 20), face=Face.FRONT)
    assert "In3.Cu" not in (b.resolve().step("k").note or "")


def _six_layer_items(board):
    """On a six-layer board: a track on In2, a zone on F and In2, a via
    F-In1, a via In1-In2 and a footprint drawing a line on In1."""
    import pcbnew
    net = pcbnew.NETINFO_ITEM(board, "GND")
    board.Add(net)
    mm = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(mm(10, 10)), t.SetEnd(mm(12, 10)), t.SetWidth(pcbnew.FromMM(0.2)), t.SetLayer(pcbnew.In2_Cu)
    t.SetNet(net)
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.F_Cu), ls.AddLayer(pcbnew.In2_Cu)
    z.SetLayerSet(ls)
    z.SetNet(net)
    z.AppendCorner(mm(8, 8), -1), z.AppendCorner(mm(14, 8), -1), z.AppendCorner(mm(14, 14), -1)
    blind, buried = pcbnew.PCB_VIA(board), pcbnew.PCB_VIA(board)
    for v, at, pair in ((blind, mm(9, 12), (pcbnew.F_Cu, pcbnew.In1_Cu)),
                        (buried, mm(11, 12), (pcbnew.In1_Cu, pcbnew.In2_Cu))):
        v.SetPosition(at)
        v.SetViaType(pcbnew.VIATYPE_MICROVIA if v is blind else
                     getattr(pcbnew, "VIATYPE_BURIED", None) or pcbnew.VIATYPE_BLIND_BURIED)
        v.SetLayerPair(*pair)
        v.SetWidth(pcbnew.FromMM(0.45))
        v.SetDrill(pcbnew.FromMM(0.2))
        v.SetNet(net)
    fp = pcbnew.FOOTPRINT(board)
    fp.SetPosition(mm(10, 14))
    line = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_SEGMENT)
    line.SetStart(mm(9, 14)), line.SetEnd(mm(11, 14)), line.SetLayer(pcbnew.In1_Cu)
    fp.Add(line)
    items = (t, z, blind, buried, fp)
    for it in items:
        board.Add(it)
    return items


@needs_kicad
def test_the_writer_keeps_a_flipped_cells_inner_copper_on_its_layers():
    import types
    import pcbnew
    from placemat.kicad.write import _move_cell
    from placemat.placement import Placement
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(6)
    track, zone, blind, buried, fp = _six_layer_items(board)
    group = pcbnew.PCB_GROUP(board)
    board.Add(group)
    for it in (track, zone, blind, buried, fp):
        group.AddItem(it)
    cell = types.SimpleNamespace(name="k", box=Box(8, 8, 14, 14))
    _move_cell(board, cell, Placement(Location(20, 20), 0.0, Face.BACK), {"k": group})
    assert track.GetLayer() == pcbnew.In2_Cu
    assert set(zone.GetLayerSet().CuStack()) == {pcbnew.B_Cu, pcbnew.In2_Cu}
    assert {blind.TopLayer(), blind.BottomLayer()} == {pcbnew.B_Cu, pcbnew.In4_Cu}
    assert {buried.TopLayer(), buried.BottomLayer()} == {pcbnew.In1_Cu, pcbnew.In2_Cu}
    (line,) = [g for g in fp.GraphicalItems() if isinstance(g, pcbnew.PCB_SHAPE)]
    assert line.GetLayer() == pcbnew.In4_Cu
    assert fp.GetLayer() == pcbnew.B_Cu


@needs_kicad
def test_the_writer_mirrors_a_flipped_parts_inner_copper_as_kicad_does():
    import pcbnew
    from placemat.kicad.write import _place_footprint
    from placemat.placement import Placement
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(6)
    *_, fp = _six_layer_items(board)
    _place_footprint(fp, Placement(Location(10, 14), 0.0, Face.FRONT), Placement(Location(20, 20), 0.0, Face.BACK))
    (line,) = [g for g in fp.GraphicalItems() if isinstance(g, pcbnew.PCB_SHAPE)]
    assert line.GetLayer() == pcbnew.In4_Cu
    assert fp.GetLayer() == pcbnew.B_Cu
