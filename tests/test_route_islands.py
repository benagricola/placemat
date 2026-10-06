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
    assert parse_islands(["V_HI", "VIN=0.5"]) == {"V_HI": None, "VIN": 0.5}
    with pytest.raises(ValueError, match="VIN=wide"):
        parse_islands(["VIN=wide"])


def test_the_islands_pass_names_its_nets_and_their_widths():
    cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu", "B.Cu"], "s.json",
                         nets=["V_HI", "VIN"], widths={"VIN": 0.5})
    i = cmd.index("--nets")
    assert cmd[i + 1:i + 3] == ["VIN", "V_HI"] and "*" not in cmd
    j = cmd.index("--power-nets")
    assert cmd[j + 1] == "VIN" and cmd[cmd.index("--power-nets-widths") + 1] == "0.5"


@needs_kicad
def test_the_route_command_passes_the_setting_and_the_flag(tmp_path, monkeypatch):
    from placemat import cli
    import placemat.kicad.route as route_mod
    (tmp_path / "placemat.toml").write_text('[route]\nislands = ["V_HI"]\n')
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    seen = {}

    class Report:
        valid, keepout_breaches, open_nets, routed_pcb, resumed, widths, pair_layers_refused = True, [], {}, pcb, [], [], []

        def has_findings(self):
            return False

        def summary(self):
            return "stand-in"

    def stand_in(pcb, work, exclude_nets=(), islands=None, **kw):
        seen["islands"] = islands
        return Report()
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb), "--islands", "VIN=0.5"]) == 0
    assert seen["islands"] == {"V_HI": None, "VIN": 0.5}


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


def test_a_malformed_island_entry_is_refused_when_the_settings_load(tmp_path):
    from placemat.settings import SettingsError, load
    for bad in ('"VIN=wide"', '"=0.5"', '"VIN=0"'):
        (tmp_path / "placemat.toml").write_text('[route]\nislands = [%s]\n' % bad)
        with pytest.raises(SettingsError, match="route.islands"):
            load(tmp_path)


@needs_kicad
def test_a_bare_flag_keeps_the_width_the_setting_gives(tmp_path, monkeypatch):
    from placemat import cli
    import placemat.kicad.route as route_mod
    (tmp_path / "placemat.toml").write_text('[route]\nislands = ["VIN=0.5"]\n')
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    seen = {}

    class Report:
        valid, keepout_breaches, open_nets, routed_pcb, resumed, widths, pair_layers_refused = True, [], {}, pcb, [], [], []

        def has_findings(self):
            return False

        def summary(self):
            return "stand-in"

    def stand_in(pcb, work, exclude_nets=(), islands=None, **kw):
        seen["islands"] = islands
        return Report()
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb), "--islands", "VIN", "V_HI"]) == 0
    assert seen["islands"] == {"VIN": 0.5, "V_HI": None}
    assert cli.main(["route", str(pcb), "--islands", "VIN=wide"]) == 2


def _four_layer_with_pours(breakout_pcb, dest, nets):
    """The breakout, four layers, a partial In2 pour of each net over the
    box round its first two plated pads."""
    import pcbnew
    dest.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), dest / ("layout" + ext))
    pcb = dest / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    brd.SetCopperLayerCount(4)
    for net in nets:
        pads = [p for f in brd.GetFootprints() for p in f.Pads()
                if p.GetNetname() == net and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH][:2]
        box = pads[0].GetBoundingBox()
        box.Merge(pads[1].GetBoundingBox())
        box.Inflate(pcbnew.FromMM(1.0))
        z = pcbnew.ZONE(brd)
        z.SetLayer(brd.GetLayerID("In2.Cu"))
        z.SetNetCode(brd.GetNetcodeFromNetname(net))
        o = z.Outline()
        o.NewOutline()
        for x, y in ((box.GetLeft(), box.GetTop()), (box.GetRight(), box.GetTop()),
                     (box.GetRight(), box.GetBottom()), (box.GetLeft(), box.GetBottom())):
            o.Append(x, y)
        brd.Add(z)
    brd.Save(str(pcb))
    return pcb


