"""A pour net's pads the pours do not reach: `[route] islands` (or
`placemat route --islands NET[=WIDTH]`) routes those nets first, alone, the
pours counted as joined copper by the router, at the net's class width or
the width given; the main pass then leaves them to their pours as before."""
import shutil
from pathlib import Path

import pytest

from placemat.kicad.route import parse_islands, router_command
from tests.conftest import needs_breakout, needs_kicad


def test_an_island_net_may_carry_a_width():
    assert parse_islands(["VSHUNT", "VBIKE=0.5"]) == {"VSHUNT": None, "VBIKE": 0.5}
    with pytest.raises(ValueError, match="VBIKE=wide"):
        parse_islands(["VBIKE=wide"])


def test_the_islands_pass_names_its_nets_and_their_widths():
    cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu", "B.Cu"], "s.json",
                         nets=["VSHUNT", "VBIKE"], widths={"VBIKE": 0.5})
    i = cmd.index("--nets")
    assert cmd[i + 1:i + 3] == ["VBIKE", "VSHUNT"] and "*" not in cmd
    j = cmd.index("--power-nets")
    assert cmd[j + 1] == "VBIKE" and cmd[cmd.index("--power-nets-widths") + 1] == "0.5"


def test_the_route_command_passes_the_setting_and_the_flag(tmp_path, monkeypatch):
    from placemat import cli
    import placemat.kicad.route as route_mod
    (tmp_path / "placemat.toml").write_text('[route]\nislands = ["VSHUNT"]\n')
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    seen = {}

    class Report:
        valid, keepout_breaches, open_nets, routed_pcb = True, [], {}, pcb

        def summary(self):
            return "stand-in"

    def stand_in(pcb, work, exclude_nets=(), islands=None, **kw):
        seen["islands"] = islands
        return Report()
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb), "--islands", "VBIKE=0.5"]) == 0
    assert seen["islands"] == {"VSHUNT": None, "VBIKE": 0.5}


@needs_kicad
@needs_breakout
def test_a_router_run_joins_the_pads_a_partial_pour_leaves_apart(breakout_pcb, tmp_path):
    import pcbnew
    from placemat.kicad.route import ROUTER_DEFAULT, route_board
    if not (Path(ROUTER_DEFAULT) / ".venv/bin/python").exists():
        pytest.skip("KiCadRoutingTools not at %s" % ROUTER_DEFAULT)
    net = "PERMIT_A"        # five plated pads and no copper graphics of its own (the router cannot land on one)
    dest = tmp_path / "in"
    dest.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), dest / ("layout" + ext))
    pcb = dest / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    brd.SetCopperLayerCount(4)
    for t in list(brd.GetTracks()):
        brd.Delete(t)
    pads = sorted((p for f in brd.GetFootprints() for p in f.Pads()
                   if p.GetNetname() == net and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH),
                  key=lambda p: p.GetPosition().y)
    near = pads[:len(pads) // 2]
    box = near[0].GetBoundingBox()
    for p in near[1:]:
        box.Merge(p.GetBoundingBox())
    box.Inflate(pcbnew.FromMM(1.5))
    assert not any(box.Contains(p.GetPosition()) for p in pads[len(pads) // 2:])
    z = pcbnew.ZONE(brd)
    z.SetLayer(brd.GetLayerID("In2.Cu"))
    z.SetNetCode(brd.GetNetcodeFromNetname(net))
    o = z.Outline()
    o.NewOutline()
    for x, y in ((box.GetLeft(), box.GetTop()), (box.GetRight(), box.GetTop()), (box.GetRight(), box.GetBottom()),
                 (box.GetLeft(), box.GetBottom())):
        o.Append(x, y)
    brd.Add(z)
    brd.Save(str(pcb))
    outline = pcbnew.SHAPE_POLY_SET(z.Outline())
    report = route_board(pcb, tmp_path / "route", exclude_nets={net, "GND", "V48P"}, layers=["F.Cu", "In2.Cu", "B.Cu"],
                         quick=True, islands={net: None})
    before, after = report.islands[net]
    assert before > 0 and after < before, report.islands
    routed = pcbnew.LoadBoard(str(report.routed_pcb))
    assert any(t.GetNetname() == net for t in routed.GetTracks())
    lid = routed.GetLayerID("In2.Cu")
    assert not any(t.GetNetname() != net and t.GetLayer() == lid and t.GetClass() == "PCB_TRACK"
                   and (outline.Contains(t.GetStart()) or outline.Contains(t.GetEnd())) for t in routed.GetTracks())
