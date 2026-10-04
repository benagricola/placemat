"""A copper polygon fitted round other nets' clearances.

A fitted pour is the shortest closed outline that holds its pads' copper and
enters no other copper's clearance outline: the relative convex hull of the
pads among the obstacles. Every edge is straight. Each obstacle is a convex
piece, its copper grown by the clearance the pair needs (plus half the pour's
stroke) with every arc replaced by tangent edges that meet outside it, so
nothing approximated ever lies inside the true clearance outline.

The outline starts as the convex hull of the pads. A hull edge an obstacle
intrudes is replaced by the shortest path between its ends that goes round
the obstacle on the hull's inside (A* over a visibility graph of the pads'
and the obstacles' vertices); a pad left outside the result, in the pocket
between the edge and its path, becomes a waypoint of that edge and the paths
are drawn again. An outline that crosses itself or closes up, or an obstacle
left standing inside it, has no way round: there is no fit.

Pure geometry: nothing here knows pcbnew or the plan.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

EPS = 1e-7          # mm: how far into a piece an edge may go and still only touch it
_TOL = 1e-6         # mm: a point this near a boundary is on it

Point = tuple


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def hull(points) -> list:
    """The convex hull of `points`, counter-clockwise (positive cross), with
    no collinear or repeated points: one point, or two, when that is all
    there is."""
    pts = sorted({(round(x, 9), round(y, 9)) for x, y in points})
    if len(pts) <= 2:
        return pts
    lower: list = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 1e-12:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 1e-12:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def grown(points, r: float, sag: float) -> list:
    """The convex hull of `points` grown by `r`, as a convex polygon
    circumscribing the true outline: each corner's arc is divided into
    tangent edges whose meeting corners stand outside the arc by at most
    `sag`. One point makes a circle, two a capsule."""
    h = hull(points)
    step = 2.0 * math.acos(r / (r + sag))             # the widest arc one tangent edge may span
    if len(h) == 1:
        n = max(3, int(math.ceil(2.0 * math.pi / step)))
        rad = r / math.cos(math.pi / n)
        return [(h[0][0] + rad * math.cos((j + 0.5) * 2.0 * math.pi / n),
                 h[0][1] + rad * math.sin((j + 0.5) * 2.0 * math.pi / n)) for j in range(n)]
    n = len(h)
    normal = []                                       # the outward normal's angle of each edge
    for i in range(n):
        dx, dy = h[(i + 1) % n][0] - h[i][0], h[(i + 1) % n][1] - h[i][1]
        normal.append(math.atan2(-dx, dy))
    out = []
    for i in range(n):
        a0 = normal[i - 1]
        span = (normal[i] - a0) % (2.0 * math.pi)
        k = max(1, int(math.ceil(span / step)))
        rad = r / math.cos(span / (2.0 * k))
        for j in range(k):
            a = a0 + (j + 0.5) * span / k
            out.append((h[i][0] + rad * math.cos(a), h[i][1] + rad * math.sin(a)))
    return out


def convex(poly) -> bool:
    n = len(poly)
    sign = 0
    for i in range(n):
        c = _cross(poly[i], poly[(i + 1) % n], poly[(i + 2) % n])
        if abs(c) < 1e-12:
            continue
        if sign and (c > 0) != (sign > 0):
            return False
        sign = 1 if c > 0 else -1
    return True


def triangles(poly) -> list:
    """`poly` (a simple polygon, either way round) as triangles, by ear clipping."""
    pts = list(poly)
    if sum(_cross(pts[0], pts[i], pts[i + 1]) for i in range(1, len(pts) - 1)) < 0:
        pts.reverse()
    out = []
    guard = len(pts) * len(pts)
    while len(pts) > 3 and guard > 0:
        guard -= 1
        n = len(pts)
        for i in range(n):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
            if _cross(a, b, c) <= 1e-12:
                continue
            if any(p not in (a, b, c) and _cross(a, b, p) >= -1e-12 and _cross(b, c, p) >= -1e-12
                   and _cross(c, a, p) >= -1e-12 for p in pts):
                continue
            out.append((a, b, c))
            del pts[i]
            break
        else:
            break
    if len(pts) == 3 and _cross(*pts) > 1e-12:
        out.append(tuple(pts))
    return out


def offset(points, d: float) -> tuple:
    """A simple polygon grown outward by `d`: each corner takes the miter, a
    corner sharper than the miter limit (twice `d`) a bevel."""
    pts = list(points)
    if sum(_cross(pts[0], pts[i], pts[i + 1]) for i in range(1, len(pts) - 1)) < 0:
        pts.reverse()
    n = len(pts)
    out = []
    for i in range(n):
        p, v, q = pts[i - 1], pts[i], pts[(i + 1) % n]
        l1, l2 = math.hypot(v[0] - p[0], v[1] - p[1]), math.hypot(q[0] - v[0], q[1] - v[1])
        if l1 < 1e-12 or l2 < 1e-12:
            continue
        n1 = ((v[1] - p[1]) / l1, -(v[0] - p[0]) / l1)
        n2 = ((q[1] - v[1]) / l2, -(q[0] - v[0]) / l2)
        c = n1[0] * n2[0] + n1[1] * n2[1]
        if c < -0.5:
            out += [(v[0] + d * n1[0], v[1] + d * n1[1]), (v[0] + d * n2[0], v[1] + d * n2[1])]
            continue
        m = d / (1.0 + c)
        out.append((v[0] + m * (n1[0] + n2[0]), v[1] + m * (n1[1] + n2[1])))
    return tuple((round(x, 6), round(y, 6)) for x, y in out)


class Piece:
    """A convex clearance outline: a polygon (counter-clockwise) and what to
    call the copper it came from."""
    __slots__ = ("poly", "what", "left", "top", "right", "bottom", "edges")

    def __init__(self, poly, what: dict):
        self.poly, self.what = tuple(poly), what
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        self.left, self.right, self.top, self.bottom = min(xs), max(xs), min(ys), max(ys)
        edges = []
        for i, a in enumerate(self.poly):
            b = self.poly[(i + 1) % len(self.poly)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = math.hypot(dx, dy)
            if n < 1e-12:
                continue
            nx, ny = dy / n, -dx / n
            edges.append((nx, ny, nx * a[0] + ny * a[1]))
        self.edges = tuple(edges)

    def contains(self, p) -> bool:
        """Whether `p` is inside the piece by more than a touch."""
        return all(nx * p[0] + ny * p[1] < c - EPS for nx, ny, c in self.edges)

    def blocks(self, p, q) -> bool:
        """Whether the segment pq enters the piece's interior by more than a touch."""
        (x0, y0), (x1, y1) = p, q
        if max(x0, x1) <= self.left + EPS or min(x0, x1) >= self.right - EPS \
                or max(y0, y1) <= self.top + EPS or min(y0, y1) >= self.bottom - EPS:
            return False
        dx, dy = x1 - x0, y1 - y0
        t0, t1 = 0.0, 1.0
        for nx, ny, c in self.edges:
            num = c - EPS - (nx * x0 + ny * y0)
            den = nx * dx + ny * dy
            if abs(den) < 1e-15:
                if num < 0.0:
                    return False
                continue
            t = num / den
            if den > 0.0:
                t1 = min(t1, t)
            else:
                t0 = max(t0, t)
            if t0 >= t1 - 1e-12:
                return False
        return True

    def centre(self) -> tuple:
        return (sum(p[0] for p in self.poly) / len(self.poly), sum(p[1] for p in self.poly) / len(self.poly))


