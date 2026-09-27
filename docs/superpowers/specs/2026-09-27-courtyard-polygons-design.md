# A courtyard that is not a rectangle

Date: 2026-09-27
Status: approved 2026-09-27
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-27 "a turned part judged
by its body's box against a round outline" and "placement behaviour met on
the ring test board (0.41)"

## The problem

placemat claims a part's courtyard as the box round the courtyard lines it
draws (`read.courtyard_box`), turned with the part. For a rectangular
courtyard that is what KiCad tests, less a stroke (placemat allows two
courtyards to overlap by their margins for that). For a courtyard that is
not a rectangle, the box claims area the part does not: a sector-shaped
winding, fixed at a disc's centre and turned to its bearing, collides with
its neighbour's box and crosses the round board's keep-in by its box's
corners, while KiCad's DRC, which tests the courtyard polygon, is clean. The
ring test board runs with `--keep-going` to get past its own windings.

## The change

1. **A part's courtyard polygon is read** from KiCad's own courtyard (the
   polygon its DRC tests: `FOOTPRINT.GetCourtyard(layer)` after
   `BuildCourtyardCaches`), in the part's frame, as `Footprint.courtyard`.
2. **A courtyard that is not a rectangle is claimed by its polygon**: the
   occupancy's courtyard shape is that polygon, turned with the part, in
   place of the box; the edge and keep-in checks take its points. A
   rectangular courtyard keeps its box and the margin rule, so no placement
   of a rectangular part changes.
3. "Not a rectangle": the polygon covers less than 98% of its own box (a
   setting, `place.courtyard_polygon_share`), so a courtyard drawn as a
   rectangle with a chamfer or a rounding stays a box.
4. **The native scan** takes the same shapes (a courtyard is already a
   polygon there); the courtyard-to-courtyard rule for a polygon courtyard
   has no margin allowance (KiCad's own polygon has none to allow for).
5. **The rank and the pocket** keep measuring by the box (they order and
   seed; they do not decide legality).

## Verification

- Pure tests: two sector-shaped parts turned about one centre, 30 degrees
  apart, whose boxes overlap and polygons do not: legal; the same at 5
  degrees, polygons overlapping: refused. A sector's box corner past a round
  board's keep-in with its polygon inside: legal.
- A rectangular part's placements are unchanged: bench, as a placement
  change (expected same 32 on all three configurations: no bench module has a
  non-rectangular courtyard, to be checked and reported).
- KiCad test: a footprint with a polygon courtyard read back as the polygon.

## Not in scope

- Rectangular courtyards claimed by KiCad's polygon rather than the box and
  margin (the same result for a rectangle).
- A body or silk envelope that is not a rectangle (the physical envelope
  already uses the drawn polygons).
