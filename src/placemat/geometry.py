"""2-D geometry in board millimetres: affine transforms, polygon overlap and
distance, boxes. y grows downward and a positive rotation turns
counter-clockwise on screen, as in KiCad. Imports nothing from pcbnew."""
from __future__ import annotations

from dataclasses import dataclass
import functools
import math
import os

from .values import Box, Location

Point = tuple[float, float]
Polygon = tuple[Point, ...]

# An optional Rust accelerator for the predicates below (native/): imported
# if it was built, PLACEMAT_NATIVE=0 forces the pure-Python path below even
# when it was. Every function it supplies has its Python body kept in place
# as the fallback and the reference - see
# docs/superpowers/specs/2026-09-24-native-core-design.md.
def _accept_native(module, version: str):
    """(module, "") when a native module was built from this placemat's
    release, else (None, why): a module from another release could place
    differently, so it is set aside rather than trusted. Between tags both
    carry the last tag's release; a changed source is rebuilt by uv."""
    from . import release
    theirs = getattr(module, "__version__", None)
    if theirs is None:
        return None, "placemat_native has no version: it is not used; rebuild it from this checkout's native/"
    if release(theirs) != release(version):
        return None, ("placemat_native is %s, placemat is %s: it is not used; rebuild it from this checkout's "
                      "native/ (uv pip install -e \".[native]\")" % (theirs, version))
    return module, ""


try:
    import placemat_native as _native
except ImportError:
    _native = None
if os.environ.get("PLACEMAT_NATIVE") == "0":
    _native = None
if _native is not None:
    from . import __version__ as _version
    _native, _why = _accept_native(_native, _version)
    if _why:
        import sys as _sys
        print("placemat: " + _why, file=_sys.stderr)


@dataclass(frozen=True)
class Transform:
    """Affine map  (x, y) -> (a*x + b*y + tx, c*x + d*y + ty)."""
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    @staticmethod
    def translate(dx: float, dy: float) -> "Transform":
        return Transform(tx=dx, ty=dy)

    @staticmethod
    def rotate(deg: float) -> "Transform":
        r = math.radians(deg)
        cos, sin = math.cos(r), math.sin(r)
        # y-down frame: +deg is counter-clockwise on screen
        return Transform(a=cos, b=sin, c=-sin, d=cos)

    @staticmethod
    def rotate_about(center: Location, deg: float) -> "Transform":
        return (Transform.translate(-center.x, -center.y)
                .then(Transform.rotate(deg))
                .then(Transform.translate(center.x, center.y)))

    @staticmethod
    def mirror_x(center: Location) -> "Transform":
        """Mirror left/right about the vertical line through `center` (a face flip)."""
        return Transform(a=-1.0, tx=2 * center.x)

    def then(self, other: "Transform") -> "Transform":
        """self first, then other."""
        return Transform(
            a=other.a * self.a + other.b * self.c,
            b=other.a * self.b + other.b * self.d,
            c=other.c * self.a + other.d * self.c,
            d=other.c * self.b + other.d * self.d,
            tx=other.a * self.tx + other.b * self.ty + other.tx,
            ty=other.c * self.tx + other.d * self.ty + other.ty,
        )

    def apply(self, p: Point) -> Point:
        x, y = p
        return (_clean(self.a * x + self.b * y + self.tx), _clean(self.c * x + self.d * y + self.ty))

    def apply_location(self, p: Location) -> Location:
        return Location(*self.apply((p.x, p.y)))


def _clean(v: float) -> float:
    r = round(v, 9)
    return 0.0 if r == 0 else r


def transform_polygon(poly: Polygon, t: Transform, clean: bool = True) -> Polygon:
    """`clean=False` skips the rounding that keeps written coordinates
    tidy: for a candidate that is only checked, never written."""
    if not clean:
        a, b, c, d, tx, ty = t.a, t.b, t.c, t.d, t.tx, t.ty
        return tuple((a * x + b * y + tx, c * x + d * y + ty) for x, y in poly)
    return tuple(t.apply(p) for p in poly)


