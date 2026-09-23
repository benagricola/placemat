"""Native and Python geometry predicates give the same answers.

Skips itself (not fail) when placemat_native isn't built - see
native/README.md. Distances are compared with an epsilon, not bit-exact
equality: Rust's f64::hypot (libm) and Python's math.hypot (a different,
compensated-summation algorithm since 3.8) can differ by ~1 ULP on the same
inputs, which every comparison in occupancy.py already tolerates (a 1e-9
threshold or _clean's 9-decimal rounding) - see
docs/superpowers/specs/2026-09-24-native-core-design.md."""
import math
import pathlib
import random

import pytest

placemat_native = pytest.importorskip("placemat_native")

from placemat import geometry as g
from tests.fixtures import rect

EPS = 1e-6


def _box(cx, cy, w, h, angle=0.0):
    pts = rect(0, 0, w, h)
    if angle:
        c, s = math.cos(angle), math.sin(angle)
        pts = tuple((x * c - y * s, x * s + y * c) for x, y in pts)
    return tuple((x + cx, y + cy) for x, y in pts)


def _octagon(cx, cy, r):
    return tuple((cx + r * math.cos(2 * math.pi * i / 8), cy + r * math.sin(2 * math.pi * i / 8))
                 for i in range(8))


def _circle16(cx, cy, r):
    return g.circle_polygon(g.Location(cx, cy), r, n=16)


def _random_pairs(n, seed):
    rnd = random.Random(seed)
    shapes = [
        lambda x, y: _box(x, y, rnd.uniform(0.5, 5.0), rnd.uniform(0.5, 5.0), rnd.uniform(0, math.pi)),
        lambda x, y: _octagon(x, y, rnd.uniform(0.5, 3.0)),
        lambda x, y: _circle16(x, y, rnd.uniform(0.3, 2.0)),
    ]
    out = []
    for _ in range(n):
        a = rnd.choice(shapes)(0.0, 0.0)
        b = rnd.choice(shapes)(rnd.uniform(-6, 6), rnd.uniform(-6, 6))
        out.append((a, b))
    return out


PAIRS = _random_pairs(3000, seed=20260924)


def test_polys_overlap_agrees_on_randomised_pairs():
    mismatches = [(a, b) for a, b in PAIRS if placemat_native.polys_overlap(a, b) != g.polys_overlap(a, b)]
    assert not mismatches


def test_poly_distance_agrees_on_randomised_pairs():
    for a, b in PAIRS:
        nd = placemat_native.poly_distance(a, b)
        pd = g.poly_distance(a, b)
        assert abs(nd - pd) < EPS, (a, b, nd, pd)


def test_point_segment_distance_agrees_on_randomised_inputs():
    rnd = random.Random(1)
    for _ in range(3000):
        p = (rnd.uniform(-10, 10), rnd.uniform(-10, 10))
        a = (rnd.uniform(-10, 10), rnd.uniform(-10, 10))
        b = (rnd.uniform(-10, 10), rnd.uniform(-10, 10))
        nd = placemat_native.point_segment_distance(p, a, b)
        pd = g.point_segment_distance(p, a, b)
        assert abs(nd - pd) < EPS


class _FakeNative:
    """A stand-in for placemat_native that counts calls, to prove the
    dispatch actually reaches it rather than merely existing unused."""
    def __init__(self):
        self.overlap_calls = 0
        self.distance_calls = 0
        self.psd_calls = 0

    def polys_overlap(self, a, b):
        self.overlap_calls += 1
        return _reference_overlap(a, b)

    def poly_distance(self, a, b):
        self.distance_calls += 1
        return _reference_distance(a, b)

    def point_segment_distance(self, p, a, b):
        self.psd_calls += 1
        return g._point_segment_distance_py(p, a, b)


def _reference_overlap(a, b):
    # The pure-Python plain-path test, called directly so the fake doesn't
    # recurse into the dispatch it is standing in for.
    pa, pb = g._Prepared(a), g._Prepared(b)
    save = g._native
    g._native = None
    try:
        return g.polys_overlap(a, b)
    finally:
        g._native = save


def _reference_distance(a, b):
    save = g._native
    g._native = None
    try:
        return g.poly_distance(a, b)
    finally:
        g._native = save


