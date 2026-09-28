"""placemat route reads the board's own settings: its placemat.toml's
[route] layers, not the defaults."""
from pathlib import Path

import pytest

from tests.conftest import needs_breakout, needs_kicad


def test_the_route_command_routes_with_the_boards_own_settings(tmp_path, monkeypatch):
    from placemat import cli
    import placemat.kicad.route as route_mod
    from placemat.settings import active
    (tmp_path / "placemat.toml").write_text('[route]\nlayers = ["F.Cu", "B.Cu"]\n')
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    seen = {}

    class Report:
        valid, keepout_breaches, open_nets, routed_pcb = True, [], {}, pcb

        def summary(self):
            return "route: stand-in"

        def as_dict(self):
            return {}

    def stand_in(pcb, work, **kw):
        seen["layers"] = active().route_layers
        return Report()
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb)]) == 0
    assert tuple(seen["layers"]) == ("F.Cu", "B.Cu")


@needs_kicad
@needs_breakout
def test_the_route_command_leaves_the_boards_plane_nets_to_their_pours(breakout_pcb, tmp_path, monkeypatch):
    """run --route leaves the plan's plane nets out; placemat route did not,
    and the router laid thin tracks on a net with a pour, and on GND."""
    import shutil
    import pcbnew
    import pytest
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
        valid, keepout_breaches, open_nets, routed_pcb = True, [], {}, pcb

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
