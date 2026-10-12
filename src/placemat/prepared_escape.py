"""Prepare full native escape snapshots; no search adoption before parity.

Only setup reads Python occupancy, intent and pair rules. Candidate geometry,
nearest targets, all escape judgements and non-escape terms stay native.
"""
from __future__ import annotations

import math
import weakref
from dataclasses import dataclass
from operator import itemgetter

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
    try:
        by_shape = {}
        for i, source in enumerate(shapes):
            by_shape.setdefault(source, []).append(i)
    except TypeError:               # a shape with an unhashable field: compare each pair, as before
        by_shape = None
    if by_shape is not None:
        for role, pool in pools:
            counts = {}
            for member in pool:
                counts[member] = counts.get(member, 0) + 1
            for member, count in counts.items():
                equal = by_shape.get(member, [])
                if not equal or len(equal) != count:
                    return None
                for index in equal:
                    masks[index] |= role
        return masks
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


# Each shape's record by its identity, the shape held with it so its id stays its own while the entry lives. A shape
# is frozen, so its record never changes. Cleared past _RECORDS_MAX.
_RECORDS = {}
_RECORDS_MAX = 200_000


def _field(occ, ref, g):
    """(its pads' intent, its turn as (rotation, cos, sin)) of a footprint's field where `g` stands."""
    pads = _pads_of(g.shapes, ref)
    intent = [(number, net, _unconnected(occ, ref, number, net)) for number, (net, _, _) in pads.items()]
    radians = math.radians(g.reference.rotation)
    return intent, (g.reference.rotation, math.cos(radians), math.sin(radians))


def _record(shape):
    hit = _RECORDS.get(id(shape))
    if hit is None or hit[0] is not shape:
        box = shape.box
        hit = shape, (shape.owner, shape.kind, shape.net, shape.label, _layer_bits(shape.layers), list(shape.poly),
                      (box.left, box.top, box.right, box.bottom), list(shape.ends), bool(shape.lane), shape.wire)
        if len(_RECORDS) >= _RECORDS_MAX:
            _RECORDS.clear()
        _RECORDS[id(shape)] = hit
    return hit[1]


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


# Whether prepared surfaces share rest pads across lifted boards (`memo_of`): False measures without it (a measurement
# switch, as escapes.BASELINE_MEMO is; never a setting).
NATIVE_MEMO = True
_MEMOS = weakref.WeakKeyDictionary()
_PRICES = weakref.WeakKeyDictionary()


def _picked(values, indices) -> list:
    """`[values[i] for i in indices]`, picked at C speed."""
    if not indices:
        return []
    if len(indices) == 1:
        return [values[indices[0]]]
    return list(itemgetter(*indices)(values))


def _pair_prices(occ):
    """The pair clearances `prepare` has asked `occ` for, by net and then (other net, owner, wire) (0.0 for its own
    net), kept for its life: a pair's clearance comes from the board's net classes and rules, which do not change while
    the occupancy lives."""
    held = _PRICES.get(occ)
    if held is None or held[0] is not occ.rules:     # rules replaced: price afresh
        held = _PRICES[occ] = (occ.rules, {})
    return held[1]


def memo_of(occ):
    """The native memo of rest pads that every prepared surface on `occ` shares, from one lifted board to the next
    (`EscapeMemo`): each surface checks it against its own rest board, so it holds only what still applies. None
    without the native class."""
    native = geometry._native
    if native is None or not hasattr(native, 'EscapeMemo') or not NATIVE_MEMO:
        return None
    memo = _MEMOS.get(occ)
    if memo is None:
        memo = _MEMOS[occ] = native.EscapeMemo()
    return memo


