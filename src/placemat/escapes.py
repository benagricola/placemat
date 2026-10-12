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
from enum import Enum
import copy
import math
import re
import weakref

from .geometry import point_in_polygon, point_segment_distance, polys_overlap, segments_intersect
from .occupancy import ALLOW_SEP
from .values import Box, CopperLayer, Location

_CELL = 2.0     # mm: the grid corridors and blockers are bucketed into
# A pad the capture declares unconnected carries KiCad's pin type no_connect (`PadGeom.no_connect`): that is what is
# judged. A board without the marker is judged by name: the net a generator gives such a pin is Zener's
# `NC_<part>_<pin>` (under its instance path, `mcu.NC_...`) or KiCad's `unconnected-(<ref>-<pad>)`, and a net local to an
# instance (a dot in its name) with one pad goes nowhere - a cell's own pins for the parent board have the bare name.
_NO_CONNECT = re.compile(r"\.|^NC_|^unconnected-\(")


def is_no_connect(net: str) -> bool:
    """Whether a net's name says its pin is left unconnected: the fallback for a pad without the capture's marker."""
    return bool(_NO_CONNECT.search(net))


from .refusals import Owner  # noqa: E402


def _by(occ, sh):
    """Who a blocking shape is, as a finding names it: its owner as it is, else what blame_owner says (an Owner)."""
    from .refusals import Owner
    return Owner("who", sh.owner) if sh.owner else occ.blame_owner(sh)


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
    """{net: pads on it} over the whole board, counted once. A pad a footprint draws as several elements (one number, a
    shape each) is one pad."""
    sizes = occ.__dict__.get("_net_sizes")
    if sizes is None:
        pads: dict = {}
        for fp in occ.geometry.footprints:
            for p in fp.pads:
                if p.net:
                    pads.setdefault(p.net, set()).add((fp.ref, p.number))
        sizes = {net: len(s) for net, s in pads.items()}
        occ.__dict__["_net_sizes"] = sizes
    return sizes


def _marked(occ) -> set:
    """{(ref, number)} of the pads the capture declares unconnected."""
    marked = occ.__dict__.get("_no_connect_pads")
    if marked is None:
        marked = {(fp.ref, p.number) for fp in occ.geometry.footprints for p in fp.pads if p.no_connect}
        occ.__dict__["_no_connect_pads"] = marked
    return marked


def _unconnected(occ, ref: str, number: str, net: str) -> bool:
    """Whether the pad is one the design leaves unconnected: the capture's marker, else the net's name."""
    return (ref, number) in _marked(occ) or is_no_connect(net)


def pad_corridors(occ, ref: str, pads: dict, rotation: float, depth: float) -> list:
    """Corridors for one part's pads: `pads` maps a pad number to (net,
    layers, box) as the part stands (or would stand)."""
    from .placer import _pin_normal
    if len(pads) < occ.settings.place_escape_min_pads:
        return []
    centres = {(ref, n): b.center for n, (_, _, b) in pads.items()}
    body = Box.union([b for _, _, b in pads.values()]).center
    out = []
    for number, (net, layers, box) in sorted(pads.items()):
        if not net or _net_sizes(occ).get(net, 0) < 2 or (ref, number) in _marked(occ):
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


# ------------------------------------------------------------ surface lanes
# The escape findings and the run score judge a pad by the cheapest way its track can leave it (placemat's own rule, not
# a KiCad rule; docs/superpowers/specs/2026-10-07-surface-escapes-design.md). A surface lane is a straight track of the
# net's class, kept what the exact path search keeps (the class's clearance, and a search cell more) from every other
# net's pads, tracks, vias and pours on any of the pad's layers, and `hole_clearance` from unplated holes. It runs in two
# legs: out of the pin field along the pin's normal (empty for a part of two pads or one), then straight in one of eight
# compass directions to the edge of the search's window, the pad's box grown by `score.escape_reach`. A lane is toward
# the pad's target when its end lies toward the nearest other placed pad of its net, as the search judges its edge. A via spot is a via of the net's class touching the pad's
# edge in each direction a corridor takes (`pad_corridors`), and one where the first leg leaves the pin field (on the
# leg, a via's clearance past the box round the part's other pads); it is clear of every other net's copper on every
# layer, of unplated holes and of via bans. A pad whose own net's copper already leaves it is not judged: its way out is
# made. The lanes are a first check only: where they find no surface way toward the target, the exact path search
# (`path_out(exact=True)`) decides (`Escapes._verdict`), so the judgement is the path search's.
class Way(Enum):
    """A judged pad's cheapest way out (`price`)."""
    SURFACE = "surface"     # a surface lane toward its target
    VIA = "via"             # none, but a via fits beside it
    AWAY = "away"           # neither, but a surface lane another way
    WALLED = "walled"       # none of these


def price(way: Way, settings) -> float:
    """What a pad whose cheapest way out is `way` costs in the run score. A walled pad has no price: it is a critical
    finding, counted in the validity tier (score.Validity), and asking its price is an error."""
    if way is Way.WALLED:
        raise ValueError("a walled pad is counted in the validity tier (score.Validity), not priced")
    return {Way.SURFACE: 0.0, Way.VIA: settings.score_escape_via, Way.AWAY: settings.score_escape_closed}[way]


@dataclass(frozen=True)
class Lane:
    ref: str
    number: str
    net: str
    layers: frozenset
    legs: tuple             # ((a, b), (b', c)): the track's centre line out of the pin field, then on; an empty leg is (p, p)
    box: Box                # round the legs' centre lines
    direction: tuple        # the second leg's unit direction, board frame
    toward_ok: bool = True  # the lane's end lies toward `pad_lanes`'s `toward` from the pad's centre (True without one)


@dataclass(frozen=True)
class ViaSpot:
    ref: str
    number: str
    net: str
    box: Box                # round the via's copper
    circle: tuple           # (x, y, radius) of the via's copper


_COMPASS = tuple((round(math.cos(math.radians(a)), 12) + 0.0, round(math.sin(math.radians(a)), 12) + 0.0)
                 for a in range(0, 360, 45))


def _exit(box: Box, ux: float, uy: float) -> float:
    """How far from the box's centre a ray along (ux, uy) leaves it."""
    tx = box.width / 2.0 / abs(ux) if abs(ux) > 1e-12 else math.inf
    ty = box.height / 2.0 / abs(uy) if abs(uy) > 1e-12 else math.inf
    return min(tx, ty)


def _to_edge(p, u, win: Box) -> float:
    """How far from `p` (inside `win`) a ray along `u` runs to the window's edge; 0 from a point on it or outside."""
    t = math.inf
    for v, k, lo, hi in ((p[0], u[0], win.left, win.right), (p[1], u[1], win.top, win.bottom)):
        if k > 1e-12:
            t = min(t, (hi - v) / k)
        elif k < -1e-12:
            t = min(t, (lo - v) / k)
    return max(0.0, t)


def _poly_exit(c, u, polys) -> float:
    """How far from `c` a ray along `u` first leaves the pad's copper (`polys`, its outlines): where the path search's
    start cells end. 0 when `c` is on none of them."""
    inside = [poly for poly in polys if point_in_polygon(c, poly)]
    if not inside:
        return 0.0
    t = math.inf
    far = (c[0] + u[0] * 1e3, c[1] + u[1] * 1e3)
    for poly in inside:
        n = len(poly)
        for k in range(n):
            (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % n]
            ex, ey = x2 - x1, y2 - y1
            den = u[0] * ey - u[1] * ex
            if abs(den) < 1e-15:
                continue
            tt = ((x1 - c[0]) * ey - (y1 - c[1]) * ex) / den
            ss = ((x1 - c[0]) * u[1] - (y1 - c[1]) * u[0]) / den
            if tt > 0.0 and -1e-12 <= ss <= 1.0 + 1e-12:
                t = min(t, tt)
    return 0.0 if t == math.inf else t


