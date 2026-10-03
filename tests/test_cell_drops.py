"""`board.place(Cell(...), drops=)` thins a stamped cell's via fields when
it is placed: a field is the drops (vias of a net the board declares a
`plane()` for) inside one of its members' pads."""
import dataclasses
import shutil

import pytest

from placemat import reuse
from placemat.board_geometry import CopperItem
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, Cell, CopperLayer, Drops, Location, Net
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint, pad


def _via(net, x, y, owner="m", size=0.6, drill=0.3):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", net, frozenset([CopperLayer.F, CopperLayer.B]), (ring,), Box.of_points(ring), owner,
                      size, drill, ((x, y),))


def _geom():
    """Cell m: U1 with a signal pad 1, a GND pad 2 and a 3 mm GND exposed
    pad 9 at (40, 40) carrying a 3x3 field 1 mm apart. Pad 2 has a field of
    one; pad 1 a signal via; one GND via stands in no pad."""
    fp = footprint("U1", 40, 40, w=7, h=5, inst="m.u1", nets=("SIG", "GND"), cell="m")
    fp = dataclasses.replace(fp, pads=fp.pads + (pad("U1", "m.u1", 9, "GND", 40, 40, 3.0, 3.0),))
    vias = [_via("GND", 39 + i, 39 + j) for j in range(3) for i in range(3)]
    vias += [_via("GND", 42.9, 40), _via("SIG", 37.1, 40), _via("GND", 40, 43.5)]
    return board_geometry([fp], cells=["m"], copper=vias, width=80, height=80)


def _plan(drops=None, plane=True, **settings):
    b = Board(_geom(), edge_margin=0.5, settings=Settings(**settings))
    b.rect(width=80, height=80)
    if plane:
        b.plane(Net("GND"), layers=(CopperLayer.B,))
    extra = {} if drops is None else {"drops": drops}
    b.place(Cell("m"), at=Location(20, 20), **extra)
    return b, b.resolve()


def _vias(plan, kind="through"):
    """The cell's vias where it was placed, relative to its pad 9's centre."""
    c = plan.occupancy.pad_location("U1", "9")
    return sorted((round(s.box.center.x - c.x, 3), round(s.box.center.y - c.y, 3))
                  for s in plan.occupancy.copper if s.owner == "m" and s.kind == kind)


def _in(vias, lo=-1.5, hi=1.5):
    return [v for v in vias if lo < v[0] < hi and lo < v[1] < hi]


def test_all_keeps_the_fields_as_stamped():
    _, plan = _plan(Drops.ALL)
    assert len(_vias(plan)) == 12 and len(_vias(plan, "hole")) == 12


def test_half_keeps_a_checkerboard_of_each_field():
    _, plan = _plan(Drops.HALF)
    assert _in(_vias(plan)) == [(-1.0, -1.0), (-1.0, 1.0), (0.0, 0.0), (1.0, -1.0), (1.0, 1.0)]
    assert _in(_vias(plan, "hole")) == _in(_vias(plan))
    assert (2.9, 0.0) in _vias(plan)                   # a field of one keeps its via
    assert len(_vias(plan)) == 5 + 3


def test_min_keeps_the_keep_share_of_each_field_rounded_up():
    _, plan = _plan(Drops.MIN, place_drops_keep_share=0.3)
    assert len(_in(_vias(plan))) == 3                  # ceil(0.3 * 9)
    assert (2.9, 0.0) in _vias(plan)
    assert len(_vias(plan)) == 3 + 3


def test_min_never_leaves_a_field_empty():
    _, plan = _plan(Drops.MIN, place_drops_keep_share=0.0)
    assert len(_in(_vias(plan))) == 1
    assert len(_vias(plan)) == 1 + 3


def test_a_signal_via_and_a_drop_outside_every_pad_are_kept():
    _, plan = _plan(Drops.MIN, place_drops_keep_share=0.0)
    assert (-2.9, 0.0) in _vias(plan) and (0.0, 3.5) in _vias(plan)


def test_without_a_plane_the_net_has_no_drops_and_nothing_is_thinned():
    _, plan = _plan(Drops.HALF, plane=False)
    assert len(_vias(plan)) == 12
    assert "no via field of a plane net" in plan.step("m").note


