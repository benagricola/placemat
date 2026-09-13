"""Copper: what a script declares (against pads and lanes) and what the writer
draws (concrete tracks, vias, pours and zones in board mm).

A declaration is planned only after placement, against where the pads
landed. Lanes are the bus vocabulary: a run at a fixed x on one layer, taps
into pads at the pad's own y, hops pad to pad, a chain over many pads, and a
crossing from one lane to another at a fixed y. Where a tap or crossing
would pass another lane on the same layer it hops to the far layer round
it. The lanes it must hop are found from the lanes the script registered,
never typed by hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from .geometry import Polygon
from .values import Box, CopperLayer, Location, Net

# A far-layer bridge round a crossed lane: via land (0.30) + clearance (0.20)
# + lane half-width (0.15) + margin (0.45) each side of the crossed lane.
BRIDGE_HALF = 1.1


# ------------------------------------------------------------------ concrete ops
@dataclass(frozen=True)
class Track:
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
    """A bus lane: `net` runs at `x` on `layer`. Its copper is emitted by the
    board's copper planning; the methods only record what the lane does."""
    net: str
    x: float
    layer: CopperLayer
    width: float
    board: object = field(repr=False)
    ops: list = field(default_factory=list)
    priority: object = None

    def _add(self, kind, **kw):
        self.ops.append((kind, kw))
        return self

    def run(self, y1: float, y2: float):
        """Straight copper down the lane between two y values."""
        return self._add("run", y1=y1, y2=y2)

    def tap(self, pad):
        """Lane -> pad at the pad's own y (via-hopping any same-layer lane between)."""
        return self._add("tap", pad=pad)

    def hop(self, pad_from, pad_to):
        """Tap out of one pad, run the lane, tap into the next."""
        return self._add("hop", pad_from=pad_from, pad_to=pad_to)

    def chain(self, pads):
        """One continuous net over many pads: each pad tapped exactly once."""
        return self._add("chain", pads=list(pads))

    def run_to(self, y_from, pad):
        """Run the lane from a y (or a pad's y) to a pad's y, then tap it."""
        return self._add("run_to", y_from=y_from, pad=pad)

    def cross_to(self, other: "Lane", y: float, from_y=None, to_y=None):
        """Jump to `other` (the lane bank on the far side) along y=`y`,
        bridging any same-layer lane the horizontal passes. `from_y`/`to_y`
        extend this lane down to the crossing and the other lane onward."""
        return self._add("cross", other=other, y=y, from_y=from_y, to_y=to_y)


