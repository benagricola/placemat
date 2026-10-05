"""Lines between two parts whose pins stand in the reverse of the order their airwires land in: the `pins.reversed`
finding.

A line joins a pin of one part to a pin of another: a net with those two pads only, or two such nets either side of a
two-pad series part (a termination resistor), followed as the pin map study follows one (`pins.follow_series`,
`pins.follow_prefixes`). Two parts that are not series parts and share `pins.reversed_min` lines or more are a pair.

Along the axis across the line between the two parts' groups of pins, a part's pins of those lines stand in an order,
and so do the places their airwires from that part land: the other part's pins, or for a line through a series part,
that part's pad. A run of `pins.reversed_min` or more lines next to each other in the part's order whose landings fall
in the opposite order, whatever lands between them, is a reversed group. The pair's straight airwires (pin to pin, or
pin to series part to pin) are counted for crossings as they stand and with the run mirrored on the part, its pins
given to its lines the other way round. When the mirror leaves fewer it is a notice. A run found from both parts is
said once, mirrored on the part whose `Pm.PinPool` holds the run's pins if mirroring there removes any crossings, else
where it leaves the fewest; the other part is named too when mirroring there is as good.

The pin map study does this and more for a part with a `Pm.PinPool`, weighing every crossing, length and bend of its
nets, and advises a map that saves `pins.gain_min` of the part's whole total; a part it gives a `pins.remap` for is
left to that advice. Judged once on the finished board (Board._report_pin_orders), never in the placement search."""
from __future__ import annotations

import math

from .pinmap_input import _series
from .pinmap_rules import natural, read_rules
from .ratsnest import segments_cross


def reversed_groups(occ, skip=frozenset(), studied=frozenset()) -> list:
    """The facts of each `pins.reversed` finding on the board as it stands. `skip`: parts left to the pin map study's
    advice; `studied`: parts the study looked at this resolve and gave no map for."""
    s = occ.settings
    geom = occ.geometry
    pads_of: dict = {}
    for fp in geom.footprints:
        if fp.ref in occ.pending or fp.ref not in occ.items:
            continue
        for p in fp.pads:
            pads_of.setdefault(fp.ref, {})[p.number] = p.net
    by_net: dict = {}
    for ref in sorted(pads_of):
        for number, net in sorted(pads_of[ref].items(), key=lambda kv: natural(kv[0])):
            if net and net not in occ.quiet_nets:
                by_net.setdefault(net, []).append((ref, number))
    prefixes = tuple(s.pins_follow_prefixes)
    series = {r for r in pads_of if s.pins_follow_series and _series(r, pads_of, prefixes)}
    at = {}

    def where(ref, number):
        k = (ref, number)
        if k not in at:
            loc = occ.pad_location(ref, number)
            at[k] = (loc.x, loc.y)
        return at[k]
    pairs: dict = {}

    def add(e1, e2, via):
        (r1, n1, net1), (r2, n2, net2) = e1, e2
        if r1 == r2 or r1 in series or r2 in series:
            return
        if r1 > r2:
            e1, e2, via = e2, e1, (via[0], via[2], via[1]) if via else None
        pairs.setdefault((e1[0], e2[0]), []).append((e1, e2, via))
    for net, ends in sorted(by_net.items()):
        if len(ends) == 2 and not any(r in series for r, _ in ends):
            add(ends[0] + (net,), ends[1] + (net,), None)
    for r in sorted(series):
        (na, neta), (nb, netb) = sorted(pads_of[r].items(), key=lambda kv: natural(kv[0]))
        if not neta or not netb or neta == netb or neta in occ.quiet_nets or netb in occ.quiet_nets:
            continue
        ea, eb = by_net.get(neta, []), by_net.get(netb, [])
        if len(ea) != 2 or len(eb) != 2:
            continue
        xa = next(e for e in ea if e[0] != r)
        xb = next(e for e in eb if e[0] != r)
        add(xa + (neta,), xb + (netb,), (r, na, nb))
    out = []
    for (p, q), lines in sorted(pairs.items()):
        if len(lines) < s.pins_reversed_min or p in skip or q in skip:
            continue
        out += _pair(occ, p, q, lines, where, s.pins_reversed_min, studied)
    return out


def _segments(lines, where, pos) -> list:
    """Each line's straight airwires: [(a, b)] pin to pin, or pin to series part and series part to pin. `pos` gives
    each line's two pins' places ({line index: (p place, q place)})."""
    out = []
    for k, (e1, e2, via) in enumerate(lines):
        a, b = pos[k]
        if via is None:
            out.append([(a, b)])
        else:
            out.append([(a, where(via[0], via[1])), (where(via[0], via[2]), b)])
    return out


def _crossings(segs) -> int:
    n = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            n += sum(1 for s1 in segs[i] for s2 in segs[j] if segments_cross(s1[0], s1[1], s2[0], s2[1]))
    return n


