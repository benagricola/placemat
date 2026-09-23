# A native core for the placement hot path

Date: 2026-09-24
Status: implemented (Phases 1, 2 and 3 landed; see "Proposed further
stages" for what is not started, and the plan's Task 4/5 for what each
phase's own report covers)

**Note on the profile below:** it was taken against the branch point before
this work started. Placemat's own `main` gained three Python-side
speed-ups to the same code path while this was in progress (commit
0b642da: `legal()` turns a part's shapes once per rotation for the
courtyard envelope too, and `polys_overlap` answers two axis-aligned
rectangles from their boxes; c785a04: the courtyard-touch comparison
allows a nanometre; e2614d8: `polys_overlap` catches a coinciding-outline
case the edge walk missed). This work rebased onto that and ported the
CURRENT algorithms (the profile's numbers are still representative of
where the cost is, since the rectangle shortcut helps rectangle-vs-rectangle
pairs specifically and the overall shape of the profile is unchanged; the
Rust code matches what is on `main` today, not what is described in this
paragraph's diff summaries). See "Phase 2" below for the numbers measured
against the current code.

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

### Phase 2: batched near-obstacle conflict search (implemented this round)

`Occupancy.obstacles()` registers its shape list into a native
`NativeObstacles` index once per call (mirrored on the returned
`ShapeIndex` as `idx._native`), the same object `legal()` already reuses
for every candidate in a sweep (`others`). Per candidate, `legal()` passes
its own (already-transformed) shapes to `first_conflict(...)` and gets back
the FIRST conflicting (shape, obstacle) pair, or none - `native/src/shapes.rs`
replicates `_conflict` / `_drawn_conflict`'s BOOLEAN decision (the gap
thresholds, the courtyard touch depth including its `+ 1e-9` allowance, the
box-gap short-circuit before `poly_distance`, `vias_block_courtyards`) to
find that pair, but formats nothing. Python then calls the existing,
untouched `Occupancy._conflict` on that one identified pair to produce the
reason string and `Blocker` - the string a script sees is still produced by
the reference implementation, byte for byte. A native/Python disagreement
on the identified pair (native says conflict, `_conflict` on the same pair
says none) raises `AssertionError` rather than silently resolving one way -
fuzz testing (below) found none, but a silent divergence would be worse
than a loud one.

**Kept in sync with upstream (commit "A through-hole part claims only its
holes on the far face"):** a courtyard's own faces no longer span both
faces for a through-hole part (only its holes do - a Python-side shape
construction change in `_fp_shapes`, no Rust change needed for that part
alone), and `_conflict`'s courtyard branch gained a rule ahead of the
via/npth one: a courtyard over ANOTHER footprint's own through-hole lead
(`Occupancy._is_lead`/`._leads` - a plated through pad standing proud of
the far face, not a thermal via flat under its own exposed pad) conflicts
on `polys_overlap` alone, whatever `vias_block_courtyards` says, and never
falls through to the via rule below it. This needed two fields Phase 2
had deliberately left off `shapes::Shape` as "not needed to decide a
conflict" - `owner` (the rule compares two shapes' owners directly, not
just whether either is a footprint) and a precomputed `is_lead` bool
(`(owner, label) in Occupancy._leads`, computed once at marshal time the
same way `owner_is_footprint` already was, since `_leads` is fixed for an
Occupancy's whole life). `PyShape` grew from a 6-tuple to an 8-tuple
accordingly; every caller (`_to_native_shape(_shifted)`, both test files'
tuple builders) updated together. New coverage: `native/src/shapes.rs`
unit tests for the lead rule (blocks regardless of `vias_block_courtyards`,
not blocked for a part's own lead, falls through correctly for a
through pad that is not a lead) and a positive-control Python test
(`test_conflict_agrees_on_a_courtyard_over_another_parts_lead`) that
shifts a real courtyard onto a real lead pad and asserts both engines
call it a conflict, not just that they agree with each other.

`ShapeIndex.near()`'s own two-stage filter (a coarse box test at the
candidate's whole reach, then a precise per-shape test) is not mirrored as
two stages: the coarse box is provably a superset of the precise one
(`Occupancy.__init__` asserts `_gap >= gap_for(s)` for every shape kind),
so `ShapeGrid`'s single per-shape grid query at the shape's own box and gap
finds the same obstacles, in the same order, as `near()` + the per-shape
filter together would - see the `shapes` module's own doc comment.

**Correctness testing**, all zero mismatches: `native/src/shapes.rs`'s own
unit tests (each `_conflict` / `_drawn_conflict` rule, the courtyard-touch
epsilon, a via not blocking a body); `tests/test_native_conflict.py` (the
boolean decision alone, ~90,000 randomised shape pairs across every
envelope, real shape kinds including a synthetic npth and a via, the
`vias_block_courtyards` house rule, and the exact touch boundary);
`tests/test_native_legal.py` (the full near-obstacle search end to end - a
verdict, a reason string and a blame tuple - on a synthetic board and on
three real fixture boards under multiple envelopes and clearance
overrides, ~6,400 randomised candidates). The one bug this found was in the
test helper, not the port: an early draft hardcoded `owner_is_footprint =
False` for every shape, which made every body/pad and body/through rule
read as "let it through" - caught because the fixture-board comparison
disagreed with the live `Occupancy.legal()`.

**Measured effect.** A/B within one process, alternating native and Python,
`time.process_time` (not wall clock) and ratios rather than absolute
seconds, on a 5-module subset (the largest fixtures) across all three
configs, 4 rounds. This machine was in power-save and under concurrent load
from another process throughout, which shows: 1.60x, 1.74x, 1.00x, 1.54x -
median 1.24x. Noisier and more modest than Phase 1's predicate-level
numbers (12-34x), consistent with the marshalling-cost finding below.
Remeasured for the persistent-index change below under quieter conditions.

Profiling
`legal()` with native wired (SlotControl, `physical`) found the win was
smaller than the Phase 1 profile's arithmetic suggested, and why: handing
a candidate's shapes to native costs real Python-side marshalling
(`_to_native_shape_shifted`: building a plain tuple, including a shifted
polygon, per candidate shape, for every shape - not only the ones that
turn out to conflict). An early version of this wiring built a full
`occupancy.Shape` object (a dataclass, with its own box) for every
candidate shape unconditionally before converting each to a native tuple -
1.1M `Shape.__init__` calls on the SlotControl/`physical` profile alone,
most of them for shapes that were never the ones that conflicted. Fixed:
only the ONE shape native identifies as the conflicting one is ever turned
into a full `Shape` (to hand to the untouched `_conflict` for its
message); every other candidate shape is marshalled straight from the
turned-once-per-rotation origin shape to a native tuple, no intermediate
object. This roughly halved `legal()`'s own (non-native, non-`_conflict`)
time in the same profile (7.6s to 3.4s tottime over 64,567 calls). Even
after that fix, the per-call marshalling (building a plain tuple with a
shifted polygon for every candidate shape, once per `legal()` call) is
larger than native's own compute (`first_conflict` itself measured ~1.9s
of tottime in the same profile, against ~5.3s for
`_to_native_shape_shifted`) - crossing the FFI boundary is not free even
"once per call", and for a courtyard-envelope part (one shape) it is
proportionally worse than for physical (several shapes, but still fewer
crossings than obstacles). A further win is available by caching the
native index across scans (see "Left for a follow-up" below) rather than
rebuilding it - and re-marshalling every candidate shape from scratch -
on every `Occupancy.obstacles()` call, which the current implementation
still does.

Not ported in Phase 2 either: `board_shape.why_not` (the polymorphic
rectangle/disc/outline edge and cutout test, run once per candidate before
obstacles) and `Reservation.overlaps` (run once per reservation per
candidate). Both are cheap relative to the near-obstacle search in the
profile and are not the bottleneck; they stay Python until measurement says
otherwise.

### Phase 3: a persistent native obstacle index (implemented this round)

Followed on directly from Phase 2's own "left for a follow-up" note (below,
kept for the record): `Occupancy.obstacles()` was rebuilding a fresh
`NativeObstacles` index - marshalling every obstacle shape into a native
tuple again - on every call, which is once per `scan()`, reused across
every candidate in that one sweep but not across scans. A `scan()` with a
wide radius amortises this well (hundreds of candidates share one
registration); a tight local search (`cleanup.py`'s per-key hints, a
freedom's several `_slide()` calls before its item commits) does not - it
paid the same registration cost for a handful of candidates each time.

Landed as the first of the two options the earlier note weighed: one
cached index per distinct skip-set (`geom.owners | self.pending`), on the
`Occupancy` itself (`_native_obstacle_cache`), rather than extending
native's grid query to filter by owner at query time. Reasoning: the
skip-set is small and usually just one item's own ref (plus a shrinking
`pending`), so per-skip-set caching captures the common case (repeat
`obstacles()` calls for the SAME item between commits) without adding an
owner field, a skip-set argument, or per-obstacle string-set membership
checks to the Rust side - the query-time-filtering alternative is still
open if a profile later shows this isn't enough. `commit()`, `add_copper()`
and the (rare, post-init) lazy path in `_register()` clear the whole cache,
since any of them can change what is an obstacle for any skip-set.

