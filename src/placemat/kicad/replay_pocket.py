"""The original pocket alternative in the same consumed second proposal slot.

Execution success is retained independently of optional policy proof. Neither
this fallback nor its receipt authorizes adoption or reopens another attempt.
"""
from copy import deepcopy
import json
from hashlib import sha256
from dataclasses import replace
from pathlib import Path

from placemat.kicad import issued_calls
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from . import replay_continuation as candidate_calls
from . import replay_ordinary_completion as ordinary_completed
from . import replay_restoration as restore_owned
from . import replay_ordinary_selection as ordinary_selection
from .replay_ordinary_trigger import permits_second_slot


def _accepted_seed(seed, nominal):
    """Correlate execution telemetry to the actual eligible original endpoints.

    This is not physical grading; the original fresh whole-board checks decide
    whether emitted copper can be selected.
    """
    # Match seed_nominal's first-seen logical-pad key, including its deliberate
    # deduplication across peer/epoch and physical-index representations.
    failures={}
    for failure in nominal['failures']:
        endpoint=failure['endpoint']
        key=(endpoint['net'],endpoint['ref'],endpoint['pad'])
        failures.setdefault(key,failure)
    seen=set();accepted=False;successes={}
    for attempt in seed['seed_attempts']:
        endpoint=attempt.get('endpoint')
        if not isinstance(endpoint,dict) or any(not isinstance(endpoint.get(field),str)
                for field in ('net','ref','pad')):
            raise ProofUnavailable('nominal_seed_identity_unproved')
        key=(endpoint['net'],endpoint['ref'],endpoint['pad'])
        if (key not in failures or key in seen
                or record_digest(endpoint)!=record_digest(failures[key]['endpoint'])):
            raise ProofUnavailable('nominal_seed_identity_unproved')
        seen.add(key)
        if not attempt['accepted_seed']:
            continue
        failure=failures[key];result=attempt.get('result')
        if (not isinstance(result,dict) or result.get('success') is not True
                or not isinstance(result.get('segments'),list)
                or not isinstance(attempt.get('fresh_graph_sha256'),str)
                or len(attempt['fresh_graph_sha256'])!=64):
            raise ProofUnavailable('nominal_seed_result_unproved')
        widths=nominal['proof']['nominal_policy']['by_net'][endpoint['net']]
        for segment in result['segments']:
            if (not isinstance(segment,dict) or segment.get('layer') not in widths
                    or type(segment.get('width')) not in (int,float)
                    or segment['width']!=widths[segment['layer']]):
                raise ProofUnavailable('nominal_seed_width_unproved')
        via=result.get('via')
        geometry=failure['nominal_geometry']
        if via is not None and (not isinstance(via,dict)
                or type(via.get('size')) not in (int,float)
                or type(via.get('drill')) not in (int,float)
                or via['size']!=geometry['via_size'] or via['drill']!=geometry['via_drill']):
            raise ProofUnavailable('nominal_seed_via_unproved')
        if not result['segments'] and via is None:
            raise ProofUnavailable('nominal_seed_copper_unproved')
        successes[endpoint['net']]=successes.get(endpoint['net'],0)+1
        if successes[endpoint['net']]>4:
            raise ProofUnavailable('nominal_seed_net_limit_unproved')
        accepted=True
    return accepted


