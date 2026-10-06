"""The explore's curve (each variant's index, time and score, and when the best
and each later improvement arrived) and its stopping rules (a stall by count or
by time, the hard terms clear): kept in the report, the channel events and the
record, and rendered at the console from the data."""
import json


from placemat import channel, checkpoint, explore, score
from placemat.explore import StopRule, search
from tests import explore_boards as eb


def _run(tmp_path, seeds=range(0, 24), seconds=60, factory=None, **kw):
    return search(factory or eb.Settled(), tmp_path / "Board_layout.py", seconds=seconds, jobs=2, seeds=seeds, **kw)[0]


# ---------------------------------------------------------------- the curve
def test_the_report_keeps_the_curve_and_when_the_best_was_found(tmp_path):
    report = _run(tmp_path)
    curve = report["curve"]
    assert [c["i"] for c in curve] == list(range(report["tried"]))
    assert curve[0]["seed"] == 0 and curve[0]["score"] == report["baseline"] and curve[0]["best"] is True
    assert all(a["t"] <= b["t"] for a, b in zip(curve, curve[1:]))
    bests = [c for c in curve if c["best"]]
    assert [c["score"] for c in bests] == sorted((c["score"] for c in bests), reverse=True)
    assert len({c["score"] for c in bests}) == len(bests)                      # each improvement is a strict one
    found = report["found"]
    assert (found["i"], found["seed"], found["score"]) == (bests[-1]["i"], bests[-1]["seed"], bests[-1]["score"])
    assert found["score"] == report["best"] and found["of_variants"] == report["tried"] and found["of_seconds"] >= found["t"]
    assert report["ended"]["rule"] == "budget"
    json.dumps(report)                                                          # plain data


def test_the_channel_events_carry_the_index_the_time_the_score_and_whether_it_was_a_new_best(tmp_path, monkeypatch):
    sent = []

    class Rep:
        def send(self, ev):
            sent.append(ev)
    monkeypatch.setattr(channel, "current", lambda: Rep())
    # in the parent: explore() is run here, its workers are processes
    report = _run(tmp_path, seeds=range(0, 12))
    variants = [e for e in sent if e["ev"] == "variant"]
    assert [e["i"] for e in variants] == list(range(1, 12)) and all(e["t"] >= 0 and "score" in e and "best" in e for e in variants)
    done = [e for e in sent if e["ev"] == "explore_done"]
    assert not done or done[0]["found"]["i"] == report["found"]["i"]            # the record write is the search's own: no board here


def test_the_curve_survives_a_resume_with_its_times(tmp_path):
    state = tmp_path / "state"
    _run(tmp_path, seeds=range(0, 10), checkpoint_dir=state, keep_state=True)
    path = state / "checkpoint.jsonl"
    lines = path.read_text().split("\n")
    path.write_text("\n".join(lines[:6]) + "\n")                                # a kill after some variants
    before = [(d["v"], d["t"]) for d in checkpoint.read_lines(path) if "v" in d]
    report = _run(tmp_path, seeds=range(0, 14), checkpoint_dir=state)
    curve = report["curve"]
    assert [c["i"] for c in curve] == list(range(report["tried"])) and report["tried"] == 14
    assert [(c["seed"], c["t"]) for c in curve[1:len(before) + 1]] == before
    assert all(a["t"] <= b["t"] for a, b in zip(curve, curve[1:]))


def test_the_curve_is_in_the_checkpoint_for_a_stopped_explore_too(tmp_path):
    state = tmp_path / "state"
    _run(tmp_path, seeds=range(0, 8), checkpoint_dir=state, keep_state=True)
    lines = [d for d in checkpoint.read_lines(state / "checkpoint.jsonl") if "v" in d]
    assert all({"v", "s", "t"} <= set(d) for d in lines) and len(lines) == 7


