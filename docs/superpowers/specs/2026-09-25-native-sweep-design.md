# The native core, stage two: the candidate sweep

Date: 2026-09-25
Status: design

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
check costs about 30 microseconds of Python round a 2-microsecond native
call: building a body box, the edge and keepout tests, rounding, the
objects each candidate allocates. Making the Rust faster gains nothing;
moving the loop into it does.

## The boundary

One native call per sweep pass instead of one per candidate:

```
native.sweep(item, candidates, face, clearance, obstacles, board, reservations)
    -> [(legal, bucket, blocker, body_box)]
```

- `item`: the item's shapes and body box turned and faced once per
  rotation (the per-turn registration that exists now, extended with the
  body box and the reach used for the edge test).
- `candidates`: (x, y, rotation) in the order the Python sweep visits
  them; the grid, the coarse and fine passes and the ordering stay in
  Python, which only asks the native call to judge each pass.
- `board`: the keep-in - a rectangle, a disc's polygon or a shaped
  outline with its cutouts - and the edge margin, registered once per
  resolve (it changes only when a cutout is settled).
- `reservations`: every reservation's polygon, face, owners and allowed
  nets, registered once and updated as reservations are added.

Per candidate, in the order `legal()` tests today: edge, then
reservations, then the near-obstacle conflict (native already), stopping
at the first failure. It returns the bucket (`edge`, `reservation`,
`courtyard`, ... - the same bucket `legal_bucket` derives today) and the
blocker's index, so the scan's tallies and blame are exact. The prose
reason is formatted in Python for the first candidate of each bucket, as
now.

What stays in Python: the grid and pass structure, scoring, the tallies,
every message, every decision about what to do with the result.

## The scorer

The scorer (the pad-to-target sum) runs only on legal candidates, but
`candidate_pad_locations` is its cost: a full transform per pad per
candidate. Two options, measured in the spike before choosing:

1. Native pad positions: the same transform arithmetic, operation for
   operation, so the pads land bit-identically; the sum stays in Python.
2. Native pad positions and the sum: needs `math.hypot` reproduced
   exactly. CPython's two-argument hypot is its own algorithm, not the C
   library's, and a one-bit difference can change which of two tied
   candidates wins. Taken only with a bit-for-bit test over at least ten
   million random pairs.

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
- randomised native-against-Python tests for each ported piece: the edge
  test on rectangles, discs and shaped outlines with cutouts; the
  reservation test with every layer, owner and net rule; a whole sweep's
  verdicts, buckets, blockers and body boxes on real fixture boards.

## Targets

Measured sequentially, CPU time, Python first then native, as for 0.30:

- a candidate check at 5 microseconds or less on average (about 30 now);
- the whole benchmark corpus's default resolve at least twice as fast as
  0.32's native;
- `bench.py --explore 64` at least twice as many variants per second.

## Packaging

Unchanged: the native module builds from the `native` extra and the tagged
release carries wheels.
