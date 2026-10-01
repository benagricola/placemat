"""check current-path gives its neck as a point and a length along the
route: how far the widest route stays narrower than the width its current
needs. Pure: synthetic boards."""
import pytest

from placemat.checks import current_paths
from tests.fixtures import board_geometry, footprint, track


def _vin(parts, copper):
    return {v.subject: v for v in current_paths(board_geometry(parts, copper=copper))}["VIN"]


def _parts():
    u = footprint("U1", 10, 10, nets=("VIN", "X"), fields={"Pm.I": "vin:3A"})
    c = footprint("C1", 30, 10, nets=("VIN", "GND"), fields={"Pm.I": "vin:3A"})
    return [u, c]


def test_the_necks_point_lies_on_it_and_its_length_is_measured_along_it():
    """A 6 mm long, 0.3 mm wide neck between two runs 1.5 mm wide, at least
    what 3 A needs: the point is on the neck and the length is the neck's
    own, not the wide runs either side of it. (The wide runs stay shorter
    than the neck's own end caps are long, so they do not touch each other
    directly.)"""
    wide1 = track("VIN", 8.6, 10, 15, 10, w=1.5)
    neck = track("VIN", 15, 10, 21, 10, w=0.3)
    wide2 = track("VIN", 21, 10, 28.6, 10, w=1.5)
    v = _vin(_parts(), [wide1, neck, wide2])
    assert v.value == pytest.approx(0.3) and not v.ok
    assert "neck at (18.00, 10.00)" in v.note and "a 6.00 mm long neck at 0.30 mm, too long" in v.note, v.note


def test_the_length_sums_a_run_of_segments_narrower_than_the_need():
    """The neck made of two 3 mm segments, 0.3 and 0.5 mm wide, both under
    what 3 A needs: the length covers both, not just the one the point sits
    on, and its width is the narrower."""
    wide1 = track("VIN", 8.6, 10, 15, 10, w=1.5)
    neck1 = track("VIN", 15, 10, 18, 10, w=0.3)
    neck2 = track("VIN", 18, 10, 21, 10, w=0.5)
    wide2 = track("VIN", 21, 10, 28.6, 10, w=1.5)
    v = _vin(_parts(), [wide1, neck1, neck2, wide2])
    assert "a 6.00 mm long neck at 0.30 mm" in v.note, v.note


def test_a_route_through_a_zone_fill_names_the_fills_narrowest_point():
    """A route through a fill alone is judged by the fill's width along it
    (3 mm across, within one 0.05 mm step), its neck a point in the fill."""
    from placemat.board_geometry import CopperItem
    from placemat.values import Box, CopperLayer
    from tests.fixtures import rect
    F = CopperLayer.F
    poly = rect(18.6, 10, 22, 3)          # spans U1's and C1's VIN pads
    zone = CopperItem("zone", "VIN", frozenset([F]), (poly,), Box.of_points(poly))
    v = _vin(_parts(), [zone])
    assert v.ok is True and 3.0 - 0.05 - 1e-6 <= v.value <= 3.0 + 1e-6, v.note
    assert "the fill's narrowest point" in v.note and "not measured" not in v.note


def test_an_arc_neck_is_measured_along_the_arc():
    """An arc's length is its own, not the chord between its ends."""
    wide1 = track("VIN", 8.6, 10, 15, 10, w=1.5)
    neck = track("VIN", 15, 10, 21, 10, w=0.3, length=6.5)      # an arc: 6.5 mm along, 6 mm across
    wide2 = track("VIN", 21, 10, 28.6, 10, w=1.5)
    v = _vin(_parts(), [wide1, neck, wide2])
    assert "a 6.50 mm long neck" in v.note, v.note


def test_a_pour_neck_is_named_as_the_pours_and_given_the_length_the_raster_measures():
    """A drawn pour's narrowest point is named as the pour's, and its length
    is how far the route runs through pour narrower than the need: the 13 mm
    neck and the flare into it at each end (a disc 1.37 mm across no longer
    fits), within a step or two."""
    from placemat.board_geometry import CopperItem
    from placemat.values import Box, CopperLayer
    dumbbell = ((8, 8), (13, 8), (13, 9.5), (26, 9.5), (26, 8), (31, 8), (31, 12), (26, 12), (26, 10.5),
                (13, 10.5), (13, 12), (8, 12))
    pour = CopperItem("poly", "VIN", frozenset([CopperLayer.F]), (dumbbell,), Box.of_points(dumbbell))
    v = _vin(_parts(), [pour])
    assert "the pour's narrowest" in v.note, v.note
    import re
    length = float(re.search(r"a ([\d.]+) mm long neck", v.note).group(1))
    assert 13.0 <= length <= 15.5 and "too long" in v.note, v.note


def test_a_pour_is_judged_along_the_route_not_by_a_sliver_off_it():
    """A drawn pour 3 mm across with a 0.2 mm spur off its side, where no
    load goes: the route is judged at the pour's width along it, as a zone
    fill's is, not at the spur."""
    from placemat.board_geometry import CopperItem
    from placemat.values import Box, CopperLayer
    body = ((8, 8.5), (18, 8.5), (18, 7.0), (18.2, 7.0), (18.2, 8.5), (31, 8.5), (31, 11.5), (8, 11.5))
    pour = CopperItem("poly", "VIN", frozenset([CopperLayer.F]), (body,), Box.of_points(body))
    v = _vin(_parts(), [pour])
    assert v.ok is True and 3.0 - 0.05 - 1e-6 <= v.value <= 3.0 + 1e-6, v.note
    assert "the pour's narrowest point" in v.note, v.note