def run(budget, owner, final_call, work, *, nominal=None):
    from . import replay_nominal
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
    nominal_sha = record_digest(nominal) if nominal is not None else None

    def validate():
        budget._check(budget.executor)
        owner.contexts_for(budget)
        if nominal is not None:
            if record_digest(nominal) != nominal_sha:
                raise ProofUnavailable('nominal_escape_eligibility_changed')
            issued_calls._unchanged(nominal['source_files'])
            issued_calls._unchanged(nominal['detached_files'])
            issued_calls._unchanged(nominal['runtime'])
            if file_hash(nominal['eligibility_reply']) != nominal['eligibility_sha256']:
                raise ProofUnavailable('nominal_escape_eligibility_changed')
        actual=issued_calls.completed_record(budget.grader,budget.ledger,budget.executor,final_call)
        if record_digest(actual)!=original_sha:
            raise ProofUnavailable('replay_original_call_changed')

    def operation(deadline):
        nonlocal completed_output
        validate()
        work.mkdir()
        given=work/'input.kicad_pcb';output=work/'output.kicad_pcb';summary=work/'summary.json'
        env=dict(replay_nominal.clear_transport(ctx.env),KRT_INTERNAL_ROUTE_CANDIDATE='1',
                 KRT_ROUTE_DEADLINE_UTC=str(deadline),
                 KRT_INTERNAL_ORDINARY_GRADE_REQUEST=str(work/'ordinary-grade-request.json'))
        kind='pocket' if nominal is None else 'escape'
        if nominal is None:
            env['KRT_INTERNAL_POCKET_WALLS']='1'
        else:
            if (record_digest(nominal['proof'])!=nominal['identity']['proof_sha256']
                    or file_hash(nominal['eligibility_reply'])!=nominal['eligibility_sha256']):
                raise ProofUnavailable('nominal_escape_eligibility_changed')
            seed_context=work/'seed-context.json';seed_evidence=work/'seed-evidence.json'
            seed_context.write_text(json.dumps(dict(proof=nominal['proof'],
                identity=nominal['identity'],candidate='escape',evidence_file=str(seed_evidence),
                failures=nominal['failures']),sort_keys=True,allow_nan=False)+'\n')
            seed_context_sha=file_hash(seed_context)
            env.update(KRT_INTERNAL_FINAL_CALL_CONTEXT=str(seed_context),
                KRT_INTERNAL_FINAL_CALL_KIND='escape',
                KRT_INTERNAL_FINAL_CALL_PROOF=nominal['identity']['proof_sha256'],
                KRT_INTERNAL_FINAL_CALL_ID=nominal['identity']['call_id'])
            env.pop('KRT_INTERNAL_POCKET_WALLS',None)
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
        if nominal is not None:
            if file_hash(seed_context)!=seed_context_sha:
                raise ProofUnavailable('nominal_seed_context_changed')
            try:
                raw_seed=seed_evidence.read_bytes()
                seed=json.loads(raw_seed)
                record_digest(seed)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, OverflowError) as error:
                raise ProofUnavailable('nominal_seed_receipt_unproved') from error
            seed_sha=sha256(raw_seed).hexdigest()
            if (not isinstance(seed,dict) or set(seed)!={'schema','seed_attempts'}
                    or type(seed['schema']) is not int or seed['schema']!=1
                    or not isinstance(seed['seed_attempts'],list)
                    or any(not isinstance(attempt,dict) or type(attempt.get('accepted_seed')) is not bool
                           for attempt in seed['seed_attempts'])):
                raise ProofUnavailable('nominal_seed_receipt_unproved')
            eligibility['nominal_seed']=seed
            eligibility['candidate_kind']='escape'
        raw=issued_calls._files(output);raw[str(summary)]=file_hash(summary)
        for path,expected in actual['files'].items():
            if raw.get(path)!=expected:
                raise ProofUnavailable('replay_owned_raw_changed')
        if nominal is not None:
            raw[str(seed_context)]=seed_context_sha;raw[str(seed_evidence)]=seed_sha
        files.update(issued_calls._snapshot(raw,work/'raw'))
        files.update(restore_owned.run(budget,original,pocket_ctx,'restore',current,given,output,lifecycle))
        validate()
        files.update({path:value for path,value in issued_calls._files(output).items() if value is not None})
        completed_output=output
        try:
            accepted=(nominal is None or eligibility['policy_proved'] and _accepted_seed(eligibility['nominal_seed'],nominal))
            if not accepted:
                eligibility['selection']={'selected':'legacy','reason':'nominal_seed_unavailable'}
            else:
                if nominal is None:
                    eligibility['selection']=ordinary_selection.choose(budget,owner,final_call,output,files,work/'ordinary-selection')
                else:
                    eligibility['selection']=ordinary_selection.choose(budget,owner,final_call,output,files,
                        work/'ordinary-selection',candidate_kind=kind)
        except ProofUnavailable as error:
            eligibility['selection']={'selected':'legacy','reason':'original_comparison_unavailable','refusal':error.record()}
        validate()
        return {'returncode':0,'files':files,'proposals':1}

    receipt=budget.run_replay(budget.executor,operation)
    return completed_output,receipt,deepcopy(eligibility)
