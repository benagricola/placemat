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
   hole, its tail redrawn from its pad; a via inside its pad stays inside it;
3. leave its pad, a via inside its pad with no tail and no spot inside it
   clear: it moves up to `place.via_leave` to the nearest spot that is, and
   a new tail on its own face joins it to the pad, at the net's track width
   or narrower down to the board's minimum;
4. shorten to a via from its own face to the nearest layer of its own
   plane between it and the far face - a plane net's carried drop only,
   and only when the fab profile's tier for the resulting via type
   (micro, blind or buried) is "yes"; "if-needed" is judged (its span
   named, would it clear) but never applied, and "no" is not applied, though
   the refusal says when it would have cleared;
5. be dropped, a plane net's drop only, while its pad keeps
   `place.drops_keep` of its drops (rounded up, at least one).

A routed via, one that two or more of its cell's tracks end on, has one step in
place of these: it moves up to `place.via_route` with every one of its tracks
rebuilt from its far end (`_give_routed`), priced at `score.via_route`.

A via already placed does the same for a later item whose own copper meets
it. The search judges the item less its carried vias natively, as it judges
any item; what the vias do is judged here, in Python, after that, and priced
at `score.via_share`, `score.via_move`, `score.via_leave`, `score.via_shorten` and
`score.via_drop` each.

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

_NATIVE_MOVE_SEARCH = True
"""Whether a via's move search uses the native offset search when it can:
switched off to compare against the pure-Python per-offset loop
(tests/test_vias_give_way.py)."""

_NATIVE_TAIL_CLEAR = True
"""Whether a share's tail is judged by a native call (`tail_clear`) when it can be."""

_NATIVE_FIRST_MOVE = True
"""Whether a via's whole move is judged by one native call (`first_move`) when the offset search
is native: switched off to compare against the per-offset Python loop."""


def pad_via_id(k: int) -> str:
    """The id of the k-th via the script declared at a pad."""
    return "pad via %d" % k


def enabled(settings) -> bool:
    """Whether a carried via may give way at all under these settings."""
    return settings.place_via_share > 0 or settings.place_via_move > 0 or settings.place_via_leave > 0 \
        or settings.place_via_route > 0 or settings.place_drops_keep < 1.0


def reach(settings) -> float:
    """How far past an item's copper what its vias do can reach."""
    return settings.place_via_share + max(settings.place_via_move, settings.place_via_leave, settings.place_via_route)


def least_cost(settings, tiers=None) -> float:
    """The least a spot where a via must give way costs beyond its score:
    the cheapest way these settings allow, and shorten when a via type it
    could use is "yes" in `tiers` (the fab profile's)."""
    shorten = any(t == "yes" for t in (tiers or {}).values())
    ways = [cost for on, cost in ((settings.place_via_share > 0, settings.score_via_share),
                                  (settings.place_via_move > 0, settings.score_via_move),
                                  (settings.place_via_leave > 0, settings.score_via_leave),
                                  (settings.place_via_route > 0, settings.score_via_route),
                                  (shorten, settings.score_via_shorten),
                                  (settings.place_drops_keep < 1.0, settings.score_via_drop)) if on]
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
    legs: list = field(default_factory=list)    # every track of its own that ends on it: one is its tail, more make it routed

    @property
    def routed(self) -> bool:
        return len(self.legs) > 1

    @property
    def shapes(self) -> list:
        return [s for s in (self.ring, self.hole) if s is not None] + list(self.legs)


@dataclass(frozen=True)
class Action:
    """What one carried via did."""
    kind: str                   # share | move | leave | shorten | drop
    via: str                    # its id
    owner: str
    home: str
    net: str
    at: tuple                   # where it stood as drawn
    to: tuple | None = None     # moved: its new centre; shared: the centre of the via it joins
    tail: object = None         # the Track drawn: a share's joining tail, a move's redrawn one, a leave's new one
    old_tail: tuple | None = None   # the drawn tail taken away, as its two ends (the via's end first)
    pad: tuple | None = None    # (refdes, pad number) of the pad it serves
    under: str = ""             # whose copper it met
    cost: float = 0.0
    shapes: tuple = field(default=(), compare=False)    # what it leaves on the board in its place
    target: str = ""            # shared: the id of the carried via it joins, which may not give way while it does
    tracks: tuple = ()          # route: the Tracks drawn in place of the via's own, every segment
    old_tracks: tuple = ()      # route: the drawn tracks taken away, each as its two ends (the via's end first)

    @property
    def moved_mm(self) -> float:
        return math.dist(self.at, self.to) if self.kind in ("move", "route") else 0.0


@dataclass
class Resolution:
    """What an item's placement makes its and others' carried vias do: the
    actions, their cost, or why one cannot give way."""
    actions: list = field(default_factory=list)
    cost: float = 0.0
    why: str | None = None
    blocker: object = None
    # A sentence naming the if-needed fab option that would have cleared this
    # spot, judged but never applied - set only when that is why the give
    # way that refused this candidate could not go through for real.
    needs: str | None = None


def _shift(s, dx: float, dy: float):
    from .occupancy import Shape
    return Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((x + dx, y + dy) for x, y in s.poly),
                 s.box.moved(dx, dy), s.label, carried=s.carried,
                 points=tuple((x + dx, y + dy) for x, y in s.points), given=s.given, claims=s.claims)


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
            g.legs.append(s)
    for g in out.values():
        if g.routed:                # a via with several tracks has no one tail (see `_give_routed`)
            g.tail = g.far = None
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


