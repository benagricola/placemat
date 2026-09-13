# The script surface

```python
from placemat import board, Net, Part, Cell, PadRef, CellPadRef, X, Y, Location, Edge, Face, CopperLayer, Priority
```

`board` is the board being laid out. Questions answer from the generated
board; declarations are collected and resolved together.

## Questions (answered from the generated board, before anything moves)

| call | answer |
|---|---|
| `board.extent(item, rotation=0, face=Face.FRONT)` | body box of a `Part`/`Cell` at that rotation, placed at the origin: a size |
| `board.part(Part("j1"))` | the footprint: `.ref`, `.inst`, `.pads`, `.body_box`, `.courtyard_box` |
| `board.cell(Cell("mcu"))` | the cell: `.members`, `.box`, `.member("conn")` |
| `board.pad(Part("j1"), 3)` / `board.pad(Part("j1"), "GND")` | a pad by number (int) or net (str) |
| `board.cell_pad(Cell("bd0"), net="CANH", ref_prefix="H")` | one pad inside a cell |
| `board.net(Net("V48"))` | the net name, or `KeyError` |

## Setup

`board.size(width, height, chamfer=0.0, radius=0.0)` - the outline, origin
top-left, y down.

## Placement

```python
board.place(item, at=Location(x, y), rotation=0, face=Face.FRONT)      # FIXED: origin (cell: box centre)
board.place(item, center=Location(x, y), rotation=0)                    # FIXED: body box centre
board.place(item, edge=Edge.NORTH, along=x, clearance=3.0, rotation=180)  # EDGE: flush to an edge
board.place(item, near=Location(x, y), radius=3.0, step=0.2, rotations=(0, 90))  # searched
board.place(item)                                                       # searched from where it is
```
`item` is a `Part` (schematic instance) or a `Cell` (module group). One
declaration per item. `why=` is recorded in the run. A FIXED placement that
collides is reported as a finding, not moved.

## Copper vocabulary

Every copper call is named for the shape it leaves on the board:

| word | the shape on the board |
|---|---|
| track | one straight trace segment of a width, on one layer; `board.track` draws several end to end |
| via | a plated hole joining all copper layers at one point |
| pour | a filled polygon of exactly the shape given, on one layer; it never pulls back from other copper, so it is drawn where nothing foreign is |
| zone | a filled area KiCad fills and refills, pulling back by the clearance round every foreign pad, track and via; what a plane is made of |
| plane | a zone covering the whole board (or an outline) on one or more layers, for a net that everything reaches by a via |
| bridge | a via, a short track on the opposite face passing under one or more tracks, and a via back: how a track gets past copper on its own layer without touching it. The lane planner and the finger make them; nothing else does yet |
| finger | a rectangular pour of a width along a centreline (a wide reach from a big pour to a pad), cut and bridged where a lane crosses it |
| lane | a straight line on one layer, in any direction, that one net's tracks run along: a bus bar drawn as tracks. Vertical (`x=`), horizontal (`y=`) or through a point at an angle. Positions along a lane are distances from its point; for `x=`/`y=` lanes those are plain y/x values |

The lane words, which only mean something on a lane:

| lane word | the shape on the board |
|---|---|
| run | a track along the lane between two positions |
| tap | a track from the lane to a pad, perpendicular to the lane, bridged under any same-layer lane between |
| hop | tap out of a pad, run along the lane, tap into the next pad |
| chain | tap, run, tap, run ... over many pads, each tapped once |
| crossing | a track from a position on this lane to the nearest point of another lane (for parallel lanes, perpendicular to both), bridged under any same-layer lane it passes |

Not in this API (they were verbs in the previous library): route45 and
l45 (45-degree legs: give `track` the corner points), spine and plane_serve
(joining plane drops with planned runs), band_with_notches, reserve,
drop_via and stitch (via-in-pad drops). They return only when a board
needs them. A script that needs a word of its own (a "corridor", a
"column") defines it where it first uses it, in these terms.

## Copper (planned after placement, against the placed pads)

Points: `Location`, `PadRef(Part, int|net)`, `CellPadRef(Cell, net=|number=, ref_prefix=)`,
or `(x, y)` where either may be `X(ref, dx)` / `Y(ref, dy)`. `.offset(dx, dy)` on a ref.

```python
board.track(net, [p1, p2, ...], layer=CopperLayer.F, width=None)     # polyline; width defaults to the net class
board.via(net, point)
board.pour(net, [p1, p2, p3, ...], layer=..., swallow_pads=False)     # filled polygon
board.plane(net, layers=(CopperLayer.IN1,), outline=None, inset=0.4)  # zone(s), whole board or outline
board.finger(net, layer=, from_=point, to=point, width=)               # pour along a centreline, cut and bridged at lanes
lane = board.lane(net, layer=, x=)  |  board.lane(net, layer=, y=)  |  board.lane(net, layer=, through=Location, angle=)
lane.run(a, b); lane.tap(pad); lane.hop(pad_a, pad_b); lane.chain([pads]); lane.run_to(a, pad, tap=True)
lane.cross_to(other_lane, at=, from_=, to=)        # positions: a distance along the lane, or a point/pad projected onto it
```
All take `priority=Priority.FIXED` to be planned before loose parts (and
become an obstacle to them); FIXED copper may not reference a searched part.
Same-layer lanes a tap or crossing passes are bridged on the far layer
automatically, from the lanes registered on the board.

## Layers and faces

`CopperLayer.F / IN1 / IN2 / B`, `Face.FRONT / BACK`, `Edge.NORTH / SOUTH / EAST / WEST`.

## Commands

```
placemat run <script> [--label L] [--fresh] [--no-render] [--no-drc] [-v] [--json]
placemat impact <run-dir-or-json> <run-dir-or-json>
placemat drc <layout.kicad_pcb> [--json]
placemat measure <layout.kicad_pcb> [cell-or-part ...] [--rotation 90]
```
A run leaves `.placemat/runs/<label>/` beside the board: `run.json`,
`script.log`, `drc.json`, `generate.log`, `impact.txt`, the written
`layout.kicad_pcb`. The generation is cached in `.placemat/generated/`;
`--fresh` regenerates.
