"""Bounded read of the existing capability protocol; no routing attempt."""
import json
import math
from pathlib import Path
import subprocess
import time
from placemat.kicad.final_call import ProofUnavailable,file_hash,record_digest
from placemat.kicad.final_owned_worker import _execute


def query(ctx,deadline,work):
    if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<=time.time():
        raise ProofUnavailable('replay_capability_deadline_unavailable')
    root=Path(ctx.router_dir).resolve()
    script=root/'krt_capabilities.py'
    route=(root/ctx.script).resolve()
    helper=route.with_name('route_execution_receipt.py')
    grade=route.with_name('route_candidates.py')
    paths=[Path(ctx.rpy).resolve(),script,route,helper,grade]
    if any(not path.is_file() for path in paths):
        raise ProofUnavailable('replay_execution_capability_unavailable')
    try:
        sources={str(path):file_hash(path) for path in paths}
    except OSError as error:
        raise ProofUnavailable('replay_execution_capability_changed') from error
    work=Path(work).resolve();work.mkdir()
    try:
        rc,out,err=_execute([str(ctx.rpy),str(script)],min(deadline,time.time()+60),dict(ctx.env),cwd=root)
    except BaseException as error:
        def text(value):
            return value.decode('utf-8','replace') if isinstance(value,bytes) else str(value or '')
        (work/'stdout.json').write_text(text(getattr(error,'output','')))
        (work/'stderr.log').write_text(text(getattr(error,'stderr','')))
        if isinstance(error,(OSError,subprocess.TimeoutExpired)):
            raise ProofUnavailable('replay_execution_capability_unavailable') from error
        raise
    (work/'stdout.json').write_text(out);(work/'stderr.log').write_text(err)
    try:
        after={str(path):file_hash(path) for path in paths}
    except OSError as error:
        raise ProofUnavailable('replay_execution_capability_changed') from error
    if rc!=0 or time.time()>=deadline or sources!=after:
        raise ProofUnavailable('replay_execution_capability_changed')
    try:
        caps=json.loads(out)
        policies=caps['execution_policies']['route.py']
        fields={'schema','legacy_only','pocket','policy_receipt_schema','parent_scope_schema',
                'route_path','helper_path','route_sha256','helper_sha256',
                'ordinary_grade_request_schema','grade_path','grade_sha256'}
        valid=(type(caps['schema']) is int and caps['schema']==1
               and Path(caps['root']).resolve()==root
               and isinstance(policies,dict) and set(policies)==fields
               and all(type(policies[key]) is int and policies[key]==expected
                       for key,expected in {'schema':1,'policy_receipt_schema':2,
                           'parent_scope_schema':2,'ordinary_grade_request_schema':2}.items())
               and policies['legacy_only'] is True and policies['pocket'] is True
               and policies['route_path']==str(route) and policies['helper_path']==str(helper)
               and policies['route_sha256']==sources[str(route)]
               and policies['helper_sha256']==sources[str(helper)]
               and policies['grade_path']==str(grade) and policies['grade_sha256']==sources[str(grade)])
    except (ValueError,TypeError,KeyError) as error:
        raise ProofUnavailable('replay_execution_capability_unavailable') from error
    if not valid:
        raise ProofUnavailable('replay_execution_capability_unavailable')
    receipt={'schema':1,'sources':sources,'policies':policies,'deadline_utc':deadline,
             'command':[str(ctx.rpy),str(script)],'stdout_sha256':file_hash(work/'stdout.json')}
    (work/'capability.json').write_text(json.dumps(receipt,allow_nan=False,indent=2)+'\n')
    return json.loads(json.dumps(receipt,allow_nan=False))
