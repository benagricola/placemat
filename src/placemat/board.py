"""The surface a layout script talks to.

A script declares what it wants - this part at that location, this cell
against that edge, this one near its connector - and asks questions of the
board as generated. Nothing moves when a call is made: `resolve()` orders
every declaration by how firm it is (FIXED, then EDGE, then searched cells,
then loose parts) and settles each one against the occupancy model. Where a
call sits in the file never decides when it runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .occupancy import Occupancy
from .placement import Placement
from .placer import box_centered_placement, edge_placement, scan
from .snapshot import CellGeom, Footprint, Snapshot
from .values import Box, Cell, Edge, Face, Location, Net, Part, Priority


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
        prio = {Priority.FIXED: 0, Priority.EDGE: 1, Priority.DEFAULT: 2}[self.priority]
        kind = 0 if self.kind == "cell" else 1
        return (prio, kind if prio == 2 else 0, self.index)


@dataclass
class Step:
    item: str
    kind: str
    priority: Priority
    placement: Placement
    moved_mm: float = 0.0
    note: str = ""
    why: str = ""


@dataclass
class Plan:
    snapshot: Snapshot
    occupancy: Occupancy
    steps: list[Step] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
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
        return {s.item: s.placement for s in self.steps}


class Board:
    """One board being laid out: queries answer from the snapshot the board
    was generated with; declarations are collected and resolved together."""

    def __init__(self, snapshot: Snapshot, edge_margin: float = 0.0, clearance: float | None = None):
        self.snapshot = snapshot
        self.edge_margin = edge_margin
        self.clearance = clearance
        self._intents: list[PlaceIntent] = []
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

    # ------------------------------------------------------------ declarations
    def size(self, width: float, height: float, chamfer: float = 0.0, radius: float = 0.0):
        """The board outline: a rectangle at the origin, chamfered or rounded."""
        if width <= 0 or height <= 0:
            raise ValueError("board size must be positive")
        self._outline = Box(0.0, 0.0, float(width), float(height))
        self._chamfer, self._radius = chamfer, radius
        self.width, self.height = float(width), float(height)

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

    # ------------------------------------------------------------ resolution
    def resolve(self, progress=None) -> Plan:
        occ = Occupancy(self.snapshot, self.edge_margin, board_box=self._outline)
        plan = Plan(self.snapshot, occ, outline=self._outline, chamfer=self._chamfer, radius=self._radius)
        for intent in sorted(self._intents, key=lambda i: i.rank):
            plan._items[intent.key] = intent.item
            step = self._settle(occ, intent, plan)
            plan.steps.append(step)
            occ.commit(intent.item, step.placement)
            if progress:
                progress("%-7s %-6s %-24s %s" % (intent.priority.value, intent.kind, intent.key, _fmt(step)))
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


def _loc(l: Location) -> str:
    return "(%.2f, %.2f)" % (l.x, l.y)


def _fmt(s: Step) -> str:
    out = "%s rot %g %s" % (_loc(s.placement.location), s.placement.rotation, s.placement.face.value)
    if s.note:
        out += "  " + s.note
    return out
