"""What a code change does to placement, across the module fixtures.

Every part of each module under fixtures/*/modules/ is released to a bare
place() and resolved under each configuration in CONFIGS. A result is scored
by parts placed, then placemat's findings, then half-perimeter wirelength
(HPWL) over the nets that are not planes, and compared with the committed
baseline in bench.json: more placed is better, then fewer findings, then HPWL
more than NOISE shorter.

    .venv/bin/python fixtures/bench.py [name ...] [--config NAME] [--jobs N] [--update]

A change that can move a placement runs this before it is committed, puts the
tally lines in the commit message, and commits bench.json with it when a
number changed.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import json
import math
import os
import pathlib
import statistics
import sys
import time

CONFIGS = {"default": {}, "solve": {"solve_enabled": True}, "physical": {"place_envelope": "physical"}}
NOISE = 0.01          # report.AIRWIRE_NOISE's value; HPWL is deterministic, the margin is for trivia
KINDS = ("better", "worse", "same", "new", "gone")


def hpwl(pads, skip=frozenset()) -> float:
    """Per net, the width plus height of the box round its pads, summed."""
    by_net = {}
    for net, x, y in pads:
        if net and net not in skip:
            by_net.setdefault(net, []).append((x, y))
    total = 0.0
    for pts in by_net.values():
        if len(pts) >= 2:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return round(total, 1)


def verdict(new: dict, old: dict) -> int:
    if new["placed"] != old["placed"]:
        return 1 if new["placed"] > old["placed"] else -1
    if new["findings"] != old["findings"]:
        return 1 if new["findings"] < old["findings"] else -1
    if new["hpwl"] < old["hpwl"] * (1 - NOISE):
        return 1
    if new["hpwl"] > old["hpwl"] * (1 + NOISE):
        return -1
    return 0


def diff(run: dict, base: dict) -> list:
    out = []
    names = sorted(set(run["modules"]) | set(base["modules"]))
    configs = sorted(set(run["configs"]) | set(base["configs"]))
    for m in names:
        new_m, old_m = run["modules"].get(m, {}), base["modules"].get(m, {})
        for c in configs:
            new, old = new_m.get(c), old_m.get(c)
            if new is None and old is None:
                continue
            if old is None:
                kind = "new"
            elif new is None:
                kind = "gone"
            else:
                kind = {1: "better", -1: "worse", 0: "same"}[verdict(new, old)]
            out.append((c, m, kind))
    return out


def tally(changes) -> dict:
    out = {}
    for c, _, kind in changes:
        out.setdefault(c, dict.fromkeys(KINDS, 0))[kind] += 1
    return out


def dump(results: dict) -> str:
    """Sorted, one module per line, so a diff shows which modules moved."""
    configs = json.dumps(results["configs"], sort_keys=True)
    rows = ['    %s: %s' % (json.dumps(m), json.dumps(results["modules"][m], sort_keys=True))
            for m in sorted(results["modules"])]
    return '{\n  "configs": %s,\n  "modules": {\n%s\n  }\n}\n' % (configs, ",\n".join(rows))


def load(text: str) -> dict:
    return json.loads(text)


ROOT = pathlib.Path(__file__).resolve().parent
BASELINE = ROOT / "bench.json"
MARGIN = 0.10          # a hand module's board: its courtyard extent plus this much a side
FILL = 3.0             # an unplaced module's board: this many times its courtyard area, square
PLANE_SHARE = 0.5      # a net touching this share of a module's parts is a plane...
PLANE_MIN_PARTS = 6    # ...in a module of at least this many


def boards() -> list:
    found = sorted(ROOT.glob("*/modules/*/layout/layout.kicad_pcb")) + \
            sorted(ROOT.glob("*/modules/*/kicad/layout.kicad_pcb"))
    return sorted(found, key=_name)


def _name(path: pathlib.Path) -> str:
    return "%s/%s" % (path.parents[3].name, path.parents[1].name)


def _planes(g) -> set:
    parts = len(g.footprints)
    count = {}
    for fp in g.footprints:
        for net in {p.net for p in fp.pads if p.net}:
            count[net] = count.get(net, 0) + 1
    if parts < PLANE_MIN_PARTS:
        return set()
    return {n for n, c in count.items() if c / parts >= PLANE_SHARE}


def _size(g, hand: bool):
    from placemat.values import Box
    if hand:
        box = Box.union([fp.courtyard_box for fp in g.footprints])
        return box.width * (1 + 2 * MARGIN), box.height * (1 + 2 * MARGIN)
    side = math.sqrt(sum(fp.courtyard_box.area for fp in g.footprints) * FILL)
    return side, side


def _resolve(g, overrides: dict, planes: set, size) -> dict:
    from placemat.layout import Board
    from placemat.settings import Settings
    from placemat.values import CopperLayer, Net, Part
    b = Board(g, edge_margin=0.2, keep_going=True, settings=dataclasses.replace(Settings(), **overrides))
    b.size(width=round(size[0], 2), height=round(size[1], 2))
    for net in sorted(planes):
        b.plane(Net(net), [CopperLayer.B], why="benchmark: a net most parts share")
    for fp in sorted(g.footprints, key=lambda f: f.inst):
        b.place(Part(fp.inst), rotation=fp.rotation)
    plan = b.resolve()
    placed = {s.item for s in plan.steps if s.placement is not None and s.kind == "part"}
    pads = []
    for fp in g.footprints:
        if fp.inst in placed:
            for p in fp.pads:
                at = plan.occupancy.pad_location(fp.ref, p.number)
                pads.append((p.net, at.x, at.y))
    return {"placed": len(placed), "findings": len(plan.findings), "hpwl": hpwl(pads, planes)}


def _hand_pads(g) -> list:
    """The fixture board's pads, measured as a placed part's are: one point per
    pad number, the centre of every pad carrying it (Occupancy.pad_location)."""
    from placemat.values import Box
    out = []
    for fp in g.footprints:
        by_number = {}
        for p in fp.pads:
            by_number.setdefault(p.number, []).append(p)
        for pads in by_number.values():
            at = Box.union([p.box for p in pads]).center
            out.extend((p.net, at.x, at.y) for p in pads)
    return out


def bench_module(path: str, configs: dict):
    from placemat.kicad.read import read_board
    path = pathlib.Path(path)
    g = read_board(path)
    hand = any(path.parents[1].glob("*_layout.py"))
    planes = _planes(g)
    size = _size(g, hand)
    row = {"parts": len(g.footprints), "hand": hpwl(_hand_pads(g), planes) if hand else None}
    seconds = {}
    for name, overrides in configs.items():
        t0 = time.perf_counter()
        row[name] = _resolve(g, overrides, planes, size)
        seconds[name] = time.perf_counter() - t0
    return _name(path), row, seconds


def _line(c, m, new, old) -> str:
    def pair(key, fmt):
        a, b = old[key], new[key]
        return (fmt % b) if a == b else ((fmt + " -> " + fmt) % (a, b))
    return "%-8s %-28s placed %s, findings %s, hpwl %s" % (
        c, m, pair("placed", "%d"), pair("findings", "%d"), pair("hpwl", "%.1f"))


def report(run: dict, base: dict, say=print) -> None:
    changes = diff(run, base)
    for c, m, kind in changes:
        new = run["modules"].get(m, {}).get(c)
        old = base["modules"].get(m, {}).get(c)
        if kind in ("new", "gone"):
            say("%-8s %-28s %s" % (c, m, kind))
        elif new != old:
            say("%s   %s" % (_line(c, m, new, old), kind))
    for c, counts in sorted(tally(changes).items()):
        both = [(run["modules"][m][c], base["modules"][m][c]) for cc, m, k in changes
                if cc == c and k in ("better", "worse", "same")]
        placed = sum(n["placed"] - o["placed"] for n, o in both)
        ratios = [n["hpwl"] / o["hpwl"] for n, o in both if n["placed"] == o["placed"] and o["hpwl"] > 0]
        extra = ", ".join("%s %d" % (k, counts[k]) for k in ("new", "gone") if counts[k])
        say("%s: better %d, worse %d, same %d%s; placed %+d; median hpwl ratio %s over %d equal-placed" % (
            c, counts["better"], counts["worse"], counts["same"], (", " + extra) if extra else "",
            placed, "%.2f" % statistics.median(ratios) if ratios else "-", len(ratios)))
    say("seconds: " + ", ".join("%s %.1f (baseline %s)" % (
        c, run["configs"][c]["seconds"],
        "%.1f" % base["configs"][c]["seconds"] if base["configs"].get(c, {}).get("seconds") is not None else "-") for c in sorted(run["configs"])))


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--config", action="append")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args(argv)
    if a.update and (a.names or a.config):
        print("--update needs the whole corpus and every configuration", file=sys.stderr)
        return 2
    configs = {k: v for k, v in CONFIGS.items() if not a.config or k in a.config}
    paths = [p for p in boards() if not a.names or any(n in _name(p) for n in a.names)]
    run = {"configs": {c: {"seconds": 0.0} for c in configs}, "modules": {}}
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.jobs) as pool:
        for name, row, seconds in pool.map(bench_module, [str(p) for p in paths], [configs] * len(paths)):
            if row["parts"] < 2:
                continue
            run["modules"][name] = row
            for c, s in seconds.items():
                run["configs"][c]["seconds"] += s
    for c in run["configs"].values():
        c["seconds"] = round(c["seconds"], 1)
    base = load(BASELINE.read_text()) if BASELINE.exists() else {"configs": {}, "modules": {}}
    if a.names or a.config:        # a partial run is compared only with what it ran
        # The baseline's seconds are for the whole corpus, so a partial run has none to compare with.
        base = {"configs": {c: {"seconds": None} for c in base["configs"] if c in run["configs"]},
                "modules": {m: {k: v for k, v in r.items() if k in ("parts", "hand") or k in run["configs"]}
                            for m, r in base["modules"].items() if m in run["modules"]}}
    report(run, base)
    if a.update:
        BASELINE.write_text(dump(run))
        print("wrote %s" % BASELINE.relative_to(ROOT.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
