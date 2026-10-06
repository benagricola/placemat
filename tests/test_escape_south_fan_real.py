"""A real module (fixtures/fairing/mcu_fan, laid out by its current script: scripts/Mcu_layout_fans.py) whose south row fans out
south-east in one escape, lanes 0.45 mm apart across their direction (x - y), the least a track and its clearance allow
(and the snap room of the fine grid the fixture is laid out for).
The handoff pins in the fan have their way out along their own lane carried on, between the lanes beside them, with no
room to spare. A way out judged on cells of a grid, off that line, did not find it and reported them walled in; a track
drawn there, and KiCad's DRC on it, is the check that the way is real."""
import json

import pytest

from tests import real_modules as rm
from tests.conftest import needs_kicad

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

# The hand layout's lanes stand at the least pitch, a track and a clearance, with no room for the router's grid snap
# (lanes.Layouter._step), and the west fan's bypass stands against them with none to spare. Laid out for a router on a
# fine grid, the lanes keep the hand layout's pitch, so what is checked is the handoff pins' way out.
FINE_GRID = {"route_router_args": ("--grid-step", "0.001")}
_run = {}
SCRIPT = "scripts/Mcu_layout_fans.py"


@pytest.fixture
def run(tmp_path_factory):
    if not _run:
        _run["r"] = rm.run(tmp_path_factory.mktemp("mcu"), "mcu", keep_going=True, overrides=FINE_GRID, script=SCRIPT)
    return _run["r"]


def _findings(result):
    return [str(f) for f in json.loads((result.run_dir / "run.json").read_text())["findings"]]


def test_no_handoff_pin_of_the_south_fan_is_reported_walled(run):
    result, _, _ = run
    said = _findings(result)
    assert not any("no other pad is on the net" in t for t in said), said


def test_the_fans_lanes_are_laid_at_the_least_pitch(run):
    """The premise: the way out between neighbours has no room to spare, so it is the lane's own line."""
    _, _, pcb = run
    board = pcbnew.LoadBoard(str(pcb))
    lines = {}
    for t in board.GetTracks():
        if t.GetClass() != "PCB_TRACK" or t.GetNetname() not in ("GNSS_TX", "GNSS_RX", "STRAP_JTAG", "GNSS_PPS", "BL_PWM"):
            continue
        a, b = t.GetStart(), t.GetEnd()
        if abs(abs(a.x - b.x) - abs(a.y - b.y)) < 10 and a.x != b.x:                    # the 45
            lines[t.GetNetname()] = pcbnew.ToMM(a.x) - pcbnew.ToMM(a.y)
    assert lines["GNSS_TX"] - lines["GNSS_RX"] == pytest.approx(-0.4535, abs=1e-4)
    assert lines["GNSS_PPS"] - lines["STRAP_JTAG"] == pytest.approx(0.4535, abs=1e-4)
