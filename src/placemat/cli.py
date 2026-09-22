"""The placemat command line: run, route, impact, drc, measure, parts, datasheet, check."""
from __future__ import annotations

import argparse
import json
import re
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
                     help="carry on past decided items that collide (recorded as findings) instead of stopping "
                          "there; an item declared required=True still stops the run")

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

    m = sub.add_parser("measure", help="what a part or a cell measures: position, boxes and every pad's "
                                       "real copper, on a board or on a bare .kicad_mod")
    m.add_argument("pcb", help="a layout.kicad_pcb, a layout script, or a footprint.kicad_mod")
    m.add_argument("items", nargs="*", help="cell names or part instances (default: every cell)")
    m.add_argument("--pads", action="store_true",
                   help="every pad's number, net, layers, centre and copper box")
    m.add_argument("--json", action="store_true")

    pl = sub.add_parser("parts", help="every part on the board: instance, refdes, face, cell, "
                                      "courtyard area, pin count and value")
    pl.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    pl.add_argument("--json", action="store_true")

    oc = sub.add_parser("occupancy", help="what copper is at a point or in a box, and where a via "
                                          "can stand near a pad")
    oc.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    what = oc.add_mutually_exclusive_group(required=True)
    what.add_argument("--at", metavar="X,Y", help="the copper under a point, per layer, and whether a via fits")
    what.add_argument("--box", metavar="X0,Y0,X1,Y1", help="the copper inside a box, by net and kind")
    what.add_argument("--via-near", metavar="PART.PAD", help="the nearest spot a via can stand and be reached")
    oc.add_argument("--net", default=None, help="the via's net (default: the pad's, or what is at the point)")
    oc.add_argument("--size", type=float, default=None, help="via diameter, mm (default: the net's class)")
    oc.add_argument("--drill", type=float, default=None, help="via drill, mm (default: the net's class)")
    oc.add_argument("--layer", default=None, help="the tail's layer (default: the pad's)")
    oc.add_argument("--radius", type=float, default=2.0, help="how far from the pad to look, mm")
    oc.add_argument("--step", type=float, default=0.05, help="the search's grid, mm")
    oc.add_argument("--in-pad", action="store_true",
                    help="allow the via to sit in its own pad (it then needs plugging)")
    oc.add_argument("--json", action="store_true")

    dsp = sub.add_parser("datasheet", help="what is in a datasheet and where: the page for each "
                                           "of land pattern, package, rules and pins")
    dsp.add_argument("pdf", help="a datasheet PDF, or the word `check`")
    dsp.add_argument("rest", nargs="*", help="for `check`: <pdf> <footprint.kicad_mod>")
    dsp.add_argument("--show", metavar="PAGE|TOPIC", default=None,
                     help="render a page (p7) or a topic's best page (land) and print its text")
    dsp.add_argument("--read", action="store_true",
                     help="the facts the sheet could be made to yield, with their provenance")
    dsp.add_argument("--pitch", type=float, default=None, help="check: the pitch the sheet requires, mm")
    dsp.add_argument("--pad", default=None, metavar="WxH", help="check: the pad size the sheet requires, mm")
    dsp.add_argument("--pads", type=int, default=None, help="check: how many pads the sheet shows")
    dsp.add_argument("--span", type=float, default=None, help="check: the span across the pads, mm")
    dsp.add_argument("--tol", type=float, default=0.02,
                     help="how far a value may differ and still agree, mm")
    dsp.add_argument("--out", default=None, help="where renders go (default: beside the PDF)")
    dsp.add_argument("--dpi", type=int, default=300)
    dsp.add_argument("--no-ocr", action="store_true",
                     help="do not read a text-poor page off its render")
    dsp.add_argument("--json", action="store_true")

    sh = sub.add_parser("show", help="one cell or part on its own: a render from above and below, its pads by net, "
                                     "and the sides its module declared (outward, quiet, handoff)")
    sh.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    sh.add_argument("item", help="a cell name, a part instance or a refdes")
    sh.add_argument("--out", help="where the PNGs go (default: <board dir>/.placemat/show)")

    fc = sub.add_parser("faces", help="write a module fragment's sides into it: outward=N (faces the board edge), "
                                      "quiet=S (away from aggressors), handoff=E (where its signals leave)")
    fc.add_argument("fragment", help="the module's layout/layout.kicad_pcb")
    fc.add_argument("sides", nargs="+", metavar="SIDE=N|S|E|W", help="outward=, quiet=, handoff=")

    st = sub.add_parser("settings", help="every resolved setting, its value and the file it came from")
    st.add_argument("where", nargs="?", default=".", help="a layout script or a board directory (default: here)")
    st.add_argument("--json", action="store_true")

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


