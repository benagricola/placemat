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


class FocusError(ValueError):
    """A focus that names nothing explorable, with what can be explored."""


def focus_keys(board, keys=(), after_line: int | None = None, box=None, baseline=None) -> frozenset:
    """The keys of the explorable items in focus: named by key, declared at
    or after a script line, or placed inside `box` by `baseline` (a plan).
    With none of these, every explorable item."""
    pool = {i.key: i for i in board._placements() if explorable(i)}
    chosen = set()
    if keys:
        for k in keys:
            if k not in pool and "block " + k in pool:
                k = "block " + k                         # a block named by its anchor, without the prefix
            if k not in pool:
                raise FocusError("nothing searched is called %r: explorable here are %s" % (
                    k, ", ".join(sorted(pool)) or "none (every item's place is decided)"))
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


def explore(make_board, focus, seconds: float, jobs: int | None = None, seeds=None, lock=None) -> ExploreResult:
    """Resolve variants of `make_board()` (a fresh board per variant, the
    script already declared on it) until `seconds` pass, in `jobs` worker
    processes (None: [explore] jobs, 0 there meaning the CPU count less
    one), and return them scored by the board's [explore] settings, the
    best first. Seed 0 - the plain placement - is always tried first;
    `seeds` fixes the variants to try (a count, not a time, for a
    reproducible answer). Each variant replays the plain run's steps before
    its first focused item. With `lock` entries, the plain placement - seed
    0 - is the locked one, and every variant keeps the unfocused items'
    entries.

    Workers are started fresh (spawn), not forked: the parent may hold
    KiCad's threads, and a fork of a threaded process can deadlock. So
    `make_board` must pickle - a module-level function, or an object such
    as BoardFactory - and it may carry a `context()` to enter round each
    variant (the settings binding a script needs)."""
    import multiprocessing as mp
    import os
    import time
    with _context_of(make_board):
        base_board = make_board()
        plain = base_board.resolve(lock=lock)
        baseline = score(base_board, plain)
    if jobs is None:
        jobs = base_board.settings.explore_jobs or max(1, (os.cpu_count() or 2) - 1)
    deadline = time.time() + seconds
    order = [s for s in seeds if s != 0] if seeds is not None else None
    ctx = mp.get_context("spawn")
    counter = ctx.Value("l", 0)
    out = ctx.Queue()
    procs = [ctx.Process(target=_work, args=(make_board, frozenset(focus), lock, plain.reuse, order, deadline,
                                             counter, out)) for _ in range(max(1, jobs))]
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


def _context_of(make_board):
    from contextlib import nullcontext
    ctx = getattr(make_board, "context", None)
    return ctx() if ctx is not None else nullcontext()


def _work(make_board, focus, lock, reuse, order, deadline, counter, out):
    """A worker: take the next seed until the list or the deadline runs out."""
    import time
    try:
        while True:
            with counter.get_lock():
                k = counter.value
                counter.value += 1
            if order is not None:
                if k >= len(order):
                    break
                seed = order[k]
            else:
                if time.time() >= deadline:
                    break
                seed = k + 1
            with _context_of(make_board):
                b = make_board()
                p = b.resolve(reuse=reuse, explore=Explore(seed, focus), lock=lock)
                out.put((seed, score(b, p)))
    finally:
        out.put(None)


@dataclass
class BoardFactory:
    """A board built by running a script against an already-read generated
    board, as a run builds it: what an explore worker needs, in a form it
    can be sent in."""
    script: object
    src: object
    cfg: object
    fab: object
    keep_going: bool
    geometry: object

    def context(self):
        from . import settings as _settings
        return _settings.bind(self.cfg)

    def __call__(self):
        from .runner import scripted_board
        return scripted_board(self.script, self.src, self.cfg, self.fab, self.keep_going, geometry=self.geometry)


