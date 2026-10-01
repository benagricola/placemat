"""Searches for legal placements against an Occupancy: a grid scan around a
hint (scored or nearest), a block laid out at its anchor's pins and scanned
as one, the free rectangles (pockets) of a face, and the placements that put
an item flush on an edge, centred on a point or round a ring. Deterministic:
candidates enumerate in a fixed order and ties break on distance, rotation,
x, y."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import functools
import math

from . import geometry as _geometry_module
from . import giveway
from .geometry import Transform, _rect_of, point_in_polygon, polys_overlap, transform_box
from .occupancy import Occupancy, ShapeIndex, _reason_key
from .placement import Placement
from .values import Box, Edge, Face, Location, Mid, bearing, bearing_vector, box_support


@dataclass
class ScanResult:
    chosen: Placement | None
    hint: Placement
    tried: int
    rejected: Counter = field(default_factory=Counter)
    reasons: dict = field(default_factory=dict)
    blockers: Counter = field(default_factory=Counter)   # (kind, owner, face label) -> how often
    score: float = 0.0

    @property
    def moved_mm(self) -> float:
        if self.chosen is None:
            return math.inf
        return self.chosen.location.distance(self.hint.location)

    def __iter__(self):
        yield from self.rejected


@functools.lru_cache(maxsize=16)
def _grid_offsets(radius: float, step: float) -> tuple:
    """(d, dx, dy) within `radius` on a `step` grid, nearest first, cached by
    (radius, step): `_grid` is called with the same handful of (radius,
    step) pairs many times over a run (one scan's several passes, many
    scans of the same kind of item), so the O(n^2) walk-and-sort happens
    once per pair, not once per call (mirrors `giveway._offsets`)."""
    n = int(math.floor(radius / step + 1e-9))
    pts = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            d = math.hypot(i * step, j * step)
            if d <= radius + 1e-9:
                pts.append((d, i * step, j * step))
    pts.sort()
    return tuple(pts)


def _grid(center: Location, radius: float, step: float):
    return [(d, round(center.x + dx, 6), round(center.y + dy, 6)) for d, dx, dy in _grid_offsets(radius, step)]


COARSE_STEPS = 4
"""A scored scan over a wide radius first walks a grid this many steps
apart and refines to the step only around its best spots. The default for
`[place] coarse_steps`; a board's own is carried on its Occupancy."""
COARSE_FROM = 12
"""Radius-to-step ratio from which a scored scan goes coarse first: below
it the fine grid is a few hundred points and not worth two passes.
`[place] coarse_from`."""
REFINE_AROUND = 3
"""How many of the best coarse spots get a fine pass. `[place] refine_around`."""


# Whether a scan judges its passes natively when it can: switched off to
# compare against the pure-Python sweep (tests/test_native_sweep.py).
NATIVE_SWEEP = True


