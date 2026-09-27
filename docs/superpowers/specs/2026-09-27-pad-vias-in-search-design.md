# A via declared at a pad goes with its part during the search

Date: 2026-09-27
Status: draft
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-27 "a plane drop through
the board lands on the other face's pads"

## The problem

A board closed its plane nets in the script: a via at the centre of every
GND and 3V3 pad of the parts it places itself (`board.via(Net(net),
PadRef(part, pad))`). Copper that depends on a searched part is planned
after the search, so the part's search never knew its pad would carry a
through via: a front part landed with its pad over a back-face part's pads,
and the via drawn there afterwards shorted them (14 shorting_items, 11
clearance on the board). placemat did say so - 40 copper findings - but
each read "pad GND is 0.00 mm from ... copper": a planned via is named as a
pad, so nothing said it was the drop.

## The change

1. **During its search, a part claims the vias declared at its pads.** For
   each `board.via(net, PadRef(part, pad))` (a via at a pad, not a
   `FreeSpot`), the part's candidate shapes gain the via's copper ring on
   every copper layer and its hole, where the pad would put it; a spot where
   that via would meet another net's copper on either face, or another
   owner's hole, is refused as the part's own pad would be. A cell or block
   member's pad counts for the cell or block.
2. **A planned via is named as a via** in a copper finding: "via GND at
   (x, y) is 0.00 mm from ... copper on B.Cu".
3. `FreeSpot` is unchanged: it already judges its site on every layer
   against what is placed, and a part placed after it sees the via.

## Verification

- Pure tests: a front part searched near a back part, a GND via declared at
  its GND pad: with the via, it lands where the via clears the back part's
  pads; the same search without the via may land over them (the test shows
  the difference). A via at a fixed part's pad is unchanged (it is planned
  before the search).
- A copper finding for a planned via says "via".
- Bench, as a placement change (no bench board declares vias at pads:
  expected same 32).

## Not in scope

- Moving a via declared at a pad off the pad: `FreeSpot` does that.
