# Turned escapes that keep clear, and handoff pins boxed in

Status: approved (2026-10-02, as requests from a board's session; the owner's hand
layout is the reference).

Source: a board's session (2026-10-02). Builds on
`2026-10-01-escape-lanes-design.md`: `board.escape(..., turn=Corner.X)` keeps its
keywords. The file name is the first request's, a fan of lanes that run to the pads
they serve; that request is the rejected option below.

## Problem

A 0.4 mm pitch QFN-56 (track 0.16, clearance 0.16) leaves one side's pins in fans at
45 degrees. The hand layout of that side:

- Parallel 45s stand track + clearance (0.32) apart across their direction. The pins
  are 0.4 apart along the row, so each next riser is 0.32 * sqrt(2) - 0.4 = 0.0526
  longer, counted from the pin at the row's end (the lines' x - y are 0.4526 apart).
- The first risers are short: a 45 moves away from its row, so it needs none of the
  depth a lane parallel to the row does (a track and a clearance past the tips).
  Pins 44 and 45 of the hand layout end their risers 0.11 and 0.17 mm past the pad
  tips.
- A bypass part stands beside pin 46, turned 135, between the fan of pins 43-45
  and the fan of pins 47-52.

What 0.79.0 gives for `escape(part, [44, 45], turn=Corner.NW)` over the same pins:

1. The lanes are laid out a step apart (`lanes.py`, `_offsets`), but the first
   lane's riser is a track and a clearance past the tips, 0.32 mm, where the 45 would
   clear the row at 0.04. The second lane's 45 then runs 0.08 mm from the bypass's
   pad.
2. A track that begins with a lane is routed leg by leg (`copper.octilinear`). A leg
   that is not clear of placed copper is rerouted. The reroute round the bypass pad
   did not see the first lane's track, which is planned in the same batch and is not
   in the occupancy, and ran over it: KiCad reports the two nets shorting.
3. The depth is counted from the pins the escape names, so two escapes of one row lay
   their lanes at depths that are not a stagger apart.

Separately, a net with one pad on a module's board leaves the module (a handoff pin:
a net and no internal connection). It keeps no corridor in the placement search
(`escapes.pad_corridors`: nothing to join) and no run reports it closed in. A pin the
script names in `escape()` has its lane reserved; a pin it does not name has nothing,
so internal copper can close its way out unnoticed. A pin whose stub is legal can be
closed in beyond the stub's end.

A third item, in the same module: a searched part (an RF matching inductor) settles at
a spot with its link at 1.84 mm while a spot a fine step from the search's own lattice
is legal, accepted, scores better and has the link at 1.50 mm (its limit).

## Options

**Fan lanes to targets.** The first request: `board.escape(..., to={pin: PadRef})` to
run each 45 on until it is level with the pad it serves and then straight into it,
`past=[...]` to start a fan's first 45 past a part, and the escape waiting to be laid
out until the parts it names are placed. It was specced, built and withdrawn.

Rejected. The board's session found that ordinary pad-to-pad tracks, plus one
`Past(...)` waypoint with `bend=Bend.START`, already route all six internal tracks of
the fan as the hand layout does. A new form would repeat what the existing ones
compose, and carries costs they do not: a lane whose extent depends on a part not
placed yet cannot be reserved when its own part is placed, so the escape must wait
and parts placed meanwhile do not see it; each lane's end moves with its target, so
neighbours' straight legs have to be checked against each other; and `past=` names the
parts the fan starts past, which a depth chosen for the pins alone does not need.
What failed was in the forms that exist: the lanes of one escape did not keep clear
of other copper, and a track drawn from a lane could leave it.

**Handoff pins, a finding or a reservation.** A finding says, once the copper is
planned, that a handoff pin is boxed in and names what closes it. A reservation keeps
a corridor or lane for every handoff pin from the start, as `escape()` does for the
pins it names.

The user's choice (2026-10-02): a finding only. The script declares `escape()` for the
pins it hands off. No automatic reservation: it would be a second way to say what
`escape()` says, it needs a way out per pin (a direction and a length) that the net
does not give, and it would put every single-pad net into the placement search and so
move every board's placements. Research on escape-routing prior art (ordered escape
routing, river routing, autorouter fanout passes) is running separately, and the open
option waits on it.

