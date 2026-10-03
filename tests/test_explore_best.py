"""best.json: the best variant's lock entries, kept as an explore goes, and
what accepting it checks before it writing the lock."""
import pytest

from placemat import checkpoint, explore, lock
from placemat.explore import search
from tests import explore_boards as eb


def _searched(tmp_path):
    script = tmp_path / "Board_layout.py"
    report, _ = search(eb.make, script, seconds=60, jobs=2, seeds=range(0, 24), checkpoint_dir=tmp_path / "state")
    assert report["best_seed"] != 0
    return script, report


def test_the_best_is_kept_as_it_is_found_and_matches_the_report(tmp_path):
    script, report = _searched(tmp_path)
    doc = checkpoint.read_best(tmp_path / "state")
    assert doc["seed"] == report["best_seed"] and doc["score"] == report["best"] and set(doc["focus"]) == set(eb.KEYS)
    assert {e["key"] for e in doc["entries"]} == set(eb.KEYS)
    assert not list((tmp_path / "state").glob("*.tmp"))          # replaced whole, nothing left beside


def test_accepting_what_was_kept_writes_the_lock_the_search_would_have(tmp_path):
    script, report = _searched(tmp_path)
    explore.accept_best(script, tmp_path / "state", release="x", run_id="r", seed=report["best_seed"])
    other = tmp_path / "other"
    other.mkdir()
    search(eb.make, other / "Board_layout.py", seconds=60, jobs=2, seeds=range(0, 24), accept=True)
    mine, theirs = lock.read(lock.path_for(script)), lock.read(lock.path_for(other / "Board_layout.py"))
    strip = lambda es: [(e.key, e.anchor, e.offset, e.rotation, e.face, e.declaration, e.turn) for e in es]
    assert strip(mine) == strip(theirs) and mine[0].run == "r" and mine[0].release == "x"


def test_accepting_refuses_another_seed_a_changed_lock_and_nothing_saved(tmp_path):
    script, report = _searched(tmp_path)
    with pytest.raises(ValueError, match="not %d" % (report["best_seed"] + 1)):
        explore.accept_best(script, tmp_path / "state", seed=report["best_seed"] + 1)
    with pytest.raises(ValueError, match="no saved explore"):
        explore.accept_best(script, tmp_path / "empty")
    lock.write(lock.path_for(script), [lock.LockEntry("zz", None, None, (1.0, 2.0), 0.0, "front", "d")])
    with pytest.raises(ValueError, match="lock changed"):
        explore.accept_best(script, tmp_path / "state")
