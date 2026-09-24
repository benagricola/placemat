"""Searches for legal placements against an Occupancy: a grid scan around a
hint (scored or nearest), a block laid out at its anchor's pins and scanned
as one, the free rectangles (pockets) of a face, and the placements that put
an item flush on an edge, centred on a point or round a ring. Deterministic:
candidates enumerate in a fixed order and ties break on distance, rotation,
x, y."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math

from . import geometry as _geometry_module
from .geometry import _rect_of, point_in_polygon, polys_overlap, transform_box
from .occupancy import Occupancy, ShapeIndex, _reason_key
from .placement import Placement
from .values import Box, Edge, Face, Location, bearing_vector, box_support


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
apart and refines to the step only around its best spots. The default for
`[place] coarse_steps`; a board's own is carried on its Occupancy."""
COARSE_FROM = 12
"""Radius-to-step ratio from which a scored scan goes coarse first: below
it the fine grid is a few hundred points and not worth two passes.
`[place] coarse_from`."""
REFINE_AROUND = 3
"""How many of the best coarse spots get a fine pass. `[place] refine_around`."""


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
    blockers: Counter = Counter()
    tried = 0
    geom = occ._geometry(item)
    span = geom.body if occ.envelope == "courtyard" else occ._extent(geom)     # silk can stand past the body
    reach = radius + max(span.width, span.height)                  # any rotation of it, anywhere in the scan
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
                blame = []
                # legal_bucket: a sweep never keeps more than one example
                # sentence per bucket (the `key not in reasons` check below),
                # so it asks for the sentence only the first time a bucket is
                # seen - see Occupancy.legal_bucket's own doc for why this
                # matters on the native path.
                hit = occ.legal_bucket(item, cand, clearance, others, blame)
                if hit is None:
                    d = math.hypot(x - hint.location.x, y - hint.location.y)
                    legal.append((score(cand) if score else 0.0, d, rot, cand))
                    if stop_at_first:
                        return legal
                    continue
                key, get_reason = hit
                rejected[key] += 1
                if key not in reasons:
                    reasons[key] = get_reason()
                for b in blame:
                    blockers[(b.kind, b.owner, "/".join(sorted(f.value for f in b.faces)))] += 1
        return legal

    cfg = occ.settings
    if score is None or radius / step < cfg.place_coarse_from:
        legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, step)), stop_at_first=score is None)
    else:
        coarse = step * cfg.place_coarse_steps
        legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, coarse)), False)
        if not legal:
            legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, coarse / 2)), False)
        if not legal:
            # Nothing on either coarse lattice. The coarse pass is there to
            # save time, not to decide: the fine grid still gets its walk, so
            # a spot narrower than a coarse step is not reported as no room.
            legal = sweep(((x, y) for _, x, y in _grid(hint.location, radius, step)), False)
        if legal:
            legal.sort(key=lambda k: k[:3])
            for _, _, _, cand in legal[:cfg.place_refine_around]:
                # The fine grid is centred on a coarse candidate, which can sit at
                # the edge of the radius: keep only what is still inside it, so
                # "within radius of the hint" is what a script gets.
                legal += sweep(((x, y) for _, x, y in _grid(cand.location, coarse, step)
                                if math.hypot(x - hint.location.x, y - hint.location.y) <= radius + 1e-9), False)
    if not legal:
        return ScanResult(None, hint, tried, rejected, reasons, blockers)
    best = min(legal, key=lambda k: k[:3])
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