def _native_move_offsets(judge: "_Judge", ring, hole, offsets: tuple) -> list | None:
    """The `offsets` (as `_offsets` gives them) at which `ring` and `hole`
    (a via's own, at dx=dy=0 - the offsets are relative to their current
    position), shifted, meet nothing on the board `judge` was built against
    - every one, nearest first - or None when no native index is
    registered on `judge.others` (no native module, or this `resolve()`
    was not given a native-backed obstacle list). Python still judges each
    candidate's own copper (`mine`) and the tail separately (a tail is not
    a rigid translation of the via - see `_give`'s own doc on this); this
    replaces only the per-offset scan of the board itself, which is what
    `judge.hit(moved, pool, ...)` cost before: one native call per via
    instead of one Python conflict test per offset per obstacle
    (docs/superpowers/specs/2026-09-30-performance-zone-width-give-way-
    sweep-design.md section 2).

    `judge.others`'s native index is the WHOLE board within reach,
    including the via's own current ring and hole (and any other via also
    giving way to the same candidate) - real registered obstacles from
    every other item's point of view. `_Judge.near` excludes these
    (`judge.hidden`) before testing a via's move, since a via naturally
    sits near its own former position and a hole's clearance rule is
    net-blind (two holes of the SAME via, one shifted, would otherwise
    read as a hole-to-hole conflict with itself). The native call is given
    the same exclusion, by obstacle index into `judge.others`'s own
    backing shape list."""
    if not _NATIVE_MOVE_SEARCH or not offsets:
        return None
    entry = getattr(judge.others, "_native", None)
    if entry is None:
        return None
    index, shapes = entry
    # The same via against the same scan's board, with the same vias set aside, has the same clear
    # offsets: a via already placed meets many candidates in one scan, so the search runs once for it.
    # A via that moves with the candidate is at a new spot each time, so its key never repeats.
    key = (ring.poly, None if hole is None else hole.poly, frozenset(judge.hidden), judge.clearance, offsets)
    cache = judge.others.__dict__.setdefault("_clear_offsets", {})
    hit = cache.get(key)
    if hit is not None:
        return list(hit)
    from .occupancy import _to_native_shape
    occ = judge.occ
    py_shapes = [_to_native_shape(x, occ._body_refs, occ._leads, occ._margins)
                for x in ((ring,) if hole is None else (ring, hole))]
    skip = _hidden_skip(judge, shapes)
    clear = index.first_clear_offset(py_shapes, list(offsets), judge.clearance, False, skip)
    found = tuple(offsets[i] for i in clear)
    if len(cache) < occ.settings.place_via_clear_cache:
        cache[key] = found
    return list(found)


def _hidden_skip(judge: "_Judge", shapes: list) -> list:
    """The indices in a native index's backing `shapes` of the vias `judge` has set aside."""
    if not judge.hidden:
        return []
    cache = judge.others.__dict__.get("_carried_index")
    if cache is None or cache[0] is not shapes:
        by: dict = {}
        for i, s in enumerate(shapes):
            if s.carried:
                by.setdefault(s.carried, []).append(i)
        cache = judge.others.__dict__["_carried_index"] = (shapes, by)
    return sorted(i for h in judge.hidden for i in cache[1].get(h, ()))


def _net_tie_owners(occ) -> frozenset:
    """The refs of the footprints that are net ties: KiCad lets another net's copper meet their pads
    inside them (`Occupancy._net_tie_exclusion`), which the native conflict rules do not model."""
    hit = occ.__dict__.get("_net_tie_owner_set")
    if hit is None:
        hit = occ.__dict__["_net_tie_owner_set"] = frozenset(
            name for fp in occ.geometry.footprints if fp.net_tie_pads for name in (fp.ref, fp.inst))
    return hit


def _meets_net_tie(judge: "_Judge", shapes: list, box: Box, near: list) -> bool:
    """Whether a net tie's copper lies within a conflict's reach of `box`, on the board (`shapes`,
    a native index's backing list) or among `near` (the item's own copper and what earlier actions
    left): where it does the native rules and `_conflict` can disagree, and Python judges."""
    occ = judge.occ
    tied = _net_tie_owners(occ)
    if not tied:
        return False
    boxes = judge.others.__dict__.get("_net_tie_boxes")
    if boxes is None:
        boxes = judge.others.__dict__["_net_tie_boxes"] = [
            x.box for x in shapes if x.owner in tied and x.kind in ("pad", "through", "copper")]
    gap = occ._gap
    return any(b.overlaps(box, gap=gap) for b in boxes) or \
        any(o.owner in tied and o.kind in ("pad", "through", "copper") and o.box.overlaps(box, gap=gap)
            for o in near)


def _native_shape(judge: "_Judge", s):
    """`s` as the native module takes it, kept for this judge: the same shapes are asked again for
    each via of a resolution."""
    cache = judge.__dict__.setdefault("_native_shapes", {})
    hit = cache.get(id(s))
    if hit is None:
        from .occupancy import _to_native_shape
        occ = judge.occ
        hit = cache[id(s)] = (s, _to_native_shape(s, occ._body_refs, occ._leads, occ._margins))
    return hit[1]


