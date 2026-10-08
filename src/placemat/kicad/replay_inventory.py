"""Exact generated-wall inventory for one privately completed call.

This proves provenance and multiplicity only. It neither proves an obstruction
nor selects walls by net name, and does not change source or candidate copper.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
from decimal import Decimal
import re

from . import issued_calls
from .board_forms import protected_forms
from .final_call import ProofUnavailable, file_hash, record_digest


def _forms(path):
    def refuse(reason):
        raise ProofUnavailable('replay_board_forms_unproved', reason=reason)
    return protected_forms(path, refuse)


def _source_snapshot(record):
    name = Path(record['source']).name
    matches = [path for path in record['input_snapshots']
               if Path(path).name.partition('-')[2] == name]
    if len(matches) != 1:
        raise ProofUnavailable('replay_source_snapshot_ambiguous')
    return Path(matches[0])


def _freeze(value):
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if not isinstance(value, str):
        raise ProofUnavailable('replay_wall_form_malformed')
    return value


def _physical_identity(form):
    """Exact primitive fields, excluding UUID/tstamp and derived lock status.

    Numeric atoms normalize spelling only; coordinates and ordered arrays are
    retained. This catches distinct UUIDs at the same physical geometry without
    treating the router midpoint as a unique identifier.
    """
    def canonical(value):
        if isinstance(value, tuple):
            return tuple(canonical(item) for item in value)
        if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value):
            return str(Decimal(value).normalize())
        return value
    value = canonical(tuple(item for item in form
                            if item != 'locked' and not (isinstance(item, tuple) and item
                                                        and item[0] in ('uuid', 'tstamp', 'locked'))))
    if value[0] == 'segment':
        fields = {item[0]: item[1:] for item in value[1:] if isinstance(item, tuple) and item}
        if 'start' not in fields or 'end' not in fields:
            raise ProofUnavailable('replay_wall_form_malformed')
        # Track direction is not physical identity. Preserve each coordinate
        # tuple, but normalize the unordered pair of endpoints.
        a, b = sorted((fields['start'], fields['end']))
        return ('segment', a, b, fields.get('width'), fields.get('layer'), fields.get('net'))
    return value


def proved_walls(grader, ledger, executor, token, *, final_input, selected):
    """Bind a caller's exact attributed wall forms to the actual completed call.

    Attribution must already be unique and scope-bound. At most one occurrence
    of each selected primitive is supported; duplicate/ambiguous identities
    refuse. Original fixed copper and all original zone intent are retained.
    The returned JSON is transport, not authorization to execute or adopt.
    """
    record = issued_calls.completed_record(grader, ledger, executor, token)
    if not isinstance(selected, (list, tuple)) or not selected:
        raise ProofUnavailable('replay_wall_inventory_missing')
    selected = tuple(_freeze(item) for item in selected)
    if (len(set(selected)) != len(selected)
            or any(not item or item[0] not in ('segment', 'via') for item in selected)):
        raise ProofUnavailable('replay_wall_inventory_unsupported')
    original, original_zones = _forms(grader._original)
    before, before_zones = _forms(_source_snapshot(record))
    after, after_zones = _forms(record['output'])
    current, current_zones = _forms(final_input)
    if (Counter(original) - Counter(current) or original_zones != current_zones
            or before_zones != after_zones):
        raise ProofUnavailable('replay_original_intent_unproved')
    generated = Counter(after) - Counter(before)
    physical = Counter(_physical_identity(item) for item in current)
    for item in selected:
        if (Counter(original)[item] or generated[item] != 1
                or Counter(after)[item] != 1 or Counter(current)[item] != 1
                or physical[_physical_identity(item)] != 1):
            raise ProofUnavailable('replay_wall_origin_ambiguous')
    # Removing precisely these occurrences must retain every other current item.
    retained = Counter(current)
    retained.subtract(selected)
    if Counter(original) - retained:
        raise ProofUnavailable('replay_original_copper_selected')
    return {
        'schema': 1,
        'issued_call_sha256': record_digest(record),
        'identity': deepcopy(record['identity']),
        'original_sha256': file_hash(grader._original),
        'final_input': str(Path(final_input).resolve()),
        'final_input_sha256': file_hash(final_input),
        'removed_forms': deepcopy(selected),
        'retained_forms_sha256': record_digest(sorted(retained.elements())),
        'zone_intent_sha256': record_digest(current_zones),
    }


def walls_at_final_call(grader, ledger, executor, prior_call, final_call, *, selected):
    """Use only the actual final ordinary single call's retained issued input.

    This is still an inventory receipt. Complete-board comparison and owned
    proposal accounting remain separate requirements.
    """
    final = issued_calls.completed_record(grader, ledger, executor, final_call)
    identity = final['identity']
    if (identity['kind'] != 'single' or final_call is prior_call
            or identity['phase'] != len(grader._phases) - 1
            or identity['phase'] >= len(ledger.call_plans)):
        raise ProofUnavailable('replay_final_call_unproved')
    plan, fingerprint = ledger.call_plans[identity['phase']]
    if (record_digest(plan) != fingerprint or not plan['calls']
            or identity['call'] != len(plan['calls']) - 1
            or plan['calls'][-1]['kind'] not in ('nets', 'rest')
            or ledger.issued[-1] is not final_call):
        raise ProofUnavailable('replay_later_work_unproved')
    path = Path(final['input'])
    expected = final['actual_input_files'].get(str(path.resolve()))
    if expected is None or not path.is_file() or file_hash(path) != expected:
        raise ProofUnavailable('replay_final_input_changed')
    result = proved_walls(grader, ledger, executor, prior_call,
                          final_input=path, selected=selected)
    result['final_issued_call_sha256'] = record_digest(final)
    return result


def _supported_work(grader, ledger, executor, pending_final=None):
    """Withhold when the actual ordered pipeline contains unrecorded work.

    This deliberately excludes pair/bus custody and skipped or resumed plans.
    A connection call must cover every planned task with actual completed wave
    receipts; a selector declaration alone cannot satisfy this inventory.
    """
    issued_calls._owner(grader, ledger, executor, writing=False)
    if len(ledger.call_plans) != len(grader._phases):
        raise ProofUnavailable('replay_work_list_incomplete')
    if pending_final is not None:
        if (not isinstance(pending_final, tuple) or len(pending_final) != 2
                or any(type(index) is not int for index in pending_final)):
            raise ProofUnavailable('replay_pending_final_unproved')
        phase, index = pending_final
        if (phase != len(grader._phases)-1 or phase < 0
                or index != len(ledger.call_plans[phase][0]['calls'])-1 or index < 0
                or ledger.call_plans[phase][0]['calls'][index]['kind'] not in ('nets', 'rest')):
            raise ProofUnavailable('replay_pending_final_unproved')
    records = [issued_calls.completed_record(grader, ledger, executor, token)
               for token in ledger.issued]
    valid_indices = {(phase, index) for phase, (plan, _) in enumerate(ledger.call_plans)
                     for index in range(len(plan['calls']))}
    if any((record['identity']['phase'], record['identity']['call']) not in valid_indices
           for record in records):
        raise ProofUnavailable('replay_work_list_extra_call')
    for phase, (plan, fingerprint) in enumerate(ledger.call_plans):
        if record_digest(plan) != fingerprint:
            raise ProofUnavailable('replay_work_list_changed')
        for index, call in enumerate(plan['calls']):
            expected_kind = {'nets': 'single', 'rest': 'single',
                             'tasks': 'connections', 'pour': 'pour'}.get(call['kind'])
            own = [record for record in records
                   if record['identity']['phase'] == phase and record['identity']['call'] == index]
            if pending_final == (phase, index):
                if own:
                    raise ProofUnavailable('replay_pending_final_already_issued')
                continue
            if expected_kind is None or not own or any(
                    record['identity']['kind'] != expected_kind for record in own):
                raise ProofUnavailable('replay_work_list_unsupported')
            if expected_kind != 'connections' and len(own) != 1:
                raise ProofUnavailable('replay_work_list_duplicate')
            if expected_kind == 'connections':
                planned = {record_digest(issued_calls._task(task)) for task in call['tasks']}
                completed = {record_digest(task) for record in own for task in record['tasks']}
                if planned != completed:
                    raise ProofUnavailable('replay_task_wave_scope_incomplete')
    return {'plans_sha256': record_digest([plan for plan, _ in ledger.call_plans]),
            'issued_calls_sha256': record_digest(records)}


def supported_completed_work(grader, ledger, executor):
    return _supported_work(grader, ledger, executor)


def _executor_prior_work(grader, ledger, executor, *, phase, call):
    """Before the exact final single issue, prove every other planned call complete.

    No incomplete token is ignored. Only the uniquely identified final planned
    nets/rest call may be absent; this is transport provenance, not adoption.
    """
    proof = _supported_work(grader, ledger, executor, (phase, call))
    records = [issued_calls.completed_record(grader, ledger, executor, token)
               for token in ledger.issued]
    return proof, records