def transform_box(box: Box, t: Transform) -> Box:
    """The box round a transformed box. Rounding the four sides is the same
    as rounding the corners and taking the extremes of those, so this asks
    for the extremes first: a candidate placement wants this box and not the
    corners it came from, and a search asks for it a hundred thousand times.
    """
    a, b, c, d, tx, ty = t.a, t.b, t.c, t.d, t.tx, t.ty
    x0, y0, x1, y1 = box.left, box.top, box.right, box.bottom
    ax0, ax1, by0, by1 = a * x0, a * x1, b * y0, b * y1
    cx0, cx1, dy0, dy1 = c * x0, c * x1, d * y0, d * y1
    xs = (ax0 + by0 + tx, ax1 + by0 + tx, ax1 + by1 + tx, ax0 + by1 + tx)
    ys = (cx0 + dy0 + ty, cx1 + dy0 + ty, cx1 + dy1 + ty, cx0 + dy1 + ty)
    return Box(_clean(min(xs)), _clean(min(ys)), _clean(max(xs)), _clean(max(ys)))


def box_polygon(box: Box) -> Polygon:
    return ((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom))


# ------------------------------------------------------------------ predicates
def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def point_in_polygon(p: Point, poly: Polygon) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return True
    return False


def _edges(poly: Polygon):
    n = len(poly)
    for i in range(n):
        yield poly[i], poly[(i + 1) % n]


def _strictly_inside(p: Point, poly: Polygon) -> bool:
    """Inside and not on the boundary, to a nanometre."""
    return point_in_polygon(p, poly) and all(point_segment_distance(p, q1, q2) > 1e-9 for q1, q2 in _edges(poly))


def _rect_of(poly: Polygon) -> bool:
    """Whether the polygon is an axis-aligned rectangle with area: four
    vertices whose sides run alternately along x and y. A courtyard, a pad
    and a body box usually are."""
    if len(poly) != 4:
        return False
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = poly
    if x0 == x1 and y1 == y2 and x2 == x3 and y3 == y0:
        return x0 != x2 and y0 != y1
    if y0 == y1 and x1 == x2 and y2 == y3 and x3 == x0:
        return y0 != y2 and x0 != x1
    return False


def polys_overlap(a: Polygon, b: Polygon) -> bool:
    """True when the two polygons share interior (touching edges do not count).

    Containment used to be tested on each polygon's first vertex alone. One
    polygon lying inside another with that vertex exactly on the other's edge
    - a via's 16-gon centred 0.3 mm inside a pad's edge puts a vertex on it -
    crossed no edge and read as clear. Any vertex strictly inside decides it,
    which can only find an overlap the first-vertex test missed, never make
    edges that merely touch count."""
    pa, pb = _prepared(a), _prepared(b)
    ax0, ay0, ax1, ay1 = pa.bounds
    bx0, by0, bx1, by1 = pb.bounds
    if ax0 >= bx1 or bx0 >= ax1 or ay0 >= by1 or by0 >= ay1:
        return False                    # boxes apart or touching: no shared interior
    if _rect_of(a) and _rect_of(b):
        return True                     # two rectangles are their boxes, and the boxes share interior
    if pa.grid is not None or pb.grid is not None:
        return _prepared_overlap(pa, pb)
    if _native is not None:
        return _native.polys_overlap(a, b)
    # What follows is the full test with what the boxes rule out skipped: a
    # point outside the other's box (closed) is not inside it, and an edge
    # whose box misses the other polygon's box crosses none of its edges.
    def within(p, x0, y0, x1, y1):
        return x0 <= p[0] <= x1 and y0 <= p[1] <= y1
    if (within(a[0], bx0, by0, bx1, by1) and point_in_polygon(a[0], b)) or \
            (within(b[0], ax0, ay0, ax1, ay1) and point_in_polygon(b[0], a)):
        return True
    ea = [(p1, p2) for p1, p2 in _edges(a) if _edge_meets(p1, p2, bx0, by0, bx1, by1)]
    eb = [(q1, q2) for q1, q2 in _edges(b) if _edge_meets(q1, q2, ax0, ay0, ax1, ay1)]
    for p1, p2 in ea:
        for q1, q2 in eb:
            if segments_intersect(p1, p2, q1, q2):
                return True
    if any(within(p, bx0, by0, bx1, by1) and _strictly_inside(p, b) for p in a[1:]) or \
            any(within(q, ax0, ay0, ax1, ay1) and _strictly_inside(q, a) for q in b[1:]):
        return True
    ina, inb = (lambda p: _strictly_inside(p, a)), (lambda p: _strictly_inside(p, b))
    va = [p for p in a if within(p, bx0, by0, bx1, by1)]
    vb = [q for q in b if within(q, ax0, ay0, ax1, ay1)]
    return _along_shared_boundary(ea, vb, ina, inb) or _along_shared_boundary(eb, va, ina, inb)


