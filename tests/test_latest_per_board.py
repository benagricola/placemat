"""Boards laid out from one directory share its `.placemat/runs`; each run
is compared with, and reuses, the last run of its own board."""
from placemat.report import RunRecord, latest_for, record_latest


def _run(runs, run_id, board):
    d = runs / run_id
    d.mkdir(parents=True)
    rec = RunRecord(run_id=run_id, board=board, status="ok", paths={"run_dir": str(d)})
    return rec.save(d / "run.json")


def test_the_last_run_of_the_same_board_is_found_after_another_boards(tmp_path):
    record_latest(tmp_path, _run(tmp_path, "a1", "Logic"), "Logic")
    record_latest(tmp_path, _run(tmp_path, "b1", "Moisture"), "Moisture")
    assert latest_for(tmp_path, "Logic").run_id == "a1"
    assert latest_for(tmp_path, "Moisture").run_id == "b1"


def test_the_directorys_latest_still_names_the_most_recent_run(tmp_path):
    record_latest(tmp_path, _run(tmp_path, "a1", "Logic"), "Logic")
    record_latest(tmp_path, _run(tmp_path, "b1", "Moisture"), "Moisture")
    assert RunRecord.load(tmp_path / "latest.json").run_id == "b1"


def test_a_board_with_no_run_of_its_own_has_no_latest(tmp_path):
    record_latest(tmp_path, _run(tmp_path, "b1", "Moisture"), "Moisture")
    assert latest_for(tmp_path, "Logic") is None


def test_a_directory_from_before_takes_its_latest_when_the_board_matches(tmp_path):
    """Runs recorded before per-board records: latest.json alone."""
    (tmp_path / "latest.json").write_text(_run(tmp_path, "a1", "Logic").read_text())
    assert latest_for(tmp_path, "Logic").run_id == "a1"
    assert latest_for(tmp_path, "Moisture") is None
