# The script surface

```python
from placemat import (board, Along, Axis, Bend, Beside, Between, Box, Cell, CellPadRef, Centre, Corner, Cover, Pin, Polar, OnRim, OnBore,
                       Cutout, Disc, Drops, Arc, Circle, Path, Slot, CopperLayer, Edge, Face, Forbid, Fraction, FreeSpot, Inside, Land, Line,
                       LinkWeight, Location, Mid, Near, Net, OnEdge, PadRef, Part, Past, Priority, Turned, X, Y)
```

`board` is the board being laid out. Questions answer from the generated
board; declarations are collected and resolved together.

## Say it by intent

A script says where a part or a piece of copper goes RELATIVE TO
something - a board edge, a row, the pin it serves, a lane past other pads, a
keepout, another part - and placemat works out the coordinate. Find what
you mean below, read the section it names, and write that form. Forms
compose: `Beside` decides a side and its `align=` the other axis; a via or
a via row one call returns is a track point in the next, and those or a
track are `Past` items. When no row fits, grep this file for the words of
the relation, try a composition, and read the newest sections of
`migration.md`, which name the hand-computed pattern each new form
replaces. Only a relation that search cannot say goes in the board's
`PLACEMAT_GAPS.md` (SKILL.md, "When no form says it").

| you want to say | write | section |
|---|---|---|
| **a part** | | |
| searched from its links, no position typed | `board.place(item)` | Placement |
| one that must place, or the run stops | `board.place(item, required=True)` | Placement |
| a cell with its pads' via fields thinned | `board.place(Cell(...), drops=Drops.HALF)` | Placement |
| on a board edge, wherever there is room | `at=OnEdge(edge)` | Placement |
| at a mechanical point along an edge | `at=OnEdge(edge, along=Along.MID)` | Placement |
| at a mechanical point (an enclosure hole, a datasheet figure) | `at=Location(x, y)`, `x`/`y` named constants | Placement |
| its own pad on the pin it serves | `at=Pin(key, X(pin), Y(pin))` | Placement |
| a cell placed by one of its members' pads | `at=Pin(CellPadRef(cell, net=), x, y)` | Placement |
| a cell placed by a member's footprint origin (not a pad) | `at=Pin(Part(member), x, y)` | Placement |
| between two pads | `at=Centre(X(Mid(a, b)), Y(a))` | Placement |
| sliding along one line, the other axis free | `at=Centre(None, y)` / `Location(x, None)` | Placement |
| somewhere the netlist cannot say (a thermal neighbour) | `at=Near(PadRef(...))` | Placement |
| beside a part, a cell or a keepout, at the envelope gap | `at=Beside(item, Edge.EAST, align=Along.START, gap=)` | Placement (Beside) |
| beside one part, level with a pad of it or of any firmly placed part | `at=Beside(item, Edge.SOUTH, align=PadRef(Part(other), n))` | Placement (Beside) |
| its pad a lane (or the clearance) past other pads | `at=Beside(item, Edge.SOUTH, align=(own_pad, Past([PadRef(...)], Edge.WEST, lane=Net(...))))` | Placement (Beside) |
| that lane as wide as its current needs | `Past(..., lane=Net(...), width=)` in that align | Placement (Beside) |
| its pad a lane (or the clearance) off a 45 past a pad's corner | `at=Beside(item, Edge.SOUTH, align=(own_pad, Past([PadRef(...)], Corner.NE, lane=Net(...))))` | Placement (Beside) |
| fixed off a part that is itself searched (a bypass at a searched part's pad end) | any firm `at=` (`Pin`, `Beside`, `row(of=)`) on the searched part: it rides the search | Placement (Riders) |
| turned with another part | `rotation=Turned(part, deg)` | Placement |
| turned to face a board edge or a bearing | `board.outward_rotation(item, edge)` | Faces |
| its fine-pitch escape kept clear | `board.fanout(part, depth=)` | Placement |
| **groups of parts** | | |
| a part and the parts at its pins | `board.block(anchor, satellites=[(item, net), ...])` | Blocks |
| parts down a board edge, in order | `board.row(items, edge)` | Placement (Rows) |
| a row inboard of another edge row | `board.row(items, edge, behind=other_row)` | Placement (Rows) |
| a row starting after a hole or a pad | `board.row(items, edge, start=Y(pad, gap))` | Placement (Rows) |
| a row along a part's side, not a board edge | `board.row(items, edge, of=Part(...))` | Placement (Rows) |
| a column held off a part's pad ends: the envelope gap off the side they set (`placemat measure --envelope` names what sets it) | `board.row(items, Edge.EAST, of=Part(...), centre=PadRef(...))` | Placement (Rows) |
| items at a mechanical pitch along a part's side, centred on a pad | `board.row(items, edge, of=Part(...), centre=PadRef(...), pitch=)` | Placement (Rows) |
| items round a centre | `board.ring(items, radius=)` | Round boards |
| a part at a radius and bearing | `at=Polar(radius, angle, about=)` | Round boards |
| on a disc's rim facing out, or at its bore facing in | `at=OnRim(edge)` / `at=OnBore(edge)` | Round boards |
| **what pulls parts together** | | |
| a connection priced (a bypass capacitor, a series part) | `board.link(a, b, weight=, limit_mm=)` | Links |
| a net whose off-board run dwarfs the board | `board.free_net(net)` | Links |
| a module's outward, quiet and handoff sides | `board.faces(outward=, quiet=, handoff=)` | Faces |
| **the board and its regions** | | |
| a board of any shape | `board.outline(path, holes=)` | Boards of any shape |
| a stretch of edge chosen by which way it faces | `board.edge(facing=Edge.NORTH)` | Boards of any shape |
| a round board | `board.disc(diameter, hole=)` | Round boards |
| a module frame sized to its own content | `board.size(fit=True)` | Setup |
| a module frame fitted in one axis, the other a declared number | `board.size(fit=Axis.X, height=)` | Setup |
| a hole in the board | `Cutout(shape, name, at=)` in `holes=` | Cutouts |
| a hole placed from the connector it serves | `at=Centre(X(Part(j)), Y(Part(j), d))` | Cutouts |
| a region that forbids parts, fill, tracks, vias or pads | `board.keepout(shape, name, at=)` | Keepouts |
| a region shaped by a part or cell, growing and turning with it | `board.keepout(item, name, margin=)` | Keepouts |
| a region inside a part's pads (between two pad columns, inside a pad ring) | `board.keepout(Inside(Part(...), margin=), name)` | Keepouts |
| a clearance anchored on a pad, in a datasheet's own coordinates | `Path(FIGURE, anchor=...)`, `at=PadRef(...)`, `rotation=Turned(part, 0)` | Keepouts |
| a clearance band along a board edge | `board.keepout(shape, name, at=OnEdge(edge, along=Along.MID))` | Cutouts (the shape on an edge) |
| a region a case leaves little room over | `board.keepout(..., excludes=(Forbid.PARTS,), max_height=)` | Keepouts |
| a part against a keepout's boundary | `at=Beside(keepout, Edge.SOUTH)` | Placement (Beside) |
| a clearance that differs from the net class, in one place | `board.rule(clearance=, within=/between=/on=)` | Rules |
| **copper** | | |
| a track from a pad to a pad | `board.track(net, [PadRef(a), PadRef(b)], layer=)` | Copper calls |
| which end of an off-grid leg takes the 45 | `board.track(..., bend=Bend.START/END/BOTH)` | Copper vocabulary |
| a track through the gap between two pads | `Between(PadRef(a), PadRef(b))` as a track point | Copper vocabulary (Lane waypoints) |
| a track held the clearance off pads, vias or tracks | `Past([PadRef(...), via, track], Edge.EAST, across=)` as a track point | Copper vocabulary (Lane waypoints) |
| a track's 45 held the clearance off a pad's corner | `Past([PadRef(...)], Corner.NE)` as a track point | Copper vocabulary (Lane waypoints) |
| a via at the nearest legal spot to a pad | `board.via(net, FreeSpot(near=PadRef(...)))` | Copper calls |
| a via its clearance past pads, vias or tracks, on a pad's axis | `board.via(net, at=Past([...], Edge.SOUTH, across=PadRef(...)))` | Copper calls |
| a power or exposed pad filled with vias | `board.vias(net, PadRef(...))` | Copper calls |
| a track, via or pour on one land of a pin drawn as several | `PadRef(part, n, land=Land.LARGEST)` or `land=2` | Copper vocabulary |
| vias in a row out from a pad, a tail joining them | `board.vias(net, along=PadRef(...), count=N)`; as a track point, its value is the farthest via | Copper calls |
| a track on to a via or a via row | the value `board.via()`/`board.vias(along=)` returns, as a track point | Copper calls |
| stitching vias over a cell, a pour or a keepout, or along its outline | `board.stitch(net, region, edge=)` | Copper calls |
| a micro, blind or buried via, for a fab that makes them (allowed in fab-profile.json) | `layers=(CopperLayer.B, CopperLayer.IN4)` on `via()`, `vias()` or `stitch()` | Copper calls (A via's layer span) |
| a pour of exactly the shape given | `board.pour(net, points, layer=)` | Copper calls |
| a pour over a set of pads, pulled back from other nets | `board.pour(net, [PadRef(...), ...], layer=, swallow_pads=True)`: the hull of the pads' copper (`cover=Cover.BOX`, the box round it) | Copper calls |
| a neck between two pads, as wide as the narrower or `width=` | `board.pour(net, [PadRef(a), PadRef(b)], layer=, swallow_pads=True, width=)` | Copper calls |
| a wide pour along a centreline into a pad | `board.finger(net, from_=, to=, width=)` | Copper calls |
| a finger as wide as a named pad | `board.finger(net, from_=, to=, width=PadRef(...))` | Copper calls |
| a zone over the whole board, or an outline | `board.plane(net, layers=, outline=)` | Copper calls |
| a zone over a group of parts only, wherever they were placed | `board.plane(net, layers=, over=[Part(...), Cell(...)], margin=)` | Copper calls |
| a coupled differential pair, its centreline found | `board.pair(p, n, [(padP, padN), (padP2, padN2)], layer=)` | Copper calls (Pairs) |
| the router pairing two nets whose names carry no `_P`/`_N` | `route.diff_pairs = ["*", "NET_A/NET_B"]` in placemat.toml | Settings (route) |
| silk text on a connector, jumper, switch or LED | `board.label(item, text, side=)` | Labels |
| a routed net kept, relative to its pads | `placemat route <script> --adopt NET` | Commands (Keeping routed copper) |

## Read the board

The questions a session asks between runs, and the command that answers
each from the board placemat already holds. Reach for these before grepping
a `.kicad_mod` or loading pcbnew.

| you want to know | run | section |
|---|---|---|
| what the parts are called, where they are, the totals | `placemat parts <board>` | Commands |
| a pad's copper box, net, centre and pin name | `placemat measure <board> <part> --pads` | Commands |
| a footprint's pads before it is on a board | `placemat measure <path>.kicad_mod --pads` | Commands |
| which item sets each side of a part's drawn envelope | `placemat measure <board> <part> --envelope` | Commands |
| each track segment of a net and what its ends land on | `placemat measure <board> --copper [NET ...]` | Commands |
| how near each part stands to a keepout | `placemat measure <board> --keepouts [NAME ...]` | Commands |
| the silk texts and marks on a board | `placemat measure <board> --labels` | Commands |
| one copper layer by net, and tracks inside another net's zone | `placemat layer <board> <LAYER>` | Commands |
| which nets matter: span, routed length, detour, vias | `placemat nets <board>` | Commands |
| what is at a point, where a via fits, a clear path between two pads | `placemat occupancy <board> --at / --via-near / --corridor` | Commands |
| each DRC violation, with the parts' instance paths | `placemat drc <layout.kicad_pcb>` | Commands |
| what changed between two runs | `placemat impact <run> <run>` | Commands |
| the placement drawn, in seconds | `placemat preview <script>` | Commands |
| a cell on its own, its pads by net and side | `placemat show <board> <cell>` | Faces |
| the settings in force and where each came from | `placemat settings <board-dir>` | Settings |
| which datasheet page has the land pattern | `placemat datasheet <pdf>` | Commands |
| the design checks the `Pm.*` facts drive | `placemat check <board>` | Commands |

## Questions (answered from the generated board, before anything moves)

| call | answer |
|---|---|
| `board.extent(item, rotation=0, face=Face.FRONT)` | body box of a `Part`/`Cell` at that rotation, placed at the origin: a size |
| `board.part(Part("j1"))` | the footprint: `.ref`, `.inst`, `.pads`, `.body_box`, `.courtyard_box` |
| `board.cell(Cell("mcu"))` | the cell: `.members`, `.box`, `.member("conn")` |
| `board.pad(Part("j1"), 3)` / `board.pad(Part("j1"), "GND")` | a pad by number (int) or net (str): `.box` (size, centre), `.through`, `.drill_mm`, `.layers` |
| `board.pitch(Part("j1"), pins=None)` | the part's pin spacing, read from its pads (a pin drawn as several lands is one pin): a connector's pin pitch; `pins=(5, 6)` the distance between two pins |
| `board.cell_pad(Cell("xcvr0"), net="BUS_H", ref_prefix="H")` (or `number=`) | one pad inside a cell |
| `board.net(Net("V48"))` | the net name, or `KeyError` |
| `board.netclass(Net("BUS_P"))` | its class: `.track_width`, `.clearance`, `.diff_pair_width`, `.diff_pair_gap` |
| `board.keep_in` | the board's copper-to-edge rule: where an EDGE item's reach lands |
| `board.reach(item, rotation=, face=)` | the item's body, pads and silk together, as a box at the origin |
| `board.height_of(part)` | the part's height in mm from its `Pm.Height` field; an error naming the field when it has none |
| `board.parts(net=None)` | every part on the board as a `Part`, or those with a pad on `net`: derive drops and checks from the netlist |
| `board.envelope(item, rotation=, face=)` | what the placer keeps for the item under `[place] envelope`, as a box at the origin - the number `row()`, `block()` and `Beside` already space by; read it to check a gap's arithmetic, not to build a row or a stack by hand |
| `board.claim(item, rotation=0, face=Face.FRONT)` | everything the item claims at that rotation, at the origin: its reach (body, pads, silk) and its courtyard together - what `row()`/`ring()` actually space by, so a zero gap is courtyards touching. A question to check a gap's number against, not a coordinate to place from |

The same answers from the command line, for when no script is running, are
`placemat parts <board>` and `placemat measure <board> <part> --pads`.

## Setup

`board.size(width, height, chamfer=0.0, radius=0.0, holes=(), web=0.0, draw=None)` - the
outline, origin top-left, y down; `draw=False` gives a fragment a frame that
is never drawn.
`board.size(fit=True, margin=None, chamfer=0.0, radius=0.0)` - a fragment's
frame (never drawn) sized to its content: the box round everything placed (each
part as the placer claims it, labels, tracks, vias, pours) plus `margin`
(default the keep-in), set once everything is placed.
`board.size(fit=Axis.X, height=, margin=None)` or `fit=Axis.Y, width=` - a frame
fitted in one axis only: the frame fits its content across x (or y) the same
way `fit=True` does, and the other axis is the declared number, origin at 0
the same as a sized board's - a mechanical fact the content must fit inside,
not a suggestion; an item whose placed box reaches outside it is a finding
naming it. `Axis` is `X` or `Y`. Even the declared axis's edges are refused
(`OnEdge`, a row on the board's own edge, `board.edge()`, `board.centre`)
until everything is placed, the same as `fit=True`'s - a scope decision, not
a limit of the number itself, which `board.width`/`board.height` answer from
declaration on.
`board.disc(diameter, hole=0.0, holes=(), web=0.0, draw=True)` - a round board at the origin, bored
`hole` wide through the middle when it goes round a shaft. Places on it are
bearings and radii (below); `board.centre`, `board.radius` and `board.bore`
answer where it is.
`board.outline(path, holes=(), web=0.0, draw=True)` - a board of any shape
(below); `path` may also be a shape, centred on the board origin.
`holes=` are cutouts, and every board takes them (below). `web=` is the least
material a hole may leave.
`board.centre` is the middle of the box round the board, whatever its shape,
and `board.centroid` is where its area balances.

## Placement

One argument says where a thing goes: `at=` a place, and the kind of
place says how much freedom is left.

```python
board.place(item)                                                       # searched: SEEDED from its links (two freedoms)
board.place(item, priority=Priority.HIGH)                               # searched, but before the rest: a tier above the rank
board.place(item, required=True)                                        # no place for it stops the run
board.place(item, at=OnEdge(Edge.NORTH))                                # on that edge, wherever there is room (one freedom)
board.place(item, at=Centre(X(Mid(pad_a, pad_b)), None))                # x pinned to a reference, y free (one freedom)
board.place(item, at=OnEdge(Edge.WEST, along=Along.MID), rotation=180)  # EDGE: on that edge at that distance (no freedom)
board.place(item, at=Location(x, y), rotation=0, face=Face.FRONT)      # FIXED: the origin, a mechanical fact (no freedom)
board.place(item, at=Centre(X(Mid(a, b)), Y(a, 3.0)), rotation=0)       # FIXED: the body centre, said in terms of pads
board.place(item, at=Pin("VIN", X(pin), Y(pin, 2.0)), rotation=90)       # FIXED: the item's own pad lands on the point
board.place(item, at=Beside(Part("u1"), Edge.EAST, align=Along.MID))   # FIXED: the drawn envelope a gap off another item's
board.place(item, at=Near(Location(x, y)), radius=3.0, step=0.2, rotations=(0, 90))  # searched round a hint
board.place(item, at=Near(PadRef(u1, 3).local(0.4, -1.2), radius=0), rotation=Turned(u1, 90))  # off a pad in its part's own frame, turned with it
```
`item` is a `Part` (schematic instance), a `Cell` (module group) or a block
(below). One declaration per item. `why=` is recorded in the run. A FIXED
or EDGE item that lands on another is a script error: the run stops
there with the collisions, before anything is searched (`placemat run
--keep-going` records them as findings and carries on). A finding names
a cell member with its cell: `j_out (edge): J5 courtyard overlaps cell
a1's R2 courtyard`.

**Degrees of freedom.** Each kind of place takes some away. `Location(x, y)`,
`Centre(x, y)` and `Pin(key, x, y)` fix both coordinates (the origin, the
body centre, or the item's own pad `key` (a number or a net), each axis a
number or a reference, and the two axes may name different parts:
`Pin(1, X(Part("j1")), Y(PadRef(Part("u1"), 14)))`): a cap whose pad must
sit on a pin's axis, a diode whose pad faces another's, is a `Pin`. On a cell, which has no pad of its
own, `key` is a `CellPadRef` or a `PadRef` naming one of its members' pads,
or a member `Part` for that member's footprint origin (a winding's arc
centre, which is no pad); the cell is carried rigidly so that pad, or
origin, lands on the point. `Location(30, None)` or
`Centre(None, y)` fix one: the item slides along the line, starting across
from what it connects to when any of that is placed, else at its middle alone or
sharing it evenly with the items pinned to the same value, aside from what
is there. `OnEdge(edge, along=)` fixes both: the reach at the
keep-in, and `along` the edge a number in mm, a reference, `Along.START`,
`MID` or `END`, or `Fraction(0.3)` of the usable length, the same on
every edge. `OnEdge(edge)` fixes one: it slides along the edge, midpoint
alone, the k-th of n at (k+1)/(n+1) with its fellows. `Near(location)` and
nothing fix none. Everything with a freedom left is searched, so it goes
down with the searched items in rank order. With no `rotation=`, an item
`OnEdge(edge)` with no `along=`, on a run from `board.edge(facing=)`, or on
a rim is turned so its outward side faces out (a cell's declared
`faces(outward=)`, a part's local +Y; see Faces); one at
`OnEdge(Edge.X, along=)` on a named side keeps rotation 0, so give it
`rotation=` or `board.outward_rotation()`. Test points,
LEDs, buttons and a connector whose exact spot does not matter are
`OnEdge(edge)`, never `along=`. Whether a position is decided is
`Freedom` - `fixed` for a point, `edge` for a distance along an edge,
`searched` for anything with a freedom left - and it is DERIVED from
`at=`, never given.

**Riders.** A firm placement - `Pin`, `Beside`, `row(of=)`, or a point said
in pads - whose reference is a searched part or cell rides it. At each
candidate the search tries the reference at, each rider is placed where its
declaration puts it with the reference there, and the candidate counts only
if every rider is legal: against the board, as a firm item is judged, and
against the reference and the other riders. They commit together, and each
rider's step says `rides u1`. A rider may have riders of its own. A rider
keeps the rotation it declares; one that turns with its reference says so,
`rotation=Turned(Part("u1"))` with a `.local()` offset. When no candidate
suits a rider, the reference is left unplaced and its finding names the
rider and why (`rider c1: C1 courtyard overlaps U1 courtyard`); a rider that
meets its reference at every rotation the search may take is refused before
the scan. Everything else a rider refers to is placed firmly before it or
rides with it: a `Beside` aligned to a pad of another searched part, or
beside a fixed part and aligned to a searched part's pad, is still refused
("only FIXED and EDGE items may be referred to"). A keepout or cutout at a
searched part's pad is refused too: regions are settled with the firm items,
before any search. A block is neither ridden nor a rider. The riders are
asked of the reference's best candidates first, so a rider that fits costs
a few checks; one that fits nowhere costs one at every candidate the
reference's own test passes.

**Rotation of a searched part.** A part searched from its links or round a
`Near()` hint, declared with neither `rotation=` nor `rotations=`, is tried
at 0, 90, 180 and 270, and the search keeps the turn that puts its pads
nearest what they connect to. `rotation=` keeps that one rotation;
`rotations=` the ones listed. An edge, a line or a ring decides its item's
rotation, and a cell or a block keeps its own. `[place] rotations =
"declared"` tries only the declared rotation.

**The rank.** Unless the script says, a searched item's place in the queue
is worked out from what it IS: how much board its courtyard needs and how
many pins it has, both against the rest of this board's searched items,
weighted by `[rank] area` and `[rank] pins`. Big and complex things go
down first and the small ones are fitted round them. Every step prints
`rank 4/64 (31.5 mm2, 12th of 64; 2 pins, 41st)`, so the numbers behind
the choice are in the log; no threshold is quoted because there is none.
`priority=Priority.HIGH` or `LOW` is a tier ABOVE the rank, for when the
rank is wrong, and the step then reads `(script: high)`. Items the rank
cannot separate - a shelf of identical passives - fall through to the
strongest link pull toward what is already placed. A place that leaves no
freedom refuses a priority: `at=Location(...)` or `along=` goes down
before anything searched already, so `priority=` on it has nothing to
order.

**`required=True`** says that failing to place this item stops the run,
with the board as it stood and the biggest free rectangles on its face. It
is independent of the rank and of whether the position is decided, and a
required item is not negotiable even under `--keep-going`. Nothing else
stops a run by itself.

**A cell's via fields.** `board.place(Cell(...), drops=Drops.HALF)` thins
the cell's via fields where it is placed. A field is the drops inside one
of its members' pads: vias of a net the board declares a `board.plane()`
for, on that pad's net. `Drops.ALL`, the default, keeps them as stamped;
`Drops.HALF` keeps every other via of each field, a checkerboard over its
grid in its part's frame (5 of a 3x3 field); `Drops.MIN` keeps
`place.drops_keep` of each field (0.5), rounded up and never fewer than
one, spread from the via nearest the field's centre. Other vias of the
cell, and the fragment itself, are untouched. The cell's step says what
each field kept: "drops half: 5 of 9 in U3.17". `drops=` takes the word
too, `"half"`, and is refused on anything but a cell.

```python
board.plane(Net("GND"), layers=(CopperLayer.B,))
board.place(Cell("m1"), face=Face.BACK, drops=Drops.HALF)
```

**A flip to the back** mirrors the item about the vertical axis and then turns
it by `rotation=`. That is KiCad's own F key (`editing.flip_left_right`, its
default), and a part and a cell flip the same way. KiCad's orientation field
will read `rotation + 180` for a back-face part, which is exactly what you get
by drawing that part upright on the front and pressing F. `face=` takes
`Face.FRONT`/`Face.BACK` or the string it prints, `"front"`/`"back"`; anything
else is refused at declaration.

**A cell's flip keeps its inner layers, which KiCad's does not.** A cell
flipped to the back swaps its own F and B copper and keeps its inner copper
(tracks, pours, zones, rule areas, buried vias) on the layer it was drawn
on, so the module keeps the layer roles it was laid out for: a pour on the
In2 power layer stays on In2. KiCad's own flip mirrors inner layers through
the stack (on six layers In1 and In4 swap, and In2 and In3); placemat judges
the cell with its inner copper where it was drawn, and the writer puts it
back there after KiCad's flip. Two things still mirror as KiCad flips them:
- A via that reaches a face (micro or blind) mirrors, so its face end moves
  with the face: F-In1 becomes B-In4. When its inner end then may no longer
  join its net - the two layers differ in KiCad type, or either lacks the
  via net's own plane (from `board.plane()` or the board's own zones) - the
  cell's step says so, naming the via and both layers.
- A footprint's own copper, a cell member's included, mirrors its whole
  stack: a footprint is one part drawn for a face, such as a coil wound on
  every layer.

**The default is a bare `place()`.** A part with a wired neighbour already
on the board needs no position: price the connection and leave it to seed.

```python
board.place(Part("j_pwr"), at=OnEdge(Edge.WEST, along=Along.MID))     # a distance along an edge: decided
board.link(PadRef(Part("rpf"), "V48_IN"), PadRef(Part("j_pwr"), "V48"), weight=LinkWeight.SHORT,
           why="the reverse-polarity FET sits at the inlet")
board.place(Part("rpf"))                                                # seeds beside J_PWR's V48 pin
board.link(PadRef(Part("c_bulk"), "V48"), PadRef(Part("rpf"), "V48_OUT"), weight=LinkWeight.SHORT, limit_mm=3.0,
           why="bulk cap at the FET's output")
board.place(Part("c_bulk"))                                             # seeds beside the FET, once it is down
```
The step note reads `seeded on V48` and the achieved link lengths are in
the run. A pad is named by number (`PadRef(part, 3)`), by net
(`PadRef(part, "V48")`), or by the pin name its symbol gives it:
`PadRef(Part("mcu"), pin="VDD_CORE")`. `.offset(dx, dy)` moves the point
in board directions; `.local(dx, dy)` moves it in the part's own frame, as
its footprint is drawn, so the move turns with the part (and on the back
mirrors). A pin drawn as several lands (a side tab, small pads and an
exposed pad on one number) is one pad whose centre may be bare board
between them; `land=Land.LARGEST` (most copper area) or `land=2` (the
footprint's second land of that number, counted from 1) names one land.
The reference then locates at that land's centre, and a track's end, a via
grid, a `Past` and a pour's corners read that land's copper only. On a
number with one land it is the plain pad. A land past the count is a
ValueError naming it; a link, and a cell's `Pin` key, refuse `land=`.
`rotation=Turned(Part("u1"), 90)` is that part's placed rotation plus 90;
the item waits for the part. Pin names are read from the symbols the
board's .zen files use, through the generator's netlist; a name
on several pads (a symbol's repeated GND) asks for the number instead, and
`placemat measure <board> <part> --pads` prints each pad's pin name beside
its number. A chain of small parts is the same thing repeated: each stage
linked to the stage before it and the two ends linked to the real pads
they terminate on, every stage a bare `place()`.

**A fanout band** keeps a fine-pitch part's escape clear:

```python
board.fanout(Part("mcu"), depth=2.0, why="the GPIO escape")   # sides=[Edge.NORTH, ...] for fewer
```
Per side of the part as placed, the strip from its pad row's outer edge out
`depth` mm, spanning the row (an exposed pad belongs to no side), is
reserved on its face as soon as the part is down. Only the part, the
satellites of a block it anchors and parts linked to its pads at
`LinkWeight.SHORT` or more may enter; a resistor seeded on a GPIO lands at
the nearest legal spot outside, across the band from its pin.

**`Near` is for what the netlist cannot say**: a thermal sensor that must
sit by the FETs it shares no net with, a test point wanted at the edge.
A `Location` constant that stands for "the power area" or "the bus
corner" is a floorplan typed by hand; the placer floorplans from the
links, and a hint on a part that has a wired, placed neighbour is a
defect. Many parts hinted at one point compete for the same rectangle and
the last of them fails to place.

**The edge is the board's.** Nothing in a script says how far from the
edge a thing sits. `board.keep_in` is the board's own copper-to-edge
rule; an edge item's reach (body, pads and silk together, `board.reach(item,
rotation)`) lands there. A face that must stand proud of the edge says
`OnEdge(edge, overhang=)` with a why. A row inboard of an edge row is `behind=` it.

**Beside another item.** `at=Beside(item, Edge.EAST, align=None, gap=None)`
stands the item on that side of `item` - a `Part`, a `Cell` or a keepout
(what `board.keepout(...)` returns) - its drawn envelope `gap` off
`item`'s. `gap` is a floor, not an override, as `row(of=)`'s is: at least
the envelope's own gap - the rule a row's default gap keeps too: the
widest of the net clearance, the component spacing and the silk
clearance, or courtyards touching under a courtyard envelope - whatever
the script gives. `side` decides one axis and `align=` the other: beside a
`NORTH` or `SOUTH` side, `align=` sets x; beside `EAST` or `WEST`, y.
FIXED like `Pin`: `item` is placed firmly (FIXED or EDGE) before it, or is
searched and this item rides it (see Riders); it keeps the rotation the
script gave, or its default -
`Beside` does not turn the item to face `item`. `align=` lines it up
across the side, flush as `OnEdge` and `row(of=)` are, never the placed
part's body centre left overhanging the corner: a `PadRef` - the placed
part's own pad on the same net lands level with the named pad -
`(own_pad, their_pad)` when the nets differ, or an `Along` of `item`'s side - `START` flush with its
start, `END` flush with its end, `MID` (default) centred. The pad may be
`item`'s own or any other part's placed firmly by then: west of a
capacitor, level with a driver's pin, is `Beside(Part("c_boot"),
Edge.WEST, align=PadRef(Part("u1"), "SW"))`.

`align=(own_pad, Past(pads, Edge.WEST, lane=None))` stands the own pad's
facing edge past the pads' `edge` side instead of level with a pad. The
distance is the worst clearance, by net pair, from the own pad's net to
the pads'; with `lane=` a net it is room for one track of that net between
them: the clearance from the pads to the net, its track width (or
`width=`, the copper its current needs: a pour's width past a switch pin),
and the clearance from the net to the own pad. `Beside`'s side still decides the
other axis, so the Past's edge is on the axis the side leaves open (`EAST`
or `WEST` beside a `NORTH` or `SOUTH` side). A placement is decided before
any copper is planned, so the Past takes pads only - a via or a track is
refused - and takes no `across=`. The pads' parts are placed firmly first,
as for any firm placement. The track then takes the same line as a
waypoint, `Past([PadRef(...)], Edge.WEST)`.

With a `Corner` in place of the edge, `(own_pad, Past(pads, Corner.NE,
lane=Net(...)))` stands the own pad off the 45 that passes the pads' NE
corner: the own pad's corner facing the 45 (its SW corner) stands the same
distance out along the diagonal from the pads' corner, measured across it.
`Beside`'s side decides one axis and the corner the other, so any side
goes with any corner. The track takes the 45 as a waypoint,
`Past([PadRef(...)], Corner.NE)`. A width sized for a current
is a fact: a named constant citing IPC-2221 at the board's `check.rise_c`
and `check.copper_oz` (`placemat settings` prints them); the run's
`current-path` check then judges the copper drawn in the lane.

```python
board.place(Part("c_bypass"), at=Beside(Part("u1"), Edge.WEST, align=PadRef(Part("u1"), "VDD")))
board.place(Cell("indicators"), at=Beside(Part("j_conn"), Edge.SOUTH))          # MID of the connector's south side
clr = board.keepout(Circle(10.0), "ant", at=PadRef(ANT, "FEED"), allow=(ANT,), why="the matching network")
board.place(Part("r_series"), at=Beside(clr, Edge.NORTH, align=Along.START, gap=0.3))
board.place(Part("u2"), at=Beside(Part("c_vdd"), Edge.SOUTH,                # its pad 1 a lane west of c_in's pad 1
                                  align=(1, Past([PadRef(Part("c_in"), 1)], Edge.WEST, lane=Net("EN")))))
board.track(Net("EN"), [PadRef(Part("u1"), "EN"), Past([PadRef(Part("c_in"), 1)], Edge.WEST),
                        PadRef(Part("u2"), 1)], layer=CopperLayer.F)
```

**Rows.** Things along one edge, in order, `gap` apart (default 0:
courtyards touching), their outward
sides out (a cell generated with its connector's bulk on local +Y turns
270 on the west edge, 90 east, 180 north, 0 south; `rotation=` overrides
that, one value or one per item). A row's outer line is the keep-in, or
`inboard` (default `gap`) behind the inner line of the row it is
`behind=`. Across the row the items align on one line: `line=Line.CENTRE`
(the default; also "centre") puts their centres on one line,
`Line.OUTER` ("outer") puts every outward reach on the outer line
(connectors edge-hard), `Line.INNER` ("inner") aligns their inboard
edges; a row butted before or after another takes that row's line:

```python
power = board.row(PD, Edge.WEST, gap=3.0, start=TOP, line=Line.OUTER)               # connectors edge-hard; gap= only with a reason (default 0: courtyards touch)
trunk = board.row([CN, U13], Edge.NORTH, gap=2.5, align=Along.MID, line=Line.OUTER)
pair = board.row([RB, RA], Edge.NORTH, gap=1.5, behind=trunk, inboard=2.0, rotation=180, centre=X(Mid(pin_n, pin_p)))
board.row([JUMPER], Edge.NORTH, gap=1.5, rotation=180, before=pair)   # on the resistors' centre line
legs = board.row(LEGS, Edge.SOUTH, gap=1.0, behind=aux_row, start=Y(PadRef(MH3, 1), 4.0))   # after the hole
board.size(width=board.keep_in + power.depth + 4 + bus.depth + board.keep_in, height=max(power.end, bus.end) + TOP)
```
`overhang=` stands the row's outward faces that far past the edge, as
`OnEdge(edge, overhang=)` does. Where a row sits along its edge, one of: `start=` a number or a
reference; `align=Along.MID` (also "centre"/"center") on the board,
`Along.END` ("end") flush with the far keep-in; `centre=` or `end=` a
reference (`X(Mid(pin_n, pin_p))`, `X(pad, -2.0)`); `before=` or `after=`
another row, one gap away. A row's `depth` (how far inboard its reach goes),
`standoff` (its outer line, in from the edge) and `length` are numbers at
declaration; `start`, `end` and `centre(item)` too when it starts at a
number, otherwise refer to its items' pads. `row.inner` and `row.outer` are
its inboard boundary and its outer line, usable as a coordinate in copper
(`(power.inner + 1.0, y)`). Declare the size after the rows that set it.

**A row off a part, not the board edge.** `board.row(items, Edge.SOUTH,
of=Part("u1"), align=Along.START)` runs the row along that side of
`Part("u1")`'s (or a `Cell`'s) drawn envelope instead of the board's: `gap`
(default the envelope's own, as `Beside` keeps) is both the row's own gap
and how far its near line stands off `of`, and `line=` still says how the
row aligns across itself. `align=Along.START/MID/END` is where along
`of`'s side the row sits (default `START`). `centre=PadRef(...)` instead
puts the row's middle on that pad's centre line: a pad of `of`, or of any
part placed firmly by then. It takes one `PadRef` or `CellPadRef` (a `Mid`
or an `X()`/`Y()` is refused, unlike a board-edge row's `centre=`) and is
not given with `align=`. `pitch=` is the
distance between neighbouring items' centres, in place of `gap=` between
their envelopes (not both); with a pitch the row's middle is halfway
between its first and last items' centres. The row still stands the
envelope gap off `of`, and a pitch that brings two envelopes closer than
that gap is refused, naming both items and the pitch they need. `start=`,
`end=`, `before=`, `after=`, `behind=` and `inboard=` are said relative to
the board's edge, so they are refused together with `of=`. It waits for
`of` (and `centre=`'s part) to be placed, and - unlike a row on the
board's own edge - accepts a fit frame:

```python
board.row([R_SDA, R_SCL], Edge.EAST, of=Part("u1"), align=Along.START)   # a lane east of U1, top-flush
board.row([Part("p_a"), Part("p_b")], Edge.NORTH, of=Part("u1"),
          centre=PadRef(Part("u1"), 8), pitch=2.7)                         # two pins at a mechanical pitch, over U1's pin 8
```

**Positions said in terms of pads and parts.** `Centre` (and a point of
references in `at=`) resolve when the item is placed:
`Centre(X(Mid(rb_mid, ra_mid)), Y(rb_mid, 3.0))` puts a cap under the
midpoint of two pads; `X(Part("sw_run"), 4.8)` and `Y(Part("sw_run"))`
are that part's placed body centre, so `Centre(X(SW_RUN, 4.8), Y(SW_RUN))`
stands an LED level with a switch. A part or cell named this way is
placed first. An item placed that way goes down after what it
refers to, which must be FIXED or EDGE.

**Modules.** A module's fragment runs the same way: `placemat run
modules/X/X_layout.py` finds the `Layout(name=, path=)` (or the
`Project(name=, path=)` the stdlib writes it as) in the `.zen`
beside it, generates the fragment and applies the script. A zen may
declare one Layout per variant (an `if` on a `config()`), each with its
own script named for it; the script's first line `# placemat generate:
--config key=value` tells the generator which. A fragment has no outline
to write, but its script may give it a frame, `board.size(w, h,
draw=False)`, sized from its own rows, so the controls that must meet
a board edge are a `row` on the frame's edge; the board supplies the
real outline. What is not on an edge is said in terms of parts and pads.
A fragment with no edge to meet takes `board.size(fit=True)`:
its main part at the origin, the rest from its pads, and the frame is what
they fill plus the margin - no frame or anchor position computed by hand. A
searched item on a fit board searches round what is placed so far, by
`place.fit_room` (10 mm) and its own size; a `board.plane()` with no
`outline=` is planned after the frame and inset from it; a keepout needs a
place of its own, not a freedom. A frame edge, `board.centre`,
`board.width` and `board.height` are refused on a fit board: the plan's
outline is the frame once it is resolved.

**How a searched item finds its place.** An explicit `at=Near(...)` scans
round its hint; a `Near(PadRef(...))` on another searched item's pad waits
for that item, block members included, whatever the two items' tiers and
ranks, so it is searched round where the pad landed. Without a hint the
item is SEEDED: the hint is the weighted centroid of the placed pads it
connects to (plane nets and free nets do not count), every legal candidate
in the scan is scored by its links and the lowest kept, and it may step at
least its own size away from the seed, or `radius=` when that is larger. An
item wired to nothing placed yet takes a POCKET: the largest free rectangle
its envelope fits on its face. A seeded item with no legal spot within
reach takes the free rectangle nearest where it was centred, and its step
says "took the pocket" and how far off that is; one with an explicit `Near`
is left unplaced instead. An unplaced item pulls nothing and blocks
nothing, and the finding says what stopped it. A scored scan over a wide
radius is coarse first (`place.coarse_steps` apart) and fine only round its
best spots, so a wide `radius=` costs little. A part the script places
later is not an obstacle where the generator left it, only once it is
placed. The step note says which of these happened.

**Order.** FIXED and EDGE items go down as declared. Searched items are
ordered by the placer, re-measured after each. A cell, a block and a loose
part are ONE queue: a connector can be the most important thing on a board
and does not wait behind the cells for being a single part. The script's
`priority=` tier leads, then the rank - courtyard area and pin count, each
measured against this board's other searched items - then the strongest link
pull toward what is placed, which only separates items the rank cannot, then
the largest. The sentence that chose each is in its step. One exception to
the rank: of two items joined by a `board.link()` and neither placed, the one
with less pull toward what is placed waits for the other, so it is seeded on
the part the link joins it to; its step says "waited for" which. The wait
orders items within one `priority=` tier: an item never waits for a partner
of a lower tier, so a `HIGH` item linked to a `DEFAULT` one goes down with
the `HIGH` tier and the other then places toward it. Two pulled equally
keep the rank's order.

**What a part claims.** `[place] envelope` says what one part may not share
with another. `courtyard` (the default) is its courtyard and its pads.
`physical` is what the part draws, each on the faces it occupies: its pads,
each pad's mask opening (the pad grown by its expansion), every silk graphic
as stroked (the footprint's text fields excluded - `board.label()` text stays
a reservation) and its body, the box of its fab graphics. A footprint that
draws neither silk nor fab keeps its courtyard. `union` is both. In
`physical` a part's courtyard still keeps off another part's plated lead, and
its plated leads out from under another part's courtyard, as KiCad's DRC
judges them (`pth_inside_courtyard`); the refusal names the pad: `C1 courtyard
sits over the through-hole lead of J1 pad 2`. Under every
envelope a footprint's own copper graphics (a net-tie's winding, a printed
antenna) are copper of no net: every other part, track and via - placed,
drawn by the script, or found by `FreeSpot` and `--via-near` - keeps the
default clearance from them. Between two
different parts, every gap is the board's own:

| | another part's copper | mask opening | silk | body |
|---|---|---|---|---|
| copper | netclass clearance | - | - | component spacing |
| silk | - | silk clearance | silk clearance | 0 |
| body | component spacing | - | 0 | component spacing |

**A courtyard that is not a rectangle** - a slice of a disc, an L - is
claimed as the polygon KiCad draws and its DRC tests, not the box round it:
parts whose boxes overlap but whose courtyards do not may stand together, and
on a round board its edge is judged by the polygon's points
(`place.courtyard_polygon_share`).

**The far face.** A part's courtyard and body are on its own face. Its
plated pads and unplated holes reach both, so on the far face a part keeps
only those: another part's pads keep their clearance from them, and another
part's courtyard may not sit over a lead (it stands proud of the far face).
A via in one of the part's own surface pads (an exposed pad's thermal vias)
is not a lead: on the far face it claims its copper only.

**Holes.** Every drilled hole - a plated pad's, a via's (a stamped cell's
included), an unplated one - keeps the board's hole-to-hole rule from
another part's or cell's holes, whatever their nets: two ground vias of two
cells may not be drilled closer than the rule, though their copper may
touch. Copper keeps the board's hole clearance from an unplated hole,
whichever of the two is being placed. A part's or a cell's own holes are its
own.

The silk clearance is the board's minimum silk item clearance; the component
spacing is `courtyard.component_spacing_mm` in fab-profile.json, twice the
courtyard excess when absent. Tracks and vias may run under a body. The
members of a block keep these gaps from each other too. The rank measures an
item by the box round what the envelope claims, and a row spaces by the reach
alone in `physical`, with a gap of at least the widest the envelope keeps
between two parts (the netclass clearance of the row's nets, the component
spacing, the silk clearance): a pad at the edge of its reach cannot meet the
next part's. KiCad's DRC still checks courtyards, so a `physical`
board reports `courtyards_overlap` wherever two courtyards now meet; if the courtyards are not what the fab uses,
`[drc.severities] courtyards_overlap = "ignore"` in `placemat.toml` sets it aside
(written into the board's project each run: the generator rewrites that file).
In `courtyard` mode a run lists each footprint whose silk or pads pass its
courtyard by more than the silk clearance (`footprints`, and
`metrics.footprints`) - outside the findings, so the best-run gate is
unaffected. `placemat measure` prints each part's drawn envelope and the layer
that sets each side.

**The cleanup pass.** Once every searched item is down, and before the copper
that joins them is planned, a cleanup pass revisits the plain searched parts:
each is tried near the middle of what it connects to and round where it
stands, identical parts (one courtyard, pad count and face) are tried in
each other's places, and so are two neighbouring two-pad parts of any size (in
any rotation each may take), keeping a change only when the part's wire (the
half-perimeter of its nets that pull) plus each declared link's weight times
its length gets shorter. No change leaves a limited link over its limit and
longer, a part turns only to rotations its declaration allows (all four when
it gave none), faces stay, and every placement is legal as a search's is. It leaves alone any part with a place of its own (`Near`, an edge, a row,
a ring, a line), a block or cell member, a labelled part, and a part another
declaration's place refers to. A moved step says `cleanup: moved D mm` or
`swapped with K`; `metrics.cleanup` holds the moves, swaps and the cost
before and after. On the module benchmark it made 21 of 32 modules better and
none worse, for about 1.7 times the placement's own time; `passes = 3, step =
0.25` made 23 better for about 3 times, and `radius = 5.0` shortens the wire
further (median 0.92 of the uncleaned against 0.95) at about 3 times.
`[cleanup] enabled = false` turns it off.

**Reusing the previous run.** A run replays the previous run's steps up to
the first one whose inputs changed and resolves from there; the board it
writes is the one a run from scratch would write. A step's inputs are its own
declaration, the links on its pads and every step before it; the generated
board, the tool, the settings, the fab profile and every board-wide
declaration (copper, planes, keepouts, cutouts, labels, rules, the outline)
feed every step, so changing one of those replays nothing - nor, with the
solve on, does changing any placement. The run prints `reused N of M steps
from run <id> (first change: <item>)` and records `metrics.reused`;
`placemat run --no-reuse` resolves every step. On the 220-part board an
unchanged rerun went from 125 s to 7 s, and a change to a part late in the
order from 118 s to 24 s. A change early in the order - most of the
fixed tier, the large parts - still re-resolves nearly everything.

**The global solve.** With `[solve] enabled = true`, at the first searched
item placemat works out where every unplaced searched part and cell would
sit if the whole netlist pulled at once - placed items as anchors, each pad
at its offset, plane and free nets pulling only through declared links,
then an even spread over the board that keeps their relative order - and
each item is searched from that point instead of its seed. A block keeps
its own seeding. A solved hint with nothing legal within reach is dropped
for the path the item had without it. It is off by default: on one
measured 96-item board it matched the sequential seed on items placed and
findings and joined seven more connections, but cost one more DRC violation
and 1.6% more airwire, so the best-run gate judged it worse; over 32
benchmark modules it was better on 13 and worse on 15, better on most of
those with fourteen or more parts. Try it on a board whose searched items
scatter or land in pockets with "nothing it connects to is placed", and let
the `best` line judge.

## Cutouts

A hole in the board is a `Cutout` in `holes=`, and every board takes them: a
rectangle, a disc and a shaped board all say it the same way and all behave
the same way.

```python
from placemat import Cutout, Slot, Circle, Path

CABLE = Cutout(Slot(13.0, 3.0), "cable",
               at=Centre(X(Part("j_cable")), Y(Part("j_cable"), 4.0)),
               why="the flat cable passes through to the panel behind")
VENT = Cutout(Slot(8.0, 2.0), "vent", at=Polar(14.0, Fraction(0.5)), why="airflow past the regulator")

board.disc(diameter=40.0, hole=6.0, web=1.5, holes=[CABLE, VENT])
board.place(J, at=OnEdge(board.cutout("cable").edge(side=Edge.NORTH), along=Along.MID))
```

**The shape says what, `at=` says where.** `Slot(length, width)` is measured
tip to tip, the way a drawing dimensions it, and runs along +X until a
`rotation=` bearing turns it. `Circle(diameter)` is a round hole and refuses a
rotation. `Path(points)` is any closed path, moved so its box centre lands
where it is placed; `anchor=` on any shape names the point of it that lands on
the place instead. `at=` takes `Location`, `Centre`, `Polar`, `OnEdge` or
`Near`, and a freedom left in it is settled against what is on the board: a
vent with `at=Centre(None, 20.0)` slides along that line to where there is
room. On `OnEdge` the shape's centre stands in from the edge by `board.web`
plus half the shape's extent toward the edge, as turned there, so a shape
`d` deep lies inside the board with its outer side on the edge, on any
side; a keepout band along an edge is a `Slot` or `Path` of the band's
length by its depth at `OnEdge(edge, along=Along.MID)`. A raw path in `holes=` still works and means "already absolute, place
nothing".

**Which way it runs.** With no `rotation=`, a place that carries a direction
runs the shape tangentially: a vent on a ring follows the rim, a slot on an
edge runs along it. Everywhere else the shape is as declared, and a `Circle`
is never turned. `rotation=Turned(part, degrees)` turns it with a part
already on the board: the region turns the way the part does (its own
placed rotation plus `degrees`), resolved once that part is placed - the
same `Turned` a `place()` takes. A region's own numeric `rotation=` is a
bearing, clockwise from the top; under `Turned`, `degrees` reads the way a
part's own `rotation=` does instead - anticlockwise on screen - so it
matches whatever the script already gave the part, not a bare bearing.
`at=PadRef(...)` alone follows the part's MOVE; `Turned` is how it follows
the part's TURN too.

**When it is settled.** A cutout with a decided place goes down with the firm
items, in dependency order, so a slot placed from a connector waits for that
connector. One with a freedom waits until every decided thing is down. Both
are settled before any part is searched, so every part is placed against a
board that already has its holes. A cutout placed from a *searched* item is
refused, naming it.

**`side=`, not `facing=`.** `board.cutout(name).edge(side=)` is the only route
to a hole's runs, so `board.edge(facing=)` can never return one. `side=
Edge.NORTH` is the hole's northern boundary, which an item sits above and
faces SOUTH into - the same turn `OnBore` makes at a bore. The board's
`facing=` means which way an item points, and on a hole those two read
opposite, so a cutout refuses `facing=` rather than hand back the wrong
stretch. Several stretches on one side raises from `.edge()` and comes back as
a list from `.edges()`. The handle also carries `.box`, `.centre`, `.area` and
`.name`; `plan.cutouts_placed[name]` is where each one ended up.

**What a cutout is not.** It is not a stretch of the board's edge:
`board.edge(facing=)` reads the outline only. It is not a copper keepout: it
is a real board edge, so tracks and zones must clear it themselves. A region
that must stay clear of copper WITHOUT removing board is a keepout (below).

**The web.** `board.web` is the least material that may remain round a hole -
to the board outline, and to another hole. `board.keep_in` is copper to edge
and says where a part may sit; `board.web` is material to material and says
where a hole may sit. A cutout that would leave less is refused, and one that
touches the outline is refused as a notch, which belongs in the board's own
outline path instead. The default is 0.0, which means unchecked.

## Keepouts

A region that forbids, as against a cutout, which removes board.

```python
board.keepout(shape, name, *, at=None, rotation=None, margin=None, excludes=None,
              allow=(), layers=None, max_height=None, why="")
```

```python
CLEARANCE = Path(DATASHEET_FIGURE, anchor=(0.0, 0.0))  # the datasheet's own coordinates

board.keepout(CLEARANCE, "antenna", at=PadRef(Part("ant"), "ANT_FEED"),
              allow=(Part("ant"), Part("r_ant_series"), Net("ANT_FEED")),
              why="datasheet p1 Layout: copper-free on every layer")
```

**The shape, the place and the rotation** are a cutout's: `Slot`, `Circle`,
`Path`, `at=` taking `Location`, `Centre`, `Polar`, `OnEdge`, `Near` or a
`PadRef`, and `rotation=` taking a number (a bearing, clockwise from the
top) or `Turned(part, degrees)` to turn with a part already on the board -
the region turning the way the part does, `degrees` turning the way a
part's own rotation does (anticlockwise on screen). A freedom left in `at=`
settles against what is on the board. `anchor=` is the point of the shape
that lands on `at=`; without one it is the middle of the shape's box, which
is right for a slot and meaningless for a stepped clearance.

**A region shaped by an item.** `shape` may be a `Part` or a `Cell` already on
the board instead: no `at=` or `rotation=`, `margin=` (default 0) in their
place.

```python
board.keepout(Part("ant"), "antenna_body", margin=0.3,
              why="clearance round the antenna's own footprint")
```

The region is that item's drawn envelope - pads, the footprint's own copper
graphics (a winding drawn as copper, on any layer), mask openings, silk and
body, and for a
`Cell` the union of its members' (its own tracks, vias and pours are not a
member's drawn envelope, so they are left out) - grown by `margin`, and it
moves, turns and mirrors with the item (face=Face.BACK flips it the same
way): settled once the item is, the same as a keepout at its pad. The item
must already be FIXED or EDGE (as `at=PadRef(...)` already requires): one
still searched raises "not placed by then".

**A region inside a part's pads.** `Inside(Part(...), margin=0.0)` in place
of the shape is the box bounded by the inner edges of the part's pads,
settled and turned as a region shaped by the item is.

```python
board.keepout(Inside(Part("u1"), margin=-0.1), "under_u1", excludes=(Forbid.VIAS, Forbid.TRACKS),
              why="nothing between the two pad columns")
```

Each pad belongs to the row of the side of the pad field it is
proportionally nearest (a tie goes by the pad's long side), and counts when
it lies wholly on that side of the body centre, so a centre pad counts for
no side. A side with a row takes that row's inner edge; a side with none
(two columns and no rows) takes the pads' outer extent on that axis. The
box is grown by `margin`, which may be negative. A part whose box has no
area is a ValueError naming it.

**What it forbids.** `excludes=` defaults to everything and narrows to any of
the `Forbid` enum: `PARTS`, `FILL`, `TRACKS`, `VIAS`, `PADS` (the strings
`"parts"`, `"fill"`, `"tracks"`, `"vias"`, `"pads"` still work). Each is one
KiCad rule-area flag, and `Forbid.PARTS` is what the placer enforces itself,
before anything is written.

**Where.** `layers=` defaults to every copper layer the board has, whatever the
count. Narrow it with a list of `CopperLayer`. It narrows what is CHECKED as
well as what is written: a track on a layer the region does not cover is not a
finding. A via joins the whole stack, so a region on any one layer contains it. A
part sits on a face, so `"parts"` keeps parts off the faces among its
layers: `layers=["F.Cu"]` leaves the back free, and inner layers alone keep
no part out. A region a cell brings follows the cell to the other face.

**What KiCad reports.** A rule area as KiCad saves it has no allow list, so
KiCad's DRC lists a part (or a track of a net) the keepout allows as
`items_not_allowed`. The run sets those aside: they are counted as
`permitted` (`metrics.permitted`, and the DRC line's "permitted by their
keepout"), not as violations.

**The board edge.** A region may hang off it. Only the on-board part does
anything - a part is refused for crossing the keep-in before any reservation is
tested, and KiCad clips a zone to Edge.Cuts itself - and the step counts the
points that fell outside. A region WHOLLY off the board is an error: it forbids
nothing, and the script says otherwise.

**A stamped cell brings its own.** A module fragment's regions arrive with the
cell, inside its group, and are honoured: they move with the cell and fence the
placer. Its labels come the same way: each silk text in the cell's group keeps
parts off its box on its face once the cell lands (`sits in the reservation
for label 'BOOT' from the debug cell`), so a parent need not declare them again.
A stamped region larger than its cell costs the parent the difference: the
cell's step says `its stamped regions keep parts off N mm2 of board beyond
its own parts`. For a part's escape band, `board.fanout()` follows the pad
rows and admits the part's own satellites and the parts linked to its pads
at `LinkWeight.SHORT` or more; a rectangle keepout does neither. A cell's
regions are read from the generated board, so a keepout whose name would
collide with one is refused.

**A stamped cell's zones under the board's own plane.** A module fragment's
copper zone (its ground or supply fill) is merged into the parent's plane when
the parent declares a `board.plane()` on the same net and layer that covers it
(a zone reaching nearer the board edge than the plane's keep-in counts by the
part inside it): the written board leaves the cell's zone out on that layer,
and the run says `zones  <cell>: GND on In1.Cu merged into the board's plane`,
adding its clearance when that differs. A cell zone whose pads join otherwise
than the plane's (solid, thermal, solid with thermal through pads, or not
joined) is kept,
and the run says `zones  <cell>: its GND zone on In1.Cu kept under the board's
plane: ...`. A cell zone on another net, on a layer the parent has no plane
on, or reaching past the plane's outline is kept. The search never
counted a zone in a cell's size, so placements are unchanged. Set
`copper.cell_zones_under_planes = "keep"` to keep them all.

**Groups on the written board.** The generator writes one KiCad group per
module sheet, a stamped cell's group nested inside its module's, so
selecting any part of the module drags its sub-modules with it. Groups on
the written board are one level: each nested group is lifted to the top
level, whole, and a module keeps its own parts as a group of their own; the run says `groups  power: cell(s)
power.buck, power.ldo lifted to the top level`. A
group left empty (a module sheet's that held only its cells) is removed.
`write.split_groups = "split"` also takes out of a group the parts the
script places by steps of their own (a group it did not place whole);
`"keep"` writes every group as generated.

```python
board.group(name, items, why="")
```

writes a top-level KiCad group called `name` holding `items`, `Part`s, so a
hand placement moves the set as one; it places nothing. Groups on the board
are one level (KiCad makes a nested group entered before anything in it
moves): a `Cell` is refused, it is a group of its own. A name another group
or cell has, or a part already in a declared group (or named twice), is
refused where it is declared; a part of a cell the script places whole is
refused before the search (group the cell). The run says `groups  <name>
written: N part(s) (<why>)`.

**Layers a module's board does not have.** A module fragment is a two-layer
board, and KiCad saves a zone on the layers its board has: a keepout declared
on every layer, or on In1 and In2, would save as F and B and arrive in a
four-layer parent unable to keep the inner pours out. So the declaration
travels in the zone name, the one thing that survives the save and the stamp.
A keepout on every copper layer is written `keepout <name> [*.Cu]`; one on
layers its board lacks lists them, `keepout shield [In1.Cu,In2.Cu]`; one on
layers its board has needs no marker. The board that stamps the module reads
the declaration, honours it on every layer it has, and widens the zone to match
so KiCad's filler and DRC honour it too. A layer that cannot be honoured is a
finding: on the module, where it is recorded but holds nothing, and on a
parent that lacks it as well. A parent need not restate a module's clearance.

**What may enter.** `allow=` takes parts and nets, and they mean different
things: a `Part` or `Cell` may SIT inside, a `Net` may RUN through. Naming a
net does not admit the parts that carry it, which is the point - an antenna's
clearance holds its own matching network and every one of those parts carries
GND.

`max_height=` (a keepout that excludes parts) admits every part no taller,
by its `Pm.Height` field (`1.1mm`): the room a case leaves over a region,
said once, where naming the short parts in `allow=` goes stale when a part is
added or swapped. A part with no `Pm.Height` counts as taller; the refusal
names each part too tall or with no height. A cell meets a keepout member by
member: each member is let in by its own name in `allow=` or its own height,
and the cell is refused only when a member that is not let in
sits over the region (the refusal names it: `its member L1 sits in the
reservation for ...: L1 is 1.8 mm`), so a rigid cell may cross a height band
with its low members. `Cell(...)` in `allow=` names every member. The cell's
own tracks and pours are judged only by a keepout that excludes copper
(`"tracks"`, `"fill"`, `"vias"` or `"pads"`), and there are let in only with
every member; a parts-only keepout leaves them be. `board.height_of(part)` and
`placemat parts` give a part's height.

**When it is settled.** With the firm items, in dependency order, so a
clearance placed from a connector waits for that connector. A keepout placed
from a searched item is refused, naming it.

**What it costs.** `board.plane()` is untouched: the rule area keeps the fill
out, and DRC and the router judge by it. A `pour`, `track` or `via` crossing a
keepout ON A LAYER IT COVERS is a finding, because each keeps exactly the shape
or the position it was given.

**Who honours it.** KiCad's filler, KiCad's DRC and the router all read the
rule area placemat writes. The router's part is checked, not assumed: every
route compares the copper the router laid against the keepouts on the board it
was given, and anything inside a region that forbids it is printed and kept in
`route.json` under `keepout_breaches`. `allow=` is placemat's own: a KiCad rule
area has no per-net exemption, so KiCad's DRC reports an allowed net's copper
inside the region as `items_not_allowed`, and the router keeps that net out
too. Draw an allowed net's copper in the script, where the allowance holds, and
expect those DRC items.

## Boards of any shape

An outline is a closed path of straight legs and arcs. The first element is
where it starts; each one after it is a point (a straight leg to it) or an
`Arc(to=, via=)` that curves through a point; it closes back to the start.
Three points fix a circle and the way round it, so an arc needs no flag for
which way it bulges. `holes=` are cutouts (above), each a path of its own.
Use this when the board's EDGE is not a rectangle or a circle; a hole in an
otherwise ordinary board is `holes=` on `size()` or `disc()`.

```python
board.outline([(0, 40), (0, 20), Arc(to=(40, 20), via=(20, 0)), (40, 40)])   # a square with a rounded top
board.outline(SHELL, holes=[SHAFT])                        # and a cutout through it

top = board.edge(facing=Edge.NORTH)                        # the stretch of edge that faces north
board.place(J, at=OnEdge(top, along=Along.MID))            # reach at the keep-in, turned to the edge there
board.place(J, at=OnEdge(top, along=8.0))                  # 8 mm along the run from its start
board.place(TP, at=OnEdge(top))                            # slides along that run to the room left
board.row([L1, L2, L3], top, align=Along.MID)               # a row that turns with the edge
for run in board.edges(facing=Edge.EAST, within=10.0): ...  # every stretch facing that way
tip = board.edge(facing=Edge.SOUTH, outermost=True)        # of several facing south, the one furthest south
```

**A side is chosen, not named.** `board.edges(facing=, within=45.0)` returns
the stretches of the outline whose outward side points within `within`
degrees of a bearing (or an `Edge`), in the order the path runs.
`board.edge(...)` returns the one, and raises when none or several match:
several is a real question - a notch in the top edge has a floor that faces
north as much as the top does - so the script narrows `within`, picks from
`edges()`, or passes `outermost=True` for the run whose middle lies furthest
out that way (a tab or an arm's tip beyond the shoulders beside it; two level
at the furthest still raise). Stretches that face the same way and run into each other come
back as ONE run, so a rounded corner belongs to the side it flows into;
narrow `within` to get the flat part alone. A shaped board refuses a named
`Edge`, because "the north edge" is no longer one thing.

**A run** carries `.length`, `.facing`, `.straight`, `.at(along)` (the point
and the bearing the board faces there), `.project(point)` and
`.curvature(along)`. On a run, `along` is length from the run's start: a
number in mm, `Along.START/MID/END`, `Fraction(f)` of it, or a reference,
which lands at the nearest place on the run. (On a plain `Edge` a number
still means a coordinate, as it always did.)

**Placed against a curve**, an item's reach is held at the keep-in from the
edge and it is turned so its outward side follows the local normal, so a row
along a rounded top fans with the curve. A row along a run takes `gap=`,
`start=`, `align=Along.MID/END` (also "centre"/"center"/"end"), `rotation=`
and `overhang=`; the anchors that only mean something on a straight side
(`line=`, `behind=`, `before=`, `after=`, `centre=`, `end=`) are refused.
Claims on a curve are
spaced by how much the edge bends under them - the items sit inboard, where
the same angle spans less edge - and are left the rounding two courtyards
may touch by, since round a curve two claims can only ever meet at a point.

**The arithmetic is done on a flattened copy** of the outline (chords within
0.02 mm of the true curve), so a part held at the keep-in can be that much
further in than the real arc would need. Edge.Cuts gets the true arcs.

## Round boards

A circle has no sides, so a disc takes no `Edge` and no `row`: it refuses
both and says what to use instead. Everything else - links, faces, labels,
copper, rules - is unchanged, because those are said in parts and pads.

```python
board.disc(diameter=40.0, hole=6.0)                       # a 40 mm board round a 6 mm shaft
board.place(J, at=OnRim(Edge.EAST))                       # reach at the keep-in, turned to face out
board.place(J, at=OnRim(120.0, overhang=0.5))             # a face proud of the rim
board.place(TP, at=OnRim())                               # slides round the rim to the room left
board.place(SENSOR, at=OnBore(Edge.NORTH))                # at the bore's keep-in, facing the shaft
board.place(LED, at=Polar(16.0, 30.0))                    # body centre 16 mm out, 30 degrees round
board.place(R, at=Polar(16.0))                            # somewhere on that ring (one freedom)
board.place(R, at=Polar(None, Edge.EAST))                 # somewhere out along that spoke
ring = board.ring([L1, L2, L3], radius=16.0, start=Edge.NORTH)     # the row of a round board
board.ring(HOLES, radius=18.0, spread=True)               # four holes, evenly round the turn
board.ring([D1, D2], radius=None, start=90.0)             # at the rim, reach at the keep-in
```

**A bearing** is degrees clockwise from the top, the way a compass and a
clock read: 90 is east, 180 south. An `Edge` is the bearing of that side
(NORTH 0, EAST 90, SOUTH 180, WEST 270) and `Fraction(f)` is f of a full
turn, so the same names work on a round board as on a rectangle.

**What turns and what does not.** `OnRim` and `OnBore` turn the item so its
outward side (its `faces(outward=)`, else local +Y) points away from the
centre, or at the bore toward it; a free one is turned to wherever it slides
to. `Polar` is a coordinate, so it does not turn anything - pass `rotation=`
or use a ring.

**A ring** is `row()` for a circle: items in order clockwise from `start`,
each facing out, spaced by what they claim across the arc. They are held
apart at their INNER corners, where a claim is narrowest, so `gap=0` leaves
the rounding two courtyards may touch by. `spread=True` ignores the claims
and shares the whole turn evenly - four mounting holes at 90 degrees. With
no `radius` every item goes to the rim, its reach at the keep-in. The Ring
it returns carries `.radius`, `.angles`, `.depth`, `.start`, `.end` and
`.span`.

**A rim is an edge too.** `board.edge(facing=)` works on a disc, giving the
arc of the rim that faces that way, so `board.row(items, board.edge(facing=
Edge.NORTH))` puts a row along the top of a round board. `ring()` is the
better verb when the items go all the way round.

**A disc with cutouts is still a disc.** A slot in a round board does not make
it a shaped board: `OnRim`, `OnBore`, `ring()`, `board.radius` and
`board.bore` all still answer. Reach for `board.outline()` only when the
board's own EDGE is not a rectangle or a circle.

**A round verb needs a round board.** `OnRim`, `OnBore`, `ring(radius=None)`,
`board.radius` and `board.bore` are a disc's, and a shaped board refuses
them with the verb that does the same thing: `OnEdge(board.edge(facing=X))`
is where `OnRim(X)` would have put it, held at the keep-in and turned to
the edge the same way. `Polar` is a coordinate about `board.centre` by
default, so it works on any board; `about=` moves the centre - a `Location`,
an (x, y) pair, or a `Part`, `Cell` or `PadRef` resolved once the Polar
item itself is placed, the same as `ring(about=)`.

**The keep-in is radial.** The rim holds an item's furthest corner back by
`board.keep_in`; a bore holds its nearest point out by the same, and that is
an edge, not a corner, when the item straddles the bore. A plane inset from
the rim is a disc, and Edge.Cuts is written as a circle (two, with a bore),
so KiCad mills the arc and clips every fill to it.

## Links

```python
board.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), weight=LinkWeight.SHORT, limit_mm=2.0, why="bypass at its pin")
board.free_net(Net("LIMIT_IN"))      # its off-board run dwarfs the board: pulls nothing, seeds nothing
```
`weight` is `LinkWeight.FREE` (0), `DEFAULT` (1), `PREFER` (2), `SHORT` (8)
or any integer; 0 means the connection's length does not matter. Every
connection not declared weighs DEFAULT. A `limit_mm` is a bound: the run
reports each link's achieved length, and one over its limit is a finding
quoting `why`.

## Faces (a module's sides, declared once)

```python
board.faces(outward=Edge.NORTH, quiet=Edge.SOUTH, handoff=Edge.EAST, why="the plungers are pressed from the north")
```
In a module's own script: `outward` is the side that faces the board
edge (a connector mouth, the plungers of a switch row), `quiet` the side
to keep from aggressors, `handoff` the side its signals leave from, all
named at the cell's rotation 0. The fact is written into the fragment
as a text on User.Comments and rides with every stamped instance; a board's rows and edge
placements turn the cell by it, and a cell with none is turned as if
its outward side were local +Y, which the step says. `placemat faces
<fragment> outward=N` stamps the fact into an existing fragment.
`placemat show <board> <cell>` renders the cell alone in ISO from both
faces and from above and below and lists its pads by net and side: look before choosing a
rotation.

**A rotation that faces an edge or a bearing.** An edge, a row and a ring
turn their own items; a part placed by `Location`, `Centre` or `Pin`
does not, so a fixed part or cell whose face must still point somewhere
needs the turn given. `board.outward_rotation(item, edge)` reads the
item's declared `faces(outward=)` (a cell) or the generic rule (a part,
local +Y) and returns `(rotation, note)`: the rotation that turns that
side to `edge` - a board `Edge`, or a bearing in degrees on a round
board's rim - and a note, for a cell with no `faces()` declared, saying
it fell back to the generic rule (read it: that cell may not turn the way
you meant). A part always takes the generic rule, with no note.
`rotation=board.outward_rotation(item, Edge.WEST)[0]` is the computed
form of a hand-written rotation helper that reads a pad's direction and
works the turn out itself: it answers a rotation, the same way `extent`
and `pitch` answer a size, and is not a coordinate to place by.

## Rules

```python
board.rule(clearance=0.2, within=Cell("drv"), why="0.5 mm pitch cannot meet the class between adjacent pads")
board.rule(clearance=0.6, between=(Net("V48"), Net("GND")), why="48 V to ground")
board.rule(clearance=0.4, on=Net("V48"), why="the bus")
```
A rule is one scope and a `why`; it is written as a KiCad custom rule in
`layout.kicad_dru` beside the board, named by its `why`, and the run's
DRC judges by it. A plan with no rules removes the file.

## Blocks

```python
ldo = board.block(Part("ldo"), satellites=[(Part("cin"), "VIN"), (Part("cout"), "VOUT")])   # gap= only with a reason (default: courtyards touch)
board.place(ldo)                                                    # seeds from the links of its members
```
A block is a part and the satellites that sit at its pins: each satellite's
pad on the named net lands on that pin's axis `gap` beyond it, body
outward. The axis is the outward normal of the pin's pad row, so a
satellite at a pin near a corner stays in front of that pin. Where no spot
on the axis is legal (satellites wider than the pitch on neighbouring pins),
the satellite slides along the pin row, the least that clears, up to
`place.block_gap_reach`, and its step says how far it slid and which of the
anchor's pins it now stands in front of; one aimed at a pin another
satellite already sits at does not. A searched block is first laid out on its own, on an empty
board, at each rotation it may take: when none works, the finding says why
at once rather than after a scan of the whole board. A net names the anchor's FIRST pad carrying it; when several do (a
supply, a ground with thermal vias numbered into an exposed pad), name the
anchor's pad by number instead - `(Part("cdec"), 20)`, 20 being the
anchor's pad - and the satellite
sits by its own pad on that pad's net. A satellite with no spot says which
anchor pad it was aimed at. The block is laid out from the anchor's REAL pads at every
candidate, so its envelope is exact, and placed as one thing (after cells,
before loose parts). Its members appear as their own steps and placements.

