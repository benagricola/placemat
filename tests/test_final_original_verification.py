"""Pure baseline semantic controls; physical mirror coverage is separate."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from placemat.kicad import final_original_verification as verification


def baseline():
    return {'$schema': 'https://schemas.kicad.org/drc.v1.json', 'coordinate_units': 'mm',
            'date': '2026-10-08T00:00:00', 'source': '/original/board.kicad_pcb',
            'kicad_version': '10.0.6', 'included_severities': ['error', 'warning'],
            'ignored_checks': [{'key': 'missing_courtyard', 'description': 'Missing courtyard'}],
            'unconnected_items': [{'items': [{'uuid': 'pad-a', 'description': 'Pad 1 [SIG]',
                                            'pos': {'x': 10.0, 'y': 4.0}},
                                           {'uuid': 'pad-b', 'description': 'Pad 2 [SIG]',
                                            'pos': {'x': 15.0, 'y': 4.0}}]}],
            'violations': [{'type': 'clearance', 'severity': 'error',
                            'description': 'Required .25; actual .20; original custom rule',
                            'items': [{'uuid': 'track-a', 'description': 'Track [SIG]',
                                       'pos': {'x': 12.0, 'y': 4.0}}]}]}


def write(path, record):
    path.write_text(json.dumps(record))
    return verification._semantic_drc(path)


def test_only_time_and_source_location_are_volatile(tmp_path):
    a = baseline()
    b = deepcopy(a)
    b['date'] = '2026-10-08T03:00:00'
    b['source'] = '/owned/original.kicad_pcb'
    b['unconnected_items'][0]['items'].reverse()
    assert write(tmp_path/'a.json', a) == write(tmp_path/'b.json', b)


@pytest.mark.parametrize('mutation', ['severity', 'position', 'identity', 'rule', 'drop_violation',
                                     'drop_open', 'unit', 'version', 'ignored_rule'])
def test_baseline_forgery_is_visible(tmp_path, mutation):
    a = baseline()
    b = deepcopy(a)
    if mutation == 'severity': b['violations'][0]['severity'] = 'warning'
    elif mutation == 'position': b['violations'][0]['items'][0]['pos']['x'] += .01
    elif mutation == 'identity': b['violations'][0]['items'][0]['uuid'] = 'other-track'
    elif mutation == 'rule': b['violations'][0]['description'] = 'Weakened rule'
    elif mutation == 'drop_violation': b['violations'] = []
    elif mutation == 'drop_open': b['unconnected_items'] = []
    elif mutation == 'unit': b['coordinate_units'] = 'in'
    elif mutation == 'version': b['kicad_version'] = 'other'
    elif mutation == 'ignored_rule': b['ignored_checks'].append({'key':'clearance'})
    assert write(tmp_path/'a.json', a) != write(tmp_path/'b.json', b)


@pytest.mark.parametrize('raw', ['{"violations":[],"violations":[],"unconnected_items":[]}',
                               '{"violations":[],"unconnected_items":[],"x":NaN}',
                               '{"violations":{},"unconnected_items":[]}'])
def test_malformed_baseline_refuses(tmp_path, raw):
    p = tmp_path/'baseline.json'
    p.write_text(raw)
    with pytest.raises(verification.ProofUnavailable):
        verification._semantic_drc(p)


@pytest.mark.parametrize('field', ['coordinates', 'polygon_vertices', 'rule_expression'])
def test_ordered_geometry_or_rule_arrays_remain_ordered(tmp_path, field):
    a = baseline()
    a['violations'][0][field] = [1.0, 2.0, 3.0]
    b = deepcopy(a)
    b['violations'][0][field].reverse()
    assert write(tmp_path/'a.json', a) != write(tmp_path/'b.json', b)


def test_unknown_schema_refuses(tmp_path):
    a = baseline()
    a['$schema'] = 'https://schemas.kicad.org/drc.v2.json'
    with pytest.raises(verification.ProofUnavailable):
        write(tmp_path/'a.json', a)


@pytest.fixture
def parent_proof(tmp_path):
    from types import SimpleNamespace
    from placemat.kicad.final_call import file_hash, record_digest
    source = tmp_path / 'source.kicad_pcb'
    source.write_text('original unlocked board')
    original = tmp_path / 'baseline.json'
    write(original, baseline())
    destination = tmp_path / 'candidate'
    root = tmp_path / 'candidate.original-check'
    root.mkdir()
    copied = root / 'original.kicad_pcb'
    copied.write_text('original board with fixed copper locked')
    measured = root / 'drc_before.json'
    write(measured, baseline())
    grader = SimpleNamespace(contract_sha256='a' * 64, _original=source, _baseline=original,
                             _counted=frozenset({'GND'}), _chosen_pours=frozenset(),
                             _open_before={'SIG': 1}, _obligations='[[{"net":"SIG"}]]')
    proof = {'schema': 1, 'original_context_sha256': grader.contract_sha256,
             'source_sha256': file_hash(source), 'copied_sha256': file_hash(copied),
             'copied_path': str(copied), 'measured_drc_path': str(measured),
             'measured_drc_sha256': file_hash(measured),
             'baseline_semantics_sha256': record_digest(verification._semantic_drc(measured)),
             'counted': ['GND'], 'chosen_pours': [], 'open_before': {'SIG': 1},
             'obligations_sha256': record_digest(json.loads(grader._obligations))}
    return grader, proof, destination


def test_parent_checks_original_baseline_artifacts_before_private_import(parent_proof):
    from placemat.kicad.final_owned_worker import _validate_original_proof
    _validate_original_proof(*parent_proof)


@pytest.mark.parametrize('field,value', [('schema', True), ('counted', []),
                                         ('open_before', {'SIG': 0}),
                                         ('obligations_sha256', 'b' * 64),
                                         ('copied_path', '/unowned/board.kicad_pcb')])
def test_parent_rejects_forged_original_proof_fields(parent_proof, field, value):
    from placemat.kicad.final_owned_worker import _validate_original_proof
    from placemat.kicad.final_call import ProofUnavailable
    grader, proof, destination = parent_proof
    proof[field] = value
    with pytest.raises(ProofUnavailable, match='original_proof_mismatch'):
        _validate_original_proof(grader, proof, destination)


def test_parent_rejects_moved_original_violation_even_with_updated_child_hash(parent_proof):
    from placemat.kicad.final_owned_worker import _validate_original_proof
    from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
    grader, proof, destination = parent_proof
    changed = baseline()
    changed['violations'][0]['items'][0]['pos']['x'] += 1
    measured = Path(proof['measured_drc_path'])
    write(measured, changed)
    proof['measured_drc_sha256'] = file_hash(measured)
    proof['baseline_semantics_sha256'] = record_digest(verification._semantic_drc(measured))
    with pytest.raises(ProofUnavailable, match='original_baseline_mismatch'):
        _validate_original_proof(grader, proof, destination)
