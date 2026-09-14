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
| `board.keep_in` | the board's copper-to-edge rule: where an EDGE item's reach lands |
| `board.reach(item, rotation=)` | the item's body, pads and silk together, as a box at the origin |

## Setup

`board.size(width, height, chamfer=0.0, radius=0.0)` - the outline, origin
top-left, y down.

## Placement

Say how firm each thing is; the netlist does the rest.

```python
board.place(item)                                                       # searched: SEEDED from its links
board.place(item, edge=Edge.NORTH, along=x, rotation=180)                 # EDGE: its reach at the board's keep-in
board.place(item, at=Location(x, y), rotation=0, face=Face.FRONT)      # FIXED: a mechanical fact (a hole, a cell)
board.place(item, center=(X(Mid(a, b)), Y(a, 3.0)), rotation=0)         # FIXED: said in terms of pads
board.place(item, near=Location(x, y), radius=3.0, step=0.2, rotations=(0, 90))  # searched round a hint
```
`item` is a `Part` (schematic instance), a `Cell` (module group) or a block
(below). One declaration per item. `why=` is recorded in the run. A FIXED
or EDGE item that lands on another is a script error: the run stops
there with the collisions, before anything is searched (`placemat run
--keep-going` records them as findings and carries on). A finding names
a cell member with its cell: `j_mot (edge): J5 courtyard overlaps cell
a1's R2 courtyard`.

**The default is a bare `place()`.** A part with a wired neighbour already
on the board needs no position: price the connection and leave it to seed.

```python
board.place(Part("j_pwr"), edge=Edge.WEST, along=PWR_ALONG)                          # the connector is EDGE
board.link(PadRef(Part("rpf"), "V48_IN"), PadRef(Part("j_pwr"), "V48"), weight=LinkWeight.SHORT,
           why="the reverse-polarity FET sits at the inlet")
board.place(Part("rpf"))                                                # seeds beside J_PWR's V48 pin
board.link(PadRef(Part("c_bulk"), "V48"), PadRef(Part("rpf"), "V48_OUT"), weight=LinkWeight.SHORT, limit_mm=3.0,
           why="bulk cap at the FET's output")
board.place(Part("c_bulk"))                                             # seeds beside the FET, once it is down
```
The step note reads `seeded on V48` and the achieved link lengths are in
the run. A chain of small parts is the same thing repeated: each stage
linked to the stage before it and the two ends linked to the real pads
they terminate on, every stage a bare `place()`.

**`near=` is for what the netlist cannot say**: a thermal sensor that must
sit by the FETs it shares no net with, a test point wanted at the edge.
A `Location` constant that stands for "the power area" or "the CAN
corner" is a floorplan typed by hand; the placer floorplans from the
links, and a hint on a part that has a wired, placed neighbour is a
defect. Many parts hinted at one point compete for the same rectangle and
the last of them fails to place.

**The edge is the board's.** Nothing in a script says how far from the
edge a thing sits. `board.keep_in` is the board's own copper-to-edge
rule; an EDGE item's reach (body, pads and silk together, `board.reach(item,
rotation)`) lands there. A face that must stand proud of the edge says
`overhang=` with a why. A row inboard of an edge row is `behind=` it.

**Rows.** Things along one edge, in order, equally gapped, their outward
sides out (a cell generated with its connector's bulk on local +Y turns
270 on the west edge, 90 east, 180 north, 0 south; `rotation=` overrides
that, one value or one per item). A row's outer line is the keep-in, or
`inboard` (default `gap`) behind the inner line of the row it is
`behind=`. Across the row the items align on one line: `line="centre"`
(the default) puts their centres on one line, `"outer"` puts every
outward reach on the outer line (connectors edge-hard), `"inner"` aligns
their inboard edges; a row butted before or after another takes that
row's line:

```python
power = board.row(PD, Edge.WEST, gap=3.0, start=TOP, line="outer")                  # connectors edge-hard
trunk = board.row([CN, U13], Edge.NORTH, gap=2.5, align="center", line="outer")
pair = board.row([RB, RA], Edge.NORTH, gap=1.5, behind=trunk, inboard=2.0, rotation=180, centre=X(Mid(pin_n, pin_p)))
board.row([JUMPER], Edge.NORTH, gap=1.5, rotation=180, before=pair)   # on the resistors' centre line
legs = board.row(LEGS, Edge.SOUTH, gap=1.0, behind=mot_aux, start=Y(PadRef(MH3, 1), 4.0))   # after the hole
board.size(width=board.keep_in + power.depth + 4 + bus.depth + board.keep_in, height=max(power.end, bus.end) + TOP)
```
Where a row sits along its edge, one of: `start=` a number or a
reference; `align="center"` on the board; `centre=` or `end=` a reference
(`X(Mid(pin_n, pin_p))`, `X(pad, -2.0)`); `before=` or `after=` another
row, one gap away. A row's `depth` (how far inboard its reach goes),
`standoff` (its outer line, in from the edge) and `length` are numbers at
declaration; `start`, `end` and `centre(item)` too when it starts at a
number, otherwise refer to its items' pads. `row.inner` and `row.outer` are
its inboard boundary and its outer line, usable as a coordinate in copper
(`(power.inner + 1.0, y)`). Declare the size after the rows that set it.

**Positions said in terms of pads.** `at=` and `center=` take a Location
or a point of references, resolved when the item is placed:
`center=(X(Mid(rb_mid, ra_mid)), Y(rb_mid, 3.0))` puts a cap under the
midpoint of two pads. An item placed that way goes down after what it
refers to, which must be FIXED or EDGE.

**Modules.** A module's fragment runs the same way: `placemat run
modules/X/X_layout.py` finds the `Layout(name=, path=)` in the `.zen`
beside it, generates the fragment and applies the script. A fragment has
no outline, so its script declares no size; its anchor part goes down at a
coordinate and the rest is said in terms of the anchor's pads.

**How a searched item finds its place.** With `near=` it scans around the
hint. A scored scan over a wide radius is coarse first (four steps apart)
and fine only around its best spots, so a wide `radius=` costs little;
a part the script will place later is not an obstacle where the
generator left it, only once it is placed. Without one it is SEEDED: the hint is the weighted centroid of the
pads already placed that it connects to (plane nets and free nets do not
count), and every legal candidate in the scan is scored by its links, the
lowest kept; it may step at least its own size away from the seed, or
`radius=` when that is larger. If nothing it connects to is placed yet it
takes a POCKET: the biggest free rectangle its envelope fits on its face.
An item that finds no legal spot is left off the board: it pulls nothing
and blocks nothing, and the finding says what stopped it. The step note
says which happened.

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

## Rules

```python
board.rule(clearance=0.2, within=Cell("tmc"), why="0.5 mm pitch cannot meet the class between adjacent pads")
board.rule(clearance=0.6, between=(Net("V48"), Net("GND")), why="48 V to ground")
board.rule(clearance=0.4, on=Net("V48"), why="the bus")
```
A rule is one scope and a `why`; it is written as a KiCad custom rule in
`layout.kicad_dru` beside the board, named by its `why`, and the run's
DRC judges by it. A plan with no rules removes the file.

## Blocks

```python
ldo = board.block(Part("ldo"), satellites=[(Part("cin"), "VIN"), (Part("cout"), "VOUT")], gap=0.5)
board.place(ldo)                                                    # seeds from the links of its members
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

