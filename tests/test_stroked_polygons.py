"""A filled copper polygon's stroke is read as KiCad's DRC tests it: round
at the corners. Read with cut corners it came 0.04 mm short at each, and a
via passed 0.1269 mm from a pour against a 0.16 rule."""
import math
import shutil

import pytest

pytest.importorskip("pcbnew")

from placemat.geometry import point_in_polygon
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def test_a_stroked_polygons_corner_is_read_round(breakout_pcb, tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    sh = pcbnew.PCB_SHAPE(brd, pcbnew.SHAPE_T_POLY)
    corners = [(200.0, 200.0), (203.0, 200.0), (203.0, 202.0), (200.0, 202.0)]      # off the board: nothing near
    sh.SetPolyPoints([pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)) for x, y in corners])
    sh.SetFilled(True)
    sh.SetWidth(pcbnew.FromMM(0.3))
    sh.SetLayer(pcbnew.B_Cu)
    sh.SetNet(brd.FindNet("GND"))
    brd.Add(sh)
    brd.Save(str(pcb))
    (poly,) = [c for c in read_board(pcb).copper if c.kind == "poly" and c.box.left > 190]
    d = 0.13 / math.sqrt(2)                     # 0.13 mm off the corner along its diagonal: inside the round stroke
    assert any(point_in_polygon((203.0 + d, 202.0 + d), o) for o in poly.outlines)
    assert not any(point_in_polygon((203.0 + 0.11, 202.0 + 0.11), o) for o in poly.outlines)   # 0.156 off: outside


def test_every_edge_of_a_self_crossing_polygon_is_stroked(breakout_pcb, tmp_path):
    """A pour whose outline doubles back on itself (a board's, 2026-09-27):
    the stroke along its bottom edge was lost, and a via passed 0.127 mm from
    it."""
    import pcbnew
    from placemat.kicad.read import read_board
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    pts = [(222.076, 226.634), (222.076, 228.255), (222.892, 228.255), (223.192, 228.212), (222.033, 228.212),
           (222.033, 226.634)]
    sh = pcbnew.PCB_SHAPE(brd, pcbnew.SHAPE_T_POLY)
    sh.SetPolyPoints([pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)) for x, y in pts])
    sh.SetFilled(True)
    sh.SetWidth(pcbnew.FromMM(0.3))
    sh.SetLayer(pcbnew.B_Cu)
    sh.SetNet(brd.FindNet("GND"))
    brd.Add(sh)
    brd.Save(str(pcb))
    (poly,) = [c for c in read_board(pcb).copper if c.kind == "poly" and c.box.left > 190]
    assert any(point_in_polygon((222.5, 228.255 + 0.14), o) for o in poly.outlines)     # under the bottom edge
    assert any(point_in_polygon((223.192 + 0.14, 228.212), o) for o in poly.outlines)   # past the far vertex
    assert 223.342 - 1e-6 <= poly.box.right < 223.35       # the round end drawn just outside its circle
