"""Accepting one check verdict, with a reason: `board.accept`. Pure: synthetic
boards, no KiCad."""
import json

import pytest

from placemat import checks, reuse
from placemat.checks import Acceptance
from placemat.layout import Board
from placemat.report import RunRecord
from tests.fixtures import board_geometry, footprint, track
from tests.test_checks import buck

WHY = "the package's pitch sets it"


def _parts():
    return list(buck())


def _vin(width):
    return [track("VIN", 8.6, 10, 8.6, 13, w=width), track("VIN", 8.6, 13, 12.6, 13, w=width)]


def _judged(acceptances, width=0.5, parts=None, **kw):
    geometry = board_geometry(parts or _parts(), copper=_vin(width))
    return checks.judge(checks.run_checks(geometry, **kw), acceptances)


def _accept(check, subject, why=WHY, **bound):
    return Acceptance(check, subject, why=why, **bound)


def _verdict(verdicts, check, subject):
    (v,) = [v for v in verdicts if v.check == check and v.subject == subject]
    return v


def test_a_failing_current_path_accepted_at_its_value_reads_accepted_with_the_why():
    verdicts, outcomes = _judged([_accept("current-path", "VIN", at_least=0.5)])
    v = _verdict(verdicts, "current-path", "VIN")
    assert v.accepted and "accepted (>= 0.5): " + WHY in v.line() and "FAIL" not in v.line()
    assert [o.outcome for o in outcomes] == ["accepted"]
    rec = RunRecord(run_id="a1", board="b", status="ok")
    lines = checks.record(rec, verdicts, outcomes)
    assert rec.metrics["checks_accepted"] == 1 and rec.metrics["checks_failed"] == 0
    assert " 1 accepted" in lines[0] and " 0 failed" in lines[0]
    assert any("current-path VIN" in l and WHY in l for l in lines[1:])


def test_the_acceptance_fails_once_the_copper_is_narrower_than_the_bound():
    verdicts, outcomes = _judged([_accept("current-path", "VIN", at_least=0.5)], width=0.4)
    v = _verdict(verdicts, "current-path", "VIN")
    assert not v.accepted and v.ok is False and "FAIL" in v.line()
    assert "past its acceptance of >= 0.5: " + WHY in v.note
    assert [o.outcome for o in outcomes] == ["past"]
    rec = RunRecord(run_id="a1", board="b", status="ok")
    checks.record(rec, verdicts, outcomes)
    assert rec.metrics["checks_failed"] == 1 and rec.metrics["checks_accepted"] == 0


def test_at_most_on_heat_is_accepted_within_and_fails_past():
    hot = footprint("U1", 14, 13, nets=("VIN", "SW"),
                    fields={"Pm.Pd": "0.6W", "Pm.Tjmax": "125C", "Pm.Thetaja": "80C/W"})
    parts = [p for p in _parts() if p.ref != "U1"] + [hot]
    verdicts, outcomes = _judged([_accept("heat", "U1", at_most=150.0)], parts=parts)
    v = _verdict(verdicts, "heat", "U1")
    assert v.value == pytest.approx(148.0) and v.accepted and "accepted (<= 150)" in v.line()
    verdicts, outcomes = _judged([_accept("heat", "U1", at_most=140.0)], parts=parts)
    v = _verdict(verdicts, "heat", "U1")
    assert not v.accepted and v.ok is False and "past its acceptance of <= 140" in v.note
    assert outcomes[0].outcome == "past"


def test_an_acceptance_with_no_verdict_or_a_passing_one_is_not_accepted_into_anything():
    verdicts, outcomes = _judged([_accept("current-path", "NOPE", at_least=0.1),
                                  _accept("current-path", "VIN", at_least=0.1)], width=2.0)
    assert [o.outcome for o in outcomes] == ["unmatched", "not needed"]
    assert not any(v.accepted for v in verdicts)


def test_the_unmatched_and_not_needed_acceptances_are_setup_findings():
    verdicts, outcomes = _judged([_accept("current-path", "NOPE", at_least=0.1),
                                  _accept("current-path", "VIN", at_least=0.1)], width=2.0)
    found = checks.findings_of(outcomes)
    assert [f.kind for f in found] == ["setup", "setup"]
    assert "current-path NOPE" in found[0] and "no verdict" in found[0]
    assert "current-path VIN" in found[1] and "not needed: the check passes" in found[1]
    assert checks.findings_of(_judged([_accept("current-path", "VIN", at_least=0.5)])[1]) == []


