"""DRC and the renders alongside the checks (`run.parallel`): the record is the one a run in sequence writes, an error in
either is raised as in sequence, and a stop while they work leaves no kicad-cli behind. On a real module
(tests/real_modules.py), with a kicad-cli stand-in on PATH where a test needs one to fail or to hang."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pcbnew")

from placemat import stop
from tests import real_modules as rm
from tests.test_stop import _alive, _wait_for

ROOT = Path(__file__).resolve().parent.parent
REAL_CLI = "/usr/bin/kicad-cli"


@pytest.fixture(autouse=True)
def _console_loud():
    yield
    from placemat import console
    console.configure(quiet=False)


def _stand_in(tmp_path, monkeypatch, **behaviour):
    """A `kicad-cli` first on PATH. `behaviour` maps a subcommand (render, drc) to what it does instead of the real one:
    "fail" (says so and exits 3, writing nothing) or "hang" (writes its pid under `pids/` and sleeps). Anything else runs
    the real kicad-cli."""
    bin_dir, pids = tmp_path / "bin", tmp_path / "pids"
    bin_dir.mkdir()
    pids.mkdir()
    cases = []
    for sub, what in behaviour.items():
        if what == "fail":
            cases.append('  *" %s "*) echo "stand-in %s failed" >&2; exit 3;;' % (sub, sub))
        else:
            cases.append('  *" %s "*) echo %s > "%s/$$"; exec sleep 600;;' % (sub, sub, pids))
    cli = bin_dir / "kicad-cli"
    cli.write_text('#!/bin/sh\ncase " $* " in\n%s\nesac\nexec %s "$@"\n' % ("\n".join(cases), REAL_CLI))
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", "%s:%s" % (bin_dir, os.environ["PATH"]))
    return pids


_VOLATILE = {"timing_s", "pid", "paths", "native"}


def _comparable(doc: dict) -> dict:
    """run.json without what changes from one run of the same inputs to the next: times, the pid, the folder."""
    out = {k: v for k, v in doc.items() if k not in _VOLATILE}
    out["metrics"] = {k: v for k, v in doc["metrics"].items() if k != "resolve_seconds"}
    out["steps"] = [{k: v for k, v in s.items() if k not in ("seconds", "first_seconds")} for s in doc["steps"]]
    return out


def _record(result) -> dict:
    return json.loads((result.run_dir / "run.json").read_text())


def test_the_record_is_the_same_with_the_stages_alongside_or_in_sequence(tmp_path):
    on, _, pcb = rm.run(tmp_path / "on", "usb5v", overrides={"run_parallel": True}, render=True)
    off, _, _ = rm.run(tmp_path / "off", "usb5v", overrides={"run_parallel": False}, render=True)
    assert on.status == off.status == "ok"
    a, b = _record(on), _record(off)
    assert a["run_id"] == b["run_id"]                     # run.parallel is not part of the id
    assert {"drc", "checks", "render"} <= set(a["timing_s"]) and list(a["timing_s"]) == list(b["timing_s"])
    assert list(a["metrics"]) == list(b["metrics"])       # the same keys in the same order
    assert _comparable(a) == _comparable(b)
    for r in (on, off):
        assert (r.run_dir / "drc.json").exists() and "$ kicad-cli pcb render" in (r.run_dir / "render.log").read_text()
    assert (pcb.parent / "layout.png").exists()


def test_a_failed_render_is_in_its_log_with_the_stages_alongside(tmp_path, monkeypatch):
    _stand_in(tmp_path, monkeypatch, render="fail")
    result, _, _ = rm.run(tmp_path, "usb5v", overrides={"run_parallel": True}, render=True)
    assert result.status == "ok"                          # as in sequence: a render's failure is its log's, not the run's
    log = (result.run_dir / "render.log").read_text()
    assert log.count("stand-in render failed") >= 2, log  # every view was tried
    assert "render" in result.record.timing_s


def test_a_render_that_raises_is_raised_by_the_run_with_the_stages_alongside(tmp_path, monkeypatch):
    from placemat.kicad import write

    def broken(*a, **k):
        raise OSError("the render could not start")
    monkeypatch.setattr(write, "render_board", broken)
    with pytest.raises(OSError, match="the render could not start"):
        rm.run(tmp_path, "usb5v", overrides={"run_parallel": True}, render=True)


def test_a_failed_drc_is_raised_by_the_run_with_the_stages_alongside(tmp_path, monkeypatch):
    _stand_in(tmp_path, monkeypatch, drc="fail")
    with pytest.raises(RuntimeError, match="kicad-cli drc wrote no report.*stand-in drc failed"):
        rm.run(tmp_path, "usb5v", overrides={"run_parallel": True}, render=True)


def test_a_drc_that_fails_after_the_checks_still_stops_a_render_in_progress(tmp_path, monkeypatch):
    """The DRC's error comes up while the render works: the run raises it and the render's kicad-cli is killed."""
    pids = _stand_in(tmp_path, monkeypatch, drc="fail", render="hang")
    with pytest.raises(RuntimeError, match="wrote no report"):
        rm.run(tmp_path, "usb5v", overrides={"run_parallel": True}, render=True)
    hung = [int(p.name) for p in pids.iterdir()]
    assert hung, "the render had started"
    assert _wait_for(lambda: not any(_alive(p) for p in hung), 10), "a render outlived the run"


def _cached_module(tmp_path):
    """The UsbC fixture module with its generation cached and its inputs recorded, so a `placemat run` of it in a
    process of its own does not generate."""
    from tests.test_explore_cli import _module
    mod, script = _module(tmp_path)
    from placemat import runner
    from placemat.project import generator_inputs
    src = runner.find_board(script)
    runner._inputs_record(src).write_text(json.dumps(generator_inputs(src), indent=1, sort_keys=True))
    return mod, script, src


def test_a_real_sigterm_while_drc_and_render_work_leaves_no_kicad_cli(tmp_path, monkeypatch):
    pids = _stand_in(tmp_path, monkeypatch, drc="hang", render="hang")
    mod, script, src = _cached_module(tmp_path)
    layout_before = {p.name: p.read_bytes() for p in src.layout_dir.iterdir() if p.is_file()}
    proc = subprocess.Popen([sys.executable, "-m", "placemat", "run", str(script), "--no-reuse", "--keep-going"], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
    try:
        both = _wait_for(lambda: len(list(pids.iterdir())) >= 2 or proc.poll() is not None, 300)
        assert both and proc.poll() is None, proc.communicate()
        hung = {int(p.name): p.read_text().strip() for p in pids.iterdir()}
        assert sorted(hung.values()) == ["drc", "render"]       # both at once: they overlap
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 143, (out, err)
    assert _wait_for(lambda: not any(_alive(p) for p in hung), 10), "a kicad-cli outlived the run"
    runs = [p for p in (src.board_dir / ".placemat" / "runs").iterdir() if (p / "run.json").exists() and not p.is_symlink()]
    doc = json.loads((runs[0] / "run.json").read_text())
    assert doc["status"] == "stopped" and doc["failure"]["signal"] == "SIGTERM"
    assert doc["failure"]["stage"] in ("checks", "drc"), doc["failure"]
    assert "stopped by SIGTERM during" in err
    assert {p.name: p.read_bytes() for p in src.layout_dir.iterdir() if p.is_file()} == layout_before


def test_in_sequence_nothing_runs_alongside(tmp_path, monkeypatch):
    """run.parallel false: the render starts only after the checks have finished."""
    from placemat import checks
    from placemat.kicad import write
    order = []
    real_checks, real_render = checks.run_checks, write.render_board
    monkeypatch.setattr(checks, "run_checks", lambda *a, **k: (order.append("checks"), real_checks(*a, **k))[1])
    monkeypatch.setattr(write, "render_board", lambda *a, **k: (order.append("render"), real_render(*a, **k))[1])
    result, _, _ = rm.run(tmp_path, "usb5v", overrides={"run_parallel": False}, render=True)
    assert result.status == "ok" and order == ["checks", "render"]


def test_the_second_signal_kills_a_tracked_child():
    """`stop.track`: what the second signal's immediate exit kills first."""
    script = ("import os, signal, subprocess\n"
              "from placemat import stop\n"
              "c = subprocess.Popen(['sleep', '600'])\n"
              "print(c.pid, flush=True)\n"
              "stop.install(); stop.track(c)\n"
              "try:\n    os.kill(os.getpid(), signal.SIGTERM)\nexcept stop.Stopped:\n    pass\n"
              "os.kill(os.getpid(), signal.SIGTERM)\n")
    code = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), timeout=60)
    assert code.returncode == 143, code.stderr
    grandchild = int(code.stdout.split()[0])
    assert _wait_for(lambda: not _alive(grandchild), 10)
