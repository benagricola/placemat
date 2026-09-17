"""A board outline of any shape: a closed path of straight legs and arcs,
what it holds, and the runs of it that face a direction.

A placement asks a board three things - what it holds inside its keep-in,
how big it is, and which way its edges point - and every shape answers them
the same way, so a rectangle's side, a rounded top and a disc's rim are one
kind of thing. The declared path is kept for the fab (an arc is written as
an arc) and a flattened copy is kept for the arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .cutouts import NM as _NM, Arc, Where, flatten_path, segment_box as _segment_box, signed_area as _area
from .values import Box, Location, bearing, bearing_of, bearing_vector


@dataclass(frozen=True)
class Run:
    """A stretch of one board edge that faces the same way: a polyline in
    path order, with the bearing its outward side points along. A straight
    side of a rectangle, a rounded top and a quarter of a rim are all runs,
    so one kind of place works along any of them."""
    points: tuple
    facing: float
    closed: bool = False
    _sign: float = 1.0          # the winding of the loop it came off, so its outward side is known

    @property
    def lengths(self) -> tuple:
        return tuple(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in self._legs())

    def _legs(self):
        pts = self.points + (self.points[0],) if self.closed else self.points
        return list(zip(pts, pts[1:]))

    @property
    def length(self) -> float:
        return sum(self.lengths)

    @property
    def straight(self) -> bool:
        legs = self._legs()
        if len(legs) < 2:
            return True
        b0 = bearing_of(legs[0][1][0] - legs[0][0][0], legs[0][1][1] - legs[0][0][1])
        return all(abs(_angle_gap(bearing_of(b[0] - a[0], b[1] - a[1]), b0)) < 1e-6 for a, b in legs)

    def _normals(self) -> list:
        sign = 1.0 if self._sign > 0 else -1.0
        return [bearing_of(*_normal(b[0] - a[0], b[1] - a[1], sign)) for a, b in self._legs()]

    def at(self, along: float) -> tuple:
        """The point `along` mm from the run's start, and the bearing its
        outward side points along there. On a curve the normal is taken from
        the legs either side, so it turns smoothly instead of stepping at
        every chord of the flattened arc."""
        legs, lens, norms = self._legs(), self.lengths, self._normals()
        s = max(0.0, min(float(along), sum(lens)))
        for n, (leg, (a, b)) in enumerate(zip(lens, legs)):
            if leg > 0.0 and (s <= leg or n == len(legs) - 1):
                t = min(1.0, s / leg)
                v0 = norms[n] if n == 0 else norms[n - 1] + _angle_gap(norms[n], norms[n - 1]) / 2.0
                v1 = norms[n] if n + 1 >= len(norms) else norms[n] + _angle_gap(norms[n + 1], norms[n]) / 2.0
                out = (v0 + _angle_gap(v1, v0) * t) % 360.0
                return Location(round(a[0] + (b[0] - a[0]) * t, 6), round(a[1] + (b[1] - a[1]) * t, 6)), out
            s -= leg
        a, b = legs[-1]
        return Location(round(b[0], 6), round(b[1], 6)), self.facing

    def project(self, point: Location) -> float:
        """Where along the run a point is: the arc length of the nearest
        place on it, so a run takes a reference like an edge does."""
        best, best_d, walked = 0.0, float("inf"), 0.0
        for (a, b), leg in zip(self._legs(), self.lengths):
            n = leg * leg
            t = 0.0 if n < 1e-18 else max(0.0, min(1.0, ((point.x - a[0]) * (b[0] - a[0]) + (point.y - a[1]) * (b[1] - a[1])) / n))
            d = math.hypot(point.x - (a[0] + t * (b[0] - a[0])), point.y - (a[1] + t * (b[1] - a[1])))
            if d < best_d:
                best_d, best = d, walked + t * leg
            walked += leg
        return best

    def curvature(self, along: float) -> float:
        """How sharply the run bends where it is `along`: 1/radius, and 0
        where it is straight. What holds neighbours apart on a curve."""
        legs, lens = self._legs(), self.lengths
        if len(legs) < 2:
            return 0.0
        walked, k = 0.0, 0
        for n, leg in enumerate(lens):
            if walked + leg >= along:
                k = n
                break
            walked += leg
        a, b = legs[min(k, len(legs) - 2)], legs[min(k + 1, len(legs) - 1)]
        t1 = bearing_of(a[1][0] - a[0][0], a[1][1] - a[0][1])
        t2 = bearing_of(b[1][0] - b[0][0], b[1][1] - b[0][1])
        turn = abs(_angle_gap(t2, t1))
        span = (lens[min(k, len(lens) - 1)] + lens[min(k + 1, len(lens) - 1)]) / 2.0
        return math.radians(turn) / span if span > 1e-9 else 0.0


def _angle_gap(a: float, b: float) -> float:
    """The signed difference between two bearings, in (-180, 180]."""
    return (a - b + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class Outline:
    """A board of any shape: one closed path, and a path per cutout. The
    declared pieces are kept for the fab; the flattened loops answer every
    question a placement asks."""
    paths: tuple            # as declared: the board's path, then each cutout's
    loops: tuple            # the same, flattened to polylines

    @staticmethod
    def of(path, holes=()) -> "Outline":
        paths = (tuple(path),) + tuple(tuple(h) for h in holes)
        return Outline(paths, tuple(flatten_path(p) for p in paths))

    @property
    def box(self) -> Box:
        xs = [p[0] for p in self.loops[0]]
        ys = [p[1] for p in self.loops[0]]
        return Box(min(xs), min(ys), max(xs), max(ys))

    @property
    def centre(self) -> Location:
        return self.box.center

    @property
    def area(self) -> float:
        return abs(_area(self.loops[0])) - sum(abs(_area(h)) for h in self.loops[1:])

    @property
    def centroid(self) -> Location:
        """The area centre: where the board balances, which is not the middle
        of its box unless it is symmetric."""
        sx = sy = sa = 0.0
        for n, loop in enumerate(self.loops):
            sign = 1.0 if n == 0 else -1.0
            for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]):
                cross = x1 * y2 - x2 * y1
                sa += sign * cross
                sx += sign * (x1 + x2) * cross
                sy += sign * (y1 + y2) * cross
        if abs(sa) < 1e-12:
            return self.centre
        return Location(round(sx / (3.0 * sa), 6), round(sy / (3.0 * sa), 6))

    def _index(self) -> Where:
        """The outline's segments, bucketed by where they lie. A search asks
        the keep-in question tens of thousands of times against a shape that
        never changes, so the buckets are built once and every question after
        that looks at the few segments near the box."""
        got = getattr(self, "_where", None)
        if got is None:
            got = Where(self.loops)
            object.__setattr__(self, "_where", got)
        return got

    def why_not(self, box: Box, margin: float) -> str | None:
        """None when `box` sits inside the board with `margin` to spare
        everywhere, else what it crosses."""
        ix = self._index()
        odd = ix.loops_around((box.left + box.right) / 2.0, (box.top + box.bottom) / 2.0)
        if 0 not in odd:
            return "outside the board"
        if odd - {0}:
            return "inside a cutout"
        left, top = box.left - margin, box.top - margin
        right, bottom = box.right + margin, box.bottom + margin
        for x1, y1, x2, y2, n, lo_x, lo_y, hi_x, hi_y in ix.near(left, top, right, bottom):
            if hi_x < left or lo_x > right or hi_y < top or lo_y > bottom:
                continue                    # too far to matter
            if _segment_box(x1, y1, x2, y2, box) < margin - _NM:
                return "past the %s keep-in (%.2f mm)" % ("board's" if n == 0 else "cutout's", margin)
        return None

    def polygon(self, inset: float = 0.0) -> tuple:
        """The board's own outline, pulled in by `inset`: what a plane is
        given. Each vertex moves along the bisector of its two legs, which
        is exact where the outline turns outward and clamped where it turns
        back on itself."""
        loop = self.loops[0]
        if inset <= 0.0:
            return tuple(loop)
        sign = 1.0 if _area(loop) > 0 else -1.0
        out = []
        n = len(loop)
        for i, (x, y) in enumerate(loop):
            ax, ay = loop[i - 1]
            bx, by = loop[(i + 1) % n]
            n1 = _normal(x - ax, y - ay, sign)
            n2 = _normal(bx - x, by - y, sign)
            mx, my = n1[0] + n2[0], n1[1] + n2[1]
            m = math.hypot(mx, my)
            if m < 1e-9:
                mx, my, m = n1[0], n1[1], 1.0
            cos_half = max(0.35, m / 2.0)       # a sharp corner would run away: clamp it
            out.append((round(x - mx / m * inset / cos_half, 6), round(y - my / m * inset / cos_half, 6)))
        return tuple(out)

    def runs(self, facing, within: float = 45.0, loop: int = 0) -> list:
        """The stretches of one of this outline's loops whose outward side
        points within `within` degrees of `facing`, in path order.

        `loop=0` is the board: a rectangle's north side is one, a rounded top
        is one, a rim gives the arc facing that way. `loop=n` is the n-th
        cutout, walked so its normals point INTO the hole - the way an item
        placed against it faces, and the direction run_placement walks back
        from."""
        if not 0 <= loop < len(self.loops):
            raise ValueError("this board has %d cutout(s); there is no loop %d"
                             % (len(self.loops) - 1, loop))
        want = bearing(facing)
        ring = self.loops[loop]
        sign = 1.0 if _area(ring) > 0 else -1.0
        if loop:
            sign = -sign            # a hole's material is outside it, so its outward side points in
        legs = list(zip(ring, ring[1:] + ring[:1]))
        keep = []
        for (a, b) in legs:
            nx, ny = _normal(b[0] - a[0], b[1] - a[1], sign)
            keep.append(abs(_angle_gap(bearing_of(nx, ny), want)) <= within + 1e-9)
        if not any(keep):
            return []
        if all(keep):
            pts = tuple(p for p, _ in legs)
            return [Run(pts, want, closed=True, _sign=sign)]
        start = next(i for i in range(len(legs)) if keep[i] and not keep[i - 1])
        runs, current = [], []
        for k in range(len(legs)):
            i = (start + k) % len(legs)
            if keep[i]:
                if not current:
                    current = [legs[i][0]]
                current.append(legs[i][1])
            elif current:
                runs.append(_run_of(current, sign))
                current = []
        if current:
            runs.append(_run_of(current, sign))
        return runs


def _normal(dx: float, dy: float, sign: float) -> tuple:
    """The outward normal of a leg going (dx, dy) on a loop of that winding."""
    b = bearing_of(dx, dy) - 90.0 * sign
    return bearing_vector(b)


def _run_of(points, sign: float) -> Run:
    legs = list(zip(points, points[1:]))
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in legs) or 1.0
    x = y = 0.0
    for a, b in legs:
        nx, ny = _normal(b[0] - a[0], b[1] - a[1], sign)
        w = math.hypot(b[0] - a[0], b[1] - a[1]) / total
        x, y = x + nx * w, y + ny * w
    return Run(tuple(points), round(bearing_of(x, y), 6) % 360.0, _sign=sign)


def rect_outline(box: Box, chamfer: float = 0.0, radius: float = 0.0) -> Outline:
    """A rectangle as an outline, so a plain board answers the same questions
    a shaped one does. Its chamfers and rounds are kept."""
    l, t, r, b = box.left, box.top, box.right, box.bottom
    if radius > 0:
        k = radius
        return Outline.of([(l + k, t), (r - k, t), Arc((r, t + k), via=(r - k + k * 0.2929, t + k - k * 0.7071)),
                           (r, b - k), Arc((r - k, b), via=(r - k + k * 0.7071, b - k + k * 0.7071)),
                           (l + k, b), Arc((l, b - k), via=(l + k - k * 0.7071, b - k + k * 0.7071)),
                           (l, t + k), Arc((l + k, t), via=(l + k - k * 0.7071, t + k - k * 0.7071))])
    if chamfer > 0:
        c = chamfer
        return Outline.of([(l + c, t), (r - c, t), (r, t + c), (r, b - c), (r - c, b), (l + c, b), (l, b - c), (l, t + c)])
    return Outline.of([(l, t), (r, t), (r, b), (l, b)])
