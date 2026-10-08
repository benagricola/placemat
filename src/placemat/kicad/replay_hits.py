"""Unique actual static-hit attribution and one deterministic prior cohort.

This selects provenance, not an escape corridor or a Standing certificate. The
router records a first-hit midpoint for a net/layer aggregate. Ambiguous hits
remain unknown rather than authorizing removal of every item on that net.
"""
from collections import Counter
import json
import math
from pathlib import Path

from . import issued_calls, replay_inventory
from .board_forms import read_forms
from .final_call import ProofUnavailable


def _refuse(reason):
    raise ProofUnavailable('replay_hit_board_unproved', reason=reason)


def _atom(value):
    if not isinstance(value, str):
        _refuse('non-atom field')
    try:
        return json.loads(value) if value.startswith('"') else value
    except ValueError as error:
        raise ProofUnavailable('replay_hit_board_unproved', reason='malformed string') from error


def _fields(form):
    fields = {}
    for value in form[1:]:
        if isinstance(value, (list, tuple)) and value:
            if value[0] in fields:
                _refuse('duplicate primitive field')
            fields[value[0]] = value[1:]
    return fields


def _tracks(path):
    root = read_forms(path, _refuse)
    names = {}
    for node in root:
        if isinstance(node, list) and node and node[0] == 'net':
            if len(node) != 3 or node[1] in names:
                _refuse('ambiguous net declaration')
            names[node[1]] = _atom(node[2])
    result = []
    for node in root:
        if not isinstance(node, list) or not node or node[0] != 'segment':
            continue
        fields = _fields(node)
        try:
            start, end = fields['start'], fields['end']
            if len(start) != 2 or len(end) != 2 or len(fields['net']) != 1 or len(fields['layer']) != 1:
                _refuse('malformed segment scope')
            points = [float(v) for v in (*start, *end)]
            if not all(math.isfinite(v) for v in points):
                _refuse('nonfinite segment coordinate')
            net = fields['net'][0]
            name = _atom(net) if net.startswith('"') else names[net]
            # Match the pinned router's literal floating midpoint expression.
            at = ((points[0] + points[2]) / 2, (points[1] + points[3]) / 2)
            result.append((name, _atom(fields['layer'][0]), at, replay_inventory._freeze(node)))
        except (KeyError, ValueError, TypeError) as error:
            raise ProofUnavailable('replay_hit_board_unproved', reason='unresolved segment') from error
    return result


def select_cohort(grader, ledger, executor, final_call, failed_nets):
    """Select only unique generated hit items from the earliest actual call.

    `failed_nets` comes from the original fixed final judgments. Every name must
    also belong to the actual final call; the raw hit records are read from its
    privately retained complete summary, never caller-supplied observations.
    """
    final = issued_calls.completed_record(grader, ledger, executor, final_call)
    replay_inventory.supported_completed_work(grader, ledger, executor)
    if (not isinstance(failed_nets, (list, tuple, set)) or not failed_nets
            or any(not isinstance(net, str) or not net for net in failed_nets)
            or not set(failed_nets).issubset(final['nets'])):
        raise ProofUnavailable('replay_failed_scope_unproved')
    issued_calls._unchanged(final['actual_input_files'])
    tracks = _tracks(final['input'])
    prior = []
    for token in ledger.issued:
        if token is final_call:
            break
        record = issued_calls.completed_record(grader, ledger, executor, token)
        before = replay_inventory._forms(replay_inventory._source_snapshot(record))[0]
        after = replay_inventory._forms(record['output'])[0]
        prior.append((token, Counter(after) - Counter(before)))
    evidence = final['raw']['summary'].get('net_evidence')
    if not isinstance(evidence, dict):
        raise ProofUnavailable('replay_static_evidence_unavailable')
    hits, unknown = [], []
    for net in sorted(failed_nets):
        entry = evidence.get(net, {})
        if not isinstance(entry, dict):
            raise ProofUnavailable('replay_static_evidence_malformed')
        records = entry.get('blocked_by', [])
        if not isinstance(records, list):
            raise ProofUnavailable('replay_static_evidence_malformed')
        for index, observation in enumerate(records):
            key = {'failed_net': net, 'evidence_index': index}
            if (not isinstance(observation, dict) or observation.get('found_by') != 'static'
                    or observation.get('kind') != 'track'):
                unknown.append(dict(key, reason='unsupported static observation'))
                continue
            at = observation.get('at')
            if (not isinstance(at, list) or len(at) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in at)):
                unknown.append(dict(key, reason='unmeasured midpoint'))
                continue
            matches = [form for name, layer, midpoint, form in tracks
                       if name == observation.get('net') and layer == observation.get('layer')
                       and midpoint == tuple(at)]
            if len(matches) != 1:
                unknown.append(dict(key, reason='midpoint is not unique', matches=len(matches)))
                continue
            owners = [token for token, generated in prior if generated[matches[0]] == 1]
            if len(owners) != 1:
                unknown.append(dict(key, reason='generated owner is not unique', matches=len(owners)))
                continue
            hits.append((owners[0], matches[0], key))
    issued_calls._unchanged(final['actual_input_files'])
    if not hits:
        raise ProofUnavailable('replay_generated_cohort_unavailable', unknown=unknown)
    token = next(token for token, _ in prior if any(owner is token for owner, _, _ in hits))
    selected = tuple(sorted({form for owner, form, _ in hits if owner is token}))
    proof = replay_inventory.walls_at_final_call(grader, ledger, executor, token, final_call, selected=selected)
    return token, selected, {'inventory': proof, 'unknown': unknown,
                             'selected_hits': [key for owner, _, key in hits if owner is token]}
