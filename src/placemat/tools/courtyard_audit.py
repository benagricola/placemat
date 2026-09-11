#!/usr/bin/env python3
"""Audit (and repair) the F.CrtYd of every footprint in parts/.

A footprint with no courtyard, or one that only traces the plastic BODY, is
invisible to KiCad's courtyards_overlap test: parts can be placed on top of
each other and DRC stays green (see commit 7284b2a).

House rule - courtyard = union(pad extents, 3D body) + EXCESS mm, drawn as one
fp_rect on F.CrtYd.  The body comes from the part's own STEP/WRL model (the
authority; the same source used to size the TS-1187A courtyard by hand); an
existing body-only outline and the silkscreen are fallbacks.  An existing
courtyard that already contains the pads is a real courtyard: it is kept and
only ever grown, never shrunk.

Usage:  placemat courtyard-audit [--fix] [--excess 0.25] [file.kicad_mod ...]
"""
import argparse
import glob
import json
import math
import os
import re
import sys

import pcbnew

# House courtyard excess: IPC-7351 "Least" density level, read from
# fab-profile.json (courtyard.excess_mm). The excess is chosen so that two
# courtyards touch at about the class clearance floor: a larger excess makes
# `courtyards_overlap` fire on correctly packed parts (two parts then need
# twice the excess of pad gap to clear) and the bucket becomes noise; at the
# floor it is a hard gate. It is a courtyard figure, not a copper clearance.
from placemat.project import fab                                   # noqa: E402
EXCESS = fab().get("courtyard", {}).get("excess_mm", 0.10)
EXCESS_SMALL = EXCESS    # chips get the same air: a smaller part does not need
                         # a BIGGER margin than its neighbours (the old 0.15 for
                         # 0402-class inverted that)
SMALL = 1.1              # a pad envelope smaller than this (mm) is 0402-class
MODEL_TOL = 0.5          # how far a 3D body may overhang pads+silk before it is junk
CY = (pcbnew.F_CrtYd, pcbnew.B_CrtYd)
PT = re.compile(r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(([^)]*)\)", re.I)
_RAW = {}


def _raw_model_bbox(path):
    """xyz bbox of a STEP/WRL model's vertices, in mm."""
    if path in _RAW:
        return _RAW[path]
    lo, hi, n = [1e9] * 3, [-1e9] * 3, 0
    txt = open(path, "r", errors="ignore").read()
    if path.lower().endswith(".wrl"):
        k = 2.54  # VRML models are in 0.1 inch units
        it = (t.split() for blk in re.findall(r"point\s*\[(.*?)\]", txt, re.S)
              for t in blk.split(","))
    else:
        k = 1.0
        txt = txt.replace("\n", "")
        it = (m.group(1).split(",") for m in PT.finditer(txt))
    for v in it:
        if len(v) != 3:
            continue
        try:
            v = [float(x) * k for x in v]
        except ValueError:
            continue
        n += 1
        for i in range(3):
            lo[i], hi[i] = min(lo[i], v[i]), max(hi[i], v[i])
    _RAW[path] = (lo, hi, n)
    return _RAW[path]


def model_bbox(fp_path):
    """3D body bbox mapped into footprint XY (mm), or None."""
    t = open(fp_path).read().replace("\n", " ").replace("\t", " ")
    box = None
    for m in re.finditer(r'\(model\s+"([^"]+)"\s*\(offset\s*\(xyz ([^)]*)\)\s*\)'
                         r"\s*\(scale\s*\(xyz ([^)]*)\)\s*\)\s*\(rotate\s*\(xyz ([^)]*)\)", t):
        path = m.group(1)
        off, scale, rot = ([float(x) for x in m.group(i).split()] for i in (2, 3, 4))
        if not os.path.exists(path):
            continue
        lo, hi, n = _raw_model_bbox(path)
        if not n:
            continue
        rz = math.radians(-rot[2])
        cs, sn = math.cos(rz), math.sin(rz)
        xs, ys = [], []
        for x in (lo[0] * scale[0], hi[0] * scale[0]):
            for y in (lo[1] * scale[1], hi[1] * scale[1]):
                xs.append(x * cs - y * sn)
                ys.append(x * sn + y * cs)
        # KiCad's board Y axis points the other way from the 3D model frame
        b = (min(xs) + off[0], -(max(ys) + off[1]), max(xs) + off[0], -(min(ys) + off[1]))
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                     max(box[2], b[2]), max(box[3], b[3]))
    return box


