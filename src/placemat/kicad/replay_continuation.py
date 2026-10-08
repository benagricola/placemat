"""One budget-private continuation of exact completed original call vectors.

No candidate token is inserted into the sealed original custody registry. These
are execution artifacts; the retained original authority alone grades/adopts.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import time

from placemat.kicad import issued_calls, replay_inventory
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad import pour_identity
from . import replay_restoration as restore_owned
from . import replay_backend as backend


def _candidate_record(original, ctx, source, output, summary):
    command = list(original['command'])
    _, _, argv = backend._runtime(ctx, command)
    prefix = len(command) - len(argv)
    if (len(argv) < 2 or Path(argv[0]).resolve() != Path(original['input'])
            or Path(argv[1]).resolve() != Path(original['output'])
            or command[-2:] != ['--json-out', original['summary']]):
        raise ProofUnavailable('replay_owned_transport_unproved')
    command[prefix:prefix + 2] = [str(source), str(output)]
    command[-1] = str(summary)
    old_paths = {str(Path(original[key]).resolve()) for key in ('source', 'input')}
    old_paths |= {str(Path(original[key]).with_suffix(ext).resolve())
                  for key in ('source', 'input') for ext in ('.kicad_pro', '.kicad_dru')}
    files = {path: value for path, value in original['actual_input_files'].items()
             if path not in old_paths}
    files.update(issued_calls._files(source))
    record = deepcopy({key: value for key, value in original.items()
                       if key not in ('raw', 'completed', 'input_snapshots')})
    record.update(command=command, source=str(source), input=str(source), output=str(output),
                  summary=str(summary), actual_input_files=files,
                  execution_transport={key: ctx.env.get(key) for key in issued_calls._TRANSPORT})
    return record


def run_calls(budget, contexts, final_call, cohort_call, wall_input, work):
    """Called only inside the consumed second proposal's owning closure.

    The enclosing coordinator itself creates wall_input from select_cohort's
    exact inventory. Each source context comes from the original issuance site.
    """
    if budget.states != ['completed', 'issued'] or budget.completion_sha is None:
        raise ProofUnavailable('replay_consumed_candidate_slot_required')
    budget._check(budget.executor)
    replay_inventory.supported_completed_work(budget.grader, budget.ledger, budget.executor)
    final = issued_calls.completed_record(budget.grader, budget.ledger, budget.executor, final_call)
    cohort = issued_calls.completed_record(budget.grader, budget.ledger, budget.executor, cohort_call)
    if final_call is not budget.ledger.issued[-1] or final['identity']['kind'] != 'single':
        raise ProofUnavailable('replay_final_call_unproved')
    key = (cohort['identity']['phase'], cohort['identity']['call'])
    prior = [token for token in budget.ledger.issued if
             (token.record['identity']['phase'], token.record['identity']['call']) == key]
    if final_call in prior or cohort_call not in prior:
        raise ProofUnavailable('replay_prior_cohort_unproved')
    tokens = [final_call, *prior]
    closed = [(token, issued_calls.completed_record(budget.grader, budget.ledger, budget.executor, token))
              for token in tokens]
    expected = [(token, record_digest(record)) for token, record in closed]
    if any(token not in contexts for token, _ in closed):
        raise ProofUnavailable('replay_original_execution_context_missing')
    work = Path(work).resolve()
    work.mkdir()
    current = Path(wall_input).resolve()
    wall_sha = file_hash(current)
    files, calls = {}, []

    def original_unchanged():
        budget._check(budget.executor)
        for token, digest in expected:
            record = issued_calls.completed_record(budget.grader, budget.ledger, budget.executor, token)
            if record_digest(record) != digest:
                raise ProofUnavailable('replay_original_call_changed')
        if file_hash(wall_input) != wall_sha:
            raise ProofUnavailable('replay_wall_input_changed')

    for index, (token, original) in enumerate(closed):
        original_unchanged()
        ctx = contexts[token]
        effective = backend._original_effective(original, ctx, final=token is final_call)
        if original['identity']['kind'] == 'pour' and (
                not isinstance(original.get('pour_transform'), dict)
                or original['pour_transform'].get('domain') != 'single_net_pour_identity_normalization'):
            raise ProofUnavailable('replay_pour_transform_unproved')
        given = work / ('c%d-input.kicad_pcb' % index)
        output = work / ('c%d-output.kicad_pcb' % index)
        summary = work / ('c%d-summary.json' % index)
        env = dict(ctx.env, KRT_INTERNAL_ROUTE_CANDIDATE='1',
                   KRT_ROUTE_DEADLINE_UTC=str(budget.deadline),
                   KRT_INTERNAL_ORDINARY_GRADE_REQUEST=str(work/('c%d-ordinary-grade-request.json' % index)))
        candidate_ctx = replace(ctx, env=env, execution=None)
        lifecycle = work / ('c%d-lifecycle' % index)
        lifecycle.mkdir()
        files.update(restore_owned.run(budget, original, candidate_ctx, 'prepare', current, given, output, lifecycle))
        for ext in ('.kicad_pro', '.kicad_dru'):
            actual = given.with_suffix(ext)
            expected = original['actual_input_files'].get(str(Path(original['input']).with_suffix(ext)))
            if (file_hash(actual) if actual.is_file() else None) != expected:
                raise ProofUnavailable('replay_original_companions_changed')
        transform = (pour_identity.normalized(current, given) if original['identity']['kind'] == 'pour' else None)
        record = _candidate_record(original, candidate_ctx, given, output, summary)
        result = backend._run_record(record, budget.deadline, candidate_ctx,
                                     work / ('c%d.log' % index), original_unchanged,
                                     effective_clearances=effective)
        raw_files = issued_calls._files(output)
        raw_files[str(summary)] = file_hash(summary)
        snapshots = issued_calls._snapshot(raw_files, work / ('c%d-raw' % index))
        files.update(restore_owned.run(budget, original, candidate_ctx, 'restore', current, given, output, lifecycle))
        if transform is not None:
            pour_identity.restored(current, output, transform)
        original_unchanged()
        if time.time() >= budget.deadline:
            raise ProofUnavailable('replay_deadline_expired')
        files.update(snapshots)
        files.update({path: value for path, value in issued_calls._files(output).items() if value is not None})
        calls.append({'original_issued_call_sha256': record_digest(original),
                      'actual_vector': record, 'raw_files': snapshots,
                      'restored_files': issued_calls._files(output),
                      'proposal_count': result['proposals']})
        current = output
    ledger_path = work / 'continuation.json'
    ledger_path.write_text(json.dumps({'schema': 1, 'deadline_utc': budget.deadline,
                                     'execution_only': True, 'calls': calls}, indent=2, allow_nan=False) + '\n')
    files[str(ledger_path)] = file_hash(ledger_path)
    return current, files
