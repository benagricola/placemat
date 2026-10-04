# tests/test_arrangement_proof.py
import types

from placemat import arrangement_run as run
from placemat.checks import Verdict
from placemat.values import Beside, Edge, Part
from tests.arrangement_support import module


def report(real=None, unconnected=0):
    return types.SimpleNamespace(real=real or {}, unconnected=unconnected)


def test_a_clean_plan_has_no_refusal_and_a_critical_finding_or_an_unplaced_item_has_one():
    b = module()
    plan = b.resolve()
    assert run.plan_refusals(plan, plan) == []
    from placemat.findings import Finding, FindingCause as C
    plan.findings.append(Finding(C.FIXED_PART, {"item": "c_in", "freedom": "fixed", "why": {"code": "edge", "what": "body", "box": [0, 0, 1, 1], "verdict": "outside", "margin_mm": 0.0}}))
    got = run.plan_refusals(plan, plan)
    assert {"form": "finding", "cause": "fixed.part", "item": "c_in"} in got
    plan.steps[1].placement = None
    assert {"form": "unplaced", "item": plan.steps[1].item} in run.plan_refusals(plan, plan)


def test_a_cell_standing_elsewhere_than_in_the_default_is_refused_by_name():
    a, b = module().resolve(), module().resolve()
    p = b.steps[0].placement
    b.steps[0].placement = p.moved(1.0, 0.0)
    b.steps[0].kind = "cell"
    a.steps[0].kind = "cell"
    assert {"form": "nested_cell", "item": a.steps[0].item} in run.plan_refusals(b, a)


def test_drc_buckets_and_unconnected_are_refusals_only_beyond_the_default():
    assert run.drc_refusals(report({"clearance": 2, "track_width": 1}, 3), 3) == [
        {"form": "drc", "bucket": "clearance", "count": 2}, {"form": "drc", "bucket": "track_width", "count": 1}]
    assert run.drc_refusals(report({}, 4), 3) == [{"form": "unconnected", "count": 4, "default": 3}]
    assert run.drc_refusals(report({}, 3), 3) == []


def test_a_failed_verdict_is_a_refusal_unless_a_script_accepted_it():
    failed = Verdict("hot-loop", "c_in", 9.0, "mm2", 5.0, False)
    accepted = Verdict("hot-loop", "u1", 9.0, "mm2", 5.0, False, accepted="accepted (<= 10): why")
    unjudged = Verdict("heat", "u1", 1.0, "C", None, None)
    assert run.verdict_refusals([failed, accepted, unjudged]) == [{"form": "verdict", "check": "hot-loop", "item": "c_in"}]
