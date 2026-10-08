"""The logical owned boundary never accepts public data as execution custody."""
import copy

import pytest

from placemat.pinmap_common import CandidateRefused
from placemat.pinmap_logical_owned import _intent, _pair, check


@pytest.mark.parametrize('record', [
    {}, {'joined': 'yes', 'violated': False, 'under': {}},
    {'joined': 1, 'violated': False, 'under': {}},
    {'joined': True, 'violated': 0, 'under': {}},
    {'joined': True, 'violated': False, 'under': []},
    {'joined': True, 'violated': False, 'under': {'F.Cu': float('nan')}},
    {'joined': True, 'violated': False, 'under': {'F.Cu': True}},
    {'joined': True, 'violated': False, 'under': {'F.Cu': 10 ** 1000}},
    {'joined': True, 'violated': False, 'under': {}, 'width_unknown': 'false'},
])
def test_malformed_final_verdict_cannot_count_as_clean(record):
    from placemat.pinmap_logical_owned import _verdict
    with pytest.raises(CandidateRefused) as got:
        _verdict(record)
    assert got.value.code == 'logical_worker_verdict_malformed'


def test_measured_under_width_is_retained_in_verdict():
    from placemat.pinmap_logical_owned import _verdict
    record = {'joined': True, 'violated': False, 'under': {'F.Cu': 0.2}}
    _verdict(record)
    assert record['under'] == {'F.Cu': 0.2}


@pytest.mark.parametrize('inherited,code', [('99', 'logical_deadline_context_mismatch'),
    ('nan', 'logical_deadline_context_mismatch'), ('bad', 'logical_deadline_invalid')])
def test_earlier_or_malformed_inherited_deadline_cannot_be_extended(inherited, code, monkeypatch):
    from placemat.pinmap_logical_owned import _environment
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC', inherited)
    with pytest.raises(CandidateRefused) as got:
        _environment(100.0)
    assert got.value.code == code
    assert __import__('os').environ['KRT_ROUTE_DEADLINE_UTC'] == inherited


def test_later_inherited_deadline_is_narrowed_to_retained_original(monkeypatch):
    from placemat.pinmap_logical_owned import _environment
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC', '101')
    assert _environment(100.0)['KRT_ROUTE_DEADLINE_UTC'] == '100.0'


def test_final_freshness_rechecks_an_artifact_read_before_later_validation(tmp_path):
    from placemat.pinmap_logical_owned import _artifact_record
    from placemat.pinmap_written import _hash
    paths = [tmp_path / 'final.kicad_pcb', tmp_path / 'final.kicad_pro', tmp_path / 'drc.json']
    for path in paths:
        path.write_text('original checked bytes')
    record = {'artifacts': {str(path.absolute()): _hash(path) for path in paths}}
    _artifact_record(record, tmp_path)
    # A subsequent validation operation changes an already verified output.
    paths[0].write_text('altered during later validation')
    with pytest.raises(CandidateRefused) as got:
        _artifact_record(record, tmp_path)
    assert got.value.code == 'logical_worker_artifact_changed'


def _input_fixture(tmp_path):
    from placemat.pinmap_written import _hash
    bundle, packets, rows = {}, {}, []
    for side in ('original', 'candidate'):
        folder = tmp_path / side
        folder.mkdir()
        source = folder / 'layout.kicad_pcb'
        source.write_text(side + ' permitted pad geometry')
        source.with_suffix('.kicad_pro').write_text('immutable project')
        capture = folder / 'capture.json'
        capture.write_text('immutable capture')
        bundle[side] = {'path': str(source), 'sha256': _hash(source)}
        rules = {'.kicad_pro': _hash(source.with_suffix('.kicad_pro')), '.kicad_dru': None}
        packets[side] = {'binding': {'paths': {'original': str(source)},
            'contract': {'source_inputs': {'rules': rules}, 'invocation': {'capture':
                {'path': str(capture), 'sha256': _hash(capture)}}}}}
    for name, sha in [('layout.kicad_pro', rules['.kicad_pro']), ('layout.kicad_dru', None),
                      ('capture.json', _hash(capture))]:
        rows.append({side: str(tmp_path / side / name) for side in ('original', 'candidate')} | {'sha256': sha})
    bundle['sidecars'] = rows
    return bundle, packets


