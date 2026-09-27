"""A written board's model paths resolve from its own folder."""
import pytest

pytest.importorskip("pcbnew")

import shutil

from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def test_a_model_path_one_level_short_is_written_to_resolve(breakout_pcb, tmp_path):
    import pcbnew
    project = tmp_path / "a" / "b" / "layout"
    project.mkdir(parents=True)
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), project / ("layout" + ext))
    pcb = project / "layout.kicad_pcb"
    (tmp_path / "parts" / "p").mkdir(parents=True)
    (tmp_path / "parts" / "p" / "f.step").write_text("")
    brd = pcbnew.LoadBoard(str(pcb))
    fp = brd.GetFootprints()[0]
    ref = fp.GetReference()
    (tmp_path / "parts" / "p" / "g.step").write_text("")
    fp.Models().clear()
    for text in ("${KIPRJMOD}/../parts/p/f.step",                     # one level short of tmp_path
                 "kicad-embed://body.step",                           # KiCad's to find: left
                 "${KIPRJMOD}/../parts/p/g.step",
                 "${KIPRJMOD}/../parts/p/nowhere.step"):
        model = pcbnew.FP_3DMODEL()
        model.m_Filename = text
        fp.Models().push_back(model)
    brd.Save(str(pcb))
    g = read_board(pcb)
    b = Board(g, edge_margin=0.0)
    b.size(width=g.outline_box.width, height=g.outline_box.height, chamfer=2.0)
    plan = b.resolve()
    apply_plan(pcb, plan)
    written = {f.GetReference(): [m.m_Filename for m in f.Models()] for f in pcbnew.LoadBoard(str(pcb)).GetFootprints()}
    assert written[ref] == ["${KIPRJMOD}/../../../parts/p/f.step", "kicad-embed://body.step",
                            "${KIPRJMOD}/../../../parts/p/g.step", "${KIPRJMOD}/../parts/p/nowhere.step"]
    assert plan.models == {"reanchored": 2, "missing": ["nowhere.step"]}
