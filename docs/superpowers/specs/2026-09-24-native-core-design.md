# A native core for the placement hot path

Date: 2026-09-24
Status: design

## Problem

`placer.scan()` sweeps a grid of candidate positions and rotations and asks
`Occupancy.legal()` whether each is legal. On the largest module fixtures
this runs `legal()` tens of thousands of times per part, and most calls are
rejections. Every rejection still walks obstacle boxes, transforms shapes
and tests polygons in pure Python. Adding a feature that multiplies the
candidate count (four rotations per part, a finer step) multiplies this cost
directly, so today it needs hand-optimisation in Python (caching turned
shapes at the origin, coarse-then-fine scans, grid-indexed obstacle lookup)
rather than a straightforward implementation.

The ask: a native (Rust) core for this hot path, callable from Python,
optional at import time, with the existing Python path kept as the
fallback and the reference for correctness.

## Method

Profiled `fixtures/fairing/modules/SlotControl` (51 parts, the largest
fixture) under `place_envelope = "physical"` with `cProfile`, resolving
through `fixtures/bench.py`'s `_resolve`. 46.8M function calls, 27.3s
(instrumented; cProfile roughly doubles wall time, so ~12s uninstrumented,
matching the 12.5s this module takes under `--jobs 4` load). The top
contributors by cumulative time inside `scan()` (277 calls, 64567 calls to
`legal()`):

| function | calls | own time | cumulative |
|---|---|---|---|
| `Occupancy.legal` | 64,567 | 5.07s | 23.64s |
| `Occupancy._conflict` | 511,508 | 0.31s | 6.14s |
| `Occupancy._drawn_conflict` | 479,963 | 1.11s | 4.83s |
| `Occupancy.near` (`ShapeIndex.near`) | 59,190 | 1.86s | 3.93s |
| `geometry.polys_overlap` | 105,519 | 0.57s | 3.15s |
| `Box.overlaps` | 11,317,301 | 2.09s | 2.09s |
| `Occupancy.gap_for` | 7,374,703 | 1.03s | 1.03s |
| `geometry.poly_distance` | 2,933 | 0.28s | 1.25s |

Two things follow from this:

1. **The geometry predicates are a small share of the total.** `polys_overlap`
   and `poly_distance` together are ~4.4s of `legal()`'s 23.6s (~19%).
   `legal()`'s OWN time (5.07s, not counting what it calls) plus `near()`'s
   (1.86s) plus the two `_conflict` layers' own time (1.42s) plus
   `gap_for`'s 7.4M calls (1.03s) - all pure Python loop and attribute
   overhead round obstacle lists - is the majority of the cost.
2. A spike that ports only `polys_overlap` / `poly_distance` / `point_segment_distance`
   to Rust, leaving every call site untouched, confirms this: on the same
   module, wall time for the `physical` config went from 12.48s to 11.41s
   (a 9% win); `default` 9.45s to 9.02s (5%); `solve` 6.15s to 5.50s (11%).
   Real, but nowhere near what "stop needing hand-optimisation in Python"
   asks for.

Isolated from the pipeline, the predicates themselves are fast in Rust: on
2000 courtyard-sized rectangle pairs called 200,000 times each,
`polys_overlap` is 12x faster (1.30s Python to 0.11s native) and
`poly_distance` is 34x faster (5.00s to 0.15s). Per-call FFI crossing costs
about 70ns over a trivial Python call (125ns vs 194ns for a call doing real
work) - noise next to the microseconds `legal()` spends per candidate. So
the ceiling on "port predicates only" is set by how much of the total cost
they are, not by crossing overhead, and per the profile that ceiling is low:
most of the cost is Python orchestrating lists of shapes, not evaluating
the polygon math.

**Conclusion: the boundary for a real win is the whole near-obstacle
conflict search inside `legal()`, not the predicates alone** - `near()`'s
box filtering, the per-shape "close" filter, and `_conflict` /
`_drawn_conflict`'s decision logic, batched into one call per `legal()`
invocation. `scan()` already registers a candidate's obstacle pool once per
scan (`others = occ.obstacles(geom, region)`, reused by every candidate in
that sweep - 277 scans for 64,567 `legal()` calls, ~233 candidates per
pool), so obstacles can be registered into Rust once per scan and queried
many times, which is exactly the "register once, not per candidate" shape
the FFI needs to not be paid for on every call.

## Boundary

Two phases, landed separately so each is independently measured, tested and
committed.

### Phase 1: geometry predicates (implemented this round)

`polys_overlap`, `poly_distance` and `point_segment_distance` in
`geometry.py` call into `placemat_native` when it is importable, with the
existing Python body kept verbatim as the fallback and the reference.
Every caller of these three functions across the codebase (`occupancy.py`,
`placer.py`, `checks.py`, `queries.py`, `describe.py`, `layout.py`,
`board_geometry.py`) benefits without being touched, because they all go
through `geometry.py`.

`point_segment_distance` is a pure leaf function (no cache, no polygon-size
dispatch) and is always delegated to native when present.

