"""The global pre-solve, pure: springs, the solver, spreading. No KiCad."""
import pytest

from placemat import solve


def test_conjugate_gradient_solves_a_small_system_exactly():
    # 4x - y = 3, -x + 3y = 5  ->  x = 14/11, y = 23/11
    A = {0: {0: 4.0, 1: -1.0}, 1: {0: -1.0, 1: 3.0}}
    x, used, residual = solve.cg_solve(A, [3.0, 5.0], [0.0, 0.0], 50, 1e-12)
    assert x == [pytest.approx(14 / 11), pytest.approx(23 / 11)]
    assert residual < 1e-9 and used <= 2


def test_a_solve_that_hits_its_cap_says_so():
    A = {i: {i: 2.0, **({i + 1: -1.0} if i < 49 else {}), **({i - 1: -1.0} if i > 0 else {})} for i in range(50)}
    x, used, residual = solve.cg_solve(A, [1.0] * 50, [0.0] * 50, 3, 1e-12)
    assert used == 3 and residual > 1e-12
