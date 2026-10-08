"""Final copper-work evidence refuses partial/stale/unproved candidate scope."""
from dataclasses import replace
import math
import json

import pytest

from placemat.kicad.final_call import (CallScope, CopperWork, NominalPolicy, ProofUnavailable,
                                      RequiredJoin, StandingAuthority, Terminal, file_hash, issued_flags,
                                      proof_of, write_proof)


@pytest.fixture
def context(tmp_path):
    pcb = tmp_path / 'input.kicad_pcb'
    pcb.write_text('(kicad_pcb)')
    pcb.with_suffix('.kicad_pro').write_text('{"board":{"design_settings":{}}}')
    join = RequiredJoin('SIGNAL', Terminal('U1', '1'), Terminal('U2', '2'), (('F.Cu', .5), ('B.Cu', .5)))
    scope = CallScope('p1_0', 'single', ('--nets', 'SIGNAL', '--layers', 'F.Cu', 'B.Cu'),
                      ('SIGNAL',), ('F.Cu', 'B.Cu'), obligations=(join,))
    receipt = {'sources': {'route.py': 'b' * 64}, 'policies': [
        {'name': 'signals', 'by_net': {'SIGNAL': {'status': 'known', 'widths': {'F.Cu': .5, 'B.Cu': .5}}}}]}
    path = tmp_path / 'width_policy.json'
    path.write_text(json.dumps(receipt))
    policy = NominalPolicy.from_validated_receipt(path, receipt, 'signals', scope)
    authority = StandingAuthority('c' * 64, 'd' * 64, 'e' * 64, 'f' * 64)
    return pcb, scope, policy, authority


def build(context, **kwargs):
    pcb, scope, policy, authority = context
    return proof_of(pcb, scope, policy, (CopperWork(scope.id, scope.kind),), authority,
                    deadline_utc=200, complete_route=True, now=100, **kwargs)


def test_final_scope_binds_original_input_rules_and_literal_flags(context):
    pcb, scope, _, _ = context
    pcb.with_suffix('.kicad_dru').write_text('(version 1)\n(rule "hole" (constraint hole_clearance (min .25)))')
    proof = build(context)
    assert proof['input_files']['.kicad_pcb'] == file_hash(pcb)
    assert proof['input_files']['.kicad_dru'] == file_hash(pcb.with_suffix('.kicad_dru'))
    assert proof['call']['routing_flags'] == list(scope.routing_flags)
    assert proof['standing_authority']['available'] is True
    assert proof['deadline_utc'] == 200


@pytest.mark.parametrize('later', ['pairs', 'connections', 'pour', 'bus', 'tuning', 'single'])
def test_later_copper_changing_work_withholds_candidate(context, later):
    pcb, scope, policy, authority = context
    with pytest.raises(ProofUnavailable, match='later_copper_work'):
        proof_of(pcb, scope, policy, (CopperWork(scope.id, scope.kind), CopperWork('later', later)), authority,
                 deadline_utc=200, complete_route=True, now=100)


def test_partial_deferred_and_unknown_finalization_withhold(context):
    pcb, scope, policy, authority = context
    for changes, code in (({'complete_route': False}, 'partial_route'),
                          ({'deferred_work': ['pending-task']}, 'deferred_copper_work'),
                          ({'finalization': ['later-tuning']}, 'unknown_finalization')):
        arguments = dict(deadline_utc=200, complete_route=True, now=100)
        arguments.update(changes)
        with pytest.raises(ProofUnavailable, match=code):
            proof_of(pcb, scope, policy, (CopperWork(scope.id, scope.kind),), authority, **arguments)


def test_missing_full_standing_authority_cannot_enable_router_candidate(context):
    pcb, scope, policy, _ = context
    with pytest.raises(ProofUnavailable, match='standing_authority_unavailable'):
        proof_of(pcb, scope, policy, (CopperWork(scope.id, scope.kind),), None,
                 deadline_utc=200, complete_route=True, now=100)