_NUDGE = 1e-7       # off a boundary, well past strictness (1e-9) and well inside the 1e-6 coordinate grid


def _along_shared_boundary(edges, others, in_a, in_b) -> bool:
    """Whether the interiors meet beside one polygon's edges. With no edge
    crossing another and no vertex strictly inside the other polygon, the
    interiors can still share area when the boundaries coincide - the same
    rectangle, or one slid along a side. Each edge is split where the other
    polygon's vertices lie on it, so each piece is wholly inside, outside or
    on the other's boundary; a point just off a piece's midpoint, on either
    side, inside both polygons is shared interior."""
    for p1, p2 in edges:
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        n2 = dx * dx + dy * dy
        if n2 == 0.0:
            continue
        on = [min(1.0, max(0.0, ((q[0] - p1[0]) * dx + (q[1] - p1[1]) * dy) / n2))
              for q in others if point_segment_distance(q, p1, p2) <= 1e-9]
        if not on:
            continue                    # no vertex of the other on this edge: the other pass or the vertex tests decide
        ts = {0.0, 1.0, *on}
        n = math.sqrt(n2)
        nx, ny = -dy / n * _NUDGE, dx / n * _NUDGE
        ts = sorted(ts)
        for t0, t1 in zip(ts, ts[1:]):
            mx, my = p1[0] + dx * (t0 + t1) / 2, p1[1] + dy * (t0 + t1) / 2
            for s in (1.0, -1.0):
                probe = (mx + s * nx, my + s * ny)
                if in_a(probe) and in_b(probe):
                    return True
    return False


class _Prepared:
    """A polygon with its box, and for one of many vertices a grid of which
    edges and vertices fall in each cell: built once, so a test against it
    looks only at the cells the other polygon covers. Every query returns
    exactly what the walk over the whole polygon would find."""
    MANY = 24           # vertices from which a grid is worth building and keeping

    def __init__(self, poly: Polygon):
        self.poly = poly
        self.bounds = _bounds(poly)
        self.grid = None
        if len(poly) < self.MANY:
            return
        x0, y0, x1, y1 = self.bounds
        self.cell = max(x1 - x0, y1 - y0, 1e-6) / max(1, int(math.sqrt(len(poly))))
        self.edges = list(_edges(poly))
        self.grid, self.rows, self.verts = {}, {}, {}
        for k, (p, q) in enumerate(self.edges):
            xs, ys = self._span(min(p[0], q[0]), max(p[0], q[0])), self._span(min(p[1], q[1]), max(p[1], q[1]))
            for j in ys:
                self.rows.setdefault(j, []).append(k)
                for i in xs:
                    self.grid.setdefault((i, j), []).append(k)
        for k, p in enumerate(poly):
            if k:
                self.verts.setdefault((self._at(p[0]), self._at(p[1])), []).append(k)

    def _at(self, v: float) -> int:
        return math.floor(v / self.cell)

    def _span(self, lo: float, hi: float):
        return range(self._at(lo), self._at(hi) + 1)

    def _cells(self, x0, y0, x1, y1, table) -> list:
        out = set()
        for i in self._span(x0, x1):
            for j in self._span(y0, y1):
                out.update(table.get((i, j), ()))
        return sorted(out)

    def contains(self, p: Point) -> bool:
        """point_in_polygon, over the edges whose row holds the point: an edge
        the ray can cross spans the point's y, so it is in that row."""
        x, y = p
        inside = False
        for k in self.rows.get(self._at(y), ()):
            (x1, y1), (x2, y2) = self.edges[k]
            if (y1 > y) != (y2 > y):
                xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < xin:
                    inside = not inside
        return inside

    def strictly_contains(self, p: Point) -> bool:
        if not self.contains(p):
            return False
        e = 1e-9
        return all(point_segment_distance(p, *self.edges[k]) > e
                   for k in self._cells(p[0] - e, p[1] - e, p[0] + e, p[1] + e, self.grid))

    def edges_meeting(self, x0, y0, x1, y1) -> list:
        return [self.edges[k] for k in self._cells(x0, y0, x1, y1, self.grid)
                if _edge_meets(*self.edges[k], x0, y0, x1, y1)]

    def vertices_within(self, x0, y0, x1, y1) -> list:
        """poly[1:] inside the closed box."""
        return [self.poly[k] for k in self._cells(x0, y0, x1, y1, self.verts)
                if x0 <= self.poly[k][0] <= x1 and y0 <= self.poly[k][1] <= y1]


