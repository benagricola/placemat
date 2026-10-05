"""What a code change does to placement, across the module fixtures.

Every part of each module under fixtures/*/modules/ is released to a bare
place() and resolved under each configuration in CONFIGS. A result is scored
by the run score (placemat's score.py, at the default weights: unplaced
parts, findings by kind, links past their limit, ratsnest crossings and
airwire), and compared with the committed baseline in bench.json: a lower
score beyond the score's noise band is better. Placed, findings, crossings
and half-perimeter wirelength (HPWL) over the nets that are not planes are
shown beside it.

    .venv/bin/python fixtures/bench.py [name ...] [--config NAME] [--jobs N] [--update]

A change that can move a placement runs this before it is committed, puts the
tally lines in the commit message, and commits bench.json with it when a
number changed.

`--arrangements` measures what module arrangements cost, which the corpus
cannot show (it declares none): `bench_arrangements`, its baseline in
bench_arrangements.json (`--arrangements --update` writes it).
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
    """1 when `new` scores better than `old`, -1 worse, 0 within the noise band."""
    from placemat import score
    from placemat.settings import Settings
    return -score.compare(new["measures"], old["measures"], Settings())[0]


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
            if old is None or "measures" not in old:        # a baseline from before the run score
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
BOARD_FIXTURE = ROOT / "fairing" / "core"
"""The whole-board fixture: a six-layer test board of cells and loose parts,
with via fields and zone fills, timed apart from the module tally
(`--board`, `--checks`) since neither shows in a module's own numbers."""
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


class ModuleBoard:
    """A module's benchmark board, declared and not yet resolved: every part
    searched, its size and planes as the benchmark sets them. It pickles, so
    an explore worker can be sent one."""

    def __init__(self, g, overrides: dict, planes: set, size):
        self.g, self.overrides, self.planes, self.size = g, dict(overrides), set(planes), size

    def __call__(self):
        from placemat.layout import Board
        from placemat.settings import Settings
        from placemat.values import CopperLayer, Net, Part
        b = Board(self.g, edge_margin=0.2, keep_going=True, settings=dataclasses.replace(Settings(), **self.overrides))
        b.rect(width=round(self.size[0], 2), height=round(self.size[1], 2))
        for net in sorted(self.planes):
            b.plane(Net(net), [CopperLayer.B], why="benchmark: a net most parts share")
        for fp in sorted(self.g.footprints, key=lambda f: f.inst):
            b.place(Part(fp.inst))          # no rotation given: the search chooses it, as a script that leaves it out
        return b


def _resolve(g, overrides: dict, planes: set, size) -> dict:
    board = ModuleBoard(g, overrides, planes, size)()
    plan = board.resolve()
    placed = {s.item for s in plan.steps if s.placement is not None and s.kind == "part"}
    pads = []
    for fp in g.footprints:
        if fp.inst in placed:
            for p in fp.pads:
                at = plan.occupancy.pad_location(fp.ref, p.number)
                pads.append((p.net, at.x, at.y))
    from placemat import score
    m = score.plan_measures(board, plan)
    return {"placed": len(placed), "findings": len(plan.findings), "hpwl": hpwl(pads, planes),
            "crossings": m["crossings"]["signal"], "score": round(score.total(m, board.settings), 1), "measures": m}


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


def bench_board() -> tuple[float, dict]:
    """The whole-board fixture's generated board, every cell and loose part
    released to a bare place() (as `ModuleBoard` does for a module) and
    resolved. Returns (seconds, {placed, findings}).

    The generated board carries no outline yet (that comes from the write),
    so this borrows the written board's real one: the fixture's own size
    and shape, not an auto-sized square, since how densely items pack
    against a real edge and each other is what drives how often a
    candidate meets another's copper - the whole point of timing this."""
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.values import Cell, Part
    g = read_board(BOARD_FIXTURE / "generated" / "layout.kicad_pcb")
    written = read_board(BOARD_FIXTURE / "layout" / "layout.kicad_pcb")
    b = Board(g, keep_going=True)
    b.outline(written.board_polygon[0], holes=written.board_polygon[1:])
    for name, cell in sorted(g.cells.items()):
        if cell.members:               # a pure parent grouping (all its members in nested cells) has nothing to place
            b.place(Cell(name))
    for fp in sorted(g.footprints, key=lambda f: f.inst):
        if fp.cell is None:
            b.place(Part(fp.inst))
    t0 = time.perf_counter()
    plan = b.resolve()
    dt = time.perf_counter() - t0
    placed = sum(1 for s in plan.steps if s.placement is not None and s.kind in ("part", "cell"))
    return dt, {"placed": placed, "findings": len(plan.findings)}


