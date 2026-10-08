"""CLI legacy-only execution metadata; never candidate adoption authority."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import sys
import time

class ReceiptUnavailable(ValueError):
    pass

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _observed(args, argv, nets, layers, environment, route_file, tasks, effective_clearances,
              requested_clearances=None, parser=None, write_request=True):
    if any(getattr(args, key, False) for key in ('preview', 'skip_routing', 'schematic_dir')):
        raise ReceiptUnavailable('unsupported legacy-only execution domain')
    try:
        deadline = float(environment['KRT_ROUTE_DEADLINE_UTC'])
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ReceiptUnavailable('original absolute deadline unavailable') from error
    if not math.isfinite(deadline) or deadline <= time.time():
        raise ReceiptUnavailable('original absolute deadline expired')
    if (not isinstance(argv, (list, tuple)) or any(not isinstance(v, str) for v in argv)
            or not isinstance(nets, (list, tuple)) or not nets
            or any(not isinstance(v, str) or not v for v in nets)
            or not isinstance(layers, (list, tuple)) or not layers
            or any(not isinstance(v, str) or not v for v in layers)
            or len(set(nets)) != len(nets) or len(set(layers)) != len(layers)):
        raise ReceiptUnavailable('actual parsed scope unavailable')
    native = sys.modules.get('grid_router')
    native_path = getattr(native, '__file__', None)
    if not isinstance(native_path, str) or not native_path.endswith('.so'):
        raise ReceiptUnavailable('actual loaded router native unavailable')
    board = Path(args.input_file).resolve()
    files = {str(board): digest(board)}
    for suffix in ('.kicad_pro', '.kicad_dru'):
        path = board.with_suffix(suffix)
        files[str(path)] = digest(path) if path.is_file() else None
    for key in ('connections', 'net_clearances', 'fab_overrides'):
        value = getattr(args, key, None)
        if value:
            path = Path(value).resolve()
            files[str(path)] = digest(path)
    transport = {key: environment.get(key) for key in (
        'KRT_INTERNAL_ROUTE_CANDIDATE', 'KRT_INTERNAL_POCKET_WALLS',
        'KRT_ROUTE_DEADLINE_UTC', 'KRT_ROUTE_BUDGET_S',
        'KRT_INTERNAL_FINAL_CALL_CONTEXT', 'KRT_INTERNAL_FINAL_CALL_KIND',
        'KRT_INTERNAL_FINAL_CALL_PROOF', 'KRT_INTERNAL_FINAL_CALL_ID')}
    if parser is None:
        raise ReceiptUnavailable('actual invocation parser unavailable')
    from route_candidates import manufacturing_envelope, ordinary_grade_request, explicit_fields
    envelope = manufacturing_envelope(args, board, {})
    ordinary_request = ordinary_grade_request(
        args, explicit_fields(argv, parser), board,
        Path(args.output_file).resolve(), None, list(nets),
        Path(args.connections).resolve() if getattr(args, 'connections', None) else None, envelope)
    value = {'schema': 2,
             'ordinary_grade_request': ordinary_request,
             'argv': list(argv), 'input_files': files,
             'output': str(Path(args.output_file).resolve()),
             'summary': str(Path(args.json_out).resolve()) if args.json_out else None,
             'nets': list(nets), 'layers': list(layers), 'deadline_utc': deadline,
             'transport': transport, 'actual_tasks': tasks,
             'effective_clearances': effective_clearances,
             'requested_clearances': requested_clearances,
             'implementation': {str(Path(route_file).resolve()): digest(route_file),
                                str(Path(__file__).resolve()): digest(__file__),
                                str(Path(sys.executable).resolve()): digest(sys.executable),
                                str(Path(native_path).resolve()): digest(native_path),
                                str(Path(sys.modules['route_candidates'].__file__).resolve()):
                                    digest(sys.modules['route_candidates'].__file__)}}
    # Snapshot nested actual parsed structures, preserving scalar JSON types.
    value = json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    request_path = environment.get('KRT_INTERNAL_ORDINARY_GRADE_REQUEST')
    if request_path is not None and write_request:
        if not isinstance(request_path, str) or not Path(request_path).is_absolute():
            raise ReceiptUnavailable('owned ordinary grade request path unavailable')
        # Written at the actual post-resolve seam, before any search. The parent
        # binds this independent artifact to its owned command and input bytes.
        try:
            with Path(request_path).open('x', encoding='utf-8') as sink:
                json.dump(value, sink, sort_keys=True, allow_nan=False)
                sink.write('\n')
        except OSError as error:
            raise ReceiptUnavailable('owned ordinary grade request unavailable') from error
    return value

def make(args, argv, nets, layers, environment, route_file, tasks, effective_clearances,
         requested_clearances=None, parser=None, observation=None):
    if environment.get('KRT_INTERNAL_ROUTE_CANDIDATE') != '1':
        return None
    value = _observed(args, argv, nets, layers, environment, route_file, tasks,
                      effective_clearances, requested_clearances, parser,
                      write_request=observation is None)
    if observation is not None:
        if not isinstance(observation, dict) or observation.get('observation') != 'parent-post-floor-scope':
            raise ReceiptUnavailable('actual prelaunch observation unavailable')
        previous = dict(observation)
        previous.pop('observation')
        try:
            expected = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
            if json.dumps(previous, sort_keys=True, separators=(',', ':'), allow_nan=False) != expected:
                raise ReceiptUnavailable('actual prelaunch observation changed')
            request_path = environment.get('KRT_INTERNAL_ORDINARY_GRADE_REQUEST')
            if request_path is not None:
                capsule = json.loads(Path(request_path).read_bytes())
                if json.dumps(capsule, sort_keys=True, separators=(',', ':'), allow_nan=False) != expected:
                    raise ReceiptUnavailable('owned ordinary grade request changed')
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as error:
            raise ReceiptUnavailable('owned ordinary grade request unavailable') from error
    value.update(policy='nested-board-candidates-disabled', board_proposals=1)
    return value


def observe_scope(args, argv, nets, layers, environment, route_file, tasks, effective_clearances,
                  requested_clearances=None, parser=None):
    """Actual post-floor parent scope, without any candidate-count claim."""
    value = _observed(args, argv, nets, layers, environment, route_file, tasks,
                      effective_clearances, requested_clearances, parser)
    value['observation'] = 'parent-post-floor-scope'
    return value


def publish_scope(receipt, returncode):
    """Append actual parent observation only after its successful return."""
    if receipt is None or type(returncode) is not int or returncode != 0:
        return
    verify_unchanged(receipt)
    if (not isinstance(receipt.get('output'), str) or not receipt['output']
            or not isinstance(receipt.get('summary'), str) or not receipt['summary']):
        raise ReceiptUnavailable('completed parent artifact paths unavailable')
    output = Path(receipt['output'])
    summary = Path(receipt['summary'])
    if not output.is_file() or not summary.is_file():
        raise ReceiptUnavailable('completed parent artifacts unavailable')
    data = json.loads(summary.read_bytes())
    if not isinstance(data, dict):
        raise ReceiptUnavailable('completed parent summary malformed')
    captured = dict(receipt, actual_output_sha256=digest(output))
    data['resolved_scope'] = captured
    summary.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def verify_unchanged(receipt):
    if receipt is None:
        return
    if time.time() >= receipt['deadline_utc']:
        raise ReceiptUnavailable('original absolute deadline expired')
    for path, expected in dict(receipt['input_files'], **receipt['implementation']).items():
        actual = digest(path) if Path(path).is_file() else None
        if actual != expected:
            raise ReceiptUnavailable('legacy-only execution input or implementation changed')
