#!/usr/bin/env python3
"""Does the BOARD provide what its stamped cells assume?

A shared cell is built against a contract it cannot check on its own: it drops
a via and expects the board's plane to pick it up, it routes on its far layer
and expects that layer to exist, it leaves a net at a pad and expects the board
to carry it away. Stamped onto a board that does not provide those things, the
cell is silently mis-used - its ground return is not a plane but an island, and
nothing in the cell's own verification can see it, because the cell was
verified alone.

That is what this gate checks, per stamped instance, from the geometry alone:

  UNLANDED DROP   a via whose whole connected cluster lies inside its own cell.
                  A plane drop exists to reach copper the board provides; if
                  everything it touches belongs to the cell that placed it,
                  the plane it was dropped into is not there. This is the
                  board-level meaning of `via_dangling`, which a fragment is
                  allowed (it has no board yet) and a board is not.

  EMPTY LAYER     a copper layer the board declares and nothing uses. On a
                  stack whose inner layers are planes, an empty inner layer
                  means the planes were never drawn, so every rail and return
                  they were meant to carry is still on the signal layers.

  ZONE NOT FILLED a zone drawn but carrying no copper, or filling to a sliver
                  of its own outline. A drawn plane that did not fill is worse
                  than no plane: the board looks like it provides a return
                  path, the drops that reach for it are still islands, and a
                  render shows the outline either way.

Both are reported per cell and per net, because "39 dangling vias" is a number
nobody can act on and "the CAN cell's 6 ground drops land in nothing" is.

  placemat contract <board>/layout/<B>/layout.kicad_pcb
  placemat contract ... --json report.json
"""
import argparse
import collections
import json
import os
import sys

sys.dont_write_bytecode = True   # no __pycache__ beside the sources

import pcbnew

from placemat.args import board as board_arg

from placemat.report import emit, hush, json_option, unhush                                                    # noqa: E402
from placemat import layout_oracle                                             # noqa: E402

MM = 1e-6
ZONE_MIN_FRACTION = 0.05   # below this a zone has not filled in any useful sense


def cell_members(board):
    """{cell name: set of uuids it owns}, footprints and their pads included."""
    out = {}
    for g in board.Groups():
        name = g.GetName()
        if not name:
            continue
        ids = set()
        for it in g.GetItems():
            ids.add(it.m_Uuid.AsString())
            if isinstance(it, pcbnew.FOOTPRINT):
                for pad in it.Pads():
                    ids.add(pad.m_Uuid.AsString())
        out[name] = ids
    return out


def owner_of(uuid, cells):
    for name, ids in cells.items():
        if uuid in ids:
            return name
    return None


