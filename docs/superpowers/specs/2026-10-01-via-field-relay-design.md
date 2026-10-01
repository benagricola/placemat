# A via field re-laid round a conflict

Status: built (2026-10-01).

Source: the give-way investigation of an item meeting some of the vias of an
exposed pad's field. Builds on 2026-09-30-plane-drops-and-the-far-face-design.md,
section 1, and 2026-10-01-in-pad-via-leaves-its-pad-design.md; sits beside
2026-10-01-routed-via-moves-design.md.

## Problem

A field is the vias of one net standing in one pad of that net: a thermal or
exposed pad filled with a square grid, or a plane net's drop vias in a pad
(`Drops`' fields, `_Owner.counts`). Where another item's copper, on either
face, meets some of the field's vias, give-way works one via at a time: share,
move, leave the pad, shorten, then drop. The only step that takes a via out of
the way of a row of them is drop, and drop never adds one. A 3 x 3 field with
one row under another item's pad ends as a 3 x 2 field plus a lost via or two,
though the pad has room beside the row. A field of a net that is no plane,
which can never be dropped, has no step at all and the spot is refused.

Give-way state is per via (`Action` by via id, `undo(via)`). Nothing says "this
field changed as one", nothing reports what the field held before and after,
and nothing chooses between ways of making room: move the row, close the
pitch, take a via out, take a row out.

Scope. Only a field of carried vias can give way, and these are a stamped
cell's own vias. A part's `board.vias()` grid is planned after the part has
landed, against the board as it stands, and is not carried: it already skips a
site that is not clear, and a later item is judged against it as copper, not
as a field. Carrying that grid is separate work and not part of this spec.

## Design

### 1. The step

A new give-way step, `relay`, between move and leave:

> 3. relay: a via of a field, none of whose own steps (share, move) worked,
>    has its field re-laid as a whole: the vias that meet the item are moved
>    or taken out and vias are moved or added, inside the pad, so the field
>    keeps its count where the pad allows it.

Order in the step list, and cost: it is tried after a via has failed to share
or to move on its own, and before it leaves its pad, since a field re-laid in
its pad keeps what the pad is for and a row of vias leaving by tails does not.
`score.via_relay` (3) sits between move (2) and leave (4); `least_cost`
counts it as a way when `place.via_relay` is on.

The step runs once per field per resolution. It handles every via of the field
that meets the item, so a row is one step, not one per via. Vias of the field
that the resolution has already given way (shared, moved, shortened, dropped)
are fixed, as are a via with a tail and a routed via: they hold their sites,
count toward the field's count, and the layouts keep clear of them.

It applies to a via that is a stamped cell's own, has no tail, is not routed
(`_give_routed` is its only step), and has its centre inside a pad of its net,
in a field of at least two vias. `place.via_relay` (default true; false never
relays) turns it off. It is attempted only where give-way is enabled at all.

A field's target count is the count it was drawn with (the cell's vias, as
stamped and as `Drops` thinned them). The floor is the existing one: for a
plane net `ceil(place.drops_keep * target)`, at least one; for any other net
the target itself, so a relay that cannot hold the count is no relay and the
vias fall back to their other steps as today. Fewer than the target but at
least the floor is allowed and reported. A field already short (drops given
way to an earlier item) may be brought back up to the target.

### 2. Candidate layouts

The field is read in its own frame: axis `u` along one of the pad's edge
directions or the direction of the field's closest pair of vias, whichever the
vias fall on the fewest lines under (the longest edge's on a tie), `v` across it. Its columns are the distinct `u` of its vias, its rows the
distinct `v`. The pitch is the field's own adjacent-line spacing (the median).
The closest two vias may stand is `max(via size, drill + hole-to-hole)`, which
is what `board.vias()` uses by default. A site is legal when its ring lies
wholly inside the pad (`board.vias()` with its default inset of 0), and the
via's ring and hole, judged as a move's are, meet nothing: every other net's
copper on every layer the via spans, every hole, the board's edge, and the
item's own copper. The far face's copper is among them. The vias of the field
that are free to move are set aside while sites are judged, so a layout may
use the room they leave; every site of a layout is also held the closest
pitch from every other.

A set of candidate layouts is generated, each a set of sites in the pad. Vias
map onto sites by nearest, so a via that keeps its site is untouched, one that
takes another site is a move, a site with no via is an add, a via with no site
is a removal. A layout that leaves a via standing on what it meets, has two
vias on a site or nearer than the closest allowed, a site outside the pad, or
fewer vias than the floor (or more than the target), is not a layout.

| way | candidates |
|---|---|
| shift vias | each via that meets the item goes to the nearest free site of the field's lattice (its lines extended past the field's edges at the pitch), or is taken out when there is none |
| shift a row or column | a line holding a conflict, all its vias, moves to a free line of the lattice, keeping its place along the line; vias of it with no clear site there are taken out; conflicts left in other lines are shifted as above |
| remove a row or column | the lines that hold the conflicts are taken out whole, the rest stay where they are |
| close the pitch | every line moves toward one end of an axis, the line spacing narrowed in `place.via_move_step` steps until two vias would stand closer than the closest allowed |
| uneven pitch | the lines on one side of a pivot line move together along an axis, by what the pad and the gap beside the pivot allow, in `place.via_move_step` steps; with the pivot at the first line the whole field slides |
| remove vias | the vias that meet the item are taken out; this is what drop does, and is generated only to compare |

