"""Plans copper. The concrete shapes the writer draws (Track, Via, Pour,
Zone), the Lane a script declares bus copper on, the planner that turns lane
declarations into tracks and vias once the pads are placed, and the finger
pour that steps round lanes."""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from .geometry import Polygon
from .values import Box, CopperLayer, Location, Net, X, Y

# A far-layer bridge round a crossed lane: via land (0.30) + clearance (0.20)
# + lane half-width (0.15) + margin (0.45) each side of the crossed lane.
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


# ------------------------------------------------------------------ lanes
@dataclass
class Lane:
    """A lane is a straight line on one layer, in any direction, that one
    net's tracks run along: a bus bar drawn as tracks. It is defined by a
    point it passes through and a direction; positions along it are
    distances from that point. Its tracks and vias are planned after
    placement; the methods only record what the lane does. The lane words:

    run       a track along the lane between two positions
    tap       a track from the lane to a pad, perpendicular to the lane
    hop       tap out of one pad, run, tap into the next
    chain     one net over many pads: tap, run, tap, run, ... each pad once
    crossing  a track from a position on this lane to another lane
    """
    net: str
    origin: Location
    direction: tuple[float, float]      # unit vector
    layer: CopperLayer
    width: float
    board: object = field(repr=False)
    ops: list = field(default_factory=list)
    priority: object = None

    @property
    def normal(self) -> tuple[float, float]:
        return (-self.direction[1], self.direction[0])

    def at(self, s: float) -> Location:
        """The point `s` mm along the lane from its origin."""
        return Location(round(self.origin.x + s * self.direction[0], 6), round(self.origin.y + s * self.direction[1], 6))

    def along(self, p: Location) -> float:
        """The position along the lane of the foot of the perpendicular from `p`."""
        return (p.x - self.origin.x) * self.direction[0] + (p.y - self.origin.y) * self.direction[1]

    def _add(self, kind, **kw):
        self.ops.append((kind, kw))
        return self

    def run(self, a, b):
        """A track along the lane between two positions (a distance along the
        lane, or a point/pad whose projection onto the lane is meant)."""
        return self._add("run", a=a, b=b)

    def tap(self, pad):
        """A track from the lane to the pad, perpendicular to the lane, bridged
        under any same-layer lane between them."""
        return self._add("tap", pad=pad)

    def hop(self, pad_from, pad_to):
        """Tap out of one pad, run the lane to the other pad, tap into it."""
        return self._add("hop", pad_from=pad_from, pad_to=pad_to)

    def chain(self, pads):
        """Tap the first pad, then run and tap to each following pad in turn;
        every pad is tapped exactly once."""
        return self._add("chain", pads=list(pads))

    def run_to(self, a, pad, tap: bool = True):
        """Run the lane from a position to a pad's position, then tap the pad
        (tap=False when the pad is tapped by a following chain)."""
        return self._add("run_to", a=a, pad=pad, tap=tap)

    def cross_to(self, other: "Lane", at, from_=None, to=None):
        """A crossing: a track from the position `at` on this lane to the
        nearest point of `other`, bridged under any same-layer lane it passes.
        `from_` adds a run along this lane to the crossing; `to` adds a run
        along `other` from the crossing onward. Positions are distances along
        the lane, or points/pads whose projection is meant."""
        return self._add("cross", other=other, at=at, from_=from_, to=to)


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


