"""Searches for legal placements against an Occupancy: a grid scan around a
hint, edge-flush placement, box-centred placement. Deterministic: candidates
enumerate in a fixed order and ties break on distance, rotation, x, y."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math

from .geometry import polys_overlap, transform_box
from .occupancy import Occupancy
from .placement import Placement
from .values import Box, Edge, Face, Location, bearing_vector, box_support


@dataclass
class ScanResult:
    chosen: Placement | None
    hint: Placement
    tried: int
    rejected: Counter = field(default_factory=Counter)
    reasons: dict = field(default_factory=dict)
    score: float = 0.0

    @property
    def moved_mm(self) -> float:
        if self.chosen is None:
            return math.inf
        return self.chosen.location.distance(self.hint.location)

    def __iter__(self):
        yield from self.rejected


def _grid(center: Location, radius: float, step: float):
    n = int(math.floor(radius / step + 1e-9))
    pts = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x, y = center.x + i * step, center.y + j * step
            d = math.hypot(i * step, j * step)
            if d <= radius + 1e-9:
                pts.append((d, round(x, 6), round(y, 6)))
    pts.sort()
    return pts


COARSE_STEPS = 4
"""A scored scan over a wide radius first walks a grid this many steps
apart and refines to the step only around its best spots."""
COARSE_FROM = 12
"""Radius-to-step ratio from which a scored scan goes coarse first: below
it the fine grid is a few hundred points and not worth two passes."""
REFINE_AROUND = 3
"""How many of the best coarse spots get a fine pass."""


def scan(occ: Occupancy, item, hint: Placement, radius: float, step: float,
         rotations=None, clearance: float | None = None, commit: bool = False, score=None) -> ScanResult:
    """A legal location within `radius` of `hint`, on a `step` grid, trying
    each rotation at each location. Without `score` it is the nearest legal
    candidate to the hint; with `score(placement) -> float` it is the legal
    candidate with the lowest score, ties broken by distance from the hint,
    then rotation. Rotations are tried in numeric order regardless of how
    they were passed. A scored scan over a wide radius is coarse first,
    then fine around its best spots."""
    rots = tuple(sorted({(r % 360) for r in (rotations or (hint.rotation,))}))
    rejected: Counter = Counter()
    reasons: dict = {}
    tried = 0
    geom = occ._geometry(item)
    reach = radius + max(geom.body.width, geom.body.height)       # any rotation of the body, anywhere in the scan
    region = Box(hint.location.x - reach, hint.location.y - reach, hint.location.x + reach, hint.location.y + reach)
    others = occ.obstacles(geom, region)
    seen: set = set()

    def sweep(points, stop_at_first: bool) -> list:
        """Evaluate every (x, y) in `points` at every rotation; the legal
        ones as (score, distance from the hint, rotation, placement)."""
        nonlocal tried
        legal = []
        for x, y in points:
            for rot in rots:
                if (x, y, rot) in seen:
                    continue
                seen.add((x, y, rot))
                cand = Placement(Location(x, y), rot, hint.face)
                tried += 1
                why = occ.legal(item, cand, clearance, others=others)
                if why is None:
                    d = math.hypot(x - hint.location.x, y - hint.location.y)
                    legal.append((score(cand) if score else 0.0, d, rot, cand))
                    if stop_at_first:
                        return legal
                    continue
                key = _reason_key(why)
                rejected[key] += 1
                reasons.setdefault(key, why)
        return legal

    if score is None or radius / step < COARSE_FROM:
        legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, step)), stop_at_first=score is None)
    else:
        coarse = step * COARSE_STEPS
        legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, coarse)), False)
        if not legal:
            legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, coarse / 2)), False)
        if legal:
            legal.sort(key=lambda k: k[:3])
            for _, _, _, cand in legal[:REFINE_AROUND]:
                # The fine grid is centred on a coarse candidate, which can sit at
                # the edge of the radius: keep only what is still inside it, so
                # "within radius of the hint" is what a script gets.
                legal += sweep(((x, y) for _, x, y in _grid(cand.location, coarse, step)
                                if math.hypot(x - hint.location.x, y - hint.location.y) <= radius + 1e-9), False)
    if not legal:
        return ScanResult(None, hint, tried, rejected, reasons)
    best = min(legal, key=lambda k: k[:3])
    chosen = best[3]
    if commit:
        occ.commit(item, chosen)
    result = ScanResult(chosen, hint, tried, rejected, reasons)
    result.score = best[0]
    return result


def _reason_key(why: str) -> str:
    for word in ("courtyard", "edge", "reservation", "copper", "through", "npth"):
        if word in why:
            return word
    return why.split(" ")[0]


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
    d = max(0.0, standoff + box_support(what, out_b) / 2.0)
    limit = d + max(what.width, what.height) + 2.0
    while d < limit and not holds(d):
        d += 0.05
    if holds(d):
        d = _bisect(holds, 0.0, d, want_low=True) + _SLACK
    cx, cy = centre_at(d)
    return Placement(Location(round(cx - box.center.x, 6), round(cy - box.center.y, 6)), rotation, face)


def fixed_placement(occ: Occupancy, item, location: Location, rotation: float = 0.0,
                    face: Face = Face.FRONT) -> Placement:
    return Placement(location, rotation, face)


def box_centered_placement(occ: Occupancy, item, center: Location, rotation: float = 0.0,
                           face: Face = Face.FRONT) -> Placement:
    """The placement whose BODY BOX is centred on `center` (a group's centre is
    its box centre, not its origin)."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    box = occ.body_box(item, probe)
    return Placement(Location(round(center.x - box.center.x, 6), round(center.y - box.center.y, 6)),
                     rotation, face)


