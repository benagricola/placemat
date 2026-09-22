# Global Pre-solve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every searched item a starting hint from the whole netlist at once, behind `[solve] enabled`, and measure on a real board whether it helps.

**Architecture:** `solve.py` is pure and knows nothing of placemat's types: pins, springs, a dictionary sparse matrix, conjugate gradient, area bisection and the SimPL loop. `layout.py` builds the pins from the occupancy the first time a searched item is placed, runs the solve once, and uses its answer as the hint between an explicit `at=Near` and `_seed_hint`.

**Tech Stack:** Python 3.12 stdlib only.

**Spec:** `docs/superpowers/specs/2026-09-22-global-presolve-design.md`

## Global Constraints

- **Zero runtime dependencies**, **plain ASCII**, **no commit mentions Claude, Anthropic or a session**, **no module, part or board names** in skill, migrations or source.
- **Deterministic.** Every loop over sorted keys; fixed caps; outputs rounded to 1e-4 mm.
- **With `solve.enabled` false, placement is byte-identical to before.**

## File Structure

- `src/placemat/solve.py` (create) - `Pin`, `cg_solve`, `axis_springs`, `solve_axis`, `bisect_spread`, `global_solve`, `SolveResult`.
- `src/placemat/settings.py` - `solve_enabled`, `solve_iterations`, `solve_tolerance`, `solve_rounds`.
- `src/placemat/layout.py` - builds the model, calls it once, uses its hints.
- `skills/placemat/references/api.md` - settings rows (enforced by an existing test).
- `tests/test_solve.py` (create), `tests/test_solve_wiring.py` (create).

---

## Task 1: Conjugate gradient on a dictionary matrix

**Interfaces:** `cg_solve(A: dict[int, dict[int, float]], b: list[float], x0: list[float], iterations: int, tolerance: float) -> tuple[list[float], int, float]` returning (x, iterations used, final residual norm).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_solve.py
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
```

- [ ] **Step 2: Run to verify it fails** - no module `placemat.solve`.

- [ ] **Step 3: Implement**

```python
# src/placemat/solve.py
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
```

- [ ] **Step 4: Run to verify it passes.** - [ ] **Step 5: Commit** - "Conjugate gradient, pure and bounded"

---

## Task 2: Pins, springs, and one axis solved

**Interfaces:** `Pin(item: str | None, dx: float, dy: float, key: tuple = ())` - for an anchored pad `item` is None and `dx, dy` are its absolute position; `axis_springs(nets: dict[str, list[Pin]], pos: dict, axis: int, weight_of, unit_span: bool) -> list[tuple[Pin, Pin, float]]`; `solve_axis(movable: list[str], springs, axis, pos, centre: float, reg: float, pulls: dict[str, tuple[float, float]], iterations, tolerance) -> tuple[dict[str, float], int, float]` where `pulls` maps an item to (target, weight).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_solve.py
def _pin(item, dx=0.0, dy=0.0, key=()):
    return solve.Pin(item, dx, dy, key)


def test_one_item_between_two_anchors_lands_at_the_weighted_midpoint():
    nets = {"A": [_pin(None, 0.0, 0.0), _pin("u")], "B": [_pin("u"), _pin(None, 10.0, 0.0)]}
    pos = {"u": (100.0, 100.0)}
    springs = solve.axis_springs(nets, pos, 0, lambda a, b: 1.0, unit_span=True)
    got, _, _ = solve.solve_axis(["u"], springs, 0, pos, 5.0, 0.0, {}, 100, 1e-12)
    assert got["u"] == pytest.approx(5.0)


def test_a_short_link_pulls_harder_than_a_default_one():
    left, right = _pin(None, 0.0, 0.0, ("J1", "1")), _pin(None, 10.0, 0.0, ("J2", "1"))
    u_l, u_r = _pin("u", key=("U1", "1")), _pin("u", key=("U1", "2"))
    nets = {"A": [left, u_l], "B": [u_r, right]}
    weight = lambda a, b: 8.0 if {a.key, b.key} == {("J1", "1"), ("U1", "1")} else 1.0
    pos = {"u": (5.0, 0.0)}
    got, _, _ = solve.solve_axis(["u"], solve.axis_springs(nets, pos, 0, weight, True), 0, pos, 5.0, 0.0, {}, 100, 1e-12)
    assert got["u"] < 5.0                    # nearer the end the SHORT link names


def test_a_chain_of_three_spreads_evenly_between_its_anchors():
    nets = {"A": [_pin(None, 0.0, 0.0), _pin("a")], "B": [_pin("a"), _pin("b")],
            "C": [_pin("b"), _pin("c")], "D": [_pin("c"), _pin(None, 12.0, 0.0)]}
    pos = {k: (0.0, 0.0) for k in "abc"}
    got, _, _ = solve.solve_axis(list("abc"), solve.axis_springs(nets, pos, 0, lambda a, b: 1.0, True),
                                 0, pos, 6.0, 0.0, {}, 200, 1e-12)
    assert [got[k] for k in "abc"] == [pytest.approx(3.0), pytest.approx(6.0), pytest.approx(9.0)]


def test_a_pin_offset_pulls_the_item_by_its_pin_not_its_centre():
    nets = {"A": [_pin(None, 0.0, 0.0), _pin("u", dx=2.0)]}
    pos = {"u": (50.0, 0.0)}
    got, _, _ = solve.solve_axis(["u"], solve.axis_springs(nets, pos, 0, lambda a, b: 1.0, True),
                                 0, pos, 0.0, 1e-9, {}, 100, 1e-12)
    assert got["u"] == pytest.approx(-2.0, abs=1e-5)   # its pin, 2 mm right of its origin, lands on the anchor
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# append to src/placemat/solve.py
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
```

