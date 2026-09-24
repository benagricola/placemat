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
- [x] **Step 5: Rebase and re-port again** for a further upstream commit ("A through-hole part claims only its holes on the far face") that changed `_conflict`'s courtyard branch - see the spec's "Kept in sync with upstream" note under Phase 2. `shapes::Shape` gained `owner` and a precomputed `is_lead`; every PyShape-tuple builder (`occupancy.py` and both native test files) updated together; new Rust and Python tests for the lead rule specifically, including a positive control. Verified both ways again (pytest, bench).
- [x] **Step 6: Rebase and re-port again** for upstream's courtyard-margin change ("Courtyards may overlap by the margin KiCad's own lie inside them"): `place_courtyard_touch`'s default dropped to 0.0, the real allowance became `max(touch, margins[a] + margins[b] - 0.001)` from each footprint's `courtyard_margin`. `shapes::Shape` gained `margin: f64` (PyShape: 8-tuple to 9-tuple, every builder updated); `conflict()`'s courtyard branch computes the same expression. One pre-existing test (`test_conflict_agrees_at_the_courtyard_touch_boundary`) depended on the old default and needed a settings override to keep testing what it was written to test, independent of the current default - fixed, not a native bug. New Rust tests for the margin allowance either side of the boundary; a Python positive control with two real footprints carrying `courtyard_margin`. Verified both ways (pytest, bench).

---

### Task 6: Per-candidate shapes stay native

