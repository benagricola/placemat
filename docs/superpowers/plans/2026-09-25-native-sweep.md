# Native Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One native call judges a whole sweep pass - edge, reservations and obstacles - so a candidate check costs a few microseconds instead of about thirty.

**Architecture:** The board's keep-in and the reservations are registered natively beside the existing obstacle index; `native.sweep` takes a pass's candidates and returns (legal, bucket, blocker, body box) for each; `placer.scan` calls it when the module is present and falls back to `legal()` per candidate when not. Scoring, messages and all decisions stay in Python.

**Tech Stack:** Rust (PyO3, the existing `native/` crate); Python standard library.

**Spec:** `docs/superpowers/specs/2026-09-25-native-sweep-design.md`

## Global Constraints

- Identical results native and pure Python: bench `same 32` x3 against `fixtures/bench.json`; `bench.py --explore 64` the same variant on every module both ways; the suite green with and without `PLACEMAT_NATIVE=0`.
- Every tunable a setting with a default; generic wording; plain ASCII; no attribution lines in commits.
- Timings: CPU time, sequential, Python first then native, ratios reported.

---

### Task 1: Spike and profile

- [ ] Prototype `native.sweep` over the obstacle test alone (edge and reservations still in Python) on fairing/SlotControl; measure the candidate-check cost and the sweep's share; decide the scorer option (spec: The scorer) from what the prototype leaves.
- [ ] Record the numbers in the spec; commit.

### Task 2: The board's keep-in, native

**Files:** `native/src/board.rs` (new), `native/src/lib.rs`, `src/placemat/occupancy.py` (register the keep-in when an Occupancy is made and when a cutout is settled), tests `tests/test_native_board.py`.

- [ ] Failing tests: native and Python edge verdicts identical on 100,000 random body boxes against a rectangle board with and without cutouts, a disc with a bore, and a shaped outline with arcs and cutouts, at several edge margins, including `past_edge` items.
- [ ] Implement; `cargo test`; suite both ways; bench; commit.

### Task 3: Reservations, native

**Files:** `native/src/reservations.rs` (new), `native/src/lib.rs`, `src/placemat/occupancy.py` (register each reservation on `reserve()` and a cell's re-reservation on commit), tests `tests/test_native_reservations.py`.

- [ ] Failing tests: native and Python reservation verdicts identical on random boxes against keepouts (with `layers=`, `allow=` nets and owners), labels, fanout bands and a cell's rule areas, including polygons of many vertices (the raster path).
- [ ] Implement; tests; bench; commit.

### Task 4: `native.sweep` in the scan

**Files:** `native/src/sweep.rs` (new), `src/placemat/placer.py` (`scan` asks the native sweep per pass; the first candidate of each bucket gets its sentence from Python's `legal()`), tests `tests/test_native_sweep.py`.

- [ ] Failing tests: on every fixture module, a scan's chosen placement, tried count, rejection tallies, first reasons and blockers are identical native and Python, for scored and unscored scans, at several rotations and both faces.
- [ ] Implement; suite both ways; bench `same 32` x3; `bench.py --explore 64` identical both ways; commit with the tally and timings.

### Task 5: The scorer

- [ ] The option the spike chose: native pad positions (bit-identical transform), and the native sum only with a ten-million-pair bit-equality test of the hypot port. Tests, bench, explore bench identical; commit.

### Task 6: Measure and decide the later stages

- [ ] Sequential timings (corpus default/solve/physical, the core board, `bench.py --explore 64`), Python then native, against the spec's targets; profile what remains; write in the spec whether blocks, the cleanup pass or explore's per-variant overhead is next, with numbers.
- [ ] Docs (`native/README.md`, the spec), release; commit.
