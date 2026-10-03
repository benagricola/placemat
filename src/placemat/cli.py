"""The placemat command line: run, route, impact, drc, measure, parts, datasheet, check."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
import tempfile

from . import stop
from .console import console


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="placemat", description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="one reproducible layout attempt: generate, script, write, check, record")
    run.add_argument("script", help="the board's layout script (or its directory)")
    run.add_argument("--label", help="run name (default: a timestamp)")
    run.add_argument("--fresh", action="store_true", help="regenerate the board even if a generation is cached")
    run.add_argument("--no-reuse", action="store_true",
                     help="resolve every step, not replaying the previous run's steps up to the first change")
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

    run.add_argument("--explore", type=float, metavar="SECONDS",
                     help="first spend up to SECONDS trying variants of the focused items' spots and order, and "
                          "report what the best would move. A long explore: run it detached (setsid nohup placemat "
                          "run ... > explore.log 2>&1 &) and do not chain it with ';', which hides its exit status "
                          "(128 + the signal when it was stopped)")
    run.add_argument("--focus", action="append", default=[], metavar="ITEM",
                     help="with --explore: vary this item (a part, cell or block key); repeatable")
    run.add_argument("--focus-after", type=int, metavar="LINE",
                     help="with --explore: vary what the script declares from this line on")
    run.add_argument("--focus-box", metavar="X0,Y0,X1,Y1", help="with --explore: vary what sits in this box (mm)")
    run.add_argument("--jobs", type=int, help="with --explore: worker processes (default [explore] jobs)")
    run.add_argument("--accept", action="store_true",
                     help="with --explore: write the best variant's decisions to the lock and use them")

    rt = sub.add_parser("route", help="route a copy of a placed board with KiCadRoutingTools and score closure")
    rt.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    rt.add_argument("--exclude", nargs="*", default=[], help="nets to leave unrouted (planes, pours)")
    rt.add_argument("--islands", nargs="*", default=[], metavar="NET[=WIDTH]",
                    help="nets with pours whose pads the pours do not reach: routed first and alone, at the "
                         "netclass width or WIDTH mm (adds to [route] islands)")
    rt.add_argument("--layers", nargs="*", help="copper layers to route on (default: all)")
    rt.add_argument("--full", action="store_true", help="the router's full run, not one round")
    rt.add_argument("--iterations", type=int, help="cap the router's search per net (default: the router's own)")
    rt.add_argument("--out", help="work directory (default: <board dir>/.placemat/route)")
    rt.add_argument("--json", action="store_true")
    keep = rt.add_mutually_exclusive_group()
    keep.add_argument("--adopt", nargs="+", metavar="NET",
                      help="keep the router's copper on these nets: every run draws it (a layout script only)")
    keep.add_argument("--adopt-all", action="store_true", help="keep the copper on every net the route closed")
    rt.add_argument("--partial", action="store_true",
                    help="with --adopt: keep a net the route left open in part - each island of its new copper "
                         "that joins two of its pads, or a pad and a plane of it")
    rt.add_argument("--no-lock", action="store_true",
                    help="with --adopt: leave the lock alone (by default the items the kept nets join are locked)")

    rs = sub.add_parser("routes", help="the routes a layout script keeps (route --adopt), and releasing them")
    rs.add_argument("script", help="a layout script")
    rel = rs.add_mutually_exclusive_group()
    rel.add_argument("--release", nargs="+", metavar="NET", help="stop keeping these nets: the router routes them again")
    rel.add_argument("--release-all", action="store_true",
                     help="stop keeping every net: the next route --adopt-all lays them again")

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
    m.add_argument("--copper", nargs="*", default=None, metavar="NET",
                   help="every track segment of these nets (default: all) with its layer, width, ends, bearing and "
                        "what each end lands on, a leg off 0/45/90 flagged; the vias; and each graphic copper "
                        "polygon (net, layer, stroke, filled, vertices) with, per edge, the nearest copper of "
                        "another net on its layer, the gap from the polygon's copper (its outline grown by half "
                        "its stroke) to it, the clearance the net class pair needs and `under` where the gap is "
                        "less; a board's .kicad_dru rules are not read")
    m.add_argument("--keepouts", nargs="*", default=None, metavar="NAME",
                   help="each part within --near of these rule areas (default: all): its physical and courtyard "
                        "gap to it, or that it reaches in")
    m.add_argument("--near", type=float, default=1.0, help="with --keepouts: how near a part is listed (mm, default 1)")
    m.add_argument("--models", action="store_true",
                   help="read each part's 3D model and say when it sits off its pads or looks turned 90 against "
                        "its fab outline")
    m.add_argument("--envelope", action="store_true",
                   help="for each side of a part's drawn envelope, the item that sets it: its layer, which one and its box")
    m.add_argument("--labels", action="store_true",
                   help="the board's silk texts (board.label() and a stamped cell's) with the box KiCad draws")
    m.add_argument("--outline", action="store_true",
                   help="the board's edge: each Edge.Cuts item, the box round them and the board's thickness")
    m.add_argument("--json", action="store_true")

    pl = sub.add_parser("parts", help="every part on the board: instance, refdes, face, cell, "
                                      "courtyard area, pin count and value")
    pl.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    pl.add_argument("--field", action="append", default=[], metavar="NAME",
                    help="a footprint field to list for each part (an order code, a manufacturer part number); repeatable")
    pl.add_argument("--fragments", action="store_true",
                    help="the fragment each part was stamped from, read from the generator's layout.log beside "
                         "the board ('-': placed by the generator itself)")
    pl.add_argument("--json", action="store_true")

    nt = sub.add_parser("nets", help="every net with two or more pads: pad count, parts, span (the minimum "
                                     "spanning tree over pad centres), routed length, detour, vias, layers, pour")
    nt.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    nt.add_argument("--sort", metavar="COLUMN", default=None,
                    help="sort by this column (default: span, largest first)")
    nt.add_argument("--net", nargs="*", default=[], metavar="NET", help="only these nets (default: every one with two or more pads)")
    nt.add_argument("--inst", action="store_true", help="parts as instance paths rather than refdes")
    nt.add_argument("--json", action="store_true")

    oc = sub.add_parser("occupancy", help="what copper is at a point or in a box, where a via "
                                          "can stand near a pad, and the clear corridors between two")
    oc.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    what = oc.add_mutually_exclusive_group(required=True)
    what.add_argument("--at", metavar="X,Y", help="the copper under a point, per layer, and whether a via fits")
    what.add_argument("--box", metavar="X0,Y0,X1,Y1", help="the copper inside a box, by net and kind")
    what.add_argument("--via-near", metavar="PART.PAD", help="the nearest spot a via can stand and be reached")
    what.add_argument("--corridor", nargs=2, metavar=("A", "B"),
                      help="the clear octilinear paths on --layer from pad A to pad B (each PART.PAD), or the "
                           "blockers across the narrowest cut when there is none; needs --layer and --width")
    oc.add_argument("--net", default=None, help="the via's or corridor's net (default: the pad's, or what is at "
                                                 "the point)")
    oc.add_argument("--size", type=float, default=None, help="via diameter, mm (default: the net's class)")
    oc.add_argument("--drill", type=float, default=None, help="via drill, mm (default: the net's class)")
    oc.add_argument("--layer", default=None, help="the tail's layer (default: the pad's); --corridor's layer")
    oc.add_argument("--radius", type=float, default=2.0, help="how far from the pad to look, mm")
    oc.add_argument("--step", type=float, default=0.05, help="the search's grid, mm")
    oc.add_argument("--in-pad", action="store_true",
                    help="allow the via to sit in its own pad (it then needs plugging)")
    oc.add_argument("--width", type=float, default=None, help="--corridor's track width, mm")
    oc.add_argument("--margin", type=float, default=10.0,
                    help="--corridor: how far past A and B the search reaches, mm")
    oc.add_argument("--ignore-kept", action="store_true",
                    help="--corridor: leave out the tracks and vias of kept routes (routes.json), to see the "
                         "room a re-route would have (a layout script only)")
    oc.add_argument("--json", action="store_true")

    dsp = sub.add_parser("datasheet", help="what is in a datasheet and where: the page for each "
                                           "of land pattern, package, rules and pins")
    dsp.add_argument("pdf", help="a datasheet PDF, or the word `check`")
    dsp.add_argument("rest", nargs="*", help="for `check`: <pdf> <footprint.kicad_mod>")
    dsp.add_argument("--show", metavar="PAGE|TOPIC", default=None,
                     help="print a page's (p7) or a topic's best page's (land) text")
    dsp.add_argument("--png", action="store_true",
                     help="with --show: also render the page, under <project>/.placemat/views/datasheet/")
    dsp.add_argument("--read", action="store_true",
                     help="the facts the sheet could be made to yield, with their provenance")
    dsp.add_argument("--pitch", type=float, default=None, help="check: the pitch the sheet requires, mm")
    dsp.add_argument("--pad", default=None, metavar="WxH", help="check: the pad size the sheet requires, mm")
    dsp.add_argument("--pads", type=int, default=None, help="check: how many pads the sheet shows")
    dsp.add_argument("--span", type=float, default=None, help="check: the span across the pads, mm")
    dsp.add_argument("--tol", type=float, default=0.02,
                     help="how far a value may differ and still agree, mm")
    dsp.add_argument("--out", default=None, help="with --show: render the page to this .png path (a directory gets <pdf>-p<N>.png)")
    dsp.add_argument("--dpi", type=int, default=300)
    dsp.add_argument("--no-ocr", action="store_true",
                     help="do not read a text-poor page off its render")
    dsp.add_argument("--json", action="store_true")

    ly = sub.add_parser("layer", help="one copper layer of a board: its zone fills, graphic copper polygons, tracks, "
                                      "vias and pads coloured by net with a legend, and each track inside another "
                                      "net's zone outline")
    ly.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    ly.add_argument("layer", help="a copper layer, e.g. In2.Cu")
    ly.add_argument("--out", help="the SVG to write (default <board dir>/.placemat/views/layer/layer-<layer>.svg)")
    ly.add_argument("--json", action="store_true")

    sh = sub.add_parser("show", help="one cell or part on its own: a render from above and below, its pads by net, "
                                     "and the sides its cell declared (outward, quiet, handoff)")
    sh.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    sh.add_argument("item", help="a cell name, a part instance or a refdes")
    sh.add_argument("--out", help="where the PNGs go (default: <board dir>/.placemat/views/show)")

    fc = sub.add_parser("faces", help="write a fragment's sides into it: outward=N (faces the board edge), "
                                      "quiet=S (away from aggressors), handoff=E (where its signals leave)")
    fc.add_argument("fragment", help="the fragment's layout/layout.kicad_pcb")
    fc.add_argument("sides", nargs="+", metavar="SIDE=N|S|E|W", help="outward=, quiet=, handoff=")

    pv = sub.add_parser("preview", help="place the board (reusing the previous run) and draw it - "
                                        "no board written, no DRC, no render: a picture in seconds")
    pv.add_argument("script", help="a layout script")
    pv.add_argument("--svg", action="store_true", help="write the SVG only, without converting it to PNG")
    pv.add_argument("--face", choices=("front", "back", "both"), default="both")
    pv.add_argument("--out", help="where to write (default <board>/.placemat/views/preview)")
    pv.add_argument("--no-heat", action="store_true", help="leave out the congestion heat map")
    pv.add_argument("--no-links", action="store_true", help="leave out the declared links")
    pv.add_argument("--no-copper", action="store_true", help="leave out the planned copper")
    pv.add_argument("--no-tags", action="store_true",
                    help="leave the annotation tags off the picture (their text is still printed): a close look "
                         "at small parts, which the tags cover")
    pv.add_argument("--zoom", help="draw only X0,Y0,X1,Y1 (board mm) of each face")
    pv.add_argument("--around", help="draw only round this placed part or cell (its instance name)")
    pv.add_argument("--margin", type=float, default=5.0, help="mm round --around (default 5)")

    pv.add_argument("--explore", type=float, metavar="SECONDS",
                     help="first spend up to SECONDS trying variants of the focused items' spots and order, and "
                          "report what the best would move")
    pv.add_argument("--focus", action="append", default=[], metavar="ITEM",
                     help="with --explore: vary this item (a part, cell or block key); repeatable")
    pv.add_argument("--focus-after", type=int, metavar="LINE",
                     help="with --explore: vary what the script declares from this line on")
    pv.add_argument("--focus-box", metavar="X0,Y0,X1,Y1", help="with --explore: vary what sits in this box (mm)")
    pv.add_argument("--jobs", type=int, help="with --explore: worker processes (default [explore] jobs)")
    pv.add_argument("--accept", action="store_true",
                     help="with --explore: write the best variant's decisions to the lock and use them")

    st = sub.add_parser("studio", help="a local page that shows the layout as it is made: the board re-resolved as the "
                                        "script, its modules or placemat.toml change, each step as it settles, and what "
                                        "the last edit moved")
    st.add_argument("script", nargs="?", help="a layout script (default: the page lists the layout scripts under the "
                                               "project of the current directory and you choose one)")
    st.add_argument("--port", type=int, help="the port to listen on, 127.0.0.1 only (default [studio] port; 0: any free one)")
    st.add_argument("--no-open", action="store_true", help="print the address without opening the browser")
    st.add_argument("--host", default="127.0.0.1",
                    help="the address to listen on (default 127.0.0.1); 0.0.0.0 or a LAN address lets another device "
                         "on the network open the page, still only with the printed token")

    fz = sub.add_parser("freeze", help="move lock entries into the script's place() calls, if the script then "
                                       "places exactly as the lock did")
    fz.add_argument("script", help="the board's layout script")
    fz.add_argument("items", nargs="*", help="the entries to freeze")
    fz.add_argument("--all", action="store_true", help="every entry")
    fz.add_argument("--fixed", action="store_true",
                    help="write a firm Location rather than a search with no room (goes down before anything searched)")
    lk = sub.add_parser("lock", help="the lock file: decisions an explore run found and --accept kept")
    lk.add_argument("script", help="the board's layout script")
    how = lk.add_mutually_exclusive_group()
    how.add_argument("--release", nargs="+", metavar="ITEM", help="drop these items' entries")
    how.add_argument("--release-all", action="store_true", help="drop every entry")
    how.add_argument("--accept-seed", type=int, metavar="N",
                     help="write the saved explore's best variant, seed N, to the lock (what a stopped "
                          "explore's message offers); no search is run")
    how.add_argument("--current", action="store_true",
                    help="lock every searched item where the board stands (the last run's placement)")
    lk.add_argument("--partial", action="store_true",
                    help="with --current: lock the items that stand and list the rest (else nothing is locked "
                         "unless every one stands)")
    st = sub.add_parser("settings", help="every resolved setting, its value and the file it came from")
    st.add_argument("where", nargs="?", default=".", help="a layout script or a board directory (default: here)")
    st.add_argument("--json", action="store_true")

    ck = sub.add_parser("check", help="design checks from the parts' Pm.* facts: hot loops, switch nodes, keep-out, "
                                      "crossings under sense tracks, current path widths, junction temperature")
    ck.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    ck.add_argument("--ambient", type=float, default=None, help="board temperature in C (default: %g)" % 100.0)
    ck.add_argument("--keep-out", type=float, default=None, help="sense copper's distance from a switch node, mm")
    ck.add_argument("--rise", type=float, default=None, help="track temperature rise the widths are sized for, C")
    ck.add_argument("--limit", action="append", default=[], metavar="CHECK=VALUE",
                    help="a bound for a reporting check, e.g. hot-loop=20 (mm2) or switch-node=15 (mm2)")
    ck.add_argument("--json", action="store_true")

    fa = sub.add_parser("facts", help="the board's facts (stackup weight and roles, pair classes, via tiers, "
                                      "fab minimums) and whether they match the last confirmation")
    fa.add_argument("script", help="the board's layout script")
    fa.add_argument("--confirm", action="store_true",
                    help="record the printed facts' digest in the nearest placemat.toml's [facts.boards], keyed by this script")
    fa.add_argument("--json", action="store_true")

    # One way to ask for the report's form and place, whatever the command.
    for sp in sub.choices.values():
        sp.add_argument("--format", choices=("text", "json"), default=None,
                        help="the report as text (the default) or JSON; --json is the same as --format json")
        sp.add_argument("--output", metavar="FILE", default=None,
                        help="write the report to FILE instead of the terminal")
        if not any(a.dest == "json" for a in sp._actions):
            sp.set_defaults(json=False)
    return root


def overrides_from(args) -> dict:
    """The settings a command's flags set, and only those: a flag left off
    falls to placemat.toml, and a key absent from that falls to the default."""
    out = {}
    for flag, name in (("ambient", "check_ambient_c"), ("keep_out", "check_keep_out_mm"),
                       ("rise", "check_rise_c")):
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


def _script_of(p):
    """`p` when it is a layout script (so its [scripts.\"...\"] settings apply), else None."""
    p = Path(p)
    return p if p.is_file() and p.suffix == ".py" else None


def cmd_settings(args) -> int:
    from .settings import load, Settings, split_key
    from .project import find_board
    p = Path(args.where)
    start = p if p.is_dir() else find_board(p).board_dir
    s = load(start, script=_script_of(p))
    if args.json:
        console.data(json.dumps({k: {"value": _plain(getattr(s, k)), "source": s.source_of(k)}
                                 for k in Settings.keys()}, indent=2, sort_keys=True))
        return 0
    for name in Settings.keys():
        section, key = split_key(name)
        console.say("settings", "%-28s %-24s %s" % (
            "%s.%s" % (section, key), _show(getattr(s, name)), s.source_of(name)))
    return 0


def _explore_options(args):
    """The ExploreOptions --explore and its flags ask for, or None."""
    if getattr(args, "explore", None) is None:
        if any(getattr(args, k, None) for k in ("focus", "focus_after", "focus_box", "accept")):
            raise SystemExit("--focus, --focus-after, --focus-box and --accept go with --explore SECONDS")
        return None
    from .explore import ExploreOptions
    from .values import Box
    box = None
    if args.focus_box:
        try:
            x0, y0, x1, y1 = (float(v) for v in args.focus_box.split(","))
        except ValueError:
            raise SystemExit("--focus-box is X0,Y0,X1,Y1 in board millimetres, not %r" % args.focus_box)
        box = Box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return ExploreOptions(args.explore, tuple(args.focus), args.focus_after, box, args.jobs, args.accept)


def cmd_lock(args) -> int:
    from . import lock
    from pathlib import Path
    path = lock.path_for(Path(args.script).resolve())
    if getattr(args, "current", False):
        return _lock_current(Path(args.script), None, partial=args.partial)
    if args.partial:
        raise SystemExit("--partial goes with --current")
    if args.accept_seed is not None:
        from .explore import accept_best
        from .checkpoint import state_dir
        from .project import find_board
        from ._version import __version__
        script = Path(args.script).resolve()
        try:
            console.say("lock", accept_best(script, state_dir(find_board(script).board_dir, script), __version__,
                                            seed=args.accept_seed))
        except ValueError as e:
            console.say("lock", str(e), level="fail")
            return 1
        return 0
    if not args.release and not args.release_all:
        entries = lock.read(path)
        console.lines("lock", "\n".join("%s  %s %s  turn %d" % (e.key, "%s.%s" % e.anchor if e.anchor else "board",
                                                                  e.offset, e.turn) for e in entries)
                      or "%s: no entries" % path.name)
        return 0
    gone = lock.release(path, None if args.release_all else set(args.release))
    console.say("lock", "released %d: %s" % (len(gone), ", ".join(gone) or "-"))
    return 0


def _lock_where_it_stands(script: Path, keys, key_of=None, plan_out=None, partial: bool = False) -> tuple:
    """(lock entries, keys locked, {key: why not}, last run's id): `keys`
    (None: every searched item; `key_of(board)` gives them once the board
    is built) locked where the board stands, and checked by resolving once
    more with them: nothing is locked unless every one of them lands where
    the board has it. `partial`: those that would not are dropped and the
    rest checked again (a smaller lock can move what is searched after it),
    until what is left all lands there. A script that does not resolve is a
    ValueError."""
    from . import lock
    from ._version import __version__
    from .previewer import resolve_like_last_run, written_pads
    board, plan, src, run_id = resolve_like_last_run(script)
    if plan_out is not None:
        plan_out.append(plan)
    if key_of is not None:
        keys = key_of(board) & set(plan.turns)
    path = lock.path_for(script.resolve())
    written = written_pads(src.pcb)
    tol = board.settings.route_adopt_tolerance
    entries, locked, refused = lock.current(board, plan, written, lock.read(path), tol, keys=keys,
                                            release=__version__, run=run_id)
    while locked:
        board2, plan2, _, _ = resolve_like_last_run(script, lock_entries=entries)
        _, held, off = lock.current(board2, plan2, written, [], tol, keys=set(locked))
        moved = set(locked) - set(held)
        for key in sorted(moved):
            refused[key] = "locked, it would not come back there (%s)" % off.get(key, "not placed")
        if not moved:
            break
        if not partial:
            locked = []
            break
        # the refused seed the recomputation: what hangs off one is dropped with it, not its anchor re-locked
        entries, locked, refused = lock.current(board, plan, written, lock.read(path), tol, keys=set(locked) - moved,
                                                release=__version__, run=run_id, refused=refused)
    return entries, locked, refused, run_id


def _lock_current(script: Path, keys, partial: bool = False) -> int:
    """Lock `keys` (None: every searched item) where the board stands; 1 when
    any would not land there, and then nothing is locked - or, `partial`,
    the rest are."""
    from . import lock
    try:
        entries, locked, refused, run_id = _lock_where_it_stands(script, keys, partial=partial)
    except ValueError as e:
        console.say("lock", str(e), level="fail")
        return 1
    if refused and not partial:
        locked = []
    if locked:
        lock.write(lock.path_for(script.resolve()), entries)
    if partial:
        console.say("lock", "locked %d of %d where the board stands (run %s)%s" % (
            len(locked), len(locked) + len(refused), run_id,
            "" if not refused else "; %d would not stand there" % len(refused)))
    else:
        console.say("lock", "locked %d where the board stands (run %s)%s" % (
            len(locked), run_id, "" if not refused else "; nothing written: %d would not stand there" % len(refused)))
    for key, why in sorted(refused.items()):
        console.say("lock", "%s: %s; run the script, then lock" % (key, why), level="finding")
    return 1 if refused else 0


def cmd_freeze(args) -> int:
    from .freeze import FreezeError, freeze
    if not args.items and not args.all:
        raise SystemExit("name the entries to freeze, or --all")
    try:
        report = freeze(args.script, None if args.all else set(args.items), fixed=args.fixed)
    except FreezeError as e:
        console.say("freeze", str(e), level="fail")
        return 1
    for r in report["refused"]:
        console.say("freeze", "refused: " + r, level="finding")
    if report["differences"]:
        console.say("freeze", "not written: the frozen script would place differently", level="fail")
        console.lines("freeze", "\n".join("  " + d for d in report["differences"]))
        return 1
    console.say("freeze", "froze %d: %s" % (len(report["frozen"]), ", ".join(report["frozen"]) or "-"))
    return 0 if report["frozen"] or not report["refused"] else 1


def cmd_run(args) -> int:
    from .runner import run
    result = run(args.script, label=args.label, fresh=args.fresh, render=not args.no_render,
                 drc=not args.no_drc, quiet=args.quiet or args.json, verbose=args.verbose,
                 route=args.route, route_quick=not args.route_full, route_exclude=args.route_exclude,
                 keep_going=args.keep_going, overrides=overrides_from(args), reuse=not args.no_reuse,
                 explore=_explore_options(args))
    if args.json:
        console.data(json.dumps(json.loads((result.run_dir / "run.json").read_text()), indent=2))
    # a run that placed but came out worse than the best of its parts is a
    # failure too, so a regression cannot pass unnoticed in a loop
    return 0 if result.status == "ok" and not result.regressed else 1


def cmd_impact(args) -> int:
    from .report import RunRecord, impact
    before, after = RunRecord.load(_record(args.before, args.board)), RunRecord.load(_record(args.after, args.board))
    text = impact(before, after)
    if args.json:
        console.data(json.dumps({"before": {"run_id": before.run_id, "metrics": before.metrics},
                                 "after": {"run_id": after.run_id, "metrics": after.metrics},
                                 "lines": text.splitlines()}, indent=2, sort_keys=True, default=str))
        return 0
    console.lines("impact", text)
    return 0


def _runs_dirs(board) -> list:
    if board:
        return [Path(board) / ".placemat" / "runs"]
    here = Path.cwd()
    found = [d for d in [here / ".placemat/runs"] + sorted(here.glob("*/.placemat/runs")) if d.is_dir()]
    return found


def _record(ref, board=None) -> Path:
    """A run.json from a path, or a run id / prefix / label looked up in the
    runs directories under the cwd (or --board). A run whose process is gone
    while its record still says "running" is said to have died."""
    path = _find_record(ref, board)
    try:
        from .report import RunRecord, dead_note
        note = dead_note(RunRecord.load(path))
        if note:
            console.say("run", note, level="fail")
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return path


def _find_record(ref, board=None) -> Path:
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
    from .kicad.drc import run_drc, unconnected_items, violation_items
    from .report import airwires_from_drc
    from .pairs import board_pairs
    pcb = Path(args.pcb)
    with tempfile.TemporaryDirectory() as scratch:      # the report is read here and not kept: a rerun makes it again
        report = run_drc(pcb, Path(scratch) / "drc.json")
        data = json.loads((Path(scratch) / "drc.json").read_text())
    try:
        from .kicad.read import read_board
        snap = read_board(pcb)
        insts = {fp.ref: fp.inst for fp in snap.footprints}
        partners = board_pairs(snap.netclasses)
    except Exception:                               # a board pcbnew cannot read has no instances or classes
        insts, partners = {}, {}
    aw = airwires_from_drc(data, partners=partners)
    items = violation_items(data, {}, insts)
    if args.json:
        console.data(json.dumps({"by_type": report.by_type, "real": report.real, "outstanding": report.outstanding,
                                 "unconnected": report.unconnected, "open_nets": dict(report.open_nets),
                                 "airwires": aw, "violations": items, "unconnected_items": unconnected_items(data, insts)},
                                indent=2))
    else:
        console.say("drc", report.summary())
        real = [v for v in items if v["kind"] in report.real_kinds]
        for v in real[:20]:                     # the ones that fail the board, each where it is
            at = next((i["at"] for i in v["items"] if i["at"]), None)
            console.say("drc", "%s%s: %s; %s" % (v["kind"], " at (%.2f, %.2f)" % tuple(at) if at else "",
                                                 v["description"], "; ".join(
                                                     i["description"] + (" (%s)" % i["instance"] if "instance" in i else "")
                                                     for i in v["items"])))
        if len(real) > 20:
            console.say("drc", "... %d more with --json" % (len(real) - 20))
        console.say("drc", "airwires %d, %.1f mm, %d crossings" % (aw["count"], aw["total_mm"], aw["crossings"]))
        for net, mm in sorted(aw["per_net"].items(), key=lambda kv: -kv[1])[:10]:
            console.say("drc", "%-20s %6.1f mm  %d crossing(s)" % (net, mm, aw["crossings_per_net"].get(net, 0)))
    return 1 if report.real else 0


def cmd_route(args) -> int:
    from .kicad.route import route_board
    from .project import find_board
    p = Path(args.pcb)
    if getattr(args, "partial", False) and not (args.adopt or args.adopt_all):
        console.say("route", "--partial keeps an open net's islands when adopting: give --adopt NET ... or --adopt-all")
        return 2
    if (args.adopt or args.adopt_all) and p.suffix == ".kicad_pcb":
        console.say("route", "--adopt keeps copper beside a layout script: give the script, not the board")
        return 2
    from .settings import bind, load
    src = None if p.suffix == ".kicad_pcb" else find_board(p)
    pcb = p if src is None else src.pcb
    work = Path(args.out) if args.out else pcb.parent.parent.parent / ".placemat" / "route"
    cfg = load(src.board_dir if src is not None else pcb.parent, script=_script_of(p))       # the board's own [route] settings
    from .kicad.route import plane_nets_of
    planes = plane_nets_of(pcb)             # served by their pours, as run --route leaves them
    with bind(cfg):
        from .settings import active, parse_islands
        try:
            flag = parse_islands(args.islands)
        except ValueError as e:
            console.say("route", "--islands: %s" % e, level="fail")
            return 2
        islands = parse_islands(active().route_islands)
        islands.update({n: w for n, w in flag.items() if w is not None or n not in islands})   # a bare NET keeps its width
        report = route_board(pcb, work, exclude_nets=set(args.exclude) | planes, layers=args.layers,
                             quick=not args.full, iterations=args.iterations, islands=islands)
    if args.json:
        console.data(json.dumps(report.as_dict(), indent=2))
    else:
        console.say("route", report.summary())
        for breach in report.keepout_breaches:
            console.say("route", breach)
        for net, n in sorted(report.open_nets.items(), key=lambda kv: -kv[1])[:15]:
            console.say("route", "%-20s %d open" % (net, n))
        console.say("route", "routed board: %s" % report.routed_pcb)
    if args.adopt or args.adopt_all:
        with bind(cfg):
            _adopt(p, args.adopt if args.adopt else None, report, lock_items=not args.no_lock,
                   partial=getattr(args, "partial", False))
    return 0 if report.valid else 1


def _adopt(script: Path, nets, report, lock_items: bool = True, partial: bool = False) -> None:
    """Keep the route's copper on `nets` (None: every net it closed) and, by
    default, lock the searched items those nets join where the board stands,
    since kept copper is dropped when they move. A placement the next run
    would not reproduce adopts nothing."""
    from . import lock, routes
    from .kicad.read import read_board
    skipped, counts = {}, {}
    new = routes.adoptable(read_board(report.work / "in.kicad_pcb"), read_board(report.routed_pcb), nets,
                           report.open_nets, report.shorted, skipped, partial=partial, counts=counts)
    for net, why in skipped.items():
        console.say("adopt", "%s not adopted: %s" % (net, why))
    for net, tally in sorted(counts.items()):
        if tally["kept"]:
            console.say("adopt", routes.island_line(net, tally, report.open_nets.get(net, 0)))
    last = []                           # the resolve the lock makes: which kept entries held on the routed board
    if new and lock_items:
        try:
            entries, locked, refused, run_id = _lock_where_it_stands(
                script, None, key_of=lambda board: routes.items_of(new, board), plan_out=last)
        except ValueError as e:
            console.say("adopt", "nothing adopted: %s" % e, level="fail")
            return
        if refused:
            console.say("adopt", "nothing adopted: the placement the route was given is not the one the next "
                                 "run makes, and kept copper would be dropped", level="fail")
            for key, why in sorted(refused.items()):
                console.say("adopt", "  %s: %s" % (key, why), level="finding")
            console.say("adopt", "run the script, route again, then adopt")
            return
        if locked:
            lock.write(lock.path_for(script.resolve()), entries)
            console.say("adopt", "locked %d item(s) the kept nets join where the board stands" % len(locked))
    held = None
    old = routes.read(routes.path_for(script))
    if new and old:                     # a net's entries that did not hold are replaced; the ones that did stay
        if not last:
            try:
                from .previewer import resolve_like_last_run
                last.append(resolve_like_last_run(script)[1])
            except ValueError:
                pass
        if last:
            held = routes.held_of(old, last[0].adopted)
    for e in routes.replaced(old, new, held):
        console.say("adopt", "replaced a kept entry of %s (adopted %s) that did not hold" % (e.net, e.adopted or "-"))
    routes.keep(script, new, held)
    for e in new:
        console.say("adopt", routes.describe(e))
    console.say("adopt", "%d entr%s kept in %s" % (len(new), "y" if len(new) == 1 else "ies", routes.path_for(script)))


def cmd_routes(args) -> int:
    from . import routes
    script = Path(args.script)
    if args.release_all:
        gone = routes.read(routes.path_for(script))
        if gone:
            routes.release(script, [e.net for e in gone])
            console.say("routes", "released %d net(s)" % len({e.net for e in gone}))
    if args.release:
        missing = routes.release(script, args.release)
        for net in missing:
            console.say("routes", "%s was not adopted" % net)
        if missing:
            return 1
    entries = routes.read(routes.path_for(script))
    for e in entries:
        console.say("routes", routes.describe(e))
    if not entries:
        console.say("routes", "no adopted routes (%s)" % routes.path_for(script))
    return 0


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
                describe.part_lines(fp, pads=args.pads, digest=digest, envelope=getattr(args, "envelope", False))))
        return 0
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    if getattr(args, "outline", False):
        from .kicad.read import read_outline
        o = read_outline(pcb)
        if args.json:
            console.data(json.dumps({"outline": o}, indent=2))
        else:
            lines = ["%.3f x %.3f mm, %.2f mm thick, %d Edge.Cuts item(s)" % (o["width"], o["height"], o["thickness"],
                                                                            len(o["items"]))]
            if o["box"]:
                lines.append("box %.3f %.3f %.3f %.3f" % tuple(o["box"]))
            lines += ["%-8s %8.3f %8.3f -> %8.3f %8.3f%s" % (i["kind"], *i["start"], *i["end"],
                                                           "  r %.3f" % i["radius"] if "radius" in i else "")
                      for i in o["items"]]
            console.lines("measure", "\n".join(lines))
        return 0
    if getattr(args, "labels", False):
        from .kicad.read import read_labels, read_silk_graphics
        labels, graphics = read_labels(pcb), read_silk_graphics(pcb)
        if args.json:
            console.data(json.dumps({"labels": labels, "graphics": graphics}, indent=2))
        else:
            lines = ["%-20s %-5s %-12s %8.3f x %.3f  box %.3f %.3f %.3f %.3f  at %.3f %.3f  h %.2f stroke %.2f "
                     "angle %g%s" % (
                         l["text"][:20], l["face"], (l["cell"] or "-")[:12], l["box"][2] - l["box"][0],
                         l["box"][3] - l["box"][1], *l["box"], *l["at"], l["height"], l["stroke"], l["angle"],
                         " mirrored" if l["mirrored"] else "") for l in labels] or ["no labels on this board"]
            lines += ["%-20s %-5s %-12s box %.3f %.3f %.3f %.3f  stroke %.2f" % (
                "(" + g["kind"] + ")", g["face"], (g["cell"] or "-")[:12], *g["box"], g["stroke"]) for g in graphics]
            console.lines("measure", "\n".join(lines))
        return 0
    snap = read_board(pcb)
    if getattr(args, "keepouts", None) is not None:
        near = getattr(args, "near", 1.0)
        if args.json:
            console.data(json.dumps({"keepouts": describe.keepout_clearances(snap, args.keepouts, near)}, indent=2))
        else:
            console.lines("measure", "\n".join(describe.keepout_lines(snap, args.keepouts, near)))
        return 0
    if getattr(args, "copper", None) is not None:
        from .settings import load
        tol = load(find_board(p).board_dir if p.suffix != ".kicad_pcb" else pcb.parent, script=_script_of(p)).copper_straight_tolerance
        if args.json:
            console.data(json.dumps({"segments": describe.copper_segments(snap, args.copper, tol),
                                     "polygons": describe.copper_polygons(snap, args.copper)}, indent=2))
        else:
            console.lines("measure", "\n".join(describe.copper_lines(snap, args.copper, tol)))
        return 0
    try:                                            # pin names, when the board's source is beside it
        import dataclasses as _dc
        from .pins import board_pin_names
        src = find_board(p if p.suffix != ".kicad_pcb" else pcb.parent.parent)
        snap = _dc.replace(snap, pin_names=board_pin_names(src, pcb.parent))
    except (FileNotFoundError, ValueError, OSError):
        pass
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
        lines += describe.part_lines(fp, snap, pads=args.pads, envelope=getattr(args, "envelope", False))
        if getattr(args, "models", False):
            checked = describe.model_check(fp, pcb.parent)
            doc["model_checks"] = checked
            lines += ["  model check: %s" % n for n in checked] or (["  model check: ok"] if fp.models else [])
    if args.json:
        console.data(json.dumps({"parts": docs}, indent=2))
    else:
        console.lines("measure", "\n".join(lines))
    return 0


