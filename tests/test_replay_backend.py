"""Actual owned processes with a controlled metadata producer; no KRT routing."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

from placemat.kicad import issued_calls, route, replay_budget
from placemat.kicad.final_call import ProofUnavailable, file_hash
from tests.test_issued_calls import issued
from tests.test_final_custody import context

HERE = Path(__file__).parent
from placemat.kicad import replay_backend as backend, phase_run

SCRIPT = '''import argparse,json,os,shutil,sys
from pathlib import Path
from types import SimpleNamespace
import route_execution_receipt as receipt
parser=argparse.ArgumentParser()
parser.add_argument('input_file');parser.add_argument('output_file')
parser.add_argument('--json-out');parser.add_argument('--connections')
parser.add_argument('--net-clearances');parser.add_argument('--nets',nargs='+')
parser.add_argument('--layers',nargs='+')
parser.set_defaults(track_width=.2,via_size=.6,via_drill=.3,clearance=.2)
args,unknown=parser.parse_known_args()
sys.modules['grid_router']=SimpleNamespace(__file__=str(Path(__file__).parent.parent/'rust_router/grid_router.so'))
# Manufacturing identity is deliberately controlled; no native board reads.
sys.modules['fab_tiers']=SimpleNamespace(fab_tier_from_args=lambda args:('controlled',{}),
 count_copper_layers_in_file=lambda path:2,
 fab_floor_min=lambda count,tier,overrides:dict(clearance=.2,track_width=.2,via_diameter=.6,via_drill=.3,annular=.15))
tasks=json.loads(Path(args.connections).read_text())
requested=json.loads(Path(args.net_clearances).read_text())
resolved_nets=sorted({task['net'] for task in tasks})
policy=receipt.make(args,sys.argv[1:],resolved_nets,args.layers,os.environ,__file__,tasks,{'1':.2},requested,parser)
shutil.copyfile(args.input_file,args.output_file)
summary={'execution_policy':policy,'connections':[dict(task,status='routed') for task in tasks]}
mode=os.environ.get('CONTROL_MODE')
if mode=='drop_project':policy['input_files'].pop(str(Path(args.input_file).with_suffix('.kicad_pro')))
if mode=='abort_zero':summary['aborted']=0
if mode=='resolved_bool':policy['effective_clearances']={'1':True}
if mode=='requested_changed':policy['requested_clearances']={'N':.3}
if mode=='argv_changed':policy['argv'].append('--invented')
if mode=='deferred':summary['connections'][0]['status']='deferred'
if mode=='missing_policy':summary.pop('execution_policy')
Path(args.json_out).write_text(json.dumps(summary))
sys.exit(1 if mode=='nonzero' else 0)
'''


@pytest.fixture
def launch(issued, tmp_path, request):
    root=tmp_path/'controlled-router'
    (root/'py_router').mkdir(parents=True);(root/'rust_router').mkdir()
    (root/'py_router/route.py').write_text(SCRIPT)
    helper=HERE/'fixtures/replay_backend/route_execution_receipt.py'
    (root/'py_router/route_execution_receipt.py').write_bytes(helper.read_bytes())
    (root/'py_router/route_candidates.py').write_bytes((HERE/'fixtures/replay_backend/route_candidates.py').read_bytes())
    (root/'rust_router/grid_router.so').write_bytes(b'controlled identity only; not imported native')
    mapping=tmp_path/'map.json';mapping.write_text('{"N":0.2}')
    grader,ledger,executor,options=issued
    env=dict(os.environ, KRT_INTERNAL_ROUTE_CANDIDATE='1', KRT_DIR=str(root),
             KRT_ROUTE_DEADLINE_UTC=str(ledger.owner.deadline_utc))
    old_hook=route._HOOK
    try:
        route._HOOK=getattr(request,'param',None)=='hooked'
        command=route.router_command(sys.executable,root/'py_router/route.py',
            options['input_board'],options['output_board'],[],['F.Cu'],options['summary'],
            connections=options['task_file'],nets=None,clearances=mapping)
    finally:
        route._HOOK=old_hook
    options.update(command=command,constraint_files=(mapping,),environment=env)
    budget=replay_budget._executor_reserve(grader,ledger,executor)
    token=issued_calls._executor_issue(grader,ledger,executor,**options)
    ctx=SimpleNamespace(router_dir=root,script='py_router/route.py',rpy=Path(sys.executable),
                        env=env,clearances_file=mapping,budget=budget)
    return grader,ledger,executor,token,ctx,tmp_path/'actual.log'


def test_actual_owned_callback_binds_fresh_files_and_private_vector(launch):
    result=backend.run_issued(*launch)
    assert result['returncode']==0 and result['proposals']==1
    assert result['files']=={launch[3].record['output']:file_hash(launch[3].record['output']),
                             launch[3].record['summary']:file_hash(launch[3].record['summary'])}
    assert launch[3].raw is None  # actual phase restoration hooks retain raw/final receipts later


@pytest.mark.parametrize('mode',['drop_project','abort_zero','resolved_bool','requested_changed',
                                'argv_changed','deferred','missing_policy','nonzero'])
def test_unverified_completed_process_cannot_mint_execution_evidence(launch,mode):
    launch[4].env['CONTROL_MODE']=mode
    with pytest.raises(ProofUnavailable):
        backend.run_issued(*launch)
    assert launch[3].raw is None
    assert Path(launch[3].record['summary']).exists()


def test_stale_output_refuses_before_actual_spawn(launch,monkeypatch):
    Path(launch[3].record['output']).write_text('historical output')
    monkeypatch.setattr(backend,'_execute',lambda *args,**kwargs:pytest.fail('stale call launched'))
    with pytest.raises(ProofUnavailable,match='outputs_not_fresh'):
        backend.run_issued(*launch)


def test_retained_resolved_none_is_not_an_unavailable_comparison(launch):
    backend.run_issued(*launch)
    record=launch[3].record;ctx=launch[4]
    summary=json.loads(Path(record['summary']).read_text())
    _,required,_=backend._runtime(ctx,record['command'])
    implementation={str(path):file_hash(path) for path in required}
    with pytest.raises(ProofUnavailable,match='effective_clearances_changed'):
        backend._policy(summary,record,ctx.env,implementation,{'N':.2},effective_clearances=None)


@pytest.mark.parametrize('launch',['hooked'],indirect=True)
def test_actual_existing_progress_wrapper_preserves_parser_vector_and_owned_context(launch):
    assert backend.run_issued(*launch)['proposals']==1
    record=launch[3].record
    summary=json.loads(Path(record['summary']).read_text())
    assert summary['execution_policy']['argv']==record['command'][3:]


@pytest.mark.parametrize('command',[[],['python']])
def test_malformed_private_command_refuses_before_indexing(command):
    with pytest.raises(ProofUnavailable,match='command_mismatch'):
        backend._runtime(SimpleNamespace(router_dir=HERE),command)


def test_consumed_callback_seals_actual_restored_output_and_immutable_raw(launch,tmp_path):
    grader,ledger,executor,token,ctx,log=launch
    output=Path(token.record['output'])
    def complete(run):
        rc=run(token.record['command'],log,ctx)
        issued_calls._executor_raw_result(grader,ledger,executor,token,
            returncode=rc,snapshot_dir=tmp_path/'actual-raw')
        for suffix in ('.kicad_pro','.kicad_dru'):
            source=Path(token.record['source']).with_suffix(suffix)
            if source.exists():
                output.with_suffix(suffix).write_bytes(source.read_bytes())
        output.write_bytes(output.read_bytes()+b' locked after raw snapshot')
        issued_calls._executor_restored_result(grader,ledger,executor,token)
    result=backend.run_completed(ctx.budget,grader,ledger,executor,token,ctx,log,complete)
    assert result['files'][str(output)]==file_hash(output)
    assert ctx.budget.states==['completed','unused']
    assert any(Path(path).parent.name=='actual-raw' for path in result['files'])
    with pytest.raises(ProofUnavailable,match='already_issued'):
        backend.run_completed(ctx.budget,grader,ledger,executor,token,ctx,log,
                              lambda run:pytest.fail('second launch'))


def test_pre_restoration_callback_cannot_complete_consumed_slot(launch):
    grader,ledger,executor,token,ctx,log=launch
    with pytest.raises(ProofUnavailable,match='not_completed'):
        backend.run_completed(ctx.budget,grader,ledger,executor,token,ctx,log,
            lambda run:run(token.record['command'],log,ctx))
    assert ctx.budget.states==['failed','unused']


@pytest.mark.parametrize('mode',['swallowed_failure','raw_mismatch'])
def test_unverified_or_changed_raw_cannot_seal_slot(launch,tmp_path,mode):
    grader,ledger,executor,token,ctx,log=launch
    if mode=='swallowed_failure':
        ctx.env['CONTROL_MODE']='missing_policy'
    def complete(run):
        try:
            rc=run(token.record['command'],log,ctx)
        except ProofUnavailable:
            if mode!='swallowed_failure':
                raise
            rc=0
        output=Path(token.record['output'])
        if mode=='raw_mismatch':
            output.write_bytes(output.read_bytes()+b' changed before capture')
        issued_calls._executor_raw_result(grader,ledger,executor,token,
            returncode=rc,snapshot_dir=tmp_path/'unverified-raw')
        for suffix in ('.kicad_pro','.kicad_dru'):
            source=Path(token.record['source']).with_suffix(suffix)
            if source.exists():
                output.with_suffix(suffix).write_bytes(source.read_bytes())
        issued_calls._executor_restored_result(grader,ledger,executor,token)
    expected='call_unverified' if mode=='swallowed_failure' else 'raw_changed'
    with pytest.raises(ProofUnavailable,match=expected):
        backend.run_completed(ctx.budget,grader,ledger,executor,token,ctx,log,complete)
    assert ctx.budget.states==['failed','unused']


def test_budget_callback_executes_actual_phase_restoration_helper(launch,tmp_path):
    import ast
    grader,ledger,executor,token,ctx,log=launch
    path=Path(phase_run.__file__)
    tree=ast.parse(path.read_text())
    helper=next(node for node in tree.body if isinstance(node,ast.FunctionDef)
                and node.name=='_completed_single_call')
    events=[]
    def companions(source,output):
        events.append('companions')
        for suffix in ('.kicad_pro','.kicad_dru'):
            original=Path(source).with_suffix(suffix)
            if original.exists():
                Path(output).with_suffix(suffix).write_bytes(original.read_bytes())
    def lock(output):
        events.append('lock');path=Path(output)
        path.write_bytes(path.read_bytes()+b' controlled lock')
    def raw(actual,rc):
        assert actual is token
        events.append('raw')
        issued_calls._executor_raw_result(grader,ledger,executor,actual,
            returncode=rc,snapshot_dir=tmp_path/'phase-helper-raw')
    def restored(actual):
        assert actual is token
        events.append('completed')
        issued_calls._executor_restored_result(grader,ledger,executor,actual)
    ctx.execution=SimpleNamespace(raw_call=raw,restored_call=restored)
    namespace={'_copy_project':companions,'lock_copper':lock,
               '_failed':lambda *a:pytest.fail('unexpected controlled failure')}
    exec(compile(ast.Module(body=[helper],type_ignores=[]),str(path),'exec'),namespace)
    result=backend.run_completed(ctx.budget,grader,ledger,executor,token,ctx,log,
        lambda run:namespace['_completed_single_call'](ctx,token.record['command'],log,
            'controlled call',Path(token.record['source']),Path(token.record['output']),token,run=run))
    assert events==['raw','companions','lock','completed']
    assert result['files'][token.record['output']]==file_hash(token.record['output'])
    assert ctx.budget.states==['completed','unused']
