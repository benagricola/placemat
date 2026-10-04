"""cutouts.loop_gap natively lands on the Python loops' bits: random loops, the ones that touch, cross, share a
vertex or lie a hair apart, the degenerate ones included."""
import math
import random
import struct

import pytest

native = pytest.importorskip("placemat_native")

from placemat import cutouts, geometry  # noqa: E402


def _bits(v):
    return struct.pack("<d", v)


def _loop(rnd, n, cx, cy, spread, grid):
    pts = []
    for _ in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        r = rnd.uniform(0.2, 1.0) * spread
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if grid:
            x, y = round(x / grid) * grid, round(y / grid) * grid
        pts.append((x, y))
    return pts


def test_loop_gap_is_the_python_loops_bit_for_bit():
    rnd = random.Random(20261004)
    seen = {"zero": 0, "gap": 0}
    for case in range(4000):
        grid = rnd.choice((0.0, 0.0, 0.05, 0.5, 1.0))
        a = _loop(rnd, rnd.choice((1, 2, 3, 4, 4, 8, 20)), 0.0, 0.0, rnd.choice((1.0, 5.0, 40.0)), grid)
        dx, dy = rnd.uniform(-8, 8), rnd.uniform(-8, 8)
        kind = rnd.randrange(5)
        if kind == 0:
            b = _loop(rnd, rnd.choice((2, 3, 4, 8, 30)), dx, dy, rnd.choice((0.5, 3.0)), grid)
        elif kind == 1:
            b = [(x + dx, y + dy) for x, y in a]                        # the same loop, moved
        elif kind == 2:
            b = [a[0]] + _loop(rnd, 3, dx, dy, 2.0, grid)               # sharing a vertex
        elif kind == 3:
            b = [(x + 1e-7 * rnd.uniform(-1, 1), y) for x, y in a]      # a hair off itself
        else:
            b = _loop(rnd, 4, 3.0, 0.0, 1.0, 0.0)                       # a box round a point of a, near
        ref = cutouts._loop_gap_py(a, b)
        got = native.loop_gap(a, b)
        assert _bits(got) == _bits(ref), (case, got, ref)
        assert _bits(cutouts.loop_gap(a, b)) == _bits(ref)
        seen["zero" if ref == 0.0 else "gap"] += 1
    assert seen["zero"] >= 300 and seen["gap"] >= 300, seen


def test_loop_gap_of_an_empty_loop_is_zero():
    assert native.loop_gap([], [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]) == 0.0
    assert native.loop_gap([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], []) == 0.0


def test_loop_gap_takes_what_python_takes(monkeypatch):
    """Points that are lists, not tuples, are the Python loops' to judge."""
    a = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
    b = [[3.0, 0.0], [4.0, 0.0], [4.0, 1.0]]
    assert cutouts.loop_gap(a, b) == cutouts._loop_gap_py(a, b) == 2.0
    monkeypatch.setattr(geometry, "_native", None)
    assert cutouts.loop_gap([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], [(3.0, 0.0), (4.0, 0.0), (4.0, 1.0)]) == 2.0
