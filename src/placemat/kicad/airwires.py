"""A written board's airwires, the same every time it is asked.

KiCad's DRC reports a board's unconnected items with endpoints its connectivity picks in no fixed order: the same board
file gives the same islands each time but other pads and track ends between them, so a length or crossing count taken
from them moves with nothing changed. Here KiCad says only what is joined: each net's islands, the pads, tracks and vias
its connectivity joins (zones filled), and an island counts where it holds a pad. The airwires join a net's islands as a
spanning tree of the shortest links between their points (pad centres, track ends, vias), ties broken by the points.
A zone joins what it reaches, but no point of its outline is a link's end: a plane net's airwire can be longer than
KiCad draws it.
"""
from __future__ import annotations

import math
from pathlib import Path


def island_edges(islands: dict) -> list:
    """The airwires of `islands` ({net: [island, ...]}, an island a list of (x, y) points): for each net, a minimum spanning
    tree of its islands by the shortest link between their points, as (net, (x, y), (x, y)), nets in name order. Links
    of equal length are taken in the order of their points, so the same islands give the same airwires."""
    out = []
    for net in sorted(islands):
        groups = [sorted(set(g)) for g in islands[net] if g]
        if len(groups) < 2:
            continue
        links = []
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                # a link's ends in order, so one of two islands given the other way round is the same link
                links.append(min((math.hypot(a[0] - b[0], a[1] - b[1]), min(a, b), max(a, b), i, j)
                                 for a in groups[i] for b in groups[j]))
        parent = list(range(len(groups)))

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k
        for d, a, b, i, j in sorted(links, key=lambda l: (round(l[0], 9), l[1], l[2])):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj
                out.append((net, a, b))
    return out


def board_islands(pcb: Path) -> dict:
    """{net: [island, ...]} of a written board as KiCad's connectivity joins it, zones filled: an island is the points
    (pads' anchors, track ends, vias) of the pads, tracks and vias joined together, and counts where it holds a pad."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb))
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.BuildConnectivity()
    conn = board.GetConnectivity()
    by_net: dict = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname():
                by_net.setdefault(pad.GetNetname(), []).append(pad)
    for t in board.GetTracks():
        if t.GetNetname():
            by_net.setdefault(t.GetNetname(), []).append(t)
    for z in board.Zones():
        if z.GetNetname() and not z.GetIsRuleArea():
            by_net.setdefault(z.GetNetname(), []).append(z)
    mm = pcbnew.ToMM
    out = {}
    for net, items in by_net.items():
        index = {it.m_Uuid.AsString(): k for k, it in enumerate(items)}
        parent = list(range(len(items)))

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k
        for k, it in enumerate(items):
            for o in conn.GetConnectedItems(it):
                j = index.get(o.m_Uuid.AsString())
                if j is not None:
                    parent[find(j)] = find(k)
        groups: dict = {}
        for k, it in enumerate(items):
            groups.setdefault(find(k), []).append(it)
        islands = []
        for g in groups.values():
            if not any(isinstance(x, pcbnew.PAD) for x in g):
                continue                    # tracks or a zone joined to no pad: nothing to join
            points = []
            for x in g:
                if isinstance(x, pcbnew.PAD):
                    # the pad's anchor as KiCad's ratsnest takes it, as kicad/read.py reads it (PadGeom.anchor)
                    cu = [l for l in x.GetLayerSet().CuStack() if board.IsLayerEnabled(l)]
                    p = x.ShapePos(cu[0]) if cu else x.GetPosition()
                    points.append((round(mm(p.x), 6), round(mm(p.y), 6)))
                elif isinstance(x, pcbnew.PCB_VIA):
                    p = x.GetPosition()
                    points.append((round(mm(p.x), 6), round(mm(p.y), 6)))
                elif isinstance(x, pcbnew.PCB_TRACK):
                    for p in (x.GetStart(), x.GetEnd()):
                        points.append((round(mm(p.x), 6), round(mm(p.y), 6)))
            islands.append(points)
        out[net] = islands
    return out


def airwire_edges(pcb: Path) -> list:
    """A written board's airwires, (net, (x, y), (x, y)) each: `island_edges` of `board_islands`."""
    return island_edges(board_islands(pcb))