## Design

### Turned escapes

`turn=` a `Corner` and no `depth=`:

- **Stagger from the row's end.** Each pad of the row, named or not, is one stagger
  (step * sqrt(2) less the pitch along the row) further out than the pad nearer the
  turn side, and the first pad is at the tips. A named pin's lane stands at its pad's
  place in that stack, so two escapes of one row lay their lanes parallel, and a
  lane does not move when another pin is named. `step` is the one the lanes already
  use: the clearance and half of each track.
- **As near the row as it may.** A named lane is no nearer the tips than where it
  keeps its clearance from the row's other pads, and then from the copper placed and
  reserved (a part placed before the escape's part is placed, or reserved by an escape
  laid out first): the least offset at which its riser and 45 are clear, taken to the
  nanometre. Where none is clear within `place.escape_via_reach`, the lane keeps the
  offset that is clear of the row, and it is blocked: a finding, as any blocked lane is.
- `depth=` keeps its meaning: the innermost lane's offset, as given, and the stagger
  from it.

A track that begins with a lane draws the lane's own legs. A leg of the lane is
never rerouted round copper that stands too near it: the lane is a finding at
settle where it is blocked (an existing finding), the copper that comes later is
judged against the lane as against a drawn track, and a lane's leg that runs through
another net's copper is not drawn (`track ...: not drawn, it would run through ...`).

### Handoff pins

At the end of the run, a pad is reported when:

- its net has no other pad on the board, and is not a no-connect net (Zener's
  `NC_<part>_<pin>`, KiCad's `unconnected-(...)`, or any name under an instance path, with a dot);
- no via of its own net is on it or on its stub;
- no track or via can get out of it: a path of a track's width and clearance from the
  pad, and from the end of its own net's copper on it, to the edge of a window
  `score.escape_depth` round that copper or to a spot a via fits at.

Obstacles are the shapes themselves, not their boxes (a diagonal track's box is mostly
empty); a pad's own net's copper is part of the pad. The finding is `escape_walled`:
`U1 pin 45 (USB_WET): no other pad is on the net, so it leaves the board here, and it
is walled off by C1, track VBUS_DISCH`.

### The search

A scored scan over a wide radius is coarse first, then fine round its best spots
(`placer.scan`). The spots refined are the best `place.refine_around` by score, and the
best `place.refine_around` that `accept` (the items riding the one scanned) takes: a
coarse spot a rider refuses can have a neighbour it takes. Without `accept` the spots
are the ones it refined before.

## Verification

Synthetic: a 0.4 mm pitch QFN-56, a bypass part turned 135 beside pin 46.

- Stagger: pins 43, 44, 45 and the pairs of them named alone: the same risers, 0, 1
  and 2 staggers past the tips, to the nanometre; two escapes of the row (43-44, 47-48)
  with lines 0, 1, 4, 5 steps across.
- Clearance: the first lane clears the row's pads, and the bypass part's pads, by at
  least the clearance.
- A lane drawn at the depth a lane parallel to the row needs, the bypass part's pads
  0.15 mm from it: the findings; the track is the lane as laid out, never a detour;
  the lanes are never closer than the clearance. The part on the lane: the track is
  not drawn, and the finding says it would run through the part.
- Handoff: a wall of another net's track along the row walls in the pins it passes
  and not the pins past its ends; a stub that ends against a wall is walled in from
  where it ends; a stub with room is not; a stub with a lane beside it a stagger
  short of the clearance, a part and a track along the row (the session's case) is;
  a no-connect net is not; a net with two pads is judged as before.
- The search: a scored scan whose `accept` refuses the coarse lattice's spots near the
  best lands within a fine step of the best.

The real module (an MCU's cell with its cached generation, `fixtures/fairing/mcu_fan`):
run end to end with the turned escape over the two pins, KiCad's DRC on the board it
writes (clearance, shorting, unconnected), the lanes compared with the hand layout's
(risers, x - y of the 45s, the clearance over the bypass's pad), and the searched
inductor's spot and link.
