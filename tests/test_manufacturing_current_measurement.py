"""Actual measurement callback with controlled owner/producer boundaries.

Current packet interpretation and final byte/identity guards execute unchanged;
this does not claim genuine factory lifecycle or native geometry qualification.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from placemat.kicad import manufacturing_current_measurement as measurement
from placemat.kicad.final_call import ProofUnavailable
from tests.test_manufacturing_receipt_validation import pair
from tests.test_manufacturing_current_prepare import current
from tests.test_manufacturing_refinement import packet as grade_packet

@pytest.fixture
def rig(pair,tmp_path,monkeypatch):
    packet,reply=pair
    budget=SimpleNamespace(deadline=packet['request']['deadline_utc'],executor=object(),states=['completed','issued'],_check=lambda e:None)
    owner=SimpleNamespace(factory=object(),contexts_for=lambda b:{'call':SimpleNamespace(env={})})
    monkeypatch.setattr(measurement,'prepare',lambda *a,**kw:packet)
    monkeypatch.setattr(measurement,'retained_original',lambda f:{'controlled':'owner'})
    monkeypatch.setattr(measurement,'_implementation',lambda:packet['request']['runtime'])
    calls=[]
    def execute(argv,deadline,env,**kw):
        calls.append((argv,deadline,env))
        Path(argv[-1]).write_text(json.dumps(reply))
        return 0,'controlled native producer',''
    monkeypatch.setattr(measurement,'_execute',execute)
    grades = grade_packet()[0]
    for grade in grades.values():
        grade['unproved'].append('independent_width_policy_unproved')
        grade['widths_unknown'] = True
    return SimpleNamespace(packet=packet,reply=reply,budget=budget,owner=owner,calls=calls,tmp=tmp_path,grades=grades)

def run(rig):
    return measurement.measure(rig.budget,rig.owner,'call','unused','unused',{},
        rig.grades,rig.tmp/'measurement',lambda:None)

def test_current_callback_binds_deadline_and_preserves_partial_unknown(rig):
    result=run(rig)
    assert len(rig.calls)==1 and rig.calls[0][1]==rig.budget.deadline
    assert rig.budget.states==['completed','issued']
    assert result['pocket']['known'] is False
    assert result['pocket']['unproved'] == ['independent_width_policy_unproved']
    assert result['pocket']['widths_unknown'] is True
    assert (rig.tmp/'measurement'/'measurement.json').exists()

@pytest.mark.parametrize('kind',['missing_reply','malformed_reply','missing_report','replaced_report'])
def test_expected_artifact_failure_is_typed_refusal(rig,monkeypatch,kind):
    def execute(argv,*a,**kw):
        if kind!='missing_reply':Path(argv[-1]).write_text('{}' if kind=='malformed_reply' else json.dumps(rig.reply))
        report=Path(rig.reply['mandatory_clearance']['rows']['candidate']['original_report']['argv'][-2])
        if kind=='missing_report':report.unlink()
        if kind=='replaced_report':report.write_text('{}')
        return 0,'',''
    monkeypatch.setattr(measurement,'_execute',execute)
    with pytest.raises(ProofUnavailable):run(rig)
    assert not (rig.tmp/'measurement'/'measurement.json').exists()

@pytest.mark.parametrize('bad',[None,{'known':False}, {'known':False,'unproved':[]}])
def test_bad_grade_refuses_before_native_launch(rig,bad):
    grades=grade_packet()[0];grades['pocket']=bad
    with pytest.raises(ProofUnavailable,match='current_measurement_grade_unavailable'):
        measurement.measure(rig.budget,rig.owner,'call','unused','unused',{},grades,rig.tmp/'measurement',lambda:None)
    assert rig.calls==[] and not (rig.tmp/'measurement').exists()

@pytest.mark.parametrize('error',[TimeoutError('original deadline'),KeyboardInterrupt()])
def test_timeout_cancellation_propagate_without_reopening_slot(rig,monkeypatch,error):
    def execute(*a,**kw):raise error
    monkeypatch.setattr(measurement,'_execute',execute)
    with pytest.raises(type(error)):run(rig)
    assert rig.budget.states==['completed','issued']

def test_expired_original_budget_refuses_before_launch(rig):
    def expired(e):raise ProofUnavailable('replay_deadline_expired')
    rig.budget._check=expired
    with pytest.raises(ProofUnavailable,match='replay_deadline_expired'):run(rig)
    assert rig.calls==[]
