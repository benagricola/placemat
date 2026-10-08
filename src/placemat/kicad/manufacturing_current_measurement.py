"""Owned retained-original manufacturing measurement for ordinary selection."""
import hashlib
import json
from pathlib import Path
import sys

from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad.final_owned_worker import _execute, _implementation
from .manufacturing_inventory import retained_original
from .manufacturing_annular import unchanged as request_unchanged, digest, Unproved
from .manufacturing_current_request import prepare
from .manufacturing_receipt import validate
from .manufacturing_refinement import refine_pair, typed_grade, Unproved as GradeUnproved


_WORKER_BOOTSTRAP = """import hashlib, importlib, pathlib, sys
root, expected, expected_sha, request, reply = sys.argv[1:]
expected = pathlib.Path(expected)
if expected.resolve() != expected or hashlib.sha256(expected.read_bytes()).hexdigest() != expected_sha:
    raise RuntimeError('manufacturing_worker_source_changed')
sys.path.insert(0, root)
worker = importlib.import_module('placemat.kicad.manufacturing_worker')
actual = pathlib.Path(worker.__file__).resolve()
if actual != expected or hashlib.sha256(actual.read_bytes()).hexdigest() != expected_sha:
    raise RuntimeError('manufacturing_worker_origin_changed')
sys.argv = [str(actual), request, reply]
worker.main()
"""


def worker_command(source, reply, runtime):
    """Resolve only this installed package; inherited PYTHONPATH is not authority."""
    worker = Path(__file__).resolve().with_name('manufacturing_worker.py')
    expected = runtime.get(str(worker))
    if type(expected) is not str or file_hash(worker) != expected:
        raise ProofUnavailable('current_measurement_worker_unbound')
    return [sys.executable, '-I', '-c', _WORKER_BOOTSTRAP,
            str(worker.parents[2]), str(worker), expected, str(source), str(reply)]


def measure(budget, owner, final_call, legacy_board, candidate_board,
            candidate_files, grades, work, check_execution):
    """No routing proposal: native inventories/DRC consume original time only."""
    try:
        for side in ('legacy','pocket'):typed_grade(grades[side])
    except (KeyError,GradeUnproved) as error:
        raise ProofUnavailable('current_measurement_grade_unavailable') from error
    check_execution()
    budget._check(budget.executor)
    work = Path(work); work.mkdir()
    try:
        packet = prepare(budget, owner, final_call, legacy_board, candidate_board,
                         candidate_files, work=work)
    except OSError as error:
        raise ProofUnavailable('current_measurement_input_unavailable') from error
    original = retained_original(owner.factory)
    implementation = _implementation()
    def check():
        check_execution()
        request_unchanged(packet['request'])
        if retained_original(owner.factory) != original or _implementation() != implementation:
            raise ProofUnavailable('current_measurement_original_runtime_changed')
        for path, expected in packet['context']['actual_raw_copper'].items():
            if file_hash(path) != expected:
                raise ProofUnavailable('current_measurement_raw_changed')
        capsule = packet['context']['capsule']
        if file_hash(capsule['path']) != capsule['sha256']:
            raise ProofUnavailable('current_measurement_capsule_changed')
    check()
    source=work/'request.json'; reply_path=work/'reply.json'
    raw=json.dumps(packet,sort_keys=True,allow_nan=False).encode()
    source.write_bytes(raw); request_sha=hashlib.sha256(raw).hexdigest()
    ctx=owner.contexts_for(budget)[final_call]
    try:
        rc,out,err=_execute(worker_command(source, reply_path, packet['request']['runtime']),
                            budget.deadline,dict(ctx.env),cwd=str(work))
    except BaseException as error:
        for attr,suffix in (('output','stdout'),('stderr','stderr')):
            text=getattr(error,attr,'') or ''
            (work/(suffix+'.log')).write_text(text.decode(errors='replace') if isinstance(text,bytes) else text)
        if isinstance(error,OSError) and not isinstance(error,TimeoutError):
            raise ProofUnavailable('current_measurement_process_unavailable') from error
        raise
    (work/'stdout.log').write_text(out);(work/'stderr.log').write_text(err)
    check()
    if file_hash(source)!=request_sha or rc!=0:
        raise ProofUnavailable('current_measurement_incomplete',returncode=rc)
    try:
        reply_bytes=reply_path.read_bytes(); reply_sha=hashlib.sha256(reply_bytes).hexdigest()
        verified=validate(packet,json.loads(reply_bytes),check)
        capsule=packet['context']['capsule']
        capsule_bytes=Path(capsule['path']).read_bytes()
        if hashlib.sha256(capsule_bytes).hexdigest()!=capsule['sha256']:
            raise ProofUnavailable('current_measurement_capsule_changed')
        capture=json.loads(capsule_bytes)
        refined=refine_pair(grades,verified,expected_request_sha256=digest(packet),
                            mandatory_maps=capture['effective_clearances'],check_current=check)
    except (OSError,Unproved,GradeUnproved,ValueError,UnicodeError) as error:
        raise ProofUnavailable('current_measurement_unproved',reason=str(error)) from error
    try:
        if file_hash(reply_path)!=reply_sha:
            raise ProofUnavailable('current_measurement_reply_changed')
    except OSError as error:
        raise ProofUnavailable('current_measurement_reply_unavailable') from error
    check()
    (work/'measurement.json').write_text(json.dumps({'schema':1,
        'request_sha256':request_sha,'reply_sha256':reply_sha,
        'comparison_authority':False,'strict_adoption':False,
        'grades_sha256':record_digest(refined)},sort_keys=True)+'\n')
    return refined