def test_owned_input_relation_preserves_project_capture_and_absent_custom_rules(tmp_path):
    from placemat.pinmap_logical_worker import _input_bundle
    bundle, packets = _input_fixture(tmp_path)
    _input_bundle(bundle, packets)


@pytest.mark.parametrize('name', ['layout.kicad_pro', 'layout.kicad_dru', 'capture.json'])
def test_child_rechecks_original_sidecar_bytes_and_absence(tmp_path, name):
    from placemat.pinmap_logical_worker import _input_bundle
    bundle, packets = _input_fixture(tmp_path)
    _input_bundle(bundle, packets)
    (tmp_path / 'candidate' / name).write_text('changed after parent verification')
    with pytest.raises(CandidateRefused) as got:
        _input_bundle(bundle, packets)
    assert got.value.code == 'logical_input_sidecar_changed'


def test_capture_must_be_bound_by_complete_input_bundle(tmp_path):
    from placemat.pinmap_logical_worker import _input_bundle
    bundle, packets = _input_fixture(tmp_path)
    bundle['sidecars'].pop()
    with pytest.raises(CandidateRefused) as got:
        _input_bundle(bundle, packets)
    assert got.value.code == 'logical_input_capture_changed'


def test_changed_candidate_rule_receipt_does_not_authorize_changed_original_project(tmp_path):
    from placemat.pinmap_logical_worker import _input_bundle
    from placemat.pinmap_written import _hash
    bundle, packets = _input_fixture(tmp_path)
    path = tmp_path / 'candidate' / 'layout.kicad_pro'
    path.write_text('changed project with independently successful candidate grade')
    packets['candidate']['binding']['contract']['source_inputs']['rules']['.kicad_pro'] = _hash(path)
    with pytest.raises(CandidateRefused) as got:
        _input_bundle(bundle, packets)
    assert got.value.code == 'logical_input_sidecar_changed'


def test_shared_open_counter_uses_first_named_item_once_per_connection():
    from placemat.kicad.drc import open_net_counts
    data = {'unconnected_items': [
        {'items': [{'description': 'unlabeled'}, {'description': 'Pad [A]'}, {'description': 'Pad [B]'}]},
        {'items': [{'description': 'Track [A] and [B]'}]},
        {'items': [{'description': 'nothing named'}]},
        {'items': [{'description': 'Pad [B]'}]}]}
    assert dict(open_net_counts(data)) == {'A': 2, 'B': 1}


@pytest.mark.parametrize('joined,matched,refuses', [(True, True, True), (False, True, False), (True, False, False)])
def test_only_final_joined_matching_narrow_outcome_withholds_projection(joined, matched, refuses):
    pytest.importorskip('placemat.kicad.phase_run', reason='combined Step1 finalized outcome classifier is required')
    from types import SimpleNamespace
    from placemat.pinmap_logical_owned import _narrow_final
    ask = {'net': 'A', 'from': {'ref': 'U1', 'pad': '1'}, 'to': {'ref': 'U2', 'pad': '1'}}
    connection = {**ask, 'status': 'joined_narrow'}
    if not matched:
        connection['to'] = {'ref': 'U3', 'pad': '1'}
    report = SimpleNamespace(phases=[{'connections': [connection]}], asked=[[ask]],
        final_judged=[[{'joined': joined, 'violated': False, 'under': {}}]])
    if refuses:
        with pytest.raises(CandidateRefused) as got:
            _narrow_final(report)
        assert got.value.code == 'logical_narrow_outcome_unsupported'
    else:
        _narrow_final(report)


@pytest.mark.parametrize('severity,effective,drc_new,clean', [('warning', True, 0, 1.0),
    ('error', True, 1, 0.0), ('error', False, 0, 1.0)])