def scan(occ: Occupancy, item, hint: Placement, radius: float, step: float,
         rotations=None, clearance: float | None = None, commit: bool = False, score=None,
         pick=None, accept=None) -> ScanResult:
    """A legal location within `radius` of `hint`, on a `step` grid, trying
    each rotation at each location. Without `score` it is the nearest legal
    candidate to the hint; with `score(placement) -> float` it is the legal
    candidate with the lowest score, ties broken by distance from the hint,
    then rotation. Rotations are tried in numeric order regardless of how
    they were passed. A scored scan over a wide radius is coarse first,
    then fine around its best spots.

    `accept(placement)`, when given, is asked of a candidate the item's own
    test passed (the items riding the one scanned, layout.py): None counts
    it, a sentence refuses it, tallied under the sentence's text before its
    first colon. An unscored scan asks it of each candidate in turn; a
    scored one of the best candidates first, until one is counted, so the
    scorer must not prune by a candidate `accept` may refuse."""
    rots = tuple(sorted({(r % 360) for r in (rotations or (hint.rotation,))}))
    rejected: Counter = Counter()
    reasons: dict = {}
    blockers: Counter = Counter()
    tried = 0
    geom = occ._geometry(item)
    span = geom.body if occ.envelope == "courtyard" else occ._extent(geom)     # silk can stand past the body
    reach = radius + max(span.width, span.height)                  # any rotation of it, anywhere in the scan
    region = Box(hint.location.x - reach, hint.location.y - reach, hint.location.x + reach, hint.location.y + reach)
    others = occ.obstacles(geom, region)
    seen: set = set()
    native = occ.native_sweeper(item, hint.face, rots, others, clearance) if NATIVE_SWEEP else None
    scoring = score.native(rots, hint.face) if native is not None and not native.recheck and hasattr(score, "native") \
        else None
    # Carried vias that may give way (giveway.py): a pass judges the item as it is first; the
    # candidates that refuses are judged again less its carried vias, and against the board less
    # the placed items' carried vias, and the vias then share, move or drop at a cost
    gw = giveway.for_scan(occ, item, hint.face, rots, region, clearance, native is not None)
    asked: dict = {}
    inline = accept is not None and score is None       # unscored: asked as each candidate is met

    def refused(cand) -> bool:
        """Whether `accept` refuses a candidate the item's own test passed;
        tallied the first time it is asked."""
        if accept is None:
            return False
        key = (cand.location.x, cand.location.y, cand.rotation)
        if key not in asked:
            why = accept(cand)
            asked[key] = why is not None
            if why is not None:
                bucket = why.split(":")[0]
                rejected[bucket] += 1
                reasons.setdefault(bucket, why)
        return asked[key]

    def counted(ranked, n: int | None) -> list:
        """The first `n` (all, for None) of `ranked` that `accept` counts."""
        if accept is None:
            return ranked if n is None else ranked[:n]
        out = []
        for entry in ranked:
            if not refused(entry[3]):
                out.append(entry)
                if n is not None and len(out) == n:
                    break
        return out

    def blocker_of(key) -> list:
        """A native refusal's blocker key as the blockers a tally counts: none for a candidate
        refused in full without one (NativeSweeper's `recheck`)."""
        return [] if key is None else [key]

    def blocker_key(b) -> tuple:
        return (b.kind, b.owner, "/".join(sorted(f.value for f in b.faces)))

    def tally(key, get_reason, blame_keys, count: int = 1) -> None:
        rejected[key] += count
        if key not in reasons:
            reasons[key] = get_reason()
        for b in blame_keys:
            blockers[b] += count

    least = giveway.least_cost(occ.settings, getattr(occ, "fab_via_tiers", None))
    best = score.best if score and hasattr(score, "best") else None
    bounded = best is not None and pick is None and accept is None     # a spot that cannot be the best is not asked

    def gave_way(cand, legal: list):
        """Phase B for one candidate the item as it is was refused at: None
        when it is legal less its carried vias and they give way (added to
        `legal` at its score plus what they cost), or when, scored, it could
        not beat the best spot found even at the least a via's giving way
        costs; else (bucket, reason, blocker keys). The scorer's best stays
        what a spot truly costs, so none is pruned against a cost it did not
        reach."""
        blame = []
        hit = occ.legal_bucket(gw.item, cand, clearance, gw.others, blame)
        if hit is not None:
            return hit[0], hit[1], [blocker_key(b) for b in blame]
        sc, before = 0.0, None
        if score:
            before = best[0] if best is not None else None
            sc = score(cand)
            if best is not None:
                best[0] = before
            if bounded and sc + least > before:
                return None
        res = gw.resolve(cand)
        if res.why is not None:
            return _reason_key(res.why), (lambda why=res.why: why), [blocker_key(res.blocker)]
        if not (inline and refused(cand)):
            if best is not None:
                best[0] = min(before, sc + res.cost)
            d = math.hypot(cand.location.x - hint.location.x, cand.location.y - hint.location.y)
            legal.append((sc + res.cost, d, cand.rotation, cand))
        return None

    def sweep(points, stop_at_first: bool) -> list:
        """Evaluate every (x, y) in `points` at every rotation; the legal
        ones as (score, distance from the hint, rotation, placement). With
        vias that may give way, the candidates refused are judged again, as
        `gave_way` does, when the pass found none it keeps (a nearest-first
        pass) or always (a scored one): a refused candidate then counts
        under why it was refused the second time."""
        nonlocal tried
        if native is not None:
            return native_sweep(points, stop_at_first)
        legal = []
        held = []
        for x, y in points:
            for rot in rots:
                if (x, y, rot) in seen:
                    continue
                seen.add((x, y, rot))
                cand = Placement(Location(x, y), rot, hint.face)
                tried += 1
                blame = []
                # legal_bucket: a sweep never keeps more than one example
                # sentence per bucket (the `key not in reasons` check below),
                # so it asks for the sentence only the first time a bucket is
                # seen - see Occupancy.legal_bucket's own doc for why this
                # matters on the native path.
                hit = occ.legal_bucket(item, cand, clearance, others, blame)
                if hit is None:
                    if inline and refused(cand):
                        continue
                    d = math.hypot(x - hint.location.x, y - hint.location.y)
                    legal.append((score(cand) if score else 0.0, d, rot, cand))
                    if stop_at_first:
                        for c, h, bl in held:
                            tally(h[0], h[1], [blocker_key(b) for b in bl])
                        return legal
                    continue
                if gw is None:
                    tally(hit[0], hit[1], [blocker_key(b) for b in blame])
                else:
                    held.append((cand, hit, blame))
        for cand, _, _ in held:
            refusal = gave_way(cand, legal)
            if refusal is not None:
                tally(*refusal)
            elif legal and stop_at_first:
                break
        return legal

    def native_sweep(points, stop_at_first: bool) -> list:
        """The same pass, judged natively (Occupancy.native_sweeper): the same
        legal candidates, tallies, first sentences and blockers."""
        nonlocal tried
        # `native.expand` keeps its own (x, y, turn) seen-set (NativeSweepSeen)
        # for this scan's `native` instance, so the whole points-x-rots loop
        # and its dedup run in Rust once per pass - the outer Python `seen`
        # set is left alone, still used by the pure-Python `sweep` branch
        # above when `native is None`.
        triples = native.expand(list(points), len(rots))
        if scoring is not None:
            scoring.floor = score.best[0]
        first_only = stop_at_first and not inline           # else the first `accept` counts
        found, scores, refusals = native.run(triples, first_only, scoring)
        if scoring is not None:
            score.best[0] = scoring.floor
        tried += found[0] + 1 if first_only and found else len(triples)
        legal = []
        for i, sc in zip(found, scores):
            x, y, k = triples[i]
            cand = Placement(Location(x, y), rots[k], hint.face)
            if inline and refused(cand):
                continue
            d = math.hypot(x - hint.location.x, y - hint.location.y)
            legal.append(((sc if scoring is not None else score(cand)) if score else 0.0, d, rots[k], cand))
            if stop_at_first:
                break
        if gw is None or (stop_at_first and legal):
            for bucket, count, first, reason, blocker in refusals:
                tally(bucket, reason, blocker_of(blocker), count)
            return legal
        taken = set(found)
        sub = [triples[i] for i in range(len(triples)) if i not in taken]

        def at(t):
            return Placement(Location(t[0], t[1]), rots[t[2]], hint.face)
        if gw.native is None:
            for t in sub:
                refusal = gave_way(at(t), legal)
                if refusal is not None:
                    tally(*refusal)
                elif legal and stop_at_first:
                    break
            return legal
        if first_only:
            # nearest first: the next candidate legal less its vias, until its vias give way
            start = 0
            while start < len(sub):
                found_b, _, refusals_b = gw.native.run(sub[start:], True, None)
                for bucket, count, first, reason, blocker in refusals_b:
                    tally(bucket, reason, blocker_of(blocker), count)
                if not found_b:
                    break
                j = start + found_b[0]
                refusal = gave_way(at(sub[j]), legal)
                if refusal is None:
                    break
                tally(*refusal)
                start = j + 1
            return legal
        found_b, _, refusals_b = gw.native.run(sub, False, None)
        events = [(first, 0, (bucket, reason, blocker_of(blocker), count)) for bucket, count, first, reason, blocker in refusals_b]
        events += [(j, 1, None) for j in found_b]
        for j, kind, what in sorted(events, key=lambda e: e[0]):
            if kind == 0:
                tally(*what)
                continue
            refusal = gave_way(at(sub[j]), legal)
            if refusal is not None:
                tally(*refusal)
            elif legal and stop_at_first:
                break
        return legal

    def any_counted(legal) -> bool:
        """Whether a pass found a candidate that counts: one `accept` takes too."""
        return bool(legal) if inline or accept is None else bool(counted(sorted(legal, key=lambda k: k[:3]), 1))

    cfg = occ.settings
    if score is None or radius / step < cfg.place_coarse_from:
        legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, step)), stop_at_first=score is None)
    else:
        coarse = step * cfg.place_coarse_steps
        legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, coarse)), False)
        if not any_counted(legal):
            legal += sweep(((x, y) for _, x, y in _grid(hint.location, radius, coarse / 2)), False)
        if not any_counted(legal):
            # Nothing on either coarse lattice. The coarse pass is there to
            # save time, not to decide: the fine grid still gets its walk, so
            # a spot narrower than a coarse step is not reported as no room.
            legal += sweep(((x, y) for _, x, y in _grid(hint.location, radius, step)), False)
        if legal:
            legal.sort(key=lambda k: k[:3])
            for _, _, _, cand in counted(legal, cfg.place_refine_around):
                # The fine grid is centred on a coarse candidate, which can sit at
                # the edge of the radius: keep only what is still inside it, so
                # "within radius of the hint" is what a script gets.
                legal += sweep(((x, y) for _, x, y in _grid(cand.location, coarse, step)
                                if math.hypot(x - hint.location.x, y - hint.location.y) <= radius + 1e-9), False)
    if accept is not None and not inline:
        legal = counted(sorted(legal, key=lambda k: k[:3]), 1 if pick is None else None)
    if not legal:
        return ScanResult(None, hint, tried, rejected, reasons, blockers)
    if pick is None:
        best = min(legal, key=lambda k: k[:3])
    else:                                   # explore: the caller draws among them, best first
        best = pick(sorted(legal, key=lambda k: k[:3]))
    chosen = best[3]
    if commit:
        occ.commit(item, chosen)
    result = ScanResult(chosen, hint, tried, rejected, reasons, blockers)
    result.score = best[0]
    return result