def prepare(delta, rotations, face, *, rest_cache=False):
    """Return a full prepared snapshot or an explicit unsupported reason.

    Refused native geometry propagates: it must not become a zero-price or
    certified result. Callers can separately invoke the independent oracle.
    """
    rotations = tuple(rotations)
    delta._check_snapshot()
    if delta.board._escapes:
        return None, 'declared escape lanes require the exact Python objective'
    # Imported vias can carry a footprint's owner without being one of its
    # numbered pads. The prepared manifest currently identifies through
    # contacts by owner/pad, so this admitted geometry needs the Python oracle
    # until that manifest carries an explicit pad-versus-via source role.
    footprint_refs = {fp.ref for fp in delta.occ.geometry.footprints}
    pools = [delta.occ.copper] + [item.shapes for item in delta.occ.items.values()]
    if any(shape.kind == 'through' and shape.wire and shape.owner in footprint_refs
           for pool in pools for shape in pool):
        return None, 'footprint-owned imported via requires the exact Python objective'
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
    # The rest cache needs the lifted board's escape snapshot, whose index is the one `judging` would build here.
    base = delta._escape_delta.base if rest_cache else judging(occ)
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
    rest_fields = None
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
        if rest_fields is None:
            # The rest of the board's fields are the same at every turn: read once.
            rest_fields = {ref: _field(occ, ref, g) for ref, g in occ.items.items()
                           if ref not in occ.pending and ref not in placed and occ.geometry.has_footprint(ref)}
        for ref, g in placed.items():
            if not occ.geometry.has_footprint(ref):
                continue
            intent, turn = _field(occ, ref, g)
            if ref in pads_by_ref and pads_by_ref[ref] != intent:
                return None, 'candidate changes pad intent grouping'
            pads_by_ref[ref] = intent
            field_turns.setdefault(ref, []).append(turn)
    for ref, (intent, turn) in (rest_fields or {}).items():
        pads_by_ref[ref] = intent
        field_turns[ref] = [turn] * len(moving_shapes)
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
    # Each shape's pair clearance depends only on its (net, owner, wire): the distinct keys are priced once per net
    # (and kept on the occupancy across lifted boards), and each shape reads its key's price.
    keys, key_index, classes = [], {}, []
    for s, role in zip(rest + list(moving_shapes[0]), rest_roles + moving_roles[0]):
        if role & CONTACT and s.kind in ('pad', 'through', 'copper'):
            key = s.net, s.owner, s.wire
            if key not in key_index:
                key_index[key] = len(keys)
                keys.append(key)
            classes.append(key_index[key])
        else:
            classes.append(-1)
    priced = _pair_prices(occ)
    wanted = set(keys)
    net_records = []
    for net in nets:
        nc = geom.netclass(net)
        clearance = max(nc.clearance, geom.hole_clearance, rules, class_clearance)
        reach = max(nc.track_width / 2.0, nc.via_diameter / 2.0) + clearance
        known = priced.setdefault(net, {})
        for key in wanted - known.keys():
            known[key] = occ.pair_clearance(net, key[0], '', key[1], True, key[2])[0] if key[0] != net else 0.0
        row = _picked(known, keys) + [0.0]     # [-1]: a shape with no pair
        pairs = _picked(row, classes)
        net_records.append((net, sizes.get(net, 0), net in occ.quiet_nets, nc.track_width, nc.clearance,
                            nc.via_diameter, nc.via_drill, reach, pairs))
    fields = [(ref, pads, field_turns[ref]) for ref, pads in sorted(pads_by_ref.items())]
    memo = memo_of(occ)
    surface = native.PreparedSurface(candidate, kernel, [_record(s) for s in rest],
        [fp.ref for fp in geom.footprints], rest_roles, moving_roles, fields, net_records,
        (cfg.score_escape_reach, cfg.score_escape_depth, cfg.place_escape_cell, cfg.place_escape_min_pads,
         geom.drc_epsilon, geom.hole_clearance, cfg.place_escape_lane_via_exit), *([memo] if memo is not None else []))
    if rest_cache:
        if not hasattr(surface, 'configure_rest_cache'):
            return None, 'complete native rest-field cache unavailable'
        baseline = delta._escape_delta
        from .escapes import Way
        ways = baseline.ways                # built once: the property makes a new dict each time it is read
        regular = {key for key, way in ways.items() if way is Way.WALLED}
        declared = {key for key in baseline.nets if baseline._base_walls(key)[0]}
        handoffs = {key for key in baseline.nets if baseline._base_walls(key)[1]}
        numbers = {None: 4, Way.SURFACE: 0, Way.VIA: 1, Way.AWAY: 2, Way.WALLED: 3}
        records = []
        moving_owners = {shape.owner for shape in moving_shapes[0]}
        for ref, pads, _ in fields:
            if ref in moving_owners or any((ref, number) not in baseline.regions for number, _, _ in pads):
                continue
            cached = []
            for number, net, unconnected in pads:
                key = ref, number
                # Extra conservative margin for the two-mm blocker buckets
                # and supplemental depth+1 grid prefilter. The full baseline
                # region already includes every lane/spot and own-copper chain
                # with maximal class/rule/hole/via reach and one search cell.
                region = baseline._wall_regions[key]
                cached.append((number, net, unconnected, numbers[ways.get(key)],
                               (region.left, region.top, region.right, region.bottom),
                               key in regular or key in declared, key in handoffs))
            records.append((ref, cached))
        surface.configure_rest_cache(candidate, kernel, records)
    return PreparedEscape(delta, candidate, kernel, surface, tuple(rotations), face), None
