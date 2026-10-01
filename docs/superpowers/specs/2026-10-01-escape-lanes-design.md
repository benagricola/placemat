# Escape lanes: a pin row's routes out, reserved when the part is placed

Status: approved (2026-10-01).

Source: a board's session (2026-10-01), relaying Ben's preferred approach
from moving dense module scripts to intent only. Supersedes part 2
(`PadRef(..., escape=True)`) of
`2026-10-01-track-rules-and-pin-escape-design.md`; part 1 of that spec
(the router keeps clearance rules) stands.

## Problem

placemat places parts, then plans copper. Hand layouts of dense parts do
it the other way round at the pins: the pins' routes out are fixed first,
and parts stand on them or clear of them. Scripts say that today with
arithmetic:

- A QFN's north row (a USB-PD controller): three pins step north, then
  west, one lane each, lowest first. `LANE_32 = TIP_N - LANE`,
  `LANE_31 = LANE_32 - (track/2 + clearance + via/2)`,
  `LANE_30 = LANE_31 - (via/2 + clearance + track/2)`; two lanes end in
  vias; a capacitor stands with its pad on one lane, west of another
  lane's via; a second capacitor's pad a clearance north of a via.
- The same controller: a capacitor lying "on CC2's lane", the trace
  through its pad; pour edges a clearance off lanes and vias.
- A converter's south pins: vias in two rows a clearance under the pin
  ends, alternate pins in the near and far rows.
- The converter's settings: six pins rising to one line a clearance over
  the row, then 45s out to their parts.
- An MCU's straps: out from the pin, a 45 across, into the pull-up, the
  pull-up placed at the 45's end.
- A crystal pin whose only way out was taken by a part linked to the next
  pin: nothing kept that pin's exit clear when the part was placed.
- A sense pair back into two adjacent pins along a lane between the pin
  tips and an output capacitor.

`board.fanout(part, depth=)` reserves a band at a part's pad rows, but it
is anonymous: one rectangle a side, no pins, no lanes, no vias, nothing
that later declarations can name. It keeps out the bodies of unrelated
parts and lets in the part's block satellites and parts linked to it at
`LinkWeight.SHORT`, so a linked part may stand on a pin's exit.

## Design

```python
esc = board.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30],
                   widths={32: LDO_TRACK}, why="VIN_3V3, GPIO6 and GPIO7 out of the north row")
```

`board.escape(part, pins, *, turn=None, vias=(), depth=None, run=None,
widths=None, pairs=(), why)` declares each pin's route out of its row: a
straight along the row's outward axis (the riser), then, with `turn=`, a
lane parallel to the row, and optionally a via. Pins are named as a
`PadRef` names them on that part (number, net, or `PinName`).

### Geometry

All of an escape's pins are on one row of one part: the same outward axis
as `_escape_axis` reads it (a fanout's, a block satellite's). A pin on
another row is refused, naming it. The row's **tips** are the outermost
reach of its pads along the axis. **Clearance** is the clearance by net
pair between neighbouring copper, as the router judges it.

