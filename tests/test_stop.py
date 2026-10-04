"""Stopping a long command: the signals raise Stopped, a second ends the
process, an explore that is stopped ends its workers and says what it has,
and a worker that dies is reported, not waited for."""
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from placemat import checkpoint, explore, lock, stop
from placemat.explore import Explore, explore as run_explore
from tests import explore_boards as eb

ROOT = Path(__file__).resolve().parent.parent


def test_stopped_is_a_base_exception_with_the_signal_and_the_exit_code():
    s = stop.Stopped(signal.SIGTERM)
    assert isinstance(s, BaseException) and not isinstance(s, Exception)
    assert s.name == "SIGTERM" and s.exit_code == 143 and stop.Stopped(signal.SIGHUP).exit_code == 129


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_each_stopping_signal_raises_stopped(sig):
    previous = stop.install()
    try:
        with pytest.raises(stop.Stopped) as e:
            os.kill(os.getpid(), sig)
            time.sleep(5)
        assert e.value.signum == sig
    finally:
        stop.restore(previous)


def test_a_second_signal_ends_the_process_at_once():
    code = textwrap.dedent("""
        import os, signal, sys, time
        from placemat import stop
        stop.install()
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)
        except stop.Stopped:
            print("first", flush=True)
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)
            print("not reached", flush=True)
    """)
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30, cwd=ROOT)
    assert done.returncode == 143 and done.stdout.strip() == "first"


def test_a_worker_killed_from_outside_is_reported_and_the_explore_does_not_hang():
    t0 = time.time()
    r = run_explore(eb.Killer(), eb.FOCUS, seconds=60, jobs=2)
    assert time.time() - t0 < 40
    assert r.tried == 1 and len(r.failures) == 2
    assert all("killed by signal 9" in f for f in r.failures), r.failures


def test_a_worker_that_raises_sends_the_traceback():
    r = run_explore(eb.Raiser(), eb.FOCUS, seconds=60, jobs=1)
    assert r.tried == 1 and len(r.failures) == 1
    assert "ValueError: boom in a variant" in r.failures[0] and "Traceback" in r.failures[0]


DRIVER = textwrap.dedent("""
    import sys
    from pathlib import Path
    from placemat import stop
    from placemat.explore import search
    from tests import explore_boards as eb
    work = Path(sys.argv[1])
    stop.install()
    try:
        search(eb.Recording(work / "pids", delay=0.05), work / "Board_layout.py", seconds=600, jobs=2,
               accept=len(sys.argv) > 2, checkpoint_dir=work / "ckpt")
    except stop.Stopped as s:
        print("stopped", s.name, flush=True)
        sys.exit(s.exit_code)
""")