def pad_anchored_placement(occ: Occupancy, item, key, point: Location, rotation: float = 0.0,
                           face: Face = Face.FRONT) -> Placement:
    """The placement that puts the item's pad `key` (a number or a net) on
    `point` at `rotation`."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    number = item.pad(key).number
    geom = occ._geometry(item)
    t = occ._transform(geom, probe)
    boxes = [transform_box(s.box, t) for s in geom.shapes if s.kind in ("pad", "through") and s.label == number]
    at = Box.union(boxes).center
    return Placement(Location(round(point.x - at.x, 6), round(point.y - at.y, 6)), rotation, face)


@dataclass(frozen=True)
class Pocket:
    """A free rectangle on one face, found by scanning the board."""
    box: Box
    face: Face


def _largest_rectangle(free, rows, cols):
    """Largest all-free axis-aligned rectangle in a boolean grid, by the
    histogram method. Returns (area, r0, c0, r1, c1) exclusive, or None."""
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
                if sh and (best is None or area > best[0]):
                    best = (area, r - sh + 1, s, r + 1, c)
                start = s
            stack.append((start, h))
    return best


def pockets(occ: Occupancy, width: float, height: float, face: Face = Face.FRONT, step: float = 0.5,
            limit: int = 8) -> list:
    """The free rectangles on `face` at least `width` x `height`, biggest
    first: the board rastered at `step`, courtyards and holes on that face
    and every through-via blocked, the edge margin excluded, the largest
    free rectangle taken and masked out until nothing fits or `limit`
    pockets are found. An upper bound on where a search can succeed."""
    board = occ.board_box
    if board is None:
        return []
    inner = board.inflate(-occ.edge_margin)
    cols = int(inner.width / step)
    rows = int(inner.height / step)
    if cols <= 0 or rows <= 0:
        return []
    free = [[True] * cols for _ in range(rows)]
    shape = occ.board_shape
    if shape is not None:                # a board that is not a rectangle: only cells inside it are free
        for r in range(rows):
            y = inner.top + r * step
            for c in range(cols):
                x = inner.left + c * step
                if shape.why_not(Box(x, y, x + step, y + step), occ.edge_margin) is not None:
                    free[r][c] = False
    blocks = [s.box for g in occ.items.values() for s in g.shapes
              if s.kind in ("courtyard", "npth", "through") and face in s.faces]
    blocks += [c.box for c in occ.copper if c.kind == "through"]        # vias come through: no face is free under them
    for b in blocks:
        c0 = max(0, int((b.left - inner.left) / step))
        c1 = min(cols, int(math.ceil((b.right - inner.left) / step)))
        r0 = max(0, int((b.top - inner.top) / step))
        r1 = min(rows, int(math.ceil((b.bottom - inner.top) / step)))
        for r in range(r0, r1):
            row = free[r]
            for c in range(c0, c1):
                row[c] = False
    need_c, need_r = int(math.ceil(width / step)), int(math.ceil(height / step))
    out = []
    while len(out) < limit:
        best = _largest_rectangle(free, rows, cols)
        if best is None:
            break
        area, r0, c0, r1, c1 = best
        if (c1 - c0) < need_c or (r1 - r0) < need_r:
            break
        out.append(Pocket(Box(inner.left + c0 * step, inner.top + r0 * step,
                              inner.left + c1 * step, inner.top + r1 * step), face))
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

    @property
    def key(self) -> str:
        return "block %s" % self.anchor.inst

    @property
    def members(self):
        return (self.anchor,) + tuple(fp for fp, _ in self.satellites)


GAP_STEP = 0.05
"""How finely a block's tightest gap is searched: the fab's placement grid."""
GAP_REACH = 2.0
"""How far a satellite may stand off its pin before the block gives up: past
this the part is not at its pin."""


def layout_block(occ: Occupancy, spec: BlockSpec, anchor: Placement, clearance=None):
    """Satellite placements for the block with its anchor at `anchor`, or a
    reason the block cannot sit there. Each satellite's pad on its served
    net lands on the anchor pin's axis, `gap` beyond the pin, with the
    satellite's body outward of its pad."""
    why = occ.legal(spec.anchor, anchor, clearance)
    if why:
        return None, "anchor: " + why
    pads = occ.candidate_pad_locations(spec.anchor, anchor)
    centre = occ.body_box(spec.anchor, anchor).center
    out = {spec.anchor.inst: anchor}
    taken = []          # courtyard polygons of members already laid, for member-vs-member checks
    _, ashapes = occ.candidate_shapes(spec.anchor, anchor)
    taken += [sh.poly for sh in ashapes if sh.kind == "courtyard"]
    for sat, net in spec.satellites:
        pin = spec.anchor.pad(net)
        p = pads[(spec.anchor.ref, pin.number)]
        ux, uy = p.x - centre.x, p.y - centre.y
        n = math.hypot(ux, uy)
        if n < 1e-9:
            ux, uy = 1.0, 0.0
        else:
            ux, uy = ux / n, uy / n
        sat_pin = sat.pad(net)
        half_anchor = _half_extent(pin.box, ux, uy)
        half_sat = _half_extent(sat_pin.box, ux, uy)
        # the gap the script named, else the smallest at which the two courtyards no longer touch
        gaps = [spec.gap] if spec.gap is not None else [round(g * GAP_STEP, 6) for g in range(int(GAP_REACH / GAP_STEP) + 1)]
        best = None
        for gap in gaps:
            target = Location(p.x + ux * (half_anchor + gap + half_sat), p.y + uy * (half_anchor + gap + half_sat))
            for rot in (0, 90, 180, 270):
                probe = Placement(Location(0.0, 0.0), rot, anchor.face)
                sp = occ.candidate_pad_locations(sat, probe)[(sat.ref, sat_pin.number)]
                cand = Placement(Location(round(target.x - sp.x, 6), round(target.y - sp.y, 6)), rot, anchor.face)
                body = occ.body_box(sat, cand).center
                outward = (body.x - target.x) * ux + (body.y - target.y) * uy      # body beyond its pad, away from the anchor
                if outward < -1e-6:
                    continue
                reason = occ.legal(sat, cand, clearance)
                if reason:
                    continue
                _, sshapes = occ.candidate_shapes(sat, cand)
                mine = [sh.poly for sh in sshapes if sh.kind == "courtyard"]
                if any(polys_overlap(a, b) for a in mine for b in taken):
                    continue
                key = (-outward, rot)
                if best is None or key < best[0]:
                    best = (key, cand, mine)
            if best is not None:
                break                       # the tightest gap that works
        if best is None:
            return None, "%s: no legal spot on the %s pin's axis" % (sat.inst, net)
        out[sat.inst] = best[1]
        taken += best[2]
    return out, None


def _half_extent(box: Box, ux: float, uy: float) -> float:
    return abs(ux) * box.width / 2.0 + abs(uy) * box.height / 2.0


def scan_block(occ: Occupancy, spec: BlockSpec, hint: Placement, radius: float, step: float,
               rotations=None, clearance=None, score=None):
    """The block's anchor placement (and its members') nearest the hint, or
    with the lowest score, where every member is legal."""
    rots = tuple(sorted({(r % 360) for r in (rotations or (hint.rotation,))}))
    rejected: Counter = Counter()
    reasons: dict = {}
    best = None
    tried = 0
    for d, x, y in _grid(hint.location, radius, step):
        for rot in rots:
            cand = Placement(Location(x, y), rot, hint.face)
            tried += 1
            members, why = layout_block(occ, spec, cand, clearance)
            if members is None:
                key = _reason_key(why)
                rejected[key] += 1
                reasons.setdefault(key, why)
                continue
            sc = score(members) if score else 0.0
            k = (sc, d, rot)
            if best is None or k < best[0]:
                best = (k, cand, members)
            if score is None:
                break
        if best is not None and score is None:
            break
    return best, tried, rejected, reasons
