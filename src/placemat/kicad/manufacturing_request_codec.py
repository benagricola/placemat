"""Scratch saved-pair annular request. Never reconstructs execution authority."""
import hashlib
import json
from pathlib import Path
from .manufacturing_inventory import raw_inventory, raw_layers, sha, InventoryUnavailable


def bound_json(path):
    path=Path(path).resolve();raw=path.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    data=json.loads(raw)
    if sha(path)!=digest:raise InventoryUnavailable('capsule_changed')
    return data,{'path':str(path),'sha256':digest}


def family(path):
    path=Path(path).resolve();result={}
    for ext in ('.kicad_pcb','.kicad_pro','.kicad_dru'):
        p=path.with_suffix(ext)
        if not p.exists():
            if ext!='.kicad_dru' or p.is_symlink():raise InventoryUnavailable('companion_unavailable')
            result[ext]=None
        else:
            if p.is_symlink():raise InventoryUnavailable('symlink_companion_unproved')
            result[ext]={'path':str(p),'sha256':sha(p)}
    return result


def saved_request(*,original,legacy,candidate,capsule,runtime,deadline_utc):
    """Diagnostic-only explicit saved paths; no factory or historical completion.

    Runtime mapping is supervisor-reviewed, never evidence supplied by the child.
    The original captured CLI maps are retained verbatim, not recomputed.
    """
    from .manufacturing_annular import validate_request, digest, dimension_iu
    import time
    capture,identity=bound_json(capsule)
    envelope=capture['ordinary_grade_request']['manufacturing_defaults']
    original_files=family(original)
    original_raw=raw_inventory(original)
    source_inventory={'files':original_files,'via_tokens_sha256':original_raw['via_tokens_sha256'],
                      'via_uuid_multiset':original_raw['via_uuid_multiset'],'copper_layers':raw_layers(original)}
    project,_=bound_json(original_files['.kicad_pro']['path'])
    annular=project['board']['design_settings']['rules']['min_via_annular_width']
    def iu(mm):
        if type(mm) not in (int,float):raise InventoryUnavailable('annular_dimension_unproved')
        value=mm*1000000
        if type(value) is float and not value.is_integer():
            raise InventoryUnavailable('annular_dimension_unproved')
        return dimension_iu(int(value))
    request={'schema':1,'runtime':dict(runtime),'deadline_utc':deadline_utc,
             'factory_annular_iu':iu(envelope['size_floors']['annular']),
             'original_annular_iu':iu(annular)}
    for side,path in (('original',legacy),('candidate',candidate)):
        raw=raw_inventory(path)
        request[side]={'files':family(path),'via_tokens_sha256':raw['via_tokens_sha256'],
                       'via_uuid_multiset':raw['via_uuid_multiset'],'copper_layers':raw_layers(path)}
    validate_request(request,time.time())
    # 'original' in paired codec denotes saved incumbent; retained source is
    # separately explicit here, preventing a modified board becoming a baseline.
    context={'schema':1,'mode':'saved_pair_diagnostic_only','comparison_authority':False,
             'historical_deadline_utc':capture['deadline_utc'],'capsule':identity,
             'source_original':original_files,'source_inventory':source_inventory,'manufacturing_defaults':envelope,
             'effective_clearances':capture['effective_clearances'],
             'requested_clearances':capture['requested_clearances'],
             'pair_request_sha256':digest(request)}
    if sha(identity['path'])!=identity['sha256']:raise InventoryUnavailable('capsule_changed')
    return {'request':request,'context':context}
