"""Carried vias that give way (docs/superpowers/specs/2026-09-30-plane-drops-
and-the-far-face-design.md, section 1).

A carried via is one a part or a stamped cell brings with it: a via the
script declared at a searched part's pad (`board.via(net, PadRef(...))`), or
one of a stamped fragment's own. Its tail is the one track of its owner's, on
its net, that ends at its centre. Where a carried via meets another net's
copper, on either face, at a candidate, it tries in turn to

1. share a same-net via of another item within `place.via_share`: the via is
   removed and a straight tail at the net's width joins its pad (its old
   tail's far end, or where it stood) to that via, on its own face;
2. move up to `place.via_move`, searched on a `place.via_move_step` grid,
   nearest first, to a spot clear of every other net's copper and every
   hole, its tail redrawn from its pad; a via inside its pad stays inside it.

The search judges the item less its carried vias natively, as it judges
any item; what the vias do is judged here, in Python, after that, and priced
at `score.via_share` and `score.via_move` each.

What is decided is recomputed at each commit from the board as it stands, so
a replayed commit, or a part the cleanup pass moves, gives way the same."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import functools
import math

from .copper import Track
from .geometry import point_in_polygon, point_segment_distance
from .values import Box, CopperLayer, Face, Location

_COPPER_AND_HOLES = frozenset(("pad", "through", "copper", "hole", "npth"))


def pad_via_id(k: int) -> str:
    """The id of the k-th via the script declared at a pad."""
    return "pad via %d" % k


def enabled(settings) -> bool:
    """Whether a carried via may give way at all under these settings."""
    return settings.place_via_share > 0 or settings.place_via_move > 0


def reach(settings) -> float:
    """How far past an item's copper what its vias do can reach."""
    return settings.place_via_share + settings.place_via_move


def least_cost(settings) -> float:
    """The least a spot where a via must give way costs beyond its score:
    the cheapest way these settings allow."""
    ways = [cost for on, cost in ((settings.place_via_share > 0, settings.score_via_share),
                                  (settings.place_via_move > 0, settings.score_via_move)) if on]
    return min(ways) if ways else 0.0


@dataclass
class Group:
    """One carried via where it stands: its ring, its hole, its tail."""
    id: str
    owner: str                  # its shapes' owner: a cell's name, or "via at REF.N"
    home: str                   # where its shapes live: a part's refdes, or a cell's name
    net: str
    ring: object = None
    hole: object = None
    tail: object = None
    centre: tuple = ()
    far: tuple | None = None    # its tail's other end

    @property
    def shapes(self) -> list:
        return [s for s in (self.ring, self.hole, self.tail) if s is not None]


@dataclass(frozen=True)
class Action:
    """What one carried via did."""
    kind: str                   # share | move | drop
    via: str                    # its id
    owner: str
    home: str
    net: str
    at: tuple                   # where it stood as drawn
    to: tuple | None = None     # moved: its new centre; shared: the centre of the via it joins
    tail: object = None         # the Track drawn: a share's joining tail, a move's redrawn one
    old_tail: tuple | None = None   # the drawn tail taken away, as its two ends (the via's end first)
    pad: tuple | None = None    # (refdes, pad number) of the pad it serves
    under: str = ""             # whose copper it met
    cost: float = 0.0
    shapes: tuple = field(default=(), compare=False)    # what it leaves on the board in its place

    @property
    def moved_mm(self) -> float:
        return math.dist(self.at, self.to) if self.kind == "move" else 0.0


@dataclass
class Resolution:
    """What an item's placement makes its and others' carried vias do: the
    actions, their cost, or why one cannot give way."""
    actions: list = field(default_factory=list)
    cost: float = 0.0
    why: str | None = None
    blocker: object = None


def _shift(s, dx: float, dy: float):
    from .occupancy import Shape
    return Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((x + dx, y + dy) for x, y in s.poly),
                 s.box.moved(dx, dy), s.label, carried=s.carried,
                 points=tuple((x + dx, y + dy) for x, y in s.points), given=s.given)


