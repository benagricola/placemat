"""The pin map study's airwire model, as pure geometry (millimetres, y down, KiCad's turn: counter-clockwise on screen):
the twin of native/src/pinmap_geom.rs, which the native core uses. The model is placemat's own, not KiCad's.

A studied part's body is its courtyard's box. A pin's airwire leaves along the pin's outward normal - the side of the box
it is nearest - to its exit point, `margin` past the box, then takes the shorter way round the box grown by `margin` to
its target, corner to corner, until the target is in sight. A target inside the body's box (a part under it, on the
other face) is reached straight. The bend at a pin is the angle between its outward normal and the bearing from its exit
point to its target: 0 facing it, 180 turning back.

The part's own frame is the board's moved to the courtyard box's centre, as the part stands; a `Pose` turns it about that
centre (and mirrors it left to right first, for the other face) to ask where the pads would be at another rotation.

Every value is the native model's to the last bit: `_clean` is `geometry._clean` (`exact::clean9`), `math.hypot` is
CPython's (`exact::hypot`), angles go through `math.radians` and `math.degrees`, and sums are plain, in order."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .geometry import _clean

_EPS = 1e-9
_SIDES = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))     # east, south, west, north: the order a tie is broken in


@dataclass(frozen=True)
class Pose:
    """A studied part's body turned `turn` degrees about (cx, cy), mirrored left to right first when `flip`."""
    cx: float
    cy: float
    turn: float = 0.0
    flip: bool = False

    def _cs(self):
        r = math.radians(self.turn)
        return math.cos(r), math.sin(r)

    def vector(self, x: float, y: float) -> tuple:
        """A direction in the part's own frame, in the board's."""
        if self.flip:
            x = -x
        c, s = self._cs()
        return (_clean(c * x + s * y), _clean(-s * x + c * y))

    def to_board(self, x: float, y: float) -> tuple:
        vx, vy = self.vector(x, y)
        return (_clean(self.cx + vx), _clean(self.cy + vy))

    def to_local(self, x: float, y: float) -> tuple:
        """A board point in the part's own frame, not rounded."""
        dx, dy = x - self.cx, y - self.cy
        c, s = self._cs()
        lx, ly = c * dx - s * dy, s * dx + c * dy
        return (-lx if self.flip else lx, ly)


@dataclass(frozen=True)
class Exit:
    """Where a studied pin's airwire leaves its part: `at` in the board's frame, `local` in the part's, `normal` (the
    board's frame) and `side` (0 east, 1 south, 2 west, 3 north) of the box it leaves by, and the body it goes round."""
    ref: str
    at: tuple
    local: tuple
    normal: tuple
    side: int
    pose: Pose
    hw: float
    hh: float
    margin: float


def exit_of(ref: str, pose: Pose, x: float, y: float, normal: tuple, hw: float, hh: float, margin: float) -> Exit:
    """The exit of a pin at (x, y) in the part's frame with outward `normal` (its frame, one of the four axes), at
    `pose`."""
    side = _SIDES.index(tuple(normal))
    lx, ly = ((hw + margin, y), (x, hh + margin), (-hw - margin, y), (x, -hh - margin))[side]
    return Exit(ref, pose.to_board(lx, ly), (lx, ly), pose.vector(*normal), side, pose, hw, hh, margin)


def through(p: tuple, q: tuple, hw: float, hh: float) -> bool:
    """Whether segment p-q passes through the inside of the box (-hw, -hh)-(hw, hh); along its edge or touching a corner
    is not through."""
    x0, y0 = p
    dx, dy = q[0] - x0, q[1] - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 + hw), (dx, hw - x0), (-dy, y0 + hh), (dy, hh - y0)):
        if abs(pp) < 1e-15:
            if qq <= _EPS:
                return False
            continue
        r = qq / pp
        if pp < 0:
            if r > t0:
                t0 = r
        elif r < t1:
            t1 = r
        if t1 - t0 <= _EPS:
            return False
    mx = x0 + dx * (t0 + t1) / 2.0
    my = y0 + dy * (t0 + t1) / 2.0
    return -hw + _EPS < mx < hw - _EPS and -hh + _EPS < my < hh - _EPS


def length(points) -> float:
    """A path's length, segment by segment in order."""
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total


_CORNER_AFTER = (1, 2, 3, 0)          # the corner reached first going clockwise from side k


def round_body(e: Exit, target: tuple) -> list:
    """The way from exit `e` to `target` (board frame) round e's body: [e.at, corners..., target], board frame."""
    t = e.pose.to_local(*target)
    hw, hh = e.hw, e.hh
    if (-hw < t[0] < hw and -hh < t[1] < hh) or not through(e.local, t, hw, hh):
        return [e.at, target]
    w, h = hw + e.margin, hh + e.margin
    corners = ((w, -h), (w, h), (-w, h), (-w, -h))         # north-east, south-east, south-west, north-west
    best = None
    for step in (1, -1):
        k = _CORNER_AFTER[e.side] if step == 1 else (_CORNER_AFTER[e.side] + 3) % 4
        local = [e.local]
        for _ in range(4):
            c = corners[k]
            local.append(c)
            if not through(c, t, hw, hh):
                break
            k = (k + step + 4) % 4
        local.append(t)
        n = length(local)
        if best is None or n < best[0] - _EPS:
            best = (n, local)
    return [e.at] + [e.pose.to_board(*c) for c in best[1][1:-1]] + [target]


def route(a, b) -> tuple:
    """An airwire's path from `a` to `b`, each an Exit (a studied pin) or a point: round the body of each end that is
    an Exit, the second end's from the last turn the first one's path makes."""
    pa = a.at if isinstance(a, Exit) else a
    pb = b.at if isinstance(b, Exit) else b
    pts = round_body(a, pb) if isinstance(a, Exit) else [pa, pb]
    if isinstance(b, Exit):
        back = round_body(b, pts[-2])
        pts = pts[:-1] + list(reversed(back))[1:]
    return tuple(tuple(p) for p in pts)


def bend(normal: tuple, at: tuple, target: tuple) -> float:
    """Degrees between a pin's outward `normal` and the bearing from its exit point `at` to `target`."""
    dx, dy = target[0] - at[0], target[1] - at[1]
    d = math.hypot(dx, dy)
    if d <= _EPS:
        return 0.0
    cos = (normal[0] * dx + normal[1] * dy) / d
    cos = -1.0 if cos < -1.0 else 1.0 if cos > 1.0 else cos         # f64::clamp: a NaN stays a NaN
    return math.degrees(math.acos(cos))
