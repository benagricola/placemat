# Cleanup Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the searched tier, move and swap plain searched parts to lower their wire length and link cost, legally, then plan the rest of the copper.

**Architecture:** A pure-ish module `src/placemat/cleanup.py` holds the objective, the global move and the swap, working on an `Occupancy` and a list of movable footprints. `Board.resolve()` chooses the movable parts, calls it between `place_ranked(RANK_CELL, RANK_LOOSE)` and `_plan_copper(... other_copper ...)`, and writes the moves back into the plan's steps.

**Tech Stack:** Python 3, pytest; `placer.scan` for the scored, legal search.

**Spec:** `docs/superpowers/specs/2026-09-23-cleanup-pass-design.md`

## Global Constraints

- Zero runtime dependencies; no pcbnew outside `kicad/`.
- Deterministic: sorted iteration, no randomness; same inputs, same bytes.
- No module, part, board or component-type names in `src/`, the skill or migrations.
- Plain ASCII. Commit messages carry no attribution lines, and each carries the benchmark tally.
- A move is legal by `occ.legal` and taken only when the cost drops by more than 1e-6 and no limited link ends over its limit and longer.
- Tests run as `.venv/bin/python -m pytest -q > $S/out.txt 2>&1; echo $?`.

---

### Task 1: The cleanup module

**Files:**
- Create: `src/placemat/cleanup.py`
- Test: `tests/test_cleanup.py`

**Interfaces:**
- Produces: `cleanup(occ, movable: dict[str, Footprint], pins: dict[str, list[tuple[str, str]]], links: list, clearance, passes: int, radius: float, step: float) -> CleanupResult`, where `movable` maps step key to footprint, `pins` maps each pulling net to its placed `(ref, pad number)` pins, and `CleanupResult` has `moves: dict[key, (Placement, Placement, float, float)]` (from, to, cost before, cost after), `swaps: list[(key, key)]`, `passes: int`, `cost_before: float`, `cost_after: float`.

- [ ] **Step 1: Write the failing tests** - pure, driving `cleanup()` directly on an `Occupancy` built from `tests.fixtures.board_geometry` with parts committed where a test puts them:

```python
"""The cleanup pass on its own: moves and swaps that lower wire and link cost."""
from placemat.cleanup import cleanup
from placemat.links import Link
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint


def _occ(fps, at, width=60, height=30):
    g = board_geometry(fps, width=width, height=height)
    occ = Occupancy(g, 0.5, board_box=g.outline_box)
    for fp in fps:
        occ.commit(fp, Placement(Location(*at[fp.inst]), 0.0, Face.FRONT))
    return g, occ


def _pins(g, placed_refs, quiet=()):
    pins = {}
    for fp in g.footprints:
        if fp.ref in placed_refs:
            for p in fp.pads:
                if p.net and p.net not in quiet:
                    pins.setdefault(p.net, []).append((fp.ref, p.number))
    return {n: v for n, v in pins.items() if len(v) > 1}


def test_a_part_left_far_from_its_connections_moves_toward_them():
    fps = [footprint("A1", 10, 15, inst="a1", nets=("N1", "N2")),
           footprint("B1", 14, 15, inst="b1", nets=("N2", "N3")),
           footprint("C1", 50, 15, inst="c1", nets=("N3", "N4"))]
    g, occ = _occ(fps, {"a1": (10, 15), "b1": (40, 15), "c1": (50, 15)})
    r = cleanup(occ, {"b1": fps[1]}, _pins(g, {"A1", "B1", "C1"}), [], None, 3, 3.0, 0.25)
    frm, to, c0, c1 = r.moves["b1"]
    assert c1 < c0 and to.location.x < frm.location.x
    assert occ.legal(fps[1], to) is None


def test_two_identical_parts_whose_connections_cross_swap():
    fps = [footprint("J1", 5, 5, inst="j1", nets=("P", "GND")), footprint("J2", 5, 25, inst="j2", nets=("Q", "GND")),
           footprint("R1", 30, 25, inst="r1", nets=("P", "X")), footprint("R2", 30, 5, inst="r2", nets=("Q", "Y"))]
    g, occ = _occ(fps, {"j1": (5, 5), "j2": (5, 25), "r1": (30, 25), "r2": (30, 5)})
    r = cleanup(occ, {"r1": fps[2], "r2": fps[3]}, _pins(g, {"J1", "J2", "R1", "R2"}, quiet={"GND"}), [], None, 3, 0.5, 0.25)
    assert r.swaps == [("r1", "r2")]


def test_a_move_that_would_push_a_link_past_its_limit_is_refused():
    fps = [footprint("A1", 10, 15, inst="a1", nets=("N1", "N2")),
           footprint("B1", 14, 15, inst="b1", nets=("N2", "N3")),
           footprint("C1", 50, 15, inst="c1", nets=("N3", "N4")),
           footprint("D1", 30, 15, inst="d1", nets=("N5", "N6"))]
    g, occ = _occ(fps, {"a1": (10, 15), "b1": (28, 15), "c1": (50, 15), "d1": (30, 20)})
    link = Link(("B1", "2"), ("D1", "1"), 1, 3.0, "keep b1 by d1", None, None)
    r = cleanup(occ, {"b1": fps[1]}, _pins(g, {"A1", "B1", "C1", "D1"}), [link], None, 3, 3.0, 0.25)
    to = r.moves["b1"][1] if "b1" in r.moves else Placement(Location(28, 15), 0.0, Face.FRONT)
    pads = occ.candidate_pad_locations(fps[1], to)
    assert pads[("B1", "2")].distance(occ.pad_location("D1", "1")) <= 3.0 + 1e-9 or "b1" not in r.moves


def test_the_pass_is_the_same_twice():
    def run():
        fps = [footprint("A%d" % k, 5 + 6 * k, 15, inst="a%d" % k, nets=("N%d" % k, "N%d" % (k + 1))) for k in range(6)]
        at = {"a%d" % k: (5 + 9 * ((k * 7) % 6), 15) for k in range(6)}
        g, occ = _occ(fps, at)
        r = cleanup(occ, {fp.inst: fp for fp in fps}, _pins(g, {fp.ref for fp in fps}), [], None, 3, 3.0, 0.25)
        return sorted((k, v[1]) for k, v in r.moves.items()), r.swaps
    assert run() == run()
```