def cmd_parts(args) -> int:
    from . import describe
    from .kicad.read import read_board
    from .project import find_board
    from .settings import load
    p = Path(args.pcb)
    src = None if p.suffix == ".kicad_pcb" else find_board(p)
    pcb = p if src is None else src.pcb
    snap = read_board(pcb)
    cfg = load(src.board_dir if src is not None else pcb.parent, script=_script_of(p))
    warnings = describe.order_warnings(snap, cfg.parts_order_fields)
    fragments = None
    if getattr(args, "fragments", False):
        log = pcb.parent / "layout.log"
        if not log.exists():
            console.say("parts", "no layout.log beside %s to read the fragments from" % pcb, level="fail")
            return 2
        fragments = describe.fragment_sources(log)
    if args.json:
        rows = describe.parts_rows(snap, getattr(args, "field", ()))
        if fragments is not None:
            for r in rows:
                r["fragment"] = fragments.get(r["instance"])
        console.data(json.dumps({"parts": rows, "totals": describe.board_totals(snap), "warnings": warnings},
                                indent=2))
        return 0
    console.lines("parts", "\n".join(describe.parts_lines(snap, getattr(args, "field", ()), fragments)))
    for w in warnings:
        console.say("parts", w, level="finding")
    return 0


def cmd_nets(args) -> int:
    from . import nets
    from .kicad.read import read_board
    from .kicad.route import plane_nets_of
    from .project import find_board
    p = Path(args.pcb)
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    snap = read_board(pcb)
    rows = nets.nets_rows(snap, plane_nets_of(pcb), inst=args.inst)
    if args.net:
        wanted = set(args.net)
        rows = [r for r in rows if r["net"] in wanted]
    try:
        rows = nets.sort_rows(rows, args.sort or "span")
    except ValueError as e:
        console.say("nets", str(e), level="fail")
        return 2
    if args.json:
        console.data(json.dumps({"nets": rows}, indent=2))
        return 0
    console.lines("nets", "\n".join(nets.nets_lines(rows)))
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
            with tempfile.TemporaryDirectory() as scratch:      # the render is only read, never kept
                runs = runs + pdf.ocr_runs(path, n, scratch, args.dpi)
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
    from .pdf import read as pdf
    if len(args.rest) != 2:
        console.say("datasheet", "check takes a datasheet and a footprint: "
                                 "placemat datasheet check <pdf> <footprint.kicad_mod>")
        return 1
    from .kicad.read import read_footprint        # after the usage check: that needs no KiCad
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
    if (args.png or args.out) and not args.show:
        console.say("datasheet", "--png and --out render the page --show names: add --show p<N> or a topic")
        return 1
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
        png = None
        if args.png or args.out:
            from .project import datasheet_root, note_views, views_dir
            if args.out and Path(args.out).suffix.lower() == ".png":
                out = Path(args.out)
                png = pdf.render(path, page, out.parent, args.dpi, name=out.name)
                note_views(png.parent)
            else:
                out_dir = Path(args.out) if args.out else views_dir(datasheet_root(path), "datasheet")
                png = pdf.render(path, page, out_dir, args.dpi)
                note_views(out_dir)
        runs, _ = by_page[page]
        if args.json:
            doc = {"page": page, "text": [r.text for r in runs]}
            if png is not None:
                doc["png"] = str(png)
            console.data(json.dumps(doc, indent=2))
            return 0
        console.say("datasheet", "page %d" % page if png is None else "page %d rendered to %s" % (page, png))
        for r in runs:
            console.say("datasheet", "  %-6.0f %-6.0f %s" % (r.box.left, r.box.top, r.text.strip()))
        if not runs:
            console.say("datasheet", "no text on this page (outlined curves)")
            if not pdf.have_ocr():
                console.say("datasheet", "tesseract is not installed: a page whose dimensions are "
                                         "outlined curves has no text to read")
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


