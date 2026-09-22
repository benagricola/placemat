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


@dataclass(frozen=True)
class Pin:
    """A pad in the solve. For a movable item, `dx, dy` is its offset from the
    item's origin; for an anchored pad (`item` None) it is where the pad is."""
    item: str | None
    dx: float
    dy: float
    key: tuple = ()             # (refdes, pad number): what a link weight is looked up by


def _at(pin: Pin, pos: dict, axis: int) -> float:
    off = pin.dx if axis == 0 else pin.dy
    return off if pin.item is None else pos[pin.item][axis] + off


def axis_springs(nets: dict, pos: dict, axis: int, weight_of, unit_span: bool) -> list:
    """Per net, the pins sorted along the axis and each consecutive pair joined
    by a spring of weight (2 / k) / span times the link weight between them.
    `unit_span` ignores the span: the first solve starts from positions whose
    spans mean nothing. A spring between two anchored pads is dropped; so is
    one whose link weight is 0."""
    out = []
    for name in sorted(nets):
        pins = nets[name]
        if len(pins) < 2:
            continue
        ordered = sorted(pins, key=lambda p: (_at(p, pos, axis), p.item or "", p.key))
        span = 1.0 if unit_span else max(_at(ordered[-1], pos, axis) - _at(ordered[0], pos, axis), 1.0)
        base = (2.0 / len(pins)) / span
        for a, b in zip(ordered, ordered[1:]):
            if a.item is None and b.item is None:
                continue
            w = base * weight_of(a, b)
            if w > 0.0:
                out.append((a, b, w))
    return out


def solve_axis(movable: list, springs: list, axis: int, pos: dict, centre: float, reg: float,
               pulls: dict, iterations: int, tolerance: float) -> tuple:
    """One axis: minimise the sum of w * (pin_a - pin_b)^2 over the springs,
    plus a weak `reg` pull toward `centre` and each item's pull toward its
    target. Returns ({item: coordinate}, iterations, residual)."""
    idx = {k: i for i, k in enumerate(movable)}
    A = {i: {} for i in range(len(movable))}
    b = [0.0] * len(movable)

    def add(i, j, v):
        A[i][j] = A[i].get(j, 0.0) + v

    for p, q, w in springs:
        po = p.dx if axis == 0 else p.dy
        qo = q.dx if axis == 0 else q.dy
        pi = idx.get(p.item) if p.item is not None else None
        qi = idx.get(q.item) if q.item is not None else None
        if pi is not None and qi is not None:
            if pi == qi:
                continue
            add(pi, pi, w); add(qi, qi, w); add(pi, qi, -w); add(qi, pi, -w)
            b[pi] += w * (qo - po)
            b[qi] += w * (po - qo)
        elif pi is not None:
            add(pi, pi, w)
            b[pi] += w * (_at(q, pos, axis) - po)
        elif qi is not None:
            add(qi, qi, w)
            b[qi] += w * (_at(p, pos, axis) - qo)
    for k, i in idx.items():
        add(i, i, reg)
        b[i] += reg * centre
        if k in pulls:
            target, w = pulls[k]
            add(i, i, w)
            b[i] += w * target
    x0 = [pos[k][axis] for k in movable]
    x, used, residual = cg_solve(A, b, x0, iterations, tolerance)
    return {k: x[i] for k, i in idx.items()}, used, residual


def bisect_spread(items: dict, pos: dict, region: tuple) -> dict:
    """An even spread that keeps the solve's relative order: sort along the
    region's longer side, split into two groups of equal body area, split the
    region in the same proportion, recurse. An item's spread position is the
    centre of the cell it ends in."""
    out = {}

    def split(keys, left, top, right, bottom):
        if not keys:
            return
        if len(keys) == 1:
            out[keys[0]] = ((left + right) / 2.0, (top + bottom) / 2.0)
            return
        wide = (right - left) >= (bottom - top)
        axis = 0 if wide else 1
        keys = sorted(keys, key=lambda k: (pos[k][axis], pos[k][1 - axis], k))
        total = sum(max(items[k], 1e-9) for k in keys)
        half, acc, cut = total / 2.0, 0.0, 1
        for n, k in enumerate(keys[:-1], start=1):
            acc += max(items[k], 1e-9)
            cut = n
            if acc >= half:
                break
        share = sum(max(items[k], 1e-9) for k in keys[:cut]) / total
        if wide:
            mid = left + (right - left) * share
            split(keys[:cut], left, top, mid, bottom)
            split(keys[cut:], mid, top, right, bottom)
        else:
            mid = top + (bottom - top) * share
            split(keys[:cut], left, top, right, mid)
            split(keys[cut:], left, mid, right, bottom)

    split(sorted(items), *region)
    return out


@dataclass(frozen=True)
class SolveResult:
    hints: dict
    rounds: int
    iterations: int
    residual: float


_REG = 0.01                 # the weak pull toward the middle of the board, per unit spring


def global_solve(movable: list, nets: dict, weight_of, areas: dict, region: tuple, start: dict,
                 rounds: int, iterations: int, tolerance: float) -> SolveResult:
    """Solve, spread, re-solve with each item pulled toward its spread cell,
    `rounds` times, the pull rising each round. The last solve's positions,
    clamped inside the region, are the hints."""
    movable = sorted(movable)
    left, top, right, bottom = region
    centre = ((left + right) / 2.0, (top + bottom) / 2.0)
    pos = {k: centre for k in movable}                      # the scatter's spans mean nothing
    used, residual = 0, 0.0
    pulls_x, pulls_y = {}, {}
    for n in range(max(rounds, 1)):
        unit = n == 0
        got, residual = [], 0.0             # the residual reported is the last round's worst axis
        for axis, pulls in ((0, pulls_x), (1, pulls_y)):
            springs = axis_springs(nets, pos, axis, weight_of, unit)
            coords, u, res = solve_axis(movable, springs, axis, pos, centre[axis], _REG, pulls,
                                        iterations, tolerance)
            used, residual = used + u, max(residual, res)
            got.append(coords)
        pos = {k: (got[0][k], got[1][k]) for k in movable}
        spread = bisect_spread({k: areas.get(k, 1.0) for k in movable}, pos, region)
        weight = 0.01 * (2.0 ** n)
        pulls_x = {k: (spread[k][0], weight) for k in movable}
        pulls_y = {k: (spread[k][1], weight) for k in movable}
    hints = {k: (round(min(max(pos[k][0], left), right), 4), round(min(max(pos[k][1], top), bottom), 4))
             for k in movable}
    return SolveResult(hints, max(rounds, 1), used, round(residual, 12))
