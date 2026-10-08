"""Pure original selector/width verification for the retained factory.

Called with the executor's retained original read snapshot, never candidate
geometry. This pure verifier performs no additional native read or query.
"""
import json
from pathlib import Path


def verify_original_binding(factory, binding, original_geometry):
    from placemat.capture_nets import read_capture
    from placemat.checks import COPPER_OZ
    from placemat.kicad.phase_select import select
    from placemat.kicad.phase_run import comparison_obligations
    from placemat.kicad.width_policy import requests_of, validate_receipt, apply
    from placemat.route_phase import phases_of
    from placemat.kicad.final_call import file_hash, record_digest
    from placemat.pinmap_common import CandidateRefused

    def refuse(code, reason):
        raise CandidateRefused(code, reason)
    contract, paths = binding['contract'], binding['paths']
    cfg = factory._board.settings
    invocation = contract.get('invocation')
    expected = factory._invocation
    keys = {'phases', 'upto', 'only', 'layers', 'exclude_nets', 'pour_nets', 'quick',
            'capture', 'router_dir', 'router_python', 'width_query_input'}
    if not isinstance(invocation, dict) or set(invocation) != keys or invocation != expected:
        refuse('authority_invocation_mismatch', 'physical context differs from retained original invocation')
    if record_digest(contract) != binding['contract_sha256']:
        refuse('authority_binding_mismatch', 'physical binding digest differs from exact contract')
    phases = phases_of(cfg)
    if invocation['upto'] is not None or invocation['only'] is not False or invocation['phases'] != json.loads(json.dumps([p.key() for p in phases])):
        refuse('authority_phase_scope_unsupported', 'initial authority requires complete configured original phases')
    if contract['phases'] != invocation['phases']:
        refuse('authority_phase_contract_mismatch', 'physical phase list differs from original configured intent')
    if type(invocation['quick']) is not bool:
        refuse('authority_invocation_malformed', 'original quick flag must be a literal boolean')
    if invocation['quick']:
        refuse('authority_quick_scope_unsupported', 'initial authority excludes one-round routing scripts')
    query = invocation['width_query_input']
    if not isinstance(query, dict) or set(query) != {'path', 'sha256'} or query['path'] != paths['original'] or query['sha256'] != factory._inputs.get(query['path']):
        refuse('authority_width_query_mismatch', 'width query must bind the retained original source')
    for key in ('layers', 'exclude_nets', 'pour_nets'):
        values = invocation[key]
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
            refuse('authority_invocation_malformed', 'original layer/net scope must contain unique names')
    capture_record = invocation['capture']
    if not isinstance(capture_record, dict) or set(capture_record) != {'path', 'sha256'}:
        refuse('authority_capture_malformed', 'original capture identity is malformed')
    if capture_record['path'] is None:
        if capture_record['sha256'] is not None:
            refuse('authority_capture_malformed', 'absent original capture has a digest')
        capture = None
    else:
        path = Path(capture_record['path'])
        if not path.is_absolute() or factory._inputs.get(str(path)) != capture_record['sha256'] or file_hash(path) != capture_record['sha256']:
            refuse('authority_capture_changed', 'actual original capture is not retained unchanged')
        capture = read_capture(path)
    excluded = set(invocation['exclude_nets'])
    pours = set(invocation['pour_nets'])
    if not pours <= set(original_geometry.nets):
        refuse('authority_pours_mismatch', 'original resolved pour nets are absent from original geometry')
    selected = [select(phase, original_geometry, capture, open_nets=set(original_geometry.nets),
                       excluded=excluded, pour_nets=pours, route_layers=invocation['layers'],
                       rise_c=cfg.check_rise_c, copper_oz=COPPER_OZ) for phase in phases]
    chosen_pours = set().union(*(set(sel.pour_nets) for sel in selected))
    if sorted(chosen_pours) != contract['chosen_pours'] or sorted(excluded | (pours - chosen_pours)) != contract['counted']:
        refuse('authority_selection_mismatch', 'original selected pours/exclusions differ from physical context')
    obligations = comparison_obligations(selected, original_geometry, excluded)
    receipt_path = paths['width_receipt']
    if not isinstance(receipt_path, str) or not Path(receipt_path).is_absolute() or file_hash(receipt_path) != contract['width_receipt_sha256']:
        refuse('authority_width_receipt_changed', 'actual original resolver receipt is missing or changed')
    receipt = json.loads(Path(receipt_path).read_text())
    if receipt != contract['width_authority']:
        refuse('authority_width_receipt_mismatch', 'physical widths differ from actual original receipt')
    validate_receipt(receipt, pcb=query['path'], router_dir=invocation['router_dir'],
                     requests=requests_of(phases, selected, cfg))
    normalized = apply(obligations, selected, phases, receipt)
    if normalized != contract['obligations']:
        refuse('authority_obligations_mismatch', 'original stable obligations and widths differ from physical context')
    return selected
