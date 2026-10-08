"""One actual owned router call; execution receipts never authorize adoption."""
import hashlib
from pathlib import Path
import json
import math
import time

from placemat import route_progress
from placemat.kicad import issued_calls
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad.final_owned_worker import _execute

_UNSET = object()


def _runtime(ctx, command):
    root = Path(ctx.router_dir).resolve()
    hook = Path(issued_calls.__file__).with_name('route_hooked.py').resolve()
    if len(command) < 3:
        raise ProofUnavailable('replay_router_command_mismatch')
    wrapped = Path(command[1]).resolve() == hook
    if len(command) < (4 if wrapped else 3):
        raise ProofUnavailable('replay_router_command_mismatch')
    script = Path(command[2] if wrapped else command[1])
    script = (root / script).resolve() if not script.is_absolute() else script.resolve()
    if script != (root / ctx.script).resolve() or Path(command[0]).resolve() != Path(ctx.rpy).resolve():
        raise ProofUnavailable('replay_router_command_mismatch')
    native = (root / 'rust_router' / 'grid_router.so').resolve()
    helper = script.with_name('route_execution_receipt.py').resolve()
    required = [Path(ctx.rpy).resolve(), script, helper, native,
                script.with_name('route_candidates.py').resolve()]
    if any(not path.is_file() for path in required):
        raise ProofUnavailable('replay_execution_policy_unavailable')
    # Bind the actual source families used by routing and width/quality tools.
    paths = set(required)
    if wrapped:
        paths.update((hook, hook.with_name('route_events.py')))
    for family in ('py_router', 'py_tools'):
        paths.update((root / family).rglob('*.py'))
    paths.update(root.glob('*.py'))
    return ({str(path.resolve()): file_hash(path) for path in sorted(paths)}, required,
            command[3:] if wrapped else command[2:])


def _policy(summary, record, env, implementation, requested_clearances, *,
            effective_clearances=_UNSET, parser_argv=None):
    try:
        record_digest(summary)
    except (TypeError, ValueError) as error:
        raise ProofUnavailable('replay_backend_policy_malformed') from error
    fields = {'schema', 'policy', 'board_proposals', 'argv', 'input_files', 'output', 'summary',
              'nets', 'layers', 'deadline_utc', 'transport', 'actual_tasks',
              'effective_clearances', 'requested_clearances', 'implementation', 'ordinary_grade_request'}
    policy = summary.get('execution_policy')
    if (not isinstance(policy, dict) or set(policy) != fields
            or type(policy['schema']) is not int or policy['schema'] != 2
            or type(policy['board_proposals']) is not int or policy['board_proposals'] != 1
            or policy['policy'] != 'nested-board-candidates-disabled'):
        raise ProofUnavailable('replay_backend_policy_malformed')
    return _resolved_fields(policy, record, env, implementation, requested_clearances,
                            effective_clearances=effective_clearances, parser_argv=parser_argv)


def _resolved_fields(policy, record, env, implementation, requested_clearances, *,
                     effective_clearances=_UNSET, parser_argv=None):
    expected_transport = {key: env.get(key) for key in issued_calls._TRANSPORT}
    if (record_digest(policy['transport']) != record_digest(expected_transport)
            or record_digest(policy['argv']) != record_digest(
                record['command'][2:] if parser_argv is None else parser_argv)
            or policy['output'] != record['output'] or policy['summary'] != record['summary']
            or record_digest(policy['nets']) != record_digest(record['nets'])
            or record_digest(policy['layers']) != record_digest(record['layers'])
            or type(policy['deadline_utc']) not in (int, float)
            or not math.isfinite(policy['deadline_utc'])
            or policy['deadline_utc'] != record['deadline_utc']
            or record_digest(policy['implementation']) != record_digest(implementation)):
        raise ProofUnavailable('replay_backend_policy_mismatch')
    inputs = policy['input_files']
    source = Path(record['source'])
    source_paths = {str(source.resolve()), *(str(source.with_suffix(ext).resolve())
                                            for ext in ('.kicad_pro', '.kicad_dru'))}
    board = Path(record['input'])
    backend_paths = {str(board.resolve()), *(str(board.with_suffix(ext).resolve())
                                             for ext in ('.kicad_pro', '.kicad_dru'))}
    backend_paths.update(set(record['actual_input_files']) - source_paths)
    expected_inputs = {path: record['actual_input_files'][path] for path in backend_paths}
    if not isinstance(inputs, dict) or record_digest(inputs) != record_digest(expected_inputs):
        raise ProofUnavailable('replay_backend_input_mismatch')
    if record_digest(policy['requested_clearances']) != record_digest(requested_clearances):
        raise ProofUnavailable('replay_backend_requested_clearances_mismatch')
    resolved = policy['effective_clearances']
    if resolved is not None and (not isinstance(resolved, dict) or any(
            not isinstance(key, str) or not key.isdigit()
            or type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for key, value in resolved.items())):
        raise ProofUnavailable('replay_backend_effective_clearances_malformed')
    if effective_clearances is not _UNSET and record_digest(resolved) != record_digest(effective_clearances):
        raise ProofUnavailable('replay_backend_effective_clearances_changed')
    if record['identity']['kind'] == 'connections':
        actual = policy['actual_tasks']
        if not isinstance(actual, list) or [issued_calls._task(task) for task in actual] != record['tasks']:
            raise ProofUnavailable('replay_backend_tasks_mismatch')
    elif policy['actual_tasks'] is not None:
        raise ProofUnavailable('replay_backend_tasks_unexpected')
    _ordinary_request(policy, record)
    return policy


