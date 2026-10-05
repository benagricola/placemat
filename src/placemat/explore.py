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


def explore(make_board, focus, seconds: float, jobs: int | None = None, seeds=None, lock=None,
            checkpoint=None) -> ExploreResult:
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
    is told of the baseline, every variant and each new best as they come."""
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
    partial = lambda: _result(results, baseline, base_m, spent + time.time() - t0, failures, variants, focus, len(procs),
                              curve, ended_by())
    try:
        for pr in procs:
            pr.start()
        if rep is not None:
            rep.send({"ev": "explore", "focus": sorted(focus), "seconds": seconds, "jobs": len(procs),
                      "seeds": None if order is None else len(order), "baseline": baseline,
                      "baseline_measures": base_m, "plain": variants[0]["placements"], "order": variants[0]["order"],
                      "at": t0})

        def take(msg):
            if msg[0] == "end":
                ended.add(msg[1])
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
    except stop.Stopped as s:
        s.partial = partial()
        s.partial.stopped = True
        s.partial.ended = {"rule": "signal", "signal": s.name, **({"cause": s.cause["cause"]} if s.cause else {})}
        if checkpoint is not None:
            checkpoint.stopped(s.label, s.partial.seconds)
        raise
    finally:
        _end(procs)
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
            ended=None) -> ExploreResult:
    rows = sorted(results.values(), key=lambda r: (r[1], r[0]))
    return ExploreResult(rows[0][0], rows[0][1], baseline, len(rows), rows, rows[0][2], base_m, round(seconds, 3),
                         list(failures), variants=variants, focus=sorted(focus), jobs=jobs,
                         plain=variants[0]["placements"] if variants else None,
                         plain_order=variants[0]["order"] if variants else None, curve=list(curve) if curve else None,
                         ended=ended)


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
                payload = None
                with best_val.get_lock():           # the best so far carries its lock entries, for the one accepted
                    better = total <= best_val.value and total < baseline - 1e-9
                    if better:
                        best_val.value = total
                if better:
                    payload = _payload(b, p, focus)
            out.put(("v", seed, total, m, payload, round(time.time() - t0, 3),
                     {"placements": _placements(p, focus), "order": _order(p, focus)}))
    except BaseException:
        out.put(("err", idx, traceback.format_exc()))
    finally:
        out.put(("end", idx))


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
           resume: str = "auto", keep_state: bool = False) -> tuple:
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
    the user's - and the stop goes on up with the report as `.explore`."""
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
    try:
        result = explore(make_board, focus, seconds, jobs, seeds=seeds, lock=entries, checkpoint=ck)
    except stop.Stopped as s:
        now = score(base, current)
        r = s.partial or ExploreResult(0, now, now, 0, [], seconds=0.0)       # stopped before a variant was begun
        report = {"tried": r.tried, "focus": sorted(focus), "baseline": r.baseline, "best": r.best,
                  "best_seed": r.best_seed, "moves": [], "accepted": False, "stopped": s.label,
                  "seconds": round(r.seconds, 1), "failures": r.failures}
        if r.curve:
            report.update(curve=_compact(r.curve), found=_found(r.curve, r.seconds), ended=r.ended)
        if r.best_seed and ck is not None and (_checkpoint.read_best(ck.dir) or {}).get("seed") == r.best_seed:
            report["accept"] = accept_command(script, r.best_seed)
        s.explore, s.stage = report, "explore"
        stop.say(stopped_line(report), both=False)
        raise
    report = {"tried": result.tried, "focus": sorted(focus), "baseline": result.baseline, "seconds": round(result.seconds, 1),
              "best": result.best, "best_seed": result.best_seed, "moves": [], "accepted": False,
              "terms": _moved_terms(base, result.baseline_measures, result.best_measures)}
    report.update(curve=_compact(result.curve), found=_found(result.curve, result.seconds), ended=result.ended)
    if result.failures:
        report["failures"] = result.failures
    if ck is not None and result.best_seed and (_checkpoint.read_best(ck.dir) or {}).get("seed") == result.best_seed:
        report["accept"] = accept_command(script, result.best_seed)
    if result.best_seed == 0:
        _study(report, make_board, entries, focus, result, {0: (base, current)})
        _write_record(script, result, report, run_id, (base, current))
        if ck is not None and not keep_state:
            ck.finish()
        return report, entries
    with _context_of(make_board):
        board = make_board()
        best = board.resolve(explore=Explore(result.best_seed, frozenset(focus)), lock=entries)
    for key in sorted(focus):
        m = _move_of(key, current.placement(key), best.placement(key))
        if m:
            report["moves"].append(m)
    # before the accept: the variants are studied under the lock they were ranked under
    _study(report, make_board, entries, focus, result, {0: (base, current), result.best_seed: (board, best)})
    if accept:
        placed = [k for k in focus if best.placement(k) is not None]
        new = _lock.entries(board, best, placed, release, run_id, round(result.best, 1))
        entries = _write_lock(path, entries, focus, new, best)
        report["accepted"] = True
        if ck is not None:
            ck.best_path.unlink(missing_ok=True)         # taken: it would not match the lock now
    _write_record(script, result, report, run_id, (board, best))
    if ck is not None and not keep_state:
        ck.finish()
    return report, entries


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
    """Write a saved explore's best variant to the script's lock, as the
    explore would have with --accept, without searching or resolving. `seed`
    is the one the caller named: refused when the saved best is another.
    Returns what was done; raises ValueError saying why when it cannot."""
    from . import checkpoint as _checkpoint
    from types import SimpleNamespace
    doc = _checkpoint.read_best(directory)
    if doc is None:
        raise ValueError("no saved explore for this script (looked in %s)" % directory)
    if seed is not None and doc["seed"] != seed:
        raise ValueError("the saved explore's best is seed %d, not %d" % (doc["seed"], seed))
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
    were placed in, which was kept and the run it was part of (`run_id`). Read after the command ends (the studio lists and
    replays it); `report["record"]` names it. `shown` is (board, the best variant's plan): its plan document, with its parts'
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
               "curve": result.curve, "found": report.get("found"), "ended": result.ended, "run": run_id}
        path.write_text(json.dumps(doc, separators=(",", ":")))
        report["record"] = str(path)
        if shown is not None:
            _write_best(path, result, *shown)
        rep = channel.current()
        if rep is not None:
            rep.send({"ev": "explore_done", "best_seed": result.best_seed, "best": result.best, "baseline": result.baseline, "tried": result.tried,
                      "kept": bool(report.get("accepted")), "record": str(path), "found": report.get("found"), "ended": result.ended})
    except (OSError, ValueError):
        pass


