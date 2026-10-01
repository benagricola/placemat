"""KiCad's shape collisions, ported in whole nanometres, to the one thing
placemat needs from them: where KiCad's DRC puts a clearance collision.

DRC_TEST_PROVIDER_COPPER_CLEARANCE (pcbnew/drc/drc_test_provider_copper_clearance.cpp,
KiCad 10.0) collides two items' effective shapes with
`itemShape->Collide( otherShape, sub_e( clearance ), &actual, &pos )` and
hands `pos` to DRC_ENGINE::IsNetTieExclusion. Every effective shape of a pad
or a graphic is a SHAPE_COMPOUND, so the pair goes through collideShapes()
(libs/kimath/src/geometry/shape_collisions.cpp): each sub-shape of one
against each of the other, the pair of least `actual` giving `pos`.

A shape here is a tuple, coordinates in nm:

    ("c", x, y, r)               SHAPE_CIRCLE
    ("s", ax, ay, bx, by, w)     SHAPE_SEGMENT
    ("r", x, y, w, h)            SHAPE_RECT, square-cornered: its top-left corner and size; a pad's
                                 carries a sixth item, the quarter turns the pad is turned by (see move_shape)
    ("p", ((x, y), ...))         SHAPE_SIMPLE, a closed polygon

and a compound is a `Compound` of them.
"""
from __future__ import annotations

import math

_ECOORD_MAX = (1 << 63) - 1
_INT_MAX = (1 << 31) - 1


class Compound(tuple):
    """A SHAPE_COMPOUND: sub-shapes, each one of the tuples above."""


