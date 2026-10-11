"""The routed board is finished under the source board's rules, and every phase is judged again on it."""
from types import SimpleNamespace
import json

import pytest

from placemat.kicad import phase_run, route, route_cleanup


def test_finalize_private_copy_restores_original_rules_and_cleanup_boundary(tmp_path, monkeypatch):
    raw, given, rules, output = [tmp_path / (name + '.kicad_pcb') for name in ('raw', 'given', 'rules', 'output')]
    raw.write_text('candidate copper')
    given.write_text('fixed input copper')
    rules.with_suffix('.kicad_pro').write_text('original manufacturing rules')
    output.with_suffix('.kicad_pro').write_text('weakened candidate rules')
    output.with_suffix('.kicad_dru').write_text('stale candidate custom rules')
    order = []
    def observe(name):
        def run(path):
            assert output.read_text() == 'candidate copper'
            assert output.with_suffix('.kicad_pro').read_text() == 'original manufacturing rules'
            assert not output.with_suffix('.kicad_dru').exists()
            order.append(name)
        return run
    monkeypatch.setattr(route, 'remove_guards', observe('guards'))
    monkeypatch.setattr(route, 'fill_zones', observe('fill'))
    cleanup, drc = object(), object()
    def clean(path, original):
        assert path == str(output) and original == str(given)
        order.append('cleanup')
        return cleanup
    def grade(path, drc_path, refill_zones):
        assert path == output and not refill_zones
        order.append('drc')
        return drc
    monkeypatch.setattr(route_cleanup, 'remove_dangling_router_copper', clean)
    monkeypatch.setattr(route, 'run_drc', grade)
    assert route.finalize_copper(raw, output, given, rules, tmp_path / 'drc.json') == (cleanup, drc)
    assert order == ['guards', 'fill', 'cleanup', 'drc']
    assert raw.read_text() == 'candidate copper' and given.read_text() == 'fixed input copper'


def test_final_recheck_retains_earlier_obligations_and_clears_stale_success(monkeypatch):
    report = SimpleNamespace(phases=[{'connections': []}, {'connections': []}], widths_failed=0)
    phases = [SimpleNamespace(name='earlier'), SimpleNamespace(name='last')]
    obs = [[{'net': 'EARLIER', 'from': {'ref': 'U1'}, 'to': {'ref': 'U2'}}],
           [{'net': 'LAST', 'from': {'ref': 'U3'}, 'to': {'ref': 'U4'}}]]
    seen = []
    def judge(pcb, asked, drc, neck, real):
        seen.append(asked)
        return [{'joined': True, 'under': {}, 'violated': False, 'width_unknown': asked[0]['net'] == 'EARLIER'}]
    monkeypatch.setattr(phase_run, 'judge_obligations', judge)
    monkeypatch.setattr(phase_run, 'phase_neck', lambda cfg, phase: None)
    monkeypatch.setattr(phase_run, 'comparison_contract', lambda phase, asked: phase.name)
    route.recheck_final_phases(report, obs, phases, {'policies': []}, 'candidate', 'drc',
                               SimpleNamespace(is_real=lambda _: True), None)
    assert seen == obs and report.asked == obs and report.asked is not obs
    assert report.widths_failed == 1
    assert report.phases[0]['final_open'][0]['width_unknown'] is True
    assert report.phases[0]['final_connected'] == 1
    assert report.phases[0]['final_width_known_under'] == 0
    assert report.phases[0]['final_width_unknown'] == 1
    assert report.phases[0]['final_closure_clean'] == 0
    assert report.phases[1]['final_closure_clean'] == 1
    # A second candidate is rejudged, rather than accumulating the first candidate's failures.
    route.recheck_final_phases(report, obs, phases, {'policies': []}, 'candidate2', 'drc2',
                               SimpleNamespace(is_real=lambda _: True), None)
    assert report.widths_failed == 1


def test_mismatched_final_contract_cannot_zip_truncate():
    with pytest.raises(ValueError, match='count mismatch'):
        route.recheck_final_phases(SimpleNamespace(phases=[]), [[]], [], {}, None, None, None, None)


