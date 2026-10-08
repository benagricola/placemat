"""Owned fresh original-rule manufacturing measurement; no routing proposal."""
import hashlib
import json
import sys
import time
from pathlib import Path
from .manufacturing_annular import validate_request, unchanged, evaluate, digest, Unproved
from .manufacturing_inventory import raw_inventory, raw_layers, collect, sha, raw_layer_record, InventoryUnavailable
from .manufacturing_local_inventory import raw_local, native_local


def paired_absence(request):
    for side in ('original','candidate'):
        if request[side]['files']['.kicad_dru'] is None:
            p=Path(request[side]['files']['.kicad_pcb']['path']).with_suffix('.kicad_dru')
            if p.exists() or p.is_symlink():raise Unproved('paired_absence_changed')


def run(packet):
    request=packet['request'];context=packet['context']
    if context['mode']!='retained_current_measurement' or context['comparison_authority'] is not False:
        raise Unproved('diagnostic_scope')
    if context['pair_request_sha256']!=digest(request):raise Unproved('request_binding')
    validate_request(request,time.time());unchanged(request);paired_absence(request)
    def original_unchanged():
        for path, expected in context['actual_raw_copper'].items():
            if sha(path)!=expected:raise Unproved('actual_raw_copper_changed')
        for suffix,entry in context['source_original'].items():
            if entry is None:
                p=Path(context['source_original']['.kicad_pcb']['path']).with_suffix(suffix)
                if p.exists() or p.is_symlink():raise Unproved('original_absence_changed')
            elif sha(entry['path'])!=entry['sha256']:raise Unproved('original_source_changed')
        if sha(context['capsule']['path'])!=context['capsule']['sha256']:raise Unproved('capsule_changed')
    original_unchanged()
    from placemat.kicad.quiet import import_pcbnew
    api=import_pcbnew()
    # Parent must pin the actual imported wrappers and extension, not another
    # same-named installed binding. No native module imported in supervisor.
    import _pcbnew
    for module in (api,_pcbnew):
        path=str(Path(module.__file__).resolve())
        if path not in request['runtime'] or sha(path)!=request['runtime'][path]:
            raise Unproved('native_origin_changed')
    source_path=context['source_original']['.kicad_pcb']['path']
    source_raw=raw_inventory(source_path);source_raw['copper_layers']=raw_layers(source_path);source_raw['physical_layer_ids']=raw_layer_record(source_path)['ids']
    if (source_raw['via_tokens_sha256']!=context['source_inventory']['via_tokens_sha256']
            or source_raw['via_uuid_multiset']!=context['source_inventory']['via_uuid_multiset']):
        raise Unproved('original_raw_inventory_changed')
    original_board=api.LoadBoard(source_path)
    if original_board is None:raise Unproved('native_original_unavailable')
    validate_request(request,time.time());unchanged(request);paired_absence(request);original_unchanged()
    original_inventory=collect(original_board,api,source_raw)
    local_reports={}
    def local_report(name,path,board):
        raw=raw_local(path)
        try:local_reports[name]=native_local(board,raw)
        except InventoryUnavailable as error:
            local_reports[name]={'raw':raw,'complete':False,'refusal':str(error),'pair_constraints_proved':False}
    local_report('source_original',source_path,original_board)
    from .manufacturing_net_map import resolve, crosscheck
    parser_path=context['krt_parser']
    if str(Path(parser_path).resolve()) not in request['runtime']:raise Unproved('net_parser_unbound')
    semantic_map=resolve(source_path,context['effective_clearances'],parser_path)
    native_names={'source_original':crosscheck(original_board,semantic_map)}
    original_inventory.pop('copper_layers')
    original_inventory['files']=context['source_original']
    validate_request(request,time.time());unchanged(request);paired_absence(request);original_unchanged()
    receipt={'schema':1,'request_sha256':digest(request),'runtime_start':dict(request['runtime'])}
    for side in ('original','candidate'):
        validate_request(request,time.time());unchanged(request);paired_absence(request);original_unchanged()
        source=request[side]['files']['.kicad_pcb']['path']
        raw=raw_inventory(source);raw['copper_layers']=raw_layers(source);raw['physical_layer_ids']=raw_layer_record(source)['ids']
        if raw['via_tokens_sha256']!=request[side]['via_tokens_sha256'] or raw['via_uuid_multiset']!=request[side]['via_uuid_multiset']:
            raise Unproved('raw_inventory_changed')
        board=api.LoadBoard(source)
        if board is None:raise Unproved('native_board_unavailable')
        validate_request(request,time.time());unchanged(request);paired_absence(request);original_unchanged()
        row=collect(board,api,raw)
        local_report(side,source,board)
        native_names[side]=crosscheck(board,semantic_map)
        row.pop('copper_layers')
        receipt[side]={'files':request[side]['files'],**row}
        validate_request(request,time.time());unchanged(request);paired_absence(request);original_unchanged()
    receipt['runtime_end']=dict(request['runtime'])
    result=evaluate(request,receipt)
    original_unchanged()
    from .manufacturing_annular import _evaluate_side
    source_request=dict(request,original=context['source_inventory'])
    original_result=_evaluate_side(source_request,original_inventory,'original')
    validate_request(request,time.time());unchanged(request);paired_absence(request);original_unchanged()
    from .manufacturing_clearance_worker import measure_pair
    clearance = measure_pair(packet)
    validate_request(request,time.time());unchanged(request);paired_absence(request);original_unchanged()
    return {'schema':1,'mode':'retained_current_measurement','comparison_authority':False,
            'request_sha256':digest(packet),'receipt':receipt,'result':result,
            'original_source_inventory':original_inventory,'original_source_result':original_result,'local_inventory':local_reports,'captured_net_map':semantic_map,'native_net_domains':native_names,'mandatory_clearance':clearance}


def main():
    source=Path(sys.argv[1]);destination=Path(sys.argv[2])
    raw=source.read_bytes();expected=hashlib.sha256(raw).hexdigest()
    packet=json.loads(raw)
    if sha(source)!=expected:raise Unproved('packet_changed')
    reply=run(packet)
    if sha(source)!=expected:raise Unproved('packet_changed')
    destination.open('x').write(json.dumps(reply,sort_keys=True,allow_nan=False)+'\n')

if __name__=='__main__':main()
