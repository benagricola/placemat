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

def make(args, argv, nets, layers, environment, route_file, tasks, effective_clearances,
         requested_clearances=None):
    if environment.get('KRT_INTERNAL_ROUTE_CANDIDATE') != '1':
        return None
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
    for key in ('connections', 'net_clearances'):
        value = getattr(args, key, None)
        if value:
            path = Path(value).resolve()
            files[str(path)] = digest(path)
    transport = {key: environment.get(key) for key in (
        'KRT_INTERNAL_ROUTE_CANDIDATE', 'KRT_INTERNAL_POCKET_WALLS',
        'KRT_ROUTE_DEADLINE_UTC', 'KRT_ROUTE_BUDGET_S',
        'KRT_INTERNAL_FINAL_CALL_CONTEXT', 'KRT_INTERNAL_FINAL_CALL_KIND',
        'KRT_INTERNAL_FINAL_CALL_PROOF', 'KRT_INTERNAL_FINAL_CALL_ID')}
    value = {'schema': 1, 'policy': 'nested-board-candidates-disabled', 'board_proposals': 1,
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
                                str(Path(native_path).resolve()): digest(native_path)}}
    # Snapshot nested actual parsed structures, preserving scalar JSON types.
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))

def verify_unchanged(receipt):
    if receipt is None:
        return
    if time.time() >= receipt['deadline_utc']:
        raise ReceiptUnavailable('original absolute deadline expired')
    for path, expected in dict(receipt['input_files'], **receipt['implementation']).items():
        actual = digest(path) if Path(path).is_file() else None
        if actual != expected:
            raise ReceiptUnavailable('legacy-only execution input or implementation changed')
