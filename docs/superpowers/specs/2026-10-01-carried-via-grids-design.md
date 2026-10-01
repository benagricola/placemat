# A part's via grid carried with it

Status: built (2026-10-01).

Addendum to 2026-10-01-via-field-relay-design.md, which left "a part's
`board.vias()` grid" out (its section 8). Builds on 2026-09-27-pad-vias-design.md
and 2026-09-30-plane-drops-and-the-far-face-design.md.

## Problem

`board.vias(net, pad)` fills a pad with a square grid. It is planned after its
part has landed, against the board as it stands, and a site that is not clear
is skipped. Another item placed later is judged against the drawn vias as
copper. So the grid never gives way: a far-face pad over one row of it either
refuses the spot (the item is searched) or leaves the row out (the grid is
planned second), and neither the per-via steps (share, move, leave, shorten,
drop) nor the field re-lay can reach it.

## Design

### 1. The grid is carried

When the board is resolved, each `board.vias(net, pad)` on a part becomes
carried vias of that part, as `board.via(net, PadRef)` on a searched part
already is (occupancy.py `carry`): a ring and a hole each, moved and turned
with the part. This is for every part with a grid, searched or placed firmly:
a firmly placed part's grid is what a later item gives way for.

- **Sites.** The sites are what the grid form has always drawn: the pad's
  land filled at `pitch` (by default the closest the hole-to-hole rule allows),
  in the part's own frame, keeping each site whose via, grown by `inset`,
  lies wholly in the land. A site is also kept only if it clears the part's
  own copper and holes (its other pads, its through pads' holes) and the
  vias carried before it. Nothing else is judged at that point: the board is
  not laid out yet, and what the other items do is what give-way is for.
- **Ids.** A via is "pad field K via J" (K the grid's declaration, J its site);
  the vias a relay adds to it are "pad field K relay M". Its owner is "via at
  REF.N", the same as a single via declared at that pad, and its home is the
  part. The inset the grid was declared with is kept on the occupancy under K.
- **The part's own judging.** Where a part lands, its own carried vias are
  not judged against its own pads: the sites were kept clear of them when
  they were carried. A site a relay chooses is judged against them, as it is
  against everything else.
- **The row form.** `board.vias(net, along=, count=)` is not carried. Its vias
  stand outside the pad, in a line, joined to the pad by one tail to the
  farthest; a row that gives way would need its tail re-drawn and its
  `count` held, which has no step. It is planned after its part as before.

### 2. When the grid is drawn

A grid of a part is drawn by the plan, as a via declared at a pad is: after
every item has been placed (a late intent). A grid on a firmly placed part
was planned before the search; it is now planned after it, so the items
searched after the part can give way to it. Copper that names a grid (a
fitted pour's member, a track's end, a `Past` item) is planned after it too.

The plan draws what the part carries when it is planned: each carried via of
the grid as it stands after give-way (moved, added by a relay, shortened), a
tail for each via that left its pad or was shared, and no via that was
dropped or shared. A via is then judged once more against the copper
planned before the grid, as it always was (`_via_site_why`: the board's edge,
other nets' copper and holes, keep-outs that forbid vias); one that fails is
not drawn, as before. A grid none of whose sites fit says "no via fits", as
before; one whose vias all gave way says nothing of its own, and its item
reports what gave way.

### 3. Giving way

A grid's vias give way as a stamped cell's do, in the same order and at the
same cost: share, move, relay, leave, shorten, drop, with the same settings.
The field re-lay is for the vias of one grid in one land of one pad: a via
of the pad that is not the grid's (a single via declared at the pad) holds
its site, counts toward the field's count and is not moved by a relay. The
target count is the count the grid was carried with; a plane net's floor and
the drop step's keep arithmetic are the existing ones, and a net that is no
plane is never dropped, so a grid of one with no room refuses the spot (a
firmly placed item that finds none is a collision, as a stamped cell's field
under it is).

Where the grid was declared with `inset=`, every site a relay chooses keeps
it: the via's copper, grown by the inset, lies wholly in the land, which is
how the grid was drawn. The closest two vias of the field may stand after a
relay is the floor `pitch=` is refused under, `max(size, drill + hole-to-hole)`,
whatever pitch the grid was declared at: a grid declared at a wider pitch may
be closed down to it (a grid declared at the closest cannot be closed at all,
and a relay only moves, adds or removes vias on its lattice).

A part put by a pin on its host's pad (a rider, settled with its host) is not
refused by the host's carried vias: the group the rider is judged against
leaves them out, and they give way to it when it is committed, as to any item
placed after them.

The report, the cost, `undo` and the commit's put-back are the field relay's.
The write is the plan's: a part's vias are drawn by its grid's plan, so
nothing is changed on a written board.

### 4. Not covered

- The row form (section 1).
- Several grids in one land: the relay treats them as one field.
- A single via declared at a pad is carried on a searched part only, as before.

## Verification

Unit tests (tests/test_carried_via_grids.py, tests/test_carried_via_grids_kicad.py):

1. A 3 x 3 grid in an exposed pad of a firmly placed part, another item's pad
   on the far face along one row: the row is re-laid, 9 vias, a "re-laid by"
   finding with 9 before and 9 after; the item is searched, and firm.
2. No room: drops to the floor with the count reported (a plane net); a net
   that is no plane refuses the spot.
3. A searched part's grid travels with it: it lands where the part lands, and
   gives way to what is already there.
4. `inset=` is kept by a relay, and the pitch is not closed below the floor
   `pitch=` is refused under.
5. Undo puts the grid back as drawn. A rider on the host's pad is placed, and
   the host's vias give way to it.
6. A grid planned late: a fitted pour that names it is planned after it.
7. The same result with the native calls switched off.
8. Written board: kicad-cli's DRC is clean.

Real board: the keep-out module fixtures (`fixtures/fairing/keep_out`) draw
grids on firmly placed parts. A far-face part is placed over a row of one,
and the grid's count before and after and the DRC of the written board are
read.