def _native_tail_clear(judge: "_Judge", shape, own):
    """Whether `shape` (a share's tail) is clear of the board, `own` and what earlier actions left,
    judged natively; None where Python must judge it (as `_native_first_move`'s `used`)."""
    occ = judge.occ
    entry = getattr(judge.others, "_native", None)
    if not _NATIVE_TAIL_CLEAR or entry is None:
        return None
    index, shapes = entry
    gap = occ.gap_for(shape)
    near = [o for o in list(own) + judge.extra if o.box.overlaps(shape.box, gap=gap)]
    if _meets_net_tie(judge, shapes, shape.box, near):
        return None
    from .occupancy import _to_native_shape
    return index.tail_clear([_to_native_shape(shape, occ._body_refs, occ._leads, occ._margins)],
                            [_native_shape(judge, o) for o in near], judge.clearance, _hidden_skip(judge, shapes))


def _tail_hit(judge: "_Judge", shape, own) -> bool:
    """Whether `shape` meets the board less the vias set aside, `own` or what earlier actions left."""
    clear = _native_tail_clear(judge, shape, own)
    if clear is not None:
        return not clear
    return judge.hit([shape], judge.near(shape.box, judge.occ.gap_for(shape)), own, say=False) is not None


def _native_first_move(judge: "_Judge", g: "Group", mine: list, span: Box, offsets: list, first, pad, r: float,
                       tail_spec):
    """(used, (dx, dy) or None): the first of `offsets` (the ones `_native_move_offsets` found clear
    of the board) at which `g`'s ring, hole and tail, moved, also clear `mine` (the item's own copper)
    and what earlier actions left, and keep the tests `_give`'s loop applies - one native call in
    place of judging each offset in Python. `used` is False where the loop must run instead: no
    native index, the switch off, or a net tie near the move, whose rules the native ones do not model.
    `first`: the copper the via first met; `pad`: the pad it must stay inside, or None; `r` its radius;
    `tail_spec`: None, or (the tail's far end, its layer, its width), the tail redrawn from there."""
    occ = judge.occ
    entry = getattr(judge.others, "_native", None)
    if not _NATIVE_FIRST_MOVE or entry is None or not offsets:
        return False, None
    index, shapes = entry
    near = list(mine) + [o for o in judge.extra if o.box.overlaps(span, gap=occ._gap)]
    if _meets_net_tie(judge, shapes, span, near):
        return False, None
    met = _first_met(occ, g, first, judge.clearance)
    native_mine = [_native_shape(judge, o) for o in near]
    via = [_native_shape(judge, x) for x in ((g.ring,) if g.hole is None else (g.ring, g.hole))]
    skip = _hidden_skip(judge, shapes)
    tail = None
    if tail_spec is not None:
        far, layer, width = tail_spec
        _, proto = _tail_shape(g.owner, g.net, layer, width, far, g.centre, carried=g.id, given=g.id)
        tail = (_native_shape(judge, proto), tuple(far), width, occ.settings.geometry_cap_steps)
    first_arg = None if met is None else (met[0], met[1], r)
    pad_arg = None if pad is None else (pad.poly, r - 1e-5)
    start = 0
    while True:
        i = index.first_move(via, offsets, judge.clearance, skip, native_mine, g.centre, first_arg, pad_arg, tail,
                             start)
        if i is None:
            return True, None
        dx, dy = offsets[i]
        if occ.edge_margin is not None and occ._edge_why(_shift(g.ring, dx, dy).box):
            start = i + 1                   # the board's edge is judged here, per spot, as `_Judge.hit` does
            continue
        return True, (dx, dy)


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

    def vias(self, net: str, centre: tuple, reach: float, home: str) -> list:
        """(distance, centre, radius, carried id) of each via of `net` within
        `reach` of `centre`, nearest first: another item's than `home`, not a
        part's plated pad."""
        box = Box(centre[0] - reach, centre[1] - reach, centre[0] + reach, centre[1] + reach)
        carried_by = self.occ.__dict__.get("_carried", {})
        out = []
        for o in self.near(box, 0.0):
            if o.kind != "through" or o.net != net or o.owner in self.occ._footprint_refs:
                continue
            if carried_by.get(o.owner, o.owner) == home:
                continue                    # its own item's: that via may give way in turn
            c = _centre(o)
            d = math.dist(c, centre)
            if d <= reach + 1e-9:
                out.append((round(d, 9), c, o.box.width / 2.0, o.carried))
        out.sort()
        return out


class _Owner:
    """What a via's own item says about it: its pads, its face, its drops."""

    def __init__(self, occ, pads, face, groups_, dropped=None):
        self.occ, self.pads, self.face = occ, pads, face
        self.dropped = dict(dropped or {})
        self.counts: dict = {}
        for g in groups_.values():
            if g.net in occ.plane_nets:
                key = self.pad_of(g)[0]
                if key is not None:
                    self.counts[key] = self.counts.get(key, 0) + 1

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

    def keeps(self, key) -> tuple:
        """(drops the pad has, how many it must keep)."""
        n = self.counts.get(key, 0)
        return n, max(1, int(math.ceil(self.occ.settings.place_drops_keep * n - 1e-9)))


def _first_met(occ, g: Group, first, clearance):
    """(outline, clearance) of `first`, the copper a via met where it stood, when a via moved to a
    spot can still meet it (see `_still_meets`), else None."""
    if first is None or first.kind not in ("pad", "through", "copper") or not (first.layers & g.ring.layers) \
            or (first.net and first.net == g.net):
        return None
    if occ.geometry.has_footprint(first.owner) and occ.geometry.footprint(first.owner).net_tie_pads:
        return None
    clr = clearance if clearance is not None else occ.pair_clearance(g.net, first.net, "", first.owner)[0]
    return first.poly, clr


