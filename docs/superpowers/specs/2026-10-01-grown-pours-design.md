# A pour grown from its pads up to the copper round it

Status: draft, for approval.

Source: a board's session (2026-10-01), relaying Ben's preferred approach
from moving dense module scripts to intent only.

## Problem

Hand layouts of power stages draw their pours as polygons bounded by the
copper and parts round them, and scripts carry those polygons as
arithmetic:

- A USB-PD controller's PP5V: "a column over pins 28-29, its west edge a
  clearance off GPIO7's pin, widening north of GPIO7's lane and west to a
  clearance off GPIO7's via, into the capacitor's pad".
- Its VBUS: "a column over pins 26-27, opening east north of CC2's
  capacitor", holding a field of six vias.
- A boost converter's PGND/VOUT neck and block, and the same kind of
  shape in two more supply cells.

`board.pour(net, pads, swallow_pads=True)` covers the hull (or box) of the
pads and pulls back from other nets when written, but it cannot reach past
the hull into the room round it. `board.plane(net, layers, outline= |
over=)` is a KiCad zone that fills everything inside its outline, pulled
back from foreign copper, but its extent is a polygon or the box round
whole parts, and it keeps every piece the fill leaves.

## Design

```python
pp5v = board.pour(Net("PP5V"), [PadRef(Part("pd"), 28), PadRef(Part("pd"), 29),
                                PadRef(Part("c_pp5v"), "PP5V")],
                  layer=CopperLayer.F, grow=1.2, why="...")
board.stitch(Net("PP5V"), pp5v)
```

`board.pour(net, pads, layer=, grow=mm, within=None)`: a pour that starts
as its pads' copper and grows outward until it meets other nets' copper or
holes at the clearance, no further than `grow` mm from those pads, and
inside `within=` when given (a keepout's name, a `Cell`, or `Part`s: the
region `plane(over=)` takes). `grow=` is required: a pour that may reach
anywhere is a plane.

It is written as a KiCad zone, filled by KiCad, as a plane is:

- Its outline is the pads' hull grown by `grow`, clipped to `within=`.
- KiCad's fill pulls it back from every other net's pads, tracks, vias,
  holes and pours by the clearance (with the script's clearance rules,
  which KiCad applies), and from the board edge.
- Pieces of fill joined to no pad of its net are removed (KiCad's own
  island removal). A piece joined only to a pad of the net the pour does
  not name is kept, as KiCad keeps it.
- Its pads connect solid; its minimum width is
  `copper.plane_min_thickness`.
- Its priority is above every plane on its layer, so a plane of another
  net on that layer pulls back from it rather than it from the plane.

It stops at escape lanes (the escape-lanes spec) and at a part's other-net
pads, because those are copper by the time it fills.

### Order and planning

A grown pour is planned after every other copper of its batch, so the
tracks, vias and pours it grows up to are known. Until it is filled, what
the plan holds for it is its pads' hull: the copper it covers whatever the
fill does. Copper planned after it is judged against that.

`board.stitch(net, pour)` on a grown pour places its vias inside the
outline, clear of other nets' copper, as now; after the fill, a stitching
via outside the fill is a finding.

The checks read the filled board, so `current-path` measures a grown pour
along the load's route as it measures any zone fill.

### Refused

At declaration: `grow=` of 0 or less, `grow=` with `swallow_pads=`,
`cover=` or `width=` (the zone's own fill decides its extent), fewer than
one pad, and a point in `pads` that is not a pad (a grown pour starts from
copper). At write: a grown pour whose fill joins none of its pads is a
finding naming it.

## Verification

- Two pads of one net with a track of another net between them and
  `grow=` past it: the fill covers both pads and stops a clearance off
  the track; nothing of it lies past `grow`.
- `within=` a keepout: the fill stays inside it.
- A piece of fill cut off by another net's copper, joined to no pad of the
  net, is removed.
- A plane of another net on the same layer pulls back from the grown pour.
- A clearance rule between the pour's net and another (`board.rule`):
  the fill keeps the rule's clearance.
- A model of the PD controller's PP5V: the three pads, GPIO7's lane and
  via as copper (or as an escape once that exists), and `grow=`: the fill
  joins the pins and the capacitor, stays a clearance off GPIO7's copper,
  and `current-path` judges it.
- Stitching: vias inside the fill; one placed where the fill does not
  reach is a finding.
- KiCad's DRC on the written board: no clearance violation from the pour.
- Digest parity: a script without `grow=` digests as before.
