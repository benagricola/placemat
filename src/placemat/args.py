#!/usr/bin/env python3
"""Argument types the commands share.

A command line is built from these rather than from each tool's own idea of
what a word means. `placemat airwires middleweight` and `placemat lint
middleweight` name the same board and reach different files; knowing which is
this module's job, not the caller's.

Resolution happens INSIDE the parser, so argparse decides what is a value of
an option and what is a positional. Scanning the raw argv for board-shaped
words cannot know that `--json out.json` is a filename, and guessing it from
position breaks the moment a switch comes first.
"""
import argparse
import glob
import os


def _norm(s):
    return "".join(c for c in s.lower() if c.isalnum())


def _pick(found, dirname, what, value):
    """Of several candidates in a board's directory, the one that IS the board.

    A directory can hold more than one - a daughter board, a variant - and
    taking the first alphabetically silently lays out the wrong one. The board
    is the file whose name matches the directory; anything else is named."""
    if len(found) == 1:
        return found[0]
    exact = [f for f in found
             if _norm(os.path.basename(f).split(".")[0].replace("_layout", "")) == _norm(dirname)]
    if len(exact) == 1:
        return exact[0]
    raise argparse.ArgumentTypeError(
        "%s holds %d %s (%s) - name the one you mean"
        % (value, len(found), what, ", ".join(os.path.basename(f) for f in found)))


def _project():
    from placemat.project import active
    return active()


def board(value):
    """A board: its name, its directory, or a path to any KiCad board file.

    A path is taken as given - a single cell's fragment is a legitimate thing
    to measure. A name is resolved to that board's generated layout.
    """
    if os.path.isfile(value):
        return value
    proj = _project()
    hit = proj.board_pcb(value)
    if hit:
        return hit
    if hit is False:
        raise argparse.ArgumentTypeError(
            "%s has never been generated - there is no layout to read. "
            "`placemat round %s` builds one." % (value, value))
    if "/" in value or "." in value:
        raise argparse.ArgumentTypeError("%s does not exist" % value)
    raise argparse.ArgumentTypeError(
        "%r is neither a file nor a board here. boards: %s"
        % (value, ", ".join(proj.board_names()) or "none"))


def script(value):
    """A board's layout script, by the board's name or by path."""
    if os.path.isfile(value):
        return value
    proj = _project()
    for d in proj.board_dirs:
        if os.path.basename(d).lower() == value.rstrip("/").lower():
            found = sorted(glob.glob(os.path.join(d, "*_layout.py")))
            if found:
                return _pick(found, os.path.basename(d), "layout scripts", value)
            raise argparse.ArgumentTypeError("%s has no layout script yet - "
                                             "`placemat new-board` writes one" % value)
    raise argparse.ArgumentTypeError(
        "%r is neither a file nor a board here. boards: %s"
        % (value, ", ".join(proj.board_names()) or "none"))


def cell(value):
    """A cell: its name, or a path to its fragment."""
    if os.path.isfile(value):
        return value
    cells = _project().module_dirs
    d = cells.get(value) or next((v for k, v in cells.items()
                                  if k.lower() == value.lower()), None)
    frag = os.path.join(d, "layout", "layout.kicad_pcb") if d else None
    if frag and os.path.exists(frag):
        return frag
    raise argparse.ArgumentTypeError(
        "%r is not a cell here (this reads CELLS, not boards). cells: %s"
        % (value, ", ".join(sorted(cells)) or "none"))


def zen(value):
    """A board's schematic: its name, or the path to a `.zen`."""
    if os.path.isfile(value):
        return value
    proj = _project()
    for d in proj.board_dirs:
        if os.path.basename(d).lower() == value.rstrip("/").lower():
            found = sorted(glob.glob(os.path.join(d, "*.zen")))
            if found:
                return _pick(found, os.path.basename(d), "schematics", value)
    raise argparse.ArgumentTypeError(
        "%r is neither a file nor a board here. boards: %s"
        % (value, ", ".join(proj.board_names()) or "none"))
