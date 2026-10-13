"""A named routing phase joins pour nets to their pours alone (pour_join.join_pour: via drops, then a task for each
group still apart) while preserving other pours.
"""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from placemat.kicad.route import router_command
from placemat.settings import Settings
from tests.conftest import needs_breakout, needs_kicad
from tests.phase_helpers import phases


ROUTE_LAYERS = ["F.Cu", "In2.Cu", "B.Cu"]


def _ctx(tmp_path, work):
    """What join_pour reads of a route's phase context (kicad/phase_run.PhaseContext)."""
    return SimpleNamespace(cfg=Settings(), work=work, rpy="py", script="route.py", router_dir=str(tmp_path),
                           iterations=None, probe=None, quick=True, clearances_file=None, env={}, timeout=60,
                           layers=ROUTE_LAYERS, geometry=SimpleNamespace(netclasses={}, min_track_width=0.2),
                           pour_currents={})


COMMON = dict(iterations=None, probe=None, quick=True, clearances=None, neckdown=True, extra_args=())


def _join(ctx, board, out, net, width, layers, stem):
    from placemat.kicad.pour_join import join_pour
    return join_pour(ctx, board, out, net, width, layers, stem, "pour", COMMON)


def _copying(seen=None):
    """A stand-in for subprocess.run of the router and its plane repair: copies its input board to its output, notes
    each call through `seen`, and writes a routed record for each --connections task."""
    import subprocess

    def run(cmd, **kw):
        if seen is not None:
            seen(cmd)
        shutil.copy(cmd[2], cmd[3])
        if "--json-out" in cmd and "--connections" in cmd:
            tasks = json.loads(Path(cmd[cmd.index("--connections") + 1]).read_text())
            Path(cmd[cmd.index("--json-out") + 1]).write_text(json.dumps({"connections": [
                dict(t, status="routed", joined=True, length_mm=1.0, min_width_mm=t["widths"],
                     layers=list(t["widths"]), evidence=None) for t in tasks]}))
        return subprocess.CompletedProcess(cmd, 0)
    return run


def _guarded(pcb, nets):
    """The route's input board as the engine leaves it: every pour net's partial pours guarded on the route's layers."""
    from placemat.kicad.route import guard_partial_pours
    guard_partial_pours(str(pcb), set(nets), ROUTE_LAYERS, 0.9)
    return pcb


def _rule_areas(pcb):
    import pcbnew
    return sorted(z.GetZoneName() for z in pcbnew.LoadBoard(str(pcb)).Zones() if z.GetIsRuleArea())




def test_the_pour_call_names_its_nets_and_their_widths():
    cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu", "B.Cu"], "s.json",
                         nets=["V_HI", "VIN"], widths={"VIN": 0.5})
    i = cmd.index("--nets")
    assert cmd[i + 1:i + 3] == ["VIN", "V_HI"] and "*" not in cmd
    j = cmd.index("--power-nets")
    assert cmd[j + 1] == "VIN" and cmd[cmd.index("--power-nets-widths") + 1] == "0.5"




@needs_kicad
@needs_breakout
def test_a_router_run_joins_the_pads_a_partial_pour_leaves_apart(breakout_pcb, tmp_path):
    import pcbnew
    from placemat.kicad.route import route_board
    from tests.conftest import router_missing
    if router_missing():
        pytest.skip(router_missing())
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
    report = route_board(pcb, tmp_path / "route", pour_nets={net, "GND", "V48P"}, layers=["F.Cu", "In2.Cu", "B.Cu"],
                         quick=True, phases=phases({"name": "pour", "nets": [net]}, {"name": "signals"}))
    pour = report.phases[0]
    assert pour["asked"] > 0 and pour["joined"] > 0, pour
    routed = pcbnew.LoadBoard(str(report.routed_pcb))
    assert any(t.GetNetname() == net for t in routed.GetTracks())
    lid = routed.GetLayerID("In2.Cu")
    assert not any(t.GetNetname() != net and t.GetLayer() == lid and t.GetClass() == "PCB_TRACK"
                   and (outline.Contains(t.GetStart()) or outline.Contains(t.GetEnd())) for t in routed.GetTracks())




