"""Stopping a long command: the signals raise Stopped, a second ends the
process, an explore that is stopped ends its workers and says what it has,
and a worker that dies is reported, not waited for."""
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


def test_a_record_still_running_whose_process_is_gone_is_reported_dead():
    from placemat.report import RunRecord, dead_note
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    assert "pid %d) is gone" % done.pid in dead_note(RunRecord("abc123", "b", "running", pid=done.pid))
    assert dead_note(RunRecord("abc123", "b", "running", pid=os.getpid())) == ""
    assert dead_note(RunRecord("abc123", "b", "stopped", pid=done.pid)) == ""
    assert dead_note(RunRecord("abc123", "b", "running")) == ""