def test_the_step_says_what_was_kept():
    _, plan = _plan(Drops.HALF)
    assert "drops half: 1 of 1 in U1.2, 5 of 9 in U1.9" in plan.step("m").note


def test_the_fragment_itself_is_untouched():
    b, plan = _plan(Drops.HALF)
    assert len([c for c in b.geometry.copper if c.kind == "via"]) == 12
    assert plan.geometry is b.geometry


def test_drops_is_for_a_cell():
    b = Board(board_geometry([footprint("R1", 10, 10, inst="r1")], width=30, height=30), edge_margin=0.5)
    from placemat.values import Part
    with pytest.raises(TypeError, match="drops"):
        b.place(Part("r1"), at=Location(10, 10), drops=Drops.HALF)


def test_drops_takes_its_value_as_a_word_too():
    _, plan = _plan("half")
    assert len(_vias(plan)) == 8


def test_a_declaration_without_drops_digests_as_before():
    b = Board(_geom(), edge_margin=0.5)
    plain = reuse.canonical(b.place(Cell("m"), at=Location(20, 20)))
    assert "drops" not in plain
    b = Board(_geom(), edge_margin=0.5)
    assert reuse.canonical(b.place(Cell("m"), at=Location(20, 20), drops=Drops.ALL)) == plain
    b = Board(_geom(), edge_margin=0.5)
    assert "drops=" in reuse.canonical(b.place(Cell("m"), at=Location(20, 20), drops=Drops.HALF))


def _kicad_board(path):
    """The same cell on a real board: U1's exposed pad 9 (GND) carrying a
    3x3 field in group m."""
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(2)
    for n in ("GND", "SIG"):
        b.Add(pcbnew.NETINFO_ITEM(b, n))
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("U1")
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(40), pcbnew.FromMM(40)))
    b.Add(fp)
    for number, net, x, w in (("1", "SIG", 37.0, 1.0), ("9", "GND", 40.0, 3.0)):
        p = pcbnew.PAD(fp)
        p.SetNumber(number)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetLayerSet(pcbnew.PAD.SMDMask())
        p.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(w), pcbnew.FromMM(w)))
        fp.Add(p)
        p.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(40)))
        p.SetNet(b.GetNetInfo().GetNetItem(net))
    g = pcbnew.PCB_GROUP(b)
    g.SetName("m")
    b.Add(g)
    g.AddItem(fp)
    for i in range(3):
        for j in range(3):
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(39 + i), pcbnew.FromMM(39 + j)))
            v.SetDrill(pcbnew.FromMM(0.3))
            v.SetWidth(pcbnew.FromMM(0.6))
            v.SetNet(b.GetNetInfo().GetNetItem("GND"))
            b.Add(v)
            g.AddItem(v)
    b.Save(str(path))


@needs_kicad
def test_the_written_board_carries_the_thinned_field(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    pcb = tmp_path / "layout.kicad_pcb"
    _kicad_board(pcb)
    shutil.copy(pcb, tmp_path / "generated.kicad_pcb")
    b = Board(read_board(pcb), edge_margin=0.5)
    b.rect(width=80, height=80)
    b.plane(Net("GND"), layers=(CopperLayer.B,))
    b.place(Cell("m"), at=Location(20, 20), drops=Drops.HALF)
    apply_plan(pcb, b.resolve())
    board = pcbnew.LoadBoard(str(pcb))
    (g,) = [g for g in board.Groups() if g.GetName() == "m"]
    pad9 = next(p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNumber() == "9").GetPosition()
    kept = sorted((round(pcbnew.ToMM(v.GetPosition().x - pad9.x), 3), round(pcbnew.ToMM(v.GetPosition().y - pad9.y), 3))
                  for v in g.GetItems() if isinstance(v, pcbnew.PCB_VIA))
    assert kept == [(-1.0, -1.0), (-1.0, 1.0), (0.0, 0.0), (1.0, -1.0), (1.0, 1.0)]
    assert len([t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]) == 5
    assert len([c for c in read_board(tmp_path / "generated.kicad_pcb").copper if c.kind == "via"]) == 9