def bench_checks() -> tuple[float, dict]:
    """The whole-board fixture's written, placed board (with its zone
    fills), `run_checks` timed alone."""
    from placemat.checks import kwargs_from, run_checks
    from placemat.kicad.read import read_board
    from placemat.settings import Settings
    g = read_board(BOARD_FIXTURE / "layout" / "layout.kicad_pcb")
    t0 = time.perf_counter()
    verdicts = run_checks(g, **kwargs_from(Settings()))
    dt = time.perf_counter() - t0
    return dt, {"verdicts": len(verdicts), "failing": sum(1 for v in verdicts if v.ok is False)}


ARRANGED_MODULE = "usb5v"
"""The real module the arrangement bench runs (tests/real_modules.py), with the alternatives of tests/test_arrangement_run.py."""
STAMPS = {"u5a": (20.0, 20.0), "u5b": (70.0, 20.0), "u5c": (20.0, 70.0), "u5d": (70.0, 70.0)}
SHARED = ("VSHUNT", "PP5V", "V3V3", "VBUS_EN")   # the module's nets from the sheet above: the stamps share them, so each links to the rest
# GND is not shared: nearly every pad is on it and the bench declares no plane, so it would pull each stamp onto every other
STAMPED_SIZE = (140.0, 120.0)
ARRANGED_BASELINE = ROOT / "bench_arrangements.json"
FIRM_MARGIN = 5.0          # mm round the firm case's places: room for an arrangement that reaches past its default
ARRANGED_REPEATS = 3         # each resolve of the arrangement bench is timed this many times: a single run varies by 10 to 30 percent


def _resolve_cells(g, outline, on: bool, firm: bool) -> dict:
    """`g`'s cells and loose parts placed and resolved, each cell free or (`firm`) at the centre of its box as `g` stands it, with
    `place.arrangements` `on` or off. `outline(board)` gives the board its outline. The resolve's seconds, run score, items placed,
    and cells standing in an arrangement other than their default."""
    from placemat import score
    from placemat.layout import Board
    from placemat.settings import Settings
    from placemat.values import Cell, Part
    b = Board(g, keep_going=True, settings=dataclasses.replace(Settings(), place_arrangements=on))
    outline(b)
    cells = [name for name, cell in sorted(g.cells.items()) if cell.members]
    for name in cells:
        b.place(Cell(name), at=g.cells[name].box.center) if firm else b.place(Cell(name))
    for fp in sorted(g.footprints, key=lambda f: f.inst):
        if fp.cell is None:
            b.place(Part(fp.inst))
    t0 = time.perf_counter()
    plan = b.resolve()
    dt = time.perf_counter() - t0
    stood = [s for s in plan.steps if s.placement is not None and s.kind in ("part", "cell")]
    return {"s": dt, "score": score.total(score.plan_measures(b, plan), b.settings), "placed": len(stood),
            "taken": sum(1 for s in stood if s.kind == "cell" and s.placement.arrangement), "plan": plan}


def _arranged_case(plain, g, outline, firm: bool, repeats: int) -> tuple:
    """One board resolved three ways: `plain` (no notes) and `g` (the same board with notes) with arrangements off and on, each
    `repeats` times; the seconds are the median. (the row, the last plan with arrangements on)"""
    row = {"cells": sum(1 for c in g.cells.values() if c.members), "offered": sum(1 for c in g.cells.values() if c.offered())}
    for key, geometry, on in (("plain", plain, False), ("off", g, False), ("on", g, True)):
        runs = [_resolve_cells(geometry, outline, on, firm) for _ in range(repeats)]
        r = runs[-1]
        row.update({"%s_s" % key: round(statistics.median(x["s"] for x in runs), 2), "%s_score" % key: round(r["score"], 1)})
        if key != "plain":
            row.update({"%s_placed" % key: r["placed"], "%s_taken" % key: r["taken"]})
    return row, r["plan"]


def _round_places(g):
    """An outline for `g` (a board with stamped places): the rectangle round its footprints plus FIRM_MARGIN, so a cell held at
    its stamped place stands inside it and its arrangements are judged and scored there. (the written board's outline is a
    different size, and would leave every firm cell outside it)"""
    boxes = [fp.box for fp in g.footprints]
    lo_x, lo_y = min(b.left for b in boxes) - FIRM_MARGIN, min(b.top for b in boxes) - FIRM_MARGIN
    hi_x, hi_y = max(b.right for b in boxes) + FIRM_MARGIN, max(b.bottom for b in boxes) + FIRM_MARGIN
    return lambda b: b.outline([(lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y)])


def _own_copper(plan, cell) -> int:
    """The copper shapes `cell` (a CellGeom, arranged or not) holds of its own in `plan`'s occupancy: its tracks and each piece of
    its pours."""
    return sum(1 for s in plan.occupancy._geometry(cell).shapes if s.owner == cell.name and s.kind == "copper")


