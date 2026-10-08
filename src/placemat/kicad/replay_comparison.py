"""Final continuation comparison against one actual completed original context."""
import json
from placemat.kicad.final_call import ProofUnavailable, record_digest
from placemat.kicad import final_custody


def fixed_reports(authority, grader, incumbent, candidate):
    """Verify both minted candidates before reading original fixed asks."""
    if authority._grader is not grader:
        raise ProofUnavailable('replay_original_authority_mismatch')
    final_custody.require_completed(grader)
    authority.verify(incumbent)
    authority.verify(candidate)
    original = json.loads(grader._obligations)
    reports = [incumbent.physical.report, candidate.physical.report]
    for report in reports:
        if (record_digest(report.asked) != record_digest(original)
                or len(report.final_judged) != len(original)
                or len(grader._phases) != len(original)):
            raise ProofUnavailable('replay_original_obligations_changed')
        for asks, judged in zip(original, report.final_judged):
            if len(asks) != len(judged) or any(
                    not isinstance(value, dict) or type(value.get('joined')) is not bool
                    for value in judged):
                raise ProofUnavailable('replay_final_judgment_unproved')
    return original, reports


def preserve_current(authority, grader, incumbent, candidate):
    """Retain every incumbent current connection before the shared rank."""
    original, reports = fixed_reports(authority, grader, incumbent, candidate)
    old, new = reports
    losses = []
    for index, (phase, asks) in enumerate(zip(grader._phases, original)):
        current_phase = phase.selector == 'current_paths' or phase.width == 'current'
        for item, obligation in enumerate(asks):
            if not current_phase and obligation.get('amps') is None:
                continue
            if old.final_judged[index][item]['joined'] and not new.final_judged[index][item]['joined']:
                losses.append({'phase': index, 'obligation': item, 'ask': obligation})
    if losses:
        raise ProofUnavailable('replay_incumbent_current_join_lost', losses=losses)
    return True


def compare_original(authority, grader, incumbent, candidate):
    preserve_current(authority,grader,incumbent,candidate)
    # Required-width unknowns, manufacturing and critical comparability remain
    # the retained authority's strict boundary. Connectivity alone cannot adopt.
    return authority.compare(incumbent, candidate)
