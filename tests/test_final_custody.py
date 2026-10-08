"""Pure adversarial custody tests; no native/KiCad read, subprocess or routing."""
from pathlib import Path
from dataclasses import dataclass
from copy import copy, deepcopy
import json
import pickle
import sys
import subprocess
import time
import pytest
from placemat.kicad import final_custody as c
from placemat.board_geometry import BoardGeometry, NetClass
from placemat.kicad.final_route import FinalCopperGrader

@dataclass
class Cfg:
    strict: bool = True

    def json(self):
        return json.dumps({'strict': self.strict})

@dataclass
class Phase:
    name: str = 'signals'

    def key(self):
        return {'name': self.name}

@dataclass
class Report:
    asked: list
    phases: list
    routed_pcb: Path
    work: Path
    final_judged: list
    quick: bool = False

    def as_dict(self):
        return {'phases': self.phases, 'routed_pcb': str(self.routed_pcb), 'quick': self.quick, 'valid': self.valid}
    valid: bool = False

@pytest.fixture
def context(tmp_path):
    original = tmp_path / 'input.kicad_pcb'
    original.write_text('original physical input')
    original.with_suffix('.kicad_pro').write_text('original required rules')
    cleanup = tmp_path / 'cleanup.kicad_pcb'
    cleanup.write_text('fixed original copper')
    baseline = tmp_path / 'baseline.json'
    baseline.write_text('{"invalid_outline":1}')
    receipt = tmp_path / 'width.json'
    widths = {'by_net': {'N': {'F.Cu': 0.2}}}
    receipt.write_text(json.dumps(widths))
    obligations = [[{'net': 'N', 'from': {'ref': 'A', 'pad': '1'}, 'to': {'ref': 'B', 'pad': '1'}, 'widths': {'F.Cu': 0.2}}]]
    grader = FinalCopperGrader(original=original, cleanup_input=cleanup, rules=original, baseline_drc=baseline, obligations=obligations, phases=(Phase(),), width_receipt=widths, cfg=Cfg(), counted=frozenset(), open_before={'N': 1}, chosen_pours=frozenset(), width_receipt_path=receipt, invocation={'upto': None, 'only': False, 'quick': False})
    geometry = BoardGeometry(str(original), (), {}, (), (), frozenset({'N'}), {'N': NetClass('Default', 0.2, 0.2, 0.6, 0.3)}, 0.2, ())
    snapshot = tmp_path / 'pre_guard.kicad_pcb'
    snapshot.write_bytes(original.read_bytes())
    manifest = dict(grader._inputs)
    manifest[str(snapshot)] = c._hash(snapshot)
    actual = {'geometry': geometry, 'read_manifest': manifest, 'read_identity': {'original_read_path': str(original), 'read_sha256': c._hash(original), 'snapshot_path': str(snapshot), 'snapshot_sha256': c._hash(snapshot)}, 'baseline': {'counts': {'invalid_outline': 1}, 'json_sha256': c._hash(baseline)}, 'counted': grader._counted, 'open_before': grader._open_before, 'selections': {'nets': ['N'], 'obligations': obligations}, 'width_receipt': widths, 'deadline_utc': time.time() + 600}
    output = tmp_path / 'routed.kicad_pcb'
    output.write_text('actual finalized copper')
    report = Report(deepcopy(obligations), [{'name': 'signals', 'calls': 1, 'final_asked': 1}], output, tmp_path, [[{'joined': True, 'under': {}, 'violated': False}]])
    (tmp_path / 'drc_after.json').write_text('{"violations":[]}')
    return (grader, actual, report)

def register(ctx):
    grader, facts, report = ctx
    c._executor_register_original(grader, **facts)
    return (grader, facts, report)

def prepared(ctx):
    grader, facts, report = register(ctx)
    executor = object()
    ledger = c._executor_begin_calls(grader, executor)
    c._executor_record_phase(grader, ledger, executor, 0, {'name': 'signals', 'calls': 1}, calls=[('signals', 0, 'summary.json')], outputs={})
    c._executor_observe_report(grader, ledger, executor, report)
    path = report.work / 'route.json'
    path.write_text(json.dumps(report.as_dict()))
    outputs = {str(p): c._hash(p) for p in (report.routed_pcb, path, report.work / 'drc_after.json')}
    return (grader, facts, report, executor, ledger, path, outputs)

