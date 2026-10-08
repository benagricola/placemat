"""Resolve captured KRT parser IDs to semantic names; native IDs are independent."""
import hashlib
import importlib
from pathlib import Path
import sys
from .manufacturing_inventory import sha,InventoryUnavailable


def resolve(path,effective,parser_path):
    parser_path=Path(parser_path).resolve()
    sys.path.insert(0,str(parser_path.parent))
    parser=importlib.import_module('kicad_parser')
    if Path(parser.__file__).resolve()!=parser_path:raise InventoryUnavailable('net_parser_origin_changed')
    parser_sha=sha(parser_path);raw=Path(path).read_bytes();source_sha=hashlib.sha256(raw).hexdigest()
    nets,_=parser.extract_nets(raw.decode())
    names=[net.name for net in nets.values() if net.name]
    if len(set(names))!=len(names):raise InventoryUnavailable('original_net_name_ambiguity')
    mapped={}
    for code,value in effective.items():
        if type(code) is not str or not code.isdigit() or str(int(code))!=code:raise InventoryUnavailable('captured_net_id_unproved')
        if type(value) not in (int,float):raise InventoryUnavailable('captured_clearance_unproved')
        import math
        try:finite=math.isfinite(value)
        except OverflowError:finite=False
        if not finite or value<0:raise InventoryUnavailable('captured_clearance_unproved')
        net=nets.get(int(code))
        if net is None or not net.name or net.name in mapped:raise InventoryUnavailable('captured_net_missing_or_duplicate')
        mapped[net.name]=value
    if sha(path)!=source_sha or sha(parser_path)!=parser_sha:raise InventoryUnavailable('net_parser_source_changed')
    return {'captured_map':effective,'semantic_map':mapped,'parser_sha256':parser_sha,'source_sha256':source_sha,
            'original_name_domain':sorted(names),'native_crosscheck_complete':False,'constraints_proved':False}


def crosscheck(board,proof):
    pairs=[(code,net.GetNetname()) for code,net in board.GetNetsByNetcode().items()]
    if any(type(code) is not int or code<0 or type(name) is not str for code,name in pairs):raise InventoryUnavailable('native_net_domain_unproved')
    names=[name for _,name in pairs if name]
    if len(set(names))!=len(names) or sorted(names)!=proof['original_name_domain']:
        raise InventoryUnavailable('native_net_domain_changed')
    return {'native_codes_by_name':{name:code for code,name in pairs if name},'native_name_domain_complete':True,
            'constraints_proved':False}
