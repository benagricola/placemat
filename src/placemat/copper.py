"""Plans copper. The concrete shapes the writer draws (Track, Via, Pour,
Zone), the bridge resolver that settles same-layer crossings by priority,
the pair drawn at a gap along one centreline, the finger pour that steps
round tracks, and the board-sized zone outline."""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from .geometry import Polygon
from .values import Box, CopperLayer, Location, Net

# A bridge passes under a crossed track: via land (0.30) + clearance (0.20)
# + crossed track half-width (0.15) + margin (0.45) each side of the crossing.
BRIDGE_HALF = 1.1


# ------------------------------------------------------------------ concrete ops
@dataclass(frozen=True)
class Track:
    """One straight trace segment of `width` on one copper layer."""
    net: str
    layer: CopperLayer
    width: float
    start: Location
    end: Location

    @property
    def polygon(self) -> Polygon:
        return _segment_polygon(self.start, self.end, self.width)

    @property
    def box(self) -> Box:
        return Box.of_points(self.polygon)


@dataclass(frozen=True)
class Via:
    """A plated through hole joining every copper layer at one point."""
    net: str
    at: Location
    drill: float
    size: float

    @property
    def polygon(self) -> Polygon:
        r = self.size / 2.0
        return tuple((self.at.x + r * math.cos(2 * math.pi * i / 16),
                      self.at.y + r * math.sin(2 * math.pi * i / 16)) for i in range(16))

    @property
    def box(self) -> Box:
        return Box.of_points(self.polygon)


@dataclass(frozen=True)
class Pour:
    """A filled copper polygon of fixed shape on one layer. It is drawn exactly
    as given and never pulls back from other copper: a pour that touches a
    foreign pad is a short. `swallow_pads` grows it over the same-net pads
    its outline touches."""
    net: str
    layer: CopperLayer
    points: tuple[tuple[float, float], ...]
    stroke: float = 0.2
    swallow_pads: bool = False       # grow the outline over same-net pads it touches

    @property
    def polygon(self) -> Polygon:
        return self.points

    @property
    def box(self) -> Box:
        return Box.of_points(self.points)


@dataclass(frozen=True)
class Zone:
    """A KiCad zone: a filled area on one layer that KiCad fills, pulling back
    by the clearance round every pad, track and via of another net, and
    refills after any change. Use it for a plane; use a Pour where the copper
    must keep exactly the shape drawn."""
    net: str
    layer: CopperLayer
    points: tuple[tuple[float, float], ...]
    clearance: float = 0.2
    min_thickness: float = 0.2
    solid_pads: bool = True
    npth_clearance: float = 0.25

    @property
    def box(self) -> Box:
        return Box.of_points(self.points)


CopperOp = Track | Via | Pour | Zone


def _segment_polygon(a: Location, b: Location, width: float) -> Polygon:
    dx, dy = b.x - a.x, b.y - a.y
    n = math.hypot(dx, dy)
    h = width / 2.0
    if n == 0:
        return ((a.x - h, a.y - h), (a.x + h, a.y - h), (a.x + h, a.y + h), (a.x - h, a.y + h))
    ux, uy = dx / n, dy / n
    px, py = -uy * h, ux * h
    return ((a.x + px - ux * h, a.y + py - uy * h), (b.x + px + ux * h, b.y + py + uy * h),
            (b.x - px + ux * h, b.y - py + uy * h), (a.x - px - ux * h, a.y - py - uy * h))


def polyline_tracks(net: str, layer: CopperLayer, width: float, points) -> list[Track]:
    pts = [p if isinstance(p, Location) else Location(*p) for p in points]
    return [Track(net, layer, width, a, b) for a, b in zip(pts, pts[1:]) if a != b]


# ------------------------------------------------------------------ bridges
@dataclass(frozen=True)
class Crossing:
    net_a: str
    net_b: str
    at: Location


def _seg_intersection(p1, p2, q1, q2):
    """The point where segment p1-p2 crosses segment q1-q2, or None."""
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p1, p2, q1, q2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _crossing_point(a: Track, b: Track):
    if a.layer is not b.layer or a.net == b.net:
        return None
    return _seg_intersection((a.start.x, a.start.y), (a.end.x, a.end.y), (b.start.x, b.start.y), (b.end.x, b.end.y))


