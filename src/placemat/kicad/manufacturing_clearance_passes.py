"""Finite clearance passes over one immutable original-filled board snapshot."""
from copy import deepcopy
import hashlib
import json
from .manufacturing_clearance_report import partition, Unproved


def seal(value):
    try:
        return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()
    except (ValueError,TypeError,OverflowError) as error:
        raise Unproved('input_domain') from error


def measure_distinct(floors_iu, *, snapshot, items, measure, check_current, check_loop=None, factory_global_floor_iu=0):
    """Owned caller supplies native custody and its existing absolute deadline.

`measure` must enforce that deadline and preserve the snapshot's filled copper;
this function neither creates a budget nor issues a routing proposal.
"""
    if not isinstance(floors_iu, dict):
        raise Unproved('map_domain')
    if any(type(value) is not int or value < 0 for value in floors_iu.values()):
        raise Unproved('map_domain')
    loop_check=check_loop if check_loop is not None else lambda:check()
    if type(factory_global_floor_iu) is not int or factory_global_floor_iu<0:
        raise Unproved('factory_floor_domain')
    levels={max(factory_global_floor_iu,value) for value in floors_iu.values()}
    if factory_global_floor_iu:levels.add(factory_global_floor_iu)
    levels.discard(0)
    if not levels:raise Unproved('floor_pass_domain')
    bound_floors=deepcopy(floors_iu)
    bound_items=deepcopy(items)
    bound_sha=seal([bound_floors,bound_items])
    def check():
        check_current(snapshot)
        if seal([floors_iu,items])!=bound_sha:
            raise Unproved('map_inventory_changed')
    check()
    partition({'violations': [], 'included_severities':['error','warning','exclusion'], 'ignored_checks':[]}, bound_items, bound_floors,
              measured_floor_iu=min(levels),check_current=loop_check,
              factory_global_floor_iu=factory_global_floor_iu)
    results = []
    for floor in sorted(levels):
        check()
        report = measure(snapshot, floor)
        check()
        result = partition(report, bound_items, bound_floors, measured_floor_iu=floor,
                           check_current=loop_check, factory_global_floor_iu=factory_global_floor_iu)
        results.append(result)
    check()
    return {'passes': results,
            'mapped_violations': [pair for result in results
                                  for pair in result['mapped_violations']],
            'mapped_floor_legal': all(result['mapped_floor_legal']
                                     for result in results),
            'comparison_authority': False}
