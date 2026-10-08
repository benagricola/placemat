"""Actual executor call ledger for a gated final ordinary-call proposal.

The retained complete-board authority is supplied by the integrated executor.
This transport helper cannot mint it, adopt copper, or infer router policy.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .final_call import (CallScope, CopperWork, NominalPolicy, ProofUnavailable,
                         RequiredJoin, Terminal, file_hash, issued_flags, proof_of, write_proof)

_KINDS = {'nets': 'single', 'rest': 'single', 'pairs': 'pairs', 'pour': 'pour',
          'tasks': 'connections', 'bus_tasks': 'connections', 'bus': 'bus'}


def _supports_final_call(caps):
    if not isinstance(caps, dict) or type(caps.get('schema')) is not int or caps['schema'] != 1:
        return False
    modules, flags = caps.get('modules'), caps.get('flags')
    if not isinstance(modules, dict) or not isinstance(flags, dict):
        return False
    route_flags = flags.get('route.py')
    return (modules.get('route.py') is True and isinstance(route_flags, list)
            and all(isinstance(flag, str) for flag in route_flags)
            and {'--final-call-proof', '--candidate-artifacts'}.issubset(route_flags))


class CandidatePlanner:
    def __init__(self, *, authority, phases, obligations, width_receipt, receipt_path,
                 complete, capabilities=None, pair_owned_nets=()):
        self._authority = authority
        self._phases = tuple(deepcopy(phases))
        self._obligations = json.dumps(obligations, sort_keys=True, allow_nan=False)
        self._width_receipt = json.dumps(width_receipt, sort_keys=True, allow_nan=False)
        self._receipt_path = Path(receipt_path)
        self._complete = complete
        try:
            self._capabilities = json.loads(json.dumps(capabilities, allow_nan=False))
        except (TypeError, ValueError):
            self._capabilities = None
        self._pair_owned = frozenset(pair_owned_nets)
        self._work = []
        self._unproved_work = []
        self.requests = []
        self.refusals = []

    def note(self, call_id, kind):
        """Record actual issued pipeline work; unsupported custody prevents activation."""
        translated = _KINDS.get(kind)
        if translated is None:
            self._unproved_work.append(call_id)
            return
        self._work.append(CopperWork(call_id, translated))
        # Pair/pour/bus/task pipelines have internal calls and outcome custody
        # this first planner cannot enumerate authoritatively. Withhold rather
        # than pretend those pipelines are one proved ordinary invocation.
        if kind not in ('nets', 'rest'):
            self._unproved_work.append(call_id)

    def _executor_bind_prior(self, grader, ledger, executor, *, phase, call):
        """Replace declaration-only prior work with validated actual receipts."""
        from . import replay_inventory
        if self._work or self._unproved_work or self.requests:
            raise ProofUnavailable('candidate_prior_work_already_bound')
        proof, records = replay_inventory._executor_prior_work(
            grader, ledger, executor, phase=phase, call=call)
        work = []
        for record in records:
            identity = record['identity']
            call_id = 'p%d-c%d-w%d' % (identity['phase'], identity['call'], identity['wave'])
            work.append(CopperWork(call_id, identity['kind']))
        self._work = work
        self._prior_custody = (grader, ledger, executor, phase, call, proof)

    def _verify_prior(self):
        prior = getattr(self, '_prior_custody', None)
        if prior is None:
            return
        from . import replay_inventory
        grader, ledger, executor, phase, call, expected = prior
        actual, _ = replay_inventory._executor_prior_work(
            grader, ledger, executor, phase=phase, call=call)
        from .final_call import record_digest
        if record_digest(actual) != record_digest(expected):
            raise ProofUnavailable('candidate_prior_work_changed')

    def resumed(self, name):
        self._unproved_work.append('resumed:' + name)

    def prepare(self, *, phase_index, call_index, calls, call_id, board, output,
                summary, command, launch, nets, layers, deadline_utc, now=None,
                original_fabrication=None):
        """Bind the literal actual final issued call, preserving ordinary argv on refusal."""
        try:
            self._verify_prior()
            if not _supports_final_call(self._capabilities):
                raise ProofUnavailable('final_call_capability_unavailable')
            if self._complete is not True:
                raise ProofUnavailable('partial_route')
            observations = json.loads(self._obligations)
            if not isinstance(observations, list) or len(observations) != len(self._phases):
                raise ProofUnavailable('original_contract_count_mismatch')
            if phase_index != len(self._phases) - 1 or call_index != len(calls) - 1:
                raise ProofUnavailable('later_copper_work')
            if self._unproved_work:
                raise ProofUnavailable('completed_work_custody_unproved', calls=list(self._unproved_work))
            if not self._work or self._work[-1].id != call_id:
                raise ProofUnavailable('unissued_final_call')
            if self.requests:
                raise ProofUnavailable('candidate_request_already_issued')
            named = tuple(sorted(nets))
            widths = json.loads(self._width_receipt)
            policies = [record for record in widths['policies'] if record['name'] == self._phases[phase_index].name]
            if len(policies) != 1:
                raise ProofUnavailable('policy_scope_mismatch')
            joins = []
            for obligation in observations[phase_index]:
                if obligation['net'] not in named:
                    continue
                start, end = obligation['from'], obligation['to']
                required = policies[0]['by_net'][obligation['net']]
                if required['status'] != 'known' or obligation.get('width_policy_unknown'):
                    raise ProofUnavailable('policy_unproved')
                requested_widths = obligation.get('widths')
                if requested_widths is None:
                    requested_widths = required['widths']
                joins.append(RequiredJoin(obligation['net'], Terminal(start['ref'], start['pad']),
                                          Terminal(end['ref'], end['pad']), tuple(requested_widths.items())))
            scope = CallScope(call_id, 'single', issued_flags(command, launch, board, output, summary),
                              named, tuple(layers), pair_owned_nets=tuple(sorted(self._pair_owned)),
                              obligations=tuple(joins))
            policy = NominalPolicy.from_validated_receipt(self._receipt_path, widths,
                                                          self._phases[phase_index].name, scope)
            proof = proof_of(board, scope, policy, self._work, self._authority,
                             deadline_utc=deadline_utc, complete_route=True, now=now)
            if original_fabrication is not None:
                proof['original_fabrication'] = deepcopy(original_fabrication)
            request = Path(summary).with_name(call_id + '_final_call.json')
            artifacts = Path(summary).with_name(call_id + '_candidates')
            if artifacts.exists():
                raise ProofUnavailable('candidate_artifacts_exist')
            write_proof(request, proof)
            self.requests.append({'call_id': call_id, 'proof': str(request), 'proof_sha256': file_hash(request),
                                  'artifacts': str(artifacts), 'summary': str(summary)})
            return list(command) + ['--final-call-proof', str(request), '--candidate-artifacts', str(artifacts)]
        except (ProofUnavailable, OSError, KeyError, TypeError, ValueError) as error:
            record = error.record() if isinstance(error, ProofUnavailable) else {
                'code': 'candidate_proof_unavailable', 'facts': {'error': type(error).__name__}}
            self.refusals.append(dict(record, call_id=call_id))
            return list(command)
