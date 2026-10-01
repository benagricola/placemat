# A fitted pour that reaches into the room round it, and over pads nearer than the clearance

Status: approved (2026-10-01).

Source: a board's session (2026-10-01), moving pours that 0.70.0 made fitted
and finding two things the grown zone did that a fitted pour cannot.

## Problem

1. **No reach.** A switch node joins a 1.0 x 2.5 mm pad and a 1.9 x 2.5 mm pad
   offset diagonally. The fitted outline is the hull of the two, and the room
   beside the hull is free. The net's `current-path` need (3.6 A at a 10 C
   rise, 1.758 mm) fails at 1.22 mm; the zone `grow=` drew passed. A `width=`
   neck drawn as declared would stand on another net's pad. A fitted pour is
   the shortest outline that holds its pads, so nothing asks it to take the
   room beside it.
2. **Pads nearer than the clearance.** A pour over two pins of a fine-pitch
   part, plus vias, is refused: "pour NET_A: U1 pad 25 (NET_B) is within its
   clearance of pad U1.26, so no pour can hold the pad clear; the pour is not
   drawn". The footprint sets the 0.15 mm between pads 25 and 26, under the
   0.2 mm clearance. The fit holds a pad whole, or inset or shrunk to its
   centre, and a pad whose centre is inside the neighbour's clearance outline
   has no such hold.

## Design

### reach=

```python
board.pour(Net("SW"), [PadRef(Part("q1"), 1), PadRef(Part("l1"), 1)], layer=CopperLayer.F,
           swallow_pads=True, reach=0.4)
```

`reach=mm`, greater than 0, on a fitted pour (`swallow_pads=True` over pads and
vias, without `width=`). Anything else is refused at the declaration.

The copper is:

1. the fitted outline (`pourfit.fit`, unchanged), grown by `reach` with round
   corners, each arc no more than `[geometry] arc_sag` off;
2. less the clearance outline of every other net's copper planned before the
   pour: the same pieces the fit keeps out of (pads, tracks, vias, pours, plated
   holes, the board edge and cutouts), each grown by its pair's clearance plus
   half the pour's stroke, so the outline keeps the clearance as a fitted
   pour's does;
3. keeping only the parts that touch the fitted outline. Copper cut off from the
   members by copper standing across the reach is dropped.

Each kept part is a graphic polygon of the net (`Pour`, `fitted=True`), never a
zone. Copper planned after it keeps clear as for any fitted pour: the
occupancy holds each polygon at its outline plus half the stroke.

The booleans are pcbnew's `SHAPE_POLY_SET` (`Inflate`, `BooleanSubtract`,
`Fracture`), KiCad's own geometry, called from `placemat/kicad/polyops.py`,
the one place the plan reaches pcbnew, and only for a pour with `reach=`.
Without pcbnew a pour with `reach=` is a finding and is not drawn. A pure
Python boolean over tangent, nearly coincident edges was not worth the risk of
a sliver the clearance check would then find.

Holes: copper standing inside the grown ring, touching neither the fitted
outline nor the ring's edge, leaves a hole. A graphic polygon has one outline,
so `Fracture` joins the hole to the outside by a bridge of no width, as KiCad
does for a zone fill. The occupancy's stroke offset, the native conflict code
and the current-path raster all take a polygon with doubled edges; the reader
(`read.py`, a poly's outline and its stroke merged) fractures its merge so the
hole survives the read. Non-convex polygons are accepted by the conflict
code as they are (it walks edges and tests containment), so nothing is split
for convexity.

The "narrows to" finding is not made for a pour with `reach=`: the grown copper
contains the fitted outline, so the neck it would name is not the copper's.

No new setting: the arc error is `[geometry] arc_sag`. `reach=` joins the
declaration's digest when set (`CopperIntent.reach`, `omit_default`), so a
pour without it digests as before.

Follow-up, not built: reaching only as far as the net's current-path width
needs (`reach=` as the width, or `reach="current"`). It needs the net's
carriers and the check's disc width inside the plan, which the plan does not
hold; the check reads a written board. Until then `reach=` is a distance, and
the migration step says to add the old `grow=`.

### Pads nearer than the clearance

KiCad judges a board graphic against a pad like any copper:
`DRC_TEST_PROVIDER_COPPER_CLEARANCE::testGraphicClearances` queues each
copper graphic, and `testSingleLayerItemAgainstItem` waives only the same net
and a net-tie exclusion; the same-footprint exemptions in `testPadAgainstItem`
are for the pad's own footprint's net-tie pads and graphics, not a board
polygon. A polygon whose copper edge is pad 26's edge is therefore at the
footprint's gap from pad 25 and is a second clearance violation, beside the
pad pair's own (confirmed with `kicad-cli`: pad 25 against pad 26 at 0.10 mm
reports once, a polygon over pad 26 with its edge on the pad's reports twice).

So the pour does not stand on the pad's edge on that side. `pourfit.fit` holds
a pad that no inset or shrinking clears as the part of it that lies outside the
neighbour's clearance outline (`pourfit.clipped`): for each piece reaching
into the pad, the side of one of the piece's edges that keeps the most area.
The pour's added copper then keeps the full clearance from pad 25, the pad's
own copper is the footprint's, and the pour still overlaps pad 26, so it joins
it. A pad wholly inside the clearance outline stays a finding ("is within its
clearance of ..."). The existing holds are tried first, so a pour that fitted
before is unchanged.

## Verification

Synthetic boards, as `tests/test_pour_fitted.py`'s.

- `tests/test_pour_reach.py`, plan: the reach outline is the fitted outline
  grown by `reach` (box, and no vertex further than `reach` from it); a foreign
  pad cuts it back to the clearance and a `board.rule` clearance is the
  rule's; the board edge's clearance bounds it; a pocket of foreign copper
  leaves one polygon with a bridge; copper planned after keeps clear; refused
  for `width=`, no `swallow_pads`, and a distance that is 0, negative, a bool
  or not a number; the declaration digests as before without `reach=`.
- Written board (pcbnew, `kicad-cli`): two parts carrying 3.6 A with offset pads
  fail `check current-path` as a bare fitted pour and pass with `reach=`, with
  no clearance or shorting violation in KiCad's DRC and no zone on the board;
  with foreign pads in the room the written pour is a clearance from them, DRC
  clean; with a pocket of foreign copper the pour is DRC clean and
  `current-path` passes.
- Tight pins: a fine-pitch row with pad 25 on another net 0.15 mm from pad 26,
  clearance 0.2 mm: the pour over pads 26 to 28 is drawn with no finding, holds
  pad 26 (overlaps it), and is a clearance from pad 25 in the plan; written,
  DRC reports the one pad-to-pad clearance violation and none involving the
  polygon. A polygon with its edge on pad 26's edge, written the same way,
  reports two. A pad wholly inside the clearance outline is still refused.
- `pourfit`: a pad whose centre is inside a piece is held clear by `clipped`;
  the randomised fit test accepts a hold whose centre is in a piece.
- The bench's tally is in the commit message.
