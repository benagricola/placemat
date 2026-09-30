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


def test_a_load_running_in_a_zone_is_judged_by_the_fill_not_by_a_boot_track():
    """A route through a fill alone is judged by the fill's width along it
    (the 3 mm lane, within one 0.05 mm step), not by a thin boot track on
    the same net."""
    parts, copper = _power()
    boot = footprint("C1", 11.4, 14.6, w=1.6, h=0.8, nets=("SW", "BST"))
    v = _sw(parts + [boot], copper + [track("SW", 11.4, 10, 11.4, 14.4, w=0.16)])
    assert v.ok is True and 3.0 - 0.05 - 1e-6 <= v.value <= 3.0 + 1e-6, v.note
    assert "the fill's narrowest point" in v.note and "Q1." in v.note


def test_a_route_through_a_zone_and_a_track_is_judged_by_the_track():
    parts, _ = _power()
    copper = [_zone("SW", 13, 10, 4, 3), track("SW", 15, 10, 18.6, 10, w=0.5)]     # half zone, half a thin track
    v = _sw(parts, copper)
    assert v.ok is False and v.value == pytest.approx(0.5) and "zone" in v.note


def test_the_note_names_the_pad_the_route_starts_from():
    a1 = footprint("A1", 10, 10, nets=("SW", "SW"), fields={"Pm.I": "3.6A"})     # SW on both; A1 first of the pair
    l1 = footprint("L1", 20, 10, nets=("SW", "VOUT"), fields={"Pm.I": "3.6A"})
    v = _sw([a1, l1], [track("SW", 8.6, 10, 8.6, 13, w=2.0), track("SW", 8.6, 13, 18.6, 13, w=2.0),
                       track("SW", 18.6, 13, 18.6, 10, w=2.0)])                  # from A1.1 only, round below
    assert "A1.1" in v.note and "A1.2" not in v.note


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
    assert v.ok is not False and "U2" not in v.note          # the 0.04 mm sense line is not the load's


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
    assert v.ok is not False and "no copper joins" in v.note and "Q2" in v.note and "Q1." in v.note


def test_one_carrying_part_is_not_judged_and_says_what_would_let_it_be():
    """A net with one part carrying current (a sense resistor, a connector's
    tab) cannot say where the load goes: the widest-joined other pad is often
    a capacitor, which carries ripple. The check says so rather than failing
    that branch at the full current."""
    r = footprint("R1", 10, 10, nets=("IN", "SENSE"), fields={"Pm.I": "3A"})
    c = footprint("C1", 20, 10, nets=("SENSE", "GND"))
    v = {v.subject: v for v in current_paths(board_geometry([r, c], copper=[track("SENSE", 10.6, 10, 19.4, 10, w=0.2)]))}
    s = v["SENSE"]
    assert s.ok is None, s
    assert "only R1 carries current on SENSE" in s.note and "Pm.I" in s.note, s.note
