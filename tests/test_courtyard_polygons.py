"""A courtyard that is not a rectangle is claimed by the polygon KiCad
draws and tests, not the box round it."""
import dataclasses
import math

import pytest

from placemat.board_geometry import Footprint
from placemat.values import Box, Location
from tests.conftest import needs_breakout, needs_kicad


@needs_kicad
@needs_breakout
def test_a_triangular_courtyard_reads_back_as_its_triangle(breakout_pcb, tmp_path):
    import shutil
    import pcbnew
    from placemat.kicad.read import read_board
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    fp = next(f for f in brd.GetFootprints() if f.GetLayer() == pcbnew.F_Cu)
    ref = fp.GetReference()
    for d in list(fp.GraphicalItems()):
        if d.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            fp.Delete(d)
    bb = fp.GetBoundingBox(False, False)
    x0, y0, x1, y1 = bb.GetLeft() - pcbnew.FromMM(1), bb.GetTop() - pcbnew.FromMM(1), \
        bb.GetRight() + pcbnew.FromMM(4), bb.GetBottom() + pcbnew.FromMM(4)
    tri = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_POLY)
    tri.SetPolyPoints([pcbnew.VECTOR2I(x0, y0), pcbnew.VECTOR2I(x1, y0), pcbnew.VECTOR2I(x0, y1)])
    tri.SetLayer(pcbnew.F_CrtYd)
    tri.SetWidth(pcbnew.FromMM(0.05))
    fp.Add(tri)
    brd.Save(str(pcb))
    part = next(f for f in read_board(pcb).footprints if f.ref == ref)
    assert len(part.courtyard_poly) == 3
    xs, ys = [p[0] for p in part.courtyard_poly], [p[1] for p in part.courtyard_poly]
    assert min(xs) == pytest.approx(pcbnew.ToMM(x0), abs=0.05) and max(ys) == pytest.approx(pcbnew.ToMM(y1), abs=0.05)


@needs_kicad
@needs_breakout
def test_a_rectangular_courtyard_reads_back_as_a_rectangle(breakout):
    fp = next(f for f in breakout.footprints if f.courtyard_poly)
    assert len(fp.courtyard_poly) == 4
