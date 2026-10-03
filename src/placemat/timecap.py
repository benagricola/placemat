"""Time bounds on a command: how long a preview or run may take, and how long one step of it may.

`--max-time SECONDS` (`[run] max_time_s`) stops the command through the same path a SIGTERM takes (stop.py): a watchdog
thread asks for that stop when the time is up, so what a stop already does - the run record "stopped", the explore's
checkpoint, the steps finished so far kept for the rerun to replay - is what a capped command does, and the record says it
was the cap (`cause`, the steps done, the step and pass it was in, the findings so far). The cap bounds the placement (the
generation, an explore, the resolve): once the placement is in hand it is lifted, because what follows (the board written, DRC,
the render) is not safely stopped half way and has its own `[timeout]`s.

`--step-warn SECONDS` and `--step-limit SECONDS` (`[run] step_warn_s`, `step_limit_s`) bound one step. A step that runs past
the warn time sends a live `step_warn` event and gets a finding (`time.step_slow`) naming the item, its seconds and the pass it
was in. A step past the limit gives up: the scan stops at its next pass boundary (the phase points of placer.scan), and the
step is left unplaced, or at the best legal spot the scan had by then, with a `time.step_limit` finding. A step that gave up is
never replayed (its reuse key is made one no later run can match), so the rerun searches it again.

These are wall-clock times: they depend on the machine's load, and a step can be cut short when the machine is busy that a quiet
one would finish. A bound that does not depend on load is a candidate budget (`place.step_budget`).

The state is per process and exists only for a command that installed the stop handlers (cli.main): a library call, the studio's
own resolve and an explore's worker processes have none, and every function here does nothing for them."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import signal
import threading
import time

_state: dict = {"flags": None, "clock": None, "started": None}


@dataclass(frozen=True)
class Bounds:
    """What bounds a command, in seconds; 0 is no bound."""
    max_time_s: float = 0.0
    step_warn_s: float = 0.0
    step_limit_s: float = 0.0

    @property
    def any(self) -> bool:
        return bool(self.max_time_s or self.step_warn_s or self.step_limit_s)


@dataclass
class StepTime:
    """How one step's time went, as data: what `Clock.end_step` returns for a step that was warned about or gave up."""
    item: str
    elapsed_s: float
    stage: str                          # the pass it was in when it ended
    within: list | None = None          # [k, n] of the refine pass it was in
    firm_pass: int | None = None        # the firm pass of the resolve it was in (layout._resolve), else None
    warned: bool = False                # it ran past its warn time
    warned_at_s: float | None = None
    warned_stage: str = ""              # the pass it was in then
    over: bool = False                  # it ran past its limit (and, if it had no pass to stop at, finished all the same)
    limited: bool = False               # a pass stopped at the limit: the step gave up
    limited_at_s: float | None = None
    limited_stage: str = ""


def pass_name(stage, within=None, firm_pass=None) -> str:
    """The pass a step is in, as one word for a person (phases.label): coarse, fine, refine, give-way, a firm pass k, or what
    else it was doing."""
    if firm_pass is not None:
        return "firm pass %d" % firm_pass
    from .phases import label
    return label(stage)


def pass_phrase(name: str, within=None) -> str:
    """A pass named for a sentence: "coarse pass", "refine pass 2 of 3", "firm pass 1"."""
    if name.startswith("firm pass"):
        return name
    return "%s pass%s" % (name or "settle", (" %d of %d" % tuple(within)) if within else "")


def configure(max_time=None, step_warn=None, step_limit=None) -> None:
    """The command's flags (None: not given, the setting decides), at the start of a command that can be stopped."""
    _state.update(flags={"max_time_s": max_time, "step_warn_s": step_warn, "step_limit_s": step_limit}, started=time.monotonic(), clock=None)


def reset() -> None:
    """Forget everything (tests, the end of a command)."""
    clock = _state.get("clock")
    if clock is not None:
        clock.close()
    _state.update(flags=None, clock=None, started=None)


def disable() -> None:
    """This process bounds nothing (an explore's worker processes: the parent holds the cap)."""
    _state.update(flags=None, clock=None, started=None)


def bounds_for(cfg, flags=None) -> Bounds:
    """The bounds a command has: its flags where given, else the settings."""
    flags = flags or {}
    pick = lambda name: float(flags[name]) if flags.get(name) is not None else float(getattr(cfg, "run_" + name))
    return Bounds(max(0.0, pick("max_time_s")), max(0.0, pick("step_warn_s")), max(0.0, pick("step_limit_s")))