def _ordinary_request(policy, record):
    request = policy['ordinary_grade_request']
    fields = {'board', 'input', 'summary', 'scope', 'manufacturing_defaults',
              'explicit_width', 'connections', 'power_nets', 'power_nets_widths',
              'impedance', 'clearance_unproved', 'electrical_unproved', 'via_size', 'via_drill'}
    if (not isinstance(request, dict) or set(request) != fields
            or request['board'] != record['output'] or request['input'] != record['input']
            or request['summary'] is not None
            or record_digest(request['scope']) != record_digest(record['nets'])
            or type(request['clearance_unproved']) is not bool
            or type(request['electrical_unproved']) is not bool):
        raise ProofUnavailable('replay_ordinary_grade_request_malformed')
    for key in ('explicit_width', 'via_size', 'via_drill'):
        value = request[key]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ProofUnavailable('replay_ordinary_grade_request_malformed')
    envelope = request['manufacturing_defaults']
    if (not isinstance(envelope, dict) or set(envelope) != {'clearance','size_floors','tier','overrides','source'}
            or envelope['source'] not in ('original_invocation_fab_floor_min','original_invocation_no_escalation')
            or not isinstance(envelope['tier'], str) or not isinstance(envelope['overrides'], dict)
            or not isinstance(envelope['size_floors'],dict)
            or set(envelope['size_floors']) != {'track_width','via_diameter','via_drill','annular'}):
        raise ProofUnavailable('replay_ordinary_grade_request_malformed')
    for value in [envelope['clearance'], *envelope['size_floors'].values()]:
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ProofUnavailable('replay_ordinary_grade_request_malformed')
    path = request['connections']
    if path is not None and (not isinstance(path,str) or not Path(path).is_absolute()
                             or path not in policy['input_files']):
        raise ProofUnavailable('replay_ordinary_grade_request_malformed')
    if (record['identity']['kind']=='connections') != (path is not None):
        raise ProofUnavailable('replay_ordinary_grade_request_malformed')
    return request


def _parent_scope(completed, ctx):
    record = completed
    _, required, argv = _runtime(ctx, record['command'])
    implementation = {str(path): file_hash(path) for path in required}
    scope = completed['raw']['summary'].get('resolved_scope')
    fields = {'schema', 'observation', 'argv', 'input_files', 'output', 'summary',
              'nets', 'layers', 'deadline_utc', 'transport', 'actual_tasks',
              'effective_clearances', 'requested_clearances', 'implementation',
              'actual_output_sha256', 'ordinary_grade_request'}
    if (not isinstance(scope, dict) or set(scope) != fields
            or type(scope['schema']) is not int or scope['schema'] != 2
            or scope['observation'] != 'parent-post-floor-scope'):
        raise ProofUnavailable('replay_original_scope_unavailable')
    raw = [value for path, value in completed['raw']['files'].items()
           if Path(path).name.split('-', 1)[-1] == Path(record['output']).name]
    if len(raw) != 1 or scope['actual_output_sha256'] != raw[0]:
        raise ProofUnavailable('replay_original_scope_output_changed')
    requested = (json.loads(Path(ctx.clearances_file).read_bytes())
                 if ctx.clearances_file is not None else None)
    _resolved_fields(scope, record, ctx.env, implementation, requested, parser_argv=argv)
    return scope['effective_clearances']


