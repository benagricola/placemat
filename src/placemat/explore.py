"""Exploring a layout: seeded variants of the placer's own choices for the
items in focus, scored, the best kept. See
docs/superpowers/specs/2026-09-25-explore-design.md."""
from __future__ import annotations

from dataclasses import dataclass, field

from .values import Freedom


@dataclass(frozen=True)
class Explore:
    """One variant: `seed` 0 is the plain placement; `focus` the item keys
    that may vary. How a variant varies - the slack, the swap chance, the
    draw's rank power - is the board's [explore] settings."""
    seed: int = 0
    focus: frozenset = field(default_factory=frozenset)


def explorable(intent) -> bool:
    """An item whose spot the scan chooses: searched from its links or round
    a Near() hint. An edge, a line, a rim, a run or a spoke slides by its own
    rule, and a decided item has nothing to choose."""
    return (intent.freedom is Freedom.SEARCHED and intent.edge is None and intent.run is None
            and intent.rim is None and intent.pin_x is None and intent.pin_y is None
            and intent.angle is None and intent.radius_at is None)


def focus_keys(board, keys=(), after_line: int | None = None, box=None, baseline=None) -> frozenset:
    """The keys of the explorable items in focus: named by key, declared at
    or after a script line, or placed inside `box` by `baseline` (a plan).
    With none of these, every explorable item."""
    pool = {i.key: i for i in board._placements() if explorable(i)}
    chosen = set()
    if keys:
        for k in keys:
            if k not in pool:
                raise KeyError("%s: no searched item by that key (explorable: %s)" % (k, ", ".join(sorted(pool))))
            chosen.add(k)
    if after_line is not None:
        chosen |= {k for k, i in pool.items() if i.line >= after_line}
    if box is not None:
        if baseline is None:
            raise ValueError("a focus box is judged on a plain run's placements: pass baseline=")
        for k in pool:
            try:
                c = baseline.box(k).center
            except (KeyError, AttributeError, TypeError):
                continue
            if box.left <= c.x <= box.right and box.top <= c.y <= box.bottom:
                chosen.add(k)
    if not keys and after_line is None and box is None:
        chosen = set(pool)
    return frozenset(chosen)


def draw(candidates, rng, slack: float, power: float):
    """One of a scan's legal candidates, best first as (score, distance,
    rotation, placement): only those within `slack` of the best (a fraction
    of it; for a best of 0, `slack` millimetres), the one at rank r weighted
    1 / r ** power, so the best stays the likeliest ([explore] slack and
    rank_power)."""
    best = candidates[0][0]
    limit = best * (1.0 + slack) if best > 0 else best + slack
    pool = [c for c in candidates if c[0] <= limit + 1e-12]
    weights = [1.0 / (k + 1) ** power for k in range(len(pool))]
    return rng.choices(pool, weights=weights, k=1)[0]


# ------------------------------------------------------------ scoring
def score(board, plan, step: float | None = None) -> tuple:
    """A variant judged in order: more parts placed, then fewer findings, then
    a less congested worst cell (RUDY), in `step`s so a difference below one
    decides nothing, then less wire - the half-perimeter of the nets that pull
    (planes and free nets do not) plus each declared link's weight times its
    length. The worst cell leads the wire because it is the measure that
    agreed with the router (congestion.py); wire length alone did not.
    `step` 0 leaves the worst cell out."""
    placed = sorted({fp.ref for s in plan.steps if s.placement is not None and s.item in plan._items
                     for fp in _members(plan._items[s.item])})
    quiet = board._plane_nets() | set(board._free_nets)
    pts: dict = {}
    for ref in placed:
        g = plan.occupancy.items.get(ref)
        if g is None:
            continue
        for s in g.shapes:
            if s.kind in ("pad", "through") and s.net and s.net not in quiet:
                pts.setdefault(s.net, []).append(s.box.center)
    wire = 0.0
    for net in sorted(pts):
        p = pts[net]
        if len(p) > 1:
            wire += max(q.x for q in p) - min(q.x for q in p) + max(q.y for q in p) - min(q.y for q in p)
    for l in plan.links:
        if l.achieved_mm is not None and int(l.weight) > 0:
            wire += int(l.weight) * l.achieved_mm
    step = board.settings.explore_congestion_step if step is None else step
    worst = getattr(getattr(plan, "rudy", None), "worst", 0.0) or 0.0
    cell = int(worst / step + 1e-9) if step > 0 else 0
    n_parts = sum(1 for s in plan.steps if s.kind == "part" and s.placement is not None)
    return (-n_parts, len(plan.findings), cell, round(wire, 6))


def _members(item):
    from .board_geometry import members_of
    return members_of(item)


# ------------------------------------------------------------ the search
@dataclass
class ExploreResult:
    best_seed: int
    best: tuple
    baseline: tuple
    tried: int
    results: list          # (seed, score), best first


def explore(make_board, focus, seconds: float, jobs: int | None = None, seeds=None) -> ExploreResult:
    """Resolve variants of `make_board()` (a fresh board per variant, the
    script already declared on it) until `seconds` pass, in `jobs` worker
    processes (None: [explore] jobs, 0 there meaning the CPU count less
    one), and return them scored by the board's [explore] settings, the
    best first. Seed 0 - the plain
    placement - is always tried first; `seeds` fixes the variants to try
    (a count, not a time, for a reproducible answer). Each variant replays
    the plain run's steps before its first focused item."""
    import multiprocessing as mp
    import time
    import os
    base_board = make_board()
    plain = base_board.resolve()
    baseline = score(base_board, plain)
    if jobs is None:
        jobs = base_board.settings.explore_jobs or max(1, (os.cpu_count() or 2) - 1)
    deadline = time.time() + seconds
    order = [s for s in (seeds if seeds is not None else ()) if s != 0]
    fixed = seeds is not None
    ctx = mp.get_context("fork")
    counter = ctx.Value("l", 0)
    out = ctx.Queue()

    def work():
        while True:
            with counter.get_lock():
                k = counter.value
                counter.value += 1
            if fixed:
                if k >= len(order):
                    break
                seed = order[k]
            else:
                if time.time() >= deadline:
                    break
                seed = k + 1
            b = make_board()
            p = b.resolve(reuse=plain.reuse, explore=Explore(seed, frozenset(focus)))
            out.put((seed, score(b, p)))
        out.put(None)

    procs = [ctx.Process(target=work) for _ in range(max(1, jobs))]
    for pr in procs:
        pr.start()
    results, done = [(0, baseline)], 0
    while done < len(procs):
        item = out.get()
        if item is None:
            done += 1
        else:
            results.append(item)
    for pr in procs:
        pr.join()
    results.sort(key=lambda r: (r[1], r[0]))
    return ExploreResult(results[0][0], results[0][1], baseline, len(results), results)