def _still_meets(occ, g: Group, first, clearance, r: float):
    """A quick test that a via moved to a spot still meets `first`, the
    copper it met where it stood, or None where there is none: its centre
    in that copper, or nearer it than its clearance plus the via's radius
    (the ring's copper reaches at least that far). Only a spot this passes
    is judged in full."""
    met = _first_met(occ, g, first, clearance)
    if met is None:
        return None
    poly, clr = met
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


def _shorten_kind(span: tuple) -> str:
    """micro (exactly two adjacent layers with an outer face), buried
    (neither end an outer face) or blind, for a via's board-layer span -
    the same convention layout.py's own via-kind classifier uses."""
    from .board_geometry import stackup_order
    ordered = sorted(span, key=stackup_order)
    outer = {ordered[0], ordered[-1]} & {CopperLayer.F, CopperLayer.B}
    if len(ordered) == 2 and outer:
        return "micro"
    return "blind" if outer else "buried"


def _shorten(occ, g: Group, judge: "_Judge", own, layer, met: str):
    """(Action, note, hint) for a drop reshaped to its own face and the nearest
    layer of its own plane, when the fab profile allows drawing it for
    real; (None, note, hint) when it is only judged (if-needed) or not
    possible at all - `note` names the span an if-needed tier would have
    used, else None; `hint` says a shorter via would clear it but the tier
    is "no", else None."""
    from .board_geometry import stackup_order
    s, geo = occ.settings, occ.geometry
    board = sorted(geo.layers, key=stackup_order)
    if layer not in board:
        return None, None, None
    plane_layers = getattr(occ, "plane_layers", {})
    own_i = board.index(layer)
    reach_layers = sorted((l for l, nets in plane_layers.items() if g.net in nets and l != layer and l in board),
                          key=lambda l: abs(board.index(l) - own_i))
    if not reach_layers:
        return None, None, None
    nearest = reach_layers[0]
    lo, hi = sorted((own_i, board.index(nearest)))
    span = tuple(board[lo:hi + 1])
    if len(span) < 2 or len(span) == len(board):
        return None, None, None            # already this short, or no shorter than a through via
    kind = _shorten_kind(span)
    tier = getattr(occ, "fab_via_tiers", {}).get(kind, "no")
    layers = frozenset(span)
    ring = replace(g.ring, layers=layers, given=g.id)
    shapes = (ring,) if g.hole is None else (ring, replace(g.hole, layers=layers, given=g.id))
    pool = judge.near(Box.union([x.box for x in shapes]), occ._gap)
    would_clear = judge.hit(shapes, pool, own, say=False) is None
    if tier == "no":
        return None, None, ("a %s via from %s to %s would clear this; the fab profile does not allow %s vias" % (
            kind, span[0].value, span[-1].value, kind)) if would_clear else None
    note = "a %s via shortened to %s-%s (via.%s is if-needed in fab-profile.json)" % (
        kind, span[0].value[:-3], span[-1].value[:-3], kind) if would_clear else None
    if tier == "yes" and would_clear:
        return Action("shorten", g.id, g.owner, g.home, g.net, g.centre, g.centre, None, None, None, met,
                      s.score_via_shorten, shapes), None, None
    return None, note, None


def _tail_widths(occ, net: str) -> tuple:
    """The widths a new tail of `net` may be drawn at, widest first: the net class's track width, then
    narrower in 0.05 mm steps down to the board's minimum track width (just the net's where that is
    not known or is not narrower)."""
    geo = occ.geometry
    top = geo.netclass(net).track_width if net in geo.nets else 0.2
    least = min(top, geo.min_track_width) if geo.min_track_width > 0 else top
    out = [top]
    w = top
    while w - _TAIL_STEP > least + 1e-9:
        w = round(w - _TAIL_STEP, 6)
        out.append(w)
    if least < out[-1] - 1e-9:
        out.append(round(least, 6))
    return tuple(out)


_TAIL_STEP = 0.05
"""How much narrower each width a leaving via's tail may be drawn at is."""


def _moved(g: Group, dx: float, dy: float, tail, width: float):
    """(its new centre, the shapes it leaves, the Track drawn or None) for `g` moved by (dx, dy), its
    tail (`tail`: the far end, the layer and the widths) drawn from its far end at `width`."""
    to = (round(g.centre[0] + dx, 9), round(g.centre[1] + dy, 9))
    moved = [replace(_shift(g.ring, dx, dy), given=g.id)]
    if g.hole is not None:
        moved.append(replace(_shift(g.hole, dx, dy), given=g.id))
    track = None
    if tail is not None:
        track, shape = _tail_shape(g.owner, g.net, tail[1], width, tail[0], to, carried=g.id, given=g.id)
        moved.append(shape)
    return to, moved, track


