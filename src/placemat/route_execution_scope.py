"""Configured ordinary/paired route scope and one inherited absolute budget."""
from contextlib import contextmanager
import hashlib
import math
import os
from pathlib import Path
import time

class ScopeUnavailable(ValueError):
    def __init__(self, code, message, **facts):
        self.code, self.facts = code, facts
        super().__init__(message)

def absolute_deadline(cfg, refuse=ScopeUnavailable):
    deadline = time.time() + cfg.timeout_route
    inherited = os.environ.get('KRT_ROUTE_DEADLINE_UTC')
    if inherited is not None:
        try:
            value = float(inherited)
        except (ValueError, OverflowError) as error:
            raise refuse('logical_deadline_malformed', 'inherited route deadline is invalid') from error
        if not math.isfinite(value):
            raise refuse('logical_deadline_malformed', 'inherited route deadline is invalid')
        deadline = min(deadline, value)
    if not math.isfinite(deadline) or deadline <= time.time():
        raise refuse('logical_deadline_expired', 'original route deadline has expired')
    return deadline


@contextmanager
def budget(cfg, refuse=ScopeUnavailable):
    """One source/candidate/check budget, restoring the worker environment."""
    old = os.environ.get('KRT_ROUTE_DEADLINE_UTC')
    deadline = absolute_deadline(cfg, refuse)
    os.environ['KRT_ROUTE_DEADLINE_UTC'] = str(deadline)
    try:
        yield deadline
    finally:
        if old is None:
            os.environ.pop('KRT_ROUTE_DEADLINE_UTC', None)
        else:
            os.environ['KRT_ROUTE_DEADLINE_UTC'] = old


def _scope_nets(board, excluded, pours):
    return set(excluded), set(pours) & set(board.geometry.nets)


def invocation(board, pcb, excluded, pours, refuse=ScopeUnavailable):
    """Reconstruct configured scope without a second width query/native read."""
    from .kicad import route
    try:
        from .capture_nets import SIDECAR, capture_beside
        from .route_phase import phases_of
        configured_router = route.configured_router
    except (ImportError, AttributeError) as error:
        raise refuse('logical_execution_unavailable',
                               'reviewed full routing execution API is unavailable') from error
    cfg = board.settings
    excluded, pours = _scope_nets(board, excluded, pours)
    selected, origin = configured_router(cfg)
    router_dir = Path(route.checked_router(selected, origin)).resolve()
    geometry = board.geometry
    layers, _ = route.resolved_layers(None, [layer.value for layer in geometry.layers],
                                    {layer.value: kind for layer, kind in geometry.layer_types.items()})
    capture_path = pcb.with_name(SIDECAR)
    capture = capture_beside(pcb)
    capture_record = {'path': str(capture_path), 'sha256': _hash(capture_path)} if capture else {
        'path': None, 'sha256': None}
    return {'phases': [phase.key() for phase in phases_of(cfg)], 'upto': None, 'only': False,
            'layers': list(layers), 'exclude_nets': sorted(excluded), 'pour_nets': sorted(pours),
            'quick': False, 'capture': capture_record, 'router_dir': str(router_dir),
            'router_python': str(router_dir / '.venv' / 'bin' / 'python'),
            'width_query_input': {'path': str(pcb), 'sha256': _hash(pcb)}}


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


