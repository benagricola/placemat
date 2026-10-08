"""Original executor scope includes one-pad nets without adding obligations."""
from copy import deepcopy
from dataclasses import replace, dataclass
import json
from pathlib import Path
import sys
import pytest
from placemat.kicad import final_custody as custody,issued_calls,final_execution,phase_run,replay_capability
from placemat.kicad.final_call import ProofUnavailable
from tests.test_final_custody import context,register

@pytest.fixture
def single(context,tmp_path):
    grader,facts,report=context
    facts['geometry']=replace(facts['geometry'],nets=frozenset({'N','NC','EXCLUDED'}))
    grader,facts,report=register(context);executor=object();ledger=custody._executor_begin_calls(grader,executor)
    issued_calls._executor_plan(grader,ledger,executor,phase=0,calls=[phase_run.Call('rest',excluded=('EXCLUDED',))],layers=['F.Cu'],input_board=grader._original)
    options=dict(phase=0,call=0,wave=0,kind='single',command=[sys.executable,'route.py','--nets','*','!EXCLUDED','--layers','F.Cu'],source=grader._original,input_board=grader._original,output_board=tmp_path/'output.kicad_pcb',summary=tmp_path/'summary.json',layers=['F.Cu'],nets=['N','NC'],tasks=[],constraint_files=(),snapshot_dir=tmp_path/'snapshot',environment={})
    return grader,ledger,executor,options,facts

def test_exact_original_rest_scope_accepts_one_pad_net_without_new_ask(single):
    grader,ledger,executor,options,_=single;before=deepcopy(grader._obligations)
    token=issued_calls._executor_issue(grader,ledger,executor,**options)
    assert token.record['nets']==['N','NC'] and grader._obligations==before
    assert ledger.call_plans[0][0]['calls'][0]['excluded']==['EXCLUDED']

@pytest.mark.parametrize('nets',[['N'],['N','NC','EXCLUDED'],['N','NC','FORGED'],['N','NC','NC']])
def test_missing_extra_excluded_or_duplicate_net_refuses(single,nets):
    grader,ledger,executor,options,_=single;options['nets']=nets
    with pytest.raises(ProofUnavailable,match='issued_single_scope_mismatch'):issued_calls._executor_issue(grader,ledger,executor,**options)
    assert not options['snapshot_dir'].exists()

def test_changed_plan_refuses(single):
    grader,ledger,executor,options,_=single;ledger.call_plans[0][0]['calls'][0]['excluded']=[]
    with pytest.raises(ProofUnavailable,match='issued_call_plan_changed'):issued_calls._executor_issue(grader,ledger,executor,**options)

def test_changed_layer_refuses(single):
    grader,ledger,executor,options,_=single;options['layers']=['B.Cu']
    with pytest.raises(ProofUnavailable,match='issued_single_scope_mismatch'):issued_calls._executor_issue(grader,ledger,executor,**options)

def test_unplanned_scope_keeps_old_obligation_guard(single):
    grader,ledger,executor,options,_=single;ledger.call_plans.clear()
    with pytest.raises(ProofUnavailable,match='issued_net_outside_original_contract'):issued_calls._executor_issue(grader,ledger,executor,**options)

def test_source_geometry_mutation_refuses(single):
    grader,ledger,executor,options,_=single;ledger.owner.geometry.netclasses.clear()
    with pytest.raises(ProofUnavailable,match='retained_geometry_changed'):issued_calls._executor_issue(grader,ledger,executor,**options)

@dataclass
class Ctx:
    env:dict