def test_parent_recomputes_final_drc_with_original_baseline_and_effective_kinds(tmp_path, severity, effective, drc_new, clean):
    import json
    from types import SimpleNamespace
    from placemat.kicad import drc, route
    if not hasattr(drc, 'real_errors') or not hasattr(route, 'new_error_count'):
        pytest.skip('combined Step1 original DRC classifier/count authority is required')
    from placemat.pinmap_logical_owned import _whole_from_files
    baseline = tmp_path / 'original-baseline.json'
    baseline.write_text(json.dumps({'violations': []}))
    data = {'violations': [{'type': 'clearance', 'severity': severity,
                           'items': [{'description': 'Track [A]', 'pos': {'x': 1.0, 'y': 2.0}}]}]}
    (tmp_path / 'drc.json').write_text(json.dumps(data))
    side = {'drc_new': drc_new, 'closure_clean': clean, 'open_after': {}}
    cfg = SimpleNamespace(drc_real_kinds=['clearance'] if effective else [])
    _whole_from_files(side, {'A': 1}, set(), baseline, tmp_path, cfg)
    side['closure_clean'] = 1 - clean
    with pytest.raises(CandidateRefused) as got:
        _whole_from_files(side, {'A': 1}, set(), baseline, tmp_path, cfg)
    assert got.value.code == 'logical_whole_artifact_mismatch'


def test_candidate_own_baseline_cannot_hide_original_new_violation(tmp_path):
    import json
    from types import SimpleNamespace
    from placemat.kicad import drc, route
    if not hasattr(drc, 'real_errors') or not hasattr(route, 'new_error_count'):
        pytest.skip('combined Step1 original DRC classifier/count authority is required')
    from placemat.pinmap_logical_owned import _whole_from_files
    baseline = tmp_path / 'original-baseline.json'
    baseline.write_text(json.dumps({'violations': []}))
    data = {'violations': [{'type': 'clearance', 'severity': 'error',
                           'items': [{'description': 'Track [A]', 'pos': {'x': 1.0, 'y': 2.0}}]}]}
    (tmp_path / 'drc.json').write_text(json.dumps(data))
    candidate_baseline = tmp_path / 'candidate-before.json'
    candidate_baseline.write_text(json.dumps(data))
    assert route.new_error_count(candidate_baseline, tmp_path / 'drc.json', lambda _: True) == 0
    with pytest.raises(CandidateRefused) as got:
        _whole_from_files({'drc_new': 0, 'closure_clean': 0.0, 'open_after': {}},
                          {'A': 1}, set(), baseline, tmp_path, SimpleNamespace(drc_real_kinds=['clearance']))
    assert got.value.code == 'logical_whole_artifact_mismatch'


@pytest.mark.parametrize('authority,candidate', [(None, None), ({}, {}), (object(), object())])
def test_public_records_cannot_supply_logical_execution_custody(authority, candidate):
    with pytest.raises(CandidateRefused) as got:
        _pair(authority, candidate)
    assert got.value.code == 'logical_execution_custody_missing'


def test_public_logical_record_refuses_before_owned_execution(tmp_path):
    destination = tmp_path / 'unpublished'
    with pytest.raises(CandidateRefused) as got:
        check({'roles': []}, None, None, None, None, destination)
    assert got.value.code == 'logical_proof_missing'
    assert not destination.exists()


@pytest.mark.parametrize('field', ['rules', 'acceptances', 'board_shape', 'board_cutouts',
                                  'quiet', 'planes', 'pending', 'fields', 'settings'])
def test_candidate_cannot_weaken_original_critical_context(field):
    keys = ('settings', 'rules', 'acceptances', 'edge_margin', 'component_spacing',
            'board_shape', 'board_cutouts', 'quiet', 'planes', 'pending', 'fields')
    original = {key: [] for key in keys}
    candidate = copy.deepcopy(original)
    candidate[field] = {'weakened': True}
    with pytest.raises(CandidateRefused) as got:
        _intent(original, candidate)
    assert got.value.code == 'logical_original_check_intent_changed'
    assert original == {key: [] for key in keys}


def test_exact_context_allows_only_separate_source_geometry_manifest():
    keys = ('settings', 'rules', 'acceptances', 'edge_margin', 'component_spacing',
            'board_shape', 'board_cutouts', 'quiet', 'planes', 'pending', 'fields')
    a = {key: [] for key in keys}
    b = copy.deepcopy(a)
    a['source_physical'], b['source_physical'] = {'pads': 'original'}, {'pads': 'proved written'}
    _intent(a, b)
