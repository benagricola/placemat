"""A global pre-solve: where every searched item would sit if the whole
netlist pulled on it at once, before any of them is scanned.

Pure: pins are points, springs are weights, and nothing here knows a board.
The placer uses the answer as a hint; `scan()` still legalises, and ordering
stays with the placer. Deterministic throughout - every loop runs in sorted
order, the solver has a fixed cap, and answers are rounded - so the same
inputs give the same bytes."""
from __future__ import annotations

from dataclasses import dataclass
import math


def _matvec(A: dict, x: list) -> list:
    return [sum(v * x[j] for j, v in sorted(A.get(i, {}).items())) for i in range(len(x))]


def _dot(a: list, b: list) -> float:
    return sum(p * q for p, q in zip(a, b))


def cg_solve(A: dict, b: list, x0: list, iterations: int, tolerance: float) -> tuple:
    """Conjugate gradient for a symmetric positive definite A held as
    {row: {col: value}}. Returns (x, iterations used, residual norm)."""
    x = list(x0)
    r = [bi - ai for bi, ai in zip(b, _matvec(A, x))]
    p = list(r)
    rr = _dot(r, r)
    used = 0
    while used < iterations and math.sqrt(rr) > tolerance:
        Ap = _matvec(A, p)
        pAp = _dot(p, Ap)
        if pAp <= 0.0:
            break
        alpha = rr / pAp
        x = [xi + alpha * pi for xi, pi in zip(x, p)]
        r = [ri - alpha * api for ri, api in zip(r, Ap)]
        rr_new = _dot(r, r)
        p = [ri + (rr_new / rr) * pi for ri, pi in zip(r, p)]
        rr = rr_new
        used += 1
    return x, used, math.sqrt(rr)
