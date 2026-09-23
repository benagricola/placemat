"""A board generated with no rules of its own - a module fragment declared
with Layout() and no board config - is laid out by the stdlib's defaults:
the run says so, since nothing else would."""
import dataclasses

from placemat.runner import rule_notes
from tests.fixtures import board_geometry, footprint


def test_a_board_with_no_silk_clearance_is_named():
    g = board_geometry([footprint("R1", 10, 10)], silk_clearance=0.0)
    (note,) = rule_notes(g)
    assert "silk clearance is 0" in note and "config" in note


def test_a_board_with_its_own_rules_has_no_note():
    g = board_geometry([footprint("R1", 10, 10)], silk_clearance=0.2)
    assert rule_notes(g) == []
