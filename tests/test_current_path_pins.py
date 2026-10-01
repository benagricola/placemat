"""check current-path takes a load as all of its pins on the net: the route
judged is the widest to any of them, so a load whose small pin is reached
through a narrow neck is judged by the wide route to its other pin. Pure:
synthetic boards."""
from placemat.checks import current_paths
from tests.fixtures import board_geometry, footprint, track


def _board(copper):
    src = footprint("R9", 10, 10, nets=("SW", "GND"), fields={"Pm.I": "sw:3A"})
    load = footprint("U3", 30, 10, w=6, nets=("SW", "SW"), fields={"Pm.I": "sw:3A"})      # pins at x 27.6 and 32.4
    return {v.subject: v for v in current_paths(board_geometry([src, load], copper=copper))}["SW"]


NARROW = [track("SW", 8.6, 10, 27.6, 10, w=0.3)]                                            # to pin 1 only
WIDE = [track("SW", 8.6, 12, 32.4, 12, w=2.0), track("SW", 8.6, 12, 8.6, 10, w=2.0),
        track("SW", 32.4, 12, 32.4, 10, w=2.0)]                                              # to pin 2 only


def test_a_load_reached_only_through_a_narrow_neck_to_its_small_pin_fails():
    v = _board(NARROW)
    assert v.ok is False and "U3.1" in v.note and "too long" in v.note, v.note


def test_a_load_with_a_second_pin_joined_wide_is_judged_by_the_wide_route():
    v = _board(NARROW + WIDE)
    assert v.ok is True and v.value >= 1.9, v.note
    assert "U3.2" in v.note, v.note
