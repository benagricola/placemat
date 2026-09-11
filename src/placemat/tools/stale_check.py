#!/usr/bin/env python3
"""Was this board placed against the cells as they are NOW?

A module's layout reaches a board only when the board is generated from an
empty directory: the generator applies a fragment solely to footprints that are
new in that sync, because re-applying it to parts already on a board would move
them. So a cell re-laid-out after a board was placed does not reach that board,
and nothing says so - the board still opens, still passes DRC, and its own
geometry asserts fail only when somebody finally regenerates it. Three boards
in this repo sat in exactly that state.

Every board records, in its own file, a hash of each cell fragment it was
placed against (BoardLayout writes it on save). This compares those against the
fragments on disk.

  placemat stale                 # every board
  placemat stale <board.kicad_pcb> [...]
  placemat stale --module McuButtons    # who stamps it, and who is stale
  placemat stale --strict        # exit 1 if any board is stale
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys

def _root():
    """The project's root. Asked for, never computed from this file's own path."""
    from placemat.project import active
    return active().root or os.getcwd()


sys.dont_write_bytecode = True


def board_files(root):
    return sorted(glob.glob(os.path.join(root, "*", "layout", "*", "layout.kicad_pcb")))


def module_fragments(root):
    """{module: fragment path} for root and board-local modules."""
    out = {}
    for pat in ("modules/*/", "*/modules/*/"):
        for d in sorted(glob.glob(os.path.join(root, pat))):
            name = os.path.basename(d.rstrip("/"))
            frag = os.path.join(d.rstrip("/"), "layout", "layout.kicad_pcb")
            if os.path.exists(os.path.join(d, name + ".zen")) and os.path.exists(frag):
                out.setdefault(name, frag)
    return out


def frag_hash(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]


def recorded(pcb):
    """{module: (hash, instances)} the board file records. Read as text - this
    runs in the harness's own interpreter, with no pcbnew import."""
    out = {}
    try:
        head = open(pcb, encoding="utf-8", errors="replace").read(400000)
    except OSError:
        return out
    for name, val in re.findall(r'\(property "stamp\.([^"]+)" "([^"]*)"\)', head):
        m = re.match(r"([0-9a-f]+)(?: x(\d+))?", val)
        if m:
            out[name] = (m.group(1), int(m.group(2) or 1))
    return out


def check(pcb, frags):
    rec = recorded(pcb)
    if not rec:
        return {"pcb": pcb, "known": False, "stale": [], "current": []}
    stale, current, gone = [], [], []
    for mod, (h, n) in sorted(rec.items()):
        frag = frags.get(mod)
        if not frag:
            gone.append(mod)
        elif frag_hash(frag) != h:
            stale.append({"module": mod, "instances": n,
                          "placed_against": h, "now": frag_hash(frag)})
        else:
            current.append(mod)
    return {"pcb": pcb, "known": True, "stale": stale, "current": current, "missing": gone}



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("boards", nargs="*")
    ap.add_argument("--module", help="report which boards stamp this cell, and which are stale")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any board is stale")
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()

    frags = module_fragments(_root())
    pcbs = [os.path.abspath(p) for p in a.boards] or board_files(_root())
    reports = [check(p, frags) for p in pcbs]

    if a.module:
        reports = [r for r in reports if a.module in
                   [s["module"] for s in r["stale"]] + r.get("current", [])]

    if a.format == "json":
        json.dump(reports, sys.stdout, indent=1)
        print()
    else:
        for r in reports:
            name = os.path.basename(os.path.dirname(r["pcb"]))
            if not r["known"]:
                print("%-16s no record - generated before provenance, or never scripted;"
                      " regenerate to record it" % name)
                continue
            if r["stale"]:
                print("%-16s STALE: %d of %d cell(s) changed since it was placed"
                      % (name, len(r["stale"]), len(r["stale"]) + len(r["current"])))
                for s in r["stale"]:
                    print("    %-20s placed against %s, now %s  (x%d on this board)"
                          % (s["module"], s["placed_against"], s["now"], s["instances"]))
            else:
                print("%-16s current (%d cell(s))" % (name, len(r["current"])))
            for m in r.get("missing", ()):
                print("    %-20s recorded, but no fragment on disk now" % m)
    return 1 if (a.strict and any(r["stale"] for r in reports)) else 0


if __name__ == "__main__":
    sys.exit(main())
