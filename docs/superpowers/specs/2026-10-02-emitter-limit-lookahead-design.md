# A look-ahead for Pm.Emits / Pm.Limit pairs

Date: 2026-10-02
Status: design, built in the same change
Source: a board's session, 0.77.0 (a source placed before its limit partner
left the partner no legal spot)

## Problem

A pair (`Pm.Emits` on a source, `Pm.Limit` on a sensitive part of the same
kind) is judged by whichever of the two is placed second: a hard disc round
the first (the limit distance, from `value(r) = v_ref * (r_ref / r) **
falloff`) that the second may not enter, and a price inside it. Nothing
looks at what the first leaves the second.

On a small round board the source's best spot by its own score is often the
middle of the region it is held in. A partner 25 mm from the source then has
no spot inside the seal ring, and ends unplaced ("in push from M1 magnetic
(limit 0.5 at 25.1 mm)"). The same pair fits when an unrelated cell moves the
source's global-solve hint, because the hint decides which legal spot the
source is nearest to: success depends on where an unrelated hint lands.
Lowering the source's priority placed the partner but let larger cells take
the source's small region; `--explore` varied spots of the source without
knowing which ones leave room; `Priority` has three tiers and both parts need
the top one.

The order the pair is searched in is the problem, and it is the same the
other way round (a sensitive part placed first, held near the middle,
leaves its source none).

## Options

1. **Solve repulsion.** The global solve treats a pair as a repulsion so the
   two hints come out at least the limit distance apart. The solve's springs
   are quadratic and attract; a repulsion needs a second pass or a different
   solver. A hint is only where a scan starts and, on a wide search, the
   tie-break among spots of equal cost; it neither knows the board's shape,
   the keep-outs and regions the partner is bound by, nor what is placed by
   then, and the solve is off by default. Moving hints moves placements on
   every board with pairs and does not remove the failure, only makes it
   rarer.
2. **A look-ahead in the search.** When a part with a still-unplaced partner
   is searched, refuse the candidates that leave the partner no legal spot at
   the limit distance. It does not depend on hints, uses the legality the
   partner's own search would use (board, keep-outs, regions, faces, turns,
   what is placed), and works in both orders.
3. **Explore varies the order inside a tier.** Order is the cause, but the
   variants are drawn at random among spots near the best and cost a run
   each; a board would have to be explored to place a pair that fits.

## Design

Option 2. Option 1 is not built: it is a quadratic-solver change for a
failure the look-ahead removes without it, and it would move placements on
boards that do not have the failure. Option 3 is unchanged (an explore
variant's draws pass through the look-ahead like any search's).

For a searched part or cell `i` (not a block), each pair of one of its
members with a part that is annotated, not yet placed, and searched
generically gives a requirement on every candidate of `i`. The partner `j`'s
legal spots are found once per settle of `i`, by `i`'s partner's own search
as it would run now: its faces, its turns, a radial band or `Near`, the
whole board otherwise; each spot the partner's legality accepts is recorded
(`scan` with an `accept` that records and refuses). The grid is
`place.lookahead_step` (1.0 mm), or the partner's own `step=` if coarser. A
candidate of `i` is then asked, per pair:

- `i` is the source, the partner sensitive (placed second, so a hard disc
  round the source holds the partner's whole body): some spot of the partner
  must have its body outside the disc of each emission and its sense point at
  least `exposure.reach` from the candidate's emission point, where the reach
  is for the part of the limit the sources placed already leave there.
- `i` is the sensitive part, the partner the source (placed second): some
  spot of the partner must have its emission point at least the reach from
  the candidate's sense point, for what the sources placed already leave of
  `i`'s limit there. The test is against the convex hull of the partner's
  emission points, the farthest point of a set being a vertex of it.

A grid step is added to each reach, so a spot found on this grid stands for
the one the partner's own, differently aligned, grid meets.

The refusal is `accept`, composed with the item's other `accept` (riders,
sums of sources). A scored scan asks it of the best candidates first, so the
check runs on a few candidates. If no candidate passes, the part is settled
again without it (the partner then ends unplaced as today) and the step says
so; the look-ahead never costs a placement.

Not looked ahead for: a partner decided, on an edge, run, ring, spoke or
line, in a block, or placed with another item (it is not searched in the
open); a part itself placed by one of those forms or on a point with turns
searched; a source whose sensitive partner is already placed (the existing
disc applies). Those are as before.

Settings (`place` section): `lookahead` (true), `lookahead_step` (1.0 mm,
above zero). `lookahead = false` is exactly the old behaviour.

Cost: one scan of the partner's legal spots per settle of a part with an
unplaced partner, the same walk as the partner's own unscored search; nothing
on a board without annotated pairs.

## Verification

- A source held within a band of a small disc's centre, partner searched on
  either face: with `lookahead` false the source takes the middle and the
  partner is unplaced; true, both place at the limit distance, the source off
  the middle (`tests/test_emitter_lookahead.py`).
- The same pair with room: placements identical with and without.
- A sensitive part pulled to the middle by a link and placed first: its
  source is placed with the look-ahead, unplaced without.
- A pair that cannot fit whatever the source does: the source is still
  placed, the partner unplaced.
- An explore variant's focused source: both placed at the limit distance.
- The native and the Python sweep choose the same spots.
- The whole-board fixture with the two annotations added to a cell's member
  and a cell's member, `[solve] enabled`: reported in the commit.
- `fixtures/bench.py`: no placement moves (no pairs in the fixtures).
