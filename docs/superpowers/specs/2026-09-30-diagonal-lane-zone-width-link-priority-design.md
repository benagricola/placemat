# A 45 off a pad's corner, a zone fill's width, and a link wait under priority

Status: approved (2026-09-30).

Three open items, each small enough to specify together:
- the owner's choice of a diagonal lane (2026-09-30);
- "spec it" for a zone fill's width (2026-09-30);
- a whole test board's observation of a linked chain waiting past its
  priority (2026-09-30).

## 1. A 45 held off a pad's corner

**Problem.** A comb of parallel 45-degree tracks, where each 45 stands a
clearance off the next pad's corner, is worked out by hand, because a point
on a 45 is fixed by x + y (PLACEMAT_GAPS 2026-09-29, "a position that is a
sum of an x and a y"). The owner chose a lane form over arithmetic on
`X`/`Y`.

**Design.** `Past` takes a corner as well as a side:
`Past(items, Corner.NE)`, with a new `Corner` enum (`NE`, `NW`, `SE`,
`SW`).
- The point is on the outward diagonal from that corner of the items'
  combined copper box.
- It stands the clearance plus half the track's width from the corner.
- A 45 leg through it, running across that diagonal (NW to SE for an NE
  corner), passes the corner at exactly the clearance.
- As a track waypoint it is that point. The track's octilinear routing
  takes the 45 through it when the points either side allow one. A route
  that cannot is a finding naming the corner.
- In `Beside`'s align pair, `(own_pad, Past(pads, Corner.NE))` stands the
  part's pad off that 45: its own corner facing the lane at the clearance.
  This is the ILIM pad a clearance off the 45 beside it.

The owner's name for the form was `Diagonal(pad, clearance)`. The design
uses `Past` with a corner instead, since it already carries items, the
clearance by net pair, `across=` and `lane=`. A separate `Diagonal` would
repeat all of that.

## 2. A zone fill's width along a load's route

**Problem.** `check current-path` joins carriers through a zone fill but
does not measure the fill's width. KiCad slits each hole in a fill to its
outline, so the fill polygon's narrowest neck reads about zero. A load
running in a zone lane is reported "not judged".

**Design.** Where the widest route between two carriers passes through a
fill, the width it has inside the fill is measured:
- The fill's polygons on that layer, with their holes, are rasterised at
  `check.zone_step` (default 0.05 mm).
- Each cell's distance to the fill's edge is its distance transform. The
  slits KiCad draws are zero-width, so they are no edge.
- Between the pads (or the tracks) where the route enters and leaves the
  fill, the widest path is found. That path maximises its narrowest
  cell's distance, the same search `current_paths` already runs on its own
  graph. Its width is twice that distance.
- The fill's width counts as the route's width at the fill, with its neck
  point.
- Carriers only a fill joins are now judged, not reported "not judged".
- A fill thinner than one cell reads as that cell's width, and says so.

## 3. A link wait under priority

**Problem.** Of two linked items not yet placed, the one with less pull
waits for the other, whatever their priorities. On a whole test board a chain
of linked cells waited link by link. Each was searched after smaller cells
had taken the room, and one cell's `priority=HIGH` was set aside for a link
to a `DEFAULT` cell.

**Design.** An item never waits for a linked partner of a lower priority
tier. The link wait orders items only within one tier. A `HIGH` item goes
down with the `HIGH` tier even when it is linked to a `DEFAULT` one, which
then places toward it as usual. The step note no longer says "priority set
aside for the link" in that case. The wait is unchanged between items of
the same tier.

## Verification

- Corner:
  - `Past([pad], Corner.NE)` as a waypoint, with a 45 through it at exactly
    the clearance from the corner;
  - each corner;
  - `across=` with a corner is refused;
  - a `Beside` pad off a 45;
  - a migration test for the comb, hand-computed against the intent form,
    agreeing within 0.01 mm.
- Zone width:
  - a fill lane 1.2 mm wide between two carriers is judged at 1.2 (within
    one step);
  - a slit fill is not read as zero;
  - a fill neck narrower than the need fails naming its point.
- Link priority:
  - a `HIGH` item linked to a `DEFAULT` one places in the `HIGH` tier;
  - two `DEFAULT` items still wait by pull.
- The full suite, a release, then the bench (item 3 is a placement
  change).
