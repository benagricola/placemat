"""The Board object a layout script declares to, and the Plan resolve()
produces from it.

Board answers questions about the generated board, records placement and
copper declarations, and resolves them in priority order (setup, FIXED,
EDGE, searched cells, FIXED copper, loose parts, remaining copper) against
the occupancy model. Plan holds the resolved placements, copper ops and
findings for the writer and the run record."""
from __future__ import annotations

from dataclasses import dataclass, field

from .copper import (CopperOp, Pour, Track, Via, Zone, board_zone_outline, finger_ops, polyline_tracks,
                     resolve_bridges)
from .geometry import polygon_box
from .occupancy import Occupancy, Shape
from .placement import Placement
from .placer import box_centered_placement, edge_placement, scan
from .board_geometry import CellGeom, Footprint, BoardGeometry
from .values import (Box, Cell, CellPadRef, CopperLayer, Edge, Face, LinkWeight, Location, Net, PadRef, Part,
                     Priority, X, Y)

RANK_FIXED, RANK_EDGE, RANK_CELL, RANK_FIXED_COPPER, RANK_LOOSE, RANK_COPPER = range(6)


@dataclass
class PlaceIntent:
    key: str                    # instance name or cell name
    item: object                # Footprint or CellGeom (from the generated board)
    kind: str                   # part | cell
    priority: Priority
    rotation: float
    face: Face
    at: Location | None = None
    center: Location | None = None
    edge: Edge | None = None
    along: float | None = None
    clearance: float | None = None
    near: Location | None = None
    radius: float = 3.0
    step: float = 0.2
    rotations: tuple = ()
    why: str = ""
    index: int = 0

    @property
    def rank(self):
        if self.priority is Priority.FIXED:
            return (RANK_FIXED, self.index)
        if self.priority is Priority.EDGE:
            return (RANK_EDGE, self.index)
        return (RANK_CELL if self.kind == "cell" else RANK_LOOSE, self.index)


@dataclass
class CopperIntent:
    key: str
    net: str
    priority: Priority
    plan: object                # callable(ctx) -> list[CopperOp]
    refs: tuple = ()            # every PadRef/CellPadRef it depends on
    why: str = ""
    index: int = 0
    bridge: bool = False        # tracks: may pass under copper they cross

    @property
    def rank(self):
        return (RANK_FIXED_COPPER if self.priority is Priority.FIXED else RANK_COPPER, self.index)


@dataclass
class Link:
    """One priced connection: pad a to pad b, and what a millimetre costs."""
    a: tuple                    # (refdes, pad number)
    b: tuple
    weight: int
    limit_mm: float | None
    why: str
    a_ref: object
    b_ref: object
    achieved_mm: float | None = None

    @property
    def within_limit(self) -> bool:
        return self.limit_mm is None or (self.achieved_mm is not None and self.achieved_mm <= self.limit_mm + 1e-9)


@dataclass
class Step:
    item: str
    kind: str
    priority: Priority
    placement: Placement | None = None
    moved_mm: float = 0.0
    note: str = ""
    why: str = ""
    ops: int = 0


@dataclass
class Plan:
    geometry: BoardGeometry
    occupancy: Occupancy
    steps: list[Step] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    copper: list = field(default_factory=list)
    links: list = field(default_factory=list)
    outline: Box | None = None
    chamfer: float = 0.0
    radius: float = 0.0
    _items: dict = field(default_factory=dict, repr=False)

    def step(self, key: str) -> Step:
        for s in self.steps:
            if s.item == key:
                return s
        raise KeyError("nothing placed as %r" % key)

    def placement(self, key: str) -> Placement:
        return self.step(key).placement

    def box(self, key: str) -> Box:
        return self.occupancy.body_box(self._items[key], self.placement(key))

    @property
    def placements(self) -> dict[str, Placement]:
        return {s.item: s.placement for s in self.steps if s.placement is not None}

    @property
    def plane_nets(self) -> set:
        """Nets served by a pour, plane or finger: routing leaves them alone."""
        return {op.net for op in self.copper if isinstance(op, (Pour, Zone))}