def _find_move(occ, g: Group, judge: "_Judge", own, first, limit: float, pad, tail):
    """(dx, dy, tail width) of the nearest spot within `limit` of `g` where its ring, hole and tail are
    clear of the board (less the vias set aside), `own` and what earlier actions left, else None.
    `pad`: the pad it must stay inside, or None. `tail`: None, or (the tail's far end, its layer, the
    widths it may be drawn at, widest first): the spot is the nearest where the narrowest is clear, and
    the width the widest that is clear there."""
    s = occ.settings
    r = _radius(g)
    widths = () if tail is None else tail[2]
    span = g.ring.box.inflate(limit)
    if g.tail is not None:
        span = Box.union([span, g.tail.box.inflate(limit)])
    mine = [o for o in own if o.box.overlaps(span, gap=occ._gap)]
    all_offsets = _offsets(limit, s.place_via_move_step)
    # The native search only knows the STATIC board (judge.others'
    # persistent index): it cannot see `judge.hidden` (another via also
    # giving way to this same candidate, excluded from `pool` while it
    # is decided) or `judge.extra` (copper an earlier give-way in this
    # same resolve() call already left behind) - both candidate-scoped,
    # not board state. The first is given to it as the vias to set
    # aside, the second as shapes beside `mine`. It finds the
    # board-clear offsets once per scan (`_native_move_offsets`) and
    # judges each candidate's move whole (`_native_first_move`). Where
    # either is not available the loop below judges each offset in
    # Python, as the reference.
    native_clear = _native_move_offsets(judge, g.ring, g.hole, all_offsets)
    candidates = native_clear if native_clear is not None else all_offsets
    narrow = None if tail is None else (tail[0], tail[1], widths[-1])
    used, at = _native_first_move(judge, g, mine, span, candidates, first, pad, r, narrow) \
        if native_clear is not None else (False, None)
    if used:
        if at is None:
            return None
        width = _widest(judge, g, mine, at, tail)
        return at[0], at[1], width if width is not None else widths[-1]
    pool = judge.near(span, occ._gap)
    still = _still_meets(occ, g, first, judge.clearance, r)
    for dx, dy in candidates:
        to = (round(g.centre[0] + dx, 9), round(g.centre[1] + dy, 9))
        if pad is not None and not _disc_inside(pad.poly, to, r - 1e-5):
            continue
        if still is not None and still(to):
            continue
        ring = _shift(g.ring, dx, dy)
        if native_clear is None and first is not None and first.box.overlaps(ring.box, gap=occ._gap) \
                and occ._conflict(ring, first, judge.clearance, say=False):
            continue                    # still on what it met: most spots near it are (no-native path only)
        moved = [replace(ring, given=g.id)]
        if g.hole is not None:
            moved.append(replace(_shift(g.hole, dx, dy), given=g.id))
        if judge.hit(moved, pool, mine, say=False):
            continue
        if tail is None:
            return dx, dy, 0.0
        width = _widest(judge, g, mine, (dx, dy), tail, pool)
        if width is not None:
            return dx, dy, width
    return None


def _widest(judge: "_Judge", g: Group, mine: list, at: tuple, tail, pool=None):
    """The widest of `tail`'s widths whose tail, drawn to `g` moved by `at`, is clear; 0.0 where there is
    no tail; None where none is."""
    if tail is None:
        return 0.0
    to = (round(g.centre[0] + at[0], 9), round(g.centre[1] + at[1], 9))
    for width in tail[2]:
        _, shape = _tail_shape(g.owner, g.net, tail[1], width, tail[0], to, carried=g.id, given=g.id)
        if pool is None:
            pool = judge.near(shape.box, judge.occ.gap_for(shape))
        if judge.hit([shape], pool, mine, say=False) is None:
            return width
    return None


def _give(occ, g: Group, judge: _Judge, own, who: _Owner, met: str, drops_now: dict, first=None):
    """(Action, why not, needs) for the first way `g` can give way, else
    (None, why not, an if-needed note or None), judged against `judge` and
    the item's own copper `own`. `first`: the copper it met, which a move is
    judged against before the rest."""
    s = occ.settings
    geo = occ.geometry
    if g.routed:
        return _give_routed(occ, g, judge, own, who, met)
    pad_key, pad, inside = who.pad_of(g)
    layer = who.layer(g, pad)
    old = (g.centre, g.far) if g.tail is not None else None
    said = []
    if s.place_via_share > 0:
        targets = judge.vias(g.net, g.centre, s.place_via_share, g.home)
        width = geo.netclass(g.net).track_width if g.net in geo.nets else 0.2
        start = g.far if g.far is not None else g.centre
        for d, c, r, target in targets:
            if d <= r:                          # on its spot: nothing to draw, its tail joins that via as it is
                left = () if g.tail is None else (replace(g.tail, carried="", points=(), given=g.id),)
                if left and _tail_hit(judge, left[0], own):
                    continue
                # a tail an earlier giving way drew is the plan's to draw; the one its item drew is on the board
                kept = Track(g.net, next(iter(g.tail.layers)), _width(g.tail), Location(*g.far),
                             Location(*g.centre)) if g.tail is not None and g.tail.given else None
                return Action("share", g.id, g.owner, g.home, g.net, g.centre, c, kept, None, pad_key, met,
                              s.score_via_share, left, target), None, None
            track, shape = _tail_shape(g.owner, g.net, layer, width, start, c, given=g.id)
            if _tail_hit(judge, shape, own):
                continue
            return Action("share", g.id, g.owner, g.home, g.net, g.centre, c, track, old, pad_key, met,
                          s.score_via_share, (shape,), target), None, None
        said.append("no %s via within %.2f mm to share" % (g.net, s.place_via_share) if not targets else
                    "no tail to the %s via%s within %.2f mm is clear" % (g.net, "s" if len(targets) > 1 else "",
                                                                         s.place_via_share))
    if s.place_via_move > 0:
        tail = None if g.tail is None else (g.far, next(iter(g.tail.layers)), (_width(g.tail),))
        found = _find_move(occ, g, judge, own, first, s.place_via_move, pad if inside else None, tail)
        if found is not None:
            dx, dy, width = found
            to, moved, track = _moved(g, dx, dy, tail, width)
            return Action("move", g.id, g.owner, g.home, g.net, g.centre, to, track, old, pad_key, met,
                          s.score_via_move, tuple(moved)), None, None
        said.append("no spot within %.2f mm%s is clear" % (s.place_via_move, " inside its pad" if inside else ""))
    if inside and g.tail is None and s.place_via_leave > 0 and pad is not None and layer in pad.layers:
        # no spot inside the pad is clear: leave it, joined by a new tail from where it stood
        widths = _tail_widths(occ, g.net)
        tail = (g.centre, layer, widths)
        found = _find_move(occ, g, judge, own, first, s.place_via_leave, None, tail)
        if found is not None:
            dx, dy, width = found
            to, moved, track = _moved(g, dx, dy, tail, width)
            return Action("leave", g.id, g.owner, g.home, g.net, g.centre, to, track, None, pad_key, met,
                          s.score_via_leave, tuple(moved)), None, None
        said.append("no spot within %.2f mm is clear to leave its pad by a tail" % s.place_via_leave)
    needs = None
    if g.net in occ.plane_nets:
        action, note, hint = _shorten(occ, g, judge, own, layer, met)
        if action is not None:
            return action, None, None
        if hint is not None:
            said.append(hint)
        if note is not None:
            needs = note
            said.append("no spot; it places with %s" % note)
    if g.net not in occ.plane_nets:
        said.append("%s is not a plane net, so it is no drop" % g.net)
    elif pad_key is None:
        said.append("it serves no pad of its own")
    else:
        n, keep = who.keeps(pad_key)
        gone = who.dropped.get(pad_key, 0) + drops_now.get(pad_key, 0)
        if n - gone - 1 >= keep:
            drops_now[pad_key] = drops_now.get(pad_key, 0) + 1
            return Action("drop", g.id, g.owner, g.home, g.net, g.centre, None, None, old, pad_key, met,
                          s.score_via_drop, ()), None, None
        said.append("%s pad %s keeps %d of its %d drops, and must keep %d" % (pad_key[0], pad_key[1], n - gone,
                                                                              n, keep))
    return None, ", ".join(said), needs


