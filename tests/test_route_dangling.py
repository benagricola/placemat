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
    tail wholly inside the polygon, a short piece lying on the body of its
    own track from pad 3, a three-piece spur off pad 1 that ends in nothing, and a
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
        _track(b, na, 50, 56, 50.04, 56)                  # on the body of the router's track from pad 3
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
    assert result.refused_nets == []
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
    done = Cleanup({"protect.VPROT": 20, "VPROT_IN": 9}, {"UART_RX": 1}, {}, (15, 15)).record()
    report = _report(done)
    assert "dangling router copper removed: 29 track(s), 1 via(s) on 3 net(s)" in report.summary()
    assert report.as_dict()["dangling_removed"]["tracks"] == {"protect.VPROT": 20, "VPROT_IN": 9}
    path = route_progress.write_record(tmp_path, {}, [], report.as_dict(), complete=True)
    assert json.loads(path.read_text())["report"]["dangling_removed"]["vias"] == {"UART_RX": 1}
    kept = _report(Cleanup({"A": 2}, {}, {}, (3, 3), [], ["Y"]).record())
    assert "dangling router copper kept on 1 net(s) whose pads it alone joins: Y" in kept.summary()


def test_the_routers_partial_copper_on_a_net_it_left_unrouted_stays(tmp_path):
    """The router keeps the copper of a net it failed (KRT cleanup_pipeline.py,
    protected nets, #473): progress a later route builds on. A net still
    unconnected in the routed copy keeps its dangling router copper, and the
    record names it."""
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V
    given = _board(tmp_path / "given.kicad_pcb", router=False)
    routed = _board(tmp_path / "routed.kicad_pcb", router=True)
    for path, partial in ((given, False), (routed, True)):
        b = pcbnew.LoadBoard(str(path))
        nc = pcbnew.NETINFO_ITEM(b, "C")
        b.Add(nc)
        fp = b.GetFootprints()[0]
        for num, x in (("5", 50), ("6", 66)):
            pad = pcbnew.PAD(fp)
            pad.SetSize(V(mm(1), mm(1)))
            pad.SetPosition(V(mm(x), mm(59)))
            pad.SetLayerSet(pad.SMDMask())
            pad.SetNet(nc)
            pad.SetNumber(num)
            fp.Add(pad)
        if partial:
            _track(b, nc, 50, 59, 53, 59)                 # the router's start on C, ending in nothing
            _track(b, nc, 53, 59, 54, 58)
        b.Save(str(path))
    result = remove_dangling_router_copper(str(routed), str(given))
    assert result.tracks == {"A": 5}
    assert result.kept_unrouted == ["C"]
    left = _router_tracks(routed)
    assert (50.0, 59.0, 53.0, 59.0, "C", False) in left and (53.0, 59.0, 54.0, 58.0, "C", False) in left
    assert "dangling router copper kept on 1 unrouted net(s): C" in _report(result.record()).summary()


def _plain_board(path, nets, pads):
    """An empty board with `nets` and a footprint U1 carrying `pads`
    [(number, (x, y), net)], inside a 30 x 22 mm outline."""
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V
    b = pcbnew.CreateEmptyBoard()
    infos = {}
    for n in nets:
        infos[n] = pcbnew.NETINFO_ITEM(b, n)
        b.Add(infos[n])
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("U1")
    fp.SetPosition(V(mm(50), mm(50)))
    for num, (x, y), net in pads:
        pad = pcbnew.PAD(fp)
        pad.SetSize(V(mm(1), mm(1)))
        pad.SetPosition(V(mm(x), mm(y)))
        pad.SetLayerSet(pad.SMDMask())
        pad.SetNet(infos[net])
        pad.SetNumber(num)
        fp.Add(pad)
    b.Add(fp)
    for x0, y0, x1, y1 in ((40, 40, 70, 40), (70, 40, 70, 62), (70, 62, 40, 62), (40, 62, 40, 40)):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(mm(x0), mm(y0)))
        s.SetEnd(V(mm(x1), mm(y1)))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        b.Add(s)
    return b, infos


def _save(b, path):
    b.Save(str(path))
    path.with_suffix(".kicad_pro").write_text("{}")
    return path


def _xy_board(path, router):
    """The reviewer's case. Net Y: pad 1's track runs on past the joint and
    ends in nothing, and pad 2's track lands on its body - KiCad calls the
    first dangling, yet removing it parts Y's pads. Net X: its pads joined,
    and a floating router fragment."""
    b, n = _plain_board(path, ("X", "Y"), (("1", (45, 50), "Y"), ("2", (55, 45), "Y"),
                                           ("3", (45, 56), "X"), ("4", (55, 56), "X")))
    if router:
        _track(b, n["Y"], 45, 50, 60, 50)
        _track(b, n["Y"], 55, 50, 55, 45)
        _track(b, n["X"], 45, 56, 55, 56)
        _track(b, n["X"], 60, 58, 62, 58)
    return _save(b, path)


