"""Owned deadline cleanup and strict reply parsing need no native board reads."""
import os
import signal
import subprocess
import sys
import time

import pytest

from placemat import stop
from placemat.kicad import final_owned_worker as worker
from placemat.kicad.final_call import ProofUnavailable
from tests.test_effective_width_policy import _observed_pid_state
from tests.test_final_custody import context


def test_owned_worker_timeout_terminates_descendants_and_preserves_unrelated_process(tmp_path):
    pidfile = tmp_path / 'child.pid'
    script = tmp_path / 'native_block.py'
    script.write_text("import subprocess, sys, time\n"
                      "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                      "open(%r,'w').write(str(child.pid))\n"
                      "time.sleep(60)\n" % str(pidfile))
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            worker._execute([sys.executable, str(script)], time.time() + .5, dict(os.environ))
        child = int(pidfile.read_text())
        until = time.monotonic() + 2
        while _observed_pid_state(child) not in ('gone', 'Z', 'X') and time.monotonic() < until:
            time.sleep(.01)
        assert _observed_pid_state(child) in ('gone', 'Z', 'X')
        assert sentinel.poll() is None
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)


@pytest.mark.parametrize('sig', stop.SIGNALS)
def test_spawn_window_signal_cleans_owned_worker_and_restores_handlers(tmp_path, monkeypatch, sig):
    original_popen = subprocess.Popen
    launched = []
    def popen(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        launched.append(proc)
        os.kill(os.getpid(), sig)
        return proc
    monkeypatch.setattr(worker.subprocess, 'Popen', popen)
    previous = {number: signal.getsignal(number) for number in stop.SIGNALS}
    def interrupted(number, frame):
        raise stop.Stopped(number)
    for number in stop.SIGNALS:
        signal.signal(number, interrupted)
    try:
        with pytest.raises(stop.Stopped):
            worker._execute([sys.executable, '-c', 'import time; time.sleep(60)'],
                            time.time() + 10, dict(os.environ))
        assert launched[0].returncode is not None
        assert not stop.pid_alive(launched[0].pid)
        assert all(signal.getsignal(number) is interrupted for number in stop.SIGNALS)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@pytest.mark.parametrize('raw', ['{"schema":1,"schema":1}', '{"value":NaN}', '['])
def test_reply_duplicate_keys_nonfinite_and_invalid_json_refuse(raw):
    with pytest.raises(ProofUnavailable, match='reply_malformed'):
        worker._json(raw)


@pytest.fixture
def critical_case(context, monkeypatch):
    from copy import deepcopy
    from types import ModuleType
    from tests.test_final_custody import completed
    grader, facts, report, ledger, token = completed(context)
    expected = {'footprints': [], 'rules_outline': {'edge_clearance': 1.0}, 'fixed_copper': [],
                'protected_forms': {'fixed': [['segment', ['uuid', 'fixed-track']]],
                                    'zones': [['zone', ['net', 'GND'], ['priority', '1']]]}}
    helper = ModuleType('placemat.final_preservation')
    helper.CandidateRefused = ProofUnavailable
    observations = []
    def manifest(geometry, source):
        observations.append((geometry, source))
        return deepcopy(expected)
    helper.manifest = manifest
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    measures = {'critical_checks': 0, 'critical_unknown': [], 'findings': {'clearance': 0}}
    critical = {'measures': measures,
                'evidence': {'critical_checks': 0, 'critical_unknown': [], 'final_findings': {'clearance': 0}},
                'preservation': {'original_manifest': deepcopy(expected), 'held_and_fixed_preserved': True}}
    return grader, {'source_physical': deepcopy(expected)}, critical, observations


def test_parent_validates_private_source_manifest_and_critical_agreement_before_mint(critical_case):
    grader, context, critical, observations = critical_case
    worker._validate_critical(grader, context, critical)
    assert len(observations) == 1
    assert observations[0][1] == grader._original
    assert not grader._minted


@pytest.mark.parametrize('change', ['truthy-preservation', 'missing-zone-definition',
                                   'caller-manifest', 'missing-manifest', 'dropped-zone', 'dropped-fixed',
                                   'manifest-bool', 'caller-manifest-bool', 'non-json-manifest', 'non-json-evidence',
                                   'critical-bool', 'evidence-bool', 'evidence-count', 'unknown-evidence'])
def test_invalid_critical_and_preservation_reply_cannot_mint(critical_case, change):
    grader, context, critical, observations = critical_case
    if change == 'truthy-preservation':
        critical['preservation']['held_and_fixed_preserved'] = 1
    elif change == 'missing-zone-definition':
        critical['preservation']['original_manifest']['protected_forms'].pop('zones')
    elif change == 'caller-manifest':
        context['source_physical']['footprints'] = ['caller replacement']
    elif change == 'missing-manifest':
        critical['preservation'].pop('original_manifest')
    elif change == 'dropped-zone':
        critical['preservation']['original_manifest']['protected_forms']['zones'] = []
    elif change == 'dropped-fixed':
        critical['preservation']['original_manifest']['protected_forms']['fixed'] = []
    elif change == 'manifest-bool':
        critical['preservation']['original_manifest']['rules_outline']['edge_clearance'] = True
    elif change == 'caller-manifest-bool':
        context['source_physical']['rules_outline']['edge_clearance'] = True
    elif change == 'non-json-manifest':
        critical['preservation']['original_manifest']['rules_outline']['edge_clearance'] = object()
    elif change == 'non-json-evidence':
        critical['evidence']['final_findings']['clearance'] = object()
    elif change == 'evidence-bool':
        critical['evidence']['critical_checks'] = False
    elif change == 'critical-bool':
        critical['measures']['critical_checks'] = False
    elif change == 'evidence-count':
        critical['evidence']['critical_checks'] = 1
    else:
        critical['evidence']['unknown'] = True
    with pytest.raises(ProofUnavailable):
        worker._validate_critical(grader, context, critical)
    assert not grader._minted