def edge_placement(occ: Occupancy, item, edge: Edge, along: float, rotation: float,
                   standoff: float, face: Face = Face.FRONT) -> Placement:
    """The placement that puts the item's reach (courtyard and graphics)
    `standoff` inside `edge` with its body centre at `along` (x for
    north/south, y for east/west). A negative standoff overhangs the edge."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    box = occ.body_box(item, probe)
    reach = occ.reach_box(item, probe)
    board = occ.board_box
    if edge is Edge.NORTH:
        dx, dy = along - box.center.x, board.top + standoff - reach.top
    elif edge is Edge.SOUTH:
        dx, dy = along - box.center.x, board.bottom - standoff - reach.bottom
    elif edge is Edge.WEST:
        dx, dy = board.left + standoff - reach.left, along - box.center.y
    else:
        dx, dy = board.right - standoff - reach.right, along - box.center.y
    return Placement(Location(round(dx, 6), round(dy, 6)), rotation, face)


_SLACK = 1e-5       # a placement is rounded to the nanometre, so a solve stops ten of
                    # them inside its own answer: rounding can never tip it past the keep-in


def _far_from(box: Box, centre: Location) -> float:
    """How far the corner of `box` furthest from `centre` is: what the rim
    holds back."""
    return max(math.hypot(x - centre.x, y - centre.y)
               for x in (box.left, box.right) for y in (box.top, box.bottom))


def _near_to(box: Box, centre: Location) -> float:
    """How close `box` comes to `centre` anywhere - an edge, not just a
    corner, when the box straddles the centre's own row: what a bore holds
    back."""
    dx = max(box.left - centre.x, 0.0, centre.x - box.right)
    dy = max(box.top - centre.y, 0.0, centre.y - box.bottom)
    return math.hypot(dx, dy)


def disc_placement(occ: Occupancy, item, disc, angle: float, standoff: float, rotation: float,
                   face: Face = Face.FRONT, bore: bool = False) -> Placement:
    """The placement that puts the item `standoff` inside the rim on the
    bearing `angle` (with `bore`, that far outside the bore), its body centre
    on that bearing. A negative standoff overhangs the rim. How far out it
    goes is solved on what the item is - its reach and its body together -
    by the same measures the board's keep-in is judged by, so a placement
    this returns is one the keep-in accepts."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    box = occ.body_box(item, probe)
    what = Box.union([occ.reach_box(item, probe), box])
    ux, uy = bearing_vector(angle)
    off = Box(what.left - box.center.x, what.top - box.center.y,
              what.right - box.center.x, what.bottom - box.center.y)
    limit = (disc.bore + standoff) if bore else (disc.radius - standoff)

    def held(d: float) -> bool:
        at = off.moved(disc.centre.x + ux * d, disc.centre.y + uy * d)
        return _near_to(at, disc.centre) >= limit if bore else _far_from(at, disc.centre) <= limit
    # Both measures grow with d along the bearing, so the answer is bisected:
    # the largest d the rim still holds, or the smallest the bore is clear of.
    lo, hi = 0.0, disc.radius + max(what.width, what.height) + abs(standoff)
    if bore:
        d = hi if not held(hi) else _bisect(held, lo, hi, want_low=True) + _SLACK
    else:
        d = 0.0 if not held(lo) else _bisect(held, lo, hi, want_low=False) - _SLACK
    cx, cy = disc.centre.x + ux * d, disc.centre.y + uy * d
    return Placement(Location(round(cx - box.center.x, 6), round(cy - box.center.y, 6)), rotation, face)


def _bisect(held, lo: float, hi: float, want_low: bool, steps: int = 60) -> float:
    """The boundary of a monotone predicate: the smallest `lo` that holds
    (want_low) or the largest, to a nanometre."""
    for _ in range(steps):
        if hi - lo < 1e-7:
            break
        mid = (lo + hi) / 2.0
        if held(mid) == want_low:
            hi = mid
        else:
            lo = mid
    return hi if want_low else lo


def run_placement(occ: Occupancy, item, shape, run, along: float, standoff: float, rotation: float,
                  face: Face = Face.FRONT) -> Placement:
    """The placement that puts the item `standoff` inside the board at the
    point `along` a run, its body centre on the inward normal there. Where
    the board is straight the first guess is exact; where it curves the item
    is stepped in until the board's own keep-in holds it, then tightened
    back, so the same rule fits a side, a rounded top or an arc of a rim."""
    point, out_b = run.at(along)
    probe = Placement(Location(0.0, 0.0), rotation, face)
    box = occ.body_box(item, probe)
    what = Box.union([occ.reach_box(item, probe), box])
    off = Box(what.left - box.center.x, what.top - box.center.y,
              what.right - box.center.x, what.bottom - box.center.y)
    ux, uy = bearing_vector(out_b)

    def centre_at(d):
        return point.x - ux * d, point.y - uy * d

    def holds(d):
        cx, cy = centre_at(d)
        return shape.why_not(off.moved(cx, cy), standoff) is None
    if standoff < 0.0:
        # an overhang: the outward reach stands exactly that far past the edge, as on a
        # named edge. The keep-in test cannot place it - a negative margin holds any box
        # whose centre is on the board, so the search would stop with the centre on the edge
        cx, cy = centre_at(standoff + box_support(what, out_b) / 2.0)
        return Placement(Location(round(cx - box.center.x, 6), round(cy - box.center.y, 6)), rotation, face)
    d = max(0.0, standoff + box_support(what, out_b) / 2.0)
    limit = d + max(what.width, what.height) + 2.0
    while d < limit and not holds(d):
        d += 0.05
    if holds(d):
        d = _bisect(holds, 0.0, d, want_low=True) + _SLACK
    cx, cy = centre_at(d)
    return Placement(Location(round(cx - box.center.x, 6), round(cy - box.center.y, 6)), rotation, face)