def groups(occ, shapes) -> dict:
    """{id: Group} of the carried vias among `shapes`, in id order."""
    out: dict = {}
    carried_by = occ.__dict__.get("_carried", {})
    for s in shapes:
        if not s.carried:
            continue
        g = out.get(s.carried)
        if g is None:
            g = out[s.carried] = Group(s.carried, s.owner, carried_by.get(s.owner, s.owner), s.net)
        if s.kind == "through":
            g.ring, g.centre = s, s.points[0]
        elif s.kind == "hole":
            g.hole = s
        elif s.kind == "copper":
            g.tail, g.far = s, s.points[1]
    return {k: out[k] for k in sorted(out) if out[k].ring is not None}


def _centre(s) -> tuple:
    if s.points:
        return s.points[0]
    if s.circle:
        return s.circle[:2]
    c = s.box.center
    return (c.x, c.y)


def _width(tail) -> float:
    """A tail's width: twice the distance from the middle of its centre line
    to its outline's sides."""
    (ax, ay), (bx, by) = tail.points
    mid = ((ax + bx) / 2.0, (ay + by) / 2.0)
    n = len(tail.poly)
    return round(2.0 * min(point_segment_distance(mid, tail.poly[i], tail.poly[(i + 1) % n]) for i in range(n)), 6)


def _radius(g: Group) -> float:
    """The via's copper radius: from its centre to its ring's nearest side."""
    n = len(g.ring.poly)
    return min(point_segment_distance(g.centre, g.ring.poly[i], g.ring.poly[(i + 1) % n]) for i in range(n))


def _disc_inside(poly, c: tuple, r: float) -> bool:
    """Whether the disc of radius `r` round `c` lies inside `poly`: its
    centre inside, and every side at least `r` from it."""
    if not point_in_polygon(c, poly):
        return False
    n = len(poly)
    return all(point_segment_distance(c, poly[i], poly[(i + 1) % n]) >= r for i in range(n))


@functools.lru_cache(maxsize=16)
def _offsets(reach: float, step: float) -> tuple:
    """(dx, dy) within `reach` on a `step` grid, nearest first, the centre left out."""
    n = int(math.floor(reach / step + 1e-9))
    pts = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            d = math.hypot(i * step, j * step)
            if 1e-12 < d <= reach + 1e-9:
                pts.append((round(d, 9), round(i * step, 9), round(j * step, 9)))
    pts.sort()
    return tuple((dx, dy) for _, dx, dy in pts)


class _Judge:
    """The board a give-way is judged against: `others` (the obstacles of the
    item being placed) less the vias hidden because they gave way, plus the
    copper they left in their place."""

    def __init__(self, occ, others, clearance):
        self.occ, self.others, self.clearance = occ, others, clearance
        self.hidden: set = set()
        self.extra: list = []

    def near(self, box: Box, gap: float) -> list:
        from .occupancy import ShapeIndex
        found = self.others.near(box, gap) if isinstance(self.others, ShapeIndex) else \
            [o for o in self.others if o.box.overlaps(box, gap=gap)]
        out = [o for o in found if not (o.carried and o.carried in self.hidden)]
        return out + [o for o in self.extra if o.box.overlaps(box, gap=gap)]

    def hit(self, shapes, pool, own=(), say: bool = True):
        """(sentence, what it met) for the first of `shapes` that meets
        anything in `pool` (from `near`) or `own`, or None. A via's ring is
        judged against the board's edge too. `say=False`: the sentence is
        only the kind of conflict."""
        occ = self.occ
        for s in shapes:
            gap = occ.gap_for(s)
            for o in pool:
                if o.box.overlaps(s.box, gap=gap):
                    why = occ._conflict(s, o, self.clearance, say=say)
                    if why:
                        return why, o
            for o in own:
                if o.box.overlaps(s.box, gap=gap):
                    why = occ._conflict(s, o, self.clearance, say=say)
                    if why:
                        return why, o
            if s.kind == "through" and occ.edge_margin is not None:
                why = occ._edge_why(s.box)
                if why:
                    c = _centre(s)
                    return "via %s at (%.2f, %.2f): its ring %s" % (s.net or "-", c[0], c[1], why), None
        return None

    def vias(self, net: str, centre: tuple, reach: float, exclude: str) -> list:
        """(distance, centre, radius) of each via of `net` within `reach` of
        `centre`, nearest first: any item's, not a part's plated pad."""
        box = Box(centre[0] - reach, centre[1] - reach, centre[0] + reach, centre[1] + reach)
        out = []
        for o in self.near(box, 0.0):
            if o.kind != "through" or o.net != net or o.owner in self.occ._footprint_refs or o.carried == exclude:
                continue
            c = _centre(o)
            d = math.dist(c, centre)
            if d <= reach + 1e-9:
                out.append((round(d, 9), c, o.box.width / 2.0))
        out.sort()
        return out


