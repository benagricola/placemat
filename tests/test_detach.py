"""`--detach` and `placemat watch <pid> --summary`: a long command started apart from the shell, and its outcome read from
the records it leaves - its progress file, its run record and its explore's report - once it has ended."""
import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from placemat import channel, detach

ROOT = Path(__file__).resolve().parent.parent


def _placemat(*args, cwd, timeout):
    """`placemat ...` as a process in `cwd`, importing this checkout's placemat whatever the folder."""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src")] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]))
    return subprocess.run([sys.executable, "-m", "placemat", *map(str, args)], cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=env)


def _board(tmp_path, pid, status="ok", events=(), metrics=None, failure=None, record_pid=True):
    """A board folder with a run folder like a run leaves: its progress file and run.json."""
    board = tmp_path / "board"
    run_dir = board / ".placemat" / "runs" / "abc123"
    run_dir.mkdir(parents=True)
    script = board / "B_layout.py"
    script.write_text("")
    hello = {"ev": "hello", "pid": pid, "command": "run", "script": str(script), "label": "t1"}
    (run_dir / "progress.jsonl").write_text("\n".join(json.dumps(e) for e in (hello, *events)) + "\n")
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": "abc123", "board": "B", "status": status, "pid": pid if record_pid else None, "metrics": metrics or {},
        "findings": ["f1"], "failure": failure, "paths": {}}))
    return board, script, run_dir


METRICS = {"drc_real": {}, "unconnected": 2, "outstanding": {}, "airwire_mm": 41.5, "crossings": 3, "congestion": 0.12,
           "explore": {"tried": 24, "seconds": 300.0, "baseline": 120.3, "best": 110.2, "best_seed": 7, "moves": [{"key": "r1"}],
                       "baseline_remapped": 118.0, "best_remapped": 104.5, "accepted": False,
                       "accept": "placemat lock B_layout.py --accept-seed 7", "taken_seed": 7,
                       "routes": [{"seed": 0, "score": 120.3, "closure": 0.9, "closure_clean": 0.8, "open_after": 2, "seconds": 30.0},
                                  {"seed": 7, "score": 110.2, "closure": 1.0, "closure_clean": 1.0, "open_after": 0, "seconds": 28.0}]}}


def test_the_outcome_of_an_ended_explore_run_is_built_from_its_records(tmp_path):
    pid = 999999991
    board, script, run_dir = _board(tmp_path, pid, metrics=METRICS,
                                    events=[{"ev": "explore_done", "best_seed": 7}, {"ev": "done", "record": "RECORD"}])
    (run_dir / "progress.jsonl").write_text((run_dir / "progress.jsonl").read_text().replace("RECORD", str(run_dir / "run.json")))
    seen = {"channel": {"pid": pid, "command": "run", "script": str(script), "label": "t1", "progress": str(run_dir / "progress.jsonl")},
            "detached": None}
    o = detach.outcome(tmp_path, pid, seen)
    assert o["ended"] == "done" and o["record"] == str(run_dir / "run.json") and o["error"] is None
    assert o["run"]["status"] == "ok" and o["run"]["id"] == "abc123" and o["run"]["dir"] == str(run_dir)
    assert o["run"]["unconnected"] == 2 and o["run"]["airwire_mm"] == 41.5
    e = o["explore"]
    assert (e["best_seed"], e["best_remapped"], e["accepted"], e["taken_seed"]) == (7, 104.5, False, 7)
    assert [r["closure_clean"] for r in e["routes"]] == [0.8, 1.0]
    text = "\n".join(detach.summary_lines(o))
    for said in ("run 999999991, label t1: ended", "best seed 7: 120.3 -> 110.2 mm", "pin remap: 118.0 -> 104.5 mm",
                 "closure 100.0% clean", "taken by route closure: seed 7", "accept it with: placemat lock B_layout.py --accept-seed 7",
                 "run abc123: ok", "DRC clean, unconnected 2 | airwires 41.5 mm, 3 crossings", "record %s" % (run_dir / "run.json"),
                 "run dir %s" % run_dir):
        assert said in text, text


def test_a_stopped_run_is_an_error_with_its_partial_explore(tmp_path):
    pid = 999999992
    stopped = {"ev": "error", "kind": "stopped", "signal": "SIGTERM", "stage": "explore", "run_id": "abc123",
               "explore": {"tried": 5, "baseline": 50.0, "best": 45.0, "best_seed": 3, "stopped": "SIGTERM", "accepted": False}}
    board, script, run_dir = _board(tmp_path, pid, status="stopped", events=[stopped],
                                    failure={"kind": "stopped", "signal": "SIGTERM", "stage": "explore", "explore": stopped["explore"]})
    seen = {"channel": None, "detached": {"pid": pid, "command": "run", "script": str(script), "label": "", "log": "L"}}
    o = detach.outcome(tmp_path, pid, seen)
    assert o["ended"] == "error" and o["error"]["kind"] == "stopped" and o["record"] == str(run_dir / "run.json")
    assert o["explore"]["best_seed"] == 3 and o["explore"]["stopped"] == "SIGTERM"
    text = "\n".join(detach.summary_lines(o))
    assert "stopped by SIGTERM during explore" in text and "best seed 3: 50.0 -> 45.0 mm" in text and "log L" in text