def _write_best(record, result, board, plan) -> None:
    """The best variant's plan document beside its record (explore_view.BEST_DIR, the record's name), with its parts' 3D models and
    the converter's jobs for them (`model_jobs`), and the run score as the explore measured it. A courtesy, as the record is."""
    import json
    import sys
    from . import score as _score
    from .channel import _model_context
    from .explore_view import BEST_DIR
    from .preview_json import declared_sites, plan_json
    try:
        ctx = _model_context(plan)
        terms = _score.terms(result.best_measures, board.settings) if result.best_measures else {}
        doc = plan_json(plan, declared_sites(board), {"total": round(result.best, 3), "terms": {k: round(v, 3) for k, v in terms.items() if v}}, ctx)
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


def before_resolve(script, board, make_board, options, say, run_id: str = "", keep_state: bool = False) -> tuple:
    """The lock entries a run resolves with, and the explore report when
    --explore was given (else None): the search runs first, and with
    --accept its decisions are in the entries returned."""
    from . import __version__
    from . import lock as _lock
    if options is None:
        return _lock.read(_lock.path_for(script)), None
    state = _state_dir(script, make_board)
    report, entries = search(make_board, script, options.seconds, options.jobs, options.keys,
                             options.after_line, options.box, options.accept, release=__version__,
                             run_id=run_id, checkpoint_dir=state, resume=options.resume, keep_state=keep_state)
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
    if not report["best_seed"]:
        return [head + ": no variant scored better than the current placement" + ended]
    moved = ", ".join("%s %.1f -> %.1f" % (t, x, y) for t, (x, y) in (report.get("terms") or {}).items())
    found = report.get("found")
    when = (", best found at variant %d of %d, %s in (of %s)" % (found["i"], found["of_variants"], duration(found["t"]),
                                                              duration(found["of_seconds"]))) if found else ""
    lines = [head + ": score %.1f -> %.1f mm%s; %d item%s would move%s%s" % (
        b, a, " (%s)" % moved if moved else "", len(report["moves"]), "" if len(report["moves"]) == 1 else "s", when, ended)]
    for m in report["moves"]:
        turn = "" if m["rotation"][0] == m["rotation"][1] else ", rotation %s -> %s" % tuple(
            "-" if r is None else "%g" % r for r in m["rotation"])
        if "arrangement" in m:
            turn += ", arrangement %s -> %s" % tuple(a or "default" for a in m["arrangement"])
        lines.append("  %s: %s%s" % (m["key"], "placed/unplaced" if m["mm"] is None else "%.2f mm" % m["mm"], turn))
    lines += pin_map_lines(report)
    if report["accepted"]:
        lines.append("accepted: written to the lock")
    else:
        lines.append("not accepted: --accept writes it to the lock%s" % (
            ", or later: " + report["accept"] if report.get("accept") else ""))
    return lines


def pin_map_lines(report) -> list:
    """A line per studied group of each variant the pin map study ran on: its weighted crossings now and after
    remapping, and the pose that takes; a variant whose study failed says so. Then the time the study took after the
    explore's own."""
    from .finding_text import at_pose
    out = []
    maps = report.get("pin_maps") or ()
    for v in maps:
        if v.get("error"):
            out.append("  pin map, seed %d at %.1f mm: the study failed with %s: %s" % (
                v["seed"], v["score"], v["error"]["type"], v["error"]["message"]))
        for g in v["groups"]:
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
