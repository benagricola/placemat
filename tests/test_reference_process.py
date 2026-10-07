"""Reference subprocesses own their groups and adopt only fresh successful records."""
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

from fixtures.reference import place_ref, route_ref


def script(tmp_path):
    path = tmp_path / "Board_layout.py"
    path.write_text("# unused test input\n")
    return path


def record(path, name="new", value=None):
    result = path.parent / ".placemat/runs" / name / "run.json"
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(json.dumps(value or {"status": "ok", "metrics": {}}))
    return result


def completed(cmd, rc=0):
    return subprocess.CompletedProcess(cmd, rc, "complete stdout", "complete stderr")


def test_an_unchanged_prior_record_is_not_this_run(tmp_path, monkeypatch):
    path = script(tmp_path)
    record(path, "old")
    monkeypatch.setattr(route_ref, "run_owned", lambda cmd, **kw: completed(cmd))
    got, _ = place_ref.placemat_run(path)
    assert got is None
    assert place_ref._failure(got)[0] == place_ref.NO_RECORD


def test_a_new_record_wins_over_a_future_dated_old_record(tmp_path, monkeypatch):
    path = script(tmp_path)
    old = record(path, "old")
    future = time.time() + 1000
    os.utime(old, (future, future))
    def run(cmd, **kw):
        record(path, value={"status": "ok", "metrics": {"new": True}})
        return completed(cmd)
    monkeypatch.setattr(route_ref, "run_owned", run)
    got, _ = place_ref.placemat_run(path)
    assert got["metrics"] == {"new": True}
    (audit,) = (path.parent / ".placemat/reference-runs").iterdir()
    assert (audit / "stdout.log").read_text() == "complete stdout"
    facts = json.loads((audit / "process.json").read_text())
    assert facts["returncode"] == 0 and facts["record"].endswith("new/run.json")
    assert facts["cwd"] == str(pathlib.Path.cwd())
    assert float(facts["router_deadline_utc"]) > time.time()


def test_rewriting_an_existing_record_is_fresh(tmp_path, monkeypatch):
    path = script(tmp_path)
    record(path)
    def run(cmd, **kw):
        record(path, value={"status": "ok", "metrics": {"rewritten": True}})
        return completed(cmd)
    monkeypatch.setattr(route_ref, "run_owned", run)
    got, _ = place_ref.placemat_run(path)
    assert got["metrics"]["rewritten"]


@pytest.mark.parametrize("fresh", [False, True])
def test_nonzero_exit_never_adopts_a_completed_record(tmp_path, monkeypatch, fresh):
    path = script(tmp_path)
    record(path, "old")
    def run(cmd, **kw):
        if fresh:
            record(path)
        return completed(cmd, 7)
    monkeypatch.setattr(route_ref, "run_owned", run)
    got, _ = place_ref.placemat_run(path)
    assert place_ref._failure(got) == ("exit 7", "complete stderr")


def test_nonzero_exit_preserves_a_fresh_failure_kind(tmp_path, monkeypatch):
    path = script(tmp_path)
    def run(cmd, **kw):
        record(path, value={"status": "failed", "failure": {"kind": "intent refused", "message": "why"}})
        return completed(cmd, 1)
    monkeypatch.setattr(route_ref, "run_owned", run)
    got, _ = place_ref.placemat_run(path)
    assert place_ref._failure(got) == ("intent refused", "why") and got["returncode"] == 1


@pytest.mark.parametrize("text", ["{", "[]", '{"metrics": {}}', '{"status":"ok","metrics":[]}',
                                  '{"status":"failed","failure":"bad"}'])
def test_malformed_fresh_records_are_clear_failures(tmp_path, monkeypatch, text):
    path = script(tmp_path)
    def run(cmd, **kw):
        record(path).write_text(text)
        return completed(cmd)
    monkeypatch.setattr(route_ref, "run_owned", run)
    got, _ = place_ref.placemat_run(path)
    assert place_ref._failure(got)[0] == "malformed run record"


def test_timeout_logs_partial_bytes_and_returns_no_success(tmp_path, monkeypatch):
    path = script(tmp_path)
    record(path, "old")
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 2, output=b"partial stdout", stderr=b"partial stderr")
    monkeypatch.setattr(route_ref, "run_owned", run)
    got, _ = place_ref.placemat_run(path)
    assert place_ref._failure(got)[0] == place_ref.TIMEOUT
    (audit,) = (path.parent / ".placemat/reference-runs").iterdir()
    assert (audit / "stdout.log").read_text() == "partial stdout"
    assert (audit / "stderr.log").read_text() == "partial stderr"