def test_default_rest_must_not_seed_pair_owned_nets(context):
    pcb, scope, policy, authority = context
    with pytest.raises(ProofUnavailable, match='pair_owned_scope'):
        build((pcb, replace(scope, pair_owned_nets=('SIGNAL',)), policy, authority))


def test_connection_scope_requires_actual_task_file_identity(context):
    pcb, scope, policy, authority = context
    with pytest.raises(ProofUnavailable, match='missing_connection_scope'):
        build((pcb, replace(scope, kind='connections'), policy, authority))
    task = pcb.with_name('connections.json')
    task.write_text('[{"net":"SIGNAL","from":{"ref":"U1","pad":"1"},"to":{"ref":"U2","pad":"2"},"widths":{"F.Cu":0.5,"B.Cu":0.5}}]')
    proof = build((pcb, replace(scope, kind='connections', tasks_sha256=file_hash(task)), policy, authority))
    assert proof['call']['tasks_sha256'] == file_hash(task)


def test_bus_boundary_must_cover_exact_selected_nets(context):
    pcb, scope, policy, authority = context
    with pytest.raises(ProofUnavailable, match='invalid_bus_scope'):
        build((pcb, replace(scope, kind='bus', bus_groups=(('UNRELATED',),)), policy, authority))
    proof = build((pcb, replace(scope, kind='bus', bus_groups=(('SIGNAL',),)), policy, authority))
    assert proof['call']['bus_groups'] == [['SIGNAL']]


@pytest.mark.parametrize('width', [math.nan, math.inf, 0, True])
def test_unproved_effective_width_cannot_become_nominal_seed(context, width):
    pcb, scope, policy, authority = context
    with pytest.raises(ProofUnavailable, match='policy_unproved'):
        build((pcb, scope, replace(policy, by_net={'SIGNAL': {'F.Cu': width, 'B.Cu': .5}}), authority))


def test_exact_transport_only_leaves_flag_aliases_for_real_router_parser():
    prefix = ['python', 'hook.py', 'route.py']
    flags = ['--track-w=.5', '--layers', 'F.Cu', '--turn-cost', '-2']
    assert issued_flags(prefix + ['in', 'out'] + flags + ['--json-out', 'summary'], prefix,
                        'in', 'out', 'summary') == tuple(flags)
    with pytest.raises(ProofUnavailable, match='unknown_command_transport'):
        issued_flags(prefix + ['in', 'out'] + flags + ['--json-out=summary'], prefix, 'in', 'out', 'summary')


def test_stale_owned_request_is_not_reused(context):
    pcb, _, _, _ = context
    path = pcb.with_name('final-call-proof.json')
    write_proof(path, build(context))
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_proof(path, build(context))
    assert path.read_bytes() == before


@pytest.mark.parametrize('field,value,code', [
    ('nets', (['nested'],), 'invalid_selected_scope'),
    ('layers', (['nested'],), 'invalid_layer_scope'),
    ('pair_owned_nets', (['nested'],), 'invalid_pair_scope'),
    ('bus_groups', ((['nested'],),), 'missing_bus_scope'),
])
def test_nested_malformed_scope_is_a_structured_refusal(context, field, value, code):
    pcb, scope, policy, authority = context
    changes = {field: value}
    if field == 'bus_groups':
        changes['kind'] = 'bus'
    with pytest.raises(ProofUnavailable, match=code):
        build((pcb, replace(scope, **changes), policy, authority))


@pytest.mark.parametrize('now', [True, math.nan, math.inf, '100'])
def test_malformed_now_cannot_make_an_expired_deadline_usable(context, now):
    pcb, scope, policy, authority = context
    with pytest.raises(ProofUnavailable, match='invalid_current_time'):
        proof_of(pcb, scope, policy, (CopperWork(scope.id, scope.kind),), authority,
                 deadline_utc=200, complete_route=True, now=now)


