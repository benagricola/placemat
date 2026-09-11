#!/usr/bin/env python3
"""Run a board's layout script. The environment is this tool's job, not the script's.

A layout script carries no environment: no bytecode switch, no sys.path
arithmetic, no board path off sys.argv, no stackup patch, no
construction. That is ceremony an author would have to get right before
thinking about a single pad, and copied into every script it is a fix that
reaches whichever ones someone remembers.

    placemat run <board>
    placemat run <board> --board-file <a generated board to mutate>
    placemat run <board> --no-save     # run the stages, write nothing

The script contributes config and stage bodies (see modules/layout_stage.py);
this resolves the board, prepares the interpreter, builds the context from the
config, runs the stages in dependency order and saves.

CONFIG IS READ BEFORE THE CONTEXT EXISTS, which is why it stays module-level
constants rather than a stage: neither can be built until the frame size
and the plane nets are known. That ordering is this tool's to know - an author
who has to remember it is an author who can get it wrong.
"""
import argparse
import importlib.util
import os
import sys

def _root():
    """The project's root. Asked for, never computed from this file's own path."""
    from placemat.project import active
    return active().root or os.getcwd()




def load(script_path):
    """Import a layout script with modules/ importable and no bytecode written."""
    sys.dont_write_bytecode = True                      # no __pycache__ beside the sources
    # A PROJECT'S OWN SHARED CODE is importable from its layout scripts: a
    # board may keep helpers beside its cells, and a project that has not moved
    # onto placemat keeps its library there too.
    mods = os.path.join(_root(), "modules")
    if os.path.isdir(mods) and mods not in sys.path:
        sys.path.insert(0, mods)
    spec = importlib.util.spec_from_file_location("board_script", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["board_script"] = mod
    spec.loader.exec_module(mod)                        # registers the stage bodies
    return mod


def find(board):
    """(script path, default board file) for a board named by dir, zen or script."""
    name = os.path.basename(board.rstrip("/"))
    d = board if os.path.isdir(board) else os.path.join(_root(), name)
    if not os.path.isdir(d):
        d = os.path.dirname(os.path.abspath(board))
    if board.endswith("_layout.py"):
        scripts = [os.path.basename(board)]
    else:
        scripts = [f for f in sorted(os.listdir(d)) if f.endswith("_layout.py")]
        if len(scripts) > 1:
            # a directory may hold more than one board (a daughter, a variant):
            # take the script whose stem IS the directory, as round.py does
            def norm(s):
                return "".join(c for c in s.lower() if c.isalnum())
            exact = [f for f in scripts if norm(f[:-len("_layout.py")]) == norm(os.path.basename(d))]
            scripts = exact or scripts
        if len(scripts) != 1:
            raise SystemExit("cannot pick the layout script in %s (candidates: %s); "
                             "name one explicitly" % (d, scripts))
    script = os.path.join(d, scripts[0])
    stem = scripts[0][:-len("_layout.py")]
    return script, os.path.join(d, "layout", stem, "layout.kicad_pcb")


def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("board", help="board name, directory, .zen or _layout.py")
    ap.add_argument("--board-file", help="the generated board to mutate (default: the board's own)")
    ap.add_argument("--no-save", action="store_true", help="run the stages, write nothing")
    ap.add_argument("--quiet", action="store_true")
    return ap


def main(argv=None):
    a = argv if hasattr(argv, "board") else parser().parse_args(argv)

    # THE PROJECT FIRST. Everything below asks it where things are - which
    # board, which script, whose modules are importable - so resolving it
    # afterwards means those questions were answered by a fallback.
    from placemat import project
    project.use(project.Project.discover(start=os.getcwd()))

    script, default_board = find(a.board)
    board_file = a.board_file or default_board
    if not os.path.exists(board_file):
        raise SystemExit("no generated board at %s - run `pcb layout` into a clean dir first" % board_file)

    mod = load(script)
    from placemat import layout_stage

    cfg = {}
    for key, arg in (("BOARD_W", "width"), ("BOARD_H", "height"), ("PLANE_NETS", "plane_nets")):
        if hasattr(mod, key):
            cfg[arg] = getattr(mod, key)
    missing = {"width", "height"} - set(cfg)
    if missing:
        raise SystemExit("%s declares no %s" % (script, ", ".join(sorted(missing))))
    cfg.setdefault("plane_nets", ())
    # anything else BoardLayout takes that this board declares
    for key, arg in (("REDROP_KEEPOUT", "redrop_keepout"),):
        if hasattr(mod, key):
            cfg[arg] = getattr(mod, key)

    layout, _board = layout_stage.run(board_file, verbose=not a.quiet, **cfg)
    if not a.no_save:
        layout.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
