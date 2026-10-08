"""Actual extracted phase lifecycle order; controlled operations, no board proof."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest

@pytest.fixture
def lifecycle():
    from placemat.kicad import phase_run
    path=Path(phase_run.__file__)
    tree=ast.parse(path.read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_completed_single_call')
    events=[]
    def failed(*args):
        events.append('failed');raise RuntimeError('real failure')
    ns={'_run':lambda *a:events.append('run') or 0,
        '_failed':failed,'_copy_project':lambda *a:events.append('companions'),
        'lock_copper':lambda *a:events.append('lock')}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    ctx=SimpleNamespace(execution=SimpleNamespace(
        raw_call=lambda *a:events.append('raw'),restored_call=lambda *a:events.append('completed')))
    return ns['_completed_single_call'],ctx,events

def test_slot_callback_includes_raw_and_existing_restoration(lifecycle,tmp_path):
    call,ctx,events=lifecycle
    output=tmp_path/'output';output.touch()
    call(ctx,[],None,None,None,output,object())
    assert events==['run','raw','companions','lock','completed']

def test_failure_never_records_restoration(lifecycle,tmp_path):
    call,ctx,events=lifecycle
    with pytest.raises(RuntimeError):
        call(ctx,[],None,None,None,tmp_path/'absent',object())
    assert events==['run','raw','failed']

def test_absent_optional_context_keeps_single_existing_restoration(lifecycle,tmp_path):
    call,ctx,events=lifecycle;ctx.execution=None
    output=tmp_path/'output';output.touch()
    call(ctx,[],None,None,None,output,None)
    assert events==['run','companions','lock']


@pytest.mark.parametrize('kind',['nets','rest','bus'])
def test_actual_route_calls_single_branch_fence_and_bus_parse_order(kind,tmp_path):
    from placemat.kicad import phase_run
    import json
    import time
    from placemat.kicad import phase_run
    path=Path(phase_run.__file__)
    tree=ast.parse(path.read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef)
           and n.name in ('route_calls','_completed_single_call')]
    events=[]
    def run(command,log,ctx):
        events.append('run')
        (ctx.work/'p0_0.kicad_pcb').write_text('controlled raw copper')
        (ctx.work/'p0_0_summary.json').write_text('{"bus_groups":[]}')
        return 0
    def parse(text):
        events.append('bus_parse');return json.loads(text)
    execution=SimpleNamespace(plan_calls=lambda **kw:None,
        issue_call=lambda **kw:object(),raw_call=lambda *a:events.append('raw'),
        restored_call=lambda *a:events.append('completed'))
    ctx=SimpleNamespace(cfg=SimpleNamespace(route_router_args=()),env={},
        class_clearances={},stated_clearances={},geometry=SimpleNamespace(default_clearance=.2,nets=['N']),
        clearance_map={},base_clearance=.2,clearances_file=None,excluded=[],pour_nets=[],
        execution=execution,iterations=None,probe=None,quick=False,work=tmp_path,rpy='python',script='route.py')
    phase=SimpleNamespace(router_args=(),name='signal',neckdown=True)
    call=phase_run.Call(kind,('N',))
    ns={'__package__':'placemat.kicad','time':time,'json':SimpleNamespace(loads=parse),
        'replace':lambda original,**kw:original,'plan_calls':lambda *a:[call],
        'PhaseOutcome':phase_run.PhaseOutcome,'Routed':lambda *a:SimpleNamespace(record=lambda:{}),
        'router_command':lambda *a,**kw:[], '_run':run,
        '_failed':lambda *a:pytest.fail('unexpected failure'),
        '_copy_project':lambda *a:events.append('companions'),
        'lock_copper':lambda *a:events.append('lock'),
        'main_pass_nets':lambda *a:['N'],
        'phase_widths':lambda *a:[], 'narrow_join_widths':lambda *a:[],
        'task_widths':lambda *a:[]}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)
    execution.issue_single=lambda actual_ctx,**kw:(actual_ctx,object())
    execution.execute_single=lambda *args:ns['_completed_single_call'](*args)
    ns['route_calls'](ctx,0,phase,SimpleNamespace(layers=['F.Cu']),tmp_path/'input')
    assert events==(['run','raw','companions','bus_parse','lock','completed']
                    if kind=='bus' else ['run','raw','companions','lock','completed'])
