# Hole Spacing When Placing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The occupancy refuses a candidate whose drilled holes come within the board's hole-to-hole rule of another owner's holes (any nets), and copper within the hole clearance of an unplated hole; the native scan agrees; the via planner sees a stamped cell's vias.

**Architecture:** A new Shape kind `hole` (a circle of the drill, both faces, no copper layers) is added beside each plated through pad with a drill (in `_fp_shapes`), each via read from the board, and each planned via (`_shape_of`). `Occupancy._conflict` gains two rules; `native/src/shapes.rs` `conflict` gains the same, with `hole_to_hole` and `hole_clearance` in `ConflictConfig`. The via planner's `_via_obstacles` reads holes from the occupancy.

**Tech Stack:** Python 3.12, Rust (pyo3, `uv pip install -q -e ".[native]"` to rebuild), pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-hole-spacing-design.md` (approved 2026-09-27)

## Global Constraints

- Two holes conflict when `poly_distance < geometry.hole_to_hole - 1e-9`, whatever their nets; only shapes of different owners are ever compared (a candidate against the rest), as now.
- An unplated hole (`npth`) conflicts with copper (`pad`, `through`, `copper`) of any net when `poly_distance < geometry.hole_clearance - 1e-9` (an overlap when `hole_clearance` is 0, as now).
- A `hole` shape never conflicts with a courtyard, a drawn shape (silk, mask, body) or copper: its pad or via ring answers for those.
- Every consumer of item shapes or `occ.copper` that selects by kind keeps its present result (a `hole` is not copper, not a lead, not a via ring).
- The prefilter reach (`_gap`) is at least `max(hole_to_hole, hole_clearance)`: raise as the envelope check does when `[place] conflict_gap` is less.
- Native and Python agree on every pair (parity tests).
- Generic wording; plain ASCII; bench before the commit; no tool or session references in commits.

## Review Focus

1. A part's own through pads and its own vias (a cell's copper) are never compared with each other.
2. `escapes.py`, `placer.py:461`, `copper_conflicts`, `_via_obstacles` and the routes "meets" check see no `hole` where they read copper.
3. Flip parity: a flipped cell's hole shapes move with it (the transform covers every shape kind).
4. `occ.commit` for a cell replaces its own copper shapes (`occupancy.py:687`): the cell's via holes go with them.
5. A board without drilled holes: nothing changes (bench same 32 unless a bench board has close holes; any change is read and explained in the commit).

---

### Task 1: Hole shapes and the two rules (Python)

**Files:** `src/placemat/occupancy.py` (`_fp_shapes`, the via shapes in `__init__`, `_conflict`, `_NAMES`, the gap check), `src/placemat/layout.py` (`_shape_of` returns the via's ring and hole: callers take a list); Test `tests/test_hole_spacing.py`.

- [ ] **Step 1: Failing tests** (pure, `tests.fixtures`):
  - two cells each with a GND via (cell copper), the second searched `Near` the first so the nearest spot puts the holes 0.2 mm apart with `hole_to_hole` 0.3: the searched cell lands where its hole is at least 0.3 from the other's;
  - a part with a plated through pad of net GND and a fixed GND via 0.1 mm hole to hole from where the part is `Location`-placed: the placement is refused with "hole 0.10 mm from ... hole (needs 0.30)";
  - copper 0.1 mm from an unplated hole, `hole_clearance` 0.25: refused; 0.3 mm: legal;
  - a part whose own two through pads are 0.1 mm apart hole to hole places (its own holes are its footprint's);
  - `occ.copper_conflicts` of a via ring beside a hole shape of another net is unchanged (a hole is not copper).
- [ ] **Step 2: Run** `uv run pytest -q tests/test_hole_spacing.py` - FAIL.
- [ ] **Step 3: Implement.** `Shape(owner, "hole", _BOTH, frozenset(), net, circle_polygon(centre, drill / 2), box, label)` for each `p.through and p.drill_mm` pad (centre `p.box.center`) and each via (`c.drill_mm`, centre `c.box.center`) and each planned `Via` op. `_conflict`: before the courtyard rules, `if ks in _HOLES and ko in _HOLES` (hole, npth) -> the hole-to-hole rule; `if "hole" in (ks, ko)` -> None; the npth-vs-copper rule uses `hole_clearance`. Sentence: `"%s hole %.2f mm from %s's hole (needs %.2f)"`. Audit every `kind` selection listed in Review Focus 2 and keep holes out.
- [ ] **Step 4: Run** - PASS, and `uv run pytest -q tests/test_occupancy*.py tests/test_escapes*.py tests/test_flip_parity.py`.
- [ ] **Step 5: Commit** "Placing keeps the hole-to-hole rule between owners, and the hole clearance from unplated holes".

### Task 2: Native parity

**Files:** `native/src/shapes.rs` (`Kind::Hole`, `ConflictConfig.hole_to_hole/hole_clearance`, `conflict`, `gap_for`), `native/src/lib.rs` (both `ConflictConfig` constructions and their Python signatures), `src/placemat/occupancy.py` (`_native_conflict_kwargs`); Test `tests/test_native_conflict.py` (the randomised pairs include `hole` and `npth` against every kind).

- [ ] **Step 1: Failing test:** the randomised parity run over pairs with `hole` shapes: native disagrees (it has no `hole` kind).
- [ ] **Step 2: Implement**, rebuild with `uv pip install -q -e ".[native]"`.
- [ ] **Step 3: Run** `uv run pytest -q tests/test_native_*.py tests/test_occupancy_parity.py tests/test_hole_spacing.py` - PASS.
- [ ] **Step 4: Commit** "native: the hole rules".

### Task 3: The via planner, docs, bench

**Files:** `src/placemat/layout.py` (`_via_obstacles`: plated holes from every placed item's and `occ.copper`'s `hole` shapes, so a cell's vias count); docs (`api.md`'s placement rules paragraph, `migration.md` To 0.43, `BACKLOG.md` Done); Test `tests/test_hole_spacing.py` (append).

- [ ] **Step 1: Failing test:** a stamped cell with a via; `board.vias` / a `FreeSpot` via near it is refused 0.2 mm hole to hole from the cell's via.
- [ ] **Step 2: Implement.** **Step 3:** Run the new tests, the bench and the full suite.
- [ ] **Step 4: Commit** "The via planner sees a cell's vias" with the bench tally.
