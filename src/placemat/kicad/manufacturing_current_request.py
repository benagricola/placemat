"""Scratch actual-parent request seam for the ordinary comparator.

The saved-request codec is reused only for bytes/inventory encoding. Its
historical context is replaced after genuine current owner/custody validation.
No authority is minted by the returned worker request.
"""
from pathlib import Path
import shutil
from placemat.kicad import issued_calls, final_custody
from placemat.kicad import replay_backend as backend
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad.final_owned_worker import _implementation
from .manufacturing_inventory import retained_original
from .manufacturing_request_codec import saved_request, bound_json


def copy_current_family(raw_board, copied, expected_raw, original_files):
    """Byte transport only; expected values come from current private custody."""
    raw_board=Path(raw_board).resolve();copied=Path(copied)
    if file_hash(raw_board)!=expected_raw:raise ProofUnavailable('current_measurement_raw_changed')
    shutil.copyfile(raw_board,copied)
    if file_hash(copied)!=expected_raw or file_hash(raw_board)!=expected_raw:
        raise ProofUnavailable('current_measurement_copied_pcb_changed')
    for suffix,entry in original_files.items():
        if suffix=='.kicad_pcb':continue
        target=copied.with_suffix(suffix)
        if entry is None:
            original=Path(original_files['.kicad_pcb']['path']).with_suffix(suffix)
            if original.exists() or original.is_symlink() or target.exists() or target.is_symlink():
                raise ProofUnavailable('current_measurement_copied_absence_changed')
        else:
            source=Path(entry['path']);expected=entry['sha256']
            if file_hash(source)!=expected:raise ProofUnavailable('current_measurement_original_changed')
            shutil.copyfile(source,target)
            if file_hash(target)!=expected or file_hash(source)!=expected:
                raise ProofUnavailable('current_measurement_copied_companion_changed')


def prepare(budget, owner, final_call, legacy_board, candidate_board, candidate_files, *, work):
    """Called only at choose's current two-slot boundary, before owned checking."""
    def checked():
        budget._check(budget.executor)
        if budget.states != ['completed', 'issued'] or owner.final_call is not final_call:
            raise ProofUnavailable('replay_completed_pocket_required')
        contexts = owner.contexts_for(budget)
        completed = final_custody.require_completed(budget.grader)
        if record_digest(completed) != budget.completion_sha:
            raise ProofUnavailable('replay_completed_context_changed')
        return contexts[final_call], retained_original(owner.factory)

    ctx, original = checked()
    if original['deadline_utc'] != budget.deadline:
        raise ProofUnavailable('current_measurement_deadline_changed')
    record = issued_calls.completed_record(budget.grader, budget.ledger,
                                          budget.executor, final_call)
    record_sha = record_digest(record)
    for board, files in ((legacy_board, record['raw']['files']),
                         (candidate_board, candidate_files)):
        board = Path(board).resolve()
        if (str(board) not in files or files[str(board)] != file_hash(board)
                or any(file_hash(path) != expected for path, expected in files.items())):
            raise ProofUnavailable('current_measurement_raw_unbound')
    template = backend.original_grade_request(record, ctx)
    capsule = ctx.env['KRT_INTERNAL_ORDINARY_GRADE_REQUEST']
    capture, identity = bound_json(capsule)
    if (capture['deadline_utc'] != budget.deadline
            or record_digest(capture['ordinary_grade_request']) != record_digest(template)):
        raise ProofUnavailable('current_measurement_capsule_changed')
    runtime = _implementation()
    runtime.update(backend._runtime(ctx, record['command'])[0])
    parser = (Path(ctx.router_dir) / ctx.script).resolve().with_name('kicad_parser.py')
    runtime[str(parser)] = file_hash(parser)
    # The implementation's own fixed family, not a path supplied by a receipt
    # or proposed candidate. This remains scratch until package mapping review.
    measurement_sources = list(Path(__file__).resolve().parent.glob('*.py'))
    for path in measurement_sources:
        path = Path(path).resolve()
        runtime[str(path)] = file_hash(path)
    source = original['original']['files']['.kicad_pcb']['path']
    # Raw snapshots have independently numbered companion names. Use only the
    # raw copper plus exact retained-original companions in native check copies,
    # as the existing ordinary grade worker does; never reinterpret a snapshot
    # suffix as authority over the project/rules.
    inputs = Path(work).resolve() / 'native-inputs'
    inputs.mkdir()
    copies = {}
    raw_pins = {str(Path(p).resolve()): file_hash(p)
                for p in (legacy_board, candidate_board)}
    for side, board in (('legacy', legacy_board), ('pocket', candidate_board)):
        folder = inputs / side; folder.mkdir()
        copied = folder / 'board.kicad_pcb'
        copy_current_family(board,copied,raw_pins[str(Path(board).resolve())],original['original']['files'])
        copies[side] = copied
    packet = saved_request(original=source, legacy=copies['legacy'],
        candidate=copies['pocket'], capsule=capsule, runtime=runtime,
        deadline_utc=budget.deadline)
    context = packet['context']
    if context['source_inventory'] != original['original']:
        raise ProofUnavailable('current_measurement_original_changed')
    context.pop('historical_deadline_utc')
    context.update(mode='retained_current_measurement',
        original_custody_sha256=original['custody_sha256'],
        actual_raw_copper=raw_pins,
        krt_parser=str(parser), drc_work=str(Path(work).resolve() / 'native-drc'))
    cli = next((p for p in runtime if Path(p).name == 'kicad-cli'), None)
    if cli is None:
        raise ProofUnavailable('current_measurement_cli_unavailable')
    context['drc_cli'] = {'path': cli, 'sha256': runtime[cli]}
    after_ctx, after_original = checked()
    if (after_original != original
            or owner._context_digest(after_ctx) != owner._context_digest(ctx)
            or record_digest(issued_calls.completed_record(budget.grader,
                budget.ledger, budget.executor, final_call)) != record_sha
            or file_hash(identity['path']) != identity['sha256']):
        raise ProofUnavailable('current_measurement_owner_changed')
    if (any(file_hash(path) != expected for path, expected in raw_pins.items())
            or any(file_hash(path) != expected for path, expected in candidate_files.items())):
        raise ProofUnavailable('current_measurement_raw_changed')
    return packet
