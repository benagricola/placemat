"""`layers=` on board.via(), board.vias() and board.stitch(): a via that
spans some of the board's copper layers is copper, and a hole, on those
layers only, and is judged there alone. One layer from an outer face it is
written as KiCad's micro via, otherwise as a blind or buried one."""
import dataclasses

import pytest

from placemat import reuse
from placemat.board_geometry import CopperItem
from placemat.copper import Via
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.occupancy import Occupancy, hole_shape
from placemat.placement import Placement
from placemat.values import Box, CopperLayer, Face, Location, Near, Net, PadRef, Part
from tests.conftest import needs_kicad, needs_native
from tests.fixtures import board_geometry, footprint

@pytest.fixture(autouse=True)
def _fab_makes_every_via(monkeypatch):
    """These tests are about how a span is judged and written: the fab
    profile allows every via type here (test_via_types_allowed covers its
    refusals)."""
    monkeypatch.setattr(Board, "fab_vias", frozenset({"micro", "blind", "buried"}))


F, B = CopperLayer.F, CopperLayer.B
IN1, IN2, IN3, IN4 = CopperLayer.IN1, CopperLayer.IN2, CopperLayer.IN3, CopperLayer.IN4
SIX = (F, IN1, IN2, IN3, IN4, B)


def _six(fps, **kw):
    return dataclasses.replace(board_geometry(fps, **kw), layers=SIX)


def _planned_over(face, layers=(B, IN4)):
    """A GND via on r9's pad 1, r9 on `face`."""
    fps = [footprint("R9", 10.1, 10, w=2, h=1, inst="r9", nets=("S", "T"), face=face)]
    b = Board(_six(fps, width=30, height=30, extra_nets=("GND",)), edge_margin=0.5, keep_going=True)
    b.place(Part("r9"), at=Location(10.1, 10), face=face)
    b.via(Net("GND"), Location(9.5, 10), size=0.45, layers=layers)
    return b.resolve()


def _copper(plan):
    return [f for f in plan.findings if f.kind == "copper"]


def test_a_via_on_the_back_span_meets_no_front_pad():
    assert not _copper(_planned_over(Face.FRONT))


def test_a_via_on_the_back_span_meets_a_back_pad():
    hits = _copper(_planned_over(Face.BACK))
    assert hits and all("via GND at (9.50, 10.00)" in f for f in hits), hits


def test_a_through_via_meets_the_front_pad():
    assert _copper(_planned_over(Face.FRONT, layers=None))


def _searched_onto_via(face):
    """r9 searched round a spot that puts its pad 1 on a fixed B-In4 via."""
    fps = [footprint("R9", 25, 25, w=2, h=1, inst="r9", nets=("S", "T"), face=face)]
    b = Board(_six(fps, width=30, height=30, extra_nets=("GND",)), edge_margin=0.5)
    b.via(Net("GND"), Location(9.5, 10), size=0.45, layers=(B, IN4))
    b.place(Part("r9"), at=Near(Location(10.1, 10), radius=3), face=face)
    return b.resolve().placement("r9").location


def test_a_front_part_lands_over_a_back_span_via():
    at = _searched_onto_via(Face.FRONT)
    assert (round(at.x, 6), round(at.y, 6)) == (10.1, 10.0)


def test_a_back_part_keeps_off_a_back_span_via():
    at = _searched_onto_via(Face.BACK)
    assert (round(at.x, 6), round(at.y, 6)) != (10.1, 10.0)


def _via_item(net, x, y, layers, owner=None, size=0.3, drill=0.1):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", net, frozenset(layers), (ring,), Box.of_points(ring), owner, size, drill, ((x, y),))


def test_a_stamped_micro_via_meets_nothing_on_the_far_face():
    """A via the reader found spanning B and In4 (a fragment built with
    spans) is copper and a hole there alone."""
    r9 = footprint("R9", 25, 25, w=2, h=1, inst="r9", nets=("S", "T"))
    occ = Occupancy(_six([r9], width=30, height=30, copper=[_via_item("GND", 9.5, 10, (B, IN4))]), edge_margin=0.5)
    assert occ.legal(r9, Placement(Location(10.1, 10), 0.0, Face.FRONT)) is None
    assert occ.legal(r9, Placement(Location(10.1, 10), 0.0, Face.BACK)) is not None