@needs_kicad
@needs_breakout
def test_each_island_net_is_routed_with_the_others_pours_guarded(breakout_pcb, tmp_path, monkeypatch):
    """Two island nets: each pass routes one, the other's partial pour kept
    clear of it, and the board the main pass gets has neither guard (the
    main pass guards both)."""
    import subprocess
    import pcbnew
    import placemat.kicad.route as route_mod
    pcb = _four_layer_with_pours(breakout_pcb, tmp_path / "in", ["PERMIT_A", "PERMIT_B"])
    passes = []

    def stand_in(cmd, **kw):          # the router: copies its input to its output
        inp, out = cmd[2], cmd[3]
        nets = cmd[cmd.index("--nets") + 1:cmd.index("--layers")]
        brd = pcbnew.LoadBoard(inp)
        passes.append((nets, sorted(z.GetZoneName() for z in brd.Zones() if z.GetIsRuleArea())))
        shutil.copy(inp, out)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(route_mod.subprocess, "run", stand_in)
    work = tmp_path / "work"
    work.mkdir()
    board, breaches = route_mod.route_islands("py", "route.py", str(tmp_path), pcb, work,
                                              {"PERMIT_A": None, "PERMIT_B": None}, ["F.Cu", "In2.Cu", "B.Cu"],
                                              None, None, True, 60, {}, 0.9)
    assert passes == [(["PERMIT_A"], ["placemat pour PERMIT_B In2.Cu"]),
                      (["PERMIT_B"], ["placemat pour PERMIT_A In2.Cu"])]
    assert breaches == []
    assert not [z for z in pcbnew.LoadBoard(str(board)).Zones() if z.GetIsRuleArea()]


@needs_kicad
@needs_breakout
def test_an_island_net_not_on_the_board_is_said_and_skipped(breakout_pcb):
    from placemat.kicad.route import islands_on_board
    kept, missing = islands_on_board(breakout_pcb, {"PERMIT_A": None, "NO_SUCH_NET": 0.5})
    assert kept == {"PERMIT_A": None} and missing == ["NO_SUCH_NET"]


def test_an_island_net_may_carry_its_own_layers():
    from placemat.settings import parse_island_layers
    items = ["VBUS=1.37@F,B", "V_HI@In2.Cu", "V_LO=0.4@B.Cu,in1,F.Cu", "VIN"]
    assert parse_islands(items) == {"VBUS": 1.37, "V_HI": None, "V_LO": 0.4, "VIN": None}
    assert parse_island_layers(items) == {"VBUS": ("F.Cu", "B.Cu"), "V_HI": ("In2.Cu",),
                                          "V_LO": ("F.Cu", "In1.Cu", "B.Cu")}     # in stack order, F first and B last


def test_an_unknown_island_layer_is_refused():
    for bad, said in (("VBUS=1.37@F,X", "X"), ("VBUS@In31", "In31"), ("VBUS@", "VBUS@"), ("VBUS=1@F,,B", "VBUS=1@F,,B")):
        with pytest.raises(ValueError, match=said):
            parse_islands([bad])


def test_an_unknown_island_layer_is_refused_when_the_settings_load(tmp_path):
    from placemat.settings import SettingsError, load
    (tmp_path / "placemat.toml").write_text('[route]\nislands = ["VBUS=1.37@F,Q"]\n')
    with pytest.raises(SettingsError, match=r"route\.islands.*'Q' is not a copper layer"):
        load(tmp_path)


def test_an_island_layer_the_board_lacks_is_refused():
    from placemat.kicad.route import island_layers_on_board
    assert island_layers_on_board({"VBUS": ("F.Cu", "B.Cu")}, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]) == {"VBUS": ["F.Cu", "B.Cu"]}
    with pytest.raises(ValueError, match="VBUS.*In3.Cu"):
        island_layers_on_board({"VBUS": ("F.Cu", "In3.Cu")}, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"])


def test_the_report_records_each_islands_layers():
    from placemat.kicad.route import RouteReport
    r = RouteReport(True, 1.0, 1.0, 0, 0, {}, [], [], ["F.Cu", "B.Cu"], 0.0, "", {}, Path("r"), Path("l"), Path("w"),
                    island_layers={"VBUS": ["F.Cu", "B.Cu"]})
    assert r.as_dict()["island_layers"] == {"VBUS": ["F.Cu", "B.Cu"]}
    assert "VBUS on F.Cu, B.Cu" in r.summary()


@needs_kicad
def test_the_route_command_passes_each_islands_layers(tmp_path, monkeypatch):
    from placemat import cli
    import placemat.kicad.route as route_mod
    (tmp_path / "placemat.toml").write_text('[route]\nislands = ["VBUS=1.37@F,B", "VIN@B"]\n')
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    seen = {}

    class Report:
        valid, keepout_breaches, open_nets, routed_pcb, resumed, widths, pair_layers_refused = True, [], {}, pcb, [], [], []

        def has_findings(self):
            return False

        def summary(self):
            return "stand-in"

    def stand_in(pcb, work, exclude_nets=(), islands=None, island_layers=None, **kw):
        seen["islands"], seen["layers"] = islands, island_layers
        return Report()
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb), "--islands", "VBUS", "VIN@F", "V_HI"]) == 0
    assert seen["islands"] == {"VBUS": 1.37, "VIN": None, "V_HI": None}
    assert seen["layers"] == {"VBUS": ("F.Cu", "B.Cu"), "VIN": ("F.Cu",)}       # a bare flag keeps the setting's layers
    assert cli.main(["route", str(pcb), "--islands", "VIN@Z"]) == 2