**`board.place(block, at=...)`** takes every place a part does - `Location`,
`Centre`, a line (one axis free), `OnEdge` (with `along=` or without),
`OnRim`, `OnBore`, `Polar` (fixed, or with a freedom) - against the
ANCHOR: `at=OnEdge(Edge.WEST, along=Along.MID)` reaches the anchor at the
west keep-in with the whole block laid out from there. Only `Pin` is
refused: a block is placed by its anchor's body or edge, not by one of its
own pads.

## Copper vocabulary

Every copper call is named for the shape it leaves on the board:

| word | the shape on the board |
|---|---|
| track | one straight trace segment of a width, on one layer; `board.track` draws several end to end |
| via | a plated hole joining all copper layers at one point |
| pour | a filled polygon of exactly the shape given, on one layer; it never pulls back from other copper, so it is drawn where nothing foreign is - except `swallow_pads`, which both grows it over the same-net pads its outline touches and pulls it back from every other net's copper to the netclass clearance |
| zone | a filled area KiCad fills and refills, pulling back by the clearance round every foreign pad, track and via; what a plane is made of |
| plane | a zone covering the whole board (or an outline, or the box round named parts) on one or more layers, for a net that everything reaches by a via |
| bridge | a via, a short track on the opposite face passing under one or more tracks, and a via back: how a track gets past copper on its own layer without touching it |
| finger | a rectangular pour of a width along a centreline (a wide reach from a big pour to a pad), cut and bridged where a track crosses it |
| stitch | vias in a grid over a region (a cell, a pour or a keepout), at the via-to-via rule, clear of every other net's copper; `edge=True` rows them along the region's own outline instead |

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
right angle counting two), then the shortest, then (its own tie-break) the
45 at the pad end. `bend=Bend.START`/`Bend.END`/`Bend.BOTH` says which end
of every off-grid leg of the track takes the 45 instead, ahead of that
scoring; a leg already on the grid, or already a single 45, is unaffected.
So a track is best given only
its ends and the waypoints where it must go; the tool routes round what it
knows is there. Every right angle between axis legs is cut back `chamfer`
(default 1.0 mm) along both legs into two 45s; `chamfer=0` keeps it sharp. A tap
that must return is written as one chain: `..., (band, Y(pin)), pin,
(X(pin, -2), Y(pin, 2)), (band, Y(pin, 2)), ...`.

