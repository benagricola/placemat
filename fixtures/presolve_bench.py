"""Does the global pre-solve place a module better than the sequential seed?

A module with a layout script was placed by hand, so its board is a
reference answer: every part is released to a bare place() at its hand
rotation, on a board the size of the hand layout's extent plus MARGIN a side,
and the result is scored against the hand layout. A module that was never
laid out is released onto a square board at a third fill, and the modes are
compared with each other.

Four modes. `seed`: placemat as it is. `seed+pocket`: the same, but a seeded
part whose one scan finds nothing takes a free rectangle instead of giving up
- an experiment patched in here, not placemat's behaviour. `solve`: the global
pre-solve on. `solve+pocket`: both.

Scored by what is placed, then half-perimeter wirelength (HPWL) over the nets
that pull: deterministic, which KiCad's ratsnest is not. A net touching at
least PLANE_SHARE of the parts of a module with at least six is declared a
plane, as a script would, so no mode is dragged about by ground.

    .venv/bin/python fixtures/presolve_bench.py [module-name ...]
"""
from __future__ import annotations

import dataclasses
import math
import pathlib
import sys

from placemat.kicad.read import read_board
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import CopperLayer, Location, Net, Part

ROOT = pathlib.Path(__file__).resolve().parent
MARGIN = 0.10
PLANE_SHARE = 0.5


def _plane_nets(g) -> set:
    parts = max(len(g.footprints), 1)
    count = {}
    for fp in g.footprints:
        for net in {p.net for p in fp.pads if p.net}:
            count[net] = count.get(net, 0) + 1
    return {n for n, c in count.items() if parts >= 6 and c / parts >= PLANE_SHARE}


def hpwl(g, where: dict, skip: set) -> float:
    """Half-perimeter wirelength: per net, the box round its pads, summed."""
    pads = {}
    for fp in g.footprints:
        for p in fp.pads:
            if not p.net or p.net in skip:
                continue
            at = where.get((fp.ref, p.number))
            if at is not None:
                pads.setdefault(p.net, []).append(at)
    total = 0.0
    for pts in pads.values():
        if len(pts) >= 2:
            xs, ys = [q.x for q in pts], [q.y for q in pts]
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


def _hand(g) -> dict:
    return {(fp.ref, p.number): p.box.center for fp in g.footprints for p in fp.pads}


def _extent(g):
    from placemat.values import Box
    box = Box.union([fp.courtyard_box for fp in g.footprints])
    dx, dy = box.width * MARGIN, box.height * MARGIN
    return box.width + 2 * dx, box.height + 2 * dy


def _with_pocket_fallback():
    """The experiment: a seeded part whose scan finds nothing tries a pocket."""
    original = Board._settle

    def settle(self, occ, i, plan, placed=frozenset(), solve=True):
        step = original(self, occ, i, plan, placed, solve)
        if step.placement is None and i.kind == "part" and self._solvable(i):
            pocket = self._settle_in_pocket(occ, i, plan, self.clearance)
            if pocket.placement is not None:
                pocket.note = "seeded scan failed, took a pocket; " + pocket.note
                return pocket
        return step
    return original, settle


def run(g, mode: str, planes: set, size):
    settings = dataclasses.replace(Settings(), solve_enabled=mode.startswith("solve"))
    b = Board(g, edge_margin=0.2, keep_going=True, settings=settings)
    b.size(width=round(size[0], 2), height=round(size[1], 2))
    for net in sorted(planes):
        b.plane(Net(net), [CopperLayer.B], why="benchmark: a net most parts share")
    for fp in sorted(g.footprints, key=lambda f: f.inst):
        b.place(Part(fp.inst), rotation=fp.rotation)
    original = None
    if mode.endswith("+pocket"):
        original, patched = _with_pocket_fallback()
        Board._settle = patched
    try:
        plan = b.resolve()
    finally:
        if original is not None:
            Board._settle = original
    placed = {s.item for s in plan.steps if s.placement is not None and s.kind == "part"}
    where = {}
    for fp in g.footprints:
        if fp.inst in placed:
            for p in fp.pads:
                where[(fp.ref, p.number)] = plan.occupancy.pad_location(fp.ref, p.number)
    return len(placed), hpwl(g, where, planes)


def compare(a, b) -> int:
    """1 when result `a` beats `b`: more placed, or as many placed and more
    than 1% shorter. -1 the other way; 0 otherwise."""
    if a[0] != b[0]:
        return 1 if a[0] > b[0] else -1
    if a[1] < b[1] * 0.99:
        return 1
    if a[1] > b[1] * 1.01:
        return -1
    return 0


MODES = ("seed", "seed+pocket", "solve", "solve+pocket")


def bench(path: pathlib.Path):
    g = read_board(path)
    if len(g.footprints) < 2:
        return None
    planes = _plane_nets(g)
    module_dir = path.parent.parent
    hand = any(module_dir.glob("*_layout.py"))
    if hand:
        size = _extent(g)
        reference = (len(g.footprints), hpwl(g, _hand(g), planes))
    else:
        area = sum(fp.courtyard_box.area for fp in g.footprints)
        side = math.sqrt(area * 3.0)
        size = (side, side)
        reference = None
    return len(g.footprints), reference, {m: run(g, m, planes, size) for m in MODES}


def main(names):
    boards = sorted(ROOT.glob("*/modules/*/layout/layout.kicad_pcb")) + sorted(ROOT.glob("*/modules/*/kicad/layout.kicad_pcb"))
    tally = {m: [0, 0, 0] for m in MODES[1:]}        # better, worse, same, against seed
    print("%-26s %5s | %-14s | %-14s | %-14s | %-14s | %-14s" % ("module", "parts", "hand", *MODES))
    for path in boards:
        name = "%s/%s" % (path.parents[3].name, path.parents[1].name)
        if names and not any(n in name for n in names):
            continue
        r = bench(path)
        if r is None:
            continue
        parts, ref, got = r
        cell = lambda v: "-" if v is None else "%3d %9.1f" % v
        print("%-26s %5d | %-14s | %-14s | %-14s | %-14s | %-14s" % (
            name, parts, cell(ref), *(cell(got[m]) for m in MODES)))
        for m in MODES[1:]:
            c = compare(got[m], got["seed"])
            tally[m][0 if c > 0 else 1 if c < 0 else 2] += 1
    for m, (b, w, same) in tally.items():
        print("%-12s against seed: better on %d, worse on %d, the same on %d" % (m, b, w, same))


if __name__ == "__main__":
    main(sys.argv[1:])
