"""The typed values a layout script uses: layers, faces, edges, priorities,
locations, boxes, and references to nets, parts, cells and pads."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
import math

from .cutouts import Cutouts


class _CopperLayerNames(str, Enum):
    """The behaviour of a copper layer, without its members: they are
    generated below, because there are thirty-two of them and writing them
    out would be thirty-two lines of noise."""

    @property
    def face(self) -> "Face | None":
        if self is type(self).F:
            return Face.FRONT
        if self is type(self).B:
            return Face.BACK
        return None

    @property
    def other_face(self) -> "CopperLayer":
        if self is type(self).F:
            return type(self).B
        if self is type(self).B:
            return type(self).F
        raise ValueError("%s is an inner layer; it has no opposite face" % self.value)

    @classmethod
    def of(cls, name: "str | CopperLayer") -> "CopperLayer":
        if isinstance(name, cls):
            return name
        for member in cls:
            if member.value == name:
                return member
        raise ValueError("unknown copper layer %r: the layers are F.Cu, In1.Cu to In30.Cu, and B.Cu"
                         % (name,))


# KiCad's maximum is 32 copper layers, and it names them F.Cu, In1.Cu upward,
# and B.Cu. Naming all of them is what stops a board with a deep stackup being
# read as though the layers placemat has no name for were not there.
_COPPER_LAYER_NAMES = {"F": "F.Cu", "B": "B.Cu"}
_COPPER_LAYER_NAMES.update({"IN%d" % n: "In%d.Cu" % n for n in range(1, 31)})

CopperLayer = _CopperLayerNames("CopperLayer", _COPPER_LAYER_NAMES)


class Face(str, Enum):
    FRONT = "front"
    BACK = "back"

    @property
    def copper(self) -> CopperLayer:
        return CopperLayer.F if self is Face.FRONT else CopperLayer.B


class Edge(str, Enum):
    NORTH = "N"
    SOUTH = "S"
    EAST = "E"
    WEST = "W"


class Corner(str, Enum):
    """A corner of a box, for `Past(items, Corner.NE)`: the point off it on
    its outward diagonal."""
    NE = "NE"
    NW = "NW"
    SE = "SE"
    SW = "SW"

    @property
    def signs(self) -> tuple:
        """(x, y) of the outward diagonal, each 1 or -1; y grows downward, so
        north is -1."""
        return {"NE": (1, -1), "NW": (-1, -1), "SE": (1, 1), "SW": (-1, 1)}[self.value]


class Axis(str, Enum):
    """One dimension of a fit frame: `board.size(fit=Axis.X)` fits that one
    to its content and takes the other's number as declared."""
    X = "x"
    Y = "y"


class Along(str, Enum):
    """A named distance along an edge, of its usable length (keep-in to keep-in)."""
    START = "start"
    MID = "mid"
    END = "end"

    @property
    def fraction(self) -> float:
        return {"start": 0.0, "mid": 0.5, "end": 1.0}[self.value]


class Line(str, Enum):
    """How a row's items align across the row, from the edge inward."""
    CENTRE = "centre"
    OUTER = "outer"
    INNER = "inner"


class Cover(str, Enum):
    """What a pour drawn as declared (no `swallow_pads`) whose corners name
    pads covers: HULL, the convex hull of those pads' copper (and any plain
    points); BOX, the box round it; CENTRES (the default), the polygon
    through the points as given, a pad at its centre. A pour over pads with
    `swallow_pads=True` is fitted round other copper and takes none."""
    HULL = "hull"
    BOX = "box"
    CENTRES = "centres"


class Bend(str, Enum):
    """Which end of an off-grid track leg takes its 45: the diagonal touches
    that pad end, a straight run carries the rest of the leg; BOTH puts a
    45 at each end with a straight between. Unset (the default), the
    planner picks: the fewest turns against the legs either side, then the
    shortest, then its own tie-break (the 45 at the pad end)."""
    START = "start"
    END = "end"
    BOTH = "both"


class Land(str, Enum):
    """Which land of a pin drawn as several a `PadRef` names by quality
    rather than by index: LARGEST, the one of most copper area (the first
    in the footprint's order on a tie)."""
    LARGEST = "largest"


