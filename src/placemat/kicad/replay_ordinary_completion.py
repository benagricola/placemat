"""One shared budget's actual ordinary completion, separate from replay proof.

Draft actual callback adapter. No alternative counter or reopened attempt exists.
"""
from pathlib import Path
from copy import deepcopy
from placemat.kicad import issued_calls
from placemat.kicad.final_call import ProofUnavailable, record_digest
from . import replay_backend as backend

_METADATA_REFUSALS = frozenset({
    'replay_backend_policy_malformed', 'replay_backend_policy_mismatch',
    'replay_backend_input_mismatch', 'replay_backend_requested_clearances_mismatch',
    'replay_backend_effective_clearances_malformed', 'replay_backend_effective_clearances_changed',
    'replay_backend_tasks_mismatch', 'replay_backend_tasks_unexpected',
})


def run_completed(budget, token, ctx, log, complete_call):
    """Consume slot zero around existing actual raw/restore token hooks.

    Returned metadata eligibility is private executor state, not a certificate.
    The actual call count uses the same ReplayBudget as every later proposal.
    """
    eligibility = {'policy_proved':False, 'refusal':None}
    def operation(deadline):
        attempted = False
        actual = None
        strict = None
        def run(command, actual_log, actual_ctx):
            nonlocal attempted, actual, strict
            if attempted or list(command)!=token.record['command'] or Path(actual_log)!=Path(log) or actual_ctx is not ctx:
                raise ProofUnavailable('replay_owned_call_changed')
            attempted=True
            def capture(value):
                nonlocal actual
                if actual is not None:
                    raise ProofUnavailable('replay_owned_completion_repeated')
                actual=deepcopy(value)
            def validate():
                budget._check(budget.executor)
                issued_calls._token(budget.grader,budget.ledger,budget.executor,token)
            try:
                strict=backend._run_record(token.record,deadline,ctx,log,validate,actual_completed=capture)
            except ProofUnavailable as error:
                if error.code not in _METADATA_REFUSALS or actual is None:
                    raise
                eligibility['refusal']=error.record()
            else:
                eligibility['policy_proved']=True
            if actual is None or actual['returncode']!=0:
                raise ProofUnavailable('replay_owned_ordinary_completion_unavailable')
            return actual['returncode']
        complete_call(run)
        if actual is None:
            raise ProofUnavailable('replay_owned_ordinary_completion_unavailable')
        completed=issued_calls.completed_record(budget.grader,budget.ledger,budget.executor,token)
        for source,expected in actual['files'].items():
            matches=[value for path,value in completed['raw']['files'].items()
                     if Path(path).name.split('-',1)[-1]==Path(source).name]
            if matches!=[expected]:
                raise ProofUnavailable('replay_owned_raw_changed')
        if record_digest(actual['command'])!=record_digest(token.record['command']) or actual['deadline_utc']!=budget.deadline:
            raise ProofUnavailable('replay_owned_call_changed')
        files=dict(completed['raw']['files'])
        files.update({path:value for path,value in completed['completed']['restored_files'].items() if value is not None})
        # This is the one actual owned legacy-only request accounted here.
        # It is not the absent optional policy receipt or replay eligibility.
        return {'returncode':0,'files':files,'proposals':1}
    receipt=budget.run_incumbent(budget.executor,operation)
    return receipt,deepcopy(eligibility)