**Lane waypoints.** `Between(PadRef(a), PadRef(b))` is a point in the
middle of the gap between two pads - halfway between their facing edges,
centred across where they face each other - resolved once both are placed: the
gap must hold the track's own width plus its clearance to each pad's net,
or the declaration is a finding naming both pads. `Past(items, Edge.EAST,
across=None)` is a point the clearance off the `edge` side of some copper.
`items` are pads (`PadRef`/`CellPadRef`), vias (what `board.via()` or
`board.vias()` returns) and tracks (what `board.track()` returns), in any
mix. The edge is read off their combined copper box; the offset is half the
track's width plus the worst clearance, by net pair, from the track to any
of them. `across=` says where the point lies across the edge: a `PadRef` or
a via puts it on that pad's or via's centre line, an `Along` at that point
of the box's side (default `Along.MID`, the middle). The point waits for
its pads to be placed and its vias and tracks to be planned. A track whose
`Past` names a via that found no spot, or a track that was not drawn, is
not drawn, and the finding names both. Both are accepted wherever a track
point is.

`Past(items, Corner.NE)` holds a 45 off a corner of the same box (`Corner`
is `NE`, `NW`, `SE` or `SW`). The point is on the outward diagonal from
that corner, half the track's width plus the clearance from it, rounded
away from the items; a 45 through it across the diagonal (NW to SE for an
NE corner) passes the corner at the clearance. A corner fixes both axes, so
it takes no `across=`. The track's legs either side of the point take that
45 through it wherever the points either side allow one, ahead of `bend=`;
where they do not and the track passes the corner nearer than the
clearance, the finding names the corner.

