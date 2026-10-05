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
import collections.abc
import contextlib
import copy
import dataclasses
import functools

from collections import Counter
from dataclasses import dataclass, field
import math
import time
import types

from .copper import (Pour, Text, Track, Via, Zone, arc_circle, arc_tracks, board_zone_outline, chamfer_cuts, chamfered, finger_ops, octilinear,
                     pair_ops, polyline_tracks, resolve_bridges, _point_seg)
from .geometry import native_status, Transform, box_polygon, circle_polygon, circle_poly_gap, via_ring, point_in_polygon, poly_distance, poly_within, polys_overlap, pose_transform, segments_intersect, transform_box, transform_polygon
from . import blame, finding_text, step_text
from .phases import Stage
from .cutouts import EdgeWhy
from .refusals import Code, Refusal, ReservedBy
from .findings import Finding, FindingCause as C, Findings
from .giveway import FIELD_PREFIX, enabled as giveway_enabled, field_via_id, pad_via_id
from .occupancy import LABEL_SOURCE, Occupancy, Shape, ban_shape, ShapeIndex, TOUCH, _polygon_area, hole_shape, parts_claim
from .cutouts import Cutouts, Path, _turned, loop_gap, signed_area
from .outline import Outline, Run, rect_outline
from . import exposure
from .placement import Placement
from .settings import Settings
from .arrangements import (DEFAULT_SPEC, Alt, Enumeration, Exclusion, Group, GroupOption, Option, Spec, check_keywords, check_name,
                           enumerate_specs, merged_call, units)
from .placer import BandTurns, BearingTurns, BlockSpec, SearchBudget, SpotTurns, ScanResult, _grid, _pin_normal, facing_rotation, pad_way_out, pad_row_end, way_out_side, parallel_rotation, _reason_key, box_centered_placement, cell_pad_anchored_placement, pad_box_at, cell_origin_anchored_placement, disc_placement, pad_anchored_placement, sweep_standoff, edge_placement, layout_block, pockets, run_placement, scan, scan_block
from .board_geometry import BoardGeometry, CellGeom, Footprint, members_of, part_height, stackup_order
from .lanes import Escape, EscapeDecl, EscapeError, Lane, LanePoint, Layouter, row_way, turn_direction
from .values import (Tangent, Turned, Turns, Axis, Bearing, Bend, Corner, Cover, Beside, Between, Cutout, CutoutEdge, Drops, Freedom, Keepout, bearing_of, Along, Box, Cell, CellPadRef, Centre, Disc, Facing, SideOf, Line, OnBore, OnRim, Origin, Parallel, Past, Pin, Polar, bearing, bearing_vector, box_support, polar_point, CopperLayer, Edge, Face, Fraction, FreeSpot, Inside, Land, LinkWeight, Location, Mid, Near, Net, OnEdge, PadRef, Part,
                     PinName, Priority, X, Y, pad_key)
from .values import Figure, FigurePoint, Reach

RANK_FIXED, RANK_EDGE, RANK_CELL, RANK_FIXED_COPPER, RANK_BLOCK, RANK_LOOSE, RANK_COPPER = range(7)


# A cell generated with its connector's body bulk on local +Y ("outward")
# faces out of each edge at this rotation.
_OPPOSITE = {Edge.NORTH: Edge.SOUTH, Edge.SOUTH: Edge.NORTH, Edge.EAST: Edge.WEST, Edge.WEST: Edge.EAST}
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


_ROW_TIE = 1e-6
"""mm: how near two pads' coordinates along a row are to equal before `over=` cannot order by them."""


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
    # over= (the row ordered by where pads land): set on the instance only then, for the same reason
    over = None
    declared = None       # the items' claims in the order given; `alongs` is them in the order the pads put them
    position = None       # each item's place in the row, by its index in the order given

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
        if self.over is not None:
            self._order_by(board, occ, axis)
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

    def _order_by(self, board, occ, axis: str) -> None:
        """Put the items in the order their `over` pads lie along the row, increasing."""
        at = [_coord(board, occ, ref, axis) for ref in self.over]
        order = sorted(range(len(at)), key=lambda k: at[k])
        for a, b in zip(order, order[1:]):
            if abs(at[a] - at[b]) < _ROW_TIE:
                raise ValueError("a row over pads: %s and %s lie at the same %s (%.3f), so the pads do not order "
                                 "them; the row runs along %s" % (self.keys[a], self.keys[b], axis, at[a], axis))
        self.position = [order.index(k) for k in range(len(at))]
        self.alongs = [self.declared[k] for k in order]
        if self.pitch is not None:
            self.length = self.alongs[0] / 2.0 + self.pitch * (len(self.alongs) - 1) + self.alongs[-1] / 2.0
        else:
            self.length = sum(self.alongs) + self.gap * (len(self.alongs) - 1)

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
        return self.centres[i if self.position is None else self.position[i]]

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
        return self.row.centres[self.index if self.row.position is None else self.row.position[self.index]]


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
    faces_note: str = ""               # the kind of note (step_text.py) the step gets when the rotation fell back to the generic rule
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
    turned: object = field(default=None, metadata={"omit_default": True})   # a Turned (its part's rotation plus its degrees) or a Parallel (the line between two points), settled at placement
    beside: object = field(default=None, metadata={"omit_default": True})   # a _BesideSpec: settled against its item's placed envelope
    row_of: object = field(default=None, metadata={"omit_default": True})   # a row(of=) item: an edge placement measured off its envelope, not the board's
    cell_pin: object = field(default=None, metadata={"omit_default": True})  # (owner, number, dx, dy[, lx, ly]): a cell placed by a member's pad
    drops: Drops = field(default=Drops.ALL, metadata={"omit_default": True})   # a cell's via fields as stamped, or thinned when it is placed
    pushes: tuple = field(default=(), metadata={"omit_default": True})   # Push declarations on this item, from board.push()
    line: int = field(default=0, metadata={"reuse": False})   # the script line that declared it: not what it decides
    file: str = field(default="", metadata={"reuse": False})  # and the file that line is in (a module the script imports, or the script)
    toward: object = field(default=None, metadata={"omit_default": True})   # Centre(toward=): an end of the free line
    pin_land: object = field(default=None, metadata={"omit_default": True})   # Pin(land=): the land of `pin` that lands on the point
    either: bool = field(default=False, metadata={"omit_default": True})   # face=Face.EITHER: `face` is FRONT, and the search also tries the back
    tangent: object = field(default=None, metadata={"omit_default": True})   # a Tangent: the turn at each spot comes from its bearing
    band: object = field(default=None, metadata={"omit_default": True})      # (r_min, r_max) about `about`: Polar((r_min, r_max), None)
    budget: int | None = field(default=None, metadata={"omit_default": True})   # the candidates its search may judge, else `place.step_budget`
    arrangements: tuple = field(default=(), metadata={"omit_default": True})   # arrangements=: the arrangement ids a cell may take, in the order tried; () every one it offers

    @property
    def stands_off(self) -> tuple | None:
        """(the item it stands off, the side of it) for a Beside or a row(of=) item - what its standoff from the shapes of
        the neighbour's envelope is measured against - else None."""
        if self.beside is not None:
            return self.beside.item, self.beside.side
        if self.row_of is not None:
            return self.row_of, self.edge
        return None

    @property
    def turns_on_point(self) -> bool:
        """A place that is a point, declared with turns to search: the item stays on the point
        and its turn is the search."""
        return (bool(self.rotations) and self.beside is None and not self.freedom.decided
                and (self.at is not None or self.center is not None))

    @property
    def freedoms(self) -> int:
        """How many freedoms the declaration leaves the search: 0 for a decided place, 1 for a slide
        (a line, an edge, a run, a rim, a ring or a spoke, or a point whose turn is searched), 2 for
        anything else. Read in the order `_settle` dispatches."""
        if self.freedom.decided:
            return 0
        if (self.turns_on_point or self.run is not None or self.rim is not None or self.radius_at is not None
                or self.angle is not None or self.edge is not None
                or self.pin_x is not None or self.pin_y is not None):
            return 1
        return 2

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
    max_height: float | None = None     # the keepout's own max_height=, for its drawn label
    admitted: frozenset = frozenset()   # the parts owners admits by height alone, a subset of owners
    barred: frozenset = frozenset()     # the parts a bars= keepout keeps out; every other part is in owners

    @property
    def admits_parts(self) -> bool:
        """Whether a keepout that excludes parts lets some in: by name (`allow=` parts or cells) or by height (`max_height=`).
        Its rule area is written allowing footprints (kicad/write.py), and a custom rule forbids the rest."""
        return "parts" in self.excludes and (bool(self.owners) or self.max_height is not None)


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
    PadRef) - or `("past", own_key, Past)`, a Past over pads. `copper`:
    the standoff is measured pad copper to pad copper, not envelope to
    envelope, and `gap` is added to the pairs' clearance."""
    item: object
    side: Edge
    align: tuple
    gap: float | None
    copper: bool = field(default=False, metadata={"omit_default": True})


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
    members: tuple = field(default=(), metadata={"omit_default": True})    # a fitted pour's via intents
    reach: float | Reach | None = field(default=None, metadata={"omit_default": True})   # a fitted pour's reach=: mm, or Reach.CURRENT
    declared: dict = field(default_factory=dict, metadata={"reuse": False})   # what the declaration gave, as a finding's suggestions read it
    only: tuple = field(default=(), metadata={"omit_default": True})    # the arrangement ids it exists in; () every one (arrangements.py)

    def applies_in(self, ident: str) -> bool:
        return not self.only or ident in self.only

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
class Push:
    """One physical effect holding an item back from a source: value(r) =
    v_ref * (r_ref / r) ** falloff, in the script's own units. Illegal
    where value(r) exceeds limit; within that, the search prices each
    candidate score.push * value(r) / limit."""
    source: object                        # Part, Cell, PadRef, a keepout's name (str), or a Location
    falloff: float
    r_ref: float
    v_ref: float
    limit: float
    target_pad_key: tuple | None = None   # (refdes, pad number): where on the item to measure from; None: its body centre
    target_member_ref: str = ""           # the item's own refdes: which cell member to measure, when the item is a cell
    why: str = field(default="", metadata={"reuse": False})
    achieved_value: float | None = field(default=None, metadata={"reuse": False})   # measured by a resolve, not declared
    achieved_mm: float | None = field(default=None, metadata={"reuse": False})
    # The rest are set only by a push that comes from part annotations (Pm.Emits / Pm.Limit), which is
    # worked out at each settle and never declared: none of it is in a declaration's digest.
    label: str = field(default="", metadata={"reuse": False})    # what the reservation and the note call the far end
    hard_limit: float | None = field(default=None, metadata={"omit_default": True})   # the disc's own limit, when the sources placed before leave less than `limit`
    target_point: object = field(default=None, metadata={"omit_default": True})       # where the item's own emission point stands now (a Location); moves with the item
    kind: str = field(default="", metadata={"omit_default": True})   # the annotated kind this push carries
    unit: str = field(default="", metadata={"omit_default": True})
    sens: str = field(default="", metadata={"omit_default": True})   # the sensitive part whose limit this is, for the sum over its sources
    slack: float = field(default=0.0, metadata={"omit_default": True})   # how far the item reaches from its own emission point: the disc is drawn that much smaller


class _FedSteps(list):
    """A plan's steps. Each one added is timed: its `seconds` is the time since the previous step was added or
    its own tail work was stamped (`_Lap.stamp`), so the steps' times add up to the resolve's and the work between
    two steps (give-way, settling, a fanout) is in the step it was for. With an `on_step`, each copper and cutout
    step is also told as it is added (a placement is told as it is committed), so a viewer sees them as they settle."""

    def __init__(self, plan, on_step, lap=None):
        super().__init__()
        self._plan, self._on_step, self._lap = plan, on_step, lap

    def append(self, step):
        if self._lap is not None:
            step.seconds += self._lap.stamp()
        super().append(step)
        if self._on_step is not None and step.kind in ("copper", "cutout"):
            self._on_step(self._plan, step)


class _Lap:
    """The resolve's stopwatch: `stamp()` is the seconds since the last stamp (or the start) and starts the next lap."""
    __slots__ = ("at",)

    def __init__(self):
        self.at = time.perf_counter()

    def stamp(self) -> float:
        now = time.perf_counter()
        spent, self.at = now - self.at, now
        return spent


@dataclass
class Step:
    item: str
    kind: str
    priority: Priority | None            # None for a decided placement: it has none
    placement: Placement | None = None
    moved_mm: float = 0.0
    notes: tuple = ()                    # what happened to it, as records (step_text.py): {"kind", ...facts}
    why: str = ""                        # the declaration's own why=, as the script wrote it
    ops: int = 0
    freedom: Freedom | None = None       # None for a copper step and for a bridge note
    rank: int | None = None              # a searched item's place in the queue
    rank_of: int | None = None
    back_face: bool = False              # a Face.EITHER search put the item on the back (score.back_face prices it)
    laid: tuple = ()                     # a copper step: where in plan.copper the ops it laid are
    unplaced: tuple | None = None        # None for an item that was placed; else why not, as refusal records (step_text.unplaced_text)
    lock: str = ""                       # how the lock fared: "held", "drifted" or "released"; "" for an item with none
    pocket: dict | None = None           # a seeded item that took a pocket: its w_mm, h_mm, at, seed_mm and face
    seconds: float = field(default=0.0, compare=False)   # how long this step took in this resolve, a replayed one its replay (reuse.py)
    first_seconds: float | None = field(default=None, compare=False)   # a replayed step: how long it took when it was first resolved, from the reuse record

    @property
    def note(self) -> str:
        """The notes as one line (step_text.render_all): for the console and the records' text, never read for data."""
        return step_text.render_all(self.notes, self.unplaced)

    def say(self, kind: str, **facts) -> None:
        """Add a note of this kind (step_text.record)."""
        self.notes = self.notes + (step_text.record(kind, **facts),)


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
    pushes: list = field(default_factory=list)                    # every push, once its item has a place (Push)
    rules: list = field(default_factory=list)
    acceptances: list = field(default_factory=list)               # board.accept: judged after the checks run (checks.Acceptance)
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
    seconds: float = 0.0                                          # how long the resolve took, in all
    turns: dict = field(default_factory=dict, repr=False)        # each searched item's turn: where it went and the pad it depends on (lock.py)
    adopted: dict = field(default_factory=dict)                   # net -> "held", or {"dropped": a Refusal as JSON}: routed copper kept beside the script
    cell_zones_under_planes: str = "drop"                         # settings: a cell's zone under the board's own plane is merged into it
    merged_zones: list = field(default_factory=list)              # the cell zones the write merged into a plane (MergedZone)
    kept_zones: list = field(default_factory=list)                # ones a plane covers but that join pads otherwise: kept
    models: dict = field(default_factory=dict)                    # the write's model paths: {"reanchored": n, "missing": [files]}
    split_groups: str = "lift"                                    # settings: what the write does to the generator's nested groups
    groups: list = field(default_factory=list)                    # the groups the script declared (DeclaredGroup)
    group_notes: list = field(default_factory=list)               # what the write did to the board's groups, a line each
    thinned: dict = field(default_factory=dict)                   # cell -> [(x, y)]: the vias drops= took out of its fields, as generated
    given_way: list = field(default_factory=list)                 # what a stamped cell's own vias did as it was placed (giveway.Action)
    pin_study: dict = field(default_factory=dict)                 # the pin map study's record (pinmap.study_findings): seconds, reused, groups, parts
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

    def __init__(self, settings, item, occ: Occupancy, targets: list, prune: bool, pushes=(), lanes=None):
        s = settings
        self.s, self.item, self.occ, self.targets, self.prune = s, item, occ, targets, prune
        self.pushes = tuple(pushes)
        self.lanes = lanes          # placement -> how many of the item's declared escape lanes it would block
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
        if self.pushes:
            points = {}
            for source_point, push in self.pushes:
                point = _push_at(occ, self.item, placement, push, pads, points)
                if point is None:
                    continue
                value, _ = _push_value(source_point, point, push)
                cost += s.score_push * value / push.limit
        if self.prune and cost >= self.best[0]:
            return cost + PRUNED        # its crossings and escapes can only add: it cannot be the best
        crossed = None
        if self.rn is not None:
            added, crossed = self.rn.leaf_costs(occ.candidate_anchors(self.item, placement), self.own, self.depth)
            cost += self.crossing * added
        if self.esc is not None:
            crossed, closed, walled = self.esc.closed(self.item, placement, crossed)
            cost += s.score_escape_crossed * crossed + s.score_escape_closed * closed + s.score_escape_walled * walled
        if self.lanes is not None:
            cost += s.score_escape_lane * self.lanes(placement)
        self.best[0] = min(self.best[0], cost)
        return cost

    def native(self, rots, face):
        """The same cost for the native sweep over these turns, or None when
        the native mirrors it needs are not there, or the item carries a
        push or a declared escape (the Rust NativeScoring module has no
        formula for either)."""
        if self.pushes or self.lanes is not None:
            return None
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

    fab_via_tiers: dict = {}       # "micro"/"blind"/"buried" -> "yes"/"no"/"if-needed"; a type not named is "no"

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
        # fit=Axis.X/Y's declared axis is a number from board.rect() on, but its
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
                 component_spacing: float | None = None, fab_via_tiers=None, fab_source: str = ""):
        self.settings = settings if settings is not None else Settings()
        # the via types beyond through: "micro"/"blind"/"buried" -> "yes"/"no"/"if-needed", and where it says so
        self.fab_via_tiers = dict(fab_via_tiers) if fab_via_tiers is not None else type(self).fab_via_tiers
        self.fab_source = fab_source
        self._planes_declared: list = []    # (net, layers) of each board.plane()
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
        self._room: dict = {}               # key -> room.measure's record, taken when the first searched item is reached
        self._waited: dict = {}                # item key -> the linked partner it waited for
        self._arr_unreached: dict = {}         # item key -> the arrangements a step out of time did not reach
        self._arr_choice: dict = {}            # firm cell key -> the arrangement it took ("" the default): _settle_firm_arranged
        self._arr_prev: dict = {}              # what each firm cell took in the pass before (`_Redo.arr`)
        self._arr_taken: dict = {}             # firm cell key -> what it took in each pass before, in order
        self._arr_unsettled: dict = {}         # firm cell key still changing at the last pass -> each id it took, in order
        self._collect_into: list | None = None  # while an explore draws over arrangements: each scan's legal candidates, best first
        self._copper: list[CopperIntent] = []
        self._pad_tracks: set = set()      # indices of the tracks whose points are all pads: their way is known before they are planned
        self._pad_vias: list = []          # (pad ref, net, drill, size, span) of each via declared at a pad: its part carries it
        self._pad_fields: list = []        # (pad ref, net, drill, size, span, inset, pitch, step) of each board.vias() grid: its part carries it
        self._field_notes: dict = {}       # grid index -> why none of its vias is drawn, said when it is planned
        self._late_copper: set = set()     # indexes of the copper intents planned after the search whatever their part (a part's grid)
        self._copper_after: dict = {}      # copper intent index -> the intents it is planned after, and so late when they are
        self._labels: list = []
        self._label_ids: dict = {}         # label key -> (its item as the key names it, its text)
        self._fanouts: list = []           # (key, footprint, depth, sides or None, why)
        self._escapes: list = []           # the EscapeDecl of each board.escape() (lanes.py)
        self._escape_laid: dict = {}       # escape index -> its Layout, once its part is placed
        self._escape_kept: dict = {}       # (escape index, pad number) -> the occupancy's copper shapes of a lane's riser and lane
        self._escape_waits: dict | None = None   # escape index -> keys of the firm items its lanes wait for (`_escape_wait_sets`)
        self._escape_named: dict = {}      # item key -> the escapes its position names
        self._settled: set = set()         # keys of the items the resolve has settled, placed or not
        self._faces: tuple | None = None
        self._links: list[Link] = []
        # a stamped cell brings its fragment's clearance rules, first: a rule this script declares stands after
        # them, and where both match a pair the later decides
        from .rules import stamped_rules
        stamped, self._stamped_rule_notes = stamped_rules(geometry)
        self._rules: list = list(stamped)
        self._acceptances: list = []        # checks.Acceptance of each board.accept: read by the checks step alone, in no digest
        self._free_nets: set = set()
        self._outline: Box | None = geometry.outline_box
        self._shape = None                  # a board that is not a rectangle: a Disc or an Outline
        self._cutouts = Cutouts()           # a rectangle's holes; a Disc or an Outline keeps its own
        self._named_cutouts: dict = {}      # the cutouts a script named, in declaration order
        self._settled_cutouts: dict = {}    # those of them that already have a position
        self._cutout_loop_of: dict = {}     # name -> its loop index in _shaped()
        self._keepouts: dict = {}           # the regions a script declared, by name
        self._annotations = exposure.Annotations()   # the parts' Pm.Emits / Pm.Limit, read when the run starts
        self._cell_placements: dict = {}    # cell name -> its settled Placement, for a region shaped by it
        self._groups: dict = {}             # the KiCad groups a script declared, by name (DeclaredGroup)
        self.web = 0.0                      # least material a hole may leave; 0: unchecked
        self._cached_outline = None         # this board as an outline, for reading runs off
        self._sized = False                 # the script has declared the board size
        self._fit = False                   # board.rect(fit=True): the frame is the placed content plus a margin
        self._fit_margin = 0.0
        self._fit_axis: Axis | None = None  # board.rect(fit=Axis.X/Y): only that axis fits; the other is declared
        self._frame_planes: set = set()     # planes with no outline of their own: on a fit board, planned once the frame is fitted
        self._draw_outline = True
        self._chamfer = 0.0
        self._radius = 0.0
        self.width = self._outline.width if self._outline else None
        self.height = self._outline.height if self._outline else None
        self._late_suggestions: list = []   # (finding, measure) pairs: facts measured once the board is finished
        self._row_members: dict = {}        # item key -> (the key of its row's first member, its place in the row's items)
        self._outline_decl: str = ""        # which of rect, disc, outline the script declared the board with
        self._centres: list = []            # (item key, the Centre it was placed at): what a Centre's flag is judged by
        self._sites: list = []              # the Site of each declaration: where the script made it (suggestions.bind)
        self._place_calls: dict = {}        # item key -> (the item as given, `at=`, the other place() keywords as given, "row"/"ring"/""): what an alternative lays over
        self._options: dict = {}            # item key -> [Option]: board.alternative(), in declaration order
        self._arr_groups: list = []         # Group (a unit): board.unit() and board.arrangement(), in declaration order
        self._group_after: dict = {}        # unit name -> how many intents (placements, keepouts, cutouts) the script had declared when it declared the unit
        self._exclusions: list = []         # Exclusion: board.exclude(), in declaration order
        self._compound: str = ""            # "row" or "ring" while one of them declares its members
        self._arrangement_enum = None       # arrangements.Enumeration, cached until a declaration changes it
        self._declarations_done = False
        self._only_sites: dict = {}         # copper index -> (file, line) of an `only=` (Task 1.4)
        self._copper_uses: dict = {}        # copper index -> the indexes of the copper intents it is drawn from or fitted round (Task 1.4)
        self._file_digests: dict = {}       # file -> digest of its text when the first declaration in it was made
        self.script_file = ""               # the layout script this board runs, set by the runner
        self.pin_study = True               # the pin map study runs at the end of a resolve; an explore's variant boards say False
        self.pin_study_cache = None         # where the last pin map study is kept (pinmap.py), set by the runner; None: not kept
        self.source_reader = None           # callable(path) -> text where the script ran from other than the file on disk

    # ------------------------------------------------------------ where declarations were made
    def _source_text(self, path: str) -> str:
        if self.source_reader is not None:
            return self.source_reader(path)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def file_digest(self, path: str) -> str:
        """The digest of a script file's text as this resolve first saw it, so a file edited while the resolve runs
        is not taken for the text its lines came from."""
        if path not in self._file_digests:
            from .script_edit import digest
            try:
                self._file_digests[path] = digest(self._source_text(path))
            except (OSError, UnicodeDecodeError, KeyError):
                self._file_digests[path] = ""
        return self._file_digests[path]

    def _record_site(self, kind: str, key: str, site: tuple) -> None:
        file, line = site
        if file and line:
            self.file_digest(file)
            self._sites.append(Site(kind, key, file, line))

    def sites_of(self, kind: str, key: str) -> list:
        return [s for s in self._sites if s.kind == kind and s.key == key]

    def shared_by(self, site: "Site") -> int:
        """How many declarations of this kind the script made on that file and line: more than one is a loop or a
        helper, and an edit there would change them all."""
        return sum(1 for s in self._sites if (s.kind, s.file, s.line) == (site.kind, site.file, site.line))

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

    def _bare_occupancy(self, fresh: bool = False) -> Occupancy:
        """An occupancy with nothing placed, for measuring an item on its own:
        with this board's settings, so it measures what the envelope claims.
        Building one registers every footprint of the board, and a scan asks
        for one per candidate, so the same one is handed back while the board,
        its margin, its settings and its spacing are the same objects. A caller
        that changes what it is given asks for a `fresh` one."""
        make = lambda: Occupancy(self.geometry, self.edge_margin, board_box=None, settings=self.settings,
                                 component_spacing=self.component_spacing)
        if fresh:
            return make()
        key = (self.geometry, self.edge_margin, self.settings, self.component_spacing)
        hit = self.__dict__.get("_bare_occ")
        if hit is None or hit[0][0] is not key[0] or hit[0][2] is not key[2] or hit[0][1] != key[1] or hit[0][3] != key[3]:
            hit = self.__dict__["_bare_occ"] = (key, make())
        return hit[1]

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
                     [self._clearance_reach(n) for n in nets])
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

    def _items_box(self, ctx, items) -> Box:
        """The box round the drawn envelopes of `items` (Parts and Cells) as
        placed now: the region `plane(over=)` takes."""
        boxes = []
        for it in items:
            geom, key, kind = self._item(it)
            if kind == "cell" and key not in self._cell_placements:
                # a cell the script never places stands where the generator put it: its
                # members, each where it is
                boxes += [self._drawn_envelope_box(Part(fp.inst), ctx.occ.items[fp.ref].reference)
                          for fp in geom.members]
            else:
                boxes.append(self._drawn_envelope_box(it, self._item_placement(ctx.occ, it)))
        return Box.union(boxes)

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
        # a span is said on the board as placed: a part the search will flip carries it flipped back, so
        # the flip lands it where it was declared (a cell flips when it is placed on the back)
        flipped = {fp.ref for i in self._placements() if hasattr(i, "item")
                   for fp in (members_of(i.item) if i.kind != "block" else
                              [i.item.anchor] + [sat for sat, _ in i.item.satellites])
                   if i.face is not (Face.FRONT if i.kind == "cell" else fp.face)}
        for k, (at, net, drill, size, span) in enumerate(self._pad_vias):
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
            layers = frozenset(span) if ref not in flipped else occ._flip_span(frozenset(span))
            faces = frozenset(l.face for l in layers if l.face is not None) if span else _BOTH
            tag, points = pad_via_id(k), ((c.x, c.y),)  # a carried via: it may give way (giveway.py)
            occ.carry(ref, [Shape(owner, "through", faces, layers or frozenset(self.geometry.layers), net, ring,
                                  Box.of_points(ring), carried=tag, points=points),
                            dataclasses.replace(hole_shape(owner, c, drill, net, layers=layers), carried=tag,
                                                points=points)])
        self._carry_pad_fields(occ, flipped)

    def _carry_pad_fields(self, occ, flipped: set) -> None:
        """Each grid declared with `vias(net, pad)` becomes copper of the pad's part, firmly placed or
        searched: the sites the grid has always drawn (`_field_sites`) that clear the part's own copper and
        holes and the vias carried before them, each a via ring and a hole. What the rest of the board does is
        for give-way to meet when the part is placed (giveway.py); the plan draws what is carried
        (`vias()`'s plan). A grid with no site says why when it is planned."""
        from .occupancy import _BOTH, hole_shape
        occ.field_decls = {}
        self._field_notes = {}
        for k, (pad, net, drill, size, span, inset, pitch, step) in enumerate(self._pad_fields):
            ref, number, _, _ = self._pad_ref(pad)
            if ref not in occ.items:
                continue
            occ.field_decls[k] = inset
            sites, why = self._field_sites(occ, pad, span, size, step, inset)
            if why:
                self._field_notes[k] = dict(why, net=net)
                continue
            owner = "via at %s.%s" % (ref, number)
            layers = frozenset(span) if ref not in flipped else occ._flip_span(frozenset(span))
            faces = frozenset(l.face for l in layers if l.face is not None) if span else _BOTH
            kept: list = []
            for at in sites:
                tag, points = field_via_id(k, len(kept) // 2), ((at.x, at.y),)
                ring = via_ring(at, size)
                shapes = [Shape(owner, "through", faces, layers or frozenset(self.geometry.layers), net, ring,
                                Box.of_points(ring), carried=tag, points=points),
                          dataclasses.replace(hole_shape(owner, at, drill, net, layers=layers), carried=tag,
                                              points=points)]
                if not self._clear_of_own(occ, ref, shapes, kept):
                    continue
                kept += shapes
            if not kept:
                self._field_notes[k] = {"variant": "field_none", "net": net, "owner": ref, "number": number,
                                        "size_mm": size, "drill_mm": drill, "inset_mm": inset}
                continue
            occ.carry(ref, kept)

    @staticmethod
    def _clear_of_own(occ, ref: str, shapes: list, kept: list) -> bool:
        """Whether a carried via's ring and hole (`shapes`) clear the copper and holes of the part `ref` and the
        vias carried before it: the rules the board's copper and holes are held to."""
        for o in list(occ.items[ref].shapes) + kept:
            if o.kind not in ("pad", "through", "copper", "hole", "npth"):
                continue
            for x in shapes:
                if x.box.overlaps(o.box, gap=occ._copper_reach) and occ._conflict(x, o, None, exact=True, say=False):
                    return False
        return True

    def _thin_drops(self, occ) -> dict:
        """Each cell placed with `drops=HALF` or `MIN` loses the vias of its
        fields it does not keep, from the occupancy (its ring and its hole)
        before its geometry is built. A field is the vias of a plane() net
        inside one of the cell's members' pads of that net. Returns {cell:
        [(x, y) of each via taken out, where the generated board has it]},
        for the writer, and notes each cell's step."""
        out, self._drops_notes, self._arranged_drops_notes = {}, {}, {}
        for i in self._placements():
            if getattr(i, "drops", Drops.ALL) is Drops.ALL or i.kind != "cell":
                continue
            cell = i.item.name
            own = [s for s in occ.copper if s.owner == cell]
            kept, gone, said = self._thin_cell_vias(i, own, i.item.members)
            self._drops_notes[i.key] = step_text.record("drops", mode=i.drops.value, fields=said)
            if not gone:
                continue
            left = {id(s) for s in kept}
            taken = {id(s) for s in own} - left
            occ.copper = [s for s in occ.copper if id(s) not in taken]
            occ._cells.pop(cell, None)
            occ._invalidate_native()
            out[cell] = gone
        return out

    def _thin_cell_vias(self, i, shapes: list, members) -> tuple:
        """(the shapes of `shapes` that cell `i`'s `drops=` keeps, [(x, y)] of each via it takes out, the notes of what each field
        kept). `shapes` is the cell's own copper, `members` its footprints as they stand: a field is the vias of a plane() net inside
        one of their pads of that net. A via taken out loses its ring and its hole."""
        from .lock import _turn
        planes = {c.net for c in self._copper if c.key.split(" ")[0] == "plane"}
        keep_share = self.settings.place_drops_keep_share
        vias = [s for s in shapes if s.kind == "through" and s.net in planes]
        fields, gone, said = {}, [], []
        for v in vias:
            c = v.box.center
            for fp in members:
                p = next((p for p in fp.pads if p.net == v.net and any(point_in_polygon((c.x, c.y), o)
                                                                       for o in p.outlines)), None)
                if p is not None:
                    fields.setdefault((fp.ref, p.number, p.box.center, fp.rotation), []).append(c)
                    break
        for (ref, number, centre, rot), pts in sorted(fields.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            # the field's grid in its part's own frame, where vias() laid it
            local = [_turn(p.x - centre.x, p.y - centre.y, -rot) for p in pts]
            kept = _checkerboard(local) if i.drops is Drops.HALF else \
                _spread(local, max(1, math.ceil(keep_share * len(pts) - 1e-9)))
            gone += [pts[k] for k in range(len(pts)) if k not in kept]
            said.append({"ref": ref, "pad": number, "kept": len(kept), "of": len(pts)})
        if not gone:
            return list(shapes), [], said
        def at(s):
            return any(abs(s.box.center.x - g.x) < 1e-6 and abs(s.box.center.y - g.y) < 1e-6 for g in gone)
        return [s for s in shapes if not (s.kind in ("through", "hole") and at(s))], [(g.x, g.y) for g in gone], said

    @staticmethod
    def _record_arranged_thinned(occ, plan, i, placement) -> None:
        """For the writer: a cell committed in an arrangement has the vias its drops= took out of the arrangement's copper in
        plan.thinned, in place of its default's (kicad/write.py thins them once it has drawn that copper)."""
        if i.kind == "cell" and placement.arrangement:
            Board._record_thinned(occ, plan, i.item.name, placement.arrangement)

    @staticmethod
    def _record_thinned(occ, plan, cell: str, arrangement: str) -> None:
        gone = occ.arranged_gone.get((cell, arrangement))
        if gone:
            plan.thinned[cell] = list(gone)
        else:
            plan.thinned.pop(cell, None)

    def _thin_arranged(self, cell, shapes: list) -> tuple:
        """Occupancy.thin_arranged: (the shapes of arranged cell `cell`'s own copper `shapes` its `drops=` keeps, [(x, y)] of each via
        it takes out). Its fields are found in its members' pads as the arrangement stands them, and the step's note says them."""
        i = next((x for x in self._placements() if x.kind == "cell" and x.item.name == cell.name), None)
        if i is None or getattr(i, "drops", Drops.ALL) is Drops.ALL:
            return shapes, []
        poses = dict(cell.poses)
        members = [_posed_footprint(fp, poses[fp.ref]) if fp.ref in poses else fp for fp in cell.members]
        kept, gone, said = self._thin_cell_vias(i, shapes, members)
        self._arranged_drops_notes[(cell.name, cell.arrangement)] = step_text.record("drops", mode=i.drops.value, fields=said)
        return kept, gone

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
        owner = self._escape_owner(ref)
        if owner is not None:                       # a lane, a lane's point, an escape or an escape's via: its part
            return self._pad_ref(owner)
        raise TypeError("not a pad reference: %r" % (ref,))

    def _escape_owner(self, ref):
        """The Part whose escape `ref` belongs to (the escape, a lane, a point
        of a lane, or a via an escape declared), else None."""
        if isinstance(ref, (Escape, Lane)):
            return ref.part
        if isinstance(ref, LanePoint):
            return ref.lane.part
        if isinstance(ref, CopperIntent):
            return next((d.part for d in self._escapes if any(v is ref for v in d.via_intents.values())), None)
        return None

    def _origin_of(self, occ: Occupancy, item) -> Location:
        """Where `Origin(item)` is now: a part's footprint origin as placed; a cell's
        frame origin, the (0, 0) the generator stamped it in, carried by the placement
        the cell was given (as stamped while the script gives it none)."""
        geom, key, kind = self._item(item)
        if kind != "cell":
            return occ.items[geom.ref].reference.location
        placed = self._cell_placements.get(key)
        if placed is None:
            return Location(0.0, 0.0)
        stamped = types.SimpleNamespace(reference=Placement(geom.box.center, 0.0, Face.FRONT))
        return occ._transform(stamped, placed).apply_location(Location(0.0, 0.0))

    def _own_pad_key(self, geom, key):
        """A pad key of the part `geom` (a number, a net, a `PinName`, or `Mid` of two of
        them), checked now: the key as given, but a pin's name as the number it names, and
        a midpoint with each end so."""
        if isinstance(key, Mid):
            a, b = self._own_pad_key(geom, key.a), self._own_pad_key(geom, key.b)
            if isinstance(a, Mid) or isinstance(b, Mid):
                raise TypeError("%s: a Mid of own pads takes two pads, not another Mid" % geom.inst)
            if geom.pad(a).number == geom.pad(b).number:
                raise ValueError("%s: Mid(%r, %r) names one pad twice; a midpoint is of two pads" % (geom.inst, key.a, key.b))
            return Mid(a, b)
        if isinstance(key, PinName):
            number = self.geometry.pad(Part(geom.inst), key).number
            return int(number) if number.isdigit() else number
        geom.pad(key)                                   # a real pad of this part
        return key

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

    def _cutout_illegal(self, occ, path, name: str, silk: bool = True) -> Refusal | None:
        """Why this hole may not be cut here (a Refusal), or None. In the spec's order:
        inside the board, clear of its outline, enough web, not through
        anything already placed and, with `silk` (a searched hole), the silk
        clearance from every placed part's silk. A hole whose place the script
        decided is cut there whatever silk stands by it."""
        shape = self._shaped()
        loop = Cutouts([path]).loops[0]
        board = shape.loops[0]
        for x, y in loop:
            if shape.why_not(Box(x, y, x, y), 0.0) is EdgeWhy.OUTSIDE:
                return Refusal(Code.CUTOUT_OUTSIDE)
        if loop_gap(loop, board) <= 0.0:
            return Refusal(Code.CUTOUT_NOTCH)
        if self.web > 0.0:
            gap = min([loop_gap(loop, board)] + [loop_gap(loop, h) for h in shape.loops[1:]])
            if gap < self.web - 1e-9:
                return Refusal(Code.CUTOUT_WEB, gap_mm=gap, web_mm=self.web)
        box = Box(min(p[0] for p in loop), min(p[1] for p in loop),
                  max(p[0] for p in loop), max(p[1] for p in loop))
        for owner, g in occ.items.items():
            if owner not in occ.pending and (g.reach or g.body).overlaps(box):
                return Refusal(Code.CUTOUT_MILLED, owner=owner)
        return self._cutout_silk(occ, loop, box) if silk else None

    def _cutout_silk(self, occ, loop, box: Box) -> Refusal | None:
        """A placed part's silk, on either face, nearer the hole than the board's silk clearance: KiCad judges silk
        against Edge.Cuts by that clearance less its DRC epsilon (drc_test_provider_edge_clearance.cpp testAgainstEdge,
        SILK_CLEARANCE_CONSTRAINT), a hole's edge included. The hole is measured by its flattened loop, whose chords
        may cut `geometry.arc_sag` inside a curved edge, so that much more is kept."""
        need = occ.clear_limit(self.geometry.silk_clearance) + self.settings.geometry_arc_sag
        for owner, g in occ.items.items():
            if owner in occ.pending or not (g.reach or g.body).overlaps(box, gap=need):
                continue
            for poly in occ.placed_silk(owner):
                if not Box.of_points(poly).overlaps(box, gap=need):
                    continue
                gap = poly_distance(loop, poly)
                if gap < need:
                    return Refusal(Code.CUTOUT_SILK, owner=owner, gap_mm=gap,
                                   need_mm=self.geometry.silk_clearance)
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

        def out_from(mid, lo, hi):
            step = self.settings.place_cutout_step
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
            turn = self.settings.place_cutout_angle_step
            for k in range(int(round(360.0 / turn))):
                b = ((k + 1) // 2 * (1 if k % 2 else -1)) * turn
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
        raise CutoutNowhere(Refusal(Code.CUTOUT_NOWHERE, nearest=nearest))

    def _keepout_unusable(self, path) -> Refusal | None:
        """Why a region may not go here, or None.

        A keepout may touch the board edge, hang off it, and lie over anything
        it allows: a hole's rules are not a region's, so a sliding region must
        not be judged by `_cutout_illegal` or it would be pushed inboard and a
        band round the rim would be refused outright. The only place a region
        cannot go is entirely off the board, where it would forbid nothing."""
        return Refusal(Code.KEEPOUT_OFF_BOARD) if self._off_board(path) else None

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
                      if shape.why_not(Box(x, y, x, y), 0.0) is EdgeWhy.OUTSIDE)
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
                if shape.why_not(Box(x, y, x, y), 0.0) is EdgeWhy.OUTSIDE:
                    why = Refusal(Code.CUTOUT_OUTSIDE)
                    break
            if why is None and loop_gap(loop, board) <= 0.0:
                why = Refusal(Code.CUTOUT_NOTCH)
            if why is None and self.web > 0.0:
                gap = min([loop_gap(loop, board)] + [loop_gap(loop, h) for h in others])
                if gap < self.web - 1e-9:
                    why = Refusal(Code.CUTOUT_WEB, gap_mm=gap, web_mm=self.web)
            if why:
                plan.findings.append(self._finding(C.FIXED_CUTOUT, {"name": name, "why": why.to_json(),
                                                                    "outline_kind": self._outline_decl}))
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
                    layer = getattr(op, "layer", None)
                    have = self.geometry.layers
                    facts = {"net": op.net, "keepout": k.name, "word": word, "excluded": excluded, "why": k.why,
                             "excludes": list(k.excludes), "bars": bool(k.barred),
                             "keepout_layers": [l.name for l in (k.layers if k.layers is not None else have)]}
                    if layer is not None:
                        facts["layer"] = layer.name
                        facts["layer_word"] = {"F": "front", "B": "back"}.get(layer.name, layer.value)
                    plan.findings.append(self._finding(C.COPPER_KEEPOUT, facts))

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
            order = list(self._named_cutouts)
            plan.findings.append(self._finding(C.SETUP_WEB, {"outline_kind": self._outline_decl,
                "cutout": order[which] if 0 <= which < len(order) else None, "gap_mm": gap, "web_mm": self.web}, "critical"))

    def _check_pitch(self, plan: "Plan"):
        """A net class whose clearance does not fit its pads' pitch. A track
        of the class's width leaves a pad straight out from the part's body,
        along the part's nearer axis, centred on the pad; its lane is the
        distance from that track to the part's other pads of other nets. A
        pad with another pad straight ahead of it (inside a grid) leaves some
        other way and is not measured. Under the clearance, the router cannot
        escape the pad. One finding per part, on its tightest lane."""
        g = self.geometry
        reach = max([c.clearance for c in g.netclasses.values()] + [r.min_mm for r in self._rules if r.kind == "clearance"],
                    default=0.0)
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
                    need = self._clearance(p.net, q.net, fp.ref, fp.ref)
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
            plan.findings.append(self._finding(C.SETUP_PITCH, {
                "ref": fp.ref, "net_class": nc.name, "clearance_mm": nc.clearance, "track_mm": nc.track_width,
                "pad": p.number, "past_pad": q.number, "net": p.net, "past_net": q.net, "lane_mm": lane, "need_mm": need,
                "short": short, "fits_mm": math.floor(lane * 100 + 1e-6) / 100}, "critical"))

    def figure(self, *, at, rotation=0.0, anchor=(0.0, 0.0), why: str = "") -> Figure:
        """A datasheet figure's frame: its point `anchor`, in the figure's own
        coordinates (mm), lands on `at` (any point), turned about it by
        `rotation`, a number or `Turned(part, degrees)`, as a keepout's `Path`
        is. It places nothing. `fig.point(x, y)` is the figure's point
        (x, y), usable wherever a point is (a Pin's target, a track, finger
        or via point, `Polar(about=)`, `X()`/`Y()`, `Mid`); `keepout(...,
        frame=fig)` puts a path in the same frame.

        It is for a datasheet's dimensioned reference layout (an antenna
        land pattern, an RF keepout, a dimensioned crystal or sensor layout),
        its points typed as printed. `why=` is required: the datasheet and
        the figure or page the coordinates come from. It is not for a layout
        a datasheet shows without measurements, and not a way round a
        placement that intent can say."""
        return Figure(at, rotation, anchor, why)

    def keepout(self, shape, name: str, *, at=None, rotation=None, frame: Figure | None = None,
                margin: float | None = None, excludes=None, allow=(), layers=None,
                max_height: float | None = None, bars=(), why: str = "") -> KeepoutIntent:
        """A region that forbids. By default nothing may sit, fill, route, via
        or pad there on any copper layer the board has; `excludes` narrows
        what and `layers` narrows where. `allow` names the parts that may sit
        inside and the nets that may run through, which are different things:
        an antenna's clearance holds its own matching network, and naming
        those parts' nets would admit every part that shares one.
        `max_height` (a parts keepout) admits every part no taller, by its
        `Pm.Height`; a part with none counts as taller. `bars` (Parts and
        Cells) is the other way round: it keeps those out and lets every
        other part in, including one added to the board later; it does not
        go with `allow=` of parts or cells, and with `max_height` the parts
        it names are barred whatever their height. `rotation=` is a
        number, or `Turned(part, degrees)` to turn with a part already on
        the board, the same as a place() does. `frame=` is a
        `board.figure(...)` in place of `at=` and `rotation=`: the shape's
        points are read as the figure's own, with no move of the shape's box
        centre, so the keepout and the figure's points share one frame; the
        shape then carries no `anchor=` of its own.

        `shape` may instead be a Part or a Cell already on the board (no
        `at=` or `rotation=`, so `margin=` in their place): the region is
        that item's own drawn envelope grown by `margin` (default 0), and it
        moves and turns with the item, settled once the item is - a shape
        from an item, not a hand-built polygon.

        `shape` may be `Inside(Part(...), margin)`: the box inside that
        part's pads (`Inside`), settled the same way."""
        if frame is not None:
            if not isinstance(frame, Figure):
                raise TypeError("keepout %r: frame= is a board.figure(...), not %r" % (name, frame))
            if at is not None or rotation is not None:
                raise ValueError("keepout %r: frame= places the shape in the figure's frame; give no at= or "
                                 "rotation=" % name)
            if not hasattr(shape, "anchor"):
                raise ValueError("keepout %r: frame= places a Path, Slot or Circle in the figure's frame, not %r"
                                 % (name, shape))
            if shape.anchor is not None:
                raise ValueError("keepout %r: frame= reads the shape's points as the figure's own; give the "
                                 "shape no anchor= (the figure's anchor is its own)" % name)
            shape = dataclasses.replace(shape, anchor=frame.anchor)
            at, rotation = frame.at, frame.rotation
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
        bars = tuple(bars)
        if bars:
            if any(not isinstance(a, (Part, Cell)) for a in bars):
                raise TypeError("keepout %r: bars= names parts or cells, not %r"
                                % (name, next(a for a in bars if not isinstance(a, (Part, Cell)))))
            if any(isinstance(a, (Part, Cell)) for a in allow):
                raise ValueError("keepout %r: a keepout says one side. bars= names what it keeps out, allow= of "
                                 "parts or cells what it lets in; give one (allow= of nets goes with either)"
                                 % name)
            if "parts" not in (excludes if excludes is not None else ("parts",)):
                raise ValueError("keepout %r: bars= names parts, so it is for a keepout that excludes parts" % name)
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
                    None if max_height is None else float(max_height), region_of, bars)
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
                plan.findings.append(Finding(C.SETUP_LAYER_LOST, {
                    "variant": "keepout", "name": k.name, "layers": [l.value for l in lost],
                    "board_layers": len(self.geometry.layers)}, "notice"))
        for r in self.geometry.rule_areas:
            if r.missing:
                plan.findings.append(Finding(C.SETUP_LAYER_LOST, {
                    "variant": "rule_area", "name": r.base, "cell": r.cell, "layers": [l.value for l in r.missing]}, "notice"))

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

    def rect(self, width: float | None = None, height: float | None = None, chamfer: float = 0.0, radius: float = 0.0,
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

    def size(self, *args, **kwargs):
        """The old name of `rect`, removed: says what to write instead."""
        raise AttributeError("board.size(...) is board.rect(...) since 0.85.0: rename the call (migration.md, "
                             "\"To 0.85.0\")")

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
                raise ValueError("the board has no size yet: board.rect(), board.disc() or board.outline() says what it is")
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
            raise ValueError("the board has no size yet: board.rect() or board.disc() says what it is")
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
        elif self._escape_owner(at.item) is not None and not isinstance(at.item, (Lane, LanePoint)):
            item_kind = "escape"                        # board.escape()'s Escape, or the via of one of its lanes
        else:
            raise TypeError("%s: Beside's item is a Part, a Cell or a keepout (what board.keepout(...) "
                            "returns), or an escape (board.escape(...)) or the via of one of its lanes, not %r"
                            % (key, at.item))
        align = at.align
        if isinstance(at.side, SideOf):
            self._pad_ref(at.side.pads[0])              # a real pad, checked now
            self._facing_numbers(key, self._item(at.side.pads[0].part)[0], at.side)
            if isinstance(align, tuple) and len(align) == 2 and isinstance(align[1], (Past, Lane, X, Y)):
                raise TypeError("%s: a Beside on a SideOf side is settled when that part is placed; a %s in its "
                                "align checks the side now, so give an Edge or align a pad or an Along"
                                % (key, type(align[1]).__name__))
        if align is None:
            norm = ("along", Along.MID)
        elif isinstance(align, Along):
            norm = ("along", align)
        elif isinstance(align, PadRef):
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
            if len(align) != 2 or not isinstance(align[1], (PadRef, Past, Lane, X, Y, Mid, Origin)):
                raise TypeError("%s: Beside's align pair is (own_pad, PadRef(item, pad)), (own_pad, a point "
                                "of the other axis: X(...), Y(...), Mid(...), Origin(...)), (own_pad, "
                                "Past(pads, edge)) or (own_pad, esc[pin]), not %r" % (key, align))
            own_key, their = align
            if kind != "part":
                raise TypeError("%s: align=(own_pad, their_pad) needs the placed item's own pad; a %s has "
                                "none - align=Along.START/MID/END instead" % (key, kind))
            own_key = self._own_pad_key(geom, own_key)      # a real pad (or two, as Mid) of this part, checked now
            if isinstance(own_key, Mid) and isinstance(their, (Past, Lane)):
                raise TypeError("%s: a midpoint of two own pads aligns on a pad or a point; Past and a lane "
                                "stand an own pad's edge off the pads" % key)
            if isinstance(their, Past):
                self._check_beside_past(key, at.side, their)
                norm = ("past", own_key, their)
            elif isinstance(their, Lane):
                self._check_beside_lane(key, at.side, their)
                norm = ("lane", own_key, their)
            else:
                if isinstance(their, PadRef):
                    self.geometry.pad(their.part, their.key)    # and a real pad of the item named
                else:
                    self._check_beside_point(key, at.side, their)
                norm = ("pads", own_key, their)
        else:
            raise TypeError("%s: Beside's align is a PadRef, an (own_pad, their_pad) pair, Along.START/MID/END, "
                            "or nothing (Along.MID), not %r" % (key, align))
        if at.copper and item_kind != "item":
            raise TypeError("%s: Beside's copper= measures from pads; a %s has none" % (key, item_kind))
        return _BesideSpec(at.item, at.side, norm, at.gap, at.copper)

    def _check_beside_point(self, key: str, side: Edge, point) -> None:
        """A point in Beside's align: placed parts' pads or origins, and an X() on a side that
        decides y (NORTH, SOUTH), a Y() on one that decides x."""
        upright = side in (Edge.EAST, Edge.WEST)
        if isinstance(point, (X, Y)) and isinstance(point, Y) != upright:
            raise ValueError("%s: Beside on the %s side decides the part's %s, so the part is lined up on a %s: "
                             "%s(...), not %s(...)" % (key, side.name, "x" if upright else "y", "y" if upright else "x",
                                                      "Y" if upright else "X", type(point).__name__))
        for ref in _refs_in([point]):
            self._pad_ref(ref)                          # real pads, parts, cells

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
        if isinstance(p.edge, Edge) and (p.edge in (Edge.EAST, Edge.WEST)) == upright:
            raise ValueError("%s: Beside on the %s side decides the part's %s; the Past in its align decides "
                             "the other axis, so its edge is %s, not %s" % (
                key, side.name, "x" if upright else "y",
                "NORTH or SOUTH" if upright else "EAST or WEST", p.edge.name))
        if p.lane is not None:
            self.geometry.require_net(p.lane)

    def _check_beside_lane(self, key: str, side: Edge, lane: Lane) -> None:
        """A lane in Beside's align: this board's, and where its line is known now
        (turned across the row by an Edge), a line `side` leaves free."""
        if lane.board is not self:
            raise TypeError("%s: %s's lane is of another board" % (key, self._escapes[lane.index].key))
        decl = self._escapes[lane.index]
        if isinstance(decl.turn, Corner):
            raise ValueError("%s: pin %s's lane runs at 45, and has no line to stand a pad on; align to the pin's "
                             "end instead: Pin(key, X(lane.end), Y(lane.end))" % (key, lane.number))
        if isinstance(decl.turn, Edge):
            along_x = decl.turn in (Edge.EAST, Edge.WEST)       # the lane runs along x, so its line is a y
            if along_x != (side in (Edge.EAST, Edge.WEST)):
                raise ValueError("%s: Beside on the %s side decides the part's %s, and pin %s's lane lies along %s: "
                                 "a pad is centred across a lane, so it needs the side to decide the %s"
                                 % (key, side.name, "x" if side in (Edge.EAST, Edge.WEST) else "y", lane.number,
                                    "x" if along_x else "y", "x" if along_x else "y"))

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
        escape = self._escape_owner(spec.item) is not None
        items = [new_item] if isinstance(spec.item, KeepoutIntent) or escape else [spec.item, new_item]
        gap = self._row_gap(items, 0.0 if spec.gap is None else float(spec.gap))
        if escape:          # off copper of the escape's nets, as off a part's pads of them
            gap = max([gap] + [self._clearance_reach(n) for n in self._escape_nets(spec.item)])
        return gap

    def _beside_copper_standoff(self, occ: Occupancy, i: PlaceIntent, ox: float, oy: float) -> float:
        """Where `Beside(copper=True)` stands the part along its side's axis: the
        offset (x for an east or west side, y for a north or south one) at
        which every pad of it keeps, from every pad of `item` of another net
        that it faces across the side (as `ox`, `oy` line it up on the other
        axis), the clearance the pair needs plus `gap`: the greatest of the
        pairs' exact standoffs (`sweep_standoff`). Pads of one net set none;
        a net tie's own-net exemption is not applied, the pair's clearance is
        what `_clearance` says whatever the footprint is."""
        b = i.beside
        u = {Edge.EAST: (1.0, 0.0), Edge.WEST: (-1.0, 0.0), Edge.SOUTH: (0.0, 1.0), Edge.NORTH: (0.0, -1.0)}[b.side]
        gap = 0.0 if b.gap is None else float(b.gap)
        bare = self._bare_occupancy()
        _, own_shapes = bare.candidate_shapes(i.item, Placement(Location(0.0, 0.0), i.rotation, i.face))
        cross = (0.0, oy) if u[0] else (ox, 0.0)
        own = [s for s in own_shapes if s.kind in ("pad", "through")]
        members = [fp for fp in (self._item(b.item)[0].members if isinstance(b.item, Cell) else [self._item(b.item)[0]])]
        fixed = [s for fp in members for number in dict.fromkeys(p.number for p in fp.pads)
                 for s in occ.pad_shapes(fp.ref, number)]
        stand = None
        for mine in own:
            poly = tuple((x + cross[0], y + cross[1]) for x, y in mine.poly)
            for theirs in fixed:
                if mine.net and mine.net == theirs.net or not mine.layers & theirs.layers:
                    continue
                d = self._clearance(mine.net, theirs.net, mine.owner, theirs.owner) + gap
                t = sweep_standoff(poly, theirs.poly, u, d)
                if t is not None and (stand is None or t > stand):
                    stand = t
        if stand is None:
            raise ValueError("%s: Beside(copper=True) has no distance to take: no pad of it faces a pad of %s of another "
                             "net across the %s side; leave copper= out for an envelope's" % (
                                 i.key, self._item(b.item)[1], b.side.name))
        return round(stand * (u[0] or u[1]), 6)

    def _beside_shape_standoff(self, occ: Occupancy, i: PlaceIntent, ox: float, oy: float, gap: float):
        """Where Beside stands the part along its side's axis against the shapes `item`'s envelope is made
        of: the offset (x for an east or west side, y for a north or south one) at which no shape of the
        part's own envelope is nearer than `gap` to a shape of `item`'s, `ox`, `oy` lining it up on the other
        axis - the greatest of the shape pairs' last contacts (`sweep_standoff`, as `copper=True` takes the
        pads'). A mark drawn outside the body at a corner holds the part off only where the part stands over
        it; the envelope box, which every standoff here was, holds it off along the whole side. None when no
        pair of shapes comes within `gap` across the side. A `row(of=)` item stands off its `of` the same way."""
        item, side = i.stands_off
        u = {Edge.EAST: (1.0, 0.0), Edge.WEST: (-1.0, 0.0), Edge.SOUTH: (0.0, 1.0), Edge.NORTH: (0.0, -1.0)}[side]
        cross = (0.0, oy) if u[0] else (ox, 0.0)
        theirs = [s for s in occ._geometry(self._item(item)[0]).shapes if s.kind != "npth"]
        _, moved = self._bare_occupancy().candidate_shapes(i.item, Placement(Location(0.0, 0.0), i.rotation, i.face))
        mine = [s for s in moved if s.kind != "npth"]

        def along(box, far):            # the box's side nearest (far=False) or furthest along `u`
            xs, ys = (box.left, box.right), (box.top, box.bottom)
            return max(x * u[0] + y * u[1] for x in xs for y in ys) if far else \
                min(x * u[0] + y * u[1] for x in xs for y in ys)

        pairs = []
        for m in mine:
            box_m = Box(m.box.left + cross[0], m.box.top + cross[1], m.box.right + cross[0], m.box.bottom + cross[1])
            for f in theirs:
                # the last contact is at most where the boxes' own separation is `gap` (a polygon's distance is
                # never under its boxes'), and none at all when the boxes never come within `gap` across the side
                if u[0]:
                    over = max(box_m.top - f.box.bottom, f.box.top - box_m.bottom)
                else:
                    over = max(box_m.left - f.box.right, f.box.left - box_m.right)
                if over < gap:
                    pairs.append((along(f.box, True) + gap - along(box_m, False), m, f))
        best = None
        for bound, m, f in sorted(pairs, key=lambda p: -p[0]):
            if best is not None and bound <= best + 1e-9:
                break
            poly = tuple((x + cross[0], y + cross[1]) for x, y in m.poly)
            t = sweep_standoff(poly, f.poly, u, gap)
            if t is not None and (best is None or t > best):
                best = t
        if best is None:
            return None
        # A last contact is a root and a placement is written to 6 places: where that leaves a pair under the
        # gap by more than the collision check allows (1e-9), the part stands a micron further out.
        t = round(best, 6)
        near = [(m, f) for bound, m, f in pairs if bound >= best - 1e-6]
        while any(poly_distance(tuple((x + cross[0] + t * u[0], y + cross[1] + t * u[1]) for x, y in m.poly), f.poly)
                  < gap - 1e-9 for m, f in near):
            t = round(t + 1e-6, 6)
        return round(t * (u[0] or u[1]), 6)

    def _beside_placement(self, occ: Occupancy, plan: "Plan", i: PlaceIntent, push: bool = True) -> Placement:
        """Where `Beside(...)` puts the item: its own drawn envelope `gap`
        off `item`'s, on `side`, aligned across it."""
        b = i.beside
        if isinstance(b.side, SideOf):
            b = dataclasses.replace(b, side=self._side_of(occ, i.key, b.side))
            i = dataclasses.replace(i, beside=b)
        if isinstance(b.item, KeepoutIntent):
            pk = plan.keepouts.get(b.item.keepout.name)
            if pk is None:
                raise ValueError("%s: keepout %r has no place, so there is nothing to stand beside"
                                 % (i.key, b.item.keepout.name))
            item_box = Box.of_points(pk.poly)
        elif self._escape_owner(b.item) is not None:
            item_box = self._escape_box(occ, b.item)
        else:
            item_box = self._placed_envelope_box(occ, b.item)
        own_box = self.envelope(i.item, i.rotation, i.face)
        gap = self._beside_gap(b, i.item)
        # Against the shapes the item's envelope is made of, where it is a part or a cell (a keepout's and an
        # escape's are boxes, and a rider's is too: it is laid before the copper its host will carry is known); a Past that turns a corner takes the diagonal from the box standoff, so keeps it.
        shaped = (not isinstance(b.item, KeepoutIntent) and self._escape_owner(b.item) is None and i.key not in self._rider_of
                  and not (b.align[0] == "past" and isinstance(b.align[2].edge, Corner)))
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
            off = _lane_distance(self, own_pad.net, shapes, past.lane, past.width, own_pad.owner)
            if isinstance(past.edge, Corner):
                # the own pad's corner that faces back across the 45 stands `off` out along the
                # diagonal from the pads' corner; the side has decided one axis, this the other
                sx, sy = past.edge.signs
                c = _box_corner(box, past.edge)
                qx = own.left if sx > 0 else own.right
                qy = own.top if sy > 0 else own.bottom
                reach = off * math.sqrt(2.0)            # sx * dx + sy * dy of the own corner off the pads'
                if past.lane is not None:
                    # off the lane's own point as a track's Past takes it, rounded away from the pads,
                    # so that rounding cannot put the lane's track nearer the own pad than its clearance
                    lane = self.geometry.require_net(past.lane)
                    lw = self._width(lane, past.width)
                    d = (lw / 2.0 + max(self._clearance(sh.net, lane, sh.owner) for sh in shapes)) / math.sqrt(2.0)
                    px, py = _round_away(c.x + sx * d, sx), _round_away(c.y + sy * d, sy)
                    reach = (sx * (px - c.x) + sy * (py - c.y)
                             + (lw / 2.0 + self._clearance(lane, own_pad.net)) * math.sqrt(2.0))
                if ox is None:
                    ox = _round_away(c.x - qx + sx * (reach - sy * (qy + oy - c.y)), sx)
                else:
                    oy = _round_away(c.y - qy + sy * (reach - sx * (qx + ox - c.x)), sy)
            elif past.edge is Edge.EAST:
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
            if align_kind == "lane":
                # the own pad centred across the lane's line: a y for a lane along x, an x for one along y
                axis, at = self._lane_line(occ, their)
                if (axis == "y") != (b.side in (Edge.EAST, Edge.WEST)):
                    raise ValueError("%s: Beside on the %s side decides the part's %s, and pin %s's lane lies along "
                                     "%s, so it decides the %s" % (i.key, b.side.name, "x" if axis == "y" else "y",
                                                                  their.number, "x" if axis == "y" else "y", axis))
                if axis == "y":
                    oy = at - own_pad.y
                else:
                    ox = at - own_pad.x
            else:
                their_loc = _locate(self, occ, their)
                if b.side in (Edge.EAST, Edge.WEST):
                    oy = their_loc.y - own_pad.y
                else:
                    ox = their_loc.x - own_pad.x
        if shaped and i.key not in self._loose:
            stand = self._beside_shape_standoff(occ, i, ox, oy, gap)
            if stand is not None:
                was = ox if b.side in (Edge.EAST, Edge.WEST) else oy
                if abs(was - stand) > 1e-6:
                    self._tight[i.key] = abs(was - stand)           # nearer than the box put it
                if b.side in (Edge.EAST, Edge.WEST):
                    ox = stand
                else:
                    oy = stand
        if b.copper:
            stand = self._beside_copper_standoff(occ, i, ox, oy)
            if b.side in (Edge.EAST, Edge.WEST):
                ox = stand
            else:
                oy = stand
        placement = Placement(Location(round(ox, 6), round(oy, 6)), i.rotation, i.face)
        if shaped and push and not b.copper:         # copper=True measures pad copper: a body over the item's is for the collision check to name
            placement = self._beside_clear_of_others(occ, i, placement)
        return placement

    # ------------------------------------------------------------ room for declared copper
    _ROOM_KINDS = ("track", "pair", "via")
    _ROOM_KINDS_AFTER = _ROOM_KINDS + ("pour",)     # a fitted pour is held once its last member is placed, not in the firm passes

    def _snapshot(self) -> tuple:
        """What a pass over the firm items changes on the board, to put back: its attributes (a container copied), and the
        fields of every declaration (a turn, a run, an alignment, copper's freedom), and of every row an item is placed
        along, with the rows it is butted before or after: a row whose start is a reference finds it during the pass."""
        attrs = {k: (copy.copy(v) if isinstance(v, (dict, list, set)) else v) for k, v in self.__dict__.items()}
        rows = []
        for i in self._intents:
            row = i.along.row if isinstance(getattr(i, "along", None), _RowSlot) else None
            while isinstance(row, Row) and not any(row is r for r in rows):
                rows.append(row)
                row = row.anchor[1] if row.anchor is not None and row.anchor[0] in ("before", "after") else None
        things = [(o, copy.copy(o.__dict__)) for o in list(self._intents) + list(self._copper) + list(self._links) + rows
                  if hasattr(o, "__dict__")]
        return attrs, things

    def _restore(self, saved: tuple) -> None:
        attrs, things = saved
        self.__dict__.clear()
        self.__dict__.update({k: (copy.copy(v) if isinstance(v, (dict, list, set)) else v) for k, v in attrs.items()})
        for o, d in things:
            o.__dict__.clear()
            o.__dict__.update(d)

    def _redo_check(self, occ: Occupancy, plan: Plan, fixed_copper) -> None:
        """Whether this run is the one. Before the collisions of the firm items are judged (`fixed_copper` None): a Beside
        part that no step within reach let stand, because a firm Beside part placed before it was in its way, is placed
        before that part in the next run, and said so in its step. After the firm items and their escapes: the copper
        declared between firm items is planned as it would be drawn, and where it meets another declaration's copper or a
        placed part's pad, the Beside parts standing nearer than the box put them that it names (or all of them, when it
        names none) go back to the box's standoff; and where the copper is not where the last run planned it, the firm
        items are placed against these plans. A run that has none of this to change
        goes on; the last one that may be run says what did not settle (`fixed.room_unsettled`). A firm cell that chose
        among its arrangements has settled only when it took the one it took in the pass before: in the first pass there is
        none before, so a run with such a cell is run again."""
        changed = {k: self._arr_taken.get(k, []) + [v] for k, v in self._arr_choice.items()
                   if k in self._arr_prev and self._arr_prev[k] != v}
        unsettled = any(self._arr_prev.get(k) != v for k, v in self._arr_choice.items())
        if not self._redo and fixed_copper is not None:
            rooms = self._dry_rooms(occ, plan, fixed_copper) if self._room_seed else {}
            self._room_unsettled = _rooms_moved(self._room_seed, rooms, self.settings.place_copper_room_tolerance) \
                if self._room_seed else []
            self._arr_unsettled = {k: list(dict.fromkeys(a or "default" for a in took)) for k, took in changed.items()}
            return
        if not self._redo:
            return
        swaps, notes = self._swaps, self._swap_notes
        fresh = []
        for p, q in self._beside_blocked:
            if not any(x in swaps + fresh for x in ((p, q), (q, p))):
                fresh.append((p, q))
                notes = dict(notes, **{p: step_text.record("placed_before", other=q)})
        seed, loose, moved = self._room_seed, self._loose, []
        if fixed_copper is not None:
            rooms = self._dry_rooms(occ, plan, fixed_copper)
            squeezers, conflicted = self._squeezers(occ, rooms, fixed_copper)
            relaxed = (squeezers | frozenset(self._beside_hint)) - loose
            if not relaxed and conflicted:
                relaxed = frozenset(self._tight) - loose        # a squeeze no part is named for: every part nearer than the box
            moved = _rooms_moved(seed, rooms, self.settings.place_copper_room_tolerance) if seed else []
            if relaxed or moved or unsettled or (conflicted and not seed):
                raise _Redo(rooms, swaps + fresh, notes, loose | relaxed, self._arr_choice)
            self._room_unsettled = moved
        if fresh or (fixed_copper is None and frozenset(self._beside_hint) - loose):
            # before the firm collisions are judged: the parts a refused one is aligned with, nearer than the box, go back to it
            raise _Redo(seed, swaps + fresh, notes, loose | frozenset(self._beside_hint), self._arr_choice)

    def _room_context(self, occ: Occupancy, plan: Plan, ctx) -> "_CopperContext":
        """A copper context to plan declared copper in without drawing it: what the real one knows, copied."""
        room = _CopperContext(self, occ)
        room.plan = plan
        room.ops_at, room.via_at, room.pour_at = dict(ctx.ops_at), dict(ctx.via_at), dict(ctx.pour_at)
        room.planned_tracks, room.planned_vias = list(ctx.planned_tracks), list(ctx.planned_vias)
        room.fixed_tracks = list(ctx.fixed_tracks)
        room.dry = True         # a fitted pour is planned without its reach: the room it keeps is the fitted outline
        self._roomed = set()
        self._room_refused = {}
        return room

    def _dry_rooms(self, occ: Occupancy, plan: Plan, intents, ctx=None, kinds=None) -> dict:
        """{copper index: [Shape]}: where each track and via of `intents` (and each pour, in `kinds`) would be drawn, planned
        as the real plan plans it but committed nowhere. A declaration the plan cannot read yet (an end not placed) has none."""
        kinds = kinds or self._ROOM_KINDS
        if ctx is None:
            ctx = _CopperContext(self, occ)
            ctx.plan = plan
        out = {}
        for c in sorted(intents, key=lambda c: c.index):
            if c.key.split(" ")[0] not in kinds:
                continue
            try:
                ops = c.plan(ctx)
            except Exception:           # an end that is not placed, a form that needs what is not there yet
                continue
            ctx.ops_at[c.index] = ops
            shapes = []
            for op in ops:
                if isinstance(op, Via) and any(
                        x.net == op.net and x.kind in ("pad", "through") and point_in_polygon((op.at.x, op.at.y), x.poly)
                        for g in occ.items.values() for x in g.shapes if x.box.contains_point(op.at)):
                    continue            # a via in a pad of its net is carried by the part, and gives way with it
                if isinstance(op, (Track, Via, Pour)):
                    sh = _shape_of(op)
                    if sh is not None:
                        shapes.append(dataclasses.replace(sh, owner="room " + c.key, label=",".join(sorted(c.owners))))
            out[c.index] = shapes
        ctx.notes = Findings()
        return out

    def _squeezers(self, occ: Occupancy, rooms: dict, intents) -> tuple:
        """The Beside parts that stand nearer than the box put them (the shape standoff) and are an end of declared copper
        that meets other copper as planned - another declaration's, or a placed part's pad - or a placed part that the copper
        meets: they go back to the box's standoff, which kept that room. And whether any such meeting was found."""
        by_index = {c.index: c for c in intents}
        shapes = [(k, sh) for k, v in rooms.items() for sh in v]
        hits = set()
        for n, (k, a) in enumerate(shapes):
            for k2, b in shapes[n + 1:]:
                if k2 != k and a.net != b.net and a.box.overlaps(b.box, gap=occ._copper_reach) \
                        and occ._conflict(a, b, None, exact=True):
                    hits |= {(k, None), (k2, None)}
            for owner, g in occ.items.items():
                if owner in occ.pending or owner in by_index[k].owners:
                    continue                # a part the copper is planned from: it is planned round it
                for o in g.shapes:
                    if o.kind in ("pad", "through", "copper") and a.box.overlaps(o.box, gap=occ._copper_reach) \
                            and occ._conflict(a, o, None, exact=True):
                        hits.add((k, owner))
        out = set()
        for k, owner in hits:
            refs = set(by_index[k].owners) | ({owner} if owner else set())
            for it in self._intents:
                if getattr(it, "stands_off", None) is not None and it.key in self._tight and \
                        refs & {fp.ref for fp in members_of(it.item)}:
                    out.add(it.key)
        return frozenset(out), bool(hits)

    def _rooms_after(self, occ: Occupancy, plan: Plan, room_ctx, placed: set, other_copper, step) -> None:
        """After a searched item lands: the declared copper whose ends are all placed now is planned provisionally, and kept
        clear of by what is placed next."""
        todo = [c for c in other_copper if c.index not in self._roomed and c.owners and c.owners <= placed]
        if not todo:
            return
        pours = [c for c in todo if c.key.startswith("pour ")]
        todo = [c for c in todo if c not in pours]
        self._roomed |= {c.index for c in todo}
        got = self._dry_rooms(occ, plan, todo, room_ctx)
        for c in todo:      # a track it could not draw: the parts placed now are those it was refused with (its finding says so)
            if not any(isinstance(op, Track) for op in room_ctx.ops_at.get(c.index, ())):
                self._room_refused[c.index] = frozenset(placed)
        # a fitted pour is the last of what it joins: its vias are planned (here or before) as well as its pads placed
        pours = [c for c in pours if all(m.index in room_ctx.ops_at for m in c.members)]
        self._roomed |= {c.index for c in pours}
        got.update(self._dry_rooms(occ, plan, pours, room_ctx, self._ROOM_KINDS_AFTER))
        todo += pours
        shapes = [sh for v in got.values() for sh in v]
        if shapes:
            occ.set_rooms(occ.rooms + shapes)
            step.say("room_kept", **{"for": [c.key for c in todo if got.get(c.index)]})

    def _rooms_digest(self) -> str:
        """What the passes decided, for the reuse record: the planned copper and the orders turned."""
        if not self._room_seed and not self._swaps:
            return ""
        import hashlib
        text = repr(sorted((k, [(sh.owner, [tuple(round(c, 4) for c in p) for p in sh.poly]) for sh in v])
                           for k, v in self._room_seed.items())) + repr(self._swaps)
        return "|rooms:" + hashlib.sha256(text.encode()).hexdigest()[:16]

    def _beside_clear_of_others(self, occ: Occupancy, i: PlaceIntent, placement: Placement) -> Placement:
        """`_beside_clear` with a user's labels left out: they give way to a firm part, the part does not."""
        real = getattr(occ, "_occ", occ)
        was, real.labels_yield = real.labels_yield, True
        try:
            return self._beside_clear(occ, i, placement)
        finally:
            real.labels_yield = was

    def _beside_clear(self, occ: Occupancy, i: PlaceIntent, placement: Placement) -> Placement:
        """Beside's standoff from `item`, moved on out along its side's axis to the first place the collision
        rule (`Occupancy.legal`: everything placed on the face, the reservations, the edge) lets the part stand,
        when something else already placed lies in its way. Stepped out from the standoff, `place.beside_step` a
        time up to `place.beside_reach`, then bisected back to the first spot that stands. The standoff itself
        when it stands, and when nothing within reach does (the collision is then reported as any firm one is)."""
        u = {Edge.EAST: (1.0, 0.0), Edge.WEST: (-1.0, 0.0), Edge.SOUTH: (0.0, 1.0), Edge.NORTH: (0.0, -1.0)}[i.stands_off[1]]
        real = getattr(occ, "_occ", occ)        # a rider is laid in a view: the host and riders before it stand in it
        others = real.obstacles(real._geometry(i.item))
        group = [x for g in list(occ._moved.values()) + list(occ._cells.values()) for x in g.shapes if not x.carried] \
            if isinstance(occ, _Riding) else []
        mine = {fp.ref for fp in members_of(i.item)}
        # what declared copper is planned to be, but for copper planned from this part (it is planned round it)
        group += [x for x in real.rooms if not (set(x.label.split(",")) & mine)]
        loc, clr = placement.location, self.clearance

        def at(s: float) -> Placement:
            return Placement(Location(round(loc.x + s * u[0], 6), round(loc.y + s * u[1], 6)), i.rotation, i.face)

        past = self._firm_past_edge(i)

        def fits(s: float) -> bool:
            """Whether the part stands at `s` with nothing giving way: the cheap answer, all the move out asks."""
            p = at(s)
            if group and real.legal(i.item, p, clr, others=ShapeIndex(group), board=False) is not None:
                return False
            return real.legal(i.item, p, clr, others=others, past_edge=past, by_corners=True) is None

        def stands_at_standoff() -> bool:
            """As a firm item is judged: a via of its own or placed before it may give way."""
            if fits(0.0):
                return True
            if group and real.legal(i.item, at(0.0), clr, others=ShapeIndex(group), board=False) is not None:
                return False
            return real.legal_giving_way(i.item, at(0.0), clr, others=others, past_edge=past, by_corners=True)[0] is None

        stands = fits
        if stands_at_standoff():
            return placement
        step, reach = self.settings.place_beside_step, self.settings.place_beside_reach
        lo, hi = 0.0, None
        for k in range(1, int(reach / step + 1e-9) + 1):
            if stands(k * step):
                hi = k * step
                break
            lo = k * step
        if hi is None:
            self._beside_refused(real, i, placement, others, group, clr)
            return placement
        while hi - lo > 1e-4:
            mid = (lo + hi) / 2.0
            lo, hi = (lo, mid) if stands(mid) else (mid, hi)
        hi = math.ceil(hi * 1e6) / 1e6
        while not stands(hi):
            hi = round(hi + 1e-6, 6)
        return at(hi)

    def _beside_refused(self, real, i: PlaceIntent, placement: Placement, others, group, clr) -> None:
        """A Beside part that no step within reach lets stand: said, by what stood in its way. Provisional copper is
        `fixed.room`; a firm Beside part placed before it is noted, for the next pass to place the two the other way round."""
        blame: list = []
        if not (group and real.legal(i.item, placement, clr, others=ShapeIndex(group), board=False, blame=blame) is not None):
            real.legal(i.item, placement, clr, others=others, past_edge=self._firm_past_edge(i), blame=blame, by_corners=True)
        if not blame:
            return
        owner = blame[0].owner
        name = getattr(owner, "name", str(owner))
        if name.startswith("room "):
            plan = self._begin_plan
            if plan is not None:
                plan.findings.append(self._finding(C.FIXED_ROOM, {
                    "item": i.key, "copper": name[len("room "):], "net": getattr(owner, "net", ""),
                    "side": i.stands_off[1].name.lower(), "reach_mm": self.settings.place_beside_reach}))
            return
        q = next((it for it in self._intents if getattr(it, "beside", None) is not None and it.key != i.key
                  and it.kind in ("part", "cell") and name in {fp.ref for fp in members_of(it.item)}), None)
        if q is not None and q.key in self._settled and not ({fp.ref for fp in members_of(q.item)} & set(i.needs)):
            self._beside_blocked.append((i.key, q.key))
            return
        # refused by a part nothing can turn round: what it is aligned with, if that stands nearer than the box put it,
        # goes back to the box (the part it carries along with it stands off it again)
        it, seen = i, set()
        while it is not None and getattr(it, "stands_off", None) is not None and it.key not in seen:
            seen.add(it.key)
            parent = it.stands_off[0]
            if isinstance(parent, KeepoutIntent) or self._escape_owner(parent) is not None:
                break
            key = self._item(parent)[1]
            if key in self._tight:
                self._beside_hint.add(key)
                break
            it = next((x for x in self._intents if x.key == key), None)

    def _row_of_box_offset(self, occ: Occupancy, i: PlaceIntent, along: float) -> tuple:
        """(ox, oy) where the envelope box puts one item of a `row(..., of=)`: its own drawn envelope `i.clearance` (the
        row's line, already worked out) off `of`'s box, on `i.edge`; its body centre at `along` down the row."""
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
        return ox, oy

    def _row_of_nearer(self, occ: Occupancy, i: PlaceIntent) -> float:
        """How much nearer `of` than the envelope box puts them the items of `i`'s `row(of=)` all stand, along the row's
        edge axis: the least that any item's own standoff from the shapes `of`'s envelope is made of (`_beside_shape_standoff`,
        as Beside takes it) allows, so that every item clears the shapes it faces and the row keeps one line. 0.0 where the box
        stands: an item with no shape to face does not limit the row, but a rider, an overhanging row (a negative
        clearance, which reaches into `of`), an item taken back to the box (`_loose`) or one whose turn is not known yet
        does, for the whole row."""
        first, _ = self._row_members[i.key]
        keys = sorted((n, k) for k, (f, n) in self._row_members.items() if f == first)
        horizontal = i.edge in (Edge.EAST, Edge.WEST)
        away = 1.0 if i.edge in (Edge.EAST, Edge.SOUTH) else -1.0
        nearest = None
        for _, key in keys:
            j = i if key == i.key else next(x for x in self._intents if x.key == key)
            if j.key in self._rider_of or j.clearance < 0.0 or j.key in self._loose:
                return 0.0
            if j is not i and j.turned is not None:
                try:
                    j = dataclasses.replace(j, rotation=self._turned_rotation(occ, j))
                except Exception:               # what its turn reads is not placed yet
                    return 0.0
            along = j.along.resolve(self, occ) if isinstance(j.along, _RowSlot) else j.along
            ox, oy = self._row_of_box_offset(occ, j, along)
            stand = self._beside_shape_standoff(occ, j, ox, oy, j.clearance)
            if stand is None:
                continue
            nearer = away * ((ox if horizontal else oy) - stand)
            nearest = nearer if nearest is None else min(nearest, nearer)
        return 0.0 if nearest is None else nearest

    def _row_of_placement(self, occ: Occupancy, i: PlaceIntent, along: float) -> Placement:
        """Where one item of a `row(..., of=)` lands: its own drawn envelope `i.clearance` (the row's line, already worked
        out) off `of`'s, on `i.edge`; its body centre at `along` down the row, as an edge row's does. As Beside is
        (`_beside_placement`), the distance is taken from the shapes `of`'s envelope is made of, not the box round them, but
        one distance for the row: the nearest at which every item clears the shapes it faces (`_row_of_nearer`), so the
        row stays on one line. An item that then is in the way of something else already placed is moved on out where it
        is; a rider is laid by the box, and so is an overhanging row, which reaches into `of`."""
        ox, oy = self._row_of_box_offset(occ, i, along)
        shaped = i.key not in self._rider_of and i.clearance >= 0.0
        if shaped:
            nearer = self._row_of_nearer(occ, i)
            if abs(nearer) > 1e-6:
                self._tight[i.key] = abs(nearer)            # nearer than the box put it
                away = 1.0 if i.edge in (Edge.EAST, Edge.SOUTH) else -1.0
                if i.edge in (Edge.EAST, Edge.WEST):
                    ox -= away * nearer
                else:
                    oy -= away * nearer
        placement = Placement(Location(round(ox, 6), round(oy, 6)), i.rotation, i.face)
        if shaped:
            placement = self._beside_clear_of_others(occ, i, placement)
        return placement

    # ------------------------------------------------------------ placement
    def place(self, item, at=None, *, rotation: float | None = None, face: Face = Face.FRONT,
              radius: float | None = None, step: float | None = None, rotations=(),
              priority: Priority | None = None, required: bool = False, why: str = "",
              drops: Drops = Drops.ALL, budget: int | None = None, arrangements=None,
              _standoff: float | None = None, _row_of: object = None, _declare: bool = True) -> PlaceIntent:
        """Declare where an item goes: `at=` a place, whose kind says how
        much freedom is left.

        Location(x, y)          the origin (a cell: its box centre)        -> FIXED, no freedom
        Centre(x, y)            the body box centre; each axis a reference,
                                or a number with coordinates=True          -> FIXED, no freedom
        Location(x, None)       one axis pinned, the other free: the item
        Centre(None, y)         slides along the line, from across what it
                                connects to, else sharing it evenly     -> searched, one freedom
        Pin(key, x, y)          the item's own pad `key` (number or net)
        Pin(key, point)         lands on the point (a PadRef with `edge=`:
                                the pad lies against that edge)           -> FIXED, no freedom
        Pin(Mid(k1, k2), ...)   the midpoint of two own pads lands on it;
        Pin(key, ..., land=)    one land of a pin drawn as several does   -> FIXED, no freedom
        Origin(part)            the item's own origin on that part's (or
                                cell's frame) origin                      -> FIXED, no freedom
        Mid(a, b)               the origin (a cell: its box centre) on the
                                midpoint of two references, as a Location -> FIXED, no freedom
        OnEdge(edge, along=)    its reach at the keep-in, at that distance
                                (mm, a reference, Along.MID, Fraction(f))  -> EDGE, no freedom
        OnEdge(edge)            on that edge, wherever there is room:
                                midpoint alone, spread with its fellows,
                                aside from what is there                  -> searched, one freedom
        Near(location)          searched round a hint                     -> searched, two freedoms
        nothing                 seeded from its links                     -> searched, two freedoms

        `radius=`, `step=` and `rotations=` tune a search (seeded or Near).
        `budget=` is how many candidates the search may judge, over all its passes and the
        carried vias' giving way (default `place.step_budget`); a search that spends it
        takes the best spot it found, or leaves the item unplaced, and says how far it got.

        `arrangements=` (a cell only) is an arrangement id its module offers, or a list of them
        in the order tried; "default" is the module's own layout. Without it the cell may take
        any arrangement it offers. An id it does not offer leaves the cell unplaced, with
        `arrangement.missing` naming the ids it offers.

        `rotation=` is a number, `Turned(part, degrees)`, `Parallel(a, b, degrees)`
        (the item's x axis along the line between two points) or `Facing(pads,
        edge)` (the right-angle turn where those pads' row points at the edge;
        `Facing(pads, toward=pad)` faces them toward another part's pad).

        `required=True` says that failing to place this item stops the run,
        with the board as it stood and the biggest free rectangles on its
        face. It is independent of the rank and of whether the position is
        decided, and a required item is not negotiable even under
        `--keep-going`. Nothing else stops a run by itself.

        `drops=Drops.HALF` or `Drops.MIN` thins a cell's via fields where
        it is placed (see `Drops`); the fragment itself is untouched.

        `face=Face.EITHER` lets a searched part or cell (seeded, or `Near`) take
        either face: the search scans the front, then the back, scores them alike
        and adds `score.back_face` to a back spot. A position that is decided or
        along an edge, a block, and a turn that depends on the face are refused.
        """
        raw = {"rotation": rotation, "face": face, "radius": radius, "step": step, "rotations": rotations, "priority": priority,
               "required": required, "why": why, "drops": drops, "budget": budget, "_standoff": _standoff, "_row_of": _row_of}
        given_at = at
        radius = self.settings.place_radius if radius is None else radius
        step = self.settings.place_step if step is None else step
        geom, key, kind = self._item(item)
        if isinstance(budget, float) and budget.is_integer():
            budget = int(budget)                    # a probe writes its figures as numbers
        if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or budget < 1):
            raise TypeError("%s: budget= is the candidates the search may judge, a whole number of at least 1, not %r"
                            % (key, budget))
        try:
            face = Face(face)
        except ValueError:
            raise TypeError("%s: face is Face.FRONT/BACK/EITHER or \"front\"/\"back\"/\"either\", not %r"
                            % (key, face)) from None
        either = face is Face.EITHER
        if either:
            face = Face.FRONT       # what the rest of the declaration reads; _settle also tries the back
        try:
            drops = Drops(drops)
        except ValueError:
            raise TypeError("%s: drops is Drops.ALL/HALF/MIN or \"all\"/\"half\"/\"min\", not %r"
                            % (key, drops)) from None
        if drops is not Drops.ALL and kind != "cell":
            raise TypeError("%s: drops= thins a cell's via fields; a %s carries none of its own" % (key, kind))
        ids = ()
        if arrangements is not None:
            if kind != "cell":
                raise TypeError("%s: arrangements= selects among a cell's arrangements; a %s has none" % (key, kind))
            if isinstance(arrangements, str):
                ids = (arrangements,)
            elif isinstance(arrangements, collections.abc.Sequence):
                ids = tuple(dict.fromkeys(arrangements))        # a repeated id once, in its first place
            else:
                raise TypeError("%s: arrangements= is an arrangement id or a list of them, not %r" % (key, arrangements))
            if not all(isinstance(a, str) and a for a in ids):
                raise TypeError("%s: arrangements= names arrangements by their ids, as text, not %r" % (key, arrangements))
        if _declare and any(i.key == key for i in self._intents):
            raise ValueError("%s is already placed; one declaration per item" % key)
        center = edge = along = near = about = run = band = None
        rim = angle = radius_at = None
        outward = False
        overhang = 0.0
        pin_x = pin_y = None
        _centre_toward = None
        pinned = ""
        pin = pin_land = None
        beside = None
        cell_pin = None
        if isinstance(at, Pin) and kind == "cell" and isinstance(at.key, Part):
            # a member's footprint origin, not a pad (a winding's arc centre): number None
            member = next((fp for fp in geom.members if fp.inst == at.key.inst), None)
            if member is None:
                raise TypeError("%s: Pin's %r is not one of cell %s's members" % (key, at.key, key))
            cell_pin, center, at = (member.ref, None, 0.0, 0.0), at.axes, None
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
            cell_pin, center, at = pin_tuple, at.axes, None
        elif isinstance(at, Pin):
            if kind != "part":
                what = "a block is placed by its anchor's position, not a pad" if kind == "block" else \
                    "a cell has no pad of its own"
                raise TypeError("%s: a Pin places a part by its pad; %s" % (key, what))
            pin = self._own_pad_key(geom, at.key)           # a real pad (or two) of this part, checked now
            if at.land is not None:
                self._pad_land(PadRef(Part(geom.inst), pin, land=at.land))      # a real land
                pin_land = at.land
            center, at = at.axes, None
        elif isinstance(at, Mid):
            pass        # a point of references: stays in `at`, as a Location does; a cell's goes to its centre below
        elif isinstance(at, Origin):
            if kind != "part":
                raise TypeError("%s: at=Origin(...) stands a part's own origin on it; a %s is placed by a member's: "
                                "Pin(Part(member), Origin(...))" % (key, kind))
            # stays in `at`: _firm_placement stands the part's origin on it, as for a Location
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
            if at.band is not None:
                # a radius range: the band between two radii about a centre, searched (a bearing: a spoke segment)
                about = (self.centre if at.about is None else _as_point(at.about)) if about_now else at.about
                if kind == "block":
                    raise TypeError("%s: a block is laid from its anchor; a Polar radius range searches a part or a cell" % key)
                band, angle = at.band, (None if at.angle is None else bearing(at.angle))
                at = None
            else:
                if isinstance(at.angle, Bearing) and at.radius is None:
                    raise TypeError("%s: a Polar with a Bearing of two points needs its radius; a bearing is "
                                    "not a spoke to slide out along" % key)
                if at.radius is not None and at.angle is not None:
                    if about_now and not isinstance(at.angle, Bearing):
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
            _centre_toward = at if isinstance(at, Centre) else None
            if isinstance(at, Centre) and _declare:
                self._centres.append((key, at))
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
        tangent = self._tangent_of(key, kind, rotations, rotation, either, at=at, center=center, edge=edge, along=along,
                                   near=near, rim=rim, run=run, beside=beside, pin_x=pin_x, pin_y=pin_y, pin=pin,
                                   cell_pin=cell_pin, radius_at=radius_at, angle=angle, band=band, row_of=_row_of)
        if tangent is not None:
            rotations = ()
        rotations = self._turn_list(key, rotations)
        source = "auto" if priority is None else "script"
        # Whether the declaration decides the position is a different question
        # from how important the item is. A decided position goes down before
        # anything searched and nothing may push it; a priority orders the
        # items that are still being searched a spot. FIXED and EDGE answer the
        # first question, so they hold exactly when the position is decided.
        # A point with turns to search leaves its turn to the search: the item stays on the point
        turns_on_point = bool(rotations) and (at is not None or center is not None) and beside is None
        decided = (at is not None or center is not None or beside is not None
                   or ((edge is not None or run is not None) and along is not None)
                   or (rim is not None and angle is not None)) and not turns_on_point
        freedom = Freedom.SEARCHED if not decided else \
            Freedom.FIXED if (at is not None or center is not None or beside is not None) else Freedom.EDGE
        if decided and priority is not None:
            raise ValueError("%s: the declaration decided this position, so the item goes down before anything "
                             "searched and priority=%s has nothing to order; drop the priority, or drop the "
                             "position to have it searched" % (key, priority.value))
        priority = priority or Priority.DEFAULT
        if either:
            self._refuse_either(key, kind, rotation, at=at, center=center, edge=edge, along=along, pin_x=pin_x,
                                pin_y=pin_y, rim=rim, angle=angle, radius_at=radius_at, run=run, beside=beside,
                                cell_pin=cell_pin, pin=pin, row_of=_row_of,
                                about=None if band is not None else about)      # a band's about= is its centre
        faces_note = ""
        if isinstance(rotation, Facing):
            if kind != "part":
                raise TypeError("%s: rotation=Facing(...) turns a part by its pads; a %s has none of its own" % (key, kind))
            if rotations:
                raise ValueError("%s: rotation=Facing(...) settles the rotation; rotations= would override it" % key)
            if rotation.toward is None:
                rotation = self._facing_rotation(key, geom, rotation, face)     # of the part alone: settled now
            else:
                self._facing_numbers(key, geom, rotation)       # real pads of this part, checked now
        turned = rotation if isinstance(rotation, (Turned, Parallel, Facing)) else None
        if turned is not None and rotations:
            raise ValueError("%s: rotation=%s(...) settles the rotation; rotations= would override it"
                             % (key, type(turned).__name__))
        if isinstance(turned, Parallel) and kind == "block":
            raise TypeError("%s: a block is turned by its anchor, not rotation=Parallel(...)" % key)
        if turned is not None:
            rotation = float(getattr(turned, "degrees", 0.0))        # provisional: the ranking measures by it until the part is down
        rotation_given = rotation is not None
        if rotation is None:
            if isinstance(run, CutoutEdge):
                rotation, faces_note = None, ""      # the stretch is not known yet: turned when it is
            elif run is not None and isinstance(along, (int, float)):
                rotation, faces_note = self.outward_rotation(item, run.at(along)[1], face)
            elif run is not None and along is not None:
                rotation, faces_note = None, ""      # along is a reference: not known until it is placed
            elif rim is not None and angle is not None:
                rotation, faces_note = self.outward_rotation(item, angle + (180.0 if rim == "bore" else 0.0), face)
            elif edge is not None and along is None:
                rotation, faces_note = self.outward_rotation(item, edge, face)
            else:
                rotation, faces_note = 0.0, ""
        if kind == "cell" and at is not None and center is None:
            center, at = at, None
        needs = {self._pad_ref(ref)[0] for ref in _refs_in([at, center, along, pin_x, pin_y, near, about,
                                                            None if tangent is None else tangent.about])}   # a real pad, placed before this
        if isinstance(at, OnEdge) and isinstance(at.edge, CutoutEdge):
            needs.add(cutout_token(at.edge.name))   # the hole is cut before anything is put against it
        if isinstance(along, _RowSlot):
            needs |= along.row.needs
        if isinstance(turned, Turned):
            needs.add(self._pad_ref(turned.part)[0])   # turned by it: placed after it
        elif isinstance(turned, Facing):
            toward = turned.toward.pads[0] if isinstance(turned.toward, SideOf) else turned.toward
            needs.add(self._pad_ref(toward)[0])         # turned toward its pad: placed after its part
        elif turned is not None:
            line = {self._pad_ref(ref)[0] for ref in _refs_in([turned.a, turned.b])}
            if line & {fp.ref for fp in members_of(geom)}:
                raise ValueError("%s: rotation=Parallel(...) turns the part by a line between points placed first; "
                                 "a point of the part itself moves with it" % key)
            needs |= line                               # turned by the line between them: placed after both
        if beside is not None:
            needs.add(cutout_token(beside.item.keepout.name) if isinstance(beside.item, KeepoutIntent)
                      else self._pad_ref(beside.item)[0])
            if isinstance(beside.side, SideOf):
                needs.add(self._pad_ref(beside.side.pads[0])[0])       # its side is where that part's pad lands
            if beside.align[0] == "pads":
                needs |= {self._pad_ref(ref)[0] for ref in _refs_in([beside.align[2]])}
            elif beside.align[0] == "lane":
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
                             cell_pin=cell_pin, drops=drops, file=_script_site()[0], line=_script_site()[1],
                             toward=getattr(_centre_toward, "toward", None), pin_land=pin_land, either=either,
                             tangent=tangent, band=band, budget=budget, arrangements=ids)
        if _declare:
            self._intents.append(intent)
            self._place_calls[key] = (item, given_at, raw, self._compound)
            self._arrangement_enum = None
        return intent

    # ------------------------------------------------------------ arrangements
    @staticmethod
    def _refuse_coordinates(key: str, at) -> None:
        """An alternative is a relation, as the default is: no number as a coordinate."""
        def numeric(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool)
        if isinstance(at, Near):
            Board._refuse_coordinates(key, at.location)
            return
        bad = (isinstance(at, (Location, Centre)) and (numeric(at.x) or numeric(at.y))) or \
              (isinstance(at, tuple) and any(numeric(v) for v in at))
        if bad:
            raise TypeError("%s: an alternative is a relation (Beside, Pin, a turn), as the default is; %r names a coordinate"
                            % (key, at))

    def _member_key(self, item, grouped: bool = False) -> str:
        """The key of a part the script has placed with its own place(), which an option or a unit may move. A row's or ring's
        member is one only in a unit (`grouped`)."""
        geom, key, kind = self._item(item)
        call = self._place_calls.get(key)
        if call is None:
            raise ValueError("%s: an alternative or a unit moves a part the script has placed with place(), and the script has "
                             "not placed it; a block's member has none of its own" % key)
        if kind != "part":
            raise TypeError("%s: an alternative is for a part of a module; a %s's arrangements are the ones its own module "
                            "offers (arrangements= on its place())" % (key, kind))
        if not grouped and (key in self._row_members or call[3]):
            raise ValueError("%s is a member of a %s: an arrangement of a row is a unit (board.unit)"
                             % (key, "row" if key in self._row_members else call[3]))
        if "+" in key:
            raise ValueError("%s: an item key with a + cannot be named in an arrangement id" % key)
        return key

    def _checked_option(self, item, name: str, keywords: dict, *, grouped: bool = False) -> Option:
        site = _script_site()
        key = self._member_key(item, grouped)
        check_name("option", name)
        check_keywords(key, keywords)
        self._refuse_coordinates(key, keywords.get("at"))
        option = Option(key, name, tuple((k, v) for k, v in keywords.items() if k != "why"), keywords.get("why", ""), *site)
        self._intent_option(option)         # built now: a bad keyword or a bad relation is refused where it is written
        return option

    def alternative(self, item, name: str, *alts, **keywords):
        """Another way a part, or a unit, may stand.

        On a part the script has placed: an option on its `place()`, which stays its default. `keywords` are those of `place()`
        that change where an item goes (`at=`, `rotation=`, `rotations=`, `face=`, `radius=`, `step=`) and `why=`; every other
        keyword and each one not given is the item's own. An option that gives `rotation=` replaces the item's `rotations=` and
        `Turned`, and one that gives `rotations=` replaces its `rotation=`. Returns the Option.

        On a unit board.unit declared: one option of the unit, `Alt(member, **keywords)` for each member it moves (each at
        most once; a member it does not name keeps its place()), and `why=`. Returns the GroupOption.

        The module run lays out every arrangement and offers the ones that pass its own DRC and checks; the board's search
        chooses among them."""
        if isinstance(item, DeclaredGroup):
            raise TypeError("group %r is a KiCad group on the written board and takes no option; a set of parts that moves as one "
                            "unit of a module's arrangements is declared with board.unit(%r, Part(...), ...)" % (item.name, item.name))
        if isinstance(item, Group):
            return self._unit_alternative(item, name, alts, keywords)
        if alts:
            raise TypeError("%s: an item's alternative takes place() keywords, not %r: Alt(...) is for a unit's option "
                            "(board.unit)" % (self._item(item)[1], alts[0]))
        option = self._checked_option(item, name, keywords)
        held = self._unit_holding(option.item)
        if held is not None:
            raise ValueError("%s:%d: %s is a member of unit %r (%s:%d): a member moves with its unit, so the option is the "
                             "unit's: board.alternative(%s, %r, Alt(...))" % (option.file, option.line, option.item, held.name,
                                                                                 held.file, held.line, held.name, name))
        if any(o.name == name for o in self._options.get(option.item, ())):
            raise ValueError("%s already has an option %r" % (option.item, name))
        self._options.setdefault(option.item, []).append(option)
        self._arrangement_enum = None
        return option

    def _unit_alternative(self, group: Group, name: str, alts, keywords: dict) -> GroupOption:
        g = next((x for x in self._arr_groups if x.name == group.name), None)
        if g is None or g.positional:
            raise TypeError("board.alternative(%r, ...): %s; a unit whose options are declared one by one is board.unit's"
                            % (group.name, "board.arrangement declares a unit with its one option" if g is not None
                               else "this board declares no unit of that name"))
        extra = sorted(set(keywords) - {"why"})
        if extra:
            raise TypeError("unit %r: a unit's alternative takes Alt(member, **keywords) for each member it moves, not %s"
                            % (g.name, ", ".join(extra)))
        check_name("option", name)
        if any(o.name == name for o in g.alternatives):
            raise ValueError("unit %r already has an option %r" % (g.name, name))
        if not alts:
            raise ValueError("unit %r: option %r names no member: give Alt(member, **keywords) for each member it moves"
                             % (g.name, name))
        seen, options = set(), []
        for a in alts:
            if not isinstance(a, Alt):
                raise TypeError("unit %r: option %r takes Alt(member, **keywords), not %r" % (g.name, name, a))
            key = self._item(a.item)[1]
            if key not in g.members:
                raise ValueError("unit %r: option %r names %s, which is not a member of the unit (its members: %s)"
                                 % (g.name, name, key, ", ".join(g.members)))
            if key in seen:
                raise ValueError("unit %r: option %r names %s twice" % (g.name, name, key))
            seen.add(key)
            options.append(self._checked_option(a.item, name, a.keywords, grouped=True))
        option = GroupOption(g.name, name, tuple(options), keywords.get("why", ""), *_script_site())
        self._arr_groups[self._arr_groups.index(g)] = dataclasses.replace(g, alternatives=g.alternatives + (option,))
        self._arrangement_enum = None
        return option

    def arrangement(self, name: str, *alts, why: str = "") -> Group:
        """A unit of the members `alts` name, with one option: `Alt(item, **keywords)` for each (the keywords of `alternative`).
        The 0.99.15 form: its id is its name, and the members it does not name keep their `place()`. It combines with every other
        item and unit except one that moves a part it moves. To give a unit more than one option, declare it with
        board.unit."""
        check_name("arrangement", name)
        self._refuse_taken_unit(name)
        if not alts:
            raise ValueError("arrangement %r names no member: give Alt(item, **keywords) for each one it moves" % name)
        file, line = _script_site()
        seen, options = set(), []
        for a in alts:
            if not isinstance(a, Alt):
                raise TypeError("arrangement %r takes Alt(item, **keywords), not %r" % (name, a))
            o = self._checked_option(a.item, name, a.keywords, grouped=True)
            if o.item in seen:
                raise ValueError("arrangement %r names %s twice" % (name, o.item))
            held = self._unit_holding(o.item)
            if held is not None:
                raise ValueError("%s:%d: arrangement %r names %s, which unit %r (%s:%d) moves: a member is in one unit"
                                 % (file, line, name, o.item, held.name, held.file, held.line))
            seen.add(o.item)
            options.append(o)
        group = Group(name, tuple(options), why, file, line)
        self._arr_groups.append(group)
        self._group_after[name] = len(self._intents)
        self._arrangement_enum = None
        return group

    def unit(self, name: str, *members, why: str = "") -> Group:
        """A set of a module's parts that moves as one unit of its arrangements: `board.unit(name, Part, Part, ..., why="")`, the
        parts given one by one, each a part the script has placed with `place()`. Its default is each member's own place();
        `board.alternative(unit, option, Alt(...), ...)` adds each option, and it combines with every other item and unit. A
        member is in one unit only and has no alternative of its own. Returns the unit (the arrangements.Group record).
        (`board.group(name, [parts])` is the KiCad group on the written board and is a different call.)"""
        file, line = _script_site()
        check_name("unit", name)
        self._refuse_taken_unit(name)
        if not members:
            raise ValueError("unit %r names no member: give the parts that move together" % name)
        if any(isinstance(m, (list, tuple, set, frozenset)) for m in members):
            raise TypeError("unit %r takes its parts one by one, board.unit(%r, Part(...), ...), not in a list; a KiCad group on "
                            "the written board is board.group" % (name, name))
        keys = []
        for m in members:
            key = self._member_key(m, grouped=True)
            if key in keys:
                raise ValueError("unit %r names %s twice" % (name, key))
            other = next((g for g in self._arr_groups if key in g.members or key in g.moves()), None)
            if other is not None:
                raise ValueError("%s:%d: unit %r names %s, which %s %r (%s:%d) already moves: a member is in one unit"
                                 % (file, line, name, key, "unit" if other.members else "arrangement", other.name,
                                    other.file, other.line))
            own = self._options.get(key)
            if own:
                raise ValueError("%s:%d: unit %r names %s, which has its own alternative %r (%s:%d): a member moves with its "
                                 "unit, so give the unit that option" % (file, line, name, key, own[0].name, own[0].file,
                                                                          own[0].line))
            keys.append(key)
        group = Group(name, (), why, file, line, members=tuple(keys))
        self._arr_groups.append(group)
        self._group_after[name] = len(self._intents)
        self._arrangement_enum = None
        return group

    def _refuse_taken_unit(self, name: str) -> None:
        taken = next((g for g in self._arr_groups if g.name == name), None)
        if taken is not None:
            raise ValueError("a unit or arrangement %r is already declared (%s:%d)" % (name, taken.file, taken.line))

    def _unit_holding(self, key: str):
        """The unit board.unit declared with `key` as a member, or None."""
        return next((g for g in self._arr_groups if key in g.members), None)

    def exclude(self, *choices, why: str = "") -> Exclusion:
        """Every combination that holds all of `choices` is not laid out. A choice is `item.option`, `unit.option`, or a
        board.arrangement's name; two or more, checked where the script finishes declaring. For combinations the author knows
        cannot stand together, so the run does not prove them, and to bring a module under `place.arrangements_max` without
        dropping an option."""
        for c in choices:
            if not isinstance(c, str):
                raise TypeError("board.exclude takes choices as text ('item.option', 'unit.option' or a unit's name), "
                                "not %r" % (c,))
        rule = Exclusion(tuple(choices), why, *_script_site())
        self._exclusions.append(rule)
        self._arrangement_enum = None
        return rule

    def _unit_order(self) -> list:
        """Item keys with options and unit names, in the order the script first declared them: an item at its place(), a unit at
        its board.unit or board.arrangement call. With no unit: the items in place() order, as before units combined."""
        keyed = [((i.index, 1, 0), i.key) for i in self._intents if i.key in self._options]
        keyed += [((self._group_after[g.name], 0, n), g.name) for n, g in enumerate(self._arr_groups)]
        return [k for _, k in sorted(keyed)]

    def arrangement_units(self) -> list:
        """The units of this module's arrangements, in the order the script declared them (arrangements.units)."""
        return units(self._unit_order(), self._options, self._arr_groups)

    def _intent_option(self, option: Option) -> "PlaceIntent":
        """The PlaceIntent an option makes of its item: the item's own `place()` call with the option laid over it, built
        without being declared."""
        item, at, raw, _ = self._place_calls[option.item]
        call = merged_call(at, raw, option)
        return Board.place.__wrapped__(self, item, call.pop("at"), _declare=False, **call)

    def arrangement_enumeration(self) -> Enumeration:
        """The arrangements this module offers, the default first (`place.arrangements` false, or no declaration: the default
        alone). Over a limit: the default alone, with the facts of `arrangement.limit` (`arrangement_limit`)."""
        if self._arrangement_enum is None:
            if not self.settings.place_arrangements or not (self._options or self._arr_groups):
                self._arrangement_enum = Enumeration((DEFAULT_SPEC,), None, 1)
            else:
                self._arrangement_enum = enumerate_specs(self._unit_order(), self._options, self._arr_groups,
                                                         self.settings.place_arrangement_options_max,
                                                         self.settings.place_arrangements_max, tuple(self._exclusions))
        return self._arrangement_enum

    def arrangement_limit(self) -> dict | None:
        """The facts of `arrangement.limit` when the declarations pass a limit, else None."""
        return self.arrangement_enumeration().over

    def finish_declarations(self) -> None:
        """Called once the script has declared everything and before any resolve: the checks that need every declaration in.
        An `only=` names arrangements of this module; copper fitted round or drawn from other copper exists wherever that does."""
        if self._declarations_done:
            return
        self._declarations_done = True
        from .arrangements import all_ids, known_id
        self._check_units()
        order = self._unit_order()
        for c in self._copper:
            for ident in c.only:
                if not known_id(ident, order, self._options, self._arr_groups):
                    file, line = self._only_sites.get(c.index, ("", 0))
                    groups = [g.name for g in self._arr_groups]
                    products = [i for i in all_ids(order, self._options, self._arr_groups) if i not in groups]
                    raise ValueError("%s:%d: %s: only= names %r, which is not an arrangement of this module; it has "
                                     "arrangements: %s; groups: %s"
                                     % (file, line, c.key, ident, ", ".join(products), ", ".join(groups) or "none"))
        by_index = {c.index: c for c in self._copper}
        for c in self._copper:
            for idx in self._copper_uses.get(c.index, ()):
                m = by_index.get(idx)
                if m is not None and m.only and (not c.only or not set(c.only) <= set(m.only)):
                    file, line = self._only_sites.get(c.index, self._only_sites.get(idx, ("", 0)))
                    raise ValueError("%s:%d: %s is drawn from or fitted round %s, which exists only in %s: give it an only= "
                                     "inside that set" % (file, line, c.key, m.key, ", ".join(m.only)))

    def _check_units(self) -> None:
        """What the declarations make only once they are all in: a unit with no option, a unit named as an item with options,
        and each exclusion. Each an error of the script with its declaration's line."""
        for g in self._arr_groups:
            if not g.positional and not g.alternatives:
                raise ValueError("%s:%d: unit %r has no option: give it one with board.alternative(%s, name, Alt(...), ...), "
                                 "or drop the unit" % (g.file, g.line, g.name, g.name))
            if g.name in self._options:
                raise ValueError("%s:%d: unit %r has the name of an item with options of its own, so their ids would be one: "
                                 "name the unit for what it is" % (g.file, g.line, g.name))
        choice = {c.id: u for u in self.arrangement_units() for c in u.choices}
        for e in self._exclusions:
            where = "%s:%d: board.exclude(%s)" % (e.file, e.line, ", ".join(repr(c) for c in e.choices))
            if len(e.choices) < 2:
                raise ValueError("%s: an exclusion names two or more choices that cannot stand together; to drop one option, "
                                 "delete its declaration" % where)
            twice = sorted({c for c in e.choices if e.choices.count(c) > 1})
            if twice:
                raise ValueError("%s: names %s twice; an exclusion names each choice once" % (where, ", ".join(twice)))
            unknown = [c for c in e.choices if c not in choice]
            if unknown:
                raise ValueError("%s: %s is not a choice of this module; its choices: %s"
                                 % (where, ", ".join(unknown), ", ".join(choice) or "none"))
            for i, a in enumerate(e.choices):
                for b in e.choices[i + 1:]:
                    u, v = choice[a], choice[b]
                    if u.name == v.name:
                        raise ValueError("%s: %s and %s are both options of %s, which takes one at a time, so no arrangement "
                                         "holds both" % (where, a, b, u.name))
                    if u.moves & v.moves:
                        raise ValueError("%s: %s and %s both move %s, so they never combine and there is nothing to exclude"
                                         % (where, a, b, ", ".join(sorted(u.moves & v.moves))))

    def refuse_board_alternatives(self) -> None:
        """Raise ValueError when a board script (its outline drawn: not a module) declares alternatives. Alternatives are a
        module's: its run proves each one and a board that stamps it chooses among them. A run calls this once the script has
        declared everything."""
        if not self._draw_outline:
            return
        sites = [(o.file, o.line, "board.alternative") for opts in self._options.values() for o in opts] + \
            [(g.file, g.line, "board.unit" if g.members else "board.arrangement") for g in self._arr_groups] + \
            [(go.file, go.line, "board.alternative") for g in self._arr_groups for go in g.alternatives] + \
            [(e.file, e.line, "board.exclude") for e in self._exclusions]
        if not sites:
            return
        file, line, form = min(sites, key=lambda s: s[1])
        what = ("leaves out arrangements, and an exclusion belongs to a module's arrangements" if form == "board.exclude"
                else "declares an arrangement, which only a module offers")
        raise ValueError("%s:%d: %s %s: this script draws its board's outline, so it lays out a board. Declare it in the "
                         "module's own script, whose frame is not drawn (board.rect(..., draw=False))" % (file, line, form, what))

    def arrangement_specs(self) -> tuple:
        """The arrangements a module run lays out, the default first, once the declarations are checked."""
        self.finish_declarations()
        return self.arrangement_enumeration().specs

    _laid = DEFAULT_SPEC.id          # the arrangement the board's declarations are laid as

    def lay_arrangement(self, spec: Spec) -> None:
        """Put the board's declarations as arrangement `spec` has them: each option of `spec` laid over its item's
        PlaceIntent, which keeps its place in the declaration order, its line and the pushes made on it; and only the copper
        that exists in `spec`. Called on a board `_restore` has put back; `resolve()` lays the default."""
        for key, option in spec.overrides:
            old = next(i for i in self._intents if i.key == key)
            new = self._intent_option(option)
            new.index, new.line, new.file = old.index, old.line, old.file
            new.pushes = old.pushes
            for p in old.pushes:
                new.needs = new.needs | self._push_needs(p.source)
            old.__dict__.clear()
            old.__dict__.update(new.__dict__)
        kept = [c for c in self._copper if c.applies_in(spec.id)]
        if len(kept) != len(self._copper):
            self._copper = kept
        self._laid = spec.id

    @staticmethod
    def _refuse_either(key: str, kind: str, rotation, **decided) -> None:
        """`face=Face.EITHER` is for an item the search places freely: seeded, or round a `Near`.
        Anything that decides the position, an edge, a ring or a line, or turns the item to a
        side of the board, is judged on the one face it was declared for."""
        if kind == "block":
            raise ValueError("%s: a block is laid out at its anchor on one face; face=Face.EITHER is for a "
                             "searched part or cell" % key)
        if isinstance(rotation, Facing):
            raise ValueError("%s: rotation=Facing(...) turns a part by the face it is on, so it keeps a fixed "
                             "face; drop face=Face.EITHER or the Facing" % key)
        named = sorted(k for k, v in decided.items() if v is not None)
        if named:
            raise ValueError("%s: face=Face.EITHER is for an item whose spot is searched (seeded by its links, or "
                             "Near); this declaration decides or constrains it with %s, so give it a face"
                             % (key, ", ".join(named)))

    @staticmethod
    def _tangent_of(key: str, kind: str, rotations, rotation, either: bool, **place) -> Tangent | None:
        """The Tangent `rotations=` names (`Turns.TANGENT` is `Tangent()`), or None. Tangent turns
        are for an item whose spot is searched - seeded from its links, round a `Near`, or in a
        `Polar` band: the turn follows the spot, so a place that is decided or slides by its own rule
        is refused, with what turns an item there."""
        if rotations is Turns.TANGENT:
            rotations = Tangent()
        if not isinstance(rotations, Tangent):
            return None
        if kind == "block":
            raise TypeError("%s: a block is turned by its anchor; Tangent turns are for a part or a cell" % key)
        if rotation is not None:
            raise ValueError("%s: rotation= settles the rotation; Tangent turns would override it" % key)
        decided = sorted(k for k, v in place.items() if v is not None and k not in ("near", "band"))
        if place["band"] is not None and place["angle"] is not None:
            decided = sorted(set(decided) | {"a bearing"})
        if decided:
            raise ValueError("%s: Tangent turns follow a searched spot (seeded, Near, or a Polar band "
                             "Polar((r_min, r_max), None)); this place is decided or slides by its own rule (%s). "
                             "board.outward_rotation(item, bearing)[0] is the turn at one bearing"
                             % (key, ", ".join(decided)))
        return rotations

    def _turn_list(self, key: str, rotations) -> tuple:
        """The turns `rotations=` names: its angles as given, or - for a step in degrees, or
        `Turns.ANY` (`place.bearing_step`) - every step from 0 round the circle."""
        if rotations is None or (not isinstance(rotations, (int, float, Turns)) and not rotations):
            return ()
        if isinstance(rotations, (bool, int, float, Turns)):
            step = self.settings.place_bearing_step if rotations is Turns.ANY else rotations
            if isinstance(step, bool) or not isinstance(step, (int, float)) or not 0 < step <= 360:
                raise ValueError("%s: rotations= as a step is between 0 and 360 degrees, not %r; or give the "
                                 "angles, or Turns.ANY for every place.bearing_step" % (key, rotations))
            return tuple(round(k * float(step), 6) for k in range(int(math.ceil(360.0 / step - 1e-9))))
        return tuple(rotations)

    def _facing_numbers(self, key: str, geom, facing) -> list:
        """The pad numbers `facing`'s (or a `SideOf`'s) pads name on the part `geom`: a `PadRef`'s
        must be of that part, a bare key names the part's own pad."""
        me = Part(geom.inst)
        if any(isinstance(p, PadRef) and p.part != me for p in facing.pads):
            raise TypeError("%s: %s turns the part by its own pads, not by %s" % (
                key, type(facing).__name__,
                ", ".join("%s pad %s" % (p.part, p.key) for p in facing.pads
                          if isinstance(p, PadRef) and p.part != me)))
        return [self.geometry.pad(me, p.key if isinstance(p, PadRef) else p).number for p in facing.pads]

    def _facing_rotation(self, key: str, geom, facing: Facing, face: Face) -> float:
        """The turn `Facing(pads, edge)` says for the part `geom` on `face`: refused, naming the
        pads, where no right-angle turn points their way out at the edge."""
        numbers = self._facing_numbers(key, geom, facing)
        try:
            return facing_rotation(self._bare_occupancy(), geom, numbers, facing.edge, face)
        except ValueError as e:
            raise ValueError("%s: Facing(%s, %s): %s" % (
                key, ", ".join("pad %s" % n for n in numbers), facing.edge.name, e)) from None

    def _side_of(self, occ: Occupancy, key: str, side: SideOf) -> Edge:
        """The side `SideOf(pads)` names, read off `occ` where the pads' part stands now: their way out
        at its placed turn and face."""
        part = side.pads[0].part
        geom, _, kind = self._item(part)
        ref = self._pad_ref(part)[0]
        placed = occ.items[ref].reference
        numbers = self._facing_numbers(key, geom, side)
        try:
            if side.along:
                way = pad_row_end(self._bare_occupancy(), geom, numbers[0], placed.face)
            else:
                way = pad_way_out(self._bare_occupancy(), geom, numbers, placed.face)
            return way_out_side(way, placed.rotation)
        except ValueError as e:
            raise ValueError("%s: SideOf(%s): %s" % (key, ", ".join("pad %s" % n for n in numbers), e)) from None

    def _given_rotations(self, items, rotation, face: Face = Face.FRONT) -> list | None:
        """A row's, ring's or run row's `rotation=` as one number per item: a number, a `Facing` (each
        item resolves it for itself) or a list of either, one per item. None when not given."""
        if rotation is None:
            return None
        if isinstance(rotation, (list, tuple)):
            if len(rotation) != len(items):
                raise ValueError("rotation= as a list gives one turn per item: %d items, %d turns"
                                 % (len(items), len(rotation)))
            given = list(rotation)
        else:
            given = [rotation] * len(items)
        out = []
        for item, r in zip(items, given):
            if isinstance(r, Facing):
                geom, key, kind = self._item(item)
                if kind != "part":
                    raise TypeError("%s: rotation=Facing(...) turns a part by its pads; a %s has none of its own"
                                    % (key, kind))
                if r.toward is not None:
                    raise ValueError("%s: Facing(toward=) is settled when the part is placed, after the pad it turns "
                                     "toward; a row measures its items first - place the part, or give Facing an "
                                     "edge" % key)
                r = self._facing_rotation(key, geom, r, face)
            out.append(float(r))
        return out

    def _toward_rotation(self, occ: Occupancy, i: "PlaceIntent") -> float:
        """The turn of `Facing(pads, toward=pad)`: the pads' way out opposite the target pad's, where
        that part stands now."""
        t = i.turned
        target = t.toward if isinstance(t.toward, SideOf) else SideOf((t.toward,))
        edge = _OPPOSITE[self._side_of(occ, i.key, target)]
        return self._facing_rotation(i.key, i.item, Facing(t.pads, edge), i.face)

    def row(self, items, edge: Edge, *, of=None, gap: float | None = None, start=None, align=Along.START,
            rotation=None, line=Line.CENTRE, behind: Row | None = None, inboard: float | None = None,
            overhang: float = 0.0, pitch: float | None = None, over=None,
            centre=None, end=None, before: Row | None = None, after: Row | None = None, why: str = "") -> Row:
        """Items down `edge` in order, `gap` apart (default: courtyards
        touching), with their outward sides
        out (`rotation=`, a number or a `Facing(pad_key, edge)`, one value or
        one per item, overrides that turn for parts with no outward side). The row's outer line is the board's
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
        together with it.

        `over=[pad, ...]` (one `PadRef` per item, in the items' order) orders
        the row by where those pads lie along it, increasing, once they are
        placed: each item stands among its neighbours as its pad does among
        theirs. Equal coordinates are refused. Returns the Row."""
        align = _as_align(align, "a row's align")
        if over is not None:
            over = list(over)
            if len(over) != len(items):
                raise ValueError("a row's over= gives one pad per item: %d items, %d pads" % (len(items), len(over)))
            for ref in over:
                if not isinstance(ref, (PadRef, CellPadRef)):
                    raise TypeError("a row's over= is a PadRef for each item, not %r" % (ref,))
                self._pad_ref(ref)
            if isinstance(edge, Run):
                raise ValueError("a row along a run is not ordered by over= yet")
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
        given = self._given_rotations(items, rotation)
        rots = [self.outward_rotation(it, edge)[0] for it in items] if given is None else given
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
        for n, k in enumerate(keys):
            self._row_members[k] = (keys[0], n)
        if over is not None:
            row.over, row.declared, row.position = over, list(alongs), list(range(len(items)))
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
                if self._sized and over is None:    # the script's own size, not the generator's frame
                    row.begin(row.centre_of(self._outline))
                else:
                    row.anchor = ("outline", None)
            elif align is Along.END:
                if self._sized and over is None:
                    row.begin(row.end_of(self._outline, self.keep_in))
                else:
                    row.anchor = ("outline_end", None)
            elif over is not None:
                row.anchor = ("start", float(self.keep_in if start is None else start))
            else:
                row.begin(float(self.keep_in if start is None else start))
            if over is not None:
                row.needs = row.needs | frozenset(self._pad_ref(ref)[0] for ref in over)
        if over is not None and of is not None:
            row.needs = row.needs | frozenset(self._pad_ref(ref)[0] for ref in over)
        row.items = list(items)
        try:
            line = Line(line)
        except ValueError:
            raise ValueError("a row's line is centre, outer or inner, not %r" % (line,)) from None
        base = row.anchor[1] if row.anchor and row.anchor[0] in ("before", "after") else row
        ref = base.standoff + {"centre": base.depth / 2.0, "outer": 0.0, "inner": base.depth}[line]   # the line, from the edge
        clears = [ref - {"centre": d / 2.0, "outer": 0.0, "inner": d}[line] for d in depths]
        row.line = line.value          # the plain value: what a declaration digest wrote before Line existed
        self._compound = "row"
        try:
            for n, (item, r, c) in enumerate(zip(items, rots, clears)):
                along = row.centres[n] if row.start is not None else _RowSlot(row, n)
                self.place(item, at=OnEdge(edge, along=along), _standoff=c, rotation=r, why=why, _row_of=of)
        finally:
            self._compound = ""
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
        given = self._given_rotations(items, rotation)
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
        self._compound = "ring"
        try:
            for item, a, r in zip(items, angles, rots):
                self.place(item, at=(OnRim(a) if radius is None else Polar(radius, a, about=centre)), rotation=r, why=why)
        finally:
            self._compound = ""
        return Ring(float(radius) if radius is not None else None, angles,
                    max(depths) if depths else 0.0, list(items), [self._item(it)[1] for it in items])

    def _row_on_run(self, items, run: Run, *, gap, start, align, rotation, overhang, why, unsupported) -> "RunRow":
        """Items along one stretch of a shaped board's edge, in order from
        its start, each turned to the way the board faces where it sits."""
        for name, value in unsupported:
            if value is not None:
                raise ValueError("a row along a run does not take %s= yet: it starts at start=, or align=\"center\", "
                                 "and every item's reach sits at the keep-in" % name)
        given = self._given_rotations(items, rotation)
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
        self._compound = "row"
        try:
            for k, (item, along) in enumerate(zip(items, alongs)):
                rot = given[k] if given is not None else self.outward_rotation(item, run.at(along)[1])[0]
                self.place(item, at=OnEdge(run, along=along), rotation=rot,
                           _standoff=(-float(overhang) if overhang else self.keep_in), why=why)
                keys.append(self._item(item)[1])
        finally:
            self._compound = ""
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

    def escape(self, part, pins, *, turn=None, vias=(), depth=None, run=None, widths=None, pairs=(),
               chamfer: float | None = None, via_size: float | None = None, via_drill: float | None = None,
               why: str):
        """A pin row's routes out, kept clear from the moment the part is placed:
        each pin of `pins` (named as a PadRef names a pad: a number, a net or a
        PinName) gets a riser straight out along the row's way out and, with
        `turn=` (an Edge across the row, or a Corner for lanes at 45), a lane
        parallel to the row, ending in a via where `vias=` names the pin. The
        pin nearest the turn side takes the innermost lane. `depth=` (the
        innermost lane's offset past the pads' tips) and `run=` (how far lanes
        with no via run past the row's turn-side end) override the defaults,
        `widths=` gives a pin's track a width, and `pairs=[(a, b)]` runs two
        neighbouring lanes together at their net class's pair gap. `chamfer=`
        (default `copper.chamfer`) cuts the lanes' corners as `track()`'s does,
        and a track that begins with a lane is drawn with it unless its own
        `chamfer=` says otherwise; `via_size=` and `via_drill=` size the lanes'
        vias as `via()`'s do (default the board's). Returns the Escape:
        `esc[pin]` is a lane, the first point of a track, and `esc[pin].via`
        and `esc[pin].end` refer to its via and its end.

        Settled when the part is placed (`_place_escapes`): the risers, lanes
        and vias stand in the occupancy as copper of their own nets, so a part
        placed later keeps its other-net pads and holes a clearance off them,
        and a searched part's lanes are weighed in its search
        (`score.escape_lane`). A fanout keeps bodies off a part's pad rows;
        this keeps copper off the named pins' routes."""
        geom, key, kind = self._item(part)
        if kind != "part":
            raise TypeError("%s: an escape is a part's pin row; a cell or block has its own" % key)
        part = Part(geom.inst)
        pins = list(pins)
        if not pins:
            raise ValueError("%s: an escape names at least one pin" % key)
        numbers = []
        for pin in pins:
            n = self._escape_number(part, pin)
            if n in numbers:
                raise ValueError("%s: pin %s is named twice; an escape takes each pin once" % (key, n))
            if not next(p for p in geom.pads if p.number == n).net:
                raise ValueError("%s: pin %s has no net, and a lane carries its pin's net" % (key, n))
            numbers.append(n)

        def named(k, what):
            n = self._escape_number(part, k)
            if n not in numbers:
                raise ValueError("%s: %s names pin %s, which the escape does not (it names %s)" % (
                    key, what, n, ", ".join(numbers)))
            return n
        if turn is not None and not isinstance(turn, (Edge, Corner)):
            raise TypeError("%s: turn= is an Edge across the row or a Corner for lanes at 45, not %r" % (key, turn))
        for what, v in (("depth", depth), ("run", run), ("via_size", via_size), ("via_drill", via_drill)):
            if v is not None and not v > 0:
                raise ValueError("%s: an escape's %s= is more than 0, not %r" % (key, what, v))
        if chamfer is not None and chamfer < 0:
            raise ValueError("%s: an escape's chamfer= is 0 or more, not %r" % (key, chamfer))
        if run is not None and turn is None:
            raise ValueError("%s: run= is how far turned lanes run past the row's end; without turn= use depth=" % key)
        wide = {}
        for k, w in dict(widths or {}).items():
            if not w > 0:
                raise ValueError("%s: a lane's width is more than 0, not %r" % (key, w))
            wide[named(k, "widths=")] = float(w)
        via_numbers = frozenset(named(k, "vias=") for k in vias)
        pair_numbers = []
        for pair in pairs:
            a, b = (named(x, "pairs=") for x in pair)
            if a == b or any(x in used for used in pair_numbers for x in (a, b)):
                raise ValueError("%s: a pair is two different pins, each in one pair only" % key)
            pair_numbers.append((a, b))
        if pair_numbers and turn is None:
            raise ValueError("%s: pairs= runs two lanes together, and without turn= there are none" % key)
        lands = self._check_escape_row(geom, numbers, pair_numbers, turn)
        decl = EscapeDecl(len(self._escapes), part, geom.ref, tuple(numbers), turn, via_numbers,
                          None if depth is None else float(depth), None if run is None else float(run),
                          tuple(sorted(wide.items())), tuple(pair_numbers),
                          float(self.settings.copper_chamfer if chamfer is None else chamfer),
                          float(self.via_size if via_size is None else via_size),
                          float(self.via_drill if via_drill is None else via_drill), why)
        decl.lands = tuple(lands)
        self._escapes.append(decl)
        return Escape(self, decl.index, part)

    def _escape_number(self, part: Part, pin) -> str:
        """The pad number a pin is named by: a number, a net or a PinName, or a PadRef on that part."""
        if isinstance(pin, PadRef):
            if pin.part != part:
                raise ValueError("%s: %s is a pin of %s; an escape is one part's pin row" % (
                    part.inst, pin, pin.part.inst))
            pin = pin.key
        return self.geometry.pad(part, pin).number

    def _check_escape_row(self, fp, numbers: list, pairs: list, turn) -> list:
        """What an escape's pins say of themselves in the part as generated: one
        row (the same way out; a pin drawn as several lands stands in it by the
        land that leads out that way, returned as (number, 1-based land) pairs), a pair's
        lanes neighbours, and `turn=` across the row where the script already decided
        the part's rotation."""
        by_number: dict = {}
        for p in fp.pads:
            by_number.setdefault(p.number, []).append(p)
        boxes = {n: [p.box for p in ps] for n, ps in by_number.items()}
        centres = {(fp.ref, n): Box.union(bs).center for n, bs in boxes.items()}
        body = fp.body_box.center

        def way_of(box):
            way = _pin_normal(centres, fp.ref, box.center, fp.rotation, box)
            if way is None:
                d = math.hypot(box.center.x - body.x, box.center.y - body.y) or 1.0
                way = ((box.center.x - body.x) / d, (box.center.y - body.y) / d)
            return (round(way[0], 6) + 0.0, round(way[1], 6) + 0.0)
        try:
            ref_way, in_row = row_way(fp.inst, numbers, boxes, way_of)
        except EscapeError as e:
            raise ValueError(str(e)) from None
        lands = {n: Box.union([boxes[n][i] for i in in_row.get(n, range(len(boxes[n])))]).center for n in numbers}
        tangent = (-ref_way[1], ref_way[0])
        order = sorted(numbers, key=lambda n: lands[n].x * tangent[0] + lands[n].y * tangent[1])
        for a, b in pairs:
            if abs(order.index(a) - order.index(b)) != 1:
                raise ValueError("%s: pins %s and %s are not neighbours along the row, so their lanes cannot run "
                                 "together" % (fp.inst, a, b))
        intent = next((i for i in self._intents if getattr(i, "item", None) is fp), None)
        if (turn is not None and intent is not None and intent.rotation_given
                and isinstance(intent.rotation, (int, float)) and intent.face is Face.FRONT and not intent.either and fp.face is Face.FRONT):
            ux, uy = Transform.rotate(intent.rotation).apply(Transform.rotate(-fp.rotation).apply(ref_way))
            if abs(abs(ux) - 1.0) < 1e-6 or abs(abs(uy) - 1.0) < 1e-6:
                try:
                    turn_direction(turn, (float(round(ux)), float(round(uy))), "escape %s" % fp.ref)
                except EscapeError as e:
                    raise ValueError(str(e)) from None
        return [(n, in_row[n][0] + 1) for n in numbers if n in in_row and len(in_row[n]) < len(boxes[n])]

    def _lane_pad(self, lane: Lane):
        decl = self._escapes[lane.index]
        return self.geometry.footprint(decl.part).pad(int(lane.number) if lane.number.isdigit() else lane.number)

    def _escape_pin(self, esc: Escape, pin) -> str:
        decl = self._escapes[esc.index]
        n = self._escape_number(decl.part, pin)
        if n not in decl.pins:
            raise KeyError("%s: the escape does not name pin %s (it names %s)" % (decl.key, n, ", ".join(decl.pins)))
        return n

    def _lane_via(self, lane: Lane):
        """The via of a lane, declared the first time it is asked for (or a track
        begins with the lane): a via intent like `board.via()`'s, drawn where the
        escape laid it out. A lane's via nobody asks for is reserved but not drawn."""
        decl = self._escapes[lane.index]
        n = lane.number
        if n not in decl.vias:
            raise ValueError("%s: pin %s's lane ends level, with no via; name the pin in vias=" % (decl.key, n))
        decl.used_vias.add(n)
        intent = decl.via_intents.get(n)
        if intent is None:
            net = self._lane_pad(lane).net

            def plan(ctx):
                laid = self._escape_laid.get(decl.index)
                if laid is None or n not in decl.used_vias:
                    return []
                via = laid.lanes[n].via
                ctx.planned_vias.append(via)
                ctx.via_at[intent.index] = via.at
                return [via]
            intent = self._copper_intent("via %s" % net, net, Priority.DEFAULT, plan, [decl.part], decl.why)
            decl.via_intents[n] = intent
        return intent

    def _lane_points(self, net, lane: Lane) -> list:
        """The points a lane stands for as a track's first: its pad, the corner
        where its riser turns, its end (its via, which a track may end on)."""
        decl = self._escapes[lane.index]
        pad = self._lane_pad(lane)
        if self.geometry.require_net(net) != pad.net:
            raise ValueError("%s: pin %s is on %s, and its lane carries that net, not %s" % (
                decl.key, lane.number, pad.net, self.geometry.require_net(net)))
        decl.drawn.add(lane.number)
        end = self._lane_via(lane) if lane.number in decl.vias else LanePoint(lane, "end")
        key = int(lane.number) if lane.number.isdigit() else lane.number
        land = dict(decl.lands).get(lane.number)         # a pin drawn as several lands starts at the one in the row
        corner = decl.turn is not None or lane.number in decl.vias       # a lane without a turn may jog on its way to its via
        return [PadRef(decl.part, key, land=land)] + ([LanePoint(lane, "corner")] if corner else []) + [end]

    def _lane_layout(self, occ, decl: EscapeDecl):
        """The escape's layout: as settled when its part was placed, else as
        the part stands in `occ` now (a candidate, for what rides it)."""
        laid = self._escape_laid.get(decl.index)
        return laid if laid is not None else self._escape_layout(occ, decl)

    def _lane_point(self, occ, p: LanePoint) -> Location:
        decl = self._escapes[p.lane.index]
        geom = self._lane_layout(occ, decl).lanes[p.lane.number]
        if p.which == "corner":
            return geom.corner
        return geom.end

    def _escape_decl_of(self, item):
        """(the declaration, the pad number of the lane or None) of an Escape or of an escape's lane via."""
        if isinstance(item, Escape):
            return self._escapes[item.index], None
        for d in self._escapes:
            for n, v in d.via_intents.items():
                if v is item:
                    return d, n
        raise TypeError("%r is not an escape or an escape's via" % (item,))

    def _escape_nets(self, item) -> list:
        decl, number = self._escape_decl_of(item)
        return [self._lane_pad(Lane(self, decl.index, decl.part, n)).net for n in ([number] if number else decl.pins)]

    def _escape_box(self, occ, item) -> Box:
        """What an escape item occupies once its part is placed: the escape's risers, lanes and vias
        together, or a lane's via."""
        decl, number = self._escape_decl_of(item)
        layout = self._lane_layout(occ, decl)
        if number is None:
            return layout.box()
        via = layout.lanes[number].via
        return Box(via.at.x - via.size / 2.0, via.at.y - via.size / 2.0, via.at.x + via.size / 2.0, via.at.y + via.size / 2.0)

    def _lane_line(self, occ, lane: Lane) -> tuple:
        """("x" | "y", coordinate): the line a lane lies along, for a pad to stand on."""
        geom = self._lane_layout(occ, self._escapes[lane.index]).lanes[lane.number]
        if geom.line is None:
            raise ValueError("pin %s's lane runs at 45, and has no line to stand a pad on" % lane.number)
        return geom.line

    def _escape_layout(self, occ, decl: EscapeDecl, placement=None):
        """The escape laid out for the part where it stands in `occ`, or at a
        candidate `placement`. A pin off the row's way out, or a way out off
        the board's axes, is an EscapeError."""
        fp = self.geometry.footprint(decl.part)
        if placement is None:
            g = occ.items[fp.ref]
            shapes, rotation, face, body = g.shapes, g.reference.rotation, g.reference.face, g.body.center
        else:
            shapes = occ.shifted_shapes(fp, placement)
            rotation, face = placement.rotation, placement.face
            body = occ.shifted_body_box(fp, placement).center
        pads: dict = {}
        for s in shapes:
            if s.kind in ("pad", "through") and s.owner == fp.ref:
                pads.setdefault(s.label, []).append(s)
        boxes = {n: [s.box for s in ss] for n, ss in pads.items()}
        centres = {(fp.ref, n): Box.union(bs).center for n, bs in boxes.items()}

        def way_of(box):
            way = _pin_normal(centres, fp.ref, box.center, rotation, box)
            if way is None:
                d = math.hypot(box.center.x - body.x, box.center.y - body.y) or 1.0
                way = ((box.center.x - body.x) / d, (box.center.y - body.y) / d)
            return (round(way[0], 6) + 0.0, round(way[1], 6) + 0.0)
        axis, lands = row_way(decl.key, list(decl.pins), boxes, way_of)
        return Layouter(decl, pads, axis, _LaneEnv(self, occ, decl, pads, face), lands).lay_out()

    def _lane_pricer(self, occ, plan, i):
        """A candidate's lane cost (see Scorer): how many of the lanes the part's
        escapes lay out would be blocked at a placement, or None where `i` has no
        escape. A way out off the axes, or a turn along it, blocks every lane."""
        decls = [d for d in self._escapes if d.ref == getattr(i.item, "ref", None)]
        if i.kind != "part" or not decls or self.settings.score_escape_lane <= 0:
            return None

        def price(placement: Placement) -> int:
            n = 0
            for decl in decls:
                try:
                    laid = self._escape_layout(occ, decl, placement)
                except EscapeError:
                    n += len(decl.pins)
                    continue
                n += len(laid.blocked())
            return n
        return price

    def _escapes_named(self, obj, seen: set | None = None) -> set:
        """The indices of the escapes a position names: an escape, a lane, a point of a lane or a lane's via, anywhere in it."""
        seen = set() if seen is None else seen
        if id(obj) in seen:
            return set()
        seen.add(id(obj))
        if isinstance(obj, (Escape, Lane)):
            return {obj.index}
        if isinstance(obj, LanePoint):
            return {obj.lane.index}
        if isinstance(obj, CopperIntent):
            return {d.index for d in self._escapes if any(v is obj for v in d.via_intents.values())}
        if isinstance(obj, dict):
            obj = list(obj.values())
        if isinstance(obj, (tuple, list, set, frozenset)):
            return set().union(*(self._escapes_named(v, seen) for v in obj)) if obj else set()
        if isinstance(obj, _BesideSpec) or (dataclasses.is_dataclass(obj) and not isinstance(obj, type)
                                            and type(obj).__module__ == "placemat.values"):
            return set().union(*(self._escapes_named(getattr(obj, f.name), seen) for f in dataclasses.fields(obj)))
        return set()

    def _escapes_of(self, i: PlaceIntent) -> set:
        """The escapes an item's place is said in terms of: it waits until their lanes are laid out."""
        if not isinstance(i, PlaceIntent):
            return set()                    # a hole or a keepout names no escape
        if i.key not in self._escape_named:
            self._escape_named[i.key] = self._escapes_named([i.at, i.center, i.along, i.near, i.about, i.pin_x, i.pin_y, i.pin,
                                                             i.beside, i.turned, i.tangent])
        return self._escape_named[i.key]

    def _escape_wait_sets(self) -> dict:
        """For each escape, the keys of the firm items its lanes are laid out after: those said relative to its part (Beside
        it, a pin of it, a point on its pads) and decided, so that the lanes keep clear of them and do not run through where
        they land. An item that is said in terms of the escape itself, or of an item that is, is left out: it waits for the
        lanes, and the lanes cannot wait for it. A searched item, and a rider with it, is placed after the lanes are laid, and
        sees them."""
        if self._escape_waits is None:
            intents = [i for i in self._placements() if isinstance(i, PlaceIntent)]
            refs = {i.key: {fp.ref for fp in (i.item.members if i.kind == "block" else members_of(i.item))} for i in intents}
            self._escape_waits = {}
            for decl in self._escapes:
                after = {i.key for i in intents if decl.index in self._escapes_of(i)}
                grew = True
                while grew:
                    grew = False
                    held = set().union(*(refs[k] for k in after)) if after else set()
                    for i in intents:
                        if i.key not in after and i.needs & held:
                            after.add(i.key)
                            grew = True
                self._escape_waits[decl.index] = {i.key for i in intents if i.freedom.decided and i.key not in self._rider_of
                                                  and decl.ref in i.needs and i.key not in after}
        return self._escape_waits

    def _lanes_ready(self, i: PlaceIntent) -> bool:
        """Whether every escape an item's place is said in terms of has its lanes laid out."""
        return all(n in self._escape_laid for n in self._escapes_of(i))

    def _place_escapes(self, occ, plan: Plan, placed: set, progress, force: bool = False):
        """Every escape whose part is down and not yet laid out: its risers,
        lanes and vias stand in the occupancy as copper of their own nets from
        here on, and each lane something already placed blocks is a finding.
        The lanes are laid after the firm items placed relative to the part
        (`_escape_wait_sets`), unless `force`, so that they keep clear of them."""
        for decl in self._escapes:
            if decl.index in self._escape_laid or decl.ref not in placed or decl.ref not in occ.items:
                continue
            if not force and not self._escape_wait_sets()[decl.index] <= self._settled:
                continue
            ways = self._reserve_ways(occ, decl)
            try:
                laid = self._escape_layout(occ, decl)
            except EscapeError as e:
                e.escape, e.part = e.escape or decl.key, e.part or decl.part.inst
                raise
            finally:
                occ.remove_copper(ways)
            self._escape_laid[decl.index] = laid
            shapes = []
            for n in laid.order:
                name = "the escape lane of %s pin %s" % (decl.ref, n)
                kept = self._escape_kept[(decl.index, n)] = [dataclasses.replace(_shape_of(t), lane=name)
                                                              for t in laid.lanes[n].tracks]
                shapes += kept
                via = laid.lanes[n].via
                if via is not None:
                    shapes += [dataclasses.replace(_shape_of(via), lane=name),
                               dataclasses.replace(hole_shape("", via.at, via.drill, via.net, layers=frozenset(via.layers)),
                                                   lane=name)]
            occ.add_copper(shapes)
            for n, lane in laid.blocked():
                from . import suggest_facts
                plan.findings.append(self._finding(C.ESCAPE_LANE, {
                    "ref": decl.ref, "part": suggest_facts.inst_of(self, decl.ref), "pin": n, "net": lane.net,
                    "blocked": [w.to_json() for w in dict.fromkeys(lane.blocked)]}))
            notes = (step_text.record("lanes", n=len(laid.order), pins=list(decl.pins)),) + \
                ((step_text.record("lanes_blocked", n=len(laid.blocked())),) if laid.blocked() else ())
            plan.steps.append(Step(decl.key, "copper", Priority.DEFAULT, None, 0.0, notes, decl.why, len(laid.order)))
            if progress:
                progress("%-28s copper  escape   %s" % (decl.key, step_text.render_all(notes)))

    def _reserve_ways(self, occ, decl: EscapeDecl) -> list:
        """The copper, as planned now, of the firm tracks declared from a pad of the escape's part that is not one of its
        pins to pads that are placed (a bypass's track from the pin beside the row): it stands in the occupancy while the
        lanes are laid out, so that they leave room for it as they do for a placed part, and is taken out again, as the track
        is planned later with the lanes in place. A track whose plan does not draw is left out."""
        ctx = self.__dict__.get("_escape_ctx")
        shapes = []
        for c in self._copper:
            if c.index not in self._pad_tracks or not c.freedom.decided or decl.ref not in c.owners or ctx is None:
                continue
            pads = [self._pad_ref(r)[:2] for r in c.refs]
            if any(o not in occ.items or o in occ.pending for o, _ in pads):
                continue
            if any(o == decl.ref and n in decl.pins for o, n in pads) or not any(o == decl.ref for o, _ in pads):
                continue
            said = len(ctx.notes)
            ops = c.plan(ctx)
            del ctx.notes[said:]
            shapes += [sh for sh in (_shape_of(op) for op in ops if isinstance(op, Track)) if sh is not None]
        if shapes:
            occ.add_copper(shapes)
        return shapes

    def _release_lane(self, occ, lane: Lane) -> None:
        """A track begins with `lane`: its reserved riser and lane leave the occupancy, and the
        track's own copper (the same, or as its chamfer= cuts it) is judged in their place."""
        kept = self._escape_kept.pop((lane.index, lane.number), None)
        if kept:
            occ.remove_copper(kept)

    def _report_lanes(self, plan: Plan) -> None:
        """A lane reserved and never drawn: no track begins with it, so its room
        was kept for nothing."""
        for decl in self._escapes:
            if decl.index not in self._escape_laid:
                continue
            for n in decl.pins:
                if n not in decl.drawn:
                    from . import suggest_facts
                    plan.findings.append(self._finding(C.SETUP_LANE_UNUSED, {
                        "ref": decl.ref, "part": suggest_facts.inst_of(self, decl.ref), "pin": n}))

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

    def push(self, item, *, from_, falloff: float, reference: tuple, limit: float, why: str = "") -> Push:
        """Price how far `item` must stand from `from_`: value(r) = v_ref *
        (r_ref / r) ** falloff, `reference=(r_ref, v_ref)` in the script's
        own units. Illegal where value(r) exceeds `limit`; within that,
        each candidate is priced `score.push * value(r) / limit`, so the
        search moves the item as far out as its other terms allow.

        `item` is a `Part`, or a `PadRef` on one for where the sensing
        element is. `from_` is a `Part` or a `Cell` (its body centre), a
        `PadRef`, a keepout's name, or a `Location`. The source is placed
        first, the same order dependency a position said in terms of a pad
        already carries."""
        if not isinstance(item, (Part, PadRef)):
            raise TypeError("push: item is a Part or a PadRef on one, not %r" % (item,))
        owner, number, _, _ = self._pad_ref(item)     # the refdes: pads and needs speak refdes, not instance names
        target_pad_key = (owner, number) if isinstance(item, PadRef) else None
        intent = next((i for i in self._intents
                       if getattr(i, "item", None) is not None and owner in {fp.ref for fp in members_of(i.item)}),
                      None)
        if intent is None:
            raise ValueError("%s: push needs a place() declaration for this item before board.push()" % owner)
        if intent.kind == "block":
            raise TypeError("%s: push does not reach a block's member - it is searched as the block, "
                            "which never asks a member's own push" % owner)
        if isinstance(falloff, bool) or not isinstance(falloff, (int, float)) or not falloff > 0:
            raise ValueError("push: falloff is more than 0, not %r" % (falloff,))
        if not (isinstance(reference, tuple) and len(reference) == 2):
            raise TypeError("push: reference is (r_ref, v_ref), not %r" % (reference,))
        r_ref, v_ref = reference
        if isinstance(r_ref, bool) or not isinstance(r_ref, (int, float)) or not r_ref > 0:
            raise ValueError("push: reference's radius (r_ref) is more than 0, not %r" % (r_ref,))
        if isinstance(v_ref, bool) or not isinstance(v_ref, (int, float)) or not v_ref > 0:
            raise ValueError("push: reference's value (v_ref) is more than 0, not %r" % (v_ref,))
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not limit > 0:
            raise ValueError("push: limit is more than 0, not %r" % (limit,))
        if isinstance(from_, str) and from_ not in self._keepouts:
            raise ValueError("push: %r is not a keepout on this board" % (from_,))
        if isinstance(from_, (Part, PadRef)) and self._pad_ref(from_)[0] == owner:
            raise ValueError("push: %s cannot push itself; from_= is a different item" % owner)
        try:
            radius = r_ref * (v_ref / limit) ** (1.0 / falloff)
        except OverflowError:
            raise ValueError("push: falloff=%r is too small for reference=(%r, %r) and limit=%r - the "
                             "disc that formula asks for has no finite radius" % (falloff, r_ref, v_ref, limit)) from None
        if not radius < float("inf"):
            raise ValueError("push: falloff=%r is too small for reference=(%r, %r) and limit=%r - the "
                             "disc that formula asks for has no finite radius" % (falloff, r_ref, v_ref, limit))
        p = Push(from_, float(falloff), float(r_ref), float(v_ref), float(limit), target_pad_key, owner, why)
        intent.pushes = intent.pushes + (p,)
        intent.needs = intent.needs | self._push_needs(from_)
        return p

    def _push_needs(self, source) -> set:
        """What a push from `source` places first: its part, or its keepout."""
        needs = {self._pad_ref(r)[0] for r in _refs_in([source])}
        if isinstance(source, str):
            needs.add(cutout_token(source))   # a keepout settles like a hole: waited for the same way
        return needs

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

    def accept(self, check: str, subject: str, *, at_least: float | None = None,
               at_most: float | None = None, why: str = ""):
        """Take one design-check verdict as it is, with the reason. `subject`
        is what the verdict names as the run prints it: the net (`keep-out`,
        `crossings-under`, `current-path`, `switch-node`), the part (`heat`),
        "<ref> <kind>" (`exposure`) or the loop (`hot-loop`). Exactly one
        bound, on the side the check judges: `at_least=` for `keep-out` and
        `current-path`, `at_most=` for the rest. A failed verdict within the
        bound reads accepted; past it, it fails, naming the acceptance. It
        changes no placement or copper."""
        from . import checks
        a = checks.accept(check, subject, at_least, at_most, why)
        if any(x.check == a.check and x.subject == a.subject for x in self._acceptances):
            raise ValueError("%s %s is already accepted" % (a.check, a.subject))
        self._acceptances.append(a)
        return a

    def _part_keep_outs(self) -> None:
        """A part's `Pm.KeepOut` as clearance rules: between the copper on each
        net it says to stay away from and its own pads on each net it keeps
        clear (`rules.Rule.of`), at its distance, or the clearance the pair has
        otherwise where that is more. They stand after the script's rules, so
        the part's own, more particular, figure decides where both match.
        Refuses a `Pm.KeepOut` that does not read, naming the part."""
        from . import checks
        from .rules import Rule
        parts, refused = checks.keep_outs(self.geometry)
        if refused:
            raise ValueError("; ".join(why for _, why in refused))
        self._rules = [r for r in self._rules if r.of is None]
        self._clearance_rules_cache = None
        derived = []
        for ref, k in sorted(parts.items()):
            for away in k.away:
                for pads in k.pads:
                    base = self._clearance(away, pads)           # the script's rules and the netclass: never lowered
                    derived.append(Rule("clearance", max(k.distance_mm, base),
                                        "%s keep-out %s to %s: %s" % (ref, away, pads, k.source),
                                        between=(away, pads), of=ref))
        self._rules += derived
        self._clearance_rules_cache = None

    def _clearance_rules(self):
        """The declared clearance rules, read as KiCad judges them (rules.ClearanceRules)."""
        from .rules import ClearanceRules
        cache = self.__dict__.get("_clearance_rules_cache")
        if cache is None or cache[0] != len(self._rules):
            cache = (len(self._rules), ClearanceRules.of(self.geometry, self._rules))
            self._clearance_rules_cache = cache
        return cache[1]

    def _clearance(self, net_a, net_b, owner_a=None, owner_b=None) -> float:
        """The copper clearance between two items, as KiCad judges it: that of
        the last declared rule that matches them (`within=` reads their
        owners, a part's ref or a cell's name; a declared track has none),
        else the netclass pair's, else the board default when either has no
        net."""
        rule = self._clearance_rules().match(net_a or "", net_b or "", owner_a or "", owner_b or "")
        if rule is not None:
            return rule.min_mm
        nets = self.geometry.nets
        if net_a not in nets or net_b not in nets:
            return self.geometry.default_clearance
        return self.geometry.clearance(net_a, net_b)

    def _clearance_reach(self, net) -> float:
        """The most a net's copper can be asked to keep from another's: its
        class's figure, or a rule that raises it."""
        base = self.geometry.clearance(net) if net in self.geometry.nets else self.geometry.default_clearance
        return max([base] + [r.min_mm for r in self._rules if r.kind == "clearance" and r.of is None
                             and (r.on == net or (r.between is not None and net in r.between))])

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
                and i.rim is None and i.angle is None and i.radius_at is None
                and i.tangent is None and i.band is None)

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
                                    self.settings.solve_tolerance, self.settings.solve_centre_pull,
                                    self.settings.solve_spread_pull, self.settings.solve_spread_growth)
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

    def _scorer(self, item, occ: Occupancy, targets: list, prune: bool = True, pushes=(), lanes=None):
        """A candidate's cost: each connection's weight times its length,
        `score.crossing` for each ratsnest crossing its airwires would add,
        the escape weights, score.push times each push's modelled
        value over its limit, and `score.escape_lane` for each declared
        escape lane it would block (`lanes`). See `Scorer`."""
        return Scorer(self.settings, item, occ, targets, prune, pushes, lanes)

    def _push_source_point(self, occ: Occupancy, plan: Plan, source) -> Location:
        """Where a push's source sits, once it is placed: a keepout's own
        centre for a name, else wherever _locate finds a Part, Cell, PadRef
        or Location."""
        if isinstance(source, str):
            return plan.keepouts[source].centre
        return _locate(self, occ, source)

    def _emission_point(self, occ: Occupancy, ref: str) -> Location:
        """Where a placed source emits from, as things stand: its `Pm.EmitsAt`
        pad, or the point given in its own frame (turned and flipped with the
        footprint), or its origin."""
        at = self._annotations.sources[ref].at
        if at is not None and at[0] == "pad":
            return occ.pad_location(ref, at[1])
        here = occ.geometry_of(ref).reference
        x, y = (at[1], at[2]) if at is not None else (0.0, 0.0)
        return exposure.local_to_board(here.location, here.rotation, here.face, x, y)

    def _sense_point(self, occ: Occupancy, ref: str) -> Location:
        """Where a placed sensitive part senses: its `Pm.SensesAt` pad, else its body centre."""
        pad = self._annotations.sensitives[ref].senses
        return occ.pad_location(ref, pad) if pad is not None else occ.geometry_of(ref).body.center

    def _paired_refs(self) -> set:
        """The parts the cleanup pass leaves where the search put them: a
        source with a sensitive part of one of its kinds (a disc from a point
        inside the moving part is not exact), and a sensitive part with more
        than one source of a kind (a disc per source does not keep their sum).
        The pass judges a move by links and discs alone."""
        ann = self._annotations
        out = set()
        for ref, src in ann.sources.items():
            kinds = {e.kind for e in src.emissions}
            if any(sens != ref and kinds & {k for k, _, _ in s.limits} for sens, s in ann.sensitives.items()):
                out.add(ref)
        for sens, s in ann.sensitives.items():
            for kind, _, _ in s.limits:
                if sum(1 for ref, src in ann.sources.items() if ref != sens and any(e.kind == kind for e in src.emissions)) > 1:
                    out.add(sens)
        return out

    @staticmethod
    def _reach_from(occ: Occupancy, item, point: Location) -> float:
        """How far any part of `item`, turned any way, can lie from `point` (a
        point of the item where it stands): the distance to its box centre
        plus the box's half width and half height."""
        box = occ._geometry(item).reach or occ._geometry(item).body
        return point.distance(box.center) + (box.width + box.height) / 2.0

    def _annotated_pushes(self, occ: Occupancy, i: PlaceIntent) -> list:
        """The pushes `i` is in through the parts' own annotations: each
        sensitive part of `i` against every source of a kind already placed,
        and each source of `i` against every sensitive part of that kind
        already placed. The pair is judged by whichever of the two is placed
        second, so nothing waits for anything. A sensitive part placed second
        is board.push with the source's emission point as its source; a
        source placed second is the same push with the sensitive part's sense
        point as its source, measured from where `i` emits, and its hard
        limit is what the sources placed before it leave the part."""
        ann = self._annotations
        if not ann or i.kind == "block":
            return []
        own = {fp.ref for fp in members_of(i.item)}
        placed = {r for r in ann.sources.keys() | ann.sensitives.keys() if r not in own and r not in occ.pending}
        out = []
        for ref in sorted(own & ann.sensitives.keys()):
            s = ann.sensitives[ref]
            key = (ref, s.senses) if s.senses is not None else None
            for kind, limit, unit in s.limits:
                for src in sorted(placed & ann.sources.keys()):
                    for e in ann.sources[src].emissions:
                        if e.kind == kind:
                            out.append(Push(self._emission_point(occ, src), e.falloff, e.r_ref, e.value, limit, key, ref,
                                            label="%s %s" % (src, kind), kind=kind, unit=unit, sens=ref))
        for ref in sorted(own & ann.sources.keys()):
            src = ann.sources[ref]
            at = src.at
            key = (ref, at[1]) if at is not None and at[0] == "pad" else None
            here = self._emission_point(occ, ref)
            slack = self._reach_from(occ, i.item, here)
            if key is not None:
                here = None
            for e in src.emissions:
                for sens in sorted(placed & ann.sensitives.keys()):
                    for kind, limit, unit in ann.sensitives[sens].limits:
                        if kind != e.kind:
                            continue
                        point = self._sense_point(occ, sens)
                        others = 0.0
                        for other in sorted(placed & ann.sources.keys()):
                            if other == sens:
                                continue
                            others += sum(o.at(self._emission_point(occ, other).distance(point))
                                          for o in ann.sources[other].emissions if o.kind == kind)
                        out.append(Push(point, e.falloff, e.r_ref, e.value, limit, key, ref,
                                        label="%s (limit on %s)" % (sens, kind), kind=kind, unit=unit,
                                        hard_limit=limit - others, target_point=here, sens=sens, slack=slack))
        return out

    def _exposure_notes(self, occ: Occupancy, i: PlaceIntent, placement: Placement, pushes: list) -> list:
        """For each sensitive part and kind `i` pushes on, where `i` stands at
        `placement`: the summed value there of every placed source (`i`'s
        own included), the part's limit and the nearest source."""
        ann = self._annotations
        own = {fp.ref for fp in members_of(i.item)}
        pads = occ.candidate_pad_locations(i.item, placement)
        t = occ._transform(occ._geometry(i.item), placement)
        points: dict = {}

        def emission(ref):
            if ref not in own:
                return self._emission_point(occ, ref)
            at = ann.sources[ref].at
            if at is not None and at[0] == "pad":
                return pads[(ref, at[1])]
            g = occ.geometry_of(ref).reference
            x, y = (at[1], at[2]) if at is not None else (0.0, 0.0)
            return t.apply_location(exposure.local_to_board(g.location, g.rotation, g.face, x, y))

        def sense(ref):
            if ref not in own:
                return self._sense_point(occ, ref)
            pad = ann.sensitives[ref].senses
            if pad is not None:
                return pads[(ref, pad)]
            point = points.get(ref)
            if point is None:
                point = points[ref] = _target_point(occ, i.item, placement, ref)
            return point

        bits = []
        for sens, kind in sorted({(p.sens, p.kind) for _, p in pushes if p.sens}):
            at = sense(sens)
            limit = next(l for k, l, _ in ann.sensitives[sens].limits if k == kind)
            unit = next(u for k, _, u in ann.sensitives[sens].limits if k == kind)
            total, nearest = 0.0, None
            for ref, src in sorted(ann.sources.items()):
                if ref == sens or (ref not in own and ref in occ.pending):
                    continue
                r = emission(ref).distance(at)
                for e in src.emissions:
                    if e.kind == kind:
                        total += e.at(r)
                        if nearest is None or r < nearest[1]:
                            nearest = (ref, r)
            if nearest is not None:
                bits.append(step_text.record("exposure", quantity=kind, sensitive=sens, total=total, unit=unit, limit=limit,
                                           nearest=nearest[0], at_mm=nearest[1]))
        return bits

    def _exposure_accept(self, occ: Occupancy, i: PlaceIntent, pushes: list):
        """A candidate refusal for the sensitive parts' summed limits, or None
        when the pushes do not need one: a disc is exact for one source on
        the moving item, so only a limit shared by several pushes, or one
        measured from a point inside the moving item, is asked. A limit the
        sources placed before already exceed is not asked (no place helps)."""
        groups: dict = {}
        for point, p in pushes:
            if p.sens:
                groups.setdefault((p.sens, p.kind), []).append((point, p))
        groups = {k: g for k, g in groups.items() if (len(g) > 1 or g[0][1].slack > 0)
                  and (g[0][1].limit if g[0][1].hard_limit is None else g[0][1].hard_limit) > 0}
        if not groups:
            return None

        def accept(placement: Placement):
            pads = occ.candidate_pad_locations(i.item, placement)
            points: dict = {}
            for (sens, kind), group in groups.items():
                bound = group[0][1].limit if group[0][1].hard_limit is None else group[0][1].hard_limit
                total = 0.0
                for source_point, p in group:
                    at = _push_at(occ, i.item, placement, p, pads, points)
                    if at is not None:
                        total += _push_value(source_point, at, p)[0]
                if total > bound + 1e-9:
                    return Refusal(Code.EXPOSURE, sens=sens, kind=kind, total=total, unit=group[0][1].unit, bound=bound)
            return None
        return accept

    def _role_point(self, occ: Occupancy, ref: str, source: bool) -> Push:
        """A Push carrying only how to find a part's own measured point at a candidate placement
        (`_push_at`): a source's emission point, a sensitive part's sense point."""
        if source:
            at = self._annotations.sources[ref].at
            key = (ref, at[1]) if at is not None and at[0] == "pad" else None
            return Push(None, 1.0, 1.0, 1.0, 1.0, key, ref, target_point=None if key is not None else self._emission_point(occ, ref))
        pad = self._annotations.sensitives[ref].senses
        return Push(None, 1.0, 1.0, 1.0, 1.0, (ref, pad) if pad is not None else None, ref)

    def _lookahead_spots(self, occ: Occupancy, j: PlaceIntent, placed) -> tuple | None:
        """(every legal placement of the searched item `j` as things stand, the grid step they were found on):
        what its search would be offered, before any push of the part being placed now. The step is
        `place.lookahead_step`, or its own if that is coarser. None for an item whose search is not the generic one
        (a decided place, an edge, a run, a ring, a spoke, a line, a block, a rider), or on a board
        with no frame yet."""
        if (j.kind == "block" or j.freedom.decided or j.key in self._rider_of or j.turns_on_point
                or any(x is not None for x in (j.run, j.rim, j.radius_at, j.angle, j.edge, j.pin_x, j.pin_y))
                or self._fit or self._outline is None):
            return None
        frame = self._outline
        hint = Placement(_locate(self, occ, j.near), j.rotation, j.face) if j.near is not None else None
        hint, band, bt, within = self._band_frame(occ, j, placed, hint)
        if band is not None:
            radius = band[2] + hint.location.distance(band[0])
        elif j.near is not None:
            radius = j.radius
        else:
            if hint is None:
                hint = Placement(self.centre if bt is None else bt.centre, j.rotation, j.face)
            radius = max(math.hypot(x - hint.location.x, y - hint.location.y)
                         for x in (frame.left, frame.right) for y in (frame.top, frame.bottom))
            within = lambda x, y, f=frame: f.left <= x <= f.right and f.top <= y <= f.bottom
        spots: list = []

        def record(cand):
            spots.append(cand)
            return Refusal(Code.LOOKAHEAD_SPOT)
        step = max(j.step, self.settings.place_lookahead_step)
        budget, occ.step_budget = getattr(occ, "step_budget", None), None     # the partner's own spots, not the step's search: not counted
        try:
            for face in self._faces_of(j):
                turns_at = None if bt is None else self._spot_turns(occ, j, placed, band, face)
                scan(occ, j.item, Placement(hint.location, hint.rotation, face), radius, step, self._turns(j),
                     self.clearance, accept=record, turns_at=turns_at, within=within)
        finally:
            occ.step_budget = budget
        return spots, step

    @staticmethod
    def _room_lost(plan: Plan, i: PlaceIntent) -> dict:
        """What a part with no legal spot says of the look-ahead of a limit partner placed before it: {"gone": the
        partners placed when no room was left for it, "kept": those placed when room was left and what was placed since
        took it}; empty for none."""
        said = plan.__dict__.get("_room_lost", {}).get(i.key)
        if not said:
            return {}
        return {"gone": sorted(a for a, t in said.items() if t), "kept": sorted(a for a, t in said.items() if not t)}

    def _lookahead(self, occ: Occupancy, i: PlaceIntent, placed):
        """A candidate refusal for the pairs of `i` (a Pm.Emits source, a Pm.Limit part) whose other
        part is still to be searched: refused where no legal spot of that part is at the distance its
        limit asks. The pair is judged by whichever part is placed second, so the part placed first
        can take a spot that leaves the second none (the first spot the search likes best is the one
        nearest the middle of a small round board, and nothing is left at the limit distance from it).
        Each partner's legal spots are found once, as its own search would find them; a candidate is
        then asked only the distance to them (`exposure.reach`: the distance the limit asks, less
        what the sources placed already add at that spot), with a grid step to spare: a spot found
        on this grid stands for the one the partner's own search meets on its. None when no pair needs it."""
        ann = self._annotations
        if not ann or i.kind == "block" or not self.settings.place_lookahead:
            return None
        own = {fp.ref for fp in members_of(i.item)}
        owner = {fp.ref: x for x in self._placements() for fp in members_of(x.item)} if own & (ann.sources.keys() | ann.sensitives.keys()) else {}
        placed_sources = sorted(r for r in ann.sources if r not in own and r not in occ.pending)
        pairs = []          # (own ref, own is the source, other ref, kind, limit, emissions of the source)
        for a in sorted(own):
            if a in ann.sources:
                for b in sorted(ann.sensitives):
                    for kind, limit, _ in ann.sensitives[b].limits:
                        em = tuple(e for e in ann.sources[a].emissions if e.kind == kind)
                        if b != a and b not in own and em:
                            pairs.append((a, True, b, kind, limit, em))
            if a in ann.sensitives:
                for kind, limit, _ in ann.sensitives[a].limits:
                    for b in sorted(ann.sources):
                        em = tuple(e for e in ann.sources[b].emissions if e.kind == kind)
                        if b != a and b not in own and em:
                            pairs.append((a, False, b, kind, limit, em))
        spots_of: dict = {}
        needs = []
        margins = []        # the grid step each need's reaches were widened by
        for a, a_source, b, kind, limit, em in pairs:
            j = owner.get(b)
            if j is None or b not in occ.pending:
                continue
            if j.key not in spots_of:
                spots_of[j.key] = self._lookahead_spots(occ, j, placed)
            if not spots_of[j.key] or not spots_of[j.key][0]:    # not a generic search, or no spot at all: nothing to keep room for
                continue
            spots, margin = spots_of[j.key]
            others_at = lambda p, skip=(a, b), k=kind: sum(
                e.at(self._emission_point(occ, o).distance(p)) for o in placed_sources if o not in skip
                for e in ann.sources[o].emissions if e.kind == k)
            there = self._role_point(occ, b, not a_source)
            geom = occ._geometry(j.item)
            pts, seen = [], set()
            for spot in spots:
                at = _push_at(occ, j.item, spot, there, occ.candidate_pad_locations(j.item, spot), {})
                if at is None:
                    continue
                if a_source:
                    # b is sensitive and placed second: its body is held outside each emission's disc (the
                    # push's reservation, which fences b alone: in a cell, that member's box, not the cell's),
                    # and its sense point has what the sources placed leave of its limit
                    if geom.part_refs and b in geom.part_refs:
                        span = geom.parts[geom.part_refs.index(b)]
                    else:
                        span = geom.body if occ.envelope == "courtyard" else occ._extent(geom)
                    box = transform_box(span, occ._transform(geom, spot))
                    key = (round(at.x, 2), round(at.y, 2), round(box.left, 2), round(box.top, 2))
                    left = limit - others_at(at)
                    if key not in seen and left > 0:
                        seen.add(key)
                        pts.append((at.x, at.y, exposure.reach(em, left) + margin, (box.left, box.top, box.right, box.bottom)))
                elif (round(at.x, 2), round(at.y, 2)) not in seen:
                    seen.add((round(at.x, 2), round(at.y, 2)))
                    pts.append(at)
            if not pts:
                continue
            margins.append(margin)
            if a_source:
                disc = max(e.radius(limit) for e in em) * _DISC_INRADIUS + margin
                needs.append((a, True, b, kind, limit, em, (pts, _hull([Location(x, y) for x, y, _, _ in pts]), disc,
                                                           min(r for _, _, r, _ in pts)), others_at))
            else:
                needs.append((a, False, b, kind, limit, em, (_hull(pts), margin), others_at))
        if not needs:
            return None
        names = sorted({b for _, _, b, *_ in needs})
        here = {a: self._role_point(occ, a, s) for a, s, *_ in needs}
        last: dict = {}
        refused: list = []      # (need, where the candidate's own point was) for each refusal

        def accept(placement: Placement):
            pads = occ.candidate_pad_locations(i.item, placement)
            points: dict = {}
            for n, (a, a_source, b, kind, limit, em, far, others_at) in enumerate(needs):
                p = _push_at(occ, i.item, placement, here[a], pads, points)
                if p is None:
                    continue
                if a_source:
                    pts, hull, disc, nearest = far
                    if max(math.hypot(p.x - x, p.y - y) for x, y in hull) < nearest - 1e-9:
                        refused.append((n, p))
                        return Refusal(Code.LOOKAHEAD_FAR, partners=accept.partners, other=b, kind=kind)
                    k = last.get(n, 0)
                    for m, (x, y, r, (l, t, rt, bt)) in enumerate(pts[k:] + pts[:k]):
                        if (math.hypot(p.x - x, p.y - y) >= r - 1e-9
                                and math.hypot(max(l - p.x, 0.0, p.x - rt), max(t - p.y, 0.0, p.y - bt)) >= disc - 1e-9):
                            last[n] = (k + m) % len(pts)
                            break
                    else:
                        refused.append((n, p))
                        return Refusal(Code.LOOKAHEAD_FAR, partners=accept.partners, other=b, kind=kind)
                else:
                    left = limit - others_at(p)
                    if left > 0:
                        r = exposure.reach(em, left) + far[1]
                        if max(math.hypot(p.x - x, p.y - y) for x, y in far[0]) < r - 1e-9:
                            refused.append((n, p))
                            return Refusal(Code.LOOKAHEAD_DIST, partners=accept.partners, other=b, reach_mm=r)
            return None
        def misses():
            """{(own ref, other ref): (mm short, mm asked)} for the refused candidate that came nearest, per pair:
            how far short of the distance the limit asks the best spot of the other part fell. The grid step
            the reaches were widened by is taken off again."""
            out: dict = {}
            for n, p in {(n, round(p.x, 2), round(p.y, 2)): (n, p) for n, p in refused}.values():
                a, a_source, b, kind, limit, em, far, others_at = needs[n]
                margin = margins[n]
                if a_source:
                    best = None
                    for x, y, r, (l, t, rt, bt) in far[0]:
                        by_point, by_body = r - math.hypot(p.x - x, p.y - y), far[2] - math.hypot(max(l - p.x, 0.0, p.x - rt), max(t - p.y, 0.0, p.y - bt))
                        short, asked = (by_point, r) if by_point >= by_body else (by_body, far[2])
                        if best is None or short < best[0]:
                            best = (short, asked)
                    short, asked = best
                else:
                    left = limit - others_at(p)
                    asked = exposure.reach(em, left) + margin
                    short = asked - max(math.hypot(p.x - x, p.y - y) for x, y in far[0])
                got = (max(short - margin, 0.0), asked - margin)
                if (a, b) not in out or got[0] < out[a, b][0]:
                    out[a, b] = got
            return out

        accept.names = list(names)
        accept.partners = ", ".join(names)
        accept.pairs = [(a, b, owner[b].key) for a, _, b, *_ in needs]
        accept.misses = misses
        accept.bucket = "no room left for %s" % accept.partners
        return accept

    def _reserve_pushes(self, occ: Occupancy, plan: Plan, i: PlaceIntent) -> list:
        """Each push's source point, resolved now (it is placed by then,
        `needs` sees to that), and its hard-limit disc reserved against
        the part the push measures alone: the cell member it names, or the
        item. Every other part, the cell's other members too, is named in
        owners, so nothing else is fenced by it (Reservation.owners /
        let_in, occupancy.py)."""
        pushes = tuple(i.pushes) + tuple(self._annotated_pushes(occ, i))
        tag_prefix = "push:%s:" % i.key
        occ.reservations = [r for r in occ.reservations if not r.source.startswith(tag_prefix)]
        if not pushes:
            return []
        own = {fp.ref for fp in members_of(i.item)}
        refs = frozenset(fp.ref for fp in self.geometry.footprints)
        resolved = []
        for n, p in enumerate(pushes):
            point = self._push_source_point(occ, plan, p.source)
            limit = p.limit if p.hard_limit is None else p.hard_limit
            resolved.append((point, p))
            if not limit > 0:
                continue        # the sources placed before already use the sensitive part's whole limit: no distance helps
            try:
                radius = p.r_ref * (p.v_ref / limit) ** (1.0 / p.falloff) - p.slack
            except OverflowError:
                continue
            if not radius > 0:
                continue
            why = ReservedBy("push", _push_source_label(p), p.why or "", limit=limit, radius_mm=radius)
            fenced = {p.target_member_ref} if p.target_member_ref in own else own
            occ.reserve(_circle(point, radius), why, owners=refs - fenced, copper=False, source=tag_prefix + str(n))
        return resolved

    def _report_centres(self, occ: Occupancy, plan: Plan) -> None:
        """A Centre that writes `coordinates=False` is a notice, since that is the default."""
        for key, c in self._centres:
            if c.coordinates is False:
                plan.findings.append(self._finding(C.SETUP_CENTRE_FLAG_DEFAULT, {"item": key}, "notice"))

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
                from . import suggest_facts
                plan.findings.append(self._finding(C.SETUP_UNDECLARED, {
                    "item": fp.inst, "ref": fp.ref, "anchor": suggest_facts.last_place(self)}))

    def _report_splits(self, plan: Plan) -> None:
        """A cell whose members form two or more groups of
        `place.split_min_group` members or more, joined only by nets not
        local to the cell (splits.py): a finding, and a note on the cell's
        step."""
        from . import splits
        cells = [it for it in plan._items.values() if isinstance(it, CellGeom)]
        plane_nets = {net for net, _ in self._planes_declared}
        for name, facts in splits.report(self.geometry, cells, plane_nets, self.settings.place_split_min_group):
            plan.findings.append(self._finding(C.SPLIT_GROUPS, dict(facts, cell=name)))
            step = next((s for s in plan.steps if s.item == name), None)
            if step is not None:
                step.say("split", facts=facts)

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
            plan.findings.append(Finding(C.PAIR_CROSSED, {"pos": pos, "neg": neg, "parts": parts}))
        for n, e, f in rn.crossed_pair_list(esc.depth):
            ends = []
            for edge in (e, f):
                mine, other = (edge.a, edge.b) if edge.a.ref == n else (edge.b, edge.a)
                ends.append((mine.number, other.ref or "copper", edge.net))
            ends.sort(key=lambda t: (int(t[0]) if t[0].isdigit() else 1 << 30, t[0]))
            (pa, xa, na), (pb, xb, nb) = ends
            plan.findings.append(Finding(C.ESCAPE_CROSSED, {"ref": n, "pins": [pa, pb], "targets": [[xa, na], [xb, nb]]}))
        closed, walled = esc.confirmed()
        from . import suggest_facts
        for ref, number, net, by, joins in closed:
            plan.findings.append(self._finding(C.ESCAPE_CLOSED, dict(
                suggest_facts.escape_facts(self, occ, plan, ref, number, net, by), joins=list(joins))))
        for ref, number, net, by, _ in walled:
            plan.findings.append(self._finding(C.ESCAPE_WALLED, dict(
                suggest_facts.escape_facts(self, occ, plan, ref, number, net, by), variant="walled")))
        for ref, number, net, by in esc.handoffs_walled():
            plan.findings.append(self._finding(C.ESCAPE_WALLED, dict(
                suggest_facts.escape_facts(self, occ, plan, ref, number, net, by), variant="handoff")))
        if not self._draw_outline:
            self._report_vias_unneeded(occ, plan, esc)

    def _report_vias_unneeded(self, occ: Occupancy, plan: Plan, esc) -> None:
        """A module's via on an escape lane that the lane does not need (`Escapes.vias_unneeded`): the lane reaches the
        frame's edge on its own layer without it, so it ends there and the parent board's router decides whether it changes
        layer. A finding per via, naming whether `vias=` on the escape put it there or a `board.via` did."""
        from . import suggest_facts
        pins = list(dict.fromkeys((d.ref, n) for d in self._escapes if d.index in self._escape_laid for n in d.pins))
        if not pins:
            return
        ctx = self.__dict__.get("_escape_ctx")
        lane_intents = {id(v) for d in self._escapes for v in d.via_intents.values()}
        for ref, number, net, layers, vias in esc.vias_unneeded(pins, occ.board_box):
            seen = set()
            for v in vias:
                x, y = (v.circle[0], v.circle[1]) if v.circle else (v.box.center.x, v.box.center.y)
                if (round(x, 4), round(y, 4)) in seen:
                    continue                # a lane's via is reserved and drawn at one spot
                seen.add((round(x, 4), round(y, 4)))
                intent = _via_intent_at(self, ctx, net, x, y)
                lane = bool(v.lane) or (intent is not None and id(intent) in lane_intents)
                plan.findings.append(self._finding(C.ESCAPE_VIA_UNNEEDED, {
                    "ref": ref, "part": suggest_facts.inst_of(self, ref), "pin": number, "net": net,
                    "layers": [l.value for l in CopperLayer if l in layers],
                    "via": {"kind": "lane" if lane else "via", "at": [round(x, 4), round(y, 4)],
                            "key": copper_id(intent) if intent is not None and not lane else ""}}))

    def _report_pin_maps(self, plan: Plan) -> None:
        """The pin map study (pinmap.py) on the finished board: once per resolve, never inside the search. An explore's
        variants are studied by the explore (explore._pin_maps), on its best ones only. A study that raises leaves the
        resolve standing: its error is on `plan.pin_study` and a `setup.pins` finding."""
        from .pinmap_rules import has_pools
        if not has_pools(self.geometry.footprints):     # a board without a pool does not import the study or its core
            return
        from . import pinmap
        try:
            plan.findings.extend(pinmap.plan_findings(self, plan))
        except BaseException as e:                      # a stop or an interrupt still ends the resolve
            if not pinmap.contained(e):
                raise
            plan.findings.append(pinmap.study_failed(plan, e))

    def _report_links(self, occ: Occupancy, plan: Plan, placed: set):
        for l in self._links:
            if l.a[0] in placed and l.b[0] in placed:
                l.achieved_mm = round(occ.pad_location(*l.a).distance(occ.pad_location(*l.b)), 3)
                if not l.within_limit:
                    plan.findings.append(self._finding(C.LINK_OVER, self._link_over_facts(l)))
                    self._late_suggestions.append((plan.findings[-1], lambda f, l=l: self._measure_link_over(occ, plan, l, f)))
            plan.links.append(l)

    def _link_over_facts(self, l) -> dict:
        from .suggest_facts import inst_of, intent_of
        a, b = inst_of(self, l.a[0]), inst_of(self, l.b[0])
        facts = {"link": _link_key(l), "a": {"key": a, "ref": l.a[0], "pad": l.a[1]},
                 "b": {"key": b, "ref": l.b[0], "pad": l.b[1]}, "achieved_mm": l.achieved_mm, "limit_mm": l.limit_mm,
                 "weight": int(l.weight), "why": l.why}
        intent = intent_of(self, a)
        if intent is not None and intent.kind != "block":
            facts["a_searched"] = not intent.freedom.decided
            facts["a_priority"] = intent.priority.value if intent.priority_source == "script" else ""
        return facts

    def _measure_link_over(self, occ: Occupancy, plan: Plan, l, finding) -> None:
        """The sides of the link's far part its near end may stand beside, measured on the finished board."""
        from .suggest_facts import free_sides, intent_of
        facts = finding.facts
        intent = intent_of(self, facts["a"]["key"])
        if intent is None or intent.kind == "block":
            return
        step = next((s for s in plan.steps if s.item == intent.key and s.placement is not None), None)
        if step is None:
            return
        facts["free_sides"] = free_sides(self, occ, plan, intent, facts["b"]["key"], step.placement.location,
                                         step.placement.rotation, step.placement.face)

    # ------------------------------------------------------------ copper
    def _only(self, only, form: str) -> tuple:
        """The arrangement ids a copper declaration exists in: a non-empty sequence of ids, or None for every arrangement."""
        if only is None:
            return ()
        if isinstance(only, str) or not hasattr(only, "__iter__"):
            raise TypeError("%s: only= is a sequence of arrangement ids, only=(%r,) for one; got %r" % (form, only, only))
        ids = tuple(only)
        if not ids:
            raise ValueError("%s: only= is empty, so the declaration would exist in no arrangement; leave it out for every one" % form)
        if not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise TypeError("%s: only= is a sequence of distinct arrangement ids, not %r" % (form, only))
        return ids

    def _copper_intent(self, key, net, priority, plan, refs, why, bridge=False, extra_owners=frozenset(), only=()):
        """A copper declaration. WHEN it is planned is not asked here: it is
        derived in resolve(), once every placement is declared, because at
        declaration time a part placed later is invisible. `extra_owners`
        widens the owners a declaration with no refs of its own still waits
        on - a stitch over a pour waits on whatever the pour itself did."""
        name = self.geometry.require_net(net)
        pads = tuple(self._pad_ref(r) for r in refs)
        ci = CopperIntent(key, name, priority, plan, tuple(refs), why, len(self._copper), bridge,
                          frozenset(owner for owner, *_ in pads) | extra_owners, only=only)
        self._copper.append(ci)
        if only:
            self._only_sites[ci.index] = _script_site()
        return ci

    def faces(self, *, outward: Edge | None = None, quiet: Edge | None = None, handoff: Edge | None = None, why: str = ""):
        """A cell's sides, said once in its own script: `outward` is the
        side that faces the board edge (the connector mouth, the plungers),
        `quiet` the side to keep away from aggressors, `handoff` the side
        its signals leave from. Written into the fragment as a fact that
        rides with every stamped instance; a board turns the cell by it."""
        words = [k + "=" + Edge(v).value for k, v in (("outward", outward), ("quiet", quiet), ("handoff", handoff)) if v is not None]
        if not words:
            raise ValueError("faces() names at least one side")
        self._faces = ("placemat faces " + " ".join(words), why, {k: Edge(v).value for k, v in (("outward", outward), ("quiet", quiet), ("handoff", handoff)) if v is not None})

    def outward_rotation(self, item, edge, face: Face = Face.FRONT) -> tuple[float, str]:
        """The rotation that turns the item's outward side to `edge` - a board
        edge, or a bearing on a round board's rim - when it is placed on
        `face`, and the kind of note (step_text.py) when the item declared none (the generic rule:
        local +Y out). A flip to the back mirrors the item about the vertical
        axis before it turns, so on the back a side declared east is its
        west until turned; north and south are unchanged."""
        face = Face.FRONT if face is None else face if isinstance(face, Face) else Face(face)   # "front"/"back", as place() takes
        geom, key, kind = self._item(item)
        declared = geom.faces.get("outward") if kind == "cell" else None
        note = "" if kind != "cell" else "no_faces_declared"
        side = Edge(declared) if declared else None
        if side is not None and face is Face.BACK:
            side = {Edge.EAST: Edge.WEST, Edge.WEST: Edge.EAST}.get(side, side)
        if isinstance(edge, Edge):
            if side is None:
                return _OUTWARD_ROTATION[edge], note
            return _rotation_taking(side, edge), ""
        # A bearing: turning by r takes a side pointing along bearing b to b - r,
        # so the rotation is the side's own bearing less the one wanted.
        local = _EDGE_BEARING[side] if side is not None else _EDGE_BEARING[Edge.SOUTH]
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
        own box on its face is reserved against the items placed firmly
        afterwards; a searched item does not see it, and a label that is
        landed on gives way (a line of labels as one), staying beside its
        item."""
        gap = self.settings.label_gap if gap is None else gap
        size = self.settings.label_text_height if size is None else size
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
            self._label_ids[key] = (self._pad_ref(one)[0] if isinstance(one, (PadRef, CellPadRef)) else self._item(one)[1],
                                    str(txt))
            self._labels.append((key, one, txt, Edge(side), float(gap), align, float(size), float(thickness),
                                 bool(knockout), float(rotation), why, bool(reserve), group))
            keys.append(key)
        return keys[0] if group is None else keys

    def _width(self, net: str, width) -> float:
        return float(width) if width is not None else self.geometry.netclass(net).track_width

    def track(self, net, points, *, layer: CopperLayer, width: float | None = None,
              chamfer: float | None = None, bend: Bend | None = None, radius: float | None = None,
              priority: Priority = Priority.DEFAULT, bridge: bool = False, only=None, why: str = ""):
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
        shorter cut; `chamfer=0` keeps sharp corners). `bend=Bend.ARC` (the legs
        as above) or `Bend.ARC_FREE` (the straight lines between the points, at any
        angle) make every corner a circular arc tangent to both legs instead, of
        `radius=` mm or else `copper.arc_radius_track_widths` times the width; a corner
        the arc does not fit is a finding and the track is not drawn. `bridge=True`
        lets it pass under a same-layer track of another net it crosses (a
        via, a track on the opposite face, a via back) when it is the one
        that must yield: the lower priority, or at equal priority the shorter."""
        if bend is not None and not isinstance(bend, Bend):
            raise TypeError("bend is Bend.START, Bend.END, Bend.BOTH, Bend.ARC or Bend.ARC_FREE, not %r" % (bend,))
        arc = bend in (Bend.ARC, Bend.ARC_FREE)
        if radius is not None and not arc:
            raise TypeError("%s: radius= is the radius of an arc corner; give bend=Bend.ARC or Bend.ARC_FREE with it" % net)
        if arc and chamfer is not None:
            raise TypeError("%s: an arc track has no chamfer, its corners are arcs; drop chamfer= (radius= sets the arc)" % net)
        if arc and bridge:
            raise TypeError("%s: a track with arc corners cannot bridge, a bridge cuts a straight leg; use straight legs "
                            "(drop bend=) where it must pass under a track" % net)
        if arc and any(isinstance(p, Lane) for p in points):
            raise TypeError("%s: a lane is reserved with its own chamfer, so a track that starts on one cannot have "
                            "arc corners" % net)
        layer = CopperLayer.of(layer)
        if any(isinstance(p, Lane) for p in points[1:]):
            raise TypeError("%s: a lane stands for its riser, its lane and its via, so it is a track's first "
                            "point; a track goes on from it, it does not come back to one" % net)
        begins = None
        lane_points = ()
        if points and isinstance(points[0], Lane):
            begins = points[0]
            decl = self._escapes[begins.index]
            if width is None:
                width = decl.width_of(begins.number)    # the lane's own, when widths= gave one
            if chamfer is None:
                chamfer = decl.chamfer                  # drawn as the escape laid and reserved it
            else:
                decl.chamfers[begins.number] = float(chamfer)       # and laid and reserved as it is to be drawn
            lane_points = self._lane_points(net, begins)
            points = lane_points + list(points[1:])
        chamfer = self.settings.copper_chamfer if chamfer is None else chamfer
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
        arc_r = None
        if arc:
            arc_r = float(radius) if radius is not None else self.settings.copper_arc_radius_track_widths * w
            if not arc_r > w / 2.0:
                raise ValueError("%s: an arc's radius (%.3f mm) must be above half the track's width (%.3f mm); give "
                                 "radius= or set copper.arc_radius_track_widths" % (name, arc_r, w / 2.0))

        def plan(ctx):
            lost = [p for p in points if isinstance(p, CopperIntent) and p.index not in ctx.via_at]
            if lost:
                ctx.note(C.COPPER_NOT_DRAWN, {"variant": "via_lost", "track": name, "lost": [p.key for p in lost]})
                return []
            located = []
            lanes = []                # per point: the 45's directions at a Past off a corner, else None
            corners = []              # the Pasts off a corner
            for p in points:
                lane = None
                if isinstance(p, Between):
                    at = _between_point(self, ctx, name, w, p)
                elif isinstance(p, Past):
                    at = _past_point(self, ctx, name, w, p, intent.key, intent.index)
                    if isinstance(at, Refusal):
                        ctx.note(C.COPPER_NOT_DRAWN, {"variant": "past", "item": intent.key,
                                                      "names": _past_names(self, p), "why": at.to_json()})
                        return []
                    if isinstance(p.edge, Corner):
                        corners.append(p)
                        lane = _lane_dirs(p.edge)
                elif isinstance(p, PadRef) and p.edge is not None:
                    at = _edge_point(self, ctx.occ, w, p)
                else:
                    at = ctx.locate(p)
                located.append(at)
                lanes.append(lane)
            n_lane = len(lane_points)
            kept = list(points)
            if begins is not None and decl.turn is None:
                # a lane without a turn has a corner only where it jogs: where it has none the point is its end's
                for i in range(n_lane - 2, -1, -1):
                    if isinstance(points[i], LanePoint) and points[i].which == "corner" and located[i] == located[i + 1]:
                        del located[i], lanes[i], kept[i]
                        n_lane -= 1
            # a tap is a point beside its pad, not a pad end a track may leave at any angle
            pads = [isinstance(p, (PadRef, CellPadRef)) and getattr(p, "edge", None) is None for p in kept]

            # a lane's own legs are the lane as it was laid out and reserved, whatever stands near it: a detour round
            # copper that is too near runs over the lane beside it, and a lane that cannot keep clear is a finding
            frozen = {(a.x, a.y, b.x, b.y) for a, b in zip(located[:n_lane], located[1:n_lane])}

            def clear(a, b):          # a leg that touches no pad of another net
                if (a.x, a.y, b.x, b.y) in frozen:
                    return True
                shape = _shape_of(Track(name, layer, w, a, b))
                return not ctx.occ.copper_conflicts(shape)

            def runs_through(a, b):   # a leg that runs through copper of another net: a short, whatever the clearance
                return any(not (bridge and o.wire and o.kind == "copper")
                           for o in ctx.occ.copper_through(_shape_of(Track(name, layer, w, a, b))))

            if arc:
                pts = octilinear(located, pads, clear, None, lanes, self.settings.copper_straight_tolerance,
                                 runs_through) if bend is Bend.ARC else located
                ops, misfits = arc_tracks(name, layer, w, pts, arc_r)
                if misfits:
                    for m in misfits:
                        ctx.note(C.COPPER_NOT_DRAWN, {"variant": "arc", "key": copper_id(intent), "radius_mm": arc_r,
                                                      "layer": layer.name, "net": name, "misfit": m.to_json(),
                                                      "free_hint": bend is Bend.ARC})
                    return []
                diagonals = []
            else:
                pts = octilinear(located, pads, clear, bend, lanes, self.settings.copper_straight_tolerance, runs_through)
                cut_pts, diagonals = chamfer_cuts(pts, chamfer)
                ops = polyline_tracks(name, layer, w, cut_pts)
            for p in corners:
                # the lane runs past every item named, but only copper on this track's layer can be passed too close
                on = _past_reach(self, ctx, name, w, p, intent.key, intent.index, layer)
                if on is None:
                    continue
                box, off, names = on
                c = _box_corner(box, p.edge)
                near = min((_point_seg(c, Location(*a), Location(*b))[0] for t in ops for a, b in t.chords()),
                           default=math.inf)
                if near < off - 1e-6:
                    ctx.notes.append(Finding(C.COPPER_CORNER, {
                        "key": copper_id(intent), "net": name, "edge": p.edge.value, "names": list(names),
                        "near_mm": near - w / 2.0, "need_mm": off - w / 2.0, "chamfer_mm": chamfer}, "critical"))
            if chamfer > 0 and not arc:
                # the 45 a corner's own cut emits, not a straight leg that merely
                # happens to run between two separate corners' cuts
                import dataclasses
                diag = {(round(a.x, 6), round(a.y, 6), round(b.x, 6), round(b.y, 6)) for a, b in diagonals}
                ops = [dataclasses.replace(t, chamfer_cut=(
                    round(t.start.x, 6), round(t.start.y, 6), round(t.end.x, 6), round(t.end.y, 6)) in diag)
                      for t in ops]
            def op_clear(t):          # a drawn piece, a straight or an arc, that touches no pad of another net
                return not ctx.occ.copper_conflicts(_shape_of(t))
            if len(points) > 2 and begins is None and any(not op_clear(t) for t in ops):
                # the script's waypoints steer this track into a pad: would pad to pad clear?
                ends_only = octilinear([located[0], located[-1]], [pads[0], pads[-1]], clear, None if arc else bend,
                                       tolerance=self.settings.copper_straight_tolerance)
                if arc:
                    direct, _ = arc_tracks(name, layer, w, ends_only, arc_r)
                else:
                    direct = polyline_tracks(name, layer, w, chamfered(ends_only, chamfer))
                others = [t for t in ctx.planned_tracks + ctx.batch_tracks
                          if t.net != name and t.layer is layer]     # tracks not in the occupancy yet count too

                def clear_of_tracks(t):
                    return all(poly_distance(t.polygon, o.polygon) >= self._clearance(name, o.net) - 1e-9
                               for o in others)
                if all(op_clear(t) and clear_of_tracks(t) for t in direct) and (direct or not arc):
                    ctx.notes.append(Finding(C.COPPER_NOTE, {
                        "variant": "waypoint", "key": copper_id(intent), "net": name, "waypoints": len(points) - 2},
                        "notice"))
            if begins is not None:
                self._release_lane(ctx.occ, begins)     # what is judged from here is what this track draws
            hits = self._through_hits(ctx, ops, bridge)
            if hits is not None:
                ctx.note(C.COPPER_NOT_DRAWN, {"variant": "through", "key": copper_id(intent), "layer": layer.name,
                                              "net": name, "waypoints": max(0, len(points) - 2),
                                              **self._track_through_facts(ctx, hits, intent.index)})
                return []
            return ops
        intent = self._copper_intent("track %s" % name, net, priority, plan, refs, why, bridge, only=self._only(only, "track"))
        self._copper_uses[intent.index] = tuple(p.index for p in points if isinstance(p, CopperIntent))
        intent.declared = {"layer": layer.name, "chamfer": chamfer, "radius": arc_r, "arc": bool(arc),
                           "waypoints": max(0, len(points) - 2) if begins is None else 0}
        if begins is None and len(points) >= 2 and all(isinstance(p, (PadRef, CellPadRef)) and getattr(p, "edge", None) is None for p in points):
            self._pad_tracks.add(intent.index)
        return intent

    def _check_past(self, p: Past, what: str, lane: bool = False):
        """A Past's vias and tracks are this board's; `lane=` only where
        `lane` says it means something (Beside's align)."""
        for it in p.items + (p.across,):
            if isinstance(it, CopperIntent) and not any(it is c for c in self._copper):
                raise TypeError("%s: %s is copper of another board" % (what, it.key))
        for it in p.items:
            if getattr(it, "edge", None) is not None:
                raise TypeError("%s: Past's items are the copper it is held off; a PadRef's edge= is a track "
                                "point on that edge, so name the pad without it" % what)
        if p.lane is not None and not lane:
            raise TypeError("%s: Past's lane= is for Beside's align, where it leaves room for a track "
                            "between a part's pad and the items; a Past here keeps its own clearance" % what)

    def pair(self, net_p, net_n, path, *, layer: CopperLayer, width: float | None = None, gap: float | None = None,
             chamfer: float | None = None, via_step: float | None = None, priority: Priority = Priority.DEFAULT,
             bridge: bool = False, only=None, why: str = ""):
        """Two nets drawn together at `gap` along one centreline. `path`
        starts and ends with a (P pad, N pad) tuple; the points between, two
        or more, are the centreline. Width and gap default to the P net's class. Corners
        are chamfered at 45, each track leaves its pad at 45, and a lead that
        would touch the partner goes over the other face from a via."""
        chamfer = self.settings.copper_pair_chamfer if chamfer is None else chamfer
        via_step = self.settings.copper_pair_via_offset if via_step is None else via_step
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
                    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "pair_close", "p": p_name, "n": n_name})
                    return []
            return pair_ops(p_name, n_name, layer, w, g, start, centre, end, self.via_drill, self.via_size,
                            via_step, chamfer, self._clearance(p_name, n_name), sfaces, efaces)
        return self._copper_intent("pair %s/%s" % (p_name, n_name), net_p, priority, plan, refs, why, bridge, only=self._only(only, "pair"))

    def vias(self, net, pad=None, *, along=None, count: int | None = None, pitch: float | None = None,
             size: float | None = None, drill: float | None = None,
             inset: float = 0.0, layers=None, priority: Priority = Priority.DEFAULT, only=None, why: str = ""):
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

        Either way, resolved when the pad's part is placed. `layers=` spans
        some layers only, as on `via()`; a via whose span misses the layer
        of the pad it joins is not drawn."""
        if (pad is None) == (along is None):
            raise TypeError("%s: vias needs exactly one of a pad (a grid over it) or along= (a row along "
                            "its axis)" % net)
        name = self.geometry.require_net(net)
        span = self._via_span(name, layers)
        nc = self.geometry.netclasses.get(name)
        s = float(size) if size is not None else (nc.via_diameter if nc else self.via_size)
        d = float(drill) if drill is not None else self._span_drill(span, nc.via_drill if nc else self.via_drill)
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
                if span and layer not in span:
                    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "vias_span", "net": name, "span": _span_of(span),
                                                  "owner": owner, "number": number, "layer": layer.value})
                    return []
                width = queries.tail_width(nc.track_width if nc else 0.2, [sh.poly for sh in shapes])
                start = Location(round(c.x, 6), round(c.y, 6))
                vias = []
                for i in range(n):
                    r = half + s / 2.0 + i * step
                    at = Location(round(c.x + ux * r, 6), round(c.y + uy * r, 6))
                    why_not = self._via_site_why(ctx, at, name, s, d, obstacles, span)
                    if why_not is None:
                        why_not = self._tail_why(ctx, Track(name, layer, width, start, at))
                    if why_not is not None:
                        ctx.note(C.COPPER_NOT_DRAWN, {"variant": "vias_row", "net": name, "placed": len(vias), "of": n,
                                                      "owner": owner, "number": number, "why": why_not.to_json()})
                        break
                    via = Via(name, at, d, s, span)
                    vias.append(via)
                    ctx.planned_vias.append(via)
                if not vias:
                    return []
                tail = Track(name, layer, width, start, vias[-1].at)
                ctx.planned_tails.append(tail)
                ctx.via_at[intent.index] = vias[-1].at      # a track may end on the row's farthest via
                return vias + [tail]
            # "via row": a track may end on it, as on one via()
            intent = self._copper_intent("via row %s" % name, net, priority, plan, _refs_in([along]), why, only=self._only(only, "vias"))
            return intent
        owner, number, _, _ = self._pad_ref(pad)
        k = len(self._pad_fields)
        self._pad_fields.append((pad, name, d, s, span, float(inset), None if pitch is None else float(pitch), step))
        prefix = "%s%d " % (FIELD_PREFIX, k)

        def plan(ctx):
            # the grid's vias are its part's, carried (_carry_pad_vias) and given way as the items were placed:
            # what is drawn is what the part carries now, each judged once more against the copper planned before it
            occ = ctx.occ
            said = self._field_notes.get(k)
            if said:
                ctx.note(C.COPPER_NOT_DRAWN, said)
                return []
            held = [sh for sh in ctx.fields.get(owner, ()) if sh.kind == "through" and sh.carried.startswith(prefix)]
            shortened = {a.via: a for a in occ.given_way.values() if a.kind == "shorten" and a.via.startswith(prefix)}
            holes, bare, forbidding = self._via_obstacles(ctx)
            mine = [sh.points[0] for sh in held]
            holes = [h for h in holes if not any(abs(h[0].x - x) < 1e-4 and abs(h[0].y - y) < 1e-4 for x, y in mine)]
            ops = []
            for sh in sorted(held, key=lambda sh: sh.carried):
                at = Location(round(sh.points[0][0], 6), round(sh.points[0][1], 6))
                layers = tuple(sorted(sh.layers, key=stackup_order)) if sh.carried in shortened else span
                if self._via_site_why(ctx, at, name, s, d, (holes, bare, forbidding), layers) is not None:
                    continue
                via = Via(name, at, d, s, layers)
                ops.append(via)
                ctx.planned_vias.append(via)    # the next via, and a later FreeSpot, keep the rule from it
            for a in sorted(occ.given_way.values(), key=lambda a: a.via):
                if a.via.startswith(prefix) and a.tail is not None and a.kind in ("leave", "share"):
                    ctx.planned_tails.append(a.tail)
                    ops.append(a.tail)
            return ops
        intent = self._copper_intent("vias %s" % name, net, priority, plan, _refs_in([pad]), why, only=self._only(only, "vias"))
        self._late_copper.add(intent.index)         # planned after the search: its part's grid gives way as items are placed
        return intent

    def _field_sites(self, occ, pad, span: tuple, s: float, step: float, inset: float) -> tuple:
        """(the sites of a grid of vias of size `s` in a pad, in the plan's frame; the facts of why there is none, or None).
        A pad filled with a square grid `step` apart in its part's own frame, centred on each land, keeping
        each site whose via, grown by `inset`, lies wholly in the land."""
        from .lock import _turn
        owner, number, _, _ = self._pad_ref(pad)
        rot = occ.items[owner].reference.rotation
        shapes = [sh for sh in _pad_shapes(self, occ, pad) if sh.kind == "pad"]       # a through land has its hole
        lands = [sh.poly for sh in shapes if not span or sh.layers & set(span)]
        if shapes and not lands:
            return [], {"variant": "field_span", "span": _span_of(span), "owner": owner, "number": number,
                        "layers": sorted({l.value for sh in shapes for l in sh.layers})}
        out = []
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
                    if poly_within(circle_polygon(at, s / 2.0 + inset - 1e-5, 24), land):
                        out.append(at)
        return out, None

    def via(self, net, at, *, drill: float | None = None, size: float | None = None, layers=None,
            priority: Priority = Priority.DEFAULT, only=None, why: str = ""):
        """A via of `net`. `at` is a position, a `FreeSpot` near a pad (the
        nearest point a via can stand and be reached, found when the pad is
        placed), or a `Past(items, edge)` (the via's radius plus its
        clearance off those pads', vias' or tracks' `edge` side). A FreeSpot
        with nowhere to go, or a Past naming a via that found no spot, is a
        finding and draws none. `layers=(CopperLayer.B, CopperLayer.IN4)`
        spans those layers and the ones between them only (see `_via_span`)."""
        name = self.geometry.require_net(net)
        span = self._via_span(name, layers)
        if isinstance(at, Past):
            self._check_past(at, "%s: a via's at=" % name)
        refs = _refs_in([at])
        d, s = drill or self._span_drill(span, self.via_drill), size or self.via_size
        carried = None
        if isinstance(at, (PadRef, CellPadRef)) and not (at.dx or at.dy):
            # at the pad, or off it in the part's frame: it turns with the part, so the part carries it
            carried = pad_via_id(len(self._pad_vias))
            self._pad_vias.append((at, name, d, s, span))

        def plan(ctx):
            ops = []
            if isinstance(at, FreeSpot):
                found = self._free_spot(ctx, at, name, d, s, span)
                if found is None:
                    return []
                where, layer, width, start, path = found
                if at.tail and not at.in_pad and where.distance(start) > 1e-9:
                    for tail in polyline_tracks(name, layer, width, path):
                        ctx.planned_tails.append(tail)
                        ops.append(tail)
            elif isinstance(at, Past):
                where = _past_point(self, ctx, name, s, at, intent.key, intent.index)     # s: the via's radius out
                if isinstance(where, Refusal):
                    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "past", "item": intent.key,
                                                  "names": _past_names(self, at), "why": where.to_json()})
                    return []
            else:
                where = ctx.locate(at)
                gave = ctx.occ.given_way.get(carried) if carried is not None else None
                if gave is not None and gave.kind == "move":
                    where = Location(*gave.to)
                elif gave is not None and gave.kind == "leave":     # out of its pad, joined to it by a new tail
                    where = Location(*gave.to)
                    ctx.planned_tails.append(gave.tail)
                    ops.append(gave.tail)
                elif gave is not None:              # shared or dropped as its part was placed (giveway.py)
                    ctx.via_at[intent.index] = Location(*gave.to) if gave.kind == "share" else where
                    if gave.tail is None:
                        return []
                    ctx.planned_tails.append(gave.tail)
                    return [gave.tail]
            via = Via(name, where, d, s, span)
            if not isinstance(at, FreeSpot) and carried is None:      # a spot the script gave, not one searched for
                met = self._through(ctx, [via])
                if met is not None:
                    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "via_stand", "net": name, "at": [where.x, where.y],
                                                  "met": met})
                    return []
            ctx.planned_vias.append(via)        # a later FreeSpot in this batch sees it
            ctx.via_at[intent.index] = where    # a track may end on it
            return [via] + ops
        intent = self._copper_intent("via %s" % name, net, priority, plan, refs, why, only=self._only(only, "via"))
        if isinstance(at, FreeSpot):
            # a searched spot keeps clear of the tracks declared before it, whenever those are planned: a track
            # that waits for a searched part is drawn after a decided via is, and has no way round it
            self._copper_after[intent.index] = tuple(
                c.index for c in self._copper if c.index < intent.index and c.key.startswith("track ") and c.net != name)
        return intent

    def stitch(self, net, region, *, pitch: float | None = None, size: float | None = None,
               drill: float | None = None, edge: bool = False, outside: bool = False,
               hole_to_edge: float | None = None, sides=None, layers=None,
               priority: Priority = Priority.DEFAULT, only=None, why: str = ""):
        """Stitching vias of `net` over `region` - a `Cell`, the
        `CopperIntent` `board.pour()` returns, or a keepout's name - `pitch`
        apart (by default the via-to-via rule: the larger of the via's own
        size and a drilled hole plus the hole-to-hole rule), each one wholly
        inside the region and clear of every other net's copper, hole,
        keepout and the board edge. A grid over the whole region by default;
        `edge=True` instead rows them along the region's own outline, a
        via's clearance in from it. Resolved once the region itself is:
        after the cell is placed, the pour is drawn, or the keepout is
        settled. `layers=` spans some layers only, as on `via()`.

        `edge=True, outside=True` rows the vias outside the region instead:
        each via's hole edge `hole_to_edge` off the region's edge, along its
        outward normal (by default the via's copper just touches the edge),
        `pitch` the most they stand apart along an edge (a side `L` long gets
        `ceil(L / pitch) + 1`, spread evenly end to end). `sides=` keeps the
        edges whose outward normal faces those `Edge`s as the region is turned
        (a keepout reads them in its own frame), each edge for the side its
        normal is nearest, within 45 degrees; by default every edge. A via
        stands at the outside of a corner between two kept edges, shared by
        both rows; a row ends `hole_to_edge` plus the via's radius in from a
        side not kept it meets. With `sides=`, a finding names the board side
        each row landed on. A via that cannot stand is left out and noted; a
        row left with a gap over `pitch` is a finding."""
        name = self.geometry.require_net(net)
        if outside and not edge:
            raise ValueError("%s: stitch's outside=True rows the vias along the region's edge; give edge=True too"
                             % name)
        if not outside and (hole_to_edge is not None or sides is not None):
            raise ValueError("%s: stitch's hole_to_edge= and sides= belong to outside=True" % name)
        span = self._via_span(name, layers)
        nc = self.geometry.netclasses.get(name)
        s = float(size) if size is not None else (nc.via_diameter if nc else self.via_size)
        d = float(drill) if drill is not None else self._span_drill(span, nc.via_drill if nc else self.via_drill)
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
            if not outside and "vias" in k.excludes and name not in {self.geometry.require_net(a) for a in k.allow if isinstance(a, Net)}:
                raise ValueError("%s: keepout %r excludes vias (excludes=%s), so no via could stand anywhere "
                                 "in it; add %r to its allow=, or narrow its excludes=" % (
                                     name, region, list(k.excludes), name))
        else:
            raise TypeError("%s: stitch's region is a Cell, a keepout's name, or the CopperIntent "
                            "board.pour() returns, not %r" % (name, region))

        wanted = None
        if sides is not None:
            wanted = [Edge(x) for x in ((sides,) if isinstance(sides, (str, Edge)) else sides)]
            if not wanted:
                raise ValueError("%s: stitch's sides= names at least one side" % name)
        # by default the via's copper touches the edge from outside: the reach of the polygon a via is judged
        # as (`via_ring`'s corners stand a little past its circle), 1e-6 mm over so the touch is not an overlap
        reach = max(math.hypot(x, y) for x, y in via_ring(Location(0.0, 0.0), s))
        gap = reach - d / 2.0 + 1e-6 if hole_to_edge is None else float(hole_to_edge)
        if gap < 0:
            raise ValueError("%s: stitch's hole_to_edge= is %.2f mm; a hole edge stands off the region by 0 or more"
                             % (name, gap))
        off = gap + d / 2.0

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
                ctx.note(C.COPPER_STITCH, {"variant": "no_region", "net": name})
                return []
            obstacles = self._via_obstacles(ctx)
            if outside:
                turn = ctx.plan.keepouts[region].rotation if isinstance(region, str) and ctx.plan else 0.0
                return self._stitch_outside(ctx, name, poly, turn, off, step, wanted, s, d, obstacles, span, pour_intent)
            vias = []
            for x, y in candidates(poly):
                at = Location(round(x, 6), round(y, 6))
                if (poly_within(circle_polygon(at, s / 2.0, 24), poly)
                        and self._via_site_why(ctx, at, name, s, d, obstacles, span) is None):
                    via = Via(name, at, d, s, span)
                    vias.append(via)
                    ctx.planned_vias.append(via)
            if not vias:
                ctx.note(C.COPPER_STITCH, {"variant": "none", "net": name, "pitch_mm": step})
            return vias
        intent = self._copper_intent("stitch %s" % name, net, priority, plan, refs, why, extra_owners=extra_owners, only=self._only(only, "stitch"))
        if pour_intent is not None:
            self._copper_after[intent.index] = (pour_intent.index,)
            self._copper_uses[intent.index] = (pour_intent.index,)     # its only= must lie inside the pour's
        return intent

    def _stitch_outside(self, ctx, name: str, poly, turn: float, off: float, step: float, wanted, size: float,
                        drill: float, obstacles, span: tuple, pour_intent) -> list:
        """`stitch(edge=True, outside=True)`: each kept edge's row, every via
        judged as a stitching via is; the ones that cannot stand are named in
        one note, and a row left with a gap over `step` is another."""
        rows = _stitch_outside_rows(poly, turn, off, step, wanted)
        vias, standing, left_out = [], [], []
        seen: dict = {}
        for side, _board_side, points in rows:
            kept = []
            for t, (x, y) in points:
                at = Location(round(x, 6), round(y, 6))
                if (at.x, at.y) not in seen:        # a corner via is one via for both rows
                    seen[(at.x, at.y)] = self._via_site_why(ctx, at, name, size, drill, obstacles, span)
                    if seen[(at.x, at.y)] is None:
                        via = Via(name, at, drill, size, span)
                        vias.append(via)
                        ctx.planned_vias.append(via)
                    else:
                        left_out.append([at.x, at.y, seen[(at.x, at.y)].to_json()])
                if seen[(at.x, at.y)] is None:
                    kept.append(t)
            standing.append((side, kept, points[-1][0]))
        if left_out:
            ctx.notes.append(Finding(C.COPPER_STITCH, {"variant": "left_out", "net": name, "left_out": left_out}, "notice"))
        for side, kept, length in standing:
            reach = [kept[i + 1] - kept[i] for i in range(len(kept) - 1)] if kept else [length]
            if max(reach, default=0.0) > step + 1e-6:
                ctx.note(C.COPPER_STITCH, {"variant": "gap", "net": name, "side": _SIDE_WORD[side],
                                           "gap_mm": max(reach), "pitch_mm": step})
        if wanted is not None and rows:
            ctx.notes.append(Finding(C.COPPER_STITCH, {
                "variant": "rows", "net": name,
                "rows": [[_SIDE_WORD[side], _SIDE_WORD[board_side]] for side, board_side, _ in rows]}, "notice"))
        if not rows:
            ctx.note(C.COPPER_STITCH, {"variant": "no_edge", "net": name})
        elif not vias:
            ctx.note(C.COPPER_STITCH, {"variant": "none_outside", "net": name, "pitch_mm": step})
        return vias

    def _via_span(self, name: str, layers) -> tuple:
        """The board's layers a via declared with `layers=` spans, in stackup
        order: its two ends and every layer between them. None, or a span of
        every layer the board has, is the through via: (). A layer the board
        does not have is refused, and so is a span of one layer."""
        if layers is None:
            return ()
        named = [CopperLayer.of(l) for l in ((layers,) if isinstance(layers, str) else layers)]
        board = sorted(self.geometry.layers, key=stackup_order)
        lacking = [l.value for l in named if l not in board]
        if lacking:
            raise ValueError("%s: a via's layers= names %s, which this board does not have; it has %s"
                             % (name, ", ".join(lacking), ", ".join(l.value for l in board)))
        if len(set(named)) < 2:
            raise ValueError("%s: a via joins two layers or more; layers= names its two ends, as "
                             "(CopperLayer.B, CopperLayer.IN4)" % name)
        lo, hi = min(map(stackup_order, named)), max(map(stackup_order, named))
        span = tuple(l for l in board if lo <= stackup_order(l) <= hi)
        if len(span) == len(board):
            return ()
        self._allow_via_type(name, span)
        return span

    def _plane_layers(self) -> dict:
        """{layer: {net, ...}} of every plane this board carries on that
        layer: each board.plane() call, from the moment it is declared (no
        copper drawn yet), plus any zone the generated board already
        carries that belongs to no cell (a board-wide plane a fragment does
        not own). A stamped cell's own local zone is not a board-wide
        plane and is left out, the same as `_flip_notes` always judged it."""
        planes: dict = {}
        for net, layers in self._planes_declared:
            for l in layers:
                planes.setdefault(l, set()).add(net)
        for c in self.geometry.copper:
            if c.kind == "zone" and not c.owner:
                for l in c.layers:
                    planes.setdefault(l, set()).add(c.net)
        return planes

    def _flip_notes(self, occ) -> dict:
        """{cell: [note]} (step_text records) for each cell with a via that reaches a face and whose
        inner end, once the cell is flipped, may no longer join its net. A
        flip keeps a cell's inner copper on its layer but mirrors such a via
        (F-In1 becomes B-In4), so its inner end moves. It still joins when
        both layers are of one KiCad layer type and hold the via net's own
        plane. Noted on the cell's step when it lands on the back."""
        types = self.geometry.layer_types
        planes = self._plane_layers()

        def standing(layer, net):
            nets = planes.get(layer, set())
            return "own_plane" if net in nets else ("other_plane" if nets else "no_plane")

        def inner_end(span):
            inner = sorted((l for l in span if l.face is None), key=stackup_order)
            return inner[-1] if CopperLayer.F in span else inner[0]

        def ends(span):
            ordered = sorted(span, key=stackup_order)
            return [ordered[0].value, ordered[-1].value]

        stack = frozenset(self.geometry.layers)
        out: dict = {}
        for c in self.geometry.copper:
            if c.kind != "via" or c.owner not in self.geometry.cells or not c.layers or stack <= c.layers:
                continue
            if not c.layers & {CopperLayer.F, CopperLayer.B} or not any(l.face is None for l in c.layers):
                continue
            flipped = occ._flip_span(c.layers)
            s_layer, d_layer = inner_end(c.layers), inner_end(flipped)
            ts, td = types.get(s_layer), types.get(d_layer)
            if ts and td and ts != td:
                why = {"form": "types", "from": ts, "to": td}
            elif standing(s_layer, c.net) != "own_plane" or standing(d_layer, c.net) != "own_plane":
                why = {"form": "standing", "from": standing(s_layer, c.net), "to": standing(d_layer, c.net)}
            else:
                continue
            said = step_text.record("flip_via", net=c.net, span=ends(c.layers), flipped=ends(flipped), from_layer=s_layer.value,
                                  to_layer=d_layer.value, why=why)
            notes = out.setdefault(c.owner, [])
            if said not in notes:
                notes.append(said)
        return out

    def _check_stamped_via_types(self) -> None:
        """A via a stamped cell brings (or one already on the board) that
        spans only some of the board's layers is a micro, blind or buried
        via: refused, naming its cell, unless the fab profile allows its type."""
        board = tuple(sorted(self.geometry.layers, key=stackup_order))
        for c in self.geometry.copper:
            if c.kind != "via" or not c.layers or set(board) <= set(c.layers):
                continue
            span = tuple(l for l in board if l in c.layers)
            if len(span) < 2:
                continue
            where = "cell %s's" % c.owner if c.owner else "the board's"
            self._allow_via_type("%s %s via at (%.2f, %.2f)" % (where, c.net or "-", c.box.center.x,
                                                                   c.box.center.y), span)

    def _allow_via_type(self, name: str, span: tuple) -> None:
        """Refuse a via type the fab profile does not allow outright: a
        micro, blind or buried via costs more, and a preferred-off type
        ("if-needed") is never drawn by a script even where it would clear."""
        kind = _via_kind(span)
        tier = self.fab_via_tiers.get(kind, "no")
        if tier == "yes":
            return
        why = "is not allowed by the fab profile" if tier == "no" else \
              "is preferred off by the fab profile (\"if-needed\")"
        raise ValueError(
            "%s: a %s via (%s) %s%s; they cost more, so a board keeps to through vias unless "
            "fab-profile.json says \"via\": {\"%s\": \"yes\"} for a fab that makes them" % (
                name, kind, _span_text(span), why, " (%s)" % self.fab_source if self.fab_source else "", kind))

    def _span_drill(self, span: tuple, drill: float) -> float:
        """A via's drill when the script gives none: `copper.microvia_drill`
        for a micro via (a span of one layer from an outer face), else
        `drill`."""
        return self.settings.copper_microvia_drill if _is_micro(span) else drill

    def _via_obstacles(self, ctx):
        """What a via's site is judged against beyond the occupancy's copper:
        every drilled hole where it now stands - each plated hole of a placed
        part at its own land, so the holes of one pin stay apart, and every
        via on the board, a stamped cell's and those planned before - every
        unplated hole, and the keepouts and rule areas that forbid vias."""
        occ = ctx.occ
        def hole(sh):                    # the circle the polygon was drawn from: its box is short of it when turned
            c = sh.box.center
            return c, 2 * max(math.dist((c.x, c.y), p) for p in sh.poly), sh.layers
        holes = [hole(sh) + (sh.net,) for o, g in occ.items.items() if o not in occ.pending for sh in g.shapes
                 if sh.kind == "hole"]
        holes += [hole(sh) + (sh.net,) for sh in occ.copper if sh.kind == "hole" and sh.owner not in occ.pending]
        # unplated holes (a connector's locating pegs): no copper, so the via's copper keeps the board's hole
        # clearance from the hole's edge as well as the hole-to-hole rule
        bare = [(sh.box.center, sh.box.width) for o, g in occ.items.items() if o not in occ.pending
                for sh in g.shapes if sh.kind == "npth"]
        # (polygon, layers, the nets it lets through): a keepout's allow= lets its nets' vias stand in it
        forbidding = [(k.poly, k.layers, frozenset(k.allow)) for k in (ctx.plan.keepouts.values() if ctx.plan else ())
                      if "vias" in k.excludes]
        forbidding += [(poly, ra.layers, ra.allow) for pairs in occ._cell_rule_areas.values() for ra, poly in pairs
                       if "vias" in ra.excludes]
        forbidding += [(ra.polygon, ra.layers, ra.allow) for ra in self.geometry.rule_areas
                       if ra.cell is None and "vias" in ra.excludes]
        return holes, bare, forbidding

    def _via_site_why(self, ctx, c: Location, net: str, size: float, drill: float, obstacles,
                      span: tuple = ()) -> Refusal | None:
        """Why a via of `net` may not stand at `c` (a Refusal), or None. A via goes
        through every layer, or the layers of its `span`: the board's edge,
        every other net's copper there (placed, and planned so far in this
        batch: tracks, tails and vias), the hole-to-hole rule from every hole
        on a layer it shares, the hole clearance from an unplated one, and
        keepouts that forbid vias there."""
        occ = ctx.occ
        holes, bare, forbidding = obstacles
        own = set(span)

        def apart(layers):              # a span that shares no layer with these: nothing between them
            return bool(own) and bool(layers) and not (own & set(layers))
        ring = via_ring(c, size)
        box = Box.of_points(ring)
        if occ.board_shape is not None:
            if occ.board_shape.why_not(box, self.keep_in):
                return Refusal(Code.OFF_BOARD, variant="shape", keep_in_mm=self.keep_in)
        elif occ.board_box is not None and not occ.board_box.inflate(-self.keep_in).contains(box):
            return Refusal(Code.OFF_BOARD, variant="rect", keep_in_mm=self.keep_in)
        hits = occ.copper_conflicts(Shape("via", "copper", frozenset(), frozenset(span or self.geometry.layers),
                                          net, ring, box, wire=True))
        if hits:
            return Refusal(Code.SITE_COPPER, why=hits[0])
        # its drill keeps the hole clearance from other nets' copper, which a net tie's bar does not lift
        hits = occ.hole_conflicts(hole_shape("via", c, drill, net, layers=frozenset(span)))
        if hits:
            return Refusal(Code.SITE_COPPER, why=hits[0])
        for v in ctx.planned_vias:
            if apart(v.layers):
                continue
            gap = c.distance(v.at) - (drill + v.drill) / 2.0
            if gap < self.geometry.hole_to_hole - 1e-9:
                return Refusal(Code.SITE_HOLE_VIA, net=v.net, gap_mm=gap, need_mm=self.geometry.hole_to_hole)
            if v.net != net:
                clr = self._clearance(net, v.net)
                if c.distance(v.at) - (size + v.size) / 2.0 < clr - 1e-9:
                    return Refusal(Code.SITE_COPPER_VIA, net=v.net, gap_mm=c.distance(v.at) - (size + v.size) / 2.0,
                                   need_mm=clr)
                dist = c.distance(v.at)         # a drill against the other's ring, each way
                for gap, whose in ((dist - (drill + v.size) / 2.0, "via"), (dist - (size + v.drill) / 2.0, "own")):
                    if gap < self.geometry.hole_clearance - 1e-9:
                        return Refusal(Code.SITE_COPPER_HOLE, of=whose, net=v.net, gap_mm=gap,
                                       need_mm=self.geometry.hole_clearance)
        for t in ctx.planned_tails + [t for t in ctx.batch_tracks if t not in ctx.planned_tails]:
            if own and t.layer not in own:
                continue
            if t.net != net and poly_distance(ring, t.polygon) < self._clearance(net, t.net) - 1e-9:
                return Refusal(Code.SITE_COPPER_TRACK, net=t.net, gap_mm=poly_distance(ring, t.polygon),
                               need_mm=self._clearance(net, t.net))
            if t.net != net and circle_poly_gap(c, drill / 2.0, t.polygon) < self.geometry.hole_clearance - 1e-9:
                return Refusal(Code.SITE_COPPER_OWN_HOLE, gap_mm=circle_poly_gap(c, drill / 2.0, t.polygon),
                               need_mm=self.geometry.hole_clearance)
        # a pour planned before it in this batch: a fitted pour is drawn as planned, so it is copper now,
        # held as the occupancy will hold it (its outline and half its stroke)
        for op in getattr(ctx, "batch_ops", ()):
            if not isinstance(op, Pour) or op.net == net or (own and op.layer not in own):
                continue
            shape = _shape_of(op)
            if shape is None or not shape.box.overlaps(
                    box, gap=max(self._clearance(net, op.net), self.geometry.hole_clearance)):
                continue
            gap = poly_distance(ring, shape.poly)
            if gap < self._clearance(net, op.net) - 1e-9:
                return Refusal(Code.SITE_COPPER_POUR, net=op.net, gap_mm=gap, need_mm=self._clearance(net, op.net))
            hole_gap = circle_poly_gap(c, drill / 2.0, shape.poly)
            if hole_gap < self.geometry.hole_clearance - 1e-9:
                return Refusal(Code.SITE_COPPER_OWN_HOLE, gap_mm=hole_gap, need_mm=self.geometry.hole_clearance)
        for at, dia, layers, hole_net in holes:
            if apart(layers):
                continue
            gap = c.distance(at) - (drill + dia) / 2.0
            if gap < self.geometry.hole_to_hole - 1e-9:
                return Refusal(Code.SITE_PAD_HOLE, what="hole", gap_mm=gap, need_mm=self.geometry.hole_to_hole)
            edge = c.distance(at) - (size + dia) / 2.0          # its ring against their drill
            if hole_net != net and edge < self.geometry.hole_clearance - 1e-9:
                return Refusal(Code.SITE_PAD_HOLE, what="copper", gap_mm=edge, need_mm=self.geometry.hole_clearance)
        for at, dia in bare:
            gap = c.distance(at) - (drill + dia) / 2.0
            if gap < self.geometry.hole_to_hole - 1e-9:
                return Refusal(Code.SITE_UNPLATED, what="hole", gap_mm=gap, need_mm=self.geometry.hole_to_hole)
            edge = c.distance(at) - (size + dia) / 2.0
            if edge < self.geometry.hole_clearance - 1e-9:
                return Refusal(Code.SITE_UNPLATED, what="copper", gap_mm=edge, need_mm=self.geometry.hole_clearance)
        for poly, layers, allowed in forbidding:
            if net not in allowed and polys_overlap(ring, poly) and not apart(layers):
                return Refusal(Code.SITE_KEEPOUT)
        return None

    def _through(self, ctx, ops, bridge: bool = False) -> dict | None:
        """What `ops` (a track's or a via's copper) would be drawn through (copper as occupancy.name_copper names it), or None: copper of another net that
        they overlap, placed, or planned before them in this or an earlier batch. A track that may bridge crosses
        a track (the bridging passes it under); two tracks of one batch that cross are the bridging's to settle."""
        hits = self._through_hits(ctx, ops, bridge)
        return hits[1][0] if hits else None

    def _through_hits(self, ctx, ops, bridge: bool = False):
        """(the first op that meets copper, [the copper it meets, as name_copper names it]) or None. The copper is in the
        order along the op from its start (where each piece is first reached, ties by name), never the occupancy's order; each
        carries `at_mm`, how far along the op it is first reached."""
        occ = ctx.occ
        for op in ops:
            if not isinstance(op, (Track, Via)):
                continue
            shape = _shape_of(op)
            hit = []
            for o in occ.copper_through(shape):
                if bridge and isinstance(op, Track) and o.wire and o.kind == "copper":
                    continue
                hit.append(o)
            for earlier in ctx.batch_ops:
                if isinstance(earlier, Track) and isinstance(op, Track):
                    continue
                other = _shape_of(earlier)
                if other is not None and other.net and shape.net and other.net != shape.net and shape.layers & other.layers \
                        and shape.box.overlaps(other.box) and occ._conflict(shape, other, 1e-4, exact=True, say=False):
                    hit.append(other)
            if not hit:
                continue
            if isinstance(op, Track):
                ux, uy = op.end.x - op.start.x, op.end.y - op.start.y
                n = math.hypot(ux, uy) or 1.0
                ux, uy = ux / n, uy / n
                along = lambda o: min((x - op.start.x) * ux + (y - op.start.y) * uy for x, y in o.poly)
            else:
                along = lambda o: 0.0
            named = []
            for o in hit:
                c = occ.name_copper(o)
                c["at_mm"] = round(max(0.0, along(o)), 4)
                named.append((c["at_mm"], c["form"], str(c.get("who", "")), str(c.get("label", "")), str(c.get("net", "")), c))
            named.sort(key=lambda t: t[:5])
            return op, [t[5] for t in named]
        return None

    def _track_through_facts(self, ctx, hits, index: int) -> dict:
        """What a track not drawn for the copper it would run through says: every piece along its first leg, the leg,
        and for each pad whether its part was placed when the room planning first tried this track (None where that was
        not tried, and for copper that is not a part's pad)."""
        op, blockers = hits
        early = None if ctx.dry else self._room_refused.get(index)
        out = []
        for c in blockers:
            c = dict(c)
            c["placed_when_plannable"] = (c["who"][0] in early) if early is not None and c["form"] == "pad" else None
            out.append(c)
        return {"met": out[0], "blockers": out,
                "leg": {"start": [round(op.start.x, 6), round(op.start.y, 6)], "end": [round(op.end.x, 6), round(op.end.y, 6)]}}

    def _tail_why(self, ctx, tail) -> Refusal | None:
        """Why `tail` cannot be drawn - within clearance of another net's via
        or track planned before it, or of copper already on the board - or
        None."""
        net, layer = tail.net, tail.layer
        for v in ctx.planned_vias:
            if v.layers and layer not in v.layers:
                continue
            if v.net != net and poly_distance(tail.polygon, v.polygon) < self._clearance(net, v.net) - 1e-9:
                return Refusal(Code.TAIL_VIA, net=v.net, gap_mm=poly_distance(tail.polygon, v.polygon),
                               need_mm=self._clearance(net, v.net))
        for t in ctx.planned_tails + [t for t in ctx.batch_tracks if t not in ctx.planned_tails]:
            if (t.net != net and t.layer is layer
                    and poly_distance(tail.polygon, t.polygon) < self._clearance(net, t.net) - 1e-9):
                return Refusal(Code.TAIL_CROSSES, net=t.net)
        hits = ctx.occ.copper_conflicts(Shape("via", "copper", frozenset(), frozenset([layer]),
                                              net, tail.polygon, Box.of_points(tail.polygon), wire=True))
        return Refusal(Code.TAIL_COPPER, why=hits[0]) if hits else None

    def _free_spot(self, ctx, spot, net: str, drill: float, size: float, span: tuple = ()):
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
            ctx.note(C.COPPER_NOT_DRAWN, {"variant": "tail_join", "net": net, "layer": layer.value, "owner": owner,
                                          "number": number})
            return None
        if span and layer not in span:
            ctx.note(C.COPPER_NOT_DRAWN, {"variant": "tail_span", "net": net, "span": _span_of(span), "layer": layer.value})
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
                if v.layers and layer not in v.layers:
                    continue
                if v.net != net and poly_distance(tail, v.polygon) < self._clearance(net, v.net) - 1e-9:
                    return Refusal(Code.TAIL_VIA, net=v.net, gap_mm=poly_distance(tail, v.polygon),
                                   need_mm=self._clearance(net, v.net))
            for t in ctx.planned_tails + [t for t in ctx.batch_tracks if t not in ctx.planned_tails]:
                if (t.net != net and t.layer is layer
                        and poly_distance(tail, t.polygon) < self._clearance(net, t.net) - 1e-9):
                    return Refusal(Code.TAIL_CROSSES, net=t.net)
            tail_hits = occ.copper_conflicts(Shape("via", "copper", frozenset(), frozenset([layer]),
                                                   net, tail, Box.of_points(tail), wire=True))
            return Refusal(Code.TAIL_COPPER, why=tail_hits[0]) if tail_hits else None

        def tail_path(c):
            # drawn as board.track() draws a leg: at 0, 45 or 90 degrees, the 45 at the pad. A
            # spot whose tail is not clear that way is passed over for the next spot the search
            # tries, rather than routed round: the search is already dense
            return octilinear([start, c], [True, False])

        def judge(c):
            ring = via_ring(c, size)
            if not spot.in_pad and any(polys_overlap(ring, sh.poly) for sh in own):
                return Refusal(Code.SOURCE_PAD), ()
            why = self._via_site_why(ctx, c, net, size, drill, obstacles, span)
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
            ctx.note(C.COPPER_NOT_DRAWN, {"variant": "via_nowhere", "net": net, "radius_mm": spot.radius, "owner": owner,
                                          "number": number, "tried": tried, "counts": [[k, n] for k, n in tally.most_common()]})
            return None
        return found.at, layer, width, start, tail_path(found.at)

    def pour(self, net, points, *, layer: CopperLayer, stroke: float | None = None, swallow_pads: bool = False,
             width: float | None = None, cover: Cover | None = None, priority: Priority = Priority.DEFAULT,
             reach: float | Reach | None = None, grow: float | None = None, within=None, only=None, why: str = ""):
        """A filled copper polygon on one layer, written as a graphic polygon
        (never a zone: nothing refills it, and nothing is cut from it once it
        is planned). Another net's copper inside it is a copper finding.

        `swallow_pads=True` over pads (`PadRef`, `CellPadRef`; two or more, without `width=`)
        fits the pour round the copper planned before it: the shortest closed
        outline that holds all their copper and keeps each other net's
        copper, every hole and the board edge its clearance (`board.rule`
        clearances included) plus half the pour's stroke, every edge
        straight. Where the outline wraps round a pad's corner, a track's end
        or a via it does so by edges tangent to the clearance outline, each
        corner no more than `geometry.arc_sag` past it. Copper planned after a
        fitted pour keeps clear of it; a track declared across one is a copper
        finding. Where other copper stands where the outline cannot go round
        it (between two of its pads with no gap past it), or two pads cannot
        be joined, the pour is not drawn and a finding names the copper and
        the pads; where the outline narrows to less than the net's track width
        a finding names where, and it is drawn. A fitted pour is given by its
        pads and vias alone: `cover=` and plain points are refused. Its members
        may be vias as well as pads (what `via()` and `vias()` return, a lane's
        `.via`): a via counts on the pour's layer when its span includes it, as
        its copper ring there, and one that does not span it is a finding. The
        pour is planned after its vias.

        `reach=mm` on a fitted pour grows its copper into the room round it:
        the fitted outline grown by `reach` (arcs no more than
        `geometry.arc_sag` off), cut back by every other net's clearance
        outline planned before it (the pieces the fit keeps clear of), of
        which the part joined to the members is kept, written as graphic
        polygon(s). The copper reaches half the pour's stroke further, as any
        pour's does. Copper planned after it keeps clear as for any fitted
        pour. A pour that must carry current (check `current-path`) over a
        narrow hull takes the width it needs from `reach=`; it needs KiCad's
        pcbnew at plan time, whose polygon booleans it uses. Where the pour
        is drawn, the part of a pad that lies nearer another net's copper than the
        clearance (its footprint sets that gap) is held only as far as it is
        clear; the pad's own copper is as it is, and the pour's added copper
        keeps the full clearance.

        Without `swallow_pads`, `cover` says what corners that name pads cover
        (`Cover`): HULL the hull of their copper, BOX the box round it, CENTRES
        (the default) the polygon through the points. Exactly two pads
        (`[PadRef(a), PadRef(b)]`) with `width=`, or without `swallow_pads`, draws the neck between them instead - a
        rectangle along their centreline, as wide as the narrower pad measured
        across it, unless `width=` says otherwise.

        `grow=` and `within=` are refused: a pour is fitted, never a zone grown from its pads."""
        stroke = self.settings.copper_pour_outline_width if stroke is None else stroke
        layer = CopperLayer.of(layer)
        name = self.geometry.require_net(net)
        if reach is not None and reach is not Reach.CURRENT:
            if isinstance(reach, bool) or not isinstance(reach, (int, float)) or not reach > 0.0:
                raise ValueError("pour %s: reach= is a distance in mm greater than 0, or Reach.CURRENT, not %r"
                                 % (name, reach))
            reach = float(reach)
        if grow is not None or within is not None:
            raise ValueError("pour %s: grow= and within= are gone, a pour is fitted and never a zone grown from its "
                             "pads; join the pads with board.pour(net, pads, layer=, swallow_pads=True), or for "
                             "ground or a plane net use board.plane(net, layers, over=[...])" % name)
        if cover is not None and not isinstance(cover, Cover):
            raise TypeError("%s: a pour's cover is Cover.HULL, Cover.BOX or Cover.CENTRES, not %r" % (name, cover))
        points = list(points)
        vias = tuple(p for p in points if isinstance(p, CopperIntent))
        for v in vias:
            self._check_pour_via(name, v)
        if vias and not swallow_pads:
            raise TypeError("pour %s: a via may be a track's end point, one of a Past's items or a member of a fitted "
                            "pour (swallow_pads=True), and only that" % name)
        all_pads = all(isinstance(p, (PadRef, CellPadRef)) for p in points)
        neck = len(points) == 2 and all_pads
        if len(points) < 3 and not neck and not vias:
            raise ValueError("%s: a pour needs 3 or more points, or exactly two pads for the neck between "
                             "them (%d given)" % (name, len(points)))
        fitted = swallow_pads and not (neck and width is not None)
        if fitted and cover is not None:
            raise ValueError("pour %s: swallow_pads=True fits the pour round other nets' copper from its pads "
                             "alone, so it takes no cover=; drop cover=, or drop swallow_pads for a pour drawn "
                             "as declared" % name)
        if fitted and not all(isinstance(p, (PadRef, CellPadRef, CopperIntent)) for p in points):
            raise ValueError("pour %s: swallow_pads=True fits the pour round other nets' copper from its pads "
                             "alone, so every point is a pad (PadRef, CellPadRef) or a via; a pour through plain "
                             "points is declared without swallow_pads" % name)
        if reach is not None and not fitted:
            raise ValueError("pour %s: reach= grows a fitted pour into the room round it, so it takes swallow_pads=True "
                             "over pads and vias, and no width= (a neck between two pads is drawn as declared)" % name)
        if reach is Reach.CURRENT:
            from . import checks
            carry = checks.carriers_of(self.geometry).get(name, {})
            if len(carry) < 2:
                who = "no part carries current on it" if not carry else \
                    "only %s carries current on it, and the width is sized between two parts" % next(iter(carry))
                raise ValueError("pour %s: reach=Reach.CURRENT sizes the pour for the current its net carries, from "
                                 "the parts' Pm.I, and %s. Give the parts that carry it their Pm.I, or, where the "
                                 "user approves a distance, use reach=mm" % (name, who))
        if cover is None:
            cover = Cover.CENTRES
        refs = _refs_in(points, via_ends=True)         # a via's pads: the pour waits for them as the via does

        def plan(ctx):
            if neck and not fitted:
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
            elif fitted:
                outlines = self._fit_pour(ctx, name, points, layer, stroke, None if ctx.dry else reach)
                if not outlines:
                    return []
                pts = outlines[0]
                if len(outlines) > 1:               # a reach cut in two by copper that stands across it
                    ctx.pour_at[intent.index] = pts
                    return [Pour(name, layer, o, stroke, True) for o in outlines]
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
            return [Pour(name, layer, pts, stroke, fitted)]
        intent = self._copper_intent("pour %s" % name, net, priority, plan, refs, why, only=self._only(only, "pour"))
        intent.members = vias
        self._copper_uses[intent.index] = tuple(v.index for v in vias)
        self._copper_after[intent.index] = tuple(v.index for v in vias)
        intent.reach = reach
        return intent

    def _check_pour_via(self, name: str, it: CopperIntent):
        """A via intent (`via()`, `vias()`, a lane's `.via`) of this board is a pour's member; a track is not."""
        if not any(it is c for c in self._copper):
            raise TypeError("pour %s: %s is copper of another board" % (name, it.key))
        if not it.key.startswith("via"):
            raise TypeError("pour %s: a fitted pour joins pads and vias, and %s is neither" % (name, it.key))

    def _fit_pour(self, ctx, net: str, pads, layer: CopperLayer, stroke: float, reach: float | Reach | None = None):
        """The outline of a fitted pour (pourfit.py) over `pads` as the plan
        stands - with `reach`, the outlines of its copper grown that far into the room
        round it (a distance, or as far as the net's current needs: Reach.CURRENT) - or [] with a finding
        when none can be drawn."""
        from . import pourfit
        occ = ctx.occ
        half = stroke / 2.0
        # every clearance outline is held off by the error its arcs are read with (a pad or a track is
        # a polygon a few microns outside the copper), and the arcs are cut finer by as much, so no
        # corner stands more than `arc_sag` past the clearance
        slack = self.settings.geometry_arc_error_nm * 1e-6
        sag = max(self.settings.geometry_arc_sag - slack, self.settings.geometry_arc_sag / 2.0)
        holds, boxes = [], []
        member_pads, member_vias = [], []       # what Reach.CURRENT measures the pour between
        for p in pads:
            if isinstance(p, CopperIntent):
                ops = ctx.ops_at.get(p.index)
                if ops is None or not any(isinstance(op, Via) for op in ops):
                    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "pour_unplanned", "net": net,
                                                  "why": _past_unplanned(ctx.ops_at, p, "the pour", None).to_json()})
                    return []
                for op in (op for op in ops if isinstance(op, Via)):
                    label = ("via", op.at.x, op.at.y)
                    if op.net != net:
                        ctx.note(C.COPPER_NOT_DRAWN, {"variant": "pour_via_net", "net": net, "member": list(label),
                                                      "on_net": op.net})
                        return []
                    if op.layers and layer not in op.layers:
                        ctx.note(C.COPPER_NOT_DRAWN, {"variant": "pour_via_span", "net": net, "member": list(label),
                                                      "layer": layer.value, "span": _span_of(op.layers)})
                        return []
                    holds.append((label, pourfit.hull(op.polygon)))
                    boxes.append(op.box)
                    member_vias.append(op.polygon)
                continue
            owner, number, _, _ = self._pad_ref(p)
            label = ("pad", owner, number)
            for sh in _pad_shapes(self, occ, p):
                if sh.net != net:
                    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "pour_pad_net", "net": net, "member": list(label),
                                                  "on_net": sh.net})
                    return []
                if layer not in sh.layers:
                    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "pour_pad_layer", "net": net, "member": list(label),
                                                  "layer": layer.value})
                    return []
                holds.append((label, pourfit.hull(sh.poly)))
                boxes.append(sh.box)
                member_pads.append((owner, number, sh.poly))
        grows = self.settings.copper_pour_reach_max if reach is Reach.CURRENT else (reach or 0.0)
        span = Box.union(boxes).inflate(grows)       # what reach= may take a clearance outline in
        pieces = []

        def add(sh, clr: float, what: dict):
            # a polygon of copper (a pour, a drawn poly) is read with the same error on its side of the gap
            r = clr + half + slack * (2 if sh.kind == "copper" and not sh.ends and not sh.owner else 1)
            if not sh.box.overlaps(span, gap=r):
                return
            pieces.extend(pourfit.pieces_of(sh.poly, r, sag, what, sh.circle, () if sh.arc else sh.ends))

        shapes = []
        for owner, g in occ.items.items():
            if owner not in occ.pending:
                shapes += [sh for sh in g.shapes if sh.kind in ("pad", "through", "copper", "npth")]
        shapes += [sh for sh in occ.copper if sh.kind in ("copper", "through")]
        if ctx.dry:             # copper declared before it, held as planned: the pour is fitted round that too
            shapes += [sh for sh in occ.rooms if sh.kind in ("copper", "through")]
        shapes += [sh for sh in (_shape_of(op) for op in ctx.batch_ops) if sh is not None]
        for sh in shapes:
            if sh.kind == "npth":
                cx, cy = sh.box.center.x, sh.box.center.y
                add(dataclasses.replace(sh, circle=(cx, cy, max(math.hypot(x - cx, y - cy) for x, y in sh.poly))),
                    self.geometry.hole_clearance, {"form": "unplated", "who": occ._w(sh.owner)})
            elif layer in sh.layers and sh.net != net:
                add(sh, occ.pair_clearance(net, sh.net, "", sh.owner)[0], _copper_name(occ, sh))
        if occ.edge_margin is not None:
            pieces += pourfit.edge_pieces(_edge_loops(occ), occ.edge_margin + half + slack, sag, span)
        res = pourfit.fit(holds, pieces, half + self.settings.geometry_arc_sag)
        if res.problem:
            facts = {"net": net, "between": [list(l) for l in res.pads],
                     "noun": "pad" if not any(l[0] == "via" for l in res.pads) else "member"}
            if res.piece is not None:
                facts["what"] = res.piece.what
            variant = {"too close": "pour_close", "enclosed": "pour_enclosed", "no way": "pour_no_way"}.get(res.problem,
                                                                                                          "pour_no_area")
            ctx.note(C.COPPER_NOT_DRAWN, dict(facts, variant=variant))
            return []
        if reach is Reach.CURRENT:
            return self._reached_to_current(ctx, net, layer, stroke, res.outline, pieces, sag, member_pads, member_vias)
        if reach is not None:
            return self._reached(ctx, net, res.outline, reach, pieces, sag)
        need = self._width(net, None)
        for gap, (x, y) in sorted(res.necks):
            if gap + stroke < need - 1e-6:
                ctx.note(C.COPPER_NOTE, {"variant": "pour_narrow", "net": net, "width_mm": gap + stroke, "at": [x, y],
                                         "need_mm": need})
        return [res.outline]

    def _grown(self, outline, reach: float, pieces) -> list:
        """The loops of `outline` grown by `reach` and cut back by every clearance outline in `pieces`,
        the parts joined to `outline` (polyops.grow_and_cut); arcs lie no more than `geometry.arc_sag` off."""
        from .kicad import polyops
        box = Box.of_points(outline).inflate(reach)
        cutters = [pc.poly for pc in pieces if pc.right > box.left and pc.left < box.right
                   and pc.bottom > box.top and pc.top < box.bottom]
        return polyops.grow_and_cut(outline, reach, self.settings.geometry_arc_sag, cutters)

    def _reached(self, ctx, net: str, outline, reach: float, pieces, sag: float):
        """The copper of a fitted pour grown by `reach` into the room round its
        `outline`: cut back by every clearance outline in `pieces`, and of what is left the parts
        joined to the pour's own. Arcs lie no more than `geometry.arc_sag` off."""
        from .kicad import polyops
        if not polyops.available():
            ctx.note(C.SETUP_PCBNEW, {"variant": "reach", "net": net})
            return []
        got = self._grown(outline, reach, pieces)
        if not got:
            ctx.note(C.COPPER_NOT_DRAWN, {"variant": "pour_no_reach", "net": net})
        return got

    def _reached_to_current(self, ctx, net: str, layer: CopperLayer, stroke: float, outline, pieces, sag: float,
                            member_pads, member_vias):
        """The copper of a fitted pour grown into the room round its `outline` as far as its net's
        current-path width needs and no further: the smallest multiple of `[copper] pour_reach_step` whose
        copper `checks.pour_current` reads at the width the current needs (`reach=` of that distance, by
        `_reached`'s booleans), searched up to `[copper] pour_reach_max`. Where the maximum falls short, the
        smallest multiple that reaches the width the maximum does, and a finding names the neck."""
        from . import checks, pourfit
        from .kicad import polyops
        s = self.settings
        if not polyops.available():
            ctx.note(C.SETUP_PCBNEW, {"variant": "current", "net": net})
            return []
        have = {p[0] for p in member_pads}
        carriers = {r: a for r, a in checks.carriers_of(self.geometry).get(net, {}).items() if r in have}
        if len(carriers) < 2:
            ctx.note(C.COPPER_NOT_DRAWN, {"variant": "pour_carriers", "net": net, "carriers": sorted(carriers)[:1]})
            return []
        step = s.copper_pour_reach_step
        top = int(math.floor(s.copper_pour_reach_max / step + 1e-9))
        tried: dict = {}

        def at(k: int):
            if k not in tried:
                loops = [outline] if k == 0 else (self._grown(outline, k * step, pieces) or [outline])
                reading = checks.pour_current(net, layer, member_pads, member_vias,
                                              [pourfit.offset(o, stroke / 2.0) for o in loops], carriers,
                                              self.geometry.copper_mm, s.check_rise_c, checks.COPPER_OZ,
                                              s.check_zone_step)
                tried[k] = (loops, reading)
            return tried[k]

        def width(k: int) -> float:
            reading = at(k)[1]
            return math.inf if reading is None else reading.width

        def met(k: int) -> bool:
            reading = at(k)[1]
            return reading is None or reading.ok

        if met(0):
            return at(0)[0]
        # the width only gains with the reach: the goal is the need, or where the room runs out the width
        # the furthest reach gets
        goal = (lambda k: met(k)) if met(top) else (lambda k: width(k) >= width(top) - 1e-9)
        if goal(0):
            k = 0
        else:
            lo, hi = 0, top
            while hi - lo > 1:
                mid = (lo + hi) // 2
                lo, hi = (mid, hi) if not goal(mid) else (lo, mid)
            k = hi
        loops, reading = at(k)
        if not met(k):
            x, y = reading.point
            near = min(((poly_distance(pc.poly, ((x, y), (x + 1e-6, y), (x, y + 1e-6))), pc.what) for pc in pieces),
                       key=lambda d: d[0], default=(math.inf, None))
            facts = {"variant": "pour_neck", "net": net, "reach_mm": k * step, "reach_max_mm": s.copper_pour_reach_max,
                     "width_mm": reading.width, "at": [x, y], "amps": reading.amps, "start": reading.start,
                     "to": reading.to, "need_mm": reading.need, "rise_c": s.check_rise_c}
            if near[0] <= reading.width:
                facts["what"] = near[1]
            ctx.note(C.COPPER_NOTE, facts)
        return loops

    def plane(self, net, layers, *, outline=None, inset: float | None = None, chamfer: float | None = None,
              clearance: float | None = None, min_thickness: float | None = None, solid_pads: bool = True,
              priority: Priority = Priority.DEFAULT, over=None, margin: float = 0.0, only=None, why: str = ""):
        """A KiCad zone per layer, filled by KiCad and pulled back round every
        foreign pad, track and via: the whole board inset from the edge, the
        polygon `outline`, or `over=[Part(...), Cell(...)]` the box round
        those items' drawn envelopes (the region `keepout(item)` takes),
        grown by `margin` and clipped to the frame inset by `inset`. A plane
        over items waits for them to be placed."""
        inset = self.settings.copper_plane_inset if inset is None else inset
        clearance = self.settings.copper_plane_clearance if clearance is None else clearance
        min_thickness = self.settings.copper_plane_min_width if min_thickness is None else min_thickness
        name = self.geometry.require_net(net)
        layers = tuple(dict.fromkeys(CopperLayer.of(l) for l in layers))
        self._planes_declared.append((name, layers))    # a flip is judged against the layers' planes
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
                box = self._items_box(ctx, over).inflate(float(margin))
                frame = ctx.occ.board_box
                if frame is not None:
                    f = frame.inflate(-inset)
                    box = Box(max(box.left, f.left), max(box.top, f.top),
                              min(box.right, f.right), min(box.bottom, f.bottom))
                if box.width <= 0 or box.height <= 0:
                    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "plane_outside", "net": name})
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
        intent = self._copper_intent("plane %s" % name, net, priority, plan, refs, why, only=self._only(only, "plane"))
        if outline is None:
            self._frame_planes.add(intent.index)    # on a fit board, planned once the frame is fitted
        return intent

    def finger(self, net, *, layer: CopperLayer, from_, to, width,
               bridge_width: float | None = None, priority: Priority = Priority.DEFAULT, only=None, why: str = ""):
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
            segs = [chord for t in ctx.tracks_on(layer) if t.net != name for chord in t.chords()]
            return finger_ops(name, layer, a, b, w, segs, self.via_drill, self.via_size, bridge_width,
                              self.settings.copper_bridge_half_gap, self.settings.copper_finger_min_piece)
        return self._copper_intent("finger %s" % name, net, priority, plan, refs, why, only=self._only(only, "finger"))

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
            c.freedom = Freedom.SEARCHED if (c.owners & searched) or c.index in self._late_copper else Freedom.FIXED
        # copper planned after another is planned after the search when that is: a pour fitted to a part's grid
        late = {c.index for c in self._copper if c.freedom is Freedom.SEARCHED}
        grew = True
        while grew:
            grew = False
            for c in self._copper:
                if c.freedom.decided and any(i in late for i in self._copper_after.get(c.index, ())):
                    c.freedom = Freedom.SEARCHED
                    late.add(c.index)
                    grew = True

    reuse_extra = ""        # what the runner adds to the reuse context: tool version, board file, settings, fab profile

    def _phase(self, stage, **info) -> bool:
        """Tell a viewer what the step being worked on is doing now (`on_begin`): a phases.Stage and its numbers (`within`,
        `hint`, `radius`, `face`), with the item and its seconds so far. True when the step is out of time (timecap.py) and the
        search is to stop here."""
        from . import timecap
        clock = timecap.active()
        cut = info.pop("cut", False)                # the scan stops here if the step is out of time: not a thing a viewer is told
        out = clock.phase(stage, cut=cut, **info) if clock is not None else False
        f = self._on_begin
        if f is not None:
            ev = {"kind": "phase", "stage": str(stage), **info}
            if self._step_t0 is not None:
                ev.update(item=self._step_item, elapsed_s=round(time.monotonic() - self._step_t0, 1))
            if self._firm_pass_no is not None:
                ev["firm_pass"] = self._firm_pass_no
            f(self._begin_plan, ev)
        return out

    _on_begin = None
    _begin_plan = None
    _step_t0 = None                 # when the step being worked on began, and its item: what a phase event says of its time
    _step_item = None
    _firm_pass_no = None

    def resolve(self, progress=None, reuse=None, explore=None, lock=None, routes=None, on_step=None, on_begin=None,
                partial=None) -> Plan:
        """Place everything and plan the copper. When a studio listens in the project (channel.py), the steps and the
        finished plan are also sent to it; with none, that costs one lookup, made once per process. `partial` is a
        reuse.PartialLog: each completed step's record is appended to it as the resolve goes."""
        self.finish_declarations()
        if self._laid == DEFAULT_SPEC.id:
            self.lay_arrangement(DEFAULT_SPEC)      # a board laid as another arrangement resolves as that one
        from . import channel
        rep = channel.reporter(getattr(self, "_script", None))
        if rep is None:
            return self._resolve(progress, reuse, explore, lock, routes, on_step, on_begin, partial)
        on_step, on_begin = rep.hooks(self, on_step, on_begin)
        plan = self._resolve(progress, reuse, explore, lock, routes, on_step, on_begin, partial)
        rep.plan(self, plan)
        return plan

    def _resolve(self, progress, reuse, explore, lock, routes, on_step, on_begin, partial=None) -> Plan:
        """The resolve, run again (from the board as it stood) while what the firm items were placed against is not what
        the declared copper turns out to be, or a Beside part was refused by a firm part it can be placed before: each run
        stops after its firm items when that is so, and the last one, or the first that finds everything in place, is the
        resolve (see `_redo_check`)."""
        self._room_seed, self._swaps, self._room_unsettled, self._swap_notes, self._loose = {}, [], [], {}, frozenset()
        self._arr_prev, self._arr_unsettled, self._arr_taken = {}, {}, {}
        self._room_refused = {}         # copper index -> the parts placed when the room planning could not draw it
        self._firm_pass_no = None
        passes = self.settings.place_firm_passes
        if not (self.settings.place_copper_room and passes > 1 and
                (self._copper or any(getattr(i, "beside", None) is not None for i in self._intents))):
            return self._resolve_run(progress, reuse, explore, lock, routes, on_step, on_begin, partial, False)
        saved = self._snapshot()
        taken: dict = {}            # firm cell key -> what it took in each pass that stopped, in order
        for n in range(1, passes + 1):
            self._firm_pass_no = n if n < passes else None      # a pass that stops after the firm items: the one a slow step names
            try:
                return self._resolve_run(progress, reuse, explore, lock, routes, on_step, on_begin, partial, n < passes)
            except _Redo as r:
                prev = self._arr_prev
                self._restore(saved)
                self._room_seed, self._swaps, self._swap_notes, self._loose = r.seed, r.swaps, r.notes, r.loose
                for k, v in r.arr.items():
                    taken.setdefault(k, []).append(v)
                # after the restore, which puts back the attributes as they stood before the passes. A pass that stopped
                # before it reached a firm cell (a Beside redo ends one before the firm collisions) leaves that cell what
                # it took before, so the next pass is compared with it
                self._arr_prev, self._arr_taken = {**prev, **r.arr}, {k: list(v) for k, v in taken.items()}

    def _resolve_run(self, progress, reuse, explore, lock, routes, on_step, on_begin, partial, redo: bool) -> Plan:
        """One run of the resolve. With `redo`, what it reports while it goes is held until it is known that it will not be
        run again."""
        out = self._out = _Out(progress, on_step, on_begin, partial) if redo and (progress or on_step or on_begin or partial) \
            else _Out.through(progress, on_step, on_begin, partial)
        self._redo = redo
        try:
            plan = self._resolve_once(out.progress, reuse, explore, lock, routes, out.on_step, out.on_begin, out.partial)
        except _Redo:
            raise
        except BaseException:
            out.flush()
            raise
        out.flush()
        return plan

    def _resolve_once(self, progress, reuse, explore, lock, routes, on_step, on_begin, partial=None):
        self._arr_choice = {}               # what the firm cells take in this pass (`_settle_firm_arranged`)
        self._check_groups()                # what a declared group may hold, before the search
        self._annotations = exposure.read(self.geometry)    # sources and sensitive parts (Pm.Emits, Pm.Limit); refuses a unit mismatch
        self._part_keep_outs()              # the clearances the parts' Pm.KeepOut ask of other nets' copper; refuses one with no citation
        self._find_riders()                 # before anything asks what is searched
        # An explore variant (explore.py): seed 0, or none, is the plain placement.
        self._explore = explore if (explore is not None and explore.seed) else None
        # Accepted decisions (lock.py): tried first at each locked item's turn.
        self._lock = {e.key: e for e in (lock or ())}
        self._lock_notes = {}
        self._lock_marks = {}
        self._lock_held = set()          # locked items at (or drifted from) their spot: the cleanup pass leaves them
        if self._explore is not None:
            import random as _random
            self._order_rng = _random.Random("%d:order" % self._explore.seed)
        self._escape_laid = {}              # every escape is laid out again, when its part is placed
        self._escape_kept = {}
        self._escape_waits, self._escape_named, self._settled = None, {}, set()
        occ = Occupancy(self.geometry, self.edge_margin, board_box=self._outline, board_shape=self._shape,
                        board_cutouts=self._cutouts, settings=self.settings,
                        component_spacing=self.component_spacing, rules=self._rules)
        occ.set_rooms([sh for shapes in self._room_seed.values() for sh in shapes])     # the copper the passes planned
        self._beside_blocked, self._tight, self._beside_hint = [], {}, set()
        self._check_stamped_via_types()     # a fragment's vias the fab profile does not allow fail the run
        self._flip_said = self._flip_notes(occ)     # a flipped cell's via whose inner end changes role
        self._carry_pad_vias(occ)          # before any cell's geometry is built from its members'
        thinned = self._thin_drops(occ)    # likewise: a cell's geometry takes its fields as thinned
        occ.thin_arranged = self._thin_arranged     # and an arranged cell's, from the arrangement's copper
        # (the callback writes the step's drops note into Board state as the occupancy builds a geometry: valid for this one
        # _resolve_once, whose occupancy it is; _thin_drops above reset the notes)
        occ.quiet_nets = frozenset(self._plane_nets() | set(self._free_nets))
        occ.plane_nets = frozenset(c.net for c in self._copper if c.key.split(" ")[0] == "plane")   # drops' nets
        occ.plane_layers = self._plane_layers()      # {layer: {net, ...}}: give way's shorten reads this
        occ.fab_via_tiers = self.fab_via_tiers        # "micro"/"blind"/"buried" -> "yes"/"no"/"if-needed"
        if self._fit:
            occ.board_box = None                # no frame yet: the decided items have no edge to be judged by
        for intent in self._placements():
            declared = [intent.item.anchor] + [fp for fp, _ in intent.item.satellites] if intent.kind == "block" else [intent.item]
            for item in declared:
                occ.pending |= occ._geometry(item).owners
        plan = Plan(self.geometry, occ, outline=self._outline, chamfer=self._chamfer, radius=self._radius,
                    shape=self._shape, cutouts=self._cutouts,
                    rules=list(self._rules), acceptances=list(self._acceptances), draw_outline=self._draw_outline,
                    cell_zones_under_planes=self.settings.copper_cell_zones_under_planes,
                    split_groups=self.settings.write_split_groups, groups=list(self._groups.values()),
                    thinned=thinned)
        lap = _Lap()
        started = lap.at
        plan.steps = _FedSteps(plan, on_step, lap)
        from . import timecap
        clock = timecap.active()
        if clock is not None and on_begin is None:
            on_begin = lambda plan, info: None          # the phases still say where a step is, to the clock
        self._on_begin, self._begin_plan = on_begin, plan
        occ.on_phase = (lambda stage, **info: self._phase(stage, **info)) if on_begin else None
        ctx = _CopperContext(self, occ)
        ctx.plan = plan
        self._escape_ctx = ctx              # what a lane's via is judged by (_LaneEnv)
        from . import reuse as _reuse
        context = _reuse.context_key(self, self.reuse_extra + self._rooms_digest())
        record = {"version": _reuse.VERSION, "context": context, "steps": [], "reused": 0, "first_change": None}
        plan.reuse = record
        if partial is not None:             # each step's record, as it is made: a resolve that dies leaves them (reuse.PartialLog)
            partial.begin(context)
        previous = reuse.get("steps", []) if reuse and reuse.get("version") == _reuse.VERSION \
            and reuse.get("context") == context else None
        chain = {"key": context, "replaying": previous is not None}
        self._solve_hints = None            # the global solve runs once per resolve, when first asked
        self._report_lost_layers(plan)
        if native_status().warns:           # the pure Python path is the reference, and 5-10x slower: never silent
            plan.findings.append(self._finding(C.SETUP_NATIVE, native_status().facts(), "warning"))
        plan.findings.extend(self._finding(C.SETUP_RULE_NOTE, facts, "notice") for facts in self._stamped_rule_notes)
        limit = self.arrangement_limit()
        if limit is not None:
            plan.findings.append(self._finding(C.ARRANGEMENT_LIMIT, limit, "warning"))
        for cname in sorted(self.geometry.cells) if self.settings.place_arrangements else ():   # off: the board ignores arrangements
            for p in self.geometry.cells[cname].arrangement_problems:
                plan.findings.append(self._finding(C.ARRANGEMENT_STALE, {"cell": cname, "reason": p["reason"], "ids": p["ids"]}, "warning"))
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
        if clock is not None:
            clock.new_pass(len(placements), self._firm_pass_no, plan)
        if on_begin:                        # what is ahead, as far as it is known now: the items, how many are searched, the copper
            on_begin(plan, {"kind": "total", "items": sum(1 for i in placements if not isinstance(i, KeepoutIntent)),
                            "searched": sum(1 for i in placements if not getattr(i.freedom, "decided", True)),
                            "copper": len(self._copper), "replay": len(previous) if previous else 0})
        self._place_fanouts(occ, plan, placed, progress)
        self._place_escapes(occ, plan, placed, progress)
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
                except CutoutNowhere as e:
                    centre, turn, why = self.centre, 0.0, e.why
            else:
                centre = self._cutout_centre(occ, c)
                turn = self._region_rotation(occ, c, centre)
                why = self._cutout_illegal(occ, c.shape.path_at(centre, turn), c.name, silk=False)
            path = c.shape.path_at(centre, turn)
            step = Step(intent.key, "cutout", None, why=intent.why)
            if why:
                plan.findings.append(self._finding(C.FIXED_CUTOUT, {"name": c.name, "why": why.to_json(),
                                                                    "outline_kind": self._outline_decl}))
                step.say("refused", why=why.to_json())
            else:
                self._add_cutout(occ, c.name, PlacedCutout(c.name, tuple(path), centre, turn))
                plan.shape, plan.cutouts = self._shape, self._cutouts   # the fab gets the holes too
                plan.cutouts_placed[c.name] = self._settled_cutouts[c.name]
                step.say("cut", at=[centre.x, centre.y], turn=turn)
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
                except CutoutNowhere as e:
                    centre, turn, why = self.centre, 0.0, e.why
            else:
                centre = self._cutout_centre(occ, k)
                turn = self._region_rotation(occ, k, centre)
                why = None
            step = Step(intent.key, "keepout", None, why=intent.why)
            if why:
                plan.findings.append(self._finding(C.FIXED_KEEPOUT, {"name": k.name, "why": why.to_json()}))
                step.say("refused", why=why.to_json())
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
                barred = frozenset(fp.ref for a in k.bars for fp in members_of(self._item(a)[0]))
                admitted = None
                if k.max_height is not None or barred:          # admitted by height, as allow= admits by name
                    # bars= admits every part on the board, read now, but the barred ones
                    admitted = frozenset(fp.ref for fp in self.geometry.footprints
                                         if fp.ref not in barred and (k.max_height is None or (
                                             part_height(fp) is not None and part_height(fp) <= k.max_height + 1e-9)))
                claims, layer = parts_claim(k.layers)
                if "parts" in k.excludes and claims:
                    occ.reserve(poly, ReservedBy("keepout", k.name, k.why, max_height_mm=k.max_height), allow=nets, owners=owners,
                                layer=layer, admitted=admitted, barred=barred,
                                copper=bool({"tracks", "fill", "vias", "pads"} & set(k.excludes)), courtyard=True)
                if "vias" in k.excludes:        # a via is held out of it as KiCad's DRC holds it
                    occ.add_copper([ban_shape("keepout %r" % k.name, poly, k.layers, nets)])
                plan.keepouts[k.name] = PlacedKeepout(k.name, poly, centre, turn, k.excludes,
                                                      k.layers, nets, owners | (admitted or frozenset()), k.why,
                                                      k.max_height, admitted or frozenset(), barred)
                step.say("kept_clear", at=[centre.x, centre.y])
                if outside:
                    step.say("points_off_board", outside=outside, of=total)
            plan.steps.append(step)
            placed.add(cutout_token(k.name))

        def place_one(obj, why_now=()):
            # The key is taken before anything below changes the declaration.
            ex = self._explore
            key = _reuse.step_key(chain["key"], obj, _reuse.links_on(self, obj),
                                  self._step_extra(obj))
            chain["key"] = key
            position = len(record["steps"])
            if chain["replaying"] and not (position < len(previous) and previous[position]["key"] == key):
                chain["replaying"] = False
            self._step_t0, self._step_item = time.monotonic(), getattr(obj, "key", None) or getattr(obj, "name", "")
            if on_begin:
                decided = getattr(obj.freedom, "decided", True)
                on_begin(plan, {"kind": "begin", "item": getattr(obj, "key", None) or getattr(obj, "name", ""),
                                "what": "keepout" if isinstance(obj, KeepoutIntent) else "cutout" if isinstance(obj, CutoutIntent)
                                else "decided" if decided else "searched",
                                "rank": self._rank_of.get(getattr(obj, "key", None)) if not decided else None,
                                "of": len(self._rank_of) if not decided else None,
                                "replaying": bool(chain["replaying"]), "n": position})
            if isinstance(obj, (KeepoutIntent, CutoutIntent)):
                entry = {"key": key}
                record["steps"].append(entry)
                if chain["replaying"]:
                    record["reused"] += 1
                elif record["first_change"] is None and previous is not None:
                    record["first_change"] = getattr(obj, "key", None) or getattr(obj, "name", None)
                if isinstance(obj, KeepoutIntent):
                    settle_keepout(obj)
                else:
                    settle_cutout(obj)
                step = plan.steps[-1]
                took = previous[position].get("seconds") if chain["replaying"] else None
                entry["seconds"] = round(took if took is not None else step.seconds, 6)
                if chain["replaying"]:
                    step.first_seconds = took
                if partial is not None:
                    partial.append(entry)
                return
            if getattr(obj, "turned", None) is not None:    # its part, or its line's points, are placed by now: needs said so
                obj.rotation = self._turned_rotation(occ, obj)
            if isinstance(obj.run, CutoutEdge):     # the hole is down by now: read its real stretch
                obj.run = self.cutout(obj.run.name).edge(side=obj.run.side, within=obj.run.within)
                if isinstance(obj.along, (Along, Fraction)):
                    obj.along = obj.along.fraction * obj.run.length
                elif obj.along is not None and not isinstance(obj.along, (int, float)):
                    obj.along = _run_along(self, occ, obj)      # a reference: the place on the edge nearest it
                if obj.rotation is None:            # turned to the way the board faces where it sits
                    obj.rotation, obj.faces_note = self.outward_rotation(
                        obj.item, obj.run.at(obj.along if obj.along is not None else 0.0)[1], getattr(obj, "face", None))
            plan._items[obj.key] = obj.item
            if self._fit and not obj.freedom.decided:
                occ.board_box = self._outline = self._fit_room(occ, plan, obj)
            if chain["replaying"]:
                step = self._replay_settle(occ, plan, previous[position], obj)
                record["steps"].append(previous[position])
                record["reused"] += 1
                self._step_t0 = None
                if clock is not None:
                    clock.replayed_step()
            else:
                if record["first_change"] is None and previous is not None:
                    record["first_change"] = obj.key
                n_found = len(plan.findings)
                if clock is not None:
                    clock.begin_step(obj.key)
                try:
                    step, entry = self._recorded_settle(occ, obj, plan, placed)
                except BaseException:
                    self._step_t0 = None        # (the clock keeps the step it was in: a stop reports it)
                    raise
                spent = clock.end_step() if clock is not None else None
                self._step_t0 = None
                entry["key"] = key
                if spent is not None and spent.limited:
                    # The result depends on how long the machine took: no later run may replay it, and the steps after it are
                    # searched again too (their keys no longer match the record's).
                    entry["key"] = key + "|time-limited"
                    self._time_limited(plan, step, spent, n_found, clock.bounds.step_limit_s)
                elif spent is not None:
                    crossed = {"warn_s": clock.bounds.step_warn_s if spent.warned else None,
                               "limit_s": clock.bounds.step_limit_s if spent.over else None}
                    plan.findings.append(self._finding(C.TIME_STEP_SLOW, dict(self._time_facts(spent), **crossed)))
                step.seconds = lap.stamp()
                entry["step"]["seconds"] = round(step.seconds, 6)
                record["steps"].append(entry)
            if chain["replaying"]:
                step.seconds = lap.stamp()
            if partial is not None:
                partial.append(record["steps"][-1])
            step.notes = tuple(why_now) + step.notes
            tier = []
            if not obj.freedom.decided:
                if obj.key in self._rank_note:
                    tier.append(self._rank_note[obj.key])
                if obj.priority_source == "script":
                    tier.append(step_text.record("priority", source="script", value=obj.priority.value))
                if obj.required:
                    tier.append(step_text.record("required"))
            elif getattr(obj, "required", False):
                tier.append(step_text.record("required"))
            step.notes = tuple(tier) + step.notes
            if obj.faces_note:
                step.say(obj.faces_note)
            plan.steps.append(step)
            if step.placement is None and getattr(obj, "required", False) and not self.keep_going:
                raise CriticalUnplaced(obj.key, self._no_place_report(occ, obj, step), plan)
            if step.placement is not None and isinstance(obj, PlaceIntent) and not obj.freedom.decided:
                plan.turns[obj.key] = dict(self._turn_of(occ, obj, step.placement, placed), order=len(plan.turns))
            if obj.key in self._lock_notes:
                step.notes += (self._lock_notes.pop(obj.key),)
                step.lock = "released"
            if step.placement is None:
                pass                    # unplaced: left off the board, pulls nothing, blocks nothing
            elif obj.kind == "block":
                occ.commit(obj.item.anchor, step.placement)
                placed.update(fp.ref for fp in obj.item.members)
            else:
                occ.commit(obj.item, step.placement)
                self._record_arranged_thinned(occ, plan, obj, step.placement)
                placed.update(fp.ref for fp in members_of(obj.item))
                self._labels_give_way(occ, plan, obj.item, step.placement, True)     # as the settle did, for a replay
                if obj.kind == "cell":
                    self._cell_placements[obj.key] = step.placement
                    taken = self._stamped_region_cost(occ, obj.item)
                    if taken >= 0.05:
                        step.say("stamped_regions", area_mm2=taken)
            step.seconds += lap.stamp()                 # the commit and the labels' give-way are this step's work; the record, already
                                                        # logged, holds the settle's time alone
            if progress:
                progress(_fmt(step))
            if on_step:
                on_step(plan, step)
            for r in self._ride_groups.get(obj.key, ()):        # committed with it, in its settle
                rs = next(s for s in reversed(plan.steps) if s.item == r.key)
                if rs.placement is None and r.required and not self.keep_going:
                    raise CriticalUnplaced(r.key, self._no_place_report(occ, r, rs), plan)
                if rs.placement is not None:
                    placed.update(fp.ref for fp in members_of(r.item))
                    self._labels_give_way(occ, plan, r.item, rs.placement, True)
                    if r.turned is not None:
                        r.rotation = rs.placement.rotation      # as a firm Turned item's is set when it is placed
                    if r.kind == "cell":
                        self._cell_placements[r.key] = rs.placement
                if progress:
                    progress(_fmt(rs))
                if on_step:
                    on_step(plan, rs)
            self._settled.add(obj.key)
            self._place_fanouts(occ, plan, placed, progress)
            self._place_escapes(occ, plan, placed, progress)
            self._place_labels(occ, plan, placed, progress)
            if occ.rooms_apply and step.placement is not None:      # declared copper whose ends are all placed now
                self._rooms_after(occ, plan, room_ctx, placed, other_copper, step)

        def place_ranked(lo, hi):
            """FIXED and EDGE go down in declaration order: nothing yields to
            them, so their order changes nothing. Searched items are ordered
            by the placer, one choice at a time, re-measured after each."""
            firm = [obj for obj in placements if lo <= obj.rank[0] <= hi and obj.freedom.decided
                    and getattr(obj, "key", None) not in self._rider_of]      # a rider goes with its item
            while firm:                     # declaration order, except that a position said in terms of a pad waits for it
                ready = [obj for obj in firm if obj.needs <= placed and self._lanes_ready(obj)]
                held = {q for p, q in self._swaps if any(o.key == p for o in firm)}      # placed after the part it was in the way of
                ready = [obj for obj in ready if obj.key not in held] or ready
                if not ready and any(d.index not in self._escape_laid and d.ref in placed for d in self._escapes):
                    self._place_escapes(occ, plan, placed, progress, force=True)    # waits that wait on each other: as before
                    continue
                if not ready:
                    raise ValueError("%s is placed relative to %s, which is not placed by then (only FIXED and EDGE "
                                     "items may be referred to)" % (firm[0].key, ", ".join(sorted(firm[0].needs - placed))))
                place_one(ready[0], [self._swap_notes[ready[0].key]] if ready[0].key in self._swap_notes else ())
                firm.remove(ready[0])
            collisions = [f for f in plan.findings
                          if f.cause in (C.FIXED_CUTOUT, C.FIXED_KEEPOUT)
                          or (f.cause is C.FIXED_PART and f.facts["freedom"] in ("fixed", "edge"))]
            required_keys = {o.key for o in placements if getattr(o, "required", False)}
            demanded = [c for c in collisions if finding_text.subject(c.cause, c.facts) in required_keys]
            if hi == RANK_EDGE:
                self._redo_check(occ, plan, None)       # a part refused by one it can be placed before: the other way round
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
                        obj, why_now = ready[0][2], [step_text.record("locked_order")]
                ex = self._explore
                if ex is not None and obj.key in ex.focus and len(pending) > 1 and self._order_rng.random() < self.settings.explore_swap_chance:
                    other, other_why = self._next_to_place([o for o in pending if o is not obj], occ, placed)
                    if other.key in ex.focus:           # two focused neighbours trade turns
                        obj, why_now = other, list(other_why) + [step_text.record("explore_before", other=obj.key)]
                pending.remove(obj)
                place_one(obj, why_now)

        place_ranked(RANK_FIXED, RANK_EDGE)
        self._place_escapes(occ, plan, placed, progress, force=True)     # whatever the firm items did not release
        self._redo_check(occ, plan, fixed_copper)       # where the declared copper goes, against where the firm items stand
        self._out.flush()
        self._check_web(plan)
        self._check_pitch(plan)
        occ.set_rooms([])       # the real copper replaces what the passes planned
        self._plan_copper(occ, ctx, fixed_copper, plan, progress)
        for key, moved in self._room_unsettled:
            plan.findings.append(self._finding(C.FIXED_ROOM_UNSETTLED, {
                "copper": key, "moved_mm": moved, "passes": self.settings.place_firm_passes}))
        for key, ids in sorted(self._arr_unsettled.items()):
            plan.findings.append(self._finding(C.FIXED_ROOM_UNSETTLED, {
                "item": key, "arrangements": ids, "passes": self.settings.place_firm_passes}))
        if self.settings.place_copper_room:
            occ.rooms_apply = True          # the search keeps clear of what declared copper will be
            room_ctx = self._room_context(occ, plan, ctx)
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
        self._give_way_copper(occ, plan)
        occ.set_rooms([])
        occ.rooms_apply = False
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
        self._report_lanes(plan)
        self._report_undeclared(plan)
        self._report_centres(occ, plan)
        self._report_splits(plan)
        if self._explore is None and self.pin_study:
            self._report_pin_maps(plan)
        self._place_labels(occ, plan, placed, progress, final=True)
        if self._faces is not None:
            text, why, sides = self._faces
            drawn = [fp.courtyard_box for fp in self.geometry.footprints] + [c.box for c in self.geometry.copper] + \
                    [op.box for op in plan.copper if hasattr(op, "box")]
            box = Box.union(drawn)                                                       # below everything the module draws
            plan.copper.append(Text(text, Location(box.left, box.bottom + 1.0), Face.FRONT, 0.5, 0.1, 0.0, "left", "top",
                                    layer="User.Comments"))
            plan.steps.append(Step("faces", "copper", Priority.DEFAULT, None, 0.0, (step_text.record("faces", sides=sides),), why, 1,
                                   laid=(len(plan.copper) - 1,)))
        from . import suggestions
        for found, measure in self._late_suggestions:     # what needs the finished board's occupancy
            try:
                measure(found)
            except Exception:                       # a suggestion is best-effort: no sides measured, the rest still offered
                pass
        self._late_suggestions = []
        if self._explore is None:                   # a variant of an explore is scored and compared, never shown or applied
            suggestions.bind(plan.findings, self)   # each suggestion to the lines of the script it edits
        plan.seconds = time.perf_counter() - started
        return plan

    def _give_way_copper(self, occ: Occupancy, plan: Plan) -> None:
        """What the carried vias did as items were placed (giveway.py): a
        stamped cell's kept on the plan for the write, which moves or
        removes each on the board, and the tails they need drawn with the
        plan's copper (a via declared at a pad draws its own when it is
        planned); and, per item whose vias gave way, a note on its step and
        a finding."""
        from .giveway import report
        plan.given_way = [a for _, a in sorted(occ.given_way.items()) if a.home in self.geometry.cells]
        plan.copper += [a.tail for a in plan.given_way if a.tail is not None]
        plan.copper += [t for a in plan.given_way for t in a.tracks]          # a routed via's rebuilt tracks
        step_of = {}
        for key, it in plan._items.items():
            if isinstance(it, CellGeom):
                step_of[it.name] = key
                for fp in it.members:
                    step_of.setdefault(fp.ref, key)
            elif isinstance(it, Footprint):
                step_of[it.ref] = key
        for key, it in plan._items.items() if occ.needs else ():    # a spot an if-needed fab option would have cleared
            if not isinstance(it, (Footprint, CellGeom)):
                continue
            step = next((s for s in plan.steps if s.item == key), None)
            said = occ.needs.get(occ._geometry(it).owners) if step is not None and step.placement is None else None
            if said:
                plan.findings.append(self._finding(C.NEEDS_OPTION, {"item": key, "option": said.to_json()}))
        for home, facts, severity in report(occ):
            key = step_of.get(home, home)
            facts = dict(facts, item=key)
            plan.findings.append(self._finding(C.VIAS_DROPPED if severity == "warning" else C.VIAS_GAVE_WAY, facts, severity))
            step = next((s for s in plan.steps if s.item == key), None)
            if step is not None:
                step.say("vias", facts=facts)

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

    @staticmethod
    def _time_facts(spent) -> dict:
        """What a time finding says of a step's time (timecap.StepTime), as facts."""
        from . import timecap
        at = spent.limited_stage if spent.limited else spent.warned_stage or spent.stage
        return {"item": spent.item, "elapsed_s": spent.elapsed_s, "warned_at_s": spent.warned_at_s,
                "pass": timecap.pass_name(at, None, spent.firm_pass), "stage": at,
                "within": spent.within, "firm_pass": spent.firm_pass}

    def _time_limited(self, plan: Plan, step: Step, spent, n_found: int, limit_s: float) -> None:
        """A step gave up at its time limit (timecap.py): the findings its search made of having no room are replaced by the
        one that says why it has none, or has the spot it had found."""
        kept = "unplaced" if step.placement is None else "best_so_far"
        if kept == "unplaced":
            del plan.findings[n_found:]
        facts = dict(self._time_facts(spent), limit_s=limit_s, kept=kept)
        unreached = self._arr_unreached.pop(step.item, [])
        if unreached:
            facts["arrangements"] = unreached
        plan.findings.append(self._finding(C.TIME_STEP_LIMIT, facts, "critical" if kept == "unplaced" else "warning"))
        if kept == "unplaced" and not step.unplaced:
            step.unplaced = ({"form": "time_limit"},)
            step.notes = (step_text.record("unplaced"),)

    def _step(self, i: PlaceIntent, placement, moved_mm: float, notes=(), unplaced: list | None = None) -> Step:
        """A searched or decided item's step, with its priority, freedom and rank. `notes` are step_text records. `unplaced`:
        why the item has no place, as step_text.unplaced_text reads it; the step's notes then start with "unplaced" and
        none of `notes` is kept."""
        notes = [step_text.record("unplaced")] if unplaced is not None else list(notes)
        arranged = getattr(i.item, "arrangement", "")
        if placement is not None and arranged and placement.arrangement != arranged:
            placement = dataclasses.replace(placement, arrangement=arranged)
        drops = self.__dict__.get("_drops_notes", {}).get(i.key)
        if placement is not None and placement.arrangement and i.kind == "cell":     # its fields as the arrangement stands them
            drops = self.__dict__.get("_arranged_drops_notes", {}).get((i.item.name, placement.arrangement), drops)
        if drops:
            notes.append(drops)
        if getattr(placement, "face", None) is Face.BACK:
            notes += self.__dict__.get("_flip_said", {}).get(i.key, ())
        return Step(i.key, i.kind, None if i.freedom.decided else i.priority, placement, moved_mm, tuple(notes), i.why,
                    freedom=i.freedom, rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None,
                    unplaced=None if unplaced is None else tuple(unplaced), lock=self.__dict__.setdefault("_lock_marks", {}).pop(i.key, ""))

    def _recorded_settle(self, occ: Occupancy, obj, plan: Plan, placed: set):
        """_settle, and what it did beyond the step it returns, for the next
        run to replay: the occupancy commits made inside it (a block's
        satellites), the steps and findings it added, the nets it was seeded
        on, whether it took a pocket, and the solve it ran."""
        from . import reuse as _reuse
        n_steps, n_findings, n_pocketed = len(plan.steps), len(plan.findings), len(plan.pocketed)
        seeded, solve, items = dict(plan.seeded_by_net), dict(plan.solve), set(plan._items)
        riders = isinstance(obj, PlaceIntent) and obj.key in self._ride_groups
        # A searched item does not see user labels (a label gives way once the item is down, in
        # place_one); a firm one does, and its labels have already given way in _settle.
        occ.labels_yield = bool(plan.__dict__.get("_label_parts")) and not getattr(obj.freedom, "decided", True) \
            and getattr(obj, "kind", "") != "block"
        occ.step_budget = SearchBudget(getattr(obj, "budget", None) or self.settings.place_step_budget) \
            if isinstance(obj, PlaceIntent) else None
        try:
            self._riding = (obj.key, occ, plan, {}) if riders else None
            with _recording_commits(occ) as commits:
                alone = self._riders_alone(occ, plan, obj) if riders else None
                if alone:
                    # a refusal of an arrangement other than the default is tagged with it, as _first_legal tags its refusals
                    turns = [[r, w.to_json()] + ([a] if a else []) for r, w, a in alone]
                    facts = {"item": obj.key, "variant": "alone", "turns": turns}
                    plan.findings.append(self._finding(C.UNPLACED_RIDES, facts))
                    step = self._step(obj, None, 0.0, unplaced=[{"form": "riders_alone", "turns": facts["turns"]}])
                    tried = list(dict.fromkeys(a for _, _, a in alone))
                    if len(tried) > 1 or tried != [""]:
                        step.notes = step.notes + (self._arrangement_note(None, [self._arrangement_row(a, None, False)
                                                                                  for a in tried]),)
                else:
                    step = self._settle(occ, obj, plan, placed)
                occ.labels_yield = False
                if riders:
                    self._settle_riders(occ, obj, plan, step)
        finally:
            occ.labels_yield = False
            occ.step_budget = None
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
        was = [(s.placement, s.notes) for s in plan.steps]
        with _recording_commits(occ) as commits:
            self._cleanup(occ, plan)
        changed = [[k, _reuse.placement_to_json(s.placement), list(s.notes)] for k, s in enumerate(plan.steps)
                   if k < len(was) and (s.placement, s.notes) != was[k]]
        return {"commits": commits, "changed": changed, "cleanup": dict(plan.cleanup)}

    def _apply_commits(self, occ: Occupancy, commits, plan: Plan):
        """Commit, in order, what _recording_commits recorded. A cell recorded in an arrangement commits as it stands it, and its
        thinned vias are the arrangement's, as when it was first committed."""
        from . import reuse as _reuse
        for key, placement in commits:
            kind, name = key[0], key[1]
            item = self.geometry.cells[name] if kind == "cell" else self.geometry.footprint(name)
            placement = _reuse.placement_from_json(placement)
            if len(key) > 2:
                placement = dataclasses.replace(placement, arrangement=key[2])
            occ.commit(item, placement)
            if kind == "cell" and placement.arrangement:
                self._record_thinned(occ, plan, name, placement.arrangement)

    def _replay_cleanup(self, occ: Occupancy, plan: Plan, entry: dict):
        from . import reuse as _reuse
        self._apply_commits(occ, entry["commits"], plan)
        for k, placement, notes in entry["changed"]:
            plan.steps[k].placement = _reuse.placement_from_json(placement)
            plan.steps[k].notes = tuple(notes)
        plan.cleanup = dict(entry["cleanup"])

    def _replay_settle(self, occ: Occupancy, plan: Plan, entry: dict, obj=None):
        """What _recorded_settle recorded, done again without the search.
        A push's hard-limit disc is a reservation, not a commit: replaying
        the recorded commits alone never re-adds it, so a later step (or
        the cleanup pass, which is not replayed whenever anything after
        this item changed) could stand inside it unrefused. Reserve it
        again here, the same as a fresh _settle does at its own start."""
        from . import reuse as _reuse
        if isinstance(obj, PlaceIntent) and obj.kind != "block":
            self._reserve_pushes(occ, plan, obj)
        self._apply_commits(occ, entry["commits"], plan)
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
                plan.findings.append(self._finding(C.SETUP_FRAME_REACH, {
                    "item": step.item, "from_mm": ilo, "to_mm": ihi, "axis": which, "frame_from_mm": lo, "frame_to_mm": hi}))

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
        held = self._paired_refs() | {d.ref for d in self._escapes}     # lanes were laid where it stands
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
                    s.cleanup_search_radius, s.cleanup_search_step,
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
            swapped_with = sorted(set(swapped[step.item])) if step.item in swapped else None
            # A part's own cost is not comparable from one pass to the next -
            # its neighbours move too - so the step says how far it went, and
            # plan.cleanup the board's cost before and after.
            moved = was.location.distance(now.location) if step.item in r.moves or not swapped_with else None
            step.say("cleanup", swapped_with=swapped_with, moved_mm=moved)
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
        for vias in self._via_passes(occ, i):
            for face in self._faces_of(i):
                for rot in rots:
                    env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, face))
                    for pocket in pockets(occ, env.width, env.height, face, item=i.item, vias=vias,
                                          step=max(i.step, self.settings.place_pocket_step)):
                        hint = box_centered_placement(occ, i.item, pocket.box.center, rot, face)
                        result = scan(occ, i.item, hint, max(pocket.box.width, pocket.box.height) / 2, i.step, (rot,), clr,
                                      accept=self._accept(i))
                        for k, why in result.reasons.items():
                            if why.code is Code.RIDER:
                                riders.setdefault(k, why)
                        if result.chosen is not None:
                            notes = [step_text.record("pocket", w_mm=pocket.box.width, h_mm=pocket.box.height,
                                                    at=[pocket.box.center.x, pocket.box.center.y])]
                            if face is not i.face:
                                notes.append(step_text.record("pocket_other_face", face=face.value, wanted=i.face.value))
                            return self._step(i, result.chosen, 0.0, notes)
                        tried.append(pocket)
        # The raster rounds each blocker out to its cells and reads a free rectangle only: room of another shape, or
        # narrower than its cells resolve, is no pocket. A scan of the whole face judges what is really there.
        result, face, cut, timed_out = self._scan_whole_face(occ, i, rots, clr, riders)
        if timed_out:
            return self._step(i, None, 0.0, unplaced=[{"form": "time_limit"}])
        if result is not None:
            notes = [step_text.record("pocket_scan", tried=len(tried))]
            if face is not i.face:
                notes.append(step_text.record("pocket_other_face", face=face.value, wanted=i.face.value))
            return self._step(i, result.chosen, 0.0, notes)
        from . import suggest_facts
        env = occ.body_box(i.item, Placement(Location(0, 0), i.rotation, i.face))
        facts = dict(suggest_facts.unplaced_pocket(self, occ, plan, i), variant="tried", w_mm=env.width, h_mm=env.height,
                     face=self._face_text(i), tried=len(tried), riders=[w.to_json() for w in riders.values()])
        if occ.board_box is not None:
            facts["scanned"] = True
            if cut is not None:
                facts["budget"] = cut
        plan.findings.append(self._finding(C.UNPLACED_POCKET, facts))
        return self._step(i, None, 0.0, unplaced=[{"form": "no_pocket"}] + [why.to_json() for why in riders.values()] +
                          ([{"form": "budget", "budget": cut}] if cut is not None else []))

    def _scan_whole_face(self, occ: Occupancy, i: PlaceIntent, rots, clr, riders: dict) -> tuple:
        """(the result of the nearest legal spot to the board's centre on a face `i` may take, the front first, else
        None; that face; the step budget's measurement when it ended a scan, else None; whether the step's time limit
        ended the search). The scan a searched item makes, over the radius a wide search uses, bounded by the step
        budget. `riders` collects the riders' refusals."""
        box = occ.board_box
        if box is None:
            return None, None, None, False
        from . import timecap
        radius = math.hypot(box.width, box.height)
        cut = None
        for face in self._faces_of(i):
            result = scan(occ, i.item, Placement(box.center, rots[0], face), radius, i.step, tuple(rots), clr,
                          accept=self._accept(i))
            for k, why in result.reasons.items():
                if why.code is Code.RIDER:
                    riders.setdefault(k, why)
            if result.chosen is not None:
                return result, face, None, False
            cut = cut or result.cut
            clock = timecap.active()
            if clock is not None and clock.gave_up:
                return None, None, cut, True
        return None, None, cut, False

    def _via_passes(self, occ: Occupancy, i: PlaceIntent) -> tuple:
        """How a pocket search treats the board's through vias, in turn. An
        item a via cannot refuse ignores them (`Occupancy.vias_matter`). One
        with pads, copper or holes is first given the pockets that leave
        every via clear; failing those, the ones that do not, for the scan to
        place its pads between the vias, as the raster cannot see where they
        fall."""
        return (True, False) if occ.vias_matter(i.item) else (True,)

    def _seeded_pocket(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, hint: Placement, score,
                       rotations, why: dict):
        """A seeded item whose scan found nothing: the free pocket nearest the
        seed that it fits, scanned with the same link score, so it lands at
        the end nearest what it connects to. None when no pocket takes it;
        with it, how many pockets there were."""
        at = hint.location

        def gap(pocket):
            b = pocket.box
            return math.hypot(max(b.left - at.x, 0.0, at.x - b.right), max(b.top - at.y, 0.0, at.y - b.bottom))
        total = 0
        for vias in self._via_passes(occ, i):
            for face in self._faces_of(i):          # the front's pockets first, then the back's
                seen = []
                for rot in rotations:
                    env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, face))
                    for pocket in pockets(occ, env.width, env.height, face, item=i.item, vias=vias,
                                          step=max(i.step, self.settings.place_pocket_step)):
                        if all(pocket.box != p.box for p, _ in seen):
                            seen.append((pocket, rot))
                total += len(seen)
                for k in sorted(range(len(seen)), key=lambda k: (round(gap(seen[k][0]), 6), k)):
                    pocket, rot = seen[k]
                    start = box_centered_placement(occ, i.item, pocket.box.center, rot, face)
                    result = scan(occ, i.item, start, max(pocket.box.width, pocket.box.height) / 2, i.step,
                                  tuple(rotations), clr, score=score, accept=self._accept(i))
                    if result.chosen is not None:
                        plan.pocketed.append(i.key)
                        took = {"w_mm": pocket.box.width, "h_mm": pocket.box.height,
                                "at": [pocket.box.center.x, pocket.box.center.y], "seed_mm": gap(pocket),
                                "face": face.value if face is not i.face else ""}
                        step = self._step(i, result.chosen, result.moved_mm, [why, step_text.record("took_pocket", pocket=took)])
                        step.pocket = took
                        return step, total
        return None, total

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
                occ.reserve(band, ReservedBy("fanout", key, side=side.name.lower()), owners=allowed, layer=face.copper)
                notes.append(side.name.lower())
            made = (step_text.record("fanout", sides=notes, depth_mm=depth),)
            plan.steps.append(Step("fanout " + key, "copper", Priority.DEFAULT, None, 0.0, made, why, 1))
            if progress:
                progress("%-28s copper  fanout   %s" % ("fanout " + key, step_text.render_all(made)))

    def _place_labels(self, occ, plan: Plan, placed: set, progress, final: bool = False):
        """Every label whose item is down and not yet labelled: its text op,
        its reservation, and a finding when it sits on something already
        placed. Called after each placement and once more at the end, when
        a label whose item was declared but found no place is a finding."""
        declared = self._declared_refs()
        done = plan.__dict__.setdefault("_labelled", {})
        if final:                       # what landed on a label after it was worked out
            for key, (op, own, face) in done.items():
                for h in _label_hits(occ, op.box, face, own):
                    if not any(f.cause is C.LABEL_SITS_ON and f.facts["key"] == key and h in f.facts["hits"]
                               for f in plan.findings):
                        plan.findings.append(self._finding(C.LABEL_SITS_ON, self._label_facts(key, hits=[h])))
        box_of = lambda item: self._label_item_box(occ, item)
        for entry in self._labels:
            key, item, text, side, gap, align, size, thick, knockout, rotation, why, reserve, group = entry
            if key in done:
                continue
            refs = self._label_refs(item)
            group_refs = [r for one in (group or ()) for r in self._label_refs(one)]
            waiting = [r for r in refs + group_refs if r in declared and r not in placed]
            if waiting:
                if final:               # its item found no place: the label is not drawn, as the item is not
                    facts = self._label_facts(key, waiting=occ.who(waiting[0]))
                    if not any(f.cause is C.LABEL_NOT_DRAWN and f.facts["key"] == key and f.facts["waiting"] == facts["waiting"]
                               for f in plan.findings):
                        plan.findings.append(Finding(C.LABEL_NOT_DRAWN, facts, "notice"))     # its item's own finding is the fault
                continue
            box, face = box_of(item)
            line = Box.union([box_of(one)[0] for one in group]) if group else None
            # The reach holds the part's own silk: a label nearer than the board's
            # silk clearance is a silk overlap to KiCad, whatever gap was asked for.
            gap = max(gap, self.geometry.silk_clearance)
            op = _label_op(text, box, face, side, gap, align, size, thick, knockout, rotation, line)
            own = {occ.who(r) for r in refs}
            notes = [step_text.record("label_at", side=side.name.lower(), item=self._label_ids[key][0])]
            off = self._label_off_board(occ, op.box)
            if off:                     # silk off the board is not printed: another spot on it, if the label is not in a line
                spots = [] if group else [c for c in self._label_candidates(entry, box, op)
                                          if not self._label_off_board(occ, c[2].box)]
                spots.sort(key=lambda c: bool(_label_hits(occ, c[2].box, face, own)))      # a clear one first
                if spots:
                    side_, word, op = spots[0]
                    notes = [step_text.record("label_at", side=side_.name.lower(), word=word, item=self._label_ids[key][0]),
                             step_text.record("label_off_board", was=side.name.lower(), fault=off.to_json())]
                    plan.__dict__.setdefault("_label_at", {})[key] = "%s %s" % (side_.name.lower(), word)
                else:
                    plan.findings.append(self._finding(C.LABEL_NO_SPOT, self._label_facts(
                        key, variant="off_board", edge=off.to_json())))
            plan.copper.append(op)
            hits = _label_hits(occ, op.box, face, own)
            if hits:
                plan.findings.append(self._finding(C.LABEL_SITS_ON, self._label_facts(key, hits=list(hits))))
                notes.append(step_text.record("sits_on", hits=list(hits)))
            if reserve:
                occ.reserve(op.box, ReservedBy("label", "%s %s" % self._label_ids[key], item=self._label_ids[key][0]), layer=face.copper, source=LABEL_SOURCE)     # the text's own box, no more
                # The reservation keeps bodies off the text; as silk it also keeps
                # a later part's silk the silk clearance away where the envelope
                # claims silk, as KiCad checks it.
                silk = Shape(key, "silk", frozenset([face]), frozenset(), "", box_polygon(op.box), op.box)
                occ.add_copper([silk])
                plan.__dict__.setdefault("_label_parts", {})[key] = (silk, occ.reservations[-1])
                notes.append(step_text.record("reserved"))
            plan.steps.append(Step(key, "copper", Priority.DEFAULT, None, 0.0, tuple(notes), why, 1, laid=(len(plan.copper) - 1,)))
            done[key] = (op, own, face)
            if progress:
                progress("%-28s copper  label    %s" % (key, step_text.render_all(notes)))

    def _finding(self, cause, facts: dict, severity: str | None = None) -> Finding:
        """A finding of this cause from the facts its site measured. Its suggestions are built from the facts at the end
        of the resolve (suggestions.bind), so a finding replayed from the reuse record has them too."""
        return Finding(cause, facts, severity)

    def _label_facts(self, key: str, **more) -> dict:
        """What a label finding is made of: the label (its item, its text), as declared (its side and size), the other
        sides it could take, and what the site adds."""
        item, text = self._label_ids[key]
        entry = next((e for e in self._labels if e[0] == key), None)
        facts = {"key": key, "item": item, "text": text}
        if entry is not None:
            facts.update(side=entry[3].name, size=entry[6], sides=[s.name for s in Edge if s is not entry[3]])
        facts.update(more)
        return facts

    def _label_item_box(self, occ, item) -> tuple:
        """(the reach a label stands off, its face): a pad's copper, or the
        reach of the part or of every member of the cell."""
        refs = self._label_refs(item)
        if isinstance(item, (PadRef, CellPadRef)):
            owner = self._pad_ref(item)[0]
            return Box.union([s.box for s in _pad_shapes(self, occ, item)]), occ.items[owner].reference.face
        return Box.union([occ.items[r].reach or occ.items[r].body for r in refs]), occ.items[refs[0]].reference.face

    @staticmethod
    def _label_in_the_way(occ, shape, reservation, item, placement, committed: bool = False) -> bool:
        """Whether `item` at `placement` stands where a label's text is kept
        clear: its silk within the silk clearance of the text's silk, or its
        body in the text's reserved box, on the label's face. `committed`:
        the item is already on the occupancy, so its shapes are read there."""
        box = shape.box
        face = next(iter(shape.faces))
        if committed:
            held = [occ.items[fp.ref] for fp in members_of(item) if fp.ref in occ.items]
            shapes = [sh for g in held for sh in g.shapes]
            if any(sh.box.overlaps(box, gap=occ.gap_for(sh)) and occ._conflict(sh, shape, None) for sh in shapes):
                return True
            on_face = any(g.reference.face is face for g in held)
            reach = lambda: any((g.reach or g.body).overlaps(box) for g in held)
            bodies = [(g.body, occ.standing_faces(g, g.reference.face)) for g in held]
        else:
            if occ.legal(item, placement, others=[shape], board=False) is not None:
                return True
            on_face = placement.face is face
            shapes = occ.shifted_shapes(item, placement)
            reach = lambda: occ.reach_box(item, placement).overlaps(box)
            geom = occ._geometry(item)
            faces = occ.standing_faces(geom, placement.face)
            bodies = [(occ.shifted_body_box(item, placement), faces)]
            if geom.parts:                          # a cell is judged by its members' boxes
                bodies = [(pb, faces) for pb in occ._shifted_parts(geom, placement)]
        if on_face:                                 # what _label_hits calls sitting on a label
            if occ.envelope != "physical":
                if reach():
                    return True
            elif any((sh.kind in _LABEL_COVERS or (sh.kind == "courtyard" and sh.claims)) and sh.box.overlaps(box)
                     and polys_overlap(shape.poly, sh.poly) for sh in shapes):
                return True
        layer = reservation.layer
        return any((layer is None or layer.face in faces) and reservation.overlaps(b) for b, faces in bodies)

    def _label_off_board(self, occ, box: Box):
        """Why a label's text box is not on the board, or None. Silk off the
        board is not printed, and KiCad judges silk to the board edge by the
        silk clearance rule (drc_test_provider_edge_clearance.cpp:
        SILK_CLEARANCE_CONSTRAINT, DRCE_SILK_EDGE_CLEARANCE), so the text keeps
        that clearance from the outline and from a cutout."""
        return occ.board_why(box, self.geometry.silk_clearance)

    def _label_candidates(self, entry, box: Box, op: Text) -> list:
        """[(side, where on it, the label there)] for the spots a label may
        move to, nearest first: along its declared side, from where it stands
        to either flush end, then the item's other sides, nearest to where it
        stands first, each from its declared align. A spot keeps the label's
        own gap off the item and the label over the item's extent on that side
        (a label wider than the side: between its two flush ends)."""
        key, item, text, side, gap, align, size, thick, knockout, rotation = entry[:10]
        face = op.face
        gap = max(gap, self.geometry.silk_clearance)
        step = self.settings.label_slide_step
        stand = op.box.center

        def drawn(s):
            return _label_op(text, box, face, s, gap, align, size, thick, knockout, rotation)

        def far(s):
            c = drawn(s).box.center
            return math.hypot(c.x - stand.x, c.y - stand.y)

        out = []
        for s in [side] + sorted((s for s in Edge if s is not side), key=far):
            base = op if s is side else drawn(s)
            along_x = s in (Edge.NORTH, Edge.SOUTH)               # the side runs along x
            lo, hi = (box.left, box.right) if along_x else (box.top, box.bottom)
            bb = base.box
            here, length = (bb.left, bb.width) if along_x else (bb.top, bb.height)
            start, end = lo, hi - length
            pmin, pmax = min(start, end), max(start, end)
            spots = {round(here, 6), round(start, 6), round(end, 6)}
            spots |= {round(min(pmax, pmin + k * step), 6) for k in range(int((pmax - pmin) / step) + 2)}
            for p in sorted((p for p in spots if pmin - 1e-6 <= p <= pmax + 1e-6), key=lambda p: (abs(p - here), p)):
                d = p - here
                at = Location(base.at.x + d, base.at.y) if along_x else Location(base.at.x, base.at.y + d)
                if abs(p - start) < 1e-6:
                    word = "START"
                elif abs(p - end) < 1e-6:
                    word = "END"
                elif abs(p - (start + end) / 2.0) < 1e-6:
                    word = "MID"
                else:
                    word = "%.2f mm from START" % abs(p - start)
                out.append((s, word, base if abs(d) < 1e-9 else dataclasses.replace(base, at=at)))
        return out

    def _labels_give_way(self, occ, plan: Plan, item, placement: Placement, committed: bool = False) -> bool:
        """A label is a user's mark, not what makes the board work: where
        `item`, firm at `placement`, would stand within silk clearance of the
        text of a label declared on another item, or in its reserved box, the
        label moves - along its side, then to the item's other sides - and
        the item does not. A line of labels (a list, or `line=`) moves as one.
        True when one did. A label with no clear spot stays, and is a
        finding."""
        parts = plan.__dict__.get("_label_parts")
        if not parts:
            return False
        done = plan._labelled
        mine = sorted({occ.who(fp.ref) for fp in members_of(item)})
        moved = False
        seen = set()
        for entry in self._labels:
            key = entry[0]
            if key in seen or key not in parts or key not in done:
                continue
            group = entry[12]
            unit = [e for e in self._labels if e[12] is group and e[0] in parts and e[0] in done] if group else [entry]
            seen |= {e[0] for e in unit}
            hit = [e for e in unit
                   if not done[e[0]][1] & set(mine)
                   and self._label_in_the_way(occ, parts[e[0]][0], parts[e[0]][1], item, placement, committed)]
            if not hit:
                continue
            if self._unit_gives_way(occ, plan, unit, item, placement, committed, mine):
                moved = True
                continue
            at = hit[0][0] if group else key
            facts = self._label_facts(at, variant="line_blocked" if group else "blocked", line=bool(group), mine=list(mine))
            if not any(f.cause is C.LABEL_NO_SPOT and f.facts["key"] == at and f.facts.get("variant") == facts["variant"]
                       and f.facts.get("mine") == facts["mine"] for f in plan.findings):
                plan.findings.append(self._finding(C.LABEL_NO_SPOT, facts))
        return moved

    def _unit_gives_way(self, occ, plan: Plan, unit: list, item, placement: Placement, committed: bool,
                        mine: list) -> bool:
        """Move a label (or a line of them, as one) to the first spot where
        every text is clear of `item` and of the board. True when it moved."""
        parts, done = plan._label_parts, plan._labelled
        keys = {e[0] for e in unit}
        boxes = {e[0]: self._label_item_box(occ, e[1])[0] for e in unit}
        theirs = set()
        for e in unit:
            theirs |= ({self._pad_ref(e[1])[0]} if isinstance(e[1], (PadRef, CellPadRef))
                       else set(self._label_refs(e[1])) | {self._item(e[1])[1]})
        for one in unit[0][12] or ():
            theirs |= ({self._pad_ref(one)[0]} if isinstance(one, (PadRef, CellPadRef))
                       else set(self._label_refs(one)) | {self._item(one)[1]})
        obstacles = occ._obstacle_shapes(frozenset(occ.pending) | theirs | keys)
        labels = [d[0].box for k, d in parts.items() if k not in keys]
        was = {e[0]: done[e[0]][0].box for e in unit}
        together = {(a, b) for a in keys for b in keys if a < b and was[a].overlaps(was[b])}
        for side, word, cands in self._unit_candidates(occ, unit, boxes, done):
            ok = True
            shapes = {}
            for e, cand in zip(unit, cands):
                op, own, face = done[e[0]]
                cb = cand.box
                silk = Shape(e[0], "silk", frozenset([face]), frozenset(), "", box_polygon(cb), cb)
                held = dataclasses.replace(parts[e[0]][1], poly=box_polygon(cb))
                shapes[e[0]] = (silk, held)
                if (self._label_off_board(occ, cb)
                        or (not own & set(mine) and self._label_in_the_way(occ, silk, held, item, placement, committed))
                        or _label_hits(occ, cb, face, set(own)) or any(cb.overlaps(b) for b in labels)
                        or (occ.envelope == "physical" and any(
                            o.box.overlaps(cb, gap=occ._drawn_gap) and occ._conflict(silk, o, None)
                            for o in obstacles))):
                    ok = False
                    break
            if ok and any(cands[i].box.overlaps(cands[j].box) for i in range(len(unit)) for j in range(i + 1, len(unit))
                          if (unit[i][0], unit[j][0]) not in together and (unit[j][0], unit[i][0]) not in together):
                ok = False
            if not ok:
                continue
            for e, cand in zip(unit, cands):
                silk, held = shapes[e[0]]
                self._move_label(occ, plan, e, cand, silk, held, side, word, mine)
            return True
        return False

    def _unit_candidates(self, occ, unit: list, boxes: dict, done: dict):
        """[(side, where on it, the unit's texts there)] for the spots a label
        or a line of them may move to, nearest first. A line moves rigidly: its
        texts keep their spacing and order, and each keeps standing beside its
        own item. Along the side it stands on, shifted by `label.slide_step`
        from where it is; then on the other sides, nearest first, redrawn as
        declared and shifted the same way. A lone label slides from flush to
        flush instead (`_label_candidates`)."""
        if len(unit) == 1 and not unit[0][12]:
            e = unit[0]
            op = done[e[0]][0]
            for side, word, cand in self._label_candidates(e, boxes[e[0]], op):
                yield side, word, [cand]
            return
        step = self.settings.label_slide_step
        said = {"centre": "MID"}.get(unit[0][5], unit[0][5].upper())
        group = unit[0][12]
        line = Box.union([self._label_item_box(occ, one)[0] for one in group])
        ops = [done[e[0]][0] for e in unit]
        here = ops[0].side
        centre = Box.union([o.box for o in ops]).center

        def drawn(s):
            out = []
            for e in unit:
                key, item, text, side, gap, align, size, thick, knockout, rotation = e[:10]
                out.append(_label_op(text, boxes[key], ops[0].face, s, max(gap, self.geometry.silk_clearance), align,
                                     size, thick, knockout, rotation, line))
            return out

        def far(s):
            c = Box.union([o.box for o in drawn(s)]).center
            return math.hypot(c.x - centre.x, c.y - centre.y)

        for s in [here] + sorted((s for s in Edge if s is not here), key=far):
            base = ops if s is here else drawn(s)
            along_x = s in (Edge.NORTH, Edge.SOUTH)
            lo, hi = -math.inf, math.inf
            for e, o in zip(unit, base):                        # a text keeps overlapping its own item along the side
                it = boxes[e[0]]
                a0, a1 = (it.left, it.right) if along_x else (it.top, it.bottom)
                b0, b1 = (o.box.left, o.box.right) if along_x else (o.box.top, o.box.bottom)
                lo, hi = max(lo, a0 - b1 + 1e-3), min(hi, a1 - b0 - 1e-3)
            lo, hi = min(lo, 0.0), max(hi, 0.0)
            shifts = {0.0, round(lo, 6), round(hi, 6)}
            k = 1
            while k * step <= max(-lo, hi) + 1e-9:
                shifts |= {round(k * step, 6), round(-k * step, 6)}
                k += 1
            for d in sorted((d for d in shifts if lo - 1e-6 <= d <= hi + 1e-6), key=lambda d: (abs(d), d)):
                at = (lambda o: Location(o.at.x + d, o.at.y)) if along_x else (lambda o: Location(o.at.x, o.at.y + d))
                word = said if abs(d) < 1e-9 else "%s, line shifted %+.2f mm" % (said, d)
                yield s, word, [o if abs(d) < 1e-9 else dataclasses.replace(o, at=at(o)) for o in base]

    def _move_label(self, occ, plan: Plan, entry, op: Text, shape: Shape, reservation, side: Edge, word: str,
                    because) -> None:
        """Take a label from where it stands to `op`: its text, its silk
        obstacle, its reserved box, and a note on its step."""
        key = entry[0]
        old, own, face = plan._labelled[key]
        was_shape, was_reservation = plan._label_parts[key]
        for n, c in enumerate(plan.copper):
            if c is old:
                plan.copper[n] = op
                break
        occ.remove_copper([was_shape])
        occ.reservations.remove(was_reservation)
        occ.add_copper([shape])
        occ.reservations.append(reservation)
        plan._label_parts[key] = (shape, reservation)
        plan._labelled[key] = (op, own, face)
        step = next((st for st in plan.steps if st.item == key), None)
        if step is not None:
            at = plan.__dict__.setdefault("_label_at", {})
            was = at.get(key) or "%s %s" % (entry[3].name.lower(), {"centre": "MID"}.get(entry[5], entry[5].upper()))
            now = at[key] = "%s %s" % (side.name.lower(), word)
            step.say("label_moved", **{"from": was, "to": now, "by": list(because)})

    def _plan_copper(self, occ, ctx, intents, plan: Plan, progress):
        """Plan a batch of copper together, with the vias of the parts' grids lifted off the board: a grid is
        drawn by its own plan (`vias()`), which keeps each via off the copper planned before it, so a track
        declared across a grid is drawn and the grid goes round it, as it always has."""
        lifted = {}
        for ref, g in occ.items.items():
            if any(x.carried.startswith(FIELD_PREFIX) for x in g.shapes):
                lifted[ref] = g
                occ.items[ref] = dataclasses.replace(g, shapes=tuple(x for x in g.shapes
                                                                     if not x.carried.startswith(FIELD_PREFIX)))
        ctx.fields = {ref: [x for x in g.shapes if x.carried.startswith(FIELD_PREFIX)] for ref, g in lifted.items()}
        if lifted:
            occ._changed()
        try:
            self._plan_copper_batch(occ, ctx, intents, plan, progress)
        finally:
            if lifted:
                occ.items.update(lifted)
                occ._changed()
            ctx.fields = {}

    def _plan_copper_batch(self, occ, ctx, intents, plan: Plan, progress):
        """Plan a batch of copper together. Tracks are collected first and
        their crossings settled by priority; pours, zones, vias and fingers
        follow (a finger yields to every track already planned)."""
        if self._on_begin is not None and intents:
            self._on_begin(plan, {"kind": "begin", "item": "copper", "what": "copper", "rank": None, "of": None,
                                  "replaying": False, "n": len(plan.steps), "count": len(intents)})
        tracks, others = [], []
        deferred = []
        ctx.batch_tracks = []
        ctx.batch_ops = []
        for c in sorted(intents, key=lambda c: c.index):
            if c.key.startswith("finger"):
                deferred.append(c)          # a finger is cut by the tracks planned in this batch
                continue
            ctx.ops_at[c.index] = c.plan(ctx)
            ctx.batch_ops += ctx.ops_at[c.index]
            for op in ctx.ops_at[c.index]:
                (tracks if isinstance(op, Track) else others).append((c, op))
                if isinstance(op, Track):
                    ctx.batch_tracks.append(op)     # a later FreeSpot in this batch judges against it
        # A crossing the track that must yield may not bridge is not drawn at all: the yielding track is left out
        # whole, and the crossings are settled again without it.
        dropped, said = set(), []
        while True:
            live = [(c, op) for c, op in tracks if c.index not in dropped]
            entries = [(op, c.priority.rank, c.bridge) for c, op in live]
            refused = []
            ops, notes, findings = resolve_bridges(entries, ctx.fixed_tracks, self.via_drill, self.via_size,
                                                   self.settings.copper_bridge_half_gap, drop=refused,
                                                   labels=[c.key for c, _ in live], ids=[copper_id(c) for c, _ in live])
            fresh = {live[i][0].index for i in refused} - dropped
            if not fresh:
                break
            said += [f for f in findings if f not in said]
            dropped |= fresh
        if dropped:
            for c in intents:
                if c.index in dropped:
                    ctx.ops_at[c.index] = []
            gone = {id(op) for c, op in tracks if c.index in dropped}
            ctx.batch_tracks = [t for t in ctx.batch_tracks if id(t) not in gone]
            ctx.batch_ops = [o for o in ctx.batch_ops if id(o) not in gone]
            tracks = live
            others = [(c, op) for c, op in others if c.index not in dropped]
        plan.findings += said + [f for f in findings if f not in said] + list(ctx.notes)
        ctx.notes = Findings()
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
        owner = {id(op): c.key for c, op in others}
        owner_id = {id(op): copper_id(c) for c, op in others}
        net_key = {}
        for c, _ in tracks:
            net_key.setdefault(c.net, c.key)               # a track's pieces after bridging are told by their net
        track_ids = {}
        for c, _ in tracks:
            track_ids.setdefault(c.net, set()).add(copper_id(c))
        laid = {}
        for op in all_ops:
            key = owner.get(id(op)) or net_key.get(getattr(op, "net", None)) or next(iter(by_key), "")
            laid.setdefault(key, []).append(len(plan.copper))
            plan.copper.append(op)
            shape = _shape_of(op)
            if shape is None:
                continue
            # A zone is filled by KiCad, which pulls it back round other copper.
            skip_findings = isinstance(op, Zone)
            if not skip_findings:
                hits = occ.copper_conflicts(shape, check=True)       # a finding: KiCad's DRC epsilon, whatever placement uses
                # and this batch's own copper planned before it, which reaches the occupancy only
                # once the batch is done: a track of one net through a via of another, both planned
                # together. Tracks that cross are the bridging's to settle.
                for earlier, o in batch:
                    if o.net == shape.net or not shape.box.overlaps(o.box, gap=occ._copper_reach):
                        continue
                    if isinstance(op, Track) and isinstance(earlier, Track) and any(
                            segments_intersect(p1, p2, q1, q2) for p1, p2 in op.chords() for q1, q2 in earlier.chords()):
                        continue
                    why = occ._conflict(shape, o, None, exact=True, check=True)
                    if why:
                        hits.append(why)
                for hit in hits:
                    extra = {}
                    if isinstance(op, Track) and op.chamfer_cut:
                        extra["chamfer_at"] = [(op.start.x + op.end.x) / 2.0, (op.start.y + op.end.y) / 2.0]
                    elif isinstance(op, Track) and op.mid is not None:
                        extra["arc_radius_mm"] = arc_circle(op.start, op.mid, op.end)[2]
                        extra["arc_at"] = [op.mid.x, op.mid.y]
                    which = owner_id.get(id(op)) or (next(iter(track_ids[op.net])) if len(track_ids.get(op.net, ())) == 1 else None)
                    declared = next((c.declared for c in intents if which and copper_id(c) == which), {})
                    layer = getattr(op, "layer", None)
                    facts = {"key": which or "", "net": op.net, "word": type(op).__name__.lower(),
                             "layer": layer.name if layer is not None else "", "waypoints": declared.get("waypoints", 0),
                             "chamfer_hit": isinstance(op, Track) and bool(op.chamfer_cut),
                             "arc_hit": isinstance(op, Track) and op.mid is not None,
                             "chamfer_mm": declared.get("chamfer"), "radius_mm": declared.get("radius"),
                             "hit": hit.to_json(), **extra}
                    plan.findings.append(self._finding(C.COPPER_MEETS, facts))
            batch.append((op, shape))
            shapes.append(shape)
            if isinstance(op, Via):
                shapes.append(hole_shape("", op.at, op.drill, op.net, layers=frozenset(op.layers)))   # what is placed after keeps its holes clear
        occ.add_copper(shapes)
        if any(c.freedom.decided for c in intents):
            ctx.fixed_tracks += [op for op in ops if isinstance(op, Track)]     # a bridge's vias are not tracks
        for key, (prio, n, why, freedom) in by_key.items():
            made = (step_text.record("ops", n=n),) + ((step_text.record("in_pad_vias"),) if key.startswith("vias ") else ())
            step = Step(key, "copper", prio, None, 0.0, made, why, n, freedom=freedom, laid=tuple(laid.get(key, ())))
            plan.steps.append(step)
            if progress:
                progress(_fmt(step))
        for note in notes:
            plan.steps.append(Step("bridge", "copper", Priority.DEFAULT, None, 0.0, (note,), "", 0))
            if progress:
                progress("   bridge: " + step_text.render(note))

    def _rank(self, occ: Occupancy):
        """Every searched item's place in the queue, from what it is: the
        courtyard area it needs and its pin count, both against the rest of
        this board's searched items.

        Static. A rank says what a part IS, so it does not move as the board
        fills; what the board looks like when an item is reached is the
        tie-break's business, not this one's."""
        from .ranking import pin_count, rank_scores
        self._rank_score, self._rank_of, self._rank_note = {}, {}, {}
        self._waited, self._room = {}, {}
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
        scores = rank_scores(m, self.settings.rank_area_weight, self.settings.rank_pins_weight)
        order = sorted(scores, key=lambda k: (-scores[k], k))
        n = len(order)
        by_area = sorted(m, key=lambda k: -m[k][0])
        by_pins = sorted(m, key=lambda k: -m[k][1])
        for position, key in enumerate(order, start=1):
            area, pins = m[key]
            self._rank_score[key] = scores[key]
            self._rank_of[key] = position
            self._rank_note[key] = step_text.record("rank", rank=position, of=n, area_mm2=area, area_rank=by_area.index(key) + 1,
                                                  pins=pins, pins_rank=by_pins.index(key) + 1)

    def _slide(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, ideal: float, lo: float, hi: float,
               placement_at, where: dict, step: float | None = None, units: str = "mm") -> Step:
        """One degree of freedom: from `ideal` outward along [lo, hi], the
        first legal placement `placement_at(along)` gives. Round a rim or a
        ring the freedom is a bearing, so `step` and `units` are in degrees."""
        geom = occ._geometry(i.item)
        others = occ.obstacles(geom, occ.board_box.inflate(2.0))
        step = step if step is not None else max(i.step, self.settings.place_freedom_min_step)
        n = int((hi - lo) / step) + 1
        candidates = sorted({min(max(ideal + d * step * sgn, lo), hi) for d in range(n) for sgn in (1, -1)},
                            key=lambda a: (abs(a - ideal), a))
        accept = self._accept(i)
        past = (i.edge is not None or i.run is not None or i.rim == "rim") and i.clearance < self.keep_in
        # as drawn first; only where no slot takes the item so, again with its carried vias, and those
        # placed before it, giving way (giveway.py): the nearest slot where they do
        for giving in (False, True) if giveway_enabled(self.settings) else (False,):
            rejected: Counter = Counter()
            reasons: dict = {}
            last_why = None
            for along in candidates:
                p = placement_at(along)
                why = occ.legal_giving_way(i.item, p, clr, others=others, past_edge=past)[0] if giving else \
                    occ.legal(i.item, p, clr, others=others, past_edge=past)
                if why is None and accept is not None:
                    why = accept(p)
                    if why is not None:
                        key = why.bucket                # a rider, named: scan() counts it the same way
                        rejected[key] += 1
                        reasons.setdefault(key, why)
                        continue
                if why is None:
                    moved = abs(along - ideal)
                    notes = [step_text.record("where", where=where)]
                    if moved > 1e-9 and getattr(i, "toward", None) is not None:
                        notes.append(step_text.record("stopped_short", mm=moved, units=units, toward=i.toward.name.lower(),
                                                    why=None if last_why is None else last_why.to_json()))
                    elif moved > 1e-9:
                        first = next(iter(reasons.values()), None)
                        notes.append(step_text.record("slid", mm=moved, units=units, why=None if first is None else first.to_json()))
                    return self._step(i, p, moved, notes)
                last_why = why
                key = _reason_key(why)
                rejected[key] += 1
                reasons.setdefault(key, why)
        from . import suggest_facts
        plan.findings.append(self._finding(C.UNPLACED_SLIDE, dict(
            suggest_facts.unplaced_slide(self, i), where=where, counts=blame.counts_of(rejected),
            riders=[w.to_json() for k, w in reasons.items() if w.code is Code.RIDER])))
        return self._step(i, None, 0.0, unplaced=[w.to_json() for w in reasons.values()])

    def _slide_block(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec, ideal: float, lo: float, hi: float,
                     anchor_at, where: dict, step: float | None = None, units: str = "mm") -> Step:
        """_slide, for a block: a candidate is legal only once the whole
        block lays out from the anchor `anchor_at(along)` gives, so each is
        checked with layout_block rather than occ.legal on one item."""
        step = step if step is not None else max(i.step, self.settings.place_freedom_min_step)
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
                notes = [step_text.record("where", where=where)]
                if moved > 1e-9:
                    notes.append(step_text.record("slid", mm=moved, units=units))
                return self._commit_block(occ, spec, members, i, plan, notes)
            key = _reason_key(why)
            rejected[key] += 1
            reasons.setdefault(key, why)
        from . import suggest_facts
        plan.findings.append(self._finding(C.UNPLACED_SLIDE, dict(
            suggest_facts.unplaced_slide(self, i), where=where, counts=blame.counts_of(rejected), riders=[], edge="")))
        return self._commit_block(occ, spec, {}, i, plan, (), unplaced=[w.to_json() for w in reasons.values()])

    def _settle_block_along_edge(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        ideal = self._edge_slot(i, occ)
        box = occ.board_box
        lo, hi = (box.left, box.right) if i.edge in (Edge.NORTH, Edge.SOUTH) else (box.top, box.bottom)
        return self._slide_block(occ, i, plan, clr, spec, ideal, lo, hi,
                                 lambda along: edge_placement(occ, spec.anchor, i.edge, along, i.rotation, i.clearance, i.face),
                                 {"form": "edge", "edge": i.edge.name.lower()})

    def _settle_block_along_run(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        run = i.run
        fellows = [x for x in self._placements() if x.run is i.run and x.along is None
                   and not x.freedom.decided]
        k, n = _slot_of(fellows, i), max(len(fellows), 1)
        ideal = run.length * (k + 1) / (n + 1)
        shape = occ.board_shape or self._shaped()

        def at(along):
            rot = self.outward_rotation(spec.anchor, run.at(along)[1], i.face)[0] if i.outward else i.rotation
            return run_placement(occ, spec.anchor, shape, run, along, i.clearance, rot, i.face)
        return self._slide_block(occ, i, plan, clr, spec, ideal, 0.0, run.length, at,
                                 {"form": "run", "facing_deg": run.facing})

    def _settle_block_round_rim(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        disc = self._disc("the same place is OnEdge(board.edge(facing=...))")
        bore = i.rim == "bore"
        ideal = self._round_slot(i)
        r = max(disc.bore if bore else disc.radius, 1e-6)

        def at(angle):
            rot = self.outward_rotation(spec.anchor, angle + (180.0 if bore else 0.0), i.face)[0] if i.outward else i.rotation
            return disc_placement(occ, spec.anchor, disc, angle, i.clearance, rot, i.face, bore=bore)
        return self._slide_block(occ, i, plan, clr, spec, ideal, ideal - 180.0, ideal + 180.0, at,
                                 {"form": "rim", "word": "bore" if bore else "rim"},
                                 step=math.degrees(max(i.step, self.settings.place_freedom_min_step) / r), units="deg")

    def _settle_block_round_ring(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        centre = self.centre if i.about is None else _locate(self, occ, i.about)
        ideal = self._round_slot(i)
        r = max(float(i.radius_at), 1e-6)

        def at(angle):
            return box_centered_placement(occ, spec.anchor, polar_point(centre, angle, r), i.rotation, i.face)
        return self._slide_block(occ, i, plan, clr, spec, ideal, ideal - 180.0, ideal + 180.0, at,
                                 {"form": "ring", "radius_mm": r}, step=math.degrees(max(i.step, self.settings.place_freedom_min_step) / r), units="deg")

    def _settle_block_along_spoke(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec) -> Step:
        centre = self.centre if i.about is None else _locate(self, occ, i.about)
        if i.band is not None:
            lo, hi = i.band
        elif isinstance(self._shape, Disc) and centre == self._shape.centre:
            lo, hi = self._shape.bore + self.keep_in, self._shape.radius - self.keep_in
        else:
            box = occ.board_box
            lo, hi = 0.0, max(box.width, box.height)
        ideal = (lo + hi) / 2.0

        def at(r):
            return box_centered_placement(occ, spec.anchor, polar_point(centre, i.angle, r), i.rotation, i.face)
        return self._slide_block(occ, i, plan, clr, spec, ideal, lo, hi, at, {"form": "spoke", "angle_deg": i.angle})

    def _settle_block_along_line(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, spec, placed: set) -> Step:
        axis = "x" if i.pin_x is not None else "y"
        pinned = _coord(self, occ, i.pin_x if axis == "x" else i.pin_y, axis)
        fellows = [o for o in self._placements() if (o.pin_x if axis == "x" else o.pin_y) is not None
                   and (o.pin_x if axis == "x" else o.pin_y) == (i.pin_x if axis == "x" else i.pin_y)]
        k, n = _slot_of(fellows, i), len(fellows)
        box = occ.board_box
        lo, hi = (box.top, box.bottom) if axis == "x" else (box.left, box.right)
        lo, hi = lo + self.keep_in, hi - self.keep_in
        ideal = lo + (hi - lo) * (k + 1) / (n + 1)
        targets = self._targets(spec.anchor, occ, placed) if i.toward is None else None
        seeded = {}
        if i.toward is not None:
            ideal = hi if i.toward in (Edge.SOUTH, Edge.EAST) else lo
            seeded = {"toward": i.toward.name.lower()}
        elif targets:
            hint = self._seed_hint(spec.anchor, occ, targets, i.rotation, i.face)
            anchor = hint.location if i.pinned_by == "at" else occ.body_box(spec.anchor, hint).center
            ideal = min(max(anchor.y if axis == "x" else anchor.x, lo), hi)
            seeded = {"across": True}

        def at(along):
            point = Location(pinned, along) if axis == "x" else Location(along, pinned)
            if i.pinned_by == "at":
                return Placement(point, i.rotation, i.face)
            return box_centered_placement(occ, spec.anchor, point, i.rotation, i.face)
        return self._slide_block(occ, i, plan, clr, spec, ideal, lo, hi, at, {"form": "line", "axis": axis, "at_mm": pinned, **seeded})

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
        k, n = _slot_of(fellows, i), len(fellows)
        box = occ.board_box
        lo, hi = (box.top, box.bottom) if axis == "x" else (box.left, box.right)
        lo, hi = lo + self.keep_in, hi - self.keep_in
        ideal = lo + (hi - lo) * (k + 1) / (n + 1)
        targets = self._targets(i.item, occ, placed) if i.toward is None else None
        seeded = {}
        if i.toward is not None:
            ideal = hi if i.toward in (Edge.SOUTH, Edge.EAST) else lo
            seeded = {"toward": i.toward.name.lower()}
        elif targets:
            hint = self._seed_hint(i.item, occ, targets, i.rotation, i.face)
            anchor = hint.location if (i.pinned_by == "at" and i.kind != "cell") else occ.body_box(i.item, hint).center
            ideal = min(max(anchor.y if axis == "x" else anchor.x, lo), hi)
            seeded = {"across": True}

        def at(along):
            point = Location(pinned, along) if axis == "x" else Location(along, pinned)
            if i.pinned_by == "at" and i.kind != "cell":
                return Placement(point, i.rotation, i.face)
            return box_centered_placement(occ, i.item, point, i.rotation, i.face)
        return self._slide(occ, i, plan, clr, ideal, lo, hi, at, {"form": "line", "axis": axis, "at_mm": pinned, **seeded})

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
        k, n = _slot_of(fellows, i), len(fellows)
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
                           {"form": "edge", "edge": i.edge.name.lower()})

    def _settle_along_run(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides along its run from its
        slot, its reach at the keep-in, turned to the way the board faces
        wherever it lands."""
        run = i.run
        fellows = [x for x in self._placements() if x.run is i.run and x.along is None
                   and not x.freedom.decided]
        k, n = _slot_of(fellows, i), max(len(fellows), 1)
        ideal = run.length * (k + 1) / (n + 1)
        shape = occ.board_shape or self._shaped()

        def at(along):
            rot = self.outward_rotation(i.item, run.at(along)[1], i.face)[0] if i.outward else i.rotation
            return run_placement(occ, i.item, shape, run, along, i.clearance, rot, i.face)
        return self._slide(occ, i, plan, clr, ideal, 0.0, run.length, at,
                           {"form": "run", "facing_deg": run.facing})

    def _round_slot(self, i: PlaceIntent) -> float:
        """Where a free item on a rim or a ring would like to be: everything
        sharing that circle divides the turn evenly, the k-th of n at k/n of
        it from the top, so one alone sits at the top."""
        fellows = [x for x in self._placements() if x.angle is None
                   and (x.rim, x.radius_at, x.about) == (i.rim, i.radius_at, i.about)
                   and not x.freedom.decided]
        k, n = _slot_of(fellows, i), max(len(fellows), 1)
        return 360.0 * k / n

    def _settle_round_rim(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides round the rim (or the bore)
        from its slot, its reach at the keep-in, facing out wherever it lands."""
        disc = self._disc("the same place is OnEdge(board.edge(facing=...))")
        bore = i.rim == "bore"
        ideal = self._round_slot(i)
        r = max(disc.bore if bore else disc.radius, 1e-6)

        def at(angle):
            rot = self.outward_rotation(i.item, angle + (180.0 if bore else 0.0), i.face)[0] if i.outward else i.rotation
            return disc_placement(occ, i.item, disc, angle, i.clearance, rot, i.face, bore=bore)
        return self._slide(occ, i, plan, clr, ideal, ideal - 180.0, ideal + 180.0, at,
                           {"form": "rim", "word": "bore" if bore else "rim"},
                           step=math.degrees(max(i.step, self.settings.place_freedom_min_step) / r), units="deg")

    def _settle_round_ring(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr) -> Step:
        """One degree of freedom: the item slides round the ring it was given."""
        centre = self.centre if i.about is None else _locate(self, occ, i.about)
        ideal = self._round_slot(i)
        r = max(float(i.radius_at), 1e-6)

        def at(angle):
            return box_centered_placement(occ, i.item, polar_point(centre, angle, r), i.rotation, i.face)
        return self._slide(occ, i, plan, clr, ideal, ideal - 180.0, ideal + 180.0, at,
                           {"form": "ring", "radius_mm": r}, step=math.degrees(max(i.step, self.settings.place_freedom_min_step) / r), units="deg")

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
        return self._slide(occ, i, plan, clr, ideal, lo, hi, at, {"form": "spoke", "angle_deg": i.angle})

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
        if entry.arrangement:
            # offers are read off the base cell: the gate may already have arranged `i`. Tested before the digest, which
            # cannot be taken in an arrangement the cell does not offer; an item that is no longer a cell offers none
            offered = self._offered(self.geometry.cells.get(i.key))
            if entry.arrangement not in offered:
                plan.findings.append(self._arrangement_missing(i.key, [entry.arrangement], ["default", *offered], source="lock"))
                self._lock_notes[i.key] = step_text.record("lock_released", reason={"form": "arrangement_gone",
                                                                                     "id": entry.arrangement})
                return None, None
        base = self._arranged(i, "")        # the declaration as the script says it, whatever the gate made of it
        if entry.declaration != _lock.declaration_digest(self, base, arrangement=entry.arrangement) and \
                entry.declaration != _lock.declaration_digest(self, base, ordered=False, arrangement=entry.arrangement):
            self._lock_notes[i.key] = step_text.record("lock_released", reason={"form": "declaration_changed"})
            return None, None
        spot, why = _lock.placement_of(entry, occ)
        if spot is None:
            self._lock_notes[i.key] = step_text.record("lock_released", reason=why)
            return None, None
        return spot, spot

    def _settle_locked(self, occ: Occupancy, i, plan: Plan, clr):
        """A locked part or cell: at its locked spot when that is legal, else
        at the nearest legal spot round it, saying how far it drifted; None
        when there is no entry or it was released."""
        spot, _ = self._lock_spot(occ, i, plan)
        if spot is None:
            return None
        i = self._arranged(i, spot.arrangement)        # a cell is laid in the arrangement its entry holds
        held = scan(occ, i.item, spot, 0.0, i.step, (spot.rotation,), clr, accept=self._accept(i))
        self._lock_held.add(i.key)
        if held.chosen is not None:
            self._lock_marks[i.key] = "held"
            return self._step(i, held.chosen, 0.0, [step_text.record("lock_held")])
        body = occ._geometry(i.item).body
        radius = max(i.radius, body.width, body.height)
        drift = scan(occ, i.item, spot, radius, i.step, (spot.rotation,), clr, accept=self._accept(i))
        if drift.chosen is None:
            self._lock_held.discard(i.key)
            self._lock_notes[i.key] = step_text.record("lock_released", reason={"form": "no_spot_near", "radius_mm": radius})
            return None
        d = drift.chosen.location.distance(spot.location)
        first = next(iter(held.reasons.values()), None)
        self._lock_marks[i.key] = "drifted"
        return self._step(i, drift.chosen, d, [step_text.record("lock_drifted", mm=d, why=None if first is None else first.to_json())])

    def _pick(self, i):
        """An explore variant's draw for a focused item, else None (the best)."""
        ex = getattr(self, "_explore", None)
        if ex is None or i.key not in ex.focus:
            return None
        if self._collect_into is not None:          # `_scan_arrangements` draws over every arrangement: a scan hands it its
            return lambda cands: (self._collect_into.extend(cands), cands[0])[1]      # sorted candidates and keeps its best
        import random as _random
        from .explore import draw
        rng = _random.Random("%d:%s" % (ex.seed, i.key))
        s = self.settings
        return lambda cands: draw(cands, rng, s.explore_spot_slack, s.explore_rank_power)

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

    def _no_pocket_note(self, occ: Occupancy, i: PlaceIntent) -> dict | None:
        """A search cannot succeed where no free rectangle holds the item's
        envelope at any of its rotations: the facts that say so instead of scanning, or None."""
        if occ.board_box is None:
            return None
        envs = []
        for face in self._faces_of(i):
            for rot in (self._turns(i)):
                env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, face))
                if pockets(occ, env.width, env.height, face, item=i.item, vias=False, step=max(i.step, self.settings.place_pocket_step), limit=1, covered=True):
                    return None
                envs.append(env)
        env = envs[0]
        return {"variant": "any_rotation", "w_mm": env.width, "h_mm": env.height, "face": self._face_text(i)}

    def _no_place_report(self, occ: Occupancy, obj, step) -> str:
        """Why a critical item stopped the run: its envelope, the reason, and
        the biggest free rectangles on its face, so the reader can see what
        would have to move."""
        item = obj.item.anchor if obj.kind == "block" else obj.item
        env = occ.body_box(item, Placement(Location(0, 0), obj.rotation, obj.face))
        free = [p for face in self._faces_of(obj) for p in
                pockets(occ, 2.0, 2.0, face, item=item, step=self.settings.place_pocket_step, limit=4)][:4]
        rects = "; ".join("%.1f x %.1f at (%.1f, %.1f)" % (p.box.width, p.box.height, p.box.center.x, p.box.center.y)
                          for p in free) or "none"
        return ("%s (required) found no place for its %.1f x %.1f envelope on the %s face: %s. "
                "Biggest free rectangles there now: %s. The board as it stood is written; nothing was placed after it."
                % (obj.key, env.width, env.height, self._face_text(obj), step_text.unplaced_text(step.unplaced), rects))

    def _next_to_place(self, pending: list, occ: Occupancy, placed: set):
        """Which searched item goes next: the script's tier first, then the
        freedoms its place leaves (a slide before an item searched in two),
        or with `place.order = "room"` the band of legal spots its declaration
        leaves it (room.py), then the rank (what the item IS), then the
        strongest pull toward what is already placed, then the largest.

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
        waits = self._link_waits(pending, {k: m[1] for k, m in measured.items()}, occ)
        for k, partner in waits.items():
            self._waited.setdefault(k, partner)
        free = [o for o in ready if o.key not in waits] or ready
        scored = sorted(((measured[o.key], o) for o in free),
                        key=lambda m: (-m[1].priority.rank, self._order_of(m[1], occ), -m[0][0], -m[0][1],
                                       -m[0][2], m[1].key))
        (score, pull, area), obj = scored[0]
        # A ranked item's step is tagged with its rank already; only an unranked
        # one needs saying why it went next.
        why = [] if obj.key in self._rank_note else [step_text.record("next_largest", area_mm2=area)]
        if self.settings.place_order == "room":
            why.append(self._room_note(obj, occ))
        elif getattr(obj, "freedoms", 2) == 1 and any(
                o.priority is obj.priority and getattr(o, "freedoms", 2) > 1 for _, o in scored):
            why.append(step_text.record("one_freedom"))
        if obj.key in self._waited:
            why.append(step_text.record("waited_for", partner=self._waited[obj.key]))
        return obj, why

    def _room_of(self, obj, occ: Occupancy) -> dict:
        """What room an item has (room.measure), taken the first time it is asked: the board as it stands when the first
        searched item is reached, with the firm items in. An item that is no part, cell or block has the whole board."""
        if obj.key not in self._room:
            from . import room
            self._room[obj.key] = room.measure(self, occ, obj, self.settings.place_room_pitch) \
                if isinstance(obj, PlaceIntent) else {"form": "board", "spots": float("inf")}
        return self._room[obj.key]

    def _order_of(self, obj, occ: Occupancy) -> int:
        """What an item's turn in its tier is ordered by: the freedoms its place leaves, or, with `place.order = "room"`,
        the band its room falls in."""
        if self.settings.place_order != "room":
            return getattr(obj, "freedoms", 2)
        from . import room
        spots = self._room_of(obj, occ)["spots"]
        return room.level(spots, self.settings.place_room_ratio) if spots != float("inf") else 10 ** 6

    def _room_note(self, obj, occ: Occupancy) -> dict:
        """The note that says how much room an item had when it went."""
        facts = self._room_of(obj, occ)
        spots = facts["spots"]
        return step_text.record("room", form=facts["form"], spots=None if spots == float("inf") else round(spots, 1),
                                cut_mm2=None if "cut_mm2" not in facts else round(facts["cut_mm2"], 1),
                                level=self._order_of(obj, occ), pitch_mm=self.settings.place_room_pitch)

    def _link_waits(self, pending: list, pull: dict, occ: Occupancy) -> dict:
        """{item key: the linked partner it waits for}, over declared links
        between two pending items: the one with less pull toward what is
        placed waits. Level pull waits for nothing, and nothing waits for a
        partner of a lower priority tier, and nothing with fewer freedoms waits
        for a partner with more: the wait orders items within a tier and a
        number of freedoms, never across one."""
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
                if (fast.priority.rank >= slow.priority.rank
                        and self._order_of(fast, occ) <= self._order_of(slow, occ)):
                    waits.setdefault(slow.key, fast.key)
        return waits

    def _commit_block(self, occ: Occupancy, spec, members: dict, i: PlaceIntent, plan: Plan, notes=(),
                      unplaced: list | None = None) -> Step:
        """A block's members once `members` is known (possibly {}: nothing
        legal). The satellites commit here; the anchor commits in the outer
        resolve loop, from the step this returns, the same as any item's."""
        from .placer import slide_note
        slid = {sat.inst: slide_note(occ, spec, members, k) for k, (sat, _) in enumerate(spec.satellites)}
        for fp in spec.members:
            if fp.inst in members and fp is not spec.anchor:
                plan._items[fp.inst] = fp
                member_notes = (step_text.record("member_of", block=i.key),) + tuple(slid[fp.inst] or ())
                plan.steps.append(Step(fp.inst, "part", i.priority, members[fp.inst], 0.0, member_notes))
                occ.commit(fp, members[fp.inst])
        plan._items[spec.anchor.inst] = spec.anchor
        anchor_at = members.get(spec.anchor.inst)
        plan.steps.append(Step(spec.anchor.inst, "part", i.priority, anchor_at, 0.0, (step_text.record("anchor_of", block=i.key),)))
        return self._step(i, anchor_at, 0.0, notes, unplaced=unplaced)

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
                rot = self.outward_rotation(spec.anchor, i.run.at(along)[1], i.face)[0] if i.rotation is None else i.rotation
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
                from . import suggest_facts
                plan.findings.append(self._finding(C.FIXED_PART, dict(suggest_facts.fixed_part(self, i), why=why.to_json())))
                members = {spec.anchor.inst: anchor}
            return self._commit_block(occ, spec, members, i, plan, [step_text.record("refused", why=why.to_json())] if why else ())
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
                    self._lock_notes[i.key] = step_text.record("lock_released", reason={"form": "no_spot_round"})
        targets = self._targets(spec.anchor, occ, placed)
        current = occ._geometry(spec.anchor).reference
        unplaced = None
        if locked is not None:
            self._lock_held.add(i.key)
            _, anchor, members = locked
            d = anchor.location.distance(spot.location)
            self._lock_marks[i.key] = "held" if d < 1e-9 else "drifted"
            notes = [step_text.record("block", members=len(members)),
                     step_text.record("lock_held") if d < 1e-9 else step_text.record("lock_drifted", mm=d)]
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
                from . import suggest_facts
                facts = dict({"item": i.key, "variant": "alone", "turns": [[r, w.to_json()] for r, w in alone]},
                             **suggest_facts.structure_facts(self, i))
                plan.findings.append(self._finding(C.UNPLACED_BLOCK, facts))
                members = {}
                notes, unplaced = [], [{"form": "turns", "turns": facts["turns"]}]
            elif best is None:
                plan.findings.append(self._finding(C.UNPLACED_BLOCK, {
                    "item": i.key, "variant": "scan", "radius_mm": radius,
                    "at": [hint.location.x, hint.location.y], "counts": blame.counts_of(rejected),
                    }))
                members = {}
                notes, unplaced = [], []
            else:
                _, anchor, members = best
                moved = anchor.location.distance(hint.location)
                notes = [step_text.record("block", members=len(members))]
                if moved > 0:
                    first = next(iter(reasons.values()), None)
                    notes.append(step_text.record("moved_off_hint", mm=moved, why=None if first is None else first.to_json()))
        return self._commit_block(occ, spec, members, i, plan, notes, unplaced=unplaced)

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
            held = [i for i in left if not isinstance(now[i], Refusal)]
            got.update(now)
            if not held:
                break
            for i in held:
                drawn += list(now[i][0]) + list(now[i][1])
            left = [i for i in left if i not in held]
        intents = []
        # after the declarations' indexes, which an arrangement's left-out copper does not shorten: ctx.ops_at is keyed by index
        base = max((c.index for c in self._copper), default=-1) + 1
        for i, e in enumerate(entries):
            key = keys[i]
            if isinstance(got[i], Refusal):
                plan.adopted[key] = {"dropped": got[i].to_json()}
                plan.findings.append(self._finding(C.ROUTE_DROPPED, {"key": key, "why": got[i].to_json()}))
                continue
            plan.adopted[key] = "held"
            ops = list(got[i][0]) + list(got[i][1])
            intents.append(CopperIntent("adopted %s" % key, e.net, Priority.DEFAULT, lambda ctx, ops=ops: ops,
                                        (), "kept from a route", base + len(intents)))
        if intents:
            self._plan_copper(occ, ctx, intents, plan, progress)

    def _block_alone(self, spec, rotations, face, clearance) -> list | None:
        """None when the block can be laid out on its own - on an empty board,
        nothing else placed - at some rotation it may take; else why not, at
        each (a list of [rotation, its Refusal]). A block its own satellites cannot fit round fails here in a
        moment rather than after a scan of the whole board."""
        from .placer import layout_block
        key = (spec.key, tuple(rotations), face)
        cache = self.__dict__.setdefault("_block_alone_cache", {})
        if key not in cache:
            bare = self._bare_occupancy(fresh=True)
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
                why.append([rot, reason])
            cache[key] = why
        return cache[key]

    def _turned_rotation(self, occ, i: PlaceIntent) -> float:
        """The rotation a `Turned` or a `Parallel` settles to, read off `occ` as it stands:
        the part's own plus its degrees, the turn that lies the item's x axis along the line, or
        the turn that faces its pads toward another's."""
        t = i.turned
        if isinstance(t, Facing):
            return self._toward_rotation(occ, i)
        if isinstance(t, Parallel):
            a, b = _locate(self, occ, t.a), _locate(self, occ, t.b)
            return parallel_rotation(a, b, i.face, t.degrees)
        ref = self._pad_ref(t.part)[0]
        return (occ.items[ref].reference.rotation + t.degrees) % 360.0

    def _firm_past_edge(self, i: PlaceIntent) -> bool:
        """Whether a firm item's body may cross the edge margin: one declared
        on an edge, a run or the rim closer than the keep-in."""
        return ((i.edge is not None or i.run is not None or i.rim == "rim")
                and i.row_of is None and i.clearance < self.keep_in)

    def _firm_placement(self, occ: Occupancy, plan: Plan, i: PlaceIntent) -> tuple:
        """(placement, note) where a firm declaration puts its item, read
        against `occ` as it stands: the item is neither judged nor committed. The note, a step_text record or None, says which
        pad a net named."""
        chose = None
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
            # a PadRef's edge= in the point stands the pad off by its own size, as it stands at this rotation
            land = None if i.pin_land is None else self._pad_land(PadRef(Part(i.item.inst), i.pin, land=i.pin_land))
            size = pad_box_at(occ, i.item, i.pin, i.rotation, i.face, land)
            p = pad_anchored_placement(occ, i.item, i.pin, _locate(self, occ, i.center, (size.width, size.height)),
                                       i.rotation, i.face, land)
            # A net names one pad here, the first of however many carry it.
            # Say which, because an offset the script measured has to come
            # off the same pad, and from outside nothing shows which it was.
            kind, value = pad_key(i.pin) if not isinstance(i.pin, Mid) else (None, None)
            if kind == "net":
                same = i.item.pads_on(value)
                if len(same) > 1:
                    chose = step_text.record("chose_pad", net=value, count=len(same), ref=i.item.ref, pad=i.item.pad(i.pin).number)
        elif i.center is not None:
            p = box_centered_placement(occ, i.item, _locate(self, occ, i.center), i.rotation, i.face)
        elif i.run is not None:
            along = _run_along(self, occ, i)
            # a numeric along= turns the item at declaration; a reference's length along
            # the run is not known until now, so its outward turn waits for it too
            rot = self.outward_rotation(i.item, i.run.at(along)[1], i.face)[0] if i.rotation is None else i.rotation
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
        the first rider that is not legal. A cell rider is laid as its one pinned
        arrangement (`_pinned`); the riders `_riders_dropped` names are left out."""
        view = _Riding(occ)
        group = view.move(i.item, at)
        out = []
        dropped = self._riders_dropped(i)
        for r in self._ride_groups[i.key]:
            if r.key in dropped:
                continue                                # unplaced by _settle_riders
            r = self._pinned(r)[0]
            if isinstance(r.along, _RowSlot):
                self._reset_rows(r.along.row)
            if r.turned is not None:
                r = dataclasses.replace(r, rotation=self._turned_rotation(view, r))
            p, chose = self._firm_placement(view, plan, r)
            others = obstacles.get(r.key) if obstacles is not None else None
            # the vias the group carries are not what a rider is judged against: they give way to it when it is
            # committed (occupancy._commit), as to any item placed after them
            # the group's own shapes stand where the script put them: silk at the board's clearance
            with occ.silk_as_drawn():
                in_group = occ.legal(r.item, p, self.clearance, others=ShapeIndex([x for x in group if not x.carried]),
                                     board=False)
            # on the board its carried vias, and those placed before it, may give way (giveway.py)
            on_board = occ.legal_giving_way(r.item, p, self.clearance, others=others,
                                            past_edge=self._firm_past_edge(r), by_corners=True)[0] \
                if board and not in_group else None
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

    def _riders_alone(self, occ: Occupancy, plan: Plan, i: PlaceIntent) -> list | None:
        """None when `i`'s riders may fit round it at some turn its search
        may take, else why not, at each (a list of [rotation, the rider's Refusal]): a rider that meets `i` or another
        rider wherever `i` goes fails here in a moment rather than after a
        scan of the whole board, as a block's satellites do. Only for an item
        searched at a known set of turns whose riders move exactly as it
        does; else None, and the search finds out. A cell is alone only when it is in every arrangement its search may take; each
        refusal is then [rotation, Refusal, the arrangement it came from ("" the default)]."""
        if i.outward or i.tangent is not None or self._locked(i) is not None:
            return None             # turned by where it lands, or by its lock: any turn at all
        if self._pinned(i)[1] is not None:
            return None             # an arrangement it does not offer: _settle says so
        turns = set(self._turns(i)) | {i.rotation, (i.rotation + 90) % 360}      # a pocket's two as well
        at = occ.board_box.center if occ.board_box is not None else Location(0.0, 0.0)
        why = []
        for ident in self._arrangement_ids(i):
            j = self._arranged(i, ident)
            for face in self._faces_of(j):
                for rot in sorted(turns):
                    laid = self._ride_turn(occ, plan, j, Placement(at, rot, face))
                    bad = None if laid is None else next(((r, g) for r, _, g in laid[1] if g), None)
                    if bad is None:
                        return None
                    why.append([rot, Refusal(Code.RIDER, key=bad[0].key, why=bad[1]), ident])
        return why

    def _rider_check(self, occ: Occupancy, plan: Plan, i: PlaceIntent):
        """What a search asks of each candidate of an item that has riders:
        None when every rider is legal with the item there, else "rider
        <key>: why". The board as the search sees it is gathered once, and
        the riders are laid once per turn of the item wherever they move
        exactly as it does: a candidate then shifts them and asks the board."""
        obstacles = {r.key: occ.obstacles(occ._geometry(r.item)) for r in (self._pinned(r)[0] for r in self._ride_groups[i.key])}
        turns = {}

        def accept(at: Placement):
            turn = (at.rotation, at.face)
            if turn not in turns:
                turns[turn] = self._ride_turn(occ, plan, i, at)
            laid = turns[turn]
            if laid is None:
                r, _, _, on_board, in_group = self._ride(occ, plan, i, at, obstacles)[-1]
                why = on_board or in_group
                return Refusal(Code.RIDER, key=r.key, why=why) if why else None
            base, riders = laid
            dx, dy = at.location.x - base.location.x, at.location.y - base.location.y
            for r, p, in_group in riders:
                p = Placement(Location(round(p.location.x + dx, 6), round(p.location.y + dy, 6)), p.rotation, p.face)
                why = in_group or occ.legal_giving_way(r.item, p, self.clearance, others=obstacles[r.key],
                                                       past_edge=self._firm_past_edge(r), by_corners=True)[0]
                if why:
                    return Refusal(Code.RIDER, key=r.key, why=why)
            return None
        return accept

    def _accept(self, i: PlaceIntent):
        """The rider check for the item being settled now, else None: one for each arrangement the search stands it in, the
        riders laid against the cell as that arrangement stands it."""
        riding = self.__dict__.get("_riding")
        if riding is None or riding[0] != i.key:
            return None
        _, occ, plan, checks = riding
        ident = getattr(i.item, "arrangement", "")
        if ident not in checks:
            checks[ident] = self._rider_check(occ, plan, i)
        return checks[ident]

    def _riders_dropped(self, i: PlaceIntent) -> dict:
        """{key: the ids it offers, or None} of `i`'s riders that are not laid: a cell rider whose `arrangements=` names an id it
        does not offer (its offered ids), and every rider that rides one of those, down the chain (None)."""
        dropped = {}
        for r in self._ride_groups[i.key]:              # in ride order: a rider comes after the one it rides
            offered = self._pinned(r)[1]
            if offered is not None:
                dropped[r.key] = offered
            elif self._rider_of.get(r.key) in dropped:
                dropped[r.key] = None
        return dropped

    def _settle_riders(self, occ: Occupancy, i: PlaceIntent, plan: Plan, step: Step) -> None:
        """Commit `i`'s riders where they go with `i` at its step's placement,
        a step each in ride order; or, with `i` unplaced, an unplaced step and
        a finding each. A cell rider whose `arrangements=` names an id it does
        not offer is unplaced with `arrangement.missing` either way, and the
        riders that ride it are unplaced as riders of an unplaced item."""
        for r in self._ride_groups[i.key]:
            plan._items[r.key] = r.item
        dropped = self._riders_dropped(i)
        laid = {}
        if step.placement is not None:
            stood = self._arranged(i, step.placement.arrangement)      # the riders go with the cell as its arrangement stands it
            laid = self._ride(occ, plan, stood, step.placement, None, stop=False)
            if any([self._labels_give_way(occ, plan, r.item, p) for r, p, *_ in laid]):
                laid = self._ride(occ, plan, stood, step.placement, None, stop=False)
            laid = {r.key: (r, p, chose, on_board, in_group) for r, p, chose, on_board, in_group in laid}
        for r in self._ride_groups[i.key]:
            if dropped.get(r.key) is not None:
                plan.steps.append(self._arrangement_gone(r, dropped[r.key], plan))
                continue
            if r.key not in laid:
                facts = {"item": r.key, "variant": "rode", "rider_of": self._rider_of[r.key]}
                plan.findings.append(self._finding(C.UNPLACED_RIDES, facts))
                plan.steps.append(self._step(r, None, 0.0, unplaced=[{"form": "rides", "rider_of": facts["rider_of"]}]))
                continue
            r, p, chose, on_board, in_group = laid[r.key]
            why = on_board or in_group
            if why:
                from . import suggest_facts
                plan.findings.append(self._finding(C.FIXED_PART, dict(suggest_facts.fixed_part(self, r), why=why.to_json())))
            notes = [step_text.record("rides", of=self._rider_of[r.key])] + ([step_text.record("required")] if r.required else [])
            notes += [x for x in (chose, step_text.record("refused", why=why.to_json()) if why else None,
                                  step_text.record(r.faces_note) if r.faces_note else None) if x]
            step = self._step(r, p, 0.0, notes)
            plan.steps.append(step)
            occ.commit(r.item, step.placement)          # its step's placement names the arrangement the rider is pinned to
            self._record_arranged_thinned(occ, plan, r, step.placement)

    def _band_frame(self, occ: Occupancy, i: PlaceIntent, placed, hint: Placement | None) -> tuple:
        """(hint, band, turns, within) for a search of `i`: its radial band and the spot turns that
        go with it, `hint` brought into the band, and the filter that keeps the scan's grid to it."""
        band = self._band_of(occ, i, placed)
        bt = self._spot_turns(occ, i, placed, band)
        within = None
        if band is not None:
            hint = self._band_hint(i, band, hint)
            slack = max((math.hypot(dx, dy) for s in self._spots_of(occ, i, placed, band, bt)
                         for dx, dy in s.offset.values()), default=0.0)
            within = lambda x, y, c=band[0], lo=band[1] - slack, hi=band[2] + slack: lo <= math.hypot(x - c.x, y - c.y) <= hi
        return hint, band, bt, within

    def _settle(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set = frozenset(),
                solve: bool = True, look: bool = True) -> Step:
        if i.kind == "block":
            return self._settle_block(occ, i, plan, placed)
        i, gone = self._gate(occ, i, plan)
        if gone is not None:
            return gone
        clr = self.clearance
        push_sources = self._reserve_pushes(occ, plan, i)
        if i.freedom.decided:
            if len(self._arrangement_ids(i)) > 1:
                return self._settle_firm_arranged(occ, i, plan, placed, clr, push_sources)
            p, chose = self._firm_placement(occ, plan, i)
            if self._on_begin is not None:
                self._phase(Stage.DECLARED, hint=[round(p.location.x, 3), round(p.location.y, 3)])
            self._labels_give_way(occ, plan, i.item, p)     # a user's label moves, the part does not
            why = self._firm_judged(occ, i, p, clr)[0]
            if why:
                from . import suggest_facts
                plan.findings.append(self._finding(C.FIXED_PART, dict(suggest_facts.fixed_part(self, i), why=why.to_json())))
            return self._step(i, p, 0.0, [x for x in (chose, step_text.record("refused", why=why.to_json()) if why else None) if x])
        if i.turns_on_point:
            return self._settle_turns_on_point(occ, i, plan, placed, clr, push_sources)
        if i.run is not None:
            return self._first_legal(occ, i, plan, lambda j: self._settle_along_run(occ, j, plan, clr))
        if i.rim is not None:
            return self._first_legal(occ, i, plan, lambda j: self._settle_round_rim(occ, j, plan, clr))
        if i.radius_at is not None:
            return self._first_legal(occ, i, plan, lambda j: self._settle_round_ring(occ, j, plan, clr))
        if i.angle is not None:
            return self._first_legal(occ, i, plan, lambda j: self._settle_along_spoke(occ, j, plan, clr))
        if i.edge is not None:
            return self._first_legal(occ, i, plan, lambda j: self._settle_along_edge(occ, j, plan, clr))
        if i.pin_x is not None or i.pin_y is not None:
            return self._first_legal(occ, i, plan, lambda j: self._settle_along_line(occ, j, plan, clr, placed))
        locked = self._settle_locked(occ, i, plan, clr)
        if locked is not None:
            return locked
        if self._on_begin is not None:
            self._phase(Stage.SEEDING)
        targets = self._targets(i.item, occ, placed)
        seeded, seeded_nets = [], []
        solved = None
        if solve and i.near is None and self.settings.solve_enabled:
            solved = self._global_hints(occ, placed, plan).get(i.key)
        if i.near is not None:
            hint = Placement(_locate(self, occ, i.near), i.rotation, i.face)
        elif solved is not None:
            hint = Placement(solved, i.rotation, i.face)
            seeded = [step_text.record("seeded_by_solve")]
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
            seeded, seeded_nets = [step_text.record("seeded", nets=nets)], nets
            for n in nets:
                plan.seeded_by_net[n] += 1
        else:
            hint = None
        hint, band, bt, within = self._band_frame(occ, i, placed, hint)
        # A board still finding its own frame (board.rect(fit=True), before anything is placed)
        # has no centre or outline to search wide against yet: a push there falls back to a pocket,
        # the same as an unpushed item with nothing else to seed it.
        wide_push = bool(push_sources) and not self._fit and self._outline is not None
        wide_tangent = hint is None and bt is not None and not self._fit and self._outline is not None
        if wide_tangent:
            hint = Placement(bt.centre, i.rotation, i.face)
            seeded = "searched from the centre its turns are taken about"
        elif hint is None and wide_push:
            hint = Placement(self.centre, i.rotation, i.face)
            seeded = "searched wide for its push" if len(push_sources) == 1 else "searched wide for its pushes"
        elif hint is None:
            return self._first_legal(occ, i, plan, lambda j: self._settle_in_pocket(occ, j, plan, clr))
        reseed = targets if i.near is None and solved is None else None
        scanned = self._scan_arrangements(occ, i, plan, placed, self._arrangement_ids(i), targets=targets,
                                          push_sources=push_sources, hint=hint, band=band, bt=bt, within=within, reseed=reseed,
                                          wide_push=wide_push, wide_tangent=wide_tangent, look=look, clr=clr)
        lead = scanned.tried[0]                         # the first arrangement's, for what follows a search that found nothing
        if scanned.won is None and all(t.hopeless for t in scanned.tried):
            from . import suggest_facts
            plan.findings.append(self._finding(C.UNPLACED_POCKET, dict(suggest_facts.unplaced_pocket(self, occ, plan, i),
                                                                       **lead.hopeless)))
            return self._step(i, None, 0.0, unplaced=[{"form": "pocket", **lead.hopeless}])
        stood = scanned.won or lead
        result, face_note, ahead, score, radius = scanned.result, scanned.face_note, stood.ahead, stood.score, stood.radius
        won = stood.j
        from . import timecap
        clock = timecap.active()
        if result.chosen is None and clock is not None and clock.gave_up:
            # out of time (--step-limit): no pocket, look-ahead or re-seeding is tried; place_one says why in a finding
            return self._step(i, None, 0.0, unplaced=[{"form": "time_limit"}])
        if result.chosen is not None and ahead is not None:
            lost = plan.__dict__.setdefault("_room_lost", {})
            for a, b, key in ahead.pairs:
                lost.setdefault(key, {})[a] = None        # room was left: the partner's refusal says so if it fails
        if result.chosen is None and ahead is not None and ahead.bucket in result.rejected:
            # No spot leaves the counterpart room, so the look-ahead cannot help: place it as before
            lost = plan.__dict__.setdefault("_room_lost", {})
            for (a, b), (short, asked) in sorted(ahead.misses().items()):
                key = next(k for x, y, k in ahead.pairs if (x, y) == (a, b))
                facts = {"item": i.key, "other": b, "own": a, "short_mm": short, "asked_mm": asked}
                plan.findings.append(self._finding(C.SETUP_LOOKAHEAD, facts, "notice"))
                lost.setdefault(key, {})[a] = facts
            step = self._settle(occ, i, plan, placed, solve=solve, look=False)
            step.notes = (step_text.record("lookahead_dropped", partners=list(ahead.names)),) + step.notes
            return step
        if result.chosen is None and solved is not None:
            # The solve spreads items without seeing what is already placed, so
            # its hint can land where nothing is legal. That must not cost a
            # placement the sequential seed would have made: drop the hint.
            step = self._settle(occ, i, plan, placed, solve=False)
            step.notes = (step_text.record("solve_hint_dropped", radius_mm=radius),) + step.notes
            return step
        if result.chosen is None:
            blamed = blame.blame_of(result)
            pocket_tried = None
            if i.near is None and bt is None and band is None and result.cut is None:
                # each arrangement's pocket in the order of the search, with its own scorer: the first that places stands
                why = step_text.record("seeded_no_spot", nets=seeded_nets or None, radius_mm=radius, blame=blamed)
                pocket_tried = 0
                for t in scanned.tried:
                    if t.hopeless:
                        continue                        # no pocket fits it
                    step, n = self._seeded_pocket(occ, t.j, plan, clr, t.hint, t.score, self._turns(t.j), why)
                    pocket_tried += n
                    if step is not None:
                        ident = getattr(t.j.item, "arrangement", "")
                        if ident:
                            step.notes = step.notes + (self._arrangement_note(ident),)
                        return step
            late = self._room_lost(plan, i)
            from . import suggest_facts
            facts = dict(suggest_facts.unplaced_search(self, occ, plan, i, placed, result, hint, radius),
                         radius_mm=radius, at=[hint.location.x, hint.location.y], blame=blamed, room_lost=late)
            if pocket_tried is not None:
                facts["pocket_tried"] = pocket_tried
            if result.cut is not None:
                facts["budget"] = result.cut
            plan.findings.append(self._finding(C.UNPLACED_SEARCH, facts))
            return self._step(i, None, 0.0, unplaced=scanned.reasons +
                              ([{"form": "budget", "budget": result.cut}] if result.cut is not None else []) +
                              ([{"form": "room_lost", "room_lost": late}] if finding_text.room_lost_text(late) else []))
        notes = list(seeded)
        if face_note:
            notes.append(face_note)
        if scanned.note:
            notes.append(scanned.note)
        if result.moved_mm > 0:
            first = next(iter(result.reasons.values()), None)
            notes.append(step_text.record("moved_off_hint", mm=result.moved_mm, why=None if first is None else first.to_json(),
                                        for_score=True if first is None and score else None))
        if push_sources:
            notes += self._push_notes(occ, plan, won, result.chosen, push_sources)
        if result.cut is not None:
            plan.findings.append(self._finding(C.SETUP_STEP_BUDGET, dict(item=i.key, **result.cut), "notice"))
            notes.append(step_text.record("search_budget", **result.cut))
        step = self._step(won, result.chosen, result.moved_mm, notes)
        step.back_face = bool(face_note) and result.chosen.face is Face.BACK
        return step

    def _firm_judged(self, occ, i: PlaceIntent, p: Placement, clr) -> tuple:
        """(refusal or None, resolution) of decided item `i` at `p`. Its carried vias, and those of the items placed before it,
        may give way (giveway.py): its commit does what this found. A decided place is judged as KiCad will: silk at the board's
        clearance."""
        with occ.silk_as_drawn():
            return occ.legal_giving_way(i.item, p, clr, past_edge=self._firm_past_edge(i), by_corners=True)

    def _firm_trials(self, occ, plan, i, placed, clr, push_sources) -> list:
        """Decided cell `i` laid in each arrangement it may take (`_arrangement_ids`), in order, as `_Trial`s: the declaration laid
        for that arranged cell (`_firm_placement`), judged as a firm item is judged (`_firm_judged`), and, when anything prices
        them (links to placed pads, pushes, an arrangement's lanes), each legal one scored once at that placement against what is
        placed now, unpruned, with what a via giving way costs. Partners not yet placed contribute nothing. User labels are looked
        past here, as a searched item looks past them: the labels of the one taken give way after (`_settle_firm_arranged`)."""
        targets = self._targets(i.item, occ, placed)
        was = occ.labels_yield
        occ.labels_yield = was or bool(plan.__dict__.get("_label_parts"))
        laid = []
        # a Beside laid nearer than its box (`_tight`) is recorded for the arrangement taken only (`_take_tight`)
        before = self._tight.pop(i.key, None)
        try:
            for ident in self._arrangement_ids(i):
                j = self._arranged(i, ident)
                p, chose = self._firm_placement(occ, plan, j)
                tight = self._tight.pop(i.key, None)
                why, resolution = self._firm_judged(occ, j, p, clr)
                laid.append((ident, j, p, chose, why, resolution, self._lane_pricer(occ, plan, j) if why is None else None,
                             tight))
        finally:
            occ.labels_yield = was
            self._tight.pop(i.key, None)
            if before is not None:
                self._tight[i.key] = before
        priced = bool(targets or push_sources or any(x[6] for x in laid))
        out = []
        for ident, j, p, chose, why, resolution, lanes, tight in laid:
            score = None
            if why is None and priced:
                score = self._scorer(j.item, occ, targets, prune=False, pushes=push_sources, lanes=lanes)(p) \
                    + (resolution.cost if resolution is not None else 0.0)
            out.append(_Trial(ident, j, p, chose, why, score, tight))
        return out

    def _take_tight(self, key: str, t: "_Trial") -> None:
        """Record in `_tight` how much nearer than its box the arrangement taken was laid, as a firm item with one arrangement
        records it while it is laid."""
        if t.tight is not None:
            self._tight[key] = t.tight

    def _settle_firm_arranged(self, occ, i, plan, placed, clr, push_sources) -> Step:
        """A decided cell that may take more than one arrangement, at its spot (`_firm_trials`). Each legal one is compared at its
        total (`_total_at`: its score, `score.arrangement` for one other than the default, `score.back_face`); the lowest wins and
        a tie keeps the one tried first. A non-default arrangement must also beat the default's total by
        `place.arrangement_margin` (`_margin`) when the default is legal, as a searched cell's must. With nothing to score, the
        first legal one stands. When none is legal it is a firm collision as for a cell with one arrangement: the default stands
        where its declaration puts it (the first `arrangements=` names when it does not name the default), and its `fixed.part`
        finding carries every other arrangement's refusal under `arrangements`. The one taken is recorded in `_arr_choice`."""
        cost = self.settings.score_arrangement
        trials = self._firm_trials(occ, plan, i, placed, clr, push_sources)
        total = {t.ident: self._total_at(t.score, t.placement, t.j, cost if t.ident else 0.0) for t in trials if t.score is not None}
        rows = [self._arrangement_row(t.ident, total.get(t.ident), t.why is None) for t in trials]
        legal = [t for t in trials if t.why is None]
        default = next((t for t in trials if not t.ident), None)
        if not legal:
            stood = default or trials[0]                    # the default when it was tried, else the first `arrangements=` names
            self._declared(stood)
            self._arr_choice[i.key] = stood.ident
            self._take_tight(i.key, stood)
            self._labels_give_way(occ, plan, stood.j.item, stood.placement)     # a user's label moves, the cell does not
            from . import suggest_facts
            facts = dict(suggest_facts.fixed_part(self, i), why=stood.why.to_json(),
                         arrangements=[{"id": t.ident or "default", "why": t.why.to_json()} for t in trials if t is not stood])
            plan.findings.append(self._finding(C.FIXED_PART, facts))
            notes = [stood.chose, step_text.record("refused", why=stood.why.to_json()), self._arrangement_note(None, rows)]
            return self._step(stood.j, stood.placement, 0.0, [x for x in notes if x])
        default_total = total.get("") if default is not None else None
        margin, held, best = self._margin(i), None, None
        for t in legal:
            mine = total.get(t.ident)
            if t.ident and mine is not None and margin is not None and default_total is not None \
                    and default_total - mine < margin:
                if mine < default_total and (held is None or mine < held[0]):
                    held = (mine, t.ident)
                continue
            if best is None or (mine is not None and mine < total[best.ident]):
                best = t
        scored = best.score is not None
        blamed = None
        if best.ident and default is not None and default.why is not None:
            blamed = [{"form": "rider", "count": 1, "reason": default.why.to_json()}]     # its one refusal, as blame_text renders it
        note = self._arrangement_note(best.ident, rows,
                                      score=self._total_at(best.score, best.placement, best.j, 0.0) if scored else None,
                                      cost=(cost if best.ident else 0.0) if scored else None,
                                      default_score=None if default_total is None or not scored
                                      else self._total_at(default.score, default.placement, default.j, 0.0),
                                      default_blame=blamed, within=None if best.ident else self._within(held, default_total, margin))
        self._declared(best)
        self._arr_choice[i.key] = best.ident
        self._take_tight(i.key, best)
        self._labels_give_way(occ, plan, best.j.item, best.placement)       # a user's label moves, the cell does not
        notes = [best.chose]
        if plan.__dict__.get("_label_parts"):
            # judged past the labels: one that could not give way is a firm collision, as for a cell with one arrangement
            why = self._firm_judged(occ, best.j, best.placement, clr)[0]
            if why:
                from . import suggest_facts
                plan.findings.append(self._finding(C.FIXED_PART, dict(suggest_facts.fixed_part(self, i), why=why.to_json())))
                notes.append(step_text.record("refused", why=why.to_json()))
        return self._step(best.j, best.placement, 0.0, [x for x in notes + [note] if x])

    def _declared(self, t: "_Trial") -> None:
        """Tell a viewer the firm cell stands at its declared spot: where, and in which arrangement ("default" for its own)."""
        if self._on_begin is not None:
            self._phase(Stage.DECLARED, hint=[round(t.placement.location.x, 3), round(t.placement.location.y, 3)],
                        arrangement=t.ident or "default")

    def _first_legal(self, occ, i, plan, settle_one) -> Step:
        """A form that is not scored (a slide along an edge, a line, a run, a rim, a ring, a spoke, a pocket with no hint) takes
        the default arrangement when it has a legal spot and tries the others, in order, only when it has none: `settle_one(j)`
        settles `j`, the item standing as one arrangement. What an arrangement that failed said is dropped when another stands;
        when none does, the first one's findings stand and the step's refusals are every arrangement's, tagged with the one they
        came from. The step's `arrangement` note lists those tried when more than one was, or one other than the default was
        taken, with why the default had no legal spot (its refusal counts, or the pocket it found none in); when none stood it
        names none as taken."""
        ids = self._arrangement_ids(i)
        if len(ids) == 1:
            return settle_one(self._arranged(i, ids[0]))
        n = len(plan.findings)
        first, first_findings, rows, refused, default_blame = None, [], [], [], None
        for ident in ids:
            step = settle_one(self._arranged(i, ident))
            rows.append(self._arrangement_row(ident, None, step.placement is not None))
            if step.placement is not None:
                if ident or len(rows) > 1:
                    step.notes = step.notes + (self._arrangement_note(ident, rows, default_blame=default_blame),)
                return step
            said = list(plan.findings[n:])
            if not ident:
                counts = next((f.facts["counts"] for f in said if f.cause == C.UNPLACED_SLIDE and f.facts.get("item") == i.key),
                              None)
                default_blame = None if counts is None else [{"form": "counts", "counts": counts}]
                pocket = next((f.facts for f in said if f.cause == C.UNPLACED_POCKET and f.facts.get("item") == i.key), None)
                if pocket is not None:          # what the pocket said (finding_text.pocket_note), without the item's suggestions
                    default_blame = [dict({k: pocket[k] for k in _POCKET_NOTE_KEYS if k in pocket}, form="pocket")]
            refused += [dict(r, **({"arrangement": ident} if ident else {})) for r in step.unplaced or ()]
            if first is None:
                first, first_findings = step, said
            del plan.findings[n:]
        plan.findings.extend(first_findings)
        if refused:
            first.unplaced = tuple(refused)
        first.notes = first.notes + (self._arrangement_note(None, rows),)
        return first

    def _scan_arrangements(self, occ, i, plan, placed, ids, **kw) -> "_Scanned":
        """Scan item `i` in each arrangement of `ids` ("" the default), in order, each an ordinary scan of the arranged cell (its own
        geometry, sweeper, scorer, seed and lanes), the front before the back. A non-default arrangement costs `score.arrangement`
        more and is taken only when its best score plus that is strictly below the best so far, or when nothing earlier has a legal
        spot; the best so far, less the cost, is the next scorer's pruning floor. The default's scan takes no floor, so its score
        is known whenever it has a legal spot. An unscored search (no links, pushes or lanes to price) takes the first arrangement
        with a legal spot and scans no further. Each scan has the step's budget afresh; the step's time limit stops between scans.
        `kw` are `_scan_one`'s keywords but `j`.

        A non-default arrangement must also beat the default's total by `place.arrangement_margin` (`_margin`); the best one held
        back by it is noted as `within`. The margin is not asked when the default had no legal spot, nor of a cell whose
        `arrangements=` names its choices, nor of an explore's draw.

        An explore variant (`_pick`) over more than one arrangement draws once from every arrangement's legal spots pooled, on
        both faces of an either-face item, each at its total as the choice compares it (`_standing_total`); the arrangement and
        face of the spot drawn stand (`_stand_drawn`). Over one arrangement the scan draws as it always has."""
        from . import timecap
        clock = timecap.active()
        cost = self.settings.score_arrangement
        margin = self._margin(i)
        self._arr_unreached.pop(i.key, None)
        draw = self._pick(i) if len(ids) > 1 else None
        tried, best, pool = [], None, []                # best: (total, ident, _Tried); pool: what `draw` draws from
        default_total, held = None, None                # held: (total, ident) of the best arrangement the margin kept out
        for k, ident in enumerate(ids):
            if k and clock is not None and clock.gave_up:
                self._arr_unreached[i.key] = [a or "default" for a in ids[k:]]
                break
            j = self._arranged(i, ident)
            budget = occ.step_budget
            if k and budget is not None:
                budget.judged = budget.lattice = budget.covered = 0
                budget.cut = False
            hint = kw["hint"]
            if j.item is not i.item and kw["reseed"] is not None and kw["band"] is None and kw["bt"] is None \
                    and not (kw["wide_push"] or kw["wide_tangent"]):
                hint = self._seed_hint(j.item, occ, kw["targets"], i.rotation, i.face)      # laid from the arranged item's pads
            extra = cost if ident else 0.0
            floor = best[0] if best is not None and ident else None
            self._collect_into = [] if draw is not None else None
            try:
                t = self._scan_one(occ, j, plan, placed, **{**kw, "hint": hint}, floor=floor, cost=extra)
            finally:
                got, self._collect_into = self._collect_into, None
            tried.append((ident, t))
            r = t.result
            if r is None or r.chosen is None:
                continue
            back = self.settings.score_back_face if j.either else 0.0
            pool += [(c[0] + extra + (back if c[3].face is Face.BACK else 0.0), c[1], c[2], c[3], ident, t) for c in got or ()]
            if t.score is None:
                best = (0.0, ident, t)                  # unscored: the first with a spot stands, nothing else is scanned
                break
            total = self._standing_total(t, extra)
            if not ident:
                default_total = total
            elif margin is not None and default_total is not None and default_total - total < margin:
                if total < default_total and (held is None or total < held[0]):
                    held = (total, ident)
                continue
            if best is None or total < best[0]:
                best = (total, ident, t)
        within = self._within(held, default_total, margin) if best is not None and not best[1] and not pool else None
        if pool:
            pool.sort(key=lambda c: c[:3])
            total, _, _, chosen, ident, t = draw(pool)  # explore.draw weighs by the total and the rank: the rest rides along
            self._stand_drawn(t, chosen, total - (cost if ident else 0.0))
            best = (total, ident, t)
        return self._chosen_scan(i, tried, best, cost, within)

    def _margin(self, i: PlaceIntent) -> float | None:
        """`place.arrangement_margin`, or None for a cell whose `arrangements=` names its choices: the script chose among them."""
        return None if i.arrangements else self.settings.place_arrangement_margin

    @staticmethod
    def _within(held, default_total, margin) -> dict | None:
        """The `within` fact of an `arrangement` note: the arrangement that scored better than the default by less than the
        margin, by how much, and the margin. `held` is (its total, its id) or None."""
        if held is None:
            return None
        return {"id": held[1], "by": round(default_total - held[0], 3), "margin": margin}

    def _stand_drawn(self, t, chosen: Placement, total: float) -> None:
        """Stand `t` (a `_Tried`) at the spot an explore drew from the pool, `total` its score with `score.back_face` and without
        the arrangement's cost: its result becomes that face's own scan's, at the drawn spot, and its face note what that face
        says."""
        back = chosen.face is Face.BACK and t.j.either
        raw = total - (self.settings.score_back_face if back else 0.0)
        own = (t.faces or {}).get(chosen.face, t.result)
        t.result = dataclasses.replace(own, chosen=chosen, score=raw, cut=own.cut or t.result.cut)
        if t.j.either:
            t.face_note = self._back_face_note(t.faces[Face.FRONT], raw) if back else None

    def _chosen_scan(self, i, tried, best, cost, within=None) -> "_Scanned":
        """What `_scan_arrangements` found: the winner's scan, or every arrangement's refusals merged when none has a legal spot, and
        the step's `arrangement` note when more than one arrangement was scanned or a non-default one was taken."""
        results = [(a, t.result) for a, t in tried if t.result is not None]
        cut = next((r.cut for _, r in results if r.cut), None)       # a cut is reported if any scan was cut
        if best is None:
            reasons = [dict(w.to_json(), **({"arrangement": a} if a else {})) for a, r in results for w in r.reasons.values()]
            if len(results) == 1:
                merged = results[0][1]
            else:
                merged = ScanResult(None, tried[0][1].hint, sum(r.tried for _, r in results),
                                    sum((r.rejected for _, r in results), Counter()),
                                    {k: w for _, r in reversed(results) for k, w in r.reasons.items()},
                                    sum((r.blockers for _, r in results), Counter()), cut=cut,
                                    bound=sum(r.bound for _, r in results))
            return _Scanned(None, [t for _, t in tried], merged, None, None, reasons)
        _, ident, won = best
        won.result.cut = won.result.cut or cut
        note = self._scanned_note(ident, won, tried, cost, within) if len(tried) > 1 or ident else None
        return _Scanned(won, [t for _, t in tried], won.result, won.face_note, note, [])

    def _standing_total(self, t, extra: float) -> float:
        """What a scan's spot (`_Tried` with a legal spot) is compared at: its score, plus `extra` (the arrangement's cost) and
        `score.back_face` when an either-face item stands on the back."""
        return self._total_at(t.result.score, t.result.chosen, t.j, extra)

    def _total_at(self, score: float, p: Placement, j: PlaceIntent, extra: float) -> float:
        """`score` of item `j` standing at `p`, plus `extra` (an arrangement's cost) and `score.back_face` when an either-face item
        stands on the back."""
        return score + extra + (self.settings.score_back_face if p.face is Face.BACK and j.either else 0.0)

    def _scanned_note(self, ident, won, tried, cost, within=None) -> dict:
        """The `arrangement` note of a scan over arrangements (`_arrangement_note`): `won` the `_Tried` taken, `tried` each
        (id, `_Tried`) scanned. Each row is its total as the choice compared it (`_standing_total`). A row is `beaten`, with no
        score, when the floor of the best so far cut it: it had room but could not beat that. `default_blame` says why the
        default had no legal spot, and `within` (`_within`) which arrangement the margin held back."""
        def beaten(t):
            r = t.result
            return t.score is not None and r is not None and (r.score >= PRUNED if r.chosen is not None else r.bound > 0)

        def row(a, t):
            r = t.result
            cut = beaten(t)
            legal = r is not None and (r.chosen is not None or cut)
            total = self._standing_total(t, cost if a else 0.0) if legal and t.score is not None and not cut else None
            return self._arrangement_row(a, total, legal, beaten=cut)
        default = next((t for a, t in tried if not a), None)
        scored = won.score is not None
        default_score = default_blame = None
        if default is not None and default.result is not None and default.result.chosen is not None:
            if scored:
                default_score = self._standing_total(default, 0.0)
        elif default is not None and default.hopeless:
            default_blame = [{"form": "pocket", **default.hopeless}]
        elif default is not None and default.result is not None:
            default_blame = blame.blame_of(default.result)
        return self._arrangement_note(ident, [row(a, t) for a, t in tried],
                                      score=self._standing_total(won, 0.0) if scored else None,
                                      cost=(cost if ident else 0.0) if scored else None, default_score=default_score,
                                      default_blame=default_blame, within=within)

    @staticmethod
    def _arrangement_row(ident, total, legal: bool, beaten: bool = False) -> dict:
        """A row of the `arrangement` note: an arrangement tried ("" the default), its total as the choice compared it (None when
        the choice was unscored, it had no legal spot, or a bound cut it), whether it had a legal spot, and `beaten` when a bound
        cut it."""
        out = {"id": ident or "default", "score": None if total is None else round(total, 3), "legal": legal}
        if beaten:
            out["beaten"] = True
        return out

    @staticmethod
    def _arrangement_note(ident, rows=None, *, score=None, cost=None, default_score=None, default_blame=None, within=None) -> dict:
        """The step's `arrangement` note, every form's: `ident` the one taken ("" the default, None when none stood); `rows` each
        arrangement tried
        (`_arrangement_row`); `score` the one taken's, without its cost, and `cost` its `score.arrangement` (both None when the
        choice was unscored); `default_score` the default's total, given only when the default was tried and had a legal spot in
        a scored choice; `default_blame` why the default had no legal spot. What is None is left out."""
        return step_text.record("arrangement", id=None if ident is None else ident or "default",
                                score=None if score is None else round(score, 3), cost=cost,
                                tried=rows, default_score=None if default_score is None else round(default_score, 3),
                                default_blame=default_blame, within=within)

    @staticmethod
    def _faces_of(i: PlaceIntent) -> tuple:
        """The faces a search of `i` tries, the front first."""
        return (Face.FRONT, Face.BACK) if i.either else (i.face,)

    @staticmethod
    def _face_text(i: PlaceIntent) -> str:
        return "front or back" if i.either else i.face.value

    def _offered(self, cell) -> tuple:
        """The ids a cell offers besides its own layout; none while `place.arrangements` is false. Give it the base cell
        (`self.geometry.cells[key]`): an arranged cell holds no arrangements and offers ()."""
        if not self.settings.place_arrangements or not isinstance(cell, CellGeom):
            return ()
        return cell.offered()

    def _arrangement_ids(self, i: PlaceIntent) -> list:
        """The arrangements a search of `i` tries, "" standing for the default: the ones `arrangements=` names in its order, else the
        default then everything the cell offers in the module's order. A part and a block have [""]; a cell already standing in an
        arrangement has that one alone. What a cell offers is read off the base cell, never off `i.item`."""
        if i.kind != "cell":
            return [""]
        if getattr(i.item, "arrangement", ""):
            return [i.item.arrangement]
        if i.arrangements:
            return ["" if a == "default" else a for a in i.arrangements]
        return [""] + list(self._offered(self.geometry.cells[i.key]))

    def _arranged(self, i: PlaceIntent, ident: str) -> PlaceIntent:
        """`i` with its cell standing as arrangement `ident` ("" the default), built from the base cell; a part or block as it is."""
        if i.kind != "cell":
            return i
        item = self.geometry.cells[i.key].arranged(ident)
        return i if item is i.item else dataclasses.replace(i, item=item)

    def _arrangement_missing(self, item: str, asked: list, offered: list, source: str = "") -> Finding:
        """`arrangement.missing`: critical when the cell's step ends unplaced for it; a warning when `source` is "lock" (the lock
        names an arrangement the cell no longer offers, and the cell is placed anyway)."""
        facts = {"item": item, "asked": list(asked), "offered": list(offered)}
        if source:
            facts["source"] = source
        return self._finding(C.ARRANGEMENT_MISSING, facts, "warning" if source == "lock" else "critical")

    def _pinned(self, i: PlaceIntent) -> tuple:
        """(the intent to lay, None), or (i, the ids the cell offers) when `arrangements=` names an id it does not offer. A cell
        that is to take one arrangement is laid as that arrangement. What the cell offers is read off the base cell."""
        if i.kind != "cell" or getattr(i.item, "arrangement", ""):
            return i, None                              # a settle that runs again with the item already arranged
        offered = ("default",) + self._offered(self.geometry.cells[i.key])
        if any(a not in offered for a in i.arrangements):
            return i, offered
        ids = self._arrangement_ids(i)
        return (self._arranged(i, ids[0]) if len(ids) == 1 else i), None

    def _arrangement_gone(self, i: PlaceIntent, offered: tuple, plan: Plan) -> Step:
        """The unplaced step of a cell whose `arrangements=` names an id it does not offer, and its finding."""
        plan.findings.append(self._arrangement_missing(i.key, i.arrangements, offered))
        return self._step(i, None, 0.0, unplaced=[{"form": "arrangement_missing", "asked": list(i.arrangements),
                                                   "offered": list(offered)}])

    def _gate(self, occ, i: PlaceIntent, plan: Plan) -> tuple:
        """(the intent to settle, None), or (i, the unplaced step) when `arrangements=` names an id the cell does not offer
        (`_pinned`)."""
        i, offered = self._pinned(i)
        return (i, None) if offered is None else (i, self._arrangement_gone(i, offered, plan))

    def _scan_one(self, occ, j, plan, placed, *, targets, push_sources, hint, band, bt, within, reseed, wide_push, wide_tangent,
                  look, clr, floor=None, cost: float = 0.0) -> "_Tried":
        """One standing of the item scanned (the item as its script says it): the riders', exposure and look-ahead tests, the lane
        pricer, the scorer, the radius, the pocket check, and the front-then-back scan."""
        # riders refuse candidates after they are scored: a refused one must not prune the rest
        accept = self._accept(j)
        exposed = self._exposure_accept(occ, j, push_sources)
        if exposed is not None:
            accept = exposed if accept is None else (lambda c, a=accept, b=exposed: a(c) or b(c))
        ahead = self._lookahead(occ, j, placed) if look else None
        if ahead is not None:
            accept = ahead if accept is None else (lambda c, a=accept, b=ahead: a(c) or b(c))
        lanes = self._lane_pricer(occ, plan, j)
        score = self._scorer(j.item, occ, targets, prune=self._pick(j) is None and accept is None,
                             pushes=push_sources, lanes=lanes) if targets or push_sources or lanes else None
        if score is not None and floor is not None and hasattr(score, "best"):
            score.best[0] = min(score.best[0], floor - cost)
        # A seeded item lands on the pads that pull it; it must be free to step at least its own size clear of them.
        body = occ._geometry(j.item).body
        if band is not None:
            radius = band[2] + hint.location.distance(band[0])      # every point of the band is within it
        elif j.near is not None:
            radius = j.radius
        elif wide_push or wide_tangent:
            # A push's own disc can swallow whatever a link or the global solve seeded, so the
            # widening applies whatever else set the hint - not only when a push seeded it too.
            radius = math.hypot(self._outline.width, self._outline.height)
        else:
            radius = max(j.radius, body.width, body.height)
        hopeless = None if bt is not None or band is not None else self._no_pocket_note(occ, j)
        if hopeless:
            return _Tried(j, hint, radius, None, None, ahead, score, hopeless)
        if self._on_begin is not None:
            self._phase(Stage.SCAN, face="either" if j.either else j.face.value,
                        hint=[round(hint.location.x, 3), round(hint.location.y, 3)], radius=round(radius, 2))
        result, face_note, faces = self._scan_faces(occ, j, hint, radius, clr, score, accept, reseed=reseed, turns_at=bt,
                                                    within=within, turns_on=lambda f: self._spot_turns(occ, j, placed, band, f))
        return _Tried(j, hint, radius, result, face_note, ahead, score, faces=faces)

    def _scan_faces(self, occ: Occupancy, i: PlaceIntent, hint: Placement, radius: float, clr, score, accept,
                    reseed=None, turns_at=None, within=None, turns_on=None):
        """(the scan's result, a step_text note on the face taken or None, {face: its own ScanResult} for each face scanned) for
        `i`. A fixed face is one scan. Face.EITHER
        scans the front and then the back, each at its own turn of the hint (`reseed`: the targets a
        seeded hint was made from, laid again for the back's pads), and takes the back only where
        its score plus `score.back_face` is less than the front's, or the front has no legal spot.
        An unscored search takes the front when it has a spot: the back costs more and nothing else
        tells them apart. A failure carries both faces' refusals. `turns_at` is the front's SpotTurns and
        `turns_on(face)` makes the back's: a tangent turn depends on the face, as the item is mirrored there."""
        turns, pick = self._turns(i), self._pick(i)
        if not i.either:
            alone = scan(occ, i.item, hint, radius, i.step, turns, clr, score=score, pick=pick, accept=accept,
                         turns_at=turns_at, within=within)
            return alone, None, {i.face: alone}
        cost = self.settings.score_back_face
        front = scan(occ, i.item, hint, radius, i.step, turns, clr, score=score, pick=pick, accept=accept,
                     turns_at=turns_at, within=within)
        if front.chosen is not None and score is None:
            return front, None, {Face.FRONT: front}
        if hint.face is Face.BACK:
            back_hint = hint
        elif reseed:
            back_hint = self._seed_hint(i.item, occ, reseed, i.rotation, Face.BACK)
        else:
            back_hint = Placement(hint.location, hint.rotation, Face.BACK)
        if front.chosen is not None and hasattr(score, "best"):
            score.best[0] = min(score.best[0], front.score - cost)      # a back spot must beat the front's by it
        back_turns = turns_on(Face.BACK) if turns_at is not None and turns_on is not None else turns_at
        back = scan(occ, i.item, back_hint, radius, i.step, turns, clr, score=score, pick=pick, accept=accept,
                    turns_at=back_turns, within=within)
        faces = {Face.FRONT: front, Face.BACK: back}
        if back.chosen is not None and back.score < PRUNED and (front.chosen is None or back.score + cost < front.score):
            return back, self._back_face_note(front, back.score), faces
        if front.chosen is not None:
            return front, None, faces
        merged = ScanResult(None, hint, front.tried + back.tried, front.rejected + back.rejected,
                            {**back.reasons, **front.reasons}, front.blockers + back.blockers,
                            cut=back.cut or front.cut,
                            # a back whose spots the floor all cut had room: it counts with the give-way cuts
                            bound=front.bound + back.bound + (1 if back.chosen is not None else 0))
        return merged, None, faces

    def _back_face_note(self, front: ScanResult, back: float) -> dict:
        """The `back_face` note of an either-face item standing on the back at score `back`, against `front`, the front's scan."""
        cost = self.settings.score_back_face
        if front.chosen is None:
            return step_text.record("back_face", front_blame=blame.blame_of(front))
        if front.score >= PRUNED:                       # the front was cut by the floor of an earlier arrangement: no score of its own
            return step_text.record("back_face", back=back, cost=cost, front_beaten=True)
        return step_text.record("back_face", back=back, cost=cost, front=front.score)

    def _push_notes(self, occ: Occupancy, plan: Plan, i: PlaceIntent, placement: Placement, push_sources: list) -> list:
        """What each push comes to with `i` at `placement`, recorded on the plan and as the step's notes."""
        points = {}
        bits = []
        pads = occ.candidate_pad_locations(i.item, placement)
        for source_point, p in push_sources:
            at = _push_at(occ, i.item, placement, p, pads, points)
            if at is None:
                at = placement.location
            value, r = _push_value(source_point, at, p)
            p.achieved_value, p.achieved_mm = round(value, 4), round(r, 3)
            if not p.sens:
                bits.append(step_text.record("push", source=_push_source_label(p), value=value, at_mm=r, limit=p.limit))
            plan.pushes.append(p)
        bits += self._exposure_notes(occ, i, placement, push_sources)
        return bits

    def _spots_of(self, occ: Occupancy, i: PlaceIntent, placed, band, front: SpotTurns | None) -> list:
        """The SpotTurns of each face a search of `i` tries, `front` being the front's (or the fixed face's)."""
        if front is None:
            return []
        if not i.either:
            return [front]
        return [front, self._spot_turns(occ, i, placed, band, Face.BACK)]

    def _spot_turns(self, occ: Occupancy, i: PlaceIntent, placed, band: tuple | None,
                    face: Face | None = None) -> SpotTurns | None:
        """The turns a scan takes at each spot when they depend on it (placer.SpotTurns): a tangent
        search's, taken from the spot's bearing about the Tangent's `about`, else that of the Polar
        band the item is in, else the board's centre; or a band's fixed turns, kept where the
        item's body centre is in the band. None when neither applies. `face` is the face the turns are for
        (the declaration's, by default). On the back the item is mirrored about the vertical axis before it
        turns, so the turn that points its outward side away from the centre is the back's own
        (`outward_rotation(..., Face.BACK)`: a declared east or west side swap, north and south stay), and
        the offset of its body centre is that of the mirrored body."""
        if i.tangent is None and band is None:
            return None
        face = i.face if face is None else face
        if i.tangent is not None:
            ref = i.tangent.about if i.tangent.about is not None else i.about
            centre = self.centre if ref is None else _locate(self, occ, ref)
            spot = BearingTurns(centre, lambda b: self.outward_rotation(i.item, b, face)[0],
                                self.settings.place_tangent_bin, i.tangent.quarters,
                                band=None if band is None else band[1:])
        else:
            spot = BandTurns(band[0], self._turns(i), {}, band[1:])
        spot.offset = {r: (c.x, c.y) for r in spot.turns
                       for c in (occ.body_box(i.item, Placement(Location(0.0, 0.0), r, face)).center,)}
        return spot

    def _band_of(self, occ: Occupancy, i: PlaceIntent, placed) -> tuple | None:
        """(centre, r_min, r_max) of the band a Polar range searches, or None."""
        if i.band is None or i.angle is not None:
            return None
        return (self.centre if i.about is None else _locate(self, occ, i.about)), float(i.band[0]), float(i.band[1])

    def _band_hint(self, i: PlaceIntent, band: tuple, hint: Placement | None) -> Placement:
        """Where a band's scan starts: the seed brought to the nearest radius in the band, else the
        item's share of the turn (as a ring's, k of n from the top) at the band's middle radius."""
        centre, lo, hi = band
        if hint is not None:
            d = hint.location.distance(centre)
            if lo <= d <= hi:
                return hint
            if d > 0.0:
                r = min(max(d, lo), hi)
                return Placement(polar_point(centre, bearing_of(hint.location.x - centre.x, hint.location.y - centre.y), r),
                                 hint.rotation, hint.face)
        fellows = [x for x in self._placements() if x.band == i.band and x.about == i.about and x.angle is None
                   and not x.freedom.decided]
        k, n = _slot_of(fellows, i), max(len(fellows), 1)
        return Placement(polar_point(centre, 360.0 * k / n, (lo + hi) / 2.0), i.rotation, i.face)

    def _settle_turns_on_point(self, occ: Occupancy, i: PlaceIntent, plan: Plan, placed: set, clr,
                               push_sources: list) -> Step:
        """The item stays on its point and its turn is searched: each turn `rotations=` names, in each arrangement of a cell, is
        laid as the declaration lays it, kept when the item is legal there as a decided place is judged, and scored as a search
        scores a candidate (links, pushes, escape lanes, a via giving way) with its arrangement's scorer. The lowest score plus
        `score.arrangement` (for an arrangement other than the default) wins; a tie goes to the arrangement tried first, then
        the turn nearest `rotation=`, then the smaller angle. A non-default arrangement must also beat the default's lowest by
        `place.arrangement_margin` (`_margin`) when the default has a legal turn. With nothing to score, the first arrangement
        with a legal turn stands and those after it are not laid."""
        turns = sorted({float(r) % 360.0 for r in i.rotations})
        ids = self._arrangement_ids(i)
        arr_cost = self.settings.score_arrangement
        targets = self._targets(i.item, occ, placed)
        declared = float(i.rotation) % 360.0
        found = []
        rejected: Counter = Counter()
        by_arrangement: dict = {}           # arrangement -> Counter of its refusals by kind
        reasons: dict = {}                  # (arrangement, reason key) -> the first refusal of that kind
        rows, scored, default_total = [], False, None
        for k, ident in enumerate(ids):
            j = self._arranged(i, ident)
            laid = {rot: self._firm_placement(occ, plan, dataclasses.replace(j, rotation=rot)) for rot in turns}
            geom = occ._geometry(j.item)
            region = Box.union([transform_box(occ._extent(geom), occ._transform(geom, p)) for p, _ in laid.values()])
            others = occ.obstacles(geom, region)
            exposed = self._exposure_accept(occ, j, push_sources)
            accept = self._accept(j)            # the items riding it, asked of each turn that is otherwise legal
            lanes = self._lane_pricer(occ, plan, j)
            score = self._scorer(j.item, occ, targets, prune=exposed is None and accept is None, pushes=push_sources,
                                 lanes=lanes) if targets or push_sources or lanes else None
            scored = scored or score is not None
            extra = arr_cost if ident else 0.0
            best = None
            for rot, (p, chose) in laid.items():
                why, resolution = occ.legal_giving_way(j.item, p, clr, others=others, by_corners=True)
                if why is None and exposed is not None:
                    why = exposed(p)
                if why is None and accept is not None:
                    why = accept(p)
                if why is not None:
                    key = _reason_key(why)
                    rejected[key] += 1
                    by_arrangement.setdefault(ident, Counter())[key] += 1
                    reasons.setdefault((ident, key), why)
                    continue
                cost = (score(p) if score is not None else 0.0) + (resolution.cost if resolution is not None else 0.0)
                away = abs((rot - declared + 180.0) % 360.0 - 180.0)
                found.append((cost + extra, k, away, rot, cost, p, chose, ident, j))
                best = cost + extra if best is None else min(best, cost + extra)
            rows.append(self._arrangement_row(ident, best if score is not None else None, best is not None))
            if not ident and best is not None and score is not None:
                default_total = best
            if score is None and best is not None:
                break                           # unscored: the first arrangement with a legal turn stands
        if not found:
            plan.findings.append(self._finding(C.UNPLACED_BEARING, {
                "item": i.key, "turns": len(turns), "counts": blame.counts_of(rejected),
                **({"arrangements": len(ids)} if len(ids) > 1 else {})}))
            return self._step(i, None, 0.0, unplaced=[dict(w.to_json(), **({"arrangement": a} if a else {}))
                                                      for (a, _), w in reasons.items()])
        margin, held = self._margin(i), None
        if margin is not None and default_total is not None:
            short = lambda f: f[7] and default_total - f[0] < margin      # an arrangement not the margin better than the default
            held = min(((f[0], f[7]) for f in found if short(f) and f[0] < default_total), default=None)
            found = [f for f in found if not short(f)]
        _, k, away, rot, cost, p, chose, ident, j = min(found, key=lambda f: f[:4])
        notes = [chose] if chose else []
        notes.append(step_text.record("turned", rot=rot, of=len(turns), cost=cost if scored else None,
                                      arrangement=ident or None))
        own = by_arrangement.get(ident)          # the refusals of the arrangement taken: the default's are its blame
        if own:
            notes.append(step_text.record("refused_count", n=sum(own.values()),
                                          why=next(w for (a, _), w in reasons.items() if a == ident).to_json()))
        if len(rows) > 1 or ident:
            default = next((r for r in rows if r["id"] == "default"), None)
            blamed = [{"form": "counts", "counts": blame.counts_of(by_arrangement.get("", Counter()))}] \
                if ident and default is not None and not default["legal"] else None
            notes.append(self._arrangement_note(ident, rows, score=cost if scored else None,
                                                cost=(arr_cost if ident else 0.0) if scored else None,
                                                default_score=default_total, default_blame=blamed,
                                                within=None if ident else self._within(held, default_total, margin)))
        if push_sources:
            notes += self._push_notes(occ, plan, j, p, push_sources)
        return self._step(j, p, 0.0, notes)


def _slot_of(fellows: list, i: "PlaceIntent") -> int:
    """Where `i` stands among the declarations sharing its freedom, found by key: a cell searched in an arrangement is not equal
    to its declaration."""
    return [x.key for x in fellows].index(i.key)


@contextlib.contextmanager
def _recording_commits(occ: Occupancy):
    """Every commit made on `occ` inside the block, as [(kind, name), placement]
    for a later run to apply again: the item named by refdes or cell name."""
    from . import reuse as _reuse
    commits = []
    real = occ.commit

    def commit(item, placement):
        if not isinstance(item, CellGeom):
            commits.append([("fp", item.ref), _reuse.placement_to_json(placement)])
            return real(item, placement)
        # A cell in an arrangement records it beside its name and in its placement (a rider's placement may leave it to the item); a
        # cell in its default records as it always did.
        arranged = placement.arrangement or item.arrangement
        if arranged:
            commits.append([("cell", item.name, arranged),
                            _reuse.placement_to_json(dataclasses.replace(placement, arrangement=arranged))])
        else:
            commits.append([("cell", item.name), _reuse.placement_to_json(placement)])
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


_LABEL_COVERS = ("body", "pad", "through", "mask", "silk")
"""The shapes of another part a label sitting on is a finding: what covers
it, clips it or stands in its silk. A claimed courtyard is the part itself
and counts too; another courtyard does not, as silk may stand in one."""


def _label_hits(occ, box: Box, face: Face, own: set) -> list:
    """Who a label's text box sits on, on its face: under the physical
    envelope, a part one of whose shapes it overlaps (a round part's disc,
    not the box round it); under the others, which draw no silk or body,
    a part whose reach it overlaps."""
    label = box_polygon(box)
    out = set()
    for r, g in occ.items.items():
        if g.reference.face is not face or r in occ.pending or occ.who(r) in own:
            continue
        if occ.envelope != "physical":
            if (g.reach or g.body).overlaps(box):
                out.add(occ.who(r))
            continue
        if any((s.kind in _LABEL_COVERS or (s.kind == "courtyard" and s.claims)) and s.box.overlaps(box)
               and polys_overlap(label, s.poly) for s in g.shapes):
            out.add(occ.who(r))
    return sorted(out)


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


@dataclass(frozen=True)
class Site:
    """Where a script declared something: the kind of call (`place`, `link`, `keepout`, ...), its key, and the
    file and line the call was made on."""
    kind: str
    key: str
    file: str
    line: int


def _link_key(l) -> str:
    return "%s.%s>%s.%s" % (l.a[0], l.a[1], l.b[0], l.b[1])


def copper_id(c) -> str:
    """What names one copper declaration for a suggestion: its key and its place in the declaration order (two
    tracks of one net have the same key)."""
    return "%s#%d" % (c.key, c.index)


def _keyed(out) -> list:
    key = getattr(out, "key", None)
    if key is None:
        return []
    return [copper_id(out)] if hasattr(out, "index") and hasattr(out, "net") else [key]


def _first(args, kwargs, name):
    return args[0] if args else kwargs.get(name)


# (method -> a function from the board, the result and the arguments to the keys of the declarations it made):
# every declaration a suggestion may edit records where it was made
_SITED = {
    "place": lambda b, out, a, k: _keyed(out),
    "link": lambda b, out, a, k: [_link_key(out)],
    "keepout": lambda b, out, a, k: [out.keepout.name],
    "label": lambda b, out, a, k: [out] if isinstance(out, str) else list(out),
    "track": lambda b, out, a, k: _keyed(out),
    "pair": lambda b, out, a, k: _keyed(out),
    "vias": lambda b, out, a, k: _keyed(out),
    "via": lambda b, out, a, k: _keyed(out),
    "stitch": lambda b, out, a, k: _keyed(out),
    "pour": lambda b, out, a, k: _keyed(out),
    "plane": lambda b, out, a, k: _keyed(out),
    "fanout": lambda b, out, a, k: [b._item(_first(a, k, "item"))[1]],
    "escape": lambda b, out, a, k: [b._item(_first(a, k, "part"))[1]],
    "rect": lambda b, out, a, k: ["board"],         # the outline: one declaration of it, so one key (two are refused at bind)
    "disc": lambda b, out, a, k: ["board"],
    "outline": lambda b, out, a, k: ["board"],
    "row": lambda b, out, a, k: [b._item(list(_first(a, k, "items"))[0])[1]],      # its first member; the members list is the argument
    "block": lambda b, out, a, k: [out.anchor.inst],
    "rule": lambda b, out, a, k: [out.why],
    "accept": lambda b, out, a, k: ["%s %s" % (out.check, out.subject)],
    "alternative": lambda b, out, a, k: ["%s.%s" % (out.group if isinstance(out, GroupOption) else out.item, out.name)],
    "arrangement": lambda b, out, a, k: [out.name],
    "unit": lambda b, out, a, k: [out.name],
    "exclude": lambda b, out, a, k: ["+".join(out.choices)],
}


def _sited(method: str, keys):
    def wrap(fn):
        @functools.wraps(fn)
        def declared(self, *args, **kwargs):
            site = _script_site()
            out = fn(self, *args, **kwargs)
            if method in ("rect", "disc", "outline"):
                self._outline_decl = method
            for key in keys(self, out, args, kwargs):
                self._record_site(method, key, site)
            return out
        return declared
    return wrap


def _script_site() -> tuple:
    """(file, line) of the script (or test) that made the declaration being
    built: the first frame outside the placemat package."""
    import inspect
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    f = inspect.currentframe()
    while f is not None:
        if not os.path.abspath(f.f_code.co_filename).startswith(here + os.sep):
            return os.path.abspath(f.f_code.co_filename), f.f_lineno
        f = f.f_back
    return "", 0


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


def _push_source_label(push) -> str:
    if push.label:
        return push.label
    source = push.source
    if isinstance(source, str):
        return "keepout %r" % source
    if isinstance(source, PadRef):
        return "%s pad %s" % (source.part, source.key)
    if isinstance(source, Location):
        return _loc(source)
    return str(source)          # Part or Cell: their own __str__ is their key


_DISC_INRADIUS = math.cos(math.pi / 72)       # a push's reservation is a 72-sided polygon (`_circle`): its flats are this much of the radius off its centre


def _hull(points: list) -> list:
    """The convex hull of some points, as (x, y) pairs: the farthest point from anywhere is one of them."""
    pts = sorted({(p.x, p.y) for p in points})
    if len(pts) <= 2:
        return pts

    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (q[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(q)
        return out
    lower, upper = half(pts), half(reversed(pts))
    return lower[:-1] + upper[:-1]


def _push_value(source_point: Location, point: Location, push: "Push") -> tuple:
    """(value, r) for a push at distance r from its source to `point`."""
    r = max(source_point.distance(point), 1e-6)
    return push.v_ref * (push.r_ref / r) ** push.falloff, r


def _push_at(occ: Occupancy, item, placement: Placement, push: "Push", pads: dict, points: dict):
    """Where a push measures its item at a candidate placement: the named
    pad, the annotated emission point carried with the item, or the
    member's body centre (`points` keeps those, per member, for one
    candidate). None when the named pad is not the item's."""
    if push.target_pad_key is not None:
        return pads.get(push.target_pad_key)
    if push.target_point is not None:
        return occ._transform(occ._geometry(item), placement).apply_location(push.target_point)
    point = points.get(push.target_member_ref)
    if point is None:
        point = _target_point(occ, item, placement, push.target_member_ref)
        points[push.target_member_ref] = point
    return point


def _target_point(occ: Occupancy, item, placement: Placement, member_ref: str) -> Location:
    """Where a push's own item stands at a candidate placement: when
    `item` is a cell, the NAMED MEMBER's body centre, carried by the
    cell's transform (a push measures the part it named, not the cell's
    aggregate box - a cell moves as one rigid body, but its members sit
    at different points within it). The item's own body centre otherwise
    (item already IS the one part)."""
    geom = occ._geometry(item)
    if geom.part_refs and member_ref in geom.part_refs:
        idx = geom.part_refs.index(member_ref)
        t = occ._transform(geom, placement)
        return t.apply_location(geom.parts[idx].center)
    return occ.body_box(item, placement).center


def _as_point(value) -> Location:
    """A centre a script gave: a Location, or an (x, y) pair."""
    if isinstance(value, Location):
        return value
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
        return Location(float(value[0]), float(value[1]))
    raise TypeError("a centre is a Location or an (x, y) pair, not %r" % (value,))


def _locate(board: "Board", occ: Occupancy, ref, placed: tuple | None = None) -> Location:
    """A point on the board as things stand: a Location, a pad reference
    (where that pad now is), the Mid of two points, a bare X()/Y() of one
    (the other axis its own), a Polar about a centre that may itself be a
    reference, or an (x, y) pair whose members may be numbers, X()/Y() of
    references, or row coordinates. `placed` is the (width, height) of the
    pad a Pin is placing, which a PadRef's `edge=` stands off by."""
    if isinstance(ref, Location):
        if isinstance(ref.x, (int, float)) and isinstance(ref.y, (int, float)):
            return ref
        return Location(_coord(board, occ, ref.x, "x", placed), _coord(board, occ, ref.y, "y", placed))   # a Location said in references
    if isinstance(ref, LanePoint):
        return board._lane_point(occ, ref)
    if isinstance(ref, FigurePoint):
        return _figure_point(board, occ, ref, placed)
    if isinstance(ref, Mid):
        a, b = _locate(board, occ, ref.a, placed), _locate(board, occ, ref.b, placed)
        return Location((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)
    if isinstance(ref, X):
        at = _locate(board, occ, ref.ref, placed)
        return Location(at.x + ref.dx, at.y)
    if isinstance(ref, Y):
        at = _locate(board, occ, ref.ref, placed)
        return Location(at.x, at.y + ref.dy)
    if isinstance(ref, Origin):
        return board._origin_of(occ, ref.item)
    if isinstance(ref, Polar):
        centre = board.centre if ref.about is None else _locate(board, occ, ref.about, placed)
        angle = _line_bearing(board, occ, ref.angle, placed) if isinstance(ref.angle, Bearing) else ref.angle
        return polar_point(centre, angle, float(ref.radius))
    if isinstance(ref, tuple) and len(ref) == 2:
        return Location(_coord(board, occ, ref[0], "x", placed), _coord(board, occ, ref[1], "y", placed))
    if isinstance(ref, Centre):
        return Location(_coord(board, occ, ref.x, "x", placed), _coord(board, occ, ref.y, "y", placed))
    if isinstance(ref, (Part, Cell)):
        geom, key, kind = board._item(ref)
        refs = [fp.ref for fp in (geom.members if kind == "cell" else (geom,))]
        return Box.union([occ.items[r].body for r in refs]).center      # where its body is now
    if getattr(ref, "edge", None) is not None:
        if placed is not None:
            return _edge_point(board, occ, placed[1] if ref.edge in (Edge.NORTH, Edge.SOUTH) else placed[0], ref,
                               placed[0] if ref.edge in (Edge.NORTH, Edge.SOUTH) else placed[1])
        raise ValueError("%s pad %s: a PadRef's edge= is a track's point on that edge of the pad, or a Past's "
                         "across=, or a Pin's point for a part's pad; here it has no width to stand off by" % (board._pad_ref(ref)[0], ref.key))
    owner, number, dx, dy = board._pad_ref(ref)
    at = occ.pad_location(owner, number, board._pad_land(ref)).offset(dx, dy)
    lx, ly = getattr(ref, "lx", 0.0), getattr(ref, "ly", 0.0)
    if lx or ly:
        from .lock import _turn
        g = occ.items[owner].reference
        vx, vy = _turn(-lx if g.face is Face.BACK else lx, ly, g.rotation)
        at = at.offset(vx, vy)
    return at


def _figure_point(board: "Board", occ: Occupancy, ref: FigurePoint, placed: tuple | None = None) -> Location:
    """A figure's point on the board: its own (x, y) less the figure's anchor,
    turned by the figure's bearing about the place the anchor lands, as a
    keepout's Path with `anchor=` is (cutouts._turned)."""
    fig = ref.figure
    centre = _locate(board, occ, fig.at, placed)
    rot = fig.rotation
    if isinstance(rot, Turned):
        # a bearing, clockwise from the top: the part's turn (counter-clockwise) negated, as _region_rotation does
        rot = -(occ.items[board._pad_ref(rot.part)[0]].reference.rotation + rot.degrees) % 360.0
    x, y = _turned([(ref.x - fig.anchor[0], ref.y - fig.anchor[1])], centre, float(rot))[0]
    return Location(x, y)


def _line_bearing(board: "Board", occ: Occupancy, b: Bearing, placed: tuple | None = None) -> float:
    """The compass bearing a `Bearing(a, b, degrees)` says: the line from a to b, plus its degrees."""
    a, c = _locate(board, occ, b.a, placed), _locate(board, occ, b.b, placed)
    if a.distance(c) < 1e-9:
        raise ValueError("a Bearing's two points are one point, %.3f, %.3f: the line between them has no direction"
                         % (a.x, a.y))
    return (bearing_of(c.x - a.x, c.y - a.y) + b.degrees) % 360.0


def _coord(board: "Board", occ: Occupancy, v, axis: str, placed: tuple | None = None) -> float:
    """One coordinate: a number, X()/Y() of a reference, a row coordinate,
    or a reference/point whose `axis` coordinate is meant."""
    if isinstance(v, X):
        return _locate(board, occ, v.ref, placed).x + v.dx
    if isinstance(v, Y):
        return _locate(board, occ, v.ref, placed).y + v.dy
    if isinstance(v, (PadRef, CellPadRef, Location, tuple, Mid, Part, Cell, LanePoint, FigurePoint, Origin)):
        l = _locate(board, occ, v, placed)
        return l.x if axis == "x" else l.y
    if isinstance(v, Polar):
        if v.radius is None or v.angle is None:
            raise ValueError("a Polar as a point needs both its radius and its bearing; %r leaves one free" % (v,))
        l = _locate(board, occ, v, placed)
        return l.x if axis == "x" else l.y
    if isinstance(v, RowCoord):
        return v.row.resolve(v.what, occ.board_box)
    return float(v)


_RIDE_PROBE = (1.37, -0.73)
# the facts of an `unplaced.pocket` finding that finding_text.pocket_note reads
_POCKET_NOTE_KEYS = ("variant", "w_mm", "h_mm", "face", "tried", "scanned", "budget", "riders")
"""How far _ride_turn moves an item to see whether its riders move with it:
off any grid a search walks, on both axes."""


@dataclass
class _Tried:
    """One standing of an item scanned (`Board._scan_one`)."""
    j: PlaceIntent
    hint: Placement
    radius: float
    result: ScanResult | None
    face_note: dict | None
    ahead: object
    score: object
    hopeless: dict | None = None
    faces: dict | None = None       # each face scanned -> its own ScanResult (`Board._scan_faces`)


@dataclass
class _Trial:
    """One arrangement of a decided cell laid at its spot (`Board._firm_trials`): its id ("" the default), the arranged intent,
    where its declaration puts it, the note of which pad a net named, its refusal (None when legal), and its score there (None
    when it is not legal or nothing prices it)."""
    ident: str
    j: PlaceIntent
    placement: Placement
    chose: dict | None
    why: object
    score: float | None
    tight: float | None = None      # how much nearer than its box a Beside laid it (`Board._tight`), None when not nearer


@dataclass
class _Scanned:
    """The scans of every arrangement of an item (`Board._scan_arrangements`) and which stands: the winner's _Tried, its
    ScanResult and face note (every arrangement's refusals merged when none has a legal spot), the step's arrangement note, and,
    when none has a legal spot, the refusals as records, each tagged with the arrangement it came from (none for the default)."""
    won: "_Tried | None"
    tried: list
    result: ScanResult
    face_note: dict | None
    note: dict | None
    reasons: list


class _Redo(Exception):
    """A run of the resolve that stops after its firm items, for the next to place them against what it found."""

    def __init__(self, seed: dict, swaps: list, notes: dict, loose: frozenset, arr: dict | None = None):
        super().__init__("the firm items are placed again")
        self.seed, self.swaps, self.notes, self.loose = seed, swaps, notes, loose
        self.arr = dict(arr or {})          # the arrangement each firm cell took in this run ("" the default)


class _Out:
    """What a resolve reports while it goes (progress lines, steps, begins, the partial reuse log), held until the run is known
    to stand, so a run that is placed again does not report its firm items twice."""

    def __init__(self, progress, on_step, on_begin, partial):
        self.queue = []
        self.progress = self._later(progress)
        self.on_step = self._later(on_step)
        self.on_begin = self._later(on_begin)
        self.partial = None if partial is None else _OutPartial(self, partial)

    @classmethod
    def through(cls, progress, on_step, on_begin, partial):
        out = cls(progress, on_step, on_begin, partial)
        out.queue = None
        return out

    def _later(self, f):
        if f is None:
            return None

        def call(*a):
            if self.queue is None:
                return f(*a)
            self.queue.append((f, a))
        return call

    def flush(self) -> None:
        queue, self.queue = self.queue, None
        for f, a in queue or ():
            f(*a)


class _OutPartial:
    def __init__(self, out: _Out, real):
        self._out, self._real = out, real

    def begin(self, *a):
        self._out._later(self._real.begin)(*a)

    def append(self, *a):
        self._out._later(self._real.append)(*a)


def _rooms_moved(old: dict, new: dict, tol: float) -> list:
    """[(copper key, mm)] for each declaration whose planned shapes differ from the last pass's by more than `tol`; a
    different count of shapes counts as moved by the most any of them could."""
    out = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k, []), new.get(k, [])
        if len(a) != len(b) or any(len(x.poly) != len(y.poly) for x, y in zip(a, b)):
            gap = float("inf")
        else:
            gap = max([abs(p - q) for x, y in zip(a, b) for u, v in zip(x.poly, y.poly) for p, q in zip(u, v)] or [0.0])
        if gap > tol:
            key = (a or b)[0].owner[len("room "):] if (a or b) else str(k)
            out.append((key, round(gap, 3) if gap != float("inf") else -1.0))
    return out


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


class _LaneEnv:
    """What a laid-out escape asks of the board (lanes.py): the clearances the
    script's rules give, and what already stands where a lane or a via would."""

    def __init__(self, board: "Board", occ, decl: EscapeDecl, pads: dict, face: Face):
        self.board = board
        self.occ = getattr(occ, "_occ", occ)            # a candidate's view reads the real occupancy's copper
        self.layer = face.copper
        s = board.settings
        self.step, self.reach = s.place_escape_via_step, s.place_escape_via_reach
        self.hole_to_hole = board.geometry.hole_to_hole
        self.own = [sh for shapes in pads.values() for sh in shapes]
        self.ref = decl.ref
        self._obstacles = None

    def clearance(self, net_a: str, net_b: str, owner_b=None) -> float:
        if owner_b:
            return _pad_clearance(self.board, net_a, net_b, owner_b)
        return _net_clearance(self.board, net_a, net_b)

    def width(self, net: str) -> float:
        return self.board._width(net, None)

    def pair_gap(self, net: str) -> float:
        nc = self.board.geometry.netclass(net)
        return nc.diff_pair_gap or self.clearance(net, net)

    def via_site(self, at: Location, net: str, size: float, drill: float):
        """Why a via of `net` may not stand at `at` among what is placed (the
        edge, other nets' copper, holes, keepouts), or None."""
        ctx = self.board.__dict__.get("_escape_ctx") or _CopperContext(self.board, self.occ)
        if self._obstacles is None:
            self._obstacles = self.board._via_obstacles(ctx)
        return self.board._via_site_why(ctx, at, net, size, drill, self._obstacles)

    def hits(self, op) -> list:
        """What copper `op` (a lane's track or via) meets among what is placed: the
        pads and copper of other nets within their clearance, and unplated holes."""
        occ = self.occ
        shape = _shape_of(op)
        out = list(occ.copper_conflicts(shape))
        if self.ref in occ.pending:                     # a candidate: its own pads are not in the occupancy yet
            out += [why for o in self.own if (why := occ._conflict(shape, o, None, exact=True))]
        for ref, g in occ.items.items():
            if ref in occ.pending:
                continue
            for o in g.shapes:
                if o.kind == "npth" and shape.box.overlaps(o.box, gap=occ._copper_reach):
                    why = occ._conflict(shape, o, None, exact=True)
                    if why:
                        out.append(why)
        return out


class CutoutNowhere(Exception):
    """A hole or a region that has nowhere legal to go: `why` is the Refusal, of code cutout_nowhere."""

    def __init__(self, why):
        super().__init__(str(why))
        self.why = why


class _CopperContext:
    def __init__(self, board: Board, occ: Occupancy):
        self.board, self.occ = board, occ
        self.planned_tracks: list = []     # every track planned so far (any batch)
        self.fields: dict = {}             # part -> the carried vias of its grids, lifted off the board while a batch is planned
        self.fixed_tracks: list = []       # tracks from the FIXED batch: never yield
        self.notes = Findings()            # findings a copper plan raises about itself, each of its own kind

        self.planned_vias: list = []       # every via planned so far, for a FreeSpot's hole rule
        self.planned_tails: list = []      # every FreeSpot tail planned so far: not in the occupancy until the batch ends
        self.batch_tracks: list = []       # tracks planned so far in the batch being planned: not in the occupancy yet
        self.batch_ops: list = []          # every op planned so far in that batch, for a fitted pour to keep clear of
        self.via_at: dict = {}             # via intent index -> where it landed, for a track ending on it
        self.pour_at: dict = {}            # pour intent index -> its drawn points, for a stitch over it
        self.ops_at: dict = {}             # copper intent index -> the ops its plan gave, for a Past over it
        self.plan = None                   # the plan being built: its keepouts, for a FreeSpot
        self.dry = False                   # planned for the room it keeps, committed nowhere: a fitted pour has no reach

    def note(self, cause, facts: dict, severity: str = "warning") -> None:
        """A finding about a declaration that is not drawn as asked, a person's call."""
        self.notes.append(Finding(cause, facts, severity))

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


def _copper_name(occ: Occupancy, sh: Shape) -> dict:
    """How a finding names a piece of copper standing in a fitted pour's way (finding_text._blocker)."""
    if sh.kind in ("pad", "through") and sh.owner:
        return {"form": "pad", "who": occ._w(sh.owner), "label": sh.label, "net": sh.net}
    if sh.circle:
        return {"form": "via", "net": sh.net, "at": [sh.circle[0], sh.circle[1]]}
    if sh.ends:
        return {"form": "track", "net": sh.net, "ends": [list(sh.ends[0]), list(sh.ends[1])], "arc": bool(sh.arc)}
    if sh.owner:
        return {"form": "owned", "who": occ._w(sh.owner), "net": sh.net}
    return {"form": "pour", "net": sh.net}


def _span_text(span: tuple) -> str:
    return "%s-%s" % (span[0].value, span[-1].value)


def _span_of(span: tuple) -> list:
    """The two ends of a via's span, as the layers' names."""
    return [span[0].value, span[-1].value]


def _edge_loops(occ: Occupancy) -> list:
    """The board's edge as closed polylines: its outline, and each cutout's."""
    shape = occ.board_shape
    if shape is None:
        loops = [tuple(box_polygon(occ.board_box))] if occ.board_box is not None else []
        return loops + list(occ.board_cutouts.loops if occ.board_cutouts else ())
    if hasattr(shape, "loops"):
        return list(shape.loops)
    return [tuple(shape.polygon())] + list(shape.cutouts.loops)


def _pad_shapes(board: "Board", occ: Occupancy, ref) -> list:
    """The Shape(s) of one pad, as placed now: usually one, but a pin of
    several apart lands (occupancy.py) carries more than one; a PadRef's
    `land=` names one of them."""
    owner, number, _, _ = board._pad_ref(ref)
    return occ.pad_shapes(owner, number, board._pad_land(ref))



def _edge_point(board: "Board", occ: Occupancy, width: float, ref: PadRef,
                along_width: float | None = None) -> Location:
    """A point on `ref.edge` of its pad (the side of the pad's copper box,
    board frame) for copper `width` across the edge: half the width outside
    the edge, less `[copper] tap_overlap`, so the copper lies against it. A track's
    copper is as wide along the edge as across it; a placed pad's is
    `along_width`. Along the edge, `ref.along`: MID the middle, START the
    west or north end, END the other, half the copper's width along in from
    the corner so it ends flush with the pad's side. The copper there must
    meet the pad's along the edge: an end of a round pad's edge, or of one
    turned off the right angle, has none, and is refused."""
    owner, number, _, _ = board._pad_ref(ref)
    polys = [sh.poly for sh in _pad_shapes(board, occ, ref)]
    box = Box.union([Box.of_points(p) for p in polys])
    upright = ref.edge in (Edge.EAST, Edge.WEST)            # the edge runs north-south: along is y
    line = {Edge.NORTH: box.top, Edge.SOUTH: box.bottom, Edge.WEST: box.left, Edge.EAST: box.right}[ref.edge]
    on = [(y if upright else x) for p in polys for x, y in p if abs((x if upright else y) - line) <= 1e-3]
    lo, hi = (box.top, box.bottom) if upright else (box.left, box.right)
    along = ref.along or Along.MID
    half = width / 2.0
    half_along = half if along_width is None else along_width / 2.0
    at = {Along.START: lo + half_along, Along.MID: (lo + hi) / 2.0, Along.END: hi - half_along}[along]
    reach = (at, at) if along is Along.MID else (at - half_along, at + half_along)
    if not on or min(on) > reach[1] + 1e-6 or max(on) < reach[0] - 1e-6 or \
            (along is not Along.MID and min(hi, max(on)) - max(lo, min(on)) < 1e-3):
        raise ValueError("%s pad %s: its %s edge has no copper at its %s (a round pad, or one turned off the "
                         "right angle); use Along.MID" % (occ.who(owner), number, ref.edge.name.lower(),
                                                                along.name.lower()))
    out = half - board.settings.copper_tap_overlap
    if ref.edge is Edge.EAST:
        return Location(round(line + out, 6), round(at, 6))
    if ref.edge is Edge.WEST:
        return Location(round(line - out, 6), round(at, 6))
    if ref.edge is Edge.NORTH:
        return Location(round(at, 6), round(line - out, 6))
    return Location(round(at, 6), round(line + out, 6))                  # SOUTH


def _pad_half_across(board: "Board", occ: Occupancy, ref, centre: Location, ux: float, uy: float) -> float:
    """How far the pad reaches from `centre` along the unit normal
    (-uy, ux): half the pad's own width measured across a run whose
    direction is (ux, uy), whatever the pad's own rotation."""
    nx, ny = -uy, ux
    return max(abs((px - centre.x) * nx + (py - centre.y) * ny)
              for sh in _pad_shapes(board, occ, ref) for px, py in sh.poly)


def _pad_clearance(board: "Board", net: str, pad_net: str, pad_owner=None) -> float:
    """The clearance a track of `net` keeps from a pad of `pad_net` (of part
    `pad_owner`, for a rule within a cell): `Board._clearance`, which is the
    board default when the pad has no net (occupancy.py's copper_conflicts
    falls back the same way) - a corner-reference pad with GetNetCode() <= 0
    names no netclass to look up."""
    return board._clearance(net, pad_net, None, pad_owner)


def _net_clearance(board: "Board", a: str, b: str) -> float:
    """The clearance between copper of two nets (`Board._clearance`); the
    board default when either has no net (as `_pad_clearance` falls back)."""
    return board._clearance(a, b)


def _lane_distance(board: "Board", own: str, shapes: list, lane, width=None, own_owner=None) -> float:
    """How far a pad of net `own` (of part `own_owner`) stands past the copper
    of `shapes`: the worst clearance between them, or with `lane` a net, room
    for one track of it between - the clearance from the copper to the lane,
    the lane's width (`width`, else its track width) and the clearance from
    the lane to the pad."""
    if lane is None:
        return max(board._clearance(own, sh.net, own_owner, sh.owner) for sh in shapes)
    name = board.geometry.require_net(lane)
    return (max(board._clearance(sh.net, name, sh.owner) for sh in shapes) + board._width(name, width)
            + board._clearance(name, own, None, own_owner))


def _between_point(board: "Board", ctx: "_CopperContext", net: str, width: float, p: Between) -> Location:
    """Between(a, b)'s point: the midpoint of the gap's centreline, and a
    note when the gap does not fit the track and its clearance to each
    pad."""
    from .geometry import poly_distance
    sa, sb = _pad_shapes(board, ctx.occ, p.a), _pad_shapes(board, ctx.occ, p.b)
    gap = min(poly_distance(x.poly, y.poly) for x in sa for y in sb)
    # clearance is to each pad's net: a pad of the track's own net asks none
    need = width + sum(0.0 if sh.net == net else _pad_clearance(board, net, sh.net, sh.owner) for sh in (sa[0], sb[0]))
    if gap < need - 1e-6:
        oa, na, _, _ = board._pad_ref(p.a)
        ob, nb, _, _ = board._pad_ref(p.b)
        ctx.note(C.COPPER_NOTE, {"variant": "between_gap", "net": net, "a": [oa, na], "b": [ob, nb], "gap_mm": gap,
                                 "width_mm": width, "need_mm": need})
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


def _past_unplanned(ops_at: dict, it, what: str, current: int | None) -> Refusal | None:
    """Why the via or track `it`, named by `what`'s Past, has no copper to
    stand off: declared after `what`, or planned and drawing nothing. None
    when it has copper."""
    if it.index not in ops_at:
        if current is not None and it.index > current:
            return Refusal(Code.PAST_AFTER, key=it.key, what=what)
        return Refusal(Code.PAST_NOT_PLANNED, key=it.key)
    if not any(isinstance(op, (Via, Track)) for op in ops_at[it.index]):
        return Refusal(Code.PAST_NO_VIA) if it.key.startswith("via") else Refusal(Code.PAST_NO_TRACK)
    return None


def _past_names(board: "Board", p: Past) -> list:
    """What a Past's items are called in a finding: a via's or track's key,
    a pad's refdes and number."""
    return [it.key if isinstance(it, CopperIntent) else "%s.%s" % board._pad_ref(it)[:2] for it in p.items]


def _past_copper(board: "Board", occ: Occupancy, ops_at: dict, p: Past, what: str,
                 current: int | None = None, layer: CopperLayer | None = None):
    """(net, box, owner, name) for every piece of copper `p.items` names: each pad's
    shapes, each via's ring and each track's segments, as the polygons the
    clearance check measures. With `layer`, only the copper on that layer: a
    pad's own layers, a via's span, a track's layer. A Refusal instead when a
    via or track has no copper (see `_past_unplanned`)."""
    out = []
    for it, name in zip(p.items, _past_names(board, p)):
        if isinstance(it, CopperIntent):
            why = _past_unplanned(ops_at, it, what, current)
            if why is not None:
                return why
            for op in ops_at[it.index]:
                if isinstance(op, (Via, Track)):
                    if layer is not None and (op.layer is not layer if isinstance(op, Track)
                                              else op.layers and layer not in op.layers):
                        continue
                    # its polygon's box: the copper the clearance check measures, a via's ring a
                    # little outside the true circle
                    out.append((op.net, op.box, "", name))
        else:
            out += [(sh.net, sh.box, sh.owner, name) for sh in _pad_shapes(board, occ, it)
                    if layer is None or layer in sh.layers]
    return out


def _past_reach(board: "Board", ctx: "_CopperContext", net: str, width: float, p: Past, what: str,
                current: int | None = None, layer: CopperLayer | None = None):
    """(the items' combined box, `width`/2 plus the worst clearance by net
    pair from `net` to them): what Past's point is measured from. A Refusal
    instead, the reason, when a via or track it names has no copper.

    With `layer` it is the verdict's reach instead: (box, distance, names)
    of the items' copper on that layer alone, or None when there is none.
    The point's lane is taken off every item, whatever face it is on."""
    copper = _past_copper(board, ctx.occ, ctx.ops_at, p, what, current, layer)
    if isinstance(copper, Refusal):
        return copper
    if layer is not None:
        if not copper:
            return None
        names = list(dict.fromkeys(nm for *_, nm in copper))
        return (Box.union([c[1] for c in copper]),
                width / 2.0 + max(_pad_clearance(board, net, c[0], c[2]) for c in copper), names)
    return (Box.union([c[1] for c in copper]),
            width / 2.0 + max(_pad_clearance(board, net, c[0], c[2]) for c in copper))


def _box_corner(box: Box, corner: Corner) -> Location:
    sx, sy = corner.signs
    return Location(box.right if sx > 0 else box.left, box.bottom if sy > 0 else box.top)


def _lane_dirs(corner: Corner) -> set:
    """The two directions of a 45 across `corner`'s outward diagonal."""
    sx, sy = corner.signs
    return {(1, -sx * sy), (-1, sx * sy)}


def _past_point(board: "Board", ctx: "_CopperContext", net: str, width: float, p: Past, what: str,
                current: int | None = None):
    """Past(items, edge)'s point for copper of `net`: `width`/2 plus the
    worst clearance by net pair off the items' combined box on `edge`,
    across it where `across` says (default the middle of the box's side).
    At a `Corner`, that far out from the box's corner on its outward
    diagonal. Rounded away from the items. A Refusal instead, the reason,
    when a via or track it names has no copper."""
    reach = _past_reach(board, ctx, net, width, p, what, current)
    if isinstance(reach, Refusal):
        return reach
    box, off = reach
    if isinstance(p.edge, Corner):
        sx, sy = p.edge.signs
        c = _box_corner(box, p.edge)
        d = off / math.sqrt(2.0)
        return Location(_round_away(c.x + sx * d, sx), _round_away(c.y + sy * d, sy))
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
        at = _edge_point(board, ctx.occ, width, a) if getattr(a, "edge", None) is not None else ctx.locate(a)
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


_SIDE_WORD = {Edge.NORTH: "north", Edge.EAST: "east", Edge.SOUTH: "south", Edge.WEST: "west"}
_SIDE_BEARING = {Edge.NORTH: 0.0, Edge.EAST: 90.0, Edge.SOUTH: 180.0, Edge.WEST: 270.0}


def _stitch_outside_rows(poly, turn: float, off: float, step: float, wanted) -> list:
    """[(side, board side, [(distance along the row, (x, y)), ...])] of `stitch(outside=True)`:
    one row per edge of `poly` whose outward normal, read in the region's own
    frame (turned back by `turn`, a clockwise bearing), is within 45 degrees of
    a side in `wanted` (None: every edge). A row stands `off` out from its edge
    along the normal and runs end to end, `ceil(L / step) + 1` points evenly
    spread. Where two kept edges meet at a corner, both rows end on the one
    point where their offset lines cross, so the corner has one via. Where a kept
    edge meets one not kept (at a convex corner), the row ends `off` in from
    that edge's line, so a via never stands on a side left unkept. Collinear
    vertices are one edge."""
    pts = list(poly)
    i = 0
    while len(pts) > 3 and i < len(pts):                   # drop a vertex that lies on the line through its neighbours
        (ax, ay), (bx, by), (cx, cy) = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
        if abs((bx - ax) * (cy - by) - (by - ay) * (cx - bx)) < 1e-9 * max(1.0, math.hypot(cx - ax, cy - ay)):
            del pts[i]
            i = max(i - 1, 0)
        else:
            i += 1
    n = len(pts)
    sign = 1.0 if sum(pts[k][0] * pts[(k + 1) % n][1] - pts[(k + 1) % n][0] * pts[k][1] for k in range(n)) > 0 else -1.0
    edges = []                                              # (start, end, length, outward normal, side or None)
    for k in range(n):
        (ax, ay), (bx, by) = pts[k], pts[(k + 1) % n]
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-9:
            edges.append(None)
            continue
        nx, ny = sign * (by - ay) / length, -sign * (bx - ax) / length
        bearing = math.degrees(math.atan2(nx, -ny))
        local = (bearing - turn) % 360.0
        board_side = min((Edge.NORTH, Edge.EAST, Edge.SOUTH, Edge.WEST),
                         key=lambda e: abs((bearing % 360.0 - _SIDE_BEARING[e] + 180.0) % 360.0 - 180.0))
        faces = [e for e, b in ((Edge.NORTH, 0.0), (Edge.EAST, 90.0), (Edge.SOUTH, 180.0), (Edge.WEST, 270.0))
                 if abs((local - b + 180.0) % 360.0 - 180.0) <= 45.0 + 1e-6]
        hit = next((e for e in faces if wanted is None or e in wanted), None)
        edges.append((pts[k], pts[(k + 1) % n], length, (nx, ny), hit, board_side))

    def end_of(e, f, at_start: bool):
        (ax, ay), (bx, by), _, (nx, ny), _, _ = e
        vx, vy = (ax, ay) if at_start else (bx, by)
        if f is not None and f[4] is not None:
            dot = nx * f[3][0] + ny * f[3][1]
            if dot > -1.0 + 1e-6:                           # the offset lines cross at the corner's outside
                k = off / (1.0 + dot)
                return vx + k * (nx + f[3][0]), vy + k * (ny + f[3][1])
        elif f is not None:
            # a side not kept meets this one at a convex corner: the row ends where it stands `off` in from that
            # side's line, the same distance the shared corner's via stands out from both lines
            fx, fy = f[3]
            dot = nx * fx + ny * fy
            wx, wy = f[0] if at_start else f[1]             # the far end of the unkept side
            if dot < 1.0 - 1e-6 and (wx - vx) * nx + (wy - vy) * ny < 0:
                k = off / (1.0 - dot)
                return vx + k * (nx - fx), vy + k * (ny - fy)
        return vx + off * nx, vy + off * ny

    rows = []
    for k, e in enumerate(edges):
        if e is None or e[4] is None:
            continue
        a = end_of(e, edges[k - 1], True)
        b = end_of(e, edges[(k + 1) % n], False)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        count = max(1, math.ceil(length / step - 1e-9))
        rows.append((e[4], e[5], [(length * i / count, (a[0] + (b[0] - a[0]) * i / count, a[1] + (b[1] - a[1]) * i / count))
                            for i in range(count + 1)]))
    return rows


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
        elif isinstance(p, LanePoint):
            out.append(p.lane.part)             # a lane's point waits for its part
        elif isinstance(p, (X, Y)):
            out += _refs_in([p.ref])        # the ref may itself be a point or a pad
        elif isinstance(p, FreeSpot):
            out += _refs_in([p.near])       # the pad it searches from must be placed first
        elif isinstance(p, Mid):
            out += _refs_in([p.a, p.b])
        elif isinstance(p, FigurePoint):
            out += _refs_in([p.figure.at] + ([p.figure.rotation.part] if isinstance(p.figure.rotation, Turned) else []))
        elif isinstance(p, Origin):
            out += _refs_in([p.item])       # its part or cell is placed first
        elif isinstance(p, Bearing):
            out += _refs_in([p.a, p.b])
        elif isinstance(p, Polar):
            out += _refs_in([p.about, p.angle])
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


def _via_kind(span: tuple) -> str:
    """A via's type from its span of the board's layers: micro (an outer face
    and the layer next to it), blind (from an outer face, deeper), or buried
    (inner layers only)."""
    if _is_micro(span):
        return "micro"
    return "blind" if any(l.face is not None for l in span) else "buried"


def _is_micro(span: tuple) -> bool:
    """Whether a via's span is a micro via's: an outer face and the layer
    next to it."""
    return len(span) == 2 and any(l.face is not None for l in span)


def _posed_footprint(fp: Footprint, pose: Placement) -> Footprint:
    """`fp` with its place and its pads moved to `pose`, where an arrangement stands it (what drops= reads of a member)."""
    t = pose_transform(Placement(fp.location, fp.rotation, fp.face), pose)
    pads = tuple(dataclasses.replace(p, outlines=tuple(transform_polygon(o, t) for o in p.outlines), box=transform_box(p.box, t),
                                     anchor=None if p.anchor is None else t.apply_location(p.anchor)) for p in fp.pads)
    return dataclasses.replace(fp, location=pose.location, rotation=pose.rotation, face=pose.face, pads=pads)


def _checkerboard(points) -> set:
    """The indices of `points` (a via field in its part's frame) that one
    colour of a checkerboard over its grid keeps: a via's column and row are
    the ranks of its x and y among the field's, to a micron, and the vias
    whose two ranks add to an even number stay."""
    xs = sorted({round(x, 3) for x, _ in points})
    ys = sorted({round(y, 3) for _, y in points})
    return {k for k, (x, y) in enumerate(points) if (xs.index(round(x, 3)) + ys.index(round(y, 3))) % 2 == 0}


def _spread(points, n: int) -> set:
    """The indices of `n` of `points` spread over the field: the one nearest
    its centre first, then each time the one farthest from those kept (on a
    tie, the one farther from them all together, then the first by row)."""
    if n >= len(points):
        return set(range(len(points)))
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    order = sorted(range(len(points)), key=lambda k: (round(points[k][1], 6), round(points[k][0], 6)))
    kept = [min(order, key=lambda k: round(math.hypot(points[k][0] - cx, points[k][1] - cy), 6))]
    while len(kept) < n:
        def far(k):
            d = [math.hypot(points[k][0] - points[j][0], points[k][1] - points[j][1]) for j in kept]
            return (round(min(d), 6), round(sum(d), 6))
        kept.append(max((k for k in order if k not in kept), key=far))
    return set(kept)


def _op_layers(op) -> frozenset:
    """The copper layers a drawn op occupies. A through via joins the whole
    stack, so a region covering any one layer contains it; a via of a span,
    the layers it spans."""
    if isinstance(op, Via):
        return frozenset(op.layers) or frozenset(CopperLayer)
    return frozenset([op.layer])


def _via_intent_at(board: "Board", ctx, net: str, x: float, y: float):
    """The copper declaration whose planned via of `net` stands at (x, y), or None. `ops_at` is keyed by `CopperIntent.index`,
    which is not the position in `board._copper` once an arrangement has left out copper its `only=` excludes."""
    for index, ops in (getattr(ctx, "ops_at", None) or {}).items():
        for op in ops:
            if isinstance(op, Via) and op.net == net and abs(op.at.x - x) < 1e-6 and abs(op.at.y - y) < 1e-6:
                return next((c for c in board._copper if c.index == index), None)
    return None


def _shape_of(op) -> Shape | None:
    both = frozenset([Face.FRONT, Face.BACK])
    if isinstance(op, Track):
        faces = frozenset([op.layer.face]) if op.layer.face else frozenset()
        return Shape("", "copper", faces, frozenset([op.layer]), op.net, op.polygon, op.box,
                    ends=((op.start.x, op.start.y), (op.end.x, op.end.y)), wire=True,
                    arc=() if op.mid is None else (op.mid.x, op.mid.y),
                    segment=(op.start.x, op.start.y, op.end.x, op.end.y, op.width) if op.mid is None else ())
    if isinstance(op, Via):
        faces = frozenset(l.face for l in op.layers if l.face is not None) if op.layers else both
        return Shape("", "through", faces, _op_layers(op), op.net, op.polygon, op.box,
                     circle=(op.at.x, op.at.y, op.size / 2.0), wire=True)
    if isinstance(op, Pour):
        faces = frozenset([op.layer.face]) if op.layer.face else frozenset()
        poly = op.polygon
        if op.stroke > 0:                       # the copper reaches half the stroke past its outline
            from .pourfit import offset
            poly = offset(poly, op.stroke / 2.0)
        return Shape("", "copper", faces, frozenset([op.layer]), op.net, poly, Box.of_points(poly),
                     drawn=((op.polygon,), op.stroke, True))
    return None            # a zone pulls back round everything; it is never an obstacle


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


for _method, _keys in _SITED.items():
    setattr(Board, _method, _sited(_method, _keys)(getattr(Board, _method)))
