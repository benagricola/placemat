# Benchmark and pocket fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A committed benchmark that says, for any code change, which fixture modules placed better or worse; then a pocket fallback for seeded items whose scan fails, measured with it.

**Architecture:** `fixtures/bench.py` holds pure scoring and baseline logic (tested without KiCad) and a runner that reads each fixture board with pcbnew, releases its parts, resolves per configuration in a process pool, and diffs against `fixtures/bench.json`. The fallback is a branch at the end of the seeded path in `Board._settle`, reusing `pockets()` and `scan()`.

**Tech Stack:** Python 3, pytest, pcbnew (runner only), `concurrent.futures`.

**Spec:** `docs/superpowers/specs/2026-09-22-bench-and-pocket-fallback-design.md`

## Global Constraints

- Zero runtime dependencies; pcbnew only in the runner half of `bench.py` and under `src/placemat/kicad/`.
- Determinism: the same code writes the same `bench.json` bytes, apart from the per-configuration seconds.
- No module, part, board or component-type names in `src/`, the skill or migrations; examples stay generic.
- Plain ASCII in everything written. Commit messages carry no attribution lines.
- Verdict noise: 1% on HPWL, the value of `report.AIRWIRE_NOISE`.
- Tests run with `.venv/bin/python -m pytest -q > $S/out.txt 2>&1; echo $?` (never piped, so the exit code is real).

---

### Task 1: Scoring and baseline logic

**Files:**
- Create: `fixtures/bench.py` (pure half only in this task)
- Test: `tests/test_bench.py`

**Interfaces:**
- Produces:
  - `hpwl(pads: list[tuple[str, float, float]], skip: set) -> float` - sum over nets of box width + height, nets in `skip` and single-pad nets ignored, rounded to 0.1.
  - `verdict(new: dict, old: dict) -> int` - rows are `{"placed": int, "findings": int, "hpwl": float}`; 1 better, -1 worse, 0 same.
  - `diff(run: dict, base: dict) -> list[tuple[str, str, str]]` - `(config, module, kind)` with kind in `better | worse | same | new | gone`, sorted by module then config; every row present in both is listed, `same` included, because the tally counts it.
  - `tally(changes) -> dict[str, dict[str, int]]` - per config, counts per kind.
  - `dump(results: dict) -> str`, `load(text: str) -> dict`. `results = {"configs": {name: {"seconds": float}}, "modules": {name: {"parts": int, "hand": float | None, <config>: row}}}`.

- [ ] **Step 1: Write the failing tests**

```python
"""The benchmark's scoring and baseline, without KiCad."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "bench", pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def row(placed, findings=0, hpwl=100.0):
    return {"placed": placed, "findings": findings, "hpwl": hpwl}


def test_more_placed_wins_over_findings_and_wire():
    assert bench.verdict(row(5, 3, 900.0), row(4, 0, 10.0)) == 1
    assert bench.verdict(row(4, 0, 10.0), row(5, 3, 900.0)) == -1


def test_fewer_findings_wins_when_as_many_are_placed():
    assert bench.verdict(row(5, 1, 900.0), row(5, 2, 10.0)) == 1


def test_wire_decides_last_and_one_percent_is_the_same():
    assert bench.verdict(row(5, 0, 98.0), row(5, 0, 100.0)) == 1
    assert bench.verdict(row(5, 0, 102.0), row(5, 0, 100.0)) == -1
    assert bench.verdict(row(5, 0, 100.9), row(5, 0, 100.0)) == 0
    assert bench.verdict(row(5, 0, 99.1), row(5, 0, 100.0)) == 0


def _results(**modules):
    return {"configs": {"default": {"seconds": 1.0}},
            "modules": {m: {"parts": 5, "hand": None, "default": r} for m, r in modules.items()}}


def test_diff_names_new_and_gone_rows_and_tally_counts_them():
    base = _results(a=row(4), b=row(5), c=row(5))
    run = _results(a=row(5), b=row(5, hpwl=200.0), d=row(5))
    changes = bench.diff(run, base)
    assert changes == [("default", "a", "better"), ("default", "b", "worse"),
                       ("default", "c", "gone"), ("default", "d", "new")]
    assert bench.tally(changes) == {"default": {"better": 1, "worse": 1, "same": 0, "new": 1, "gone": 1}}


def test_a_baseline_written_twice_is_the_same_bytes_and_reads_back():
    r = _results(b=row(5), a=row(4, 1, 12.3))
    text = bench.dump(r)
    assert text == bench.dump(bench.load(text))
    assert bench.load(text) == r
    assert text.index('"a"') < text.index('"b"')
    assert len([l for l in text.splitlines() if l.lstrip().startswith('"a"')]) == 1


def test_hpwl_sums_each_nets_box_and_skips_planes_and_lone_pads():
    pads = [("N1", 0, 0), ("N1", 3, 4), ("N1", 1, 1), ("GND", 0, 0), ("GND", 50, 50), ("LONE", 9, 9)]
    assert bench.hpwl(pads, skip={"GND"}) == 7.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bench.py -q`
