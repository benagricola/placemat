"""Fresh current-pair clearance measurement under the retained original deadline.

Only the existing owned measurement child calls this operation. The returned
receipt is checked by its parent and does not grant publication authority.
"""
import hashlib
import json
from pathlib import Path
import shutil
import time
from .manufacturing_annular import validate_request,unchanged,digest,Unproved
from .manufacturing_inventory import sha
from .manufacturing_floor_project import stricter


def fill_geometry(board,api):
    layers=list(board.GetEnabledLayers().CuStack())
    if any(type(v) is not int or not api.IsCopperLayer(v) for v in layers):raise Unproved('fill_layer_domain')
    def chain(value):
        count=value.PointCount()
        if type(count) is not int or count<3 or value.ArcCount()!=0:raise Unproved('fill_chain_unsupported')
        points=[]
        for i in range(count):
            p=value.CPoint(i)
            if any(type(v) is not int or not -2**31<=v<=2**31-1 for v in (p.x,p.y)):
                raise Unproved('fill_coordinate_unsupported')
            points.append([p.x,p.y])
        return points
    rows=[];seen=set()
    zones=[(None,z) for z in board.Zones()]
    for fp in board.GetFootprints():zones.extend((fp.m_Uuid.AsString(),z) for z in fp.Zones())
    for parent,zone in zones:
        uid=zone.m_Uuid.AsString()
        if uid in seen:raise Unproved('fill_zone_duplicate')
        seen.add(uid)
        if zone.GetIsRuleArea():
            rows.append({'uuid':uid,'parent':parent,'rule_area':True});continue
        for layer in layers:
            if not zone.IsOnLayer(layer):continue
            if zone.HasFilledPolysForLayer(layer) is not True:raise Unproved('fill_unavailable')
            polygons=zone.GetFill(layer);count=polygons.OutlineCount()
            if type(count) is not int or count<0:raise Unproved('fill_outline_count')
            outlines=[]
            for i in range(count):
                holes=polygons.HoleCount(i)
                if type(holes) is not int or holes<0:raise Unproved('fill_hole_count')
                outlines.append({'outline':chain(polygons.COutline(i)),
                    'holes':[chain(polygons.CHole(i,j)) for j in range(holes)]})
            rows.append({'uuid':uid,'parent':parent,'layer':layer,'rule_area':False,'polygons':outlines})
    return {'layers':layers,'zones':rows}


def raw_fills(path):
    from placemat.kicad.board_forms import read_forms
    root=read_forms(path,lambda r:(_ for _ in ()).throw(Unproved(r)))
    result=[]
    def visit(node,parent=None):
        if not isinstance(node,list) or not node:return
        if node[0]=='zone':
            ids=[x for x in node if isinstance(x,list) and x and x[0]=='uuid']
            if len(ids)!=1:raise Unproved('raw_fill_zone_uuid')
            result.append({'uuid':ids[0][1],'parent':parent,
                'fills':[x for x in node if isinstance(x,list) and x and x[0] in ('filled_polygon','fill_segments')]})
        elif node[0]=='footprint':
            ids=[x for x in node if isinstance(x,list) and x and x[0]=='uuid']
            if len(ids)!=1:raise Unproved('raw_fill_parent_uuid')
            for child in node:visit(child,ids[0][1])
    for item in root:visit(item)
    return result


def copy_pinned_pcb(source, destination, expected):
    if sha(source)!=expected:raise Unproved('floor_source_copy_changed')
    shutil.copyfile(source,destination)
    if sha(destination)!=expected or sha(source)!=expected:
        raise Unproved('floor_copied_pcb_changed')


def nonfill_identity(path):
    """Actual read_board plus independent configured/raw preservation projection."""
    from placemat.kicad.read import read_board
    from placemat.final_preservation import manifest
    return manifest(read_board(path), path)


