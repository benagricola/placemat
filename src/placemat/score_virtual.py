"""Placement-only pin finalist receipts shared by live and resumed ensembles.

The checkpoint's board/script/settings digest supplies the external context.
These receipts bind the exact source row and the independently evaluated
baseline/candidate; they do not certify a routed board or a writer result.
"""
from dataclasses import asdict
import hashlib
import json
import math

from .score import Validity

VERSION = 1
FIELD = 'placement_comparison'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def source_identity(seed, objective, measures):
    return digest({'seed': seed, 'objective': objective,
                   'measures': {k: v for k, v in measures.items() if k != FIELD}})


def receipt(board, plan, proposal, seed, objective, measures):
    """Bind a current combined evaluation before publishing the worker row."""
    selected = proposal['final'] if proposal.get('actionable') else proposal['baseline']
    known = (not selected.get('refusals') and not selected['validity'].get('unmeasured')
             and not proposal['baseline'].get('refusals')
             and not proposal['baseline']['validity'].get('unmeasured')
             and selected.get('total') is not None and proposal['baseline'].get('total') is not None)
    context = digest({'settings': asdict(board.settings), 'geometry': repr(board.geometry),
                      'items': repr(plan.occupancy.items), 'copper': repr(plan.occupancy.copper),
                      'pending': sorted(plan.occupancy.pending),
                      'cell_areas': repr(getattr(plan.occupancy, '_cell_rule_areas', {})),
                      'links': repr(getattr(plan, 'links', ())), 'pushes': repr(getattr(plan, 'pushes', ())),
                      'lanes': repr(getattr(board, '_escapes', ())),
                      'quiet': sorted(board._plane_nets()) if hasattr(board, '_plane_nets') else [],
                      'free': sorted(getattr(board, '_free_nets', ()))})
    measures['placement_context'] = context
    proof = {'v': VERSION, 'scope': 'placement', 'state': 'measured' if known else 'unknown',
             'source': source_identity(seed, objective, measures), 'context': context,
             'baseline': proposal['baseline'], 'candidate': selected,
             'selection': proposal.get('groups', []) if proposal.get('actionable') else [],
             'objective': (objective + (selected['total'] - proposal['baseline']['total'])) if known else None}
    return {**proof, 'digest': digest(proof)}


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validity(value):
    if not isinstance(value, dict) or set(value) != {'unplaced', 'drc_new', 'widths_failed', 'critical', 'unmeasured'}:
        raise ValueError('malformed validity')
    unplaced = value['unplaced']
    if not isinstance(unplaced, (list, tuple)) or len(unplaced) != 3 or not all(map(_count, unplaced)):
        raise ValueError('malformed unplaced counts')
    if value['drc_new'] is not None and not _count(value['drc_new']):
        raise ValueError('malformed DRC count')
    if not all(_count(value[k]) for k in ('widths_failed', 'critical')):
        raise ValueError('malformed validity counts')
    if not isinstance(value['unmeasured'], (list, tuple)):
        raise ValueError('malformed unmeasured evidence')
    return Validity(tuple(unplaced), value['drc_new'], value['widths_failed'], value['critical'],
                    tuple(value['unmeasured']))


def standing(row, record):
    """Return measured validity/objective, or explicit unknown evidence.

    Source-only fallback cannot acquire virtual validity from a legacy scalar.
    Unknown receipts use the source counts plus a missing-proof obligation.
    """
    seed, objective, measures = row
    source = Validity.of(measures, drc_new=measures.get('drc'))
    unknown = Validity(source.unplaced, source.drc_new, source.widths_failed, source.critical,
                       source.unmeasured + ('placement_comparison_unmeasured',))
    try:
        if not isinstance(record, dict):
            raise ValueError('missing comparison')
        proof = {k: v for k, v in record.items() if k != 'digest'}
        if (type(record['v']) is not int or record['v'] != VERSION or record['scope'] != 'placement'
                or record['digest'] != digest(proof)
                or record['source'] != source_identity(seed, objective, measures)
                or not isinstance(record['context'], str) or len(record['context']) != 64
                or record['context'] != measures.get('placement_context')):
            raise ValueError('stale comparison')
        candidate, baseline = record['candidate'], record['baseline']
        validity = _validity(candidate['validity'])
        baseline_validity = _validity(baseline['validity'])
        if (record['state'] != 'measured' or candidate.get('refusals') or validity.unmeasured
                or baseline.get('refusals') or baseline_validity.unmeasured):
            return unknown, math.inf
        values = (record['objective'], candidate['total'], baseline['total'])
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError('unmeasured objective')
        if record['objective'] != objective + (candidate['total'] - baseline['total']):
            raise ValueError('unrelated candidate objective')
        if (validity.key(), candidate['total']) > (baseline_validity.key(), baseline['total']):
            raise ValueError('candidate does not improve the evaluated baseline')
        return validity, record['objective']
    except (KeyError, TypeError, ValueError, OverflowError):
        return unknown, math.inf