def _four_layer_with_pours(breakout_pcb, dest, nets):
    """The breakout, four layers, no tracks, a partial In2 pour of each net over the box round its first two plated
    pads. The breakout's own tracks join every pad of these nets, which would leave join_pour nothing apart to join."""
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
def test_each_pour_net_is_routed_with_the_others_pours_guarded(breakout_pcb, tmp_path, monkeypatch):
    """Two pour nets, each joined in a join_pour of its own: its drop call and its task calls see its own net's guard
    taken off and the other's partial pour kept clear of it, and the board it leaves has its own pour guarded again."""
    import pcbnew
    import placemat.kicad.route as route_mod
    pcb = _guarded(_four_layer_with_pours(breakout_pcb, tmp_path / "in", ["PERMIT_A", "PERMIT_B"]),
                   ["PERMIT_A", "PERMIT_B"])
    passes = []

    def seen(cmd):                    # each call's net: the plane repair's --nets, a task call's --connections tasks
        if "--no-fix-drc-settings" in cmd:
            kind, nets = "drops", cmd[cmd.index("--nets") + 1:cmd.index("--layers")]
        else:
            kind = "tasks"
            nets = sorted({t["net"] for t in json.loads(Path(cmd[cmd.index("--connections") + 1]).read_text())})
        brd = pcbnew.LoadBoard(cmd[2])
        passes.append((kind, nets, sorted(z.GetZoneName() for z in brd.Zones() if z.GetIsRuleArea())))
    monkeypatch.setattr(route_mod.subprocess, "run", _copying(seen))
    work = tmp_path / "work"
    work.mkdir()
    ctx = _ctx(tmp_path, work)
    a, b = work / "p0_0.kicad_pcb", work / "p0_1.kicad_pcb"
    _join(ctx, pcb, a, "PERMIT_A", None, ROUTE_LAYERS, "p0_0")
    assert _rule_areas(a) == ["placemat pour PERMIT_A In2.Cu", "placemat pour PERMIT_B In2.Cu"]
    _join(ctx, a, b, "PERMIT_B", None, ROUTE_LAYERS, "p0_1")
    assert [p[0] for p in passes if p[1] == ["PERMIT_A"]][:2] == ["drops", "tasks"]
    assert [p[0] for p in passes if p[1] == ["PERMIT_B"]][:2] == ["drops", "tasks"]
    assert {(tuple(nets), tuple(guards)) for _, nets, guards in passes} == {
        (("PERMIT_A",), ("placemat pour PERMIT_B In2.Cu",)), (("PERMIT_B",), ("placemat pour PERMIT_A In2.Cu",))}
    assert _rule_areas(b) == ["placemat pour PERMIT_A In2.Cu", "placemat pour PERMIT_B In2.Cu"]


