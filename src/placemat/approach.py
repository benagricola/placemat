"""A pad's approach toward what it joins, pinched between two other nets' copper: the `escape.pinched` finding.

Each pad of a net that is not quiet (a plane's, a free net's) is followed along its airwire toward its nearest target,
the nearest pad or copper of its net the ratsnest joins it to, from the pad out to `place.approach_reach`, or to the
target when that is nearer. A corridor `place.approach_detour` to either side of that airwire is the room a track has
to get there without a long way round. On the pad's layer two things stand in it:

- the copper of every other net: pads, and planned tracks and vias. Pours are left out: they give way to a track;
- the airwires of the other nets that are not quiet and join two pads on that layer, those that do not cross this
  airwire: a way round that crosses one is not a way round, since one of the two would have to leave the layer. (One
  that crosses this airwire is crossed whichever way the net goes.)

A pinch is two pads or pieces of copper of two different nets and two different parts, neither the pad's own part nor
the target's (their pin fields are the escape findings'), on either side of the airwire with the airwire passing
between them, closer together than the pad's track width plus its clearance to each (the net's class against theirs,
and the script's clearance rules: `Occupancy.pair_clearance`). Two pieces of one net, or the pads of one part, are no
pinch: the airwire crosses that net's copper or that part. A pinch is a finding when no track gets from the pad to the
corridor's far end inside the corridor without crossing one of those airwires (the copper, grown by half the track and
its clearance, and the airwires join one side of the corridor to the other), and one would if the pinch were wide
enough: with its two parts (or pieces of copper) taken as far enough apart, the corridor opens. A wall with no such
pinch, a module's copper across the airwire, is no finding: no gap in it is the way. The narrowest such pinch is the
one named, the one nearer the pad among equals.

A pad on more than one layer (through-hole) is a finding only when every layer it is on is closed so. A pinch met from
both ends of one airwire is reported once. It is judged once on the finished board (Board._report_approaches), never
in the placement search."""
from __future__ import annotations

import math

from .geometry import poly_distance, segments_intersect
from .pinmap_rules import natural
from .ratsnest import _cells as _rn_cells
from .values import Box, CopperLayer

_LINE = 1e-6        # mm: an airwire's reach in the wall, a line a track may not cross but may run beside


def pinched(occ, esc) -> list:
    """The facts of each `escape.pinched` finding on the board as it stands: `esc` is the board's Escapes, whose grid of
    placed pads and planned copper is the spatial index the corridors are looked up in; the ratsnest's own grid gives
    the airwires near each corridor."""
    s = occ.settings
    geom = occ.geometry
    rn = occ.ratsnest()
    nearest: dict = {}
    for net in sorted(rn._edges):
        if net in occ.quiet_nets:
            continue
        for e in rn._edges[net]:
            for a, b in ((e.a, e.b), (e.b, e.a)):
                if not a.ref or a.ref in occ.pending or not geom.has_footprint(a.ref):
                    continue
                d = math.hypot(b.x - a.x, b.y - a.y)
                k = (a.ref, a.number)
                if d > 1e-6 and (k not in nearest or d < nearest[k][0]):
                    nearest[k] = (d, net, a, b)
    margin = max([geom.default_clearance] + [nc.clearance for nc in geom.netclasses.values()]) + 0.5
    layers_of: dict = {}

    def pad_layers(ref, number) -> frozenset:
        k = (ref, number)
        if k not in layers_of:
            layers_of[k] = frozenset().union(*[p.layers for p in esc._blockers.get(ref, ())
                                               if p.label == number and p.kind in ("pad", "through")])
        return layers_of[k]
    clears: dict = {}                       # net -> {(other net, owner, wire): a track centre's reach}
    out, seen = [], set()
    for ref, number in sorted(nearest, key=lambda k: (k[0], natural(k[1]))):
        d, net, a, b = nearest[(ref, number)]
        found = _pad(occ, esc, rn, pad_layers, clears, ref, number, net, a, b, d, s.place_approach_reach,
                     s.place_approach_detour, margin)
        if found is None:
            continue
        facts, key = found
        if key not in seen:
            seen.add(key)
            out.append(facts)
    return out


