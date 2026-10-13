"""How far the surface-lane judgement of escapes agrees with the exact path search, over the bench modules.

Each module under fixtures/*/modules/ is resolved as fixtures/bench.py resolves it (the default configuration). For each
pad the judgement judges (escapes.Escapes.judged), "a surface way out toward the target" is asked twice: the lanes say
yes when the pad's way is Way.SURFACE; the path search says yes when `path_out(exact=True, via_exit=False)` finds a
track from the pad to the edge of a window `score.escape_reach` round it, on the side facing the pad's nearest other
placed pad of its net, against the copper the judgement's own search reads (`escapes.search_near`). Prints one JSON line per disagreement, then one per module with its agreement share, how many
pads the judgement sent to the path search (its lanes not deciding) and the seconds the judgement took, then the
totals. Since the judgement is the path search's with the lanes as a first check, a disagreement is a lane open
toward the target where the search finds no way (`lanes_only`).

    .venv/bin/python fixtures/escape_agreement.py [name ...] [--jobs N]

A disagreement's `cause`:
    path_only   the path search finds a way the judgement does not
    lanes_only  a lane the path search does not find: the window's corners lie past the lanes' reach, or the search's
                0.05 mm cells miss a gap a lane's centre line keeps
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def agreement(path: str) -> dict:
    from bench import ModuleBoard, _name, _planes, _size
    from placemat.escapes import Way, judging, path_out, search_near
    from placemat.kicad.read import read_board
    p = pathlib.Path(path)
    g = read_board(p)
    hand = any(p.parents[1].glob("*_layout.py"))
    board = ModuleBoard(g, {}, _planes(g), _size(g, hand))()
    occ = board.resolve().occupancy
    esc = judging(occ)
    reach = occ.settings.score_escape_reach
    rows, agree = [], 0
    near = search_near(occ)                 # the copper the judgement's search reads
    t0 = time.perf_counter()
    judged = esc.judged()
    seconds = time.perf_counter() - t0
    searched = esc.searched
    for ref, number, net, way, _ in judged:
        if net in occ.quiet_nets:
            continue                        # judged for walled only: no target to agree on
        centre = esc._lanes_of(ref)[2][number][2].center
        aim = esc._aim(ref, number, net, centre)
        lanes = way is Way.SURFACE
        path = bool(path_out(occ, ref, number, depth=reach, toward=aim, near=near, exact=True, via_exit=False))
        if lanes == path:
            agree += 1
        else:
            rows.append({"module": _name(p), "pad": [ref, number], "net": net, "way": way.value, "lanes": lanes,
                         "path": path, "cause": "path_only" if path else "lanes_only"})
    signal = sum(1 for j in judged if j[2] not in occ.quiet_nets)
    return {"module": _name(p), "judged": signal, "agree": agree, "disagree": rows, "searched": searched,
            "seconds": round(seconds, 3)}


def main(argv) -> int:
    from bench import boards, _name
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--jobs", type=int, default=1)
    args = ap.parse_args(argv)
    paths = [str(p) for p in boards() if not args.names or _name(p) in args.names]
    totals = {"judged": 0, "agree": 0, "path_only": 0, "lanes_only": 0, "searched": 0, "seconds": 0.0}
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for r in pool.map(agreement, paths):
            for row in r["disagree"]:
                print(json.dumps(row))
                totals[row["cause"]] += 1
            share = r["agree"] / r["judged"] if r["judged"] else 1.0
            print(json.dumps({"module": r["module"], "judged": r["judged"], "agree": r["agree"], "share": round(share, 4),
                              "searched": r["searched"], "seconds": r["seconds"]}))
            for k in ("judged", "agree", "searched", "seconds"):
                totals[k] += r[k]
            sys.stdout.flush()
    totals["seconds"] = round(totals["seconds"], 3)
    totals["share"] = round(totals["agree"] / totals["judged"], 4) if totals["judged"] else 1.0
    print(json.dumps({"total": totals}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
