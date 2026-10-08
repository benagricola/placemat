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
