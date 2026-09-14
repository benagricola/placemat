"""The placemat command line: run, route, impact, drc, measure, check."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .console import console


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
    run.add_argument("--route", action="store_true", help="after the checks, route a copy with KiCadRoutingTools and score closure")
    run.add_argument("--route-full", action="store_true", help="with --route: the router's full run, not one round")
    run.add_argument("--route-exclude", nargs="*", default=[], help="with --route: extra nets to leave unrouted")
    run.add_argument("--keep-going", action="store_true",
                     help="carry on past FIXED/EDGE items that collide (recorded as findings) instead of stopping there")

    rt = sub.add_parser("route", help="route a copy of a placed board with KiCadRoutingTools and score closure")
    rt.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    rt.add_argument("--exclude", nargs="*", default=[], help="nets to leave unrouted (planes, pours)")
    rt.add_argument("--layers", nargs="*", help="copper layers to route on (default: all)")
    rt.add_argument("--full", action="store_true", help="the router's full run, not one round")
    rt.add_argument("--iterations", type=int, help="cap the router's search per net (default: the router's own)")
    rt.add_argument("--out", help="work directory (default: <board dir>/.placemat/route)")
    rt.add_argument("--json", action="store_true")

    imp = sub.add_parser("impact", help="what changed between two runs (ids, id prefixes, labels, or paths)")
    imp.add_argument("before")
    imp.add_argument("after")
    imp.add_argument("--board", help="board directory holding .placemat/runs (default: found under the cwd)")

    drc = sub.add_parser("drc", help="kicad-cli DRC on a board, as buckets")
    drc.add_argument("pcb")
    drc.add_argument("--json", action="store_true")

    m = sub.add_parser("measure", help="what the generated board measures: each cell's size and members, a part's size and pads")
    m.add_argument("pcb")
    m.add_argument("items", nargs="*", help="cell names or part instances (default: every cell)")

    sh = sub.add_parser("show", help="one cell or part on its own: a render from above and below, its pads by net, "
                                     "and the sides its module declared (outward, quiet, handoff)")
    sh.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    sh.add_argument("item", help="a cell name, a part instance or a refdes")
    sh.add_argument("--out", help="where the PNGs go (default: <board dir>/.placemat/show)")

    fc = sub.add_parser("faces", help="write a module fragment's sides into it: outward=N (faces the board edge), "
                                      "quiet=S (away from aggressors), handoff=E (where its signals leave)")
    fc.add_argument("fragment", help="the module's layout/layout.kicad_pcb")
    fc.add_argument("sides", nargs="+", metavar="SIDE=N|S|E|W", help="outward=, quiet=, handoff=")

    ck = sub.add_parser("check", help="design checks from the parts' Pm.* facts: hot loops, switch nodes, keep-out, "
                                      "crossings under sense tracks, current path widths, junction temperature")
    ck.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    ck.add_argument("--ambient", type=float, default=None, help="board temperature in C (default: %g)" % 100.0)
    ck.add_argument("--keep-out", type=float, default=None, help="sense copper's distance from a switch node, mm")
    ck.add_argument("--rise", type=float, default=None, help="track temperature rise the widths are sized for, C")
    ck.add_argument("--copper-oz", type=float, default=None, help="outer copper weight the widths are sized for")
    ck.add_argument("--limit", action="append", default=[], metavar="CHECK=VALUE",
                    help="a bound for a reporting check, e.g. hot-loop=20 (mm2) or switch-node=15 (mm2)")
    ck.add_argument("--json", action="store_true")
    return root


def cmd_run(args) -> int:
    from .runner import run
    result = run(args.script, label=args.label, fresh=args.fresh, render=not args.no_render,
                 drc=not args.no_drc, quiet=args.quiet or args.json, verbose=args.verbose,
                 route=args.route, route_quick=not args.route_full, route_exclude=args.route_exclude,
                 keep_going=args.keep_going)
    if args.json:
        console.data(json.dumps(json.loads((result.run_dir / "run.json").read_text()), indent=2))
    return 0 if result.status == "ok" else 1


def cmd_impact(args) -> int:
    from .report import RunRecord, impact
    console.lines("impact", impact(RunRecord.load(_record(args.before, args.board)),
                                   RunRecord.load(_record(args.after, args.board))))
    return 0


def _runs_dirs(board) -> list:
    if board:
        return [Path(board) / ".placemat" / "runs"]
    here = Path.cwd()
    found = [d for d in [here / ".placemat/runs"] + sorted(here.glob("*/.placemat/runs")) if d.is_dir()]
    return found


def _record(ref, board=None) -> Path:
    """A run.json from a path, or a run id / prefix / label looked up in the
    runs directories under the cwd (or --board)."""
    from .report import resolve_run
    p = Path(ref)
    if p.exists():
        return p / "run.json" if p.is_dir() else p
    for runs in _runs_dirs(board):
        try:
            return resolve_run(runs, ref) / "run.json"
        except FileNotFoundError:
            continue
    raise SystemExit("no run %r; looked in %s" % (ref, ", ".join(str(r) for r in _runs_dirs(board)) or "no runs dir"))


def cmd_drc(args) -> int:
    from .kicad.drc import run_drc
    from .report import airwires_from_drc
    pcb = Path(args.pcb)
    out = pcb.parent / "drc.json"
    report = run_drc(pcb, out)
    aw = airwires_from_drc(json.loads(out.read_text()))
    if args.json:
        console.data(json.dumps({"by_type": report.by_type, "real": report.real, "outstanding": report.outstanding,
                                 "unconnected": report.unconnected, "open_nets": dict(report.open_nets),
                                 "airwires": aw}, indent=2))
    else:
        console.say("drc", report.summary())
        console.say("drc", "airwires %d, %.1f mm, %d crossings" % (aw["count"], aw["total_mm"], aw["crossings"]))
        for net, mm in sorted(aw["per_net"].items(), key=lambda kv: -kv[1])[:10]:
            console.say("drc", "%-20s %6.1f mm  %d crossing(s)" % (net, mm, aw["crossings_per_net"].get(net, 0)))
    return 1 if report.real else 0


def cmd_route(args) -> int:
    from .kicad.route import route_board
    from .project import find_board
    p = Path(args.pcb)
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    work = Path(args.out) if args.out else pcb.parent.parent.parent / ".placemat" / "route"
    report = route_board(pcb, work, exclude_nets=set(args.exclude), layers=args.layers, quick=not args.full,
                         iterations=args.iterations)
    if args.json:
        console.data(json.dumps(report.as_dict(), indent=2))
    else:
        console.say("route", report.summary())
        for net, n in sorted(report.open_nets.items(), key=lambda kv: -kv[1])[:15]:
            console.say("route", "%-20s %d open" % (net, n))
        console.say("route", "routed board: %s" % report.routed_pcb)
    return 0 if report.valid else 1


def cmd_measure(args) -> int:
    from .kicad.read import read_board
    snap = read_board(args.pcb)
    items = args.items or sorted(snap.cells)
    for name in items:
        if name in snap.cells:
            c = snap.cell(name)
            console.say("measure", "cell %-16s %.3f x %.3f  members %s" % (
                name, c.box.width, c.box.height, " ".join(fp.ref for fp in c.members)))
        else:
            fp = snap.footprint(name)
            console.say("measure", "part %-16s %s  %.3f x %.3f  pads %s" % (
                fp.inst, fp.ref, fp.body_box.width, fp.body_box.height,
                " ".join("%s:%s" % (p.number, p.net) for p in fp.pads)))
    return 0


def cmd_show(args) -> int:
    from .kicad.read import read_board
    from .kicad.write import show_item
    from .project import find_board
    p = Path(args.pcb)
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    snap = read_board(pcb)
    name = args.item
    if name in snap.cells:
        c = snap.cell(name)
        console.say("show", "cell %s  %.2f x %.2f mm  %d members  faces: %s" % (
            name, c.box.width, c.box.height, len(c.members),
            ", ".join("%s=%s" % kv for kv in sorted(c.faces.items())) or "none declared (edge placement assumes local +Y outward)"))
        fps = list(c.members)
    else:
        fp = snap.footprint(name)
        console.say("show", "part %s (%s)  %.2f x %.2f mm  face %s  rotation %g" % (
            fp.inst, fp.ref, fp.body_box.width, fp.body_box.height, fp.face.value, fp.rotation))
        fps = [fp]
        name = fp.ref
    ref_box = snap.cell(name).box if name in snap.cells else fps[0].body_box
    for fp in fps:
        console.say("show", "  %-6s %-24s at (%+.2f, %+.2f) from the %s centre, rot %g, %s" % (
            fp.ref, fp.inst, fp.location.x - ref_box.center.x, fp.location.y - ref_box.center.y,
            "cell" if name in snap.cells else "part", fp.rotation, fp.face.value))
        for pad in fp.pads:
            side = ("N" if pad.location.y < ref_box.center.y - 0.01 else "S" if pad.location.y > ref_box.center.y + 0.01 else "") + \
                   ("W" if pad.location.x < ref_box.center.x - 0.01 else "E" if pad.location.x > ref_box.center.x + 0.01 else "")
            console.say("show", "      pad %-4s %-20s %s of centre" % (pad.number, pad.net or "-", side or "at the"))
    out = Path(args.out) if args.out else pcb.parent.parent.parent / ".placemat" / "show" if pcb.parent.name != "." else pcb.parent / ".placemat" / "show"
    if not args.out:
        # <board dir>/.placemat/show: the board dir holds layout/<Board>/layout.kicad_pcb
        out = pcb.parents[2] / ".placemat" / "show" if pcb.parent.parent.name == "layout" else pcb.parent / ".placemat" / "show"
    pngs = show_item(pcb, name, out)
    for png in pngs:
        console.say("show", "render %s" % png)
    return 0


def cmd_faces(args) -> int:
    from .kicad.write import write_faces
    faces = {}
    for item in args.sides:
        k, _, v = item.partition("=")
        if k not in ("outward", "quiet", "handoff") or v.upper() not in ("N", "S", "E", "W"):
            raise SystemExit("a side is outward=, quiet= or handoff= with N, S, E or W, not %r" % item)
        faces[k] = v.upper()
    console.say("faces", "%s: %s" % (args.fragment, write_faces(args.fragment, faces)))
    return 0


def cmd_check(args) -> int:
    from . import checks
    from .kicad import read
    from .project import find_board
    p = Path(args.pcb)
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    geometry = read.read_board(pcb)
    limits = {}
    for item in args.limit:
        name, _, value = item.partition("=")
        limits[name] = float(value)
    kw = {k: v for k, v in (("ambient_c", args.ambient), ("keep_out_mm", args.keep_out),
                            ("rise_c", args.rise), ("copper_oz", args.copper_oz)) if v is not None}
    verdicts = checks.run_checks(geometry, limits=limits, **kw)
    if args.json:
        console.data(json.dumps([v.__dict__ for v in verdicts], indent=2))
    else:
        for v in verdicts:
            console.say("check", v.line())
        if not verdicts:
            console.say("check", "no Pm.* facts on this board: nothing to check")
    return 1 if any(v.ok is False for v in verdicts) else 0


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    return {"run": cmd_run, "impact": cmd_impact, "drc": cmd_drc, "measure": cmd_measure,
            "route": cmd_route, "check": cmd_check, "show": cmd_show, "faces": cmd_faces}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
