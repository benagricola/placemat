"""The typed values a layout script uses: layers, faces, edges, priorities,
locations, boxes, and references to nets, parts, cells and pads."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
import math

from .cutouts import Cutouts


class CopperLayer(str, Enum):
    F = "F.Cu"
    IN1 = "In1.Cu"
    IN2 = "In2.Cu"
    B = "B.Cu"

    @property
    def face(self) -> "Face | None":
        if self is CopperLayer.F:
            return Face.FRONT
        if self is CopperLayer.B:
            return Face.BACK
        return None

    @property
    def other_face(self) -> "CopperLayer":
        if self is CopperLayer.F:
            return CopperLayer.B
        if self is CopperLayer.B:
            return CopperLayer.F
        raise ValueError("%s is an inner layer; it has no opposite face" % self.value)

    @classmethod
    def of(cls, name: "str | CopperLayer") -> "CopperLayer":
        if isinstance(name, cls):
            return name
        for member in cls:
            if member.value == name:
                return member
        raise ValueError("unknown copper layer %r" % (name,))


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


class Along(str, Enum):
    """A named distance along an edge, of its usable length (keep-in to keep-in)."""
    START = "start"
    MID = "mid"
    END = "end"

    @property
    def fraction(self) -> float:
        return {"start": 0.0, "mid": 0.5, "end": 1.0}[self.value]


@dataclass(frozen=True)
class Centre:
    """A place for an item's body centre. Each axis is a number, a reference
    (X()/Y() of a pad, or a Mid inside X()/Y()), or None to leave that axis
    free: Centre(30, None) pins x and lets the item slide in y."""
    x: object
    y: object

    def __post_init__(self):
        if self.x is None and self.y is None:
            raise ValueError("a Centre needs at least one axis")

    @property
    def free_axis(self) -> str | None:
        return "x" if self.x is None else "y" if self.y is None else None


@dataclass(frozen=True)
class Pin:
    """A place for one of the item's own pads: the pad `key` (a number or a
    net name) lands on (x, y), each axis a number or a reference, and the
    part sits round it at its rotation. How a part is put where its pin
    must be: a cap's pad on a pin's axis, a diode's pad facing another's."""
    key: object
    x: object
    y: object

    def __post_init__(self):
        if self.x is None or self.y is None:
            raise ValueError("a Pin places both axes: the pad lands on one point")


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
        if not isinstance(self.edge, Edge) and not (hasattr(self.edge, "at") and hasattr(self.edge, "length")):
            raise TypeError("OnEdge takes an Edge or a run off board.edge(facing=), not %r" % (self.edge,))
        if self.along is not None and not isinstance(self.along, (int, float, X, Y, Mid, Along, Fraction)) \
                and type(self.along).__name__ != "_RowSlot":
            raise TypeError("along is a number, a reference, Along.START/MID/END or Fraction(f), not %r" % (self.along,))


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
class Fraction:
    """A distance along an edge as a fraction of its usable length: Fraction(0.3)."""
    value: float

    def __post_init__(self):
        if not 0.0 <= self.value <= 1.0:
            raise ValueError("a Fraction of an edge is between 0 and 1, not %r" % (self.value,))

    @property
    def fraction(self) -> float:
        return self.value


class Priority(str, Enum):
    """How firm a declaration is. The runner orders work by this, never by
    where a call sits in the file. For a placement, FIXED and EDGE say the
    declaration decided the position; they follow from the place given and a
    script does not choose them. HIGH, DEFAULT and LOW order the items the
    placer still has to find a spot for. For copper: FIXED is planned before
    every searched item and nothing may cut into it; where two tracks cross,
    the lower priority one passes under."""
    FIXED = "fixed"        # a point: the origin, a body centre, a pad
    EDGE = "edge"          # a distance along an edge or a run, or a bearing on a rim
    HIGH = "high"          # searched, and wanted before the rest
    DEFAULT = "default"    # searched; yields to everything firmer
    LOW = "low"            # searched, after the rest

    @property
    def rank(self) -> int:
        return {"fixed": 4, "edge": 3, "high": 2, "default": 1, "low": 0}[self.value]


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


def pad_key(key):
    """A pad is addressed by its NUMBER (an int) or by the NET on it (a str).
    A numeric string is neither, and is rejected rather than guessed. A net
    that several of the part's pads carry names the FIRST of them in pad
    order, the same one everywhere it is used, so an offset measured off a
    pad is applied through that pad; name the number to pick another."""
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
    part's pad by number (int) or by net (str). `dx`/`dy` offset the point."""
    part: Part
    key: object
    dx: float = 0.0
    dy: float = 0.0

    def __post_init__(self):
        pad_key(self.key)

    def offset(self, dx: float = 0.0, dy: float = 0.0) -> "PadRef":
        return PadRef(self.part, self.key, self.dx + dx, self.dy + dy)


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