def _pads(occ, shapes) -> list:
    return [((s.owner, s.label), s) for s in shapes
            if s.kind in ("pad", "through") and not s.carried and s.owner in occ._footprint_refs]


def _home_owner(occ, home: str) -> _Owner:
    """What an item already placed says about its vias: the part's or the
    cell's pads where they stand, its face, the drops it had and has given.
    Kept until the board changes."""
    cache = occ.__dict__.setdefault("_placed_groups_owners", {})
    if home not in cache:
        cache[home] = _placed_owner(occ, home)
    return cache[home]


def _placed_owner(occ, home: str) -> _Owner:
    cell = occ.geometry.cells.get(home)
    refs = [m.ref for m in cell.members] if cell is not None else [home]
    pads = [p for ref in refs if ref in occ.items for p in _pads(occ, occ.items[ref].shapes)]
    face = occ.items[refs[0]].reference.face if refs and refs[0] in occ.items else Face.FRONT
    if cell is not None:
        pristine = occ._pristine_copper.get(home) or [c for c in occ.copper if c.owner == home]
        pristine = list(pristine) + [s for ref in refs for s in occ.geometry_of(ref).shapes]
    else:
        pristine = occ.geometry_of(home).shapes
    dropped: dict = {}
    for a in occ.given_way.values():
        if a.home in refs + [home] and a.kind == "drop" and a.pad is not None:
            dropped[a.pad] = dropped.get(a.pad, 0) + 1
    return _Owner(occ, pads, face, groups(occ, pristine), dropped)


def resolve(occ, item, placement, clearance=None, others=None) -> Resolution:
    """What `item` at `placement` makes the carried vias do - those of items
    already placed that its own copper meets, then its own that meet the
    board - or why one of them cannot give way. The item less its carried
    vias is taken to be legal there."""
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
    # what a via may not sit on: copper and holes, and a courtyard where the board's house rule says so
    kinds = _COPPER_AND_HOLES | ({"courtyard"} if occ.vias_block_courtyards else frozenset())
    fixed = [x for x in mine if not x.carried and x.kind in kinds]
    own = groups(occ, mine)
    # 1. the vias already placed that the item's own copper meets
    skip = geom.owners | occ.pending
    if fixed:
        extent = Box.union([x.box for x in fixed])
        owners: dict = {}
        drops_placed: dict = {}
        met = []
        for g in occ.placed_groups().values():
            if g.home in skip or g.owner in skip or not g.ring.box.overlaps(extent, gap=occ._gap):
                continue
            hit = None
            parts = g.shapes
            for x in fixed:
                gap = occ.gap_for(x)
                for o in parts:
                    if x.box.overlaps(o.box, gap=gap):
                        why = occ._conflict(x, o, clearance)
                        if why:
                            hit = (why, x)
                            break
                if hit:
                    break
            if hit is not None:
                met.append((g, hit))
        judge.hidden |= {g.id for g, _ in met}          # none of them is there for another to share
        for g, hit in met:
            sharer = next((a for a in occ.given_way.values() if a.kind == "share" and a.target == g.id), None)
            if sharer is not None:
                return _refused(occ, res, "%s; the via %s at (%.2f, %.2f) (%s) cannot give way: the via at "
                                "(%.2f, %.2f) of %s shares it" % (hit[0], g.net, g.centre[0], g.centre[1],
                                                                 _owner_name(occ, g), sharer.at[0], sharer.at[1],
                                                                 _owner_name(occ, Group(sharer.via, sharer.owner,
                                                                                        sharer.home, sharer.net))),
                                g.ring)
            who = owners.get(g.home) or owners.setdefault(g.home, _home_owner(occ, g.home))
            action, why_not, needs = _give(occ, g, judge, [x for x in mine if x.kind in kinds],
                                           who, occ.who(hit[1].owner), drops_placed.setdefault(g.home, {}), hit[1])
            if action is None:
                res.needs = needs
                if needs:
                    occ.needs[geom.owners] = needs
                return _refused(occ, res, "%s; the via %s at (%.2f, %.2f) (%s) cannot give way: %s" % (
                    hit[0], g.net, g.centre[0], g.centre[1], _owner_name(occ, g), why_not), g.ring)
            judge.extra += list(action.shapes)
            res.actions.append(action)
            res.cost += action.cost
    # 2. its own vias that meet the board
    if own:
        mine_face = placement.face
        who = _Owner(occ, _pads(occ, mine), mine_face, own)
        meeting = []
        for g in own.values():
            pool = judge.near(Box.union([x.box for x in g.shapes]), occ._gap)
            hit = judge.hit(g.shapes, pool)
            if hit is not None:
                meeting.append((g, hit))
        if meeting:
            gone = {g.id for g, _ in meeting}
            keep = [x for x in mine if x.kind in _COPPER_AND_HOLES and x.carried not in gone]
            drops_now: dict = {}
            for g, (why, o) in meeting:
                met = "the edge" if o is None else occ.who(o.owner) if o.owner else \
                    ("a via" if o.kind == "through" else "a track")
                action, why_not, needs = _give(occ, g, judge, keep, who, met, drops_now, o)
                if action is None:
                    res.needs = needs
                    if needs:
                        occ.needs[geom.owners] = needs
                    return _refused(occ, res, "%s; it cannot give way: %s" % (why, why_not), o)
                keep += list(action.shapes)
                res.actions.append(action)
                res.cost += action.cost
    return res


