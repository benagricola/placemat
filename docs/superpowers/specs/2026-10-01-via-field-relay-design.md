# A via field re-laid round a conflict

Status: draft (2026-10-01).

Source: the give-way investigation of a part meeting some of the vias of an
exposed pad's field. Builds on 2026-09-30-plane-drops-and-the-far-face-design.md,
section 1, and 2026-10-01-in-pad-via-leaves-its-pad-design.md.

## Problem

A field is the vias of one net standing in one pad of that net: a thermal or
exposed pad filled with a square grid, or a plane net's drop vias in a pad
(`Drops`' fields, `_Owner.counts`). Where another item's copper, on either
face, meets some of the field's vias, give-way works one via at a time: share,
move, leave the pad, shorten, then drop. The only step that takes a via out of
the way of a row of them is drop, and drop never adds one. A 3 x 3 field with
one row under another item's pad ends as a 3 x 2 field plus a lost via or two,
though the pad has room beside the row. A field of a non-plane net, which can
never be dropped, has no step at all and the spot is refused.

Give-way state is per via (`Action` by via id, `undo(via)`). Nothing says "this
field changed as one", nothing reports what the field held before and after,
and nothing chooses between ways of making room (move the row, close the
pitch, take a via out, take a row out).

Scope. Only a field of carried vias can give way, and these are a stamped
cell's own vias. A part's `board.vias()` grid is planned after the part has
landed, against the board as it stands, and is not carried: it already skips a
site that is not clear, and a later item is judged against it as copper, not
as a field. Carrying that grid is separate work and not part of this spec.

## Design

### 1. The step

A new give-way step, `relay`, between shorten and drop:

> 5. relay: a via of a field, none of whose own steps worked, has its field
>    re-laid as a whole: the vias that meet the item are moved or taken out
>    and vias are added or moved, inside the pad, so the field keeps its
>    count where the pad allows it.

The step runs once per field per resolution. It handles every via of the
field that meets the item, so a row is one step, not one per via, and the
vias of the field that the resolution has already given way (shared, moved,
shortened, dropped) are fixed.

It applies to a via that is a stamped cell's own, has no tail (a via a track
meets is part of a route and stays), and has its centre inside a pad of its
net, where the field has at least two vias that are free to move. `place.via_relay`
(default true; false never relays) turns it off; it is attempted only where
give-way is enabled at all.

A field's target count is the count it was drawn with (the cell's vias, as
stamped and as `Drops` thinned them). The floor is the existing one: for a
plane net `ceil(place.drops_keep * target)`, at least one; for any other net
the target itself, so a relay that cannot hold the count is no relay and the
vias fall back to their other steps as today. Fewer than the target but at
least the floor is allowed and reported. A field already short (drops given
way to an earlier item) may be brought back up to the target.

### 2. Candidate layouts

The field is read in its own frame: axis `u` along the pad's longest edge
(the nearest-neighbour direction for a round pad), `v` across it. Its columns
are the distinct `u` of its vias, its rows the distinct `v`. The pitch is the
field's own adjacent-line spacing (the median), the closest pair of vias may
stand `max(via size, drill + hole-to-hole)` apart, which is what
`board.vias()` uses by default. A site is legal when its ring, grown by
nothing, lies wholly inside the pad (`board.vias()` with its default inset),
and the via's ring and hole, judged as a move's are, meet nothing: every
other net's copper on every layer the via spans, every hole, the board's edge,
and the item's own copper. The far face's copper is among them.

A set of candidate layouts is generated, each a set of sites in the pad.
Vias map onto sites by nearest, so a via that keeps its site is untouched,
one that takes another site is a move, a site with no via is an add, a via
with no site is a removal.

| way | candidates |
|---|---|
| shift vias | each via that meets the item goes to the nearest free site of the field's lattice (its lines extended past the field's edge at the pitch), or is taken out when there is none |
| shift a row or column | a line holding a conflict, all its vias, moves to a free line of the lattice, keeping its place along the line; vias of it with no clear site there are taken out |
| close the pitch | every line moves toward one end of an axis, the line spacing narrowed in `place.via_move_step` steps down to where two vias would stand closer than the closest allowed |
| uneven pitch | the lines on one side of a pivot line move together along an axis, by up to the room between the pivot and its neighbour or the pad's edge, in `place.via_move_step` steps |
| remove a row or column | the lines that hold the conflicts are taken out whole, the rest stay where they are |
| remove vias | the vias that meet the item are taken out; this is what drop does, and is generated only to compare |

A candidate that keeps a via standing on what it meets, or has two vias nearer
than the closest allowed, or has fewer than the floor, is discarded without
judging. The close-pitch and uneven-pitch candidates need every via of the
field free to move.

