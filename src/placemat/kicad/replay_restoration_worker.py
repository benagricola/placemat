"""Owned candidate call lifecycle, using the existing concrete route helpers."""
import hashlib
import json
from pathlib import Path
import shutil
import re
import sys
import time


def operations(request, route):
    current, given, output = map(Path, (request['current'], request['given'], request['output']))
    nets = {request['net']} if request['kind'] == 'pour' else set()
    if request['stage'] == 'prepare':
        shutil.copyfile(current, given)
        route._copy_project(current, given)
        if nets:
            route.drop_pour_guards(str(given), nets)
            route.pours_as_zones(str(given), request['net'])
    else:
        route._copy_project(given, output)
        if nets:
            route.pours_back(str(output), str(current))
        route.lock_copper(str(output))
        if nets:
            route.guard_partial_pours(str(output), nets, request['guard_layers'], request['plane_share'])


def evaluate(request):
    from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
    fields = {'schema', 'stage', 'kind', 'current', 'given', 'output', 'net',
              'guard_layers', 'plane_share', 'settings', 'deadline_utc', 'inputs', 'raw_output_sha256'}
    if (not isinstance(request, dict) or set(request) != fields
            or type(request['schema']) is not int or request['schema'] != 1
            or request['stage'] not in ('prepare', 'restore')
            or request['kind'] not in ('single', 'connections', 'pour')
            or type(request['deadline_utc']) not in (int, float)
            or not time.time() < request['deadline_utc'] < float('inf')):
        raise ProofUnavailable('replay_restoration_request_unproved')
    raw = request['raw_output_sha256']
    if (request['stage'] == 'prepare' and raw is not None
            or request['stage'] == 'restore' and (not isinstance(raw, str)
            or re.fullmatch('[0-9a-f]{64}', raw) is None)):
        raise ProofUnavailable('replay_restoration_raw_unproved')
    for key in ('current', 'given', 'output'):
        if not isinstance(request[key], str) or not Path(request[key]).is_absolute():
            raise ProofUnavailable('replay_restoration_paths_unproved')
    if (not isinstance(request['guard_layers'], list)
            or any(not isinstance(layer, str) for layer in request['guard_layers'])
            or type(request['plane_share']) not in (int, float)
            or not 0 <= request['plane_share'] <= 1
            or (request['kind'] == 'pour' and (not isinstance(request['net'], str) or not request['net']))
            or (request['kind'] != 'pour' and request['net'] is not None)):
        raise ProofUnavailable('replay_restoration_scope_unproved')
    if (not isinstance(request['inputs'], dict) or not request['inputs']
            or any(not isinstance(path, str) or not Path(path).is_absolute()
                   or value is not None and (not isinstance(value, str)
                                             or re.fullmatch('[0-9a-f]{64}', value) is None)
                   for path, value in request['inputs'].items())
            or not isinstance(request['settings'], dict)):
        raise ProofUnavailable('replay_restoration_request_unproved')
    def unchanged():
        if time.time() >= request['deadline_utc']:
            raise ProofUnavailable('replay_deadline_expired')
        for path, expected in request['inputs'].items():
            actual = file_hash(path) if Path(path).is_file() else None
            if actual != expected:
                raise ProofUnavailable('replay_restoration_input_changed', path=path)
    changed = Path(request['given'] if request['stage'] == 'prepare' else request['output'])
    if any(Path(path) in {changed, changed.with_suffix('.kicad_pro'), changed.with_suffix('.kicad_dru')} for path in request['inputs']):
        raise ProofUnavailable('replay_restoration_mutable_input')
    unchanged()
    if request['stage'] == 'restore' and file_hash(request['output']) != request['raw_output_sha256']:
        raise ProofUnavailable('replay_restoration_raw_changed')
    # Native loads happen only inside the existing owned child deadline.
    import placemat_native
    from placemat.kicad.quiet import import_pcbnew
    import_pcbnew()
    from placemat.kicad.final_owned_worker import _implementation
    from placemat.kicad import route
    from placemat.settings import Settings, SettingsError, _coerce, _validate, bind
    from dataclasses import asdict, fields
    from placemat.kicad.final_worker_protocol import _plain
    implementation = _implementation()
    values = request['settings']
    if (not isinstance(values.get('sources'),dict)
            or any(not isinstance(key,str) or not isinstance(value,str)
                   for key,value in values['sources'].items())):
        raise ProofUnavailable('replay_restoration_settings_changed')
    declared = {field.name: str(field.type) for field in fields(Settings)}
    if set(values) != set(declared):
        raise ProofUnavailable('replay_restoration_settings_changed')
    try:
        for key, value in values.items():
            if key == 'sources' or value is None and 'None' in declared[key]:
                continue
            _validate(key, value, 'retained restoration settings')
        cfg = Settings(**{key: _coerce(key, value) for key, value in values.items()})
    except (SettingsError, TypeError, ValueError) as error:
        raise ProofUnavailable('replay_restoration_settings_changed') from error
    if record_digest(_plain(asdict(cfg))) != record_digest(values):
        raise ProofUnavailable('replay_restoration_settings_changed')
    with bind(cfg):
        operations(request, route)
    unchanged()
    end = _implementation()
    if record_digest(implementation) != record_digest(end):
        raise ProofUnavailable('replay_restoration_implementation_changed')
    from placemat.kicad import issued_calls
    return {'schema': 1, 'request_sha256': record_digest(request),
            'implementation_start': implementation, 'implementation_end': end,
            'worker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'outputs': issued_calls._files(request['given'] if request['stage'] == 'prepare' else request['output'])}


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(2)
    result = evaluate(json.loads(Path(sys.argv[1]).read_bytes()))
    with Path(sys.argv[2]).open('x') as stream:
        json.dump(result, stream, allow_nan=False)
        stream.write('\n')
