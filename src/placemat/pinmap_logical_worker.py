"""Owned logical route checks; decoded records never mint comparison authority."""
from __future__ import annotations

from collections import Counter, defaultdict
import math

from .pinmap_common import CandidateRefused


def _refuse(code, **facts):
    raise CandidateRefused(code, 'owned logical route proof is unavailable', **facts)


def _pin_nets(geometry):
    nets, lands = {}, Counter()
    if len({fp.ref for fp in geometry.footprints}) != len(geometry.footprints):
        _refuse('logical_terminal_ambiguous')
    for fp in geometry.footprints:
        for pad in fp.pads:
            key = fp.ref, pad.number
            if key in nets and nets[key] != pad.net:
                _refuse('logical_terminal_ambiguous', ref=fp.ref, pad=pad.number)
            nets[key] = pad.net
            lands[key] += 1
    return nets, lands


def _verify_pools(source, candidate, quiet):
    """Repeat declared physical pool legality from independent saved reads.

    Physical cell members retain their actual source grouping. Nets wholly
    inside that group remain held, using the same part_pins inside predicate.
    No carried alias string is inferred to be a movable physical pin. Live
    parent capability checks still establish all permitted pose changes.
    """
    from .pinmap_rules import read_rules, part_pins
    original, source_lands = _pin_nets(source)
    final, final_lands = _pin_nets(candidate)
    if source_lands != final_lands:
        _refuse('logical_land_membership_changed')
    refs = {ref for ref, number in original if original[ref, number] != final[ref, number]}
    by_net = defaultdict(set)
    for pin, net in original.items():
        by_net[net].add(pin)
    connected = {net for net, pins in by_net.items() if net and len(pins) > 1}
    out = []
    footprints = {fp.ref: fp for fp in source.footprints}
    for ref in sorted(refs):
        fp = footprints[ref]
        members = {item.ref for item in source.footprints if fp.cell and item.cell == fp.cell}
        inside = {net for net, pins in by_net.items() if members and all(owner in members for owner, _ in pins)}
        pads = {}
        for pad in fp.pads:
            entry = pad.net, pad.no_connect
            if pad.number in pads and pads[pad.number] != entry:
                _refuse('logical_terminal_ambiguous', ref=ref, pad=pad.number)
            pads[pad.number] = entry
        rules, problems = read_rules(ref, fp.fields, [(number, net) for number, (net, _) in pads.items()],
                                    source.pin_names.get(ref, {}))
        if rules is None or problems:
            _refuse('logical_pin_rules_unproved', ref=ref)
        slots, problems = part_pins(rules, [(number, net, nc) for number, (net, nc) in pads.items()],
                                   connected, set(quiet), inside=inside)
        if slots is None or problems:
            _refuse('logical_pin_rules_unproved', ref=ref)
        actual = {}
        for net in slots.movable:
            pins = [number for owner, number in final if owner == ref and final[owner, number] == net]
            if len(pins) != 1 or pins[0] not in slots.allowed[net]:
                _refuse('logical_pin_pool_illegal', ref=ref, net=net)
            actual[net] = pins[0]
        mutable = set(slots.present.values()) | set(slots.free)
        for number, (net, _) in pads.items():
            if number not in mutable and final[ref, number] != net:
                _refuse('logical_held_endpoint_changed', ref=ref, pad=number)
        expected = Counter(net for number, (net, _) in pads.items())
        got = Counter(final[ref, number] for number in pads)
        if expected != got:
            _refuse('logical_terminal_multiplicity', ref=ref)
        if len(set(actual.values())) != len(actual):
            _refuse('logical_pin_pool_illegal', ref=ref)
        for name, nets in slots.groups:
            if not any(all(not net or actual.get(net) == number for net, number in zip(nets, window))
                       for window in slots.windows[name]):
                _refuse('logical_hard_group_changed', ref=ref, group=name)
        out.append({'ref': ref, 'mapping': [[net, slots.present[net], actual[net]] for net in sorted(actual)]})
    return out


