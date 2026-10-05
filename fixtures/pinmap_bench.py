"""The pin map study's speed and result on the reference boards (fixtures/pinmap/reference.json): each case's laid board
read as its file has it, its parts given the fixture's pin annotations (no capture carries them), and the study's core
run on each annotated part, `--repeat` times. Prints, per case, the median seconds per studied part against
`pins.budget_ms`, whether the native core ran, whether the clock ran out, and the present and best totals; with
`--long`, the best a long search finds too, the mark the default search effort is judged against.

    flock <realboard lock> .venv/bin/python fixtures/pinmap_bench.py [--repeat N] [--long] [--set pins_key=value ...]

Real boards: run it alone, under the lock the other real-board runs take."""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REFERENCE = HERE / "pinmap" / "reference.json"


def annotated(geometry, parts: dict):
    """The board with the fixture's annotations added to its parts' fields."""
    fps = tuple(dataclasses.replace(fp, fields=dict(fp.fields, **parts[fp.ref])) if fp.ref in parts else fp
                for fp in geometry.footprints)
    return dataclasses.replace(geometry, footprints=fps)


def cases() -> list:
    return json.loads(REFERENCE.read_text())["cases"]


def board_of(case):
    from placemat.kicad.read import read_board
    return annotated(read_board(HERE / case["board"]), case["parts"])


def input_of(case):
    """The case's board read and annotated, as the study's input."""
    from placemat.pairs import board_pairs
    from placemat.pinmap_input import build, placed_from_geometry
    g = board_of(case)
    placed = placed_from_geometry(g)
    inp, _ = build(placed.pads, placed.parts, g.pin_names, frozenset(case["quiet"]), board_pairs(g.netclasses),
                   g.netclasses, cells=placed.cells)
    return inp


def run_case(case, settings, repeat: int) -> dict:
    """The study of each of the case's annotated parts, `repeat` times: the median seconds a part, and the last run's
    present and best totals, the best pose and whether the clock ran out."""
    from placemat.pinmap_core import native_core, problem_of, study_group
    inp = input_of(case)
    pb = problem_of(inp, settings.pins_exit_mm)
    times, out = [], {}
    for _ in range(repeat):
        t0 = time.perf_counter()
        groups = [study_group(inp, (ref,), settings, pb=pb) for ref in sorted(case["parts"])]
        times.append((time.perf_counter() - t0) / len(groups))
        g = groups[0]
        best = min(g.results, key=lambda r: r.breakdown.total) if g.results else None
        out = {"present": round(g.present.total, 3), "best": round(best.breakdown.total, 3) if best else None,
               "pose": [t for _, t, _ in best.poses] if best else None, "budget_out": g.budget_out,
               "native": native_core() is not None}
    return dict(out, seconds_per_part=round(statistics.median(times), 3))


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--long", action="store_true", help="also run a long search (4 seeds of 4000 moves, no clock)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="a setting, e.g. pins_anneal_moves=200")
    args = ap.parse_args(argv)
    from placemat.settings import Settings
    over = {k: _value(v) for k, v in (s.split("=", 1) for s in args.set)}
    if "pins_rotations" in over:
        over["pins_rotations"] = tuple(over["pins_rotations"])
    settings = dataclasses.replace(Settings(), **over)
    for case in cases():
        got = run_case(case, settings, args.repeat)
        line = "%s: %.3f s a part (budget %d ms, native %s), present %s, best %s at %s, clock ran out: %s" % (
            case["name"], got["seconds_per_part"], settings.pins_budget_ms, got["native"], got.get("present"),
            got.get("best"), got.get("pose"), got.get("budget_out"))
        if args.long:
            long = dataclasses.replace(settings, pins_seeds=4, pins_anneal_moves=4000, pins_budget_ms=10 ** 7)
            line += "; long search best %s" % run_case(case, long, 1).get("best")
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