`polys_overlap` / `poly_distance` are NOT always delegated: `geometry.py`
keeps its existing dispatch on polygon size. A polygon with 24+ vertices
(a keepout or reservation drawn with arcs, tested repeatedly against many
candidates) uses Python's cached `_Prepared` grid, built once and reused;
the plain O(n * m) test used for everything under that size - courtyards,
pads, silk, mask, body, all rectangles or simple outlines - is what goes
native. The two are provably the same boolean answer for any polygon size
(the grid is a cache over the same test, not a different one -
`geometry.py`'s own docstring on `_prepared_overlap` says so), so this
split changes performance only, never the verdict. This is a deliberate,
documented divergence from "port everything": the grid's cross-call cache
has no native equivalent yet, and reservation polygons are rare enough
(board-level keepouts, not one per part) that porting the cache is not
worth doing before Phase 2.

**Divergence:** Rust's `f64::hypot` (libm) and Python's `math.hypot` (a
different, compensated-summation algorithm since Python 3.8) can differ by
1 ULP on the same inputs - confirmed on the spike's random pairs (one
mismatch in 2000: `1.2817787076028189` vs `...186`, a difference of
3e-16). Every comparison in `occupancy.py` carries at least a `1e-9`
tolerance (`_clean` rounds to 9 decimals; `_conflict` / `_drawn_conflict`
compare with `- 1e-9`), so a 1-ULP difference at the 16th significant digit
cannot flip a verdict. Tests compare native and Python distances with an
epsilon, not bit-exact equality, matching how the codebase itself compares
them.

### Phase 2: batched near-obstacle conflict search (next; not in this round)

Design, not yet built: `Occupancy.obstacles()` registers its `ShapeIndex`
into a native structure once per `scan()` (mirroring `ShapeIndex`'s grid),
returning a handle `legal()` reuses for every candidate in that sweep, the
same way `others` already is in Python. Per candidate, `legal()` passes its
own (already-transformed) shapes and gets back the FIRST conflicting
(shape, obstacle) pair, or none - Rust replicates `_conflict` /
`_drawn_conflict`'s BOOLEAN decision (the gap thresholds, the courtyard
touch depth, the box-gap short-circuit before `poly_distance`) to find that
pair, but does not format anything. Python then calls the existing,
untouched `_conflict` / `_drawn_conflict` on that one identified pair to
produce the reason string and `Blocker` - so the string a script sees is
still produced by the reference implementation, byte for byte, and Rust's
job is only to find the same pair Python's linear scan would have stopped
at first. The handle is invalidated (rebuilt) on `Occupancy.commit()`,
matching `ShapeIndex`'s own lifetime (`obstacles()` is called fresh per
scan already).

Expected win, from the profile above: `near()` + `legal()`'s own loop +
both `_conflict` layers + `gap_for` are collectively ~11.4s of this
module's 23.6s `legal()`-cumulative time; collapsing that into one native
call per `legal()` invocation (rather than dozens of Python-level box and
attribute-access calls) is where the multi-x win this project is for would
come from, not from Phase 1's predicate swap. This is scoped as the next
task in the plan and is substantial - it needs `Shape`, `ShapeIndex` and
the `_conflict` / `_drawn_conflict` decision tree ported faithfully,
including every gap/threshold combination silk, mask, body, pad, through,
copper, courtyard and npth can hit - not started this session; see the
plan for its own task breakdown and risk notes.

Not ported in Phase 2 either: `board_shape.why_not` (the polymorphic
rectangle/disc/outline edge and cutout test, run once per candidate before
obstacles) and `Reservation.overlaps` (run once per reservation per
candidate). Both are cheap relative to the near-obstacle search in the
profile and are not the bottleneck; they stay Python until measurement says
otherwise.

## What stays Python, permanently

- All mutable state: `Occupancy.items`, `.reservations`, `.copper`,
  `.pending`, the `_cells` cache. `commit()` still mutates these in Python;
  Phase 2's native handle is a read-only index built FROM them, rebuilt
  when they change.
- `board_shape` (`Box` implicit, `Disc`, `Outline` in `board_geometry.py` /
  `outline.py`) and its polymorphic `why_not`.
- Reason-string formatting and `who()` (cell-name lookups need
  `self.geometry`, a Python object graph not worth mirroring for text).
- `scan()`'s grid generation, coarse-then-fine refinement, and the `score`
  callback (an arbitrary Python closure per script - not something a native
  core can call without paying the same crossing cost this whole exercise
  is trying to avoid, and it only runs on the ~15% of candidates that are
  legal).
- `cleanup.py`'s move/swap search (calls `scan()`; benefits from Phase 1/2
  transitively without its own port).

## Constraints carried from the task

- No required runtime dependency: `placemat_native` is imported in a
  `try/except ImportError`, `_native = None` on failure, and every
  function it would have supplied has the Python body sitting right next
  to the import guard, unconditionally runnable. `PLACEMAT_NATIVE=0` forces
  the Python path even when the module is present (for tests and for
  falling back if the compiled module ever misbehaves on a platform).
- Same verdicts, same reasons, same blame tallies: verified by direct
  native-vs-Python comparison tests on `polys_overlap`, `poly_distance`
  and on `Occupancy.legal()` itself (random candidates against real
  fixture boards, both with the module present and with
  `PLACEMAT_NATIVE=0`), and by the benchmark reporting `same 32` in all
  three configs with native on.
- The crate lives in `native/`, is not on the Python import path unless
  built and installed (`maturin develop` / `maturin build`), and carries
  its own build docs (`native/README.md`).

## Packaging (left for the user)

This spec builds and installs the native module into the dev venv with
`maturin develop` for local iteration. It does NOT decide how a released
placemat ships the compiled extension to a user's machine (a prebuilt
wheel per platform via `maturin build` + CI, vs. building from source at
install time, vs. leaving it as a manual `pip install` step in `native/`
for whoever wants the speed). That is a packaging/distribution decision,
not a correctness one, and is called out in the plan as a stopping point
for the user rather than guessed at.
