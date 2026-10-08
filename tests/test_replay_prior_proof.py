"""Actual private task receipts qualify prior work, never declaration-only intent."""
import pytest
from placemat.kicad import issued_calls, replay_inventory
from placemat.kicad.final_candidate import CandidatePlanner
from placemat.kicad.final_call import ProofUnavailable
from placemat.kicad.phase_run import Call
from placemat.kicad.phase_select import Task
from tests.test_issued_calls import issued, issue, finish
from tests.test_final_custody import context

@pytest.fixture
def prior(issued, tmp_path):
    grader, ledger, executor, options = issued
    raw = options['tasks'][0]
    task = Task(raw['net'],tuple(raw['from'][k] for k in ('ref','pad')),
                tuple(raw['to'][k] for k in ('ref','pad')),tuple(raw['widths'].items()))
    issued_calls._executor_plan(grader,ledger,executor,phase=0,
        calls=[Call('tasks',tasks=(task,)),Call('rest',('N',))],layers=['F.Cu'],input_board=options['input_board'])
    token=issue(issued)
    return issued,token,tmp_path

def bind(prior):
    args,token,tmp=prior
    return replay_inventory._executor_prior_work(*args[:3],phase=0,call=1)

def test_incomplete_actual_token_cannot_be_ignored(prior):
    with pytest.raises(ProofUnavailable,match='not_completed'):bind(prior)

def test_actual_task_wave_completion_proves_only_prior_scope(prior):
    args,token,tmp=prior;finish(args,token,tmp)
    proof,records=bind(prior)
    assert records[0]['identity']['kind']=='connections'
    assert records[0]['tasks']==args[3]['tasks']
    assert proof['issued_calls_sha256']
    with pytest.raises(ProofUnavailable,match='unsupported'):
        replay_inventory.supported_completed_work(*args[:3])

def test_wrong_executor_cannot_supply_prior_receipts(prior):
    args,token,tmp=prior;finish(args,token,tmp)
    with pytest.raises(ProofUnavailable,match='owner_mismatch'):
        replay_inventory._executor_prior_work(args[0],args[1],object(),phase=0,call=1)

@pytest.mark.parametrize('phase,call',[(0,0),(0,2),(True,1)])
def test_only_exact_last_single_call_can_remain_unissued(prior,phase,call):
    args,token,tmp=prior;finish(args,token,tmp)
    with pytest.raises(ProofUnavailable,match='pending_final'):
        replay_inventory._executor_prior_work(*args[:3],phase=phase,call=call)

def test_planner_retains_and_revalidates_actual_task_artifacts(prior):
    args,token,tmp=prior;finish(args,token,tmp)
    p=CandidatePlanner(authority=None,phases=[],obligations=[],width_receipt={},receipt_path=tmp/'receipt',complete=True)
    p._executor_bind_prior(*args[:3],phase=0,call=1)
    assert p._work[0].kind=='connections' and not p._unproved_work
    p._verify_prior()
    args[3]['output_board'].write_text('changed restored copper')
    with pytest.raises(ProofUnavailable,match='artifact_changed'):p._verify_prior()


def test_changed_original_plan_refuses(prior):
    args,token,tmp=prior;finish(args,token,tmp)
    args[1].call_plans[0][0]['calls'][0]['tasks'].clear()
    with pytest.raises(ProofUnavailable,match='plan_changed'):bind(prior)


def test_missing_planned_task_cannot_be_covered_by_one_wave(issued,tmp_path):
    grader,ledger,executor,options=issued
    raw=options['tasks'][0]
    first=Task(raw['net'],tuple(raw['from'][k] for k in ('ref','pad')),
               tuple(raw['to'][k] for k in ('ref','pad')),tuple(raw['widths'].items()))
    second=Task(first.net,first.start,('OTHER','1'),first.widths)
    issued_calls._executor_plan(grader,ledger,executor,phase=0,
        calls=[Call('tasks',tasks=(first,second)),Call('rest',('N',))],layers=['F.Cu'],input_board=options['input_board'])
    token=issue(issued);finish(issued,token,tmp_path)
    with pytest.raises(ProofUnavailable,match='wave_scope_incomplete'):
        replay_inventory._executor_prior_work(grader,ledger,executor,phase=0,call=1)


def test_already_issued_final_is_not_ignored(prior):
    args,token,tmp=prior;finish(args,token,tmp)
    options=dict(args[3],call=1,kind='single',tasks=[],task_file=None,
        output_board=tmp/'final.kicad_pcb',summary=tmp/'final.json',snapshot_dir=tmp/'final-before')
    issued_calls._executor_issue(*args[:3],**options)
    with pytest.raises(ProofUnavailable,match='not_completed'):bind(prior)


def test_actual_repeated_task_wave_keeps_original_retry_semantics(prior):
    args,token,tmp=prior;finish(args,token,tmp)
    options=dict(args[3],wave=1,output_board=tmp/'retry.kicad_pcb',
        summary=tmp/'retry.json',snapshot_dir=tmp/'retry-before')
    second=issued_calls._executor_issue(*args[:3],**options)
    retry=(args[0],args[1],args[2],options)
    retry_dir=tmp/'retry';retry_dir.mkdir();finish(retry,second,retry_dir)
    proof,records=bind(prior)
    assert len(records)==2 and records[0]['tasks']==records[1]['tasks']
    assert proof['issued_calls_sha256']


def test_extra_task_in_actual_receipt_refuses(prior):
    args,token,tmp=prior;finish(args,token,tmp)
    token.record['tasks'].append(dict(token.record['tasks'][0],net='UNOWNED'))
    with pytest.raises(ProofUnavailable,match='issued_call_token_mismatch'):bind(prior)
