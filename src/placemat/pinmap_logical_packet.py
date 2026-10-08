"""Strict logical comparison data for an owned routed worker; mint no authority.

These records supplement raw physical contracts. The eventual retained consumer
must independently validate both executor custody packets, resolved receipts and
original baseline before it can use them. A decoded record is never a Standing.
"""
from __future__ import annotations

import hashlib
import json
import math

from .pinmap_common import CandidateRefused
from .pinmap_logical import LogicalTerminals


def _refuse(code, message, **facts):
    raise CandidateRefused(code, message, **facts)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise CandidateRefused('logical_packet_malformed', 'logical packet requires finite JSON values') from error


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _names(value):
    if type(value) is not list or any(type(v) is not str or not v for v in value) or len(set(value)) != len(value):
        _refuse('logical_packet_malformed', 'logical membership requires unique nonempty names')
    return value


def _widths(policy):
    """Retain exact known per-net/layer requirements from resolved receipts.

    The caller/owned worker must first run the shared source-bound receipt
    validator. This shape validation is not a replacement for its input custody.
    """
    if type(policy) is not dict or type(policy.get('schema')) is not int or policy['schema'] != 1:
        _refuse('logical_width_policy_unproved', 'logical comparison requires a resolved width receipt')
    records = policy.get('policies')
    if type(records) is not list:
        _refuse('logical_width_policy_unproved', 'resolved policy scopes are missing')
    out = []
    for record in records:
        if type(record) is not dict or type(record.get('name')) is not str or record.get('kind') not in ('nets', 'pairs'):
            _refuse('logical_width_policy_unproved', 'resolved policy scope is malformed')
        by_net = record.get('by_net')
        if type(by_net) is not dict or any(type(n) is not str or not n for n in by_net):
            _refuse('logical_width_policy_unproved', 'resolved policy net membership is malformed')
        widths = []
        for net, entry in sorted(by_net.items()):
            if type(entry) is not dict or entry.get('status') != 'known':
                _refuse('logical_width_unknown', 'required logical width has no known proof', phase=record['name'], net=net)
            layers = entry.get('widths')
            if type(layers) is not dict or not layers:
                _refuse('logical_width_policy_unproved', 'resolved policy layers are missing')
            for layer, width in layers.items():
                if type(layer) is not str or type(width) not in (int, float):
                    _refuse('logical_width_policy_unproved', 'resolved policy width is malformed')
                try:
                    finite = math.isfinite(width)
                except OverflowError:
                    finite = False
                if not finite or width <= 0:
                    _refuse('logical_width_policy_unproved', 'resolved policy width is outside its domain')
            widths.append([net, [[layer, width] for layer, width in sorted(layers.items())]])
        out.append({'name': record['name'], 'kind': record['kind'], 'by_net': widths})
    return out



def _endpoint(value):
    if type(value) is not dict or set(value) != {'ref', 'pad'} or any(
            type(value[key]) is not str or not value[key] for key in ('ref', 'pad')):
        _refuse('logical_packet_malformed', 'fixed logical ask endpoint is malformed')
    return value['ref'], value['pad']


def _project_asks(asked, asked_sha256, roles, selected_nets):
    """Keep the exact original generated pair set and denominator, not a new tree."""
    if type(asked) is not list:
        _refuse('logical_asks_missing', 'original fixed generated asks are missing')
    if type(asked_sha256) is not str or len(asked_sha256) != 64 or _hash(asked) != asked_sha256:
        _refuse('logical_asks_changed', 'fixed asks differ from their retained original receipt')
    mapping = {tuple(old): (net, new) for net, old, new in roles}
    seen, out = set(), []
    for index, ask in enumerate(asked):
        if type(ask) is not dict or set(ask) != {'net', 'from', 'to', 'widths', 'width_policy_contract'}:
            _refuse('logical_asks_missing', 'fixed generated ask has unsupported or unproved fields')
        start, end = _endpoint(ask['from']), _endpoint(ask['to'])
        net = ask['net']
        if type(net) is not str or net not in selected_nets:
            _refuse('logical_membership_unproved', 'fixed ask net is outside its original selected phase membership')
        if start not in mapping or end not in mapping or any(
                mapping[endpoint][0] != net for endpoint in (start, end)):
            _refuse('logical_endpoint_unproved', 'fixed ask does not belong to one proved original logical net')
        if type(ask['widths']) is not dict or not ask['widths']:
            _refuse('logical_width_unknown', 'fixed logical ask lacks known original widths')
        key = (net, *sorted((start, end)))
        if start == end or key in seen:
            _refuse('logical_asks_changed', 'fixed logical asks contain duplicate or self endpoints')
        seen.add(key)
        candidate = {**ask, 'from': dict(zip(('ref', 'pad'), mapping[start][1])),
                     'to': dict(zip(('ref', 'pad'), mapping[end][1]))}
        out.append({'index': index, 'identity_sha256': _hash(ask), 'original': ask, 'candidate': candidate})
    return out

