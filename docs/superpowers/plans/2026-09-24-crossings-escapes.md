# Crossings and Escape Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ratsnest crossings and escape room count in the search, cleanup, explore and (after a replay) the best-run ranking; cleanup can swap any two parts and move satellites within a limit; crossed and walled-off escapes are findings.

**Architecture:** A new `ratsnest.py` computes KiCad's per-net MST and its crossings, with an incremental form for scoring one candidate. A new `escapes.py` keeps each placed pad's corridors. `Board._scorer`, `cleanup.cost` and `explore.score` share one cost function; cleanup gains lift-and-search swaps and satellite moves.

**Tech Stack:** Python standard library; kicad-cli for the KiCad cross-checks (the existing KiCad-marked tests).

**Spec:** `docs/superpowers/specs/2026-09-24-crossings-escapes-design.md`

## Global Constraints

- Every weight, depth and noise band is a setting with a documented default (api.md settings table; the settings-documented test enforces it). Defaults come from measurement, recorded in the commit.
- Generic wording in src, skill and migrations; plain ASCII; no attribution lines in commits.
- TDD: each task's tests fail first.
- Every placement-affecting commit: suite with and without `PLACEMAT_NATIVE=0`, `fixtures/bench.py` in default, solve and physical, tally in the message, baseline updated in the commit when numbers change.
- Performance budget: bench default resolve at most 1.5x its 0.32.2 time (CPU, sequential).

---

### Task 1: placemat's ratsnest

**Files:** Create `src/placemat/ratsnest.py`; tests `tests/test_ratsnest.py`, `tests/test_ratsnest_kicad.py` (KiCad-marked).

**Interfaces (produced):**
- `anchors(occ, refs, quiet) -> dict[net, list[Anchor]]`: `Anchor(ref, number, x, y)` at each pad's position, for placed pads on counted nets.
- `mst(anchors, clusters=()) -> list[Edge]`: `Edge(net, a, b)`. It runs Kruskal over all pairs with KiCad's order key `(weight, (x, y, tag) of the lower end, (x, y, tag) of the higher end)`. Pads in one copper cluster are pre-united.
- `crossings(edges, weights=None) -> (count, per_net)`: proper intersections between edges of different nets, the same test as `report.airwires_from_drc`, each weighted by its nets' weights (plane nets at `crossing_plane_weight`).
- `class Ratsnest`: kept on the Occupancy. `update(refs)` recomputes the nets those parts touch; `added(item, placement) -> float` gives the weighted crossings a candidate's leaf edges add. It uses a grid index over edge boxes (cell size `[place] geometry_index_cells` pattern).

- [ ] Tests:
  - an MST on hand-made point sets with a known tree;
  - equal-distance ties broken as KiCad's order key;
  - copper-joined pads never get an edge;
  - collinear points;
  - crossings counted once per pair, and never between edges of one net;
  - plane nets weighted;
  - `added()` equals the full recount's difference for a leaf join on random small boards.
- [ ] KiCad test: on each fixture board the suite writes and checks with kicad-cli, placemat's count over counted nets equals `airwires_from_drc`'s, within KiCad's own run-to-run variation (run it three times and take the range).
- [ ] Implement; suite both ways; commit. The measure is not used by placement yet, so no bench is needed.

### Task 2: the bench records crossings

**Files:** `fixtures/bench.py`, `fixtures/bench.json`, `tests/test_bench*.py`.

- [ ] Failing test: `_resolve` returns `crossings`, and the report line shows it beside hpwl.
- [ ] Add the column; the verdict is unchanged (placed, findings, hpwl) until task 3 measures it. Regenerate the baseline, whose placements are unchanged, only the new column. Commit with the three tallies.

### Task 3: crossings in the search cost, and its default

**Files:** `src/placemat/settings.py` (`place_crossing_cost`, `place_crossing_plane_weight`), `src/placemat/layout.py` (`_scorer` adds `crossing_cost * ratsnest.added(...)`; `Ratsnest.update` on every commit), `src/placemat/occupancy.py` (holds the Ratsnest), `skills/placemat/references/api.md` (settings rows), `tests/test_crossing_cost.py`.

- [ ] Failing tests:
  - two candidate spots with equal wire, where one crosses a placed net: the search takes the other;
  - with `crossing_cost = 0` the choice is today's;
  - a plane net's crossing costs nothing at the default weight.
- [ ] Implement.
- [ ] Measure: the bench at `crossing_cost` in {0, 0.5, 1, 2, 4} mm, recording crossings, hpwl, placed, findings and time. Pick the default from the table: the fewest crossings with no module worse on placed or findings, and hpwl within 3%. Put the table in the spec and the commit.
- [ ] The bench verdict gains crossings (a module is worse if placed or findings fall, or if crossings rise beyond noise with hpwl not better). New baseline; tally; commit.

### Task 4: escape corridors

**Files:** Create `src/placemat/escapes.py`; modify `settings.py` (`place_escape_depth`, `place_escape_cost`), `layout.py` (`_scorer` adds the escape term; corridors registered as pads commit), api.md rows; tests `tests/test_escapes.py`.

**Interfaces (produced):**
- `corridors(occ, ref) -> list[Corridor]`: `Corridor(ref, number, net, box, direction)`, built on the pad's free sides. A row pad of a many-pin part (pads in a row, as `_pin_normal` finds them) gets one corridor along its normal; a two-pad part's pad gets up to three.
- `Escapes.closed(item, placement) -> (closed, walled)`: how many pads' last corridor toward their target, and how many pads' last corridor of any kind, the candidate would take.

