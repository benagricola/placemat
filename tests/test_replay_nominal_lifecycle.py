"""Actual owner/slot/caller lifecycle with explicitly controlled boundaries."""
import json,os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests.test_final_custody import context
from tests.nominal_lifecycle import completed_hook
from placemat.kicad.final_call import ProofUnavailable,file_hash

def test_actual_issue_execute_complete_finish_publication(context,monkeypatch,tmp_path):
    """Actual ownership/slot/caller code; controlled factory, native and backend.

    Nominal eligibility and physical grading remain controlled here; their
    independent codecs/worker tests do not turn this into native route proof.
    """
    import shutil
    from placemat.kicad import replay_finish,replay_nominal,replay_pocket
    from placemat.kicad.final_call import record_digest
    from placemat.kicad.route import RouteReport
    hook,original_report=completed_hook(context,monkeypatch)
    monkeypatch.setattr(replay_pocket,'replace',lambda value,**kw:SimpleNamespace(**(vars(value)|kw)))
    assert hook.replay_budget.states==['completed','unused']
    ctx=hook.contexts_for(hook.replay_budget)[hook.final_call]
    helper=Path(ctx.router_dir)/'route_candidates.py'
    shutil.copyfile(Path(__file__).parent/'fixtures/replay_backend/ordinary_grade.py',helper)
    hook.backend_capability['sources']={str(helper.resolve()):file_hash(helper)}
    hook.backend_capability_sha=record_digest(hook.backend_capability)
    observation=deepcopy(hook.nominal_observation)
    observation['proof']['nominal_policy']['by_net']={'N':{'F.Cu':.2}}
    observation['identity']['proof_sha256']=record_digest(observation['proof'])
    observation['failures']=[{'endpoint':{'net':'N','ref':'A','pad':'1'},
                             'nominal_geometry':{'via_size':.6,'via_drill':.3}}]
    eligible_reply=tmp_path/'controlled-eligible.json';eligible_reply.write_text('{}')
    observation.update(eligibility_reply=str(eligible_reply),eligibility_sha256=file_hash(eligible_reply))
    monkeypatch.setattr(replay_nominal,'eligible',lambda *args:observation)
    launches=[]
    def restore(budget,original,c,stage,current,given,output,work):
        work.mkdir(exist_ok=True)
        if stage=='prepare':
            given.write_bytes(Path(current).read_bytes())
            given.with_suffix('.kicad_pro').write_bytes(Path(current).with_suffix('.kicad_pro').read_bytes())
        else:
            output.with_suffix('.kicad_pro').write_bytes(given.with_suffix('.kicad_pro').read_bytes())
        return {}
    monkeypatch.setattr(replay_pocket.restore_owned,'run',restore)
    def backend(record,deadline,c,log,validate,actual_completed):
        validate();launches.append(c.env['KRT_INTERNAL_FINAL_CALL_KIND'])
        transport=json.loads(Path(c.env['KRT_INTERNAL_FINAL_CALL_CONTEXT']).read_bytes())
        assert transport['candidate']=='escape' and transport['evidence_file']!=hook.nominal_observation['evidence']
        Path(transport['evidence_file']).write_text(json.dumps({'schema':1,'seed_attempts':[
            {'endpoint':observation['failures'][0]['endpoint'],'accepted_seed':True,
             'fresh_graph_sha256':'a'*64,'result':{'success':True,'via':None,
                 'segments':[{'layer':'F.Cu','width':.2}]}}]}))
        Path(record['output']).write_text('controlled escape copper')
        Path(record['summary']).write_text('{}')
        actual_completed({'returncode':0,'files':{str(record['output']):file_hash(record['output']),
                                               str(record['summary']):file_hash(record['summary'])}})
    monkeypatch.setattr(replay_pocket.ordinary_completed.backend,'_run_record',backend)
    monkeypatch.setattr(replay_pocket.ordinary_selection,'choose',lambda *args,**kw:
        {'selected':'escape','candidate_kind':'escape','preference_candidate':'pocket','ordinary_comparison_only':True})
    minted=[]
    def regrade(raw,destination):
        destination.mkdir()
        for name in ('board.kicad_pcb','board.kicad_pro','board.kicad_dru','drc_after.json','route.json','full-standing.json'):
            (destination/name).write_text('controlled finalized '+name)
        report=RouteReport(False,1.,1.,1,0,{},[],[],['F.Cu'],.2,'controlled',{},
                           destination/'board.kicad_pcb',destination/'historical.log',destination)
        report.asked=deepcopy(original_report.asked);report.final_judged=deepcopy(original_report.final_judged)
        candidate=SimpleNamespace(physical=SimpleNamespace(report=report),evidence=destination/'full-standing.json')
        minted.append(candidate);return candidate
    def verify(candidate):assert any(candidate is value for value in minted)
    authority=SimpleNamespace(_grader=hook.grader,regrade=regrade,verify=verify)
    hook.factory.completed_authority=lambda:authority
    # The controlled phase class has no routing selector metadata; supply its
    # ordinary-rest semantics as class defaults without changing sealed fields.
    monkeypatch.setattr(type(hook.grader._phases[0]),'selector','rest',raising=False)
    monkeypatch.setattr(type(hook.grader._phases[0]),'width',None,raising=False)
    result,packet=replay_finish.finish(hook.factory,original_report,tmp_path/'finish')
    assert result is packet.verify() and result is not original_report
    assert result.routed_pcb.parent.name=='ordinary-published'
    assert launches==['escape'] and hook.replay_budget.states==['completed','completed']
    assert json.loads((result.work/'ordinary-selection.json').read_text())['strict_adoption'] is False
    assert original_report.routed_pcb.read_text()=='controlled raw copper'
    with pytest.raises(ProofUnavailable):
        replay_finish.finish(hook.factory,original_report,tmp_path/'third-finish')
    assert launches==['escape']