- [ ] **Step 4: Run to verify it passes.** - [ ] **Step 5: Commit** - "Springs from the netlist, pad-aware, and one axis solved"

---

## Task 3: Spreading by area bisection

**Interfaces:** `bisect_spread(items: dict[str, float], pos: dict, region: tuple[float, float, float, float]) -> dict[str, tuple[float, float]]` where `items` maps a key to its body area and `region` is (left, top, right, bottom).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_solve.py
def test_bisection_gives_every_item_its_own_cell_and_keeps_their_order():
    pos = {k: (float(i) * 0.01, 5.0) for i, k in enumerate("abcd")}      # piled on a line
    got = solve.bisect_spread({k: 1.0 for k in "abcd"}, pos, (0.0, 0.0, 40.0, 10.0))
    xs = [got[k][0] for k in "abcd"]
    assert xs == sorted(xs) and len(set(round(x, 6) for x in xs)) == 4
    assert xs == [pytest.approx(5.0), pytest.approx(15.0), pytest.approx(25.0), pytest.approx(35.0)]


def test_spread_positions_stay_inside_the_region():
    pos = {k: (500.0, -300.0) for k in "abcdefg"}
    got = solve.bisect_spread({k: 1.0 + i for i, k in enumerate("abcdefg")}, pos, (0.0, 0.0, 30.0, 20.0))
    assert all(0.0 <= x <= 30.0 and 0.0 <= y <= 20.0 for x, y in got.values())


