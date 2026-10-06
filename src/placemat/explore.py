"""Exploring a layout: seeded variants of the placer's own choices for the
items in focus, scored, the best kept. See
docs/superpowers/specs/2026-09-25-explore-design.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import lock as _lock
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
    return (intent.freedom is Freedom.SEARCHED and not intent.turns_on_point
            and intent.edge is None and intent.run is None
            and intent.rim is None and intent.pin_x is None and intent.pin_y is None
            and intent.angle is None and intent.radius_at is None
            and intent.tangent is None and intent.band is None)


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
def measure(board, plan, step: float | None = None) -> dict:
    """A variant's measures for the run score (score.py): its own ratsnest's
    crossings and airwire, and the worst RUDY cell in `step`s, the measure
    that agreed with the router (congestion.py). `step` 0 leaves the worst
    cell out."""
    from . import score as _score
    step = board.settings.explore_congestion_step if step is None else step
    return _score.plan_measures(board, plan, congestion_step=step or None)


def score(board, plan, step: float | None = None) -> float:
    """A variant's run score, in millimetres: lower is better."""
    from . import score as _score
    return _score.total(measure(board, plan, step), board.settings)


def _members(item):
    from .board_geometry import members_of
    return members_of(item)


# ------------------------------------------------------------ the search
@dataclass
class ExploreResult:
    best_seed: int
    best: float            # the run score, mm
    baseline: float
    tried: int
    results: list          # (seed, score, measures), best first
    best_measures: dict = None
    baseline_measures: dict = None
    seconds: float = 0.0   # spent, over every session of a resumed explore
    failures: list = field(default_factory=list)    # a worker that died or raised, as a sentence (a traceback for a raise)
    stopped: bool = False
    variants: list = None          # {seed, score, measures, placements, order, t} for each of this session, in the order they finished
    focus: list = None
    jobs: int = 0
    plain: dict = None
    plain_order: list = None
    curve: list = None             # {i, seed, t, score, best} for every variant in the order it finished, over every session
    ended: dict = None             # why it ended: {"rule": "budget" | "stall_count" | "stall_time" | "hard_clear" | "signal", ...}
    routes: list = None            # with routing: each route's entry (_route_work), in the order they came


class StopRule:
    """The rules that end an explore before its budget (the [explore] stall settings): `variants` finished without an
    improvement, `seconds` since the last improvement, or - when the plain placement had hard terms - a variant that has
    none. Fed each finished variant by `see` (and the clock by `tick`); returns the rule that fired, or None."""

    def __init__(self, variants: int = 0, seconds: float = 0.0, hard: bool = False, baseline_hard_clear: bool = True):
        self.variants, self.seconds = int(variants or 0), float(seconds or 0.0)
        self.hard = bool(hard) and not baseline_hard_clear
        self.since, self.best_t = 0, 0.0

    @property
    def active(self) -> bool:
        return bool(self.variants or self.seconds or self.hard)

    def see(self, t: float, improved: bool, hard_clear: bool):
        if improved:
            self.since, self.best_t = 0, t
        else:
            self.since += 1
        if self.hard and hard_clear:
            return "hard_clear"
        if self.variants and self.since >= self.variants:
            return "stall_count"
        return self.tick(t)

    def tick(self, t: float):
        if self.seconds and t - self.best_t >= self.seconds:
            return "stall_time"
        return None

    def detail(self, rule: str, t: float) -> dict:
        if rule == "stall_count":
            return {"rule": rule, "limit": self.variants, "after": self.since}
        if rule == "stall_time":
            return {"rule": rule, "limit": self.seconds, "after": round(t - self.best_t, 3)}
        return {"rule": rule}


def duration(s: float) -> str:
    """Seconds as a person says them: 4 s, 5 min 12 s, 43 min, 1 h 02 min."""
    s = int(round(s))
    if s < 60:
        return "%d s" % s
    if s < 600 or (s < 3600 and s % 60):
        m, r = divmod(s, 60)
        return "%d min %d s" % (m, r) if r else "%d min" % m
    if s < 3600:
        return "%d min" % round(s / 60)
    h, m = divmod(round(s / 60), 60)
    return "%d h %02d min" % (h, m)


def _found(curve, seconds: float):
    """When the best was found: the last improving entry of the curve."""
    best = [c for c in curve if c["best"]][-1]
    return {"i": best["i"], "seed": best["seed"], "t": best["t"], "score": best["score"], "of_variants": len(curve),
            "of_seconds": round(seconds, 3)}


