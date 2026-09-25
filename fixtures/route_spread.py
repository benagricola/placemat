"""How much a route's outcome depends on where the board sits on the router's
grid: the same board routed at N sub-grid offsets.

On a dense board a small change to the input changes which nets fail, so one
route cannot judge a placement or a router change. This routes the board at
N offsets inside one grid cell (the first is no offset; the rest follow a
Halton sequence, so they cover the cell evenly), each in a fresh process
with the router `placemat route` drives, and reports the spread: failed nets
per run (min, median, max) and how often each net failed.

    route_spread.py BOARD.kicad_pcb OUT [--runs N] [--grid G] [--jobs J]
                    [--router DIR] -- ROUTER ARGS...

ROUTER ARGS go to the router's route.py as given (nets, layers, rules).
Results: OUT/spread.json and one directory per run.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def halton(i: int, base: int) -> float:
    f, r = 1.0, 0.0
    while i > 0:
        f /= base
        r += f * (i % base)
        i //= base
    return r


def offsets(n: int, grid: float) -> list:
    """(dx, dy) in mm: none first, then a Halton (2, 3) cover of one cell."""
    return [(0.0, 0.0)] + [(round(halton(i, 2) * grid, 4), round(halton(i, 3) * grid, 4)) for i in range(1, n)]


SHIFT = """
import sys
sys.path.insert(0, %r)
from placemat.kicad.quiet import import_pcbnew
p = import_pcbnew()
b = p.LoadBoard(sys.argv[1])
b.Move(p.VECTOR2I(p.FromMM(float(sys.argv[3])), p.FromMM(float(sys.argv[4]))))
p.SaveBoard(sys.argv[2], b)
""" % str(ROOT / "src")


def shifted(board: Path, out: Path, dx: float, dy: float) -> Path:
    """The board moved by (dx, dy), with its project beside it. Written in a
    fresh process: KiCad keeps a project it has saved."""
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "in.kicad_pcb"
    subprocess.run([sys.executable, "-c", SHIFT, str(board), str(dst), str(dx), str(dy)],
                   check=True, capture_output=True)
    pro = board.with_suffix(".kicad_pro")
    if pro.exists():
        shutil.copy(pro, out / "in.kicad_pro")      # after the save, which writes a default one
    return dst


def route(job) -> dict:
    board, out, dx, dy, router, args = job
    src = shifted(Path(board), Path(out), dx, dy)
    py = Path(router) / ".venv/bin/python"
    r = subprocess.run([str(py), "-X", "utf8", str(Path(router) / "py_router/route.py"), str(src),
                        str(Path(out) / "out.kicad_pcb"), "--json-out", str(Path(out) / "r.json")] + list(args),
                       cwd=router, capture_output=True, text=True, errors="replace")
    (Path(out) / "route.log").write_text(r.stdout + r.stderr)
    try:
        j = json.load(open(Path(out) / "r.json"))
        failed = sorted(j.get("failed_single") or [])
        failed += sorted(f["net_name"] for f in (j.get("failed_multipoint") or []) if f.get("net_name") not in failed)
    except (OSError, ValueError):
        failed = None
    return {"dx": dx, "dy": dy, "failed": failed, "rc": r.returncode}


def spread(runs: list) -> dict:
    ok = [r for r in runs if r["failed"] is not None]
    counts = [len(r["failed"]) for r in ok]
    freq = {}
    for r in ok:
        for n in r["failed"]:
            freq[n] = freq.get(n, 0) + 1
    return {"runs": len(runs), "errors": len(runs) - len(ok),
            "failed_min": min(counts) if counts else None, "failed_median": statistics.median(counts) if counts else None,
            "failed_max": max(counts) if counts else None,
            "net_failures": dict(sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])))}


def main(argv) -> int:
    if "--" in argv:
        i = argv.index("--")
        argv, args = argv[:i], argv[i + 1:]
    else:
        args = []
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("out")
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--grid", type=float, default=0.1)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--router", default=os.environ.get("KRT_DIR", os.path.expanduser("~/work/KiCadRoutingTools")))
    a = ap.parse_args(argv)
    out = Path(a.out)
    jobs = [(a.board, out / ("run%02d" % k), dx, dy, a.router, args) for k, (dx, dy) in enumerate(offsets(a.runs, a.grid))]
    with concurrent.futures.ProcessPoolExecutor(a.jobs) as ex:
        runs = list(ex.map(route, jobs))
    result = {"board": a.board, "router": a.router, "args": args, "grid": a.grid, "runs": runs, "spread": spread(runs)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "spread.json").write_text(json.dumps(result, indent=1))
    s = result["spread"]
    print("failed nets per run: min %s, median %s, max %s over %d runs (%d errors)" % (
        s["failed_min"], s["failed_median"], s["failed_max"], s["runs"], s["errors"]))
    for n, c in s["net_failures"].items():
        print("  %-40s %d of %d" % (n, c, s["runs"] - s["errors"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
