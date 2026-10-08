"""Both final-board candidates use source rules and the same frozen phase contract."""
from types import SimpleNamespace
import json

import pytest

from placemat.kicad import phase_run, route, route_cleanup


def test_retained_invocation_and_actual_width_receipt_are_bound(tmp_path):
    from placemat.kicad.final_call import ProofUnavailable
    from placemat.kicad.final_route import FinalCopperGrader
    from placemat.settings import Settings
    original, baseline, receipt = [tmp_path / name for name in ('source.kicad_pcb', 'drc.json', 'width.json')]
    original.write_text('source')
    original.with_suffix('.kicad_pro').write_text('rules')
    baseline.write_text('{}')
    widths = {'policies': []}
    receipt.write_text(json.dumps(widths))
    invocation = {'layers': ['F.Cu'], 'exclude_nets': ['EXCLUDED'], 'pour_nets': [],
                  'upto': None, 'only': False, 'capture_path': None}
    grader = FinalCopperGrader(original=original, cleanup_input=original, rules=original,
                              baseline_drc=baseline, obligations=[], phases=[], width_receipt=widths,
                              cfg=Settings(), counted={'EXCLUDED'}, open_before={}, chosen_pours=set(),
                              invocation=invocation, width_receipt_path=receipt)
    invocation['exclude_nets'].clear()
    bound = grader.binding()
    assert bound['contract']['invocation']['exclude_nets'] == ['EXCLUDED']
    assert bound['paths']['width_receipt'] == str(receipt)
    assert bound['contract']['width_receipt_sha256']
    receipt.write_text('{"policies": [{"name": "changed"}]}')
    with pytest.raises(ProofUnavailable, match='original_grading_input_changed'):
        grader.binding()


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