_prepared_many = functools.lru_cache(maxsize=512)(_Prepared)


def _prepared(poly: Polygon) -> _Prepared:
    """A polygon of many vertices is prepared once and kept: a reservation or
    a keepout drawn with arcs is asked about by every candidate of a scan. A
    small one is cheaper to walk than to look up."""
    if len(poly) < _Prepared.MANY:
        return _Prepared(poly)
    try:
        return _prepared_many(poly)
    except TypeError:                   # built of lists, so not hashable: prepared, not kept
        return _Prepared(poly)


def _prepared_overlap(pa: _Prepared, pb: _Prepared) -> bool:
    """polys_overlap's answer when either polygon has a grid: the same three
    tests, each over only what the other's box can reach."""
    a, b = pa.poly, pb.poly
    ax0, ay0, ax1, ay1 = pa.bounds
    bx0, by0, bx1, by1 = pb.bounds

    def within(p, x0, y0, x1, y1):
        return x0 <= p[0] <= x1 and y0 <= p[1] <= y1

    def contains(pp, p):
        return pp.contains(p) if pp.grid is not None else point_in_polygon(p, pp.poly)

    def strictly(pp, p):
        return pp.strictly_contains(p) if pp.grid is not None else _strictly_inside(p, pp.poly)

    def edges(pp, x0, y0, x1, y1):
        if pp.grid is not None:
            return pp.edges_meeting(x0, y0, x1, y1)
        return [(p1, p2) for p1, p2 in _edges(pp.poly) if _edge_meets(p1, p2, x0, y0, x1, y1)]

    def vertices(pp, x0, y0, x1, y1):
        if pp.grid is not None:
            return pp.vertices_within(x0, y0, x1, y1)
        return [p for p in pp.poly[1:] if within(p, x0, y0, x1, y1)]

    if (within(a[0], bx0, by0, bx1, by1) and contains(pb, a[0])) or \
            (within(b[0], ax0, ay0, ax1, ay1) and contains(pa, b[0])):
        return True
    eb = edges(pb, ax0, ay0, ax1, ay1)
    for p1, p2 in edges(pa, bx0, by0, bx1, by1):
        for q1, q2 in eb:
            if segments_intersect(p1, p2, q1, q2):
                return True
    if any(strictly(pb, p) for p in vertices(pa, bx0, by0, bx1, by1)) or \
            any(strictly(pa, q) for q in vertices(pb, ax0, ay0, ax1, ay1)):
        return True
    va = vertices(pa, bx0, by0, bx1, by1) + ([a[0]] if within(a[0], bx0, by0, bx1, by1) else [])
    vb = vertices(pb, ax0, ay0, ax1, ay1) + ([b[0]] if within(b[0], ax0, ay0, ax1, ay1) else [])
    ina, inb = (lambda p: strictly(pa, p)), (lambda p: strictly(pb, p))
    return _along_shared_boundary(edges(pa, bx0, by0, bx1, by1), vb, ina, inb) or \
        _along_shared_boundary(eb, va, ina, inb)


