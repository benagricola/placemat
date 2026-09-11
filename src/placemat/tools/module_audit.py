#!/usr/bin/env python3
"""Module fragments against the layout rules that can be measured.

The `pcb-layout` skill states the rules; this reads them off the geometry so a
rule that changes does not quietly leave every fragment behind. Report-only:
each finding names the module, the part and what to do.

Checks
------
`ep_ground_serve` (skill tactic 12, the EP-grounded exception)
    An IC whose exposed pad is ground needs no via or stub on its other ground
    PINS. The EP takes the vias and the board's ground fill joins each ground
    pin's pad to the EP across the sub-millimetre gap. A track from a ground
    pin to the EP, or a via sitting on a ground pin's pad, only crowds the pad
    corridor - and in the cell's own DRC those pins reading unconnected is the
    accepted bucket, not a defect to route away.

Usage:
    placemat modules                 # every module fragment
    placemat modules <fragment.kicad_pcb> ...
    placemat modules --json out.json
Exit 1 when anything is flagged.
"""
import argparse
import glob
import json
import os
import sys

sys.dont_write_bytecode = True

import pcbnew

from placemat.args import cell as cell_arg

from placemat.report import emit, hush, json_option, unhush  # noqa: E402

def _root():
    """The project's root. Asked for, never computed from this file's own path."""
    from placemat.project import active
    return active().root or os.getcwd()


GND_NAMES = ("gnd", "GND", "GND_IN", "gnd_in", "AGND", "agnd", "PGND", "pgnd")


def _is_gnd(net):
    return net.split(".")[-1] in GND_NAMES


def _pad_box(p):
    bb = p.GetBoundingBox()
    return (bb.GetLeft() / 1e6, bb.GetTop() / 1e6, bb.GetRight() / 1e6, bb.GetBottom() / 1e6)


def _in_box(x, y, b, grow=0.0):
    return (b[0] - grow <= x <= b[2] + grow) and (b[1] - grow <= y <= b[3] + grow)


def ep_ground_serve(board, name):
    """Ground pins served INTO the exposed pad, which the board's fill does."""
    out = []
    for fp in board.GetFootprints():
        pads = list(fp.Pads())
        gnd = [p for p in pads if _is_gnd(p.GetNetname())]
        if len(gnd) < 2:
            continue
        # The EP is the largest-area ground pad, and only counts as one when it
        # dwarfs the pins it would serve (a two-pad passive has no EP).
        areas = [(p.GetSizeX() / 1e6) * (p.GetSizeY() / 1e6) for p in gnd]
        ep_i = max(range(len(gnd)), key=lambda i: areas[i])
        rest = [a for i, a in enumerate(areas) if i != ep_i]
        if not rest or areas[ep_i] < 3.0 * max(rest):
            continue
        ep, pins = gnd[ep_i], [p for i, p in enumerate(gnd) if i != ep_i]
        ep_box = _pad_box(ep)
        pin_boxes = [(p, _pad_box(p)) for p in pins]
        ref = fp.GetReference()
        for t in board.GetTracks():
            if not _is_gnd(t.GetNetname()):
                continue
            if t.GetClass() == "PCB_VIA":
                x, y = t.GetStart().x / 1e6, t.GetStart().y / 1e6
                for p, b in pin_boxes:
                    if _in_box(x, y, b):
                        out.append({"check": "ep_ground_serve", "module": name,
                                    "part": ref, "pad": p.GetNumber(),
                                    "what": "via on a ground PIN pad",
                                    "at": [round(x, 2), round(y, 2)]})
                continue
            a = (t.GetStart().x / 1e6, t.GetStart().y / 1e6)
            c = (t.GetEnd().x / 1e6, t.GetEnd().y / 1e6)
            for p, b in pin_boxes:
                ends_on_pin = _in_box(*a, b) or _in_box(*c, b)
                if not ends_on_pin:
                    continue
                if _in_box(*a, ep_box) or _in_box(*c, ep_box):
                    out.append({"check": "ep_ground_serve", "module": name,
                                "part": ref, "pad": p.GetNumber(),
                                "what": "track from a ground PIN to the EP",
                                "at": [round(a[0], 2), round(a[1], 2)]})
    return out


CHECKS = (ep_ground_serve,)


def fragments():
    pats = (os.path.join(_root(), "modules", "*", "layout", "layout.kicad_pcb"),
            os.path.join(_root(), "*", "modules", "*", "layout", "layout.kicad_pcb"))
    return sorted(set(sum((glob.glob(p) for p in pats), [])))



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("targets", nargs="*", type=cell_arg, metavar="CELL",
                    help="cell names or fragment paths (default: every cell)")
    json_option(ap, 'the findings')
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()
    _out = hush(a.json)   # with --json the JSON is the answer
    # A CELL, by name or by path. This audits cells, not boards - saying so
    # beats loading whatever was handed over and failing somewhere underneath.
    from placemat.project import active
    cells = active().module_dirs
    paths = []
    for want in a.targets:
        if os.path.isfile(want):
            paths.append(want)
            continue
        d = cells.get(want) or next((v for k, v in cells.items()
                                     if k.lower() == want.lower()), None)
        frag = os.path.join(d, "layout", "layout.kicad_pcb") if d else None
        if not frag or not os.path.exists(frag):
            sys.exit("placemat modules: %r is not a cell here (this audits CELLS, "
                     "not boards).\n  cells: %s" % (want, ", ".join(sorted(cells))))
        paths.append(frag)
    paths = paths or fragments()
    findings = []
    for p in paths:
        name = os.path.basename(os.path.dirname(os.path.dirname(p)))
        b = pcbnew.LoadBoard(p)
        if b is None:
            sys.exit("placemat modules: %s is not a board file" % p)
        for chk in CHECKS:
            findings += chk(b, name)
    by_mod = {}
    for f in findings:
        by_mod.setdefault(f["module"], []).append(f)
    print("module audit: %d fragment(s), %d finding(s)" % (len(paths), len(findings)))
    for mod in sorted(by_mod):
        rows = by_mod[mod]
        kinds = {}
        for r in rows:
            kinds.setdefault((r["part"], r["what"]), []).append(r["pad"])
        print("  %s" % mod)
        for (ref, what), padlist in sorted(kinds.items()):
            print("     %-6s %-34s pads %s" % (ref, what, ",".join(sorted(padlist))))
    unhush(_out)
    emit(findings, a.json)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