def test_retained_grader_snapshots_contract_and_reports_each_private_candidate(tmp_path, monkeypatch):
    from placemat.kicad.final_route import FinalCopperGrader
    from placemat.route_phase import Phase
    from placemat.settings import Settings
    original, raw, rules, baseline = [tmp_path / name for name in ('original.kicad_pcb', 'raw.kicad_pcb',
                                                                 'rules.kicad_pcb', 'baseline.json')]
    original.write_text('fixed copper')
    raw.write_text('candidate')
    rules.with_suffix('.kicad_pro').write_text('original rules')
    baseline.write_text('{}')
    template = route.RouteReport(True, 0, 0, 1, 1, {'N': 1}, [], [], ['F.Cu'], 1, 'router', {},
                                 raw, baseline, tmp_path, phases=[{'name': 'last', 'connections': []}])
    obligations, policy = [[]], {'policies': []}
    def finalize(source, output, fixed, source_rules, drc_path):
        assert fixed == original
        output.write_bytes(source.read_bytes())
        output.with_suffix('.kicad_pro').write_bytes(source_rules.with_suffix('.kicad_pro').read_bytes())
        drc_path.write_text('{"violations": []}')
        return SimpleNamespace(record=lambda: {}), SimpleNamespace(open_nets={}, by_type={}, is_real=lambda _: True)
    monkeypatch.setattr(route, 'finalize_copper', finalize)
    monkeypatch.setattr(route, '_violations_by_net', lambda _: {})
    monkeypatch.setattr(route, 'router_breaches', lambda *args: [])
    monkeypatch.setattr(route, 'new_error_count', lambda *args: 0)
    monkeypatch.setattr(route, 'routed_copper', lambda *args: (1, 2., 3))
    monkeypatch.setattr(phase_run, 'judge_obligations', lambda *args: [])
    monkeypatch.setattr(phase_run, 'phase_neck', lambda *args: None)
    grader = FinalCopperGrader(original=original, cleanup_input=original, rules=rules, baseline_drc=baseline,
                              obligations=obligations, phases=[Phase('last', 'rest')], width_receipt=policy,
                              cfg=Settings(), counted=set(), open_before={'N': 1}, chosen_pours=set())
    from placemat.kicad.final_call import ProofUnavailable
    with pytest.raises(ProofUnavailable, match='completed_incumbent_unavailable'):
        grader.regrade(raw, tmp_path / 'premature')
    assert not (tmp_path / 'premature').exists()
    with pytest.raises(ProofUnavailable, match='execution_contract_mismatch'):
        grader.bind_execution(template)
    template.asked = [[]]
    grader.bind_execution(template)
    with pytest.raises(ProofUnavailable, match='execution_already_bound'):
        grader.bind_execution(template)
    binding = grader.binding()
    binding['contract']['obligations'].append([{'net': 'UNTRUSTED'}])
    assert grader.binding()['contract']['obligations'] == [[]]
    obligations[0].append({'net': 'UNTRUSTED'})
    policy['policies'].append({'name': 'UNTRUSTED'})
    template.phases[0]['name'] = 'mutated caller report'
    first = grader.regrade(raw, tmp_path / 'first')
    second = grader.regrade(raw, tmp_path / 'second')
    assert grader.verify(first) == first.receipt
    assert grader.verify(second) == second.receipt
    # These private measurements are deliberately absent from public as_dict.
    # Changing them must still invalidate authority before a final adapter reads them.
    original_public = first.report.as_dict()
    from copy import deepcopy
    for name, replacement in (('asked', [[{'net': 'FORGED'}]]),
                              ('final_judged', [[{'joined': True, 'width_unknown': False}]])):
        original_value = deepcopy(getattr(first.report, name))
        setattr(first.report, name, replacement)
        assert first.report.as_dict() == original_public
        with pytest.raises(ProofUnavailable, match='physical_grade_report_changed'):
            grader.verify(first)
        setattr(first.report, name, original_value)
        assert grader.verify(first) == first.receipt
    evidence = tmp_path / 'first/physical_grade.json'
    evidence_bytes = evidence.read_bytes()
    evidence.write_text('{}')
    from placemat.kicad.final_call import ProofUnavailable
    with pytest.raises(ProofUnavailable, match='physical_grade_evidence_changed'):
        grader.verify(first)
    evidence.write_bytes(evidence_bytes)
    second.report.phases[0]['final_closure_clean'] = 0
    from placemat.kicad.final_call import ProofUnavailable
    with pytest.raises(ProofUnavailable, match='physical_grade_report_changed'):
        grader.verify(second)
    first.receipt['contract_sha256'] = '0' * 64
    with pytest.raises(ProofUnavailable, match='physical_grade_receipt_changed'):
        grader.verify(first)
    assert first.report.phases[0]['name'] == 'last'
    assert first.report.phases[0]['final_closure_clean'] == 1
    assert first.report.asked == [[]] and first.report.drc_new == 0
    assert first.receipt['outputs']['route.json']
    assert first.receipt['full_standing'] == 'requires_retained_integrated_adapter'
    assert (tmp_path / 'first/routed.kicad_pro').read_text() == 'original rules'
    rules.with_suffix('.kicad_pro').write_text('weakened rules')
    from placemat.kicad.final_call import ProofUnavailable
    with pytest.raises(ProofUnavailable, match='original_grading_input_changed'):
        grader.regrade(raw, tmp_path / 'third')
    assert not (tmp_path / 'third').exists()


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

