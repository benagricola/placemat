"""The router leaves short tails KiCad reports as track_dangling: a segment
whose ends both land on one other item of its net (the net's filled copper
polygon, or the body of another track) and nothing else. KiCad counts such
an item once (connectivity_data.cpp TestTrackEndpointDangling, "short
segments which can be connected to the *same* other item on each end"), so
the segment is dangling. placemat removes the router's dangling copper from
the routed copy as KiCad's TRACKS_CLEANER does, and leaves the copper it was
given alone."""
import pytest

pytest.importorskip("pcbnew")

import json

from placemat.kicad.drc import run_drc
from placemat.kicad.route_cleanup import remove_dangling_router_copper
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def _track(b, net, x0, y0, x1, y1, w=0.2, locked=False):
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(V(mm(x0), mm(y0)))
    t.SetEnd(V(mm(x1), mm(y1)))
    t.SetWidth(mm(w))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(net)
    t.SetLocked(locked)
    b.Add(t)
    return t


def _board(path, router: bool):
    """Net A: pad 1 at (45, 50), pad 2 at (62, 50) inside a filled F.Cu
    polygon of A, and a declared track from pad 1 into the polygon. Net B: a
    declared escape stub that dangles. With `router`, the router's copper: a
    tail wholly inside the polygon, a short piece lying on the body of the
    declared track, a three-piece spur off pad 1 that ends in nothing, and a
    track joining pad 3 to the polygon, which stays."""
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V
    b = pcbnew.CreateEmptyBoard()
    na, nb = pcbnew.NETINFO_ITEM(b, "A"), pcbnew.NETINFO_ITEM(b, "B")
    b.Add(na)
    b.Add(nb)
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("U1")
    fp.SetPosition(V(mm(50), mm(50)))
    for num, (x, y), net in (("1", (45, 50), na), ("2", (62, 50), na), ("3", (45, 56), na), ("4", (45, 44), nb)):
        pad = pcbnew.PAD(fp)
        pad.SetSize(V(mm(1), mm(1)))
        pad.SetPosition(V(mm(x), mm(y)))
        pad.SetLayerSet(pad.SMDMask())
        pad.SetNet(net)
        pad.SetNumber(num)
        fp.Add(pad)
    b.Add(fp)
    poly = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_POLY)
    poly.SetPolyPoints([V(mm(x), mm(y)) for x, y in ((55, 45), (65, 45), (65, 55), (55, 55))])
    poly.SetFilled(True)
    poly.SetWidth(mm(0.1))
    poly.SetLayer(pcbnew.F_Cu)
    poly.SetNet(na)
    b.Add(poly)
    for x0, y0, x1, y1 in ((40, 40, 70, 40), (70, 40, 70, 62), (70, 62, 40, 62), (40, 62, 40, 40)):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(mm(x0), mm(y0)))
        s.SetEnd(V(mm(x1), mm(y1)))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        b.Add(s)
    _track(b, na, 45, 50, 57, 50, locked=True)           # declared: pad 1 into the polygon
    _track(b, nb, 45, 44, 47, 44, locked=True)           # declared: an escape stub, dangling
    if router:
        _track(b, na, 58, 52, 58.05, 52.03)               # wholly inside the polygon
        _track(b, na, 50, 50, 50.04, 50)                  # on the declared track's body
        _track(b, na, 45, 50, 45, 48)                     # a spur off pad 1, ending in nothing
        _track(b, na, 45, 48, 46, 47)
        _track(b, na, 46, 47, 48, 47)
        _track(b, na, 45, 56, 56, 56)                     # pad 3 ...
        _track(b, na, 56, 56, 56, 54)                     # ... into the polygon
    b.Save(str(path))
    path.with_suffix(".kicad_pro").write_text("{}")
    return path


def _router_tracks(pcb):
    import pcbnew
    return sorted((round(t.GetStart().x / 1e6, 3), round(t.GetStart().y / 1e6, 3),
                   round(t.GetEnd().x / 1e6, 3), round(t.GetEnd().y / 1e6, 3), t.GetNetname(), t.IsLocked())
                  for t in pcbnew.LoadBoard(str(pcb)).GetTracks())


def _dangling(report, net):
    doc = json.loads(report.path.read_text())
    return [v for v in doc["violations"] if v["type"] in ("track_dangling", "via_dangling")
            and any("[%s]" % net in i["description"] for i in v["items"])]


