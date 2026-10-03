"""The probe (probe.py): candidates for a searched suggestion, judged by a resolve in place of the files on disk. The resolve is a
fake here (a function of the edited text), so the sweep, the judging, the results file and the found suggestion are tested
without a board; tests/test_probe_real.py runs it on a fixture."""
import json
import re

import pytest

from placemat import probe, script_edit as se, suggestions as sg
from placemat.suggestions import Edit, Suggestion, Target

SCRIPT = 'from placemat import board\nboard.track("GND", [(0, 0), (5, 5)], layer=1, chamfer=0.5)\n'
KEY = ("copper", "copper.corner", "GND")


def make(tmp_path, kind="bisect", declared=0.5, far=0.1, severity="critical"):
    path = tmp_path / "layout.py"
    path.write_text(SCRIPT)
    target = Target("track", "track GND#1", str(path), 2, 1, se.digest(SCRIPT))
    if kind == "bisect":
        figure = {"name": "chamfer", "unit": "mm", "kind": "bisect", "edit": 0, "declared": declared, "far": far,
                  "lo": far, "hi": declared, "direction": "lower clears", "resolution": 0.01, "what": "the chamfer of the GND track",
                  "const": "GND_CHAMFER_MM", "of": "need_mm - near_mm", "times": 2, "finding": list(KEY), "severity": severity}
        edits = (Edit("set_kwarg", target, {"name": "chamfer"}),)
    else:
        figure = {"name": "bend", "kind": "set", "edit": 1, "enum": "Bend", "values": ["START", "END", "BOTH"],
                  "what": "which end of the GND track's leg takes its 45", "finding": list(KEY), "severity": severity}
        edits = (Edit("ensure_import", None, {"names": ["Bend"]}, None, {}, str(path)), Edit("set_kwarg", target, {"name": "bend"}))
    return Suggestion(figure["what"], edits, 1, "x", "s3a", {str(path): se.digest(SCRIPT)}, "searched", figure), path


def finding(cause="copper.corner", subject="GND", severity="critical", kind="copper"):
    return {"kind": kind, "cause": cause, "severity": severity, "facts": {"net": subject}}


@pytest.fixture(autouse=True)
def _subject(monkeypatch):
    """finding_key reads (kind, cause, subject) from a finding's JSON: here the subject is the net."""
    real = sg.finding_key
    monkeypatch.setattr(sg, "finding_key", lambda f: (f["kind"], f["cause"], f["facts"]["net"]) if isinstance(f, dict) else real(f))


def chamfer_of(overlay):
    return float(re.search(r"chamfer=([0-9.]+)", next(iter(overlay.values()))).group(1)) if overlay else None


def resolver(threshold, log, still=None, score=None):
    """A resolve whose finding clears when the chamfer is at most `threshold`."""
    def resolve(overlay):
        v = chamfer_of(overlay)
        log.append(v)
        out = [] if v is not None and v <= threshold else [finding()]
        out += still or []
        return probe.Outcome(out, score(v) if score else v, 0.1)
    return resolve


def run(s, resolve, **kw):
    base = probe.Outcome([finding()], 1.0, 0.1)
    events = []
    kw.setdefault("budget_s", 1000)
    kw.setdefault("candidates", 12)
    p = probe.Probe(s, resolve, base, emit=events.append, **kw)
    return p.run(), events


# ------------------------------------------------------------------ bisection
def test_bisection_finds_the_largest_change_that_is_not_needed(tmp_path):
    s, _ = make(tmp_path)
    log = []
    r, events = run(s, resolver(0.3, log))
    assert r.state == "found" and r.best.value == pytest.approx(0.3, abs=0.01)
    assert log[0] == pytest.approx(0.1)                       # the far end is checked first
    assert r.neighbour["value"] == pytest.approx(0.31, abs=0.011) and r.neighbour["cleared"] is False
    assert r.monotone and r.n <= 12
    assert [e["ev"] for e in events][0] == "probe" and events[-1]["ev"] == "probe_done"
    assert [e["ev"] for e in events].count("candidate") == r.n


