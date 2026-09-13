"""placemat: lay out a KiCad board from a Python script and see what changed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="placemat", description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="one reproducible layout attempt: generate, script, write, check, record")
    run.add_argument("script", help="the board's layout script (or its directory)")
    run.add_argument("--label", help="run name (default: a timestamp)")
    run.add_argument("--fresh", action="store_true", help="regenerate the board even if a generation is cached")
    run.add_argument("--no-render", action="store_true", help="skip the PNG renders")
    run.add_argument("--no-drc", action="store_true", help="skip kicad-cli DRC")
    run.add_argument("--json", action="store_true", help="print the run record as JSON on stdout")
    run.add_argument("-q", "--quiet", action="store_true")
    run.add_argument("-v", "--verbose", action="store_true", help="every placement and copper step as it resolves")

    imp = sub.add_parser("impact", help="what changed between two run records")
    imp.add_argument("before")
    imp.add_argument("after")

    drc = sub.add_parser("drc", help="kicad-cli DRC on a board, as buckets")
    drc.add_argument("pcb")
    drc.add_argument("--json", action="store_true")

    m = sub.add_parser("measure", help="what the generated board measures: a cell or part's extents and pads")
    m.add_argument("pcb")
    m.add_argument("items", nargs="*", help="cell names or part instances (default: every cell)")
    m.add_argument("--rotation", type=float, default=0.0)
    return root


def cmd_run(args) -> int:
    from .runner import run
    result = run(args.script, label=args.label, fresh=args.fresh, render=not args.no_render,
                 drc=not args.no_drc, quiet=args.quiet or args.json, verbose=args.verbose)
    if args.json:
        print(json.dumps(json.loads((result.run_dir / "run.json").read_text()), indent=2))
    return 0 if result.status == "ok" else 1


def cmd_impact(args) -> int:
    from .report import RunRecord, impact
    print(impact(RunRecord.load(_record(args.before)), RunRecord.load(_record(args.after))))
    return 0


def _record(p) -> Path:
    p = Path(p)
    return p / "run.json" if p.is_dir() else p


def cmd_drc(args) -> int:
    from .kicad.drc import run_drc
    from .report import airwires_from_drc
    pcb = Path(args.pcb)
    out = pcb.parent / "drc.json"
    report = run_drc(pcb, out)
    aw = airwires_from_drc(json.loads(out.read_text()))
    if args.json:
        print(json.dumps({"by_type": report.by_type, "real": report.real, "outstanding": report.outstanding,
                          "unconnected": report.unconnected, "open_nets": dict(report.open_nets), "airwires": aw}, indent=2))
    else:
        print(report.summary())
        print("airwires %d, %.1f mm, %d crossings" % (aw["count"], aw["total_mm"], aw["crossings"]))
        for net, mm in sorted(aw["per_net"].items(), key=lambda kv: -kv[1])[:10]:
            print("   %-20s %.1f mm" % (net, mm))
    return 1 if report.real else 0


def cmd_measure(args) -> int:
    from .kicad.read import read_board
    from .layout import Board
    from .values import Cell, Part
    snap = read_board(args.pcb)
    b = Board(snap)
    items = args.items or sorted(snap.cells)
    for name in items:
        if name in snap.cells:
            e = b.extent(Cell(name), rotation=args.rotation)
            c = snap.cell(name)
            print("cell %-16s %.3f x %.3f (rot %g)  members %s" % (
                name, e.width, e.height, args.rotation, " ".join(fp.ref for fp in c.members)))
        else:
            fp = snap.footprint(name)
            e = b.extent(Part(fp.inst), rotation=args.rotation)
            print("part %-16s %s  %.3f x %.3f (rot %g)  pads %s" % (
                fp.inst, fp.ref, e.width, e.height, args.rotation,
                " ".join("%s:%s" % (p.number, p.net) for p in fp.pads)))
    return 0


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    return {"run": cmd_run, "impact": cmd_impact, "drc": cmd_drc, "measure": cmd_measure}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
