"""Private actual-call custody for optional complete-board proposals.

These receipts describe executed work. They are neither a Standing certificate
nor permission to change original copper. The ordinary route owns issuance.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time

from . import final_custody as custody
from .final_call import ProofUnavailable, file_hash, record_digest

_MINT = object()
_TRANSPORT = ('KRT_INTERNAL_ROUTE_CANDIDATE', 'KRT_INTERNAL_POCKET_WALLS',
              'KRT_ROUTE_DEADLINE_UTC', 'KRT_ROUTE_BUDGET_S',
              'KRT_INTERNAL_FINAL_CALL_CONTEXT', 'KRT_INTERNAL_FINAL_CALL_KIND',
              'KRT_INTERNAL_FINAL_CALL_PROOF', 'KRT_INTERNAL_FINAL_CALL_ID')


def _owner(grader, ledger, executor, *, writing=True):
    state = custody._context(grader)
    if (state.run is not ledger or ledger.owner is not state
            or ledger.executor is not executor or (writing and ledger.sealed)):
        raise ProofUnavailable('issued_call_owner_mismatch')
    for record, fingerprint in ledger.call_plans:
        if record_digest(record) != fingerprint:
            raise ProofUnavailable('issued_call_plan_changed')
    return state


def _files(board):
    board = Path(board)
    paths = [board] + [board.with_suffix(ext) for ext in ('.kicad_pro', '.kicad_dru')]
    return {str(path.resolve()): file_hash(path) if path.is_file() else None for path in paths}


def _unchanged(files):
    for path, expected in files.items():
        actual = file_hash(path) if Path(path).is_file() else None
        if actual != expected:
            raise ProofUnavailable('issued_call_artifact_changed', path=path)


def _snapshot(files, destination):
    destination = Path(destination)
    destination.mkdir()
    saved = {}
    for index, (path, expected) in enumerate(files.items()):
        if expected is None:
            continue
        target = destination / ('%d-%s' % (index, Path(path).name))
        with target.open('xb') as stream:
            stream.write(Path(path).read_bytes())
        if file_hash(target) != expected:
            raise ProofUnavailable('issued_call_snapshot_changed', path=path)
        saved[str(target.resolve())] = expected
    _unchanged(files)
    return saved


def _task(record):
    if not isinstance(record, dict):
        raise ProofUnavailable('issued_task_malformed')
    try:
        value = {key: deepcopy(record[key]) for key in ('net', 'from', 'to', 'widths')}
    except KeyError as error:
        raise ProofUnavailable('issued_task_malformed') from error
    if (not isinstance(value['net'], str) or not value['net']
            or any(not isinstance(value[side], dict) or set(value[side]) != {'ref', 'pad'}
                   or any(not isinstance(v, str) or not v for v in value[side].values())
                   for side in ('from', 'to')) or not isinstance(value['widths'], dict)):
        raise ProofUnavailable('issued_task_malformed')
    if (not value['widths'] or any(not isinstance(layer, str) or not layer
            or type(width) not in (int, float) or not math.isfinite(width) or width <= 0
            for layer, width in value['widths'].items())):
        raise ProofUnavailable('issued_task_width_malformed')
    record_digest(value)
    return value


@dataclass(frozen=True)
class _Identity:
    phase: int
    call: int
    wave: int
    kind: str

    def record(self):
        if (any(type(v) is not int or v < 0 for v in (self.phase, self.call, self.wave))
                or self.kind not in ('single', 'connections', 'pour')):
            raise ProofUnavailable('issued_call_identity_malformed')
        return dict(phase=self.phase, call=self.call, wave=self.wave, kind=self.kind)


class IssuedCall(custody._Opaque):
    """Noncopyable token minted at actual executor issuance, never from JSON."""
    __slots__ = ('owner', 'ledger', 'executor', 'record', 'record_sha', 'raw', 'raw_sha', 'completed', 'completed_sha')

    def __new__(cls, key, *args):
        if key is not _MINT:
            raise ProofUnavailable('private_call_issuer_required')
        return super().__new__(cls)

    def __init__(self, key, owner, ledger, executor, record):
        self.owner, self.ledger, self.executor = owner, ledger, executor
        self.record, self.record_sha = record, record_digest(record)
        self.raw = self.raw_sha = self.completed = self.completed_sha = None


def _executor_plan(grader, ledger, executor, *, phase, calls, layers, input_board):
    """Bind the actual planner result before any call in this phase executes."""
    _owner(grader, ledger, executor)
    from .phase_run import Call
    if (type(phase) is not int or phase != len(ledger.phases)
            or phase != len(ledger.call_plans) or phase >= len(grader._phases)
            or not isinstance(calls, (list, tuple))
            or any(type(call) is not Call for call in calls)
            or not isinstance(layers, (list, tuple)) or not layers
            or any(not isinstance(layer, str) or not layer for layer in layers)
            or len(set(layers)) != len(layers)
            or not isinstance(input_board, (str, Path)) or not Path(input_board).is_file()):
        raise ProofUnavailable('issued_call_plan_malformed')
    records = []
    for call in calls:
        records.append(dict(kind=call.kind, nets=list(call.nets), excluded=list(call.excluded),
                            tasks=[task.record() for task in call.tasks],
                            width=call.width, clearance=call.clearance))
    record = dict(phase=phase, layers=list(layers), calls=records, input=_files(input_board))
    fingerprint = record_digest(record)
    ledger.call_plans.append((deepcopy(record), fingerprint))


def _executor_issue(grader, ledger, executor, *, phase, call, wave, kind,
                    command, source, input_board, output_board, summary,
                    layers, nets, tasks, constraint_files, snapshot_dir, task_file=None, environment=None):
    """PRIVATE hook immediately before the actual issued subprocess.

    Pour source and transformed input are separate identities. Connection tasks
    are bound to the actual written file and original frozen terminal demands.
    """
    owner = _owner(grader, ledger, executor)
    identity = _Identity(phase, call, wave, kind).record()
    if ledger.call_plans:
        if phase >= len(ledger.call_plans):
            raise ProofUnavailable('issued_call_plan_missing')
        planned = ledger.call_plans[phase][0]['calls']
        if call >= len(planned):
            raise ProofUnavailable('issued_call_outside_plan')
        permitted = {'single': ('nets', 'rest'), 'connections': ('tasks', 'bus_tasks'),
                     'pour': ('pour',)}
        if planned[call]['kind'] not in permitted[kind]:
            raise ProofUnavailable('issued_call_kind_outside_plan')
    issued = ledger.issued
    if any(t.completed is None for t in issued):
        raise ProofUnavailable('issued_call_previous_incomplete')
    if any(t.record['identity'] == identity for t in issued):
        raise ProofUnavailable('issued_call_duplicate')
    if phase != len(ledger.phases) or phase >= len(grader._phases):
        raise ProofUnavailable('issued_call_phase_order')
    if (not isinstance(command, (tuple, list)) or not command
            or any(not isinstance(token, str) for token in command)
            or not isinstance(layers, (tuple, list)) or not layers
            or any(not isinstance(layer, str) for layer in layers)
            or not isinstance(nets, (tuple, list)) or any(not isinstance(n, str) for n in nets)):
        raise ProofUnavailable('issued_call_scope_malformed')
    if not isinstance(tasks, (tuple, list)) or not isinstance(constraint_files, (tuple, list)):
        raise ProofUnavailable('issued_call_scope_malformed')
    paths = (source, input_board, output_board, summary, snapshot_dir)
    if task_file is not None:
        paths += (task_file,)
    if any(not isinstance(path, (str, Path)) or not str(path)
           for path in paths + tuple(constraint_files)):
        raise ProofUnavailable('issued_call_path_malformed')
    if not Path(source).is_file() or not Path(input_board).is_file():
        raise ProofUnavailable('issued_call_board_missing')
    if environment is not None and (not isinstance(environment, dict)
            or any(environment.get(key) is not None and not isinstance(environment.get(key), str)
                   for key in _TRANSPORT)):
        raise ProofUnavailable('issued_execution_environment_malformed')
    transport = ({key: environment.get(key) for key in _TRANSPORT}
                 if environment is not None else None)
    normalized = [_task(task) for task in tasks]
    if kind == 'connections' and (
            set(nets) != {task['net'] for task in normalized}
            or any(set(task['widths']) != set(layers) for task in normalized)
            or len(set(layers)) != len(layers) or len(set(nets)) != len(nets)):
        raise ProofUnavailable('issued_connection_scope_mismatch')
    originals = [_task(task) for task in json.loads(grader._obligations)[phase]]
    if any(task not in originals for task in normalized):
        raise ProofUnavailable('issued_task_outside_original_contract')
    if kind == 'connections':
        if not normalized or task_file is None:
            raise ProofUnavailable('issued_connection_tasks_missing')
        try:
            actual_tasks = json.loads(Path(task_file).read_bytes())
            if not isinstance(actual_tasks, list) or [_task(task) for task in actual_tasks] != normalized:
                raise ProofUnavailable('issued_task_file_mismatch')
        except (OSError, ValueError, UnicodeError) as error:
            if isinstance(error, ProofUnavailable):
                raise
            raise ProofUnavailable('issued_task_file_unavailable') from error
        constraint_files = tuple(constraint_files) + (task_file,)
    if not set(nets).issubset({task['net'] for task in originals}):
        raise ProofUnavailable('issued_net_outside_original_contract')
    if kind == 'pour':
        if len(nets) != 1 or nets[0] not in grader._chosen_pours or len(set(layers)) != len(layers):
            raise ProofUnavailable('issued_pour_scope_unproved')
        selected = [task for task in originals if task['net'] == nets[0]]
        task_selector = getattr(grader._phases[phase], 'selector', None) in ('connections', 'current_paths')
        if ((normalized or task_selector) and normalized != selected
                or any(set(task['widths']) != set(layers) for task in selected)):
            raise ProofUnavailable('issued_pour_task_scope_mismatch')
    files = dict(_files(source))
    files.update(_files(input_board))
    for path in constraint_files:
        path = Path(path).resolve()
        if not path.is_file():
            raise ProofUnavailable('issued_constraint_missing', path=str(path))
        files[str(path)] = file_hash(path)
    transform = None
    if kind == 'pour':
        from . import pour_identity
        transform = pour_identity.normalized(source, input_board)
    source_files = _snapshot(files, snapshot_dir)
    record = {'schema': 1, 'identity': identity, 'phase': grader._phases[phase].name,
              'command': list(command), 'source': str(Path(source).resolve()),
              'input': str(Path(input_board).resolve()), 'output': str(Path(output_board).resolve()),
              'summary': str(Path(summary).resolve()), 'layers': list(layers), 'nets': list(nets),
              'tasks': normalized, 'actual_input_files': files, 'input_snapshots': source_files,
              'original_context_sha256': owner.original_sha,
              'width_authority_sha256': record_digest(json.loads(grader._widths)),
              'deadline_utc': owner.deadline_utc, 'pour_transform': transform,
              'execution_transport': transport}
    token = IssuedCall(_MINT, owner, ledger, executor, record)
    issued.append(token)
    return token


def _token(grader, ledger, executor, token, *, writing=True):
    owner = _owner(grader, ledger, executor, writing=writing)
    if (type(token) is not IssuedCall or token.owner is not owner
            or token.ledger is not ledger or token.executor is not executor
            or token not in ledger.issued
            or record_digest(token.record) != token.record_sha):
        raise ProofUnavailable('issued_call_token_mismatch')
    _unchanged(token.record['input_snapshots'])
    if token.raw is not None and record_digest(token.raw) != token.raw_sha:
        raise ProofUnavailable('issued_raw_receipt_changed')
    if token.completed is not None and record_digest(token.completed) != token.completed_sha:
        raise ProofUnavailable('issued_completed_receipt_changed')
    return owner


def _executor_raw_result(grader, ledger, executor, token, *, returncode, snapshot_dir):
    """PRIVATE after the real process returns, before project/guard restoration."""
    _token(grader, ledger, executor, token)
    if token.raw is not None or token.completed is not None or type(returncode) is not int:
        raise ProofUnavailable('issued_call_raw_result_mismatch')
    if returncode != 0:
        raise ProofUnavailable('issued_call_incomplete', returncode=returncode)
    output, summary = Path(token.record['output']), Path(token.record['summary'])
    if not output.is_file() or not summary.is_file():
        raise ProofUnavailable('issued_call_outputs_missing')
    try:
        data = json.loads(summary.read_bytes())
    except (OSError, ValueError, UnicodeError) as error:
        raise ProofUnavailable('issued_call_summary_malformed') from error
    if not isinstance(data, dict):
        raise ProofUnavailable('issued_call_summary_malformed')
    if token.record['identity']['kind'] == 'connections':
        from .phase_select import Task
        from .phase_run import connection_summary
        from .route import RouterFailed
        pending = [Task(task['net'], (task['from']['ref'], task['from']['pad']),
                        (task['to']['ref'], task['to']['pad']), tuple(task['widths'].items()))
                   for task in token.record['tasks']]
        try:
            checked = connection_summary(summary, pending, token.record['phase'], summary)
        except RouterFailed as error:
            raise ProofUnavailable('issued_connection_summary_unproved', reason=error.facts) from error
        if checked != data:
            raise ProofUnavailable('issued_call_summary_changed')
    if token.record['identity']['kind'] == 'pour':
        integer_fields = ('successful', 'failed', 'total_iterations', 'total_vias')
        if (any(type(data.get(key)) is not int or data[key] < 0 for key in integer_fields)
                or type(data.get('total_time')) not in (int, float)
                or not math.isfinite(data['total_time']) or data['total_time'] < 0
                or any(data.get(key) is not None and data[key] is not False
                       for key in ('aborted', 'cancelled', 'timed_out'))):
            raise ProofUnavailable('issued_pour_summary_unproved')
        # Recognized execution effort/status only. These values never certify
        # connectivity or widths; original frozen asks are independently graded.
    files = _files(output)
    files[str(summary)] = file_hash(summary)
    token.raw = {'returncode': returncode, 'summary': data, 'files': _snapshot(files, snapshot_dir)}
    token.raw_sha = record_digest(token.raw)


def _executor_restored_result(grader, ledger, executor, token):
    """PRIVATE after actual source-project/locking/pour/guard restoration."""
    _token(grader, ledger, executor, token)
    if token.raw is None or token.completed is not None:
        raise ProofUnavailable('issued_call_restoration_order')
    _unchanged(token.raw['files'])
    summary = Path(token.record['summary'])
    raw_summary_sha = next(v for p, v in token.raw['files'].items() if Path(p).name.endswith(summary.name))
    if file_hash(summary) != raw_summary_sha:
        raise ProofUnavailable('issued_call_summary_changed')
    output_files = _files(token.record['output'])
    if output_files[token.record['output']] is None:
        raise ProofUnavailable('issued_call_outputs_missing')
    for ext in ('.kicad_pro', '.kicad_dru'):
        source = str(Path(token.record['source']).with_suffix(ext))
        output = str(Path(token.record['output']).with_suffix(ext))
        if output_files[output] != token.record['actual_input_files'][source]:
            raise ProofUnavailable('issued_restored_rules_changed', suffix=ext)
    transform = None
    if token.record['identity']['kind'] == 'pour':
        from .pour_identity import restored
        transform = restored(token.record['source'], token.record['output'],
                             token.record['pour_transform'])
    token.completed = {'restored_files': output_files, 'completed_utc': time.time(),
                       'pour_transform': transform}
    token.completed_sha = record_digest(token.completed)
    return completed_record(grader, ledger, executor, token)


def completed_record(grader, ledger, executor, token):
    """Validated detached execution receipt; no mint or adoption authority."""
    _token(grader, ledger, executor, token, writing=False)
    if token.completed is None:
        raise ProofUnavailable('issued_call_not_completed')
    _unchanged(token.raw['files'])
    _unchanged(token.completed['restored_files'])
    return deepcopy(dict(token.record, raw=token.raw, completed=token.completed))
