# Native Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One native call judges and scores a whole sweep pass - edge, keepouts, obstacles, then wire, crossings and escapes for the legal candidates - so a candidate costs a few microseconds instead of tens.

**Architecture:** The keep-in and the reservations are registered on a per-Occupancy native handle with a generation number; `sweep()` takes one pass's points and rotations and returns each candidate's verdict and detail; `placer.scan` turns those into its tallies, blockers and sentences as now, and falls back to `legal_bucket()` per candidate without the module. Scoring, messages and all decisions stay in Python.

**Tech Stack:** Rust (PyO3, the existing `native/` crate); Python standard library.

**Spec:** `docs/superpowers/specs/2026-09-25-native-sweep-design.md`

## Global Constraints

- Identical results native and pure Python: bench `same 32` x3 against `fixtures/bench.json`; `bench.py --explore 64` the same variant on every module both ways; the suite green with and without `PLACEMAT_NATIVE=0`.
- Bit-identical arithmetic: `_clean` (round to 9 places) and CPython's two-argument hypot ported, not approximated; every comparison keeps its Python form and constant.
- Every tunable a setting with a default; generic wording; plain ASCII; no attribution lines in commits.
- Timings: CPU time, sequential, Python first then native, ratios reported.

---

### Task 1: Spike, profile and mutation sites

- [x] Prototype a sweep over the obstacle test alone (edge and reservations still called from Python per candidate) on fairing/SlotControl; measure the candidate-check cost and what share the edge and reservation tests keep; record in the spec.
- [x] List every site that changes `board_shape`, `board_cutouts`, `edge_margin` or `reservations` on an Occupancy (the handle's generation must bump at each); record in the spec.
- [x] Profile at 0.33 (the spec's revision): legality 35%, the scorer 31%; the scorer goes native (tasks 6-8).

### Task 2: Exact arithmetic

**Files:** `native/src/exact.rs` (new), `native/src/lib.rs` (expose both for the tests), `tests/test_native_exact.py`.

- [x] Failing tests: native `clean(v)` equals `_clean(v)` bit for bit on ten million values (random magnitudes, grid multiples of 0.001-1.0 mm plus sums of them, exact decimal ties at the ninth place, negatives, zero and negative zero); native `hypot(a, b)` equals `math.hypot(a, b)` bit for bit on ten million pairs (random, equal magnitude, one zero, subnormal, near overflow).
- [x] Implement: `clean` by `{:.9}` format and parse; `hypot` ported from CPython's `vector_norm` two-argument path (cite the `mathmodule.c` lines in the comment).
- [x] `cargo test`; the pytest file; commit.

### Task 3: The keep-in, native

**Files:** `native/src/keepin.rs` (new), `native/src/lib.rs`, `src/placemat/occupancy.py` (build the handle's keep-in; bump the generation at each site from task 1), `tests/test_native_keepin.py`.

- [x] Failing tests: the native verdict (none, or which of the seven edge kinds) matches the kind of sentence Python's edge test gives on 100,000 grid-drawn body boxes each against a rectangle with and without cutouts, a disc with and without a bore and cutouts, and a shaped outline with arcs and cutouts, at margins 0, 0.3 and 1.0 mm, and `past_edge` skipping it.
- [x] Implement, porting `Where` (the segment grid), `loops_around`, `segment_box` and the rect/disc/outline/cutout `why_not` order; tests; suite both ways; bench; commit.

### Task 4: Reservations, native

**Files:** `native/src/reservations.rs` (new), `native/src/lib.rs`, `src/placemat/occupancy.py` (register reservations on the handle; generation bump on add and replace), `tests/test_native_reservations.py`.

- [x] Failing tests: the native first-hit reservation index equals Python's on random grid boxes against keepouts with `layers=`, `allow=` nets and owners, through-hole items (both faces), label and fanout reservations, and polygons of 4, 23, 24 and 200 vertices (both sides of the raster threshold).
- [x] Implement with the existing native `polys_overlap`; tests; bench; commit.

### Task 5: `sweep()` in the scan

**Files:** `native/src/sweep.rs` (new), `native/src/lib.rs`, `src/placemat/occupancy.py` (the handle's `sweep`, the detail-to-bucket/blocker/sentence mapping with per-sweep memo), `src/placemat/placer.py` (`scan`'s `sweep()` calls it when native is present), `tests/test_native_sweep.py`.

- [x] Failing tests: on every fixture module, for every scan the resolve makes (recorded by wrapping `placer.scan`), the native and Python scans give the same chosen placement, `tried`, `rejected`, `reasons`, `blockers` and score, for scored and unscored scans.
- [x] Implement; suite both ways; bench `same 32` x3; `bench.py --explore 64` identical both ways; commit with the tally and timings.

### Task 6: The ratsnest, native

**Files:** `native/src/ratsnest.rs` (new), `native/src/lib.rs`, `src/placemat/occupancy.py` (the native mirror updated in `_ratsnest_refresh`), `tests/test_native_ratsnest.py`.

- [x] Failing tests: native `leaf_costs(pads, own, depth)` equals `Ratsnest.leaf_costs` (weighted crossings and crossed escapes, exactly) on random boards of up to 40 nets, with quiet nets weighted 0 and 0.25, own parts excluded, and after random `set_net` updates.
- [x] Implement: anchors per net, airwires with their nanometre ends, the 2 mm grid; the nearest-anchor search in Python's order (ties to the first); the crossing point and the depth test with the hypot port.
- [x] Suite both ways; bench `same`; commit.

### Task 7: The escapes, native

**Files:** `native/src/escapes.rs` (new), `native/src/lib.rs`, `src/placemat/escapes.py` (the native mirror updated in `refresh` and `add_copper`), `tests/test_native_escapes.py`.

- [x] Failing tests: native `closed(item, placement, crossed)` equals `Escapes.closed` on every candidate of every scan of three fixture modules (recorded by wrapping the scorer), and after random commits, lifts and planned copper.
- [x] Implement: corridors and via spots as Python builds them (built in Python, handed over), their open flags, the blocking copper grid, the candidate's pads and own corridors at the origin per turn, shifted.
- [x] Suite both ways; bench `same`; commit.

### Task 8: The scorer in the sweep

**Files:** `native/src/sweep.rs`, `src/placemat/layout.py` (`_scorer` hands its targets, weights and floor to the native sweep), `src/placemat/cleanup.py` (the move and swap scores), `tests/test_native_sweep.py`.

- [x] Failing tests: every scan of every fixture module gives the same chosen placement, score, tried count, rejections and blockers native and Python, for the search and the cleanup pass; explore variants (unpruned) the same.
- [x] Implement: the wire sum in Python's order with the hypot port, the leaf costs and escape check from tasks 6-7, the pruning floor.
- [x] Suite both ways; bench `same 32` x3; `bench.py --explore 64` identical both ways; commit with the tally and timings.

### Task 9: Measure and decide the later stages

- [x] Sequential timings (corpus default, solve and physical, the core board, `bench.py --explore 64`), Python then native, against the spec's targets; profile what remains; write in the spec whether blocks, the cleanup pass or explore's per-variant overhead is next, with numbers.
- [ ] Docs (`native/README.md`, the spec, the migration note if anything a user sees changes), release; commit.
