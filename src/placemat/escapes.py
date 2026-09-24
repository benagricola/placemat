"""Escape room: the routes out of each placed pad, and what a candidate
placement would close.

Every pad on a net keeps short corridors out of it, each a track plus its
clearance on both sides wide and `place.escape_depth` long:

- a pad of a part with more than two pads has one, along the normal of its
  pad row (placer._pin_normal);
- a pad of a part with two pads or one has one outward along the part's
  axis and one to either side.

A corridor is closed by copper of another net that shares a copper layer
with the pad: another part's pad, a track, a via. A part's body does not
close one, since a track can run under it, and neither does the pad's own
part.

A pad's corridors toward what it connects to are those pointing at a
ratsnest neighbour (a positive dot product). A pad on a quiet net (a
plane's, a free net's) or with no neighbour yet takes any corridor as
toward: a via can go at its end. Taking a pad's last open corridor toward
its target closes its escape; taking its last open corridor of any kind
walls it off."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .geometry import polys_overlap
from .values import Box, CopperLayer, Location

_CELL = 2.0     # mm: the grid corridors and blockers are bucketed into


@dataclass(frozen=True)
class Corridor:
    ref: str
    number: str
    net: str
    layers: frozenset
    poly: tuple
    box: Box
    direction: tuple        # unit (dx, dy), board frame
    via: bool = False       # a via spot where the corridor starts: out to another layer, toward anything


def _box_poly(b: Box) -> tuple:
    return ((b.left, b.top), (b.right, b.top), (b.right, b.bottom), (b.left, b.bottom))


def _half(box: Box, ux: float, uy: float) -> float:
    return abs(ux) * box.width / 2.0 + abs(uy) * box.height / 2.0


def _rect(start, d, length: float, half_width: float) -> tuple:
    (sx, sy), (ux, uy) = start, d
    px, py = -uy * half_width, ux * half_width
    ex, ey = sx + ux * length, sy + uy * length
    return ((sx + px, sy + py), (ex + px, ey + py), (ex - px, ey - py), (sx - px, sy - py))


def _net_sizes(occ) -> dict:
    """{net: pads on it} over the whole board, counted once."""
    sizes = occ.__dict__.get("_net_sizes")
    if sizes is None:
        sizes = {}
        for fp in occ.geometry.footprints:
            for p in fp.pads:
                if p.net:
                    sizes[p.net] = sizes.get(p.net, 0) + 1
        occ.__dict__["_net_sizes"] = sizes
    return sizes


def pad_corridors(occ, ref: str, pads: dict, rotation: float, depth: float) -> list:
    """Corridors for one part's pads: `pads` maps a pad number to (net,
    layers, box) as the part stands (or would stand)."""
    from .placer import _pin_normal
    if len(pads) < occ.settings.place_escape_pads:
        return []
    centres = {(ref, n): b.center for n, (_, _, b) in pads.items()}
    body = Box.union([b for _, _, b in pads.values()]).center
    out = []
    for number, (net, layers, box) in sorted(pads.items()):
        if not net or _net_sizes(occ).get(net, 0) < 2:
            continue                        # nothing to join: an unconnected pin keeps no escape
        c = box.center
        d = _pin_normal(centres, ref, c, rotation, box)
        if d is None:
            ux, uy = c.x - body.x, c.y - body.y
            n = math.hypot(ux, uy)
            d = (ux / n, uy / n) if n > 1e-9 else (1.0, 0.0)
        dirs = [d]
        if len(pads) <= 2:
            dirs += [(-d[1], d[0]), (d[1], -d[0])]
            if len(pads) == 1:
                dirs.append((-d[0], -d[1]))
        nc = occ.geometry.netclass(net)
        half_width = nc.track_width / 2.0 + nc.clearance
        via = nc.via_diameter / 2.0 + nc.clearance
        every = frozenset(occ.geometry.layers) if occ.geometry.layers else frozenset(layers)
        for ux, uy in dirs:
            ux, uy = round(ux, 9) + 0.0, round(uy, 9) + 0.0
            h = _half(box, ux, uy)
            poly = _rect((c.x + ux * h, c.y + uy * h), (ux, uy), depth, half_width)
            out.append(Corridor(ref, number, net, frozenset(layers), poly, Box.of_points(poly), (ux, uy)))
            # a via touching the pad's edge that way, and its clearance: clear on every layer
            r = nc.via_diameter / 2.0
            vx, vy = c.x + ux * (h + r), c.y + uy * (h + r)
            spot = Box(vx - via, vy - via, vx + via, vy + via)
            out.append(Corridor(ref, number, net, every, _box_poly(spot), spot, (ux, uy), via=True))
    return out


def _pads_of(shapes, ref) -> dict:
    pads: dict = {}
    for s in shapes:
        if s.kind in ("pad", "through") and s.owner == ref:
            net, layers, box = pads.get(s.label, (s.net, frozenset(), None))
            pads[s.label] = (net or s.net, layers | s.layers, s.box if box is None else Box.union([box, s.box]))
    return pads


def corridors(occ, ref: str, depth: float | None = None) -> list:
    """A placed part's corridors where it stands."""
    g = occ.items[ref]
    depth = occ.settings.place_escape_depth if depth is None else depth
    return pad_corridors(occ, ref, _pads_of(g.shapes, ref), g.reference.rotation, depth)


