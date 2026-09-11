#!/usr/bin/env python3
"""Objective board-placement review metrics (pcbnew, KiCad 10).

Usage: placemat review <board.kicad_pcb> [--edge-parts REF,REF,...]

Reports, for the placement-review loop:
  * board envelope from Edge.Cuts
  * per-connector: distance of body bbox to the nearest board edge + whether
    its pads sit inboard of its body centroid (a proxy for entry facing OUT)
  * pairwise body clearance between tall parts (relays/connectors/electrolytics)
  * ratsnest: total airwire length + crossing count (routing-simplicity proxy)
  * unplaced-at-origin / overlapping-courtyard counts

Heuristics only - the human render review still rules on aesthetics.
"""
import os
import sys

import argparse
import pcbnew

from placemat.args import board as board_arg

from placemat.layout_helpers import to_mm   # noqa: E402

sys.dont_write_bytecode = True   # no __pycache__ beside the sources
from placemat.layout_helpers import fp_body_bbox     # noqa: E402  (physical = courtyard-free)

CONN_PREFIXES = ("J", "P", "H", "USBC", "Card", "SW")
# vertical-entry parts: no board-edge requirement (plug/finger comes from above)
VERTICAL_ENTRY = ("H", "SW", "TP", "MH", "P")
TALL_VALUES = ("RELAY", "SRD", "HFD3", "2EDGRC", "DB910", "FUSE", "BLX", "MP2104")


def main(path, edge_refs=None):
    b = pcbnew.LoadBoard(path)
    # envelope from Edge.Cuts
    xs, ys = [], []
    for d in b.GetDrawings():
        if d.GetLayerName() == "Edge.Cuts":
            bb = d.GetBoundingBox()
            xs += [to_mm(bb.GetLeft()), to_mm(bb.GetRight())]
            ys += [to_mm(bb.GetTop()), to_mm(bb.GetBottom())]
    if not xs:
        print("NO Edge.Cuts outline")
        x0 = y0 = 0; x1 = y1 = 0
    else:
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        print("envelope: %.1f x %.1f mm  (x %.1f..%.1f, y %.1f..%.1f)" % (x1-x0, y1-y0, x0, x1, y0, y1))

    fps = list(b.GetFootprints())
    conns = [f for f in fps if any(f.GetReference().startswith(p) for p in CONN_PREFIXES)]
    if edge_refs:
        conns = [f for f in fps if f.GetReference() in edge_refs]
    print("\n== connectors: edge distance + entry direction ==")
    for f in sorted(conns, key=lambda f: f.GetReference()):
        bb = fp_body_bbox(f)
        l, r, t, bo = to_mm(bb.GetLeft()), to_mm(bb.GetRight()), to_mm(bb.GetTop()), to_mm(bb.GetBottom())
        dists = {"left": l-x0, "right": x1-r, "top": t-y0, "bottom": y1-bo}
        edge, dist = min(dists.items(), key=lambda kv: kv[1])
        vertical = any(f.GetReference().startswith(v) for v in VERTICAL_ENTRY)
        # pad centroid vs body centroid: pads should sit INBOARD of body centre
        # for an edge connector whose entry faces out
        px = sum(to_mm(p.GetPosition().x) for p in f.Pads()) / max(1, f.GetPadCount())
        py = sum(to_mm(p.GetPosition().y) for p in f.Pads()) / max(1, f.GetPadCount())
        cx, cy = (l+r)/2, (t+bo)/2
        inboard = {"left": px > cx, "right": px < cx, "top": py > cy, "bottom": py < cy}[edge]
        flag = ""
        if vertical:
            flag = "  (vertical entry - edge n/a)"
        else:
            if dist > 1.0: flag += "  <-- NOT AT EDGE (%.1fmm)" % dist
            if not inboard: flag += "  <-- ENTRY MAY FACE INBOARD"
        print("  %-8s nearest=%-6s gap=%5.1fmm %s" % (f.GetReference(), edge, dist, flag))

    print("\n== tall-part pairwise clearances < 3mm ==")
    tall = [f for f in fps if any(k in f.GetValue().upper() for k in TALL_VALUES)] + conns
    seen = set()
    for i, a in enumerate(tall):
        for c in tall[i+1:]:
            key = tuple(sorted((a.GetReference(), c.GetReference())))
            if key in seen: continue
            seen.add(key)
            ba, bc = fp_body_bbox(a), fp_body_bbox(c)
            dx = max(to_mm(bc.GetLeft()) - to_mm(ba.GetRight()), to_mm(ba.GetLeft()) - to_mm(bc.GetRight()), 0)
            dy = max(to_mm(bc.GetTop()) - to_mm(ba.GetBottom()), to_mm(ba.GetTop()) - to_mm(bc.GetBottom()), 0)
            gap = max(dx, dy) if (dx == 0 or dy == 0) else (dx*dx + dy*dy) ** 0.5
            if dx == 0 and dy == 0:
                print("  %s <-> %s OVERLAP" % key)
            elif gap < 3.0:
                print("  %s <-> %s %.1fmm" % (key[0], key[1], gap))

    print("\n== ratsnest (routing-simplicity proxy) ==")
    try:
        b.BuildConnectivity()
        conn = b.GetConnectivity()
        edges = []
        for i in range(conn.GetNetCount()):
            try:
                for e in conn.GetRatsnestForNet(i):
                    a, c = e.GetSourceNode(), e.GetTargetNode()
                    edges.append(((to_mm(a.Pos().x), to_mm(a.Pos().y)), (to_mm(c.Pos().x), to_mm(c.Pos().y))))
            except Exception:
                pass
        total = sum(((p[0]-q[0])**2 + (p[1]-q[1])**2) ** 0.5 for p, q in edges)
        def seg_x(s1, s2):
            (ax, ay), (bx, by) = s1; (cx2, cy2), (dx2, dy2) = s2
            def ccw(px, py, qx, qy, rx, ry): return (ry-py)*(qx-px) > (qy-py)*(rx-px)
            return ccw(ax, ay, cx2, cy2, dx2, dy2) != ccw(bx, by, cx2, cy2, dx2, dy2) and \
                   ccw(ax, ay, bx, by, cx2, cy2) != ccw(ax, ay, bx, by, dx2, dy2)
        crossings = 0
        for i in range(len(edges)):
            for j in range(i+1, len(edges)):
                if seg_x(edges[i], edges[j]):
                    crossings += 1
        print("  airwires: %d  total length: %.0fmm  crossings: %d" % (len(edges), total, crossings))
    except Exception as e:
        print("  ratsnest unavailable:", e)

    at_origin = [f.GetReference() for f in fps if to_mm(f.GetPosition().x) == 0 and to_mm(f.GetPosition().y) == 0]
    if at_origin:
        print("\nUNPLACED AT ORIGIN:", at_origin)


def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcb", type=board_arg, help="board name, or a path to a board file")
    ap.add_argument("--edge-parts", metavar="REF,REF",
                    help="refs that belong at the edge by design")
    return ap


def cli(args=None):
    a = args if args is not None else parser().parse_args()
    edge = set(a.edge_parts.split(",")) if a.edge_parts else None
    return main(a.pcb, edge)


if __name__ == "__main__":
    sys.exit(cli() or 0)
