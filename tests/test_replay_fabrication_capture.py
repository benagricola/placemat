"""Actual retained fixture and observer hook, controlled router/native factory."""
import pytest
from tests.test_final_custody import context
from tests.nominal_lifecycle import completed_hook
from placemat.kicad import final_custody
from placemat.kicad.final_call import file_hash


def test_actual_prior_issue_and_completed_hook_binds_original_capture(context,monkeypatch):
    hook,_=completed_hook(context,monkeypatch)
    original=final_custody.require_completed(hook.grader)['original']
    proof=hook.nominal_observation['proof']
    record=proof['original_fabrication']
    assert record['path']==str(hook.grader._original.resolve())
    assert record['sha256']==original['read_manifest'][record['path']]==file_hash(record['path'])
    assert record['custody_sha256']==original['private_context_sha256']
    assert proof['deadline_utc']==hook.deadline
    assert hook.replay_budget.states==['completed','unused']
    # Both earlier and final actual issued contexts remain bound; no third slot.
    assert len(hook.ledger.issued)==2


def test_actual_retained_custody_refuses_original_change_after_capture(context,monkeypatch):
    hook,_=completed_hook(context,monkeypatch)
    hook.grader._original.write_bytes(hook.grader._original.read_bytes()+b'changed original after capture')
    with pytest.raises(final_custody.CustodyUnavailable):
        final_custody.require_completed(hook.grader)