def test_a_bigger_item_gets_a_bigger_cell():
    pos = {"big": (0.0, 0.0), "small": (1.0, 0.0)}
    got = solve.bisect_spread({"big": 3.0, "small": 1.0}, pos, (0.0, 0.0, 40.0, 10.0))
    assert got["big"][0] == pytest.approx(15.0) and got["small"][0] == pytest.approx(35.0)
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# append to src/placemat/solve.py
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
```

- [ ] **Step 4: Run to verify it passes.** - [ ] **Step 5: Commit** - "An even spread that keeps the solve's order"

---

## Task 4: The SimPL loop

**Interfaces:** `SolveResult(hints: dict[str, tuple[float, float]], rounds: int, iterations: int, residual: float)`; `global_solve(movable: list[str], nets, weight_of, areas: dict, region: tuple, start: dict, rounds: int, iterations: int, tolerance: float) -> SolveResult`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_solve.py
def _board_nets():
    return {"A": [_pin(None, 0.0, 10.0), _pin("a")], "B": [_pin("a"), _pin("b")],
            "C": [_pin("b"), _pin("c")], "D": [_pin("c"), _pin(None, 40.0, 10.0)]}


def test_the_same_input_solves_to_the_same_numbers_twice():
    args = (list("abc"), _board_nets(), lambda a, b: 1.0, {k: 4.0 for k in "abc"},
            (0.0, 0.0, 40.0, 20.0), {k: (200.0, 200.0) for k in "abc"}, 6, 200, 1e-9)
    assert solve.global_solve(*args) == solve.global_solve(*args)


def test_the_solve_spreads_a_chain_along_its_anchors_inside_the_board():
    r = solve.global_solve(list("abc"), _board_nets(), lambda a, b: 1.0, {k: 4.0 for k in "abc"},
                           (0.0, 0.0, 40.0, 20.0), {k: (200.0, 200.0) for k in "abc"}, 6, 200, 1e-9)
    xs = [r.hints[k][0] for k in "abc"]
    assert xs == sorted(xs) and all(0.0 <= x <= 40.0 for x in xs)
    assert all(0.0 <= r.hints[k][1] <= 20.0 for k in "abc")
    assert r.rounds == 6 and r.iterations > 0


def test_an_anchored_pad_never_moves():
    nets = {"A": [_pin(None, 7.0, 3.0), _pin("a")]}
    r = solve.global_solve(["a"], nets, lambda a, b: 1.0, {"a": 1.0}, (0.0, 0.0, 20.0, 20.0),
                           {"a": (0.0, 0.0)}, 3, 100, 1e-9)
    assert set(r.hints) == {"a"}
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# append to src/placemat/solve.py
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
```

- [ ] **Step 4: Run to verify it passes.** - [ ] **Step 5: Commit** - "The SimPL loop: solve, spread, pull toward the spread, again"

---

## Task 5: Wiring it into the placer

**Files:** `src/placemat/settings.py`, `src/placemat/layout.py`, `skills/placemat/references/api.md`. Test `tests/test_solve_wiring.py`.

**Interfaces:** Settings `solve_enabled: bool = False`, `solve_iterations: int = 200`, `solve_tolerance: float = 1e-6`, `solve_rounds: int = 8`. `Board._global_hints(occ, placed, pending) -> dict[str, Placement]`, computed once per resolve at the first searched item. `metrics.solve` in the run record.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_solve_wiring.py
"""The global solve inside a resolve. Pure: synthetic boards."""
import dataclasses

from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Near, Part
from tests.fixtures import board_geometry, footprint


def _board(enabled):
    fps = [footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("U1", 30, 30, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 32, 34, w=2, h=1, inst="r1", nets=("B", "C")),
           footprint("J2", 45, 20, w=2, h=2, inst="j2", nets=("C", "GND"))]
    b = Board(board_geometry(fps, width=50, height=40), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), solve_enabled=enabled))
    b.place(Part("j1"), at=Location(5, 20))
    b.place(Part("j2"), at=Location(45, 20))
    return b


def test_with_the_solve_on_the_first_searched_item_is_seeded_from_the_netlist():
    b = _board(True)
    b.place(Part("u1"))
    b.place(Part("r1"))
    plan = b.resolve()
    notes = {s.item: s.note for s in plan.steps}
    assert "global solve" in notes["u1"] and "global solve" in notes["r1"]
    assert "nothing it connects to is placed" not in notes["u1"]


def test_an_explicit_near_beats_the_solve():
    b = _board(True)
    b.place(Part("u1"), at=Near(Location(25, 10)))
    b.place(Part("r1"))
    plan = b.resolve()
    assert "global solve" not in {s.item: s.note for s in plan.steps}["u1"]


def test_with_the_solve_off_placement_is_as_it_was():
    def run():
        b = _board(False)
        b.place(Part("u1"))
        b.place(Part("r1"))
        return [(s.item, s.placement) for s in b.resolve().steps]
    assert run() == run()
    b = _board(False)
    b.place(Part("u1"))
    b.place(Part("r1"))
    assert all("global solve" not in s.note for s in b.resolve().steps)


