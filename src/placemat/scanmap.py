"""Where a scan's candidates are certain to be refused, worked out without judging them.

A scan that finds nothing legal walks its whole grid, and most of what it judges is refused by a shape of the item
lying across a shape of the board. This reads those overlaps off the shapes instead of off every candidate: for a
pair of an item's shape and an obstacle that conflict whenever the two overlap by a given depth, the candidates that
put the two at least that deep into each other form a rectangle of the scan's grid, and every grid point in it is
refused. The map is conservative: it names a candidate only where the conflict rule itself, asked of that pair,
says so, so a candidate the map names is one the judge refuses, and the judge still sees every other.

A shape is taken as its core, the largest axis-aligned rectangle it is known to hold (the shape itself where it is
one; the rectangle inside a convex outline; none for a concave one). Two cores that overlap by a depth `d` in both
directions share area, so the shapes do, and the pair is asked of the rule at the shallowest such overlap, its
corners and its middle: it counts only if every one conflicts. The depths tried go up from a hair, since a rule can
allow a little overlap (two courtyards may touch). Candidates are on a lattice, rounded to a micron, far finer
than the margin the depth keeps."""
from __future__ import annotations

import math
from array import array

from . import geometry as _geometry_module
from .geometry import _rect_of, point_in_polygon
from .values import Box

DEPTHS = (0.002, 0.03, 0.12, 0.3, 0.6)
"""How deep two cores must overlap, in turn, for a pair's conflict to be counted on: the shallowest at which the rule
says conflict at the overlap's corners and middle."""
MARGIN = 1e-5
"""How far inside the depth a lattice point must lie to be named: a candidate's coordinates are rounded to a
micron, and a rule is asked at the depth itself, so the points named are deeper than the one asked."""
CELL = 2.0
"""The grid, mm, the obstacle cores are found by."""
MIN_CORE = 0.25
"""The share of its box a convex outline's core must fill to be used."""


def core_of(shape) -> Box | None:
    """The largest axis-aligned rectangle the shape is known to hold, or None. A rectangle is its own; a convex
    outline holds the box round its centre, shrunk until its four corners are inside; a concave one is not asked."""
    cached = shape.__dict__.get("_core", 0) if hasattr(shape, "__dict__") else 0
    if cached != 0:
        return cached
    poly = shape.poly
    core = None
    if len(poly) >= 3 and shape.box.width > 0 and shape.box.height > 0:
        if _rect_of(poly):
            core = shape.box
        elif _convex(poly):
            core = _inscribed(poly, shape.box)
    try:
        object.__setattr__(shape, "_core", core)
    except (AttributeError, TypeError):
        pass
    return core


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


def _inscribed(poly, box: Box) -> Box | None:
    area = cx = cy = 0.0
    n = len(poly)
    for k in range(n):
        (x0, y0), (x1, y1) = poly[k], poly[(k + 1) % n]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area) < 1e-12:
        return None
    cx, cy = cx / (3.0 * area), cy / (3.0 * area)
    hw, hh = box.width / 2.0, box.height / 2.0

    def inside(t: float) -> bool:
        return all(point_in_polygon((cx + sx * hw * t, cy + sy * hh * t), poly) for sx in (-1, 1) for sy in (-1, 1))
    if not inside(MIN_CORE):
        return None
    lo, hi = MIN_CORE, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2.0
        if inside(mid):
            lo = mid
        else:
            hi = mid
    t = lo * 0.98
    return Box(cx - hw * t, cy - hh * t, cx + hw * t, cy + hh * t)


class NativeOracle:
    """Whether two shapes conflict, as the native judge says it: the judge's own pair rule, over a one-shape
    obstacle index and a one-shape origin handle, each made once."""

    def __init__(self, occ, clearance):
        from .occupancy import _to_native_shape
        self.native = _geometry_module._native
        self.clearance = clearance
        self._kwargs = occ._native_conflict_kwargs()
        self._convert = lambda s: _to_native_shape(s, occ._body_refs, occ._leads, occ._margins)
        self._obstacles: dict = {}
        self._origins: dict = {}

    def hit(self, s, o, dx: float, dy: float) -> bool:
        obstacle = self._obstacles.get(id(o))
        if obstacle is None:
            obstacle = self._obstacles[id(o)] = (o, self.native.NativeObstacles([self._convert(o)], **self._kwargs))
        origin = self._origins.get(id(s))
        if origin is None:
            origin = self._origins[id(s)] = (s, self.native.NativeOriginShapes([self._convert(s)]))
        return obstacle[1].first_conflict_shifted(origin[1], dx, dy, self.clearance) is not None