@needs_kicad
@needs_breakout
def test_a_pour_net_routes_on_its_phases_layers_at_its_width_and_keeps_the_inner_guards(breakout_pcb, tmp_path,
                                                                                         monkeypatch):
    """A phase on F and B at 0.5 mm: the drop call and the task calls join on those layers at that width, and the
    inner-layer guards of the other pour net (and its own, put back) stay on the route's layers for the calls after it."""
    import placemat.kicad.route as route_mod
    pcb = _guarded(_four_layer_with_pours(breakout_pcb, tmp_path / "in", ["PERMIT_A", "PERMIT_B"]),
                   ["PERMIT_A", "PERMIT_B"])
    seen = []
    monkeypatch.setattr(route_mod.subprocess, "run", _copying(seen.append))
    work = tmp_path / "work"
    work.mkdir()
    out = work / "p0_0.kicad_pcb"
    _join(_ctx(tmp_path, work), pcb, out, "PERMIT_A", 0.5, ["F.Cu", "B.Cu"], "p0_0")
    assert _rule_areas(out) == ["placemat pour PERMIT_A In2.Cu", "placemat pour PERMIT_B In2.Cu"]
    drops, *tracks = seen
    assert "--no-fix-drc-settings" in drops and tracks          # the drop call, then the tasks for the groups left apart
    assert "--layer-costs" not in drops
    assert drops[drops.index("--layers") + 1:drops.index("--track-width")] == ["F.Cu", "B.Cu"]
    assert drops[drops.index("--track-width") + 1] == "0.5" and drops[drops.index("--max-track-width") + 1] == "0.5"
    for cmd in tracks:
        assert cmd[cmd.index("--layers") + 1:cmd.index("--escalation")] == ["F.Cu", "B.Cu"]
        for t in json.loads(Path(cmd[cmd.index("--connections") + 1]).read_text()):
            assert t["net"] == "PERMIT_A" and t["widths"] == {"F.Cu": 0.5, "B.Cu": 0.5}


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
def test_a_pour_nets_own_graphic_pour_reaches_the_router_as_a_zone(breakout_pcb, tmp_path, monkeypatch):
    """The router credits a net's zones as joining what they reach, but not its filled copper graphics (KRT models
    each as scanline bands and takes every band for an island of the net to join). So the pour net's call hands the
    router the net's own pour as a zone over its copper, and the board it leaves has the pour back as drawn."""
    import pcbnew
    import placemat.kicad.route as route_mod
    pcb, uuid, outline = _graphic_pour(breakout_pcb, tmp_path / "in", "PERMIT_A")
    seen = []

    def look(cmd):                    # the plane repair's input: the pour as a zone
        if "--no-fix-drc-settings" in cmd:
            brd = pcbnew.LoadBoard(cmd[2])
            seen.append(([(z.GetNetname(), brd.GetLayerName(z.GetFirstLayer()), z.Outline().Area(), z.IsFilled())
                          for z in brd.Zones() if not z.GetIsRuleArea() and z.GetNetname() == "PERMIT_A"],
                         [d.m_Uuid.AsString() for d in brd.GetDrawings()
                          if d.IsOnCopperLayer() and d.GetNetname() == "PERMIT_A"]))
    monkeypatch.setattr(route_mod.subprocess, "run", _copying(look))
    work = tmp_path / "work"
    work.mkdir()
    board = work / "p0_0.kicad_pcb"
    _join(_ctx(tmp_path, work), pcb, board, "PERMIT_A", None, ROUTE_LAYERS, "p0_0")
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
def test_a_router_run_lays_no_copper_over_the_pour_nets_own_graphic_pour(breakout_pcb, tmp_path):
    import pcbnew
    from placemat.kicad.route import route_board
    from tests.conftest import router_missing
    if router_missing():
        pytest.skip(router_missing())
    net = "PERMIT_A"
    pcb, uuid, outline = _graphic_pour(breakout_pcb, tmp_path / "in", net)
    report = route_board(pcb, tmp_path / "route", pour_nets={net, "GND", "V48P"}, layers=["F.Cu", "In2.Cu", "B.Cu"],
                         quick=True, phases=phases({"name": "pour", "nets": [net]}, {"name": "signals"}))
    assert report.phases[0]["asked"] > 0, report.phases[0]
    routed = pcbnew.LoadBoard(str(report.routed_pcb))
    lid = routed.GetLayerID("In2.Cu")
    inside = [t for t in routed.GetTracks() if t.GetNetname() == net and t.GetClass() == "PCB_TRACK"
              and t.GetLayer() == lid and outline.Contains(t.GetStart()) and outline.Contains(t.GetEnd())]
    assert inside == []
    assert [d.m_Uuid.AsString() for d in routed.GetDrawings() if d.GetNetname() == net] == [uuid]


@needs_kicad
@needs_breakout
def test_a_cells_graphic_pour_goes_back_into_its_group(breakout_pcb, tmp_path, monkeypatch):
    import pcbnew
    import placemat.kicad.route as route_mod
    pcb, uuid, _ = _graphic_pour(breakout_pcb, tmp_path / "in", "PERMIT_A", group="cell_a")

    monkeypatch.setattr(route_mod.subprocess, "run", _copying())
    work = tmp_path / "work"
    work.mkdir()
    board = work / "p0_0.kicad_pcb"
    _join(_ctx(tmp_path, work), pcb, board, "PERMIT_A", None, ROUTE_LAYERS, "p0_0")
    out = pcbnew.LoadBoard(str(board))
    back, = [d for d in out.GetDrawings() if d.m_Uuid.AsString() == uuid]
    assert back.GetParentGroup() is not None and back.GetParentGroup().GetName() == "cell_a"
