"""Searches for legal placements against an Occupancy: a grid scan around a
hint, edge-flush placement, box-centred placement. Deterministic: candidates
enumerate in a fixed order and ties break on distance, rotation, x, y."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math

from .geometry import polys_overlap
from .occupancy import Occupancy
from .placement import Placement
from .values import Box, Edge, Face, Location


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
                legal += sweep(((x, y) for _, x, y in _grid(cand.location, coarse, step)), False)
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
    blocked, the edge margin excluded, the largest free rectangle taken and
    masked out until nothing fits or `limit` pockets are found."""
    board = occ.board_box
    if board is None:
        return []
    inner = board.inflate(-occ.edge_margin)
    cols = int(inner.width / step)
    rows = int(inner.height / step)
    if cols <= 0 or rows <= 0:
        return []
    free = [[True] * cols for _ in range(rows)]
    blocks = [s.box for g in occ.items.values() for s in g.shapes
              if s.kind in ("courtyard", "npth", "through") and face in s.faces]
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
    gap: float = 0.5

    @property
    def key(self) -> str:
        return "block %s" % self.anchor.inst

    @property
    def members(self):
        return (self.anchor,) + tuple(fp for fp, _ in self.satellites)


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
        target = Location(p.x + ux * (half_anchor + spec.gap + half_sat), p.y + uy * (half_anchor + spec.gap + half_sat))
        best = None
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
