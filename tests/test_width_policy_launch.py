"""Actual stop during Popen cannot lose custody of its new process group."""
import os
import signal
import subprocess
import sys

import pytest

from placemat import stop
from placemat.kicad import width_policy
from placemat.route_phase import parse_phases
from placemat.settings import Settings
from tests.test_effective_width_policy import selected


@pytest.mark.parametrize('stopped_signal', stop.SIGNALS)
def test_stopped_after_spawn_before_assignment_reaps_and_restores_handlers(tmp_path, monkeypatch, stopped_signal):
    script = tmp_path / 'py_router/nominal_width_policy.py'
    script.parent.mkdir()
    script.write_text('import time; time.sleep(60)')
    real_popen = subprocess.Popen
    launched = []
    def interrupted_launch(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        launched.append(child)
        os.kill(os.getpid(), stopped_signal)
        return child
    outer_handlers = {sig: signal.getsignal(sig) for sig in stop.SIGNALS}
    previous = stop.install()
    installed_handlers = {sig: signal.getsignal(sig) for sig in stop.SIGNALS}
    try:
        monkeypatch.setattr(width_policy.subprocess, 'Popen', interrupted_launch)
        (phase,) = parse_phases([{'name': 'signals'}])
        with pytest.raises(stop.Stopped) as stopped:
            width_policy.resolve(sys.executable, tmp_path, tmp_path / 'board.kicad_pcb',
                                 [phase], [selected()], Settings(), timeout=2)
        assert stopped.value.signum == stopped_signal
        assert len(launched) == 1 and launched[0].returncode is not None
        assert {sig: signal.getsignal(sig) for sig in stop.SIGNALS} == installed_handlers
    finally:
        for child in launched:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        stop.restore(previous)
    assert {sig: signal.getsignal(sig) for sig in stop.SIGNALS} == outer_handlers


def test_failed_launch_restores_original_handlers_and_stays_structured(tmp_path, monkeypatch):
    script = tmp_path / 'py_router/nominal_width_policy.py'
    script.parent.mkdir()
    script.write_text('unused')
    handlers = {sig: signal.getsignal(sig) for sig in stop.SIGNALS}
    def missing(*args, **kwargs):
        raise FileNotFoundError('configured interpreter unavailable')
    monkeypatch.setattr(width_policy.subprocess, 'Popen', missing)
    (phase,) = parse_phases([{'name': 'signals'}])
    result = width_policy.resolve(sys.executable, tmp_path, tmp_path / 'board.kicad_pcb',
                                  [phase], [selected()], Settings(), timeout=2)
    assert result['failure']['code'] == 'unavailable'
    assert {sig: signal.getsignal(sig) for sig in stop.SIGNALS} == handlers