def test_a_verdict_nobody_judged_is_not_accepted_either():
    verdicts, outcomes = _judged([_accept("hot-loop", "hot", at_most=1.0)])      # no hot-loop limit set
    assert outcomes[0].outcome == "not needed" and not any(v.accepted for v in verdicts)


def test_the_run_record_lists_each_acceptance_with_its_outcome():
    verdicts, outcomes = _judged([_accept("current-path", "VIN", at_least=0.5),
                                  _accept("keep-out", "GONE", at_least=1.0)])
    rec = RunRecord(run_id="a1", board="b", status="ok")
    checks.record(rec, verdicts, outcomes)
    first, second = rec.acceptances
    assert first == {"check": "current-path", "subject": "VIN", "side": "at_least", "bound": 0.5, "why": WHY,
                     "value": pytest.approx(0.5), "outcome": "accepted"}
    assert second["outcome"] == "unmatched" and second["value"] is None
    json.dumps(rec.acceptances)


def test_a_board_with_no_facts_still_reports_its_acceptances():
    rec = RunRecord(run_id="a1", board="b", status="ok")
    verdicts, outcomes = checks.judge([], [_accept("heat", "U9", at_most=100.0)])
    lines = checks.record(rec, verdicts, outcomes)
    assert rec.acceptances[0]["outcome"] == "unmatched" and "no Pm.* facts" in lines[0]


def test_no_acceptances_leave_the_record_and_the_head_line_as_they_were():
    verdicts, outcomes = _judged([])
    rec = RunRecord(run_id="a1", board="b", status="ok")
    lines = checks.record(rec, verdicts, outcomes)
    assert outcomes == [] and rec.acceptances == [] and rec.metrics["checks_accepted"] == 0
    assert "accepted" not in lines[0]


def test_the_impact_names_a_failure_that_became_accepted():
    from placemat import report
    row = {"check": "current-path", "subject": "VIN", "ok": False, "value": 0.5, "unit": "mm", "limit": 1.4,
           "note": "", "accepted": False}
    after = dict(row, accepted=True)
    text = report.impact(RunRecord(run_id="a1", board="b", status="ok", verdicts=[row]),
                         RunRecord(run_id="a2", board="b", status="ok", verdicts=[after]))
    assert "FAIL -> accepted" in text


# ----------------------------------------------------------------- declaring

def _board():
    return Board(board_geometry([footprint("R1", 30, 10, nets=("V48", "GND"))]), edge_margin=1.0)


def test_board_accept_is_carried_on_the_plan():
    b = _board()
    a = b.accept("current-path", "V48", at_least=0.35, why=WHY)
    assert b.resolve().acceptances == [a]
    assert a == Acceptance("current-path", "V48", at_least=0.35, why=WHY)


@pytest.mark.parametrize("args, bound, text", [
    (("nonsense", "X"), {"at_least": 1.0}, "unknown check"),
    (("keep-out", "X"), {}, "exactly one"),
    (("keep-out", "X"), {"at_least": 1.0, "at_most": 2.0}, "exactly one"),
    (("keep-out", "X"), {"at_most": 1.0}, "at_least"),
    (("heat", "X"), {"at_least": 1.0}, "at_most"),
    (("keep-out", "X"), {"at_least": 1.0, "why": ""}, "why"),
])
def test_each_refusal(args, bound, text):
    b = _board()
    bound = {"why": WHY, **bound}
    with pytest.raises(ValueError, match=text):
        b.accept(*args, **bound)
    assert b._acceptances == []


def test_the_same_check_and_subject_twice_is_refused():
    b = _board()
    b.accept("keep-out", "SW", at_least=1.0, why=WHY)
    with pytest.raises(ValueError, match="already accepted"):
        b.accept("keep-out", "SW", at_least=0.5, why="again")
    b.accept("keep-out", "SW2", at_least=1.0, why=WHY)


def test_an_acceptance_changes_no_digest_a_placement_or_copper_step_reads():
    plain, accepting = _board(), _board()
    accepting.accept("current-path", "V48", at_least=0.35, why=WHY)
    assert reuse.context_key(plain, "tool") == reuse.context_key(accepting, "tool")
    plan_a, plan_b = plain.resolve(), accepting.resolve()
    assert plan_a.reuse["context"] == plan_b.reuse["context"]
    assert [s["key"] for s in plan_a.reuse["steps"]] == [s["key"] for s in plan_b.reuse["steps"]]
