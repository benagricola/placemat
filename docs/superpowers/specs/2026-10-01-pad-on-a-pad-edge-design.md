# A part's pad placed on another pad's edge, and net ties as copper

Status: approved (2026-10-01).

Source: a board's session (2026-10-01), placing net ties Ben approved at a
current shunt's Kelvin taps.

## Problem

A shunt (a 1206 standing upright, 0.76 mm between its pads) gets its sense
lines through net ties: a tie joins VSHUNT to VSHUNT_SENSE, another VPROT to
VPROT_SENSE (two 0.3 mm pads 0.5 mm apart, joined by a copper bar; front
copper only, no mask). Each tie belongs in the gap under the shunt's body,
lying east-west: its pad 1 against its own pad's inner edge, so the tie's
copper is the Kelvin junction, and its pad 2 out past the pad's east end,
where the sense track starts. Two 0.3 mm ties stack in the 0.76 mm gap with
0.16 mm between them. Outside the shunt they do not fit.

Two things stop a script saying it:

1. `PadRef(part, pad, edge=, along=)` (0.64) is a track point only; as a
   placement point (`Pin`, `X`, `Y`) it is refused. A `Beside` puts the tie
   outside the shunt's envelope, not on the pad's edge.
2. A net tie that draws no courtyard, silk or fab is claimed by its
   courtyard (falling back to the box round its pads and bar), and under
   `[place] envelope = "physical"` that claim is the part itself. Either way
   the shunt's body and pads keep it out. KiCad's DRC has no courtyard to
   judge for it: a net tie of that kind is copper only.

## Design

### A placed pad on a pad's edge

`PadRef(part, pad, edge=, along=)` is accepted where a placement takes a
point (`Pin(key, x, y)` through `X()`/`Y()`, and `Pin(key, point)`), with
the meaning a track point has (0.64), the track's width replaced by the
placed pad's own size across the edge:

- The placed pad lies against the edge, outside the target pad, its copper
  reaching 0.005 mm over the edge (`_EDGE_OVERLAP`, the tap's own) so
  KiCad joins the two. Its centre is half its own size across the edge
  outside it, less that overlap.
- `along=`: `MID` its centre on the edge's middle; `START`/`END` its side
  flush with the target pad's side, as a tap's is.
- The placed pad's size is taken as the part stands at the placement's
  rotation, so `rotation=Turned(...)` settles first.

```python
board.place(Part("nt_vshunt"), at=Pin(1, PadRef(Part("r_shunt"), "VSHUNT", edge=Edge.SOUTH,
                                                along=Along.END)),
            rotation=Turned(Part("r_shunt"), 90), why="the Kelvin junction at the shunt's inner edge")
```

`Pin(key, point)` with one point argument is new: today `Pin` takes `x` and
`y`, and `Pin(key, X(p), Y(p))` says the same thing longer. Both forms are
accepted.

A pad placed so is refused where its edge is refused for a track (an end of
a round pad's edge, a pad off the right angle), naming the pad.

### A net tie that draws nothing is copper

A footprint that is a net tie (KiCad's net-tie pad groups) and draws no
courtyard, silk or fab claims its pads and its copper only, under every
envelope:

- No courtyard and no body: another part's body and courtyard may stand
  over it, as over a track.
- Its pads and bar keep the copper clearance from other nets' copper, with
  KiCad's net-tie exclusion (0.65.2) where they meet the nets of its own
  pad groups; a pad of the same net may overlap them (the target pad).
- A net tie that draws a courtyard keeps today's behaviour.

## Verification

- A 0.3 mm two-pad net tie placed `Pin(1, PadRef(shunt, "VSHUNT",
  edge=SOUTH, along=END))`: its pad 1 lies against the shunt pad's south
  edge, overlapping it by 0.005 mm, its east side flush with the pad's;
  `along=MID` centres it.
- Turned 90 with the shunt: the pad's size across the edge is the turned one.
- Two ties, one on each inner edge of a 0.76 mm gap: both placed, 0.17 mm
  apart (0.76 less two 0.3 mm pads, each 0.005 mm over its edge), no
  finding at a 0.16 mm clearance.
- The shunt's body over the ties: no conflict; a third part's body over a
  tie: no conflict; a third part's other-net pad within the clearance of a
  tie's pad: a conflict.
- A net tie that draws a courtyard is still claimed by it.
- KiCad's DRC on the written shunt with its two ties: no clearance,
  courtyard or unconnected item.
- Refusals: an `END` on a round target pad.
- Digest parity: a script without these forms digests as before.