def arm(cfg) -> "Clock | None":
    """Start bounding the command by the settings `cfg` and the flags `configure` was given. None when the command did not
    configure (not a stoppable command) or nothing bounds it. Once per command: a second call returns the same clock."""
    flags = _state.get("flags")
    if flags is None:
        return None
    if _state["clock"] is not None:
        return _state["clock"]
    bounds = bounds_for(cfg, flags)
    if not bounds.any:
        return None
    clock = Clock(bounds, _state["started"])
    _state["clock"] = clock
    clock.start()
    return clock


def active() -> "Clock | None":
    return _state["clock"]


def placement_done() -> None:
    """The placement is in hand: the cap is lifted (see the module's doc), the step bounds have nothing left to bound."""
    clock = _state["clock"]
    if clock is not None:
        clock.lift_cap()
        clock.end_step()


@contextmanager
def cap_only():
    """Within it only the time cap is kept: no step is timed (an explore's baseline resolves are not the command's placement)."""
    clock = _state["clock"]
    if clock is None:
        yield
        return
    clock.steps_on = False
    try:
        yield
    finally:
        clock.steps_on = True


def report() -> dict:
    """Where a command stopped by the cap had got to, as data (see Clock.report); {} when it is not bounded."""
    clock = _state["clock"]
    return clock.report() if clock is not None else {}


