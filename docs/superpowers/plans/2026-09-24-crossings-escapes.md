# Crossings and Escape Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Runs, explore variants and the bench are judged by one weighted score with configurable weights; ratsnest crossings and escape room count in it and in the search and cleanup; cleanup can swap any two parts and move satellites within a limit; crossed and walled-off escapes are findings.

**Architecture:** A new `ratsnest.py` computes KiCad's per-net MST and its crossings, with an incremental form for scoring one candidate. A new `escapes.py` keeps each placed pad's corridors. A new `score.py` gives the weighted run score used by the ranking, explore and the bench. `Board._scorer` and `cleanup.cost` add the crossing and escape terms; cleanup gains lift-and-search swaps and satellite moves.

**Tech Stack:** Python standard library; kicad-cli for the KiCad cross-checks (the existing KiCad-marked tests).

**Spec:** `docs/superpowers/specs/2026-09-24-crossings-escapes-design.md`

## Global Constraints

- Every weight, depth and noise band is a setting with a documented default (api.md settings table; the settings-documented test enforces it). Defaults come from measurement, recorded in the commit.
- Generic wording in src, skill and migrations; plain ASCII; no attribution lines in commits.
- TDD: each task's tests fail first.
- Every placement-affecting commit: suite with and without `PLACEMAT_NATIVE=0`, `fixtures/bench.py` in default, solve and physical, tally in the message, baseline updated in the commit when numbers change.
- Performance budget: bench default resolve at most 1.5x its 0.32.2 time (CPU, sequential).

---

### Task 1: placemat's ratsnest (done)

**Files:** Create `src/placemat/ratsnest.py`; tests `tests/test_ratsnest.py`, `tests/test_ratsnest_kicad.py` (KiCad-marked).

**Interfaces (produced):**
- `anchors(occ, refs, quiet) -> dict[net, list[Anchor]]`: `Anchor(ref, number, x, y)` at each pad's position, for placed pads on counted nets.
- `mst(anchors, clusters=()) -> list[Edge]`: `Edge(net, a, b)`. It runs Kruskal over all pairs with KiCad's order key `(weight, (x, y, tag) of the lower end, (x, y, tag) of the higher end)`. Pads in one copper cluster are pre-united.
- `crossings(edges, weights=None) -> (count, per_net)`: proper intersections between edges of different nets, the same test as `report.airwires_from_drc`, each weighted by its nets' weights (plane nets at `crossing_plane_weight`).
- `class Ratsnest`: kept on the Occupancy. `update(refs)` recomputes the nets those parts touch; `added(item, placement) -> float` gives the weighted crossings a candidate's leaf edges add. It uses a grid index over edge boxes (cell size `[place] geometry_index_cells` pattern).

- [x] Tests:
  - an MST on hand-made point sets with a known tree;
  - equal-distance ties broken as KiCad's order key;
  - copper-joined pads never get an edge;
  - collinear points;
  - crossings counted once per pair, and never between edges of one net;
  - plane nets weighted;
  - `added()` equals the full recount's difference for a leaf join on random small boards.
- [x] KiCad test: on each fixture board the suite writes and checks with kicad-cli, placemat's count over counted nets equals `airwires_from_drc`'s, within KiCad's own run-to-run variation (run it three times and take the range).
- [x] Implement; suite both ways; commit. The measure is not used by placement yet, so no bench is needed.