```python
v = board.via(Net("SIG_N"), FreeSpot(near=PadRef(Part("j1"), 3)))
board.track(Net("SIG_P"), [PadRef(Part("j1"), 2), Past([v], Edge.SOUTH), PadRef(Part("j1"), 8)],
            layer=CopperLayer.F)                 # a U-turn a track's clearance under the via
board.track(Net("S_A"), [PadRef(Part("r_a"), 2), Past([PadRef(Part("r_b"), 2)], Corner.NE),
                         PadRef(Part("j1"), 1)], layer=CopperLayer.F)   # its 45 a clearance off r_b's pad corner
```

**Who bridges.** Where two tracks of different nets cross on one layer, the
lower `priority` passes under; at equal priority the shorter one does; a
track planned before the search (every endpoint decided) never yields to
copper planned after it. Only a track declared `bridge=True` may pass
under; a crossing where the track that should yield may not is a finding,
and both tracks are drawn as declared. The order of the declarations never
enters into it. Fingers always yield to tracks.

A script that needs a word of its own (a "corridor", a "spine") defines it
where it first uses it, in these terms.

## Copper calls

Copper is planned after placement, against the placed pads.

Points: `Location`, `PadRef(Part, int|net, land=None)`, `CellPadRef(Cell, net=|number=, ref_prefix=)`,
or `(x, y)` where either may be `X(ref, dx)` / `Y(ref, dy)`. `.offset(dx, dy)` on a ref.
A pad is named by its number (an int) or by the net on it (a str). A net that
several of the part's pads carry names the first of them in pad order, the
same pad in a `PadRef`, a `Pin`, a link and `board.part(x).pad(net)`; a
placement on it says which pad that was. Name the number to pick another.

