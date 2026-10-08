"""Actual second-slot callback; controlled restoration/router and original comparator."""
import json
from pathlib import Path
import pytest
from tests.test_replay_pocket import rig
from placemat.kicad import replay_pocket as pocket
from placemat.kicad.final_call import file_hash,record_digest,ProofUnavailable


def nominal(rig):
    reply=rig.work.parent/'eligibility.json';reply.write_text('{}')
    proof={'nominal_policy':{'by_net':{'SIGNAL':{'F.Cu':.2}}}}
    return {'proof':proof,'identity':{'proof_sha256':record_digest(proof),'call_id':'fixed'},
            'eligibility_reply':str(reply),'eligibility_sha256':file_hash(reply),
            'source_files':{},'detached_files':{},'runtime':{},'failures':[{'endpoint':{'net':'SIGNAL','ref':'J1','pad':'1'},'nominal_geometry':{'via_size':.6,'via_drill':.3}}]}


@pytest.mark.parametrize('accepted',[True,False])
def test_escape_consumes_only_second_slot_with_fresh_context(rig,monkeypatch,accepted):
    old=rig.work.parent/'old-context.json';old.write_text('immutable')
    ctx=rig.owner.contexts_for(rig.budget)[rig.token]
    ctx.env.update(KRT_INTERNAL_FINAL_CALL_CONTEXT=str(old),KRT_INTERNAL_FINAL_CALL_KIND='legacy',
                   KRT_INTERNAL_FINAL_CALL_PROOF='old',KRT_INTERNAL_FINAL_CALL_ID='old')
    calls=[]
    def backend(record,deadline,c,log,validate,actual_completed):
        validate();calls.append(dict(c.env))
        assert c.env['KRT_INTERNAL_ROUTE_CANDIDATE']=='1'
        assert c.env['KRT_INTERNAL_FINAL_CALL_KIND']=='escape'
        assert 'KRT_INTERNAL_POCKET_WALLS' not in c.env
        seed=json.loads(Path(c.env['KRT_INTERNAL_FINAL_CALL_CONTEXT']).read_text())
        assert seed['candidate']=='escape' and seed['evidence_file']!=str(old)
        assert c.env['KRT_INTERNAL_FINAL_CALL_CONTEXT']!=str(old)
        Path(seed['evidence_file']).write_text(json.dumps({'schema':1,'seed_attempts':[{'endpoint':seed['failures'][0]['endpoint'],'accepted_seed':accepted,'fresh_graph_sha256':'a'*64,'result':{'success':True,'segments':[{'layer':'F.Cu','width':.2}],'via':None}}]}))
        Path(record['output']).write_text('escape');Path(record['summary']).write_text('{}')
        actual_completed({'returncode':0,'files':{record['output']:file_hash(record['output']),record['summary']:file_hash(record['summary'])}})
    monkeypatch.setattr(pocket.ordinary_completed.backend,'_run_record',backend)
    def choose(*args,**kw):
        assert rig.budget.states==['completed','issued'] and kw=={'candidate_kind':'escape'}
        return {'selected':'escape'}
    monkeypatch.setattr(pocket.ordinary_selection,'choose',choose)
    _,_,evidence=pocket.run(rig.budget,rig.owner,rig.token,rig.work,nominal=nominal(rig))
    assert evidence['selection']['selected']==('escape' if accepted else 'legacy')
    assert len(calls)==1 and rig.budget.states==['completed','completed']
    assert old.read_text()=='immutable'
    with pytest.raises(AssertionError):
        pocket.run(rig.budget,rig.owner,rig.token,rig.work.parent/'third',nominal=nominal(rig))
    assert len(calls)==1

@pytest.mark.parametrize('change',['endpoint','width','bool_width','via','empty','duplicate'])
def test_accepted_seed_must_match_original_failure_and_nominal_geometry(rig,change):
    value=nominal(rig)
    attempt={'endpoint':value['failures'][0]['endpoint'],'accepted_seed':True,
             'fresh_graph_sha256':'a'*64,'result':{'success':True,
             'segments':[{'layer':'F.Cu','width':.2}],'via':None}}
    seed={'schema':1,'seed_attempts':[attempt]}
    if change=='endpoint':attempt['endpoint']={'net':'OTHER','ref':'J1','pad':'1'}
    elif change=='width':attempt['result']['segments'][0]['width']=.1
    elif change=='bool_width':attempt['result']['segments'][0]['width']=True
    elif change=='via':attempt['result']['via']={'size':.5,'drill':.3}
    elif change=='empty':attempt['result']['segments']=[]
    else:seed['seed_attempts'].append(attempt)
    with pytest.raises(ProofUnavailable):pocket._accepted_seed(seed,value)

from tests.test_issued_calls import issued,issue,finish
from tests.test_final_custody import context


def test_genuine_completed_call_summary_uses_detached_snapshot(issued,tmp_path):
    from placemat.kicad import replay_nominal
    token=issue(issued);record=finish(issued,token,tmp_path)
    assert record['summary'] not in record['raw']['files']
    assert replay_nominal.issued_calls.raw_summary_hash(record)==file_hash(record['summary'])
    Path(record['summary']).write_text('{}')
    with pytest.raises(ProofUnavailable,match='summary_changed'):
        replay_nominal.issued_calls.raw_summary_hash(record)


def test_duplicate_snapshot_basename_refuses(issued,tmp_path):
    from placemat.kicad import replay_nominal
    token=issue(issued);record=finish(issued,token,tmp_path)
    path=next(path for path in record['raw']['files'] if Path(path).name=='3-summary.json')
    duplicate=tmp_path/'duplicate'/Path(path).name;duplicate.parent.mkdir();duplicate.write_bytes(Path(path).read_bytes())
    record['raw']['files'][str(duplicate)]=file_hash(duplicate)
    with pytest.raises(ProofUnavailable,match='summary_snapshot_unproved'):
        replay_nominal.issued_calls.raw_summary_hash(record)


from tests.test_replay_budget import budget as real_budget,complete


def test_nominal_failed_pairs_require_actual_completed_template_seal(real_budget):
    from placemat.kicad import replay_nominal
    budget=real_budget[0]
    complete(real_budget)
    assert replay_nominal._failed_pairs(budget.grader)==set()
    budget.grader._template.final_judged[0][0]['joined']=False
    with pytest.raises(ProofUnavailable,match='grader_private_context_changed'):
        replay_nominal._failed_pairs(budget.grader)



def test_duplicate_nominal_epochs_use_same_first_seen_pad_as_backend(rig):
    from copy import deepcopy
    value=nominal(rig);first=value['failures'][0]
    later=deepcopy(first);later['endpoint']['physical_index']=9
    later['nominal_geometry']['via_size']=.8
    value['failures'].append(later)
    attempt={'endpoint':deepcopy(first['endpoint']),'accepted_seed':True,
             'fresh_graph_sha256':'a'*64,'result':{'success':True,'segments':[],
             'via':{'size':.6,'drill':.3}}}
    assert pocket._accepted_seed({'schema':1,'seed_attempts':[attempt]},value)
    attempt['endpoint']=later['endpoint']
    with pytest.raises(ProofUnavailable,match='identity_unproved'):
        pocket._accepted_seed({'schema':1,'seed_attempts':[attempt]},value)
