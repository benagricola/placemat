"""A cleanup pass after the searched tier: global moves toward each part's
optimal region (FastPlace-DP, Pan, Viswanathan and Chu, ICCAD 2005), and
swaps of any two neighbouring parts, at the size of a board.

Moves and swaps use the required one_score factory and the common run
score's incremental change (score_search.MSTScorer). They follow score.rank:
fewer walled pads comes first, then a lower score at equal validity. Each
candidate is judged with the moved parts lifted, and is legal by occ.legal.

A swap lifts both parts, searches the larger around the smaller's old spot,
then the smaller around the larger's. No move or swap lengthens a limited
link beyond its limit or takes a satellite further from its pin than its
limit. Turns follow the declaration; faces stay. Visits are deterministic,
in sorted order, without randomness."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import statistics

from .placement import Placement
from .placer import UNWEIGHED, scan
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
            turns: dict | None = None, limits: dict | None = None, settings=None, one_score=None) -> CleanupResult:
    """`movable` maps a step key to its footprint, committed where it stands;
    `pins` maps each net that pulls to its placed (refdes, pad number) pins;
    `turns` maps a key to the rotations its move may take, else it keeps its
    own; `limits` maps a satellite's key to (its pin, its own pad, mm): how
    far its pad may stand from its pin, edge to edge. `one_score(footprint)`,
    when given, is the one-score search's scorer for that footprint, lifted
    (score_search.MSTScorer): the moves and swaps are judged by it."""
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
    rn = occ.ratsnest()
    if one_score is None:
        raise ValueError("cleanup requires the common run-score factory (one_score)")

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

    def limits_ok(ks, override, before=None):
        """Whether no limited link of `ks` ends over its limit and longer than it was. `before` places the items as they
        were where the board no longer holds that (a swap's two parts, committed at their new spots). `limits_ok.of(k)`:
        whether `k` has a limit to keep (a limited link, or a satellite's)."""
        for k in ks:
            for l in links_of[k]:
                if l.limit_mm is None:
                    continue
                after = link_len(l, override)
                if after > l.limit_mm + 1e-9 and after > link_len(l, before or {}) + 1e-9:
                    return False
        return True

    limits_ok.of = lambda k: k in limits or any(l.limit_mm is not None for l in links_of[k])

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
            chosen = _one_score_move(occ, movable[k], k, cur, one_score, hints_for(k, cur, nets), radius, step,
                                     turns.get(k, (cur.rotation,)), clearance, limits_ok, satellite_ok)
            if chosen is not None:
                first = result.moves.get(k, (cur, None, chosen[1], None))
                occ.commit(movable[k], chosen[0])
                placement[k] = chosen[0]
                result.moves[k] = (first[0], chosen[0], first[2], chosen[2])
                changed = True
            else:
                occ.unlift([ref_of[k]])
            continue
        # ---------------------------------------------------------------- swaps
        if _swaps(occ, movable, keys, placement, ref_of, nets_of, links_of, cost, limits_ok, satellite_ok,
                  turns, s.cleanup_swap_radius, step, clearance, s.cleanup_swap_neighbours, result, rn, crossing,
                  one_score):
            changed = True
        if not changed:
            break
    result.cost_after = total_cost()
    return result


def _swaps(occ, movable, keys, placement, ref_of, nets_of, links_of, cost, limits_ok, satellite_ok,
           turns, radius, step, clearance, neighbours: int, result, rn=None, crossing: float = 0.0,
           one_score=None) -> bool:
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
        big, small = (a, b) if size[a].area >= size[b].area else (b, a)
        spot = {a: pa, b: pb}

        def search(k, around):
            target = occ.body_box(movable[around], spot[around]).center

            score = _limited(one_score(movable[k]), k, limits_ok, satellite_ok)
            if hasattr(score, 'delta'):
                # one surface for every turn's scan (score_search.MSTScorer.native maps each scan's turn to it)
                score.native(tuple(sorted({r % 360 for r in turns.get(k, (spot[k].rotation,))})), spot[k].face)
            best = None
            for rot in turns.get(k, (spot[k].rotation,)):
                c = occ.shifted_body_box(movable[k], Placement(Location(0.0, 0.0), rot, spot[k].face)).center
                hint = Placement(Location(round(target.x - c.x, 4), round(target.y - c.y, 4)), rot, spot[k].face)
                r = scan(occ, movable[k], hint, radius, step, (rot,), clearance, score=score)
                if r.chosen is not None and (best is None or _below((r.walled, r.score), best[0], 1e-9)):
                    best = ((r.walled, r.score), r.chosen)
            return best

        first = search(big, small)
        if first is None or first[0][1] >= _OVER:
            occ.unlift([ref_of[a], ref_of[b]])
            continue
        occ.commit(movable[big], first[1])
        second = search(small, big)
        if second is None or second[0][1] >= _OVER:
            occ.lift([ref_of[big]])
            occ.commit(movable[big], spot[big])
            occ.unlift([ref_of[small]])
            continue
        occ.commit(movable[small], second[1])
        moved = {big: first[1], small: second[1]}
        taken = _one_score_swap(occ, movable, ref_of, a, b, spot, moved, one_score)
        occ.lift([ref_of[a], ref_of[b]])
        if taken and limits_ok([a, b], moved, {a: pa, b: pb}) and satellite_ok(a, None) and satellite_ok(b, None):
            occ.commit(movable[a], moved[a])
            occ.commit(movable[b], moved[b])
            placement[a], placement[b] = moved[a], moved[b]
            result.swaps.append((a, b))
            changed = True
        else:
            occ.commit(movable[a], pa)
            occ.commit(movable[b], pb)
    return changed


def _below(a: tuple, b: tuple, eps: float) -> bool:
    """Whether standing `a` (pads walled off, cost) is below `b`: fewer pads walled off, or as many at a cost more than
    `eps` lower."""
    return a[0] < b[0] or (a[0] == b[0] and a[1] < b[1] - eps)


def _centred(occ, fp, centre, rotation, face) -> Placement:
    """The placement that puts the part's body centre on `centre`."""
    c = occ.shifted_body_box(fp, Placement(Location(0.0, 0.0), rotation, face)).center
    return Placement(Location(round(centre.x - c.x, 4), round(centre.y - c.y, 4)), rotation, face)


def _limited(scorer, k, limits_ok, satellite_ok):
    """The one-score search's scorer for part `k`, or, when `k` has a limited link or is a satellite (`limits_ok.of`),
    one that ranks a candidate over its limit below every other (in Python: the native sweep does not know the
    limits)."""
    return _Limits(scorer, k, limits_ok, satellite_ok) if limits_ok.of(k) else scorer


class _Limits:
    """An MSTScorer whose candidates over a link's limit, or a satellite's, stand past every walled count."""
    OVER = UNWEIGHED - 2

    def __init__(self, scorer, k, limits_ok, satellite_ok):
        self.scorer, self.k, self.limits_ok, self.satellite_ok = scorer, k, limits_ok, satellite_ok
        self.spots, self.best = scorer.spots, scorer.best

    @property
    def walled_base(self):
        return self.scorer.walled_base

    def _ok(self, pl):
        return self.limits_ok([self.k], {self.k: pl}) and self.satellite_ok(self.k, pl)

    def native(self, rots, face):
        return None

    def scan(self, pl):
        walled, cost = self.scorer.scan(pl)
        return walled, cost + (0.0 if self._ok(pl) else _OVER)

    def partial(self, pl, python=False):
        return self.scan(pl)[1]

    def full(self, pl, python=False):
        walled, cost = self.scorer.full(pl, python=True)
        return (walled, cost) if self._ok(pl) else (self.OVER, cost + _OVER)

    def __call__(self, pl):
        return self.full(pl)


def _one_score_move(occ, fp, k, cur, one_score, hints, radius, step, rotations, clearance, limits_ok, satellite_ok):
    """(where part `k`, lifted, goes, the change at `cur`, the change there) when the move ranks the board above where
    it stands (`score.rank`: validity first): it walls fewer pads, whatever its change, or as many and lowers the run
    score, as the one-score search computes the change. A move that walls more is refused. Else None.

    Each hint's scan gives its best (walled, change), fewest walled first, and the best of them is the move: a costlier
    move that walls fewer pads ranks above a cheaper one that walls as many."""
    from .score_search import ScoreDomainError
    scorer = one_score(fp)
    try:
        # the scans' own turns, so the part's spot is scored on the surface they prepare, natively
        now = _in_full(scorer, [cur], tuple(sorted({r % 360 for r in rotations})))[0]
        best = None
        for h in hints:
            r = scan(occ, fp, h, radius, step, rotations, clearance, score=_limited(scorer, k, limits_ok, satellite_ok))
            if r.chosen is not None and (best is None or _below((r.walled, r.score), best[0], 1e-9)):
                best = ((r.walled, r.score), r.chosen)
    except ScoreDomainError:
        return None
    if best is None or best[0][0] > now[0] or (best[0][0] == now[0] and not best[0][1] < now[1] - _EPS):
        return None
    if not (limits_ok([k], {k: best[1]}) and satellite_ok(k, best[1])):
        return None
    return best[1], now[1], best[0][1]


def _one_score_swap(occ, movable, ref_of, a, b, spot, moved, one_score) -> bool:
    """Whether swapping parts `a` and `b` (both committed at `moved` now) from `spot` ranks the board above it
    (`score.rank`: validity first): it walls fewer pads than the board with both at `spot`, whatever its change, or as
    many and lowers the run score, as the one-score search computes the change. The change
    is taken in two lifts, each the search's own: `a` from its spot to its new one with `b` at its spot, then `b` from
    its spot to its new one with `a` at its new one. Leaves both committed at `moved`."""
    from .score_search import ScoreDomainError
    try:
        occ.lift([ref_of[b]])
        occ.commit(movable[b], spot[b])
        occ.lift([ref_of[a]])
        first = one_score(movable[a])
        before, a_moved = _in_full(first, [spot[a], moved[a]])
        occ.commit(movable[a], moved[a])
        occ.lift([ref_of[b]])
        second = one_score(movable[b])
        b_still, after = _in_full(second, [spot[b], moved[b]])
        occ.commit(movable[b], moved[b])
    except ScoreDomainError:
        for k in (a, b):
            if ref_of[k] in occ.pending:
                occ.commit(movable[k], moved[k])
        return False
    change = (a_moved[1] - before[1]) + (after[1] - b_still[1])
    return after[0] < before[0] or (after[0] == before[0] and change < -_EPS)


def _in_full(scorer, placements, rotations=None):
    """(walled, cost) of each of `placements` (one face) scored in full by the one-score scorer: natively, on the
    surface it prepares for `rotations` (else the placements' own turns) when that holds their turns, else in Python
    (the same value to the bit)."""
    face = placements[0].face
    rots = rotations if rotations is not None else tuple(sorted({p.rotation for p in placements}))
    if all(p.face == face and p.rotation in rots for p in placements):
        scorer.native(rots, face)
    return [scorer.full(p) for p in placements]