class _Owner:
    """What a via's own item says about it: its pads, its face."""

    def __init__(self, occ, pads, face):
        self.occ, self.pads, self.face = occ, pads, face

    def pad_of(self, g: Group):
        """(pad key, its shape, whether the via is inside it): the pad of the
        via's net that holds its centre, else the one its tail ends in."""
        for at, inside in ((g.centre, True), (g.far, False)):
            if at is None:
                continue
            for key, s in self.pads:
                if s.net == g.net and point_in_polygon(at, s.poly):
                    return key, s, inside
        return None, None, False

    def layer(self, g: Group, pad) -> CopperLayer:
        """The via's own face: its tail's layer, else its pad's on the item's
        face, else the item's face."""
        if g.tail is not None:
            return next(iter(g.tail.layers))
        outer = [l for l in (pad.layers if pad is not None else ()) if l in (CopperLayer.F, CopperLayer.B)]
        if len(outer) == 1:
            return outer[0]
        return self.face.copper


def _still_meets(occ, g: Group, first, clearance, r: float):
    """A quick test that a via moved to a spot still meets `first`, the
    copper it met where it stood, or None where there is none: its centre
    in that copper, or nearer it than its clearance plus the via's radius
    (the ring's copper reaches at least that far). Only a spot this passes
    is judged in full."""
    if first is None or first.kind not in ("pad", "through", "copper") or not (first.layers & g.ring.layers) \
            or (first.net and first.net == g.net):
        return None
    if occ.geometry.has_footprint(first.owner) and occ.geometry.footprint(first.owner).net_tie_pads:
        return None
    geo = occ.geometry
    clr = clearance if clearance is not None else (
        geo.clearance(g.net, first.net) if (g.net in geo.nets and first.net in geo.nets) else geo.default_clearance)
    poly = first.poly
    n = len(poly)

    def still(c) -> bool:
        if point_in_polygon(c, poly):
            return True
        d = min(point_segment_distance(c, poly[i], poly[(i + 1) % n]) for i in range(n))
        return d - r < clr - 1e-9
    return still


def _tail_shape(owner, net, layer, width, start, end, carried="", given=""):
    from .occupancy import Shape
    t = Track(net, layer, width, Location(*start), Location(*end))
    faces = frozenset([layer.face]) if layer.face else frozenset()
    return t, Shape(owner, "copper", faces, frozenset([layer]), net, t.polygon, t.box, carried=carried,
                    points=(tuple(end), tuple(start)) if carried else (), given=given)


