"""Running a layout script written to a real file on a small synthetic board, so a finding's suggestions bind to
the script's own lines and can be applied to it."""
from pathlib import Path

from placemat.context import run_script
from placemat.layout import Board
from tests.fixtures import board_geometry, footprint

IMPORTS = ("from placemat import (board, Along, Beside, Between, Centre, Edge, Face, FreeSpot, LinkWeight, Location,\n"
           "                      Near, OnEdge, PadRef, Part, Past, Priority, Turns)\n")


def make_board(parts=None, width=60.0, height=60.0, keep_going=True, settings=None, **kw):
    parts = parts if parts is not None else [
        footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("VIN", "OUT")),
        footprint("C1", 40, 40, inst="c1", nets=("VIN", "GND")),
        footprint("C4", 40, 45, inst="c4", nets=("VIN", "GND")),
        footprint("R1", 40, 50, inst="r1", nets=("OUT", "GND")),
        footprint("J1", 45, 10, w=4, h=4, inst="j1", nets=("OUT", "GND"))]
    extra = {"settings": settings} if settings is not None else {}
    return Board(board_geometry(parts, width=width, height=height), edge_margin=1.0, keep_going=keep_going, **extra, **kw)


def script(tmp_path: Path, body: str, name="layout.py", imports=IMPORTS) -> Path:
    path = tmp_path / name
    path.write_text(imports + "\n" + body)
    return path


def resolve(tmp_path: Path, body: str, parts=None, name="layout.py", imports=IMPORTS, **kw):
    """(board, plan, script path) of `body` run against a board of `parts`."""
    path = script(tmp_path, body, name, imports)
    board = make_board(parts, **kw)
    board.script_file = str(path)
    run_script(path, board)
    plan = board.resolve()
    return board, plan, path


def suggestions_of(plan, case=None):
    return [s for f in plan.findings if case is None or f.case == case for s in f.suggestions]


def apply_and_resolve(tmp_path: Path, plan, id: str, path: Path, parts=None, **kw):
    """Apply suggestion `id` of the plan to the script on disk, as `placemat apply` does, and resolve it again:
    (board, plan)."""
    from placemat import suggestions as sg
    sg.apply_suggestion(suggestions_of(plan), id, root=tmp_path, log=tmp_path / "applied.jsonl")
    board = make_board(parts, **kw)
    board.script_file = str(path)
    run_script(path, board)
    return board, board.resolve()
