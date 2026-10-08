"""JSON-only final physical and critical judgment in an owned bounded child.

The caller must terminate and reap this process group at the retained absolute
deadline. This module mints no authority: the parent independently verifies
every artifact and imports the result into its retained grader.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

from .final_check_context import ContextRefused, judge


def _refuse(message):
    raise ContextRefused('final_check_worker_request_invalid', message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _deadline(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= time.time()):
        raise ContextRefused('final_check_worker_deadline_expired', 'shared final-check deadline expired')


def evaluate(request):
    """Finalize and check one candidate; called only inside owned execution."""
    if not isinstance(request, dict) or set(request) != {'schema', 'deadline_utc', 'physical', 'critical'}:
        _refuse('worker request fields are missing or unknown')
    if type(request['schema']) is not int or request['schema'] != 1:
        _refuse('worker request schema is unsupported')
    _deadline(request['deadline_utc'])
    physical = request['physical']
    if not isinstance(physical, dict) or physical.get('deadline_utc') != request['deadline_utc']:
        _refuse('physical grading must share the retained absolute deadline')
    request_sha = _digest(request)
    # Binding-time import deliberately keeps this entrypoint unavailable on a
    # standalone branch without the reviewed physical codec. No duck typing or
    # dynamic module/class name supplied by JSON can replace it.
    from .kicad.final_worker_protocol import reconstruct, report_record
    grader, raw, destination, summary = reconstruct(physical)
    _deadline(request['deadline_utc'])
    result = grader.regrade(raw, destination, candidate_summary=summary)
    receipt = grader.verify(result)
    _deadline(request['deadline_utc'])
    critical = judge(request['critical'], result.report.routed_pcb)
    _deadline(request['deadline_utc'])
    # Reverification catches input/output mutation while critical checks read
    # the finalized PCB. Publication remains the retained parent's duty.
    if grader.verify(result) != receipt or _digest(request) != request_sha:
        _refuse('worker request or physical grading evidence changed')
    return {'schema': 1, 'request_sha256': request_sha,
            'binding_sha256': physical['binding']['contract_sha256'],
            'report': report_record(result.report), 'physical_receipt': receipt,
            'physical_grade_sha256': hashlib.sha256((destination / 'physical_grade.json').read_bytes()).hexdigest(),
            'critical': {'measures': critical.measures, 'evidence': critical.evidence()}}


def _unique(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            _refuse('worker JSON contains duplicate fields')
        record[key] = value
    return record


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    parser.add_argument('response', type=Path)
    args = parser.parse_args(argv)
    if not args.request.is_absolute() or not args.response.is_absolute() or args.response.exists():
        _refuse('worker request/response must be absolute fresh artifact paths')
    raw = args.request.read_bytes()
    request = json.loads(raw, object_pairs_hook=_unique,
                         parse_constant=lambda _: _refuse('nonfinite worker JSON'))
    result = evaluate(request)
    if args.request.read_bytes() != raw:
        _refuse('worker request bytes changed')
    _deadline(request['deadline_utc'])
    # Exclusive creation avoids overwriting any previous evidence. A truncated
    # response cannot satisfy the parent's JSON/hash verification.
    with args.response.open('x') as stream:
        stream.write(json.dumps(result, sort_keys=True, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