def cmd_preview(args) -> int:
    from .previewer import preview
    from .runner import RunFailure
    from .values import Box
    region = None
    if args.zoom:
        try:
            x0, y0, x1, y1 = (float(v) for v in args.zoom.split(","))
        except ValueError:
            console.say("preview", "--zoom is X0,Y0,X1,Y1 in board millimetres, not %r" % args.zoom, level="fail")
            return 2
        region = Box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    faces = ("front", "back") if args.face == "both" else (args.face,)
    try:
        result = preview(args.script, faces=faces, svg_only=args.svg, out=args.out, heat=not args.no_heat,
                         links=not args.no_links, copper=not args.no_copper, region=region, around=args.around,
                         margin=args.margin, explore=_explore_options(args), tags=not args.no_tags)
    except RunFailure as e:
        console.say("fail", "%s: %s" % (e, e.details.get("error", "")), level="fail")
        return 1
    except ValueError as e:
        console.say("preview", str(e), level="fail")
        return 2
    from .preview import note_lines
    plan = result.plan
    placed = sum(1 for s in plan.steps if s.placement is not None)
    if args.json:
        console.data(json.dumps({
            "svg": str(result.svg), "png": str(result.png) if result.png else None,
            "png_problem": result.png_problem or None, "placed": placed,
            "findings": plan.findings,
            "finding_details": [{"kind": f.kind, "severity": f.severity, "text": str(f)} for f in plan.findings],
            "reused": result.reused or None,
            "congestion": None if plan.rudy is None else {"worst": plan.rudy.worst,
                                                          "at": [plan.rudy.worst_at.x, plan.rudy.worst_at.y]},
            "seen_px_per_mm": round(result.seen_px_per_mm, 1) if result.model_edge else None,
            "notes": [{"tag": n.tag, "kind": n.kind, "in_view": n.at is not None,
                       "at": None if n.at is None else [round(n.at.x, 3), round(n.at.y, 3)], "text": n.text}
                      for n in result.notes]}, indent=2))
        return 0
    from .findings import summary
    console.say("script", "%d placed, %d finding(s)%s" % (
        placed, len(plan.findings), " (%s)" % summary(plan.findings) if plan.findings else ""))
    if result.reused:
        console.say("reused", result.reused[len("reused "):])
    if plan.rudy is not None:
        console.say("congestion", "worst cell %.2f of capacity at (%.1f, %.1f)" % (
            plan.rudy.worst, plan.rudy.worst_at.x, plan.rudy.worst_at.y))
    for f in plan.findings.most_serious_first():
        console.finding(f)
    for line in note_lines(result.notes):
        console.say("tag", line)
    console.say("preview", "svg %s" % result.svg)
    if result.png is not None:
        console.say("preview", "png %s" % result.png)
        if result.model_edge:
            console.say("preview", "a model that scales images to a %d px long edge ([preview] model_edge, an "
                        "assumption) sees about %.0f px per mm%s" % (
                            result.model_edge, result.seen_px_per_mm, "" if result.seen_px_per_mm >= 20 else
                            ": too coarse for small passives and their gaps - look closer with --around or --zoom"))
    elif not args.svg:
        console.say("preview", "no png: %s" % result.png_problem)
    return 0


