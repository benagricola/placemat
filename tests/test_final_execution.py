"""Optional hooks bind actual phase artifacts without changing ordinary routing."""
import json
from pathlib import Path

import pytest

from placemat.kicad import final_execution
from placemat.kicad.final_call import ProofUnavailable, file_hash
from placemat.kicad.phase_run import Routed
from tests.test_final_custody import context


def execution(work):
    # Exercise the phase hook independently of the unavailable Step 2 adapter.
    hook = object.__new__(final_execution.FinalExecution)
    hook.work, hook.active = work, True
    hook.grader, hook.ledger, hook.executor = object(), object(), object()
    hook.refusals = (ProofUnavailable,)
    return hook


def test_actual_routed_summary_triples_bind_names_indices_and_artifact_bytes(tmp_path, monkeypatch):
    board = tmp_path / 'phase.kicad_pcb'
    board.write_text('actual phase copper')
    summary = tmp_path / 'phase_0_summary.json'
    summary.write_text('{"actual": "router output"}')
    routed = Routed(board, 1.2, 1, summaries=[('signals', 0, summary)])
    recorded = []
    monkeypatch.setattr(final_execution.custody, '_executor_record_phase',
                        lambda *args, **kwargs: recorded.append((args, kwargs)))
    hook = execution(tmp_path)
    record = {'name': 'signals'}
    hook.phase(0, record, routed)
    assert hook.active
    assert recorded[0][0] == (hook.grader, hook.ledger, hook.executor, 0, record)
    assert recorded[0][1] == {
        'calls': [('signals', 0, str(summary))],
        'outputs': {str(board): file_hash(board), str(summary): file_hash(summary)},
    }


@pytest.mark.parametrize('item', [('signals', '0', 'summary.json'),
                                  ('signals', True, 'summary.json'),
                                  ('other', 0, 'summary.json'),
                                  ('signals', 0), ('signals', 0, [])])
def test_malformed_optional_summary_withholds_custody_and_preserves_board(tmp_path, monkeypatch, item):
    board = tmp_path / 'phase.kicad_pcb'
    board.write_text('ordinary output')
    routed = Routed(board, 1.2, 1, summaries=[item])
    monkeypatch.setattr(final_execution.custody, '_executor_record_phase',
                        lambda *args, **kwargs: pytest.fail('malformed custody must not be recorded'))
    hook = execution(tmp_path)
    hook.phase(0, {'name': 'signals'}, routed)
    assert not hook.active
    assert board.read_text() == 'ordinary output'
    assert json.loads((tmp_path / 'final_authority_unavailable.json').read_text())['code'] == 'ordinary_call_summary_malformed'


def test_read_snapshot_refusal_still_performs_one_ordinary_read(tmp_path):
    from types import SimpleNamespace
    board = tmp_path / 'input.kicad_pcb'
    board.write_text('original bytes')
    (tmp_path / 'final-original-read.kicad_pcb').write_text('old owned snapshot')
    hook = execution(tmp_path)
    reads = []
    geometry = SimpleNamespace(path=str(board))
    def read(path):
        reads.append(path)
        return geometry
    assert hook.read(board, read) is geometry
    assert reads == [str(board)]
    assert not hook.active
    assert board.read_text() == 'original bytes'


def test_process_cancellation_during_optional_read_propagates(tmp_path):
    from placemat import stop
    board = tmp_path / 'input.kicad_pcb'
    board.write_text('original bytes')
    hook = execution(tmp_path)
    def stopped(path):
        raise stop.Stopped(15)
    with pytest.raises(stop.Stopped):
        hook.read(board, stopped)
    assert hook.active


def test_actual_hooks_register_original_then_seal_only_completed_phase_ledger(context):
    from copy import deepcopy
    from types import SimpleNamespace
    from placemat.kicad.final_custody import require_completed, require_original
    original_grader, facts, report = context
    hook = execution(report.work)
    hook.geometry = deepcopy(facts['geometry'])
    hook.read_identity = deepcopy(facts['read_identity'])
    hook.deadline = facts['deadline_utc']
    bound = []
    hook.factory = SimpleNamespace(bind_physical=bound.append)
    (report.work / 'width_policy.json').write_text(json.dumps(facts['width_receipt']))
    invocation = dict(original_grader._semantic_contract['invocation'],
                      capture={'path': None, 'sha256': None})
    hook.prepare(original=original_grader._original, cleanup_input=original_grader._cleanup_input,
                 baseline_drc=original_grader._baseline, obligations=report.asked,
                 phases=original_grader._phases, width_receipt=facts['width_receipt'],
                 cfg=original_grader._cfg, counted=original_grader._counted,
                 open_before=original_grader._open_before, chosen_pours=original_grader._chosen_pours,
                 invocation=invocation, selections=facts['selections'])
    assert hook.active and bound == [hook.grader]
    assert require_original(hook.grader)['deadline_utc'] == facts['deadline_utc']
    with pytest.raises(ProofUnavailable):
        require_completed(hook.grader)
    summary = report.work / 'actual-summary.json'
    summary.write_text('{"router":"ordinary"}')
    routed = Routed(report.routed_pcb, 1.2, 1, summaries=[('signals', 0, summary)])
    hook.phase(0, report.phases[0], routed)
    (report.work / 'route.json').write_text(json.dumps(report.as_dict()))
    hook.complete(report)
    assert hook.active
    completed = require_completed(hook.grader)
    assert completed['completed']['status'] == 'completed'
    assert completed['completed']['ordinary_phase_calls']['values'][0]['calls']['values'][0]['values'] == ['signals', 0, str(summary)]
