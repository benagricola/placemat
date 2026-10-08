"""Optional full authority requires privately retained execution custody."""
import time
from pathlib import Path

import pytest

from placemat.final_authority import AuthorityRefused, retain
from tests.test_pinmap_common import scene
from tests.test_pinmap_written import _source


def factory(tmp_path, **overrides):
    board, plan, _, _ = scene()
    values = dict(invocation={}, deadline_utc=time.time() + 60)
    values.update(overrides)
    return retain(board, plan, {}, _source(tmp_path), **values)


@pytest.mark.parametrize('deadline', [True, float('inf'), 0])
def test_unavailable_absolute_deadline_refuses(tmp_path, deadline):
    with pytest.raises(AuthorityRefused) as error:
        factory(tmp_path, deadline_utc=deadline)
    assert error.value.code == 'authority_deadline_unavailable'


def test_completion_without_actual_bound_executor_is_unavailable(tmp_path):
    value = factory(tmp_path)
    with pytest.raises(AuthorityRefused) as error:
        value.completed_authority()
    assert error.value.code == 'authority_completion_unavailable'


def test_changed_original_source_refuses_without_native_read(tmp_path):
    value = factory(tmp_path)
    value._source.write_text('changed source')
    with pytest.raises(AuthorityRefused) as error:
        value.completed_authority()
    assert error.value.code == 'authority_original_input_changed'


def test_original_receipt_mismatch_is_structured_at_validation_site(tmp_path, monkeypatch):
    import hashlib
    import json
    import sys
    from types import SimpleNamespace
    from placemat.original_binding import verify_original_binding
    from placemat.pinmap_common import CandidateRefused
    source = tmp_path / 'source.kicad_pcb'
    source.write_text('original')
    receipt = tmp_path / 'width_policy.json'
    receipt.write_text('{}')
    sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    class KnownError(ValueError):
        pass
    phase = SimpleNamespace(key=lambda: ['rest'])
    def invalid_receipt(*args, **kwargs):
        raise ValueError('receipt board identity differs from original')
    monkeypatch.setitem(sys.modules, 'placemat.capture_nets', SimpleNamespace(read_capture=lambda path: None, CaptureError=KnownError))
    monkeypatch.setitem(sys.modules, 'placemat.route_phase', SimpleNamespace(phases_of=lambda cfg: [phase], PhaseError=KnownError))
    monkeypatch.setitem(sys.modules, 'placemat.kicad.phase_select', SimpleNamespace(select=lambda *a, **kw: SimpleNamespace(pour_nets=())))
    monkeypatch.setitem(sys.modules, 'placemat.kicad.phase_run', SimpleNamespace(comparison_obligations=lambda *a: []))
    monkeypatch.setitem(sys.modules, 'placemat.kicad.width_policy', SimpleNamespace(
        requests_of=lambda *a: {}, validate_receipt=invalid_receipt, apply=lambda *a: []))
    monkeypatch.setitem(sys.modules, 'placemat.kicad.final_call', SimpleNamespace(file_hash=sha, record_digest=lambda value: 'bound'))
    invocation = {'phases': [['rest']], 'upto': None, 'only': False, 'quick': False,
                  'layers': ['F.Cu'], 'exclude_nets': [], 'pour_nets': [],
                  'capture': {'path': None, 'sha256': None}, 'router_dir': str(tmp_path),
                  'router_python': '/usr/bin/python3',
                  'width_query_input': {'path': str(source), 'sha256': sha(source)}}
    board, _, _, _ = scene()
    retained = SimpleNamespace(_board=board, _invocation=invocation, _inputs={str(source): sha(source)})
    binding = {'contract_sha256': 'bound', 'paths': {'original': str(source), 'width_receipt': str(receipt)},
               'contract': {'invocation': invocation, 'phases': [['rest']], 'chosen_pours': [],
                            'counted': [], 'width_receipt_sha256': sha(receipt),
                            'width_authority': {}, 'obligations': []}}
    with pytest.raises(CandidateRefused) as error:
        verify_original_binding(retained, binding, SimpleNamespace(nets={'A': ()}))
    assert error.value.code == 'authority_width_receipt_unavailable'
    assert str(error.value) == 'receipt board identity differs from original'