def completed(ctx):
    grader, facts, report, executor, ledger, path, outputs = prepared(ctx)
    token = c._executor_seal_completed(grader, ledger, executor, report, report_json=path, outputs=outputs)
    return (grader, facts, report, ledger, token)

def test_public_constructor_binding_template_and_bind_execution_do_not_mint(context):
    grader, facts, report = context
    for modify in (lambda: None, lambda: grader.bind_execution(report)):
        modify()
        descriptor = grader.binding()
        assert descriptor['contract_sha256']
        with pytest.raises(c.CustodyUnavailable):
            c.original_snapshot(grader)
        for forged in (descriptor, report, object(), {'completed': True}, c._digest(descriptor)):
            with pytest.raises(c.CustodyUnavailable):
                c.completed_snapshot(grader, forged)

def test_constructor_supplied_template_cannot_mint(context):
    grader, facts, report = context
    grader._template = deepcopy(report)
    with pytest.raises(c.CustodyUnavailable):
        c.original_snapshot(grader)

def test_original_is_typed_detached_deep_snapshot(context):
    grader, facts, report = register(context)
    a = c.original_snapshot(grader)
    assert type(a['geometry']) is BoardGeometry
    facts['geometry'].netclasses['N'] = NetClass('Changed', 0.9, 0.9, 1, 0.5)
    facts['selections']['nets'].append('forged')
    facts['width_receipt']['by_net']['N']['F.Cu'] = 1.5
    a['geometry'].netclasses.clear()
    a['original_facts']['selections']['nets'].clear()
    a['read_manifest'].clear()
    b = c.original_snapshot(grader)
    assert b['geometry'].netclasses['N'].track_width == 0.2
    assert b['original_facts']['selections']['nets'] == ['N']
    assert b['original_facts']['width_receipt']['by_net']['N']['F.Cu'] == 0.2

def test_registration_rejects_json_geometry_and_stale_read_manifest(context):
    grader, facts, report = context
    bad = dict(facts, geometry={'path': facts['geometry'].path})
    with pytest.raises(c.CustodyUnavailable, match='typed_original'):
        c._executor_register_original(grader, **bad)
    Path(facts['geometry'].path).write_text('changed after original read')
    with pytest.raises(c.CustodyUnavailable, match='read_file_changed'):
        c._executor_register_original(grader, **facts)

@pytest.mark.parametrize('field', ('_open_before', '_counted', '_obligations', '_widths', '_semantic_contract', '_template'))
def test_mutable_private_original_fingerprint_rejects_tampering(context, field):
    grader, _, report = register(context)
    setattr(grader, field, {'changed': True})
    with pytest.raises(c.CustodyUnavailable, match='private_context_changed'):
        c.original_snapshot(grader)

def test_original_file_addition_or_mutation_refused(context):
    grader, _, _ = register(context)
    grader._rules.with_suffix('.kicad_dru').write_text('new custom rule')
    with pytest.raises(c.CustodyUnavailable, match='locked_original_file_changed'):
        c.original_snapshot(grader)

@pytest.mark.parametrize('mode', ('copy', 'deepcopy', 'pickle'))
def test_private_tokens_not_copyable_or_serializable(context, mode):
    grader, _, report, ledger, token = completed(context)
    for value in (ledger, token):
        with pytest.raises(c.CustodyUnavailable):
            {'copy': copy, 'deepcopy': deepcopy, 'pickle': pickle.dumps}[mode](value)

def test_completion_exact_identity_no_public_token_or_report_substitution(context):
    grader, _, report, ledger, token = completed(context)
    for fake in (object(), {'report_sha': token.report_sha}, token.report_sha):
        with pytest.raises(c.CustodyUnavailable):
            c.completed_snapshot(grader, fake)
    with pytest.raises(c.CustodyUnavailable):
        c._executor_seal_completed(grader, ledger, ledger.executor, report, report_json=report.work / 'route.json', outputs={})
    got = c.completed_snapshot(grader, token)
    assert got['report'].valid is False
    got['report'].phases.clear()
    got['original']['geometry'].netclasses.clear()
    assert len(c.completed_snapshot(grader, token)['report'].phases) == 1