def _scopes(grader, geometry):
    import json
    from .capture_nets import read_capture
    from .checks import COPPER_OZ
    from .kicad.phase_select import select
    from .kicad.width_policy import requests_of
    from .pinmap_logical_packet import _hash
    invocation = grader.binding()['contract']['invocation']
    capture = invocation['capture']
    capture = read_capture(capture['path']) if capture['path'] is not None else None
    selections = [select(phase, geometry, capture, open_nets=set(geometry.nets),
                         excluded=set(invocation['exclude_nets']), pour_nets=set(invocation['pour_nets']),
                         route_layers=invocation['layers'], rise_c=grader._cfg.check_rise_c,
                         copper_oz=COPPER_OZ) for phase in grader._phases]
    obligations = json.loads(grader._obligations)
    if len(obligations) != len(selections):
        _refuse('logical_original_asks_missing')
    scopes = []
    for phase, selected, asked in zip(grader._phases, selections, obligations):
        if selected.tasks:
            _refuse('logical_physical_task_unsupported', phase=phase.name)
        nets = set(selected.nets) | set(selected.pour_nets)
        nets.update(net for group in (*selected.pairs, *selected.buses) for net in group)
        scopes.append({'definition': json.loads(json.dumps(phase.key())), 'nets': sorted(nets),
                       'tasks': [], 'asked': asked, 'asked_sha256': _hash(asked)})
    return scopes, requests_of(list(grader._phases), selections, grader._cfg)


def _clean_whole(original_open, open_after, data, is_real, counted):
    before, after = sum(original_open.values()), sum(open_after.values())
    if before == 0 and after:
        _refuse('logical_zero_denominator_opened', original_open=original_open, open_after=open_after)
    if after > before:
        _refuse('logical_final_open_exceeds_denominator', original_open=original_open, open_after=open_after)
    from .kicad.drc import real_errors
    from .kicad.route import score
    violated = {net for error in real_errors(data, is_real) for net in error['nets']}
    result = score(original_open, open_after, violated - counted)
    if not 0 <= result.closure_clean <= 1 or not math.isfinite(result.closure_clean):
        _refuse('logical_whole_closure_unmeasured', original_open=original_open, open_after=open_after,
                closure_clean=result.closure_clean)
    return result


def _input_bundle(bundle, packets):
    """Exact original sidecar relation, independently checked in the child."""
    from pathlib import Path
    import hashlib
    from .pinmap_logical_packet import _json
    if type(bundle) is not dict or set(bundle) != {'original', 'candidate', 'sidecars'}:
        _refuse('logical_input_bundle_malformed')
    for side in ('original', 'candidate'):
        artifact = bundle[side]
        if (type(artifact) is not dict or set(artifact) != {'path', 'sha256'}
                or artifact['path'] != packets[side]['binding']['paths']['original']):
            _refuse('logical_input_bundle_malformed')
    rows = bundle['sidecars']
    if type(rows) is not list:
        _refuse('logical_input_bundle_malformed')
    seen = {'original': set(), 'candidate': set()}
    for row in rows:
        if type(row) is not dict or set(row) != {'original', 'candidate', 'sha256'}:
            _refuse('logical_input_bundle_malformed')
        for side in seen:
            if type(row[side]) is not str or row[side] in seen[side]:
                _refuse('logical_input_bundle_malformed')
            seen[side].add(row[side])
    for side in ('original', 'candidate'):
        source = Path(bundle[side]['path'])
        for ext in ('.kicad_pro', '.kicad_dru'):
            matches = [row for row in rows if row[side] == str(source.with_suffix(ext))]
            if len(matches) != 1 or matches[0]['sha256'] != packets[side]['binding']['contract']['source_inputs']['rules'][ext]:
                _refuse('logical_input_sidecar_changed', side=side, extension=ext)
    for artifact in [bundle['original'], bundle['candidate'],
                     *({'path': row[side], 'sha256': row['sha256']} for row in rows for side in seen)]:
        path = artifact['path']
        expected = artifact['sha256']
        if type(path) is not str or not Path(path).is_absolute() or (expected is not None and
                (type(expected) is not str or len(expected) != 64)):
            _refuse('logical_input_bundle_malformed')
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None
        if actual != expected:
            _refuse('logical_input_sidecar_changed', path=path)
    # Every explicitly supplied capture must be one of these retained files.
    for side in seen:
        capture = packets[side]['binding']['contract']['invocation']['capture']
        if capture['path'] is not None and not any(row[side] == capture['path'] and
                                                   row['sha256'] == capture['sha256'] for row in rows):
            _refuse('logical_input_capture_changed', side=side)
    _json(bundle)


