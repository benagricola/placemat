"""placemat's ratsnest: the airwires KiCad would draw, and where they cross.

A port of KiCad's `RN_NET` (pcbnew/ratsnest/ratsnest_data.cpp, master,
2026-09-24):

- per net, the nodes are the pad anchors;
- pads already joined by copper are one cluster, united before the tree is
  grown and never given an airwire between them (`AddCluster`, the
  zero-weight edges in `kruskalMST`);
- the airwires are the minimum spanning tree over the anchors, each edge
  weighted by the anchors' distance rounded to the nanometre
  (`CN_ANCHOR::Dist`), equal weights ordered by (weight, lower end, higher
  end), each end as (x, y, tag) (`kruskalMST`'s `orderKey`).

KiCad offers Kruskal the edges of a Delaunay triangulation; the Euclidean
minimum spanning tree is a subgraph of that triangulation, so every pair is
offered here instead, which gives the same tree.

One divergence, deliberate: a tag is the anchor's place in (x, y, refdes,
pad number) order. KiCad's follows its node set's order, which depends on
memory addresses, so two anchors at one position tie differently from run
to run there anyway (report.py's AIRWIRE_NOISE note).

A pad's anchor is `PAD::ShapePos`, read with the board
(`PadGeom.airwire_end`): the centre of its polygonised outline drifts by a
fraction of a micron, enough to make the airwires along a row of pads cross
where KiCad's lie on one line.

Crossings are counted as `report.airwires_from_drc` counts them from KiCad's
own airwires: two edges of different nets that properly intersect."""
from __future__ import annotations

from dataclasses import dataclass
import math

_CELL = 2.0     # mm: the grid a Ratsnest buckets its edges into, so a candidate tests only the edges near it


@dataclass(frozen=True)
class Anchor:
    ref: str
    number: str
    x: float
    y: float


@dataclass(frozen=True)
class Edge:
    net: str
    a: Anchor
    b: Anchor


def _nm(v: float) -> int:
    return int(round(v * 1e6))


def _dist(a, b) -> int:
    """KiCad's edge weight: the distance in nanometres, rounded."""
    h = math.hypot(_nm(a.x) - _nm(b.x), _nm(a.y) - _nm(b.y))
    return int(math.floor(h + 0.5))


def mst(net: str, anchors, joined=()) -> list:
    """The airwires of one net: `anchors` its placed pads, `joined` pairs of
    indexes into them that copper already connects."""
    nodes = list(anchors)
    if len(nodes) < 2:
        return []
    from . import geometry as _geometry
    native = _geometry._native
    if native is not None and hasattr(native, "mst"):       # the same tree, worked out natively
        pairs = native.mst([(a.x, a.y, a.ref, a.number) for a in nodes], [tuple(p) for p in joined])
        return [Edge(net, nodes[i], nodes[j]) for i, j in pairs]
    order = sorted(range(len(nodes)), key=lambda i: (_nm(nodes[i].x), _nm(nodes[i].y), nodes[i].ref, nodes[i].number))
    tag = {i: t for t, i in enumerate(order)}
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def unite(i, j) -> bool:
        ri, rj = find(i), find(j)
        if ri == rj:
            return False
        parent[ri] = rj
        return True

    for i, j in joined:
        unite(i, j)
    end = lambda i: (_nm(nodes[i].x), _nm(nodes[i].y), tag[i])
    candidates = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            # Two anchors at one position in different clusters are joined
            # at weight 1, not 0: KiCad still draws that airwire (the
            # anchor chains in TRIANGULATOR_STATE::Triangulate)
            w = max(_dist(nodes[i], nodes[j]), 1)
            first, second = sorted((end(i), end(j)))
            candidates.append((w, first, second, i, j))
    candidates.sort()
    out = []
    for w, _, _, i, j in candidates:
        if unite(i, j):
            out.append(Edge(net, nodes[i], nodes[j]))
    return out


def _turn(ax, ay, bx, by, cx, cy) -> int:
    """-1, 0 or 1: which side of a-b the point c is on."""
    v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    return (v > 0) - (v < 0)


def segments_cross(p1, p2, q1, q2) -> bool:
    """Whether segment p1-p2 crosses q1-q2 through both their interiors,
    points in mm. An airwire that only touches another - ending on it, as
    along a row of pads, or lying along it - does not cross it, whichever
    way round either is written. The test runs on whole nanometres, KiCad's
    own unit, so a touch is exact rather than a floating-point rounding
    either way."""
    return _cross_nm(_nm(p1[0]), _nm(p1[1]), _nm(p2[0]), _nm(p2[1]), _nm(q1[0]), _nm(q1[1]), _nm(q2[0]), _nm(q2[1]))


