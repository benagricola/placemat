"""Owned logical checking of two privately retained finalized route outputs.

The physical reports remain unchanged. This boundary does not accept a report,
hash descriptor or decoded packet as original execution custody. Comparison and
explore publication remain separate from this check's verified evidence.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys

from .final_authority import FullStandingAuthority, AuthoritativeCandidate
from .pinmap_common import CandidateRefused
from .pinmap_logical import LogicalTerminals
from .pinmap_logical_packet import _hash, _json, contract_record


def _refuse(code, **facts):
    raise CandidateRefused(code, 'retained logical route evidence is unavailable', **facts)


def _pair(authority, candidate):
    if type(authority) is not FullStandingAuthority or type(candidate) is not AuthoritativeCandidate:
        _refuse('logical_execution_custody_missing')
    authority.verify(candidate)
    retained = authority._minted[id(candidate)][2]
    if _json(asdict(candidate.standing)) != _json(asdict(retained)):
        _refuse('logical_execution_standing_changed')
    if _hash(authority._factory._critical) != authority._factory._critical_sha:
        _refuse('logical_original_check_intent_changed')
    if authority._factory.completed_authority() is not authority:
        _refuse('logical_execution_custody_mismatch')


def _intent(a, b):
    keys = ('settings', 'rules', 'acceptances', 'edge_margin', 'component_spacing',
            'board_shape', 'board_cutouts', 'quiet', 'planes', 'pending', 'fields')
    if any(key not in a or key not in b or _json(a[key]) != _json(b[key]) for key in keys):
        _refuse('logical_original_check_intent_changed')


def _artifact_record(side, destination):
    """Every output path is fixed by the owned request, never a reply path."""
    from .pinmap_written import _hash as file_hash
    final = destination / 'final.kicad_pcb'
    paths = [final, final.with_suffix('.kicad_pro'), destination / 'drc.json']
    custom = final.with_suffix('.kicad_dru')
    if custom.exists():
        paths.append(custom)
    expected = {str(path.absolute()): file_hash(path) for path in paths}
    if type(side) is not dict or _json(side.get('artifacts')) != _json(expected):
        _refuse('logical_worker_artifact_changed')


def _verdict(record):
    if (type(record) is not dict or set(record) not in ({'joined', 'violated', 'under'},
            {'joined', 'violated', 'under', 'width_unknown'})
            or type(record['joined']) is not bool or type(record['violated']) is not bool
            or type(record['under']) is not dict
            or ('width_unknown' in record and type(record['width_unknown']) is not bool)):
        _refuse('logical_worker_verdict_malformed')
    for layer, width in record['under'].items():
        if (type(layer) is not str or not layer or type(width) not in (int, float)
                or not 0 <= width < math.inf):
            _refuse('logical_worker_verdict_malformed')
        try:
            finite = math.isfinite(width)
        except OverflowError:
            finite = False
        if not finite:
            _refuse('logical_worker_verdict_malformed')
    if record.get('width_unknown'):
        _refuse('logical_required_width_unknown', judged=record)


def _environment(deadline):
    env = dict(os.environ)
    inherited = env.get('KRT_ROUTE_DEADLINE_UTC')
    if inherited is not None:
        try:
            value = float(inherited)
        except ValueError as error:
            raise CandidateRefused('logical_deadline_invalid', 'inherited deadline is malformed') from error
        if not math.isfinite(value) or value < deadline:
            _refuse('logical_deadline_context_mismatch')
    env['KRT_ROUTE_DEADLINE_UTC'] = str(deadline)
    return env


def _bundle(proof, a, b):
    from .kicad.final_call import file_hash
    expected = dict(proof.physical.inputs)
    if _json(expected) != _json(a._inputs):
        _refuse('logical_original_bundle_changed')
    sidecars = []
    final_inputs = {str(b._source): file_hash(b._source)}
    for raw, sha in expected.items():
        if Path(raw) == a._source:
            continue
        path = Path(raw)
        target = (b._source.with_suffix(path.suffix) if path in
                  (a._source.with_suffix('.kicad_pro'), a._source.with_suffix('.kicad_dru'))
                  else b._source.parent / path.name)
        sidecars.append({'original': raw, 'candidate': str(target), 'sha256': sha})
        final_inputs[str(target)] = sha
    if _json(b._inputs) != _json(final_inputs):
        _refuse('logical_candidate_bundle_changed')
    return {'original': {'path': str(a._source), 'sha256': file_hash(a._source)},
            'candidate': {'path': str(b._source), 'sha256': file_hash(b._source)}, 'sidecars': sidecars}


def _narrow_final(report):
    """Only current finalized per-ask narrow outcomes with an actual join."""
    from .kicad.phase_run import outcome_of
    if not (len(report.phases) == len(report.asked) == len(report.final_judged)):
        _refuse('logical_final_asks_unmeasured')
    for phase, asked, judged in zip(report.phases, report.asked, report.final_judged):
        if len(asked) != len(judged):
            _refuse('logical_final_asks_unmeasured')
        for ask, verdict in zip(asked, judged):
            _verdict(verdict)
            if verdict['joined'] and outcome_of(ask, phase.get('connections') or []) == 'joined_narrow':
                _refuse('logical_narrow_outcome_unsupported', obligation=ask, judged=verdict)


def _whole_from_files(side, original_open, original_counted, baseline, destination, cfg):
    from .kicad.drc import open_net_counts
    from .kicad.route import new_error_count
    from .pinmap_logical_worker import _clean_whole
    drc_path = destination / 'drc.json'
    data = json.loads(drc_path.read_text())
    is_real = set(cfg.drc_real_kinds).__contains__
    measured_new = new_error_count(baseline, drc_path, is_real)
    opens = {net: count for net, count in open_net_counts(data).items() if net not in original_counted}
    whole = _clean_whole(original_open, opens, data, is_real, original_counted)
    if (measured_new is None or side['drc_new'] != measured_new or _json(side['open_after']) != _json(opens)
            or side['closure_clean'] != round(whole.closure_clean, 4)):
        _refuse('logical_whole_artifact_mismatch')


def _judgment(side, phases, original_open, original_counted, baseline, critical, grader, destination):
    from .kicad.final_owned_worker import _validate_critical
    from .kicad.phase_run import is_clean
    keys = {'phases', 'drc_new', 'closure_clean', 'open_before', 'open_after',
            'critical', 'preservation', 'artifacts'}
    if type(side) is not dict or set(side) != keys:
        _refuse('logical_worker_judgment_malformed')
    if type(side['drc_new']) is not int or side['drc_new'] < 0:
        _refuse('logical_original_baseline_unmeasured')
    if _json(side['open_before']) != _json(original_open):
        _refuse('logical_original_denominator_changed')
    opens = side['open_after']
    if type(opens) is not dict or any(type(net) is not str or type(n) is not int or n < 0
                                    for net, n in opens.items()):
        _refuse('logical_worker_judgment_malformed')
    before, after = sum(original_open.values()), sum(opens.values())
    clean = side['closure_clean']
    if (type(clean) not in (int, float) or not 0 <= clean <= 1
            or (before == 0 and after) or after > before):
        _refuse('logical_whole_closure_unmeasured')
    records = side['phases']
    if type(records) is not list or len(records) != len(phases):
        _refuse('logical_final_asks_unmeasured')
    for expected, record in zip(phases, records):
        if (type(record) is not dict or set(record) != {'name', 'asked', 'joined', 'closure_clean', 'judged'}
                or record['name'] != expected['definition']['name']
                or type(record['asked']) is not int or record['asked'] != expected['asked_count']
                or type(record['judged']) is not list or len(record['judged']) != record['asked']):
            _refuse('logical_final_asks_unmeasured')
        judged = record['judged']
        for j in judged:
            _verdict(j)
        joined = sum(is_clean(j, None) for j in judged)
        closure = round(joined / record['asked'], 4) if record['asked'] else 1.0
        if (type(record['joined']) is not int or record['joined'] != joined
                or type(record['closure_clean']) not in (int, float) or record['closure_clean'] != closure):
            _refuse('logical_final_closure_changed')
    checks = side['critical']
    if type(checks) is not dict or set(checks) != {'measures', 'evidence'}:
        _refuse('logical_final_checks_unmeasured')
    _validate_critical(grader, critical, {**checks, 'preservation': side['preservation']})
    if checks['measures']['critical_unknown']:
        _refuse('logical_final_checks_unmeasured', unknown=checks['measures']['critical_unknown'])
    _artifact_record(side, destination)
    _whole_from_files(side, original_open, original_counted, baseline, destination, grader._cfg)


def check(proof, original_authority, original, candidate_authority, candidate, destination):
    """Run the third owned check under the two executions' original deadline.

    Returns checked JSON evidence only. The future private comparison consumer
    must keep these exact live objects and reverify them at adoption/publication.
    No serialized result from this function is independently authorizing.
    """
    if type(proof) is not LogicalTerminals:
        _refuse('logical_proof_missing')
    _pair(original_authority, original)
    _pair(candidate_authority, candidate)
    _narrow_final(original.physical.report)
    _narrow_final(candidate.physical.report)
    a, b = original_authority._factory, candidate_authority._factory
    proof.verify(a._board, a._plan, a._board.settings)
    if proof.physical.source.resolve() != a._source or a._deadline_utc != b._deadline_utc:
        _refuse('logical_original_execution_changed')
    _intent(a._critical, b._critical)
    from .kicad.final_owned_worker import (_execute, _implementation, _remaining,
                                         _validate_original_proof, _json as decode)
    from .kicad.final_worker_protocol import export
    from .pinmap_logical_worker import _scopes, _verify_pools
    from .pinmap_logical_worker import _input_bundle
    from .pinmap_written import _readback_expectation, _verify_readback_record
    from .occupancy import Occupancy
    deadline = a._deadline_utc
    _remaining(deadline)
    env = _environment(deadline)
    expected_readback = _readback_expectation(proof.physical)
    _verify_readback_record(expected_readback, Occupancy(copy.deepcopy(b._original_snapshot['geometry']),
                                                       settings=b._board.settings))
    input_bundle = _bundle(proof, a, b)
    expected_pools = _verify_pools(a._original_snapshot['geometry'], b._original_snapshot['geometry'], a._critical['quiet'])
    destination = Path(destination).absolute()
    if destination.exists():
        _refuse('logical_destination_exists')
    # All original selection work is pure over the executor's retained read.
    scopes, requests = _scopes(original_authority._grader, a._original_snapshot['geometry'])
    _, candidate_requests = _scopes(candidate_authority._grader, b._original_snapshot['geometry'])
    logical = contract_record(a._board, a._plan, proof, scopes, requests,
                              json.loads(original_authority._grader._widths), candidate_requests,
                              json.loads(candidate_authority._grader._widths), settings=a._board.settings)
    destination.mkdir(parents=True, exist_ok=False)
    packets = {name: export(authority._grader, result.physical.report.routed_pcb,
                           destination / name, deadline_utc=deadline)
               for name, authority, result in (('original', original_authority, original),
                                               ('candidate', candidate_authority, candidate))}
    request = {'schema': 1, 'deadline_utc': deadline, **packets, 'logical': logical,
               'expected_readback': expected_readback, 'input_bundle': input_bundle,
               'critical_original': copy.deepcopy(a._critical), 'critical_candidate': copy.deepcopy(b._critical)}
    runtime = _implementation()
    receipts = [copy.deepcopy(authority._grader.verify(result.physical))
                for authority, result in ((original_authority, original), (candidate_authority, candidate))]
    request_path, response_path = destination / 'request.json', destination / 'response.json'
    request_path.write_text(_json(request) + '\n')
    _input_bundle(input_bundle, request)
    rc, stdout, stderr = _execute([sys.executable, '-m', 'placemat.pinmap_logical_worker',
                                  str(request_path), str(response_path)], deadline, env)
    (destination / 'worker.stdout').write_text(stdout)
    (destination / 'worker.stderr').write_text(stderr)
    _remaining(deadline)
    for authority, result, expected in zip((original_authority, candidate_authority), (original, candidate), receipts):
        _pair(authority, result)
        if _json(authority._grader.verify(result.physical)) != _json(expected):
            _refuse('logical_execution_receipt_changed')
    proof.verify(a._board, a._plan, a._board.settings)
    if _implementation() != runtime or request_path.read_text() != _json(request) + '\n':
        _refuse('logical_worker_context_changed')
    if rc != 0 or not response_path.is_file():
        _refuse('logical_worker_refused', returncode=rc,
                response=decode(response_path.read_text()) if response_path.is_file() else None)
    response = decode(response_path.read_text())
    keys = {'schema', 'request_sha256', 'logical_sha256', 'implementation_start', 'implementation_end',
            'original_verification', 'judgments', 'fixed_preservation', 'pool_proof'}
    if (type(response) is not dict or set(response) != keys or type(response['schema']) is not int
            or response['schema'] != 1 or response['request_sha256'] != _hash(request)
            or response['logical_sha256'] != _hash(logical)
            or response['implementation_start'] != runtime or response['implementation_end'] != runtime):
        _refuse('logical_worker_reply_malformed')
    for field in ('judgments', 'original_verification'):
        if type(response[field]) is not dict or set(response[field]) != {'original', 'candidate'}:
            _refuse('logical_worker_reply_malformed')
    for name, authority, critical in (('original', original_authority, a._critical),
                                      ('candidate', candidate_authority, b._critical)):
        target = destination / name
        _validate_original_proof(authority._grader, response['original_verification'][name], target)
        _judgment(response['judgments'][name], logical['phases'], original_authority._grader._open_before,
                  original_authority._grader._counted,
                  response['original_verification']['original']['measured_drc_path'],
                  critical, authority._grader, target)
    fixed = {key: a._critical['source_physical'][key] for key in ('fixed_copper', 'protected_forms')}
    if _json(response['fixed_preservation']) != _json(fixed):
        _refuse('logical_original_fixed_copper_changed')
    if _json(response['pool_proof']) != _json(expected_pools):
        _refuse('logical_physical_pool_changed')
    # Validation itself reads several independent artifacts. Recheck all
    # previously read evidence after that pass, before returning checked data.
    for name, authority, result, expected in zip(('original', 'candidate'),
            (original_authority, candidate_authority), (original, candidate), receipts):
        _pair(authority, result)
        if _json(authority._grader.verify(result.physical)) != _json(expected):
            _refuse('logical_execution_receipt_changed')
        _validate_original_proof(authority._grader, response['original_verification'][name], destination / name)
        _artifact_record(response['judgments'][name], destination / name)
    proof.verify(a._board, a._plan, a._board.settings)
    _input_bundle(input_bundle, request)
    if (_implementation() != runtime or request_path.read_text() != _json(request) + '\n'
            or _json(decode(response_path.read_text())) != _json(response)):
        _refuse('logical_worker_context_changed')
    _remaining(deadline)
    return copy.deepcopy(response)
