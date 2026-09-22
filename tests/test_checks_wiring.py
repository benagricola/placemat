"""The design checks, run on every finished board and recorded with the run.
They were written and tested, and reachable as `placemat check`; nothing in
`placemat run` called them. Pure: synthetic boards, no KiCad."""
from placemat import checks, report
from placemat.report import RunRecord
from placemat.settings import Settings
from tests.fixtures import board_geometry
from tests.test_checks import buck


def _judged(limits=None):
    cfg = Settings(check_limits=dict(limits or {}))
    return checks.run_checks(board_geometry(list(buck())), **checks.kwargs_from(cfg))


def test_the_check_arguments_come_from_the_settings_once():
    """`placemat check` and `placemat run` must judge by the same numbers, so
    the mapping from settings to arguments has one home."""
    cfg = Settings(check_ambient_c=85.0, check_limits={"hot-loop": 20.0})
    kw = checks.kwargs_from(cfg)
    assert kw["ambient_c"] == 85.0 and kw["limits"] == {"hot-loop": 20.0}


def test_a_hot_loop_over_its_limit_is_a_failed_verdict_in_the_run_record():
    from tests.fixtures import footprint
    # a loop with a return: 8.4 mm2, the parallelogram test_checks measures
    loop = [footprint("C1", 10, 10, nets=("VIN", "GND"), fields={"Pm.Loop": "hot"}),
            footprint("U1", 14, 13, nets=("VIN", "GND"), fields={"Pm.Loop": "hot"})]
    cfg = Settings(check_limits={"hot-loop": 5.0})
    rec = RunRecord(run_id="a1", board="b", status="ok")
    checks.record(rec, checks.run_checks(board_geometry(loop), **checks.kwargs_from(cfg)))
    (v,) = [v for v in rec.verdicts if v["check"] == "hot-loop"]
    assert v["ok"] is False and v["value"] > 5.0
    assert rec.metrics["checks_failed"] == 1


def test_a_check_with_no_limit_set_is_recorded_as_not_judged():
    rec = RunRecord(run_id="a1", board="b", status="ok")
    checks.record(rec, _judged())
    loops = [v for v in rec.verdicts if v["check"] == "hot-loop"]
    assert loops and loops[0]["ok"] is None
    assert rec.metrics["checks_unjudged"] >= 1


def test_a_missing_pm_fact_is_not_judged_rather_than_passed():
    """A check that silently passes because a footprint lacks `Pm.Pd` or a
    thermal resistance is worse than no check."""
    rec = RunRecord(run_id="a1", board="b", status="ok")
    checks.record(rec, _judged())
    (heat,) = [v for v in rec.verdicts if v["check"] == "heat"]
    assert heat["subject"] == "U1"          # carries Pm.Pd but no thermal resistance
    assert heat["ok"] is None and "ThetaJ" in heat["note"]
    assert rec.metrics["checks_failed"] == 0


def test_a_board_with_no_facts_records_no_verdicts_and_says_so():
    rec = RunRecord(run_id="a1", board="b", status="ok")
    said = checks.record(rec, [])
    assert rec.verdicts == [] and rec.metrics["checks_failed"] == 0
    assert "no Pm.* facts" in said[0]


def test_a_verdict_that_regressed_since_the_last_run_is_named_in_the_impact():
    before = RunRecord(run_id="a1", board="b", status="ok",
                       verdicts=[{"check": "hot-loop", "subject": "buck", "ok": True,
                                  "value": 12.0, "unit": "mm2", "limit": 20.0, "note": ""}])
    after = RunRecord(run_id="a2", board="b", status="ok",
                      verdicts=[{"check": "hot-loop", "subject": "buck", "ok": False,
                                 "value": 31.0, "unit": "mm2", "limit": 20.0, "note": ""}])
    text = report.impact(before, after)
    assert "hot-loop buck" in text and "31" in text and "FAIL" in text


def test_the_docs_say_every_run_runs_the_checks():
    from pathlib import Path
    api = " ".join(Path("skills/placemat/references/api.md").read_text().split())
    assert "Every `placemat run` runs the same checks" in api
    assert "## To 0.16" in Path("skills/placemat/references/migration.md").read_text()
