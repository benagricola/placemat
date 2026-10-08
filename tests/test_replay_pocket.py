"""Actual sole-pocket callback with controlled native/router boundaries."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from placemat.kicad import replay_pocket as pocket
from placemat.kicad.final_call import ProofUnavailable,file_hash


@pytest.fixture
def rig(tmp_path,monkeypatch):
    import shutil
    root=tmp_path/'router';root.mkdir()
    helper=root/'route_candidates.py'
    shutil.copyfile(Path(__file__).parent/'fixtures'/'replay_backend'/'ordinary_grade.py',helper)
    ctx=SimpleNamespace(router_dir=helper.parent,script='route.py',env={},execution=None)
    # replace() requires the actual ctx's dataclass shape; keep this boundary controlled.
    monkeypatch.setattr(pocket,'replace',lambda obj,**kw:SimpleNamespace(**(vars(obj)|kw)))
    token=object();executor=object();states=['completed','unused'];processes=[]
    original={'identity':{'kind':'single'},'input':str(tmp_path/'original.kicad_pcb'),'raw':{'summary':{'regrade':{},'open_single':['A']}},'command':['controlled']}
    Path(original['input']).write_text('original')
    ctx.router_dir=helper.parent
    monkeypatch.setattr(pocket.ordinary_completed.backend,'_runtime',lambda *a:({str(helper):file_hash(helper)},None,None))
    monkeypatch.setattr(pocket.issued_calls,'completed_record',lambda *a:original)
    monkeypatch.setattr(pocket.candidate_calls,'_candidate_record',lambda orig,c,g,o,s:{'output':str(o),'summary':str(s)})
    def restore(b,orig,c,stage,current,given,output,work):
        work.mkdir(exist_ok=True)
        if stage=='prepare':given.write_text(Path(current).read_text())
        return {}
    monkeypatch.setattr(pocket.restore_owned,'run',restore)
    def backend(record,deadline,c,log,validate,actual_completed):
        processes.append('pocket');validate()
        Path(record['output']).write_text('pocket');Path(record['summary']).write_text('{}')
        actual_completed({'returncode':0,'files':{record['output']:file_hash(record['output']),record['summary']:file_hash(record['summary'])}})
        raise ProofUnavailable('replay_backend_policy_malformed')
    monkeypatch.setattr(pocket.ordinary_completed.backend,'_run_record',backend)
    def files(path):return {str(path):file_hash(path)}
    monkeypatch.setattr(pocket.issued_calls,'_files',files)
    def snapshot(values,dest):
        dest.mkdir();result={}
        for i,(name,sha) in enumerate(values.items()):
            out=dest/(str(i)+'-'+Path(name).name);out.write_bytes(Path(name).read_bytes());result[str(out)]=sha
        return result
    monkeypatch.setattr(pocket.issued_calls,'_snapshot',snapshot)
    def replay(executor,operation):
        assert states==['completed','unused'];states[1]='issued'
        try:result=operation(123.)
        except BaseException:states[1]='cancelled';raise
        states[1]='completed';return result
    budget=SimpleNamespace(grader=object(),ledger=object(),executor=executor,deadline=123.,states=states,_check=lambda e:None,run_replay=replay)
    owner=SimpleNamespace(final_call=token,contexts_for=lambda b:{token:ctx},backend_capability={'sources':{str(helper):file_hash(helper)}})
    return SimpleNamespace(budget=budget,owner=owner,token=token,original=original,processes=processes,work=tmp_path/'pocket')


def test_missing_policy_uses_one_slot_and_comparator_inside_slot(rig,monkeypatch):
    def choose(b,*args):
        assert b.states==['completed','issued'];return {'selected':'pocket'}
    monkeypatch.setattr(pocket.ordinary_selection,'choose',choose)
    output,receipt,evidence=pocket.run(rig.budget,rig.owner,rig.token,rig.work)
    assert output.read_text()=='pocket' and rig.processes==['pocket']
    assert rig.budget.states==['completed','completed']
    assert evidence['selection']['selected']=='pocket' and not evidence['policy_proved']


@pytest.mark.parametrize('summary',[{}, {'status':'already_connected'}, {'regrade':{}}])
def test_original_complete_or_unmeasured_keeps_second_slot_unused(rig,summary,monkeypatch):
    rig.original['raw']['summary']=summary
    monkeypatch.setattr(pocket.ordinary_selection,'choose',lambda *a:pytest.fail('no comparator'))
    assert pocket.run(rig.budget,rig.owner,rig.token,rig.work)[0] is None
    assert rig.budget.states==['completed','unused'] and not rig.processes


def test_comparator_cancellation_consumes_without_third_route(rig,monkeypatch):
    def stopped(*a):raise KeyboardInterrupt
    monkeypatch.setattr(pocket.ordinary_selection,'choose',stopped)
    with pytest.raises(KeyboardInterrupt):pocket.run(rig.budget,rig.owner,rig.token,rig.work)
    assert rig.budget.states==['completed','cancelled'] and rig.processes==['pocket']

from tests.test_replay_budget import budget as real_budget, complete
from tests.test_final_custody import context


def test_actual_private_budget_fallback_consumption_blocks_replay_and_repeat(rig,real_budget,monkeypatch):
    value,executor,*_=real_budget
    # Complete and seal the real original registry before replacing controlled
    # router/native boundaries for this callback. No separate attempt counter.
    complete(real_budget)
    rig.budget=value
    def choose(b,*args):
        assert b is value and b.states==['completed','issued']
        return {'selected':'legacy'}
    monkeypatch.setattr(pocket.ordinary_selection,'choose',choose)
    pocket.run(value,rig.owner,rig.token,rig.work)
    assert value.states==['completed','completed'] and rig.processes==['pocket']
    with pytest.raises(ProofUnavailable,match='already_issued'):
        value.run_replay(executor,lambda _:pytest.fail('strict replay after fallback'))
    with pytest.raises(ProofUnavailable):
        pocket.run(value,rig.owner,rig.token,rig.work.parent/'another')
    assert rig.processes==['pocket']


def test_actual_private_budget_replay_consumption_blocks_fallback(rig,real_budget):
    value,executor,*_=real_budget;complete(real_budget)
    value.run_replay(executor,lambda _: {'returncode':0,'proposals':1,'files':dict(real_budget[-1])})
    with pytest.raises(ProofUnavailable,match='already_issued'):
        pocket.run(value,rig.owner,rig.token,rig.work)
    assert not rig.processes and value.states==['completed','completed']
