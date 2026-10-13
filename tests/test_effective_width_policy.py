"""The router's widths per phase: asked of the router, applied to each obligation, and failures kept as records."""
import dataclasses
import json
import sys

import pytest

from placemat.kicad import phase_run, width_policy
from placemat.kicad.phase_select import Selection, Task
from placemat.route_phase import parse_phases
from placemat.settings import Settings


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


def test_resolved_widths_replace_a_widthless_obligation():
    (phase,) = parse_phases([{'name': 'signals'}])
    def applied(width):
        policy = {'policies': [{'name': 'signals', 'by_net': {'VB': {'status': 'known', 'widths': {'F.Cu': width}}}}]}
        return width_policy.apply([[obligation()]], [selected()], [phase], policy)[0]
    assert applied(0.2)[0]['widths'] == {'F.Cu': 0.2} and applied(0.5)[0]['widths'] == {'F.Cu': 0.5}


def test_explicit_task_and_pour_task_keep_their_own_required_widths():
    (phase,) = parse_phases([{'name': 'current', 'current_paths': True, 'width': 'current'}])
    task = Task('VB', ('J1', '1'), ('J2', '1'), (('F.Cu', 0.3),), 1.0)
    sel = Selection('current', 'current_paths', tasks=(task,), pour_nets=('VB',), layers=('F.Cu',))
    policy = {'policies': [{'name': 'current', 'by_net': {'VB': {'status': 'known', 'widths': {'F.Cu': 0.8}}}}]}
    obs = [[obligation({'F.Cu': 0.3})]]
    assert width_policy.apply(obs, [sel], [phase], policy) == obs


def test_unknown_nominal_policy_cannot_certify_a_connected_board(tmp_path, monkeypatch):
    (phase,) = parse_phases([{'name': 'signals'}])
    policy = {'policies': [{'name': 'signals', 'by_net': {'VB': {'status': 'unknown', 'widths': None,
                                                                 'reason': 'stored impedance'}}}]}
    (obs,) = width_policy.apply([[obligation()]], [selected()], [phase], policy)
    drc = tmp_path / 'drc.json'; drc.write_text('{"violations": []}')
    monkeypatch.setattr(phase_run, 'joined_pairs', lambda *args: [True])
    (judgment,) = phase_run.judge_obligations('board', obs, drc, is_real=lambda _: False)
    assert judgment['joined'] and judgment['width_unknown'] and not phase_run.is_clean(judgment)
    assert phase_run.widths_failed([[judgment]]) == 1
    assert phase_run.open_entry(obs[0], judgment, None, {})['width_policy_failure'] == {
        'code': 'router_unknown', 'facts': {'reason': 'stored impedance'}}


def test_length_mismatch_and_conflicting_policy_scopes_are_not_silently_truncated():
    (phase,) = parse_phases([{'name': 'signals'}])
    with pytest.raises(ValueError, match='count mismatch'):
        width_policy.requests_of([phase], [], Settings())
    with pytest.raises(ValueError, match='count mismatch'):
        width_policy.apply([], [selected()], [phase], {'policies': []})
    policy = {'policies': [{'name': 'signals', 'by_net': {'VB': {'status': 'known', 'widths': {'F.Cu': w}}}}
                           for w in (0.11, 0.16)]}
    (obs,) = width_policy.apply([[obligation()]], [selected()], [phase], policy)
    assert obs[0]['width_policy_unknown'] and obs[0]['width_policy_failure']['code'] == 'conflicting_policies'


def query(tmp_path, text):
    """A stand-in router checkout whose width query is `text`."""
    script = tmp_path / 'py_router' / 'nominal_width_policy.py'
    script.parent.mkdir(exist_ok=True)
    script.write_text(text)
    return tmp_path


def resolve(router, rpy=sys.executable, **kwargs):
    (phase,) = parse_phases([{'name': 'signals'}])
    return width_policy.resolve(rpy, router, router / 'b.kicad_pcb', [phase], [selected()], Settings(),
                                router / 'width_policy.log', **kwargs)


def test_an_answer_gives_each_net_its_widths(tmp_path):
    answer = {'schema': 1, 'policies': [{'name': 'signals', 'kind': 'nets', 'by_net': {
        'VB': {'status': 'known', 'widths': {'F.Cu': 0.2, 'B.Cu': 0.25}, 'options': {}}}}]}
    router = query(tmp_path, 'import sys, json; json.load(sys.stdin); print("noise"); '
                             'print("PLACEMAT_WIDTH_POLICY " + %r)' % json.dumps(answer))
    got = resolve(router)
    assert 'failure' not in got
    assert got['policies'] == [{'name': 'signals', 'kind': 'nets',
                                'by_net': {'VB': {'status': 'known', 'widths': {'F.Cu': 0.2, 'B.Cu': 0.25}}}}]


