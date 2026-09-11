#!/usr/bin/env python3
"""Measure the TRUE minimum copper gap between different-net items in a layout.

Why this exists: a module fragment is DRC'd standalone against its own default
clearance, but every consuming board stamps it under a stricter net class
(the classes differ).  Module-internal violations therefore
only surface at board level, where they get written off as "module artifacts".
This tool checks a fragment against the STRICTEST floor any board declares,
without a board.

It does not trust kicad-cli DRC as the primary: DRC collapses some pairs.
Geometry is
measured here directly - every copper item (pad, track, via, gr_poly, zone
fill) is converted to its real polygon (ERROR_OUTSIDE, so gaps are never
over-reported), then every different-net pair sharing a copper layer is swept
segment-to-segment.

Usage:
  placemat clearance                      # all module fragments
  placemat clearance modules/OptoSense    # one module (or a .kicad_pcb)
  placemat clearance --threshold 0.25 --verbose
"""
import argparse
import glob
import os
import sys

import pcbnew

sys.dont_write_bytecode = True   # no __pycache__ beside the sources
from placemat import geometry                                                    # noqa: E402
from placemat.geometry import (Item, MM, collect, outlines_of,               # noqa: E402,F401
                      poly_dist, point_in_poly, sweep)

# The exact-polygon machinery lives in modules/geometry.py so the oracle
# (modules/layout_oracle.py) measures a PROPOSED segment with the same code
# that measures a committed one.  Names re-exported above for callers that
# still import them from here.
POLY_ERR_NM = geometry.CLEAR_ERR_NM
_bbox_gap = geometry.bbox_gap
_inside = point_in_poly


def load_floors(root):
    """Per-module floors, DERIVED from the net classes of every board that
    stamps the cell (modules/clearance_floors.py), then raised by whatever the
    module's own clearance.json records that a class cannot express."""
    from placemat import clearance_floors
    return clearance_floors.config(root)


class Floors:
    """Per-pair floor: max(module floor, net floors), minus documented accepts."""

    def __init__(self, cfg, module):
        self.d = cfg.get("modules", {}).get(module, {})
        self.base = self.d.get("floor", cfg.get("default_floor", 0.25))
        self.nets = self.d.get("nets", {})
        self.accept = {}
        for a, b, g, why in self.d.get("accept", []):
            self.accept[tuple(sorted((a, b)))] = (g, why)

    def floor(self, na, nb):
        acc = self.accept.get(tuple(sorted((na, nb))))
        if acc:
            return acc[0]
        return max(self.base, self.nets.get(na, 0.0), self.nets.get(nb, 0.0))


def _is_part_internal(h):
    """Both items are pads of the same footprint: part geometry, not layout."""
    _, a, b = h
    return a.fp is not None and a.fp == b.fp


def analyse(pcb_path, threshold=0.25, cutoff=None, floors=None):
    cutoff = cutoff if cutoff is not None else max(threshold + 0.25, 0.5)
    board = pcbnew.LoadBoard(pcb_path)
    items = collect(board)
    hits = sweep(items, cutoff=cutoff)

    def bad(h):
        f = floors.floor(h[1].net, h[2].net) if floors else threshold
        return h[0] < f - 5e-4
    under = [h for h in hits if bad(h)]
    layout_hits = [h for h in hits if not _is_part_internal(h)]
    tgt = [h for h in hits if h[0] < threshold - 5e-4]
    return {"path": pcb_path, "items": len(items), "hits": hits,
            "under": [h for h in under if not _is_part_internal(h)],
            "part": [h for h in tgt if _is_part_internal(h)],
            "target": [h for h in tgt if not _is_part_internal(h)],
            "min": layout_hits[0][0] if layout_hits else None,
            "min_any": hits[0][0] if hits else None, "threshold": threshold}


def _fragments(targets, root):
    out = []
    for t in targets or [os.path.join(root, "modules")]:
        if t.endswith(".kicad_pcb"):
            out.append(t)
        elif os.path.isdir(t):
            found = sorted(glob.glob(os.path.join(t, "**", "layout.kicad_pcb"),
                                     recursive=True))
            out.extend(found)
    return out


def _label(h):
    d, a, b = h
    return "%7.3f  %-14s %-26s <-> %-14s %s" % (d, a.net, a.name, b.net, b.name)


