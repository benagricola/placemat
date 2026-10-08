"""Actual retained factory, issuance, completion, contexts and prepare boundary.

No native reading or routing: physical critical/selector encoding and runtime
inventory are controlled boundaries. Prelaunch schema2 capsule is a controlled
producer and is validated by actual original_grade_request, not bypassed.
"""
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import json,sys,time,os
import pytest
from placemat.layout import Board
from placemat.settings import Settings
from placemat.board_geometry import BoardGeometry
from placemat.final_authority import retain
from placemat.kicad.final_route import FinalCopperGrader
from placemat.kicad.final_execution import FinalExecution
from placemat.kicad import final_custody as custody,issued_calls,replay_budget,phase_run,replay_backend
from placemat.kicad.final_call import file_hash,ProofUnavailable
from tests.test_final_custody import Phase,Report
from placemat.kicad import manufacturing_current_request as current_request
@dataclass
class Context:
    router_dir:Path
    script:str
    rpy:Path
    cfg:object
    layers:list
    env:dict
    clearances_file:object=None
    execution:object=None

@pytest.fixture
def current(tmp_path,monkeypatch):
    source=tmp_path/'original.kicad_pcb'
    source.write_text('(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (net 1 "N") (net 2 "M") (segment (start 0 0) (end 1 0) (width .2) (layer "F.Cu") (net 1 "N") (uuid "00000000-0000-0000-0000-000000000001")) (segment (start 0 1) (end 1 1) (width .2) (layer "F.Cu") (net 2 "M") (uuid "00000000-0000-0000-0000-000000000002")))')
    source.with_suffix('.kicad_pro').write_text(json.dumps({'board':{'design_settings':{'rules':{'min_via_annular_width':.05, 'min_clearance': .25}}}}))
    geometry=BoardGeometry(str(source),(),{},(),(),frozenset({'N'}),{},.25,())
    cfg=Settings();board=Board(geometry,keep_going=True,settings=cfg)
    occupancy=SimpleNamespace(items={},copper=[],pending=set(),_cell_rule_areas={},quiet_nets=set(),plane_nets=set())
    plan=SimpleNamespace(geometry=geometry,occupancy=occupancy,links=[],pushes=[],steps=[],acceptances=[])
    deadline=time.time()+120
    factory=retain(board,plan,{},source,invocation={},deadline_utc=deadline)
    owner=FinalExecution(factory,tmp_path)
    cleanup=tmp_path/'cleanup.kicad_pcb';cleanup.write_bytes(source.read_bytes())
    baseline=tmp_path/'baseline.json';baseline.write_text('{}')
    widths=tmp_path/'width.json';widths.write_text('{}')
    grader=FinalCopperGrader(original=source,cleanup_input=cleanup,rules=source,baseline_drc=baseline,
        obligations=[[]],phases=(Phase(),),width_receipt={},cfg=cfg,counted=frozenset(),open_before={},
        chosen_pours=frozenset(),width_receipt_path=widths,invocation={'upto':None,'only':False,'quick':False})
    snapshot=tmp_path/'snapshot.kicad_pcb';snapshot.write_bytes(source.read_bytes())
    manifest=dict(grader._inputs);manifest[str(snapshot)]=file_hash(snapshot)
    custody._executor_register_original(grader,geometry=geometry,read_manifest=manifest,
        read_identity={'original_read_path':str(source),'read_sha256':file_hash(source),
                       'snapshot_path':str(snapshot),'snapshot_sha256':file_hash(snapshot)},
        baseline={'counts':{},'json_sha256':file_hash(baseline)},counted=frozenset(),open_before={},
        selections={'nets':['N'],'obligations':[[]]},width_receipt={},deadline_utc=deadline)
    import placemat.original_binding as binding
    import placemat.final_check_context as critical
    monkeypatch.setattr(binding,'verify_original_binding',lambda *a:None)
    monkeypatch.setattr(critical,'encode',lambda *a,**kw:{'controlled_critical_boundary':True})
    factory.bind_physical(grader);factory._route_execution=owner
    owner.grader=grader;owner.geometry=geometry
    owner.ledger=custody._executor_begin_calls(grader,owner.executor)
    issued_calls._executor_plan(grader,owner.ledger,owner.executor,phase=0,
        calls=[phase_run.Call('nets',('N',))],layers=['F.Cu'],input_board=source)
    budget=replay_budget._executor_reserve(grader,owner.ledger,owner.executor);owner.replay_budget=budget
    root=tmp_path/'router';(root/'py_router').mkdir(parents=True);(root/'rust_router').mkdir()
    for name in ('route.py','route_execution_receipt.py','route_candidates.py'):
        (root/'py_router'/name).write_text('# controlled source identity, not executed\n')
    krt=Path(os.environ['KRT_DIR'])
    (root/'py_router/kicad_parser.py').symlink_to(krt/'py_router/kicad_parser.py')
    (root/'py_router/route_candidates.py').write_bytes((krt/'py_router/route_candidates.py').read_bytes())
    (root/'rust_router/grid_router.so').write_bytes(b'controlled native identity, not imported')
    output=tmp_path/'routed.kicad_pcb';summary=tmp_path/'summary.json';capsule=tmp_path/'capsule.json'
    ctx=Context(root,'py_router/route.py',Path(sys.executable),cfg,['F.Cu'],
        {'KRT_INTERNAL_ORDINARY_GRADE_REQUEST':str(capsule),'KRT_ROUTE_DEADLINE_UTC':str(deadline)})
    command=[sys.executable,str(root/'py_router/route.py'),str(source),str(output),'--nets','N','--layers','F.Cu','--json-out',str(summary)]
    token=issued_calls._executor_issue(grader,owner.ledger,owner.executor,phase=0,call=0,wave=0,kind='single',
        command=command,source=source,input_board=source,output_board=output,summary=summary,
        layers=['F.Cu'],nets=['N'],tasks=[],constraint_files=(),snapshot_dir=tmp_path/'issued',environment=ctx.env)
    owner.final_call=token;owner._remember_context(token,ctx)
    record=token.record
    _,required,argv=replay_backend._runtime(ctx,command)
    request={'board':str(output),'input':str(source),'summary':None,'scope':['N'],
        'manufacturing_defaults':{'clearance':.25,'size_floors':{'track_width':.2,'via_diameter':.6,'via_drill':.3,'annular':.18},
            'tier':'controlled','overrides':{},'source':'original_invocation_no_escalation'},
        'explicit_width':None,'connections':None,'power_nets':None,'power_nets_widths':None,'impedance':None,
        'clearance_unproved':False,'electrical_unproved':False,'via_size':None,'via_drill':None}
    capture={'schema':2,'argv':argv,'input_files':record['actual_input_files'],'output':str(output),'summary':str(summary),
        'nets':['N'],'layers':['F.Cu'],'deadline_utc':deadline,
        'transport':{key:ctx.env.get(key) for key in issued_calls._TRANSPORT},'actual_tasks':None,
        'effective_clearances':{},'requested_clearances':None,'implementation':{str(p):file_hash(p) for p in required},
        'ordinary_grade_request':request}
    capsule.write_text(json.dumps(capture))
    def incumbent(d):
        output.write_bytes(source.read_bytes());summary.write_text('{}')
        issued_calls._executor_raw_result(grader,owner.ledger,owner.executor,token,returncode=0,snapshot_dir=tmp_path/'raw')
        output.with_suffix('.kicad_pro').write_bytes(source.with_suffix('.kicad_pro').read_bytes())
        complete=issued_calls._executor_restored_result(grader,owner.ledger,owner.executor,token)
        return {'returncode':0,'proposals':1,'files':{p:h for p,h in complete['completed']['restored_files'].items() if h is not None}}
    budget.run_incumbent(owner.executor,incumbent)
    phase={'name':'signals','calls':1,'final_asked':0}
    custody._executor_record_phase(grader,owner.ledger,owner.executor,0,phase,calls=[('signals',0,str(summary))],outputs={str(output):file_hash(output)})
    report=Report([[]],[phase],output,tmp_path,[[]])
    custody._executor_observe_report(grader,owner.ledger,owner.executor,report)
    route=tmp_path/'route.json';route.write_text(json.dumps(report.as_dict()));drc=tmp_path/'drc_after.json';drc.write_text('{}')
    custody._executor_seal_completed(grader,owner.ledger,owner.executor,report,report_json=route,
        outputs={str(p):file_hash(p) for p in (route,drc,output)})
    budget.seal_incumbent(owner.executor)
    completed=issued_calls.completed_record(grader,owner.ledger,owner.executor,token)
    raw=next(Path(p) for p in completed['raw']['files'] if p.endswith(output.name))
    candidate=tmp_path/'candidate.kicad_pcb';candidate.write_bytes(raw.read_bytes());candidate_files={str(candidate):file_hash(candidate)}
    # Inventory-only native runtime boundary: actual prepare, owner, capsule,
    # custody, completed records and copy/hash validators all execute unchanged.
    monkeypatch.setattr(current_request,'_implementation',lambda:{'/usr/bin/kicad-cli':file_hash('/usr/bin/kicad-cli')})
    return SimpleNamespace(owner=owner,budget=budget,token=token,raw=raw,candidate=candidate,
        candidate_files=candidate_files,tmp=tmp_path,source=source,ctx=ctx)