def _cells(box: Box):
    for cx in range(math.floor(box.left / _CELL), math.floor(box.right / _CELL) + 1):
        for cy in range(math.floor(box.top / _CELL), math.floor(box.bottom / _CELL) + 1):
            yield cx, cy


class _Grid:
    def __init__(self):
        self.cells: dict = {}

    def add(self, item, box):
        for c in _cells(box):
            self.cells.setdefault(c, []).append(item)

    def remove(self, item, box):
        for c in _cells(box):
            bucket = self.cells.get(c)
            if bucket is not None and item in bucket:
                bucket.remove(item)

    def near(self, box):
        seen = set()
        for c in _cells(box):
            for item in self.cells.get(c, ()):
                if id(item) not in seen:
                    seen.add(id(item))
                    yield item


class Escapes:
    """The corridors of every placed pad, which are open, and what copper
    closes them; kept as items commit."""

    def __init__(self, occ, mirror: bool = True):
        self.occ = occ
        self.depth = occ.settings.place_escape_depth
        self._corr: dict = {}           # ref -> [Corridor]
        self._open: dict = {}           # id(corridor) -> bool
        self._cgrid = _Grid()
        self._blockers: dict = {}       # ref (or copper key) -> [Shape]
        self._bgrid = _Grid()
        # The native mirror (the occupancy's placemat_native.NativeRatsnest,
        # which also holds the ratsnest `closed` reads): kept in step after
        # every refresh, it answers `closed`. `_nid` is each corridor's id there.
        self.mirror = occ.ratsnest().mirror if mirror else None
        self._nid: dict = {}
        if self.mirror is not None:
            self.mirror.esc_set_quiet(sorted(occ.quiet_nets))
        self.refresh(set(occ.items), copper=True)

    # ------------------------------------------------------------ keeping up
    def refresh(self, refs, copper: bool = False) -> None:
        """Take `refs`' corridors and copper out and put back what is placed now."""
        occ = self.occ
        vacated = []
        touched = []
        for ref in refs:
            for c in self._corr.pop(ref, ()):
                self._cgrid.remove(c, c.box)
                self._open.pop(id(c), None)
                self._nid.pop(id(c), None)
            for s in self._blockers.pop(ref, ()):
                self._bgrid.remove(s, s.box)
                vacated.append(s.box)
        changed = []
        for ref in refs:
            g = occ.items.get(ref)
            if g is None or ref in occ.pending or not occ.geometry.has_footprint(ref):
                continue
            own = [s for s in g.shapes if s.kind in ("pad", "through") and s.owner == ref]
            self._blockers[ref] = own
            for s in own:
                self._bgrid.add(s, s.box)
            changed += own
            cs = corridors(occ, ref, self.depth)
            self._corr[ref] = cs
            for c in cs:
                self._cgrid.add(c, c.box)
                self._open[id(c)] = self._clear(c)
        if copper:
            metal = [s for s in occ.copper if s.kind in ("copper", "through")]
            self._blockers[":copper"] = metal
            for s in metal:
                self._bgrid.add(s, s.box)
            changed += metal
        for s in changed:                   # what the new copper now closes
            for c in self._cgrid.near(s.box):
                if self._open.get(id(c)) and self._closes(s, c):
                    self._open[id(c)] = False
                    touched.append(c)
        for box in vacated:                 # what copper that moved away may have opened
            for c in self._cgrid.near(box):
                if not self._open.get(id(c), True):
                    self._open[id(c)] = self._clear(c)
                    touched.append(c)
        if self.mirror is not None:
            self._sync(refs, copper, touched)

    def _sync(self, refs, copper: bool, touched) -> None:
        """Hand the mirror what `refresh` changed: the parts' corridors and
        pads, the planned copper, and the open flags it set elsewhere."""
        m = self.mirror
        for ref in refs:
            cs = self._corr.get(ref, [])
            centres = {}
            if cs:
                centres = {n: b.center for n, (_, _, b) in _pads_of(self.occ.items[ref].shapes, ref).items()}
            ids = m.esc_set_part(ref, [_corr_tuple(c, self._open[id(c)], centres[c.number]) for c in cs])
            for c, i in zip(cs, ids):
                self._nid[id(c)] = i
            m.esc_set_metal(ref, [_metal_tuple(sh) for sh in self._blockers.get(ref, ())])
        if copper:
            m.esc_set_metal(":copper", [_metal_tuple(sh) for sh in self._blockers.get(":copper", ())])
        flags = [(self._nid[id(c)], self._open[id(c)]) for c in touched if id(c) in self._nid]
        if flags:
            m.esc_set_open(flags)

    def add_copper(self, shapes) -> None:
        metal = [s for s in shapes if s.kind in ("copper", "through")]
        self._blockers.setdefault(":copper", []).extend(metal)
        touched = []
        for s in metal:
            self._bgrid.add(s, s.box)
            for c in self._cgrid.near(s.box):
                if self._open.get(id(c)) and self._closes(s, c):
                    self._open[id(c)] = False
                    touched.append(c)
        if self.mirror is not None:
            self.mirror.esc_set_metal(":copper", [_metal_tuple(sh) for sh in metal], add=True)
            flags = [(self._nid[id(c)], False) for c in touched if id(c) in self._nid]
            if flags:
                self.mirror.esc_set_open(flags)

    @staticmethod
    def _closes(s, c) -> bool:
        return (s.net != c.net and s.owner != c.ref and bool(s.layers & c.layers)
                and s.box.overlaps(c.box) and polys_overlap(s.poly, c.poly))

    def _clear(self, c, skip=frozenset()) -> bool:
        return not any(self._closes(s, c) for s in self._bgrid.near(c.box) if s.owner not in skip)

    # ------------------------------------------------------------ targets
    def _targets(self, ref, number, net, at: Location):
        """Where a pad's airwires go: its ratsnest neighbours; None when any
        way out will do (a quiet net, or nothing placed to join yet)."""
        occ = self.occ
        if net in occ.quiet_nets:
            return None
        rn = occ.ratsnest()
        out = [(e.b if (e.a.ref, e.a.number) == (ref, number) else e.a) for e in rn._edges.get(net, ())
               if (ref, number) in ((e.a.ref, e.a.number), (e.b.ref, e.b.number))]
        return [(a.x - at.x, a.y - at.y) for a in out] or None

    @staticmethod
    def _toward(c, targets) -> bool:
        return c.via or targets is None or any(c.direction[0] * dx + c.direction[1] * dy > 1e-9 for dx, dy in targets)

    def open_toward(self, ref: str, number: str) -> bool:
        """Whether a placed pad still has an open corridor toward what it joins."""
        cs = [c for c in self._corr.get(ref, ()) if c.number == number]
        if not cs:
            return True
        box = Box.union([c.box for c in cs])
        at = self.occ.pad_location(ref, number)
        targets = self._targets(ref, number, cs[0].net, at)
        return any(self._open.get(id(c)) and self._toward(c, targets) for c in cs)

    def confirmed(self) -> tuple:
        """(closed, walled): the pads the path search confirms, each as
        (ref, number, net, what closes its corridors, what it joins): walled
        when no track or via gets out at all, closed when none gets out toward
        what it joins."""
        occ = self.occ
        closed, walled = [], []
        for ref, cs in sorted(self._corr.items()):
            for group in _group(cs):
                c0 = group[0]
                open_ = [c for c in group if self._open.get(id(c))]
                at = occ.pad_location(ref, c0.number)
                targets = self._targets(ref, c0.number, c0.net, at)
                if open_ and any(self._toward(c, targets) for c in open_):
                    continue
                pad = Box.union([c.box for c in group])
                near = list(self._bgrid.near(pad.inflate(self.depth + 1.0)))
                by = sorted({sh.owner for c in group for sh in self._bgrid.near(c.box) if self._closes_any(sh, c)})
                if not open_ and not path_out(occ, ref, c0.number, self.depth, near=near):
                    walled.append((ref, c0.number, c0.net, by, []))
                    continue
                if targets and not any(path_out(occ, ref, c0.number, self.depth, toward=t, near=near) for t in targets):
                    closed.append((ref, c0.number, c0.net, by, self._joins(ref, c0.number, c0.net)))
        return closed, walled

    def _closes_any(self, s, c) -> bool:
        """Whether `s` closes corridor `c`, the pad's own part included: what a
        finding names as walling a pad in."""
        return (s.net != c.net and bool(s.layers & c.layers) and s.box.overlaps(c.box)
                and not (s.owner == c.ref and s.label == c.number) and polys_overlap(s.poly, c.poly))

    def _joins(self, ref, number, net) -> list:
        rn = self.occ.ratsnest()
        out = set()
        for e in rn._edges.get(net, ()):
            if (e.a.ref, e.a.number) == (ref, number) and e.b.ref:
                out.add(e.b.ref)
            elif (e.b.ref, e.b.number) == (ref, number) and e.a.ref:
                out.add(e.a.ref)
        return sorted(out)

    def count(self) -> tuple:
        """(crossed, closed, walled) over the board as it stands, confirmed."""
        closed, walled = self.confirmed()
        return self.occ.ratsnest().crossed_pairs(self.depth), len(closed), len(walled)

    # ------------------------------------------------------------ a candidate
    def _at_origin(self, item, placement):
        """The item's pads and its own corridors turned and faced as
        `placement` asks, at the origin: worked out once per turn and face."""
        occ = self.occ
        geom = occ._geometry(item)
        cache = self.__dict__.setdefault("_origin", {})
        key = (id(geom), placement.rotation, placement.face)
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            shapes = [s for s in occ._origin_shapes(item, geom, placement) if s.kind in ("pad", "through")]
            by_ref: dict = {}
            for s in shapes:
                by_ref.setdefault(s.owner, []).append(s)
            own = []
            for ref, ss in by_ref.items():
                pads = _pads_of(ss, ref)
                for group in _group(pad_corridors(occ, ref, pads, placement.rotation, self.depth)):
                    own.append((group, pads[group[0].number][2].center))
            hit = (geom, shapes, own)
            cache[key] = hit
        return hit[1], hit[2]

    def _native_turn(self, item, placement):
        """The mirror's handle on `_at_origin` for this turn."""
        geom = self.occ._geometry(item)
        cache = self.__dict__.setdefault("_turns", {})
        key = (id(geom), placement.rotation, placement.face)
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            pads, groups = self._at_origin(item, placement)
            handle = self.mirror.esc_turn([_metal_tuple(s) for s in pads],
                                          [([_corr_tuple(c, True, centre) for c in group], (centre.x, centre.y))
                                           for group, centre in groups])
            hit = (geom, handle)
            cache[key] = hit
        return hit[1]

    def closed(self, item, placement, crossed: int | None = None) -> tuple:
        """(crossed, closed, walled) that placing `item` at `placement` would
        cause: escapes crossed near a neighbour's pin row, pads whose last
        route toward their target it takes, and pads it walls off - its
        neighbours' pads and its own."""
        from .board_geometry import members_of
        from .occupancy import Shape
        occ = self.occ
        own = frozenset(fp.ref for fp in members_of(item))
        dx, dy = placement.location.x, placement.location.y
        if self.mirror is not None:
            closed, walled = self.mirror.esc_closed(self._native_turn(item, placement), dx, dy, list(own))
            if crossed is None:
                crossed = occ.ratsnest().crossed_escapes(occ.candidate_anchors(item, placement), own, self.depth)
            return crossed, closed, walled
        origin_pads, origin_corr = self._at_origin(item, placement)
        cand = [Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((x + dx, y + dy) for x, y in s.poly),
                      s.box.moved(dx, dy), s.label) for s in origin_pads]
        # its copper against the corridors of what is placed
        taken: dict = {}
        for s in cand:
            for c in self._cgrid.near(s.box):
                if c.ref not in own and self._open.get(id(c)) and self._closes(s, c):
                    taken.setdefault((c.ref, c.number), set()).add(id(c))
        closed = walled = 0
        for (ref, number), gone in taken.items():
            cs = [c for c in self._corr.get(ref, ()) if c.number == number]
            before = [c for c in cs if self._open.get(id(c))]
            after = [c for c in before if id(c) not in gone]
            if before and not after:
                walled += 1
                continue
            at = occ.pad_location(ref, number)
            targets = self._targets(ref, number, cs[0].net, at)
            if any(self._toward(c, targets) for c in before) and not any(self._toward(c, targets) for c in after):
                closed += 1
        # its own pads against what is placed
        rn = occ.ratsnest()
        for group, centre in origin_corr:
            c0 = group[0]
            open_ = []
            for c in group:
                box = c.box.moved(dx, dy)
                poly = None
                shut = False
                for s in self._bgrid.near(box):
                    if s.owner in own or s.net == c0.net or not (s.layers & c.layers) or not s.box.overlaps(box):
                        continue
                    if poly is None:
                        poly = tuple((x + dx, y + dy) for x, y in c.poly)
                    if polys_overlap(s.poly, poly):
                        shut = True
                        break
                if not shut:
                    open_.append(c)
            if not open_:
                walled += 1
                continue
            if c0.net in occ.quiet_nets:
                continue
            near = _nearest(rn, c0.net, Location(centre.x + dx, centre.y + dy), own)
            if near is not None and not any(self._toward(c, [near]) for c in open_):
                closed += 1
        if crossed is None:                 # the scorer passes it, from the leaf search it made anyway
            crossed = rn.crossed_escapes(occ.candidate_anchors(item, placement), own, self.depth)
        return crossed, closed, walled


