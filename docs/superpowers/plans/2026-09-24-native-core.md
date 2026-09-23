# Native core implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** an optional Rust extension, `placemat_native`, that accelerates
the placement hot path without changing any legal/illegal verdict, chosen
placement, reason string or blame tally the pure-Python path already
produces.

**Architecture:** see `docs/superpowers/specs/2026-09-24-native-core-design.md`
for the measured boundary decision. Phase 1 (this plan's Tasks 1-2) ports
the three geometry predicates (`polys_overlap`, `poly_distance`,
`point_segment_distance`) behind the existing call sites in `geometry.py`.
Phase 2 (Task 3) ports the near-obstacle conflict search inside
`Occupancy.legal()` - obstacles registered into Rust once per `scan()`,
queried per candidate, with the reason string still produced by the
unmodified Python `_conflict` / `_drawn_conflict` on the one pair Rust
identifies.

**Tech Stack:** Rust 1.93 + PyO3 0.29 + maturin, in `native/` (its own
crate; not a runtime dependency of `placemat`). Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-native-core-design.md`.

## Global constraints

- `placemat` imports and runs with `native/` never built. `placemat_native`
  is imported in a `try/except ImportError`; every accelerated function's
  Python body stays in place, unconditionally runnable.
- `PLACEMAT_NATIVE=0` forces the Python path even when the module is
  installed.
- No verdict, placement, reason string or blame tally may change. Checked
  by: `fixtures/bench.py --jobs 4` reporting `better 0, worse 0, same 32`
  in all three configs with native built; `pytest -q` green both with and
  without the module (`PLACEMAT_NATIVE=0`); randomised native-vs-Python
  comparison tests.
- Every commit that can change placements (none of these should, but a
  bench run is cheap insurance) carries the bench tally lines.
- Plain ASCII; no module/part/board/component-type names in `src/`; no
  attribution lines in commits.

---

### Task 1: Crate scaffold and the optional import

**Files:**
- Add: `native/Cargo.toml`, `native/pyproject.toml`, `native/src/lib.rs`, `native/README.md`
- Modify: `src/placemat/geometry.py` (the `try/except ImportError` guard and `PLACEMAT_NATIVE` check, no behaviour change yet - nothing calls `_native` until Task 2)
- Test: `tests/test_native_import.py`

**Interfaces:**
- Produces: `geometry._native` (`module | None`), importable regardless of whether the crate is built.

- [x] **Step 1: Failing test.** `tests/test_native_import.py`: importing `placemat.geometry` never raises, regardless of whether `placemat_native` is installed; with `PLACEMAT_NATIVE=0` in the environment, `geometry._native is None` even when the module is importable.
- [x] **Step 2: Run to verify it fails** (module doesn't exist yet / no guard yet).
- [x] **Step 3: Implement.** `native/`: `maturin init --bindings pyo3`, crate name `placemat_native`, `crate-type = ["cdylib"]`, `pyo3` with the `extension-module` feature. `native/README.md`: what it is, `maturin develop --release` to build into the active venv, `cargo test` for the Rust unit tests, and that it is optional. `geometry.py`: near the top,
  ```python
  import os
  try:
      import placemat_native as _native
  except ImportError:
      _native = None
  if os.environ.get("PLACEMAT_NATIVE") == "0":
      _native = None
  ```
- [x] **Step 4: Run tests and suite; commit** ("A native module, imported if present, changes nothing yet").

---

### Task 2: Geometry predicates

**Files:**
- Modify: `native/src/lib.rs`, add `native/src/geometry.rs` (pure Rust, `#[cfg(test)]` unit tests, no PyO3 dependency in the module itself)
- Modify: `src/placemat/geometry.py` (`polys_overlap`, `poly_distance`, `point_segment_distance`)
- Test: `native/src/geometry.rs` (`cargo test`), `tests/test_native_geometry.py` (randomised native-vs-Python comparison, runs unconditionally: it is a no-op pass when the module isn't built)

**Interfaces:**
- Produces: `placemat_native.polys_overlap(a, b) -> bool`, `.poly_distance(a, b) -> float`, `.point_segment_distance(p, a, b) -> float`, each taking/returning plain tuples of floats.

- [x] **Step 1: Rust unit tests first** (`cargo test`, TDD on the Rust side): disjoint boxes don't overlap and are 1.0 apart; touching boxes don't overlap and are 0.0 apart; overlapping boxes overlap; the first-vertex-on-boundary case `polys_overlap`'s own docstring calls out (a 16-gon with one vertex exactly on a box's edge) reads as overlapping.
- [x] **Step 2: Implement `native/src/geometry.rs`**, porting `_cross`, `point_in_polygon`, `segments_intersect`, `_edges`, `point_segment_distance`, `_edge_meets`, `_strictly_inside` and `polys_overlap`'s PLAIN branch (no grid) expression-for-expression from `geometry.py`, so float comparisons and operator order match. `poly_distance` calls this `polys_overlap` first, then the same two-way `min` walk. Confirm `cargo test` passes.
- [x] **Step 3: Wire `native/src/lib.rs`** - `#[pyfunction]` wrappers `polys_overlap`, `poly_distance`, `point_segment_distance` taking `Vec<(f64, f64)>` / `(f64, f64)`, registered on the `placemat_native` module. `maturin develop --release`.
- [x] **Step 4: Failing Python test first** (`tests/test_native_geometry.py`, skipped with a clear reason when `placemat_native` isn't built): generate randomised polygon pairs (axis boxes, rotated boxes, octagons, a 16-gon circle) with a fixed seed, assert `_native.polys_overlap`/`poly_distance`/`point_segment_distance` agree with the pure-Python functions - overlap by exact equality (boolean), distances within `1e-6` (see the spec's hypot divergence note, not bit-exact). Also run the comparison directly against polygons pulled from a real fixture board (courtyard and pad outlines from `fixtures/fairing/modules/SlotControl`).
- [x] **Step 5: Run to verify it fails without native wired**, then **implement the dispatch** in `geometry.py`:
  - `point_segment_distance`: delegate to `_native.point_segment_distance` when `_native is not None`, else the existing body (rename existing to keep as the fallback, e.g. keep the same function with an early return).
  - `polys_overlap`: keep the existing box-reject and `pa.grid is not None or pb.grid is not None` branch (routes to the Python-cached grid path) exactly as today; only the final "plain" branch dispatches to `_native.polys_overlap(a, b)` when available.
  - `poly_distance`: when `_native is not None`, `return _native.poly_distance(a, b)`; else the existing body. (Native's own `polys_overlap` call inside `poly_distance` is always the plain test, which the spec confirms is behaviourally identical to the grid path for any polygon size - so this is safe even for a 24+-vertex operand.)
- [x] **Step 6: Run tests and suite both ways** (built, and `PLACEMAT_NATIVE=0`).
- [x] **Step 7: Bench both ways**, record seconds; **commit** with the tally (`same 32` expected in all three configs - this changes performance only) and the sequential timings in the message body.

---

### Task 3: Batched near-obstacle conflict search (Phase 2)

This is the task the spec's profiling says is where the real win is; it is
substantially bigger than Tasks 1-2 and carries the correctness risk the
spec's design section addresses (Rust decides WHICH pair conflicts; Python's
existing, untouched `_conflict` / `_drawn_conflict` still formats the
answer). Split into sub-steps so each is independently testable; land only
as many as fit this session with full TDD and both-ways verification - a
sub-step not reached is left for a follow-up plan, reported as unfinished
rather than rushed.

**Files:**
- Add: `native/src/shapes.rs` (`Shape`, `ShapeIndex`/grid, the `_conflict` / `_drawn_conflict` boolean decision)
- Modify: `native/src/lib.rs` (a `PyClass` wrapping a registered obstacle index; a `first_conflict` call)
- Modify: `src/placemat/occupancy.py` (`ShapeIndex`/`obstacles()` register into native when available; `legal()` calls it and, on a hit, re-runs the existing `_conflict`/`_drawn_conflict` on the identified pair only)
- Test: `native/src/shapes.rs` (`cargo test`), `tests/test_native_legal.py` (randomised candidates against real fixture boards, comparing `Occupancy.legal()`'s verdict AND reason string, native vs `PLACEMAT_NATIVE=0`)

**Interfaces:**
- Produces: a native obstacle index built from a `ShapeIndex`'s shapes (owner, kind, faces, layers, net, polygon, box, label), and `first_conflict(candidate_shapes, gap, drawn_gap, silk_clearance, component_spacing, touch, footprint_refs, vias_block_courtyards) -> (shape_index, obstacle_index) | None`.

- [ ] **Step 1: Port `Shape` and the near-box grid.** Rust unit tests: a grid built from N shapes returns the same set `ShapeIndex.near()` would for a box+gap query, on both a linear (<48 shapes) and grid-indexed (>=48) pool, matching `ShapeIndex.CELL`/`LINEAR`.
- [ ] **Step 2: Port the `_conflict` boolean decision** (courtyard-courtyard touch/overlap with `_touch`; courtyard-vs-npth/through with `vias_block_courtyards`; pad/through/copper clearance with the net-equal short-circuit and `_box_gap` prefilter; npth-cuts-copper) and **`_drawn_conflict`'s** (the kind-pair table: silk/mask, silk/body, body/body, body/pad-or-through with the footprint-ref check) - as boolean-only functions returning which rule fired, not a formatted string. Rust unit tests per rule, each with a case that conflicts and a case at/just outside the gap (boundary-exact, matching the `- 1e-9` comparisons).
- [ ] **Step 3: Randomised Rust-vs-Python fuzz test** (`tests/test_native_legal.py` or a standalone comparison script folded into it): for shape pairs pulled from real fixture footprints (courtyard, pad, silk, mask, body outlines) at randomised offsets, the native boolean decision agrees with calling the live Python `_conflict`/`_drawn_conflict` on the same pair, across every kind combination the table covers. This gates Step 4 - do not wire `legal()` to native until this is at zero mismatches over a large randomised run (>= 100k pairs).
- [ ] **Step 4: Wire `Occupancy.obstacles()`** to build (or reuse) a native index alongside the `ShapeIndex` it returns today, keyed so `commit()` invalidates it (mirrors `others = occ.obstacles(...)` already being rebuilt fresh per `scan()`/`layout_block()` call - confirm no code holds an `obstacles()` result across a `commit()`, which the current code doesn't).
- [ ] **Step 5: Wire `Occupancy.legal()`**: when a native index is available for `others`, pass the candidate's transformed shapes (already computed exactly as today) to `first_conflict(...)`; on a hit, call the existing Python `_conflict`/`_drawn_conflict` on that one `(shape, obstacle)` pair to produce the reason string and `Blocker`, appended exactly as today. On a miss, `None`, exactly as today. When no native index (module absent, `PLACEMAT_NATIVE=0`, or `others` isn't the kind `obstacles()` builds - e.g. a hand-built `ShapeIndex` in a test), fall through to today's Python loop unchanged.
- [ ] **Step 6: Run tests and suite both ways.**
- [ ] **Step 7: Bench both ways** on the full corpus - `same 32` in all three configs is the bar, since this can only change speed, and sequential per-config timings (Python vs native) recorded in the commit message. **Commit.**

---

### Task 4: Report and packaging note

- [ ] Update `native/README.md` with whatever Task 3 lands (build steps, `cargo test`, what `PLACEMAT_NATIVE=0` does).
- [ ] Leave a note in the spec's "Packaging" section (already written) as the open decision for the user: how a released `placemat` ships the compiled extension. Not decided or guessed at here.
