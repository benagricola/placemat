"""Live paired routing for an explicitly requested pin finalist comparison.

The returned diagnostic cannot authorize publication. Physical source selection
remains separate; executable pin-map publication is deliberately withheld.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import time
from contextlib import contextmanager

from .pinmap_common import CandidateRefused


class PairedUnavailable(CandidateRefused):
    """Retain an ordinary completed source route when its proposal refuses."""
    def __init__(self, error, source):
        super().__init__(error.code, str(error), **error.facts)
        self.source = source


def compare_live(incumbent, live, diagnostic, *, phase_priority=None):
    """Retain ties/non-improvements; unavailable prior evidence is explicit."""
    if not diagnostic['improving_proposal']:
        return incumbent
    if incumbent is None:
        return live
    known_refusals = _known_refusals()
    try:
        order = live.compare_candidate(incumbent, phase_priority=phase_priority)
    except CandidateRefused as error:
        diagnostic['cross_seed_refusal'] = error.record()
        return incumbent
    except known_refusals as error:
        diagnostic['cross_seed_refusal'] = {'code': error.code, 'facts': dict(error.facts)}
        return incumbent
    diagnostic['cross_seed_candidate_rank'] = order
    return live if order < 0 else incumbent


def _deadline(cfg):
    deadline = time.time() + cfg.timeout_route
    inherited = os.environ.get('KRT_ROUTE_DEADLINE_UTC')
    if inherited is not None:
        try:
            value = float(inherited)
        except (ValueError, OverflowError) as error:
            raise CandidateRefused('logical_deadline_malformed', 'inherited route deadline is invalid') from error
        if not math.isfinite(value):
            raise CandidateRefused('logical_deadline_malformed', 'inherited route deadline is invalid')
        deadline = min(deadline, value)
    if not math.isfinite(deadline) or deadline <= time.time():
        raise CandidateRefused('logical_deadline_expired', 'original route deadline has expired')
    return deadline


@contextmanager
def budget(cfg):
    """One source/candidate/check budget, restoring the worker environment."""
    old = os.environ.get('KRT_ROUTE_DEADLINE_UTC')
    deadline = _deadline(cfg)
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


def _invocation(board, pcb, excluded, pours):
    """Reconstruct configured scope without a second width query/native read."""
    from .kicad import route
    try:
        from .capture_nets import SIDECAR, capture_beside
        from .route_phase import phases_of
        configured_router = route.configured_router
    except (ImportError, AttributeError) as error:
        raise CandidateRefused('logical_execution_unavailable',
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


def _remaining(deadline):
    if time.time() >= deadline:
        raise CandidateRefused('logical_deadline_expired', 'shared routing/check deadline expired')


def _known_refusals():
    try:
        from .kicad.route import RouteRefused, RouterFailed
        from .kicad.final_call import ProofUnavailable
    except ImportError:
        return ()
    return RouteRefused, ProofUnavailable, RouterFailed


def paired(router, board, plan, pcb, folder, proposal, *, excluded, pours, resume, deadline):
    """Return raw source route and detached checked comparison diagnostics.

    All authorities and proofs remain local and alive through comparison. The
    queue never receives a mintable capability or altered physical contracts.
    """
    from . import final_authority, pinmap_logical, pinmap_written, score
    diagnostic, inp, picked, finalist = proposal
    if not diagnostic['actionable'] or finalist.refusals:
        raise CandidateRefused('logical_finalist_unavailable', 'no measured simultaneous pin finalist is available')
    pcb, folder = Path(pcb).resolve(), Path(folder).resolve()
    if deadline != float(os.environ.get('KRT_ROUTE_DEADLINE_UTC', 'nan')) or deadline <= time.time():
        raise CandidateRefused('logical_deadline_unavailable', 'paired route requires its retained shared budget')
    excluded, pours = _scope_nets(board, excluded, pours)
    invocation = _invocation(board, pcb, excluded, pours)
    _remaining(deadline)
    capture = invocation['capture']['path']
    context_files = (Path(capture),) if capture is not None else ()
    physical = pinmap_written.mint(board, plan, inp, picked, pcb, context_files=context_files)
    _remaining(deadline)
    logical = pinmap_logical.mint(board, plan, physical)
    folder.mkdir(parents=True, exist_ok=True)
    candidate_pcb, _ = pinmap_written.write_proved(board, plan, physical, folder / 'candidate-input')
    _remaining(deadline)
    candidate_context = tuple(candidate_pcb.parent / path.name for path in context_files)
    source_factory = final_authority.retain(board, plan, score.plan_measures(board, plan), pcb,
        invocation=invocation, deadline_utc=deadline, context_files=context_files)
    candidate_factory = final_authority.retain(finalist.board, finalist.plan, finalist.measures, candidate_pcb,
        invocation=_invocation(finalist.board, candidate_pcb, excluded, pours), deadline_utc=deadline,
        context_files=candidate_context)
    source = router.route(pcb, folder / 'route', exclude_nets=excluded, quick=False, resume=resume,
                          _authority_factory=source_factory, capture_path=capture, pour_nets=pours)
    return _after_source(source, lambda: _finish(router, source, candidate_pcb, folder, excluded, resume,
                                               source_factory, candidate_factory, logical, deadline, pours=pours))


def _after_source(source, operation):
    """Known refusals retain source; unexpected defects remain exceptions."""
    known_refusals = _known_refusals()
    try:
        return operation()
    except CandidateRefused as error:
        raise PairedUnavailable(error, source) from error
    except known_refusals as error:
        facts = dict(error.facts)
        if hasattr(error, 'exit_code'):
            facts.update(exit_code=error.exit_code, log=str(error.log), tail=error.tail)
        refusal = CandidateRefused(error.code, str(error), **facts)
        raise PairedUnavailable(refusal, source) from error
    except OSError as error:
        refusal = CandidateRefused('logical_candidate_artifact_unavailable', str(error))
        raise PairedUnavailable(refusal, source) from error
    except Exception as error:
        # Unexpected defects still propagate. The worker can retain the
        # completed ordinary source artifact as diagnostic evidence.
        error.completed_source_route = source
        raise


def _finish(router, source, candidate_pcb, folder, excluded, resume,
            source_factory, candidate_factory, logical, deadline, *, pours=()):
    from . import pinmap_logical_compare
    _remaining(deadline)
    candidate = router.route(candidate_pcb, folder / 'candidate-route', exclude_nets=excluded,
                             quick=False, resume=resume, _authority_factory=candidate_factory,
                             capture_path=candidate_factory._invocation['capture']['path'], pour_nets=pours)
    _remaining(deadline)
    source_authority = source_factory.completed_authority()
    candidate_authority = candidate_factory.completed_authority()
    source_grade = source_authority.regrade(source.routed_pcb, folder / 'source-grade')
    _remaining(deadline)
    candidate_grade = candidate_authority.regrade(candidate.routed_pcb, folder / 'candidate-grade')
    _remaining(deadline)
    comparison = pinmap_logical_compare.evaluate(logical, source_authority, source_grade,
        candidate_authority, candidate_grade, folder / 'logical-check')
    outcome = comparison.rank()
    _remaining(deadline)
    comparison.verify()
    return source, {'scope': 'full_configured_shared_deadline', 'deadline_utc': deadline,
                    'source_report': source.as_dict(), 'candidate_report': candidate.as_dict(),
                    'comparison': comparison.diagnostic(), 'candidate_rank': outcome,
                    'improving_proposal': outcome < 0,
                    'adoption_refusal': {'code': 'logical_mapping_publication_unsupported', 'facts': {}}}, comparison
