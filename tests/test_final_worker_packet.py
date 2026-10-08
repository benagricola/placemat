"""Malformed artifact fields refuse before creating destinations or children."""
from copy import deepcopy

import pytest

from placemat.kicad import final_owned_worker, final_worker_protocol
from placemat.kicad.final_call import ProofUnavailable
from placemat.kicad.final_custody import require_completed
from tests.test_final_custody import context, completed


@pytest.mark.parametrize('field,value', [
    ('raw', {}), ('raw', {'sha256': '0' * 64}),
    ('raw', {'path': [], 'sha256': '0' * 64}),
    ('raw', {'path': True, 'sha256': '0' * 64}),
    ('raw', {'path': 'relative.pcb', 'sha256': '0' * 64}),
    ('raw', {'path': '/board.pcb', 'sha256': None}),
    ('raw', {'path': '/board.pcb', 'sha256': 'Z' * 64}),
    ('candidate_summary', {}), ('candidate_summary', {'sha256': '0' * 64}),
    ('candidate_summary', {'path': 42, 'sha256': '0' * 64}),
    ('candidate_summary', {'path': '/summary.json', 'sha256': False}),
    ('candidate_summary', []), ('destination', False),
    ('destination', 'relative-output'), ('schema', True),
])
def test_malformed_artifact_with_completed_custody_refuses_before_publication(context, monkeypatch, field, value):
    grader, facts, report, ledger, token = completed(context)
    destination = report.work / 'candidate'
    packet = {'schema': 1, 'deadline_utc': facts['deadline_utc'],
              'binding': {}, 'settings': {}, 'template': {},
              'executor_custody': require_completed(grader),
              'raw': {'path': str(report.routed_pcb), 'sha256': '0' * 64},
              'destination': str(destination), 'candidate_summary': None}
    packet[field] = deepcopy(value)
    monkeypatch.setattr(final_owned_worker, '_execute',
                        lambda *args, **kwargs: pytest.fail('malformed packet launched a child'))
    with pytest.raises(ProofUnavailable):
        final_worker_protocol.validate_packet_fields(packet)
    with pytest.raises(ProofUnavailable):
        final_owned_worker.grade_owned(grader, packet, {}, deadline_utc=facts['deadline_utc'])
    assert not destination.exists()
    assert not destination.with_name('candidate.worker').exists()
