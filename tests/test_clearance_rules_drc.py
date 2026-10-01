"""Placemat's own copper judgement and KiCad's DRC agree under a script's clearance rule: a track the
router draws under a rule is clean in kicad-cli's DRC with the rule written beside the board, and the
track it would have drawn without the rule is not. Both directions: a rule that raises the netclass
figure and one that lowers it."""
import json
import subprocess

import pytest

from placemat.copper import Track
from placemat.rules import write_rules
from placemat.values import Net
from tests.conftest import needs_kicad
from tests.test_clearance_rules import _run

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")


def _mm(v):
    return pcbnew.FromMM(v)


def _clearance_violations(tmp_path, plan, rules, name):
    """The clearance violations kicad-cli reports on a board that carries `plan`'s parts' pads and
    tracks, judged with `rules` in the .kicad_dru beside it (the default 0.2 mm netclass otherwise)."""
    board = pcbnew.CreateEmptyBoard()
    nets = {}

    def net(n):
        if n not in nets:
            nets[n] = pcbnew.NETINFO_ITEM(board, n)
            board.Add(nets[n])
        return nets[n]
    for fp in plan.geometry.footprints:
        kfp = pcbnew.FOOTPRINT(board)
        kfp.SetReference(fp.ref)
        kfp.SetPosition(pcbnew.VECTOR2I(_mm(fp.location.x), _mm(fp.location.y)))
        for p in fp.pads:
            kp = pcbnew.PAD(kfp)
            kp.SetShape(pcbnew.PAD_SHAPE_RECT)
            kp.SetSize(pcbnew.VECTOR2I(_mm(p.box.width), _mm(p.box.height)))
            kp.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.F_Cu)
            kp.SetLayerSet(ls)
            kp.SetPosition(pcbnew.VECTOR2I(_mm(p.box.center.x), _mm(p.box.center.y)))
            kp.SetNumber(str(p.number))
            kp.SetNet(net(p.net))
            kfp.Add(kp)
        board.Add(kfp)
    for t in (op for op in plan.copper if isinstance(op, Track)):
        kt = pcbnew.PCB_TRACK(board)
        kt.SetLayer(pcbnew.F_Cu)
        kt.SetWidth(_mm(t.width))
        kt.SetStart(pcbnew.VECTOR2I(_mm(t.start.x), _mm(t.start.y)))
        kt.SetEnd(pcbnew.VECTOR2I(_mm(t.end.x), _mm(t.end.y)))
        kt.SetNet(net(t.net))
        board.Add(kt)
    pcb = tmp_path / ("%s.kicad_pcb" % name)
    board.Save(str(pcb))
    write_rules(str(pcb), rules)
    report = tmp_path / ("%s.json" % name)
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    return [v for v in json.loads(report.read_text()).get("violations", []) if v.get("type") == "clearance"]


def test_kicad_keeps_a_raising_rule_the_router_kept_and_flags_the_track_that_ignores_it(tmp_path):
    rule = dict(clearance=0.4, between=(Net("A"), Net("B")), why="a kept off b")
    ruled, _ = _run([rule], gap=0.25)
    plain, _ = _run([], gap=0.25)
    assert _clearance_violations(tmp_path, plain, ruled.rules, "plain_under_rule")      # the rule is real to KiCad
    assert _clearance_violations(tmp_path, ruled, ruled.rules, "ruled_under_rule") == []
    assert _clearance_violations(tmp_path, plain, [], "plain_under_netclass") == []


def test_kicad_passes_a_lowering_rule_the_router_took_and_flags_the_track_without_it(tmp_path):
    rule = dict(clearance=0.1, between=(Net("A"), Net("B")), why="a close to b")
    ruled, _ = _run([rule], gap=0.15)
    assert _clearance_violations(tmp_path, ruled, ruled.rules, "ruled_under_rule") == []
    assert _clearance_violations(tmp_path, ruled, [], "ruled_under_netclass")           # the rule is real to KiCad


def test_of_two_matching_rules_kicad_and_the_router_keep_the_later(tmp_path):
    on = dict(clearance=0.4, on=Net("A"), why="a is fussy")
    between = dict(clearance=0.1, between=(Net("A"), Net("B")), why="a close to b")
    low_last, _ = _run([on, between], gap=0.15)
    high_last, _ = _run([between, on], gap=0.15)
    assert low_last.rules[-1].min_mm == 0.1 and high_last.rules[-1].min_mm == 0.4
    assert _clearance_violations(tmp_path, low_last, low_last.rules, "low_last") == []
    assert _clearance_violations(tmp_path, high_last, high_last.rules, "high_last") == []
    # the two routes differ, and each is wrong under the other's order
    assert _clearance_violations(tmp_path, low_last, high_last.rules, "low_under_high")
