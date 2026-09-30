# A track point on a pad's edge

Status: draft, for approval.

Source: a board's session (2026-09-30), a shunt's Kelvin sense taps.

## Problem

A Kelvin sense track must meet its pad at one chosen place: the inner edge
of a current shunt's pad, where the voltage is the resistor's alone, away
from the copper the load current flows through. No track waypoint says that.

- `PadRef(part, pad)` is the pad's centre, on the load path.
- `Past([pad], edge)` is a clearance plus half a track off the pad, even
  when the pad is the track's own net: the track misses the pad (left
  unconnected), or turns back and runs over it, which moves where it
  meets the pad to the pad's outer end.

A script reaches the edge today only with coordinates from `placed_size()`,
which the skill keeps for declarations the user approves one by one.

## Design

`PadRef(part, pad, edge=Edge.SOUTH, along=Along.END)` is a point on that
edge of the pad, touching it.

- `edge` is a side of the pad's copper box in the board frame, as `Past`'s
  edge is.
- `along` sets where on that edge, as a label's `align` does: along a north
  or south edge `START` is the west end, along an east or west edge the
  north end. Default `MID`.
- As a track waypoint the point is half the track's width outside the edge,
  so the track's copper lies against the edge. At `START` or `END` it is
  also half a track in from the corner, so the copper ends flush with the
  pad's side.
- `Past(..., across=PadRef(..., edge=...))` lies on that point's line, not
  the pad's centre line, so a lane can pick up the tap without a jog.

For the shunt in the source (VSHUNT pad north of VPROT, the gap between
them; R5 to the north-east):

```python
tap = PadRef(Part("r_shunt"), "VSHUNT", edge=Edge.SOUTH, along=Along.END)
board.track(Net("VSHUNT"), [tap,
                            Past([PadRef(Part("r_shunt"), "VSHUNT")], Edge.EAST, across=tap),
                            PadRef(Part("r5"), "VSHUNT")])
```

The tap leaves the inner edge at its east end, runs east a clearance off
the pad's side, and turns north to R5. With `along=Along.MID` the tap runs
along the inner edge, in the gap, before leaving it; both forms meet the pad
only at its inner edge.

**Refused**, at resolve with the pad named:
- `edge=` on a pad not at a right angle to the board (its box's edge is not
  copper);
- `along=START` or `END` on a round or oval pad (the box's corner is not
  copper);
- `edge=` anywhere but a track waypoint or a `Past`'s `across=` (a via's
  `at=`, a placement's anchor).

`edge` and `along` are left out of a declaration's digest when unset, so a
lock accepted before them still holds. `along` without `edge` is refused.

## Verification

- A track from `PadRef(..., edge=Edge.SOUTH)` touches the pad along its
  south edge, and not elsewhere: its copper and the pad's overlap only in a
  strip at that edge.
- At `along=Along.END` the track's copper ends flush with the pad's east
  side.
- A part turned 90 and one on the back: the edge is the board-frame one.
- `Past(..., across=tap)` lies on the tap's line: the leg between them is
  straight.
- The shunt case: both taps in the 0.76 mm gap, the written board passes
  KiCad's DRC and the taps are connected.
- Each refusal above.
- Digest parity: a script without `edge=` digests as before.