def _bb(item):
    b = item.GetBoundingBox()
    if isinstance(item, pcbnew.PCB_SHAPE):
        b.Inflate(int(-item.GetWidth() / 2))   # the stroke straddles the outline
    return [b.GetLeft() / 1e6, b.GetTop() / 1e6, b.GetRight() / 1e6, b.GetBottom() / 1e6]


def _union(*bs):
    bs = [b for b in bs if b]
    if not bs:
        return None
    return [min(b[0] for b in bs), min(b[1] for b in bs),
            max(b[2] for b in bs), max(b[3] for b in bs)]


def _contains(a, b, tol=0.001):
    return (a[0] <= b[0] + tol and a[1] <= b[1] + tol
            and a[2] >= b[2] - tol and a[3] >= b[3] - tol)


def measure(path):
    """-> dict(pads, cy, silk, body, n_cy) of bboxes in footprint mm."""
    fp = pcbnew.FootprintLoad(os.path.dirname(path), os.path.basename(path)[:-10])
    if fp is None:
        raise RuntimeError("cannot load " + path)
    d = {"pads": None, "cy": None, "silk": None, "n_cy": 0}
    for p in fp.Pads():
        d["pads"] = _union(d["pads"], _bb(p))
    for g in fp.GraphicalItems():
        if not isinstance(g, pcbnew.PCB_SHAPE):
            continue
        if g.GetLayer() in CY:
            d["n_cy"] += 1
            d["cy"] = _union(d["cy"], _bb(g))
        elif g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            d["silk"] = _union(d["silk"], _bb(g))
    d["body"] = model_bbox(path)
    d["named"] = named_body(path, d["silk"])
    return d


def named_body(path, silk):
    """body rect from the L/W tokens in the footprint or model file name.

    LCSC names them body-length x body-width; which one lies along X is decided
    by matching the silkscreen aspect (the silk traces the body).
    """
    names = [os.path.basename(path)] + [os.path.basename(m) for m in
                                        re.findall(r'\(model\s+"([^"]+)"', open(path).read())]
    names = [os.path.splitext(n)[0] for n in names]
    L = W = None
    for n in names:
        mL, mW = re.search(r"[-_]L(\d+\.?\d*)", n), re.search(r"[-_]W(\d+\.?\d*)", n)
        if mL and mW:
            L, W = float(mL.group(1)), float(mW.group(1))
            break
    if L is None or silk is None:
        return None
    sx, sy = silk[2] - silk[0], silk[3] - silk[1]
    if min(sx, sy) < 0.3:
        return None
    err = lambda c: abs(c[0] - sx) + abs(c[1] - sy)
    bx, by = (L, W) if err((L, W)) <= err((W, L)) else (W, L)
    cx, cy = (silk[0] + silk[2]) / 2, (silk[1] + silk[3]) / 2
    return [cx - bx / 2, cy - by / 2, cx + bx / 2, cy + by / 2]


def target(d, excess=None):
    """-> (rect, excess, body_source) the courtyard this footprint should carry."""
    pads = d["pads"]
    if excess is None:
        excess = EXCESS_SMALL if (pads and max(pads[2] - pads[0],
                                               pads[3] - pads[1]) <= SMALL) else EXCESS
    keep, outline = None, None
    if d["cy"]:
        if _contains(d["cy"], pads):
            keep = d["cy"]          # already a real courtyard - grow only
        else:
            outline = d["cy"]       # easyeda draws the plastic BODY on F.CrtYd
    # a model that overhangs everything the footprint draws is mis-oriented or
    # carries stray geometry - do not let it set the courtyard
    sane = _union(pads, d["silk"], outline)   # NOT keep: it may be our own output
    body, src = d["body"], "model"
    if body and sane and not _contains([v + s * MODEL_TOL for v, s in
                                        zip(sane, (-1, -1, 1, 1))], body):
        body, src = None, "model-rejected"
    if outline:
        body = _union(body, outline)
        src = "model+outline" if src == "model" else "outline"
    if body is None and keep is None and d.get("named"):
        body, src = d["named"], "name"          # LCSC body dims from the part name
    if body is None and keep is None and d["silk"]:
        body, src = d["silk"], "silk"           # last resort: silk traces the body
    core = _union(pads, body)
    grown = [round(core[0] - excess, 3), round(core[1] - excess, 3),
             round(core[2] + excess, 3), round(core[3] + excess, 3)]
    rect = [round(v, 3) for v in _union(grown, keep)]
    return rect, excess, (src if body else "pads")