def pieces_of(poly, r: float, sag: float, what: str, circle=None, ends=None) -> list:
    """The clearance outline of one piece of copper, `r` all round, as
    convex pieces: a circle (centre and radius), a track (its ends and half
    width), or a polygon of any shape (cut into triangles when it is not
    convex)."""
    if circle:
        return [Piece(grown([(circle[0], circle[1])], circle[2] + r, sag), what)]
    if ends:
        h = min(math.hypot(v[0] - e[0], v[1] - e[1]) for v in poly for e in ends)
        return [Piece(grown(list(ends), h + r, sag), what)]
    if len(poly) < 3:
        return []
    if convex(poly):
        return [Piece(grown(poly, r, sag), what)]
    return [Piece(grown(t, r, sag), what) for t in triangles(poly)]


def _inside(poly, p) -> bool:
    """Even-odd containment of `p` in a closed polyline."""
    x, y = p
    n, hit = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
            hit = not hit
    return hit


def _seg_gap(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    if n < 1e-24:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _edge_gap(poly, p) -> float:
    n = len(poly)
    return min(_seg_gap(p, poly[i], poly[(i + 1) % n]) for i in range(n))


def _outside(poly, p) -> bool:
    return not _inside(poly, p) and _edge_gap(poly, p) > _TOL


def _crossing(a, b, c, d) -> bool:
    """Whether segments ab and cd cross at a point interior to both."""
    d1, d2 = _cross(a, b, c), _cross(a, b, d)
    d3, d4 = _cross(c, d, a), _cross(c, d, b)
    return ((d1 > 1e-12 and d2 < -1e-12) or (d1 < -1e-12 and d2 > 1e-12)) and \
           ((d3 > 1e-12 and d4 < -1e-12) or (d3 < -1e-12 and d4 > 1e-12))


class _NoWay(Exception):
    def __init__(self, a, b):
        self.a, self.b = a, b


class _Space:
    """The free space of a fit: the pieces to keep out of, and the vertices a
    path may turn at. A segment is free when it enters no piece."""

    def __init__(self, pieces, nodes):
        self.pieces = pieces
        self.nodes = list(dict.fromkeys(nodes))
        self._free: dict = {}
        self._paths: dict = {}

    def free(self, p, q) -> bool:
        key = (p, q) if p <= q else (q, p)
        got = self._free.get(key)
        if got is None:
            got = not any(pc.blocks(p, q) for pc in self.pieces)
            self._free[key] = got
        return got

    def blockers(self, p, q) -> list:
        return [pc for pc in self.pieces if pc.blocks(p, q)]

    def path(self, u, v) -> list:
        """The shortest path from u to v among the pieces, as its turning points."""
        got = self._paths.get((u, v))
        if got is not None:
            return got
        if self.free(u, v):
            got = [u, v]
        else:
            nodes = list(dict.fromkeys(self.nodes + [u, v]))
            dist, prev = {u: 0.0}, {}
            heap = [(math.hypot(u[0] - v[0], u[1] - v[1]), 0.0, u)]
            done = set()
            while heap:
                _, g, n = heapq.heappop(heap)
                if n in done:
                    continue
                if n == v:
                    break
                done.add(n)
                for m in nodes:
                    if m in done:
                        continue
                    ng = g + math.hypot(m[0] - n[0], m[1] - n[1])
                    if ng >= dist.get(m, math.inf) - 1e-12 or not self.free(n, m):
                        continue
                    dist[m], prev[m] = ng, n
                    heapq.heappush(heap, (ng + math.hypot(m[0] - v[0], m[1] - v[1]), ng, m))
            if v not in prev:
                raise _NoWay(u, v)
            got, n = [v], v
            while n != u:
                n = prev[n]
                got.append(n)
            got.reverse()
        self._paths[(u, v)] = got
        return got


@dataclass
class Fit:
    outline: tuple | None = None
    problem: str = ""                 # "": fitted; "too close", "no way", "enclosed", "degenerate"
    piece: Piece | None = None        # the copper in the way
    pads: tuple = ()                  # the pads it stands between (labels)
    necks: list = field(default_factory=list)   # (gap, (x, y)) where the outline narrows


def _clean(path) -> list:
    """`path` without repeated or collinear vertices."""
    out = []
    for p in path:
        if out and math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) < 1e-9:
            continue
        out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            if _seg_gap(b, a, c) < 1e-7:
                del out[i]
                changed = True
                break
    return out


