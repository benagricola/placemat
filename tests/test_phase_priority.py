"""Per-run named phase ordering retains complete comparison obligations."""
from dataclasses import replace
import pytest
from placemat.score import Standing, rank, Validity
from placemat.settings import Settings

def board(closures, clean):
    return Standing({'v': 2, 'airwire_mm': 10.0}, closures=closures, clean=clean,
                    phase_contracts=('power-contract', 'rest-contract'), routed=True,
                    phase_names=('power', 'rest'))

def test_omitted_phase_does_not_precede_whole_closure():
    a, b = board((1., 0.), .9), board((1., 1.), .8)
    assert rank(a, b, Settings()) == 1
    assert rank(a, b, Settings(), phase_priority=('power',)) == -1

def test_supplied_named_order_changes_winner():
    a, b = board((1., .5), .9), board((.5, 1.), .9)
    assert rank(a, b, Settings(), phase_priority=('power', 'rest')) == -1
    assert rank(a, b, Settings(), phase_priority=('rest', 'power')) == 1

@pytest.mark.parametrize('priority', [('missing',), ('power', 'power'), 'power'])
def test_invalid_named_priority_refuses(priority):
    a = board((1., 1.), 1.)
    with pytest.raises(ValueError):
        rank(a, a, Settings(), phase_priority=priority)

def test_omitted_phase_contract_still_must_match_before_validity():
    a = board((1., 1.), 1.)
    b = replace(a, phase_contracts=('power-contract', 'different-rest'), validity=Validity(drc_new=1))
    with pytest.raises(ValueError, match='incomparable'):
        rank(a, b, Settings(), phase_priority=('power',))

def test_missing_complete_names_refuses_override():
    a = board((1., 1.), 1.)
    with pytest.raises(ValueError):
        rank(replace(a, phase_names=None), a, Settings(), phase_priority=('power',))

def test_default_uses_original_phase_order_and_ties_keep_incumbent():
    a, b = board((1., .5), .9), board((.5, 1.), .9)
    assert rank(a, b, Settings()) == -1
    assert rank(a, a, Settings(), phase_priority=('rest',)) == 0


def test_explore_takes_named_priority_through_authoritative_report():
    from placemat.explore import _taken

    def routed(seed, rest, clean):
        return {'seed': seed, 'drc_new': 0, 'widths_failed': 0,
                'critical_checks': 0, 'critical_unknown': [], 'final_findings': {},
                'closure_clean': clean,
                'phases': [{'name': 'power', 'comparison_contract': 'power-contract',
                            'final_closure_clean': 1.},
                           {'name': 'rest', 'comparison_contract': 'rest-contract',
                            'final_closure_clean': rest}]}

    routes = [routed(0, 0., .9), routed(1, 1., .8)]
    measures = {seed: {'v': 2, 'airwire_mm': 10.} for seed in (0, 1)}
    assert _taken(routes, measures, Settings()) == 1
    assert _taken(routes, measures, Settings(), phase_priority=('power',)) == 0
