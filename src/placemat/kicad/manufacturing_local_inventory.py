"""Complete raw/native local override inventory. Does not resolve pair rules."""
from collections import Counter
from decimal import Decimal,InvalidOperation
import json
from uuid import UUID
from placemat.kicad.board_forms import read_forms
from .manufacturing_inventory import InventoryUnavailable,sha


def uid(node):
    entries=[x for x in node if isinstance(x,list) and x and x[0]=='uuid']
    if len(entries)!=1 or len(entries[0])!=2:raise InventoryUnavailable('local_uuid_unproved')
    value=entries[0][1]
    if value.startswith('"'):value=json.loads(value)
    try:parsed=UUID(value)
    except (ValueError,TypeError,AttributeError):raise InventoryUnavailable('local_uuid_unproved') from None
    if str(parsed)!=value or parsed.int==0:raise InventoryUnavailable('local_uuid_unproved')
    return value


def local(node):
    entries=[x for x in node if isinstance(x,list) and x and x[0]=='clearance']
    if len(entries)>1:raise InventoryUnavailable('local_duplicate_value')
    if not entries:return None
    if len(entries[0])!=2:raise InventoryUnavailable('local_value_unproved')
    try:value=Decimal(entries[0][1])*1000000
    except (InvalidOperation,TypeError):raise InventoryUnavailable('local_value_unproved') from None
    if not value.is_finite() or value<0 or value!=value.to_integral_value() or value>2**31-1:
        raise InventoryUnavailable('local_value_unproved')
    return int(value)


def raw_local(path):
    before=sha(path)
    root=read_forms(path,lambda r:(_ for _ in ()).throw(InventoryUnavailable(r)))
    rows=[]
    for node in root:
        if not isinstance(node,list) or not node:continue
        if node[0]=='footprint':
            fp=uid(node);rows.append({'kind':'footprint','uuid':fp,'parent':None,'local_iu':local(node)})
            for pad in node:
                if isinstance(pad,list) and pad and pad[0]=='pad':
                    rows.append({'kind':'pad','uuid':uid(pad),'parent':fp,'local_iu':local(pad)})
                elif isinstance(pad,list) and pad and pad[0]=='zone':
                    links=[x for x in pad if isinstance(x,list) and x and x[0]=='connect_pads']
                    if len(links)>1:raise InventoryUnavailable('zone_local_unproved')
                    rows.append({'kind':'zone','uuid':uid(pad),'parent':fp,'local_iu':local(links[0]) if links else None})
        elif node[0]=='zone':
            links=[x for x in node if isinstance(x,list) and x and x[0]=='connect_pads']
            if len(links)>1:raise InventoryUnavailable('zone_local_unproved')
            rows.append({'kind':'zone','uuid':uid(node),'parent':None,'local_iu':local(links[0]) if links else None})
    if sha(path)!=before:raise InventoryUnavailable('local_source_changed')
    return rows


def native_local(board,raw):
    rows=[]
    def value(item):
        v=item.GetLocalClearance()
        if v is not None and (type(v) is not int or not 0<=v<=2**31-1):raise InventoryUnavailable('native_local_value_unproved')
        return v
    for fp in board.GetFootprints():
        fp_id=fp.m_Uuid.AsString();rows.append({'kind':'footprint','uuid':fp_id,'parent':None,'local_iu':value(fp)})
        for pad in fp.Pads():rows.append({'kind':'pad','uuid':pad.m_Uuid.AsString(),'parent':fp_id,'local_iu':value(pad)})
        for zone in fp.Zones():rows.append({'kind':'zone','uuid':zone.m_Uuid.AsString(),'parent':fp_id,'local_iu':value(zone)})
    for zone in board.Zones():rows.append({'kind':'zone','uuid':zone.m_Uuid.AsString(),'parent':None,'local_iu':value(zone)})
    def signature(row):return row['kind'],row['uuid'],row['parent']
    if Counter(map(signature,rows))!=Counter(map(signature,raw)):raise InventoryUnavailable('local_raw_native_coverage')
    # None and zero both mean no explicit local override. Preserve both raw and
    # native observations, compare normalized semantic presence only here.
    if Counter((*signature(r),r['local_iu'] or 0) for r in rows)!=Counter((*signature(r),r['local_iu'] or 0) for r in raw):
        raise InventoryUnavailable('local_raw_native_value_mismatch')
    return {'raw':raw,'native':rows,'complete':True,'pair_constraints_proved':False}
