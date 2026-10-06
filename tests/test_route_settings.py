"""placemat route: [route] layers is retired (route layers are a board
fact, from each layer's role); `placemat route --layers` still overrides
for one run."""

import pytest

from tests.conftest import needs_breakout, needs_kicad


def test_route_layers_in_placemat_toml_is_refused(tmp_path):
    from placemat.settings import SettingsError, load
    (tmp_path / "placemat.toml").write_text('[route]\nlayers = ["F.Cu", "B.Cu"]\n')
    with pytest.raises(SettingsError, match="route.layers"):
        load(tmp_path)


@needs_kicad
def test_the_route_command_s_layers_flag_overrides_for_one_run(tmp_path, monkeypatch):
    from placemat import cli
    import placemat.kicad.route as route_mod
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    seen = {}

    class Report:
        valid, keepout_breaches, open_nets, routed_pcb, resumed, widths, pair_layers_refused = True, [], {}, pcb, [], [], []

        def has_findings(self):
            return False

        def summary(self):
            return "route: stand-in"

        def as_dict(self):
            return {}

    def stand_in(pcb, work, layers=None, **kw):
        seen["layers"] = layers
        return Report()
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb), "--layers", "F.Cu", "B.Cu"]) == 0
    assert tuple(seen["layers"]) == ("F.Cu", "B.Cu")


@needs_kicad
@needs_breakout
def test_the_route_command_leaves_the_boards_plane_nets_to_their_pours(breakout_pcb, tmp_path, monkeypatch):
    """run --route leaves the plan's plane nets out; placemat route did not,
    and the router laid thin tracks on a net with a pour, and on GND."""
    import shutil
    import pcbnew
    from placemat import cli
    import placemat.kicad.route as route_mod
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    z = pcbnew.ZONE(brd)
    z.SetLayer(pcbnew.B_Cu)
    z.SetNetCode(brd.GetNetcodeFromNetname("V48P"))
    o = z.Outline()
    o.NewOutline()
    for x, y in ((10, 10), (20, 10), (20, 20), (10, 20)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    brd.Add(z)
    brd.Save(str(pcb))
    seen = {}

    class Report:
        valid, keepout_breaches, open_nets, routed_pcb, resumed, widths, pair_layers_refused = True, [], {}, pcb, [], [], []

        def has_findings(self):
            return False

        def summary(self):
            return "stand-in"

    def stand_in(pcb, work, exclude_nets=(), **kw):
        seen["exclude"] = set(exclude_nets)
        return Report()
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb), "--exclude", "EXTRA"]) == 0
    assert {"V48P", "EXTRA"} <= seen["exclude"]


@needs_kicad
@needs_breakout
def test_a_cells_own_zone_leaves_its_net_to_the_router(breakout_pcb, tmp_path):
    """run --route leaves out the script's own planes and pours, not a stamped
    cell's local zone: its net (a regulator's output, say) runs to parts
    elsewhere that still need routing."""
    import shutil
    import pcbnew
    from placemat.kicad.route import plane_nets_of
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    before = plane_nets_of(pcb)
    net = next(n for n in ("V48P", "TERM_NEAR_MID") if n not in before)
    brd = pcbnew.LoadBoard(str(pcb))
    z = pcbnew.ZONE(brd)
    z.SetLayer(pcbnew.B_Cu)
    z.SetNetCode(brd.GetNetcodeFromNetname(net))
    o = z.Outline()
    o.NewOutline()
    for x, y in ((10, 10), (20, 10), (20, 20), (10, 20)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    brd.Add(z)
    grp = pcbnew.PCB_GROUP(brd)
    grp.SetName("cell")
    brd.Add(grp)
    grp.AddItem(z)
    brd.Save(str(pcb))
    assert net not in plane_nets_of(pcb)


TEARDROP_ZONE = """	(zone
		(net {code})
		(net_name "{net}")
		(layer "{layer}")
		(uuid "00000000-0000-4000-8000-0000000000{code:02d}")
		(name "$teardrop_padvia$")
		(hatch full 0.1)
		(priority 30053)
		(attr
			(teardrop
				(type padvia)
			)
		)
		(connect_pads yes
			(clearance 0)
		)
		(min_thickness 0.0254)
		(filled_areas_thickness no)
		(fill yes
			(thermal_gap 0.5)
			(thermal_bridge_width 0.5)
			(island_removal_mode 1)
			(island_area_min 10)
		)
		(polygon
			(pts
				(xy 10 10) (xy 11 10) (xy 11 11) (xy 10 11)
			)
		)
	)
"""


def add_teardrop_zone(pcb, net, layer="B.Cu"):
    """Append a KiCad teardrop zone (what the teardrop generator writes at a pad or via) on `net` to the board file."""
    import pcbnew
    code = pcbnew.LoadBoard(str(pcb)).GetNetcodeFromNetname(net)
    text = pcb.read_text().rstrip()
    assert text.endswith(")")
    pcb.write_text(text[:-1] + TEARDROP_ZONE.format(code=code, net=net, layer=layer) + ")\n")
    zone = next(z for z in pcbnew.LoadBoard(str(pcb)).Zones() if z.GetZoneName() == "$teardrop_padvia$")
    assert zone.IsTeardropArea() and zone.GetNetname() == net


def _board_with_teardrop_zone(breakout_pcb, tmp_path):
    """A copy of the breakout board with a teardrop zone on a net it has no pour on: (pcb, net)."""
    import shutil
    from placemat.kicad.route import plane_nets_of
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    net = next(n for n in ("V48P", "TERM_NEAR_MID") if n not in plane_nets_of(pcb))
    add_teardrop_zone(pcb, net)
    return pcb, net


@needs_kicad
@needs_breakout
def test_a_teardrop_zone_is_not_a_pour(breakout_pcb, tmp_path):
    """A teardrop zone widens a track at a pad or via; it serves no net by a pour, so the net is routed and
    counted in the closure."""
    from placemat.kicad.route import plane_nets_of
    pcb, net = _board_with_teardrop_zone(breakout_pcb, tmp_path)
    assert net not in plane_nets_of(pcb)


@needs_kicad
@needs_breakout
def test_a_plane_is_not_raised_over_a_teardrop_zone(breakout_pcb, tmp_path):
    """A teardrop zone has its own very high priority and KiCad does not report it as an intersecting zone:
    a plane drawn over it keeps its priority."""
    import pcbnew
    from placemat.kicad.write import _raise_planes_over_zones
    pcb, net = _board_with_teardrop_zone(breakout_pcb, tmp_path)
    brd = pcbnew.LoadBoard(str(pcb))
    z = pcbnew.ZONE(brd)
    z.SetLayer(pcbnew.B_Cu)
    z.SetNetCode(brd.GetNetcodeFromNetname(net))
    o = z.Outline()
    o.NewOutline()
    for x, y in ((9, 9), (12, 9), (12, 12), (9, 12)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    brd.Add(z)
    _raise_planes_over_zones(brd, [z])
    assert z.GetAssignedPriority() == 0
