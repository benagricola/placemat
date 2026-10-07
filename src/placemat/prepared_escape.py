"""Prepare full native escape snapshots; no search adoption before parity.

Only setup reads Python occupancy, intent and pair rules. Candidate geometry,
nearest targets, all escape judgements and non-escape terms stay native.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import geometry
from .escapes import _layer_bits, _net_sizes, _pads_of, _unconnected, judging, search_near
from .placement import Placement
from .values import Location

CONTACT, PATH, HOLE, BAN = 1, 2, 4, 8


def _moving_roles(shapes, pools):
    """Validate full transformed pool membership against original source order.

    The two occupancy reads independently transform the same source snapshot.
    Equality must match all metadata and geometry, not just an owner or box.
    Partial membership of equal islands is ambiguous: refuse instead of
    assigning a role to the wrong original source identity.
    """
    masks = [0] * len(shapes)
    for role, pool in pools:
        seen = set()
        for member in pool:
            if id(member) in seen:
                continue
            equal = [i for i, source in enumerate(shapes) if source == member]
            members = [s for s in pool if s == member]
            seen.update(map(id, members))
            if not equal or len(equal) != len(members):
                return None
            for index in equal:
                masks[index] |= role
    return masks


def _record(shape):
    box = shape.box
    return (shape.owner, shape.kind, shape.net, shape.label, _layer_bits(shape.layers), list(shape.poly),
            (box.left, box.top, box.right, box.bottom), list(shape.ends), bool(shape.lane), shape.wire)


@dataclass(frozen=True)
class PreparedEscape:
    snapshot: object
    candidate: object
    scoring: object
    surface: object
    rotations: tuple
    face: object

    def evaluate(self, placement, turn, *, inspect=False):
        self.snapshot._check_snapshot()
        if type(turn) is not int or not 0 <= turn < len(self.rotations):
            raise ValueError('prepared escape turn is outside the frozen rotation set')
        if placement.face != self.face or placement.rotation != self.rotations[turn]:
            raise ValueError('prepared escape pose differs from its frozen face or turn; rebuild the snapshot')
        if placement.arrangement and placement.arrangement != getattr(self.snapshot.item, 'arrangement', ''):
            raise ValueError('prepared escape arrangement differs from its frozen source; rebuild the snapshot')
        return self.surface.evaluate(self.candidate, self.scoring, placement.location.x, placement.location.y, turn, inspect)


def prepare(delta, rotations, face):
    """Return a full prepared snapshot or an explicit unsupported reason.

    Refused native geometry propagates: it must not become a zero-price or
    certified result. Callers can separately invoke the independent oracle.
    """
    rotations = tuple(rotations)
    delta._check_snapshot()
    if delta.board._escapes:
        return None, 'declared escape lanes require the exact Python objective'
    native = geometry._native
    if native is None or not hasattr(native, 'PreparedSurface'):
        return None, 'full native escape kernel unavailable'
    kernel = delta.native(rotations, face)
    if kernel is None:
        return None, 'non-escape snapshot unsupported'
    candidate = delta.native_shapes(rotations, face)
    if candidate is None:
        return None, 'source polygon snapshot unsupported'
    occ = delta.occ
    base = judging(occ)
    contact = [s for pool in base._blockers.values() for s in pool]
    path = search_near(occ)
    holes = [s for ref, g in occ.items.items() if ref not in occ.pending for s in g.shapes if s.kind == 'npth']
    bans = [s for pool in [occ.copper] + [g.shapes for ref, g in occ.items.items() if ref not in occ.pending]
            for s in pool if s.kind == 'viaban']
    rest = []
    seen = set()
    for shape in contact + path + holes + bans:
        if id(shape) not in seen:
            seen.add(id(shape))
            rest.append(shape)
    rest_membership = {}
    for role, pool in [(CONTACT, contact), (PATH, path), (HOLE, holes), (BAN, bans)]:
        for shape in pool:
            rest_membership[id(shape)] = rest_membership.get(id(shape), 0) | role
    rest_roles = [rest_membership[id(s)] for s in rest]
    moving_roles, moving_shapes, field_turns = [], [], {}
    pads_by_ref = {}
    for rotation in rotations:
        origin = Placement(Location(0, 0), rotation, face)
        placed, copper = occ.placed_geometries(delta.item, origin)
        # The original-source native transform preserves this exact order.
        shapes = occ.candidate_shapes(delta.item, origin)[1]
        new_contact = [s for ref, g in placed.items() if occ.geometry.has_footprint(ref)
                       for s in g.shapes if s.owner == ref and s.kind in ('pad', 'through', 'npth')]
        new_contact += [s for s in copper if s.kind in ('copper', 'through')]
        new_path = [s for g in placed.values() for s in g.shapes if s.kind in ('pad', 'through')]
        new_path += [s for s in copper if s.kind in ('copper', 'through')]
        new_holes = [s for g in placed.values() for s in g.shapes if s.kind == 'npth']
        new_bans = [s for pool in [copper] + [g.shapes for g in placed.values()] for s in pool if s.kind == 'viaban']
        roles = _moving_roles(shapes, [(CONTACT, new_contact), (PATH, new_path),
                                       (HOLE, new_holes), (BAN, new_bans)])
        if roles is None:
            return None, 'transformed pool source association is missing or ambiguous'
        moving_roles.append(roles)
        moving_shapes.append(shapes)
        active = {ref: g for ref, g in occ.items.items() if ref not in occ.pending}
        active.update(placed)
        for ref, g in sorted(active.items()):
            if not occ.geometry.has_footprint(ref):
                continue
            pads = _pads_of(g.shapes, ref)
            intent = [(number, net, _unconnected(occ, ref, number, net)) for number, (net, _, _) in pads.items()]
            if ref in pads_by_ref and pads_by_ref[ref] != intent:
                return None, 'candidate changes pad intent grouping'
            pads_by_ref[ref] = intent
            radians = math.radians(g.reference.rotation)
            field_turns.setdefault(ref, []).append((g.reference.rotation, math.cos(radians), math.sin(radians)))
    if not moving_shapes or any(len(shapes) != len(moving_shapes[0]) for shapes in moving_shapes):
        return None, 'candidate source shape count changes'
    # Original owner/net/wire rules are geometry independent. Net intent must
    # not be weakened by candidate copper or the order in which it is tested.
    nets = sorted({net for pads in pads_by_ref.values() if len(pads) >= occ.settings.place_escape_min_pads
                   for _, net, _ in pads if net})
    if len(nets) * (len(rest) + len(moving_shapes[0])) > 4_000_000:
        return None, 'pair-clearance snapshot exceeds bounded capacity'
    sizes, geom = _net_sizes(occ), occ.geometry
    cfg = occ.settings
    rules = occ.rules.largest() if occ.rules else 0.0
    class_clearance = max((c.clearance for c in geom.netclasses.values()), default=0.0)
    net_records = []
    for net in nets:
        nc = geom.netclass(net)
        clearance = max(nc.clearance, geom.hole_clearance, rules, class_clearance)
        reach = max(nc.track_width / 2.0, nc.via_diameter / 2.0) + clearance
        pairs = [occ.pair_clearance(net, s.net, '', s.owner, True, s.wire)[0]
                 if role & CONTACT and s.kind in ('pad', 'through', 'copper') and s.net != net else 0.0
                 for s, role in zip(rest + list(moving_shapes[0]), rest_roles + moving_roles[0])]
        net_records.append((net, sizes.get(net, 0), net in occ.quiet_nets, nc.track_width, nc.clearance,
                            nc.via_diameter, nc.via_drill, reach, pairs))
    fields = [(ref, pads, field_turns[ref]) for ref, pads in sorted(pads_by_ref.items())]
    surface = native.PreparedSurface(candidate, kernel, [_record(s) for s in rest],
        [fp.ref for fp in geom.footprints], rest_roles, moving_roles, fields, net_records,
        (cfg.score_escape_reach, cfg.score_escape_depth, cfg.place_escape_cell, cfg.place_escape_min_pads,
         geom.drc_epsilon, geom.hole_clearance, cfg.place_escape_lane_via_exit))
    return PreparedEscape(delta, candidate, kernel, surface, tuple(rotations), face), None