# ------------------------------------------------------------------ integer helpers
def rescale(a: int, b: int, c: int) -> int:
    """KiCad's rescale(): a * b / c, rounded half away from zero."""
    q = a * b
    r = (abs(q) + abs(c) // 2) // abs(c)
    return r if (q >= 0) == (c > 0) else -r


def _kiround(v: float) -> int:
    """KiROUND: half away from zero."""
    return int(v + 0.5) if v >= 0 else -int(-v + 0.5)


def _half(v: int) -> int:
    """VECTOR2I / 2: halves round away from zero."""
    return -((1 - v) // 2) if v < 0 else (v + 1) // 2


def _sqrt_int(v: int) -> int:
    """`(int) sqrt( v )`: the double square root, truncated."""
    return int(math.sqrt(v))


def _sq(p, q) -> int:
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2


# ------------------------------------------------------------------ SEG (libs/kimath/src/geometry/seg.cpp)
def nearest_to_point(seg, p):
    """SEG::NearestPoint( VECTOR2I )."""
    (ax, ay), (bx, by) = seg
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return (ax, ay)
    t = dx * (p[0] - ax) + dy * (p[1] - ay)
    if t < 0:
        return (ax, ay)
    if t > l2:
        return (bx, by)
    return (ax + rescale(t, dx, l2), ay + rescale(t, dy, l2))


def sq_distance_point(seg, p) -> int:
    """SEG::SquaredDistance( VECTOR2I )."""
    (ax, ay), (bx, by) = seg
    abx, aby = bx - ax, by - ay
    apx, apy = p[0] - ax, p[1] - ay
    e = apx * abx + apy * aby
    if e <= 0:
        return apx * apx + apy * apy
    f = abx * abx + aby * aby
    if e >= f:
        bpx, bpy = p[0] - bx, p[1] - by
        return bpx * bpx + bpy * bpy
    g = (apx * apx + apy * apy) - (float(e) * float(e)) / float(f)
    if g < 0 or g > _ECOORD_MAX:
        return 0
    return _kiround(g)


def intersect(s1, s2):
    """SEG::Intersect( SEG ): the point two segments share, or None; for
    collinear ones the middle of their overlap."""
    (ax, ay), (bx, by) = s1
    (cx, cy), (ex, ey) = s2
    if max(ax, bx) < min(cx, ex) or max(cx, ex) < min(ax, bx) or \
            max(ay, by) < min(cy, ey) or max(cy, ey) < min(ay, by):
        return None
    d1x, d1y = bx - ax, by - ay
    d2x, d2y = ex - cx, ey - cy
    ox, oy = cx - ax, cy - ay
    det = d2x * d1y - d2y * d1x
    if det == 0:
        if d1x * oy - d1y * ox != 0:
            return None
        use_x = abs(d1x) >= abs(d1y)
        s1a, s1b, s2a, s2b, o1a, o1b = (ax, bx, cx, ex, ay, by) if use_x else (ay, by, cy, ey, ax, bx)
        lo, hi = max(min(s1a, s1b), min(s2a, s2b)), min(max(s1a, s1b), max(s2a, s2b))
        if hi < lo:
            return None
        proj = int((lo + hi) / 2)                  # C++ integer division truncates toward zero
        other = o1a + rescale(proj - s1a, o1b - o1a, s1b - s1a) if s1b != s1a else o1a
        return (proj, other) if use_x else (other, proj)
    p2 = d2x * oy - d2y * ox
    p1 = d1x * oy - d1y * ox
    if det > 0:
        if p1 < 0 or p1 > det or p2 < 0 or p2 > det:
            return None
    elif p1 > 0 or p1 < det or p2 > 0 or p2 < det:
        return None
    return (cx + rescale(p1, d2x, det), cy + rescale(p1, d2y, det))


def sq_distance(s1, s2) -> int:
    """SEG::SquaredDistance( SEG )."""
    if s1[0] == s1[1]:
        return sq_distance_point(s2, s1[0])
    if s2[0] == s2[1]:
        return sq_distance_point(s1, s2[0])
    if intersect(s1, s2) is not None:
        return 0
    return min(_sq(nearest_to_point(s2, s1[0]), s1[0]), _sq(nearest_to_point(s2, s1[1]), s1[1]),
               _sq(nearest_to_point(s1, s2[0]), s2[0]), _sq(nearest_to_point(s1, s2[1]), s2[1]))


def nearest_point(s1, s2):
    """SEG::NearestPoint( SEG ): the point of `s1` nearest `s2`."""
    hit = intersect(s1, s2)
    if hit is not None:
        return hit
    outs = [s1[0], s1[1], nearest_to_point(s1, s2[0]), nearest_to_point(s1, s2[1])]
    dists = [_sq(nearest_to_point(s2, s1[0]), s1[0]), _sq(nearest_to_point(s2, s1[1]), s1[1]),
             _sq(outs[2], s2[0]), _sq(outs[3], s2[1])]
    i = min(range(4), key=lambda k: (dists[k], k))
    return outs[i]


def seg_collide(s1, s2, clearance: int):
    """SEG::Collide( SEG, clearance, &actual ): (actual, collides)."""
    if clearance < 0:
        return 0, False
    if s1[0] == s1[1]:
        d = math.isqrt(sq_distance_point(s2, s1[0]))
        return d, d == 0 or d < clearance
    if s2[0] == s2[1]:
        d = math.isqrt(sq_distance_point(s1, s2[0]))
        return d, d == 0 or d < clearance
    if intersect(s1, s2) is not None:
        return 0, True
    clearance_sq = clearance * clearance
    best = _ECOORD_MAX
    for d in (sq_distance_point(s1, s2[0]), sq_distance_point(s1, s2[1]),
              sq_distance_point(s2, s1[0]), sq_distance_point(s2, s1[1])):
        if d == 0:
            return 0, True
        best = min(best, d)
    return math.isqrt(best), best < clearance_sq


# ------------------------------------------------------------------ SHAPE_LINE_CHAIN_BASE
def point_inside(p, pts) -> bool:
    """SHAPE_LINE_CHAIN_BASE::PointInside at an accuracy of 0: the crossing
    rule, so a point on a right-hand edge is outside."""
    inside = False
    n = len(pts)
    if n < 3:
        return False
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        dy = p2[1] - p1[1]
        if dy == 0:
            continue
        d = rescale(p2[0] - p1[0], p[1] - p1[1], dy)
        if ((p1[1] >= p[1]) != (p2[1] >= p[1])) and (p[0] - p1[0] < d):
            inside = not inside
    return inside


def _edges(pts):
    n = len(pts)
    return [(pts[i], pts[(i + 1) % n]) for i in range(n)]


def chain_collide_seg(pts, seg, clearance: int):
    """SHAPE_LINE_CHAIN::Collide( SEG ) of a closed chain (shape_line_chain.cpp):
    (actual, location) or None."""
    if point_inside(seg[0], pts):
        return 0, seg[0]
    closest = _ECOORD_MAX
    clearance_sq = clearance * clearance
    nearest = (0, 0)
    for s in _edges(pts):
        d = sq_distance(s, seg)
        if d < closest:
            nearest = nearest_point(s, seg)
            closest = d
            if closest == 0:
                break
    if closest == 0 or closest < clearance_sq:
        return _sqrt_int(closest), nearest
    return None


def chain_collide_chain(a, b, clearance: int):
    """Collide( SHAPE_LINE_CHAIN_BASE, SHAPE_LINE_CHAIN_BASE ) (shape_collisions.cpp)
    of two closed chains, A first."""
    closest = _INT_MAX
    nearest = (0, 0)
    if point_inside(a[0], b):
        closest, nearest = 0, a[0]
    elif point_inside(b[0], a):
        closest, nearest = 0, b[0]
    else:
        key = lambda s: (s[0][0], s[0][1])
        a_segs, b_segs = sorted(_edges(a), key=key), sorted(_edges(b), key=key)
        for sa in a_segs:
            for sb in b_segs:
                d, hit = seg_collide(sa, sb, clearance)
                if hit:
                    if d < closest:
                        nearest = nearest_point(sa, sb)
                        closest = d
                    if closest == 0:
                        break
    if closest == 0 or closest < clearance:
        return closest, nearest
    return None


# ------------------------------------------------------------------ one shape against a segment
def circle_collide_seg(c, seg, clearance: int):
    """SHAPE_CIRCLE::Collide( SEG ) (shape_circle.h)."""
    _, cx, cy, r = c
    pn = nearest_to_point(seg, (cx, cy))
    dist_sq = _sq(pn, (cx, cy))
    if dist_sq == 0 or dist_sq < (clearance + r) ** 2:
        at = pn
        if dist_sq == 0:
            pts = _circle_intersect(c, seg)
            if pts:
                at = pts[0]
        return max(0, _sqrt_int(dist_sq) - r), at
    return None


def _resize(v, length: int):
    """VECTOR2I::Resize."""
    x, y = v
    if x == 0 and y == 0:
        return (0, 0)
    if abs(x) == abs(y):
        nx = ny = abs(length) * math.sqrt(0.5)
    else:
        l_sq = x * x + y * y
        n_sq = length * length
        nx = math.sqrt(rescale(n_sq, x * x, l_sq))
        ny = math.sqrt(rescale(n_sq, y * y, l_sq))
    return (-_kiround(nx) if x < 0 else _kiround(nx), -_kiround(ny) if y < 0 else _kiround(ny))


def _euclid_norm(x: int, y: int) -> int:
    """VECTOR2<int64>::EuclideanNorm."""
    if abs(x) == abs(y):
        return _kiround(abs(x) * math.sqrt(2.0))
    if x == 0:
        return abs(y)
    if y == 0:
        return abs(x)
    return _kiround(math.hypot(x, y))


def _circle_intersect(c, seg):
    """CIRCLE::Intersect( SEG ) (libs/kimath/src/geometry/circle.cpp): the
    line's crossings of the circle that lie on the segment."""
    _, cx, cy, r = c
    (ax, ay), (bx, by) = seg
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        m = (ax, ay)
    else:
        t = dx * (cx - ax) + dy * (cy - ay)
        m = (ax + rescale(t, dx, l2), ay + rescale(t, dy, l2))
    om = _euclid_norm(m[0] - cx, m[1] - cy)
    prec = 1                                                     # SHAPE::MIN_PRECISION_IU
    if om > r + prec:
        return []
    if r - prec <= om <= r + prec:
        pts = [m]
    else:
        to1 = _resize((dx, dy), int(math.sqrt(r * r - om * om)))
        pts = [(to1[0] + m[0], to1[1] + m[1]), (-to1[0] + m[0], -to1[1] + m[1])]
    return [p for p in pts if sq_distance_point(seg, p) <= 3]    # SEG::Contains


def segment_collide_seg(s, seg, clearance: int):
    """SHAPE_SEGMENT::Collide( SEG ) (shape_segment.h)."""
    _, ax, ay, bx, by, w = s
    me = ((ax, ay), (bx, by))
    min_dist = (w + 1) // 2 + clearance
    if seg[0] == seg[1]:
        dist_sq = sq_distance_point(me, seg[0])
        loc = nearest_to_point(me, seg[0])
    else:
        dist_sq = sq_distance(me, seg)
        loc = nearest_point(me, seg)
    if dist_sq == 0 or dist_sq < min_dist * min_dist:
        return max(0, _sqrt_int(dist_sq) - (w + 1) // 2), loc
    return None


def rect_collide_seg(r, seg, clearance: int):
    """SHAPE_RECT::Collide( SEG ) (shape_rect.cpp), square-cornered."""
    x, y, w, h = r[1:5]
    for end in (seg[0], seg[1]):
        if x <= end[0] <= x + w and y <= end[1] <= y + h:
            return 0, end
    corners = [(x, y), (x, y + h), (x + w, y + h), (x + w, y), (x, y)]
    closest = _ECOORD_MAX
    nearest = (0, 0)
    for i in range(4):
        side = (corners[i], corners[i + 1])
        d = sq_distance(side, seg)
        if d < closest:
            nearest = nearest_point(side, seg)
            closest = d
        elif d == closest:
            near = nearest_point(side, seg)
            if _sq(near, seg[0]) < _sq(nearest, seg[0]):
                nearest = near
    if closest == 0 or closest < clearance * clearance:
        return _sqrt_int(closest), nearest
    return None


# ------------------------------------------------------------------ pairs of single shapes (shape_collisions.cpp)
def _circle_circle(a, b, clearance):
    _, ax, ay, ar = a
    _, bx, by, br = b
    min_dist = clearance + ar + br
    dist_sq = (bx - ax) ** 2 + (by - ay) ** 2
    if dist_sq == 0 or dist_sq < min_dist * min_dist:
        sx, sy = ax + bx, ay + by
        return max(0, _sqrt_int(dist_sq) - ar - br), (_half(sx), _half(sy))
    return None


def _rect_circle(rect, circle, clearance):
    x, y, w, h = rect[1:5]
    _, cx, cy, r = circle
    min_dist_sq = (clearance + r) ** 2
    vts = [(x, y), (x, y + h), (x + w, y + h), (x + w, y), (x, y)]
    inside = x <= cx <= x + w and y <= cy <= y + h
    nearest_sq = _ECOORD_MAX
    nearest = (0, 0)
    for i in range(4):
        pn = nearest_to_point((vts[i], vts[i + 1]), (cx, cy))
        d = _sq(pn, (cx, cy))
        if d < nearest_sq:
            nearest, nearest_sq = pn, d
            if nearest_sq == 0:
                break
    if inside or nearest_sq == 0 or nearest_sq < min_dist_sq:
        return max(0, _sqrt_int(nearest_sq) - r), nearest
    return None


def _circle_chain(circle, pts, clearance):
    _, cx, cy, _r = circle
    closest = _INT_MAX
    nearest = (0, 0)
    if point_inside((cx, cy), pts):
        nearest, closest = (cx, cy), 0
    else:
        for s in _edges(pts):
            hit = circle_collide_seg(circle, s, clearance)
            if hit is not None:
                d, pn = hit
                if d < closest:
                    nearest, closest = pn, d
                if closest == 0:
                    break
    if closest == 0 or closest < clearance:
        return closest, nearest
    return None


def _circle_segment(circle, s, clearance):
    w = s[5]
    hit = circle_collide_seg(circle, ((s[1], s[2]), (s[3], s[4])), clearance + w // 2)
    if hit is None:
        return None
    return max(0, hit[0] - w // 2), hit[1]


def _segment_segment(a, b, clearance):
    hit = segment_collide_seg(a, ((b[1], b[2]), (b[3], b[4])), clearance + b[5] // 2)
    if hit is None:
        return None
    return max(0, hit[0] - b[5] // 2), hit[1]


def _rect_segment(rect, s, clearance):
    w = s[5]
    hit = rect_collide_seg(rect, ((s[1], s[2]), (s[3], s[4])), clearance + w // 2)
    if hit is None:
        return None
    return max(0, hit[0] - w // 2), hit[1]


def _chain_segment(pts, s, clearance):
    w = s[5]
    hit = chain_collide_seg(pts, ((s[1], s[2]), (s[3], s[4])), clearance + w // 2)
    if hit is None:
        return None
    return max(0, hit[0] - w // 2), hit[1]


def _rect_chain(rect, pts, clearance):
    x, y, w, h = rect[1:5]
    closest = _INT_MAX
    nearest = (0, 0)
    centre = (x + w // 2, y + h // 2)
    if point_inside(centre, pts):
        nearest, closest = centre, 0
    else:
        for s in _edges(pts):
            hit = rect_collide_seg(rect, s, clearance)
            if hit is not None:
                d, pn = hit
                if d < closest:
                    nearest, closest = pn, d
                if closest == 0:
                    break
    if closest == 0 or closest < clearance:
        return closest, nearest
    return None


def _outline(rect):
    x, y, w, h = rect[1:5]
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))


def collide_single(a, b, clearance: int):
    """collideSingleShapes(): (actual, location) of two single shapes, or None."""
    ta, tb = a[0], b[0]
    if ta == "c":
        if tb == "c":
            return _circle_circle(a, b, clearance)
        if tb == "r":
            return _rect_circle(b, a, clearance)
        if tb == "p":
            return _circle_chain(a, b[1], clearance)
        return _circle_segment(a, b, clearance)
    if ta == "r":
        if tb == "c":
            return _rect_circle(a, b, clearance)
        if tb == "r":
            return chain_collide_chain(_outline(a), _outline(b), clearance)
        if tb == "p":
            return _rect_chain(a, b[1], clearance)
        return _rect_segment(a, b, clearance)
    if ta == "p":
        if tb == "c":
            return _circle_chain(b, a[1], clearance)
        if tb == "r":
            return _rect_chain(b, a[1], clearance)
        if tb == "p":
            return chain_collide_chain(a[1], b[1], clearance)
        return _chain_segment(a[1], b, clearance)
    if tb == "c":
        return _circle_segment(b, a, clearance)
    if tb == "r":
        return _rect_segment(b, a, clearance)
    if tb == "p":
        return _chain_segment(b[1], a, clearance)
    return _segment_segment(a, b, clearance)


def collide(a, b, clearance: int, first: bool = False):
    """SHAPE::Collide( SHAPE, clearance, &actual, &location ) - collideShapes()
    in shape_collisions.cpp: (actual, location) or None. Of the sub-shape
    pairs that collide, the one of least `actual` gives the location (the
    first of equals), and a pair at 0 ends the search. `first`: the caller
    passes no `aActual` (pcbnew's Python bindings can only call it so), and
    the first pair that collides ends it."""
    parts_a = a if isinstance(a, Compound) else (a,)
    parts_b = b if isinstance(b, Compound) else (b,)
    if not isinstance(a, Compound) and not isinstance(b, Compound):
        return collide_single(a, b, clearance)
    colliding = False
    current_actual = _INT_MAX
    current_location = (0, 0)
    done = False
    for ea in parts_a:
        for eb in parts_b:
            hit = collide_single(ea, eb, clearance)
            if hit is not None:
                colliding = True
                if hit[0] < current_actual:
                    current_actual, current_location = hit
                if not first and current_actual > 0:
                    continue
                done = True                 # canExit(): found, and no `actual` is wanted or it is 0
                break
        if done:
            break
    return (current_actual, current_location) if colliding else None


def collide_point(shape, p, clearance: int) -> bool:
    """SHAPE::Collide( VECTOR2I, clearance ) of an effective shape: the point
    is a zero-length segment (SHAPE_COMPOUND::Collide( SEG ) is a loop over its
    sub-shapes)."""
    seg = (p, p)
    for s in (shape if isinstance(shape, Compound) else (shape,)):
        t = s[0]
        if t == "c":
            hit = circle_collide_seg(s, seg, clearance)
        elif t == "s":
            hit = segment_collide_seg(s, seg, clearance)
        elif t == "r":
            hit = rect_collide_seg(s, seg, clearance)
        else:
            hit = chain_collide_seg(s[1], seg, clearance)
        if hit is not None:
            return True
    return False


def to_nm(mm: float) -> int:
    return int(round(mm * 1e6))
