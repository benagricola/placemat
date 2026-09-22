"""The Board object a layout script declares to, and the Plan resolve()
produces from it.

Board answers questions about the generated board, records placement and
copper declarations, and resolves them in order (setup, the decided
placements, the copper whose endpoints are all decided, then every searched
item by rank, then the rest of the copper) against
the occupancy model. Plan holds the resolved placements, copper ops and
findings for the writer and the run record."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math

from .copper import (CopperOp, Pour, Text, Track, Via, Zone, board_zone_outline, chamfered, finger_ops, octilinear, pair_ops, polyline_tracks,
                     resolve_bridges)
from .geometry import circle_polygon, polygon_box, polys_overlap, transform_box
from .occupancy import Occupancy, Shape, TOUCH
from .cutouts import Cutouts, loop_gap, signed_area
from .outline import Outline, Run, rect_outline
from .placement import Placement
from .settings import Settings
from .placer import BlockSpec, _reason_key, box_centered_placement, disc_placement, pad_anchored_placement, edge_placement, layout_block, pockets, run_placement, scan, scan_block
from .board_geometry import BoardGeometry, CellGeom, Footprint, stackup_order
from .values import (Cutout, CutoutEdge, Freedom, Keepout, bearing_of, Along, Box, Cell, CellPadRef, Centre, Disc, OnBore, OnRim, Pin, Polar, bearing, bearing_vector, box_support, polar_point, CopperLayer, Edge, Face, Fraction, FreeSpot, LinkWeight, Location, Mid, Near, Net, OnEdge, PadRef, Part,
                     Priority, X, Y, pad_key)

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
class _EdgeFraction:
    """A distance along an edge as a fraction of its usable length, and how
    the item sits on it: its centre there (Along.MID, Fraction), or its
    near end flush with the edge's start, its far end with its end."""
    fraction: float
    anchor: str = "centre"          # start | centre | end


def _free_axis(value):
    """'x' or 'y' when a Location, Centre or (x, y) pair leaves that axis None."""
    if isinstance(value, (Location, Centre)):
        return value.free_axis
    if isinstance(value, tuple) and len(value) == 2 and (value[0] is None) != (value[1] is None):
        return "x" if value[0] is None else "y"
    return None


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
    pin_x: object = None               # x pinned (a number or a reference), y free
    pin_y: object = None               # y pinned, x free
    priority_source: str = "auto"      # "script" when the declaration said, else worked out
    faces_note: str = ""               # when the rotation fell back to the generic rule
    pinned_by: str = ""                # "at" (the origin sits on the line) or "center" (the body centre does)
    pin: object = None                 # a pad key: `center` is where that pad lands, not the body centre
    rim: str | None = None             # "rim" or "bore": a place against a round board's edge
    angle: float | None = None         # its bearing, when the script gave one; None slides round
    radius_at: object = None           # a Polar radius: the ring the item sits on
    outward: bool = False              # turn it to face out wherever it lands
    about: object = None               # the centre a radius and bearing are measured from
    run: object = None                 # a stretch of a shaped board's edge, from board.edge(facing=)
    freedom: Freedom = Freedom.SEARCHED   # derived from at=, never chosen
    required: bool = False                # failing to place this stops the run

    @property
    def rank(self):
        if self.freedom is Freedom.FIXED:
            return (RANK_FIXED, self.index)
        if self.freedom is Freedom.EDGE:
            return (RANK_EDGE, self.index)
        return ({"cell": RANK_CELL, "block": RANK_BLOCK}.get(self.kind, RANK_LOOSE), self.index)


@dataclass(frozen=True)
class PlacedCutout:
    """A hole once it has a position: what was cut, where, and which way."""
    name: str
    path: tuple
    centre: Location
    rotation: float


def cutout_token(name: str) -> str:
    """What a cutout is called in the `needs`/`placed` bookkeeping. Those
    sets hold refdes, and a cutout may perfectly well be named after the
    part it serves, so its token is namespaced: otherwise a hole called
    "U1" would tell everything waiting on the part U1 that it had been
    placed, and they would resolve against where the generator left it."""
    return "cutout:%s" % name


@dataclass(frozen=True)
class PlacedKeepout:
    """A region once it has a position: what it forbids, where, and to whom."""
    name: str
    poly: tuple
    centre: Location
    rotation: float
    excludes: tuple
    layers: tuple | None
    allow: frozenset
    owners: frozenset
    why: str


@dataclass
class KeepoutIntent:
    """A region waiting for its place. It sits in the firm queue with the
    parts and the cutouts, so `needs` orders it against whatever its place
    refers to."""
    key: str
    keepout: object
    why: str = ""
    index: int = 0
    needs: frozenset = frozenset()
    freedom: Freedom = Freedom.FIXED

    @property
    def rank(self):
        return (RANK_FIXED, self.index)


@dataclass
class CutoutIntent:
    """A hole waiting for its place. It sits in the firm queue with the
    parts, so `needs` orders it against whatever its place refers to: a slot
    inboard of a connector waits for the connector, and a part against that
    slot waits for the slot."""
    key: str
    cutout: object
    why: str = ""
    index: int = 0
    needs: frozenset = frozenset()
    freedom: Freedom = Freedom.FIXED

    @property
    def rank(self):
        return (RANK_FIXED, self.index)


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
    owners: frozenset = frozenset()       # refdes its endpoints belong to
    freedom: Freedom = Freedom.FIXED      # derived in resolve(), once every declaration is in

    @property
    def rank(self):
        return (RANK_FIXED_COPPER if self.freedom.decided else RANK_COPPER, self.index)


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
    priority: Priority | None            # None for a decided placement: it has none
    placement: Placement | None = None
    moved_mm: float = 0.0
    note: str = ""
    why: str = ""
    ops: int = 0
    freedom: Freedom | None = None       # None for a copper step and for a bridge note
    rank: int | None = None              # a searched item's place in the queue
    rank_of: int | None = None


class CutoutHandle:
    """One named cutout, and the stretches of its boundary.

    The only route to a cutout's runs: board.edge() reads the board's own
    outline, so a script asking for the board's edge can never be handed a
    hole's by accident."""
    __slots__ = ("_board", "name")

    def __init__(self, board, name: str):
        self._board, self.name = board, name

    @property
    def settled(self) -> bool:
        """Whether this hole has a position yet. One placed from a part is
        settled when that part is."""
        return self.name in self._board._cutout_loop_of

    def edges(self, side=None, within: float = 45.0, **kw) -> list:
        """The stretches of this cutout's boundary on that SIDE of it. The
        northern side is the boundary an item above the hole sits against,
        facing south into it."""
        if "facing" in kw:
            raise TypeError("a cutout takes side=, not facing=: side=Edge.NORTH is the hole's northern "
                            "boundary, which an item sits above and faces south into. facing= is the "
                            "board's word, for which way an item points, and on a hole the two read opposite")
        if kw:
            raise TypeError("unexpected argument(s) to a cutout's edges(): %s" % ", ".join(sorted(kw)))
        if side is None:
            raise TypeError("which side of the cutout: side=Edge.NORTH, a bearing, or Fraction(f)")
        if not self.settled:
            raise ValueError("cutout %r has no place yet, so its edges are not known. Place one item "
                             "against it with .edge(side=), which waits for it" % self.name)
        want = (bearing(side) + 180.0) % 360.0      # the run whose normal points back into the hole
        return self._board._shaped().runs(want, within, loop=self._board._cutout_loop_of[self.name])

    def edge(self, side=None, within: float = 45.0, **kw):
        """The one stretch on that side: a Run when the hole already has a
        place, else a CutoutEdge promise resolved when the item that asked
        for it is placed, by which time the hole is down. Several stretches
        (or none) is a script question, not a guess."""
        if not self.settled:
            if kw or side is None:
                self.edges(side, within, **kw)          # raise the same way for a bad call
            return CutoutEdge(self.name, side, within)
        runs = self.edges(side, within, **kw)
        if len(runs) == 1:
            return runs[0]
        if not runs:
            raise ValueError("no part of cutout %r is on the %r side within %g degrees"
                             % (self.name, side, within))
        raise ValueError("%d stretches of cutout %r are on the %r side within %g degrees (%s): "
                         "narrow within=, or pick from .edges()"
                         % (len(runs), self.name, side, within, ", ".join("%.2f mm" % r.length for r in runs)))

    @property
    def _loop(self):
        if not self.settled:
            raise ValueError("cutout %r has no place yet" % self.name)
        return self._board._shaped().loops[self._board._cutout_loop_of[self.name]]

    @property
    def box(self) -> Box:
        xs = [p[0] for p in self._loop]
        ys = [p[1] for p in self._loop]
        return Box(min(xs), min(ys), max(xs), max(ys))

    @property
    def centre(self) -> Location:
        return self.box.center

    @property
    def area(self) -> float:
        return abs(signed_area(self._loop))


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
    draw_outline: bool = True           # False: the outline is a placement frame only (a module fragment)
    chamfer: float = 0.0
    radius: float = 0.0
    shape: object | None = None         # the board when it is not a rectangle: a Disc or an Outline
    cutouts: object = field(default_factory=lambda: Cutouts())   # a rectangle's holes, for Edge.Cuts
    cutouts_placed: dict = field(default_factory=dict)           # every named cutout, once it has a place
    keepouts: dict = field(default_factory=dict)                 # every named keepout, once it has a place
    seeded_by_net: Counter = field(default_factory=Counter)      # net -> how many items it seeded
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
        if key not in self._items:
            if key in self.cutouts_placed:
                raise KeyError("%r is a cutout, not an item: plan.cutouts_placed[%r] is where it was "
                               "milled, and board.cutout(%r) reads its edges" % (key, key, key))
            raise KeyError("nothing placed as %r" % key)
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


@dataclass
class RunRow:
    """What a row along a run placed: the run, where each item's centre sits
    along it, how far into the board they reach and how much of the run they
    take together."""
    run: object
    alongs: list
    depth: float
    length: float
    items: list = field(default_factory=list)
    keys: list = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.alongs[0] if self.alongs else 0.0

    @property
    def end(self) -> float:
        return self.alongs[-1] if self.alongs else 0.0