def test_copy_grader_and_cross_context_never_inherit_authority(context, tmp_path):
    grader, _, report, ledger, token = completed(context)
    for other in (copy(grader), deepcopy(grader)):
        with pytest.raises(c.CustodyUnavailable):
            c.original_snapshot(other)
        with pytest.raises(c.CustodyUnavailable):
            c.completed_snapshot(other, token)

    class Impostor:

        def __eq__(self, other):
            return True

        def __hash__(self):
            return hash(grader)
    with pytest.raises(c.CustodyUnavailable):
        c.original_snapshot(Impostor())

def test_completion_output_mutation_refuses_export(context):
    grader, _, report, ledger, token = completed(context)
    report.routed_pcb.write_text('modified')
    with pytest.raises(c.CustodyUnavailable, match='completed_output_changed'):
        c.completed_snapshot(grader, token)

def test_duplicate_original_registration_refused(context):
    grader, facts, _ = register(context)
    with pytest.raises(c.CustodyUnavailable):
        c._executor_register_original(grader, **facts)

def test_module_import_does_not_load_kicad_or_native():
    completed = subprocess.run([sys.executable, '-c', "import sys; from placemat.kicad import final_custody; assert 'pcbnew' not in sys.modules and '_pcbnew' not in sys.modules; assert not any(n.startswith('placemat_native') for n in sys.modules)"], capture_output=True, text=True, timeout=5)
    assert completed.returncode == 0, completed.stderr

def test_worker_geometry_fingerprint_ignores_only_read_copy_path(context):
    from dataclasses import replace
    grader, facts, _ = register(context)
    geometry = facts['geometry']
    copy_path = replace(geometry, path='/owned/worker/original.kicad_pcb')
    assert c.geometry_fingerprint(copy_path) == c.geometry_fingerprint(geometry)
    for changed in (replace(geometry, default_clearance=0.1), replace(geometry, pin_names={'U1': {'1': 'changed'}}), replace(geometry, layer_types={'F.Cu': 'power'}), replace(geometry, copper_mm={'F.Cu': 0.02}), replace(geometry, min_track_width=0.1)):
        assert c.geometry_fingerprint(changed) != c.geometry_fingerprint(geometry)
    record = c.geometry_record(geometry)
    json.dumps(record, allow_nan=False)
    assert set(record['typed_geometry']['fields']) == {f.name for f in __import__('dataclasses').fields(geometry)} - {'path'}
    with pytest.raises(c.CustodyUnavailable):
        c.original_snapshot(record)

@pytest.mark.parametrize('field', ('counted', 'open_before', 'width_receipt'))
def test_executor_registered_actual_facts_must_match_retained_grader(context, field):
    grader, facts, _ = context
    bad = dict(facts)
    bad[field] = {'forged': 1}
    with pytest.raises(c.CustodyUnavailable, match='original_facts_mismatch'):
        c._executor_register_original(grader, **bad)

def test_full_manifest_cannot_omit_baseline_or_source_companions(context):
    grader, facts, _ = context
    for omitted in (str(grader._baseline), str(grader._rules.with_suffix('.kicad_pro')), str(grader._receipt_path)):
        manifest = dict(facts['read_manifest'])
        manifest.pop(omitted)
        with pytest.raises(c.CustodyUnavailable, match='manifest_not_full'):
            c._executor_register_original(grader, **dict(facts, read_manifest=manifest))

def test_changed_completed_diagnostics_refuse_export(context):
    grader, _, report, ledger, token = completed(context)
    grader._template.phases[0]['final_asked'] = 99
    with pytest.raises(c.CustodyUnavailable, match='private_context_changed'):
        c.completed_snapshot(grader, token)

def test_geometry_record_preserves_ordered_intent_arrays(context):
    from dataclasses import replace
    geometry = context[1]['geometry']
    a = replace(geometry, outline=(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),))
    b = replace(geometry, outline=(((1.0, 0.0), (0.0, 0.0), (1.0, 1.0)),))
    assert c.geometry_fingerprint(a) != c.geometry_fingerprint(b)
    a = replace(a, nets=frozenset(['A', 'B']))
    b = replace(a, nets=frozenset(['B', 'A']))
    assert c.geometry_fingerprint(a) == c.geometry_fingerprint(b)

