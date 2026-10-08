"""Actual-call receipts retain artifacts without asserting routing legality."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from placemat.kicad import final_custody as custody, issued_calls as calls
from placemat.kicad.final_call import ProofUnavailable
from tests.test_final_custody import context, register


@pytest.fixture
def issued(context, tmp_path):
    grader, facts, report = register(context)
    executor = object()
    ledger = custody._executor_begin_calls(grader, executor)
    task = deepcopy(report.asked[0][0])
    task_file = tmp_path / 'tasks.json'
    task_file.write_text(json.dumps([task]))
    options = dict(phase=0, call=0, wave=0, kind='connections',
                   command=['python', 'route.py', '--connections', str(task_file)],
                   source=grader._original, input_board=grader._original,
                   output_board=tmp_path / 'call.kicad_pcb', summary=tmp_path / 'summary.json',
                   layers=['F.Cu'], nets=['N'], tasks=[task], constraint_files=(),
                   snapshot_dir=tmp_path / 'before', task_file=task_file)
    return grader, ledger, executor, options


def issue(issued):
    grader, ledger, executor, options = issued
    return calls._executor_issue(grader, ledger, executor, **options)


@pytest.mark.parametrize('environment', [[], {'KRT_INTERNAL_ROUTE_CANDIDATE': True},
                                        {'KRT_ROUTE_DEADLINE_UTC': 123}])
def test_malformed_execution_transport_refuses_before_snapshot(issued, environment):
    issued[3]['environment'] = environment
    with pytest.raises(ProofUnavailable, match='execution_environment_malformed'):
        issue(issued)
    assert not issued[3]['snapshot_dir'].exists()


def test_execution_transport_is_detached_and_excludes_unrelated_environment(issued):
    environment = {'KRT_INTERNAL_ROUTE_CANDIDATE': '1',
                   'KRT_ROUTE_DEADLINE_UTC': '123', 'UNRELATED_SECRET': 'private'}
    issued[3]['environment'] = environment
    token = issue(issued)
    environment['KRT_INTERNAL_ROUTE_CANDIDATE'] = 'changed'
    assert token.record['execution_transport']['KRT_INTERNAL_ROUTE_CANDIDATE'] == '1'
    assert 'UNRELATED_SECRET' not in token.record['execution_transport']


def test_actual_plan_cannot_be_changed_before_issuance(issued):
    from placemat.kicad.phase_run import Call
    grader, ledger, executor, options = issued
    calls._executor_plan(grader, ledger, executor, phase=0, calls=[Call('tasks')],
                         layers=['F.Cu'], input_board=options['input_board'])
    ledger.call_plans[0][0]['calls'][0]['kind'] = 'nets'
    with pytest.raises(ProofUnavailable, match='plan_changed'):
        issue(issued)
    assert not options['snapshot_dir'].exists()


def test_actual_issued_kind_must_match_plan(issued):
    from placemat.kicad.phase_run import Call
    grader, ledger, executor, options = issued
    calls._executor_plan(grader, ledger, executor, phase=0, calls=[Call('nets', ('N',))],
                         layers=['F.Cu'], input_board=options['input_board'])
    with pytest.raises(ProofUnavailable, match='kind_outside_plan'):
        issue(issued)
    assert not options['snapshot_dir'].exists()


def test_completed_phase_retains_actual_plan_in_sealed_ledger_input(issued, tmp_path):
    from placemat.kicad.phase_run import Call
    grader, ledger, executor, options = issued
    calls._executor_plan(grader, ledger, executor, phase=0, calls=[Call('tasks')],
                         layers=['F.Cu'], input_board=options['input_board'])
    token = issue(issued)
    finish(issued, token, tmp_path)
    custody._executor_record_phase(grader, ledger, executor, 0,
                                  {'name': grader._phases[0].name},
                                  calls=[(grader._phases[0].name, 0, str(options['summary']))],
                                  outputs={str(options['output_board']): calls.file_hash(options['output_board'])})
    assert ledger.phases[0]['actual_call_plan'] == ledger.call_plans[0][0]
    ledger.call_plans[0][0]['calls'].clear()
    assert len(ledger.phases[0]['actual_call_plan']['calls']) == 1


def finish(issued, token, tmp_path):
    grader, ledger, executor, options = issued
    options['output_board'].write_text('actual raw result')
    options['summary'].write_text(json.dumps({'connections': [dict(task, status='routed') for task in options['tasks']]}))
    calls._executor_raw_result(grader, ledger, executor, token, returncode=0,
                               snapshot_dir=tmp_path / 'raw')
    options['output_board'].write_text('restored actual result')
    source_pro = Path(options['source']).with_suffix('.kicad_pro')
    options['output_board'].with_suffix('.kicad_pro').write_bytes(source_pro.read_bytes())
    return calls._executor_restored_result(grader, ledger, executor, token)


def test_actual_input_raw_and_restored_are_distinct_immutable_receipts(issued, tmp_path):
    token = issue(issued)
    record = finish(issued, token, tmp_path)
    raw_path = next(p for p in record['raw']['files'] if p.endswith('call.kicad_pcb'))
    assert Path(raw_path).read_text() == 'actual raw result'
    assert issued[3]['output_board'].read_text() == 'restored actual result'
    record['tasks'][0]['widths']['F.Cu'] = 99
    assert calls.completed_record(*issued[:3], token)['tasks'][0]['widths']['F.Cu'] == .2


@pytest.mark.parametrize('change', ['task', 'file', 'owner', 'phase'])
def test_unproved_actual_scope_cannot_issue(issued, change):
    grader, ledger, executor, options = issued
    if change == 'task':
        options['tasks'][0]['widths']['F.Cu'] = .1
    elif change == 'file':
        options['task_file'].write_text('[]')
    elif change == 'owner':
        executor = object()
    else:
        options['phase'] = 1
    with pytest.raises(ProofUnavailable):
        calls._executor_issue(grader, ledger, executor, **options)
    assert not options['snapshot_dir'].exists()


def test_incomplete_and_duplicate_calls_refuse(issued, tmp_path):
    token = issue(issued)
    with pytest.raises(ProofUnavailable, match='previous_incomplete'):
        issue(issued)
    finish(issued, token, tmp_path)
    with pytest.raises(ProofUnavailable, match='duplicate'):
        issue(issued)


@pytest.mark.parametrize('code', [1, True])
def test_nonzero_or_boolean_return_cannot_complete(issued, tmp_path, code):
    token = issue(issued)
    with pytest.raises(ProofUnavailable):
        calls._executor_raw_result(*issued[:3], token, returncode=code,
                                   snapshot_dir=tmp_path / 'raw')
    assert token.raw is None


def test_changed_snapshot_and_restored_artifact_refuse(issued, tmp_path):
    token = issue(issued)
    finish(issued, token, tmp_path)
    issued[3]['output_board'].write_text('changed')
    with pytest.raises(ProofUnavailable, match='artifact_changed'):
        calls.completed_record(*issued[:3], token)


def test_public_record_cannot_substitute_token(issued):
    token = issue(issued)
    with pytest.raises(ProofUnavailable, match='token_mismatch'):
        calls.completed_record(*issued[:3], deepcopy(token.record))


def test_truncated_actual_connection_summary_cannot_complete(issued, tmp_path):
    token = issue(issued)
    options = issued[3]
    options['output_board'].write_text('actual result')
    options['summary'].write_text('{"connections": []}')
    with pytest.raises(ProofUnavailable, match='connection_summary_unproved'):
        calls._executor_raw_result(*issued[:3], token, returncode=0,
                                   snapshot_dir=tmp_path / 'raw')
    assert token.raw is None


def test_real_task_wave_sites_capture_before_and_after_restoration(context, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from placemat.kicad import phase_run
    from placemat.kicad.final_execution import FinalExecution
    from placemat.kicad.phase_select import Selection, Task
    grader, facts, report = register(context)
    hook = object.__new__(FinalExecution)
    hook.work, hook.active, hook.grader = tmp_path, True, grader
    hook.executor, hook.refusals = object(), (ProofUnavailable,)
    hook.ledger = custody._executor_begin_calls(grader, hook.executor)
    task = Task('N', ('A', '1'), ('B', '1'), (('F.Cu', .2),))
    geometry = facts['geometry']
    ctx = phase_run.PhaseContext(
        Path('/usr/bin/python3'), 'route.py', str(tmp_path), tmp_path, ['F.Cu'],
        None, None, False, 60, {}, SimpleNamespace(route_router_args=()), geometry,
        {}, .2, None, set(), set(), None, execution=hook)
    phase = SimpleNamespace(name='signals', router_args=(), neckdown=False)
    selected = Selection('signals', 'connections', tasks=(task,), layers=('F.Cu',))
    monkeypatch.setattr(phase_run, 'router_command',
                        lambda py, script, src, out, excluded, layers, summary, **kw:
                        [str(py), script, str(src), str(out), str(summary), str(kw['connections'])])
    def run(command, log, context):
        planned, planned_sha = hook.ledger.call_plans[0]
        assert planned['phase'] == 0 and planned['layers'] == ['F.Cu']
        assert planned['calls'][0]['kind'] == 'tasks'
        assert planned['calls'][0]['tasks'] == [task.record()]
        assert planned_sha == calls.record_digest(planned)
        assert len(hook.ledger.issued) == 1
        assert hook.ledger.issued[0].raw is None
        Path(command[3]).write_text('raw from actual issued wave')
        Path(command[4]).write_text(json.dumps({'connections': [dict(task.record(), status='routed')]}))
        return 0
    monkeypatch.setattr(phase_run, '_run', run)
    monkeypatch.setattr(phase_run, '_copy_project',
                        lambda src, out: Path(out).with_suffix('.kicad_pro').write_bytes(
                            Path(src).with_suffix('.kicad_pro').read_bytes()))
    def lock(path):
        token = hook.ledger.issued[0]
        assert token.raw is not None
        assert token.completed is None or Path(path).name == 'p0_0.kicad_pcb'
        Path(path).write_text('locked restored actual result')
    monkeypatch.setattr(phase_run, 'lock_copper', lock)
    for name in ('phase_widths', 'narrow_join_widths', 'task_widths'):
        monkeypatch.setattr(phase_run, name, lambda *args: [])
    outcome = phase_run.route_calls(ctx, 0, phase, selected, grader._original)
    assert hook.active
    token = hook.ledger.issued[0]
    assert token.record['tasks'][0]['widths'] == {'F.Cu': .2}
    assert token.completed is not None
    assert outcome.routed['connections'][0]['status'] == 'routed'
    raw = next(p for p in token.raw['files'] if p.endswith('p0_0_0.kicad_pcb'))
    assert Path(raw).read_text() == 'raw from actual issued wave'


@pytest.mark.parametrize('field,value', [('tasks', None), ('constraint_files', {}),
                                         ('source', []), ('summary', False),
                                         ('task_file', {}), ('constraint_files', [True])])
def test_malformed_named_scope_refuses_before_snapshot(issued, field, value):
    issued[3][field] = value
    with pytest.raises(ProofUnavailable):
        issue(issued)
    assert not issued[3]['snapshot_dir'].exists()


@pytest.mark.parametrize('field,value', [('nets', []), ('nets', ['N', 'N']),
                                        ('layers', ['F.Cu', 'B.Cu']), ('layers', ['F.Cu', 'F.Cu'])])
def test_actual_connection_scope_must_exactly_match_task_file(issued, field, value):
    issued[3][field] = value
    with pytest.raises(ProofUnavailable, match='connection_scope_mismatch'):
        issue(issued)
    assert not issued[3]['snapshot_dir'].exists()


@pytest.mark.parametrize('field', ['source', 'input_board'])
def test_board_absence_is_not_an_optional_sidecar(issued, tmp_path, field):
    issued[3][field] = tmp_path / 'absent.kicad_pcb'
    with pytest.raises(ProofUnavailable, match='board_missing'):
        issue(issued)


def test_arbitrary_restored_sidecar_cannot_be_proved(issued, tmp_path):
    token = issue(issued)
    options = issued[3]
    options['output_board'].write_text('raw actual result')
    options['summary'].write_text(json.dumps({'connections': [dict(t, status='routed') for t in options['tasks']]}))
    calls._executor_raw_result(*issued[:3], token, returncode=0, snapshot_dir=tmp_path / 'raw')
    options['output_board'].with_suffix('.kicad_pro').write_text('weakened arbitrary project')
    with pytest.raises(ProofUnavailable, match='restored_rules_changed'):
        calls._executor_restored_result(*issued[:3], token)
    assert token.completed is None


@pytest.fixture
def pour_execution(context, tmp_path):
    from placemat.kicad.final_execution import FinalExecution
    from placemat.kicad.final_route import FinalCopperGrader
    from tests.test_pour_identity import BOARD
    old, facts, report = context
    old._original.write_text(BOARD)
    old._phases[0].selector = 'current_paths'
    grader = FinalCopperGrader(
        original=old._original, cleanup_input=old._cleanup_input, rules=old._rules,
        baseline_drc=old._baseline, obligations=json.loads(old._obligations), phases=old._phases,
        width_receipt=json.loads(old._widths), cfg=old._cfg, counted=old._counted,
        open_before=old._open_before, chosen_pours={'N'},
        width_receipt_path=old._receipt_path, invocation=old._semantic_contract['invocation'])
    snapshot = Path(facts['read_identity']['snapshot_path'])
    snapshot.write_bytes(grader._original.read_bytes())
    facts['read_identity']['read_sha256'] = custody._hash(grader._original)
    facts['read_identity']['snapshot_sha256'] = custody._hash(snapshot)
    facts['read_manifest'] = dict(grader._inputs, **{str(snapshot): custody._hash(snapshot)})
    custody._executor_register_original(grader, **facts)
    hook = object.__new__(FinalExecution)
    hook.work, hook.active, hook.grader = tmp_path, True, grader
    hook.executor, hook.refusals = object(), (ProofUnavailable,)
    hook.ledger = custody._executor_begin_calls(grader, hook.executor)
    return hook


def test_actual_pour_helper_binds_transform_raw_and_guard_completion(pour_execution, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from placemat.kicad import route
    from placemat.kicad.phase_select import Task
    hook = pour_execution
    stages = []
    def strip(path, nets):
        stages.append('drop_own_guards')
    def normalize(path, net):
        stages.append('normalize_own_pour')
        return 0
    monkeypatch.setattr(route, 'drop_pour_guards', strip)
    monkeypatch.setattr(route, 'pours_as_zones', normalize)
    monkeypatch.setattr(route, 'router_command', lambda py, script, src, out, excluded, layers, summary, *a, **k:
                        [str(py), script, str(src), str(out), str(summary)])
    def run(command, **kwargs):
        assert stages == ['drop_own_guards', 'normalize_own_pour']
        token = hook.ledger.issued[0]
        assert token.record['pour_transform']['domain'] == 'single_net_pour_identity_normalization'
        Path(command[3]).write_bytes(Path(command[2]).read_bytes())
        Path(command[3]).with_suffix('.kicad_pro').write_text('raw router project rewrite')
        Path(command[4]).write_text(json.dumps(dict(successful=1, failed=0, total_iterations=3, total_vias=0, total_time=.1)))
        stages.append('actual_return')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(route.subprocess, 'run', run)
    def restore(out, source):
        assert hook.ledger.issued[0].raw is not None
        assert Path(out).with_suffix('.kicad_pro').read_text() == 'original required rules'
        stages.append('restore_own_pour')
    monkeypatch.setattr(route, 'pours_back', restore)
    monkeypatch.setattr(route, 'lock_copper', lambda path: stages.append('lock'))
    def guards(path, nets, layers, share):
        assert hook.ledger.issued[0].completed is None
        stages.append('restore_own_guards')
        return []
    monkeypatch.setattr(route, 'guard_partial_pours', guards)
    ctx = SimpleNamespace(work=tmp_path, cfg=SimpleNamespace(route_plane_share=.5),
                          rpy=Path('/usr/bin/python3'), script='route.py', iterations=None,
                          probe=None, quick=False, clearances_file=None, router_dir=tmp_path,
                          env={}, timeout=10, layers=['F.Cu'], execution=hook)
    task = Task('N', ('A', '1'), ('B', '1'), (('F.Cu', .2),))
    route.route_pour_net(ctx, hook.grader._original, tmp_path/'p0_0.kicad_pcb', 'N', .2,
                         ['F.Cu'], 'p0_0', _issued_scope=(0, 0, (task,)))
    assert hook.active
    token = hook.ledger.issued[0]
    assert token.completed['pour_transform']['domain'] == 'single_net_pour_identity_normalization'
    assert token.record['tasks'] == [calls._task(task.record())]
    assert stages == ['drop_own_guards', 'normalize_own_pour', 'actual_return',
                      'restore_own_pour', 'lock', 'restore_own_guards']


def pour_issue(hook, tmp_path, **changed):
    task = json.loads(hook.grader._obligations)[0][0]
    options = dict(phase=0, call=0, wave=0, kind='pour', command=['python', 'route.py'],
                   source=hook.grader._original, input_board=hook.grader._original,
                   output_board=tmp_path/'out.kicad_pcb', summary=tmp_path/'summary.json',
                   layers=['F.Cu'], nets=['N'], tasks=[task], constraint_files=(),
                   snapshot_dir=tmp_path/'issued')
    options.update(changed)
    return calls._executor_issue(hook.grader, hook.ledger, hook.executor, **options), options


@pytest.mark.parametrize('changed', [{'tasks': []}, {'nets': []}, {'nets': ['N', 'N']},
                                      {'layers': ['F.Cu', 'B.Cu']}])
def test_pour_original_task_net_and_layer_vectors_are_exact(pour_execution, tmp_path, changed):
    with pytest.raises(ProofUnavailable):
        pour_issue(pour_execution, tmp_path, **changed)
    assert not (tmp_path/'issued').exists()


@pytest.mark.parametrize('summary', [{}, {'successful': True},
                                     dict(successful=1, failed=0, total_iterations=3,
                                          total_vias=0, total_time=.1, aborted=True),
                                     dict(successful=1, failed=0, total_iterations=3,
                                          total_vias=0, total_time=float('nan'))])
def test_pour_execution_summary_not_arbitrary_dict(pour_execution, tmp_path, summary):
    token, options = pour_issue(pour_execution, tmp_path)
    options['output_board'].write_bytes(pour_execution.grader._original.read_bytes())
    options['summary'].write_text(json.dumps(summary))
    with pytest.raises(ProofUnavailable, match='pour_summary_unproved'):
        calls._executor_raw_result(pour_execution.grader, pour_execution.ledger,
                                  pour_execution.executor, token, returncode=0,
                                  snapshot_dir=tmp_path/'raw')
    assert token.raw is None


def test_nonidentity_pour_withholds_optional_custody_but_routes_ordinary(pour_execution, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from placemat.kicad import route
    from placemat.kicad.phase_select import Task
    hook = pour_execution
    monkeypatch.setattr(route, 'drop_pour_guards', lambda *args: None)
    def unsupported(path, net):
        Path(path).write_text(Path(path).read_text()+'\n')
    monkeypatch.setattr(route, 'pours_as_zones', unsupported)
    monkeypatch.setattr(route, 'router_command', lambda py, script, src, out, *a, **k:
                        [str(py), script, str(src), str(out)])
    invoked = []
    def run(command, **kwargs):
        invoked.append(command)
        Path(command[3]).write_bytes(Path(command[2]).read_bytes())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(route.subprocess, 'run', run)
    monkeypatch.setattr(route, 'pours_back', lambda *args: 0)
    monkeypatch.setattr(route, 'lock_copper', lambda *args: None)
    monkeypatch.setattr(route, 'guard_partial_pours', lambda *args: [])
    ctx = SimpleNamespace(work=tmp_path, cfg=SimpleNamespace(route_plane_share=.5),
                          rpy=Path('/usr/bin/python3'), script='route.py', iterations=None,
                          probe=None, quick=False, clearances_file=None, router_dir=tmp_path,
                          env={}, timeout=10, layers=['F.Cu'], execution=hook)
    task = Task('N', ('A', '1'), ('B', '1'), (('F.Cu', .2),))
    output = tmp_path/'p0_0.kicad_pcb'
    assert route.route_pour_net(ctx, hook.grader._original, output, 'N', .2, ['F.Cu'], 'p0_0',
                                _issued_scope=(0, 0, (task,))) == []
    assert len(invoked) == 1 and output.exists()
    assert not hook.active and not hook.ledger.issued
    assert json.loads((tmp_path/'final_authority_unavailable.json').read_text())['code'] == 'pour_transform_nonidentity_unproved'
    # Existing direct helper context without the optional field stays ordinary.
    del ctx.execution
    assert route.route_pour_net(ctx, hook.grader._original, tmp_path/'direct.kicad_pcb',
                                'N', .2, ['F.Cu'], 'direct') == []
    assert len(invoked) == 2


@pytest.mark.parametrize('selector', ['nets', 'rest'])
def test_actual_single_call_records_raw_before_rule_and_lock_restoration(context, tmp_path, monkeypatch, selector):
    from types import SimpleNamespace
    from placemat.kicad import phase_run
    from placemat.kicad.final_execution import FinalExecution
    from placemat.kicad.phase_select import Selection
    grader, facts, report = register(context)
    hook = object.__new__(FinalExecution)
    hook.work, hook.active, hook.grader = tmp_path, True, grader
    hook.executor, hook.refusals = object(), (ProofUnavailable,)
    hook.ledger = custody._executor_begin_calls(grader, hook.executor)
    ctx = phase_run.PhaseContext(
        Path('/usr/bin/python3'), 'route.py', str(tmp_path), tmp_path, ['F.Cu'],
        None, None, False, 60, {}, SimpleNamespace(route_router_args=()), facts['geometry'],
        {}, .2, None, set(), set(), None, execution=hook)
    phase = SimpleNamespace(name='signals', router_args=(), neckdown=False)
    selected = Selection('signals', selector, nets=('N',), rest=selector == 'rest', layers=('F.Cu',))
    monkeypatch.setattr(phase_run, 'router_command',
                        lambda py, script, src, out, excluded, layers, summary, **kw:
                        [str(py), script, str(src), str(out), str(summary)])
    def run(command, log, context):
        token = hook.ledger.issued[0]
        assert token.record['identity']['kind'] == 'single'
        assert token.record['nets'] == ['N']
        assert token.raw is None
        Path(command[3]).write_text('raw single result')
        Path(command[4]).write_text(json.dumps({'successful': 1, 'failed': 0}))
        return 0
    monkeypatch.setattr(phase_run, '_run', run)
    monkeypatch.setattr(phase_run, '_copy_project',
                        lambda src, out: Path(out).with_suffix('.kicad_pro').write_bytes(
                            Path(src).with_suffix('.kicad_pro').read_bytes()))
    def lock(path):
        token = hook.ledger.issued[0]
        assert token.raw is not None and token.completed is None
        Path(path).write_text('locked single result')
    monkeypatch.setattr(phase_run, 'lock_copper', lock)
    for name in ('phase_widths', 'narrow_join_widths', 'task_widths'):
        monkeypatch.setattr(phase_run, name, lambda *args: [])
    phase_run.route_calls(ctx, 0, phase, selected, grader._original)
    token = hook.ledger.issued[0]
    assert hook.active and token.completed is not None
    raw = next(path for path in token.raw['files'] if path.endswith('p0_0.kicad_pcb'))
    assert Path(raw).read_text() == 'raw single result'
    assert Path(token.record['output']).read_text() == 'locked single result'
