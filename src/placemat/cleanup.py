"""A cleanup pass after the searched tier: global moves toward each part's
optimal region and swaps of identical parts (FastPlace-DP, Pan, Viswanathan
and Chu, ICCAD 2005), at the size of a board.

Each move is legal by `occ.legal` - a scored `scan()` finds it - and is taken
only when it lowers the part's cost: the HPWL of its nets that pull plus, for
each declared link on one of its pads, the link's weight times its length. No
move leaves a limited link over its limit and longer than it was. A move
may turn a part to any rotation it is given in `turns`; the face does not
change. Deterministic: sorted order, no randomness."""
from __future__ import annotations

from dataclasses import dataclass, field
import statistics

from .placement import Placement
from .placer import scan
from .values import Location

_EPS = 1e-6
_OVER = 1e9                 # what breaking a link's limit costs in the search: always worse than any wire


@dataclass
class CleanupResult:
    moves: dict = field(default_factory=dict)       # key -> (from, to, cost before, cost after), the last move of each
    swaps: list = field(default_factory=list)       # (key, key) in the order they were made
    passes: int = 0
    cost_before: float = 0.0
    cost_after: float = 0.0


def cleanup(occ, movable: dict, pins: dict, links, clearance, passes: int, radius: float, step: float,
            turns: dict | None = None) -> CleanupResult:
    """`movable` maps a step key to its footprint, committed where it stands;
    `pins` maps each net that pulls to its placed (refdes, pad number) pins;
    `turns` maps a key to the rotations its move may take, else it keeps its own."""
    turns = turns or {}
    keys = sorted(movable)
    ref_of = {k: movable[k].ref for k in keys}
    key_of_ref = {r: k for k, r in ref_of.items()}
    nets_of = {k: sorted({p.net for p in movable[k].pads if p.net in pins}) for k in keys}
    links_of = {k: [l for l in links if ref_of[k] in (l.a[0], l.b[0])] for k in keys}
    placement = {k: occ.items[ref_of[k]].reference for k in keys}
    offsets = {}

    def pads_at(k, pl):
        key = (k, pl.rotation, pl.face)
        if key not in offsets:
            offsets[key] = occ.candidate_pad_locations(movable[k], Placement(Location(0.0, 0.0), pl.rotation, pl.face))
        x, y = pl.location.x, pl.location.y
        return {rn: Location(q.x + x, q.y + y) for rn, q in offsets[key].items()}

    def where(ref, number, override):
        k = key_of_ref.get(ref)
        if k is not None and k in override:
            return pads_at(k, override[k])[(ref, number)]
        return occ.pad_location(ref, number)

    def hp(nets, override):
        total = 0.0
        for n in nets:
            pts = [where(r, m, override) for r, m in pins[n]]
            total += max(q.x for q in pts) - min(q.x for q in pts) + max(q.y for q in pts) - min(q.y for q in pts)
        return total

    def link_len(link, override):
        return where(*link.a, override).distance(where(*link.b, override))

    def cost(ks, nets, override):
        total = hp(nets, override)
        seen = set()
        for k in ks:
            for l in links_of[k]:
                if id(l) not in seen and l.weight > 0:
                    seen.add(id(l))
                    total += int(l.weight) * link_len(l, override)
        return total

    def links_ok(ks, override):
        for k in ks:
            for l in links_of[k]:
                if l.limit_mm is None:
                    continue
                after = link_len(l, override)
                if after > l.limit_mm + 1e-9 and after > link_len(l, {}) + 1e-9:
                    return False
        return True

    def total_cost():
        nets = sorted({n for k in keys for n in nets_of[k]})
        return cost(keys, nets, {})

    result = CleanupResult(cost_before=total_cost())
    for n in range(max(passes, 0)):
        changed = False
        result.passes = n + 1
        for k in keys:
            nets = nets_of[k]
            if not nets and not links_of[k]:
                continue
            cur = placement[k]
            now = cost([k], nets, {})
            hints = []
            xs, ys = [], []
            for net in nets:
                others = [occ.pad_location(r, m) for r, m in pins[net] if r != ref_of[k]]
                if others:
                    xs += [min(q.x for q in others), max(q.x for q in others)]
                    ys += [min(q.y for q in others), max(q.y for q in others)]
            if xs:
                body = occ.body_box(movable[k], cur).center
                tx, ty = statistics.median(xs), statistics.median(ys)
                hints.append(Placement(Location(round(cur.location.x + tx - body.x, 4),
                                                round(cur.location.y + ty - body.y, 4)), cur.rotation, cur.face))
            hints.append(cur)

            def score(pl, k=k, nets=nets):
                over = 0.0 if links_ok([k], {k: pl}) else _OVER
                return cost([k], nets, {k: pl}) + over

            best = None
            for h in hints:
                r = scan(occ, movable[k], h, radius, step, turns.get(k, (cur.rotation,)), clearance, score=score)
                if r.chosen is not None and (best is None or r.score < best[0] - 1e-9):
                    best = (r.score, r.chosen)
            if best is not None and best[0] < now - _EPS and links_ok([k], {k: best[1]}):
                first = result.moves.get(k, (cur, None, now, None))
                occ.commit(movable[k], best[1])
                placement[k] = best[1]
                result.moves[k] = (first[0], best[1], first[2], best[0])
                changed = True
        groups = {}
        for k in keys:
            fp = movable[k]
            b = fp.courtyard_box
            groups.setdefault((round(b.width, 3), round(b.height, 3), len(fp.pads), placement[k].face), []).append(k)
        for sig in sorted(groups, key=lambda g: (g[0], g[1], g[2], g[3].value)):
            group = groups[sig]
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    pa, pb = placement[a], placement[b]
                    nets = sorted(set(nets_of[a]) | set(nets_of[b]))
                    if not nets and not links_of[a] and not links_of[b]:
                        continue
                    swap = {a: pb, b: pa}
                    now = cost([a, b], nets, {})
                    if cost([a, b], nets, swap) >= now - _EPS or not links_ok([a, b], swap):
                        continue
                    occ.pending |= {ref_of[b]}
                    ok = occ.legal(movable[a], pb, clearance) is None
                    occ.pending -= {ref_of[b]}
                    if not ok:
                        continue
                    occ.commit(movable[a], pb)
                    if occ.legal(movable[b], pa, clearance) is not None:
                        occ.commit(movable[a], pa)
                        continue
                    occ.commit(movable[b], pa)
                    placement[a], placement[b] = pb, pa
                    result.swaps.append((a, b))
                    changed = True
        if not changed:
            break
    result.cost_after = total_cost()
    return result
