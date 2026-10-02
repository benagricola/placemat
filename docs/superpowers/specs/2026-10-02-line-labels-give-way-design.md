# A line of labels gives way

Follows `2026-10-01-labels-give-way-design.md` and
`2026-10-01-labels-yield-to-searches-design.md`, which made a label move for a
part placed after it and left a line of labels (a list, or `line=`) out.

## Problem

A searched cell placed after a line, a one-freedom slide having placed its
items first, put a pad under one text, and KiCad reported `silk_over_copper`
("Silkscreen clipped by solder mask"). The line neither gave way nor was
avoided.

The principle is the charter's: a user label is a mark, not a function of the
board; it gives way to parts, staying next to its item.

## Design

`_labels_give_way` works on a unit: a lone label, or every label of one
`board.label(...)` call that has a group. A unit is triggered when any of its
texts is in the way of the item (the existing `_label_in_the_way`, per text).
It then moves to the first candidate where every text passes the single-label
tests: on the board, not in the way of the item, not on another part, clear of
other labels and (physical envelope) of silk obstacles.

Candidates, nearest first:

1. the side it stands on, shifted along it by 0, then by `label.slide_step`
   either way, and to both ends of the allowed range;
2. the other sides of its items, nearest to where the line stands first,
   redrawn as declared (`_label_op` with the line's box) and shifted the same
   way.

A shift keeps every text overlapping its own item's extent along the side, so
a text never ends up beside its neighbour's item; spacing and order are those
of the declaration. Two texts that overlapped before the move are not held
apart. A lone label keeps its flush-to-flush slide.

With no candidate the line stays, one `label` finding names the first text in
the way and the item, and the item is placed as before.

A step's note reads "moved from north MID to south MID: C1 was there", or
"... to north MID, line shifted +0.50 mm: ...".

## Documents

`api.md` said the text's box is reserved so nothing placed later lands on it.
That holds for a firm item and a block's members; a searched item does not see
it, and the label moves. The docstring of `board.label` and the manual now say
so.

## Verification

`tests/test_label_line_gives_way.py`: a line meets a later searched part's pad
and moves as one (spacing, order, side), a line with no room is a finding and
the part places, a replayed run ends the same, pad labels with `line=` move as
one, and kicad-cli's DRC on the written shapes finds no `silk_over_copper`.
Full suite and the bench.
