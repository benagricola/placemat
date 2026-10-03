"""The probe: a sweep over one value of one script edit, to find the value that clears a finding.

A searched suggestion (`how: "searched"`) has a `figure` instead of a value: where a condition flips, or a small set to try.
The probe makes each candidate by filling the figure's value into the suggestion's edits (a dry run), has the edited texts
resolved in place of the files on disk (the studio's try path: `resolve(overlay)`), and judges what came back. Its result is
data (`ProbeResult`); `line` words it at the edge. A found value becomes an instant suggestion of its own (`found_suggestion`).

Nothing here resolves a board itself: `resolve` is a function the caller gives (the command line's `overlay_resolver`, a test's
fake), so the same judging serves the command line and the studio's worker."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import suggestions as sg
from .findings import RANK

PROBES = "probes"


class ProbeRefused(Exception):
    """A searched suggestion that cannot be probed (it has no figure, or its edits cannot be made on the script as it stands).
    `record` is why, as data: {"code": "not_searched" (id) | "edit_failed" (detail: the edit's own error) | "base_failed" (error: the
    resolve's, see `error_text`) | "finding_gone" (id)}; `str()` is `refusal_text` of it."""

    def __init__(self, code: str, **facts):
        self.record = {"code": code, **facts}
        super().__init__(refusal_text(self.record))


def error_text(e: dict) -> str:
    """A resolve's error as `overlay_resolver` records it: {"kind": "timeout", "limit_s"} or {"kind": "exception", "type", "detail"}."""
    if e.get("kind") == "timeout":
        return "the resolve took longer than [studio] try_timeout_s (%g s)" % e["limit_s"]
    return "%s: %s" % (e.get("type", ""), e.get("detail", "")) if e.get("type") else e.get("detail", "")


def refusal_text(r: dict) -> str:
    """A ProbeRefused record in words."""
    code = r.get("code")
    if code == "not_searched":
        return "%s is not a searched suggestion with a figure and the finding it is for" % r["id"]
    if code == "base_failed":
        return "the script as it stands does not resolve: %s" % error_text(r["error"])
    if code == "finding_gone":
        return "the finding %s is for is not in the script's resolve any more: run it again for suggestions that fit" % r["id"]
    return r.get("detail", "") or str(code)


# ------------------------------------------------------------------ what a candidate resolve gave
@dataclass
class Outcome:
    """What resolving one edited script gave: its findings (Findings or their JSON), the run score (lower is better) and the
    seconds it took. `error` is set where the edited script did not resolve (`error_text` says it)."""
    findings: list
    score: float | None = None
    seconds: float = 0.0
    error: dict | None = None


@dataclass
class Candidate:
    """One value tried: whether the finding cleared, what was gained (each `{kind, cause, subject, severity}`), the score and
    the seconds. `acceptable` is the judgement: cleared, and nothing more serious gained than what was cleared."""
    value: object
    cleared: bool = False
    gained: list = field(default_factory=list)
    score: float | None = None
    seconds: float = 0.0
    error: dict | None = None
    acceptable: bool = False

    def to_json(self) -> dict:
        out = {"value": self.value, "cleared": self.cleared, "gained": self.gained, "score": self.score,
               "seconds": round(self.seconds, 3), "acceptable": self.acceptable}
        if self.error:
            out["error"] = self.error
        return out

    @staticmethod
    def from_json(d: dict) -> "Candidate":
        return Candidate(d["value"], bool(d.get("cleared")), list(d.get("gained", ())), d.get("score"),
                         float(d.get("seconds", 0.0)), _error_of(d.get("error")), bool(d.get("acceptable")))


def _error_of(v) -> dict | None:
    """A saved candidate's error: a record, or the sentence an earlier release saved."""
    if not v:
        return None
    return v if isinstance(v, dict) else {"kind": "exception", "type": "", "detail": str(v)}


@dataclass
class ProbeResult:
    """How a probe ended. `state`: found (a best candidate, the search converged), none (no value in the range clears it),
    limit (the candidate limit ended it), budget (the time budget did), stopped (asked to), error (the edit could not be made).
    `neighbour` is the value one step toward the declared one and whether it cleared; `monotone` is False where it did."""
    state: str
    candidates: list
    best: Candidate | None = None
    neighbour: dict | None = None
    monotone: bool = True
    of: int = 0
    refusal: dict | None = None     # a state "error": the ProbeRefused record
    resumed: int = 0

    @property
    def n(self) -> int:
        return len(self.candidates)

    def to_json(self) -> dict:
        return {"state": self.state, "n": self.n, "of": self.of, "best": self.best.to_json() if self.best else None,
                "neighbour": self.neighbour, "monotone": self.monotone, "refusal": self.refusal, "resumed": self.resumed,
                "candidates": [c.to_json() for c in self.candidates]}


# ------------------------------------------------------------------ judging
def _rank(severity) -> int:
    return RANK.get(severity or "warning", 1)


def _severity(f) -> str:
    return (f.get("severity") if isinstance(f, dict) else f.severity) or "warning"


def judge(figure: dict, base_keys: set, outcome: Outcome, value) -> Candidate:
    """The candidate `outcome` makes of `value`: the finding the suggestion is for (`figure["finding"]`) cleared, the findings
    gained (keys not in the unedited resolve), and acceptable when it cleared and nothing of a higher severity than the
    cleared finding's was gained."""
    c = Candidate(value, seconds=outcome.seconds, score=outcome.score, error=outcome.error)
    if outcome.error:
        return c
    key = tuple(figure["finding"])
    now = {sg.finding_key(f): f for f in outcome.findings}
    c.cleared = key not in now
    c.gained = [{"kind": k[0], "cause": k[1], "subject": k[2], "severity": _severity(f)}
                for k, f in now.items() if k not in base_keys]
    worst = max((_rank(g["severity"]) for g in c.gained), default=-1)
    c.acceptable = c.cleared and worst <= _rank(figure.get("severity"))
    return c


def _departure(figure: dict, value) -> float:
    return abs(value - figure["declared"]) if figure["kind"] == "bisect" else 0.0


def best_of(figure: dict, candidates: list):
    """The acceptable candidate that departs least from the declared value, ties by score, then by the order tried."""
    ok = [(k, c) for k, c in enumerate(candidates) if c.acceptable]
    if not ok:
        return None
    return min(ok, key=lambda kc: (round(_departure(figure, kc[1].value), 9),
                                   kc[1].score if kc[1].score is not None else float("inf"), kc[0]))[1]


# ------------------------------------------------------------------ the value a candidate writes
def value_of(figure: dict, value):
    """The intent expression a candidate value is written as."""
    if figure["kind"] == "set":
        return {"enum": "%s.%s" % (figure["enum"], value)}
    return {"num": value}


def _key(v) -> str:
    return "%.6f" % v if isinstance(v, (int, float)) else str(v)


# ------------------------------------------------------------------ the results file
def probe_key(s: sg.Suggestion) -> str:
    """What a probe's saved results are for: the suggestion (its id, its edits and its figure) and the digests of the files
    it edits. A changed file or edit is another key."""
    doc = json.dumps({"id": s.id, "edits": [e.to_json() for e in s.edits], "figure": s.figure, "digests": s.digests},
                     sort_keys=True)
    return hashlib.sha1(doc.encode()).hexdigest()[:16]


def results_path(board_dir, s: sg.Suggestion) -> Path:
    return Path(board_dir) / ".placemat" / PROBES / ("%s.%s.jsonl" % (s.id, probe_key(s)))


def load_results(path) -> dict:
    """{value key: Candidate} saved by earlier probes under this key."""
    out = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                c = Candidate.from_json(json.loads(line))
            except (ValueError, KeyError):
                continue
            out[_key(c.value)] = c
    except OSError:
        pass
    return out


def stale_results(board_dir, s: sg.Suggestion) -> list:
    """The saved results of this suggestion's id under another key: the script or the edit changed since they were made."""
    mine = results_path(board_dir, s)
    folder = Path(board_dir) / ".placemat" / PROBES
    return [p for p in sorted(folder.glob("%s.*.jsonl" % s.id)) if p != mine] if folder.exists() else []


def save_result(path, c: Candidate) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(c.to_json()) + "\n")


# ------------------------------------------------------------------ the sweep
class Probe:
    """One probe of a searched suggestion. `resolve(overlay)` resolves the script with `overlay` ({path: text}) in place of those
    files and returns an `Outcome`; `base` is the `Outcome` of the unedited script. `emit(event)` is told `probe`, `candidate`
    and `probe_done`. `saved` holds the candidates an earlier probe resolved (not resolved again) and `save(candidate)` keeps each
    new one. `clock` is `time.monotonic` (a test gives its own)."""

    def __init__(self, s: sg.Suggestion, resolve, base: Outcome, *, budget_s: float, candidates: int, emit=None, saved=None,
                 save=None, clock=time.monotonic, stoppers=()):
        if s.how != "searched" or not s.figure or "finding" not in s.figure:
            raise ProbeRefused("not_searched", id=s.id or s.text)
        self.s, self.figure, self.resolve = s, s.figure, resolve
        self.base_keys = {sg.finding_key(f) for f in base.findings}
        self.budget_s, self.limit = float(budget_s), int(candidates)
        self.emit, self.saved, self.save, self.clock = emit or (lambda ev: None), saved or {}, save, clock
        self.stoppers = tuple(stoppers)
        self.tried: list = []
        self.by_value: dict = {}
        self.t0 = clock()
        self.resumed = 0

    # -- one candidate
    def edits_for(self, value) -> list:
        return sg.fill(self.s.edits, self.figure, value_of(self.figure, value))

    def _spent(self) -> bool:
        return self.clock() - self.t0 >= self.budget_s

    def try_value(self, value) -> Candidate:
        key = _key(value)
        if key in self.by_value:
            return self.by_value[key]
        if key in self.saved:
            c = self.saved[key]
            self.resumed += 1
        else:
            try:
                changed = sg.apply_edits(self.edits_for(value), self.s.digests, dry_run=True)
            except sg.SuggestionError as e:
                raise ProbeRefused("edit_failed", detail=str(e)) from None
            overlay = {str(p): ch.after for p, ch in changed.files.items()}
            out = self.resolve(overlay)
            c = judge(self.figure, self.base_keys, out, value)
            if self.save is not None:
                self.save(c)
        self.by_value[key] = c
        self.tried.append(c)
        self.emit({"ev": "candidate", "id": self.s.id, "value": value, "cleared": c.cleared, "gained": c.gained,
                   "score": c.score, "seconds": round(c.seconds, 3), "acceptable": c.acceptable, "n": len(self.tried),
                   "of": self.limit, "saved": key in self.saved, **({"error": c.error} if c.error else {})})
        return c

    def _room(self) -> bool:
        return len(self.tried) < self.limit and not self._spent()

    # -- the whole probe
    def run(self) -> ProbeResult:
        f = self.figure
        self.emit({"ev": "probe", "id": self.s.id, "figure": f, "budget_s": self.budget_s, "candidates": self.limit})
        from .stop import Stopped
        result = None
        try:
            result = self._bisect() if f["kind"] == "bisect" else self._set()
        except ProbeRefused as e:
            result = ProbeResult("error", self.tried, of=self.limit, refusal=e.record)
        except (Stopped, KeyboardInterrupt):
            result = self._end("stopped")
            self.emit_done(result)
            raise
        result.resumed = self.resumed
        self.emit_done(result)
        return result

    def emit_done(self, result: ProbeResult) -> None:
        self.emit({"ev": "probe_done", "id": self.s.id, **result.to_json()})

    def _end(self, state: str, **more) -> ProbeResult:
        best = best_of(self.figure, self.tried)
        return ProbeResult(state, list(self.tried), best, of=self.limit, **more)

    def _set(self) -> ProbeResult:
        for v in self.figure["values"]:
            if not self._room():
                return self._end("budget" if self._spent() else "limit")
            self.try_value(v)
        result = self._end("found" if best_of(self.figure, self.tried) else "none")
        return result

    def _bisect(self) -> ProbeResult:
        f = self.figure
        res = float(f.get("resolution", 0.01))
        bad, good = f["declared"], f["far"]
        if not self._room():
            return self._end("budget" if self._spent() else "limit")
        far = self.try_value(good)
        if not far.acceptable:
            return self._end("none")
        probed_bad = None
        while abs(good - bad) > res + 1e-9:
            if not self._room():
                return self._end("budget" if self._spent() else "limit")
            mid = round(round((good + bad) / 2 / res) * res, 6)
            if abs(mid - good) < 1e-9 or abs(mid - bad) < 1e-9:
                break
            c = self.try_value(mid)
            if c.acceptable:
                good = mid
            else:
                bad, probed_bad = mid, c
        # the neighbour toward the declared value: probed if the search ended on one, else the declared value itself, which
        # the finding says does not clear; a step beyond `good` is resolved once more so a figure that is not monotone says so
        step = round(good + (res if bad > good else -res), 6)
        neighbour = None
        if abs(step - bad) < 1e-9 and probed_bad is not None:
            neighbour = {"value": bad, "cleared": probed_bad.cleared}
        elif abs(step - f["declared"]) < 1e-9:
            neighbour = {"value": f["declared"], "cleared": False, "declared": True}
        elif self._room():
            c = self.try_value(step)
            neighbour = {"value": step, "cleared": c.acceptable}
        result = self._end("found", neighbour=neighbour)
        if neighbour and neighbour["cleared"]:
            result.monotone = False
        return result


# ------------------------------------------------------------------ the result as a suggestion
def found_suggestion(s: sg.Suggestion, result: ProbeResult, n: int = 1) -> sg.Suggestion | None:
    """The best candidate as an instant suggestion of the same finding, `<id>.<n>`: a number is a named constant with a comment
    saying a probe found it (the constants rule), an enum member is written as it is. None where nothing cleared it."""
    if result.best is None:
        return None
    f, v = s.figure, result.best.value
    if f["kind"] == "set":
        value = {"enum": "%s.%s" % (f["enum"], v)}
        text = "Set %s to %s (found by a probe)" % (f["what"], v)
    else:
        unit = f.get("unit", "")
        near = result.neighbour
        comment = "Found by a probe of the %s for %s: %s %s clears it" % (f["name"], f["finding"][1], _num(v), unit)
        if near and near.get("value") is not None and not near.get("cleared"):
            comment += "; %s %s does not" % (_num(near["value"]), unit)
        comment += "."
        value = sg._const(f["const"], v, comment)
        text = "Set %s to %s %s (found by a probe)" % (f["what"], _num(v), unit)
    return replace(s, text=text, edits=tuple(sg.fill(s.edits, f, value)), id="%s.%d" % (s.id, n), how="instant", figure=None,
                   rank=1)


def _num(v) -> str:
    return ("%.4f" % v).rstrip("0").rstrip(".")


# ------------------------------------------------------------------ words, at the edge
def line(ev: dict) -> str:
    """One line for a probe event, for the console and `placemat watch`."""
    kind = ev.get("ev")
    if kind == "probe":
        f = ev["figure"]
        rng = ("%s to %s" % (_num(f["lo"]), _num(f["hi"]))) if f["kind"] == "bisect" else ", ".join(f["values"])
        return "probe %s: %s, %s (budget %.0f s, up to %d candidates)" % (ev["id"], f.get("what", f["name"]), rng, ev["budget_s"],
                                                                         ev["candidates"])
    if kind == "candidate":
        what = ("cleared" if ev["cleared"] else "not cleared") if not ev.get("error") else "error: %s" % error_text(ev["error"])
        gained = (", gained %d" % len(ev["gained"])) if ev["gained"] else ""
        score = (", score %.2f" % ev["score"]) if ev.get("score") is not None else ""
        return "  %s = %s: %s%s%s (%.1f s%s)" % (ev["id"], _num(ev["value"]) if isinstance(ev["value"], (int, float)) else ev["value"],
                                                what, gained, score, ev["seconds"], ", saved" if ev.get("saved") else "")
    if kind == "probe_done":
        best = ev.get("best")
        got = (_num(best["value"]) if isinstance(best["value"], (int, float)) else best["value"]) if best else None
        state = ev["state"]
        if state == "found":
            near = ev.get("neighbour")
            tail = ""
            if near and near.get("value") is not None:
                tail = ("; not monotone: it clears at %s too" % _num(near["value"])) if not ev.get("monotone", True) else \
                    "; %s does not" % _num(near["value"])
            return "found %s%s" % (got, tail)
        if state == "none":
            return "no value in the range clears it"
        if state == "stopped":
            return "stopped by you after %d of %d candidates%s" % (ev["n"], ev["of"], ": best so far %s" % got if best else "")
        if state in ("budget", "limit"):
            why = "budget spent" if state == "budget" else "candidate limit reached"
            return "%s after %d candidates%s" % (why, ev["n"], ": best so far %s" % got if best else "")
        return "probe failed: %s" % refusal_text(ev["refusal"] or {})
    return str(kind)


# ------------------------------------------------------------------ before it starts: what it will cost
def board_wide(s: sg.Suggestion) -> bool:
    """Whether each candidate resolves the whole board. An edit to one item's placement changes one step's key and the steps
    before it replay; an edit to board-wide declarations (copper, labels, rules, keepouts, the outline, a setting) changes the
    context key, and nothing replays."""
    return any(e.target is None or e.target.kind != "place" for e in s.edits if e.op != "ensure_import")


def last_resolve_s(board_dir, script) -> float | None:
    """How long the board's last recorded resolve took (the run record's `timing_s["resolve"]`), or None."""
    from .project import find_board
    from .report import latest_for
    try:
        src = find_board(script)
        rec = latest_for(Path(board_dir) / ".placemat" / "runs", src.name)
    except (ValueError, OSError, SystemExit):
        return None
    t = (rec.timing_s or {}).get("resolve") if rec is not None else None
    return float(t) if t else None


def estimate(s: sg.Suggestion, board_dir, script, candidates: int, budget_s: float) -> dict:
    """What a probe will cost, as data: whether each candidate resolves the whole board, the candidate limit, the last resolve's
    seconds (None where no run is recorded) and the total that makes (never over the budget)."""
    each = last_resolve_s(board_dir, script)
    return {"board_wide": board_wide(s), "candidates": int(candidates), "resolve_s": each, "budget_s": float(budget_s),
            "total_s": None if each is None else min(each * candidates, float(budget_s))}


def estimate_line(est: dict) -> str:
    where = ("resolves the whole board for each candidate" if est["board_wide"]
             else "resolves each candidate, replaying the steps before the first one changed")
    if est["resolve_s"] is None:
        return "this probe %s, up to %d candidates; no earlier resolve time is recorded to estimate from" % (where, est["candidates"])
    return "this probe %s, up to %d candidates, about %.0f s each (the last resolve took %.0f s): about %.0f s in all" % (
        where, est["candidates"], est["resolve_s"], est["resolve_s"], est["total_s"])


# ------------------------------------------------------------------ the resolve of an edited script, in this process
class _TimedOut(Exception):
    pass


def overlay_resolver(script, timeout_s: float):
    """`resolve(overlay)` for a probe in this process: the script resolved with `overlay` ({path: text}) read in place of those
    files, as the studio's try does it, silent on the live channel, bounded by `timeout_s` (`[studio] try_timeout_s`) at each
    step. A script that does not run, or a resolve that took too long, is an Outcome with `error`, not an exception; a stop is
    not caught."""
    from . import channel, score as score_mod
    from .previewer import resolved
    held = {}

    def resolve(overlay) -> Outcome:
        t0 = time.monotonic()

        def check(*_):
            if time.monotonic() - t0 > timeout_s:
                raise _TimedOut()
        try:
            with channel.paused(), resolved(script, None, quiet=True, progress=check, on_step=check, on_begin=check, cache=held,
                                            overlay=overlay) as r:
                findings = list(r.plan.findings)
                try:
                    total = score_mod.total(score_mod.plan_measures(r.board, r.plan), r.cfg)
                except Exception:                      # a score is a courtesy: the candidate is judged without it
                    total = None
        except _TimedOut:
            return Outcome([], None, time.monotonic() - t0, {"kind": "timeout", "limit_s": timeout_s})
        except Exception as e:
            return Outcome([], None, time.monotonic() - t0,
                           {"kind": "exception", "type": type(e).__name__, "detail": str(e).splitlines()[0] if str(e) else ""})
        return Outcome(findings, total, time.monotonic() - t0)
    return resolve


# ------------------------------------------------------------------ one whole search
def search(s: sg.Suggestion, board_dir, script, settings, *, resolve=None, emit=None, say=None, clock=time.monotonic) -> tuple:
    """Probe the searched suggestion `s` of `script`: the unedited script resolved once (what the candidates are judged against),
    the saved results of an earlier probe of the same suggestion used, the sweep run, the best candidate kept as an instant
    suggestion `<id>.1` in the board's suggestion store. Returns (the ProbeResult, the found Suggestion or None). A stop
    (`stop.Stopped`) is raised after its `probe_done` is sent and the results are saved."""
    emit = emit or (lambda ev: None)
    say = say or (lambda text: None)
    resolve = resolve or overlay_resolver(script, float(settings.studio_try_timeout_s))
    try:                                    # the script as the plan saw it, and the edit makeable on it, before any resolve is spent
        sg.apply_edits(sg.fill(s.edits, s.figure, sg.sample_value(s.figure)), s.digests, dry_run=True)
    except sg.SuggestionError as e:
        raise ProbeRefused("edit_failed", detail=str(e)) from None
    where = results_path(board_dir, s)
    old = stale_results(board_dir, s)
    if old:
        say("the script or the edit changed since an earlier probe of %s: its saved results are not used" % s.id)
        for p in old:
            try:
                p.unlink()
            except OSError:
                pass
    saved = load_results(where)
    if saved:
        say("continuing %s from %d saved result(s); a value already resolved is not resolved again" % (s.id, len(saved)))
    base = resolve({})
    if base.error:
        raise ProbeRefused("base_failed", error=base.error)
    sk = s.figure.get("finding")
    if sk is not None and tuple(sk) not in {sg.finding_key(f) for f in base.findings}:
        raise ProbeRefused("finding_gone", id=s.id)
    p = Probe(s, resolve, base, budget_s=settings.studio_probe_budget_s, candidates=settings.studio_probe_candidates,
              emit=emit, saved=saved, save=lambda c: save_result(where, c), clock=clock)
    from .stop import Stopped
    try:
        result = p.run()
    except (Stopped, KeyboardInterrupt) as stopped:     # what was found is kept: its suggestion too
        result = p._end("stopped")
        found = found_suggestion(s, result)
        if found is not None:
            sg.add_found(board_dir, script, found)
        stopped.probe = (result, found)
        raise
    found = found_suggestion(s, result)
    if found is not None:
        sg.add_found(board_dir, script, found)
    return result, found