def test_actual_phase_ledger_is_minimal_and_refuses_incomplete_or_wrong_executor(context):
    grader, _, report = register(context)
    executor = object()
    ledger = c._executor_begin_calls(grader, executor)
    with pytest.raises(c.CustodyUnavailable):
        c._executor_begin_calls(grader, executor)
    with pytest.raises(c.CustodyUnavailable):
        c._executor_record_phase(grader, ledger, object(), 0, {'name': 'signals'}, calls=[], outputs={})
    with pytest.raises(c.CustodyUnavailable):
        c._executor_record_phase(grader, ledger, executor, 1, {'name': 'signals'}, calls=[], outputs={})
    with pytest.raises(c.CustodyUnavailable):
        c._executor_observe_report(grader, ledger, executor, report)
    c._executor_record_phase(grader, ledger, executor, 0, {'name': 'signals', 'calls': 1}, calls=['actual call'], outputs={})
    with pytest.raises(c.CustodyUnavailable):
        c._executor_record_phase(grader, ledger, executor, 0, {'name': 'signals'}, calls=[], outputs={})

def test_bad_output_phase_record_is_transactional(context):
    grader, _, report = register(context)
    executor = object()
    ledger = c._executor_begin_calls(grader, executor)
    with pytest.raises(c.CustodyUnavailable):
        c._executor_record_phase(grader, ledger, executor, 0, {'name': 'signals'}, calls=[], outputs={str(report.routed_pcb): '0' * 64})
    assert ledger.phases == [] and ledger.outputs == {}

@pytest.mark.parametrize('changed', ('copied', 'quick', 'asked', 'final_judged', 'phase_asked', 'artifact', 'wrong_executor'))
def test_incomplete_or_copied_actual_full_report_cannot_seal(context, changed):
    grader, _, report, executor, ledger, path, outputs = prepared(context)
    if changed == 'copied':
        report = deepcopy(report)
    if changed == 'quick':
        report.quick = True
    if changed == 'asked':
        report.asked = []
    if changed == 'final_judged':
        report.final_judged = []
    if changed == 'phase_asked':
        report.phases[0]['final_asked'] = 999
    if changed == 'artifact':
        path.write_text('{"partial":true}')
        outputs[str(path)] = c._hash(path)
    if changed == 'wrong_executor':
        executor = object()
    with pytest.raises(c.CustodyUnavailable):
        c._executor_seal_completed(grader, ledger, executor, report, report_json=path, outputs=outputs)
    with pytest.raises(c.CustodyUnavailable):
        c.require_completed(grader)

def test_export_requires_real_completion_and_detaches_json_records(context):
    grader, _, report, executor, ledger, path, outputs = prepared(context)
    original = c.require_original(grader)
    with pytest.raises(c.CustodyUnavailable):
        c.require_completed(grader)
    token = c._executor_seal_completed(grader, ledger, executor, report, report_json=path, outputs=outputs)
    record = c.require_completed(grader)
    json.dumps(record, allow_nan=False)
    assert record['original'] == original
    assert record['completed']['status'] == 'completed'
    assert {'asked', 'final_judged'} <= set(record['completed']['report']['fields'])
    record['original']['read_manifest'].clear()
    record['completed']['output_files'].clear()
    assert c.require_completed(grader, token)['completed']['output_files']
    for forged in (record, deepcopy(report), record['completed']['report_sha256']):
        with pytest.raises(c.CustodyUnavailable):
            c.require_completed(grader, forged)

def test_deadline_expiry_withholds_original_and_completed_export(context, monkeypatch):
    grader, facts, report, ledger, token = completed(context)
    monkeypatch.setattr(c.time, 'time', lambda: facts['deadline_utc'] + 1)
    with pytest.raises(c.CustodyUnavailable, match='deadline_expired'):
        c.original_snapshot(grader)
    with pytest.raises(c.CustodyUnavailable, match='deadline_expired'):
        c.require_completed(grader, token)