def bench_arrangements(module: str | None = ARRANGED_MODULE, board=None, outline=None, repeats: int = ARRANGED_REPEATS) -> dict:
    """The cost of arrangements, in cases the module corpus cannot show (it declares none). Seconds and run scores.

    `module`: the real module run with its one layout and with k arrangements (`module_one_s`, `module_k_s`, `module_k`); then its
    fragment stamped four times on one board, the stamps linked by the nets the module takes from the sheet above (`stamped`): the
    plain fragment's stamps, and the noted fragment's with arrangements off and on, with a stamp's own copper shapes in its default
    and in the first arrangement offered (`default_copper`, `arranged_copper`). None skips both.
    `board`: a generated board of stamped cells (default the whole-board fixture's), each cell with two or more members given a
    synthetic note (tests/arrangement_support.synthetic_notes_for), resolved with every cell free (`board`) and at its stamped
    place (`firm`), each as the board without notes and with notes, arrangements off and on. `outline` is the free case's outline as
    points; by default the fixture's written board's. The firm case's outline is the rectangle round the board's places
    (_round_places), so its cells stand inside it. Each resolve runs `repeats` times and its seconds are the median.

    Budgets: a module run at most about k times the default's; a board's resolve at most 25 percent longer than the same board
    without arrangements."""
    import shutil
    import tempfile
    sys.path.insert(0, str(ROOT.parent))
    from placemat.kicad.read import read_board
    from tests.arrangement_support import stamp_fragment_as_cells, synthetic_notes_for
    out = {}
    work = pathlib.Path(tempfile.mkdtemp())
    try:
        if module is not None:
            from tests import real_modules
            from tests.test_arrangement_run import with_alternatives
            frags = {}
            for label, edit in (("one", None), ("k", with_alternatives)):
                t0 = time.perf_counter()
                result, _, frags[label] = real_modules.run(work / label, module, edit=edit)
                out["module_%s_s" % label] = round(time.perf_counter() - t0, 1)
                if label == "k":
                    out["module_k"] = len(json.loads((result.run_dir / "run.json").read_text()).get("arrangements", [1]))
            missing = sorted(set(SHARED) - set(read_board(frags["k"]).nets))
            if missing:                     # a renamed net would leave the stamps unlinked and the search unscored
                raise ValueError("the bench's shared nets are not the module's: %s" % ", ".join(missing))
            stamped = {label: read_board(stamp_fragment_as_cells(frags[label], work / ("stamped_%s.kicad_pcb" % label), STAMPS,
                                                                 SHARED))
                       for label in frags}
            rect = lambda b: b.rect(width=STAMPED_SIZE[0], height=STAMPED_SIZE[1])
            row, plan = _arranged_case(stamped["one"], stamped["k"], rect, False, repeats)
            cell = stamped["k"].cells[sorted(STAMPS)[0]]
            row["default_copper"] = _own_copper(plan, cell)
            row["arranged_copper"] = _own_copper(plan, cell.arranged(cell.offered()[0])) if cell.offered() else None
            out["stamped"] = row
        source = pathlib.Path(board) if board is not None else BOARD_FIXTURE / "generated" / "layout.kicad_pcb"
        pcb = work / "noted" / source.name
        pcb.parent.mkdir()
        for f in source.parent.glob(source.stem + ".*"):
            shutil.copy(f, pcb.parent / f.name)
        plain = read_board(pcb)
        synthetic_notes_for(pcb)
        g = read_board(pcb)
        if outline is None:
            written = read_board(BOARD_FIXTURE / "layout" / "layout.kicad_pcb")
            edge = lambda b: b.outline(written.board_polygon[0], holes=written.board_polygon[1:])
        else:
            edge = lambda b: b.outline(list(outline))
        out["board"] = _arranged_case(plain, g, edge, False, repeats)[0]
        out["firm"] = _arranged_case(plain, g, _round_places(g), True, repeats)[0]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out


def arrangement_changes(run: dict, base: dict) -> list:
    """What moved against the arrangement baseline, as (case, key, baseline, now): every count and score that differs (key None
    for a top-level value). Seconds are machine time and are left out."""
    out = []
    for case in sorted(set(run) | set(base)):
        new, old = run.get(case), base.get(case)
        if not isinstance(new, dict) or not isinstance(old, dict):
            if new != old and not case.endswith("_s"):
                out.append((case, None, old, new))
            continue
        for key in sorted(set(new) | set(old)):
            if not key.endswith("_s") and new.get(key) != old.get(key):
                out.append((case, key, old.get(key), new.get(key)))
    return out


def _line(c, m, new, old) -> str:
    def pair(key, fmt):
        a, b = old[key], new[key]
        return (fmt % b) if a == b else ((fmt + " -> " + fmt) % (a, b))
    return "%-8s %-28s score %s: placed %s, findings %s, crossings %s, hpwl %s" % (
        c, m, pair("score", "%.1f"), pair("placed", "%d"), pair("findings", "%d"), pair("crossings", "%d"),
        pair("hpwl", "%.1f"))


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