@needs_kicad
@needs_breakout
def test_an_island_with_layers_routes_on_them_and_a_bare_one_on_the_routes(breakout_pcb, tmp_path, monkeypatch):
    import subprocess
    import placemat.kicad.route as route_mod
    pcb = _four_layer_with_pours(breakout_pcb, tmp_path / "in", ["PERMIT_A", "PERMIT_B"])
    passes = {}

    def stand_in(cmd, **kw):
        nets = cmd[cmd.index("--nets") + 1:cmd.index("--layers")]
        passes[nets[0]] = cmd[cmd.index("--layers") + 1:cmd.index("--escalation")]
        assert "--layer-costs" not in cmd
        shutil.copy(cmd[2], cmd[3])
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(route_mod.subprocess, "run", stand_in)
    work = tmp_path / "work"
    work.mkdir()
    route_mod.route_islands("py", "route.py", str(tmp_path), pcb, work, {"PERMIT_A": 0.5, "PERMIT_B": None},
                            ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], None, None, True, 60, {}, 0.9,
                            island_layers={"PERMIT_A": ["F.Cu", "B.Cu"]})
    assert passes == {"PERMIT_A": ["F.Cu", "B.Cu"], "PERMIT_B": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]}


def _graphic_pour(breakout_pcb, dest, net, group=None):
    """The breakout, four layers, no tracks, and a filled copper polygon of `net` on In2 drawn as `board.pour` draws one
    (write.py _draw_pour): a pentagon standing on the net's topmost plated pad, off the board's other pads, its slanted
    sides giving the router a band per scanline. Returns (board path, the polygon's uuid, its outline)."""
    import pcbnew
    dest.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), dest / ("layout" + ext))
    pcb = dest / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    brd.SetCopperLayerCount(4)
    for t in list(brd.GetTracks()):
        brd.Delete(t)
    pad = min((p for f in brd.GetFootprints() for p in f.Pads()
               if p.GetNetname() == net and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH), key=lambda p: p.GetPosition().y)
    cx, cy = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
    one = pcbnew.SHAPE_POLY_SET()
    one.NewOutline()
    for x, y in ((cx - 1.3, cy), (cx + 1.3, cy), (cx + 2.3, cy - 5.0), (cx, cy - 8.5), (cx - 2.3, cy - 5.0)):
        one.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    sh = pcbnew.PCB_SHAPE(brd, pcbnew.SHAPE_T_POLY)
    sh.SetLayer(brd.GetLayerID("In2.Cu"))
    sh.SetFilled(True)
    sh.SetWidth(pcbnew.FromMM(0.2))
    sh.SetPolyShape(one)
    sh.SetNetCode(brd.GetNetcodeFromNetname(net))
    brd.Add(sh)
    if group is not None:                   # a cell's pour, in the cell's group
        g = pcbnew.PCB_GROUP(brd)
        g.SetName(group)
        brd.Add(g)
        g.AddItem(sh)
    brd.Save(str(pcb))
    return pcb, sh.m_Uuid.AsString(), pcbnew.SHAPE_POLY_SET(one)