def test_no_query_or_no_interpreter_is_unavailable(tmp_path):
    missing = resolve(tmp_path)
    assert missing['failure'] == {'code': 'unavailable',
                                  'facts': {'script': str(tmp_path / 'py_router/nominal_width_policy.py')}}
    assert missing['policies'][0]['by_net']['VB']['status'] == 'unknown'
    router = query(tmp_path, '')
    failed = resolve(router, rpy=str(tmp_path / 'missing'))
    assert failed['failure']['code'] == 'unavailable' and failed['failure']['facts']['error'] == 'FileNotFoundError'


def test_a_query_past_its_timeout_is_stopped_and_every_net_is_unknown(tmp_path):
    router = query(tmp_path, 'import time; time.sleep(60)')
    got = resolve(router, timeout=0.5)
    assert got['failure'] == {'code': 'timeout', 'facts': {'seconds': 0.5, 'log': str(tmp_path / 'width_policy.log')}}
    assert got['policies'][0]['by_net']['VB'] == {'status': 'unknown', 'widths': None}


def test_a_failed_query_is_a_record_with_its_exit_code(tmp_path):
    got = resolve(query(tmp_path, 'import sys; sys.exit(3)'))
    assert got['failure'] == {'code': 'failed', 'facts': {'exit_code': 3, 'log': str(tmp_path / 'width_policy.log')}}


@pytest.mark.parametrize('damage, problem', [('schema', 'schema'), ('count', 'scope_count'), ('net', 'net_membership'),
                                             ('layers', 'layer_membership'), ('width', 'width'),
                                             ('silent', 'no_answer'), ('text', 'not_json')])
def test_an_answer_that_does_not_fit_the_request_is_malformed(tmp_path, damage, problem):
    answer = {'schema': 1, 'policies': [{'name': 'signals', 'kind': 'nets', 'by_net': {
        'VB': {'status': 'known', 'widths': {'F.Cu': 0.2, 'B.Cu': 0.2}}}}]}
    entry = answer['policies'][0]['by_net']['VB']
    line = 'PLACEMAT_WIDTH_POLICY ' + json.dumps(answer)
    if damage == 'schema':
        line = line.replace('"schema": 1', '"schema": true')
    elif damage == 'count':
        line = 'PLACEMAT_WIDTH_POLICY ' + json.dumps(dict(answer, policies=[]))
    elif damage == 'net':
        answer['policies'][0]['by_net'] = {'OTHER': entry}
        line = 'PLACEMAT_WIDTH_POLICY ' + json.dumps(answer)
    elif damage == 'layers':
        del entry['widths']['B.Cu']
        line = 'PLACEMAT_WIDTH_POLICY ' + json.dumps(answer)
    elif damage == 'width':
        line = line.replace('0.2}', 'NaN}')
    elif damage == 'silent':
        line = 'nothing'
    else:
        line = 'PLACEMAT_WIDTH_POLICY {'
    got = resolve(query(tmp_path, 'print(%r)' % line))
    assert got['failure'] == {'code': 'malformed', 'facts': {'problem': problem, 'log': str(tmp_path / 'width_policy.log')}}
    assert got['policies'][0]['by_net']['VB']['status'] == 'unknown'


def test_a_failed_query_marks_each_obligation_with_its_failure():
    (phase,) = parse_phases([{'name': 'signals'}])
    policy = {'failure': {'code': 'timeout', 'facts': {'seconds': 1.0}},
              'policies': [{'name': 'signals', 'kind': 'nets', 'by_net': {'VB': {'status': 'unknown', 'widths': None}}}]}
    ((item,),) = width_policy.apply([[obligation()]], [selected()], [phase], policy)
    assert item['width_policy_unknown'] and item['width_policy_failure'] == {'code': 'timeout', 'facts': {'seconds': 1.0}}


def test_a_phase_key_follows_its_own_widths_and_status_only():
    earlier = {'name': 'early', 'kind': 'nets', 'by_net': {'A': {'status': 'known', 'widths': {'F.Cu': .2}}}}
    later = {'name': 'late', 'kind': 'nets', 'by_net': {'B': {'status': 'known', 'widths': {'F.Cu': .3}}}}
    before = {'schema': 1, 'policies': [earlier, later]}
    after = json.loads(json.dumps(before))
    after['policies'][1]['by_net']['B']['widths']['F.Cu'] = .4
    assert width_policy.phase_key(before, 'early') == width_policy.phase_key(after, 'early')
    assert width_policy.phase_key(before, 'late') != width_policy.phase_key(after, 'late')
    unknown = json.loads(json.dumps(before))
    unknown['policies'][0]['by_net']['A'] = {'status': 'unknown', 'widths': None, 'reason': 'unproved'}
    assert width_policy.phase_key(before, 'early') != width_policy.phase_key(unknown, 'early')


def test_an_interrupted_query_stops_its_process(tmp_path, monkeypatch):
    from placemat import stop
    router = query(tmp_path, 'import time\ntime.sleep(60)\n')
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
        resolve(router)
    assert launched[0].returncode is not None and not stop.pid_alive(launched[0].pid)
