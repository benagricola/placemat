"""Executor-owned two-proposal accounting, without adoption authority.

The optional executor reserves this before issuing its incumbent. A continuation
callback owns its actual launch and artifacts; this module never spawns a second
launcher, changes a deadline, or interprets execution policy as a Standing.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time

from ..stop import Stopped
from . import final_custody as custody, issued_calls
from .final_call import ProofUnavailable, file_hash, record_digest

_MINT = object()


class ReplayBudget(custody._Opaque):
    __slots__ = ('grader', 'ledger', 'executor', 'deadline', 'prior', 'states',
                 'incumbent_files', 'completion_sha', 'results')

    def __new__(cls, key, *args):
        if key is not _MINT:
            raise ProofUnavailable('private_replay_executor_required')
        return super().__new__(cls)

    def __init__(self, key, grader, ledger, executor, prior):
        self.grader, self.ledger, self.executor = grader, ledger, executor
        self.deadline = ledger.owner.deadline_utc
        self.prior = prior
        self.states = ['unused', 'unused']
        self.incumbent_files = self.completion_sha = None
        self.results = [None, None]

    def _check(self, executor):
        if executor is not self.executor or self.ledger.replay_budget is not self:
            raise ProofUnavailable('replay_executor_mismatch')
        issued_calls._owner(self.grader, self.ledger, executor, writing=False)
        if self.deadline != self.ledger.owner.deadline_utc:
            raise ProofUnavailable('replay_deadline_changed')
        if time.time() >= self.deadline:
            raise ProofUnavailable('replay_deadline_expired')
        for token, expected in self.prior:
            actual = issued_calls.completed_record(self.grader, self.ledger, executor, token)
            if record_digest(actual) != expected:
                raise ProofUnavailable('replay_prior_call_changed')
        if self.incumbent_files is not None:
            for path, expected in self.incumbent_files.items():
                if file_hash(path) != expected:
                    raise ProofUnavailable('replay_incumbent_changed', path=path)

    def run_incumbent(self, executor, launch):
        """Call the actual owning launch once, with the original absolute deadline."""
        self._check(executor)
        if self.states[0] != 'unused':
            raise ProofUnavailable('replay_incumbent_already_issued')
        return self._run(0, launch)

    def seal_incumbent(self, executor):
        """Require the same executor's completed ordinary report and artifacts."""
        self._check(executor)
        if self.states[0] != 'completed' or self.completion_sha is not None:
            raise ProofUnavailable('replay_incumbent_not_sealable')
        completed = custody.require_completed(self.grader)
        self.incumbent_files = deepcopy(completed['completed']['output_files'])
        self.completion_sha = record_digest(completed)

    def run_replay(self, executor, continue_candidate):
        """One fixed continuation; it cannot create another board proposal.

        The callback receives only an execution deadline. It must use the existing
        owned runner for every search, finalization and verification operation.
        Its return is execution evidence, never permission to adopt or publish.
        """
        self._check(executor)
        if self.completion_sha is None or self.states[0] != 'completed':
            raise ProofUnavailable('replay_completed_incumbent_required')
        if record_digest(custody.require_completed(self.grader)) != self.completion_sha:
            raise ProofUnavailable('replay_completed_context_changed')
        if self.states[1] != 'unused':
            raise ProofUnavailable('replay_candidate_already_issued')
        return self._run(1, continue_candidate)

    def _run(self, slot, operation):
        # Consume before launch. Exceptions and cancellation cannot reopen a slot.
        self.states[slot] = 'issued'
        try:
            result = operation(self.deadline)
            self._check(self.executor)
            if time.time() >= self.deadline:
                raise ProofUnavailable('replay_deadline_expired')
            if (not isinstance(result, dict) or set(result) != {'returncode', 'files', 'proposals'}
                    or type(result['returncode']) is not int
                    or type(result['proposals']) is not int or result['proposals'] != 1
                    or not isinstance(result['files'], dict) or not result['files']):
                raise ProofUnavailable('replay_execution_receipt_malformed')
            for path, expected in result['files'].items():
                if (not isinstance(path, str) or not Path(path).is_absolute()
                        or not isinstance(expected, str) or file_hash(path) != expected):
                    raise ProofUnavailable('replay_execution_artifact_changed')
            if result['returncode'] != 0:
                raise ProofUnavailable('replay_execution_incomplete', returncode=result['returncode'])
            self.results[slot] = deepcopy(result)
            self.states[slot] = 'completed'
            return deepcopy(result)
        except BaseException as error:
            self.states[slot] = ('cancelled' if isinstance(error, (Stopped, KeyboardInterrupt, SystemExit))
                                 else 'failed')
            raise


def _executor_reserve(grader, ledger, executor):
    """Private issuance-site hook; no public JSON request can mint this ledger.

    Final-call scope and removal inventory are validated by the continuation
    adapter before this hook is reached. Reservation alone grants neither scope
    nor full-board authority. The ordinary path does not call this hook.
    """
    issued_calls._owner(grader, ledger, executor)
    if ledger.replay_budget is not None:
        raise ProofUnavailable('replay_budget_already_reserved')
    prior = [(token, record_digest(issued_calls.completed_record(grader, ledger, executor, token)))
             for token in ledger.issued]
    budget = ReplayBudget(_MINT, grader, ledger, executor, prior)
    ledger.replay_budget = budget
    return budget