@dataclass
class Ring:
    """What ring() placed: the circle it used (None at the rim), the bearing
    of each item, and how deep the deepest reaches along the radius."""
    radius: float | None
    angles: list
    depth: float
    items: list = field(default_factory=list)
    keys: list = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.angles[0] if self.angles else 0.0

    @property
    def end(self) -> float:
        return self.angles[-1] if self.angles else 0.0

    @property
    def span(self) -> float:
        """How much of the turn it takes, from the first item to the last."""
        return (self.end - self.start) % 360.0


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
                 via_drill: float = 0.3, via_size: float = 0.6, keep_going: bool = False,
                 courtyard_excess: float = 0.1, settings: Settings | None = None):
        self.settings = settings if settings is not None else Settings()
        self.geometry = geometry
        self.courtyard_excess = courtyard_excess    # the fab's assembly margin round a part: the only spacing that comes free
        self.edge_margin = geometry.edge_clearance if edge_margin is None else edge_margin
        self.clearance = clearance
        self.via_drill, self.via_size = via_drill, via_size
        self.keep_going = keep_going            # carry on past colliding decided items, as findings;
                                                # required=True overrides it
        self._intents: list = []            # placements and cutouts: one queue, ordered by needs
        self._rank_score: dict = {}
        self._rank_of: dict = {}
        self._rank_note: dict = {}
        self._copper: list[CopperIntent] = []
        self._labels: list = []
        self._faces: tuple | None = None
        self._links: list[Link] = []
        self._rules: list = []
        self._free_nets: set = set()
        self._outline: Box | None = geometry.outline_box
        self._shape = None                  # a board that is not a rectangle: a Disc or an Outline
        self._cutouts = Cutouts()           # a rectangle's holes; a Disc or an Outline keeps its own
        self._named_cutouts: dict = {}      # the cutouts a script named, in declaration order
        self._settled_cutouts: dict = {}    # those of them that already have a position
        self._cutout_loop_of: dict = {}     # name -> its loop index in _shaped()
        self._keepouts: dict = {}           # the regions a script declared, by name
        self.web = 0.0                      # least material a hole may leave; 0: unchecked
        self._cached_outline = None         # this board as an outline, for reading runs off
        self._sized = False                 # the script has declared the board size
        self._draw_outline = True
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
        from .describe import pitch_of
        fp = self.geometry.footprint(part)
        found = pitch_of(fp.pads)
        if found is None:
            raise ValueError("%s has %d pad(s): no pitch" % (fp.ref, len(fp.pads)))
        return found

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

    def claim(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """Everything the item claims at `rotation`, at the origin: its reach
        (body, pads, silk) and its courtyard together. What a row spaces by,
        so a zero gap is courtyards touching."""
        geom, _, _ = self._item(item)
        occ = Occupancy(self.geometry, self.edge_margin, board_box=None)
        p = Placement(Location(0.0, 0.0), rotation, face)
        courts = [transform_box(s.box, occ._transform(occ._geometry(geom), p))
                  for s in occ._geometry(geom).shapes if s.kind == "courtyard"]
        return Box.union([occ.reach_box(geom, p)] + courts)

    def reach(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """Everything the item physically is (body, pads, silk) at
        `rotation`, at the origin: what edge placement and rows measure."""
        geom, _, _ = self._item(item)
        occ = Occupancy(self.geometry, self.edge_margin, board_box=None)
        return occ.reach_box(geom, Placement(Location(0.0, 0.0), rotation, face))

    def _pad_ref(self, ref):
        """Validate a pad reference now; return (refdes, pad number, dx, dy).
        A Part or Cell reference (its body centre) yields its first refdes
        and no pad: enough for the placement order to wait for it."""
        if isinstance(ref, (Part, Cell)):
            geom, key, kind = self._item(ref)
            return ((geom.members[0].ref if kind == "cell" else geom.ref), None, 0.0, 0.0)
        if isinstance(ref, PadRef):
            p = self.geometry.pad(ref.part, ref.key)
            return (p.owner, p.number, ref.dx, ref.dy)
        if isinstance(ref, CellPadRef):
            p = self.geometry.cell_pad(ref.cell, net=ref.net, number=ref.number, ref_prefix=ref.ref_prefix)
            return (p.owner, p.number, ref.dx, ref.dy)
        raise TypeError("not a pad reference: %r" % (ref,))

    # ------------------------------------------------------------ setup
    def _add_cutout(self, occ, name: str, placed):
        """A hole that has just been settled. The board's own shape and the
        occupancy grow together, so every legality test after this one - the
        next cutout's, and every part's - sees it."""
        import dataclasses
        path = list(placed.path)
        if isinstance(self._shape, Disc):
            self._shape = dataclasses.replace(self._shape, holes=tuple(self._shape.holes) + (tuple(path),))
        elif isinstance(self._shape, Outline):
            self._shape = Outline.of(self._shape.paths[0], list(self._shape.paths[1:]) + [path])
        else:
            self._cutouts = Cutouts(list(self._cutouts.paths) + [path])
        self._cached_outline = None
        occ.board_shape, occ.board_cutouts = self._shape, self._cutouts
        self._cutout_loop_of[name] = len(self._shaped().loops) - 1
        self._settled_cutouts[name] = placed

    def _cutout_illegal(self, occ, path, name: str) -> str | None:
        """Why this hole may not be cut here, or None. In the spec's order:
        inside the board, clear of its outline, enough web, and not through
        anything already placed."""
        shape = self._shaped()
        loop = Cutouts([path]).loops[0]
        board = shape.loops[0]
        for x, y in loop:
            if shape.why_not(Box(x, y, x, y), 0.0) == "outside the board":
                return "reaches outside the board"
        if loop_gap(loop, board) <= 0.0:
            return ("touches the board outline: that is a notch, not a hole, and it belongs in the "
                    "board's own outline path")
        if self.web > 0.0:
            gap = min([loop_gap(loop, board)] + [loop_gap(loop, h) for h in shape.loops[1:]])
            if gap < self.web - 1e-9:
                return "would leave a %.2f mm web, under the %.2f mm minimum" % (gap, self.web)
        box = Box(min(p[0] for p in loop), min(p[1] for p in loop),
                  max(p[0] for p in loop), max(p[1] for p in loop))
        for owner, g in occ.items.items():
            if (g.reach or g.body).overlaps(box):
                return "would be milled through %s" % owner
        return None

    def _cutout_centre(self, occ, cutout) -> Location:
        """Where a decided place puts the hole's centre. Polar is a bearing
        and a radius about the board's centre, which _locate does not read
        because no part is ever placed that way."""
        at = cutout.at
        if isinstance(at, Polar):
            about = self.centre if at.about is None else _as_point(at.about)
            r = float(at.radius) if isinstance(at.radius, (int, float)) else _coord(self, occ, at.radius, "x")
            return polar_point(about, at.angle, r)
        if isinstance(at, OnEdge):
            run = at.edge if isinstance(at.edge, Run) else self.edge(facing=at.edge)
            along = at.along.fraction * run.length if isinstance(at.along, (Along, Fraction)) else float(at.along or 0.0)
            point, out = run.at(along)
            depth = max(self.web, 0.0) + _cutout_half_across(cutout, out)
            ux, uy = bearing_vector(out)
            return Location(round(point.x - ux * depth, 6), round(point.y - uy * depth, 6))
        return _locate(self, occ, at)

    def _cutout_free(self, cutout) -> bool:
        """Whether its place leaves a freedom for the board to settle."""
        at = cutout.at
        if isinstance(at, Centre):
            return at.free_axis is not None
        if isinstance(at, Polar):
            return at.radius is None or at.angle is None
        if isinstance(at, Location):
            return at.x is None or at.y is None
        return isinstance(at, Near)

    def _cutout_candidates(self, occ, cutout):
        """Every centre its one freedom allows, nearest its ideal first, with
        the rotation each implies. The board's middle is the ideal for a free
        axis, so a hole takes the room furthest from the edges first."""
        at, box = cutout.at, self._outline

        def out_from(mid, lo, hi, step=0.2):
            n = int((hi - lo) / step) + 1
            for k in range(2 * n):
                v = mid + (k + 1) // 2 * step * (1 if k % 2 else -1)
                if lo <= v <= hi:
                    yield v

        if isinstance(at, Polar) and at.angle is None:
            r = float(_coord(self, occ, at.radius, "x")) if not isinstance(at.radius, (int, float)) \
                else float(at.radius)
            for k in range(720):
                b = ((k + 1) // 2 * (1 if k % 2 else -1)) * 0.5
                centre = polar_point(self.centre, b % 360.0, r)
                yield centre, (float(cutout.rotation) if cutout.rotation is not None
                               else self._implied_rotation(cutout, centre))
            return
        if isinstance(at, Polar) and at.radius is None:
            hi = max(box.width, box.height) / 2.0
            for r in out_from(hi / 2.0, 0.0, hi):
                centre = polar_point(self.centre, bearing(at.angle), r)
                yield centre, (float(cutout.rotation) if cutout.rotation is not None
                               else self._implied_rotation(cutout, centre))
            return
        axis = at.free_axis if isinstance(at, Centre) else ("x" if at.x is None else "y")
        held = at.y if axis == "x" else at.x
        fixed = _coord(self, occ, held, "y" if axis == "x" else "x")
        lo, hi = (box.left, box.right) if axis == "x" else (box.top, box.bottom)
        for v in out_from((lo + hi) / 2.0, lo, hi):
            centre = Location(v, fixed) if axis == "x" else Location(fixed, v)
            yield centre, (float(cutout.rotation) if cutout.rotation is not None
                           else self._implied_rotation(cutout, centre))

    def _slide_cutout(self, occ, region, illegal=None):
        """The first place its freedom allows where the region is legal. When
        none is, the reason given is the one nearest its ideal - what stopped
        it where it wanted to be, not what stopped it at the far end of its
        travel, which is almost always just the board's edge.

        `illegal` is the test, because a hole's legality is not a keepout's: a
        region may touch the board edge, hang off it, and lie over a part it
        allows, so the keepout path passes `_keepout_unusable` and only a hole
        falls back to `_cutout_illegal`."""
        if illegal is None:
            def illegal(path):
                return self._cutout_illegal(occ, path, region.name)
        nearest = None
        for centre, turn in self._cutout_candidates(occ, region):
            why = illegal(region.shape.path_at(centre, turn))
            if why is None:
                return centre, turn
            if nearest is None:
                nearest = why
        raise ValueError("has nowhere legal to go: %s" % (nearest or "nowhere on the board"))

    def _keepout_unusable(self, path) -> str | None:
        """Why a region may not go here, or None.

        A keepout may touch the board edge, hang off it, and lie over anything
        it allows: a hole's rules are not a region's, so a sliding region must
        not be judged by `_cutout_illegal` or it would be pushed inboard and a
        band round the rim would be refused outright. The only place a region
        cannot go is entirely off the board, where it would forbid nothing."""
        outside, total = self._points_off_board(path)
        return "is wholly off the board" if outside == total else None

    def _points_off_board(self, path) -> tuple:
        """(points outside the board, points in all) for a region's boundary.

        A region is used exactly as declared: the part hanging off the board
        can refuse nothing, because `Occupancy.legal` rejects a part for
        crossing the keep-in before it ever tests a reservation, and KiCad
        clips a zone to Edge.Cuts itself. The count is reported so a region
        that is mostly off the board is visible; a point count, not an area,
        because a region whose boundary IS the outline has the board's own
        area and any area measure reads zero."""
        shape = self._shaped()
        loop = Cutouts([path]).loops[0]
        outside = sum(1 for x, y in loop
                      if shape.why_not(Box(x, y, x, y), 0.0) == "outside the board")
        return outside, len(loop)

    def _implied_rotation(self, cutout, centre: Location) -> float:
        """Which way a shape runs when the script did not say. A place that
        carries a direction - round a circle, along an edge - runs the shape
        TANGENTIALLY: a vent follows the rim, a cable slot runs parallel to
        the connector it serves. Everywhere else the shape is as declared,
        and a shape with no direction of its own is never turned."""
        if not getattr(cutout.shape, "turns", True):
            return 0.0
        # A shape runs along +X at rotation 0, which is bearing 90, so running it
        # along bearing B is a rotation of B - 90. Tangential is B + 90 - 90: the
        # outward bearing itself.
        if isinstance(cutout.at, Polar):
            return bearing_of(centre.x - self.centre.x, centre.y - self.centre.y) % 360.0
        if isinstance(cutout.at, OnEdge):
            run = cutout.at.edge if isinstance(cutout.at.edge, Run) else self.edge(facing=cutout.at.edge)
            return run.at(run.project(centre))[1] % 360.0
        return 0.0

    def _check_settled_cutouts(self, occ, plan: "Plan"):
        """A cutout declared at an absolute place is already in the board's
        shape, so it never passes through the queue. It is still checked: it
        may reach outside the board, notch its edge, or leave too thin a web.
        A part milled through by one is caught the other way round, when the
        part is refused for sitting inside a cutout."""
        for name, settled in self._settled_cutouts.items():
            shape = self._shaped()
            loop = Cutouts([list(settled.path)]).loops[0]
            board = shape.loops[0]
            others = [h for n, h in enumerate(shape.loops[1:], start=1)
                      if n != self._cutout_loop_of.get(name)]
            why = None
            for x, y in loop:
                if shape.why_not(Box(x, y, x, y), 0.0) == "outside the board":
                    why = "reaches outside the board"
                    break
            if why is None and loop_gap(loop, board) <= 0.0:
                why = ("touches the board outline: that is a notch, not a hole, and it belongs in the "
                       "board's own outline path")
            if why is None and self.web > 0.0:
                gap = min([loop_gap(loop, board)] + [loop_gap(loop, h) for h in others])
                if gap < self.web - 1e-9:
                    why = "would leave a %.2f mm web, under the %.2f mm minimum" % (gap, self.web)
            if why:
                plan.findings.append("%s (cutout): %s" % (name, why))
            plan.cutouts_placed[name] = settled

    def _check_keepouts(self, plan: Plan):
        """Copper the script drew, crossing a region that forbids it.

        A plane is a KiCad zone and the filler honours the rule area, so it
        is not checked here. A pour keeps exactly the shape it is given, and
        a track and a via go exactly where they are put, so those are
        reported rather than silently reshaped."""
        kinds = {Pour: ("pour", "fill"), Track: ("track", "tracks"), Via: ("via", "vias")}
        for op in plan.copper:
            named = kinds.get(type(op))
            if named is None:
                continue                            # a Zone: the rule area governs it
            word, excluded = named
            for k in plan.keepouts.values():
                if excluded not in k.excludes or op.net in k.allow:
                    continue
                if k.layers is not None and not (_op_layers(op) & frozenset(k.layers)):
                    continue                        # the region does not cover this op's layer
                if not Box.of_points(k.poly).overlaps(op.box):
                    continue
                if polys_overlap(k.poly, op.polygon):
                    plan.findings.append(
                        "%s %s crosses keepout %r (%s): a %s goes exactly where it is put, so move it, "
                        "reshape it, or name its net in the keepout's allow="
                        % (word, op.net, k.name, k.why, word))

    def _check_web(self, plan: "Plan"):
        """How much board is left round every hole. A web under the declared
        minimum is a sliver: it snaps in depanelling or in the hand."""
        if self.web <= 0.0:
            return
        shape = self._shaped()          # always an Outline, whatever the board was declared as
        holes = Cutouts(shape.paths[1:])
        if not holes:
            return
        gap, which = holes.web_against([shape.loops[0]])
        if gap < self.web - 1e-9:
            plan.findings.append("web %.2f mm round %s is under the %.2f mm minimum"
                                 % (gap, self._cutout_label(which), self.web))

    def _cutout_label(self, n: int) -> str:
        """Which hole a measurement was taken on. Named cutouts come first,
        in declaration order, so the index names one directly."""
        order = list(self._named_cutouts)
        return "cutout %r" % order[n] if 0 <= n < len(order) else "an unnamed cutout"

    def keepout(self, shape, name: str, *, at, rotation: float | None = None,
                excludes=None, allow=(), layers=None, why: str = "") -> KeepoutIntent:
        """A region that forbids. By default nothing may sit, fill, route, via
        or pad there on any copper layer the board has; `excludes` narrows
        what and `layers` narrows where. `allow` names the parts that may sit
        inside and the nets that may run through, which are different things:
        an antenna's clearance holds its own matching network, and naming
        those parts' nets would admit every part that shares one."""
        if name in self._keepouts:
            raise ValueError("there is already a keepout named %r on this board" % name)
        clash = [r for r in self.geometry.rule_areas if r.base == "keepout %s" % name]
        if clash:
            raise ValueError(
                "the generated board already carries a rule area called %r%s, so a keepout named "
                "%r would leave two regions and no way to say which one won; pick another name"
                % (clash[0].name, (" from the %s cell" % clash[0].cell) if clash[0].cell else "",
                   name))
        k = Keepout(shape, name, at, rotation,
                    tuple(excludes) if excludes is not None
                    else ("parts", "fill", "tracks", "vias", "pads"),
                    tuple(allow),
                    None if layers is None else tuple(CopperLayer.of(l) for l in layers), why)
        self._keepouts[name] = k
        needs = frozenset(self._pad_ref(r)[0] for r in _refs_in([at]))
        settled = not self._cutout_free(k)
        intent = KeepoutIntent("keepout %s" % name, k, why, len(self._intents), needs,
                               Freedom.FIXED if settled else Freedom.SEARCHED)
        self._intents.append(intent)
        return intent

    def _report_lost_layers(self, plan: Plan):
        """A keepout on a layer its board does not have is recorded in its zone
        name and honoured by a board that has the layer, but on this one it
        holds nothing there - so it is said, not dropped. The same for a
        stamped module's rule area declaring a layer this board lacks too."""
        have = set(self.geometry.layers)
        for k in self._keepouts.values():
            lost = sorted((l for l in (k.layers or ()) if l not in have), key=stackup_order)
            if lost:
                plan.findings.append(
                    "keepout %s declares %s, which this %d-layer board does not have: recorded "
                    "in its name, and honoured by a board that has it"
                    % (k.name, ", ".join(l.value for l in lost), len(self.geometry.layers)))
        for r in self.geometry.rule_areas:
            if r.missing:
                plan.findings.append(
                    "%s from the %s cell declares %s, which this board does not have either"
                    % (r.base, r.cell or "board", ", ".join(l.value for l in r.missing)))

    def cutout(self, name: str) -> CutoutHandle:
        """A named cutout, so something can be placed against its boundary."""
        order = list(self._named_cutouts)
        if name not in self._named_cutouts:
            raise ValueError("no cutout named %r on this board%s" % (
                name, (": there is " + ", ".join(repr(n) for n in order)) if order else
                ". Only a named Cutout(shape, name, at=) can be referred to, not a raw path"))
        return CutoutHandle(self, name)

    def _cutout_paths(self, holes) -> tuple:
        """`holes` as absolute paths. A raw path is already where it goes; a
        Cutout is a shape and a place, and is settled here. Named cutouts
        come first, in declaration order, so board.cutout(name) can find its
        loop by index."""
        named_paths, raw, named = [], [], {}
        self._cutout_loop_of = {}
        for h in holes:
            if not isinstance(h, Cutout):
                raw.append(list(h))
                continue
            if h.name in named:
                raise ValueError("there is already a cutout named %r on this board" % h.name)
            named[h.name] = h
            if isinstance(h.at, Location) and isinstance(h.at.x, (int, float)) and isinstance(h.at.y, (int, float)):
                named_paths.append(h.shape.path_at(h.at, h.rotation or 0.0))   # absolute: settled now
                self._cutout_loop_of[h.name] = len(named_paths)                # loop 0 is the board
                self._settled_cutouts[h.name] = PlacedCutout(
                    h.name, tuple(named_paths[-1]), h.at, float(h.rotation or 0.0))
            else:
                needs = frozenset(self._pad_ref(r)[0] for r in _refs_in([h.at]))
                # a decided place goes down in declaration order with the firm items; one with a
                # freedom waits until every decided thing is down, then takes the room that is left
                settled = not self._cutout_free(h)
                self._intents.append(CutoutIntent("cutout %s" % h.name, h, h.why, len(self._intents),
                                                  needs,
                                                  Freedom.FIXED if settled else Freedom.SEARCHED))
        self._named_cutouts = named
        return tuple(named_paths) + tuple(raw)

    def size(self, width: float, height: float, chamfer: float = 0.0, radius: float = 0.0,
             holes=(), web: float = 0.0, draw: bool = True):
        """The board outline: a rectangle at the origin, chamfered or rounded.
        `holes` are cutouts in it - a slot for a cable, a window - each a
        closed path of straight legs and arcs, the same as any other board's."""
        if width <= 0 or height <= 0:
            raise ValueError("board size must be positive")
        self._outline = Box(0.0, 0.0, float(width), float(height))
        self._shape = None
        self._cached_outline = None
        self.web = float(web)
        self._cutouts = Cutouts(self._cutout_paths(holes))
        self._chamfer, self._radius = chamfer, radius
        self.width, self.height = float(width), float(height)
        self._sized = True
        self._draw_outline = draw          # a fragment's frame is for placement only, never written

    def disc(self, diameter: float, hole: float = 0.0, holes=(), web: float = 0.0, draw: bool = True):
        """The board outline: a round board at the origin, `hole` wide through
        the middle when it goes round a shaft. A circle has no sides, so
        places on it are said as a bearing and a radius: OnRim, OnBore,
        Polar and ring(). `holes` are cutouts anywhere in it - a slot for a
        cable, a window - each a closed path of straight legs and arcs, the
        same as a shaped board's."""
        d = float(diameter)
        self.web = float(web)
        self._shape = Disc(Location(d / 2.0, d / 2.0), d, float(hole), self._cutout_paths(holes))
        self._cutouts = Cutouts()           # a disc keeps its own
        self._cached_outline = None
        self._outline = self._shape.box
        self._chamfer = self._radius = 0.0
        self.width = self.height = d
        self._sized = True
        self._draw_outline = draw

    def outline(self, path, holes=(), web: float = 0.0, draw: bool = True):
        """The board outline as a closed path of straight legs and arcs: the
        first element is where it starts, each one after it is a point (a
        straight leg to it) or an Arc(to=, via=) that curves through a point,
        and it closes back to the start. It may also be a shape - `Circle(d)`,
        `Slot(l, w)`, `Path(points)` - which is centred on the board origin.
        `holes` are cutouts, each a `Cutout` or a path of its own. Stretches
        of it are selected by which way they face, with board.edge(facing=)."""
        if hasattr(path, "path_at"):        # a shape, not a path: the board sits at the origin
            lo_x, lo_y, hi_x, hi_y = path.box_at(Location(0.0, 0.0), 0.0)
            path = path.path_at(Location((hi_x - lo_x) / 2.0, (hi_y - lo_y) / 2.0), 0.0)
        self.web = float(web)
        self._shape = Outline.of(path, self._cutout_paths(holes))
        self._cutouts = Cutouts()           # an outline keeps its own
        self._cached_outline = None
        self._outline = self._shape.box
        self._chamfer = self._radius = 0.0
        self.width, self.height = self._outline.width, self._outline.height
        self._sized = True
        self._draw_outline = draw

    def edges(self, facing, within: float = 45.0) -> list:
        """The stretches of this board's edge whose outward side points
        within `within` degrees of `facing` (a bearing or an Edge), in the
        order the outline runs. A rectangle's north side is one; a rounded
        top is one; a rim gives the arc of it that faces that way; a notch
        in the top edge gives its floor as well, which is why this returns a
        list and a script says which it meant."""
        return self._shaped().runs(facing, within)

    def edge(self, facing, within: float = 45.0) -> Run:
        """The one stretch of the board's edge facing that way. Several (or
        none) is a script question, not a guess: narrow `within`, or take
        the one wanted from edges()."""
        runs = self.edges(facing, within)
        if len(runs) == 1:
            return runs[0]
        if not runs:
            raise ValueError("no part of this board's edge faces %r within %g degrees" % (facing, within))
        raise ValueError("%d stretches of this board's edge face %r within %g degrees (%s): "
                         "narrow within=, or pick from board.edges()"
                         % (len(runs), facing, within, ", ".join("%.2f mm" % r.length for r in runs)))

    def _shaped(self) -> Outline:
        """This board as an outline, whatever it was declared as: what runs
        are read off. A disc's rim is its polygon; a rectangle's four sides
        are its own."""
        if isinstance(self._shape, Outline):
            return self._shape
        if self._cached_outline is None:
            if isinstance(self._shape, Disc):
                holes = [list(_circle(self._shape.centre, self._shape.bore))] if self._shape.bore else []
                holes += [list(h) for h in self._shape.holes]
                self._cached_outline = Outline.of(list(self._shape.polygon()), holes)
            elif self._outline is not None:
                rect = rect_outline(self._outline, self._chamfer, self._radius)
                self._cached_outline = Outline.of(rect.paths[0], self._cutouts.paths)
            else:
                raise ValueError("the board has no size yet: board.size(), board.disc() or board.outline() says what it is")
        return self._cached_outline

    @property
    def centroid(self) -> Location:
        """Where the board's area balances, which is not the middle of its
        box unless it is symmetric."""
        return self._shaped().centroid

    @property
    def centre(self) -> Location:
        """The middle of the board: the centre of the box round it, which is
        what a mounting pattern and a ring are usually measured from.
        `board.centroid` is the area centre instead."""
        if self._outline is None:
            raise ValueError("the board has no size yet: board.size() or board.disc() says what it is")
        return self._outline.center

    @property
    def radius(self) -> float:
        """A round board's radius."""
        return self._disc("board.box, board.centre and board.edge(facing=) are what measures one").radius

    @property
    def bore(self) -> float:
        """A round board's bore radius; 0 when it is solid."""
        return self._disc("its cutouts are its holes=, which have no one radius").bore

    def _disc(self, instead: str = "") -> Disc:
        """This board as a disc, or a sentence saying what to use instead.
        A shaped board reaching here is a script using a round board's verb
        on one that is not round, so it is told the verb that does the same
        thing, never left with an attribute error from inside the placer."""
        if isinstance(self._shape, Disc):
            return self._shape
        tail = (": " + instead) if instead else ""
        if isinstance(self._shape, Outline):
            raise ValueError("this is a shaped board, not a round one%s" % tail)
        raise ValueError("this is not a round board: declare one with board.disc(diameter=...)%s"
                         % ((", or " + instead) if instead else ""))

    # ------------------------------------------------------------ blocks
    def block(self, anchor, satellites, gap: float | None = None) -> BlockSpec:
        """A part and the satellites that sit at its pins: `satellites` is a
        list of (Part, net) pairs, each placed on that pin's axis `gap` out,
        body outward of its pad; the default gap is the two courtyards
        touching. Place the returned block like a part; it is laid out from
        the anchor's real pads at every candidate."""
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
    def place(self, item, at=None, *, rotation: float | None = None, face: Face = Face.FRONT,
              radius: float | None = None, step: float | None = None, rotations=(),
              priority: Priority | None = None, required: bool = False, why: str = "",
              _standoff: float | None = None) -> PlaceIntent:
        """Declare where an item goes: `at=` a place, whose kind says how
        much freedom is left.

        Location(x, y)          the origin (a cell: its box centre)        -> FIXED, no freedom
        Centre(x, y)            the body box centre; each axis a number or
                                a reference                                -> FIXED, no freedom
        Location(x, None)       one axis pinned, the other free: the item
        Centre(None, y)         slides along the line, sharing it evenly  -> searched, one freedom
        Pin(key, x, y)          the item's own pad `key` (number or net)
                                lands on the point                        -> FIXED, no freedom
        OnEdge(edge, along=)    its reach at the keep-in, at that distance
                                (mm, a reference, Along.MID, Fraction(f))  -> EDGE, no freedom
        OnEdge(edge)            on that edge, wherever there is room:
                                midpoint alone, spread with its fellows,
                                aside from what is there                  -> searched, one freedom
        Near(location)          searched round a hint                     -> searched, two freedoms
        nothing                 seeded from its links                     -> searched, two freedoms

        `radius=`, `step=` and `rotations=` tune a search (seeded or Near).

        `required=True` says that failing to place this item stops the run,
        with the board as it stood and the biggest free rectangles on its
        face. It is independent of the rank and of whether the position is
        decided, and a required item is not negotiable even under
        `--keep-going`. Nothing else stops a run by itself.
        """
        radius = self.settings.place_radius if radius is None else radius
        step = self.settings.place_step if step is None else step
        geom, key, kind = self._item(item)
        if any(i.key == key for i in self._intents):
            raise ValueError("%s is already placed; one declaration per item" % key)
        center = edge = along = near = about = run = None
        rim = angle = radius_at = None
        outward = False
        overhang = 0.0
        pin_x = pin_y = None
        pinned = ""
        pin = None
        if at is None:
            pass
        elif isinstance(at, Pin):
            if kind != "part":
                raise TypeError("%s: a Pin places a part by its pad; a cell has no pad of its own" % key)
            geom.pad(at.key)                                # a real pad of this part, checked now
            pin, center, at = at.key, (at.x, at.y), None
        elif isinstance(at, OnEdge) and isinstance(at.edge, CutoutEdge):
            # a hole that is not settled yet: keep the promise and the named
            # `along`, and wait for the cutout the same way a position said
            # in terms of a pad waits for that pad
            run, along, overhang = at.edge, at.along, at.overhang
            outward = rotation is None
            at = None
        elif isinstance(at, OnEdge) and isinstance(at.edge, Run):
            run, along, overhang = at.edge, at.along, at.overhang
            if isinstance(along, (Along, Fraction)):
                along = along.fraction * run.length
            outward = rotation is None
            at = None
        elif isinstance(at, OnEdge):
            if isinstance(self._shape, Disc):
                raise ValueError("%s: a disc has no edges; place it on the rim at a bearing, OnRim(angle), "
                                 "or on a stretch of it from board.edge(facing=)" % key)
            if isinstance(self._shape, Outline):
                raise ValueError("%s: a shaped board's sides are chosen, not named: board.edge(facing=Edge.NORTH)" % key)
            edge, along, overhang = at.edge, at.along, at.overhang
            if isinstance(along, (Along, Fraction)):
                along = _EdgeFraction(along.fraction, along.value if isinstance(along, Along) else "centre")
            at = None
        elif isinstance(at, (OnRim, OnBore)):
            self._disc("the same place is OnEdge(board.edge(facing=...)), which holds the item "
                       "at the keep-in and turns it to the edge there")
            rim = "bore" if isinstance(at, OnBore) else "rim"
            angle = None if at.angle is None else bearing(at.angle)
            overhang = getattr(at, "overhang", 0.0)
            outward = rotation is None          # it faces out at whatever bearing it ends up on
            at = None
        elif isinstance(at, Polar):
            about = self.centre if at.about is None else _as_point(at.about)
            if at.radius is not None and at.angle is not None:
                center, at = polar_point(about, at.angle, at.radius), None
            else:
                radius_at, angle = at.radius, (None if at.angle is None else bearing(at.angle))
                at = None
        elif isinstance(at, Near):
            near = at.location
            radius = at.radius if at.radius is not None else radius
            step = at.step if at.step is not None else step
            rotations = at.rotations if at.rotations is not None else rotations
            at = None
        elif isinstance(at, (Location, Centre, tuple)):
            free = _free_axis(at)
            if free is not None:
                pinned = "center" if isinstance(at, Centre) else "at"
                xs = at.x if isinstance(at, (Location, Centre)) else at[0]
                ys = at.y if isinstance(at, (Location, Centre)) else at[1]
                if free == "y":
                    pin_x = xs
                else:
                    pin_y = ys
                at = None
            elif isinstance(at, Centre):
                center, at = (at.x, at.y), None
        else:
            raise TypeError("%s: at= takes a Location, a Centre, a Pin, an OnEdge, an OnRim, an OnBore, a Polar, a Near "
                            "or a point of references, not %r" % (key, at))
        source = "auto" if priority is None else "script"
        # Whether the declaration decides the position is a different question
        # from how important the item is. A decided position goes down before
        # anything searched and nothing may push it; a priority orders the
        # items that are still being searched a spot. FIXED and EDGE answer the
        # first question, so they hold exactly when the position is decided.
        decided = (at is not None or center is not None
                   or ((edge is not None or run is not None) and along is not None)
                   or (rim is not None and angle is not None))
        freedom = Freedom.SEARCHED if not decided else \
            Freedom.FIXED if (at is not None or center is not None) else Freedom.EDGE
        if decided and priority is not None:
            raise ValueError("%s: the declaration decided this position, so the item goes down before anything "
                             "searched and priority=%s has nothing to order; drop the priority, or drop the "
                             "position to have it searched" % (key, priority.value))
        priority = priority or Priority.DEFAULT
        faces_note = ""
        if rotation is None:
            if isinstance(run, CutoutEdge):
                rotation, faces_note = None, ""      # the stretch is not known yet: turned when it is
            elif run is not None and along is not None:
                rotation, faces_note = self.outward_rotation(item, run.at(along)[1])
            elif rim is not None and angle is not None:
                rotation, faces_note = self.outward_rotation(item, angle + (180.0 if rim == "bore" else 0.0))
            elif edge is not None and along is None:
                rotation, faces_note = self.outward_rotation(item, edge)
            else:
                rotation, faces_note = 0.0, ""
        if kind == "cell" and at is not None and center is None:
            center, at = at, None
        needs = {self._pad_ref(ref)[0] for ref in _refs_in([at, center, along, pin_x, pin_y, near])}   # a real pad, placed before this
        if isinstance(at, OnEdge) and isinstance(at.edge, CutoutEdge):
            needs.add(cutout_token(at.edge.name))   # the hole is cut before anything is put against it
        if isinstance(along, _RowSlot):
            needs |= along.row.needs
        standoff = _standoff if _standoff is not None else (-float(overhang) if overhang else self.keep_in)
        turn = None if rotation is None else float(rotation)   # None: settled when the stretch is known
        intent = PlaceIntent(key, geom, kind, priority, turn, face, at, center, edge, along,
                             standoff, near, radius, step, tuple(rotations), why, len(self._intents), frozenset(needs),
                             pin_x, pin_y, source, faces_note, pinned, pin, rim, angle, radius_at, outward, about, run,
                             freedom, required)
        self._intents.append(intent)
        return intent

    def row(self, items, edge: Edge, *, gap: float = 0.0, start=None, align: str = "start",
            rotation: float | None = None, line: str = "centre", behind: Row | None = None, inboard: float | None = None,
            overhang: float = 0.0,
            centre=None, end=None, before: Row | None = None, after: Row | None = None, why: str = "") -> Row:
        """Items down `edge` in order, `gap` apart (default: courtyards
        touching), with their outward sides
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
        if isinstance(edge, Run):
            return self._row_on_run(items, edge, gap=gap, start=start, align=align, rotation=rotation,
                                    overhang=overhang, why=why, unsupported=[
                                        ("line", line if line != "centre" else None), ("behind", behind),
                                        ("inboard", inboard), ("centre", centre), ("end", end),
                                        ("before", before), ("after", after)])
        if isinstance(self._shape, Disc):
            raise ValueError("a disc has no edges: board.ring(items, radius=) is the row of a round board, "
                             "or board.row(items, board.edge(facing=)) puts them along a stretch of the rim")
        if isinstance(self._shape, Outline):
            raise ValueError("a shaped board's sides are chosen, not named: "
                             "board.row(items, board.edge(facing=Edge.NORTH))")
        rots = [self.outward_rotation(it, edge)[0] for it in items] if rotation is None else \
            ([float(r) for r in rotation] if isinstance(rotation, (list, tuple)) else [float(rotation)] * len(items))
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
            claim, reach = self.claim(item, r), self.reach(item, r)      # spaced by what they claim, deep as they reach
            keys.append(key)
            alongs.append(claim.height if along_axis else claim.width)
            depths.append(reach.width if along_axis else reach.height)
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
            self.place(item, at=OnEdge(edge, along=along), _standoff=c, rotation=r, why=why)
        return row

    def ring(self, items, *, radius=None, start=Edge.NORTH, gap: float = 0.0, spread: bool = False,
             rotation=None, about=None, why: str = "") -> "Ring":
        """Items round a centre - the board's, or `about` another point - in
        order clockwise from the bearing `start`, each turned to face
        outward: their body centres `radius` from that centre, or with no
        radius (a round board only) their reach at the rim's keep-in. Spaced by what they claim across the arc, `gap` mm of arc
        between claims - two claims can only meet at a point round a
        circle, so a gap of nothing leaves their inner corners the rounding
        two courtyards may touch by; `spread=True` shares the whole turn evenly instead
        (four mounting holes at 90 degrees). `rotation=` (one value or one
        per item) overrides the outward turn. Returns the Ring."""
        centre = self.centre if about is None else _as_point(about)
        # only a ring at the rim needs a rim; with a radius any board can hold one
        disc = self._disc("give ring() a radius, or board.row(items, board.edge(facing=...)) "
                          "puts them along a stretch of the edge") if radius is None else None
        b0 = bearing(start)
        given = None
        if rotation is not None:
            given = [float(r) for r in rotation] if isinstance(rotation, (list, tuple)) else [float(rotation)] * len(items)
        n = max(len(items), 1)
        angles, rots, depths = [], [], []
        angle, half_prev = b0, 0.0
        for k, item in enumerate(items):
            if spread:
                angle = b0 + 360.0 * k / n
            # An item facing out has its own width across the arc and its own depth
            # along the radius: measured where outward is south, which the ring's
            # own symmetry allows. A rotation the script gave has no such relation
            # to the arc, so there the claim is projected onto the tangent.
            base = given[k] if given is not None else self.outward_rotation(item, Edge.SOUTH)[0]
            claim, reach = self.claim(item, base), self.reach(item, base)
            across = box_support(claim, angle + 90.0) if given is not None else claim.width
            stands = box_support(reach, angle) if given is not None else reach.height     # what the rim holds off
            thick = box_support(claim, angle) if given is not None else claim.height      # what a neighbour must clear
            arc_r = float(radius) if radius is not None else max(disc.radius - self.keep_in - stands / 2.0, 1e-6)
            # Round a circle items are held apart by their INNER corners: the
            # angle one takes is measured at the radius where it is narrowest,
            # and it is the claim, not the reach, that has to clear.
            half = math.degrees(math.atan2(across / 2.0, max(arc_r - thick / 2.0, 1e-6)))
            if not spread and k:
                angle += half_prev + math.degrees((gap + TOUCH) / arc_r) + half
            half_prev = half
            angles.append(angle)
            rots.append(given[k] if given is not None else self.outward_rotation(item, angle)[0])
            depths.append(thick)
        for item, a, r in zip(items, angles, rots):
            self.place(item, at=(OnRim(a) if radius is None else Polar(radius, a, about=centre)), rotation=r, why=why)
        return Ring(float(radius) if radius is not None else None, angles,
                    max(depths) if depths else 0.0, list(items), [self._item(it)[1] for it in items])

    def _row_on_run(self, items, run: Run, *, gap, start, align, rotation, overhang, why, unsupported) -> "RunRow":
        """Items along one stretch of a shaped board's edge, in order from
        its start, each turned to the way the board faces where it sits."""
        for name, value in unsupported:
            if value is not None:
                raise ValueError("a row along a run does not take %s= yet: it starts at start=, or align=\"center\", "
                                 "and every item's reach sits at the keep-in" % name)
        given = None
        if rotation is not None:
            given = [float(r) for r in rotation] if isinstance(rotation, (list, tuple)) else [float(rotation)] * len(items)
        claims = []
        for k, item in enumerate(items):
            base = given[k] if given is not None else self.outward_rotation(item, Edge.SOUTH)[0]
            claims.append(self.claim(item, base))

        standoff = -float(overhang) if overhang else self.keep_in

        def walk(s0):
            """Where each item's centre falls, walking the run from `s0`. A
            claim takes more of a bending run than of a straight one: the
            items sit inboard of the edge, where the same angle spans less
            of it, so the step is opened by how much the run bends under
            them. On a curve two claims can only meet at a point, so they
            are left the rounding two courtyards may touch by."""
            alongs, prev = [], None
            s = s0
            for claim in claims:
                bend = run.curvature(max(s, 0.0))
                inboard = standoff + claim.height          # the boundary to the claim's far corner
                half = (claim.width / 2.0) / max(1.0 - bend * inboard, 0.2)
                if prev is not None:
                    s += prev + gap + (TOUCH if abs(bend) > 1e-9 else 0.0) + half
                alongs.append(s)
                prev = half
            return alongs, prev
        first_half = claims[0].width / 2.0 if claims else 0.0
        alongs, last_half = walk(first_half)
        total = (alongs[-1] + last_half) - (alongs[0] - first_half) if alongs else 0.0
        if align == "center":
            s0 = max(0.0, (run.length - total) / 2.0) + first_half
        elif start is None:
            s0 = first_half
        elif isinstance(start, (int, float)):
            s0 = float(start) + first_half
        elif isinstance(start, (Along, Fraction)):
            s0 = start.fraction * run.length + first_half
        else:
            s0 = run.project(_as_point(start) if isinstance(start, (tuple, Location)) else start) + first_half
        alongs, _ = walk(s0)
        keys = []
        for k, (item, along) in enumerate(zip(items, alongs)):
            rot = given[k] if given is not None else self.outward_rotation(item, run.at(along)[1])[0]
            self.place(item, at=OnEdge(run, along=along), rotation=rot,
                       _standoff=(-float(overhang) if overhang else self.keep_in), why=why)
            keys.append(self._item(item)[1])
        return RunRow(run, alongs, max((c.height for c in claims), default=0.0), total, list(items), keys)

    def _is_searched(self, refdes: str) -> bool:
        fp = self.geometry.footprint(refdes)
        for i in self._placements():
            if not i.freedom.decided and (i.key == fp.inst or (i.kind == "cell" and fp.cell == i.key)):
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

    def _declared_link(self, pad_a: tuple, pad_b: tuple):
        """The link the script declared between these two pads, or None. A
        weight of DEFAULT is what an undeclared connection is worth, so the
        weight alone cannot say whether anybody asked for one."""
        for l in self._links:
            if {l.a, l.b} == {pad_a, pad_b}:
                return l
        return None

    def _link_weight(self, pad_a: tuple, pad_b: tuple) -> int:
        link = self._declared_link(pad_a, pad_b)
        return link.weight if link is not None else int(LinkWeight.DEFAULT)

    def _targets(self, item, occ: Occupancy, placed: set) -> list:
        """(own pad key, target location, weight) for every connection from
        this item's pads to a pad already placed, on a net that pulls.

        A plane's or a free net's connections do not pull: a net with two
        hundred pads gives a centroid that means nothing. A link the script
        DECLARED on such a net does pull, because it names two specific pads
        and the reason for the exclusion does not apply to it. A bypass
        capacitor shares nothing with its IC but the rail, so `board.link` is
        the only way to say they belong together - and it used to measure the
        distance, report it over its limit, and change nothing."""
        quiet = self._plane_nets() | self._free_nets
        fps = item.members if isinstance(item, CellGeom) else (item,)
        own_refs = {fp.ref for fp in fps}
        out = []
        for fp in fps:
            for p in fp.pads:
                if not p.net:
                    continue
                silent = p.net in quiet
                for other in self.geometry.pads_on_net(p.net):
                    if other.owner in own_refs or other.owner not in placed:
                        continue
                    link = self._declared_link((fp.ref, p.number), (other.owner, other.number))
                    if silent and link is None:
                        continue
                    w = link.weight if link is not None else int(LinkWeight.DEFAULT)
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
        """A copper declaration. WHEN it is planned is not asked here: it is
        derived in resolve(), once every placement is declared, because at
        declaration time a part placed later is invisible."""
        name = self.geometry.require_net(net)
        pads = tuple(self._pad_ref(r) for r in refs)
        ci = CopperIntent(key, name, priority, plan, tuple(refs), why, len(self._copper), bridge,
                          frozenset(owner for owner, *_ in pads))
        self._copper.append(ci)
        return ci

    def faces(self, *, outward: Edge | None = None, quiet: Edge | None = None, handoff: Edge | None = None, why: str = ""):
        """A module's sides, said once in its own script: `outward` is the
        side that faces the board edge (the connector mouth, the plungers),
        `quiet` the side to keep away from aggressors, `handoff` the side
        its signals leave from. Written into the fragment as a fact that
        rides with every stamped instance; a board turns the cell by it."""
        words = [k + "=" + Edge(v).value for k, v in (("outward", outward), ("quiet", quiet), ("handoff", handoff)) if v is not None]
        if not words:
            raise ValueError("faces() names at least one side")
        self._faces = ("placemat faces " + " ".join(words), why)

    def outward_rotation(self, item, edge) -> tuple[float, str]:
        """The rotation that turns the item's outward side to `edge` - a board
        edge, or a bearing on a round board's rim - and a note when the item
        declared none (the generic rule: local +Y out)."""
        geom, key, kind = self._item(item)
        declared = geom.faces.get("outward") if kind == "cell" else None
        note = "" if kind != "cell" else "no faces declared: turned as if its outward side were local +Y"
        if isinstance(edge, Edge):
            if not declared:
                return _OUTWARD_ROTATION[edge], note
            return _rotation_taking(Edge(declared), edge), ""
        # A bearing: turning by r takes a side pointing along bearing b to b - r,
        # so the rotation is the side's own bearing less the one wanted.
        local = _EDGE_BEARING[Edge(declared)] if declared else _EDGE_BEARING[Edge.SOUTH]
        return (local - bearing(edge)) % 360.0, "" if declared else note

    def label(self, item, text: str, *, side: Edge = Edge.NORTH, gap: float | None = None, align: str = "centre",
              size: float | None = None, thickness: float | None = None, knockout: bool = False,
              rotation: float = 0.0,
              reserve: bool = True, line=None, why: str = ""):
        """Silkscreen text that marks a user-facing feature: a connector,
        jumper, switch or LED. It sits `gap` off `side` of the item's reach
        (a Part or Cell) or of one pad (a PadRef/CellPadRef), on the item's
        own face, aligned `"centre"`, `"start"` (west or north end) or
        `"end"` along that side; `rotation=90` runs it up the page;
        a list of items with a list of texts is one label each, all on
        one line: `gap` off `side` of the deepest of them, each aligned
        on its own item, so the labels of a row read as a row; `line=`
        names the item (a Part or Cell) whose reach that line stands off
        instead, so pin labels sit over their pads but clear of the part;
        `knockout` cuts it out of a filled box. The label is worked out the
        moment its item is placed and, unless `reserve=False`, the text's
        own box on its face is reserved, so nothing placed later lands on
        it."""
        gap = self.settings.label_gap if gap is None else gap
        size = self.settings.label_size if size is None else size
        thickness = self.settings.label_thickness if thickness is None else thickness
        if align not in ("centre", "start", "end"):
            raise ValueError("a label aligns centre, start or end, not %r" % (align,))
        if rotation not in (0, 90):
            raise ValueError("a label reads across (0) or up the page (90), not %r" % (rotation,))
        if isinstance(item, (list, tuple)):
            items, texts = list(item), list(text) if isinstance(text, (list, tuple)) else [text]
            if len(texts) != len(items):
                raise ValueError("labels for %d items need %d texts, not %d" % (len(items), len(items), len(texts)))
            group = tuple(items)
        else:
            items, texts, group = [item], [text], None
        if line is not None:
            self._item(line)                                    # a real part or cell, checked now
            group = (line,)
        keys = []
        for one, txt in zip(items, texts):
            if isinstance(one, (PadRef, CellPadRef)):
                self._pad_ref(one)                             # a real pad, checked now
                key = "label %s %s" % (self._pad_ref(one)[0], txt)
            else:
                key = "label %s %s" % (self._item(one)[1], txt)
            self._labels.append((key, one, txt, Edge(side), float(gap), align, float(size), float(thickness),
                                 bool(knockout), float(rotation), why, bool(reserve), group))
            keys.append(key)
        return keys[0] if group is None else keys

    def _width(self, net: str, width) -> float:
        return float(width) if width is not None else self.geometry.netclass(net).track_width

    def track(self, net, points, *, layer: CopperLayer, width: float | None = None,
              chamfer: float | None = None,
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
        chamfer = self.settings.copper_chamfer if chamfer is None else chamfer
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
             chamfer: float | None = None, via_step: float | None = None, priority: Priority = Priority.DEFAULT,
             bridge: bool = False, why: str = ""):
        """Two nets drawn together at `gap` along one centreline. `path`
        starts and ends with a (P pad, N pad) tuple; the points between are
        the centreline. Width and gap default to the P net's class. Corners
        are chamfered at 45, each track leaves its pad at 45, and a lead that
        would touch the partner goes over the other face from a via."""
        chamfer = self.settings.copper_pair_chamfer if chamfer is None else chamfer
        via_step = self.settings.copper_pair_via_step if via_step is None else via_step
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
        """A via of `net`. `at` is a position, or a `FreeSpot` near a pad:
        the nearest point a via can stand and be reached, found when the pad
        is placed. A FreeSpot with nowhere to go is a finding and draws none."""
        name = self.geometry.require_net(net)
        refs = _refs_in([at])
        d, s = drill or self.via_drill, size or self.via_size

        def plan(ctx):
            if isinstance(at, FreeSpot):
                where = self._free_spot(ctx, at, name, d, s)
                if where is None:
                    return []
            else:
                where = ctx.locate(at)
            via = Via(name, where, d, s)
            ctx.planned_vias.append(via)        # a later FreeSpot in this batch sees it
            return [via]
        return self._copper_intent("via %s" % name, net, priority, plan, refs, why)

    def _free_spot(self, ctx, spot, net: str, drill: float, size: float):
        """Run the search from the pad against the board as it stands: placed
        pads and planned copper through the occupancy, the vias planned so far,
        drilled holes, keepouts and the edge."""
        from . import queries
        occ = ctx.occ
        owner, number, _, _ = self._pad_ref(spot.near)
        start = ctx.locate(spot.near)
        placed = occ.items[owner].shapes if owner in occ.items else ()
        own = [sh for sh in placed if sh.label == number and sh.kind in ("pad", "through")]
        layer = CopperLayer.of(spot.layer) if spot.layer is not None else (
            sorted((l for sh in own for l in sh.layers), key=stackup_order) or [CopperLayer.F])[0]
        nc = self.geometry.netclasses.get(net)
        width = nc.track_width if nc else 0.2
        every = frozenset(self.geometry.layers)
        holes = [(occ.pad_location(fp.ref, p.number), p.drill_mm)
                 for fp in self.geometry.footprints for p in fp.pads if p.through and p.drill_mm]
        forbidding = [(k.poly, k.layers) for k in (ctx.plan.keepouts.values() if ctx.plan else ())
                      if "vias" in k.excludes]
        forbidding += [(poly, ra.layers) for pairs in occ._cell_rule_areas.values() for ra, poly in pairs
                       if "vias" in ra.excludes]
        forbidding += [(ra.polygon, ra.layers) for ra in self.geometry.rule_areas
                       if ra.cell is None and "vias" in ra.excludes]

        def judge(c):
            ring = circle_polygon(c, size / 2.0)
            box = Box.of_points(ring)
            if not spot.in_pad and any(polys_overlap(ring, sh.poly) for sh in own):
                return "in the source pad", ()
            if occ.board_shape is not None:
                if occ.board_shape.why_not(box, self.keep_in):
                    return "off the board, or within %.2f mm of the board edge" % self.keep_in, ()
            elif occ.board_box is not None and not occ.board_box.inflate(-self.keep_in).contains(box):
                return "within %.2f mm of the board edge" % self.keep_in, ()
            hits = occ.copper_conflicts(Shape("via", "copper", frozenset(), every, net, ring, box))
            if hits:
                return "copper " + hits[0], ()
            for v in ctx.planned_vias:
                gap = c.distance(v.at) - (drill + v.drill) / 2.0
                if gap < self.geometry.hole_to_hole - 1e-9:
                    return "hole %.2f mm from the %s via's hole" % (max(gap, 0.0), v.net), ()
                if v.net != net:
                    clr = self.geometry.clearance(net, v.net)
                    if c.distance(v.at) - (size + v.size) / 2.0 < clr - 1e-9:
                        return "copper %.2f mm from the %s via" % (c.distance(v.at) - (size + v.size) / 2.0, v.net), ()
            for at, dia in holes:
                gap = c.distance(at) - (drill + dia) / 2.0
                if gap < self.geometry.hole_to_hole - 1e-9:
                    return "hole %.2f mm from a pad's hole" % max(gap, 0.0), ()
            for poly, layers in forbidding:
                if polys_overlap(ring, poly):
                    return "inside a keepout, which forbids vias", ()
            if c.distance(start) > 1e-9:
                tail = queries._segment(start, c, width)
                tail_hits = occ.copper_conflicts(Shape("via", "copper", frozenset(), frozenset([layer]),
                                                       net, tail, Box.of_points(tail)))
                if tail_hits:
                    return "tail " + tail_hits[0], ()
            return None, ()

        found, tally, tried = queries.free_spot(start, judge, spot.radius, spot.step)
        if found is None:
            ctx.notes.append("via %s: nowhere within %.2f mm of %s.%s, %d spot(s) tried: %s" % (
                net, spot.radius, owner, number, tried,
                ", ".join("%s x%d" % kv for kv in tally.most_common())))
            return None
        return found.at

    def pour(self, net, points, *, layer: CopperLayer, stroke: float | None = None, swallow_pads: bool = False,
             priority: Priority = Priority.DEFAULT, why: str = ""):
        """A filled copper polygon of exactly this shape on one layer. It does
        not pull back from foreign copper; `swallow_pads` grows it over the
        same-net pads its outline touches."""
        stroke = self.settings.copper_pour_stroke if stroke is None else stroke
        layer = CopperLayer.of(layer)
        name = self.geometry.require_net(net)
        refs = _refs_in(points)

        def plan(ctx):
            pts = tuple((l.x, l.y) for l in (ctx.locate(p) for p in points))
            return [Pour(name, layer, pts, stroke, swallow_pads)]
        return self._copper_intent("pour %s" % name, net, priority, plan, refs, why)

    def plane(self, net, layers, *, outline=None, inset: float | None = None, chamfer: float | None = None,
              clearance: float | None = None, min_thickness: float | None = None, solid_pads: bool = True,
              priority: Priority = Priority.DEFAULT, why: str = ""):
        """A KiCad zone per layer, filled by KiCad and pulled back round every
        foreign pad, track and via: the whole board inset from the edge, or
        the polygon `outline`."""
        inset = self.settings.copper_plane_inset if inset is None else inset
        clearance = self.settings.copper_plane_clearance if clearance is None else clearance
        min_thickness = self.settings.copper_plane_min_thickness if min_thickness is None else min_thickness
        name = self.geometry.require_net(net)
        layers = tuple(dict.fromkeys(CopperLayer.of(l) for l in layers))

        def plan(ctx):
            if outline is not None:
                pts = tuple((l.x, l.y) for l in (ctx.locate(p) for p in outline))
            elif self._shape is not None:
                pts = self._shape.polygon(inset)
            else:
                ch = self._chamfer if chamfer is None else chamfer
                pts = board_zone_outline(self.width, self.height, inset, ch)
            return [Zone(name, l, pts, clearance, min_thickness, solid_pads) for l in layers]
        refs = [] if outline is None else _refs_in(outline)
        return self._copper_intent("plane %s" % name, net, priority, plan, refs, why)

    def finger(self, net, *, layer: CopperLayer, from_, to, width: float,
               bridge_width: float | None = None, priority: Priority = Priority.DEFAULT, why: str = ""):
        """A finger: a rectangular pour of `width` along the centreline from
        `from_` to `to` (points, pads, or (x, y) pairs with X()/Y()), cut
        either side of every same-layer track of another net it crosses and
        bridged under each on the opposite face so the pieces stay one net.
        Fingers always yield to tracks."""
        bridge_width = self.settings.copper_finger_bridge_width if bridge_width is None else bridge_width
        layer = CopperLayer.of(layer)
        name = self.geometry.require_net(net)
        refs = _refs_in([from_, to])

        def plan(ctx):
            a, b = ctx.locate(from_), ctx.locate(to)
            segs = [((t.start.x, t.start.y), (t.end.x, t.end.y)) for t in ctx.tracks_on(layer) if t.net != name]
            return finger_ops(name, layer, a, b, width, segs, self.via_drill, self.via_size, bridge_width,
                              self.settings.copper_bridge_half)
        return self._copper_intent("finger %s" % name, net, priority, plan, refs, why)

    # ------------------------------------------------------------ resolution
    def _derive_copper_freedom(self):
        """Copper whose every endpoint belongs to something nothing will move
        is planned before the search and becomes an obstacle to it; copper
        naming a searched part waits for it.

        Derived here, once every declaration is in. Copper with no endpoints
        at all - plain coordinates - is decided by definition, so
        `board.via(net, Location(x, y))` reserves its spot with nothing to
        remember."""
        searched = set()
        for i in self._placements():
            if i.freedom.decided:
                continue
            if i.kind == "cell":
                fps = list(i.item.members)
            elif i.kind == "block":
                fps = [i.item.anchor] + [fp for fp, _ in i.item.satellites]
            else:
                fps = [i.item]
            searched |= {fp.ref for fp in fps}
        for c in self._copper:
            c.freedom = Freedom.SEARCHED if (c.owners & searched) else Freedom.FIXED

    def resolve(self, progress=None) -> Plan:
        occ = Occupancy(self.geometry, self.edge_margin, board_box=self._outline, board_shape=self._shape,
                        board_cutouts=self._cutouts, settings=self.settings)
        for intent in self._placements():
            declared = [intent.item.anchor] + [fp for fp, _ in intent.item.satellites] if intent.kind == "block" else [intent.item]
            for item in declared:
                occ.pending |= occ._geometry(item).owners
        plan = Plan(self.geometry, occ, outline=self._outline, chamfer=self._chamfer, radius=self._radius,
                    shape=self._shape, cutouts=self._cutouts,
                    rules=list(self._rules), draw_outline=self._draw_outline)
        ctx = _CopperContext(self, occ)
        ctx.plan = plan
        self._report_lost_layers(plan)
        self._rank(occ)
        self._derive_copper_freedom()
        placements = sorted(self._intents, key=lambda i: i.rank)   # holes included: they are placed too
        fixed_copper = [c for c in self._copper if c.freedom.decided]
        other_copper = [c for c in self._copper if not c.freedom.decided]
        placed: set = set()
        self._place_labels(occ, plan, placed, progress)        # labels on parts the script never moves
        self._check_settled_cutouts(occ, plan)                 # holes whose place was already absolute

        def settle_cutout(intent):
            """A hole takes its place like an item does, from whatever its
            at= refers to. Everything placed after it sees the board with
            the hole in it."""
            c = intent.cutout
            if self._cutout_free(c):
                try:
                    centre, turn = self._slide_cutout(occ, c)
                    why = None
                except ValueError as e:
                    centre, turn, why = self.centre, 0.0, str(e)
            else:
                centre = self._cutout_centre(occ, c)
                turn = float(c.rotation) if c.rotation is not None else self._implied_rotation(c, centre)
                why = self._cutout_illegal(occ, c.shape.path_at(centre, turn), c.name)
            path = c.shape.path_at(centre, turn)
            step = Step(intent.key, "cutout", None, why=intent.why)
            if why:
                plan.findings.append("%s (cutout): %s" % (c.name, why))
                step.note = why
            else:
                self._add_cutout(occ, c.name, PlacedCutout(c.name, tuple(path), centre, turn))
                plan.shape, plan.cutouts = self._shape, self._cutouts   # the fab gets the holes too
                plan.cutouts_placed[c.name] = self._settled_cutouts[c.name]
                step.note = "cut at %.2f, %.2f facing %.0f" % (centre.x, centre.y, turn)
            plan.steps.append(step)
            placed.add(cutout_token(c.name))

        def settle_keepout(intent):
            """A region takes its place like a hole does, then forbids."""
            k = intent.keepout
            if self._cutout_free(k):
                try:
                    centre, turn = self._slide_cutout(
                        occ, k, illegal=lambda path: self._keepout_unusable(path))
                    why = None
                except ValueError as e:
                    centre, turn, why = self.centre, 0.0, str(e)
            else:
                centre = self._cutout_centre(occ, k)
                turn = float(k.rotation) if k.rotation is not None else self._implied_rotation(k, centre)
                why = None
            step = Step(intent.key, "keepout", None, why=intent.why)
            if why:
                plan.findings.append("%s (keepout): %s" % (k.name, why))
                step.note = why
            else:
                path = k.shape.path_at(centre, turn)
                outside, total = self._points_off_board(path)
                if outside == total:
                    raise ValueError(
                        "keepout %r is wholly off the board, so it forbids nothing: all %d of its "
                        "points are outside the outline. Move it, or remove the declaration."
                        % (k.name, total))
                poly = Cutouts([path]).loops[0]
                nets = frozenset(self.geometry.require_net(a) for a in k.allow if isinstance(a, Net))
                owners = frozenset(self._pad_ref(a)[0] for a in k.allow if isinstance(a, (Part, Cell)))
                if "parts" in k.excludes:
                    occ.reserve(poly, "keepout %r (%s)" % (k.name, k.why), allow=nets, owners=owners)
                plan.keepouts[k.name] = PlacedKeepout(k.name, poly, centre, turn, k.excludes,
                                                      k.layers, nets, owners, k.why)
                step.note = "kept clear at %.2f, %.2f" % (centre.x, centre.y)
                if outside:
                    step.note += "; %d of its %d points are off the board" % (outside, total)
            plan.steps.append(step)
            placed.add(cutout_token(k.name))

        def place_one(obj, why_now=""):
            if isinstance(obj, KeepoutIntent):
                settle_keepout(obj)
                return
            if isinstance(obj, CutoutIntent):
                settle_cutout(obj)
                return
            if isinstance(obj.run, CutoutEdge):     # the hole is down by now: read its real stretch
                obj.run = self.cutout(obj.run.name).edge(side=obj.run.side, within=obj.run.within)
                if isinstance(obj.along, (Along, Fraction)):
                    obj.along = obj.along.fraction * obj.run.length
                if obj.rotation is None:            # turned to the way the board faces where it sits
                    obj.rotation, obj.faces_note = self.outward_rotation(
                        obj.item, obj.run.at(obj.along if obj.along is not None else 0.0)[1])
            plan._items[obj.key] = obj.item
            step = self._settle(occ, obj, plan, placed)
            if why_now:
                step.note = (why_now + "; " + step.note) if step.note else why_now
            if not obj.freedom.decided:
                tag = self._rank_note.get(obj.key, "")
                if obj.priority_source == "script":
                    tag += " (script: %s)" % obj.priority.value
                if obj.required:
                    tag += ", required"
                step.note = (tag + "; " + step.note) if step.note else tag
            elif getattr(obj, "required", False):
                step.note = ("required; " + step.note) if step.note else "required"
            if obj.faces_note:
                step.note = (step.note + "; " if step.note else "") + obj.faces_note
            plan.steps.append(step)
            if step.placement is None and getattr(obj, "required", False) and not self.keep_going:
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
            self._place_labels(occ, plan, placed, progress)

        def place_ranked(lo, hi):
            """FIXED and EDGE go down in declaration order: nothing yields to
            them, so their order changes nothing. Searched items are ordered
            by the placer, one choice at a time, re-measured after each."""
            firm = [obj for obj in placements if lo <= obj.rank[0] <= hi and obj.freedom.decided]
            while firm:                     # declaration order, except that a position said in terms of a pad waits for it
                ready = [obj for obj in firm if obj.needs <= placed]
                if not ready:
                    raise ValueError("%s is placed relative to %s, which is not placed by then (only FIXED and EDGE "
                                     "items may be referred to)" % (firm[0].key, ", ".join(sorted(firm[0].needs - placed))))
                place_one(ready[0])
                firm.remove(ready[0])
            collisions = [f for f in plan.findings
                          if f.split(" ")[1] in ("(fixed):", "(edge):", "(cutout):", "(keepout):")]
            required_keys = {o.key for o in placements if getattr(o, "required", False)}
            demanded = [c for c in collisions if c.split(" ")[0] in required_keys]
            if demanded or (collisions and not self.keep_going):
                raise PlacementCollision(demanded or collisions)
            pending = [obj for obj in placements if lo <= obj.rank[0] <= hi and not obj.freedom.decided]
            for hole in [o for o in pending if isinstance(o, (CutoutIntent, KeepoutIntent))]:
                pending.remove(hole)        # holes first: every part after one sees the board it left
                place_one(hole)
            while pending:
                obj, why_now = self._next_to_place(pending, occ, placed)
                pending.remove(obj)
                place_one(obj, why_now)

        place_ranked(RANK_FIXED, RANK_EDGE)
        self._check_web(plan)
        self._plan_copper(occ, ctx, fixed_copper, plan, progress)
        # Every searched item is one queue, whatever kind it is: a connector can
        # be the most important thing on a board, and it does not wait behind a
        # tier of cells for being a single part. What it needs decides.
        place_ranked(RANK_CELL, RANK_LOOSE)
        self._plan_copper(occ, ctx, other_copper, plan, progress)
        self._check_keepouts(plan)
        self._report_links(occ, plan, placed)
        self._place_labels(occ, plan, placed, progress, final=True)
        if self._faces is not None:
            text, why = self._faces
            drawn = [fp.courtyard_box for fp in self.geometry.footprints] + [c.box for c in self.geometry.copper] + \
                    [op.box for op in plan.copper if hasattr(op, "box")]
            box = Box.union(drawn)                                                       # below everything the module draws
            plan.copper.append(Text(text, Location(box.left, box.bottom + 1.0), Face.FRONT, 0.5, 0.1, 0.0, "left", "top",
                                    layer="User.Comments"))
            plan.steps.append(Step("faces", "copper", Priority.DEFAULT, None, 0.0, text[len("placemat faces "):], why, 1))
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
                    return Step(i.key, i.kind, None if i.freedom.decided else i.priority, result.chosen, 0.0, note, i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)
                tried.append(pocket)
        current = occ._geometry(i.item).reference
        plan.findings.append("%s: no pocket fits its %s envelope on the %s face (%d pocket(s) tried)" % (
            i.key, "%.1f x %.1f" % (occ.body_box(i.item, Placement(Location(0, 0), i.rotation, i.face)).width,
                                    occ.body_box(i.item, Placement(Location(0, 0), i.rotation, i.face)).height),
            i.face.value, len(tried)))
        return Step(i.key, i.kind, None if i.freedom.decided else i.priority, None, 0.0, "UNPLACED: no pocket fits", i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)

    def _placements(self) -> list:
        """The item placements among the intents.

        Regions - cutouts, keepouts - share the queue with them, because
        they are ordered by the same `needs`, but they are not items: they
        have no footprint, no rotation and no bearing of their own. Anything
        reading what an item declared - which fellows share its edge, its
        ring or its axis - asks for this, never for `_intents`. The test is
        positive so that the next region type cannot fall through it."""
        return [i for i in self._intents if isinstance(i, PlaceIntent)]

    def _declared_refs(self) -> set:
        """Every refdes a placement declaration covers."""
        out = set()
        for i in self._placements():
            parts = [i.item.anchor] + [fp for fp, _ in i.item.satellites] if i.kind == "block" else \
                (list(i.item.members) if i.kind == "cell" else [i.item])
            out |= {fp.ref for fp in parts}
        return out

    def _label_refs(self, item) -> list:
        if isinstance(item, (PadRef, CellPadRef)):
            return [self._pad_ref(item)[0]]
        geom, ikey, kind = self._item(item)
        return [fp.ref for fp in (geom.members if kind == "cell" else (geom,))]

    def _place_labels(self, occ, plan: Plan, placed: set, progress, final: bool = False):
        """Every label whose item is down and not yet labelled: its text op,
        its reservation, and a finding when it sits on something already
        placed. Called after each placement and once more at the end, when
        an item that was declared but found no place is an error."""
        declared = self._declared_refs()
        done = plan.__dict__.setdefault("_labelled", {})
        if final:                       # what landed on a label after it was worked out
            for key, (op, own, face) in done.items():
                hits = sorted({occ.who(r) for r, g in occ.items.items()
                               if g.reference.face is face and r not in occ.pending and (g.reach or g.body).overlaps(op.box)} - own)
                for h in hits:
                    if not any(f.startswith("%s: sits on" % key) and h in f for f in plan.findings):
                        plan.findings.append("%s: sits on %s" % (key, h))
        def box_of(item):
            refs = self._label_refs(item)
            if isinstance(item, (PadRef, CellPadRef)):
                owner, number, _, _ = self._pad_ref(item)
                g = occ.items[owner]
                return (Box.union([s.box for s in g.shapes if s.kind in ("pad", "through") and s.label == number]),
                        g.reference.face)
            return Box.union([occ.items[r].reach or occ.items[r].body for r in refs]), occ.items[refs[0]].reference.face
        for entry in self._labels:
            key, item, text, side, gap, align, size, thick, knockout, rotation, why, reserve, group = entry
            if key in done:
                continue
            refs = self._label_refs(item)
            group_refs = [r for one in (group or ()) for r in self._label_refs(one)]
            waiting = [r for r in refs + group_refs if r in declared and r not in placed]
            if waiting:
                if final:
                    raise ValueError("%s: %s was declared but found no place" % (key, waiting[0]))
                continue
            box, face = box_of(item)
            line = Box.union([box_of(one)[0] for one in group]) if group else None
            op = _label_op(text, box, face, side, gap, align, size, thick, knockout, rotation, line)
            plan.copper.append(op)
            own = {occ.who(r) for r in refs}
            hits = sorted({occ.who(r) for r, g in occ.items.items()
                           if g.reference.face is face and r not in occ.pending and (g.reach or g.body).overlaps(op.box)} - own)
            note = "%s of %s" % (side.name.lower(), key.split(" ", 2)[1])
            if hits:
                plan.findings.append("%s: sits on %s" % (key, ", ".join(hits)))
                note += "; sits on " + ", ".join(hits)
            if reserve:
                occ.reserve(op.box, "label %s" % key.split(" ", 1)[1], layer=face.copper)     # the text's own box, no more
                note += "; reserved"
            plan.steps.append(Step(key, "copper", Priority.DEFAULT, None, 0.0, note, why, 1))
            done[key] = (op, own, face)
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
        ops, notes, findings = resolve_bridges(entries, ctx.fixed_tracks, self.via_drill, self.via_size,
                                               self.settings.copper_bridge_half)
        plan.findings += findings + ctx.notes
        ctx.notes = []
        ctx.planned_tracks += [op for op in ops if isinstance(op, Track)]
        for c in deferred:
            for op in c.plan(ctx):
                others.append((c, op))
        by_key = {}
        for c, _ in tracks:
            by_key.setdefault(c.key, [c.priority, 0, c.why, c.freedom])
        for c, _ in others:
            by_key.setdefault(c.key, [c.priority, 0, c.why, c.freedom])
        n_by_net = {}
        for op in ops:
            n_by_net[op.net] = n_by_net.get(op.net, 0) + 1
        for c, _ in tracks:
            by_key[c.key][1] = n_by_net.get(c.net, 0)
        all_ops = list(ops)
        for c, op in others:
            by_key.setdefault(c.key, [c.priority, 0, c.why, c.freedom])
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
        if any(c.freedom.decided for c in intents):
            ctx.fixed_tracks += [op for op in ops]
        for key, (prio, n, why, freedom) in by_key.items():
            step = Step(key, "copper", prio, None, 0.0, "%d op(s)" % n, why, n, freedom=freedom)
            plan.steps.append(step)
            if progress:
                progress(_fmt(step))
        for note in notes:
            plan.steps.append(Step("bridge", "copper", Priority.DEFAULT, None, 0.0, note, "", 0))
            if progress:
                progress("   bridge: " + note)

    def _rank(self, occ: Occupancy):
        """Every searched item's place in the queue, from what it is: the
        courtyard area it needs and its pin count, both against the rest of
        this board's searched items.

        Static. A rank says what a part IS, so it does not move as the board
        fills; what the board looks like when an item is reached is the
        tie-break's business, not this one's."""
        from .ranking import pin_count, rank_scores
        self._rank_score, self._rank_of, self._rank_note = {}, {}, {}
        searched = [i for i in self._placements() if not i.freedom.decided]
        if not searched:
            return

        def measure(i):
            if i.kind == "cell":
                parts, area = list(i.item.members), i.item.courtyard_box.area
            elif i.kind == "block":
                parts = [i.item.anchor] + [fp for fp, _ in i.item.satellites]
                area = sum(fp.courtyard_box.area for fp in parts)
            else:
                parts, area = [i.item], i.item.courtyard_box.area
            return area, sum(pin_count(fp) for fp in parts)

        m = {i.key: measure(i) for i in searched}
        scores = rank_scores(m, self.settings.rank_area, self.settings.rank_pins)
        order = sorted(scores, key=lambda k: (-scores[k], k))
        n = len(order)
        by_area = sorted(m, key=lambda k: -m[k][0])
        by_pins = sorted(m, key=lambda k: -m[k][1])
        for position, key in enumerate(order, start=1):
            area, pins = m[key]
            self._rank_score[key] = scores[key]
            self._rank_of[key] = position
            self._rank_note[key] = "rank %d/%d (%.1f mm2, %s of %d; %d pins, %s)" % (
                position, n, area, _ordinal(by_area.index(key) + 1), n,
                pins, _ordinal(by_pins.index(key) + 1))

    def _slide(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, ideal: float, lo: float, hi: float,
               placement_at, what: str, step: float | None = None, units: str = "mm") -> Step:
        """One degree of freedom: from `ideal` outward along [lo, hi], the
        first legal placement `placement_at(along)` gives. Round a rim or a
        ring the freedom is a bearing, so `step` and `units` are in degrees."""
        geom = occ._geometry(i.item)
        others = occ.obstacles(geom, occ.board_box.inflate(2.0))
        step = step if step is not None else max(i.step, 0.2)
        n = int((hi - lo) / step) + 1
        candidates = sorted({min(max(ideal + d * step * sgn, lo), hi) for d in range(n) for sgn in (1, -1)},
                            key=lambda a: (abs(a - ideal), a))
        rejected: Counter = Counter()
        reasons: dict = {}
        for along in candidates:
            p = placement_at(along)
            why = occ.legal(i.item, p, clr, others=others,
                            past_edge=(i.edge is not None or i.run is not None or i.rim == "rim")
                            and i.clearance < self.keep_in)
            if why is None:
                moved = abs(along - ideal)
                note = what
                if moved > 1e-9:
                    note += "; slid %.2f %s from its slot: %s" % (moved, units, next(iter(reasons.values()), ""))
                return Step(i.key, i.kind, None if i.freedom.decided else i.priority, p, moved, note, i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)
            key = _reason_key(why)
            rejected[key] += 1
            reasons.setdefault(key, why)
        plan.findings.append("%s: no room anywhere %s (%s)" % (
            i.key, what, ", ".join("%s x%d" % kv for kv in rejected.most_common(3))))
        return Step(i.key, i.kind, None if i.freedom.decided else i.priority, None, 0.0, "UNPLACED: " + "; ".join(reasons.values()), i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)

    def _settle_along_line(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """x or y pinned, the other free: the item's body centre sits on the
        pinned line, shares it evenly with the items pinned to the same
        value, and slides along it to the nearest legal spot."""
        axis = "x" if i.pin_x is not None else "y"
        pinned = _coord(self, occ, i.pin_x if axis == "x" else i.pin_y, axis)
        fellows = [o for o in self._placements() if (o.pin_x if axis == "x" else o.pin_y) is not None
                   and (o.pin_x if axis == "x" else o.pin_y) == (i.pin_x if axis == "x" else i.pin_y)]
        k, n = fellows.index(i), len(fellows)
        box = occ.board_box
        lo, hi = (box.top, box.bottom) if axis == "x" else (box.left, box.right)
        lo, hi = lo + self.keep_in, hi - self.keep_in
        ideal = lo + (hi - lo) * (k + 1) / (n + 1)

        def at(along):
            point = Location(pinned, along) if axis == "x" else Location(along, pinned)
            if i.pinned_by == "at" and i.kind != "cell":
                return Placement(point, i.rotation, i.face)
            return box_centered_placement(occ, i.item, point, i.rotation, i.face)
        return self._slide(occ, i, plan, clr, ideal, lo, hi, at, "on the line %s = %.2f" % (axis, pinned))

    def _edge_fraction(self, edge: Edge, occ: Occupancy, fraction: float) -> float:
        """A distance along `edge` as a fraction of its usable length,
        keep-in to keep-in."""
        box = occ.board_box
        lo, hi = (box.left, box.right) if edge in (Edge.NORTH, Edge.SOUTH) else (box.top, box.bottom)
        lo, hi = lo + self.keep_in, hi - self.keep_in
        return lo + (hi - lo) * fraction

    def _edge_slot(self, i: PlaceIntent, occ: Occupancy) -> float:
        """Where a free edge item would like to be: the edge's free items
        share it evenly, the k-th of n at (k + 1) / (n + 1) of the usable
        length, so one alone sits at the midpoint."""
        fellows = [x for x in self._placements() if x.edge is i.edge and x.along is None
                   and not x.freedom.decided]
        k, n = fellows.index(i), len(fellows)
        box = occ.board_box
        lo, hi = (box.left, box.right) if i.edge in (Edge.NORTH, Edge.SOUTH) else (box.top, box.bottom)
        lo, hi = lo + self.keep_in, hi - self.keep_in
        return lo + (hi - lo) * (k + 1) / (n + 1)

    def _settle_along_edge(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides along its edge from its
        slot to the nearest legal spot, its reach at the board's keep-in."""
        ideal = self._edge_slot(i, occ)
        box = occ.board_box
        lo, hi = (box.left, box.right) if i.edge in (Edge.NORTH, Edge.SOUTH) else (box.top, box.bottom)
        return self._slide(occ, i, plan, clr, ideal, lo, hi,
                           lambda along: edge_placement(occ, i.item, i.edge, along, i.rotation, i.clearance, i.face),
                           "along the %s edge" % i.edge.name.lower())

    def _settle_along_run(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides along its run from its
        slot, its reach at the keep-in, turned to the way the board faces
        wherever it lands."""
        run = i.run
        fellows = [x for x in self._placements() if x.run is i.run and x.along is None
                   and not x.freedom.decided]
        k, n = fellows.index(i), max(len(fellows), 1)
        ideal = run.length * (k + 1) / (n + 1)
        shape = occ.board_shape or self._shaped()

        def at(along):
            rot = self.outward_rotation(i.item, run.at(along)[1])[0] if i.outward else i.rotation
            return run_placement(occ, i.item, shape, run, along, i.clearance, rot, i.face)
        return self._slide(occ, i, plan, clr, ideal, 0.0, run.length, at,
                           "along the run facing %.0f degrees" % run.facing)

    def _round_slot(self, i: PlaceIntent) -> float:
        """Where a free item on a rim or a ring would like to be: everything
        sharing that circle divides the turn evenly, the k-th of n at k/n of
        it from the top, so one alone sits at the top."""
        fellows = [x for x in self._placements() if x.angle is None
                   and (x.rim, x.radius_at, x.about) == (i.rim, i.radius_at, i.about)
                   and not x.freedom.decided]
        k, n = fellows.index(i), max(len(fellows), 1)
        return 360.0 * k / n

    def _settle_round_rim(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides round the rim (or the bore)
        from its slot, its reach at the keep-in, facing out wherever it lands."""
        disc = self._disc("the same place is OnEdge(board.edge(facing=...))")
        bore = i.rim == "bore"
        ideal = self._round_slot(i)
        r = max(disc.bore if bore else disc.radius, 1e-6)

        def at(angle):
            rot = self.outward_rotation(i.item, angle + (180.0 if bore else 0.0))[0] if i.outward else i.rotation
            return disc_placement(occ, i.item, disc, angle, i.clearance, rot, i.face, bore=bore)
        return self._slide(occ, i, plan, clr, ideal, ideal - 180.0, ideal + 180.0, at,
                           "round the %s" % ("bore" if bore else "rim"),
                           step=math.degrees(max(i.step, 0.2) / r), units="deg")

    def _settle_round_ring(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides round the ring it was given."""
        centre = i.about or self.centre
        ideal = self._round_slot(i)
        r = max(float(i.radius_at), 1e-6)

        def at(angle):
            return box_centered_placement(occ, i.item, polar_point(centre, angle, r), i.rotation, i.face)
        return self._slide(occ, i, plan, clr, ideal, ideal - 180.0, ideal + 180.0, at,
                           "round the %.2f mm ring" % r, step=math.degrees(max(i.step, 0.2) / r), units="deg")

    def _settle_along_spoke(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides out along its bearing, from
        the bore's keep-in (or the centre) to as far as the board reaches."""
        centre = i.about or self.centre
        if isinstance(self._shape, Disc) and centre == self._shape.centre:
            lo, hi = self._shape.bore + self.keep_in, self._shape.radius - self.keep_in
        else:
            box = occ.board_box
            lo, hi = 0.0, max(box.width, box.height)     # the board's own keep-in prunes what is too far
        ideal = (lo + hi) / 2.0

        def at(r):
            return box_centered_placement(occ, i.item, polar_point(centre, i.angle, r), i.rotation, i.face)
        return self._slide(occ, i, plan, clr, ideal, lo, hi, at, "out along the %.0f degree spoke" % i.angle)

    def _no_pocket_note(self, occ: Occupancy, i: PlaceIntent) -> str:
        """A search cannot succeed where no free rectangle holds the item's
        envelope at any of its rotations: say so instead of scanning."""
        if occ.board_box is None:
            return ""
        envs = []
        for rot in (i.rotations or (i.rotation,)):
            env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, i.face))
            if pockets(occ, env.width, env.height, i.face, step=max(i.step, 0.5), limit=1):
                return ""
            envs.append(env)
        env = envs[0]
        return "no pocket fits its %.1f x %.1f envelope on the %s face at any rotation asked for" % (
            env.width, env.height, i.face.value)

    def _no_place_report(self, occ: Occupancy, obj, step) -> str:
        """Why a critical item stopped the run: its envelope, the reason, and
        the biggest free rectangles on its face, so the reader can see what
        would have to move."""
        item = obj.item.anchor if obj.kind == "block" else obj.item
        env = occ.body_box(item, Placement(Location(0, 0), obj.rotation, obj.face))
        free = pockets(occ, 2.0, 2.0, obj.face, step=0.5, limit=4)
        rects = "; ".join("%.1f x %.1f at (%.1f, %.1f)" % (p.box.width, p.box.height, p.box.center.x, p.box.center.y)
                          for p in free) or "none"
        return ("%s (required) found no place for its %.1f x %.1f envelope on the %s face: %s. "
                "Biggest free rectangles there now: %s. The board as it stood is written; nothing was placed after it."
                % (obj.key, env.width, env.height, obj.face.value, step.note.replace("UNPLACED: ", ""), rects))

    def _next_to_place(self, pending: list, occ: Occupancy, placed: set):
        """Which searched item goes next: the script's tier first, then the
        rank (what the item IS), then the strongest pull toward what is
        already placed, then the largest.

        Pull is a TIE-BREAK. It counts an item's pads against the placed pads
        they share a net with, so it measures net fan-out, which tracks pin
        count and bus membership rather than how hard an item is to place. It
        decides between items the rank cannot separate - the shelf of
        identical passives, which score the same to the last bit - and
        nothing else."""
        def measure(obj):
            parts = obj.item.members if obj.kind == "block" else (obj.item,)
            area = sum(s.box.area for it in parts for s in occ._geometry(it).shapes
                       if s.kind == "courtyard")
            pull = sum(w for it in parts for _, _, w in self._targets(it, occ, placed))
            return self._rank_score.get(obj.key, 0.0), pull, area

        scored = sorted(((measure(o), o) for o in pending),
                        key=lambda m: (-m[1].priority.rank, -m[0][0], -m[0][1], -m[0][2], m[1].key))
        (score, pull, area), obj = scored[0]
        why = "next: " + self._rank_note.get(obj.key, "largest (%.0f mm2)" % area)
        return obj, why

    def _settle_block(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set) -> Step:
        spec = i.item
        clr = self.clearance
        if i.at is not None or i.center is not None:
            # Said in pads or in numbers, the point is resolved here, the same way
            # a part's is: a block declared against a reference waits for it.
            anchor = Placement(_locate(self, occ, i.at), i.rotation, i.face) if i.at is not None else \
                box_centered_placement(occ, spec.anchor, _locate(self, occ, i.center), i.rotation, i.face)
            members, why = layout_block(occ, spec, anchor, clr)
            if members is None:
                plan.findings.append("%s (fixed): %s" % (i.key, why))
                members = {spec.anchor.inst: anchor}
            note = why or ""
        else:
            targets = self._targets(spec.anchor, occ, placed)
            current = occ._geometry(spec.anchor).reference
            if i.near is not None:
                hint = Placement(_locate(self, occ, i.near), i.rotation, i.face)
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
        return Step(i.key, "block", None if i.freedom.decided else i.priority, anchor_at, 0.0, note, i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)

    def _settle(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set = frozenset()) -> Step:
        if i.kind == "block":
            return self._settle_block(occ, i, plan, placed)
        clr = self.clearance
        chose = ""
        if i.freedom.decided:
            if i.at is not None:
                p = Placement(_locate(self, occ, i.at), i.rotation, i.face)
            elif i.center is not None and i.pin is not None:
                p = pad_anchored_placement(occ, i.item, i.pin, _locate(self, occ, i.center), i.rotation, i.face)
                # A net names one pad here, the first of however many carry it.
                # Say which, because an offset the script measured has to come
                # off the same pad, and from outside nothing shows which it was.
                kind, value = pad_key(i.pin)
                if kind == "net":
                    same = i.item.pads_on(value)
                    if len(same) > 1:
                        chose = "%s is %d pads on %s: pad %s is the one on the point" % (
                            value, len(same), i.item.ref, i.item.pad(i.pin).number)
            elif i.center is not None:
                p = box_centered_placement(occ, i.item, _locate(self, occ, i.center), i.rotation, i.face)
            elif i.run is not None:
                p = run_placement(occ, i.item, occ.board_shape or self._shaped(), i.run,
                                  _run_along(self, occ, i), i.clearance, i.rotation, i.face)
            elif i.rim is not None:
                p = disc_placement(occ, i.item, self._disc("the same place is "
                                                          "OnEdge(board.edge(facing=...))"),
                                   i.angle, i.clearance, i.rotation, i.face, bore=i.rim == "bore")
            else:
                if isinstance(i.along, _RowSlot):
                    along = i.along.resolve(self, occ)
                elif isinstance(i.along, _EdgeFraction):
                    along = self._edge_fraction(i.edge, occ, i.along.fraction)
                    if i.along.anchor in ("start", "end"):
                        reach = occ.reach_box(i.item, Placement(Location(0.0, 0.0), i.rotation, i.face))
                        half = (reach.width if i.edge in (Edge.NORTH, Edge.SOUTH) else reach.height) / 2.0
                        along += half if i.along.anchor == "start" else -half
                else:
                    along = _coord(self, occ, i.along, "x" if i.edge in (Edge.NORTH, Edge.SOUTH) else "y")
                p = edge_placement(occ, i.item, i.edge, along, i.rotation, i.clearance, i.face)
            why = occ.legal(i.item, p, clr,
                            past_edge=(i.edge is not None or i.run is not None or i.rim == "rim")
                            and i.clearance < self.keep_in)
            if why:
                plan.findings.append("%s (%s): %s" % (i.key, i.freedom.value, why))
            return Step(i.key, i.kind, None if i.freedom.decided else i.priority, p, 0.0, "; ".join(x for x in (chose, why) if x), i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)
        if i.run is not None:
            return self._settle_along_run(occ, i, plan, clr)
        if i.rim is not None:
            return self._settle_round_rim(occ, i, plan, clr)
        if i.radius_at is not None:
            return self._settle_round_ring(occ, i, plan, clr)
        if i.angle is not None:
            return self._settle_along_spoke(occ, i, plan, clr)
        if i.edge is not None:
            return self._settle_along_edge(occ, i, plan, clr)
        if i.pin_x is not None or i.pin_y is not None:
            return self._settle_along_line(occ, i, plan, clr)
        current = occ._geometry(i.item).reference
        targets = self._targets(i.item, occ, placed)
        seeded = ""
        if i.near is not None:
            hint = Placement(_locate(self, occ, i.near), i.rotation, i.face)
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
            for n in nets:
                plan.seeded_by_net[n] += 1
        else:
            return self._settle_in_pocket(occ, i, plan, clr)
        score = self._scorer(i.item, occ, targets) if targets else None
        # A seeded item lands on the pads that pull it; it must be free to step at least its own size clear of them.
        body = occ._geometry(i.item).body
        radius = i.radius if i.near is not None else max(i.radius, body.width, body.height)
        hopeless = self._no_pocket_note(occ, i)
        if hopeless:
            plan.findings.append("%s: %s" % (i.key, hopeless))
            return Step(i.key, i.kind, None if i.freedom.decided else i.priority, None, 0.0, "UNPLACED: " + hopeless, i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)
        result = scan(occ, i.item, hint, radius, i.step, i.rotations or (i.rotation,), clr, score=score)
        if result.chosen is None:
            plan.findings.append("%s: no legal location within %.1f mm of %s (%s)" % (
                i.key, radius, _loc(hint.location), _blame_text(result)))
            return Step(i.key, i.kind, None if i.freedom.decided else i.priority, None, 0.0, "UNPLACED: " + "; ".join(result.reasons.values()), i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)
        note = seeded
        if result.moved_mm > 0:
            first = next(iter(result.reasons.values()), "")
            moved = "moved %.2f mm off the hint" % result.moved_mm
            if first:
                moved += ": " + first
            elif score:
                moved += " for a better link score"
            note = (note + "; " if note else "") + moved
        return Step(i.key, i.kind, None if i.freedom.decided else i.priority, result.chosen, result.moved_mm, note, i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)

_EDGE_BEARING = {Edge.NORTH: 0.0, Edge.EAST: 90.0, Edge.SOUTH: 180.0, Edge.WEST: 270.0}
_EDGE_DIR = {Edge.NORTH: (0.0, -1.0), Edge.SOUTH: (0.0, 1.0), Edge.EAST: (1.0, 0.0), Edge.WEST: (-1.0, 0.0)}


def _rotation_taking(local: Edge, edge: Edge) -> float:
    """The rotation (0, 90, 180 or 270) that turns a cell's `local` side
    (named at rotation 0) to face the board's `edge`: found by turning the
    side's direction, so no sign is guessed."""
    from .geometry import Transform
    want = _EDGE_DIR[edge]
    for r in (0.0, 90.0, 180.0, 270.0):
        x, y = Transform.rotate(r).apply(_EDGE_DIR[local])
        if abs(x - want[0]) < 1e-9 and abs(y - want[1]) < 1e-9:
            return r
    raise ValueError("no rotation takes %s to %s" % (local, edge))


def _label_op(text, box: Box, face: Face, side: Edge, gap: float, align: str, size: float, thick: float,
              knockout: bool, rotation: float, line: Box | None = None) -> Text:
    """The anchor and justification that put the text `gap` off `side` of
    `box`, aligned along that side. Along a north or south side `start` is
    the west end; along an east or west side it is the north end. `line`,
    when given, is the box the text stands off instead (a group of labels
    sharing one line); `box` still sets where it sits along the side."""
    mirrored = face is Face.BACK
    off = line or box
    def T(*a):
        return Text(*a, side=side)
    if rotation == 0:
        along = {"centre": ("centre", box.center.x), "start": ("left", box.left), "end": ("right", box.right)}
        across = {"centre": ("centre", box.center.y), "start": ("top", box.top), "end": ("bottom", box.bottom)}
        if side is Edge.NORTH:
            hj, x = along[align]; return T(text, Location(x, off.top - gap), face, size, thick, 0.0, hj, "bottom", knockout, mirrored)
        if side is Edge.SOUTH:
            hj, x = along[align]; return T(text, Location(x, off.bottom + gap), face, size, thick, 0.0, hj, "top", knockout, mirrored)
        if side is Edge.WEST:
            vj, y = across[align]; return T(text, Location(off.left - gap, y), face, size, thick, 0.0, "right", vj, knockout, mirrored)
        vj, y = across[align]; return T(text, Location(off.right + gap, y), face, size, thick, 0.0, "left", vj, knockout, mirrored)
    # 90 counter-clockwise: the text runs up the page, its top faces west
    along = {"centre": ("centre", box.center.y), "start": ("right", box.top), "end": ("left", box.bottom)}
    across = {"centre": ("centre", box.center.x), "start": ("bottom", box.left), "end": ("top", box.right)}
    if side is Edge.WEST:
        hj, y = along[align]; return T(text, Location(off.left - gap, y), face, size, thick, 90.0, hj, "bottom", knockout, mirrored)
    if side is Edge.EAST:
        hj, y = along[align]; return T(text, Location(off.right + gap, y), face, size, thick, 90.0, hj, "top", knockout, mirrored)
    if side is Edge.NORTH:
        vj, x = across[align]; return T(text, Location(x, off.top - gap), face, size, thick, 90.0, "left", vj, knockout, mirrored)
    vj, x = across[align]; return T(text, Location(x, off.bottom + gap), face, size, thick, 90.0, "right", vj, knockout, mirrored)


def _run_along(board: "Board", occ: Occupancy, i: PlaceIntent) -> float:
    """Where along a run an item was told to sit: a length in mm, or the
    place on the run nearest a reference."""
    if isinstance(i.along, (int, float)):
        return float(i.along)
    return i.run.project(_locate(board, occ, i.along))


def _circle(centre: Location, radius: float, segments: int = 72) -> tuple:
    """A circle as a polygon, for reading runs off a round board."""
    return tuple((round(centre.x + bearing_vector(360.0 * n / segments)[0] * radius, 6),
                  round(centre.y + bearing_vector(360.0 * n / segments)[1] * radius, 6))
                 for n in range(segments))


def _as_point(value) -> Location:
    """A centre a script gave: a Location, or an (x, y) pair."""
    if isinstance(value, Location):
        return value
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
        return Location(float(value[0]), float(value[1]))
    raise TypeError("a centre is a Location or an (x, y) pair, not %r" % (value,))


def _locate(board: "Board", occ: Occupancy, ref) -> Location:
    """A point on the board as things stand: a Location, a pad reference
    (where that pad now is), the Mid of two points, or an (x, y) pair whose
    members may be numbers, X()/Y() of references, or row coordinates."""
    if isinstance(ref, Location):
        if isinstance(ref.x, (int, float)) and isinstance(ref.y, (int, float)):
            return ref
        return Location(_coord(board, occ, ref.x, "x"), _coord(board, occ, ref.y, "y"))   # a Location said in references
    if isinstance(ref, Mid):
        a, b = _locate(board, occ, ref.a), _locate(board, occ, ref.b)
        return Location((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)
    if isinstance(ref, tuple) and len(ref) == 2:
        return Location(_coord(board, occ, ref[0], "x"), _coord(board, occ, ref[1], "y"))
    if isinstance(ref, Centre):
        return Location(_coord(board, occ, ref.x, "x"), _coord(board, occ, ref.y, "y"))
    if isinstance(ref, (Part, Cell)):
        geom, key, kind = board._item(ref)
        refs = [fp.ref for fp in (geom.members if kind == "cell" else (geom,))]
        return Box.union([occ.items[r].body for r in refs]).center      # where its body is now
    owner, number, dx, dy = board._pad_ref(ref)
    return occ.pad_location(owner, number).offset(dx, dy)


def _coord(board: "Board", occ: Occupancy, v, axis: str) -> float:
    """One coordinate: a number, X()/Y() of a reference, a row coordinate,
    or a reference/point whose `axis` coordinate is meant."""
    if isinstance(v, X):
        return _locate(board, occ, v.ref).x + v.dx
    if isinstance(v, Y):
        return _locate(board, occ, v.ref).y + v.dy
    if isinstance(v, (PadRef, CellPadRef, Location, tuple, Mid, Part, Cell)):
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
        self.planned_vias: list = []       # every via planned so far, for a FreeSpot's hole rule
        self.plan = None                   # the plan being built: its keepouts, for a FreeSpot

    def locate(self, ref) -> Location:
        return _locate(self.board, self.occ, ref)

    def coord(self, v, axis: str) -> float:
        return _coord(self.board, self.occ, v, axis)

    def tracks_on(self, layer) -> list:
        return [t for t in self.planned_tracks if t.layer is layer]


def _cutout_half_across(cutout, bearing_deg: float) -> float:
    """How far the shape reaches from its centre along a bearing: what holds
    a hole placed on an edge back off it."""
    lo_x, lo_y, hi_x, hi_y = cutout.shape.box_at(Location(0.0, 0.0), 0.0)
    return box_support(Box(lo_x, lo_y, hi_x, hi_y), bearing_deg) / 2.0


def _refs_in(points) -> list:
    """Every pad, part or cell reference a list of points depends on (inside tuples and X/Y too)."""
    out = []
    for p in points:
        if isinstance(p, (PadRef, CellPadRef, Part, Cell)):
            out.append(p)
        elif isinstance(p, (X, Y)):
            out += _refs_in([p.ref])        # the ref may itself be a point or a pad
        elif isinstance(p, FreeSpot):
            out += _refs_in([p.near])       # the pad it searches from must be placed first
        elif isinstance(p, Mid):
            out += _refs_in([p.a, p.b])
        elif isinstance(p, tuple):
            out += _refs_in(p)
        elif isinstance(p, (Centre, Location)):
            out += _refs_in([p.x, p.y])
    return out


def _op_layers(op) -> frozenset:
    """The copper layers a drawn op occupies. A via joins the whole stack, so
    a region covering any one layer contains it."""
    if isinstance(op, Via):
        return frozenset(CopperLayer)
    return frozenset([op.layer])


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


def _blame_text(result) -> str:
    """The rejection counts, and for each kind the owners that caused most of
    them. The owner and the faces are computed for every candidate the scan
    refuses and were being thrown away; three owners, because a crowded board
    has forty and a reader needs one."""
    parts = []
    for kind, n in result.rejected.most_common(3):
        owners = sorted(((owner, faces, count)
                         for (k, owner, faces), count in result.blockers.items()
                         if k == kind and owner),
                        key=lambda t: -t[2])[:3]
        detail = "" if not owners else ": " + ", ".join(
            "%s%s x%d" % (owner, (" %s face" % faces) if faces else "", count)
            for owner, faces, count in owners)
        parts.append("%s x%d%s" % (kind, n, detail))
    return "; ".join(parts)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def _loc(l: Location) -> str:
    return "(%.2f, %.2f)" % (l.x, l.y)


STEP_HEADER = "%-28s %-6s %-11s %s" % ("item", "kind", "place", "result")


def _place_column(s: "Step") -> str:
    """What decided when this step ran: a decided placement says its freedom,
    a searched one its rank, and copper its priority."""
    if s.freedom is not None and s.freedom.decided:
        return s.freedom.value
    if s.rank:
        return "rank %d/%d" % (s.rank, s.rank_of or s.rank)
    return s.priority.value if s.priority else ""


def _fmt(s: Step) -> str:
    """One step, in the columns STEP_HEADER names. A placement's result is
    `at (x, y) rot R face F`; copper's is its op count."""
    place = _place_column(s)
    if s.placement is None:
        return "%-28s %-6s %-11s %s" % (s.item, s.kind, place, s.note)
    out = "%-28s %-6s %-11s at %s rot %g face %s" % (s.item, s.kind, place, _loc(s.placement.location),
                                                     s.placement.rotation, s.placement.face.value)
    if s.note:
        out += "  " + s.note
    return out
