"""Requested router widths cannot silently disappear from final certificates."""
import dataclasses
import json

import pytest

from placemat.kicad import phase_run, width_policy
from placemat.kicad.phase_select import Selection, Task
from placemat.route_phase import parse_phases
from placemat.settings import Settings


def _observed_pid_state(pid):
    from pathlib import Path
    try:
        stat = Path('/proc/%d/stat' % pid).read_text()
    except FileNotFoundError:
        return 'gone'
    # A process command name may contain spaces or parentheses.
    return stat.rpartition(')')[2].split()[0]


def test_unreaped_zombie_is_terminated_despite_existing_pid():
    import subprocess
    import sys
    import time
    from placemat.stop import pid_alive
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        assert _observed_pid_state(child.pid) not in ('gone', 'Z', 'X')
        child.kill()  # only this directly owned process; deliberately do not reap yet
        until = time.monotonic() + 2.0
        state = _observed_pid_state(child.pid)
        while state != 'Z' and time.monotonic() < until:
            time.sleep(.01)
            state = _observed_pid_state(child.pid)
        assert state == 'Z'
        assert pid_alive(child.pid)  # the production utility correctly reports PID existence
    finally:
        child.kill()
        child.wait()


def selected(name='signals', **kwargs):
    return Selection(name, 'rest', nets=('VB',), layers=('F.Cu', 'B.Cu'), rest=True, **kwargs)


def obligation(widths=None):
    return {'net': 'VB', 'from': {'ref': 'J1', 'pad': '1'}, 'to': {'ref': 'J2', 'pad': '1'}, 'widths': widths}


def test_single_and_pair_flags_have_distinct_scopes_and_phase_flags_last():
    phases = parse_phases([{'name': 'pair', 'pairs': [['P', 'N']], 'router_args': ['--track-width', '0.11']},
                           {'name': 'signals', 'router_args': ['--track-width=0.4']}])
    sels = [Selection('pair', 'pairs', pairs=(('P', 'N'),), layers=('F.Cu',)), selected()]
    cfg = dataclasses.replace(Settings(), route_router_args=('--track-width', '0.5'),
                              route_pair_router_args=('--track-width', '0.2'))
    pair, single = width_policy.requests_of(phases, sels, cfg)
    assert pair['args'] == ['--track-width', '0.2', '--track-width', '0.11']
    assert single['args'] == ['--track-width', '0.5', '--track-width=0.4']


def test_default_rest_inherits_prior_pair_geometry_but_explicit_numeric_rest_does_not():
    phases = parse_phases([{'name': 'pair', 'pairs': [['P', 'N']]}, {'name': 'signals'}])
    pair = Selection('pair', 'pairs', pairs=(('P', 'N'),), layers=('F.Cu',))
    rest = dataclasses.replace(selected(), nets=('P', 'N', 'VB'))
    requests = width_policy.requests_of(phases, [pair, rest], Settings())
    inherited = next(r for r in requests if r['name'] == 'signals' and r['kind'] == 'pairs')
    ordinary = next(r for r in requests if r['name'] == 'signals' and r['kind'] == 'nets')
    assert inherited['owner'] == 'pair' and inherited['pairs'] == [['P', 'N']]
    assert ordinary['nets'] == ['VB']
    numeric = dataclasses.replace(rest, width=0.3)
    requests = width_policy.requests_of(phases, [pair, numeric], Settings())
    assert requests[-1]['kind'] == 'nets' and requests[-1]['power'] == {'P': 0.3, 'N': 0.3, 'VB': 0.3}


def test_resolved_global_class_widths_replace_widthless_obligation_and_bind_contract():
    (phase,) = parse_phases([{'name': 'signals'}])
    def applied(width):
        policy = {'policies': [{'name': 'signals', 'by_net': {'VB': {'status': 'known', 'widths': {'F.Cu': width}}}}]}
        return width_policy.apply([[obligation()]], [selected()], [phase], policy)[0]
    class_obs, global_obs = applied(0.2), applied(0.5)
    assert class_obs[0]['widths'] == {'F.Cu': 0.2}
    assert phase_run.comparison_contract(phase, class_obs) != phase_run.comparison_contract(phase, global_obs)


def test_explicit_task_and_pour_task_keep_their_own_required_widths():
    (phase,) = parse_phases([{'name': 'current', 'current_paths': True, 'width': 'current'}])
    task = Task('VB', ('J1', '1'), ('J2', '1'), (('F.Cu', 0.3),), 1.0)
    sel = Selection('current', 'current_paths', tasks=(task,), pour_nets=('VB',), layers=('F.Cu',))
    policy = {'policies': [{'name': 'current', 'by_net': {'VB': {'status': 'known', 'widths': {'F.Cu': 0.8}}}}]}
    obs = [[obligation({'F.Cu': 0.3})]]
    assert width_policy.apply(obs, [sel], [phase], policy) == obs