def bridge_track(track: Track, points, via_drill: float, via_size: float, half: float = BRIDGE_HALF) -> list:
    """Cut `track` at each of `points` and pass under: a via, a track on the
    opposite face `half` either side of the point, and a via back."""
    length = track.start.distance(track.end)
    ux, uy = (track.end.x - track.start.x) / length, (track.end.y - track.start.y) / length
    ordered = sorted(points, key=lambda p: math.hypot(p[0] - track.start.x, p[1] - track.start.y))
    ops = []
    cur = track.start
    for cx, cy in ordered:
        near = Location(round(cx - ux * half, 6), round(cy - uy * half, 6))
        far = Location(round(cx + ux * half, 6), round(cy + uy * half, 6))
        ops += polyline_tracks(track.net, track.layer, track.width, [cur, near])
        ops.append(Via(track.net, near, via_drill, via_size))
        ops.append(Via(track.net, far, via_drill, via_size))
        ops += polyline_tracks(track.net, track.layer.other_face, track.width, [near, far])
        cur = far
    ops += polyline_tracks(track.net, track.layer, track.width, [cur, track.end])
    return ops


def resolve_bridges(entries, fixed_tracks, via_drill: float, via_size: float):
    """Decide every same-layer crossing between tracks of different nets.

    `entries` are (Track, priority_rank, may_bridge) for the copper being
    planned; `fixed_tracks` are tracks already on the board, which never
    yield. At each crossing the lower priority track passes under; at equal
    priority the shorter one does. A crossing where the track that should
    yield may not bridge is returned as a finding and both tracks are drawn
    as declared. Returns (ops, notes, findings). The result does not depend
    on the order of `entries`."""
    entries = list(entries)
    cuts = {i: [] for i in range(len(entries))}
    notes, findings = [], []

    def yielder(i, j):
        (ta, pa, ba), (tb, pb, bb) = entries[i], entries[j]
        if pa != pb:
            return (i, "") if pa < pb else (j, "")
        la, lb = ta.start.distance(ta.end), tb.start.distance(tb.end)
        if abs(la - lb) > 1e-9:
            return (i, "shorter") if la < lb else (j, "shorter")
        return (i, "first by name") if (ta.net, ta.start) < (tb.net, tb.start) else (j, "first by name")

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            pt = _crossing_point(entries[i][0], entries[j][0])
            if pt is None:
                continue
            k, why = yielder(i, j)
            other = j if k == i else i
            if entries[k][2]:
                cuts[k].append(pt)
                if why:
                    notes.append("%s passes under %s at (%.2f, %.2f): %s" % (
                        entries[k][0].net, entries[other][0].net, pt[0], pt[1], why))
            else:
                findings.append("%s and %s cross on %s at (%.2f, %.2f) and neither may bridge" % (
                    entries[i][0].net, entries[j][0].net, entries[i][0].layer.value, pt[0], pt[1]))
        for ft in fixed_tracks:
            pt = _crossing_point(entries[i][0], ft)
            if pt is None:
                continue
            if entries[i][2]:
                cuts[i].append(pt)
            else:
                findings.append("%s crosses FIXED %s on %s at (%.2f, %.2f) and may not bridge" % (
                    entries[i][0].net, ft.net, ft.layer.value, pt[0], pt[1]))
    ops = []
    for i, (t, _, _) in enumerate(entries):
        seen = []
        for pt in cuts[i]:
            if not any(math.hypot(pt[0] - q[0], pt[1] - q[1]) < 1e-6 for q in seen):
                seen.append(pt)
        ops += bridge_track(t, seen, via_drill, via_size) if seen else [t]
    return ops, notes, findings


def finger_ops(net: str, layer: CopperLayer, a: Location, b: Location, width: float, lane_segments,
               via_drill: float, via_size: float, bridge_width: float = 1.0,
               notch_half: float = BRIDGE_HALF) -> list:
    """A finger: a rectangular pour of `width` along the centreline a-b (a
    wide copper reach from a big pour to a pad). Where a same-layer track of
    another net (given as segments) crosses the centreline the rectangle is
    cut into pieces either side of it, and each cut is bridged: a via, a
    track on the opposite face under the crossing track, and a via, so the
    pieces stay one net."""
    length = a.distance(b)
    if length < 1e-9:
        return []
    ux, uy = (b.x - a.x) / length, (b.y - a.y) / length
    nx, ny = -uy * width / 2.0, ux * width / 2.0
    cuts = []
    for s1, s2 in lane_segments:
        pt = _seg_intersection((a.x, a.y), (b.x, b.y), s1, s2)
        if pt is not None:
            cuts.append(math.hypot(pt[0] - a.x, pt[1] - a.y))
    bounds = [0.0]
    for c in sorted(set(round(c, 6) for c in cuts)):
        if 0 < c < length:
            bounds += [c - notch_half, c + notch_half]
    bounds.append(length)
    ops = []

    def at(s):
        return (round(a.x + ux * s, 6), round(a.y + uy * s, 6))
    for i in range(0, len(bounds), 2):
        s0, s1 = bounds[i], bounds[i + 1]
        if s1 > s0 + 0.05:
            (x0, y0), (x1, y1) = at(s0), at(s1)
            ops.append(Pour(net, layer, ((x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny))))
    for c in sorted(set(round(c, 6) for c in cuts)):
        if 0 < c < length:
            p, q = Location(*at(c - notch_half)), Location(*at(c + notch_half))
            ops.append(Via(net, p, via_drill, via_size))
            ops.append(Via(net, q, via_drill, via_size))
            ops += polyline_tracks(net, layer.other_face, bridge_width, [p, q])
    return ops


