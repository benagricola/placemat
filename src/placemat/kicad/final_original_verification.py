"""Worker-only independent original baseline verification; scratch review draft.

Caller must run this entire operation in the owned final-check worker within
its original absolute deadline. No baseline supplied by a packet is authority
until the exact original source is independently copied, locked and measured.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest


def _remaining(deadline):
    from placemat.kicad.final_owned_worker import _remaining as check
    return check(deadline)


def _semantic_drc(path):
    """Retain all checks and geometry; omit only report time/source pathname."""
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ProofUnavailable('original_baseline_malformed')
            out[key] = value
        return out
    try:
        raw = json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                         parse_constant=lambda _: (_ for _ in ()).throw(
                             ProofUnavailable('original_baseline_malformed')))
    except (OSError, ValueError, UnicodeError) as error:
        raise ProofUnavailable('original_baseline_unavailable') from error
    if (not isinstance(raw, dict)
            or raw.get('$schema') != 'https://schemas.kicad.org/drc.v1.json'
            or not isinstance(raw.get('violations'), list)
            or not isinstance(raw.get('unconnected_items'), list)):
        raise ProofUnavailable('original_baseline_malformed')
    raw.pop('date', None)
    raw.pop('source', None)
    unordered = {('violations',), ('unconnected_items',),
                 ('violations', '*', 'items'), ('unconnected_items', '*', 'items')}
    def canonical(value, path=()):
        if isinstance(value, dict):
            return {key: canonical(item, path + (key,)) for key, item in value.items()}
        if isinstance(value, list):
            records = [canonical(item, path + ('*',)) for item in value]
            if path in unordered:
                if any(not isinstance(item, dict) for item in records):
                    raise ProofUnavailable('original_baseline_malformed')
                return sorted(records, key=lambda item: json.dumps(item, sort_keys=True, allow_nan=False))
            return records
        return value
    return canonical(raw)


def verify_original(grader, *, fresh_directory, deadline_utc, executor_custody):
    """Repeat production pre-guard measurement from immutable original files."""
    from placemat.settings import bind
    from placemat.kicad.final_route import FinalCopperGrader
    from placemat.kicad.route import copy_source_rules, lock_copper
    from placemat.kicad.read import read_board
    from placemat.kicad.drc import run_drc
    from placemat.kicad.phase_select import select
    from placemat.kicad.phase_run import comparison_obligations
    from placemat.kicad.width_policy import apply, requests_of, validate_receipt
    from placemat.capture_nets import read_capture
    from placemat.checks import COPPER_OZ
    from .final_custody import geometry_record, geometry_fingerprint
    _remaining(deadline_utc)
    if type(grader) is not FinalCopperGrader:
        raise ProofUnavailable('original_context_unavailable')
    if (not isinstance(executor_custody, dict) or set(executor_custody) != {'schema', 'original', 'completed'}
            or type(executor_custody['schema']) is not int or executor_custody['schema'] != 1
            or not isinstance(executor_custody['original'], dict)
            or not isinstance(executor_custody['completed'], dict)):
        raise ProofUnavailable('original_executor_custody_malformed')
    original_custody = executor_custody['original']
    completed = executor_custody['completed']
    if (original_custody.get('deadline_utc') != deadline_utc
            or completed.get('deadline_utc') != deadline_utc or completed.get('status') != 'completed'):
        raise ProofUnavailable('original_executor_custody_incomplete')
    binding = grader.binding()
    invocation = binding['contract']['invocation']
    if (not isinstance(invocation, dict) or invocation.get('upto') is not None
            or invocation.get('only') is not False or invocation.get('quick') is not False):
        raise ProofUnavailable('original_invocation_unsupported')
    root = Path(fresh_directory)
    root.mkdir(parents=True, exist_ok=False)
    source = Path(binding['paths']['original'])
    copied = root / 'original.kicad_pcb'
    shutil.copyfile(source, copied)
    copy_source_rules(source, copied)
    with bind(grader._cfg):
        lock_copper(str(copied))
        _remaining(deadline_utc)
        geometry = read_board(str(copied))
        _remaining(deadline_utc)
        if (geometry_record(geometry) != original_custody.get('worker_geometry_record')
                or geometry_fingerprint(geometry) != original_custody.get('worker_geometry_sha256')):
            raise ProofUnavailable('original_read_geometry_mismatch')
        capture_record = invocation['capture']
        capture = read_capture(capture_record['path']) if capture_record['path'] is not None else None
        if (capture_record['path'] is not None
                and file_hash(capture_record['path']) != capture_record['sha256']):
            raise ProofUnavailable('original_capture_changed')
        excluded = set(invocation['exclude_nets'])
        pours = set(invocation['pour_nets']) & set(geometry.nets)
        picked = [select(phase, geometry, capture, open_nets=set(geometry.nets),
                         excluded=excluded, pour_nets=pours,
                         route_layers=invocation['layers'], rise_c=grader._cfg.check_rise_c,
                         copper_oz=COPPER_OZ) for phase in grader._phases]
        chosen = set().union(*(set(item.pour_nets) for item in picked))
        counted = excluded | (pours - chosen)
        if counted != grader._counted or chosen != grader._chosen_pours:
            raise ProofUnavailable('original_counted_scope_mismatch')
        width_receipt = json.loads(grader._widths)
        query = invocation['width_query_input']
        if file_hash(query['path']) != query['sha256']:
            raise ProofUnavailable('original_width_query_input_changed')
        requests = requests_of(list(grader._phases), picked, grader._cfg)
        validate_receipt(width_receipt, pcb=Path(query['path']),
                         router_dir=Path(invocation['router_dir']), requests=requests)
        obligations = comparison_obligations(picked, geometry, excluded)
        obligations = apply(obligations, picked, list(grader._phases), width_receipt)
        if obligations != json.loads(grader._obligations):
            raise ProofUnavailable('original_obligation_scope_mismatch')
        measured_path = root / 'drc_before.json'
        before = run_drc(copied, measured_path)
        _remaining(deadline_utc)
        open_before = {name: count for name, count in before.open_nets.items() if name not in counted}
        if open_before != grader._open_before:
            raise ProofUnavailable('original_open_counts_mismatch')
        original = _semantic_drc(binding['paths']['baseline_drc'])
        measured = _semantic_drc(measured_path)
        if original != measured:
            raise ProofUnavailable('original_baseline_mismatch')
    grader._unchanged()
    _remaining(deadline_utc)
    return {'schema': 1, 'original_context_sha256': binding['contract_sha256'],
            'source_sha256': file_hash(source), 'copied_sha256': file_hash(copied),
            'baseline_semantics_sha256': record_digest(measured),
            'measured_drc_path': str(measured_path.absolute()),
            'measured_drc_sha256': file_hash(measured_path),
            'copied_path': str(copied.absolute()),
            'counted': sorted(counted), 'chosen_pours': sorted(chosen),
            'open_before': open_before, 'obligations_sha256': record_digest(obligations)}
