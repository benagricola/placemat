#!/usr/bin/env python3
"""Exact-polygon geometry primitives shared by the layout gates and the oracle.

ONE implementation of each mechanic (the library rule at the top of
`layout_helpers.py`).  Everything here is real geometry: a shape is flattened
to a polygon with `ERROR_OUTSIDE`, so a modelled outline CIRCUMSCRIBES the true
one and a measured gap is never larger, nor an overlap smaller, than reality.
Bounding boxes appear only as a cheap pre-filter, never as an answer.

Two flattening errors, both deliberate and both kept at their historic values
so the gates that moved here report the same numbers as before:

  CLEAR_ERR_NM  500nm  clearance work (`outlines_of`, `collect`).  0.0005mm of
                bias, i.e. below the 3-decimal report resolution.
  OCC_ERR_NM   5000nm  occupancy work (the `ps_*` helpers).  Areas and unions
                over a whole board, where 0.005mm is free and the boolean cost
                is not.

Consumers:
  `placemat clearance`   copper-gap sweep       (collect / sweep / poly_dist)
  `placemat occupancy`    two-face occupancy     (ps_* / inst_of)
  modules/layout_oracle.py    in-process queries     (all of it + SpatialIndex)

numpy is used when present and is the fast path for the all-pairs sweep; the
KiCad AppImage interpreter has no numpy, so every function here also has a pure
-Python path that computes the same quantity by the same formula.  Which one
ran is `HAVE_NUMPY`.
"""
import math
import os

import pcbnew

from placemat.layout_helpers import to_mm   # noqa: E402

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:                       # KiCad's bundled python has no numpy
    np = None
    HAVE_NUMPY = False

NM = 1e6                     # nm per mm
MM = pcbnew.ToMM             # nm -> mm
CLEAR_ERR_NM = 500           # flattening error for clearance geometry
OCC_ERR_NM = 5000            # flattening error for occupancy geometry

FACES = ("F", "B")
CU = {"F": pcbnew.F_Cu, "B": pcbnew.B_Cu}
CRTYD = {"F": "F.Courtyard", "B": "B.Courtyard"}
FAB_LAYERS = ("F.Fab", "B.Fab")


# ============================================================ segment distance
def _segs(pts):
    """Point list -> closed-polygon segments, (N,4) array or list of tuples."""
    if HAVE_NUMPY:
        a = np.asarray(pts, dtype=float)
        b = np.roll(a, -1, axis=0)
        return np.hstack([a, b])
    return [(pts[i][0], pts[i][1], pts[(i + 1) % len(pts)][0],
             pts[(i + 1) % len(pts)][1]) for i in range(len(pts))]


def _pt_seg_dist(p, s):
    """p: (N,2) points, s: (M,4) segments -> (N,M) distances (numpy only)."""
    a, b = s[:, :2], s[:, 2:]
    d = b - a                                        # (M,2)
    ll = np.einsum('ij,ij->i', d, d)                 # (M,)
    ll = np.where(ll == 0, 1e-30, ll)
    ap = p[:, None, :] - a[None, :, :]               # (N,M,2)
    t = np.clip(np.einsum('nmj,mj->nm', ap, d) / ll, 0.0, 1.0)
    proj = a[None, :, :] + t[:, :, None] * d[None, :, :]
    return np.linalg.norm(p[:, None, :] - proj, axis=2)


def _pt_segs_min_py(pts, segs):
    """Smallest distance from any point in `pts` to any segment in `segs`."""
    best = math.inf
    for px, py in pts:
        for ax, ay, bx, by in segs:
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            if ll == 0:
                ll = 1e-30
            t = ((px - ax) * dx + (py - ay) * dy) / ll
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            ex, ey = px - (ax + t * dx), py - (ay + t * dy)
            d = math.hypot(ex, ey)
            if d < best:
                best = d
    return best


def _cross(o, a, b):
    return (a[..., 0] - o[..., 0]) * (b[..., 1] - o[..., 1]) - \
           (a[..., 1] - o[..., 1]) * (b[..., 0] - o[..., 0])


def _cross_py(ox, oy, ax, ay, bx, by):
    return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)


def _sign(v):
    return (v > 0) - (v < 0)