```python
board.track(net, [p1, p2, ...], layer=CopperLayer.F, width=None, chamfer=None, bend=None, priority=Priority.DEFAULT, bridge=False)
board.via(net, at, drill=None, size=None, layers=None)                # at= a point; the board's via size unless given; layers= a span
board.via(net, at=FreeSpot(near=PadRef(...), radius=2.0))            # the nearest legal spot to a pad, joined to it by its tail
board.via(net, at=Past([PadRef(...), ...], Edge.SOUTH, across=None)) # its radius plus its clearance off the items' side
board.vias(net, pad=PadRef(...), pitch=None, size=None, drill=None, inset=0, layers=None)  # a pad filled with a grid of vias, turned with its part
board.vias(net, along=PadRef(...), count=N, pitch=None, size=None, drill=None, layers=None)  # a row out from a pad, along its escape axis
board.stitch(net, region, pitch=None, size=None, drill=None, edge=False, layers=None)  # vias in a grid over a cell, a pour or a keepout
board.pour(net, [p1, p2, p3, ...], layer=..., swallow_pads=False, stroke=None)  # filled polygon; stroke= its outline's width (copper.pour_stroke)
board.pour(net, [PadRef(a), PadRef(b), PadRef(c)], layer=..., swallow_pads=True, cover=None)  # over the pads' copper
board.pour(net, [PadRef(a), PadRef(b)], layer=..., swallow_pads=True, width=None)  # the neck between two pads
board.plane(net, layers=(CopperLayer.IN1,), outline=None, inset=0.4)  # zone(s), whole board or outline
board.plane(net, layers=(CopperLayer.IN1,), over=[Part(...), Cell(...)], margin=0.0)  # zone(s) over named items
board.plane(..., clearance=None, min_thickness=None, solid_pads=True, chamfer=None)  # the zone's pullback and minimum width (copper.plane_*), pads joined solid or by thermal spokes, the frame outline's corner chamfer
board.finger(net, layer=, from_=point, to=point, width=, bridge_width=None)  # pour along a centreline, cut and bridged at tracks; width= a number or a PadRef
```
All take `priority=`, which decides only who passes under where two tracks
of different nets cross. WHEN a piece of copper is planned is derived, not
declared: copper whose every endpoint belongs to something nothing will move
- a fixed or edge part, or plain coordinates - is planned before the search
and becomes an obstacle to it, so `board.via(net, Location(x, y))` reserves
its spot with nothing to remember. Copper naming a searched part is planned
after the search, once its shape is known. A via at a searched part's pad
(`board.via(net, PadRef(...))`, or off it by `.local()`) goes with the part
through its search: the part, or the cell or block holding it, carries the
via's ring on every layer and its hole, so it lands where the via clears the
other face's copper and holes. A copper finding against a via names it as
one: "via GND at (x, y) is ...". A finding against a declared `track()`
names the conflicting segment by its ends and layer, not its net alone:
"track SW (x, y)-(x, y) is ...". When that segment is the 45 a corner's
`chamfer` cut, not a leg the script asked for, the finding says so and
points at the fix: "...; the 45 of its chamfer at (x, y); a smaller
chamfer= there keeps clear".

**Carried vias give way.** A carried via is one a part or a cell brings
with it: a via at a searched part's pad, as above, or one of a stamped
cell's own. Its tail is the one track of the same owner and net that ends
at its centre; a via that two of the cell's tracks meet, or whose track
runs on to another of its vias, is part of a route and stays as drawn.
Where a carried via meets another net's copper, on either face, the search
does not refuse the spot at once. The via tries, in turn:

- to share a via of its net from any other item, on either face, within
  `place.via_share` (1.0 mm): the via is taken out and a straight tail at
  the net's width joins its pad (its old tail's far end, or where it stood)
  to that via on the via's own face. The tail must clear every other net's
  copper. A via of the net already on its spot needs no tail. The via
  shared then stays: where a later item meets it, it does not give way,
  and the refusal says which via shares it. When its own item is placed
  again, the vias that shared it go back as drawn;
- to move up to `place.via_move` (0.5 mm), searched on a
  `place.via_move_step` (0.05 mm) grid nearest first, to a spot clear of
  every other net's copper on every layer and of every hole, its tail
  redrawn from its pad. A via inside its pad moves only within that pad;
- a drop only (a via of a net the board declares a `plane()` for): to be
  dropped, while each of the item's pads keeps at least `place.drops_keep`
  (0.5) of its drops, rounded up and never fewer than one. A shared drop
  counts as kept.

If none works the spot is refused, and the refusal names the via and why
each way failed: "via GND at (19.10, 21.90) is 0.00 mm from S copper on
B.Cu (needs 0.20); it cannot give way: no GND via within 1.00 mm to share,
no spot within 0.50 mm is clear, GND is not a plane net, so it is no drop".
Each way has a cost the search adds to the spot's score -
`score.via_share` (1), `score.via_move` (2), `score.via_drop` (10) - so it
prefers spots where the vias stay as drawn; a nearest-first search takes a
spot where they give way only when no spot has them as drawn. A via
already placed does the same for an item placed later whose own copper
meets it, its owner otherwise untouched and its keep share still held. A
firm item's carried vias, and a rider's, give way where it is put. An item
searched along an edge, a run or a rim takes the nearest slot where its
vias stay as drawn, and only when there is none the nearest where they
give way. A block's members are judged as drawn. The write moves or
removes a cell's via on the board and draws the tails; a via declared at a
pad is drawn where it went. What gave way is a note on the owner's step
and a finding of kind `vias`, per owner and net: "m: 6 GND vias shared, 2
moved up to 0.25 mm, 1 dropped under R9".

**A plane over named parts.** `board.plane(net, layers, over=[Part(...),
Cell(...)], margin=0.0)` draws the zone over the box round those items'
drawn envelopes - the region `board.keepout(item)` takes, a footprint's
copper graphics included - where they were placed, grown by `margin` and
clipped to the frame less `inset`. It waits for the items to be placed, so
a part placed by `Beside` outside the others' box is still under it.
`over=` and `outline=` are not given together. A part in the group whose
copper the fill must stay off (a winding) takes
`board.keepout(Part(...), name, excludes=(Forbid.FILL,), why=...)`:

```python
board.plane(Net("GND"), layers=(CopperLayer.IN1,), over=[Cell("driver"), Part("c_bulk")], margin=0.5)
```

