"""2-D geometry in board millimetres: affine transforms, polygon overlap and
distance, boxes. y grows downward and a positive rotation turns
counter-clockwise on screen, as in KiCad. Imports nothing from pcbnew."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .values import Box, Location

Point = tuple[float, float]
Polygon = tuple[Point, ...]


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


def polys_overlap(a: Polygon, b: Polygon) -> bool:
    """True when the two polygons share interior (touching edges do not count).

    Containment used to be tested on each polygon's first vertex alone. One
    polygon lying inside another with that vertex exactly on the other's edge
    - a via's 16-gon centred 0.3 mm inside a pad's edge puts a vertex on it -
    crossed no edge and read as clear. Any vertex strictly inside decides it,
    which can only find an overlap the first-vertex test missed, never make
    edges that merely touch count."""
    if point_in_polygon(a[0], b) or point_in_polygon(b[0], a):
        return True
    for p1, p2 in _edges(a):
        for q1, q2 in _edges(b):
            if segments_intersect(p1, p2, q1, q2):
                return True
    return any(_strictly_inside(p, b) for p in a[1:]) or any(_strictly_inside(q, a) for q in b[1:])


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
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
    """Shortest gap between two polygons; 0 when they overlap or touch."""
    if polys_overlap(a, b):
        return 0.0
    best = math.inf
    for p in a:
        for q1, q2 in _edges(b):
            best = min(best, point_segment_distance(p, q1, q2))
    for p in b:
        for q1, q2 in _edges(a):
            best = min(best, point_segment_distance(p, q1, q2))
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


def polygon_box(poly: Polygon) -> Box:
    return Box.of_points(poly)


def circle_polygon(center: Location, radius: float, n: int = 16) -> Polygon:
    return tuple((center.x + radius * math.cos(2 * math.pi * i / n),
                  center.y + radius * math.sin(2 * math.pi * i / n)) for i in range(n))