def check(pcb, verbose=False):
    board = pcbnew.LoadBoard(pcb)
    o = layout_oracle.Oracle(board, path=pcb)
    o._cluster()                                   # populates _cluster_objs
    clusters = o._cluster_objs
    cells = cell_members(board)

    # cluster lookup by item uuid, so a via finds its own cluster in one step
    where = {}
    for net, groups in clusters.items():
        for gi, items in enumerate(groups):
            for it in items:
                where[it.m_Uuid.AsString()] = (net, gi)

    unlanded = collections.defaultdict(list)       # (cell, net) -> [(x, y)]
    for t in board.GetTracks():
        if not isinstance(t, pcbnew.PCB_VIA) or t.GetNetCode() <= 0:
            continue
        uid = t.m_Uuid.AsString()
        cell = owner_of(uid, cells)
        if cell is None:
            continue                               # a board-level via is the board's own business
        loc = where.get(uid)
        if loc is None:
            continue
        net, gi = loc
        group = clusters[net][gi]
        outside = any(owner_of(x.m_Uuid.AsString(), cells) != cell for x in group)
        if not outside:
            p = t.GetPosition()
            unlanded[(cell, net)].append((round(p.x * MM, 3), round(p.y * MM, 3)))

    # copper layers the board declares, and what actually uses them
    used = collections.Counter()
    for t in board.GetTracks():
        if not isinstance(t, pcbnew.PCB_VIA):
            used[board.GetLayerName(t.GetLayer())] += 1
    for i in range(board.GetAreaCount()):
        used[board.GetLayerName(board.GetArea(i).GetLayer())] += 1
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_SHAPE) and d.GetNetCode() > 0:
            used[board.GetLayerName(d.GetLayer())] += 1
    # pads and via barrels punch every layer they pass through; that is not
    # somebody USING the layer, so they do not count as copper drawn on it
    declared = [board.GetLayerName(lid) for lid in board.GetEnabledLayers().CuStack()]
    empty = [ly for ly in declared if not used.get(ly)]

    # A zone is a promise of copper; filling is what keeps it. Compare the
    # filled area with the outline it was drawn to: a zone that fills to a
    # sliver has been eaten by clearances or islands and is not a plane.
    zones = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea():
            continue
        outline = z.CalculateOutlineArea() / 1e12
        filled = z.GetFilledArea() / 1e12
        frac = (filled / outline) if outline else 0.0
        rec = {"net": z.GetNetname(), "layer": board.GetLayerName(z.GetLayer()),
               "outline_mm2": round(outline, 1), "filled_mm2": round(filled, 1),
               "filled_fraction": round(frac, 3), "is_filled": bool(z.IsFilled())}
        zones.append(rec)
    unfilled = [z for z in zones if not z["is_filled"] or z["filled_fraction"] < ZONE_MIN_FRACTION]

    return {"pcb": pcb, "declared_copper_layers": declared, "empty_copper_layers": empty,
            "zones": zones, "zones_unfilled": unfilled,
            "unlanded": {"%s|%s" % k: v for k, v in sorted(unlanded.items())},
            "unlanded_vias": sum(len(v) for v in unlanded.values()),
            "cells_affected": len({c for c, _ in unlanded})}



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcb", nargs="+", type=board_arg, help="board names, or paths")
    json_option(ap, 'the report')
    ap.add_argument("-v", "--verbose", action="store_true", help="list every via position")
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()
    _out = hush(a.json)   # with --json the JSON is the answer

    reports, bad = [], 0
    for pcb in a.pcb:
        r = check(pcb, a.verbose)
        reports.append(r)
        print("== %s" % pcb)
        print("   copper layers declared: %s" % ", ".join(r["declared_copper_layers"]))
        if r["empty_copper_layers"]:
            print("   EMPTY LAYER   %s - declared and carrying no copper"
                  % ", ".join(r["empty_copper_layers"]))
            bad += 1
        for key, pts in sorted(r["unlanded"].items(), key=lambda kv: -len(kv[1])):
            cell, net = key.split("|")
            print("   UNLANDED DROP %-14s %-16s %d via(s)%s"
                  % (cell, net, len(pts), (" " + str(pts)) if a.verbose else ""))
        for z in r["zones_unfilled"]:
            print("   ZONE NOT FILLED %-10s %-7s %.0f mm2 outline, %.0f mm2 filled (%.0f%%)"
                  % (z["net"], z["layer"], z["outline_mm2"], z["filled_mm2"],
                     100 * z["filled_fraction"]))
        if r["zones_unfilled"]:
            bad += 1
        if r["zones"] and not r["zones_unfilled"]:
            print("   zones: %d, all filled (%s)"
                  % (len(r["zones"]), ", ".join("%s %s %.0f mm2" % (z["net"], z["layer"], z["filled_mm2"])
                                                for z in r["zones"][:4])))
        if r["unlanded_vias"]:
            print("   %d plane drop(s) in %d cell(s) land in nothing the board provides"
                  % (r["unlanded_vias"], r["cells_affected"]))
            bad += 1
        if not r["empty_copper_layers"] and not r["unlanded_vias"]:
            print("   ok - every stamped cell's drops land, every declared layer carries copper")

    unhush(_out)

    emit(reports, a.json)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
