"""An explore's checkpoint and its resume: one line per finished variant
as it goes, a digest of what makes a variant, a rerun that continues with the
untried seeds and the rest of the time, and one that refuses (or starts over)
when something changed."""
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from placemat import checkpoint, lock
from placemat.explore import search
from tests import explore_boards as eb
from tests.test_stop import DRIVER, ROOT, _wait_for

FILE = "checkpoint.jsonl"


def _seeds_of(lines):
    return [d["v"] for d in lines if "v" in d]


def _calls(pids) -> int:
    """The variants the workers built so far: each one a line in the file."""
    p = Path(pids)
    return len(p.read_text().split()) if p.exists() else 0


def _search(tmp_path, seeds=None, seconds=60, **kw):
    pids = tmp_path / "pids"
    return search(eb.Recording(pids), tmp_path / "Board_layout.py", seconds=seconds, jobs=2, seeds=seeds,
                  checkpoint_dir=tmp_path / "state", **kw)


def test_a_finished_variant_is_a_line_with_the_header_first_and_a_done_line_last(tmp_path):
    _search(tmp_path, seeds=range(0, 10), keep_state=True)
    lines = checkpoint.read_lines(tmp_path / "state" / FILE)
    head = lines[0]
    assert head["kind"] == "header" and head["digest"] and set(head["parts"]) == set(checkpoint.PARTS)
    assert head["baseline"]["score"] > 0 and head["baseline"]["measures"] and head["budget"]["seeds"] == 10
    assert sorted(_seeds_of(lines)) == list(range(1, 10))
    assert lines[-1]["done"] is True and lines[-1]["t"] > 0
    assert all("t" in d and "s" in d for d in lines if "v" in d)
    # a variant that beat every one before it carries its measures; the others are lean
    assert any("m" in d for d in lines if "v" in d)
    assert all("m" not in d for d in lines if "v" in d and d["s"] >= head["baseline"]["score"])


def test_a_complete_explore_clears_its_checkpoint_and_keeps_the_best(tmp_path):
    _search(tmp_path, seeds=range(0, 10))
    assert not (tmp_path / "state" / FILE).exists() and (tmp_path / "state" / "best.json").exists()


def test_a_resume_tries_only_the_untried_seeds_and_gets_the_same_answer(tmp_path):
    full = tmp_path / "full"
    full.mkdir()
    whole, _ = _search(full, seeds=range(0, 24))
    # a run that was killed after some variants: the file as it stood
    _search(tmp_path, seeds=range(0, 10), keep_state=True)
    path = tmp_path / "state" / FILE
    lines = path.read_text().split("\n")
    path.write_text("\n".join(lines[:5]) + "\n" + lines[5][:12])            # the header, 4 variants, and a line cut short
    (tmp_path / "pids").unlink()
    tried = set(_seeds_of(checkpoint.read_lines(path)))
    assert len(tried) == 4
    report, _ = _search(tmp_path, seeds=range(0, 24))
    assert _calls(tmp_path / "pids") == 23 - len(tried)                       # the untried only
    assert report["tried"] == 24 and report["best_seed"] == whole["best_seed"] and report["best"] == whole["best"]
    assert report["terms"] == whole["terms"]


def test_a_resumed_time_boxed_explore_spends_the_rest_of_the_budget(tmp_path):
    _search(tmp_path, seeds=range(0, 8), keep_state=True)
    path = tmp_path / "state" / FILE
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    lines = [d for d in lines if "done" not in d]
    lines[-1]["t"] = 9.5                                                      # 9.5 s of 10 spent
    path.write_text("".join(json.dumps(d) + "\n" for d in lines))
    (tmp_path / "pids").unlink()
    report, _ = _search(tmp_path, seconds=10)
    assert _calls(tmp_path / "pids") < 20      # half a second of budget is left, and a worker takes a while to start: a
    assert report["tried"] >= 8                # whole budget spent again would be hundreds


def test_nothing_left_to_do_starts_no_workers(tmp_path):
    _search(tmp_path, seeds=range(0, 8), keep_state=True)
    (tmp_path / "pids").unlink()
    report, _ = _search(tmp_path, seeds=range(0, 8), keep_state=True)           # a finished explore, asked again
    assert not (tmp_path / "pids").exists() and report["tried"] == 8


