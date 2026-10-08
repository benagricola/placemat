"""Concrete optional decode and parent native-discovery refusal controls."""
import builtins
from copy import deepcopy
import json
import sys
from types import SimpleNamespace

import pytest

from placemat.kicad import final_owned_worker
from placemat.kicad.final_call import ProofUnavailable
from tests.test_final_custody import context
from tests.test_final_execution import execution


@pytest.mark.parametrize('raw', [b'{', b'\xff'])
def test_optional_baseline_decode_withholds_without_aborting_ordinary(context, raw):
    original_grader, facts, report = context
    hook = execution(report.work)
    hook.geometry = deepcopy(facts['geometry'])
    hook.read_identity = deepcopy(facts['read_identity'])
    hook.deadline = facts['deadline_utc']
    bound = []
    hook.factory = SimpleNamespace(bind_physical=bound.append)
    (report.work / 'width_policy.json').write_text(json.dumps(facts['width_receipt']))
    original_grader._baseline.write_bytes(raw)
    hook.prepare(original=original_grader._original, cleanup_input=original_grader._cleanup_input,
                 baseline_drc=original_grader._baseline, obligations=report.asked,
                 phases=original_grader._phases, width_receipt=facts['width_receipt'],
                 cfg=original_grader._cfg, counted=original_grader._counted,
                 open_before=original_grader._open_before, chosen_pours=original_grader._chosen_pours,
                 invocation={'capture': {'path': None, 'sha256': None}}, selections=facts['selections'])
    assert not hook.active and bound == []
    assert report.routed_pcb.read_text() == 'actual finalized copper'
    assert json.loads((report.work / 'final_authority_unavailable.json').read_text())['code'] == 'original_baseline_malformed'


def test_parent_runtime_discovery_requires_existing_native_import(monkeypatch):
    for name in list(sys.modules):
        if name == 'placemat_native' or name.startswith('placemat_native.'):
            monkeypatch.delitem(sys.modules, name)
    original_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == 'placemat_native' or name.startswith('placemat_native.'):
            pytest.fail('parent runtime discovery introduced a native import')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    with pytest.raises(ProofUnavailable, match='physical_runtime_unavailable'):
        final_owned_worker._implementation()