def pad_lanes(occ, ref: str, pads: dict, rotation: float, toward: dict | None = None, polys: dict | None = None) -> tuple:
    """(lanes, via spots) of one part's judged pads: `pads` maps a pad number to (net, layers, box) as the part stands
    (or would stand). A pad is judged when the pad is not left unconnected (`_unconnected`) and its net has two pads or
    more; a pad of a quiet net is judged for walled only (`Escapes._verdict`). `toward` maps a pad number to the
    direction of its target, for each lane's `toward_ok`. `polys` maps a pad number to its copper outlines: each lane
    then starts where its ray from the pad's centre first leaves that copper, so no ground between the copper and the
    lane goes unchecked (the path search starts on the copper itself); without it, at the pad's box. A pad number whose
    centre is on none of its outlines has no lanes; its via spots must touch actual copper.

    The first leg runs from the pad's edge along its pin normal out of the box round the part's other pads, and on
    until a second leg at 45 degrees from its end keeps a lane's reach (half the track and the clearance) from each of
    those pads' corners: on a fine pitch the neighbours' tips stand within that reach of a diagonal from the box's edge.
    A part of two pads or one has no first leg, and its second legs start at the pad's edge in their own direction. The
    second legs run to the edge of the path search's window, the pad's box grown by `score.escape_reach` (`path_out`),
    and a lane is toward the target when its end, seen from the pad's centre, is (as the search judges its edge)."""
    from .placer import _pin_normal
    if len(pads) < occ.settings.place_escape_min_pads:
        return [], []
    centres = {(ref, n): b.center for n, (_, _, b) in pads.items()}
    body = Box.union([b for _, _, b in pads.values()]).center
    reach = occ.settings.score_escape_reach
    sizes = _net_sizes(occ)
    lanes, spots = [], []
    for number, (net, layers, box) in sorted(pads.items()):
        if not net or sizes.get(net, 0) < 2 or _unconnected(occ, ref, number, net):
            continue
        c = box.center
        d = _pin_normal(centres, ref, c, rotation, box)
        if d is None:
            ux, uy = c.x - body.x, c.y - body.y
            n = math.hypot(ux, uy)
            d = (ux / n, uy / n) if n > 1e-9 else (1.0, 0.0)
        d = (round(d[0], 9) + 0.0, round(d[1], 9) + 0.0)
        nc = occ.geometry.netclass(net)
        half = nc.track_width / 2.0 + nc.clearance
        r = nc.via_diameter / 2.0
        own = None if polys is None else polys.get(number)
        # a pad number whose centre is on none of its outlines (an SOT-223's pin and tab, split pads) has no lanes: a lane
        # from the centre of its box would cross ground that is none of its copper, and the path search decides alone
        blind = own is not None and not any(point_in_polygon((c.x, c.y), poly) for poly in own)
        h = _exit(box, *d) if own is None else _poly_exit((c.x, c.y), d, own)
        start = (c.x + d[0] * h, c.y + d[1] * h)
        first = out = 0.0
        if len(pads) > 2:
            others = [b for n, (_, _, b) in pads.items() if n != number]
            first = out = max(0.0, max((qx - start[0]) * d[0] + (qy - start[1]) * d[1]
                                       for qx, qy in _box_poly(Box.union(others))))
            # on until a 45-degree leg from its end keeps a lane's reach from every corner of those pads: a corner
            # `back` behind the end and `side` to one side is (side + back) / sqrt 2 from that leg's centre line
            ex, ey = start[0] + d[0] * first, start[1] + d[1] * first
            more = 0.0
            for b in others:
                for qx, qy in _box_poly(b):
                    along = (qx - ex) * d[0] + (qy - ey) * d[1]
                    side = abs((qx - ex) * d[1] - (qy - ey) * d[0])
                    more = max(more, half * math.sqrt(2.0) - side + along)
            first += more
        win = box.inflate(reach)            # the path search's window (`path_out`): the lanes run to its edge
        end = (start[0] + d[0] * min(first, _to_edge(start, d, win)), start[1] + d[1] * min(first, _to_edge(start, d, win)))
        aim = None if toward is None else toward.get(number)
        field = len(pads) > 2
        for ux, uy in (() if blind else _COMPASS):
            if field:
                a = end
            else:
                e = _exit(box, ux, uy) if own is None else _poly_exit((c.x, c.y), (ux, uy), own)
                a = (c.x + ux * e, c.y + uy * e)
            length = _to_edge(a, (ux, uy), win)
            f = (a[0] + ux * length, a[1] + uy * length)
            legs = ((start, end), (a, f)) if field else ((a, a), (a, f))
            ok = aim is None or (f[0] - c.x) * aim[0] + (f[1] - c.y) * aim[1] > 1e-9
            lanes.append(Lane(ref, number, net, frozenset(layers), legs, Box.of_points([p for leg in legs for p in leg]),
                              (ux, uy), ok))
        dirs = [d]
        if len(pads) <= 2:
            dirs += [(-d[1], d[0]), (d[1], -d[0])]
            if len(pads) == 1:
                dirs.append((-d[0], -d[1]))
        at = [(c.x + ux * (_half(box, ux, uy) + r), c.y + uy * (_half(box, ux, uy) + r)) for ux, uy in dirs]
        if first > 0.0:                     # where the lane leaves the pin field: a via's clearance past its box
            t = max(first, out + r + nc.clearance)
            at.append((start[0] + d[0] * t, start[1] + d[1] * t))
        for x, y in at:
            if blind and not any(
                    _point_poly_distance((x, y), poly) <= r + 1e-9
                    and max(math.hypot(px - x, py - y) for px, py in poly) >= nc.via_drill / 2.0 - 1e-9
                    for poly in own):
                continue
            spots.append(ViaSpot(ref, number, net, Box(x - r, y - r, x + r, y + r), (x, y, r)))
    return lanes, spots


def native_pad_lanes(occ, ref, pads, rotation, toward=None, polys=None):
    """Explicit native lane-generation twin; not selected by live search yet."""
    from .geometry import _native
    if _native is None or not hasattr(_native, 'surface_lanes'):
        raise RuntimeError('native surface lane generator unavailable')
    if len(pads) < occ.settings.place_escape_min_pads:
        return [], []
    sizes = _net_sizes(occ)
    records = []
    layers_by_bits = {}
    for number, (net, layers, box) in sorted(pads.items()):
        bits = _layer_bits(layers)
        layers_by_bits[bits] = frozenset(layers)
        eligible = bool(net and sizes.get(net, 0) >= 2 and not _unconnected(occ, ref, number, net))
        # Unconnected pads still define the pin field. Python pad_lanes skips
        # their class lookup entirely; no class for the empty net is required.
        if eligible:
            nc = occ.geometry.netclass(net)
            params = (nc.track_width / 2.0 + nc.clearance, nc.via_diameter / 2.0,
                      nc.via_drill / 2.0, nc.clearance)
        else:
            params = (0.0, 0.0, 0.0, 0.0)  # unused by the native ineligible-pad branch
        records.append((number, bits, (box.left, box.top, box.right, box.bottom),
                        None if polys is None or number not in polys else [list(poly) for poly in polys[number]], eligible,
                        *params))
    angle = math.radians(rotation)
    raw_lanes, raw_spots = _native.surface_lanes(records, rotation, (math.cos(angle), math.sin(angle)),
                                               occ.settings.score_escape_reach, occ.settings.place_escape_min_pads)
    lanes, spots = [], []
    for number, (legs, bits, bounds), direction in raw_lanes:
        aim = None if toward is None else toward.get(number)
        centre = pads[number][2].center
        end = legs[-1][-1]
        ok = aim is None or (end[0] - centre.x) * aim[0] + (end[1] - centre.y) * aim[1] > 1e-9
        lanes.append(Lane(ref, number, pads[number][0], layers_by_bits[bits], tuple(map(tuple, legs)),
                          Box(*bounds), tuple(direction), ok))
    for number, (point, radius, bounds) in raw_spots:
        spots.append(ViaSpot(ref, number, pads[number][0], Box(*bounds), (*point, radius)))
    return lanes, spots


def _seg_poly_distance(a, b, poly) -> float:
    """The least distance from segment a-b to the polygon, 0 when they meet."""
    if point_in_polygon(a, poly):
        return 0.0
    n = len(poly)
    best = math.inf
    for k in range(n):
        p, q = poly[k], poly[(k + 1) % n]
        if segments_intersect(a, b, p, q):
            return 0.0
        best = min(best, point_segment_distance(p, a, b), point_segment_distance(a, p, q), point_segment_distance(b, p, q))
    return best


def _point_poly_distance(p, poly) -> float:
    if point_in_polygon(p, poly):
        return 0.0
    n = len(poly)
    return min(point_segment_distance(p, poly[k], poly[(k + 1) % n]) for k in range(n))


def _box_gap(a: Box, b: Box) -> float:
    dx = max(a.left - b.right, b.left - a.right, 0.0)
    dy = max(a.top - b.bottom, b.top - a.bottom, 0.0)
    return math.hypot(dx, dy)


def search_near(occ) -> list:
    """The copper the judgement's path search judges against: the placed items' pads and the planned copper, leaving
    out what a pending item owns, read from the board as it stands (a via that gave way included)."""
    return _Near([s for r, h in occ.items.items() if r not in occ.pending for s in h.shapes if s.kind in ("pad", "through")]
                 + [s for s in occ.copper if s.kind in ("copper", "through") and s.owner not in occ.pending], occ)


class _Near(list):
    """`search_near`'s shapes, with what a path search reads of them found by bucket rather than by a pass over all:
    `overlapping` gives the shapes whose boxes overlap a box, and `extra` the holes and bans `extra_walls` gives, each
    in the order a pass over the list (or the board) gives them. Built from `occ` as it stood; `extra` reads the board
    again for any other occupancy."""
    def __init__(self, shapes, occ):
        super().__init__(shapes)
        self.occ = occ
        self._cells = None
        self._walls = None

    def overlapping(self, box: Box) -> list:
        if self._cells is None:
            self._cells = {}
            for i, shape in enumerate(self):
                for c in _cells(shape.box):
                    self._cells.setdefault(c, []).append(i)
        found = set()
        for c in _cells(box):
            found.update(self._cells.get(c, ()))
        return [self[i] for i in sorted(found) if self[i].box.overlaps(box)]

    def extra(self, occ, box: Box, net: str) -> tuple:
        if occ is not self.occ:
            return extra_walls(occ, box, net)
        if self._walls is None:
            self._walls = (
                [s for r, g in occ.items.items() if r not in occ.pending for s in g.shapes if s.kind == "npth"],
                [s for pool in ([occ.copper] + [g.shapes for r, g in occ.items.items() if r not in occ.pending])
                 for s in pool if s.kind == "viaban"])
        holes, bans = self._walls
        return ([s for s in holes if s.box.overlaps(box)],
                [s for s in bans if s.box.overlaps(box) and net not in s.net.split(ALLOW_SEP)])


def judging(occ):
    """The Escapes the escape findings and the run score are judged with: the board's own when it keeps
    `score.escape_depth` (the depth of the walled lanes' and hand-offs' path search), else one at that depth, built
    without corridors (the judgement does not read them). Its exact path searches run in Rust when the native twin is
    built (`native_judge`)."""
    depth = occ.settings.score_escape_depth
    esc = occ.escapes()
    if depth != esc.depth:
        esc = Escapes(occ, mirror=False, depth=depth, corridors=False)
    esc.native_paths = native_judge()
    return esc


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
        """The items in the cells `box` covers, each once, in the order of their cells and then of each cell's list."""
        get = self.cells.get
        x0, x1 = math.floor(box.left / _CELL), math.floor(box.right / _CELL)
        y0, y1 = math.floor(box.top / _CELL), math.floor(box.bottom / _CELL)
        buckets = [b for b in (get((cx, cy)) for cx in range(x0, x1 + 1) for cy in range(y0, y1 + 1)) if b]
        if not buckets:
            return []
        if len(buckets) == 1:
            b = buckets[0]
            if len(set(map(id, b))) == len(b):
                return list(b)
        # The first of each identity keeps its place; a later one rewrites the same object.
        return list({id(x): x for b in buckets for x in b}.values())


