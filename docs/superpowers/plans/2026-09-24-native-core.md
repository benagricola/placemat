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

- [x] **Step 1: Port `Shape` and the near-box grid.** Landed as a single uniform grid (`ShapeGrid`) rather than mirroring `ShapeIndex`'s linear-vs-grid size heuristic: a grid is cheap to build in Rust regardless of obstacle count, and `ShapeGrid::near` returns the same set, in the same registration order, that `ShapeIndex.near()` would (`grid_first_conflict_matches_a_brute_force_scan` in `native/src/shapes.rs`).
- [x] **Step 2: Port the `_conflict` boolean decision** and **`_drawn_conflict`'s**, as boolean-only functions. Rust unit tests per rule in `native/src/shapes.rs`, including the courtyard-touch epsilon (placemat commit c785a04) and a via not blocking a body.
- [x] **Step 3: Randomised Rust-vs-Python fuzz test** (`tests/test_native_conflict.py`: the boolean decision alone, ~90,000 randomised pairs across all three envelopes, `vias_block_courtyards`, and the touch boundary, zero mismatches; `tests/test_native_legal.py`: the full near-obstacle search end to end on a synthetic board and three real fixture boards under multiple envelopes, ~6,400 candidates against a hand-rolled native-assisted `legal()`, plus (once Step 5 landed) ~1,500 more directly against the real, shipped `Occupancy.legal()` toggled native on/off in the same process - the strongest check, since it is not a reimplementation. Zero mismatches throughout. Found and fixed one bug along the way: not in the Rust port, but in the first draft of the hand-rolled fuzz helper itself (a hardcoded `owner_is_footprint=False` that made every body/pad rule read as "let it through").
- [x] **Step 4: Wire `Occupancy.obstacles()`** - builds a native index alongside the `ShapeIndex` it returns, attached as `idx._native`. Confirmed no code holds an `obstacles()` result across a `commit()` (grepped every call site: `scan()`, `block_obstacles()`, `_slide()`, and `legal()`'s own `others is None` fallback all call `obstacles()` fresh immediately before use).
- [x] **Step 5: Wire `Occupancy.legal()`**: when `others._native` is set, the candidate's transformed shapes (built exactly as before - `_origin_shapes` then shifted) go to `first_conflict(...)`; on a hit, the existing, untouched `Occupancy._conflict` produces the reason string and `Blocker` from the identified pair. A native/Python disagreement here (native says conflict, `_conflict` on the same pair says no) raises `AssertionError` rather than silently picking one answer - the fuzz testing found none, but a silent divergence would be worse than a loud one. The pure-Python `near()` + per-shape loop is untouched and still exactly what runs with no native module, `PLACEMAT_NATIVE=0`, or a hand-built `others`.
- [x] **Step 6: Run tests and suite both ways.** Both green (`pytest -q`, `PLACEMAT_NATIVE=0 pytest -q`).
- [x] **Step 7: Bench both ways** on the full corpus - `same 32` in all three configs. **Commit.**

---

### Task 4: Report and packaging note

- [x] Update `native/README.md` with what Task 3 landed (`shapes.rs`, the `NativeObstacles` class).
- [x] Spec's "Packaging" section left as-is: the open decision for the user, not decided or guessed at here. Added a "Left for a follow-up" section instead, on the native-index-caching opportunity Task 3's profiling found (see the spec).

---

### Task 5: A persistent native obstacle index (Phase 3)

**Goal:** stop rebuilding and re-marshalling the native obstacle index on
every `Occupancy.obstacles()` call; cache it on the `Occupancy` itself, per
skip-set, invalidated on any change to `self.items` / `self.copper`. See
the spec's "Phase 3" section for the numbers and reasoning behind the
per-skip-set-cache design (over the alternative, query-time owner
filtering in Rust).

**Files:**
- Modify: `src/placemat/occupancy.py` (`__init__`: `_native_obstacle_cache`; new `_invalidate_native()`, called from `commit()`, `add_copper()`, `_register()`; `obstacles()` and the old `_build_native_obstacles` replaced by `_native_obstacle_index(skip)`; `legal()`'s native branch unpacks `(native_index, native_shapes)` and indexes into `native_shapes`, not `others`)
- No Rust changes: `native/src/lib.rs` / `shapes.rs` are unchanged - this is entirely a change to WHEN and HOW OFTEN the existing `NativeObstacles` API is called, not to what it does.

**Interfaces:**
- Produces: `Occupancy._native_obstacle_cache: dict[frozenset, tuple[NativeObstacles, list[Shape]]]`, `Occupancy._native_obstacle_index(skip) -> tuple | None`.

- [x] **Step 1: Design.** A cache keyed by skip-set only (not skip-set + region): the native index holds every non-skipped shape on the board regardless of `region`, since native's own grid narrows a query to what's spatially near without needing a Python-side pre-filtered list first - `region` was always a performance pre-filter (`scan()` sizes it to contain every candidate's own reach), never a correctness one, so dropping it for the native path cannot change which obstacle a search finds first (same near-box-and-gap test either way, same relative order among survivors). The `ShapeIndex` `obstacles()` returns is unchanged (still region-filtered) for the non-native path and for `layout_block`'s member-vs-member `.near()` calls, which never touch this cache.
- [x] **Step 2: Implement.** `_invalidate_native()` clears the cache; called wherever `self.items` or `self.copper` can change. `_native_obstacle_index(skip)` builds-or-returns a cached `(NativeObstacles, shapes_list)` pair; `obstacles()` attaches it as `idx._native` unchanged in shape (still a truthy "is there a native index" signal `legal()` checks via `getattr`), but callers must now unpack the tuple. `legal()`'s native branch updated to look up the conflicting obstacle in `native_shapes` (the cache entry's own backing list), not in `others` (which may be a smaller, region-filtered list with different indices).
- [x] **Step 3: Run tests and suite both ways.** No test changes needed: `test_native_legal.py`'s strongest test already calls the real `Occupancy.legal()` toggled native on/off, which exercises the new cache transparently. `pytest -q` and `PLACEMAT_NATIVE=0 pytest -q` both green.
- [x] **Step 4: Bench both ways** on the full corpus against main's current `fixtures/bench.json` (main gained a rotations-for-searched-parts feature since Phase 1/2 were written, moving the baseline numbers but not this task's job, which is speed only) - `same 32` in every config. **Commit** with the tally and A/B process-time ratios (whole corpus, alternating, power-save off).
