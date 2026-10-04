"""A track wholly inside a net-less filled footprint polygon. KiCad reports it
as a clearance violation. The router's own checker (KRT check_drc.py) does not:
it adds every net that touches a footprint graphic to the graphic's effective
nets (`_build_graphic_unification`, include_mutable), and
`_graphic_pair_is_same_net` (check_drc.py:1153) then waives the pair, so a
foreign track inside the fill is judged to be on the fill's net. placemat does
not use that checker: the board's DRC is kicad-cli's, and the router is kept
off the polygon by a rule area."""
import pytest

pytest.importorskip("pcbnew")

from placemat.kicad.drc import run_drc
from placemat.kicad.route import guard_footprint_copper, router_breaches
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def _board(path, with_track: bool):
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V
    b = pcbnew.CreateEmptyBoard()
    na, nb = pcbnew.NETINFO_ITEM(b, "A"), pcbnew.NETINFO_ITEM(b, "B")
    b.Add(na)
    b.Add(nb)
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("U1")
    fp.SetPosition(V(mm(50), mm(50)))
    pad = pcbnew.PAD(fp)
    pad.SetSize(V(mm(1), mm(1)))
    pad.SetPosition(V(mm(50), mm(50)))
    pad.SetLayerSet(pad.SMDMask())
    pad.SetNet(na)
    pad.SetNumber("1")
    fp.Add(pad)
    poly = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_POLY)
    poly.SetPolyPoints([V(mm(x), mm(y)) for x, y in ((50, 50), (60, 50), (60, 60), (50, 60))])
    poly.SetFilled(True)
    poly.SetWidth(mm(0.1))
    poly.SetLayer(pcbnew.F_Cu)
    fp.Add(poly)
    b.Add(fp)
    for x0, y0, x1, y1 in ((40, 40, 70, 40), (70, 40, 70, 70), (70, 70, 40, 70), (40, 70, 40, 40)):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(mm(x0), mm(y0)))
        s.SetEnd(V(mm(x1), mm(y1)))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        b.Add(s)
    if with_track:
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(V(mm(53), mm(55)))
        t.SetEnd(V(mm(57), mm(55)))
        t.SetWidth(mm(0.2))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(nb)
        b.Add(t)
    b.Save(str(path))
    return path


def _with_project(tmp_path, name, with_track):
    pcb = _board(tmp_path / (name + ".kicad_pcb"), with_track)
    (tmp_path / (name + ".kicad_pro")).write_text("{}")
    return pcb


def test_the_boards_drc_reports_a_track_inside_a_filled_footprint_polygon(tmp_path):
    with_track = run_drc(_with_project(tmp_path, "inside", True), tmp_path / "a.json")
    without = run_drc(_with_project(tmp_path, "free", False), tmp_path / "b.json")
    assert with_track.by_type.get("clearance", 0) == without.by_type.get("clearance", 0) + 1
    assert "clearance" in with_track.real


def test_a_track_the_router_lays_inside_the_polygon_is_a_breach(tmp_path):
    given = _with_project(tmp_path, "given", False)
    routed = _with_project(tmp_path, "routed", True)
    assert guard_footprint_copper(str(given)) == 1
    (breach,) = router_breaches(given, routed)
    assert "track of B" in breach and "footprint copper U1" in breach
