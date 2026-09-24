# The native core, stage two: the candidate sweep

Date: 2026-09-25
Status: design, revised 2026-09-24 after 0.33

## Revision after 0.33

0.33 added a crossing and escape cost to every legal candidate (the
crossings-escapes spec). Profile of fairing/SlotControl at 0.33, default
config, native module on (9.7 s unprofiled; under the profiler):

| | cumulative |
|---|---|
| candidate sweeps (`placer.scan`) | 20.9 s of 23.6 |
| legality (`legal_bucket`: edge, keepouts, obstacles) | 8.2 s |
| the scorer on legal candidates (wire, crossings, escapes) | 7.4 s |
| - the crossing leaf search (`Ratsnest.leaf_costs`) | 4.1 s |
| - the escape check (`Escapes.closed`) | 4.3 s |
| candidate pad positions (`candidate_pad_locations`) | 2.0 s |
| the native conflict search itself | 0.5 s |

Legality alone leaves the scorer behind: a third of the time. So the
native sweep does both, in two stages:

1. **Legality** as designed below (edge, keepouts, obstacles).
2. **The scorer**: the wire (each target's weight times its distance), the
   crossing leaf search against the placed ratsnest, and the escape check
   against the placed corridors and copper, for each legal candidate, with
   the pruning floor (a candidate whose wire reaches the best cost seen is
   not weighed further) kept as it is. The native side mirrors the
   occupancy's Ratsnest (anchors, airwires, their grid) and Escapes
   (corridors, their open flags, the blocking copper), updated at each
   commit, lift and unlift through the same calls that update the Python
   ones. Python keeps building both, and stays the reference and the
   fallback.

Bit-identical: the wire sums in the order Python sums; distances use the
CPython hypot port; the crossing test is already whole nanometres; the
escape boxes and polygons use the native `polys_overlap`. Explore draws
among candidates by their exact scores, so explore keeps the unpruned
scorer, as in Python.


## Where the time goes now

Profile of three explore variants of the benchmark's slowest module
(fairing/SlotControl, default config, native module on, 2026-09-25):

| | cumulative | own |
|---|---|---|
| `Occupancy.legal_bucket` (543,739 candidate checks) | 17.7 s | 3.5 s |
| - `shifted_body_box` | 4.6 s | 1.6 s |
| - `_edge_or_reservation_conflict` | 3.3 s | 1.2 s |
| - the native conflict search (`first_conflict_shifted`) | 0.9 s | 0.9 s |
| the scorer's `candidate_pad_locations` (92,550 calls) | 5.3 s | 0.6 s |
| `placer.scan` sweep loop | 29.2 s | 2.6 s |
| dataclass constructions (`Box`, `Location`, `Placement`) | 1.8 s | 1.8 s |
| `round` / `_clean` | 3.9 s | 2.3 s |

Out of about 28 s, the Rust conflict search is 0.9 s (3%). A candidate
check costs about 30 microseconds of Python around a 2-microsecond native
call: building a body box, the edge and keepout tests, rounding, the
objects each candidate allocates. Making the Rust faster gains nothing;
moving the loop into it does.

## The boundary

One native call per sweep pass instead of one per candidate:

```
native_board.sweep(item_handle, points, rotations, face, clearance, obstacles, stop_at_first)
    -> [(x, y, rotation, verdict, detail, body_box)]
```

- `item_handle`: the item's shapes turned and faced at the origin, once
  per rotation and face (the `NativeOriginShapes` handle that exists now),
  extended with the body box at the origin (what `shifted_body_box`
  caches) and whether the item has through or npth shapes (which puts it
  on both faces for the reservation test).
- `points`: the (x, y) of one pass in the order `_grid` yields them. The
  grid, the coarse and fine passes, the refinement around the best spots
  and the `seen` set stay in Python, so the pass structure in `placer.scan`
  is unchanged; the native call takes the rotations and skips what Python
  says was seen.
- `obstacles`: the per-skip-set `NativeObstacles` cache entry that exists
  now.
- the keep-in and the reservations: registered on the Occupancy's native
  handle (below), not passed per call.

Per candidate it runs the tests in the order `legal_bucket` runs them
today and stops at the first failure:

1. the edge: the rectangle board's inset `contains`, or a shaped board's
   `why_not` (disc: the rim and the bore; outline: the loop parity and the
   segment distances), then the cutouts' `why_not`;
2. the reservations, in list order, with the face, owner and net skips;
3. the near-obstacle conflict (`first_conflict_shifted`, unchanged).

`verdict` says which test failed (or none), and `detail` which way: the
edge sentence kind (seven: crosses the rectangle's margin, outside the
board, inside a cutout, past the board's keep-in, past a cutout's keep-in,
past the rim, into the bore), the reservation's index, or the obstacle
pair (shape index, obstacle index). Python turns that into the bucket, the
`Blocker` and, for the first candidate of each bucket, the sentence:

- edge: the sentence is formatted from the kind and the body box, and the
  bucket is `_reason_key` of it, as now (an edge sentence does not always
  bucket as `edge` - "outside the board" buckets under its first word);
- reservation: bucket and blocker memoised per reservation index;
- conflict: `_native_bucket` and `who()` as now, memoised per obstacle
  index for the sweep.

So `rejected`, `reasons` and `blockers` come out as they do today. Legal
candidates are returned for Python to score; with `stop_at_first` (an
unscored scan) the call stops at the first legal one, as the Python loop
does.

What stays in Python: the grid and pass structure, scoring, the tallies,
every message, every decision about what to do with the result.

## Mutation sites (task 1)

What the native keep-in and reservations mirror, and every place it
changes:

- `board_shape`, `board_cutouts`, `board_box`, `edge_margin`: set in
  `Occupancy.__init__`; `Board._add_cutout` replaces the shape or cutouts
  with a new object (never edits one), so the native copy is keyed by the
  objects' identity and rebuilt when either is a different object.
- `reservations`: appended by `Occupancy.reserve` (keepouts, fanout bands,
  labels, rule areas at start and on a cell's commit), and rebound by
  `Occupancy._commit` when a cell's commit drops its old rule areas. Both
  bump a generation number the native copy is keyed by.

## The Occupancy's native handle

Beside the obstacle cache, an Occupancy keeps one native handle holding:

- the keep-in: the edge margin and one of a rectangle with cutouts, a disc
  (centre, radius, bore) with cutouts, or a shaped outline's flattened
  loops (arcs are already flattened for the arithmetic, `outline.py`),
  with the segment grid `Where` builds;
- the reservations: each one's polygon, box, face (or both), owners and
  allowed nets. The raster `Reservation.overlaps` uses for a polygon of 24
  or more vertices is a shortcut to `polys_overlap`'s answer, so the
  native side calls its own `polys_overlap` (already ported and tested)
  for every reservation; the randomised tests below hold it to the
  raster's answers.

Both change during a resolve (a cutout settled, a reservation added or
replaced by source), so the handle carries a generation number: every
change to `board_shape`, `board_cutouts`, `edge_margin` or
`reservations` bumps it, and the sweep rebuilds the handle when it is
stale. Finding every mutation site is task one of the plan.

## Exact arithmetic

The native path must give the same bits as the Python one, not answers
within a tolerance: the rectangle test is an exact `contains`, and grid
points land exactly on margins all the time.

- `_clean` is `round(v, 9)`, which CPython rounds correctly from the exact
  binary value. The native side formats with `{:.9}` (also correctly
  rounded from the exact value, ties to even; spot-checked against Python
  on rustc 1.93) and parses back. A test compares it with Python's on ten
  million values, including every tie class.
- The disc's rim and bore tests use `math.hypot`. CPython's is its own
  algorithm (`vector_norm` in `mathmodule.c`, with its correction step),
  not the C library's `hypot` that Rust's `f64::hypot` calls. The native
  side ports CPython's two-argument path; a test compares bit for bit on
  ten million pairs, including subnormal, huge and equal-magnitude ones.
- Every comparison keeps its Python form and constant (`< margin - NM`,
  `> radius - margin + NM`, strict or not as written).

## The scorer

The scorer (the pad-to-target sum) runs only on legal candidates, but
`candidate_pad_locations` is its cost: a full transform per pad per
candidate. Two options, measured in the spike before choosing:

1. Native pad positions: the same transform arithmetic, operation for
   operation, so the pads land bit-identically; the sum stays in Python.
2. Native pad positions and the sum, using the hypot port above.

The spike decides between them by what option 1 leaves on the table.

## Later stages, measured first

- Blocks: `layout_block`'s satellite loop and `scan_block`'s sweep through
  the same native call.
- The cleanup pass's cost functions, if a profile still shows them after
  the sweep moves.
- Explore's per-variant overhead (running the script and building the
  board for each variant), if it becomes a visible share once a variant's
  resolve is faster.

## Consistency

The pure-Python path stays the reference and the fallback
(`PLACEMAT_NATIVE=0`). Each stage must give identical results:

- the benchmark `same 32` in every configuration against the baseline;
- `bench.py --explore 64` choosing the same variant on every module
  native and pure Python;
- the full suite green both ways;
- randomised native-against-Python tests for each ported piece: the
  rounding and hypot ports bit for bit; the edge test on rectangles,
  discs with bores and shaped outlines with cutouts, with boxes drawn on
  the grid so boundary cases are common; the reservation test with every
  layer, owner and net rule and polygons both sides of the raster's 24
  vertices; a whole sweep's verdicts, buckets, reasons, blockers and
  chosen placement on every fixture board.

## Targets

Measured sequentially, CPU time, Python first then native, as for 0.30:

- a candidate check, legality and score, at 5 microseconds or less on
  average;
- the whole benchmark corpus's default resolve at least twice as fast as
  0.33's native (78-83 s);
- `bench.py --explore 64` at least twice as many variants per second.

## Packaging

Unchanged: the native module builds from the `native` extra and the tagged
release carries wheels.