def _necks(outline, pads) -> list:
    """(gap, midpoint) where the outline's width is least, one per place it
    narrows: at each inward corner, the nearest edge not beside it, seen
    through the outline's inside and clear of the pads' own copper. Corners
    and edges that follow one another along the outline are one place."""
    n = len(outline)
    found = []
    for i in range(n):
        p, v, q = outline[i - 1], outline[i], outline[(i + 1) % n]
        if _cross(p, v, q) >= -1e-12:
            continue                                  # a corner turning outward
        best = None
        for j in range(n):
            if j in ((i - 2) % n, (i - 1) % n, i, (i + 1) % n):
                continue
            a, b = outline[j], outline[(j + 1) % n]
            d = _seg_gap(v, a, b)
            if best is not None and d >= best[0]:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = max(0.0, min(1.0, ((v[0] - a[0]) * dx + (v[1] - a[1]) * dy) / (dx * dx + dy * dy)))
            f = (a[0] + t * dx, a[1] + t * dy)
            mid = ((v[0] + f[0]) / 2.0, (v[1] + f[1]) / 2.0)
            if _inside(outline, mid):
                best = (d, mid, j)
        if best is not None and not any(_inside(poly, best[1]) for poly in pads):
            found.append((best[0], best[1], i, best[2]))

    def near(x, y) -> bool:
        return min((x - y) % n, (y - x) % n) <= 2
    places: list = []
    for gap, mid, i, j in sorted(found):
        for place in places:
            if any((near(i, pi) and near(j, pj)) or (near(i, pj) and near(j, pi)) for _, _, pi, pj in place):
                place.append((gap, mid, i, j))
                break
        else:
            places.append([(gap, mid, i, j)])
    return [(place[0][0], place[0][1]) for place in places]


