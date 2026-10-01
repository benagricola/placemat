"""check current-path weighs how long a neck is: a stretch of the route
narrower than the width its current needs is credited as short when
conduction to the copper at each end holds its rise inside its share of
`check.rise_c`, and fails as too long when it does not. The note gives its
width, its length and which. Pure: synthetic boards."""
import re

import pytest

from placemat.board_geometry import CopperItem
from placemat.checks import current_paths, ipc2221_width_mm
from placemat.settings import Settings, bind
from placemat.values import Box, CopperLayer
from tests.fixtures import board_geometry, footprint, rect, track

F = CopperLayer.F
AMPS = "3.6A"
NEED = ipc2221_width_mm(3.6, 10.0, 1.0)         # 1.758 mm


def _parts(l_x=30.0):
    """Q1's SW pad at (11.4, 10), L1's `l_x - 1.4` (28.6 by default), each 1 x 1."""
    q1 = footprint("Q1", 10, 10, nets=("GND", "SW"), fields={"Pm.I": AMPS})
    l1 = footprint("L1", l_x, 10, nets=("SW", "VOUT"), fields={"Pm.I": AMPS})
    return [q1, l1]


def _pour(*outlines):
    return CopperItem("poly", "SW", frozenset([F]), tuple(outlines), Box.of_points([p for o in outlines for p in o]))


def _zone(*outlines):
    return CopperItem("zone", "SW", frozenset([F]), tuple(outlines), Box.of_points([p for o in outlines for p in o]))


def _dumbbell(neck_w, neck_len, x0=14.0):
    """Two 4 mm bells joined by a neck `neck_w` across and `neck_len` long, from x0, and the
    parts whose SW pads stand in them: (outline, parts)."""
    x1 = x0 + neck_len
    y0, y1 = 10 - neck_w / 2, 10 + neck_w / 2
    outline = ((10, 8), (x0, 8), (x0, y0), (x1, y0), (x1, 8), (x1 + 4, 8), (x1 + 4, 12), (x1, 12), (x1, y1),
               (x0, y1), (x0, 12), (10, 12))
    return outline, _parts(x1 + 2.4)


def _sw(copper, parts=None):
    return {v.subject: v for v in current_paths(board_geometry(parts or _parts(), copper=copper))}["SW"]


def _bell(neck_w, neck_len, kind=_pour):
    outline, parts = _dumbbell(neck_w, neck_len)
    return _sw([kind(outline)], parts)


def _length(note):
    return float(re.search(r"a ([\d.]+) mm long neck at", note).group(1))


def _max(note):
    return float(re.search(r"passes up to ([\d.]+) mm", note).group(1))


def test_a_long_narrow_strip_fails_as_before():
    v = _sw([_pour(rect(20, 10, 20, 0.9))])
    assert v.ok is False and v.limit == pytest.approx(NEED)
    assert 0.9 - 0.05 - 1e-6 <= v.value <= 0.9 + 1e-6
    assert "too long" in v.note and "credited" not in v.note, v.note
    assert 15.0 <= _length(v.note) <= 17.5, v.note             # pad edge to pad edge


def test_a_short_constriction_between_wide_pours_passes_with_its_length_printed():
    v = _bell(1.03, 0.4)
    assert v.value < NEED and v.limit == pytest.approx(NEED)
    assert v.ok is True, v.note
    assert "credited as short" in v.note and ("at %.2f mm" % v.value) in v.note, v.note
    assert 0.4 <= _length(v.note) <= 3.0, v.note             # the neck and the flare into it


def test_a_zone_fill_constriction_is_credited_the_same_way():
    v = _bell(1.03, 0.4, kind=_zone)
    assert v.ok is True and "credited as short" in v.note, v.note


def test_a_constriction_just_over_the_length_it_passes_fails():
    short = _bell(1.03, 3.0)
    long_ = _bell(1.03, 6.0)
    assert short.ok is True and _length(short.note) <= _max(short.note), short.note
    assert long_.ok is False and "too long" in long_.note, long_.note
    assert _length(long_.note) > _max(long_.note), long_.note
    assert _max(short.note) == pytest.approx(_max(long_.note))      # the width sets how long a neck passes


def test_a_narrower_neck_passes_a_shorter_length():
    wide = _bell(1.2, 3.5)
    thin = _bell(0.6, 3.5)
    assert _max(thin.note) < _max(wide.note)
    assert wide.ok is True and thin.ok is False, (wide.note, thin.note)


def test_the_note_gives_width_length_and_basis():
    v = _bell(1.03, 0.4)
    assert re.search(r"a [\d.]+ mm long neck at 0\.9\d mm, credited as short: ", v.note), v.note
    assert "of its 4 C share of the 10 C rise" in v.note and "conduction to the copper at each end" in v.note


def test_the_end_share_setting_moves_the_outcome():
    assert _bell(1.03, 0.4).ok is True
    with bind(Settings(check_neck_end_share=1.0)):
        v = _bell(1.03, 0.4)
    assert v.ok is False and "not credited as short" in v.note and "check.neck_end_share" in v.note, v.note
    base = _max(_bell(1.03, 3.0).note)
    with bind(Settings(check_neck_end_share=0.9)):         # the ends take nine tenths of the rise: a shorter neck passes
        assert _max(_bell(1.03, 3.0).note) < base * 0.6


def test_conductivity_and_resistivity_settings_move_the_outcome():
    assert _bell(1.03, 6.0).ok is False
    with bind(Settings(check_neck_conductivity=900.0)):
        assert _bell(1.03, 6.0).ok is True
    with bind(Settings(check_neck_resistivity=1.0e-8)):
        assert _bell(1.03, 6.0).ok is True


def test_a_neck_too_thin_to_measure_is_not_credited():
    """Narrower than one raster step: no path of cells, so no length."""
    thin = ((10, 8), (14, 8), (14, 9.985), (16, 9.985), (16, 8), (20, 8), (20, 12), (16, 12), (16, 10.015),
            (14, 10.015), (14, 12), (10, 12))
    v = _sw([_pour(thin)], _parts(17.4))
    assert v.ok is False and "length not measured" in v.note, v.note


def test_a_short_track_neck_between_wide_tracks_is_credited_and_a_long_one_is_not():
    def route(neck_to):
        return [track("SW", 11.4, 10, 14, 10, w=1.8), track("SW", 14, 10, neck_to, 10, w=0.5),
                track("SW", neck_to, 10, 28.6, 10, w=1.8)]
    short = _sw(route(16.0))
    assert short.ok is True and "credited as short" in short.note and "a 2.00 mm long neck at 0.50 mm" in short.note
    long_ = _sw(route(20.0))
    assert long_.ok is False and "too long" in long_.note and "a 6.00 mm long neck at 0.50 mm" in long_.note


def test_a_route_with_no_neck_is_judged_as_before():
    v = _sw([_pour(rect(20, 10, 20, 3.0))])
    assert v.ok is True and "neck long" not in v.note and "credited" not in v.note and "too long" not in v.note