### 3. Choosing

Each candidate has a cost, all weights settings:

```
cost = score.via_relay
     + score.via_drop          * (target - vias kept)
     + score.via_relay_moved   * (vias moved + vias added)
     + score.via_relay_gap     * (empty sites in the lines' grid, beyond the field as drawn)
     + score.via_relay_pitch   * (mm the line spacings depart from the pitch, summed)
```

Defaults 6, 10 (existing), 0.5, 1, 4. A via lost costs what a drop costs, so
the count weighs most; moving a via is cheap; a regular grid (no gaps, the
drawn pitch) is a weight below the count. Candidates are ordered by cost
(ties: more vias kept, then the order of the table) and judged lazily: the
first legal one wins. Site judgments are cached by position within a
resolution. If the winner is "remove vias" alone the step does not apply and
the vias take the drop step as today.

The relay's own cost, `cost` above without the `score.via_drop` term when
nothing is lost, is what the search adds to the spot, once per field; its
moved vias add nothing separately. Order in the step list: it costs more than
shorten (5) and less than a drop (10) when it keeps every via, so it is tried
after shorten and before drop. `least_cost` counts `score.via_relay` as a way
when `place.via_relay` is on.

### 4. State and undo

The relay is a group of per-via actions (`FieldStep`, a subclass of `Action`)
that share a field id ("field <cell> <ref>.<pad>") and carry the way, the
count before and after, and the target. Kinds: `relay-move`, `relay-drop`,
`relay-add`. They live in `given_way` by via id like any action, so apply, the
cell's write and replay work on them as they do on a move or a drop. An added
via has an id of its own ("<cell> relay <k>") and its shapes carry it, so it
is a carried via that may give way in turn.

`undo(via)` on any via of a field undoes the field: every step of it, and the
vias that share one of them. Putting an item back (`_put_back`) does what it
did, and the field's steps go with its other vias'.

The drop step's keep arithmetic counts what the field holds now, not only the
drops given way, so a field a relay left short is not dropped below its floor.

### 5. The write

The cell's group on the board is changed: a `relay-move` moves the via, a
`relay-drop` deletes it (`board.Delete`), a `relay-add` adds a copy of the
nearest via of the field (size, drill, layers, type) at the new site, in the
cell's group. Adds are made before any via is removed, and each action finds
its via at the position drawn before any is changed.

### 6. The report

A field re-laid is a note on its item's step and a finding of kind `vias`:
"m: GND field in U1 pad 1 re-laid by shifting a row, 9 vias before, 9 after
(under R9)". Fewer than the target says so: "7 of 9". A field whose relay
fell back to drop reports as drop does today.

### 7. Settings

| setting | default | |
|---|---|---|
| `place.via_relay` | true | re-lay a field before dropping from it |
| `score.via_relay` | 6 | a field re-laid, once |
| `score.via_relay_moved` | 0.5 | each via moved or added by a relay |
| `score.via_relay_gap` | 1 | each empty site a relay leaves in its grid beyond the drawn field's |
| `score.via_relay_pitch` | 4 | per mm the line spacings depart from the drawn pitch |

### 8. Not covered

- A declared count: the grid forms take no count today (`count=` is for a
  row along an axis), so the target is the count drawn.
- `inset=`: a stamped cell does not know the inset its grid was laid with; a
  new site is inside its pad as `board.vias()` keeps it by default.
- A part's `board.vias()` grid (section Problem).

## Verification

Unit tests (tests/test_via_field_relay.py):

1. 3 x 3 field in a pad with room for more than one more line, another item's
   pad on the far face along one row: the row moves, 9 vias, all legal, the
   report says 9 before and 9 after.
2. The same with room for none: falls back to drop, the count reported, the
   floor kept.
3. A field whose lines can only close the pitch, or only an uneven pitch,
   keeps its count; each way is the one chosen when the others are not
   possible.
4. A field of a non-plane net with no room is refused, as before.
5. A removed row is chosen when `score.via_relay_gap` outweighs the lost vias.
6. Weights: `score.via_relay` priced in a scan; settings defaults and bounds.
7. Undo: after a commit, `undo` of any via of the field restores every via as
   drawn and removes the added ones; a refused candidate leaves the occupancy
   as it was.
8. A later item meeting a field already re-laid: relays again, count held.
9. Parity: the same result with the native move search and first-move calls
   switched off.
10. The write (pcbnew): moves, deletes and adds vias in the cell's group, and
    kicad-cli DRC on the written board is clean.

Real board: a fixture under `fixtures/` with an exposed-pad via field, run
through the bench; the give-way tallies and each placement that moves are
reported in the commit.
