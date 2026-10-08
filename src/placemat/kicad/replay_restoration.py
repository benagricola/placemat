"""Concrete native lifecycle child using the existing owned deadline runner."""
import json
from dataclasses import asdict
from pathlib import Path
import sys

from placemat.kicad import issued_calls
from placemat.kicad.final_worker_protocol import _plain
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad.final_owned_worker import _execute, _implementation


def run(budget, original, ctx, stage, current, given, output, work):
    budget._check(budget.executor)
    if record_digest(_plain(asdict(ctx.cfg))) != record_digest(_plain(asdict(budget.grader._cfg))):
        raise ProofUnavailable('replay_retained_settings_changed')
    kind = original['identity']['kind']
    if kind not in ('single', 'connections', 'pour') or kind == 'pour' and len(original['nets']) != 1:
        raise ProofUnavailable('replay_restoration_kind_unproved')
    paths = {key: str(Path(value).resolve()) for key, value in
             (('current', current), ('given', given), ('output', output))}
    if stage not in ('prepare', 'restore') or len(set(paths.values())) != 3:
        raise ProofUnavailable('replay_restoration_paths_unproved')
    inputs = issued_calls._files(paths['current'])
    if stage == 'restore':
        inputs.update(issued_calls._files(paths['given']))
    request = dict(paths, schema=1, stage=stage, kind=kind,
                   net=original['nets'][0] if kind == 'pour' else None,
                   guard_layers=list(ctx.layers), plane_share=ctx.cfg.route_plane_share,
                   settings=_plain(asdict(ctx.cfg)), deadline_utc=budget.deadline,
                   inputs=inputs,
                   raw_output_sha256=file_hash(output) if stage == 'restore' else None)
    implementation = _implementation()  # already-loaded actual parent modules only
    worker = Path(__file__).with_name('replay_restoration_worker.py')
    worker_sha = file_hash(worker)
    request_path = Path(work) / (stage + '-request.json')
    response_path = Path(work) / (stage + '-response.json')
    if response_path.exists():
        raise ProofUnavailable('replay_restoration_destination_not_fresh')
    with request_path.open('x') as stream:
        json.dump(request, stream, allow_nan=False)
    request_sha = file_hash(request_path)
    rc, stdout, stderr = _execute([sys.executable, str(worker), str(request_path), str(response_path)],
                                  budget.deadline, dict(ctx.env))
    Path(work, stage + '.log').write_text(stdout + stderr)
    budget._check(budget.executor)
    if rc != 0 or file_hash(request_path) != request_sha or file_hash(worker) != worker_sha:
        raise ProofUnavailable('replay_restoration_incomplete', returncode=rc)
    try:
        response = json.loads(response_path.read_bytes())
    except (OSError, ValueError, UnicodeError) as error:
        raise ProofUnavailable('replay_restoration_response_unavailable') from error
    keys = {'schema', 'request_sha256', 'implementation_start', 'implementation_end', 'worker_sha256', 'outputs'}
    if (not isinstance(response, dict) or set(response) != keys
            or type(response['schema']) is not int or response['schema'] != 1
            or response['request_sha256'] != record_digest(request)
            or response['worker_sha256'] != worker_sha
            or record_digest(response['implementation_start']) != record_digest(implementation)
            or record_digest(response['implementation_end']) != record_digest(implementation)
            or record_digest(_implementation()) != record_digest(implementation)):
        raise ProofUnavailable('replay_restoration_implementation_unproved')
    actual = issued_calls._files(given if stage == 'prepare' else output)
    if record_digest(response['outputs']) != record_digest(actual):
        raise ProofUnavailable('replay_restoration_output_changed')
    issued_calls._unchanged(inputs)
    return {str(request_path): request_sha, str(response_path): file_hash(response_path)}
