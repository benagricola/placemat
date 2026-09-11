#!/usr/bin/env python3
"""`placemat` - one command for the whole loop.

One entry point, versioned with the library that answers it, so a command
written down in a skill or a project's rules names something real.

    placemat status                   what is here, and what is unfinished
    placemat init                     prepare a directory to be laid out in
    placemat new-board <Name>         write a layout script to fill in
    placemat round <board>            place it and check it - the everyday one

Everything after that checks ONE thing about a board that has already been
placed, for when `round` reports a number you want to look into. They take a
board by name - `placemat airwires middleweight` - or a path to any KiCad
board file, including a single cell's.

Everything needs `pcbnew`, which ships with system KiCad and is not on PyPI, so
placemat has to run inside a venv that inherits the system interpreter's
packages. `placemat init` checks that first and says exactly how to fix it,
because it is the one environment mistake whose downstream errors explain
nothing.
"""
import argparse
import glob
import importlib
import os
import shutil
import sys

# name -> module under placemat.tools, with the one-line help the CLI prints
GATES = {
    "round": ("round", "place a board and check it: generate, run its script, run every check"),
    "run": ("layout", "run a board's layout script by itself, without the checks"),
    "lint": ("layout_lint", "does a layout script match the current standard?"),
    "airwires": ("airwires", "what is still unconnected, as a number"),
    "occupancy": ("board_occupancy", "parts overlapping, on one face or through the board"),
    "review": ("board_review", "envelope, connector edges, tall parts, parts left at the origin"),
    "clearance": ("module_clearance", "the smallest copper gap, against what this board requires"),
    "courtyards": ("courtyard_sweep", "how close any two parts are, all pairs"),
    "courtyard-audit": ("courtyard_audit", "check or regenerate the keepout around each footprint"),
    "escape": ("escape_check", "can a pad's net get out, by any path a track could take?"),
    "polys": ("poly_audit", "every copper pour: net, layer, area, narrowest point"),
    "modules": ("module_audit", "check every cell against the rules that can be measured"),
    "stale": ("stale_check", "was this board placed against the cells as they are now?"),
    "contract": ("stamp_contract", "does the board give its cells what they assume?"),
    "datasheets": ("datasheets", "fetch the missing datasheet for every part"),
    "trial": ("route_trial", "how much of this board a router can actually connect"),
    # PASS-THROUGH: the router owns these arguments, so placemat forwards them
    # rather than declaring a parser for flags it does not define.
    "trial-round": ("route_one_round", "a shorter routing trial, for iterating", "raw"),
}


# KiCad's own asserts, printed by the C++ library when pcbnew loads. They say
# nothing about this project or this command, and three lines of them before
# every answer trains a reader to skip the output that matters.
_NOISE = ("assert \"m_choices.GetCount() > 0\"", "Debug: Adding duplicate image handler",
          "PCB_VIA::GetWidth called without a layer argument")


def quiet_pcbnew():
    """Import pcbnew with the library's own startup noise held back.

    Held back, not discarded: anything it prints that is NOT the known noise is
    passed through, so a real failure to load still reaches the terminal.
    """
    import os as _os
    r, w = _os.pipe()
    saved = _os.dup(2)
    try:
        _os.dup2(w, 2)
        import pcbnew                                          # noqa: F401
    finally:
        _os.dup2(saved, 2)
        _os.close(saved)
        _os.close(w)
        out = _os.read(r, 1 << 20).decode("utf-8", "replace")
        _os.close(r)
    for line in out.splitlines():
        if line.strip() and not any(n in line for n in _NOISE):
            sys.stderr.write(line + "\n")


def _use_project(where="."):
    """Resolve the project once, here, for whatever runs next.

    Every command needs it - a gate reads the fab profile, `status` reads the
    boards, a pass reads both - and resolving it per command is how they end up
    disagreeing. It comes from the DIRECTORY THE COMMAND WAS RUN IN, never from
    where placemat itself is installed.
    """
    from placemat import project as _project
    return _project.use(_project.Project.discover(start=os.path.abspath(where), quiet=True))


def _pcbnew_or_explain():
    """pcbnew is the whole toolchain's floor. Fail with the remedy, not a traceback."""
    try:
        quiet_pcbnew()
        return True
    except ImportError:
        sys.stderr.write(
            "placemat: cannot import pcbnew.\n\n"
            "It ships with system KiCad and is not installable from PyPI, so placemat\n"
            "has to run in a venv that inherits the system interpreter's packages:\n\n"
            '    uv venv --python "$(which python3)" --system-site-packages\n'
            "    uv sync\n"
            "    uv run placemat ...\n\n"
            "An isolated environment (`uv tool install`, `uvx`) cannot see pcbnew.\n")
        return False


def cmd_init(args):
    """Prepare a directory to be laid out in. Writes project data, never code."""
    if not _pcbnew_or_explain():
        return 2
    import pcbnew
    root = os.path.abspath(args.dir)
    print("placemat: pcbnew %s" % pcbnew.GetBuildVersion())
    made = []
    for d in ("modules", "parts"):
        p = os.path.join(root, d)
        if not os.path.isdir(p):
            os.makedirs(p); made.append(d + "/")
    fab = os.path.join(root, "fab-profile.json")
    if not os.path.exists(fab):
        shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "templates", "fab-profile.json"), fab)
        made.append("fab-profile.json")
        print("placemat: wrote a TEMPLATE fab profile. Its numbers are not your fab's -\n"
              "          edit it before laying anything out.")
    print("placemat: %s" % (", ".join(made) if made else "nothing to do, already set up"))
    if not os.path.exists(os.path.join(root, "pcb.toml")):
        print("placemat: no pcb.toml here - a project usually has one at its root")
    return 0


