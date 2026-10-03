"""A cell of several jobs (docs/superpowers/specs/2026-09-30-split-modules-
for-placement-design.md, section 2).

A cell is placed as one rigid piece, so a cell that holds two or more
jobs joined only through board-level nets carries every job to wherever its
tightest one lands. This finds those cells from the generated board's
geometry, once a run has it, and reports it back: the capture decides a
cell's parts from what must sit close together; the layout can only say
that a cell, as captured, does not hold one job.

A net is local to a cell when every pad the whole board has on it sits on
the cell's own members; a `board.plane()` net is never local, whatever its
pads. Two members are in one group when a local net joins them, directly or
through other members. A member no local net joins to another is
unjoined, and takes no part in any group: it is judged by what places it.
A bypass capacitor between a board-level supply and a plane is unjoined
this way, yet it always belongs with the IC it serves; a sensing part
belongs at what it senses. A part with no such need (a pull-up on a
shared bus) may belong with the rest of its job elsewhere."""
from __future__ import annotations

from .board_geometry import BoardGeometry, CellGeom


def _board_net_counts(geometry: BoardGeometry) -> dict:
    counts: dict = {}
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.net:
                counts[p.net] = counts.get(p.net, 0) + 1
    return counts


def _local_nets(cell: CellGeom, board_counts: dict, plane_nets) -> set:
    """The nets on this cell's members whose every board-wide pad is on one
    of them, less any net the board declares a plane for."""
    cell_counts: dict = {}
    for fp in cell.members:
        for p in fp.pads:
            if p.net:
                cell_counts[p.net] = cell_counts.get(p.net, 0) + 1
    return {net for net, n in cell_counts.items() if net not in plane_nets and n == board_counts.get(net, 0)}


def _groups(cell: CellGeom, local_nets: set) -> list:
    """The cell's members that carry a local net, grouped by it - directly
    or through other members - in the order the first member of each group
    appears among `cell.members`. A member no local net joins to another is
    left out (unjoined)."""
    parent = {fp.ref: fp.ref for fp in cell.members}

    def find(ref):
        while parent[ref] != ref:
            parent[ref] = parent[parent[ref]]
            ref = parent[ref]
        return ref

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_net: dict = {}
    for fp in cell.members:
        for net in sorted({p.net for p in fp.pads if p.net in local_nets}):
            by_net.setdefault(net, []).append(fp.ref)
    joined = {ref for refs in by_net.values() for ref in refs}
    for refs in by_net.values():
        for a, b in zip(refs, refs[1:]):
            union(a, b)
    groups: dict = {}
    for fp in cell.members:
        if fp.ref in joined:
            groups.setdefault(find(fp.ref), []).append(fp)
    return list(groups.values())


def cell_facts(geometry: BoardGeometry, cell: CellGeom, plane_nets, min_group: int,
               board_counts: dict | None = None) -> dict | None:
    """The `split` finding's facts for `cell` (`groups`, the refs of each group of `min_group` members or more, and
    `unjoined`, the refs of the parts no net inside the cell joins to the others), or None when it is not one: two or more
    groups of `min_group` members or more, joined only by nets that are not local to the cell."""
    board_counts = _board_net_counts(geometry) if board_counts is None else board_counts
    groups = _groups(cell, _local_nets(cell, board_counts, plane_nets))
    counted = [g for g in groups if len(g) >= min_group]
    if len(counted) < 2:
        return None
    # A member of a real group (two members or more) that only falls short
    # of `min_group` is not unjoined - a local net does join it to another
    # member, just not enough of them to count. Saying otherwise would be
    # false, so such a group is left out of the finding altogether rather
    # than folded into the unjoined list.
    paired_refs = {fp.ref for g in groups if len(g) >= 2 for fp in g}
    unjoined = [fp for fp in cell.members if fp.ref not in paired_refs]
    return {"groups": [[fp.ref for fp in g] for g in counted], "unjoined": [fp.ref for fp in unjoined]}


def report(geometry: BoardGeometry, cells, plane_nets, min_group: int) -> list:
    """(cell name, facts) for each cell in `cells` that is a `split`
    finding."""
    board_counts = _board_net_counts(geometry)
    out = []
    for cell in cells:
        facts = cell_facts(geometry, cell, plane_nets, min_group, board_counts)
        if facts is not None:
            out.append((cell.name, facts))
    return out
