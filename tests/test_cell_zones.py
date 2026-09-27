"""A stamped cell's copper zone on a net and layer the board's own plane
already covers is merged into that plane when the board is written: the
plane fills the cell's area anyway. Every other cell zone is kept."""
import pytest

pytest.importorskip("pcbnew")        # the module imports placemat.kicad, which needs KiCad's pcbnew

import shutil

from placemat.layout import Board
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.settings import Settings
from placemat.values import CopperLayer, Location, Net
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def _copy(breakout_pcb, tmp_path):
    dst = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, dst)
    pro = breakout_pcb.with_suffix(".kicad_pro")
    if pro.exists():
        shutil.copy(pro, tmp_path / "layout.kicad_pro")
    return dst


def _add_cell_zone(pcb, name, net, layer, group_name, solid_pads=True):
    """A copper zone inside a cell's group, the way `pcb layout` stamps a
    module fragment's own plane: a 2 mm square at the cell's centre."""
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    (g,) = [g for g in board.Groups() if g.GetName() == group_name]
    c = g.GetBoundingBox().Centre()
    cx, cy = pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(False)
    z.SetLayer(board.GetLayerID(layer))
    z.SetNetCode(board.GetNetcodeFromNetname(net))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if solid_pads else pcbnew.ZONE_CONNECTION_THERMAL)
    o = z.Outline()
    o.NewOutline()
    for x, y in ((cx - 1, cy - 1), (cx + 1, cy - 1), (cx + 1, cy + 1), (cx - 1, cy + 1)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    z.SetZoneName(name)
    board.Add(z)
    g.AddItem(z)
    board.Save(str(pcb))


def _zone_names(pcb):
    import pcbnew
    return {z.GetZoneName() for z in pcbnew.LoadBoard(str(pcb)).Zones()}


def _write(pcb, settings=None, plane_outline=None):
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True, settings=settings)
    b.plane(Net("GND"), layers=(CopperLayer.B,), outline=plane_outline)
    plan = b.resolve()
    apply_plan(pcb, plan)
    return plan


def test_a_cell_zone_under_the_boards_own_plane_is_merged_into_it(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    _add_cell_zone(pcb, "cell gnd", "GND", "B.Cu", "power_drop0")
    plan = _write(pcb)
    assert "cell gnd" not in _zone_names(pcb)
    assert [(m.cell, m.net, m.layer) for m in plan.merged_zones] == [("power_drop0", "GND", CopperLayer.B)]


def test_zones_merged_from_several_cells_leave_the_board_readable(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    for cell in ("power_drop0", "power_drop1", "bus_drop0", "bus_drop1"):
        _add_cell_zone(pcb, "cell gnd " + cell, "GND", "B.Cu", cell)
    plan = _write(pcb)
    assert len(plan.merged_zones) == 4
    assert not any(n.startswith("cell gnd") for n in _zone_names(pcb))


def test_a_cell_zone_on_a_layer_the_board_has_no_plane_on_is_kept(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    _add_cell_zone(pcb, "cell gnd front", "GND", "F.Cu", "power_drop0")
    plan = _write(pcb)
    assert "cell gnd front" in _zone_names(pcb)
    assert plan.merged_zones == []


def test_a_cell_zone_of_another_net_under_the_plane_is_kept(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    net = next(n for n in read_board(pcb).nets if n not in ("GND", ""))
    _add_cell_zone(pcb, "cell other", net, "B.Cu", "power_drop0")
    _write(pcb)
    assert "cell other" in _zone_names(pcb)


def test_a_cell_zone_the_plane_does_not_wholly_cover_is_kept(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    _add_cell_zone(pcb, "cell gnd", "GND", "B.Cu", "power_drop0")
    corner = [Location(1, 1), Location(5, 1), Location(5, 5), Location(1, 5)]
    plan = _write(pcb, plane_outline=corner)
    assert "cell gnd" in _zone_names(pcb)
    assert plan.merged_zones == []


def test_the_setting_keeps_every_cell_zone(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    _add_cell_zone(pcb, "cell gnd", "GND", "B.Cu", "power_drop0")
    _write(pcb, settings=Settings(copper_cell_zones_under_planes="keep"))
    assert "cell gnd" in _zone_names(pcb)


def test_a_merged_zone_says_how_its_pads_differed_from_the_plane(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    _add_cell_zone(pcb, "cell gnd", "GND", "B.Cu", "power_drop0", solid_pads=False)
    (m,) = _write(pcb).merged_zones
    assert "thermal" in m.note and "solid" in m.note