def _forms(txt):
    """yield (start, end) of every top-level (fp_*) form inside the footprint."""
    i = 0
    while True:
        i = txt.find("\n\t(fp_", i)
        if i < 0:
            return
        j, depth, instr = i + 1, 0, False
        while j < len(txt):
            c = txt[j]
            if instr:
                instr = c != '"'
            elif c == '"':
                instr = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield (i + 1, j + 1)
        i = j


def rewrite(path, rect, uid):
    """drop every F.CrtYd form, insert one fp_rect; returns the new text."""
    txt = open(path).read()
    cy = re.compile(r'\(layer "?[FB]\.CrtYd"?\)')   # v6+ quotes the layer, v5 does not
    cuts = [(a, b) for a, b in _forms(txt) if cy.search(txt[a:b])]
    for a, b in reversed(cuts):
        end = b + 1 if txt[b:b + 1] == "\n" else b
        txt = txt[:a] + txt[end:]
    if cuts:
        ins = cuts[0][0]
    else:
        m = re.search(r"\n[ \t]*\((?:fp_|pad )", txt)
        if m is None:
            raise RuntimeError("no insertion point in " + path)
        ins = m.start() + 1
    legacy = txt.lstrip().startswith("(module")
    shape = ('\t(fp_rect (start %g %g) (end %g %g) (layer F.CrtYd) (width 0.05))\n'
             % tuple(rect)) if legacy else (
        '\t(fp_rect\n\t\t(start %g %g)\n\t\t(end %g %g)\n'
        '\t\t(stroke\n\t\t\t(width 0.05)\n\t\t\t(type solid)\n\t\t)\n'
        '\t\t(fill no)\n\t\t(layer "F.CrtYd")\n\t\t(uuid "%s")\n\t)\n'
        % (rect[0], rect[1], rect[2], rect[3], uid))
    return txt[:ins] + shape + txt[ins:]


def uuid_for(path):
    """deterministic uuid so a re-run of --fix is a no-op"""
    import hashlib
    h = hashlib.sha1(os.path.basename(path).encode()).hexdigest()
    return "%s-%s-%s-%s-%s" % (h[:8], h[8:12], h[12:16], h[16:20], h[20:32])



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--excess", type=float, default=None)
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()
    if a.files:
        files = a.files
    else:
        # EVERY FOOTPRINT THE PROJECT OWNS. Where the parts are is the project's
        # to say (pcb.toml [placemat] parts), not this tool's to assume.
        from placemat.project import active
        files = sorted(f for d in active().part_dirs.values()
                       for f in glob.glob(os.path.join(d, "**", "*.kicad_mod"), recursive=True))
    bad = 0
    for f in files:
        d = measure(f)
        rect, ex, src = target(d, a.excess)
        cur = d["cy"]
        ok = cur is not None and _contains(cur, rect) and d["n_cy"] > 0
        state = "ok" if ok else ("MISSING" if not d["n_cy"] else "BODY-ONLY")
        if not ok:
            bad += 1
            print("%-58s %-10s ex=%.2f src=%-13s cur=%-28s -> %s"
                  % (os.path.relpath(f, active().root or os.getcwd()), state, ex, src,
                     str(cur), str(rect)))
            if a.fix:
                new = rewrite(f, rect, uuid_for(f))   # read fully BEFORE truncating
                open(f, "w").write(new)
    print("# %d/%d footprints %s" % (bad, len(files), "fixed" if a.fix else "need a courtyard"))
    return 1 if bad and not a.fix else 0


if __name__ == "__main__":
    sys.exit(main())
