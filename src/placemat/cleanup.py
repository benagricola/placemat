"""A cleanup pass after the searched tier: global moves toward each part's
optimal region (FastPlace-DP, Pan, Viswanathan and Chu, ICCAD 2005), and
swaps of any two neighbouring parts, at the size of a board.

A part's cost is the HPWL of its nets that pull, plus each declared link on
one of its pads times its weight and length, plus the ratsnest crossings its
airwires make and the escapes it crosses, closes or walls off, weighed as
the search weighs them (`score.crossing`, `score.escape_*`). A part is judged
lifted off the board, so where it stands and where it might go are weighed
alike.

Each move is legal by `occ.legal` - a scored `scan()` finds it - and is taken
only when it lowers the part's cost. A swap lifts both parts, searches the
larger (by body area) round the smaller's old spot, then the smaller round
the larger's, and is kept only when the pair's cost falls. No move or swap
leaves a limited link over its limit and longer than it was, nor a block's
satellite further from its pin than its limit. A move may turn a part to any
rotation it is given in `turns`; the face does not change. Deterministic:
sorted order, no randomness."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import statistics

from .placement import Placement
from .placer import scan
from .values import Location

_EPS = 1e-6
_OVER = 1e9                 # what breaking a limit costs in the search: always worse than any wire


@dataclass
class CleanupResult:
    moves: dict = field(default_factory=dict)       # key -> (from, to, cost before, cost after), the last move of each
    swaps: list = field(default_factory=list)       # (key, key) in the order they were made
    passes: int = 0
    cost_before: float = 0.0
    cost_after: float = 0.0


def _pad_gap(occ, a, b) -> float:
    """Edge to edge between two placed pads."""
    def box(ref, number):
        from .values import Box
        return Box.union([s.box for s in occ.items[ref].shapes if s.kind in ("pad", "through") and s.label == number])
    pa, pb = box(*a), box(*b)
    dx = max(pa.left - pb.right, pb.left - pa.right, 0.0)
    dy = max(pa.top - pb.bottom, pb.top - pa.bottom, 0.0)
    return math.hypot(dx, dy)


def cleanup(occ, movable: dict, pins: dict, links, clearance, passes: int, radius: float, step: float,
            turns: dict | None = None, limits: dict | None = None, settings=None) -> CleanupResult:
    """`movable` maps a step key to its footprint, committed where it stands;
    `pins` maps each net that pulls to its placed (refdes, pad number) pins;
    `turns` maps a key to the rotations its move may take, else it keeps its
    own; `limits` maps a satellite's key to (its pin, its own pad, mm): how
    far its pad may stand from its pin, edge to edge."""
    turns = turns or {}
    limits = limits or {}
    s = settings if settings is not None else occ.settings
    keys = sorted(movable)
    ref_of = {k: movable[k].ref for k in keys}
    key_of_ref = {r: k for k, r in ref_of.items()}
    nets_of = {k: sorted({p.net for p in movable[k].pads if p.net in pins}) for k in keys}
    links_of = {k: [l for l in links if ref_of[k] in (l.a[0], l.b[0])] for k in keys}
    placement = {k: occ.items[ref_of[k]].reference for k in keys}
    offsets = {}
    crossing = s.score_crossing
    escaping = s.score_escape_crossed > 0 or s.score_escape_closed > 0 or s.score_escape_walled > 0
    rn = occ.ratsnest() if crossing > 0 or escaping else None
    esc = occ.escapes() if escaping else None

    def pads_at(k, pl):
        # keyed by the part's geometry as it stands, as the occupancy's own
        # caches are: once it has moved, its offsets are worked out again
        geom = occ._geometry(movable[k])
        key = (k, pl.rotation, pl.face)
        hit = offsets.get(key)
        if hit is None or hit[0] is not geom:
            hit = (geom, occ.candidate_pad_locations(movable[k], Placement(Location(0.0, 0.0), pl.rotation, pl.face)))
            offsets[key] = hit
        x, y = pl.location.x, pl.location.y
        return {rn_: Location(q.x + x, q.y + y) for rn_, q in hit[1].items()}

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

    def terms(k, pl):
        """The crossings and escapes of part `k` at `pl`, with `k` lifted."""
        if rn is None:
            return 0.0
        own = frozenset([ref_of[k]])
        added, crossed = rn.leaf_costs(occ.candidate_anchors(movable[k], pl), own, s.place_escape_depth)
        total = crossing * added
        if esc is not None:
            crossed, closed, walled = esc.closed(movable[k], pl, crossed)
            total += s.score_escape_crossed * crossed + s.score_escape_closed * closed + s.score_escape_walled * walled
        return total

    def limits_ok(ks, override):
        for k in ks:
            for l in links_of[k]:
                if l.limit_mm is None:
                    continue
                after = link_len(l, override)
                if after > l.limit_mm + 1e-9 and after > link_len(l, {}) + 1e-9:
                    return False
        return True

    def satellite_ok(k, pl):
        """A satellite's pad no further than its limit from its pin."""
        if k not in limits:
            return True
        pin, own_pad, mm = limits[k]
        if pl is None:
            return _pad_gap(occ, pin, own_pad) <= mm + 1e-9
        from .values import Box
        shapes = occ.shifted_shapes(movable[k], pl)
        mine = Box.union([sh.box for sh in shapes if sh.kind in ("pad", "through") and sh.label == own_pad[1]])
        theirs = Box.union([sh.box for sh in occ.items[pin[0]].shapes
                            if sh.kind in ("pad", "through") and sh.label == pin[1]])
        dx = max(mine.left - theirs.right, theirs.left - mine.right, 0.0)
        dy = max(mine.top - theirs.bottom, theirs.top - mine.bottom, 0.0)
        return math.hypot(dx, dy) <= mm + 1e-9

    class PartScore:
        """Part `k`'s cost at a candidate, as the scans of a move or a swap
        weigh it: over a limit, `_OVER`; wire reaching the best cost seen
        (`best[0]`), its wire plus `_OVER`; else the wire, links, crossings
        and escapes. Called, it is the Python reference; `native(rots, face)`
        gives the native sweep the same cost (NativeCleanupScoring)."""

        def __init__(self, k, nets, floor):
            self.k, self.nets, self.best = k, nets, [floor]
            self._native = {}

        def __call__(self, pl):
            k, nets, floor = self.k, self.nets, self.best
            if not (limits_ok([k], {k: pl}) and satellite_ok(k, pl)):
                return _OVER
            wire = cost([k], nets, {k: pl})
            if wire >= floor[0]:
                return wire + _OVER     # its crossings and escapes only add: no better than staying
            total = wire + terms(k, pl)
            floor[0] = min(floor[0], total)
            return total

        def native(self, rots, face):
            if (rn is not None and rn.mirror is None) or (esc is not None and esc.mirror is None):
                return None
            key = (tuple(rots), face)
            hit = self._native.get(key)
            if hit is None:
                hit = self._build(rots, face)
                self._native[key] = hit
            hit.floor = self.best[0]
            return hit

        def _build(self, rots, face):
            from .values import Box
            k = self.k
            fp, ref = movable[k], ref_of[k]
            origin = [Placement(Location(0.0, 0.0), r, face) for r in rots]
            turned = [pads_at(k, pl) for pl in origin]      # the same offsets the Python cost uses
            order = list(turned[0])
            index = {key: i for i, key in enumerate(order)}
            pads = [[(d[key].x, d[key].y) for key in order] for d in turned]
            nets = []
            for n in self.nets:
                fixed = [occ.pad_location(r, m) for r, m in pins[n] if key_of_ref.get(r) != k]
                mine = [index[(r, m)] for r, m in pins[n] if key_of_ref.get(r) == k]
                ext = (min(q.x for q in fixed), max(q.x for q in fixed), min(q.y for q in fixed),
                       max(q.y for q in fixed)) if fixed else None
                nets.append((ext, mine))

            def end(r, m):
                if key_of_ref.get(r) == k:
                    return (index[(r, m)], 0.0, 0.0)
                at = occ.pad_location(r, m)
                return (-1, at.x, at.y)
            links_ = [(float(int(l.weight)), end(*l.a), end(*l.b), l.limit_mm, link_len(l, {})) for l in links_of[k]]
            satellite = None
            if k in limits:
                pin, own_pad, mm = limits[k]
                mine = []
                for pl in origin:
                    b = Box.union([sh.box for sh in occ.shifted_shapes(fp, pl)
                                   if sh.kind in ("pad", "through") and sh.label == own_pad[1]])
                    mine.append((b.left, b.top, b.right, b.bottom))
                t = Box.union([sh.box for sh in occ.items[pin[0]].shapes
                               if sh.kind in ("pad", "through") and sh.label == pin[1]])
                satellite = (mine, (t.left, t.top, t.right, t.bottom), mm)
            mirror = rn.mirror if rn is not None else None
            return occ.native_module().NativeCleanupScoring(
                pads, nets, links_, satellite, mirror,
                [occ.candidate_anchors(fp, pl) for pl in origin] if rn is not None else [],
                [esc._native_turn(fp, pl) for pl in origin] if esc is not None else [],
                [ref], crossing, esc is not None,
                (s.score_escape_crossed, s.score_escape_closed, s.score_escape_walled), s.place_escape_depth,
                _OVER, self.best[0])

    def total_cost():
        nets = sorted({n for k in keys for n in nets_of[k]})
        return cost(keys, nets, {})

    def hints_for(k, cur, nets):
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
        return hints

    result = CleanupResult(cost_before=total_cost())
    for n in range(max(passes, 0)):
        changed = False
        result.passes = n + 1
        # ---------------------------------------------------------------- moves
        for k in keys:
            nets = nets_of[k]
            if not nets and not links_of[k]:
                continue
            cur = placement[k]
            occ.lift([ref_of[k]])
            now = cost([k], nets, {}) + terms(k, cur)

            score = PartScore(k, nets, now)
            best = None
            for h in hints_for(k, cur, nets):
                r = scan(occ, movable[k], h, radius, step, turns.get(k, (cur.rotation,)), clearance, score=score)
                if r.chosen is not None and (best is None or r.score < best[0] - 1e-9):
                    best = (r.score, r.chosen)
            if best is not None and best[0] < now - _EPS and limits_ok([k], {k: best[1]}) and satellite_ok(k, best[1]):
                first = result.moves.get(k, (cur, None, now, None))
                occ.commit(movable[k], best[1])
                placement[k] = best[1]
                result.moves[k] = (first[0], best[1], first[2], best[0])
                changed = True
            else:
                occ.unlift([ref_of[k]])
        # ---------------------------------------------------------------- swaps
        if _swaps(occ, movable, keys, placement, ref_of, nets_of, links_of, cost, terms, limits_ok, satellite_ok,
                  turns, s.cleanup_swap_radius, step, clearance, s.cleanup_swap_neighbours, result, rn, crossing,
                  PartScore):
            changed = True
        if not changed:
            break
    result.cost_after = total_cost()
    return result