def test_genuine_completed_owner_actual_prepare_under_consumed_slot(current):
    result=[]
    def candidate(deadline):
        assert deadline==current.budget.deadline
        work=current.tmp/'measurement';work.mkdir()
        result.append(current_request.prepare(current.budget,current.owner,current.token,current.raw,
            current.candidate,current.candidate_files,work=work))
        return {'returncode':0,'proposals':1,'files':current.candidate_files}
    current.budget.run_replay(current.owner.executor,candidate)
    assert current.budget.states==['completed','completed']
    assert result[0]['context']['mode']=='retained_current_measurement'
    assert result[0]['context']['original_custody_sha256']
    assert result[0]['request']['deadline_utc']==current.budget.deadline
    with pytest.raises(ProofUnavailable,match='replay_candidate_already_issued'):
        current.budget.run_replay(current.owner.executor,candidate)


@pytest.mark.parametrize('which',['original','template','context'])
def test_actual_completed_boundary_mutation_refuses_and_consumes_no_third_slot(current,which):
    def candidate(deadline):
        if which=='original':current.source.write_text('changed original')
        elif which=='template':current.owner.grader._template.phases[0]['final_asked']=99
        else:current.owner.contexts[current.token][0].env['changed']='yes'
        work=current.tmp/'measurement';work.mkdir()
        current_request.prepare(current.budget,current.owner,current.token,current.raw,
            current.candidate,current.candidate_files,work=work)
    with pytest.raises(ProofUnavailable):current.budget.run_replay(current.owner.executor,candidate)
    assert current.budget.states==['completed','failed']
    with pytest.raises(ProofUnavailable):current.budget.run_replay(current.owner.executor,candidate)