def test_dispatch_reaches_native_for_small_non_rectangular_polygons(monkeypatch):
    fake = _FakeNative()
    monkeypatch.setattr(g, "_native", fake)
    # Two axis-aligned rectangles are answered by the box alone (_rect_of),
    # in Python, before ever reaching native - octagons exercise the actual
    # native dispatch, the plain (non-grid, non-rectangle-shortcut) path.
    small_a, small_b = _octagon(0, 0, 2), _octagon(1, 0, 2)
    g.polys_overlap(small_a, small_b)
    assert fake.overlap_calls == 1
    g.poly_distance(small_a, small_b)
    assert fake.distance_calls == 1
    g.point_segment_distance((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
    assert fake.psd_calls == 1


def test_dispatch_skips_native_for_two_axis_aligned_rectangles(monkeypatch):
    """Confirms the current understanding of geometry.polys_overlap's own
    dispatch order (box-reject, then _rect_of, then the grid check, then
    native): two rectangles are answered without native at all."""
    fake = _FakeNative()
    monkeypatch.setattr(g, "_native", fake)
    assert g.polys_overlap(rect(0, 0, 2, 2), rect(1, 0, 2, 2)) is True
    assert fake.overlap_calls == 0


def test_dispatch_keeps_the_python_grid_path_for_many_vertex_polygons(monkeypatch):
    fake = _FakeNative()
    monkeypatch.setattr(g, "_native", fake)
    big = _circle16(0, 0, 5.0) + _circle16(0, 0, 5.01)[:10]  # >= 24 vertices: forces the grid path
    assert len(big) >= 24
    small = rect(0, 0, 1, 1)
    g.polys_overlap(big, small)
    assert fake.overlap_calls == 0  # grid path taken, not native


def test_dispatch_is_the_python_path_when_native_is_none(monkeypatch):
    monkeypatch.setattr(g, "_native", None)
    a, b = rect(0, 0, 2, 2), rect(1, 0, 2, 2)
    assert g.polys_overlap(a, b) is True
    assert g.poly_distance(rect(0, 0, 1, 1), rect(5, 0, 1, 1)) == pytest.approx(4.0)


def test_agrees_with_the_polys_overlap_reference_oracle():
    """Reuses test_polys_overlap_fast.py's own independent oracle (the full
    edge-walk test, verbatim, minus the box short-circuit it names
    `expected`) rather than comparing native against geometry.polys_overlap
    - a stronger check, since it does not share code with either. Covers
    the coinciding-outline case (placemat commit e2614d8) and many-vertex
    outlines (a reservation or keepout drawn with arcs), calling native
    directly so it also exercises polygon sizes Python's own dispatch would
    route to the cached grid path instead."""
    from tests.test_polys_overlap_fast import expected, _poly, _rect, _ring

    rnd = random.Random(20260924)
    mismatches = []
    for _ in range(4000):
        a = _poly(rnd, rnd.uniform(0, 10), rnd.uniform(0, 10), rnd.uniform(0.2, 4), rnd.choice([4, 6, 16, 60]), rnd.random() < 0.5)
        b = (_rect(*(lambda x, y: (x, y, x + rnd.uniform(0.1, 3), y + rnd.uniform(0.1, 3)))(rnd.uniform(0, 10), rnd.uniform(0, 10)))
             if rnd.random() < 0.5 else
             _poly(rnd, rnd.uniform(0, 10), rnd.uniform(0, 10), rnd.uniform(0.2, 4), rnd.choice([4, 12, 200]), rnd.random() < 0.5))
        if placemat_native.polys_overlap(a, b) != expected(a, b):
            mismatches.append((a, b))
        if placemat_native.polys_overlap(b, a) != expected(b, a):
            mismatches.append((b, a))
    for big in (_ring(25, 25, 19, 21, 160), _ring(25, 25, 5, 24, 300)):
        for _ in range(500):
            x, y = rnd.uniform(0, 50), rnd.uniform(0, 50)
            small = _rect(x, y, x + rnd.uniform(0.2, 6), y + rnd.uniform(0.2, 6))
            if placemat_native.polys_overlap(big, small) != expected(big, small):
                mismatches.append((big, small))
    assert not mismatches


def test_agrees_on_real_footprint_outlines():
    """Real courtyard and pad polygons, not synthetic boxes: pulled straight
    off a fixture board so the shapes are whatever KiCad actually drew."""
    pytest.importorskip("pcbnew")
    from placemat.kicad.read import read_board
    board = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/modules/SlotControl/layout/layout.kicad_pcb"
    if not board.exists():
        pytest.skip("fixture board not found")
    geo = read_board(board)
    polys = []
    for fp in geo.footprints:
        polys.append(g.box_polygon(fp.courtyard_box))
        for p in fp.pads:
            polys.extend(p.outlines)
    assert len(polys) > 10
    rnd = random.Random(7)
    mismatches = 0
    for _ in range(2000):
        a, b = rnd.choice(polys), rnd.choice(polys)
        if placemat_native.polys_overlap(a, b) != g.polys_overlap(a, b):
            mismatches += 1
        nd, pd = placemat_native.poly_distance(a, b), g.poly_distance(a, b)
        if abs(nd - pd) >= EPS:
            mismatches += 1
    assert mismatches == 0