(Check `Link`'s constructor and `board_geometry`'s outline attribute when writing this; adjust the helpers, not the assertions.)

- [ ] **Step 2: Run to verify they fail** - ImportError on `placemat.cleanup`.

- [ ] **Step 3: Implement** by porting the measured prototype: `pads_at` (pad offsets per rotation and face, shifted), `hp(nets, override)`, `cost(keys, nets, override)` = HPWL plus `weight * length` for each link on one of the parts, `links_ok(keys, override)`, then per pass the global move (optimal region = median of the other pins' box edges per net; `scan()` with `score=cost` around the shifted origin and around the current placement, at the part's rotation and face, within `radius` at `step`) and the swaps within signature groups (courtyard width and height rounded to 0.001 mm, pad count, face), using `occ.pending` to exclude the partner while testing the first half of a swap and undoing the first commit when the second is illegal.

- [ ] **Step 4: Run to verify they pass**, then the suite.

- [ ] **Step 5: Commit** (`Cleanup pass: moves and swaps that lower wire and link cost, pure`).

---

### Task 2: In the resolve

**Files:**
- Modify: `src/placemat/layout.py` (`Plan.cleanup`, `_cleanup_movable`, the call in `resolve()`)
- Modify: `src/placemat/settings.py` (`cleanup_enabled=True`, `cleanup_passes=3`, `cleanup_radius=3.0`, `cleanup_step=0.25`, and the `[cleanup]` table in the loader beside `[solve]`)
- Modify: `src/placemat/runner.py` (`run_metrics`: `metrics["cleanup"]`)
- Test: `tests/test_cleanup_wiring.py`

**Interfaces:**
- Consumes: `cleanup()` from Task 1.
- Produces: `Plan.cleanup: dict` (`moves`, `swaps`, `passes`, `cost_before`, `cost_after`); `Board._cleanup_movable(plan) -> dict[key, Footprint]`.

- [ ] **Step 1: Write the failing tests**:
  1. a searched part placed early, whose neighbours are placed after it, ends nearer them with `cleanup_enabled` and its step note contains `cleanup: moved`;
  2. the same part with `at=Near(...)`, with a label, or named by another item's `Near(PadRef(...))`, does not move; a fixed part and a block member do not move;
  3. with `cleanup_enabled=False` the steps' placements equal those of the code before (compare against a run with the pass monkeypatched out);
  4. `plan.cleanup["moves"]` counts the moves, and `run_metrics(plan, ...)["cleanup"]` carries it;
  5. a `board.track()` (or plane stitch) planned between a moved part and a fixed one reaches the moved part's pad where it ended.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** `_cleanup_movable`: steps of kind `part`, placed, `Freedom.SEARCHED`, whose intent passes `_solvable`, minus every ref named by a label, by a placement reference (`near`, `at`, `center`, `FreeSpot.near`) of another intent, by a row or ring, or by a keepout's anchor. Pins: placed refs only, nets not in `_plane_nets() | _free_nets`, at least two pins. Call between the searched tier and `other_copper`; for each move, set the step's `placement` and `moved_mm` stays the search's; append the note. Also re-run `_report_links` after (it already runs later) - no change needed.
- [ ] **Step 4: Run the tests and the suite; run `fixtures/bench.py`.** Expect `default` better on most modules and worse on none; explain any worse row before going on.
- [ ] **Step 5: Measure the core board** (the scratch copy of the fairing core, cached generation) - HPWL, link length, links over limit, findings, resolve time - with the pass on and off, and put the numbers in the commit.
- [ ] **Step 6: Commit** with the tally and the core numbers; `fixtures/bench.json` updated.

---

### Task 3: Docs and release

**Files:** `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, `skills/placemat/references/migration.md`, `src/placemat/__init__.py`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `BACKLOG.md`.

- [ ] **Step 1:** `api.md`: `[cleanup]` rows in the settings table; a paragraph after "Where each is searched from" on what the pass moves and what it leaves; `metrics.cleanup`.
- [ ] **Step 2:** `SKILL.md`: a step noting `cleanup:` moved after its turn; a part that must stay where the search put it takes a `Near`.
- [ ] **Step 3:** `migration.md` `## To 0.23`: searched parts may move after placement to shorten wire and links; `[cleanup] enabled = false` gives the old placement.
- [ ] **Step 4:** Version 0.23.0 in the three files; reinstall (`uv pip install -e . --no-deps`) so the version test passes.
- [ ] **Step 5:** `BACKLOG.md`: the pass under Done with its numbers; the solve item updated (no better than the seed once the pass runs).
- [ ] **Step 6:** Suite, benchmark (same on 32), commit.
