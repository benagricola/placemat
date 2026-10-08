"""Ordinary-grade refinement after owned fresh native measurement.

This is never a Standing publisher. The caller must bind measurement to the
actual retained factory, original capsule, two raw boards and original deadline.
Historical diagnostic replies are explicitly refused.
"""
from copy import deepcopy

from .manufacturing_grade import typed_grade, GradeUnproved as Unproved


def refine_pair(grades, measurement, *, expected_request_sha256,
                mandatory_maps, check_current):
    """Keep independently unresolved manufacturing reasons visible.

check_current is the actual parent's retained-original/runtime/raw-artifact
verification closure, invoked before and after interpretation. The measurement
worker is not permitted to supply it or to authorize selection.
"""
    check_current()
    if (measurement.get('mode') != 'retained_current_measurement'
            or measurement.get('comparison_authority') is not False
            or measurement.get('request_sha256') != expected_request_sha256):
        raise Unproved('current_measurement_binding')
    result = deepcopy(grades)
    for side in ('legacy', 'pocket'):
        grade = result[side]
        typed_grade(grade)
        reasons = grade.get('unproved')
        if not isinstance(reasons, list) or any(type(r) is not str for r in reasons):
            raise Unproved('ordinary_grade_malformed')
        evidence = measurement['sides'][side]
        # Only all-via annular coverage can remove this specific factory-floor
        # uncertainty. Fresh original-rule DRC remains independently required.
        annular = evidence['annular']
        if (annular.get('known') is True and type(annular.get('under')) is list
                and evidence.get('original_rules_drc_validated') is True):
            reasons = [r for r in reasons
                       if r != 'original_size_floor_below_factory_annular']
            grade['undersized'] = max(grade['undersized'], len(annular['under']))
        clearance = evidence.get('clearance')
        supported_reasons = {'original_size_floor_below_factory_annular'}
        if clearance is not None:
            if (type(clearance) is not dict
                    or set(clearance) != {'complete', 'legal', 'violations', 'original_errors', 'failure_count'}
                    or type(clearance['complete']) is not bool
                    or type(clearance['legal']) is not bool
                    or type(clearance['violations']) is not list
                    or type(clearance['original_errors']) is not int
                    or clearance['original_errors'] < 0
                    or type(clearance['failure_count']) is not int
                    or clearance['failure_count'] < clearance['original_errors']
                    or clearance['failure_count'] < len(clearance['violations'])
                    or clearance['legal'] is not (not clearance['violations'])):
                raise Unproved('ordinary_clearance_malformed')
            if clearance['complete'] and evidence['original_rules_drc_validated']:
                supported_reasons.update({'local_clearance_overrides_unproved',
                                          'mandatory_clearance_maps_unproved'})
                reasons = [reason for reason in reasons if reason not in {
                    'local_clearance_overrides_unproved', 'mandatory_clearance_maps_unproved'}]
                # A measured original-floor violation is known invalid. It is
                # never made acceptable because it was inherited by both sides.
                grade['drc'] = max(grade['drc'], clearance['failure_count'])
        if mandatory_maps and 'local_clearance_overrides_unproved' not in supported_reasons:
            if 'mandatory_clearance_maps_unproved' not in reasons:
                reasons.append('mandatory_clearance_maps_unproved')
        grade['unproved'] = reasons
        original_reasons = set(grades[side]['unproved'])
        grade['known'] = (not reasons and (grades[side]['known']
            or bool(original_reasons) and original_reasons.issubset(supported_reasons)))
        typed_grade(grade)
    check_current()
    return result
