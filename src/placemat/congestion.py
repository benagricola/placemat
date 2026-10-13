"""RUDY (Rectangular Uniform wire DensitY; Spindler and Johannes, DATE 2007):
each net's wire - the half-perimeter of its box - spread evenly over that box,
summed on a grid and set against what a cell can carry: its routing layers
times tracks per mm.

On the module study (2026-09-23) the most congested cell was the one measure
that picked the better-routing of two complete placements of the same circuit
more often than chance (75-77% of 28-31 pairs); the mean, the percentiles,
wire length and ratsnest crossings did not. So it is reported, and nothing
yet steers by it.

Pads do not take capacity. Subtracting the area they cover left a cell under
a large pad with none, and 40 of the study's 140 placements then read that
cell as the worst whatever their wiring; without it the worst cell agreed
with the router on 73-76% of pairs, as often as before, with almost no ties."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .values import Box, Location


@dataclass
class Rudy:
    worst: float            # demand over capacity in the most congested cell
    worst_at: Location      # that cell's centre
    p99: float              # the 99th percentile cell
    overflow: float         # mm of wire above capacity, summed over the cells
    demand: float           # mm of wire asked for (the sum of the nets' half-perimeters)
    cells: int
    cell: float
    util: list = None       # rows (y) of cells (x): each cell's demand over its capacity
    origin: Location = None  # the grid's top-left corner


def rudy(pads, board: Box, layers: int, pitch: float, cell: float = 0.5, skip=frozenset(), box: float = None) -> Rudy:
    """`pads` are (net, box, copper layer count) of the placed pads - each net's
    box is read from its pads' centres, and is at least `box` mm (one cell if
    None) each way (`score.congestion_box`); `pitch` is a track and its clearance;
    nets in `skip` (planes, free nets) and nets with one pad ask for nothing."""
    floor = cell if box is None else box
    nx = max(1, int(math.ceil(board.width / cell)))
    ny = max(1, int(math.ceil(board.height / cell)))
    x_org, y_org = board.left, board.top
    by_net = {}
    for net, pad_box, _ in pads:
        if net and net not in skip:
            by_net.setdefault(net, []).append(pad_box.center)
    demand = [[0.0] * nx for _ in range(ny)]
    total = 0.0
    for net in sorted(by_net):
        pts = by_net[net]
        if len(pts) < 2:
            continue
        x0, x1 = min(p.x for p in pts), max(p.x for p in pts)
        y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
        wire = (x1 - x0) + (y1 - y0)
        total += wire
        x0, x1, y0, y1 = _floored(x0, x1, y0, y1, floor)
        density = max(wire, cell) / ((x1 - x0) * (y1 - y0))
        for j, oy in _spans(y0, y1, y_org, cell, ny):
            row = demand[j]
            for i, ox in _spans(x0, x1, x_org, cell, nx):
                row[i] += density * ox * oy
    cap = layers * cell * cell / pitch                      # mm of track a cell holds
    util, over, worst, worst_at = [], 0.0, 0.0, Location(board.center.x, board.center.y)
    grid = []
    for j in range(ny):
        grid.append([])
        for i in range(nx):
            d = demand[j][i]
            over += max(0.0, d - cap)
            u = d / cap
            util.append(u)
            grid[j].append(round(u, 4))
            if u > worst + 1e-12:
                worst = u
                worst_at = Location(round(x_org + (i + 0.5) * cell, 3), round(y_org + (j + 0.5) * cell, 3))
    util.sort()
    p99 = util[min(len(util) - 1, int(0.99 * len(util)))] if util else 0.0
    return Rudy(round(worst, 4), worst_at, round(p99, 4), round(over, 3), round(total, 3), nx * ny, cell, grid,
                Location(x_org, y_org))


def _box_of(points) -> tuple:
    """(x0, x1, y0, y1) of the points."""
    return (min(p.x for p in points), max(p.x for p in points), min(p.y for p in points), max(p.y for p in points))


def _floored(x0, x1, y0, y1, floor):
    """A net's box widened about its centre to at least `floor` each way.
    placemat's own rule (no upstream RUDY handles a thin box): a short net along
    one axis would otherwise pack its wire into one row of cells, and a small turn
    that widens it would move the worst cell by many steps."""
    if x1 - x0 < floor:
        x0, x1 = (x0 + x1 - floor) / 2, (x0 + x1 + floor) / 2
    if y1 - y0 < floor:
        y0, y1 = (y0 + y1 - floor) / 2, (y0 + y1 + floor) / 2
    return x0, x1, y0, y1


def _spans(lo: float, hi: float, origin: float, cell: float, n: int):
    """(index, overlap) of the cells a span [lo, hi] covers along one axis."""
    first = max(0, int(math.floor((lo - origin) / cell)))
    last = min(n, int(math.ceil((hi - origin) / cell)))
    for k in range(first, last):
        a = origin + k * cell
        o = min(hi, a + cell) - max(lo, a)
        if o > 0:
            yield k, o


def _native_cells():
    from . import geometry
    native = geometry._native
    return getattr(native, 'RudyCells', None) if native is not None else None


class RudyGrid:
    """Per-net RUDY demand, with signed candidate changes on scratch cells.

    The grid frame stays fixed during a search. Replacing a touched net's
    box can reduce demand as well as increase it; unchanged cells retain
    their congestion-step counts without a full candidate grid scan.
    """
    def __init__(self, board: Box, layers: int, pitch: float, step: float, cell: float = 0.5, box: float = None):
        self.board, self.cell, self.step = board, cell, step
        self.box = cell if box is None else box             # the net box floor, as `rudy` takes it
        self.nx = max(1, math.ceil(board.width / cell))
        self.ny = max(1, math.ceil(board.height / cell))
        self.capacity = layers * cell * cell / pitch
        self.boxes = {}                                     # net -> its pads' box (x0, x1, y0, y1), two pads or more
        # The cells' demand by net and the step counts, kept natively when it is built (rudy.rs, the same sums bit
        # for bit), else here.
        native = _native_cells()
        self._native = None if native is None else native(board.left, board.top, cell, self.nx, self.ny, self.box,
                                                          self.capacity, self.step)
        self._demand = [0.0] * (self.nx * self.ny)
        self.nets = {}
        self.cells = [{} for _ in self._demand] if self._native is None else None
        self.counts = {0: len(self._demand)}

    def _step(self, value):
        return int(max(0.0, value) / self.capacity / self.step + 1e-9) if self.step else 0

    def _contribution(self, points):
        if len(points) < 2:
            return {}
        return self._box_contribution(_box_of(points))

    def _box_contribution(self, raw):
        """A net's demand by cell from its pads' box (two pads or more): min and max are exact, so the same box gives
        the same demand bit for bit."""
        x0, x1, y0, y1 = raw
        wire = (x1 - x0) + (y1 - y0)
        x0, x1, y0, y1 = _floored(x0, x1, y0, y1, self.box)
        density = max(wire, self.cell) / ((x1 - x0) * (y1 - y0))
        return {j * self.nx + i: density * ox * oy
                for j, oy in _spans(y0, y1, self.board.top, self.cell, self.ny)
                for i, ox in _spans(x0, x1, self.board.left, self.cell, self.nx)}

    def _apply(self, net, contribution, remove=False):
        for index, amount in contribution.items():
            old = self._step(self._demand[index])
            self.counts[old] -= 1
            if not self.counts[old]:
                del self.counts[old]
            if remove:
                self.cells[index].pop(net, None)
            else:
                self.cells[index][net] = amount
            self._demand[index] = math.fsum(self.cells[index].values())
            new = self._step(self._demand[index])
            self.counts[new] = self.counts.get(new, 0) + 1

    def add_net(self, net, points):
        if len(points) >= 2 and self.boxes.get(net) == _box_of(points):
            return                      # the same box: the same demand, bit for bit
        if self._native is not None:
            raw = _box_of(points) if len(points) >= 2 else None
            self.boxes.pop(net, None)
            self._native.replace_box(net, raw)
            self.nets[net] = True
            if raw is not None:
                self.boxes[net] = raw
            return
        contribution = self._contribution(points)
        self.remove_net(net)
        self.nets[net] = contribution
        if len(points) >= 2:
            self.boxes[net] = _box_of(points)
        self._apply(net, contribution)

    def remove_net(self, net):
        self.boxes.pop(net, None)
        if self._native is not None:
            if self.nets.pop(net, None) is not None:
                self._native.replace(net, [])
            return
        contribution = self.nets.pop(net, None)
        if contribution is not None:
            self._apply(net, contribution, remove=True)

    def worst(self):
        if self._native is not None:
            return self._native.worst()
        return max(self._demand, default=0.0) / self.capacity

    def steps(self):
        if self._native is not None:
            return self._native.steps()
        return max(self.counts, default=0)

    @property
    def demand(self) -> list:
        """Each cell's demand, by `j * nx + i`."""
        return self._native.demand() if self._native is not None else self._demand

    def change(self, replacements):
        """Signed worst-step change for {net: points}; never mutate this grid."""
        if self._native is not None:
            boxes = []
            for net, points in replacements.items():
                raw = _box_of(points) if len(points) >= 2 else None
                if raw is not None and self.boxes.get(net) == raw:
                    continue            # its box as it was: its demand is the same, bit for bit
                boxes.append((net, raw))
            return self._native.change_boxes(boxes) if boxes else 0
        contributions = {}
        for net, points in replacements.items():
            raw = _box_of(points) if len(points) >= 2 else None
            if raw is not None and self.boxes.get(net) == raw:
                continue                # its box as it was: its demand is the same, bit for bit
            contributions[net] = {} if raw is None else self._box_contribution(raw)
        touched = set()
        for net, contribution in contributions.items():
            touched.update(self.nets.get(net, {}))
            touched.update(contribution)
        counts = dict(self.counts)
        for index in touched:
            old = self._step(self._demand[index])
            counts[old] -= 1
            if not counts[old]:
                del counts[old]
            # Re-sum only changed cells. Compensated summation prevents
            # repeated lift/commit subtraction drift at a step boundary.
            value = math.fsum([amount for net, amount in self.cells[index].items() if net not in contributions]
                              + [c[index] for c in contributions.values() if index in c])
            new = self._step(value)
            counts[new] = counts.get(new, 0) + 1
        return max(counts, default=0) - self.steps()
