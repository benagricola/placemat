"""Retain original Run intent and finish its bounded ordinary route choice.

Unsupported authority preserves ordinary routing. Optional continuation and
ordinary pocket selection share the original deadline and two proposal slots;
only verified finalized reports reach the caller. Refusals remain separate
from the original sealed route report and strict certification.
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from contextlib import ExitStack, contextmanager

from .route_execution_scope import ScopeUnavailable, budget, invocation


@dataclass(frozen=True)
class OrdinaryRouted:
    report: object
    factory: object | None
    unavailable: dict | None


@contextmanager
def run(board, plan, measures, source, work, route_board, **options):
    """Actual runner seam; authority retains this original Board/Plan once."""
    if '_authority_factory' in options:
        raise ValueError('ordinary route authority is executor-owned')
    try:
        from .final_authority import AuthorityRefused, retain
    except ModuleNotFoundError as error:
        if error.name != 'placemat.final_authority':
            raise
        yield OrdinaryRouted(route_board(source, work, **options), None,
                              {'code': 'final_authority_adapter_unavailable', 'facts': {}})
        return
    if options.get('quick'):
        yield OrdinaryRouted(route_board(source, work, **options), None,
                              {'code': 'final_authority_quick_unavailable', 'facts': {}})
        return
    # Preparation can refuse before routing. The ordinary call must then use
    # its original environment, rather than inherit an optional new budget.
    unavailable = None
    with ExitStack() as stack:
        try:
            deadline = stack.enter_context(budget(board.settings, ScopeUnavailable))
            scope = invocation(board, source, options.get('exclude_nets', ()),
                               options.get('pour_nets', ()), ScopeUnavailable)
            factory = retain(board, plan, measures, source,
                             invocation=scope, deadline_utc=deadline,
                             context_files=([scope['capture']['path']] if scope['capture']['path'] else ()))
        except OSError as error:
            unavailable = {'code': 'final_authority_input_unavailable', 'facts': {'detail': str(error)}}
        except (AuthorityRefused, ScopeUnavailable) as error:
            unavailable = {'code': error.code, 'facts': dict(error.facts)}
        else:
            report = route_board(source, work, _authority_factory=factory, **options)
            from .kicad.final_call import ProofUnavailable
            from .kicad import replay_finish as caller_finish
            try:
                report,publication=caller_finish.finish(factory,report,Path(work)/'ordinary-route-finish')
                if publication is not None:
                    report=publication.verify()
            except (ProofUnavailable,AuthorityRefused) as error:
                # Known optional proof refusal preserves completed ordinary report.
                unavailable={'code':error.code,'facts':dict(error.facts)}
            yield OrdinaryRouted(report, factory, unavailable)
            return
    yield OrdinaryRouted(route_board(source, work, **options), None, unavailable)
