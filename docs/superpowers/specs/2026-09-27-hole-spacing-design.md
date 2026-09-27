# Hole spacing when placing

Date: 2026-09-27
Status: approved 2026-09-27
Source: a board's layout work, 2026-09-27 (core, run core-study-3): "two
stamped cells' vias can land closer than the hole-to-hole rule"

## The problem

A searched back-face cell put its GND via with its centre 0.29 mm from a
fixed front cell's GND via, holes under 0.30 mm apart. KiCad reports `hole_to_hole` (minimum 0.30 mm).
The placer judges a candidate's vias and plated pads as copper only: two
copper shapes of one net never conflict, and holes are not compared at all.
Hole spacing is net-blind, so same-net vias from two cells, or a via and a
through pad of the same net, can land too close.

Unplated holes have the same gap: the occupancy refuses copper that overlaps
an unplated hole, but not copper inside the board's hole clearance of it.

The via planner already applies both rules to the vias it places
(`layout._via_site_why`, `queries.via_verdict`). The occupancy, which judges
where parts and cells go, applies neither.

## The change

1. **A drilled hole is an obstacle of its own.** Each plated through pad
   with a drill, and each via on the board (a stamped cell's among them),
   adds a `hole` shape to the occupancy: a circle of the drill at its centre,
   on both faces, owned as its pad or via is. Unplated holes are already
   `npth` shapes.
2. **Two holes of different owners keep the board's hole-to-hole rule**
   (`hole_to_hole`, read from the board's design settings), whatever their
   nets: `hole` or `npth` against `hole` or `npth`. The refusal says "hole
   0.12 mm from <who>'s hole (needs 0.30)".
3. **Copper keeps the hole clearance from an unplated hole**
   (`hole_clearance`), in place of refusing only an overlap. A plated hole
   is inside its own pad's copper, so the copper clearance already covers it.
4. **The native scan applies the same rules** (`native/src/shapes.rs`
   `conflict`, a `Hole` kind, the two distances in its config), so both paths
   agree; the parity tests cover the new pairs.
5. **The via planner reads holes from the occupancy**, so a via is judged
   against a stamped cell's own vias too (today's `_via_obstacles` lists
   footprint holes only; this was a deferred minor from 0.41).

## Verification

- Pure tests: two cells, each with a via of the same net, placed so the holes
  are 0.25 mm apart: the searched one is refused and lands elsewhere; a
  through pad against a via of its own net, likewise; copper 0.1 mm from an
  unplated hole with `hole_clearance` 0.25 is refused; the native and Python
  paths agree on each.
- The via planner refusing a site 0.2 mm from a stamped cell's via hole.
- Bench (a placement change).

## Not in scope

- Hole-to-hole within one part or one cell: those move together and are the
  footprint's or module's own.
- Drill-to-edge (board edge clearance for holes): the edge rule already
  covers the copper around a hole.
