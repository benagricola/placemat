"""The routed board is finished under the source board's rules, and every phase is judged again on it."""
from types import SimpleNamespace
import json

import pytest

from placemat.kicad import phase_run, route, route_cleanup


def test_the_routed_board_takes_the_source_rules_then_guards_fill_cleanup_and_drc(tmp_path, monkeypatch):
    raw, given, rules, output = [tmp_path / (name + '.kicad_pcb') for name in ('raw', 'given', 'rules', 'output')]
    raw.write_text('routed copper')
    given.write_text('fixed input copper')
    rules.with_suffix('.kicad_pro').write_text('source rules')
    output.with_suffix('.kicad_pro').write_text('old rules')
    output.with_suffix('.kicad_dru').write_text('old custom rules')
    order = []
    def observe(name):
        def run(path):
            assert output.read_text() == 'routed copper'
            assert output.with_suffix('.kicad_pro').read_text() == 'source rules'
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
    assert raw.read_text() == 'routed copper' and given.read_text() == 'fixed input copper'


def test_every_phase_is_judged_again_and_a_second_judging_starts_afresh(monkeypatch):
    report = SimpleNamespace(phases=[{'connections': []}, {'connections': []}], widths_failed=0)
    phases = [SimpleNamespace(name='earlier'), SimpleNamespace(name='last')]
    obs = [[{'net': 'EARLIER', 'from': {'ref': 'U1'}, 'to': {'ref': 'U2'}}],
           [{'net': 'LAST', 'from': {'ref': 'U3'}, 'to': {'ref': 'U4'}}]]
    seen = []
    def judge(pcb, asked, drc, neck, real, baseline=None):
        seen.append(asked)
        return [{'joined': True, 'under': {}, 'violated': False, 'width_unknown': asked[0]['net'] == 'EARLIER'}]
    monkeypatch.setattr(phase_run, 'judge_obligations', judge)
    monkeypatch.setattr(phase_run, 'phase_neck', lambda cfg, phase: None)
    monkeypatch.setattr(phase_run, 'phase_input_drc', lambda work, index: None)
    route.recheck_final_phases(report, obs, phases, {'policies': []}, 'routed', 'drc',
                               SimpleNamespace(is_real=lambda _: True, is_real_kind=lambda _: True), None)
    assert seen == obs and report.asked == obs
    assert report.widths_failed == 1
    assert report.phases[0]['final_open'][0]['width_unknown'] is True
    assert report.phases[0]['final_connected'] == 1
    assert report.phases[0]['final_width_known_under'] == 0
    assert report.phases[0]['final_width_unknown'] == 1
    assert report.phases[0]['final_closure_clean'] == 0
    assert report.phases[1]['final_closure_clean'] == 1
    # judging again counts from zero, not on top of the first count
    route.recheck_final_phases(report, obs, phases, {'policies': []}, 'routed2', 'drc2',
                               SimpleNamespace(is_real=lambda _: True, is_real_kind=lambda _: True), None)
    assert report.widths_failed == 1


def test_phase_and_obligation_counts_must_match():
    with pytest.raises(ValueError, match='count mismatch'):
        route.recheck_final_phases(SimpleNamespace(phases=[]), [[]], [], {}, None, None, None, None)


def test_a_judgment_shorter_than_its_obligations_is_refused(monkeypatch):
    monkeypatch.setattr(phase_run, 'judge_obligations', lambda *args: [])
    monkeypatch.setattr(phase_run, 'phase_neck', lambda *args: None)
    with pytest.raises(ValueError, match='judgment/obligation count mismatch'):
        route.recheck_final_phases(SimpleNamespace(phases=[{}]), [[{'net': 'N'}]],
                                  [SimpleNamespace(name='n')], {'policies': []}, None, None,
                                  SimpleNamespace(is_real=lambda _: True, is_real_kind=lambda _: True), None)


def test_final_connected_and_width_evidence_counts_are_distinct_from_clean(monkeypatch):
    import placemat.kicad.phase_run as phase_run
    judged = [{'joined': True, 'under': {'F.Cu': 0.1}, 'violated': False, 'width_unknown': True},
              {'joined': True, 'under': {}, 'violated': False, 'width_unknown': False},
              {'joined': False, 'under': {}, 'violated': False, 'width_unknown': False}]
    asked = [[{'net': 'N', 'from': {'ref': 'A', 'pad': str(i)}, 'to': {'ref': 'B', 'pad': str(i)},
               'widths': {'F.Cu': 0.2}} for i in range(3)]]
    monkeypatch.setattr(phase_run, 'judge_obligations', lambda *args: judged)
    monkeypatch.setattr(phase_run, 'phase_neck', lambda *args: None)
    monkeypatch.setattr(phase_run, 'phase_input_drc', lambda work, index: None)
    report = SimpleNamespace(phases=[{'name': 'signals', 'connections': []}], final_judged=[], widths_failed=0)
    route.recheck_final_phases(report, asked, [SimpleNamespace(name='signals')], {'policies': []},
                              'routed', 'drc', SimpleNamespace(is_real=lambda _: True, is_real_kind=lambda _: True), None)
    phase = report.phases[0]
    assert (phase['final_connected'], phase['final_joined']) == (2, 1)
    assert (phase['final_width_known_under'], phase['final_width_unknown']) == (1, 1)


@pytest.mark.parametrize("copy", [route.copy_source_rules, route._copy_project])
def test_a_reused_work_folder_keeps_no_rules_the_source_lacks(tmp_path, copy):
    source, owned = tmp_path / 'source.kicad_pcb', tmp_path / 'in.kicad_pcb'
    source.with_suffix('.kicad_pro').write_text('source project')
    owned.with_suffix('.kicad_pro').write_text('old project')
    owned.with_suffix('.kicad_dru').write_text('old custom rules')
    copy(source, owned)
    assert owned.with_suffix('.kicad_pro').read_text() == 'source project'
    assert not owned.with_suffix('.kicad_dru').exists()
    assert source.with_suffix('.kicad_pro').read_text() == 'source project'
    source.with_suffix('.kicad_pro').unlink()
    copy(source, owned)
    assert not owned.with_suffix('.kicad_pro').exists()
