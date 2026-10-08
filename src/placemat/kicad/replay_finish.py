"""Finish the actual ordinary runner's private route owner under its deadline."""
from pathlib import Path
from placemat.kicad.final_call import ProofUnavailable,record_digest
from placemat.kicad import issued_calls
from .replay_ordinary_trigger import permits_second_slot
from . import replay_coordinator as coordinator
from . import replay_pocket as sole_pocket
from .replay_ordinary_publication import publish_selected

_NO_COHORT={
    'replay_static_evidence_unavailable', 'replay_static_evidence_malformed',
    'replay_generated_cohort_unavailable', 'replay_hit_board_unproved',
}


def finish(factory,report,work):
    owner=getattr(factory,'_route_execution',None)
    if owner is None or not owner.active or owner.replay_budget is None:
        return report,None
    budget=owner.replay_budget
    if owner.factory is not factory:
        raise ProofUnavailable('replay_original_execution_owner_mismatch')
    owner.contexts_for(budget)
    authority=factory.completed_authority()
    if authority._grader is not budget.grader:
        raise ProofUnavailable('replay_original_authority_mismatch')
    if record_digest(owner.backend_capability)!=owner.backend_capability_sha:
        raise ProofUnavailable('replay_execution_capability_changed')
    original=issued_calls.completed_record(budget.grader,budget.ledger,budget.executor,owner.final_call)
    ctx=owner.contexts_for(budget)[owner.final_call]
    helper=(Path(ctx.router_dir)/ctx.script).resolve().with_name('route_candidates.py')
    if not permits_second_slot(helper,original['raw']['summary'],owner.backend_capability['sources'][str(helper)]):
        return report,None
    work=Path(work).resolve()
    if work.exists():raise ProofUnavailable('replay_fresh_finish_required')
    work.mkdir()
    # A completed original owner can use either route for slot one, never both.
    if owner.backend_eligibility['policy_proved']:
        try:
            result=coordinator.continue_original(budget,factory,owner,owner.final_call,
                                                 work/'cohort',work/'cohort-published')
        except ProofUnavailable as error:
            if budget.states[1]!='unused' or error.code not in _NO_COHORT:
                raise
        else:
            if result['published'] is not None:
                from .replay_publication import detached
                packet=detached(authority,result['candidate'],result['published'])
                return packet.verify(),packet
            return report,None
    from . import replay_nominal
    nominal=replay_nominal.eligible(budget,owner,owner.final_call,work/'nominal-eligibility')
    if nominal is None:
        output,receipt,evidence=sole_pocket.run(budget,owner,owner.final_call,work/'pocket')
    else:
        output,receipt,evidence=sole_pocket.run(budget,owner,owner.final_call,work/'escape',nominal=nominal)
    selection=evidence.get('selection',{})
    if output is None or selection.get('selected') not in ('pocket','escape'):return report,None
    # Fresh final physical/critical checks still run even when strict Standing
    # is unknown; original ordinary selection is recorded as such, not adoption.
    incumbent=authority.regrade(report.routed_pcb,work/'ordinary-incumbent')
    candidate=authority.regrade(output,work/'ordinary-pocket')
    packet=publish_selected(budget,authority,incumbent,candidate,
                            work/'ordinary-published',selection)
    return packet.verify(),packet