def test_the_routers_dangling_tails_are_removed_and_the_given_copper_stays(tmp_path):
    given = _board(tmp_path / "given.kicad_pcb", router=False)
    routed = _board(tmp_path / "routed.kicad_pcb", router=True)
    before = run_drc(routed, tmp_path / "before.json")
    assert len(_dangling(before, "A")) >= 3               # the tails, as KiCad reports them
    assert len(_dangling(before, "B")) == 1

    result = remove_dangling_router_copper(str(routed), str(given))

    after = run_drc(routed, tmp_path / "after.json")
    assert _dangling(after, "A") == []
    assert len(_dangling(after, "B")) == 1                # the declared escape stub is not the router's
    assert after.unconnected == before.unconnected
    assert result.tracks == {"A": 5}
    assert result.vias == {}
    assert not result.refused
    left = _router_tracks(routed)
    assert (45.0, 50.0, 57.0, 50.0, "A", True) in left    # declared copper as given
    assert (45.0, 44.0, 47.0, 44.0, "B", True) in left
    assert (45.0, 56.0, 56.0, 56.0, "A", False) in left   # the router's track joining pad 3 to the polygon
    assert len(left) == 4


def test_a_board_with_no_router_copper_is_left_as_it_was(tmp_path):
    given = _board(tmp_path / "given.kicad_pcb", router=False)
    routed = _board(tmp_path / "routed.kicad_pcb", router=False)
    text = routed.read_text()
    result = remove_dangling_router_copper(str(routed), str(given))
    assert result.tracks == {} and result.vias == {} and result.merged == {}
    assert routed.read_text() == text


def test_the_routers_collinear_pieces_are_merged_once_a_tail_is_gone(tmp_path):
    """KiCad merges collinear tracks after it deletes dangling ones
    (TRACKS_CLEANER::CleanupBoard): two router pieces meeting where a tail
    branched off join into one track."""
    given = _board(tmp_path / "given.kicad_pcb", router=False)
    routed = _board(tmp_path / "routed.kicad_pcb", router=False)
    import pcbnew
    b = pcbnew.LoadBoard(str(routed))
    na = b.FindNet("A")
    _track(b, na, 45, 56, 50, 56)                         # pad 3 ...
    _track(b, na, 50, 56, 56, 56)                         # ... collinear ...
    _track(b, na, 56, 56, 56, 54)                         # ... into the polygon
    _track(b, na, 50, 56, 50, 58)                         # a tail off the joint
    b.Save(str(routed))
    result = remove_dangling_router_copper(str(routed), str(given))
    assert result.tracks == {"A": 1}
    assert result.merged == {"A": 1}
    assert (45.0, 56.0, 56.0, 56.0, "A", False) in _router_tracks(routed)


def _report(dangling):
    from pathlib import Path
    from placemat.kicad.route import RouteReport
    return RouteReport(True, 0.8, 0.8, 10, 2, {}, [], [], ["F.Cu"], 1.0, "v", {}, Path("r.kicad_pcb"), Path("r.log"),
                       Path("."), dangling_removed=dangling)


def test_the_console_line_and_the_report_carry_what_was_removed(tmp_path):
    from placemat import route_progress
    from placemat.kicad.route_cleanup import Cleanup
    assert "dangling" not in _report(Cleanup().record()).summary()
    done = Cleanup({"protect.VPROT": 20, "VPROT_IN": 9}, {"UART_RX": 1}, {}, False, (15, 15)).record()
    report = _report(done)
    assert "dangling router copper removed: 29 track(s), 1 via(s) on 3 net(s)" in report.summary()
    assert report.as_dict()["dangling_removed"]["tracks"] == {"protect.VPROT": 20, "VPROT_IN": 9}
    path = route_progress.write_record(tmp_path, {}, [], report.as_dict(), complete=True)
    assert json.loads(path.read_text())["report"]["dangling_removed"]["vias"] == {"UART_RX": 1}
    kept = _report(Cleanup({"A": 2}, {}, {}, True, (3, 4)).record())
    assert "2 dangling router track(s) and 0 via(s) kept: removing them took unconnected 3 -> 4" in kept.summary()


def test_a_removal_that_would_open_a_connection_is_refused(tmp_path, monkeypatch):
    from placemat.kicad import route_cleanup
    given = _board(tmp_path / "given.kicad_pcb", router=False)
    routed = _board(tmp_path / "routed.kicad_pcb", router=True)
    text = routed.read_text()
    counts = iter([3, 4])
    monkeypatch.setattr(route_cleanup, "_unconnected", lambda board: next(counts))
    result = remove_dangling_router_copper(str(routed), str(given))
    assert result.refused and result.unconnected == (3, 4) and result.tracks == {"A": 5}
    assert routed.read_text() == text
