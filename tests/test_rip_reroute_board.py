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
