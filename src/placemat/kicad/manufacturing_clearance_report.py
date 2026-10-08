"""Pure partition of one global-floor DRC pass; producer custody remains required."""
from uuid import UUID

class Unproved(ValueError):
    pass


def partition(report, items, floors_iu, *, measured_floor_iu, check_current, factory_global_floor_iu=0):
    """One distinct captured floor; no geometry inferred from report prose."""
    check_current()
    if not isinstance(floors_iu,dict):
        raise Unproved('map_domain')
    if any(not isinstance(n,str) or not n or type(v) is not int or v<0 for n,v in floors_iu.items()):
        raise Unproved('map_domain')
    if type(factory_global_floor_iu) is not int or factory_global_floor_iu<0:
        raise Unproved('factory_floor_domain')
    levels={max(factory_global_floor_iu,value) for value in floors_iu.values()}
    if factory_global_floor_iu:levels.add(factory_global_floor_iu)
    levels.discard(0)
    if type(measured_floor_iu) is not int or measured_floor_iu<=0 or measured_floor_iu not in levels:
        raise Unproved('floor_pass_domain')
    if not isinstance(items,list):raise Unproved('item_domain')
    domain={}
    for item in items:
        check_current()
        if not isinstance(item,dict) or set(item)!={'uuid','net','layers','kind'}:
            raise Unproved('item_domain')
        uid=item['uuid']
        try:valid=isinstance(uid,str) and str(UUID(uid))==uid and UUID(uid).int!=0
        except (ValueError,AttributeError):valid=False
        if not valid or uid in domain:raise Unproved('uuid_domain')
        if not isinstance(item['net'],str) or item['kind'] not in {'pad','track','arc','via','zone'}:
            raise Unproved('item_domain')
        layers=item['layers']
        if not isinstance(layers,list) or not layers or any(not isinstance(x,str) for x in layers) or len(layers)!=len(set(layers)):
            raise Unproved('layer_domain')
        domain[uid]=item
    if not isinstance(report,dict) or not isinstance(report.get('violations'),list):
        raise Unproved('report_domain')
    allowed_ignored={'missing_courtyard','track_not_centered_on_via','tuning_profile_track_geometries','footprint_filters_mismatch','footprint_type_mismatch'}
    if report.get('included_severities')!=['error','warning','exclusion']:
        raise Unproved('severity_domain')
    ignored=report.get('ignored_checks')
    if not isinstance(ignored,list) or any(not isinstance(value,dict)
            or not isinstance(value.get('description'),str)
            or not isinstance(value.get('key'),str) or value['key'] not in allowed_ignored
            for value in ignored):
        raise Unproved('ignored_constraint_unproved')
    mapped=[];unmapped=[];other_levels=[]
    for violation in report['violations']:
        check_current()
        if not isinstance(violation,dict):raise Unproved('report_domain')
        if violation.get('type')!='clearance':continue
        if violation.get('severity') not in {'error','warning'}:
            raise Unproved('excluded_clearance_unproved')
        rows=violation.get('items')
        if not isinstance(rows,list) or len(rows)!=2:raise Unproved('pair_domain')
        ids=[row.get('uuid') if isinstance(row,dict) else None for row in rows]
        if any(not isinstance(uid,str) for uid in ids) or len(set(ids))!=2 or any(uid not in domain for uid in ids):raise Unproved('pair_domain')
        a,b=(domain[uid] for uid in ids)
        if (a['net'] and a['net']==b['net']) or not set(a['layers'])&set(b['layers']):
            raise Unproved('pair_domain')
        pair={'uuids':ids,'nets':[a['net'],b['net']],
              'violation_scope':'original_constraints_plus_measured_global_floor'}
        required=max(factory_global_floor_iu,*(floors_iu.get(n,0) for n in pair['nets']))
        pair['captured_floor_iu']=required
        (mapped if required==measured_floor_iu else other_levels if required else unmapped).append(pair)
    check_current()
    return {'mapped_violations':mapped,'unmapped_violations':unmapped,
            'other_floor_violations':other_levels,'measured_floor_iu':measured_floor_iu,
            'mapped_floor_legal':not mapped,'comparison_authority':False}