def near_carried(occ, item, region: Box) -> bool:
    """Whether a via may give way to `item` within `region`: it carries one,
    or an item already placed has one there."""
    if occ.carries(item):
        return True
    skip = occ._geometry(item).owners | occ.pending
    return any(g.home not in skip and g.owner not in skip and g.ring.box.overlaps(region, gap=occ._gap)
               for g in occ.placed_groups().values())


class ScanGiveWay:
    """What a scan needs to let vias give way to its item: the item less
    its carried vias and the obstacles it is judged against (the board less
    the placed items' carried vias), natively where the scan is, and the
    whole board for the vias themselves."""

    def __init__(self, occ, item, face, rots, region: Box, clearance, native: bool):
        from .occupancy import WithoutCarried
        self.occ, self.of, self.clearance = occ, item, clearance
        self.item = WithoutCarried(item)
        geom = occ._geometry(item)
        self.others = occ.obstacles(geom, region, carried=False)
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


def _owner_name(occ, g: Group) -> str:
    if g.owner.startswith("via at "):
        return g.owner[len("via at "):]
    return "cell %s" % g.owner if g.owner in occ.geometry.cells else g.owner


def _refused(occ, res: Resolution, why: str, o) -> Resolution:
    from .occupancy import Blocker, _blocker_kind
    res.why = why
    res.blocker = Blocker("edge", "", frozenset()) if o is None else \
        Blocker(_blocker_kind(o.kind), occ.blame_owner(o), frozenset(o.faces))
    return res


def apply(occ, res: Resolution, by: str) -> None:
    """Leave on the board what `res` decided, `by` the item placed: each via
    that gave way taken out of its item, and what it left in its place put
    in; the item as drawn is kept to put back if it is placed again."""
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
            a = replace(a, at=before.at, old_tail=before.old_tail if before.old_tail is not None else a.old_tail,
                        old_tracks=before.old_tracks or a.old_tracks)
        occ.given_way[a.via] = a
        occ._given_by.setdefault(a.via, []).append(by)
    if res.actions:
        occ._changed()


def sharers(occ, via: str) -> list:
    """The ids of the vias that gave way by sharing `via`."""
    return [v for v, a in occ.given_way.items() if a.kind == "share" and a.target == via]


def undo(occ, via: str) -> None:
    """Put a via that gave way back as its item drew it, and those that
    share it, since it may no longer be where they joined it."""
    for v in sharers(occ, via):
        undo(occ, v)
    a = occ.given_way.pop(via, None)
    occ._given_by.pop(via, None)
    if a is None:
        return
    if a.home in occ._pristine:
        drawn = [x for x in occ._pristine[a.home].shapes if x.carried == via]
        g = occ.items[a.home]
        occ.items[a.home] = replace(g, shapes=tuple(x for x in g.shapes if x.carried != via and x.given != via)
                                    + tuple(drawn))
    elif a.home in occ._pristine_copper:
        drawn = [x for x in occ._pristine_copper[a.home] if x.carried == via]
        occ.copper = [c for c in occ.copper if c.carried != via and c.given != via] + drawn
    occ._changed()


def report(occ) -> list:
    """(home, sentence) per item whose carried vias gave way, a clause per
    net: "6 GND vias shared, 2 moved up to 0.25 mm, 1 dropped under U3"."""
    by: dict = {}
    for a in occ.given_way.values():
        by.setdefault(a.home, {}).setdefault(a.net, []).append(a)
    out = []
    for home in sorted(by):
        said = []
        for net in sorted(by[home]):
            acts = by[home][net]
            parts = []
            for kind, verb in (("share", "shared"), ("move", "moved"), ("route", "re-routed"), ("leave", "left its pad"), ("shorten", "shortened"), ("drop", "dropped")):
                done = [a for a in acts if a.kind == kind]
                if not done:
                    continue
                if kind in ("move", "route"):
                    far = max(a.moved_mm for a in done)
                    verb += (" %.2f mm" if len(done) == 1 else " up to %.2f mm") % far
                n = len(done)
                parts.append(("%d %s via%s %s" % (n, net, "" if n == 1 else "s", verb)) if not parts else
                             "%d %s" % (n, verb))
            under = sorted({a.under for a in acts if a.under})
            said.append(", ".join(parts) + (" under %s" % ", ".join(under) if under else ""))
        out.append((home, "; ".join(said)))
    return out


