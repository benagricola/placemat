"""The Board object a layout script declares to, and the Plan resolve()
produces from it.

Board answers questions about the generated board, records placement and
copper declarations, and resolves them in order against the occupancy model:
setup, the decided placements, the copper whose endpoints are all decided,
every searched item by rank, the cleanup pass (cleanup.py), the rest of the
copper, then the checks, the congestion measure (congestion.py) and the
labels. Steps whose inputs did not change since the previous run are replayed
from its record (reuse.py) instead of resolved. Plan holds the resolved
placements, copper ops and findings for the writer and the run record."""
from __future__ import annotations

import collections
import contextlib
import dataclasses

from collections import Counter
from dataclasses import dataclass, field
import math

from .copper import (Pour, Text, Track, Via, Zone, board_zone_outline, chamfer_cuts, chamfered, finger_ops, octilinear,
                     pair_ops, polyline_tracks, resolve_bridges)
from .geometry import Transform, box_polygon, circle_polygon, via_ring, point_in_polygon, poly_distance, poly_within, polys_overlap, segments_intersect, transform_box
from .findings import Finding, Findings
from .occupancy import Occupancy, Shape, ShapeIndex, TOUCH, _polygon_area, hole_shape, parts_claim
from .cutouts import Cutouts, Path, loop_gap, signed_area
from .outline import Outline, Run, rect_outline
from .placement import Placement
from .settings import Settings
from .placer import BlockSpec, _grid, _pin_normal, _reason_key, box_centered_placement, cell_pad_anchored_placement, cell_origin_anchored_placement, disc_placement, pad_anchored_placement, edge_placement, layout_block, pockets, run_placement, scan, scan_block
from .board_geometry import BoardGeometry, CellGeom, Footprint, members_of, part_height, stackup_order
from .values import (Turned, Axis, Bend, Cover, Beside, Between, Cutout, CutoutEdge, Freedom, Keepout, bearing_of, Along, Box, Cell, CellPadRef, Centre, Disc, Line, OnBore, OnRim, Past, Pin, Polar, bearing, bearing_vector, box_support, polar_point, CopperLayer, Edge, Face, Fraction, FreeSpot, Inside, Land, LinkWeight, Location, Mid, Near, Net, OnEdge, PadRef, Part,
                     Priority, X, Y, pad_key)

RANK_FIXED, RANK_EDGE, RANK_CELL, RANK_FIXED_COPPER, RANK_BLOCK, RANK_LOOSE, RANK_COPPER = range(7)


# A cell generated with its connector's body bulk on local +Y ("outward")
# faces out of each edge at this rotation.
_OUTWARD_ROTATION = {Edge.SOUTH: 0.0, Edge.EAST: 90.0, Edge.NORTH: 180.0, Edge.WEST: 270.0}

# What envelope.drawn_envelope unions for a single footprint - pads, mask
# openings, silk and body - read as occupancy shape kinds, so a keepout
# shaped by an item can grow the same box a cell's own members draw: the
# item's courtyard (an assembly margin, not drawn geometry) is left out.
_ENVELOPE_DRAWN_KINDS = frozenset(("silk", "body", "mask", "pad", "through"))

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
    against the outline. With `pitch`, neighbouring items' centres are
    `pitch` apart instead of their claims `gap` apart."""

    # A declaration's digest names every attribute a Row holds, so a pitch is
    # set on the instance only when given: a row without one digests as before.
    pitch: float | None = None

    def __init__(self, edge: Edge, standoff: float, gap: float, start: float | None, keys, alongs, depth: float,
                 pitch: float | None = None):
        self.edge, self.standoff, self.gap = edge, standoff, gap     # standoff: the outer line, in from the edge
        self.keys, self.alongs, self.depth = list(keys), list(alongs), depth
        self.items: list = []
        if pitch is not None:
            self.pitch = float(pitch)
            self.length = alongs[0] / 2.0 + self.pitch * (len(alongs) - 1) + alongs[-1] / 2.0
        else:
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
        elif kind == "outline_end":
            self.begin(self.end_of(occ.board_box, board.keep_in))
        elif kind == "centre":
            self.begin(_coord(board, occ, value, axis) - self.length / 2.0)
        elif kind == "end":
            self.begin(_coord(board, occ, value, axis) - self.length)
        elif kind == "start":
            self.begin(_coord(board, occ, value, axis))
        elif kind == "of":
            of, align, *centre = value
            if centre:
                self.begin(_coord(board, occ, centre[0], axis) - self.middle())
                return
            box = board._placed_envelope_box(occ, of)
            lo, hi = (box.top, box.bottom) if axis == "y" else (box.left, box.right)
            self.begin(lo + align.fraction * (hi - lo - self.length))
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
        if self.pitch is not None:
            self.centres = [start + self.alongs[0] / 2.0 + n * self.pitch for n in range(len(self.alongs))]
            return
        self.centres = []
        cursor = start
        for a in self.alongs:
            self.centres.append(cursor + a / 2.0)
            cursor += a + self.gap

    def middle(self) -> float:
        """How far past its start the row's middle lies: halfway between the
        first and last items' centres at a pitch, else half its length."""
        if self.pitch is not None:
            return self.alongs[0] / 2.0 + self.pitch * (len(self.alongs) - 1) / 2.0
        return self.length / 2.0

    def centre_of(self, outline: Box) -> float:
        total = outline.height if self.edge in (Edge.EAST, Edge.WEST) else outline.width
        return (total - self.length) / 2.0

    def end_of(self, outline: Box, keep_in: float) -> float:
        """Where the row starts so its far end sits flush with the far
        keep-in, the mirror of the near keep-in a plain "start" begins at."""
        total = outline.height if self.edge in (Edge.EAST, Edge.WEST) else outline.width
        return total - keep_in - self.length

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


_ALIGN_ALIASES = {"centre": Along.MID, "center": Along.MID}    # Along's own spelling is "mid"


def _as_align(value, what: str = "align") -> Along:
    """A row's or a label's `align=`: the Along enum, or the string a
    script already writes ("start", "centre", the misspelling "center",
    "end"), normalised so either spelling reads the same rule."""
    if isinstance(value, Along):
        return value
    if value in _ALIGN_ALIASES:
        return _ALIGN_ALIASES[value]
    try:
        return Along(value)
    except ValueError:
        raise ValueError("%s is \"start\", \"centre\"/\"center\", \"end\" or Along.START/MID/END, not %r"
                         % (what, value)) from None


def _align_word(a: Along) -> str:
    """The three-word spelling _label_op still reads ("centre", not
    Along.MID's own "mid")."""
    return "centre" if a is Along.MID else a.value


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
    rotation_given: bool = False          # the script said rotation=: that one, not a choice of four
    turned: object = field(default=None, metadata={"omit_default": True})   # a Turned: its part's rotation plus its degrees, settled at placement
    beside: object = field(default=None, metadata={"omit_default": True})   # a _BesideSpec: settled against its item's placed envelope
    row_of: object = field(default=None, metadata={"omit_default": True})   # a row(of=) item: an edge placement measured off its envelope, not the board's
    cell_pin: object = field(default=None, metadata={"omit_default": True})  # (owner, number, dx, dy[, lx, ly]): a cell placed by a member's pad
    line: int = field(default=0, metadata={"reuse": False})   # the script line that declared it: not what it decides

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


@dataclass(frozen=True)
class _BesideSpec:
    """A resolved Beside(...): `item` (a Part, a Cell or a KeepoutIntent,
    already placed by the time this settles), `side`, `gap` (None: the
    envelope's own), and `align` normalised to `("along", Along)`,
    `("pads", own_key, PadRef)` - `own_key` a pad of the part being placed,
    the `PadRef` a pad of `item` (its own net when align was a bare
    PadRef) - or `("past", own_key, Past)`, a Past over pads."""
    item: object
    side: Edge
    align: tuple
    gap: float | None


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
    why: str = field(metadata={"reuse": False})                  # prose: decides nothing
    a_ref: object = None
    b_ref: object = None
    achieved_mm: float | None = field(default=None, metadata={"reuse": False})   # measured by a resolve, not declared

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


@dataclass(frozen=True)
class MergedZone:
    """A stamped cell's zone left out of the written board because the
    board's own plane on its net and layer covers it; `note` says how the
    cell's zone was set up differently from that plane, if it was."""
    cell: str
    net: str
    layer: CopperLayer
    note: str = ""


@dataclass(frozen=True)
class DeclaredGroup:
    """A KiCad group a script declared with board.group(): the parts (by
    refdes) it holds, at the top level."""
    name: str
    parts: tuple
    why: str = ""


@dataclass
class Plan:
    geometry: BoardGeometry
    occupancy: Occupancy
    steps: list[Step] = field(default_factory=list)
    findings: Findings = field(default_factory=Findings)
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
    solve: dict = field(default_factory=dict)                     # what the global solve did, when it ran
    pocketed: list = field(default_factory=list)                  # seeded items whose scan failed and took a pocket
    footprints: list = field(default_factory=list)                # courtyard mode: footprints whose courtyard understates the part
    cleanup: dict = field(default_factory=dict)                   # what the cleanup pass did, when it ran
    rudy: object = None                                           # congestion.Rudy of the placed board
    reuse: dict = field(default_factory=dict)                     # this run's record, for the next run to replay
    turns: dict = field(default_factory=dict, repr=False)        # each searched item's turn: where it went and the pad it depends on (lock.py)
    adopted: dict = field(default_factory=dict)                   # net -> "held", or "dropped: why": routed copper kept beside the script
    cell_zones_under_planes: str = "drop"                         # settings: a cell's zone under the board's own plane is merged into it
    merged_zones: list = field(default_factory=list)              # the cell zones the write merged into a plane (MergedZone)
    kept_zones: list = field(default_factory=list)                # ones a plane covers but that join pads otherwise: kept
    models: dict = field(default_factory=dict)                    # the write's model paths: {"reanchored": n, "missing": [files]}
    split_groups: str = "lift"                                    # settings: what the write does to the generator's nested groups
    groups: list = field(default_factory=list)                    # the groups the script declared (DeclaredGroup)
    group_notes: list = field(default_factory=list)               # what the write did to the board's groups, a line each
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


# What a candidate the scorer did not finish weighing scores on top of its
# wire: more than any real cost, so it is never chosen over one weighed in full.
PRUNED = 1e6


class Scorer:
    """A searched item's cost at a candidate placement: each connection's
    weight times its length, `score.crossing` for each ratsnest crossing its
    airwires would add, and the escape weights for each escape it would
    cross, close or wall off (escapes.py). With `prune`, a candidate whose
    wire alone reaches the best cost weighed so far (`best[0]`) is not
    weighed further: its crossings and escapes can only add. Explore draws
    among candidates near the best and needs every one weighed.

    Called, it is the Python reference; `native(rots, face)` hands a scan
    the same cost, worked out in the native sweep (placemat_native.NativeScoring),
    sharing `best` with it."""

    def __init__(self, settings, item, occ: Occupancy, targets: list, prune: bool):
        s = settings
        self.s, self.item, self.occ, self.targets, self.prune = s, item, occ, targets, prune
        self.crossing = s.score_crossing
        self.rn = occ.ratsnest() if self.crossing > 0 else None
        self.escaping = s.score_escape_crossed > 0 or s.score_escape_closed > 0 or s.score_escape_walled > 0
        self.esc = occ.escapes() if self.escaping else None
        self.own = frozenset(fp.ref for fp in members_of(item))
        self.depth = s.place_escape_depth
        self.best = [math.inf]
        self._native = {}

    def __call__(self, placement: Placement) -> float:
        occ, s = self.occ, self.s
        pads = occ.candidate_pad_locations(self.item, placement)
        cost = sum(w * pads[key].distance(target) for key, target, w in self.targets if key in pads)
        if self.prune and cost >= self.best[0]:
            return cost + PRUNED        # its crossings and escapes can only add: it cannot be the best
        crossed = None
        if self.rn is not None:
            added, crossed = self.rn.leaf_costs(occ.candidate_anchors(self.item, placement), self.own, self.depth)
            cost += self.crossing * added
        if self.esc is not None:
            crossed, closed, walled = self.esc.closed(self.item, placement, crossed)
            cost += s.score_escape_crossed * crossed + s.score_escape_closed * closed + s.score_escape_walled * walled
        self.best[0] = min(self.best[0], cost)
        return cost

    def native(self, rots, face):
        """The same cost for the native sweep over these turns, or None when
        the native mirrors it needs are not there."""
        occ, s = self.occ, self.s
        rn = occ.ratsnest()
        mirror = rn.mirror
        if mirror is None or (self.esc is not None and self.esc.mirror is None):
            return None
        key = (tuple(rots), face)
        hit = self._native.get(key)
        if hit is None:
            geom = occ._geometry(self.item)
            centres = occ.reference_pad_centres(self.item)
            targets = [((centres[k].x, centres[k].y), (t.x, t.y), w) for k, t, w in self.targets if k in centres]
            origin = [Placement(Location(0.0, 0.0), r, face) for r in rots]
            esc = self.esc if self.esc is not None else occ.escapes()
            hit = occ.native_module().NativeScoring(
                mirror, targets, [occ.turn_transform(geom, r, face) for r in rots],
                [occ.candidate_anchors(self.item, pl) for pl in origin],
                [esc._native_turn(self.item, pl) for pl in origin] if self.esc is not None else [],
                sorted(self.own), self.crossing, self.esc is not None,
                (s.score_escape_crossed, s.score_escape_closed, s.score_escape_walled), self.depth,
                self.prune, PRUNED, self.best[0])
            self._native[key] = hit
        hit.floor = self.best[0]
        return hit