class Escapes:
    """The corridors of every placed pad, which are open, and what copper
    closes them; kept as items commit."""

    def __init__(self, occ, mirror: bool = True, depth: float | None = None, corridors: bool = True):
        self.occ = occ
        self.depth = occ.settings.place_escape_depth if depth is None else depth
        # Without corridors the index holds only the blockers and the lanes: what the surface judgement, its
        # supplemental lane and hand-off checks and the findings read. `confirmed`, `count` and `closed` need them.
        self.corridors = corridors
        # The exact path searches (the judgement's, the supplemental lane and hand-off checks') in Rust
        # (`path_out(native=True)`), their twin.
        self.native_paths = False
        self._pairs: dict = {}          # (net, net, owner, wire) -> the pair's clearance (`Occupancy.pair_clearance`)
        self._pairs_of = None           # the rules and geometry `_pairs` was read under
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
        self._lane_cache: dict = {}     # ref -> (lanes, via spots, pads) where it stands: the surface-lane judgement's
        self.searched = 0               # pads the judgement has sent to the path search, its lanes not deciding
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
            self._lane_cache.pop(ref, None)
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
            own = [s for s in g.shapes if s.kind in ("pad", "through", "npth") and s.owner == ref]
            self._blockers[ref] = own
            for s in own:
                self._bgrid.add(s, s.box)
            changed += own
            if not self.corridors:
                continue
            cs = corridors(occ, ref, self.depth)
            self._corr[ref] = cs
            for c in cs:
                self._cgrid.add(c, c.box)
                self._open[id(c)] = self._clear(c)
        if copper:
            metal = [s for s in occ.copper if s.kind in ("copper", "through") and s.owner not in occ.pending]
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
        if not copper:
            self._sync_cell_copper(refs)

    def _sync_cell_copper(self, names) -> None:
        """A cell's own copper (its tracks and vias) stands where the cell stands: when the cell is placed, moved or
        lifted, the copper kept here from where it stood before is taken out and what the occupancy holds now put in.
        Without it a stamped cell's tracks and vias are not seen: a corridor a track crosses reads open, and a pad a
        track leaves reads unjoined."""
        occ = self.occ
        for name in names:
            if name not in occ.geometry.cells:
                continue
            now = [] if name in occ.pending else [s for s in occ.copper if s.owner == name and s.kind in ("copper", "through")]
            held = [s for s in self._blockers.get(":copper", ()) if s.owner == name]
            if len(now) == len(held) and all(a is b for a, b in zip(now, held)):
                continue
            if held:
                self.remove_copper(held)
            if now:
                self.add_copper(now)

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

    def remove_copper(self, shapes) -> None:
        """Copper taken back: the corridors it closed open again where nothing else closes them."""
        gone = {id(s) for s in shapes}
        metal = self._blockers.get(":copper", [])
        self._blockers[":copper"] = [s for s in metal if id(s) not in gone]
        vacated = [s for s in metal if id(s) in gone]
        touched = []
        for s in vacated:
            self._bgrid.remove(s, s.box)
        for s in vacated:
            for c in self._cgrid.near(s.box):
                if not self._open.get(id(c), True) and self._clear(c):
                    self._open[id(c)] = True
                    touched.append(c)
        if self.mirror is not None:
            self.mirror.esc_set_metal(":copper", [_metal_tuple(sh) for sh in self._blockers[":copper"]])
            flags = [(self._nid[id(c)], True) for c in touched if id(c) in self._nid]
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

    # ------------------------------------------------------------ surface lanes
    def _native_paths(self) -> bool:
        """Whether the exact path searches run in Rust: asked for (`native_paths`) and built (`native_judge`)."""
        return self.native_paths and native_judge()

    def _lanes_of(self, ref) -> tuple:
        hit = self._lane_cache.get(ref)
        if hit is None:
            g = self.occ.items[ref]
            pads = _pads_of(g.shapes, ref)
            polys: dict = {}
            for sh in g.shapes:
                if sh.kind in ("pad", "through") and sh.owner == ref:
                    polys.setdefault(sh.label, []).append(sh.poly)
            lanes, spots = pad_lanes(self.occ, ref, pads, g.reference.rotation, polys=polys)
            hit = (lanes, spots, pads)
            self._lane_cache[ref] = hit
        return hit

    def lanes(self, ref: str, number: str) -> list:
        """The pad's surface lanes where it stands (none when it is not judged)."""
        return [l for l in self._lanes_of(ref)[0] if l.number == number]

    def _bans(self) -> list:
        """Every rule area that forbids vias, of the planned copper and the placed parts."""
        occ = self.occ
        return [s for pool in ([occ.copper] + [g.shapes for r, g in occ.items.items() if r not in occ.pending])
                for s in pool if s.kind == "viaban"]

    def _foes(self, box: Box, net: str, ref: str, number: str) -> list:
        """(shape, a lane centre's reach from it, a via centre's reach less the via's radius) of what stands near `box`
        that a lane or via of `net` from pad `ref` `number` keeps clear of: other nets' pads, tracks, vias, pours and
        escape lanes (a script's pour is static copper), and unplated holes.

        A lane keeps what the path search keeps (`path_out`, exact): half the track and the net class's clearance (the
        hole clearance from a hole), less the DRC epsilon, and one search cell more, so a lane found open is a way the
        search's cells find too. A via keeps the pair's clearance, the script's rules included."""
        occ = self.occ
        geom = occ.geometry
        nc = geom.netclass(net)
        track = nc.track_width / 2.0 + nc.clearance
        eps = geom.drc_epsilon
        cell = occ.settings.place_escape_cell
        if self._pairs_of is None or self._pairs_of[0] is not occ.rules or self._pairs_of[1] is not occ.geometry:
            self._pairs, self._pairs_of = {}, (occ.rules, occ.geometry)
        pairs = self._pairs
        hole = (max(track + geom.hole_clearance - nc.clearance - eps, 0.0) + cell, geom.hole_clearance - eps)
        reach = max(track - eps, 0.0) + cell
        out = []
        for s in self._bgrid.near(box):
            kind = s.kind
            if kind == "npth":
                out.append((s, *hole))
            elif (kind in ("pad", "through", "copper") and (s.net != net or not net)
                  and not (s.owner == ref and s.label == number)):
                key = net, s.net, s.owner, s.wire
                clr = pairs.get(key)
                if clr is None:
                    clr = pairs[key] = occ.pair_clearance(net, s.net, "", s.owner, True, s.wire)[0]
                out.append((s, reach, clr - eps))
        return out

    def _lane_blocked(self, lane: Lane, foes) -> list:
        """The foes that close the lane: any on one of the pad's layers (a hole on every layer) within its reach, as the
        path search walls a cell. The lane is open when this is empty."""
        out = []
        for s, reach, _ in foes:
            if s.kind != "npth" and not (s.layers & lane.layers):
                continue
            if _box_gap(s.box, lane.box) >= reach:
                continue
            if any(_seg_poly_distance(a, b, s.poly) < reach for a, b in lane.legs):
                out.append(s)
        return out

    def _spot_blocked(self, spot: ViaSpot, foes, bans) -> list:
        x, y, r = spot.circle
        out = []
        for s, _, clr in foes:
            if _box_gap(s.box, spot.box) < clr and _point_poly_distance((x, y), s.poly) < r + clr:
                out.append(s)
        for s in bans:
            if s.box.overlaps(spot.box) and spot.net not in s.net.split(ALLOW_SEP) \
                    and _point_poly_distance((x, y), s.poly) < r:
                out.append(s)
        return out

    def lane_open(self, lane: Lane) -> bool:
        """Whether nothing closes the lane where the board stands."""
        return not self._lane_blocked(lane, self._foes(self._reach(lane.box, lane.net), lane.net, lane.ref, lane.number))

    def _reach(self, box: Box, net: str) -> Box:
        """`box` grown by as far as any foe can reach a track or via of `net`."""
        geom = self.occ.geometry
        nc = geom.netclass(net)
        rules = self.occ.rules.largest() if self.occ.rules else 0.0
        clr = max(nc.clearance, geom.hole_clearance, rules,
                  max([c.clearance for c in geom.netclasses.values()], default=0.0))
        return box.inflate(max(nc.track_width / 2.0, nc.via_diameter / 2.0) + clr)

    def _aim(self, ref: str, number: str, net: str, at: Location):
        """The direction from the pad to the nearest other placed pad of its net, None when there is none."""
        best = None
        for a in self.occ.ratsnest()._anchors.get(net, ()):
            if (a.ref, a.number) == (ref, number):
                continue
            d = (a.x - at.x) ** 2 + (a.y - at.y) ** 2
            if best is None or d < best[0]:
                best = (d, (a.x - at.x, a.y - at.y))
        return None if best is None else best[1]

    def _verdict(self, ref: str, number: str, bans, near=None, *, native=False) -> tuple | None:
        """(way, what blocks) for one pad, None when it is not judged: it is unconnected, its net has no other pad placed,
        or copper of its own net (planned copper, another part's pad) already leaves it: its way out is made.

        The exact path search (`path_out(exact=True)`, a window `score.escape_reach` round the pad) decides, in the
        order of the prices: a surface route toward the target is SURFACE, else an open via spot VIA, else a surface
        route any way AWAY, else WALLED. The lanes are a first check only: an open lane toward the target is SURFACE,
        an open lane any way passes the third test, without the search. A pad of a quiet net (a plane's, a free net's)
        drops to the plane by a via: it is judged for walled only, and is not reported (None) when a via spot or a
        surface route any way is open."""
        lanes_all, spots_all, pads = self._lanes_of(ref)
        lanes = [l for l in lanes_all if l.number == number]
        spots = [p for p in spots_all if p.number == number]
        occ = self.occ
        pad = pads.get(number)
        if pad is None or len(pads) < occ.settings.place_escape_min_pads:
            return None
        net = pad[0]
        if not net or _net_sizes(occ).get(net, 0) < 2 or _unconnected(occ, ref, number, net):
            return None
        quiet = net in occ.quiet_nets
        aim = None
        if not quiet:
            aim = self._aim(ref, number, net, pads[number][2].center)
            if aim is None:
                return None
        if self._joined(ref, number, net) or self._on_own_net_pad(ref, number, net):
            return None
        region = Box.union([pads[number][2]] + [l.box for l in lanes] + [p.box for p in spots])
        foes = self._foes(self._reach(region, net), net, ref, number)
        if native:
            return self._native_way(ref, number, net, pads[number][2].center, aim, quiet,
                                    lanes, spots, foes, bans, near), []
        shut = {id(l): self._lane_blocked(l, foes) for l in lanes}
        reach = occ.settings.score_escape_reach

        near = search_near(occ) if near is None else near

        def search(toward) -> bool:
            return bool(path_out(occ, ref, number, depth=reach, toward=toward, near=near, exact=True, via_exit=False,
                                 native=self._native_paths()))
        if not quiet:
            toward = self._toward_lanes(lanes, aim, pads[number][2].center)
            if any(not shut[id(l)] for l in toward):
                return Way.SURFACE, []
            self.searched += 1
            if search(aim if abs(aim[0]) + abs(aim[1]) >= 1e-12 else None):
                return Way.SURFACE, []
            by = {_by(occ, s) for l in toward for s in shut[id(l)]}
        else:
            by = set()
        spot_shut = [self._spot_blocked(p, foes, bans) for p in spots]
        if any(not b for b in spot_shut):
            if quiet:
                return None
            way = Way.VIA
        elif any(not shut[id(l)] for l in lanes) or search(None):
            if quiet:
                return None
            way = Way.AWAY
        else:
            way = Way.WALLED
            by |= {_by(occ, s) for l in lanes for s in shut[id(l)]}
            by |= {_by(occ, s) if s.kind != "viaban" else Owner("who", s.owner) for b in spot_shut for s in b}
        named = sorted(by, key=str)
        return way, [b for b in named if str(b) != ref] or named

    def _native_way(self, ref, number, net, centre, aim, quiet, lanes, spots, foes, bans, near):
        """Classification twin only; diagnostic blockers still use Python."""
        from .geometry import _native
        if _native is None or not hasattr(_native, 'surface_judge'):
            raise RuntimeError('native surface escape judge unavailable')
        occ = self.occ
        mine = [s for s in occ.items[ref].shapes if s.kind in ('pad', 'through')
                and s.owner == ref and s.label == number]
        layers = frozenset().union(*(s.layers for s in mine))
        win = Box.union(s.box for s in mine).inflate(occ.settings.score_escape_reach)
        nc = occ.geometry.netclass(net)
        track, via = nc.track_width / 2 + nc.clearance, nc.via_diameter / 2 + nc.clearance
        reach = win.inflate(max(track, via))
        near = search_near(occ) if near is None else near
        near_reach = near.overlapping(reach) if isinstance(near, _Near) else near
        walls = [s for s in near_reach if (s.net != net or not net) and not (s.owner == ref and s.label == number)
                 and s.kind != 'npth' and s.box.overlaps(reach)]
        holes, path_bans = near.extra(occ, reach, net) if isinstance(near, _Near) else extra_walls(occ, reach, net)
        delta = {id(s): occ.geometry.hole_clearance - nc.clearance for s in holes}
        delta.update({id(s): -nc.clearance for s in path_bans})
        def bounds(b):
            return b.left, b.top, b.right, b.bottom
        def shape(s):
            return _surface_shape(s, delta.get(id(s), 0.0))
        if not delta:
            shape = _surface_shape
        path = ([shape(s) for s in mine], [shape(s) for s in walls + holes], _layer_bits(layers),
                bounds(win), track, via, aim, [shape(s) for s in path_bans],
                occ.settings.place_escape_cell, occ.geometry.drc_epsilon, False)
        result = _native.surface_judge(
            [(list(l.legs), _layer_bits(l.layers), bounds(l.box)) for l in lanes],
            [((s.circle[0], s.circle[1]), s.circle[2], bounds(s.box)) for s in spots],
            [(shape(s), lane, clearance, s.kind == 'npth') for s, lane, clearance in foes],
            [shape(s) for s in bans if net not in s.net.split(ALLOW_SEP)],
            aim, (centre.x, centre.y), quiet, path)
        return (Way.SURFACE, Way.VIA, Way.AWAY, Way.WALLED, None)[result]

    def judge_native(self, ref, number):
        """Explicit classification parity entry point, not adopted by search."""
        result = self._verdict(ref, number, self._bans(), search_near(self.occ), native=True)
        return None if result is None else result[0]

    def _toward_lanes(self, lanes, aim, centre) -> list:
        """The lanes whose end lies toward `aim` from the pad's centre, as the path search judges an edge cell, by one
        search cell to spare (a cell's centre stands up to half a cell from the end); every lane when `aim` is nil."""
        n = math.hypot(*aim)
        if n < 1e-12:
            return list(lanes)
        cell = self.occ.settings.place_escape_cell
        return [l for l in lanes
                if ((l.legs[1][1][0] - centre.x) * aim[0] + (l.legs[1][1][1] - centre.y) * aim[1]) / n > cell]

    def lane_check(self, ref: str, number: str) -> tuple:
        """(an open lane toward the target, an open lane any way, the direction to the target) for one pad, where the
        board stands: the first check `_verdict` makes before the path search. None when the pad has no lanes or no
        target."""
        lanes_all, _, pads = self._lanes_of(ref)
        lanes = [l for l in lanes_all if l.number == number]
        if not lanes:
            return None
        net = lanes[0].net
        centre = pads[number][2].center
        aim = self._aim(ref, number, net, centre)
        if aim is None:
            return None
        foes = self._foes(self._reach(Box.union([l.box for l in lanes]), net), net, ref, number)
        open_ = [l for l in lanes if not self._lane_blocked(l, foes)]
        return bool(set(map(id, open_)) & set(map(id, self._toward_lanes(lanes, aim, centre)))), bool(open_), aim

    def _on_own_net_pad(self, ref: str, number: str, net: str) -> bool:
        """Whether another part's pad of the pad's own net stands on it (a pad on a net tie's pad): joined already."""
        for p in self._blockers.get(ref, ()):
            if p.label != number:
                continue
            for s in self._bgrid.near(p.box):
                if (s.kind in ("pad", "through") and s.net == net and s.owner != ref and s.layers & p.layers
                        and s.box.overlaps(p.box) and polys_overlap(s.poly, p.poly)):
                    return True
        return False

    def judge(self, ref: str, number: str) -> Way | None:
        """The pad's cheapest way out where the board stands, None when it is not judged."""
        v = self._verdict(ref, number, self._bans(), search_near(self.occ))
        return None if v is None else v[0]

    def judged(self) -> list:
        """(ref, number, net, way, what blocks) of every judged pad on the board as it stands, by ref and pad number."""
        occ = self.occ
        bans = self._bans()
        near = search_near(occ)
        self.searched = 0
        out = []
        for ref in sorted(occ.items):
            if ref in occ.pending or not occ.geometry.has_footprint(ref):
                continue
            for number, (net, _, _) in self._lanes_of(ref)[2].items():
                v = self._verdict(ref, number, bans, near)
                if v is not None:
                    out.append((ref, number, net, v[0], v[1]))
        return out

    def found(self) -> dict:
        """The escape findings' records over the board as it stands, by kind: `escape_crossed` (part, edge, edge)
        crossed within this Escapes' depth; `escape_via` (ref, number, net, by); `escape_closed` (ref, number, net, by,
        joins); `escape_walled` (ref, number, net, by, variant): a pad judged walled, a declared lane that runs out
        (`lanes_walled`) or a hand-off pin walled in (`handoffs_walled`, variant "handoff")."""
        via, closed, walled = [], [], []
        for ref, number, net, way, by in self.judged():
            if way is Way.VIA:
                via.append((ref, number, net, by))
            elif way is Way.AWAY:
                closed.append((ref, number, net, by, self._joins(ref, number, net)))
            elif way is Way.WALLED:
                walled.append((ref, number, net, by, "walled"))
        seen = {(w[0], w[1]) for w in walled}
        walled += [(r, n, net, by, "walled") for r, n, net, by, _ in self.lanes_walled() if (r, n) not in seen]
        walled += [(r, n, net, by, "handoff") for r, n, net, by in self.handoffs_walled()]
        return {"escape_crossed": self.occ.ratsnest().crossed_pair_list(self.depth), "escape_via": via,
                "escape_closed": closed, "escape_walled": walled}

    def counts(self, ways=None) -> dict:
        """Raw counts, including declared lanes and handoffs independently.

        `ways` may supply a complete per-pad classification snapshot; default
        judgement remains the full Python oracle used by findings.
        """
        if ways is None:
            ways = {(r, n): way for r, n, _, way, _ in self.judged()}
        walls = {key for key, way in ways.items() if way is Way.WALLED}
        return {'escape_crossed': self.occ.ratsnest().crossed_pairs(self.depth),
                'escape_via': sum(way is Way.VIA for way in ways.values()),
                'escape_closed': sum(way is Way.AWAY for way in ways.values()),
                'escape_walled': len(walls) + sum((r, n) not in walls for r, n, *_ in self.lanes_walled())
                                 + len(self.handoffs_walled())}

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
                if self._joined(ref, c0.number, c0.net):
                    continue
                pad = Box.union([c.box for c in group])
                near = list(self._bgrid.near(pad.inflate(self.depth + 1.0)))
                by = sorted({_by(occ, sh) for c in group for sh in self._bgrid.near(c.box)
                             if self._closes_any(sh, c)}, key=str)
                if not open_ and not self._gets_out(ref, c0.number, near):
                    by = sorted(set(by) | self._holes_and_bans(pad.inflate(self.depth), c0.net, c0.layers), key=str)
                    walled.append((ref, c0.number, c0.net, by, []))
                    continue
                if targets and not any(self._gets_out(ref, c0.number, near, toward=t) for t in targets):
                    closed.append((ref, c0.number, c0.net, by, self._joins(ref, c0.number, c0.net)))
        seen = {(w[0], w[1]) for w in walled}
        walled += [w for w in self.lanes_walled() if (w[0], w[1]) not in seen]
        return closed, walled

    def _gets_out(self, ref: str, number: str, near, toward=None) -> bool:
        """Whether a track or via gets out of the pad: the path search on the obstacles' boxes, and when that finds none,
        on the shapes themselves. A box says a pad is walled where a diagonal track or pour whose box covers it leaves it
        room, and a finding is only made on what is there."""
        occ = self.occ
        return (path_out(occ, ref, number, self.depth, toward=toward, near=near)
                or path_out(occ, ref, number, self.depth, toward=toward, near=near, exact=True))

    def vias_unneeded(self, pins, frame: Box) -> list:
        """The vias on the lanes of `pins` ((ref, number) pairs: a module's escaped pins) that the lane does not need:
        copper of the pad's own net stands on it and ends in a via, and with the via taken away the pad and that copper
        still have a track's way to the edge of `frame` on the pad's own layers. Each as (ref, number, net, layers, the via
        shapes). A pad of a plane or free net (`occ.quiet_nets`) is left out: its via is a drop into the plane, not an
        escape. So is one whose copper runs on into another pad of its net, a route made inside the frame."""
        occ = self.occ
        out = []
        for ref, number in pins:
            g = occ.items.get(ref)
            if g is None or ref in occ.pending:
                continue
            pad = _pads_of(g.shapes, ref).get(number)
            if pad is None:
                continue
            net, layers, _ = pad
            if not net or net in occ.quiet_nets or _unconnected(occ, ref, number, net):
                continue
            chain = self._own_copper(ref, number, net)
            vias = [s for s in chain if s.kind == "through"]
            if not vias or self._runs_on(chain, ref, number, net):
                continue
            own = [s for s in chain if s.kind != "through"]
            if path_out(occ, ref, number, own=own, exact=True, via_exit=False, window=frame):
                out.append((ref, number, net, layers, vias))
        return out

    def handoffs_walled(self) -> list:
        """The pads of nets with no other pad on the board - the net leaves the board there, as a cell's pin does for the
        parent board - that no track or via gets out of: (ref, number, net, what closes it). Such a pad keeps no corridor in
        the placement search (`pad_corridors`: it has nothing to join), so what walls it in is reported once the copper is
        planned. Copper of the pad's own net that stands on it (a stub, an escape's lane) is part of it: the way out is
        looked for from where that copper ends, and a via on it is a way out made."""
        out = []
        for ref, pads in self._judged_fields():
            for number, (net, layers, box) in sorted(pads.items()):
                by = self._handoff_walled(ref, number, net, layers, box)
                if by is not None:
                    out.append((ref, number, net, by))
        return out

    def _judged_fields(self):
        """(ref, pads) of each placed footprint whose pads the escape judgement looks at: at least
        `place.escape_min_pads` of them, by ref."""
        occ = self.occ
        for ref, g in sorted(occ.items.items()):
            if ref in occ.pending or not occ.geometry.has_footprint(ref):
                continue
            pads = _pads_of(g.shapes, ref)
            if len(pads) >= occ.settings.place_escape_min_pads:
                yield ref, pads

    def _handoff_walled(self, ref: str, number: str, net: str, layers, box, *, blame: bool = True):
        """What walls in one pad of `handoffs_walled`, None when it is not such a pad or gets out. `blame` off: an empty
        list for a walled pad, without naming what walls it."""
        occ = self.occ
        if not net or _net_sizes(occ).get(net, 0) >= 2 or _unconnected(occ, ref, number, net):
            return None
        own = self._own_copper(ref, number, net)
        if any(s.kind == "through" for s in own):
            return None                                     # a via is on it: its way out is made
        reach = Box.union([box] + [s.box for s in own])
        near = list(self._bgrid.near(reach.inflate(self.depth + 1.0)))
        if not own and path_out(occ, ref, number, self.depth, near=near):
            return None                     # not even the foes' boxes wall it
        if path_out(occ, ref, number, self.depth, near=near, own=own, exact=True,
                    via_exit=occ.settings.place_escape_lane_via_exit, native=self._native_paths()):
            return None
        if not blame:
            return []
        window = reach.inflate(self.depth)
        by = sorted({_by(occ, sh) for sh in near
                     if (sh.net != net or not net) and not (sh.owner == ref and sh.label == number)
                     and sh.layers & layers and sh.box.overlaps(window)} | self._holes_and_bans(window, net, layers),
                    key=str)
        return [b for b in by if str(b) != ref] or by

    def lanes_walled(self) -> list:
        """The pads of nets with other pads whose escape lane (`board.escape`) runs out against copper: (ref, number, net,
        what closes it, []). A lane is the pad's way out, so the pad counts as joined while the lane has room to go on; the
        way on is looked for from where the pad's own copper ends, among the copper of every other net on the pad's layers
        (a through-hole pad on every layer it spans). A lane that goes on into another pad of the net, a via or a pour is
        made, and a track the script drew from a pad with no lane is the script's. (A pad whose net has no other pad is
        `handoffs_walled`'s.)"""
        out = []
        for ref, pads in self._judged_fields():
            for number, (net, layers, box) in sorted(pads.items()):
                by = self._lane_walled(ref, number, net, layers, box)
                if by is not None:
                    out.append((ref, number, net, by, []))
        return out

    def _lane_walled(self, ref: str, number: str, net: str, layers, box, *, blame: bool = True):
        """What closes one pad's declared lane (`lanes_walled`), None when the pad has no such lane or it goes on.
        `blame` off: an empty list for a lane that runs out, without naming what closes it."""
        occ = self.occ
        if not net or _net_sizes(occ).get(net, 0) < 2:
            return None
        own = self._own_copper(ref, number, net)
        if not own or any(s.kind == "through" or not (s.lane or s.wire) for s in own):
            return None
        if self._runs_on(own, ref, number, net):
            return None
        reach = Box.union([box] + [s.box for s in own])
        near = list(self._bgrid.near(reach.inflate(self.depth + 1.0)))
        if path_out(occ, ref, number, self.depth, near=near, own=own, exact=True,
                    via_exit=occ.settings.place_escape_lane_via_exit, native=self._native_paths()):
            return None
        if not blame:
            return []
        window = reach.inflate(self.depth)
        by = sorted({_by(occ, sh) for sh in near
                     if sh.net != net and not (sh.owner == ref and sh.label == number)
                     and sh.layers & layers and sh.box.overlaps(window)} | self._holes_and_bans(window, net, layers),
                    key=str)
        return [b for b in by if str(b) != ref] or by

    def _runs_on(self, own, ref: str, number: str, net: str) -> bool:
        """Whether copper of the pad's own chain stands on another pad of its net: the route is made."""
        for s in own:
            for p in self._bgrid.near(s.box):
                if (p.kind in ("pad", "through") and p.net == net and self.occ.geometry.has_footprint(p.owner)
                        and not (p.owner == ref and p.label == number) and p.layers & s.layers
                        and s.box.overlaps(p.box) and polys_overlap(s.poly, p.poly)):
                    return True
        return False

    def _holes_and_bans(self, window: Box, net: str, layers) -> set:
        """The names of the unplated holes and via bans in `window` a path out of a pad on `net` and `layers` meets."""
        holes, bans = extra_walls(self.occ, window, net)
        return {Owner("who", h.owner) for h in holes} | {Owner("who", b.owner) for b in bans}

    def _own_copper(self, ref: str, number: str, net: str) -> list:
        """The copper of the pad's own net that stands on it, and on that copper in turn: a chain of tracks (and vias) as
        far as it goes, on the pad's layers."""
        mine = [p for p in self._blockers.get(ref, ()) if p.label == number]
        chain: list = []
        seen: set = set()                   # id() of each piece in the chain: a pour's pieces make the chain long
        todo = list(mine)
        while todo:
            at = todo.pop()
            for s in self._bgrid.near(at.box):
                if (id(s) not in seen and s.net == net and s.kind in ("copper", "through")
                        and not self.occ.geometry.has_footprint(s.owner) and any(s.layers & p.layers for p in mine)
                        and s.box.overlaps(at.box) and polys_overlap(s.poly, at.poly)):
                    seen.add(id(s))
                    chain.append(s)
                    todo.append(s)
        return chain

    def _joined(self, ref: str, number: str, net: str) -> bool:
        """Whether copper of the pad's own net already leaves it: a track from it, a via in
        it, a pour over it. Its way out is made."""
        occ = self.occ
        for p in self._blockers.get(ref, ()):
            if p.label != number:
                continue
            for s in self._bgrid.near(p.box):
                if (s.net == net and s.kind in ("copper", "through") and s.layers & p.layers
                        and not occ.geometry.has_footprint(s.owner) and s.box.overlaps(p.box)
                        and polys_overlap(s.poly, p.poly)):
                    return True
        return False

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
            shapes = [s for s in occ._origin_shapes(item, geom, placement) if s.kind in ("pad", "through", "npth")]
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


