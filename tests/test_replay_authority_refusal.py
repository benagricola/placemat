"""Real retained-factory refusal after ordinary output remains optional."""
import importlib.util,sys,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests.test_replay_ordinary_authority import inputs,scope
from placemat import ordinary_route_authority as module


@pytest.mark.parametrize('failure',['deadline','invocation'])
def test_actual_factory_refusal_preserves_completed_ordinary_report(monkeypatch,failure):
    authority=pytest.importorskip('placemat.final_authority')
    from placemat.kicad import replay_finish as caller_finish
    factory=object.__new__(authority.RetainedAuthorityFactory)
    factory._deadline_utc=time.time()-1 if failure=='deadline' else time.time()+120
    factory._invocation={'original':True};factory._invocation_sha=authority._digest(factory._invocation)
    if failure=='invocation':factory._invocation['original']=False
    monkeypatch.setattr(module,'invocation',lambda *a:{'capture':{'path':None}})
    monkeypatch.setattr(authority,'retain',lambda *a,**k:factory)
    def finish(actual,report,work):
        assert actual is factory and report=='completed ordinary report'
        actual.completed_authority()
        pytest.fail('actual invalid authority accepted')
    monkeypatch.setattr(caller_finish,'finish',finish)
    calls=[]
    def route(*a,**k):calls.append(k);return 'completed ordinary report'
    board,plan,measures,source=inputs()
    with module.run(board,plan,measures,source,'/work',route) as result:
        assert result.report=='completed ordinary report'
        assert result.unavailable['code']=='authority_deadline_or_invocation_changed'
    assert len(calls)==1


@pytest.mark.parametrize('failure',['cancel','timeout'])
def test_optional_finish_process_control_propagates_without_second_call(monkeypatch,failure):
    import subprocess
    authority=pytest.importorskip('placemat.final_authority')
    from placemat.kicad import replay_finish as caller_finish
    monkeypatch.setattr(module,'invocation',lambda *a:{'capture':{'path':None}})
    monkeypatch.setattr(authority,'retain',lambda *a,**k:object())
    error=KeyboardInterrupt() if failure=='cancel' else subprocess.TimeoutExpired(['owned-worker'],1)
    def stop(*a):raise error
    monkeypatch.setattr(caller_finish,'finish',stop)
    calls=[]
    def route(*a,**k):calls.append(k);return 'completed report'
    board,plan,measures,source=inputs()
    with pytest.raises(type(error)):
        with module.run(board,plan,measures,source,'/work',route):pass
    assert len(calls)==1
