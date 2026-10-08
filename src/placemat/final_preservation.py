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
