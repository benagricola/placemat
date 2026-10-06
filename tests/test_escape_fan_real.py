"""A real module (fixtures/fairing/mcu_fan: an MCU's cell with its cached generation, its layout script and the board's
settings) run end to end, as tests/real_modules.py runs the others, with a turned escape over two pins of its west row
(44 and 45), beside a bypass part turned 135. Synthetic boards have passed where a real one failed, so this is the check
that counts: KiCad's DRC on the board written, the lanes against the owner's hand layout of the same two pins, and the
searched RF inductor's spot."""
import json
import math

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

# The hand layout's own figures for the same two pins (module frame): the end of each riser, and x - y along each 45.
PINS = ("44", "45")
HAND_RISER_END = {"44": -3.8525, "45": -3.9051}
HAND_LINE = {"44": -1.6525, "45": -2.1051}
PAD_TIP = -3.7425                       # the west row's pad tips
HAND_TOLERANCE = 0.08                   # mm: the hand layout starts the first riser 0.0575 past the row's end
BYPASS_PAD_LINE = -4.661 + 1.711        # x - y of the bypass's pad 1 at (-4.661, -1.711)


@pytest.fixture
def run(tmp_path_factory):
    if not _run:
        _run["r"] = rm.run(tmp_path_factory.mktemp("mcu"), "mcu", keep_going=True, overrides=FINE_GRID)
    return _run["r"]


def _findings(result):
    return [str(f) for f in json.loads((result.run_dir / "run.json").read_text())["findings"]]


def _net_of(board, pin):
    return next(p.GetNetname() for p in board.FindFootprintByReference("U1").Pads() if p.GetNumber() == pin)


def _segments(pcb, pin):
    """The straight tracks of the net on U1's pin `pin`, as ((x, y), (x, y)) in mm."""
    board = pcbnew.LoadBoard(str(pcb))
    net = _net_of(board, pin)
    mm = pcbnew.ToMM
    return [((mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y)))
            for t in board.GetTracks() if t.GetNetname() == net and t.GetClass() == "PCB_TRACK"]


def _legs(pcb, pin):
    legs = _segments(pcb, pin)
    assert len(legs) == 2, legs                                        # the riser and the 45
    riser = next(leg for leg in legs if abs(leg[0][1] - leg[1][1]) < 1e-4)
    diag = next(leg for leg in legs if abs(leg[0][1] - leg[1][1]) > 1e-3)
    return riser, diag


def test_the_run_is_ok_and_kicad_finds_no_clearance_or_shorting_violation(run):
    result, drc, _ = run
    assert result.status == "ok", result.record.failure
    assert rm.violations(drc, "clearance", "hole_clearance", "shorting_items") == []


def test_the_two_lanes_are_not_among_the_unconnected_and_raise_no_finding(run):
    result, drc, pcb = run
    board = pcbnew.LoadBoard(str(pcb))
    nets = [_net_of(board, pin) for pin in PINS]
    assert not any(net in v for net in nets for v in rm.violations(drc, "unconnected_items"))
    said = _findings(result)
    assert not any(net in t or "U1 pin %s " % pin in t for net, pin in zip(nets, PINS) for t in said), said


def test_the_lanes_are_the_hand_layouts_to_a_hand_s_slack(run):
    _, _, pcb = run
    lines, risers = {}, {}
    for pin in PINS:
        riser, diag = _legs(pcb, pin)
        risers[pin] = riser[1][0]
        lines[pin] = diag[0][0] - diag[0][1]
        assert abs(abs(diag[1][0] - diag[0][0]) - abs(diag[1][1] - diag[0][1])) < 1e-4           # a 45, to the nanometre
    for pin in PINS:
        assert risers[pin] == pytest.approx(HAND_RISER_END[pin], abs=HAND_TOLERANCE)
        assert lines[pin] == pytest.approx(HAND_LINE[pin], abs=HAND_TOLERANCE)
        assert risers[pin] > HAND_RISER_END[pin] - 1e-6                # no longer than the hand layout's: the 45 is as near the row as it may
    # a track, a clearance and the fine grid's snap room across their direction
    assert (lines["44"] - lines["45"]) / math.sqrt(2.0) == pytest.approx(0.32 + 0.001 / math.sqrt(2.0), abs=1e-5)
    assert PAD_TIP - risers["44"] == pytest.approx(0.0525, abs=2e-3)                         # one stagger from the row's end


def test_the_lanes_stand_the_hand_layouts_distance_over_the_bypass(run):
    """The hand layout's 45s pass 0.84 mm (in x - y) above the bypass's pad 1: not under it."""
    _, _, pcb = run
    for pin in PINS:
        _, diag = _legs(pcb, pin)
        assert diag[0][0] - diag[0][1] - BYPASS_PAD_LINE >= 0.84 - HAND_TOLERANCE


def test_the_searched_inductor_lands_where_its_link_is_within_its_limit(run):
    """The search missed a spot a fine step off its lattice that was legal and within the link's limit (1.50 mm).

    Since Beside stands against the shapes of its item's envelope, the bypass beside the chip stands 0.32 mm nearer (a
    legal, tighter placement), and the inductor, searched after it, lands 0.2 mm further out: its link is 1.61 mm against
    the 1.50 mm soft limit. That is the correct result of the tighter placement, so the test asserts the link is reported
    with its measured length and where the inductor stands, not the old position."""
    result, _, pcb = run
    said = _findings(result)
    over = [t for t in said if t.startswith("link L1.1 to U1.1")]
    assert len(over) == 1 and "1.61 mm, over its 1.50 mm limit" in over[0], said
    at = pcbnew.LoadBoard(str(pcb)).FindFootprintByReference("L1").GetPosition()
    assert (pcbnew.ToMM(at.x), pcbnew.ToMM(at.y)) == pytest.approx((-2.80, 5.33), abs=0.05)


def test_no_handoff_pin_of_the_module_is_reported_walled(run):
    result, _, _ = run
    said = _findings(result)
    assert not any("no other pad is on the net" in t for t in said), said
