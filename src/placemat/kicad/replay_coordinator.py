"""Budget-private complete continuation using the retained original authority.

This draft remains uncalled until the actual preissue executor seam is reviewed.
"""
from pathlib import Path
from collections import Counter
import json
import shutil
from placemat.kicad import board_forms, issued_calls, replay_hits
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from .replay_comparison import compare_original
from . import replay_continuation as candidate_calls


def publish_if_better(budget, authority, incumbent, candidate, destination):
    budget._check(budget.executor)
    if authority._grader is not budget.grader:
        raise ProofUnavailable('replay_original_authority_mismatch')
    # Fresh per-obligation check is immediately adjacent to publication. Never
    # expose a refused candidate to the aggregate-only publication method.
    if not compare_original(authority, budget.grader, incumbent, candidate):
        return None
    return authority.publish(incumbent, candidate, destination)


def _without_walls(source, selected, output):
    def refuse(reason):
        raise ProofUnavailable('replay_wall_input_unproved', reason=reason)
    root = board_forms.read_forms(source, refuse)
    def frozen(node):
        return tuple(frozen(item) if isinstance(item, list) else item for item in node)
    remaining = Counter(selected)
    kept = []
    for node in root:
        key = frozen(node) if isinstance(node, list) else None
        if key is not None and remaining[key]:
            remaining[key] -= 1
        else:
            kept.append(node)
    if any(remaining.values()):
        raise ProofUnavailable('replay_wall_inventory_changed')
    def wire(value):
        return '(' + ' '.join(wire(item) for item in value) + ')' if isinstance(value, list) else value
    output.write_text(wire(kept)+'\n')
    for ext in ('.kicad_pro', '.kicad_dru'):
        companion = Path(source).with_suffix(ext)
        if companion.is_file():
            shutil.copyfile(companion, output.with_suffix(ext))


def continue_original(budget, factory, owner, final_call, work, destination):
    """Exactly one complete replay; original sealed ledger remains immutable."""
    budget._check(budget.executor)
    if factory._route_execution is not owner or owner.replay_budget is not budget:
        raise ProofUnavailable("replay_original_execution_owner_mismatch")
    contexts = owner.contexts_for(budget)
    authority = factory.completed_authority()
    if authority._grader is not budget.grader:
        raise ProofUnavailable('replay_original_authority_mismatch')
    if budget.states != ['completed', 'unused'] or budget.completion_sha is None:
        raise ProofUnavailable('replay_completed_incumbent_required')
    work = Path(work).resolve()
    work.mkdir()
    original = budget.grader._template.routed_pcb
    incumbent = authority.regrade(original, work/'incumbent-grade')
    budget._check(budget.executor)
    report = incumbent.physical.report
    asks = json.loads(budget.grader._obligations)
    if record_digest(report.asked) != record_digest(asks) or len(report.final_judged) != len(asks):
        raise ProofUnavailable('replay_original_obligations_changed')
    phase_index = len(asks)-1
    if len(report.final_judged[phase_index]) != len(asks[phase_index]):
        raise ProofUnavailable('replay_final_judgment_unproved')
    failed = set()
    for ask, result in zip(asks[phase_index], report.final_judged[phase_index]):
        if type(result.get('joined')) is not bool or not isinstance(ask.get('net'), str):
            raise ProofUnavailable('replay_final_judgment_unproved')
        if not result['joined']:
            failed.add(ask['net'])
    cohort, selected, attribution = replay_hits.select_cohort(
        budget.grader, budget.ledger, budget.executor, final_call, failed)
    final = issued_calls.completed_record(budget.grader, budget.ledger, budget.executor, final_call)
    wall_input = work/'wall-input.kicad_pcb'
    _without_walls(Path(final['input']), selected, wall_input)
    candidate = None
    def continuation(deadline):
        nonlocal candidate
        if deadline != budget.deadline:
            raise ProofUnavailable('replay_deadline_changed')
        board, files = candidate_calls.run_calls(budget, owner.contexts_for(budget), final_call, cohort, wall_input, work/'calls')
        candidate = authority.regrade(board, work/'candidate-grade')
        authority.verify(incumbent)
        authority.verify(candidate)
        # Verify full authority before consuming completion; final publication
        # repeats the individual-current guard on these exact minted objects.
        compare_original(authority, budget.grader, incumbent, candidate)
        evidence = Path(candidate.evidence)
        files[str(evidence)] = file_hash(evidence)
        return {'returncode':0, 'proposals':1, 'files':files}
    budget.run_replay(budget.executor, continuation)
    published = publish_if_better(budget, authority, incumbent, candidate, destination)
    return {'published':published, 'incumbent':incumbent, 'candidate':candidate,
            'attribution':attribution}