Expected: FAIL - `fixtures/bench.py` does not exist.

- [ ] **Step 3: Implement the pure half of `fixtures/bench.py`**

```python
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

import json

CONFIGS = {"default": {}, "solve": {"solve_enabled": True}}
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
```

The printer (Task 2) shows only rows whose numbers differ.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bench.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add fixtures/bench.py tests/test_bench.py
git commit -m "Benchmark scoring and baseline format, pure"
```

---

### Task 2: The runner, and the baseline before any change

**Files:**
- Modify: `fixtures/bench.py` (append the runner)
- Delete: `fixtures/presolve_bench.py`
- Create: `fixtures/bench.json` (generated)
- Modify: `README.md` (a Benchmark paragraph after the install block)

**Interfaces:**
- Consumes: `hpwl`, `diff`, `tally`, `dump`, `load`, `CONFIGS` from Task 1.
- Produces: `bench_module(path: str, configs: dict) -> tuple[str, dict, dict]` returning `(name, module_row, seconds_by_config)`; `main(argv) -> int`.

- [ ] **Step 1: Append the runner**

Ported from `presolve_bench.py` (its setup is the spec's "Setup per module"); the monkeypatch and the four modes go.

```python
import argparse
import concurrent.futures
import dataclasses
import math
import os
import pathlib
import statistics
import sys
import time

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


