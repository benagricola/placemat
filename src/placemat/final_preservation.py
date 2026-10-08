"""Exact original physical preservation in the owned worker only."""
from collections import Counter
from dataclasses import fields
import json
import math
from pathlib import Path
import re

from placemat.pinmap_common import CandidateRefused


def refuse(reason):
    raise CandidateRefused('final_preservation_unproved', reason)


def facts(value):
    from placemat.board_geometry import Footprint, PadGeom, NetClass, RuleArea, CopperItem
    from placemat.values import Location, Box, Face, CopperLayer
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            refuse('nonfinite physical identity')
        return value
    if type(value) in (Face, CopperLayer):
        return {'enum': type(value).__name__, 'value': value.value}
    if type(value) in (Footprint, PadGeom, NetClass, RuleArea, CopperItem, Location, Box):
        return {'type': type(value).__name__, 'fields': {f.name: facts(getattr(value, f.name)) for f in fields(value)}}
    if type(value) in (tuple, list):
        return [facts(v) for v in value]
    if type(value) in (set, frozenset):
        return sorted((facts(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if type(value) is dict:
        return sorted(([facts(k), facts(v)] for k, v in value.items()), key=lambda v: json.dumps(v[0], sort_keys=True))
    refuse('unsupported physical identity object')


def held(geometry):
    from placemat.board_geometry import BoardGeometry
    if type(geometry) is not BoardGeometry or len({fp.ref for fp in geometry.footprints}) != len(geometry.footprints):
        refuse('original physical geometry has ambiguous identities')
    keys = ('outline', 'board_polygon', 'nets', 'netclasses', 'default_clearance', 'layers',
            'edge_clearance', 'rule_areas', 'hole_to_hole', 'hole_clearance', 'silk_clearance',
            'min_track_width', 'drc_epsilon', 'pin_names', 'layer_types', 'copper_mm')
    return {'footprints': [facts(fp) for fp in sorted(geometry.footprints, key=lambda fp: fp.ref)],
            'rules_outline': {key: facts(getattr(geometry, key)) for key in keys}}


def forms(path):
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', Path(path).read_text())
    stack, roots = [], []
    for token in tokens:
        if token == '(':
            node = []
            (stack[-1] if stack else roots).append(node)
            stack.append(node)
        elif token == ')':
            if not stack:
                refuse('malformed board closing token')
            stack.pop()
        elif stack:
            stack[-1].append(token)
        else:
            refuse('board token outside form')
    if stack or len(roots) != 1 or not roots[0] or roots[0][0] != 'kicad_pcb':
        refuse('malformed board root')
    def frozen(value):
        return tuple(frozen(v) if isinstance(v, list) else v for v in value)
    fixed, zones = [], []
    for node in roots[0]:
        if not isinstance(node, list) or not node:
            continue
        if type(node[0]) is not str:
            refuse('malformed board form head')
        if node[0] in ('segment', 'arc', 'via') or node[0].startswith('gr_'):
            fixed.append(frozen(node))
        elif node[0] == 'zone':
            definition = []
            for value in node:
                if isinstance(value, list) and value:
                    if value[0] in ('filled_polygon', 'fill_segments'):
                        continue
                    # KiCad's direct zone fill yes atom is derived m_isFilled
                    # state. Retain every fill parameter and unknown token;
                    # graphic fills and nested yes atoms are not normalized.
                    if value[0] == 'fill' and len(value) > 1 and value[1] == 'yes':
                        value = [value[0], *value[2:]]
                definition.append(value)
            zones.append(frozen(definition))
    return tuple(sorted(fixed)), tuple(sorted(zones))


def manifest(geometry, pcb):
    original = held(geometry)
    fixed, zones = forms(pcb)
    original['fixed_copper'] = sorted((facts(c) for c in geometry.copper if c.kind != 'zone'),
                                     key=lambda c: json.dumps(c, sort_keys=True))
    original['protected_forms'] = {'fixed': facts(fixed), 'zones': facts(zones)}
    return original


def verify(source_geometry, source_pcb, final_geometry, final_pcb, expected_manifest):
    original = manifest(source_geometry, source_pcb)
    encoded = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if encoded(original) != encoded(expected_manifest):
        refuse('actual original geometry differs from retained executor manifest')
    if encoded(held(final_geometry)) != encoded({k: original[k] for k in ('footprints', 'rules_outline')}):
        refuse('final board changes original held physical geometry or intent')
    verify_fixed(source_geometry, source_pcb, final_geometry, final_pcb)
    return {'original_manifest': original, 'held_and_fixed_preserved': True}


def verify_fixed(source_geometry, source_pcb, final_geometry, final_pcb):
    """Original electrical copper and zone intent, separately from pad poses.

    The logical worker first proves its emitted input and final held domain.
    This additional check carries the original source's fixed copper through a
    permitted input permutation. It neither permits pad changes nor mints
    their authority, and newly routed copper can only be added.
    """
    canonical = lambda item: json.dumps(facts(item), sort_keys=True, separators=(',', ':'))
    original_copper = Counter(canonical(c) for c in source_geometry.copper if c.kind != 'zone')
    final_copper = Counter(canonical(c) for c in final_geometry.copper if c.kind != 'zone')
    if original_copper - final_copper:
        refuse('final board changes original non-zone electrical copper')
    fixed, zones = forms(source_pcb)
    final_fixed, final_zones = forms(final_pcb)
    if Counter(fixed) - Counter(final_fixed) or zones != final_zones:
        refuse('final board changes original fixed copper or zone definitions')
    original = manifest(source_geometry, source_pcb)
    return {key: original[key] for key in ('fixed_copper', 'protected_forms')}


def verify_fixed_after_permutation(source_geometry, source_pcb, written_geometry, written_pcb,
                                   final_geometry, final_pcb, pool_records):
    """Cross-input copper proof after exact emitted and final pad-domain checks.

    Only numbered lands changed by independently verified pool records can
    leave the original pad-net Counter. Ambiguous physical land identities
    refuse; ordinary fixed preservation remains strict.
    """
    verify(written_geometry, written_pcb, final_geometry, final_pcb,
           manifest(written_geometry, written_pcb))
    source_pads = {(fp.ref, pad.number): [] for fp in source_geometry.footprints for pad in fp.pads}
    written_pads = {(fp.ref, pad.number): [] for fp in written_geometry.footprints for pad in fp.pads}
    for geometry, table in ((source_geometry, source_pads), (written_geometry, written_pads)):
        for fp in geometry.footprints:
            for pad in fp.pads:
                table[fp.ref, pad.number].append(pad)
    changed = set()
    expected_nets = {key: {pad.net for pad in pads} for key, pads in source_pads.items()}
    if set(source_pads) != set(written_pads):
        refuse('permuted numbered land membership changed')
    for record in pool_records:
        for net, old, new in record['mapping']:
            if old != new:
                key = record['ref'], old
                if key not in source_pads or key not in written_pads:
                    refuse('permuted pad physical identity is missing')
                if any(p.net != net for p in source_pads[key]):
                    refuse('permuted original pad net is not proved')
                target = record['ref'], new
                if target not in written_pads or any(p.net != net for p in written_pads[target]):
                    refuse('permuted written pad net is not proved')
                expected_nets[target] = {net}
                changed.add(key)
    if any({pad.net for pad in written_pads[key]} != nets for key, nets in expected_nets.items()):
        refuse('unselected pad net changed outside proved permutation')
    def land(pad):
        return pad.owner, pad.net, pad.layers, pad.outlines, pad.box
    identities = {}
    for key, pads in source_pads.items():
        for pad in pads:
            identities.setdefault(land(pad), set()).add(key)
    permitted = set()
    for key in changed:
        for pad in source_pads[key]:
            identity = land(pad)
            if identities[identity] != {key}:
                refuse('permuted pad copper identity is ambiguous')
            permitted.add(identity)
    expected_lands = Counter(land(p) for key in changed for p in source_pads[key])
    actual_lands = Counter((c.owner, c.net, c.layers, c.outlines, c.box)
                           for c in source_geometry.copper if c.kind == 'pad'
                           and (c.owner, c.net, c.layers, c.outlines, c.box) in permitted)
    if expected_lands != actual_lands:
        refuse('permuted pad copper multiplicity is unproved')
    canonical = lambda item: json.dumps(facts(item), sort_keys=True, separators=(',', ':'))
    def omitted(item):
        return item.kind == 'pad' and (item.owner, item.net, item.layers, item.outlines, item.box) in permitted
    original = Counter(canonical(c) for c in source_geometry.copper if c.kind != 'zone' and not omitted(c))
    final = Counter(canonical(c) for c in final_geometry.copper if c.kind != 'zone')
    if original - final:
        refuse('final board changes original non-permuted electrical copper')
    fixed, zones = forms(source_pcb)
    final_fixed, final_zones = forms(final_pcb)
    if Counter(fixed) - Counter(final_fixed) or zones != final_zones:
        refuse('final board changes original fixed copper or zone definitions')
    retained = manifest(source_geometry, source_pcb)
    return {key: retained[key] for key in ('fixed_copper', 'protected_forms')}