def cmd_studio(args) -> int:
    from .studio import run
    return run(args.script, port=args.port, open_browser=False if args.no_open else None, host=args.host)


def cmd_occupancy(args) -> int:
    from . import queries
    from .kicad.read import read_board
    from .project import find_board
    from .settings import active, bind, load
    from .values import Box, CopperLayer, Location
    p = Path(args.pcb)
    src = None if p.suffix == ".kicad_pcb" else find_board(p)
    pcb = p if src is None else src.pcb
    with bind(load(src.board_dir if src is not None else pcb.parent, script=_script_of(p))):
        g = read_board(pcb)
        adopt_tolerance = active().route_adopt_tolerance

    def via_rules(net):
        nc = g.netclasses.get(net)
        size = args.size or (nc.via_diameter if nc else 0.6)
        drill = args.drill or (nc.via_drill if nc else 0.3)
        width = nc.track_width if nc else 0.2
        return size, drill, width

    def find_pad(spec):
        part, _, number = spec.rpartition(".")
        fp = g.footprint(part)
        pads = [q for q in fp.pads if q.number == number]
        if not pads:
            console.say("occupancy", "%s has no pad %r; its pads are %s" % (
                fp.inst, number, ", ".join(sorted({q.number for q in fp.pads}))))
            return None
        return fp, pads[0]

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
    if args.corridor:
        if not args.layer or not args.width:
            console.say("occupancy", "--corridor needs --layer and --width", level="fail")
            return 2
        if args.ignore_kept and p.suffix == ".kicad_pcb":
            console.say("occupancy", "--ignore-kept reads a script's kept routes: give the script, not the board",
                        level="fail")
            return 2
        found_a, found_b = find_pad(args.corridor[0]), find_pad(args.corridor[1])
        if found_a is None or found_b is None:
            return 1
        (fp_a, pad_a), (fp_b, pad_b) = found_a, found_b
        net = args.net if args.net is not None else pad_a.net
        layer = CopperLayer.of(args.layer)
        geometry = g
        if args.ignore_kept:
            from . import routes
            geometry = routes.without_kept(g, routes.read(routes.path_for(p)), adopt_tolerance)
        result = queries.corridor(geometry, pad_a.box.center, pad_b.box.center, net, args.width, layer,
                                  margin=args.margin)
        if args.json:
            console.data(json.dumps({
                "a": "%s.%s" % (fp_a.inst, pad_a.number), "b": "%s.%s" % (fp_b.inst, pad_b.number),
                "layer": layer.value, "width": args.width, "net": net,
                "paths": [{"points": [list(pt) for pt in cp.points], "length": cp.length, "turns": cp.turns}
                         for cp in result.paths],
                "blockers": list(result.blockers)}, indent=2))
        else:
            console.lines("occupancy", "\n".join(queries.corridor_lines(
                result, "%s.%s" % (fp_a.inst, pad_a.number), "%s.%s" % (fp_b.inst, pad_b.number),
                net, args.width, layer)))
        return 0 if result.paths else 1
    found = find_pad(args.via_near)
    if found is None:
        return 1
    fp, pad = found
    pads = [q for q in fp.pads if q.number == pad.number]
    net = args.net if args.net is not None else pad.net
    size, drill, width = via_rules(net)
    width = queries.tail_width(width, [o for q in pads for o in q.outlines])
    layer = CopperLayer.of(args.layer) if args.layer else queries._ordered(pad.layers or g.layers)[0]
    source = () if args.in_pad else queries.pad_copper(fp, pad.number)
    spot, tally, tried = queries.free_spot(pad.box.center, queries.via_judge(g, pad.box.center, net, size, drill,
                                                                              width, layer, source),
                                           args.radius, args.step)
    if args.json:
        console.data(json.dumps({"spot": None if spot is None else {
            "at": [spot.at.x, spot.at.y], "distance": spot.distance, "soft": list(spot.soft)},
            "tally": dict(tally), "tried": tried, "net": net, "size": size, "drill": drill,
            "layer": layer.value, "tail_width": width}, indent=2))
    else:
        console.lines("occupancy", "\n".join(queries.spot_lines(spot, tally, tried, net,
                                                                  "%s.%s" % (fp.inst, pad.number),
                                                                  tail=None if args.in_pad else (width, layer))))
    return 0 if spot is not None else 1


