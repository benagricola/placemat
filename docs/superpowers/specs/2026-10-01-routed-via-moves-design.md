# A routed via moved with its tracks

Status: draft (2026-10-01).

Builds on 2026-09-30-plane-drops-and-the-far-face-design.md, section 1, and
2026-10-01-in-pad-via-leaves-its-pad-design.md.

## Problem

A stamped cell's via gives way to another net's copper on either face by
sharing, moving, leaving its pad, shortening or dropping (`giveway.py`). The
steps take a via with at most one track of the cell's on it: its tail,
redrawn straight from its far end. A via that two or more of the cell's
tracks end on (a layer change in the middle of a route, a junction) is part
of a route: `occupancy._cell_vias` does not carry it, so it never gives way
and a cell whose routed via meets the other face's copper is refused, at
every spot, however short a move would clear it.

Moving it needs the tracks to follow. A straight redraw of each track from
its far end to the new centre leaves legs at any angle, and placemat's
tracks are octilinear.

## Design

### A routed via is carried

`_cell_vias` carries a via that two or more of the cell's same-net tracks end
on, when `place.via_route` is above 0: the via's ring and hole, and each
track that ends on it, carry its id as a via's ring and tail do, so a search
judges the item less them and `giveway.resolve` judges them whole. `Group`
has `legs`, the tracks of the via (`tail` is the one leg of a via with one);
a group with more than one leg is routed.

A via is still not carried when a track ends on it and runs on to another
via of the cell's (a track shared by two vias has no one owner), and the
rule for a via with no tail, one tail, or inside a pad of its net is
unchanged. With `place.via_route` 0 a routed via is not carried: the rule
as it was.

### The route move

A routed via has one give-way step, tried in place of the others: share,
leave, shorten and drop do not apply to a via that joins several tracks. It
moves up to `place.via_route` (default 0.5 mm) on the `place.via_move_step`
grid, nearest first, to a spot where:

- its ring and hole are clear of every other net's copper and every hole
  (the native offset search `_native_move_offsets` finds them, as for a
  move), and clear of the item's own copper;
- a via inside a pad of its net stays inside it, as a move does;
- each of its tracks, rebuilt from its far end (the end that is not on the
  via, where it stays) to the new centre, is clear.

A track's rebuilt path is `copper.octilinear` between its far end and the new
centre (with `copper.straight_tolerance`), its right angles chamfered by
`copper.chamfer`: the same router and chamfer that draw a declared track
between two points (`route_leg`: at most three legs at 0, 45 or 90 degrees,
fewest turns, then shortest), with `clear` set to the judging of a track segment of the
track's layer and width against the board and the item's own copper
(`_tail_hit`, native where a native index is registered, as a share's tail
is). Its candidates that cross another net's copper are not used; a track for which
none clears refuses that spot, and the next spot is tried. The width and layer of
each track are its own. A spot where a track would have no length (the
centre on its far end) is not used.

The unit: a spot is used only when the ring, the hole and every track
clear; the Action carries them all, and a spot where one fails leaves the
via and all its tracks as drawn. Undo (`giveway.undo`) puts the via and
every track back, as it does for a tail.

Only the cell's own tracks that end on the via are rebuilt; the far ends
stay, and the track that continues from a far end is not touched.

A routed via that has moved stands as a carried via whose legs are the
segments of its rebuilt tracks (each carrying its id, with its end toward
the via first, as a tail's points are). A later item's copper that meets it
rebuilds each leg from the far end of its chain, the end furthest from the
via along the segments that join, the same way.

### Step order and cost

For a routed via the route move is the whole order: it is the move of a via
with several tracks. The refusal names the via and says "no spot within 0.50
mm is clear with its N tracks rebuilt", or, with `place.via_route` 0, the
via is not carried and the item is judged as before.

Cost `score.via_route`, default 3.0: above `score.via_move` (2), because it
redraws tracks, below `score.via_leave` (4). `least_cost()` counts it.
`enabled()` and `reach()` count `place.via_route`.

### Action and write

`Action("route", ...)`: `to` the new centre, `tracks` the Tracks drawn (every
segment), `old_tracks` the (via end, far end) of each track taken away as
drawn, `shapes` the ring, the hole and the segments. The plan draws `tracks`
with its copper; the write (`kicad.write._given_way`) moves the via and
deletes each of `old_tracks`. The report names it: "1 SIG via re-routed
0.15 mm".

### Native

Judging is the existing native calls: the offset search for the ring and
hole, and `tail_clear` for each segment. No new native code; the Python
fallback (`_NATIVE_MOVE_SEARCH`, `_NATIVE_TAIL_CLEAR` off) decides the same
spot, which a parity test checks.

### Settings

| Setting | Default |
|---|---|
| `place.via_route` | 0.5 mm |
| `score.via_route` | 3.0 |

Both are at least 0; 0 is "never".

## Verification

1. A cell with a via joined by two tracks (one an L whose far end is a
   corner, one straight), the other face's pad over the via: the item places,
   the via has moved, both tracks join it by octilinear legs, no clearance
   violation by placemat's judge, and `kicad-cli pcb drc` on the written
   cell (via, tracks, pads) shows no clearance violation and no unconnected
   item.
2. A spot whose rebuilt leg would cross another net is refused and the next
   spot is tried; the chosen spot's legs are clear.
3. Nothing within reach: refused, naming the via, the reach and the tracks.
4. Undo restores via and tracks.
5. A via with no tail, one tail, or in a pad is as before.
6. Native and Python judging choose the same spot.
7. A real board: a stamped cell of a fixture whose routed via meets the other
   face's copper, placed with this and without; the bench tally.