def box_centered_placement(occ: Occupancy, item, center: Location, rotation: float = 0.0,
                           face: Face = Face.FRONT) -> Placement:
    """The placement whose BODY BOX is centred on `center` (a group's centre is
    its box centre, not its origin)."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    box = occ.body_box(item, probe)
    return Placement(Location(round(center.x - box.center.x, 6), round(center.y - box.center.y, 6)),
                     rotation, face)


def _offset_hits(o, u, poly, d: float) -> list:
    """The t at which the point o + t*u is exactly `d` from an edge of `poly`:
    where it crosses the lines `d` either side of each edge, within the edge's
    span, and the circles of radius `d` round each vertex."""
    out = []
    n = len(poly)
    for k in range(n):
        p, q = poly[k], poly[(k + 1) % n]
        ex, ey = q[0] - p[0], q[1] - p[1]
        length = math.hypot(ex, ey)
        if length == 0.0:
            continue
        ex, ey = ex / length, ey / length
        nx, ny = -ey, ex
        slope = u[0] * nx + u[1] * ny
        if slope != 0.0:
            base = (o[0] - p[0]) * nx + (o[1] - p[1]) * ny
            for side in (d, -d):
                t = (side - base) / slope
                foot = (o[0] + t * u[0] - p[0]) * ex + (o[1] + t * u[1] - p[1]) * ey
                if -1e-9 <= foot <= length + 1e-9:
                    out.append(t)
        wx, wy = o[0] - p[0], o[1] - p[1]
        half = u[0] * wx + u[1] * wy
        disc = half * half - (wx * wx + wy * wy - d * d)
        if disc >= -1e-12:
            root = math.sqrt(max(disc, 0.0))
            out += [-half - root, -half + root]
    return out


def sweep_standoff(moving, fixed, u, d: float) -> float | None:
    """How far, as a translation `t` along the unit vector `u`, `moving` (a
    polygon) must go for it to stand `d` from `fixed` for good - the greatest
    t at which the two are exactly `d` apart - or None when no translation
    along `u` brings them within `d`. Exact: the last contact is a vertex of
    one polygon at distance `d` from an edge or vertex of the other, so the
    candidates are where each vertex, carried along `u` (or back along it,
    for the fixed polygon's), crosses the edges' offset lines and the
    vertices' circles."""
    box_m, box_f = Box.of_points(moving), Box.of_points(fixed)
    across = (box_m.top - box_f.bottom, box_f.top - box_m.bottom) if u[0] else \
        (box_m.left - box_f.right, box_f.left - box_m.right)
    if max(across) >= d:
        return None
    best = None
    for origin, direction, poly in (
            [(v, u, fixed) for v in moving] + [(v, (-u[0], -u[1]), moving) for v in fixed]):
        for t in _offset_hits(origin, direction, poly, d):
            if best is not None and t <= best:
                continue
            shifted = tuple((x + t * u[0], y + t * u[1]) for x, y in moving)
            if abs(_geometry_module.poly_distance(shifted, fixed) - d) <= 1e-6:
                best = t
    return best


def pad_box_at(occ: Occupancy, item, key, rotation: float = 0.0, face: Face = Face.FRONT,
               land: int | None = None) -> Box:
    """The box of the item's pad `key` (a number or a net) with the item at
    the origin, turned to `rotation` and on `face`; with `land` (0-based, in
    the footprint's order for that number) that one land's. For a `Mid` of
    two keys, the point halfway between their pads, as a box of no size."""
    if isinstance(key, Mid):
        a, b = (pad_box_at(occ, item, k, rotation, face).center for k in (key.a, key.b))
        mx, my = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
        return Box(mx, my, mx, my)
    probe = Placement(Location(0.0, 0.0), rotation, face)
    number = item.pad(key).number
    geom = occ._geometry(item)
    t = occ._transform(geom, probe)
    shapes = [s for s in geom.shapes if s.kind in ("pad", "through") and s.label == number]
    if land is not None:
        counts = [len(q.outlines) for q in item.pads if q.number == number]
        shapes = shapes[sum(counts[:land]):sum(counts[:land + 1])]
    return Box.union([transform_box(s.box, t) for s in shapes])


def pad_anchored_placement(occ: Occupancy, item, key, point: Location, rotation: float = 0.0,
                           face: Face = Face.FRONT, land: int | None = None) -> Placement:
    """The placement that puts the item's pad `key` (a number or a net; one
    `land` of it; or the midpoint of two, as `Mid`) on `point` at `rotation`."""
    at = pad_box_at(occ, item, key, rotation, face, land).center
    return Placement(Location(round(point.x - at.x, 6), round(point.y - at.y, 6)), rotation, face)


def parallel_rotation(a: Location, b: Location, face: Face, degrees: float = 0.0) -> float:
    """The rotation that lies a part's own x axis along the line from `a` to
    `b`, plus `degrees`. A part turns counter-clockwise on screen; on the back
    face its own x axis is mirrored, so it points the other way for the same
    rotation."""
    dx, dy = b.x - a.x, b.y - a.y
    if math.hypot(dx, dy) < 1e-9:
        raise ValueError("Parallel's two points are one point, %.3f, %.3f: the line between them has no direction"
                         % (a.x, a.y))
    turn = math.degrees(math.atan2(-dy, dx)) if face is Face.FRONT else math.degrees(math.atan2(dy, -dx))
    return round((turn + degrees) % 360.0, 6)


def facing_rotation(occ: Occupancy, item, numbers: list, edge: Edge, face: Face = Face.FRONT) -> float:
    """Of the item's four right-angle turns on `face`, the one where the way out
    of pads `numbers` (`_pin_normal`'s outward normal of the row each sits in)
    points at `edge`. Raises ValueError, saying why, where a pad has no way out
    (a square pad at a corner, a lone pad) or the pads' ways out differ (two
    rows)."""
    probe = Placement(Location(0.0, 0.0), 0.0, face)
    geom = occ._geometry(item)
    t = occ._transform(geom, probe)
    boxes: dict = {}
    for sh in geom.shapes:
        if sh.kind in ("pad", "through"):
            boxes.setdefault(sh.label, []).append(transform_box(sh.box, t))
    pads = {(item.ref, n): Box.union(bs).center for n, bs in boxes.items()}
    outs = {}
    for n in numbers:
        box = Box.union(boxes[n])
        out = _pin_normal(pads, item.ref, box.center, 0.0, box)
        if out is None:
            raise ValueError("pad %s has no way out to turn by: it is a square pad at a corner of the pad field, "
                             "or the only pad of a row" % n)
        outs[n] = (round(out[0]), round(out[1]))
    if len(set(outs.values())) > 1:
        raise ValueError("pads %s are not one row: their ways out differ (%s)" % (
            ", ".join(numbers), ", ".join("%s %s" % (n, _way_name(o)) for n, o in outs.items())))
    (ox, oy), = set(outs.values())
    want = bearing_vector(bearing(edge))
    for r in (0.0, 90.0, 180.0, 270.0):
        ux, uy = Transform.rotate(r).apply((ox, oy))
        if abs(ux - want[0]) < 1e-6 and abs(uy - want[1]) < 1e-6:
            return r
    raise ValueError("no right-angle turn points their way out at %s" % edge.name)


def _way_name(out: tuple) -> str:
    return {(0, -1): "north", (0, 1): "south", (1, 0): "east", (-1, 0): "west"}.get(out, "%s,%s" % out)


def cell_pad_anchored_placement(occ: Occupancy, cell, owner: str, number: str, dx: float, dy: float,
                                point: Location, rotation: float = 0.0, face: Face = Face.FRONT,
                                lx: float = 0.0, ly: float = 0.0) -> Placement:
    """The placement that puts a cell so member `owner`'s pad `number`
    (offset `dx`, `dy` in board directions, `lx`, `ly` in the member's own -
    turned and, on its back, mirrored, as a part's own `PadRef.local` does)
    lands on `point`: `Pin` for a cell, whose own pad is one of its members'.
    `owner`/`number` name a single pad among a cell's shapes, which several
    members may number alike."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    geom = occ._geometry(cell)
    t = occ._transform(geom, probe)
    boxes = [transform_box(s.box, t) for s in geom.shapes
             if s.kind in ("pad", "through") and s.owner == owner and s.label == number]
    at = Box.union(boxes).center
    vx = vy = 0.0
    if lx or ly:
        from .lock import _turn
        # the member's own place, exactly as a cell's commit() derives it for
        # the placement it is trying: turned by the cell's rotation less its
        # own (a cell's own reference rotation is always 0, so this reduces
        # to the cell's own candidate rotation when the member is not itself
        # turned within it), mirrored with it when the cell's face flips.
        m = occ.items[owner].reference
        flip = probe.face != geom.reference.face
        turn = (probe.rotation + geom.reference.rotation - m.rotation) % 360.0 if flip \
            else m.rotation + (probe.rotation - geom.reference.rotation)
        member_face = (Face.BACK if m.face is Face.FRONT else Face.FRONT) if flip else m.face
        vx, vy = _turn(-lx if member_face is Face.BACK else lx, ly, turn)
    target = Location(point.x - dx - vx, point.y - dy - vy)
    return Placement(Location(round(target.x - at.x, 6), round(target.y - at.y, 6)), rotation, face)


def cell_origin_anchored_placement(occ: Occupancy, cell, owner: str, point: Location, rotation: float = 0.0,
                                   face: Face = Face.FRONT) -> Placement:
    """The placement that puts a cell so member `owner`'s footprint origin
    (its own anchor, a pad or not: a winding's arc centre) lands on
    `point`, at the cell's `rotation` and `face`."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    geom = occ._geometry(cell)
    at = occ._transform(geom, probe).apply_location(occ.geometry.footprint(owner).location)
    return Placement(Location(round(point.x - at.x, 6), round(point.y - at.y, 6)), rotation, face)


@dataclass(frozen=True)
class Pocket:
    """A free rectangle on one face, found by scanning the board."""
    box: Box
    face: Face


def _largest_rectangle(free, rows, cols, need_r: int = 1, need_c: int = 1):
    """Largest all-free axis-aligned rectangle in a boolean grid at least
    `need_r` rows by `need_c` columns, by the histogram method. Every maximal
    free rectangle is met on its bottom row, so the largest that meets the
    size is among them. Returns (area, r0, c0, r1, c1) exclusive, or None.

    Pure integer/boolean logic, no floating point - ported to native whole
    (not just a predicate inside it), since there is no epsilon-boundary
    question a native answer could get wrong: see native/src/pockets.rs and
    docs/superpowers/specs/2026-09-24-native-core-design.md."""
    if _geometry_module._native is not None:
        return _geometry_module._native.largest_rectangle(free, rows, cols, need_r, need_c)
    heights = [0] * cols
    best = None
    for r in range(rows):
        for c in range(cols):
            heights[c] = heights[c] + 1 if free[r][c] else 0
        stack = []
        for c in range(cols + 1):
            h = heights[c] if c < cols else 0
            start = c
            while stack and stack[-1][1] >= h:
                s, sh = stack.pop()
                area = sh * (c - s)
                if sh >= need_r and c - s >= need_c and (best is None or area > best[0]):
                    best = (area, r - sh + 1, s, r + 1, c)
                start = s
            stack.append((start, h))
    return best


def _board_mask(occ: Occupancy, inner: Box, rows: int, cols: int, step: float, covered: bool = False) -> list:
    """Which raster cells lie on the board. On a board that is not a
    rectangle a cell the outline crosses is out, or with `covered` in: then
    a cell is out only when no corner and not its centre may be used, so no
    room is lost to the raster. The answer depends only on the outline, the
    margin and the grid, so it is kept on the occupancy."""
    shape = occ.board_shape
    key = (id(shape), occ.edge_margin, inner, rows, cols, step, covered)
    cache = occ.__dict__.setdefault("_board_masks", {})
    if key not in cache:
        mask = [[True] * cols for _ in range(rows)]
        if shape is not None:
            def out(x, y):
                return shape.why_not(Box(x, y, x, y), occ.edge_margin) is not None
            for r in range(rows):
                y = inner.top + r * step
                for c in range(cols):
                    x = inner.left + c * step
                    h = step / 2
                    if not covered:
                        if shape.why_not(Box(x, y, x + step, y + step), occ.edge_margin) is not None:
                            mask[r][c] = False
                    elif out(x, y) and out(x + step, y) and out(x, y + step) and out(x + step, y + step) \
                            and out(x + h, y + h):
                        mask[r][c] = False
        cache[key] = (shape, mask)          # the shape is held so its id cannot be reused
    return cache[key][1]


def _cells(box: Box, inner: Box, step: float, rows: int, cols: int, covered: bool):
    """(r0, r1, c0, c1) of the cells a blocker's box touches, or with
    `covered` the cells wholly inside it; None when there are none."""
    if covered:
        c0 = max(0, int(math.ceil((box.left - inner.left) / step - 1e-9)))
        c1 = min(cols, int(math.floor((box.right - inner.left) / step + 1e-9)))
        r0 = max(0, int(math.ceil((box.top - inner.top) / step - 1e-9)))
        r1 = min(rows, int(math.floor((box.bottom - inner.top) / step + 1e-9)))
    else:
        c0 = max(0, int((box.left - inner.left) / step))
        c1 = min(cols, int(math.ceil((box.right - inner.left) / step)))
        r0 = max(0, int((box.top - inner.top) / step))
        r1 = min(rows, int(math.ceil((box.bottom - inner.top) / step)))
    if c1 <= c0 or r1 <= r0:
        return None
    return r0, r1, c0, c1


def _convex(poly) -> bool:
    n = len(poly)
    sign = 0
    for k in range(n):
        (x0, y0), (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % n], poly[(k + 2) % n]
        z = (x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)
        if abs(z) > 1e-12:
            if sign and (z > 0) != (sign > 0):
                return False
            sign = 1 if z > 0 else -1
    return True


def pockets(occ: Occupancy, width: float, height: float, face: Face = Face.FRONT, step: float = 0.5,
            limit: int = 8, covered: bool = False) -> list:
    """The free rectangles on `face` at least `width` x `height`, biggest
    first: the board rastered at `step`, what parts claim on that face
    blocked (courtyards and holes; bodies, pads and silk too in a drawn
    envelope) and every through-via, the edge margin excluded, the largest
    free rectangle the size fits taken and masked out until none is left or
    `limit` pockets are found.

    A cell anything touches is taken, so a pocket is room a search can use.
    With `covered` only the cells wholly inside a blocker are, so the
    raster rounds toward room: no pocket then means a search cannot
    succeed, and that is what the check before a search asks."""
    board = occ.board_box
    if board is None:
        return []
    inner = board.inflate(-occ.edge_margin)
    if covered:                                             # a part cell at the far side is room too
        cols, rows = int(math.ceil(inner.width / step - 1e-9)), int(math.ceil(inner.height / step - 1e-9))
    else:
        cols, rows = int(inner.width / step), int(inner.height / step)
    if cols <= 0 or rows <= 0:
        return []
    free = [row[:] for row in _board_mask(occ, inner, rows, cols, step, covered)]
    kinds = ("courtyard", "npth", "through") if occ.envelope == "courtyard" else \
        ("courtyard", "npth", "through", "body", "pad", "silk")          # what a drawn envelope claims instead
    # A part the script has not placed yet is pending: it stands where the
    # generator left it, which is nowhere, and blocks nothing.
    blocks = [s.poly for owner, g in occ.items.items() if owner not in occ.pending for s in g.shapes
              if s.kind in kinds and face in s.faces]
    blocks += [c.poly for c in occ.copper if c.kind == "through"]      # vias come through: no face is free under them
    for poly in blocks:
        box = Box.of_points(poly)
        span = _cells(box, inner, step, rows, cols, covered)
        if span is None:
            continue
        r0, r1, c0, c1 = span
        rect = _rect_of(poly) or not covered            # touched: the box is what blocks
        if not rect and not _convex(poly):
            continue                                    # covered, and a concave shape: none is sure
        for r in range(r0, r1):
            row = free[r]
            y0, y1 = inner.top + r * step, inner.top + (r + 1) * step
            for c in range(c0, c1):
                if not rect:
                    x0, x1 = inner.left + c * step, inner.left + (c + 1) * step
                    if not all(point_in_polygon(q, poly) for q in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))):
                        continue
                row[c] = False
    # An item w wide meets at least ceil(w / step) cells, however it sits.
    need_c, need_r = int(math.ceil(width / step - 1e-9)), int(math.ceil(height / step - 1e-9))
    if not covered:
        need_c, need_r = int(math.ceil(width / step)), int(math.ceil(height / step))
    out = []
    while len(out) < limit:
        best = _largest_rectangle(free, rows, cols, need_r, need_c)
        if best is None:
            break
        area, r0, c0, r1, c1 = best
        out.append(Pocket(Box(inner.left + c0 * step, inner.top + r0 * step,
                              min(inner.right, inner.left + c1 * step), min(inner.bottom, inner.top + r1 * step)), face))
        for r in range(r0, r1):
            for c in range(c0, c1):
                free[r][c] = False
    return out