def _compact(curve, cap: int = 2000):
    """The curve as kept in a report: all of it, or - past `cap` entries - every improvement and an even sample."""
    if len(curve) <= cap:
        return curve
    step = -(-len(curve) // cap)
    return [c for k, c in enumerate(curve) if c["best"] or k % step == 0]


@dataclass(frozen=True)
class Routing:
    """What an explore's routing worker needs (`explore(routing=)`): the folder its variants are written in, the nets
    left out of their routes, route_board's `resume`, and the board writer and router (VariantRouter; a test's stand-in)."""
    folder: Path
    exclude: tuple = ()
    resume: bool = True
    router: object = None


class VariantRouter:
    """How the routing worker writes a variant's board and routes it: as a run writes its own (`_write_variant`), and
    placemat's quick route."""

    def write(self, make_board, board, plan, folder):
        return _write_variant(make_board, board, plan, folder)

    def route(self, pcb, work, exclude_nets=(), quick=True, resume=True):
        from .kicad import route as route_mod
        return route_mod.route_board(pcb, work, exclude_nets=exclude_nets, quick=quick, resume=resume)


def explore(make_board, focus, seconds: float, jobs: int | None = None, seeds=None, lock=None,
            checkpoint=None, routing: Routing | None = None) -> ExploreResult:
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
    variant (the settings binding a script needs).

    A worker that raises sends its traceback, and one that is killed from
    outside (the out-of-memory killer) is noticed by its exit code; both are
    in `failures` and the others carry on. When the process is stopped
    (stop.Stopped) the workers are ended and the exception, carrying the
    partial result as `.partial`, goes on up. `checkpoint` (checkpoint.py)
    is told of the baseline, every variant and each new best as they come.

    With `routing`, a routing worker process (`_route_work`) quick-routes the
    plain placement first, then each new best by run score as it comes; while
    it routes, only the latest new best waits, and a best overtaken before
    its route starts is not routed. It takes one of the `jobs`; with one job
    the search has it, and the routes run after the search. When the search
    ends the worker finishes the route in hand and the one waiting. Each
    route is said, sent as an `explore_route` event and kept in `routes`; one
    that fails, or a worker that dies, is an entry with its `error`."""
    import multiprocessing as mp
    import os
    import queue
    import time
    from . import stop
    from .console import console
    t0 = time.time()
    prior = checkpoint.load() if checkpoint is not None else None
    if prior is not None:
        console.say("explore", "resuming a saved explore: %d variants in %.0f s so far%s" % (
            len(prior.done) + 1, prior.spent, "" if not prior.best_seed else ", best seed %d" % prior.best_seed))
    elif checkpoint is not None and checkpoint.discarded:
        console.say("explore", "a saved explore was not continued: %s changed since it began" % " and ".join(
            checkpoint.discarded))
    with _context_of(make_board):
        base_board = make_board()
        plain = base_board.resolve(lock=lock)
        if prior is None:
            base_m = measure(base_board, plain)
            baseline = _total(base_board, base_m)
        else:                                   # the baseline is the saved one: it is the same board and settings
            baseline, base_m = prior.baseline, prior.measures
    if jobs is None:
        jobs = base_board.settings.explore_jobs or max(1, (os.cpu_count() or 2) - 1)
    route_after = routing is not None and jobs <= 1          # one job: the search has it, the routes come after
    if routing is not None and not route_after:
        jobs -= 1                                            # the routing worker's
    done_before = dict(prior.done) if prior is not None else {}
    spent = prior.spent if prior is not None else 0.0
    if checkpoint is not None and prior is None:
        checkpoint.start(baseline, base_m, seconds, seeds)
    deadline = t0 + max(0.0, seconds - spent)
    order = [s for s in seeds if s != 0 and s not in done_before] if seeds is not None else None
    nothing_left = (not order) if order is not None else deadline <= time.time()
    ctx = mp.get_context("spawn")
    counter = ctx.Value("l", 0)
    halt = ctx.Value("b", 0)                       # a stopping rule fired: the workers take no more seeds
    best_val = ctx.Value("d", min([baseline] + [r[1] for r in done_before.values()]))
    out = ctx.Queue()
    untried = _untried(done_before)
    procs = [ctx.Process(target=_work, args=(k, make_board, frozenset(focus), lock, plain.reuse, order, deadline,
                                             counter, out, best_val, baseline, os.getpid(), untried, halt), daemon=True)
             for k in range(0 if nothing_left else max(1, jobs))]
    results = {0: (0, baseline, base_m)}
    results.update(done_before)
    failures, ended = [], set()
    from . import channel
    rep = channel.current()
    variants = [{"seed": 0, "score": baseline, "measures": base_m, "placements": _placements(plain, focus),
                 "order": _order(plain, focus), "t": 0.0, "i": 0, "best": True}]
    from . import score as _score
    rule = StopRule(base_board.settings.explore_stall_variants, base_board.settings.explore_stall_seconds,
                    base_board.settings.explore_stop_hard_clear, _score.hard_clear(base_m))
    curve = [{"i": 0, "seed": 0, "t": 0.0, "score": baseline, "best": True}]
    best_so_far = [baseline]

    def note(seed, total, t):
        """A finished variant on the curve; whether it beat every one before it."""
        better = total < best_so_far[0] - 1e-9
        if better:
            best_so_far[0] = total
        curve.append({"i": len(curve), "seed": seed, "t": round(t, 3), "score": total, "best": better})
        return better
    for seed_, score_, t_ in (prior.curve if prior is not None else ()):
        note(seed_, score_, t_)
        rule.see(t_, curve[-1]["best"], False)
    fired = []                                      # [{"rule": ...}] once a rule has ended it
    ended_by = lambda: fired[0] if fired else {"rule": "budget"}
    routes = []
    rq = ctx.Queue() if routing is not None else None
    rproc = ctx.Process(target=_route_work, args=(make_board, frozenset(focus), lock, plain.reuse, routing, rq, out,
                                                  os.getpid()), daemon=True, name="explore-router") \
        if routing is not None else None
    rs = {"inflight": None, "pending": None, "started": False, "dead": False}
    partial = lambda: _result(results, baseline, base_m, spent + time.time() - t0, failures, variants, focus, len(procs),
                              curve, ended_by(), list(routes) if routing is not None else None)

    def dispatch():
        """The waiting best to the routing worker, when it is free."""
        if rs["started"] and not rs["dead"] and rs["inflight"] is None and rs["pending"] is not None:
            rq.put(rs["pending"])
            rs["inflight"], rs["pending"] = rs["pending"], None

    def start_router():
        rproc.start()
        rs["started"] = True
        rq.put(0)                                    # the plain placement first: the baseline the others are judged by
        rs["inflight"] = 0
        dispatch()

    def routed(seed, entry):
        total = results[seed][1] if seed in results else baseline
        entry = {"seed": seed, "score": round(total, 1), **{k: v for k, v in entry.items() if k != "seed"}}
        routes.append(entry)
        rs["inflight"] = None
        console.say("explore", route_line(entry))
        dispatch()
        if rep is not None:
            rep.send({"ev": "explore_route", **entry})

    def router_gone():
        """A routing worker that died with a route in hand: that route, and the one waiting, are entries that say so."""
        if not rs["started"] or rs["dead"] or rproc.is_alive():
            return
        try:
            while True:
                take(out.get_nowait())
        except queue.Empty:
            pass
        if rs["inflight"] is None and rs["pending"] is None:
            return
        code = rproc.exitcode
        why = "was killed by signal %d (%s)" % (-code, _signame(-code)) if code is not None and code < 0 else \
            "exited with code %s" % code
        rs["dead"] = True
        for seed in (rs["inflight"], rs["pending"]):
            if seed is not None:
                rs["inflight"] = seed
                routed(seed, {"seed": seed, "dir": str(routing.folder / ("seed-%d" % seed)), "seconds": 0.0,
                              "error": {"type": "WorkerDied", "message": "the routing worker %s before this route "
                                        "finished" % why}})
        rs["inflight"] = rs["pending"] = None
    try:
        for pr in procs:
            pr.start()
        if routing is not None and not route_after and procs:
            start_router()
        if rep is not None:
            rep.send({"ev": "explore", "focus": sorted(focus), "seconds": seconds, "jobs": len(procs),
                      "seeds": None if order is None else len(order), "baseline": baseline,
                      "baseline_measures": base_m, "plain": variants[0]["placements"], "order": variants[0]["order"],
                      "at": t0})

        def take(msg):
            if msg[0] == "end":
                ended.add(msg[1])
            elif msg[0] == "route":
                routed(msg[1], msg[2])
            elif msg[0] == "rend":
                pass
            elif msg[0] == "err":
                failures.append("worker %d raised:\n%s" % (msg[1], msg[2].rstrip()))
                console.say("explore", "worker %d raised: %s" % (msg[1], failures[-1].splitlines()[-1]), level="fail")
            else:
                _, seed, total, m, payload, dt, extra = msg
                results[seed] = (seed, total, m)
                now = spent + time.time() - t0
                better = note(seed, total, now)
                v = {"seed": seed, "score": total, "measures": m, **extra, "t": round(now, 3), "i": curve[-1]["i"], "best": better}
                variants.append(v)
                if rep is not None:
                    rep.send({"ev": "variant", **v})
                if better and routing is not None:
                    rs["pending"] = seed                     # the latest new best waits; one it overtakes is not routed
                    dispatch()
                if checkpoint is not None:
                    checkpoint.variant(seed, total, m, now, payload)
                if rule.active and not fired:
                    why = rule.see(now, better, _score.hard_clear(m))
                    if why:
                        fired.append(rule.detail(why, now))
                        halt.value = 1
        while len(ended) < len(procs):
            try:
                take(out.get(timeout=1.0))
                continue
            except queue.Empty:
                pass
            if rule.active and not fired:
                why = rule.tick(spent + time.time() - t0)
                if why:
                    fired.append(rule.detail(why, spent + time.time() - t0))
                    halt.value = 1
            router_gone()
            for k, pr in enumerate(procs):
                if k in ended or pr.is_alive():
                    continue
                try:                                  # what it sent before it went
                    while True:
                        take(out.get_nowait())
                except queue.Empty:
                    pass
                if k not in ended:
                    ended.add(k)
                    code = pr.exitcode
                    if code is not None and code < 0:
                        why = "was killed by signal %d (%s), out of memory perhaps" % (-code, _signame(-code))
                    else:
                        why = "exited with code %s" % code
                    failures.append("worker %d %s without finishing" % (k, why))
                    console.say("explore", failures[-1], level="fail")
        if routing is not None:                      # the search is done: the route in hand and the one waiting
            if not rs["started"]:
                start_router()
            while rs["inflight"] is not None or (rs["pending"] is not None and not rs["dead"]):
                try:
                    take(out.get(timeout=1.0))
                    continue
                except queue.Empty:
                    pass
                router_gone()
            if not rs["dead"]:
                rq.put(None)
                rproc.join(5.0)
    except stop.Stopped as s:
        s.partial = partial()
        s.partial.stopped = True
        s.partial.ended = {"rule": "signal", "signal": s.name, **({"cause": s.cause["cause"]} if s.cause else {})}
        if checkpoint is not None:
            checkpoint.stopped(s.label, s.partial.seconds)
        raise
    finally:
        _end(procs + ([rproc] if rs["started"] else []))
        out.close()
        out.cancel_join_thread()
    result = partial()
    if checkpoint is not None:
        checkpoint.done(result.seconds, result.best_seed, result.ended)
    return result


def _signame(n: int) -> str:
    import signal
    try:
        return signal.Signals(n).name
    except ValueError:
        return "signal %d" % n


def _end(procs) -> None:
    """Stop the workers still running, without waiting on them long."""
    import time
    for pr in procs:
        if pr.is_alive():
            pr.terminate()
    t = time.time() + 0.5
    for pr in procs:
        if pr.pid is not None:
            pr.join(max(0.0, t - time.time()))
    for pr in procs:
        if pr.is_alive():
            pr.kill()
            pr.join(0.5)


def _result(results: dict, baseline, base_m, seconds: float, failures, variants=None, focus=(), jobs=0, curve=None,
            ended=None, routes=None) -> ExploreResult:
    rows = sorted(results.values(), key=lambda r: (r[1], r[0]))
    return ExploreResult(rows[0][0], rows[0][1], baseline, len(rows), rows, rows[0][2], base_m, round(seconds, 3),
                         list(failures), variants=variants, focus=sorted(focus), jobs=jobs,
                         plain=variants[0]["placements"] if variants else None,
                         plain_order=variants[0]["order"] if variants else None, curve=list(curve) if curve else None,
                         ended=ended, routes=routes)


def _untried(done: dict):
    """The seeds, in order, a time-boxed explore tries: 1, 2, 3 ... but not
    those already tried (a resumed explore). Returns (the gaps below the
    highest tried, that highest)."""
    top = max(done) if done else 0
    return [s for s in range(1, top + 1) if s not in done], top


def _total(board, m) -> float:
    from . import score as _score
    return _score.total(m, board.settings)


def _context_of(make_board):
    from contextlib import nullcontext
    ctx = getattr(make_board, "context", None)
    return ctx() if ctx is not None else nullcontext()


def _placements(plan, focus) -> dict:
    """{key: [x, y, rotation, face, arrangement] or None} for the focused items: where a variant put them, and the arrangement
    a cell stands in ("" its module's own; a record from before arrangements has four elements)."""
    out = {}
    for key in sorted(focus):
        p = plan.placement(key)
        out[key] = None if p is None else [round(p.location.x, 3), round(p.location.y, 3), round(p.rotation, 3), p.face.value, p.arrangement]
    return out


def _order(plan, focus) -> list:
    seen, out = set(), []
    for s in plan.steps:
        if s.item in focus and s.placement is not None and s.item not in seen:
            seen.add(s.item)
            out.append(s.item)
    return out


def _work(idx, make_board, focus, lock, reuse, order, deadline, counter, out, best_val, baseline, parent, untried, halt):
    """A worker: take the next seed until the list or the deadline runs out,
    and say so: a variant's result, a traceback if one raises, and that it
    has ended. It does not outlive its parent, and leaves the stopping to it
    (a Ctrl-C goes to every process of the terminal's group)."""
    import signal
    import time
    import traceback
    from . import channel, stop
    channel.disable()                                   # the parent reports for the explore, not each variant's resolve
    from . import timecap
    timecap.disable()                                   # and holds the time cap: a variant's steps are not timed
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    stop.parent_death_signal()
    import os
    if os.getppid() != parent:
        return
    gaps, top = untried
    try:
        while True:
            if halt.value:
                break
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
                seed = gaps[k] if k < len(gaps) else top + 1 + k - len(gaps)
            t0 = time.time()
            with _context_of(make_board):
                b = make_board()
                p = b.resolve(reuse=reuse, explore=Explore(seed, focus), lock=lock)
                m = measure(b, p)
                total = _total(b, m)
                with best_val.get_lock():
                    if total <= best_val.value and total < baseline - 1e-9:
                        best_val.value = total
                payload = _payload(b, p, focus)     # every variant carries its lock entries: any of them can be accepted
            out.put(("v", seed, total, m, payload, round(time.time() - t0, 3),
                     {"placements": _placements(p, focus), "order": _order(p, focus)}))
    except BaseException:
        out.put(("err", idx, traceback.format_exc()))
    finally:
        out.put(("end", idx))


def _route_work(make_board, focus, lock, reuse, routing, rq, out, parent):
    """The routing worker: take a seed from `rq` until None, resolve that variant (seed 0 the plain placement), write
    its board in its own folder (`routing.folder`/seed-S) and quick-route it there, the plane nets and `routing.exclude`
    left out, and send its entry {"seed", "dir", "seconds", and "closure_clean", "closure", "open_before", "open_after",
    "valid", or "error" {"type", "message"}}. A process of its own, as the search's workers are: KiCad's writer runs on
    its main thread, and it reports nothing to the command's readers (channel.disable, as channel.paused does in a run's
    own process). A SIGTERM ends it and the router it is running."""
    import os
    import signal
    import time
    from . import channel, stop, timecap
    channel.disable()
    timecap.disable()
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    def ended(signum, frame):
        raise SystemExit(128 + signum)                  # subprocess.run kills the router on the way out
    signal.signal(signal.SIGTERM, ended)
    stop.parent_death_signal()
    if os.getppid() != parent:
        return
    router = routing.router if routing.router is not None else VariantRouter()
    try:
        while True:
            seed = rq.get()
            if seed is None:
                break
            d = Path(routing.folder) / ("seed-%d" % seed)
            entry = {"seed": seed, "dir": str(d)}
            t0 = time.perf_counter()
            try:
                with _context_of(make_board):
                    b = make_board()
                    p = b.resolve(reuse=reuse, lock=lock) if seed == 0 else \
                        b.resolve(reuse=reuse, explore=Explore(seed, focus), lock=lock)
                    pcb = router.write(make_board, b, p, d)
                    r = router.route(pcb, d / "route", exclude_nets=set(p.plane_nets) | set(routing.exclude), quick=True,
                                     resume=routing.resume)
                entry.update(closure_clean=r.closure_clean, closure=r.closure, open_before=r.open_before,
                             open_after=r.open_after, valid=r.valid)
            except Exception as e:
                entry["error"] = {"type": type(e).__name__, "message": str(e)}
            entry["seconds"] = round(time.perf_counter() - t0, 3)
            out.put(("route", seed, entry))
    finally:
        out.put(("rend",))


def _payload(board, plan, focus) -> dict:
    """What accepting this variant writes, without resolving it again: the
    lock entries for the focused items it placed, and the order its plan
    placed every item in (what merging them with the other entries
    renumbers by)."""
    from dataclasses import asdict
    from . import lock as _lock
    placed = [k for k in focus if plan.placement(k) is not None]
    return {"entries": [asdict(e) for e in _lock.entries(board, plan, placed)],
            "orders": {k: v["order"] for k, v in plan.turns.items()}}


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
        board = scripted_board(self.script, self.src, self.cfg, self.fab, self.keep_going, geometry=self.geometry)
        board.pin_study = False             # a variant is studied by the explore, on its best ones (`_pin_maps`)
        return board


# ------------------------------------------------------------ search and accept
def _script_digest(script) -> str:
    """What the script is, for a saved explore to say it still is: its text,
    its imports and its lock and routes files (project.script_fingerprint)."""
    from . import checkpoint
    from .project import script_fingerprint
    try:
        return checkpoint.sha(script_fingerprint(script, with_lock=False))
    except OSError:
        return ""


def _parts(script, base, make_board, entries, focus) -> dict:
    """What a variant is made of, digested, by what each is called in a
    checkpoint (checkpoint.PARTS): a saved explore continues only when every
    one is the same."""
    import json
    from . import __version__, checkpoint
    from . import reuse as _reuse
    settings = json.loads(_reuse.placement_settings(base.settings))
    for k in [k for k in settings if k in ("explore_jobs", "explore_checkpoint_max_variants", "explore_stall_variants",
                                                          "explore_stall_seconds", "explore_stop_hard_clear")]:
        del settings[k]                                 # how many workers, how long a checkpoint: not what a variant is
    fab = getattr(make_board, "fab", None)
    return {"script": _script_digest(script), "board": checkpoint.sha(_reuse._geometry_digest(base.geometry)),
            "settings": checkpoint.sha(json.dumps(settings, sort_keys=True)),
            "fab": checkpoint.sha(fab.json()) if fab is not None else "", "version": __version__,
            "lock": checkpoint.lock_digest(entries), "focus": checkpoint.sha(",".join(sorted(focus)))}


def _shown(script) -> str:
    """The script as a command line names it: relative to here when it is under here."""
    import os
    import shlex
    path = os.path.abspath(str(script))
    rel = os.path.relpath(path)
    return shlex.quote(rel if not rel.startswith("..") else path)


def accept_command(script, seed: int) -> str:
    """The command that writes a saved explore's best variant to the lock."""
    return "placemat lock %s --accept-seed %d" % (_shown(script), seed)


def _write_lock(path, entries, focus, new, plan) -> list:
    """The lock file, with the entries `new` for the focused items in place
    of the old ones (the others kept), renumbered in the order `plan` placed
    them. Returns the entries written."""
    kept = [e for e in entries if e.key not in focus]
    merged = _lock.renumber(kept + new, plan)
    _lock.write(path, merged)
    return merged


def search(make_board, script, seconds: float, jobs: int | None = None, keys=(), after_line=None, box=None,
           accept: bool = False, seeds=None, release: str = "", run_id: str = "", checkpoint_dir=None,
           resume: str = "auto", keep_state: bool = False, route_best: bool | None = None, variants_dir=None,
           route_exclude=(), route_resume: bool = True, router=None) -> tuple:
    """What `--explore` does: read the script's lock, choose the focus, run
    the variants, and report what the best would move against the current
    placement. With `accept`, write the best's decisions for the focused
    items to the lock (merged with the entries for other items). Returns
    (report, entries): the entries a run should now resolve with.

    `checkpoint_dir` is where the explore keeps its state (checkpoint.py): a
    saved explore of this script that is this one - the same script, board,
    settings, fab profile, version, lock and focus - is continued
    (`resume` "auto"; "yes" refuses when it is not this one, saying what
    changed; "no" starts over). It is cleared when the explore is complete,
    unless `keep_state`: the caller clears it (checkpoint.finish_dir) once
    the result is recorded. When the process is stopped, the best so far is reported and kept there,
    nothing is written to the lock whatever `accept` says - the decision is
    the user's - and the stop goes on up with the report as `.explore`.

    `route_best` (None: [explore] route_best) quick-routes the plain placement and each new best as the search finds
    them, each on its own board written in `variants_dir` (explore's `routing`, `router` the board writer and router);
    with routes, the variant taken - reported as `taken_seed`, its moves the report's, and what `accept` writes - is the
    best clean closure, ties going to the better score, and the best score when every route failed. Without
    `variants_dir` (a preview) nothing is routed and the report says so. `route_resume` False routes every stage of
    those routes again (`placemat run --no-resume`). A stop keeps the routes done in the report and sends an
    `explore_done` event that keeps nothing."""
    from . import checkpoint as _checkpoint
    from . import stop
    path = _lock.path_for(script)
    entries = _lock.read(path)
    with _context_of(make_board):
        base = make_board()
        current = base.resolve(lock=entries)
    focus = focus_keys(base, keys, after_line, box, baseline=current)
    if not focus:
        now = score(base, current)
        return {"tried": 0, "focus": [], "baseline": now, "best": now,
                "best_seed": 0, "moves": [], "accepted": False, "empty": True}, entries
    ck = None
    if checkpoint_dir is not None:
        ck = _checkpoint.Checkpoint(checkpoint_dir, _parts(script, base, make_board, entries, focus), focus, resume,
                                    base.settings.explore_checkpoint_max_variants)
    on = base.settings.explore_route_best if route_best is None else bool(route_best)
    routing = Routing(Path(variants_dir), tuple(route_exclude), route_resume, router) \
        if on and variants_dir is not None else None
    try:
        result = explore(make_board, focus, seconds, jobs, seeds=seeds, lock=entries, checkpoint=ck, routing=routing)
    except stop.Stopped as s:
        now = score(base, current)
        r = s.partial or ExploreResult(0, now, now, 0, [], seconds=0.0)       # stopped before a variant was begun
        report = {"tried": r.tried, "focus": sorted(focus), "baseline": r.baseline, "best": r.best,
                  "best_seed": r.best_seed, "moves": [], "accepted": False, "stopped": s.label,
                  "seconds": round(r.seconds, 1), "failures": r.failures}
        if r.curve:
            report.update(curve=_compact(r.curve), found=_found(r.curve, r.seconds), ended=r.ended)
        if ck is not None and _checkpoint.saved(ck.dir, r.best_seed):
            report["accept"] = accept_command(script, r.best_seed)
        if r.routes is not None:
            report["routes"] = r.routes
            _send_done(report, kept=False, stopped=s.label)
        s.explore, s.stage = report, "explore"
        stop.say(stopped_line(report), both=False)
        raise
    report = {"tried": result.tried, "focus": sorted(focus), "baseline": result.baseline, "seconds": round(result.seconds, 1),
              "best": result.best, "best_seed": result.best_seed, "moves": [], "accepted": False,
              "terms": _moved_terms(base, result.baseline_measures, result.best_measures)}
    report.update(curve=_compact(result.curve), found=_found(result.curve, result.seconds), ended=result.ended)
    if result.failures:
        report["failures"] = result.failures
    saved = (lambda seed: _checkpoint.saved(ck.dir, seed)) if ck is not None else (lambda seed: False)
    taken = result.best_seed
    if on and variants_dir is None:
        report["routes"], report["routes_skipped"] = [], "no_board"
    elif on:
        report["routes"] = result.routes
        closed = _taken(result.routes, {r[0]: r[1] for r in result.results})
        if closed is not None:
            taken = report["taken_seed"] = closed
    if saved(taken):
        report["accept"] = accept_command(script, taken)
    have = {0: (base, current)}
    if result.best_seed:
        _variant(make_board, entries, focus, result.best_seed, have)
    if taken:
        board, chosen = _variant(make_board, entries, focus, taken, have)
        for key in sorted(focus):
            m = _move_of(key, current.placement(key), chosen.placement(key))
            if m:
                report["moves"].append(m)
    # before the accept: the variants are studied under the lock they were ranked under
    _study(report, make_board, entries, focus, result, have)
    if accept and taken:
        placed = [k for k in focus if chosen.placement(k) is not None]
        total = next(r[1] for r in result.results if r[0] == taken)
        new = _lock.entries(board, chosen, placed, release, run_id, round(total, 1))
        entries = _write_lock(path, entries, focus, new, chosen)
        report["accepted"] = True
        if ck is not None:
            ck.best_path.unlink(missing_ok=True)         # taken: it would not match the lock now
    _write_record(script, result, report, run_id, have[taken])
    if ck is not None and not keep_state:
        ck.finish()
    return report, entries


def _variant(make_board, entries, focus, seed: int, have: dict) -> tuple:
    """(board, plan) of a variant: the one in `have`, or resolved again (a seed is deterministic) and kept there."""
    if seed not in have:
        with _context_of(make_board):
            board = make_board()
            have[seed] = (board, board.resolve(explore=Explore(seed, frozenset(focus)), lock=entries))
    return have[seed]


def _write_variant(make_board, board, plan, folder: Path) -> Path:
    """The variant's board, written as a run writes its own: the plan applied to a copy of the board `pcb layout`
    generated (the cached generation, as an arrangement's board is), in `folder` as layout.kicad_pcb with its project and
    rules beside it. Returns the board's path."""
    from .arrangement_run import scratch_board
    from .kicad.write import apply_plan, finish_board
    from .runner import cached_generation
    src = make_board.src
    pcb = scratch_board(cached_generation(src) / src.pcb.name, folder)
    apply_plan(pcb, plan)
    finish_board(pcb, make_board.fab, refs_to_fab=getattr(board, "refs_on_fab", True))
    return pcb


def _taken(routes: list, scores: dict):
    """The seed of the routed variant with the best clean closure, the better run score (`scores`, {seed: score}) of a
    tie; None when every route failed."""
    closed = [r for r in routes if "error" not in r]
    if not closed:
        return None
    return min(closed, key=lambda r: (-r["closure_clean"], scores.get(r["seed"], r["score"]), r["seed"]))["seed"]


def _send_done(report, kept: bool, **more) -> None:
    """The `explore_done` event of an explore that left no record (a stop): its result as far as it got."""
    from . import channel
    rep = channel.current()
    if rep is not None:
        rep.send({"ev": "explore_done", "best_seed": report["best_seed"], "best": report["best"], "baseline": report["baseline"],
                  "tried": report["tried"], "kept": kept, "found": report.get("found"), "ended": report.get("ended"),
                  "pin_maps": [], **_routed(report), **more})


def _study(report, make_board, entries, focus, result, have: dict) -> None:
    """`report["pin_maps"]` from `_pin_maps`. A stop during the study is a stop of the explore, as one during its
    search: the report goes up with it as `.explore`, said, with nothing accepted."""
    from . import stop
    try:
        report["pin_maps"] = _pin_maps(make_board, entries, focus, result, have)
    except stop.Stopped as s:
        report["stopped"] = s.label
        s.explore, s.stage = report, "explore"
        stop.say(stopped_line(report), both=False)
        raise


def _pin_maps(make_board, entries, focus, result, have: dict) -> list:
    """The pin map study (pinmap.py) on the best `pins.explore_top` variants, in the explore's own order (by run score):
    each variant's weighted crossings after remapping and its map, reported beside its score and never folded into it.
    `have` holds plans already resolved, {seed: (board, plan)}; another variant is resolved again (a seed is
    deterministic). Nothing is resolved for a board whose parts carry no `Pm.PinPool`. A study that raises on a variant
    leaves the explore's result standing: that variant's entry has no groups and carries the error. Each entry's
    `seconds` is what its resolve and its study took, after the explore's own time."""
    import time
    from .pinmap_rules import has_pools
    first = have[0][0]
    top = first.settings.pins_explore_top
    if top <= 0 or not has_pools(first.geometry.footprints):
        return []
    from . import pinmap
    out = []
    with _context_of(make_board):
        for seed, total, _ in result.results[:top]:
            entry = {"seed": seed, "score": round(total, 1), "groups": []}
            t0 = time.perf_counter()
            try:
                if seed in have:
                    board, plan = have[seed]
                else:
                    board = make_board()
                    plan = board.resolve(explore=Explore(seed, frozenset(focus)), lock=entries)
                entry["groups"] = pinmap.plan_summary(board, plan)
            except BaseException as e:                  # a stop or an interrupt still ends the explore
                if not pinmap.contained(e):
                    raise
                entry["error"] = {"type": type(e).__name__, "message": str(e)}
            entry["seconds"] = round(time.perf_counter() - t0, 3)
            out.append(entry)
    return out


def _move_of(key, was, now) -> dict | None:
    """One focused item's move between the plain placement and the variant's, as the report holds it: {"key", "mm",
    "rotation": [was, now]}, plus "arrangement": [was, now] when a cell's arrangement changed; "mm" is None when it is placed
    in one and not the other. None when it did not move."""
    if was is None or now is None:
        if was == now:
            return None
        return {"key": key, "mm": None, "rotation": [getattr(was, "rotation", None), getattr(now, "rotation", None)]}
    d = was.location.distance(now.location)
    if d <= 1e-6 and was.rotation == now.rotation and was.arrangement == now.arrangement:
        return None
    out = {"key": key, "mm": round(d, 3), "rotation": [was.rotation, now.rotation]}
    if was.arrangement != now.arrangement:
        out["arrangement"] = [was.arrangement, now.arrangement]
    return out


def stopped_line(report) -> str:
    """What a stopped explore says, whole: what it had and how to take it."""
    head = "explore stopped by %s after %d variant%s in %.0f s" % (
        report["stopped"], report["tried"], "" if report["tried"] == 1 else "s", report.get("seconds", 0.0))
    if report["best_seed"] and report.get("accept"):
        return "%s; best seed %d: %.1f -> %.1f mm; nothing accepted; accept it with: %s" % (
            head, report["best_seed"], report["baseline"], report["best"], report["accept"])
    if report["best_seed"]:
        return "%s; best seed %d: %.1f -> %.1f mm; nothing accepted (no saved state to accept it from)" % (
            head, report["best_seed"], report["baseline"], report["best"])
    return "%s; no variant beat the current placement (%.1f mm); nothing accepted" % (head, report["baseline"])


def accept_best(script, directory, release: str = "", run_id: str = "", seed: int | None = None) -> str:
    """Write a saved explore's variant to the script's lock, as the explore
    would have with --accept, without searching or resolving: its best, or
    `seed`, any variant the saved explore kept (checkpoint.read_variant), a
    finished one included until the next explore of the script replaces it.
    Returns what was done; raises ValueError saying why when it cannot."""
    from . import checkpoint as _checkpoint
    from types import SimpleNamespace
    doc = _checkpoint.read_best(directory)
    kept = (Path(directory) / "checkpoint.jsonl").exists()
    if doc is None and not kept:
        raise ValueError("no saved explore for this script (looked in %s)" % directory)
    if seed == 0:
        raise ValueError("seed 0 is the placement the explore began from: there is nothing to accept "
                         "(`placemat lock <script> --current` locks the current placement)")
    if seed is not None and (doc is None or doc["seed"] != seed):
        doc = _checkpoint.read_variant(directory, seed)
        if doc is None:
            raise ValueError("seed %d is not among the saved explore's variants (looked in %s)" % (seed, directory))
    if doc is None:
        raise ValueError("the saved explore has no variant better than the placement it began from; name one "
                         "with --accept-seed S")
    path = _lock.path_for(script)
    entries = _lock.read(path)
    if _checkpoint.lock_digest(entries) != doc["lock"]:
        raise ValueError("the lock changed since that explore began; explore again (or --resume once it is "
                         "the same lock)")
    if doc["script"] != _script_digest(script):
        raise ValueError("the script changed since that explore began; explore again")
    new = [_lock.LockEntry(**{**e, "anchor": tuple(e["anchor"]) if e["anchor"] is not None else None,
                              "offset": tuple(e["offset"]), "release": release, "run": run_id,
                              "score": round(doc["score"], 1)}) for e in doc["entries"]]
    plan = SimpleNamespace(turns={k: {"order": o} for k, o in doc["orders"].items()})
    _write_lock(path, entries, set(doc["focus"]), new, plan)
    return "wrote seed %d (score %.1f -> %.1f mm) for %d item%s to %s" % (
        doc["seed"], doc["baseline"], doc["score"], len(new), "" if len(new) == 1 else "s", path.name)


def _write_record(script, result, report, run_id: str = "", shown=None) -> None:
    """The explore's result, kept: every variant's seed, score, measures, the focused items' placements and the order they
    were placed in, which was kept, the run it was part of (`run_id`) and the pin map study of its best variants
    (`pin_maps`, `_pin_maps`), which the `explore_done` event carries too. Read after the command ends (the studio lists and
    replays it); `report["record"]` names it. `shown` is (board, plan) of the variant taken - the best, or the one its
    routes took (`taken_seed`), which is what an accept writes: its plan document, with its parts'
    3D models, is kept beside the record (explore_view.BEST_DIR) for the studio to show. A courtesy: a record that cannot be
    written does not fail the explore."""
    import json
    import os
    import time
    from . import channel
    try:
        from .project import find_board
        d = find_board(Path(script).resolve()).board_dir / ".placemat" / "views" / "explore"
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = d / ("%s-%d.json" % (stamp, os.getpid()))
        doc = {"version": 1, "script": str(Path(script).resolve()), "at": time.time(), "pid": os.getpid(), "focus": result.focus,
               "seconds": result.seconds, "jobs": result.jobs, "baseline": result.baseline, "plain": result.plain, "order": result.plain_order,
               "best_seed": result.best_seed, "best": result.best, "kept": bool(report.get("accepted")), "variants": result.variants,
               "curve": result.curve, "found": report.get("found"), "ended": result.ended, "run": run_id,
               "pin_maps": report.get("pin_maps") or []}
        doc.update(_routed(report))
        path.write_text(json.dumps(doc, separators=(",", ":")))
        report["record"] = str(path)
        if shown is not None:
            seed = report.get("taken_seed", result.best_seed)
            row = next((r for r in getattr(result, "results", ()) if r[0] == seed), None)
            _write_best(path, result, *shown, total=row[1] if row else None, measures=row[2] if row else None)
        rep = channel.current()
        if rep is not None:
            rep.send({"ev": "explore_done", "best_seed": result.best_seed, "best": result.best, "baseline": result.baseline, "tried": result.tried,
                      "kept": bool(report.get("accepted")), "record": str(path), "found": report.get("found"), "ended": result.ended,
                      "pin_maps": report.get("pin_maps") or [], **_routed(report)})
    except (OSError, ValueError):
        pass


def _routed(report) -> dict:
    """What the record and its done event keep of the routes (`_route_work`): the routes and the seed taken by them,
    when the explore routed."""
    return {k: report[k] for k in ("routes", "taken_seed", "routes_skipped") if k in report}


def _write_best(record, result, board, plan, total=None, measures=None) -> None:
    """The best variant's plan document beside its record (explore_view.BEST_DIR, the record's name), with its parts' 3D models and
    the converter's jobs for them (`model_jobs`), and the run score as the explore measured it: `total` and `measures` are
    the shown variant's (the one its routes took), the best's when not given. A courtesy, as the record is."""
    import json
    import sys
    from . import score as _score
    from .channel import _model_context
    from .explore_view import BEST_DIR
    from .preview_json import declared_sites, plan_json
    try:
        ctx = _model_context(plan)
        measures = result.best_measures if measures is None else measures
        total = result.best if total is None else total
        terms = _score.terms(measures, board.settings) if measures else {}
        doc = plan_json(plan, declared_sites(board), {"total": round(total, 3), "terms": {k: round(v, 3) for k, v in terms.items() if v}}, ctx)
        if ctx is not None:
            doc["model_jobs"] = ctx.new_jobs(set())
        out = record.parent / BEST_DIR / record.name
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(doc, separators=(",", ":")))
    except Exception as e:                                              # the record stands without it: the studio moves the run's board instead
        print("explore: the best variant's plan was not kept: %s: %s" % (type(e).__name__, e), file=sys.stderr)


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
    resume: str = "auto"            # "yes": --resume, "no": --no-resume
    route_best: bool | None = None  # --route-best; None: [explore] route_best


def before_resolve(script, board, make_board, options, say, run_id: str = "", keep_state: bool = False, variants_dir=None,
                   route_exclude=(), route_resume: bool = True) -> tuple:
    """The lock entries a run resolves with, and the explore report when
    --explore was given (else None): the search runs first, and with
    --accept its decisions are in the entries returned. `variants_dir` is
    where routed variants are written (a run's; None routes none)."""
    from . import __version__
    from . import lock as _lock
    if options is None:
        return _lock.read(_lock.path_for(script)), None
    state = _state_dir(script, make_board)
    report, entries = search(make_board, script, options.seconds, options.jobs, options.keys,
                             options.after_line, options.box, options.accept, release=__version__,
                             run_id=run_id, checkpoint_dir=state, resume=options.resume, keep_state=keep_state,
                             route_best=options.route_best, variants_dir=variants_dir, route_exclude=route_exclude,
                             route_resume=route_resume)
    for line in report_lines(report):
        say("explore", line)
    return entries, report


def _state_dir(script, make_board):
    """Where this script's explore keeps its state: beside the board's runs
    (None for a factory that is not a run's, which has no board folder)."""
    from . import checkpoint
    src = getattr(make_board, "src", None)
    return checkpoint.state_dir(src.board_dir, script) if src is not None else None


def _moved_terms(board, before, after) -> dict:
    """{term: [before, after]} for the terms of the run score that differ."""
    from . import score as _score
    if not before or not after:
        return {}
    tb, ta = _score.terms(before, board.settings), _score.terms(after, board.settings)
    return {t: [round(tb[t], 1), round(ta[t], 1)] for t in _score.TERMS if abs(tb[t] - ta[t]) > 1e-6}


def report_lines(report) -> list:
    lines = _report_lines(report)
    for f in report.get("failures", ()):
        lines += ["worker failed: " + (f if "\n" not in f else f.splitlines()[0] + " " + f.splitlines()[-1])]
    return lines


def _ended_text(ended) -> str:
    """Which rule ended an explore, from its record; nothing for the budget."""
    rule = (ended or {}).get("rule")
    if rule == "stall_count":
        return "; ended by a stall: %d variants without improvement" % ended["limit"]
    if rule == "stall_time":
        return "; ended by a stall: %s without improvement" % duration(ended["limit"])
    if rule == "hard_clear":
        return "; ended: the hard terms are clear"
    return ""


def _report_lines(report) -> list:
    b, a = report["baseline"], report["best"]
    if report.get("empty"):
        return ["nothing to explore: no searched item is in focus (every item's place is decided, or the focus "
                "names none)"]
    head = "%d variants in %.0f s over %d focused item%s" % (
        report["tried"], report.get("seconds", 0.0), len(report["focus"]), "" if len(report["focus"]) == 1 else "s")
    ended = _ended_text(report.get("ended"))
    if not report["best_seed"] and "routes" not in report:
        return [head + ": no variant scored better than the current placement" + ended]
    if not report["best_seed"]:
        lines = [head + ": no variant scored better than the current placement" + ended]
        return lines + _move_lines(report) + routes_summary(report) + _accept_lines(report)
    moved = ", ".join("%s %.1f -> %.1f" % (t, x, y) for t, (x, y) in (report.get("terms") or {}).items())
    found = report.get("found")
    when = (", best found at variant %d of %d, %s in (of %s)" % (found["i"], found["of_variants"], duration(found["t"]),
                                                              duration(found["of_seconds"]))) if found else ""
    taken = report.get("taken_seed", report["best_seed"])
    lines = [head + ": score %.1f -> %.1f mm%s; %d item%s would move%s%s%s" % (
        b, a, " (%s)" % moved if moved else "", len(report["moves"]), "" if len(report["moves"]) == 1 else "s",
        "" if taken == report["best_seed"] else " to seed %d's places, taken by route closure" % taken, when, ended)]
    lines += _move_lines(report)
    lines += pin_map_lines(report)
    lines += routes_summary(report)
    return lines + _accept_lines(report)


def _move_lines(report) -> list:
    lines = []
    for m in report["moves"]:
        turn = "" if m["rotation"][0] == m["rotation"][1] else ", rotation %s -> %s" % tuple(
            "-" if r is None else "%g" % r for r in m["rotation"])
        if "arrangement" in m:
            turn += ", arrangement %s -> %s" % tuple(a or "default" for a in m["arrangement"])
        lines.append("  %s: %s%s" % (m["key"], "placed/unplaced" if m["mm"] is None else "%.2f mm" % m["mm"], turn))
    return lines


def _accept_lines(report) -> list:
    if report["accepted"]:
        return ["accepted: written to the lock"]
    if report.get("taken_seed") == 0:
        return ["nothing to accept: the current placement's route closed best"]
    return ["not accepted: --accept writes it to the lock%s" % (
        ", or later: " + report["accept"] if report.get("accept") else "")]


def route_line(r: dict) -> str:
    """One route of the routing worker (`_route_work`), as it is said when it comes: its closure, clean and raw, the
    signal items it left open and the time it took, or that writing or routing it failed."""
    at = "  route, seed %d at %.1f mm: " % (r["seed"], r["score"])
    if r.get("error"):
        message = (r["error"]["message"] or "").splitlines()
        return at + "the route failed with %s%s" % (r["error"]["type"], ": " + message[0] if message else "")
    return at + "closure %.1f%% clean (%.1f%% raw), %d open, in %s%s" % (
        100 * r["closure_clean"], 100 * r["closure"], r["open_after"], duration(r["seconds"]),
        "" if r.get("valid", True) else "; the placement's DRC was not clean before routing")


def route_lines(report) -> list:
    """Every route's line (`route_line`), then `routes_summary`'s."""
    return [route_line(r) for r in report.get("routes") or ()] + routes_summary(report)


def routes_summary(report) -> list:
    """What the routes came to, after their lines were said as they came: how many, the time they took and the variant
    taken. Nothing when the explore did not route."""
    if "routes" not in report:
        return []
    if report.get("routes_skipped") == "no_board":
        return ["  routes: none; a preview writes no board to route: explore in a run to route its variants"]
    routes = report["routes"]
    if not routes:
        return []
    t = report.get("taken_seed")
    taken = ("taken by closure: seed %d%s" % (t, ", the current placement" if t == 0 else "")) if t is not None \
        else "every route failed: the best score is taken"
    return ["  routes: %d variant%s quick-routed in %s, alongside the search; %s" % (
        len(routes), "" if len(routes) == 1 else "s", duration(sum(r["seconds"] for r in routes)), taken)]


def pin_map_lines(report) -> list:
    """A line per studied group of each variant the pin map study ran on: its weighted crossings now and after
    remapping, and the pose that takes, or that it ran past its wall-clock guard; a variant whose study failed says so. Then the time the study took after the
    explore's own."""
    from .finding_text import at_pose
    out = []
    maps = report.get("pin_maps") or ()
    for v in maps:
        if v.get("error"):
            out.append("  pin map, seed %d at %.1f mm: the study failed with %s: %s" % (
                v["seed"], v["score"], v["error"]["type"], v["error"]["message"]))
        for g in v["groups"]:
            if g.get("slow"):
                out.append("  pin map, seed %d at %.1f mm: %s ran past its wall-clock guard, pins.guard_ms of %g ms, after %d "
                           "of its %d steps; no map" % (v["seed"], v["score"], " and ".join(g["refs"]), g["guard_ms"],
                                                         g["steps"], g["budget_steps"]))
                continue
            turned = [t for t in g["turns"] if t["turn_deg"] or t["flip"]]
            out.append("  pin map, seed %d at %.1f mm: %s %g -> %g weighted crossings after remapping%s" % (
                v["seed"], v["score"], " and ".join(g["refs"]), g["present"]["weighted"], g["best"]["weighted"],
                ", " + at_pose(turned) if turned else ""))
    if maps:
        out.append("  pin map study: %d variant%s in %.2f s, after the explore's time" % (
            len(maps), "" if len(maps) == 1 else "s", sum(v.get("seconds", 0.0) for v in maps)))
    return out


def lock_summary(plan) -> str:
    """How the lock fared in a plan: held, drifted, released, from its steps."""
    held = sum(1 for s in plan.steps if s.lock == "held")
    drifted = sum(1 for s in plan.steps if s.lock == "drifted")
    released = sum(1 for s in plan.steps if s.lock == "released")
    if not (held or drifted or released):
        return ""
    return "%d held by lock, %d drifted, %d released" % (held, drifted, released)
