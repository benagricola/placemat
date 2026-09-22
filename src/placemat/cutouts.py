"""Closed paths of straight legs and arcs, and the holes a board has in it.

A cutout is the same thing whatever it is cut in: a slot for a cable, a
window for a display, the bore of a disc. The path is kept as declared so
the fab gets real arcs, and a flattened copy answers the questions a
placement asks - is this box inside the hole, and is it clear of the hole's
keep-in.

Nothing here knows about placemat's own types. A point is anything with
`.x` and `.y` or an (x, y) pair, and a box is anything with `.left`,
`.top`, `.right` and `.bottom`, so the module sits under both `outline`
(which builds boards out of paths) and `values` (where a Disc lives), and
neither has to import the other.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

NM = 1e-5           # ten KiCad units: the placement grid's own rounding, not an allowance
SAG = 0.02          # how far a flattened arc may cut the corner off the real one; [geometry] arc_sag
CELLS = 16          # buckets across the longer side: a handful of segments each; [geometry] index_cells


@dataclass(frozen=True)
class Arc:
    """A curved leg of a path: it ends at `to` and passes through `via`.
    Three points fix a circle and the way round it, so nothing is implied
    and no flag decides which way it bulges."""
    to: tuple
    via: tuple


def point(v) -> tuple:
    """A declared path point as a pair, whether it came as one or as
    something with x and y."""
    if hasattr(v, "x") and hasattr(v, "y"):
        return (float(v.x), float(v.y))
    if isinstance(v, (tuple, list)) and len(v) == 2:
        return (float(v[0]), float(v[1]))
    raise TypeError("a path point is an (x, y) pair or a Location, not %r" % (v,))


def circle_through(a: tuple, b: tuple, c: tuple):
    """The centre and radius of the circle through three points, or None
    when they are in a line."""
    (ax, ay), (bx, by), (cx, cy) = a, b, c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def flatten_arc(start: tuple, arc: Arc, sag: float | None = None) -> list:
    """The arc as a polyline, ending at its own end point: enough segments
    that none cuts more than `sag` off the true curve."""
    if sag is None:
        from .settings import active
        sag = active().geometry_arc_sag
    end, via = point(arc.to), point(arc.via)
    found = circle_through(start, via, end)
    if found is None:
        return [end]                            # three points in a line: it is a straight leg
    (cx, cy), r = found
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    av = math.atan2(via[1] - cy, via[0] - cx)

    def sweep(to, direction):
        d = (to - a0) * direction
        return d % (2.0 * math.pi)
    # the way round that passes through `via`: the one whose sweep reaches it first
    direction = 1.0 if sweep(av, 1.0) < sweep(a1, 1.0) else -1.0
    total = sweep(a1, direction)
    step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - min(sag, r) / r))) if r > sag else math.pi / 8.0
    n = max(2, int(math.ceil(total / max(step, 1e-6))))
    out = []
    for i in range(1, n + 1):
        a = a0 + direction * total * i / n
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    out[-1] = end
    return out


def flatten_path(path) -> tuple:
    """A declared path as a closed polyline. The first element is the start
    point; each one after it is a point (a straight leg) or an Arc."""
    if len(path) < 3:
        raise ValueError("a closed path needs at least three points")
    start = point(path[0])
    pts = [start]
    for piece in path[1:]:
        if isinstance(piece, Arc):
            pts.extend(flatten_arc(pts[-1], piece))
        else:
            pts.append(point(piece))
    if math.hypot(pts[-1][0] - start[0], pts[-1][1] - start[1]) < NM:
        pts.pop()                               # the close is implied, never doubled
    return tuple(pts)


def closes_itself(path) -> bool:
    """Whether the path's last piece already lands on its start point, so
    drawing a leg back to the start would be a leg of nothing. A circle of
    arcs and a rounded slot both do; a rectangle's four corners do not."""
    last = path[-1]
    end = point(last.to if isinstance(last, Arc) else last)
    start = point(path[0])
    return math.hypot(end[0] - start[0], end[1] - start[1]) < NM