class Drops(str, Enum):
    """How much of a placed cell's via fields it keeps. A field is the
    drops (vias of a net the board declares a `plane()` for) inside one of
    its members' pads. ALL keeps them as stamped; HALF every other via of
    each field, a checkerboard over its grid; MIN each field at the
    `place.drops_keep` share, rounded up and never fewer than one."""
    ALL = "all"
    HALF = "half"
    MIN = "min"


class Forbid(str, Enum):
    """What a keepout keeps out of its region."""
    PARTS = "parts"
    FILL = "fill"
    TRACKS = "tracks"
    VIAS = "vias"
    PADS = "pads"


@dataclass(frozen=True)
class Centre:
    """A place for an item's body centre. Each axis is a number, a reference
    (X()/Y() of a pad, or a Mid inside X()/Y()), or None to leave that axis
    free: Centre(30, None) pins x and lets the item slide in y. `toward=`
    an Edge at one end of the free axis takes the legal spot farthest that
    way, instead of the one nearest what the item connects to."""
    x: object
    y: object
    toward: object = field(default=None, metadata={"omit_default": True})

    def __post_init__(self):
        if self.x is None and self.y is None:
            raise ValueError("a Centre needs at least one axis")
        if self.toward is not None:
            ends = {"x": (Edge.EAST, Edge.WEST), "y": (Edge.NORTH, Edge.SOUTH)}.get(self.free_axis)
            if ends is None or self.toward not in ends:
                raise ValueError("Centre(toward=%r): toward names an end of the free axis (%s)" % (
                    self.toward, " or ".join(e.name for e in ends) if ends else "this Centre has none"))

    @property
    def free_axis(self) -> str | None:
        return "x" if self.x is None else "y" if self.y is None else None


@dataclass(frozen=True)
class Pin:
    """A place for one of the item's own pads: the pad `key` (a number or a
    net name) lands on a point, and the part sits round it at its rotation.
    The point is `Pin(key, point)`, any place a script can name (a Location,
    a pad reference, a PadRef with `edge=`), or `Pin(key, x, y)`, each axis a
    number or a reference. How a part is put where its pin must be: a cap's
    pad on a pin's axis, a diode's pad facing another's, a net tie's pad
    against another pad's edge."""
    key: object
    x: object
    y: object = None            # None: x is the point

    def __post_init__(self):
        if self.x is None or (self.y is None and isinstance(self.x, (int, float))):
            raise ValueError("a Pin places the pad on a point: Pin(key, point) or Pin(key, x, y)")

    @property
    def axes(self) -> tuple:
        """What each axis is said in: (x, y), or the one point twice."""
        return (self.x, self.x) if self.y is None else (self.x, self.y)


@dataclass(frozen=True)
class OnEdge:
    """A place on a board edge: the item's reach at the keep-in (or
    `overhang` past it), and `along` the edge a number in mm, a reference,
    Along.START/MID/END or Fraction(f) of the usable length. With no
    `along` the item slides along the edge to the room that is left.

    `edge` is an Edge - a side of a rectangular board, where `along` is a
    coordinate - or a run off `board.edge(facing=)`, a stretch of an outline
    of any shape, where `along` is measured as length from the run's start
    and the item is turned to the way the board faces there."""
    edge: Edge
    along: object = None
    overhang: float = 0.0

    def __post_init__(self):
        if not isinstance(self.edge, (Edge, CutoutEdge)) and \
                not (hasattr(self.edge, "at") and hasattr(self.edge, "length")):
            raise TypeError("OnEdge takes an Edge, a run off board.edge(facing=), or a cutout's "
                            "board.cutout(name).edge(side=), not %r" % (self.edge,))
        if self.along is not None and not isinstance(self.along, (int, float, X, Y, Mid, Along, Fraction)) \
                and type(self.along).__name__ != "_RowSlot":
            raise TypeError("along is a number, a reference, Along.START/MID/END or Fraction(f), not %r" % (self.along,))


