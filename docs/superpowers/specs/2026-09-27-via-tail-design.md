# A via found near a pad, joined to it

Date: 2026-09-27
Status: proposal, awaiting approval

## The problem

`board.via(net, FreeSpot(near=PadRef(...)))` finds the nearest spot a via
can stand beside a pad. The search already checks that a straight tail on
the pad's layer can reach it (`_free_spot`, layout.py: the "tail" rejection).
It draws the via only. A track cannot end on it either: `_locate` has no case
for a via, so a script cannot join the via to its pad or run a track on from
it.

The via is left beside its pad, unconnected. Three PLACEMAT_GAPS reports hit
this (2026-09-26 "fixed bypasses at power-land ends and ground-via tails",
2026-09-26 "a searched via cannot be a track endpoint", 2026-09-27 "a plane
drop needs a typed via position"). The board's scripts work round it by
typing via positions as pad offsets copied from `placemat occupancy
--via-near`. Those offsets go stale when a part moves, turns or its footprint
is corrected, which is the coordinate typing the search was meant to remove.

Via-in-pad covers most plane drops on a board that pays for filled vias. The
tail is still needed for pads too small to hold a via: fine-pitch leads, and
small passives' pads.

## The change

1. **A FreeSpot via draws its tail.** `FreeSpot(..., tail=True)` adds the
   straight track from the pad's centre to the via on the searched layer, at
   the width the search checked (the net class's track width). The search
   already accepts only spots whose tail clears, so the tail is the one that
   was judged. A via in the pad (`in_pad=True`) draws no tail. **Default:
   `tail=True`.** An unjoined via beside a pad is almost never what a script
   means; a script that wants the via alone says `tail=False`.
2. **A via is a track end.** `board.via()` returns its intent already. That
   intent becomes a valid point in `board.track()`: it resolves to the via's
   centre once the via is planned. A track so declared plans after its via,
   because copper plans in declaration order within its tier and the track
   inherits the via's pads as its dependencies (a searched pad makes both
   searched). If the via found no spot, the track is not drawn and a finding
   names both.
3. **Docs.** api.md's "A via where one fits" paragraph, the verb table line
   for `board.via`, the migration note for 0.38, and one SKILL.md line.

A drop verb (`board.drop(PadRef, layers=)`) is left out: with the tail on
by default, `board.via(net, FreeSpot(near=pad))` is the drop.

## Verification

- Pure tests (synthetic boards):
  - a FreeSpot via's tail runs from the pad centre to the via, on the pad's
    layer, at the class width, and is one of `plan.copper`'s tracks;
  - `tail=False` and `in_pad=True` draw no tail;
  - on a searched part, the tail meets the pad where the part landed (the
    part placed away from its generated position);
  - a track through a via intent starts or ends at the via's centre, and a
    via that found no spot leaves the track out with a finding.
- KiCad test (breakout board): a FreeSpot via with its tail on a searched
  part's pad adds no DRC violation, no unconnected item and no dangling via.
- The bench, as for any placement change. FreeSpot vias plan after the
  searched tier, so the tally should be the same.

## Not in scope

- A `Pin` or cutout placed relative to a searched item ("only FIXED and EDGE
  items may be referred to"): its own change.
- Routing a tail that is not straight, or choosing the layer by what is
  free: the search's straight tail on one layer is kept as is.
