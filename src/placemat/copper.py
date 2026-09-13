"""Plans copper. The concrete shapes the writer draws (Track, Via, Pour,
Zone), the Lane a script declares bus copper on, the planner that turns lane
declarations into tracks and vias once the pads are placed, and the finger
pour that steps round lanes."""
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
