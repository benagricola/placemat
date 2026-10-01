# Labels give way

## Problem

A `board.label()` is worked out the moment its item is placed, and the text's
box is reserved on its face (and its silk added as an obstacle). A part that
is placed firmly afterwards, beside the labelled item, can land within the
silk clearance of that text. The run then stops with a finding such as
"other (fixed): other's U2 silk is 0.17 mm from label conn.j1 USB-C silk
(needs 0.20)". The label sat flush with its member's end and its knockout
frame stood slightly past it; `Beside` measures its standoff from the item's
parts only.

The first fix considered was to count labels in `Beside`'s reach, so the
placed item stands off the label. The user decided against it. Source: a
session in another project on 2026-10-01, about a connector's user label:

> the solution there is is not anything to do with the light sensor. It's to
> move the silk screen for the USB-C port because that is that's a user
> label, right? So that's the first thing that should be moved. It's not
> something that defines the functioning of the of the device. Therefore,
> it's okay to move it as long as it's still clear that it's referring to
> the USB port that it's near.

A part never moves for a user label. The label gives way.

## Design

When a firm placement (FIXED or EDGE, including a rider) would come within
silk clearance of a label declared on another item, or sit on its reserved
box, the label is re-settled before the placement is judged:

1. Slide along its declared side. Positions run from the side's start-flush to
   its end-flush position (the label's box within the item's extent on that
   side; a label wider than the side slides between its two flush positions),
   nearest the declared position first, every `label.slide_step` mm and both
   flush ends.
2. Then the item's other sides, nearest to the declared spot first, each slid
   the same way from the label's declared `align` on it.
3. A candidate must keep its own `gap` off the item (unchanged), clear the
   parts placed (their shapes under a physical envelope, their reach under
   the others), the other labels, and the part now being placed.
4. If no candidate is clear the label stays, a `label` finding names it and
   what blocks it, and the collision is reported as it was.

A moved label's step note says so: "moved from north END to north, 0.1 mm
toward the start: <what> was there". Its reservation and silk obstacle move
with it.

Searched items keep treating a label as an obstacle (they avoid it, so no
label need move). Grouped labels (a list, or `line=`) keep their line and do
not give way. A block's firm members are not swept.

Labels are re-settled in two places: before a firm placement is judged (so no
collision is recorded) and after each commit (so a replayed run, which does
not judge, ends with the same labels). The second is a no-op when the first
did its work.

Labels are Python only (the reservation and the silk obstacle are Python
state; the native obstacle index is rebuilt by `add_copper`/`remove_copper`),
so there is no native change.

## Verification

- The reported case: a cell whose envelope is taller than a labelled member,
  another cell placed `Beside` it; the other cell lands where `Beside` puts it
  without the label, and the label slides to a clear spot on its side.
- A label with no room on its side moves to another side.
- A label with no room anywhere stays and gives a finding naming it.
- A label on the far side, and a label on the other face, change nothing.
- The existing collision test (a firm part on a reserved label) now moves the
  label.
- Full suite, and `fixtures/bench.py --jobs 4` for placement drift.