def _seg_seg_min(s1, s2):
    """Min distance between segment sets s1 and s2. 0.0 if any pair crosses."""
    if not len(s1) or not len(s2):
        return math.inf
    if HAVE_NUMPY:
        if not isinstance(s1, np.ndarray):
            s1 = np.asarray(s1, dtype=float)
        if not isinstance(s2, np.ndarray):
            s2 = np.asarray(s2, dtype=float)
        p1, p2 = s1[:, None, :2], s1[:, None, 2:]
        q1, q2 = s2[None, :, :2], s2[None, :, 2:]
        d1 = np.sign(_cross(p1, p2, q1)) * np.sign(_cross(p1, p2, q2))
        d2 = np.sign(_cross(q1, q2, p1)) * np.sign(_cross(q1, q2, p2))
        if np.any((d1 < 0) & (d2 < 0)):
            return 0.0
        m = min(_pt_seg_dist(s1[:, :2], s2).min(), _pt_seg_dist(s1[:, 2:], s2).min(),
                _pt_seg_dist(s2[:, :2], s1).min(), _pt_seg_dist(s2[:, 2:], s1).min())
        return float(m)
    for px1, py1, px2, py2 in s1:
        for qx1, qy1, qx2, qy2 in s2:
            d1 = _sign(_cross_py(px1, py1, px2, py2, qx1, qy1)) * \
                 _sign(_cross_py(px1, py1, px2, py2, qx2, qy2))
            d2 = _sign(_cross_py(qx1, qy1, qx2, qy2, px1, py1)) * \
                 _sign(_cross_py(qx1, qy1, qx2, qy2, px2, py2))
            if d1 < 0 and d2 < 0:
                return 0.0
    a1 = [(s[0], s[1]) for s in s1]
    a2 = [(s[2], s[3]) for s in s1]
    b1 = [(s[0], s[1]) for s in s2]
    b2 = [(s[2], s[3]) for s in s2]
    return float(min(_pt_segs_min_py(a1, s2), _pt_segs_min_py(a2, s2),
                     _pt_segs_min_py(b1, s1), _pt_segs_min_py(b2, s1)))


def point_in_rects(x, y, rects):
    """Is (x, y) inside any of `rects` [(x1, y1, x2, y2), ...]?

    The list form of a region test: a region a board cares about (an isolated
    ground island, a reserved band, a shadow) is usually several rectangles
    rather than one, and asking per rectangle reads as arithmetic."""
    return any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in rects)


def lay_along(seq, start):
    """Pack items along one axis: `seq` is [(name, width, gap_after), ...] and
    `start` the first item's near edge. Returns ({name: centre}, end).

    One-dimensional packing is the commonest arithmetic in a layout script - a
    connector row, a test-point block, a station's parts - and written by hand
    it is where an off-by-a-half-width lands."""
    at = start
    out = {}
    for name, width, gap in seq:
        out[name] = round(at + width / 2.0, 4)
        at += width + gap
    return out, round(at, 4)


def point_in_poly(pt, pts):
    """Ray-cast point-in-polygon (mm coordinates)."""
    x, y = pt
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def point_to_poly(pt, outline):
    """Distance in mm from a point to one closed polygon's EDGES.

    0.0 on an edge; a point strictly inside still reports its distance to the
    nearest edge, so pair it with `point_in_poly` when containment matters.

        >>> point_to_poly((2.0, 0.5), [(0,0),(1,0),(1,1),(0,1)])
        1.0
    """
    segs = [(outline[i][0], outline[i][1],
             outline[(i + 1) % len(outline)][0],
             outline[(i + 1) % len(outline)][1]) for i in range(len(outline))]
    return _pt_segs_min_py([pt], segs)


def poly_dist(a_outlines, b_outlines):
    """Min gap in mm between two multi-outline shapes; 0.0 if they touch.

    Each argument is a list of outlines, each outline a list of (x, y) in mm.
    Containment counts as touching: a shape wholly inside another has no edge
    crossing, so the ray-cast check at the end catches it.

        >>> poly_dist([[(0,0),(1,0),(1,1),(0,1)]], [[(2,0),(3,0),(3,1),(2,1)]])
        1.0
    """
    best = math.inf
    for pa in a_outlines:
        sa = _segs(pa)
        for pb in b_outlines:
            sb = _segs(pb)
            d = _seg_seg_min(sa, sb)
            if d == 0.0:
                return 0.0
            best = min(best, d)
    if point_in_poly(a_outlines[0][0], b_outlines[0]) or \
            point_in_poly(b_outlines[0][0], a_outlines[0]):
        return 0.0
    return best