class PythonOracle:
    """The same question of the Python rule, `Occupancy._conflict`."""

    def __init__(self, occ, clearance):
        self.occ, self.clearance = occ, clearance

    def hit(self, s, o, dx: float, dy: float) -> bool:
        from .occupancy import Shape
        moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((x + dx, y + dy) for x, y in s.poly),
                      s.box.moved(dx, dy), s.label, claims=s.claims, wire=s.wire)
        return self.occ._conflict(moved, o, self.clearance, say=False) is not None


class RefusalMap:
    """The lattice points of a scan, at each turn, that a pair of an item's shape and an obstacle refuse. The
    lattice is `centre` plus whole `step`s, `n` of them each way. `witness(turn, i, j)` is the number of a pair
    in `pairs` ((turn, the item's shape, the obstacle) as the native judge numbers them) that refuses the point,
    or -1. Where several do, the first in the judge's own order: the item's shape, then the obstacle."""

    def __init__(self, oracle, turns: list, obstacles: list, centre, step: float, n: int, skip=frozenset()):
        self.cx, self.cy, self.step, self.n = centre.x, centre.y, step, n
        self.width = 2 * n + 1
        self.pairs: list = []
        self.painted = [[0] * self.width for _ in turns]
        self.witnesses = [array("i", [-1]) * (self.width * self.width) for _ in turns]
        self.asked = 0
        reach = Box(self.cx - n * step, self.cy - n * step, self.cx + n * step, self.cy + n * step)
        index: dict = {}
        cores: list = []
        for oi, o in enumerate(obstacles):
            core = core_of(o) if o.owner not in skip else None
            cores.append(core)
            if core is None:
                continue
            for x in range(math.floor(core.left / CELL), math.floor(core.right / CELL) + 1):
                for y in range(math.floor(core.top / CELL), math.floor(core.bottom / CELL) + 1):
                    index.setdefault((x, y), []).append(oi)
        self._index, self._cores, self._obstacles, self._reach = index, cores, obstacles, reach
        for t, shapes in enumerate(turns):
            for si, s in enumerate(shapes):
                if s.owner in skip:
                    continue
                core = core_of(s)
                if core is not None:
                    self._pairs_of(oracle, t, si, s, core)

    def _near(self, box: Box) -> list:
        found = set()
        for x in range(math.floor(box.left / CELL), math.floor(box.right / CELL) + 1):
            for y in range(math.floor(box.top / CELL), math.floor(box.bottom / CELL) + 1):
                found.update(self._index.get((x, y), ()))
        return sorted(found)

    def _pairs_of(self, oracle, t: int, si: int, s, rs: Box) -> None:
        r = self._reach
        sweep = Box(rs.left + r.left, rs.top + r.top, rs.right + r.right, rs.bottom + r.bottom)
        for oi in self._near(sweep):
            ro = self._cores[oi]
            if not ro.overlaps(sweep):
                continue
            o = self._obstacles[oi]
            # the deepest overlap, the cores' middles together: where the rule is asked first
            mx, my = (ro.left + ro.right - rs.left - rs.right) / 2.0, (ro.top + ro.bottom - rs.top - rs.bottom) / 2.0
            self.asked += 1
            if not oracle.hit(s, o, mx, my):
                continue
            for depth in DEPTHS:
                xa, xb = ro.left - rs.right + depth, ro.right - rs.left - depth
                ya, yb = ro.top - rs.bottom + depth, ro.bottom - rs.top - depth
                if xa > xb or ya > yb:
                    break
                samples = ((xa, ya), (xb, ya), (xa, yb), (xb, yb), ((xa + xb) / 2.0, (ya + yb) / 2.0))
                self.asked += len(samples)
                if all(oracle.hit(s, o, x, y) for x, y in samples):
                    self._paint(t, (t, si, oi), xa + MARGIN, xb - MARGIN, ya + MARGIN, yb - MARGIN)
                    break

    def _paint(self, t: int, pair: tuple, x0: float, x1: float, y0: float, y1: float) -> None:
        if x0 > x1 or y0 > y1:
            return
        n, step = self.n, self.step
        i0, i1 = math.ceil((x0 - self.cx) / step - 1e-9), math.floor((x1 - self.cx) / step + 1e-9)
        j0, j1 = math.ceil((y0 - self.cy) / step - 1e-9), math.floor((y1 - self.cy) / step + 1e-9)
        i0, i1, j0, j1 = max(i0, -n), min(i1, n), max(j0, -n), min(j1, n)
        if i0 > i1 or j0 > j1:
            return
        run = ((1 << (i1 - i0 + 1)) - 1) << (i0 + n)
        pid = len(self.pairs)
        used = False
        rows, wit, w = self.painted[t], self.witnesses[t], self.width
        for j in range(j0, j1 + 1):
            row = rows[j + n]
            new = run & ~row
            if new:
                rows[j + n] = row | run
                used = True
                base = (j + n) * w
                while new:
                    low = new & -new
                    wit[base + low.bit_length() - 1] = pid
                    new ^= low
        if used:
            self.pairs.append(pair)

    def witness(self, t: int, i: int, j: int) -> int:
        return self.witnesses[t][(j + self.n) * self.width + i + self.n]

    def witness_at(self, t: int, x: float, y: float) -> int:
        """`witness` of a point by its coordinates: -1 for one off the lattice."""
        at = self.lattice_of(x, y)
        return -1 if at is None else self.witness(t, at[0], at[1])

    def split(self, triples: list, after: int) -> tuple:
        """(the (x, y, turn) triples the map does not name, where each stood in `triples`, the ones it names as
        (where it stood, its pair, the triple)). The first `after` are never named: a pass that finds its spot
        among the nearest has not asked for a map."""
        cx, cy, step, n, w, wits = self.cx, self.cy, self.step, self.n, self.width, self.witnesses
        kept, stood, named = list(triples[:after]), list(range(min(after, len(triples)))), []
        for at in range(after, len(triples)):
            t = triples[at]
            x, y, k = t
            i, j = round((x - cx) / step), round((y - cy) / step)
            if -n <= i <= n and -n <= j <= n and abs(x - (cx + i * step)) <= 1e-5 and abs(y - (cy + j * step)) <= 1e-5:
                pair = wits[k][(j + n) * w + i + n]
                if pair >= 0:
                    named.append((at, pair, t))
                    continue
            kept.append(t)
            stood.append(at)
        return kept, stood, named

    def lattice_of(self, x: float, y: float):
        """(i, j) of a point on the lattice, or None where it is not on it."""
        i, j = round((x - self.cx) / self.step), round((y - self.cy) / self.step)
        if abs(i) > self.n or abs(j) > self.n:
            return None
        if abs(x - (self.cx + i * self.step)) > 1e-5 or abs(y - (self.cy + j * self.step)) > 1e-5:
            return None
        return i, j

    def blocked(self) -> int:
        """How many lattice points, over every turn, a pair refuses."""
        return sum(bin(row).count("1") for rows in self.painted for row in rows)


