"""Task-private stricter derivative project for sufficient-positive measurement."""
from copy import deepcopy
from decimal import Decimal,InvalidOperation
import hashlib
import json

class Unsupported(ValueError):
    pass

def iu(value):
    if type(value) not in (int,float):raise Unsupported('clearance_scalar_unproved')
    try:n=Decimal(str(value))*1000000
    except InvalidOperation:raise Unsupported('clearance_scalar_unproved') from None
    if not n.is_finite() or n<0 or n!=n.to_integral_value() or n>2**31-1:
        raise Unsupported('clearance_scalar_unproved')
    return int(n)


def stricter(original_bytes, semantic_floors_mm):
    """One semantic project delta, never source or router input modification.

Original-rule-refilled saved copper must be checked by stricter DRC WITHOUT
refilling, with its filled geometry preserved. A complete error-free check is
a sufficient positive result only; a negative may concern unmapped nets and
cannot become a claimed mapped violation.
"""
    if (type(semantic_floors_mm) is not dict or not semantic_floors_mm
            or any(type(n) is not str or not n for n in semantic_floors_mm)):
        raise Unsupported('semantic_map_unproved')
    floors={n:iu(v) for n,v in semantic_floors_mm.items()}
    if any(v<=0 for v in floors.values()):raise Unsupported('semantic_map_unproved')
    original=json.loads(original_bytes)
    before=original['board']['design_settings']['rules']['min_clearance']
    floor=max(iu(before),*floors.values())
    derivative=deepcopy(original)
    derivative['board']['design_settings']['rules']['min_clearance']=floor/1000000
    reconstructed=deepcopy(derivative)
    reconstructed['board']['design_settings']['rules']['min_clearance']=before
    if reconstructed!=original:raise Unsupported('derivative_extra_change')
    encoded=(json.dumps(derivative,sort_keys=True,allow_nan=False)+'\n').encode()
    return encoded,{'original_sha256':hashlib.sha256(original_bytes).hexdigest(),
        'derivative_sha256':hashlib.sha256(encoded).hexdigest(),
        'delta_path':['board','design_settings','rules','min_clearance'],
        'before':before,'after':floor/1000000,'floor_iu':floor,
        'semantic_floors_iu':floors,'sufficient_positive_only':True,
        'original_rules_unchanged':True,'comparison_authority':False}