def checked_folder(folder, expected):
    actual={p.name:sha(p) for p in folder.iterdir() if p.is_file() and not p.is_symlink()}
    if any(p.is_symlink() or not p.is_file() for p in folder.iterdir()):raise Unproved('floor_folder_domain')
    extras=set(actual)-set(expected)
    prl='board.kicad_prl'
    if extras-{prl}:raise Unproved('floor_folder_extras')
    for name,value in expected.items():
        if actual.get(name)!=value:raise Unproved('floor_companion_changed')
    return {'generated_prl':actual.get(prl),'prl_absent_at_start':True}


def floor_context(board, proof, original_project):
    from .manufacturing_net_map import crosscheck
    native=crosscheck(board,proof)
    derivative,delta=stricter(original_project,proof['semantic_map'])
    return native,derivative,delta


def verify_artifacts(artifacts):
    for path,expected in artifacts.items():
        try:
            actual=sha(path)
        except OSError as error:
            raise Unproved('measurement_artifact_unavailable') from error
        if actual!=expected:
            raise Unproved('earlier_measurement_artifact_changed')


def checked_cli(execute,cli,board,report,deadline,env,*,refill=False,save=False):
    argv=[cli,'pcb','drc','--format','json','--units','mm','--all-track-errors','--severity-all']
    if refill:argv.append('--refill-zones')
    if save:
        if not refill:raise Unproved('save_without_original_refill')
        argv.append('--save-board')
    argv+=['--output',str(report),str(board)]
    rc,out,err=execute(argv,deadline,env,cwd=str(board.parent))
    report.with_suffix('.stdout').write_text(out);report.with_suffix('.stderr').write_text(err)
    if type(rc) is not int or rc!=0:raise Unproved('floor_cli_failed')
    raw=report.read_bytes();data=json.loads(raw)
    from .manufacturing_drc_report import validate
    metadata=validate(data,board)
    expected=hashlib.sha256(raw).hexdigest()
    if sha(report)!=expected:raise Unproved('floor_report_changed')
    artifacts={str(report):expected,
        str(report.with_suffix('.stdout')):hashlib.sha256(out.encode()).hexdigest(),
        str(report.with_suffix('.stderr')):hashlib.sha256(err.encode()).hexdigest()}
    verify_artifacts(artifacts)
    return {'argv':argv,'returncode':rc,'report_sha256':expected,'full_report':data,'schema':metadata,
            'artifacts':artifacts}