- [ ] Failing tests:
  - a part placed across the only corridor of a row pad toward its target costs `escape_cost`, and one beside it costs nothing;
  - a pad with another corridor still open toward its target costs nothing;
  - taking a pad's last corridor costs twice;
  - same-net copper, and the pad's own part, never close a corridor;
  - with the MCU-like quad anchor from `tests/test_blocks.py`, a part linked to pin 3 is not placed across pin 4's corridor when room under pins 2-3 is free.
- [ ] Implement.
- [ ] Measure `escape_depth` in {0.5, 1.0, 2.0} mm and `escape_cost` in {0.5, 1, 2} x `crossing_cost` on the bench. Pick the defaults as in task 3. Put the table in the spec; tally; baseline; commit.

### Task 5: cleanup - the cost, satellites and swaps

**Files:** `src/placemat/cleanup.py`, `src/placemat/layout.py` (`_cleanup_movable` gains satellites with their limits, parts linked to one anchor, and cells; `_cleanup` passes the Ratsnest and Escapes), `tests/test_cleanup_swaps.py`, `tests/test_cleanup_satellites.py`.

**Interfaces:**
- `cleanup(occ, movable, pins, links, clearance, passes, radius, step, turns=None, cost_terms=None, limits=None)`
  - `cost_terms(keys, override) -> float` gives the crossing and escape terms;
  - `limits[key] = (pin (ref, number), own pad number, mm)` holds each satellite's limit.

- [ ] Failing tests:
  - **The brief's case.** A quad anchor, `c_en` a satellite on pin 4, `l_rf_supply` linked SHORT to pin 3 and placed under pin 6: VDD_RF crosses MCU_EN. After cleanup the two are swapped, or `l_rf_supply` is under pins 2-3, and the crossing is gone.
  - A satellite never ends further from its pin than its limit (link limit if declared, else `block_gap_reach`, pad edge to pad edge).
  - A swap of a large and a small part, lifted: the larger is searched round the smaller's old spot, then the smaller round the larger's.
  - A swap that would push a limited link over its limit is refused.
  - Fixed, edge, lock-held and explore-focused items never move.
  - The old identical-part and two-pad swaps still happen, as special cases (today's tests keep passing).
- [ ] Implement. The lift-and-search swap replaces the two swap loops. Cells take part as a unit.
- [ ] Suite both ways; bench (tally, baseline); commit.

### Task 6: explore judges the cost; the findings

**Files:** `src/placemat/explore.py` (`score` uses the shared cost), `src/placemat/escapes.py` (`path_out(occ, ref, number)`: a grid path search at track width and clearance in an `escape_depth` window), `src/placemat/layout.py` (the findings after cleanup), tests `tests/test_explore_score.py` (extend), `tests/test_escape_findings.py`.

- [ ] Failing tests:
  - explore's score orders two variants of equal wire by crossings;
  - a "crossed escape" finding for two pads of one part whose edges cross within `escape_depth`, worded "U1 pins 3/4: L2 VDD_RF crosses C2 MCU_EN";
  - a "walled off" finding only where the path search confirms it, not where corridors alone say so;
  - the findings keep their wording through reuse (replayed runs).
- [ ] Implement; suite; bench; `bench.py --explore 64` tally; commit.

### Task 7: crossings in the run record, and the ranking replay

**Files:** `src/placemat/runner.py`, `src/placemat/report.py` (`crossings_counted` in metrics; in the against-best report), a replay script at `fixtures/rank_replay.py`, tests `tests/test_report_crossings.py`.

- [ ] Failing tests: a run records `crossings_counted` (KiCad's crossings over counted nets) and reports its change against the best run; `objective` unchanged.
- [ ] Implement; commit.
- [ ] Replay: for the recorded runs of the fairing core and the bench corpus, list the run each candidate order would keep. The candidates are:
  - crossings before airwire;
  - crossings after airwire;
  - crossings ahead of findings.

  Each crossings comparison uses a noise band, `best.crossing_noise`, measured from repeat runs of identical inputs as `AIRWIRE_NOISE` was. Present the table to Ben; apply the order he chooses in a separate commit (with api.md and migration notes).

### Task 8: preview without tags

**Files:** `src/placemat/preview.py` (`draw_annotated(..., tags=True)`), `src/placemat/cli.py` (`--no-tags` on preview), `tests/test_preview*.py`.

- [ ] Failing test: `--no-tags` output has no tag elements, and the notes are still printed.
- [ ] Implement; commit.

### Task 9: measure on the fairing core, docs, release

- [ ] Work in a scratch copy of fairing-instrument electronics (`--no-reuse`). Check against the spec's "Done when":
  - MCU cell crossings, crossed escapes, walled-off pads, satellite offsets and link limits;
  - core crossings and findings against run 985825a5.

  Record the numbers in the spec.
- [ ] If the MCU cell misses 34 crossings, measure where the remaining crossings are before adding anything. The push-aside moves come in only with numbers showing they are needed.
- [ ] Docs:
  - api.md settings and explanations;
  - SKILL.md: when crossings and escapes decide;
  - migration notes: placements move, lock entries may drift, re-accept.
- [ ] Release. Tag and push only when Ben says so.
