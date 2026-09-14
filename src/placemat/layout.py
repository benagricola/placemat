"""The Board object a layout script declares to, and the Plan resolve()
produces from it.

Board answers questions about the generated board, records placement and
copper declarations, and resolves them in priority order (setup, FIXED,
EDGE, searched cells, FIXED copper, loose parts, remaining copper) against
the occupancy model. Plan holds the resolved placements, copper ops and
findings for the writer and the run record."""
from __future__ import annotations

from dataclasses import dataclass, field

from .copper import (CopperOp, Pour, Text, Track, Via, Zone, board_zone_outline, chamfered, finger_ops, octilinear, pair_ops, polyline_tracks,
                     resolve_bridges)
from .geometry import polygon_box
from .occupancy import Occupancy, Shape
from .placement import Placement
from .placer import BlockSpec, box_centered_placement, edge_placement, layout_block, pockets, scan, scan_block
from .board_geometry import CellGeom, Footprint, BoardGeometry
from .values import (Box, Cell, CellPadRef, CopperLayer, Edge, Face, LinkWeight, Location, Mid, Net, PadRef, Part,
                     Priority, X, Y)

RANK_FIXED, RANK_EDGE, RANK_CELL, RANK_FIXED_COPPER, RANK_BLOCK, RANK_LOOSE, RANK_COPPER = range(7)


# A cell generated with its connector's body bulk on local +Y ("outward")
# faces out of each edge at this rotation.
_OUTWARD_ROTATION = {Edge.SOUTH: 0.0, Edge.EAST: 90.0, Edge.NORTH: 180.0, Edge.WEST: 270.0}


@dataclass(frozen=True)
class RowCoord:
    """A coordinate of a row that needs the board outline: resolved when
    copper is planned, usable wherever a number is."""
    row: "Row"
    what: str        # inner | outer

    def __add__(self, dx):
        return RowCoord(self.row, "%s%+g" % (self.what, dx))


class Row:
    """Items down one edge, in order, `gap` apart, each flush to the edge with
    its outward side out. Along-edge numbers (start, end, length, centre of
    each item) are known at declaration when the row starts at a number, and
    when its items are placed if it starts at a reference; the inboard
    boundary (`inner`) and the edge line (`outer`) are references resolved
    against the outline."""

    def __init__(self, edge: Edge, standoff: float, gap: float, start: float | None, keys, alongs, depth: float):
        self.edge, self.standoff, self.gap = edge, standoff, gap     # standoff: the outer line, in from the edge
        self.keys, self.alongs, self.depth = list(keys), list(alongs), depth
        self.items: list = []
        self.length = sum(alongs) + gap * (len(alongs) - 1)
        self.start = self.end = None
        self.centres = []
        self.anchor = None            # ("centre"|"end"|"before"|"after"|"outline", value): how a deferred row finds its start
        self.line = "centre"          # how the items align across the row
        self.needs: frozenset = frozenset()   # refdes the anchor refers to
        if start is not None:
            self.begin(start)

    def begin_from(self, board, occ):
        """Fix the row's start from its anchor, now that what it refers to is placed."""
        if self.start is not None:
            return
        kind, value = self.anchor
        axis = "x" if self.edge in (Edge.NORTH, Edge.SOUTH) else "y"
        if kind == "outline":
            self.begin(self.centre_of(occ.board_box))
        elif kind == "centre":
            self.begin(_coord(board, occ, value, axis) - self.length / 2.0)
        elif kind == "end":
            self.begin(_coord(board, occ, value, axis) - self.length)
        elif kind == "start":
            self.begin(_coord(board, occ, value, axis))
        elif kind == "before":
            value.begin_from(board, occ)
            self.begin(value.start - self.gap - self.length)
        else:
            value.begin_from(board, occ)
            self.begin(value.end + self.gap)

    def begin(self, start: float):
        """Fix where the row starts along its edge (a centred row learns this
        from the outline at resolve)."""
        self.start, self.end = start, start + self.length
        self.centres = []
        cursor = start
        for a in self.alongs:
            self.centres.append(cursor + a / 2.0)
            cursor += a + self.gap

    def centre_of(self, outline: Box) -> float:
        total = outline.height if self.edge in (Edge.EAST, Edge.WEST) else outline.width
        return (total - self.length) / 2.0

    def centre(self, item) -> float:
        """The along-edge centre of one item (the item, or its key)."""
        if self.start is None:
            raise ValueError("this row starts at a reference: its numbers exist once it is placed; "
                             "refer to its items' pads instead")
        i = self.items.index(item) if item in self.items else self.keys.index(item)
        return self.centres[i]

    @property
    def inner(self) -> RowCoord:
        return RowCoord(self, "inner")

    @property
    def outer(self) -> RowCoord:
        return RowCoord(self, "outer")

    def resolve(self, what: str, board_box: Box) -> float:
        base, dx = (what.split("+")[0] if "+" in what else what.split("-")[0]), 0.0
        if len(what) > len(base):
            dx = float(what[len(base):])
        depth = self.standoff + (self.depth if base == "inner" else 0.0)
        if self.edge is Edge.WEST:
            return board_box.left + depth + dx
        if self.edge is Edge.EAST:
            return board_box.right - depth + dx
        if self.edge is Edge.NORTH:
            return board_box.top + depth + dx
        return board_box.bottom - depth + dx


