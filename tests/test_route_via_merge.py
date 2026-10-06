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
