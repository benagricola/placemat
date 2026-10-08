"""Logical contract data keeps complete roles and actual width provenance."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from placemat.pinmap_common import CandidateRefused
from placemat.pinmap_logical import mint
from placemat.pinmap_logical_packet import contract_record
from tests.test_pinmap_logical import proved


def context(tmp_path):
    board, plan, physical = proved(tmp_path)
    proof = mint(board, plan, physical)
    nets = sorted({net for net, _, _ in proof.roles if net})
    definition = {'name': 'complete', 'selector': 'rest', 'nets': [], 'net_classes': [],
                  'buses': [], 'connections': [], 'interfaces': [], 'net_types': [],
                  'pairs': [], 'width': None, 'layers': None, 'neckdown': True, 'router_args': []}
    scopes = [{'definition': definition, 'nets': nets, 'tasks': [], 'asked': [], 'asked_sha256': None}]
    requests = [{'name': 'complete', 'kind': 'nets', 'nets': nets, 'layers': ['F.Cu'], 'args': [], 'power': {}}]
    config = hashlib.sha256(json.dumps(requests, sort_keys=True).encode()).hexdigest()
    original = {'schema': 1, 'config_sha256': config, 'inputs': {'source': 'original'},
                'policies': [{'name': 'complete', 'kind': 'nets', 'by_net': {
                    net: {'status': 'known', 'widths': {'F.Cu': .3}} for net in nets}}]}
    for net in nets:
        members = sorted(old for role, old, _ in proof.roles if role == net)
        for other in members[1:]:
            scopes[0]['asked'].append({'net': net, 'from': dict(zip(('ref', 'pad'), members[0])),
                'to': dict(zip(('ref', 'pad'), other)), 'widths': {'F.Cu': .3}, 'width_policy_contract': config})
    scopes[0]['asked_sha256'] = hashlib.sha256(json.dumps(scopes[0]['asked'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    candidate = deepcopy(original)
    candidate['inputs'] = {'source': 'written candidate'}
    return board, plan, proof, scopes, requests, original, deepcopy(requests), candidate


def test_distinct_physical_membership_projects_complete_original_roles_and_retains_both_receipts(tmp_path):
    args = context(tmp_path)
    record = contract_record(*args)
    assert record['original_receipt_sha256'] != record['candidate_receipt_sha256']
    assert any(old != new for _, old, new in record['roles'])
    for phase in record['phases']:
        for membership in phase['members']:
            net = membership['net']
            assert membership['original'] == sorted(old for role, old, _ in record['roles'] if role == net)
            assert membership['candidate'] == sorted(new for role, _, new in record['roles'] if role == net)
            assert len(membership['original']) == len(membership['candidate'])
    assert record['widths']
    # The packet is explicit JSON data, not a reconstructed authority/Standing.
    assert json.loads(json.dumps(record, allow_nan=False)) == record
    assert 'comparison_contract' not in record


@pytest.mark.parametrize('task', ['interfaces', 'connections', 'current_paths', 'captured_task'])
def test_physical_capture_tasks_refuse_even_without_phase_connections(tmp_path, task):
    args = list(context(tmp_path))
    scopes = args[3]
    if task in ('interfaces', 'connections'):
        scopes[0]['definition'][task] = ['physical endpoint']
    elif task == 'current_paths':
        scopes[0]['definition']['selector'] = task
    else:
        scopes[0]['tasks'] = [{'kind': 'interface', 'from': ['U1', '1']}]
    with pytest.raises(CandidateRefused) as error:
        contract_record(*args)
    assert error.value.code == 'logical_physical_task_unsupported'


@pytest.mark.parametrize('change', ['request', 'required_width', 'unknown', 'net', 'layer', 'config', 'missing_scope'])
def test_candidate_cannot_weaken_original_resolved_width_scope(tmp_path, change):
    args = list(context(tmp_path))
    candidate = args[7]
    net = next(iter(candidate['policies'][0]['by_net']))
    if change == 'request':
        args[6][0]['power'] = {net: .1}
    elif change == 'required_width':
        candidate['policies'][0]['by_net'][net]['widths']['F.Cu'] = .1
    elif change == 'unknown':
        candidate['policies'][0]['by_net'][net] = {'status': 'unknown', 'reason': 'missing proof'}
    elif change == 'net':
        del candidate['policies'][0]['by_net'][net]
    elif change == 'layer':
        candidate['policies'][0]['by_net'][net]['widths'] = {'B.Cu': .3}
    elif change == 'config':
        candidate['config_sha256'] = 'forged'
    else:
        candidate['policies'] = []
    with pytest.raises(CandidateRefused):
        contract_record(*args)


@pytest.mark.parametrize('change', ['duplicate_phase', 'unknown_net', 'extra_field', 'missing_definition', 'missing_policy'])
def test_incomplete_or_unrelated_contract_data_is_refused(tmp_path, change):
    args = list(context(tmp_path))
    if change == 'duplicate_phase':
        args[3].append(deepcopy(args[3][0]))
    elif change == 'unknown_net':
        args[3][0]['nets'].append('UNPROVED')
    elif change == 'extra_field':
        args[3][0]['unverified'] = True
    elif change == 'missing_definition':
        del args[3][0]['definition']['neckdown']
    else:
        args[5]['policies'] = []
    with pytest.raises(CandidateRefused):
        contract_record(*args)


def test_forged_or_stale_role_capability_cannot_create_a_packet(tmp_path):
    args = list(context(tmp_path))
    original = args[2]
    args[2] = replace(original)
    with pytest.raises(CandidateRefused) as error:
        contract_record(*args)
    assert error.value.code == 'logical_proof_missing'
    args[2] = original
    original.physical.source.write_text('(source changed)')
    with pytest.raises(CandidateRefused) as error:
        contract_record(*args)
    assert error.value.code == 'proof_input_changed'


@pytest.mark.parametrize('change', ['drop', 'duplicate', 'unknown_endpoint', 'held_changed', 'width', 'policy', 'reorder'])
def test_original_fixed_ask_denominator_and_required_widths_cannot_change(tmp_path, change):
    args = list(context(tmp_path))
    asks = args[3][0]['asked']
    assert len(asks) >= 2
    if change == 'drop': asks.pop()
    elif change == 'duplicate': asks.append(deepcopy(asks[0]))
    elif change == 'unknown_endpoint': asks[0]['to']['ref'] = 'UNPROVED'
    elif change == 'held_changed': asks[0]['to']['pad'] = 'UNPROVED'
    elif change == 'width': asks[0]['widths']['F.Cu'] = .1
    elif change == 'policy': asks[0]['width_policy_contract'] = 'forged'
    else: asks.reverse()
    with pytest.raises(CandidateRefused):
        contract_record(*args)


def test_partial_closure_keeps_original_asked_identities_and_denominator(tmp_path):
    args = context(tmp_path)
    record = contract_record(*args)
    phase = record['phases'][0]
    assert phase['asked_count'] == len(args[3][0]['asked'])
    role_map = {tuple(old): tuple(new) for _, old, new in record['roles']}
    for index, ask in enumerate(phase['asks']):
        assert ask['index'] == index
        assert ask['original'] == args[3][0]['asked'][index]
        for endpoint in ('from', 'to'):
            old = ask['original'][endpoint]
            final = ask['candidate'][endpoint]
            assert tuple(final[key] for key in ('ref', 'pad')) == role_map[tuple(old[key] for key in ('ref', 'pad'))]
        assert ask['original']['widths'] == ask['candidate']['widths']
    # A partially connected component is transformed by the role mapping; the
    # same fixed asks succeed, without replacing the denominator with net count.
    endpoint = lambda value: tuple(value[key] for key in ('ref', 'pad'))
    first = phase['asks'][0]['original']
    source_component = {endpoint(first['from']), endpoint(first['to'])}
    final_component = {role_map[value] for value in source_component}
    source_joined = [all(endpoint(ask['original'][end]) in source_component for end in ('from', 'to'))
                     for ask in phase['asks']]
    final_joined = [all(endpoint(ask['candidate'][end]) in final_component for end in ('from', 'to'))
                    for ask in phase['asks']]
    assert source_joined == final_joined
    assert 0 < sum(source_joined) < phase['asked_count']



@pytest.mark.parametrize('field,value', [('neckdown', 1), ('connections', {}), ('router_args', [True]),
    ('pairs', [['A']]), ('nets', {}), ('layers', ['F.Cu', 'F.Cu']), ('width', float('nan'))])
def test_malformed_nested_phase_values_have_structured_refusals(tmp_path, field, value):
    args = list(context(tmp_path))
    args[3][0]['definition'][field] = value
    with pytest.raises(CandidateRefused) as error:
        contract_record(*args)
    assert error.value.code == 'logical_packet_malformed'


def test_noncanonical_original_tree_order_is_retained_from_its_receipt(tmp_path):
    args = list(context(tmp_path))
    asks = args[3][0]['asked']
    asks.reverse()
    args[3][0]['asked_sha256'] = hashlib.sha256(json.dumps(asks, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    record = contract_record(*args)
    assert [ask['original'] for ask in record['phases'][0]['asks']] == asks
    assert record['phases'][0]['asked_count'] == len(asks)


def test_ask_on_genuinely_proved_but_unselected_net_is_structurally_refused(tmp_path):
    args = list(context(tmp_path))
    scope = args[3][0]
    outside = scope['asked'][0]['net']
    assert outside in {net for net, _, _ in args[2].roles}
    scope['nets'].remove(outside)
    for requests in (args[4], args[6]):
        requests[0]['nets'] = [net for net in requests[0]['nets'] if net != outside]
    config = hashlib.sha256(json.dumps(args[4], sort_keys=True).encode()).hexdigest()
    for policy in (args[5], args[7]):
        del policy['policies'][0]['by_net'][outside]
        policy['config_sha256'] = config
    for ask in scope['asked']:
        ask['width_policy_contract'] = config
    scope['asked_sha256'] = hashlib.sha256(json.dumps(scope['asked'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    # Requests/receipts agree on the narrowed selection; only the genuine other
    # net ask is out of scope. Refuse it before per-ask width policy lookup.
    with pytest.raises(CandidateRefused) as error:
        contract_record(*args)
    assert error.value.code == 'logical_membership_unproved'


def test_owned_data_verifier_reconstructs_roles_without_reconstructing_authority(tmp_path):
    from placemat.pinmap_logical_packet import verify_contract_record
    args = context(tmp_path)
    proof = args[2].physical
    record = contract_record(*args)
    assert verify_contract_record(record, proof.source_pads, proof.final_pads, *args[3:]) == record


@pytest.mark.parametrize('change', ['role', 'held', 'duplicate', 'asked_count', 'width', 'receipt'])
def test_owned_data_verifier_rejects_changed_projected_evidence(tmp_path, change):
    from placemat.pinmap_logical_packet import verify_contract_record
    args = context(tmp_path)
    physical = args[2].physical
    record = contract_record(*args)
    if change == 'role': record['roles'][0][2] = ['UNKNOWN', '1']
    elif change == 'held':
        held = next(role for role in record['roles'] if role[1] == role[2])
        held[2] = ['UNKNOWN', '1']
    elif change == 'duplicate': record['roles'].append(deepcopy(record['roles'][0]))
    elif change == 'asked_count': record['phases'][0]['asked_count'] += 1
    elif change == 'width': record['phases'][0]['asks'][0]['candidate']['widths']['F.Cu'] = .1
    else: record['original_receipt_sha256'] = 'forged'
    with pytest.raises(CandidateRefused) as error:
        verify_contract_record(record, physical.source_pads, physical.final_pads, *args[3:])
    assert error.value.code == 'logical_projection_changed'