# ------------------------------------------------------------ search and accept
def search(make_board, script, seconds: float, jobs: int | None = None, keys=(), after_line=None, box=None,
           accept: bool = False, seeds=None, release: str = "") -> tuple:
    """What `--explore` does: read the script's lock, choose the focus, run
    the variants, and report what the best would move against the current
    placement. With `accept`, write the best's decisions for the focused
    items to the lock (merged with the entries for other items). Returns
    (report, entries): the entries a run should now resolve with."""
    from . import lock as _lock
    path = _lock.path_for(script)
    entries = _lock.read(path)
    with _context_of(make_board):
        base = make_board()
        current = base.resolve(lock=entries)
    focus = focus_keys(base, keys, after_line, box, baseline=current)
    if not focus:
        return {"tried": 0, "focus": [], "baseline": list(score(base, current)), "best": list(score(base, current)),
                "best_seed": 0, "moves": [], "accepted": False, "empty": True}, entries
    result = explore(make_board, focus, seconds, jobs, seeds=seeds, lock=entries)
    report = {"tried": result.tried, "focus": sorted(focus), "baseline": list(result.baseline),
              "best": list(result.best), "best_seed": result.best_seed, "moves": [], "accepted": False}
    if result.best_seed == 0:
        return report, entries
    with _context_of(make_board):
        board = make_board()
        best = board.resolve(explore=Explore(result.best_seed, frozenset(focus)), lock=entries)
    for key in sorted(focus):
        was, now = current.placement(key), best.placement(key)
        if was is None or now is None:
            if was != now:
                report["moves"].append({"key": key, "mm": None, "rotation": [getattr(was, "rotation", None),
                                                                              getattr(now, "rotation", None)]})
            continue
        d = was.location.distance(now.location)
        if d > 1e-6 or was.rotation != now.rotation:
            report["moves"].append({"key": key, "mm": round(d, 3), "rotation": [was.rotation, now.rotation]})
    if accept:
        placed = [k for k in focus if best.placement(k) is not None]
        new = _lock.entries(board, best, placed, release)
        kept = [e for e in entries if e.key not in focus]
        entries = _lock.renumber(kept + new, best)
        _lock.write(path, entries)
        report["accepted"] = True
    return report, entries


# ------------------------------------------------------------ the runner's side
@dataclass(frozen=True)
class ExploreOptions:
    """What --explore and its flags asked for."""
    seconds: float
    keys: tuple = ()
    after_line: int | None = None
    box: object = None
    jobs: int | None = None
    accept: bool = False


def before_resolve(script, board, make_board, options, say) -> tuple:
    """The lock entries a run resolves with, and the explore report when
    --explore was given (else None): the search runs first, and with
    --accept its decisions are in the entries returned."""
    from . import __version__
    from . import lock as _lock
    if options is None:
        return _lock.read(_lock.path_for(script)), None
    import time
    t0 = time.time()
    report, entries = search(make_board, script, options.seconds, options.jobs, options.keys,
                             options.after_line, options.box, options.accept, release=__version__)
    report["seconds"] = round(time.time() - t0, 1)
    for line in report_lines(report):
        say("explore", line)
    return entries, report


def report_lines(report) -> list:
    b, a = report["baseline"], report["best"]
    if report.get("empty"):
        return ["nothing to explore: no searched item is in focus (every item's place is decided, or the focus "
                "names none)"]
    head = "%d variants in %.0f s over %d focused item%s" % (
        report["tried"], report.get("seconds", 0.0), len(report["focus"]), "" if len(report["focus"]) == 1 else "s")
    if not report["best_seed"]:
        return [head + ": no variant scored better than the current placement"]
    lines = [head + ": placed %d -> %d, findings %d -> %d, worst cell %d -> %d steps, wire %.1f -> %.1f mm; "
             "%d item%s would move" % (-b[0], -a[0], b[1], a[1], b[2], a[2], b[3], a[3], len(report["moves"]),
                                      "" if len(report["moves"]) == 1 else "s")]
    for m in report["moves"]:
        turn = "" if m["rotation"][0] == m["rotation"][1] else ", rotation %s -> %s" % tuple(
            "-" if r is None else "%g" % r for r in m["rotation"])
        lines.append("  %s: %s%s" % (m["key"], "placed/unplaced" if m["mm"] is None else "%.2f mm" % m["mm"], turn))
    lines.append("accepted: written to the lock" if report["accepted"] else "not accepted: --accept writes it to the lock")
    return lines


def lock_summary(plan) -> str:
    """How the lock fared in a plan: held, drifted, released, from its notes."""
    held = sum(1 for s in plan.steps if "held by lock" in (s.note or ""))
    drifted = sum(1 for s in plan.steps if "lock: drifted" in (s.note or ""))
    released = sum(1 for s in plan.steps if "lock: released" in (s.note or ""))
    if not (held or drifted or released):
        return ""
    return "%d held by lock, %d drifted, %d released" % (held, drifted, released)