def cmd_layer(args) -> int:
    from .layerview import layer_crossings, layer_svg, read_layer
    from .project import board_dir_of, find_board, note_views, views_dir
    p = Path(args.pcb)
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    try:
        items = read_layer(pcb, args.layer)
    except ValueError as e:
        console.say("layer", str(e), level="fail")
        return 2
    out = Path(args.out) if args.out else (views_dir(board_dir_of(pcb), "layer")
                                           / ("layer-%s.svg" % args.layer.replace(".", "_")))
    out.parent.mkdir(parents=True, exist_ok=True)
    note_views(out.parent)
    out.write_text(layer_svg(items, args.layer))
    crossings = layer_crossings(items)
    nets = sorted({z["net"] for z in items["zones"] if z["net"]})
    if args.json:
        console.data(json.dumps({"svg": str(out), "zone_nets": nets,
                                 "polygons": len(items["polygons"]), "crossings": crossings}, indent=2))
        return 0
    console.say("layer", "%s: %d zone(s) (%s), %d track(s), %d via(s)%s; %s" % (
        args.layer, len(items["zones"]), ", ".join(nets) or "none", len(items["tracks"]), len(items["vias"]),
        ", %d polygon(s)" % len(items["polygons"]) if items["polygons"] else "", out))
    for c in crossings:
        console.say("layer", "%s track (%.2f, %.2f)-(%.2f, %.2f) runs inside %s's zone outline" % (
            c["track_net"], *c["start"], *c["end"], c["zone_net"]), level="finding")
    return 0