def _final_side(grader, raw, destination, asks, critical, original_baseline, original_open, original_counted, deadline):
    from pathlib import Path
    import shutil
    from .settings import bind
    from .kicad.route import copy_source_rules, new_error_count
    from .kicad.drc import run_drc
    from .kicad.phase_run import judge_obligations, phase_neck, is_clean
    from .kicad.final_owned_worker import _remaining
    from .kicad.final_call import file_hash
    from .final_check_context import judge
    from .final_preservation import verify
    from .pinmap_written import _read_occupancy
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    final = destination / 'final.kicad_pcb'
    shutil.copyfile(raw, final)
    copy_source_rules(grader._original, final)
    with bind(grader._cfg):
        _remaining(deadline)
        drc_path = destination / 'drc.json'
        drc = run_drc(final, drc_path)
        _remaining(deadline)
        source = _read_occupancy(grader._original, grader._cfg)
        after = _read_occupancy(final, grader._cfg)
        # The finalized domain remains the exact emitted input's physical
        # footprint/pose/rule domain. New electrical routing is additive only.
        preservation = verify(source.geometry, grader._original, after.geometry, final,
                              critical['source_physical'])
        records = []
        for phase, obligations in zip(grader._phases, asks):
            _remaining(deadline)
            got = judge_obligations(final, obligations, drc_path, phase_neck(grader._cfg, phase), drc.is_real)
            if len(got) != len(obligations):
                _refuse('logical_final_asks_unmeasured', phase=phase.name)
            if any(o.get('width_policy_unknown') or j.get('width_unknown') for o, j in zip(obligations, got)):
                _refuse('logical_required_width_unknown', phase=phase.name, obligations=obligations, judged=got)
            joined = sum(is_clean(verdict, None) for verdict in got)
            records.append({'name': phase.name, 'asked': len(obligations), 'joined': joined,
                            'closure_clean': round(joined / len(obligations), 4) if obligations else 1.0,
                            'judged': got})
        checks = judge(critical, final)
        _remaining(deadline)
        drc_new = new_error_count(original_baseline, drc_path, drc.is_real)
        if drc_new is None:
            _refuse('logical_original_baseline_unmeasured')
        import json
        open_after = {net: count for net, count in drc.open_nets.items() if net not in original_counted}
        whole = _clean_whole(original_open, open_after, json.loads(drc_path.read_text()), drc.is_real, original_counted)
    artifacts = {str(path.absolute()): file_hash(path) for path in
                 (final, final.with_suffix('.kicad_pro'), drc_path)}
    custom = final.with_suffix('.kicad_dru')
    if custom.exists():
        artifacts[str(custom.absolute())] = file_hash(custom)
    return {'phases': records, 'drc_new': drc_new, 'closure_clean': round(whole.closure_clean, 4),
            'open_before': original_open, 'open_after': open_after,
            'critical': {'measures': checks.measures, 'evidence': checks.evidence()},
            'preservation': preservation, 'artifacts': artifacts}, after


