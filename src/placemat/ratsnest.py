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


def mst_change(rest_anchors, rest_edges, new_pads, *, net=None):
    """Exact signed MST addition using the old tree as a sparse certificate.

    Adding vertices needs only the old MST and edges incident to a new
    vertex. Old edges can disappear, so both added and dropped edges are
    returned. This placement objective uses unjoined pad anchors: a tree
    with prejoined copper clusters is refused rather than losing its cluster
    connectivity. `net` is needed when the old tree has no edges.
    """
    rest, previous, added_nodes = list(rest_anchors), list(rest_edges), list(new_pads)
    if len(previous) != max(0, len(rest) - 1):
        raise ValueError("mst_change requires an unjoined complete rest tree")
    nodes = rest + added_nodes
    if net is None and not previous and added_nodes:
        raise ValueError("mst_change needs net when the rest tree has no edges")
    net = net if net is not None else (previous[0].net if previous else "")
    if not added_nodes:
        return [], [], 0.0
    if any(not math.isfinite(p.x) or not math.isfinite(p.y) for p in nodes):
        raise ValueError("mst_change anchors must be finite")
    indices = {anchor: i for i, anchor in enumerate(nodes)}
    if len(indices) != len(nodes):
        raise ValueError("mst_change anchors must be distinct")
    parents = list(range(len(rest)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for edge in previous:
        i, j = indices.get(edge.a), indices.get(edge.b)
        if i is None or j is None or i >= len(rest) or j >= len(rest) or i == j:
            raise ValueError("mst_change rest edge endpoint invalid")
        a, b = root(i), root(j)
        if a == b:
            raise ValueError("mst_change rest tree must be connected and acyclic")
        parents[a] = b
    order = sorted(range(len(nodes)), key=lambda i: (_nm(nodes[i].x), _nm(nodes[i].y), nodes[i].ref, nodes[i].number))
    tags = {i: tag for tag, i in enumerate(order)}
    def end(i):
        return (_nm(nodes[i].x), _nm(nodes[i].y), tags[i])
    candidates = []
    def offer(i, j):
        i, j = sorted((i, j))
        first, second = sorted((end(i), end(j)))
        candidates.append((max(_dist(nodes[i], nodes[j]), 1), first, second, i, j))
    for edge in previous:
        offer(indices[edge.a], indices[edge.b])
    for j in range(len(rest), len(nodes)):
        for i in range(j):
            offer(i, j)
    candidates.sort()
    parent = list(range(len(nodes)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    tree = []
    for _, _, _, i, j in candidates:
        a, b = find(i), find(j)
        if a != b:
            parent[a] = b
            tree.append(Edge(net, nodes[i], nodes[j]))
            if len(tree) == len(nodes) - 1:
                break
    def identity(edge):
        return frozenset((edge.a, edge.b))
    before, after = {identity(e) for e in previous}, {identity(e) for e in tree}
    added = [e for e in tree if identity(e) not in before]
    dropped = [e for e in previous if identity(e) not in after]
    length = lambda edges: sum(math.hypot(e.a.x - e.b.x, e.a.y - e.b.y) for e in edges)
    return added, dropped, length(added) - length(dropped)


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


def nm_segment(e) -> tuple:
    """An airwire on whole nanometres, with its box: (ax, ay, bx, by, x min, x max, y min, y max), for `count_crossings`."""
    ax, ay, bx, by = _nm(e.a.x), _nm(e.a.y), _nm(e.b.x), _nm(e.b.y)
    return ax, ay, bx, by, min(ax, bx), max(ax, bx), min(ay, by), max(ay, by)


def count_crossings(a, b) -> int:
    """How many pairs of an airwire of `a` and one of `b` (each `nm_segment`) cross: `segments_cross` summed over
    every pair, the box test taken first."""
    n = 0
    for ax, ay, bx, by, x0, x1, y0, y1 in a:
        for cx, cy, dx, dy, u0, u1, v0, v1 in b:
            if x1 < u0 or u1 < x0 or y1 < v0 or v1 < y0:
                continue
            if _cross_nm(ax, ay, bx, by, cx, cy, dx, dy):
                n += 1
    return n


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


KIND_PLAIN, KIND_IMPEDANCE, KIND_PAIR, KIND_PLANE = 0, 1, 2, 3     # pinmap_input.KINDS' order


CLASS_NAMES = ("plain", "impedance", "pair_net", "plane", "pair")     # the classes a crossing is priced in, `prices`' order


def prices_of(s) -> tuple:
    """The crossing prices of settings `s`, in crossings (the run score multiplies by score.crossing), in
    `CLASS_NAMES` order: plain, impedance, pair net, plane, a pair crossing itself."""
    return (1.0, s.score_impedance, s.score_crossing_pair_net, s.score_crossing_plane,
            s.score_pair_crossing / s.score_crossing if s.score_crossing > 0 else 1.0)


def crossing_key(kinds, partners, a, b) -> str:
    """The measure key of a crossing of nets `a` and `b`, which does not depend on any price: "plane" when either net
    is quiet, "pair" for a differential pair's two halves, else its two nets' kinds, the lower first
    ("plain+plain", "impedance+pair_net")."""
    ka, kb = kinds.get(a, KIND_PLAIN), kinds.get(b, KIND_PLAIN)
    if ka == KIND_PLANE or kb == KIND_PLANE:
        return "plane"
    if partners and partners.get(a) == b:
        return "pair"
    lo, hi = sorted((ka, kb))
    return "%s+%s" % (CLASS_NAMES[lo], CLASS_NAMES[hi])


def crossing_class(kinds, partners, prices, a, b) -> int:
    """The class (an index into `prices`, `CLASS_NAMES`) a crossing of nets `a` and `b` is priced in: plane when either
    net is quiet; a differential pair's two halves crossing each other, the pair's own; else the dearer of the two
    nets' kinds (the higher kind on a tie). The pin study's rule (native/src/pinmap.rs `crossing`), with the run
    score's own price for a pair crossing itself."""
    ka, kb = kinds.get(a, KIND_PLAIN), kinds.get(b, KIND_PLAIN)
    if ka == KIND_PLANE or kb == KIND_PLANE:
        return KIND_PLANE
    if partners and partners.get(a) == b:
        return 4
    return max((ka, kb), key=lambda k: (prices[k], k))


def crossing_price(kinds, partners, prices, a, b) -> float:
    """What a crossing of nets `a` and `b` counts, in crossings (the run score multiplies by score.crossing): the
    price of its `crossing_class`. `prices` is (plain, impedance, pair net, plane, a pair with itself)."""
    return prices[crossing_class(kinds, partners, prices, a, b)]


def crossings(edges, kinds=None, partners=None, prices=(1.0, 1.0, 1.0, 1.0, 1.0)) -> tuple:
    """(priced count, crossings per net, crossings per key) over `edges`: each crossing of two different nets
    counts `crossing_price` (`kinds`, net -> kind, plain when absent; `partners`, net -> its pair's other half); per
    net counts every crossing; per key (`crossing_key`) counts each crossing once, whatever it is priced at."""
    kinds = kinds or {}
    grid: dict = {}
    for k, e in enumerate(edges):
        for c in _cells(*_ends(e)):
            grid.setdefault(c, []).append(k)
    seen = set()
    total, per_net = 0.0, {}
    per_class: dict = {}
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
                    k = crossing_class(kinds, partners, prices, e.net, f.net)
                    total += prices[k]
                    key = crossing_key(kinds, partners, e.net, f.net)
                    per_class[key] = per_class.get(key, 0) + 1
                    for n in (e.net, f.net):
                        per_net[n] = per_net.get(n, 0) + 1
    return total, dict(sorted(per_net.items(), key=lambda kv: (-kv[1], kv[0]))), per_class


class Ratsnest:
    """The airwires of the pads placed so far, net by net, kept so a
    candidate can be asked what it would add without recounting the board.
    A quiet net is not kept when a plane crossing weighs 0 (and it is no pair's half): nothing it crosses counts."""

    def __init__(self, kinds: dict | None = None, mirror=None, partners: dict | None = None,
                 prices: tuple = (1.0, 1.0, 1.0, 1.0, 1.0)):
        self.kinds = dict(kinds or {})
        # a differential pair's halves: their crossing counts prices[4]
        self.partners = dict(partners or {})
        self.prices = tuple(prices)
        # placemat_native.NativeRatsnest, kept in step with every set_net:
        # it answers leaf_costs, the question every candidate asks
        self.mirror = mirror
        if mirror is not None:
            mirror.set_prices(list(self.prices))
            for net, kind in self.kinds.items():
                mirror.set_kind(net, kind)
            if self.partners:
                mirror.set_partners(sorted(self.partners.items()))
        self._anchors: dict = {}
        self._edges: dict = {}
        self._grid: dict = {}
        self._nmends: dict = {}         # id(edge) -> its ends in whole nanometres

    def _kept(self, net: str) -> bool:
        """Whether `net`'s edges are kept: all but a quiet net's when a plane crossing weighs nothing (and it is no
        pair's half). Any other net can cross a dearer kind, so it is kept whatever its own kind's price."""
        return not (self.kinds.get(net, KIND_PLAIN) == KIND_PLANE and self.prices[3] <= 0 and net not in self.partners)

    def set_net(self, net: str, anchors, joined=()) -> None:
        """The placed pads of `net` are now `anchors` (with `joined` as mst takes it)."""
        for e in self._edges.pop(net, ()):
            self._nmends.pop(id(e), None)
            for c in _cells(*_ends(e)):
                bucket = self._grid.get(c)
                if bucket is not None:
                    bucket.remove(e)
        self._anchors[net] = list(anchors)
        if not self._kept(net):
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
        """A candidate's leaf airwires: (net, p, q, the anchor joined)."""
        out = []
        for net, x, y in pads:
            if not self._kept(net):
                continue
            best = None
            for a in self._anchors.get(net, ()):
                if a.ref in own:
                    continue
                d = (a.x - x) ** 2 + (a.y - y) ** 2
                if best is None or d < best[0]:
                    best = (d, a)
            if best is not None and best[0] > 0:
                out.append((net, (x, y), (best[1].x, best[1].y), best[1]))
        return out

    def leaf_costs(self, pads, own=frozenset(), depth: float = 1.0) -> tuple:
        """(weighted crossings added, escapes crossed) for a candidate: `added`
        and `crossed_escapes` from one search for its leaf airwires. The
        native mirror answers it when there is one, the same way."""
        if self.mirror is not None:
            return self.mirror.leaf_costs(list(pads), list(own), depth)
        leaves = self._leaves(pads, own)
        total, crossed = 0.0, 0
        for k, (net, p, q, joined) in enumerate(leaves):
            pn = (_nm(p[0]), _nm(p[1]), _nm(q[0]), _nm(q[1]))
            seen = set()
            for c in _cells(p, q):
                for e in self._grid.get(c, ()):
                    if e.net == net or id(e) in seen or e.a.ref in own or e.b.ref in own:
                        continue
                    seen.add(id(e))
                    if not _cross_nm(*pn, *self._nmends[id(e)]):
                        continue
                    total += crossing_price(self.kinds, self.partners, self.prices, net, e.net)
                    n = joined.ref
                    if n and n in (e.a.ref, e.b.ref) and not e.a.ref == e.b.ref == n:
                        at = _crossing_point(p, q, *_ends(e))
                        ends = [q] + [(v.x, v.y) for v in (e.a, e.b) if v.ref == n]
                        if at is not None and min(math.hypot(at[0] - ex, at[1] - ey) for ex, ey in ends) <= depth:
                            crossed += 1
            for net2, p2, q2, _ in leaves[k + 1:]:
                if net2 != net and segments_cross(p, q, p2, q2):
                    total += crossing_price(self.kinds, self.partners, self.prices, net, net2)
        return total, crossed

    def crossed_escapes(self, pads, own=frozenset(), depth: float = 1.0) -> int:
        """How many escapes from one part's pins a candidate's leaf airwires
        cross near that part: a leaf joining a pad of part N that crosses
        another net's airwire from N, within `depth` of N's pads at either
        end. `pads` and `own` as for `added`."""
        return self.leaf_costs(pads, own, depth)[1]

    def crossed_pairs(self, depth: float = 1.0) -> int:
        """How many pairs of airwires of different nets leave pads of one part
        and cross within `depth` of that part's pads: crossed escapes. The count of `crossed_pair_list`, each pair
        tested as it tests it. Only two airwires with a part in common can count, so the pairs are those of each part's
        airwires, a pair taken at the first part it shares (the grid `crossed_pair_list` reads finds every pair that
        crosses: two airwires that cross share a cell)."""
        edges = self.edges()
        nmends = self._nmends
        by_part = {}
        for i, e in enumerate(edges):
            for ref in {e.a.ref, e.b.ref}:
                if ref:
                    by_part.setdefault(ref, []).append(i)
        total = 0
        for part, members in by_part.items():
            for x, i in enumerate(members):
                e = edges[i]
                ea, eb = e.a, e.b
                ex0, ey0, ex1, ey1 = nmends[id(e)]
                elo, ehi, eblo, ebhi = min(ex0, ex1), max(ex0, ex1), min(ey0, ey1), max(ey0, ey1)
                parts_e = {ea.ref, eb.ref} - {""}
                for k in members[x + 1:]:
                    f = edges[k]
                    if f.net == e.net:
                        continue
                    fx0, fy0, fx1, fy1 = nmends[id(f)]
                    if ehi < min(fx0, fx1) or max(fx0, fx1) < elo or ebhi < min(fy0, fy1) or max(fy0, fy1) < eblo:
                        continue
                    shared = sorted(parts_e & ({f.a.ref, f.b.ref} - {""}))
                    if shared[0] != part or not _cross_nm(ex0, ey0, ex1, ey1, fx0, fy0, fx1, fy1):
                        continue        # the pair is taken at the first part it shares
                    at = _crossing_point(*_ends(e), *_ends(f))
                    for n in shared:
                        if ea.ref == eb.ref == n or f.a.ref == f.b.ref == n:
                            continue
                        ends = [(v.x, v.y) for v in (ea, eb, f.a, f.b) if v.ref == n]
                        if at is not None and min(math.hypot(at[0] - px, at[1] - py) for px, py in ends) <= depth:
                            total += 1
                            break
        return total

    def _later(self, e, i, index) -> list:
        """The airwires sharing a grid cell with `e` that come after it (`i` its place in `edges()`), each once, in
        `edges()` order: the grid's buckets are in the order the nets were last set, which is not an order to report in."""
        near = {}
        for c in _cells(*_ends(e)):
            for f in self._grid.get(c, ()):
                k = index.get(id(f), -1)
                if k > i:
                    near[k] = f
        return [near[k] for k in sorted(near)]

    def crossed_pair_list(self, depth: float = 1.0) -> list:
        """(part, edge, edge) for each crossed escape `crossed_pairs` counts."""
        out = []
        edges = self.edges()
        index = {id(e): i for i, e in enumerate(edges)}
        for i, e in enumerate(edges):
            parts_e = {e.a.ref, e.b.ref} - {""}
            for f in self._later(e, i, index):
                if f.net == e.net:
                    continue
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
            for f in self._later(e, i, index):
                if f.net == partner and _cross_nm(*self._nmends[id(e)], *self._nmends[id(f)]):
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
