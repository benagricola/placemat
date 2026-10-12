"""The router can leave two vias of one net closer than the board's
hole-to-hole (its stub-swap and stub-layer-switch rescues). KiCad's
hole_to_hole check ignores nets, so the pair is a real DRC error. placemat's
post-route cleanup merges the router's via into its neighbour as KRT's own
merge_close_same_net_vias does (pcb_modification.py:6755-6880), when the
net's pads stay joined."""
import pytest

pytest.importorskip("pcbnew")

import json

from placemat.kicad.drc import run_drc
from placemat.kicad.route_cleanup import Cleanup, remove_dangling_router_copper
from tests.conftest import needs_kicad
from tests.test_route_dangling import _plain_board, _report, _save

pytestmark = needs_kicad


def _track(b, net, x0, y0, x1, y1, layer, w=0.2):
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(V(mm(x0), mm(y0)))
    t.SetEnd(V(mm(x1), mm(y1)))
    t.SetWidth(mm(w))
    t.SetLayer(layer)
    t.SetNet(net)
    b.Add(t)


def _via(b, net, x, y, locked=False):
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(V(mm(x), mm(y)))
    v.SetWidth(mm(0.45))
    v.SetDrill(mm(0.2))
    v.SetNet(net)
    v.SetLocked(locked)
    b.Add(v)


def _smd(b, back):
    """Every pad SMD with no hole, on F.Cu, or on B.Cu for the numbers in `back`."""
    import pcbnew
    for p in b.GetPads():
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetDrillSize(pcbnew.VECTOR2I(0, 0))
        if p.GetNumber() in back:
            layers = pcbnew.LSET()
            layers.AddLayer(pcbnew.B_Cu)
            p.SetLayerSet(layers)


def _pair_board(path, router, locked=False):
    """Net A from pad 1 (F.Cu, 45, 50) to pad 2 (B.Cu, 55, 50). The router
    drops two through vias 0.1 mm apart at (50, 50) and (50.1, 50), each with
    an F.Cu and a B.Cu track, as the stub rescues leave VSHUNT."""
    import pcbnew
    b, n = _plain_board(path, ("A",), (("1", (45, 50), "A"), ("2", (55, 50), "A")))
    _smd(b, ("2",))
    if router:
        a = n["A"]
        _track(b, a, 45, 50, 50, 50, pcbnew.F_Cu)
        _via(b, a, 50, 50, locked)
        _track(b, a, 50, 50, 50.1, 50, pcbnew.F_Cu)
        _track(b, a, 50, 50, 50.1, 50, pcbnew.B_Cu)
        _via(b, a, 50.1, 50, locked)
        _track(b, a, 50.1, 50, 55, 50, pcbnew.B_Cu)
    return _save(b, path)


def _vias(pcb):
    import pcbnew
    return sorted((round(t.GetPosition().x / 1e6, 3), round(t.GetPosition().y / 1e6, 3), t.GetNetname())
                  for t in pcbnew.LoadBoard(str(pcb)).GetTracks() if t.GetClass() == "PCB_VIA")


def _of(report, kind):
    return [v for v in json.loads(report.path.read_text())["violations"] if v["type"] == kind]


def test_a_routers_via_too_close_to_another_of_its_net_is_merged(tmp_path):
    given = _pair_board(tmp_path / "given.kicad_pcb", router=False)
    routed = _pair_board(tmp_path / "routed.kicad_pcb", router=True)
    before = run_drc(routed, tmp_path / "before.json")
    assert len(_of(before, "hole_to_hole")) == 1
    assert before.open_nets.get("A", 0) == 0

    result = remove_dangling_router_copper(str(routed), str(given))

    after = run_drc(routed, tmp_path / "after.json")
    assert _of(after, "hole_to_hole") == []
    assert after.open_nets.get("A", 0) == 0
    assert set(after.by_type) <= set(before.by_type) - {"hole_to_hole"}
    assert result.vias_merged == {"A": 1}
    assert result.vias_kept_close == []
    assert len(_vias(routed)) == 1
    import pcbnew
    assert not [t for t in pcbnew.LoadBoard(str(routed)).GetTracks()
                if t.GetClass() == "PCB_TRACK" and t.GetStart() == t.GetEnd()]


def test_a_locked_router_via_is_merged_but_a_given_pair_stays(tmp_path):
    """The island stages lock their router copper; that copper is still the
    router's, as in the dangling cleanup. Vias on the given board are never
    touched."""
    given = _pair_board(tmp_path / "given.kicad_pcb", router=False)
    routed = _pair_board(tmp_path / "routed.kicad_pcb", router=True, locked=True)
    assert remove_dangling_router_copper(str(routed), str(given)).vias_merged == {"A": 1}

    given = _pair_board(tmp_path / "given2.kicad_pcb", router=True, locked=True)
    routed = _pair_board(tmp_path / "routed2.kicad_pcb", router=True, locked=True)
    text = routed.read_text()
    result = remove_dangling_router_copper(str(routed), str(given))
    assert result.vias_merged == {} and result.vias_kept_close == []
    assert routed.read_text() == text


