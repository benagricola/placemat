"""Counted report-domain controls; no native geometry authority is supplied."""
from placemat.kicad.manufacturing_failure_count import failure_count


def original(kind='clearance', ids=('a', 'b'), severity='error'):
    return {'type': kind, 'severity': severity,
            'items': [{'uuid': uid} for uid in ids]}


def mandatory(ids=('a', 'b')):
    return {'uuids': list(ids)}


def test_overlapping_original_and_floor_failure_count_once():
    assert failure_count([original()], [mandatory(('b', 'a'))]) == 1


def test_distinct_original_error_remains_separate():
    assert failure_count([original('shorting_items')], [mandatory()]) == 2


def test_distinct_pair_remains_separate():
    assert failure_count([original()], [mandatory(('a', 'c'))]) == 2


def test_report_multiplicity_retained_by_maximum():
    assert failure_count([original(), original()], [mandatory()]) == 2
    assert failure_count([original()], [mandatory(), mandatory(), mandatory()]) == 3


def test_original_warning_does_not_add_error_count():
    assert failure_count([original(severity='warning')], [mandatory()]) == 1