@dataclass(frozen=True)
class Beside:
    """A place at another item's side: the item's drawn envelope, `gap`
    from `item`'s (default: the envelope's own gap - the widest of the net
    clearance, the component spacing and the silk clearance, or courtyards
    touching under a courtyard envelope), on `side`. `item` is a Part, a
    Cell or a keepout (what `board.keepout(...)` returns); it is placed
    before this waits for it.

    `align` lines the part up across `side`:
    - a `PadRef`: this part's own pad on the same net lands level with it;
    - `(own_pad, their_pad)`: an own pad key and a `PadRef`, for when the
      nets differ;
    either pad may be `item`'s or any other part's placed firmly by then;
    - `(own_pad, Past(pads, edge, lane=))`: the own pad's facing edge the
      clearance past the pads' `edge` side, or with `lane=` a net, room for
      one track of it between them;
    - an `Along` of `item`'s side (default `Along.MID`).

    `copper=True` measures the standoff from copper, not envelopes: the part
    stands as near `item` on `side` as its pads allow, every pad of it
    keeping, from every pad of `item` (a cell's members') of another net,
    the clearance the pair needs plus `gap` (default 0.0, with no envelope
    floor); pads of one net set no distance. Its body, courtyard and silk
    are judged afterwards as for any placement.

    Firm, like `Pin`: the position is decided, not searched. The
    rotation is what the script gave, or its default - `Beside` does not
    turn the part to face `item`."""
    item: object
    side: Edge
    align: object = None
    gap: float | None = None
    copper: bool = field(default=False, kw_only=True, metadata={"omit_default": True})

    def __post_init__(self):
        if not isinstance(self.side, Edge):
            raise TypeError("Beside's side is an Edge, not %r" % (self.side,))
        if self.align is not None and not isinstance(self.align, (Along, PadRef, tuple)):
            raise TypeError("Beside's align is a PadRef, an (own_pad, their_pad) pair, Along.START/MID/END, "
                            "or nothing (Along.MID), not %r" % (self.align,))


@dataclass(frozen=True)
class Near:
    """A hint to search round: the item is placed at the best legal spot
    within `radius` of `location`, on a `step` grid, at each rotation
    (each falls back to place()'s own radius=, step=, rotations=)."""
    location: Location
    radius: float | None = None
    step: float | None = None
    rotations: tuple | None = None


@dataclass(frozen=True)
class FreeSpot:
    """Where a via stands: the nearest point to `near` (a pad) that clears
    every other net's copper, hole, keepout and the board edge, and that a
    straight tail on `layer` (the pad's own by default) can reach. Resolved when
    the pad's part is placed, against the copper planned before it. The via
    stays out of its own pad unless `in_pad` says otherwise, and the tail it
    was judged by is drawn with it unless `tail=False` (a via in the pad has
    none)."""
    near: object
    radius: float = 2.0
    step: float = 0.05
    layer: object = None
    in_pad: bool = False
    tail: bool = True


@dataclass(frozen=True)
class Fraction:
    """A distance along an edge as a fraction of its usable length: Fraction(0.3)."""
    value: float

    def __post_init__(self):
        if not 0.0 <= self.value <= 1.0:
            raise ValueError("a Fraction of an edge is between 0 and 1, not %r" % (self.value,))

    @property
    def fraction(self) -> float:
        return self.value


class Freedom(str, Enum):
    """Whether a position is decided before the search runs.

    Derived, never chosen: from `at=` for a placement, and from the endpoints
    for copper. A decided item goes down first and nothing may move it; a
    searched one takes its turn in the queue by rank."""
    FIXED = "fixed"          # a point: Location(x, y), Centre(x, y), Pin(k, x, y), Polar(r, a)
    EDGE = "edge"            # a distance along an edge, a run or a rim
    SEARCHED = "searched"    # anything with a freedom left

    @property
    def decided(self) -> bool:
        return self is not Freedom.SEARCHED


class Priority(str, Enum):
    """How firm a declaration is, as the SCRIPT says it. Never derived and
    never auto-assigned.

    For a placement it orders the searched items above the rank the placer
    works out: HIGH goes before the rest, LOW after them. Whether a position
    is decided is a different question, answered by `Freedom`.

    For copper it decides who passes under where two tracks of different nets
    cross: the lower priority one bridges. WHEN a piece of copper is planned -
    before the search or after it - is `Freedom` again, derived from its
    endpoints."""
    HIGH = "high"          # searched, and wanted before the rest
    DEFAULT = "default"    # searched; yields to everything firmer
    LOW = "low"            # searched, after the rest

    @property
    def rank(self) -> int:
        return {"high": 2, "default": 1, "low": 0}[self.value]


