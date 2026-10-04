"""A run that dies while resolving leaves its steps' records in the run
folder, and the rerun replays them. On a real module (tests/real_modules.py)."""
import signal

import pytest

pytest.importorskip("pcbnew")

from placemat import reuse, stop
from tests.test_stop_run import _only_run, _stage_and_patch


@pytest.fixture(autouse=True)
def _console_loud():
    """A run sets the console's quiet flag for the process: put it back for the tests that read the console."""
    yield
    from placemat import console
    console.configure(quiet=False)


def test_a_rerun_after_a_death_replays_the_steps_that_were_done(tmp_path, monkeypatch):
    script, src, runner = _stage_and_patch(tmp_path, monkeypatch, "mcu")
    real = reuse.PartialLog.append
    seen = {"n": 0}

    def dying(self, entry):
        real(self, entry)
        seen["n"] += 1
        if seen["n"] == 6:
            raise stop.Stopped(signal.SIGTERM)
    monkeypatch.setattr(reuse.PartialLog, "append", dying)
    with pytest.raises(stop.Stopped):
        runner.run(script, render=False, quiet=True)
    doc, run_dir = _only_run(src)
    assert doc["status"] == "stopped" and doc["failure"]["stage"] == "resolve"
    kept = reuse.read_partial(run_dir / "reuse.partial.jsonl")
    assert len(kept["steps"]) == 6 and not (run_dir / "reuse.json").exists()

    monkeypatch.setattr(reuse.PartialLog, "append", real)
    result = runner.run(script, render=False, quiet=True)
    assert result.status == "ok"
    info = result.record.metrics["reused"]
    assert info["steps"] == 6 and "interrupted" in info["from"] and info["of"] > 6
    assert not (result.run_dir / "reuse.partial.jsonl").exists() and (result.run_dir / "reuse.json").exists()

    # what it placed is what a run that was never interrupted places
    clean_script, clean_src, _ = _stage_and_patch(tmp_path / "clean", monkeypatch, "mcu")
    clean = runner.run(clean_script, render=False, quiet=True, reuse=False)
    assert result.record.placements == clean.record.placements
    assert result.record.metrics["measures"] == clean.record.metrics["measures"]
