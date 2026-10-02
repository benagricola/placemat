"""A real module (fixtures/fairing/mcu_fan, laid out by scripts/Mcu_layout_westfan_case.py) whose west row fans out north-west
in one escape over nine pins, `run=` a lane long, with four of the tracks going on from their lanes into parts and a bypass
beside the chip, turned 135, with its V3V3 pad level with pin 45. The upper lanes pass over the bypass and the lower ones under
it: the lower lanes start past it although `run=` makes each lane's own copper a short stub, and the bypass's own track from
pin 46 runs between the two fans. The owner's hand layout of the same pins is the reference."""
import json

import pytest

from tests import real_modules as rm
from tests.conftest import needs_kicad

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

SCRIPT = "scripts/Mcu_layout_westfan_case.py"
ROW = {"43": "LED_STATUS_DRIVE", "44": "VBUS_DISCH", "45": "USB_WET", "47": "PD_IRQ", "48": "SDA_PWR", "49": "UART_TX_CHIP",
       "50": "UART_RX", "51": "STRAP_VSPI"}
# The hand layout's riser ends (x, module frame) of the same pins
HAND_RISER_END = {"44": -3.8530, "45": -3.9050, "47": -4.7280, "48": -4.7800, "49": -4.8330, "50": -4.8900, "51": -4.9500}
HAND_TOLERANCE = 0.15       # mm: the hand layout leaves a little room the least pitch does not
_run = {}


def _level_with_pin_45(text: str) -> str:
    """The script's comment says the bypass's V3V3 pad stands level with pin 45; its code aligns it with pin 46."""
    old = 'align=(1, PadRef(Part("mcu"), VDD3P3_CPU_PIN))'
    assert old in text
    return text.replace(old, 'align=(1, PadRef(Part("mcu"), CPU_BYPASS_ROW_PIN))')


@pytest.fixture
def run(tmp_path_factory):
    if not _run:
        _run["r"] = rm.run(tmp_path_factory.mktemp("mcu"), "mcu", keep_going=True, script=SCRIPT, edit=_level_with_pin_45)
    return _run["r"]


def _findings(result):
    return [str(f) for f in json.loads((result.run_dir / "run.json").read_text())["findings"]]


def _risers(pcb):
    """pin -> the x where its riser (the track level from the pad) ends and its 45 begins."""
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


def test_every_lane_gets_out_and_every_track_is_drawn(run):
    result, _, _ = run
    said = [t for t in _findings(result) if "lane is blocked" in t or "not drawn" in t or "walled" in t or "copper " in t]
    assert not said, said


def test_the_lower_lanes_start_past_the_bypass_as_the_hand_layout_does(run):
    _, _, pcb = run
    risers = _risers(pcb)
    assert set(HAND_RISER_END) <= set(risers), risers
    for pin, x in HAND_RISER_END.items():
        assert risers[pin] == pytest.approx(x, abs=HAND_TOLERANCE), (pin, risers)


def _bypass_a_mm_further_out(text: str) -> str:
    return _level_with_pin_45(text).replace("gap=LANE, align=(1,", "gap=LANE + 1.0, align=(1,")


@pytest.fixture
def far(tmp_path_factory):
    if "far" not in _run:
        _run["far"] = rm.run(tmp_path_factory.mktemp("mcu_far"), "mcu", keep_going=True, script=SCRIPT, edit=_bypass_a_mm_further_out)
    return _run["far"]


def test_the_bypass_s_own_track_from_pin_46_keeps_its_way_between_the_fans(far):
    """The bypass stands a millimetre further out, so its track from pin 46 is no longer its pad's own reach: the lanes
    are laid out with that track in place, and the lower ones start out beside the bypass."""
    result, drc, pcb = far
    assert rm.violations(drc, "clearance", "hole_clearance", "shorting_items") == []
    said = [t for t in _findings(result) if "V3V3" in t and ("not drawn" in t or "copper " in t)]
    assert not said, said
    board = pcbnew.LoadBoard(str(pcb))
    bypass_x = pcbnew.ToMM(board.FindFootprintByReference("C1").FindPadByNumber("1").GetPosition().x)
    risers = _risers(pcb)
    for pin in ("47", "48"):
        assert risers[pin] < bypass_x + 0.5, (pin, risers, bypass_x)         # not at the row, where the track passes
