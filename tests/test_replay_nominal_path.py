"""Actual eligible subprocess in split/flat layouts; controlled grade producer."""
from pathlib import Path
from types import SimpleNamespace
import json,sys,shutil
import pytest
from tests.test_replay_backend import launch,issued,context
from tests.test_replay_ordinary_backend import lifecycle
from placemat.kicad import replay_backend as backend,replay_nominal as nominal
from placemat.kicad.final_call import file_hash,record_digest,ProofUnavailable

GRADE = """import json,sys
from pathlib import Path
assert sys.argv[1]=='--nominal-evidence'
r=json.loads(Path(sys.argv[2]).read_bytes());ctx=json.loads(Path(r['context']).read_bytes())
value={'schema':1,'proof_sha256':ctx['identity']['proof_sha256'],'call_id':ctx['identity']['call_id'],'input_files':ctx['proof']['input_files'],'files':r['files'],'failures':[{'endpoint':{'net':'N','ref':'A','pad':'1'},'peer':{'ref':'B','pad':'2'}}],'refused':[],'comparison_authority':False}
Path(sys.argv[3]).write_text(json.dumps(value))
"""

@pytest.fixture(params=['split','flat'])
def eligibility(issued,tmp_path,monkeypatch,request):
    from tests.test_replay_backend import SCRIPT,HERE
    from placemat.kicad import route,replay_budget,issued_calls
    import os
    root=tmp_path/'controlled-router';root.mkdir();(root/'rust_router').mkdir()
    folder=root/'py_router' if request.param=='split' else root
    folder.mkdir(exist_ok=True)
    script=SCRIPT if request.param=='split' else SCRIPT.replace("Path(__file__).parent.parent/'rust_router", "Path(__file__).parent/'rust_router")
    (folder/'route.py').write_text(script)
    (folder/'route_execution_receipt.py').write_bytes((HERE/'fixtures/replay_backend/route_execution_receipt.py').read_bytes())
    grade=folder/'route_candidates.py'
    grade.write_text((HERE/'fixtures/replay_backend/route_candidates.py').read_text().split("if __name__ == '__main__':",1)[0]+"\nif __name__ == '__main__':\n"+''.join('    '+line+'\n' for line in GRADE.splitlines()))
    (root/'rust_router/grid_router.so').write_bytes(b'controlled identity only')
    mapping=tmp_path/'map.json';mapping.write_text('{"N":0.2}')
    grader,ledger,executor,options=issued
    env=dict(os.environ,KRT_INTERNAL_ROUTE_CANDIDATE='1',KRT_DIR=str(root),KRT_ROUTE_DEADLINE_UTC=str(ledger.owner.deadline_utc))
    command=route.router_command(sys.executable,folder/'route.py',options['input_board'],options['output_board'],[],['F.Cu'],options['summary'],connections=options['task_file'],nets=None,clearances=mapping)
    options.update(command=command,constraint_files=(mapping,),environment=env)
    budget=replay_budget._executor_reserve(grader,ledger,executor)
    token=issued_calls._executor_issue(grader,ledger,executor,**options)
    ctx=SimpleNamespace(router_dir=root,script=str((folder/'route.py').relative_to(root)),rpy=Path(sys.executable),env=env,clearances_file=mapping,budget=budget)
    log=tmp_path/'actual.log';launch=(grader,ledger,executor,token,ctx,log)
    backend.run_completed(ctx.budget,grader,ledger,executor,token,ctx,log,lifecycle(launch,tmp_path))
    files={};identity={'proof_sha256':'a'*64,'call_id':'call'};proof={'input_files':{}}
    paths={}
    for name in ('context','evidence','log'):
        path=tmp_path/(name+'.json');path.write_text(json.dumps({'identity':identity,'proof':proof}) if name=='context' else '{}')
        paths[name]=str(path);files[str(path)]=file_hash(path)
    runtime,_,_=backend._runtime(ctx,token.record['command'])
    observation=dict(paths,identity=identity,proof=proof,source_files=files,detached_files=files,runtime=runtime)
    capability={'policies':{'grade_path':str(grade.resolve()),'grade_sha256':file_hash(grade)}}
    owner=SimpleNamespace(final_call=token,backend_eligibility={'policy_proved':True},nominal_refusal=None,nominal_observation=observation,nominal_observation_sha=record_digest(observation),backend_capability=capability,backend_capability_sha=record_digest(capability),contexts_for=lambda budget:{token:ctx})
    monkeypatch.setattr(nominal,'_failed_pairs',lambda grader:{('N','A','1','B','2')})
    return ctx.budget,owner,token,tmp_path/'eligibility',grade


def test_actual_eligible_executes_configured_sibling(eligibility):
    budget,owner,token,work,grade=eligibility
    value=nominal.eligible(budget,owner,token,work)
    assert value['failures'][0]['endpoint']['net']=='N'
    assert (work/'reply.json').exists()

@pytest.mark.parametrize('change',['helper','capability'])
def test_changed_helper_or_capability_refuses_before_subprocess(eligibility,change):
    budget,owner,token,work,grade=eligibility
    if change=='helper':grade.write_text('changed helper')
    else:owner.backend_capability['policies']['grade_sha256']='b'*64
    with pytest.raises(ProofUnavailable):nominal.eligible(budget,owner,token,work)
    assert not (work/'reply.json').exists()


@pytest.mark.parametrize('change',['helper','capability'])
def test_changed_helper_or_capability_after_actual_subprocess_refuses(eligibility,monkeypatch,change):
    budget,owner,token,work,grade=eligibility
    execute=nominal._execute
    def actual(*args,**kwargs):
        result=execute(*args,**kwargs)
        if change=='helper':grade.write_text('changed after actual reply')
        else:owner.backend_capability['policies']['grade_sha256']='c'*64
        return result
    monkeypatch.setattr(nominal,'_execute',actual)
    with pytest.raises(ProofUnavailable):nominal.eligible(budget,owner,token,work)
    assert (work/'reply.json').exists()