def _turned(points, centre, bearing: float) -> list:
    """`points`, about the origin, turned by a bearing and moved to `centre`.
    A bearing is degrees clockwise from the top, so a shape turns the way
    everything else in placemat does."""
    cx, cy = point(centre)
    r = math.radians(bearing)
    cos_r, sin_r = math.cos(r), math.sin(r)

    def at(p):
        x, y = p
        return (round(cx + x * cos_r - y * sin_r, 6), round(cy + x * sin_r + y * cos_r, 6))

    out = []
    for piece in points:
        out.append(Arc(to=at(piece.to), via=at(piece.via)) if isinstance(piece, Arc) else at(piece))
    return out


def _circle_local(r: float) -> list:
    k = r * math.sqrt(0.5)
    return [(0.0, -r), Arc(to=(r, 0.0), via=(k, -k)), Arc(to=(0.0, r), via=(k, k)),
            Arc(to=(-r, 0.0), via=(-k, k)), Arc(to=(0.0, -r), via=(-k, -k))]


def _about(local, anchor) -> list:
    """`local`, moved so that `anchor` sits at the origin. With no anchor the
    middle of the shape's box goes there, which is what a shape with no
    feature worth naming wants."""
    if anchor is None:
        lo_x, lo_y, hi_x, hi_y = _box_of(local)
        anchor = ((lo_x + hi_x) / 2.0, (lo_y + hi_y) / 2.0)
    ax, ay = point(anchor)
    return _turned(local, (-ax, -ay), 0.0)


def _box_of(path) -> tuple:
    """The box round a declared path, flattening its arcs so a bulge counts."""
    loop = flatten_path(list(path))
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    return (min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True)
class Slot:
    """A rounded-end slot, `length` measured tip to tip and `width` across.
    It runs along +X until a bearing turns it.

    Tip to tip is what a drawing dimensions and what callipers measure, so a
    12.5 mm cable wants a 13 mm slot, not a 13 mm centre line.

    `anchor` is the point of the shape that lands where it is placed, in the
    shape's own coordinates; None is the middle of its box."""
    length: float
    width: float
    anchor: tuple | None = None
    turns = True                             # a slot has a direction; a circle does not

    def __post_init__(self):
        if self.width <= 0 or self.length <= 0:
            raise ValueError("a slot's length and width are positive, not %r by %r" % (self.length, self.width))
        if self.length < self.width:
            raise ValueError("a slot is at least as long as it is wide: %r tip to tip is less than %r across"
                             % (self.length, self.width))

    @property
    def area(self) -> float:
        r = self.width / 2.0
        return (self.length - self.width) * self.width + math.pi * r * r

    def _local(self) -> list:
        r = self.width / 2.0
        h = max(self.length / 2.0 - r, 0.0)      # half the centre line
        if h < NM:
            return _circle_local(r)              # as wide as it is long: a round hole
        return [(-h, -r), (h, -r), Arc(to=(h, r), via=(h + r, 0.0)),
                (-h, r), Arc(to=(-h, -r), via=(-h - r, 0.0))]

    def path_at(self, centre, rotation: float = 0.0) -> list:
        return _turned(_about(self._local(), self.anchor), centre, float(rotation))

    def box_at(self, centre, rotation: float = 0.0) -> tuple:
        return _box_of(self.path_at(centre, rotation))


@dataclass(frozen=True)
class Circle:
    """A round hole. `anchor` is the point of it that lands where it is
    placed; None is its centre."""
    diameter: float
    anchor: tuple | None = None
    turns = False                            # the same whichever way it is turned

    def __post_init__(self):
        if self.diameter <= 0:
            raise ValueError("a circle's diameter is positive, not %r" % (self.diameter,))

    @property
    def area(self) -> float:
        return math.pi * (self.diameter / 2.0) ** 2

    def path_at(self, centre, rotation: float = 0.0) -> list:
        if abs(float(rotation)) > 1e-9:
            raise ValueError("a circle has no direction: drop the rotation, or use a Slot")
        return _turned(_about(_circle_local(self.diameter / 2.0), self.anchor), centre, 0.0)

    def box_at(self, centre, rotation: float = 0.0) -> tuple:
        return _box_of(self.path_at(centre, rotation))