def test_wrong_call_token_same_source_files_cannot_seal_second_executor(context):
    first, facts, report, ledger, token = completed(context)
    second = copy(first)
    second._template = None
    c._executor_register_original(second, **facts)
    executor = object()
    other = c._executor_begin_calls(second, executor)
    with pytest.raises(c.CustodyUnavailable):
        c._executor_record_phase(second, ledger, executor, 0, {'name': 'signals'}, calls=[], outputs={})
    with pytest.raises(c.CustodyUnavailable):
        c.require_completed(second, token)
    with pytest.raises(c.CustodyUnavailable):
        c._executor_seal_completed(second, other, executor, deepcopy(report), report_json=report.work / 'route.json', outputs={})

def test_worker_record_preserves_physical_pad_multiplicity_pose_and_copper(context):
    from dataclasses import replace
    from placemat.board_geometry import Footprint, PadGeom, CopperItem
    from placemat.values import Box, Location, Face, CopperLayer
    b = Box(0.0, 0.0, 1.0, 1.0)
    poly = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    pad = PadGeom('A', '/A', '1', 'N', frozenset({CopperLayer.F}), (poly,), b, False)
    fp = Footprint('A', '/A', None, 'R', Location(0.5, 0.5), 0.0, Face.FRONT, b, b, b, (pad, pad), lib_id='lib:R')
    copper = CopperItem('track', 'N', frozenset({CopperLayer.F}), (poly,), b, width_mm=0.2, anchors=((0.0, 0.0), (1.0, 1.0)))
    geometry = replace(context[1]['geometry'], footprints=(fp,), copper=(copper,))
    clone = deepcopy(geometry)
    assert c.geometry_fingerprint(clone) == c.geometry_fingerprint(geometry)
    for changed in (replace(geometry, footprints=(replace(fp, pads=(pad,)),)), replace(geometry, footprints=(replace(fp, rotation=90.0),)), replace(geometry, copper=(replace(copper, width_mm=0.1),)), replace(geometry, footprints=(replace(fp, net_tie_groups=(('1', '2'),)),))):
        assert c.geometry_fingerprint(changed) != c.geometry_fingerprint(geometry)

def test_pre_guard_read_identity_survives_guarded_input_but_snapshot_is_immutable(context):
    grader, facts, report = context
    original = Path(facts['geometry'].path)
    original.write_text('guarded cleanup terrain')
    grader._inputs[str(original)] = c._hash(original)
    facts['read_manifest'][str(original)] = c._hash(original)
    grader, facts, report, ledger, token = completed(context)
    got = c.require_completed(grader, token)['original']
    assert got['read_identity']['read_sha256'] != got['read_manifest'][str(original)]
    assert got['read_identity']['original_read_path'] == facts['geometry'].path
    Path(got['read_identity']['snapshot_path']).write_text('corrupted snapshot')
    with pytest.raises(c.CustodyUnavailable, match='locked_original_file_changed'):
        c.require_completed(grader, token)

@pytest.mark.parametrize('change', ('path', 'hash', 'same_path'))
def test_read_identity_must_match_actual_read_and_separate_snapshot(context, change):
    grader, facts, report = context
    if change == 'path':
        facts['read_identity']['original_read_path'] += 'other'
    elif change == 'hash':
        facts['read_identity']['snapshot_sha256'] = '0' * 64
    else:
        facts['read_identity']['snapshot_path'] = facts['read_identity']['original_read_path']
    with pytest.raises(c.CustodyUnavailable):
        c._executor_register_original(grader, **facts)


@pytest.mark.parametrize('offset', [-30, 30])
def test_worker_export_and_execution_cannot_change_private_deadline(context, monkeypatch, offset):
    from placemat.kicad.final_worker_protocol import export
    from placemat.kicad import final_owned_worker
    from placemat.kicad.final_call import ProofUnavailable
    grader, facts, report, ledger, token = completed(context)
    deadline = facts['deadline_utc'] + offset
    destination = report.work / 'candidate'
    monkeypatch.setattr(final_owned_worker, '_execute',
                        lambda *args: pytest.fail('changed deadline must refuse before launch'))
    with pytest.raises(ProofUnavailable, match='deadline_context_mismatch'):
        export(grader, report.routed_pcb, destination, deadline_utc=deadline)
    with pytest.raises(ProofUnavailable, match='deadline_context_mismatch'):
        final_owned_worker.grade_owned(grader, {}, {}, deadline_utc=deadline)
    assert not destination.exists()
    assert not destination.with_name('candidate.worker').exists()