**Goal:** stop rebuilding a shifted, plain-tuple polygon for every candidate
shape on every `legal()` call - the cost Phase 2's own profiling flagged as
larger than native's search itself. See the spec's matching section for
the measured effect (physical envelope: 3.03x, up from Phase 3's 2.44x).

**Files:**
- Modify: `native/src/shapes.rs` (`ShapeGrid::first_conflict_shifted`), `native/src/lib.rs` (`NativeOriginShapes` class, `NativeObstacles::first_conflict_shifted`), `src/placemat/occupancy.py` (`_native_origin_shapes`, `legal()`'s native branch, `_to_native_shape_shifted` removed as dead code)

- [x] **Step 1: Rust unit test first.** `first_conflict_shifted` on unshifted origin shapes agrees with `first_conflict` on the same shapes pre-shifted, at several offsets.
- [x] **Step 2: Implement.** `ShapeGrid::first_conflict_shifted(origin_shapes, dx, dy, clearance, cfg)`: shifts each shape's bbox unconditionally (cheap), its polygon only for one actually near enough to test. `NativeOriginShapes` (lib.rs): a handle over unshifted shapes, built once. `Occupancy._native_origin_shapes`: caches a handle per `(id(geom), rotation, face)`, the same key `_origin_shapes` itself uses.
- [x] **Step 3: Wire `legal()`** to call `native_index.first_conflict_shifted(origin_handle, dx, dy, clearance)` in place of `first_conflict([_to_native_shape_shifted(...) for s in origin_shapes], clearance)`. Remove the now-dead `_to_native_shape_shifted`.
- [x] **Step 4: Run tests and suite both ways.** `test_the_actual_wired_legal_agrees_with_itself_native_on_and_off` (calls the real, shipped `legal()`) needed no changes and covers this end to end. Both green.
- [x] **Step 5: Bench and A/B time both ways; commit** with the tally and the ratios.
- [x] **Step 6 (found during this task's own profiling, not planned):** `geometry::polys_overlap` never got upstream's `_rect_of` rectangle shortcut, because `shapes::conflict` calls it directly (Rust to Rust), bypassing the Python dispatch layer where the shortcut lived. Ported `rect_of` into `native/src/geometry.rs`. New Rust unit tests (an L-shape sharing a rectangle's bounding box is not a rectangle; a degenerate box is not one; reversed winding still is). Verified both ways, bench `same 32`, own commit.

---

### Task 7: pockets() / _largest_rectangle

**Goal:** the largest-free-rectangle search `pockets()` uses, ported whole
- see the spec's matching section for why this was reordered ahead of the
full `scan()` sweep the original later request proposed next: a profile of
the current (post-Task-6) code showed it costing more than `scan`'s own
loop overhead, with none of `scan`'s reason-string/`who()` entanglement
(pure integer/boolean array logic, no floating point, no message to match).

**Files:**
- Add: `native/src/pockets.rs`
- Modify: `native/src/lib.rs` (`largest_rectangle` pyfunction), `src/placemat/placer.py` (`_largest_rectangle` dispatch)
- Test: `tests/test_native_pockets.py`

**Interfaces:**
- Produces: `placemat_native.largest_rectangle(free, rows, cols, need_r, need_c) -> (area, r0, c0, r1, c1) | None` - identical signature and return shape to the Python function it replaces.

- [x] **Step 1: Rust unit tests first.** Empty and fully-blocked grids, a single free cell, a whole free grid, a minimum-size prune, and a tie-break case (two equal-area rectangles that cannot combine into one bigger one) confirming Python's strict `area > best[0]` - first-found-in-row-then-column-order wins - carries over exactly.
- [x] **Step 2: Implement `native/src/pockets.rs`**, the histogram method ported expression-for-expression (integer heights and areas throughout - no floating point, so no epsilon question at all).
- [x] **Step 3: Wire `native/src/lib.rs`** and `placer.py`'s `_largest_rectangle`: dispatch to native when built, else the unchanged Python body.
- [x] **Step 4: Python comparison test** (`tests/test_native_pockets.py`): 500 randomised grids up to 20x20, varied fill and minimum sizes, EXACT equality against the reference Python body called directly (not through the dispatch); edge cases; a dispatch-wiring test with a fake native module.
- [x] **Step 5: Run tests and suite both ways; bench both ways; commit** with the tally.

---

### Task 8: Deferred conflict-reason formatting in scan()'s sweep

**Goal:** stop paying `_conflict` / `_drawn_conflict`'s full sentence
formatting cost on every native near-obstacle rejection, when a scan only
ever keeps one example sentence per bucket. See the spec's matching
section for the profile that motivated this (a `default`-config profile
specifically, after Task 6/7 left `physical` well over 2x but `default`
near 1x).

**Files:**
- Modify: `src/placemat/occupancy.py` (`_edge_or_reservation_conflict` extracted from `legal()`; `legal_bucket`, `_native_bucket`, `_COPPERISH`; `_reason_key` moved here from `placer.py`)
- Modify: `src/placemat/placer.py` (`sweep()` inside `scan()` calls `legal_bucket` instead of `legal`; imports `_reason_key` from `occupancy` instead of defining it)
- Test: `tests/test_native_bucket.py`

**Interfaces:**
- Produces: `Occupancy.legal_bucket(item, placement, clearance, others, blame) -> tuple[str, Callable[[], str]] | None`.

- [x] **Step 1: Extract `_edge_or_reservation_conflict`** from `legal()`'s body, no behaviour change - `legal()` calls it and returns its answer unchanged when it fires.
- [x] **Step 2: Move `_reason_key`** to `occupancy.py`; `placer.py` imports it from there (re-exported, so `layout.py`'s existing `from .placer import _reason_key` needs no change).
- [x] **Step 3: Rust-vs-prose fuzz test first** (`tests/test_native_bucket.py`): `_native_bucket(s, o)` against `_reason_key(occ._conflict(s, o, None))` on ~20,000 randomised pairs per envelope from `test_native_conflict.py`'s rich synthetic occupancy, over every kind combination that can actually conflict.
- [x] **Step 4: Run to verify it fails, implement `_native_bucket`**, mirroring `_conflict`'s dispatch order (drawn kinds checked first). Found and fixed a real bug this way: the first draft checked npth-involvement before drawn-kind involvement, misbucketing a body-vs-npth pair.
- [x] **Step 5: Implement `legal_bucket`**, calling the shared edge/reservation check, then (native available) the existing `first_conflict_shifted` call with formatting deferred via a closure, or (no native) `legal()` itself with `_reason_key` on its answer - zero optimisation possible or needed on the no-native path, since `_conflict` has to run there anyway to know the candidate is illegal.
- [x] **Step 6: Wire `placer.py`'s `sweep()`** (inside `scan()` only - `scan_block`'s own sweep is unchanged, left for a follow-up) to call `legal_bucket` and only call `get_reason()` for a bucket not already in `reasons`.
- [x] **Step 7: End-to-end test** (`tests/test_native_bucket.py`): `legal_bucket` against `legal()` - bucket, formatted sentence once fetched, and blame - on 600 randomised candidates each across three real fixture boards and three envelopes.
- [x] **Step 8: Run tests and suite both ways; bench both ways; commit** with the tally and the profile numbers.

---

### Proposed further stages (not started; see spec's own section)

`scan_block` / `layout_block`'s own sweep (the same near-obstacle search
and the same deferred-reason idea, wired a second time), and the cleanup
pass's cost/move functions - see the spec for what each would need.
