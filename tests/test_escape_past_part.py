"""An escape is laid out after the firm parts placed relative to its part, so its lanes keep clear of them: a bypass placed
beside a chip, turned 135 at the middle of a west row, stands where a lane of one escape over the whole row would run, and the
lanes under it start past it. A part placed relative to the escape itself, or to a part that is, waits for the lanes
instead. Synthetic boards (tests/escape_fixtures.py: a 0.4 mm pitch QFN-56 at (30, 30), track 0.16, clearance 0.16)."""
import pytest

from placemat.copper import Track
from placemat.geometry import poly_distance
from placemat.values import Beside, Corner, CopperLayer, Edge, Location, Net, PadRef, Part
from tests.escape_fixtures import CLEAR56, bypass_135, fan_board, one_pad

F = CopperLayer.F
GAP = 0.64                  # two lanes between the row and the bypass


def _chain(plan, net):
    return [t for t in plan.copper if isinstance(t, Track) and t.net == net]


def _board(pins, beside=True, **kw):
    """The QFN-56 with a bypass turned 135 beside its west row (a lane west of it, its pad 1 level with pin 45) and one
    NW escape over `pins`, drawn as stubs."""
    cap = bypass_135("C1", "cap", ("BYP", "GND"), 12.0, 12.0)
    b = fan_board([cap], keep_going=True, **kw)
    esc = b.escape(Part("mcu"), pins, turn=Corner.NW, why="a fan over the row")
    if beside:
        b.place(Part("cap"), at=Beside(Part("mcu"), Edge.WEST, gap=GAP, align=(1, PadRef(Part("mcu"), 45))),
                why="the bypass beside the chip")
    for p in pins:
        b.track(Net("N%d" % p), [esc[p]], layer=F, why="its lane")
    return b, esc


def _riser_end(plan, pin):
    legs = [t for t in _chain(plan, "N%d" % pin) if abs(t.start.y - t.end.y) < 1e-9]
    return min(min(t.start.x, t.end.x) for t in legs)


def test_lanes_under_a_bypass_beside_the_chip_start_past_it():
    plan = _board([44, 45, 47, 48, 49])[0].resolve()
    assert [f for f in plan.findings if f.kind in ("copper", "escape_lane", "fixed")] == []
    pads = [s for s in plan.occupancy.items["C1"].shapes if s.kind == "pad"]
    for pin in (44, 45, 47, 48, 49):
        assert min(poly_distance(t.polygon, p.poly) for t in _chain(plan, "N%d" % pin) for p in pads) >= CLEAR56 - 1e-6, pin


def test_the_lower_lanes_start_further_out_for_the_bypass_than_without_it():
    with_cap = _board([44, 45, 47, 48, 49])[0].resolve()
    without = _board([44, 45, 47, 48, 49], beside=False)[0].resolve()
    for pin in (47, 48, 49):
        assert _riser_end(with_cap, pin) < _riser_end(without, pin) - 0.05, pin


def test_the_upper_lanes_are_where_they_were():
    """Over the bypass, the lanes keep the stagger they have from the row's end."""
    with_cap = _board([44, 45])[0].resolve()
    without = _board([44, 45], beside=False)[0].resolve()
    for pin in (44, 45):
        assert _riser_end(with_cap, pin) == pytest.approx(_riser_end(without, pin), abs=1e-6)


def test_a_part_placed_by_the_escape_waits_for_its_lanes():
    """Beside the escape of a part, a second part is placed after the lanes (a part beside the chip is placed first)."""
    cap = bypass_135("C1", "cap", ("BYP", "GND"), 12.0, 12.0)
    side = one_pad("R1", "r1", "N60", 12.0, 12.0)
    b = fan_board([cap, side], keep_going=True)
    esc = b.escape(Part("mcu"), [43, 44, 45], turn=Corner.NW, why="a fan")
    b.place(Part("r1"), at=Beside(esc, Edge.NORTH), why="north of the lanes")
    b.place(Part("cap"), at=Beside(Part("mcu"), Edge.WEST, gap=GAP, align=(1, PadRef(Part("mcu"), 45))),
            why="the bypass beside the chip")
    for p in (43, 44, 45):
        b.track(Net("N%d" % p), [esc[p]], layer=F, why="its lane")
    plan = b.resolve()
    lanes = b._escape_laid[0].box()
    assert plan.box("r1").bottom <= lanes.top + 1e-6
    assert [f for f in plan.findings if f.kind in ("fixed", "unplaced", "escape_lane")] == []


def test_two_escapes_whose_waits_wait_on_each_other_are_both_laid_as_they_were():
    """A part beside the first escape and a part beside the second, each also placed against the chip: each escape would wait
    for the part the other's lanes hold up. Both are laid when nothing else can go on, and everything is placed."""
    a = one_pad("R1", "r1", "N60", 12.0, 12.0)
    c = one_pad("R2", "r2", "N61", 14.0, 12.0)
    b = fan_board([a, c], keep_going=True)
    west = b.escape(Part("mcu"), [44, 45], why="the west row's pins out")
    north = b.escape(Part("mcu"), [33, 34], why="the north row's pins out")
    b.place(Part("r1"), at=Beside(west, Edge.WEST), why="west of the west lanes")
    b.place(Part("r2"), at=Beside(north, Edge.NORTH), why="north of the north lanes")
    plan = b.resolve()
    assert sorted(b._escape_laid) == [0, 1]
    assert plan.placement("r1") is not None and plan.placement("r2") is not None