_CELL_MM = 0.05     # the path search's grid: a quarter of the narrowest track a fab offers


def path_out(occ, ref: str, number: str, depth: float | None = None, toward=None, near=None) -> bool:
    """Whether a track of the pad's net can get out of it: a path, at the
    net's track width and clearance from every other net's copper on the
    pad's layers, from the pad to the edge of a window `depth` round it or
    to a spot where a via fits clear of every other net's copper. With
    `toward` (a direction), only an edge facing that way counts, and a via
    spot still does: the route leaves the layer there. `near` is the copper
    to judge against (default: every placed item's pads and the planned
    copper). Obstacles are taken as their boxes."""
    depth = occ.settings.place_escape_depth if depth is None else depth
    g = occ.items[ref]
    mine = [s for s in g.shapes if s.kind in ("pad", "through") and s.owner == ref and s.label == number]
    if not mine:
        return True
    net = mine[0].net
    layers = frozenset().union(*(s.layers for s in mine))
    pad = Box.union([s.box for s in mine])
    nc = occ.geometry.netclass(net)
    track, via = nc.track_width / 2.0 + nc.clearance, nc.via_diameter / 2.0 + nc.clearance
    win = pad.inflate(depth)
    reach = win.inflate(max(track, via))
    if near is None:
        near = [s for r, h in occ.items.items() if r not in occ.pending for s in h.shapes
                if s.kind in ("pad", "through")] + [s for s in occ.copper if s.kind in ("copper", "through")]
    foes = [s for s in near if (s.net != net or not net) and not (s.owner == ref and s.label == number)
            and s.box.overlaps(reach)]
    walls = [s.box.inflate(track) for s in foes if s.layers & layers]
    vias = [s.box.inflate(via) for s in foes]
    nx = max(1, int(math.ceil(win.width / _CELL_MM)))
    ny = max(1, int(math.ceil(win.height / _CELL_MM)))
    cw, ch = win.width / nx, win.height / ny

    def centre(i, j):
        return win.left + (i + 0.5) * cw, win.top + (j + 0.5) * ch

    def inside(b, x, y):
        return b.left < x < b.right and b.top < y < b.bottom

    blocked = [[False] * ny for _ in range(nx)]
    for b in walls:
        i0, i1 = max(0, int((b.left - win.left) / cw)), min(nx - 1, int((b.right - win.left) / cw))
        j0, j1 = max(0, int((b.top - win.top) / ch)), min(ny - 1, int((b.bottom - win.top) / ch))
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                if not blocked[i][j] and inside(b, *centre(i, j)):
                    blocked[i][j] = True
    start = [(i, j) for i in range(nx) for j in range(ny) if inside(pad, *centre(i, j))]
    seen = set(start)
    todo = list(start)
    cx, cy = pad.center.x, pad.center.y
    while todo:
        i, j = todo.pop()
        x, y = centre(i, j)
        if i in (0, nx - 1) or j in (0, ny - 1):
            if toward is None or toward[0] * (x - cx) + toward[1] * (y - cy) > 0:
                return True
        if not inside(pad, x, y) and not any(inside(b, x, y) for b in vias):
            return True                     # a via fits here
        for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a < nx and 0 <= b < ny and (a, b) not in seen and not blocked[a][b]:
                seen.add((a, b))
                todo.append((a, b))
    return False


_LAYER_BIT = {l: 1 << i for i, l in enumerate(CopperLayer)}      # a copper layer set as the mirror's bits


def _layer_bits(layers) -> int:
    return sum(_LAYER_BIT[l] for l in layers)


def _corr_tuple(c, open_: bool, centre) -> tuple:
    b = c.box
    return (c.ref, c.number, c.net, _layer_bits(c.layers), [tuple(p) for p in c.poly], (b.left, b.top, b.right, b.bottom),
            c.direction, c.via, bool(open_), (centre.x, centre.y))


def _metal_tuple(s) -> tuple:
    b = s.box
    return (s.owner, s.net or "", _layer_bits(s.layers), [tuple(p) for p in s.poly], (b.left, b.top, b.right, b.bottom))


def _group(cs):
    out: dict = {}
    for c in cs:
        out.setdefault(c.number, []).append(c)
    return list(out.values())


def _nearest(rn, net, at, own):
    best = None
    for a in rn._anchors.get(net, ()):
        if a.ref in own:
            continue
        d = (a.x - at.x) ** 2 + (a.y - at.y) ** 2
        if best is None or d < best[0]:
            best = (d, (a.x - at.x, a.y - at.y))
    return None if best is None else best[1]