def test_unknown_nominal_policy_cannot_certify_a_connected_board(tmp_path, monkeypatch):
    (phase,) = parse_phases([{'name': 'signals'}])
    policy = {'policies': [{'name': 'signals', 'by_net': {'VB': {'status': 'unknown', 'reason': 'stored impedance'}}}]}
    (obs,) = width_policy.apply([[obligation()]], [selected()], [phase], policy)
    drc = tmp_path / 'drc.json'; drc.write_text('{"violations": []}')
    monkeypatch.setattr(phase_run, 'joined_pairs', lambda *args: [True])
    (judgment,) = phase_run.judge_obligations('board', obs, drc, is_real=lambda _: False)
    assert judgment['joined'] and judgment['width_unknown'] and not phase_run.is_clean(judgment, None)
    assert phase_run.widths_failed([{}], [obs], [[judgment]]) == 1
    assert phase_run.open_entry(obs[0], judgment, [], {})['width_policy_reason'] == 'stored impedance'


def test_length_mismatch_and_conflicting_policy_scopes_are_not_silently_truncated():
    (phase,) = parse_phases([{'name': 'signals'}])
    with pytest.raises(ValueError, match='count mismatch'):
        width_policy.requests_of([phase], [], Settings())
    with pytest.raises(ValueError, match='count mismatch'):
        width_policy.apply([], [selected()], [phase], {'policies': []})
    policy = {'policies': [{'name': 'signals', 'by_net': {'VB': {'status': 'known', 'widths': {'F.Cu': w}}}}
                           for w in (0.11, 0.16)]}
    (obs,) = width_policy.apply([[obligation()]], [selected()], [phase], policy)
    assert obs[0]['width_policy_unknown'] and 'conflicting' in obs[0]['width_policy_reason']


def test_missing_interpreter_and_expired_deadline_are_structured_unknown(tmp_path, monkeypatch):
    script = tmp_path / 'py_router' / 'nominal_width_policy.py'; script.parent.mkdir(); script.write_text('')
    (phase,) = parse_phases([{'name': 'signals'}])
    expired = width_policy.resolve('missing', tmp_path, tmp_path / 'b.kicad_pcb', [phase], [selected()],
                                    Settings(), {'KRT_ROUTE_DEADLINE_UTC': '1'})
    assert expired['failure']['code'] == 'deadline'
    missing = width_policy.resolve(str(tmp_path / 'missing'), tmp_path, tmp_path / 'b.kicad_pcb', [phase],
                                    [selected()], Settings())
    assert missing['failure']['code'] == 'unavailable'


def test_policy_authority_invalidates_unknown_to_known_and_changed_source():
    base = {'schema': 1, 'config_sha256': 'a', 'sources': {'rule.py': 'one'}, 'policies': [
        {'name': 'signals', 'kind': 'nets', 'by_net': {'VB': {'status': 'unknown', 'reason': 'unavailable'}}}]}
    known = json.loads(json.dumps(base)); known['policies'][0]['by_net']['VB'] = {'status': 'known', 'widths': {'F.Cu': 0.2}}
    changed = dict(known, sources={'rule.py': 'two'})
    assert width_policy.authority(base) != width_policy.authority(known) != width_policy.authority(changed)


def test_policy_timeout_terminates_its_child_group_and_preserves_unrelated_process(tmp_path):
    import subprocess
    import sys
    import time
    script = tmp_path / 'py_router' / 'nominal_width_policy.py'; script.parent.mkdir()
    pidfile = tmp_path / 'child.pid'
    script.write_text("import subprocess, sys, time\n"
                      "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                      "open(%r, 'w').write(str(child.pid))\n"
                      "time.sleep(60)\n" % str(pidfile))
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        (phase,) = parse_phases([{'name': 'signals'}])
        result = width_policy.resolve(sys.executable, tmp_path, tmp_path / 'b.kicad_pcb', [phase], [selected()],
                                       Settings(), timeout=0.5)
        assert result['failure']['code'] == 'timeout'
        assert pidfile.exists()
        child_pid = int(pidfile.read_text())
        observations = []
        until = time.monotonic() + 2.0
        while True:
            state = _observed_pid_state(child_pid)
            observations.append({'elapsed': 2.0 - (until - time.monotonic()), 'state': state})
            if state in ('gone', 'Z', 'X') or time.monotonic() >= until:
                break
            time.sleep(.01)
        (tmp_path / 'child-states.json').write_text(json.dumps(observations, indent=2))
        assert state in ('gone', 'Z', 'X'), observations
        assert sentinel.poll() is None
    finally:
        sentinel.kill(); sentinel.wait()


