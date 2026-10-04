"""KiCad's DRC judges a keep-out written as a clearance rule (rules.Rule.of) between copper sharing a layer
only, the distinction `checks.keep_out` makes: a pad on the back 0.7 mm from a front pad passes a 2 mm rule,
the same pair on one layer does not, and a via spanning both layers does not."""
import json
import shutil
import subprocess

import pytest

from placemat.rules import Rule
from tests.conftest import needs_kicad

pytestmark = [needs_kicad, pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")]

pcbnew = pytest.importorskip("pcbnew")

RULE = Rule("clearance", 2.0, "U1 keep-out SW to FB: datasheet", between=("SW", "FB"), of="U1")
# the part's rule holds no track or via (a pad escape cannot be told from one); a rule over the nets does
NETS_RULE = Rule("clearance", 2.0, "SW to FB", between=("SW", "FB"))


def _mm(v):
    return pcbnew.FromMM(v)


def _vec(x, y):
    return pcbnew.VECTOR2I(_mm(x), _mm(y))


def _clearances(tmp_path, fb_layer, via=False, rule=RULE):
    """kicad-cli's clearance violations under the keep-out rule: L1's SW pad on F.Cu, U1's FB pad on `fb_layer`
    0.7 mm below it, and with `via`, a SW via 0.7 mm from the FB pad on the other side."""
    board = pcbnew.CreateEmptyBoard()
    nets = {n: pcbnew.NETINFO_ITEM(board, n) for n in ("SW", "FB")}
    for n in nets.values():
        board.Add(n)

    def part(ref, net, layer, cx, cy):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(_vec(cx, cy))
        p = pcbnew.PAD(fp)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetSize(_vec(1.0, 1.0))
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        ls = pcbnew.LSET()
        ls.AddLayer(layer)
        p.SetLayerSet(ls)
        p.SetPosition(_vec(cx, cy))
        p.SetNumber("1")
        p.SetNet(net)
        fp.Add(p)
        board.Add(fp)
    part("L1", nets["SW"], pcbnew.F_Cu, 20.0, 20.0)
    part("U1", nets["FB"], fb_layer, 20.0, 21.7)
    if via:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(_vec(22.4, 21.7))
        v.SetWidth(_mm(0.6))
        v.SetDrill(_mm(0.3))
        v.SetNet(nets["SW"])
        board.Add(v)
    pcb = tmp_path / "board.kicad_pcb"
    board.Save(str(pcb))
    (tmp_path / "board.kicad_dru").write_text("(version 1)\n%s\n" % rule.text())
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   check=True, capture_output=True)
    return [v for v in json.loads(report.read_text())["violations"] if v["type"] == "clearance"]


def test_a_pad_on_the_other_layer_inside_the_distance_passes():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        assert _clearances(Path(d), pcbnew.B_Cu) == []


def test_a_pad_on_the_same_layer_inside_the_distance_fails():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        assert _clearances(Path(d), pcbnew.F_Cu) != []


def test_a_via_spanning_both_layers_inside_the_distance_fails_a_rule_over_the_nets():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        assert _clearances(Path(d), pcbnew.B_Cu, via=True, rule=NETS_RULE) != []