def controlled_measurement_reply(packet,work,*,invalid=False):
    """Native collector/DRC producer replaced; actual typed validators run."""
    from copy import deepcopy
    from placemat.kicad.manufacturing_annular import digest,evaluate
    from placemat.kicad.manufacturing_drc_report import validate
    request=packet['request'];cli=packet['context']['drc_cli']['path']
    receipt={'schema':1,'runtime_start':request['runtime'],'runtime_end':request['runtime'],
             'request_sha256':digest(request)}
    from placemat.kicad.manufacturing_factory_floor import captured_floor
    from placemat.kicad.manufacturing_net_map import resolve
    from placemat.kicad.manufacturing_floor_project import stricter
    from placemat.kicad.manufacturing_clearance_worker import nonfill_identity, raw_fills
    from placemat.kicad.manufacturing_copper_domain import raw_domain, raw_layer_domain
    from placemat.kicad.manufacturing_inventory import raw_layers
    from placemat.kicad.manufacturing_clearance_report import partition
    from placemat.kicad.board_forms import read_forms
    context=packet['context']
    capsule=context['capsule']
    factory=captured_floor(Path(capsule['path']).read_bytes(),capsule['sha256'])
    proof=resolve(context['source_original']['.kicad_pcb']['path'],context['effective_clearances'],context['krt_parser'])
    floor=factory['factory_global_floor_iu']
    rows={}
    for side in ('original','candidate'):
        bound=request[side]
        receipt[side]={'files':deepcopy(bound['files']),'via_tokens_sha256':bound['via_tokens_sha256'],
            'via_count':0,'vias':[]}
        folder=Path(context['drc_work']).with_name('native-clearance')/side
        folder.mkdir(parents=True)
        board=folder/'board.kicad_pcb'
        board.write_bytes(Path(bound['files']['.kicad_pcb']['path']).read_bytes())
        original_project=Path(bound['files']['.kicad_pro']['path']).read_bytes()
        derivative,delta=stricter(original_project,{'__captured_factory_global_floor__':floor/1000000})
        board.with_suffix('.kicad_pro').write_bytes(derivative)
        report={'$schema':'https://schemas.kicad.org/drc.v1.json','coordinate_units':'mm','date':'controlled',
            'ignored_checks':[],'included_severities':['error','warning','exclusion'],'kicad_version':'controlled',
            'source':board.name,'violations':[],'unconnected_items':[],'schematic_parity':[]}
        def record(name, data, refill):
            path=folder/name
            path.write_text(json.dumps(data))
            path.with_suffix('.stdout').write_text('controlled native producer')
            path.with_suffix('.stderr').write_text('')
            argv=[cli,'pcb','drc','--format','json','--units','mm','--all-track-errors','--severity-all']
            if refill:argv += ['--refill-zones','--save-board']
            argv += ['--output',str(path),str(board)]
            return {'returncode':0,'report_sha256':file_hash(path),'full_report':deepcopy(data),
                'schema':validate(data,board),'argv':argv,
                'artifacts':{str(p):file_hash(p) for p in (path,path.with_suffix('.stdout'),path.with_suffix('.stderr'))}}
        original_report=record('original.json',report,True)
        raw=raw_domain(board,read_forms,lambda:None)
        layers=raw_layer_domain(board,read_forms,raw_layers(board),lambda:None)
        items=[dict(item,layers=layers[item['uuid']]) for item in raw]
        if invalid:
            report['violations']=[{'type':'clearance','severity':'error','description':'controlled inherited fixed gap',
                'items':[{'uuid':item['uuid'],'description':'controlled segment','pos':{'x':0,'y':0}}
                         for item in items]}]
        measured=record('floor-'+str(floor)+'.json',report,False)
        part=partition(report,items,{},measured_floor_iu=floor,check_current=lambda:None,
                       factory_global_floor_iu=floor)
        rows[side]={'mode':'retained_current_measurement','comparison_authority':False,'cli_no_refill':True,
            'factory_floor_provenance':factory,'semantic_map_proof':proof,'original_report':original_report,
            'saved_filled_sha256':file_hash(board),'raw_fill_sha256':digest(raw_fills(board)),
            'native_item_domain':items,'distinct_floor_passes':[{'requested_floor_iu':floor,
                'actual_global_floor_iu':delta['floor_iu'],'project_delta':delta,'floor_report':measured}],
            'mandatory_partition':{'passes':[part],'mapped_violations':part['mapped_violations'],
                'mapped_floor_legal':part['mapped_floor_legal'],'comparison_authority':False}}
    result=evaluate(request,receipt)
    assert result['original']['known'] is True and result['candidate']['known'] is True
    return {'schema':1,'mode':'retained_current_measurement','comparison_authority':False,
        'request_sha256':digest(packet),'receipt':receipt,'result':result,
        'mandatory_clearance':{'schema':1,'mode':'retained_current_measurement','comparison_authority':False,
            'request_sha256':digest(packet),'rows':rows}}