def board_zone_outline(width: float, height: float, inset: float, chamfer: float = 0.0) -> tuple:
    W, H, ch, i = width, height, chamfer, inset
    if ch:
        return ((ch + i, i), (W - ch - i, i), (W - i, ch + i), (W - i, H - ch - i),
                (W - ch - i, H - i), (ch + i, H - i), (i, H - ch - i), (i, ch + i))
    return ((i, i), (W - i, i), (W - i, H - i), (i, H - i))


# ------------------------------------------------------------------ pairs
def _unit(a: Location, b: Location):
    dx, dy = b.x - a.x, b.y - a.y
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else (0.0, 0.0)


def chamfered(pts: list, c: float) -> list:
    """Cut every right-angle corner of a polyline back by `c` along both
    legs, so it becomes two 45s (shorter where a leg is short). Other turns
    are left: a 45 is already on the grid, and cutting it would not be."""
    if c <= 0 or len(pts) < 3:
        return list(pts)
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, v, b = pts[i - 1], pts[i], pts[i + 1]
        u1, u2 = _unit(a, v), _unit(v, b)
        dot = u1[0] * u2[0] + u1[1] * u2[1]
        axis = all(abs(u[0]) < 1e-9 or abs(u[1]) < 1e-9 for u in (u1, u2))
        if abs(dot) > 1e-6 or not axis:       # only a right angle between axis legs is cut: a turn made of 45s is drawn as meant
            out.append(v)
            continue
        k = min(c, a.distance(v) / 2.0, v.distance(b) / 2.0)
        out.append(Location(round(v.x - u1[0] * k, 6), round(v.y - u1[1] * k, 6)))
        out.append(Location(round(v.x + u2[0] * k, 6), round(v.y + u2[1] * k, 6)))
    out.append(pts[-1])
    return out


def _offset(pts: list, d: float) -> list:
    """The polyline `d` to the left of `pts` (left of the direction of travel,
    y down), its corners mitred so the two lines stay parallel."""
    normals = []
    for a, b in zip(pts, pts[1:]):
        ux, uy = _unit(a, b)
        normals.append((uy, -ux))
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            nx, ny = normals[0]
        elif i == len(pts) - 1:
            nx, ny = normals[-1]
        else:
            n1, n2 = normals[i - 1], normals[i]
            s = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
            nx, ny = (n1, ) [0] if s < 1e-6 else ((n1[0] + n2[0]) / s, (n1[1] + n2[1]) / s)
        out.append(Location(round(p.x + d * nx, 6), round(p.y + d * ny, 6)))
    return out


def _point_seg(q: Location, a: Location, b: Location):
    """(distance, nearest point, t) from q to segment a-b."""
    dx, dy = b.x - a.x, b.y - a.y
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((q.x - a.x) * dx + (q.y - a.y) * dy) / l2))
    n = Location(a.x + t * dx, a.y + t * dy)
    return q.distance(n), n, t


def _seg_seg_dist(a, b, c, d) -> float:
    if _seg_intersection((a.x, a.y), (b.x, b.y), (c.x, c.y), (d.x, d.y)) is not None:
        return 0.0
    return min(_point_seg(a, c, d)[0], _point_seg(b, c, d)[0], _point_seg(c, a, b)[0], _point_seg(d, a, b)[0])


def _nearest(pts: list, q: Location):
    """The nearest point of a polyline to q: (point, segment index, t)."""
    best = None
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        dist, n, t = _point_seg(q, a, b)
        if best is None or dist < best[0]:
            best = (dist, n, i, t)
    return best[1], best[2], best[3]


def _dir(a: Location, b: Location):
    return (0 if abs(b.x - a.x) < 1e-9 else math.copysign(1, b.x - a.x),
            0 if abs(b.y - a.y) < 1e-9 else math.copysign(1, b.y - a.y))