def _pad(occ, esc, rn, pad_layers, clears, ref, number, net, a, b, d, reach, detour, margin):
    """(facts, the pinch's key) when the pad's approach is pinched on every layer it is on, else None."""
    pads = [p for p in esc._blockers.get(ref, ()) if p.label == number and p.kind in ("pad", "through")]
    if not pads:
        return None
    nc = occ.geometry.netclass(net)
    half = nc.track_width / 2.0
    ux, uy = (b.x - a.x) / d, (b.y - a.y) / d
    end = min(reach, d)

    def local(pt):
        dx, dy = pt[0] - a.x, pt[1] - a.y
        return dx * ux + dy * uy, dy * ux - dx * uy

    corners = [(a.x + ux * s - uy * t, a.y + uy * s + ux * t) for s in (0.0, end) for t in (-detour, detour)]
    box = Box.of_points(corners).inflate(half + margin)
    ends = frozenset(r for r in (ref, b.ref) if r)
    near = [sh for sh in esc._bgrid.near(box)
            if (sh.kind in ("pad", "through") or (sh.kind == "copper" and sh.wire))
            and (sh.net != net or not net) and sh.box.overlaps(box)]
    wires: dict = {}                        # id -> airwire, filled on the first ask

    def lines_on(layer) -> list:
        """The other nets' airwires near the corridor that join two pads on `layer`, in the corridor's frame: looked up
        only for a corridor with a pinch on its airwire."""
        if not wires:
            wires[None] = None
            for c in _rn_cells((box.left, box.top), (box.right, box.bottom)):
                for e in rn._grid.get(c, ()):
                    if e.net != net and e.net not in occ.quiet_nets and e.a.ref and e.b.ref:
                        wires[id(e)] = e
        return [(local((e.a.x, e.a.y)), local((e.b.x, e.b.y))) for e in wires.values()
                if e is not None and layer in pad_layers(e.a.ref, e.a.number) and layer in pad_layers(e.b.ref, e.b.number)]
    pad_t = [local(p)[1] for sh in pads for p in sh.poly]
    eps = occ.geometry.drc_epsilon
    reaches = clears.setdefault(net, {})

    def clearance(sh) -> float:
        k = (sh.net, sh.owner, sh.wire)
        if k not in reaches:
            reaches[k] = half + occ.pair_clearance(net, sh.net, "", sh.owner, True, sh.wire)[0] - eps
        return reaches[k]
    first = None
    for layer in CopperLayer:
        if not any(layer in p.layers for p in pads):
            continue
        hit = _layer(occ, clearance, [sh for sh in near if layer in sh.layers], lambda: lines_on(layer), local, end,
                     detour, min(pad_t), max(pad_t), eps, ends)
        if hit is None:
            return None                     # a way through on this layer
        if first is None:
            first = (layer, hit)
    if first is None:
        return None
    layer, (gap, need, at_s, sa, sb) = first
    at = [round(a.x + ux * at_s, 4), round(a.y + uy * at_s, 4)]
    facts = {"net": net, "pad": [ref, number], "toward": [b.ref, b.number if b.ref else ""], "layer": layer.value,
             "neighbours": [_neighbour(occ, sh) for sh in (sa, sb)], "gap_mm": round(gap, 4), "need_mm": round(need, 4),
             "track_mm": nc.track_width, "detour_mm": detour, "at": at}
    return facts, (net, layer, frozenset((id(sa), id(sb))))


