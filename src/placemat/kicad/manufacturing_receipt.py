"""Independent current measurement reply validation; no publication authority."""
from .manufacturing_annular import evaluate, digest, Unproved


def validate(packet, reply, check_current):
    check_current()
    try:
        result = _validate(packet, reply, check_current)
    except Unproved:
        raise
    except (OSError, KeyError, TypeError, AttributeError, ValueError, UnicodeError) as error:
        raise Unproved('current_reply_malformed') from error
    check_current()
    return result


def _validate(packet, reply, check_current):
    """Recompute annular results and bind exact successful original-rule reports.

The actual parent's check_current closure owns registry/custody, original
deadline and artifact verification. This function does not accept historical
diagnostic identity as a substitute for that live owner.
"""
    if (packet['context']['mode'] != 'retained_current_measurement'
            or reply.get('mode') != 'retained_current_measurement'
            or reply.get('comparison_authority') is not False
            or type(reply.get('schema')) is not int or reply['schema'] != 1
            or reply.get('request_sha256') != digest(packet)):
        raise Unproved('current_reply_binding')
    # evaluate checks exact schema, all UUID multiplicities, layer order,
    # per-layer positive typed dimensions, runtime, fresh time and file hashes.
    annular = evaluate(packet['request'], reply['receipt'])
    if digest(annular) != digest(reply['result']):
        raise Unproved('current_annular_result_changed')
    from .manufacturing_clearance_receipt import validate as validate_clearance
    clearance = validate_clearance(packet, reply['mandatory_clearance'], check_current)
    sides = {}
    for side, label in (('original', 'legacy'), ('candidate', 'pocket')):
        measured = clearance[label]
        sides[label] = {
            'annular': annular[side],
            'original_rules_drc_validated': measured['complete'],
            'original_rule_error_count': measured['original_errors'],
            'clearance': measured,
        }
    return {'mode': 'retained_current_measurement', 'comparison_authority': False,
            'request_sha256': digest(packet), 'sides': sides}