def drc_crosscheck(pcb_path, threshold, workdir):
    """Run the real kicad-cli DRC with every class forced to `threshold`."""
    import json
    import shutil
    import subprocess
    os.makedirs(workdir, exist_ok=True)
    pcb = os.path.join(workdir, "layout.kicad_pcb")
    shutil.copy(pcb_path, pcb)
    pro_src = pcb_path[:-len(".kicad_pcb")] + ".kicad_pro"
    if os.path.exists(pro_src):
        pro = os.path.join(workdir, "layout.kicad_pro")
        shutil.copy(pro_src, pro)
        d = json.load(open(pro))
        d["board"]["design_settings"]["rules"]["min_clearance"] = threshold
        for c in d["net_settings"]["classes"]:
            c["clearance"] = threshold
        json.dump(d, open(pro, "w"))
    out = os.path.join(workdir, "drc.json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json",
                    "--output", out, pcb],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    v = json.load(open(out))["violations"]
    buckets = {}
    for x in v:
        buckets[x["type"]] = buckets.get(x["type"], 0) + 1
    return buckets, [x["description"] for x in v if x["type"] == "clearance"]



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("targets", nargs="*", help="module dirs or .kicad_pcb files")
    ap.add_argument("--threshold", type=float, default=0.25,
                    help="floor to test against (mm, default 0.25 = strictest "
                         "net class any consuming board declares)")
    ap.add_argument("--cutoff", type=float, default=None,
                    help="report pairs up to this gap (mm)")
    ap.add_argument("--top", type=int, default=8,
                    help="also list N tightest survivors above the threshold")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--part-internal", action="store_true",
                    help="also list same-footprint pad pairs (part geometry - "
                         "not fixable in layout, judged against the pads' own "
                         "net class, not this floor)")
    ap.add_argument("--no-floors", action="store_true",
                    help="ignore the derived clearance floors; judge every "
                         "pair against --threshold")
    ap.add_argument("--drc", action="store_true",
                    help="cross-check with real kicad-cli DRC at the threshold")
    return ap


def main(args=None):
    args = args if args is not None else parser().parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = _fragments(args.targets, root)
    if not paths:
        print("no fragments found", file=sys.stderr)
        return 2

    fails = 0
    rows = []
    for p in paths:
        name = os.path.basename(os.path.dirname(os.path.dirname(p))) or p
        fl = None if args.no_floors else Floors(load_floors(root), name)
        r = analyse(p, args.threshold, args.cutoff, floors=fl)
        mn = "%.3f" % r["min"] if r["min"] is not None else ">cutoff"
        rows.append((name, mn, len(r["under"]), len(r["target"]),
                     "%.2f" % fl.base if fl else "-", r["items"]))
        if r["under"]:
            fails += 1
        if r["under"] or args.verbose or (args.part_internal and r["part"]):
            print("\n== %s  (%s, %d copper items)" % (name, p, r["items"]))
            for h in r["under"]:
                print("  UNDER %s" % _label(h))
            if args.verbose:
                for h in r["target"]:
                    if h not in r["under"]:
                        print("  below-target %s" % _label(h))
            if args.part_internal:
                for h in r["part"]:
                    print("  part  %s" % _label(h))
            if args.verbose:
                surv = [h for h in r["hits"]
                        if h[0] >= args.threshold - 5e-4 and not _is_part_internal(h)]
                for h in surv[:args.top]:
                    print("   ok   %s" % _label(h))
        if args.drc:
            wd = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                              "modclr", name)
            buckets, descs = drc_crosscheck(p, args.threshold, wd)
            print("  drc@%.2f: clearance=%d  %s" %
                  (args.threshold, buckets.get("clearance", 0),
                   {k: v for k, v in sorted(buckets.items()) if k != "clearance"}))
            for d in descs:
                print("     %s" % d.strip())

    print("\n%-22s %9s %6s %6s %6s %7s" %
          ("module", "min gap", "floor", "under", "<%.2f" % args.threshold,
           "items"))
    for name, mn, u, tg, fb, it in rows:
        print("%-22s %9s %6s %6d %6d %7d%s" %
              (name, mn, fb, u, tg, it, "  FAIL" if u else ""))
    print("\n%d/%d fragments below their declared floor "
          "(derived from the consuming boards' net classes); '<%.2f' counts layout-controlled "
          "pairs under the reporting threshold" % (fails, len(rows), args.threshold))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
