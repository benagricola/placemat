# Placement Envelopes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `[place] envelope = "courtyard" | "physical" | "union"`: in physical a part claims its pads, mask apertures, stroked silk and fab body, judged against other parts at the board's own rule gaps, so a legal placement cannot produce silk DRC items between footprints.

**Architecture:** The reader adds per-face silk, mask and body polygons to each `Footprint` and the board's silk clearance to `BoardGeometry`; the fab profile gains `component_spacing`. `occupancy._fp_shapes` builds the shapes the envelope asks for, and `_conflict` judges the new kinds by the spec's table. Rank area, row claims and cell envelopes read the same shapes. The courtyard-mode report is a separate `footprints` metric.

**Tech Stack:** Python 3, pytest, pcbnew 10 (reader only).

**Spec:** `docs/superpowers/specs/2026-09-23-placement-envelopes-design.md` (its "Decisions on review" are part of it).

## Global Constraints

- `courtyard` (the default) is byte-identical to today: same shapes, same placements, same run output apart from the new report line.
- Pairs within one footprint are never tested.
- Every gap comes from the board or fab profile: netclass clearance, `m_SilkClearance`, `component_spacing` (default `2 * courtyard_excess`).
- No module, part, board or component-type names in `src/`, the skill or migrations.
- Deterministic; zero runtime dependencies; pcbnew only under `kicad/`.
- Each commit that can move a placement carries the benchmark tally; plain ASCII; no attribution lines.
- Tests run as `.venv/bin/python -m pytest -q > $S/out.txt 2>&1; echo $?`.

---

### Task 1: Read silk, mask and body

**Files:**
- Modify: `src/placemat/board_geometry.py` (`Footprint.silk`, `.mask`, `.fab`: `tuple[tuple[Face, Polygon], ...] = ()`; `BoardGeometry.silk_clearance: float = 0.0`)
- Modify: `src/placemat/kicad/read.py` (both footprint readers, and the board-level read)
- Modify: `src/placemat/project.py` (`FabProfile.component_spacing`, read from `courtyard.component_spacing_mm`, default `2 * excess`)
- Test: `tests/test_envelope_read.py` (`needs_kicad`, on a fixture board under `fixtures/`)

**Interfaces:**
- Produces: `Footprint.silk / .mask / .fab`, `BoardGeometry.silk_clearance`, `FabProfile.component_spacing`.