class Board:
    """One board being laid out. Questions are answered from the geometry read
    off the generated .kicad_pcb; declarations are collected and resolved
    together."""

    def __init__(self, geometry: BoardGeometry, edge_margin: float = 0.0, clearance: float | None = None,
                 via_drill: float = 0.3, via_size: float = 0.6):
        self.geometry = geometry
        self.edge_margin = edge_margin
        self.clearance = clearance
        self.via_drill, self.via_size = via_drill, via_size
        self._intents: list[PlaceIntent] = []
        self._copper: list[CopperIntent] = []
        self._links: list[Link] = []
        self._free_nets: set = set()
        self._outline: Box | None = geometry.outline_box
        self._chamfer = 0.0
        self._radius = 0.0
        self.width = self._outline.width if self._outline else None
        self.height = self._outline.height if self._outline else None

    # ------------------------------------------------------------ questions
    def part(self, key) -> Footprint:
        return self.geometry.footprint(key)

    def cell(self, key) -> CellGeom:
        return self.geometry.cell(key)

    def pad(self, part, key):
        return self.geometry.pad(part, key)

    def cell_pad(self, cell, **kw):
        return self.geometry.cell_pad(cell, **kw)

    def net(self, net) -> str:
        return self.geometry.require_net(net)

    def _item(self, item):
        if isinstance(item, Cell):
            return self.geometry.cell(item), item.name, "cell"
        if isinstance(item, Part):
            fp = self.geometry.footprint(item)
            return fp, fp.inst, "part"
        if isinstance(item, CellGeom):
            return item, item.name, "cell"
        if isinstance(item, Footprint):
            return item, item.inst, "part"
        raise TypeError("place() takes a Part or a Cell, not %r" % (item,))

    def extent(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """The item's body box at `rotation`, placed at the origin: a size, not a place."""
        geom, _, _ = self._item(item)
        occ = Occupancy(self.geometry, self.edge_margin, board_box=None)
        return occ.body_box(geom, Placement(Location(0.0, 0.0), rotation, face))

    def _pad_ref(self, ref):
        """Validate a pad reference now; return (refdes, pad number, dx, dy)."""
        if isinstance(ref, PadRef):
            p = self.geometry.pad(ref.part, ref.key)
            return (p.owner, p.number, ref.dx, ref.dy)
        if isinstance(ref, CellPadRef):
            p = self.geometry.cell_pad(ref.cell, net=ref.net, number=ref.number, ref_prefix=ref.ref_prefix)
            return (p.owner, p.number, ref.dx, ref.dy)
        raise TypeError("not a pad reference: %r" % (ref,))

    # ------------------------------------------------------------ setup
    def size(self, width: float, height: float, chamfer: float = 0.0, radius: float = 0.0):
        """The board outline: a rectangle at the origin, chamfered or rounded."""
        if width <= 0 or height <= 0:
            raise ValueError("board size must be positive")
        self._outline = Box(0.0, 0.0, float(width), float(height))
        self._chamfer, self._radius = chamfer, radius
        self.width, self.height = float(width), float(height)

    # ------------------------------------------------------------ placement
    def place(self, item, *, at: Location | None = None, center: Location | None = None,
              rotation: float = 0.0, face: Face = Face.FRONT, edge: Edge | None = None,
              along: float | None = None, clearance: float | None = None,
              near: Location | None = None, radius: float = 3.0, step: float = 0.2,
              rotations=(), priority: Priority | None = None, why: str = "") -> PlaceIntent:
        """Declare where an item goes.

        at=       a part's origin (a cell's box centre)      -> FIXED
        center=   the body box centre                        -> FIXED
        edge=, along=, clearance=   flush to a board edge    -> EDGE
        near=     a hint; the placer searches around it      -> DEFAULT
        nothing   searched from where the generator left it  -> DEFAULT
        """
        geom, key, kind = self._item(item)
        if any(i.key == key for i in self._intents):
            raise ValueError("%s is already placed; one declaration per item" % key)
        if sum(x is not None for x in (at, center, edge, near)) > 1:
            raise ValueError("%s: give one of at=, center=, edge= or near=" % key)
        if edge is not None and along is None:
            raise ValueError("%s: edge= needs along=" % key)
        if priority is None:
            priority = Priority.FIXED if (at is not None or center is not None) else \
                Priority.EDGE if edge is not None else Priority.DEFAULT
        if kind == "cell" and at is not None and center is None:
            center, at = at, None
        intent = PlaceIntent(key, geom, kind, priority, float(rotation), face, at, center, edge, along,
                             clearance if clearance is not None else self.edge_margin, near, radius, step,
                             tuple(rotations), why, len(self._intents))
        self._intents.append(intent)
        return intent

    def _is_searched(self, refdes: str) -> bool:
        fp = self.geometry.footprint(refdes)
        for i in self._intents:
            if i.priority is Priority.DEFAULT and (i.key == fp.inst or (i.kind == "cell" and fp.cell == i.key)):
                return True
        return False

    # ------------------------------------------------------------ links
    def link(self, a, b, weight=LinkWeight.DEFAULT, limit_mm: float | None = None, why: str = "") -> Link:
        """Price one connection between two pads. `weight` is a LinkWeight or
        any integer (0: the length of this connection does not matter);
        `limit_mm` makes it a bound the run reports against."""
        w = int(weight)
        if w < 0:
            raise ValueError("a link weight is 0 or more, not %r" % (weight,))
        ka, kb = self._pad_ref(a), self._pad_ref(b)
        link = Link((ka[0], ka[1]), (kb[0], kb[1]), w, limit_mm, why, a, b)
        self._links.append(link)
        return link

    def free_net(self, net):
        """A net whose length on this board does not matter (its off-board
        run dwarfs it): it seeds nothing and pulls nothing."""
        self._free_nets.add(self.geometry.require_net(net))

    def _plane_nets(self) -> set:
        return {c.net for c in self._copper if c.key.split(" ")[0] in ("pour", "plane", "finger")}

    def _link_weight(self, pad_a: tuple, pad_b: tuple) -> int:
        for l in self._links:
            if {l.a, l.b} == {pad_a, pad_b}:
                return l.weight
        return int(LinkWeight.DEFAULT)

    def _targets(self, item, occ: Occupancy, placed: set) -> list:
        """(own pad key, target location, weight) for every connection from
        this item's pads to a pad already placed, on a net that pulls."""
        quiet = self._plane_nets() | self._free_nets
        fps = item.members if isinstance(item, CellGeom) else (item,)
        own_refs = {fp.ref for fp in fps}
        out = []
        for fp in fps:
            for p in fp.pads:
                if not p.net or p.net in quiet:
                    continue
                for other in self.geometry.pads_on_net(p.net):
                    if other.owner in own_refs or other.owner not in placed:
                        continue
                    w = self._link_weight((fp.ref, p.number), (other.owner, other.number))
                    if w <= 0:
                        continue
                    out.append(((fp.ref, p.number), occ.pad_location(other.owner, other.number), w))
        return out

    def _scorer(self, item, occ: Occupancy, targets: list):
        def score(placement: Placement) -> float:
            pads = occ.candidate_pad_locations(item, placement)
            return sum(w * pads[key].distance(target) for key, target, w in targets if key in pads)
        return score

    def _report_links(self, occ: Occupancy, plan: Plan, placed: set):
        for l in self._links:
            if l.a[0] in placed and l.b[0] in placed:
                l.achieved_mm = round(occ.pad_location(*l.a).distance(occ.pad_location(*l.b)), 3)
                if not l.within_limit:
                    plan.findings.append("link %s.%s to %s.%s is %.2f mm, over its %.2f mm limit%s" % (
                        l.a[0], l.a[1], l.b[0], l.b[1], l.achieved_mm, l.limit_mm, (": " + l.why) if l.why else ""))
            plan.links.append(l)

    # ------------------------------------------------------------ copper
    def _copper_intent(self, key, net, priority, plan, refs, why, bridge=False):
        name = self.geometry.require_net(net)
        pads = tuple(self._pad_ref(r) for r in refs)
        if priority is Priority.FIXED:
            for owner, *_ in pads:
                if self._is_searched(owner):
                    raise ValueError("%s: FIXED copper may not reference %s, a searched part; "
                                     "fix the part or drop the priority" % (key, owner))
        ci = CopperIntent(key, name, priority, plan, tuple(refs), why, len(self._copper), bridge)
        self._copper.append(ci)
        return ci

    def _width(self, net: str, width) -> float:
        return float(width) if width is not None else self.geometry.netclass(net).track_width

    def track(self, net, points, *, layer: CopperLayer, width: float | None = None,
              priority: Priority = Priority.DEFAULT, bridge: bool = False, why: str = ""):
        """Straight track segments through `points` in order, on one layer.
        A point is a Location, a pad reference, or an (x, y) pair whose
        members may be numbers or X()/Y() of a pad. `bridge=True` lets it
        pass under a same-layer track of another net it crosses (a via, a
        track on the opposite face, a via back) when it is the one that must
        yield: the lower priority, or at equal priority the shorter."""
        layer = CopperLayer.of(layer)
        refs = _refs_in(points)
        name = self.geometry.require_net(net)
        w = self._width(name, width)

        def plan(ctx):
            return polyline_tracks(name, layer, w, [ctx.locate(p) for p in points])
        return self._copper_intent("track %s" % name, net, priority, plan, refs, why, bridge)

    def via(self, net, at, *, drill: float | None = None, size: float | None = None,
            priority: Priority = Priority.DEFAULT, why: str = ""):
        name = self.geometry.require_net(net)
        refs = _refs_in([at])
        d, s = drill or self.via_drill, size or self.via_size

        def plan(ctx):
            return [Via(name, ctx.locate(at), d, s)]
        return self._copper_intent("via %s" % name, net, priority, plan, refs, why)

    def pour(self, net, points, *, layer: CopperLayer, stroke: float = 0.2, swallow_pads: bool = False,
             priority: Priority = Priority.DEFAULT, why: str = ""):
        """A filled copper polygon of exactly this shape on one layer. It does
        not pull back from foreign copper; `swallow_pads` grows it over the
        same-net pads its outline touches."""
        layer = CopperLayer.of(layer)
        name = self.geometry.require_net(net)
        refs = _refs_in(points)

        def plan(ctx):
            pts = tuple((l.x, l.y) for l in (ctx.locate(p) for p in points))
            return [Pour(name, layer, pts, stroke, swallow_pads)]
        return self._copper_intent("pour %s" % name, net, priority, plan, refs, why)

    def plane(self, net, layers, *, outline=None, inset: float = 0.4, chamfer: float | None = None,
              clearance: float = 0.2, min_thickness: float = 0.2, solid_pads: bool = True,
              priority: Priority = Priority.DEFAULT, why: str = ""):
        """A KiCad zone per layer, filled by KiCad and pulled back round every
        foreign pad, track and via: the whole board inset from the edge, or
        the polygon `outline`."""
        name = self.geometry.require_net(net)
        layers = tuple(dict.fromkeys(CopperLayer.of(l) for l in layers))

        def plan(ctx):
            if outline is not None:
                pts = tuple((l.x, l.y) for l in (ctx.locate(p) for p in outline))
            else:
                ch = self._chamfer if chamfer is None else chamfer
                pts = board_zone_outline(self.width, self.height, inset, ch)
            return [Zone(name, l, pts, clearance, min_thickness, solid_pads) for l in layers]
        refs = [] if outline is None else _refs_in(outline)
        return self._copper_intent("plane %s" % name, net, priority, plan, refs, why)

    def finger(self, net, *, layer: CopperLayer, from_, to, width: float,
               bridge_width: float = 1.0, priority: Priority = Priority.DEFAULT, why: str = ""):
        """A finger: a rectangular pour of `width` along the centreline from
        `from_` to `to` (points, pads, or (x, y) pairs with X()/Y()), cut
        either side of every same-layer track of another net it crosses and
        bridged under each on the opposite face so the pieces stay one net.
        Fingers always yield to tracks."""
        layer = CopperLayer.of(layer)
        name = self.geometry.require_net(net)
        refs = _refs_in([from_, to])

        def plan(ctx):
            a, b = ctx.locate(from_), ctx.locate(to)
            segs = [((t.start.x, t.start.y), (t.end.x, t.end.y)) for t in ctx.tracks_on(layer) if t.net != name]
            return finger_ops(name, layer, a, b, width, segs, self.via_drill, self.via_size, bridge_width)
        return self._copper_intent("finger %s" % name, net, priority, plan, refs, why)

    # ------------------------------------------------------------ resolution
    def resolve(self, progress=None) -> Plan:
        occ = Occupancy(self.geometry, self.edge_margin, board_box=self._outline)
        plan = Plan(self.geometry, occ, outline=self._outline, chamfer=self._chamfer, radius=self._radius)
        ctx = _CopperContext(self, occ)
        placements = sorted(self._intents, key=lambda i: i.rank)
        fixed_copper = [c for c in self._copper if c.priority is Priority.FIXED]
        other_copper = [c for c in self._copper if c.priority is not Priority.FIXED]
        placed: set = set()

        def place_ranked(lo, hi):
            for obj in placements:
                if lo <= obj.rank[0] <= hi:
                    plan._items[obj.key] = obj.item
                    step = self._settle(occ, obj, plan, placed)
                    plan.steps.append(step)
                    occ.commit(obj.item, step.placement)
                    placed.update(fp.ref for fp in (obj.item.members if obj.kind == "cell" else (obj.item,)))
                    if progress:
                        progress(_fmt(step))

        place_ranked(RANK_FIXED, RANK_CELL)
        self._plan_copper(occ, ctx, fixed_copper, plan, progress)
        place_ranked(RANK_LOOSE, RANK_LOOSE)
        self._plan_copper(occ, ctx, other_copper, plan, progress)
        self._report_links(occ, plan, placed)
        return plan

    def _plan_copper(self, occ, ctx, intents, plan: Plan, progress):
        """Plan a batch of copper together. Tracks are collected first and
        their crossings settled by priority; pours, zones, vias and fingers
        follow (a finger yields to every track already planned)."""
        tracks, others = [], []
        deferred = []
        for c in sorted(intents, key=lambda c: c.index):
            if c.key.startswith("finger"):
                deferred.append(c)          # a finger is cut by the tracks planned in this batch
                continue
            for op in c.plan(ctx):
                (tracks if isinstance(op, Track) else others).append((c, op))
        entries = [(op, c.priority.rank, c.bridge) for c, op in tracks]
        ops, notes, findings = resolve_bridges(entries, ctx.fixed_tracks, self.via_drill, self.via_size)
        plan.findings += findings
        ctx.planned_tracks += [op for op in ops if isinstance(op, Track)]
        for c in deferred:
            for op in c.plan(ctx):
                others.append((c, op))
        by_key = {}
        for c, _ in tracks:
            by_key.setdefault(c.key, [c.priority, 0, c.why])
        for c, _ in others:
            by_key.setdefault(c.key, [c.priority, 0, c.why])
        n_by_net = {}
        for op in ops:
            n_by_net[op.net] = n_by_net.get(op.net, 0) + 1
        for c, _ in tracks:
            by_key[c.key][1] = n_by_net.get(c.net, 0)
        all_ops = list(ops)
        for c, op in others:
            by_key.setdefault(c.key, [c.priority, 0, c.why])
            all_ops.append(op)
            by_key[c.key][1] += 1
        shapes = []
        for op in all_ops:
            plan.copper.append(op)
            shape = _shape_of(op)
            if shape is None:
                continue
            for hit in occ.copper_conflicts(shape):
                plan.findings.append("copper %s: %s" % (op.net, hit))
            shapes.append(shape)
        occ.add_copper(shapes)
        if any(c.priority is Priority.FIXED for c in intents):
            ctx.fixed_tracks += [op for op in ops]
        for key, (prio, n, why) in by_key.items():
            step = Step(key, "copper", prio, None, 0.0, "%d op(s)" % n, why, n)
            plan.steps.append(step)
            if progress:
                progress(_fmt(step))
        for note in notes:
            plan.steps.append(Step("bridge", "copper", Priority.DEFAULT, None, 0.0, note, "", 0))
            if progress:
                progress("   bridge: " + note)

    def _settle(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set = frozenset()) -> Step:
        clr = self.clearance
        if i.priority in (Priority.FIXED, Priority.EDGE):
            if i.at is not None:
                p = Placement(i.at, i.rotation, i.face)
            elif i.center is not None:
                p = box_centered_placement(occ, i.item, i.center, i.rotation, i.face)
            else:
                p = edge_placement(occ, i.item, i.edge, i.along, i.rotation, i.clearance, i.face)
            why = occ.legal(i.item, p, clr)
            if why:
                plan.findings.append("%s (%s): %s" % (i.key, i.priority.value, why))
            return Step(i.key, i.kind, i.priority, p, 0.0, why or "", i.why)
        current = occ._geometry(i.item).reference
        targets = self._targets(i.item, occ, placed)
        seeded = ""
        if i.near is not None:
            hint = Placement(i.near, i.rotation, i.face)
        elif targets:
            wsum = sum(w for _, _, w in targets)
            cx = sum(t.x * w for _, t, w in targets) / wsum
            cy = sum(t.y * w for _, t, w in targets) / wsum
            # the hint is where the part's ORIGIN should go for its pads to sit on the centroid
            pads_now = occ.candidate_pad_locations(i.item, Placement(current.location, i.rotation, i.face))
            own = [pads_now[k] for k, _, _ in targets if k in pads_now]
            ox = sum(p.x for p in own) / len(own) - current.location.x if own else 0.0
            oy = sum(p.y for p in own) / len(own) - current.location.y if own else 0.0
            hint = Placement(Location(round(cx - ox, 3), round(cy - oy, 3)), i.rotation, i.face)
            nets = sorted({self.geometry.footprint(k[0]).pad(int(k[1]) if k[1].isdigit() else k[1]).net
                           for k, _, _ in targets if k[0] in {fp.ref for fp in (i.item.members if i.kind == "cell" else (i.item,))}})
            seeded = "seeded on %s" % ", ".join(nets)
        else:
            hint = Placement(current.location, i.rotation, i.face)
        score = self._scorer(i.item, occ, targets) if targets else None
        result = scan(occ, i.item, hint, i.radius, i.step, i.rotations or (i.rotation,), clr, score=score)
        if result.chosen is None:
            plan.findings.append("%s: no legal location within %.1f mm of %s (%s)" % (
                i.key, i.radius, _loc(hint.location), ", ".join("%s x%d" % kv for kv in result.rejected.most_common(3))))
            return Step(i.key, i.kind, i.priority, hint, 0.0, "UNPLACED: " + "; ".join(result.reasons.values()), i.why)
        note = seeded
        if result.moved_mm > 0:
            first = next(iter(result.reasons.values()), "")
            moved = "moved %.2f mm off the hint" % result.moved_mm
            if first:
                moved += ": " + first
            elif score:
                moved += " for a better link score"
            note = (note + "; " if note else "") + moved
        return Step(i.key, i.kind, i.priority, result.chosen, result.moved_mm, note, i.why)

class _CopperContext:
    def __init__(self, board: Board, occ: Occupancy):
        self.board, self.occ = board, occ
        self.planned_tracks: list = []     # every track planned so far (any batch)
        self.fixed_tracks: list = []       # tracks from the FIXED batch: never yield

    def locate(self, ref) -> Location:
        if isinstance(ref, Location):
            return ref
        if isinstance(ref, tuple) and len(ref) == 2:
            return Location(self.coord(ref[0], "x"), self.coord(ref[1], "y"))
        owner, number, dx, dy = self.board._pad_ref(ref)
        return self.occ.pad_location(owner, number).offset(dx, dy)

    def coord(self, v, axis: str) -> float:
        """One coordinate: a number, X()/Y() of a pad reference, or a pad
        reference/point whose `axis` coordinate is meant."""
        if isinstance(v, X):
            return self.locate(v.ref).x + v.dx
        if isinstance(v, Y):
            return self.locate(v.ref).y + v.dy
        if isinstance(v, (PadRef, CellPadRef, Location, tuple)):
            l = self.locate(v)
            return l.x if axis == "x" else l.y
        return float(v)

    def tracks_on(self, layer) -> list:
        return [t for t in self.planned_tracks if t.layer is layer]


def _refs_in(points) -> list:
    """Every pad reference a list of points depends on (inside tuples and X/Y too)."""
    out = []
    for p in points:
        if isinstance(p, (PadRef, CellPadRef)):
            out.append(p)
        elif isinstance(p, (X, Y)):
            out += _refs_in([p.ref])        # the ref may itself be a point or a pad
        elif isinstance(p, tuple):
            out += _refs_in(p)
    return out


def _shape_of(op) -> Shape | None:
    both = frozenset([Face.FRONT, Face.BACK])
    if isinstance(op, Track):
        faces = frozenset([op.layer.face]) if op.layer.face else frozenset()
        return Shape("", "copper", faces, frozenset([op.layer]), op.net, op.polygon, op.box)
    if isinstance(op, Via):
        return Shape("", "through", both, frozenset(CopperLayer), op.net, op.polygon, op.box)
    if isinstance(op, Pour):
        faces = frozenset([op.layer.face]) if op.layer.face else frozenset()
        return Shape("", "copper", faces, frozenset([op.layer]), op.net, op.polygon, op.box)
    return None            # a zone pulls back round everything; it is never an obstacle


def _loc(l: Location) -> str:
    return "(%.2f, %.2f)" % (l.x, l.y)


def _fmt(s: Step) -> str:
    if s.placement is None:
        return "%-7s %-6s %-28s %s" % (s.priority.value, s.kind, s.item, s.note)
    out = "%-7s %-6s %-28s %s rot %g %s" % (s.priority.value, s.kind, s.item, _loc(s.placement.location),
                                             s.placement.rotation, s.placement.face.value)
    if s.note:
        out += "  " + s.note
    return out
