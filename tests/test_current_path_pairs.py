"""check current-path judges the load's route between the parts that carry
it: each pair at the lesser of their currents, by the widest route between
them, zones included."""
import pytest

from placemat.board_geometry import CopperItem
from placemat.checks import current_paths, ipc2221_width_mm
from placemat.values import Box, CopperLayer
from tests.fixtures import board_geometry, footprint, rect, track

F = CopperLayer.F


def _zone(net, cx, cy, w, h):
    poly = rect(cx, cy, w, h)
    return CopperItem("zone", net, frozenset([F]), (poly,), Box.of_points(poly))


def _power():
    """Q1 (3.6 A, its SW pad at (11.4, 10)) and L1 (3.6 A, its SW pad at
    (18.6, 10)), joined by a 3 mm SW zone lane."""
    q1 = footprint("Q1", 10, 10, nets=("GND", "SW"), fields={"Pm.I": "3.6A"})
    l1 = footprint("L1", 20, 10, nets=("SW", "VOUT"), fields={"Pm.I": "3.6A"})
    return [q1, l1], [_zone("SW", 15, 10, 8, 3)]


def _sw(parts, copper):
    return {v.subject: v for v in current_paths(board_geometry(parts, copper=copper))}["SW"]


def test_the_load_running_in_a_zone_is_judged_by_the_zone_not_a_boot_track():
    parts, copper = _power()
    boot = footprint("C1", 11.4, 14.6, w=1.6, h=0.8, nets=("SW", "BST"))
    v = _sw(parts + [boot], copper + [track("SW", 11.4, 10, 11.4, 14.4, w=0.16)])
    assert v.ok and v.value >= 2.9 and "Q1." in v.note and "L1." in v.note


def test_a_controller_pair_is_judged_at_the_controllers_own_current():
    parts, copper = _power()
    u1 = footprint("U1", 15, 12.5, nets=("SW", "SW"), fields={"Pm.I": "1mA"})       # its two SW pins at y 12.5
    v = _sw(parts + [u1], copper + [track("SW", 13.6, 12.5, 16.4, 12.5, w=0.16),
                                    track("SW", 13.6, 12.5, 13.6, 11.2, w=0.16)])       # into the lane
    assert v.ok, v.note


def test_a_net_a_part_gives_zero_current_does_not_make_it_a_carrier():
    parts, copper = _power()
    sense = footprint("U2", 15, 14, nets=("SW", "GND"), fields={"Pm.I": "sw:0 gnd:1mA"})
    v = _sw(parts + [sense], copper + [track("SW", 13.6, 14, 13.6, 11.2, w=0.04)])
    assert v.ok and "U2" not in v.note


def test_carriers_no_copper_joins_are_not_judged():
    parts, _ = _power()
    v = _sw(parts, [])
    assert v.ok is None and "no copper joins" in v.note


def test_a_narrow_route_between_the_carriers_fails_naming_them_and_the_current():
    parts, _ = _power()
    v = _sw(parts, [track("SW", 11.4, 10, 18.6, 10, w=0.5)])
    assert v.ok is False and v.value == pytest.approx(0.5)
    assert v.limit == pytest.approx(ipc2221_width_mm(3.6, 10.0, 1.0)) and "3.6 A" in v.note


def test_a_carrier_not_joined_yet_is_said_beside_the_pair_that_is_judged():
    parts, copper = _power()
    far = footprint("Q2", 40, 30, nets=("SW", "GND"), fields={"Pm.I": "2A"})
    v = _sw(parts + [far], copper)
    assert v.ok and "Q1." in v.note and "L1." in v.note and "no copper joins" in v.note and "Q2" in v.note
