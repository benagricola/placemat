"""Controlled original-contract comparison controls; no Standing or board proof."""
import json
from types import SimpleNamespace
import pytest
from placemat.kicad import replay_comparison as compare
from placemat.kicad.final_call import ProofUnavailable

@pytest.fixture
def pair(monkeypatch):
    asks=[[{'net':'P','amps':1},{'net':'Q','amps':2}],[{'net':'S'}]]
    grader=SimpleNamespace(_obligations=json.dumps(asks),_phases=[
        SimpleNamespace(selector='current_paths',width='current'),
        SimpleNamespace(selector='rest',width=None)])
    def result(joined):
        return SimpleNamespace(physical=SimpleNamespace(report=SimpleNamespace(
            asked=json.loads(json.dumps(asks)),final_judged=[[{'joined':v} for v in row] for row in joined])))
    verified=[];ranked=[]
    authority=SimpleNamespace(_grader=grader,verify=lambda value:verified.append(value),
        compare=lambda old,new:ranked.append((old,new)) or True)
    monkeypatch.setattr(compare.final_custody,'require_completed',lambda actual: actual is grader or pytest.fail('wrong grader'))
    return authority,grader,result,verified,ranked

def test_one_incumbent_current_loss_refuses_even_when_aggregate_matches(pair):
    authority,grader,result,verified,ranked=pair
    with pytest.raises(ProofUnavailable,match='current_join_lost'):
        compare.compare_original(authority,grader,result([[True,False],[False]]),result([[False,True],[True]]))
    assert len(verified)==2 and not ranked

def test_preserved_individual_currents_still_use_shared_strict_comparison(pair):
    authority,grader,result,verified,ranked=pair
    assert compare.compare_original(authority,grader,result([[True,False],[False]]),result([[True,True],[True]]))
    assert len(ranked)==1

def test_same_number_of_asks_does_not_allow_changed_identity(pair):
    authority,grader,result,_,ranked=pair
    candidate=result([[True,True],[True]]);candidate.physical.report.asked[0][0]['net']='different'
    with pytest.raises(ProofUnavailable,match='obligations_changed'):
        compare.compare_original(authority,grader,result([[True,False],[False]]),candidate)
    assert not ranked

@pytest.mark.parametrize('value',[1,None])
def test_joined_requires_actual_bool_and_full_cardinality(pair,value):
    authority,grader,result,_,ranked=pair
    candidate=result([[True,True],[True]])
    candidate.physical.report.final_judged[0][0]['joined']=value
    with pytest.raises(ProofUnavailable,match='judgment_unproved'):
        compare.compare_original(authority,grader,result([[True,False],[False]]),candidate)
    assert not ranked

def test_required_width_unknown_refusal_propagates_from_full_authority(pair):
    authority,grader,result,_,_=pair
    def unknown(*args):
        raise ProofUnavailable('required_width_unproved')
    authority.compare=unknown
    with pytest.raises(ProofUnavailable,match='required_width_unproved'):
        compare.compare_original(authority,grader,result([[True,False],[False]]),result([[True,True],[True]]))
