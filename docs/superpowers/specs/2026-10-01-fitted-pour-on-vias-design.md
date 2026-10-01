# A fitted pour that joins vias

Status: approved (2026-10-01).

Source: a board's session (2026-10-01), migrating to fitted pours (0.67.0).

## Problem

A fitted pour (`board.pour(net, pads, layer=, swallow_pads=True)`) is given
by the pads it joins. On an inner layer the copper to join is vias: a
converter's output area on In2 joining the vias dropped from its front-face
output pads, a regulator's input strap on In2 between two via drops. The
pads are front copper only, so the pour is refused ("pad has no copper on
In2.Cu"). The session moved both to `board.plane(net, layers=(In2,),
over=[parts])`, a KiCad zone: it fills the whole box round those parts and
lets copper planned later be drawn across it, which the fitted pour exists
to prevent.

## Design

A fitted pour's members may be vias as well as pads: what `board.via()` and
`board.vias()` return, and an escape lane's `.via`. A via counts on the
pour's layer when its span includes that layer, as its copper ring there
(the via's size).

```python
drops = board.vias(Net("VOUT"), along=PadRef(Part("c_out"), "VOUT"), count=3)
board.pour(Net("VOUT"), [drops, PadRef(Part("q1"), "VOUT")], layer=CopperLayer.IN2, swallow_pads=True,
           why="the output area on In2, joining the drops")
```

- Members are pads with copper on the layer and vias spanning it; a
  `board.vias()` result counts as all its vias. A pad without copper on the
  layer is refused as today; a via that does not span the layer is refused,
  naming it.
- The fit is unchanged: the outline holds every member's copper on the layer
  and keeps every other net's clearance outline out of it.
- The pour waits for its vias to be planned (a via found by `FreeSpot` or
  placed with its part), as `Past` does.
- A pour with only vias as members (no pads) is allowed.
- `swallow_pads=` keeps its name: it says the pour is fitted round its
  members.

## Verification

- Three vias of one net on In2, another net's track running between two of
  them: the fitted outline holds the three rings and keeps the track's
  clearance.
- A pour joining a pad on F.Cu and a via: on F.Cu, both; on In2, the pad is
  refused naming it.
- A via whose span is F.Cu to In1 named in a pour on In2: refused.
- A `board.vias(..., count=3)` result as one member: all three held.
- The pour waits for a `FreeSpot` via: placed after it.
- KiCad's DRC on the written board: no clearance violation from the pour.
- Digest parity: a script without via members digests as before.
