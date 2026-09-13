"""Typed values a layout script speaks in. Nothing here touches pcbnew."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


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


class Priority(str, Enum):
    """How firm a declaration is. The runner orders work by this, never by
    where a call sits in the file."""
    FIXED = "fixed"        # a mechanical fact: placed first, never moved
    EDGE = "edge"          # one degree of freedom along an edge
    DEFAULT = "default"    # searched; yields to everything firmer


@dataclass(frozen=True, order=True)
class Location:
    x: float
    y: float

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
    A numeric string is neither, and is rejected rather than guessed."""
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
