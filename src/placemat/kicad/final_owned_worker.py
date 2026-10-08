"""One JSON worker within an existing deadline; no adoption authority.

Scratch review draft. Caller supplies retained physical and critical context.
Only a completed owned execution can mint the private import token below.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time

from placemat import stop
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad.final_route import FinalCopperGrader, FinalCopperResult

# Token custody is process-local; public JSON or a caller-supplied descriptor
# cannot enter the physical grader's private minted-results table.
_COMPLETIONS = {}


def _remaining(deadline):
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ProofUnavailable('final_worker_deadline_invalid')
    value = deadline - time.time()
    if value <= 0:
        raise ProofUnavailable('final_worker_deadline_expired')
    return value


def _implementation():
    import placemat
    native = sys.modules.get('placemat_native')
    extension = sys.modules.get('placemat_native.placemat_native')
    if getattr(native, '__file__', None) is None or getattr(extension, '__file__', None) is None:
        raise ProofUnavailable('final_worker_physical_runtime_unavailable', module='placemat_native')
    package = Path(placemat.__file__).resolve().parent
    native_package = Path(native.__file__).resolve().parent
    paths = list(package.rglob('*.py')) + list(native_package.rglob('*.py')) + list(native_package.glob('*.so'))
    paths.append(Path(sys.executable).resolve())
    # Executor already read original geometry. Do not introduce a parent
    # native import/read merely to discover the runtime used by grading.
    for name in ('pcbnew', '_pcbnew'):
        module = sys.modules.get(name)
        filename = getattr(module, '__file__', None)
        if filename is None:
            raise ProofUnavailable('final_worker_physical_runtime_unavailable', module=name)
        paths.append(Path(filename).resolve())
    executable = shutil.which('kicad-cli')
    if executable is None:
        raise ProofUnavailable('final_worker_physical_runtime_unavailable', tool='kicad-cli')
    paths.append(Path(executable).resolve())
    return {str(path): file_hash(path) for path in sorted(set(paths))}


def _execute(argv, deadline, env, *, cwd=None, pass_fds=()):
    """Bound the wait by the original deadline; shutdown time cannot mint proof."""
    if threading.current_thread() is not threading.main_thread():
        raise ProofUnavailable('final_worker_main_thread_required')
    _remaining(deadline)
    previous = {sig: signal.getsignal(sig) for sig in stop.SIGNALS}
    proc, pending = None, None

    def interrupted(sig, frame):
        nonlocal pending
        if proc is None:
            if pending is None:
                pending = sig, frame
            return
        handler = previous[sig]
        if callable(handler):
            handler(sig, frame)
        elif handler != signal.SIG_IGN:
            raise stop.Stopped(sig)

    def cleanup():
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        if proc is None:
            return None, None
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            return proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                return proc.communicate(timeout=1)
            except subprocess.TimeoutExpired as error:
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        stream.close()
                proc.wait(timeout=1)
                return error.output or '', error.stderr or ''

    try:
        for sig, handler in previous.items():
            if handler != signal.SIG_IGN:
                signal.signal(sig, interrupted)
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, start_new_session=True, cwd=cwd, pass_fds=pass_fds)
        if pending is not None:
            interrupted(*pending)
        stdout, stderr = proc.communicate(timeout=_remaining(deadline))
        _remaining(deadline)
        return proc.returncode, stdout, stderr
    except BaseException as error:
        stdout, stderr = cleanup()
        if stdout:
            error.output = stdout
        if stderr:
            error.stderr = stderr
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _unique(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise ProofUnavailable('final_worker_reply_malformed')
        record[key] = value
    return record


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProofUnavailable('final_worker_reply_malformed')))
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ProofUnavailable):
            raise
        raise ProofUnavailable('final_worker_reply_malformed') from error


def _validate_original_proof(grader, proof, destination):
    """Verify child baseline artifacts against privately retained originals."""
    from .final_original_verification import _semantic_drc
    fields = {'schema', 'original_context_sha256', 'source_sha256', 'copied_sha256',
              'copied_path', 'baseline_semantics_sha256', 'measured_drc_path',
              'measured_drc_sha256', 'counted', 'chosen_pours', 'open_before',
              'obligations_sha256'}
    root = destination.parent / (destination.name + '.original-check')
    measured = root / 'drc_before.json'
    copied = root / 'original.kicad_pcb'
    if (not isinstance(proof, dict) or set(proof) != fields
            or type(proof['schema']) is not int or proof['schema'] != 1
            or proof['original_context_sha256'] != grader.contract_sha256
            or proof['source_sha256'] != file_hash(grader._original)
            or proof['copied_path'] != str(copied.absolute())
            or proof['measured_drc_path'] != str(measured.absolute())
            or proof['counted'] != sorted(grader._counted)
            or proof['chosen_pours'] != sorted(grader._chosen_pours)
            or proof['open_before'] != grader._open_before
            or proof['obligations_sha256'] != record_digest(json.loads(grader._obligations))):
        raise ProofUnavailable('final_worker_original_proof_mismatch')
    if (file_hash(copied) != proof['copied_sha256']
            or file_hash(measured) != proof['measured_drc_sha256']):
        raise ProofUnavailable('final_worker_original_artifact_changed')
    original = _semantic_drc(grader._baseline)
    actual = _semantic_drc(measured)
    if actual != original or record_digest(actual) != proof['baseline_semantics_sha256']:
        raise ProofUnavailable('final_worker_original_baseline_mismatch')


def _critical_digest(value):
    try:
        return record_digest(value)
    except (TypeError, ValueError) as error:
        raise ProofUnavailable('final_worker_critical_malformed') from error


def _validate_critical(grader, context, critical):
    """Validate complete critical/preservation reply before any physical mint."""
    if (not isinstance(context, dict) or not isinstance(context.get('source_physical'), dict)
            or not isinstance(critical, dict) or set(critical) != {'measures', 'evidence', 'preservation'}
            or any(not isinstance(critical[key], dict) for key in critical)):
        raise ProofUnavailable('final_worker_critical_malformed')
    preserved = critical['preservation']
    if (set(preserved) != {'original_manifest', 'held_and_fixed_preserved'}
            or preserved['held_and_fixed_preserved'] is not True):
        raise ProofUnavailable('final_worker_preservation_malformed')
    from .final_custody import original_snapshot
    try:
        from placemat.final_preservation import CandidateRefused, manifest
    except ImportError as error:
        raise ProofUnavailable('final_worker_preservation_unavailable') from error
    snapshot = original_snapshot(grader)
    try:
        expected_manifest = manifest(snapshot['geometry'], grader._original)
    except CandidateRefused as error:
        raise ProofUnavailable('final_worker_preservation_unavailable',
                               preservation_code=error.code, detail=str(error)) from error
    expected_sha = _critical_digest(expected_manifest)
    if (_critical_digest(context['source_physical']) != expected_sha
            or _critical_digest(preserved['original_manifest']) != expected_sha):
        raise ProofUnavailable('final_worker_preservation_mismatch')
    measures = critical['measures']
    if (type(measures.get('critical_checks')) is not int or measures['critical_checks'] < 0
            or not isinstance(measures.get('critical_unknown'), list)
            or not isinstance(measures.get('findings'), dict)
            or any(type(count) is not int or count < 0 for count in measures['findings'].values())):
        raise ProofUnavailable('final_worker_critical_measures_malformed')
    expected = {'critical_checks': measures['critical_checks'],
                'critical_unknown': measures['critical_unknown'], 'final_findings': measures['findings']}
    if _critical_digest(critical['evidence']) != _critical_digest(expected):
        raise ProofUnavailable('final_worker_critical_evidence_mismatch')
    grader._unchanged()


def grade_owned(grader, physical_packet, critical_context, *, deadline_utc):
    """Execute one original-context worker and privately import its evidence."""
    from placemat.kicad.final_worker_protocol import export, read_report, validate_packet_fields, _read_artifact
    _remaining(deadline_utc)
    if type(grader) is not FinalCopperGrader:
        raise ProofUnavailable('final_worker_context_unavailable')
    from .final_custody import require_completed
    completed_custody = require_completed(grader)
    if any(completed_custody[key]['deadline_utc'] != deadline_utc for key in ('original', 'completed')):
        raise ProofUnavailable('final_worker_deadline_context_mismatch')
    if not isinstance(physical_packet, dict):
        raise ProofUnavailable('final_worker_context_malformed')
    packet = deepcopy(physical_packet)
    validate_packet_fields(packet)
    if packet['executor_custody'] != completed_custody:
        raise ProofUnavailable('final_worker_executor_custody_mismatch')
    if packet['deadline_utc'] != deadline_utc:
        raise ProofUnavailable('final_worker_deadline_context_mismatch')
    raw = _read_artifact(packet['raw'])
    destination = Path(packet['destination'])
    summary = _read_artifact(packet['candidate_summary']) if packet['candidate_summary'] is not None else None
    if export(grader, raw, destination, deadline_utc=deadline_utc, candidate_summary=summary) != packet:
        raise ProofUnavailable('final_worker_context_mismatch')
    if destination.exists():
        raise ProofUnavailable('final_worker_destination_not_fresh')
    supervision = destination.parent / (destination.name + '.worker')
    supervision.mkdir(parents=True, exist_ok=False)
    request = {'schema': 1, 'deadline_utc': deadline_utc, 'physical': packet,
               'critical': deepcopy(critical_context)}
    request_path, response_path = supervision / 'request.json', supervision / 'response.json'
    request_bytes = (json.dumps(request, sort_keys=True, allow_nan=False) + '\n').encode()
    request_path.write_bytes(request_bytes)
    implementation = _implementation()
    env = dict(os.environ)
    inherited = env.get('KRT_ROUTE_DEADLINE_UTC')
    if inherited is not None:
        try:
            effective = min(deadline_utc, float(inherited))
        except (ValueError, TypeError) as error:
            raise ProofUnavailable('final_worker_deadline_invalid') from error
        if not math.isfinite(effective) or effective < deadline_utc:
            raise ProofUnavailable('final_worker_deadline_context_mismatch')
    env['KRT_ROUTE_DEADLINE_UTC'] = str(deadline_utc)
    argv = [sys.executable, '-m', 'placemat.final_check_worker', str(request_path.absolute()), str(response_path.absolute())]
    facts = {'argv': argv, 'cwd': str(Path.cwd()), 'deadline_utc': deadline_utc,
             'request_sha256': hashlib.sha256(request_bytes).hexdigest(), 'implementation': implementation}
    started = time.monotonic()
    result = None
    try:
        rc, stdout, stderr = _execute(argv, deadline_utc, env)
        facts['returncode'] = rc
        (supervision / 'stdout.log').write_text(stdout)
        (supervision / 'stderr.log').write_text(stderr)
        if rc != 0:
            raise ProofUnavailable('final_worker_failed', returncode=rc)
        _remaining(deadline_utc)
        if request_path.read_bytes() != request_bytes or _implementation() != implementation:
            raise ProofUnavailable('final_worker_execution_changed')
        response_bytes = response_path.read_bytes()
        reply = _json(response_bytes)
        if not isinstance(reply, dict) or set(reply) != {'schema', 'request_sha256', 'binding_sha256', 'report',
                                                       'physical_receipt', 'physical_grade_sha256', 'critical',
                                                       'implementation_start', 'implementation_end', 'original_verification'}:
            raise ProofUnavailable('final_worker_reply_malformed')
        if (type(reply['schema']) is not int or reply['schema'] != 1
                or reply['request_sha256'] != record_digest(request)
                or reply['binding_sha256'] != grader.contract_sha256):
            raise ProofUnavailable('final_worker_reply_context_mismatch')
        if reply['implementation_start'] != implementation or reply['implementation_end'] != implementation:
            raise ProofUnavailable('final_worker_imported_runtime_mismatch')
        _validate_original_proof(grader, reply['original_verification'], destination)
        report = read_report(reply['report'])
        receipt = reply['physical_receipt']
        evidence = destination / 'physical_grade.json'
        evidence_bytes = evidence.read_bytes()
        if _json(evidence_bytes) != receipt or file_hash(evidence) != reply['physical_grade_sha256']:
            raise ProofUnavailable('final_worker_physical_evidence_changed')
        _validate_critical(grader, critical_context, reply['critical'])
        facts['response_sha256'] = hashlib.sha256(response_bytes).hexdigest()
        facts['elapsed_s'] = time.monotonic() - started
        _remaining(deadline_utc)
        token = object()
        _COMPLETIONS[token] = (grader, deepcopy(reply), raw, destination, summary, deepcopy(facts),
                               request_path, request_bytes, response_path, response_bytes, deadline_utc)
        try:
            result = _import_completed(token, grader, report)
        finally:
            _COMPLETIONS.pop(token, None)
        _remaining(deadline_utc)
        return result, deepcopy(reply['critical']), deepcopy(facts)
    except BaseException as error:
        if result is not None:
            grader._minted.pop(id(result), None)
        facts['failure'] = {'type': type(error).__name__, 'message': str(error)}
        for name in ('output', 'stderr'):
            value = getattr(error, name, None)
            if value:
                (supervision / ('stdout.log' if name == 'output' else 'stderr.log')).write_text(
                    value.decode(errors='replace') if isinstance(value, bytes) else value)
        raise
    finally:
        facts['elapsed_s'] = time.monotonic() - started
        (supervision / 'execution.json').write_text(json.dumps(facts, sort_keys=True, indent=2) + '\n')


def _import_completed(token, grader, report):
    owned = _COMPLETIONS.get(token)
    if owned is None or owned[0] is not grader:
        raise ProofUnavailable('foreign_final_worker_completion')
    _, reply, raw, destination, summary, facts, request_path, request_bytes, response_path, response_bytes, deadline = owned
    _remaining(deadline)
    if request_path.read_bytes() != request_bytes or response_path.read_bytes() != response_bytes:
        raise ProofUnavailable('final_worker_execution_changed')
    from .final_custody import require_completed
    if require_completed(grader) != _json(request_bytes)['physical']['executor_custody']:
        raise ProofUnavailable('final_worker_executor_custody_changed')
    grader._unchanged()
    receipt = reply['physical_receipt']
    # Known outputs only: no arbitrary paths or self-reported source/rule contract.
    names = {'routed.kicad_pcb', 'routed.kicad_pro', 'routed.kicad_dru', 'drc_after.json', 'route.json'}
    receipt_fields = {'schema', 'contract_sha256', 'original_inputs', 'raw_board_sha256',
                      'execution_provenance', 'outputs', 'width_authority_sha256', 'full_standing'}
    if (not isinstance(receipt, dict) or set(receipt) != receipt_fields
            or type(receipt.get('schema')) is not int or receipt.get('schema') != 1
            or receipt.get('contract_sha256') != grader.contract_sha256
            or receipt.get('original_inputs') != grader._inputs
            or receipt.get('width_authority_sha256') != record_digest(json.loads(grader._widths))
            or not isinstance(receipt.get('outputs'), dict) or set(receipt['outputs']) != names
            or any(value is not None and (not isinstance(value, str) or len(value) != 64
                   or any(char not in '0123456789abcdef' for char in value))
                   for value in receipt['outputs'].values())
            or any(receipt['outputs'][name] is None for name in names - {'routed.kicad_dru'})
            or receipt.get('full_standing') != 'requires_retained_integrated_adapter'
            or report.routed_pcb != destination / 'routed.kicad_pcb'
            or report.work != destination or report.asked != json.loads(grader._obligations)):
        raise ProofUnavailable('final_worker_physical_context_mismatch')
    result = FinalCopperResult(report, deepcopy(receipt))
    grader._minted[id(result)] = (result, deepcopy(receipt), destination, raw, summary,
                                 reply['physical_grade_sha256'], deepcopy(report))
    try:
        grader.verify(result)
        _remaining(deadline)
    except BaseException:
        grader._minted.pop(id(result), None)
        raise
    return result