def test_what_changed_is_named_and_resume_refuses(tmp_path):
    _search(tmp_path, seeds=range(0, 6), keep_state=True)
    script = tmp_path / "Board_layout.py"
    lock.write(lock.path_for(script), [lock.LockEntry("zz", None, None, (1.0, 2.0), 0.0, "front", "d")])
    with pytest.raises(checkpoint.ResumeRefused) as e:
        _search(tmp_path, seeds=range(0, 6), resume="yes")
    assert "the lock changed" in str(e.value) and "script" not in str(e.value)
    script.write_text("# edited\n")
    with pytest.raises(checkpoint.ResumeRefused) as e:
        _search(tmp_path, seeds=range(0, 6), resume="yes")
    assert "the script and the lock changed" in str(e.value)


def test_without_resume_a_checkpoint_that_is_not_this_explore_is_dropped_and_a_new_one_begins(tmp_path, capsys):
    _search(tmp_path, seeds=range(0, 6), keep_state=True)
    (tmp_path / "Board_layout.py").write_text("# edited\n")
    (tmp_path / "pids").unlink()
    report, _ = _search(tmp_path, seeds=range(0, 6))
    assert _calls(tmp_path / "pids") == 5 and report["tried"] == 6                # all of them again: none were this explore's
    assert "was not continued: the script changed" in capsys.readouterr().out


def test_no_resume_starts_over(tmp_path):
    _search(tmp_path, seeds=range(0, 6), keep_state=True)
    (tmp_path / "pids").unlink()
    _search(tmp_path, seeds=range(0, 6), resume="no")
    assert _calls(tmp_path / "pids") == 5


def test_a_changed_setting_or_focus_is_not_the_same_explore(tmp_path):
    _search(tmp_path, seeds=range(0, 6), keep_state=True)
    with pytest.raises(checkpoint.ResumeRefused, match="the focus changed"):
        _search(tmp_path, seeds=range(0, 6), resume="yes", keys=("r1", "r2"))


def test_the_checkpoint_is_bounded(tmp_path):
    ck = checkpoint.Checkpoint(tmp_path, {k: "x" for k in checkpoint.PARTS}, [], max_variants=5)
    ck.start(10.0, {"a": 1}, 60, None)
    for seed in range(1, 40):
        ck.variant(seed, 20.0, {"a": 2}, seed * 0.1, None)
    ck.close()
    lines = checkpoint.read_lines(tmp_path / FILE)
    assert len(_seeds_of(lines)) == 5 and lines[-1] == {"full": 5}


def test_writing_the_checkpoint_costs_next_to_nothing(tmp_path):
    ck = checkpoint.Checkpoint(tmp_path, {k: "x" for k in checkpoint.PARTS}, ["a", "b"])
    m = {"airwire_mm": 40.695, "crossings": {"pair": 0, "plane": 6, "signal": 0}, "drc": 0, "findings": {},
         "giveway": 0, "link_excess": 0.0, "pushes": 0.0, "unplaced": {}}
    ck.start(100.0, m, 60, None)
    t0 = time.perf_counter()
    n = 2000
    for seed in range(1, n + 1):
        ck.variant(seed, 100.0 - seed * 1e-3, m, seed * 0.1, None)         # every one an improvement: the dearest line
    per = (time.perf_counter() - t0) / n
    ck.close()
    assert per < 0.002, "a line costs %.3f ms" % (per * 1000)


def test_a_real_stop_then_a_resume_skips_the_seeds_already_tried(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", DRIVER, str(tmp_path)], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    state = tmp_path / "ckpt" / FILE
    try:
        assert _wait_for(lambda: state.exists() and len(checkpoint.read_lines(state)) >= 8)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 143
    saved = checkpoint.read_lines(tmp_path / "ckpt" / FILE)
    assert saved[-1].get("stop") == "SIGTERM"
    tried = set(_seeds_of(saved))
    assert len(tried) >= 7
    top = max(tried) + 6
    (tmp_path / "pids").unlink()
    report, _ = search(eb.Recording(tmp_path / "pids"), tmp_path / "Board_layout.py", seconds=600, jobs=2,
                       seeds=range(0, top + 1), checkpoint_dir=tmp_path / "ckpt")
    assert _calls(tmp_path / "pids") == top - len(tried)
    assert report["tried"] == top + 1