# ---------------------------------------------------------------- the line, from the data
def test_the_summary_says_when_the_best_was_found_from_the_report_data():
    report = {"baseline": 100.0, "best": 90.0, "best_seed": 7, "tried": 34, "focus": ["a", "b"], "seconds": 43 * 60.0,
              "moves": [], "accepted": False, "terms": {},
              "found": {"i": 7, "seed": 7, "t": 312.0, "score": 90.0, "of_variants": 34, "of_seconds": 43 * 60.0},
              "ended": {"rule": "budget"}}
    lines = explore.report_lines(report)
    assert "best found at variant 7 of 34, 5 min 12 s in (of 43 min)" in lines[0]
    report["ended"] = {"rule": "stall_count", "limit": 20, "after": 27}
    assert "ended by a stall: 20 variants without improvement" in explore.report_lines(report)[0]
    report["ended"] = {"rule": "stall_time", "limit": 600.0, "after": 612.0}
    assert "ended by a stall: 10 min without improvement" in explore.report_lines(report)[0]
    report["ended"] = {"rule": "hard_clear"}
    assert "ended: the hard terms are clear" in explore.report_lines(report)[0]


def test_a_duration_is_said_in_the_unit_that_fits():
    assert [explore.duration(s) for s in (4.2, 59, 312, 43 * 60, 3725)] == ["4 s", "59 s", "5 min 12 s", "43 min", "1 h 02 min"]


# ---------------------------------------------------------------- the rules
def test_a_stall_by_count_fires_after_that_many_variants_without_an_improvement():
    r = StopRule(variants=3)
    assert [r.see(t, improved, False) for t, improved in [(1, True), (2, False), (3, False), (4, True), (5, False), (6, False)]] == [None] * 6
    assert r.see(7, False, False) == "stall_count" and r.since == 3 and r.best_t == 4


def test_a_stall_by_time_counts_from_the_last_improvement_and_is_checked_without_a_variant():
    r = StopRule(seconds=10.0)
    r.see(5.0, True, False)
    assert r.tick(14.9) is None and r.tick(15.0) == "stall_time"
    r2 = StopRule(seconds=10.0)
    r2.see(2.0, True, False)
    assert r2.see(11.0, False, False) is None and r2.see(12.5, False, False) == "stall_time"


def test_the_hard_terms_rule_fires_only_from_a_baseline_that_has_some():
    on = StopRule(hard=True, baseline_hard_clear=False)
    assert on.see(1.0, True, False) is None and on.see(2.0, True, True) == "hard_clear"
    already = StopRule(hard=True, baseline_hard_clear=True)
    assert already.see(1.0, True, True) is None                                 # nothing to wait for


def test_nothing_is_on_by_default_the_rules_are_settings():
    from placemat.settings import Settings
    s = Settings()
    assert hasattr(s, "explore_stall_variants") and hasattr(s, "explore_stall_seconds") and hasattr(s, "explore_stop_hard_clear")
    r = StopRule(s.explore_stall_variants, s.explore_stall_seconds, s.explore_stop_hard_clear, False)
    assert r.active == bool(s.explore_stall_variants or s.explore_stall_seconds or s.explore_stop_hard_clear)


def test_which_terms_are_hard_is_derived_from_the_findings_severities():
    from placemat import findings
    assert set(score.HARD_FINDINGS) == {k for k, sev in findings.SEVERITY.items() if sev == "critical"} & set(score._FINDING_WEIGHTS)
    clear = {"unplaced": {}, "findings": {"label": 3, "setup": 1}}
    assert score.hard_clear(clear)
    assert not score.hard_clear({"unplaced": {"default": 1}, "findings": {}})
    assert not score.hard_clear({"unplaced": {}, "findings": {"copper": 1}})


def test_a_stall_by_count_ends_a_time_boxed_explore_early_and_it_is_complete(tmp_path):
    state = tmp_path / "state"
    report = _run(tmp_path, seeds=None, seconds=120, factory=eb.Settled(explore_stall_variants=6), accept=True, checkpoint_dir=state)
    assert report["ended"]["rule"] == "stall_count" and report["ended"]["limit"] == 6
    assert report["seconds"] < 100
    tail = [c for c in report["curve"] if c["i"] > report["found"]["i"]]
    assert len(tail) >= 6
    assert report["accepted"] is True and (tmp_path / "Board_layout.lock.json").exists()      # complete: --accept applies
    assert checkpoint.read_lines(state / "checkpoint.jsonl")[-1] == {"recorded": True}


def test_a_stall_by_time_ends_it_too(tmp_path):
    report = _run(tmp_path, seeds=None, seconds=120, factory=eb.Settled(explore_stall_seconds=4.0))
    assert report["ended"]["rule"] == "stall_time" and report["seconds"] < 100
    assert report["ended"]["after"] >= 4.0
