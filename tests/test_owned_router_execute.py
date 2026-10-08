"""Exact shared owned executor extension; tiny real processes, no boards."""
from pathlib import Path
import os
import subprocess
import sys
import time
import pytest
from placemat.kicad import final_owned_worker as original

execute = original._execute


def test_actual_router_cwd_and_progress_fd_are_preserved(tmp_path):
    (tmp_path/'context.txt').write_text('router cwd')
    read, write = os.pipe()
    try:
        os.write(write, b'fd')
        rc, stdout, stderr = execute([sys.executable, '-c',
            'import os; print(open("context.txt").read()); print(os.read(%d,2).decode())' % read],
            time.time()+10, dict(os.environ), cwd=str(tmp_path), pass_fds=(read,))
        assert (rc, stdout, stderr) == (0, 'router cwd\nfd\n', '')
    finally:
        os.close(read)
        os.close(write)


def test_timeout_terminates_owned_child_group_and_preserves_unrelated_process(tmp_path):
    pid_file = tmp_path/'child.pid'
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    code = ('import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c",'
            '"import time; time.sleep(60)"]); open("child.pid","w").write(str(p.pid)); time.sleep(60)')
    try:
        with pytest.raises(BaseException) as interrupted:
            execute([sys.executable, '-c', code], time.time()+.4,
                    dict(os.environ), cwd=str(tmp_path))
        assert isinstance(interrupted.value, (subprocess.TimeoutExpired, original.ProofUnavailable))
        pid = int(pid_file.read_text())
        until = time.monotonic()+2
        while time.monotonic()<until:
            path = Path('/proc')/str(pid)/'stat'
            if not path.exists() or path.read_text().rpartition(')')[2].split()[0] == 'Z':
                break
            time.sleep(.01)
        else:
            pytest.fail('owned descendant still executing')
        assert sentinel.poll() is None
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)


def test_cancellation_in_spawn_window_cleans_group_and_restores_handlers(tmp_path, monkeypatch):
    import signal
    from placemat import stop
    before = {signum: signal.getsignal(signum) for signum in stop.SIGNALS}
    real_popen, spawned = subprocess.Popen, []
    def spawn(*args, **kwargs):
        assert kwargs['cwd'] == str(tmp_path)
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        os.kill(os.getpid(), signal.SIGTERM)
        return proc
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    with pytest.raises(stop.Stopped):
        execute([sys.executable, '-c', 'import time; time.sleep(60)'],
                time.time()+10, dict(os.environ), cwd=str(tmp_path))
    assert len(spawned) == 1 and spawned[0].poll() is not None
    assert {signum: signal.getsignal(signum) for signum in stop.SIGNALS} == before
