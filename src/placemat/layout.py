"""The Board object a layout script declares to, and the Plan resolve()
produces from it.

Board answers questions about the generated board, records placement and
copper declarations, and resolves them in priority order (setup, FIXED,
EDGE, searched cells, FIXED copper, loose parts, remaining copper) against
the occupancy model. Plan holds the resolved placements, copper ops and
findings for the writer and the run record."""
from __future__ import annotations

from dataclasses import dataclass, field

from .copper import (CopperOp, Lane, LanePlanner, Pour, Track, Via, Zone, board_zone_outline,
                     finger_ops, polyline_tracks)
from .geometry import polygon_box
from .occupancy import Occupancy, Shape
from .placement import Placement
from .placer import box_centered_placement, edge_placement, scan
from .snapshot import CellGeom, Footprint, Snapshot
from .values import (Box, Cell, CellPadRef, CopperLayer, Edge, Face, Location, Net, PadRef, Part,
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

    @property
    def rank(self):
        return (RANK_FIXED_COPPER if self.priority is Priority.FIXED else RANK_COPPER, self.index)


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
    snapshot: Snapshot
    occupancy: Occupancy
    steps: list[Step] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    copper: list = field(default_factory=list)
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


class Board:
    """One board being laid out: queries answer from the snapshot the board
    was generated with; declarations are collected and resolved together."""

    def __init__(self, snapshot: Snapshot, edge_margin: float = 0.0, clearance: float | None = None,
                 via_drill: float = 0.3, via_size: float = 0.6):
        self.snapshot = snapshot
        self.edge_margin = edge_margin
        self.clearance = clearance
        self.via_drill, self.via_size = via_drill, via_size
        self._intents: list[PlaceIntent] = []
        self._copper: list[CopperIntent] = []
        self._lanes: list[Lane] = []
        self._outline: Box | None = snapshot.outline_box
        self._chamfer = 0.0
        self._radius = 0.0
        self.width = self._outline.width if self._outline else None
        self.height = self._outline.height if self._outline else None

    # ------------------------------------------------------------ questions
    def part(self, key) -> Footprint:
        return self.snapshot.footprint(key)

    def cell(self, key) -> CellGeom:
        return self.snapshot.cell(key)

    def pad(self, part, key):
        return self.snapshot.pad(part, key)

    def cell_pad(self, cell, **kw):
        return self.snapshot.cell_pad(cell, **kw)

    def net(self, net) -> str:
        return self.snapshot.require_net(net)

    def _item(self, item):
        if isinstance(item, Cell):
            return self.snapshot.cell(item), item.name, "cell"
        if isinstance(item, Part):
            fp = self.snapshot.footprint(item)
            return fp, fp.inst, "part"
        if isinstance(item, CellGeom):
            return item, item.name, "cell"
        if isinstance(item, Footprint):
            return item, item.inst, "part"
        raise TypeError("place() takes a Part or a Cell, not %r" % (item,))

    def extent(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """The item's body box at `rotation`, placed at the origin: a size, not a place."""
        geom, _, _ = self._item(item)
        occ = Occupancy(self.snapshot, self.edge_margin, board_box=None)
        return occ.body_box(geom, Placement(Location(0.0, 0.0), rotation, face))

    def _pad_ref(self, ref):
        """Validate a pad reference now; return (refdes, pad number, dx, dy)."""
        if isinstance(ref, PadRef):
            p = self.snapshot.pad(ref.part, ref.key)
            return (p.owner, p.number, ref.dx, ref.dy)
        if isinstance(ref, CellPadRef):
            p = self.snapshot.cell_pad(ref.cell, net=ref.net, number=ref.number, ref_prefix=ref.ref_prefix)
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
        fp = self.snapshot.footprint(refdes)
        for i in self._intents:
            if i.priority is Priority.DEFAULT and (i.key == fp.inst or (i.kind == "cell" and fp.cell == i.key)):
                return True
        return False

    # ------------------------------------------------------------ copper
    def _copper_intent(self, key, net, priority, plan, refs, why):
        name = self.snapshot.require_net(net)
        pads = tuple(self._pad_ref(r) for r in refs)
        if priority is Priority.FIXED:
            for owner, *_ in pads:
                if self._is_searched(owner):
                    raise ValueError("%s: FIXED copper may not reference %s, a searched part; "
                                     "fix the part or drop the priority" % (key, owner))
        ci = CopperIntent(key, name, priority, plan, tuple(refs), why, len(self._copper))
        self._copper.append(ci)
        return ci

    def _width(self, net: str, width) -> float:
        return float(width) if width is not None else self.snapshot.netclass(net).track_width

    def track(self, net, points, *, layer: CopperLayer, width: float | None = None,
              priority: Priority = Priority.DEFAULT, why: str = ""):
        """A polyline of tracks through `points`: Locations, pad references,
        or (x, y) pairs whose members may be numbers or X()/Y() of a pad."""
        layer = CopperLayer.of(layer)
        refs = _refs_in(points)
        name = self.snapshot.require_net(net)
        w = self._width(name, width)

        def plan(ctx):
            return polyline_tracks(name, layer, w, [ctx.locate(p) for p in points])
        return self._copper_intent("track %s" % name, net, priority, plan, refs, why)

    def via(self, net, at, *, drill: float | None = None, size: float | None = None,
            priority: Priority = Priority.DEFAULT, why: str = ""):
        name = self.snapshot.require_net(net)
        refs = _refs_in([at])
        d, s = drill or self.via_drill, size or self.via_size

        def plan(ctx):
            return [Via(name, ctx.locate(at), d, s)]
        return self._copper_intent("via %s" % name, net, priority, plan, refs, why)

    def pour(self, net, points, *, layer: CopperLayer, stroke: float = 0.2, swallow_pads: bool = False,
             priority: Priority = Priority.DEFAULT, why: str = ""):
        """A filled polygon on one layer, as drawn (optionally grown over the
        same-net pads its outline touches)."""
        layer = CopperLayer.of(layer)
        name = self.snapshot.require_net(net)
        refs = _refs_in(points)

        def plan(ctx):
            pts = tuple((l.x, l.y) for l in (ctx.locate(p) for p in points))
            return [Pour(name, layer, pts, stroke, swallow_pads)]
        return self._copper_intent("pour %s" % name, net, priority, plan, refs, why)

    def plane(self, net, layers, *, outline=None, inset: float = 0.4, chamfer: float | None = None,
              clearance: float = 0.2, min_thickness: float = 0.2, solid_pads: bool = True,
              priority: Priority = Priority.DEFAULT, why: str = ""):
        """A filled zone per layer: the whole board (inset) or `outline`."""
        name = self.snapshot.require_net(net)
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

    def lane(self, net, *, x: float, layer: CopperLayer, width: float | None = None,
             priority: Priority = Priority.DEFAULT) -> Lane:
        """Register a bus lane. Its taps, runs, hops and crossings are
        declared on the returned Lane; all lanes are planned together so a
        tap knows which same-layer lanes it must bridge."""
        name = self.snapshot.require_net(net)
        lane = Lane(name, float(x), CopperLayer.of(layer), self._width(name, width), self, priority=priority)
        self._lanes.append(lane)
        return lane

    def finger(self, net, *, layer: CopperLayer, y_lo: float, y_hi: float, x_from: float, x_to: float,
               bridge_width: float = 1.0, priority: Priority = Priority.DEFAULT, why: str = ""):
        """A pour finger between y_lo..y_hi from x_from to x_to, notched round
        every registered same-layer lane it would swallow and bridged on the
        far layer so it stays one net."""
        layer = CopperLayer.of(layer)
        name = self.snapshot.require_net(net)
        refs = _refs_in([(x_from, y_lo), (x_to, y_hi)])

        def plan(ctx):
            ylo, yhi = ctx.coord(y_lo, "y"), ctx.coord(y_hi, "y")
            lo, hi = min(ylo, yhi), max(ylo, yhi)
            xa, xb = ctx.coord(x_from, "x"), ctx.coord(x_to, "x")
            xs = sorted({l.x for l in self._lanes if l.layer is layer and l.net != name
                         and ctx.lane_extent(l) is not None
                         and ctx.lane_extent(l)[0] <= hi and lo <= ctx.lane_extent(l)[1]})
            return finger_ops(name, layer, lo, hi, xa, xb, xs, self.via_drill, self.via_size, bridge_width)
        return self._copper_intent("finger %s" % name, net, priority, plan, refs, why)

    # ------------------------------------------------------------ resolution
    def resolve(self, progress=None) -> Plan:
        occ = Occupancy(self.snapshot, self.edge_margin, board_box=self._outline)
        plan = Plan(self.snapshot, occ, outline=self._outline, chamfer=self._chamfer, radius=self._radius)
        ctx = _CopperContext(self, occ)
        work = [(i.rank, "place", i) for i in self._intents] + [(c.rank, "copper", c) for c in self._copper]
        lanes_fixed = [l for l in self._lanes if l.priority is Priority.FIXED]
        lanes_default = [l for l in self._lanes if l.priority is not Priority.FIXED]
        if lanes_fixed:
            work.append(((RANK_FIXED_COPPER, len(self._copper)), "lanes", lanes_fixed))
        if lanes_default:
            work.append(((RANK_COPPER, len(self._copper) + 1), "lanes", lanes_default))
        for rank, what, obj in sorted(work, key=lambda w: w[0]):
            if what == "place":
                plan._items[obj.key] = obj.item
                step = self._settle(occ, obj, plan)
                plan.steps.append(step)
                occ.commit(obj.item, step.placement)
            elif what == "copper":
                step = self._draw(occ, ctx, obj, plan)
                plan.steps.append(step)
            else:
                step = self._draw_lanes(occ, ctx, obj, plan)
                plan.steps.append(step)
            if progress:
                progress(_fmt(step))
        return plan

    def _settle(self, occ: Occupancy, i: PlaceIntent, plan: Plan) -> Step:
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
        hint = Placement(i.near, i.rotation, i.face) if i.near is not None else \
            Placement(current.location, i.rotation, i.face)
        result = scan(occ, i.item, hint, i.radius, i.step, i.rotations or (i.rotation,), clr)
        if result.chosen is None:
            plan.findings.append("%s: no legal location within %.1f mm of %s (%s)" % (
                i.key, i.radius, _loc(hint.location), ", ".join("%s x%d" % kv for kv in result.rejected.most_common(3))))
            return Step(i.key, i.kind, i.priority, hint, 0.0, "UNPLACED: " + "; ".join(result.reasons.values()), i.why)
        note = ""
        if result.moved_mm > 0:
            first = next(iter(result.reasons.values()), "")
            note = "moved %.2f mm off the hint: %s" % (result.moved_mm, first)
        return Step(i.key, i.kind, i.priority, result.chosen, result.moved_mm, note, i.why)

    def _draw(self, occ, ctx, c: CopperIntent, plan: Plan) -> Step:
        ops = c.plan(ctx)
        return self._record_ops(occ, plan, c.key, c.priority, ops, c.why)

    def _draw_lanes(self, occ, ctx, lanes, plan: Plan) -> Step:
        planner = LanePlanner(lanes, ctx, self.via_drill, self.via_size)
        ops = planner.plan()
        ctx.lane_extents.update(planner.extents)
        prio = lanes[0].priority if lanes else Priority.DEFAULT
        key = "lanes " + ", ".join(dict.fromkeys(l.net for l in lanes))
        return self._record_ops(occ, plan, key, prio or Priority.DEFAULT, ops, "")

    def _record_ops(self, occ, plan, key, priority, ops, why) -> Step:
        shapes = []
        for op in ops:
            plan.copper.append(op)
            shape = _shape_of(op)
            if shape is None:
                continue
            for hit in occ.copper_conflicts(shape):
                plan.findings.append("%s: %s" % (key, hit))
            shapes.append(shape)
        occ.add_copper(shapes)
        return Step(key, "copper", priority, None, 0.0, "%d op(s)" % len(ops), why, len(ops))


class _CopperContext:
    def __init__(self, board: Board, occ: Occupancy):
        self.board, self.occ = board, occ
        self.lane_extents: dict = {}

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

    def lane_extent(self, lane):
        if not self.lane_extents:
            planner = LanePlanner(self.board._lanes, self, self.board.via_drill, self.board.via_size)
            self.lane_extents = dict(planner.compute_extents())
            self.lane_extents.setdefault("_computed", True)
        return self.lane_extents.get(id(lane))


def _refs_in(points) -> list:
    """Every pad reference a list of points depends on (inside tuples and X/Y too)."""
    out = []
    for p in points:
        if isinstance(p, (PadRef, CellPadRef)):
            out.append(p)
        elif isinstance(p, (X, Y)):
            out.append(p.ref)
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