def test_two_vias_whose_spans_share_no_layer_have_no_hole_rule_between_them():
    """KiCad 10's DRC checks no hole-to-hole between two vias on layers
    they do not share (blind B-In3 and F-In2 0.05 mm apart); on a shared
    layer it does."""
    occ = Occupancy(_six([], width=30, height=30), edge_margin=0.5)
    back = hole_shape("", Location(10, 10), 0.3, "A", layers=frozenset((B, IN4, IN3)))
    front = hole_shape("", Location(10.35, 10), 0.3, "A", layers=frozenset((F, IN1, IN2)))
    deep = hole_shape("", Location(10.35, 10), 0.3, "A", layers=frozenset((B, IN4, IN3, IN2)))
    through = hole_shape("", Location(10.35, 10), 0.3, "A")
    assert occ._conflict(back, front, None) is None
    assert "hole-to-hole" in occ._conflict(back, deep, None)
    assert "hole-to-hole" in occ._conflict(back, through, None)


@needs_native
def test_the_native_judge_agrees_on_the_hole_rule_between_spans():
    placemat_native = pytest.importorskip("placemat_native")
    from tests.test_native_conflict import _cfg_kwargs, _py_shape
    occ = Occupancy(_six([], width=30, height=30), edge_margin=0.5)
    back = hole_shape("", Location(10, 10), 0.3, "A", layers=frozenset((B, IN4, IN3)))
    cfg = _cfg_kwargs(occ)
    for other in (hole_shape("", Location(10.35, 10), 0.3, "A", layers=frozenset((F, IN1, IN2))),
                  hole_shape("", Location(10.35, 10), 0.3, "A", layers=frozenset((B, IN4, IN3, IN2))),
                  hole_shape("", Location(10.35, 10), 0.3, "A")):
        py = occ._conflict(back, other, None) is not None
        assert placemat_native.conflict(_py_shape(back, False), _py_shape(other, False), None, **cfg) == py


def test_a_flip_mirrors_a_span_that_reaches_a_face_as_kicad_does():
    """KiCad's own flip of a via: B-In4 to F-In1, B-In2 to F-In3. A buried
    via (In1-In2) keeps its layers, as a cell's inner copper does."""
    occ = Occupancy(_six([], width=30, height=30), edge_margin=0.5)
    assert occ._flip_span(frozenset((B, IN4))) == frozenset((F, IN1))
    assert occ._flip_span(frozenset((B, IN4, IN3, IN2))) == frozenset((F, IN1, IN2, IN3))
    assert occ._flip_span(frozenset((IN1, IN2))) == frozenset((IN1, IN2))
    assert occ._flip_span(frozenset(CopperLayer)) == frozenset(CopperLayer)


def test_a_carried_via_keeps_its_declared_span_on_a_flipped_part():
    """u1 is drawn on the front and placed on the back; the via at its pad
    spans B-In4 where it lands, so a front pad under it is no conflict."""
    fps = [footprint("U1", 25, 25, w=3, h=1, inst="u1", nets=("GND", "X")),
           footprint("R9", 10, 10, w=2, h=1, inst="r9", nets=("S", "T"))]
    b = Board(_six(fps, width=30, height=30), edge_margin=0.5)
    b.place(Part("r9"), at=Location(10, 10))
    b.place(Part("u1"), at=Near(Location(10.3, 10), radius=3), face=Face.BACK, rotation=0)
    b.via(Net("GND"), PadRef(Part("u1"), 1), size=0.45, layers=(B, IN4))
    at = b.resolve().placement("u1").location
    assert (round(at.x, 6), round(at.y, 6)) == (10.3, 10.0)


def test_a_span_on_a_layer_the_board_lacks_is_refused():
    b = Board(board_geometry([], width=30, height=30, extra_nets=("GND",)), edge_margin=0.5)
    with pytest.raises(ValueError, match="In4.Cu"):
        b.via(Net("GND"), Location(10, 10), layers=(B, IN4))


def test_a_span_of_one_layer_is_refused():
    b = Board(_six([], width=30, height=30, extra_nets=("GND",)), edge_margin=0.5)
    with pytest.raises(ValueError, match="two"):
        b.via(Net("GND"), Location(10, 10), layers=(B,))


def _vias(plan):
    return [op for op in plan.copper if isinstance(op, Via)]


def test_the_default_is_the_through_via_and_digests_as_before():
    assert Via("A", Location(1, 2), 0.3, 0.6).layers == ()
    assert "layers" not in reuse.canonical(Via("A", Location(1, 2), 0.3, 0.6))
    b = Board(_six([], width=30, height=30, extra_nets=("GND",)), edge_margin=0.5)
    b.via(Net("GND"), Location(10, 10))
    (v,) = _vias(b.resolve())
    assert v.layers == () and v.drill == 0.3