class Clock:
    """A command's bounds being kept: the cap's watchdog, and the step in progress."""

    TICK = 0.5                                              # seconds between the watchdog's looks

    def __init__(self, bounds: Bounds, started: float):
        self.bounds, self.started = bounds, started
        self.lock = threading.Lock()
        self._done = threading.Event()
        self.thread = None
        self.cap_lifted = False
        self.cap_asked = False
        self.steps_on = True                                # False inside `cap_only`
        # the resolve so far
        self.steps_done = 0
        self.steps_of = None
        self.replayed = 0
        self.plan = None                                    # the plan being made: its findings are read for a report
        self.firm_pass = None
        # the step in progress
        self.item = None
        self.step_started = None
        self.stage = ""
        self.within = None
        self.warned = None                                  # (elapsed_s, stage) when the warn time passed
        self.over = None                                    # likewise for the limit
        self.limited = None                                 # likewise for a pass that stopped at the limit

    # ---- the watchdog
    def start(self) -> None:
        self.thread = threading.Thread(target=self._watch, daemon=True, name="placemat-timecap")
        self.thread.start()

    def close(self) -> None:
        self._done.set()

    def lift_cap(self) -> None:
        with self.lock:
            self.cap_lifted = True

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def _watch(self) -> None:
        while not self._done.wait(self.TICK):
            try:
                self.tick()
            except Exception:                               # a bound that cannot be kept must not end the command
                pass

    def tick(self) -> None:
        """One look: the cap asks for the stop when its time is up, a step past its warn time says so."""
        ask = False
        with self.lock:
            cap = self.bounds.max_time_s
            if cap and not self.cap_lifted and not self.cap_asked and self.elapsed() >= cap:
                self.cap_asked = ask = True
            self._check_step()
        if ask:
            from . import stop
            stop.request("max_time", limit_s=cap)

    # ---- the steps
    def new_pass(self, total: int | None, firm_pass: int | None, plan=None) -> None:
        """A run of the resolve begins (the firm passes are runs of their own): its steps are counted from none."""
        with self.lock:
            if not self.steps_on:
                return
            self.steps_done, self.steps_of, self.replayed, self.firm_pass, self.plan = 0, total, 0, firm_pass, plan
            self._clear_step()

    def _clear_step(self) -> None:
        self.item = self.step_started = self.warned = self.over = self.limited = None
        self.stage, self.within = "", None

    def begin_step(self, item: str) -> None:
        with self.lock:
            self._clear_step()
            if self.steps_on:
                self.item, self.step_started = item, time.monotonic()

    def replayed_step(self) -> None:
        with self.lock:
            if self.steps_on:
                self.steps_done += 1
                self.replayed += 1

    def end_step(self) -> "StepTime | None":
        """The step in progress is over: how its time went when it was warned about or gave up, else None."""
        with self.lock:
            if self.item is None:
                return None
            self.steps_done += 1
            self._check_step()                              # a step that ended between two looks was still timed
            spent = None
            if self.warned or self.over or self.limited:
                spent = StepTime(self.item, round(time.monotonic() - self.step_started, 1), self.stage, self.within, self.firm_pass,
                                 warned=self.warned is not None, warned_at_s=self.warned[0] if self.warned else None,
                                 warned_stage=self.warned[1] if self.warned else "",
                                 over=self.over is not None, limited=self.limited is not None,
                                 limited_at_s=self.limited[0] if self.limited else None,
                                 limited_stage=self.limited[1] if self.limited else "")
            self._clear_step()
            return spent

    def phase(self, stage, within=None, cut: bool = False, **_) -> bool:
        """The step in progress is at a phase (a phases.Stage: a pass of the scan, seeding ...). With `cut`, the caller stops
        its work where it is when this is True: the step is out of time (past its limit) and gives up here."""
        with self.lock:
            if self.item is None:
                return False
            self.stage = str(stage)
            self.within = list(within) if within else None
            self._check_step()
            if cut and self.over is not None and self.limited is None:
                self.limited = (round(time.monotonic() - self.step_started, 1), self.stage)
                self._tell("step_limit", time.monotonic() - self.step_started, self.bounds.step_limit_s)
            return self.limited is not None

    @property
    def gave_up(self) -> bool:
        with self.lock:
            return self.limited is not None

    def _check_step(self) -> None:
        """(under the lock) The step in progress against its warn and limit times."""
        if self.item is None:
            return
        elapsed = time.monotonic() - self.step_started
        b = self.bounds
        if b.step_warn_s and self.warned is None and elapsed >= b.step_warn_s:
            self.warned = (round(elapsed, 1), self.stage)
            self._tell("step_warn", elapsed, b.step_warn_s)
        if b.step_limit_s and self.over is None and elapsed >= b.step_limit_s:
            self.over = (round(elapsed, 1), self.stage)         # the step gives up at its next pass boundary (`phase`)

    def _tell(self, kind: str, elapsed: float, bound: float) -> None:
        """A live event for the readers (`placemat watch`, the studio), and a line for the console."""
        event = {"ev": kind, "item": self.item, "elapsed_s": round(elapsed, 1), "pass": pass_name(self.stage, self.within, self.firm_pass),
                 "stage": self.stage, "within": self.within, "firm_pass": self.firm_pass, "bound_s": bound, "at": time.time()}
        try:
            from . import channel
            channel.send(event)
        except Exception:
            pass
        try:
            from .console import errors                 # stderr: a preview's --json owns stdout
            errors.say("slow", step_line(event), level="notice" if kind == "step_warn" else "warning")
        except Exception:
            pass

    # ---- what a stop by the cap reports
    def report(self) -> dict:
        """Where the command had got to: the steps done of those there are, the step in progress and its pass, the findings so
        far. Data; `stop.line` makes the words."""
        with self.lock:
            findings = list(self.plan.findings) if self.plan is not None else []
            step = None
            if self.item is not None:
                step = {"item": self.item, "elapsed_s": round(time.monotonic() - self.step_started, 1),
                        "pass": pass_name(self.stage, self.within, self.firm_pass), "stage": self.stage, "within": self.within,
                        "firm_pass": self.firm_pass}
            by_severity: dict = {}
            for f in findings:
                by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
            return {"limit_s": self.bounds.max_time_s, "elapsed_s": round(self.elapsed(), 1), "steps_done": self.steps_done,
                    "steps_of": self.steps_of, "steps_replayed": self.replayed, "in_progress": step,
                    "findings": {"count": len(findings), "by_severity": by_severity}}


def step_line(ev: dict) -> str:
    """One line for a `step_warn` or `step_limit` event, for the console and `placemat watch`."""
    where = pass_phrase(ev.get("pass") or "settle", ev.get("within"))
    if ev.get("ev") == "step_limit":
        return "%s: gave up after %.1f s (--step-limit %g s) in the %s" % (ev.get("item"), ev.get("elapsed_s", 0.0), ev.get("bound_s", 0), where)
    return "%s: still working after %.1f s (--step-warn %g s) in the %s" % (ev.get("item"), ev.get("elapsed_s", 0.0), ev.get("bound_s", 0), where)