def _rules(occ, ref, pins) -> dict:
    """Whether a `Pm.PinPool` on the part holds every pin of `pins` (and none is fixed), and the `Pm.PinGroup` that
    holds them all ("" for none)."""
    fp = occ.geometry.footprint(ref)
    rules, _ = read_rules(ref, fp.fields, [(p.number, p.net) for p in fp.pads], occ.geometry.pin_names.get(ref, {}))
    if rules is None:
        return {"ref": ref, "pool": False, "group": ""}
    pool = all(p in rules.pool and p not in rules.fixed for p in pins)
    group = next((name for name, held, _ in rules.groups if set(pins) <= set(held)), "") if pool else ""
    return {"ref": ref, "pool": pool, "group": group}


def _runs(order, rank, least) -> list:
    """The runs of `least` or more lines next to each other in `order` whose `rank` falls from each to the next: lines
    that land in the reverse of their order, whatever lands between them."""
    runs, i = [], 0
    while i < len(order):
        j = i + 1
        while j < len(order) and rank[order[j]] < rank[order[j - 1]]:
            j += 1
        if j - i >= least:
            runs.append(order[i:j])
        i = j
    return runs


def _pair(occ, p, q, lines, where, least, studied) -> list:
    """The `pins.reversed` facts of one pair of parts: each run reversed between a part's pins and where their airwires
    from it land (the other part's pins, or a series part's pads on the way), whose mirror on that part removes
    crossings, the best of the two parts for each set of lines."""
    pos = {k: (where(e1[0], e1[1]), where(e2[0], e2[1])) for k, (e1, e2, _) in enumerate(lines)}

    def hop(k, side):
        """Where line k's airwire from its pin on `side` lands: the series part's pad on that side, or the other pin."""
        via = lines[k][2]
        return where(via[0], via[1 + side]) if via else pos[k][1 - side]
    cp = [sum(pos[k][0][i] for k in pos) / len(pos) for i in (0, 1)]
    cq = [sum(pos[k][1][i] for k in pos) / len(pos) for i in (0, 1)]
    d = math.hypot(cq[0] - cp[0], cq[1] - cp[1])
    if d < 1e-9:
        return []
    vx, vy = -(cq[1] - cp[1]) / d, (cq[0] - cp[0]) / d

    def t(pt):
        return pt[0] * vx + pt[1] * vy
    now = _crossings(_segments(lines, where, pos))
    if not now:
        return []
    found: dict = {}
    for side, ref in ((0, p), (1, q)):
        order = sorted(pos, key=lambda k: (t(pos[k][side]), k))
        landing = sorted(pos, key=lambda k: (t(hop(k, side)), k))
        rank = {k: i for i, k in enumerate(landing)}
        for run in _runs(order, rank, least):
            moved = dict(pos)
            for k, to in zip(run, reversed(run)):
                ends = list(pos[k])
                ends[side] = pos[to][side]
                moved[k] = tuple(ends)
            mirrored = _crossings(_segments(lines, where, moved))
            if mirrored < now:
                rules = _rules(occ, ref, [lines[k][side][1] for k in run])
                found.setdefault(frozenset(run), []).append((not rules["pool"], mirrored, ref, side, rules, run))
    out = []
    chosen = []
    for tries in found.values():
        tries.sort(key=lambda x: x[:3])
        best = tries[0]
        also = next((x[2] for x in tries[1:] if x[:2] == best[:2]), "")     # the other part, as good a mirror
        chosen.append((best[3], best[2], best[1], best[4], best[5], also))
    for side, ref, mirrored, rules, run, also in sorted(chosen, key=lambda x: (x[1], sorted(x[4]))):
        other = 1 - side
        sign = -1.0 if natural(lines[run[0]][side][1]) > natural(lines[run[-1]][side][1]) else 1.0
        mine = sorted(run, key=lambda k: sign * t(pos[k][side]))     # so the part's own pins come in their order
        far = sorted(run, key=lambda k: sign * t(hop(k, side)))
        refs = [ref, (p, q)[other]]
        far_ends = [[lines[k][2][0], lines[k][2][1 + side]] if lines[k][2] else list(lines[k][other][:2]) for k in far]
        pins = [lines[k][side][1] for k in mine]
        centre = [sum(pos[k][s_][i] for k in run for s_ in (0, 1)) / (2 * len(run)) for i in (0, 1)]
        out.append({"refs": refs, "mirror": ref, "mirror_also": also,
                    "nets": [[lines[k][side][2] for k in mine], [lines[k][side][2] for k in far]],
                    "pins": pins, "far": far_ends, "crossings": now, "crossings_mirrored": mirrored,
                    "rules": [rules, _rules(occ, refs[1], [lines[k][other][1] for k in run])],
                    "studied": ref in studied, "at": [round(centre[0], 3), round(centre[1], 3)]})
    return out