def bench_module(path: str, configs: dict):
    from placemat.kicad.read import read_board
    path = pathlib.Path(path)
    g = read_board(path)
    hand = any(path.parents[1].glob("*_layout.py"))
    planes = _planes(g)
    size = _size(g, hand)
    row = {"parts": len(g.footprints),
           "hand": hpwl([(p.net, p.box.center.x, p.box.center.y) for fp in g.footprints for p in fp.pads],
                        planes) if hand else None}
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
        "%.1f" % base["configs"][c]["seconds"] if c in base["configs"] else "-") for c in sorted(run["configs"])))


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--config", action="append")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args(argv)
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
        base = {"configs": {c: v for c, v in base["configs"].items() if c in run["configs"]},
                "modules": {m: {k: v for k, v in r.items() if k in ("parts", "hand") or k in run["configs"]}
                            for m, r in base["modules"].items() if m in run["modules"]}}
    report(run, base)
    if a.update:
        if a.names or a.config:
            print("--update needs the whole corpus and every configuration", file=sys.stderr)
            return 2
        BASELINE.write_text(dump(run))
        print("wrote %s" % BASELINE.relative_to(ROOT.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

(Move the new imports to the top of the file beside `import json`; `placemat` imports stay inside the functions so Task 1's tests load the module without pcbnew.)

- [ ] **Step 2: Check it against the old benchmark**

Run: `.venv/bin/python fixtures/bench.py --update`, then read `fixtures/bench.json`.
Expected: 32 modules; each module's `default` placed and HPWL equal to `presolve_bench.py`'s `seed` column and `solve` equal to its `solve` column (the saved `bench4.txt` in the session scratchpad), HPWL to 0.1.

- [ ] **Step 3: Check it is deterministic**

Run: `cp fixtures/bench.json $S/b1.json; .venv/bin/python fixtures/bench.py --update; diff <(grep -v seconds $S/b1.json) <(grep -v seconds fixtures/bench.json)`
Expected: no output; the report's tally reads `same 32` for both configurations.

- [ ] **Step 4: Remove the old benchmark, add the README paragraph**

`git rm fixtures/presolve_bench.py`. In `README.md`, after the install block:

```markdown
`fixtures/` holds real modules with the libraries that build them.
`uv run python fixtures/bench.py` places each of them from scratch under each
configuration and compares the result with the committed `fixtures/bench.json`:
more parts placed, then fewer findings, then shorter wire. A change that can
move a placement runs it first, puts its tally lines in the commit message, and
commits the rewritten baseline (`--update`) with it.
```

- [ ] **Step 5: Run the suite, commit**

Run: `.venv/bin/python -m pytest -q > $S/out.txt 2>&1; echo $?` - expect 0.

```bash
git add fixtures/bench.py fixtures/bench.json README.md
git commit -m "The fixture benchmark and its baseline, before the pocket fallback"
```

---

### Task 3: The pocket fallback

**Files:**
- Modify: `src/placemat/layout.py` (`Plan`: add `pocketed`; `_settle`: the branch after the seeded scan; a new `_seeded_pocket`)
- Test: `tests/test_seeded_pocket.py`

**Interfaces:**
- Consumes: `pockets(occ, width, height, face, step)` and `scan(occ, item, hint, radius, step, rotations, clearance, score=)` from `placer.py`.
- Produces: `Plan.pocketed: list[str]` (item keys, in placement order); `Board._seeded_pocket(occ, i, plan, clr, hint, score, rotations) -> tuple[Step | None, int]` - the step when a pocket took the item, else `None`, and how many pockets were tried.

- [ ] **Step 1: Write the failing tests**

```python
"""A seeded item whose scan finds nothing takes the nearest pocket. Pure."""
import dataclasses

import placemat.layout as layout
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Near, Part
from tests.fixtures import board_geometry, footprint


def _board(u_w=6.0, u_h=6.0, solve=False):
    """j1 on the west edge; a wall east of it leaves no room for u1 near j1.
    Past the wall a narrow gap, a second wall, then a wide gap."""
    fps = [footprint("J1", 3, 10, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("K1", 13, 10, w=16, h=17, inst="k1", nets=("K1A", "K1B")),
           footprint("K2", 35, 10, w=10, h=17, inst="k2", nets=("K2A", "K2B")),
           footprint("U1", 50, 10, w=u_w, h=u_h, inst="u1", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=20), edge_margin=0.5, keep_going=True,
              settings=dataclasses.replace(Settings(), solve_enabled=solve))
    b.place(Part("j1"), at=Location(3, 10))
    b.place(Part("k1"), at=Location(13, 10))
    b.place(Part("k2"), at=Location(35, 10))
    return b


def _step(plan, key):
    return next(s for s in plan.steps if s.item == key)


def test_a_seeded_part_with_no_room_by_its_connections_takes_a_pocket():
    b = _board()
    b.place(Part("u1"))
    plan = b.resolve()
    s = _step(plan, "u1")
    assert s.placement is not None
    assert "took the pocket" in s.note and "mm from the seed" in s.note
    assert "no legal spot within" in s.note
    assert not [f for f in plan.findings if f.startswith("u1")]
    assert plan.pocketed == ["u1"]


def test_the_pocket_nearer_the_seed_wins_over_a_bigger_one():
    b = _board()
    b.place(Part("u1"))
    x = _step(b.resolve(), "u1").placement.location.x
    assert 21.0 < x < 30.0, x


def test_an_explicit_near_that_fails_stays_unplaced():
    b = _board()
    b.place(Part("u1"), at=Near(Location(3, 15)))
    plan = b.resolve()
    s = _step(plan, "u1")
    assert s.placement is None and s.note.startswith("UNPLACED")
    assert any(f.startswith("u1: no legal location within") for f in plan.findings)
    assert plan.pocketed == []


def test_with_no_pocket_the_part_is_unplaced_and_the_finding_says_so(monkeypatch):
    monkeypatch.setattr(layout, "pockets", lambda *a, **k: [])
    b = _board()
    b.place(Part("u1"))
    plan = b.resolve()
    assert _step(plan, "u1").placement is None
    assert any(f.startswith("u1: no legal location within") and f.endswith("; no pocket took it (0 tried)")
               for f in plan.findings)


def test_a_dropped_solve_hint_then_a_failed_seed_ends_in_a_pocket(monkeypatch):
    monkeypatch.setattr(Board, "_global_hints", lambda self, occ, placed, plan: {"u1": Location(10, 10)})
    b = _board(solve=True)
    b.place(Part("u1"))
    s = _step(b.resolve(), "u1")
    assert s.placement is not None
    assert "global solve's hint" in s.note and "took the pocket" in s.note


def test_a_seeded_part_that_fits_by_its_connections_is_where_it_was():
    """No wall: the seeded scan succeeds and the fallback never runs."""
    fps = [footprint("J1", 3, 10, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("U1", 50, 10, w=6, h=6, inst="u1", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=20), edge_margin=0.5)
    b.place(Part("j1"), at=Location(3, 10))
    b.place(Part("u1"))
    plan = b.resolve()
    assert "pocket" not in _step(plan, "u1").note and plan.pocketed == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_seeded_pocket.py -q`
Expected: the first five FAIL (u1 UNPLACED; `Plan` has no `pocketed`), the last FAILs on `pocketed` only. If the first test's u1 is placed without the fallback, the wall geometry is wrong: widen K1 until the plain scan fails, and re-run before going on.

- [ ] **Step 3: Implement**

In `Plan`, after `solve`:

```python
    pocketed: list = field(default_factory=list)                  # seeded items whose scan failed and took a pocket
```

In `_settle`, replace the final `if result.chosen is None:` block (the one that appends "no legal location within") with:

```python
        if result.chosen is None:
            blame = "no legal location within %.1f mm of %s (%s)" % (radius, _loc(hint.location), _blame_text(result))
            if i.near is None:
                step, tried = self._seeded_pocket(occ, i, plan, clr, hint, score,
                                                  i.rotations or (i.rotation,),
                                                  "no legal spot within %.1f mm of the %s (%s)" % (
                                                      radius, seeded or "seed", _blame_text(result)))
                if step is not None:
                    return step
                blame += "; no pocket took it (%d tried)" % tried
            plan.findings.append("%s: %s" % (i.key, blame))
            return Step(i.key, i.kind, None if i.freedom.decided else i.priority, None, 0.0, "UNPLACED: " + "; ".join(result.reasons.values()), i.why, freedom=i.freedom,
                    rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None)
```

The solve's own fallback above this block is untouched: it re-enters `_settle` with `solve=False`, which reaches this block. Its note wraps the one returned here, so the pocket note must not be recorded twice - `plan.pocketed` is appended in `_seeded_pocket`, which runs once.

Beside `_settle_in_pocket`:

```python
    def _seeded_pocket(self, occ: Occupancy, i: PlaceIntent, plan: Plan, clr, hint: Placement, score,
                       rotations, why: str):
        """A seeded item whose scan found nothing: the free pocket nearest the
        seed that it fits, scanned with the same link score, so it lands at
        the end nearest what it connects to. None when no pocket takes it."""
        seen = []
        for rot in rotations:
            env = occ.body_box(i.item, Placement(Location(0.0, 0.0), rot, i.face))
            for pocket in pockets(occ, env.width, env.height, i.face, step=max(i.step, 0.5)):
                if pocket.box not in [p.box for p, _ in seen]:
                    seen.append((pocket, rot))
        at = hint.location
        def gap(p):
            b = p.box
            dx = max(b.left - at.x, 0.0, at.x - b.right)
            dy = max(b.top - at.y, 0.0, at.y - b.bottom)
            return math.hypot(dx, dy)
        order = sorted(range(len(seen)), key=lambda k: (round(gap(seen[k][0]), 6), k))
        for k in order:
            pocket, rot = seen[k]
            start = box_centered_placement(occ, i.item, pocket.box.center, rot, i.face)
            result = scan(occ, i.item, start, max(pocket.box.width, pocket.box.height) / 2, i.step,
                          tuple(rotations), clr, score=score)
            if result.chosen is not None:
                plan.pocketed.append(i.key)
                note = "%s; took the pocket %.1f x %.1f at (%.1f, %.1f), %.1f mm from the seed" % (
                    why, pocket.box.width, pocket.box.height, pocket.box.center.x, pocket.box.center.y,
                    gap(pocket))
                return Step(i.key, i.kind, None if i.freedom.decided else i.priority, result.chosen,
                            result.moved_mm, note, i.why, freedom=i.freedom,
                            rank=self._rank_of.get(i.key), rank_of=len(self._rank_of) or None), len(seen)
        return None, len(seen)
```

Check `math` is imported in `layout.py`; add it if not.

- [ ] **Step 4: Run to verify they pass, then the suite**

Run: `.venv/bin/python -m pytest tests/test_seeded_pocket.py -q` - expect 6 passed.
Run: `.venv/bin/python -m pytest -q > $S/out.txt 2>&1; echo $?` - expect 0. A failure elsewhere means an existing board had a seeded item that failed its scan; read the test, and change its expectation only if the pocket placement is legal and the test was asserting the old UNPLACED outcome.

- [ ] **Step 5: Measure nearest-first against biggest-first**

Run: `.venv/bin/python fixtures/bench.py > $S/nearest.txt`. Temporarily change the sort key in `_seeded_pocket` to `lambda k: k` (biggest first, the order `pockets()` returns) and run again into `$S/biggest.txt`; revert. Compare the two `default:` tally lines.
Expected: nearest-first is kept unless biggest-first has more better and fewer worse. If biggest-first wins, keep it, change the docstring and note, and change `test_the_pocket_nearer_the_seed_wins_over_a_bigger_one` to assert the new order - and bring the result back to the user before committing, because it contradicts the spec.

- [ ] **Step 6: Update the baseline, commit with the tally**

Run: `.venv/bin/python fixtures/bench.py --update > $S/final.txt`.

```bash
git add src/placemat/layout.py tests/test_seeded_pocket.py fixtures/bench.json
git commit -F - <<'EOF'
A seeded item whose scan finds nothing takes the nearest pocket

<one paragraph: what changed>

Benchmark against the previous baseline:
<the default: and solve: tally lines from $S/final.txt>
Nearest-first against biggest-first: <the two default: lines>
EOF
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"   # must print nothing
```

---

### Task 4: Reporting, docs, the solve comparison, 0.21.0

**Files:**
- Modify: `src/placemat/runner.py:252-257` (metrics and a line)
- Modify: `skills/placemat/SKILL.md`, `skills/placemat/references/api.md`, `skills/placemat/references/migration.md`
- Modify: `src/placemat/__init__.py`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (0.20.0 -> 0.21.0)
- Test: `tests/test_seeded_pocket.py` (one more test)

**Interfaces:**
- Consumes: `Plan.pocketed` from Task 3.
- Produces: `metrics["pocketed"]: int` in the run record, only when nonzero.

- [ ] **Step 1: Write the failing test**

The runner's metrics dict is built inline, so extract it: a function `run_metrics(plan, n_place, n_copper, extent_metrics) -> dict` in `runner.py`, used where the dict is built today.

```python
def test_the_run_metrics_count_pocketed_items():
    from placemat.runner import run_metrics
    b = _board()
    b.place(Part("u1"))
    plan = b.resolve()
    m = run_metrics(plan, 4, 0, {})
    assert m["pocketed"] == 1
    assert m["placed"] == 4 and m["findings"] == len(plan.findings)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_seeded_pocket.py -q` - expect ImportError on `run_metrics`.

- [ ] **Step 3: Implement**

In `runner.py`:

```python
def run_metrics(plan, n_place: int, n_copper: int, extent_metrics: dict) -> dict:
    metrics = {"board": [round(plan.outline.width, 3), round(plan.outline.height, 3)] if plan.outline else None,
               "findings": len(plan.findings), "placed": n_place, "copper_ops": n_copper,
               "seeded_by_net": dict(plan.seeded_by_net), **extent_metrics}
    if plan.solve:
        metrics["solve"] = dict(plan.solve)
    if plan.pocketed:
        metrics["pocketed"] = len(plan.pocketed)
    return metrics
```

and at the old site, `metrics = run_metrics(plan, n_place, n_copper, extent_metrics)`, preceded by:

```python
        if plan.pocketed:
            say("pocketed", "%d item(s) had no room by what they connect to and took a pocket: %s" % (
                len(plan.pocketed), ", ".join(plan.pocketed[:8]) + (", ..." if len(plan.pocketed) > 8 else "")))
```

Run the file's tests and the suite; expect 0.

- [ ] **Step 4: The solve comparison**

Read the `default` and `solve` columns of `fixtures/bench.json` and count, per module, `verdict(solve, default)`:

```bash
.venv/bin/python - <<'EOF'
import importlib.util, json
s = importlib.util.spec_from_file_location("bench", "fixtures/bench.py"); b = importlib.util.module_from_spec(s); s.loader.exec_module(b)
mods = json.load(open("fixtures/bench.json"))["modules"]
v = [b.verdict(r["solve"], r["default"]) for r in mods.values()]
print("solve against default: better %d, worse %d, same %d" % (v.count(1), v.count(-1), v.count(0)))
EOF
```

Record that line, with the date, in `api.md` under the `[solve]` settings table.

- [ ] **Step 5: Docs**

- `migration.md`, new `## To 0.21` at the top: "A part or cell that was UNPLACED because its seeded scan found no legal spot now takes the free pocket nearest what it connects to, and parts placed after it can move. A board that placed every part is unchanged. `metrics.pocketed` counts these, and the run prints them."
- `SKILL.md`, beside the existing note on "nothing it connects to is placed": "A step noting `took the pocket` had no room by what it connects to: make room there, or give it a `Near`."
- `api.md`: the `pocketed` metric in the run-record metrics list; the solve line from Step 4.
- Version 0.21.0 in the three files.

- [ ] **Step 6: Suite, bench, commit**

Run: `.venv/bin/python -m pytest -q > $S/out.txt 2>&1; echo $?` - expect 0.
Run: `.venv/bin/python fixtures/bench.py` - expect `same` on every row (reporting only).

```bash
git add -A src skills .claude-plugin tests
git commit -m "Plugin 0.21.0: a seeded item with no room takes the nearest pocket; the benchmark says what changed"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"   # must print nothing
```

Then save the practice (run the benchmark before committing a placement change; tally in the message) to memory and to cave.
