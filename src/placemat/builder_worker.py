"""The board builder's reader: one process per request that generates a board's schematic layout (as a first `placemat run` does),
reads the generated board and answers with what the builder shows - its parts and cells, its nets, the total courtyard area, and
the facts `placemat facts` would print. pcbnew stays out of the studio server: the server starts this module with a request on
stdin and relays the lines it writes on stdout.

Request: `{"zen": path, "name": board name, "script": path or null, "fresh": bool}`. Lines out: `{"ev": "progress", "text"}` while it
works, then `{"ev": "board", ...}` (see `board_record`) or `{"ev": "error", "message", "tail"}`. Nothing is written but what `pcb
layout` and the generation cache already write."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

from .builder_facts import facts_record


def _poly_area(poly) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]))) / 2.0


def courtyard_area(fp) -> float:
    """What a footprint claims of the board, mm2: its courtyard polygon's area, else the box it claims (the placer's claim)."""
    if fp.courtyard_poly:
        return _poly_area(list(fp.courtyard_poly))
    b = fp.courtyard_box
    return max(0.0, (b.right - b.left) * (b.bottom - b.top))


def _box_size(box) -> tuple:
    return round(box.right - box.left, 3), round(box.bottom - box.top, 3)


def parts_record(geometry) -> dict:
    """The generated board's parts and cells as the builder reads them. Parts are the footprints, cells are the stamped groups, an
    item's key is the name a script gives it (`Part(key)` for a loose part, `Cell(key)` for a cell)."""
    parts, cells = [], []
    for fp in geometry.footprints:
        w, h = _box_size(fp.courtyard_box)
        parts.append({"key": fp.inst, "ref": fp.ref, "value": fp.value, "cell": fp.cell, "w": w, "h": h, "area": round(courtyard_area(fp), 3),
                      "pads": len(fp.pads), "face": fp.face.value, "nets": sorted({p.net for p in fp.pads if p.net}),
                      "pad_list": [{"number": p.number, "net": p.net} for p in fp.pads]})
    for name, cell in geometry.cells.items():
        w, h = _box_size(cell.courtyard_box)
        members = list(cell.members)
        cells.append({"key": name, "members": [fp.inst for fp in members], "w": w, "h": h,
                      "area": round(sum(courtyard_area(fp) for fp in members), 3), "pads": sum(len(fp.pads) for fp in members),
                      "nets": sorted({p.net for fp in members for p in fp.pads if p.net}), "faces": dict(cell.faces)})
    total = sum(courtyard_area(fp) for fp in geometry.footprints)
    return {"parts": parts, "cells": cells, "nets": sorted(geometry.nets), "total_courtyard_area": round(total, 3),
            "copper_layers": len(geometry.layers)}


def board_record(geometry, facts_doc, cfg, *, confirmed: str = "", rise_file: str = "", fab_file: str = "") -> dict:
    """The generated board as the builder reads it: `parts_record`, the facts `placemat facts` would print, and where they are
    decided."""
    return {**parts_record(geometry), "facts": facts_record(facts_doc), "confirmed": confirmed,
            "rise_set": cfg.source_of("check_rise_c") != "default", "rise_file": rise_file, "fab_file": fab_file,
            "outline_box": list(_outline_box(geometry))}


def _outline_box(geometry):
    b = geometry.outline_box
    return (b.left, b.top, b.right, b.bottom) if b is not None else ()


def read(zen, name, script=None, fresh=False, say=lambda text: None) -> dict:
    """Generate (or restore the cached generation of) the board and read it: the record `board_record` makes."""
    from . import facts as facts_mod, settings as settings_mod
    from .kicad.read import read_board
    from .pins import board_pin_names
    from .project import fab_profile, find_board, views_dir
    from .runner import cached_generation, generate, scripted_board
    import dataclasses
    src = find_board(Path(zen).resolve().parent, wanted=name)
    script = Path(script).resolve() if script else None
    cfg = settings_mod.load(src.board_dir, script=script if script is not None and script.is_file() else None)
    fab = fab_profile(src.board_dir)
    run_dir = views_dir(src.board_dir, "builder")
    say("generating %s with pcb layout (a cached generation is used where its inputs are unchanged) ..." % src.zen.name)
    ran = generate(src, run_dir, fresh, quiet=True)
    say("generated %s" % src.name if ran else "used the cached generation of %s" % src.name)
    generated = cached_generation(src) / src.pcb.name
    say("reading the generated board ...")
    geometry = read_board(generated, courtyard_excess_mm=fab.courtyard_excess)
    geometry = dataclasses.replace(geometry, pin_names=board_pin_names(src, generated.parent))
    plane_layers = frozenset()
    if script is not None and script.is_file():
        with settings_mod.bind(cfg):
            board = scripted_board(script, src, cfg, fab, keep_going=True, pcb=generated)
        plane_layers = frozenset(l for l, _nets in board._plane_layers().items())
    doc = facts_mod.facts_of(geometry, fab, cfg.check_rise_c, plane_layers)
    confirmed = facts_mod.confirmed_digest(cfg, script) if script is not None and script.is_file() else ""
    rise_file = cfg.sources.get("check_rise_c", "") if cfg.source_of("check_rise_c") != "default" else ""
    return board_record(geometry, doc, cfg, confirmed=confirmed, rise_file=rise_file, fab_file=str(fab.path) if fab.path else "")


def main() -> int:
    from .runner import RunFailure
    out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)                       # whatever else prints goes to stderr, not into the protocol
    sys.stdout = sys.stderr

    def send(event):
        out.write(json.dumps(event, separators=(",", ":")) + "\n")
        out.flush()
    try:
        req = json.loads(sys.stdin.read() or "{}")
        record = read(req["zen"], req["name"], req.get("script"), bool(req.get("fresh")), lambda t: send({"ev": "progress", "text": t}))
        send({"ev": "board", **record})
        return 0
    except RunFailure as e:
        send({"ev": "error", "message": str(e), "tail": e.details.get("tail", ""), "log": e.details.get("log", "")})
    except Exception as e:
        send({"ev": "error", "message": "%s: %s" % (type(e).__name__, e), "tail": ""})
    return 1


if __name__ == "__main__":
    sys.exit(main())
