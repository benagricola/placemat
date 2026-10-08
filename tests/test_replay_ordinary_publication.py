"""Ordinary comparator outcome never calls strict authority publication/rank."""
import json
from types import SimpleNamespace
import pytest
from tests.test_replay_publication import publication
from tests.test_replay_comparison import pair
from placemat.kicad.final_call import ProofUnavailable
from placemat.kicad import replay_comparison as original_comparison
from placemat.kicad import replay_ordinary_publication as ordinary_publication


def test_unknown_strict_grade_does_not_become_ordinary_certificate(publication,tmp_path,monkeypatch):
    authority,candidate,_=publication
    grader=SimpleNamespace(_obligations=json.dumps(candidate.physical.report.asked),_phases=[SimpleNamespace(selector='rest',width=None)])
    authority._grader=grader
    authority.compare=lambda *a:pytest.fail('ordinary choice called strict rank')
    authority.publish=lambda *a:pytest.fail('ordinary choice called strict publication')
    monkeypatch.setattr(original_comparison.final_custody,'require_completed',lambda g:None)
    budget=SimpleNamespace(executor=object(),grader=grader,_check=lambda e:None)
    dest=tmp_path/'ordinary-published'
    packet=ordinary_publication.publish_selected(budget,authority,candidate,candidate,dest,
                          {'selected':'pocket','ordinary_comparison_only':True,'grades':{'known':False}})
    assert packet.verify().routed_pcb==dest/'board.kicad_pcb'
    assert json.loads((dest/'ordinary-selection.json').read_text())['strict_adoption'] is False
    (dest/'ordinary-selection.json').write_text('{}')
    with pytest.raises(ProofUnavailable,match='published_bundle_changed'):packet.verify()


def test_current_trade_refuses_before_ordinary_copy(pair,tmp_path):
    authority,grader,result,_,ranked=pair
    old=result([[True,False],[False]]);new=result([[False,True],[True]])
    source=tmp_path/'grade';source.mkdir();new.evidence=source/'evidence.json';new.evidence.write_text('{}')
    budget=SimpleNamespace(executor=object(),grader=grader,_check=lambda e:None)
    dest=tmp_path/'published'
    with pytest.raises(ProofUnavailable,match='current_join_lost'):
        ordinary_publication.publish_selected(budget,authority,old,new,dest,
                                             {'selected':'pocket','ordinary_comparison_only':True})
    assert not dest.exists() and not ranked
