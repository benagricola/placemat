# Performance: zone width, give way, the sweep's Python

Status: approved (2026-09-30).

Source: Ben asked what could move into the native module (2026-09-30).
Profiles, all under cProfile, which roughly doubles pure-Python time:
- **The whole-board test board's checks** (`placemat check` on the written board):
  1500 s. The zone-fill width was 1497 s of it:
  - `_Fill.touching` 1228 s: about a billion `point_segment_distance` calls;
  - `_Fill._reach` 234 s;
  - the distance transform 16 s.
- **The whole-board test board's placement** (`run`, up to the write): 727 s.
  - `giveway.resolve` took 552 s over 19,657 calls.
  - The native sweep took 70 s.
- **The bench's modules** (default and physical configs): 127 s. The native
  sweep was 10.6 s; the Python round it about 45 s:
  - `_decode` 20.2 s;
  - `_grid` 8.5 s;
  - `native_sweep`'s own loop 8.3 s;
  - `_native_obstacle_index`, rebuilt for each scan, 5.0 s.

Nothing here changes a result. Every change is judged by identical output:
- the same plans (bench tally "same 32" on every config, and identical plan
  digests);
- the same check verdicts, and the same refusal sentences.

## 1. Zone width

**Algorithm first.** `touching(polys, tau)` asks, for each fill cell at
least `tau` from the fill's edge, whether a disc of `radius(tau)` round it
reaches the copper. It does this by measuring the cell's distance to every
edge of the copper. The copper is often a pour with thousands of edges.

Instead:
- Rasterise the copper (the entry's or the exit's polygons) on the fill's
  own grid.
- Take the distance transform to it, with the same exact two-pass
  transform `_Fill` already uses.
- A cell touches when its distance to the copper is at most `radius(tau)`
  plus half a step, the tolerance the current test allows.
- One transform per copper item per fill, cached on the `_Fill`, replaces
  the per-cell edge scan for every level of the width search.

The current test is exact to the copper's edges; the raster is exact to
half a cell. So the Python version is compared with the current one on the
tests and the whole-board test board. A width may change by at most one step
(`check.zone_step`), and a changed verdict is reported, not assumed.

**Then native.** `_Fill` moves to Rust as `NativeFill`, in a new
`native/src/fill.rs`:
- rasterisation, the distance transform, the copper transforms;
- the breadth-first `_reach`;
- the level search in `width`.

Python keeps the choice of the neck point and the sentence. A parity test
runs both on the current-path tests' fills and on a slit fill, and requires
identical widths and neck cells.

Target: the whole-board checks under 30 s, unprofiled.

## 2. Give way

`resolve` runs for every candidate spot that is legal apart from its vias:
19,657 times on the whole board, each searching up to `place.via_move` of offsets
for each via that meets something.

**Split each via's move search into a part that holds for the whole scan
and a part that depends on the candidate.**
- For a via already placed (part 1 of `resolve`), the board it moves on
  does not change during a scan. Only the item being placed does.
- So, once per scan and per placed via near the region, compute the move
  offsets clear of the board less the item: its ring, hole and tail. This
  gives the via's clear offsets, nearest first.
- Each candidate then checks only those offsets against its own copper.
- Share targets are listed the same way once per scan, each with its tail
  judged against the board; per candidate only the tail against the item
  remains.
- For the item's own vias (part 2), the board moves relative to the via at
  each candidate. There, the offsets are judged natively: a new
  `NativeObstacles.first_clear_offset(shapes, offsets, clearance)` returns
  the first offset at which the via's shapes, shifted, meet nothing. It
  reuses the sweep's obstacle index and conflict judge, with one call per
  via instead of one Python conflict test per offset per obstacle.

The rest of give way (drops' keep shares, the report, apply and undo) stays
in Python.

Target: give way under 15% of the whole board's placement time, down from 76%.
The same actions on the give-way tests and the whole board.

## 3. The sweep's Python

Each of these makes the same calls with the same results:
- **`_decode`** builds a refusal's moved shape before looking in its cache.
  It looks first, and builds the shape only when it must sentence it.
- **`_grid`** rebuilds the candidate grid for every sweep. The offsets for
  a (radius, step) are cached, sorted by distance, and moved to each
  centre.
- **`native_sweep`'s loop** builds (x, y, turn) triples through a `seen`
  set in Python. It sends the points and the turn count, and the native
  side skips what was seen, keeping the set for the scan.
- **`_native_obstacle_index`** is rebuilt for every scan. It is kept per
  occupancy version and region, and rebuilt only when a commit changed
  what it holds.

Target: the bench's Python round the sweep from about 45 s to under 15 s
profiled.

## 4. A bench case this size

The bench's modules carry no via fields and no zone fills worth measuring,
so neither slowdown showed. The bench gains a whole-board case: a
six-layer test board of 31 cells, with via fields and zone fills, and a
layout script placing its cells, committed under `fixtures/`.

Timed separately:
- `bench.py --board` runs its placement;
- `bench.py --checks` runs its checks.

The commit that lands each part of this spec states both times.

## Order

1. Zone width in Python (the largest cost, and a small change).
2. The bench case, so each later step is measured.
3. The sweep's Python.
4. Give way.
5. `NativeFill`.

Each is its own commit, with the bench tally and the timings.

## Verification

- Zone width: the current-path tests pass unchanged; the whole board's verdicts
  match, or each difference is at most one step and listed.
- NativeFill: parity with the Python `_Fill` on every test fill and on the
  whole board's fills.
- Give way:
  - the give-way tests pass unchanged;
  - the whole board's give-way actions are identical before and after;
  - `test_a_sweep_whose_vias_give_way_is_the_same_native_or_not` passes.
- The sweep: `test_native_sweep` and `test_native_legal` pass; bench
  "same 32" on every config.
- Timings against the targets above, unprofiled, stated in each commit.