def contract_record(board, plan, proof, phase_scopes, original_requests, original_policy,
                    candidate_requests, candidate_policy, *, settings=None):
    """Encode a complete net-level projection, retaining both receipt digests.

    ``phase_scopes`` comes from independently reconstructed actual selections:
    each record has the full phase definition, selected nets, actual task
    records and original fixed asks with their independently retained receipt.
    This codec never generates a replacement original/candidate tree. Physical capture tasks are refused even if phase.connections is
    empty. This function verifies the live proof, but grants no routing custody.
    """
    if type(proof) is not LogicalTerminals:
        _refuse('logical_proof_missing', 'logical packet requires the exact minted role proof')
    proof.verify(board, plan, settings)
    return _contract_data([[net, list(old), list(new)] for net, old, new in proof.roles],
                          phase_scopes, original_requests, original_policy,
                          candidate_requests, candidate_policy)


def _contract_data(roles, phase_scopes, original_requests, original_policy,
                   candidate_requests, candidate_policy):
    if type(phase_scopes) is not list:
        _refuse('logical_packet_malformed', 'complete original phase scopes are missing')
    phases, names = [], set()
    for scope in phase_scopes:
        if type(scope) is not dict or set(scope) != {'definition', 'nets', 'tasks', 'asked', 'asked_sha256'}:
            _refuse('logical_packet_malformed', 'logical phase scope has unsupported fields')
        definition = scope['definition']
        phase_keys = {'name', 'selector', 'nets', 'net_classes', 'buses', 'connections', 'interfaces',
                      'net_types', 'pairs', 'width', 'layers', 'neckdown', 'router_args'}
        if type(definition) is not dict or set(definition) != phase_keys or type(definition.get('name')) is not str or not definition['name']:
            _refuse('logical_packet_malformed', 'logical phase identity is missing')
        for field in ('nets', 'net_classes', 'interfaces', 'net_types', 'router_args'):
            values = definition[field]
            if type(values) is not list or any(type(value) is not str for value in values):
                _refuse('logical_packet_malformed', 'phase named values are malformed', field=field)
        for field in ('pairs', 'buses'):
            groups = definition[field]
            if type(groups) is not list or any(type(group) is not list or not group or any(
                    type(value) is not str or not value for value in group) for group in groups):
                _refuse('logical_packet_malformed', 'phase grouped net values are malformed', field=field)
            if field == 'pairs' and any(len(group) != 2 for group in groups):
                _refuse('logical_packet_malformed', 'phase pair membership is malformed')
        if type(definition['connections']) is not list or type(scope['tasks']) is not list or type(definition['neckdown']) is not bool:
            _refuse('logical_packet_malformed', 'phase task or neckdown values are malformed')
        if definition['layers'] is not None:
            _names(definition['layers'])
        width = definition['width']
        if width is not None:
            if type(width) not in (int, float):
                _refuse('logical_physical_task_unsupported', 'phase width requires unsupported physical intent')
            try:
                finite = math.isfinite(width)
            except OverflowError:
                finite = False
            if not finite or width <= 0:
                _refuse('logical_packet_malformed', 'phase width is outside its domain')
        name = definition['name']
        if name in names:
            _refuse('logical_packet_malformed', 'logical phase names are duplicated')
        names.add(name)
        if definition.get('selector') not in ('rest', 'nets', 'net_classes', 'net_types', 'pairs', 'buses'):
            _refuse('logical_physical_task_unsupported', 'logical comparison excludes physical task selectors', phase=name)
        if definition.get('connections') or definition.get('interfaces') or scope['tasks'] != []:
            _refuse('logical_physical_task_unsupported', 'logical comparison excludes captured or explicit physical tasks', phase=name)
        nets = _names(scope['nets'])
        members = []
        for net in sorted(nets):
            selected = [row for row in roles if row[0] == net]
            if not selected:
                _refuse('logical_membership_unproved', 'selected logical net has no proved terminal membership', phase=name, net=net)
            members.append({'net': net, 'original': sorted(row[1] for row in selected),
                            'candidate': sorted(row[2] for row in selected)})
        asks = _project_asks(scope['asked'], scope['asked_sha256'], roles, set(nets))
        phases.append({'definition': definition, 'members': members, 'asks': asks,
                       'asked_count': len(asks), 'asked_sha256': scope['asked_sha256']})
    if _json(original_requests) != _json(candidate_requests):
        _refuse('logical_width_scope_changed', 'candidate width requests change original logical requirements')
    if type(original_requests) is not list:
        _refuse('logical_width_scope_changed', 'logical width requests must be complete records')
    config_hash = hashlib.sha256(json.dumps(original_requests, sort_keys=True).encode()).hexdigest()
    if any(type(policy) is not dict or policy.get('config_sha256') != config_hash
           for policy in (original_policy, candidate_policy)):
        _refuse('logical_width_scope_changed', 'resolved width receipt does not bind issued logical requests')
    original_widths, candidate_widths = _widths(original_policy), _widths(candidate_policy)
    if len(original_requests) != len(original_widths):
        _refuse('logical_width_scope_changed', 'resolved widths omit issued scopes')
    for request, widths in zip(original_requests, original_widths):
        if type(request) is not dict or request.get('name') != widths['name'] or request.get('kind') != widths['kind']:
            _refuse('logical_width_scope_changed', 'resolved width scope differs from its issued request')
        nets = _names(request.get('nets'))
        layers = _names(request.get('layers'))
        if sorted(nets) != [net for net, _ in widths['by_net']] or any(
                sorted(layers) != [layer for layer, _ in values] for _, values in widths['by_net']):
            _refuse('logical_width_scope_changed', 'resolved width membership differs from its issued request')
    if _json(original_widths) != _json(candidate_widths):
        _refuse('logical_width_policy_changed', 'candidate required widths differ from original resolved logical widths')
    for width_scope in original_widths:
        if width_scope['name'] not in names:
            _refuse('logical_width_scope_changed', 'width policy names an unproved phase')
        phase = next(p for p in phases if p['definition']['name'] == width_scope['name'])
        selected = {m['net'] for m in phase['members']}
        if any(net not in selected for net, _ in width_scope['by_net']):
            _refuse('logical_width_scope_changed', 'width policy names an unproved logical net')
    for phase in phases:
        covered = {net for width_scope in original_widths if width_scope['name'] == phase['definition']['name']
                   for net, _ in width_scope['by_net']}
        if covered != {member['net'] for member in phase['members']}:
            _refuse('logical_width_scope_changed', 'phase membership lacks complete resolved required widths')
        resolved = {}
        for width_scope in original_widths:
            if width_scope['name'] == phase['definition']['name']:
                for net, values in width_scope['by_net']:
                    if net in resolved and _json(resolved[net]) != _json(dict(values)):
                        _refuse('logical_width_unknown', 'selected net has conflicting required-width policies')
                    resolved[net] = dict(values)
        for ask in phase['asks']:
            original = ask['original']
            if original['width_policy_contract'] != config_hash or _json(original['widths']) != _json(resolved[original['net']]):
                _refuse('logical_width_scope_changed', 'fixed logical ask does not bind original resolved widths')
    record = {'schema': 1, 'roles': roles, 'phases': phases, 'widths': original_widths,
              'original_receipt_sha256': _hash(original_policy),
              'candidate_receipt_sha256': _hash(candidate_policy),
              'requests_sha256': _hash(original_requests)}
    return json.loads(_json(record))


