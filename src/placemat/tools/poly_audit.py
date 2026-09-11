#!/usr/bin/env python3
"""Copper-polygon audit for module fragments and boards: ground pours and thin necks.

Why: a module must not pour
ground - the board's fill or plane does that and a ground pad takes a via - and
a power pour whose narrowest section is thinner than the net needs is worse
than a trace, because it reads as copper. Every polygon here is listed with its
net, layer, area and NARROWEST section (edge-to-edge, stroke included), and is
flagged when it is a ground pour or when the neck is below the floor: the net
class's track width from the board file's own netclasses when the polygon's net
resolves to one, else --floor (default 0.5 mm).

Usage:
  placemat polys modules/*/layout/layout.kicad_pcb
  placemat polys <board.kicad_pcb> --floor 0.6
Exit 1 when anything is flagged (a gate).
"""
import argparse

from placemat.args import board as board_arg
import json
import math
import os
import re
import subprocess
import sys

GROUND = ("gnd", "gnd_ret", "agnd", "pgnd", "ground")  # a cell-local floating reference (e.g. GND_FLOAT) is a different net

KPY = r'''
import json, sys, math, pcbnew
def mm(v): return pcbnew.ToMM(v)
out = []
for path in sys.argv[1:]:
    b = pcbnew.LoadBoard(path)
    for d in b.GetDrawings():
        if d.GetClass() != "PCB_SHAPE" or d.GetShape() != pcbnew.S_POLYGON or not d.IsOnCopperLayer():
            continue
        o = d.GetPolyShape().Outline(0); n = o.PointCount()
        pts = [(mm(o.CPoint(i).x), mm(o.CPoint(i).y)) for i in range(n)]
        area = abs(sum(pts[i][0]*pts[(i+1)%n][1]-pts[(i+1)%n][0]*pts[i][1] for i in range(n)))/2
        out.append({"file": path, "net": d.GetNetname(), "layer": d.GetLayerName(), "n": n,
                    "area": area, "stroke": mm(d.GetWidth()), "pts": pts})
json.dump(out, open(sys.argv[0] + ".out.json", "w"))
'''


def seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def neck(pts):
    """Narrowest edge-to-edge distance between non-adjacent edges (sampled at
    quarter points): the polygon's thinnest section, without the stroke."""
    n = len(pts)
    best, where = 1e9, pts[0]
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for f in (0.25, 0.5, 0.75):
            m = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            for j in range(n):
                if j in (i, (i - 1) % n, (i + 1) % n):
                    continue
                d = seg_dist(m, pts[j], pts[(j + 1) % n])
                if d < best:
                    best, where = d, m
    return best, where


def netclass_widths(pcb_path):
    """net name -> track width from the sibling .kicad_pro (explicit assignments
    and pattern assignments), else {}."""
    pro = pcb_path[:-len(".kicad_pcb")] + ".kicad_pro"
    if not os.path.exists(pro):
        return {}, []
    try:
        j = json.load(open(pro))
    except Exception:
        return {}, []
    classes = {c["name"]: c.get("track_width") for c in j.get("net_settings", {}).get("classes", [])}
    explicit = {}
    for c in j.get("net_settings", {}).get("classes", []):
        for n in c.get("nets", []) or []:
            explicit[n] = classes.get(c["name"])
    patterns = [(p.get("pattern"), classes.get(p.get("netclass"))) for p in j.get("net_settings", {}).get("netclass_patterns", [])]
    return explicit, patterns


def width_for(net, explicit, patterns):
    if net in explicit and explicit[net]:
        return explicit[net]
    for pat, w in patterns:
        if pat and w and re.fullmatch(pat.replace("*", ".*"), net):
            return w
    return None



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("boards", nargs="+", type=board_arg, help="board or fragment")
    ap.add_argument("--floor", type=float, default=0.5, help="neck floor when the net has no class width (mm)")
    ap.add_argument("--allow-ground", action="store_true", help="do not flag ground pours (boards may pour)")
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()
    # placemat runs in an interpreter that carries pcbnew - that is the whole
    # reason for its venv - so this one will do. The variable stays an override
    # for a machine with more than one KiCad.
    interp = os.environ.get("KICAD_PYTHON_INTERPRETER") or sys.executable
    script = os.path.join(os.environ.get("TMPDIR", "/tmp"), "poly_audit_%d.py" % os.getpid())
    open(script, "w").write(KPY)
    boards = [os.path.abspath(b) for b in a.boards]
    subprocess.run([interp, script] + boards, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    polys = json.load(open(script + ".out.json"))
    os.remove(script); os.remove(script + ".out.json")
    flagged = 0
    by_file = {}
    for p in polys:
        by_file.setdefault(p["file"], []).append(p)
    for f in boards:
        rows = by_file.get(f, [])
        if not rows:
            continue
        explicit, patterns = netclass_widths(f)
        rel = os.path.relpath(f)
        print("== %s: %d copper polygon(s)" % (rel, len(rows)))
        for p in rows:
            w, where = neck(p["pts"])
            w += p["stroke"]
            floor = width_for(p["net"], explicit, patterns) or a.floor
            flags = []
            if p["net"].lower() in GROUND and not a.allow_ground:
                flags.append("GROUND POUR: the board fills or planes ground; give the pads a via instead")
            if w < floor - 1e-6:
                flags.append("THIN NECK %.2f < %.2f mm floor (net class width or --floor)" % (w, floor))
            flagged += bool(flags)
            print("   %-22s %-5s %2d pts  area %7.2f mm2  narrowest %.2f mm at (%.1f, %.1f)%s"
                  % (p["net"][:22], p["layer"], p["n"], p["area"], w, where[0], where[1],
                     ("  <-- " + "; ".join(flags)) if flags else ""))
    print("%d polygon(s) flagged" % flagged)
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
