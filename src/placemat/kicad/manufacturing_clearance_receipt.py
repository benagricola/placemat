"""Validate fresh owned floor measurements; transport cannot authorize adoption."""
import hashlib
import json
import time
from pathlib import Path

from .manufacturing_annular import Unproved, digest
from .manufacturing_clearance_report import partition
from .manufacturing_failure_count import failure_count
from .manufacturing_factory_floor import captured_floor
from .manufacturing_floor_project import iu, stricter
from .manufacturing_net_map import resolve
from .manufacturing_drc_report import validate as validate_drc
from .manufacturing_copper_domain import raw_domain, raw_layer_domain
from .manufacturing_inventory import raw_layers
from .manufacturing_clearance_worker import raw_fills
from placemat.kicad.board_forms import protected_forms
from placemat.final_preservation import configured_intent
from placemat.kicad.board_forms import read_forms


def bound_report(record, cli, board, report_path, refill, save, check):
    check()
    if type(record) is not dict or type(record.get('returncode')) is not int or record['returncode'] != 0:
        raise Unproved('clearance_report_execution')
    expected = [cli, 'pcb', 'drc', '--format', 'json', '--units', 'mm',
                '--all-track-errors', '--severity-all']
    if refill:
        expected.append('--refill-zones')
    if save:
        expected.append('--save-board')
    argv = record['argv']
    if type(argv) is not list or argv[:-3] != expected or argv[-3] != '--output' or argv[-1] != str(board):
        raise Unproved('clearance_report_command')
    path = Path(argv[-2])
    if path != report_path or path.is_symlink() or path.resolve() != report_path:
        raise Unproved('clearance_report_path')
    raw = path.read_bytes()
    report_sha = hashlib.sha256(raw).hexdigest()
    if report_sha != record['report_sha256'] or digest(json.loads(raw)) != digest(record['full_report']):
        raise Unproved('clearance_report_changed')
    artifacts = record['artifacts']
    expected_paths = {str(path), str(path.with_suffix('.stdout')), str(path.with_suffix('.stderr'))}
    if (type(artifacts) is not dict or set(artifacts) != expected_paths
            or artifacts.get(str(path)) != report_sha):
        raise Unproved('clearance_report_artifacts')
    for source, expected_sha in artifacts.items():
        check()
        if hashlib.sha256(Path(source).read_bytes()).hexdigest() != expected_sha:
            raise Unproved('clearance_report_changed')
    report = json.loads(raw)
    if digest(validate_drc(report, board)) != digest(record['schema']):
        raise Unproved('clearance_report_schema')
    check()
    return report


def validate(packet, receipt, check):
    """Recompute each stratum from exact report bytes and preserved item domain."""
    try:
        return _validate(packet, receipt, check)
    except Unproved:
        raise
    except (OSError, KeyError, TypeError, ValueError, AttributeError, UnicodeError) as error:
        raise Unproved('clearance_receipt_malformed') from error


