"""Execute the actual patched runner route branch with controlled dependencies.

This is a source-site control, not a native board or KRT routing proof.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import time
import pytest

from tests.test_replay_ordinary_authority import ordinary,scope,adapter


@pytest.mark.parametrize("mode",["ordinary","published","refused"])
def test_actual_runner_route_branch_retains_original_context_through_final_judge(tmp_path, monkeypatch,mode):
    adopted=mode=="published"
    from placemat.kicad import route
    from placemat import preview_json, checks
    import sys
    import inspect
    from placemat import runner
    source=inspect.getsource(runner)
    tree = ast.parse(source)
    branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                  and isinstance(node.test, ast.Name) and node.test.id == 'route'
                  and any(isinstance(child, ast.Name) and child.id == 'route_authority_stack'
                          for child in ast.walk(node)))
    # Exact existing runner body, including the existing final-check block.
    module = ast.fix_missing_locations(ast.Module(body=[branch], type_ignores=[]))
    original_measures = {'vias': 0}
    board = SimpleNamespace(settings=SimpleNamespace(timeout_route=3600))
    plan = SimpleNamespace(plane_nets={'GND'}, findings=[])
    pcb = tmp_path / 'original.kicad_pcb'
    factory, retained, routed, judged = object(), [], [], []
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC', str(time.time() + 120))
    expected_deadline = float(scope.os.environ['KRT_ROUTE_DEADLINE_UTC'])
    monkeypatch.setattr(ordinary, 'invocation', lambda *a: {'capture': {'path': None}})
    def retain(*args, **kwargs):
        retained.append((args, kwargs))
        return factory
    adapter(monkeypatch, retain)
    report = SimpleNamespace(resumed=[], as_dict=lambda: {}, closure_clean=1,
                             routed_pcb=tmp_path / 'routed.kicad_pcb', summary=lambda: 'done',
                             phases=[], phases_without_copper=[], keepout_breaches=[],
                             has_findings=lambda: False, open_nets={})
    selected=report
    verified=[]
    if adopted:
        from placemat.kicad import replay_finish as caller_finish
        from copy import copy
        selected=copy(report);selected.routed_pcb=tmp_path/'published'/'board.kicad_pcb'
        def serialize():
            assert verified
            return {'pcb':str(selected.routed_pcb)}
        selected.as_dict=serialize
        class Packet:
            def verify(self):verified.append(True);return selected
        monkeypatch.setattr(caller_finish,'finish',lambda *a:(selected,Packet()))
    if mode=='refused':
        from placemat.kicad import replay_finish as caller_finish
        from placemat.kicad.final_call import ProofUnavailable
        def refuse(*a):raise ProofUnavailable('replay_incumbent_current_join_lost',phase=0)
        monkeypatch.setattr(caller_finish,'finish',refuse)
    def route_board(source, work, **kwargs):
        routed.append((source, work, kwargs))
        assert kwargs['_authority_factory'] is factory
        return report
    monkeypatch.setattr(route, 'route_board', route_board)
    quality_inputs=[]
    def quality(pcb):
        quality_inputs.append(pcb)
        if adopted:assert verified
        return {'vias':0}
    monkeypatch.setattr(route,'routed_quality',quality,raising=False)
    monkeypatch.setattr(route, 'phase_lines', lambda *a: [])
    monkeypatch.setattr(preview_json, 'declared_sites', lambda *a: [])
    monkeypatch.setattr(preview_json, 'plan_json', lambda *a: {})
    monkeypatch.setattr(checks, 'record', lambda *a: [])
    def judge(actual_board, actual_plan, actual_pcb, measures):
        assert float(scope.os.environ['KRT_ROUTE_DEADLINE_UTC']) == expected_deadline
        judged.append((actual_board, actual_plan, actual_pcb))
        return SimpleNamespace(measures=measures, evidence=lambda: {}, verdicts=[], outcomes=[], findings=[])
    monkeypatch.setitem(sys.modules, 'placemat.final_board', SimpleNamespace(judge=judge))
    namespace = {'__package__': 'placemat', 'route': True, 'board': board, 'plan': plan,
                 'metrics': {'measures': original_measures}, 'src': SimpleNamespace(pcb=pcb),
                 'run_dir': tmp_path, 'route_exclude': {'X'}, 'route_quick': False,
                 'resume': False, 'rec': SimpleNamespace(run_id='original', timing_s={}, verdicts=[], acceptances=[]),
                 'script': tmp_path / 'intent.py', 'say': lambda *a, **k: None,
                 'console': SimpleNamespace(finding=lambda *a: None), 'time': time, 'json': __import__('json'),
                 'checks': checks, 'stale': [], 'suggestions_mod': SimpleNamespace(bind=lambda *a: None)}
    exec(compile(module, 'actual-runner-route-branch', 'exec'), namespace)
    assert len(retained)==len(routed)==1
    integrated_final='from .final_board import judge' in source
    assert len(judged)==int(integrated_final)
    assert retained[0][0] == (board, plan, original_measures, pcb)
    assert retained[0][1]['deadline_utc'] == expected_deadline
    if integrated_final:assert judged==[(board,plan,selected.routed_pcb)]
    if 'routed_quality(' in source:assert quality_inputs==[selected.routed_pcb]
    assert namespace['metrics']['route']==selected.as_dict()
    if adopted:assert verified
    if mode=='refused':assert namespace['metrics']['route_optional']=={'code':'replay_incumbent_current_join_lost','facts':{'phase':0}}