def test_a_merge_that_would_part_the_nets_pads_is_left_and_reported(tmp_path):
    """Each via is in a small F.Cu pad of its own (3 and 4) and joins it to
    a B.Cu track. Whichever via is dropped, moving its tracks onto the other
    leaves its pad on nothing."""
    import pcbnew

    def board(path, router):
        b, n = _plain_board(path, ("A",), (("1", (45, 50), "A"), ("2", (55, 50), "A"), ("3", (50, 50), "A"),
                                           ("4", (50.4, 50), "A")))
        _smd(b, ("1", "2"))
        from pcbnew import FromMM as mm, VECTOR2I as V
        for p in b.GetPads():
            if p.GetNumber() in ("3", "4"):
                p.SetSize(V(mm(0.3), mm(0.3)))
        if router:
            a = n["A"]
            _track(b, a, 45, 50, 50, 50, pcbnew.B_Cu)
            _via(b, a, 50, 50)
            _track(b, a, 50, 50, 50.4, 50, pcbnew.B_Cu)
            _via(b, a, 50.4, 50)
            _track(b, a, 50.4, 50, 55, 50, pcbnew.B_Cu)
        return _save(b, path)

    given, routed = board(tmp_path / "given.kicad_pcb", False), board(tmp_path / "routed.kicad_pcb", True)
    before = run_drc(routed, tmp_path / "before.json")
    assert len(_of(before, "hole_to_hole")) == 1 and before.open_nets.get("A", 0) == 0
    text = routed.read_text()
    result = remove_dangling_router_copper(str(routed), str(given))
    assert routed.read_text() == text
    assert result.vias_merged == {}
    assert len(result.vias_kept_close) == 1
    kept = result.vias_kept_close[0]
    assert kept["net"] == "A" and kept["reason"] == "parts_net"
    assert sorted([kept["at_mm"], kept["near_mm"]]) == [[50.0, 50.0], [50.4, 50.0]]
    assert kept["distance_mm"] == pytest.approx(0.4)


def test_the_console_line_and_the_record_carry_the_merged_and_kept_vias():
    assert "via" not in _report(Cleanup().record()).summary()
    kept = {"net": "INA_ALERT", "at_mm": [33.1, 12.8], "near_mm": [32.77, 12.85], "distance_mm": 0.334,
            "reason": "parts_net"}
    done = Cleanup(vias_merged={"VSHUNT": 1, "X": 2}, vias_kept_close=[kept]).record()
    assert done["vias_merged"] == {"VSHUNT": 1, "X": 2}
    assert done["vias_kept_close"] == [kept]
    line = _report(done).summary()
    assert "same-net vias within hole-to-hole merged: 3 via(s) on 2 net(s)" in line
    assert "same-net vias within hole-to-hole kept: INA_ALERT at (33.1, 12.8)" in line


def test_a_merge_that_would_bring_a_track_within_clearance_of_another_net_is_left(tmp_path):
    """Vias 0.4 mm apart, each with a track running north to its pad. Whichever
    via is dropped, its track swings over to the other via and passes within
    clearance of net B's track beside it on that layer, so the pair stays."""
    import pcbnew

    def board(path, router):
        b, n = _plain_board(path, ("A", "B"), (("1", (50, 53), "A"), ("2", (50.4, 53), "A")))
        _smd(b, ("2",))
        _track(b, n["B"], 49.85, 50.8, 49.85, 51.8, pcbnew.B_Cu)      # beside the B.Cu track's swing
        _track(b, n["B"], 50.55, 50.8, 50.55, 51.8, pcbnew.F_Cu)      # beside the F.Cu track's swing
        if router:
            a = n["A"]
            _track(b, a, 50, 53, 50, 50, pcbnew.F_Cu)
            _via(b, a, 50, 50)
            _track(b, a, 50, 50, 50.4, 50, pcbnew.B_Cu)
            _via(b, a, 50.4, 50)
            _track(b, a, 50.4, 50, 50.4, 53, pcbnew.B_Cu)
        return _save(b, path)

    given, routed = board(tmp_path / "given.kicad_pcb", False), board(tmp_path / "routed.kicad_pcb", True)
    before = run_drc(routed, tmp_path / "before.json")
    assert len(_of(before, "hole_to_hole")) == 1 and _of(before, "clearance") == []
    text = routed.read_text()
    result = remove_dangling_router_copper(str(routed), str(given))
    assert routed.read_text() == text
    assert result.vias_merged == {}
    assert len(result.vias_kept_close) == 1
    kept = result.vias_kept_close[0]
    assert kept["net"] == "A" and kept["reason"] == "clearance" and kept["other_net"] == "B"
    assert sorted([kept["at_mm"], kept["near_mm"]]) == [[50.0, 50.0], [50.4, 50.0]]


VIA_BLOCK = r"\t\(via\n.*?\n\t\)\n"