The first four ways are generated first. The pitch ways need every via of the
field free to move, and each is walked from the smallest change up (a larger
one moves the same vias further and costs more), stopping at the first layout
that is legal; they are generated only when what the others found costs more
than the least a pitch layout could (`score.via_relay` plus the cheaper of a
move or a drop for each via that meets the item).

### 3. Choosing

Each candidate has a cost, all weights settings:

```
cost = score.via_relay
     + score.via_drop          * (target - vias kept)
     + score.via_relay_moved   * (vias moved + vias added)
     + score.via_relay_gap     * (empty sites in the lines' grid, beyond the field as drawn)
     + score.via_relay_pitch   * (mm the line spacings depart from the drawn pitch, summed)
```

Defaults 3, 10 (existing), 0.5, 1, 4. A via lost costs what a drop costs, so
the count weighs most; moving a via is cheap; a regular grid (no gaps, the
drawn pitch) is a weight below the count. Candidates are ordered by cost
(ties: more vias kept, then the order of the table) and judged lazily: the
first legal one wins. Site judgments are cached by position within a
resolution. If the winner is "remove vias" alone, which costs no
`score.via_relay`, the step does not apply and the vias take the drop step as
today.

The relay's own cost is what the search adds to the spot, once per field; the
vias it moves are in it.

### 4. State and undo

The relay is a group of per-via actions (`FieldStep`, a subclass of `Action`)
that share a field id ("field <cell> <ref>.<pad>") and carry the way, the
count before and after, and the target. Kinds: `relay-move`, `relay-drop`,
`relay-add`. They live in `given_way` by via id like any action, so apply, the
cell's write and replay work on them as they do on a move or a drop. An added
via has an id of its own ("<cell> relay <k>") and its shapes carry it, so it is
a carried via that may give way in turn; a via a relay added that then moves is
an add at its new place (`chain`).

`undo(via)` on any via of a field undoes the field: every step of it, and the
vias that share one of them. Putting an item back (`_put_back`) does what it
did, and the field's steps go with its other vias'. A resolution refused for
another via leaves nothing applied.

The drop step's keep arithmetic counts what the field holds now, not only the
drops given way, so a field a relay left short is not dropped below its floor.

### 5. The write

The cell's group on the board is changed: a `relay-move` moves the via, a
`relay-drop` deletes it (`board.Delete`), a `relay-add` adds a copy of the
nearest via of the field (size, drill, layers, type) at the new site, in the
cell's group. Adds are made before any via is removed, and each action finds its
via at the position drawn before any is changed.

### 6. The report

A field re-laid is a note on its item's step and part of its item's finding of
kind `vias`: "m: GND field in U1 pad 1 re-laid by shift vias, 9 vias before, 9
after under R9". Fewer than the target says so: "6 after (9 drawn)". Vias
dropped from a field report what the pad holds: "3 GND vias dropped under R9
(U1 pad 1 holds 6 of 9)".

### 7. Settings

| setting | default | |
|---|---|---|
| `place.via_relay` | true | re-lay a field before its vias leave the pad or are dropped |
| `score.via_relay` | 3 | a field re-laid, once |
| `score.via_relay_moved` | 0.5 | each via moved or added by a relay |
| `score.via_relay_gap` | 1 | each empty site a relay leaves in its grid beyond the drawn field's |
| `score.via_relay_pitch` | 4 | per mm the line spacings depart from the drawn pitch |

### 8. Not covered

- A declared count: the grid forms take no count today (`count=` is for a row
  along an axis), so the target is the count drawn.
- `inset=`: a stamped cell does not know the inset its grid was laid with; a
  new site is inside its pad as `board.vias()` keeps it by default.
- A part's `board.vias()` grid (section Problem).
- Mixed via sizes or drills in one field: it is not re-laid.

## Verification

Unit tests (tests/test_via_field_relay.py, tests/test_via_field_relay_kicad.py):

1. A 3 x 3 field in a pad with a free row, another item's pad on the far face
   along one row: the row moves to the free side, 9 vias, all legal, the
   report says 9 before and 9 after; the same before the vias may leave their
   pad.
2. A pad with no room: falls back to drop, the count reported; with relay off
   the same drop.
3. A pad that only closing the pitch makes room in, and one only an uneven pitch
   does, keep 9; a whole row is taken out when `score.via_relay_gap` outweighs
   the lost vias, and plain removal is left to drop otherwise.
4. A field of a net that is no plane with no room is refused, as before; with
   room it is re-laid.
5. The keep share is held, and a later drop counts what a relay took.
6. A field re-laid for one item is re-laid again for the next.
7. Undo: any via of the field undoes it, an added via included; a refused
   candidate leaves the occupancy as it was.
8. A routed via of the field stays where it is.
9. Weights: `score.via_relay` and `score.via_relay_moved` priced in a scan;
   settings defaults and bounds; `least_cost`.
10. Parity: the same result with the native move search, first-move and tail
    calls switched off (the relay itself is judged in Python, as a leave's
    tail is).
11. The write (pcbnew): moves, adds and deletes vias in the cell's group, and
    kicad-cli DRC on the written board is clean where the field as drawn is not.

Real board: the whole-board fixture (`fixtures/fairing/core`) has stamped cells
with fields up to 36 vias. A cell with a 6 x 6 field in an exposed pad is put
firmly, and another cell on the far face searched at the field; the give-way
tallies are compared with `place.via_relay` off and on, and kicad-cli's DRC is
run on the two cells' pads and vias as left. The bench's module boards carry no
stamped cells, so they are unchanged; the bench tally is in the commit.
