# A keepout by part height

Date: 2026-09-27
Status: approved 2026-09-27 (heights from the Pm.Height field only)
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-27 "a part's package and
LCSC code, for a height survey" and "a one-face parts keepout refuses a cell
on the other face"

## The problem

A case leaves limited room over parts of the board: 1.9 mm over the front of
a ring, 2.17 mm over the back. The board keeps tall parts out with a parts
keepout per ring and face, and lets short ones in by naming them in
`allow=`. The list was built by hand from a height survey (datasheets, a
regex over the board file, a JSON of heights) and goes stale whenever a part
is added or swapped. placemat knows nothing of a part's height.

## The change

1. **A part's height** is the footprint field `Pm.Height` (the capture sets
   it, as it sets `Pm.I`), a length such as `1.1mm` or `1.1`; without it the
   height is unknown. (Reading a 3D model's extent was left out: it needs a
   STEP reader placemat does not carry.)
2. **`board.keepout(..., max_height=1.9)`** on a `parts` exclusion admits a
   part no taller than `max_height` and refuses a taller one, as `allow=`
   admits a named one. A part whose height is unknown is refused, and the
   finding says its height is unknown and how to give it (`Pm.Height`).
   `allow=` still admits by name, whatever the height.
3. **Queries.** `board.height_of(part)` (`board.height` is the frame's) gives a part's height or raises when it
   is unknown; `placemat parts` gains a height column (`-` when unknown) and
   `--json` a `height` (null when unknown).
4. **Docs.** api.md's keepout paragraph and verb table, the placemat-design
   skill's `Pm.*` list (`Pm.Height`), SKILL.md's line on regions, and the
   migration note: a keepout whose `allow=` lists short parts by name can
   say `max_height=` once the parts carry heights.

## Verification

- Pure tests: a part with `Pm.Height` under and over a region's
  `max_height` is admitted and refused; an unknown height is refused with
  the finding; `allow=` still admits a tall named part; `board.height_of()`.
- Bench, as a placement change (no bench board declares `max_height`).

## Not in scope

- A height map of the case: the regions and their limits are the script's.
- Heights for a stamped cell as a whole: each member is judged.