def _flanking(piece, verts, a, b) -> tuple:
    """The labels of the pads nearest `piece` on either side of it along the
    way from `a` to `b`: the pads it stands between."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    c = piece.centre()
    tc = ((c[0] - a[0]) * dx + (c[1] - a[1]) * dy)
    sides = ([], [])
    for p, label in verts.items():
        t = (p[0] - a[0]) * dx + (p[1] - a[1]) * dy
        sides[0 if t < tc else 1].append((math.hypot(p[0] - c[0], p[1] - c[1]), label))
    out = [min(side)[1] for side in sides if side]
    return tuple(dict.fromkeys(out))


def inset(poly, d: float):
    """The convex polygon `poly` (counter-clockwise) with every edge moved
    inward by `d`, or by as much less as leaves anything; None for nothing."""
    for k in (1.0, 0.5, 0.25, 0.0):
        out = list(poly)
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            ln = math.hypot(b[0] - a[0], b[1] - a[1])
            if ln < 1e-12:
                continue
            nx, ny = (b[1] - a[1]) / ln, -(b[0] - a[0]) / ln
            c = nx * a[0] + ny * a[1] - d * k
            kept = []
            for j, p in enumerate(out):
                q = out[(j + 1) % len(out)]
                sp, sq = nx * p[0] + ny * p[1] - c, nx * q[0] + ny * q[1] - c
                if sp <= 0.0:
                    kept.append(p)
                if (sp < 0.0 < sq) or (sq < 0.0 < sp):
                    t = sp / (sp - sq)
                    kept.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
            out = kept
            if len(out) < 3:
                break
        if len(out) >= 3:
            return out
    return None


def _area(poly) -> float:
    return sum(_cross(poly[0], poly[i], poly[i + 1]) for i in range(1, len(poly) - 1)) / 2.0


def _halfplane(poly, nx: float, ny: float, c: float) -> list:
    """The convex polygon `poly` cut to the side where nx*x + ny*y >= c."""
    out = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        sp, sq = nx * p[0] + ny * p[1] - c, nx * q[0] + ny * q[1] - c
        if sp >= 0.0:
            out.append(p)
        if (sp < 0.0 < sq) or (sq < 0.0 < sp):
            t = sp / (sp - sq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def clipped(poly, pieces):
    """The part of the convex pad `poly` that lies outside `pieces`, or None
    when none of it does: for each piece that reaches into what is left, the
    side of one of its edges that keeps the most. The pad is closer to
    another net's copper than the clearance there (its footprint sets the
    gap), so the pour holds only the part of it that is clear; the pad's own
    copper stays as it is."""
    out = list(poly)
    for pc in pieces:
        if not (any(pc.contains(p) for p in out)
                or any(pc.blocks(out[i], out[(i + 1) % len(out)]) for i in range(len(out)))):
            continue
        best, most = None, 1e-9
        for nx, ny, c in pc.edges:
            part = _halfplane(out, nx, ny, c)
            if len(part) >= 3 and _area(part) > most:
                best, most = part, _area(part)
        if best is None:
            return None
        out = best
    return out


def _ends(h, piece) -> tuple:
    """The two ends of the hull edge nearest the piece's centre: a direction
    to say which pads stand either side of the piece."""
    c = piece.centre()
    best = min(range(len(h)), key=lambda i: _seg_gap(c, h[i], h[(i + 1) % len(h)]))
    return h[best], h[(best + 1) % len(h)]


def fit(holds, pieces, margin: float = 0.0) -> Fit:
    """The outline of `holds` ((label, convex polygon) of each pad's copper)
    round `pieces`. A pad that a piece reaches into (another net's copper
    nearer than the clearance and the stroke it needs, though no nearer than
    the clearance itself) is held `margin` in from its edges: the pour's
    stroke then reaches the pad's edge and no further."""
    box = (min(p[0] for _, poly in holds for p in poly), min(p[1] for _, poly in holds for p in poly),
           max(p[0] for _, poly in holds for p in poly), max(p[1] for _, poly in holds for p in poly))
    near = [pc for pc in pieces if pc.right > box[0] and pc.left < box[2] and pc.bottom > box[1] and pc.top < box[3]]

    def clear(poly) -> bool:
        return not any(pc.contains(p) for p in poly for pc in near) \
            and not any(pc.blocks(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)) for pc in near)
    verts: dict = {}
    for label, poly in holds:
        if margin > 0.0 and not clear(poly):
            # held in by the margin; or, on a pad too small for that, as far in as clears the copper
            # (down to a speck at its centre: the pour need only touch it)
            c = (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
            tries = [inset(poly, margin)] + [[(c[0] + (x - c[0]) * f, c[1] + (y - c[1]) * f) for x, y in poly]
                                              for f in (0.5, 0.25, 0.1, 0.02)]
            poly = next((t for t in tries if t and clear(t)), poly)
        if not clear(poly):
            # a pad nearer the copper than the clearance, its footprint's own spacing: held as far as it is clear
            part = clipped(poly, near)
            if part is not None and clear(part):
                poly = part
        if not clear(poly):
            pc = next(pc for pc in near if any(pc.contains(p) for p in poly)
                      or any(pc.blocks(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))))
            return Fit(problem="too close", piece=pc, pads=(label,))
        for p in poly:
            verts.setdefault(p, label)
    h = hull(list(verts))
    if len(h) < 3:
        return Fit(problem="degenerate")
    n = len(h)

    def in_hull(p) -> bool:
        return all(_cross(h[i], h[(i + 1) % n], p) >= -1e-9 for i in range(n))
    owner: dict = {}
    nodes = list(verts)
    for pc in near:
        for v in pc.poly:
            if in_hull(v) and not any(o is not pc and o.contains(v) for o in near):
                nodes.append(v)
                owner.setdefault(v, pc)
    space = _Space(near, nodes)
    ways = [[h[i], h[(i + 1) % n]] for i in range(n)]

    def chain(i: int) -> list:
        out = [ways[i][0]]
        for u, v in zip(ways[i], ways[i][1:]):
            out += space.path(u, v)[1:]
        return out

    def lost(e: _NoWay) -> Fit:
        blocking = space.blockers(e.a, e.b)
        mid = ((e.a[0] + e.b[0]) / 2.0, (e.a[1] + e.b[1]) / 2.0)
        pc = min(blocking, key=lambda b: math.hypot(b.centre()[0] - mid[0], b.centre()[1] - mid[1])) if blocking else None
        labels = _flanking(pc, verts, e.a, e.b) if pc is not None else tuple(
            dict.fromkeys(verts[p] for p in (e.a, e.b) if p in verts))
        return Fit(problem="no way", piece=pc, pads=labels)
    try:
        for _ in range(len(verts) + 4):
            chains = [chain(i) for i in range(n)]
            outline = _clean([p for c in chains for p in c[:-1]])
            gone = [p for p in verts if _outside(outline, p)]
            if not gone:
                break
            p = max(gone, key=lambda q: _edge_gap(outline, q))
            for i in range(n):
                if p in ways[i]:
                    continue
                c = chain(i)
                if len(c) > 2 and (_inside(c, p) or _seg_gap(p, c[-1], c[0]) < 1e-7):
                    a, b = ways[i][0], ways[i][-1]
                    along = lambda q: (q[0] - a[0]) * (b[0] - a[0]) + (q[1] - a[1]) * (b[1] - a[1])
                    k = 1
                    while k < len(ways[i]) - 1 and along(ways[i][k]) < along(p):
                        k += 1
                    ways[i].insert(k, p)
                    break
            else:
                break
    except _NoWay as e:
        return lost(e)
    stuck = [p for p in verts if _outside(outline, p)]
    if stuck:                                         # no waypoint brought a pad inside: say which
        return Fit(problem="no way", pads=(verts[stuck[0]],))
    m = len(outline)
    for i in range(m):
        for j in range(i + 2, m):
            if i == 0 and j == m - 1:
                continue
            if _crossing(outline[i], outline[(i + 1) % m], outline[j], outline[(j + 1) % m]):
                owners = [owner[p] for p in outline if p in owner]
                x = outline[i]
                pc = min(owners, key=lambda b: math.hypot(b.centre()[0] - x[0], b.centre()[1] - x[1])) if owners else None
                return Fit(problem="no way", piece=pc, pads=_flanking(pc, verts, *_ends(h, pc)) if pc else ())
    for pc in near:
        c = pc.centre()
        if _inside(outline, c) and _edge_gap(outline, c) > _TOL:
            ranked = sorted(verts.items(), key=lambda kv: math.hypot(kv[0][0] - c[0], kv[0][1] - c[1]))
            return Fit(problem="enclosed", piece=pc, pads=tuple(dict.fromkeys(l for _, l in ranked))[:2])
    necks = _necks(outline, [poly for _, poly in holds])
    pinched = [nk for nk in necks if nk[0] < _TOL]
    if pinched:
        x = pinched[0][1]
        owners = [owner[p] for p in outline if p in owner]
        pc = min(owners, key=lambda b: math.hypot(b.centre()[0] - x[0], b.centre()[1] - x[1])) if owners else None
        return Fit(problem="no way", piece=pc, pads=_flanking(pc, verts, *_ends(h, pc)) if pc else ())
    return Fit(outline=tuple((round(x, 6), round(y, 6)) for x, y in outline), necks=necks)


def edge_pieces(loops, r: float, sag: float, box) -> list:
    """The board's edge as clearance outlines: each leg of each closed
    polyline `loops` (the outline and its cutouts) grown by `r`, those that
    reach `box` (anything with left, top, right, bottom)."""
    out = []
    for loop in loops:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9:
                continue
            if max(a[0], b[0]) < box.left - r or min(a[0], b[0]) > box.right + r \
                    or max(a[1], b[1]) < box.top - r or min(a[1], b[1]) > box.bottom + r:
                continue
            out.append(Piece(grown([a, b], r, sag), {"form": "edge"}))
    return out
