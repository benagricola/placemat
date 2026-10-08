"""Scratch paired annular evidence codec; no native reads or adoption authority."""
from collections import Counter
import hashlib
import json
import math
import time
from uuid import UUID
from pathlib import Path

class Unproved(ValueError):
    pass


def digest(value):
    try:
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    except (ValueError,TypeError,OverflowError) as error:
        raise Unproved('non_json_evidence') from error
    return hashlib.sha256(raw).hexdigest()


def exact_keys(value, keys):
    if not isinstance(value,dict) or set(value)!=set(keys):
        raise Unproved('schema')


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise Unproved('integer')
    return value


def dimension_iu(value, minimum=0):
    # PCB_VIA.GetWidth/GetDrillValue expose C++ int internal units.
    integer(value, minimum)
    if value > 2**31-1:raise Unproved('native_dimension_range')
    return value


def hash_value(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise Unproved('hash')


def via_uuid(value):
    if not isinstance(value, str):raise Unproved('uuid_inventory')
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise Unproved('uuid_inventory') from None
    if str(parsed) != value or parsed.int == 0:raise Unproved('uuid_inventory')


def validate_request(request, now):
    exact_keys(request,('schema','original','candidate','runtime','deadline_utc','factory_annular_iu','original_annular_iu'))
    if type(request['schema']) is not int or request['schema']!=1:
        raise Unproved('schema')
    deadline=request['deadline_utc']
    for value in (deadline, now):
        try:
            finite = type(value) in (int,float) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:raise Unproved('deadline')
    if deadline<=now:raise Unproved('deadline')
    dimension_iu(request['factory_annular_iu'],1);dimension_iu(request['original_annular_iu'])
    for side in ('original','candidate'):
        exact_keys(request[side],('files','via_tokens_sha256','via_uuid_multiset','copper_layers'))
        files=request[side]['files']
        exact_keys(files,('.kicad_pcb','.kicad_pro','.kicad_dru'))
        for suffix, value in files.items():
            if value is None and suffix=='.kicad_dru':continue
            exact_keys(value,('path','sha256'))
            if not isinstance(value['path'],str) or not value['path']:raise Unproved('path')
            hash_value(value['sha256'])
        hash_value(request[side]['via_tokens_sha256'])
        layers=request[side]['copper_layers']
        if not isinstance(layers,list) or not layers or any(not isinstance(x,str) for x in layers) or len(set(layers))!=len(layers):raise Unproved('board_layers')
        ids=request[side]['via_uuid_multiset']
        if not isinstance(ids,list):raise Unproved('uuid_inventory')
        for value in ids:via_uuid(value)
    if not isinstance(request['runtime'],dict) or not request['runtime']:raise Unproved('runtime')
    for path, sha in request['runtime'].items():
        if not isinstance(path,str) or not path:raise Unproved('runtime')
        hash_value(sha)
    digest(request)


def unchanged(request):
    for side in ('original','candidate'):
        for value in request[side]['files'].values():
            if value is None:
                board_path=request[side]['files']['.kicad_pcb']['path']
                absent=Path(board_path).with_suffix('.kicad_dru')
                if absent.exists() or absent.is_symlink():raise Unproved('source_absence_changed')
                continue
            if hashlib.sha256(Path(value['path']).read_bytes()).hexdigest()!=value['sha256']:
                raise Unproved('source_changed')
    for path, expected in request['runtime'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected:raise Unproved('runtime_changed')


def _evaluate_side(request, data, side):
    floor=max(request['factory_annular_iu'],request['original_annular_iu'])
    exact_keys(data,('files','via_tokens_sha256','via_count','vias'))
    if digest(data['files'])!=digest(request[side]['files']) or data['via_tokens_sha256']!=request[side]['via_tokens_sha256']:raise Unproved('board_binding')
    if not isinstance(data['vias'],list) or integer(data['via_count'])!=len(data['vias']):raise Unproved('via_count')
    rows=data['vias']
    for row in rows:
        exact_keys(row,('uuid','kind','drill_iu','layers','diameters_iu'))
        via_uuid(row['uuid'])
    if Counter(row['uuid'] for row in rows)!=Counter(request[side]['via_uuid_multiset']):raise Unproved('via_coverage')
    under=[];unsupported=[]
    for index,row in enumerate(rows):
        exact_keys(row,('uuid','kind','drill_iu','layers','diameters_iu'))
        if row['kind']!='through':unsupported.append({'index':index,'uuid':row['uuid'],'reason':'via_stack_unproved'});continue
        drill=dimension_iu(row['drill_iu'],1)
        layers=row['layers'];diameters=row['diameters_iu']
        if layers!=request[side]['copper_layers']:raise Unproved('layer_coverage')
        if not isinstance(diameters,list) or len(diameters)!=len(layers):raise Unproved('layer_coverage')
        for layer,diameter in zip(layers,diameters):
            dimension_iu(diameter,1)
            if diameter<=drill:raise Unproved('nonpositive_ring')
            if diameter-drill<2*floor:under.append({'index':index,'uuid':row['uuid'],'layer':layer})
    return {'count':len(rows),'under':under,'unproved':unsupported,'known':not unsupported}

def evaluate(request, receipt, now=None):
    """Validate both complete inventories independently; local rule proof stays open."""
    clock = time.time if now is None else (now if callable(now) else lambda:now)
    validate_request(request,clock())
    unchanged(request)
    exact_keys(receipt,('schema','request_sha256','runtime_start','runtime_end','original','candidate'))
    if type(receipt['schema']) is not int or receipt['schema']!=1 or receipt['request_sha256']!=digest(request):raise Unproved('request_binding')
    if digest(receipt['runtime_start'])!=digest(request['runtime']) or digest(receipt['runtime_end'])!=digest(request['runtime']):raise Unproved('runtime_binding')
    result={}
    for side in ('original','candidate'):
        try:
            result[side]=_evaluate_side(request,receipt[side],side)
        except Unproved as error:
            result[side]={'count':None,'under':[], 'unproved':[{'reason':str(error)}], 'known':False}
    result['remove_reason']=('original_size_floor_below_factory_annular' if result['candidate']['known'] and not result['candidate']['under'] and result['original']['known'] and not result['original']['under'] else None)
    result['remaining_reason']='local_clearance_overrides_unproved'
    result['comparison_authority']=False
    result['requires_fresh_original_rules_drc']=True
    result['requires_complete_original_constraints']=True
    unchanged(request)
    validate_request(request,clock())
    return result