class _OverlayGrid:
    """Read-only rest index plus one candidate's independently indexed metal."""
    def __init__(self, rest, added):
        self.rest = rest
        self.added = _Grid()
        for shape in added:
            self.added.add(shape, shape.box)

    def near(self, box):
        yield from self.rest.near(box)
        yield from self.added.near(box)


class EscapeDelta:
    """Conservative affected-pad twin for one already-lifted rest board.

    Old moving geometry is absent before this snapshot is built. A different
    net's pad is skipped only when every lane/spot, exact-search window and
    own-copper chain, with maximal foe reach, misses all added geometry.
    All pads of touched signal nets are rejudged: raw nearest targets and
    joins can change without an MST endpoint changing. A pad's supplemental lane and
    hand-off validity is rechecked under the same proof, with its region
    grown by the margin the native rest cache keeps (`WALL_MARGIN`).

    The rest board's verdicts are judged as a candidate first needs them:
    `difference` reads only the pads it rejudges, so a caller comparing
    candidates never judges the whole rest board. `ways` and `counts` judge
    every pad, once. `native` judges the rest board's pads with the native
    twins (classification and exact path search), as `change(native=True)`
    judges a candidate's.
    """
    WALL_MARGIN = 3.0

    def __init__(self, occ, own, *, native=False):
        self.occ, self.own = occ, frozenset(own)
        self._revision = occ.__dict__.get('_score_revision', 0)
        self._pending, self._frame = frozenset(occ.pending), occ.board_box
        if not self.own <= occ.pending:
            raise ValueError('EscapeDelta requires the moving item to be lifted')
        # Own index/caches: later verification commits cannot refresh this
        # snapshot through the live occupancy's Escapes object.
        self.base = Escapes(occ, mirror=False, depth=occ.settings.score_escape_depth, corridors=False)
        self.base.native_paths = self.native = native
        # Pair clearances come from the rules and the geometry: every lifted board of the occupancy shares them.
        pairs = _PAIRS.get(occ)
        if pairs is None or pairs[0] is not occ.rules or pairs[1] is not occ.geometry:
            pairs = _PAIRS[occ] = (occ.rules, occ.geometry, {})
        self.base._pairs, self.base._pairs_of = pairs[2], (occ.rules, occ.geometry)
        self.regions, self.nets = {}, {}
        # What earlier lifted boards of this occupancy judged, still true of this one (`_BaselineMemo`).
        self._memo = _baseline_memo(occ, native) if BASELINE_MEMO else None
        self._generation = self._memo.generation if self._memo is not None else None
        known = self._memo.pads if self._memo is not None else {}
        self._known = {}
        for ref in sorted(occ.items):
            if ref in occ.pending or not occ.geometry.has_footprint(ref):
                continue
            if self._memo is not None:
                self._memo.lanes_into(self.base, ref)
            lanes, spots, pads = self.base._lanes_of(ref)
            if self._memo is not None:
                self._memo.keep_lanes(self.base, ref)
            for number, (net, _, box) in pads.items():
                # Netless pads have no escape verdict, but remain physical
                # blockers in the base and candidate geometry indexes.
                if not net:
                    continue
                key = ref, number
                self.nets[key] = net
                entry = known.get(key)
                if entry is not None:
                    self.regions[key] = entry['region']
                    self._known[key] = entry
                    continue
                chain = self.base._own_copper(ref, number, net)
                boxes = [box.inflate(max(self.base.depth, occ.settings.score_escape_reach))]
                boxes += [l.box for l in lanes if l.number == number]
                boxes += [s.box for s in spots if s.number == number]
                if chain:
                    boxes.append(Box.union([box] + [s.box for s in chain]).inflate(self.base.depth))
                # Includes class/rule/hole clearance and the extra search cell
                # of the lane subset predicate. This is deliberately broad.
                self.regions[key] = self.base._reach(Box.union(boxes), net).inflate(occ.settings.place_escape_cell)
        self._wall_regions = {key: region.inflate(self.WALL_MARGIN) for key, region in self.regions.items()}
        if self._memo is not None:
            for key, net in self.nets.items():
                if key not in self._known:
                    self._known[key] = self._memo.add(key, net, self.regions[key], self._wall_regions[key])
        self._ways, self._walls = {}, {}
        self._judging = None
        self._crossed = None
        self._counts = None

    def _base_way(self, key):
        if key not in self._ways:
            entry = self._known.get(key)
            aim = self._aim_of(key) if entry is not None and self.nets[key] not in self.occ.quiet_nets else None
            if entry is not None and 'way' in entry and (not entry.get('stale') or entry.get('aim') == aim):
                self._ways[key] = entry['way']
            else:
                # An earlier board's verdict for this pad, judged with the same shapes on its region and the same
                # target (`_BaselineMemo.earlier`), while the memo stands at this board.
                here = self._memo is not None and self._memo.generation == self._generation
                if here:
                    target = (aim if entry is not None else self._aim_of(key)) \
                        if self.nets[key] not in self.occ.quiet_nets else None
                    members = self._memo.members(self.regions[key])
                    found = self._memo.earlier(key, members, target)
                if here and found is not None:
                    self._ways[key] = found[0]
                else:
                    if self._judging is None:
                        self._judging = self.base._bans(), search_near(self.occ)
                    verdict = self.base._verdict(*key, *self._judging, native=self.native)
                    self._ways[key] = None if verdict is None else verdict[0]
                    if here:
                        self._memo.keep(key, members, target, self._ways[key])
                if entry is not None and (not entry.get('stale') or self._memo.generation == self._generation):
                    entry.update(way=self._ways[key], aim=aim, stale=False)
        return self._ways[key]

    def _aim_of(self, key):
        """The pad's target as `Escapes._verdict` takes it, where the board stands (None when it has none)."""
        pads = self.base._lanes_of(key[0])[2]
        return self.base._aim(key[0], key[1], self.nets[key], pads[key[1]][2].center)

    def _base_walls(self, key):
        if key not in self._walls:
            entry = self._known.get(key)
            if entry is not None and 'walls' in entry:
                self._walls[key] = entry['walls']
            else:
                self._walls[key] = _wall_flags(self.base, *key)
                if entry is not None:
                    entry['walls'] = self._walls[key]
        return self._walls[key]

    @property
    def ways(self) -> dict:
        """Every judged rest pad's way (None when it is not judged), by (ref, number)."""
        return {key: self._base_way(key) for key in self.nets}

    @property
    def counts(self) -> dict:
        """The rest board's raw escape counts, as `Escapes.counts` gives them."""
        if self._counts is None:
            ways = self.ways
            counts = {'escape_crossed': self._base_crossed(), 'escape_via': 0, 'escape_closed': 0, 'escape_walled': 0}
            for key, way in ways.items():
                _add(counts, way, self._base_walls(key), 1)
            self._counts = counts
        return self._counts

    def _base_crossed(self):
        if self._crossed is None:
            self._crossed = self.occ.ratsnest().crossed_pairs(self.base.depth)
        return self._crossed

    def _check(self):
        if not self.own <= self.occ.pending:
            raise ValueError('EscapeDelta snapshot requires the moving item to remain lifted')
        if self.occ.__dict__.get('_score_revision', 0) != self._revision:
            raise ValueError('EscapeDelta occupancy changed; rebuild the lifted snapshot')
        if frozenset(self.occ.pending) != self._pending or self.occ.board_box != self._frame:
            raise ValueError('EscapeDelta pending geometry or frame changed; rebuild the lifted snapshot')

    def difference(self, view, geometries, copper, *, native=False):
        """(signed raw count changes from the rest board to the candidate, pads rejudged).

        `native` uses the proved native classification twin, and the native
        exact path search for the supplemental lane and hand-off checks;
        snapshot assembly still runs in Python. It is a hybrid parity entry
        point, not the final prepared native candidate kernel.
        """
        self._check()
        esc = copy.copy(self.base)
        esc.occ, esc.mirror, esc.searched, esc.native_paths = view, None, 0, native
        esc._lane_cache = dict(self.base._lane_cache)
        esc._blockers = dict(self.base._blockers)
        added = []
        candidate_shapes = list(copper)
        for ref, geometry in geometries.items():
            esc._lane_cache.pop(ref, None)
            shapes = [s for s in geometry.shapes if s.owner == ref and s.kind in ('pad', 'through', 'npth')]
            esc._blockers[ref] = shapes
            added += shapes
            candidate_shapes += [s for s in geometry.shapes if s.kind in ('pad', 'through', 'npth', 'copper', 'viaban')]
        metal = [s for s in copper if s.kind in ('copper', 'through')]
        esc._blockers[':copper'] = self.base._blockers.get(':copper', []) + metal
        added += metal
        esc._bgrid = _OverlayGrid(self.base._bgrid, added)
        # A quiet net's pad takes no target (it is judged for walled only): a candidate on its net changes its verdict
        # only by standing on or near it, which the region test sees.
        touched = {s.net for s in candidate_shapes if s.net and s.net not in self.occ.quiet_nets}
        boxes = [s.box for s in candidate_shapes]
        selected, walls = set(), set()
        for key, net in self.nets.items():
            region = self.regions[key]
            if net in touched or any(region.overlaps(b) for b in boxes):
                selected.add(key)
                walls.add(key)
            elif any(self._wall_regions[key].overlaps(b) for b in boxes):
                walls.add(key)
        moving = {(ref, number) for ref in geometries for number in esc._lanes_of(ref)[2]}
        out = {'escape_crossed': view.ratsnest().crossed_pairs(esc.depth) - self._base_crossed(),
               'escape_via': 0, 'escape_closed': 0, 'escape_walled': 0}
        bans, near = esc._bans(), search_near(view)
        for key in sorted(selected | walls | moving):
            if key in moving:
                before_way, before_walls = None, (False, False)
            else:
                before_way, before_walls = self._base_way(key), self._base_walls(key)
            way, flags = before_way, before_walls
            if key in selected or key in moving:
                verdict = esc._verdict(*key, bans, near, native=native)
                way = None if verdict is None else verdict[0]
            if key in walls or key in moving:
                flags = _wall_flags(esc, *key)
            _add(out, before_way, before_walls, -1)
            _add(out, way, flags, 1)
        return out, len(selected | moving)

    def change(self, view, geometries, copper, *, native=False):
        """Return candidate counts and number of rejudged pads, signed by caller."""
        difference, rejudged = self.difference(view, geometries, copper, native=native)
        return {kind: self.counts[kind] + value for kind, value in difference.items()}, rejudged