def test_actual_final_preissue_retains_first_precise_issuer_refusal(single,monkeypatch):
    grader,ledger,executor,options,facts=single
    hook=object.__new__(final_execution.FinalExecution);hook.active=True;hook.grader=grader;hook.ledger=ledger;hook.executor=executor;hook.work=options['snapshot_dir'].parent;hook.deadline=facts['deadline_utc'];hook.refusals=(ProofUnavailable,);hook.contexts={};hook.final_call=None;hook.replay_budget=None
    monkeypatch.setattr(replay_capability,'query',lambda *a:{'controlled':True})
    def no_observer(*a):raise ProofUnavailable('controlled_observer_unavailable')
    monkeypatch.setattr(hook,'_prepare_nominal_context',no_observer)
    options=dict(options);options.pop('snapshot_dir');options['nets']=['N']
    ctx=Ctx({});actual,token=hook.issue_single(ctx,**options)
    assert actual is ctx and token is None and hook.replay_budget is None and hook.final_call is None
    assert json.loads((hook.work/'final_authority_unavailable.json').read_text())['code']=='issued_single_scope_mismatch'
    assert not ledger.issued and not hook.contexts

@pytest.mark.parametrize('command',[
    [sys.executable,'route.py','--nets','*','--layers','F.Cu'],
    [sys.executable,'route.py','--nets','N','NC','--layers','F.Cu'],
    [sys.executable,'route.py','--nets','*','!EXCLUDED','--nets','*','--layers','F.Cu'],
    [sys.executable,'route.py','--nets','*','!EXCLUDED','--layers','B.Cu'],
])
def test_changed_actual_filter_or_layer_vector_refuses(single,command):
    grader,ledger,executor,options,_=single;options['command']=command
    with pytest.raises(ProofUnavailable,match='issued_single_scope_mismatch'):
        issued_calls._executor_issue(grader,ledger,executor,**options)

def named_scope(context,tmp_path,names,kind,nets=(),excluded=()):
    from placemat.kicad.route import router_command, main_pass_nets
    grader,facts,report=context;facts['geometry']=replace(facts['geometry'],nets=frozenset(names))
    grader,facts,report=register(context);executor=object();ledger=custody._executor_begin_calls(grader,executor)
    issued_calls._executor_plan(grader,ledger,executor,phase=0,calls=[phase_run.Call(kind,tuple(nets),excluded=tuple(excluded))],layers=['F.Cu'],input_board=grader._original)
    selected=sorted(main_pass_nets(names,set(excluded))) if kind=='rest' else list(nets)
    output=tmp_path/'out.kicad_pcb';summary=tmp_path/'summary.json'
    command=router_command(sys.executable,'route.py',grader._original,output,set(excluded),['F.Cu'],summary,nets=None if kind=='rest' else list(nets))
    options=dict(phase=0,call=0,wave=0,kind='single',command=command,source=grader._original,input_board=grader._original,output_board=output,summary=summary,layers=['F.Cu'],nets=selected,tasks=[],constraint_files=(),snapshot_dir=tmp_path/'named-snapshot')
    return grader,ledger,executor,options

@pytest.mark.parametrize('name',['D[0]','D*','D?','!RESET'])
def test_actual_builder_literal_one_pad_scope(context,tmp_path,name):
    args=named_scope(context,tmp_path,{'N',name,'D0','DX'},'nets',nets=[name])
    token=issued_calls._executor_issue(*args[:3],**args[3]);assert token.record['nets']==[name]

@pytest.mark.parametrize('excluded,expected',[
    (['GND'],{'N'}),
    (['/Sub/GND'],{'N','GND'}),
])
def test_actual_rest_hierarchical_exclusion(context,tmp_path,excluded,expected):
    args=named_scope(context,tmp_path,{'N','GND','/Sub/GND'},'rest',excluded=excluded)
    token=issued_calls._executor_issue(*args[:3],**args[3]);assert set(token.record['nets'])==expected

def test_actual_rest_literal_exclusion_token_named_net_is_included(context,tmp_path):
    args=named_scope(context,tmp_path,{'N','GND','!GND','/Sub/GND'},'rest',excluded=['GND'])
    token=issued_calls._executor_issue(*args[:3],**args[3]);assert set(token.record['nets'])=={'N','GND','!GND','/Sub/GND'}

def test_explicit_leaf_alias_widening_refuses(context,tmp_path):
    args=named_scope(context,tmp_path,{'N','GND','/Sub/GND'},'nets',nets=['GND'])
    with pytest.raises(ProofUnavailable,match='issued_single_leaf_scope_unproved'):
        issued_calls._executor_issue(*args[:3],**args[3])
