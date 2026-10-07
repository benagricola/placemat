"""A virtual pin candidate never inherits source validity or a legacy scalar."""
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from placemat import score
from placemat.score_virtual import FIELD, digest, receipt, standing
from placemat.settings import Settings


def proof(seed=1, objective=10.0, source_critical=1, final_critical=0, gain=-5.0):
    measures = {'drc': 0, 'findings': {'fixed': source_critical}}
    baseline = {'total': 10.0, 'validity': asdict(score.Validity(drc_new=0, critical=source_critical)),
                'refusals': [], 'terms': {'airwire': 10.0}}
    candidate = {'total': 10.0 - gain, 'validity': asdict(score.Validity(drc_new=0, critical=final_critical)),
                 'refusals': [], 'terms': {'airwire': 10.0 - gain}}
    proposal = {'baseline': baseline, 'final': candidate, 'actionable': True,
                'groups': [{'refs': ['U1'], 'map': [{'ref': 'U1', 'net': 'S', 'to': {'pin': '2'}}]}]}
    board = SimpleNamespace(settings=Settings(), geometry='current physical input')
    plan = SimpleNamespace(occupancy=SimpleNamespace(items={}, copper=[], pending=set()))
    measures[FIELD] = receipt(board, plan, proposal, seed, objective, measures)
    return (seed, objective, measures)


def test_validity_repair_with_negative_soft_gain_beats_invalid_cheaper_source():
    repaired = proof()
    invalid = (2, 1.0, {'drc': 0, 'findings': {'fixed': 1}})
    assert standing(repaired, repaired[2][FIELD])[1] == 15.0
    assert score.placement_key(repaired, {1: 10.0}) < score.placement_key(invalid)


def test_serialized_receipt_has_same_live_and_resumed_rank():
    import json
    row = proof()
    resumed = tuple(json.loads(json.dumps(row)))
    assert score.placement_key(row, {1: 10.0}) == score.placement_key(resumed, {1: 10.0})


@pytest.mark.parametrize('change', ['source', 'seed', 'objective', 'candidate', 'version', 'counts', 'nonfinite'])
def test_stale_or_malformed_record_cannot_certify_a_virtual_candidate(change):
    row = proof()
    seed, objective, measures = deepcopy(row)
    record = measures[FIELD]
    if change == 'source':
        measures['findings']['fixed'] = 0
    elif change == 'seed':
        seed = 7
    elif change == 'objective':
        objective = 9.0
    elif change == 'candidate':
        record['selection'][0]['map'][0]['to']['pin'] = '3'
    elif change == 'version':
        record['v'] = 999
        record['digest'] = digest({k: v for k, v in record.items() if k != 'digest'})
    elif change == 'counts':
        record['candidate']['validity']['critical'] = -1
        record['digest'] = digest({k: v for k, v in record.items() if k != 'digest'})
    else:
        record['objective'] = float('nan')
    validity, total = standing((seed, objective, measures), record)
    assert not validity.valid and validity.unmeasured
    assert total == float('inf')


def test_legacy_scalar_and_unknown_receipt_cannot_beat_known_legal_candidate():
    legal = (0, 100.0, {'drc': 0})
    legacy = (1, 1.0, {'drc': 0})
    assert score.placement_key(legal) < score.placement_key(legacy, {1: 0.0})
    row = proof()
    row[2][FIELD]['state'] = 'unknown'
    row[2][FIELD]['digest'] = digest({k: v for k, v in row[2][FIELD].items() if k != 'digest'})
    assert score.placement_key(legal) < score.placement_key(row, {1: 0.0})


def test_checkpoint_and_live_result_keep_same_validity_repair(tmp_path):
    from placemat import checkpoint, explore
    parts = {key: 'same current context' for key in checkpoint.PARTS}
    ck = checkpoint.Checkpoint(tmp_path, parts, [])
    baseline = (0, 1.0, {'drc': 0, 'findings': {'fixed': 1}})
    repaired = proof()
    ck.start(baseline[1], baseline[2], 10.0, None)
    ck.variant(1, repaired[1], repaired[2], 1.0, {'entries': [], 'orders': {}}, rank=15.0)
    ck.close()
    assert checkpoint.read_best(tmp_path)['seed'] == 1
    prior = checkpoint.Checkpoint(tmp_path, parts, []).load()
    assert prior.best_seed == 1
    compare = explore._variant_order(Settings(), prior.ranks)
    assert compare(prior.done[1], (0, prior.baseline, prior.measures)) < 0


@pytest.mark.parametrize('field', ['context', 'baseline_unknown', 'worse_candidate'])
def test_inconsistent_context_or_baseline_refuses_virtual_certificate(field):
    row = proof()
    record = row[2][FIELD]
    if field == 'context':
        record['context'] = '0' * 64
    elif field == 'baseline_unknown':
        record['baseline']['validity']['unmeasured'] = ['required current check']
    else:
        record['candidate']['validity']['critical'] = 2
    record['digest'] = digest({k: v for k, v in record.items() if k != 'digest'})
    validity, objective = standing(row, record)
    assert validity.unmeasured and objective == float('inf')