def _validate(packet, receipt, check):
    check()
    context = packet['context']
    def deadline_only():
        if time.time() >= packet['request']['deadline_utc']:
            raise Unproved('deadline')
    if (context['mode'] != 'retained_current_measurement'
            or receipt.get('mode') != context['mode']
            or receipt.get('comparison_authority') is not False
            or type(receipt.get('schema')) is not int or receipt['schema'] != 1
            or receipt.get('request_sha256') != digest(packet)
            or set(receipt['rows']) != {'original', 'candidate'}):
        raise Unproved('clearance_receipt_binding')
    capsule = context['capsule']
    factory = captured_floor(Path(capsule['path']).read_bytes(), capsule['sha256'])
    original = context['source_original']
    proof = resolve(original['.kicad_pcb']['path'], context['effective_clearances'], context['krt_parser'])
    floors = {net: iu(value) for net, value in proof['semantic_map'].items()}
    global_floor = factory['factory_global_floor_iu']
    levels = sorted({global_floor, *(max(global_floor, value) for value in floors.values())})
    original_project = Path(original['.kicad_pro']['path']).read_bytes()
    work = Path(context['drc_work']).with_name('native-clearance')
    if not work.is_absolute() or work.resolve() != work or work.is_symlink():
        raise Unproved('clearance_work_path')
    result = {}
    sealed_artifacts = {}
    for side, label in (('original', 'legacy'), ('candidate', 'pocket')):
        check()
        row = receipt['rows'][side]
        if (row.get('mode') != context['mode'] or row.get('comparison_authority') is not False
                or row.get('cli_no_refill') is not True
                or digest(row['factory_floor_provenance']) != digest(factory)
                or digest(row['semantic_map_proof']) != digest(proof)):
            raise Unproved('clearance_original_scope')
        # The owned producer copies raw source and verifies full non-fill
        # preservation before exposing this saved original-rule-filled board.
        first = row['original_report']
        board = Path(first['argv'][-1])
        expected_board = work / side / 'board.kicad_pcb'
        if board != expected_board or board.resolve() != expected_board or board.is_symlink():
            raise Unproved('clearance_board_path')
        if hashlib.sha256(board.read_bytes()).hexdigest() != row['saved_filled_sha256']:
            raise Unproved('clearance_filled_board_changed')
        if digest(raw_fills(board)) != row['raw_fill_sha256']:
            raise Unproved('clearance_fills_changed')
        source = Path(packet['request'][side]['files']['.kicad_pcb']['path'])
        # Native held geometry and complete non-fill manifest are compared in
        # the pinned owned worker. Parent verification repeats the existing
        # pure configured-pad and literal copper/zone protections; it never
        # imports pcbnew or performs an unbounded native read here.
        source = Path(packet['request'][side]['files']['.kicad_pcb']['path'])
        def refuse(reason):
            raise Unproved(reason)
        if (protected_forms(source, refuse) != protected_forms(board, refuse)
                or configured_intent(source) != configured_intent(board)):
            raise Unproved('clearance_nonfill_changed')
        raw = raw_domain(board, read_forms, deadline_only)
        items = row['native_item_domain']
        reduced = [{key: item[key] for key in ('uuid', 'kind', 'net')} for item in items]
        if digest(raw) != digest(reduced):
            raise Unproved('clearance_native_domain_changed')
        layer_domain = raw_layer_domain(board, read_forms, raw_layers(board), deadline_only)
        if layer_domain != {item['uuid']: item['layers'] for item in items}:
            raise Unproved('clearance_native_layers_changed')
        passes = row['distinct_floor_passes']
        if type(passes) is not list or [p['requested_floor_iu'] for p in passes] != levels:
            raise Unproved('clearance_floor_schedule')
        cli = context['drc_cli']['path']
        original_report = bound_report(first, cli, board, board.with_name('original.json'),
                                       True, True, deadline_only)
        sealed_artifacts.update(first['artifacts'])
        allowed_ignored = {'missing_courtyard', 'track_not_centered_on_via',
                           'tuning_profile_track_geometries', 'footprint_filters_mismatch',
                           'footprint_type_mismatch'}
        if (original_report['included_severities'] != ['error', 'warning', 'exclusion']
                or any(v['key'] not in allowed_ignored for v in original_report['ignored_checks'])
                or any(v['severity'] == 'exclusion' for v in original_report['violations'])):
            raise Unproved('clearance_original_constraint_domain')
        recomputed = []
        violations = []
        for level, measured in zip(levels, passes):
            check()
            selected = {name: value for name, value in proof['semantic_map'].items()
                        if max(global_floor, iu(value)) == level}
            if not selected:
                selected = {'__captured_factory_global_floor__': level / 1000000}
            derivative, delta = stricter(original_project, selected)
            if digest(delta) != digest(measured['project_delta']) or measured['actual_global_floor_iu'] != delta['floor_iu']:
                raise Unproved('clearance_project_delta')
            report = bound_report(measured['floor_report'], cli, board,
                                  board.with_name('floor-' + str(level) + '.json'),
                                  False, False, deadline_only)
            sealed_artifacts.update(measured['floor_report']['artifacts'])
            part = partition(report, items, floors, measured_floor_iu=level, check_current=deadline_only,
                             factory_global_floor_iu=global_floor)
            recomputed.append(part)
            violations.extend(part['mapped_violations'])
        if board.with_suffix('.kicad_pro').read_bytes() != derivative:
            raise Unproved('clearance_final_project_changed')
        rule = original['.kicad_dru']
        copied_rule = board.with_suffix('.kicad_dru')
        if rule is None:
            if copied_rule.exists() or copied_rule.is_symlink():
                raise Unproved('clearance_rules_absence_changed')
        elif hashlib.sha256(copied_rule.read_bytes()).hexdigest() != rule['sha256']:
            raise Unproved('clearance_rules_changed')
        recorded = row['mandatory_partition']
        if (digest(recorded['passes']) != digest(recomputed)
                or digest(recorded['mapped_violations']) != digest(violations)
                or recorded['mapped_floor_legal'] is not (not violations)):
            raise Unproved('clearance_partition_changed')
        result[label] = {'complete': True, 'legal': not violations,
                         'violations': violations,
                         'original_errors': sum(v['severity'] == 'error' for v in original_report['violations']),
                         'failure_count': failure_count(original_report['violations'], violations)}
    for source, expected in sealed_artifacts.items():
        deadline_only()
        if hashlib.sha256(Path(source).read_bytes()).hexdigest() != expected:
            raise Unproved('clearance_report_changed')
    check()
    return result
