"""NativeFill against the Python `_Fill`: identical `touching` sets and
identical `width()` answers (width, neck point, one-step flag) on every
zone fill the current-path test suite exercises, plus a slit fill (a
zero-width seam to a hole, KiCad's own way of drawing a thermal void
inside a pour)."""
import pytest

native = pytest.importorskip("placemat_native")

import placemat.checks as checks_module  # noqa: E402
from placemat.checks import _Fill  # noqa: E402
from tests.fixtures import rect  # noqa: E402

STEP = 0.05

# Every zone fill polygon the current-path tests build, plus a slit fill
# and a wide lane (native/src/fill.rs's own seed-inversion regression,
# mirrored here): (name, fill polygon, entry polygons, exit polygons).
_SLIT = ((11, 8), (19, 8), (19, 12), (15, 12), (15, 10.5),
         (14.5, 10.5), (14.5, 9.5), (15.5, 9.5), (15.5, 10.5), (15, 10.5),
         (15, 12), (11, 12))
_DUMBBELL = ((8, 8), (13, 8), (13, 9.5), (26, 9.5), (26, 8), (31, 8), (31, 12), (26, 12), (26, 10.5),
             (13, 10.5), (13, 12), (8, 12))
_NARROW_NECK = ((11, 8.5), (14.8, 8.5), (14.8, 9.8), (15.2, 9.8), (15.2, 8.5), (19, 8.5), (19, 11.5),
                (15.2, 11.5), (15.2, 10.2), (14.8, 10.2), (14.8, 11.5), (11, 11.5))
_ONE_STEP_NECK = ((11, 8.5), (14.8, 8.5), (14.8, 9.985), (15.2, 9.985), (15.2, 8.5), (19, 8.5), (19, 11.5),
                  (15.2, 11.5), (15.2, 10.015), (14.8, 10.015), (14.8, 11.5), (11, 11.5))

FILLS = [
    ("lane_1.2mm", rect(15, 10, 8, 1.2), [rect(11.25, 10, 0.5, 1.2)], [rect(18.75, 10, 0.5, 1.2)]),
    ("slit_to_a_hole", _SLIT, [rect(11.25, 10, 0.5, 4)], [rect(18.75, 10, 0.5, 4)]),
    ("narrow_neck", _NARROW_NECK, [rect(11.25, 10, 0.5, 3)], [rect(18.75, 10, 0.5, 3)]),
    ("one_step_neck", _ONE_STEP_NECK, [rect(11.25, 10, 0.5, 3)], [rect(18.75, 10, 0.5, 3)]),
    ("track_and_fill_13x4x3", rect(13, 10, 4, 3), [rect(11.25, 10, 0.5, 3)], [rect(14.75, 10, 0.5, 3)]),
    ("pairs_lane_15x8x3", rect(15, 10, 8, 3), [rect(11.25, 10, 0.5, 3)], [rect(18.75, 10, 0.5, 3)]),
    ("neck_lane_18_6x22x3", rect(18.6, 10, 22, 3), [rect(8.1, 10, 0.5, 3)], [rect(29.1, 10, 0.5, 3)]),
    ("dumbbell_pour", _DUMBBELL, [rect(9.5, 10, 1.0, 1.0)], [rect(29.5, 10, 1.0, 1.0)]),
    ("wide_lane_20mm", rect(15, 10, 20, 1.2), [rect(5.25, 10, 0.5, 1.2)], [rect(24.75, 10, 0.5, 1.2)]),
]


def _width_native_and_python(poly, entry, exit_):
    checks_module._NATIVE_FILL = True
    native_result = _Fill(poly, STEP).width(entry, exit_)
    checks_module._NATIVE_FILL = False
    try:
        python_result = _Fill(poly, STEP).width(entry, exit_)
    finally:
        checks_module._NATIVE_FILL = True
    return native_result, python_result


@pytest.mark.parametrize("name,poly,entry,exit_", FILLS, ids=[f[0] for f in FILLS])
def test_native_fill_width_matches_python_fill_width(name, poly, entry, exit_):
    native_result, python_result = _width_native_and_python(poly, entry, exit_)
    assert native_result is not None and python_result is not None, (native_result, python_result)
    n_w, n_pt, n_step = native_result
    p_w, p_pt, p_step = python_result
    assert n_w == pytest.approx(p_w, abs=1e-9)
    assert n_pt == pytest.approx(p_pt, abs=1e-9)
    assert n_step == p_step


@pytest.mark.parametrize("name,poly,entry,exit_", FILLS, ids=[f[0] for f in FILLS])
def test_native_fill_touching_matches_python_fill_touching(name, poly, entry, exit_):
    """The same cells, at several tau levels spanning the fill's own
    depth range, for both the entry and the exit copper."""
    checks_module._NATIVE_FILL = True
    f_native = _Fill(poly, STEP)
    checks_module._NATIVE_FILL = False
    try:
        f_python = _Fill(poly, STEP)
    finally:
        checks_module._NATIVE_FILL = True
    assert f_native.levels == pytest.approx(f_python.levels)
    taus = f_python.levels[:: max(1, len(f_python.levels) // 5)] or [0.0]
    for tau in taus:
        for polys in (entry, exit_):
            got = f_native.touching(polys, tau)
            want = f_python.touching(polys, tau)
            assert got == want, (name, tau, polys)


def test_native_fill_is_used_by_default():
    f = _Fill(rect(0, 0, 4, 4), STEP)
    assert f._native is not None