def outline_segments(outline):
    """A closed outline as [(x1, y1, x2, y2, minx, miny, maxx, maxy), ...].

    The per-segment box is what lets `poly_dist_within` throw away the far side
    of a board-sized pour before measuring anything."""
    out = []
    n = len(outline)
    for i in range(n):
        x1, y1 = outline[i]
        x2, y2 = outline[(i + 1) % n]
        out.append((x1, y1, x2, y2, min(x1, x2), min(y1, y2),
                    max(x1, x2), max(y1, y2)))
    return out


def poly_dist_within(a_outlines, b_outlines, limit, b_segments=None):
    """Exact gap between two shapes when it is <= `limit`, else math.inf.

    Same answer as `poly_dist` inside the limit, and far cheaper against a big
    pour: only the pour's segments whose own box is within `limit` of the query
    are measured.  Containment is tested first, so a query sitting inside a
    pour still reports 0.0 even though no edge is near it.

    `b_segments` is `[outline_segments(o) for o in b_outlines]` if the caller
    has it cached (Item.segments does).

        >>> poly_dist_within([[(0,0),(1,0),(1,1),(0,1)]],
        ...                  [[(9,0),(10,0),(10,1),(9,1)]], 0.5)
        inf
    """
    ax = [p[0] for o in a_outlines for p in o]
    ay = [p[1] for o in a_outlines for p in o]
    abox = (min(ax) - limit, min(ay) - limit, max(ax) + limit, max(ay) + limit)
    for ob in b_outlines:
        if point_in_poly(a_outlines[0][0], ob):
            return 0.0
    for oa in a_outlines:
        if point_in_poly(b_outlines[0][0], oa):
            return 0.0
    if b_segments is None:
        b_segments = [outline_segments(o) for o in b_outlines]
    best = math.inf
    for oa in a_outlines:
        sa = _segs(oa)
        for segs in b_segments:
            near = [s[:4] for s in segs
                    if not (s[6] < abox[0] or s[4] > abox[2] or
                            s[7] < abox[1] or s[5] > abox[3])]
            if not near:
                continue
            d = _seg_seg_min(sa, near)
            if d == 0.0:
                return 0.0
            best = min(best, d)
    return best if best <= limit else math.inf


