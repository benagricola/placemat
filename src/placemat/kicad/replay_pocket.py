"""The original pocket alternative in the same consumed second proposal slot.

Execution success is retained independently of optional policy proof. Neither
this fallback nor its receipt authorizes adoption or reopens another attempt.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from placemat.kicad import issued_calls
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from . import replay_continuation as candidate_calls
from . import replay_ordinary_completion as ordinary_completed
from . import replay_restoration as restore_owned
from . import replay_ordinary_selection as ordinary_selection
from .replay_ordinary_trigger import permits_second_slot


def run(budget, owner, final_call, work):
    contexts = owner.contexts_for(budget)
    if final_call is not owner.final_call or final_call not in contexts:
        raise ProofUnavailable('replay_final_call_unproved')
    original = issued_calls.completed_record(budget.grader,budget.ledger,budget.executor,final_call)
    if original['identity']['kind'] != 'single':
        raise ProofUnavailable('replay_pocket_single_call_required')
    original_sha = record_digest(original)
    ctx = contexts[final_call]
    runtime,_,_=ordinary_completed.backend._runtime(ctx,original['command'])
    helper=(Path(ctx.router_dir)/ctx.script).resolve().with_name('route_candidates.py')
    if not permits_second_slot(helper,original['raw']['summary'],owner.backend_capability['sources'][str(helper)]):
        return None,None,{'policy_proved':False,'refusal':None,'selection':{'selected':'legacy','reason':'original_second_slot_not_applicable'}}
    work = Path(work).resolve()
    if work.exists():
        raise ProofUnavailable('replay_fresh_pocket_work_required')
    eligibility = {'policy_proved':False, 'refusal':None}
    completed_output = None

    def validate():
        budget._check(budget.executor)
        owner.contexts_for(budget)
        actual=issued_calls.completed_record(budget.grader,budget.ledger,budget.executor,final_call)
        if record_digest(actual)!=original_sha:
            raise ProofUnavailable('replay_original_call_changed')

    def operation(deadline):
        nonlocal completed_output
        validate()
        work.mkdir()
        given=work/'input.kicad_pcb';output=work/'output.kicad_pcb';summary=work/'summary.json'
        env=dict(ctx.env,KRT_INTERNAL_ROUTE_CANDIDATE='1',KRT_INTERNAL_POCKET_WALLS='1',
                 KRT_ROUTE_DEADLINE_UTC=str(deadline),
                 KRT_INTERNAL_ORDINARY_GRADE_REQUEST=str(work/'ordinary-grade-request.json'))
        pocket_ctx=replace(ctx,env=env,execution=None)
        lifecycle=work/'lifecycle';lifecycle.mkdir()
        current=Path(original['input'])
        # The final single call uses the exact original issued terrain/rules.
        files=restore_owned.run(budget,original,pocket_ctx,'prepare',current,given,output,lifecycle)
        record=candidate_calls._candidate_record(original,pocket_ctx,given,output,summary)
        actual=None
        def capture(value):
            nonlocal actual
            if actual is not None:
                raise ProofUnavailable('replay_owned_completion_repeated')
            actual=deepcopy(value)
        try:
            ordinary_completed.backend._run_record(record,deadline,pocket_ctx,work/'router.log',validate,
                                                   actual_completed=capture)
        except ProofUnavailable as error:
            if error.code not in ordinary_completed._METADATA_REFUSALS or actual is None:
                raise
            eligibility['refusal']=error.record()
        else:
            eligibility['policy_proved']=True
        if actual is None or actual['returncode']!=0:
            raise ProofUnavailable('replay_owned_ordinary_completion_unavailable')
        raw=issued_calls._files(output);raw[str(summary)]=file_hash(summary)
        for path,expected in actual['files'].items():
            if raw.get(path)!=expected:
                raise ProofUnavailable('replay_owned_raw_changed')
        files.update(issued_calls._snapshot(raw,work/'raw'))
        files.update(restore_owned.run(budget,original,pocket_ctx,'restore',current,given,output,lifecycle))
        validate()
        files.update({path:value for path,value in issued_calls._files(output).items() if value is not None})
        completed_output=output
        try:
            eligibility['selection']=ordinary_selection.choose(budget,owner,final_call,output,files,work/'ordinary-selection')
        except ProofUnavailable as error:
            eligibility['selection']={'selected':'legacy','reason':'original_comparison_unavailable','refusal':error.record()}
        validate()
        return {'returncode':0,'files':files,'proposals':1}

    receipt=budget.run_replay(budget.executor,operation)
    return completed_output,receipt,deepcopy(eligibility)