def evaluate(request):
    """Independent owned check only; parent must validate custody and mint."""
    import json
    from .final_check_worker import _deadline, _runtime_identity
    from .pinmap_logical_packet import _hash, _json, verify_contract_record
    keys = {'schema', 'deadline_utc', 'original', 'candidate', 'logical', 'expected_readback', 'input_bundle',
            'critical_original', 'critical_candidate'}
    if type(request) is not dict or set(request) != keys or type(request['schema']) is not int or request['schema'] != 1:
        _refuse('logical_worker_request_malformed')
    _json(request)
    deadline = request['deadline_utc']
    if type(deadline) not in (int, float):
        _refuse('logical_worker_request_malformed')
    try:
        finite = math.isfinite(deadline)
    except OverflowError:
        finite = False
    if not finite:
        _refuse('logical_worker_request_malformed')
    _deadline(deadline)
    for side in ('original', 'candidate'):
        packet = request[side]
        context = request['critical_' + side]
        if (type(packet) is not dict or packet.get('deadline_utc') != deadline
                or type(context) is not dict or type(context.get('source_physical')) is not dict):
            _refuse('logical_worker_context_missing', side=side)
        quiet = context.get('quiet')
        if type(quiet) is not list or any(type(net) is not str for net in quiet) or len(set(quiet)) != len(quiet):
            _refuse('logical_worker_context_missing', side=side)
    intent = ('settings', 'rules', 'acceptances', 'edge_margin', 'component_spacing',
              'board_shape', 'board_cutouts', 'quiet', 'planes', 'pending', 'fields')
    for key in intent:
        original_context, candidate_context = request['critical_original'], request['critical_candidate']
        if (key not in original_context or key not in candidate_context
                or _json(original_context[key]) != _json(candidate_context[key])):
            _refuse('logical_original_check_intent_changed', field=key)
    if request['critical_original']['pending']:
        _refuse('logical_pending_domain_unsupported')
    implementation_start = _runtime_identity()
    from .kicad.final_worker_protocol import reconstruct
    from .settings import bind
    from .pinmap_written import _read_occupancy, _pads, _verify_readback_record
    from .final_preservation import verify_fixed
    original, original_raw, original_dest, _ = reconstruct(request['original'])
    candidate, candidate_raw, candidate_dest, _ = reconstruct(request['candidate'])
    from dataclasses import asdict
    original_settings, candidate_settings = asdict(original._cfg), asdict(candidate._cfg)
    original_settings.pop('sources', None)
    candidate_settings.pop('sources', None)
    if _json(original_settings) != _json(candidate_settings):
        _refuse('logical_settings_changed')
    a_invocation = original.binding()['contract']['invocation']
    b_invocation = candidate.binding()['contract']['invocation']
    for key in ('phases', 'upto', 'only', 'layers', 'exclude_nets', 'pour_nets', 'quick', 'router_dir', 'router_python'):
        if _json(a_invocation[key]) != _json(b_invocation[key]):
            _refuse('logical_original_invocation_changed', field=key)
    if a_invocation['capture']['sha256'] != b_invocation['capture']['sha256']:
        _refuse('logical_original_capture_changed')
    _input_bundle(request['input_bundle'], request)
    # Source-bound width receipt validation and original baseline measurement
    # occurred independently during both strict reconstructions above.
    with bind(original._cfg):
        source = _read_occupancy(original._original, original._cfg)
        original_scopes, original_requests = _scopes(original, source.geometry)
    with bind(candidate._cfg):
        written = _read_occupancy(candidate._original, candidate._cfg)
        _verify_readback_record(request['expected_readback'], written)
        _, candidate_requests = _scopes(candidate, written.geometry)
    pool_proof = _verify_pools(source.geometry, written.geometry, request['critical_original']['quiet'])
    verify_contract_record(request['logical'], _pads(source), _pads(written), original_scopes,
                           original_requests, json.loads(original._widths),
                           candidate_requests, json.loads(candidate._widths))
    original_asks = [[entry['original'] for entry in phase['asks']] for phase in request['logical']['phases']]
    candidate_asks = [[entry['candidate'] for entry in phase['asks']] for phase in request['logical']['phases']]
    baseline = original._worker_original_proof['measured_drc_path']
    a, original_final = _final_side(original, original_raw, original_dest, original_asks,
                                  request['critical_original'], baseline, original._open_before, original._counted, deadline)
    b, candidate_final = _final_side(candidate, candidate_raw, candidate_dest, candidate_asks,
                                   request['critical_candidate'], baseline, original._open_before, original._counted, deadline)
    fixed = verify_fixed(source.geometry, original._original, candidate_final.geometry,
                         candidate_dest / 'final.kicad_pcb')
    from .kicad.final_call import file_hash
    for side, grader in (('original', original), ('candidate', candidate)):
        grader._unchanged()
        artifact = request[side]['raw']
        if file_hash(artifact['path']) != artifact['sha256']:
            _refuse('logical_final_artifact_changed', side=side)
    _input_bundle(request['input_bundle'], request)
    _deadline(deadline)
    implementation_end = _runtime_identity()
    if implementation_start != implementation_end:
        _refuse('logical_worker_implementation_changed')
    return {'schema': 1, 'request_sha256': _hash(request), 'logical_sha256': _hash(request['logical']),
            'implementation_start': implementation_start, 'implementation_end': implementation_end,
            'original_verification': {'original': original._worker_original_proof,
                                      'candidate': candidate._worker_original_proof},
            'judgments': {'original': a, 'candidate': b}, 'fixed_preservation': fixed, 'pool_proof': pool_proof}


def main(argv=None):
    """One JSON request under the retained parent's owned-process deadline."""
    import argparse
    import json
    from pathlib import Path
    from .final_check_worker import _unique
    parser = argparse.ArgumentParser()
    parser.add_argument('request')
    parser.add_argument('response')
    args = parser.parse_args(argv)
    response = Path(args.response)
    if response.exists():
        _refuse('logical_worker_destination_exists')
    request = json.loads(Path(args.request).read_text(), object_pairs_hook=_unique,
                         parse_constant=lambda value: _refuse('logical_worker_request_malformed'))
    try:
        result = evaluate(request)
    except CandidateRefused as error:
        response.write_text(json.dumps({'schema': 1, 'refusal': error.record()},
                                      sort_keys=True, allow_nan=False) + '\n')
        return 1
    response.write_text(json.dumps(result, sort_keys=True, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