def test_an_item_with_nothing_that_pulls_still_takes_a_pocket():
    fps = [footprint("J1", 5, 20, inst="j1", nets=("A", "GND")),
           footprint("X1", 30, 30, inst="x1", nets=("P", "Q"))]
    b = Board(board_geometry(fps, width=50, height=40), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), solve_enabled=True))
    b.place(Part("j1"), at=Location(5, 20))
    b.place(Part("x1"))
    note = {s.item: s.note for s in b.resolve().steps}["x1"]
    assert "pocket" in note and "global solve" not in note


def test_the_plan_records_what_the_solve_did():
    b = _board(True)
    b.place(Part("u1"))
    b.place(Part("r1"))
    plan = b.resolve()
    assert plan.solve["seeded"] == 2 and plan.solve["rounds"] >= 1
```



- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement.** Add the four settings (and their `api.md` rows). In `Board.resolve` reset `self._solve_hints = None` and `plan.solve = {}`. In the searched path, before `targets`/`_seed_hint`:

```python
        solved = None
        if i.near is None and self.settings.solve_enabled:
            solved = self._global_hints(occ, placed, plan).get(i.key)
        if i.near is not None:
            hint = Placement(_locate(self, occ, i.near), i.rotation, i.face)
        elif solved is not None:
            hint = Placement(solved, i.rotation, i.face)
            seeded = "seeded by the global solve"
        elif targets:
            ...                                     # unchanged
```

and `_global_hints` builds, once per resolve, the pins of every searched intent not yet placed (at its first rotation and face, from `occ.candidate_pad_locations(item, Placement(Location(0, 0), rot, face))`) and of every placed item (from `occ.pad_location`), grouped by net with the `_targets` rule for quiet nets, the weight from `_declared_link`, the region from the occupancy's board box inset by `keep_in`, and the areas from each item's body box; calls `solve.global_solve`; keeps only items with at least one pulling pin; records `plan.solve = {"seeded": n, "rounds": ..., "iterations": ..., "residual": ...}`. The runner copies `plan.solve` into `metrics["solve"]` when it is not empty.

- [ ] **Step 4: Run to verify it passes**, then the whole suite (which also proves the solve-off path unchanged).

- [ ] **Step 5: Commit** - "The global solve's hints, between an explicit Near and the seed"

---

## Task 6: Measure it on a real board

- [ ] On the scratch copy of a real board that has a run ledger, run with the solve off and on (`--keep-going`, same everything else), and compare the two runs on the best-run objective (placed, real DRC, findings, airwire).
- [ ] Record both runs' numbers in the commit message and in the docs as a generic measurement.
- [ ] If the solve wins on the objective, make `solve.enabled` default true and add a migration note saying placement moves; otherwise leave it false and say in the docs that it did not beat the sequential seed on the board measured.

---

## Task 7: Documentation and version

- [ ] `api.md`: a paragraph on the solve beside the placement order text.
- [ ] `SKILL.md`: the scatter-and-pocket symptom and the setting.
- [ ] `migration.md`: `## To 0.20`.
- [ ] Docs test; bump to 0.20.0; full suite; commit.

---

## Acceptance criteria

1. The suite passes, and with `solve.enabled` false every existing placement test passes unchanged.
2. CG solves a known system exactly and reports hitting its cap.
3. One item between two anchors lands at the midpoint; a SHORT link pulls harder; a chain spreads evenly; a pin offset pulls by the pin.
4. Bisection gives each item a cell, keeps order, keeps inside the region, and sizes cells by area.
5. The loop is deterministic, keeps hints inside the board, and never moves an anchor.
6. With the solve on, searched items are seeded by it and say so; an explicit `Near` beats it; an item with nothing pulling still takes a pocket; the plan records what it did.
7. The real-board measurement is run, recorded, and decides the default.
8. Docs carry the settings, the behaviour and `## To 0.20`, with no module, part or board names.
9. No commit mentions Claude, Anthropic or a session.