def test_no_value_up_to_the_far_end_clears_it(tmp_path):
    s, _ = make(tmp_path)
    r, _ = run(s, resolver(-1.0, []))
    assert r.state == "none" and r.best is None and r.n == 1


def test_a_candidate_that_gains_a_worse_finding_is_not_acceptable(tmp_path):
    s, _ = make(tmp_path)
    worse = [finding("copper.meets", "VCC", "critical")]
    r, _ = run(s, resolver(0.3, [], still=worse))             # as bad as what it cleared: acceptable
    assert r.state == "found"
    s2, _ = make(tmp_path, severity="warning")
    r, _ = run(s2, resolver(0.3, [], still=worse))            # a critical gained for a warning cleared: not
    assert r.state == "none"


def test_a_figure_that_is_not_monotone_says_so(tmp_path):
    s, _ = make(tmp_path)

    def resolve(overlay):
        v = chamfer_of(overlay)
        return probe.Outcome([] if v < 0.2 or abs(v - 0.31) < 1e-6 else [finding()], v, 0.1)
    r, _ = run(s, resolve)
    assert r.state == "found" and r.best is not None
    assert r.monotone is False or r.neighbour["cleared"] is False         # never presented as a threshold it is not
    if not r.monotone:
        assert "not monotone" in probe.line(dict(r.to_json(), ev="probe_done"))


def test_the_candidate_limit_ends_a_probe_with_the_best_so_far(tmp_path):
    s, _ = make(tmp_path)
    log = []
    r, _ = run(s, resolver(0.3, log), candidates=3)
    assert r.state == "limit" and r.n == 3 and r.best is not None
    assert "candidate limit" in probe.line(dict(r.to_json(), ev="probe_done"))


def test_the_time_budget_ends_a_probe(tmp_path):
    s, _ = make(tmp_path)
    ticks = iter(range(0, 1000, 10))
    r, _ = run(s, resolver(0.3, []), budget_s=25, clock=lambda: next(ticks))
    assert r.state == "budget" and r.n >= 1
    assert "budget spent after %d candidates" % r.n in probe.line(dict(r.to_json(), ev="probe_done"))


def test_a_stop_keeps_what_was_found_and_is_said(tmp_path):
    from placemat.stop import Stopped
    s, _ = make(tmp_path)
    n = []

    def resolve(overlay):
        n.append(1)
        if len(n) == 3:
            raise Stopped(15)
        return probe.Outcome([], 0.0, 0.1) if chamfer_of(overlay) <= 0.3 else probe.Outcome([finding()], 0.0, 0.1)
    events = []
    p = probe.Probe(s, resolve, probe.Outcome([finding()]), budget_s=100, candidates=12, emit=events.append)
    with pytest.raises(Stopped):
        p.run()
    done = events[-1]
    assert done["ev"] == "probe_done" and done["state"] == "stopped" and done["n"] == 2
    assert probe.line(done).startswith("stopped by you after 2 of 12 candidates")


# ------------------------------------------------------------------ sets
def test_a_set_tries_every_member_in_order_and_picks_the_best_score(tmp_path):
    s, path = make(tmp_path, "set")
    seen = []

    def resolve(overlay):
        text = overlay[str(path)]
        seen.append(re.search(r"bend=Bend\.(\w+)", text).group(1))
        assert "from placemat import board, Bend" in text
        ok = seen[-1] != "START"
        return probe.Outcome([] if ok else [finding()], {"START": 3, "END": 2, "BOTH": 1}[seen[-1]], 0.1)
    r, _ = run(s, resolve)
    assert seen == ["START", "END", "BOTH"] and r.state == "found" and r.best.value == "BOTH"