- [ ] **Step 1: Failing tests.** On `fixtures/fairing/modules/Mcu/layout/layout.kicad_pcb`:
  1. `silk_clearance` equals `GetDesignSettings().m_SilkClearance` in mm;
  2. a footprint with silk graphics has `silk` polygons on its face, and none comes from a field (the union of `silk` boxes does not reach the Reference field's box when that field sits clear of the graphics);
  3. each SMD pad has one mask polygon per mask layer it is on, and its box is the pad's box grown by `pad.GetSolderMaskExpansion(layer)` (to 0.01 mm);
  4. a footprint with Fab graphics has one `fab` polygon per face, the box of its non-text Fab graphics;
  5. `fab_profile()` gives `component_spacing == 2 * courtyard_excess` with no key, and the key's value when given.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Silk: for each `fp.GraphicalItems()` on `F_SilkS`/`B_SilkS` (fields are not in `GraphicalItems()`; `PCB_TEXT` graphics are), `outlines_of(item, layer)` - the stroked outline. Mask: for each pad and each of `F_Mask`/`B_Mask` in its layer set, `TransformShapeToPolySet(ps, layer, expansion, err, ERROR_OUTSIDE)` with `expansion = pad.GetSolderMaskExpansion(layer)`; confirm in the test that this is the pad grown once, not twice, and use clearance 0 if the call already applies it. Body: per Fab layer, the box of its non-text graphics as a 4-point polygon. A plated through-hole pad's mask polygons and a through-hole part's body carry both faces (the `Face` in the tuple is the one drawn; `_fp_shapes` widens it).
- [ ] **Step 4: Run tests and suite; commit** (`The reader carries each footprint's silk, mask apertures and fab body`).

---

### Task 2: The envelope in the occupancy

**Files:**
- Modify: `src/placemat/settings.py` (`place_envelope: str = "courtyard"`, validated to the three values)
- Modify: `src/placemat/occupancy.py` (`_fp_shapes(fp, envelope)`, `Occupancy(..., component_spacing=, silk_clearance=)`, `_conflict`)
- Modify: `src/placemat/layout.py` (pass the setting, `component_spacing` and `silk_clearance` when building every `Occupancy`)
- Modify: `tests/fixtures.py` (`footprint(..., silk=(), mask=(), fab=None)` builders)
- Test: `tests/test_envelopes.py` (pure)

**Interfaces:**
- Produces: shape kinds `silk`, `mask`, `body` beside `courtyard`, `pad`, `through`, `npth`; `Occupancy.envelope`.

- [ ] **Step 1: Failing tests** (pure, synthetic footprints):
  1. two footprints whose silk passes their courtyards: in `physical` the second cannot be placed with its silk within `silk_clearance` of the first's, and a scan puts it where the silks stand clear; in `courtyard` the same pair may sit where the silks overlap;
  2. silk over another part's mask aperture closer than `silk_clearance` is refused; silk over its copper outside the aperture is allowed;
  3. body to body and body to another part's pad closer than `component_spacing` are refused; at exactly `component_spacing` allowed;
  4. silk touching another body is allowed; silk inside another body is refused (gap 0);
  5. a footprint with only pads places exactly as in `courtyard` mode, in both `physical` and `union`;
  6. a footprint with no physical layers falls back to its courtyard in `physical`;
  7. `union` refuses what either `courtyard` or `physical` refuses;
  8. an unknown `envelope` value is a settings error naming the three.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** `_fp_shapes`: `courtyard` as today; `physical` = pads, npth, `mask`, `silk`, `body` (courtyard dropped unless the footprint has none of silk, mask beyond its pads, or fab - then today's courtyard); `union` = both. `_conflict` rows per the spec table, each clearance checked with the existing box-gap prefilter before `poly_distance`; the conflict gap for the obstacle prefilter is at least `max(component_spacing, silk_clearance)` (today's `_GAP` of 1.0 covers it; assert it in `__init__`). Refusal text names both kinds and the gap: `U1 silk is 0.04 mm from U2 silk (needs 0.10)`.
- [ ] **Step 4: Run tests and suite** - `courtyard` must leave every existing test and `fixtures/bench.py` unchanged. **Commit.**

---

### Task 3: What follows the setting

**Files:**
- Modify: `src/placemat/layout.py` (`_rank` area; `claim()`; cell envelope)
- Modify: `src/placemat/occupancy.py` (the `CellGeom` branch of `_geometry` already unions members' shapes - check it carries the new kinds)
- Test: `tests/test_envelopes.py` (more)

- [ ] **Step 1: Failing tests:** in `physical`, a part whose silk and body far exceed its courtyard ranks by that larger area; a row of such parts spaces by their reach, with no courtyard in the claim; a cell's envelope contains its members' silk and bodies.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Rank area: in `physical`/`union`, the area of the union box of the envelope's shapes (courtyard mode keeps `courtyard_box.area`). `claim()`: in `physical`, `reach_box` alone; `union` keeps today's union. Reach in `physical` includes mask and body boxes.
- [ ] **Step 4: Tests, suite, commit.**

---

### Task 4: Reporting

**Files:**
- Modify: `src/placemat/describe.py` (`measure` prints the envelope box and the layers that set each side)
- Modify: `src/placemat/layout.py` (`Plan.footprints: list[str]`, filled in courtyard mode) and `src/placemat/runner.py` (`run_metrics`: `metrics["footprints"]`; one `footprints` line naming up to eight)
- Test: `tests/test_envelopes.py`, `tests/test_describe*.py`

- [ ] **Step 1: Failing tests:** `measure` output has `envelope W x H (silk, body)` for a part whose silk and body set it; in courtyard mode a footprint whose silk passes its courtyard by more than `silk_clearance` appears in `plan.footprints` as `U1: courtyard understates the part by 0.42 mm (silk)` and NOT in `plan.findings`; `run_metrics()["footprints"]` counts them.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** The understatement is the largest distance any silk or pad box passes the courtyard box, per side; the layer named is the one that passes furthest.
- [ ] **Step 4: Tests, suite, commit.**

---

### Task 5: Acceptance on real boards

**Files:**
- Modify: `fixtures/bench.py` (a `physical` configuration beside `default` and `solve`), `fixtures/bench.json`

- [ ] **Step 1:** `fixtures/bench.py --update`: `default` and `solve` same on 32; the new `physical` rows recorded. Report how `physical` compares with `default` per module (placed, findings, HPWL).
- [ ] **Step 2: The core board**, in the scratch copy with its cached generation, `[place] envelope = "physical"`, full `placemat run` with DRC:
  - `silk_overlap` and `silk_over_copper` items between different footprints: 0, apart from any from Reference/Value text (count them from `drc.json`, pairing each item's two footprints);
  - resolve time within 20% of the courtyard-mode resolve on the same copy (the spec's 137 s is the board agent's machine; measure both here);
  - placed, findings and airwire against courtyard mode, reported.
- [ ] **Step 3:** If silk items remain, find which shapes or gaps let them through and fix before going on; if the resolve is over budget, profile and fix.
- [ ] **Step 4: Commit** the bench configuration and baseline with the tally and the core numbers.

---

### Task 6: Docs and release

**Files:** `skills/placemat/references/api.md` (the `[place] envelope` row, a paragraph with the conflict table, `component_spacing`, `metrics.footprints`), `skills/placemat/SKILL.md` (when to choose physical: silk DRC between parts; the footprints report), `skills/placemat/references/migration.md` (`## To 0.23`: nothing changes in courtyard mode; switching the mode re-places every board; the new report line), version 0.23.0 in the three files, `BACKLOG.md`.

- [ ] Suite, benchmark, commit, attribution check.

The cleanup-pass plan (`2026-09-23-cleanup-pass.md`) follows this one and becomes 0.25.0; its envelope-aware legality comes for free, since it moves parts through `occ.legal` and `scan()`.