def _wait_for(pred, seconds=60):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if pred():
            return True
        time.sleep(0.1)
    return False


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie is not running
    try:
        return Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _start(tmp_path, *extra):
    return subprocess.Popen([sys.executable, "-c", DRIVER, str(tmp_path), *extra], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_a_stopped_search_ends_its_workers_says_what_it_had_and_does_not_accept(tmp_path):
    proc = _start(tmp_path, "accept")
    try:
        assert _wait_for(lambda: (tmp_path / "pids").exists() and len((tmp_path / "pids").read_text().split()) >= 2)
        time.sleep(2)                       # some variants finish
        pids = [int(p) for p in (tmp_path / "pids").read_text().split()]
        t0 = time.time()
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
        took = time.time() - t0
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 143 and "stopped SIGTERM" in out, (out, err)
    assert took < 20
    assert "explore stopped by SIGTERM after" in out and "nothing accepted; accept it with: placemat lock" in out
    assert not (tmp_path / "Board_layout.lock.json").exists()          # --accept given, the decision is still pending
    best = checkpoint.read_best(tmp_path / "ckpt")
    assert best is not None and ("best seed %d:" % best["seed"]) in out
    # the command it names writes the lock from what was saved, without a search
    script = tmp_path / "Board_layout.py"
    msg = explore.accept_best(script, tmp_path / "ckpt", seed=best["seed"])
    assert lock.path_for(script).exists() and {e.key for e in lock.read(lock.path_for(script))} == set(eb.KEYS), msg
    held = eb.make().resolve(lock=lock.read(lock.path_for(script)))
    variant = eb.make().resolve(explore=Explore(best["seed"], eb.FOCUS))
    assert {k: held.placement(k) for k in eb.KEYS} == {k: variant.placement(k) for k in eb.KEYS}
    assert _wait_for(lambda: not any(_alive(p) for p in pids), 10), "workers outlived the parent"


def test_workers_do_not_outlive_a_parent_that_is_killed(tmp_path):
    proc = _start(tmp_path)
    try:
        assert _wait_for(lambda: (tmp_path / "pids").exists() and len((tmp_path / "pids").read_text().split()) >= 2)
        pids = [int(p) for p in (tmp_path / "pids").read_text().split()]
        os.kill(proc.pid, signal.SIGKILL)
        proc.communicate(timeout=30)
        assert _wait_for(lambda: not any(_alive(p) for p in pids), 15), "workers outlived a killed parent"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_a_stop_record_is_rendered_to_a_line_at_the_edge_and_watch_describes_it_from_the_record():
    from placemat import channel
    rec = stop.record(stop.Stopped(signal.SIGTERM), command="run", stage="explore", run_id="abc", elapsed_s=7.2, record="/r/run.json")
    assert rec["signal"] == "SIGTERM" and "message" not in rec
    line = stop.line(rec)
    assert line.startswith("run abc stopped by SIGTERM during explore after 7 s") and line.endswith("/r/run.json")
    assert channel.describe({"ev": "error", **rec}) == line
    assert stop.line(stop.record(stop.Stopped(signal.SIGHUP), command="route")) == "route stopped by SIGHUP"


def test_a_record_still_running_whose_process_is_gone_is_reported_dead():
    from placemat.report import RunRecord, dead_note
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    assert "pid %d) is gone" % done.pid in dead_note(RunRecord("abc123", "b", "running", pid=done.pid))
    assert dead_note(RunRecord("abc123", "b", "running", pid=os.getpid())) == ""
    assert dead_note(RunRecord("abc123", "b", "stopped", pid=done.pid)) == ""
    assert dead_note(RunRecord("abc123", "b", "running")) == ""


CAP_DRIVER = textwrap.dedent("""
    import json, sys
    from pathlib import Path
    from placemat import stop, timecap
    from placemat.explore import search
    from placemat.settings import Settings
    from tests import explore_boards as eb
    work = Path(sys.argv[1])
    stop.install()
    timecap.configure(max_time=float(sys.argv[2]))
    timecap.arm(Settings())
    try:
        search(eb.Recording(work / "pids", delay=0.05), work / "Board_layout.py", seconds=600, jobs=2, checkpoint_dir=work / "ckpt")
    except stop.Stopped as s:
        print("RECORD " + json.dumps(stop.record(s, command="run", stage="explore", explore=s.explore)), flush=True)
        sys.exit(s.exit_code)
""")


def test_a_capped_explore_keeps_its_variants_and_its_checkpoint_and_ends_its_workers(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", CAP_DRIVER, str(tmp_path), "8"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 143, (out, err)
    rec = json.loads(next(l for l in out.splitlines() if l.startswith("RECORD "))[len("RECORD "):])
    assert rec["cause"] == "max_time" and rec["limit_s"] == 8.0 and rec["stage"] == "explore"
    assert rec["explore"]["tried"] >= 1 and rec["explore"]["stopped"] == "the time cap (--max-time 8 s)"
    assert "explore stopped by the time cap (--max-time 8 s) after" in out + err
    lines = [json.loads(l) for l in (tmp_path / "ckpt" / "checkpoint.jsonl").read_text().splitlines() if l.strip()]
    assert any("v" in l for l in lines) and lines[-1]["stop"] == "the time cap (--max-time 8 s)"       # the variants finished, and why it stopped
    pids = [int(p) for p in (tmp_path / "pids").read_text().split()]
    assert _wait_for(lambda: not any(_alive(p) for p in pids), 10), "workers outlived the parent"
    # and the saved explore is there to continue
    assert checkpoint.read_best(tmp_path / "ckpt") is not None or any(l.get("v") for l in lines)
