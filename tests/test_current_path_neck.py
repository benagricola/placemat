"""check current-path gives its neck as a point and a length along the
route: how far the widest route stays within 10% of its narrowest width.
Pure: synthetic boards."""
import pytest

from placemat.checks import current_paths
from tests.fixtures import board_geometry, footprint, track


def _vin(parts, copper):
    return {v.subject: v for v in current_paths(board_geometry(parts, copper=copper))}["VIN"]


def _parts():
    u = footprint("U1", 10, 10, nets=("VIN", "X"), fields={"Pm.I": "vin:3A"})
    c = footprint("C1", 30, 10, nets=("VIN", "GND"))
    return [u, c]


def test_the_necks_point_lies_on_it_and_its_length_is_measured_along_it():
    """A 2 mm long, 0.3 mm wide neck between two 0.6 mm wide runs: the point
    is on the neck and the length is the neck's own, not the wide runs
    either side of it. (The wide runs stay narrower than the neck's own
    rounded end caps are long, so they do not touch each other directly.)"""
    wide1 = track("VIN", 8.6, 10, 15, 10, w=0.6)
    neck = track("VIN", 15, 10, 17, 10, w=0.3)
    wide2 = track("VIN", 17, 10, 28.6, 10, w=0.6)
    v = _vin(_parts(), [wide1, neck, wide2])
    assert v.value == pytest.approx(0.3) and not v.ok
    assert "neck at (16.00, 10.00), 2.00 mm long" in v.note


def test_the_length_sums_a_run_of_similarly_narrow_segments():
    """The neck made of two 1 mm segments, both 0.3 mm wide: the length
    covers both, not just the one the point sits on."""
    wide1 = track("VIN", 8.6, 10, 15, 10, w=0.6)
    neck1 = track("VIN", 15, 10, 16, 10, w=0.3)
    neck2 = track("VIN", 16, 10, 17, 10, w=0.3)
    wide2 = track("VIN", 17, 10, 28.6, 10, w=0.6)
    v = _vin(_parts(), [wide1, neck1, neck2, wide2])
    assert "2.00 mm long" in v.note


def test_a_route_through_a_zone_fill_gives_no_neck_point():
    """The existing zone behaviour is unchanged: a route through a fill says
    the fill's width is not measured, and gives no neck point."""
    from placemat.board_geometry import CopperItem
    from placemat.values import Box, CopperLayer
    from tests.fixtures import rect
    F = CopperLayer.F
    poly = rect(18.6, 10, 22, 3)          # spans U1's and C1's VIN pads
    zone = CopperItem("zone", "VIN", frozenset([F]), (poly,), Box.of_points(poly))
    v = _vin(_parts(), [zone])
    assert v.ok is None and "not measured" in v.note and "neck at" not in v.note
