"""Real hook/custody/budget lifecycle, controlled factory and router/native work."""
import json,sys,os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from placemat.kicad import final_custody as custody,issued_calls,phase_run
from placemat.kicad.final_call import ProofUnavailable,file_hash
from tests.test_final_custody import context


def completed_hook(context,monkeypatch,observer_mode='bound'):
    from placemat.kicad import replay_backend,replay_capability as owned_capability,replay_ordinary_completion as ordinary_completed
    from placemat.kicad import final_execution as module
    if not os.environ.get('KRT_DIR'):
        pytest.skip('$KRT_DIR is required for the real recorder helper')
    if not (Path(os.environ['KRT_DIR'])/'py_router/final_escape.py').is_file():
        pytest.skip('$KRT_DIR lacks py_router/final_escape.py')
    original,facts,report=context
    hook=object.__new__(module.FinalExecution)
    hook.active=True;hook.work=report.work;hook.refusals=(ProofUnavailable,)
    hook.geometry=deepcopy(facts['geometry']);hook.read_identity=deepcopy(facts['read_identity']);hook.deadline=facts['deadline_utc'];hook.executor=object()
    facts['width_receipt']={'sources':{'route.py':'b'*64},'policies':[
        {'name':'signals','by_net':{'N':{'status':'unknown' if observer_mode=='nominal_unknown' else 'known','widths':{'F.Cu':.2}}}}]}
    bound=[]
    class Factory:
        def bind_physical(self,g):
            self._grader=g;bound.append(g)
            from placemat.kicad.final_call import StandingAuthority
            self._authority=SimpleNamespace(descriptor=lambda:StandingAuthority('c'*64,'d'*64,'e'*64,'f'*64))
    hook.factory=Factory()
    (hook.work/'width_policy.json').write_text(json.dumps(facts['width_receipt']))
    hook.prepare(original=original._original,cleanup_input=original._cleanup_input,baseline_drc=original._baseline,
                 obligations=report.asked,phases=original._phases,width_receipt=facts['width_receipt'],cfg=original._cfg,
                 counted=original._counted,open_before=original._open_before,chosen_pours=original._chosen_pours,
                 invocation=dict(original._semantic_contract['invocation'],capture={'path':None,'sha256':None}),selections=facts['selections'])
    assert hook.active and hook.factory._route_execution is hook and bound==[hook.grader]
    hook.plan_calls(phase=0,calls=[phase_run.Call('nets',('N',)),phase_run.Call('rest',('N',))],layers=['F.Cu'],input_board=original._original)
    ctx=SimpleNamespace(router_dir=hook.work,script='route.py',rpy=sys.executable,env={},cfg=original._cfg,layers=['F.Cu'],clearances_file=None,execution=hook)
    monkeypatch.setattr(module,'replace',lambda value,**kw:SimpleNamespace(**(vars(value)|kw)))
    monkeypatch.setattr(replay_backend,'_original_effective',lambda *a,**k:None)
    def capability(c,deadline,work):
        work.mkdir()
        (work/'stdout.json').write_text(json.dumps({'schema':1,'modules':{'route.py':True},
             'flags':{'route.py':[] if observer_mode=='unsupported' else ['--final-call-proof','--candidate-artifacts']}}))
        receipt={'controlled':True,'stdout_sha256':file_hash(work/'stdout.json')}
        if observer_mode=='capability_changed':(work/'stdout.json').write_text('{}')
        return receipt
    monkeypatch.setattr(owned_capability,'query',capability)
    monkeypatch.setattr(replay_backend,'_runtime',lambda c,command:({},[],command[2:]))
    processes=[];summaries=[]
    for index in (0,1):
        output=hook.work/('call%d.kicad_pcb'%index);summary=hook.work/('call%d-summary.json'%index)
        cmd=[sys.executable,str(hook.work/'route.py'),str(original._original),str(output),'--nets','N','--layers','F.Cu','--json-out',str(summary)]
        issued=dict(phase=0,call=index,wave=0,kind='single',command=cmd,source=original._original,input_board=original._original,
                    output_board=output,summary=summary,layers=['F.Cu'],nets=['N'],tasks=[],constraint_files=(),environment={})
        actual_ctx,token=hook.issue_single(ctx,**issued)
        assert token is not None
        if index==0:
            assert 'KRT_INTERNAL_ORDINARY_GRADE_REQUEST' not in actual_ctx.env
            assert 'KRT_INTERNAL_FINAL_CALL_CONTEXT' not in actual_ctx.env
        else:
            assert actual_ctx.env['KRT_INTERNAL_ORDINARY_GRADE_REQUEST']==str(hook.work/'ordinary-grade-original.json')
            assert hook.replay_budget.states==['unused','unused']
            if observer_mode in ('bound','context_changed','log_changed'):
                captured=json.loads(Path(actual_ctx.env['KRT_INTERNAL_FINAL_CALL_CONTEXT']).read_bytes())
                assert captured['candidate']=='legacy' and captured['failures']==[]
                assert captured['proof']['call']['routing_flags']==['--nets','N','--layers','F.Cu']
                assert captured['proof']['copper_work']==[
                    {'id':'p0-c0-w0','kind':'single'},{'id':'p0-c1-w0','kind':'single'}]
                assert captured['proof']['deadline_utc']==hook.deadline
                assert token.record['execution_transport']['KRT_INTERNAL_FINAL_CALL_CONTEXT']==str(hook.work/'nominal-original-context.json')
            else:
                assert 'KRT_INTERNAL_FINAL_CALL_CONTEXT' not in actual_ctx.env
                assert hook.nominal_refusal
        def complete_call(c,command,log,what,source,board,t,run=None):
            code=run(command,log,c) if run else 0
            processes.append(index)
            board=Path(board);board.write_text('controlled raw copper');summary.write_text('{"regrade":{},"open_single":["N"]}')
            issued_calls._executor_raw_result(hook.grader,hook.ledger,hook.executor,t,returncode=code,snapshot_dir=hook.work/('raw%d'%index))
            board.with_suffix('.kicad_pro').write_bytes(original._original.with_suffix('.kicad_pro').read_bytes())
            issued_calls._executor_restored_result(hook.grader,hook.ledger,hook.executor,t)
            return board
        monkeypatch.setattr(phase_run,'_completed_single_call',complete_call)
        def backend(record,deadline,c,log,validate,actual_completed):
            validate();output.write_text('controlled raw copper');summary.write_text('{"regrade":{},"open_single":["N"]}')
            if index==1 and observer_mode in ('bound','context_changed','log_changed'):
                import contextlib,io,importlib.util
                monkeypatch.syspath_prepend(str(Path(os.environ['KRT_DIR'])/'py_router'))
                import final_escape as escape
                transport=json.loads(Path(c.env['KRT_INTERNAL_FINAL_CALL_CONTEXT']).read_bytes())
                recorder=escape.FailureRecorder(transport['proof'],transport['identity'],
                                               evidence_file=transport['evidence_file'])
                stream=io.StringIO()
                with contextlib.redirect_stdout(stream):recorder.finish()
                Path(log).write_text(stream.getvalue())
                if observer_mode=='log_changed':
                    original_read=Path.read_bytes
                    touched=[]
                    def read_then_change(path):
                        raw=original_read(path)
                        if path==Path(log) and not touched:
                            touched.append(True);path.write_bytes(raw+b'changed after parse')
                        return raw
                    monkeypatch.setattr(Path,'read_bytes',read_then_change)
                if observer_mode=='context_changed':
                    path=Path(c.env['KRT_INTERNAL_FINAL_CALL_CONTEXT']);path.write_bytes(path.read_bytes()+b' ')
            actual_completed({'returncode':0,'command':record['command'],'deadline_utc':deadline,
                              'files':{str(output):file_hash(output),str(summary):file_hash(summary)}})
            raise ProofUnavailable('replay_backend_policy_malformed')
        monkeypatch.setattr(ordinary_completed.backend,'_run_record',backend)
        hook.execute_single(actual_ctx,cmd,hook.work/'log','ordinary',original._original,output,token)
        summaries.append(('signals',index,summary))
    report.routed_pcb=output;report.phases[0]['calls']=2
    hook.phase(0,report.phases[0],phase_run.Routed(output,1.,1,summaries=summaries))
    (hook.work/'route.json').write_text(json.dumps(report.as_dict()))
    hook.complete(report)
    assert hook.active and processes==[0,1] and hook.replay_budget.states==['completed','unused']
    assert custody.require_completed(hook.grader)['completed']['status']=='completed'
    assert hook.backend_eligibility['policy_proved'] is False

    if observer_mode=='bound':
        assert hook.nominal_observation['detached_files']
        assert all(Path(path).is_file() for path in hook.nominal_observation['detached_files'])
        assert json.loads(Path(hook.nominal_observation['evidence']).read_bytes())['nominal_taps']==[]
    elif observer_mode=='context_changed':
        assert hook.nominal_refusal[0]['code']=='nominal_observer_context_changed'
        assert 'detached_files' not in hook.nominal_observation

    elif observer_mode=='log_changed':
        assert hook.nominal_refusal[0]['code']=='issued_call_snapshot_changed'
        assert 'detached_files' not in hook.nominal_observation

    return hook, report