def overrides_from(args) -> dict:
    """The settings a command's flags set, and only those: a flag left off
    falls to placemat.toml, and a key absent from that falls to the default."""
    out = {}
    for flag, name in (("ambient", "check_ambient_c"), ("keep_out", "check_keep_out_mm"),
                       ("rise", "check_rise_c"), ("copper_oz", "check_copper_oz")):
        value = getattr(args, flag, None)
        if value is not None:
            out[name] = value
    limits = {}
    for item in getattr(args, "limit", None) or []:
        name, _, value = item.partition("=")
        limits[name] = float(value)
    if limits:
        out["check_limits"] = limits
    return out


def check_kwargs(s) -> dict:
    """The arguments `checks.run_checks` takes, from the resolved settings."""
    from .checks import kwargs_from
    return kwargs_from(s)


def _plain(v):
    return list(v) if isinstance(v, tuple) else v


def _show(v) -> str:
    if isinstance(v, (tuple, list)):
        return "[%d]" % len(v)
    if isinstance(v, dict):
        return "{%d}" % len(v)
    return "%s" % (v,)


def cmd_settings(args) -> int:
    from .settings import load, Settings, split_key
    from .project import find_board
    p = Path(args.where)
    start = p if p.is_dir() else find_board(p).board_dir
    s = load(start)
    if args.json:
        console.data(json.dumps({k: {"value": _plain(getattr(s, k)), "source": s.source_of(k)}
                                 for k in Settings.keys()}, indent=2, sort_keys=True))
        return 0
    for name in Settings.keys():
        section, key = split_key(name)
        console.say("settings", "%-28s %-24s %s" % (
            "%s.%s" % (section, key), _show(getattr(s, name)), s.source_of(name)))
    return 0


def cmd_run(args) -> int:
    from .runner import run
    result = run(args.script, label=args.label, fresh=args.fresh, render=not args.no_render,
                 drc=not args.no_drc, quiet=args.quiet or args.json, verbose=args.verbose,
                 route=args.route, route_quick=not args.route_full, route_exclude=args.route_exclude,
                 keep_going=args.keep_going, overrides=overrides_from(args))
    if args.json:
        console.data(json.dumps(json.loads((result.run_dir / "run.json").read_text()), indent=2))
    # a run that placed but came out worse than the best of its parts is a
    # failure too, so a regression cannot pass unnoticed in a loop
    return 0 if result.status == "ok" and not result.regressed else 1


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
        for breach in report.keepout_breaches:
            console.say("route", breach)
        for net, n in sorted(report.open_nets.items(), key=lambda kv: -kv[1])[:15]:
            console.say("route", "%-20s %d open" % (net, n))
        console.say("route", "routed board: %s" % report.routed_pcb)
    return 0 if report.valid else 1


def _near(name: str, snap) -> str:
    """The closest few names, because not knowing what the parts are called is
    the usual reason for getting one wrong."""
    import difflib
    known = [fp.inst for fp in snap.footprints] + list(snap.cells)
    close = difflib.get_close_matches(name, known, n=3, cutoff=0.4)
    return ("; did you mean %s?" % ", ".join(close)) if close else ""


def cmd_measure(args) -> int:
    from . import describe
    from .kicad.read import read_board, read_footprint
    from .project import find_board
    p = Path(args.pcb)
    if p.suffix == ".kicad_mod":
        fp, digest = read_footprint(p)
        if args.json:
            doc = describe.part_facts(fp)
            doc["sha256"] = digest
            doc["pads"] = [describe.pad_facts(fp, q) for q in fp.pads]
            console.data(json.dumps({"parts": [doc]}, indent=2))
        else:
            console.lines("measure", "\n".join(
                describe.part_lines(fp, pads=args.pads, digest=digest)))
        return 0
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    snap = read_board(pcb)
    items = args.items or sorted(snap.cells)
    docs, lines = [], []
    for name in items:
        if name in snap.cells:
            c = snap.cell(name)
            docs.append({"cell": name, "size": [round(c.box.width, 3), round(c.box.height, 3)],
                         "members": [fp.ref for fp in c.members]})
            lines.append("cell %-16s %.3f x %.3f  members %s" % (
                name, c.box.width, c.box.height, " ".join(fp.ref for fp in c.members)))
            continue
        try:
            fp = snap.footprint(name)
        except KeyError:
            raise SystemExit("no cell or part called %r on %s. `placemat parts %s` lists them%s"
                             % (name, pcb, args.pcb, _near(name, snap)))
        doc = describe.part_facts(fp, snap)
        if args.pads:
            doc["pads"] = [describe.pad_facts(fp, q, snap) for q in fp.pads]
            doc["copper_on_pads"] = describe.copper_on(fp, snap)
        docs.append(doc)
        lines += describe.part_lines(fp, snap, pads=args.pads)
    if args.json:
        console.data(json.dumps({"parts": docs}, indent=2))
    else:
        console.lines("measure", "\n".join(lines))
    return 0


