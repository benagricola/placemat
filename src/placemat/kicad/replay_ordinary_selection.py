"""Reuse the original ordinary pocket comparator, without FullStanding claims.

All helpers and independent --grade workers run from the pinned backend source
under the same actual two-slot owner and existing absolute deadline.
"""
import ast
from copy import deepcopy
import json
import hashlib
import math
from pathlib import Path

from placemat.kicad import issued_calls
from placemat.kicad.final_call import ProofUnavailable,file_hash,record_digest
from placemat.kicad.final_owned_worker import _execute
from . import replay_backend as backend


def _snapshot(files,name,parent=None):
    matches=[Path(path) for path in files if Path(path).name.split('-',1)[-1]==name
             and (parent is None or Path(path).parent==parent)]
    if len(matches)!=1:
        raise ProofUnavailable('replay_ordinary_raw_snapshot_unproved')
    path=matches[0]
    if file_hash(path)!=files[str(path)]:
        raise ProofUnavailable('replay_ordinary_raw_snapshot_changed')
    return path


def _grade(value):
    try:
        record_digest(value)
    except (TypeError,ValueError,OverflowError):
        return None
    if not isinstance(value,dict) or type(value.get('known')) is not bool:
        return None
    if not value['known']:
        return value
    if (set(value)!={'known','unproved','drc','undersized','widths_unknown','open','quality'}
            or not isinstance(value['unproved'],list)
            or any(not isinstance(item,str) for item in value['unproved'])
            or type(value['widths_unknown']) is not bool):
        return None
    if any(type(value[key]) is not int or value[key]<0 for key in ('drc','undersized','open')):
        return None
    if value['unproved']:
        return None
    def finite_quality(item):
        if type(item) not in (int,float) or item<0:return False
        try:return math.isfinite(item)
        except OverflowError:return False
    if (not isinstance(value['quality'],list) or len(value['quality'])!=3
            or any(not finite_quality(item) for item in value['quality'])):
        return None
    return value


def choose(budget,owner,final_call,pocket_output,pocket_files,work, *, candidate_kind='pocket'):
    """Grade/select inside the already consumed ordinary pocket slot.

    This cannot launch another routing search or publish an authoritative
    candidate. The caller must still finalize/recheck the chosen copper.
    """
    budget._check(budget.executor)
    if budget.states!=['completed','issued'] or owner.final_call is not final_call:
        raise ProofUnavailable('replay_completed_pocket_required')
    ctx=owner.contexts_for(budget)[final_call]
    original=issued_calls.completed_record(budget.grader,budget.ledger,budget.executor,final_call)
    original_sha=record_digest(original)
    template=backend.original_grade_request(original,ctx)
    request_sha=record_digest(template)
    runtime,_,_=backend._runtime(ctx,original['command'])
    helper=(Path(ctx.router_dir)/ctx.script).resolve().with_name('route_candidates.py')
    work=Path(work).resolve();work.mkdir()
    pocket_output=Path(pocket_output).resolve()
    legacy_board=_snapshot(original['raw']['files'],Path(original['output']).name)
    pocket_board=_snapshot(pocket_files,pocket_output.name,pocket_output.parent/'raw')
    pocket_summary_path=_snapshot(pocket_files,'summary.json',pocket_output.parent/'raw')
    try:
        pocket_summary=json.loads(pocket_summary_path.read_bytes())
    except (OSError,ValueError,UnicodeError) as error:
        raise ProofUnavailable('replay_ordinary_summary_unavailable') from error
    if not isinstance(pocket_summary,dict):
        raise ProofUnavailable('replay_ordinary_summary_unavailable')
    summaries=[original['raw']['summary'],pocket_summary]

    def unchanged():
        budget._check(budget.executor);owner.contexts_for(budget)
        if record_digest(issued_calls.completed_record(budget.grader,budget.ledger,budget.executor,final_call))!=original_sha:
            raise ProofUnavailable('replay_original_call_changed')
        if record_digest(backend.original_grade_request(original,ctx))!=request_sha:
            raise ProofUnavailable('replay_ordinary_grade_request_changed')
        try:
            current_runtime=backend._runtime(ctx,original['command'])[0]
        except OSError as error:
            raise ProofUnavailable('replay_ordinary_grader_changed') from error
        if current_runtime!=runtime:
            raise ProofUnavailable('replay_ordinary_grader_changed')
        for files in (original['raw']['files'],pocket_files):
            for path,expected in files.items():
                if file_hash(path)!=expected:
                    raise ProofUnavailable('replay_ordinary_raw_snapshot_changed')

    def worker(mode,request,name):
        unchanged()
        source=work/(name+'-request.json');output=work/(name+'.json')
        source.write_text(json.dumps(request,sort_keys=True,allow_nan=False)+'\n')
        rc,out,err=_execute([str(ctx.rpy),str(helper),mode,str(source),str(output)],
                            budget.deadline,dict(ctx.env),cwd=ctx.router_dir)
        (work/(name+'.stdout')).write_text(out);(work/(name+'.stderr')).write_text(err)
        unchanged()
        if rc!=0:return None
        try:return json.loads(output.read_bytes())
        except (OSError,ValueError,UnicodeError):return None

    scope=worker('--ordinary-scope',{'requested_scope':template['scope'],
                 'candidates':[{'summary':summary} for summary in summaries],
                 'connections':template['connections']},'scope')
    if (not isinstance(scope,dict) or set(scope)!={'scope','identity'}
            or not isinstance(scope['scope'],list)
            or any(not isinstance(net,str) or not net for net in scope['scope'])):
        return {'selected':'legacy','reason':'original_scope_unavailable','grades':{}}
    identity=scope['identity']
    if (not isinstance(identity,dict) or set(identity)!={'requested_nets','graded_nets','tasks','sha256'}
            or identity['requested_nets']!=sorted(set(template['scope']))
            or identity['graded_nets']!=scope['scope']
            or scope['scope']!=sorted(set(scope['scope']))):
        return {'selected':'legacy','reason':'original_scope_unavailable','grades':{}}
    expected=dict(identity);claimed=expected.pop('sha256')
    if type(claimed) is not str or claimed!=hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest():
        return {'selected':'legacy','reason':'original_scope_unavailable','grades':{}}
    grades={}
    for name,board,summary in zip(('legacy','pocket'),(legacy_board,pocket_board),summaries):
        request=deepcopy(template)
        request.update(board=str(board),summary=summary,scope=scope['scope'])
        grades[name]=_grade(worker('--grade',request,name))
    # Exactly the configured backend's existing pure ordinary preference rule.
    tree=ast.parse(helper.read_text())
    node=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prefer_pocket'),None)
    if node is None:raise ProofUnavailable('replay_ordinary_preference_unavailable')
    namespace={}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(helper),'exec'),namespace)
    unchanged()
    if candidate_kind not in ('pocket','escape'):raise ProofUnavailable('ordinary_candidate_kind_unproved')
    selected='pocket' if namespace['prefer_pocket'](grades['legacy'],grades['pocket']) else 'legacy'
    result={'selected':selected,'scope':scope,'grades':grades,'ordinary_comparison_only':True}
    if candidate_kind=='escape':
        result.update(selected='escape' if selected=='pocket' else 'legacy',candidate_kind='escape',preference_candidate='pocket')
    (work/'selection.json').write_text(json.dumps(result,sort_keys=True,allow_nan=False)+'\n')
    return result
