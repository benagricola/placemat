"""A finished explore keeps its variants: its checkpoint stays, marked recorded, with every variant's lock entries, so
`placemat lock --accept-seed S` takes any of them, until the next explore of the script replaces it. A recorded explore
is not resumed; an unfinished one, or a finished one whose run did not record it, still is."""
import pytest

from placemat import checkpoint, explore, lock
from placemat.explore import search
from tests import explore_boards as eb

SEEDS = range(0, 12)


def _searched(tmp_path, **kw):
    script = tmp_path / "Board_layout.py"
    report, _ = search(eb.make, script, seconds=60, jobs=2, seeds=SEEDS, checkpoint_dir=tmp_path / "state", **kw)
    return script, report


def _entries_of(seed, script):
    """The lock entries an accept of `seed` writes, as the search would make them."""
    board = eb.make()
    plan = board.resolve(explore=explore.Explore(seed, eb.FOCUS), lock=lock.read(lock.path_for(script)))
    return [(e.key, e.anchor, e.offset, e.rotation, e.face, e.declaration)
            for e in lock.entries(board, plan, [k for k in eb.KEYS if plan.placement(k) is not None])]


def _strip(entries):
    return sorted((e.key, e.anchor, e.offset, e.rotation, e.face, e.declaration) for e in entries)


def test_a_finished_explore_keeps_its_checkpoint_marked_recorded(tmp_path):
    _searched(tmp_path)
    lines = checkpoint.read_lines(tmp_path / "state" / "checkpoint.jsonl")
    assert lines[0]["kind"] == "header" and any(d.get("done") for d in lines) and lines[-1] == {"recorded": True}


def test_any_variant_of_a_finished_explore_can_be_accepted(tmp_path):
    script, report = _searched(tmp_path)
    other = next(s for s in SEEDS if s not in (0, report["best_seed"]))
    said = explore.accept_best(script, tmp_path / "state", release="x", run_id="r", seed=other)
    assert "seed %d" % other in said
    written = lock.read(lock.path_for(script))
    assert _strip(written) == sorted(_entries_of(other, tmp_path / "nothing.py"))
    assert written[0].run == "r" and written[0].release == "x"


def test_the_runs_finish_marks_the_explore_recorded_and_keeps_it(tmp_path):
    script, report = _searched(tmp_path, keep_state=True)
    assert checkpoint.read_lines(tmp_path / "state" / "checkpoint.jsonl")[-1] != {"recorded": True}
    checkpoint.finish_dir(tmp_path / "state")
    assert checkpoint.read_lines(tmp_path / "state" / "checkpoint.jsonl")[-1] == {"recorded": True}
    explore.accept_best(script, tmp_path / "state", seed=report["best_seed"])


def test_a_recorded_explore_is_not_resumed_and_the_next_explore_replaces_it(tmp_path, capsys):
    script, first = _searched(tmp_path)
    pids = tmp_path / "pids"
    again, _ = search(eb.Recording(pids), script, seconds=60, jobs=2, seeds=range(0, 4), checkpoint_dir=tmp_path / "state")
    assert pids.exists() and again["tried"] == 4                               # searched again, not taken from the last one
    assert "was not continued" not in capsys.readouterr().out
    lines = checkpoint.read_lines(tmp_path / "state" / "checkpoint.jsonl")
    assert sorted(d["v"] for d in lines if "v" in d) == [1, 2, 3]
    with pytest.raises(ValueError, match="not among"):
        explore.accept_best(script, tmp_path / "state", seed=11)


def test_seed_0_and_a_seed_not_tried_are_refused_saying_why(tmp_path):
    script, report = _searched(tmp_path)
    with pytest.raises(ValueError, match="seed 0 is the placement the explore began from"):
        explore.accept_best(script, tmp_path / "state", seed=0)
    with pytest.raises(ValueError, match="seed 99 is not among the saved explore's variants"):
        explore.accept_best(script, tmp_path / "state", seed=99)


def test_the_report_offers_the_accept_command_for_its_best(tmp_path):
    script, report = _searched(tmp_path)
    assert report["accept"] == explore.accept_command(script, report["best_seed"])