@dataclass(frozen=True)
class BlockSpec:
    """A part and the satellites that sit at its pins: (satellite footprint,
    the net it serves) pairs, each placed on its pin's axis `gap` out."""
    anchor: object                   # Footprint
    satellites: tuple                # ((Footprint, net), ...)
    gap: float | None = None         # pad edge to pin edge; None: as close as the two courtyards allow
    pins: tuple = ()                 # the anchor pad NUMBER each satellite is aimed at; () - the first pad on its net
    named: tuple = ()                # per satellite, True when the script named the pad by number

    @property
    def key(self) -> str:
        return "block %s" % self.anchor.inst

    @property
    def members(self):
        return (self.anchor,) + tuple(fp for fp, _ in self.satellites)


GAP_STEP = 0.05
"""How finely a block's tightest gap is searched: the fab's placement grid.
`[place] block_gap_step`."""
GAP_REACH = 2.0
"""How far a satellite may stand off its pin before the block gives up: past
this the part is not at its pin. `[place] block_gap_reach`."""


def layout_block(occ: Occupancy, spec: BlockSpec, anchor: Placement, clearance=None, others=None,
                 past_edge: bool = False):
    """Satellite placements for the block with its anchor at `anchor`, or a
    reason the block cannot sit there. Each satellite's pad on its served
    net lands on the anchor pin's axis (the normal of its pad row, see
    `_pin_normal`), `gap` beyond the pin, with the
    satellite's body outward of its pad; where no spot on the normal is
    legal (a satellite wider than the pitch beside another), it slides along
    the pin's row, up to `block_gap_reach`, unless another satellite already
    sits at that pin. `others`, from `block_obstacles`,
    is each member's obstacles gathered once for a whole scan. `past_edge`
    lets the ANCHOR alone cross the edge margin, as a lone part on the same
    declaration would; a satellite is still placed at its pin's normal and
    keeps clear of the edge, since nothing in the script declared its own
    reach past it."""
    others = others or {}
    why = occ.legal(spec.anchor, anchor, clearance, others=others.get(spec.anchor.inst), past_edge=past_edge)
    if why:
        return None, "anchor: " + why
    pads = occ.candidate_pad_locations(spec.anchor, anchor)
    centre = occ.body_box(spec.anchor, anchor).center
    out = {spec.anchor.inst: anchor}
    _, ashapes = occ.candidate_shapes(spec.anchor, anchor)
    pad_boxes = {}
    for sh in ashapes:
        if sh.kind in ("pad", "through") and sh.owner == spec.anchor.ref:
            pad_boxes[sh.label] = sh.box if sh.label not in pad_boxes else Box.union([pad_boxes[sh.label], sh.box])
    # In a drawn envelope a member is judged against the members already laid
    # as against any other part: silk, mask openings, bodies and pads, each at
    # its gap. The courtyards alone are what a courtyard envelope claims. The
    # anchor and the satellites laid are kept apart: the gap at which a
    # satellite clears the anchor alone is where it slides along the row.
    drawn = occ.envelope != "courtyard"
    anchor_yard = [sh.poly for sh in ashapes if sh.kind == "courtyard"]
    anchor_laid = ShapeIndex(ashapes + occ.shifted_yards(spec.anchor, anchor)) if drawn else ShapeIndex()
    taken = []          # courtyard polygons of the satellites already laid
    laid = ShapeIndex()

    def meets(mine, sshapes, yards, index):
        return (any(polys_overlap(a, b) for a in mine for b in yards)
                or any(occ._conflict(a, b, clearance) for a in sshapes for b in index.near(a.box, occ.gap_for(a))))

    step_mm, reach = occ.settings.place_block_gap_step, occ.settings.place_block_gap_reach
    for k, (sat, net) in enumerate(spec.satellites):
        pin = _aimed_at(spec, k, net)
        p = pads[(spec.anchor.ref, pin.number)]
        pin_box = pad_boxes.get(pin.number, pin.box)
        normal = _pin_normal(pads, spec.anchor.ref, p, anchor.rotation, pin_box)
        if normal is not None:
            ux, uy = normal
        else:
            ux, uy = p.x - centre.x, p.y - centre.y
            n = math.hypot(ux, uy)
            if n < 1e-9:
                ux, uy = 1.0, 0.0
            else:
                ux, uy = ux / n, uy / n
        sat_pin = sat.pad(net)
        half_anchor = _half_extent(pin_box, ux, uy)
        half_sat = _half_extent(sat_pin.box, ux, uy)
        # the gap the script named, else the smallest at which the two courtyards no longer touch
        gaps = [spec.gap] if spec.gap is not None else [round(g * step_mm, 6)
                                                        for g in range(int(reach / step_mm) + 1)]
        # The satellite's pad at each turn is the same whatever the gap: asked once.
        probes = {rot: occ.candidate_pad_locations(sat, Placement(Location(0.0, 0.0), rot, anchor.face))[
            (sat.ref, sat_pin.number)] for rot in (0, 90, 180, 270)}
        clear = {}          # turn -> the tightest gap on the normal at which it clears the anchor

        def attempt(gap, slide, rots, best):
            out_by = half_anchor + gap + half_sat
            target = Location(p.x + ux * out_by - uy * slide, p.y + uy * out_by + ux * slide)
            for rot in rots:
                sp = probes[rot]
                cand = Placement(Location(round(target.x - sp.x, 6), round(target.y - sp.y, 6)), rot, anchor.face)
                body = occ.shifted_body_box(sat, cand).center
                outward = (body.x - target.x) * ux + (body.y - target.y) * uy      # body beyond its pad, away from the anchor
                if outward < -1e-6:
                    continue
                # The members first: at the tightest gaps a satellite's courtyard
                # meets its anchor's, and that is cheaper to find than the board.
                if drawn:
                    sshapes = occ.shifted_shapes(sat, cand) + occ.shifted_yards(sat, cand)
                    mine = [sh.poly for sh in sshapes if sh.kind == "courtyard"]
                else:
                    sshapes = ()
                    mine = occ.shifted_courtyards(sat, cand)
                if meets(mine, sshapes, anchor_yard, anchor_laid):
                    continue
                if slide == 0.0:
                    clear.setdefault(rot, gap)
                if meets(mine, sshapes, taken, laid):
                    continue
                reason = occ.legal(sat, cand, clearance, others=others.get(sat.inst))
                if reason:
                    continue
                key = (-outward, rot)
                if best is None or key < best[0]:
                    best = (key, cand, mine, sshapes)
            return best

        best = None
        for gap in gaps:
            best = attempt(gap, 0.0, (0, 90, 180, 270), best)
            if best is not None:
                break                       # the tightest gap that works
        there = [s.inst for j, (s, n) in enumerate(spec.satellites[:k]) if _aimed_at(spec, j, n) is pin]
        if best is None and clear and not there:
            # Nothing on the normal: slide along the pin's row, the least that
            # works, at each turn's own gap off the anchor; away from the
            # row's middle first where both ways work.
            side = 1.0 if (p.x - centre.x) * -uy + (p.y - centre.y) * ux >= 0 else -1.0
            for j in range(1, int(reach / step_mm) + 1):
                for sign in (side, -side):
                    for rot, gap in sorted(clear.items()):
                        best = attempt(gap, sign * round(j * step_mm, 6), (rot,), best)
                    if best is not None:
                        break
                if best is not None:
                    break
        if best is None:
            if there:
                return None, "%s: no legal spot on the axis of %s; %s already sits there: aim at another pad, " \
                    "or link it instead" % (sat.inst, _aim_text(spec, k, pin, net), ", ".join(there))
            return None, "%s: no legal spot on the axis of %s, nor slid up to %g mm along its row" % (
                sat.inst, _aim_text(spec, k, pin, net), reach)
        out[sat.inst] = best[1]
        taken += best[2]
        if drawn:
            laid = ShapeIndex(list(laid) + list(best[3]))
    return out, None