Result: every fixture board whose airwires end at pads (20 of 34; the 14 routed boards end airwires at tracks and vias, whose reported position is not the airwire's end) matches kicad-cli's airwire count and length exactly, and its crossings within one equal-length tie. On the way:
- a pad's anchor is `PAD::ShapePos`, read into `PadGeom.anchor`: the polygon's box centre drifted enough to make a row's airwires cross;
- track ends, vias and copper shapes' connection points are nodes, as KiCad's connectivity has them;
- anchors at one position in different clusters are joined at weight 1, as KiCad does;
- the crossing test is exact (whole nanometres) and order-independent: an airwire that ends on another only touches it. `report.airwires_from_drc` uses the same test, so a run's crossing count can move slightly from 0.32's.

### Task 2: findings with a kind (done)

**Files:** `src/placemat/layout.py`, `src/placemat/copper.py` and `src/placemat/runner.py` (every emitting site), `src/placemat/reuse.py` (replay keeps the kind), `tests/test_finding_kinds.py`.

**Interfaces (produced):**
- `Finding(kind: str, text: str)`, a `str` subclass carrying `.kind`, so every reader of `plan.findings` as strings keeps working.
- Kinds: `unplaced`, `link_over`, `fixed`, `copper`, `label`, `escape_crossed`, `escape_closed`, `escape_walled`, `setup`.
- `plan.findings` is a `Findings` list, which refuses a bare string; `plan.findings.by_kind() -> dict[kind, list]`.

- [x] Failing tests:
  - each emitting site gives its kind (one case per site, from the grep of `findings.append`);
  - the texts are unchanged;
  - a replayed run keeps the kinds;
  - an old reuse cache without kinds reads them as `setup`, or re-resolves.
- [x] Implement; suite both ways; bench (placements unchanged); commit.

### Task 3: the run score (done)

**Files:** Create `src/placemat/score.py`; modify `settings.py` (the `score_*` settings and the three escape weights, which task 5 then uses in the search and measures, `best_crossing_noise`), `report.py` (`objective` -> the score, stored measurements, the noise band, the per-term report), `runner.py` (metrics record counts by kind, link excess, `crossings_counted` from DRC over counted nets), `explore.py` (`score` -> the run score without DRC, with placemat's crossings and the RUDY term), `fixtures/bench.py` (records crossings and the score; verdict by score beyond noise), api.md rows, tests `tests/test_run_score.py`, `tests/test_report*.py`, `tests/test_explore_score.py`, bench tests.

**Interfaces (produced):**
- `score.terms(measures: dict, cfg: Settings) -> dict[term, float]`;
- `score.total(measures, cfg) -> float`;
- `score.noise(measures, cfg) -> float`;
- `score.compare(a, b, cfg) -> (sign, deciding term)`.

`measures` holds:
- `unplaced` by priority;
- `drc_real`;
- `link_excess`: the sum of (mm over x link weight);
- the finding counts by kind;
- `crossings_counted`;
- `airwire_mm`;
- `rudy_steps`.

- [x] Failing tests:
  - each term computed from its measure and weight;
  - an unplaced part counted once, not also as a finding;
  - a HIGH part's absence costs twice a DEFAULT's;
  - a link 0.03 mm over costs 0.03 x 20 x its weight;
  - two runs within the noise band tie;
  - a changed weight in the settings re-ranks two stored runs without re-running them;
  - the best-run report names the deciding term;
  - explore orders variants by the score;
  - the bench verdict moves only beyond noise;
  - old best tables and run records (0.32 metrics) are read, with the measures they lack taken as zero, as `comparable()` does today.
- [x] Implement. The crossing weight is `place_crossing_cost`, which task 4 measures. Until then its default is a placeholder of 2 mm, stated in the commit and replaced in task 4.
- [x] Replay: the fairing core's recorded runs (`.placemat/runs/*/run.json`) and the bench corpus. Tabulate the run each gives as best under the old order and under the default weights, and where they differ, why. Show Ben; adjust the defaults if he asks; record the table in the spec.
- [x] Bench: new baseline (score column); tally; commit.

Replay and chosen defaults: see the spec's run score section (unplaced 2000, link 20 x weight). A best stored by 0.32 reads as absent (no measures) rather than with its missing measures as zero, so it is never judged against numbers it did not take.

### Task 4: crossings in the search cost, and its default (done)

**Files:** `src/placemat/settings.py` (`score_crossing`, `score_crossing_plane` (task 3)), `src/placemat/layout.py` (`_scorer` adds `crossing_cost * ratsnest.added(...)`; `Ratsnest.update` on every commit), `src/placemat/occupancy.py` (holds the Ratsnest), `skills/placemat/references/api.md` (settings rows), `tests/test_crossing_cost.py`.

- [x] Failing tests:
  - two candidate spots with equal wire, where one crosses a placed net: the search takes the other;
  - with `crossing_cost = 0` the choice is today's;
  - a plane net's crossing costs nothing at the default weight.
- [x] Implement.
- [x] Measure: the bench at `crossing_cost` in {0, 0.5, 1, 2, 4} mm, recording crossings, hpwl, placed, findings and time. Pick the default from the table: the fewest crossings with no module worse on placed or findings, and hpwl within 3%. Put the table in the spec and the commit.
- [x] Replace task 3's placeholder crossing weight with the measured default; new baseline; tally; commit.

Result: default 4 mm per crossing; the sweep table is in the spec. A block is scored by its anchor's crossings only; its satellites' come with task 6.

### Task 5: escape corridors (done)

**Files:** Create `src/placemat/escapes.py`; modify `settings.py` (`place_escape_depth`; the three escape weights exist from task 3), `layout.py` (`_scorer` adds the escape term; corridors registered as pads commit), api.md rows; tests `tests/test_escapes.py`.

**Interfaces (produced):**
- `corridors(occ, ref) -> list[Corridor]`: `Corridor(ref, number, net, box, direction)`, built on the pad's free sides. A row pad of a many-pin part (pads in a row, as `_pin_normal` finds them) gets one corridor along its normal; a two-pad part's pad gets up to three.
- `Escapes.closed(item, placement) -> (crossed, closed, walled)`: how many escapes from a neighbour's pin row the candidate's edges cross; how many pads' last corridor toward their target it takes; how many pads' last corridor of any kind it takes.

- [x] Failing tests:
  - a part placed across the only corridor of a row pad toward its target costs `escape_closed`, and one beside it costs nothing;
  - a pad with another corridor still open toward its target costs nothing;
  - taking a pad's last corridor of any kind costs `escape_walled`, not `escape_closed`;
  - at the default weights, the search walls a pad off only when no other legal spot exists;
  - same-net copper, and the pad's own part, never close a corridor;
  - with the MCU-like quad anchor from `tests/test_blocks.py`, a part linked to pin 3 is not placed across pin 4's corridor when room under pins 2-3 is free.
- [x] Implement.
- [x] Measure `escape_depth` in {0.5, 1.0, 2.0} mm and `escape_closed` in {25, 50, 100} mm on the bench (`escape_crossed` and `escape_walled` scaled with it). Pick the defaults as in task 4. Put the table in the spec; tally; baseline; commit.

Result: via spots added, bodies do not close corridors, unconnected pads have no escapes but block others, the path search (`escapes.path_out`, from task 7) brought forward so the run score counts confirmed escapes only. Measurements and the router check are in the spec.

### Task 6: cleanup - the cost, satellites and swaps (done but for cells)

**Files:** `src/placemat/cleanup.py`, `src/placemat/layout.py` (`_cleanup_movable` gains satellites with their limits, parts linked to one anchor, and cells; `_cleanup` passes the Ratsnest and Escapes), `tests/test_cleanup_swaps.py`, `tests/test_cleanup_satellites.py`.

**Interfaces:**
- `cleanup(occ, movable, pins, links, clearance, passes, radius, step, turns=None, cost_terms=None, limits=None)`
  - `cost_terms(keys, override) -> float` gives the crossing and escape terms;
  - `limits[key] = (pin (ref, number), own pad number, mm)` holds each satellite's limit.

- [x] Failing tests:
  - **The brief's case.** A quad anchor, `c_en` a satellite on pin 4, `l_rf_supply` linked SHORT to pin 3 and placed under pin 6: VDD_RF crosses MCU_EN. After cleanup the two are swapped, or `l_rf_supply` is under pins 2-3, and the crossing is gone.
  - A satellite never ends further from its pin than its limit (link limit if declared, else `block_gap_reach`, pad edge to pad edge).
  - A swap of a large and a small part, lifted: the larger is searched round the smaller's old spot, then the smaller round the larger's.
  - A swap that would push a limited link over its limit is refused.
  - Fixed, edge, lock-held and explore-focused items never move.
  - The old identical-part and two-pad swaps still happen, as special cases (today's tests keep passing).
- [x] Implement. The lift-and-search swap replaces the two swap loops. Cells take part as a unit.
- [x] Suite both ways; bench (tally, baseline); commit.

Result: parts and satellites move and swap; cells are not yet movable as units (the spec's "Not yet"). Measurements are in the spec.

### Task 7: the escape findings (done)

**Files:** `src/placemat/layout.py` (the findings after cleanup; `escapes.path_out` exists from task 5, kinds `escape_crossed`, `escape_closed` and `escape_walled`), `tests/test_escape_findings.py`.

- [x] Failing tests:
  - a crossed-escape finding for two pads of one part whose edges cross within `escape_depth`, worded "U1 pins 3/4: L2 VDD_RF crosses C2 MCU_EN";
  - a walled-off finding only where the path search confirms it, not where corridors alone say so;
  - both keep their wording and kind through reuse.
- [x] Implement; suite; bench; `bench.py --explore 64` tally; commit.

Result: a resolve reports `escape_crossed` ("U2 pins 3/4: L2 VDD_RF crosses C2 MCU_EN"), `escape_closed` and `escape_walled` ("U9 pin 1 (IN): walled off by R9") findings, confirmed by the path search; the run score counts escapes from these findings. An airwire between two pads of one part is no escape. Geometry tests set escape findings aside (`tests/fixtures.placement_findings`).

### Task 8: preview without tags (done)

**Files:** `src/placemat/preview.py` (`draw_annotated(..., tags=True)`), `src/placemat/cli.py` (`--no-tags` on preview), `tests/test_preview*.py`.

- [x] Failing test: `--no-tags` output has no tag elements, and the notes are still printed.
- [x] Implement; commit.

### Task 9: measure on the fairing core, docs, release

- [x] Work in a scratch copy of fairing-instrument electronics (`--no-reuse`). Check against the spec's "Done when":
  - MCU cell crossings, crossed escapes, walled-off pads, satellite offsets and link limits;
  - core crossings and findings against run 985825a5.

  Record the numbers in the spec.
- [ ] If the MCU cell misses 34 crossings, measure where the remaining crossings are before adding anything. The push-aside moves come in only with numbers showing they are needed.
- [x] Docs:
  - api.md settings and explanations;
  - SKILL.md: when crossings and escapes decide;
  - migration notes: placements move, lock entries may drift, re-accept.
- [ ] Release. Tag and push only when Ben says so.
