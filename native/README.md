# placemat_native

An optional Rust accelerator for placemat's geometry and placement hot
path. placemat runs correctly without it - `src/placemat/geometry.py`
imports it in a `try/except ImportError` and falls back to the pure-Python
implementation, which stays the reference for correctness. See
`docs/superpowers/specs/2026-09-24-native-core-design.md` for what moved
here and why, and `docs/superpowers/plans/2026-09-24-native-core.md` for
the task breakdown.

## Build

Requires a Rust toolchain (1.93+) and `maturin` (installed into
placemat's own venv is fine; it is a build-time tool, not a runtime
dependency of `placemat`):

```
uv pip install --python /path/to/placemat/.venv/bin/python maturin
```

Then, from this directory, with placemat's venv active (or via `--python`):

```
maturin develop --release
```

installs the compiled extension into that venv as `placemat_native`.
`placemat` picks it up on next import. To build a wheel instead of
installing in place: `maturin build --release` (output under
`target/wheels/`).

## Forcing the Python path

Set `PLACEMAT_NATIVE=0` to make placemat use the pure-Python
implementation even when `placemat_native` is installed - useful for
testing the fallback, or if the compiled module ever misbehaves on a
platform it wasn't built for.

## Tests

`cargo test` runs the Rust-side unit tests (pure geometry, no Python
involved). The Python test suite's `tests/test_native_*.py` files compare
native and Python answers directly; they skip themselves (not fail) when
`placemat_native` isn't built, so `pytest -q` is green either way.

## What's in here

- `src/geometry.rs`: pure geometry predicates (`polys_overlap`,
  `poly_distance`, `point_segment_distance`, and what they're built from,
  including the `_rect_of` axis-aligned-rectangle shortcut), ported
  expression-for-expression from `placemat.geometry` so floating point
  comparisons land the same way. No PyO3 dependency in this module - it's
  plain Rust, unit-tested on its own.
- `src/shapes.rs`: the near-obstacle conflict search - `Shape` (carrying
  `owner`, `owner_is_footprint`, `is_lead` and `margin`, each precomputed
  once at marshal time rather than read from Python state per candidate), a
  uniform grid over obstacle boxes, and `Occupancy._conflict` /
  `_drawn_conflict`'s boolean decision (which pair conflicts, not why -
  Python still produces the reason string from the identified pair).
  `ShapeGrid::first_conflict_shifted` takes a candidate's UNSHIFTED,
  once-per-turn shapes plus `(dx, dy)` and shifts them inside Rust, so a
  candidate on an already-registered turn costs two floats crossing the FFI
  boundary. Also plain Rust, unit-tested on its own; see the module's own
  doc comment for how this replaces `ShapeIndex.near()` without a
  two-stage filter.
- `src/pockets.rs`: `placer._largest_rectangle`, ported whole - the
  largest all-free axis-aligned rectangle in a boolean grid, by the
  histogram method. Pure integer/boolean logic, no floating point, so no
  epsilon-boundary question at all (an exact port, not an approximation).
- `src/lib.rs`: the PyO3 module - `#[pyfunction]` wrappers around
  `geometry.rs` and `pockets.rs`, and two classes over `shapes.rs`:
  `NativeObstacles` (a scan's obstacle pool, registered once and queried
  once per candidate from `Occupancy.legal()`) and `NativeOriginShapes` (a
  candidate item's own shapes for one turn, registered once per
  (item, rotation, face) rather than re-marshalled every call). Neither
  class has decision logic of its own. Registration is a Python-side
  concern: `Occupancy` caches one `NativeObstacles` per skip-set
  (`_native_obstacle_cache`) and one `NativeOriginShapes` per turn
  (`_native_shape_cache`), rebuilding only when the underlying state
  changes - see the spec's "Phase 3" and "per-candidate shapes stay
  native" sections.

## Packaging

Not decided here. This README covers building for local development.
How a released placemat ships the compiled extension to a user's machine
(a prebuilt wheel per platform, building from source at install time, or a
manual opt-in step) is a distribution decision left to the project - see
the spec's "Packaging" section.