def test_expired_placement_deadline_refuses_before_spawn(tmp_path, monkeypatch):
    path = script(tmp_path)
    monkeypatch.setenv("KRT_ROUTE_DEADLINE_UTC", str(time.time() - 1))
    monkeypatch.setattr(route_ref.subprocess, "Popen", lambda *a, **k: pytest.fail("expired invocation spawned"))
    got, _ = place_ref.placemat_run(path)
    assert place_ref._failure(got)[0] == "RuntimeError" and "expired" in place_ref._failure(got)[1]


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("during_spawn", [False, True])
def test_signals_reap_only_owned_child_and_restore_handlers(tmp_path, signum, during_spawn):
    pidfile = tmp_path / "child.pid"
    restored = tmp_path / "restored"
    worker_code = f'''import os,signal,sys
from pathlib import Path
from fixtures.reference import route_ref
previous={{s:signal.getsignal(s) for s in (signal.SIGTERM,signal.SIGINT)}}
real=route_ref.subprocess.Popen
def spawn(cmd,**kw):
 p=real(cmd,**kw)
 Path({str(pidfile)!r}).write_text(str(p.pid))
 if {during_spawn!r}:os.kill(os.getpid(),{int(signum)})
 return p
route_ref.subprocess.Popen=spawn
try:route_ref.run_owned([sys.executable,'-c','import time; time.sleep(100)'],timeout=10)
except SystemExit:
 assert all(signal.getsignal(s)==h for s,h in previous.items())
 Path({str(restored)!r}).write_text('restored')
 raise
'''
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(100)"], start_new_session=True)
    worker = subprocess.Popen([sys.executable, "-c", worker_code], start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    child = None
    try:
        deadline = time.monotonic() + 5
        while not pidfile.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pidfile.exists()
        child = int(pidfile.read_text())
        if not during_spawn:
            os.kill(worker.pid, signum)
        assert worker.wait(timeout=5) == 128 + signum, worker.stderr.read()
        assert restored.read_text() == "restored"
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
        assert sentinel.poll() is None
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait()
        if child is not None:
            try:
                os.killpg(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        sentinel.terminate()
        sentinel.wait(timeout=5)


def test_supervisor_refuses_a_thread_without_launching(monkeypatch):
    import concurrent.futures
    monkeypatch.setattr(route_ref.subprocess, "Popen", lambda *a, **k: pytest.fail("thread spawned"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(route_ref.run_owned, ["unused"], timeout=1)
        with pytest.raises(RuntimeError, match="main thread"):
            future.result()


def test_expiration_is_recomputed_after_spawn(monkeypatch):
    real = subprocess.Popen
    seen = []
    def spawn(cmd, **kwargs):
        proc = real([sys.executable, "-c", "import time; time.sleep(100)"], **kwargs)
        seen.append(proc.pid)
        time.sleep(0.15)
        return proc
    monkeypatch.setattr(route_ref.subprocess, "Popen", spawn)
    with pytest.raises(subprocess.TimeoutExpired):
        route_ref.run_owned(["unused"], timeout=0.1)
    with pytest.raises(ProcessLookupError):
        os.kill(seen[0], 0)


def test_stubborn_term_child_retains_output_from_shutdown_grace(tmp_path, monkeypatch):
    path = script(tmp_path)
    real = subprocess.Popen
    seen = []
    child = """import signal,sys,time
signal.signal(signal.SIGTERM,lambda *a:(print('during TERM grace',flush=True),print('grace stderr',file=sys.stderr,flush=True)))
print('before timeout',flush=True)
print('before stderr',file=sys.stderr,flush=True)
time.sleep(100)
"""
    def spawn(cmd, **kwargs):
        proc = real([sys.executable, "-c", child], **kwargs)
        seen.append(proc.pid)
        return proc
    monkeypatch.setattr(route_ref.subprocess, "Popen", spawn)
    monkeypatch.setattr(place_ref, "RUN_TIMEOUT_S", 0.1)
    got, _ = place_ref.placemat_run(path)
    assert place_ref._failure(got)[0] == place_ref.TIMEOUT
    (audit,) = (path.parent / ".placemat/reference-runs").iterdir()
    assert (audit / "stdout.log").read_text() == "before timeout\nduring TERM grace\n"
    assert (audit / "stderr.log").read_text() == "before stderr\ngrace stderr\n"
    with pytest.raises(ProcessLookupError):
        os.kill(seen[0], 0)
