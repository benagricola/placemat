"""Actual parent/worker protocol with controlled native imports/operations."""
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict,replace
from copy import deepcopy
import json,time,sys
import pytest
from placemat.settings import Settings,active
from placemat.kicad import replay_restoration as parent,replay_restoration_worker as worker,final_owned_worker,quiet
from placemat.kicad.final_worker_protocol import _plain
from placemat.kicad.final_call import ProofUnavailable

@pytest.fixture
def protocol(tmp_path,monkeypatch):
    cfg=Settings(run_max_time_s=432.5,run_parallel=False,studio_port=4242,facts_confirmed='confirmed',facts_boards={'board.py':'fact'},sources={'route':'retained'})
    current=tmp_path/'current.kicad_pcb';current.write_text('immutable board')
    current.with_suffix('.kicad_pro').write_text('retained rules')
    given=tmp_path/'given.kicad_pcb';output=tmp_path/'output.kicad_pcb';work=tmp_path/'work';work.mkdir()
    budget=SimpleNamespace(executor=object(),deadline=time.time()+100,grader=SimpleNamespace(_cfg=deepcopy(cfg)),_check=lambda executor:None)
    ctx=SimpleNamespace(cfg=cfg,layers=['F.Cu'],env={});seen=[];requests=[]
    monkeypatch.setitem(sys.modules,'placemat_native',SimpleNamespace())
    monkeypatch.setattr(quiet,'import_pcbnew',lambda:None)
    monkeypatch.setattr(final_owned_worker,'_implementation',lambda:{'controlled':True})
    monkeypatch.setattr(parent,'_implementation',lambda:{'controlled':True})
    def operations(request,route):
        seen.append(_plain(asdict(active())))
        Path(request['given']).write_bytes(Path(request['current']).read_bytes())
        Path(request['given']).with_suffix('.kicad_pro').write_bytes(current.with_suffix('.kicad_pro').read_bytes())
    monkeypatch.setattr(worker,'operations',operations)
    def execute(command,deadline,env):
        request=json.loads(Path(command[2]).read_bytes());requests.append(request)
        Path(command[3]).write_text(json.dumps(worker.evaluate(request)));return 0,'',''
    monkeypatch.setattr(parent,'_execute',execute)
    return budget,ctx,current,given,output,work,seen,requests

@pytest.mark.parametrize('stage',['prepare','restore'])
def test_real_parent_packet_full_settings_roundtrip(protocol,stage,monkeypatch):
    budget,ctx,current,given,output,work,seen,requests=protocol;before=_plain(asdict(ctx.cfg))
    if stage=='restore':
        given.write_bytes(current.read_bytes());given.with_suffix('.kicad_pro').write_text('retained rules');output.write_text('raw output')
        def operations(request,route):
            seen.append(_plain(asdict(active())))
            output.write_text(output.read_text()+' controlled lock')
            output.with_suffix('.kicad_pro').write_bytes(given.with_suffix('.kicad_pro').read_bytes())
        monkeypatch.setattr(worker,'operations',operations)
    parent.run(budget,{'identity':{'kind':'single'},'nets':['N']},ctx,stage,current,given,output,work)
    assert requests[0]['settings']==before and seen==[before]
    assert {'sources','run_max_time_s','studio_port','facts_boards'}<=set(before)
    assert _plain(asdict(ctx.cfg))==before==_plain(asdict(budget.grader._cfg))
    assert given.read_bytes()==current.read_bytes()

@pytest.mark.parametrize('change',['missing','extra','wrong_bool','wrong_sources','coercion','source_changed'])
def test_actual_parent_malformed_or_changed_packet_refuses(protocol,monkeypatch,change):
    budget,ctx,current,given,output,work,seen,requests=protocol
    def execute(command,deadline,env):
        request=json.loads(Path(command[2]).read_bytes());requests.append(request);values=request['settings']
        if change=='missing':values.pop('run_parallel')
        elif change=='extra':values['invented']=True
        elif change=='wrong_bool':values['run_parallel']=0
        elif change=='wrong_sources':values['sources']={'route':False}
        elif change=='coercion':values['studio_port']='4242'
        else:current.write_text('changed source')
        worker.evaluate(request);pytest.fail('malformed packet accepted')
    monkeypatch.setattr(parent,'_execute',execute)
    with pytest.raises(ProofUnavailable):parent.run(budget,{'identity':{'kind':'single'},'nets':['N']},ctx,'prepare',current,given,output,work)
    assert seen==[] and not given.exists()


@pytest.mark.parametrize('field,value',[('run_max_time_s',10.0),('studio_port',4243),('facts_confirmed','changed'),('sources',{'route':'changed'})])
def test_omitted_projection_field_context_mismatch_refuses_before_child(protocol,monkeypatch,field,value):
    budget,ctx,current,given,output,work,seen,requests=protocol
    ctx.cfg=replace(ctx.cfg,**{field:value})
    monkeypatch.setattr(parent,'_execute',lambda *a,**k:pytest.fail('mismatched context launched'))
    with pytest.raises(ProofUnavailable,match='retained_settings_changed'):
        parent.run(budget,{'identity':{'kind':'single'},'nets':['N']},ctx,'prepare',current,given,output,work)
    assert seen==[] and requests==[]
