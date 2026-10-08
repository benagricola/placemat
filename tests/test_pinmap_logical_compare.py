"""Private comparison guards and stable fixed-ask compatibility values."""
import copy

import pytest

from placemat import score
from placemat.pinmap_common import CandidateRefused
from placemat.pinmap_logical_compare import LogicalRouteComparison, _scope, _standing
from placemat.settings import Settings


def _records():
    ask = {'net': 'A', 'from': {'ref': 'U2', 'pad': '1'}, 'to': {'ref': 'U1', 'pad': '1'},
           'widths': {'F.Cu': 0.3}, 'width_policy_contract': 'source physical receipt'}
    logical = {'roles': [['A', ['U1', '1'], ['U1', '2']], ['A', ['U2', '1'], ['U2', '1']]],
        'widths': [{'name': 'REST', 'kind': 'nets', 'by_net': [['A', [['F.Cu', 0.3]]]]}],
        'original_receipt_sha256': 'first source receipt', 'candidate_receipt_sha256': 'first candidate receipt',
        'phases': [{'definition': {'name': 'REST'}, 'asks': [{'original': ask}],
                    'members': [{'net': 'A', 'original': [['U1', '1'], ['U2', '1']]}]}]}
    keys = ('settings', 'rules', 'acceptances', 'edge_margin', 'component_spacing',
            'board_shape', 'board_cutouts', 'quiet', 'planes', 'pending', 'fields')
    request = {'logical': logical, 'critical_original': {key: [] for key in keys},
        'expected_readback': {'rules': [['hole_clearance', 0.2], ['copper_mm', {'F.Cu': 0.035}]]},
        'input_bundle': {'sidecars': [{'original': '/seed-0/layout.kicad_pro', 'sha256': 'project bytes'},
                                    {'original': '/seed-0/layout.kicad_dru', 'sha256': None},
                                    {'original': '/seed-0/capture.json', 'sha256': 'capture bytes'}]}}
    response = {'fixed_preservation': {'fixed_copper': [], 'protected_forms': {}},
                'original_verification': {'original': {'baseline_semantics_sha256': 'actual original baseline',
                                                     'open_before': {'A': 1}, 'counted': []}}}
    return request, response


def test_different_raw_receipts_do_not_replace_stable_fixed_ask_identity():
    request, response = _records()
    other = copy.deepcopy(request)
    other['logical']['original_receipt_sha256'] = 'second source receipt'
    other['logical']['candidate_receipt_sha256'] = 'second candidate receipt'
    other['logical']['phases'][0]['asks'][0]['original']['width_policy_contract'] = 'second physical receipt'
    for row in other['input_bundle']['sidecars']:
        row['original'] = row['original'].replace('seed-0', 'seed-1')
    assert _scope(request, response) == _scope(other, response)
    assert request['logical']['original_receipt_sha256'] == 'first source receipt'


@pytest.mark.parametrize('field', ['project', 'custom_rule_presence', 'capture', 'physical_hole_rule', 'stackup'])
def test_different_original_manufacturing_or_capture_context_is_incomparable(field):
    request, response = _records()
    other = copy.deepcopy(request)
    if field in ('project', 'custom_rule_presence', 'capture'):
        index = {'project': 0, 'custom_rule_presence': 1, 'capture': 2}[field]
        other['input_bundle']['sidecars'][index]['sha256'] = 'different original bytes'
    elif field == 'physical_hole_rule':
        other['expected_readback']['rules'][0][1] = 0.1
    else:
        other['expected_readback']['rules'][1][1]['F.Cu'] = 0.07
    assert _scope(request, response) != _scope(other, response)


@pytest.mark.parametrize('field', ['lib_id', 'net_tie_pads', 'drill_mm', 'through', 'board_only'])
def test_live_original_manufacturing_semantics_are_part_of_seed_scope(field):
    request, response = _records()
    original = {'lib_id': 'Library:Pad', 'net_tie_pads': [], 'drill_mm': 0.3,
                'through': True, 'board_only': False}
    changed = copy.deepcopy(original)
    changed[field] = 'different original semantics'
    assert _scope(request, response, source_semantics=original) != _scope(
        request, response, source_semantics=changed)


@pytest.mark.parametrize('change', ['asked_endpoint', 'asked_order', 'required_width', 'held_role', 'baseline', 'denominator'])
def test_fixed_original_obligations_and_baseline_remain_comparison_scope(change):
    request, response = _records()
    other, result = copy.deepcopy(request), copy.deepcopy(response)
    if change == 'asked_endpoint':
        other['logical']['phases'][0]['asks'][0]['original']['from']['ref'] = 'U3'
    elif change == 'asked_order':
        second = copy.deepcopy(other['logical']['phases'][0]['asks'][0])
        second['original']['from']['ref'] = 'U3'
        request['logical']['phases'][0]['asks'].append(copy.deepcopy(second))
        other['logical']['phases'][0]['asks'].insert(0, second)
    elif change == 'required_width':
        other['logical']['phases'][0]['asks'][0]['original']['widths']['F.Cu'] = 0.4
    elif change == 'held_role':
        other['logical']['roles'].append(['HELD', ['U3', '1'], ['U3', '1']])
    elif change == 'baseline':
        result['original_verification']['original']['baseline_semantics_sha256'] = 'candidate before baseline'
    else:
        result['original_verification']['original']['open_before']['A'] = 2
    assert _scope(request, response) != _scope(other, result)


def test_private_value_view_retains_raw_known_width_and_critical_failures():
    physical = score.Standing({'airwire_mm': 4, 'vias': 1},
        score.Validity(drc_new=0, widths_failed=2, critical=3), (0.5,), 0.5,
        ('actual raw physical contract',), True, ('REST',))
    judgment = {'critical': {'measures': {'findings': {}, 'critical_checks': 0}},
                'drc_new': 1, 'closure_clean': 0.75,
                'phases': [{'closure_clean': 0.75, 'judged': [{'joined': True, 'under': {'F.Cu': 0.2}}]}]}
    value = _standing(physical, judgment)
    assert value.validity.widths_failed == 2 and value.validity.critical == 3 and value.validity.drc_new == 1
    assert value.phase_contracts == physical.phase_contracts
    assert value.closures == (0.75,) and physical.closures == (0.5,)
    assert physical.measures == {'airwire_mm': 4, 'vias': 1}


def test_public_rank_still_refuses_distinct_raw_physical_contracts():
    a = score.Standing({}, score.Validity(drc_new=0), (1.0,), 1.0, ('original physical contract',), True, ('REST',))
    b = score.Standing({}, score.Validity(drc_new=0), (1.0,), 1.0, ('candidate physical contract',), True, ('REST',))
    with pytest.raises(ValueError, match='incomparable phase obligations'):
        score.rank(a, b, Settings())


def test_constructed_comparison_and_serialized_flags_cannot_rank(tmp_path):
    comparison = LogicalRouteComparison(None, {'logical_verified': True}, {}, {}, {}, tmp_path, object())
    with pytest.raises(CandidateRefused) as got:
        comparison.rank()
    assert got.value.code == 'logical_comparison_not_minted'
