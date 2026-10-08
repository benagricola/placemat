"""JSON final-check transport preserves original checks and refuses unknown context."""
import copy
from dataclasses import replace

import pytest

from placemat import final_board, score
from placemat.final_check_context import ContextRefused, encode, judge, _shape, _read_shape
from tests.fixtures import board_geometry, footprint, track
from tests.test_final_board import _placed


def context(tmp_path):
    parts = [footprint('U1', 10, 10, nets=('VIN', 'X'), fields={'Pm.I': 'vin:3A'}),
             footprint('C1', 30, 10, nets=('VIN', 'GND'), fields={'Pm.I': 'vin:3A'})]
    board, plan = _placed(board_geometry(parts))
    source = tmp_path / 'original.kicad_pcb'
    source.write_text('retained source')
    source.with_suffix('.kicad_pro').write_text('{}')
    return board, plan, source, score.plan_measures(board, plan)


def test_worker_context_runs_the_same_authoritative_current_and_escape_judgement(tmp_path, monkeypatch):
    board, plan, source, measures = context(tmp_path)
    routed = tmp_path / 'routed.kicad_pcb'
    narrow = board_geometry(list(plan.geometry.footprints), copper=[
        track('VIN', 8.6, 10, 15, 10, w=1.5), track('VIN', 15, 10, 21, 10, w=.3),
        track('VIN', 21, 10, 28.6, 10, w=1.5)])
    reads = []
    def read(path):
        reads.append(path)
        return plan.geometry if str(path) == str(source) else narrow
    monkeypatch.setattr('placemat.kicad.read.read_board', read)
    expected = final_board.judge(board, plan, routed, measures)
    record = encode(board, plan, measures, source)
    result = judge(record, routed)
    assert result.evidence() == expected.evidence()
    assert result.measures == expected.measures
    assert [vars(v) for v in result.verdicts] == [vars(v) for v in expected.verdicts]
    assert result.evidence()['critical_checks'] == 1
    assert reads == [routed, str(source), routed]


def test_actual_rule_and_acceptance_bounds_survive_transport(tmp_path, monkeypatch):
    from placemat.checks import Acceptance
    from placemat.rules import Rule
    board, plan, source, measures = context(tmp_path)
    board._rules = [Rule('clearance', .4, 'retained rule', between=('VIN', 'GND'))]
    plan.acceptances = [Acceptance('hot-loop', 'VIN', at_most=3.5, why='original bounded exception')]
    record = encode(board, plan, measures, source)
    observed = {}
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda _: plan.geometry)
    def grading(board, restored, pcb, measures):
        observed.update(rules=board._rules, acceptances=restored.acceptances)
        return 'shared grader'
    monkeypatch.setattr('placemat.final_board.judge', grading)
    assert judge(record, source) == 'shared grader'
    assert observed == {'rules': board._rules, 'acceptances': plan.acceptances}


@pytest.mark.parametrize('change', ['unknown-field', 'schema-bool', 'missing-setting', 'relative-source',
                                  'missing-digest', 'unknown-shape', 'nonfinite', 'unknown-rule'])
def test_malformed_context_refuses_without_final_certification(tmp_path, monkeypatch, change):
    board, plan, source, measures = context(tmp_path)
    record = copy.deepcopy(encode(board, plan, measures, source))
    if change == 'unknown-field':
        record['callback'] = 'untrusted code'
    elif change == 'schema-bool':
        record['schema'] = True
    elif change == 'missing-setting':
        record['settings'].pop('score_area')
    elif change == 'relative-source':
        record['source'] = 'relative.kicad_pcb'
    elif change == 'missing-digest':
        record['inputs'][str(source)] = None
    elif change == 'unknown-shape':
        record['board_shape'] = {'kind': 'dynamic-class'}
    elif change == 'nonfinite':
        record['component_spacing'] = float('inf')
    else:
        record['rules'] = [{'kind': 'dynamic-class'}]
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda _: plan.geometry)
    monkeypatch.setattr('placemat.final_board.judge', lambda *a: pytest.fail('malformed context certified'))
    with pytest.raises(ContextRefused):
        judge(record, source)


def test_changed_source_and_declared_escape_never_acquire_worker_authority(tmp_path, monkeypatch):
    board, plan, source, measures = context(tmp_path)
    record = encode(board, plan, measures, source)
    source.write_text('changed source')
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda _: pytest.fail('stale source read'))
    with pytest.raises(ContextRefused):
        judge(record, source)
    board._escapes = [object()]
    with pytest.raises(ContextRefused):
        encode(board, plan, measures, source)


def test_exact_outline_disc_and_cutout_paths_roundtrip_and_detect_changed_flattening():
    from placemat.cutouts import Arc, Cutouts
    from placemat.outline import Outline
    from placemat.values import Disc, Location
    path = ((0., 0.), (10., 0.), (10., 10.), (0., 10.))
    hole = ((3., 3.), Arc((5., 3.), (4., 2.)), (5., 5.), (3., 5.))
    for shape in (None, Outline.of(path, (hole,)), Cutouts((hole,)), Disc(Location(5., 5.), 10., 2., (hole,))):
        assert _read_shape(_shape(shape)) == shape
    record = _shape(Outline.of(path))
    record['loops'][0][0][0] += .001
    with pytest.raises(ContextRefused):
        _read_shape(record)


@pytest.mark.parametrize('change', ['check-list', 'check-dict', 'wrong-bound', 'bound-list',
                                  'rule-pair-dict', 'disc-negative', 'arc-not-record'])
def test_malformed_nested_intent_refuses_before_final_judge(tmp_path, monkeypatch, change):
    from placemat.checks import Acceptance
    from placemat.rules import Rule
    board, plan, source, measures = context(tmp_path)
    plan.acceptances = [Acceptance('hot-loop', 'VIN', at_most=3., why='retained')]
    board._rules = [Rule('clearance', .4, 'retained', between=('VIN', 'GND'))]
    record = encode(board, plan, measures, source)
    if change.startswith('check-'):
        record['acceptances'][0]['check'] = [] if change == 'check-list' else {}
    elif change == 'wrong-bound':
        record['acceptances'][0].update(at_most=None, at_least=3.)
    elif change == 'bound-list':
        record['acceptances'][0]['at_most'] = [3.]
    elif change == 'rule-pair-dict':
        record['rules'][0]['between'] = {'first': 'VIN', 'second': 'GND'}
    elif change == 'disc-negative':
        record['board_shape'] = {'kind': 'disc', 'centre': [0., 0.], 'diameter': -1., 'hole': 0., 'holes': []}
    else:
        record['board_shape'] = {'kind': 'outline', 'paths': [[{'arc': []}]], 'loops': [[]]}
    monkeypatch.setattr('placemat.kicad.read.read_board', lambda _: plan.geometry)
    monkeypatch.setattr('placemat.final_board.judge', lambda *a: pytest.fail('malformed intent certified'))
    with pytest.raises(ContextRefused) as refused:
        judge(record, source)
    assert refused.value.code == 'final_check_context_unsupported'
