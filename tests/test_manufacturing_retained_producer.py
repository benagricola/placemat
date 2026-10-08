"""Real retain, grader, original registry and bind_physical; selector verifier
and critical encoder are controlled boundaries, not native/selector proof.
"""
import json
import time
from copy import deepcopy
import pytest
from placemat.kicad.manufacturing_inventory import retained_original, InventoryUnavailable
from placemat.final_authority import retain, AuthorityRefused
from placemat.kicad import final_custody as custody
from placemat.kicad.final_route import FinalCopperGrader
from placemat.board_geometry import BoardGeometry
from tests.test_pinmap_common import scene

@pytest.fixture
def bound(tmp_path, monkeypatch):
    board,plan,_,_=scene()
    source=tmp_path/'original.kicad_pcb'
    source.write_text('(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" mixed)))')
    source.with_suffix('.kicad_pro').write_text('{}')
    cleanup=tmp_path/'clean.kicad_pcb';cleanup.write_bytes(source.read_bytes())
    baseline=tmp_path/'baseline.json';baseline.write_text('{}')
    receipt=tmp_path/'width.json';receipt.write_text('{}')
    deadline=time.time()+60
    factory=retain(board,plan,{},source,invocation={},deadline_utc=deadline)
    grader=FinalCopperGrader(original=source,cleanup_input=cleanup,rules=source,baseline_drc=baseline,
        obligations=[],phases=(),width_receipt={},cfg=board.settings,counted=frozenset(),open_before={},
        chosen_pours=frozenset(),width_receipt_path=receipt,invocation={})
    geometry=BoardGeometry(str(source),(),{},(),(),frozenset(),{},.25,())
    snapshot=tmp_path/'snapshot.kicad_pcb';snapshot.write_bytes(source.read_bytes())
    manifest=dict(grader._inputs);manifest[str(snapshot)]=custody._hash(snapshot)
    custody._executor_register_original(grader,geometry=geometry,read_manifest=manifest,
        read_identity={'original_read_path':str(source),'read_sha256':custody._hash(source),
                       'snapshot_path':str(snapshot),'snapshot_sha256':custody._hash(snapshot)},
        baseline={'counts':{},'json_sha256':custody._hash(baseline)},counted=frozenset(),open_before={},
        selections={'nets':[],'obligations':[]},width_receipt={},deadline_utc=deadline)
    import placemat.original_binding as selector
    import placemat.final_check_context as critical
    monkeypatch.setattr(selector,'verify_original_binding',lambda *a:None)
    monkeypatch.setattr(critical,'encode',lambda *a,**kw:{'controlled_critical_boundary':True})
    factory.bind_physical(grader)
    return factory


def test_real_retained_registered_bound_producer(bound):
    before=deepcopy(custody.require_original(bound._grader))
    result=retained_original(bound)
    assert result['custody_sha256']==before['private_context_sha256']
    assert result['deadline_utc']==before['deadline_utc']
    assert result['original']['via_uuid_multiset']==[]
    assert result['original']['copper_layers']==['F.Cu','B.Cu']
    assert result['original']['files']['.kicad_dru'] is None
    assert result['comparison_authority'] is False
    assert custody.require_original(bound._grader)==before

@pytest.mark.parametrize('which',['source','project','absence','dangling','snapshot'])
def test_retained_original_mutation_refuses(bound,which):
    if which=='source':bound._source.write_text('changed')
    elif which=='project':bound._source.with_suffix('.kicad_pro').write_text('changed')
    elif which=='absence':bound._source.with_suffix('.kicad_dru').write_text('new rules')
    elif which=='dangling':bound._source.with_suffix('.kicad_dru').symlink_to(bound._source.parent/'missing-rules')
    else:
        original=custody.require_original(bound._grader)
        from pathlib import Path
        Path(original['read_identity']['snapshot_path']).write_text('changed')
    with pytest.raises((InventoryUnavailable,AuthorityRefused,custody.CustodyUnavailable)):
        retained_original(bound)

def test_public_record_cannot_supply_private_original(bound):
    with pytest.raises(InventoryUnavailable):retained_original(custody.require_original(bound._grader))