def test_a_net_whose_pads_the_dangling_copper_joins_keeps_it_and_another_net_is_cleaned(tmp_path):
    given = _xy_board(tmp_path / "given.kicad_pcb", False)
    routed = _xy_board(tmp_path / "routed.kicad_pcb", True)
    before = run_drc(routed, tmp_path / "before.json")
    assert _dangling(before, "Y") and _dangling(before, "X")
    result = remove_dangling_router_copper(str(routed), str(given))
    after = run_drc(routed, tmp_path / "after.json")
    assert result.refused_nets == ["Y"]
    assert result.tracks == {"X": 1}
    assert _dangling(after, "X") == []
    assert after.open_nets.get("Y", 0) == before.open_nets.get("Y", 0) == 0
    assert after.unconnected <= before.unconnected
    left = _router_tracks(routed)
    assert (45.0, 50.0, 60.0, 50.0, "Y", False) in left and (55.0, 50.0, 55.0, 45.0, "Y", False) in left
    assert (60.0, 58.0, 62.0, 58.0, "X", False) not in left


def test_a_dangling_router_via_is_deleted(tmp_path):
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V

    def board(path, router):
        b, n = _plain_board(path, ("A",), (("1", (45, 50), "A"), ("2", (55, 50), "A")))
        _track(b, n["A"], 45, 50, 55, 50, locked=True)
        if router:
            _track(b, n["A"], 50, 50, 50, 54)             # off the body, to a via joined on F.Cu only
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(V(mm(50), mm(54)))
            v.SetWidth(mm(0.6))
            v.SetDrill(mm(0.3))
            v.SetNet(n["A"])
            b.Add(v)
        return _save(b, path)

    given, routed = board(tmp_path / "given.kicad_pcb", False), board(tmp_path / "routed.kicad_pcb", True)
    before = run_drc(routed, tmp_path / "before.json")
    assert _dangling(before, "A")
    result = remove_dangling_router_copper(str(routed), str(given))
    after = run_drc(routed, tmp_path / "after.json")
    assert result.vias == {"A": 1} and result.tracks == {"A": 1}
    assert _dangling(after, "A") == [] and after.unconnected == before.unconnected
    assert not [t for t in pcbnew.LoadBoard(str(routed)).GetTracks() if t.GetClass() == "PCB_VIA"]


def test_a_t_junction_on_a_track_body_is_kept(tmp_path):
    def board(path, router):
        b, n = _plain_board(path, ("A",), (("1", (45, 50), "A"), ("2", (60, 50), "A"), ("3", (52, 56), "A")))
        if router:
            _track(b, n["A"], 45, 50, 60, 50)
            _track(b, n["A"], 52, 50, 52, 56)             # from the trunk's body down to pad 3
        return _save(b, path)

    given, routed = board(tmp_path / "given.kicad_pcb", False), board(tmp_path / "routed.kicad_pcb", True)
    text = routed.read_text()
    result = remove_dangling_router_copper(str(routed), str(given))
    assert result.tracks == {} and result.vias == {} and result.refused_nets == []
    assert routed.read_text() == text
    assert _dangling(run_drc(routed, tmp_path / "after.json"), "A") == []


def test_a_given_escape_stub_the_router_rewrote_is_kept(tmp_path):
    """The router may write a given track again: split in pieces with new
    uuids, or with its own uuid and a moved end. Either way it is the
    script's copper and stays, dangling or not."""
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V

    def board(path, router):
        b, n = _plain_board(path, ("A", "B"), (("1", (45, 50), "A"), ("2", (55, 50), "A"), ("4", (45, 44), "B"),
                                               ("5", (55, 56), "B")))
        _track(b, n["A"], 45, 50, 55, 50, locked=True)
        if not router:
            _track(b, n["B"], 45, 44, 47, 44, locked=True)    # escape stubs, pad 4's and pad 5's
            _track(b, n["B"], 55, 56, 53, 56, locked=True)
        else:
            _track(b, n["B"], 45, 44, 46, 44)                 # the first written again in two pieces
            _track(b, n["B"], 46, 44, 47, 44)
            _track(b, n["B"], 55, 56, 52.5, 56)               # the second with a moved end ...
        return _save(b, path)

    given, routed = board(tmp_path / "given.kicad_pcb", False), board(tmp_path / "routed.kicad_pcb", True)
    uuid = lambda path: [t.m_Uuid.AsString() for t in pcbnew.LoadBoard(str(path)).GetTracks()
                         if t.GetNetname() == "B" and t.GetStart().x == mm(55)][0]
    routed.write_text(routed.read_text().replace(uuid(routed), uuid(given)))     # ... and its own uuid
    before = run_drc(routed, tmp_path / "before.json")
    assert len(_dangling(before, "B")) >= 2
    result = remove_dangling_router_copper(str(routed), str(given))
    assert result.tracks == {} and result.vias == {}
    left = _router_tracks(routed)
    assert (45.0, 44.0, 46.0, 44.0, "B", False) in left and (46.0, 44.0, 47.0, 44.0, "B", False) in left
    assert (55.0, 56.0, 52.5, 56.0, "B", False) in left
