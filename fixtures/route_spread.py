"""How much a route's outcome depends on small changes to its input: one
board routed N ways, reported as a spread.

On a dense board a small change to the input changes which nets fail, so one
route cannot judge a placement or a router change. Two perturbations:

- `order` (the default): the router's own net order (MPS, computed with the
  router's code) with a few neighbouring pairs swapped, a different seeded
  set per run; run 0 is the order unswapped. Routed with `--ordering
  original`, so a router's own ordering passes after MPS do not apply.
- `jitter`: the router's own ordering, all passes included, with a seeded
  set of neighbouring swaps made by the router after its fan pass
  (KICAD_ORDER_JITTER, run k seed k; run 0 none). Needs a router that has
  the knob.
- `offset`: the whole board moved by N sub-grid offsets (a Halton cover of
  one cell; run 0 is no offset). This measures grid alignment, which on a
  minimum-pitch part dominates: a row whose centre lines leave the grid seals.

Each run is a fresh process with the router `placemat route` drives. Reported:
failed nets per run (min, median, max) and how often each net failed; with
`--connectivity`, the same for the nets the router's `check_connected.py`
finds unrouted or broken in the output.

    route_spread.py BOARD.kicad_pcb OUT [--runs N] [--perturb order|jitter|offset]
                    [--swaps K] [--grid G] [--jobs J] [--router DIR] [--connectivity]
                    -- ROUTER ARGS...

ROUTER ARGS must name the nets (`--nets ...`) for the order perturbation.

ROUTER ARGS go to the router's route.py as given (nets, layers, rules).
Results: OUT/spread.json and one directory per run.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
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


MPS = """
import sys, json
sys.path.insert(0, sys.argv[1] + "/py_router")
from kicad_parser import parse_kicad_pcb
from net_queries import compute_mps_net_ordering
pcb = parse_kicad_pcb(sys.argv[2])
names = {nid: getattr(n, 'name', n) for nid, n in pcb.nets.items()}
ids = {v: k for k, v in names.items()}
nets = json.loads(sys.argv[3])
order = compute_mps_net_ordering(pcb, [ids[n] for n in nets if n in ids])
order = order if isinstance(order, list) else order.ordered_ids
print(json.dumps([names[n] for n in order]))
"""


def mps_order(router: str, board: str, nets: list) -> list:
    py = Path(router) / ".venv/bin/python"
    r = subprocess.run([str(py), "-c", MPS, router, board, json.dumps(nets)], capture_output=True, text=True,
                       cwd=router)
    return json.loads(r.stdout.strip().splitlines()[-1])


def swapped(order: list, seed: int, swaps: int) -> list:
    """`order` with `swaps` neighbouring pairs swapped, chosen by `seed`."""
    import random
    out = list(order)
    rng = random.Random(seed)
    for _ in range(swaps if seed else 0):
        i = rng.randrange(len(out) - 1)
        out[i], out[i + 1] = out[i + 1], out[i]
    return out


def nets_in(args: list) -> tuple:
    """(the nets named after --nets, the args without them)."""
    if "--nets" not in args:
        return [], list(args)
    i = args.index("--nets")
    j = i + 1
    while j < len(args) and not args[j].startswith("--"):
        j += 1
    return args[i + 1:j], args[:i] + args[j:]


UNROUTED = re.compile(r"^    (\S.*) \(\d+ pads\)$")
BROKEN = re.compile(r"^  (\S.*) \(net \d+\):$")


def disconnected(router: str, pcb: Path) -> list | None:
    """The nets the router's connectivity check finds unrouted or broken."""
    py = Path(router) / ".venv/bin/python"
    r = subprocess.run([str(py), "-X", "utf8", str(Path(router) / "py_router/check_connected.py"), str(pcb), "--quiet"],
                       cwd=router, capture_output=True, text=True, errors="replace")
    lines = r.stdout.splitlines()
    if not any(l.strip() in ("OK",) or l.startswith("FAILED") for l in lines):
        return None
    return sorted({m.group(1) for l in lines for m in (UNROUTED.match(l), BROKEN.match(l)) if m})


