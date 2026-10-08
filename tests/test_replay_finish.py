"""Actual finish boundary separates optional attribution from original custody."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from placemat.kicad import replay_finish as finish
from placemat.kicad.final_call import ProofUnavailable,file_hash,record_digest


@pytest.fixture
def scenario(tmp_path,monkeypatch):
    import shutil
    helper=tmp_path/'route_candidates.py'
    shutil.copyfile(Path(__file__).parent/'fixtures/replay_backend/ordinary_grade.py',helper)
    token=object();ctx=SimpleNamespace(router_dir=tmp_path,script='route.py')
    grader=object();budget=SimpleNamespace(grader=grader,executor=object(),ledger=object(),states=['completed','unused'],_check=lambda e:None)
    capability={'sources':{str(helper):file_hash(helper)}}
    owner=SimpleNamespace(active=True,replay_budget=budget,final_call=token,contexts_for=lambda b:{token:ctx},
                          backend_capability=capability,backend_capability_sha=record_digest(capability),
                          backend_eligibility={'policy_proved':True})
    authority=SimpleNamespace(_grader=grader)
    factory=SimpleNamespace(_route_execution=owner,completed_authority=lambda:authority);owner.factory=factory
    monkeypatch.setattr(finish.issued_calls,'completed_record',lambda *a:{'raw':{'summary':{'regrade':{},'open_single':['N']}}})
    return factory,budget,owner,object()


@pytest.mark.parametrize('code',['replay_static_evidence_unavailable','replay_static_evidence_malformed','replay_hit_board_unproved','replay_generated_cohort_unavailable'])
def test_optional_attribution_refusal_preserves_original_pocket_slot(scenario,tmp_path,monkeypatch,code):
    factory,budget,owner,report=scenario;calls=[]
    def cohort(*a):raise ProofUnavailable(code)
    monkeypatch.setattr(finish.coordinator,'continue_original',cohort)
    def pocket(*a):
        assert budget.states==['completed','unused']
        calls.append('original pocket');budget.states[1]='completed'
        return None,{}, {'selection':{'selected':'legacy'}}
    monkeypatch.setattr(finish.sole_pocket,'run',pocket)
    assert finish.finish(factory,report,tmp_path/'finish')==(report,None)
    assert calls==['original pocket']


@pytest.mark.parametrize('code',['replay_original_call_changed','replay_deadline_expired','replay_failed_scope_unproved'])
def test_mandatory_custody_scope_or_deadline_failure_never_falls_back(scenario,tmp_path,monkeypatch,code):
    factory,budget,owner,report=scenario
    def cohort(*a):raise ProofUnavailable(code)
    monkeypatch.setattr(finish.coordinator,'continue_original',cohort)
    monkeypatch.setattr(finish.sole_pocket,'run',lambda *a:pytest.fail('mandatory failure reopened ordinary slot'))
    with pytest.raises(ProofUnavailable):finish.finish(factory,report,tmp_path/'finish')
    assert budget.states==['completed','unused']


def test_optional_attribution_refusal_after_issue_cannot_add_third_attempt(scenario,tmp_path,monkeypatch):
    factory,budget,owner,report=scenario
    def cohort(*a):budget.states[1]='failed';raise ProofUnavailable('replay_static_evidence_malformed')
    monkeypatch.setattr(finish.coordinator,'continue_original',cohort)
    monkeypatch.setattr(finish.sole_pocket,'run',lambda *a:pytest.fail('third attempt'))
    with pytest.raises(ProofUnavailable):finish.finish(factory,report,tmp_path/'finish')
