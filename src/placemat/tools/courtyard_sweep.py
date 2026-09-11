#!/usr/bin/env python3
"""All-pairs footprint-courtyard sweep for a milled layout (KiCad 10 / pcbnew).

Usage: placemat courtyards <board.kicad_pcb> [margin_mm] [origin_x origin_y]

Copper-only verification misses part-vs-part collisions entirely, and a plan
verifier that models courtyards as boxes misses rotated ones. This reads the
REAL F.Courtyard polygons off the board, so rotations (a crystal at -45, caps at
90/180, a SOT-23-5 at 90) are handled by construction, convex-hulls each, and
separates them with SAT. Reports every overlap plus every pair inside `margin` -
a pair at 0.000 is a defect in waiting, not a pass.

Cross-check it against `kicad-cli pcb drc`'s courtyards_overlap count on first
use for a new board; if they disagree, the sweep is wrong, not DRC.

Scope, and what to use instead: this compares SAME-FACE courtyards only, and it
convex-hulls each one, so on a concave courtyard it over-reports. It is a fast
per-fragment gate. `placemat occupancy` is the authority on a real
two-sided board - exact polygons (matches kicad-cli on all five boards) plus
the classes this cannot see at all: a through-hole pin or via landing on the
opposite face's pads (short) or under its component bodies (assembly-
impossible, and DRC is silent about it).
"""
import sys, math, itertools
import argparse
import pcbnew

from placemat.args import board as board_arg

def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcb", type=board_arg, help="board name, or a path to a board file")
    ap.add_argument("margin", nargs="?", type=float, default=0.0,
                    help="report pairs closer than this (mm)")
    ap.add_argument("mx", nargs="?", type=float, default=0.0, help="extra margin in x")
    ap.add_argument("my", nargs="?", type=float, default=0.0, help="extra margin in y")
    return ap


def main(args=None):
    """Report how close any two parts are, all pairs."""
    _A = args if args is not None else parser().parse_args()
    b = pcbnew.LoadBoard(_A.pcb)
    if b is None:
        sys.exit("placemat courtyards: %s is not a board file" % _A.pcb)
    MARGIN = _A.margin
    # Optional reporting origin (a module script's anchor), so printed coordinates
    # match the layout script's own frame; defaults to raw board coordinates.
    MX, MY = _A.mx, _A.my
    U = 1e6


    def inst(fp):
        return (fp.GetFieldText("Path") or "").split(".")[0] or fp.GetReference()


    def face_of(fp):
        """Which side the part is mounted on - its courtyard lives on that side."""
        return "B" if fp.GetLayerName() == "B.Cu" else "F"


    def crtyd(fp):
        """Courtyard as a list of (x,y) mm polygons, MCU-relative.

        Reads the courtyard layer belonging to the part's OWN face. Reading only
        F.Courtyard silently drops every bottom-side part, which on a two-sided
        board halves the sweep.
        """
        want = face_of(fp) + ".Courtyard"
        polys = []
        for s in fp.GraphicalItems():
            if s.GetLayerName() != want:
                continue
            sp = s.GetPolyShape() if s.GetShape() == pcbnew.SHAPE_T_POLY else None
            if sp and sp.OutlineCount():
                o = sp.Outline(0)
                polys.append([(o.CPoint(i).x / U - MX, o.CPoint(i).y / U - MY)
                              for i in range(o.PointCount())])
            else:
                bb = s.GetBoundingBox()
                polys.append([(bb.GetLeft() / U - MX, bb.GetTop() / U - MY),
                              (bb.GetRight() / U - MX, bb.GetTop() / U - MY),
                              (bb.GetRight() / U - MX, bb.GetBottom() / U - MY),
                              (bb.GetLeft() / U - MX, bb.GetBottom() / U - MY)])
        return polys


    def hull(polys):
        """Convex hull (monotone chain). Courtyards here are rectangles or the
        crystal's diamond - all convex, so the hull is exact, and SAT needs an
        ORDERED polygon: feeding it raw points made 147 phantom overlaps."""
        pts = sorted(set(p for poly in polys for p in poly))
        if len(pts) < 3:
            return pts

        def half(ps):
            out = []
            for p in ps:
                while len(out) >= 2:
                    (x1, y1), (x2, y2) = out[-2], out[-1]
                    if (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) > 1e-12:
                        break
                    out.pop()
                out.append(p)
            return out

        return half(pts)[:-1] + half(pts[::-1])[:-1]


    def sep(a, b):
        """Signed separation between two convex-ish point sets via SAT on both
        edge sets. Negative = overlap depth."""
        best = -1e9   # SAT: separation is the MAX gap over candidate axes.
        for src in (a, b):
            n = len(src)
            for i in range(n):
                x0, y0 = src[i]
                x1, y1 = src[(i + 1) % n]
                ex, ey = x1 - x0, y1 - y0
                L = math.hypot(ex, ey)
                if L < 1e-9:
                    continue
                nx, ny = -ey / L, ex / L
                pa = [nx * x + ny * y for x, y in a]
                pb = [nx * x + ny * y for x, y in b]
                gap = max(min(pb) - max(pa), min(pa) - max(pb))
                best = max(best, gap)
        return best


    fps = []
    for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        pts = hull(crtyd(fp))
        if pts:
            fps.append((inst(fp), fp.GetReference(), pts, face_of(fp)))

    print("swept %d footprints, %d pairs, margin %.2fmm"
          % (len(fps), len(fps) * (len(fps) - 1) // 2, MARGIN))
    hits = []
    for (ia, ra, pa, fa), (ib, rb, pb, fb) in itertools.combinations(fps, 2):
        if fa != fb:
            continue          # opposite faces cannot collide in plan; the
                              # through-feature classes are board_occupancy.py's job
        d = sep(pa, pb)
        if d < MARGIN:
            hits.append((d, ia, ra, ib, rb))
    for d, ia, ra, ib, rb in sorted(hits):
        tag = "OVERLAP" if d < 0 else "tight  "
        print("  %s %7.3f  %-16s %-4s + %-16s %s" % (tag, d, ia, ra, ib, rb))
    print("%d overlapping, %d tight" % (sum(1 for h in hits if h[0] < 0),
                                        sum(1 for h in hits if h[0] >= 0)))



if __name__ == "__main__":
    sys.exit(main() or 0)