def _turns(dirs: list) -> int:
    """Direction changes along a run of legs, a right angle between axis
    legs counting two: the chamfer will make it two 45s."""
    n = 0
    for d1, d2 in zip(dirs, dirs[1:]):
        if d1 is None or d2 is None or d1 == d2:
            continue
        axis1, axis2 = (d1[0] == 0 or d1[1] == 0), (d2[0] == 0 or d2[1] == 0)
        n += 2 if axis1 and axis2 and d1[0] * d2[0] + d1[1] * d2[1] == 0 else 1
    return n


def _leg_candidates(a: Location, b: Location) -> list:
    """Octilinear ways from a to b with at most three legs, each a list of
    points including a and b: the 45 at the start, at the end, or between
    two straights; two 45s round one straight; and the two right-angle
    L shapes. Every leg is at 0, 45 or 90 degrees."""
    dx, dy = b.x - a.x, b.y - a.y
    if abs(dx) < 1e-9 or abs(dy) < 1e-9 or abs(abs(dx) - abs(dy)) < 1e-9:
        return [[a, b]]
    sx, sy = math.copysign(1, dx), math.copysign(1, dy)
    m = min(abs(dx), abs(dy))                      # the diagonal's reach on each axis
    M = max(abs(dx), abs(dy))
    major_x = abs(dx) >= abs(dy)                   # the straight runs along the major axis

    def step(p, along, diag):
        """p moved `along` on the major axis and `diag` on both (45)."""
        ax = along + diag if major_x else diag
        ay = diag if major_x else along + diag
        return Location(round(p.x + sx * ax, 6), round(p.y + sy * ay, 6))
    out = []
    out.append([a, step(a, 0, m), b])                          # 45 then straight
    out.append([a, step(a, M - m, 0), b])                      # straight then 45
    for f in (0.25, 0.5, 0.75):                                # straight, 45, straight
        s1 = (M - m) * f
        out.append([a, step(a, s1, 0), step(a, s1, m), b])
    for f in (0.25, 0.5, 0.75):                                # 45, straight, 45
        d1 = m * f
        out.append([a, step(a, 0, d1), step(a, M - m, d1), b])
    out.append([a, Location(b.x, a.y), b])                     # the L shapes
    out.append([a, Location(a.x, b.y), b])
    return out


def route_leg(a: Location, b: Location, pad_a: bool, pad_b: bool, prev, nxt, clear) -> list:
    """The best octilinear way from a to b: among the candidates whose legs
    all `clear`, the fewest direction changes against the legs either side
    (a chamfered right angle counting two), then the shortest, then the 45
    at the pad end. If none clears, the fewest-turn candidate is returned
    and the conflict is left for the run to report."""
    scored = []
    for k, cand in enumerate(_leg_candidates(a, b)):
        dirs = [prev] + [_dir(p, q) for p, q in zip(cand, cand[1:])] + [nxt]
        turns = _turns(dirs)
        length = sum(p.distance(q) for p, q in zip(cand, cand[1:]))
        first = len(cand) == 3 and _dir(cand[0], cand[1])[0] != 0 and _dir(cand[0], cand[1])[1] != 0
        tie = 0 if (first and not (pad_b and not pad_a)) or (not first and pad_b and not pad_a) else 1
        ok = all(clear(p, q) for p, q in zip(cand, cand[1:])) if clear is not None else True
        scored.append((0 if ok else 1, turns, round(length, 6), tie, k, cand))
    scored.sort(key=lambda t: t[:5])
    return scored[0][5]


def octilinear(pts: list, at_pad=None, clear=None) -> list:
    """The polyline with every leg at 0, 45 or 90 degrees: a leg at another
    angle is routed by route_leg, the best clear octilinear way between its
    ends given the legs either side."""
    at_pad = at_pad or [False] * len(pts)
    out = [pts[0]] if pts else []
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        prev = _dir(out[-2], out[-1]) if len(out) > 1 else None
        nxt = _dir(b, pts[i + 2]) if i + 2 < len(pts) else None
        out += route_leg(a, b, at_pad[i], at_pad[i + 1], prev, nxt, clear)[1:]
    return out


def _dogleg(a: Location, b: Location) -> list:
    """From a to b as one 45 then one straight, the way a track leaves a pad."""
    dx, dy = b.x - a.x, b.y - a.y
    m = min(abs(dx), abs(dy))
    mid = Location(round(a.x + math.copysign(m, dx), 6), round(a.y + math.copysign(m, dy), 6))
    pts = [a, mid, b]
    return [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]


def _conflicts(path: list, other: list, limit: float) -> bool:
    return any(_seg_seg_dist(a, b, c, d) < limit for a, b in zip(path, path[1:]) for c, d in zip(other, other[1:]))


