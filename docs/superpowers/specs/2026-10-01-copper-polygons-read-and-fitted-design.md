# Graphic copper polygons: read back, and fitted round other nets

Status: draft, for approval.

Source: Ben, through a board's session (2026-10-01): a boost converter's
VOUT and SW2 copper drawn by hand as polygons, to be folded into the
module's script.

## Part 1: reading a board's graphic copper polygons

### Problem

`placemat measure <board> --copper NET` lists track segments and vias;
`placemat layer <board> F.Cu` draws zone fills, tracks, vias and pads.
Neither shows a graphic copper polygon (a `PCB_SHAPE` polygon on a copper
layer, such as a pour a script or a person drew). `read_board` already
reads them (kind `poly`, with their outlines; the current-path check
measures them), so only the two read commands leave them out. To see a
hand-drawn polygon and its clearances, the session read it with pcbnew and
measured each edge in a script of its own.

### Design

`measure --copper [NET ...]` lists each graphic copper polygon of those
nets after the tracks and vias: its net, layer, stroke width, whether it is
filled, and its outline's vertices; and for each edge, the nearest copper
of another net on its layer (pad, track, via, polygon, zone fill), the gap
from the polygon's copper (its outline grown by half its stroke) to it, the
clearance the pair needs, and `under` where the gap is less. JSON
(`--json`) carries the same as fields; the text form prints one line per
polygon and one per edge.

`layer <board> <layer>` draws graphic copper polygons, filled or outlined
as KiCad draws them, coloured by net as zone fills are, and counts them in
its summary line.

The clearance is the net class pair's, as the other read commands judge
it; a board's `.kicad_dru` rules are not read (the script's `board.rule`
clearances are a run's, not a board file's).

### Verification

- A board with a filled polygon and an unfilled one, each of a named net,
  beside another net's pad, track and via: `measure --copper` lists both
  with net, layer, stroke, filled and vertices, and each edge's nearest
  foreign copper and gap; an edge nearer than the clearance is marked
  `under`; the gaps agree with KiCad's DRC within a micron.
- `layer` draws both polygons and counts them.
- A board without graphic polygons: both commands print as before.

## Part 2: a copper polygon fitted round foreign clearances

### Problem

A swallowing pour (`board.pour(net, pads, swallow_pads=True)`) covers its
pads' hull (or box, or the polygon through their centres) and the writer
pulls it back from every other net's copper afterwards. Where other copper
stands inside the hull, the result is a hull with bites taken out of it:
one hull over a switch node's four pads covers the gap between a bootstrap
pin and the output bar; one over the output pads covers a sense pin and its
track. The shape Ben draws instead is one static polygon over the pads it
joins, every edge straight, every edge that passes other copper tangent to
that copper's clearance outline: a rubber band round its own pads, pushed
in by foreign clearances.

### Design

`board.pour(net, pads, layer=, swallow_pads=True)` over pads is **fitted**
(Ben: fitting replaces pull-back on pours):

- **Its pads**: the copper of every pad named (all their lands) is inside
  the outline.
- **What it keeps clear of**: every other net's copper on its layer that is
  planned before it (pads, tracks, vias, other pours, zone fills as the
  plan holds them), every hole, and the board edge, each grown by the
  clearance the pair needs (`board.rule` clearances included, as the router
  keeps them) plus half the pour's stroke: the item's **clearance outline**,
  round at a pad's corner and a track's end.
- **The outline**: the shortest closed outline that holds its pads and
  enters no clearance outline: the relative convex hull of its pads among
  the clearance outlines. Every edge is straight. Where the outline wraps
  round a clearance outline's arc, it does so by edges tangent to the arc
  meeting outside it, the arc divided finely enough that no corner stands
  more than `geometry.arc_sag` past the arc. So an edge that passes foreign
  copper keeps at least its clearance from it and at most the clearance
  plus `geometry.arc_sag`.
- **Drawn once, static**: written as the polygon it is, no pull-back when
  written. The writer's pull-back of swallowing pours is removed for a
  fitted pour.
- **An obstacle afterwards**: copper planned after it of another net keeps
  its clearance from it like any copper; where it cannot (a track declared
  across it), that is a copper finding, not a cut in the pour.
- **No way round**: where other copper stands where the outline cannot go
  round it (between two of its pads with no gap past it), the pour is not
  drawn, and a finding names the copper and the pads it stands between.
  The same where two of its pads cannot be joined at all (another net's
  clearance outline crosses every way between them).
- **Thin necks**: where the outline narrows, between its pads, to less
  than its net's track width, a finding names where; it is drawn.

A pour whose points are not all pads (a corner given as a point), and a
pour declared with `cover=` (`Cover.HULL`, `Cover.BOX`, `Cover.CENTRES`),
keeps today's shape and pull-back. A pour without `swallow_pads` is drawn
exactly as declared, as today.

### What changes for existing scripts

Every swallowing pour over pads alone changes shape: from a hull with other
nets' copper pulled out of it, to the fitted outline. Where no other copper
stands inside the hull, the fitted outline is the hull (to within
`geometry.arc_sag` at its rounded pad corners). A script that wants the old
shape names its `cover=` explicitly.

### Verification

- Three pads in a row with another net's pad standing between two of them
  inside their hull: the fitted outline holds all three pads, keeps the
  clearance from the other pad and no more than `arc_sag` beyond it, and
  every edge is straight.
- Four pads round another net's pin and track (a switch node round a
  bootstrap pin), as in the reference drawing: the outline's edges reach
  the pin and the track at the clearance (the reference drawing's are
  0.158 to 0.165 mm against 0.16).
- A track planned after the pour that would cross it: a copper finding;
  the pour is unchanged.
- Another net's via standing where the outline cannot go round it: the
  pour is not drawn, and the finding names the via and the pads.
- A `board.rule` clearance for the pair is kept.
- A swallowing pour with `cover=Cover.HULL`: today's shape and pull-back.
- KiCad's DRC on the written board: no clearance violation from a fitted
  pour.
- Bench: unchanged (the corpus places parts and declares no pours).
- On release, the boards whose scripts declare swallowing pours over pads
  (20 layout scripts in one project) are rerun on scratch copies and each
  changed pour reported: its findings before and after, and KiCad's DRC.