def layout_block(occ: Occupancy, spec: BlockSpec, anchor: Placement, clearance=None, others=None):
    """Satellite placements for the block with its anchor at `anchor`, or a
    reason the block cannot sit there. Each satellite's pad on its served
    net lands on the anchor pin's axis, `gap` beyond the pin, with the
    satellite's body outward of its pad. `others`, from `block_obstacles`,
    is each member's obstacles gathered once for a whole scan."""
    others = others or {}
    why = occ.legal(spec.anchor, anchor, clearance, others=others.get(spec.anchor.inst))
    if why:
        return None, "anchor: " + why
    pads = occ.candidate_pad_locations(spec.anchor, anchor)
    centre = occ.body_box(spec.anchor, anchor).center
    out = {spec.anchor.inst: anchor}
    taken = []          # courtyard polygons of members already laid, for member-vs-member checks
    _, ashapes = occ.candidate_shapes(spec.anchor, anchor)
    taken += [sh.poly for sh in ashapes if sh.kind == "courtyard"]
    # In a drawn envelope a member is judged against the members already laid
    # as against any other part: silk, mask openings, bodies and pads, each at
    # its gap. The courtyards alone are what a courtyard envelope claims.
    drawn = occ.envelope != "courtyard"
    laid = ShapeIndex(ashapes) if drawn else ShapeIndex()
    for k, (sat, net) in enumerate(spec.satellites):
        pin = _aimed_at(spec, k, net)
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
        step_mm, reach = occ.settings.place_block_gap_step, occ.settings.place_block_gap_reach
        gaps = [spec.gap] if spec.gap is not None else [round(g * step_mm, 6)
                                                        for g in range(int(reach / step_mm) + 1)]
        best = None
        # The satellite's pad at each turn is the same whatever the gap: asked once.
        probes = {rot: occ.candidate_pad_locations(sat, Placement(Location(0.0, 0.0), rot, anchor.face))[
            (sat.ref, sat_pin.number)] for rot in (0, 90, 180, 270)}
        for gap in gaps:
            target = Location(p.x + ux * (half_anchor + gap + half_sat), p.y + uy * (half_anchor + gap + half_sat))
            for rot in (0, 90, 180, 270):
                sp = probes[rot]
                cand = Placement(Location(round(target.x - sp.x, 6), round(target.y - sp.y, 6)), rot, anchor.face)
                body = occ.shifted_body_box(sat, cand).center
                outward = (body.x - target.x) * ux + (body.y - target.y) * uy      # body beyond its pad, away from the anchor
                if outward < -1e-6:
                    continue
                # The members first: at the tightest gaps a satellite's courtyard
                # meets its anchor's, and that is cheaper to find than the board.
                if drawn:
                    sshapes = occ.shifted_shapes(sat, cand)
                    mine = [sh.poly for sh in sshapes if sh.kind == "courtyard"]
                    if any(polys_overlap(a, b) for a in mine for b in taken):
                        continue
                    if any(occ._conflict(a, b, clearance)
                           for a in sshapes for b in laid.near(a.box, occ.gap_for(a))):
                        continue
                else:
                    sshapes = ()
                    mine = occ.shifted_courtyards(sat, cand)
                    if any(polys_overlap(a, b) for a in mine for b in taken):
                        continue
                reason = occ.legal(sat, cand, clearance, others=others.get(sat.inst))
                if reason:
                    continue
                key = (-outward, rot)
                if best is None or key < best[0]:
                    best = (key, cand, mine, sshapes)
            if best is not None:
                break                       # the tightest gap that works
        if best is None:
            there = [s.inst for j, (s, n) in enumerate(spec.satellites[:k]) if _aimed_at(spec, j, n) is pin]
            return None, "%s: no legal spot on the axis of %s%s" % (
                sat.inst, _aim_text(spec, k, pin, net),
                "; %s already sits there: aim at another pad, or link it instead" % ", ".join(there) if there else "")
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


def _half_extent(box: Box, ux: float, uy: float) -> float:
    return abs(ux) * box.width / 2.0 + abs(uy) * box.height / 2.0


def scan_block(occ: Occupancy, spec: BlockSpec, hint: Placement, radius: float, step: float,
               rotations=None, clearance=None, score=None):
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
    best = min(fits, key=lambda f: f[0]) if fits else None
    return best, tried, rejected, reasons