def for_scan(occ, item, geom, rots, face, centre, n: int, step: float, clearance, others, native, gw):
    """The refusal map of a scan of `item` over the lattice `centre` + `step` x (-n..n) at each of `rots`, or None
    where this scan cannot have one: a pure-Python one with carried vias that may give way or a net tie of its own.
    Where vias may give way the map reads the item less its carried vias against the board less the others', which
    refuses whatever the whole item does. A natively judged scan whose net ties are judged apart (`recheck`) is
    mapped as it is judged natively: what the map names the native pass refuses, and the Python judgment of what the
    pass accepts only ever refuses more."""
    from .placement import Placement
    from .values import Location
    if native is not None:
        if gw is not None and gw.native is None:
            return None
        sweeper = native if gw is None else gw.native
        turns, obstacles = sweeper.origin, sweeper.shapes
        oracle = NativeOracle(occ, clearance)
    else:
        if gw is not None or occ._tie_refs & geom.owners:
            return None
        turns = [list(occ._legal_origin_shapes(item, geom, Placement(Location(0.0, 0.0), rot, face))) for rot in rots]
        obstacles = list(others)
        oracle = PythonOracle(occ, clearance)
    return RefusalMap(oracle, turns, obstacles, centre, step, n, occ._tie_refs)


def board_only_sweeper(occ, item, face, rots, native, clearance):
    """A native sweeper of `item` over the board alone, no obstacles: the edge and the reservations as the judge
    says them, and every candidate they leave is legal."""
    from .occupancy import NativeSweeper
    nat = _geometry_module._native
    empty = (nat.NativeObstacles([], **occ._native_conflict_kwargs()), [])
    return NativeSweeper(occ, item, face, rots, empty, native.board, clearance)
