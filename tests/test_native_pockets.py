"""Native and Python _largest_rectangle agree, exactly (no epsilon needed:
this is pure integer/boolean logic - see native/src/pockets.rs).

Skips itself when placemat_native isn't built."""
import random

import pytest

placemat_native = pytest.importorskip("placemat_native")

from placemat import placer


def _python_largest_rectangle(free, rows, cols, need_r=1, need_c=1):
    """The reference body, called directly (bypassing placer._largest_rectangle's
    own dispatch) so this test is meaningful even when native is built."""
    heights = [0] * cols
    best = None
    for r in range(rows):
        for c in range(cols):
            heights[c] = heights[c] + 1 if free[r][c] else 0
        stack = []
        for c in range(cols + 1):
            h = heights[c] if c < cols else 0
            start = c
            while stack and stack[-1][1] >= h:
                s, sh = stack.pop()
                area = sh * (c - s)
                if sh >= need_r and c - s >= need_c and (best is None or area > best[0]):
                    best = (area, r - sh + 1, s, r + 1, c)
                start = s
            stack.append((start, h))
    return best


def _random_grid(rnd, rows, cols, p_free):
    return [[rnd.random() < p_free for _ in range(cols)] for _ in range(rows)]


def test_agrees_on_randomised_grids():
    rnd = random.Random(20260924)
    mismatches = []
    for _ in range(500):
        rows, cols = rnd.randint(1, 20), rnd.randint(1, 20)
        p_free = rnd.uniform(0.2, 0.95)
        grid = _random_grid(rnd, rows, cols, p_free)
        need_r, need_c = rnd.randint(1, 3), rnd.randint(1, 3)
        want = _python_largest_rectangle(grid, rows, cols, need_r, need_c)
        got = placemat_native.largest_rectangle(grid, rows, cols, need_r, need_c)
        if got != want:
            mismatches.append((rows, cols, need_r, need_c, want, got))
    assert not mismatches, mismatches[:5]


def test_agrees_on_edge_cases():
    for rows, cols, grid in [
        (0, 0, []),
        (1, 1, [[True]]),
        (1, 1, [[False]]),
        (3, 3, [[True] * 3] * 3),
        (2, 2, [[False, False], [False, False]]),
    ]:
        want = _python_largest_rectangle(grid, rows, cols)
        got = placemat_native.largest_rectangle(grid, rows, cols, 1, 1)
        assert got == want, (rows, cols, grid, want, got)


def test_dispatch_reaches_native(monkeypatch):
    calls = []

    class Fake:
        def largest_rectangle(self, free, rows, cols, need_r, need_c):
            calls.append((rows, cols, need_r, need_c))
            return _python_largest_rectangle(free, rows, cols, need_r, need_c)

    monkeypatch.setattr(placer._geometry_module, "_native", Fake())
    grid = [[True, True], [True, False]]
    result = placer._largest_rectangle(grid, 2, 2)
    assert calls == [(2, 2, 1, 1)]
    assert result == (2, 0, 0, 1, 2)


def test_dispatch_is_python_when_native_is_none(monkeypatch):
    monkeypatch.setattr(placer._geometry_module, "_native", None)
    grid = [[True, True], [True, False]]
    assert placer._largest_rectangle(grid, 2, 2) == (2, 0, 0, 1, 2)
