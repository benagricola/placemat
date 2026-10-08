"""Strict physical context transport for a supervised final-board worker.

This codec provides no adoption authority. The parent must bind the actual
owned execution, request, implementation and deadline before importing results.
"""
from dataclasses import asdict, fields
import json
import math
from pathlib import Path
import time

from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad.final_route import FinalCopperGrader
from placemat.kicad.route import RouteReport
from placemat.route_phase import phases_of
from placemat.settings import Settings, SettingsError, _coerce, _validate

_PATH_FIELDS = frozenset(('routed_pcb', 'log', 'work'))


def _plain(value):
    def path(item):
        if isinstance(item, Path):
            return str(item)
        raise TypeError('unsupported physical worker value')
    try:
        return json.loads(json.dumps(value, default=path, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ProofUnavailable('physical_worker_value_unsupported') from error


def _keys(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ProofUnavailable('physical_worker_scope_mismatch')


def _deadline(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= time.time()):
        raise ProofUnavailable('physical_worker_deadline_expired')


def _path(value):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ProofUnavailable('physical_worker_path_malformed')
    return Path(value)


def _artifact_fields(record):
    _keys(record, ('path', 'sha256'))
    path = _path(record['path'])
    digest = record['sha256']
    if (not isinstance(digest, str) or len(digest) != 64
            or any(char not in '0123456789abcdef' for char in digest)):
        raise ProofUnavailable('physical_worker_hash_malformed')
    return path


def validate_packet_fields(record):
    """Pure transport shape validation before constructing owned destinations."""
    _keys(record, ('schema', 'deadline_utc', 'binding', 'settings', 'template', 'raw',
                   'destination', 'candidate_summary', 'executor_custody'))
    if type(record['schema']) is not int or record['schema'] != 1:
        raise ProofUnavailable('physical_worker_schema')
    _deadline(record['deadline_utc'])
    if any(not isinstance(record[key], dict) for key in ('binding', 'settings', 'template', 'executor_custody')):
        raise ProofUnavailable('physical_worker_context_malformed')
    _artifact_fields(record['raw'])
    _path(record['destination'])
    if record['candidate_summary'] is not None:
        _artifact_fields(record['candidate_summary'])


def _artifact(path):
    path = Path(path).absolute()
    try:
        return {'path': str(path), 'sha256': file_hash(path)}
    except OSError as error:
        raise ProofUnavailable('physical_worker_input_unavailable', path=str(path)) from error


def _read_artifact(record):
    path = _artifact_fields(record)
    try:
        digest = file_hash(path)
    except OSError as error:
        raise ProofUnavailable('physical_worker_input_unavailable', path=str(path)) from error
    if digest != record['sha256']:
        raise ProofUnavailable('physical_worker_input_changed', path=str(path))
    return path

def report_record(report):
    if type(report) is not RouteReport:
        raise ProofUnavailable('physical_worker_report_type')
    return _plain(asdict(report))


def read_report(record):
    _keys(record, (field.name for field in fields(RouteReport)))
    values = _plain(record)
    for name in _PATH_FIELDS:
        values[name] = _path(values[name])
    for name in ('valid', 'quick'):
        if type(values[name]) is not bool:
            raise ProofUnavailable('physical_worker_report_malformed', field=name)
    for name in ('open_before', 'open_after', 'widths_failed', 'vias', 'segments'):
        if type(values[name]) is not int or values[name] < 0:
            raise ProofUnavailable('physical_worker_report_malformed', field=name)
    for name in ('closure', 'closure_clean', 'seconds', 'track_mm'):
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ProofUnavailable('physical_worker_report_malformed', field=name)
    for name in ('asked', 'final_judged', 'phases'):
        if not isinstance(values[name], list):
            raise ProofUnavailable('physical_worker_report_malformed', field=name)
    if not (len(values['asked']) == len(values['final_judged']) == len(values['phases'])):
        raise ProofUnavailable('physical_worker_judgement_scope_mismatch')
    if any(not isinstance(a, list) or not isinstance(j, list) or len(a) != len(j)
           for a, j in zip(values['asked'], values['final_judged'])):
        raise ProofUnavailable('physical_worker_judgement_scope_mismatch')
    return RouteReport(**values)


def export(grader, raw, destination, *, deadline_utc, candidate_summary=None):
    """Export only the actual retained context after completed incumbent binding."""
    _deadline(deadline_utc)
    if type(grader) is not FinalCopperGrader or grader._template is None:
        raise ProofUnavailable('physical_worker_context_unavailable')
    from .final_custody import require_completed
    executor_custody = require_completed(grader)
    if any(executor_custody[key]['deadline_utc'] != deadline_utc for key in ('original', 'completed')):
        raise ProofUnavailable('physical_worker_deadline_context_mismatch')
    binding = grader.binding()
    if binding['contract']['invocation'] is None or binding['paths']['width_receipt'] is None:
        raise ProofUnavailable('physical_worker_original_authority_missing')
    return {'schema': 1, 'deadline_utc': deadline_utc, 'binding': binding,
            'executor_custody': executor_custody,
            'settings': _plain(asdict(grader._cfg)), 'template': report_record(grader._template),
            'raw': _artifact(raw), 'destination': str(Path(destination).absolute()),
            'candidate_summary': _artifact(candidate_summary) if candidate_summary is not None else None}


def reconstruct(record):
    """Reconstruct named original types only; unsupported phase overrides refuse.

    The original executor factory independently validates the scope before it
    exports this packet. The worker repeats identity checks rather than trusting
    candidate-derived settings, widths, selections or reports.
    """
    validate_packet_fields(record)
    values = record['settings']
    _keys(values, (field.name for field in fields(Settings)))
    sources = values['sources']
    if not isinstance(sources, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                          for k, v in sources.items()):
        raise ProofUnavailable('physical_worker_settings_malformed')
    declared = {field.name: str(field.type) for field in fields(Settings)}
    try:
        for key, value in values.items():
            if key == 'sources' or value is None and 'None' in declared[key]:
                continue
            _validate(key, value, 'original physical worker context')
        cfg = Settings(**{key: _coerce(key, value) for key, value in values.items()})
    except (SettingsError, TypeError, ValueError) as error:
        raise ProofUnavailable('physical_worker_settings_malformed') from error
    binding = record['binding']
    _keys(binding, ('contract_sha256', 'contract', 'paths'))
    contract, paths = binding['contract'], binding['paths']
    _keys(contract, ('obligations', 'width_authority', 'phases', 'settings', 'source_inputs',
                     'counted', 'open_before', 'chosen_pours', 'invocation', 'width_receipt_sha256'))
    _keys(paths, ('original', 'cleanup_input', 'rules', 'baseline_drc', 'width_receipt'))
    if record_digest(contract) != binding['contract_sha256']:
        raise ProofUnavailable('physical_worker_contract_mismatch')
    phases = phases_of(cfg)
    if _plain([phase.key() for phase in phases]) != contract['phases']:
        raise ProofUnavailable('physical_worker_phase_override_unsupported')
    raw = _read_artifact(record['raw'])
    summary = _read_artifact(record['candidate_summary']) if record['candidate_summary'] is not None else None
    destination = _path(record['destination'])
    grader = FinalCopperGrader(original=_path(paths['original']), cleanup_input=_path(paths['cleanup_input']),
                              rules=_path(paths['rules']), baseline_drc=_path(paths['baseline_drc']),
                              obligations=contract['obligations'], phases=phases,
                              width_receipt=contract['width_authority'], cfg=cfg,
                              counted=contract['counted'], open_before=contract['open_before'],
                              chosen_pours=contract['chosen_pours'], invocation=contract['invocation'],
                              width_receipt_path=_path(paths['width_receipt']))
    if grader.binding() != binding:
        raise ProofUnavailable('physical_worker_context_changed')
    grader.bind_execution(read_report(record['template']))
    from .final_original_verification import verify_original
    proof = verify_original(grader, fresh_directory=destination.parent / (destination.name + '.original-check'),
                            deadline_utc=record['deadline_utc'], executor_custody=record['executor_custody'])
    grader._worker_original_proof = proof
    _deadline(record['deadline_utc'])
    return grader, raw, destination, summary