class Board:
    """One board being laid out. Questions are answered from the geometry read
    off the generated .kicad_pcb; declarations are collected and resolved
    together."""

    @property
    def width(self) -> float:
        if getattr(self, "_fit", False) and self._fit_axis is not Axis.Y:
            raise ValueError("a fit frame has no width until its content is placed: the plan's outline has it")
        return self._frame_width

    @width.setter
    def width(self, value):
        self._frame_width = value

    @property
    def height(self) -> float:
        if getattr(self, "_fit", False) and self._fit_axis is not Axis.X:
            raise ValueError("a fit frame has no height until its content is placed: the plan's outline has it")
        return self._frame_height

    @height.setter
    def height(self, value):
        self._frame_height = value

    def _refuse_on_fit(self, what: str):
        if not self._fit:
            return
        # fit=Axis.X/Y's declared axis is a number from board.size() on, but its
        # edges are refused here too: the row and edge machinery reads the
        # board's own outline for both axes together, which a fit frame in one
        # axis does not have until content is placed even on the axis it
        # declared - a scope decision (docs/superpowers/specs/2026-09-29-
        # missing-intent-relations-design.md's review), not a limit of the
        # declared number itself, which board.width/board.height still answer.
        if self._fit_axis is Axis.X:
            raise ValueError("%s: a fit frame in one axis has no edges yet - not even north or south, which "
                             "its declared height fixes - until its content is placed" % what)
        if self._fit_axis is Axis.Y:
            raise ValueError("%s: a fit frame in one axis has no edges yet - not even east or west, which "
                             "its declared width fixes - until its content is placed" % what)
        raise ValueError("%s: a fit frame has no edges or centre until its content is placed" % what)

    def __init__(self, geometry: BoardGeometry, edge_margin: float | None = None, clearance: float | None = None,
                 via_drill: float = 0.3, via_size: float = 0.6, keep_going: bool = False,
                 courtyard_excess: float = 0.1, settings: Settings | None = None,
                 component_spacing: float | None = None):
        self.settings = settings if settings is not None else Settings()
        self._solve_hints = None
        self.geometry = geometry
        self.courtyard_excess = courtyard_excess    # the fab's assembly margin round a part: the only spacing that comes free
        # body to body in the physical envelope: twice the excess, the touching courtyards of a well-drawn footprint
        self.component_spacing = 2 * courtyard_excess if component_spacing is None else component_spacing
        self.edge_margin = geometry.edge_clearance if edge_margin is None else edge_margin
        self.clearance = clearance
        self.via_drill, self.via_size = via_drill, via_size
        self.keep_going = keep_going            # carry on past colliding decided items, as findings;
                                                # required=True overrides it
        self._intents: list = []            # placements and cutouts: one queue, ordered by needs
        self._rider_of: dict = {}           # rider key -> the key of the item it rides (resolve's _find_riders)
        self._ride_groups: dict = {}        # searched item key -> the riders settled with it, in order
        self._rank_score: dict = {}
        self._rank_of: dict = {}
        self._rank_note: dict = {}
        self._waited: dict = {}                # item key -> the linked partner it waited for
        self._copper: list[CopperIntent] = []
        self._pad_vias: list = []          # (pad ref, net, drill, size) of each via declared at a pad: its part carries it
        self._labels: list = []
        self._fanouts: list = []           # (key, footprint, depth, sides or None, why)
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
        self._cell_placements: dict = {}    # cell name -> its settled Placement, for a region shaped by it
        self._groups: dict = {}             # the KiCad groups a script declared, by name (DeclaredGroup)
        self.web = 0.0                      # least material a hole may leave; 0: unchecked
        self._cached_outline = None         # this board as an outline, for reading runs off
        self._sized = False                 # the script has declared the board size
        self._fit = False                   # board.size(fit=True): the frame is the placed content plus a margin
        self._fit_margin = 0.0
        self._fit_axis: Axis | None = None  # board.size(fit=Axis.X/Y): only that axis fits; the other is declared
        self._frame_planes: set = set()     # planes with no outline of their own: on a fit board, planned once the frame is fitted
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

    def height_of(self, part) -> float:
        """A part's height in mm, from its `Pm.Height` field."""
        fp = self.geometry.footprint(part)
        h = part_height(fp)
        if h is None:
            raise ValueError("%s has no height: the capture gives it as the field Pm.Height (e.g. 1.1mm)" % fp.ref)
        return h

    def parts(self, net=None) -> list:
        """Every part on the board, by instance name; with `net`, those with a
        pad on it - so a drop to a plane, or a check on a rail, is derived from
        the netlist rather than a list typed into the script."""
        name = None if net is None else self.geometry.require_net(net)
        return [Part(fp.inst) for fp in sorted(self.geometry.footprints, key=lambda f: f.inst)
                if name is None or any(p.net == name for p in fp.pads)]

    def pitch(self, part, pins=None) -> float:
        """The spacing of a part's pins: the distance between neighbouring
        pin centres, read from the footprint (a connector's pin pitch, a
        two-pad part's pad spacing), a pin drawn as several lands counting
        as one. `pins=(a, b)`: the distance between those two pins."""
        from .describe import pin_centres, pitch_of
        fp = self.geometry.footprint(part)
        if pins is not None:
            a, b = (str(n) for n in pins)
            centres = pin_centres(fp.pads)
            missing = [n for n in (a, b) if n not in centres]
            if missing:
                raise ValueError("%s has no pin %s" % (fp.ref, ", ".join(missing)))
            return round(centres[a].distance(centres[b]), 6)
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

    def _bare_occupancy(self) -> Occupancy:
        """An occupancy with nothing placed, for measuring an item on its own:
        with this board's settings, so it measures what the envelope claims."""
        return Occupancy(self.geometry, self.edge_margin, board_box=None, settings=self.settings,
                         component_spacing=self.component_spacing)

    def extent(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """The item's body box at `rotation`, placed at the origin: a size, not a place."""
        geom, _, _ = self._item(item)
        occ = self._bare_occupancy()
        return occ.body_box(geom, Placement(Location(0.0, 0.0), rotation, face))

    def _row_gap(self, items, gap: float) -> float:
        """A row's or ring's gap, at least what the envelope keeps between two
        parts. In a drawn envelope items are spaced by their reach, and a pad
        or silk can sit at the edge of it, so neighbours need the widest gap
        the envelope enforces: the netclass clearance of their nets, the
        component spacing and the silk clearance. A courtyard envelope spaces
        by courtyards, which carry that margin already."""
        if self.settings.place_envelope == "courtyard":
            return gap
        nets = {p.net for item in items for fp in members_of(self._item(item)[0]) for p in fp.pads if p.net}
        widest = max([self.clearance or self.geometry.default_clearance or 0.0, self.component_spacing,
                      self.geometry.silk_clearance] +
                     [self.geometry.clearance(n) for n in nets if n in self.geometry.nets])
        return max(float(gap), widest)

    def envelope(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """What the placer keeps for the item at `rotation`, at the origin, as
        `[place] envelope` claims it: its courtyard and pads (courtyard), its
        pads, mask, silk and body (physical), or both (union), and under
        every envelope the footprint's own copper graphics. What a row or
        a stack built by hand must space by for the placer's gaps to hold."""
        geom, _, _ = self._item(item)
        occ = self._bare_occupancy()
        g = occ._geometry(geom)
        t = occ._transform(g, Placement(Location(0.0, 0.0), rotation, face))
        return Box.union([transform_box(s.box, t) for s in g.shapes if s.kind != "npth"])

    def claim(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """Everything the item claims at `rotation`, at the origin: its reach
        (body, pads, silk) and its courtyard together. What a row spaces by,
        so a zero gap is courtyards touching."""
        geom, _, _ = self._item(item)
        occ = self._bare_occupancy()
        p = Placement(Location(0.0, 0.0), rotation, face)
        courts = [transform_box(s.box, occ._transform(occ._geometry(geom), p))
                  for s in occ._geometry(geom).shapes if s.kind == "courtyard"]
        return Box.union([occ.reach_box(geom, p)] + courts)

    def reach(self, item, rotation: float = 0.0, face: Face = Face.FRONT) -> Box:
        """Everything the item physically is (body, pads, silk) at
        `rotation`, at the origin: what edge placement and rows measure."""
        geom, _, _ = self._item(item)
        occ = self._bare_occupancy()
        return occ.reach_box(geom, Placement(Location(0.0, 0.0), rotation, face))

    def _item_envelope_shape(self, item, margin: float, name: str) -> Path:
        """The region a keepout shaped by an item takes: envelope.drawn_envelope's
        box - pads, a footprint's own copper graphics, mask, silk and body, a
        cell's own union of its members', the cell's own tracks left out -
        grown by `margin`, in the item's own frame
        at rotation 0 (whatever face it currently has, so no face carries a
        spurious flip into the local shape): an anchor at the origin, so
        `path_at` lands it exactly where the item settles and turns with it.

        Read with its own occupancy, envelope forced to `physical`: what a
        script's own `[place] envelope` setting claims for search (courtyard
        by default) is a different question from what the item draws."""
        env = self._drawn_envelope_box(item)
        if env is None:
            raise ValueError("keepout %r: %s draws nothing to shape a region from" % (name, self._item(item)[1]))
        return Path(box_polygon(env.inflate(margin)), anchor=(0.0, 0.0))

    def _inside_shape(self, inside: Inside, name: str) -> Path:
        """The region `Inside(part, margin)` takes, in the frame
        `_item_envelope_shape` draws in (the part's own, at rotation 0, on its
        generated face) so it settles the same way: `_inner_box` of its pads,
        grown by the margin. A box with no area is refused."""
        from .geometry import transform_polygon
        geom, _, _ = self._item(inside.part)
        occ = self._bare_occupancy()
        g = occ._geometry(geom)
        t = occ._transform(g, Placement(Location(0.0, 0.0), 0.0, g.reference.face))
        pads = [Box.of_points(transform_polygon(s.poly, t)) for s in g.shapes
                if s.kind in ("pad", "through") and s.owner == geom.ref]
        if not pads:
            raise ValueError("keepout %r: %s has no pads to be inside" % (name, geom.ref))
        box = _inner_box(pads, transform_box(g.body, t).center).inflate(float(inside.margin))
        if box.width <= 1e-9 or box.height <= 1e-9:
            raise ValueError("keepout %r: the box inside %s's pads, grown by %g, is %.3f x %.3f mm: no area"
                             % (name, geom.ref, inside.margin, box.width, box.height))
        return Path(box_polygon(box), anchor=(0.0, 0.0))

    def _drawn_envelope_box(self, item, placement: Placement | None = None) -> Box | None:
        """The box round what a Part or Cell draws (envelope.drawn_envelope's
        kinds, and a footprint's own copper graphics; a cell's own tracks
        left out), at `placement`, or in the item's own frame at rotation 0
        when None. None when it draws nothing."""
        import dataclasses
        geom, key, kind = self._item(item)
        settings = dataclasses.replace(self.settings, place_envelope="physical")
        occ = Occupancy(self.geometry, self.edge_margin, board_box=None, settings=settings,
                        component_spacing=self.component_spacing)
        g = occ._geometry(geom)
        t = occ._transform(g, placement or Placement(Location(0.0, 0.0), 0.0, g.reference.face))
        own = key if kind == "cell" else None      # a cell's own copper is not a member's drawn envelope
        # a footprint's own copper graphics (a winding) are what it draws too, and what a fill
        # kept off it must stay off
        return Box.union([transform_box(s.box, t) for s in g.shapes
                          if (s.kind in _ENVELOPE_DRAWN_KINDS or s.kind == "copper") and s.owner != own])

    def _item_placement(self, occ: Occupancy, item) -> Placement:
        """Where a placed Part or Cell stands, for a region that moves and
        turns with it: a part's own settled placement, read off the
        occupancy directly; a cell's, recorded when it was committed - the
        occupancy itself keeps only each of its members' own, not the
        cell's."""
        geom, key, kind = self._item(item)
        if kind == "cell":
            return self._cell_placements[key]
        return occ.items[geom.ref].reference

    def _carry_pad_vias(self, occ) -> None:
        """Each via declared at a pad becomes copper of the pad's part - its
        ring on every layer and its hole, where the pad puts it - so the part,
        or the cell or block it is in, carries it through the search: a via
        at a searched part's pad is otherwise planned after the part has
        landed, over whatever the other face has there."""
        from .board_geometry import members_of
        from .lock import _turn
        from .occupancy import _BOTH, hole_shape
        # a decided item's vias are planned before the search, where it stands: only a searched one, or a
        # rider of one, carries them
        searched = {fp.ref for i in self._placements() if not i.freedom.decided or i.key in self._rider_of
                    for fp in (members_of(i.item) if hasattr(i, "item") and i.kind != "block" else
                               [i.item.anchor] + [sat for sat, _ in i.item.satellites] if i.kind == "block" else [])}
        for at, net, drill, size in self._pad_vias:
            ref, number, _, _ = self._pad_ref(at)
            if ref not in occ.items or ref not in searched:
                continue
            g = occ.items[ref]
            try:
                c = occ.pad_location(ref, number, self._pad_land(at))   # where the planned via will stand, by the same measure
            except KeyError:
                continue
            lx, ly = getattr(at, "lx", 0.0), getattr(at, "ly", 0.0)
            vx, vy = _turn(-lx if g.reference.face is Face.BACK else lx, ly, g.reference.rotation)
            c = Location(c.x + vx, c.y + vy)
            owner = "via at %s.%s" % (ref, number)       # not the part's: its pad lookups must not take it
            ring = via_ring(c, size)
            occ.carry(ref, [Shape(owner, "through", _BOTH, frozenset(self.geometry.layers), net, ring,
                                  Box.of_points(ring)), hole_shape(owner, c, drill, net)])

    def _pad_ref(self, ref):
        """Validate a pad reference now; return (refdes, pad number, dx, dy).
        A Part or Cell reference (its body centre) yields its first refdes
        and no pad: enough for the placement order to wait for it."""
        if isinstance(ref, (Part, Cell)):
            geom, key, kind = self._item(ref)
            return ((geom.members[0].ref if kind == "cell" else geom.ref), None, 0.0, 0.0)
        if isinstance(ref, PadRef):
            p = self.geometry.pad(ref.part, ref.key)
            self._pad_land(ref)                         # a real land, checked now
            return (p.owner, p.number, ref.dx, ref.dy)
        if isinstance(ref, CellPadRef):
            p = self.geometry.cell_pad(ref.cell, net=ref.net, number=ref.number, ref_prefix=ref.ref_prefix)
            return (p.owner, p.number, ref.dx, ref.dy)
        raise TypeError("not a pad reference: %r" % (ref,))

    def _pad_land(self, ref) -> int | None:
        """The 0-based land a PadRef's `land=` names among its pad number's
        lands, in the footprint's order: Land.LARGEST the one of most copper
        area (the first on a tie). None with no `land=`, and for a number of
        one land, so such a reference is the plain pad's."""
        land = getattr(ref, "land", None)
        if land is None:
            return None
        p = self.geometry.pad(ref.part, ref.key)
        lands = [q for q in self.geometry.footprint(p.owner).pads if q.number == p.number]
        if land is Land.LARGEST:
            areas = [sum(_polygon_area(o) for o in q.outlines) for q in lands]
            i = areas.index(max(areas))
        else:
            if land > len(lands):
                raise ValueError("%s pad %s has %d land%s; land=%d is past them"
                                 % (p.owner, p.number, len(lands), "" if len(lands) == 1 else "s", land))
            i = land - 1
        return None if len(lands) == 1 else i

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
            if owner not in occ.pending and (g.reach or g.body).overlaps(box):
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
            # the shape as it will be turned: along the edge (the implied turn), or as given
            rot = cutout.rotation if isinstance(cutout.rotation, (int, float)) else (
                out % 360.0 if cutout.rotation is None and getattr(cutout.shape, "turns", True) else 0.0)
            depth = max(self.web, 0.0) + _cutout_half_across(cutout, out, rot)
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

    def _region_rotation(self, occ, region, centre: Location) -> float:
        """The rotation a cutout or keepout settles at: what the script gave
        (a number, or Turned - the part's own placed rotation plus degrees,
        waited for the same way a place() does), else the implied turn."""
        rot = region.rotation
        if isinstance(rot, Turned):
            # a part turns counter-clockwise on screen (Transform.rotate); a region's
            # rotation is a bearing, clockwise from the top (cutouts._turned): the
            # region turns the way its part does, so the part's turn is negated
            ref = self._pad_ref(rot.part)[0]
            return -(occ.items[ref].reference.rotation + rot.degrees) % 360.0
        return float(rot) if rot is not None else self._implied_rotation(region, centre)

    def _cutout_candidates(self, occ, cutout):
        """Every centre its one freedom allows, nearest its ideal first, with
        the rotation each implies. The board's middle is the ideal for a free
        axis, so a hole takes the room furthest from the edges first. A
        Near() freedom is a search round a hint, the same as a part's."""
        at, box = cutout.at, self._outline

        def out_from(mid, lo, hi, step=0.2):
            n = int((hi - lo) / step) + 1
            for k in range(2 * n):
                v = mid + (k + 1) // 2 * step * (1 if k % 2 else -1)
                if lo <= v <= hi:
                    yield v

        if isinstance(at, Near):
            hint = _locate(self, occ, at.location)
            radius = at.radius if at.radius is not None else self.settings.place_radius
            step = at.step if at.step is not None else self.settings.place_step
            for _, x, y in _grid(hint, radius, step):
                centre = Location(x, y)
                yield centre, self._region_rotation(occ, cutout, centre)
            return
        if isinstance(at, Polar) and at.angle is None:
            r = float(_coord(self, occ, at.radius, "x")) if not isinstance(at.radius, (int, float)) \
                else float(at.radius)
            for k in range(720):
                b = ((k + 1) // 2 * (1 if k % 2 else -1)) * 0.5
                centre = polar_point(self.centre, b % 360.0, r)
                yield centre, self._region_rotation(occ, cutout, centre)
            return
        if isinstance(at, Polar) and at.radius is None:
            hi = max(box.width, box.height) / 2.0
            for r in out_from(hi / 2.0, 0.0, hi):
                centre = polar_point(self.centre, bearing(at.angle), r)
                yield centre, self._region_rotation(occ, cutout, centre)
            return
        axis = at.free_axis if isinstance(at, Centre) else ("x" if at.x is None else "y")
        held = at.y if axis == "x" else at.x
        fixed = _coord(self, occ, held, "y" if axis == "x" else "x")
        lo, hi = (box.left, box.right) if axis == "x" else (box.top, box.bottom)
        for v in out_from((lo + hi) / 2.0, lo, hi):
            centre = Location(v, fixed) if axis == "x" else Location(fixed, v)
            yield centre, self._region_rotation(occ, cutout, centre)

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
        return "is wholly off the board" if self._off_board(path) else None

    def _off_board(self, path) -> bool:
        """Whether a region shares no area with the board: clear of its
        outline, or wholly inside one of its holes. Judged by area, not by the
        region's corners - a strip across the board has every corner past an
        edge and covers the board between them."""
        from .geometry import point_in_polygon, point_segment_distance, polys_overlap
        if self._fit:
            return False                        # a fit frame grows to hold what is placed
        shape = self._shaped()
        loop = Cutouts([path]).loops[0]
        if not polys_overlap(loop, shape.loops[0]):
            return True

        def within(hole):
            def on(q):
                return any(point_segment_distance(q, hole[k], hole[(k + 1) % len(hole)]) <= 1e-9
                           for k in range(len(hole)))
            mids = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(loop, tuple(loop[1:]) + tuple(loop[:1]))]
            return all(point_in_polygon(q, hole) or on(q) for q in tuple(loop) + tuple(mids))
        return any(within(h) for h in shape.loops[1:])

    def _points_off_board(self, path) -> tuple:
        """(points outside the board, points in all) for a region's boundary.

        A region is used exactly as declared: the part hanging off the board
        can refuse nothing, because `Occupancy.legal` rejects a part for
        crossing the keep-in before it ever tests a reservation, and KiCad
        clips a zone to Edge.Cuts itself. The count is reported so a region
        that is mostly off the board is visible; a point count, not an area,
        because a region whose boundary IS the outline has the board's own
        area and any area measure reads zero."""
        loop = Cutouts([path]).loops[0]
        if self._fit:
            return 0, len(loop)                 # a fit frame has no outline yet to be off
        shape = self._shaped()
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
                plan.findings.append(Finding("fixed", "%s (cutout): %s" % (name, why)))
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
                    plan.findings.append(Finding(
                        "copper",
                        "%s %s crosses keepout %r (%s): a %s goes exactly where it is put, so move it, "
                        "reshape it, or name its net in the keepout's allow="
                        % (word, op.net, k.name, k.why, word)))

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
            plan.findings.append(Finding("setup", "web %.2f mm round %s is under the %.2f mm minimum"
                                 % (gap, self._cutout_label(which), self.web)))

    def _check_pitch(self, plan: "Plan"):
        """A net class whose clearance does not fit its pads' pitch. A track
        of the class's width leaves a pad straight out from the part's body,
        along the part's nearer axis, centred on the pad; its lane is the
        distance from that track to the part's other pads of other nets. A
        pad with another pad straight ahead of it (inside a grid) leaves some
        other way and is not measured. Under the clearance, the router cannot
        escape the pad. One finding per part, on its tightest lane."""
        g = self.geometry
        reach = max((c.clearance for c in g.netclasses.values()), default=0.0)
        for fp in g.footprints:
            pads = [p for p in fp.pads if p.net and p.outlines]
            worst, short = None, 0
            for p in pads:
                nc = g.netclass(p.net)
                lane_of = _escape_lane(fp, p, pads, nc.track_width, reach)
                if lane_of is None:
                    continue
                for q in pads:
                    if q.net == p.net or not (p.layers & q.layers):
                        continue
                    need = g.clearance(p.net, q.net)
                    lane = lane_of(q)
                    if lane is None or lane >= need - 1e-6:
                        continue
                    if poly_distance(p.outlines[0], q.outlines[0]) <= 0.0:
                        continue                # pads that touch: the footprint's fault, not the class's
                    short += 1
                    if worst is None or lane - need < worst[0] - worst[1]:
                        worst = (lane, need, p, q, nc)
            if worst is None:
                continue
            lane, need, p, q, nc = worst
            plan.findings.append(Finding(
                "setup",
                "%s: net class %r (clearance %.2f mm, track %.2f mm) does not fit the pads' pitch: the lane out "
                "of pad %s past pad %s is %.3f mm for a %.2f mm clearance (%d lane(s) short), so the router "
                "cannot escape them; a clearance of %.2f mm or less fits"
                % (fp.ref, nc.name, nc.clearance, nc.track_width, p.number, q.number, lane, need, short,
                   math.floor(lane * 100 + 1e-6) / 100)))

    def _cutout_label(self, n: int) -> str:
        """Which hole a measurement was taken on. Named cutouts come first,
        in declaration order, so the index names one directly."""
        order = list(self._named_cutouts)
        return "cutout %r" % order[n] if 0 <= n < len(order) else "an unnamed cutout"

    def keepout(self, shape, name: str, *, at=None, rotation=None, margin: float | None = None,
                excludes=None, allow=(), layers=None, max_height: float | None = None,
                why: str = "") -> KeepoutIntent:
        """A region that forbids. By default nothing may sit, fill, route, via
        or pad there on any copper layer the board has; `excludes` narrows
        what and `layers` narrows where. `allow` names the parts that may sit
        inside and the nets that may run through, which are different things:
        an antenna's clearance holds its own matching network, and naming
        those parts' nets would admit every part that shares one.
        `max_height` (a parts keepout) admits every part no taller, by its
        `Pm.Height`; a part with none counts as taller. `rotation=` is a
        number, or `Turned(part, degrees)` to turn with a part already on
        the board, the same as a place() does.

        `shape` may instead be a Part or a Cell already on the board (no
        `at=` or `rotation=`, so `margin=` in their place): the region is
        that item's own drawn envelope grown by `margin` (default 0), and it
        moves and turns with the item, settled once the item is - a shape
        from an item, not a hand-built polygon.

        `shape` may be `Inside(Part(...), margin)`: the box inside that
        part's pads (`Inside`), settled the same way."""
        inside = shape if isinstance(shape, Inside) else None
        region_of = inside.part if inside is not None else shape if isinstance(shape, (Part, Cell)) else None
        if region_of is not None:
            if at is not None:
                raise ValueError("keepout %r: an item shapes its own region; give margin=, not at=" % name)
            if rotation is not None:
                raise ValueError("keepout %r: an item's region turns with it; give no rotation=" % name)
        if inside is not None:
            if margin is not None:
                raise ValueError("keepout %r: Inside carries its own margin; give Inside(part, margin=)" % name)
            shape = self._inside_shape(inside, name)
        elif region_of is not None:
            m = 0.0 if margin is None else float(margin)
            if m < 0:
                raise ValueError("keepout %r: margin is 0 or more, not %r" % (name, margin))
            shape = self._item_envelope_shape(region_of, m, name)
        elif margin is not None:
            raise ValueError("keepout %r: margin= grows an item's own envelope; give a shape and at= instead"
                             % name)
        if max_height is not None and "parts" not in (excludes if excludes is not None else ("parts",)):
            raise ValueError("keepout %r: max_height admits parts by height, so it is for a keepout that "
                             "excludes parts" % name)
        if name in self._keepouts:
            raise ValueError("there is already a keepout named %r on this board" % name)
        area = getattr(shape, "area", None)
        if area is not None and not (area() if callable(area) else area) > 1e-9:
            # KiCad reads such a rule area as malformed, and it keeps nothing out
            raise ValueError("keepout %r: its shape has no area (its points lie on a line)" % name)
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
                    None if layers is None else tuple(CopperLayer.of(l) for l in layers), why,
                    None if max_height is None else float(max_height), region_of)
        self._keepouts[name] = k
        if region_of is not None:
            needs = frozenset([self._pad_ref(region_of)[0]])   # waits for the item, like a keepout at its pad
        else:
            # rotation=Turned(part, degrees) waits for that part too, the same as a place() does
            turned_by = [rotation.part] if isinstance(rotation, Turned) else []
            needs = frozenset(self._pad_ref(r)[0] for r in _refs_in([at] + turned_by))
        settled = not self._cutout_free(k)
        if self._fit and not settled:
            raise ValueError("keepout %r: a fit frame has no room for it to slide in until its content is placed; "
                             "give it a place" % name)
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
                plan.findings.append(Finding(
                    "setup",
                    "keepout %s declares %s, which this %d-layer board does not have: recorded "
                    "in its name, and honoured by a board that has it"
                    % (k.name, ", ".join(l.value for l in lost), len(self.geometry.layers))))
        for r in self.geometry.rule_areas:
            if r.missing:
                plan.findings.append(Finding(
                    "setup",
                    "%s from the %s cell declares %s, which this board does not have either"
                    % (r.base, r.cell or "board", ", ".join(l.value for l in r.missing))))

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
            if isinstance(h.at, Location) and isinstance(h.at.x, (int, float)) and isinstance(h.at.y, (int, float)) \
                    and not isinstance(h.rotation, Turned):             # a Turned rotation waits for its part
                named_paths.append(h.shape.path_at(h.at, h.rotation or 0.0))   # absolute: settled now
                self._cutout_loop_of[h.name] = len(named_paths)                # loop 0 is the board
                self._settled_cutouts[h.name] = PlacedCutout(
                    h.name, tuple(named_paths[-1]), h.at, float(h.rotation or 0.0))
            else:
                # rotation=Turned(part, degrees) waits for that part too, the same as a place() does
                turned_by = [h.rotation.part] if isinstance(h.rotation, Turned) else []
                needs = frozenset(self._pad_ref(r)[0] for r in _refs_in([h.at] + turned_by))
                # a decided place goes down in declaration order with the firm items; one with a
                # freedom waits until every decided thing is down, then takes the room that is left
                settled = not self._cutout_free(h)
                self._intents.append(CutoutIntent("cutout %s" % h.name, h, h.why, len(self._intents),
                                                  needs,
                                                  Freedom.FIXED if settled else Freedom.SEARCHED))
        self._named_cutouts = named
        return tuple(named_paths) + tuple(raw)

    def size(self, width: float | None = None, height: float | None = None, chamfer: float = 0.0, radius: float = 0.0,
             holes=(), web: float = 0.0, draw: bool | None = None, *, fit: bool | Axis = False,
             margin: float | None = None):
        """The board outline: a rectangle at the origin, chamfered or rounded.
        `holes` are cutouts in it - a slot for a cable, a window - each a
        closed path of straight legs and arcs, the same as any other board's.
        `fit=True` (a fragment's frame, draw=False): no numbers - the frame is
        the box round what is placed, plus `margin` (default the keep-in).
        `fit=Axis.X` fits that one axis to the content and takes the other's
        number as declared (`height=` for Axis.X, `width=` for Axis.Y) -
        origin at 0 on that axis, the same as a sized board's."""
        if fit:
            if draw:
                raise ValueError("fit=True sizes a fragment's frame, never drawn; a board's outline is a mechanical fact")
            if margin is not None and margin < 0:
                raise ValueError("a fit frame's margin is 0 or more, not %r" % (margin,))
            axis = fit if isinstance(fit, Axis) else None
            if axis is Axis.X:
                if width is not None:
                    raise ValueError("fit=Axis.X fits the width to the content; give height=, not width=")
                if height is None or height <= 0:
                    raise ValueError("fit=Axis.X takes the declared height=, a positive number")
            elif axis is Axis.Y:
                if height is not None:
                    raise ValueError("fit=Axis.Y fits the height to the content; give width=, not height=")
                if width is None or width <= 0:
                    raise ValueError("fit=Axis.Y takes the declared width=, a positive number")
            elif width is not None or height is not None:
                raise ValueError("fit=True fits both axes to the content; width= and height= have nothing to size")
            self._fit, self._fit_axis = True, axis
            self._fit_margin = self.keep_in if margin is None else float(margin)
            if axis is Axis.X:
                self.height = float(height)
            elif axis is Axis.Y:
                self.width = float(width)
            self._outline, self._shape, self._cached_outline = None, None, None
            self._cutouts = Cutouts()
            self._chamfer, self._radius = chamfer, radius
            self._sized, self._draw_outline = True, False
            return
        self._fit, self._fit_axis = False, None
        draw = True if draw is None else draw
        if width is None or height is None or width <= 0 or height <= 0:
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
        self._fit = False
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
        self._fit = False
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

    def edge(self, facing, within: float = 45.0, outermost: bool = False) -> Run:
        """The one stretch of the board's edge facing that way. Several (or
        none) is a script question, not a guess: narrow `within`, take the
        one wanted from edges(), or say `outermost=True` for the one whose
        middle lies furthest out that way - a tab or an arm's tip beyond the
        shoulders beside it. Two level at the furthest is still a question."""
        self._refuse_on_fit("board.edge()")
        runs = self.edges(facing, within)
        if not runs:
            raise ValueError("no part of this board's edge faces %r within %g degrees" % (facing, within))
        if len(runs) > 1 and outermost:
            ux, uy = bearing_vector(bearing(facing))
            out = [(r.at(r.length / 2.0)[0], r) for r in runs]
            reach = [(round(p.x * ux + p.y * uy, 6), r) for p, r in out]
            far = max(d for d, _ in reach)
            level = [r for d, r in reach if d >= far - 1e-6]
            if len(level) == 1:
                return level[0]
            raise ValueError("%d stretches of this board's edge facing %r lie level at the furthest out "
                             "(%s): pick from board.edges()" % (len(level), facing,
                                                               ", ".join("%.2f mm" % r.length for r in level)))
        if len(runs) == 1:
            return runs[0]
        raise ValueError("%d stretches of this board's edge face %r within %g degrees (%s): "
                         "narrow within=, say outermost=True, or pick from board.edges()"
                         % (len(runs), facing, within, ", ".join("%.2f mm" % r.length for r in runs)))

    def _shaped(self) -> Outline:
        """This board as an outline, whatever it was declared as: what runs
        are read off. A disc's rim is its polygon; a rectangle's four sides
        are its own."""
        if self._fit and self._outline is None:
            self._refuse_on_fit("the board's outline")
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
        self._refuse_on_fit("board.centre")
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
        list of (Part, pad) pairs, each placed on that pin's axis `gap` out,
        body outward of its pad; the default gap is the two courtyards
        touching. The pad is the anchor's, a net name (the first pad carrying
        it) or an int pad number; the satellite sits by its own pad on that
        pad's net. Place the returned block like a part; it is laid out from
        the anchor's real pads at every candidate."""
        a = self.geometry.footprint(anchor)
        sats, pins, named = [], [], []
        for part, key in satellites:
            fp = self.geometry.footprint(part)
            kind, value = pad_key(key)
            if kind == "number":
                pad = a.pad(key)
                name = pad.net
            else:
                name = self.geometry.require_net(key)
                pad = a.pad(name)        # the anchor must carry the net
            fp.pad(name)                 # and so must the satellite
            sats.append((fp, name))
            pins.append(pad.number)
            named.append(kind == "number")
        return BlockSpec(a, tuple(sats), gap, tuple(pins), tuple(named))

    # ------------------------------------------------------------ Beside
    def _beside_spec(self, key: str, geom, kind: str, at: Beside) -> "_BesideSpec":
        """Resolve a `Beside(...)` against the generated board: validated
        now, settled once `at.item` is placed. `align`, when it names pads,
        is normalised to the placed item's own pad key."""
        if kind == "block":
            raise TypeError("%s: a block is placed by its anchor's position, not Beside" % key)
        if isinstance(at.item, KeepoutIntent):
            item_kind = "keepout"
        elif isinstance(at.item, (Part, Cell)):
            item_kind = "item"
            item_geom = self._item(at.item)[0]          # a real part or cell, checked now
        else:
            raise TypeError("%s: Beside's item is a Part, a Cell or a keepout (what board.keepout(...) "
                            "returns), not %r" % (key, at.item))
        align = at.align
        if align is None:
            norm = ("along", Along.MID)
        elif isinstance(align, Along):
            norm = ("along", align)
        elif isinstance(align, PadRef):
            if item_kind == "keepout":
                raise TypeError("%s: a keepout has no pads to align on; align=Along.START/MID/END, or "
                                "leave align= out" % key)
            if kind != "part":
                raise TypeError("%s: align=PadRef needs the placed item's own pad; a %s has none - give "
                                "align=(own_pad, their_pad)" % (key, kind))
            # any firmly placed part's pad: the item's own, or a third part's (a coil beside a
            # capacitor, level with the driver's pin); a part still searched then is refused when
            # this is placed, as any firm placement referring to it is
            their = self.geometry.pad(align.part, align.key)
            if not their.net:
                raise ValueError("%s: Beside's align pad %s has no net to line up on; give "
                                 "align=(own_pad, %s) naming an own pad" % (key, align, align))
            owns = geom.pads_on(their.net)
            if not owns:
                raise ValueError("%s carries no pad on %s, %s's net; give align=(own_pad, %s) naming one"
                                 % (key, their.net, align.part, align))
            number = owns[0].number
            norm = ("pads", int(number) if number.isdigit() else number, align)
        elif isinstance(align, tuple):
            if len(align) != 2 or not isinstance(align[1], (PadRef, Past)):
                raise TypeError("%s: Beside's align pair is (own_pad, PadRef(item, pad)) or (own_pad, "
                                "Past(pads, edge)), not %r" % (key, align))
            own_key, their = align
            if kind != "part":
                raise TypeError("%s: align=(own_pad, their_pad) needs the placed item's own pad; a %s has "
                                "none - align=Along.START/MID/END instead" % (key, kind))
            geom.pad(own_key)                          # a real pad of this part, checked now
            if isinstance(their, Past):
                self._check_beside_past(key, at.side, their)
                norm = ("past", own_key, their)
            else:
                self.geometry.pad(their.part, their.key)    # and a real pad of the item named
                norm = ("pads", own_key, their)
        else:
            raise TypeError("%s: Beside's align is a PadRef, an (own_pad, their_pad) pair, Along.START/MID/END, "
                            "or nothing (Along.MID), not %r" % (key, align))
        return _BesideSpec(at.item, at.side, norm, at.gap)

    def _check_beside_past(self, key: str, side: Edge, p: Past):
        """A Past in Beside's align: over pads only, since a placement is
        decided before any copper is planned; no `across=`, since `side`
        decides that axis; and an edge on the other axis."""
        for it in p.items:
            if isinstance(it, CopperIntent):
                raise TypeError("%s: a placement is decided before copper is planned; Past in Beside's align "
                                "takes pads, not %s" % (key, it.key))
            self._pad_ref(it)                           # a real pad, checked now
        if p.across is not None:
            raise TypeError("%s: Beside's side decides where the part stands along the pads; Past in its "
                            "align takes no across=" % key)
        upright = side in (Edge.EAST, Edge.WEST)
        if (p.edge in (Edge.EAST, Edge.WEST)) == upright:
            raise ValueError("%s: Beside on the %s side decides the part's %s; the Past in its align decides "
                             "the other axis, so its edge is %s, not %s" % (
                key, side.name, "x" if upright else "y",
                "NORTH or SOUTH" if upright else "EAST or WEST", p.edge.name))
        if p.lane is not None:
            self.geometry.require_net(p.lane)

    def _placed_envelope_box(self, occ: Occupancy, item) -> Box:
        """The envelope (courtyard, physical or their union, whichever
        `[place] envelope` claims) a placed Part or Cell draws, read from
        its committed geometry - its real position, not a measurement at
        the origin."""
        geom, _, _ = self._item(item)
        g = occ._geometry(geom)
        return Box.union([s.box for s in g.shapes if s.kind != "npth"])

    def _beside_gap(self, spec: "_BesideSpec", new_item) -> float:
        """Beside's own gap: what the script gave, or 0.0, floored to the
        envelope's own - the row's rule (silk clearance, component spacing,
        the nets' clearance) under a physical envelope, unchanged under a
        courtyard one - exactly as row(of=)'s gap= is: a spacing is the
        envelope's own unless a named rule asks for more."""
        items = [new_item] if isinstance(spec.item, KeepoutIntent) else [spec.item, new_item]
        return self._row_gap(items, 0.0 if spec.gap is None else float(spec.gap))

    def _beside_placement(self, occ: Occupancy, plan: "Plan", i: PlaceIntent) -> Placement:
        """Where `Beside(...)` puts the item: its own drawn envelope `gap`
        off `item`'s, on `side`, aligned across it."""
        b = i.beside
        if isinstance(b.item, KeepoutIntent):
            pk = plan.keepouts.get(b.item.keepout.name)
            if pk is None:
                raise ValueError("%s: keepout %r has no place, so there is nothing to stand beside"
                                 % (i.key, b.item.keepout.name))
            item_box = Box.of_points(pk.poly)
        else:
            item_box = self._placed_envelope_box(occ, b.item)
        own_box = self.envelope(i.item, i.rotation, i.face)
        gap = self._beside_gap(b, i.item)
        ox = oy = None
        if b.side is Edge.EAST:
            ox = item_box.right + gap - own_box.left
        elif b.side is Edge.WEST:
            ox = item_box.left - gap - own_box.right
        elif b.side is Edge.SOUTH:
            oy = item_box.bottom + gap - own_box.top
        else:
            oy = item_box.top - gap - own_box.bottom
        align_kind = b.align[0]
        if align_kind == "along":
            # flush, as OnEdge and row(of=) are: START puts the part's own
            # envelope start at the item's side start, END its end, MID
            # centres - never the part's body centre on the item's corner.
            along = b.align[1]
            if b.side in (Edge.EAST, Edge.WEST):
                lo, hi = item_box.top, item_box.bottom
                start = lo + along.fraction * (hi - lo - (own_box.bottom - own_box.top))
                oy = start - own_box.top
            else:
                lo, hi = item_box.left, item_box.right
                start = lo + along.fraction * (hi - lo - (own_box.right - own_box.left))
                ox = start - own_box.left
        elif align_kind == "past":
            # the own pad's facing edge the clearance, or a lane, past the pads' edge
            own_key, past = b.align[1], b.align[2]
            bare = self._bare_occupancy()
            g = bare._geometry(i.item)
            t = bare._transform(g, Placement(Location(0.0, 0.0), i.rotation, i.face))
            own_pad = i.item.pad(own_key)
            own = Box.union([transform_box(s.box, t) for s in g.shapes
                             if s.kind in ("pad", "through") and s.label == own_pad.number])
            shapes = [sh for ref in past.items for sh in _pad_shapes(self, occ, ref)]
            box = Box.union([sh.box for sh in shapes])
            off = _lane_distance(self, own_pad.net, [sh.net for sh in shapes], past.lane, past.width)
            if past.edge is Edge.EAST:
                ox = box.right + off - own.left
            elif past.edge is Edge.WEST:
                ox = box.left - off - own.right
            elif past.edge is Edge.SOUTH:
                oy = box.bottom + off - own.top
            else:
                oy = box.top - off - own.bottom
        else:
            own_key, their = b.align[1], b.align[2]
            anchored = pad_anchored_placement(self._bare_occupancy(), i.item, own_key, Location(0.0, 0.0),
                                              i.rotation, i.face)
            own_pad = Location(-anchored.location.x, -anchored.location.y)
            their_loc = _locate(self, occ, their)
            if b.side in (Edge.EAST, Edge.WEST):
                oy = their_loc.y - own_pad.y
            else:
                ox = their_loc.x - own_pad.x
        return Placement(Location(round(ox, 6), round(oy, 6)), i.rotation, i.face)

    def _row_of_placement(self, occ: Occupancy, i: PlaceIntent, along: float) -> Placement:
        """Where one item of a `row(..., of=)` lands: its own drawn envelope
        `i.clearance` (the row's line, already worked out) off `of`'s, on
        `i.edge`; its body centre at `along` down the row, as an edge row's
        does."""
        of_box = self._placed_envelope_box(occ, i.row_of)
        own_box = self.envelope(i.item, i.rotation, i.face)
        own_body = self.extent(i.item, i.rotation, i.face)
        ox = oy = None
        if i.edge is Edge.EAST:
            ox = of_box.right + i.clearance - own_box.left
        elif i.edge is Edge.WEST:
            ox = of_box.left - i.clearance - own_box.right
        elif i.edge is Edge.SOUTH:
            oy = of_box.bottom + i.clearance - own_box.top
        else:
            oy = of_box.top - i.clearance - own_box.bottom
        if i.edge in (Edge.EAST, Edge.WEST):
            oy = along - own_body.center.y
        else:
            ox = along - own_body.center.x
        return Placement(Location(round(ox, 6), round(oy, 6)), i.rotation, i.face)

    # ------------------------------------------------------------ placement
    def place(self, item, at=None, *, rotation: float | None = None, face: Face = Face.FRONT,
              radius: float | None = None, step: float | None = None, rotations=(),
              priority: Priority | None = None, required: bool = False, why: str = "",
              _standoff: float | None = None, _row_of: object = None) -> PlaceIntent:
        """Declare where an item goes: `at=` a place, whose kind says how
        much freedom is left.

        Location(x, y)          the origin (a cell: its box centre)        -> FIXED, no freedom
        Centre(x, y)            the body box centre; each axis a number or
                                a reference                                -> FIXED, no freedom
        Location(x, None)       one axis pinned, the other free: the item
        Centre(None, y)         slides along the line, from across what it
                                connects to, else sharing it evenly     -> searched, one freedom
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
        try:
            face = Face(face)
        except ValueError:
            raise TypeError("%s: face is Face.FRONT/BACK or \"front\"/\"back\", not %r" % (key, face)) from None
        if any(i.key == key for i in self._intents):
            raise ValueError("%s is already placed; one declaration per item" % key)
        center = edge = along = near = about = run = None
        rim = angle = radius_at = None
        outward = False
        overhang = 0.0
        pin_x = pin_y = None
        pinned = ""
        pin = None
        beside = None
        cell_pin = None
        if isinstance(at, Pin) and kind == "cell" and isinstance(at.key, Part):
            # a member's footprint origin, not a pad (a winding's arc centre): number None
            member = next((fp for fp in geom.members if fp.inst == at.key.inst), None)
            if member is None:
                raise TypeError("%s: Pin's %r is not one of cell %s's members" % (key, at.key, key))
            cell_pin, center, at = (member.ref, None, 0.0, 0.0), (at.x, at.y), None
        elif isinstance(at, Pin) and kind == "cell" and not isinstance(at.key, (CellPadRef, PadRef)):
            raise TypeError("%s: a cell has no pad of its own; Pin's key is a CellPadRef, a PadRef on "
                            "one of its members, or a member Part (its footprint origin), not %r" % (key, at.key))
        if at is None:
            pass
        elif kind == "cell" and isinstance(at, Pin):
            owner, number, dx, dy = self._pad_ref(at.key)
            if owner not in {fp.ref for fp in geom.members}:
                raise TypeError("%s: Pin's %r is not a pad of one of cell %s's members" % (key, at.key, key))
            if self._pad_land(at.key) is not None:
                raise ValueError("%s: a cell placed by a member's pad lands that pad's centre; land= names one "
                                 "land for a point on a placed pad, not for Pin's key" % key)
            lx, ly = getattr(at.key, "lx", 0.0), getattr(at.key, "ly", 0.0)
            pin_tuple = (owner, number, dx, dy, lx, ly) if (lx or ly) else (owner, number, dx, dy)
            cell_pin, center, at = pin_tuple, (at.x, at.y), None
        elif isinstance(at, Pin):
            if kind != "part":
                what = "a block is placed by its anchor's position, not a pad" if kind == "block" else \
                    "a cell has no pad of its own"
                raise TypeError("%s: a Pin places a part by its pad; %s" % (key, what))
            geom.pad(at.key)                                # a real pad of this part, checked now
            pin, center, at = at.key, (at.x, at.y), None
        elif isinstance(at, Beside):
            beside = self._beside_spec(key, geom, kind, at)
            at = None
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
            if _row_of is None:
                self._refuse_on_fit("%s on the frame's %s edge" % (key, Edge(at.edge).value))
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
            # about= a Location, an (x, y) pair or None resolves now, as it always did; a
            # reference (a part not yet placed, a pad) resolves when this item is, through
            # _locate - center holds the Polar itself, and radius_at/about the raw reference,
            # so a declaration that never used about= digests exactly as before
            about_now = at.about is None or isinstance(at.about, (Location, tuple))
            if at.radius is not None and at.angle is not None:
                if about_now:
                    about = self.centre if at.about is None else _as_point(at.about)
                    center, about, at = polar_point(about, at.angle, at.radius), about, None
                else:
                    center, about, at = at, at.about, None
            else:
                about = (self.centre if at.about is None else _as_point(at.about)) if about_now else at.about
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
        decided = (at is not None or center is not None or beside is not None
                   or ((edge is not None or run is not None) and along is not None)
                   or (rim is not None and angle is not None))
        freedom = Freedom.SEARCHED if not decided else \
            Freedom.FIXED if (at is not None or center is not None or beside is not None) else Freedom.EDGE
        if decided and priority is not None:
            raise ValueError("%s: the declaration decided this position, so the item goes down before anything "
                             "searched and priority=%s has nothing to order; drop the priority, or drop the "
                             "position to have it searched" % (key, priority.value))
        priority = priority or Priority.DEFAULT
        faces_note = ""
        turned = rotation if isinstance(rotation, Turned) else None
        if turned is not None and rotations:
            raise ValueError("%s: rotation=Turned(...) settles the rotation; rotations= would override it" % key)
        if turned is not None:
            rotation = float(turned.degrees)        # provisional: the ranking measures by it until the part is down
        rotation_given = rotation is not None
        if rotation is None:
            if isinstance(run, CutoutEdge):
                rotation, faces_note = None, ""      # the stretch is not known yet: turned when it is
            elif run is not None and isinstance(along, (int, float)):
                rotation, faces_note = self.outward_rotation(item, run.at(along)[1])
            elif run is not None and along is not None:
                rotation, faces_note = None, ""      # along is a reference: not known until it is placed
            elif rim is not None and angle is not None:
                rotation, faces_note = self.outward_rotation(item, angle + (180.0 if rim == "bore" else 0.0))
            elif edge is not None and along is None:
                rotation, faces_note = self.outward_rotation(item, edge)
            else:
                rotation, faces_note = 0.0, ""
        if kind == "cell" and at is not None and center is None:
            center, at = at, None
        needs = {self._pad_ref(ref)[0] for ref in _refs_in([at, center, along, pin_x, pin_y, near, about])}   # a real pad, placed before this
        if isinstance(at, OnEdge) and isinstance(at.edge, CutoutEdge):
            needs.add(cutout_token(at.edge.name))   # the hole is cut before anything is put against it
        if isinstance(along, _RowSlot):
            needs |= along.row.needs
        if turned is not None:
            needs.add(self._pad_ref(turned.part)[0])   # turned by it: placed after it
        if beside is not None:
            needs.add(cutout_token(beside.item.keepout.name) if isinstance(beside.item, KeepoutIntent)
                      else self._pad_ref(beside.item)[0])
            if beside.align[0] == "pads":
                needs.add(self._pad_ref(beside.align[2])[0])
            elif beside.align[0] == "past":
                needs |= {self._pad_ref(ref)[0] for ref in beside.align[2].items}
        if _row_of is not None:
            needs.add(self._pad_ref(_row_of)[0])
        standoff = _standoff if _standoff is not None else (-float(overhang) if overhang else self.keep_in)
        turn = None if rotation is None else float(rotation)   # None: settled when the stretch is known
        intent = PlaceIntent(key, geom, kind, priority, turn, face, at, center, edge, along,
                             standoff, near, radius, step, tuple(rotations), why, len(self._intents), frozenset(needs),
                             pin_x, pin_y, source, faces_note, pinned, pin, rim, angle, radius_at, outward, about, run,
                             freedom, required, rotation_given, turned=turned, beside=beside, row_of=_row_of,
                             cell_pin=cell_pin, line=_script_line())
        self._intents.append(intent)
        return intent

    def row(self, items, edge: Edge, *, of=None, gap: float | None = None, start=None, align=Along.START,
            rotation: float | None = None, line=Line.CENTRE, behind: Row | None = None, inboard: float | None = None,
            overhang: float = 0.0, pitch: float | None = None,
            centre=None, end=None, before: Row | None = None, after: Row | None = None, why: str = "") -> Row:
        """Items down `edge` in order, `gap` apart (default: courtyards
        touching), with their outward sides
        out (`rotation=`, one value or one per item, overrides that turn for
        parts with no outward side). The row's outer line is the board's
        keep-in, or `inboard` (default `gap`) behind the inner line of the
        row it is `behind=`; `overhang=` puts a face that far past the edge. Across the row the items align
        on one line: `line=Line.CENTRE` (the default) puts their centres on
        the line the deepest item's centre falls on; `Line.OUTER` puts every
        outward reach on the outer line (connectors edge-hard); `Line.INNER`
        aligns the inboard edges. A row butted `before=` or `after=`
        another takes that row's line. Where the row sits along the edge:
        `start=` a number (default: the keep-in) or a reference;
        `align=Along.MID` (or "centre"/"center") on the board, `Along.END`
        flush with the far keep-in; `centre=` or `end=` a reference (a
        pad's X()/Y(), a Mid); `before=` or `after=` another row, one gap
        away. A row placed by a reference is measured when its items are
        placed.

        `of=Part(...)`/`Cell(...)` runs the row along `edge` of that item's
        drawn envelope instead of the board's: `gap` (default the envelope's
        own) is both the row's own gap and how far its near line stands off
        `of`, and `align=Along.START/MID/END` is where along `of`'s side the
        row sits (default START). `centre=PadRef(...)` instead puts the
        row's middle on that pad's centre line (a pad of `of` or of any part
        placed firmly by then). `pitch=` spaces neighbouring items' centres
        that far apart, in place of `gap=` between their envelopes; the row
        still stands the envelope gap off `of`, and a pitch that brings two
        envelopes closer than that gap is refused. It waits for `of` to be
        placed, and accepts a fit frame, unlike a row on the board's own
        edge; `start=`, `end=`, `before=`, `after=`, `behind=` and
        `inboard=` are not said relative to a part, so they are refused
        together with it. Returns the Row."""
        align = _as_align(align, "a row's align")
        if pitch is not None:
            if of is None:
                raise ValueError("pitch= spaces a row of= a part; a row on the board's edge is spaced by gap=")
            if gap is not None:
                raise ValueError("a row is spaced one way: pitch= between centres or gap= between envelopes, "
                                 "not both")
            if float(pitch) <= 0:
                raise ValueError("a row's pitch is a distance, more than 0, not %r" % (pitch,))
        if of is not None:
            given = [n for n, v in (("start", start), ("end", end),
                                    ("before", before), ("after", after), ("behind", behind),
                                    ("inboard", inboard)) if v is not None]
            if given:
                raise ValueError("a row of=%r is placed along its side; %s not with it"
                                 % (of, " and ".join(given)))
            if not isinstance(edge, Edge):
                raise TypeError("a row of= a part is on one of its Edge.N/S/E/W sides, not %r" % (edge,))
            if centre is not None:
                if not isinstance(centre, (PadRef, CellPadRef)):
                    raise TypeError("a row of=%r is centred on a pad: centre= takes a PadRef, not %r" % (of, centre))
                if align is not Along.START:
                    raise ValueError("a row of=%r is placed one way: centre= a pad or align=Along.START/MID/END"
                                     % (of,))
            self._item(of)                        # a real part or cell, checked now
        elif isinstance(edge, Edge):
            self._refuse_on_fit("a row on the frame's %s edge" % edge.value)
        gap = self._row_gap(list(items) + ([of] if of is not None else []), 0.0 if gap is None else gap)
        if isinstance(edge, Run):
            return self._row_on_run(items, edge, gap=gap, start=start, align=align, rotation=rotation,
                                    overhang=overhang, why=why, unsupported=[
                                        ("line", line if line != "centre" else None), ("behind", behind),
                                        ("inboard", inboard), ("centre", centre), ("end", end),
                                        ("before", before), ("after", after)])
        if of is None and isinstance(self._shape, Disc):
            raise ValueError("a disc has no edges: board.ring(items, radius=) is the row of a round board, "
                             "or board.row(items, board.edge(facing=)) puts them along a stretch of the rim")
        if of is None and isinstance(self._shape, Outline):
            raise ValueError("a shaped board's sides are chosen, not named: "
                             "board.row(items, board.edge(facing=Edge.NORTH))")
        rots = [self.outward_rotation(it, edge)[0] for it in items] if rotation is None else \
            ([float(r) for r in rotation] if isinstance(rotation, (list, tuple)) else [float(rotation)] * len(items))
        if of is not None:
            clr = -float(overhang) if overhang else gap
        elif behind is not None:
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
            claim = self.claim(item, r)      # spaced by what they claim
            # of=: placed by the envelope box (_row_of_placement, as Beside is), so the
            # line must read the same measure, or items with different courtyard
            # margins would not share it. On the board's own edge the line is still
            # how far the item physically reaches, not its assembly margin.
            deep = self.envelope(item, r) if of is not None else self.reach(item, r)
            keys.append(key)
            alongs.append(claim.height if along_axis else claim.width)
            depths.append(deep.width if along_axis else deep.height)
        if pitch is not None:
            self._check_row_pitch(items, keys, rots, along_axis, float(pitch), gap)
        row = Row(edge, clr, gap, None, keys, alongs, max(depths), pitch=pitch)
        if of is not None:
            row.anchor = ("of", (of, align)) if centre is None else ("of", (of, align, centre))
            row.needs = frozenset([self._pad_ref(of)[0]] + ([self._pad_ref(centre)[0]] if centre is not None else []))
        else:
            by_ref = start is not None and not isinstance(start, (int, float))
            anchors = [("centre", centre), ("end", end), ("before", before), ("after", after), ("start", start if by_ref else None)]
            given = [(k, v) for k, v in anchors if v is not None]
            if len(given) > 1 or (given and ((start is not None and not by_ref) or align is not Along.START)):
                raise ValueError("a row is placed one way: start=, align=Along.MID/END, centre=, end=, before= or after=")
            if given:
                row.anchor = given[0]
                kind, value = given[0]
                if kind in ("before", "after"):
                    row.needs = frozenset(value.needs) | frozenset(
                        fp.ref for it in value.items for fp in (self._item(it)[0].members if self._item(it)[2] == "cell" else (self._item(it)[0],)))
                else:
                    row.needs = frozenset(self._pad_ref(ref)[0] for ref in _refs_in([value]))
            elif align is Along.MID:
                if self._sized:                     # the script's own size, not the generator's frame
                    row.begin(row.centre_of(self._outline))
                else:
                    row.anchor = ("outline", None)
            elif align is Along.END:
                if self._sized:
                    row.begin(row.end_of(self._outline, self.keep_in))
                else:
                    row.anchor = ("outline_end", None)
            else:
                row.begin(float(self.keep_in if start is None else start))
        row.items = list(items)
        try:
            line = Line(line)
        except ValueError:
            raise ValueError("a row's line is centre, outer or inner, not %r" % (line,)) from None
        base = row.anchor[1] if row.anchor and row.anchor[0] in ("before", "after") else row
        ref = base.standoff + {"centre": base.depth / 2.0, "outer": 0.0, "inner": base.depth}[line]   # the line, from the edge
        clears = [ref - {"centre": d / 2.0, "outer": 0.0, "inner": d}[line] for d in depths]
        row.line = line.value          # the plain value: what a declaration digest wrote before Line existed
        for n, (item, r, c) in enumerate(zip(items, rots, clears)):
            along = row.centres[n] if row.start is not None else _RowSlot(row, n)
            self.place(item, at=OnEdge(edge, along=along), _standoff=c, rotation=r, why=why, _row_of=of)
        return row

    def _check_row_pitch(self, items, keys, rots, along_axis: bool, pitch: float, gap: float) -> None:
        """Refuse a row(of=) pitch that brings two neighbours' envelopes
        closer than `gap`. A row of= puts each item's body centre on its
        along position, so the pitch is between body centres."""
        spans = []
        for item, r in zip(items, rots):
            env, body = self.envelope(item, r), self.extent(item, r)
            c = body.center.y if along_axis else body.center.x
            lo, hi = (env.top, env.bottom) if along_axis else (env.left, env.right)
            spans.append((c - lo, hi - c))          # how far the envelope reaches back and on from the centre
        for n in range(len(spans) - 1):
            need = spans[n][1] + gap + spans[n + 1][0]
            if pitch < need - 1e-9:
                raise ValueError("a row at pitch=%g puts %s and %s's envelopes closer than the envelope gap "
                                 "(%.3f mm); they need a pitch of at least %.3f"
                                 % (pitch, keys[n], keys[n + 1], gap, need))

    def ring(self, items, *, radius=None, start=Edge.NORTH, gap: float = 0.0, spread: bool = False,
             rotation=None, about=None, why: str = "") -> "Ring":
        """Items round a centre - the board's, `about` another point, or
        `about` a Part/Cell/PadRef resolved once each item is placed - in
        order clockwise from the bearing `start`, each turned to face
        outward: their body centres `radius` from that centre, or with no
        radius (a round board only) their reach at the rim's keep-in. Spaced by what they claim across the arc, `gap` mm of arc
        between claims - two claims can only meet at a point round a
        circle, so a gap of nothing leaves their inner corners the rounding
        two courtyards may touch by; `spread=True` shares the whole turn evenly instead
        (four mounting holes at 90 degrees). `rotation=` (one value or one
        per item) overrides the outward turn. Returns the Ring."""
        gap = self._row_gap(items, gap)
        centre = about   # resolved per item by place()'s own Polar handling, same as an item's own about=
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
        if align is Along.MID:
            s0 = max(0.0, (run.length - total) / 2.0) + first_half
        elif align is Along.END:
            s0 = max(0.0, run.length - total) + first_half
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


    # ------------------------------------------------------------ links
    def fanout(self, item, *, depth: float = 2.0, sides=None, why: str = ""):
        """A band outside the part's pad rows, `depth` mm deep, on each of
        `sides` (default every side with pads, judged as placed), that keeps
        out every part but the part's own block satellites and the parts
        linked to its pads at LinkWeight.SHORT or more: the room its pins
        escape through. Reserved on the part's face as soon as it is placed."""
        geom, key, kind = self._item(item)
        if kind != "part":
            raise TypeError("%s: a fanout is a part's pads; a cell or block has its own" % key)
        if depth <= 0:
            raise ValueError("%s: a fanout's depth is more than 0, not %r" % (key, depth))
        self._fanouts.append((key, geom, float(depth), None if sides is None else tuple(Edge(s) for s in sides), why))

    def link(self, a, b, weight=LinkWeight.DEFAULT, limit_mm: float | None = None, why: str = "") -> Link:
        """Price one connection between two pads. `weight` is a LinkWeight or
        any integer (0: the length of this connection does not matter);
        `limit_mm` makes it a bound the run reports against."""
        w = int(weight)
        if w < 0:
            raise ValueError("a link weight is 0 or more, not %r" % (weight,))
        ka, kb = self._pad_ref(a), self._pad_ref(b)
        if self._pad_land(a) is not None or self._pad_land(b) is not None:
            raise ValueError("a link prices the connection between two pins and measures each at its "
                             "whole pad; land= names one land for copper or a placement point, not a link")
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
        weight alone cannot say whether anybody asked for one. The first one
        declared, when the script declared two."""
        index = self.__dict__.get("_link_index")
        if index is None or index[0] != len(self._links):
            by_pair = {}
            for l in self._links:
                by_pair.setdefault(frozenset((l.a, l.b)), l)
            index = (len(self._links), by_pair)
            self._link_index = index
        return index[1].get(frozenset((pad_a, pad_b)))


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

    def _solvable(self, i) -> bool:
        """A searched part or cell placed by the plain search: the one path the
        solve seeds. A block, and anything with a line, an edge, a rim or a
        hint of its own, keeps the path it has."""
        return (i.kind in ("part", "cell") and not i.freedom.decided and i.near is None
                and i.at is None and i.center is None
                and i.edge is None and i.pin_x is None and i.pin_y is None and i.run is None
                and i.rim is None and i.angle is None and i.radius_at is None)

    def _global_hints(self, occ: Occupancy, placed: set, plan: Plan) -> dict:
        """Where every searched item not yet placed would sit if the whole
        netlist pulled at once, solved once per resolve at the first searched
        item. Placed items are anchors at their pads. A plane's or free net's
        connections pull only through a declared link, as for the seed, and
        every declared link is one more spring at its weight. An item nothing
        pulls gets no hint and falls through to the pocket scan."""
        if self._solve_hints is not None:
            return self._solve_hints
        from . import solve
        self._solve_hints = {}
        movable = [i for i in self._placements() if self._solvable(i) and not (
            ({fp.ref for fp in i.item.members} if i.kind == "cell" else {i.item.ref}) & set(placed))]
        box = occ.board_box
        if not movable or box is None:
            return self._solve_hints
        quiet = self._plane_nets() | self._free_nets
        by_net, owner_of = {}, {}
        for i in movable:
            offsets = occ.candidate_pad_locations(i.item, Placement(Location(0.0, 0.0), i.rotation, i.face))
            for fp in members_of(i.item):
                owner_of[fp.ref] = i.key
                for p in fp.pads:
                    off = offsets.get((fp.ref, p.number))
                    if p.net and off is not None:
                        by_net.setdefault(p.net, []).append(solve.Pin(i.key, off.x, off.y, (fp.ref, p.number)))
        for fp in self.geometry.footprints:
            if fp.ref not in placed:
                continue
            for p in fp.pads:
                if p.net in by_net:
                    at = occ.pad_location(fp.ref, p.number)
                    by_net[p.net].append(solve.Pin(None, at.x, at.y, (fp.ref, p.number)))
        nets = {n: pins for n, pins in by_net.items() if n not in quiet}
        pins_by_key = {pin.key: pin for pins in by_net.values() for pin in pins}
        for k, link in enumerate(self._links):
            a, b = pins_by_key.get(link.a), pins_by_key.get(link.b)
            if a is not None and b is not None and link.weight > 0:
                nets["link %d" % k] = [a, b]

        def weight_of(a, b):
            link = self._declared_link(a.key, b.key)
            if link is None:
                return float(LinkWeight.DEFAULT)
            return float(link.weight)

        pulled = {pin.item for pins in nets.values() if len(pins) >= 2
                  for pin in pins if pin.item is not None}
        keep = self.keep_in
        region = (box.left + keep, box.top + keep, box.right - keep, box.bottom - keep)
        areas = {i.key: occ._geometry(i.item).body.area for i in movable}
        result = solve.global_solve([i.key for i in movable], nets, weight_of, areas, region, {},
                                    self.settings.solve_rounds, self.settings.solve_iterations,
                                    self.settings.solve_tolerance)
        self._solve_hints = {k: Location(x, y) for k, (x, y) in result.hints.items() if k in pulled}
        plan.solve = {"seeded": len(self._solve_hints), "rounds": result.rounds,
                      "iterations": result.iterations, "residual": result.residual}
        return self._solve_hints

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

    def _scorer(self, item, occ: Occupancy, targets: list, prune: bool = True):
        """A candidate's cost: each connection's weight times its length,
        `score.crossing` for each ratsnest crossing its airwires would add,
        and the escape weights for each escape it would cross, close or wall
        off (escapes.py). See `Scorer`."""
        return Scorer(self.settings, item, occ, targets, prune)

    def _report_undeclared(self, plan: Plan):
        """A footprint no declaration places - itself, or as a cell's or a
        block's member - stays where the generator put it: say which."""
        declared = set()
        for i in self._intents:
            item = getattr(i, "item", None)
            if item is not None:
                declared |= {fp.ref for fp in members_of(item)}
        for fp in sorted(self.geometry.footprints, key=lambda f: f.inst):
            if fp.ref not in declared:
                plan.findings.append(Finding("setup", "%s (%s): no declaration places it, so it stays where the generator put it"
                                     % (fp.inst, fp.ref)))

    def _report_escapes(self, occ: Occupancy, plan: Plan):
        """Escapes left crossed at a pin row, and pads the path search finds
        closed toward what they join or walled off (escapes.py); and each
        differential pair whose two halves' airwires cross. Measured at
        `score.escape_depth`, whatever depth the search used: the run score
        counts these, and a shallower corridor is crossed less without being
        any easier to route."""
        from .escapes import Escapes
        depth = occ.settings.score_escape_depth
        esc = occ.escapes() if depth == occ.escapes().depth else Escapes(occ, mirror=False, depth=depth)
        rn = occ.ratsnest()
        from .pairs import pair_key
        for e, f in rn.pair_crossings():
            parts = sorted({v.ref for v in (e.a, e.b, f.a, f.b) if v.ref})
            pos, neg = (e.net, f.net) if (pair_key(e.net) or (0, True))[1] else (f.net, e.net)
            plan.findings.append(Finding("pair_crossed", "%s/%s cross between %s: swap two interchangeable parts on "
                                         "the pair, or turn a part whose pinout is mirrored 180 degrees"
                                         % (pos, neg, ", ".join(parts))))
        for n, e, f in rn.crossed_pair_list(esc.depth):
            ends = []
            for edge in (e, f):
                mine, other = (edge.a, edge.b) if edge.a.ref == n else (edge.b, edge.a)
                ends.append((mine.number, other.ref or "copper", edge.net))
            ends.sort(key=lambda t: (int(t[0]) if t[0].isdigit() else 1 << 30, t[0]))
            (pa, xa, na), (pb, xb, nb) = ends
            plan.findings.append(Finding("escape_crossed", "%s pins %s/%s: %s %s crosses %s %s" % (n, pa, pb, xa, na, xb, nb)))
        closed, walled = esc.confirmed()
        for ref, number, net, by, joins in closed:
            plan.findings.append(Finding("escape_closed", "%s pin %s (%s): closed toward %s by %s" % (
                ref, number, net, ", ".join(joins) or "what it joins", ", ".join(by) or "copper")))
        for ref, number, net, by, _ in walled:
            plan.findings.append(Finding("escape_walled", "%s pin %s (%s): walled off by %s" % (
                ref, number, net, ", ".join(by) or "copper")))

    def _report_links(self, occ: Occupancy, plan: Plan, placed: set):
        for l in self._links:
            if l.a[0] in placed and l.b[0] in placed:
                l.achieved_mm = round(occ.pad_location(*l.a).distance(occ.pad_location(*l.b)), 3)
                if not l.within_limit:
                    plan.findings.append(Finding("link_over", "link %s.%s to %s.%s is %.2f mm, over its %.2f mm limit%s" % (
                        l.a[0], l.a[1], l.b[0], l.b[1], l.achieved_mm, l.limit_mm, (": " + l.why) if l.why else "")))
            plan.links.append(l)

    # ------------------------------------------------------------ copper
    def _copper_intent(self, key, net, priority, plan, refs, why, bridge=False, extra_owners=frozenset()):
        """A copper declaration. WHEN it is planned is not asked here: it is
        derived in resolve(), once every placement is declared, because at
        declaration time a part placed later is invisible. `extra_owners`
        widens the owners a declaration with no refs of its own still waits
        on - a stitch over a pour waits on whatever the pour itself did."""
        name = self.geometry.require_net(net)
        pads = tuple(self._pad_ref(r) for r in refs)
        ci = CopperIntent(key, name, priority, plan, tuple(refs), why, len(self._copper), bridge,
                          frozenset(owner for owner, *_ in pads) | extra_owners)
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
        # to a millionth of a degree: a bearing read off a curve carries float noise (359.99999999999994 for
        # 0), and a part turned by it has pads a hair off the axes, which the router reads as off the board
        return round(local - bearing(edge), 6) % 360.0, "" if declared else note

    def label(self, item, text: str, *, side: Edge = Edge.NORTH, gap: float | None = None, align=Along.MID,
              size: float | None = None, thickness: float | None = None, knockout: bool = False,
              rotation: float = 0.0,
              reserve: bool = True, line=None, why: str = ""):
        """Silkscreen text that marks a user-facing feature: a connector,
        jumper, switch or LED. It sits `gap` off `side` of the item's reach
        (a Part or Cell) or of one pad (a PadRef/CellPadRef), on the item's
        own face, aligned `Along.MID` (or "centre"/"center"), `Along.START`
        (west or north end) or `Along.END` along that side; `rotation=90` runs it up the page;
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
        align = _align_word(_as_align(align, "a label's align"))
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
              chamfer: float | None = None, bend: Bend | None = None,
              priority: Priority = Priority.DEFAULT, bridge: bool = False, why: str = ""):
        """Track segments through `points` in order, on one layer. A point is
        a Location, a pad reference, a Mid, a `Between(PadRef(a), PadRef(b))`
        (the centreline of the gap between two pads), a `Past(items, edge)`
        (the clearance off those pads', vias' or tracks' `edge` side), or an (x, y) pair whose
        members may be numbers or X()/Y() of a reference. Legs run at 0, 45 or 90
        degrees only: a leg at another angle is a 45 and a straight, the 45
        at the pad end - or, with `bend=Bend.START`/`Bend.END`/`Bend.BOTH`,
        at the end(s) the script names, every off-grid leg of this track.
        Every corner is cut back `chamfer`
        along both legs (a right angle becomes two 45s; a short leg gets a
        shorter cut; `chamfer=0` keeps sharp corners). `bridge=True`
        lets it pass under a same-layer track of another net it crosses (a
        via, a track on the opposite face, a via back) when it is the one
        that must yield: the lower priority, or at equal priority the shorter."""
        chamfer = self.settings.copper_chamfer if chamfer is None else chamfer
        if bend is not None and not isinstance(bend, Bend):
            raise TypeError("bend is Bend.START, Bend.END or Bend.BOTH, not %r" % (bend,))
        layer = CopperLayer.of(layer)
        for p in points:
            if isinstance(p, CopperIntent) and not p.key.startswith("via "):
                raise TypeError("%s: a track may end on a via, and %r is not a via" % (net, p.key))
            if isinstance(p, CopperIntent) and not any(p is c for c in self._copper):
                raise TypeError("%s: %s is a via of another board" % (net, p.key))
            if isinstance(p, Past):
                self._check_past(p, "%s: a track point" % net)
        refs = _refs_in(points, via_ends=True)
        name = self.geometry.require_net(net)
        w = self._width(name, width)

        def plan(ctx):
            lost = [p for p in points if isinstance(p, CopperIntent) and p.index not in ctx.via_at]
            if lost:
                ctx.notes.append("track %s: its end on %s is not drawn, because that via found no spot" % (
                    name, ", ".join(p.key for p in lost)))
                return []
            located = []
            for p in points:
                if isinstance(p, Between):
                    at = _between_point(self, ctx, name, w, p)
                elif isinstance(p, Past):
                    at = _past_point(self, ctx, name, w, p, intent.key, intent.index)
                    if isinstance(at, str):
                        ctx.notes.append("%s: its point past %s is not drawn, because %s" % (
                            intent.key, ", ".join(_past_names(self, p)), at))
                        return []
                else:
                    at = ctx.locate(p)
                located.append(at)
            pads = [isinstance(p, (PadRef, CellPadRef)) for p in points]

            def clear(a, b):          # a leg that touches no pad of another net
                shape = _shape_of(Track(name, layer, w, a, b))
                return not ctx.occ.copper_conflicts(shape)

            pts = octilinear(located, pads, clear, bend)
            cut_pts, diagonals = chamfer_cuts(pts, chamfer)
            ops = polyline_tracks(name, layer, w, cut_pts)
            if chamfer > 0:
                # the 45 a corner's own cut emits, not a straight leg that merely
                # happens to run between two separate corners' cuts
                import dataclasses
                diag = {(round(a.x, 6), round(a.y, 6), round(b.x, 6), round(b.y, 6)) for a, b in diagonals}
                ops = [dataclasses.replace(t, chamfer_cut=(
                    round(t.start.x, 6), round(t.start.y, 6), round(t.end.x, 6), round(t.end.y, 6)) in diag)
                      for t in ops]
            if len(points) > 2 and any(not clear(t.start, t.end) for t in ops):
                # the script's waypoints steer this track into a pad: would pad to pad clear?
                direct = polyline_tracks(name, layer, w, chamfered(octilinear([located[0], located[-1]], [pads[0], pads[-1]], clear, bend), chamfer))
                others = [t for t in ctx.planned_tracks + ctx.batch_tracks
                          if t.net != name and t.layer is layer]     # tracks not in the occupancy yet count too

                def clear_of_tracks(t):
                    return all(poly_distance(t.polygon, o.polygon) >= self.geometry.clearance(name, o.net) - 1e-9
                               for o in others)
                if all(clear(t.start, t.end) and clear_of_tracks(t) for t in direct):
                    ctx.notes.append("track %s: a waypoint steers it into another net's pad; drawn pad to pad it clears, "
                                     "so drop the waypoint(s) unless the route must go there" % name)
            return ops
        intent = self._copper_intent("track %s" % name, net, priority, plan, refs, why, bridge)
        return intent

    def _check_past(self, p: Past, what: str, lane: bool = False):
        """A Past's vias and tracks are this board's; `lane=` only where
        `lane` says it means something (Beside's align)."""
        for it in p.items + (p.across,):
            if isinstance(it, CopperIntent) and not any(it is c for c in self._copper):
                raise TypeError("%s: %s is copper of another board" % (what, it.key))
        if p.lane is not None and not lane:
            raise TypeError("%s: Past's lane= is for Beside's align, where it leaves room for a track "
                            "between a part's pad and the items; a Past here keeps its own clearance" % what)

    def pair(self, net_p, net_n, path, *, layer: CopperLayer, width: float | None = None, gap: float | None = None,
             chamfer: float | None = None, via_step: float | None = None, priority: Priority = Priority.DEFAULT,
             bridge: bool = False, why: str = ""):
        """Two nets drawn together at `gap` along one centreline. `path`
        starts and ends with a (P pad, N pad) tuple; the points between, two
        or more, are the centreline. Width and gap default to the P net's class. Corners
        are chamfered at 45, each track leaves its pad at 45, and a lead that
        would touch the partner goes over the other face from a via."""
        chamfer = self.settings.copper_pair_chamfer if chamfer is None else chamfer
        via_step = self.settings.copper_pair_via_step if via_step is None else via_step
        layer = CopperLayer.of(layer)
        p_name, n_name = self.geometry.require_net(net_p), self.geometry.require_net(net_n)
        nc = self.geometry.netclass(p_name)
        w = float(width) if width is not None else (nc.diff_pair_width or nc.track_width)
        g = float(gap) if gap is not None else (nc.diff_pair_gap or nc.clearance)
        if len(path) == 3 or len(path) < 2:
            raise ValueError("%s/%s: a pair needs its two pad pairs, alone or with at least two centreline points "
                             "between (the direction the pair runs is read from them); %d given"
                             % (p_name, n_name, len(path) - 2))
        (sp, sn), (ep, en), mids = path[0], path[-1], path[1:-1]
        refs = _refs_in(path)

        def pad_end(rp, rn, ctx):
            out = []
            for r in (rp, rn):
                owner, number, _, _ = self._pad_ref(r)
                lands = [p for p in self.geometry.footprint(owner).pads if p.number == number]
                pad = lands[self._pad_land(r) or 0]
                out.append((ctx.locate(r), pad.through, layer if layer in pad.layers else next(iter(pad.layers))))
            (lp, tp, fp), (ln, tn, fn) = out
            return (lp, ln, tp, tn), (fp, fn)

        def own_centreline(start, end):
            """The pair's own centreline when the script gives none: from a pitch
            out of the first pad pair's middle to a pitch short of the last's,
            octilinear as a track's leg."""
            (sp_, sn_), (ep_, en_) = start[:2], end[:2]
            ms = Location((sp_.x + sn_.x) / 2.0, (sp_.y + sn_.y) / 2.0)
            me = Location((ep_.x + en_.x) / 2.0, (ep_.y + en_.y) / 2.0)
            d = ms.distance(me)
            step = w + g
            if d <= 2.0 * step:
                return None
            ux, uy = (me.x - ms.x) / d, (me.y - ms.y) / d
            cs = Location(round(ms.x + ux * step, 6), round(ms.y + uy * step, 6))
            ce = Location(round(me.x - ux * step, 6), round(me.y - uy * step, 6))
            return octilinear([cs, ce])

        def plan(ctx):
            start, sfaces = pad_end(sp, sn, ctx)
            end, efaces = pad_end(ep, en, ctx)
            if mids:
                centre = [ctx.locate(m) for m in mids]
            else:
                centre = own_centreline(start, end)
                if centre is None:
                    ctx.notes.append("pair %s/%s: its pad pairs are too close for a centreline of its own; give "
                                     "the centreline's points" % (p_name, n_name))
                    return []
            return pair_ops(p_name, n_name, layer, w, g, start, centre, end, self.via_drill, self.via_size,
                            via_step, chamfer, self.geometry.clearance(p_name, n_name), sfaces, efaces)
        return self._copper_intent("pair %s/%s" % (p_name, n_name), net_p, priority, plan, refs, why, bridge)

    def vias(self, net, pad=None, *, along=None, count: int | None = None, pitch: float | None = None,
             size: float | None = None, drill: float | None = None,
             inset: float = 0.0, priority: Priority = Priority.DEFAULT, why: str = ""):
        """Vias of `net` at a pad, one of two ways.

        `pad` (a `PadRef`/`CellPadRef`): the pad filled with a square grid
        `pitch` apart (by default the closest the board's hole-to-hole rule
        allows), in the part's own frame and centred on each of the pin's
        lands, keeping each via whose copper, grown by `inset`, lies wholly
        in that land. A via in a pad is filled or plugged at the fab.

        `along=PadRef(...)` with `count=N`: N vias in a row out from that
        pad along its escape axis (the outward normal of the pad row it
        sits in, or the ray from the part's body centre when the row does
        not decide one), `pitch` apart (by default the via-to-via rule: the
        larger of the via's own size and a drilled hole plus the
        hole-to-hole rule), the first clear of the pad's own copper, joined
        to the pad by a tail at the net's width out to the farthest via. A
        via the row cannot fit, or its tail cannot reach - the board edge,
        another net's copper, a hole - is a finding, and the row stops
        there. A track may end on the returned intent: the farthest via.

        Either way, resolved when the pad's part is placed."""
        if (pad is None) == (along is None):
            raise TypeError("%s: vias needs exactly one of a pad (a grid over it) or along= (a row along "
                            "its axis)" % net)
        name = self.geometry.require_net(net)
        nc = self.geometry.netclasses.get(name)
        s = float(size) if size is not None else (nc.via_diameter if nc else self.via_size)
        d = float(drill) if drill is not None else (nc.via_drill if nc else self.via_drill)
        floor = d + self.geometry.hole_to_hole
        step = max(s, floor) if pitch is None else float(pitch)
        if inset < 0:
            raise ValueError("%s: a negative inset lets a via's copper leave its pad; inset is 0 or more" % name)
        if step < floor - 1e-9:
            raise ValueError("%s: vias %.2f mm apart break the hole-to-hole rule (a %.2f mm hole plus %.2f): "
                             "%.2f mm at least" % (name, step, d, self.geometry.hole_to_hole, floor))
        if along is not None:
            if inset:
                raise ValueError("%s: inset keeps a via inside the pad it fills; a row along= its axis "
                                 "has no pad to stay inside" % name)
            if count is None or int(count) < 1:
                raise ValueError("%s: along= needs count=, a positive number of vias" % name)
            n = int(count)
            owner, number, _, _ = self._pad_ref(along)

            def plan(ctx):
                from . import queries
                shapes = _pad_shapes(self, ctx.occ, along)
                ux, uy = _escape_axis(ctx.occ, owner, number, Box.union([sh.box for sh in shapes]))
                c = Box.union([sh.box for sh in shapes]).center
                half = max(abs((px - c.x) * ux + (py - c.y) * uy) for sh in shapes for px, py in sh.poly)
                obstacles = self._via_obstacles(ctx)
                # a via clear of the pad's tip touches it at one point at most, which KiCad counts
                # as unconnected: a tail at the net's width joins the pad to the farthest via
                layer = sorted((l for sh in shapes for l in sh.layers), key=stackup_order)[0]
                width = queries.tail_width(nc.track_width if nc else 0.2, [sh.poly for sh in shapes])
                start = Location(round(c.x, 6), round(c.y, 6))
                vias = []
                for i in range(n):
                    r = half + s / 2.0 + i * step
                    at = Location(round(c.x + ux * r, 6), round(c.y + uy * r, 6))
                    why_not = self._via_site_why(ctx, at, name, s, d, obstacles)
                    if why_not is None:
                        why_not = self._tail_why(ctx, Track(name, layer, width, start, at))
                    if why_not is not None:
                        ctx.notes.append("vias %s: %d of %d along %s.%s's axis, the next stands %s" % (
                            name, len(vias), n, owner, number, why_not))
                        break
                    via = Via(name, at, d, s)
                    vias.append(via)
                    ctx.planned_vias.append(via)
                if not vias:
                    return []
                tail = Track(name, layer, width, start, vias[-1].at)
                ctx.planned_tails.append(tail)
                ctx.via_at[intent.index] = vias[-1].at      # a track may end on the row's farthest via
                return vias + [tail]
            # "via row": a track may end on it, as on one via()
            intent = self._copper_intent("via row %s" % name, net, priority, plan, _refs_in([along]), why)
            return intent
        owner, number, _, _ = self._pad_ref(pad)

        def plan(ctx):
            from .lock import _turn
            occ = ctx.occ
            g = occ.items[owner]
            rot = g.reference.rotation
            lands = [sh.poly for sh in _pad_shapes(self, occ, pad) if sh.kind == "pad"]   # a through land has its hole
            obstacles = self._via_obstacles(ctx)
            vias = []
            for land in lands:
                c = Box.of_points(land).center
                local = [_turn(x - c.x, y - c.y, -rot) for x, y in land]      # the land in its part's frame
                lx0, lx1 = min(p[0] for p in local), max(p[0] for p in local)
                ly0, ly1 = min(p[1] for p in local), max(p[1] for p in local)
                mx, my = (lx0 + lx1) / 2.0, (ly0 + ly1) / 2.0

                def count(extent):              # to 10 nm: a turned land's corners are rounded
                    return max(0, int(math.floor((extent - s - 2.0 * inset) / step + 1e-5)) + 1)
                nx, ny = count(lx1 - lx0), count(ly1 - ly0)
                for i in range(nx):
                    for j in range(ny):
                        ox, oy = _turn(mx + (i - (nx - 1) / 2.0) * step, my + (j - (ny - 1) / 2.0) * step, rot)
                        at = Location(round(c.x + ox, 6), round(c.y + oy, 6))
                        # 10 nm short of the copper: a via reaching the land's edge is inside it
                        if (poly_within(circle_polygon(at, s / 2.0 + inset - 1e-5, 24), land)
                                and self._via_site_why(ctx, at, name, s, d, obstacles) is None):
                            via = Via(name, at, d, s)
                            vias.append(via)
                            ctx.planned_vias.append(via)    # the next via, and a later FreeSpot, keep the rule from it
            if not vias:
                ctx.notes.append("vias %s: no via fits in %s.%s, or clears the copper and holes round it "
                                 "(%.2f mm via, %.2f mm drill, %.2f mm inset)" % (
                    name, owner, number, s, d, inset))
                return []
            return vias
        return self._copper_intent("vias %s" % name, net, priority, plan, _refs_in([pad]), why)

    def via(self, net, at, *, drill: float | None = None, size: float | None = None,
            priority: Priority = Priority.DEFAULT, why: str = ""):
        """A via of `net`. `at` is a position, a `FreeSpot` near a pad (the
        nearest point a via can stand and be reached, found when the pad is
        placed), or a `Past(items, edge)` (the via's radius plus its
        clearance off those pads', vias' or tracks' `edge` side). A FreeSpot
        with nowhere to go, or a Past naming a via that found no spot, is a
        finding and draws none."""
        name = self.geometry.require_net(net)
        if isinstance(at, Past):
            self._check_past(at, "%s: a via's at=" % name)
        refs = _refs_in([at])
        d, s = drill or self.via_drill, size or self.via_size
        if isinstance(at, (PadRef, CellPadRef)) and not (at.dx or at.dy):
            # at the pad, or off it in the part's frame: it turns with the part, so the part carries it
            self._pad_vias.append((at, name, d, s))

        def plan(ctx):
            ops = []
            if isinstance(at, FreeSpot):
                found = self._free_spot(ctx, at, name, d, s)
                if found is None:
                    return []
                where, layer, width, start, path = found
                if at.tail and not at.in_pad and where.distance(start) > 1e-9:
                    for tail in polyline_tracks(name, layer, width, path):
                        ctx.planned_tails.append(tail)
                        ops.append(tail)
            elif isinstance(at, Past):
                where = _past_point(self, ctx, name, s, at, intent.key, intent.index)     # s: the via's radius out
                if isinstance(where, str):
                    ctx.notes.append("%s: its point past %s is not drawn, because %s" % (
                        intent.key, ", ".join(_past_names(self, at)), where))
                    return []
            else:
                where = ctx.locate(at)
            via = Via(name, where, d, s)
            ctx.planned_vias.append(via)        # a later FreeSpot in this batch sees it
            ctx.via_at[intent.index] = where    # a track may end on it
            return [via] + ops
        intent = self._copper_intent("via %s" % name, net, priority, plan, refs, why)
        return intent

    def stitch(self, net, region, *, pitch: float | None = None, size: float | None = None,
               drill: float | None = None, edge: bool = False, priority: Priority = Priority.DEFAULT,
               why: str = ""):
        """Stitching vias of `net` over `region` - a `Cell`, the
        `CopperIntent` `board.pour()` returns, or a keepout's name - `pitch`
        apart (by default the via-to-via rule: the larger of the via's own
        size and a drilled hole plus the hole-to-hole rule), each one wholly
        inside the region and clear of every other net's copper, hole,
        keepout and the board edge. A grid over the whole region by default;
        `edge=True` instead rows them along the region's own outline, a
        via's clearance in from it. Resolved once the region itself is:
        after the cell is placed, the pour is drawn, or the keepout is
        settled."""
        name = self.geometry.require_net(net)
        nc = self.geometry.netclasses.get(name)
        s = float(size) if size is not None else (nc.via_diameter if nc else self.via_size)
        d = float(drill) if drill is not None else (nc.via_drill if nc else self.via_drill)
        floor = d + self.geometry.hole_to_hole
        step = max(s, floor) if pitch is None else float(pitch)
        if step < floor - 1e-9:
            raise ValueError("%s: stitching vias %.2f mm apart break the hole-to-hole rule (a %.2f mm hole "
                             "plus %.2f): %.2f mm at least" % (name, step, d, self.geometry.hole_to_hole, floor))
        extra_owners, refs, pour_intent = frozenset(), (), None
        if isinstance(region, CopperIntent):
            if not region.key.startswith("pour "):
                raise TypeError("%s: stitch's region is a Cell, a keepout's name, or the CopperIntent "
                                "board.pour() returns, not %r" % (name, region.key))
            if region.net != name:
                raise ValueError("%s: stitch's region is a pour of net %r; stitching vias join the pour "
                                 "they sit on, so they must be its own net" % (name, region.net))
            extra_owners, pour_intent = region.owners, region
        elif isinstance(region, Cell):
            refs = (region,)
        elif isinstance(region, str):
            if region not in self._keepouts:
                raise KeyError("no keepout named %r on this board" % (region,))
            k = self._keepouts[region]
            if "vias" in k.excludes and name not in k.allow:
                raise ValueError("%s: keepout %r excludes vias (excludes=%s), so no via could stand anywhere "
                                 "in it; add %r to its allow=, or narrow its excludes=" % (
                                     name, region, list(k.excludes), name))
        else:
            raise TypeError("%s: stitch's region is a Cell, a keepout's name, or the CopperIntent "
                            "board.pour() returns, not %r" % (name, region))

        def candidates(poly):
            if not edge:
                box = Box.of_points(poly)
                y = box.top + step / 2.0
                while y <= box.bottom - step / 2.0 + 1e-6:
                    x = box.left + step / 2.0
                    while x <= box.right - step / 2.0 + 1e-6:
                        yield x, y
                        x += step
                    y += step
                return
            inset = s / 2.0 + (nc.clearance if nc else self.geometry.default_clearance)
            yield from _stitch_edge_points(poly, step, inset)

        def plan(ctx):
            poly = _stitch_region(self, ctx, region, pour_intent)
            if poly is None:
                ctx.notes.append("stitch %s: its region is not drawn, so there is nothing to stitch over" % name)
                return []
            obstacles = self._via_obstacles(ctx)
            vias = []
            for x, y in candidates(poly):
                at = Location(round(x, 6), round(y, 6))
                if (poly_within(circle_polygon(at, s / 2.0, 24), poly)
                        and self._via_site_why(ctx, at, name, s, d, obstacles) is None):
                    via = Via(name, at, d, s)
                    vias.append(via)
                    ctx.planned_vias.append(via)
            if not vias:
                ctx.notes.append("stitch %s: no via fits in the region at a %.2f mm pitch" % (name, step))
            return vias
        return self._copper_intent("stitch %s" % name, net, priority, plan, refs, why, extra_owners=extra_owners)

    def _via_obstacles(self, ctx):
        """What a via's site is judged against beyond the occupancy's copper:
        every drilled hole where it now stands - each plated hole of a placed
        part at its own land, so the holes of one pin stay apart, and every
        via on the board, a stamped cell's and those planned before - every
        unplated hole, and the keepouts and rule areas that forbid vias."""
        occ = ctx.occ
        def hole(sh):                    # the circle the polygon was drawn from: its box is short of it when turned
            c = sh.box.center
            return c, 2 * max(math.dist((c.x, c.y), p) for p in sh.poly)
        holes = [hole(sh) for o, g in occ.items.items() if o not in occ.pending for sh in g.shapes if sh.kind == "hole"]
        holes += [hole(sh) for sh in occ.copper if sh.kind == "hole" and sh.owner not in occ.pending]
        # unplated holes (a connector's locating pegs): no copper, so the via's copper keeps the board's hole
        # clearance from the hole's edge as well as the hole-to-hole rule
        bare = [(sh.box.center, sh.box.width) for o, g in occ.items.items() if o not in occ.pending
                for sh in g.shapes if sh.kind == "npth"]
        forbidding = [(k.poly, k.layers) for k in (ctx.plan.keepouts.values() if ctx.plan else ())
                      if "vias" in k.excludes]
        forbidding += [(poly, ra.layers) for pairs in occ._cell_rule_areas.values() for ra, poly in pairs
                       if "vias" in ra.excludes]
        forbidding += [(ra.polygon, ra.layers) for ra in self.geometry.rule_areas
                       if ra.cell is None and "vias" in ra.excludes]
        return holes, bare, forbidding

    def _via_site_why(self, ctx, c: Location, net: str, size: float, drill: float, obstacles) -> str | None:
        """Why a via of `net` may not stand at `c`, or None. A via goes
        through every layer: the board's edge, every other net's copper
        (placed, and planned so far in this batch: tracks, tails and vias),
        the hole-to-hole rule from every hole, the hole clearance from an
        unplated one, and keepouts that forbid vias."""
        occ = ctx.occ
        holes, bare, forbidding = obstacles
        ring = via_ring(c, size)
        box = Box.of_points(ring)
        if occ.board_shape is not None:
            if occ.board_shape.why_not(box, self.keep_in):
                return "off the board, or within %.2f mm of the board edge" % self.keep_in
        elif occ.board_box is not None and not occ.board_box.inflate(-self.keep_in).contains(box):
            return "within %.2f mm of the board edge" % self.keep_in
        hits = occ.copper_conflicts(Shape("via", "copper", frozenset(), frozenset(self.geometry.layers), net, ring, box))
        if hits:
            return "copper " + hits[0]
        for v in ctx.planned_vias:
            gap = c.distance(v.at) - (drill + v.drill) / 2.0
            if gap < self.geometry.hole_to_hole - 1e-9:
                return "hole %.2f mm from the %s via's hole" % (max(gap, 0.0), v.net)
            if v.net != net:
                clr = self.geometry.clearance(net, v.net)
                if c.distance(v.at) - (size + v.size) / 2.0 < clr - 1e-9:
                    return "copper %.2f mm from the %s via" % (c.distance(v.at) - (size + v.size) / 2.0, v.net)
        for t in ctx.planned_tails + [t for t in ctx.batch_tracks if t not in ctx.planned_tails]:
            if t.net != net and poly_distance(ring, t.polygon) < self.geometry.clearance(net, t.net) - 1e-9:
                return "copper %.2f mm from a %s track planned before it" % (poly_distance(ring, t.polygon), t.net)
        for at, dia in holes:
            gap = c.distance(at) - (drill + dia) / 2.0
            if gap < self.geometry.hole_to_hole - 1e-9:
                return "hole %.2f mm from a pad's hole" % max(gap, 0.0)
        for at, dia in bare:
            gap = c.distance(at) - (drill + dia) / 2.0
            if gap < self.geometry.hole_to_hole - 1e-9:
                return "hole %.2f mm from an unplated hole" % max(gap, 0.0)
            edge = c.distance(at) - (size + dia) / 2.0
            if edge < self.geometry.hole_clearance - 1e-9:
                return "copper %.2f mm from an unplated hole (needs %.2f)" % (max(edge, 0.0), self.geometry.hole_clearance)
        for poly, layers in forbidding:
            if polys_overlap(ring, poly):
                return "inside a keepout, which forbids vias"
        return None

    def _tail_why(self, ctx, tail) -> str | None:
        """Why `tail` cannot be drawn - within clearance of another net's via
        or track planned before it, or of copper already on the board - or
        None."""
        net, layer = tail.net, tail.layer
        for v in ctx.planned_vias:
            if v.net != net and poly_distance(tail.polygon, v.polygon) < self.geometry.clearance(net, v.net) - 1e-9:
                return "tail %.2f mm from the %s via" % (poly_distance(tail.polygon, v.polygon), v.net)
        for t in ctx.planned_tails + [t for t in ctx.batch_tracks if t not in ctx.planned_tails]:
            if (t.net != net and t.layer is layer
                    and poly_distance(tail.polygon, t.polygon) < self.geometry.clearance(net, t.net) - 1e-9):
                return "tail crosses a %s track planned before it" % t.net
        hits = ctx.occ.copper_conflicts(Shape("via", "copper", frozenset(), frozenset([layer]),
                                              net, tail.polygon, Box.of_points(tail.polygon)))
        return "tail " + hits[0] if hits else None

    def _free_spot(self, ctx, spot, net: str, drill: float, size: float):
        """Run the search from the pad against the board as it stands: placed
        pads and planned copper through the occupancy, the vias planned so far,
        drilled holes, keepouts and the edge."""
        from . import queries
        occ = ctx.occ
        owner, number, _, _ = self._pad_ref(spot.near)
        start = ctx.locate(spot.near)
        try:
            own = _pad_shapes(self, occ, spot.near) if owner in occ.items else []
        except KeyError:
            own = []
        if own and not any(point_in_polygon((start.x, start.y), sh.poly) for sh in own):
            # a pin of several apart lands: the centre of their union can be bare board
            start = min((sh.box.center for sh in own), key=start.distance)
        layer = CopperLayer.of(spot.layer) if spot.layer is not None else (
            sorted((l for sh in own for l in sh.layers), key=stackup_order) or [CopperLayer.F])[0]
        if spot.tail and not spot.in_pad and own and not any(layer in sh.layers for sh in own):
            ctx.notes.append("via %s: its tail on %s would not join %s.%s, which is not on that layer" % (
                net, layer.value, owner, number))
            return None
        nc = self.geometry.netclasses.get(net)
        width = queries.tail_width(nc.track_width if nc else 0.2, [sh.poly for sh in own])
        obstacles = self._via_obstacles(ctx)

        judged = {}

        def leg_why(a, b):
            """Why one leg of the tail cannot be drawn: within clearance of another
            net's via or track planned before it, or of the board's copper. Asked of
            the same leg by the routing and by the judge, so kept for this search."""
            key = (a.x, a.y, b.x, b.y)
            if key not in judged:
                judged[key] = _leg_why(a, b)
            return judged[key]

        def _leg_why(a, b):
            tail = queries._segment(a, b, width)
            for v in ctx.planned_vias:
                if v.net != net and poly_distance(tail, v.polygon) < self.geometry.clearance(net, v.net) - 1e-9:
                    return "tail %.2f mm from the %s via" % (poly_distance(tail, v.polygon), v.net)
            for t in ctx.planned_tails + [t for t in ctx.batch_tracks if t not in ctx.planned_tails]:
                if (t.net != net and t.layer is layer
                        and poly_distance(tail, t.polygon) < self.geometry.clearance(net, t.net) - 1e-9):
                    return "tail crosses a %s track planned before it" % t.net
            tail_hits = occ.copper_conflicts(Shape("via", "copper", frozenset(), frozenset([layer]),
                                                   net, tail, Box.of_points(tail)))
            return "tail " + tail_hits[0] if tail_hits else None

        def tail_path(c):
            # drawn as board.track() draws a leg: at 0, 45 or 90 degrees, the 45 at the pad. A
            # spot whose tail is not clear that way is passed over for the next spot the search
            # tries, rather than routed round: the search is already dense
            return octilinear([start, c], [True, False])

        def judge(c):
            ring = via_ring(c, size)
            if not spot.in_pad and any(polys_overlap(ring, sh.poly) for sh in own):
                return "in the source pad", ()
            why = self._via_site_why(ctx, c, net, size, drill, obstacles)
            if why:
                return why, ()
            if c.distance(start) > 1e-9:            # the tail it will draw: clear of other nets' vias and tracks
                path = tail_path(c)
                for a, b in zip(path, path[1:]):
                    why = leg_why(a, b)
                    if why:
                        return why, ()
            return None, ()

        found, tally, tried = queries.free_spot(start, judge, spot.radius, spot.step)
        if found is None:
            ctx.notes.append("via %s: nowhere within %.2f mm of %s.%s, %d spot(s) tried: %s" % (
                net, spot.radius, owner, number, tried,
                ", ".join("%s x%d" % kv for kv in tally.most_common())))
            return None
        return found.at, layer, width, start, tail_path(found.at)

    def pour(self, net, points, *, layer: CopperLayer, stroke: float | None = None, swallow_pads: bool = False,
             width: float | None = None, cover: Cover | None = None, priority: Priority = Priority.DEFAULT,
             why: str = ""):
        """A filled copper polygon on one layer. It does not pull back from
        foreign copper; `swallow_pads` grows it over the same-net pads its
        outline touches and pulls it back from other nets when written.
        `cover` says what corners that name pads cover (`Cover`): a pour over
        pads whose corners are all pads covers the hull of their copper, any
        other the polygon through its points. Exactly two pads (`[PadRef(a),
        PadRef(b)]`) draws the neck between them instead - a rectangle along
        their centreline, as wide as the narrower pad measured across it,
        unless `width=` says otherwise."""
        stroke = self.settings.copper_pour_stroke if stroke is None else stroke
        layer = CopperLayer.of(layer)
        name = self.geometry.require_net(net)
        if cover is not None and not isinstance(cover, Cover):
            raise TypeError("%s: a pour's cover is Cover.HULL, Cover.BOX or Cover.CENTRES, not %r" % (name, cover))
        all_pads = all(isinstance(p, (PadRef, CellPadRef)) for p in points)
        if cover is None:
            cover = Cover.HULL if swallow_pads and all_pads and len(points) >= 3 else Cover.CENTRES
        neck = len(points) == 2 and all_pads
        if len(points) < 3 and not neck:
            raise ValueError("%s: a pour needs 3 or more points, or exactly two pads for the neck between "
                             "them (%d given)" % (name, len(points)))
        refs = _refs_in(points)

        def plan(ctx):
            if neck:
                ca, cb = ctx.locate(points[0]), ctx.locate(points[1])
                dx, dy = cb.x - ca.x, cb.y - ca.y
                n = math.hypot(dx, dy)
                if n < 1e-9:
                    raise ValueError("%s: a pour neck needs its two pads at different points" % name)
                ux, uy = dx / n, dy / n
                w = float(width) if width is not None else 2.0 * min(
                    _pad_half_across(self, ctx.occ, points[0], ca, ux, uy),
                    _pad_half_across(self, ctx.occ, points[1], cb, ux, uy))
                nx, ny = -uy * w / 2.0, ux * w / 2.0
                pts = ((ca.x + nx, ca.y + ny), (cb.x + nx, cb.y + ny), (cb.x - nx, cb.y - ny), (ca.x - nx, ca.y - ny))
            elif cover is Cover.CENTRES:
                pts = tuple((l.x, l.y) for l in (ctx.locate(p) for p in points))
            else:
                # the pads' copper, every land's corners, and any plain point as given
                corners = []
                for p in points:
                    if isinstance(p, (PadRef, CellPadRef)):
                        corners += [q for sh in _pad_shapes(self, ctx.occ, p) for q in sh.poly]
                    else:
                        l = ctx.locate(p)
                        corners.append((l.x, l.y))
                if cover is Cover.BOX:
                    pts = box_polygon(Box.of_points(corners))
                else:
                    from .checks import _hull
                    pts = tuple(_hull([(round(x, 6), round(y, 6)) for x, y in corners]))
            ctx.pour_at[intent.index] = pts       # a stitch over this pour, once it is drawn
            named = tuple(_named_pad(self, ctx, name, p) for p in points)
            named = tuple(n for n in named if n is not None)
            return [Pour(name, layer, pts, stroke, swallow_pads, named)]
        intent = self._copper_intent("pour %s" % name, net, priority, plan, refs, why)
        return intent

    def plane(self, net, layers, *, outline=None, inset: float | None = None, chamfer: float | None = None,
              clearance: float | None = None, min_thickness: float | None = None, solid_pads: bool = True,
              priority: Priority = Priority.DEFAULT, over=None, margin: float = 0.0, why: str = ""):
        """A KiCad zone per layer, filled by KiCad and pulled back round every
        foreign pad, track and via: the whole board inset from the edge, the
        polygon `outline`, or `over=[Part(...), Cell(...)]` the box round
        those items' drawn envelopes (the region `keepout(item)` takes),
        grown by `margin` and clipped to the frame inset by `inset`. A plane
        over items waits for them to be placed."""
        inset = self.settings.copper_plane_inset if inset is None else inset
        clearance = self.settings.copper_plane_clearance if clearance is None else clearance
        min_thickness = self.settings.copper_plane_min_thickness if min_thickness is None else min_thickness
        name = self.geometry.require_net(net)
        layers = tuple(dict.fromkeys(CopperLayer.of(l) for l in layers))
        if over is not None:
            if outline is not None:
                raise ValueError("plane %s: its outline is over= items or outline= points, not both" % name)
            over = [over] if isinstance(over, (Part, Cell)) else list(over)
            if not over or not all(isinstance(it, (Part, Cell)) for it in over):
                raise TypeError("plane %s: over= names Part(...)/Cell(...) items, not %r" % (name, over))
            for it in over:
                self._item(it)                  # a real part or cell, checked now

        def plan(ctx):
            if over is not None:
                boxes = []
                for it in over:
                    geom, key, kind = self._item(it)
                    if kind == "cell" and key not in self._cell_placements:
                        # a cell the script never places stands where the generator put it: its
                        # members, each where it is
                        boxes += [self._drawn_envelope_box(Part(fp.inst), ctx.occ.items[fp.ref].reference)
                                  for fp in geom.members]
                    else:
                        boxes.append(self._drawn_envelope_box(it, self._item_placement(ctx.occ, it)))
                box = Box.union(boxes).inflate(float(margin))
                frame = ctx.occ.board_box
                if frame is not None:
                    f = frame.inflate(-inset)
                    box = Box(max(box.left, f.left), max(box.top, f.top),
                              min(box.right, f.right), min(box.bottom, f.bottom))
                if box.width <= 0 or box.height <= 0:
                    ctx.notes.append("plane %s: its items lie outside the frame, so it is not drawn" % name)
                    return []
                pts = box_polygon(box)
            elif outline is not None:
                pts = tuple((l.x, l.y) for l in (ctx.locate(p) for p in outline))
            elif self._shape is not None:
                pts = self._shape.polygon(inset)
            elif self._fit:                     # planned once the frame is fitted to what was placed
                f, ch = ctx.plan.outline, self._chamfer if chamfer is None else chamfer
                pts = board_zone_outline(f.width, f.height, inset, ch, origin=(f.left, f.top))
            else:
                ch = self._chamfer if chamfer is None else chamfer
                pts = board_zone_outline(self.width, self.height, inset, ch)
            return [Zone(name, l, pts, clearance, min_thickness, solid_pads) for l in layers]
        refs = _refs_in(over) if over is not None else [] if outline is None else _refs_in(outline)
        intent = self._copper_intent("plane %s" % name, net, priority, plan, refs, why)
        if outline is None:
            self._frame_planes.add(intent.index)    # on a fit board, planned once the frame is fitted
        return intent

    def finger(self, net, *, layer: CopperLayer, from_, to, width,
               bridge_width: float | None = None, priority: Priority = Priority.DEFAULT, why: str = ""):
        """A finger: a rectangular pour along the centreline from `from_` to
        `to` (points, pads, or (x, y) pairs with X()/Y()), `width` wide - a
        number, or a `PadRef`/`CellPadRef` to run as wide as that pad
        measured across the run - cut either side of every same-layer track
        of another net it crosses and bridged under each on the opposite
        face so the pieces stay one net. Fingers always yield to tracks."""
        bridge_width = self.settings.copper_finger_bridge_width if bridge_width is None else bridge_width
        layer = CopperLayer.of(layer)
        name = self.geometry.require_net(net)
        width_pad = width if isinstance(width, (PadRef, CellPadRef)) else None
        if width_pad is None and not isinstance(width, (int, float)):
            raise TypeError("%s: a finger's width is a number, or a PadRef/CellPadRef to run as wide as "
                            "that pad, not %r" % (name, width))
        refs = _refs_in([from_, to] + ([width_pad] if width_pad is not None else []))

        def plan(ctx):
            a, b = ctx.locate(from_), ctx.locate(to)
            dx, dy = b.x - a.x, b.y - a.y
            n = math.hypot(dx, dy)
            if width_pad is None:
                w = float(width)
            elif n < 1e-9:
                w = 2.0 * _pad_half_across(self, ctx.occ, width_pad, a, 1.0, 0.0)
            else:
                w = 2.0 * _pad_half_across(self, ctx.occ, width_pad, ctx.locate(width_pad), dx / n, dy / n)
            segs = [((t.start.x, t.start.y), (t.end.x, t.end.y)) for t in ctx.tracks_on(layer) if t.net != name]
            return finger_ops(name, layer, a, b, w, segs, self.via_drill, self.via_size, bridge_width,
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
            if i.freedom.decided and i.key not in self._rider_of:      # a rider lands with what it rides
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

    reuse_extra = ""        # what the runner adds to the reuse context: tool version, board file, settings, fab profile

    def resolve(self, progress=None, reuse=None, explore=None, lock=None, routes=None) -> Plan:
        self._check_groups()                # what a declared group may hold, before the search
        self._find_riders()                 # before anything asks what is searched
        # An explore variant (explore.py): seed 0, or none, is the plain placement.
        self._explore = explore if (explore is not None and explore.seed) else None
        # Accepted decisions (lock.py): tried first at each locked item's turn.
        self._lock = {e.key: e for e in (lock or ())}
        self._lock_notes = {}
        self._lock_held = set()          # locked items at (or drifted from) their spot: the cleanup pass leaves them
        if self._explore is not None:
            import random as _random
            self._order_rng = _random.Random("%d:order" % self._explore.seed)
        occ = Occupancy(self.geometry, self.edge_margin, board_box=self._outline, board_shape=self._shape,
                        board_cutouts=self._cutouts, settings=self.settings,
                        component_spacing=self.component_spacing)
        self._carry_pad_vias(occ)          # before any cell's geometry is built from its members'
        occ.quiet_nets = frozenset(self._plane_nets() | set(self._free_nets))
        if self._fit:
            occ.board_box = None                # no frame yet: the decided items have no edge to be judged by
        for intent in self._placements():
            declared = [intent.item.anchor] + [fp for fp, _ in intent.item.satellites] if intent.kind == "block" else [intent.item]
            for item in declared:
                occ.pending |= occ._geometry(item).owners
        plan = Plan(self.geometry, occ, outline=self._outline, chamfer=self._chamfer, radius=self._radius,
                    shape=self._shape, cutouts=self._cutouts,
                    rules=list(self._rules), draw_outline=self._draw_outline,
                    cell_zones_under_planes=self.settings.copper_cell_zones_under_planes,
                    split_groups=self.settings.write_split_groups, groups=list(self._groups.values()))
        ctx = _CopperContext(self, occ)
        ctx.plan = plan
        from . import reuse as _reuse
        context = _reuse.context_key(self, self.reuse_extra)
        record = {"version": _reuse.VERSION, "context": context, "steps": [], "reused": 0, "first_change": None}
        plan.reuse = record
        previous = reuse.get("steps", []) if reuse and reuse.get("version") == _reuse.VERSION \
            and reuse.get("context") == context else None
        chain = {"key": context, "replaying": previous is not None}
        self._solve_hints = None            # the global solve runs once per resolve, when first asked
        self._report_lost_layers(plan)
        self._rank(occ)
        if occ.envelope == "courtyard":
            from .envelope import understatement
            for fp in sorted(self.geometry.footprints, key=lambda f: f.ref):
                u = understatement(fp, self.geometry.silk_clearance)
                if u is not None:
                    plan.footprints.append("%s: courtyard understates the part by %.2f mm (%s)" % (fp.ref, u[0], u[1]))
        self._derive_copper_freedom()
        placements = sorted(self._intents, key=lambda i: i.rank)   # holes included: they are placed too
        held = self._frame_planes if self._fit else set()
        fixed_copper = [c for c in self._copper if c.freedom.decided and c.index not in held]
        other_copper = [c for c in self._copper if not c.freedom.decided and c.index not in held]
        placed: set = set()
        self._place_fanouts(occ, plan, placed, progress)
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
                turn = self._region_rotation(occ, c, centre)
                why = self._cutout_illegal(occ, c.shape.path_at(centre, turn), c.name)
            path = c.shape.path_at(centre, turn)
            step = Step(intent.key, "cutout", None, why=intent.why)
            if why:
                plan.findings.append(Finding("fixed", "%s (cutout): %s" % (c.name, why)))
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
            region_shape = None
            if k.region_of is not None:
                import dataclasses
                p = self._item_placement(occ, k.region_of)
                geom, _, kind = self._item(k.region_of)
                # the shape was drawn in the item's own GENERATED frame, never
                # flipped (_item_envelope_shape's own doing) - a part's own
                # declared face, always Face.FRONT for a cell (occupancy._geometry's
                # own rule, occ._transform's docstring). occ.items has since
                # moved to the item's real, placed reference, which is not
                # what the shape was drawn against, so it is read here, not
                # from occ. Mirror the shape the same way occupancy._transform
                # mirrors the item's real shapes - about its own local x=0 -
                # exactly when its placed face differs from that.
                ref_face = geom.face if kind == "part" else Face.FRONT
                if p.face != ref_face:
                    region_shape = dataclasses.replace(
                        k.shape, points=tuple((-x, y) for x, y in k.shape.points))
                # a part's own rotation turns counter-clockwise on screen
                # (Transform.rotate); a shape's path_at turns a bearing
                # clockwise from the top (cutouts._turned) - negate so a
                # region's stored rotation (its bearing) turns the same way
                # the item actually does, normalised like any other bearing.
                centre, turn, why = p.location, (-p.rotation) % 360.0, None
            elif self._cutout_free(k):
                try:
                    centre, turn = self._slide_cutout(
                        occ, k, illegal=lambda path: self._keepout_unusable(path))
                    why = None
                except ValueError as e:
                    centre, turn, why = self.centre, 0.0, str(e)
            else:
                centre = self._cutout_centre(occ, k)
                turn = self._region_rotation(occ, k, centre)
                why = None
            step = Step(intent.key, "keepout", None, why=intent.why)
            if why:
                plan.findings.append(Finding("fixed", "%s (keepout): %s" % (k.name, why)))
                step.note = why
            else:
                path = (region_shape or k.shape).path_at(centre, turn)
                outside, total = self._points_off_board(path)
                if self._off_board(path):
                    raise ValueError(
                        "keepout %r is wholly off the board, so it forbids nothing: all %d of its "
                        "points are outside the outline. Move it, or remove the declaration."
                        % (k.name, total))
                poly = Cutouts([path]).loops[0]
                nets = frozenset(self.geometry.require_net(a) for a in k.allow if isinstance(a, Net))
                owners = frozenset(fp.ref for a in k.allow if isinstance(a, (Part, Cell))
                                   for fp in members_of(self._item(a)[0]))      # every member: KiCad names each
                admitted = None
                if k.max_height is not None:                    # admitted by height, as allow= admits by name
                    admitted = frozenset(fp.ref for fp in self.geometry.footprints
                                         if (part_height(fp) is not None and part_height(fp) <= k.max_height + 1e-9))
                claims, layer = parts_claim(k.layers)
                if "parts" in k.excludes and claims:
                    tall = ("; parts up to %g mm tall may sit here, and a part with no Pm.Height counts as taller"
                            % k.max_height) if k.max_height is not None else ""
                    occ.reserve(poly, "keepout %r (%s%s)" % (k.name, k.why, tall), allow=nets, owners=owners,
                                layer=layer, admitted=admitted)
                plan.keepouts[k.name] = PlacedKeepout(k.name, poly, centre, turn, k.excludes,
                                                      k.layers, nets, owners | (admitted or frozenset()), k.why)
                step.note = "kept clear at %.2f, %.2f" % (centre.x, centre.y)
                if outside:
                    step.note += "; %d of its %d points are off the board" % (outside, total)
            plan.steps.append(step)
            placed.add(cutout_token(k.name))

        def place_one(obj, why_now=""):
            # The key is taken before anything below changes the declaration.
            ex = self._explore
            key = _reuse.step_key(chain["key"], obj, _reuse.links_on(self, obj),
                                  self._step_extra(obj))
            chain["key"] = key
            position = len(record["steps"])
            if chain["replaying"] and not (position < len(previous) and previous[position]["key"] == key):
                chain["replaying"] = False
            if isinstance(obj, (KeepoutIntent, CutoutIntent)):
                record["steps"].append({"key": key})
                if chain["replaying"]:
                    record["reused"] += 1
                elif record["first_change"] is None and previous is not None:
                    record["first_change"] = getattr(obj, "key", None) or getattr(obj, "name", None)
                if isinstance(obj, KeepoutIntent):
                    settle_keepout(obj)
                else:
                    settle_cutout(obj)
                return
            if getattr(obj, "turned", None) is not None:    # its part is placed by now: needs said so
                ref = self._pad_ref(obj.turned.part)[0]
                obj.rotation = (occ.items[ref].reference.rotation + obj.turned.degrees) % 360.0
            if isinstance(obj.run, CutoutEdge):     # the hole is down by now: read its real stretch
                obj.run = self.cutout(obj.run.name).edge(side=obj.run.side, within=obj.run.within)
                if isinstance(obj.along, (Along, Fraction)):
                    obj.along = obj.along.fraction * obj.run.length
                elif obj.along is not None and not isinstance(obj.along, (int, float)):
                    obj.along = _run_along(self, occ, obj)      # a reference: the place on the edge nearest it
                if obj.rotation is None:            # turned to the way the board faces where it sits
                    obj.rotation, obj.faces_note = self.outward_rotation(
                        obj.item, obj.run.at(obj.along if obj.along is not None else 0.0)[1])
            plan._items[obj.key] = obj.item
            if self._fit and not obj.freedom.decided:
                occ.board_box = self._outline = self._fit_room(occ, plan, obj)
            if chain["replaying"]:
                step = self._replay_settle(occ, plan, previous[position])
                record["steps"].append(previous[position])
                record["reused"] += 1
            else:
                if record["first_change"] is None and previous is not None:
                    record["first_change"] = obj.key
                step, entry = self._recorded_settle(occ, obj, plan, placed)
                entry["key"] = key
                record["steps"].append(entry)
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
            if step.placement is not None and isinstance(obj, PlaceIntent) and not obj.freedom.decided:
                plan.turns[obj.key] = dict(self._turn_of(occ, obj, step.placement, placed), order=len(plan.turns))
            if obj.key in self._lock_notes:
                step.note = (step.note + "; " if step.note else "") + self._lock_notes.pop(obj.key)
            if step.placement is None:
                pass                    # unplaced: left off the board, pulls nothing, blocks nothing
            elif obj.kind == "block":
                occ.commit(obj.item.anchor, step.placement)
                placed.update(fp.ref for fp in obj.item.members)
            else:
                occ.commit(obj.item, step.placement)
                placed.update(fp.ref for fp in members_of(obj.item))
                if obj.kind == "cell":
                    self._cell_placements[obj.key] = step.placement
                    taken = self._stamped_region_cost(occ, obj.item)
                    if taken >= 0.05:
                        step.note = (step.note + "; " if step.note else "") + \
                            "its stamped regions keep parts off %.1f mm2 of board beyond its own parts" % taken
            if progress:
                progress(_fmt(step))
            for r in self._ride_groups.get(obj.key, ()):        # committed with it, in its settle
                rs = next(s for s in reversed(plan.steps) if s.item == r.key)
                if rs.placement is None and r.required and not self.keep_going:
                    raise CriticalUnplaced(r.key, self._no_place_report(occ, r, rs), plan)
                if rs.placement is not None:
                    placed.update(fp.ref for fp in members_of(r.item))
                    if r.turned is not None:
                        r.rotation = rs.placement.rotation      # as a firm Turned item's is set when it is placed
                    if r.kind == "cell":
                        self._cell_placements[r.key] = rs.placement
                if progress:
                    progress(_fmt(rs))
            self._place_fanouts(occ, plan, placed, progress)
            self._place_labels(occ, plan, placed, progress)

        def place_ranked(lo, hi):
            """FIXED and EDGE go down in declaration order: nothing yields to
            them, so their order changes nothing. Searched items are ordered
            by the placer, one choice at a time, re-measured after each."""
            firm = [obj for obj in placements if lo <= obj.rank[0] <= hi and obj.freedom.decided
                    and getattr(obj, "key", None) not in self._rider_of]      # a rider goes with its item
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
                if self._locked(obj) is not None:       # the locked items go in their accepted order
                    ready = sorted((self._lock[o.key].turn, o.index, o) for o in pending
                                   if getattr(o, "key", None) in self._lock and self._locked(o) is not None
                                   and o.needs <= placed)
                    if ready and ready[0][2] is not obj:
                        obj, why_now = ready[0][2], "locked order"
                ex = self._explore
                if ex is not None and obj.key in ex.focus and len(pending) > 1 and self._order_rng.random() < self.settings.explore_swap:
                    other, other_why = self._next_to_place([o for o in pending if o is not obj], occ, placed)
                    if other.key in ex.focus:           # two focused neighbours trade turns
                        obj, why_now = other, (other_why + "; " if other_why else "") + "explore: before " + obj.key
                pending.remove(obj)
                place_one(obj, why_now)

        place_ranked(RANK_FIXED, RANK_EDGE)
        self._check_web(plan)
        self._check_pitch(plan)
        self._plan_copper(occ, ctx, fixed_copper, plan, progress)
        if self._fit:
            # the search's room: round what is decided, or round the origin when nothing is
            decided = self._placed_box(occ, plan)
            room = self.settings.place_fit_room
            grow = decided.inflate(room) if decided is not None else Box(-room, -room, room, room)
            occ.board_box = self._fit_bound(grow)
            self._outline = occ.board_box       # the search's fallback hint and its pockets read it
        # Every searched item is one queue, whatever kind it is: a connector can
        # be the most important thing on a board, and it does not wait behind a
        # tier of cells for being a single part. What it needs decides.
        place_ranked(RANK_CELL, RANK_LOOSE)
        if self.settings.cleanup_enabled:
            before = reuse.get("cleanup") if (reuse and chain["replaying"]) else None
            if before is not None and before.get("key") == chain["key"]:
                self._replay_cleanup(occ, plan, before)
                record["cleanup"] = before
            else:
                record["cleanup"] = self._recorded_cleanup(occ, plan)
                record["cleanup"]["key"] = chain["key"]
        self._plan_copper(occ, ctx, other_copper, plan, progress)
        if routes:
            self._draw_adopted(occ, ctx, plan, routes, progress)
        if self._fit:
            # the frame, now that everything is placed: the content plus the margin, and the planes that follow it
            content = self._placed_box(occ, plan)
            grown = (content or Box(0.0, 0.0, 0.0, 0.0)).inflate(self._fit_margin)
            frame = self._fit_bound(grown)
            self._check_fit_content(occ, plan, frame)
            plan.outline = self._outline = occ.board_box = frame
            self._plan_copper(occ, ctx, [c for c in self._copper if c.index in held], plan, progress)
        self._check_keepouts(plan)
        plan.rudy = self._rudy(occ, plan)
        self._report_links(occ, plan, placed)
        self._report_escapes(occ, plan)
        self._report_undeclared(plan)
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

    def group(self, name: str, items, why: str = "") -> "DeclaredGroup":
        """A KiCad group on the written board holding `items` (Parts), at
        the top level like every group placemat writes, so a hand placement
        moves them as one. It places nothing: the script places the items as
        it wants."""
        if name in self.geometry.cells or name in self._groups:
            raise ValueError("group %r: the board already has a group or cell called %r; pick another name"
                             % (name, name))
        parts = []
        for it in items:
            obj, key, kind = self._item(it)
            if kind == "cell":
                raise ValueError("group %r: %s is a cell, a group of its own; groups on the board are one level "
                                 "(KiCad makes a nested group entered before anything in it moves)" % (name, key))
            if kind != "part":
                raise TypeError("group %r: takes Parts, not %r" % (name, it))
            if obj.ref in parts:
                raise ValueError("group %r: %s is named twice" % (name, key))
            other = next((g.name for g in self._groups.values() if obj.ref in g.parts), None)
            if other is not None:
                raise ValueError("group %r: %s is already in group %r" % (name, key, other))
            parts.append(obj.ref)
        g = DeclaredGroup(name, tuple(parts), why)
        self._groups[name] = g
        return g

    def _check_groups(self) -> None:
        """What a declared group may hold, from what the script places,
        before the search: not a part inside a cell the script places whole
        (that group is written as it stands; group the cell)."""
        if not self._groups:
            return
        whole = {intent.item.name for intent in self._placements() if intent.kind == "cell"}

        def around(cell):                       # a group and every group it sits in
            out = []
            while cell is not None and cell in self.geometry.cells:
                out.append(cell)
                cell = self.geometry.cells[cell].parent
            return out
        for g in self._groups.values():
            for ref in g.parts:
                fp = self.geometry.footprint(ref)
                inside = [c for c in around(fp.cell) if c in whole]
                if inside:
                    raise ValueError("group %r: %s is in cell %r, which the script places whole; group the cell"
                                     % (g.name, fp.inst, inside[0]))

    def _rudy(self, occ: Occupancy, plan: Plan):
        """The placed board's RUDY (congestion.py): its placed pads, the nets
        that are routed (no planes, no free nets), a track and its clearance."""
        from .congestion import rudy
        box = plan.outline or occ.board_box
        if box is None:
            return None
        refs = set()
        for s in plan.steps:
            if s.placement is not None and s.item in plan._items:
                refs |= {fp.ref for fp in members_of(plan._items[s.item])}
        pads = []
        for ref in sorted(refs):
            g = occ.items.get(ref)
            if g is None:
                continue
            for s in g.shapes:
                if s.kind in ("pad", "through") and s.owner == ref:
                    pads.append((s.net, s.box, len(s.layers)))
        classes = list(self.geometry.netclasses.values())
        width = min((c.track_width for c in classes), default=0.2)
        pitch = width + (self.geometry.default_clearance or 0.2)
        return rudy(pads, box, max(1, len(self.geometry.layers)), pitch,
                    skip=self._plane_nets() | self._free_nets)

    def _step(self, i: PlaceIntent, placement, moved_mm: float, note: str) -> Step:
        """A searched or decided item's step, with its priority, freedom and rank."""
        return Step(i.key, i.kind, None if i.freedom.decided else i.priority, placement, moved_mm, note, i.why,
                    freedom=i.freedom, rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)

    def _recorded_settle(self, occ: Occupancy, obj, plan: Plan, placed: set):
        """_settle, and what it did beyond the step it returns, for the next
        run to replay: the occupancy commits made inside it (a block's
        satellites), the steps and findings it added, the nets it was seeded
        on, whether it took a pocket, and the solve it ran."""
        from . import reuse as _reuse
        n_steps, n_findings, n_pocketed = len(plan.steps), len(plan.findings), len(plan.pocketed)
        seeded, solve, items = dict(plan.seeded_by_net), dict(plan.solve), set(plan._items)
        riders = isinstance(obj, PlaceIntent) and obj.key in self._ride_groups
        self._riding = (obj.key, self._rider_check(occ, plan, obj)) if riders else None
        try:
            with _recording_commits(occ) as commits:
                alone = self._riders_alone(occ, plan, obj) if riders else None
                if alone:
                    plan.findings.append(Finding("unplaced", "%s: %s" % (obj.key, alone)))
                    step = self._step(obj, None, 0.0, "UNPLACED: " + alone)
                else:
                    step = self._settle(occ, obj, plan, placed)
                if riders:
                    self._settle_riders(occ, obj, plan, step)
        finally:
            self._riding = None
        entry = {"step": _reuse.step_to_json(step), "commits": commits,
                 "steps": [_reuse.step_to_json(s) for s in plan.steps[n_steps:]],
                 "findings": [_reuse.finding_to_json(f) for f in plan.findings[n_findings:]], "pocketed": plan.pocketed[n_pocketed:],
                 "seeded": {n: c - seeded.get(n, 0) for n, c in plan.seeded_by_net.items() if c != seeded.get(n, 0)},
                 "solve": dict(plan.solve) if plan.solve != solve else None,
                 "items": [[k, "cell", v.name] if isinstance(v, CellGeom) else [k, "fp", v.ref]
                           for k, v in plan._items.items() if k not in items]}
        return step, entry

    def _recorded_cleanup(self, occ: Occupancy, plan: Plan) -> dict:
        """The cleanup pass, and what it did: its commits in order, the steps
        whose placement or note it changed, and plan.cleanup."""
        from . import reuse as _reuse
        was = [(s.placement, s.note) for s in plan.steps]
        with _recording_commits(occ) as commits:
            self._cleanup(occ, plan)
        changed = [[k, _reuse.placement_to_json(s.placement), s.note] for k, s in enumerate(plan.steps)
                   if k < len(was) and (s.placement, s.note) != was[k]]
        return {"commits": commits, "changed": changed, "cleanup": dict(plan.cleanup)}

    def _apply_commits(self, occ: Occupancy, commits):
        """Commit, in order, what _recording_commits recorded."""
        from . import reuse as _reuse
        for (kind, name), placement in commits:
            item = self.geometry.cells[name] if kind == "cell" else self.geometry.footprint(name)
            occ.commit(item, _reuse.placement_from_json(placement))

    def _replay_cleanup(self, occ: Occupancy, plan: Plan, entry: dict):
        from . import reuse as _reuse
        self._apply_commits(occ, entry["commits"])
        for k, placement, note in entry["changed"]:
            plan.steps[k].placement = _reuse.placement_from_json(placement)
            plan.steps[k].note = note
        plan.cleanup = dict(entry["cleanup"])

    def _replay_settle(self, occ: Occupancy, plan: Plan, entry: dict):
        """What _recorded_settle recorded, done again without the search."""
        from . import reuse as _reuse
        self._apply_commits(occ, entry["commits"])
        plan.steps.extend(_reuse.step_from_json(s) for s in entry["steps"])
        plan.findings.extend(_reuse.finding_from_json(f) for f in entry["findings"])
        plan.pocketed.extend(entry["pocketed"])
        for net, c in entry["seeded"].items():
            plan.seeded_by_net[net] += c
        if entry["solve"] is not None:
            plan.solve = dict(entry["solve"])
        for key, kind, name in entry.get("items", ()):
            plan._items[key] = self.geometry.cells[name] if kind == "cell" else self.geometry.footprint(name)
        return _reuse.step_from_json(entry["step"])

    def _fit_bound(self, box: Box) -> Box:
        """`box`, with a fit frame's DECLARED axis (fit=Axis.X or Axis.Y)
        clamped to its number - origin at 0, the same as a sized board's -
        and the fitting axis left as `box` gives it. fit=True (both axes
        fit) leaves it unchanged."""
        if self._fit_axis is Axis.X:            # width fits; height is declared
            return Box(box.left, 0.0, box.right, self._frame_height)
        if self._fit_axis is Axis.Y:            # height fits; width is declared
            return Box(0.0, box.top, self._frame_width, box.bottom)
        return box

    def _check_fit_content(self, occ: Occupancy, plan: "Plan", frame: Box) -> None:
        """fit=Axis.X/Y's declared axis is a mechanical fact, not a
        suggestion: an item whose placed box reaches outside it (the frame
        clamps to the number regardless, per `_fit_bound`) is a finding
        naming the item, not a silent clip."""
        axis = self._fit_axis
        if axis is None:
            return
        lo, hi, which = (frame.top, frame.bottom, "height") if axis is Axis.X else (frame.left, frame.right, "width")
        for step in plan.steps:
            if step.placement is None or step.kind not in ("part", "cell"):
                continue
            item = plan._items[step.item]
            boxes = [sh.box for fp in members_of(item) if fp.ref in occ.items for sh in occ.items[fp.ref].shapes]
            box = Box.union(boxes) if boxes else None
            if box is None:
                continue
            ilo, ihi = (box.top, box.bottom) if axis is Axis.X else (box.left, box.right)
            if ilo < lo - 1e-6 or ihi > hi + 1e-6:
                plan.findings.append(Finding(
                    "setup", "%s: reaches %.2f to %.2f mm, outside the frame's declared %s of %.2f to %.2f mm"
                    % (step.item, ilo, ihi, which, lo, hi)))

    def _fit_room(self, occ: Occupancy, plan: Plan, obj) -> Box:
        """Where a searched item may go on a fit board: round everything placed
        so far (round the origin when nothing is), by `place.fit_room` and the
        item's own longest side, so a part larger than the room still fits."""
        from .board_geometry import members_of
        fps = [obj.item.anchor] + [fp for fp, _ in obj.item.satellites] if obj.kind == "block" else members_of(obj.item)
        span = sum(max(b.width, b.height) for b in
                   (occ.reach_box(fp, Placement(Location(0.0, 0.0), 0.0, Face.FRONT)) for fp in fps))
        content = self._placed_box(occ, plan) or Box(0.0, 0.0, 0.0, 0.0)
        return self._fit_bound(content.inflate(self.settings.place_fit_room + span))

    def _placed_box(self, occ: Occupancy, plan: Plan) -> Box | None:
        """The box round what the plan has placed so far, as the placer
        claims it - each placed part's shapes, the labels reserved for them,
        planned tracks, vias and pours - or None when nothing is. Zones are
        left out: they are sized from the frame, not the frame from them."""
        from .board_geometry import members_of
        boxes = []
        for step in plan.steps:
            if step.placement is None or step.kind not in ("part", "cell"):
                continue
            item = plan._items[step.item]
            for fp in members_of(item):
                if fp.ref in occ.items:
                    boxes += [sh.box for sh in occ.items[fp.ref].shapes]
            if isinstance(item, CellGeom):      # the cell's own tracks, vias and pours, where it now stands
                boxes += [c.box for c in occ.copper if c.owner == item.name]
        boxes += [op.box for op in plan.copper if isinstance(op, (Track, Via, Pour, Text))]
        return Box.union(boxes) if boxes else None

    def _cleanup_movable(self, plan: Plan) -> dict:
        """{step key: footprint} for the parts the cleanup pass may move: a
        searched part placed by the plain search, which nothing else was
        positioned against - no label, and no other declaration whose place
        refers to it."""
        intents = {i.key: i for i in self._placements()}
        held = set()
        for i in self._intents:
            held |= set(getattr(i, "needs", ()) or ())
        for entry in self._labels:
            for obj in (entry[1],) + tuple(entry[12] or ()):
                if isinstance(obj, (PadRef, CellPadRef)):
                    held.add(self._pad_ref(obj)[0])
                else:
                    held |= {fp.ref for fp in members_of(self._item(obj)[0])}
        # A locked item keeps its spot, and inside an explore variant a focused
        # item keeps the spot it drew: that spot is what a lock records.
        kept = set(self._lock_held) | (set(self._explore.focus) if self._explore is not None else set())
        out = {}
        for s in plan.steps:
            i = intents.get(s.item)
            if (s.kind != "part" or s.placement is None or i is None or i.kind != "part"
                    or not self._solvable(i) or i.item.ref in held or s.item in kept):
                continue
            out[s.item] = i.item
        placed = {s.item for s in plan.steps if s.placement is not None}
        for key, (sat, _) in self._cleanup_limits(plan).items():
            if key in placed and sat.ref not in held and key not in kept:
                out[key] = sat
        return out

    def _cleanup_limits(self, plan: Plan) -> dict:
        """{satellite key: (footprint, (its pin, its own pad, mm))} for every
        block's satellites the cleanup pass may move: its pad no further from
        its pin than the declared link's limit, else `place.block_gap_reach`,
        edge to edge. A locked or focused block's satellites stay, and so do
        a block's whose place the script decided (FIXED or EDGE): copper
        planned before the pass may end on them."""
        from .placer import _aimed_at
        kept = set(self._lock_held) | (set(self._explore.focus) if self._explore is not None else set())
        out = {}
        for i in self._placements():
            spec = i.item
            if not isinstance(spec, BlockSpec) or i.key in kept or i.freedom.decided:
                continue
            for k, (sat, net) in enumerate(spec.satellites):
                pin = _aimed_at(spec, k, net)
                own = sat.pad(net)
                link = self._declared_link((sat.ref, own.number), (spec.anchor.ref, pin.number))
                mm = link.limit_mm if link is not None and link.limit_mm is not None else self.settings.place_block_gap_reach
                out[sat.inst] = (sat, ((spec.anchor.ref, pin.number), (sat.ref, own.number), mm))
        return out

    def _cleanup(self, occ: Occupancy, plan: Plan):
        """The cleanup pass (cleanup.py) over the movable parts, its moves
        written back into their steps."""
        from .cleanup import cleanup
        movable = self._cleanup_movable(plan)
        if not movable:
            return
        placed = set()
        for s in plan.steps:
            if s.placement is not None and s.item in plan._items:
                placed |= {fp.ref for fp in members_of(plan._items[s.item])}
        quiet = self._plane_nets() | self._free_nets
        pins = {}
        for fp in self.geometry.footprints:
            if fp.ref in placed:
                for p in fp.pads:
                    if p.net and p.net not in quiet:
                        pins.setdefault(p.net, []).append((fp.ref, p.number))
        pins = {n: v for n, v in pins.items() if len(v) > 1}
        s = self.settings
        intents = {i.key: i for i in self._placements()}
        limits = {k: lim for k, (_, lim) in self._cleanup_limits(plan).items() if k in movable}
        every = (0.0, 90.0, 180.0, 270.0)
        r = cleanup(occ, movable, pins, list(self._links), self.clearance, s.cleanup_passes,
                    s.cleanup_radius, s.cleanup_step,
                    turns={k: self._turns(intents[k]) if k in intents else every for k in movable},
                    limits=limits, settings=s)
        swapped = {}
        for a, b in r.swaps:
            swapped.setdefault(a, []).append(b)
            swapped.setdefault(b, []).append(a)
        for step in plan.steps:
            if step.item not in movable:
                continue
            now = occ.items[movable[step.item].ref].reference
            if now == step.placement:
                continue
            was = step.placement
            step.placement = now
            said = []
            if step.item in swapped:
                said.append("swapped with %s" % ", ".join(sorted(set(swapped[step.item]))))
            # A part's own cost is not comparable from one pass to the next -
            # its neighbours move too - so the step says how far it went, and
            # plan.cleanup the board's cost before and after.
            if step.item in r.moves or not said:
                said.append("moved %.2f mm" % was.location.distance(now.location))
            step.note = (step.note + "; " if step.note else "") + "cleanup: " + "; ".join(said)
        plan.cleanup = {"moves": len(r.moves), "swaps": len(r.swaps), "passes": r.passes,
                        "cost_before": round(r.cost_before, 3), "cost_after": round(r.cost_after, 3)}

    def _settle_in_pocket(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """Nothing this item connects to is placed and no hint was given: put
        it in the biggest free rectangle its envelope fits, trying each
        rotation asked for (and the two orthogonal ones when none was)."""
        if self.settings.place_rotations == "declared":
            rots = list(i.rotations) or [i.rotation, (i.rotation + 90) % 360]
        else:
            rots = list(self._turns(i))
        tried = []
        riders = {}             # a rider's refusal, the first each time it refused a candidate
        for rot in rots:
            env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, i.face))
            for pocket in pockets(occ, env.width, env.height, i.face, step=max(i.step, 0.5)):
                hint = box_centered_placement(occ, i.item, pocket.box.center, rot, i.face)
                result = scan(occ, i.item, hint, max(pocket.box.width, pocket.box.height) / 2, i.step, (rot,), clr,
                              accept=self._accept(i))
                for k, why in result.reasons.items():
                    if k.startswith("rider "):
                        riders.setdefault(k, why)
                if result.chosen is not None:
                    note = "pocket %.1f x %.1f at (%.1f, %.1f): nothing it connects to is placed" % (
                        pocket.box.width, pocket.box.height, pocket.box.center.x, pocket.box.center.y)
                    return self._step(i, result.chosen, 0.0, note)
                tried.append(pocket)
        plan.findings.append(Finding("unplaced", "%s: no pocket fits its %s envelope on the %s face (%d pocket(s) tried)" % (
            i.key, "%.1f x %.1f" % (occ.body_box(i.item, Placement(Location(0, 0), i.rotation, i.face)).width,
                                    occ.body_box(i.item, Placement(Location(0, 0), i.rotation, i.face)).height),
            i.face.value, len(tried)) + "".join("; %s" % why for why in riders.values())))
        return self._step(i, None, 0.0, "UNPLACED: no pocket fits" + "".join("; %s" % why for why in riders.values()))

    def _seeded_pocket(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, hint: Placement, score,
                       rotations, why: str):
        """A seeded item whose scan found nothing: the free pocket nearest the
        seed that it fits, scanned with the same link score, so it lands at
        the end nearest what it connects to. None when no pocket takes it;
        with it, how many pockets there were."""
        seen = []
        for rot in rotations:
            env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, i.face))
            for pocket in pockets(occ, env.width, env.height, i.face, step=max(i.step, 0.5)):
                if all(pocket.box != p.box for p, _ in seen):
                    seen.append((pocket, rot))
        at = hint.location

        def gap(pocket):
            b = pocket.box
            return math.hypot(max(b.left - at.x, 0.0, at.x - b.right), max(b.top - at.y, 0.0, at.y - b.bottom))
        for k in sorted(range(len(seen)), key=lambda k: (round(gap(seen[k][0]), 6), k)):
            pocket, rot = seen[k]
            start = box_centered_placement(occ, i.item, pocket.box.center, rot, i.face)
            result = scan(occ, i.item, start, max(pocket.box.width, pocket.box.height) / 2, i.step,
                          tuple(rotations), clr, score=score, accept=self._accept(i))
            if result.chosen is not None:
                plan.pocketed.append(i.key)
                note = "%s; took the pocket %.1f x %.1f at (%.1f, %.1f), %.1f mm from the seed" % (
                    why, pocket.box.width, pocket.box.height, pocket.box.center.x, pocket.box.center.y, gap(pocket))
                return self._step(i, result.chosen,
                            result.moved_mm, note), len(seen)
        return None, len(seen)

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

    def _stamped_region_cost(self, occ, cell, cell_mm: float = 0.05) -> float:
        """How much board a cell's parts-excluding regions keep other parts
        off beyond what its own members claim, sampled on a `cell_mm` grid:
        what a stamped keepout costs the board that stamps it."""
        from .geometry import point_in_polygon
        regions = [r.poly for r in occ.reservations if r.source == "cell:%s" % cell.name]
        if not regions:
            return 0.0
        own = []
        for fp in cell.members:
            g = occ.items.get(fp.ref)
            if g is not None:
                own += [s.box for s in g.shapes if s.kind == "courtyard"] or [g.reach or g.body]
        n = 0
        for poly in regions:
            box = Box.of_points(poly)
            y = box.top + cell_mm / 2
            while y < box.bottom:
                x = box.left + cell_mm / 2
                while x < box.right:
                    if point_in_polygon((x, y), poly) and not any(o.left <= x <= o.right and o.top <= y <= o.bottom for o in own):
                        n += 1
                    x += cell_mm
                y += cell_mm
        return n * cell_mm * cell_mm

    def _place_fanouts(self, occ, plan: Plan, placed: set, progress):
        """Every fanout whose part is down and not yet banded: one reservation
        per side, on the part's face, open to the part, its block's
        satellites and what is linked SHORT to its pads."""
        done = plan.__dict__.setdefault("_fanned", set())
        for key, fp, depth, sides, why in self._fanouts:
            if key in done or fp.ref not in placed or fp.ref not in occ.items:
                continue
            done.add(key)
            g = occ.items[fp.ref]
            body, face = g.body, g.reference.face
            pads = [s.box for s in g.shapes if s.kind in ("pad", "through") and s.owner == fp.ref]
            allowed = {fp.ref}
            for i in self._intents:
                spec = getattr(i, "item", None)
                if isinstance(spec, BlockSpec) and spec.anchor.ref == fp.ref:
                    allowed |= {sat.ref for sat, _ in spec.satellites}
            for l in self._links:
                if int(l.weight) >= int(LinkWeight.SHORT) and fp.ref in (l.a[0], l.b[0]):
                    allowed |= {l.a[0], l.b[0]}
            rows = {Edge.NORTH: [b for b in pads if b.top <= body.top + 1.0],
                    Edge.SOUTH: [b for b in pads if b.bottom >= body.bottom - 1.0],
                    Edge.WEST: [b for b in pads if b.left <= body.left + 1.0],
                    Edge.EAST: [b for b in pads if b.right >= body.right - 1.0]}
            notes = []
            for side in (Edge.NORTH, Edge.SOUTH, Edge.WEST, Edge.EAST):
                row = rows[side]
                if not row or (sides is not None and side not in sides):
                    continue
                if side is Edge.NORTH:
                    top = min(b.top for b in row); band = Box(min(b.left for b in row), top - depth, max(b.right for b in row), top)
                elif side is Edge.SOUTH:
                    bot = max(b.bottom for b in row); band = Box(min(b.left for b in row), bot, max(b.right for b in row), bot + depth)
                elif side is Edge.WEST:
                    left = min(b.left for b in row); band = Box(left - depth, min(b.top for b in row), left, max(b.bottom for b in row))
                else:
                    right = max(b.right for b in row); band = Box(right, min(b.top for b in row), right + depth, max(b.bottom for b in row))
                occ.reserve(band, "fanout of %s (%s side)" % (key, side.name.lower()), owners=allowed, layer=face.copper)
                notes.append(side.name.lower())
            note = "%s side%s kept for its pins, %.2f mm deep" % (", ".join(notes) or "no", "" if len(notes) == 1 else "s", depth)
            plan.steps.append(Step("fanout " + key, "copper", Priority.DEFAULT, None, 0.0, note, why, 1))
            if progress:
                progress("%-28s copper  fanout   %s" % ("fanout " + key, note))

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
                        plan.findings.append(Finding("label", "%s: sits on %s" % (key, h)))
        def box_of(item):
            refs = self._label_refs(item)
            if isinstance(item, (PadRef, CellPadRef)):
                owner, number, _, _ = self._pad_ref(item)
                return Box.union([s.box for s in _pad_shapes(self, occ, item)]), occ.items[owner].reference.face
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
            # The reach holds the part's own silk: a label nearer than the board's
            # silk clearance is a silk overlap to KiCad, whatever gap was asked for.
            gap = max(gap, self.geometry.silk_clearance)
            op = _label_op(text, box, face, side, gap, align, size, thick, knockout, rotation, line)
            plan.copper.append(op)
            own = {occ.who(r) for r in refs}
            hits = sorted({occ.who(r) for r, g in occ.items.items()
                           if g.reference.face is face and r not in occ.pending and (g.reach or g.body).overlaps(op.box)} - own)
            note = "%s of %s" % (side.name.lower(), key.split(" ", 2)[1])
            if hits:
                plan.findings.append(Finding("label", "%s: sits on %s" % (key, ", ".join(hits))))
                note += "; sits on " + ", ".join(hits)
            if reserve:
                occ.reserve(op.box, "label %s" % key.split(" ", 1)[1], layer=face.copper)     # the text's own box, no more
                # The reservation keeps bodies off the text; as silk it also keeps
                # a later part's silk the silk clearance away where the envelope
                # claims silk, as KiCad checks it.
                occ.add_copper([Shape(key, "silk", frozenset([face]), frozenset(), "", box_polygon(op.box), op.box)])
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
        ctx.batch_tracks = []
        for c in sorted(intents, key=lambda c: c.index):
            if c.key.startswith("finger"):
                deferred.append(c)          # a finger is cut by the tracks planned in this batch
                continue
            ctx.ops_at[c.index] = c.plan(ctx)
            for op in ctx.ops_at[c.index]:
                (tracks if isinstance(op, Track) else others).append((c, op))
                if isinstance(op, Track):
                    ctx.batch_tracks.append(op)     # a later FreeSpot in this batch judges against it
        entries = [(op, c.priority.rank, c.bridge) for c, op in tracks]
        ops, notes, findings = resolve_bridges(entries, ctx.fixed_tracks, self.via_drill, self.via_size,
                                               self.settings.copper_bridge_half)
        plan.findings += findings + [Finding("copper", n) for n in ctx.notes]
        ctx.notes = []
        ctx.planned_tracks += [op for op in ops if isinstance(op, Track)]
        for c in deferred:
            ctx.ops_at[c.index] = c.plan(ctx)
            for op in ctx.ops_at[c.index]:
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
        shapes, batch = [], []
        for op in all_ops:
            plan.copper.append(op)
            shape = _shape_of(op)
            if shape is None:
                continue
            # A swallow pour is drawn exactly as declared here, but the writer (kicad/write.py's
            # _draw_pour) pulls it back from every other net's copper to the netclass clearance
            # before saving it - and placemat's geometry (geometry.py) and its native module have
            # no polygon subtract to compute that pull-back here too. A clearance finding measured
            # against this raw shape would report a problem the written board never has, so it is
            # left out; the raw shape still goes into the occupancy below, so it stays an obstacle
            # for copper planned after it, the same as the writer keeps it one.
            skip_findings = isinstance(op, Pour) and op.swallow_pads
            if not skip_findings:
                hits = occ.copper_conflicts(shape)
                # and this batch's own copper planned before it, which reaches the occupancy only
                # once the batch is done: a track of one net through a via of another, both planned
                # together. Tracks that cross are the bridging's to settle, and a swallow pour's
                # clearance is the writer's, as above.
                for earlier, o in batch:
                    if o.net == shape.net or not shape.box.overlaps(o.box, gap=1.0):
                        continue
                    if isinstance(earlier, Pour) and earlier.swallow_pads:
                        continue
                    if isinstance(op, Track) and isinstance(earlier, Track) and segments_intersect(
                            (op.start.x, op.start.y), (op.end.x, op.end.y),
                            (earlier.start.x, earlier.start.y), (earlier.end.x, earlier.end.y)):
                        continue
                    why = occ._conflict(shape, o, None, exact=True)
                    if why:
                        hits.append(why)
                for hit in hits:
                    note = "copper %s: %s" % (op.net, hit)
                    if isinstance(op, Track) and op.chamfer_cut:
                        mx, my = (op.start.x + op.end.x) / 2.0, (op.start.y + op.end.y) / 2.0
                        note += "; the 45 of its chamfer at (%.2f, %.2f); a smaller chamfer= there keeps clear" % (mx, my)
                    plan.findings.append(Finding("copper", note))
            batch.append((op, shape))
            shapes.append(shape)
            if isinstance(op, Via):
                shapes.append(hole_shape("", op.at, op.drill, op.net))     # what is placed after keeps its holes clear
        occ.add_copper(shapes)
        if any(c.freedom.decided for c in intents):
            ctx.fixed_tracks += [op for op in ops]
        for key, (prio, n, why, freedom) in by_key.items():
            note = "%d op(s)" % n + ("; in the pad: filled or plugged at the fab" if key.startswith("vias ") else "")
            step = Step(key, "copper", prio, None, 0.0, note, why, n, freedom=freedom)
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
        self._waited = {}
        searched = [i for i in self._placements() if not i.freedom.decided]
        if not searched:
            return

        drawn = occ.envelope != "courtyard"

        def claimed(item) -> float:
            """The area the envelope claims: the courtyard, or in a drawn
            envelope the box round every shape the item claims."""
            if not drawn:
                return item.courtyard_box.area
            return Box.union([s.box for s in occ._geometry(item).shapes]).area

        def measure(i):
            if i.kind == "cell":
                parts, area = list(i.item.members), claimed(i.item)
            elif i.kind == "block":
                parts = [i.item.anchor] + [fp for fp, _ in i.item.satellites]
                area = sum(claimed(fp) for fp in parts)
            else:
                parts, area = [i.item], claimed(i.item)
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
        accept = self._accept(i)
        for along in candidates:
            p = placement_at(along)
            why = occ.legal(i.item, p, clr, others=others,
                            past_edge=(i.edge is not None or i.run is not None or i.rim == "rim")
                            and i.clearance < self.keep_in)
            if why is None and accept is not None:
                why = accept(p)
                if why is not None:
                    key = why.split(":")[0]         # a rider, named: scan() counts it the same way
                    rejected[key] += 1
                    reasons.setdefault(key, why)
                    continue
            if why is None:
                moved = abs(along - ideal)
                note = what
                if moved > 1e-9:
                    note += "; slid %.2f %s from its slot: %s" % (moved, units, next(iter(reasons.values()), ""))
                return self._step(i, p, moved, note)
            key = _reason_key(why)
            rejected[key] += 1
            reasons.setdefault(key, why)
        plan.findings.append(Finding("unplaced", "%s: no room anywhere %s (%s)%s" % (
            i.key, what, ", ".join("%s x%d" % kv for kv in rejected.most_common(3)),
            "".join("; %s" % why for k, why in reasons.items() if k.startswith("rider ")))))
        return self._step(i, None, 0.0, "UNPLACED: " + "; ".join(reasons.values()))

    def _slide_block(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec, ideal: float, lo: float, hi: float,
                     anchor_at, what: str, step: float | None = None, units: str = "mm") -> Step:
        """_slide, for a block: a candidate is legal only once the whole
        block lays out from the anchor `anchor_at(along)` gives, so each is
        checked with layout_block rather than occ.legal on one item."""
        step = step if step is not None else max(i.step, 0.2)
        n = int((hi - lo) / step) + 1
        candidates = sorted({min(max(ideal + d * step * sgn, lo), hi) for d in range(n) for sgn in (1, -1)},
                            key=lambda a: (abs(a - ideal), a))
        rejected: Counter = Counter()
        reasons: dict = {}
        for along in candidates:
            members, why = layout_block(occ, spec, anchor_at(along), clr,
                                        past_edge=(i.edge is not None or i.run is not None or i.rim == "rim")
                                        and i.clearance < self.keep_in)
            if members is not None:
                moved = abs(along - ideal)
                note = what
                if moved > 1e-9:
                    note += "; slid %.2f %s from its slot" % (moved, units)
                return self._commit_block(occ, spec, members, i, plan, note)
            key = _reason_key(why)
            rejected[key] += 1
            reasons.setdefault(key, why)
        plan.findings.append(Finding("unplaced", "%s: no room anywhere %s (%s)" % (
            i.key, what, ", ".join("%s x%d" % kv for kv in rejected.most_common(3)))))
        return self._commit_block(occ, spec, {}, i, plan, "UNPLACED: " + "; ".join(reasons.values()))

    def _settle_block_along_edge(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        ideal = self._edge_slot(i, occ)
        box = occ.board_box
        lo, hi = (box.left, box.right) if i.edge in (Edge.NORTH, Edge.SOUTH) else (box.top, box.bottom)
        return self._slide_block(occ, i, plan, clr, spec, ideal, lo, hi,
                                 lambda along: edge_placement(occ, spec.anchor, i.edge, along, i.rotation, i.clearance, i.face),
                                 "along the %s edge" % i.edge.name.lower())

    def _settle_block_along_run(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        run = i.run
        fellows = [x for x in self._placements() if x.run is i.run and x.along is None
                   and not x.freedom.decided]
        k, n = fellows.index(i), max(len(fellows), 1)
        ideal = run.length * (k + 1) / (n + 1)
        shape = occ.board_shape or self._shaped()

        def at(along):
            rot = self.outward_rotation(spec.anchor, run.at(along)[1])[0] if i.outward else i.rotation
            return run_placement(occ, spec.anchor, shape, run, along, i.clearance, rot, i.face)
        return self._slide_block(occ, i, plan, clr, spec, ideal, 0.0, run.length, at,
                                 "along the run facing %.0f degrees" % run.facing)

    def _settle_block_round_rim(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        disc = self._disc("the same place is OnEdge(board.edge(facing=...))")
        bore = i.rim == "bore"
        ideal = self._round_slot(i)
        r = max(disc.bore if bore else disc.radius, 1e-6)

        def at(angle):
            rot = self.outward_rotation(spec.anchor, angle + (180.0 if bore else 0.0))[0] if i.outward else i.rotation
            return disc_placement(occ, spec.anchor, disc, angle, i.clearance, rot, i.face, bore=bore)
        return self._slide_block(occ, i, plan, clr, spec, ideal, ideal - 180.0, ideal + 180.0, at,
                                 "round the %s" % ("bore" if bore else "rim"),
                                 step=math.degrees(max(i.step, 0.2) / r), units="deg")

    def _settle_block_round_ring(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        centre = self.centre if i.about is None else _locate(self, occ, i.about)
        ideal = self._round_slot(i)
        r = max(float(i.radius_at), 1e-6)

        def at(angle):
            return box_centered_placement(occ, spec.anchor, polar_point(centre, angle, r), i.rotation, i.face)
        return self._slide_block(occ, i, plan, clr, spec, ideal, ideal - 180.0, ideal + 180.0, at,
                                 "round the %.2f mm ring" % r, step=math.degrees(max(i.step, 0.2) / r), units="deg")

    def _settle_block_along_spoke(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        centre = self.centre if i.about is None else _locate(self, occ, i.about)
        if isinstance(self._shape, Disc) and centre == self._shape.centre:
            lo, hi = self._shape.bore + self.keep_in, self._shape.radius - self.keep_in
        else:
            box = occ.board_box
            lo, hi = 0.0, max(box.width, box.height)
        ideal = (lo + hi) / 2.0

        def at(r):
            return box_centered_placement(occ, spec.anchor, polar_point(centre, i.angle, r), i.rotation, i.face)
        return self._slide_block(occ, i, plan, clr, spec, ideal, lo, hi, at, "out along the %.0f degree spoke" % i.angle)

    def _settle_block_along_line(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec, placed: set) -> Step:
        axis = "x" if i.pin_x is not None else "y"
        pinned = _coord(self, occ, i.pin_x if axis == "x" else i.pin_y, axis)
        fellows = [o for o in self._placements() if (o.pin_x if axis == "x" else o.pin_y) is not None
                   and (o.pin_x if axis == "x" else o.pin_y) == (i.pin_x if axis == "x" else i.pin_y)]
        k, n = fellows.index(i), len(fellows)
        box = occ.board_box
        lo, hi = (box.top, box.bottom) if axis == "x" else (box.left, box.right)
        lo, hi = lo + self.keep_in, hi - self.keep_in
        ideal = lo + (hi - lo) * (k + 1) / (n + 1)
        targets = self._targets(spec.anchor, occ, placed)
        seeded = ""
        if targets:
            hint = self._seed_hint(spec.anchor, occ, targets, i.rotation, i.face)
            anchor = hint.location if i.pinned_by == "at" else occ.body_box(spec.anchor, hint).center
            ideal = min(max(anchor.y if axis == "x" else anchor.x, lo), hi)
            seeded = "; across from what it connects to"

        def at(along):
            point = Location(pinned, along) if axis == "x" else Location(along, pinned)
            if i.pinned_by == "at":
                return Placement(point, i.rotation, i.face)
            return box_centered_placement(occ, spec.anchor, point, i.rotation, i.face)
        return self._slide_block(occ, i, plan, clr, spec, ideal, lo, hi, at, "on the line %s = %.2f%s" % (axis, pinned, seeded))

    def _settle_along_line(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, placed: set = frozenset()) -> Step:
        """x or y pinned, the other free: the item's body centre sits on the
        pinned line and slides along it to the nearest legal spot, from the
        point across from what it connects to when any of that is placed,
        else from an even share of the line with the items pinned to the
        same value."""
        axis = "x" if i.pin_x is not None else "y"
        pinned = _coord(self, occ, i.pin_x if axis == "x" else i.pin_y, axis)
        fellows = [o for o in self._placements() if (o.pin_x if axis == "x" else o.pin_y) is not None
                   and (o.pin_x if axis == "x" else o.pin_y) == (i.pin_x if axis == "x" else i.pin_y)]
        k, n = fellows.index(i), len(fellows)
        box = occ.board_box
        lo, hi = (box.top, box.bottom) if axis == "x" else (box.left, box.right)
        lo, hi = lo + self.keep_in, hi - self.keep_in
        ideal = lo + (hi - lo) * (k + 1) / (n + 1)
        targets = self._targets(i.item, occ, placed)
        seeded = ""
        if targets:
            hint = self._seed_hint(i.item, occ, targets, i.rotation, i.face)
            anchor = hint.location if (i.pinned_by == "at" and i.kind != "cell") else occ.body_box(i.item, hint).center
            ideal = min(max(anchor.y if axis == "x" else anchor.x, lo), hi)
            seeded = "; across from what it connects to"

        def at(along):
            point = Location(pinned, along) if axis == "x" else Location(along, pinned)
            if i.pinned_by == "at" and i.kind != "cell":
                return Placement(point, i.rotation, i.face)
            return box_centered_placement(occ, i.item, point, i.rotation, i.face)
        return self._slide(occ, i, plan, clr, ideal, lo, hi, at, "on the line %s = %.2f%s" % (axis, pinned, seeded))

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
        centre = self.centre if i.about is None else _locate(self, occ, i.about)
        ideal = self._round_slot(i)
        r = max(float(i.radius_at), 1e-6)

        def at(angle):
            return box_centered_placement(occ, i.item, polar_point(centre, angle, r), i.rotation, i.face)
        return self._slide(occ, i, plan, clr, ideal, ideal - 180.0, ideal + 180.0, at,
                           "round the %.2f mm ring" % r, step=math.degrees(max(i.step, 0.2) / r), units="deg")

    def _settle_along_spoke(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides out along its bearing, from
        the bore's keep-in (or the centre) to as far as the board reaches."""
        centre = self.centre if i.about is None else _locate(self, occ, i.about)
        if isinstance(self._shape, Disc) and centre == self._shape.centre:
            lo, hi = self._shape.bore + self.keep_in, self._shape.radius - self.keep_in
        else:
            box = occ.board_box
            lo, hi = 0.0, max(box.width, box.height)     # the board's own keep-in prunes what is too far
        ideal = (lo + hi) / 2.0

        def at(r):
            return box_centered_placement(occ, i.item, polar_point(centre, i.angle, r), i.rotation, i.face)
        return self._slide(occ, i, plan, clr, ideal, lo, hi, at, "out along the %.0f degree spoke" % i.angle)

    def _step_extra(self, obj) -> str:
        """What else decides a step, for its reuse key: an explore variant's
        seed for a focused item, a lock entry for a locked one."""
        from . import reuse as _reuse
        key = getattr(obj, "key", None)
        ex = self._explore
        riders = self.__dict__.get("_ride_groups", {}).get(key)
        # the items riding it are settled in its step: their declarations and links decide it too
        rides = "" if not riders else "riders:" + _reuse.canonical(
            [[r, _reuse.links_on(self, r)] for r in riders])
        if ex is not None and key in ex.focus:
            return "explore:%d" % ex.seed + rides
        entry = self._lock.get(key)
        return ("lock:%r" % (entry,) if entry is not None else "") + rides

    def _locked(self, i):
        """The item's lock entry, unless an explore variant is varying it."""
        ex = self._explore
        if ex is not None and i.key in ex.focus:
            return None
        return self._lock.get(i.key)

    def _anchor_pad(self, item, occ: Occupancy, placed: set):
        """The placed pad an item depends on most: its strongest connection
        (a declared link's weight, else a pulling net's), ties to the lowest
        (refdes, pad number)."""
        quiet = self._plane_nets() | self._free_nets
        fps = item.members if isinstance(item, CellGeom) else (item,)
        own = {fp.ref for fp in fps}
        best = None
        for fp in fps:
            for p in fp.pads:
                if not p.net:
                    continue
                for other in self.geometry.pads_on_net(p.net):
                    if other.owner in own or other.owner not in placed:
                        continue
                    link = self._declared_link((fp.ref, p.number), (other.owner, other.number))
                    if p.net in quiet and link is None:
                        continue
                    w = link.weight if link is not None else int(LinkWeight.DEFAULT)
                    if w <= 0:
                        continue
                    k = (-int(w), other.owner, other.number)
                    if best is None or k < best:
                        best = k
        return None if best is None else (best[1], best[2])

    def _turn_of(self, occ: Occupancy, i, placement: Placement, placed: set) -> dict:
        """What a lock entry needs of an item's turn: where it went, and the
        pad it depends on with its part's rotation and face at that moment."""
        item = i.item.anchor if i.kind == "block" else i.item
        anchor = self._anchor_pad(item, occ, placed)
        turn = {"placement": placement, "anchor": anchor}
        if anchor is not None:
            g = occ.items[anchor[0]]
            turn.update(anchor_at=occ.pad_location(*anchor), anchor_rotation=g.reference.rotation,
                        anchor_face=g.reference.face.value)
        return turn

    def _lock_spot(self, occ: Occupancy, i, plan: Plan):
        """(placement, drift_from) for a locked item, or (None, None) after
        noting why its entry was released."""
        from . import lock as _lock
        entry = self._locked(i)
        if entry is None:
            return None, None
        if entry.declaration != _lock.declaration_digest(self, i) and \
                entry.declaration != _lock.declaration_digest(self, i, ordered=False) and \
                entry.declaration != _lock.declaration_digest(self, i, legacy=True):
            self._lock_notes[i.key] = "lock: released - its declaration changed since it was accepted"
            return None, None
        spot, why = _lock.placement_of(entry, occ)
        if spot is None:
            self._lock_notes[i.key] = "lock: released - " + why
            return None, None
        return spot, spot

    def _settle_locked(self, occ: Occupancy, i, plan: Plan, clr):
        """A locked part or cell: at its locked spot when that is legal, else
        at the nearest legal spot round it, saying how far it drifted; None
        when there is no entry or it was released."""
        spot, _ = self._lock_spot(occ, i, plan)
        if spot is None:
            return None
        held = scan(occ, i.item, spot, 0.0, i.step, (spot.rotation,), clr, accept=self._accept(i))
        self._lock_held.add(i.key)
        if held.chosen is not None:
            return self._step(i, held.chosen, 0.0, "held by lock")
        body = occ._geometry(i.item).body
        radius = max(i.radius, body.width, body.height)
        drift = scan(occ, i.item, spot, radius, i.step, (spot.rotation,), clr, accept=self._accept(i))
        if drift.chosen is None:
            self._lock_held.discard(i.key)
            self._lock_notes[i.key] = "lock: released - no legal spot within %.1f mm of its locked spot" % radius
            return None
        d = drift.chosen.location.distance(spot.location)
        first = next(iter(held.reasons.values()), "")
        return self._step(i, drift.chosen, d, "lock: drifted %.2f mm from its locked spot%s" % (d, (": " + first) if first else ""))

    def _pick(self, i):
        """An explore variant's draw for a focused item, else None (the best)."""
        ex = getattr(self, "_explore", None)
        if ex is None or i.key not in ex.focus:
            return None
        import random as _random
        from .explore import draw
        rng = _random.Random("%d:%s" % (ex.seed, i.key))
        s = self.settings
        return lambda cands: draw(cands, rng, s.explore_slack, s.explore_rank_power)

    def _turns(self, i: PlaceIntent) -> tuple:
        """The rotations a search may take an item at: the list the script
        gave, else the one rotation it gave, else - for a part, with
        `[place] rotations = "all"` - all four from its own. A cell's sides
        are declared and a block is laid from its anchor: each keeps its one."""
        if i.rotations:
            return tuple(i.rotations)
        if i.rotation_given or i.kind != "part" or self.settings.place_rotations != "all":
            return (i.rotation,)
        return tuple((i.rotation + d) % 360 for d in (0, 90, 180, 270))

    def _no_pocket_note(self, occ: Occupancy, i: PlaceIntent) -> str:
        """A search cannot succeed where no free rectangle holds the item's
        envelope at any of its rotations: say so instead of scanning."""
        if occ.board_box is None:
            return ""
        envs = []
        for rot in (self._turns(i)):
            env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, i.face))
            if pockets(occ, env.width, env.height, i.face, step=max(i.step, 0.5), limit=1, covered=True):
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
            if occ.envelope == "courtyard":
                area = sum(s.box.area for it in parts for s in occ._geometry(it).shapes
                           if s.kind == "courtyard")
            else:
                area = sum(Box.union([s.box for s in occ._geometry(it).shapes]).area for it in parts)
            pull = sum(w for it in parts for _, _, w in self._targets(it, occ, placed))
            return self._rank_score.get(obj.key, 0.0), pull, area

        # An item searched round a pad (a Near on a PadRef) waits while
        # the item holding that pad is still to be searched: its hint is where
        # the pad lands, not where the generator parked it. A cycle waits for
        # nothing rather than for ever.
        holds = {o.key: {fp.ref for fp in (o.item.members if o.kind == "block" else members_of(o.item))}
                 | {fp.ref for r in self._ride_groups.get(o.key, ()) for fp in members_of(r.item)}
                 for o in pending}
        ready = [o for o in pending
                 if not any(o.needs & refs for k, refs in holds.items() if k != o.key)] or pending
        measured = {o.key: measure(o) for o in pending}
        # Of two linked items neither placed, the one with more placed
        # connections goes first: the other is then seeded on it, the part
        # the link joins it to, instead of on whatever else it touches.
        waits = self._link_waits(pending, {k: m[1] for k, m in measured.items()})
        for k, partner in waits.items():
            self._waited.setdefault(k, partner)
        free = [o for o in ready if o.key not in waits] or ready
        scored = sorted(((measured[o.key], o) for o in free),
                        key=lambda m: (-m[1].priority.rank, -m[0][0], -m[0][1], -m[0][2], m[1].key))
        (score, pull, area), obj = scored[0]
        # A ranked item's step is tagged with its rank already; only an unranked
        # one needs saying why it went next.
        why = "" if obj.key in self._rank_note else "next: largest (%.0f mm2)" % area
        if obj.key in self._waited:
            partner = self._waited[obj.key]
            why = (why + "; " if why else "") + "waited for %s, the item it is linked to with more placed connections" % (
                partner)
            other = next((o for o in self._placements() if o.key == partner), None)
            if other is not None and obj.priority.rank > other.priority.rank:
                # the wait comes before the tier: say what it overrode
                why += " (its own priority %s set aside for the link)" % obj.priority.name.lower()
        return obj, why

    def _link_waits(self, pending: list, pull: dict) -> dict:
        """{item key: the linked partner it waits for}, over declared links
        between two pending items: the one with less pull toward what is
        placed waits. Level pull waits for nothing."""
        owner = {}
        for o in pending:
            for fp in (o.item.members if o.kind in ("block", "cell") else (o.item,)):
                owner[fp.ref] = o
        waits = {}
        for link in self._links:
            if link.weight <= 0:
                continue
            a, b = owner.get(link.a[0]), owner.get(link.b[0])
            if a is None or b is None or a is b:
                continue
            pa, pb = pull[a.key], pull[b.key]
            if abs(pa - pb) > 1e-9:
                slow, fast = (a, b) if pa < pb else (b, a)
                waits.setdefault(slow.key, fast.key)
        return waits

    def _commit_block(self, occ: Occupancy, spec, members: dict, i: PlaceIntent, plan: Plan, note: str) -> Step:
        """A block's members once `members` is known (possibly {}: nothing
        legal). The satellites commit here; the anchor commits in the outer
        resolve loop, from the step this returns, the same as any item's."""
        from .placer import slide_note
        slid = {sat.inst: slide_note(occ, spec, members, k) for k, (sat, _) in enumerate(spec.satellites)}
        for fp in spec.members:
            if fp.inst in members and fp is not spec.anchor:
                plan._items[fp.inst] = fp
                member_note = "in %s" % i.key + ("; %s" % slid[fp.inst] if slid.get(fp.inst) else "")
                plan.steps.append(Step(fp.inst, "part", i.priority, members[fp.inst], 0.0, member_note))
                occ.commit(fp, members[fp.inst])
        plan._items[spec.anchor.inst] = spec.anchor
        anchor_at = members.get(spec.anchor.inst)
        plan.steps.append(Step(spec.anchor.inst, "part", i.priority, anchor_at, 0.0, "anchor of %s" % i.key))
        return self._step(i, anchor_at, 0.0, note)

    def _settle_block(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set) -> Step:
        """A block honours every at= form a part does: the anchor's point is
        worked out the same way _settle works out a part's (ported below,
        against spec.anchor for the measurements), and the whole block is
        then laid out from it with layout_block - once for a decided place,
        or at each candidate of a search with one freedom left."""
        spec = i.item
        clr = self.clearance
        if i.freedom.decided:
            if i.at is not None:
                anchor = Placement(_locate(self, occ, i.at), i.rotation, i.face)
            elif i.center is not None:
                anchor = box_centered_placement(occ, spec.anchor, _locate(self, occ, i.center), i.rotation, i.face)
            elif i.run is not None:
                along = _run_along(self, occ, i)
                rot = self.outward_rotation(spec.anchor, i.run.at(along)[1])[0] if i.rotation is None else i.rotation
                anchor = run_placement(occ, spec.anchor, occ.board_shape or self._shaped(), i.run,
                                       along, i.clearance, rot, i.face)
            elif i.rim is not None:
                anchor = disc_placement(occ, spec.anchor, self._disc("the same place is "
                                                                     "OnEdge(board.edge(facing=...))"),
                                        i.angle, i.clearance, i.rotation, i.face, bore=i.rim == "bore")
            else:
                if isinstance(i.along, _RowSlot):
                    along = i.along.resolve(self, occ)
                elif isinstance(i.along, _EdgeFraction):
                    along = self._edge_fraction(i.edge, occ, i.along.fraction)
                    if i.along.anchor in ("start", "end"):
                        reach = occ.reach_box(spec.anchor, Placement(Location(0.0, 0.0), i.rotation, i.face))
                        half = (reach.width if i.edge in (Edge.NORTH, Edge.SOUTH) else reach.height) / 2.0
                        along += half if i.along.anchor == "start" else -half
                else:
                    along = _coord(self, occ, i.along, "x" if i.edge in (Edge.NORTH, Edge.SOUTH) else "y")
                anchor = edge_placement(occ, spec.anchor, i.edge, along, i.rotation, i.clearance, i.face)
            members, why = layout_block(occ, spec, anchor, clr,
                                        past_edge=(i.edge is not None or i.run is not None or i.rim == "rim")
                                        and i.clearance < self.keep_in)
            if members is None:
                plan.findings.append(Finding("fixed", "%s (%s): %s" % (i.key, i.freedom.value, why)))
                members = {spec.anchor.inst: anchor}
            return self._commit_block(occ, spec, members, i, plan, why or "")
        if i.run is not None:
            return self._settle_block_along_run(occ, i, plan, clr, spec)
        if i.rim is not None:
            return self._settle_block_round_rim(occ, i, plan, clr, spec)
        if i.radius_at is not None:
            return self._settle_block_round_ring(occ, i, plan, clr, spec)
        if i.angle is not None:
            return self._settle_block_along_spoke(occ, i, plan, clr, spec)
        if i.edge is not None:
            return self._settle_block_along_edge(occ, i, plan, clr, spec)
        if i.pin_x is not None or i.pin_y is not None:
            return self._settle_block_along_line(occ, i, plan, clr, spec, placed)
        # No place left at all: searched from a lock, a hint, what it connects to, or the board's own middle.
        spot, _ = self._lock_spot(occ, i, plan)
        locked = None
        if spot is not None:
            locked = scan_block(occ, spec, spot, 0.0, i.step, (spot.rotation,), clr)[0]
            if locked is None:
                body = occ._geometry(spec.anchor).body
                locked = scan_block(occ, spec, spot, max(i.radius, body.width, body.height), i.step,
                                    (spot.rotation,), clr)[0]
                if locked is None:
                    self._lock_notes[i.key] = "lock: released - no legal spot round its locked spot"
        targets = self._targets(spec.anchor, occ, placed)
        current = occ._geometry(spec.anchor).reference
        if locked is not None:
            self._lock_held.add(i.key)
            _, anchor, members = locked
            d = anchor.location.distance(spot.location)
            note = "block of %d laid out from the anchor's pads; %s" % (
                len(members), "held by lock" if d < 1e-9 else "lock: drifted %.2f mm from its locked spot" % d)
        else:
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
                anchor_score = self._scorer(spec.anchor, occ, targets, prune=self._pick(i) is None)

                def score(members):
                    return anchor_score(members[spec.anchor.inst])
            body = occ._geometry(spec.anchor).body
            radius = i.radius if i.near is not None else max(i.radius, body.width, body.height)
            alone = self._block_alone(spec, i.rotations or (i.rotation,), i.face, clr)
            if alone is not None:           # no board position can help: say so now, not after the scan
                best, rejected = None, Counter()
            else:
                best, tried, rejected, reasons = scan_block(occ, spec, hint, radius, i.step, i.rotations or (i.rotation,),
                                                            clr, score, pick=self._pick(i))
            if best is None and alone is not None:
                plan.findings.append(Finding("unplaced", "%s: cannot be laid out on its own at any rotation it may "
                                             "take, whatever room the board has (%s)" % (i.key, alone)))
                members = {}
                note = "UNPLACED: " + alone
            elif best is None:
                plan.findings.append(Finding("unplaced", "%s: no legal spot within %.1f mm of %s (%s)" % (
                    i.key, radius, _loc(hint.location), ", ".join("%s x%d" % kv for kv in rejected.most_common(3)))))
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
        return self._commit_block(occ, spec, members, i, plan, note)

    def _draw_adopted(self, occ, ctx, plan: Plan, entries, progress):
        """Routed copper kept beside the script (routes.py): each net drawn
        while the parts it joins stand as they did when it was adopted,
        else dropped with a finding, and the router routes it again."""
        from . import routes as _routes
        # an entry whose end met another kept entry's copper is judged once that one's is drawn: rounds
        # until nothing more holds
        keys = _routes.entry_keys(entries)
        drawn, got, left = [], {}, list(range(len(entries)))
        while left:
            also = [_shape_of(op) for op in drawn]
            now = {i: _routes.resolve(entries[i], occ, self.settings.route_adopt_tolerance, [s for s in also if s])
                   for i in left}
            held = [i for i in left if not isinstance(now[i], str)]
            got.update(now)
            if not held:
                break
            for i in held:
                drawn += list(now[i][0]) + list(now[i][1])
            left = [i for i in left if i not in held]
        intents = []
        for i, e in enumerate(entries):
            key = keys[i]
            if isinstance(got[i], str):
                plan.adopted[key] = "dropped: " + got[i]
                plan.findings.append(Finding("route", "adopted route %s dropped: %s; the router routes it again"
                                             % (key, got[i])))
                continue
            plan.adopted[key] = "held"
            ops = list(got[i][0]) + list(got[i][1])
            intents.append(CopperIntent("adopted %s" % key, e.net, Priority.DEFAULT, lambda ctx, ops=ops: ops,
                                        (), "kept from a route", len(self._copper) + len(intents)))
        if intents:
            self._plan_copper(occ, ctx, intents, plan, progress)

    def _block_alone(self, spec, rotations, face, clearance) -> str | None:
        """None when the block can be laid out on its own - on an empty board,
        nothing else placed - at some rotation it may take; else why not, at
        each. A block its own satellites cannot fit round fails here in a
        moment rather than after a scan of the whole board."""
        from .placer import layout_block
        key = (spec.key, tuple(rotations), face)
        cache = self.__dict__.setdefault("_block_alone_cache", {})
        if key not in cache:
            bare = self._bare_occupancy()
            bare.board_box, bare.board_shape, bare.board_cutouts = None, None, None
            bare.copper, bare.reservations = [], []
            bare.pending = {fp.ref for fp in self.geometry.footprints}
            why = []
            for rot in rotations:
                members, reason = layout_block(bare, spec, Placement(Location(0.0, 0.0), rot, face), clearance,
                                               others={fp.inst: [] for fp in spec.members})   # an empty board
                if members is not None:
                    why = None
                    break
                why.append("%g: %s" % (rot, reason))
            cache[key] = None if why is None else "; ".join(why)
        return cache[key]

    def _firm_past_edge(self, i: PlaceIntent) -> bool:
        """Whether a firm item's body may cross the edge margin: one declared
        on an edge, a run or the rim closer than the keep-in."""
        return ((i.edge is not None or i.run is not None or i.rim == "rim")
                and i.row_of is None and i.clearance < self.keep_in)

    def _firm_placement(self, occ: Occupancy, plan: Plan, i: PlaceIntent) -> tuple:
        """(placement, note) where a firm declaration puts its item, read
        against `occ` as it stands: the item is neither judged nor committed."""
        chose = ""
        if i.at is not None:
            p = Placement(_locate(self, occ, i.at), i.rotation, i.face)
        elif i.center is not None and i.cell_pin is not None:
            owner, number, dx, dy, *rest = i.cell_pin
            lx, ly = rest if rest else (0.0, 0.0)
            if number is None:              # the member's footprint origin, not a pad
                p = cell_origin_anchored_placement(occ, i.item, owner, _locate(self, occ, i.center),
                                                   i.rotation, i.face)
            else:
                p = cell_pad_anchored_placement(occ, i.item, owner, number, dx, dy,
                                                _locate(self, occ, i.center), i.rotation, i.face, lx, ly)
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
            along = _run_along(self, occ, i)
            # a numeric along= turns the item at declaration; a reference's length along
            # the run is not known until now, so its outward turn waits for it too
            rot = self.outward_rotation(i.item, i.run.at(along)[1])[0] if i.rotation is None else i.rotation
            p = run_placement(occ, i.item, occ.board_shape or self._shaped(), i.run,
                              along, i.clearance, rot, i.face)
        elif i.rim is not None:
            p = disc_placement(occ, i.item, self._disc("the same place is "
                                                      "OnEdge(board.edge(facing=...))"),
                               i.angle, i.clearance, i.rotation, i.face, bore=i.rim == "bore")
        elif i.beside is not None:
            p = self._beside_placement(occ, plan, i)
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
            p = self._row_of_placement(occ, i, along) if i.row_of is not None else \
                edge_placement(occ, i.item, i.edge, along, i.rotation, i.clearance, i.face)
        return p, chose

    # ------------------------------------------------------------ riders
    def _primary_refs(self, i: PlaceIntent) -> set:
        """The refdes a firm item's place is said relative to: Beside's item,
        a row's `of` (and what the row is centred on), else every reference
        in its point."""
        if i.beside is not None:
            return set() if isinstance(i.beside.item, KeepoutIntent) else {self._pad_ref(i.beside.item)[0]}
        refs = {self._pad_ref(ref)[0] for ref in _refs_in([i.at, i.center, i.along, i.pin_x, i.pin_y, i.near,
                                                             i.about])}
        if i.row_of is not None:
            refs.add(self._pad_ref(i.row_of)[0])
        if isinstance(i.along, _RowSlot):
            refs |= set(i.along.row.needs)
        return refs

    def _find_riders(self) -> None:
        """Which firm placements ride a searched item. A firm part or cell
        whose place is said relative to a searched part or cell, or to a
        rider of one, rides it: it is placed with it at each candidate and
        commits with it. Every other item it refers to is placed firmly
        before, or rides with it. One that refers to some other searched item
        stays in the firm queue, which refuses it."""
        intents = self._placements()
        owner = {fp.ref: i for i in intents
                 for fp in (i.item.members if i.kind == "block" else members_of(i.item))}
        root = {i.key: i.key for i in intents if not i.freedom.decided and i.kind in ("part", "cell")}
        order = {k: 0 for k in root}            # a rider settles after everything it refers to in its group
        self._rider_of, self._ride_groups = {}, {}
        changed = True
        while changed:
            changed = False
            for i in intents:
                if (not i.freedom.decided or i.key in self._rider_of or i.kind == "block"
                        or isinstance(i.run, CutoutEdge)
                        or not all(r in owner or r.startswith("cutout:") for r in i.needs)):
                    continue
                moving = {owner[r].key for r in i.needs
                          if r in owner and (not owner[r].freedom.decided or owner[r].key in self._rider_of)}
                primary = {owner[r].key for r in self._primary_refs(i) if r in owner} & moving
                if not primary or not moving <= set(root) or len({root[k] for k in moving}) != 1:
                    continue
                ref = max(sorted(primary), key=lambda k: order[k])
                self._rider_of[i.key] = ref
                root[i.key] = root[ref]
                order[i.key] = max(order[k] for k in moving) + 1
                self._ride_groups.setdefault(root[ref], []).append(i)
                changed = True
        for group in self._ride_groups.values():
            group.sort(key=lambda r: (order[r.key], r.index))

    def _reset_rows(self, row) -> None:
        """Let a row said relative to a riding item find its start again at
        the next candidate: what it is anchored on moves with it."""
        if row.anchor is None or row.start is None:
            return
        row.start = row.end = None
        row.centres = []
        if row.anchor[0] in ("before", "after"):
            self._reset_rows(row.anchor[1])

    def _ride(self, occ: Occupancy, plan: Plan, i: PlaceIntent, at: Placement, obstacles: dict | None,
              stop: bool = True, board: bool = True) -> list:
        """[(rider, placement, note, why the board refuses it, why the group
        does)] for `i`'s riders with `i` at `at`, in the order they settle:
        each where its declaration puts it with `i` and the riders before it
        there, judged against `i` and those riders, then against the board as
        a firm item is (not with `board=False`). With `stop`, the list ends at
        the first rider that is not legal."""
        view = _Riding(occ)
        group = view.move(i.item, at)
        out = []
        for r in self._ride_groups[i.key]:
            if isinstance(r.along, _RowSlot):
                self._reset_rows(r.along.row)
            if r.turned is not None:
                turned = view.items[self._pad_ref(r.turned.part)[0]].reference.rotation
                r = dataclasses.replace(r, rotation=(turned + r.turned.degrees) % 360.0)
            p, chose = self._firm_placement(view, plan, r)
            others = obstacles.get(r.key) if obstacles is not None else None
            in_group = occ.legal(r.item, p, self.clearance, others=ShapeIndex(group), board=False)
            on_board = occ.legal(r.item, p, self.clearance, others=others, past_edge=self._firm_past_edge(r),
                                 by_corners=True) if board and not in_group else None
            out.append((r, p, chose, on_board, in_group))
            if (on_board or in_group) and stop:
                break
            group += view.move(r.item, p)
        return out

    def _ride_turn(self, occ: Occupancy, plan: Plan, i: PlaceIntent, at: Placement):
        """The riders of `i` at one turn and face of it, laid once: (where
        `i` was, [(rider, placement, why the group refuses it)]) when every
        rider moves exactly as `i` does at that turn - its declaration is
        said wholly relative to what moves with it - else None, and each
        candidate lays them afresh."""
        shifted = Placement(Location(at.location.x + _RIDE_PROBE[0], at.location.y + _RIDE_PROBE[1]),
                            at.rotation, at.face)
        a = self._ride(occ, plan, i, at, None, board=False)
        b = self._ride(occ, plan, i, shifted, None, board=False)
        if len(a) != len(b):
            return None
        for (_, pa, _, _, ga), (_, pb, _, _, gb) in zip(a, b):
            if (pa.rotation, pa.face, bool(ga)) != (pb.rotation, pb.face, bool(gb)) or \
                    abs(pb.location.x - pa.location.x - _RIDE_PROBE[0]) > 1e-6 or \
                    abs(pb.location.y - pa.location.y - _RIDE_PROBE[1]) > 1e-6:
                return None
        return at, [(r, p, g) for r, p, _, _, g in a]

    def _riders_alone(self, occ: Occupancy, plan: Plan, i: PlaceIntent) -> str | None:
        """None when `i`'s riders may fit round it at some turn its search
        may take, else why not, at each: a rider that meets `i` or another
        rider wherever `i` goes fails here in a moment rather than after a
        scan of the whole board, as a block's satellites do. Only for an item
        searched at a known set of turns whose riders move exactly as it
        does; else None, and the search finds out."""
        if i.outward or self._locked(i) is not None:
            return None             # turned by where it lands, or by its lock: any turn at all
        turns = set(self._turns(i)) | {i.rotation, (i.rotation + 90) % 360}      # a pocket's two as well
        at = occ.board_box.center if occ.board_box is not None else Location(0.0, 0.0)
        why = []
        for rot in sorted(turns):
            laid = self._ride_turn(occ, plan, i, Placement(at, rot, i.face))
            bad = None if laid is None else next(((r, g) for r, _, g in laid[1] if g), None)
            if bad is None:
                return None
            why.append("%g: rider %s: %s" % (rot, bad[0].key, bad[1]))
        return "cannot be laid out with its riders at any rotation it may take, whatever room the board has " \
               "(%s)" % "; ".join(why)

    def _rider_check(self, occ: Occupancy, plan: Plan, i: PlaceIntent):
        """What a search asks of each candidate of an item that has riders:
        None when every rider is legal with the item there, else "rider
        <key>: why". The board as the search sees it is gathered once, and
        the riders are laid once per turn of the item wherever they move
        exactly as it does: a candidate then shifts them and asks the board."""
        obstacles = {r.key: occ.obstacles(occ._geometry(r.item)) for r in self._ride_groups[i.key]}
        turns = {}

        def accept(at: Placement):
            turn = (at.rotation, at.face)
            if turn not in turns:
                turns[turn] = self._ride_turn(occ, plan, i, at)
            laid = turns[turn]
            if laid is None:
                r, _, _, on_board, in_group = self._ride(occ, plan, i, at, obstacles)[-1]
                why = on_board or in_group
                return "rider %s: %s" % (r.key, why) if why else None
            base, riders = laid
            dx, dy = at.location.x - base.location.x, at.location.y - base.location.y
            for r, p, in_group in riders:
                p = Placement(Location(round(p.location.x + dx, 6), round(p.location.y + dy, 6)), p.rotation, p.face)
                why = in_group or occ.legal(r.item, p, self.clearance, others=obstacles[r.key],
                                            past_edge=self._firm_past_edge(r), by_corners=True)
                if why:
                    return "rider %s: %s" % (r.key, why)
            return None
        return accept

    def _accept(self, i: PlaceIntent):
        """The rider check for the item being settled now, else None."""
        riding = self.__dict__.get("_riding")
        return riding[1] if riding is not None and riding[0] == i.key else None

    def _settle_riders(self, occ: Occupancy, i: PlaceIntent, plan: Plan, step: Step) -> None:
        """Commit `i`'s riders where they go with `i` at its step's placement,
        a step each; or, with `i` unplaced, an unplaced step and a finding
        each."""
        for r in self._ride_groups[i.key]:
            plan._items[r.key] = r.item
        if step.placement is None:
            for r in self._ride_groups[i.key]:
                why = "rides %s, which found no place" % self._rider_of[r.key]
                plan.findings.append(Finding("unplaced", "%s: %s" % (r.key, why)))
                plan.steps.append(self._step(r, None, 0.0, "UNPLACED: " + why))
            return
        for r, p, chose, on_board, in_group in self._ride(occ, plan, i, step.placement, None, stop=False):
            why = on_board or in_group
            if why:
                plan.findings.append(Finding("fixed", "%s (%s): %s" % (r.key, r.freedom.value, why)))
            tags = ["rides %s" % self._rider_of[r.key]] + (["required"] if r.required else [])
            note = "; ".join(x for x in tags + [chose, why, r.faces_note] if x)
            plan.steps.append(self._step(r, p, 0.0, note))
            occ.commit(r.item, p)

    def _settle(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set = frozenset(),
                solve: bool = True) -> Step:
        if i.kind == "block":
            return self._settle_block(occ, i, plan, placed)
        clr = self.clearance
        if i.freedom.decided:
            p, chose = self._firm_placement(occ, plan, i)
            why = occ.legal(i.item, p, clr, past_edge=self._firm_past_edge(i), by_corners=True)
            if why:
                plan.findings.append(Finding("fixed", "%s (%s): %s" % (i.key, i.freedom.value, why)))
            return self._step(i, p, 0.0, "; ".join(x for x in (chose, why) if x))
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
            return self._settle_along_line(occ, i, plan, clr, placed)
        locked = self._settle_locked(occ, i, plan, clr)
        if locked is not None:
            return locked
        targets = self._targets(i.item, occ, placed)
        seeded = ""
        solved = None
        if solve and i.near is None and self.settings.solve_enabled:
            solved = self._global_hints(occ, placed, plan).get(i.key)
        if i.near is not None:
            hint = Placement(_locate(self, occ, i.near), i.rotation, i.face)
        elif solved is not None:
            hint = Placement(solved, i.rotation, i.face)
            seeded = "seeded by the global solve"
        elif targets:
            hint = self._seed_hint(i.item, occ, targets, i.rotation, i.face)
            # k[1] here is always a raw pad NUMBER string from _targets() (never
            # a net name) - some real footprints number pads like "1'" for a
            # mechanically doubled leg, which is not all-digit, so this matches
            # p.number directly instead of going through pad_key()'s int/net
            # guess (which mis-reads a non-digit pad number as a net name).
            nets = sorted({p.net for k, _, _ in targets
                           if k[0] in {fp.ref for fp in members_of(i.item)}
                           for p in self.geometry.footprint(k[0]).pads if p.number == k[1]})
            seeded = "seeded on %s" % ", ".join(nets)
            for n in nets:
                plan.seeded_by_net[n] += 1
        else:
            return self._settle_in_pocket(occ, i, plan, clr)
        # riders refuse candidates after they are scored: a refused one must not prune the rest
        score = self._scorer(i.item, occ, targets, prune=self._pick(i) is None and self._accept(i) is None) \
            if targets else None
        # A seeded item lands on the pads that pull it; it must be free to step at least its own size clear of them.
        body = occ._geometry(i.item).body
        radius = i.radius if i.near is not None else max(i.radius, body.width, body.height)
        hopeless = self._no_pocket_note(occ, i)
        if hopeless:
            plan.findings.append(Finding("unplaced", "%s: %s" % (i.key, hopeless)))
            return self._step(i, None, 0.0, "UNPLACED: " + hopeless)
        result = scan(occ, i.item, hint, radius, i.step, self._turns(i), clr, score=score, pick=self._pick(i),
                      accept=self._accept(i))
        if result.chosen is None and solved is not None:
            # The solve spreads items without seeing what is already placed, so
            # its hint can land where nothing is legal. That must not cost a
            # placement the sequential seed would have made: drop the hint.
            step = self._settle(occ, i, plan, placed, solve=False)
            step.note = "the global solve's hint had no legal spot within %.1f mm, so it was dropped; %s" % (
                radius, step.note)
            return step
        if result.chosen is None:
            blame = "no legal location within %.1f mm of %s (%s)" % (radius, _loc(hint.location), _blame_text(result))
            if i.near is None:
                step, tried = self._seeded_pocket(occ, i, plan, clr, hint, score, self._turns(i),
                                                  "%s, but no legal spot within %.1f mm (%s)" % (
                                                      seeded or "seeded", radius, _blame_text(result)))
                if step is not None:
                    return step
                blame += "; no pocket took it (%d tried)" % tried
            plan.findings.append(Finding("unplaced", "%s: %s" % (i.key, blame)))
            return self._step(i, None, 0.0, "UNPLACED: " + "; ".join(result.reasons.values()))
        note = seeded
        if result.moved_mm > 0:
            first = next(iter(result.reasons.values()), "")
            moved = "moved %.2f mm off the hint" % result.moved_mm
            if first:
                moved += ": " + first
            elif score:
                moved += " for a better link score"
            note = (note + "; " if note else "") + moved
        return self._step(i, result.chosen, result.moved_mm, note)

@contextlib.contextmanager
def _recording_commits(occ: Occupancy):
    """Every commit made on `occ` inside the block, as [(kind, name), placement]
    for a later run to apply again: the item named by refdes or cell name."""
    from . import reuse as _reuse
    commits = []
    real = occ.commit

    def commit(item, placement):
        commits.append([("cell", item.name) if isinstance(item, CellGeom) else ("fp", item.ref),
                        _reuse.placement_to_json(placement)])
        return real(item, placement)
    occ.commit = commit
    try:
        yield commits
    finally:
        del occ.commit


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


def _script_line() -> int:
    """The line of the script (or test) that made the declaration being
    built: the first frame outside the placemat package."""
    import inspect
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    f = inspect.currentframe()
    while f is not None:
        if not os.path.abspath(f.f_code.co_filename).startswith(here + os.sep):
            return f.f_lineno
        f = f.f_back
    return 0


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
    (where that pad now is), the Mid of two points, a bare X()/Y() of one
    (the other axis its own), a Polar about a centre that may itself be a
    reference, or an (x, y) pair whose members may be numbers, X()/Y() of
    references, or row coordinates."""
    if isinstance(ref, Location):
        if isinstance(ref.x, (int, float)) and isinstance(ref.y, (int, float)):
            return ref
        return Location(_coord(board, occ, ref.x, "x"), _coord(board, occ, ref.y, "y"))   # a Location said in references
    if isinstance(ref, Mid):
        a, b = _locate(board, occ, ref.a), _locate(board, occ, ref.b)
        return Location((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)
    if isinstance(ref, X):
        return Location(_locate(board, occ, ref.ref).x + ref.dx, _locate(board, occ, ref.ref).y)
    if isinstance(ref, Y):
        return Location(_locate(board, occ, ref.ref).x, _locate(board, occ, ref.ref).y + ref.dy)
    if isinstance(ref, Polar):
        centre = board.centre if ref.about is None else _locate(board, occ, ref.about)
        return polar_point(centre, ref.angle, float(ref.radius))
    if isinstance(ref, tuple) and len(ref) == 2:
        return Location(_coord(board, occ, ref[0], "x"), _coord(board, occ, ref[1], "y"))
    if isinstance(ref, Centre):
        return Location(_coord(board, occ, ref.x, "x"), _coord(board, occ, ref.y, "y"))
    if isinstance(ref, (Part, Cell)):
        geom, key, kind = board._item(ref)
        refs = [fp.ref for fp in (geom.members if kind == "cell" else (geom,))]
        return Box.union([occ.items[r].body for r in refs]).center      # where its body is now
    owner, number, dx, dy = board._pad_ref(ref)
    at = occ.pad_location(owner, number, board._pad_land(ref)).offset(dx, dy)
    lx, ly = getattr(ref, "lx", 0.0), getattr(ref, "ly", 0.0)
    if lx or ly:
        from .lock import _turn
        g = occ.items[owner].reference
        vx, vy = _turn(-lx if g.face is Face.BACK else lx, ly, g.rotation)
        at = at.offset(vx, vy)
    return at


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


_RIDE_PROBE = (1.37, -0.73)
"""How far _ride_turn moves an item to see whether its riders move with it:
off any grid a search walks, on both axes."""


class _Riding:
    """An Occupancy as it would stand with some items moved to candidate
    placements, none of them committed: what a rider's declaration reads
    while the item it rides is searched. Everything else is the Occupancy's."""

    def __init__(self, occ: Occupancy):
        self._occ = occ
        self._moved: dict = {}
        self._cells: dict = {}
        self.items = collections.ChainMap(self._moved, occ.items)

    def __getattr__(self, name):
        return getattr(self._occ, name)

    def move(self, item, placement: Placement) -> list:
        """Put `item` at `placement`; what it is there to another item's
        legality, as if committed: its shapes, and its yards."""
        placed, own = self._occ.placed_geometries(item, placement)
        self._moved.update(placed)
        if isinstance(item, CellGeom):
            self._cells[item.name] = self._occ.cell_geometry(item, placed, own)
            shapes = self._cells[item.name].shapes
        else:
            shapes = placed[item.ref].shapes
        return list(shapes) + self._occ.shifted_yards(item, placement)

    def _geometry(self, item):
        if isinstance(item, Footprint) and item.ref in self._moved:
            return self._moved[item.ref]
        if isinstance(item, CellGeom) and item.name in self._cells:
            return self._cells[item.name]
        return self._occ._geometry(item)

    def pad_shapes(self, ref: str, number: str, land: int | None = None) -> list:
        # the Occupancy's own reading, over the moved items where they now stand
        return Occupancy.pad_shapes(self, ref, number, land)

    def pad_location(self, ref: str, number: str, land: int | None = None) -> Location:
        if ref not in self._moved:
            return self._occ.pad_location(ref, number, land)
        return Box.union([s.box for s in self.pad_shapes(ref, number, land)]).center


class _CopperContext:
    def __init__(self, board: Board, occ: Occupancy):
        self.board, self.occ = board, occ
        self.planned_tracks: list = []     # every track planned so far (any batch)
        self.fixed_tracks: list = []       # tracks from the FIXED batch: never yield
        self.notes: list = []              # findings a copper plan raises about itself
        self.planned_vias: list = []       # every via planned so far, for a FreeSpot's hole rule
        self.planned_tails: list = []      # every FreeSpot tail planned so far: not in the occupancy until the batch ends
        self.batch_tracks: list = []       # tracks planned so far in the batch being planned: not in the occupancy yet
        self.via_at: dict = {}             # via intent index -> where it landed, for a track ending on it
        self.pour_at: dict = {}            # pour intent index -> its drawn points, for a stitch over it
        self.ops_at: dict = {}             # copper intent index -> the ops its plan gave, for a Past over it
        self.plan = None                   # the plan being built: its keepouts, for a FreeSpot

    def locate(self, ref) -> Location:
        if isinstance(ref, CopperIntent):
            return self.via_at[ref.index]
        return _locate(self.board, self.occ, ref)


    def tracks_on(self, layer) -> list:
        return [t for t in self.planned_tracks if t.layer is layer]


def _escape_axis(occ: Occupancy, owner: str, number: str, pin_box: Box | None = None) -> tuple:
    """The way out from a pad, as placed now: `_pin_normal`'s outward normal
    of the pad row it sits in (the same measure a block's satellite escapes
    its anchor's pin by), or, where neither side of the row decides one (a
    lone pad, a square one at a corner), the ray from the part's body
    centre through it. `pin_box` is the pad's own box (one land's, for a
    PadRef naming one), else every land's."""
    g = occ.items[owner]
    boxes: dict = {}
    for sh in g.shapes:
        if sh.kind in ("pad", "through"):
            boxes.setdefault(sh.label, []).append(sh.box)
    pads = {(owner, n): Box.union(bs).center for n, bs in boxes.items()}
    pin_box = pin_box or Box.union(boxes[number])
    p = pin_box.center
    normal = _pin_normal(pads, owner, p, g.reference.rotation, pin_box)
    if normal is not None:
        return normal
    c = g.body.center
    dx, dy = p.x - c.x, p.y - c.y
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-9 else (1.0, 0.0)


def _inner_box(pads: list, centre: Location) -> Box:
    """The box inside a part's pads (`Inside`), in the part's own frame at
    rotation 0: `pads` each land's box, `centre` the body's. Each land joins
    the row `_pin_normal` puts it in (the side of the pads' centres it is
    proportionally nearest, a tie settled by its long side), and counts
    only when it lies wholly on that side of `centre`. A side's edge is the
    innermost edge of its row; a side with no row takes the pads' outer
    extent on that axis."""
    centres = {("", i): b.center for i, b in enumerate(pads)}
    outer = Box.union(pads)
    west, east, north, south = [], [], [], []
    for i, b in enumerate(pads):
        n = _pin_normal(centres, "", b.center, 0.0, b)
        if n is None:
            continue
        ux, uy = n
        if ux < -0.5 and b.right <= centre.x:
            west.append(b.right)
        elif ux > 0.5 and b.left >= centre.x:
            east.append(b.left)
        elif uy < -0.5 and b.bottom <= centre.y:
            north.append(b.bottom)
        elif uy > 0.5 and b.top >= centre.y:
            south.append(b.top)
    return Box(max(west) if west else outer.left, max(north) if north else outer.top,
               min(east) if east else outer.right, min(south) if south else outer.bottom)


def _named_pad(board: "Board", ctx: "_CopperContext", net: str, p) -> tuple | None:
    """(label, (x, y)) for a point that names a same-net pad, else None: what
    a `swallow_pads` pour's pull-back checks are still joined to the result
    once it pulls back from foreign copper. A point that names another net's
    pad is a corner reference only - the pour never grows over it and the
    pull-back cuts it clear like any other foreign pad, so it is not one of
    the pads the result must still touch."""
    if not isinstance(p, (PadRef, CellPadRef)):
        return None
    owner, number, _, _ = board._pad_ref(p)
    if _pad_shapes(board, ctx.occ, p)[0].net != net:
        return None
    at = ctx.locate(p)
    return ("%s.%s" % (owner, number), (at.x, at.y))


def _pad_shapes(board: "Board", occ: Occupancy, ref) -> list:
    """The Shape(s) of one pad, as placed now: usually one, but a pin of
    several apart lands (occupancy.py) carries more than one; a PadRef's
    `land=` names one of them."""
    owner, number, _, _ = board._pad_ref(ref)
    return occ.pad_shapes(owner, number, board._pad_land(ref))


def _pad_half_across(board: "Board", occ: Occupancy, ref, centre: Location, ux: float, uy: float) -> float:
    """How far the pad reaches from `centre` along the unit normal
    (-uy, ux): half the pad's own width measured across a run whose
    direction is (ux, uy), whatever the pad's own rotation."""
    nx, ny = -uy, ux
    return max(abs((px - centre.x) * nx + (py - centre.y) * ny)
              for sh in _pad_shapes(board, occ, ref) for px, py in sh.poly)


def _pad_clearance(board: "Board", net: str, pad_net: str) -> float:
    """The clearance a track of `net` keeps from a pad of `pad_net`: the
    board default when the pad has no net (occupancy.py's copper_conflicts
    falls back the same way) - a corner-reference pad with GetNetCode() <= 0
    names no netclass to look up."""
    if pad_net not in board.geometry.nets:
        return board.geometry.default_clearance
    return board.geometry.clearance(net, pad_net)


def _net_clearance(board: "Board", a: str, b: str) -> float:
    """KiCad's clearance between copper of two nets; the board default when
    either has no net (as `_pad_clearance` falls back)."""
    nets = board.geometry.nets
    if a not in nets or b not in nets:
        return board.geometry.default_clearance
    return board.geometry.clearance(a, b)


def _lane_distance(board: "Board", own: str, nets: list, lane, width=None) -> float:
    """How far a pad of net `own` stands past copper of `nets`: the worst
    clearance between them, or with `lane` a net, room for one track of it
    between - the clearance from the copper to the lane, the lane's width
    (`width`, else its track width) and the clearance from the lane to the
    pad."""
    if lane is None:
        return max(_net_clearance(board, own, n) for n in nets)
    name = board.geometry.require_net(lane)
    return (max(_net_clearance(board, n, name) for n in nets) + board._width(name, width)
            + _net_clearance(board, name, own))


def _between_point(board: "Board", ctx: "_CopperContext", net: str, width: float, p: Between) -> Location:
    """Between(a, b)'s point: the midpoint of the gap's centreline, and a
    note when the gap does not fit the track and its clearance to each
    pad."""
    from .geometry import poly_distance
    sa, sb = _pad_shapes(board, ctx.occ, p.a), _pad_shapes(board, ctx.occ, p.b)
    gap = min(poly_distance(x.poly, y.poly) for x in sa for y in sb)
    need = width + _pad_clearance(board, net, sa[0].net) + _pad_clearance(board, net, sb[0].net)
    if gap < need - 1e-6:
        oa, na, _, _ = board._pad_ref(p.a)
        ob, nb, _, _ = board._pad_ref(p.b)
        ctx.notes.append("track %s: the gap between %s.%s and %s.%s is %.3f mm, not enough for a %.2f mm "
                         "track with clearance to each (%.3f mm needed)" % (net, oa, na, ob, nb, gap, width, need))
    # the middle of the gap, between the pads' facing edges on the axis they stand apart on,
    # centred across where they face each other on the other
    ba, bb = Box.union([s.box for s in sa]), Box.union([s.box for s in sb])
    gx = max(bb.left - ba.right, ba.left - bb.right)
    gy = max(bb.top - ba.bottom, ba.top - bb.bottom)
    if gx >= gy:
        x = (ba.right + bb.left) / 2.0 if ba.right <= bb.left else (bb.right + ba.left) / 2.0
        y = (max(ba.top, bb.top) + min(ba.bottom, bb.bottom)) / 2.0
    else:
        y = (ba.bottom + bb.top) / 2.0 if ba.bottom <= bb.top else (bb.bottom + ba.top) / 2.0
        x = (max(ba.left, bb.left) + min(ba.right, bb.right)) / 2.0
    return Location(round(x, 6), round(y, 6))


def _past_unplanned(ops_at: dict, it, what: str, current: int | None) -> str | None:
    """Why the via or track `it`, named by `what`'s Past, has no copper to
    stand off: declared after `what`, or planned and drawing nothing. None
    when it has copper."""
    if it.index not in ops_at:
        if current is not None and it.index > current:
            return "%s is declared after %s; declare it first" % (it.key, what)
        return "%s is not planned by then" % it.key
    if not any(isinstance(op, (Via, Track)) for op in ops_at[it.index]):
        return "that via found no spot" if it.key.startswith("via") else "that track is not drawn"
    return None


def _past_names(board: "Board", p: Past) -> list:
    """What a Past's items are called in a finding: a via's or track's key,
    a pad's refdes and number."""
    return [it.key if isinstance(it, CopperIntent) else "%s.%s" % board._pad_ref(it)[:2] for it in p.items]


def _past_copper(board: "Board", occ: Occupancy, ops_at: dict, p: Past, what: str,
                 current: int | None = None):
    """(net, box) for every piece of copper `p.items` names: each pad's
    shapes, each via's ring and each track's segments, as the polygons the
    clearance check measures. A string instead when a via or track has no copper
    (see `_past_unplanned`)."""
    out = []
    for it in p.items:
        if isinstance(it, CopperIntent):
            why = _past_unplanned(ops_at, it, what, current)
            if why is not None:
                return why
            for op in ops_at[it.index]:
                if isinstance(op, (Via, Track)):
                    # its polygon's box: the copper the clearance check measures, a via's ring a
                    # little outside the true circle
                    out.append((op.net, op.box))
        else:
            out += [(sh.net, sh.box) for sh in _pad_shapes(board, occ, it)]
    return out


def _past_point(board: "Board", ctx: "_CopperContext", net: str, width: float, p: Past, what: str,
                current: int | None = None):
    """Past(items, edge)'s point for copper of `net`: `width`/2 plus the
    worst clearance by net pair off the items' combined box on `edge`,
    across it where `across` says (default the middle of the box's side).
    A string instead, the reason, when a via or track it names has no
    copper."""
    copper = _past_copper(board, ctx.occ, ctx.ops_at, p, what, current)
    if isinstance(copper, str):
        return copper
    box = Box.union([b for _, b in copper])
    off = width / 2.0 + max(_pad_clearance(board, net, n) for n, _ in copper)
    upright = p.edge in (Edge.EAST, Edge.WEST)          # the side runs north-south: across is y
    lo, hi = (box.top, box.bottom) if upright else (box.left, box.right)
    a = p.across
    if a is None or isinstance(a, Along):
        across = lo + (Along.MID if a is None else a).fraction * (hi - lo)
    else:
        if isinstance(a, CopperIntent):
            why = _past_unplanned(ctx.ops_at, a, what, current)
            if why is not None:
                return why
        at = ctx.locate(a)
        across = at.y if upright else at.x
    if p.edge is Edge.EAST:
        return Location(_round_away(box.right + off, 1), round(across, 6))
    if p.edge is Edge.WEST:
        return Location(_round_away(box.left - off, -1), round(across, 6))
    if p.edge is Edge.NORTH:
        return Location(round(across, 6), _round_away(box.top - off, -1))
    return Location(round(across, 6), _round_away(box.bottom + off, 1))         # SOUTH


def _round_away(v: float, sign: int) -> float:
    """`v` to 1e-6 mm, rounded away from the items it is held off (up when
    `sign` is 1, down when -1), so the rounding never eats the clearance;
    float noise under 1e-9 mm is not rounded up."""
    q = v * 1e6
    return (math.ceil(q - 1e-3) if sign > 0 else math.floor(q + 1e-3)) / 1e6


def _stitch_region(board: "Board", ctx: "_CopperContext", region, pour_intent) -> tuple | None:
    """`region`'s polygon as placed now: a pour's own drawn points (None
    until it is drawn), a Cell's placed member boxes unioned, or a settled
    keepout's polygon (None until it is settled - never later than any
    copper, since a keepout is always planned in the fixed queue)."""
    if pour_intent is not None:
        return ctx.pour_at.get(pour_intent.index)
    if isinstance(region, Cell):
        geom, key, kind = board._item(region)
        return box_polygon(Box.union([ctx.occ.items[fp.ref].body for fp in geom.members]))
    placed = ctx.plan.keepouts.get(region) if ctx.plan else None
    return None if placed is None else placed.poly


def _stitch_edge_points(poly, step: float, inset: float):
    """Via centres in a row along each edge of `poly`, `step` apart, `inset`
    in from it along the inward normal: `stitch(edge=True)`'s row hugging a
    region's own outline, not a grid over its whole inside. Marches from
    each corner rather than centring on the edge, the same way the interior
    grid marches from the region's box rather than centring on it; the
    site's own poly_within/`_via_site_why` check in `stitch()` drops
    whatever does not fit."""
    for i in range(len(poly)):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % len(poly)]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue
        ux, uy = dx / length, dy / length
        nx, ny = uy, -ux                # perpendicular to the edge, one of the two inward/outward normals
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        if not point_in_polygon((mx + nx * 1e-6, my + ny * 1e-6), poly):
            nx, ny = -nx, -ny           # the other side is the inward one
        t = inset
        while t <= length - inset + 1e-6:
            yield (ax + ux * t + nx * inset, ay + uy * t + ny * inset)
            t += step


def _cutout_half_across(cutout, bearing_deg: float, rotation: float = 0.0) -> float:
    """How far the shape, at `rotation`, reaches from its centre along a
    bearing: what holds a hole placed on an edge back off it."""
    lo_x, lo_y, hi_x, hi_y = cutout.shape.box_at(Location(0.0, 0.0), rotation)
    return box_support(Box(lo_x, lo_y, hi_x, hi_y), bearing_deg) / 2.0


def _refs_in(points, via_ends: bool = False) -> list:
    """Every pad, part or cell reference a list of points depends on (inside
    tuples and X/Y too). A via intent is a point only where `via_ends` says
    so: a track's own end points."""
    out = []
    for p in points:
        if isinstance(p, CopperIntent):
            if not via_ends:
                raise TypeError("%s: a via may be a track's end point or one of a Past's items, and only that"
                                % p.key)
            out += list(p.refs)             # a via's pads: the track waits for them as the via does
        elif isinstance(p, (PadRef, CellPadRef, Part, Cell)):
            out.append(p)
        elif isinstance(p, (X, Y)):
            out += _refs_in([p.ref])        # the ref may itself be a point or a pad
        elif isinstance(p, FreeSpot):
            out += _refs_in([p.near])       # the pad it searches from must be placed first
        elif isinstance(p, Mid):
            out += _refs_in([p.a, p.b])
        elif isinstance(p, Between):
            out += _refs_in([p.a, p.b])
        elif isinstance(p, Past):
            for it in p.items + ((p.across,) if p.across is not None else ()):
                if isinstance(it, CopperIntent):
                    out += list(it.refs)    # a via's or track's pads: the point waits for them as it does
                elif not isinstance(it, Along):
                    out += _refs_in([it])
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
        return Shape("", "copper", faces, frozenset([op.layer]), op.net, op.polygon, op.box,
                    ends=((op.start.x, op.start.y), (op.end.x, op.end.y)))
    if isinstance(op, Via):
        return Shape("", "through", both, frozenset(CopperLayer), op.net, op.polygon, op.box,
                     circle=(op.at.x, op.at.y, op.size / 2.0))
    if isinstance(op, Pour):
        faces = frozenset([op.layer.face]) if op.layer.face else frozenset()
        return Shape("", "copper", faces, frozenset([op.layer]), op.net, op.polygon, op.box)
    return None            # a zone pulls back round everything; it is never an obstacle


_BLOCKED_BY = {"hole-to-hole": ("hole", "npth"),    # a bucket named for its rule: the obstacle kinds behind it
               "copper": ("pad", "through")}        # another part's pads and vias are copper refusals too
_KNOWN_BUCKETS = frozenset(("courtyard", "edge", "reservation", "copper", "through", "npth", "hole-to-hole"))
_DRAWN_KINDS = frozenset(("silk", "mask", "body"))


def _blame_text(result) -> str:
    """The rejection counts, and for each kind the owners that caused most of
    them. The owner and the faces are computed for every candidate the scan
    refuses and were being thrown away; three owners, because a crowded board
    has forty and a reader needs one."""
    parts = []
    shown = result.rejected.most_common(3)
    # a rider that refused candidates is named with its reason, however few it refused, and so is
    # copper: whose copper a via field met is what a far-face refusal needs to say
    shown += [kv for kv in result.rejected.most_common()
              if (kv[0].startswith("rider ") or kv[0] == "copper") and kv not in shown]
    for kind, n in shown:
        if kind.startswith("rider "):
            parts.append("%s x%d" % (result.reasons[kind], n))
            continue
        if kind == "body":
            kind = "edge"       # "body box ... is past the rim's keep-in / outside the board / inside a cutout"
        # a drawn envelope's refusal (silk, a mask opening, a body) is counted under its sentence's first
        # word, the candidate's own name: it is shown as what it is, with the drawn things in the way
        drawn = kind not in _KNOWN_BUCKETS
        owners = sorted(((owner, faces, count)
                         for (k, owner, faces), count in result.blockers.items()
                         if (k in _DRAWN_KINDS if drawn else (k == kind or k in _BLOCKED_BY.get(kind, ())))
                         and owner),
                        key=lambda t: -t[2])[:3]
        detail = "" if not owners else ": " + ", ".join(
            "%s%s x%d" % (owner, (" %s face" % faces) if faces else "", count)
            for owner, faces, count in owners)
        parts.append("%s x%d%s" % ("body, silk or mask" if drawn else kind, n, detail))
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


def _escape_lane(fp, pad, pads, width: float, reach: float):
    """The straight track out of `pad` (see Board._check_pitch), as a
    function of another pad: the distance from the track to it, or None when
    the pad is not beside the track. None instead of a function when the pad
    has no straight way out: it sits at the body's centre, or another pad
    lies ahead of it, across any of its width (an inner ball of a grid, an
    exposed pad inside a row)."""
    c = pad.box.center
    body = fp.body_box.center
    t = Transform.rotate(fp.rotation)
    axes = [t.apply((1.0, 0.0)), t.apply((0.0, 1.0))]
    ox, oy = c.x - body.x, c.y - body.y
    if math.hypot(ox, oy) < 1e-6:
        return None
    ux, uy = max(axes, key=lambda a: abs(ox * a[0] + oy * a[1]))
    if ox * ux + oy * uy < 0:
        ux, uy = -ux, -uy
    along = [(x - c.x) * ux + (y - c.y) * uy for x, y in pad.outlines[0]]
    end = max(along)

    def strip(length):
        hx, hy = -uy * width / 2.0, ux * width / 2.0
        fx, fy = c.x + ux * length, c.y + uy * length
        return ((c.x + hx, c.y + hy), (fx + hx, fy + hy), (fx - hx, fy - hy), (c.x - hx, c.y - hy))

    ahead = strip(end + reach + width)
    side = [(x - c.x) * -uy + (y - c.y) * ux for x, y in pad.outlines[0]]
    for q in pads:
        if q is pad or not (q.layers & pad.layers):
            continue
        beyond = min((x - c.x) * ux + (y - c.y) * uy for x, y in q.outlines[0])
        across = [(x - c.x) * -uy + (y - c.y) * ux for x, y in q.outlines[0]]
        if beyond > end - 1e-9 and min(across) < max(side) and max(across) > min(side):
            return None

    near = Box.of_points(ahead).inflate(reach)

    def lane(q):
        return poly_distance(ahead, q.outlines[0]) if near.overlaps(q.box) else None
    return lane