def actual_selection_module():
    from placemat.kicad import replay_ordinary_selection
    return replay_ordinary_selection


@pytest.mark.parametrize('kind',['partial_unknown','known_invalid','measured_inherited_invalid','malformed_unknown','supported_legal'])
def test_actual_choose_calls_current_measurement_inside_one_consumed_slot(current,monkeypatch,kind):
    import hashlib
    from placemat.kicad import manufacturing_current_measurement as measurement
    selection=actual_selection_module();native_calls=[];grade_calls=[]
    monkeypatch.setattr(measurement,'_implementation',lambda:{'/usr/bin/kicad-cli':file_hash('/usr/bin/kicad-cli')})
    def grade_worker(argv,deadline,env,**kw):
        assert deadline==current.budget.deadline
        request=json.loads(Path(argv[-2]).read_bytes());output=Path(argv[-1])
        if argv[-3]=='--ordinary-scope':
            identity={'requested_nets':['N'],'graded_nets':['N'],'tasks':None}
            identity['sha256']=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            result={'scope':['N'],'identity':identity}
        else:
            grade_calls.append(request)
            result={'known':False,'unproved':['original_size_floor_below_factory_annular','local_clearance_overrides_unproved'],
                'drc':0,'undersized':0,'widths_unknown':False,'open':1 if len(grade_calls)==1 else 0,'quality':[1,2,3]}
            if kind=='partial_unknown':result['unproved'].append('independent_electrical_domain_unproved')
            if kind=='known_invalid':result.update(known=True,unproved=[],drc=1)
            if kind=='malformed_unknown':result={'known':False,'unproved':[]}
        output.write_text(json.dumps(result));return 0,'controlled ordinary grader',''
    monkeypatch.setattr(selection,'_execute',grade_worker)
    def native_worker(argv,deadline,env,**kw):
        native_calls.append(deadline)
        packet=json.loads(Path(argv[-2]).read_bytes())
        reply=controlled_measurement_reply(packet,Path(argv[-1]).parent,invalid=kind=='measured_inherited_invalid')
        Path(argv[-1]).write_text(json.dumps(reply));return 0,'controlled native producer',''
    monkeypatch.setattr(measurement,'_execute',native_worker)
    pocket=current.tmp/'pocket';(pocket/'raw').mkdir(parents=True)
    output=pocket/'candidate.kicad_pcb';raw=pocket/'raw/0-candidate.kicad_pcb';raw.write_bytes(current.candidate.read_bytes())
    summary=pocket/'raw/3-summary.json';summary.write_text('{}')
    files={str(p):file_hash(p) for p in (raw,summary)}
    results=[]
    def candidate(deadline):
        results.append(selection.choose(current.budget,current.owner,current.token,output,files,current.tmp/'selection'))
        return {'returncode':0,'proposals':1,'files':files}
    if kind=='malformed_unknown':
        with pytest.raises(ProofUnavailable,match='current_measurement_grade_unavailable'):
            current.budget.run_replay(current.owner.executor,candidate)
        assert not native_calls and current.budget.states==['completed','failed']
    else:
        current.budget.run_replay(current.owner.executor,candidate)
        assert native_calls==[current.budget.deadline] and len(grade_calls)==2
        assert results[0]['selected']==('pocket' if kind=='supported_legal' else 'legacy')
        assert results[0]['ordinary_comparison_only'] is True
        assert all(request['input']==str(current.source) for request in grade_calls)
        assert (current.tmp/'selection/manufacturing/measurement.json').exists()
        if kind=='supported_legal':
            assert all(g['known'] is True and g['unproved']==[] and g['drc']==0 for g in results[0]['grades'].values())
            assert results[0]['grades']['pocket']['open']==0 and results[0]['grades']['legacy']['open']==1
        elif kind in {'known_invalid','measured_inherited_invalid'}:assert all(g['known'] is True and g['drc']==1 for g in results[0]['grades'].values())
        else:assert all(g['known'] is False for g in results[0]['grades'].values())
        assert current.budget.states==['completed','completed']
    with pytest.raises(ProofUnavailable):current.budget.run_replay(current.owner.executor,candidate)
