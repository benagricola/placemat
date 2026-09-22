# Is this spot legal, and which spot is

Date: 2026-09-22
Status: design

The read surface answers what a part or a pad is. Nothing answers what is at a
point, or where a via may stand. `PLACEMAT_GAPS.md` records the cost twice: a
via placed on an eyeballed coordinate costs a full pass and a route to find out
it was wrong, and a review had to build a per-layer copper model in a scratch
pcbnew script to ask "is there metal here". The same hand-built search for the
nearest legal ground tap was run seven times in one round.

## What exists

- `Occupancy.copper_conflicts(shape)` judges a candidate copper shape against
  other nets' pads and planned copper at the board's own clearances. It is the
  primitive; it does not see copper already on a routed board, holes, the edge,
  or keepouts.
- `BoardGeometry.copper` reads every pad, track, via, graphic polygon and zone
  fill of a board, per layer, with its net.
- `NetClass` carries each class's track width, clearance, via diameter and
  drill. The board's hole-to-hole and hole clearance minimums are not read:
  `m_HoleToHoleMin` and `m_HoleClearance` (0.30 and 0.20 on the four-layer
  board measured) are.

## Obstacles for a via

A via joins every copper layer at one point, so a candidate position of net N,
diameter d and drill h is judged:

- **Hard, on every layer**: a pad, track, via or graphic polygon of another net
  closer than the clearance between N and that net; another hole closer than
  the hole-to-hole minimum; the board edge closer than the copper edge
  clearance; a rule area that forbids vias.
- **Soft**: a zone fill of another net. KiCad refills a zone and pulls it back
  round a new via, so a pour is not an obstacle; the answer says which pour on
  which layer would give way, because a via can split a plane.
- **Not an obstacle**: copper of net N, and a courtyard - DRC allows a via
  under a body.

**The tail.** A tap is only useful if it can be reached. A straight track from
the source pad's centre to the candidate, at N's class width on one layer (the
pad's own by default), is judged against the same hard obstacles on that
layer, skipping the source pad itself and every net-N item it touches.

## The search

`free_spot` walks candidates outward from the source pad: rings of `step`
radius increments, each ring's points at an angular spacing no wider than
`step`, in a fixed order (radius, then angle from east, anticlockwise). The
first candidate whose via and tail are both clear wins. Every rejected
candidate adds its reason to a tally, so the answer says why the nearer spots
failed - "edge x40, copper x212, hole x3" - the way `scan()` already does for
placements. No randomness; the same board gives the same spot.

## The command

```
placemat occupancy <board | script> --at X,Y [--json]
placemat occupancy <board | script> --box X0,Y0,X1,Y1 [--json]
placemat occupancy <board | script> --via-near PART.PAD [--net N] [--size D]
                   [--drill H] [--layer L] [--radius R] [--step S] [--json]
```

`--at` prints, per copper layer, the copper covering the point (kind, net,
owner) and the nearest copper of another net, then whether a via of the
point's own net - or the default class when nothing is there - could stand
there, with the reasons. `--box` prints, per layer, the copper inside by net and
kind. `--via-near` runs the search from a pad and prints the spot, its distance
from the pad, the tail's layer and length, the pours that would give way, and
the tally for everything nearer.

## In a script

```python
board.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u5"), "GND"), radius=2.0))
```

`FreeSpot` is a position resolved during copper planning, like every other
reference: after the part it names is placed, against the occupancy as it
stands - placed pads and copper planned so far - so a later via sees an
earlier one. A search that finds nothing is a finding carrying the tally, and
no via is drawn.

## What this does NOT do

**Net analysis** - length per layer, via counts, bottlenecks and the vias whose
removal disconnects a net - is a different question about the same data and is
not here.

**Fill a zone.** Pours are judged as KiCad would refill them, not refilled.
Whether a via splits a plane into islands is reported as the pours that would
give way, not computed.

**Route.** The tail is one straight segment; a tap that needs a dog-leg is a
tap the router or the script draws.

## Test plan

Pure, over synthetic geometry:

1. a via touching another net's track within clearance is blocked, naming it;
2. copper of the via's own net does not block;
3. another net's zone fill does not block and is reported as giving way;
4. a hole closer than hole-to-hole blocks;
5. the edge closer than the edge clearance blocks;
6. a rule area forbidding vias blocks, one forbidding tracks only does not;
7. a tail crossing another net's track on its layer blocks the candidate;
8. the search returns the nearest clear candidate and a tally of the rest;
9. the search is identical run twice;
10. nothing within the radius returns no spot and the full tally;
11. `--at` names the copper under a point per layer;
12. `--box` counts copper by net and kind per layer.

With KiCad:

13. vias read their drill, and the board's hole-to-hole and hole clearance
    minimums are read;
14. `--via-near` on a real routed board returns a spot that KiCad's DRC
    accepts when a via is added there.

In a script:

15. `FreeSpot` near a placed pad resolves to a clear position, and a second
    via near the same pad lands clear of the first;
16. a `FreeSpot` with nowhere to go is a finding with the tally and draws
    nothing.

## Documentation

- `api.md`: the command, and `FreeSpot` beside `board.via`.
- `SKILL.md`: before placing a via by coordinate, ask `placemat occupancy
  --via-near`, or write the via with `at=FreeSpot(...)`.
- `references/migration.md`, `## To 0.19`: the command and the reference are
  new; nothing to change.