def bbox_gap(a, b):
    """Distance between two (x1,y1,x2,y2) mm boxes; 0.0 if they overlap."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


# =============================================================== copper items
def outlines_of(item, layer, err_nm=CLEAR_ERR_NM):
    """A board item's real shape on `layer` as mm outlines (ERROR_OUTSIDE).

        >>> outlines_of(track, pcbnew.F_Cu)      # doctest: +SKIP
        [[(1.0, 2.0), (3.0, 2.0), ...]]
    """
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolySet(ps, layer, 0, err_nm, pcbnew.ERROR_OUTSIDE)
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        pts = [(to_mm(o.CPoint(j).x), to_mm(o.CPoint(j).y)) for j in range(o.PointCount())]
        if len(pts) >= 3:
            out.append(pts)
    return out


class Item:
    """One piece of copper: its name, net, copper layers, mm outlines, bbox.

    `fp` is the owning footprint reference for a pad, else None - the sweep
    uses it to separate part geometry (two pads of one package) from layout."""

    __slots__ = ("name", "net", "layers", "outlines", "bbox", "fp", "obj",
                 "_segs")

    def __init__(self, name, net, layers, outlines, fp=None, obj=None):
        self.name, self.net, self.layers, self.outlines = name, net, layers, outlines
        self.fp = fp
        self.obj = obj
        self._segs = None
        xs = [p[0] for o in outlines for p in o]
        ys = [p[1] for o in outlines for p in o]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))

    @property
    def segments(self):
        """Per-outline segment lists with boxes, built once per item."""
        if self._segs is None:
            self._segs = [outline_segments(o) for o in self.outlines]
        return self._segs


def pad_items(fp):
    """One footprint's copper pads as Items (NPTH skipped: it carries none).

    Shared with modules/layout_oracle.py, which builds the same Items for a
    HYPOTHETICAL pose and measures them against the board's index.

        >>> [i.name for i in pad_items(fp)]            # doctest: +SKIP
        ['U1.1', 'U1.2', 'U1.3']
    """
    ref = fp.GetReference()
    items = []
    for pad in fp.Pads():
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            continue
        layers = [l for l in pad.GetLayerSet().CuStack()]
        if not layers:
            continue
        outs = outlines_of(pad, layers[0])
        if outs:
            items.append(Item("%s.%s" % (ref, pad.GetNumber() or "?"),
                              pad.GetNetname(), set(layers), outs, ref, pad))
    return items


def collect(board):
    """Every copper item on `board` as an Item (layers held as a set).

    Pads, tracks, vias, netted gr_poly shapes and zone fills.  NPTH pads are
    skipped: they carry no copper.  A zone contributes one Item per layer,
    everything else one Item whose `layers` is its whole copper stack.

        >>> items = collect(pcbnew.LoadBoard(path))    # doctest: +SKIP
        >>> len(items)
        589
    """
    items = []

    def add(obj, name, net, fp=None):
        layers = [l for l in obj.GetLayerSet().CuStack()]
        if not layers:
            return
        outs = outlines_of(obj, layers[0])
        if outs:
            items.append(Item(name, net, set(layers), outs, fp, obj))

    for fp in board.GetFootprints():
        items += pad_items(fp)
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            c = t.GetPosition()
            add(t, "via@%.3f,%.3f" % (to_mm(c.x), to_mm(c.y)), t.GetNetname())
        else:
            s, e = t.GetStart(), t.GetEnd()
            add(t, "trk %.2f,%.2f-%.2f,%.2f" % (to_mm(s.x), to_mm(s.y), to_mm(e.x), to_mm(e.y)),
                t.GetNetname())
    for d in board.GetDrawings():
        if not isinstance(d, pcbnew.PCB_SHAPE):
            continue
        if not d.GetLayerSet().CuStack():
            continue
        c = d.GetCenter()
        add(d, "poly@%.2f,%.2f" % (to_mm(c.x), to_mm(c.y)), d.GetNetname())
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        for layer in z.GetLayerSet().CuStack():
            ps = z.GetFilledPolysList(layer)
            outs = []
            for k in range(ps.OutlineCount()):
                o = ps.Outline(k)
                outs.append([(to_mm(o.CPoint(j).x), to_mm(o.CPoint(j).y))
                             for j in range(o.PointCount())])
            if outs:
                items.append(Item("zone@%s" % board.GetLayerName(layer),
                                  z.GetNetname(), {layer}, outs, None, z))
    return items


def sweep(items, cutoff=1.0, skip_nonet=True):
    """All different-net Item pairs whose gap <= cutoff, as (gap, a, b), sorted.

        >>> hits = sweep(collect(board), cutoff=0.5)   # doctest: +SKIP
        >>> hits[0][0]
        0.2
    """
    hits = []
    n = len(items)
    for i in range(n):
        a = items[i]
        for j in range(i + 1, n):
            b = items[j]
            if a.net == b.net:
                continue
            if skip_nonet and (not a.net or not b.net):
                continue
            if not (a.layers & b.layers):
                continue
            if bbox_gap(a.bbox, b.bbox) > cutoff:
                continue
            d = poly_dist(a.outlines, b.outlines)
            if d <= cutoff:
                hits.append((d, a, b))
    hits.sort(key=lambda h: h[0])
    return hits


def segment_item(board, net, x1, y1, x2, y2, layer_id, w, name="proposed"):
    """A PROPOSED track as an Item, without adding anything to the board.

    The polygon is KiCad's own track transform (a stadium: rectangle plus round
    caps), so a proposed segment laid over an existing one measures the same
    gaps that existing one does.

        >>> it = segment_item(b, "V48", 10, 10, 20, 10, pcbnew.F_Cu, 0.5)
        ... # doctest: +SKIP
        >>> it.bbox
        (9.75, 9.75, 20.25, 10.25)
    """
    t = pcbnew.PCB_TRACK(board)
    t.SetLayer(layer_id)
    t.SetWidth(int(round(w * NM)))
    t.SetStart(pcbnew.VECTOR2I(int(round(x1 * NM)), int(round(y1 * NM))))
    t.SetEnd(pcbnew.VECTOR2I(int(round(x2 * NM)), int(round(y2 * NM))))
    outs = outlines_of(t, layer_id)
    return Item(name, net, {layer_id}, outs, None, None)


# ============================================================== spatial index
class SpatialIndex:
    """Uniform bbox bins over copper Items, one bucket set per copper layer.

    A query for "what is near this proposed segment" then touches the handful
    of items sharing its bins instead of all of them - the difference between
    milliseconds and a full O(n^2) sweep on a 1,500-item board.

        >>> idx = SpatialIndex(collect(board))         # doctest: +SKIP
        >>> near = idx.near((10, 10, 12, 12), pcbnew.F_Cu, margin=0.5)
        >>> len(near)
        7
    """

    def __init__(self, items, cell_mm=4.0):
        self.cell = float(cell_mm)
        self.items = items
        self.bins = {}
        for it in items:
            for layer in it.layers:
                for key in self._keys(layer, it.bbox):
                    self.bins.setdefault(key, []).append(it)

    def _keys(self, layer, bbox):
        c = self.cell
        ix0, iy0 = int(math.floor(bbox[0] / c)), int(math.floor(bbox[1] / c))
        ix1, iy1 = int(math.floor(bbox[2] / c)), int(math.floor(bbox[3] / c))
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                yield (layer, ix, iy)

    def near(self, bbox, layer, margin=0.0):
        """Items on `layer` whose bbox is within `margin` mm of `bbox`."""
        grown = (bbox[0] - margin, bbox[1] - margin,
                 bbox[2] + margin, bbox[3] + margin)
        seen, out = set(), []
        for key in self._keys(layer, grown):
            for it in self.bins.get(key, ()):
                k = id(it)
                if k in seen:
                    continue
                seen.add(k)
                if bbox_gap(bbox, it.bbox) <= margin:
                    out.append(it)
        return out


# ==================================================== SHAPE_POLY_SET helpers
def ps_new():
    return pcbnew.SHAPE_POLY_SET()


def ps_add(dst, item, layer, clearance_nm=0):
    """Union `item`'s real shape (on `layer`) into `dst`, grown by clearance."""
    t = ps_new()
    item.TransformShapeToPolySet(t, layer, int(clearance_nm), OCC_ERR_NM,
                                 pcbnew.ERROR_OUTSIDE)
    if t.OutlineCount():
        dst.BooleanAdd(t)
    return dst


