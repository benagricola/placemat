"""A real explore (the UsbC fixture module, as a real `placemat run`) ended by a stall: it is complete (--accept
applies), and its curve is kept in run.json and in the explore record after the checkpoint is gone."""
import json

import pytest

pytest.importorskip("pcbnew")

from tests.test_stop_run import _only_run, _run_explore, _searched_module


def test_a_real_explore_ended_by_a_stall_is_complete_and_keeps_its_curve(tmp_path):
    mod, script, src = _searched_module(tmp_path)
    (mod / "placemat.toml").write_text("[explore]\nstall_variants = 8\n")
    proc = _run_explore(script, 600, "--accept")
    out, err = proc.communicate(timeout=300)
    assert proc.returncode == 0, out + err
    assert "ended by a stall: 8 variants without improvement" in out and "best found at variant" in out, out
    assert "accepted: written to the lock" in out and (mod / "UsbC_layout.lock.json").exists()
    doc, run_dir = _only_run(src)
    ex = doc["metrics"]["explore"]
    assert doc["status"] == "ok" and ex["ended"]["rule"] == "stall_count" and ex["ended"]["limit"] == 8
    assert ex["accepted"] is True and ex["found"]["of_variants"] == ex["tried"] == len(ex["curve"])
    assert ex["found"]["i"] == [c["i"] for c in ex["curve"] if c["best"]][-1] and ex["seconds"] < 300
    kept = sorted((mod / ".placemat" / "views" / "explore").glob("*.json"))
    assert len(kept) == 1
    record = json.loads(kept[0].read_text())
    assert record["ended"]["rule"] == "stall_count" and record["curve"] == ex["curve"] and record["found"] == ex["found"]
    assert all({"i", "t", "score", "best"} <= set(v) for v in record["variants"])
    assert record["run"] == doc["run_id"] == run_dir.name                                          # the run it was part of
    best = json.loads((kept[0].parent / "best" / kept[0].name).read_text())                       # the best variant's own plan, for the studio
    assert best["items"] and best["score"]["total"] == round(record["best"], 3) and isinstance(best["model_jobs"], list)
    placed = {it["key"]: it for it in best["items"]}
    for key, pl in next(v for v in record["variants"] if v["seed"] == record["best_seed"])["placements"].items():
        if pl is not None:
            assert placed[key]["at"] == [round(pl[0], 3), round(pl[1], 3)] and placed[key]["face"] == pl[3]
    assert not (mod / ".placemat" / "explore" / "UsbC_layout" / "checkpoint.jsonl").exists()