@dataclass(frozen=True)
class _RowSlot:
    """One item's along-edge position in a row whose start is a reference."""
    row: Row
    index: int

    def resolve(self, board, occ) -> float:
        self.row.begin_from(board, occ)
        return self.row.centres[self.index]


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
    needs: frozenset = frozenset()     # refdes this position refers to: placed first

    @property
    def rank(self):
        if self.priority is Priority.FIXED:
            return (RANK_FIXED, self.index)
        if self.priority is Priority.EDGE:
            return (RANK_EDGE, self.index)
        return ({"cell": RANK_CELL, "block": RANK_BLOCK}.get(self.kind, RANK_LOOSE), self.index)


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
    rules: list = field(default_factory=list)
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
        """The item's body box where it was placed (the occupancy's committed
        geometry, so a turned cell reads turned)."""
        item = self._items[key]
        if isinstance(item, (BlockSpec, CellGeom)):
            return Box.union([self.occupancy.items[m.ref].body for m in item.members])
        return self.occupancy.items[item.ref].body

    @property
    def placements(self) -> dict[str, Placement]:
        return {s.item: s.placement for s in self.steps if s.placement is not None}

    @property
    def plane_nets(self) -> set:
        """Nets served by a pour, plane or finger: routing leaves them alone."""
        return {op.net for op in self.copper if isinstance(op, (Pour, Zone))}


class PlacementCollision(Exception):
    """Two things the script declared firm (FIXED or EDGE) land on each
    other: a script error, reported before anything is searched."""
    def __init__(self, collisions):
        self.collisions = list(collisions)
        super().__init__("%d firm placement(s) collide:\n  " % len(self.collisions) + "\n  ".join(self.collisions))


class CriticalUnplaced(Exception):
    """A HIGH priority searched item found no place. The resolve stops here
    with the plan as it stood, so what is free at this moment is what gets
    looked at, not a board where the furniture has since taken the space."""
    def __init__(self, key: str, message: str, plan):
        self.key, self.plan = key, plan
        super().__init__(message)