@pytest.mark.parametrize('damage', ['schema', 'count', 'width', 'input', 'source'])
def test_malformed_policy_receipts_cannot_certify_widths(tmp_path, monkeypatch, damage):
    import hashlib
    from types import SimpleNamespace
    (phase,) = parse_phases([{'name': 'signals'}])
    script = tmp_path / 'py_router' / 'nominal_width_policy.py'
    script.parent.mkdir(); script.write_text('# policy\n')
    board = tmp_path / 'b.kicad_pcb'; board.write_text('board')
    requests = width_policy.requests_of([phase], [selected()], Settings())
    receipt = {'schema': 1, 'config_sha256': hashlib.sha256(json.dumps(requests, sort_keys=True).encode()).hexdigest(),
               'board': str(board), 'inputs': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
                   for p in (board, board.with_suffix('.kicad_pro'), board.with_suffix('.kicad_dru'))},
               'sources': {'py_router/nominal_width_policy.py': hashlib.sha256(script.read_bytes()).hexdigest()},
               'policies': [{'name': 'signals', 'kind': 'nets', 'by_net': {'VB': {'status': 'known',
                   'widths': {'F.Cu': 0.2, 'B.Cu': 0.2}}}}]}
    if damage == 'schema': receipt['schema'] = True
    elif damage == 'count': receipt['policies'] = []
    elif damage == 'width': receipt['policies'][0]['by_net']['VB']['widths']['F.Cu'] = float('nan')
    elif damage == 'input': receipt['inputs'][str(board)] = 'wrong'
    else: receipt['sources'] = {}
    monkeypatch.setattr(width_policy.subprocess, 'Popen', lambda *args, **kwargs: SimpleNamespace(returncode=0,
        communicate=lambda *a, **k: ('PLACEMAT_WIDTH_POLICY ' + json.dumps(receipt), '')))
    result = width_policy.resolve('python', tmp_path, board, [phase], [selected()], Settings())
    assert result['failure']['code'] == 'malformed'
    assert result['policies'][0]['by_net']['VB']['status'] == 'unknown'


def test_interrupted_policy_wait_reaps_only_owned_process(tmp_path, monkeypatch):
    import sys
    from placemat import stop
    (phase,) = parse_phases([{'name': 'signals'}])
    script = tmp_path / 'py_router' / 'nominal_width_policy.py'
    script.parent.mkdir(); script.write_text('import time\ntime.sleep(60)\n')
    real_popen = width_policy.subprocess.Popen
    launched = []
    def popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        launched.append(proc)
        original = proc.communicate
        count = 0
        def communicate(*a, **kw):
            nonlocal count
            count += 1
            if count == 1:
                raise KeyboardInterrupt
            return original(*a, **kw)
        proc.communicate = communicate
        return proc
    monkeypatch.setattr(width_policy.subprocess, 'Popen', popen)
    with pytest.raises(KeyboardInterrupt):
        width_policy.resolve(sys.executable, tmp_path, tmp_path / 'b', [phase], [selected()], Settings())
    assert launched[0].returncode is not None and not stop.pid_alive(launched[0].pid)


def test_later_policy_config_changes_do_not_change_earlier_phase_authority():
    earlier = {'name': 'early', 'kind': 'nets', 'by_net': {'A': {'status': 'known', 'widths': {'F.Cu': .2}}}}
    later = {'name': 'late', 'kind': 'nets', 'by_net': {'B': {'status': 'known', 'widths': {'F.Cu': .3}}}}
    before = {'schema': 1, 'config_sha256': 'all-before', 'sources': {'resolver.py': 'same'},
              'external_inputs': {'fab': 'same'}, 'policies': [earlier, later]}
    after = json.loads(json.dumps(before))
    after['config_sha256'] = 'all-after'
    after['policies'][1]['by_net']['B']['widths']['F.Cu'] = .4
    assert width_policy.shared_authority(before) == width_policy.shared_authority(after)
    assert width_policy.phase_authority(before, 'early') == width_policy.phase_authority(after, 'early')
    assert width_policy.phase_authority(before, 'late') != width_policy.phase_authority(after, 'late')
    for field in ('sources', 'external_inputs'):
        changed = dict(after, **{field: {'changed': 'different'}})
        assert width_policy.shared_authority(before) != width_policy.shared_authority(changed)
    unknown = json.loads(json.dumps(before))
    unknown['policies'][0]['by_net']['A'] = {'status': 'unknown', 'reason': 'unproved'}
    assert width_policy.phase_authority(before, 'early') != width_policy.phase_authority(unknown, 'early')
