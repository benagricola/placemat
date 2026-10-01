"""kicad-cli's DRC on the vias a part's re-laid grid draws (docs/superpowers/specs/2026-10-01-carried-via-grids-design.md):
clear of the other face's pad where the grid as declared is not."""
import json
import shutil
import subprocess

import pytest

from tests.conftest import needs_kicad
from tests.test_carried_via_grids import AS_DRAWN, NO_LEAVE, SIZE, DRILL, TOP_ROW, _board, _drawn

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

_RULES = {"clearance", "hole_clearance", "hole_to_hole", "shorting_items"}


def _mm(v):
    return pcbnew.FromMM(v)


def _vec(x, y):
    return pcbnew.VECTOR2I(_mm(x), _mm(y))


def _violations(tmp_path, vias):
    """kicad-cli's clearance and hole violations of a board with U1's pad on the front, R9's on the back, and `vias`."""
    board = pcbnew.CreateEmptyBoard()
    gnd, sig = pcbnew.NETINFO_ITEM(board, "GND"), pcbnew.NETINFO_ITEM(board, "S")
    board.Add(gnd)
    board.Add(sig)

    def pad_fp(ref, net, layer, cx, cy, w, h):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(_vec(cx, cy))
        p = pcbnew.PAD(fp)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetSize(pcbnew.VECTOR2I(_mm(w), _mm(h)))
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        ls = pcbnew.LSET()
        ls.AddLayer(layer)
        p.SetLayerSet(ls)
        p.SetPosition(_vec(cx, cy))
        p.SetNumber("1")
        p.SetNet(net)
        fp.Add(p)
        board.Add(fp)
    pad_fp("U1", gnd, pcbnew.F_Cu, 20.0, 20.0, 2.4, 2.4)
    pad_fp("R9", sig, pcbnew.B_Cu, TOP_ROW[0], TOP_ROW[1], TOP_ROW[2], TOP_ROW[3])
    for x, y in vias:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(_vec(x, y))
        v.SetWidth(_mm(SIZE))
        v.SetDrill(_mm(DRILL))
        v.SetNet(gnd)
        board.Add(v)
    pcb = tmp_path / "board.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   check=True, capture_output=True)
    return [v for v in json.loads(report.read_text())["violations"] if v["type"] in _RULES]


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")
def test_kicad_finds_the_re_laid_grid_clear_of_the_other_faces_pad_and_the_declared_one_not(tmp_path):
    plan = _board([TOP_ROW], settings=NO_LEAVE).resolve()
    after = _drawn(plan)
    assert len(after) == 9 and after != AS_DRAWN
    assert _violations(tmp_path, after) == []
    assert _violations(tmp_path, AS_DRAWN) != []             # the control: the grid as declared meets the pad