def _extent(occ: Occupancy, item) -> float:
    """How far any of the item's shapes reaches from its origin, at any turn."""
    g = occ._geometry(item)
    o = g.reference.location
    return max(math.hypot(x - o.x, y - o.y) for sh in g.shapes
               for x in (sh.box.left, sh.box.right) for y in (sh.box.top, sh.box.bottom))


def slide_note(occ: Occupancy, spec: BlockSpec, members: dict, k: int) -> str | None:
    """How far the k-th satellite, as placed in `members`, stands along the
    pin row off its pin's axis, and which of the anchor's pins in that row its
    body is in front of; None when it is on the axis."""
    sat, net = spec.satellites[k]
    anchor_at, sat_at = members.get(spec.anchor.inst), members.get(sat.inst)
    if anchor_at is None or sat_at is None:
        return None
    pads = occ.candidate_pad_locations(spec.anchor, anchor_at)
    pin = _aimed_at(spec, k, net)
    p = pads[(spec.anchor.ref, pin.number)]
    _, ashapes = occ.candidate_shapes(spec.anchor, anchor_at)
    boxes = [sh.box for sh in ashapes if sh.kind in ("pad", "through") and sh.label == pin.number]
    pin_box = Box.union(boxes) if boxes else pin.box
    normal = _pin_normal(pads, spec.anchor.ref, p, anchor_at.rotation, pin_box)
    if normal is None:
        return None
    ux, uy = normal
    rx, ry = -uy, ux                                    # along the pin row
    s = occ.candidate_pad_locations(sat, sat_at)[(sat.ref, sat.pad(net).number)]
    slide = (s.x - p.x) * rx + (s.y - p.y) * ry
    if abs(slide) < 1e-3:
        return None
    body = occ.shifted_body_box(sat, sat_at)
    ts = [(x - p.x) * rx + (y - p.y) * ry for x in (body.left, body.right) for y in (body.top, body.bottom)]
    lo, hi = min(ts), max(ts)
    depth = _half_extent(pin_box, ux, uy)
    row = sorted((number for (ref, number), q in pads.items()
                  if ref == spec.anchor.ref and number != pin.number
                  and abs((q.x - p.x) * ux + (q.y - p.y) * uy) <= depth + 1e-6
                  and lo - 1e-6 <= (q.x - p.x) * rx + (q.y - p.y) * ry <= hi + 1e-6),
                 key=lambda n: (len(n), n))
    note = "slid %.2f mm along the pin row from %s pin %s's axis" % (abs(slide), spec.anchor.ref, pin.number)
    if row:
        note += "; in front of %s pin%s %s" % (spec.anchor.ref, "s" if len(row) > 1 else "", ", ".join(row))
    return note


