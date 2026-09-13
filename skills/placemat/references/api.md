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
| `board.pad(Part("j1"), 3)` / `board.pad(Part("j1"), "GND")` | a pad by number (int) or net (str): `.box` (size, centre), `.through`, `.drill_mm`, `.layers` |
| `board.pitch(Part("j1"))` | the part's pad spacing, read from its pads: a connector's pin pitch |
| `board.cell_pad(Cell("bd0"), net="CANH", ref_prefix="H")` | one pad inside a cell |
| `board.net(Net("V48"))` | the net name, or `KeyError` |
| `board.netclass(Net("CAN_P"))` | its class: `.track_width`, `.clearance`, `.diff_pair_width`, `.diff_pair_gap` |

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
`item` is a `Part` (schematic instance), a `Cell` (module group) or a block
(below). One declaration per item. `why=` is recorded in the run. A FIXED
placement that collides is reported as a finding, not moved.

**Rows.** Things down one edge, in order, equally gapped, each flush to the
edge with its outward side out (a cell generated with its connector's bulk
on local +Y turns 270 on the west edge, 90 east, 180 north, 0 south;
`rotation=` overrides that, one value or one per item; `line="centre"`
aligns items of different depths on their centres instead of the edge):

```python
power = board.row(PD, Edge.WEST, gap=3.0, start=TOP)              # starts TOP along the edge
trunk = board.row([CN, U13], Edge.NORTH, gap=2.5, align="center")  # centred, once the size is known
board.row(parts, Edge.NORTH, gap=1.5, clearance=12.0, rotation=180, line="centre", start=trunk.centre(U13) - 4)
board.size(width=EDGE + power.depth + 4 + bus.depth + EDGE, height=max(power.end, bus.end) + TOP)
```
Where a row sits along its edge, one of: `start=` a number; `align="center"`
on the board; `centre=` or `end=` a reference (`X(Mid(pin_n, pin_p))`,
`X(pad, -2.0)`); `before=` or `after=` another row, one gap away. A row's
`depth` (how far inboard it reaches) and `length` are numbers at
declaration; `start`, `end` and `centre(item)` too when it starts at a
number, otherwise refer to its items' pads. `row.inner` and `row.outer` are
its inboard boundary and its edge line, usable as a coordinate in copper
(`(power.inner + 1.0, y)`). Declare the size after the rows that set it.

**Positions said in terms of pads.** `at=` and `center=` take a Location
or a point of references, resolved when the item is placed:
`center=(X(Mid(rb_mid, ra_mid)), Y(rb_mid, 3.0))` puts a cap under the
midpoint of two pads. An item placed that way goes down after what it
refers to, which must be FIXED or EDGE.

**Modules.** A module's fragment runs the same way: `placemat run
modules/X/X_layout.py` finds the `Layout(name=, path=)` in the `.zen`
beside it, generates the fragment and applies the script. A fragment has
no outline, so its script declares no size and places by coordinate.

**How a searched item finds its place.** With `near=` it scans around the
hint. Without one it is SEEDED: the hint is the weighted centroid of the
pads already placed that it connects to (plane nets and free nets do not
count), and every legal candidate in the scan is scored by its links, the
lowest kept. If nothing it connects to is placed yet it takes a POCKET: the
biggest free rectangle its envelope fits on its face. The step note says
which happened.

**Order.** FIXED and EDGE items go down as declared. Searched items are
ordered by the placer, re-measured after each: cells, then blocks, then
loose parts; within a tier, an item needing more than a quarter of the
free board goes now, else the strongest link pull toward what is placed,
else the largest. The sentence that chose each is in its step.

## Links

```python
board.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), weight=LinkWeight.SHORT, limit_mm=2.0, why="bypass at its pin")
board.free_net(Net("ENDSTOP"))      # its off-board run dwarfs the board: pulls nothing, seeds nothing
```
`weight` is `LinkWeight.FREE` (0), `DEFAULT` (1), `PREFER` (2), `SHORT` (8)
or any integer; 0 means the connection's length does not matter. Every
connection not declared weighs DEFAULT. A `limit_mm` is a bound: the run
reports each link's achieved length, and one over its limit is a finding
quoting `why`.

## Blocks

```python
ldo = board.block(Part("ldo"), satellites=[(Part("cin"), "VIN"), (Part("cout"), "VOUT")], gap=0.5)
board.place(ldo, near=Location(30, 22))
```
A block is a part and the satellites that sit at its pins: each satellite's
pad on the named net lands on that pin's axis `gap` beyond it, body
outward. The block is laid out from the anchor's REAL pads at every
candidate, so its envelope is exact, and placed as one thing (after cells,
before loose parts). Its members appear as their own steps and placements.

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

**Corners.** Every track corner is cut back `chamfer` (default 1.0 mm) along
both legs, so a right angle is two 45s; `chamfer=0` keeps it sharp. A tap
that must return is written as one chain: `..., (band, Y(pin)), pin,
(X(pin, -2), Y(pin, 2)), (band, Y(pin, 2)), ...`.

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

**Pairs.** Two nets drawn together at a gap along one centreline, the way
KiCad's differential tool does:

```python
board.pair(CAN_P, CAN_N, [(padP, padN), (x, y), (x, y2), (padP2, padN2)], layer=B)
```
The path starts and ends with a (P pad, N pad) tuple; the points between
are the centreline. Width and gap come from the P net's class
(`diff_pair_width`, `diff_pair_gap`; else the track width and clearance) or
`width=`/`gap=`. Corners are chamfered at 45 (`chamfer=`), each track leaves
its pad at 45 then straight to the nearest point of its line, and a lead
that would touch the partner on the pair's layer, or whose pad has no copper
there, goes over the other face from a via stepped `via_step` clear of the
partner. Pads side by side across the run fan straight in; a pad in line
with the run gets a lead along its line. The pair is one step,
`pair P/N`, and bridges as one.

## Layers and faces

`CopperLayer.F / IN1 / IN2 / B`, `Face.FRONT / BACK`, `Edge.NORTH / SOUTH / EAST / WEST`.

## Commands

```
placemat run <script> [--label L] [--fresh] [--no-render] [--no-drc] [-v] [--json] [--route [--route-full] [--route-exclude NET ...]]
placemat route <layout.kicad_pcb | script> [--exclude NET ...] [--layers L ...] [--full] [--iterations N] [--out DIR] [--json]
placemat impact <run-dir-or-json> <run-dir-or-json>
placemat drc <layout.kicad_pcb> [--json]
placemat measure <layout.kicad_pcb> [cell-or-part ...]
```
KiCad's own stderr (assertion notes, image-handler debug lines) is kept
out of the terminal; every line of it is in `kicad-stderr.log` in the run
directory, and `PLACEMAT_SHOW_KICAD=1` prints it all. Anything KiCad says
that is not one of the known noise patterns is printed regardless.

A run leaves `.placemat/runs/<id>/` beside the board (`<id>` is the hash of
the script, the generated board and the tool; `--label` adds a symlink
alias): `run.json`,
`script.log`, `drc.json`, `generate.log`, `impact.txt`, the written
`layout.kicad_pcb`, and `route/` (the routed copy, `route.json`,
`router.log`, DRC before and after) when routing ran. The generation is
cached in `.placemat/generated/`; `--fresh` regenerates. Routing needs
KiCadRoutingTools at `$KRT_DIR` (default `~/work/KiCadRoutingTools`) with
its own venv; quick mode is one routing round with the router's post-route
smoothing off (a measurement: the Breakout routes in about 10 s), `--full`
is the router's whole run. The search budget per net is the router's own
unless `--iterations` caps it.