def verify_contract_record(record, original_pads, candidate_pads, phase_scopes,
                           original_requests, original_policy, candidate_requests, candidate_policy):
    """Owned-child verification against independently read physical identities.

    Source-bound selector/receipt and permitted readback verification precede
    this call. It reconstructs role identities only, never a RemapProof or any
    executor capability. Exact source and final land membership is mandatory.
    """
    from .pinmap_logical import _terminals
    if type(record) is not dict or set(record) != {'schema', 'roles', 'phases', 'widths',
            'original_receipt_sha256', 'candidate_receipt_sha256', 'requests_sha256'} or type(record['schema']) is not int or record['schema'] != 1:
        _refuse('logical_packet_malformed', 'logical projection record has unsupported fields')
    source, source_lands = _terminals(original_pads)
    final, final_lands = _terminals(candidate_pads)
    if source_lands != final_lands:
        _refuse('logical_land_membership_changed', 'written candidate changes source physical lands')
    moving = {pin for pin in source if source[pin] != final[pin]}
    roles = [[net, list(pin), list(pin)] for pin, net in source.items() if pin not in moving]
    for net in sorted(set(source.values()) | set(final.values())):
        old = sorted(pin for pin in moving if source[pin] == net)
        new = sorted(pin for pin in moving if final[pin] == net)
        if len(old) != len(new):
            _refuse('logical_terminal_multiplicity', 'written candidate changes original logical role counts')
        roles.extend([net, list(a), list(b)] for a, b in zip(old, new))
    roles.sort()
    expected = _contract_data(roles, phase_scopes, original_requests, original_policy,
                              candidate_requests, candidate_policy)
    if _json(record) != _json(expected):
        _refuse('logical_projection_changed', 'logical projection differs from independently verified original and written contexts')
    return expected