def ps_circle(cx, cy, r_nm):
    """Drill/annulus circle as a polygon (ERROR_OUTSIDE: circumscribed)."""
    n = max(16, int(2 * math.pi / math.acos(max(-1.0, 1.0 - OCC_ERR_NM / max(r_nm, 1)))))
    n = min(n, 96)
    rr = r_nm / math.cos(math.pi / n)          # circumscribe
    p = ps_new()
    p.NewOutline()
    for i in range(n):
        a = 2 * math.pi * i / n
        p.Append(int(cx + rr * math.cos(a)), int(cy + rr * math.sin(a)))
    return p


def ps_hull(pts):
    """Convex hull of integer-nm points as a polyset (monotone chain).

    Used for *.Fab body outlines, which are UNFILLED strokes: transforming
    them yields a thin frame, so a pin in the middle of a part reads as zero
    overlap.  Hulling is conservative (a chamfered body reads slightly large),
    and body outlines are convex rectangles in practice."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return ps_new()

    def half(ps):
        out = []
        for q in ps:
            while len(out) >= 2:
                (x1, y1), (x2, y2) = out[-2], out[-1]
                if (x2 - x1) * (q[1] - y1) - (y2 - y1) * (q[0] - x1) > 0:
                    break
                out.pop()
            out.append(q)
        return out

    ring = half(pts)[:-1] + half(pts[::-1])[:-1]
    p = ps_new()
    p.NewOutline()
    for x, y in ring:
        p.Append(int(x), int(y))
    return p


def ps_area_mm2(p):
    return abs(p.Area()) / (NM * NM)


def ps_inter(a, b):
    t = pcbnew.SHAPE_POLY_SET(a)
    t.BooleanIntersection(b)
    return t


def ps_hits(a, b):
    """Intersection area in mm2 (0.0 = disjoint or edge-touching only)."""
    if not a.OutlineCount() or not b.OutlineCount():
        return 0.0
    ba, bb = a.BBox(), b.BBox()
    if not ba.Intersects(bb):
        return 0.0
    return ps_area_mm2(ps_inter(a, b))


def ps_bbox_mm(p):
    if not p.OutlineCount():
        return None
    b = p.BBox()
    return (b.GetLeft() / NM, b.GetTop() / NM, b.GetRight() / NM, b.GetBottom() / NM)


def ps_gap_mm(a, b, reach_nm):
    """0.0 if the shapes touch, else the true gap if it is under `reach`."""
    if ps_hits(a, b) > 0:
        return 0.0
    lo, hi = 0.0, reach_nm
    for _ in range(12):                        # bisect on an inflated copy
        mid = (lo + hi) / 2
        t = pcbnew.SHAPE_POLY_SET(a)
        t.Inflate(int(mid), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, OCC_ERR_NM)
        if ps_hits(t, b) > 0:
            hi = mid
        else:
            lo = mid
    return hi / NM if hi < reach_nm else None


def ps_outlines_mm(p):
    """A SHAPE_POLY_SET as mm outlines, the form `poly_dist` eats."""
    out = []
    for i in range(p.OutlineCount()):
        o = p.Outline(i)
        pts = [(o.CPoint(j).x / NM, o.CPoint(j).y / NM)
               for j in range(o.PointCount())]
        if len(pts) >= 3:
            out.append(pts)
    return out


# ================================================================== identity
class PathShapeError(ValueError):
    """A footprint's `Path` field is not `<instance>[.<instance>...].<name>`."""


