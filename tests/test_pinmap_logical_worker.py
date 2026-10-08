from dataclasses import replace
import pytest
from placemat.pinmap_common import CandidateRefused
from placemat.pinmap_logical_worker import _verify_pools
from tests.test_pinmap_common import scene


def candidate(geometry):
    fp = geometry.footprint('U1')
    reverse = dict(zip('ABCD', 'DCBA'))
    mapped = replace(fp, pads=tuple(replace(pad, net=reverse[pad.net]) for pad in fp.pads))
    return replace(geometry, footprints=tuple(mapped if item.ref == fp.ref else item for item in geometry.footprints),
                   _by_ref={}, _by_inst={})


def test_independent_saved_pool_rules_allow_complete_permutation():
    board, _, _, _ = scene()
    proof = _verify_pools(board.geometry, candidate(board.geometry), ())
    assert len(proof) == 1 and proof[0]['ref'] == 'U1'
    assert len(proof[0]['mapping']) == 4


@pytest.mark.parametrize('fields,quiet', [({'Pm.PinFixed': '1'}, ()),
    ({'Pm.PinAllow': 'A:1'}, ()), ({'Pm.PinDeny': 'A:4'}, ()), ({}, ('A',))])
def test_held_or_disallowed_pool_endpoint_cannot_be_reassigned(fields, quiet):
    board, _, _, _ = scene(fields=fields)
    with pytest.raises(CandidateRefused):
        _verify_pools(board.geometry, candidate(board.geometry), quiet)


def test_physical_cell_members_with_external_terminals_keep_pool_support():
    board, _, _, _ = scene(cell='group')
    assert _verify_pools(board.geometry, candidate(board.geometry), ())


def test_missing_physical_land_refuses_before_rule_mapping():
    board, _, _, _ = scene()
    new = candidate(board.geometry)
    fp = new.footprint('U1')
    new = replace(new, footprints=tuple(replace(fp, pads=fp.pads[:-1]) if item.ref == fp.ref else item for item in new.footprints),
                  _by_ref={}, _by_inst={})
    with pytest.raises(CandidateRefused) as error:
        _verify_pools(board.geometry, new, ())
    assert error.value.code == 'logical_land_membership_changed'


@pytest.mark.parametrize('deadline', [True, 'tomorrow', 10 ** 1000])
def test_malformed_owned_deadline_refuses_before_native_import(deadline, monkeypatch):
    from placemat.pinmap_logical_worker import evaluate
    from placemat import final_check_worker
    monkeypatch.setattr(final_check_worker, '_runtime_identity', lambda: pytest.fail('native runtime must not load'))
    packet = {'schema': 1, 'deadline_utc': deadline, 'original': {}, 'candidate': {},
              'logical': {}, 'expected_readback': {}, 'input_bundle': {}, 'critical_original': {}, 'critical_candidate': {}}
    with pytest.raises(CandidateRefused) as error:
        evaluate(packet)
    assert error.value.code == 'logical_worker_request_malformed'


def test_wholly_internal_physical_cell_net_is_held():
    board, _, _, _ = scene(cell='group')
    geometry = replace(board.geometry,
        footprints=tuple(replace(fp, cell='group') if fp.ref == 'TP4' else fp for fp in board.geometry.footprints),
        _by_ref={}, _by_inst={})
    with pytest.raises(CandidateRefused):
        _verify_pools(geometry, candidate(geometry), ())


def test_hard_group_order_is_revalidated_from_declared_fields():
    board, _, _, _ = scene(fields={'Pm.PinGroup': 'PAIR!:1-2'})
    with pytest.raises(CandidateRefused) as error:
        _verify_pools(board.geometry, candidate(board.geometry), ())
    assert error.value.code == 'logical_hard_group_changed'


@pytest.mark.parametrize('field', ['rules', 'acceptances', 'board_shape', 'quiet', 'planes', 'pending'])
def test_candidate_cannot_weaken_original_check_intent(field, monkeypatch):
    from copy import deepcopy
    import time
    from placemat.pinmap_logical_worker import evaluate
    from placemat import final_check_worker
    monkeypatch.setattr(final_check_worker, '_runtime_identity', lambda: pytest.fail('native runtime must not load'))
    deadline = time.time() + 30
    context = {key: [] for key in ('rules', 'acceptances', 'board_shape', 'board_cutouts', 'quiet', 'planes', 'pending')}
    context.update(settings={}, edge_margin=0.0, component_spacing=0.0, fields={}, source_physical={})
    changed = deepcopy(context)
    changed[field] = ['changed']
    request = {'schema': 1, 'deadline_utc': deadline, 'original': {'deadline_utc': deadline},
               'candidate': {'deadline_utc': deadline}, 'logical': {}, 'expected_readback': {}, 'input_bundle': {},
               'critical_original': context, 'critical_candidate': changed}
    with pytest.raises(CandidateRefused) as error:
        evaluate(request)
    assert error.value.code == 'logical_original_check_intent_changed'
    assert error.value.facts['field'] == field


@pytest.mark.parametrize('severity,effective,expected', [('warning', True, 1.0), ('error', True, 0.0), ('error', False, 1.0)])
def test_logical_whole_closure_uses_effective_real_errors(severity, effective, expected):
    from placemat.kicad import drc
    from placemat.pinmap_logical_worker import _clean_whole
    if not hasattr(drc, 'real_errors'):
        pytest.skip('combined Step1 effective real-error classifier is required')
    data = {'violations': [{'type': 'clearance', 'severity': severity,
                           'items': [{'description': 'Track [A]', 'pos': {'x': 1.0, 'y': 2.0}}]}]}
    result = _clean_whole({'A': 1}, {}, data, lambda kind: effective and kind == 'clearance', set())
    assert result.closure_clean == expected


@pytest.mark.parametrize('before,after,code', [({}, {'A': 1}, 'logical_zero_denominator_opened'),
    ({'A': 1}, {'A': 2}, 'logical_final_open_exceeds_denominator')])
def test_original_whole_denominator_cannot_certify_new_opens(before, after, code):
    from placemat.pinmap_logical_worker import _clean_whole
    with pytest.raises(CandidateRefused) as error:
        _clean_whole(before, after, {}, lambda kind: True, set())
    assert error.value.code == code
    assert error.value.facts['original_open'] == before and error.value.facts['open_after'] == after
