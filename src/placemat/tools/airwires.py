#!/usr/bin/env python3
"""The ratsnest of a board or module fragment as a number: airwire count,
total length and crossings, per net and per owner (a stamped cell, a loose
part), from the geometry oracle. For a module fragment, `--zen` (or the .zen
found beside the layout folder) splits the open nets into the ones the module
must close itself and the io nets it hands to the board.

Usage (`placemat round` records it every pass):
  placemat airwires <board> [--json out.json] [--top N] [--zen module.zen]
"""
import argparse
import json
import os
import sys

sys.dont_write_bytecode = True   # no __pycache__ beside the sources
import pcbnew

from placemat.args import board as board_arg

from placemat.report import emit, json_option  # noqa: E402
from placemat.layout_oracle import Oracle  # noqa: E402
from placemat.layout_helpers import zen_io_nets, module_zen  # noqa: E402



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcb", type=board_arg, help="board name, or a path to a board file")
    json_option(ap, "the full measure")
    ap.add_argument("--top", type=int, default=8, help="owners and nets to list")
    ap.add_argument("--zen", help="the module's .zen (io nets); found beside layout/ when omitted")
    return ap


def main(args=None):
    a = args if args is not None else parser().parse_args()
    b = pcbnew.LoadBoard(a.pcb)
    o = Oracle(b, path=a.pcb)
    aw = o.airwires()
    zen = a.zen or module_zen(a.pcb)
    if zen:
        io = set(zen_io_nets(zen))
        aw["io_nets"] = sorted(io)
        aw["internal_open"] = {n: v for n, v in aw["per_net"].items() if n not in io}
        aw["io_open"] = {n: v for n, v in aw["per_net"].items() if n in io}
    if emit(aw, a.json):
        return 0
    print("airwires %d, %.0f mm, %d crossings" % (aw["count"], aw["total_mm"], aw["crossings"]))
    if zen:
        print("  module-internal open nets: %d (%.1f mm) %s" % (
            len(aw["internal_open"]), sum(aw["internal_open"].values()),
            ", ".join(sorted(aw["internal_open"])[:a.top])))
        print("  io nets open to the board: %d (%.1f mm)" % (len(aw["io_open"]), sum(aw["io_open"].values())))
    owners = sorted(aw["per_owner"].items(), key=lambda kv: -kv[1]["external_mm"])[:a.top]
    if owners:
        print("  by owner (external mm / internal mm / airwires):")
        for name, r in owners:
            print("    %-16s %7.1f  %6.1f  %4d" % (name, r["external_mm"], r["internal_mm"], r["count"]))
    nets = sorted(aw["per_net"].items(), key=lambda kv: -kv[1])[:a.top]
    print("  longest nets: " + ", ".join("%s %.0f" % (n, v) for n, v in nets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