def cmd_status(args):
    """What this project holds, and what is not finished.

    The question an agent asks when it is pointed at a directory and told to
    get on with something. Globbing for it by hand gets a different answer per
    agent; this is one answer, from the same code that resolves a project.
    """
    root = os.path.abspath(args.dir)
    proj = _use_project(root)
    if proj.root is None:
        print("placemat: no pcb.toml at or above %s - not a project yet." % root)
        print("placemat: `placemat init` prepares one.")
        return 1

    print("project %s" % proj.root)
    print("  fab profile %s" % ("present" if proj._fab else "MISSING - via sizes and "
                                "clearances would be somebody else's"))
    from placemat.project import DEFAULT_BOARDS, DEFAULT_CELLS
    if proj.boards != DEFAULT_BOARDS or proj.cells != DEFAULT_CELLS:
        print("  looking in   boards %s   cells %s   (pcb.toml [placemat])"
              % (list(proj.boards), list(proj.cells)))

    boards, cells = [], []
    for d in proj.board_dirs:
        name = os.path.basename(d)
        zens = [f for f in sorted(os.listdir(d)) if f.endswith(".zen")]
        script = [f for f in sorted(os.listdir(d)) if f.endswith("_layout.py")]
        placed = bool(glob.glob(os.path.join(d, "layout", "*", "layout.kicad_pcb")))
        boards.append((name, bool(zens), bool(script), placed))
    for name, d in sorted(proj.module_dirs.items()):
        script = os.path.exists(os.path.join(d, "%s_layout.py" % name))
        frag = os.path.exists(os.path.join(d, "layout", "layout.kicad_pcb"))
        cells.append((name, script, frag))

    def mark(ok):
        return "yes" if ok else "NO"

    if boards:
        print("\n  boards")
        for name, zen, script, placed in boards:
            print("    %-22s captured %-3s  script %-3s  placed %s"
                  % (name, mark(zen), mark(script), mark(placed)))
    if cells:
        print("\n  cells")
        for name, script, frag in cells:
            print("    %-22s script %-3s  fragment %s" % (name, mark(script), mark(frag)))

    todo = []
    todo += ["%s has no layout script" % n for n, z, s, _p in boards if z and not s]
    todo += ["%s has a script but was never placed" % n for n, _z, s, p in boards if s and not p]
    todo += ["cell %s has no layout script" % n for n, s, _f in cells if not s]
    todo += ["cell %s has no fragment" % n for n, s, f in cells if s and not f]
    print("\n  unfinished (%d)" % len(todo))
    for line in todo:
        print("    - %s" % line)
    if not todo:
        print("    nothing: every board has a script and a placed layout")
    return 0


def cmd_new_board(args):
    """Write a board layout script from the scaffold that matches THIS version."""
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "templates", "scaffold_layout.py")
    dst = args.out or os.path.join(os.path.abspath(args.dir or "."),
                                   "%s_layout.py" % args.name)
    if os.path.exists(dst) and not args.force:
        sys.stderr.write("placemat: %s exists (use --force)\n" % dst)
        return 1
    shutil.copy(src, dst)
    print("placemat: wrote %s" % dst)
    print("placemat: fill in CONFIG, then the stage bodies. Nothing runs at import.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        quiet_pcbnew()          # before anything imports it noisily
    except ImportError:
        pass
    ap = argparse.ArgumentParser(
        prog="placemat", description=__doc__.split("Everything needs")[0].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="checks, once a board is placed:\n" + "\n".join("  %-16s %s" % (k, v[1]) for k, v in GATES.items()))
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("status", help="what is here, and what is unfinished")
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("init", help="prepare a directory to be laid out in")
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("new-board", help="write a layout script from the scaffold")
    p.add_argument("name")
    p.add_argument("--dir")
    p.add_argument("--out")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_new_board)

    for name, entry in GATES.items():
        mod, help_ = entry[0], entry[1]
        sub.add_parser(name, help=help_, add_help=False)

    if not argv or argv[0] in ("-h", "--help"):
        ap.print_help()
        return 0
    if argv[0] in GATES:
        # THE COMMAND'S OWN PARSER PARSES IT. placemat is one tool: the command
        # line is composed from the pieces each command declares, and argparse
        # decides what is an option's value and what is a board. Scanning argv
        # here instead means guessing both.
        if not _pcbnew_or_explain():
            return 2
        _use_project()
        if len(GATES[argv[0]]) > 2 and GATES[argv[0]][2] == "raw":
            import runpy
            sys.argv = ["placemat " + argv[0]] + argv[1:]
            try:
                runpy.run_module("placemat.tools." + GATES[argv[0]][0], run_name="__main__")
            except SystemExit as e:
                if e.code is None or isinstance(e.code, int):
                    return e.code or 0
                sys.stderr.write(str(e.code).rstrip() + chr(10))
                return 1
            return 0
        mod = importlib.import_module("placemat.tools." + GATES[argv[0]][0])
        ap = mod.parser()
        ap.prog = "placemat " + argv[0]
        try:
            ns = ap.parse_args(argv[1:])
            entry = getattr(mod, "cli", None) or getattr(mod, "main")
            return entry(ns) or 0
        except SystemExit as e:
            if e.code is None or isinstance(e.code, int):
                return e.code or 0
            sys.stderr.write(str(e.code).rstrip() + chr(10))
            return 1
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 1
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
