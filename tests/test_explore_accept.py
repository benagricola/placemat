"""explore.search(): the lock read, the focus chosen, the variants run, what
the best would move reported, and with accept the lock written."""
from placemat import lock
from placemat.explore import search
from tests.explore_boards import KEYS, make as _make

# This factory explores the real common objective before local cleanup;
# its deterministic improving seeds are shared with the worker/route controls.


def _where(plan):
    return {k: plan.placement(k) for k in KEYS}


def test_without_accept_nothing_is_written_and_the_moves_are_reported(tmp_path):
    script = tmp_path / "Board_layout.py"
    report, entries = search(_make, script, seconds=60, jobs=2, seeds=range(0, 24))
    assert not lock.path_for(script).exists() and entries == []
    assert report["tried"] == 24 and report["best"] <= report["baseline"]
    if report["best_seed"]:
        assert report["moves"] and all(m["key"] in KEYS for m in report["moves"])


def test_accepting_writes_a_lock_that_reproduces_the_best(tmp_path):
    script = tmp_path / "Board_layout.py"
    report, entries = search(_make, script, seconds=60, jobs=2, seeds=range(0, 24), accept=True)
    assert report["best_seed"] != 0, "the fixture should have something better than the plain run"
    assert report["best"] < report["baseline"]
    assert lock.path_for(script).exists() and {e.key for e in lock.read(lock.path_for(script))} == set(KEYS)
    from placemat.explore import Explore
    best = _make().resolve(explore=Explore(report["best_seed"], frozenset(KEYS)))
    held = _make().resolve(lock=lock.read(lock.path_for(script)))
    assert _where(held) == _where(best)


def test_a_second_search_starts_from_the_lock(tmp_path):
    script = tmp_path / "Board_layout.py"
    first, _ = search(_make, script, seconds=60, jobs=2, seeds=range(0, 24), accept=True)
    again, _ = search(_make, script, seconds=60, jobs=2, seeds=range(0, 24))
    assert again["baseline"] == first["best"]


def test_releasing_drops_entries(tmp_path):
    script = tmp_path / "Board_layout.py"
    search(_make, script, seconds=60, jobs=2, seeds=range(0, 24), accept=True)
    path = lock.path_for(script)
    assert lock.release(path, ["r1"]) == ["r1"]
    assert "r1" not in {e.key for e in lock.read(path)}
    assert set(lock.release(path, None)) == set(KEYS) - {"r1"}
    assert lock.read(path) == []