class PolyRaster:
    """A polygon rastered once into cells wholly inside it, wholly outside it,
    or crossed by its outline: a cell no edge meets lies all on one side, and
    its corners say which. `classify(box)` says whether a box shares interior
    with the polygon when the cells under it decide it, else None - the box
    touches a crossed cell and only the polygon test can say."""
    MAX_CELLS = 40000

    def __init__(self, poly: Polygon):
        x0, y0, x1, y1 = _bounds(poly)
        self.x0, self.y0 = x0, y0
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        self.cell = c = max(0.25, math.sqrt(w * h / self.MAX_CELLS))
        self.nx, self.ny = max(1, int(math.ceil(w / c))), max(1, int(math.ceil(h / c)))
        pp = _prepared(poly)

        def inside(p):
            return pp.contains(p) if pp.grid is not None else point_in_polygon(p, poly)

        def crossed(a0, b0, a1, b1):
            if pp.grid is not None:
                return bool(pp.edges_meeting(a0, b0, a1, b1))
            return any(_edge_meets(p, q, a0, b0, a1, b1) for p, q in _edges(poly))
        corner = [[inside((x0 + i * c, y0 + j * c)) for i in range(self.nx + 1)] for j in range(self.ny + 1)]
        self.state = []                                 # per row: 1 inside, 0 outside, 2 crossed
        for j in range(self.ny):
            row = []
            for i in range(self.nx):
                a0, b0 = x0 + i * c, y0 + j * c
                if crossed(a0, b0, a0 + c, b0 + c):
                    row.append(2)
                else:
                    row.append(1 if corner[j][i] else 0)
            self.state.append(row)

    def classify(self, box):
        c = self.cell
        i0 = max(0, int(math.floor((box.left - self.x0) / c)))
        i1 = min(self.nx, int(math.ceil((box.right - self.x0) / c)))
        j0 = max(0, int(math.floor((box.top - self.y0) / c)))
        j1 = min(self.ny, int(math.ceil((box.bottom - self.y0) / c)))
        crossed = False
        for j in range(j0, j1):
            b0 = self.y0 + j * c
            if not (b0 < box.bottom and b0 + c > box.top):
                continue                                # touches the row only along a line
            row = self.state[j]
            for i in range(i0, i1):
                a0 = self.x0 + i * c
                if not (a0 < box.right and a0 + c > box.left):
                    continue
                s = row[i]
                if s == 1:
                    return True
                if s == 2:
                    crossed = True
        return None if crossed else False


def _bounds(poly: Polygon):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _edge_meets(p1: Point, p2: Point, x0: float, y0: float, x1: float, y1: float) -> bool:
    """The edge's box meets the closed box (x0, y0)-(x1, y1)."""
    return (min(p1[0], p2[0]) <= x1 and max(p1[0], p2[0]) >= x0
            and min(p1[1], p2[1]) <= y1 and max(p1[1], p2[1]) >= y0)


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    if _native is not None:
        return _native.point_segment_distance(p, a, b)
    return _point_segment_distance_py(p, a, b)


def _point_segment_distance_py(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def poly_distance(a: Polygon, b: Polygon) -> float:
    """Shortest gap between two polygons; 0 when they overlap or touch.

    Delegates whole to native when it is built: native's own polys_overlap
    is always the plain (non-grid) test, which is the same boolean answer
    as the grid path for any polygon size (see polys_overlap below), so
    this is exact for a 24+-vertex operand too."""
    if _native is not None:
        return _native.poly_distance(a, b)
    if polys_overlap(a, b):
        return 0.0
    best = math.inf
    for p in a:
        for q1, q2 in _edges(b):
            best = min(best, _point_segment_distance_py(p, q1, q2))
    for p in b:
        for q1, q2 in _edges(a):
            best = min(best, _point_segment_distance_py(p, q1, q2))
    return best


def distance_to_boundary(poly: Polygon, boundary: Polygon) -> float:
    """The shortest distance from `poly` to the EDGE of `boundary`.

    Not `poly_distance`: that returns 0 for polygons that overlap, and a pad
    on a board overlaps the board outline, so it would call every pad 0 mm
    from the edge. This measures to the outline itself, whether the polygon
    is inside it, outside it or across it.

    A polygon that CROSSES the boundary is 0 from it even though no vertex of
    either lies on it - a part declared to overhang an edge does exactly that
    - so the crossing is tested before any vertex is measured. Both directions
    are then taken, because a sharp feature of the boundary can come nearer to
    the polygon's edge than any of its vertices does."""
    for p1, p2 in _edges(poly):
        for q1, q2 in _edges(boundary):
            if segments_intersect(p1, p2, q1, q2):
                return 0.0
    return min(min(point_segment_distance(p, a, b) for p in poly for a, b in _edges(boundary)),
               min(point_segment_distance(q, a, b) for q in boundary for a, b in _edges(poly)))



def circle_polygon(center: Location, radius: float, n: int = 16) -> Polygon:
    return tuple((center.x + radius * math.cos(2 * math.pi * i / n),
                  center.y + radius * math.sin(2 * math.pi * i / n)) for i in range(n))
