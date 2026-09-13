"""The offline placer: candidate locations tested against an Occupancy, never
against pcbnew. Every search is deterministic: candidates are enumerated in
a fixed order and ties break on (distance from hint, rotation, x, y)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math

from .occupancy import Occupancy
from .placement import Placement
from .values import Box, Edge, Face, Location


@dataclass
class ScanResult:
    chosen: Placement | None
    hint: Placement
    tried: int
    rejected: Counter = field(default_factory=Counter)
    reasons: dict = field(default_factory=dict)

    @property
    def moved_mm(self) -> float:
        if self.chosen is None:
            return math.inf
        return self.chosen.location.distance(self.hint.location)

    def __iter__(self):
        yield from self.rejected


def _grid(center: Location, radius: float, step: float):
    n = int(math.floor(radius / step + 1e-9))
    pts = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x, y = center.x + i * step, center.y + j * step
            d = math.hypot(i * step, j * step)
            if d <= radius + 1e-9:
                pts.append((d, round(x, 6), round(y, 6)))
    pts.sort()
    return pts


def scan(occ: Occupancy, item, hint: Placement, radius: float, step: float,
         rotations=None, clearance: float | None = None, commit: bool = False) -> ScanResult:
    """The nearest legal location to `hint` within `radius`, on a `step` grid,
    trying each rotation at each location. Rotations are tried in numeric
    order regardless of how they were passed."""
    rots = tuple(sorted({(r % 360) for r in (rotations or (hint.rotation,))}))
    rejected: Counter = Counter()
    reasons: dict = {}
    tried = 0
    for d, x, y in _grid(hint.location, radius, step):
        for rot in rots:
            cand = Placement(Location(x, y), rot, hint.face)
            tried += 1
            why = occ.legal(item, cand, clearance)
            if why is None:
                if commit:
                    occ.commit(item, cand)
                return ScanResult(cand, hint, tried, rejected, reasons)
            key = _reason_key(why)
            rejected[key] += 1
            reasons.setdefault(key, why)
    return ScanResult(None, hint, tried, rejected, reasons)


def _reason_key(why: str) -> str:
    for word in ("courtyard", "edge", "reservation", "copper", "through", "npth"):
        if word in why:
            return word
    return why.split(" ")[0]


def edge_placement(occ: Occupancy, item, edge: Edge, along: float, rotation: float,
                   clearance: float, face: Face = Face.FRONT) -> Placement:
    """The placement that puts the item's body box `clearance` inside `edge`
    with its centre at `along` (x for north/south, y for east/west)."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    box = occ.body_box(item, probe)
    board = occ.board_box
    if edge is Edge.NORTH:
        dx, dy = along - box.center.x, board.top + clearance - box.top
    elif edge is Edge.SOUTH:
        dx, dy = along - box.center.x, board.bottom - clearance - box.bottom
    elif edge is Edge.WEST:
        dx, dy = board.left + clearance - box.left, along - box.center.y
    else:
        dx, dy = board.right - clearance - box.right, along - box.center.y
    return Placement(Location(round(dx, 6), round(dy, 6)), rotation, face)


def fixed_placement(occ: Occupancy, item, location: Location, rotation: float = 0.0,
                    face: Face = Face.FRONT) -> Placement:
    return Placement(location, rotation, face)


def box_centered_placement(occ: Occupancy, item, center: Location, rotation: float = 0.0,
                           face: Face = Face.FRONT) -> Placement:
    """The placement whose BODY BOX is centred on `center` (a group's centre is
    its box centre, not its origin)."""
    probe = Placement(Location(0.0, 0.0), rotation, face)
    box = occ.body_box(item, probe)
    return Placement(Location(round(center.x - box.center.x, 6), round(center.y - box.center.y, 6)),
                     rotation, face)
