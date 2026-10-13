"""Rip and reroute on real boards (pcbnew), no router."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from placemat.kicad import rip_reroute as rr
from placemat.kicad.route import copper_items
from tests.conftest import needs_kicad
from tests.rip_helpers import TOY, rip_board, toy_router
from tests.test_net_clearance import _two_part_board


def _add_track(pcb, net, a, b, width=0.2, layer="F.Cu"):
    text = pcb.read_text()
    nid = {"SW": 1, "FB": 2, "VIN": 3}[net]
    seg = '\t(segment (start %g %g) (end %g %g) (width %g) (layer "%s") (net %d))\n' % (*a, *b, width, layer, nid)
    pcb.write_text(text.replace("\t(gr_rect", seg + "\t(gr_rect", 1))


@needs_kicad
def test_router_copper_is_what_the_input_board_lacks(tmp_path):
    pytest.importorskip("pcbnew")
    given = _two_part_board(tmp_path)
    script = frozenset(copper_items(given))
    routed = tmp_path / "routed.kicad_pcb"
    shutil.copy(given, routed)
    _add_track(routed, "FB", (110, 110), (125, 110))
    assert rr.router_nets(routed, script) == {"FB": 1}
    assert rr.laid_nets(given, routed) == {"FB"}


@needs_kicad
def test_removing_a_victim_takes_its_router_copper_and_leaves_script_copper_and_other_nets(tmp_path):
    pytest.importorskip("pcbnew")
    given = _two_part_board(tmp_path)
    _add_track(given, "FB", (110, 110), (112, 110))          # script copper on the victim
    script = frozenset(copper_items(given))
    routed = tmp_path / "routed.kicad_pcb"
    shutil.copy(given, routed)
    _add_track(routed, "FB", (112, 110), (125, 110))         # router copper on the victim
    _add_track(routed, "VIN", (113, 110), (113, 115))        # router copper on another net
    out = tmp_path / "ripped.kicad_pcb"
    got = rr.remove_copper(routed, out, {"FB"}, script)
    assert got == {"tracks": 1, "arcs": 0, "vias": 0, "track_mm": 13.0}
    left = {(k[1], k[3]) for k in copper_items(out)}
    assert ("FB", (110.0, 110.0, 112.0, 110.0)) in left and ("VIN", (113.0, 110.0, 113.0, 115.0)) in left
    assert not any(n == "FB" and e == (112.0, 110.0, 125.0, 110.0) for n, e in left)
    assert out.with_suffix(".kicad_pro").exists()
    assert copper_items(routed) - copper_items(out)        # the source board is not written


@needs_kicad
def test_a_pair_is_first_joined_on_the_first_board_whose_copper_joins_it(tmp_path):
    pytest.importorskip("pcbnew")
    boards = []
    for i in range(3):
        d = tmp_path / ("b%d" % i)
        d.mkdir()
        b = _two_part_board(d)
        if i:
            _add_track(b, "FB", (110, 110), (125, 110))
        boards.append(b)
    assert rr.first_joined([(("U1", "2"), ("J1", "1"))], boards) == [1]
    assert rr.first_joined([(("U1", "2"), ("J1", "1"))], boards[:1]) == [None]


def _toy(krt, board, out, *args):
    """Run the stand-in router on `board`, writing `out`; returns its summary."""
    summary = out.with_suffix(".json")
    env = dict(os.environ, FAKE_ROUTER_LOG=str(out.parent / "router.log"))
    subprocess.run([sys.executable, krt / "py_router/route.py", board, out, *args, "--json-out", summary],
                   env=env, check=True)
    return json.loads(summary.read_text())


def _segments(pcb):
    return sorted((k[1], k[3]) for k in copper_items(pcb) if k[0] == "segment")


@needs_kicad
def test_the_stand_in_router_lays_straight_names_its_blockers_and_detours(tmp_path):
    pytest.importorskip("pcbnew")
    krt = toy_router(tmp_path)
    assert (krt / "py_router/route.py").read_text() == TOY
    board = rip_board(tmp_path)
    a_laid = tmp_path / "a.kicad_pcb"
    _toy(krt, board, a_laid, "--nets", "A", "--layers", "F.Cu")
    assert _segments(a_laid) == [("A", (105.0, 110.0, 125.0, 110.0))]

    b_laid = tmp_path / "b.kicad_pcb"
    doc = _toy(krt, a_laid, b_laid, "--nets", "B", "--layers", "F.Cu")
    assert _segments(b_laid) == _segments(a_laid)
    assert doc["blockers"] == [{"net": "B", "stage": "preexisting", "blocked_by": [{"net": "A", "preexisting": True}]}]

    b_only = tmp_path / "b_only.kicad_pcb"
    _toy(krt, board, b_only, "--nets", "B", "--layers", "F.Cu")
    assert _segments(b_only) == [("B", (115.0, 104.0, 115.0, 116.0))]
    conns = tmp_path / "conns.json"
    conns.write_text(json.dumps([{"net": "A", "from": {"ref": "P1", "pad": "1"}, "to": {"ref": "P2", "pad": "1"},
                                  "widths": {"F.Cu": 0.2}, "amps": None}]))
    detoured = tmp_path / "detoured.kicad_pcb"
    doc = _toy(krt, b_only, detoured, "--connections", conns, "--layers", "F.Cu")
    a = [e for n, e in _segments(detoured) if n == "A"]
    assert len(a) == 3 and [e for e in a if e[1] == e[3] == 118.0] == [(105.0, 118.0, 125.0, 118.0)]
    assert [(r["net"], r["status"], r["joined"]) for r in doc["connections"]] == [("A", "routed", True)]


@needs_kicad
def test_a_track_blocks_b_and_c_every_way_on_the_rip_board(tmp_path):
    pytest.importorskip("pcbnew")
    krt = toy_router(tmp_path)
    board = rip_board(tmp_path, a_track=True, c_net=True)
    out = tmp_path / "out.kicad_pcb"
    doc = _toy(krt, board, out, "--nets", "*", "!A", "--layers", "F.Cu")
    assert _segments(out) == [("A", (105.0, 110.0, 125.0, 110.0))]
    assert doc["blockers"] == [{"net": n, "stage": "preexisting", "blocked_by": [{"net": "A", "preexisting": True}]}
                               for n in ("B", "C")]


def _add_copper(pcb, sexprs):
    pcb.write_text(pcb.read_text().replace("\t(gr_rect", "".join("\t%s\n" % s for s in sexprs) + "\t(gr_rect", 1))


@needs_kicad
def test_off_layer_counts_the_added_tracks_and_arcs_off_the_layers_and_never_a_via(tmp_path):
    pytest.importorskip("pcbnew")
    given = _two_part_board(tmp_path)
    routed = tmp_path / "routed.kicad_pcb"
    shutil.copy(given, routed)
    _add_copper(routed, ['(segment (start 112 115) (end 120 115) (width 0.2) (layer "B.Cu") (net 2))',
                         '(arc (start 128 104) (mid 129 105) (end 128 106) (width 0.2) (layer "B.Cu") (net 2))',
                         '(segment (start 112 117) (end 120 117) (width 0.2) (layer "F.Cu") (net 2))',
                         '(via (at 122 115) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 2))'])
    assert rr.off_layer(given, routed, ["F.Cu"]) == 2
    assert rr.off_layer(given, routed, ["F.Cu", "B.Cu"]) == 0
    assert rr.off_layer(given, given, ["F.Cu"]) == 0


def _standing_board(d, stub):
    """_two_part_board with VIN joined (U1.3 to J1.2) and FB left open; `stub` adds a VIN stub too near SW's track (a
    clearance error, a real kind). A via on VIN below KiCad's minimum size and drill gives two errors of kinds that are
    not real."""
    d.mkdir()
    pcb = _two_part_board(d)
    _add_copper(pcb, ['(segment (start 113 110) (end 113 108) (width 0.2) (layer "F.Cu") (net 3))',
                      '(segment (start 113 108) (end 126 108) (width 0.2) (layer "F.Cu") (net 3))',
                      '(segment (start 126 108) (end 126 110) (width 0.2) (layer "F.Cu") (net 3))',
                      '(via (at 120 108) (size 0.3) (drill 0.1) (layers "F.Cu" "B.Cu") (net 3))']
                + (['(segment (start 113 108) (end 109.35 108) (width 0.2) (layer "F.Cu") (net 3))'] if stub else []))
    return pcb


@needs_kicad
def test_a_standing_reads_its_boards_drc_and_judges_each_phase_against_its_own_input(tmp_path):
    import types
    from placemat.kicad.drc import run_drc
    pytest.importorskip("pcbnew")
    work = tmp_path / "work"
    work.mkdir()
    run_drc(_standing_board(tmp_path / "clean", False), work / "drc_before.json", refill_zones=False)
    run_drc(_standing_board(tmp_path / "short", True), work / "p0_drc.json", refill_zones=False)
    board = _standing_board(tmp_path / "judged", True)
    vin = {"net": "VIN", "from": {"ref": "U1", "pad": "3"}, "to": {"ref": "J1", "pad": "2"}, "widths": {}}
    fb = {"net": "FB", "from": {"ref": "U1", "pad": "2"}, "to": {"ref": "J1", "pad": "1"}, "widths": {}}
    phase = types.SimpleNamespace(neckdown=False, router_args=())
    ctx = types.SimpleNamespace(work=work, cfg=None)
    st = rr.standing(ctx, [[vin], [vin, fb]], [phase, phase], 1, board, "t")
    assert st.board == board and st.copy == work / "t_drc.kicad_pcb" and st.drc_json == work / "t_drc.json"
    assert st.open_nets == {"FB": 1}
    assert [(e["type"], e["nets"]) for e in st.errors] == [("clearance", ("SW", "VIN"))]
    kinds = {v["type"] for v in json.loads(st.drc_json.read_text())["violations"] if v["severity"] == "error"}
    assert {"via_diameter", "drill_out_of_range"} <= kinds and not any(st.is_real(k) for k in kinds - {"clearance"})
    # phase 0's input (drc_before.json) lacks the short, phase 1's (p0_drc.json) has it
    assert [[(j["joined"], j["violated"]) for j in js] for js in st.judged] == [[(True, True)], [(True, False), (False, False)]]