@needs_kicad
@needs_breakout
def test_an_island_nets_own_graphic_pour_reaches_the_router_as_a_zone(breakout_pcb, tmp_path, monkeypatch):
    """The router credits a net's zones as joining what they reach, but not its filled copper graphics (KRT models
    each as scanline bands and takes every band for an island of the net to join). So the island pass hands the
    router the net's own pour as a zone over its copper, and the board it leaves has the pour back as drawn."""
    import subprocess
    import pcbnew
    import placemat.kicad.route as route_mod
    pcb, uuid, outline = _graphic_pour(breakout_pcb, tmp_path / "in", "PERMIT_A")
    seen = []

    def stand_in(cmd, **kw):          # the router: copies its input to its output
        inp, out = cmd[2], cmd[3]
        brd = pcbnew.LoadBoard(inp)
        seen.append(([(z.GetNetname(), brd.GetLayerName(z.GetFirstLayer()), z.Outline().Area(), z.IsFilled())
                      for z in brd.Zones() if not z.GetIsRuleArea() and z.GetNetname() == "PERMIT_A"],
                     [d.m_Uuid.AsString() for d in brd.GetDrawings() if d.IsOnCopperLayer() and d.GetNetname() == "PERMIT_A"]))
        shutil.copy(inp, out)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(route_mod.subprocess, "run", stand_in)
    work = tmp_path / "work"
    work.mkdir()
    board, _ = route_mod.route_islands("py", "route.py", str(tmp_path), pcb, work, {"PERMIT_A": None},
                                       ["F.Cu", "In2.Cu", "B.Cu"], None, None, True, 60, {}, 0.9)
    (zones, graphics), = seen
    assert graphics == []
    (net, layer, area, filled), = [z for z in zones if z[1] == "In2.Cu"]
    assert (net, layer, filled) == ("PERMIT_A", "In2.Cu", True) and area >= outline.Area()
    out = pcbnew.LoadBoard(str(board))
    assert not [z for z in out.Zones() if z.GetNetname() == "PERMIT_A"]
    back, = [d for d in out.GetDrawings() if d.m_Uuid.AsString() == uuid]
    assert (back.GetNetname(), out.GetLayerName(back.GetLayer()), back.IsSolidFill()) == ("PERMIT_A", "In2.Cu", True)
    assert back.GetPolyShape().Area() == outline.Area() and back.GetWidth() == pcbnew.FromMM(0.2)


@needs_kicad
@needs_breakout
def test_a_router_run_lays_no_copper_over_the_island_nets_own_graphic_pour(breakout_pcb, tmp_path):
    import pcbnew
    from placemat.kicad.route import ROUTER_DEFAULT, route_board
    if not (Path(ROUTER_DEFAULT) / ".venv/bin/python").exists():
        pytest.skip("KiCadRoutingTools not at %s" % ROUTER_DEFAULT)
    net = "PERMIT_A"
    pcb, uuid, outline = _graphic_pour(breakout_pcb, tmp_path / "in", net)
    report = route_board(pcb, tmp_path / "route", exclude_nets={net, "GND", "V48P"}, layers=["F.Cu", "In2.Cu", "B.Cu"],
                         quick=True, islands={net: None})
    before, after = report.islands[net]
    assert after <= before, report.islands
    routed = pcbnew.LoadBoard(str(report.routed_pcb))
    lid = routed.GetLayerID("In2.Cu")
    inside = [t for t in routed.GetTracks() if t.GetNetname() == net and t.GetClass() == "PCB_TRACK"
              and t.GetLayer() == lid and outline.Contains(t.GetStart()) and outline.Contains(t.GetEnd())]
    assert inside == []
    assert [d.m_Uuid.AsString() for d in routed.GetDrawings() if d.GetNetname() == net] == [uuid]


@needs_kicad
@needs_breakout
def test_a_cells_graphic_pour_goes_back_into_its_group(breakout_pcb, tmp_path, monkeypatch):
    import subprocess
    import pcbnew
    import placemat.kicad.route as route_mod
    pcb, uuid, _ = _graphic_pour(breakout_pcb, tmp_path / "in", "PERMIT_A", group="cell_a")

    def stand_in(cmd, **kw):
        shutil.copy(cmd[2], cmd[3])
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(route_mod.subprocess, "run", stand_in)
    work = tmp_path / "work"
    work.mkdir()
    board, _ = route_mod.route_islands("py", "route.py", str(tmp_path), pcb, work, {"PERMIT_A": None},
                                       ["F.Cu", "In2.Cu", "B.Cu"], None, None, True, 60, {}, 0.9)
    out = pcbnew.LoadBoard(str(board))
    back, = [d for d in out.GetDrawings() if d.m_Uuid.AsString() == uuid]
    assert back.GetParentGroup() is not None and back.GetParentGroup().GetName() == "cell_a"
