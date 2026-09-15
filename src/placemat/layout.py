"""The Board object a layout script declares to, and the Plan resolve()
produces from it.

Board answers questions about the generated board, records placement and
copper declarations, and resolves them in priority order (setup, FIXED,
EDGE, searched cells, FIXED copper, loose parts, remaining copper) against
the occupancy model. Plan holds the resolved placements, copper ops and
findings for the writer and the run record."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math

from .copper import (CopperOp, Pour, Text, Track, Via, Zone, board_zone_outline, chamfered, finger_ops, octilinear, pair_ops, polyline_tracks,
                     resolve_bridges)
from .geometry import polygon_box, transform_box
from .occupancy import Occupancy, Shape, TOUCH
from .outline import Outline, Run, rect_outline
from .placement import Placement
from .placer import BlockSpec, _reason_key, box_centered_placement, disc_placement, pad_anchored_placement, edge_placement, layout_block, pockets, run_placement, scan, scan_block
from .board_geometry import CellGeom, Footprint, BoardGeometry
from .values import (Along, Box, Cell, CellPadRef, Centre, Disc, OnBore, OnRim, Pin, Polar, bearing, bearing_vector, box_support, polar_point, CopperLayer, Edge, Face, Fraction, LinkWeight, Location, Mid, Near, Net, OnEdge, PadRef, Part,
                     Priority, X, Y)

RANK_FIXED, RANK_EDGE, RANK_CELL, RANK_FIXED_COPPER, RANK_BLOCK, RANK_LOOSE, RANK_COPPER = range(7)


# A cell generated with its connector's body bulk on local +Y ("outward")
# faces out of each edge at this rotation.
_OUTWARD_ROTATION = {Edge.SOUTH: 0.0, Edge.EAST: 90.0, Edge.NORTH: 180.0, Edge.WEST: 270.0}

_CRITICAL_SHARE = 0.02
"""A searched item is critical on its own only if it needs at least this
much of the board: below it, being the largest thing left means little."""


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
    draw_outline: bool = True           # False: the outline is a placement frame only (a module fragment)
    chamfer: float = 0.0
    radius: float = 0.0
    shape: object | None = None         # the board when it is not a rectangle: a Disc
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
                 via_drill: float = 0.3, via_size: float = 0.6, keep_going: bool = False, courtyard_excess: float = 0.1):
        self.geometry = geometry
        self.courtyard_excess = courtyard_excess    # the fab's assembly margin round a part: the only spacing that comes free
        self.edge_margin = geometry.edge_clearance if edge_margin is None else edge_margin
        self.clearance = clearance
        self.via_drill, self.via_size = via_drill, via_size
        self.keep_going = keep_going            # carry on past colliding FIXED/EDGE items, as findings
        self._intents: list[PlaceIntent] = []
        self._weights: dict = {}
        self._copper: list[CopperIntent] = []
        self._labels: list = []
        self._faces: tuple | None = None
        self._links: list[Link] = []
        self._rules: list = []
        self._free_nets: set = set()
        self._outline: Box | None = geometry.outline_box
        self._shape = None                  # a board that is not a rectangle: a Disc or an Outline
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
    def size(self, width: float, height: float, chamfer: float = 0.0, radius: float = 0.0, draw: bool = True):
        """The board outline: a rectangle at the origin, chamfered or rounded."""
        if width <= 0 or height <= 0:
            raise ValueError("board size must be positive")
        self._outline = Box(0.0, 0.0, float(width), float(height))
        self._chamfer, self._radius = chamfer, radius
        self.width, self.height = float(width), float(height)
        self._sized = True
        self._draw_outline = draw          # a fragment's frame is for placement only, never written

    def disc(self, diameter: float, hole: float = 0.0, draw: bool = True):
        """The board outline: a round board at the origin, `hole` wide through
        the middle when it goes round a shaft. A circle has no sides, so
        places on it are said as a bearing and a radius: OnRim, OnBore,
        Polar and ring()."""
        d = float(diameter)
        self._shape = Disc(Location(d / 2.0, d / 2.0), d, float(hole))
        self._cached_outline = None
        self._outline = self._shape.box
        self._chamfer = self._radius = 0.0
        self.width = self.height = d
        self._sized = True
        self._draw_outline = draw

    def outline(self, path, holes=(), draw: bool = True):
        """The board outline as a closed path of straight legs and arcs: the
        first element is where it starts, each one after it is a point (a
        straight leg to it) or an Arc(to=, via=) that curves through a point,
        and it closes back to the start. `holes` are cutouts, each a path of
        its own. Stretches of it are selected by which way they face, with
        board.edge(facing=)."""
        self._shape = Outline.of(path, holes)
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
                self._cached_outline = Outline.of(list(self._shape.polygon()), holes)
            elif self._outline is not None:
                self._cached_outline = rect_outline(self._outline, self._chamfer, self._radius)
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
        return self._disc().radius

    @property
    def bore(self) -> float:
        """A round board's bore radius; 0 when it is solid."""
        return self._disc().bore

    def _disc(self) -> Disc:
        if self._shape is None:
            raise ValueError("this is not a round board: declare one with board.disc(diameter=...)")
        return self._shape

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
              radius: float = 3.0, step: float = 0.2, rotations=(),
              priority: Priority | None = None, why: str = "", _standoff: float | None = None) -> PlaceIntent:
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
        """
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
            self._disc()
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
        if priority is None:
            priority = Priority.FIXED if (at is not None or center is not None) else \
                Priority.EDGE if ((edge is not None and along is not None) or (rim is not None and angle is not None)
                                  or (run is not None and along is not None)) else Priority.DEFAULT
        if edge is not None and along is None and priority in (Priority.FIXED, Priority.EDGE):
            raise ValueError("%s: an edge item with no distance along it is free to slide; it cannot be %s" % (key, priority.value))
        if run is not None and along is None and priority in (Priority.FIXED, Priority.EDGE):
            raise ValueError("%s: an item on a run with no distance along it is free to slide; it cannot be %s"
                             % (key, priority.value))
        if rim is not None and angle is None and priority in (Priority.FIXED, Priority.EDGE):
            raise ValueError("%s: a %s item with no bearing is free to slide round; it cannot be %s" % (key, rim, priority.value))
        faces_note = ""
        if rotation is None:
            if run is not None and along is not None:
                rotation, faces_note = self.outward_rotation(item, run.at(along)[1])
            elif rim is not None and angle is not None:
                rotation, faces_note = self.outward_rotation(item, angle + (180.0 if rim == "bore" else 0.0))
            elif edge is not None and along is None:
                rotation, faces_note = self.outward_rotation(item, edge)
            else:
                rotation, faces_note = 0.0, ""
        if kind == "cell" and at is not None and center is None:
            center, at = at, None
        needs = {self._pad_ref(ref)[0] for ref in _refs_in([at, center, along, pin_x, pin_y])}   # a real pad, placed before this
        if isinstance(along, _RowSlot):
            needs |= along.row.needs
        standoff = _standoff if _standoff is not None else (-float(overhang) if overhang else self.keep_in)
        intent = PlaceIntent(key, geom, kind, priority, float(rotation), face, at, center, edge, along,
                             standoff, near, radius, step, tuple(rotations), why, len(self._intents), frozenset(needs),
                             pin_x, pin_y, source, faces_note, pinned, pin, rim, angle, radius_at, outward, about, run)
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
        disc = self._disc() if radius is None else None      # only a ring at the rim needs a rim
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

    def label(self, item, text: str, *, side: Edge = Edge.NORTH, gap: float = 0.0, align: str = "centre",
              size: float = 1.0, thickness: float = 0.15, knockout: bool = False, rotation: float = 0.0,
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
            elif self._shape is not None:
                pts = self._shape.polygon(inset)
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
        occ = Occupancy(self.geometry, self.edge_margin, board_box=self._outline, board_shape=self._shape)
        for intent in self._intents:
            declared = [intent.item.anchor] + [fp for fp, _ in intent.item.satellites] if intent.kind == "block" else [intent.item]
            for item in declared:
                occ.pending |= occ._geometry(item).owners
        plan = Plan(self.geometry, occ, outline=self._outline, chamfer=self._chamfer, radius=self._radius, shape=self._shape,
                    rules=list(self._rules), draw_outline=self._draw_outline)
        ctx = _CopperContext(self, occ)
        self._weigh(occ)
        placements = sorted(self._intents, key=lambda i: i.rank)
        fixed_copper = [c for c in self._copper if c.priority is Priority.FIXED]
        other_copper = [c for c in self._copper if c.priority is not Priority.FIXED]
        placed: set = set()
        self._place_labels(occ, plan, placed, progress)        # labels on parts the script never moves

        def place_one(obj, why_now=""):
            plan._items[obj.key] = obj.item
            step = self._settle(occ, obj, plan, placed)
            if why_now:
                step.note = (why_now + "; " + step.note) if step.note else why_now
            if obj.priority not in (Priority.FIXED, Priority.EDGE):
                tag = "priority %s (%s)" % (obj.priority.value, self._weights.get(obj.key, obj.priority_source))
                step.note = (tag + "; " + step.note) if step.note else tag
            if obj.faces_note:
                step.note = (step.note + "; " if step.note else "") + obj.faces_note
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
            self._place_labels(occ, plan, placed, progress)

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

    def _weigh(self, occ: Occupancy):
        """Every searched item's priority, unless the script said: from how
        much of the largest item's area it needs, how many connections tie
        it to other declared items, and how many parts it holds. The reason
        is kept for the step."""
        self._weights: dict = {}
        searched = [i for i in self._intents if i.priority not in (Priority.FIXED, Priority.EDGE)]
        if not searched:
            return
        declared = self._declared_refs()

        def parts_of(i):
            return [i.item.anchor] + [fp for fp, _ in i.item.satellites] if i.kind == "block" else \
                (list(i.item.members) if i.kind == "cell" else [i.item])

        def measure(i):
            parts = parts_of(i)
            own = {fp.ref for fp in parts}
            area = sum(fp.courtyard_box.area for fp in parts)
            conns = sum(1 for fp in parts for p in fp.pads if p.net
                        and any(o.owner not in own and o.owner in declared for o in self.geometry.pads_on_net(p.net)))
            return area, conns, len(parts)
        m = {i.key: measure(i) for i in searched}
        top = [max(v[k] for v in m.values()) or 1 for k in range(3)]
        board_area = occ.board_box.area if occ.board_box is not None else sum(v[0] for v in m.values())
        for i in searched:
            area, conns, n = m[i.key]
            score = 0.5 * area / top[0] + 0.3 * conns / top[1] + 0.2 * n / top[2]
            share = area / board_area if board_area else 0.0
            # critical: it dominates the other searched items AND it is a real piece of the board
            auto = Priority.HIGH if (score >= 0.5 and share >= _CRITICAL_SHARE) else \
                Priority.LOW if score <= 0.1 else Priority.DEFAULT
            why = "%.0f%% of the largest area, %.1f%% of the board, %d connection(s), %d part(s)" % (
                100 * area / top[0], 100 * share, conns, n)
            if i.priority_source == "script":
                self._weights[i.key] = "script; would be %s: %s" % (auto.value, why)
            else:
                i.priority = auto
                self._weights[i.key] = "auto: " + why

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
                return Step(i.key, i.kind, i.priority, p, moved, note, i.why)
            key = _reason_key(why)
            rejected[key] += 1
            reasons.setdefault(key, why)
        plan.findings.append("%s: no room anywhere %s (%s)" % (
            i.key, what, ", ".join("%s x%d" % kv for kv in rejected.most_common(3))))
        return Step(i.key, i.kind, i.priority, None, 0.0, "UNPLACED: " + "; ".join(reasons.values()), i.why)

    def _settle_along_line(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """x or y pinned, the other free: the item's body centre sits on the
        pinned line, shares it evenly with the items pinned to the same
        value, and slides along it to the nearest legal spot."""
        axis = "x" if i.pin_x is not None else "y"
        pinned = _coord(self, occ, i.pin_x if axis == "x" else i.pin_y, axis)
        fellows = [o for o in self._intents if (o.pin_x if axis == "x" else o.pin_y) is not None
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
        fellows = [x for x in self._intents if x.edge is i.edge and x.along is None
                   and x.priority not in (Priority.FIXED, Priority.EDGE)]
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
        fellows = [x for x in self._intents if x.run is i.run and x.along is None
                   and x.priority not in (Priority.FIXED, Priority.EDGE)]
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
        fellows = [x for x in self._intents if x.angle is None
                   and (x.rim, x.radius_at, x.about) == (i.rim, i.radius_at, i.about)
                   and x.priority not in (Priority.FIXED, Priority.EDGE)]
        k, n = fellows.index(i), max(len(fellows), 1)
        return 360.0 * k / n

    def _settle_round_rim(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides round the rim (or the bore)
        from its slot, its reach at the keep-in, facing out wherever it lands."""
        disc = self._disc()
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
        if self._shape is not None and centre == self._shape.centre:
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
            elif i.center is not None and i.pin is not None:
                p = pad_anchored_placement(occ, i.item, i.pin, _locate(self, occ, i.center), i.rotation, i.face)
            elif i.center is not None:
                p = box_centered_placement(occ, i.item, _locate(self, occ, i.center), i.rotation, i.face)
            elif i.run is not None:
                p = run_placement(occ, i.item, occ.board_shape or self._shaped(), i.run,
                                  _run_along(self, occ, i), i.clearance, i.rotation, i.face)
            elif i.rim is not None:
                p = disc_placement(occ, i.item, self._disc(), i.angle, i.clearance, i.rotation, i.face,
                                   bore=i.rim == "bore")
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
                plan.findings.append("%s (%s): %s" % (i.key, i.priority.value, why))
            return Step(i.key, i.kind, i.priority, p, 0.0, why or "", i.why)
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
        hopeless = self._no_pocket_note(occ, i)
        if hopeless:
            plan.findings.append("%s: %s" % (i.key, hopeless))
            return Step(i.key, i.kind, i.priority, None, 0.0, "UNPLACED: " + hopeless, i.why)
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

    def locate(self, ref) -> Location:
        return _locate(self.board, self.occ, ref)

    def coord(self, v, axis: str) -> float:
        return _coord(self.board, self.occ, v, axis)

    def tracks_on(self, layer) -> list:
        return [t for t in self.planned_tracks if t.layer is layer]


def _refs_in(points) -> list:
    """Every pad, part or cell reference a list of points depends on (inside tuples and X/Y too)."""
    out = []
    for p in points:
        if isinstance(p, (PadRef, CellPadRef, Part, Cell)):
            out.append(p)
        elif isinstance(p, (X, Y)):
            out += _refs_in([p.ref])        # the ref may itself be a point or a pad
        elif isinstance(p, Mid):
            out += _refs_in([p.a, p.b])
        elif isinstance(p, tuple):
            out += _refs_in(p)
        elif isinstance(p, (Centre, Location)):
            out += _refs_in([p.x, p.y])
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
