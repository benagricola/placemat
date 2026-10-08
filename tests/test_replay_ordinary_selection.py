"""Controlled grade/measurement producers; actual scope and preference stay intact.

Genuine retained manufacturing custody is tested by the manufacturing integration
modules. This unit fixture uses JSON stand-in boards and cannot provide custody.
"""
import ast
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from placemat.kicad import replay_ordinary_selection as selection
from placemat.kicad.final_call import ProofUnavailable,file_hash


def grade(open_count=1):
    return dict(known=True,unproved=[],drc=0,undersized=0,widths_unknown=False,open=open_count,quality=[1,2,3])


@pytest.fixture
def rig(tmp_path,monkeypatch):
    root=tmp_path/'router';root.mkdir()
    helper=root/'route_candidates.py'
    fixtures=Path(__file__).parent/'fixtures'/'replay_backend'
    shutil.copy(fixtures/'ordinary_grade.py',helper)
    shutil.copy(fixtures/'route_summary.py',root/'route_summary.py')
    from placemat.kicad import manufacturing_current_measurement
    measurement_calls = []
    def controlled_measure(*args):
        measurement_calls.append(True)
        return args[6]
    monkeypatch.setattr(manufacturing_current_measurement, 'measure', controlled_measure)
    token=object();executor=object()
    ctx=SimpleNamespace(router_dir=root,script='route.py',rpy=sys.executable,env=dict(os.environ,PYTHONPATH=str(root)))
    legacy=tmp_path/'legacy-raw';legacy.mkdir();pocket=tmp_path/'pocket';(pocket/'raw').mkdir(parents=True)
    old=legacy/'1-out.kicad_pcb';old.write_text(json.dumps(grade(2)))
    new=pocket/'raw'/'1-out.kicad_pcb';new.write_text(json.dumps(grade(1)))
    summary=pocket/'raw'/'2-summary.json';summary.write_text(json.dumps({'routed_single':['B']}))
    record={'command':['controlled'], 'output':str(tmp_path/'out.kicad_pcb'), 'raw':{'files':{str(old):file_hash(old)},'summary':{'oracle_open':{'C':1}}}}
    files={str(p):file_hash(p) for p in (new,summary)}
    template={'scope':['A'],'connections':None,'board':'unused','summary':None,'input':'original','sentinel':{'explicit':False}}
    monkeypatch.setattr(selection.issued_calls,'completed_record',lambda *a:record)
    monkeypatch.setattr(selection.backend,'original_grade_request',lambda *a:template)
    monkeypatch.setattr(selection.backend,'_runtime',lambda *a:({str(helper):file_hash(helper)},None,None))
    budget=SimpleNamespace(states=['completed','issued'],executor=executor,grader=object(),ledger=object(),deadline=time.time()+10,_check=lambda e:None)
    owner=SimpleNamespace(final_call=token,contexts_for=lambda b:{token:ctx})
    return SimpleNamespace(budget=budget,owner=owner,token=token,output=pocket/'out.kicad_pcb',files=files,new=new,helper=helper,tmp=tmp_path,template=template,measurement_calls=measurement_calls,old=old,record=record)


def run(rig):
    return selection.choose(rig.budget,rig.owner,rig.token,rig.output,rig.files,rig.tmp/'selection')


def test_actual_scope_and_grade_workers_select_with_same_requests(rig):
    result=run(rig)
    assert result['selected']=='pocket'
    assert result['scope']['scope']==['A','B','C']
    for name in ('legacy','pocket'):
        request=json.loads((rig.tmp/'selection'/(name+'-request.json')).read_text())
        assert request['input']=='original' and request['sentinel']=={'explicit':False}
        assert request['scope']==['A','B','C']


@pytest.mark.parametrize('field,value',[('known',1),('drc',False),('widths_unknown',0),('quality',[True,2,3]),('open',-1)])
def test_malformed_typed_grade_retains_legacy(rig,field,value):
    changed=grade(0);changed[field]=value;rig.new.write_text(json.dumps(changed));rig.files[str(rig.new)]=file_hash(rig.new)
    result = run(rig)
    assert result['selected']=='legacy'
    assert result['reason']=='original_grade_unavailable'
    assert rig.measurement_calls == []


def test_unknown_width_retains_legacy(rig):
    value=grade(0);value['widths_unknown']=True;rig.new.write_text(json.dumps(value));rig.files[str(rig.new)]=file_hash(rig.new)
    assert run(rig)['selected']=='legacy'


def test_snapshot_same_basename_is_ambiguous(tmp_path):
    paths=[tmp_path/'a'/'1-out.kicad_pcb',tmp_path/'b'/'2-out.kicad_pcb']
    with pytest.raises(ProofUnavailable):selection._snapshot({str(p):'unused' for p in paths},'out.kicad_pcb')


@pytest.mark.parametrize('error',[KeyboardInterrupt(),TimeoutError('owned deadline')])
def test_worker_cancellation_or_deadline_propagates(rig,monkeypatch,error):
    def failed(*args,**kwargs):raise error
    monkeypatch.setattr(selection,'_execute',failed)
    with pytest.raises(type(error)):run(rig)
    assert not (rig.tmp/'selection'/'selection.json').exists()


def test_tasks_only_original_scope_is_preserved(rig):
    taskfile=rig.tmp/'tasks.json';tasks=[{'net':'A','from':'U1.1','to':'U2.1','widths':{'F.Cu':.4}}]
    taskfile.write_text(json.dumps(tasks));rig.template.update(scope=[],connections=str(taskfile))
    result=run(rig)
    assert result['scope']['identity']['tasks']==tasks
    for name in ('legacy','pocket'):
        request=json.loads((rig.tmp/'selection'/(name+'-request.json')).read_text())
        assert request['connections']==str(taskfile)


def test_bound_grader_disappearance_refuses_without_selection(rig,monkeypatch):
    execute=selection._execute
    def disappearing(*args,**kwargs):
        result=execute(*args,**kwargs);rig.helper.unlink();return result
    monkeypatch.setattr(selection,'_execute',disappearing)
    with pytest.raises(ProofUnavailable,match='replay_ordinary_grader_changed'):run(rig)
    assert not (rig.tmp/'selection'/'selection.json').exists()


@pytest.mark.parametrize('change',[{'quality':[10**1000,1,1]},{'unproved':['missing width']}])
def test_contradictory_or_unbounded_grade_retains_legacy(rig,change):
    value=grade(0);value.update(change);rig.new.write_text(json.dumps(value));rig.files[str(rig.new)]=file_hash(rig.new)
    assert run(rig)['selected']=='legacy'
    assert rig.measurement_calls == []


@pytest.mark.parametrize('number',[float('nan'),float('inf'),-float('inf')])
def test_nonfinite_unknown_grade_cannot_break_legacy_selection(rig,number):
    rig.new.write_text(json.dumps({'known':False,'reason':number}))
    rig.files[str(rig.new)]=file_hash(rig.new)
    result=run(rig)
    assert result['selected']=='legacy' and result['grades']['pocket'] is None
    assert rig.measurement_calls == []
    assert json.loads((rig.tmp/'selection'/'selection.json').read_text())['selected']=='legacy'


def test_malformed_legacy_grade_retains_original_without_measurement(rig):
    value = grade(2)
    value['known'] = 1
    rig.old.write_text(json.dumps(value))
    rig.record['raw']['files'][str(rig.old)] = file_hash(rig.old)
    result = run(rig)
    assert result['selected'] == 'legacy'
    assert result['reason'] == 'original_grade_unavailable'
    assert result['grades']['legacy'] is None
    assert rig.measurement_calls == []