def route(job) -> dict:
    board, out, dx, dy, router, args, connectivity = job
    env = dict(os.environ)
    if isinstance(dx, str):                 # ("order", seed) or ("jitter", seed)
        src = shifted(Path(board), Path(out), 0.0, 0.0)
        if dx == "jitter":
            env["KICAD_ORDER_JITTER"] = str(dy)
    else:
        src = shifted(Path(board), Path(out), dx, dy)
    py = Path(router) / ".venv/bin/python"
    r = subprocess.run([str(py), "-X", "utf8", str(Path(router) / "py_router/route.py"), str(src),
                        str(Path(out) / "out.kicad_pcb"), "--json-out", str(Path(out) / "r.json")] + list(args),
                       cwd=router, capture_output=True, text=True, errors="replace", env=env)
    (Path(out) / "route.log").write_text(r.stdout + r.stderr)
    try:
        j = json.load(open(Path(out) / "r.json"))
        failed = sorted(j.get("failed_single") or [])
        failed += sorted(f["net_name"] for f in (j.get("failed_multipoint") or []) if f.get("net_name") not in failed)
    except (OSError, ValueError):
        failed = None
    res = {"dx": dx, "dy": dy, "failed": failed, "rc": r.returncode}
    if connectivity:
        res["disconnected"] = disconnected(router, Path(out) / "out.kicad_pcb")
    return res   # order/jitter runs: dx the mode, dy the seed


def spread(runs: list, key: str = "failed") -> dict:
    ok = [r for r in runs if r.get(key) is not None]
    counts = [len(r[key]) for r in ok]
    freq = {}
    for r in ok:
        for n in r[key]:
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
    ap.add_argument("--perturb", choices=("order", "jitter", "offset"), default="order")
    ap.add_argument("--connectivity", action="store_true",
                    help="also run the router's check_connected.py on each output")
    ap.add_argument("--swaps", type=int, default=0, help="order: pairs swapped per run (default: a tenth of the nets)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.perturb == "offset":
        jobs = [(a.board, out / ("run%02d" % k), dx, dy, a.router, args, a.connectivity) for k, (dx, dy) in enumerate(offsets(a.runs, a.grid))]
    elif a.perturb == "jitter":
        jobs = [(a.board, out / ("run%02d" % k), "jitter", k, a.router, args, a.connectivity) for k in range(a.runs)]
    else:
        nets, rest = nets_in(args)
        if not nets:
            ap.error("the order perturbation needs --nets in the router arguments")
        base = mps_order(a.router, a.board, nets)
        swaps = a.swaps or max(1, len(base) // 10)
        jobs = [(a.board, out / ("run%02d" % k), "order", k, a.router,
                 rest + ["--ordering", "original", "--nets"] + swapped(base, k, swaps), a.connectivity) for k in range(a.runs)]
    with concurrent.futures.ProcessPoolExecutor(a.jobs) as ex:
        runs = list(ex.map(route, jobs))
    result = {"board": a.board, "router": a.router, "args": args, "grid": a.grid, "runs": runs, "spread": spread(runs)}
    if a.connectivity:
        result["connectivity"] = spread(runs, "disconnected")
    out.mkdir(parents=True, exist_ok=True)
    (out / "spread.json").write_text(json.dumps(result, indent=1))
    s = result["spread"]
    print("failed nets per run: min %s, median %s, max %s over %d runs (%d errors)" % (
        s["failed_min"], s["failed_median"], s["failed_max"], s["runs"], s["errors"]))
    for n, c in s["net_failures"].items():
        print("  %-40s %d of %d" % (n, c, s["runs"] - s["errors"]))
    if a.connectivity:
        s = result["connectivity"]
        print("disconnected nets per run: min %s, median %s, max %s over %d runs (%d errors)" % (
            s["failed_min"], s["failed_median"], s["failed_max"], s["runs"], s["errors"]))
        for n, c in s["net_failures"].items():
            print("  %-40s %d of %d" % (n, c, s["runs"] - s["errors"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
