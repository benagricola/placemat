"""The owned worker uses a fixed codec and one absolute deadline."""
import copy
import sys
import time
from types import SimpleNamespace

import pytest

from placemat import final_check_worker as worker
from placemat.final_check_context import ContextRefused


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch):
    # Unit sequencing uses explicit stand-ins; actual runtime/native reads are
    # exercised separately by the owned saved-board integration gate.
    monkeypatch.setattr(worker, '_runtime_identity', lambda: {'runtime': 'bound'})
    monkeypatch.setattr(worker, '_preservation', lambda *args: {
        'original_manifest': {'bound': 'original'}, 'held_and_fixed_preserved': True})


def request():
    deadline = time.time() + 30
    return {'schema': 1, 'deadline_utc': deadline,
            'physical': {'deadline_utc': deadline, 'binding': {'contract_sha256': 'bound'}},
            'critical': {'original': 'context', 'source_physical': {'bound': 'original'}}}


@pytest.mark.parametrize('change', ['missing', 'schema-bool', 'expired', 'nonfinite', 'other-deadline'])
def test_bad_outer_context_refuses_before_physical_reconstruction(change):
    value = request()
    if change == 'missing':
        del value['critical']
    elif change == 'schema-bool':
        value['schema'] = True
    elif change == 'expired':
        value['deadline_utc'] = time.time() - 1
    elif change == 'nonfinite':
        value['deadline_utc'] = float('inf')
    else:
        value['physical']['deadline_utc'] += 1
    with pytest.raises(ContextRefused):
        worker.evaluate(value)


def test_exact_physical_then_shared_critical_judge_and_reverification(tmp_path, monkeypatch):
    value = request()
    calls = []
    report = SimpleNamespace(routed_pcb=tmp_path / 'routed.kicad_pcb')
    result = SimpleNamespace(report=report)
    receipt = {'original': 'physical context'}
    (tmp_path / 'physical_grade.json').write_text('physical evidence')
    class Grader:
        _worker_original_proof = {'original': 'verified'}
        def regrade(self, raw, dest, *, candidate_summary):
            calls.append(('physical', raw, dest, candidate_summary))
            return result
        def verify(self, actual):
            assert actual is result
            calls.append(('verify',))
            return copy.deepcopy(receipt)
    codec = SimpleNamespace(reconstruct=lambda packet: (Grader(), 'raw', tmp_path, None),
                            report_record=lambda actual: {'whole_report': actual is report})
    monkeypatch.setitem(sys.modules, 'placemat.kicad.final_worker_protocol', codec)
    def critical(context, pcb):
        assert context is value['critical'] and pcb == report.routed_pcb
        calls.append(('critical',))
        return SimpleNamespace(measures={'critical_checks': 0}, evidence=lambda: {'critical_unknown': []})
    monkeypatch.setattr(worker, 'judge', critical)
    response = worker.evaluate(value)
    assert [c[0] for c in calls] == ['physical', 'verify', 'critical', 'verify']
    assert response['report'] == {'whole_report': True}
    assert response['physical_receipt'] == receipt
    assert response['critical']['measures'] == {'critical_checks': 0}
    assert response['request_sha256'] == worker._digest(value)
    assert response['original_verification'] == {'original': 'verified'}
    assert response['implementation_start'] == response['implementation_end'] == {'runtime': 'bound'}
    assert response['critical']['preservation']['held_and_fixed_preserved'] is True


def test_duplicate_json_fields_refuse():
    with pytest.raises(ContextRefused):
        worker._unique([('schema', 1), ('schema', 2)])


@pytest.mark.parametrize('change', ['deadline', 'physical', 'request', 'runtime'])
def test_late_or_changed_evidence_never_returns_authority(tmp_path, monkeypatch, change):
    value = request()
    if change == 'runtime':
        identities = iter(({'runtime': 'bound'}, {'runtime': 'changed'}))
        monkeypatch.setattr(worker, '_runtime_identity', lambda: next(identities))
    report = SimpleNamespace(routed_pcb=tmp_path / 'routed.kicad_pcb')
    result = SimpleNamespace(report=report)
    calls = []
    class Grader:
        _worker_original_proof = {'original': 'verified'}
        def regrade(self, *args, **kwargs):
            return result
        def verify(self, actual):
            calls.append('verify')
            return {'hash': 'changed' if change == 'physical' and len(calls) == 2 else 'original'}
    monkeypatch.setitem(sys.modules, 'placemat.kicad.final_worker_protocol', SimpleNamespace(
        reconstruct=lambda packet: (Grader(), 'raw', tmp_path, None), report_record=lambda _: {}))
    def critical(*args):
        if change == 'deadline':
            monkeypatch.setattr(worker.time, 'time', lambda: value['deadline_utc'] + 1)
        elif change == 'request':
            value['critical']['original'] = 'mutated'
        return SimpleNamespace(measures={}, evidence=lambda: {})
    monkeypatch.setattr(worker, 'judge', critical)
    with pytest.raises(ContextRefused):
        worker.evaluate(value)


def test_missing_physical_manifest_refuses_before_runtime_or_native_reads(monkeypatch):
    value = request()
    del value['critical']['source_physical']
    monkeypatch.setattr(worker, '_runtime_identity', lambda: pytest.fail('invalid context reached native runtime'))
    with pytest.raises(ContextRefused):
        worker.evaluate(value)
