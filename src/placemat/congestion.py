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


def rudy(pads, board: Box, layers: int, pitch: float, cell: float = 0.5, skip=frozenset()) -> Rudy:
    """`pads` are (net, box, copper layer count) of the placed pads - each net's
    box is read from its pads' centres; `pitch` is a track and its clearance;
    nets in `skip` (planes, free nets) and nets with one pad ask for nothing."""
    nx = max(1, int(math.ceil(board.width / cell)))
    ny = max(1, int(math.ceil(board.height / cell)))
    x_org, y_org = board.left, board.top
    by_net = {}
    for net, box, _ in pads:
        if net and net not in skip:
            by_net.setdefault(net, []).append(box.center)
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
        if x1 - x0 < cell:                      # a box at least a cell each way
            x0, x1 = (x0 + x1 - cell) / 2, (x0 + x1 + cell) / 2
        if y1 - y0 < cell:
            y0, y1 = (y0 + y1 - cell) / 2, (y0 + y1 + cell) / 2
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


def _spans(lo: float, hi: float, origin: float, cell: float, n: int):
    """(index, overlap) of the cells a span [lo, hi] covers along one axis."""
    first = max(0, int(math.floor((lo - origin) / cell)))
    last = min(n, int(math.ceil((hi - origin) / cell)))
    for k in range(first, last):
        a = origin + k * cell
        o = min(hi, a + cell) - max(lo, a)
        if o > 0:
            yield k, o