def path_of(fp):
    """The generation's hierarchical `Path` field, or "" when the footprint has none.

    Zener writes one on every footprint it stamps; a hand-added render-only
    dummy footprint has none, and that is the ONLY tolerated absence - the
    caller falls back to the refdes.
    """
    try:
        return fp.GetFieldText("Path") or ""
    except KeyError:                    # older mills carry no Path field
        return ""


def inst_of(fp):
    """Stable CELL identity: the first component of the `Path` field.

    `mcu.c_vreg.C` -> `mcu`, which is also the PCB_GROUP name the generation
    stamps.  Never the refdes - refdes renumber between mills.  A footprint
    with no Path falls back to its refdes; a Path that is present but carries
    no dot is a shape this code has never seen, and raises rather than
    guessing (a bare `mcu` would silently become its own cell).

        >>> inst_of(fp)                                # doctest: +SKIP
        'mcu'
    """
    path = path_of(fp)
    if not path:
        return fp.GetReference()
    if "." not in path:
        raise PathShapeError(
            "footprint %s has Path %r: expected <instance>...<name> with at "
            "least one dot" % (fp.GetReference(), path))
    return path.split(".")[0]


def cell_of(fp):
    """The FULL instance path: everything before the last dot.

    `mcu.c_vreg.C` -> `mcu.c_vreg`, i.e. the stamped sub-cell rather than
    the top-level group `inst_of` returns.  Same failure rule as `inst_of`.

        >>> cell_of(fp)                                # doctest: +SKIP
        'mcu.c_vreg'
    """
    path = path_of(fp)
    if not path:
        return fp.GetReference()
    if "." not in path:
        raise PathShapeError(
            "footprint %s has Path %r: expected <instance>...<name> with at "
            "least one dot" % (fp.GetReference(), path))
    return path.rsplit(".", 1)[0]


def in_cell(fp, cell):
    """Is `fp` part of `cell`? `cell` is a group name or any Path prefix.

        >>> in_cell(fp, "mcu")                      # doctest: +SKIP
        True
    """
    path = path_of(fp)
    if not path:
        return fp.GetReference() == cell
    return path == cell or path.startswith(cell + ".")


def repo_root(start=None):
    """The directory holding pcb.toml. One implementation, in project."""
    from placemat import project
    return project.repo_root(start)


def overlap_depth(a, b, axis="y"):
    """Real overlap depth (mm) of two (l, t, r, b) boxes along one axis, for
    boxes already known to intersect."""
    if axis == "y":
        return min(a[3], b[3]) - max(a[1], b[1])
    return min(a[2], b[2]) - max(a[0], b[0])


def clip_segment(x1, y1, x2, y2, lo_x, lo_y, hi_x, hi_y):
    """Liang-Barsky clip of a segment to a box; None when wholly outside."""
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x1 - lo_x), (dx, hi_x - x1), (-dy, y1 - lo_y), (dy, hi_y - y1)):
        if abs(pp) < 1e-9:
            if qq < 0:
                return None
            continue
        t = qq / pp
        if pp < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return x1 + t0 * dx, y1 + t0 * dy, x1 + t1 * dx, y1 + t1 * dy