def cmd_parts(args) -> int:
    from . import describe
    from .kicad.read import read_board
    from .project import find_board
    p = Path(args.pcb)
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    snap = read_board(pcb)
    if args.json:
        console.data(json.dumps({"parts": describe.parts_rows(snap)}, indent=2))
        return 0
    console.lines("parts", "\n".join(describe.parts_lines(snap)))
    return 0


def _page_for(what: str, candidates):
    """`p7` is a page; `land` is a topic, resolved through the index."""
    if re.fullmatch(r"p?\d+", what):
        return int(what.lstrip("p"))
    for c in candidates:
        if c.topic == what and c.band != "none":
            return c.page
    return None


def _pages_of(pdf, path, args, with_paths=True) -> dict:
    """Every page's text and drawing. A page with no text of its own is read
    off its render instead, when tesseract is here and --no-ocr is not set."""
    by_page = {}
    for n in range(1, pdf.page_count(path) + 1):
        runs = pdf.text_runs(path, n)
        if not args.no_ocr and pdf.have_ocr() and pdf.text_is_thin(runs):
            runs = runs + pdf.ocr_runs(path, n, Path(args.out or path.parent), args.dpi)
        by_page[n] = (runs, pdf.draw_paths(path, n) if with_paths else ())
    return by_page


def _expected_from(args) -> dict:
    """Only the values a flag actually set. A check nobody asked for is
    reported as unchecked, never as passed."""
    out = {}
    for flag in ("pitch", "pads", "span"):
        value = getattr(args, flag, None)
        if value is not None:
            out[flag] = value
    if args.pad:
        w, _, h = args.pad.lower().partition("x")
        out["pad"] = (float(w), float(h))
    return out


def _datasheet_check(args) -> int:
    from . import datasheet as ds
    from .kicad.read import read_footprint
    from .pdf import read as pdf
    if len(args.rest) != 2:
        console.say("datasheet", "check takes a datasheet and a footprint: "
                                 "placemat datasheet check <pdf> <footprint.kicad_mod>")
        return 1
    pdf_path, mod = Path(args.rest[0]), Path(args.rest[1])
    try:
        by_page = _pages_of(pdf, pdf_path, args, with_paths=False)
    except pdf.PdfError as e:
        console.say("datasheet", str(e))
        return 1
    fp, digest = read_footprint(mod)
    got = ds.compare(_expected_from(args), fp.pads, ds.facts(by_page), args.tol)
    if args.json:
        console.data(json.dumps({"pdf": str(pdf_path), "footprint": str(mod),
                                 "sha256": digest, "checks": ds.check_rows(got)}, indent=2))
    else:
        console.say("check", "%s against %s" % (mod.name, pdf_path.name))
        console.lines("check", "\n".join(ds.check_lines(got)))
    return 1 if any(c.verdict == "MISMATCH" for c in got) else 0


def cmd_datasheet(args) -> int:
    from . import datasheet as ds
    from .pdf import read as pdf
    if args.pdf == "check":
        return _datasheet_check(args)
    path = Path(args.pdf)
    try:
        pages = pdf.page_count(path)
        by_page = _pages_of(pdf, path, args)
    except pdf.PdfError as e:
        console.say("datasheet", str(e))
        return 1
    found = ds.index(by_page)
    if args.read:
        sourced = ds.facts(by_page)
        if args.json:
            console.data(json.dumps({"pdf": str(path), "facts": ds.read_rows(sourced)}, indent=2))
            return 0
        console.lines("datasheet", "\n".join(ds.read_lines(path.stem, sourced)))
        return 0
    if args.show:
        page = _page_for(args.show, found)
        if page is None:
            console.say("datasheet", "no candidate for %r; the index says what was found, "
                                     "or name a page as p<N>" % args.show)
            return 1
        out_dir = Path(args.out) if args.out else path.parent
        png = pdf.render(path, page, out_dir, args.dpi)
        runs, _ = by_page[page]
        if args.json:
            console.data(json.dumps({"page": page, "png": str(png),
                                     "text": [r.text for r in runs]}, indent=2))
            return 0
        console.say("datasheet", "page %d rendered to %s" % (page, png))
        for r in runs:
            console.say("datasheet", "  %-6.0f %-6.0f %s" % (r.box.left, r.box.top, r.text.strip()))
        return 0
    if args.json:
        console.data(json.dumps({"pdf": str(path), "pages": pages, "ocr": pdf.have_ocr(),
                                 "index": ds.index_rows(found)}, indent=2))
        return 0
    console.lines("datasheet", "\n".join(ds.index_lines(path.stem, pages, found)))
    if not pdf.have_ocr():
        console.say("datasheet", "tesseract is not installed: a page whose dimensions are "
                                 "outlined curves has no text to read")
    return 0