def cmd_show(args) -> int:
    from .kicad.read import read_board
    from .kicad.write import show_item
    from .project import board_dir_of, find_board, note_views, views_dir
    p = Path(args.pcb)
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    snap = read_board(pcb)
    name = args.item
    doc = {}
    if name in snap.cells:
        c = snap.cell(name)
        doc = {"kind": "cell", "name": name, "size": [round(c.box.width, 3), round(c.box.height, 3)],
               "members": len(c.members), "faces": dict(sorted(c.faces.items()))}
        fps = list(c.members)
    else:
        fp = snap.footprint(name)
        doc = {"kind": "part", "name": fp.inst, "ref": fp.ref,
               "size": [round(fp.body_box.width, 3), round(fp.body_box.height, 3)],
               "face": fp.face.value, "rotation": fp.rotation}
        fps = [fp]
        name = fp.ref
    ref_box = snap.cell(name).box if name in snap.cells else fps[0].body_box
    doc["footprints"] = []
    for fp in fps:
        pads = []
        for pad in fp.pads:
            side = ("N" if pad.location.y < ref_box.center.y - 0.01 else "S" if pad.location.y > ref_box.center.y + 0.01 else "") + \
                   ("W" if pad.location.x < ref_box.center.x - 0.01 else "E" if pad.location.x > ref_box.center.x + 0.01 else "")
            pads.append({"number": pad.number, "net": pad.net, "side": side})
        doc["footprints"].append({"ref": fp.ref, "instance": fp.inst,
                                  "from_centre": [round(fp.location.x - ref_box.center.x, 3),
                                                  round(fp.location.y - ref_box.center.y, 3)],
                                  "rotation": fp.rotation, "face": fp.face.value, "pads": pads})
    out = Path(args.out) if args.out else views_dir(board_dir_of(pcb), "show")
    note_views(out)
    doc["renders"] = [str(png) for png in show_item(pcb, name, out)]
    if args.json:
        console.data(json.dumps(doc, indent=2))
        return 0
    if doc["kind"] == "cell":
        console.say("show", "cell %s  %.2f x %.2f mm  %d members  faces: %s" % (
            doc["name"], doc["size"][0], doc["size"][1], doc["members"],
            ", ".join("%s=%s" % kv for kv in doc["faces"].items()) or "none declared (edge placement assumes local +Y outward)"))
    else:
        console.say("show", "part %s (%s)  %.2f x %.2f mm  face %s  rotation %g" % (
            doc["name"], doc["ref"], doc["size"][0], doc["size"][1], doc["face"], doc["rotation"]))
    for f in doc["footprints"]:
        console.say("show", "  %-6s %-24s at (%+.2f, %+.2f) from the %s centre, rot %g, %s" % (
            f["ref"], f["instance"], f["from_centre"][0], f["from_centre"][1], doc["kind"], f["rotation"], f["face"]))
        for pad in f["pads"]:
            console.say("show", "      pad %-4s %-20s %s of centre" % (pad["number"], pad["net"] or "-", pad["side"] or "at the"))
    for png in doc["renders"]:
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
    result = write_faces(args.fragment, faces)
    if args.json:
        console.data(json.dumps({"fragment": str(args.fragment), "faces": faces, "result": result}, indent=2))
        return 0
    console.say("faces", "%s: %s" % (args.fragment, result))
    return 0