@dataclass(frozen=True)
class Path:
    """Any closed path, as declared. It is moved so its box centre lands
    where it is placed, so one constant can be cut in two places."""
    points: tuple
    anchor: tuple | None = None
    turns = True

    def __init__(self, points, anchor=None):
        object.__setattr__(self, "points", tuple(points))
        object.__setattr__(self, "anchor", None if anchor is None else point(anchor))
        if len(self.points) < 3:
            raise ValueError("a closed path needs at least three points")

    @property
    def area(self) -> float:
        return abs(signed_area(flatten_path(list(self.points))))

    def _local(self) -> list:
        return list(self.points)

    def path_at(self, centre, rotation: float = 0.0) -> list:
        return _turned(_about(self._local(), self.anchor), centre, float(rotation))

    def box_at(self, centre, rotation: float = 0.0) -> tuple:
        return _box_of(self.path_at(centre, rotation))


def signed_area(loop) -> float:
    """The signed shoelace area. Positive means the loop runs clockwise on
    screen, where y grows downward."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def inside(loop, p) -> bool:
    """Whether a point is inside a loop, by the crossing rule."""
    x, y, hit = p.x, p.y, False
    for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
            hit = not hit
    return hit


def point_segment(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-18 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / n))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _side(ax, ay, bx, by, px, py) -> float:
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def crosses(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
    d1, d2 = _side(cx, cy, dx, dy, ax, ay), _side(cx, cy, dx, dy, bx, by)
    d3, d4 = _side(ax, ay, bx, by, cx, cy), _side(ax, ay, bx, by, dx, dy)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def segment_box(x1, y1, x2, y2, box) -> float:
    """How far a segment is from a box; 0 when it touches or crosses it."""
    if (box.left <= x1 <= box.right and box.top <= y1 <= box.bottom) or \
       (box.left <= x2 <= box.right and box.top <= y2 <= box.bottom):
        return 0.0
    corners = ((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom))
    d = min(point_segment(cx, cy, x1, y1, x2, y2) for cx, cy in corners)
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        d = min(d, point_segment(x1, y1, ax, ay, bx, by), point_segment(x2, y2, ax, ay, bx, by))
        if crosses(x1, y1, x2, y2, ax, ay, bx, by):
            return 0.0
    return d


def loop_gap(a, b) -> float:
    """The shortest distance between two closed loops; 0.0 when they touch
    or cross. Between a cutout and the board that distance is the material
    left between them."""
    best = math.inf
    for (ax, ay), (bx, by) in zip(a, a[1:] + a[:1]):
        for (cx, cy), (dx, dy) in zip(b, b[1:] + b[:1]):
            if crosses(ax, ay, bx, by, cx, cy, dx, dy):
                return 0.0
            best = min(best, point_segment(ax, ay, cx, cy, dx, dy),
                       point_segment(cx, cy, ax, ay, bx, by))
    return 0.0 if best is math.inf else best


class Where:
    """Where a set of loops' segments are, so a box can find the ones near it.

    The segments of every loop, each with its own bounding box, bucketed
    into a grid of square cells; a segment sits in every cell its box
    touches, as its position in the declared order. Two questions are
    answered off it. `near` is the segments a box could be close to.
    `loops_around` is which loops enclose a point, counting crossings along
    the ray east from it, which only visits the cells in that point's row."""
    __slots__ = ("segs", "cells", "side", "x0", "y0", "y1", "nx", "ny")

    def __init__(self, loops):
        segs = []
        for n, loop in enumerate(loops):
            for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]):
                segs.append((x1, y1, x2, y2, n,
                             min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
        self.segs = tuple(segs)
        xs = [p[0] for loop in loops for p in loop]
        ys = [p[1] for loop in loops for p in loop]
        self.x0, self.y0 = min(xs), min(ys)
        w, h = max(xs) - self.x0, max(ys) - self.y0
        from .settings import active
        self.side = max(max(w, h) / active().geometry_index_cells, 1e-6)
        self.nx = int(w / self.side) + 1
        self.ny = int(h / self.side) + 1
        self.y1 = self.y0 + self.ny * self.side
        self.cells = [[] for _ in range(self.nx * self.ny)]
        for i, seg in enumerate(self.segs):
            for cy in range(self._row(seg[6]), self._row(seg[8]) + 1):
                row = cy * self.nx
                for cx in range(self._col(seg[5]), self._col(seg[7]) + 1):
                    self.cells[row + cx].append(i)

    def _col(self, x) -> int:
        c = int((x - self.x0) / self.side)
        return 0 if c < 0 else (self.nx - 1 if c >= self.nx else c)

    def _row(self, y) -> int:
        r = int((y - self.y0) / self.side)
        return 0 if r < 0 else (self.ny - 1 if r >= self.ny else r)

    def near(self, left, top, right, bottom) -> list:
        """Every segment whose cell the box touches, in the order the loops
        and their points were declared, so what is reported about a box past
        two loops at once does not depend on the bucketing."""
        cells, nx, segs = self.cells, self.nx, self.segs
        found = None
        for cy in range(self._row(top), self._row(bottom) + 1):
            row = cy * nx
            for cx in range(self._col(left), self._col(right) + 1):
                here = cells[row + cx]
                if here:
                    if found is None:
                        found = set(here)
                    else:
                        found.update(here)
        if not found:
            return ()
        return [segs[i] for i in sorted(found)]

    def loops_around(self, x: float, y: float) -> set:
        """Which loops enclose the point, by the crossing rule along the ray
        east of it: a segment that crosses that ray has the crossing in this
        row, at or east of the point's own cell, so no other cell can hold
        one."""
        if not (self.y0 <= y <= self.y1):
            return set()                    # no loop reaches this line
        cells, segs = self.cells, self.segs
        hits: dict = {}
        row = self._row(y) * self.nx
        seen = set()
        for cx in range(self._col(x), self.nx):
            for i in cells[row + cx]:
                if i in seen:
                    continue
                seen.add(i)
                x1, y1, x2, y2, n = segs[i][:5]
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                    hits[n] = not hits.get(n, False)
        return {n for n, odd in hits.items() if odd}


class Cutouts:
    """The holes in a board, whatever shape the board is: the declared paths
    for the fab, and the flattened loops the keep-in is measured against.

    A shape that answers `why_not` itself - a disc's rim, an outline's own
    path - asks this for the part of the answer its cutouts own, so a slot
    in a round board and a slot in a shaped one refuse a part in the same
    words."""
    __slots__ = ("paths", "loops", "_where")

    def __init__(self, paths=()):
        self.paths = tuple(tuple(p) for p in paths)
        self.loops = tuple(flatten_path(p) for p in self.paths)
        self._where = None

    def __bool__(self) -> bool:
        return bool(self.paths)

    def __len__(self) -> int:
        return len(self.paths)

    def __eq__(self, other) -> bool:
        return isinstance(other, Cutouts) and self.paths == other.paths

    def __hash__(self) -> int:
        return hash(self.paths)

    def __repr__(self) -> str:
        return "Cutouts(%d)" % len(self.paths)

    @property
    def area(self) -> float:
        """How much board the cutouts take away."""
        return sum(abs(signed_area(loop)) for loop in self.loops)

    def web_against(self, loops) -> tuple:
        """The narrowest material between any cutout and any of `loops` - the
        board's own outline - and which cutout it was measured on. Cutouts
        are measured against each other too. (inf, -1) with nothing to
        measure."""
        best, which = math.inf, -1
        for n, hole in enumerate(self.loops):
            for other in loops:
                gap = loop_gap(hole, other)
                if gap < best:
                    best, which = gap, n
            for m in range(n + 1, len(self.loops)):
                gap = loop_gap(hole, self.loops[m])
                if gap < best:
                    best, which = gap, n
        return best, which

    def _index(self) -> Where:
        """Built once: a search asks the keep-in question tens of thousands
        of times against holes that never move."""
        if self._where is None:
            self._where = Where(self.loops)
        return self._where

    def why_not(self, box, margin: float) -> str | None:
        """None when `box` is clear of every cutout with `margin` to spare,
        else what it is in or too near."""
        if not self.loops:
            return None
        ix = self._index()
        if ix.loops_around((box.left + box.right) / 2.0, (box.top + box.bottom) / 2.0):
            return "inside a cutout"
        left, top = box.left - margin, box.top - margin
        right, bottom = box.right + margin, box.bottom + margin
        for x1, y1, x2, y2, _n, lo_x, lo_y, hi_x, hi_y in ix.near(left, top, right, bottom):
            if hi_x < left or lo_x > right or hi_y < top or lo_y > bottom:
                continue                    # too far to matter
            if segment_box(x1, y1, x2, y2, box) < margin - NM:
                return "past the cutout's keep-in (%.2f mm)" % margin
        return None
