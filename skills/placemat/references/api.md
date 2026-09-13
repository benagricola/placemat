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
| bridge | a via, a short track on the opposite face passing under one or more tracks, and a via back: how a track gets past copper on its own layer without touching it |
| finger | a rectangular pour of a width along a centreline (a wide reach from a big pour to a pad), cut and bridged where a track crosses it |

A bus down a board is written as it looks: one vertical (or horizontal)
track per net between the first and last pad it serves, `(x, Y(pad))` to
`(x, Y(other_pad))`, and one short track per pad from the pad to that line,
`[pad, (x, Y(pad))]`. No object stands for the bus.

**Who bridges.** Where two tracks of different nets cross on one layer, the
lower `priority` passes under; at equal priority the shorter one does; a
`FIXED` track never does. Only a track declared `bridge=True` may pass
under; a crossing where the track that should yield may not is a finding,
and both tracks are drawn as declared. The order of the declarations never
enters into it. Fingers always yield to tracks.

Not in this API (they were verbs in the previous library): route45 and
l45 (45-degree legs: give `track` the corner points), spine and plane_serve
(joining plane drops with planned runs), band_with_notches, reserve,
drop_via and stitch (via-in-pad drops), and the lane vocabulary (tap, hop,
chain, crossing). They return only when a board needs them. A script that
needs a word of its own (a "corridor", a "spine") defines it where it first
uses it, in these terms.

## Copper (planned after placement, against the placed pads)

Points: `Location`, `PadRef(Part, int|net)`, `CellPadRef(Cell, net=|number=, ref_prefix=)`,
or `(x, y)` where either may be `X(ref, dx)` / `Y(ref, dy)`. `.offset(dx, dy)` on a ref.

```python
board.track(net, [p1, p2, ...], layer=CopperLayer.F, width=None, priority=Priority.DEFAULT, bridge=False)
board.via(net, point)
board.pour(net, [p1, p2, p3, ...], layer=..., swallow_pads=False)     # filled polygon
board.plane(net, layers=(CopperLayer.IN1,), outline=None, inset=0.4)  # zone(s), whole board or outline
board.finger(net, layer=, from_=point, to=point, width=)               # pour along a centreline, cut and bridged at tracks
```
All take `priority=`. `Priority.FIXED` copper is planned before the loose
parts and becomes an obstacle to them, and may not reference a searched
part. `HIGH`, `DEFAULT` and `LOW` only decide who bridges at a crossing.

## Layers and faces

`CopperLayer.F / IN1 / IN2 / B`, `Face.FRONT / BACK`, `Edge.NORTH / SOUTH / EAST / WEST`.

## Commands

```
placemat run <script> [--label L] [--fresh] [--no-render] [--no-drc] [-v] [--json] [--route [--route-full] [--route-exclude NET ...]]
placemat route <layout.kicad_pcb | script> [--exclude NET ...] [--layers L ...] [--full] [--iterations N] [--out DIR] [--json]
placemat impact <run-dir-or-json> <run-dir-or-json>
placemat drc <layout.kicad_pcb> [--json]
placemat measure <layout.kicad_pcb> [cell-or-part ...] [--rotation 90]
```
A run leaves `.placemat/runs/<label>/` beside the board: `run.json`,
`script.log`, `drc.json`, `generate.log`, `impact.txt`, the written
`layout.kicad_pcb`, and `route/` (the routed copy, `route.json`,
`router.log`, DRC before and after) when routing ran. The generation is
cached in `.placemat/generated/`; `--fresh` regenerates. Routing needs
KiCadRoutingTools at `$KRT_DIR` (default `~/work/KiCadRoutingTools`) with
its own venv; quick mode is one routing round, `--full` adds the router's
reconciliation rounds.