def cmd_check(args) -> int:
    from . import checks
    from .kicad import read
    from .project import find_board
    from .settings import bind, load
    p = Path(args.pcb)
    src = None if p.suffix == ".kicad_pcb" else find_board(p)
    pcb = p if src is None else src.pcb
    cfg = load(src.board_dir if src is not None else pcb.parent, overrides=overrides_from(args), script=_script_of(p))
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


def cmd_facts(args) -> int:
    from . import facts as facts_mod
    from .project import fab_profile, find_board
    from .runner import cached_generation, scripted_board
    from .settings import bind, load
    script = Path(args.script).resolve()
    src = find_board(script)
    cfg = load(src.board_dir, script=script)
    fab = fab_profile(src.board_dir)
    # the board as generated, as `run` reads it: the written layout carries the last run's own rule areas
    generated = cached_generation(src) / src.pcb.name
    with bind(cfg):
        board = scripted_board(script, src, cfg, fab, keep_going=True,
                               pcb=generated if generated.exists() else None)
    geometry = board.geometry
    plane_layers = frozenset(l for l, _nets in board._plane_layers().items())
    doc = facts_mod.facts_of(geometry, fab, cfg.check_rise_c, plane_layers)
    reasons = facts_mod.unconfirmed_reasons(doc, facts_mod.confirmed_digest(cfg, script))
    if args.confirm:
        # the placemat.toml the run uses: the nearest one up from the board, never a new one beside a
        # script when an ancestor has one (it would cut a module off from the board's shared helpers)
        from .settings import _files
        found = _files(src.board_dir)
        toml = found[-1] if found else src.board_dir / "placemat.toml"
        facts_mod.write_confirmed(toml, doc.digest(), key=facts_mod.script_key(script, toml))
        console.say("facts", "confirmed: %s" % doc.digest())
        return 0
    if args.json:
        console.data(json.dumps({"layers": doc.layers, "pairs": doc.pairs, "via_types": doc.via_types,
                                 "fab_min": doc.fab_min, "rise_c": doc.rise_c,
                                 "plane_mismatches": list(doc.plane_mismatches), "unconfirmed": reasons}, indent=2))
        return 0
    for line in facts_mod.render(doc, reasons):
        console.say("facts", line)
    return 1 if reasons else 0