def _give(occ, g: Group, judge: _Judge, own, who: _Owner, met: str, first=None):
    """(Action, None) for the first way `g` can give way, else (None, why
    not), judged against `judge` and the item's own copper `own`. `first`:
    the copper it met, which a move is judged against before the rest."""
    s = occ.settings
    geo = occ.geometry
    pad_key, pad, inside = who.pad_of(g)
    layer = who.layer(g, pad)
    old = (g.centre, g.far) if g.tail is not None else None
    said = []
    if s.place_via_share > 0:
        targets = judge.vias(g.net, g.centre, s.place_via_share, g.id)
        width = geo.netclass(g.net).track_width if g.net in geo.nets else 0.2
        start = g.far if g.far is not None else g.centre
        for d, c, r in targets:
            if d <= r:                          # on its spot: nothing to draw, its tail joins that via as it is
                left = () if g.tail is None else (replace(g.tail, carried="", points=(), given=g.id),)
                if left and judge.hit(left, judge.near(left[0].box, occ.gap_for(left[0])), own, say=False):
                    continue
                # a tail an earlier giving way drew is the plan's to draw; the one its item drew is on the board
                kept = Track(g.net, next(iter(g.tail.layers)), _width(g.tail), Location(*g.far),
                             Location(*g.centre)) if g.tail is not None and g.tail.given else None
                return Action("share", g.id, g.owner, g.home, g.net, g.centre, c, kept, None, pad_key, met,
                              s.score_via_share, left), None
            track, shape = _tail_shape(g.owner, g.net, layer, width, start, c, given=g.id)
            if judge.hit([shape], judge.near(shape.box, occ.gap_for(shape)), own, say=False):
                continue
            return Action("share", g.id, g.owner, g.home, g.net, g.centre, c, track, old, pad_key, met,
                          s.score_via_share, (shape,)), None
        said.append("no %s via within %.2f mm to share" % (g.net, s.place_via_share) if not targets else
                    "no tail to the %s via%s within %.2f mm is clear" % (g.net, "s" if len(targets) > 1 else "",
                                                                         s.place_via_share))
    if s.place_via_move > 0:
        limit = s.place_via_move
        r = _radius(g)
        width = _width(g.tail) if g.tail is not None else 0.0
        span = g.ring.box.inflate(limit)
        if g.tail is not None:
            span = Box.union([span, g.tail.box.inflate(limit)])
        pool = judge.near(span, occ._gap)
        mine = [o for o in own if o.box.overlaps(span, gap=occ._gap)]
        still = _still_meets(occ, g, first, judge.clearance, r)
        found = None
        for dx, dy in _offsets(limit, s.place_via_move_step):
            to = (round(g.centre[0] + dx, 9), round(g.centre[1] + dy, 9))
            if inside and not _disc_inside(pad.poly, to, r - 1e-5):
                continue
            if still is not None and still(to):
                continue
            ring = _shift(g.ring, dx, dy)
            if first is not None and first.box.overlaps(ring.box, gap=occ._gap) \
                    and occ._conflict(ring, first, judge.clearance, say=False):
                continue                    # still on what it met: most spots near it are
            moved = [replace(ring, given=g.id)]
            if g.hole is not None:
                moved.append(replace(_shift(g.hole, dx, dy), given=g.id))
            if judge.hit(moved, pool, mine, say=False):
                continue
            track = None
            if g.tail is not None:
                track, shape = _tail_shape(g.owner, g.net, next(iter(g.tail.layers)), width, g.far, to,
                                           carried=g.id, given=g.id)
                if judge.hit([shape], pool, mine, say=False):
                    continue
                moved.append(shape)
            found = Action("move", g.id, g.owner, g.home, g.net, g.centre, to, track, old, pad_key, met,
                           s.score_via_move, tuple(moved))
            break
        if found is not None:
            return found, None
        said.append("no spot within %.2f mm%s is clear" % (limit, " inside its pad" if inside else ""))
    return None, ", ".join(said)


def _pads(occ, shapes) -> list:
    return [((s.owner, s.label), s) for s in shapes
            if s.kind in ("pad", "through") and not s.carried and s.owner in occ._footprint_refs]