def test_a_set_where_nothing_clears_finds_nothing(tmp_path):
    s, _ = make(tmp_path, "set")
    r, _ = run(s, lambda o: probe.Outcome([finding()], 1.0, 0.1))
    assert r.state == "none" and r.n == 3


# ------------------------------------------------------------------ the result as a suggestion
def test_the_best_candidate_becomes_an_instant_suggestion_with_a_named_constant(tmp_path):
    s, path = make(tmp_path)
    r, _ = run(s, resolver(0.3, []))
    found = probe.found_suggestion(s, r)
    assert found.id == "s3a.1" and found.how == "instant" and found.figure is None
    done = sg.apply_edits(found.edits, found.digests, dry_run=True)
    text = done.files[str(path)].after
    assert re.search(r"chamfer=GND_CHAMFER_MM", text) and "GND_CHAMFER_MM = 0.3" in text
    assert "Found by a probe of the chamfer for copper.corner: 0.3 mm clears it; 0.31 mm does not." in text


def test_nothing_found_gives_no_suggestion(tmp_path):
    s, _ = make(tmp_path)
    r, _ = run(s, resolver(-1.0, []))
    assert probe.found_suggestion(s, r) is None


def test_a_set_member_is_written_as_the_enum(tmp_path):
    s, path = make(tmp_path, "set")
    r, _ = run(s, lambda o: probe.Outcome([], {"x": 1}["x"], 0.1))
    found = probe.found_suggestion(s, r)
    text = sg.apply_edits(found.edits, found.digests, dry_run=True).files[str(path)].after
    assert "bend=Bend.START" in text and "import board, Bend" in text


# ------------------------------------------------------------------ the results file and resume
def test_results_are_kept_and_a_second_probe_does_not_resolve_a_value_again(tmp_path):
    s, _ = make(tmp_path)
    where = probe.results_path(tmp_path, s)
    log1 = []
    r1, _ = run(s, resolver(0.3, log1), save=lambda c: probe.save_result(where, c), candidates=3)
    assert r1.state == "limit" and len(log1) == 3
    assert len(where.read_text().splitlines()) == 3
    log2 = []
    r2, ev = run(s, resolver(0.3, log2), save=lambda c: probe.save_result(where, c), saved=probe.load_results(where))
    assert not set(round(v, 6) for v in log2) & set(round(v, 6) for v in log1)
    assert r2.state == "found" and r2.resumed == 3 and r2.best.value == pytest.approx(0.3, abs=0.01)
    assert [e["saved"] for e in ev if e["ev"] == "candidate"][:3] == [True, True, True]


def test_the_key_changes_with_a_changed_file_so_old_results_are_stale(tmp_path):
    s, path = make(tmp_path)
    where = probe.results_path(tmp_path, s)
    probe.save_result(where, probe.Candidate(0.1, True))
    changed = Suggestion(s.text, s.edits, 1, "x", "s3a", {str(path): "0" * 40}, "searched", s.figure)
    assert probe.results_path(tmp_path, changed) != where
    assert probe.stale_results(tmp_path, changed) == [where]
    assert probe.load_results(probe.results_path(tmp_path, changed)) == {}


# ------------------------------------------------------------------ refusals
def test_an_instant_suggestion_is_not_probed(tmp_path):
    s, _ = make(tmp_path)
    with pytest.raises(probe.ProbeRefused):
        probe.Probe(Suggestion("x", s.edits, how="instant"), lambda o: None, probe.Outcome([]), budget_s=1, candidates=1)


def test_an_edit_that_cannot_be_made_ends_the_probe_with_an_error(tmp_path):
    s, path = make(tmp_path)
    path.write_text(SCRIPT + "# changed\n")
    r, events = run(s, resolver(0.3, []))
    assert r.state == "error" and events[-1]["state"] == "error"


def test_the_events_are_json(tmp_path):
    s, _ = make(tmp_path)
    _, events = run(s, resolver(0.3, []))
    json.dumps(events)
    assert all(probe.line(e) for e in events)
