"""Scope-bound actual first-hit observations, without native reads or routing."""
import pytest
from placemat.kicad import replay_hits
from placemat.kicad.final_call import ProofUnavailable
from tests.test_replay_inventory import walls, final_call
from tests.test_issued_calls import pour_execution
from tests.test_final_custody import context


def evidence(at):
    return {'net_evidence': {'N': {'blocked_by': [dict(found_by='static', kind='track',
                                                     net='N', layer='F.Cu', at=at)]}}}


@pytest.fixture(autouse=True)
def named_board_source(monkeypatch, request):
    from tests import test_pour_identity, test_replay_inventory
    monkeypatch.setattr(test_pour_identity, 'BOARD',
                        test_pour_identity.BOARD.replace('(kicad_pcb ', '(kicad_pcb (net 1 "N") '))
    if getattr(request, 'param', False):
        monkeypatch.setattr(test_replay_inventory, 'WALL',
                            '(segment (start 1 2) (end 3 4) (width .4) (layer "F.Cu")'
                            ' (net 1) (uuid "wall"))')


@pytest.mark.parametrize('final_call', [evidence([2.5, 0])], indirect=True)
def test_actual_unique_hit_selects_one_generated_prior_call(walls, final_call):
    hook, prior, _, selected = walls
    token, forms, receipt = replay_hits.select_cohort(hook.grader, hook.ledger, hook.executor,
                                                    final_call, ['N'])
    assert token is prior and forms == tuple(selected)
    assert receipt['unknown'] == []
    assert receipt['selected_hits'] == [{'failed_net': 'N', 'evidence_index': 0}]


@pytest.mark.parametrize('named_board_source', [True], indirect=True)
@pytest.mark.parametrize('final_call', [evidence([2, 3])], indirect=True)
def test_original_and_generated_same_midpoint_different_width_remains_unknown(walls, final_call, named_board_source):
    hook = walls[0]
    with pytest.raises(ProofUnavailable, match='generated_cohort_unavailable') as caught:
        replay_hits.select_cohort(hook.grader, hook.ledger, hook.executor, final_call, ['N'])
    assert caught.value.facts['unknown'][0]['matches'] == 2


@pytest.mark.parametrize('final_call', [evidence([2.5, 0])], indirect=True)
def test_future_or_unselected_failed_net_cannot_borrow_hit_scope(walls, final_call):
    hook = walls[0]
    with pytest.raises(ProofUnavailable, match='failed_scope_unproved'):
        replay_hits.select_cohort(hook.grader, hook.ledger, hook.executor, final_call, ['FUTURE'])


@pytest.mark.parametrize('final_call', [{'net_evidence': {'N': []}}], indirect=True)
def test_malformed_actual_retained_evidence_refuses_structurally(walls, final_call):
    hook = walls[0]
    with pytest.raises(ProofUnavailable, match='static_evidence_malformed'):
        replay_hits.select_cohort(hook.grader, hook.ledger, hook.executor, final_call, ['N'])


@pytest.mark.parametrize('walls', [True], indirect=True)
@pytest.mark.parametrize('final_call', [{'net_evidence': {'N': {'blocked_by':
    [dict(found_by='static', kind='track', net='N', layer='F.Cu', at=[4.5, 0]),
     dict(found_by='static', kind='track', net='N', layer='F.Cu', at=[2.5, 0])]}}}], indirect=True)
def test_earliest_actual_cohort_wins_over_observation_order(walls, final_call):
    hook, prior, _, selected = walls
    token, forms, receipt = replay_hits.select_cohort(hook.grader, hook.ledger, hook.executor,
                                                    final_call, ['N'])
    assert token is prior and forms == tuple(selected)
    assert receipt['selected_hits'] == [{'failed_net': 'N', 'evidence_index': 1}]


@pytest.mark.parametrize('final_call', [{'net_evidence': {'N': {'blocked_by':
    [dict(found_by='static', kind='track', net='N', layer='F.Cu', at=[2.5, 0])]*2}}}], indirect=True)
def test_repeated_hit_keeps_evidence_sequence_but_selects_item_once(walls, final_call):
    hook = walls[0]
    _, forms, receipt = replay_hits.select_cohort(hook.grader, hook.ledger, hook.executor,
                                                final_call, ['N'])
    assert len(forms) == 1 and len(receipt['selected_hits']) == 2


@pytest.mark.parametrize('final_call', [evidence([2.5, 0])], indirect=True)
def test_actual_input_change_during_attribution_cannot_qualify(walls, final_call, monkeypatch):
    original = replay_hits._tracks
    def changed(path):
        tracks = original(path)
        from pathlib import Path
        Path(path).write_text('changed actual input')
        return tracks
    monkeypatch.setattr(replay_hits, '_tracks', changed)
    hook = walls[0]
    with pytest.raises(ProofUnavailable):
        replay_hits.select_cohort(hook.grader, hook.ledger, hook.executor, final_call, ['N'])