def _swaps(occ, movable, keys, placement, ref_of, nets_of, links_of, cost, terms, limits_ok, satellite_ok,
           turns, radius, step, clearance, neighbours: int, result, rn=None, crossing: float = 0.0,
           part_score=None) -> bool:
    """Offer each part a swap with its nearest movable neighbours, and with
    every part identical to it: lift both, search the larger round the
    smaller's old spot, then the smaller round the larger's; keep it when
    the pair's cost falls."""
    if neighbours <= 0:
        return False
    centre = {k: occ.body_box(movable[k], placement[k]).center for k in keys}
    size = {k: occ.body_box(movable[k], placement[k]) for k in keys}
    pairs = []
    for a in keys:
        near = sorted((centre[a].distance(centre[b]), b) for b in keys if b != a
                      and placement[b].face == placement[a].face)
        reach = radius + max(size[a].width, size[a].height) * 2
        for d, b in near[:neighbours]:
            if d <= reach + max(size[b].width, size[b].height):
                pairs.append(tuple(sorted((a, b))))
    # identical parts swap at any distance, as the pass always has: two of one
    # part on opposite sides, each wired to the other's side
    groups: dict = {}
    for k in keys:
        fp = movable[k]
        cb = fp.courtyard_box
        groups.setdefault((round(cb.width, 3), round(cb.height, 3), len(fp.pads), placement[k].face), []).append(k)
    for group in groups.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pairs.append(tuple(sorted((a, b))))
    changed = False
    for a, b in sorted(set(pairs)):
        nets = sorted(set(nets_of[a]) | set(nets_of[b]))
        if not nets and not links_of[a] and not links_of[b]:
            continue
        pa, pb = placement[a], placement[b]
        if pa.face != pb.face:
            continue
        # A first look, neither part lifted: the two exchanged centre on centre,
        # in their own turns, on wire, links and crossings. Only a pair that
        # gains there is searched.
        ca = _centred(occ, movable[a], occ.body_box(movable[b], pb).center, pa.rotation, pa.face)
        cb = _centred(occ, movable[b], occ.body_box(movable[a], pa).center, pb.rotation, pb.face)
        own = frozenset([ref_of[a], ref_of[b]])

        def rough(over):
            total = cost([a, b], nets, over)
            if rn is not None and crossing > 0:
                for k, pl in ((a, over.get(a, pa)), (b, over.get(b, pb))):
                    total += crossing * rn.leaf_costs(occ.candidate_anchors(movable[k], pl), own)[0]
            return total
        if rough({a: ca, b: cb}) >= rough({}) - _EPS:
            continue
        occ.lift([ref_of[a], ref_of[b]])
        now = cost([a, b], nets, {}) + terms(a, pa) + terms(b, pb)
        big, small = (a, b) if size[a].area >= size[b].area else (b, a)
        spot = {a: pa, b: pb}

        def search(k, around):
            target = occ.body_box(movable[around], spot[around]).center

            score = part_score(k, nets_of[k], math.inf)
            best = None
            for rot in turns.get(k, (spot[k].rotation,)):
                c = occ.shifted_body_box(movable[k], Placement(Location(0.0, 0.0), rot, spot[k].face)).center
                hint = Placement(Location(round(target.x - c.x, 4), round(target.y - c.y, 4)), rot, spot[k].face)
                r = scan(occ, movable[k], hint, radius, step, (rot,), clearance, score=score)
                if r.chosen is not None and (best is None or r.score < best[0] - 1e-9):
                    best = (r.score, r.chosen)
            return best

        first = search(big, small)
        if first is None or first[0] >= _OVER:
            occ.unlift([ref_of[a], ref_of[b]])
            continue
        occ.commit(movable[big], first[1])
        second = search(small, big)
        if second is None or second[0] >= _OVER:
            occ.lift([ref_of[big]])
            occ.commit(movable[big], spot[big])
            occ.unlift([ref_of[small]])
            continue
        occ.commit(movable[small], second[1])
        moved = {big: first[1], small: second[1]}
        occ.lift([ref_of[a], ref_of[b]])
        after = cost([a, b], nets, {}) + terms(a, moved[a]) + terms(b, moved[b])
        if after < now - _EPS and limits_ok([a, b], {}) and satellite_ok(a, None) and satellite_ok(b, None):
            occ.commit(movable[a], moved[a])
            occ.commit(movable[b], moved[b])
            placement[a], placement[b] = moved[a], moved[b]
            result.swaps.append((a, b))
            changed = True
        else:
            occ.commit(movable[a], pa)
            occ.commit(movable[b], pb)
    return changed


def _centred(occ, fp, centre, rotation, face) -> Placement:
    """The placement that puts the part's body centre on `centre`."""
    c = occ.shifted_body_box(fp, Placement(Location(0.0, 0.0), rotation, face)).center
    return Placement(Location(round(centre.x - c.x, 4), round(centre.y - c.y, 4)), rotation, face)
