"""Exact captured factory clearance transport; no permission or authority mint."""
import hashlib
import json
from .manufacturing_floor_project import iu, Unsupported
from .manufacturing_clearance_report import Unproved


def captured_floor(raw, expected_sha256):
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Unproved('factory_capsule_changed')
    try:
        capsule = json.loads(raw)
        if type(capsule.get('schema')) is not int or capsule['schema'] != 2:
            raise Unproved('factory_capsule_schema')
        request = capsule['ordinary_grade_request']
        defaults = request['manufacturing_defaults']
        if not isinstance(defaults, dict):
            raise Unproved('factory_rule_unavailable')
        value = defaults['clearance']
        floor = iu(value)
        if floor <= 0 or not isinstance(defaults.get('source'), str) or not defaults['source']:
            raise Unproved('factory_rule_unavailable')
    except (KeyError, TypeError, ValueError, Unsupported) as error:
        raise Unproved('factory_rule_unavailable') from error
    return {'factory_global_floor_iu': floor, 'capsule_sha256': expected_sha256,
            'original_request': request, 'manufacturing_defaults': defaults,
            'comparison_authority': False}