One behaviour changed on the way: the cached index is built from EVERY
non-skipped shape on the board, not the `region`-filtered subset
`obstacles()` builds for its returned `ShapeIndex` (still built and
returned unchanged, for the non-native path and for `layout_block`'s
member-vs-member `.near()` calls, which do not go through this cache).
This is safe because `region` was always a Python-side performance
pre-filter, never a correctness one: any obstacle a candidate's own
near-box-and-gap query would actually find is, by construction
(`scan()` sizes `region` to contain every candidate's own reach), also
inside `region` - so dropping the pre-filter for the native path can only
add obstacles nothing ever queries near, never change which one a search
finds first. Confirmed by the same test suite Phase 2 used (`legal()`
toggled native on/off in the same process, and the full corpus bench).

**Correctness testing:** `pytest -q` and `PLACEMAT_NATIVE=0 pytest -q`
both green, no test changes needed - `test_native_legal.py`'s
`test_the_actual_wired_legal_agrees_with_itself_native_on_and_off` calls
the real, shipped `Occupancy.legal()` both ways and needed no changes to
cover this, since the cache is an internal detail behind the same
`others._native` seam. `fixtures/bench.py --jobs 4`: `same 32` in every
config against main's current `fixtures/bench.json`.

**Measured effect:** A/B within one process, alternating native and Python
(one pass each order per config, to cancel first-run warmup bias),
`time.process_time`, over the WHOLE bench corpus (all 34 fixture modules,
not a subset), power-save off: `default` 1.11x (native 52.7s, Python
58.7s), `solve` 1.37x (46.8s vs 64.1s), `physical` 2.44x (77.1s vs 187.9s).
Larger than Phase 2's own subset numbers (median 1.24x, taken under
power-save and contention) and consistent with the mechanism: `physical`
gives an item the most shapes per candidate (pads, mask, silk, body), so
the most `_conflict`/`_drawn_conflict` calls and obstacles per query, and
the most to gain from not re-marshalling the obstacle pool on every
`obstacles()` call. `default` gains the least, matching the profiling
note above: for a single scan-then-commit item (the common case in the
searched tier), Phase 3 does not change how many times the obstacle pool
gets marshalled at all (still once, on that one scan) - its win is for
repeated `obstacles()` calls between commits (cleanup's per-key hints,
`_slide`'s several freedoms), and does nothing for the still-unaddressed
per-candidate cost of marshalling each candidate's OWN shapes on every
`legal()` call (the earlier profiling's larger remaining cost). A full,
authoritative sequential Python-then-native comparison is planned from
the main session after merge, on a quiet machine.

### Phase 2's original follow-up note, superseded by Phase 3 above

`Occupancy.obstacles()` builds a fresh `NativeObstacles` index (and
marshals every obstacle shape into a native tuple) on every call, which is
once per `scan()` - reused across every candidate in that one sweep, but
not across scans. A `scan()` with a wide radius amortises this well
(hundreds of candidates share one registration); a tight local search
(`cleanup.py`'s move/swap pass, small radius and step) does not - it pays
the same registration cost for a handful of candidates. Caching the index
on the `Occupancy` itself, keyed by what it excludes (`geom.owners |
self.pending`, which differs per item), and invalidating it on `commit()`
rather than rebuilding fresh every call, would help this case, but was not
attempted here: it needs either one cached index per distinct skip-set (a
memory/staleness trade-off) or extending native's grid query to take a
skip-set and filter obstacles by owner at query time (rather than at
Python-side registration), which is more Rust surface than this round's
budget covered carefully. Flagged for the user rather than built in a
rush.

### Kept in sync with upstream: the margin allowance (rebase onto "Courtyards may overlap by the margin KiCad's own lie inside them")

Main's courtyard-vs-courtyard touch rule stopped being a flat threshold:
`place_courtyard_touch`'s own default dropped to 0.0, and each footprint
now carries `courtyard_margin` (how far KiCad's own courtyard polygon lies
inside `courtyard_box`); the allowed overlap is
`max(place_courtyard_touch, margins[a] + margins[b] - 0.001)`, read off
`Occupancy._margins` (a `{ref: margin}` dict, only entries with a nonzero
margin). Ported: `shapes::Shape` gained a `margin: f64` field (like
`owner_is_footprint` and `is_lead`, computed once at marshal time, since
`_margins` is fixed for an Occupancy's life); `conflict()`'s
courtyard-courtyard branch computes the same `allowed` expression, in the
same order, before the same `+ 1e-9` boundary comparison. `PyShape` grew
from an 8-tuple to a 9-tuple; every builder
(`_to_native_shape(_shifted)`, both native test files' tuple helpers)
updated together, same pattern as the lead-rule change before it.

One pre-existing test broke on the rebase, unrelated to native:
`test_conflict_agrees_at_the_courtyard_touch_boundary` asserted an exact
epsilon case that depended on `place_courtyard_touch`'s OLD default
(0.02); with the default now 0.0 and no margin on its synthetic footprint,
the pure-Python `Occupancy._conflict` itself started calling that case a
real overlap (correctly - a flat 0.0 touch setting no longer forgives it,
by design). Fixed by setting `place_courtyard_touch` explicitly in that
test rather than relying on the default, which restores the epsilon case
it was written to check without depending on a value the project has since
changed on purpose.

New coverage: `native/src/shapes.rs` unit tests for overlapping by less
than / more than the combined margin; `tests/test_native_conflict.py`'s
`test_conflict_agrees_on_courtyards_overlapping_by_their_kicad_margin`, a
positive control with two REAL footprints carrying `courtyard_margin` (so
`occ._margins` is populated the way a real board populates it, not a
hand-built dict), checked on both sides of the boundary in both engines.
`test_the_actual_wired_legal_agrees_with_itself_native_on_and_off`
already exercises this on real fixture boards (their footprints' real,
KiCad-read `courtyard_margin` values) without needing any change - the
strongest coverage here, since it calls the shipped `Occupancy.legal()`
both ways, not a re-implementation.

`pytest -q` and `PLACEMAT_NATIVE=0 pytest -q`: both green.
`fixtures/bench.py --jobs 4`: `same 32` in every config against main's
current `fixtures/bench.json`.

### Stage: per-candidate shapes stay native (implemented)

Followed Phase 2's own "Left for a follow-up" finding: even with a
persistent obstacle index (Phase 3), `legal()`'s native path was rebuilding
a plain-tuple, shifted polygon for EVERY candidate shape on EVERY call
(`_to_native_shape_shifted`), although the shapes themselves are already
turned once per (rotation, face) and cached (`_origin_shapes`). Added
`NativeOriginShapes` (native/src/lib.rs): a handle over a turned item's
UNSHIFTED shapes, registered once per (item, rotation, face) exactly the
way `_origin_shapes` caches the Python turn (`Occupancy._native_origin_shapes`).
`ShapeGrid::first_conflict_shifted` (native/src/shapes.rs) takes that
handle plus `(dx, dy)` and shifts each shape's bbox - and, only for one
actually near enough to test, its polygon - inside Rust, so a candidate at
a new position on an already-registered turn costs two floats crossing the
FFI boundary, not a rebuilt polygon per shape. `_to_native_shape_shifted`
(no longer called) removed.

**Measured effect**, A/B within one process (`time.process_time`,
alternating native/Python, one pass each order per config, whole 34-module
corpus, default `[place] rotations = "all"` so most searched parts try
four turns): `default` 1.05x (127.5s native vs 133.9s Python), `solve`
1.14x (110.4s vs 125.9s), `physical` **3.03x** (110.7s vs 335.3s) - a real
jump from Phase 3's own 2.44x on a smaller subset, consistent with this
being the cost Phase 2's profiling flagged as still-unaddressed.

**Also found and fixed while profiling this stage:** upstream added
`_rect_of` (two axis-aligned rectangles overlap iff their boxes do, no
vertex walk needed) to `geometry.polys_overlap`'s Python dispatch before
this project started. The native port deliberately hadn't mirrored it,
reasoning "Python checks it before ever calling native" - true for calls
through that dispatch, but `shapes::conflict` calls
`geometry::polys_overlap` directly, Rust to Rust, never through Python's
dispatch at all. A courtyard pair - overwhelmingly rectangles - is the
near-obstacle search's dominant case, so the hot path was never getting
upstream's own shortcut. Fixed: `rect_of` ported into
`native/src/geometry.rs`, checked in the same place Python checks it.

pytest -q and PLACEMAT_NATIVE=0 pytest -q: both green throughout.
bench (native built, --jobs 4): default, physical, solve: better 0, worse
0, same 32 each, against main's current fixtures/bench.json, both times.

### Stage: pockets() / _largest_rectangle (implemented)

A later request asked for the whole performance-critical core to move to
Rust in one continuous push, in a rough proposed order: (1) per-candidate
shapes stay native [done, above], (2) the whole candidate sweep of
`scan()`, (3) `scan_block` / `layout_block`, (4) `pockets()`, (5) the
cleanup pass. Before taking (2) on faith, profiled the CURRENT (post
per-candidate-shapes-native) code on `SlotControl`/`physical` to see where
time actually goes now, the same way every earlier boundary decision in
this spec was made - not by guessing at the proposed order's payoff.

Two things followed from that profile:

1. **`scan()`'s own remaining Python cost is smaller, and less removable,
   than the proposed order assumes.** `sweep()`'s own loop tottime (2.05s)
   plus `legal()`'s own tottime (3.31s) together are real but modest next
   to the ~39s instrumented total. More importantly, `_conflict`'s reason
   STRING still has to come from the real, untouched Python `_conflict` /
   `_drawn_conflict` (Phase 2's own safety design: native decides which
   pair, Python's reference implementation formats the answer) - and
   `_reason_key`, which buckets a rejection for `scan()`'s `rejected` /
   `reasons` Counters, matches on SUBSTRINGS OF THAT PROSE, not on
   `Blocker.kind` (a pad/through/copper clearance failure's message always
   says "... copper on ...", so it buckets as `"copper"` regardless of
   whether the obstacle was a pad, a via or a track; a drawn-envelope
   silk/mask/body message contains none of the checked words at all, so it
   buckets on the OWNER's name instead). Reproducing this natively would
   mean re-implementing prose generation (including `who()`'s cell-name
   lookups) in Rust - exactly what Phase 2 deliberately kept in Python - or
   still calling back into Python once per REJECTED candidate (the ~85%
   majority) to get it, which is close to what happens today already
   (native only decides the pair; Python still formats it). Either way, a
   full sweep port's real ceiling is `sweep`'s + `legal`'s own loop
   overhead alone, not another `_conflict`-search-sized win - useful, but
   the smallest of the remaining stages, and the riskiest (coarse-then-fine
   refinement, exact tie-breaking, an arbitrary per-script `score` closure
   to call back into).
2. **`pockets()`'s `_largest_rectangle` costs more than `scan`'s own loop
   does, in the same profile** (2.79s tottime over only 776 calls - the
   single biggest tottime entry after `legal` itself) **and needs none of
   the above.** It is pure integer/boolean array logic - a grid of cells,
   the largest all-free rectangle in it - with no floating point, no
   conflict decision, no reason string, no `who()`. A native answer is not
   "the same to a tolerance", it is identical, for every input.

Reordered on this evidence: `_largest_rectangle` ported whole
(`native/src/pockets.rs`) ahead of the full `scan()` sweep. `placer.py`
dispatches to `_native.largest_rectangle(free, rows, cols, need_r, need_c)`
when built, else the unchanged Python body; same signature, same return
shape, so `pockets()` itself needed no change.

**Correctness testing:** `native/src/pockets.rs` unit tests (empty and
fully-blocked grids, a single free cell, a whole free grid, a minimum-size
prune, and - since ties are possible with integer areas, unlike the
floating-point predicates - a dedicated test that Python's strict `area >
best[0]` tie-break, kept identical in Rust, picks the first-found
rectangle in row-then-column order); `tests/test_native_pockets.py`
compares native against the reference Python body directly (not through
the dispatch) on 500 randomised grids up to 20x20 at varied fill rates and
minimum sizes, EXACT equality throughout (no epsilon needed - this is the
one ported surface with no floating point in it at all), plus a
dispatch-wiring test with a fake native module.

pytest -q and PLACEMAT_NATIVE=0 pytest -q: both green.
bench (native built, --jobs 4): default, physical, solve: better 0, worse
0, same 32 each, against main's current fixtures/bench.json.

### Proposed further stages (not started; for the user to confirm)

Remaining from the later request's list: the whole candidate sweep of
`scan()` (now understood to be the smallest and riskiest of the group, per
the finding above - still worth doing, just not the next-highest payoff),
`scan_block` / `layout_block` (the same near-obstacle search wired a
second time, for a block's members laid out together - should be a
smaller, mostly-mechanical follow-on once `scan()` itself is done, since it
reuses the same native primitives), and the cleanup pass's cost and moves
(`cleanup.py`'s `hp` / `cost` / `where` and layout.py's `score` closures
are pure coordinate/distance arithmetic on already-placed pads - no
conflict decision or reason string at all, so - like `pockets()` - a clean
port with no message-formatting entanglement; the profile shows these
functions with real cumulative time, `cost`+`hp`+`where` alone summing to
several seconds, so this may be the next-best payoff after `scan()`'s
sweep or even ahead of it, but was not profiled in isolation to confirm
that before this report). Each remaining stage deserves the same
spec-numbers-plan-TDD treatment already applied above; see the plan
document for a task sketch.

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