def _cross_nm(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
    """segments_cross on whole nanometres already."""
    if max(ax, bx) < min(cx, dx) or max(cx, dx) < min(ax, bx) or max(ay, by) < min(cy, dy) or max(cy, dy) < min(ay, by):
        return False
    return _turn(ax, ay, bx, by, cx, cy) * _turn(ax, ay, bx, by, dx, dy) < 0 and \
        _turn(cx, cy, dx, dy, ax, ay) * _turn(cx, cy, dx, dy, bx, by) < 0


def _ends(e):
    return (e.a.x, e.a.y), (e.b.x, e.b.y)


def _cells(p, q):
    x0, x1 = sorted((p[0], q[0]))
    y0, y1 = sorted((p[1], q[1]))
    for cx in range(math.floor(x0 / _CELL), math.floor(x1 / _CELL) + 1):
        for cy in range(math.floor(y0 / _CELL), math.floor(y1 / _CELL) + 1):
            yield cx, cy


def _weight(weights, net) -> float:
    return 1.0 if weights is None else weights.get(net, 1.0)


def _crossing_weight(weights, partners, pair_weight, a, wa, b, wb) -> float:
    """What a crossing of nets `a` and `b` (weights `wa`, `wb`) counts: the
    pair weight when they are one pair's two halves (a pair crossing itself
    must exchange sides to route coupled), else the lighter of the two."""
    if partners and partners.get(a) == b:
        return pair_weight
    return wa if wa < wb else wb


def crossings(edges, weights=None, partners=None, pair_weight: float = 1.0) -> tuple:
    """(weighted count, crossings per net) over `edges`: each crossing of two
    different nets counts the lighter of the two nets' weights (`weights`,
    net -> weight, 1 when absent), or `pair_weight` when the two are one
    differential pair's halves (`partners`, net -> its partner); per net
    counts every crossing."""
    grid: dict = {}
    for k, e in enumerate(edges):
        for c in _cells(*_ends(e)):
            grid.setdefault(c, []).append(k)
    seen = set()
    total, per_net = 0.0, {}
    for bucket in grid.values():
        for x in range(len(bucket)):
            for y in range(x + 1, len(bucket)):
                i, j = bucket[x], bucket[y]
                if i > j:
                    i, j = j, i
                e, f = edges[i], edges[j]
                if e.net == f.net or (i, j) in seen:
                    continue
                seen.add((i, j))
                if segments_cross(*_ends(e), *_ends(f)):
                    total += _crossing_weight(weights, partners, pair_weight, e.net, _weight(weights, e.net),
                                              f.net, _weight(weights, f.net))
                    for n in (e.net, f.net):
                        per_net[n] = per_net.get(n, 0) + 1
    return total, dict(sorted(per_net.items(), key=lambda kv: (-kv[1], kv[0])))


class Ratsnest:
    """The airwires of the pads placed so far, net by net, kept so a
    candidate can be asked what it would add without recounting the board.
    A net whose weight is 0 is not kept: nothing it crosses counts."""

    def __init__(self, weights: dict | None = None, mirror=None, partners: dict | None = None,
                 pair_weight: float = 1.0):
        self.weights = dict(weights or {})
        # a differential pair's halves: their crossing counts pair_weight
        self.partners = dict(partners or {})
        self.pair_weight = pair_weight
        # placemat_native.NativeRatsnest, kept in step with every set_net:
        # it answers leaf_costs, the question every candidate asks
        self.mirror = mirror
        self._anchors: dict = {}
        self._edges: dict = {}
        self._grid: dict = {}
        self._nmends: dict = {}         # id(edge) -> its ends in whole nanometres

    def set_net(self, net: str, anchors, joined=()) -> None:
        """The placed pads of `net` are now `anchors` (with `joined` as mst takes it)."""
        for e in self._edges.pop(net, ()):
            self._nmends.pop(id(e), None)
            for c in _cells(*_ends(e)):
                bucket = self._grid.get(c)
                if bucket is not None:
                    bucket.remove(e)
        self._anchors[net] = list(anchors)
        if _weight(self.weights, net) <= 0:
            self._edges[net] = []
            if self.mirror is not None:
                self.mirror.set_net(net, [(a.ref, a.number, a.x, a.y) for a in self._anchors[net]], [])
            return
        edges = mst(net, self._anchors[net], joined)
        self._edges[net] = edges
        if self.mirror is not None:
            self.mirror.set_net(net, [(a.ref, a.number, a.x, a.y) for a in self._anchors[net]],
                                [(e.a.ref, e.a.number, e.a.x, e.a.y, e.b.ref, e.b.number, e.b.x, e.b.y) for e in edges])
        for e in edges:
            self._nmends[id(e)] = (_nm(e.a.x), _nm(e.a.y), _nm(e.b.x), _nm(e.b.y))
            for c in _cells(*_ends(e)):
                self._grid.setdefault(c, []).append(e)

    def edges(self) -> list:
        return [e for net in sorted(self._edges) for e in self._edges[net]]

    def _leaves(self, pads, own):
        """A candidate's leaf airwires: (net, weight, p, q, the anchor joined)."""
        out = []
        for net, x, y in pads:
            w = _weight(self.weights, net)
            if w <= 0:
                continue
            best = None
            for a in self._anchors.get(net, ()):
                if a.ref in own:
                    continue
                d = (a.x - x) ** 2 + (a.y - y) ** 2
                if best is None or d < best[0]:
                    best = (d, a)
            if best is not None and best[0] > 0:
                out.append((net, w, (x, y), (best[1].x, best[1].y), best[1]))
        return out

    def leaf_costs(self, pads, own=frozenset(), depth: float = 1.0) -> tuple:
        """(weighted crossings added, escapes crossed) for a candidate: `added`
        and `crossed_escapes` from one search for its leaf airwires. The
        native mirror answers it when there is one, the same way."""
        if self.mirror is not None:
            return self.mirror.leaf_costs(list(pads), list(own), depth)
        leaves = self._leaves(pads, own)
        total, crossed = 0.0, 0
        for k, (net, w, p, q, joined) in enumerate(leaves):
            pn = (_nm(p[0]), _nm(p[1]), _nm(q[0]), _nm(q[1]))
            seen = set()
            for c in _cells(p, q):
                for e in self._grid.get(c, ()):
                    if e.net == net or id(e) in seen or e.a.ref in own or e.b.ref in own:
                        continue
                    seen.add(id(e))
                    if not _cross_nm(*pn, *self._nmends[id(e)]):
                        continue
                    total += _crossing_weight(self.weights, self.partners, self.pair_weight,
                                              net, w, e.net, _weight(self.weights, e.net))
                    n = joined.ref
                    if n and n in (e.a.ref, e.b.ref) and not e.a.ref == e.b.ref == n:
                        at = _crossing_point(p, q, *_ends(e))
                        ends = [q] + [(v.x, v.y) for v in (e.a, e.b) if v.ref == n]
                        if at is not None and min(math.hypot(at[0] - ex, at[1] - ey) for ex, ey in ends) <= depth:
                            crossed += 1
            for net2, w2, p2, q2, _ in leaves[k + 1:]:
                if net2 != net and segments_cross(p, q, p2, q2):
                    total += _crossing_weight(self.weights, self.partners, self.pair_weight, net, w, net2, w2)
        return total, crossed

    def crossed_escapes(self, pads, own=frozenset(), depth: float = 1.0) -> int:
        """How many escapes from one part's pins a candidate's leaf airwires
        cross near that part: a leaf joining a pad of part N that crosses
        another net's airwire from N, within `depth` of N's pads at either
        end. `pads` and `own` as for `added`."""
        return self.leaf_costs(pads, own, depth)[1]

    def crossed_pairs(self, depth: float = 1.0) -> int:
        """How many pairs of airwires of different nets leave pads of one part
        and cross within `depth` of that part's pads: crossed escapes."""
        return len(self.crossed_pair_list(depth))

    def crossed_pair_list(self, depth: float = 1.0) -> list:
        """(part, edge, edge) for each crossed escape `crossed_pairs` counts."""
        out = []
        edges = self.edges()
        index = {id(e): i for i, e in enumerate(edges)}
        for i, e in enumerate(edges):
            parts_e = {e.a.ref, e.b.ref} - {""}
            seen = set()
            for c in _cells(*_ends(e)):
                for f in self._grid.get(c, ()):
                    if id(f) in seen or f.net == e.net or index.get(id(f), -1) <= i:
                        continue
                    seen.add(id(f))
                    shared = parts_e & ({f.a.ref, f.b.ref} - {""})
                    if not shared or not _cross_nm(*self._nmends[id(e)], *self._nmends[id(f)]):
                        continue
                    at = _crossing_point(*_ends(e), *_ends(f))
                    for n in sorted(shared):
                        if e.a.ref == e.b.ref == n or f.a.ref == f.b.ref == n:
                            continue            # an airwire between two of the part's own pads is no escape
                        ends = [(v.x, v.y) for v in (e.a, e.b, f.a, f.b) if v.ref == n]
                        if at is not None and min(math.hypot(at[0] - x, at[1] - y) for x, y in ends) <= depth:
                            out.append((n, e, f))
                            break
        return out

    def pair_crossings(self) -> list:
        """(edge, edge) for each crossing between a differential pair's two
        halves (`partners`), each pair of airwires once."""
        out = []
        edges = self.edges()
        index = {id(e): i for i, e in enumerate(edges)}
        for i, e in enumerate(edges):
            partner = self.partners.get(e.net)
            if partner is None:
                continue
            seen = set()
            for c in _cells(*_ends(e)):
                for f in self._grid.get(c, ()):
                    if id(f) in seen or f.net != partner or index.get(id(f), -1) <= i:
                        continue
                    seen.add(id(f))
                    if _cross_nm(*self._nmends[id(e)], *self._nmends[id(f)]):
                        out.append((e, f))
        return out

    def added(self, pads, own=frozenset()) -> float:
        """The weighted crossings a candidate adds: `pads` its (net, x, y),
        each joined to the nearest placed pad of its net not on a part in
        `own` (the leaf an MST would grow), against the airwires of other
        nets not touching `own`, and against each other."""
        return self.leaf_costs(pads, own)[0]


def _crossing_point(p, q, r, t):
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p, q, r, t
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if den == 0:
        return None
    u = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return x1 + u * (x2 - x1), y1 + u * (y2 - y1)


def _touch(a_outlines, a_box, b_outlines, b_box) -> bool:
    from .geometry import poly_distance, polys_overlap
    if not a_box.overlaps(b_box, gap=1e-6):
        return False
    return any(polys_overlap(p, q) or poly_distance(p, q) <= 1e-6 for p in a_outlines for q in b_outlines)


def board_nets(pads, copper=()) -> dict:
    """{net: (anchors, joined)} for `mst`: `pads` as (ref, number, net,
    layers, outlines, box, anchor), `copper` as (kind, net, layers, outlines,
    box, anchors). As KiCad's connectivity has them: every item's anchors
    are nodes (a track's ends, a via's centre as well as each pad's), and
    two items of one net that share a copper layer and touch are one
    cluster, whose nodes get no airwire between them. A zone joins what it
    touches but lends no node of its own (KiCad's are its fill's outline
    points, moved to the nearest one by `OptimizeRNEdges`): a deliberate
    divergence, since a plane's pads weigh nothing by default."""
    by_net: dict = {}
    for ref, number, net, layers, outlines, box, at in pads:
        if net:
            by_net.setdefault(net, []).append(([Anchor(ref, number, at.x, at.y)], layers, outlines, box))
    for kind, net, layers, outlines, box, points in copper:
        if net in by_net:
            by_net[net].append(([Anchor("", kind, x, y) for x, y in points], layers, outlines, box))
    out = {}
    for net, items in by_net.items():
        parent = list(range(len(items)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(items)):
            _, li, oi, bi = items[i]
            for j in range(i + 1, len(items)):
                _, lj, oj, bj = items[j]
                if li & lj and bi.overlaps(bj, gap=1e-6) and find(i) != find(j) and _touch(oi, bi, oj, bj):
                    parent[find(i)] = find(j)
        anchors, owner = [], []
        for k, (points, _, _, _) in enumerate(items):
            for a in points:
                anchors.append(a)
                owner.append(find(k))
        joined = [(i, j) for i in range(len(anchors)) for j in range(i + 1, len(anchors)) if owner[i] == owner[j]]
        out[net] = (anchors, joined)
    return out


def from_geometry(g, weights=None) -> Ratsnest:
    """The ratsnest of a board as read: every pad where it stands, joined by
    the tracks, vias, pours and zones already on it."""
    pads = [(p.owner, p.number, p.net, p.layers, p.outlines, p.box, p.airwire_end) for fp in g.footprints for p in fp.pads]
    copper = [(c.kind, c.net, c.layers, c.outlines, c.box, c.anchors) for c in g.copper
              if c.kind in ("track", "via", "poly", "zone")]
    r = Ratsnest(weights)
    for net, (anchors, joined) in sorted(board_nets(pads, copper).items()):
        r.set_net(net, anchors, joined)
    return r