**Corners and routing between points.** Every leg is at 0, 45 or 90
degrees. Between two points that are not on the grid the tool tries the
octilinear ways of up to three legs (the 45 at the start, at the end or
between two straights, two 45s round a straight, the two L shapes), drops
those whose legs touch another net's pad or copper, and keeps the one with
the fewest direction changes against the legs either side (a chamfered
right angle counting two), then the shortest. So a track is best given only
its ends and the waypoints where it must go; the tool routes round what it
knows is there. Every right angle between axis legs is cut back `chamfer`
(default 1.0 mm) along both legs into two 45s; `chamfer=0` keeps it sharp. A tap
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

## Labels (silkscreen text for what a user touches)

```python
board.label(Part("j_mot"), "MOTOR", side=Edge.SOUTH, gap=0.5, knockout=True)
board.label(Cell("usb"), "USB-C", side=Edge.NORTH, align="start", size=1.2)
board.label(PadRef(Part("jp1"), 1), "1", side=Edge.WEST, gap=0.3, size=0.6)
board.label(Part("j_bus"), "CAN", side=Edge.EAST, rotation=90, why="reads along the edge it plugs into")
```
Text `gap` off `side` of the item's reach (or of one pad), on the item's
own face (mirrored on the back), aligned `centre`, `start` (the west or
north end of that side) or `end`; `rotation=90` runs it up the page;
`knockout` cuts it out of a filled box, which reads better over a busy
board. `size` and `thickness` default to 1.0 and 0.15 mm. Labels are
written after placement, so they follow the item; a label that lands on
another part on the same face is a finding. Mark what a user handles:
every connector, jumper, switch and LED, by what it does, not its refdes.

## Layers and faces

`CopperLayer.F / IN1 / IN2 / B`, `Face.FRONT / BACK`, `Edge.NORTH / SOUTH / EAST / WEST`.

## Commands

```
placemat run <script> [--label L] [--fresh] [--no-render] [--no-drc] [-v] [--json] [--keep-going] [--route [--route-full] [--route-exclude NET ...]]
placemat route <layout.kicad_pcb | script> [--exclude NET ...] [--layers L ...] [--full] [--iterations N] [--out DIR] [--json]
placemat impact <run-dir-or-json> <run-dir-or-json>
placemat drc <layout.kicad_pcb> [--json]
placemat measure <layout.kicad_pcb> [cell-or-part ...]
placemat check <layout.kicad_pcb | script> [--ambient C] [--keep-out MM] [--rise C] [--copper-oz OZ] [--limit CHECK=VALUE ...] [--json]
```
`check` reads the `Pm.*` facts the capture put on its parts (the
placemat-design skill says which) and reports hot loop area, switch node
copper, keep-out distance, crossings under sense tracks, current path
width against IPC-2221 and junction temperature; exit 1 on a failed
verdict. A board with no facts reports nothing to check.
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