def _listed_first(pcb, at):
    """Rewrite `pcb` with its vias in file order, the one at `at` (x, y) first: pcbnew lists a board's tracks in the
    order of its file, as the router's uuids left it."""
    import re
    text = pcb.read_text()
    blocks = re.findall(VIA_BLOCK, text, flags=re.S)
    first = "(at %g %g)" % at
    ordered = sorted(blocks, key=lambda b: first not in b)
    pieces = iter(ordered)
    pcb.write_text(re.sub(VIA_BLOCK, lambda m: next(pieces), text, flags=re.S))
    return pcb


def _order(pcb):
    import pcbnew
    return [(round(t.GetPosition().x / 1e6, 3), round(t.GetPosition().y / 1e6, 3))
            for t in pcbnew.LoadBoard(str(pcb)).GetTracks() if t.GetClass() == "PCB_VIA"]


def _copper(pcb):
    import pcbnew
    return sorted((t.GetClass(), t.GetLayerName(), t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y)
                  for t in pcbnew.LoadBoard(str(pcb)).GetTracks())


def _routed_both_ways(tmp_path, board, a, b):
    """`board(path, router)` routed with the via at `a` listed first, and again with `b` first: [(Cleanup, path)]."""
    given = board(tmp_path / "given.kicad_pcb", False)
    out = []
    for name, first in (("a", a), ("b", b)):
        routed = _listed_first(board(tmp_path / ("routed_%s.kicad_pcb" % name), True), first)
        assert _order(routed)[0] == first
        out.append((remove_dangling_router_copper(str(routed), str(given)), routed))
    return out


def test_the_via_kept_is_the_same_whichever_the_board_lists_first(tmp_path):
    """The pair board's two vias carry three track ends each: the tie goes to the lower x, then y."""
    results = _routed_both_ways(tmp_path, lambda p, r: _pair_board(p, router=r), (50, 50), (50.1, 50))
    for result, routed in results:
        assert result.vias_merged == {"A": 1}
        assert _vias(routed) == [(50.0, 50.0, "A")]
    assert _copper(results[0][1]) == _copper(results[1][1])


def test_the_via_more_track_ends_land_on_is_kept(tmp_path):
    """Pad 1's F.Cu track and pad 2's B.Cu track both end on the via at (50.1, 50); the one at (50, 50) has only the
    short link between them. The lower x would keep (50, 50); the via with more ends is kept."""
    import pcbnew

    def board(path, router):
        b, n = _plain_board(path, ("A",), (("1", (45, 50), "A"), ("2", (55, 50), "A")))
        _smd(b, ("2",))
        if router:
            a = n["A"]
            _track(b, a, 45, 50, 50.1, 50, pcbnew.F_Cu)
            _via(b, a, 50.1, 50)
            _track(b, a, 50.1, 50, 55, 50, pcbnew.B_Cu)
            _via(b, a, 50, 50)
            _track(b, a, 50, 50, 50.1, 50, pcbnew.F_Cu)
        return _save(b, path)

    for result, routed in _routed_both_ways(tmp_path, board, (50, 50), (50.1, 50)):
        assert result.vias_merged == {"A": 1}
        assert _vias(routed) == [(50.1, 50.0, "A")]


@pytest.mark.parametrize("beside", ["B.Cu", "F.Cu"])
def test_a_merge_that_clashes_one_way_is_made_the_other_way(tmp_path, beside):
    """Vias 0.4 mm apart with two track ends each, as in the clearance case, but net B runs beside one swing only:
    on B.Cu, dropping (50.4, 50) swings pad 2's track into it, so (50, 50) is dropped instead; on F.Cu, dropping
    (50, 50) swings pad 1's track into it, so (50.4, 50) is dropped. Either way the pair is merged, whichever via
    the board lists first."""
    import pcbnew

    def board(path, router):
        b, n = _plain_board(path, ("A", "B"), (("1", (50, 53), "A"), ("2", (50.4, 53), "A")))
        _smd(b, ("2",))
        if beside == "B.Cu":
            _track(b, n["B"], 49.85, 50.8, 49.85, 51.8, pcbnew.B_Cu)
        else:
            _track(b, n["B"], 50.55, 50.8, 50.55, 51.8, pcbnew.F_Cu)
        if router:
            a = n["A"]
            _track(b, a, 50, 53, 50, 50, pcbnew.F_Cu)
            _via(b, a, 50, 50)
            _track(b, a, 50, 50, 50.4, 50, pcbnew.B_Cu)
            _via(b, a, 50.4, 50)
            _track(b, a, 50.4, 50, 50.4, 53, pcbnew.B_Cu)
        return _save(b, path)

    kept = (50.4, 50.0, "A") if beside == "B.Cu" else (50.0, 50.0, "A")
    for result, routed in _routed_both_ways(tmp_path, board, (50, 50), (50.4, 50)):
        assert result.vias_merged == {"A": 1}
        assert result.vias_kept_close == []
        assert _vias(routed) == [kept]
        after = run_drc(routed, tmp_path / "after.json")
        assert _of(after, "clearance") == [] and _of(after, "hole_to_hole") == []