**A via where one fits.** `FreeSpot(near=PadRef(...), radius=2.0, step=0.05,
layer=None, in_pad=False)` is the nearest point to the pad where a via clears
every other net's copper, every drilled hole, every keepout that forbids vias
and the board edge, and where a tail on `layer` (the pad's own by default)
reaches it at 0, 45 or 90 degrees - a 45 from the pad, then straight, as
`board.track()` draws a leg. It is found when the pad's part is placed, against the
copper planned before it, so a second via near the same pad lands clear of the
first. The via stays out of its own pad unless `in_pad=True`: an SMD pad's
centre passes every other rule, and a via in a pad needs plugging. A search
with nowhere to go is a finding carrying why every nearer spot failed, and no
via is drawn.

The via is drawn with the tail it was judged by, from the pad's
centre on that layer at the net class's track width, or the pad's narrower
side when that is less; `tail=False` draws the
via alone, and a via in the pad has none. `board.via()` returns the via,
and a `board.track()` may end on it - `v = board.via(GND, FreeSpot(...))`,
then `board.track(GND, [v, PadRef(...)], layer=CopperLayer.B)` - so a searched part's
via is joined on wherever the part lands. A track through a via that found
no spot is not drawn, and the finding says so.

**A via past copper.** `board.via(net, at=Past(items, Edge.SOUTH,
across=PadRef(...)))` stands the via off the items' `edge` side by its
radius plus the worst clearance, by net pair, to any of them: pads, vias
and tracks, as a track's `Past` takes (Lane waypoints). `across=` a pad
puts it on that pad's axis. A track may end on it, and a later `Past` may
name it, so a row of vias under a connector's contact tips and a track's
U-turn under the vias are said without a coordinate:

```python
tips = [PadRef(Part("j1"), n) for n in range(1, 13)]
v = [board.via(Net("SIG_N"), at=Past(tips, Edge.SOUTH, across=PadRef(Part("j1"), n))) for n in (4, 9)]
board.track(Net("SIG_P"), [PadRef(Part("j1"), 5), Past(v, Edge.SOUTH), PadRef(Part("j1"), 8)],
            layer=CopperLayer.F)
```

**A pad filled with vias.** `board.vias(net, PadRef(...))` fills a power or
exposed pad with a square grid of vias, placed once the pad's part is: in the
part's own frame (it turns with the part), centred on each of the pin's
lands, `pitch` apart (by default the closest the board's hole-to-hole rule
allows, never closer than a via's size), keeping each via whose copper,
grown by `inset`, lies wholly in its land and clears every other net's copper
on every layer (placed, and planned before it: tracks, tails, vias), every
other hole (a part's, and every via on the board: a stamped cell's too) by
the hole-to-hole rule and an unplated one by the hole
clearance, the board edge and keepouts that forbid vias. The net class's via
by default (`board.via` takes the board's). A through land of the pin already
has its hole and is not filled. A pad
no via fits in is a finding; a `pitch` under the hole-to-hole rule is refused
when declared. The step says the vias are in the pad: filled or plugged at
the fab.

**Vias in a row.** `board.vias(net, along=PadRef(...), count=N)` draws N
vias out from a pad along its escape axis (the outward normal of the pad
row it sits in, or the ray from the part's body centre when the row does
not decide one) at the via-to-via rule (by default the larger of the via's
own size and a drilled hole plus the hole-to-hole rule), the first clear of
the pad's own copper, and a track at the net's width (as a via's tail)
from the pad to the farthest via joins them. A via the row cannot fit, or
whose tail cannot reach it - the edge, another net's copper, a hole - is a
finding, and the row stops there. A track given the value it returns as
a point ends on the row's farthest via, as on one `board.via()`; a `Past`
naming it is held off every via of the row and its tail.
`pad=`/`along=` are exclusive: one call, a grid over a pad or a row along
its axis.

**Stitching.** `board.stitch(net, region, pitch=None)` fills `region` - a
`Cell`, the value `board.pour()` returns, or a keepout's name - with vias
in a grid at `pitch` (by default the via-to-via rule), each one wholly
inside the region and clear of every other net's copper, hole, keepout and
the board edge. Resolved once the region itself is: after the cell is
placed, the pour is drawn, or the keepout is settled. A pour region must be
`net`'s own net; a keepout whose `excludes` forbids vias (the default) and
does not `allow` this net is refused when declared, naming the exclusion,
rather than planning nothing and saying no via fit.

`edge=True` rows the vias along `region`'s own outline instead of filling
its inside: `pitch` apart along each side, a via's own radius plus its
netclass clearance in from the edge, going all the way round. For stitching
a ground pour's or a shield keepout's border, not its middle.

**A via's layer span.** For a fab that makes blind or micro vias,
`layers=(CopperLayer.B, CopperLayer.IN4)` on `board.via()`, `board.vias()`
(both forms) or `board.stitch()` names the two ends of the via's span. The
via is copper, and a hole, on those layers and the ones between them only,
and is judged there alone: a far-face pad of another net over a B-In4 via
is no conflict, and two vias whose spans share no layer keep no
hole-to-hole rule between them (KiCad's DRC checks none). It is written as
KiCad's micro via when the span is an outer face and the layer next to it,
and as a blind (from an outer face) or buried via otherwise. A micro via's
drill is `copper.microvia_drill` (0.1) unless `drill=` says. The default is
every layer, the through via; a span of every layer the board has is one
too. A layer the board does not have, or a span of one layer, is refused
when declared. A via whose span misses the layer of what it joins - a
grid's pad, a row's or a `FreeSpot`'s tail - is not drawn, and the finding
says so. A cell flipped to the other face mirrors a via that reaches a face
(B-In4 becomes F-In1) and keeps a buried one on its layers ("A cell's flip
keeps its inner layers", under Placement); a via declared at a pad is
spanned where the part lands. A fragment built with
spans carries them into the parent, which reads each via's layers.

These vias cost more, so each type is refused unless the fab profile
allows it: `"via": {"allow_micro": true, "allow_blind": true,
"allow_buried": true}` in `fab-profile.json`, each only when the fab makes
it and its cost is accepted. With none allowed (the default) a span is
refused when declared, naming the type and the key that allows it, and a
stamped fragment carrying such a via fails the run, naming its cell. Look
for another way first: a through via moved, shared or dropped (the give-way
above), or a field thinned with `drops=`.

```python
board.vias(Net("GND"), PadRef(Part("u3"), 17), layers=(CopperLayer.B, CopperLayer.IN4))
```

**A pour between two pads.** `board.pour(net, [PadRef(a), PadRef(b)],
swallow_pads=True)` with exactly two pads draws the neck between them - a
rectangle along their centreline, as wide as the narrower pad measured
across the run, unless `width=` says otherwise - instead of needing a
third point.

**What a pour over pads covers.** `cover=` (`Cover`) says what corners
that name pads cover. `Cover.HULL`, the default for a `swallow_pads` pour
whose corners are all pads (three or more), is the convex hull of those
pads' copper, every land's corners; `Cover.BOX` is the box round it;
`Cover.CENTRES`, the default otherwise, is the polygon through the points
as given, a pad at its centre - over three pads in a row that is a line,
and the pour is as thin as its stroke. A plain point among the corners
counts as given under HULL and BOX too.

**A swallowing pour pulls back too.** `swallow_pads` both grows the pour
over the same-net pads its outline touches and pulls it back, to the
netclass clearance (the larger of the two nets' classes; a `board.rule`
clearance is not applied to it), from every other net's copper on its layer - every
pad, at its real shape rather than its bounding box; every track, via and
pour this run plans (two swallow pours settle as KiCad's zone priority
does: the one the plan draws first - the one declared first, when both
wait on the same placements - keeps its fill, and the later one keeps the clearance from it as
written); and every track, via and poly already on the board
before this run (a stamped cell's own), as a zone fill does. A pad with no
net, or on a net this board's geometry does not know, keeps the board's
own default clearance. A piece the pull-back cuts off that no longer
touches a named or swallowed pad is dropped; if that leaves a named pad
joined to nothing, it is a finding naming the pad. Only a same-net pad
counts as one of the pour's own pads: a polygon corner that names another
net's pad shapes the outline near it and is never swallowed or checked as
joined. A pour without `swallow_pads` keeps exactly the shape it is given,
still.

The pull-back is applied when the board is written, so the plan does not
report a `swallow_pads` pour's clearance to other nets; the declared shape
still occupies the board, an obstacle for copper planned after it.

**A finger as wide as a pad.** `board.finger(net, from_=, to=, width=PadRef(...))`
runs the finger as wide as that pad measured across the run, instead of a
fixed number.

**Pairs.** Two nets drawn together at a gap along one centreline, the way
KiCad's differential tool does:

```python
board.pair(BUS_P, BUS_N, [(padP, padN), (x, y), (x, y2), (padP2, padN2)], layer=CopperLayer.B)
```
The path starts and ends with a (P pad, N pad) tuple; the points between,
two or more, are the centreline. Given the two pad pairs alone -
`board.pair(P, N, [(padP, padN), (padP2, padN2)], layer=CopperLayer.B)` - the pair
finds its own: from a pitch (width plus gap) out of the first pair's middle
to a pitch short of the last's, octilinear as a track's leg; pad pairs too
close for that are a finding asking for the points. Width and gap come from the P net's class
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
board.label(Part("j_out"), "LOAD", side=Edge.SOUTH, knockout=True)              # gap= only with a reason (default 0)
board.label(Cell("power"), "POWER", side=Edge.NORTH, align=Along.START, size=1.2)
board.label(PadRef(Part("jp1"), 1), "1", side=Edge.WEST, gap=0.3, size=0.6)
board.label(Part("j_bus"), "BUS", side=Edge.EAST, rotation=90, why="reads along the edge it plugs into")
board.label([SW_BOOT, SW_RUN, LED], ["BOOT", "RUN", "MCU"], side=Edge.SOUTH, knockout=True)   # one line for a row
board.label([PadRef(J, 1), PadRef(J, 2)], ["GND", "CLK"], side=Edge.NORTH, line=J)           # pin labels clear of the part
```
Text `gap` off `side` of the item's reach (or of one pad), on the item's
own face (mirrored on the back), aligned `Along.MID` (also "centre"/
"center"), `Along.START` (also "start", the west or north end of that
side) or `Along.END` (also "end"); `rotation=90` runs it up the page.
A list of items with a list of texts is one label each on ONE line,
`gap` off the deepest of them, each over its own item: the labels of a
row of parts of different heights read as a row; `line=` names the part
or cell whose reach that line stands off instead, so labels of pads sit
over their pads but past the part's outline;
`knockout` cuts it out of a filled box, which reads better over a busy
board. `size` and `thickness` default to 1.0 and 0.15 mm. A label is
worked out the moment its item is placed and the text's own box on
its face is reserved: nothing placed later lands on it, and a firm
item declared on top of it is a collision that stops the run.
`reserve=False` keeps the label out of the way of placement and only
reports what lands on it. Mark what a user handles:
every connector, jumper, switch and LED, by what it does, not its refdes.

## Layers and faces

A flip to `Face.BACK` is described under Placement ("A flip to the back").
`CopperLayer.F / IN1 .. IN30 / B` (the faces and every inner layer KiCad
allows; a board uses as many as its stackup has), `Face.FRONT / BACK`,
`Edge.NORTH / SOUTH / EAST / WEST`.

## Commands

```
placemat run <script> [--label L] [--fresh] [--no-reuse] [--no-render] [--no-drc] [-v | -q] [--json] [--keep-going] [--route [--route-full] [--route-exclude NET ...]]
placemat route <layout.kicad_pcb | script> [--exclude NET ...] [--islands NET[=WIDTH] ...] [--layers L ...] [--full] [--iterations N] [--out DIR] [--json]
               [--adopt NET ... | --adopt-all] [--partial] [--no-lock]
placemat routes <script> [--release NET ... | --release-all]
placemat impact <run-dir-or-json> <run-dir-or-json> [--board DIR]
placemat drc <layout.kicad_pcb> [--json]
placemat measure <layout.kicad_pcb | script | footprint.kicad_mod> [cell-or-part ...] [--pads] [--envelope] [--models] [--copper [NET ...]] [--keepouts [NAME ...] [--near MM]] [--labels] [--outline] [--json]
placemat parts <layout.kicad_pcb | script> [--field NAME ...] [--fragments] [--json]
placemat nets <layout.kicad_pcb | script> [--sort COLUMN] [--net NET ...] [--inst] [--json]
placemat datasheet <pdf> [--show PAGE|TOPIC] [--read] [--no-ocr] [--out DIR] [--dpi N] [--json]
placemat datasheet check <pdf> <footprint.kicad_mod> [--pitch F] [--pad WxH] [--pads N] [--span F] [--tol F] [--json]
placemat occupancy <layout.kicad_pcb | script> (--at X,Y | --box X0,Y0,X1,Y1 | --via-near PART.PAD | --corridor A B)
                   [--net N] [--size D] [--drill H] [--layer L] [--radius R] [--step S] [--in-pad] [--json]
                   [--width W] [--margin MM] [--ignore-kept]
placemat show <layout.kicad_pcb | script> <cell | part> [--out DIR]
placemat layer <layout.kicad_pcb | script> <LAYER> [--out FILE] [--json]
placemat faces <module layout.kicad_pcb> outward=N [quiet=S] [handoff=E]
placemat check <layout.kicad_pcb | script> [--ambient C] [--keep-out MM] [--rise C] [--copper-oz OZ] [--limit CHECK=VALUE ...] [--json]
placemat settings [<script-or-board-dir>] [--json]
```

`drc` runs kicad-cli's DRC on a board and prints the counts by kind, the
airwires, and each violation that fails the board with where it is and the
items it is between (the first twenty; `--json` gives them all as
`violations`, each with its kind, severity, KiCad's description and its
items' descriptions and positions, and every open connection as
`unconnected_items`, by net). An item on a part carries the part's instance
path beside KiCad's refdes (`instance`; in the text, in brackets).

`measure` is the geometry query. Given a board it prints, per part, the
instance, refdes, value, face, rotation and origin, the `body`, `courtyard` and
`physical` boxes, its drawn envelope and the layer setting each side, how near
its courtyard and copper come to the board's edge, each 3D model's file,
offset, rotation and scale, and a `footprint:` line when its courtyard lies
inside its own silk or equals its fab body. `--json` gives each box by its
edges too, as `boxes` (left, top, right, bottom; `fab` among them when the
part draws fab graphics), and the models as `models`. `--envelope` adds, for
each side of the drawn envelope, the one item that sets it: its layer, which
of that layer's items it is (a pad by number) and its box (`--json`:
`envelope_items`). `--models` reads each part's STEP model (a `.wrl` path
is tried as `.step`; a model embedded in the board is skipped), places its
box as KiCad's 3D view does (scaled, turned by its angles, offset) and
says when it sits off its pads or matches the fab outline only turned 90
degrees - a model that lost its turn, which otherwise shows only in the
render (`--json`: `model_checks`). `--copper [NET ...]` lists instead every track segment
of those nets (all when none is named) - layer, width, both ends and what
each lands on (a pad as REF.NUMBER, a via, another track, or `-`), length
and bearing, `off 0/45/90` on a leg at any other angle - then the vias.
Given the routed copy (`.placemat/route/.../*.kicad_pcb`) it shows where the
router put each net's copper.
`--keepouts [NAME ...]` lists, per rule area (all when none is named) and
what it excludes, each part within `--near` mm (default 1) on a face it
covers: the gap from its physical box and from its courtyard to the area,
or `overlaps` - so a keepout DRC finding a courtyard causes is told from a
body inside the area.
`--pads`
adds every pad's number, net, layers, drill, centre in the board frame, **the
box round its copper** - not the anchor size, which for a custom pad is not the
copper - and the mask and paste layers it opens, and under a custom pad
(an exposed pad with lead fingers) its copper outline, since its box hides
its shape; `--json` gives each pad's copper outline as polygons and says
which are custom. Measured on a `.kicad_mod`, the outline is in the
footprint's own frame, to set beside a datasheet's drawing. Given a path ending `.kicad_mod` it reads that
footprint with no board at all, in the footprint's own frame, and prints the
file's SHA-256 so two variants of a part can be told apart; a pad read that way
reports an attribute rather than layers, because a footprint has no stackup.
`--labels` lists the board's own silk texts instead - every `board.label()`
text and a stamped cell's - with face, cell, the box KiCad draws, position,
height, stroke, angle and mirroring, so a panel can be sized round them and
another board's marks matched; then its silk graphics (an arrow, a mark),
each with its kind, face, cell, box and stroke.

`layer` draws one copper layer of a board file as SVG - zone fills
(translucent) and outlines (dashed), pads, tracks and vias, each net in its
own colour with a legend - and lists each track that runs inside another
net's zone outline on that layer: the router routes round a zone's last
fill, not its outline, so such a track cuts the pour apart while DRC
passes, KiCad refilling round it. `--json` gives the SVG's path, the zone
nets and the crossings. It reads any board file: the routed copy's layers
too.

`preview` places the board as a run does - the cached generation, the
previous run's steps replayed - and draws it, without writing the board,
running DRC or rendering it:

```
placemat preview <script> [--svg] [--face front|back|both] [--out DIR]
                 [--zoom X0,Y0,X1,Y1 | --around PART [--margin MM]]
                 [--no-heat] [--no-links] [--no-copper] [--no-tags]
```

It writes `preview.svg` and, through `[preview] converter`, `preview.png` at
`[preview] px_per_mm`, under `<board>/.placemat/preview/`, and prints the
paths, the step counts, what it reused, the congestion line and the findings.
Each face is a panel, the back mirrored as seen from the front, on a
millimetre grid: the board, keepouts and reservations, each part's pads,
courtyard, fab body, silk and reference, planned copper, declared links
(green within their limit, red over it, with their lengths), parts that took
a pocket, the congestion heat map with its worst cell, and a column with the
parts not placed and why. `--zoom` and `--around` draw one region of each
face; `--no-tags` leaves the annotation tags off the picture, which at a
close look cover small parts, and still prints their text. A preview writes
no run record; `placemat run` is still what checks the
board. It also prints the resolution a model reading the PNG sees: an
image's long edge is scaled to about 1568 px before a model reads it, so a
whole board comes through at a few pixels a millimetre.

`parts` answers "what are the parts called, and where are they": one line per
footprint with its cell, origin (x, y), rotation, courtyard area, pin count and
value (`--json` adds the body centre and the nets). The area and the pin count are what
the placement rank is worked out from, so the listing also explains the order
things went down in. It also warns for a placed part carrying none of
`[parts] order_fields` (default `Lcsc`, `LCSC`, `Mpn`, `MPN`) present and
non-empty - "no order number: R40 (power.r_fb)" - so a board is not sent
for assembly with a part nobody can buy; a part marked do-not-populate is
never warned about. `--json` gives the same lines as `warnings`. The last
line counts the parts, the pads and the solder joints an assembler places -
the pads of every part it populates, do-not-populate and board-only parts
left out (`--json`: `totals`). `--fragments` adds the fragment each part
was stamped from, read from the generator's `layout.log` beside the board:
`-` for a part the generator placed itself, `?` for one the log does not
name.

`nets` answers "which nets matter": one row per net with at least two pads -
its pad count and the parts it joins (refs, or instance paths with `--inst`);
its span, the minimum spanning tree over its pads' centres in mm - how far
the net has to reach, whatever is routed; its routed length, the sum of its
tracks' and arcs' own lengths (pcbnew's `GetLength()`, an arc's real path,
not its chord); its detour, routed length over span (`-` when the net
carries no track); its via count and the copper layers its tracks use; and
whether a pour serves it instead of the router (`plane_nets_of`, as `route`
leaves a plane net unrouted). Rows are sorted by span, largest first,
by default; `--sort` takes any column name (`net`, `pads`, `parts`, `span`,
`routed`, `detour`, `vias`, `layers`, `pour`), largest first there too (a
list-valued column by how many, an unrouted net's `-` detour last), `net`
A to Z. `--net` narrows the rows to the nets named. It is the table to
choose from which nets to declare as copper rather than leave to the
router.

All three take `--json`. Reach for these before grepping a `.kicad_mod` or
loading pcbnew in a scratch script.

`datasheet` ranks a PDF's pages against four topics - land pattern, package
dimensions, layout rules and pin map - and prints the evidence behind each
ranking, so the ranking can be judged rather than trusted. `--show p7` renders
that page to a PNG and prints its text with positions; `--show land` resolves
the topic through the index first. Measured over 67 datasheets, a keyword list
alone names a land pattern on half of them, so the geometry counts too: a page
holding a row of identical rectangles is a pad row whether or not it says so.
A datasheet whose every dimension is an outlined curve carries no text at all,
and `--show` is the answer for those.
It shells out to mupdf and poppler; `tesseract` is used when installed.

`--read` prints the facts the sheet could be made to yield - its unit, its
scale, every dimension on it and the headings that name a topic - each with the
page, the position, the channel that read it and that channel's confidence. A
value that could not be sourced is absent rather than guessed.

`check` compares a `.kicad_mod` against what the sheet is said to require.
placemat cannot tell which decimal on a drawing is the pitch, so the values are
supplied as flags; what it does automatically is measure the footprint and say
whether the number you supplied appears on the sheet at all, which is what
makes an override safe rather than blind. Every check is reported including the
ones nobody supplied a value for, because a check missing from a report reads
as one that passed. Exit 1 when any check disagrees.

```
check   part.kicad_mod against part.pdf
check     pitch  0.5        0.5        ok        p1 (498,1828) ocr conf 88
check     pad    0.3 x 1.3  0.3 x 1.3  ok        not on the page
check     pads   24         18         MISMATCH  not on the page
check     span   -          9.86       unchecked
check     1 of 3 checks disagree
```

`occupancy` answers what is at a point and where a via can go, on the board as
it stands - routed or not. `--at` names the copper under a point on each layer
and the nearest copper of another net, then whether a via fits there and why
not. `--box` counts the copper in a box by net and kind on each layer.
`--via-near` searches outward from a pad, in a fixed order so the same board
gives the same answer, for the nearest spot a via of the pad's net clears
every other net's pads, tracks, vias and graphic copper, every hole, every
keepout forbidding vias and the edge, and can be reached by a straight tail;
it prints the spot and why every nearer spot failed, and exits 1 when there is
nowhere. Another net's pour is not an obstacle: KiCad refills it round the new
via, so the answer names the pour that would give way instead.

`--corridor A B` (each `PART.PAD`) finds the clear octilinear paths on
`--layer` from pad A to pad B for a track of `--width` on `--net` (default:
A's net): every other net's copper that reaches the layer keeps its
netclass clearance - pads, vias, tracks, foreign zones (unlike a via, a
zone does not give way to a track) and cutouts - and a rule area forbidding
tracks on the layer is an obstacle too, unless its `allow=` names the net.
It prints the shortest path as its corner points - the pads' own centres at
each end, not the grid node the search snapped them to - with its length
and turn count, and up to two more that keep at least a track-and-clearance
gap from it and each other away from the pads themselves (not the same
corridor shifted a cell); with none, the blockers across the narrowest cut
between A and B, each named (a pad, a via, a track of a net, a zone, a
cutout, a keepout). The search is one occupancy built on a 0.1 mm grid -
the router's default - over the box round A and B grown by `--margin`
(default 10 mm), built once and searched, not a scan repeated per
candidate the way `--via-near` is. `--ignore-kept` leaves out the tracks
and vias of a script's kept routes (`routes.json`; a layout script only,
not a bare board), matched by their anchors as well as their outline, to
see the room a re-route would have.

A page carrying almost no text of its own is read off its render with
`tesseract` when it is installed; `--no-ocr` turns that off. It costs about a
second and a half a page and only runs on pages under 200 characters.

`check` reads the `Pm.*` facts the capture put on its parts (the
`references/capture.md` says which) and reports hot loop area, switch node
copper, keep-out distance, crossings under sense tracks, current path
width against IPC-2221 and junction temperature; exit 1 on a failed
verdict. The keep-out verdict judges what layout can change - a part's own
pins are its package, left out - and names the two pieces of copper that
set its distance and their points, a pad by its part and number, a track
or via by its net and ends: "L1 pad 1 (SW) at (x, y) to U3 pad 9 (FB) at
(x, y)"; a nearer pair inside one part is said after it: "U3's own pads are
1.27 mm apart, a distance its footprint sets". `--json` carries the same,
in the verdict's note. The current path is the route the load
takes, through tracks, vias, pours and zone fills alike. A zone fill on
the route is measured along it: the fill is rasterised at `check.zone_step`
(default 0.05 mm), each cell's distance to the fill's edge taken (the slit
KiCad draws from each hole to the outline has no width, so it is no edge),
and the widest path found between the copper the route enters and leaves
the fill by - the widest disc that can travel from touching the one to
touching the other. Its width reads within about one step of the copper's;
a neck no cell falls in reads as one step and says so. The fill's
width is the route's there when it is narrower than the rest of the route
by more than a step. Each two parts carrying `Pm.I` on the net
are judged at the lesser of their two currents - what can flow between
them - by the narrowest point of the widest route from any pad of one to
any pad of the other; the net's verdict is its worst pair, naming both ends
and the current, and its neck: the point along the route the width is
narrowest, and how far the route stays within 10% of that width, measured
along the copper the widest route passes - "neck at (x, y), 0.9 mm long".
Where the neck is in a zone fill, the point is the fill's narrowest
point, with no length. A net only one part carries is not judged: one carrier cannot
say where its load goes (the widest-joined other pad is as often a
capacitor carrying ripple), and the verdict asks for a `Pm.I` on the part
that takes the load. A part carries on a net only at a current above zero:
a per-net `Pm.I` that leaves a net out, or gives it 0, leaves a sense pin
out of the load. Two carriers no copper joins yet are said, not judged. A board with no facts reports nothing to check. **Every `placemat
run` runs the same checks on the board it wrote**, prints one `checks` line -
how many failed, passed and were not judged, then each failure - and keeps the
verdicts in `run.json` under `verdicts`, with `checks_failed` and
`checks_unjudged` in the metrics. A verdict is "not judged" when no limit is
set or a fact the check needs is missing, and it is never counted as a pass.
The impact names any check whose verdict flipped since the previous run, and
the nets whose airwire changed most (`airwire by net:`); a run records
`metrics.airwire_per_net`, longest first.
Like DRC, a failed check is read as the gate; it does not change the exit
code on its own.
KiCad's own stderr (assertion notes, image-handler debug lines) is kept
out of the terminal; every line of it is in `kicad-stderr.log` in the run
directory, and `PLACEMAT_SHOW_KICAD=1` prints it all. Anything KiCad says
that is not one of the known noise patterns is printed regardless.

A run leaves `.placemat/runs/<id>/` beside the board (`<id>` is the hash of
the script and the modules it imports from beside it, its lock and kept
routes files, the generated board, the tool, the settings and the fab
profile, so `--accept` or `route --adopt` makes the next run a new id; `--label` adds a symlink
alias): `run.json`,
`script.log`, `drc.json`, `generate.log`, `impact.txt`, the written
`layout.kicad_pcb`, and `route/` (the routed copy, `route.json`,
`router.log`, DRC before and after) when routing ran. The generation is
cached in `.placemat/generated/`, with the digests of what it was made
from beside it (`<board>.inputs.json`: the board's .zen, every file a .zen
names by relative path - modules, loads, footprints, symbols - the
layout of each stamped fragment, the workspace's pcb.toml and the generate
arguments). A run whose inputs changed generates again and says which
file changed; `--fresh` regenerates regardless. `placemat preview` never
generates, and says when the cache it draws from is out of date.

A script runs with its own directory importable, and each folder above it
up to the one holding the nearest `placemat.toml`, innermost first: geometry
several scripts share can live in a module beside them, or in the board's
folder when each module's script sits in a folder of its own
(`import core_geometry`). A change to such a module changes the run id.

Every finished run is judged against the best earlier run of the same parts -
its **family**, the runs whose script asked to place the same items - and
`.placemat/runs/best.json` keeps one best per family. Better means a lower
**run score**: one number in millimetres of wire, each thing that can go
wrong counted and weighted by a `[score]` setting (the table below):

- an unplaced part, times its declared priority's multiplier;
- a real DRC violation;
- each millimetre a link is past its limit, times the link's weight;
- each finding by its kind: a fixed item not legal where put, copper that
  breaks a rule, a label on a part, a crossed, closed or walled-off escape,
  and a setup finding (the same every run, 0 by default);
- each ratsnest crossing, with a plane's or free net's crossing at
  `score.crossing_plane` of it;
- the airwire itself, a millimetre each.

A run records these measures, not its score, so a weight changed in
placemat.toml re-ranks the recorded runs at once, the stored best included.
Two scores tie within `best.airwire_noise` of the airwire plus
`best.crossing_noise` of the crossings' term, because kicad-cli picks
different ratsnest edges each run for a byte-identical board. A run made
with `--no-drc` measured neither, so it is not judged and never becomes a
best. The run prints a `score` line (each term, beside the
best's where they differ) and one `best` line - first of its family,
matches, better than, worse than, or not judged. **A run that comes out
worse is a finding naming the score and the term that moved it most, and
`placemat run` exits 1**, so a regression cannot pass unnoticed in a loop. Adding or removing a
part starts a new family. Routing needs
KiCadRoutingTools at `$KRT_DIR` (default `~/work/KiCadRoutingTools`) with
its own venv; quick mode is one routing round with the router's post-route
smoothing off (a measurement: a small two-layer board routes in about 10 s), `--full`
is the router's whole run. The search budget per net is the router's own
unless `--iterations` caps it. Left to itself (no `--layers` and no
`route.layers`), the router gets every copper layer except an inner one whose
own outline a `board.plane()` zone covers at least `route.plane_share` of (a
stamped cell's zone never counts, and F.Cu/B.Cu never drop) - the route step
prints which layers it left out and why, and the report's `plane_layers`
names them too. A net with a zone or a filled copper pour on the board is
left to its pour and not routed, as `run --route` leaves the plan's plane
nets; `--exclude` adds to them. The router does not see copper zones when it routes other nets: it lays
tracks through a board-wide fill, and the refill carves round them, so a fill
need not be switched off for routing. A partial pour on an inner layer of a
net left out would be split that way, so the router's input copy keeps other
nets' tracks out of its outline (vias may pass) and the route step says how
many pours it kept (`pours_kept` in the report); a route through one is a
keepout breach naming the pour. Outer-layer pours are left open to it: other
nets' pads sit in them.

Every router pass (the pairs, the island nets, the main pass) is given
`route.turn_cost` (20000 by default, where the router's own default is
1000: at that a 45-degree kink costs the router 0.05 mm of path, and its
routes stair-step along the line to their target) and runs the router's
own smoothing; `route.router_args` passes more of its flags through
(`route.pair_router_args` to the pair router). Routes
already kept stay as they were laid: `placemat routes <script>
--release-all` drops them, and the next `route --adopt-all` lays them again.

The pair router finds a pair by its nets' suffix (`_P`/`_N`, `P`/`N`,
`+`/`-`) among the nets `route.diff_pairs` selects. Two nets named
otherwise, such as a tank's two leads, are named as a pair with an entry
`"NET_A/NET_B"` (the first is P): the route step renames the two in its own
copy to `PMPAIR<i>_P`/`PMPAIR<i>_N`, a name no board net has, routes that
pair, and names them back in the routed copy before its copper is read or
kept. The renamed nets keep their net classes. The entry is a pair when it
has one `/`, not leading, and no glob character; a hierarchical name
(`/sheet/NET`) cannot be named this way. A named net the board does not
have stops the route before the router runs; a net in two named pairs is
refused when the settings load. Placement weighs a named pair's crossings
as it does a suffix pair's, and a named pair takes its nets from any suffix
pair they were in.

A pour net whose pours do not reach every pad of it (a rail's small taps on
the far side of a cell) is named in `[route] islands` (or `--islands
NET[=WIDTH]`): the route then runs the router on those nets first, one at a
time, each kept out of the other island nets' partial inner-layer pours.
The router counts a net's own zones as joining what they reach, so it joins
only the pads and pieces the pours leave apart, at the net's netclass width
(read from the board's project) or the WIDTH given (the router raises a
width below its own default track width to that); its tracks are then fixed
and the main pass leaves the net to its pours, other nets kept out of its
partial inner-layer pours. A name the board does not have is said and
skipped; a malformed entry is refused when the settings load. The route step says how many pieces each
island net had apart before and after (`islands` in the report); the
island nets count in the closure, and `--adopt NET` keeps their routes like
any other net's.

A footprint's own copper graphics (a net-tie's winding, a copper logo) are
not obstacles to the router, and its writer moves net-less ones on the
outer layers to silk. So the router's input copy carries a rule area over
each, on its own layer, forbidding tracks and vias (a route through one is
a keepout breach naming its footprint), and the routed copy gets every
footprint's graphics back as they were before its DRC is run; the report's
`restored_graphics` counts them.

**Keeping routed copper.** `placemat route <script> --adopt NET ...` routes
as above, then keeps the router's new copper on the named nets in
`<script stem>.routes.json` beside the script (commit it with the script);
`--adopt-all` keeps every net the route closed. A net is adopted whole and
clean: one still open or shorted after the route, or one the route added no
copper to, is not kept, and says why - unless `--partial`: then a net the
route left open keeps each island of its new copper that joins two of its
pads, or a pad and a plane of it (a via inside one of its zones), trimmed of
copper that leads nowhere, as a partial entry; the adopt line says how many
islands were kept and dropped and how much is still open. Copper already
there (the script's, a kept route's) joins what it touches. A later pass
adds another partial entry beside it; adopting the net whole replaces them
all. Each point is stored as an offset
from a pad of its net - the pad it lies on, or the net's nearest pad - with
the centres of the pads its parts were at, so a run fits how the parts have
moved and turned and carries the copper with them; a part is named by its
instance path. Adopting also locks the searched items the kept nets join
where the board stands (as `lock --current` does; `--no-lock` leaves the
lock alone), since kept copper is dropped when they move; a placement the
next run would not reproduce adopts nothing and says which items, so route
a board the current placemat has just run, or lock it first (`placemat lock
<script> --current`). Every
run and preview draws the kept copper as copper of its net, after the script's own, while
the parts it joins stand as they did relative to each other when it was
adopted (within `route.adopt_tolerance` at every kept pad); a conflict with
other copper is a `copper` finding. The net is dropped with a finding
("adopted route NET dropped: ...") when one of those parts has moved or
turned relative to the others, changed face or left the board, when a pad
it ends on is gone or on another net, or when an end that met the net's
other copper (a via or track the script declares) no longer does; the next
route routes it again. The run's
`adopted` line and `run.json`'s `metrics.adopted` say which nets were held
and which dropped. Kept copper is locked input copper on the written board,
so a route leaves it alone and counts its net closed. `placemat routes
<script>` lists what is kept (net, tracks, vias, the parts it joins, when)
and `--release NET ...` stops keeping a net.

## Exploring a placement

Once the declarations are right, the placer can search its own choices for
the items it was left to place:

```
placemat run <script> --explore SECONDS [--focus ITEM ...] [--focus-after LINE]
                      [--focus-box X0,Y0,X1,Y1] [--jobs N] [--accept]
placemat preview <script> --explore SECONDS [the same]
placemat lock <script> [--current [--partial] | --release ITEM ... | --release-all]
placemat freeze <script> ITEM ... | --all [--fixed]
```

**What varies.** Only the items in focus, and only what the search chooses
for them: a focused item draws among its better legal spots (within
`[explore] slack` of its best, the best the likeliest), rotation with the
spot, and two focused items next in the placement order sometimes trade
turns (`[explore] swap`). Everything else is placed as the plain run places
it. An item in focus is one searched from its links or round a `Near()`
hint - fixed, edge, line and rim items never vary.

**The focus.** `--focus` names items by key (a part, a cell, a block);
`--focus-after LINE` takes what the script declares from that line on;
`--focus-box` what the current placement put inside the box. With none,
every searched item. A focus with nothing in it says so and searches
nothing.

**Judging a variant.** By the run score (Commands), with the worst congestion
cell (RUDY) added in steps of `[explore] congestion_step` at
`score.congestion` each: the measure that agreed with the router in the
congestion study. Lower wins; it is one weighted sum, not a tiered
comparison.

**What a run says.** `explore  N variants in S s over K focused items:
score B -> A mm (term b -> a, ...); M items would move`, the terms of the
score that changed in brackets, then one line per item that would move. `metrics.explore` records it.
Without `--accept` nothing persists.

**The lock.** `--accept` writes the best variant's decisions for the
focused items to `<script stem>.lock.json` beside the script, and the run
uses them. Each entry places its item off the placed pad it depends on
most, in that pad's part's frame (it follows the part when it moves or
turns), keeps its turn among the locked items, and carries a digest of the
item's declaration. Every later run applies the lock: `held by lock` when
the spot is legal, `lock: drifted N mm` when something now blocks it (the
nearest legal spot round it), `lock: released - why` when the declaration
changed or the anchor is gone, turned over or placed later. The cleanup
pass leaves a held item where it is. Commit the lock with the script; a
run prints how many items it held, drifted and released. `placemat lock`
lists entries and releases them. An anchor is named by its part's
instance path, so a renumbering of the board moves nothing.

`placemat lock <script> --current` locks every searched item where the
board stands: the script is resolved as its last run resolved it, each
item's pads are checked against the written board, the items are locked,
merged over the entries the lock holds, and the script is resolved again to
check each comes back there. One that would land elsewhere is named, nothing
is written, and the command exits 1: run the script, then lock. With
`--partial` those that would not stand are dropped and the rest checked
again (a smaller lock can move what is searched after it) until every one
left comes back; those are written, the rest listed ("locked 46 of 75 ...;
29 would not stand there"), and the command exits 1 when any was left out.

**Freeze.** `placemat freeze <script> ITEM` (or `--all`) writes entries
into the script in the lock's own terms: the item's `place()` call gains
`at=Near(PadRef(<anchor>).local(dx, dy), radius=0)` - an offset in the
anchor part's own frame - and `rotation=Turned(Part(<anchor>), r)`, so it
keeps its turn of the order and turns with its anchor exactly as the lock
held it, and its `why=` gains where the spot came from (`explore <run>:
<score> mm, frozen <date>`). `--fixed` writes a firm
`Location(X(...), Y(...))` instead, allowed when the anchor is fixed. Only
that call's arguments change - comments and every other line stay - and the
script and lock are written only when the edited script places every item
exactly as the lock did; otherwise freeze says what would have moved (an
entry that drifted is refused: accept it again where it now stands). A call inside a loop or a helper function
declares more than one item and is refused with its line.

## Report form and the files placemat writes

Every command takes `--format text|json` (text by default; `--json` is the
same as `--format json`) and `--output FILE`, which writes the report to FILE
instead of the terminal, without colour. A command writes a report file only
when `--output` asks for one.

Besides that, these commands write files as part of what they are for, each
in a place of its own:

| Command | What it writes | Where |
|---|---|---|
| `run` | the placed board: `layout.kicad_pcb`, the project's presets and a `.kicad_dru` of the script's rules | the board's layout directory |
| `run` | the generation, cached so a rerun skips `pcb layout` | `.placemat/generated/<board>/` |
| `run` | what that generation was made from, to know when it is out of date | `.placemat/generated/<board>.inputs.json` |
| `run` | the run: `run.json`, `script.log`, a copy of the board, renders, `drc.json`, `impact.txt`, `reuse.json` (what the next run replays) | `.placemat/runs/<id>/` |
| `run` | `latest.json` (the last run of any board), `latest-<board>.json` (the last of each board: what a run compares with and reuses), `best.json`, and with `--label` an alias | `.placemat/runs/` |
| `preview` | `preview.svg`, `preview.png`, and `reuse.json` (what the next preview replays) | `.placemat/preview/`, or `--out DIR` |
| `run` / `preview` with `--explore --accept`, `lock --current`, `route --adopt` | the lock: accepted decisions | `<script stem>.lock.json` beside the script |
| `freeze` | the script's frozen `place()` calls, and the lock less those entries | the script, and its lock |
| `route --adopt` / `routes --release` | the kept routes | `<script stem>.routes.json` beside the script |
| `route` | the input and routed boards, the router's log, `route.json` | `.placemat/route/`, or `--out DIR` |
| `show` | the item's renders | `.placemat/show/`, or `--out DIR` |
| `datasheet --show` | the page's render | beside the PDF, or `--out DIR` |
| `faces` | the declared sides, into the fragment | the fragment named |

`.placemat/` sits in the board's directory. The other commands only read.

A written board's 3D model paths resolve from its own folder: a
`${KIPRJMOD}`-relative or relative model path that does not is re-anchored
to the nearest folder above the project that holds the same tail
(`parts/<part>/<file>.step`), up to the workspace, and written back
`${KIPRJMOD}`-relative; a module deeper in the tree than the board its
library was written for renders with its bodies. Only a path from the
project's folder (`${KIPRJMOD}/...`, `$(KIPRJMOD)/...`, `../...`) is
judged; an embedded model, another variable, a search-path alias and a
library-relative or absolute path are KiCad's to find, and left. The run's `models` line says how many were
re-anchored and names any found nowhere.

## Settings

`placemat.toml` holds every behavioural constant. It is found by walking up
from the board's directory, and every file on that path contributes: the
NEAREST file wins per key, so a project root sets the house style and one
board overrides one number without restating the rest.

```
built-in default  <  placemat.toml (nearest wins per key)  <  CLI flag
```

An unknown section or key, a wrong type or a value outside its range is an
error naming the file and the key. A setting that quietly did nothing would
read as though it were in force.

The resolved settings are part of a run's id, so changing one gives a new run
rather than replacing the last one.

`placemat settings [<script-or-dir>] [--json]` prints every resolved value and
the file it came from.

```toml
# electronics/placemat.toml
[place]
step = 0.1              # this board is laid out on a 0.1 grid

[drc]
real_kinds = ["clearance", "shorting_items", "hole_clearance"]
```

| key | default | what it governs |
|---|---|---|
| `rank.area` | 0.7 | weight on courtyard area when ordering searched items |
| `rank.pins` | 0.3 | weight on pin count when ordering searched items |
| `place.radius` | 3.0 | a search's default radius |
| `place.step` | 0.2 | a search's default step |
| `place.rotations` | "all" | a searched part with no `rotation=` or `rotations=`: `all` four rotations, or only its `declared` one |
| `place.envelope` | "courtyard" | what a part claims against another: `courtyard` (its courtyard and pads), `physical` (its pads, mask openings, silk and body, each at the board's own gap), or `union` (both) |
| `place.coarse_steps` | 4 | how many steps apart a scored scan's first pass walks |
| `place.coarse_from` | 12 | radius-to-step ratio from which a scan goes coarse first |
| `place.refine_around` | 3 | how many of the best coarse spots get a fine pass |
| `place.block_gap_step` | 0.05 | how finely a block's tightest gap is searched |
| `place.block_gap_reach` | 2.0 | how far a satellite may stand off its pin |
| `place.escape_depth` | 1.0 | how far each corridor out of a pad runs in the search: it weighs a candidate that crosses, closes or walls off a pad's corridors (`score.escape_*`); the run score measures them at `score.escape_depth` |
| `place.escape_pads` | 1 | a part's pads keep escapes when it has at least this many (3 leaves two-pad parts out) |
| `place.courtyard_touch` | 0.0 | how far two courtyards may overlap at least; each pair may also overlap by the two parts' margins (how far KiCad's courtyard polygon lies inside the drawn box) less 0.001 mm, which keeps KiCad's courtyards apart - it counts touching as overlapping |
| `place.courtyard_polygon_share` | 0.98 | a courtyard whose polygon covers less of the box round it than this (a slice of a disc, an L, a rectangle turned off the axes) is claimed as KiCad draws it, with no margin; one that covers more is claimed as its box |
| `place.conflict_gap` | 1.0 | how far outside a box a conflict can still reach |
| `place.fit_room` | 10.0 | on a fit frame, how far round the decided content a searched item may go |
| `place.via_share` | 1.0 | how near a via of its net a carried via that meets another net's copper may be to share it instead; 0 never shares |
| `place.via_move` | 0.5 | how far such a via may move to clear it; 0 never moves |
| `place.via_move_step` | 0.05 | the grid a via's move is searched on |
| `place.drops_keep` | 0.5 | the share of a pad's drops (vias of a `plane()` net in it) the pad keeps, rounded up and never fewer than one: what `drops=Drops.MIN` keeps of each field, and what a pad keeps when a carried drop is dropped to clear another net's copper (1 drops none there) |
| `copper.chamfer` | 1.0 | how far a right angle is cut back into two 45s |
| `copper.pair_chamfer` | 0.5 | the same, for a differential pair |
| `copper.pair_via_step` | 0.4 | how far clear of its partner a pair's lead vias |
| `copper.bridge_half` | 1.1 | half the gap a bridge leaves round a crossed track |
| `copper.finger_bridge_width` | 1.0 | the width of a finger's bridge under a track |
| `copper.plane_inset` | 0.4 | how far a plane is inset from the board edge |
| `copper.plane_clearance` | 0.2 | a zone's pullback from foreign copper |
| `copper.plane_min_thickness` | 0.2 | a zone's minimum filled width |
| `copper.pour_stroke` | 0.2 | a pour's outline stroke |
| `write.split_groups` | "lift" | the generator's nested groups: `lift` each cell's group out of its module's to the top level (the module keeps its own parts), `split` also takes out of a group the parts the script places by steps of their own, `keep` writes them as generated; a group left empty is removed |
| `write.keepout_drawings` | "admitting" | draw a keepout's outline and what it admits, on its Fab layer (or `User.Comments` for one on both faces or on inner layers only): `admitting` (default) those that admit something (`allow=` or `max_height=`), `all` every keepout, `none` |
| `write.keepout_line` | 0.1 | a drawn keepout's outline stroke |
| `write.keepout_text` | 0.8 | a drawn keepout's label height |
| `copper.microvia_drill` | 0.1 | a micro via's drill (`layers=` one layer from an outer face) when the script gives none |
| `copper.cell_zones_under_planes` | "drop" | a stamped cell's zone the board's own plane covers on its net and layer: `drop` merges it into the plane, `keep` keeps it |
| `label.size` | 1.0 | silkscreen text height |
| `label.thickness` | 0.15 | silkscreen stroke width |
| `label.gap` | 0.0 | a label's gap from what it names; never less than the board's silk clearance |
| `geometry.arc_sag` | 0.02 | how far a flattened arc may cut the corner off the real one |
| `geometry.index_cells` | 16 | buckets across the longer side of the spatial index |
| `geometry.arc_error_nm` | 5000 | arc approximation error when reading pad outlines |
| `check.ambient_c` | 100.0 | board temperature the junction estimate starts from (`--ambient`) |
| `check.keep_out_mm` | 2.0 | how far sense copper stays from a switch node (`--keep-out`) |
| `check.rise_c` | 10.0 | the rise a current path is sized for (`--rise`) |
| `check.copper_oz` | 1.0 | outer copper weight the widths are sized for (`--copper-oz`) |
| `check.zone_step` | 0.05 | the cell a zone fill is rasterised at to measure its width along a load's route; the width reads within one step |
| `check.limits` | none | a bound per check, e.g. `"hot-loop" = 20.0` (`--limit`) |
| `parts.order_fields` | `["Lcsc", "LCSC", "Mpn", "MPN"]` | a footprint field naming an order code (an LCSC number, an MPN); `parts` warns when a placed part (not `dnp`) has none of them present and non-empty |
| `explore.slack` | 0.25 | an explored item draws among spots scoring within this fraction of its best |
| `explore.swap` | 0.2 | the chance two focused items next in the placement order trade turns |
| `explore.rank_power` | 1.0 | an explored item's spot at rank r among its candidates is drawn with weight 1 / r to this power: higher keeps it nearer its best |
| `explore.congestion_step` | 0.05 | variants are ranked by the run score, with the worst congestion cell counted in steps of this at `score.congestion` each (0 leaves it out) |
| `explore.jobs` | 0 | worker processes for `--explore`; 0 is the CPU count less one |
| `drc.severities` | none | a table of KiCad rule names to `error`, `warning` or `ignore`, written into the board's .kicad_pro before DRC |
| `drc.real_kinds` | `clearance`, `shorting_items`, `track_width`, `annular_width`, `hole_clearance`, `hole_to_hole`, `courtyards_overlap`, `copper_edge_clearance` | which violations mean the board is not done: the `real` buckets |
| `drc.outstanding_kinds` | `via_dangling`, `track_dangling`, `isolated_copper` | which violations are copper not yet joined: `outstanding` |
| `drc.footprint_kinds` | `lib_footprint_issues`, `lib_footprint_mismatch`, `malformed_courtyard`, `padstack` | which violations are defects in the footprints themselves: `footprint issues` |
| `drc.refill_zones` | true | refill zones for the check |
| `route.router_dir` | `$KRT_DIR`, else `~/work/KiCadRoutingTools` | the KiCadRoutingTools checkout |
| `route.quick` | true | one routing round rather than the router's full run |
| `route.iterations` | the router's own | cap on the router's search per net |
| `route.layers` | every copper layer, minus an inner one the board's own plane fills whole | which layers the router may use |
| `route.plane_share` | 0.9 | how much of the board's own outline a zone must cover, to count as a plane that fills its (inner) layer whole for `route.layers`' default |
| `route.turn_cost` | 20000 | what the router charges a turn, per 90 degrees (a 45 half of it), against 1000 a straight grid step: the router's own default of 1000 makes a kink nearly free and its routes stair-step; 20000 measured best on a dense four-layer board (fewer than half the turns, 10% less copper, closure no worse); 1000 gives the router's own behaviour |
| `route.smoothing` | true | the router's own octolinear smoothing, as it defaults; false skips it |
| `route.router_args` | `[]` | more of the router's own flags (`--direction-preference-cost`, `--heuristic-weight`, `--bus`, `--via-cost`, ...), each a string, appended to its route.py passes (the island nets, the main pass); one placemat sets itself (`--nets`, `--layers`, `--escalation`, `--keep-input-copper`, `--turn-cost`, `--smoothing`, `--no-smoothing`, `--power-nets`, `--power-nets-widths`, `--max-iterations`, `--max-probe-iterations`, `--json-out`) is refused |
| `route.pair_router_args` | `[]` | the same for the pair router (route_diff.py), which takes flags of its own (`--max-turn-angle`, `--min-turning-radius`, ...) and not all of route.py's |
| `route.islands` | `[]` | nets with pours whose pads the pours do not reach (a pour net's small taps), `"NET"` or `"NET=WIDTH"` (mm): routed first and alone, joining only the pads and pieces the pours leave apart, at the netclass width or WIDTH; `placemat route --islands` adds to them |
| `route.diff_pairs` | `["*"]` | net patterns naming the differential pairs: the router's pair router (route_diff.py) routes them first, as pairs, and placement prices their own crossings at `score.pair_crossing`; an entry `"NET_A/NET_B"` names one pair outright, P first (see `placemat route` under Commands); `[]` names none (every net single-ended, no pair weighting) |
| `route.diff_pair_gap` | 0 | mm between a pair's tracks; 0 is the net class's diff pair gap (the router never goes below the class clearance) |
| `route.diff_pair_width` | 0 | mm, a pair's track width; 0 is the net class's diff pair width |
| `route.adopt_tolerance` | 0.001 | mm any kept pad may lie from where the parts' common motion puts it before the kept routes joining them are dropped |
| `timeout.generate` | 900 | seconds for `pcb layout` |
| `timeout.drc` | 600 | seconds for kicad-cli DRC |
| `timeout.route` | 3600 | seconds for the router |
| `timeout.render` | 300 | seconds for a render |
| `noise.patterns` | none | extra KiCad stderr patterns to suppress, ADDED to the built-ins |
| `best.airwire_noise` | 0.01 | how far airwire may move, as a fraction, before a run counts as better or worse than its family's best: kicad-cli picks different ratsnest edges each run for a byte-identical board |
| `best.crossing_noise` | 0.02 | how far the crossings' term may move, as a fraction, before a score counts as better or worse: kicad-cli's ratsnest varies run to run |
| `score.unplaced` | 2000 | mm a part left unplaced costs the run score, times its priority's multiplier |
| `score.priority_high` | 2.0 | the unplaced multiplier for a part declared `priority=HIGH` |
| `score.priority_default` | 1.0 | the unplaced multiplier for a part with no declared priority |
| `score.priority_low` | 0.5 | the unplaced multiplier for a part declared `priority=LOW` |
| `score.drc` | 200 | mm a real DRC violation costs |
| `score.link_over` | 20 | mm per millimetre a link is past its limit, times the link's weight |
| `score.fixed` | 200 | mm a decided item (fixed, a cutout, a keepout) not legal where it was put costs |
| `score.copper` | 200 | mm planned copper that meets another net, crosses a keepout or cannot bridge costs |
| `score.label` | 50 | mm a label with a part on it costs |
| `score.setup` | 0 | mm a setup finding costs: the same every run of a script (an undeclared part, a layer the board lacks) |
| `score.crossing` | 4.0 | mm a ratsnest crossing costs, in the run score and in the search |
| `score.crossing_plane` | 0 | a crossing with a plane's or free net's airwire, as a share of `score.crossing`: each of its pads drops to the plane by a via |
| `score.pair_crossing` | 100 | mm a differential pair (as `route.diff_pairs` names them) crossing itself costs, in place of `score.crossing`: such a pair has to exchange sides to route coupled, so a swap of two identical parts or a turned part is worth wire |
| `score.escape_crossed` | 20 | mm two escapes from one part's pins crossing near its pin row cost |
| `score.escape_closed` | 50 | mm a pad whose last route toward what it connects to is closed costs |
| `score.escape_walled` | 400 | mm a pad with no route out at all costs |
| `score.escape_depth` | 1.5 | mm: the corridor length the escape findings, and so the run score, are measured at, whatever `place.escape_depth` the search used, so runs at different search depths compare |
| `score.congestion` | 10 | explore: mm per `explore.congestion_step` of the worst RUDY cell |
| `score.via_share` | 1 | mm the search adds to a spot for each carried via that shares a via of its net there |
| `score.via_move` | 2 | mm for each carried via that moves there |
| `score.via_drop` | 10 | mm for each plane drop dropped there |
| `score.push` | 10 | mm-equivalent: `score.push` times a push's modelled value over its limit, at the search |
| `solve.enabled` | false | give the searched tier its hints from a global solve of the whole netlist, before any item is scanned |
| `solve.iterations` | 200 | the solve's conjugate-gradient cap per axis per round |
| `solve.tolerance` | 1e-06 | the residual the solve stops at |
| `solve.rounds` | 8 | solve-then-spread rounds, the pull toward the spread doubling each round |
| `preview.converter` | "rsvg-convert --width {width} -o {png} {svg}" | the command `placemat preview` runs to turn its SVG into a PNG; `{svg}`, `{png}` and `{width}` are filled in |
| `preview.px_per_mm` | 40.0 | the preview PNG's resolution, pixels per millimetre of the drawing |
| `preview.model_edge` | 1568 | the long edge, in pixels, an image is scaled to before the model reading it sees it - an assumption about that model, which placemat cannot know; the preview reports the resolution the model would then see. 0 reports nothing |
| `cleanup.enabled` | true | after the searched tier, move and swap plain searched parts where that shortens their wire and declared links |
| `cleanup.passes` | 2 | passes over the movable parts; one that changes nothing ends it |
| `cleanup.radius` | 3.0 | how far round its optimal region, and round where it stands, a part is searched |
| `cleanup.step` | 0.5 | that search's step |
| `cleanup.swap_neighbours` | 4 | each part is offered a swap with this many of its nearest movable neighbours: both lifted, each searched round the other's old spot |
| `cleanup.swap_radius` | 1.0 | how far round the other's old spot each part of a swap is searched |

A run also records `metrics.seeded_by_net`: how many searched items each net
seeded. One net seeding most of the board is a missing `board.plane()`. And
`metrics.pocketed`, when any were: how many searched items found no room by
what they connect to and took a pocket instead; the run prints their names.
And `metrics.footprints`, in courtyard mode, when any courtyard understates
its part, and `metrics.cleanup` when the cleanup pass ran. And `metrics.rudy`:
the placed board's congestion by RUDY - each routed net's wire spread over its
box on a 0.5 mm grid, against what a cell's layers carry - as
the worst cell's share of capacity and where it is, the 99th percentile cell
and the overflow; the run prints the worst cell as `congestion`. On a study
of the fixture modules the worst cell was the one congestion measure that
picked the better-routing of two placements more often than chance (about
three times in four). The search does not weigh it; explore ranks variants
by it (`score.congestion`).

Every verb whose default appears here takes an explicit argument that still
wins: `board.plane(..., inset=1.0)` beats `copper.plane_inset`.

Three kinds of constant are NOT settable, because they are not behaviour: the
grid epsilons (ten KiCad units, the file format's resolution), the physical
constants (IPC-2221 and unit conversions), and the tables that map placemat's
words onto KiCad's layers and flags.