def _layer(occ, clearance, shapes, lines_on, local, end, detour, pad_tlo, pad_thi, eps, ends):
    """(gap, need, the pinch's place along the airwire, its two shapes) of the narrowest pinch whose widening alone would
    open the corridor on one layer, or None when a track gets through or no such pinch is in the wall. `lines_on()`
    gives the other nets' airwires on the layer, each as its two ends in the corridor's frame (along, across); `ends`
    the parts at the airwire's two ends, whose pads wall the corridor but are no side of a pinch; `clearance(shape)` how
    far a track's centre keeps from a shape: half the track and their clearance, less the DRC epsilon."""
    rough = []                              # (shape, its reach, its box's centre across, its box's half diagonal)
    for sh in shapes:
        r = clearance(sh)
        bx = sh.box
        cs, ct = local((bx.center.x, bx.center.y))
        h = math.hypot(bx.width, bx.height) / 2.0
        if cs - h - r < end and cs + h + r > 0.0 and abs(ct) - h - r < detour:
            rough.append((sh, r, ct, h))
    n = len(rough)
    if n < 2:
        return None
    reach = 2.0 * max(x[1] for x in rough)
    obs: list = [None] * n

    def ob(k):
        """The shape in the corridor's frame: (shape, reach, points, along from, along to, across from, across to)."""
        if obs[k] is None:
            sh, r = rough[k][0], rough[k][1]
            pts = [local(p) for p in sh.poly]
            ss, ts = [p[0] for p in pts], [p[1] for p in pts]
            obs[k] = (sh, r, pts, min(ss), max(ss), min(ts), max(ts))
        return obs[k]
    by_line = [k for k, x in enumerate(rough) if abs(x[2]) - x[3] < reach]      # within a pinch's reach of the airwire
    pinches = []
    for x, i in enumerate(by_line):
        shi, ri, _, s0i, s1i, t0i, t1i = ob(i)
        for j in by_line[x + 1:]:
            shj, rj, _, s0j, s1j, t0j, t1j = ob(j)
            if not ((t1i < 0.0 < t0j) or (t1j < 0.0 < t0i)) or (shi.net and shi.net == shj.net) \
                    or (shi.owner and shi.owner == shj.owner and occ.geometry.has_footprint(shi.owner)) \
                    or shi.owner in ends or shj.owner in ends:
                continue
            need = ri + rj
            if s0j - s1i >= need or s0i - s1j >= need or t0j - t1i >= need or t0i - t1j >= need:
                continue
            gap = poly_distance(shi.poly, shj.poly)
            at = (max(s0i, s0j) + min(s1i, s1j)) / 2.0
            if gap < need and 0.0 <= at <= end:
                pinches.append((round(gap, 6), at, i, j))
    if not pinches:
        return None                         # nothing narrow on the airwire: no need to ask whether the corridor is shut
    obs = [ob(k) for k in range(n)]
    touching = []
    for i in range(n):
        shi, ri, _, s0i, s1i, t0i, t1i = obs[i]
        for j in range(i + 1, n):
            shj, rj, _, s0j, s1j, t0j, t1j = obs[j]
            need = ri + rj
            if s0j - s1i >= need or s0i - s1j >= need or t0j - t1i >= need or t0i - t1j >= need:
                continue
            if poly_distance(shi.poly, shj.poly) < need:
                touching.append((i, j))
    # an airwire that crosses this one is a crossing whichever way this net goes: only those on one side wall it in
    walls = [c for c in (_clip(p, q, end, detour) for p, q in lines_on())
             if c is not None and not segments_intersect(c[0], c[1], (0.0, 0.0), (end, 0.0))]
    m = len(walls)
    left, right = n + m, n + m + 1         # the corridor's two sides, each with the back of it beside the pad
    sides = []                             # (node, side) joins that no pinch's widening changes
    left_back = ((0.0, min(max(pad_thi, 0.0), detour)), (0.0, detour))
    right_back = ((0.0, -detour), (0.0, max(min(pad_tlo, 0.0), -detour)))
    for i, (sh, r, pts, s0, s1, t0, t1) in enumerate(obs):
        if t1 + r > detour or (s0 - r < 0.0 and t1 + r > left_back[0][1] and _seg_gap(pts, *left_back) < r):
            sides.append((i, left))
        if t0 - r < -detour or (s0 - r < 0.0 and t0 - r < right_back[1][1] and _seg_gap(pts, *right_back) < r):
            sides.append((i, right))
    for k, (p, q) in enumerate(walls):
        w = n + k
        if max(p[1], q[1]) >= detour - _LINE or (min(p[0], q[0]) <= _LINE and _seg_gap([p, q], *left_back) < _LINE):
            sides.append((w, left))
        if min(p[1], q[1]) <= -detour + _LINE or (min(p[0], q[0]) <= _LINE and _seg_gap([p, q], *right_back) < _LINE):
            sides.append((w, right))
        for i, (_, r, pts, s0, s1, t0, t1) in enumerate(obs):
            if (min(p[0], q[0]) < s1 + r and max(p[0], q[0]) > s0 - r and min(p[1], q[1]) < t1 + r
                    and max(p[1], q[1]) > t0 - r and _seg_gap(pts, p, q) < r):
                sides.append((w, i))
    geom = occ.geometry

    def unit(i):
        """What a pinch widens as one: a part's pads move together, a piece of copper alone."""
        sh = obs[i][0]
        return sh.owner if sh.owner and geom.has_footprint(sh.owner) else ("copper", i)

    def shut(apart=None) -> bool:
        """Whether the corridor is closed, with the two units of `apart` taken as far enough apart."""
        parent = list(range(n + m + 2))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for i, j in touching:
            if apart is None or {unit(i), unit(j)} != apart:
                parent[find(i)] = find(j)
        for x, y in sides:
            parent[find(x)] = find(y)
        return find(left) == find(right)
    if not shut():
        return None
    # the narrowest pinch whose widening alone would open the corridor: the approach's only way, and too narrow for it
    for gap, at, i, j in sorted(pinches):
        if not shut({unit(i), unit(j)}):
            lo, hi = sorted((obs[i], obs[j]), key=lambda o: o[5])          # in order across the airwire
            return gap, lo[1] + hi[1] + 2.0 * eps, at, lo[0], hi[0]
    return None