def _numbers(text: str, n: int) -> list:
    values = [float(v) for v in text.replace(" ", "").split(",")]
    if len(values) != n:
        raise SystemExit("expected %d numbers separated by commas, got %r" % (n, text))
    return values


def cmd_occupancy(args) -> int:
    from . import queries
    from .kicad.read import read_board
    from .project import find_board
    from .settings import bind, load
    from .values import Box, CopperLayer, Location
    p = Path(args.pcb)
    src = None if p.suffix == ".kicad_pcb" else find_board(p)
    pcb = p if src is None else src.pcb
    with bind(load(src.board_dir if src is not None else pcb.parent)):
        g = read_board(pcb)

    def via_rules(net):
        nc = g.netclasses.get(net)
        size = args.size or (nc.via_diameter if nc else 0.6)
        drill = args.drill or (nc.via_drill if nc else 0.3)
        width = nc.track_width if nc else 0.2
        return size, drill, width

    if args.at:
        x, y = _numbers(args.at, 2)
        at = Location(x, y)
        under = [c for cs in queries.copper_at(g, at).values() for c in cs]
        net = args.net if args.net is not None else (under[0].net if under else "")
        size, drill, _ = via_rules(net)
        if args.json:
            v = queries.judge_via(g, at, net, size, drill)
            console.data(json.dumps({"at": [x, y], "copper": {
                l.value: [{"kind": c.kind, "net": c.net, "owner": c.owner} for c in cs]
                for l, cs in queries.copper_at(g, at).items()},
                "via": {"net": net, "clear": v.clear, "hard": list(v.hard), "soft": list(v.soft)}}, indent=2))
        else:
            console.lines("occupancy", "\n".join(queries.at_lines(g, at, net, size, drill)))
        return 0
    if args.box:
        x0, y0, x1, y1 = _numbers(args.box, 4)
        box = Box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        if args.json:
            console.data(json.dumps({l.value: [{"net": n, "kind": k, "count": c} for (n, k), c in cnt.most_common()]
                                     for l, cnt in queries.copper_in(g, box).items()}, indent=2))
        else:
            console.lines("occupancy", "\n".join(queries.box_lines(g, box)))
        return 0
    part, _, number = args.via_near.rpartition(".")
    fp = g.footprint(part)
    pads = [q for q in fp.pads if q.number == number]
    if not pads:
        console.say("occupancy", "%s has no pad %r; its pads are %s" % (
            fp.inst, number, ", ".join(sorted({q.number for q in fp.pads}))))
        return 1
    pad = pads[0]
    net = args.net if args.net is not None else pad.net
    size, drill, width = via_rules(net)
    layer = CopperLayer.of(args.layer) if args.layer else queries._ordered(pad.layers or g.layers)[0]
    source = () if args.in_pad else pad.outlines
    spot, tally, tried = queries.free_spot(pad.box.center, queries.via_judge(g, pad.box.center, net, size, drill,
                                                                              width, layer, source),
                                           args.radius, args.step)
    if args.json:
        console.data(json.dumps({"spot": None if spot is None else {
            "at": [spot.at.x, spot.at.y], "distance": spot.distance, "soft": list(spot.soft)},
            "tally": dict(tally), "tried": tried, "net": net, "size": size, "drill": drill,
            "layer": layer.value}, indent=2))
    else:
        console.lines("occupancy", "\n".join(queries.spot_lines(spot, tally, tried, net,
                                                                  "%s.%s" % (fp.inst, pad.number))))
    return 0 if spot is not None else 1


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
    from .settings import bind, load
    p = Path(args.pcb)
    src = None if p.suffix == ".kicad_pcb" else find_board(p)
    pcb = p if src is None else src.pcb
    cfg = load(src.board_dir if src is not None else pcb.parent, overrides=overrides_from(args))
    with bind(cfg):
        geometry = read.read_board(pcb)
        verdicts = checks.run_checks(geometry, **check_kwargs(cfg))
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
            "route": cmd_route, "check": cmd_check, "show": cmd_show, "faces": cmd_faces,
            "settings": cmd_settings, "parts": cmd_parts,
            "datasheet": cmd_datasheet, "occupancy": cmd_occupancy}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
