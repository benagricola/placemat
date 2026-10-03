"""A resolve that died leaves each completed step's reuse record in a
partial log, and the rerun replays them: only steps whose chained keys still
match, so nothing stale replays."""
import json

import pytest

from placemat import reuse
from tests.test_reuse_replay import _board, _same


class Died(BaseException):
    pass


class Dying(reuse.PartialLog):
    """A partial log whose process dies after `after` steps are logged."""

    def __init__(self, path, after):
        super().__init__(path)
        self.after, self.n = after, 0

    def append(self, entry):
        super().append(entry)
        self.n += 1
        if self.n == self.after:
            raise Died()


def _die_after(tmp_path, k, **board):
    path = tmp_path / "reuse.partial.jsonl"
    log = Dying(path, k)
    with pytest.raises(Died):
        _board(**board).resolve(partial=log)
    log.close()
    return path


def test_a_resolve_logs_every_step_as_it_goes_with_the_context_first(tmp_path):
    path = tmp_path / "reuse.partial.jsonl"
    log = reuse.PartialLog(path)
    plan = _board().resolve(partial=log)
    log.close()
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    assert lines[0]["kind"] == "header" and lines[0]["context"] == plan.reuse["context"]
    assert lines[1:] == json.loads(json.dumps(plan.reuse["steps"]))


def test_a_resolve_that_died_is_replayed_as_far_as_it_got_and_matches_a_clean_one(tmp_path):
    clean = _board().resolve()
    path = _die_after(tmp_path, 3)
    partial = reuse.read_partial(path)
    assert len(partial["steps"]) == 3
    again = _board().resolve(reuse=partial)
    _same(clean, again)
    assert again.reuse["reused"] == 3 and again.reuse["first_change"] is not None


def test_a_step_that_changed_since_is_not_replayed_nor_any_after_it(tmp_path):
    path = _die_after(tmp_path, 5)
    partial = reuse.read_partial(path)
    whole = _board().resolve().reuse                      # what a run that finished would have left
    fresh = _board(r2_radius=6.0).resolve()
    again = _board(r2_radius=6.0).resolve(reuse=partial)
    _same(fresh, again)
    from_whole = _board(r2_radius=6.0).resolve(reuse=whole).reuse
    assert 0 < again.reuse["reused"] == from_whole["reused"] and again.reuse["first_change"] == "r2"


def test_a_line_cut_short_by_the_kill_is_dropped(tmp_path):
    path = _die_after(tmp_path, 3)
    with open(path, "a") as f:
        f.write('{"key":"abc","ste')
    assert len(reuse.read_partial(path)["steps"]) == 3


def test_no_log_or_no_header_is_nothing(tmp_path):
    assert reuse.read_partial(tmp_path / "missing.jsonl") is None
    (tmp_path / "empty.jsonl").write_text("")
    assert reuse.read_partial(tmp_path / "empty.jsonl") is None


def test_the_better_record_is_the_one_that_replays_more():
    ctx = lambda n, c="c": {"version": reuse.VERSION, "context": c, "steps": [{"key": str(k)} for k in range(n)]}
    # a previous run that reached further along the same steps wins; one that went a different way loses
    assert reuse.better_of(ctx(9), ctx(4)) is not None and len(reuse.better_of(ctx(9), ctx(4))["steps"]) == 9
    other = ctx(9)
    other["steps"][2] = {"key": "different"}
    assert len(reuse.better_of(other, ctx(4))["steps"]) == 4
    assert len(reuse.better_of(ctx(9, "other"), ctx(4))["steps"]) == 4
    assert reuse.better_of(None, ctx(4))["context"] == "c" and reuse.better_of(ctx(9), None)["context"] == "c"
    assert reuse.better_of(None, None) is None


def test_a_log_costs_next_to_nothing_a_step(tmp_path):
    import time
    log = reuse.PartialLog(tmp_path / "p.jsonl")
    log.begin("ctx")
    entry = {"key": "k" * 64, "step": {"item": "x", "placement": [1.0, 2.0, 0.0, "front"]}, "commits": [[["fp", "R1"], [1.0, 2.0, 0.0, "front"]]] * 3,
             "steps": [], "findings": [], "pocketed": [], "seeded": {}, "solve": None, "items": []}
    t0 = time.perf_counter()
    for _ in range(1000):
        log.append(entry)
    per = (time.perf_counter() - t0) / 1000
    log.close()
    assert per < 0.002
