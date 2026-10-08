"""Controlled ordinary scope/grade worker; no KiCad or routing search.

Pure preference/scope bodies are preserved from the reviewed backend; grade
output is deliberately supplied by the owned test board JSON.
"""
import hashlib,json,sys
from pathlib import Path

def closure_hint(summary):
    """Only a trigger; adoption requires a fresh grade of the shipped file."""
    if not isinstance(summary, dict):
        return None
    records = summary.get('connections')
    if records is not None:
        return sum(not r.get('joined') or r.get('status') in
                   ('failed', 'refused', 'joined_narrow', 'deferred') for r in records)
    if summary.get('status') == 'already_connected':
        return 0
    if not isinstance(summary.get('regrade'), dict):
        return None
    return (len(summary.get('failed_single') or [])
            + len(summary.get('open_single') or [])
            + max(0, (summary.get('multipoint_pads_total') or 0)
                  - (summary.get('multipoint_pads_connected') or 0)))


def prefer_pocket(legacy, pocket):
    """Fail closed on unknown checks; only a physically legal proposal competes.

    Complete legacy is retained without making a proposal. Among remaining
    candidates compare closure; quality is a tie-break only for complete boards.
    Ties always retain legacy, including equal incomplete closure.
    """
    if not legacy or not pocket or not pocket.get('known'):
        return False
    if pocket['drc'] or pocket['undersized'] or pocket['widths_unknown']:
        return False
    if not legacy.get('known'):
        return False
    if pocket['open'] < legacy['open']:
        return True
    if pocket['open'] == legacy['open'] == 0:
        if legacy['drc'] or legacy['undersized'] or legacy['widths_unknown']:
            return True
        return tuple(pocket['quality']) < tuple(legacy['quality'])
    return False


def freeze_scope(requested_scope, candidates, tasks=None):
    """Both proposals owe exactly the same requested and discovered obligations."""
    from route_summary import named_nets
    requested = sorted(set(requested_scope))
    scope = sorted(set(requested) | {net for candidate in candidates
        for net in named_nets([candidate['summary'] or {}])})
    identity = {'requested_nets': requested, 'graded_nets': scope, 'tasks': tasks}
    identity['sha256'] = hashlib.sha256(json.dumps(identity, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    return scope, identity


def load_json(path):
    try:
        with open(path, encoding='utf-8') as source:
            return json.load(source)
    except (OSError, ValueError):
        return None


def ordinary_scope_request(request):
    """The existing ordinary comparator's full requested/disclosed scope."""
    scope, identity = freeze_scope(request['requested_scope'], request['candidates'],
        load_json(request['connections']) if request['connections'] else None)
    return {'scope': scope, 'identity': identity}


def grade_request(request):
    return json.loads(Path(request['board']).read_text())

if __name__=='__main__':
    mode,request,output=sys.argv[1:]
    request=json.loads(Path(request).read_text())
    result=ordinary_scope_request(request) if mode=='--ordinary-scope' else grade_request(request)
    Path(output).write_text(json.dumps(result)+'\n')