@pytest.mark.parametrize('fails', [False, True])
def test_retained_physical_settings_drive_real_drc_parser_and_restore_caller(tmp_path, monkeypatch, fails):
    from placemat.kicad.final_route import FinalCopperGrader
    from placemat.kicad import drc
    from pathlib import Path
    from placemat.settings import Settings, active, bind
    original, raw, rules, baseline = [tmp_path / name for name in
        ('original.kicad_pcb', 'raw.kicad_pcb', 'rules.kicad_pcb', 'baseline.json')]
    original.write_text('fixed copper'); raw.write_text('candidate')
    rules.with_suffix('.kicad_pro').write_text('original rules')
    baseline.write_text('{"violations": []}')
    template = route.RouteReport(True, 0, 0, 1, 1, {}, [], [], ['F.Cu'], 1, 'router', {},
                                 raw, baseline, tmp_path, phases=[], asked=[])
    retained = Settings(drc_refill_zones=False, drc_real_kinds=('proof_issue',),
                        drc_outstanding_kinds=('proof_issue',))
    grader = FinalCopperGrader(original=original, cleanup_input=original, rules=rules,
        baseline_drc=baseline, obligations=[], phases=[], width_receipt={'policies': []},
        cfg=retained, counted=set(), open_before={}, chosen_pours=set(), template=template)
    calls = []
    def subprocess_drc(cmd, **kwargs):
        # The stand-in consumes the actual issued refill policy. The real DRC
        # parser then classifies the result under the retained original kinds.
        calls.append(cmd)
        kind = 'wrong_refill_policy' if '--refill-zones' in cmd else 'proof_issue'
        out = Path(cmd[cmd.index('--output') + 1])
        out.write_text(json.dumps({'violations': [{'type': kind, 'severity': 'error',
                                                'description': 'controlled proof', 'items': []}]}))
        return SimpleNamespace(returncode=0, stderr='')
    def finalize(source, output, fixed, source_rules, drc_path):
        output.write_bytes(source.read_bytes())
        output.with_suffix('.kicad_pro').write_bytes(source_rules.with_suffix('.kicad_pro').read_bytes())
        measured = drc.run_drc(output, drc_path, run=subprocess_drc)
        if fails:
            raise RuntimeError('controlled finalizer failure')
        return SimpleNamespace(record=lambda: {}), measured
    monkeypatch.setattr(route, 'finalize_copper', finalize)
    monkeypatch.setattr(route, 'router_breaches', lambda *args: [])
    monkeypatch.setattr(route, 'routed_copper', lambda *args: (0, 0., 0))
    caller = Settings(drc_refill_zones=True, drc_real_kinds=('caller_only',),
                      drc_outstanding_kinds=('proof_issue',))
    with bind(caller):
        if fails:
            with pytest.raises(RuntimeError, match='controlled finalizer failure'):
                grader.regrade(raw, tmp_path / 'result')
        else:
            result = grader.regrade(raw, tmp_path / 'result')
            assert result.report.drc_after == {'proof_issue': 1}
            assert result.report.drc_new == 1
            assert grader.verify(result) == result.receipt
        assert active() is caller
    assert len(calls) == 1 and '--refill-zones' not in calls[0]


def test_actual_phase_key_tuple_fields_match_retained_json_invocation(tmp_path):
    from placemat.kicad.final_route import FinalCopperGrader
    from placemat.kicad.final_call import record_digest
    from placemat.route_phase import Phase
    from placemat.settings import Settings
    original = tmp_path / 'original.kicad_pcb'
    baseline = tmp_path / 'baseline.json'
    original.write_text('original')
    original.with_suffix('.kicad_pro').write_text('original rules')
    baseline.write_text('{}')
    phase = Phase('signals', 'rest', width=.3, layers=('F.Cu', 'B.Cu'), neckdown=False,
                  router_args=('--track-width', '.3'))
    invocation = {'phases': json.loads(json.dumps([phase.key()]))}
    grader = FinalCopperGrader(original=original, cleanup_input=original, rules=original,
                              baseline_drc=baseline, obligations=[[]], phases=[phase],
                              width_receipt={'policies': []}, cfg=Settings(), counted=set(),
                              open_before={}, chosen_pours=set(), invocation=invocation)
    binding = grader.binding()
    assert binding['contract']['phases'] == binding['contract']['invocation']['phases']
    old_representation = dict(binding['contract'], phases=[phase.key()])
    assert record_digest(old_representation) == binding['contract_sha256']
    binding['contract']['phases'][0]['router_args'].append('--changed')
    assert grader.binding()['contract']['phases'] == invocation['phases']


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
