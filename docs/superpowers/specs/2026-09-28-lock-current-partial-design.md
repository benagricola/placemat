# Locking what stands, when some of it does not

Date: 2026-09-28
Status: approved 2026-09-28
Source: the fairing board's session, 2026-09-28: "`lock --current` refuses
to write anything if any one item wouldn't stand, which made the 0.49 to
0.50 migration all-or-nothing (29 of 75 refused)"

## The problem

`placemat lock <script> --current` locks every searched item where the
board has it, resolves once more with those locks, and writes nothing
unless every item comes back where it was (`cli._lock_where_it_stands`,
`_lock_current`). One item that would not stand holds back all the others.

## The change

1. **`--current --partial`**: lock the items that stand and list the rest.
   The items that would not stand are dropped and the rest are checked again
   (a smaller lock can move what is searched after it), until every item
   left comes back where the board has it, or none is left. The lock is
   written with those.
2. **Output**: "locked N of M where the board stands (run R); K would not
   stand there", then each refused item with its reason (as now), and a
   non-zero exit when any was refused, so a loop still notices.
3. Without `--partial`, unchanged.

## Verification

- A board where one item's recorded spot is taken (it would not stand) and
  two others stand: `--partial` writes the two, lists the one, exits 1;
  without it nothing is written (as now).
- An item that stands only while a refused one is locked is dropped in the
  second check and listed with its reason.

## Not in scope

- Changing why an item would not stand; the reasons are listed as now.
