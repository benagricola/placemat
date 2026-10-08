import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

from placemat import ordinary_route_authority as ordinary
from placemat import route_execution_scope as scope


def invoke(*args, **kwargs):
    with ordinary.run(*args, **kwargs) as result:
        return result


def inputs():
    return SimpleNamespace(settings=SimpleNamespace(timeout_route=3600)), object(), {'original': 1}, Path('/original.kicad_pcb')


def test_missing_adapter_keeps_one_original_call_environment_and_options(monkeypatch):
    monkeypatch.setitem(sys.modules, 'placemat.final_authority', None)
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC', 'unchanged-original-value')
    calls = []
    def route(source, work, **options):
        calls.append((source, work, options, scope.os.environ['KRT_ROUTE_DEADLINE_UTC']))
        return 'original report'
    board, plan, measures, source = inputs()
    result = invoke(board, plan, measures, source, '/work', route, resume=True, exclude_nets={'X'})
    assert result.report == 'original report' and result.factory is None
    assert calls == [(source, '/work', {'resume': True, 'exclude_nets': {'X'}}, 'unchanged-original-value')]


def adapter(monkeypatch, retain):
    class Refused(ValueError):
        code, facts = 'unsupported', {}
    monkeypatch.setitem(sys.modules, 'placemat.final_authority', SimpleNamespace(AuthorityRefused=Refused, retain=retain))
    return Refused


def test_present_adapter_retains_exact_original_context_and_shared_deadline(monkeypatch):
    board, plan, measures, source = inputs()
    monkeypatch.setattr(scope.time, 'time', lambda: 100)
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC', '150')
    actual_scope = {'capture': {'path': '/original.capture'}, 'original_scope': True}
    monkeypatch.setattr(ordinary, 'invocation', lambda b, s, e, p, r: actual_scope)
    factory = object()
    retained, calls = [], []
    def retain(*args, **kwargs):
        retained.append((args, kwargs))
        return factory
    adapter(monkeypatch, retain)
    def route(s, w, **kwargs):
        calls.append((s, w, kwargs, scope.os.environ['KRT_ROUTE_DEADLINE_UTC']))
        return 'original report'
    result = invoke(board, plan, measures, source, '/work', route, exclude_nets={'X'}, pour_nets={'GND'})
    assert retained == [((board, plan, measures, source), {'invocation': actual_scope, 'deadline_utc': 150.0, 'context_files': ['/original.capture']})]
    assert calls == [(source, '/work', {'_authority_factory': factory, 'exclude_nets': {'X'}, 'pour_nets': {'GND'}}, '150.0')]
    assert result.factory is factory
    assert scope.os.environ['KRT_ROUTE_DEADLINE_UTC'] == '150'


def test_optional_preparation_refusal_restores_environment_before_original_call(monkeypatch):
    board, plan, measures, source = inputs()
    monkeypatch.setattr(scope.time, 'time', lambda: 100)
    monkeypatch.delenv('KRT_ROUTE_DEADLINE_UTC', raising=False)
    def refuse(*args):
        raise scope.ScopeUnavailable('scope unavailable', 'unavailable')
    monkeypatch.setattr(ordinary, 'invocation', refuse)
    adapter(monkeypatch, lambda *a, **k: pytest.fail('retained after refusal'))
    calls = []
    def route(*args, **kwargs):
        assert 'KRT_ROUTE_DEADLINE_UTC' not in scope.os.environ
        calls.append(kwargs)
        return 'ordinary'
    result = invoke(board, plan, measures, source, '/work', route)
    assert calls == [{}] and result.factory is None


def test_actual_route_error_or_cancellation_never_runs_second_ordinary_call(monkeypatch):
    board, plan, measures, source = inputs()
    monkeypatch.setattr(scope.time, 'time', lambda: 100)
    monkeypatch.delenv('KRT_ROUTE_DEADLINE_UTC', raising=False)
    monkeypatch.setattr(ordinary, 'invocation', lambda *a: {'capture': {'path': None}})
    adapter(monkeypatch, lambda *a, **k: object())
    calls = []
    def cancel(*args, **kwargs):
        calls.append(kwargs)
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        invoke(board, plan, measures, source, '/work', cancel)
    assert len(calls) == 1
    assert 'KRT_ROUTE_DEADLINE_UTC' not in scope.os.environ


def test_retained_deadline_stays_active_for_caller_final_checks(monkeypatch):
    board, plan, measures, source = inputs()
    monkeypatch.setattr(scope.time, 'time', lambda: 100)
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC', '150')
    monkeypatch.setattr(ordinary, 'invocation', lambda *a: {'capture': {'path': None}})
    adapter(monkeypatch, lambda *a, **k: object())
    with ordinary.run(board, plan, measures, source, '/work', lambda *a, **k: 'ordinary') as result:
        assert result.factory is not None
        # The caller's regrade/compare remains inside the exact same context.
        assert scope.os.environ['KRT_ROUTE_DEADLINE_UTC'] == '150.0'
    assert scope.os.environ['KRT_ROUTE_DEADLINE_UTC'] == '150'


def test_broken_present_adapter_dependency_is_not_disguised_as_absence(monkeypatch):
    import builtins
    board, plan, measures, source = inputs()
    original_import = builtins.__import__
    def broken(name, *args, **kwargs):
        if name == 'final_authority':
            raise ModuleNotFoundError('broken adapter dependency', name='broken_dependency')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', broken)
    with pytest.raises(ModuleNotFoundError, match='broken adapter'):
        with ordinary.run(board, plan, measures, source, '/work', lambda *a, **k: pytest.fail('unexpected launch')):
            pass


def test_actual_seam_verifies_adopted_report_before_yield_and_under_deadline(monkeypatch):
    from placemat.kicad import replay_finish as caller_finish
    board,plan,measures,source=inputs()
    monkeypatch.setattr(scope.time,'time',lambda:100)
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC','150')
    monkeypatch.setattr(ordinary,'invocation',lambda *a:{'capture':{'path':None}})
    factory=object();adapter(monkeypatch,lambda *a,**k:factory)
    verified=[]
    class Packet:
        def verify(self):
            assert scope.os.environ['KRT_ROUTE_DEADLINE_UTC']=='150.0'
            verified.append(True);return 'published report'
    def finish(actual_factory,report,work):
        assert actual_factory is factory and report=='incumbent report'
        return 'unverified alias',Packet()
    monkeypatch.setattr(caller_finish,'finish',finish)
    with ordinary.run(board,plan,measures,source,'/work',lambda *a,**k:'incumbent report') as result:
        assert verified==[True] and result.report=='published report'
    assert scope.os.environ['KRT_ROUTE_DEADLINE_UTC']=='150'


def test_actual_seam_current_loss_refusal_retains_ordinary_report(monkeypatch):
    from placemat.kicad import replay_finish as caller_finish
    from placemat.kicad.final_call import ProofUnavailable
    board,plan,measures,source=inputs()
    monkeypatch.setattr(scope.time,'time',lambda:100)
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC','150')
    monkeypatch.setattr(ordinary,'invocation',lambda *a:{'capture':{'path':None}})
    adapter(monkeypatch,lambda *a,**k:object())
    def refuse(*a):raise ProofUnavailable('replay_incumbent_current_join_lost')
    monkeypatch.setattr(caller_finish,'finish',refuse)
    result=invoke(board,plan,measures,source,'/work',lambda *a,**k:'ordinary report')
    assert result.report=='ordinary report' and result.unavailable['code']=='replay_incumbent_current_join_lost'