# Whether lifted boards share what they judged of their rest pads (`_BaselineMemo`): False measures without it (a
# measurement switch, as placer.NATIVE_SWEEP is; never a setting).
BASELINE_MEMO = True
_BASELINES = None
_PAIRS = weakref.WeakKeyDictionary()     # occupancy -> (its rules, its geometry, `Escapes._pairs` under them)


class _BaselineMemo:
    """What `EscapeDelta` judges of a lifted board's rest pads, kept from one lifted board of an occupancy to the next:
    each part's lanes, via spots and pads (`Escapes._lanes_of`, read from its own shapes only), and each pad's region,
    way and wall flags. Shapes are compared by identity; the memo holds the last board's, so none is reused. A change
    of settings, geometry, rules, quiet nets, frame or judging mode starts it again.

    A pad's entry is dropped when a shape added or removed since overlaps its region (what `EscapeDelta.difference`
    rejudges its way by). A changed shape within its wall region but clear of its region drops only its wall flags.
    A changed shape on its net alone drops its wall flags too, and leaves its region and, for a quiet net's pad (judged
    for walled only, with no target), its way; a signal pad's way then holds while its target (`Escapes._aim`, the only
    thing its judgement reads from the rest of its net) is the same, which the next judgement checks (`stale`).

    A pad's way is also kept beyond its entry (`earlier`): with the shapes on its region and its target, its last
    `VERSIONS` verdicts. A later board with equal shapes there (compared as values: a part put back stands in new
    shapes) and the same target takes it, the boards between them however they differed."""
    VERSIONS = 4

    def __init__(self):
        self.key = None
        self.generation = 0     # one more for each board synced with a change
        self.shapes = {}        # id -> shape, of the last board synced
        self.lanes = {}         # ref -> (its shapes, the cached `_lanes_of` value)
        self.pads = {}          # (ref, number) -> {'net', 'region', 'wall', and 'way' / 'walls' once judged}
        self.ways = {}          # (ref, number) -> [(the shapes on its region, sorted by `_value_key`, target, way)]
        self._cells = None      # the last board's shapes by `_cells` cell, as {id: shape}, made when first asked

    def sync(self, occ, native) -> None:
        key = (occ.settings, occ.geometry, occ.rules, frozenset(occ.quiet_nets), occ.board_box,
               occ.settings.score_escape_depth, bool(native))
        current = {id(sh): sh for r, g in occ.items.items() if r not in occ.pending for sh in g.shapes}
        current.update((id(sh), sh) for sh in occ.copper)
        if self.key is None or any(a is not b for a, b in zip(key[:3], self.key[:3])) or key[3:] != self.key[3:]:
            self.key, self.shapes, self.lanes, self.pads, self.ways, self._cells = key, current, {}, {}, {}, None
            self.generation += 1
            return
        added = [sh for i, sh in current.items() if i not in self.shapes]
        gone = [sh for i, sh in self.shapes.items() if i not in current]
        changed = added + gone
        self.shapes = current
        if not changed:
            return
        self.generation += 1
        if self._cells is not None:
            for sh in gone:
                for c in _cells(sh.box):
                    self._cells[c].pop(id(sh), None)
            for sh in added:
                for c in _cells(sh.box):
                    self._cells.setdefault(c, {})[id(sh)] = sh
        nets = {sh.net for sh in changed if sh.net}
        boxes = [sh.box for sh in changed]
        quiet = occ.quiet_nets
        kept = {}
        for k, e in self.pads.items():
            near = [b for b in boxes if e['wall'].overlaps(b)]
            if any(e['region'].overlaps(b) for b in near):
                continue
            if near or e['net'] in nets:
                e = {n: v for n, v in e.items() if n != 'walls'}
                if e['net'] in nets and e['net'] not in quiet:
                    e['stale'] = True
            kept[k] = e
        self.pads = kept

    def members(self, region) -> list:
        """The last board's shapes whose boxes overlap `region` (as `sync` tests a changed shape against it), sorted
        by `_value_key`."""
        if self._cells is None:
            self._cells = {}
            for sh in self.shapes.values():
                for c in _cells(sh.box):
                    self._cells.setdefault(c, {})[id(sh)] = sh
        found = {}
        for c in _cells(region):
            bucket = self._cells.get(c)
            if bucket:
                found.update(bucket)
        return sorted((sh for sh in found.values() if region.overlaps(sh.box)), key=_value_key)

    def earlier(self, key, members, target):
        """(way,) of an earlier verdict for the pad made with equal shapes on its region and this target, or None."""
        for held, aim, way in self.ways.get(key, ()):
            if aim == target and len(held) == len(members) and all(a is b or a == b for a, b in zip(held, members)):
                return (way,)
        return None

    def keep(self, key, members, target, way) -> None:
        versions = self.ways.setdefault(key, [])
        versions.append((members, target, way))
        if len(versions) > self.VERSIONS:
            del versions[0]

    def lanes_into(self, esc, ref) -> None:
        hit = self.lanes.get(ref)
        shapes = esc.occ.items[ref].shapes
        if hit is not None and len(hit[0]) == len(shapes) and all(a is b for a, b in zip(hit[0], shapes)):
            esc._lane_cache[ref] = hit[1]

    def keep_lanes(self, esc, ref) -> None:
        self.lanes[ref] = (tuple(esc.occ.items[ref].shapes), esc._lane_cache[ref])

    def add(self, key, net, region, wall) -> dict:
        entry = self.pads[key] = {'net': net, 'region': region, 'wall': wall}
        return entry