def block_obstacles(occ: Occupancy, spec: BlockSpec, hint: Placement, radius: float) -> dict:
    """Each member's obstacles within reach of any layout of the block whose
    anchor is within `radius` of the hint: the anchor spans its own extent
    about its origin; a satellite's pad lands at most the anchor's extent plus
    the widest gap plus its own extent from the anchor's origin, and its
    shapes reach its extent again past that pad."""
    anchor = _extent(occ, spec.anchor)
    sats = [_extent(occ, sat) for sat, _ in spec.satellites]
    gap = spec.gap if spec.gap is not None else occ.settings.place_block_gap_reach
    reach = radius + 2 * anchor + gap + 3 * max(sats, default=0.0)
    x, y = hint.location.x, hint.location.y
    region = Box(x - reach, y - reach, x + reach, y + reach)
    return {m.inst: occ.obstacles(occ._geometry(m), region)
            for m in [spec.anchor] + [sat for sat, _ in spec.satellites]}


def _aimed_at(spec: BlockSpec, k: int, net: str):
    """The anchor pad satellite `k` sits at: the one the script numbered, or
    the first pad carrying its net."""
    if k < len(spec.pins):
        return next(p for p in spec.anchor.pads if p.number == spec.pins[k])
    return spec.anchor.pad(net)