def test_a_micro_via_takes_the_laser_drill_setting():
    from placemat.settings import Settings
    b = Board(_six([], width=30, height=30, extra_nets=("GND",)), edge_margin=0.5,
              settings=Settings(copper_microvia_drill=0.12))
    b.via(Net("GND"), Location(10, 10), layers=(IN4, B))
    b.via(Net("GND"), Location(20, 10), layers=(B, IN2))
    micro, blind = _vias(b.resolve())
    assert micro.layers == (IN4, B) and micro.drill == 0.12
    assert blind.layers == (IN2, IN3, IN4, B) and blind.drill == 0.3


def test_a_pad_grid_and_a_stitch_take_a_span():
    fps = [footprint("U1", 10, 10, w=6, h=3, inst="u1", nets=("X", "GND"))]
    b = Board(_six(fps, width=30, height=30), edge_margin=0.5)
    b.place(Part("u1"), at=Location(10, 10))
    b.vias(Net("GND"), PadRef(Part("u1"), 2), pitch=0.35, size=0.3, layers=(F, IN1))
    pour = b.pour(Net("GND"), [Location(20, 20), Location(24, 20), Location(24, 24), Location(20, 24)], layer=F)
    b.stitch(Net("GND"), pour, layers=(F, IN1))
    vias = _vias(b.resolve())
    assert vias and all(v.layers == (F, IN1) and v.drill == 0.1 for v in vias)
    assert any(v.at.x > 19 for v in vias) and any(v.at.x < 19 for v in vias)


def test_a_pad_grid_whose_span_misses_the_pad_draws_none():
    fps = [footprint("U1", 10, 10, w=6, h=3, inst="u1", nets=("X", "GND"))]
    b = Board(_six(fps, width=30, height=30), edge_margin=0.5)
    b.place(Part("u1"), at=Location(10, 10))
    b.vias(Net("GND"), PadRef(Part("u1"), 2), pitch=0.35, size=0.3, layers=(B, IN4))
    plan = b.resolve()
    assert not _vias(plan)
    assert any("a span of In4.Cu-B.Cu does not reach U1.2 on F.Cu" in f for f in plan.findings), list(plan.findings)


def _six_layer_board(path):
    import pcbnew
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(6)
    net = pcbnew.NETINFO_ITEM(board, "GND")
    board.Add(net)
    t = pcbnew.PCB_TRACK(board)                 # something on the net, so the board keeps it
    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(2), pcbnew.FromMM(28)))
    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(3), pcbnew.FromMM(28)))
    t.SetWidth(pcbnew.FromMM(0.2))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(net)
    board.Add(t)
    board.Save(str(path))


@needs_kicad
def test_a_span_is_written_as_a_micro_or_blind_via_and_read_back(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    pcb = tmp_path / "layout.kicad_pcb"
    _six_layer_board(pcb)
    b = Board(read_board(pcb), edge_margin=0.5)
    b.size(width=30, height=30)
    b.via(Net("GND"), Location(10, 10), layers=(B, IN4))
    b.via(Net("GND"), Location(20, 10), layers=(B, IN2))
    b.via(Net("GND"), Location(15, 20))
    apply_plan(pcb, b.resolve())
    board = pcbnew.LoadBoard(str(pcb))
    vias = {(round(pcbnew.ToMM(v.GetPosition().x), 3), round(pcbnew.ToMM(v.GetPosition().y), 3)): v
            for v in board.GetTracks() if isinstance(v, pcbnew.PCB_VIA)}
    micro, blind, through = vias[(10.0, 10.0)], vias[(20.0, 10.0)], vias[(15.0, 20.0)]
    blind_type = getattr(pcbnew, "VIATYPE_BLIND", None) or pcbnew.VIATYPE_BLIND_BURIED
    assert micro.GetViaType() == pcbnew.VIATYPE_MICROVIA
    assert round(pcbnew.ToMM(micro.GetDrillValue()), 3) == 0.1
    assert blind.GetViaType() == blind_type
    assert through.GetViaType() == pcbnew.VIATYPE_THROUGH
    layers = {c.anchors[0]: c.layers for c in read_board(pcb).copper if c.kind == "via"}
    assert layers[(10.0, 10.0)] == frozenset((B, IN4))
    assert layers[(20.0, 10.0)] == frozenset((B, IN4, IN3, IN2))
    assert layers[(15.0, 20.0)] == frozenset(SIX)
