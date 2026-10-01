# An in-pad via that leaves its pad, and what a refusal says about vias

Status: draft (2026-10-01).

Source: a board's session (2026-10-01), a part's placement refused with
"the via V3V3 at (x, y) cannot give way: no V3V3 via within 1.00 mm to
share, no spot within 0.50 mm inside its pad is clear, FB1 pad 1 keeps 1 of
its 1 drops, and must keep 1". Builds on
2026-09-30-plane-drops-and-the-far-face-design.md, section 1.

## Problem

A carried via gives way to another net's copper by sharing a same-net via,
moving, shortening or being dropped (`giveway.py`). Three gaps:

1. A via whose centre lies in a pad of its own net and that has no tail may
   only move inside that pad: a move out would leave the pad unjoined. A
   0.45 mm plane drop in a 0.80 x 0.95 mm back-face pad, directly under
   another part's pad on the front, has about 0.17 x 0.25 mm of play, and
   none of it clears the front pad. With one drop in the pad the drop step
   is closed too (the pad must keep its one drop), so the part has no spot.
   A via beside its pad, joined by a short track, would clear it.
2. Shorten is not tried when the fab profile's tier for the shortened via
   type is "no". A refusal for a spot where a blind via would have cleared
   says nothing of it, so the reader cannot tell that the fab profile, and
   not the board, is what stops the part. "if-needed" already says so.
3. A run's refusal tallies bucket a sentence under the first of a fixed list
   of words it contains (`_reason_key`). A refusal caused by a carried via
   that could not give way is counted as "copper", "through" or "hole-to-hole"
   with the refusals of plain pads, and the count that says vias are the
   problem is not there.

## Design

### 1. A via leaves its pad

A new give-way step, between "move" and "shorten":

> 3. leave its pad: a via whose centre is inside a pad of its net and that
>    has no tail, when no spot inside the pad is clear, moves to the nearest
>    spot clear of every other net's copper and every hole within
>    `place.via_leave` of where it stood, and a new tail is drawn on the
>    via's own pad face from where it stood, in the pad's copper, to the
>    via.

- The reach is its own setting, `place.via_leave` (default 1.0 mm; 0
  never leaves). Clearing a pad on the other face usually takes the
  ring's radius plus the clearance past that pad's edge, more than the
  0.5 mm `place.via_move` allows for a move that keeps the via in its pad.
  The spots are searched on `place.via_move_step`, nearest first, as a move's
  are.
- The tail is on the layer `who.layer` gives the via (its pad's outer layer on
  the item's face), from the via's old centre to its new one, so it starts
  in the pad's copper and the two are joined. Its width is the net class's
  track width. Where that width meets another net's copper or the pad's
  edge leaves too little room, the nearest spot is kept and the width is
  stepped down by 0.05 mm to the board's minimum track width
  (`BoardGeometry.min_track_width`, read from the board's rules; 0 where it is
  not known, which tries the net's width only), the widest that is clear
  at that spot. The tail is judged as any tail is: clear of every other
  copper and hole, and the edge.
- The via keeps its net, its size, drill and layer span. It is joined to
  its pad by the tail, so the net's connection is as it was. A via that has
  left stands as a carried via with a tail, so a later item's copper that
  meets it moves it as any tailed via moves (the tail is redrawn from the
  pad).
- Cost: `score.via_leave`, default 4.0, between `score.via_move` (2) and
  `score.via_shorten` (5).
- The action is `Action("leave", ...)`: `to` the new centre, `tail` the track
  drawn. The part's pad via is drawn at `to` with the tail; a stamped cell's
  via is moved in the write as a move is, and the plan's copper carries the
  tail. The report names it: "1 V3V3 via left its pad".

Step order. Share and move keep the via where its pad is already joined, and
are tried first. Leaving comes next, ahead of shorten and drop, because it
costs a tail but changes neither the via's type (shorten needs the fab
profile) nor the pad's connection or its count of drops (drop removes a plane
connection and is limited by `place.drops_keep`). It is tried only when no
spot inside the pad is clear, so a pad with room is unchanged.

Native code judges only the board's side of a via's move (clear offsets, a
move's first spot). Leaving uses the same calls with the larger reach and a
tail starting at the old centre, so the native and Python searches decide
alike; a parity test covers it.

### 2. The refusal names a shorter via the fab profile does not allow

Where a shorten (drop reshaped to its own face and the nearest layer of its
plane, `_shorten`) would have cleared the conflict but the profile's tier for
its type is "no", the refusal adds:

> a blind via from B.Cu to In3.Cu would clear this; the fab profile does not
> allow blind vias

(micro or buried for the other types). It is a refusal sentence, not a
`needs` note: nothing places with it. "yes" and "if-needed" are as before.

### 3. A tally of vias that could not give way

A refusal whose sentence says a carried via "cannot give way" is counted
under its own bucket, "via cannot give way", ahead of the word list in
`_reason_key`, and the placement note prints it as "vias that could not give
way xN", always, as a rider's refusals are. Its count leaves the bucket
the first word would have given it.

### Settings

| Setting | Default |
|---|---|
| `place.via_leave` | 1.0 mm |
| `score.via_leave` | 4.0 |

Both are at least 0. `enabled()`, `reach()` and `least_cost()` count them.

## Verification

1. A pad on one face with a single in-pad plane drop, another part's pad over
   it on the other face, about 0.17 x 0.25 mm of play: the part places, the
   via is outside its pad joined by a tail on the pad's face at the net's
   width, and KiCad's DRC on the written board shows no clearance and no
   unconnected item.
2. A pad with room inside still moves inside, with no tail.
3. A tail that needs it is narrower, no narrower than the board's minimum
   track width; none clear gives the refusal.
4. A "no" tier: the refusal carries the sentence; "yes" shortens as before.
5. The tally: refusals by a via that cannot give way count under their own
   bucket and the note prints it.
6. Native parity of a leave over random boards.
7. Bench: tallied in the commit.
