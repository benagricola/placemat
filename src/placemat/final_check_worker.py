"""JSON-only final physical and critical judgment in an owned bounded child.

The caller must terminate and reap this process group at the retained absolute
deadline. This module mints no authority: the parent independently verifies
every artifact and imports the result into its retained grader.
"""
from __future__ import annotations

from copy import deepcopy
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


def _runtime_identity():
    """Load and bind actual runtimes only inside the owned child."""
    from .kicad.quiet import import_pcbnew
    from .kicad.final_owned_worker import _implementation
    import_pcbnew()
    import placemat_native
    return _implementation()


def _preservation(grader, final_pcb, expected):
    from .kicad.read import read_board
    from .final_preservation import verify
    from .settings import bind
    with bind(grader._cfg):
        original = read_board(grader._original)
        final = read_board(final_pcb)
        return verify(original, grader._original, final, final_pcb, expected)


def evaluate_critical(request):
    """Only the full final judgement, without routing/finalization/authority."""
    if (type(request) is not dict or set(request) !=
            {'schema','operation','deadline_utc','critical','pcb','inputs'}
            or type(request['schema']) is not int or request['schema'] != 1
            or request['operation'] != 'critical-only'
            or type(request['pcb']) is not str or not Path(request['pcb']).is_absolute()
            or type(request['inputs']) is not dict):
        _refuse('critical-only request fields are invalid')
    _deadline(request['deadline_utc'])
    from .kicad.final_call import file_hash
    from .final_check_judgement import encode
    pcb=Path(request['pcb'])
    expected={str(pcb),str(pcb.with_suffix('.kicad_pro')),str(pcb.with_suffix('.kicad_dru'))}
    if set(request['inputs']) != expected:
        _refuse('critical-only input inventory is incomplete')
    def unchanged():
        for path,expected_hash in request['inputs'].items():
            if (expected_hash is not None and (type(expected_hash) is not str
                    or len(expected_hash)!=64 or any(c not in '0123456789abcdef' for c in expected_hash))):
                _refuse('critical-only input hash is invalid')
            actual=file_hash(path) if Path(path).is_file() else None
            if actual!=expected_hash or (path==str(pcb) and actual is None):
                _refuse('critical-only input changed')
    unchanged()
    implementation_start=_runtime_identity()
    _deadline(request['deadline_utc'])
    request_sha=_digest(request)
    judgement=judge(request['critical'],pcb)
    _deadline(request['deadline_utc'])
    unchanged()
    implementation_end=_runtime_identity()
    if implementation_start!=implementation_end or _digest(request)!=request_sha:
        _refuse('critical-only implementation or request changed')
    return {'schema':1,'operation':'critical-only','request_sha256':request_sha,
            'implementation_start':implementation_start,'implementation_end':implementation_end,
            'judgement':encode(judgement),'evidence':judgement.evidence()}


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
    critical_context = request['critical']
    if not isinstance(critical_context, dict) or not isinstance(critical_context.get('source_physical'), dict):
        _refuse('retained original physical manifest is required')
    request_sha = _digest(request)
    # Binding-time import deliberately keeps this entrypoint unavailable on a
    # standalone branch without the reviewed physical codec. No duck typing or
    # dynamic module/class name supplied by JSON can replace it.
    try:
        from .kicad.final_worker_protocol import reconstruct, report_record
        implementation_start = _runtime_identity()
    except ImportError as error:
        raise ContextRefused('final_check_worker_unavailable',
                             'reviewed physical worker runtime is unavailable') from error
    _deadline(request['deadline_utc'])
    grader, raw, destination, summary = reconstruct(physical)
    _deadline(request['deadline_utc'])
    result = grader.regrade(raw, destination, candidate_summary=summary)
    receipt = grader.verify(result)
    _deadline(request['deadline_utc'])
    critical = judge(critical_context, result.report.routed_pcb)
    _deadline(request['deadline_utc'])
    preservation = _preservation(grader, result.report.routed_pcb, critical_context['source_physical'])
    _deadline(request['deadline_utc'])
    # Reverification catches input/output mutation while critical checks read
    # the finalized PCB. Publication remains the retained parent's duty.
    if grader.verify(result) != receipt or _digest(request) != request_sha:
        _refuse('worker request or physical grading evidence changed')
    implementation_end = _runtime_identity()
    if implementation_end != implementation_start:
        _refuse('worker implementation changed during grading')
    return {'schema': 1, 'request_sha256': request_sha,
            'binding_sha256': physical['binding']['contract_sha256'],
            'report': report_record(result.report), 'physical_receipt': receipt,
            'physical_grade_sha256': hashlib.sha256((destination / 'physical_grade.json').read_bytes()).hexdigest(),
            'implementation_start': implementation_start, 'implementation_end': implementation_end,
            'original_verification': deepcopy(grader._worker_original_proof),
            'critical': {'measures': critical.measures, 'evidence': critical.evidence(),
                         'preservation': preservation}}


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
    result = evaluate_critical(request) if type(request) is dict and request.get('operation') == 'critical-only' else evaluate(request)
    if args.request.read_bytes() != raw:
        _refuse('worker request bytes changed')
    _deadline(request['deadline_utc'])
    # Exclusive creation avoids overwriting any previous evidence. A truncated
    # response cannot satisfy the parent's JSON/hash verification.
    with args.response.open('x') as stream:
        stream.write(json.dumps(result, sort_keys=True, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