def test_nominal_policy_cannot_mutate_behind_receipt_hash(context):
    pcb, scope, policy, _ = context
    selected = {'SIGNAL': {'F.Cu': .5, 'B.Cu': .5}}
    snapshot = NominalPolicy(policy.receipt_sha256, policy.sources_sha256, selected, policy.receipt)
    selected['SIGNAL']['F.Cu'] = .1
    assert snapshot.record(scope)['by_net']['SIGNAL']['F.Cu'] == .5
    with pytest.raises(TypeError):
        snapshot.by_net['SIGNAL']['F.Cu'] = .1
    with pytest.raises(ProofUnavailable, match='nominal_receipt_mismatch'):
        NominalPolicy(policy.receipt_sha256, policy.sources_sha256, selected, policy.receipt)
    path = pcb.with_name('width_policy.json')
    original = json.loads(path.read_text())
    changed = json.loads(path.read_text())
    changed['policies'][0]['by_net']['SIGNAL']['widths']['F.Cu'] = .1
    with pytest.raises(ProofUnavailable, match='nominal_receipt_mismatch'):
        NominalPolicy.from_validated_receipt(path, changed, 'signals', scope)
    assert original['policies'][0]['by_net']['SIGNAL']['widths']['F.Cu'] == .5


def test_required_peer_identity_cannot_be_dropped_or_replaced_by_unselected_net(context):
    pcb, scope, policy, authority = context
    with pytest.raises(ProofUnavailable, match='missing_terminal_obligations'):
        build((pcb, replace(scope, obligations=()), policy, authority))
    unrelated = replace(scope.obligations[0], net='FUTURE')
    with pytest.raises(ProofUnavailable, match='unselected_terminal_obligation'):
        build((pcb, replace(scope, obligations=(unrelated,)), policy, authority))
    changed = replace(scope.obligations[0], end=Terminal('U3', '3'))
    assert build((pcb, replace(scope, obligations=(changed,)), policy, authority))['call']['obligations'] != build(context)['call']['obligations']


@pytest.mark.parametrize('wrapper', [bytearray, memoryview])
def test_policy_receipt_cannot_change_after_snapshot(context, wrapper):
    _, _, policy, _ = context
    with pytest.raises(ProofUnavailable, match='missing_validated_nominal_receipt'):
        NominalPolicy(policy.receipt_sha256, policy.sources_sha256, dict(policy.by_net), wrapper(policy.receipt))


def test_unreadable_or_invalid_saved_receipt_withholds_candidate(context):
    pcb, scope, _, _ = context
    path = pcb.with_name('bad-receipt.json')
    for data in (None, b'not json', b'\xff'):
        if data is not None:
            path.write_bytes(data)
        with pytest.raises(ProofUnavailable, match='unreadable_nominal_receipt'):
            NominalPolicy.from_validated_receipt(path, {'policies': []}, 'signals', scope)


@pytest.mark.parametrize('shared', [True, False])
def test_same_net_tasks_with_different_policies_are_not_collapsed_to_net_width(context, shared):
    pcb, scope, policy, authority = context
    second = RequiredJoin('SIGNAL', Terminal('U1' if shared else 'U3', '1'), Terminal('U4', '2'),
                          (('F.Cu', .8), ('B.Cu', .5)))
    tasks = pcb.with_name('tasks.json')
    tasks.write_text('[]')
    scope = replace(scope, kind='connections', tasks_sha256=file_hash(tasks),
                    obligations=scope.obligations + (second,))
    records = scope.record()['obligations']
    assert records[0]['task_sha256'] != records[1]['task_sha256']
    with pytest.raises(ProofUnavailable, match='terminal_policy_mismatch'):
        build((pcb, scope, policy, authority))


def test_nested_scope_and_join_containers_are_snapshots(context):
    _, scope, _, _ = context
    widths = [['F.Cu', .5], ['B.Cu', .5]]
    join = RequiredJoin('SIGNAL', Terminal('U1', '1'), Terminal('U2', '2'), widths)
    nets, joins = ['SIGNAL'], [join]
    snapshot = replace(scope, nets=nets, obligations=joins, kind='bus', bus_groups=[nets])
    widths[0][1] = .1
    nets.append('UNRELATED')
    joins.clear()
    record = snapshot.record()
    assert record['nets'] == ['SIGNAL'] and record['bus_groups'] == [['SIGNAL']]
    assert record['obligations'][0]['widths']['F.Cu'] == .5