Each lane's **copper** is its via's size where it has a via, else its
track width (`widths=` for that pin, else the net's track width): a via
may stand anywhere along it, so the lanes either side keep clear of it
whole. A **step** between two neighbours is half of each one's copper
plus the clearance. These are the hand layout's own figures: its
`LANE = TRACK + CLEAR` and its lane-to-via steps.

**With `turn=`** (an `Edge` across the row: a north row turns `WEST` or
`EAST`):

- The pin nearest the turn side takes the innermost lane, the next pin
  the next lane, and so on, so no riser crosses a lane. There is no
  `order=`: any other order crosses.
- The innermost lane's centreline is its own copper plus the clearance
  past the tips (`depth=` overrides it); each next lane one step further
  out.
- Each riser runs from its pad's centre straight out to its lane, then
  turns; the corner is chamfered as the track's own chamfer.
- A lane with a via ends at it. The vias are placed innermost lane first,
  each at the first spot along its lane past the row's turn-side end
  that keeps the clearance from the part's pads, every riser and lane,
  and the vias already placed. A lane without a via ends level with the
  outermost via, or one step past the row's turn-side end where the
  escape has none; `run=` (mm past the row's turn-side end) sets every
  lane's end instead.
- `turn=` a `Corner` (a north row: `NW` or `NE`) runs the lanes at 45,
  stepped across their own direction; otherwise the same. `run=` is then
  each 45's length.

**Without `turn=`**: each riser runs out to `depth=` past the tips
(default: its copper plus the clearance), and a pin in `vias=` ends in a
via at the first spot out along its own axis that keeps the clearance
from the row's pads and the vias already placed, taken in the order
`pins` lists them. Alternate pins of a fine-pitch row fall into a near
and a far row, as the converter's south pins do by hand.

**`pairs=[(a, b)]`**: two pins whose lanes run together, a pair's gap
apart (the net class's pair gap, else the clearance) instead of a step.
Their lanes must be neighbours in the order above, else the pair is
refused.

### Reserved at placement

An escape is settled as soon as its part is placed, as a fanout is. Its
risers, lanes and vias then stand in the occupancy as copper of their
own nets:

- A part placed later may stand over a lane with its body (copper under a
  body is normal), and with a pad of the lane's own net on it (a
  capacitor whose pad the lane runs through), but not with a pad, hole
  or other copper of another net within the clearance. A part linked to
  the escaped part at `SHORT`, which a fanout admits, is judged the same.
- Vias placed later (`FreeSpot`, stitching, give-way) keep the clearance
  from it; an escape's own vias do not give way.
- Copper planned later of another net is judged against it as against a
  drawn track.

A searched part's lanes are weighed in its search. At each candidate the
escape is laid out as above, and the candidate is priced
`score.escape_lane` (a setting, default 400, as `score.escape_walled`: a
declared route out that cannot be laid is a pin walled off from its own
route) for each lane that would meet another net's pad, hole or copper
already placed, or whose via finds no legal spot. The price joins the
candidate's other escape terms (`escapes.py`), so the search prefers a
spot where every lane lies clear; where none does, the part still lands
and each blocked lane is a finding naming what blocks it. The escape is
settled where the part lands.

### Handles

`esc[pin]` is that pin's lane (a `Lane`), named as the pin was:

- **A track point.** `board.track(net, [esc[31]])` draws the pin's riser
  and lane to its via; `[esc[32], PadRef(Part("c_pd"), "V3V3")]` draws
  them and goes on to the pad. As a track's first point the lane expands
  to its own points; anywhere else it is refused.
- **Its via.** `esc[31].via` is a via handle, as `board.via()` returns:
  a track point and a `Past` item. It is also a placement reference:
  `Beside(esc[31].via, Edge.WEST)` stands a part the gap off it.
- **A line to stand on.** `Beside(Part("c_pd"), Edge.WEST,
  align=(own_pad, esc[32]))` sets the part's pad centred across the
  lane's line (the lane's for a turned lane, the riser's without a
  turn). `esc[32].end` is the lane's end as a point reference, which
  `X()`/`Y()` take: `Pin("V3V3", X(esc[32].end), Y(esc[32].end))` sets the
  pad's centre there.
- **The whole escape.** `Beside(esc, Edge.NORTH)` stands an item beside
  its risers, lanes and vias.

A placement that refers to a lane waits for its part, as one that refers
to a pad does.

A lane reserved but never drawn (no track begins with it) is a finding at
the end of the run: its room was kept for nothing.

### The cases above, by intent

```python
esc = board.escape(Part("pd"), ["V3V3", "EXCITE", "USB_WET"], turn=Edge.WEST,
                   vias=["EXCITE", "USB_WET"], widths={"V3V3": LDO_TRACK}, why="...")
board.place(Part("c_pd"), at=Beside(esc["EXCITE"].via, Edge.WEST, align=("V3V3", esc["V3V3"])),
            rotation=..., why="VIN_3V3's 10 uF at the end of its lane, west of GPIO6's via")
board.track(Net("V3V3"), [esc["V3V3"], PadRef(Part("c_pd"), "V3V3")], layer=CopperLayer.F)
board.track(Net("EXCITE"), [esc["EXCITE"]], layer=CopperLayer.F)
board.track(Net("USB_WET"), [esc["USB_WET"]], layer=CopperLayer.F)

south = board.escape(Part("ctl"), [2, 3, 4, 5, 6, 7], vias=[2, 3, 4, 5, 6, 7], why="...")   # near and far rows
xtal = board.escape(Part("mcu"), ["XTAL_N"], why="pin 53's exit kept clear")             # L3 stands off it
```

### Relation to fanout

Both stay. A fanout keeps unrelated parts' bodies off a part's pad rows;
an escape keeps the named pins' routes clear of other nets' copper,
including that of the parts the fanout lets in. A script may declare
both.

## Refused

At declaration: pins of another part or another row; a pin named twice;
`turn=` along the row's axis; `vias=` or `widths=` naming a pin the escape
does not; a pair whose lanes are not neighbours; `run=` or `depth=` of 0
or less; an escape's lane as any track point but the first. At resolve: a
via with no legal spot along its lane or axis, naming what stands in the
way.

## Verification

- A model of the PD controller's north row (0.5 mm pitch, the hand
  layout's track, via and clearance): the three lanes at exactly the
  hand layout's `LANE_32`, `LANE_31`, `LANE_30`; the vias at the first
  legal spot along their lanes, each clear of the others and the pads;
  the hand layout's own via positions compared and any difference
  reported in the plan.
- The derived order: a north row turning west gives the westmost pin the
  innermost lane; turning east, the eastmost.
- Without a turn: six pins at 0.5 pitch with vias fall into a near and a
  far row, alternate pins, as the converter's hand layout has them.
- A 45 lane (`turn=Corner.SW` on a south row): the lane at 45, the next
  one a step across it.
- A pair: the two lanes a pair gap apart.
- Reservation: a part linked `SHORT` to the escaped part, its
  other-net pad on a reserved riser, is placed clear of it; the same part
  with a pad of the lane's own net on the lane is let stand; a body over
  a lane is let stand; a `FreeSpot` via of another net keeps off a lane.
- Handles: a part `Beside` a lane's via; a pad aligned on a lane; a pad
  at a lane's end; a track from a lane to a pad; `Past` with a lane's
  via.
- The search: a searched part with an escape, two candidate spots, a
  part already placed whose pad would sit on a lane at the nearer one:
  the part lands at the other; with every spot blocked, it lands and the
  blocked lane is a finding.
- Each refusal.
- A lane never drawn is a finding.
- The written board passes KiCad's DRC on the PD row model.
- Digest parity: a script without `board.escape` digests as before.