def _clip(p, q, end, detour):
    """The part of segment pq inside the corridor (0 to `end` along, `detour` either side), or None (Liang-Barsky)."""
    (x0, y0), (x1, y1) = p, q
    dx, dy = x1 - x0, y1 - y0
    lo, hi = 0.0, 1.0
    for d, room in ((-dx, x0), (dx, end - x0), (-dy, y0 + detour), (dy, detour - y0)):
        if d == 0.0:
            if room < 0.0:
                return None
            continue
        r = room / d
        if d < 0.0:
            lo = max(lo, r)
        else:
            hi = min(hi, r)
        if lo > hi:
            return None
    return (x0 + lo * dx, y0 + lo * dy), (x0 + hi * dx, y0 + hi * dy)


def _seg_gap(pts, p, q) -> float:
    """The least distance from the polygon (or the segment, two points) `pts` to the segment pq; 0 where they meet."""
    return math.inf if p == q else poly_distance(pts, (p, q))


def _neighbour(occ, sh) -> dict:
    """A shape of a pinch as a finding names it: a pad (its part, the part's cell, its number), an escape's lane, a track
    or a via (the cell that owns it, if one does); and its net."""
    geom = occ.geometry
    if sh.lane:
        kind = "lane"
    elif sh.kind in ("pad", "through") and sh.label and geom.has_footprint(sh.owner):
        kind = "pad"
    else:
        kind = "via" if sh.kind == "through" else "track"
    ref = sh.owner if kind == "pad" else ""
    cell = (geom.footprint(ref).cell or "") if ref else (sh.owner if sh.owner in geom.cells else "")
    return {"kind": kind, "ref": ref, "cell": cell, "pin": sh.label if kind == "pad" else "", "net": sh.net,
            "lane": sh.lane}