@dataclass(frozen=True, order=True)
class Location:
    """A point. One axis may be None: then it names a line, and an item
    placed at it is pinned on that axis and free on the other."""
    x: float | None
    y: float | None

    def __post_init__(self):
        if self.x is None and self.y is None:
            raise ValueError("a Location needs at least one axis")

    @property
    def free_axis(self) -> str | None:
        """'x' or 'y' when that axis is left free, else None."""
        return "x" if self.x is None else "y" if self.y is None else None

    def offset(self, dx: float = 0.0, dy: float = 0.0) -> "Location":
        return Location(self.x + dx, self.y + dy)

    def distance(self, other: "Location") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def __iter__(self):
        yield self.x
        yield self.y


@dataclass(frozen=True)
class Box:
    """Axis-aligned mm box: left, top, right, bottom (y grows downward)."""
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center(self) -> Location:
        return Location((self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def inflate(self, d: float) -> "Box":
        return Box(self.left - d, self.top - d, self.right + d, self.bottom + d)

    def moved(self, dx: float, dy: float) -> "Box":
        return Box(self.left + dx, self.top + dy, self.right + dx, self.bottom + dy)

    def overlaps(self, other: "Box", gap: float = 0.0) -> bool:
        return (self.left < other.right + gap and other.left < self.right + gap
                and self.top < other.bottom + gap and other.top < self.bottom + gap)

    def contains(self, other: "Box") -> bool:
        return (self.left <= other.left and other.right <= self.right
                and self.top <= other.top and other.bottom <= self.bottom)

    def contains_point(self, p: Location) -> bool:
        return self.left <= p.x <= self.right and self.top <= p.y <= self.bottom

    @staticmethod
    def union(boxes) -> "Box | None":
        boxes = [b for b in boxes if b is not None]
        if not boxes:
            return None
        return Box(min(b.left for b in boxes), min(b.top for b in boxes),
                   max(b.right for b in boxes), max(b.bottom for b in boxes))

    @staticmethod
    def of_points(points) -> "Box":
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return Box(min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True)
class Net:
    """A net named in the schematic. The Python variable is the stable handle;
    the string is the one place a schematic rename has to be followed."""
    name: str

    def __post_init__(self):
        if not self.name:
            raise ValueError("a Net needs a name")

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class Part:
    """A schematic instance (the Zener instance path, never a refdes)."""
    inst: str

    def __post_init__(self):
        if not self.inst:
            raise ValueError("a Part needs an instance name")

    def __str__(self):
        return self.inst


@dataclass(frozen=True)
class Cell:
    """A stamped module group, addressed by its group name."""
    name: str

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class PinName:
    """A pad key by the name the part's symbol gives its pin."""
    name: str


def pad_key(key):
    """A pad is addressed by its NUMBER (an int) or by the NET on it (a str).
    A numeric string is neither, and is rejected rather than guessed. A net
    that several of the part's pads carry names the FIRST of them in pad
    order, the same one everywhere it is used, so an offset measured off a
    pad is applied through that pad; name the number to pick another."""
    if isinstance(key, PinName):
        return ("pin", key.name)
    if isinstance(key, bool):
        raise TypeError("pad key must be an int pad number or a net name, not %r" % (key,))
    if isinstance(key, int):
        return ("number", str(key))
    if isinstance(key, Net):
        return ("net", key.name)
    if isinstance(key, str):
        if key.strip().isdigit():
            raise TypeError("pad key %r looks like a pad number: pass it as an int" % key)
        return ("net", key)
    raise TypeError("pad key must be an int pad number or a net name, not %r" % (key,))


@dataclass(frozen=True)
class PadRef:
    """A pad on a part, resolved to a location only after placement: the
    part's pad by number (int), by net (str), or `pin=` by the name its
    symbol gives the pin. `dx`/`dy` offset the point."""
    part: Part
    key: object = None
    dx: float = 0.0
    dy: float = 0.0
    pin: str | None = None
    # an offset in the part's own frame: turned, and on the back mirrored, with it. Left out of a
    # declaration's digest at 0, so a lock accepted before it existed still holds (reuse.canonical)
    lx: float = field(default=0.0, metadata={"omit_default": True})
    ly: float = field(default=0.0, metadata={"omit_default": True})
    # one land of a pin drawn as several: Land.LARGEST, or its 1-based index in the footprint's
    # order for that number. Left out of the digest when unset, as lx/ly are
    land: object = field(default=None, metadata={"omit_default": True})
    # a track point on that side of the pad (board frame), touching it: see `_edge_point` in layout.py.
    # `along` sets where on the side: START the west or north end, END the other, MID (default) the middle
    edge: object = field(default=None, metadata={"omit_default": True})
    along: object = field(default=None, metadata={"omit_default": True})

    def __post_init__(self):
        if self.edge is not None and not isinstance(self.edge, Edge):
            raise TypeError("a PadRef's edge= is an Edge, not %r" % (self.edge,))
        if self.along is not None:
            if self.edge is None:
                raise TypeError("a PadRef's along= says where on its edge=; give the edge")
            if not isinstance(self.along, Along):
                raise TypeError("a PadRef's along= is Along.START, MID or END, not %r" % (self.along,))
        if self.land is not None:
            if isinstance(self.land, bool) or not isinstance(self.land, (int, Land)):
                raise TypeError("a PadRef's land= is Land.LARGEST or a land's number, not %r" % (self.land,))
            if not isinstance(self.land, Land) and self.land < 1:
                raise ValueError("a PadRef's land= counts from 1, in the footprint's order; not %r" % (self.land,))
        if self.pin is not None:
            if self.key is not None:
                raise TypeError("a PadRef names its pad one way: a key or pin=, not both")
            object.__setattr__(self, "key", PinName(self.pin))
        elif self.key is None:
            raise TypeError("a PadRef needs a pad: a number, a net, or pin=")
        pad_key(self.key)

    def offset(self, dx: float = 0.0, dy: float = 0.0) -> "PadRef":
        """The point moved in board directions."""
        return PadRef(self.part, self.key, self.dx + dx, self.dy + dy, None, self.lx, self.ly, self.land,
                      self.edge, self.along)

    def local(self, dx: float = 0.0, dy: float = 0.0) -> "PadRef":
        """The point moved in the part's own frame, as its footprint is
        drawn: the move turns with the part, and on the back mirrors."""
        return PadRef(self.part, self.key, self.dx, self.dy, None, self.lx + dx, self.ly + dy, self.land,
                      self.edge, self.along)


@dataclass(frozen=True)
class Turned:
    """A rotation relative to a part: its placed rotation plus `degrees`,
    settled when the item is placed, which waits for that part."""
    part: Part
    degrees: float = 0.0

    def __post_init__(self):
        if not isinstance(self.part, Part):
            raise TypeError("Turned follows a Part's rotation, not %r" % (self.part,))


@dataclass(frozen=True)
class CellPadRef:
    """A pad inside a cell, found by net or number, optionally only on members
    whose refdes starts with `ref_prefix`; resolved after the cell is placed."""
    cell: Cell
    net: object = None
    number: int | None = None
    ref_prefix: str | None = None
    dx: float = 0.0
    dy: float = 0.0

    def offset(self, dx: float = 0.0, dy: float = 0.0) -> "CellPadRef":
        return CellPadRef(self.cell, self.net, self.number, self.ref_prefix, self.dx + dx, self.dy + dy)


@dataclass(frozen=True)
class X:
    """The x of a pad reference (plus dx), for a point that mixes a pad's
    coordinate with a fixed one: `(X(pad, 2.0), 40.0)`."""
    ref: object
    dx: float = 0.0


@dataclass(frozen=True)
class Y:
    """The y of a pad reference (plus dy)."""
    ref: object
    dy: float = 0.0


@dataclass(frozen=True)
class Mid:
    """The midpoint of two references (pads, points), for a part or a row
    that sits between them: `X(Mid(pin_p, pin_n))`."""
    a: object
    b: object


@dataclass(frozen=True)
class Between:
    """A track waypoint at the centreline of the gap between two pads:
    `board.track(net, [..., Between(PadRef(a), PadRef(b)), ...], ...)`.
    Resolved when both pads are placed, against the track's own width and
    net class: a gap too narrow for the track and its clearance to each pad
    is a finding naming both pads, and the track is still drawn through the
    midpoint."""
    a: object
    b: object


_PAST_COPPER = ("via", "vias", "track")       # the first word of a copper declaration's key Past may name


@dataclass(frozen=True)
class Past:
    """A point the clearance off the `edge` side of some copper:
    `Past([PadRef(a), PadRef(b)], Edge.EAST)`. `items` are pads
    (`PadRef`/`CellPadRef`), vias (what `board.via()` or `board.vias()`
    returns) and tracks (what `board.track()` returns), in any mix; the edge
    is read off their combined copper box, and the offset is the worst
    clearance by net pair from what stands at the point.

    `across` sets where the point lies across `edge`: on a pad's or a via's
    centre line, or at an `Along` of the box's side (default the middle).

    `edge` may be a `Corner` instead: the point is on the outward diagonal
    from that corner of the box, the clearance off it, so a 45 through it
    across the diagonal passes the corner at the clearance. A corner fixes
    the point on both axes, so it takes no `across`.

    As a track waypoint the point is half the track's width further out; as
    a via's `at=`, the via's radius. In `Beside`'s align pair, `lane=` a net
    leaves room for one track of it between the items and the part's pad,
    `width=` wide (default the net's track width): the copper its current
    needs.

    Resolved when every pad is placed and every via and track planned."""
    items: tuple
    edge: object
    across: object = field(default=None, metadata={"omit_default": True})
    lane: object = field(default=None, metadata={"omit_default": True})
    width: float | None = field(default=None, metadata={"omit_default": True})

    def __post_init__(self):
        from .layout import CopperIntent
        object.__setattr__(self, "items", tuple(self.items))
        if not self.items:
            raise ValueError("Past needs at least one pad, via or track")
        if not isinstance(self.edge, (Edge, Corner)):
            raise TypeError("Past's edge is an Edge or a Corner, not %r" % (self.edge,))
        if isinstance(self.edge, Corner) and self.across is not None:
            raise TypeError("Past at a corner is fixed on both axes by it; it takes no across=")
        for it in self.items:
            if isinstance(it, CopperIntent):
                if it.key.split(" ")[0] not in _PAST_COPPER:
                    raise TypeError("Past's items are pads, vias and tracks; %s is neither a via nor a track"
                                    % it.key)
            elif not isinstance(it, (PadRef, CellPadRef)):
                raise TypeError("Past's items are pads (PadRef, CellPadRef), vias and tracks, not %r" % (it,))
        a = self.across
        if not (a is None or isinstance(a, (PadRef, CellPadRef, Along))
                or (isinstance(a, CopperIntent) and a.key.split(" ")[0] == "via")):
            raise TypeError("Past's across is a PadRef, a via or Along.START/MID/END, not %r" % (a,))
        if self.lane is not None and not isinstance(self.lane, Net):
            raise TypeError("Past's lane is a Net, not %r" % (self.lane,))
        if self.width is not None and self.lane is None:
            raise TypeError("Past's width= is a lane's width: give it with lane=Net(...)")

    @property
    def pads(self) -> tuple:
        """The pads among `items`."""
        return tuple(it for it in self.items if isinstance(it, (PadRef, CellPadRef)))


class LinkWeight(IntEnum):
    """What a millimetre costs on one connection when a part is placed. Any
    integer works; these are the usual values. FREE (0) means the connection
    pulls nothing: its length does not matter (an off-board run dwarfs it)."""
    FREE = 0
    DEFAULT = 1
    PREFER = 2
    SHORT = 8


# ------------------------------------------------------------------ round boards
_EDGE_BEARING = {Edge.NORTH: 0.0, Edge.EAST: 90.0, Edge.SOUTH: 180.0, Edge.WEST: 270.0}
_CARDINAL = {0.0: (0.0, -1.0), 90.0: (1.0, 0.0), 180.0: (0.0, 1.0), 270.0: (-1.0, 0.0)}
_NM = 1e-5      # ten KiCad units: a placement is rounded to the nanometre, and a keep-in
                # is a design rule, so it is not judged finer than the arithmetic is honest


def bearing(value) -> float:
    """An angle round a board: degrees clockwise from the top, the way a
    compass and a clock read. A number, an Edge (NORTH 0, EAST 90, SOUTH
    180, WEST 270) or Fraction(f) of a full turn."""
    if isinstance(value, Edge):
        return _EDGE_BEARING[value]
    if isinstance(value, Fraction):
        return value.fraction * 360.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("a bearing is degrees clockwise from the top, an Edge or Fraction(f), not %r" % (value,))
    return float(value)


def bearing_vector(deg: float) -> tuple:
    """The unit vector pointing out along that bearing. y grows downward, so
    the top of the board is -y; the quarter turns are exact."""
    b = float(deg) % 360.0
    if b in _CARDINAL:
        return _CARDINAL[b]
    r = math.radians(b)
    return (math.sin(r), -math.cos(r))


def bearing_of(dx: float, dy: float) -> float:
    """The bearing a vector points along."""
    return math.degrees(math.atan2(dx, -dy)) % 360.0


def box_support(box: Box, deg: float) -> float:
    """How wide `box` is measured along that bearing: a box's own extent in
    a direction that is not one of its axes."""
    ux, uy = bearing_vector(deg)
    return abs(box.width * ux) + abs(box.height * uy)


def polar_point(centre: Location, angle, radius: float) -> Location:
    """The point `radius` from `centre` on that bearing."""
    ux, uy = bearing_vector(bearing(angle))
    return Location(round(centre.x + ux * radius, 6), round(centre.y + uy * radius, 6))


@dataclass(frozen=True)
class Disc:
    """A round board: its centre, its diameter, the diameter of a central
    bore (0: none), and a path per cutout. Places on it are said as a
    bearing and a radius, never as an edge: a circle has no sides.

    A bore is the cutout a round board nearly always has, so it keeps its
    own field and its own exact arithmetic; `holes` are any others - a slot
    for a cable, a window - declared the same way a shaped board's are."""
    centre: Location
    diameter: float
    hole: float = 0.0
    holes: tuple = ()

    def __post_init__(self):
        if self.diameter <= 0:
            raise ValueError("a disc's diameter is positive, not %r" % (self.diameter,))
        if not 0.0 <= self.hole < self.diameter:
            raise ValueError("a bore is smaller than the board it is cut in")
        object.__setattr__(self, "holes", tuple(tuple(h) for h in self.holes))
        object.__setattr__(self, "cutouts", Cutouts(self.holes))

    @property
    def radius(self) -> float:
        return self.diameter / 2.0

    @property
    def bore(self) -> float:
        """The bore's radius; 0 when the board is solid."""
        return self.hole / 2.0

    @property
    def box(self) -> Box:
        r = self.radius
        return Box(self.centre.x - r, self.centre.y - r, self.centre.x + r, self.centre.y + r)

    @property
    def area(self) -> float:
        return math.pi * (self.radius ** 2 - self.bore ** 2) - self.cutouts.area

    def point(self, angle, radius: float) -> Location:
        """The point `radius` from the centre on that bearing."""
        return polar_point(self.centre, angle, radius)

    def why_not(self, box: Box, margin: float) -> str | None:
        """None when `box` sits inside the board with `margin` to spare
        everywhere, else which side of the board it crosses."""
        far = max(math.hypot(x - self.centre.x, y - self.centre.y)
                  for x in (box.left, box.right) for y in (box.top, box.bottom))
        if far > self.radius - margin + _NM:
            return "past the rim's keep-in (%.2f mm)" % margin
        if self.bore:
            dx = max(box.left - self.centre.x, 0.0, self.centre.x - box.right)
            dy = max(box.top - self.centre.y, 0.0, self.centre.y - box.bottom)
            if math.hypot(dx, dy) < self.bore + margin - _NM:
                return "into the bore's keep-in (%.2f mm)" % margin
        return self.cutouts.why_not(box, margin)

    def polygon(self, inset: float = 0.0, segments: int = 72) -> tuple:
        """The rim, inset, as a polygon: what a zone or a pour is given."""
        r = self.radius - inset
        out = []
        for i in range(segments):
            ux, uy = bearing_vector(360.0 * i / segments)
            out.append((round(self.centre.x + ux * r, 6), round(self.centre.y + uy * r, 6)))
        return tuple(out)


@dataclass(frozen=True)
class CutoutEdge:
    """A promise of a stretch of a named cutout's boundary, for a script that
    places something against a hole the board has not settled yet. It is
    resolved when the item is placed, by which time the cutout is down."""
    name: str
    side: object
    within: float = 45.0


@dataclass(frozen=True)
class Cutout:
    """A hole in the board: what it is (a shape), where it goes (`at`, the
    same places a part takes), and which way it runs.

    `name` is how a script refers to it later, to put something against its
    edge. A shape carries no position, so the same slot can be cut twice.
    `rotation` is a number, or `Turned(part, degrees)` to turn with a part
    already on the board."""
    shape: object
    name: str
    at: object = None
    rotation: object = None
    why: str = ""

    def __post_init__(self):
        if not self.name or not str(self.name).strip():
            raise ValueError("a cutout needs a name: it is how a script refers to its edge")
        if self.at is None:
            raise ValueError("cutout %r needs at=: where a hole goes is not a guess. "
                             "at=Location(x, y), Centre(...), Polar(...) or OnEdge(...)" % (self.name,))


@dataclass(frozen=True)
class Keepout:
    """A region that forbids: what it is (a shape), where it goes (`at`, the
    same places a part takes), what may not happen there and what may.

    A cutout removes board; a keepout leaves it and says what may not be put
    there. The line between them is whether the board is still there.
    `rotation` is a number, or `Turned(part, degrees)` to turn with a part
    already on the board.

    `region_of` is set instead of `at`/`rotation` for a region shaped by an
    item: the shape is already the item's own drawn envelope, grown by a
    margin, and this just names the item so the region is settled from its
    placement rather than a declared place."""
    shape: object
    name: str
    at: object = None
    rotation: object = None
    excludes: tuple = ("parts", "fill", "tracks", "vias", "pads")
    allow: tuple = ()
    layers: tuple | None = None          # None: every copper layer the board has
    why: str = ""
    max_height: float | None = field(default=None, metadata={"omit_default": True})   # a parts keepout: admit parts no taller (Pm.Height)
    region_of: object = field(default=None, metadata={"omit_default": True})   # a Part or Cell this region is shaped from
    bars: tuple = field(default=(), metadata={"omit_default": True})   # the Parts and Cells it keeps out: every other part is let in

    def __post_init__(self):
        if not self.name or not str(self.name).strip():
            raise ValueError("a keepout needs a name: it is how a finding names the region")
        if self.at is None and self.region_of is None:
            raise ValueError("keepout %r needs at=: where a region goes is not a guess" % (self.name,))
        if not self.why:
            raise ValueError("keepout %r says why: a region nobody can justify is one nobody can move"
                             % (self.name,))
        bad = [e for e in self.excludes if e not in ("parts", "fill", "tracks", "vias", "pads")]
        if bad:
            raise ValueError("a keepout excludes parts, fill, tracks, vias or pads, not %r" % (bad[0],))


@dataclass(frozen=True)
class Inside:
    """A keepout's region inside a part's pads: `board.keepout(Inside(Part(
    "u1"), margin=0.0), name, ...)`. The box bounded, on each side that has a
    row of pads, by those pads' inner edge, and on a side with none by the
    pads' outer extent on that axis; grown by `margin` (negative shrinks it).
    It moves, turns and mirrors with the part, as keepout(Part) does."""
    part: Part
    margin: float = 0.0

    def __post_init__(self):
        if not isinstance(self.part, Part):
            raise TypeError("Inside takes a Part, not %r" % (self.part,))
        if isinstance(self.margin, bool) or not isinstance(self.margin, (int, float)):
            raise TypeError("Inside's margin is a number of mm, not %r" % (self.margin,))


@dataclass(frozen=True)
class Polar:
    """A place said as a radius and a bearing: the item's body centre
    `radius` from `about` (the board's centre unless another point is given)
    on the bearing `angle`. Any board can take one - it measures from a
    centre, not from an outline. Either may be None to leave that freedom:
    Polar(16.0) slides round that ring, Polar(None, 90.0) slides out along
    that spoke. A polar place is a coordinate, so it does not turn the item;
    OnRim and ring() do."""
    radius: object
    angle: object = None
    about: object = None

    def __post_init__(self):
        if self.radius is None and self.angle is None:
            raise ValueError("a Polar place needs a radius, a bearing, or both")
        if self.angle is not None:
            bearing(self.angle)
        if self.radius is not None and (isinstance(self.radius, bool)
                                        or not isinstance(self.radius, (int, float)) or self.radius < 0):
            raise ValueError("a Polar radius is a distance from the board's centre, not %r" % (self.radius,))


@dataclass(frozen=True)
class OnRim:
    """A place on a round board's rim: the item's reach at the keep-in (or
    `overhang` past it) on the bearing `angle`, turned to face outward.
    With no angle it slides round the rim to the room that is left."""
    angle: object = None
    overhang: float = 0.0

    def __post_init__(self):
        if self.angle is not None:
            bearing(self.angle)


@dataclass(frozen=True)
class OnBore:
    """A place at the edge of a round board's bore: the item's reach at the
    keep-in outside the bore on the bearing `angle`, turned to face the
    bore. With no angle it slides round it."""
    angle: object = None

    def __post_init__(self):
        if self.angle is not None:
            bearing(self.angle)
