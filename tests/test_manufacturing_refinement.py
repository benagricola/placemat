from copy import deepcopy
import pytest
from placemat.kicad.manufacturing_refinement import refine_pair, Unproved

def packet():
    grades = {s: {'known': False, 'unproved': [
        'original_size_floor_below_factory_annular',
        'local_clearance_overrides_unproved'], 'open': n,
        'drc':0,'undersized':0,'widths_unknown':False,'quality':[1,2,3]}
        for s, n in (('legacy', 1), ('pocket', 0))}
    measurement = {'mode': 'retained_current_measurement',
        'comparison_authority': False, 'request_sha256': 'bound',
        'sides': {s: {'annular': {'known': True, 'under': []},
                     'original_rules_drc_validated': True}
                  for s in grades}}
    return grades, measurement

def test_specific_reason_only_and_original_immutable():
    grades, measurement = packet(); before = deepcopy(grades); checks=[]
    result = refine_pair(grades, measurement, expected_request_sha256='bound',
        mandatory_maps={'GND': .28, 'VCC': .28}, check_current=lambda: checks.append(True))
    assert checks == [True, True] and grades == before
    for grade in result.values():
        assert grade['known'] is False
        assert grade['unproved'] == ['local_clearance_overrides_unproved',
                                     'mandatory_clearance_maps_unproved']

@pytest.mark.parametrize('field,value', [('mode','saved_pair_diagnostic_only'),
    ('comparison_authority',True), ('request_sha256','other')])
def test_historical_or_unbound_measurement_refuses(field,value):
    grades, measurement=packet();measurement[field]=value
    with pytest.raises(Unproved,match='current_measurement_binding'):
        refine_pair(grades,measurement,expected_request_sha256='bound',
                    mandatory_maps={},check_current=lambda:None)

def test_post_interpretation_original_change_refuses():
    grades,measurement=packet(); calls=[]
    def check():
        calls.append(True)
        if len(calls)==2:raise Unproved('source_changed')
    with pytest.raises(Unproved,match='source_changed'):
        refine_pair(grades,measurement,expected_request_sha256='bound',
                    mandatory_maps={},check_current=check)

@pytest.mark.parametrize('change',[lambda g:g.pop('quality'),
    lambda g:g.__setitem__('drc',False),lambda g:g.__setitem__('open',-1),
    lambda g:g.__setitem__('widths_unknown',0),lambda g:g.__setitem__('quality',[10**1000,1,1]),
    lambda g:g.__setitem__('quality',[True,1,1])])
def test_unknown_grade_domain_is_fully_validated(change):
    grades,measurement=packet();change(grades['pocket'])
    with pytest.raises(Unproved,match='ordinary_grade_malformed'):
        refine_pair(grades,measurement,expected_request_sha256='bound',mandatory_maps={},check_current=lambda:None)

def test_exhaustive_annular_only_domain_can_be_known_with_zero_maps():
    grades,measurement=packet()
    for g in grades.values():g['unproved']=['original_size_floor_below_factory_annular']
    result=refine_pair(grades,measurement,expected_request_sha256='bound',mandatory_maps={},check_current=lambda:None)
    assert all(g['known'] is True and g['unproved']==[] for g in result.values())


def test_false_grade_without_original_reasons_cannot_be_promoted():
    grades,measurement=packet();grades['pocket']['unproved']=[]
    with pytest.raises(Unproved,match='ordinary_grade_contradictory'):
        refine_pair(grades,measurement,expected_request_sha256='bound',mandatory_maps={},check_current=lambda:None)


def test_unsupported_original_reason_stays_unknown_after_valid_annular_proof():
    grades,measurement=packet()
    for g in grades.values():g['unproved']=['unknown_original_domain','original_size_floor_below_factory_annular']
    result=refine_pair(grades,measurement,expected_request_sha256='bound',mandatory_maps={},check_current=lambda:None)
    assert all(g['known'] is False and g['unproved']==['unknown_original_domain'] for g in result.values())


@pytest.mark.parametrize('bad', [False, True])
def test_complete_native_floor_evidence_resolves_known_domain_without_waiving_invalid(bad):
    grades, measured = packet()
    for side in grades:
        measured['sides'][side]['clearance'] = {
            'complete': True, 'legal': not bad,
            'violations': [{'uuids': ['fixed-a', 'fixed-b']}] if bad else [],
            'original_errors': 0,
            'failure_count': int(bad),
        }
    result = refine_pair(grades, measured, expected_request_sha256='bound',
                         mandatory_maps={'VCC': .28}, check_current=lambda: None)
    assert all(g['known'] is True and g['unproved'] == [] for g in result.values())
    assert all(g['drc'] == int(bad) for g in result.values())
    if bad:
        assert result['pocket']['drc'] > 0  # Existing prefer_pocket refuses invalid copper.


def test_complete_annular_under_is_known_invalid_without_floor_waiver():
    grades, measured = packet()
    for side in grades:
        grades[side]['unproved'] = ['original_size_floor_below_factory_annular']
        measured['sides'][side]['annular']['under'] = [{'uuid': 'controlled-under'}]
    result = refine_pair(grades, measured, expected_request_sha256='bound',
                         mandatory_maps={}, check_current=lambda: None)
    assert all(g['known'] and g['undersized'] == 1 for g in result.values())