def _original_effective(completed, ctx, *, final=False):
    if not final:
        return _parent_scope(completed, ctx)
    if ctx.env.get('KRT_INTERNAL_ROUTE_CANDIDATE') != '1':
        raise ProofUnavailable('replay_original_final_policy_unavailable')
    _, required, argv = _runtime(ctx, completed['command'])
    implementation = {str(path): file_hash(path) for path in required}
    try:
        requested = json.loads(Path(ctx.clearances_file).read_bytes()) if ctx.clearances_file is not None else None
    except (OSError, ValueError, UnicodeError) as error:
        raise ProofUnavailable('replay_original_scope_unavailable') from error
    return _policy(completed['raw']['summary'], completed, ctx.env, implementation,
                   requested, parser_argv=argv)['effective_clearances']


def run_issued(grader, ledger, executor, token, ctx, log):
    """Execute the actual private issued vector once under its retained deadline.

    Existing phase restoration/raw receipt hooks still own those operations.
    No public invocation or summary can substitute for the issued token.
    """
    owner = issued_calls._token(grader, ledger, executor, token)
    if token.raw is not None or token.completed is not None:
        raise ProofUnavailable('replay_call_already_completed')
    record = token.record
    deadline = owner.deadline_utc
    return _run_record(record, deadline, ctx, log,
                       lambda: issued_calls._token(grader, ledger, executor, token))


def _run_record(record, deadline, ctx, log, validate, *, effective_clearances=_UNSET, actual_completed=None):
    """Shared owned launch; only its private owning closure supplies context.

    This function cannot mint original execution custody or adoption authority.
    """
    validate()
    env = dict(ctx.env)
    try:
        actual_deadline = float(env.get('KRT_ROUTE_DEADLINE_UTC', 'nan'))
    except (ValueError, TypeError, OverflowError) as error:
        raise ProofUnavailable('replay_actual_transport_mismatch') from error
    if (record['execution_transport'] is None
            or record_digest(record['execution_transport']) != record_digest(
                {key: env.get(key) for key in issued_calls._TRANSPORT})
            or env.get('KRT_INTERNAL_ROUTE_CANDIDATE') != '1'
            or actual_deadline != deadline):
        raise ProofUnavailable('replay_actual_transport_mismatch')
    files, required, parser_argv = _runtime(ctx, record['command'])
    expected_implementation = {str(path): files[str(path)] for path in required}
    issued_calls._unchanged(record['actual_input_files'])
    # Preserve old artifacts; a reused output is not a fresh owned call.
    if Path(record['output']).exists() or Path(record['summary']).exists():
        raise ProofUnavailable('replay_outputs_not_fresh')
    try:
        rc, stdout, stderr = _execute(record['command'], deadline, env,
                                    cwd=str(Path(ctx.router_dir).resolve()),
                                    pass_fds=route_progress.pass_fds())
    except BaseException as error:
        Path(log).write_text(str(getattr(error, 'output', '') or '') +
                             str(getattr(error, 'stderr', '') or ''))
        raise
    Path(log).write_text(stdout + stderr)
    issued_calls._unchanged(files)
    issued_calls._unchanged(record['actual_input_files'])
    validate()
    if rc != 0 or time.time() >= deadline:
        raise ProofUnavailable('replay_backend_incomplete', returncode=rc)
    try:
        summary_bytes = Path(record['summary']).read_bytes()
        summary = json.loads(summary_bytes)
    except (OSError, ValueError, UnicodeError) as error:
        raise ProofUnavailable('replay_backend_summary_unavailable') from error
    if not isinstance(summary, dict):
        raise ProofUnavailable('replay_backend_summary_malformed')
    if any(summary.get(key) is not None and summary[key] is not False
           for key in ('aborted', 'cancelled', 'timed_out')):
        raise ProofUnavailable('replay_backend_deferred')
    if record['identity']['kind'] == 'connections':
        entries = summary.get('connections')
        if not isinstance(entries, list) or any(not isinstance(entry, dict)
                or entry.get('status') == 'deferred' for entry in entries):
            raise ProofUnavailable('replay_backend_deferred')
    try:
        raw_files = {record['output']: file_hash(record['output']),
                     record['summary']: hashlib.sha256(summary_bytes).hexdigest()}
        issued_calls._unchanged(raw_files)
    except OSError as error:
        raise ProofUnavailable('replay_backend_output_unavailable') from error
    if actual_completed is not None:
        # Execution facts only; optional policy metadata cannot certify these.
        actual_completed({'returncode': rc, 'files': dict(raw_files),
                          'command': list(record['command']),
                          'input_files': dict(record['actual_input_files']),
                          'implementation': dict(files), 'deadline_utc': deadline})
        issued_calls._unchanged(files)
        issued_calls._unchanged(record['actual_input_files'])
        issued_calls._unchanged(raw_files)
        validate()
        if time.time() >= deadline:
            raise ProofUnavailable('replay_backend_incomplete', returncode=rc)
    requested = None
    if ctx.clearances_file is not None:
        try:
            requested = json.loads(Path(ctx.clearances_file).read_bytes())
        except (OSError, ValueError, UnicodeError) as error:
            raise ProofUnavailable('replay_requested_clearances_unavailable') from error
    policy = _policy(summary, record, env, expected_implementation, requested, parser_argv=parser_argv,
                     effective_clearances=effective_clearances)
    return {'returncode': rc, 'files': {record['output']: file_hash(record['output']),
                                      record['summary']: file_hash(record['summary'])},
            'proposals': policy['board_proposals']}