def _aim_text(spec: BlockSpec, k: int, pin, net: str) -> str:
    """Which anchor pad a satellite was aimed at, and why that one."""
    text = "%s pad %s (%s" % (spec.anchor.ref, pin.number, net)
    by_number = k < len(spec.named) and spec.named[k]
    carrying = sum(1 for p in spec.anchor.pads if p.net == net)
    if not by_number and carrying > 1:
        text += ", the first of its %d pads on it: name a pad number to aim at another" % carrying
    return text + ")"


def _pin_normal(pads: dict, ref: str, p: Location, rotation: float, pin_box: Box):
    """The way out from pin `p`: the outward normal of the pad row it sits
    in. In the anchor's own axes the pin's row is the side of its pads'
    centres it is proportionally nearest; where two sides tie (a corner of
    the pad field) the pad's long side decides, as a pad runs across its
    row. None when neither does - a square pad at a corner, or the one pad
    at the centre - and the ray from the body's centre is used instead."""
    to_part, to_board = Transform.rotate(-rotation), Transform.rotate(rotation)
    local = [to_part.apply((q.x, q.y)) for (r, _), q in pads.items() if r == ref]
    xs, ys = [q[0] for q in local], [q[1] for q in local]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    hw, hh = (max(xs) - min(xs)) / 2.0, (max(ys) - min(ys)) / 2.0
    px, py = to_part.apply((p.x, p.y))
    rx = abs(px - cx) / hw if hw > 1e-6 else 0.0
    ry = abs(py - cy) / hh if hh > 1e-6 else 0.0
    if abs(rx - ry) < 1e-6:
        w, h = pin_box.width, pin_box.height
        if rotation % 180 == 90:
            w, h = h, w
        if abs(w - h) < 1e-6:
            return None
        rx, ry = (1.0, 0.0) if w > h else (0.0, 1.0)
    n = (1.0 if px >= cx else -1.0, 0.0) if rx > ry else (0.0, 1.0 if py >= cy else -1.0)
    ux, uy = to_board.apply(n)
    size = math.hypot(ux, uy)
    return ux / size, uy / size


def _half_extent(box: Box, ux: float, uy: float) -> float:
    return abs(ux) * box.width / 2.0 + abs(uy) * box.height / 2.0


def scan_block(occ: Occupancy, spec: BlockSpec, hint: Placement, radius: float, step: float,
               rotations=None, clearance=None, score=None, pick=None):
    """The block's anchor placement (and its members') nearest the hint, or
    with the lowest score, where every member is legal. A scored scan over a
    wide radius is coarse first, then fine around its best spots, as a single
    part's is: laying the whole block out is the most expensive question the
    placer asks, and a block that fits anywhere fits over a patch wider than
    one step."""
    rots = tuple(sorted({(r % 360) for r in (rotations or (hint.rotation,))}))
    rejected: Counter = Counter()
    reasons: dict = {}
    tried = 0
    hx, hy = hint.location.x, hint.location.y
    seen: set = set()
    others = block_obstacles(occ, spec, hint, radius)

    def sweep(points, stop_at_first: bool) -> list:
        """Lay the block out at every (x, y) in `points` at every rotation;
        the ones that fit as (key, anchor placement, members)."""
        nonlocal tried
        fits = []
        for x, y in points:
            for rot in rots:
                if (x, y, rot) in seen:
                    continue
                seen.add((x, y, rot))
                cand = Placement(Location(x, y), rot, hint.face)
                tried += 1
                members, why = layout_block(occ, spec, cand, clearance, others)
                if members is None:
                    key = _reason_key(why)
                    rejected[key] += 1
                    reasons.setdefault(key, why)
                    continue
                d = math.hypot(x - hx, y - hy)
                fits.append(((score(members) if score else 0.0, d, rot), cand, members))
                if stop_at_first:
                    return fits
        return fits

    cfg = occ.settings
    if score is None or radius / step < cfg.place_coarse_from:
        fits = sweep(((x, y) for _, x, y in _grid(hint.location, radius, step)), score is None)
    else:
        coarse = step * cfg.place_coarse_steps
        fits = sweep(((x, y) for _, x, y in _grid(hint.location, radius, coarse)), False)
        if not fits:
            fits = sweep(((x, y) for _, x, y in _grid(hint.location, radius, coarse / 2)), False)
        if not fits:
            fits = sweep(((x, y) for _, x, y in _grid(hint.location, radius, step)), False)
        if fits:
            fits.sort(key=lambda f: f[0])
            for _, cand, _ in fits[:cfg.place_refine_around]:
                # The fine grid is centred on a coarse candidate, which can sit
                # at the edge of the radius: keep only what is still inside it.
                fits += sweep(((x, y) for _, x, y in _grid(cand.location, coarse, step)
                               if math.hypot(x - hx, y - hy) <= radius + 1e-9), False)
    if not fits:
        best = None
    elif pick is None:
        best = min(fits, key=lambda f: f[0])
    else:                                   # explore: drawn as a part's are, best first
        best = pick([f[0] + (f,) for f in sorted(fits, key=lambda f: f[0])])[3]
    return best, tried, rejected, reasons