def resolve(occ, item, placement, clearance=None, others=None) -> Resolution:
    """What `item` at `placement` makes its carried vias that meet the board
    do, or why one of them cannot give way. The item less its carried vias
    is taken to be legal there."""
    s = occ.settings
    res = Resolution()
    if not enabled(s):
        return res
    geom = occ._geometry(item)
    dx, dy = placement.location.x, placement.location.y
    mine = [_shift(x, dx, dy) for x in occ._origin_shapes(item, geom, placement)]
    if others is None:
        extent = Box.union([x.box for x in mine])
        others = occ.obstacles(geom, extent.inflate(reach(s)))
    judge = _Judge(occ, others, clearance)
    own = groups(occ, mine)
    if own:
        mine_face = placement.face
        who = _Owner(occ, _pads(occ, mine), mine_face)
        meeting = []
        for g in own.values():
            pool = judge.near(Box.union([x.box for x in g.shapes]), occ._gap)
            hit = judge.hit(g.shapes, pool)
            if hit is not None:
                meeting.append((g, hit))
        if meeting:
            gone = {g.id for g, _ in meeting}
            keep = [x for x in mine if x.kind in _COPPER_AND_HOLES and x.carried not in gone]
            for g, (why, o) in meeting:
                met = "the edge" if o is None else occ.who(o.owner) if o.owner else \
                    ("a via" if o.kind == "through" else "a track")
                action, why_not = _give(occ, g, judge, keep, who, met, o)
                if action is None:
                    return _refused(occ, res, "%s; it cannot give way: %s" % (why, why_not), o)
                keep += list(action.shapes)
                res.actions.append(action)
                res.cost += action.cost
    return res


def near_carried(occ, item, region: Box) -> bool:
    """Whether a via may give way to `item` within `region`: it carries one."""
    return occ.carries(item)


class ScanGiveWay:
    """What a scan needs to let vias give way to its item: the item less
    its carried vias, judged natively where the scan is, and the board its
    vias are judged against."""

    def __init__(self, occ, item, face, rots, region: Box, clearance, native: bool):
        from .occupancy import WithoutCarried
        self.occ, self.of, self.clearance = occ, item, clearance
        self.item = WithoutCarried(item)
        geom = occ._geometry(item)
        self.others = occ.obstacles(geom, region)
        self.full = occ.obstacles(geom, region.inflate(reach(occ.settings)))
        self.native = occ.native_sweeper(self.item, face, rots, self.others, clearance) if native else None

    def resolve(self, placement) -> Resolution:
        return resolve(self.occ, self.of, placement, self.clearance, self.full)


def for_scan(occ, item, face, rots, region: Box, clearance, native: bool):
    """A ScanGiveWay for a scan of `item` over `region`, or None when no via
    could give way there."""
    if not enabled(occ.settings) or not near_carried(occ, item, region):
        return None
    return ScanGiveWay(occ, item, face, rots, region, clearance, native)


def _refused(occ, res: Resolution, why: str, o) -> Resolution:
    from .occupancy import Blocker, _blocker_kind
    res.why = why
    res.blocker = Blocker("edge", "", frozenset()) if o is None else \
        Blocker(_blocker_kind(o.kind), occ.blame_owner(o), frozenset(o.faces))
    return res


def apply(occ, res: Resolution) -> None:
    """Leave on the board what `res` decided: each via that gave way taken
    out of its item, and what it left in its place put in; the item as drawn
    is kept to put back if it is placed again."""
    for a in res.actions:
        if a.home in occ.items and occ.geometry.has_footprint(a.home):
            occ._pristine.setdefault(a.home, occ.items[a.home])
            g = occ.items[a.home]
            occ.items[a.home] = replace(g, shapes=tuple(x for x in g.shapes if x.carried != a.via) + a.shapes)
        else:
            occ._pristine_copper.setdefault(a.home, [c for c in occ.copper if c.owner == a.home])
            occ.copper = [c for c in occ.copper if c.carried != a.via] + list(a.shapes)
        before = occ.given_way.get(a.via)
        if before is not None:
            a = replace(a, at=before.at, old_tail=before.old_tail if before.old_tail is not None else a.old_tail)
        occ.given_way[a.via] = a
    if res.actions:
        occ._changed()
