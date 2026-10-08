"""Scratch cooperative executor custody boundary; no native imports or reads.

Only the private ordinary executor hooks may register/seal custody. Public
constructors, binding(), templates and JSON receipts are not authority. Python
reflection/arbitrary access to private executor code is outside this boundary.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
import weakref
import time
from pathlib import Path
from placemat.board_geometry import BoardGeometry
from placemat.kicad.final_call import ProofUnavailable
from placemat.kicad.final_route import FinalCopperGrader

class CustodyUnavailable(ProofUnavailable):
    """Optional custody refusal with a stable code and detached facts."""
_REGISTRY = {}
_MINT = object()

def _value(x: object) -> object:
    if is_dataclass(x):
        return {'type': type(x).__module__ + '.' + type(x).__qualname__, 'fields': {f.name: _value(getattr(x, f.name)) for f in fields(x)}}
    if isinstance(x, Enum):
        return {'enum': type(x).__module__ + '.' + type(x).__qualname__, 'value': _value(x.value)}
    if isinstance(x, Path):
        return {'path': str(x)}
    if isinstance(x, dict):
        if not all((isinstance(k, str) for k in x)):
            raise CustodyUnavailable('unsupported_mapping_key')
        return {k: _value(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return {'sequence': type(x).__name__, 'values': [_value(v) for v in x]}
    if isinstance(x, (set, frozenset)):
        return {'set': type(x).__name__, 'values': sorted((_value(v) for v in x), key=lambda v: json.dumps(v, sort_keys=True))}
    if x is None or isinstance(x, (str, bool, int)):
        return x
    if isinstance(x, float) and math.isfinite(x):
        return x
    raise CustodyUnavailable('unsupported_snapshot_value', type_name=type(x).__name__)

def _digest(x: object) -> str:
    return hashlib.sha256(json.dumps(_value(x), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def _hash(path: str | Path) -> str | None:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None

def _fingerprint(grader: FinalCopperGrader, *, include_template: bool = True) -> str:
    names = (
        '_original',
        '_cleanup_input',
        '_rules',
        '_baseline',
        '_receipt_path',
        '_inputs',
        '_obligations',
        '_widths',
        '_phases',
        '_cfg',
        '_counted',
        '_open_before',
        '_chosen_pours',
        '_semantic_contract',
        '_contract_sha256',
        '_template',
    )
    if not include_template:
        names = tuple((n for n in names if n != '_template'))
    try:
        return _digest({name: getattr(grader, name) for name in names})
    except AttributeError as error:
        raise CustodyUnavailable('grader_private_context_missing') from error

@dataclass
class _Original:
    owner: weakref.ReferenceType[FinalCopperGrader]
    geometry: BoardGeometry
    geometry_sha: str
    manifest: dict[str, str | None]
    read_identity: dict
    facts: dict
    fingerprint: str
    deadline_utc: float
    original_sha: str
    run: _Ledger | None = None
    completed: _Completion | None = None

class _Opaque:
    __slots__ = ()

    def __copy__(self):
        raise CustodyUnavailable('custody_not_copyable')

    def __deepcopy__(self, memo):
        raise CustodyUnavailable('custody_not_copyable')

    def __reduce__(self):
        raise CustodyUnavailable('custody_not_serializable')

class _Ledger(_Opaque):
    __slots__ = ('owner', 'executor', 'report', 'phases', 'outputs', 'sealed', 'issued', 'replay_budget', 'call_plans')

    def __new__(cls, key, *args):
        if key is not _MINT:
            raise CustodyUnavailable('private_executor_required')
        return super().__new__(cls)

    def __init__(self, key, owner, executor):
        self.owner, self.executor, self.report, self.phases, self.outputs, self.sealed = (owner, executor, None, [], {}, False)
        self.issued = []
        self.replay_budget = None
        self.call_plans = []

class _Completion(_Opaque):
    __slots__ = ('owner', 'report_sha', 'outputs', 'ledger_sha', 'completed_at')

    def __new__(cls, key, *args):
        if key is not _MINT:
            raise CustodyUnavailable('private_executor_required')
        return super().__new__(cls)

    def __init__(self, key, owner, report_sha, outputs, ledger_sha):
        self.owner, self.report_sha, self.outputs, self.ledger_sha, self.completed_at = (owner, report_sha, outputs, ledger_sha, time.time())

def _context(grader: FinalCopperGrader) -> _Original:
    state = _REGISTRY.get(id(grader))
    if state is None or state.owner() is not grader:
        raise CustodyUnavailable('executor_original_unavailable')
    if time.time() >= state.deadline_utc:
        raise CustodyUnavailable('original_execution_deadline_expired')
    if _fingerprint(grader) != state.fingerprint:
        raise CustodyUnavailable('grader_private_context_changed')
    if _digest(state.geometry) != state.geometry_sha:
        raise CustodyUnavailable('retained_geometry_changed')
    for path, expected in state.manifest.items():
        if _hash(path) != expected:
            raise CustodyUnavailable('locked_original_file_changed', path=path)
    return state

def geometry_record(geometry: BoardGeometry) -> dict:
    """JSON-safe exact physical+intent fields for independent worker comparison.

    Only the top-level read pathname is excluded: original/read-copy paths are
    bound independently in the immutable read manifest. Derived lookup caches,
    pin names, stackup, layers, rules, poses, pads and copper are all retained.
    A public record/digest never confers registration or completion custody.
    """
    if type(geometry) is not BoardGeometry:
        raise CustodyUnavailable('typed_original_geometry_required')
    value = _value(geometry)
    value['fields'].pop('path')
    return {'schema': 1, 'path_policy': 'top-level BoardGeometry.path only; separately bound read manifest', 'typed_geometry': value}

def geometry_fingerprint(geometry: BoardGeometry) -> str:
    return hashlib.sha256(json.dumps(geometry_record(geometry), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def _executor_register_original(grader, *, geometry, read_manifest, read_identity, baseline, counted, open_before, selections, width_receipt, deadline_utc):
    """PRIVATE hook immediately after executor's original read+actual baseline.

    Caller is trusted executor code, not a public factory. Manifest was hashed
    around that actual read, not obtained from constructor fields afterward.
    """
    if isinstance(deadline_utc, bool) or not isinstance(deadline_utc, (int, float)) or (not math.isfinite(deadline_utc)) or (deadline_utc <= time.time()):
        raise CustodyUnavailable('original_execution_deadline_invalid')
    if type(grader) is not FinalCopperGrader:
        raise CustodyUnavailable('exact_physical_grader_required')
    if type(geometry) is not BoardGeometry:
        raise CustodyUnavailable('typed_original_geometry_required')
    if id(grader) in _REGISTRY:
        raise CustodyUnavailable('original_already_registered')
    if not isinstance(read_manifest, dict) or not read_manifest:
        raise CustodyUnavailable('read_manifest_required')
    manifest = {str(Path(p).resolve()): h for p, h in read_manifest.items()}
    if len(manifest) != len(read_manifest):
        raise CustodyUnavailable('duplicate_manifest_path')
    keys = {'original_read_path', 'read_sha256', 'snapshot_path', 'snapshot_sha256'}
    if not isinstance(read_identity, dict) or set(read_identity) != keys:
        raise CustodyUnavailable('geometry_read_identity_missing')
    identity = deepcopy(read_identity)
    for key in ('original_read_path', 'snapshot_path'):
        identity[key] = str(Path(identity[key]).resolve())
    if identity['original_read_path'] != str(Path(geometry.path).resolve()):
        raise CustodyUnavailable('geometry_read_path_mismatch')
    if identity['snapshot_path'] == identity['original_read_path']:
        raise CustodyUnavailable('protected_snapshot_must_be_separate')
    sha = identity['read_sha256']
    if not isinstance(sha, str) or len(sha) != 64 or identity['snapshot_sha256'] != sha or (manifest.get(identity['snapshot_path']) != sha):
        raise CustodyUnavailable('protected_snapshot_identity_mismatch')
    for p, h in manifest.items():
        if h is not None and (not isinstance(h, str) or len(h) != 64):
            raise CustodyUnavailable('read_hash_invalid')
        if _hash(p) != h:
            raise CustodyUnavailable('read_file_changed', path=p)
    retained = getattr(grader, '_inputs', None)
    if not isinstance(retained, dict) or any((manifest.get(str(Path(p).resolve()), object()) != h for p, h in retained.items())):
        raise CustodyUnavailable('grader_manifest_not_full_original')
    if counted != grader._counted or open_before != grader._open_before or width_receipt != json.loads(grader._widths):
        raise CustodyUnavailable('executor_original_facts_mismatch')
    facts = {
        'baseline': deepcopy(baseline),
        'counted': deepcopy(counted),
        'open_before': deepcopy(open_before),
        'selections': deepcopy(selections),
        'width_receipt': deepcopy(width_receipt),
    }
    _digest(facts)
    snap = deepcopy(geometry)
    _digest(snap)
    ident = id(grader)
    owner = weakref.ref(grader, lambda ref: _REGISTRY.pop(ident, None))
    _REGISTRY[ident] = _Original(
        owner,
        snap,
        _digest(snap),
        manifest,
        identity,
        facts,
        _fingerprint(grader),
        float(deadline_utc),
        _fingerprint(grader, include_template=False),
    )
    _context(grader)

def original_snapshot(grader: FinalCopperGrader) -> dict:
    """PUBLIC validation/read: detached retained typed context, never authority mint."""
    state = _context(grader)
    return {
        'custody_record': require_original(grader),
        'geometry': deepcopy(state.geometry),
        'read_manifest': deepcopy(state.manifest),
        'read_identity': deepcopy(state.read_identity),
        'original_facts': deepcopy(state.facts),
        'geometry_sha256': state.geometry_sha,
        'worker_geometry_record': geometry_record(state.geometry),
        'worker_geometry_sha256': geometry_fingerprint(state.geometry),
    }

def _executor_begin_calls(grader: FinalCopperGrader, executor: object) -> _Ledger:
    """PRIVATE actual _route_board context hook before the ordinary phase loop."""
    state = _context(grader)
    if state.run is not None or state.completed is not None:
        raise CustodyUnavailable('execution_already_started')
    ledger = _Ledger(_MINT, state, executor)
    state.run = ledger
    return ledger

def _executor_record_phase(grader, ledger, executor, index, record, *, calls, outputs):
    """PRIVATE hook after actual judge_phase or validated resumed phase record.

    This records actual ordinary phase/call/artifact receipts, not invented
    cleanup chronology or critical checks that the ordinary route never runs.
    """
    state = _context(grader)
    if state.run is not ledger or ledger.owner is not state or ledger.executor is not executor or ledger.sealed:
        raise CustodyUnavailable('execution_custody_mismatch')
    if isinstance(index, bool) or index != len(ledger.phases) or index >= len(grader._phases):
        raise CustodyUnavailable('ordinary_phase_order_mismatch')
    if not isinstance(record, dict) or record.get('name') != grader._phases[index].name or (not isinstance(calls, (tuple, list))):
        raise CustodyUnavailable('ordinary_phase_incomplete')
    phase = {'index': index, 'record': deepcopy(record), 'calls': deepcopy(calls)}
    if index < len(ledger.call_plans):
        planned, fingerprint = ledger.call_plans[index]
        from .final_call import record_digest
        if record_digest(planned) != fingerprint:
            raise CustodyUnavailable('ordinary_call_plan_changed')
        phase['actual_call_plan'] = deepcopy(planned)
    if ledger.issued:
        from .issued_calls import completed_record
        phase['issued_calls'] = [completed_record(grader, ledger, executor, token)
                                 for token in ledger.issued
                                 if token.record['identity']['phase'] == index]
    _digest(phase)
    new_outputs = {}
    for p, h in outputs.items():
        path = str(Path(p).resolve())
        if not isinstance(h, str) or len(h) != 64 or _hash(path) != h:
            raise CustodyUnavailable('completed_output_changed')
        new_outputs[path] = h
    ledger.phases.append(phase)
    ledger.outputs.update(new_outputs)

def _executor_observe_report(grader: FinalCopperGrader, ledger: _Ledger, executor: object, report: object) -> None:
    """PRIVATE constructor-owner hook when ordinary _route_board creates its report."""
    state = _context(grader)
    if state.run is not ledger or ledger.owner is not state or ledger.executor is not executor or (ledger.report is not None) or ledger.sealed:
        raise CustodyUnavailable('execution_custody_mismatch')
    if not is_dataclass(report) or len(ledger.phases) != len(grader._phases):
        raise CustodyUnavailable('ordinary_full_execution_incomplete')
    ledger.report = report

def _executor_seal_completed(grader, ledger, executor, report, *, report_json, outputs):
    """PRIVATE hook after ordinary actual full RouteReport and JSON are written.

    No critical proof is minted here; the bounded integrated worker supplies it.
    """
    state = _context(grader)
    if (
        state.run is not ledger
        or ledger.owner is not state
        or ledger.executor is not executor
        or ledger.report is not report
        or ledger.sealed
        or state.completed is not None
    ):
        raise CustodyUnavailable('execution_custody_mismatch')
    invocation = grader._semantic_contract['invocation']
    if not isinstance(invocation, dict) or invocation.get('upto') is not None or invocation.get('only') is not False or (invocation.get('quick') is not False):
        raise CustodyUnavailable('ordinary_full_invocation_required')
    if (
        not is_dataclass(report)
        or getattr(report, 'quick', True) is not False
        or report.asked != json.loads(grader._obligations)
        or len(report.phases) != len(grader._phases)
        or len(ledger.phases) != len(grader._phases)
    ):
        raise CustodyUnavailable('ordinary_full_execution_incomplete')
    for phase, actual, asked in zip(ledger.phases, report.phases, report.asked):
        if any((actual.get(k) != v for k, v in phase['record'].items())):
            raise CustodyUnavailable('actual_phase_ledger_mismatch')
        if actual.get('final_asked') != len(asked):
            raise CustodyUnavailable('final_phase_report_incomplete')
    if (
        not isinstance(report.final_judged, list)
        or len(report.final_judged) != len(report.asked)
        or any((len(j) != len(a) for j, a in zip(report.final_judged, report.asked)))
    ):
        raise CustodyUnavailable('final_phase_report_incomplete')
    paths = {str(Path(p).resolve()): h for p, h in outputs.items()}
    output = str(Path(report.routed_pcb).resolve())
    report_path = str(Path(report_json).resolve())
    drc_path = str((Path(report.work) / 'drc_after.json').resolve())
    if output not in paths or report_path not in paths or drc_path not in paths or any((_hash(p) != h for p, h in paths.items())):
        raise CustodyUnavailable('ordinary_final_artifacts_not_bound')
    if any((_hash(p) != h for p, h in ledger.outputs.items())):
        raise CustodyUnavailable('ordinary_call_artifacts_changed')
    try:
        published = json.loads(Path(report_path).read_bytes())
        actual = json.loads(json.dumps(report.as_dict(), sort_keys=True, allow_nan=False))
    except (OSError, ValueError, TypeError) as error:
        raise CustodyUnavailable('ordinary_full_report_unavailable') from error
    if published != actual:
        raise CustodyUnavailable('ordinary_report_artifact_mismatch')
    report_sha = _digest(report)
    if grader._template is None:
        grader.bind_execution(report)
    elif _digest(grader._template) != report_sha:
        raise CustodyUnavailable('public_template_not_actual_report')
    state.fingerprint = _fingerprint(grader)
    all_outputs = dict(ledger.outputs)
    all_outputs.update(paths)
    token = _Completion(_MINT, state, report_sha, all_outputs, _digest(ledger.phases))
    state.completed = token
    ledger.sealed = True
    return token

def completed_snapshot(grader: FinalCopperGrader, token: _Completion) -> dict:
    """PUBLIC worker-export prerequisite: validate exact private completed identity."""
    state = _context(grader)
    if state.completed is not token or type(token) is not _Completion or token.owner is not state:
        raise CustodyUnavailable('executor_completion_unavailable')
    if any((_hash(p) != h for p, h in token.outputs.items())):
        raise CustodyUnavailable('completed_output_changed')
    if _digest(grader._template) != token.report_sha:
        raise CustodyUnavailable('completed_report_changed')
    return {
        'custody_record': require_completed(grader, token),
        'original': original_snapshot(grader),
        'report': deepcopy(grader._template),
        'output_files': deepcopy(token.outputs),
        'ledger_sha256': token.ledger_sha,
    }

def require_original(grader: FinalCopperGrader) -> dict:
    """Detached JSON-safe getter; public records never register authority."""
    state = _context(grader)
    return {
        'schema': 1,
        'read_manifest': deepcopy(state.manifest),
        'read_identity': deepcopy(state.read_identity),
        'original_facts': _value(state.facts),
        'worker_geometry_record': geometry_record(state.geometry),
        'worker_geometry_sha256': geometry_fingerprint(state.geometry),
        'private_context_sha256': state.original_sha,
        'deadline_utc': state.deadline_utc,
    }

def require_completed(grader: FinalCopperGrader, token: _Completion | None = None) -> dict:
    """Parent export/import must call this on the SAME actual retained grader.

    Default reads the private completed registry entry, never a public template.
    An optional opaque token must be the exact privately sealed object.
    """
    state = _context(grader)
    actual = state.completed
    if actual is None or (token is not None and actual is not token) or type(actual) is not _Completion or (actual.owner is not state):
        raise CustodyUnavailable('executor_completion_unavailable')
    if any((_hash(p) != h for p, h in actual.outputs.items())):
        raise CustodyUnavailable('completed_output_changed')
    if _digest(grader._template) != actual.report_sha or _digest(state.run.phases) != actual.ledger_sha:
        raise CustodyUnavailable('completed_report_or_ledger_changed')
    return {
        'schema': 1,
        'original': require_original(grader),
        'completed': {
            'status': 'completed',
            'report': _value(grader._template),
            'report_sha256': actual.report_sha,
            'ordinary_phase_calls': _value(state.run.phases),
            'ordinary_phase_calls_sha256': actual.ledger_sha,
            'output_files': deepcopy(actual.outputs),
            'completed_at_utc': actual.completed_at,
            'deadline_utc': state.deadline_utc,
        },
    }