# The commands that can run for minutes: a stop (SIGTERM, SIGHUP, Ctrl-C) ends them with a line saying
# so and the exit status 128 + the signal, keeping what they had done.
STOPPABLE = ("run", "preview", "route")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.format == "json":
        args.json = True
    previous = stop.install() if args.command in STOPPABLE else {}
    try:
        return _main(args)
    except stop.Stopped as s:
        if not s.said:
            stop.say("%s stopped by %s%s" % (args.command, s.name, " during %s" % s.stage if s.stage else ""))
        return s.exit_code
    finally:
        stop.restore(previous)


def _main(args) -> int:
    if args.output is None:
        return _dispatch(args)
    with open(args.output, "w") as stream:
        previous, colour = console._stream, console.colour
        console._stream, console.colour = stream, False
        try:
            return _dispatch(args)
        finally:
            console._stream, console.colour = previous, colour


def _dispatch(args) -> int:
    return {"run": cmd_run, "lock": cmd_lock, "freeze": cmd_freeze, "impact": cmd_impact, "drc": cmd_drc, "measure": cmd_measure,
            "route": cmd_route, "routes": cmd_routes, "check": cmd_check, "show": cmd_show, "layer": cmd_layer, "faces": cmd_faces,
            "settings": cmd_settings, "parts": cmd_parts, "nets": cmd_nets, "facts": cmd_facts,
            "datasheet": cmd_datasheet, "occupancy": cmd_occupancy, "preview": cmd_preview,
            "studio": cmd_studio}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
