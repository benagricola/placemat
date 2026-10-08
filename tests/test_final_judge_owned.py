"""Actual owned launcher, controlled judgment producer; no native board proof."""
import json
from pathlib import Path
import subprocess
import sys
import time
import pytest
from placemat.checks import Verdict
from placemat.final_board import Judgement
from placemat.final_authority import RetainedAuthorityFactory
from placemat.kicad.final_call import ProofUnavailable
from placemat.kicad.final_owned_worker import _execute as actual_execute

from placemat import final_check_judgement as codec, final_judge_owned as owned, final_check_worker as worker

@pytest.fixture
def rig(tmp_path,monkeypatch):
    factory=object.__new__(RetainedAuthorityFactory)
    factory._deadline_utc=time.time()+10
    factory._critical={'measures':{'vias':0},'source':'retained source','fields':{'U1':{'Pm.I':'1A'}}}
    verified=[]
    monkeypatch.setattr(RetainedAuthorityFactory,'_verify',lambda self:verified.append(self))
    identity={'actual controlled source':'immutable-sha'}
    monkeypatch.setattr(owned,'_implementation',lambda:dict(identity))
    monkeypatch.setattr(worker,'_runtime_identity',lambda:dict(identity))
    judged=[]
    def judge(context,pcb):
        judged.append((context,pcb))
        assert context['fields']==factory._critical['fields']
        measures=dict(context['measures'],critical_checks=0,critical_unknown=[],findings={})
        return Judgement([Verdict('current-path','N',.3,'mm',.2,True)],[],[],measures)
    monkeypatch.setattr(worker,'judge',judge)
    pcb=tmp_path/'final.kicad_pcb';pcb.write_text('actual controlled saved copper')
    pcb.with_suffix('.kicad_pro').write_text('original rules')
    return factory,pcb,tmp_path/'owned',verified,judged


def producer(monkeypatch, mutate=None):
    def execute(argv,deadline,env):
        request=json.loads(Path(argv[-2]).read_text())
        response=worker.evaluate_critical(request)
        if mutate:mutate(response,request)
        Path(argv[-1]).write_text(json.dumps(response))
        return 0,'controlled child',''
    monkeypatch.setattr(owned,'_execute',execute)


def test_actual_quality_context_and_judgement_metrics_retained(rig,monkeypatch):
    producer(monkeypatch)
    factory,pcb,dest,verified,judged=rig
    result=owned.judge_owned(factory,pcb,{'vias':7,'length':23.5,'copper':3.,'findings':{}},dest)
    assert result.measures['vias']==7 and result.measures['length']==23.5
    assert len(verified)==2 and len(judged)==1
    assert factory._critical['measures']=={'vias':0}
    assert result.verdicts[0].severity==''
    assert json.loads((dest/'execution.json').read_text())['comparison_authority'] is False


@pytest.mark.parametrize('mode',['quality','runtime','bool-schema','fields','late','input'])
def test_bad_or_late_reply_never_becomes_result(rig,monkeypatch,mode):
    factory,pcb,dest,_,_=rig
    def mutate(response,request):
        if mode=='quality':
            decoded=codec.decode(response['judgement']);decoded.measures['vias']=True
            response['judgement']=codec.encode(decoded)
        elif mode=='runtime':response['implementation_end']={}
        elif mode=='bool-schema':response['schema']=True
        elif mode=='fields':response['extra']='unknown'
        elif mode=='late':factory._deadline_utc=0
        elif mode=='input':pcb.with_suffix('.kicad_pro').write_text('changed original rules')
    producer(monkeypatch,mutate)
    with pytest.raises(ProofUnavailable):owned.judge_owned(factory,pcb,{'vias':7},dest)
    assert not (dest/'execution.json').exists()


def test_blocked_actual_owned_child_stops_at_original_deadline(rig,monkeypatch):
    factory,pcb,dest,_,judged=rig;factory._deadline_utc=time.time()+.25
    def blocked(argv,deadline,env):
        return actual_execute([sys.executable,'-c','import time;print("owned-block",flush=True);time.sleep(60)'],deadline,env)
    monkeypatch.setattr(owned,'_execute',blocked)
    start=time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):owned.judge_owned(factory,pcb,{'vias':7},dest)
    assert time.monotonic()-start<3 and not judged
    assert 'owned-block' in (dest/'stdout.log').read_text()
    assert not (dest/'response.json').exists() and not (dest/'execution.json').exists()


def test_cancellation_propagates_without_result_or_second_worker(rig,monkeypatch):
    calls=[]
    def cancel(*args):calls.append(True);raise KeyboardInterrupt()
    monkeypatch.setattr(owned,'_execute',cancel)
    factory,pcb,dest,_,_=rig
    with pytest.raises(KeyboardInterrupt):owned.judge_owned(factory,pcb,{'vias':7},dest)
    assert len(calls)==1 and not (dest/'execution.json').exists()

@pytest.mark.parametrize('inherited',['earlier','nan','invalid'])
def test_inherited_scope_cannot_be_extended_or_spawn(rig,monkeypatch,inherited):
    factory,pcb,dest,_,_=rig
    value=str(factory._deadline_utc-1) if inherited=='earlier' else inherited
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC',value)
    monkeypatch.setattr(owned,'_execute',lambda *a:pytest.fail('unbound deadline spawned'))
    with pytest.raises(ProofUnavailable):owned.judge_owned(factory,pcb,{'vias':7},dest)
    assert not dest.exists()


def test_exact_decoded_reply_bytes_must_stay_unchanged(rig,monkeypatch):
    factory,pcb,dest,_,_=rig;producer(monkeypatch)
    original=owned._json
    def decode_then_change(raw):
        decoded=original(raw)
        (dest/'response.json').write_text('different bytes')
        return decoded
    monkeypatch.setattr(owned,'_json',decode_then_change)
    with pytest.raises(ProofUnavailable,match='reply_changed'):
        owned.judge_owned(factory,pcb,{'vias':7},dest)
    assert not (dest/'execution.json').exists()


def test_cancellation_stops_actual_owned_child_group(rig,monkeypatch):
    import os,signal,threading
    factory,pcb,dest,_,_=rig
    def blocked(argv,deadline,env):
        timer=threading.Timer(.15,lambda:os.kill(os.getpid(),signal.SIGINT))
        timer.start()
        try:
            return actual_execute([sys.executable,'-c','import time;time.sleep(60)'],deadline,env)
        finally:
            timer.cancel();timer.join()
    monkeypatch.setattr(owned,'_execute',blocked)
    start=time.monotonic()
    with pytest.raises(KeyboardInterrupt):owned.judge_owned(factory,pcb,{'vias':7},dest)
    assert time.monotonic()-start<3
    assert not (dest/'response.json').exists() and not (dest/'execution.json').exists()