def test_candidate_phase_recheck_does_not_mutate_incumbent_records(monkeypatch):
    incumbent = {'connections': [], 'final_closure_clean': 1.0, 'final_open': []}
    candidate = SimpleNamespace(phases=[incumbent], widths_failed=0)
    monkeypatch.setattr(phase_run, 'judge_obligations', lambda *args: [
        {'joined': False, 'under': {}, 'violated': False}])
    monkeypatch.setattr(phase_run, 'phase_neck', lambda *args: None)
    monkeypatch.setattr(phase_run, 'comparison_contract', lambda *args: 'frozen')
    obs = [[{'net': 'N', 'from': {'ref': 'U1'}, 'to': {'ref': 'U2'}}]]
    route.recheck_final_phases(candidate, obs, [SimpleNamespace(name='n')], {'policies': []},
                               None, None, SimpleNamespace(is_real=lambda _: True), None)
    assert candidate.phases[0]['final_closure_clean'] == 0
    assert incumbent['final_closure_clean'] == 1 and incumbent['final_open'] == []


def test_truncated_actual_judgment_cannot_certify_final_board(monkeypatch):
    monkeypatch.setattr(phase_run, 'judge_obligations', lambda *args: [])
    monkeypatch.setattr(phase_run, 'phase_neck', lambda *args: None)
    monkeypatch.setattr(phase_run, 'comparison_contract', lambda *args: 'frozen')
    with pytest.raises(ValueError, match='judgment/obligation count mismatch'):
        route.recheck_final_phases(SimpleNamespace(phases=[{}]), [[{'net': 'N'}]],
                                  [SimpleNamespace(name='n')], {'policies': []}, None, None,
                                  SimpleNamespace(is_real=lambda _: True), None)


def test_final_connected_and_width_evidence_counts_are_distinct_from_clean(monkeypatch):
    import placemat.kicad.phase_run as phase_run
    judged = [{'joined': True, 'under': {'F.Cu': 0.1}, 'violated': False, 'width_unknown': True},
              {'joined': True, 'under': {}, 'violated': False, 'width_unknown': False},
              {'joined': False, 'under': {}, 'violated': False, 'width_unknown': False}]
    asked = [[{'net': 'N', 'from': {'ref': 'A', 'pad': str(i)}, 'to': {'ref': 'B', 'pad': str(i)},
               'widths': {'F.Cu': 0.2}} for i in range(3)]]
    monkeypatch.setattr(phase_run, 'judge_obligations', lambda *args: judged)
    monkeypatch.setattr(phase_run, 'phase_neck', lambda *args: None)
    monkeypatch.setattr(phase_run, 'comparison_contract', lambda *args: 'contract')
    report = SimpleNamespace(phases=[{'name': 'signals', 'connections': []}], final_judged=[], widths_failed=0)
    route.recheck_final_phases(report, asked, [SimpleNamespace(name='signals')], {'policies': []},
                              'candidate', 'drc', SimpleNamespace(is_real=lambda _: True), None)
    phase = report.phases[0]
    assert (phase['final_connected'], phase['final_joined']) == (2, 1)
    assert (phase['final_width_known_under'], phase['final_width_unknown']) == (1, 1)


@pytest.mark.parametrize("copy", [route.copy_source_rules, route._copy_project])
def test_reused_work_companions_cannot_inherit_absent_source_rules(tmp_path, copy):
    source, owned = tmp_path / 'source.kicad_pcb', tmp_path / 'in.kicad_pcb'
    source.with_suffix('.kicad_pro').write_text('current original project')
    owned.with_suffix('.kicad_pro').write_text('old project')
    owned.with_suffix('.kicad_dru').write_text('old foreign custom rules')
    copy(source, owned)
    assert owned.with_suffix('.kicad_pro').read_text() == 'current original project'
    assert not owned.with_suffix('.kicad_dru').exists()
    assert source.with_suffix('.kicad_pro').read_text() == 'current original project'
    source.with_suffix('.kicad_pro').unlink()
    copy(source, owned)
    assert not owned.with_suffix('.kicad_pro').exists()
