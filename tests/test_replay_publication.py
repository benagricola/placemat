"""Controlled publication custody; actual RouteReport codec, no board proof."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
import pytest
from placemat.kicad.route import RouteReport
from placemat.kicad.final_call import ProofUnavailable
from placemat.kicad import replay_publication as adopted_report

@pytest.fixture
def publication(tmp_path):
    source=tmp_path/'grade';source.mkdir()
    for name in ('board.kicad_pcb','board.kicad_pro','board.kicad_dru','drc_after.json','route.json','full-standing.json'):
        (source/name).write_text('original '+name)
    report=RouteReport(True,1.,1.,1,0,{},[],[],['F.Cu'],.1,'controlled',{},source/'board.kicad_pcb',source/'historic.log',source)
    report.asked=[[{'net':'N'}]];report.final_judged=[[{'joined':True}]]
    candidate=SimpleNamespace(physical=SimpleNamespace(report=report),evidence=source/'full-standing.json')
    authority=SimpleNamespace(verify=lambda actual: actual is candidate or pytest.fail('wrong candidate'))
    published=tmp_path/'published';shutil.copytree(source,published)
    return authority,candidate,published

@pytest.mark.parametrize('name',['board.kicad_pro','board.kicad_dru','drc_after.json','route.json','full-standing.json'])
def test_unchanged_pcb_does_not_hide_changed_sidecar_or_report(publication,name):
    authority,candidate,published=publication
    owned=adopted_report.detached(authority,candidate,published)
    (published/name).write_text('tampered')
    with pytest.raises(ProofUnavailable,match='published_bundle_changed'):
        owned.verify()
    assert candidate.physical.report.routed_pcb.parent!=published


def test_caller_record_relocates_pointers_without_rewriting_minted_evidence(publication):
    authority,candidate,published=publication
    before=(published/'route.json').read_bytes()
    owned=adopted_report.detached(authority,candidate,published)
    report=owned.verify()
    assert report.routed_pcb==published/'board.kicad_pcb'
    assert json.loads((published/'caller-route.json').read_bytes())['routed_pcb']==str(report.routed_pcb)
    assert (published/'route.json').read_bytes()==before
    assert report is not candidate.physical.report
    report.final_judged[0][0]['joined']=False
    with pytest.raises(ProofUnavailable,match='published_bundle_changed'):
        owned.verify()
