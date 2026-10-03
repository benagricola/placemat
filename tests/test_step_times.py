"""How long each step took: measured in the resolve, carried in the reuse record, the plan JSON and the events."""
import json

from placemat import reuse as _reuse
from placemat.preview_json import declared_sites, item_json, plan_json
from tests.test_reuse_replay import _board
from tests.test_preview_json import _plan


def test_every_step_has_a_duration_and_the_resolve_a_total():
    plan = _board(block=True).resolve()
    assert plan.steps and all(isinstance(s.seconds, float) and s.seconds >= 0 for s in plan.steps)
    assert all(s.first_seconds is None for s in plan.steps)
    assert plan.seconds >= sum(s.seconds for s in plan.steps) - 1e-6


def test_the_record_keeps_each_steps_time():
    plan = _board().resolve()
    placed = [s["step"]["seconds"] for s in plan.reuse["steps"] if "step" in s]
    assert placed and all(v >= 0 for v in placed)


def test_a_replayed_step_has_its_replay_time_and_the_time_it_first_took():
    first = _board(block=True).resolve()
    for entry in first.reuse["steps"]:                      # as if the first resolve had been slow
        if "step" in entry:
            entry["step"]["seconds"] = 4.2
    again = _board(block=True).resolve(reuse=first.reuse)
    assert again.reuse["reused"] == len(first.reuse["steps"])
    placed = [s for s in again.steps if s.kind in ("part", "cell", "block")]
    assert placed and all(s.seconds >= 0 for s in again.steps)
    assert any(s.first_seconds == 4.2 for s in placed)
    assert all(s.seconds < 4.2 for s in placed)
    assert all(e["step"]["seconds"] == 4.2 for e in again.reuse["steps"] if "step" in e)    # kept for the run after


def test_a_step_that_was_not_replayed_has_no_first_time():
    first = _board().resolve()
    again = _board(r2_radius=6.0).resolve(reuse=first.reuse)
    fresh = [s for s in again.steps if s.item == "r2"]
    assert fresh and all(s.first_seconds is None for s in fresh)


def test_a_record_with_no_times_replays_with_no_first_time():
    first = _board().resolve()
    for entry in first.reuse["steps"]:
        if "step" in entry:
            entry["step"].pop("seconds")
    again = _board().resolve(reuse=json.loads(json.dumps(first.reuse)))
    assert all(s.first_seconds is None and s.seconds >= 0 for s in again.steps)


def test_the_step_round_trips_through_the_record():
    plan = _board().resolve()
    s = plan.steps[0]
    s.seconds = 1.25
    back = _reuse.step_from_json(json.loads(json.dumps(_reuse.step_to_json(s))))
    assert back.first_seconds == 1.25 and back.seconds == 0.0


def test_the_plan_json_and_the_item_carry_the_times():
    b, plan = _plan()
    plan.steps[0].seconds, plan.steps[0].first_seconds, plan.seconds = 0.012, 4.2, 9.5
    doc = plan_json(plan, declared_sites(b))
    assert doc["seconds"] == 9.5
    assert (doc["steps"][0]["seconds"], doc["steps"][0]["first_seconds"]) == (0.012, 4.2)
    assert all("seconds" in s for s in doc["steps"])
    ev = item_json(plan, plan.steps[0], declared_sites(b))
    assert (ev["seconds"], ev["first_seconds"]) == (0.012, 4.2)
    json.dumps(doc)