def test_a_run_that_failed_before_it_reported_is_read_from_its_record(tmp_path):
    pid = 999999993
    board, script, run_dir = _board(tmp_path, pid, status="failed", failure={"kind": "generation", "message": "pcb failed"})
    (run_dir / "progress.jsonl").unlink()
    staged = run_dir.parent / (".20260101-000000-%d" % pid)
    run_dir.rename(staged)
    doc = json.loads((staged / "run.json").read_text())
    doc["pid"] = None
    (staged / "run.json").write_text(json.dumps(doc))
    seen = {"channel": None, "detached": {"pid": pid, "command": "run", "script": str(script), "label": "", "log": "L"}}
    o = detach.outcome(tmp_path, pid, seen)
    assert o["ended"] == "error" and o["error"]["kind"] == "run_failure" and o["record"] == str(staged / "run.json")
    assert "Schematic generation failed: pcb failed" in "\n".join(detach.summary_lines(o))


def test_nothing_of_the_pid_is_not_found_and_exits_2(tmp_path):
    out = io.StringIO()
    assert detach.summary(tmp_path, "999999994", out=out, poll=0.01) == 2
    assert "not found" in out.getvalue()
    out = io.StringIO()
    assert detach.summary(tmp_path, "nolabel", out=out, poll=0.01) == 2


def test_the_summary_waits_for_the_command_to_end(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])
    try:
        t0 = time.time()
        out = io.StringIO()
        code = []
        import threading
        t = threading.Thread(target=lambda: code.append(detach.summary(tmp_path, str(proc.pid), out=out, poll=0.1)))
        t.start()
        time.sleep(0.5)
        assert out.getvalue() == ""                     # nothing while it runs
        proc.wait()                                     # reaped: a zombie of this test would read as alive
        t.join(10)
        assert time.time() - t0 >= 1.0 and code == [2]
    finally:
        proc.kill()


def test_detach_returns_at_once_and_the_summary_reads_the_real_run(tmp_path):
    pytest.importorskip("pcbnew")
    from tests.test_stop_run import _searched_module
    mod, script, src = _searched_module(tmp_path)
    t0 = time.time()
    started = _placemat("run", script, "--no-render", "--keep-going", "--explore", "3", "--jobs", "2", "--label", "bg", "--detach", "--json",
                        cwd=mod, timeout=60)
    assert started.returncode == 0, started.stdout + started.stderr
    assert time.time() - t0 < 30
    entry = json.loads(started.stdout)
    pid = entry["pid"]
    assert entry["label"] == "bg" and entry["command"] == "run" and "--detach" not in entry["args"]
    assert Path(entry["log"]).parent == mod / ".placemat" / "detached" and channel.pid_alive(pid)
    done = _placemat("watch", pid, "--summary", cwd=mod, timeout=600)
    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert out.startswith("run %d, label bg: ended" % pid), out
    assert "explore: " in out and "variants" in out and "run " in out and ": ok" in out and "DRC " in out
    assert "record %s" % (mod / ".placemat" / "runs") in out and "log %s" % entry["log"] in out
    assert json.loads(Path(entry["log"]).read_text())["run_id"]     # the run's own output (its --json record) went to the log
    again = _placemat("watch", "bg", "--summary", "--json", cwd=mod, timeout=60)
    o = json.loads(again.stdout)
    assert again.returncode == 0 and o["pid"] == pid and o["run"]["status"] == "ok" and o["explore"]["tried"] >= 1


def test_a_detached_run_stops_on_sigterm_and_keeps_its_work(tmp_path):
    pytest.importorskip("pcbnew")
    from tests.test_stop_run import _searched_module
    mod, script, src = _searched_module(tmp_path)
    started = _placemat("run", script, "--no-render", "--keep-going", "--explore", "600", "--jobs", "2", "--detach", "--json",
                        cwd=mod, timeout=60)
    pid = json.loads(started.stdout)["pid"]
    ck = mod / ".placemat" / "explore" / "UsbC_layout" / "checkpoint.jsonl"
    from placemat import checkpoint
    t0 = time.time()
    while time.time() - t0 < 180 and sum(1 for d in checkpoint.read_lines(ck) if "v" in d) < 2:
        time.sleep(0.5)
    os.kill(pid, signal.SIGTERM)
    done = _placemat("watch", pid, "--summary", "--json", cwd=mod, timeout=120)
    o = json.loads(done.stdout)
    assert done.returncode == 1 and o["ended"] == "error" and o["error"]["kind"] == "stopped", done.stdout + done.stderr
    assert o["run"]["status"] == "stopped" and o["explore"]["tried"] >= 2
    assert sum(1 for d in checkpoint.read_lines(ck) if "v" in d) >= 2       # the variants found are kept for a resume