class Board:
    """One board being laid out. Questions are answered from the geometry read
    off the generated .kicad_pcb; declarations are collected and resolved
    together."""

    def __init__(self, geometry: BoardGeometry, edge_margin: float | None = None, clearance: float | None = None,
                 via_drill: float = 0.3, via_size: float = 0.6, keep_going: bool = False):
        self.geometry = geometry
        self.edge_margin = geometry.edge_clearance if edge_margin is None else edge_margin
        self.clearance = clearance
        self.via_drill, self.via_size = via_drill, via_size
        self.keep_going = keep_going            # carry on past colliding FIXED/EDGE items, as findings
        self._intents: list[PlaceIntent] = []
        self._copper: list[CopperIntent] = []
        self._labels: list = []
        self._links: list[Link] = []
        self._rules: list = []
        self._free_nets: set = set()
        self._outline: Box | None = geometry.outline_box
        self._sized = False                 # the script has declared the board size
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

    def netclass(self, net):
        """The net's class: `.track_width`, `.clearance`, `.diff_pair_width`, `.diff_pair_gap`."""
        return self.geometry.netclass(net)

    def pitch(self, part) -> float:
        """The spacing of a part's pads: the distance between neighbouring
        pad centres, read from the footprint (a connector's pin pitch, a
        two-pad part's pad spacing)."""
        fp = self.geometry.footprint(part)
        centres = [p.box.center for p in fp.pads]
        if len(centres) < 2:
            raise ValueError("%s has %d pad(s): no pitch" % (fp.ref, len(centres)))
        nearest = [min(a.distance(b) for b in centres if b is not a) for a in centres]
        return round(min(nearest), 6)

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
        if isinstance(item, BlockSpec):
            return item, item.key, "block"
        raise TypeError("place() takes a Part, a Cell or a block, not %r" % (item,))

    @property
    def keep_in(self) -> float:
        """How close anything may come to the board edge: the board's own
        copper-to-edge rule. Edge placement puts an item's reach here."""
        return self.edge_margin

    def extent(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """The item's body box at `rotation`, placed at the origin: a size, not a place."""
        geom, _, _ = self._item(item)
        occ = Occupancy(self.geometry, self.edge_margin, board_box=None)
        return occ.body_box(geom, Placement(Location(0.0, 0.0), rotation, face))

    def reach(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """Everything the item physically is (body, pads, silk) at
        `rotation`, at the origin: what edge placement and rows measure."""
        geom, _, _ = self._item(item)
        occ = Occupancy(self.geometry, self.edge_margin, board_box=None)
        return occ.reach_box(geom, Placement(Location(0.0, 0.0), rotation, face))

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
        self._sized = True

    # ------------------------------------------------------------ blocks
    def block(self, anchor, satellites, gap: float = 0.5) -> BlockSpec:
        """A part and the satellites that sit at its pins: `satellites` is a
        list of (Part, net) pairs, each placed on that pin's axis `gap` out,
        body outward of its pad. Place the returned block like a part; it is
        laid out from the anchor's real pads at every candidate."""
        a = self.geometry.footprint(anchor)
        sats = []
        for part, net in satellites:
            fp = self.geometry.footprint(part)
            name = self.geometry.require_net(net)
            a.pad(name)              # the anchor must carry the net
            fp.pad(name)             # and so must the satellite
            sats.append((fp, name))
        return BlockSpec(a, tuple(sats), gap)

    # ------------------------------------------------------------ placement
    def place(self, item, *, at: Location | None = None, center: Location | None = None,
              rotation: float = 0.0, face: Face = Face.FRONT, edge: Edge | None = None,
              along: float | None = None, overhang: float = 0.0,
              near: Location | None = None, radius: float = 3.0, step: float = 0.2,
              rotations=(), priority: Priority | None = None, why: str = "", _standoff: float | None = None) -> PlaceIntent:
        """Declare where an item goes.

        at=       a part's origin (a cell's box centre)      -> FIXED
        center=   the body box centre                        -> FIXED
        edge=, along=   its reach at the board's keep-in     -> EDGE
                  (`overhang=` past the edge, for a face that must stand proud)
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
        needs = {self._pad_ref(ref)[0] for ref in _refs_in([at, center, along])}   # a real pad, placed before this
        if isinstance(along, _RowSlot):
            needs |= along.row.needs
        if overhang and edge is None:
            raise ValueError("%s: overhang= goes with edge=" % key)
        standoff = _standoff if _standoff is not None else (-float(overhang) if overhang else self.keep_in)
        intent = PlaceIntent(key, geom, kind, priority, float(rotation), face, at, center, edge, along,
                             standoff, near, radius, step, tuple(rotations), why, len(self._intents), frozenset(needs))
        self._intents.append(intent)
        return intent

    def row(self, items, edge: Edge, *, gap: float, start=None, align: str = "start",
            rotation: float | None = None, line: str = "centre", behind: Row | None = None, inboard: float | None = None,
            overhang: float = 0.0,
            centre=None, end=None, before: Row | None = None, after: Row | None = None, why: str = "") -> Row:
        """Items down `edge` in order, `gap` apart, with their outward sides
        out (`rotation=`, one value or one per item, overrides that turn for
        parts with no outward side). The row's outer line is the board's
        keep-in, or `inboard` (default `gap`) behind the inner line of the
        row it is `behind=`; `overhang=` puts a face that far past the edge. Across the row the items align
        on one line: `line="centre"` (the default) puts their centres on
        the line the deepest item's centre falls on; `"outer"` puts every
        outward reach on the outer line (connectors edge-hard); `"inner"`
        aligns the inboard edges. A row butted `before=` or `after=`
        another takes that row's line. Where the row sits along the edge:
        `start=` a number (default: the keep-in) or a reference;
        `align="center"` on the board; `centre=` or `end=` a reference (a
        pad's X()/Y(), a Mid); `before=` or `after=` another row, one gap
        away. A row placed by a reference is measured when its items are
        placed. Returns the Row."""
        rots = [_OUTWARD_ROTATION[edge]] * len(items) if rotation is None else \
            ([float(r) for r in rotation] if isinstance(rotation, (list, tuple)) else [float(rotation)] * len(items))
        rot = rots[0] if rots else _OUTWARD_ROTATION[edge]
        if behind is not None:
            if behind.edge is not edge:
                raise ValueError("a row is behind a row on its own edge")
            if overhang:
                raise ValueError("a row behind another has no edge to overhang")
            clr = behind.standoff + behind.depth + (gap if inboard is None else float(inboard))
        else:
            clr = -float(overhang) if overhang else self.keep_in
        along_axis = edge in (Edge.EAST, Edge.WEST)
        keys, alongs, depths = [], [], []
        for item, r in zip(items, rots):
            geom, key, kind = self._item(item)
            box = self.reach(item, r)
            keys.append(key)
            alongs.append(box.height if along_axis else box.width)
            depths.append(box.width if along_axis else box.height)
        by_ref = start is not None and not isinstance(start, (int, float))
        anchors = [("centre", centre), ("end", end), ("before", before), ("after", after), ("start", start if by_ref else None)]
        given = [(k, v) for k, v in anchors if v is not None]
        if len(given) > 1 or (given and ((start is not None and not by_ref) or align == "center")):
            raise ValueError("a row is placed one way: start=, align=\"center\", centre=, end=, before= or after=")
        row = Row(edge, clr, gap, None, keys, alongs, max(depths))
        if given:
            row.anchor = given[0]
            kind, value = given[0]
            if kind in ("before", "after"):
                row.needs = frozenset(value.needs) | frozenset(
                    fp.ref for it in value.items for fp in (self._item(it)[0].members if self._item(it)[2] == "cell" else (self._item(it)[0],)))
            else:
                row.needs = frozenset(self._pad_ref(ref)[0] for ref in _refs_in([value]))
        elif align == "center":
            if self._sized:                     # the script's own size, not the generator's frame
                row.begin(row.centre_of(self._outline))
            else:
                row.anchor = ("outline", None)
        else:
            row.begin(float(self.keep_in if start is None else start))
        row.items = list(items)
        if line not in ("centre", "outer", "inner"):
            raise ValueError("a row's line is centre, outer or inner, not %r" % (line,))
        base = row.anchor[1] if row.anchor and row.anchor[0] in ("before", "after") else row
        ref = base.standoff + {"centre": base.depth / 2.0, "outer": 0.0, "inner": base.depth}[line]   # the line, from the edge
        clears = [ref - {"centre": d / 2.0, "outer": 0.0, "inner": d}[line] for d in depths]
        row.line = line
        for n, (item, r, c) in enumerate(zip(items, rots, clears)):
            along = row.centres[n] if row.start is not None else _RowSlot(row, n)
            self.place(item, edge=edge, along=along, _standoff=c, rotation=r, why=why)
        return row

    def _is_searched(self, refdes: str) -> bool:
        fp = self.geometry.footprint(refdes)
        for i in self._intents:
            if i.priority not in (Priority.FIXED, Priority.EDGE) and (i.key == fp.inst or (i.kind == "cell" and fp.cell == i.key)):
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

    def rule(self, *, clearance: float, within=None, between=None, on=None, why: str = ""):
        """A design rule KiCad's DRC judges by: a `clearance` in one scope,
        `within=` a cell (its members to each other), `between=(net, net)`,
        or `on=` a net. Written as a custom rule beside the board; `why`
        names it, and a violation quotes the name."""
        from .rules import Rule
        if sum(x is not None for x in (within, between, on)) != 1:
            raise ValueError("a rule has one scope: within=, between= or on=")
        if not why:
            raise ValueError("a rule says why: it is named by it")
        rule = Rule("clearance", float(clearance), why,
                    within=self.geometry.cell(within).name if within is not None else None,
                    between=(self.geometry.require_net(between[0]), self.geometry.require_net(between[1])) if between else None,
                    on=self.geometry.require_net(on) if on is not None else None)
        self._rules.append(rule)
        return rule

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

    def _seed_hint(self, item, occ: Occupancy, targets: list, rotation: float, face) -> Placement:
        """Where the item's origin should go for its wired pads to sit on
        the weighted centroid of the placed pads they connect to."""
        current = occ._geometry(item).reference
        wsum = sum(w for _, _, w in targets)
        cx = sum(t.x * w for _, t, w in targets) / wsum
        cy = sum(t.y * w for _, t, w in targets) / wsum
        pads_now = occ.candidate_pad_locations(item, Placement(current.location, rotation, face))
        own = [pads_now[k] for k, _, _ in targets if k in pads_now]
        ox = sum(p.x for p in own) / len(own) - current.location.x if own else 0.0
        oy = sum(p.y for p in own) / len(own) - current.location.y if own else 0.0
        return Placement(Location(round(cx - ox, 3), round(cy - oy, 3)), rotation, face)

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

    def label(self, item, text: str, *, side: Edge = Edge.NORTH, gap: float = 0.5, align: str = "centre",
              size: float = 1.0, thickness: float = 0.15, knockout: bool = False, rotation: float = 0.0,
              why: str = ""):
        """Silkscreen text that marks a user-facing feature: a connector,
        jumper, switch or LED. It sits `gap` off `side` of the item's reach
        (a Part or Cell) or of one pad (a PadRef/CellPadRef), on the item's
        own face, aligned `"centre"`, `"start"` (west or north end) or
        `"end"` along that side; `rotation=90` runs it up the page;
        `knockout` cuts it out of a filled box. Written after placement,
        so it follows the item wherever it lands."""
        if align not in ("centre", "start", "end"):
            raise ValueError("a label aligns centre, start or end, not %r" % (align,))
        if rotation not in (0, 90):
            raise ValueError("a label reads across (0) or up the page (90), not %r" % (rotation,))
        if isinstance(item, (PadRef, CellPadRef)):
            self._pad_ref(item)                             # a real pad, checked now
            key = "label %s %s" % (self._pad_ref(item)[0], text)
        else:
            key = "label %s %s" % (self._item(item)[1], text)
        self._labels.append((key, item, text, Edge(side), float(gap), align, float(size), float(thickness),
                             bool(knockout), float(rotation), why))
        return key

    def _width(self, net: str, width) -> float:
        return float(width) if width is not None else self.geometry.netclass(net).track_width

    def track(self, net, points, *, layer: CopperLayer, width: float | None = None, chamfer: float = 1.0,
              priority: Priority = Priority.DEFAULT, bridge: bool = False, why: str = ""):
        """Track segments through `points` in order, on one layer. A point is
        a Location, a pad reference, a Mid, or an (x, y) pair whose members
        may be numbers or X()/Y() of a reference. Legs run at 0, 45 or 90
        degrees only: a leg at another angle is a 45 and a straight, the 45
        at the pad end. Every corner is cut back `chamfer`
        along both legs (a right angle becomes two 45s; a short leg gets a
        shorter cut; `chamfer=0` keeps sharp corners). `bridge=True`
        lets it pass under a same-layer track of another net it crosses (a
        via, a track on the opposite face, a via back) when it is the one
        that must yield: the lower priority, or at equal priority the shorter."""
        layer = CopperLayer.of(layer)
        refs = _refs_in(points)
        name = self.geometry.require_net(net)
        w = self._width(name, width)

        def plan(ctx):
            pads = [isinstance(p, (PadRef, CellPadRef)) for p in points]

            def clear(a, b):          # a leg that touches no pad of another net
                shape = _shape_of(Track(name, layer, w, a, b))
                return not ctx.occ.copper_conflicts(shape)
            located = [ctx.locate(p) for p in points]
            pts = octilinear(located, pads, clear)
            ops = polyline_tracks(name, layer, w, chamfered(pts, chamfer))
            if len(points) > 2 and any(not clear(t.start, t.end) for t in ops):
                # the script's waypoints steer this track into a pad: would pad to pad clear?
                direct = polyline_tracks(name, layer, w, chamfered(octilinear([located[0], located[-1]], [pads[0], pads[-1]], clear), chamfer))
                if all(clear(t.start, t.end) for t in direct):
                    ctx.notes.append("track %s: a waypoint steers it into another net's pad; drawn pad to pad it clears, "
                                     "so drop the waypoint(s) unless the route must go there" % name)
            return ops
        return self._copper_intent("track %s" % name, net, priority, plan, refs, why, bridge)

    def pair(self, net_p, net_n, path, *, layer: CopperLayer, width: float | None = None, gap: float | None = None,
             chamfer: float = 0.5, via_step: float = 0.4, priority: Priority = Priority.DEFAULT,
             bridge: bool = False, why: str = ""):
        """Two nets drawn together at `gap` along one centreline. `path`
        starts and ends with a (P pad, N pad) tuple; the points between are
        the centreline. Width and gap default to the P net's class. Corners
        are chamfered at 45, each track leaves its pad at 45, and a lead that
        would touch the partner goes over the other face from a via."""
        layer = CopperLayer.of(layer)
        p_name, n_name = self.geometry.require_net(net_p), self.geometry.require_net(net_n)
        nc = self.geometry.netclass(p_name)
        w = float(width) if width is not None else (nc.diff_pair_width or nc.track_width)
        g = float(gap) if gap is not None else (nc.diff_pair_gap or nc.clearance)
        if len(path) < 3:
            raise ValueError("a pair needs its two pad pairs and at least one centreline point between")
        (sp, sn), (ep, en), mids = path[0], path[-1], path[1:-1]
        refs = _refs_in(path)

        def pad_end(rp, rn, ctx):
            out = []
            for r in (rp, rn):
                owner, number, _, _ = self._pad_ref(r)
                pad = next(p for p in self.geometry.footprint(owner).pads if p.number == number)
                out.append((ctx.locate(r), pad.through, layer if layer in pad.layers else next(iter(pad.layers))))
            (lp, tp, fp), (ln, tn, fn) = out
            return (lp, ln, tp, tn), (fp, fn)

        def plan(ctx):
            start, sfaces = pad_end(sp, sn, ctx)
            end, efaces = pad_end(ep, en, ctx)
            centre = [ctx.locate(m) for m in mids]
            return pair_ops(p_name, n_name, layer, w, g, start, centre, end, self.via_drill, self.via_size,
                            via_step, chamfer, self.geometry.clearance(p_name, n_name), sfaces, efaces)
        return self._copper_intent("pair %s/%s" % (p_name, n_name), net_p, priority, plan, refs, why, bridge)

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
        for intent in self._intents:
            declared = [intent.item.anchor] + [fp for fp, _ in intent.item.satellites] if intent.kind == "block" else [intent.item]
            for item in declared:
                occ.pending |= occ._geometry(item).owners
        plan = Plan(self.geometry, occ, outline=self._outline, chamfer=self._chamfer, radius=self._radius,
                    rules=list(self._rules))
        ctx = _CopperContext(self, occ)
        placements = sorted(self._intents, key=lambda i: i.rank)
        fixed_copper = [c for c in self._copper if c.priority is Priority.FIXED]
        other_copper = [c for c in self._copper if c.priority is not Priority.FIXED]
        placed: set = set()

        def place_one(obj, why_now=""):
            plan._items[obj.key] = obj.item
            step = self._settle(occ, obj, plan, placed)
            if why_now:
                step.note = (why_now + "; " + step.note) if step.note else why_now
            plan.steps.append(step)
            if step.placement is None and obj.priority is Priority.HIGH and not self.keep_going:
                raise CriticalUnplaced(obj.key, self._no_place_report(occ, obj, step), plan)
            if step.placement is None:
                pass                    # unplaced: left off the board, pulls nothing, blocks nothing
            elif obj.kind == "block":
                occ.commit(obj.item.anchor, step.placement)
                placed.update(fp.ref for fp in obj.item.members)
            else:
                occ.commit(obj.item, step.placement)
                placed.update(fp.ref for fp in (obj.item.members if obj.kind == "cell" else (obj.item,)))
            if progress:
                progress(_fmt(step))

        def place_ranked(lo, hi):
            """FIXED and EDGE go down in declaration order: nothing yields to
            them, so their order changes nothing. Searched tiers are ordered
            by the placer, one choice at a time, re-measured after each."""
            firm = [obj for obj in placements if lo <= obj.rank[0] <= hi and obj.priority in (Priority.FIXED, Priority.EDGE)]
            while firm:                     # declaration order, except that a position said in terms of a pad waits for it
                ready = [obj for obj in firm if obj.needs <= placed]
                if not ready:
                    raise ValueError("%s is placed relative to %s, which is not placed by then (only FIXED and EDGE "
                                     "items may be referred to)" % (firm[0].key, ", ".join(sorted(firm[0].needs - placed))))
                place_one(ready[0])
                firm.remove(ready[0])
            collisions = [f for f in plan.findings if f.split(" ")[1] in ("(fixed):", "(edge):")]
            if collisions and not self.keep_going:
                raise PlacementCollision(collisions)
            pending = [obj for obj in placements if lo <= obj.rank[0] <= hi
                       and obj.priority not in (Priority.FIXED, Priority.EDGE)]
            while pending:
                obj, why_now = self._next_to_place(pending, occ, placed)
                pending.remove(obj)
                place_one(obj, why_now)

        place_ranked(RANK_FIXED, RANK_CELL)
        self._plan_copper(occ, ctx, fixed_copper, plan, progress)
        place_ranked(RANK_BLOCK, RANK_BLOCK)
        place_ranked(RANK_LOOSE, RANK_LOOSE)
        self._plan_copper(occ, ctx, other_copper, plan, progress)
        self._report_links(occ, plan, placed)
        self._place_labels(occ, plan, placed, progress)
        return plan

    def _settle_in_pocket(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """Nothing this item connects to is placed and no hint was given: put
        it in the biggest free rectangle its envelope fits, trying each
        rotation asked for (and the two orthogonal ones when none was)."""
        rots = list(i.rotations) or [i.rotation, (i.rotation + 90) % 360]
        tried = []
        for rot in rots:
            env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, i.face))
            for pocket in pockets(occ, env.width, env.height, i.face, step=max(i.step, 0.5)):
                hint = box_centered_placement(occ, i.item, pocket.box.center, rot, i.face)
                result = scan(occ, i.item, hint, max(pocket.box.width, pocket.box.height) / 2, i.step, (rot,), clr)
                if result.chosen is not None:
                    note = "pocket %.1f x %.1f at (%.1f, %.1f): nothing it connects to is placed" % (
                        pocket.box.width, pocket.box.height, pocket.box.center.x, pocket.box.center.y)
                    return Step(i.key, i.kind, i.priority, result.chosen, 0.0, note, i.why)
                tried.append(pocket)
        current = occ._geometry(i.item).reference
        plan.findings.append("%s: no pocket fits its %s envelope on the %s face (%d pocket(s) tried)" % (
            i.key, "%.1f x %.1f" % (occ.body_box(i.item, Placement(Location(0, 0), i.rotation, i.face)).width,
                                    occ.body_box(i.item, Placement(Location(0, 0), i.rotation, i.face)).height),
            i.face.value, len(tried)))
        return Step(i.key, i.kind, i.priority, None, 0.0, "UNPLACED: no pocket fits", i.why)

    def _declared_refs(self) -> set:
        """Every refdes a placement declaration covers."""
        out = set()
        for i in self._intents:
            parts = [i.item.anchor] + [fp for fp, _ in i.item.satellites] if i.kind == "block" else \
                (list(i.item.members) if i.kind == "cell" else [i.item])
            out |= {fp.ref for fp in parts}
        return out

    def _place_labels(self, occ, plan: Plan, placed: set, progress):
        declared = self._declared_refs()
        for key, item, text, side, gap, align, size, thick, knockout, rotation, why in self._labels:
            if isinstance(item, (PadRef, CellPadRef)):
                owner, number, _, _ = self._pad_ref(item)
                if owner in declared and owner not in placed:
                    raise ValueError("%s: %s was declared but found no place" % (key, owner))
                g = occ.items[owner]
                box = Box.union([s.box for s in g.shapes if s.kind in ("pad", "through") and s.label == number])
                face = g.reference.face
            else:
                geom, ikey, kind = self._item(item)
                refs = [fp.ref for fp in (geom.members if kind == "cell" else (geom,))]
                if any(r in declared and r not in placed for r in refs):
                    raise ValueError("%s: %s was declared but found no place" % (key, ikey))
                box = Box.union([occ.items[r].reach or occ.items[r].body for r in refs])
                face = occ.items[refs[0]].reference.face
            op = _label_op(text, box, face, side, gap, align, size, thick, knockout, rotation)
            plan.copper.append(op)
            hits = sorted({occ.who(r) for r, g in occ.items.items()
                           if g.reference.face is face and (g.reach or g.body).overlaps(op.box)} - {occ.who(r) for r in
                          ([self._pad_ref(item)[0]] if isinstance(item, (PadRef, CellPadRef)) else refs)})
            note = "%s of %s" % (side.name.lower(), key.split(" ", 2)[1])
            if hits:
                plan.findings.append("%s: sits on %s" % (key, ", ".join(hits)))
                note += "; sits on " + ", ".join(hits)
            plan.steps.append(Step(key, "copper", Priority.DEFAULT, None, 0.0, note, why, 1))
            if progress:
                progress("%-28s copper  label    %s" % (key, note))

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
        plan.findings += findings + ctx.notes
        ctx.notes = []
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

    def _no_place_report(self, occ: Occupancy, obj, step) -> str:
        """Why a critical item stopped the run: its envelope, the reason, and
        the biggest free rectangles on its face, so the reader can see what
        would have to move."""
        item = obj.item.anchor if obj.kind == "block" else obj.item
        env = occ.body_box(item, Placement(Location(0, 0), obj.rotation, obj.face))
        free = pockets(occ, 2.0, 2.0, obj.face, step=0.5, limit=4)
        rects = "; ".join("%.1f x %.1f at (%.1f, %.1f)" % (p.box.width, p.box.height, p.box.center.x, p.box.center.y)
                          for p in free) or "none"
        return ("%s (HIGH priority) found no place for its %.1f x %.1f envelope on the %s face: %s. "
                "Biggest free rectangles there now: %s. The board as it stood is written; nothing was placed after it."
                % (obj.key, env.width, env.height, obj.face.value, step.note.replace("UNPLACED: ", ""), rects))

    def _next_to_place(self, pending: list, occ: Occupancy, placed: set):
        """Which searched item goes down next, and why. Fit (the item's
        courtyard over the free board) dominates: an item needing more than
        a quarter of what is left goes now. Otherwise the strongest pull
        toward what is already placed, then the largest, then the name."""
        free = max(occ.free_area(), 1e-9)

        def measure(obj):
            parts = obj.item.members if obj.kind == "block" else (obj.item,)
            area = sum(s.box.area for it in parts for s in occ._geometry(it).shapes if s.kind == "courtyard")
            pull = sum(w for it in parts for _, _, w in self._targets(it, occ, placed))
            return area / free, pull, area

        scored = sorted(((measure(o), o) for o in pending),
                        key=lambda m: (-m[1].priority.rank, -(m[0][0] > 0.25), -m[0][1], -m[0][2], m[1].key))
        (fit, pull, area), obj = scored[0]
        kind = {"cell": "cells", "block": "blocks"}.get(obj.kind, "parts")
        if fit > 0.25:
            why = "next among %s: needs %.0f%% of the free board" % (kind, 100 * fit)
        elif pull > 0:
            why = "next among %s: strongest pull (%d) toward what is placed" % (kind, pull)
        else:
            why = "next among %s: largest (%.0f mm2), nothing placed pulls any" % (kind, area)
        return obj, why

    def _settle_block(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set) -> Step:
        spec = i.item
        clr = self.clearance
        if i.at is not None or i.center is not None:
            anchor = Placement(i.at, i.rotation, i.face) if i.at is not None else \
                box_centered_placement(occ, spec.anchor, i.center, i.rotation, i.face)
            members, why = layout_block(occ, spec, anchor, clr)
            if members is None:
                plan.findings.append("%s (fixed): %s" % (i.key, why))
                members = {spec.anchor.inst: anchor}
            note = why or ""
        else:
            targets = self._targets(spec.anchor, occ, placed)
            current = occ._geometry(spec.anchor).reference
            if i.near is not None:
                hint = Placement(i.near, i.rotation, i.face)
            elif targets:
                hint = self._seed_hint(spec.anchor, occ, targets, i.rotation, i.face)
            elif self._outline is not None:  # nothing placed pulls it: search from the board, not from where the generator dropped it
                hint = Placement(self._outline.center, i.rotation, i.face)
            else:
                hint = Placement(current.location, i.rotation, i.face)
            score = None
            if targets:
                def score(members):
                    return self._scorer(spec.anchor, occ, targets)(members[spec.anchor.inst])
            body = occ._geometry(spec.anchor).body
            radius = i.radius if i.near is not None else max(i.radius, body.width, body.height)
            best, tried, rejected, reasons = scan_block(occ, spec, hint, radius, i.step, i.rotations or (i.rotation,), clr, score)
            if best is None:
                plan.findings.append("%s: no legal spot within %.1f mm of %s (%s)" % (
                    i.key, radius, _loc(hint.location), ", ".join("%s x%d" % kv for kv in rejected.most_common(3))))
                members = {}
                note = "UNPLACED"
            else:
                _, anchor, members = best
                moved = anchor.location.distance(hint.location)
                note = "block of %d laid out from the anchor's pads" % len(members)
                if moved > 0:
                    note += "; moved %.2f mm off the hint" % moved
                    first = next(iter(reasons.values()), "")
                    note += (": " + first) if first else ""
        for fp in spec.members:
            if fp.inst in members and fp is not spec.anchor:
                plan._items[fp.inst] = fp
                plan.steps.append(Step(fp.inst, "part", i.priority, members[fp.inst], 0.0, "in %s" % i.key))
                occ.commit(fp, members[fp.inst])
        plan._items[spec.anchor.inst] = spec.anchor
        anchor_at = members.get(spec.anchor.inst)
        plan.steps.append(Step(spec.anchor.inst, "part", i.priority, anchor_at, 0.0, "anchor of %s" % i.key))
        return Step(i.key, "block", i.priority, anchor_at, 0.0, note, i.why)

    def _settle(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set = frozenset()) -> Step:
        if i.kind == "block":
            return self._settle_block(occ, i, plan, placed)
        clr = self.clearance
        if i.priority in (Priority.FIXED, Priority.EDGE):
            if i.at is not None:
                p = Placement(_locate(self, occ, i.at), i.rotation, i.face)
            elif i.center is not None:
                p = box_centered_placement(occ, i.item, _locate(self, occ, i.center), i.rotation, i.face)
            else:
                along = i.along.resolve(self, occ) if isinstance(i.along, _RowSlot) else _coord(self, occ, i.along, "x" if i.edge in (Edge.NORTH, Edge.SOUTH) else "y")
                p = edge_placement(occ, i.item, i.edge, along, i.rotation, i.clearance, i.face)
            why = occ.legal(i.item, p, clr, past_edge=i.edge is not None and i.clearance < self.keep_in)
            if why:
                plan.findings.append("%s (%s): %s" % (i.key, i.priority.value, why))
            return Step(i.key, i.kind, i.priority, p, 0.0, why or "", i.why)
        current = occ._geometry(i.item).reference
        targets = self._targets(i.item, occ, placed)
        seeded = ""
        if i.near is not None:
            hint = Placement(i.near, i.rotation, i.face)
        elif targets:
            hint = self._seed_hint(i.item, occ, targets, i.rotation, i.face)
            # k[1] here is always a raw pad NUMBER string from _targets() (never
            # a net name) - some real footprints number pads like "1'" for a
            # mechanically doubled leg, which is not all-digit, so this matches
            # p.number directly instead of going through pad_key()'s int/net
            # guess (which mis-reads a non-digit pad number as a net name).
            nets = sorted({p.net for k, _, _ in targets
                           if k[0] in {fp.ref for fp in (i.item.members if i.kind == "cell" else (i.item,))}
                           for p in self.geometry.footprint(k[0]).pads if p.number == k[1]})
            seeded = "seeded on %s" % ", ".join(nets)
        else:
            return self._settle_in_pocket(occ, i, plan, clr)
        score = self._scorer(i.item, occ, targets) if targets else None
        # A seeded item lands on the pads that pull it; it must be free to step at least its own size clear of them.
        body = occ._geometry(i.item).body
        radius = i.radius if i.near is not None else max(i.radius, body.width, body.height)
        result = scan(occ, i.item, hint, radius, i.step, i.rotations or (i.rotation,), clr, score=score)
        if result.chosen is None:
            plan.findings.append("%s: no legal location within %.1f mm of %s (%s)" % (
                i.key, radius, _loc(hint.location), ", ".join("%s x%d" % kv for kv in result.rejected.most_common(3))))
            return Step(i.key, i.kind, i.priority, None, 0.0, "UNPLACED: " + "; ".join(result.reasons.values()), i.why)
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

def _label_op(text, box: Box, face: Face, side: Edge, gap: float, align: str, size: float, thick: float,
              knockout: bool, rotation: float) -> Text:
    """The anchor and justification that put the text `gap` off `side` of
    `box`, aligned along that side. Along a north or south side `start` is
    the west end; along an east or west side it is the north end."""
    mirrored = face is Face.BACK
    def T(*a):
        return Text(*a, side=side)
    if rotation == 0:
        along = {"centre": ("centre", box.center.x), "start": ("left", box.left), "end": ("right", box.right)}
        across = {"centre": ("centre", box.center.y), "start": ("top", box.top), "end": ("bottom", box.bottom)}
        if side is Edge.NORTH:
            hj, x = along[align]; return T(text, Location(x, box.top - gap), face, size, thick, 0.0, hj, "bottom", knockout, mirrored)
        if side is Edge.SOUTH:
            hj, x = along[align]; return T(text, Location(x, box.bottom + gap), face, size, thick, 0.0, hj, "top", knockout, mirrored)
        if side is Edge.WEST:
            vj, y = across[align]; return T(text, Location(box.left - gap, y), face, size, thick, 0.0, "right", vj, knockout, mirrored)
        vj, y = across[align]; return T(text, Location(box.right + gap, y), face, size, thick, 0.0, "left", vj, knockout, mirrored)
    # 90 counter-clockwise: the text runs up the page, its top faces west
    along = {"centre": ("centre", box.center.y), "start": ("right", box.top), "end": ("left", box.bottom)}
    across = {"centre": ("centre", box.center.x), "start": ("bottom", box.left), "end": ("top", box.right)}
    if side is Edge.WEST:
        hj, y = along[align]; return T(text, Location(box.left - gap, y), face, size, thick, 90.0, hj, "bottom", knockout, mirrored)
    if side is Edge.EAST:
        hj, y = along[align]; return T(text, Location(box.right + gap, y), face, size, thick, 90.0, hj, "top", knockout, mirrored)
    if side is Edge.NORTH:
        vj, x = across[align]; return T(text, Location(x, box.top - gap), face, size, thick, 90.0, "left", vj, knockout, mirrored)
    vj, x = across[align]; return T(text, Location(x, box.bottom + gap), face, size, thick, 90.0, "right", vj, knockout, mirrored)


def _locate(board: "Board", occ: Occupancy, ref) -> Location:
    """A point on the board as things stand: a Location, a pad reference
    (where that pad now is), the Mid of two points, or an (x, y) pair whose
    members may be numbers, X()/Y() of references, or row coordinates."""
    if isinstance(ref, Location):
        return ref
    if isinstance(ref, Mid):
        a, b = _locate(board, occ, ref.a), _locate(board, occ, ref.b)
        return Location((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)
    if isinstance(ref, tuple) and len(ref) == 2:
        return Location(_coord(board, occ, ref[0], "x"), _coord(board, occ, ref[1], "y"))
    owner, number, dx, dy = board._pad_ref(ref)
    return occ.pad_location(owner, number).offset(dx, dy)


def _coord(board: "Board", occ: Occupancy, v, axis: str) -> float:
    """One coordinate: a number, X()/Y() of a reference, a row coordinate,
    or a reference/point whose `axis` coordinate is meant."""
    if isinstance(v, X):
        return _locate(board, occ, v.ref).x + v.dx
    if isinstance(v, Y):
        return _locate(board, occ, v.ref).y + v.dy
    if isinstance(v, (PadRef, CellPadRef, Location, tuple, Mid)):
        l = _locate(board, occ, v)
        return l.x if axis == "x" else l.y
    if isinstance(v, RowCoord):
        return v.row.resolve(v.what, occ.board_box)
    return float(v)


class _CopperContext:
    def __init__(self, board: Board, occ: Occupancy):
        self.board, self.occ = board, occ
        self.planned_tracks: list = []     # every track planned so far (any batch)
        self.fixed_tracks: list = []       # tracks from the FIXED batch: never yield
        self.notes: list = []              # findings a copper plan raises about itself

    def locate(self, ref) -> Location:
        return _locate(self.board, self.occ, ref)

    def coord(self, v, axis: str) -> float:
        return _coord(self.board, self.occ, v, axis)

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
        elif isinstance(p, Mid):
            out += _refs_in([p.a, p.b])
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


STEP_HEADER = "%-28s %-6s %-8s %s" % ("item", "kind", "priority", "result")


def _fmt(s: Step) -> str:
    """One step, in the columns STEP_HEADER names. A placement's result is
    `at (x, y) rot R face F`; copper's is its op count."""
    if s.placement is None:
        return "%-28s %-6s %-8s %s" % (s.item, s.kind, s.priority.value, s.note)
    out = "%-28s %-6s %-8s at %s rot %g face %s" % (s.item, s.kind, s.priority.value, _loc(s.placement.location),
                                                     s.placement.rotation, s.placement.face.value)
    if s.note:
        out += "  " + s.note
    return out
