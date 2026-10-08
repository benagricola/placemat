"""Read original nominal telemetry under the existing owner/deadline, no route slot."""
import json
from pathlib import Path
from placemat.kicad import issued_calls, final_custody
from placemat.kicad.final_call import ProofUnavailable,file_hash,record_digest
from placemat.kicad.final_owned_worker import _execute
from . import replay_backend as backend


def clear_transport(env):
    result=dict(env)
    for suffix in ('CONTEXT','KIND','PROOF','ID'):
        result.pop('KRT_INTERNAL_FINAL_CALL_'+suffix,None)
    return result


def _failed_pairs(grader):
    final_custody.require_completed(grader)
    asks=json.loads(grader._obligations)
    template=grader._template
    if record_digest(template.asked)!=record_digest(asks) or len(template.final_judged)!=len(asks):
        raise ProofUnavailable('nominal_original_judgments_changed')
    if not asks or len(template.final_judged[-1])!=len(asks[-1]):
        raise ProofUnavailable('nominal_original_judgments_unproved')
    pairs=set()
    for ask,result in zip(asks[-1],template.final_judged[-1]):
        if type(result.get('joined')) is not bool:
            raise ProofUnavailable('nominal_original_judgments_unproved')
        if not result['joined']:
            for first,second in (('from','to'),('to','from')):
                a,b=ask[first],ask[second]
                pairs.add((ask['net'],a['ref'],a['pad'],b['ref'],b['pad']))
    return pairs


def eligible(budget,owner,final_call,work):
    owner.contexts_for(budget)
    if final_call is not owner.final_call:
        raise ProofUnavailable('nominal_original_call_mismatch')
    if not owner.backend_eligibility['policy_proved'] or getattr(owner,'nominal_refusal',None):
        return None
    observation=getattr(owner,'nominal_observation',None)
    if observation is None or 'detached_files' not in observation:
        return None
    if record_digest(observation)!=owner.nominal_observation_sha:
        raise ProofUnavailable('nominal_observer_changed')
    original=issued_calls.completed_record(budget.grader,budget.ledger,budget.executor,final_call)
    ctx=owner.contexts_for(budget)[final_call]
    backend._original_effective(original,ctx,final=True)
    runtime,_,_=backend._runtime(ctx,original['command'])
    issued_calls._unchanged(observation['runtime'])
    issued_calls._unchanged(observation['detached_files'])
    issued_calls._unchanged(observation['source_files'])
    grade=(Path(ctx.router_dir)/ctx.script).resolve().with_name('route_candidates.py')
    capability=owner.backend_capability
    if record_digest(capability)!=owner.backend_capability_sha:
        raise ProofUnavailable('nominal_capability_changed')
    policies=capability['policies']
    if (str(grade)!=policies.get('grade_path')
            or runtime.get(str(grade))!=policies.get('grade_sha256')):
        raise ProofUnavailable('nominal_grade_implementation_unproved')
    grade_sha=file_hash(grade)
    if grade_sha!=policies['grade_sha256']:
        raise ProofUnavailable('nominal_grade_implementation_changed')
    work=Path(work).resolve()
    if work.exists():raise ProofUnavailable('nominal_fresh_work_required')
    work.mkdir()
    paths={'board':original['input'],'context':observation['context'],
           'evidence':observation['evidence']}
    # The detached log is uniquely bound by the positive completion marker's raw source.
    originals={str(Path(path).resolve()):expected for path,expected in
               issued_calls._files(original['input']).items()}
    context_path=Path(observation['context']);evidence_path=Path(observation['evidence'])
    log=observation.get('log')
    if not isinstance(log,str):raise ProofUnavailable('nominal_log_binding_unavailable')
    paths.update(log=log,summary=original['summary'])
    for key in ('context','evidence','log','summary'):
        path=Path(paths[key]).resolve()
        originals[str(path)]=(issued_calls.raw_summary_hash(original) if key=='summary'
                              else observation['source_files'][str(path)])
    request={'schema':1,'deadline_utc':budget.deadline,**paths,'files':originals}
    request_path=work/'request.json';reply=work/'reply.json'
    request_path.write_text(json.dumps(request,sort_keys=True,allow_nan=False)+'\n')
    request_sha=file_hash(request_path)
    def unchanged():
        budget._check(budget.executor);owner.contexts_for(budget)
        if record_digest(owner.backend_capability)!=owner.backend_capability_sha:
            raise ProofUnavailable('nominal_capability_changed')
        if file_hash(grade)!=grade_sha:
            raise ProofUnavailable('nominal_grade_implementation_changed')
        if record_digest(observation)!=owner.nominal_observation_sha:
            raise ProofUnavailable('nominal_observer_changed')
        issued_calls._unchanged(runtime);issued_calls._unchanged(originals)
        issued_calls._unchanged(observation['detached_files'])
        issued_calls._unchanged(observation['source_files'])
        if file_hash(request_path)!=request_sha:raise ProofUnavailable('nominal_request_changed')
    unchanged()
    command=[str(ctx.rpy),str(grade),
             '--nominal-evidence',str(request_path),str(reply)]
    code,stdout,stderr=_execute(command,budget.deadline,dict(ctx.env,
        KRT_ROUTE_DEADLINE_UTC=str(budget.deadline)),cwd=ctx.router_dir)
    (work/'stdout.log').write_text(stdout);(work/'stderr.log').write_text(stderr)
    unchanged()
    if code!=0 or not reply.is_file():return None
    raw=reply.read_bytes()
    try:value=json.loads(raw)
    except (json.JSONDecodeError,UnicodeDecodeError):return None
    try:record_digest(value)
    except (TypeError,ValueError,OverflowError):return None
    fields={'schema','proof_sha256','call_id','input_files','files','failures','refused','comparison_authority'}
    if (not isinstance(value,dict) or set(value)!=fields or type(value['schema']) is not int
            or value['schema']!=1 or value['comparison_authority'] is not False
            or record_digest(value['files'])!=record_digest(originals)
            or value['proof_sha256']!=observation['identity']['proof_sha256']
            or value['call_id']!=observation['identity']['call_id']
            or record_digest(value['input_files'])!=record_digest(observation['proof']['input_files'])
            or not isinstance(value['failures'],list) or not value['failures']
            or not isinstance(value['refused'],list)):
        return None
    from hashlib import sha256
    if file_hash(reply)!=sha256(raw).hexdigest():raise ProofUnavailable('nominal_reply_changed')
    unchanged()
    failed=_failed_pairs(budget.grader)
    failures=[failure for failure in value['failures'] if
        (failure['endpoint']['net'],failure['endpoint']['ref'],failure['endpoint']['pad'],
         failure['peer']['ref'],failure['peer']['pad']) in failed]
    if not failures:return None
    return dict(observation,failures=failures,eligibility_reply=str(reply),
                eligibility_sha256=sha256(raw).hexdigest())
