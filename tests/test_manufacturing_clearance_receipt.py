"""Genuine retained request, controlled native producer, actual receipt checks."""
from copy import deepcopy
from pathlib import Path

import pytest

from placemat.kicad.manufacturing_clearance_receipt import validate
from placemat.kicad.manufacturing_annular import Unproved
from placemat.kicad.final_call import ProofUnavailable
from placemat.kicad import manufacturing_current_request as requests
from tests.test_manufacturing_current_prepare import current, controlled_measurement_reply


@pytest.fixture
def measured(current):
    result = []

    def candidate(deadline):
        work = current.tmp / 'measurement'
        work.mkdir()
        packet = requests.prepare(current.budget, current.owner, current.token,
                                  current.raw, current.candidate, current.candidate_files,
                                  work=work)
        result.append((packet, controlled_measurement_reply(packet, work)))
        return {'returncode': 0, 'proposals': 1, 'files': current.candidate_files}

    current.budget.run_replay(current.owner.executor, candidate)
    checks = []

    def check():
        checks.append(True)
        current.budget._check(current.owner.executor)

    return current, result[0][0], result[0][1]['mandatory_clearance'], check, checks


def test_complete_receipt_uses_actual_parent_closure_and_bounded_checks(measured):
    current, packet, receipt, check, checks = measured
    result = validate(packet, receipt, check)
    assert all(side['complete'] and side['legal'] for side in result.values())
    assert len(checks) <= 6  # Whole inventories are not rehashed per copper item.
    assert current.budget.states == ['completed', 'completed']


@pytest.mark.parametrize('kind', [
    'schedule', 'layer', 'duplicate_item', 'delta', 'artifact', 'factory',
    'mode', 'board_path', 'report_path', 'board_symlink',
])
def test_source_bound_floor_receipt_substitution_refuses(measured, kind):
    current, packet, receipt, check, checks = measured
    row = receipt['rows']['candidate']
    if kind == 'schedule':
        row['distinct_floor_passes'].append(deepcopy(row['distinct_floor_passes'][0]))
    elif kind == 'layer':
        row['native_item_domain'][0]['layers'] = ['B.Cu']
    elif kind == 'duplicate_item':
        row['native_item_domain'].append(deepcopy(row['native_item_domain'][0]))
    elif kind == 'delta':
        row['distinct_floor_passes'][0]['project_delta']['floor_iu'] += 1
    elif kind == 'artifact':
        record = row['distinct_floor_passes'][0]['floor_report']
        Path(next(p for p in record['artifacts'] if p.endswith('.stdout'))).write_text('changed')
    elif kind == 'factory':
        row['factory_floor_provenance']['factory_global_floor_iu'] += 1
    elif kind == 'mode':
        receipt['mode'] = 'saved_pair_diagnostic_only'
    elif kind == 'board_path':
        original = Path(row['original_report']['argv'][-1])
        other = current.tmp / 'historical-board.kicad_pcb'
        other.write_bytes(original.read_bytes())
        row['original_report']['argv'][-1] = str(other)
    elif kind == 'report_path':
        record = row['distinct_floor_passes'][0]['floor_report']
        other = current.tmp / 'historical-report.json'
        other.write_bytes(Path(record['argv'][-2]).read_bytes())
        record['argv'][-2] = str(other)
    else:
        original = Path(row['original_report']['argv'][-1])
        other = current.tmp / 'linked-board.kicad_pcb'
        original.rename(other)
        original.symlink_to(other)
    with pytest.raises(Unproved):
        validate(packet, receipt, check)
    assert current.budget.states == ['completed', 'completed']
    with pytest.raises(ProofUnavailable, match='replay_candidate_already_issued'):
        current.budget.run_replay(current.owner.executor, lambda deadline: None)

@pytest.mark.parametrize('original_count,floor_count,kind,expected', [
    (1, 1, 'clearance', 1),
    (2, 1, 'clearance', 2),
    (1, 3, 'clearance', 3),
    (1, 1, 'shorting_items', 2),
])
def test_actual_receipt_to_refinement_counts_overlapping_domains(
        measured, original_count, floor_count, kind, expected):
    import hashlib
    import json
    from placemat.kicad.manufacturing_drc_report import validate as validate_report
    from placemat.kicad.manufacturing_clearance_report import partition
    from placemat.kicad.manufacturing_refinement import refine_pair

    current, packet, receipt, check, checks = measured
    for row in receipt['rows'].values():
        items = row['native_item_domain']
        finding = {'type': 'clearance', 'severity': 'error',
                   'description': 'controlled sealed same-board failure domain',
                   'items': [{'uuid': item['uuid'], 'description': 'controlled item',
                              'pos': {'x': 0, 'y': 0}} for item in items]}
        original = row['original_report']
        floor = row['distinct_floor_passes'][0]['floor_report']
        for record, count, error_type, reverse in (
                (original, original_count, kind, False),
                (floor, floor_count, 'clearance', True)):
            report = deepcopy(record['full_report'])
            report['violations'] = [deepcopy(finding) for _ in range(count)]
            for error in report['violations']:
                error['type'] = error_type
                if reverse:
                    error['items'].reverse()
            path = Path(record['argv'][-2])
            path.write_text(json.dumps(report))
            expected_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            record.update(full_report=report, report_sha256=expected_sha,
                          schema=validate_report(report, Path(record['argv'][-1])))
            record['artifacts'][str(path)] = expected_sha
        level = row['distinct_floor_passes'][0]['requested_floor_iu']
        part = partition(floor['full_report'], items, {}, measured_floor_iu=level,
                         check_current=lambda: None, factory_global_floor_iu=level)
        row['mandatory_partition'].update(passes=[part],
            mapped_violations=part['mapped_violations'], mapped_floor_legal=False)
    result = validate(packet, receipt, check)
    grades = {side: {'known': False, 'unproved': ['local_clearance_overrides_unproved'],
                    'drc': 0, 'undersized': 0, 'widths_unknown': False,
                    'open': 0, 'quality': [0, 0, 0]} for side in result}
    measurement = {'mode': 'retained_current_measurement', 'comparison_authority': False,
                   'request_sha256': 'controlled-refinement-binding',
                   'sides': {side: {'annular': {'known': True, 'under': []},
                                   'original_rules_drc_validated': True,
                                   'clearance': evidence} for side, evidence in result.items()}}
    refined = refine_pair(grades, measurement,
        expected_request_sha256='controlled-refinement-binding', mandatory_maps={}, check_current=check)
    assert all(value['failure_count'] == expected for value in result.values())
    assert all(value['known'] and value['drc'] == expected for value in refined.values())
    assert current.budget.states == ['completed', 'completed']