def run_completed(budget, grader, ledger, executor, token, ctx, log, complete_call):
    """Consume one slot around the owning phase's whole existing lifecycle.

    complete_call receives a runner with the existing (cmd, log, ctx) shape.
    It must invoke that runner once, capture raw output, restore original
    companions and lock copper through the normal phase helper, then complete
    the actual issued token. This does not finalize or adopt a board.
    """
    if (budget.grader is not grader or budget.ledger is not ledger
            or budget.executor is not executor):
        raise ProofUnavailable('replay_executor_mismatch')

    def operation(deadline):
        ran = False
        verified = None
        def run(command, actual_log, actual_ctx):
            nonlocal ran, verified
            if (ran or list(command) != token.record['command']
                    or Path(actual_log) != Path(log) or actual_ctx is not ctx):
                raise ProofUnavailable('replay_owned_call_changed')
            ran = True
            verified = run_issued(grader, ledger, executor, token, ctx, log)
            return verified['returncode']
        complete_call(run)
        if verified is None:
            raise ProofUnavailable('replay_owned_call_unverified')
        completed = issued_calls.completed_record(grader, ledger, executor, token)
        for source, expected in verified['files'].items():
            matches = [value for path, value in completed['raw']['files'].items()
                       if Path(path).name.split('-', 1)[-1] == Path(source).name]
            if matches != [expected]:
                raise ProofUnavailable('replay_owned_raw_changed', path=source)
        # Raw artifacts are immutable snapshots. Live outputs are hashed only
        # after original companion restoration and locking has completed.
        files = dict(completed['raw']['files'])
        files.update(completed['completed']['restored_files'])
        return {'returncode': completed['raw']['returncode'], 'proposals': 1,
                'files': {path: value for path, value in files.items() if value is not None}}

    return budget.run_incumbent(executor, operation)


def original_grade_request(record, ctx):
    """Validate the prelaunch request even if completion policy is unavailable.

    This proves the ordinary comparator's requested context, not successful
    routing, candidate cardinality or a FullStanding certificate.
    """
    path = ctx.env.get('KRT_INTERNAL_ORDINARY_GRADE_REQUEST')
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ProofUnavailable('replay_ordinary_grade_request_unavailable')
    try:
        capsule_sha = file_hash(path)
        value = json.loads(Path(path).read_bytes())
        record_digest(value)
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise ProofUnavailable('replay_ordinary_grade_request_unavailable') from error
    fields = {'schema','argv','input_files','output','summary','nets','layers','deadline_utc',
              'transport','actual_tasks','effective_clearances','requested_clearances',
              'implementation','ordinary_grade_request'}
    if not isinstance(value,dict) or set(value)!=fields or type(value['schema']) is not int or value['schema']!=2:
        raise ProofUnavailable('replay_ordinary_grade_request_malformed')
    _, required, argv = _runtime(ctx,record['command'])
    implementation = {str(path):file_hash(path) for path in required}
    try:
        requested=json.loads(Path(ctx.clearances_file).read_bytes()) if ctx.clearances_file is not None else None
    except (OSError, ValueError, UnicodeError) as error:
        raise ProofUnavailable('replay_ordinary_grade_request_unavailable') from error
    _resolved_fields(value,record,ctx.env,implementation,requested,parser_argv=argv)
    try:
        if file_hash(path) != capsule_sha:
            raise ProofUnavailable('replay_ordinary_grade_request_changed')
    except OSError as error:
        raise ProofUnavailable('replay_ordinary_grade_request_unavailable') from error
    return value['ordinary_grade_request']