def _value_key(sh) -> tuple:
    """An order for shapes by value, so two boards' equal shapes on a region line up."""
    b = sh.box
    return sh.owner, sh.kind, sh.net, sh.label, b.left, b.top, b.right, b.bottom


def _baseline_memo(occ, native):
    """The occupancy's `_BaselineMemo`, synced with its board as it stands."""
    global _BASELINES
    import weakref
    if _BASELINES is None:
        _BASELINES = weakref.WeakKeyDictionary()
    memo = _BASELINES.get(occ)
    if memo is None:
        memo = _BASELINES[occ] = _BaselineMemo()
    memo.sync(occ, native)
    return memo


def native_judge() -> bool:
    """Whether the native escape judgement twins are built: the classification (`surface_judge`) and the exact path
    search (`surface_path_out`)."""
    from .geometry import _native
    return _native is not None and hasattr(_native, 'surface_judge') and hasattr(_native, 'surface_path_out')


def _wall_flags(esc, ref, number) -> tuple:
    """(its declared lane runs out, it is a walled hand-off) for one pad, as `lanes_walled` and `handoffs_walled` judge it
    where `esc`'s board stands."""
    pads = _pads_of(esc.occ.items[ref].shapes, ref)
    if len(pads) < esc.occ.settings.place_escape_min_pads or number not in pads:
        return False, False
    net, layers, box = pads[number]
    return (esc._lane_walled(ref, number, net, layers, box, blame=False) is not None,
            esc._handoff_walled(ref, number, net, layers, box, blame=False) is not None)


