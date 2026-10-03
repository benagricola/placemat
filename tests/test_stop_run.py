"""A run that is stopped: its record says so, the layout folder is as it was,
a final line names the stage and the cause on both streams, and the exit
status is 128 + the signal. On a real module (tests/real_modules.py), and as
a real process given a real SIGTERM."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pcbnew")

from placemat import stop
from tests import real_modules as rm

ROOT = Path(__file__).resolve().parent.parent


def _stage_and_patch(tmp_path, monkeypatch):
    from placemat import runner
    script = rm.stage(tmp_path, "usb5v")
    src = runner.find_board(script)

    def restore(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(runner.cached_generation(src), src.layout_dir)
        return False
    monkeypatch.setattr(runner, "generate", restore)
    return script, src, runner


def _only_run(src):
    runs = [p for p in (src.board_dir / ".placemat" / "runs").iterdir() if (p / "run.json").exists() and not p.is_symlink()]
    assert len(runs) == 1, runs
    return json.loads((runs[0] / "run.json").read_text()), runs[0]


def test_a_run_stopped_while_resolving_is_recorded_and_the_folder_restored(tmp_path, monkeypatch, capsys):
    script, src, runner = _stage_and_patch(tmp_path, monkeypatch)
    from placemat import explore as explore_mod
    from placemat.board_geometry import BoardGeometry  # noqa: F401  (keeps the import cost out of the timing)
    marker = src.layout_dir / "hand_made.txt"
    runner.generate(src, tmp_path, False, True)
    marker.write_text("the last run's folder")
    real = explore_mod.before_resolve

    def stopping(*a, **k):
        raise stop.Stopped(signal.SIGTERM)
    monkeypatch.setattr(explore_mod, "before_resolve", stopping)
    t0 = time.time()
    with pytest.raises(stop.Stopped) as e:
        runner.run(script, render=False, quiet=False, reuse=False)
    assert time.time() - t0 < 30 and e.value.exit_code == 143
    doc, run_dir = _only_run(src)
    assert doc["status"] == "stopped" and doc["pid"] == os.getpid()
    assert doc["failure"]["kind"] == "stopped" and doc["failure"]["signal"] == "SIGTERM"
    assert doc["failure"]["stage"] == "resolve" and doc["failure"]["elapsed_s"] >= 0
    assert marker.read_text() == "the last run's folder"            # restored from before/, not left half written
    out = capsys.readouterr()
    for stream in (out.out, out.err):
        assert "stopped by SIGTERM during resolve" in stream, stream
    monkeypatch.setattr(explore_mod, "before_resolve", real)


def test_the_record_is_running_with_the_pid_as_soon_as_the_id_is_taken(tmp_path, monkeypatch):
    script, src, runner = _stage_and_patch(tmp_path, monkeypatch)
    seen = {}
    from placemat import explore as explore_mod

    def peek(*a, **k):
        seen.update(_only_run(src)[0])
        raise stop.Stopped(signal.SIGHUP)
    monkeypatch.setattr(explore_mod, "before_resolve", peek)
    with pytest.raises(stop.Stopped):
        runner.run(script, render=False, quiet=True, reuse=False)
    assert seen["status"] == "running" and seen["pid"] == os.getpid() and seen["run_id"]


def test_a_stop_is_loud_even_when_quiet(tmp_path, monkeypatch, capsys):
    script, src, runner = _stage_and_patch(tmp_path, monkeypatch)
    from placemat import explore as explore_mod
    monkeypatch.setattr(explore_mod, "before_resolve", lambda *a, **k: (_ for _ in ()).throw(stop.Stopped(signal.SIGINT)))
    with pytest.raises(stop.Stopped):
        runner.run(script, render=False, quiet=True, reuse=False)
    assert "stopped by SIGINT during resolve" in capsys.readouterr().err


def _children(pid):
    try:
        return [int(c) for c in Path("/proc/%d/task/%d/children" % (pid, pid)).read_text().split()]
    except OSError:
        return []


def _searched_module(tmp_path):
    from tests.test_explore_cli import _module
    mod, script = _module(tmp_path, searched=True)
    from placemat import runner
    src = runner.find_board(script)
    from placemat.project import generator_inputs
    runner._inputs_record(src).write_text(json.dumps(generator_inputs(src), indent=1, sort_keys=True))
    return mod, script, src


def test_a_real_sigterm_to_a_real_explore_run(tmp_path):
    mod, script, src = _searched_module(tmp_path)
    layout_before = {p.name: p.read_bytes() for p in src.layout_dir.iterdir() if p.is_file()}
    proc = subprocess.Popen([sys.executable, "-m", "placemat", "run", str(script), "--no-render", "--keep-going", "--explore", "600",
                             "--jobs", "2"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        t0 = time.time()
        while len(_children(proc.pid)) < 3 and time.time() - t0 < 120 and proc.poll() is None:
            time.sleep(0.2)
        assert proc.poll() is None, proc.communicate()
        workers = _children(proc.pid)
        time.sleep(4)
        t1 = time.time()
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=60)
        took = time.time() - t1
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 143, (out, err)
    assert took < 10
    assert "explore stopped by SIGTERM after" in out and "nothing accepted" in out
    assert "stopped by SIGTERM during explore" in out and "stopped by SIGTERM during explore" in err
    doc, _ = _only_run(src)
    assert doc["status"] == "stopped" and doc["failure"]["stage"] == "explore"
    ex = doc["failure"]["explore"]
    assert ex["stopped"] == "SIGTERM" and ex["tried"] >= 1 and ex["focus"]
    assert not (mod / "UsbC_layout.lock.json").exists()
    assert {p.name: p.read_bytes() for p in src.layout_dir.iterdir() if p.is_file()} == layout_before
    for w in workers:
        assert not Path("/proc/%d" % w).exists() or "Z" in Path("/proc/%d/stat" % w).read_text().rsplit(")", 1)[1][:3]
    # the command the message offers writes the lock from what was saved
    import re
    m = re.search(r"accept it with: placemat lock (\S+) --accept-seed (\d+)", out)
    if m:
        done = subprocess.run([sys.executable, "-m", "placemat", "lock", m.group(1), "--accept-seed", m.group(2)],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert done.returncode == 0 and "wrote seed %s" % m.group(2) in done.stdout, done.stdout + done.stderr
        assert json.loads((mod / "UsbC_layout.lock.json").read_text())["entries"]
        again = subprocess.run([sys.executable, "-m", "placemat", "lock", m.group(1), "--accept-seed", "999999"],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert again.returncode == 1 and "not 999999" in again.stdout


def _run_explore(script, seconds, *flags):
    return subprocess.Popen([sys.executable, "-m", "placemat", "run", str(script), "--no-render", "--keep-going",
                             "--explore", str(seconds), "--jobs", "2", *flags], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _stop_after(proc, seconds):
    t0 = time.time()
    while len(_children(proc.pid)) < 3 and time.time() - t0 < 120 and proc.poll() is None:
        time.sleep(0.2)
    time.sleep(seconds)
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=60)
    return proc.returncode, out, err


def test_a_real_explore_stopped_twice_resumes_each_time_without_repeating_a_seed(tmp_path):
    mod, script, src = _searched_module(tmp_path)
    ck = mod / ".placemat" / "explore" / "UsbC_layout" / "checkpoint.jsonl"
    from placemat import checkpoint
    rc, out, err = _stop_after(_run_explore(script, 40), 5)
    assert rc == 143
    first = checkpoint.read_lines(ck)
    s1 = [d["v"] for d in first if "v" in d]
    assert first[0]["kind"] == "header" and first[-1]["stop"] == "SIGTERM" and len(s1) >= 3
    rc, out, err = _stop_after(_run_explore(script, 40), 5)
    assert rc == 143 and "resuming a saved explore: %d variants" % (len(s1) + 1) in out, out
    second = checkpoint.read_lines(ck)
    s2 = [d["v"] for d in second if "v" in d]
    assert len(s2) == len(set(s2)) and set(s1) < set(s2)                      # no seed twice; what was done is kept
    assert second[0] == first[0]                                              # the same header: the baseline is reused
    assert sum(1 for d in second if "stop" in d) == 2 and max(d["t"] for d in second if "t" in d) > first[-1]["t"]
    # finish it: the rest of a short budget (the time already spent counts against it)
    spent = max(d["t"] for d in second if "t" in d)
    proc = _run_explore(script, int(spent) + 4)
    out, err = proc.communicate(timeout=300)
    assert proc.returncode == 0, out + err
    assert "resuming a saved explore: %d variants" % (len(s2) + 1) in out
    assert not ck.exists()                                                    # recorded in the run: not needed
    doc, _ = _only_run(src)
    assert doc["status"] == "ok" and doc["metrics"]["explore"]["tried"] > len(s2) + 1


def test_resume_refuses_a_saved_explore_of_another_script(tmp_path):
    mod, script, src = _searched_module(tmp_path)
    rc, out, err = _stop_after(_run_explore(script, 40), 3)
    assert rc == 143
    script.write_text(script.read_text() + "\n# edited\n")
    proc = _run_explore(script, 10, "--resume")
    out, err = proc.communicate(timeout=120)
    assert proc.returncode == 1 and "the script changed since it began" in out, out
