# Give way, native: a via's whole move judged in one call

Status: draft, for approval.

Source: Ben (2026-09-30), after the per-scan cache (0.62.0) left give way
at about 85% of a whole six-layer test board's placement.

## Where the time is

Profiled on the whole-board test board, 0.62.0, after the cache:
- placement 654 s, of which give way 552 s;
- the native clear-offset search 85 s (26,071 calls);
- the rest is Python, judging each clear offset in turn inside `_give`.

That Python loop, per offset, per via, per candidate:
- `_disc_inside`, whether the moved via still lies inside its pad (12.5
  million calls);
- `still`, whether it still meets what it first met (6.7 million calls,
  95 million edge distances);
- `_shift`, which rebuilds the via's ring, hole and tail at the offset (6
  million calls);
- `hit`, which judges them against the item's own copper and the
  shapes earlier actions left (1.2 million calls, 27 million `_conflict`
  calls).

Candidates are many because give way runs for every spot that is legal
apart from its vias: about 25,000 resolutions on this board.

## Design

### 1. A via's move judged natively, whole

A new native call answers what the Python loop answers:

```
NativeObstacles.first_move(via, offsets, clearance, skip,
                           mine, first, pad, tail) -> offset index | None
```

- `via`: its ring and hole, at their current place.
- `offsets`: the clear offsets the cached search found, nearest first.
- `mine`: the candidate item's own copper and holes at the candidate,
  and the shapes earlier actions in this resolution left (`judge.extra`).
  These are the shapes the per-scan index does not hold.
- `first`: the copper the via first met. An offset where the moved ring
  still meets it is skipped, as `still` does now.
- `pad`: the via's own pad polygon, when the via lies inside its pad: the
  moved disc must stay inside it (`_disc_inside`).
- `tail`: the via's tail as a track (its far end, width and layer). At
  each offset the redrawn tail is judged against the board index, `mine`
  and the pool, as `_tail_shape` plus `hit` do now.

It returns the first offset that passes every test, in the same order the
Python loop takes them, so the same offset is chosen. Python keeps the
decision flow:
- share, then move, then shorten, then drop;
- the Action, its cost and its report;
- apply and undo.

The rules are the conflict rules the native judge already has.
`_disc_inside` and `still` are ports of their Python definitions, with the
same tolerances, and are tested for parity.

### 2. Share tails judged natively

A share's tail (from the via's far end to a target via) is judged the same
way: `NativeObstacles.tail_clear(tail, mine, clearance, skip)` replaces
`judge.hit` on the tail shape.

### 3. Fewer resolutions

A scored scan already skips a candidate that cannot beat the best spot at
the cheapest give-way cost. Two more cuts, each exact:
- **A via no cheaper way can free.** When a resolution is refused because
  a via meets the item and every way is refused, the refusal holds for
  every later candidate at which that via meets the same shapes of the
  item at the same relative offset. It is cached per scan and returned
  without judging again.
- **Nearest-first scans stop at the first spot that resolves**, as today.
  Candidates are ordered so the ones whose vias meet nothing come first.
  Already true; kept, and pinned by a test.

### Settings

None new. `place.via_clear_cache` bounds the refusal cache too; its
api.md row says so.

## Verification

- Parity:
  - for every via in the give-way tests, and a random sweep of
    candidates on the whole-board fixture, `first_move` returns the offset
    the Python loop returns: 1,000 cases with no mismatch;
  - `tail_clear` matches `hit` on share tails.
- Identical results on the whole-board fixture with a fixed hash seed,
  before and after: placements, steps, findings, check verdicts and
  give-way actions.
- The give-way tests, the native sweep and legal parity tests, and the
  digest parity tests pass unchanged.
- Timing on the whole-board fixture, unprofiled:
  - placement under 250 s, from 446 s;
  - give way under 30% of placement, from 85%.
- A Python fallback when the native module is missing, still exercised by
  the give-way tests with the native path switched off.
- The bench: "same 32" on every config.
