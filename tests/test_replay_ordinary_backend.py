"""Real backend/completion lifecycle; controlled producer, no native routing."""
from pathlib import Path
import json
import pytest
from tests.test_replay_backend import launch, issued, context
from placemat.kicad import replay_backend as backend, replay_ordinary_completion as ordinary, issued_calls
from placemat.kicad.final_call import ProofUnavailable


def lifecycle(launch, tmp_path, mutate=False):
    grader, ledger, executor, token, ctx, log = launch
    def complete(run):
        rc = run(token.record['command'], log, ctx)
        output = Path(token.record['output'])
        if mutate:
            output.write_bytes(output.read_bytes() + b' changed raw')
        issued_calls._executor_raw_result(grader, ledger, executor, token,
                                         returncode=rc, snapshot_dir=tmp_path/'raw')
        for suffix in ('.kicad_pro', '.kicad_dru'):
            source = Path(token.record['source']).with_suffix(suffix)
            if source.exists():
                output.with_suffix(suffix).write_bytes(source.read_bytes())
        output.write_bytes(output.read_bytes() + b' controlled locked')
        issued_calls._executor_restored_result(grader, ledger, executor, token)
    return complete


@pytest.mark.parametrize('mode', [None, 'missing_policy', 'malformed_policy'])
def test_real_backend_ordinary_completion_restores_once(launch, tmp_path, monkeypatch, mode):
    if mode:
        launch[4].env['CONTROL_MODE'] = mode
    execute = backend._execute
    calls = []
    def actual(*args, **kwargs):
        calls.append(args[0])
        result = execute(*args, **kwargs)
        if mode == 'malformed_policy':
            path = Path(launch[3].record['summary'])
            summary = json.loads(path.read_bytes());summary['execution_policy'] = True
            path.write_text(json.dumps(summary))
        return result
    monkeypatch.setattr(backend, '_execute', actual)
    receipt, eligibility = ordinary.run_completed(launch[4].budget, launch[3], launch[4], launch[5], lifecycle(launch,tmp_path))
    assert eligibility['policy_proved'] is (mode is None)
    assert (eligibility['refusal'] is None) is (mode is None)
    assert len(calls) == 1 and launch[4].budget.states == ['completed', 'unused']
    assert launch[3].raw is not None and launch[3].completed is not None
    with pytest.raises(ProofUnavailable, match='already_issued'):
        ordinary.run_completed(launch[4].budget, launch[3], launch[4], launch[5], lambda run:pytest.fail('reopened'))
    assert len(calls) == 1


@pytest.mark.parametrize('mode', ['missing_policy', 'malformed_policy'])
@pytest.mark.parametrize('marker', ['aborted', 'cancelled', 'timed_out', 'deferred', 'numeric'])
def test_mandatory_markers_refuse_before_optional_capture(launch,tmp_path,monkeypatch,mode,marker):
    execute = backend._execute
    def actual(*args, **kwargs):
        result = execute(*args, **kwargs)
        path=Path(launch[3].record['summary']);summary=json.loads(path.read_bytes())
        if mode=='missing_policy':summary.pop('execution_policy')
        else:summary['execution_policy']=True
        if marker=='deferred':summary['connections'][0]['status']='deferred'
        elif marker=='numeric':summary['aborted']=0
        else:summary[marker]=True
        path.write_text(json.dumps(summary));return result
    monkeypatch.setattr(backend,'_execute',actual)
    with pytest.raises(ProofUnavailable,match='backend_deferred'):
        ordinary.run_completed(launch[4].budget,launch[3],launch[4],launch[5],lifecycle(launch,tmp_path))
    assert launch[4].budget.states==['failed','unused'] and launch[3].raw is None


def test_actual_raw_mutation_cannot_seal_ordinary_slot(launch,tmp_path):
    launch[4].env['CONTROL_MODE']='missing_policy'
    with pytest.raises(ProofUnavailable,match='raw_changed'):
        ordinary.run_completed(launch[4].budget,launch[3],launch[4],launch[5],lifecycle(launch,tmp_path,True))
    assert launch[4].budget.states==['failed','unused']


def test_capture_exact_execution_facts_once(launch):
    values=[];grader,ledger,executor,token,ctx,log=launch
    result=backend._run_record(token.record,ledger.owner.deadline_utc,ctx,log,
        lambda:issued_calls._token(grader,ledger,executor,token),actual_completed=values.append)
    assert len(values)==1 and values[0]['files']==result['files']
    assert values[0]['command']==token.record['command']
    assert values[0]['deadline_utc']==ledger.owner.deadline_utc
    assert values[0]['input_files']==token.record['actual_input_files']


@pytest.mark.parametrize('failure', ['nonzero', 'missing_output', 'expired', 'cancelled'])
def test_execution_failure_never_captures_or_reopens(launch,tmp_path,monkeypatch,failure):
    execute=backend._execute
    def actual(*args, **kwargs):
        if failure=='cancelled':raise KeyboardInterrupt()
        result=execute(*args, **kwargs)
        if failure=='nonzero':return 1,result[1],result[2]
        if failure=='missing_output':Path(launch[3].record['output']).unlink()
        if failure=='expired':monkeypatch.setattr(backend.time,'time',lambda:launch[4].budget.deadline+1)
        return result
    monkeypatch.setattr(backend,'_execute',actual)
    expected=KeyboardInterrupt if failure=='cancelled' else ProofUnavailable
    with pytest.raises(expected):
        ordinary.run_completed(launch[4].budget,launch[3],launch[4],launch[5],lifecycle(launch,tmp_path))
    assert launch[3].raw is None
    assert launch[4].budget.states==['cancelled' if failure=='cancelled' else 'failed','unused']


def test_callback_mutation_refuses_before_policy(launch):
    grader,ledger,executor,token,ctx,log=launch
    def capture(value):Path(token.record['output']).write_text('mutated')
    with pytest.raises(ProofUnavailable):
        backend._run_record(token.record,ledger.owner.deadline_utc,ctx,log,
            lambda:issued_calls._token(grader,ledger,executor,token),actual_completed=capture)



def test_owned_timeout_preserves_logs_without_completion(launch,tmp_path,monkeypatch):
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1, output='partial stdout', stderr='partial stderr')
    monkeypatch.setattr(backend,'_execute',timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        ordinary.run_completed(launch[4].budget,launch[3],launch[4],launch[5],lifecycle(launch,tmp_path))
    assert launch[5].read_text()=='partial stdoutpartial stderr'
    assert launch[3].raw is None and launch[4].budget.states==['failed','unused']