def measure_pair(packet):
    request=packet['request'];context=packet['context']
    if context['mode']!='retained_current_measurement' or context['comparison_authority'] is not False:
        raise Unproved('floor_scope')
    def check():
        validate_request(request,time.time());unchanged(request)
        for suffix,entry in context['source_original'].items():
            if entry is None:
                path=Path(context['source_original']['.kicad_pcb']['path']).with_suffix(suffix)
                if path.exists() or path.is_symlink():raise Unproved('source_absence_changed')
            elif sha(entry['path'])!=entry['sha256']:raise Unproved('source_changed')
        if sha(context['capsule']['path'])!=context['capsule']['sha256']:raise Unproved('capsule_changed')
        for side in ('original','candidate'):
            if request[side]['files']['.kicad_dru'] is None:
                p=Path(request[side]['files']['.kicad_pcb']['path']).with_suffix('.kicad_dru')
                if p.exists() or p.is_symlink():raise Unproved('paired_absence_changed')
    check()
    from placemat.kicad.quiet import import_pcbnew
    api=import_pcbnew()
    import _pcbnew
    for module in (api,_pcbnew):
        p=str(Path(module.__file__).resolve())
        if request['runtime'].get(p)!=sha(p):raise Unproved('native_origin_changed')
    from placemat.kicad.final_owned_worker import _execute
    from .manufacturing_net_map import resolve,crosscheck
    from .manufacturing_factory_floor import captured_floor
    capsule_raw=Path(context['capsule']['path']).read_bytes()
    factory_proof=captured_floor(capsule_raw,context['capsule']['sha256'])
    factory_global_floor_iu=factory_proof['factory_global_floor_iu']
    floors=resolve(context['source_original']['.kicad_pcb']['path'],context['effective_clearances'],context['krt_parser'])
    work=Path(context['drc_work']).with_name('native-clearance');work.mkdir();rows={}
    def measure(label,source,original_project,case_floors,*,expected_source_sha=None):
        check();folder=work/label;folder.mkdir();board_path=folder/'board.kicad_pcb'
        source_sha=expected_source_sha if expected_source_sha is not None else sha(source)
        copy_pinned_pcb(source,board_path,source_sha)
        project=board_path.with_suffix('.kicad_pro');project.write_bytes(original_project)
        rules=context['source_original']['.kicad_dru']
        if rules is not None:shutil.copyfile(rules['path'],board_path.with_suffix('.kicad_dru'))
        import os
        env=dict(os.environ,KRT_ROUTE_DEADLINE_UTC=str(request['deadline_utc']))
        initial_files={p.name:sha(p) for p in folder.iterdir()}
        intent_before=nonfill_identity(board_path)
        (folder/'nonfill-before.json').write_text(json.dumps(intent_before,sort_keys=True,allow_nan=False)+'\n')
        initial_files['nonfill-before.json']=sha(folder/'nonfill-before.json')
        original_report=checked_cli(_execute,context['drc_cli']['path'],board_path,
            folder/'original.json',request['deadline_utc'],env,refill=True,save=True)
        if project.read_bytes()!=original_project:raise Unproved('original_refill_project_changed')
        if rules is None:
            rp=board_path.with_suffix('.kicad_dru')
            if rp.exists() or rp.is_symlink():raise Unproved('original_refill_rules_absence_changed')
        elif sha(board_path.with_suffix('.kicad_dru'))!=rules['sha256']:
            raise Unproved('original_refill_rules_changed')
        intent_after_refill=nonfill_identity(board_path)
        (folder/'nonfill-after-refill.json').write_text(json.dumps(intent_after_refill,sort_keys=True,allow_nan=False)+'\n')
        initial_files['nonfill-after-refill.json']=sha(folder/'nonfill-after-refill.json')
        if intent_after_refill!=intent_before:raise Unproved('original_refill_nonfill_changed')
        check()
        original_board=api.LoadBoard(str(board_path));before=fill_geometry(original_board,api)
        raw_before=raw_fills(board_path);filled_sha=sha(board_path)
        companion_start=dict(initial_files)
        companion_start['board.kicad_pcb']=filled_sha
        for name in ('original.json','original.stdout','original.stderr'):companion_start[name]=sha(folder/name)
        original_folder_receipt=checked_folder(folder,companion_start)
        from .manufacturing_copper_domain import raw_domain,collect
        from placemat.kicad.board_forms import read_forms
        from .manufacturing_clearance_passes import measure_distinct
        from .manufacturing_floor_project import iu
        native_map=crosscheck(original_board,case_floors)
        from .manufacturing_inventory import raw_layers
        if raw_layers(board_path)!=[api.LayerName(layer) for layer in original_board.GetEnabledLayers().CuStack()]:
            raise Unproved('raw_native_stack_changed')
        def cheap_loop_check():
            if time.time()>=request['deadline_utc']:
                raise Unproved('deadline')
        check()
        raw_items=raw_domain(board_path,read_forms,cheap_loop_check)
        items=collect(original_board,api,raw_items,cheap_loop_check)
        check()
        snapshots={'pcb_sha256':filled_sha,'fill_geometry':before,'raw_fills':raw_before,
                   'nonfill':intent_before,'items':items}
        passes=[]
        sealed_artifacts=dict(original_report['artifacts'])
        expected_project=original_project
        def same_snapshot(actual):
            check()
            if project.read_bytes()!=expected_project:
                raise Unproved('floor_project_changed')
            copied_rules=board_path.with_suffix('.kicad_dru')
            if rules is None:
                if copied_rules.exists() or copied_rules.is_symlink():
                    raise Unproved('floor_rules_absence_changed')
            elif sha(copied_rules)!=rules['sha256']:
                raise Unproved('floor_rules_changed')
            verify_artifacts(sealed_artifacts)
            if actual is not snapshots or sha(board_path)!=filled_sha or raw_fills(board_path)!=raw_before:
                raise Unproved('floor_geometry_changed')
            loaded=api.LoadBoard(str(board_path))
            if fill_geometry(loaded,api)!=before:
                raise Unproved('floor_geometry_changed')
            if collect(loaded,api,raw_items,cheap_loop_check)!=items:
                raise Unproved('native_item_domain_changed')
        def measure_floor(actual,level):
            nonlocal expected_project
            same_snapshot(actual)
            selected={name:value for name,value in case_floors['semantic_map'].items() if max(factory_global_floor_iu,iu(value))==level}
            if not selected:
                # This is a task-private project constraint, not an invented net request.
                selected={'__captured_factory_global_floor__':level/1000000}
            derivative,delta=stricter(original_project,selected)
            expected_project=derivative
            project.write_bytes(derivative)
            same_snapshot(actual)
            target=folder/('floor-'+str(level)+'.json')
            report=checked_cli(_execute,context['drc_cli']['path'],board_path,
                target,request['deadline_utc'],env)
            sealed_artifacts.update(report['artifacts'])
            same_snapshot(actual)
            if project.read_bytes()!=derivative:
                raise Unproved('floor_project_changed')
            after_intent=nonfill_identity(board_path)
            if {k:v for k,v in after_intent.items() if k!='rules_outline'}!={k:v for k,v in intent_before.items() if k!='rules_outline'}:
                raise Unproved('floor_nonfill_changed')
            passes.append({'requested_floor_iu':level,'actual_global_floor_iu':delta['floor_iu'],
                           'project_delta':delta,'floor_report':report})
            return report['full_report']
        floor_result=measure_distinct({name:iu(value) for name,value in case_floors['semantic_map'].items()},
            snapshot=snapshots,items=items,measure=measure_floor,check_current=same_snapshot,
            check_loop=cheap_loop_check,factory_global_floor_iu=factory_global_floor_iu)
        floor_expected=dict(companion_start)
        floor_expected['board.kicad_pro']=sha(project)
        for path,expected in sealed_artifacts.items():
            floor_expected[Path(path).name]=expected
        folder_receipt=checked_folder(folder,floor_expected)
        floor_report=passes[-1]['floor_report']
        delta=passes[-1]['project_delta']
        check()
        rows[label]={'original_report':original_report,'floor_report':floor_report,
            'nonfill_identity_sha256':digest(intent_before),
            'original_folder_receipt':original_folder_receipt,'folder_receipt':folder_receipt,
            'semantic_map_proof':case_floors,'native_name_crosscheck':native_map,
            'project_delta':delta,'distinct_floor_passes':passes,'mandatory_partition':floor_result,
            'factory_floor_provenance':factory_proof,
            'native_item_domain':items,'original_fill_geometry':before,'raw_fill_sha256':digest(raw_before),
            'cli_no_refill':True,
            'saved_filled_sha256':filled_sha,'mode':'retained_current_measurement','comparison_authority':False}
    original_project=Path(context['source_original']['.kicad_pro']['path']).read_bytes()
    for side in ('original','candidate'):
        measure(side,request[side]['files']['.kicad_pcb']['path'],original_project,floors,
                expected_source_sha=request[side]['files']['.kicad_pcb']['sha256'])
    check()
    return {'schema':1,'mode':'retained_current_measurement','comparison_authority':False,
            'request_sha256':digest(packet),'rows':rows,
            'cli_semantics_source':'https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0.6/pcbnew/pcbnew_jobs_handler.cpp'}
