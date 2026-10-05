"""A real module (fixtures/fairing/mcu_fan, as tests/real_modules.py runs it) with one escape more: pins 9 and 10 of the
chip's south row, 0.4 mm apart, both ending in a 0.45 / 0.20 via. Two such vias cannot stand on straight lanes at that
pitch; the run places them, the second lane jogging at 45 away from the first, and KiCad's DRC passes the board."""
import json

import pytest

from tests import real_modules as rm
from tests.conftest import needs_kicad

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

_run = {}
NETS = ("GNSS_PPS", "BL_PWM")
DECLARATION = '''esc_pps = board.escape(Part("mcu"), ["GNSS_PPS", "BL_PWM"], vias=["GNSS_PPS", "BL_PWM"],
                       via_size=VIA, via_drill=VIA_DRILL, why="the south row's PPS and PWM pins, each to its via")
board.track(Net("GNSS_PPS"), [esc_pps["GNSS_PPS"]], layer=CopperLayer.F)
board.track(Net("BL_PWM"), [esc_pps["BL_PWM"]], layer=CopperLayer.F)
'''
MARKER = 'board.link(PadRef(Part("c_rf_post"), "VDD_RF")'


@pytest.fixture
def run(tmp_path_factory):
    if not _run:
        def edit(text):
            assert MARKER in text
            return text.replace(MARKER, DECLARATION + MARKER, 1)
        _run["r"] = rm.run(tmp_path_factory.mktemp("mcu"), "mcu", keep_going=True, edit=edit)
    return _run["r"]


def test_the_run_places_both_vias_and_kicad_finds_no_clearance_hole_or_shorting_violation(run):
    result, drc, pcb = run
    assert result.status == "ok", result.record.failure
    assert rm.violations(drc, "clearance", "hole_clearance", "hole_to_hole", "shorting_items") == []
    board = pcbnew.LoadBoard(str(pcb))
    vias = {t.GetNetname() for t in board.GetTracks() if t.GetClass() == "PCB_VIA"}
    assert set(NETS) <= vias


def test_neither_pin_is_among_the_unconnected_or_the_subject_of_a_finding(run):
    result, drc, _ = run
    assert not any(net in v for net in NETS for v in rm.violations(drc, "unconnected_items"))
    # the vias stand on lanes that have a way out on F.Cu, which is escape.via_unneeded: this test is about where they stand
    said = [f["text"] for f in json.loads((result.run_dir / "run.json").read_text())["finding_details"]
            if f.get("cause") != "escape.via_unneeded"]
    assert not any(t.startswith(("U1 pin 9 ", "U1 pin 10 ", "escape U1")) or "via has no" in t for t in said), said