# ------------------------------------------------------------------ a routed via
# (docs/superpowers/specs/2026-10-01-routed-via-moves-design.md)

_ON = 1e-6
"""How near two ends are to be the same point: a leg's end and the via's centre are the same number."""


def _chains(g: Group) -> list:
    """(far end, layer, width) of each track of a routed via: the leg that starts at its centre, followed
    through the legs that join it end to end (a track a move rebuilt is several), to the end furthest
    from the via. The layer and width are the first leg's."""
    def at(p, q) -> bool:
        return abs(p[0] - q[0]) <= _ON and abs(p[1] - q[1]) <= _ON
    out, used = [], set()
    for head in g.legs:
        if not at(head.points[0], g.centre):
            continue
        cur = head
        while True:
            used.add(id(cur))
            nxt = next((l for l in g.legs if id(l) not in used and at(l.points[0], cur.points[1])), None)
            if nxt is None:
                break
            cur = nxt
        out.append((cur.points[1], next(iter(head.layers)), _width(head)))
    return out


def _far_ends(g: Group) -> list:
    """Where the tracks of a routed via end away from it: they stay when it moves."""
    return [far for far, _, _ in _chains(g)]


def _rebuilt(occ, g: Group, judge: "_Judge", mine: list, chains: list, to: tuple):
    """The Tracks that join each chain's far end to `to`, drawn as a declared track is (copper.octilinear
    between the ends, its right angles chamfered), each of its layer and width, or None where one has no
    length or a segment of one is not clear of the board, `mine` and what earlier actions left."""
    from .copper import chamfer_cuts, octilinear, polyline_tracks
    s = occ.settings
    drawn = []
    for far, layer, width in chains:
        if math.dist(far, to) <= _ON:
            return None

        def clear(a, b, layer=layer, width=width) -> bool:
            return not _tail_hit(judge, _tail_shape(g.owner, g.net, layer, width, (a.x, a.y), (b.x, b.y))[1], mine)
        path = octilinear([Location(*far), Location(*to)], [False, False], clear, tolerance=s.copper_straight_tolerance)
        cut, diagonals = chamfer_cuts(path, s.copper_chamfer)
        cuts = {(round(a.x, 6), round(a.y, 6), round(b.x, 6), round(b.y, 6)) for a, b in diagonals}
        for t in polyline_tracks(g.net, layer, width, cut):
            if not clear(t.start, t.end):
                return None
            drawn.append(replace(t, chamfer_cut=(round(t.start.x, 6), round(t.start.y, 6), round(t.end.x, 6),
                                                 round(t.end.y, 6)) in cuts))
    return drawn


def _give_routed(occ, g: Group, judge: "_Judge", own, who: _Owner, met: str):
    """(Action, why not, None) for a via that two or more of its item's tracks end on, moved up to
    `place.via_route`, nearest spot first, with each track rebuilt from its far end; the spot is used only
    when its ring, its hole and every track are clear, so one that fails leaves them all as drawn."""
    s = occ.settings
    pad_key, pad, inside = who.pad_of(g)
    chains = _chains(g)
    limit = s.place_via_route
    r = _radius(g)
    span = Box.union([g.ring.box.inflate(limit)] + [x.box.inflate(limit) for x in g.legs])
    mine = [o for o in own if o.box.overlaps(span, gap=occ._gap)]
    offsets = _offsets(limit, s.place_via_move_step)
    clear_spots = _native_move_offsets(judge, g.ring, g.hole, offsets)
    # the native offsets are clear of the board; what is left to judge is the item's own copper and what
    # earlier actions left, and without them every offset, against the board too
    pool = [o for o in judge.extra if o.box.overlaps(span, gap=occ._gap)] if clear_spots is not None else \
        judge.near(span, occ._gap)
    for dx, dy in (offsets if clear_spots is None else clear_spots):
        to = (round(g.centre[0] + dx, 9), round(g.centre[1] + dy, 9))
        if inside and not _disc_inside(pad.poly, to, r - 1e-5):
            continue
        moved = [replace(_shift(g.ring, dx, dy), given=g.id)]
        if g.hole is not None:
            moved.append(replace(_shift(g.hole, dx, dy), given=g.id))
        if judge.hit(moved, pool, mine, say=False):
            continue
        tracks = _rebuilt(occ, g, judge, mine, chains, to)
        if tracks is None:
            continue
        for t in tracks:
            moved.append(_tail_shape(g.owner, g.net, t.layer, t.width, (t.start.x, t.start.y), (t.end.x, t.end.y),
                                     carried=g.id, given=g.id)[1])
        old = tuple((tuple(x.points[0]), tuple(x.points[1])) for x in g.legs)
        return Action("route", g.id, g.owner, g.home, g.net, g.centre, to, None, None, pad_key, met,
                      s.score_via_route, tuple(moved), tracks=tuple(tracks), old_tracks=old), None, None
    return None, "no spot within %.2f mm%s is clear with its %d tracks rebuilt" % (
        limit, " inside its pad" if inside else "", len(chains)), None
