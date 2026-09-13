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

## Copper (planned after placement, against the placed pads)

Points: `Location`, `PadRef(Part, int|net)`, `CellPadRef(Cell, net=|number=, ref_prefix=)`,
or `(x, y)` where either may be `X(ref, dx)` / `Y(ref, dy)`. `.offset(dx, dy)` on a ref.

```python
board.track(net, [p1, p2, ...], layer=CopperLayer.F, width=None)     # polyline; width defaults to the net class
board.via(net, point)
board.pour(net, [p1, p2, p3, ...], layer=..., swallow_pads=False)     # filled polygon
board.plane(net, layers=(CopperLayer.IN1,), outline=None, inset=0.4)  # zone(s), whole board or outline
board.finger(net, layer=, y_lo=, y_hi=, x_from=, x_to=)               # pour notched round same-layer lanes, bridged
lane = board.lane(net, x=, layer=, width=None)
lane.run(y1, y2); lane.tap(pad); lane.hop(pad_a, pad_b); lane.chain([pads]); lane.run_to(y_or_pad, pad, tap=True)
lane.cross_to(other_lane, y=, from_y=pad_or_y, to_y=pad_or_y)
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
