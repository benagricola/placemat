"""A real module (fixtures/fairing/mcu_fan, laid out by scripts/Mcu_layout_west_fan.py) whose west row fans out north-west in
one escape over five of its pins, with a bypass placed beside the chip, turned 135, at the middle of the row. The upper
pins' lanes pass over the bypass and the lower ones under it, and the lower ones start past it: the escape is laid out when
the chip is placed, before the bypass, and must still keep clear of it. The owner's hand layout of the same pins is the
reference: the lower risers end 4.73 and 4.83 mm out from the pads' centres, the upper ones 3.85 and 3.91."""
import json

import pytest

from tests import real_modules as rm
from tests.conftest import needs_kicad

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

# The hand layout's lanes stand at the least pitch, a track and a clearance, with no room for the router's grid snap
# (lanes.Layouter._step), and the bypass stands against them with none to spare. Laid out for a router on a fine grid,
# the lanes keep the hand layout's pitch, so what is checked is how they pass the bypass.
FINE_GRID = {"route_router_args": ("--grid-step", "0.001")}

_run = {}
SCRIPT = "scripts/Mcu_layout_west_fan.py"
ROW = {"43": "LED_STATUS_DRIVE", "44": "VBUS_DISCH", "45": "USB_WET", "47": "PD_IRQ", "49": "UART_TX_CHIP"}
# The hand layout's riser ends (x, module frame) of the same pins
HAND_RISER_END = {"44": -3.8530, "45": -3.9050, "47": -4.7280, "49": -4.8330}
HAND_TOLERANCE = 0.15       # mm: the hand layout leaves a little room the least pitch does not


@pytest.fixture
def run(tmp_path_factory):
    if not _run:
        _run["r"] = rm.run(tmp_path_factory.mktemp("mcu"), "mcu", keep_going=True, overrides=FINE_GRID, script=SCRIPT)
    return _run["r"]


def _findings(result):
    return [str(f) for f in json.loads((result.run_dir / "run.json").read_text())["findings"]]


def _risers(pcb):
    """pin -> the x where its riser (the track level from the pad) ends and its 45 begins, over the escape's pins."""
    board = pcbnew.LoadBoard(str(pcb))
    pad_x = pcbnew.ToMM(board.FindFootprintByReference("U1").FindPadByNumber("45").GetPosition().x)
    out = {}
    for pin, net in ROW.items():
        for t in board.GetTracks():
            if t.GetClass() != "PCB_TRACK" or t.GetNetname() != net or abs(t.GetStart().y - t.GetEnd().y) > 10:
                continue
            xs = sorted((pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetEnd().x)))
            if abs(xs[1] - pad_x) < 1e-3:
                out[pin] = xs[0]
    return out


def test_the_run_is_ok_and_kicad_finds_no_clearance_or_shorting_violation(run):
    result, drc, _ = run
    assert result.status == "ok", result.record.failure
    assert rm.violations(drc, "clearance", "hole_clearance", "shorting_items") == []


def test_no_lane_is_reported_blocked_by_the_bypass(run):
    result, _, _ = run
    said = _findings(result)
    assert not any("its lane is blocked" in t for t in said), said


def test_the_lower_lanes_start_past_the_bypass_as_the_hand_layout_does(run):
    _, _, pcb = run
    risers = _risers(pcb)
    assert set(HAND_RISER_END) <= set(risers), risers
    for pin, x in HAND_RISER_END.items():
        assert risers[pin] == pytest.approx(x, abs=HAND_TOLERANCE), (pin, risers)
