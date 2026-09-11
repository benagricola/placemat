#!/usr/bin/env python3
"""Can this pad's net get OUT, by any path a track could take?

The straight-line test - is the corridor directly outward clear? - answers a
question no router asks. A track may leave a pad, run a short way and turn 45
round whatever is in front of it, so a pad whose outward band is blocked can
still be perfectly escapable. This floods instead: it rasterises every piece of
FOREIGN copper on the layer, grown by (track/2 + clearance), and asks whether a
track centre can walk from the pad to the edge of a window round the part.

A zone is NOT an obstacle: it reflows around whatever is routed through it.
Same-net copper is not an obstacle either.

Usage:
    placemat escape <board.kicad_pcb> <REF> [--pads 2,27,28,35]
                                  [--step 0.05] [--margin 4.0] [--width 0.2]
                                  [--clearance 0.2] [--png out.png]
"""
import argparse
import math
import os
import sys

sys.dont_write_bytecode = True

import pcbnew

from placemat.report import emit, hush, json_option, unhush  # noqa: E402
from placemat import geometry  # noqa: E402

MM = 1e6


def build_blocked(board, net_name, layer_id, w, clr):
    """Foreign copper on `layer_id`, grown by half the track plus clearance."""
    grow = int((w / 2.0 + clr) * MM)
    ps = geometry.ps_new()
    for f in board.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() == net_name or not p.IsOnLayer(layer_id):
                continue
            geometry.ps_add(ps, p, layer_id, grow)
    for t in board.GetTracks():
        if t.GetNetname() == net_name:
            continue
        if t.GetClass() == "PCB_VIA":
            if not t.IsOnLayer(layer_id):
                continue
            geometry.ps_add(ps, t, layer_id, grow)
        elif t.IsOnLayer(layer_id):
            geometry.ps_add(ps, t, layer_id, grow)
    # net-tagged copper graphics are real copper; zones are not obstacles
    for d in board.GetDrawings():
        if d.GetClass() == "PCB_SHAPE" and d.IsOnLayer(layer_id) \
                and d.GetNetname() and d.GetNetname() != net_name:
            geometry.ps_add(ps, d, layer_id, grow)
    return ps


def flood(board, fp, pad, w, clr, step, margin, snap=False):
    """True when a track centre can walk from the pad to the window edge."""
    layer_id = pcbnew.F_Cu if not fp.IsFlipped() else pcbnew.B_Cu
    for cand in (pcbnew.F_Cu, pcbnew.B_Cu):
        if pad.IsOnLayer(cand):
            layer_id = cand
            break
    net = pad.GetNetname()
    bb = fp.GetBoundingBox()
    x0, y0 = bb.GetLeft() / MM - margin, bb.GetTop() / MM - margin
    x1, y1 = bb.GetRight() / MM + margin, bb.GetBottom() / MM + margin
    if snap:
        # put the lattice where a router anchored at the board origin puts it,
        # so the test asks what THAT router can represent, not what geometry
        # allows
        x0 = round(x0 / step) * step
        y0 = round(y0 / step) * step
    blocked = build_blocked(board, net, layer_id, w, clr)
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1

    def free(i, j):
        return not blocked.Collide(pcbnew.VECTOR2I(int((x0 + i * step) * MM),
                                                   int((y0 + j * step) * MM)))
    px, py = pad.GetPosition().x / MM, pad.GetPosition().y / MM
    si, sj = int(round((px - x0) / step)), int(round((py - y0) / step))
    seen = set()
    stack = []
    # seed from anywhere inside the pad that is itself free
    pb = pad.GetBoundingBox()
    for i in range(max(0, int((pb.GetLeft() / MM - x0) / step)),
                   min(nx, int((pb.GetRight() / MM - x0) / step) + 1)):
        for j in range(max(0, int((pb.GetTop() / MM - y0) / step)),
                       min(ny, int((pb.GetBottom() / MM - y0) / step) + 1)):
            if free(i, j):
                stack.append((i, j))
                seen.add((i, j))
    if not stack:
        return False, [], (si, sj), (x0, y0, step, nx, ny), seen
    prev = {}
    goal = None
    while stack:
        i, j = stack.pop()
        if i <= 0 or j <= 0 or i >= nx - 1 or j >= ny - 1:
            goal = (i, j)
            break
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            n = (i + di, j + dj)
            if n in seen or not (0 <= n[0] < nx and 0 <= n[1] < ny):
                continue
            if not free(*n):
                continue
            seen.add(n)
            prev[n] = (i, j)
            stack.append(n)
    path = []
    if goal:
        c = goal
        while c in prev:
            path.append((x0 + c[0] * step, y0 + c[1] * step))
            c = prev[c]
    return bool(goal), path, (si, sj), (x0, y0, step, nx, ny), seen



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("ref")
    ap.add_argument("--pads")
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--margin", type=float, default=4.0)
    ap.add_argument("--width", type=float, default=0.2)
    ap.add_argument("--clearance", type=float, default=0.2)
    ap.add_argument("--snap", action="store_true",
                    help="anchor the lattice on multiples of --step from the board origin, "
                         "the way a grid router does")
    json_option(ap, 'the result per pad')
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()
    _out = hush(a.json)   # with --json the JSON is the answer
    b = pcbnew.LoadBoard(a.board)
    fp = [f for f in b.GetFootprints() if f.GetReference() == a.ref]
    if not fp:
        fp = [f for f in b.GetFootprints() if a.ref in f.GetValue()]
    fp = fp[0]
    want = set(a.pads.split(",")) if a.pads else None
    out = {}
    print("escape check: %s %s, track %.2f, clearance %.2f, grid %.2f%s, window +%.1f mm"
          % (a.ref, fp.GetValue(), a.width, a.clearance, a.step,
             " (snapped to the board origin)" if a.snap else "", a.margin))
    for p in sorted(fp.Pads(), key=lambda q: q.GetNumber()):
        if want and p.GetNumber() not in want:
            continue
        if not p.GetNetname():
            continue
        ok, path, _, _, seen = flood(b, fp, p, a.width, a.clearance, a.step, a.margin, a.snap)
        out[p.GetNumber()] = ok
        print("   pad %-4s %-22s %s   (%d cells reachable%s)"
              % (p.GetNumber(), p.GetNetname(), "ESCAPES" if ok else "BOXED IN",
                 len(seen), ", path %d pts" % len(path) if ok else ""))
    unhush(_out)
    emit(out, a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