class LanePlanner:
    """Turns lane declarations into ops, given resolved pad locations and the
    set of every lane's y-extent (so a tap knows which lanes it crosses)."""

    def __init__(self, lanes: list[Lane], locate, via_drill: float, via_size: float,
                 bridge_half: float = BRIDGE_HALF):
        self.lanes = lanes
        self.locate = locate
        self.via_drill, self.via_size = via_drill, via_size
        self.bridge_half = bridge_half
        self.extents: dict[int, tuple[float, float]] = {}

    def _pad_y(self, ref) -> float:
        return self.locate(ref).y

    def _extent(self, lane: Lane) -> tuple[float, float] | None:
        ys = []
        for kind, kw in lane.ops:
            if kind == "run":
                ys += [kw["y1"], kw["y2"]]
            elif kind == "tap":
                ys.append(self._pad_y(kw["pad"]))
            elif kind == "hop":
                ys += [self._pad_y(kw["pad_from"]), self._pad_y(kw["pad_to"])]
            elif kind == "chain":
                ys += [self._pad_y(p) for p in kw["pads"]]
            elif kind == "run_to":
                y0 = kw["y_from"] if isinstance(kw["y_from"], (int, float)) else self._pad_y(kw["y_from"])
                ys += [y0, self._pad_y(kw["pad"])]
            elif kind == "cross":
                ys.append(kw["y"])
                if kw["from_y"] is not None:
                    ys.append(kw["from_y"])
        return (min(ys), max(ys)) if ys else None

    def crossed_lanes(self, lane: Lane, x_from: float, x_to: float, y: float) -> list[float]:
        """x of every OTHER same-layer lane between x_from and x_to whose
        copper is present at y."""
        lo, hi = min(x_from, x_to), max(x_from, x_to)
        xs = []
        for other in self.lanes:
            if other is lane or other.layer is not lane.layer or other.net == lane.net:
                continue
            ext = self.extents.get(id(other))
            if ext is None or not (lo < other.x < hi):
                continue
            if ext[0] - 1e-9 <= y <= ext[1] + 1e-9:
                xs.append(other.x)
        return sorted(xs)

    def _horizontal(self, lane: Lane, x_from: float, x_to: float, y: float) -> list:
        """A horizontal run on the lane's layer, via-bridged round crossed lanes."""
        ops = []
        crossings = self.crossed_lanes(lane, x_from, x_to, y)
        going_pos = x_to > x_from
        bridge = lane.layer.other_face
        cur = x_from
        h = self.bridge_half
        for cx in (crossings if going_pos else reversed(crossings)):
            near, far = (cx - h, cx + h) if going_pos else (cx + h, cx - h)
            ops += polyline_tracks(lane.net, lane.layer, lane.width, [(cur, y), (near, y)])
            ops.append(Via(lane.net, Location(near, y), self.via_drill, self.via_size))
            ops.append(Via(lane.net, Location(far, y), self.via_drill, self.via_size))
            ops += polyline_tracks(lane.net, bridge, lane.width, [(near, y), (far, y)])
            cur = far
        ops += polyline_tracks(lane.net, lane.layer, lane.width, [(cur, y), (x_to, y)])
        return ops

    def _tap(self, lane: Lane, pad_ref) -> list:
        p = self.locate(pad_ref)
        return self._horizontal(lane, lane.x, p.x, p.y)

    def _run(self, lane: Lane, y1: float, y2: float) -> list:
        return polyline_tracks(lane.net, lane.layer, lane.width, [(lane.x, y1), (lane.x, y2)])

    def plan(self) -> list:
        for lane in self.lanes:
            ext = self._extent(lane)
            if ext:
                self.extents[id(lane)] = ext
        ops = []
        for lane in self.lanes:
            for kind, kw in lane.ops:
                if kind == "run":
                    ops += self._run(lane, kw["y1"], kw["y2"])
                elif kind == "tap":
                    ops += self._tap(lane, kw["pad"])
                elif kind == "hop":
                    a, b = kw["pad_from"], kw["pad_to"]
                    ops += self._tap(lane, a) + self._run(lane, self._pad_y(a), self._pad_y(b)) + self._tap(lane, b)
                elif kind == "chain":
                    pads = kw["pads"]
                    ops += self._tap(lane, pads[0])
                    for prev, nxt in zip(pads, pads[1:]):
                        ops += self._run(lane, self._pad_y(prev), self._pad_y(nxt)) + self._tap(lane, nxt)
                elif kind == "run_to":
                    y0 = kw["y_from"] if isinstance(kw["y_from"], (int, float)) else self._pad_y(kw["y_from"])
                    ops += self._run(lane, y0, self._pad_y(kw["pad"])) + self._tap(lane, kw["pad"])
                elif kind == "cross":
                    other, y = kw["other"], kw["y"]
                    if kw["from_y"] is not None:
                        ops += self._run(lane, kw["from_y"], y)
                    ops += self._horizontal(lane, lane.x, other.x, y)
                    if kw["to_y"] is not None:
                        ops += polyline_tracks(lane.net, other.layer, other.width, [(other.x, y), (other.x, kw["to_y"])])
        return ops


def finger_ops(net: str, layer: CopperLayer, y_lo: float, y_hi: float, x_from: float, x_to: float,
               lane_xs, via_drill: float, via_size: float, bridge_width: float = 1.0,
               notch_half: float = BRIDGE_HALF) -> list:
    """A finger pour from x_from to x_to between y_lo and y_hi, notched round
    each same-layer lane in `lane_xs` and bridged on the far layer so the
    segments stay one net."""
    x0, x1 = (x_from, x_to) if x_to >= x_from else (x_to, x_from)
    bounds = [x0]
    notches = []
    for nx in sorted(lane_xs):
        if x0 < nx < x1:
            bounds += [nx - notch_half, nx + notch_half]
            notches.append(nx)
    bounds.append(x1)
    ops = []
    for i in range(0, len(bounds), 2):
        xa, xb = bounds[i], bounds[i + 1]
        if xb > xa + 0.05:
            ops.append(Pour(net, layer, ((xa, y_lo), (xb, y_lo), (xb, y_hi), (xa, y_hi))))
    mid_y = (y_lo + y_hi) / 2.0
    for nx in notches:
        ops.append(Via(net, Location(nx - notch_half, mid_y), via_drill, via_size))
        ops.append(Via(net, Location(nx + notch_half, mid_y), via_drill, via_size))
        ops += polyline_tracks(net, layer.other_face, bridge_width, [(nx - notch_half, mid_y), (nx + notch_half, mid_y)])
    return ops


def board_zone_outline(width: float, height: float, inset: float, chamfer: float = 0.0) -> tuple:
    W, H, ch, i = width, height, chamfer, inset
    if ch:
        return ((ch + i, i), (W - ch - i, i), (W - i, ch + i), (W - i, H - ch - i),
                (W - ch - i, H - i), (ch + i, H - i), (i, H - ch - i), (i, ch + i))
    return ((i, i), (W - i, i), (W - i, H - i), (i, H - i))