def pair_ops(net_p: str, net_n: str, layer: CopperLayer, width: float, gap: float, start, path, end,
             via_drill: float, via_size: float, via_step: float = 0.4, chamfer: float = 0.5,
             clearance: float = 0.2, start_faces=None, end_faces=None) -> list:
    """Two tracks at `gap` either side of the centreline `path`, from the pads
    in `start` to the pads in `end`. `start` and `end` are (P location, N
    location, P through-hole?, N through-hole?); `start_faces`/`end_faces`
    name the copper layer of a surface pad (default: the pair's layer).
    Corners are chamfered at 45. Each track leaves its pad at 45 then straight
    to the nearest point of its line. A lead that would touch the partner on
    the pair's layer, or whose pad has no copper there, goes over the other
    face from a via stepped `via_step` away from the partner."""
    h = (width + gap) / 2.0
    centre = chamfered([q if isinstance(q, Location) else Location(*q) for q in path], chamfer)

    def side(a, b, q):
        return (b.x - a.x) * (q.y - a.y) - (b.y - a.y) * (q.x - a.x)
    # P takes the side its pads lean to; on a tie, the left of travel
    lean = side(centre[0], centre[1], start[1]) - side(centre[0], centre[1], start[0]) + \
        side(centre[-2], centre[-1], end[1]) - side(centre[-2], centre[-1], end[0])
    p_sign = 1.0 if lean >= 0 else -1.0
    lines = {net_p: _offset(centre, p_sign * h), net_n: _offset(centre, -p_sign * h)}
    partner = {net_p: net_n, net_n: net_p}
    other = layer.other_face
    limit = width + clearance
    ends = ((0, start, start_faces or (layer, layer)), (-1, end, end_faces or (layer, layer)))
    leads = {net_p: [], net_n: []}       # (at_end_index, pad, plain lead, must lift)
    for k, (pad_p, pad_n, thru_p, thru_n), faces in ends:
        for net, pad, thru, face in ((net_p, pad_p, thru_p, faces[0]), (net_n, pad_n, thru_n, faces[1])):
            target, i, t = _nearest(lines[net], pad)
            plain = _dogleg(pad, target)
            leads[net].append([k, pad, plain, (i, t), not thru and face is not layer, thru or face is other])
    # a lead that touches the partner's line lifts; if only the two leads touch, the longer one does
    for k in (0, 1):
        lp, ln = leads[net_p][k], leads[net_n][k]
        hit_p = _conflicts(lp[2], lines[net_n], limit)
        hit_n = _conflicts(ln[2], lines[net_p], limit)
        if not hit_p and not hit_n and _conflicts(lp[2], ln[2], limit):
            if lp[1].distance(lp[2][-1]) >= ln[1].distance(ln[2][-1]):
                hit_p = True
            else:
                hit_n = True
        if hit_p and lp[5]:
            lp[4] = True
        if hit_n and ln[5]:
            ln[4] = True
    ops = []
    for net in (net_p, net_n):
        line = list(lines[net])
        pline = lines[partner[net]]
        extra = []
        for k, pad, plain, (i, t), lift, _ in sorted(leads[net], key=lambda e: (-e[3][0], -e[3][1])):   # later points first: earlier indices stay valid
            if not lift:
                extra += polyline_tracks(net, layer, width, plain)
                continue
            target = plain[-1]
            # the via sits off the line, away from the partner, joined by 45s
            near_partner = _nearest(pline, target)[0]
            nx, ny = _unit(near_partner, target)
            via_at = Location(round(target.x + nx * via_step, 6), round(target.y + ny * via_step, 6))
            if t <= 1e-9 and i == 0:
                u = _unit(line[0], line[1])
                line = [via_at, Location(round(line[0].x + u[0] * via_step, 6), round(line[0].y + u[1] * via_step, 6))] + line[1:]
            elif t >= 1 - 1e-9 and i == len(line) - 2:
                u = _unit(line[-1], line[-2])
                line = line[:-1] + [Location(round(line[-1].x + u[0] * via_step, 6), round(line[-1].y + u[1] * via_step, 6)), via_at]
            else:
                u = _unit(line[i], line[i + 1])
                before = Location(round(target.x - u[0] * via_step, 6), round(target.y - u[1] * via_step, 6))
                after = Location(round(target.x + u[0] * via_step, 6), round(target.y + u[1] * via_step, 6))
                line = line[:i + 1] + [before, via_at, after] + line[i + 1:]
            extra.append(Via(net, via_at, via_drill, via_size))
            extra += polyline_tracks(net, other, width, _dogleg(pad, via_at))
        ops += polyline_tracks(net, layer, width, line) + extra
    return ops