def _add(counts, way, walls, sign) -> None:
    """Add one pad's way and wall flags into raw escape counts, as `Escapes.counts` counts them: a pad is walled once
    whether its way or its declared lane walls it, and a walled hand-off once more."""
    lane, handoff = walls
    if way is Way.VIA:
        counts['escape_via'] += sign
    elif way is Way.AWAY:
        counts['escape_closed'] += sign
    counts['escape_walled'] += sign * (int(way is Way.WALLED or lane) + int(handoff))


def path_out(occ, ref: str, number: str, depth: float | None = None, toward=None, near=None, own=(),
             exact: bool = False, via_exit: bool = True, window: Box | None = None, *, native: bool = False) -> bool:
    """Whether a track of the pad's net can get out of it: a path, at the
    net's track width and clearance from every other net's copper on the
    pad's layers, from the pad to the edge of a window `depth` round it or
    to a spot where a via fits clear of every other net's copper. With
    `toward` (a direction), only an edge facing that way counts, and a via
    spot still does: the route leaves the layer there. `near` is the copper
    to judge against (default: every placed item's pads and the planned
    copper). Obstacles are taken as their boxes. `own` is copper of the pad's own net standing on it (a stub): the path
    starts anywhere on it. `exact` takes the obstacles as the shapes they are, not their boxes (a diagonal track's box is
    mostly empty): a cell is blocked by a track's own width and clearance, and the window is judged cell by cell as the
    search reaches it. `via_exit` off: a spot a via fits at is no way out, only a track reaching the window's edge is.
    `window` is the window itself, in place of the one `depth` round the pad: a module's frame, whose edge a lane reaches."""
    depth = occ.settings.place_escape_depth if depth is None else depth
    g = occ.items[ref]
    mine = [s for s in g.shapes if s.kind in ("pad", "through") and s.owner == ref and s.label == number]
    if not mine:
        return True
    net = mine[0].net
    layers = frozenset().union(*(s.layers for s in mine))
    pad = Box.union([s.box for s in mine] + [s.box for s in own])
    nc = occ.geometry.netclass(net)
    track, via = nc.track_width / 2.0 + nc.clearance, nc.via_diameter / 2.0 + nc.clearance
    win = pad.inflate(depth) if window is None else window
    reach = win.inflate(max(track, via))
    if near is None:
        near = [s for r, h in occ.items.items() if r not in occ.pending for s in h.shapes
                if s.kind in ("pad", "through")] + [s for s in occ.copper if s.kind in ("copper", "through")]
    near_reach = near.overlapping(reach) if isinstance(near, _Near) else near
    foes = [s for s in near_reach if (s.net != net or not net) and not (s.owner == ref and s.label == number)
            and s.kind != "npth" and s.box.overlaps(reach)]
    holes, bans = near.extra(occ, reach, net) if isinstance(near, _Near) else extra_walls(occ, reach, net)
    # a hole keeps a track `hole_clearance` off its edge, a via ban nothing but the via's own ring: each as the foe it is,
    # by how much its reach differs from a copper clearance
    delta = {id(h): occ.geometry.hole_clearance - nc.clearance for h in holes}
    delta.update({id(b): -nc.clearance for b in bans})
    if exact:
        if native and _native_fits(win, occ.settings.place_escape_cell):
            return _path_out_native(occ, mine + list(own), foes + holes, layers, win, track, via,
                                    toward, bans, delta, via_exit)
        return _path_out_exact(occ, mine + list(own), foes + holes, layers, win, track, via, toward, bans, delta, via_exit)
    walls = [s.box.inflate(track) for s in foes if s.layers & layers] + [h.box.inflate(track + delta[id(h)]) for h in holes]
    vias = [s.box.inflate(via) for s in foes] + [s.box.inflate(via + delta[id(s)]) for s in holes + bans]
    cell = occ.settings.place_escape_cell
    # The search below reads only these boxes, the window, the pad, the cell and `toward`: the same inputs give the same
    # answer, so a lifted board's judgement (every Delta's) does not search a pad's unchanged surroundings again.
    key = (_box_key(win), _box_key(pad), cell, None if toward is None else tuple(toward), tuple(sorted(map(_box_key, walls))),
           tuple(sorted(map(_box_key, vias))))
    hit = _BOX_PATHS.get(key)
    if hit is None:
        if len(_BOX_PATHS) >= _BOX_PATHS_MAX:
            _BOX_PATHS.clear()
        hit = _BOX_PATHS[key] = _path_out_boxes(win, pad, cell, toward, walls, vias)
    return hit