class LanePlanner:
    """Turns lane declarations into tracks and vias, given resolved pad
    locations. Every lane's extent (the segment its copper occupies) is
    computed first so a tap or crossing knows which lanes it passes."""

    def __init__(self, lanes: list[Lane], ctx, via_drill: float, via_size: float,
                 bridge_half: float = BRIDGE_HALF):
        self.lanes = lanes
        self.locate = ctx.locate
        self.coord = ctx.coord
        self.via_drill, self.via_size = via_drill, via_size
        self.bridge_half = bridge_half
        self.extents: dict[int, tuple[float, float]] = {}

    def _pos(self, lane: Lane, v) -> float:
        """A position along `lane`: a number as given; an X()/Y() as the point
        with that coordinate on the line through the lane's origin, projected;
        else the projection of a point or pad."""
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, X):
            return lane.along(Location(self.coord(v, "x"), lane.origin.y))
        if isinstance(v, Y):
            return lane.along(Location(lane.origin.x, self.coord(v, "y")))
        return lane.along(self.locate(v))

    def compute_extents(self) -> dict:
        """Every lane's along-range, counting a crossing's far-side run toward
        the lane it runs along."""
        ss: dict[int, list] = {id(l): [] for l in self.lanes}
        for lane in self.lanes:
            for kind, kw in lane.ops:
                if kind == "run":
                    ss[id(lane)] += [self._pos(lane, kw["a"]), self._pos(lane, kw["b"])]
                elif kind == "tap":
                    ss[id(lane)].append(self._pos(lane, kw["pad"]))
                elif kind == "hop":
                    ss[id(lane)] += [self._pos(lane, kw["pad_from"]), self._pos(lane, kw["pad_to"])]
                elif kind == "chain":
                    ss[id(lane)] += [self._pos(lane, p) for p in kw["pads"]]
                elif kind == "run_to":
                    ss[id(lane)] += [self._pos(lane, kw["a"]), self._pos(lane, kw["pad"])]
                elif kind == "cross":
                    other = kw["other"]
                    here = lane.at(self._pos(lane, kw["at"]))
                    ss[id(lane)].append(self._pos(lane, kw["at"]))
                    if kw["from_"] is not None:
                        ss[id(lane)].append(self._pos(lane, kw["from_"]))
                    ss.setdefault(id(other), []).append(other.along(here))
                    if kw["to"] is not None:
                        ss[id(other)].append(self._pos(other, kw["to"]))
        self.extents = {k: (min(v), max(v)) for k, v in ss.items() if v}
        return self.extents

    def extent_segment(self, lane: Lane):
        ext = self.extents.get(id(lane))
        if ext is None:
            return None
        return (tuple(lane.at(ext[0])), tuple(lane.at(ext[1])))

    def crossings_on(self, lane: Lane, p_from: Location, p_to: Location) -> list:
        """Where the segment p_from-p_to crosses the copper of another lane on
        the same layer, ordered from p_from."""
        hits = []
        for other in self.lanes:
            if other is lane or other.layer is not lane.layer or other.net == lane.net:
                continue
            seg = self.extent_segment(other)
            if seg is None:
                continue
            pt = _seg_intersection((p_from.x, p_from.y), (p_to.x, p_to.y), seg[0], seg[1])
            if pt is not None:
                hits.append((math.hypot(pt[0] - p_from.x, pt[1] - p_from.y), (round(pt[0], 6), round(pt[1], 6))))
        hits.sort()
        out = []
        for d, pt in hits:
            if not out or abs(d - out[-1][0]) > 1e-6:
                out.append((d, pt))
        return [pt for _, pt in out]

    def bridged(self, lane: Lane, p_from: Location, p_to: Location) -> list:
        """A straight track from p_from to p_to on the lane's layer, bridged
        under every same-layer lane it crosses: a via, a track on the
        opposite face, and a via back, `bridge_half` either side of the
        crossing point."""
        ops = []
        length = p_from.distance(p_to)
        if length < 1e-9:
            return ops
        ux, uy = (p_to.x - p_from.x) / length, (p_to.y - p_from.y) / length
        h = self.bridge_half
        cur = p_from
        for cx, cy in self.crossings_on(lane, p_from, p_to):
            near = Location(round(cx - ux * h, 6), round(cy - uy * h, 6))
            far = Location(round(cx + ux * h, 6), round(cy + uy * h, 6))
            ops += polyline_tracks(lane.net, lane.layer, lane.width, [cur, near])
            ops.append(Via(lane.net, near, self.via_drill, self.via_size))
            ops.append(Via(lane.net, far, self.via_drill, self.via_size))
            ops += polyline_tracks(lane.net, lane.layer.other_face, lane.width, [near, far])
            cur = far
        ops += polyline_tracks(lane.net, lane.layer, lane.width, [cur, p_to])
        return ops

    def _tap(self, lane: Lane, pad_ref) -> list:
        p = self.locate(pad_ref)
        return self.bridged(lane, lane.at(lane.along(p)), p)

    def _run(self, lane: Lane, a, b) -> list:
        return polyline_tracks(lane.net, lane.layer, lane.width, [lane.at(self._pos(lane, a)), lane.at(self._pos(lane, b))])

    def plan(self) -> list:
        self.compute_extents()
        ops = []
        for lane in self.lanes:
            for kind, kw in lane.ops:
                if kind == "run":
                    ops += self._run(lane, kw["a"], kw["b"])
                elif kind == "tap":
                    ops += self._tap(lane, kw["pad"])
                elif kind == "hop":
                    a, b = kw["pad_from"], kw["pad_to"]
                    ops += self._tap(lane, a) + self._run(lane, a, b) + self._tap(lane, b)
                elif kind == "chain":
                    pads = kw["pads"]
                    ops += self._tap(lane, pads[0])
                    for prev, nxt in zip(pads, pads[1:]):
                        ops += self._run(lane, prev, nxt) + self._tap(lane, nxt)
                elif kind == "run_to":
                    ops += self._run(lane, kw["a"], kw["pad"])
                    if kw.get("tap", True):
                        ops += self._tap(lane, kw["pad"])
                elif kind == "cross":
                    other = kw["other"]
                    here = lane.at(self._pos(lane, kw["at"]))
                    there = other.at(other.along(here))
                    if kw["from_"] is not None:
                        ops += self._run(lane, kw["from_"], kw["at"])
                    ops += self.bridged(lane, here, there)
                    if kw["to"] is not None:
                        ops += polyline_tracks(lane.net, other.layer, other.width, [there, other.at(self._pos(other, kw["to"]))])
        return ops


def finger_ops(net: str, layer: CopperLayer, a: Location, b: Location, width: float, lane_segments,
               via_drill: float, via_size: float, bridge_width: float = 1.0,
               notch_half: float = BRIDGE_HALF) -> list:
    """A finger: a rectangular pour of `width` along the centreline a-b (a
    wide copper reach from a spine to a pad). Where a same-layer lane in
    `lane_segments` crosses the centreline the rectangle is cut into pieces
    either side of the lane, and each cut is bridged: a via, a track on the
    opposite face under the lane, and a via, so the pieces stay one net."""
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
