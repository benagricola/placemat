"""Two rules of an escape's lane layout, on a synthetic part (tests/escape_fixtures.py: a 0.4 mm pitch QFN-56 at (30, 30),
track 0.16, clearance 0.16, west row pads' tips at x = 26.2575) with no fixture file.

A lane's start is judged out to the row's depth whatever `run=` leaves of the lane's own copper, so a part beside the row
that `run=` makes the lane stop short of is still passed. A firm pad-to-pad track from a pad of the escape's part that the
escape does not name, to a placed pad, stands in the occupancy while the lanes are laid out, so they leave it room."""
import math

import pytest

from placemat.copper import Track
from placemat.geometry import poly_distance
from placemat.lanes import ROUTER_GRID_STEP
from placemat.values import Beside, Corner, CopperLayer, Edge, Net, PadRef, Part
from tests.escape_fixtures import CLEAR56, TRACK56, bypass_135, fan_board

F = CopperLayer.F
LANE = TRACK56 + CLEAR56
UPPER = [43, 44, 45]
LOWER = [47, 48, 49]
BAD = ("copper", "escape_lane", "fixed", "unplaced")


def _chain(plan, net):
    return [t for t in plan.copper if isinstance(t, Track) and t.net == net]


def _riser_end(plan, pin):
    legs = [t for t in _chain(plan, "N%d" % pin) if abs(t.start.y - t.end.y) < 1e-9]
    return min(min(t.start.x, t.end.x) for t in legs)


def _board(pins, bypass=True, gap=LANE * 2, track_from=None, level=45):
    """The QFN-56 with one NW escape over `pins`, `run=` one lane, each pin's own track drawn as its lane. With `bypass`, a
    bypass turned 135 beside the west row (its pad 1 level with pin `level`, `gap` out); with `track_from`, a firm track
    from that pin, not named by the escape, to the bypass's pad 1."""
    cap = bypass_135("C1", "cap", ("BYP", "GND"), 12.0, 12.0)
    b = fan_board([cap] if bypass else [], keep_going=True, pin_nets={track_from: "BYP"} if track_from else None)
    esc = b.escape(Part("mcu"), pins, turn=Corner.NW, run=LANE, why="a fan over the row")
    if bypass:
        b.place(Part("cap"), at=Beside(Part("mcu"), Edge.WEST, gap=gap, align=(1, PadRef(Part("mcu"), level))),
                why="the bypass beside the chip")
    for p in pins:
        b.track(Net("N%d" % p), [esc[p]], layer=F, why="its lane")
    if track_from:
        b.track(Net("BYP"), [PadRef(Part("mcu"), track_from), PadRef(Part("cap"), 1)], layer=F, why="the bypass's own track")
    return b


def _findings(plan):
    return [str(f) for f in plan.findings if f.kind in BAD or "not drawn" in str(f) or "blocked" in str(f)]


def _min_gap(plan, net_a, net_b):
    return min(poly_distance(x.polygon, y.polygon) for x in _chain(plan, net_a) for y in _chain(plan, net_b))


def test_lanes_start_past_a_bypass_beside_the_row_whatever_run_leaves_of_them():
    plan = _board(UPPER + LOWER).resolve()
    without = _board(UPPER + LOWER, bypass=False).resolve()
    assert _findings(plan) == []
    pads = [s for s in plan.occupancy.items["C1"].shapes if s.kind == "pad"]
    for pin in LOWER:
        assert _riser_end(plan, pin) < _riser_end(without, pin) - 0.05, pin
        legs = _chain(plan, "N%d" % pin)
        assert min(poly_distance(t.polygon, p.poly) for t in legs for p in pads) >= CLEAR56 - 1e-6, pin


def test_a_pad_to_pad_track_from_a_pin_between_the_fans_is_drawn_and_the_lanes_leave_it_room():
    plan = _board(UPPER + LOWER, gap=LANE + 1.0, track_from=46).resolve()
    assert _findings(plan) == []
    track = _chain(plan, "BYP")
    assert track, "the track is not drawn"
    for pin in UPPER + LOWER:
        assert _min_gap(plan, "BYP", "N%d" % pin) >= CLEAR56 - 1e-6, pin


# the riser ends (x) of the escape on its own: from the tips, one stagger per pad of the row (the step, a track, a clearance
# and the router's grid snap room, times sqrt 2, less the 0.4 mm pitch)
STAGGER = (LANE + ROUTER_GRID_STEP / math.sqrt(2.0)) * math.sqrt(2.0) - 0.4
RISER_END = {p: 26.2575 - (p - 43) * STAGGER for p in (43, 44, 45, 47, 48, 49)}


def test_with_no_bypass_and_no_track_the_lanes_are_where_they_were():
    plan = _board(UPPER + LOWER, bypass=False).resolve()
    assert _findings(plan) == []
    for pin, x in RISER_END.items():
        assert _riser_end(plan, pin) == pytest.approx(x, abs=1e-4), pin
