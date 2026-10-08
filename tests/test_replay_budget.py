"""Two-proposal execution accounting uses the real private custody registry."""
from copy import deepcopy

import pytest

from placemat.kicad import final_custody as custody, replay_budget
from placemat.kicad.final_call import ProofUnavailable, file_hash
from tests.test_final_custody import context, prepared


@pytest.fixture
def budget(context):
    grader, facts, report, executor, ledger, path, outputs = prepared(context)
    return (replay_budget._executor_reserve(grader, ledger, executor), executor,
            grader, ledger, report, path, outputs)


def result(files):
    return {'returncode': 0, 'proposals': 1, 'files': deepcopy(files)}


def complete(budget):
    value, executor, grader, ledger, report, path, outputs = budget
    seen = []
    value.run_incumbent(executor, lambda deadline: seen.append(deadline) or result(outputs))
    custody._executor_seal_completed(grader, ledger, executor, report,
                                    report_json=path, outputs=outputs)
    value.seal_incumbent(executor)
    return seen


def test_one_incumbent_one_continuation_same_deadline_and_no_third(budget):
    value, executor, *_ = budget
    deadlines = complete(budget)
    value.run_replay(executor, lambda deadline: deadlines.append(deadline) or result(budget[-1]))
    assert deadlines == [value.deadline, value.deadline]
    assert value.states == ['completed', 'completed']
    with pytest.raises(ProofUnavailable, match='already_issued'):
        value.run_replay(executor, lambda _: pytest.fail('third proposal'))
    with pytest.raises(ProofUnavailable, match='already_issued'):
        value.run_incumbent(executor, lambda _: pytest.fail('second incumbent'))


def test_no_public_or_cross_executor_reservation(budget):
    value, executor, grader, ledger, *_ = budget
    with pytest.raises(ProofUnavailable, match='private'):
        replay_budget.ReplayBudget(object(), grader, ledger, executor, [])
    with pytest.raises(ProofUnavailable, match='already_reserved'):
        replay_budget._executor_reserve(grader, ledger, executor)
    with pytest.raises(ProofUnavailable, match='executor_mismatch'):
        value.run_incumbent(object(), lambda _: pytest.fail('wrong owner launched'))
    with pytest.raises(custody.CustodyUnavailable):
        deepcopy(value)


def test_replay_requires_actual_complete_ordinary_report(budget):
    value, executor, *_ = budget
    value.run_incumbent(executor, lambda _: result(budget[-1]))
    with pytest.raises(custody.CustodyUnavailable, match='completion_unavailable'):
        value.seal_incumbent(executor)
    with pytest.raises(ProofUnavailable, match='completed_incumbent'):
        value.run_replay(executor, lambda _: pytest.fail('unsealed launched'))
    assert value.states[1] == 'unused'


@pytest.mark.parametrize('alter', ['nested', 'bool', 'returncode', 'stale'])
def test_failed_execution_consumes_slot(budget, alter):
    value, executor, *_ = budget
    receipt = result(budget[-1])
    if alter == 'nested':
        receipt['proposals'] = 2
    elif alter == 'bool':
        receipt['proposals'] = True
    elif alter == 'returncode':
        receipt['returncode'] = 1
    else:
        receipt['files'][str(budget[-2])] = '0' * 64
    with pytest.raises(ProofUnavailable):
        value.run_incumbent(executor, lambda _: receipt)
    assert value.states == ['failed', 'unused']
    with pytest.raises(ProofUnavailable, match='already_issued'):
        value.run_incumbent(executor, lambda _: pytest.fail('retry launched'))


def test_cancellation_propagates_and_never_reopens_slot(budget):
    value, executor, *_ = budget
    def cancel(deadline):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        value.run_incumbent(executor, cancel)
    assert value.states == ['cancelled', 'unused']


def test_mutated_incumbent_blocks_replay_without_launch(budget):
    value, executor, *_ = budget
    complete(budget)
    before = budget[-2].read_bytes()
    budget[-2].write_bytes(before + b' ')
    with pytest.raises(ProofUnavailable, match='incumbent_changed'):
        value.run_replay(executor, lambda _: pytest.fail('stale incumbent launched'))
    assert value.states[1] == 'unused'


def test_expired_original_deadline_prevents_launch(budget, monkeypatch):
    value, executor, *_ = budget
    monkeypatch.setattr(replay_budget.time, 'time', lambda: value.deadline + 1)
    with pytest.raises(ProofUnavailable, match='deadline_expired'):
        value.run_incumbent(executor, lambda _: pytest.fail('expired launched'))
    assert value.states == ['unused', 'unused']


def test_changed_deadline_cannot_enlarge_callback_budget(budget):
    value, executor, *_ = budget
    value.deadline += 30
    with pytest.raises(ProofUnavailable, match='deadline_changed'):
        value.run_incumbent(executor, lambda _: pytest.fail('enlarged deadline launched'))
    assert value.states == ['unused', 'unused']


@pytest.mark.parametrize('target', ['source', 'incumbent'])
def test_callback_mutation_cannot_complete_replay(budget, target):
    value, executor, grader, *_ = budget
    complete(budget)
    def mutate(deadline):
        path = grader._original if target == 'source' else budget[-2]
        path.write_text('changed by continuation')
        return result({str(path): file_hash(path)})
    with pytest.raises(ProofUnavailable):
        value.run_replay(executor, mutate)
    assert value.states == ['completed', 'failed']
    assert value.results[1] is None