# The box search's answers by its inputs (`path_out`, exact off), and how many are kept before they are dropped.
_BOX_PATHS: dict = {}
_BOX_PATHS_MAX = 200_000


def _box_key(b) -> tuple:
    return b.left, b.top, b.right, b.bottom


def _path_out_boxes(win, pad, cell, toward, walls, vias) -> bool:
    """`path_out`'s search with the obstacles taken as their boxes: `walls` block a track's cell, `vias` a via's."""
    nx = max(1, int(math.ceil(win.width / cell)))
    ny = max(1, int(math.ceil(win.height / cell)))
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


def extra_walls(occ, box: Box, net: str) -> tuple:
    """(holes, bans) near `box` that the clearance check refuses a track or a via at but are no copper: the unplated holes
    of every placed part (a hole is on every layer), and the rule areas that forbid vias, which only a via meets, unless
    they let `net` through."""
    holes = [s for r, g in occ.items.items() if r not in occ.pending for s in g.shapes
             if s.kind == "npth" and s.box.overlaps(box)]
    bans = [s for pool in ([occ.copper] + [g.shapes for r, g in occ.items.items() if r not in occ.pending])
            for s in pool if s.kind == "viaban" and s.box.overlaps(box) and net not in s.net.split(ALLOW_SEP)]
    return holes, bans


_NATIVE_CELLS = 1_000_000    # the most cells the Rust search takes (native/src/surface.rs, `validate_search`)


def _native_fits(win: Box, cell: float) -> bool:
    """Whether the Rust search takes a window this size: a larger one (a pad whose own copper runs across the board) is
    searched in Python, as it was before the search had a native twin."""
    nx = max(1, math.ceil(win.width / cell))
    ny = max(1, math.ceil(win.height / cell))
    return nx * ny <= _NATIVE_CELLS


def _path_out_native(occ, start_shapes, foes, layers, win, track, via, toward, bans=(), delta=None, via_exit=True):
    """The exact path search in Rust, `_path_out_exact`'s twin: what `path_out(exact=True, native=True)` runs, which the
    judgement uses when the native module is built (`Escapes._native_paths`).

    Refused snapshots propagate rather than silently certifying a way out.
    The Python oracle remains independently callable by `_path_out_exact`.
    """
    from .geometry import _native
    if _native is None or not hasattr(_native, 'surface_path_out'):
        raise RuntimeError('native surface escape search unavailable')
    delta = delta or {}
    def shape(s):
        return _surface_shape(s, delta.get(id(s), 0.0))
    return _native.surface_path_out([shape(s) for s in start_shapes], [shape(s) for s in foes],
        _layer_bits(layers), (win.left, win.top, win.right, win.bottom), track, via, toward,
        [shape(s) for s in bans], occ.settings.place_escape_cell, occ.geometry.drc_epsilon, via_exit)


# A shape's surface record parts (polygon, box, layer bits, ends) by its identity, the shape held with them so its id
# stays its own while the entry lives. A shape is frozen, so its record never changes. Cleared past _SURFACE_MAX.
_SURFACE = {}
_SURFACE_MAX = 200_000


def _surface_shape(s, delta=0.0):
    hit = _SURFACE.get(id(s))
    if hit is None or hit[0] is not s:
        b = s.box
        hit = (s, (list(map(tuple, s.poly)), (b.left, b.top, b.right, b.bottom), _layer_bits(s.layers),
                   list(map(tuple, s.ends or ())), 0.0))
        if len(_SURFACE) >= _SURFACE_MAX:
            _SURFACE.clear()
        _SURFACE[id(s)] = hit
    record = hit[1]
    return record if delta == 0.0 and math.copysign(1.0, delta) > 0 else (*record[:4], delta)


def _path_out_exact(occ, start_shapes, foes, layers, win: Box, track: float, via: float, toward, bans=(), delta=None, via_exit: bool = True) -> bool:
    """`path_out`'s search on the shapes themselves: from every cell on `start_shapes` (the pad and the pad's own copper) over
    the cells of `win` a track keeps `track` (half its width and the clearance) from every foe on its layers, to the window's
    edge or to a cell a via fits at, `via` from every foe. A gap short of that by no more than the board's DRC epsilon is a tie,
    which holds, as in occupancy.

    A track runs at 0, 45 and 90 degrees, so a second search walks those directions from where the pad's copper can be carried
    on: each end of its tracks and the pad's centre, on a lattice of `place.escape_cell` steps through that point. A lane
    laid at the least pitch from its neighbours has no room to spare, and the free-form cells above, off its line, cannot
    follow it."""
    cell = occ.settings.place_escape_cell
    nx = max(1, int(math.ceil(win.width / cell)))
    ny = max(1, int(math.ceil(win.height / cell)))
    cw, ch = win.width / nx, win.height / ny
    walls = [s for s in foes if s.layers & layers]

    def centre(i, j):
        return win.left + (i + 0.5) * cw, win.top + (j + 0.5) * ch

    delta = delta or {}
    eps = occ.geometry.drc_epsilon

    def near(shapes, x, y, r):
        """Whether the least distance from (x, y) to the shapes is under `r` (a shape's own reach differs by its `delta`), 0
        inside one."""
        for sh in shapes:
            rs = max(r + delta.get(id(sh), 0.0) - eps, 0.0)
            b = sh.box
            if b.left - rs >= x or x >= b.right + rs or b.top - rs >= y or y >= b.bottom + rs:
                continue
            if point_in_polygon((x, y), sh.poly):
                return True
            n = len(sh.poly)
            if any(point_segment_distance((x, y), sh.poly[k], sh.poly[(k + 1) % n]) < rs for k in range(n)):
                return True
        return False
    memo_wall: dict = {}

    def walled(i, j):
        k = (i, j)
        if k not in memo_wall:
            memo_wall[k] = near(walls, *centre(i, j), track)
        return memo_wall[k]

    def on_start(x, y):
        return any(sh.box.left <= x <= sh.box.right and sh.box.top <= y <= sh.box.bottom and point_in_polygon((x, y), sh.poly)
                   for sh in start_shapes)
    top = Box.union([sh.box for sh in start_shapes])
    todo = [(i, j) for i in range(max(0, int((top.left - win.left) / cw)), min(nx, int((top.right - win.left) / cw) + 1))
            for j in range(max(0, int((top.top - win.top) / ch)), min(ny, int((top.bottom - win.top) / ch) + 1))
            if on_start(*centre(i, j))]
    seen = set(todo)
    cx, cy = top.center.x, top.center.y
    while todo:
        i, j = todo.pop()
        x, y = centre(i, j)
        if i in (0, nx - 1) or j in (0, ny - 1):
            if toward is None or toward[0] * (x - cx) + toward[1] * (y - cy) > 0:
                return True
        if via_exit and not on_start(x, y) and not near(foes, x, y, via) and not near(bans, x, y, via):
            return True                     # a via fits here
        for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a < nx and 0 <= b < ny and (a, b) not in seen and not walled(a, b):
                seen.add((a, b))
                todo.append((a, b))
    # along the octilinear lattices
    anchors = []
    for sh in start_shapes:
        pts = sh.ends or ((sh.box.center.x, sh.box.center.y),)
        anchors += [tuple(p) for p in pts if tuple(p) not in anchors]
    for ax, ay in anchors:
        if _walk_lattice(ax, ay, win, cell, toward, (cx, cy), lambda x, y: near(walls, x, y, track), on_start,
                         lambda x, y: via_exit and not near(foes, x, y, via) and not near(bans, x, y, via)):
            return True
    return False


def _walk_lattice(ax, ay, win: Box, step: float, toward, centre: tuple, walled, on_start, via_fits) -> bool:
    """Whether a track from (ax, ay) gets out of `win` moving by `step` at 0, 45 and 90 degrees: to a node within a step of
    the window's edge (facing `toward`, when it is given), or to one a via fits at."""
    seen = {(0, 0)}
    todo = [(0, 0)]
    while todo:
        i, j = todo.pop()
        x, y = ax + i * step, ay + j * step
        if (x - win.left <= step or win.right - x <= step or y - win.top <= step or win.bottom - y <= step):
            if toward is None or toward[0] * (x - centre[0]) + toward[1] * (y - centre[1]) > 0:
                return True
        if not on_start(x, y) and via_fits(x, y):
            return True
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                k = (i + di, j + dj)
                if (di or dj) and k not in seen:
                    seen.add(k)
                    nxt = (ax + k[0] * step, ay + k[1] * step)
                    if win.left <= nxt[0] <= win.right and win.top <= nxt[1] <= win.bottom and not walled(*nxt):
                        todo.append(k)
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
