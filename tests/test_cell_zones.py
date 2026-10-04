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


def _add_cell_zone(pcb, name, net, layer, group_name, solid_pads=True, connection=None, at=None, priority=None):
    """A copper zone inside a cell's group, the way `pcb layout` stamps a
    module fragment's own plane: a 2 mm square at the cell's centre.
    `connection`, a pcbnew ZONE_CONNECTION_* name, overrides `solid_pads`."""
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    (g,) = [g for g in board.Groups() if g.GetName() == group_name]
    c = g.GetBoundingBox().Centre()
    cx, cy = at if at else (pcbnew.ToMM(c.x), pcbnew.ToMM(c.y))
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(False)
    if priority is not None:
        z.SetAssignedPriority(priority)
    z.SetLayer(board.GetLayerID(layer))
    z.SetNetCode(board.GetNetcodeFromNetname(net))
    z.SetPadConnection(getattr(pcbnew, connection) if connection
                       else pcbnew.ZONE_CONNECTION_FULL if solid_pads else pcbnew.ZONE_CONNECTION_THERMAL)
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


def _write(pcb, settings=None, plane_outline=None, solid_pads=None):
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True, settings=settings)
    extra = {} if solid_pads is None else {"solid_pads": solid_pads}
    b.plane(Net("GND"), layers=(CopperLayer.B,), outline=plane_outline, **extra)
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


def test_a_cell_zone_whose_pads_join_otherwise_than_the_planes_is_kept(breakout_pcb, tmp_path):
    """A cell's solid pour under a thermal board fill (its RF shunts and
    exposed pads joined solidly): merged, those joins became thermal spokes
    or none. It stays, and the run says why."""
    pcb = _copy(breakout_pcb, tmp_path)
    _add_cell_zone(pcb, "cell gnd", "GND", "B.Cu", "power_drop0", solid_pads=True)
    plan = _write(pcb, solid_pads=False)
    assert "cell gnd" in _zone_names(pcb)
    assert plan.merged_zones == []
    (k,) = plan.kept_zones
    assert k.cell == "power_drop0" and "solid" in k.note and "thermal" in k.note


def test_a_thermal_cell_zone_under_a_solid_plane_is_kept_too(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    _add_cell_zone(pcb, "cell gnd", "GND", "B.Cu", "power_drop0", solid_pads=False)
    plan = _write(pcb, solid_pads=True)
    assert "cell gnd" in _zone_names(pcb) and plan.merged_zones == []


@pytest.mark.parametrize("connection, said", [("ZONE_CONNECTION_THT_THERMAL", "solid, thermal on through pads"),
                                              ("ZONE_CONNECTION_NONE", "not joined")])
def test_a_cell_zone_joining_pads_any_other_way_is_kept(breakout_pcb, tmp_path, connection, said):
    """Solid surface pads with thermal through pads, or pads left unjoined:
    merged into a thermal plane, they would all get spokes."""
    pcb = _copy(breakout_pcb, tmp_path)
    _add_cell_zone(pcb, "cell gnd", "GND", "B.Cu", "power_drop0", connection=connection)
    plan = _write(pcb, solid_pads=False)
    assert "cell gnd" in _zone_names(pcb) and plan.merged_zones == []
    (k,) = plan.kept_zones
    assert "its pads were %s, the plane's are thermal" % said in k.note, k.note


def test_a_cell_zone_reaching_nearer_the_edge_than_the_plane_is_merged(breakout_pcb, tmp_path):
    """A cell against the board edge: its zone runs 0.2 mm from the edge,
    the plane stops at the keep-in. The strip between holds no copper, so
    the plane covers all of the zone that can."""
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path)
    g = read_board(pcb)
    ob, keep = g.outline_box, g.edge_clearance
    board = pcbnew.LoadBoard(str(pcb))
    (grp,) = [x for x in board.Groups() if x.GetName() == "power_drop0"]
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(False)
    z.SetLayer(board.GetLayerID("B.Cu"))
    z.SetNetCode(board.GetNetcodeFromNetname("GND"))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)          # as the plane joins pads: only the edge is at issue
    o = z.Outline()
    o.NewOutline()
    x0, y0 = ob.left + 0.2, ob.top + 10
    for x, y in ((x0, y0), (x0 + 3, y0), (x0 + 3, y0 + 3), (x0, y0 + 3)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    z.SetZoneName("cell gnd at the edge")
    board.Add(z)
    grp.AddItem(z)
    board.Save(str(pcb))
    plan = _write(pcb)
    assert keep > 0.2 and "cell gnd at the edge" not in _zone_names(pcb)
    assert [(m.cell, m.net) for m in plan.merged_zones] == [("power_drop0", "GND")]


def _zone_priorities(pcb, *names):
    import pcbnew
    zs = {z.GetZoneName(): z for z in pcbnew.LoadBoard(str(pcb)).Zones()}
    return [zs[n].GetAssignedPriority() for n in names]


def _zones_intersect(pcb, tmp_path):
    import json
    import subprocess
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=180)
    # the breakout's own plane is written as pieces at priority 0 that KiCad reports against each other: not the cells' zones
    return [v for v in json.loads(report.read_text()).get("violations", []) if v.get("type") == "zones_intersect"
            and any("priority 0" not in i["description"] for i in v["items"])]


def _two_overlapping(breakout_pcb, tmp_path, layer="F.Cu"):
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path)
    b = pcbnew.LoadBoard(str(pcb))
    c = next(g for g in b.Groups() if g.GetName() == "power_drop0").GetBoundingBox().Centre()
    at = (pcbnew.ToMM(c.x), pcbnew.ToMM(c.y))
    _add_cell_zone(pcb, "cell gnd a", "GND", layer, "power_drop0", at=at, priority=1)
    _add_cell_zone(pcb, "cell gnd b", "GND", layer, "power_drop1", at=(at[0] + 1, at[1]), priority=1)
    return pcb


def test_two_cells_zones_of_one_net_overlapping_at_one_priority_are_given_distinct_ones(breakout_pcb, tmp_path):
    pcb = _two_overlapping(breakout_pcb, tmp_path)
    assert len(_zones_intersect(pcb, tmp_path)) == 1          # the stamped cells as they arrive
    plan = _write(pcb)
    a, b = _zone_priorities(pcb, "cell gnd a", "cell gnd b")
    assert a != b and min(a, b) >= 1
    assert _zones_intersect(pcb, tmp_path) == []
    assert plan.merged_zones == []


def test_two_cells_zones_on_a_layer_the_plane_covers_are_merged_and_none_intersect(breakout_pcb, tmp_path):
    pcb = _two_overlapping(breakout_pcb, tmp_path, layer="B.Cu")
    _write(pcb)
    assert _zones_intersect(pcb, tmp_path) == []


def test_cells_zones_that_do_not_overlap_keep_their_priority(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    for cell in ("power_drop0", "power_drop1"):
        _add_cell_zone(pcb, "cell gnd " + cell, "GND", "F.Cu", cell, priority=1)
    _write(pcb)
    assert _zone_priorities(pcb, "cell gnd power_drop0", "cell gnd power_drop1") == [1, 1]
