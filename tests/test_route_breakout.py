"""placemat route on the placed Breakout: the router runs on the signal nets
only, closure comes back as numbers, and the placed board is untouched."""
import shutil
from pathlib import Path

import pytest

from placemat.kicad.route import ROUTER_DEFAULT, route_board
from tests.conftest import needs_breakout, needs_kicad

needs_router = pytest.mark.skipif(not (Path(ROUTER_DEFAULT) / ".venv/bin/python").exists(),
                                  reason="KiCadRoutingTools not at %s" % ROUTER_DEFAULT)
pytestmark = [needs_kicad, needs_breakout, needs_router]


def test_routing_the_committed_breakout_scores_and_leaves_the_board_alone(breakout_pcb, tmp_path):
    for ext in (".kicad_pcb", ".kicad_pro"):
        src = breakout_pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    before = pcb.read_bytes()
    report = route_board(pcb, tmp_path / "route", exclude_nets={"V48P", "GND"}, quick=True, iterations=200)
    assert pcb.read_bytes() == before                     # routing works on a copy
    assert report.valid is True                           # the committed board is DRC clean
    assert 0.0 <= report.closure_clean <= 1.0
    assert report.routed_pcb.exists() and report.log.exists()
    assert report.seconds > 0 and report.router_version
    assert isinstance(report.open_nets, dict)
