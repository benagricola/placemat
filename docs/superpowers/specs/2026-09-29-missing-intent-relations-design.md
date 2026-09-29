# The intent relations layout scripts are missing

Date: 2026-09-29
Status: draft
Replaces: 2026-09-29-pad-references-design.md (withdrawn: it made coordinate
arithmetic official instead of naming the relations)
Source: docs/audits/2026-09-29-intent-vocabulary.md (section 3) and
docs/audits/2026-09-29-layout-scripts.md (sections 3-4). The scripts audit
counts the sites in one board's scripts that hand-compute each relation
today.

## The problem

Placemat's intent vocabulary covers items against the board (edges, rows,
rings, pockets, keep-ins) and against one part's pins (blocks, `Near`,
`Pin`). Dense module layouts also relate parts to other parts, and route
and pour copper by pads. With no words for those relations, scripts compute
positions with `X`/`Y` offsets and helper libraries, and each later edit
copies the pattern.

The relations below name what the scripts compute. Placemat owns every gap,
clearance and alignment:
- sides are `Edge`;
- no argument is a coordinate;
- a spacing is the envelope's own unless a named rule asks for more.

## The relations

Each entry gives its form and how many sites need it today.

1. **A part beside another part** (129 sites).
   - Form: `at=Beside(item, Edge.EAST, align=None, gap=None)`.
   - The part stands on the item's east side, its drawn envelope at the gap
     the envelope rules keep between two parts (silk clearance, component
     spacing), or `gap=`.
   - `align=`:
     - a pad of the item (`PadRef`): the part's pad on the same net lines
       up with it;
     - `(own_pad, their_pad)`: when the nets differ;
     - an `Along`: START, MID or END of the item's side;
     - default MID.
   - The item may be a part, a cell or a keepout.
   - It waits for the item to be placed.
2. **A pour over a set of pads** (99).
   - `board.pour_pads(net, [PadRef...])`: one pour over the named same-net
     pads' copper. Another net's pad inside it is refused, naming the pad.
   - `board.finger(..., width=PadRef(...))`: a neck as wide as that pad
     across the run.
3. **A row or stack off a part** (51).
   - `board.row(items, Edge.SOUTH, of=Part("u1"), align=Along.START)`: the
     row runs along the part's south side, each item at the envelope gap.
     This uses the row machinery that today takes a board edge.
   - A fit frame accepts it.
4. **A track through the gap between pads, or held off pads** (40-70).
   - Two waypoint forms:
     - `Between(PadRef(a), PadRef(b))`: the centreline of the gap, with room
       for the track and its clearances checked;
     - `Past([pads], Edge.EAST)`: the track keeps the clearance off the
       pads' east side.
   - The track planner takes the 45s round them, as it does today.
5. **The end of a leg that takes the 45** (20).
   - `board.track(..., bend=Bend.START | Bend.END | Bend.BOTH)` per leg.
   - The planner's own choice stays the default.
6. **Vias in a row along a pad's axis, or stitching a region** (27).
   - `board.vias(net, along=PadRef(...), count=N)`: vias along the pad's
     escape axis at the via-to-via rule.
   - `board.stitch(net, region, pitch=None)`: stitching over a cell, a pour
     or a keepout, at the rule pitch.
7. **A cell placed by a member** (10). `Pin` takes a cell's member pad, so a
   cell lands with that pad on the reference.
8. **A keepout shaped by an item** (18). `board.keepout(Part("ant"),
   name, margin=...)`: the region is the item's drawn envelope grown by the
   margin, and it moves and turns with the item. A shape from an item
   replaces a hand-built polygon.
9. **Against a keepout's edge** (6). `Beside(keepout, Edge.SOUTH)`, as
   item 1: a keepout takes the same side handle a cutout already has.
10. **A fit frame in one axis** (11). `board.size(fit=Axis.X)`: the frame
    fits its content across x, and y stays as declared.

## Order

1, 2, 3 and 4 first: they cover about 350 of the sites. Then 7 and 9,
which are small and share code with 1. Then 5, 6, 8 and 10.

## Verification

Each relation gets pure tests on synthetic fixtures that assert the placed
geometry: envelope gaps measured with `drawn_envelope`, pad alignment, and
the lane's clearance. A migration check rewrites two real module
fragments' coordinate placements with the new forms, and the placed boards
must match within 0.01 mm. Bench for each placement change.

## Not in scope

- Coordinate arithmetic on references. The withdrawn spec proposed it;
  intent forms replace it.
- Rewriting the boards' scripts. The board sessions do that once each
  relation is released; the skill's intent-first guidance tells them how.
