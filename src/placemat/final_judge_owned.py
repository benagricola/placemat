"""A retained Run's full final judgement, within its original deadline."""
from copy import deepcopy
import json
import hashlib
import math
import os
from pathlib import Path
import sys

from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad.final_owned_worker import _execute, _implementation, _remaining, _json
from placemat.final_check_judgement import decode


def judge_owned(factory, pcb, measures, destination):
    from placemat.final_authority import RetainedAuthorityFactory
    if type(factory) is not RetainedAuthorityFactory:
        raise ProofUnavailable('final_judge_retained_context_required')
    factory._verify()
    deadline=factory._deadline_utc
    _remaining(deadline)
    env=dict(os.environ)
    inherited=env.get('KRT_ROUTE_DEADLINE_UTC')
    if inherited is not None:
        try:
            inherited=float(inherited)
        except (ValueError,TypeError,OverflowError) as error:
            raise ProofUnavailable('final_judge_deadline_context_invalid') from error
        if not math.isfinite(inherited) or inherited < deadline:
            raise ProofUnavailable('final_judge_deadline_context_mismatch')
    env['KRT_ROUTE_DEADLINE_UTC']=str(deadline)
    pcb=Path(pcb).resolve()
    inputs={str(pcb):file_hash(pcb)}
    for suffix in ('.kicad_pro','.kicad_dru'):
        path=pcb.with_suffix(suffix)
        inputs[str(path)]=file_hash(path) if path.is_file() else None
    implementation=_implementation()
    original_context_sha=record_digest(factory._critical)
    critical=deepcopy(factory._critical)
    try:
        critical['measures']=json.loads(json.dumps(measures,allow_nan=False))
    except (TypeError,ValueError) as error:
        raise ProofUnavailable('final_judge_measures_unsupported') from error
    request={'schema':1,'operation':'critical-only','deadline_utc':deadline,
             'critical':critical,'pcb':str(pcb),'inputs':inputs}
    request_sha=record_digest(request)
    destination=Path(destination).absolute()
    destination.mkdir(parents=True,exist_ok=False)
    source=destination/'request.json';reply=destination/'response.json'
    source.write_text(json.dumps(request,sort_keys=True,allow_nan=False)+'\n')
    source_sha=file_hash(source)
    try:
        rc,out,err=_execute([sys.executable,'-m','placemat.final_check_worker',str(source),str(reply)],
                           deadline,env)
    except BaseException as error:
        (destination/'stdout.log').write_text(getattr(error,'output','') or '')
        (destination/'stderr.log').write_text(getattr(error,'stderr','') or '')
        raise
    (destination/'stdout.log').write_text(out)
    (destination/'stderr.log').write_text(err)
    if rc!=0 or not reply.is_file():
        raise ProofUnavailable('final_judge_worker_failed',returncode=rc)
    reply_bytes=reply.read_bytes()
    reply_sha=hashlib.sha256(reply_bytes).hexdigest()
    result=_json(reply_bytes)
    expected={'schema','operation','request_sha256','implementation_start','implementation_end','judgement','evidence'}
    if (type(result) is not dict or set(result)!=expected
            or type(result['schema']) is not int or result['schema']!=1
            or result['operation']!='critical-only' or result['request_sha256']!=request_sha
            or result['implementation_start']!=implementation or result['implementation_end']!=implementation):
        raise ProofUnavailable('final_judge_worker_reply_invalid')
    judgement=decode(result['judgement'])
    from placemat.final_board import Judgement
    if type(judgement) is not Judgement or record_digest(judgement.evidence())!=record_digest(result['evidence']):
        raise ProofUnavailable('final_judge_worker_evidence_invalid')
    for key,value in critical['measures'].items():
        if key not in ('findings','critical_checks','critical_unknown'):
            if key not in judgement.measures or record_digest(judgement.measures[key])!=record_digest(value):
                raise ProofUnavailable('final_judge_quality_measures_changed',key=key)
    factory._verify()
    _remaining(deadline)
    if factory._deadline_utc != deadline:
        raise ProofUnavailable('final_judge_deadline_context_mismatch')
    if file_hash(reply)!=reply_sha:
        raise ProofUnavailable('final_judge_reply_changed')
    if file_hash(source)!=source_sha or record_digest(factory._critical)!=original_context_sha:
        raise ProofUnavailable('final_judge_original_context_changed')
    for path,expected_hash in inputs.items():
        actual=file_hash(path) if Path(path).is_file() else None
        if actual!=expected_hash:
            raise ProofUnavailable('final_judge_candidate_changed')
    if _implementation()!=implementation:
        raise ProofUnavailable('final_judge_implementation_changed')
    (destination/'execution.json').write_text(json.dumps({'deadline_utc':deadline,
        'request_sha256':request_sha,'response_sha256':reply_sha,'inputs':inputs,
        'implementation':implementation,'operation':'critical-only','comparison_authority':False},
        sort_keys=True,allow_nan=False)+'\n')
    _remaining(deadline)
    if file_hash(reply)!=reply_sha:
        raise ProofUnavailable('final_judge_reply_changed')
    return judgement