def explore_tally(rows: dict) -> dict:
    """How many modules the best of their variants beat the plain placement
    on (by the run score), how many it did not, and how many it placed
    more parts on."""
    better = sum(1 for r in rows.values() if r["best"] < r["baseline"] - 1e-9)
    placed = sum(1 for r in rows.values() if r["unplaced"][1] < r["unplaced"][0])
    return {"better": better, "same": len(rows) - better, "placed": placed}


def explore_bench(paths, configs: dict, n: int, jobs: int) -> None:
    """--explore N: each module's plain placement against the best of N
    fixed seeds, every part in focus, per config; module by module, the
    variants of one module spread over `jobs` workers."""
    from placemat.explore import explore, focus_keys
    from placemat.kicad.read import read_board
    for c, overrides in configs.items():
        rows, spent, tried = {}, 0.0, 0
        for path in paths:
            g = read_board(path)
            if len(g.footprints) < 2:
                continue
            make = ModuleBoard(g, overrides, _planes(g), _size(g, any(path.parents[1].glob("*_layout.py"))))
            focus = focus_keys(make())
            if not focus:
                continue
            t0 = time.perf_counter()
            r = explore(make, focus, 0, jobs, seeds=range(n))
            dt = time.perf_counter() - t0
            spent, tried = spent + dt, tried + r.tried
            unplaced = [sum(m["unplaced"].values()) for m in (r.baseline_measures, r.best_measures)]
            rows[_name(path)] = {"baseline": r.baseline, "best": r.best, "seed": r.best_seed, "unplaced": unplaced}
            print("%-8s %-28s score %.1f -> %.1f  seed %d  %.1f s" % (c, _name(path), r.baseline, r.best,
                                                                    r.best_seed, dt), flush=True)
        t = explore_tally(rows)
        print("%s: explore %d seeds: better %d, same %d of %d modules; more placed on %d; %.2f s per variant" % (
            c, n, t["better"], t["same"], len(rows), t["placed"], spent / max(1, tried)), flush=True)


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--config", action="append")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--explore", type=int, metavar="N",
                    help="the best of N explore seeds per module against its plain placement, instead of the tally")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="a setting for every configuration, e.g. score_crossing=1 (a measurement, never --update)")
    ap.add_argument("--out", help="write this run's results here, as bench.json is written")
    ap.add_argument("--board", action="store_true", help="the whole-board fixture's placement, timed alone")
    ap.add_argument("--checks", action="store_true", help="the whole-board fixture's checks, timed alone")
    ap.add_argument("--arrangements", action="store_true",
                    help="the cost of arrangements: a module run with k, its fragment stamped four times, the whole board and a "
                         "board of firm cells with synthetic notes, timed without notes and with arrangements off and on")
    a = ap.parse_args(argv)
    if a.arrangements:
        run = bench_arrangements()
        print(json.dumps(run, indent=1, sort_keys=True))
        if ARRANGED_BASELINE.exists():
            for case, key, old, new in arrangement_changes(run, json.loads(ARRANGED_BASELINE.read_text())):
                print("%s%s: %s -> %s" % (case, " " + key if key else "", old, new))
        if a.out:
            pathlib.Path(a.out).write_text(json.dumps(run, indent=1, sort_keys=True) + "\n")
        if a.update:
            ARRANGED_BASELINE.write_text(json.dumps(run, indent=1, sort_keys=True) + "\n")
            print("wrote %s" % ARRANGED_BASELINE.relative_to(ROOT.parent))
        return 0
    if a.board or a.checks:
        if a.board:
            dt, row = bench_board()
            print("board: %.1f s, placed %d, findings %d" % (dt, row["placed"], row["findings"]))
        if a.checks:
            dt, row = bench_checks()
            print("checks: %.1f s, %d verdicts, %d failing" % (dt, row["verdicts"], row["failing"]))
        return 0
    if a.update and (a.names or a.config or a.set):
        print("--update needs the whole corpus, every configuration and the settings as they are", file=sys.stderr)
        return 2
    extra = {}
    for item in a.set:
        from placemat.settings import Settings
        name, _, value = item.partition("=")
        extra[name] = type(getattr(Settings(), name))(value)
    configs = {k: {**v, **extra} for k, v in CONFIGS.items() if not a.config or k in a.config}
    paths = [p for p in boards() if not a.names or any(n in _name(p) for n in a.names)]
    if a.explore:
        explore_bench(paths, configs, a.explore, a.jobs)
        return 0
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
    if a.out:
        pathlib.Path(a.out).write_text(dump(run))
    if a.update:
        BASELINE.write_text(dump(run))
        print("wrote %s" % BASELINE.relative_to(ROOT.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
