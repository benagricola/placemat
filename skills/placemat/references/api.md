# The script surface

```python
from placemat import (board, Along, Axis, Bearing, Bend, Beside, Between, Box, Cell, CellPadRef, Centre, Corner, Cover, Pin, Polar, OnRim, OnBore,
                       Cutout, Disc, Drops, Arc, Circle, Path, Slot, CopperLayer, Edge, Face, Facing, Figure, FigurePoint, Forbid, Fraction, FreeSpot, Inside,
                       Land, Line, SideOf, LinkWeight, Location, Mid, Near, Net, OnEdge, Origin, Parallel, PadRef, Part, Past, Priority, Reach, Tangent,
                       Turned, Turns, X, Y)
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
replaces. Only a relation that search cannot say goes to placemat as a
request (SKILL.md, "When no form says it").

| you want to say | write | section |
|---|---|---|
| **a part** | | |
| searched from its links, no position typed | `board.place(item)` | Placement |
| one that must place, or the run stops | `board.place(item, required=True)` | Placement |
| a cell with its pads' via fields thinned | `board.place(Cell(...), drops=Drops.HALF)` | Placement |
| a cell held to its module's own layout, or to chosen arrangements | `board.place(cell, arrangements="default")`, `arrangements=["a", "b"]` | Placement (Arrangements) |
| on a board edge, wherever there is room | `at=OnEdge(edge)` | Placement |
| at a mechanical point along an edge | `at=OnEdge(edge, along=Along.MID)` | Placement |
| at a mechanical point (an enclosure hole, a datasheet figure) | `at=Location(x, y)`, `x`/`y` named constants | Placement |
| its own pad on the pin it serves | `at=Pin(key, X(pin), Y(pin))`, or `Pin(key, pin)` | Placement |
| its own pad against another pad's edge (a net tie at a shunt's inner edge) | `at=Pin(1, PadRef(part, n, edge=Edge.SOUTH, along=Along.END))` | Placement |
| a cell placed by one of its members' pads | `at=Pin(CellPadRef(cell, net=), x, y)` | Placement |
| a cell placed by a member's footprint origin (not a pad) | `at=Pin(Part(member), x, y)` | Placement |
| a part's own origin on another part's (or a cell's) origin | `at=Origin(Part(other))` | Placement (Origins) |
| its own origin on the midpoint of two pads (a pad-less outline between two pins) | `at=Mid(PadRef(a, 1), PadRef(b, 1))` | Placement (Origins) |
| another part's origin as a coordinate | `X(Origin(Part(other)))`, `Mid(Origin(a), Origin(b))`, `Polar(r, bearing, about=Origin(...))` | Placement (Origins) |
| the midpoint of two of its own pads on a point | `at=Pin(Mid(10, 11), x, y)` | Placement (Own pad midpoint) |
| that midpoint level with a point, beside a part | `at=Beside(item, Edge.SOUTH, align=(Mid(10, 11), X(point)))` | Placement (Own pad midpoint) |
| one land of a pin drawn as several on the point | `at=Pin(key, x, y, land=Land.LARGEST)` | Placement (Own pad midpoint) |
| between two pads | `at=Centre(X(Mid(a, b)), Y(a))` | Placement |
| sliding along one line, the other axis free | `at=Centre(None, y)` / `Location(x, None)` | Placement |
| as far toward one end of a line as it is legal | `at=Centre(x, None, toward=Edge.SOUTH)` | Placement |
| somewhere the netlist cannot say (a thermal neighbour) | `at=Near(PadRef(...))` | Placement |
| beside a part, a cell or a keepout, at the envelope gap | `at=Beside(item, Edge.EAST, align=Along.START, gap=)` | Placement (Beside) |
| beside one part, level with a pad of it or of any firmly placed part | `at=Beside(item, Edge.SOUTH, align=PadRef(Part(other), n))` | Placement (Beside) |
| a part a clearance off another part's pad copper (a net tie at a pad) | `at=Beside(item, Edge.NORTH, copper=True, align=(own_pad, PadRef(...)))` | Placement (Beside) |
| its pad a lane (or the clearance) past other pads | `at=Beside(item, Edge.SOUTH, align=(own_pad, Past([PadRef(...)], Edge.WEST, lane=Net(...))))` | Placement (Beside) |
| that lane as wide as its current needs | `Past(..., lane=Net(...), width=)` in that align | Placement (Beside) |
| its pad a lane (or the clearance) off a 45 past a pad's corner | `at=Beside(item, Edge.SOUTH, align=(own_pad, Past([PadRef(...)], Corner.NE, lane=Net(...))))` | Placement (Beside) |
| fixed off a part that is itself searched (a bypass at a searched part's pad end) | any firm `at=` (`Pin`, `Beside`, `row(of=)`) on the searched part: it rides the search | Placement (Riders) |
| turned with another part | `rotation=Turned(part, deg)` | Placement |
| turned parallel to the line between two pads (any angle) | `rotation=Parallel(PadRef(a, 1), PadRef(a, 2))` | Placement (Turns) |
| a point a gap off a pad along that line's normal | `Polar(gap, Bearing(a, b, 90), about=pad)` | Placement (Turns) |
| turned so a pad's row faces a board side | `rotation=Facing(PadRef(part, n), Edge.NORTH)` | Placement (Turns) |
| turned so a grid's outer row or column faces a side | `rotation=Facing([PadRef(part, "B2"), PadRef(part, "A2")], Edge.SOUTH)` | Placement (Turns) |
| every part of a row turned so its pad n faces a side | `board.row(items, edge, rotation=Facing(n, Edge.WEST))` | Placement (Rows) |
| turned so its pad faces another part's pad, whichever side that lands on | `rotation=Facing(PadRef(c, "SUPPLY"), toward=PadRef(u, "VCC"))` | Placement (Turns) |
| beside a part on the side where its pad lands after its turn | `at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC")))` | Placement (Beside) |
| beside a part past the end of the pin row where a pad lies | `at=Beside(Part("u"), SideOf(PadRef(Part("u"), 1), along=True))` | Placement (Beside) |
| a row ordered by where the pads its items serve land | `board.row(items, edge, of=Part("u"), over=[PadRef(Part("u"), "SDA"), ...])` | Placement (Rows) |
| on a point, its turn (a bearing) searched, scored by links, pushes and keepouts | `at=Pin(Part("c.member"), Location(x, y)), rotations=Turns.ANY` | Placement (Turns) |
| turned to face a board edge or a bearing | `board.outward_rotation(item, edge, face=)` | Faces |
| searched in a band of radii about a point, turned to the tangent at whatever bearing it lands on | `at=Polar((r_min, r_max), None, about=centre), rotations=Turns.TANGENT` | Round boards |
| on a ring about a point, any bearing, its body centre at the radius and turned to face out there | `at=Polar(r, None, about=centre), rotations=Turns.TANGENT` | Round boards |
| its fine-pitch escape kept clear | `board.fanout(part, depth=)` | Placement |
| a pin row's routes out kept clear, lanes and vias, before parts are placed | `esc = board.escape(part, pins, turn=Edge.WEST, vias=[...])` | Placement (Escape) |
| a track along one of those lanes, through its via | `board.track(net, [esc[pin], ...])` | Placement (Escape) |
| a part beside a lane's via, or beside the whole escape | `at=Beside(esc[pin].via, Edge.WEST)` / `at=Beside(esc, Edge.NORTH)` | Placement (Escape) |
| a part's pad on a pin's lane | `at=Beside(item, Edge.WEST, align=(own_pad, esc[pin]))` | Placement (Escape) |
| a part's pad at the end of a lane | `at=Pin(key, X(esc[pin].end), Y(esc[pin].end))` | Placement (Escape) |
| a via or a track held off a lane's via | `Past([esc[pin].via], Edge.WEST)` | Placement (Escape) |
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
| a part searched between two radii | `at=Polar((r_min, r_max), None, about=)` | Round boards |
| on a disc's rim facing out, or at its bore facing in | `at=OnRim(edge)` / `at=OnBore(edge)` | Round boards |
| **what pulls parts together** | | |
| a connection priced (a bypass capacitor, a series part) | `board.link(a, b, weight=, limit_mm=)` | Links |
| a part held back from a source by physics, not a hand-picked point (a field sensor from a magnet, a heat-sensitive part from a heat source) | `board.push(item, from_=, falloff=, reference=(r_ref, v_ref), limit=)` | Push |
| a part held back from another part by what the capture says they emit and tolerate | `Pm.Emits` on the source, `Pm.Limit` on the sensitive part (no script line) | Push, annotated |
| a net whose off-board run dwarfs the board | `board.free_net(net)` | Links |
| a cell's outward, quiet and handoff sides | `board.faces(outward=, quiet=, handoff=)` | Faces |
| **the board and its regions** | | |
| a board of any shape | `board.outline(path, holes=)` | Boards of any shape |
| a stretch of edge chosen by which way it faces | `board.edge(facing=Edge.NORTH)` | Boards of any shape |
| a rectangular board | `board.rect(width, height, chamfer=, radius=, holes=)` | Setup |
| a round board | `board.disc(diameter, hole=)` | Round boards |
| a fragment frame sized to its own content | `board.rect(fit=True)` | Setup |
| a fragment frame fitted in one axis, the other a declared number | `board.rect(fit=Axis.X, height=)` | Setup |
| a hole in the board | `Cutout(shape, name, at=)` in `holes=` | Cutouts |
| a hole placed from the connector it serves | `at=Centre(X(Part(j)), Y(Part(j), d))` | Cutouts |
| a region that forbids parts, fill, tracks, vias or pads | `board.keepout(shape, name, at=)` | Keepouts |
| a region shaped by a part or cell, growing and turning with it | `board.keepout(item, name, margin=)` | Keepouts |
| a region inside a part's pads (between two pad columns, inside a pad ring) | `board.keepout(Inside(Part(...), margin=), name)` | Keepouts |
| a clearance anchored on a pad, in a datasheet's own coordinates | `Path(FIGURE, anchor=...)`, `at=PadRef(...)`, `rotation=Turned(part, 0)` | Keepouts |
| the points of a datasheet's dimensioned reference layout (feed, strip, vias), in the figure's own coordinates | `fig = board.figure(at=, rotation=, anchor=, why=)`, `fig.point(x, y)`, `board.keepout(Path(FIGURE), name, frame=fig)` | Keepouts |
| a clearance band along a board edge | `board.keepout(shape, name, at=OnEdge(edge, along=Along.MID))` | Cutouts (the shape on an edge) |
| a region a case leaves little room over | `board.keepout(..., excludes=(Forbid.PARTS,), max_height=)` | Keepouts |
| a region that keeps a few parts out and lets every other part in | `board.keepout(..., bars=(Part(...), Cell(...)))` | Keepouts |
| a part against a keepout's boundary | `at=Beside(keepout, Edge.SOUTH)` | Placement (Beside) |
| a clearance that differs from the net class, in one place | `board.rule(clearance=, within=/between=/on=)` | Rules |
| one design-check verdict taken as it is, with the reason | `board.accept(check, subject, at_least=/at_most=, why=)` | Accepting a check verdict |
| **copper** | | |
| a track from a pad to a pad | `board.track(net, [PadRef(a), PadRef(b)], layer=)` | Copper calls |
| which end of an off-grid leg takes the 45 | `board.track(..., bend=Bend.START/END/BOTH)` | Copper vocabulary |
| corners drawn as tangent arcs (a curved trace) | `board.track(..., bend=Bend.ARC)`, `radius=` | Copper vocabulary |
| a track through the gap between two pads | `Between(PadRef(a), PadRef(b))` as a track point | Copper vocabulary (Lane waypoints) |
| a track held the clearance off pads, vias, tracks, a cutout, the board edge, a part or a label | `Past([PadRef(...), via, track], Edge.EAST, across=)`, `Past([vent], Edge.WEST)`, `Past([board.edge(facing=Edge.WEST)], Edge.EAST)` as a track point | Copper vocabulary (Lane waypoints) |
| a track's 45 held the clearance off a corner of pads or a cutout | `Past([PadRef(...)], Corner.NE)` as a track point | Copper vocabulary (Lane waypoints) |
| a track meeting its pad at one edge only (a Kelvin tap) | `PadRef(part, n, edge=Edge.SOUTH, along=Along.END)` as a track point | Copper vocabulary (Lane waypoints) |
| a via at the nearest legal spot to a pad | `board.via(net, FreeSpot(near=PadRef(...)))` | Copper calls |
| a via its clearance past pads, vias, tracks, a cutout or a label, on a pad's axis | `board.via(net, at=Past([...], Edge.SOUTH, across=PadRef(...)))` | Copper calls |
| a power or exposed pad filled with vias | `board.vias(net, PadRef(...))` | Copper calls |
| a track, via or pour on one land of a pin drawn as several | `PadRef(part, n, land=Land.LARGEST)` or `land=2` | Copper vocabulary |
| vias in a row out from a pad, a tail joining them | `board.vias(net, along=PadRef(...), count=N)`; as a track point, its value is the farthest via | Copper calls |
| a track on to a via or a via row | the value `board.via()`/`board.vias(along=)` returns, as a track point | Copper calls |
| stitching vias over a cell, a pour or a keepout, along its outline, or in a row outside it | `board.stitch(net, region, edge=, outside=)` | Copper calls |
| a micro, blind or buried via, for a fab that makes them (allowed in fab-profile.json) | `layers=(CopperLayer.B, CopperLayer.IN4)` on `via()`, `vias()` or `stitch()` | Copper calls (A via's layer span) |
| a pour of exactly the shape given | `board.pour(net, points, layer=)` | Copper calls |
| a pour over a set of pads, fitted round other nets' copper | `board.pour(net, [PadRef(...), ...], layer=, swallow_pads=True)`: a graphic polygon holding the pads' copper, every edge at least the clearance from other copper | Copper calls (A fitted pour) |
| a pour on an inner layer joining vias | `board.pour(net, [vias, PadRef(...), ...], layer=, swallow_pads=True)`: members are pads and the vias `via()`, `vias()` and a lane's `.via` return | Copper calls (A fitted pour) |
| a pour over the hull or the box round a set of pads, drawn as declared | `board.pour(net, [PadRef(...), ...], layer=, cover=Cover.HULL)` (or `Cover.BOX`) | Copper calls (What a pour over pads covers) |
| a pour that widens into the room round its pads until its net's current-path width is met | `board.pour(net, [PadRef(...), ...], layer=, swallow_pads=True, reach=Reach.CURRENT)`: grown only as far as the current on the parts, the rise and the copper weight need, cut back by other nets' clearance outlines; a finding names the neck where the room runs out | Copper calls (A fitted pour, Reach) |
| a pour that reaches past its pads by a distance with no fact behind it | an escape hatch, as a coordinate is (SKILL.md, "When no form says it"): `board.pour(net, [PadRef(...), ...], layer=, swallow_pads=True, reach=mm)` only on the user's yes for that declaration. `grow=` and `within=` are gone; for ground or a plane net, `board.plane(net, layers, over=[...])` | Copper calls (A fitted pour) |
| a neck between two pads, as wide as the narrower or `width=` | `board.pour(net, [PadRef(a), PadRef(b)], layer=, width=)` | Copper calls |
| a wide pour along a centreline into a pad | `board.finger(net, from_=, to=, width=)` | Copper calls |
| a finger as wide as a named pad | `board.finger(net, from_=, to=, width=PadRef(...))` | Copper calls |
| a zone over the whole board, or an outline | `board.plane(net, layers=, outline=)` | Copper calls |
| a zone over a group of parts only, wherever they were placed | `board.plane(net, layers=, over=[Part(...), Cell(...)], margin=)` | Copper calls |
| a coupled differential pair, its centreline found | `board.pair(p, n, [(padP, padN), (padP2, padN2)], layer=)` | Copper calls (Pairs) |
| two nets pairing whatever they are called | a net class of exactly two nets with `diff_pair_width`/`diff_pair_gap` set, in the board's .zen | Copper calls (Pairs) |
| silk text on a connector, jumper, switch or LED | `board.label(item, text, side=)` | Labels |
| a routed net kept, relative to its pads | `placemat route <script> --adopt NET` | Commands (Keeping routed copper) |

## Read the board

The questions a session asks between runs, and the command that answers
each from the board placemat already holds. Reach for these before grepping
a `.kicad_mod` or loading pcbnew.

| you want to know | run | section |
|---|---|---|
| what the parts are called, where they are, the totals | `placemat parts <board>` | Commands |
| how a long command is going (or how one that died ended) | `placemat watch [PID\|LABEL]` | Live progress |
| a pad's copper box, net, centre and pin name | `placemat measure <board> <part> --pads` | Commands |
| a footprint's pads before it is on a board | `placemat measure <path>.kicad_mod --pads` | Commands |
| which item sets each side of a part's drawn envelope | `placemat measure <board> <part> --envelope` | Commands |
| each track segment of a net and what its ends land on | `placemat measure <board> --copper [NET ...]` | Commands |
| how near each part stands to a keepout | `placemat measure <board> --keepouts [NAME ...]` | Commands |
| the silk texts and marks on a board | `placemat measure <board> --labels` | Commands |
| one copper layer by net (zone fills, polygons, tracks, vias, pads), and tracks inside another net's zone | `placemat layer <board> <LAYER>` | Commands |
| which nets matter: span, routed length, detour, vias | `placemat nets <board>` | Commands |
| what is at a point, where a via fits, a clear path between two pads | `placemat occupancy <board> --at / --via-near / --corridor` | Commands |
| each DRC violation, with the parts' instance paths | `placemat drc <layout.kicad_pcb>` | Commands |
| what changed between two runs | `placemat impact <run> <run>` | Commands |
| the placement drawn, in seconds | `placemat preview <script>` | Commands |
| the layout live in a browser: each step as it settles, what an edit moved | `placemat studio <script>` | Studio |
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
| `board.keep_in` | the board's copper-to-edge rule: how far inside the edge copper stays, and where an EDGE item's reach lands; a courtyard or body only has to stay inside the edge itself |
| `board.reach(item, rotation=, face=)` | the item's body, pads and silk together, as a box at the origin |
| `board.height_of(part)` | the part's height in mm from its `Pm.Height` field; an error naming the field when it has none |
| `board.parts(net=None)` | every part on the board as a `Part`, or those with a pad on `net`: derive drops and checks from the netlist |
| `board.envelope(item, rotation=, face=)` | what the placer keeps for the item under `[place] envelope`, as a box at the origin - the number `row()`, `block()` and `Beside` already space by; read it to check a gap's arithmetic, not to build a row or a stack by hand |
| `board.claim(item, rotation=0, face=Face.FRONT)` | everything the item claims at that rotation, at the origin: its reach (body, pads, silk) and its courtyard together - what `row()`/`ring()` actually space by, so a zero gap is courtyards touching. A question to check a gap's number against, not a coordinate to place from |

The same answers from the command line, for when no script is running, are
`placemat parts <board>` and `placemat measure <board> <part> --pads`.

## Setup

`board.rect(width, height, chamfer=0.0, radius=0.0, holes=(), web=0.0, draw=None)` - the
outline, origin top-left, y down; `draw=False` gives a fragment a frame that
is never drawn. The old name, `board.size(...)`, is refused with an error naming `board.rect(...)`.
`board.rect(fit=True, margin=None, chamfer=0.0, radius=0.0)` - a fragment's
frame (never drawn) sized to its content: the box round everything placed (each
part as the placer claims it, labels, tracks, vias, pours) plus `margin`
(default the keep-in), set once everything is placed.
`board.rect(fit=Axis.X, height=, margin=None)` or `fit=Axis.Y, width=` - a frame
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
board.place(cell, at=Pin(Part("c.member"), Location(x, y)), rotations=Turns.ANY)  # on the point, its turn searched (one freedom)
board.place(cell, at=Polar((r_min, r_max), None, about=centre), rotations=Turns.TANGENT)  # searched in a band, turned to the tangent at each spot
board.place(cell, at=Polar(r, None, about=centre), rotations=Turns.TANGENT)  # on a ring at exactly r, facing out at the bearing it lands on
board.place(item, face=Face.EITHER)                                     # searched on both faces; the front unless the back is better
board.place(item, at=Near(Location(x, y)), radius=20, budget=5_000_000)  # a search that may judge this many candidates
board.place(cell, arrangements=["default", "pair.upright"])          # a cell: the arrangements of its module the search may take
```
`item` is a `Part` (schematic instance), a `Cell` (a stamped group) or a block
(below). One declaration per item. `why=` is recorded in the run. A FIXED
or EDGE item that lands on another is a script error: the run stops
there with the collisions, before anything is searched (`placemat run
--keep-going` records them as findings and carries on). A finding names
a cell member with its cell: `j_out (edge): J5 courtyard overlaps cell
a1's R2 courtyard`.

**A cell of several jobs.** At each run, placemat groups a cell's members
by the nets local to it: a net every one of whose pads, board-wide, sits
on this cell's own members; a `board.plane()` net is never local,
whatever its pads. Two members are in one group when a local net joins
them, directly or through others; `place.split_min_group` (2) is the
least members a group needs to count. A cell with two or more such groups
is a finding of kind `split`, naming each group and the parts no net
inside the cell joins to another: "m: its parts form 3 groups joined only
by board-level nets: U3, C7, R2; U5, R4; Q2, R9 (and 4 parts no net
inside the cell joins to the others: C1, C2, C3, R1; judge each by what
places it: a bypass capacitor stays with the IC it serves, a sensing part
at what it senses). Parts with
no close placement requirement in common may be split into cells of
their own." It carries no run-score weight (score.py), and the same text
is a note on the cell's step.

**A number on a `Centre` is a coordinate, and a script says so.** `Centre(30, 12, coordinates=True)` places by coordinates;
without the flag each axis is a reference (`X(pad)`, `Y(pad)`, a `Mid`) or `None`. `coordinates=False` is the default and
is never written: a script that writes it gets a `setup` notice (`setup.centre_flag_default`) and a suggestion that removes
it. A number without the flag is refused where the `Centre` is written (a `ValueError` saying what to write: a relation such
as `Beside`, a pad's reference on the axis, or `coordinates=True`).
`Location` is coordinates by its name and takes no flag. A suggestion never writes a number into a `Centre` or a `Location`,
never sets `coordinates=True`, and never edits a `Location` or a `Centre` with the flag; it may free one axis of an intent `Centre` (`Centre(X(pad), None)`).

**Degrees of freedom.** Each kind of place takes some away. `Location(x, y)`,
`Centre(x, y)` and `Pin(key, x, y)` fix both coordinates (the origin, the
body centre, or the item's own pad `key` (a number or a net), each axis a
number or a reference, and the two axes may name different parts:
`Pin(1, X(Part("j1")), Y(PadRef(Part("u1"), 14)))`): a cap whose pad must
sit on a pin's axis, a diode whose pad faces another's, is a `Pin`.
`Pin(key, point)` says one point instead of two axes: a `Location`, a
`PadRef`, a `Mid`, any place a script can name. A `PadRef` with `edge=` is
a point on that edge of the target pad that puts the item's pad `key`
against it, outside the target: see "A part's pad on another pad's edge"
below. On a cell, which has no pad of its
own, `key` is a `CellPadRef` or a `PadRef` naming one of its members' pads,
or a member `Part` for that member's footprint origin (a winding's arc
centre, which is no pad); the cell is carried rigidly so that pad, or
origin, lands on the point. `Location(30, None)` or
`Centre(None, y)` fix one: the item slides along the line, starting across
from what it connects to when any of that is placed, else at its middle alone or
sharing it evenly with the items pinned to the same value, aside from what
is there. `Centre(x, None, toward=Edge.SOUTH)` starts at that end instead,
and takes the legal spot farthest toward it; a cell is judged member by
member, so a height band stops its tall members while its low ones may
stand in the band, and the step names what stopped it. `toward` must name
an end of the free axis. `OnEdge(edge, along=)` fixes both: the reach at the
keep-in, and `along` the edge a number in mm, a reference, `Along.START`,
`MID` or `END`, or `Fraction(0.3)` of the usable length, the same on
every edge. `OnEdge(edge)` fixes one: it slides along the edge, midpoint
alone, the k-th of n at (k+1)/(n+1) with its fellows. `Near(location)` and
nothing fix none. Everything with a freedom left is searched, so it goes
down with the searched items. Within a priority tier the item with fewer
freedoms goes first: a slide (one freedom: `Centre`/`Location` with one
axis `None`, `OnEdge(edge)`, a `Polar` ring or spoke, `OnRim()`, a stretch
of `board.edge(facing=)`, a point whose turn is searched) before an item
searched in two (nothing, `Near`, a `Polar` band), so a large item does not
take the line a slide runs along. Items with the same number of freedoms
go in rank order. (`place.order = "room"` orders by legal spots instead; see
Order by room.) With no `rotation=`, an item
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

**Origins.** `Origin(Part("a"))` is a part's footprint origin as placed, a
point wherever a point is taken: `at=`, `X()`/`Y()`, `Mid`,
`Polar(about=)`, `Pin(key, point)`. `board.place(Part("b"), at=Origin(Part("a")),
rotation=Turned(Part("a"), 0))` stands b's own origin on a's, as
`at=Location` does, and waits for a. `Origin(Cell("c"))` is the cell's frame
origin, the (0, 0) its fragment was stamped in, carried by the placement the
cell was given; a cell is placed by a member's origin with
`Pin(Part(member), Origin(...))`, not `at=Origin(...)`. `X(Part("a"))` is
still a's body centre. `at=Mid(a, b)`, the midpoint of two references (pads,
origins), stands the part's origin there too, as `at=Location` does (a
cell's box centre), and waits for what it names: a pad-less outline
between two pins is `at=Mid(PadRef(Part("j_p"), 1), PadRef(Part("j_n"), 1))`.

**Own pad midpoint.** `Pin(Mid(10, 11), x, y)` (or `Pin(Mid(10, 11), point)`)
puts the midpoint of the part's own pads 10 and 11 on the point, at any
turn and face; the keys are as `Pin` takes them (a number, a net, a
`PinName`), and two different pads. `Beside(item, side, align=(Mid(10, 11),
their))` lines that midpoint up as an own pad is, `their` a `PadRef` or a
point of the axis `side` leaves free: an `X(...)` for a north or south
side, a `Y(...)` for east or west, or a `Mid`/`Origin` (its coordinate on
that axis). `Pin(key, ..., land=Land.LARGEST)` or `land=2` puts one land of
a pin drawn as several on the point, as `PadRef(land=)` names one (counted
from 1, in the footprint's order); `Mid` takes no `land=`.

```python
board.place(Part("ldc"), at=Beside(Part("tank0"), Edge.SOUTH,
            align=(Mid(10, 11), X(Mid(PadRef(Part("l_ring0"), "B"), PadRef(Part("l_ring1"), "A"))))),
            rotation=0, why="the coil inputs centred between the windings' terminals")
```

**Turns.** `rotation=Parallel(a, b, degrees=0)` turns the part so its own
x axis (its footprint's 0 degree axis) lies along the line from point `a`
to point `b`, plus `degrees`: any angle, not only right angles, and the
part waits for both points (pads, an `Origin`, a `Mid`; not a point of the
part itself). On the back face the part's own x axis is the mirrored one,
and it still lies along the line. `Bearing(a, b, degrees=0)` is the compass
bearing of that line (0 north, 90 east, as `Polar` reads one) plus
`degrees`, for `Polar`'s bearing, which then needs its radius.
`Beside` stays on the board's axes; a stand-off along a turned line is
`Polar` and `Bearing` from a pad:

```python
line = (PadRef(Part("l_ring0"), "A"), PadRef(Part("l_ring0"), "B"))
board.place(Part("c_tank0"), at=Pin(1, Polar(TANK_GAP, Bearing(*line, 90), about=line[0])),
            rotation=Parallel(*line), why="the tank parallel to its winding's terminals, off along the normal")
```

`rotation=Facing(PadRef(Part("ldc"), 9), Edge.NORTH)` is the one of the
part's four right-angle turns where that pad's way out (its row's outward
axis, `_pin_normal`'s, as fanouts and escapes read it) points at the
edge; `Facing([PadRef(...), ...], edge)` takes a row of pads. It is settled
when the part is declared, from the part alone, and refused naming the pads
when their ways out differ (two rows). A pad with no row (a ball in a grid, a
square pad at the corner of the pad field, a lone pad) has the direction
from the pad field's centre through the named pads' centroid, snapped to an
axis: name the outermost row or column of a grid, `Facing([PadRef(p, "B2"),
PadRef(p, "A2")], Edge.SOUTH)` puts that column on the south side. It is
refused, saying why, when that direction is none (the centroid at the
field's centre) or a diagonal (one corner ball alone). On the back face it
is the turn that faces the side as seen from the front. `rotations=` with
any of `Turned`, `Parallel` or `Facing` is refused.

`Facing(1, Edge.WEST)` and `Facing("DRAIN", Edge.SOUTH)` name a pad by a bare
key (number or net) that each part resolves for itself, so one value serves
a row: `board.row(items, edge, rotation=Facing(1, Edge.WEST))`. `rotation=` of
`row()`, `ring()` and a run row is a number, a `Facing`, or a list of either,
one per item. `Facing(pad_key, toward=PadRef(other, "VCC"))` turns the part
so its pad's way out is opposite the way out of that pad, which makes the pad
face it for a part standing on the side of `other` where that pad lands
(`Beside(other, SideOf(...))` puts it there). It waits for `other`, as
`Turned` does; it is refused in a row. `toward=SideOf(PadRef(other, key),
along=True)` turns the pad's way out opposite the row end that pad lies at,
for a part standing there (`Beside(other, SideOf(PadRef(other, key),
along=True))`).

A track leg whose ends differ by less than `copper.straight_tolerance`
(0.002 mm) on one axis is drawn as one straight segment, not a straight
plus a sub-micron jog; `placemat measure --copper` does not flag it as off
0/45/90.

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

**The turns `rotations=` names.** A list of angles (any angle, `range(0, 360,
5)`), a number, the step in degrees from 0 (`rotations=5` is 0, 5 ... 355;
between 0 and 360), or `Turns.ANY`, every `place.bearing_step` degrees
(default 5.0), so a script need not carry the step. `Near(rotations=)` takes
the same. Each turn is another candidate at every point scanned, so a fine
step costs that many times the scan. `Turns.TANGENT` is a turn taken from the
spot rather than a list: see "A turn that follows the curve", under Round
boards.

**A point with turns to search.** `rotations=` on a place that is a point -
`Location`, `Centre`, `Pin` (a part's pad, a cell's member pad, or a member's
origin, `Pin(Part("c.member"), point)`), `Origin`, `Mid` - leaves the item on
the point and searches its turn, as `OnRim()` searches a slide: the item is
searched, with one freedom, and waits its turn in the rank. Each turn is laid
as the declaration lays it (the point stays on its spot), kept when the item
is legal there - the board's keep-in judged by what a member is, a round rim
and a member drawn as an arc, keepouts, hard-limit discs, other items, carried
vias giving way - and scored as a search scores: links, `Pm.Emits` and
`Pm.Limit` pairs, `board.push`, escape lanes. The cheapest wins; a tie goes to
the turn nearest `rotation=` (0 without it), then the smaller angle, so with
nothing to pull it the item keeps the turn it was given. The step says
`turned 180 of 72 bearings tried about its point, cost 17.70`.

```python
board.place(Cell("winding"), at=Pin(Part("winding.a"), Location(x, y)), rotations=Turns.ANY)
board.keepout(Circle(4.0), "arms", at=Location(ax, ay), why="where the arms join")  # a bearing to avoid is a region
```

A bearing to avoid is said by what stands there: a keepout over the region
refuses every turn that puts a member in it, and an emitter or limit pair or a
`board.push` costs the turns that stand near the aggressor. A rule area on the
cell's own rule area follows the turn taken. With every turn refused the item is
unplaced and the finding names the refusals. An item placed beside the cell
rides it (below). A keepout shaped by one of its members (`board.keepout(Part,
...)`) is refused as for any searched item, since regions are settled with the
firm items; the global solve, the cleanup pass and explore leave it on its
point. A fixed `rotation=` with no `rotations=` is laid once, as before.

**The rank.** Unless the script says, a searched item's place in the queue
is worked out from what it IS: how much board its courtyard needs and how
many pins it has, both against the rest of this board's searched items,
weighted by `[rank] area` and `[rank] pins`. Big and complex things go
down first and the small ones are fitted round them. Every step prints
`rank 4/64 (31.5 mm2, 12th of 64; 2 pins, 41st)`, so the numbers behind
the choice are in the log; no threshold is quoted because there is none.
`priority=Priority.HIGH` or `LOW` is a tier ABOVE the rank, for when the
rank is wrong, and the step then reads `(script: high)`. Within a tier a
slide (one freedom left) goes before an item searched in two, then the rank
orders. Items the rank
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
`place.drops_keep_share` of each field (0.5), rounded up and never fewer than
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
else is refused at declaration. The default is `Face.FRONT`.

**Either face.** `face=Face.EITHER` (or `"either"`) on a searched part or cell,
with no position or a `Near`, lets the search try both faces. It scans the
front as it does now, then the back, each spot judged and scored as any is:
the board's keep-in, courtyards and bodies on their own face, plated leads and
holes on both ("The far face"), keepouts by the layers they cover, via
conflicts with the other face's copper, a cell's flip rules (above), link
lengths from the pads where they land on that face, ratsnest crossings,
escape weights, `board.push` and `Pm.Emits`/`Pm.Limit` pairs. A spot on the
back costs `score.back_face` more (2.0), so the front wins an equal spot; the
back is taken when its score plus that is below the front's, or when the front
has no legal spot. With nothing to score by (no link, push or lane) the front
is taken whenever it has a spot. The step note says why a back spot was
taken. An item with no spot on either face takes the front's pockets, then the
back's, then a scan of each whole face (the step budget bounds it), and is
unplaced when none fits.

```python
board.place(Cell("m1"), face=Face.EITHER)                       # a cell with no reason to be on one face
board.place(Part("c9"), at=Near(PadRef(Part("u1"), "3")), face=Face.EITHER)
```

Links do not pull an item to the face its partners are on: the search
measures a link in the board's plane, a link between faces costs its length,
and a part on the back is mirrored, so its pads land on the other sides of it.
An item that must face something keeps a fixed face: `Face.EITHER` is refused
with a decided position (`Location`, `Centre`, `Pin`, `Beside`...), a line, an
edge, a rim or a ring, a block, and `rotation=Facing(...)`. A label follows the
face chosen; a keepout with `layers=` is judged against it, and a
through-hole lead is refused by either face's keepout. `rotations=Tangent(...)` and a `Polar` band are allowed with it; each face takes its own tangent turns ("Round boards").

**A cell's flip keeps its inner layers, which KiCad's does not.** A cell
flipped to the back swaps its own F and B copper and keeps its inner copper
(tracks, pours, zones, rule areas, buried vias) on the layer it was drawn
on, so the cell keeps the layer roles it was laid out for: a pour on the
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

**An escape** keeps a pin row's routes out, and says where they run:

```python
esc = board.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30],
                   widths={32: OUT_TRACK}, why="OUT, SENSE and PGOOD out of the north row")
board.place(Part("c_pd"), at=Beside(esc[30].via, Edge.WEST, align=(2, esc[32])),
            why="OUT's capacitor at the end of its lane, west of PGOOD's via")
board.track(Net("OUT"), [esc[32], PadRef(Part("c_pd"), 2)], layer=CopperLayer.F)
board.track(Net("SENSE"), [esc[31]], layer=CopperLayer.F)
board.track(Net("PGOOD"), [esc[30]], layer=CopperLayer.F)
```

An escape on its own is a reservation: its risers, lanes and vias are kept
clear while parts are placed, but nothing is written to the board, and the
router does not see them. A pin's lane becomes copper only when a track
begins with it (`board.track(net, [esc[pin]])`, as above); the router then
keeps it as it keeps all input copper and routes on from where it ends. So
to have the router take a fanout as laid out, draw each pin's lane. `vias=`
names only the pins that drop to another layer: a pin left out gets a lane
that ends on its own layer, for the router to continue on that layer.

`board.escape(part, pins, *, turn=None, vias=(), depth=None, run=None,
widths=None, pairs=(), chamfer=None, via_size=None, via_drill=None, why)`
gives each pin of one row a riser (straight out
along the row's way out, as `vias()` reads it) and, with `turn=`, a lane
parallel to the row, ending at a via where `vias=` names the pin. Pins are
named as a `PadRef` names a pad (number, net or `PinName`). It returns the
`Escape`. All the pins are on one row of one part, a pin on another row or
another part is refused (naming each pin's way out), and so is a pin named
twice. A pin drawn as several lands, a QFN's corner pin with a land in each of
two rows, leads out along each: it stands in the row by the land that leads
out the way the other pins do, its lane starts at that land, and an escape
whose pins have no way out in common, or two, is refused at its declaration. The lanes are worked
out when the part is placed, from its pads as placed; a row whose way out is
not along a board axis is refused.

- **Order.** With `turn=` (an `Edge` across the row: a north row turns `WEST`
  or `EAST`) the pin nearest the turn side takes the innermost lane, the next
  pin the next lane out, so no riser crosses a lane. There is no `order=`.
- **Steps.** The innermost lane's centreline is its own copper plus the
  clearance past the pads' outermost reach (`depth=` sets that distance
  instead); each next lane is a step out. A lane's copper is its via's size
  where it has a via, else its track (`widths=`, else its net's track width).
  A step is the clearance by net pair, as the router judges it (`board.rule`
  clearances count), added to the largest of: half each lane's track; half
  the inner lane's via and half the outer lane's track (the outer track
  passes the inner via); half the inner lane's track and half the outer
  lane's via (the inner track may run on past it). Two vias are not stepped
  apart by their sizes: they keep the clearance by standing apart along their
  lanes, innermost first. A lane and the via beside it keep the clearance
  wherever the via stands.
- **Corners.** Each riser runs from its pad's centre to its lane and turns;
  the corner is cut by `chamfer=` (default `copper.chamfer`), as `track()`'s
  `chamfer=` cuts one. The lanes are laid out and reserved with it, and a
  track that begins with a lane is drawn with it unless the track gives its
  own `chamfer=`, which that lane is then laid out and reserved with too. A
  chamfer's 45 runs across the inside of the turn, nearer an inner lane's via
  than a square corner is, so each via is searched clear of the 45 and of the
  square corner of every lane still to be placed; a larger `chamfer=` can
  therefore stand the vias farther along their lanes.
- **Lanes at 45.** `turn=` a `Corner` (a north row: `NW` or `NE`) runs the
  lanes at 45, a step apart across their direction. A 45 moves away from its
  row, so it stands as near the row as it may, not a lane's depth past the
  tips: the risers are staggered from the row's turn-side end, the pad there
  at the tips and each next pad of the row, named or not, one stagger (the
  step times the square root of 2, less the pitch along the row: 0.0526 mm
  for a 0.32 mm step at 0.4 mm pitch) further out. A lane is where it would be
  among lanes for every pin of the row, so two escapes of one row lay their
  lanes parallel and a lane does not move when another pin is named. A named
  lane is no nearer the tips than where its riser and 45 keep the clearance
  from the row's other pads and from the copper placed and reserved when it is
  laid out (a bypass beside the row, and the firm tracks declared from a pad of the part that is not one
  of the escape's pins to placed pads, as they would be planned), judged out to the row's depth and a track and a
  clearance whatever `run=` leaves of the lane; where no offset within
  `place.escape_via_reach` is clear it keeps the offset that is clear of the
  row, and it is an `escape_lane` finding. `depth=` sets the innermost lane's
  offset as given, and the stagger follows it. A track that begins with a lane
  draws the lane's own legs: a leg is never rerouted round copper that stands
  too near it, and a leg that runs through another net's copper is not drawn.
- **Vias.** A lane with a via ends at it, its via `via_size=` and `via_drill=`
  (default the board's, as `board.via()`'s `size=` and `drill=`; the lane's
  steps use that size). The vias are placed innermost lane first, each at the first spot along its lane, from the row's turn-side end,
  that keeps the clearance from every pad of the part, every other lane and
  the vias already placed, and from what is placed on the board (the edge,
  other nets' copper, holes, keepouts). A lane with none ends level with
  the outermost via, or one step past the row's turn-side end where the
  escape has none; `run=` (mm past that end, or each 45's length) sets the
  end of such lanes instead.
- **No turn.** Each riser runs out `depth=` past the pads' reach (default: its
  copper plus the clearance), and a pin in `vias=` ends in a via at the first
  spot out along its own axis that keeps the clearance from the part's pads
  and the vias already placed, taken in the order `pins` lists them. At a
  fine pitch alternate pins fall into a near and a far row. Where the pitch
  leaves no room beside a placed via (a lane passes it a pitch off, and the
  via needs its size and a clearance), the lane runs out to the least depth
  at which a 45 keeps the clearance from the row's pads, jogs along the row
  to the side that puts its via nearer the row, and ends in its via there: a
  0.45 mm via at 0.4 mm pitch (clearance 0.16) takes its neighbour's lane
  round at 45. A lane that finds no spot says what stands nearest in its way
  and how far off it is.
- **`pairs=[(a, b)]`** runs two neighbouring lanes together, the net class's
  pair gap apart (else the clearance) instead of a step. Their pins must be
  neighbours along the row; `pairs=` needs `turn=`.

The escape is settled when its part is placed, as a fanout is, and its
risers, lanes and vias stand in the occupancy as copper of their own nets. It
waits for the firm parts the script places relative to its part (`Beside` it, a
`Pin` or any position said in terms of its pads), so a bypass beside the chip
is down when the lanes are laid out and they keep clear of it: one escape over
a whole row, with a part standing beside the chip at the row's middle, starts
the lanes past that part without a `depth=`. A part placed relative to the
escape itself (`Beside(esc, ...)`, a lane's end or via), or to a part that is,
waits for the lanes instead, and an escape and a part that would wait for each
other are laid out as soon as nothing else can be placed. A searched part, and
the parts that ride it, are placed after the lanes. A part placed later may stand over a lane with its body, and with a pad of the
lane's own net on it, but not with a pad, a hole or other copper of another
net within the clearance; the parts a fanout lets in (linked at
`LinkWeight.SHORT`) are judged the same. Vias placed later (`FreeSpot`,
`stitch`, give way) keep the clearance from it, and an escape's own vias do
not give way. Copper of another net planned later is judged against it as
against a drawn track, until a track begins with the lane: the track's own
copper then stands in its place, and what is judged is what is drawn. The cleanup pass leaves the escaped part where the
search put it.

A searched part's lanes are weighed in its search. At each candidate the
escape is laid out as above and the candidate costs `score.escape_lane` (400)
for each lane that would meet another net's pad, hole or copper already
placed, or whose via finds no legal spot. Where no candidate lies clear the
part lands anyway and each blocked lane is an `escape_lane` finding naming
what blocks it. Only the plain search prices lanes (a part on an edge or a
rim, or one inside a cell or block, is laid out where it lands). A lane the
run never draws (no track begins with it) is a setup finding: its room was
kept for nothing.
In a module (a frame not drawn), a via on a lane, from `vias=` or a `board.via` on the lane's copper, whose lane reaches the frame's edge on its own layer without it is an `escape.via_unneeded` finding: a module names a pin in `vias=` only when its lane is walled in within the module.

What the handles are:

| handle | is |
|---|---|
| `esc[pin]` | the pin's lane, named as the pin was. As a track's first point it stands for the pin's riser, its lane and its via (`board.track(net, [esc[31]])`), and the track goes on from it (`[esc[32], PadRef(...)]`); anywhere else in a track it is refused. A track from a lane takes the lane's `widths=` track unless it gives a `width=` |
| `esc[pin].via` | the lane's via, as `board.via()` returns one: a track point, a `Past` item (`Past([esc[30].via], Edge.WEST)`) and the item of a `Beside` (`Beside(esc[30].via, Edge.WEST)` stands a part the envelope gap off it). It is drawn when a track begins with the lane or the handle is used; refused for a lane with no via |
| `align=(own_pad, esc[pin])` | in a `Beside`: the own pad centred across the lane's line (the lane's for a lane turned across the row, the riser's without a turn). The side decides the other axis, so the lane's line must run across it; a 45 lane has no line |
| `esc[pin].end` | where the lane ends (its via, or the end of its track) as a point reference: `X()`, `Y()` and a `Pin` take it, `at=Pin(1, X(esc[32].end), Y(esc[32].end))` |
| `Beside(esc, Edge.NORTH)` | stands an item beside the escape's risers, lanes and vias together |

A placement that refers to a lane waits for its part, as one that refers to
a pad does, and rides the part when it is searched.

An escape and a fanout both stay: a fanout keeps the bodies of unrelated
parts off a part's pad rows, and lets in the part's block satellites and the
parts linked at `LinkWeight.SHORT`; an escape keeps the named pins' routes
clear of other nets' copper, including that of the parts the fanout lets in.
A script may declare both. Refused at declaration: pins of another part or
row, a pin named twice, `turn=` along the row's axis (when the part's
rotation is already declared, else when it is placed), `vias=`, `widths=` or
`pairs=` naming a pin the escape does not, a pair whose lanes are not
neighbours, `run=`, `depth=`, `via_size=` or `via_drill=` of 0 or less, a
negative `chamfer=`, and a lane as any track point
but the first. At resolve, a via with no legal spot along its lane or axis
even with nothing else on the board stops the run, naming what stands in the
way (a run failure, as a collision of firm placements is); a via that only the
rest of the board blocks is a finding.

**`Near` is for what the netlist cannot say**: a thermal sensor that must
sit by the FETs it shares no net with, a test point wanted at the edge.
A `Location` constant that stands for "the power area" or "the bus
corner" is a floorplan typed by hand; the placer floorplans from the
links, and a hint on a part that has a wired, placed neighbour is a
defect. Many parts hinted at one point compete for the same rectangle and
the last of them fails to place.

**The edge is the board's.** Nothing in a script says how far from the
edge a thing sits. `board.keep_in` is the board's own copper-to-edge
rule: pads and copper stay that far inside the edge (KiCad's
`copper_edge_clearance`), a courtyard or body only inside the edge itself, so
a searched part may stand nearer the edge by its courtyard's margin. An edge
item's reach (body, pads and silk together, `board.reach(item,
rotation)`) lands there. A face that must stand proud of the edge says
`OnEdge(edge, overhang=)` with a why. A row inboard of an edge row is `behind=` it.

**Beside another item.** `at=Beside(item, Edge.EAST, align=None, gap=None)`
stands the item on that side of `item` - a `Part`, a `Cell`, a keepout
(what `board.keepout(...)` returns), an escape or the via of one of its lanes
(see "An escape") - its drawn envelope `gap` off
`item`'s. `gap` is a floor, not an override, as `row(of=)`'s is: at least
the envelope's own gap - the rule a row's default gap keeps too: the
widest of the net clearance, the component spacing and the silk
clearance, or courtyards touching under a courtyard envelope - whatever
the script gives. `side` decides one axis and `align=` the other: beside a
`NORTH` or `SOUTH` side, `align=` sets x; beside `EAST` or `WEST`, y.
FIXED like `Pin`: `item` is placed firmly (FIXED or EDGE) before it, or is
searched and this item rides it (see Riders); it keeps the rotation the
script gave, or its default -
`Beside` does not turn the item to face `item`. The distance is from the shapes
`item`'s envelope is made of (pads, mask, silk and body under a physical
envelope, the courtyard under a courtyard one), not from the box round them: a
mark drawn outside the body at one corner holds the item off only where it
stands over it. Where that would put the item in the way of something else
already placed (a part, a reservation, the edge) it is moved on out along its
side to the first place the collision rule lets it stand (`place.beside_step`, up
to `place.beside_reach`), and where a part placed before it is in its way and
the two can be taken the other way round, it is placed first. The item also
keeps clear of the copper the script declares (`board.track`, `board.via`)
between parts placed by then: that copper is planned provisionally, and the part
stands where it leaves the room (`place.copper_room`); a part that stands nearer
than the box put it and is an end of copper that then meets other copper goes back
to the box's distance. `fixed.room` says a part for which no place within reach
keeps that room. `align=` lines it up
across the side, flush as `OnEdge` and `row(of=)` are, never the placed
part's body centre left overhanging the corner: a `PadRef` - the placed
part's own pad on the same net lands level with the named pad -
`(own_pad, their_pad)` when the nets differ, or an `Along` of `item`'s side - `START` flush with its
start, `END` flush with its end, `MID` (default) centred. The pad may be
`item`'s own or any other part's placed firmly by then: west of a
capacitor, level with a driver's pin, is `Beside(Part("c_boot"),
Edge.WEST, align=PadRef(Part("u1"), "SW"))`.

`side` may be `SideOf(PadRef(Part("u"), "VCC"))` (or a list of pads, as
`Facing` takes): the board side the pad's way out points at once `u` is
placed, its turn and face applied and snapped to the nearest axis - the same
way out `Facing` reads, so `Beside(u, SideOf(pad))` stands the part where
`Facing(pad, edge)` would have put that edge. `u` is placed first. A
`SideOf` side with a `Past`, a lane or an `X`/`Y` point in `align=` is
refused: those check the side's axis now.

`SideOf(PadRef(Part("u"), 1), along=True)` is the side where the pad lies
along its row instead of the row's outward normal: the end of the row the pad
is nearer, with `u`'s turn and face applied. The row is the pads that share
the pad's way out, and the end is which side of the middle between its
outermost pad centres the pad lies on. It names one pad. A pad exactly mid-row (the middle pin of an odd
row) is refused, saying neither end is nearer, and so is a pad with no row (a
grid, a corner pad, a lone pad). Use it for a part that stands past the end
of a package on the side where a given pin lands:
`Beside(u, SideOf(PadRef(u, 1), along=True))`. There is no eager
`board.side_of(...)`: a side a script would branch on is a relation to
say (`SideOf`, `Facing(toward=)`, `row(over=)`).

`copper=True` measures the standoff from pad copper, not envelopes: the part
stands as near `item` on `side` as its pads allow, every pad of it keeping,
from every pad of `item` (of a cell, its members') of another net, the
clearance the pair needs (by net pair, `board.rule` clearances included)
plus `gap`, which is then added to it, not a floor against the envelope's
gap (default 0.0). Pads are measured as their copper outlines, so a round
or turned pad gets its true standoff, and only pads that face each other
across `side` at the `align=` count. Pads of one net set no distance, so a
net tie's pad 1 on the output net may stand on that net's pad while its pad
2 stands the clearance off it; the tie's own-net exemption in KiCad's DRC
does not shorten the distance. The part's body, courtyard and silk are
judged afterwards as for any placement, and a body that overlaps `item`'s
at that distance is refused. A part with no pad facing a pad of another net
is refused. A keepout or an escape has no pads, so `copper=` is refused for
them.

`align=(own_pad, Past(pads, Edge.WEST, lane=None))` stands the own pad's
facing edge past the pads' `edge` side instead of level with a pad. The
distance is the worst clearance, by net pair, from the own pad's net to
the pads'; with `lane=` a net it is room for one track of that net between
them: the clearance from the pads to the net, its track width (or
`width=`, the copper its current needs: a pour's width past a switch pin),
and the clearance from the net to the own pad. `Beside`'s side still decides the
other axis, so the Past's edge is on the axis the side leaves open (`EAST`
or `WEST` beside a `NORTH` or `SOUTH` side). The Past takes pads, cutouts
with a decided place, stretches of the board edge or of a hole, and parts
and cells: what has its place before the part does. A cutout or a stretch
of edge holds the own pad the board's copper-to-edge clearance off (with
`lane=`, that plus the lane's width and its clearance to the own pad); a
part's or a cell's envelope holds it nothing off, and the part's pads
their clearance. A via or a track is refused (a placement is decided
before any copper is planned), a label too (it gives way to the parts
placed after it), and a cutout with a freedom (the board slides it once
every firm item is down). The Past takes no `across=`. What it names is
placed or cut first, as for any firm placement. The track then takes the same line as a
waypoint, `Past([PadRef(...)], Edge.WEST)`.

With a `Corner` in place of the edge, `(own_pad, Past(pads, Corner.NE,
lane=Net(...)))` stands the own pad off the 45 that passes the pads' NE
corner: the own pad's corner facing the 45 (its SW corner) stands the same
distance out along the diagonal from the pads' corner, measured across it.
`Beside`'s side decides one axis and the corner the other, so any side
goes with any corner. The track takes the 45 as a waypoint,
`Past([PadRef(...)], Corner.NE)`. A width sized for a current
is a fact: a named constant citing IPC-2221 at the board's `check.rise_c`
(`placemat settings` prints it) and the layer's own copper weight, from the
board's stackup; the run's `current-path` check then judges the copper
drawn in the lane.

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
board.rect(width=board.keep_in + power.depth + 4 + bus.depth + board.keep_in, height=max(power.end, bus.end) + TOP)
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
row aligns across itself. The distance is taken as `Beside`'s is: from the
shapes `of`'s envelope is made of, not the box round them, but one distance
for the row, the nearest at which every item clears the shapes it faces, so
the row stays on one line: a mark drawn outside the body holds the whole row
off only if an item stands over it. An item that then stands nearer than the
box put it, and would be in the way of something placed, is moved on out
(`place.beside_step`, `place.beside_reach`). A row that overhangs, a row
riding a searched `of` and a row with an item taken back to the box (copper
declared where it stands nearer) keep the box. `align=Along.START/MID/END` is where along
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

`over=[PadRef, ...]` (one pad per item, in the order the items are given) orders a
row by where those pads lie along it, increasing (x for a north or south
row, y for east or west), once they are placed: each item stands among its
neighbours as the pad it serves stands among theirs, so a script need not
know which pin landed west. The row waits for the pads' parts; equal
coordinates are refused naming the items. It composes with every anchor
(`of=`, `centre=`, `start=`, `align=`, `before=`/`after=`). An order read
off the items' nets was not built: a net reaches several pads, or none
directly.

```python
board.row([R_SCL, R_SDA], Edge.NORTH, of=Part("u1"),
          over=[PadRef(Part("u1"), "SCL"), PadRef(Part("u1"), "SDA")])   # whichever pin is west, its resistor is
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
to write, but its script may give it a frame, `board.rect(w, h,
draw=False)`, sized from its own rows, so the controls that must meet
a board edge are a `row` on the frame's edge; the board supplies the
real outline. What is not on an edge is said in terms of parts and pads.
A fragment with no edge to meet takes `board.rect(fit=True)`:
its main part at the origin, the rest from its pads, and the frame is what
they fill plus the margin - no frame or anchor position computed by hand. A
searched item on a fit board searches round what is placed so far, by
`place.fit_room` (10 mm) and its own size; a `board.plane()` with no
`outline=` is planned after the frame and inset from it; a keepout needs a
place of its own, not a freedom. A frame edge, `board.centre`,
`board.width` and `board.height` are refused on a fit board: the plan's
outline is the frame once it is resolved.

**Arrangements.** A module can declare alternatives to how it is laid
out. The module run proves each on the module's own terms and writes the
ones that pass into the fragment; the board's search chooses among them.
A module that declares none, and a board that stamps only such modules,
run as before. A module that adds alternatives needs its own script run
again. Only a module's script, whose frame is not drawn, may declare
them: a board script that does fails with a script error naming the
declaration's line.

```python
board.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST), why="bypass at VIN")
board.alternative(Part("c_in"), "turned", rotation=180)
board.alternative(Part("r_pull"), "turned", rotation=180)

pair = board.unit("pair", Part("c1"), Part("r1"), why="the filter pair moves as one")
board.alternative(pair, "flat",
                  Alt(Part("c1"), rotation=0),
                  Alt(Part("r1"), at=Beside(Part("c1"), Edge.EAST)))
board.alternative(pair, "upright",
                  Alt(Part("c1"), rotation=90),
                  Alt(Part("r1"), at=Beside(Part("c1"), Edge.NORTH)),
                  why="the pair stands in the column")

board.exclude("c_in.turned", "pair.upright", why="both stand in the one column")
```

- `board.alternative(item, name, **keywords)` adds an option to the
  item's `place()`, which stays its default option. An option takes the
  keywords of `place()` that say where an item goes (`at=`, `rotation=`,
  `rotations=`, `face=`, `radius=`, `step=`) and `why=`; every keyword
  it does not give is the item's own, so `rotation=180` alone keeps the
  `at=`. The item is a part the script has placed with `place()`: a part
  of a row, ring or block, and a cell, are refused. A searched item may
  have options too, as each arrangement is a full resolve.
- `board.unit(name, *members, why="")` declares a unit: parts the
  script has placed with `place()` that move as one, given one by one
  (a list is refused; `board.group` is the KiCad group on the written
  board). Its default is each member's own `place()`. It returns the
  unit, which `board.alternative(unit, name, *alts, why="")` takes to
  add one option, one call per option: an `Alt(member, **keywords)`
  (the keywords of `alternative`) for each member it moves, each at most
  once; a member it does not name keeps its `place()`. A unit's
  alternative takes `Alt`s and `why=`, no place keywords; an item's takes
  keywords and no `Alt`s. Option names are unique within the unit. A
  unit with no option is an error where the script finishes declaring.
  Declare a unit's options when its members only make sense moving
  together; otherwise each member's own `alternative` gives more
  combinations for the same declarations. A row's or ring's members may
  be members of a unit.
- A part is in one unit only, and a member of a unit has no
  `alternative` of its own: a second unit naming it, an item's
  alternative on a unit's member, and a unit naming a part that has one
  are errors at the second call, each naming both declarations.
- `board.arrangement(name, *alts)`, the 0.99.15 form, is removed: it
  raises `TypeError` at the call. A unit with one option does what it
  did, and combines with the module's other items and units.
- `board.exclude(*choices, why="")`: no combination holding all of
  `choices` is laid out. A choice is `item.option` or `unit.option`. Use
  it for combinations that cannot stand together, so the run does not
  prove them, and to bring a module under `place.arrangements_max`
  without dropping an option. Fewer than two choices, a choice twice, a
  choice the module does not declare (a combination id is not one), and
  two options of one item or unit are errors where the script finishes
  declaring, with the declaration's line.
- The units of a module are its items with options and its units, in
  the order the script declares them: an item at its `place()`, a unit
  at its `board.unit` call. Its arrangements are the default, then every
  combination of the units (each contributing its default and each
  option) in `itertools.product` order with the first unit changing
  slowest, less the excluded ones. A module with no unit has its items'
  combinations in `place()` order, as before.
- An arrangement's id is `default`, or its units' choices in unit order
  joined by `+`: `item.option` or `unit.option`
  (`c_in.turned+pair.upright`). Option and unit names are lower-case
  words, digits and `_`; `default` is refused, a name may be declared
  once, and a unit may not have the name of an item with options. The id
  is what the lock, findings, step notes, the studio and the board's
  `arrangements=` use. `choices` is the same as data, `{unit: option}`.
- Two arrangements that lay out the same places and copper are one: the
  later is dropped with an `arrangement.duplicate` notice naming both.

`only=` on `board.track`, `pair`, `via`, `vias`, `stitch`, `pour`,
`plane` and `finger` names the arrangements the declaration exists in.
Each entry is `default`, a choice (`item.option` or `unit.option`), or
choices joined by `+` in unit order; the declaration exists in every
arrangement that holds all the choices of some entry:

```python
board.track(Net("FB"), [PadRef(Part("r1"), 2), PadRef(Part("u1"), 7)], only=("pair.upright",))
board.pour(Net("SRC"), ..., only=("c_in.turned+r_pull.turned",))
```

The track exists in `pair.upright` and in every combination holding it,
`r_pull.turned+pair.upright` among them; the pour only where both turns
are taken. Without `only=` the declaration is in every arrangement;
`only=("default",)` is the module's own layout alone. An empty `only=`
and a bare string are refused at the call. An entry that names no
choice of the module, names them out of unit order, or that every
arrangement holding it is excluded, is refused where the script
finishes declaring, with the declaration's line. Copper drawn from an
item's pads follows the item without `only=`; `only=` is for copper that
exists in some arrangements only. Copper fitted round or drawn from
other copper that has an `only=` exists only where that copper does:
each of its entries holds every choice of one of the other's.

Limits: `place.arrangement_options_max` (default 4) options per item
or unit, its default included, and `place.arrangements_max` (default 16)
arrangements per module, the default included, counted after
exclusions. A module over either is not partly accepted: the run lays
out the default only and raises `arrangement.limit` (facts: the counts,
both limits, and `excluded`, how many combinations the exclusions left
out). `place.arrangements = false` lays out the default only without a
finding.

The module run generates once, then resolves the board once per
arrangement, the default first and the rest in declared order, with that
arrangement's options laid over the items' intents and the copper whose
`only=` holds for it. Each arrangement other than the default is proven
on a scratch board of its own:

1. its resolve places every member with no critical finding, and every
   cell nested in the module stands where the default put it;
2. KiCad's DRC on the scratch board has no `real` violation and no more
   unconnected items than the default;
3. the design checks have no failed verdict, `board.accept` applied.

Warnings, notices and measures are recorded, not refused. An arrangement
that fails any step, or whose resolve or proof raises, is not offered:
it is kept in the record with its refusals and raises
`arrangement.refused` (warning), and the run goes on with the rest. The
default is always written. An offered arrangement is written into the
fragment as `placemat arrangement <escaped json>` texts on
`User.Comments` (members' places in the fragment's frame, the
arrangement's copper, its rule areas, and a digest of the default's
places), split into numbered texts of `place.arrangement_note_chars`
characters when longer. An arrangement whose note would leave no room in
a chunk is not offered (`note_chars`).

A combination is refused where two options cannot stand together; it
needs no action when each option is offered in some other combination.
An option refused in every combination that holds it, excluded ones not
counted, raises `arrangement.option_dead` (warning). Its facts are
`unit`, `option`, `choice` (the option as an id names it), `refused`
(the ids) and `reasons` (each id's refusals, as `arrangement.refused`
gives them). The board is never offered such an option: fix it or drop
it.

The run keeps each arrangement in `arrangements/<id>/` of its run
folder: `layout.kicad_pcb`, `drc.json`, `reuse.json` (and
`reuse.partial.jsonl` while it runs), and with `--render` the render of
each arrangement that was proven, offered or not. A stopped run resumes
each arrangement from its own record. `timing_s["arrangements"]` is the
seconds for the other arrangements' resolves and proofs;
`timing_s["resolve"]` is the default's alone.

`run.json` is the default's, as before, and gains `arrangements` when
the module declares any alternatives or is over a limit (in the second
case the one entry is the default). One entry per arrangement, the
default first:

```json
"arrangements": [
  {"id": "default", "choices": {}, "offered": true, "dir": "arrangements/default",
   "metrics": {"drc": 0, "findings": {"warning": 1}, "measures": {}},
   "extent": [{"item": "c_bulk", "sides": ["east", "north"], "protrudes_mm": 1.8}]},
  {"id": "pair.flat", "choices": {"pair": "flat"}, "offered": false, "dir": "arrangements/pair.flat",
   "why": [{"unit": "pair", "option": "flat", "why": "", "unit_why": "the filter pair moves as one"}],
   "metrics": {"drc": 2, "findings": {}, "measures": {}}, "extent": [],
   "refused": [{"form": "drc", "bucket": "clearance", "count": 2}, {"form": "verdict", "check": "loop", "item": "c_in"}]},
  {"id": "c_in.turned+pair.upright", "choices": {"c_in": "turned", "pair": "upright"}, "offered": false,
   "why": [{"unit": "pair", "option": "upright", "why": "the pair stands in the column",
            "unit_why": "the filter pair moves as one"}],
   "excluded": {"why": "both stand in the one column", "by": ["c_in.turned", "pair.upright"]}}
]
```

- `metrics.drc` is the number of `real` DRC violations, or null when DRC
  was not run; `findings` counts the arrangement's findings by severity;
  `measures` are the inputs of the run score for that arrangement,
  recorded for comparison and not summed into the module's score. The
  run's score is the default's.
- `extent` lists the members whose box reaches the module's outline on a
  side: the item, the sides, and `protrudes_mm`, how far it stands past
  the next member on its most protruding side. It is measured on the
  default and on each arrangement whose resolve completed. A listed
  member with no alternative raises an `arrangement.extent_fixed` notice
  on a module that declares any, and on one that declares none, or runs
  with `place.arrangements` false, when it protrudes more than
  `place.extent_notice_mm`.
- `why` lists the reasons of the choices an arrangement holds, in unit
  order, for those the script gave one: an item's option as `item`,
  `option` and `why`; a unit's option as `unit`, `option`, the option's
  `why` and the unit's own (`unit_why`). It is absent when there are
  none. `placemat run` prints them after the arrangement's row.
- A combination an exclusion leaves out has `offered` false and
  `excluded`, the exclusion's `why` and its choices (`by`), and no
  `dir`, `metrics` or `extent`: it is not laid out. These entries come
  after the laid-out ones. `placemat run` prints each as excluded and
  the studio lists each as a notice.
- A duplicate has `offered` false, `duplicate_of` (the id it matches)
  and `metrics` null. An arrangement whose resolve raised has `offered`
  false, `refused` and `metrics` null, and no `extent`; one whose proof
  raised has the same with its `extent`.
- `refused` holds records, each a `form` and its facts, rendered to a
  sentence only where shown (`placemat run` prints one line per
  arrangement; `arrangement.refused` carries `id` and `refused`):

| `form` | Facts | Meaning |
|---|---|---|
| `unplaced` | `item` | a member the resolve gave no place, or a required item with no place |
| `finding` | `cause`, `item` | a critical finding of the resolve, or items that collide where they stand |
| `nested_cell` | `item` | a cell inside the module stands elsewhere than in the default |
| `drc` | `bucket`, `count` | KiCad's DRC found `count` violations of that kind |
| `unconnected` | `count`, `default` | more unconnected items than the default has |
| `verdict` | `check`, `item` | a design check failed and is not accepted |
| `escape` | `escape`, `part` | a declared escape cannot be laid out with its part as placed |
| `error` | `type`, `message` | the resolve or proof raised that error |
| `note_chars` | `chars` | `place.arrangement_note_chars` leaves no room for the note |

**On the board.** A cell stamped from a module that offered arrangements
takes one of them. `arrangements=` on the cell's `place()` is an id or a
sequence of ids (`"default"` is the module's own layout):

```python
board.place(cell, arrangements="pair.upright")               # pinned: laid in that arrangement
board.place(cell, arrangements=["default", "pair.upright"])  # the search tries these, in this order
board.place(cell)                                        # the default, then every arrangement the cell offers
```

- It is for a cell only: any value on a part or a block raises
  `TypeError`, the empty sequence included. Anything that is not a
  string or a sequence raises a `TypeError` saying `arrangements=` is an
  id or a list of them; an empty string, or an item that is not a
  string, raises one saying ids are text. A repeated id counts once.
- A riding cell takes its arrangement only when it is pinned to exactly
  one id; with several ids or none it is laid in its default.
- An id the cell does not offer leaves the cell unplaced with an
  `arrangement.missing` finding (critical; facts `item`, `asked`,
  `offered`). A cell with `place.arrangements` false offers only the
  default, so a pin to any other id is missing. A rider of a cell skipped
  for its arrangement is unplaced as a rider of an unplaced item.
- The lock and freeze hold an arrangement (see "The lock" and "Freeze").
  A lock entry whose arrangement the cell no longer offers is released,
  and the cell is searched as its call says, with an
  `arrangement.missing` warning whose facts add `source: "lock"`.
- A note that cannot stand gives one `arrangement.stale` warning per
  ignored arrangement and reason (facts `cell`, `reason`, `ids`); `text`
  carries no ids. The cell is laid with the arrangements that remain.
  With `place.arrangements` false the board ignores the notes and raises
  none. The reasons are:

| `reason` | A note is ignored because |
|---|---|
| `version` | it is of a version this placemat does not read |
| `base` | it does not match its own digest of the module's default places |
| `offset` | the cell's stamp no longer matches the module's default places |
| `member` | it names members the cell does not have, or the cell has members it does not name |
| `net` | it names a net the board does not have |
| `text` | its text is not whole or does not parse (malformed) |

`run.json`'s `placements[cell]` and each settled item of `plan.json` (and of
the `item` event) carry `"arrangement": "<id>"` when the cell stands in an
arrangement other than the default.

The writer puts an arranged cell in its arrangement before it moves it
into place. The cell's copper, keepouts (rule areas and drawings) and
texts are replaced by the arrangement's, its carried vias are thinned
against the arranged copper, and its zones are refilled. The cell's
members go to the arrangement's places.

**How the board chooses.** A cell that may take more than one
arrangement is searched in each, the default first and the others in the
order of `arrangements=` (or the order the module offers them). Each is an
ordinary scan of the cell as that arrangement stands it, on both faces for
a cell placed on either. The scores are compared as the search scores a
spot, a non-default arrangement carrying `score.arrangement` on top.
A non-default arrangement is taken only when it beats the default by
`place.arrangement_margin` (default 0.5 mm); within the margin the default
stands. The margin is not asked when the default has no legal spot, of a
cell whose `arrangements=` names its choices, or of an explore's draw.
The step's `arrangement` note names the one taken and its score, and each
arrangement tried with its total, whether it had a legal spot, and whether
the best so far cut its scan short. When an arrangement scored better and
stayed within the margin, the note says which, by how much, and that the
default stands. When none has a legal spot the note lists those tried.

**A firm cell.** A cell held at its decided spot (`Location`, `Beside` and
the other decided forms) tries its arrangements there: each legal one is
scored once at that spot and compared as above, the margin included
(not asked of a cell whose `arrangements=` names its choices). When
none is legal the cell stands in its default, where its declaration puts
it, or in the first arrangement `arrangements=` names when the default was
not tried, and `fixed.part` is raised as for any firm collision; its
`arrangements` fact lists every other arrangement's refusal, each as `id`
and `why`. Each firm pass chooses a firm cell's arrangement afresh, and
the choice is compared with the one the pass before took. The passes
settle only when each such cell took in a pass the arrangement it took in
the one before, so in the first pass, which has none
before it, a board with such a cell runs a second pass. A cell that still
changes between the last two passes raises `fixed.room_unsettled` with
`item`, `passes` and `arrangements`, every arrangement it took in the
order it took them; what stands beside it was placed against its last
pass's choice.

**Time limit.** A step that gives up at `--step-limit` before it has
scanned every arrangement of a cell raises `time.step_limit` with the
arrangements it did not reach in `arrangements`.

**Replay.** `reuse.VERSION` is 5, which records a cell's arrangement in a
placement and in a commit. The first run after upgrading finds no record it
can replay and searches every step; later runs replay as before.

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
radius is coarse first (`place.coarse_stride` apart) and fine only round its
best spots (the best `place.refine_spots` by score, and, where riders
constrain the spot, the best that they take), so a wide `radius=` costs little. A part the script places
later is not an obstacle where the generator left it, only once it is
placed. The step note says which of these happened.

**A step's search budget.** The candidates one item's step may judge are counted over all its passes, both
faces and the carried vias' giving way (each via's giving way counts as one candidate): `place.step_budget`, or the item's own `budget=` on `board.place`. The
count is of candidates, not seconds, so a result does not depend on how busy the machine is. The look-ahead's scans of a partner's spots are not part of the step's search and are not
counted. A step that spends it
stops where it is: it takes the best legal spot found so far (a `setup.step_budget` notice says so, with the
candidates judged, the share of the search area they covered and the budget), or, where none was found, leaves the
item unplaced, and the `unplaced.search` finding carries the same measurement in `facts["budget"]`
(`judged`, `share`, `limit`) and says "the search stopped at its budget". Both offer a higher budget for that
item, a searched suggestion that finds the least `budget=` that clears the finding, starting from what covering the
whole area would take at the rate the search went. The default is set high enough that none of the
benchmark modules or the core board's steps reaches it; it ends a search that would run on without finding anything.

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

**Order by room.** `place.order = "room"` (default `"freedoms"`) replaces
"fewer freedoms first" with "fewest legal spots first": within a tier, the
item whose declaration leaves it the fewest places goes first, then the rank,
the pull and the size as above. The spots are counted at `place.room_pitch`
from what the declaration says and the board as it stands when the first
searched item is reached (the firm items, keepouts and reservations in); no
spot is judged. A slide, an edge, a run, a rim, a ring or a spoke is its
length less the item's own size over the pitch; `Near` with a `radius=`, a
`Polar` band and an item left to the whole board are an area (the board's
free area for the last) over the pitch squared, less each `board.push`
hard-limit disc and each keepout or reservation that does not let the item
in; a turn searched on a point is its number of turns. Items whose counts are
within `place.room_ratio` of each other are level and go by rank, so a shelf
of unconstrained parts keeps the rank's order. The estimate is of a box
overlap, not a judgment: it says how tight an item is, not exactly where it
fits. A link's `limit_mm` is a price, not a limit, and counts for nothing.
The step carries a `room` note (`form`, `spots`, `cut_mm2`, `level`),
shown as `room 214 spots (near, counted at 1.0 mm), band 7`. Set it in
`placemat.toml` (`[place] order = "room"`) or for one script
(`[scripts."path.py".place]`).

**What a part claims.** `[place] envelope` says what one part may not share
with another. `courtyard` (the default) is its courtyard and its pads.
`physical` is what the part draws, each on the faces it occupies: its pads,
each pad's mask opening (the pad grown by its expansion), every silk graphic
as stroked (the footprint's text fields excluded - `board.label()` text stays
a reservation) and its body, the box of its fab graphics. A footprint that
draws neither silk nor fab claims its courtyard as the part itself: another
part's body or pads may not stand in it (its silk may), and it touches
another courtyard as courtyards do. So a keep-clear drawn only as a
courtyard (a no-parts radius round something mounted off the board) keeps
parts out. `union` is both. In
`physical` a part's courtyard still keeps off another part's plated lead, and
its plated leads out from under another part's courtyard, as KiCad's DRC
judges them (`pth_inside_courtyard`); the refusal names the pad: `C1 courtyard
sits over the through-hole lead of J1 pad 2`. Under every
envelope a footprint's own copper graphics (a net-tie's winding, a printed
antenna) are copper of no net: every other part, track and via - placed,
drawn by the script, or found by `FreeSpot` and `--via-near` - keeps the
default clearance from them. A net tie (a footprint with KiCad net-tie pad
groups) that draws no courtyard, silk or fab is copper only, as a track is:
under every envelope it claims its pads and its copper graphics and nothing
else, so another part's body or courtyard may stand over it, while another
net's pad or copper keeps the clearance from its pads and bar (KiCad's
net-tie exclusion applies where they meet the nets of its own pad groups).
A net tie that draws a courtyard is claimed by it as any part is. Between two
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

**A cell against a round rim.** A cell is judged against the board's edge by
its members' boxes, not the box round them, so an arc of members along a rim
may stand where the box round the arc passes it. For an item whose place the
script decided (`Location`, `Pin`, an edge or a rim), a member whose own box
corner passes the rim is judged again by the corners of its pads, courtyard
and copper, so a member drawn as an arc may stand along the rim; a searched
item is judged by boxes, as a part is.

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

The silk clearance is the board's minimum silk item clearance. Where
placement chooses the place (a search, `Beside`, a row), it keeps silk
`place.silk_margin` (0.001 mm) wider: KiCad compares silk at the clearance
itself on geometry rounded to the nanometre, so silk placed at exactly the
clearance can come out a nanometre short once a stamped cell or a tangent turn
takes it off the quarter turns. A place the script decided, and a rider's
place in its group, are judged at the clearance itself. The component
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

A run appends each completed step's record to `<run dir>/reuse.partial.jsonl`
as it resolves (the context first), and removes the file when `reuse.json` is
written. A run that died while resolving (killed, stopped, out of memory)
leaves it; a rerun of the same inputs - the same run id, so the same folder -
replays those steps, by the same chained keys, so a step that changed since
is not replayed, nor any after it. It prints `reused N of M steps from run
<id> (interrupted)`. When an earlier finished run's `reuse.json` holds every
step the partial one does, and goes on, that one is used instead.

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
refused, naming it. A freedom is settled at the first spot where the hole is
inside the board, keeps its web, mills through nothing already placed, and
stands the board's silk clearance from every placed part's silk on either
face (KiCad judges silk against Edge.Cuts by that clearance); a decided
place is cut where it was put.

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
board.keepout(shape, name, *, at=None, rotation=None, frame=None, margin=None, excludes=None,
              allow=(), layers=None, max_height=None, bars=(), why="")
```

`name` and `why=` are required (an empty `why` raises), and so is `at=` unless the
shape is a `Part`, a `Cell`, an `Inside` or goes by `frame=`. `board.rule(...)`
likewise raises without a `why`.

```python
CLEARANCE = Path(DATASHEET_FIGURE, anchor=(0.0, 0.0))  # the datasheet's own coordinates

board.keepout(CLEARANCE, "antenna", at=PadRef(Part("ant"), "ANT_FEED"),
              allow=(Part("ant"), Part("r_ant_series"), Net("ANT_FEED")),
              why="datasheet p1 Layout: copper-free on every layer")
```

**The shape, the place and the rotation** are a cutout's: `Slot`, `Circle`,
`Path`, `at=` taking `Location`, `Centre`, `Polar`, `OnEdge`, `Near`, a
`PadRef` or a `Mid` of two points (a figure anchored between two pads), and
`rotation=` taking a number (a bearing, clockwise from the
top) or `Turned(part, degrees)` to turn with a part already on the board -
the region turning the way the part does, `degrees` turning the way a
part's own rotation does (anticlockwise on screen). A freedom left in `at=`
settles against what is on the board. `anchor=` is the point of the shape
that lands on `at=`; without one it is the middle of the shape's box, which
is right for a slot and meaningless for a stepped clearance.

**A datasheet figure's frame.** `board.figure(at=, rotation=, anchor=(0, 0), why=)`
is for a datasheet's dimensioned reference layout (an antenna land pattern,
an RF keepout, a dimensioned crystal or sensor layout), with the points typed
exactly as printed. It is not for a layout a datasheet shows without
measurements (a converter's application layout with no stated dimensions),
and not a way round a placement that intent can say. `why=` is required and
names the datasheet and the figure or page the coordinates come from; a
figure without it is refused.

`anchor` is the figure's own point (mm) that lands on `at` (any point: a pad,
a `Mid`, an origin), and `rotation` (a number, or `Turned(part, degrees)`)
turns the figure about it exactly as a keepout's `Path` is turned and
placed. `board.figure` places nothing. `fig.point(x, y)` is the figure's
point (x, y) as a point reference, settled when `at` and the rotation's part
are: it goes wherever a point does (`Pin(key, point)` and a Pin's `X()` /
`Y()`, a track, finger or via point, `Polar(about=)`, `Mid`).
`board.keepout(Path(FIGURE), name, frame=fig)` reads the path in the same
frame, with its points as the figure's own and no move of the box centre; it
is the polygon `Path(FIGURE, anchor=A)` gives at the same `at=` and
`rotation=`. `frame=` goes with no `at=`, `rotation=` or `anchor=`. The
rotation does not mirror for a part on the back face, as a keepout's does
not.

```python
fig = board.figure(at=Mid(PadRef(Part("ant"), 1), PadRef(Part("ant"), 4)),
                   rotation=Turned(Part("ant"), 0), why="ant datasheet p7, recommended layout")
board.keepout(Path(CLEARANCE), "antenna clearance", frame=fig, why="ant datasheet p7")
board.place(Part("c_match"), at=Pin(1, fig.point(-2.1, 3.4)), rotation=Turned(Part("ant"), 90),
            why="ant datasheet p7")
for y in (0.9, 1.9, 2.9):
    board.via(Net("GND"), at=fig.point(4.2, y), why="ant datasheet p7: the strip's vias")
```

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
before anything is written. It judges a part as KiCad's DRC does: each
footprint's courtyard polygon against the region (`items_not_allowed` when
they overlap), not the part's body, pads or silk, and whatever `[place]
envelope` says - the envelope sets the spacing between parts, not what a rule
area tests. A part that draws no courtyard is not tested by KiCad; placemat
holds its claimed courtyard box out of the region all the same. A cell's own
tracks, vias and pours have no courtyard and are judged by their box, as
before.

**Where.** `layers=` defaults to every copper layer the board has, whatever the
count. Narrow it with a list of `CopperLayer`. It narrows what is CHECKED as
well as what is written: a track on a layer the region does not cover is not a
finding. A via joins the whole stack, so a region on any one layer contains it. A
part sits on a face, so `"parts"` keeps parts off the faces among its
layers: `layers=["F.Cu"]` leaves the back free, and inner layers alone keep
no part out. A region a cell brings follows the cell to the other face.

**What KiCad reports.** A rule area as KiCad saves it has no allow list or
height. So a keepout that admits parts (`allow=` parts or cells, or
`max_height=`) is written as a rule area that allows footprints, and a rule
in the board's `.kicad_dru` forbids the parts it does not admit (for
`bars=`, exactly the barred ones):
`(rule "keepout ring" (constraint disallow footprint) (condition
"A.intersectsArea('keepout ring') && A.Layer == 'F.Cu' && (A.Reference ==
'T1' || ...)"))`, naming the board's parts that are too tall, have no
`Pm.Height`, or are not named. A part placed by hand in KiCad inside the
region is then an error only when placemat would refuse it too. A keepout
that admits every part on the board writes no rule; one that excludes parts
outright forbids footprints in its rule area, as before. A track of a net
the keepout allows is still listed as `items_not_allowed`; the run sets
those aside, counted as `permitted` (`metrics.permitted`, and the DRC
line's "permitted by their keepout"), not as violations.

**Drawn on the board.** A keepout is a KiCad rule area, and one that
admits parts has a rule area that allows footprints and a `.kicad_dru`
rule, so its limit shows nowhere while placing by hand. By default such a
keepout is also drawn: its outline and its name on the Fab layer of its
face, or `User.Comments` for one on both faces or on inner layers only,
with its height limit when it has one (`ring: parts <= 1.90 mm`). The
parts and nets it admits or bars by name are never written as text: the
rule says them. `write.keepout_drawings` chooses: `admitting` (the default), `all`,
or `none`. These drawings are placemat's own, in one group, `keepout
drawings`, replaced whole on every write.

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
While the cell is searched each text's box is the cell's silk, judged as its
parts' silk is against what is already placed: under the `physical` or `union`
envelope a spot that puts it within the silk clearance of another part's silk
or mask opening is refused, on the face the cell lands on. Under any envelope a
searched spot also keeps each text's box the board's silk clearance inside the
outline and off every cutout, which is what KiCad checks silk to the board edge
against (`label silk to edge: box ...` in the scan's refusals). A cell whose
place the script decided keeps its texts where they fall, as does a cell
inside it that the script does not place; a text nearer the outline or a
cutout than the silk clearance, or over or covering a cutout, is a
`label.cell_edge` warning
naming the cell, the text, the edge (the outline, or the cutout by name), the
gap and the clearance.
A stamped region larger than its cell costs the parent the difference: the
cell's step says `its stamped regions keep parts off N mm2 of board beyond
its own parts`. For a part's escape band, `board.fanout()` follows the pad
rows and admits the part's own satellites and the parts linked to its pads
at `LinkWeight.SHORT` or more; a rectangle keepout does neither. For the
routes of named pins, `board.escape()` keeps their lanes and vias. A cell's
regions are read from the generated board, so a keepout whose name would
collide with one is refused.

A stamped keepout's `allow=` nets arrive with it, named as the parent names
them (`SIG` in a fragment is `<cell>.SIG` in the cell, a net from
the sheet above is that sheet's), so the parent's own vias, tracks and routes
of those nets stand in the region, and the parent's `layout.kicad_dru` carries
the rule that lets KiCad's DRC agree. A fragment written by a release before
this one carries no allowed nets: run its module again. Parts named in a
keepout's `allow=` are not carried.

A stamped cell brings its clearance rules (`board.rule`) the same
way: the fragment carries each as a note (a User.Comments text
`placemat rule clearance=0.1 between=A,B why=...`, written when a fragment is
run), and the parent judges and writes them held to the cell
(`A.memberOf(<cell>) && B.memberOf(<cell>)`) over the nets as pcb named them
in the cell. They stand before the parent's own `board.rule`s, so where both
match a pair the parent's decides; a cell's `within=` a cell of its own
takes that cell's stamped group. A rule whose net or cell the parent lacks is
not carried, and the run says so. A part's `Pm.KeepOut` is not a note: the
parent reads it off the part. See Rules.

The notes are transport. A board that stamps a fragment reads them and
writes none: its faces and rule notes come off the generated board as soon as
the run has read them, and again from the written board, in a group or
loose. A fragment keeps its own: a script's `board.faces()` and
`board.rule()` are written afresh each run, and the faces text
`placemat faces` stamped into a fragment stays on a fragment run alone.

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
module sheet, a stamped cell's group nested inside its module sheet's, so
selecting any part of the cell drags its sub-cells with it. Groups on
the written board are one level: each nested group is lifted to the top
level, whole, and a module sheet's group keeps its own parts as a group of their own; the run says `groups  power: cell(s)
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
written: N part(s) (<why>)`. A module's parts that move as one unit of its
arrangements are declared with `board.unit` (see "Arrangements"), not here.

**Layers a fragment's board does not have.** A module fragment is a two-layer
board, and KiCad saves a zone on the layers its board has: a keepout declared
on every layer, or on In1 and In2, would save as F and B and arrive in a
four-layer parent unable to keep the inner pours out. So the declaration
travels in the zone name, the one thing that survives the save and the stamp.
A keepout on every copper layer is written `keepout <name> [*.Cu]`; one on
layers its board lacks lists them, `keepout shield [In1.Cu,In2.Cu]`; one on
layers its board has needs no marker. The board that stamps the cell reads
the declaration, honours it on every layer it has, and widens the zone to match
so KiCad's filler and DRC honour it too. A layer that cannot be honoured is a
finding: on the fragment, where it is recorded but holds nothing, and on a
parent that lacks it as well. A parent need not restate a cell's clearance.

**What may enter.** `allow=` takes parts and nets, and they mean different
things: a `Part` or `Cell` may SIT inside, a `Net` may RUN through. Naming a
net does not admit the parts that carry it, which is the point - an antenna's
clearance holds its own matching network and every one of those parts carries
GND.

`max_height=` (a keepout that excludes parts) admits every part no taller,
by its `Pm.Height` field (`1.1mm`): the room a case leaves over a region,
said once, where naming the short parts in `allow=` goes stale when a part is
added or swapped. A part with no `Pm.Height` counts as taller; the refusal
names each part too tall or with no height.

`bars=` (Parts and Cells, in a keepout that excludes parts) is the other
way round: it names the parts the region keeps out, and every other part
is let in. A region that must bar only a few parts does not list every
other part in `allow=`, and a part added to the board later is let in
without an edit. A `Cell` in `bars=` bars every member. `bars=` and
`allow=` of parts or cells do not go together (a keepout says one side:
declaring both is refused); `allow=` of nets still lets copper through.
With `max_height=`, the parts named are barred whatever their height and
every other part is judged by the height; the refusal says `M1 is barred`.

```python
board.keepout(Circle(9.0), "cup", at=PadRef(Part("j1"), "1"),
              excludes=(Forbid.PARTS,), bars=(Part("m1"),),
              why="a part mounted off the board sits over it")
```

A cell meets a keepout member by
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
`route.json` under `keepout_breaches`. A KiCad rule area has
no per-net exemption, so a keepout with `allow=` nets is written in two parts:
the rule area allows the tracks, vias and pads it excludes, and a custom rule in
`layout.kicad_dru` (`disallow track via pad` where `A.intersectsArea(<area>)
&& A.NetName != <net>`) forbids them to every other net. KiCad's DRC then
passes an allowed net's copper in the region and flags the rest as
`items_not_allowed`. The zone's name carries the allowed nets and the types
(` {allow GND,SIG | tracks,vias,pads}`, after the layer marker), which is how
a board that stamps the cell writes the same rule. pcb names every stamp's
copy of a module's area alike, so the board that stamps it renames each copy
for its cell (` @<cell>` after the marker) and builds each cell's rule from
that name: one stamp's allowed nets are not let through another stamp's
area. A pour is still kept out
(`fill`): the allowance is for copper the script draws.

## Boards of any shape

An outline is a closed path of straight legs and arcs. The first element is
where it starts; each one after it is a point (a straight leg to it) or an
`Arc(to=, via=)` that curves through a point; it closes back to the start.
Three points fix a circle and the way round it, so an arc needs no flag for
which way it bulges. `holes=` are cutouts (above), each a path of its own.
Use this when the board's EDGE is not a rectangle or a circle; a hole in an
otherwise ordinary board is `holes=` on `rect()` or `disc()`.

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

**A band of radii.** `Polar((r_min, r_max), None, about=centre)` searches the
ground between two radii about `centre`, any bearing: a searched part or cell
with two freedoms, seeded from its links like any, and scanned only where its
body centre is in the band. `about=` is any point `Polar(about=)` takes, so a
band works on a `board.outline()` board, about the middle of its round part
rather than the middle of its box. With nothing to seed it, the items sharing
a band divide the turn, as a ring's do, and each starts from its share at the
band's middle radius. A seed outside the band is brought to the nearest
radius in it. When nothing in the band is legal the item is unplaced; no
pocket outside the band is tried. A bearing with a range,
`Polar((r_min, r_max), 90.0)`, is a spoke segment: one freedom, the radius
within the range. A range is a place's alone: a cutout or a keepout goes at
one radius, and a `Bearing` of two points needs one.

A band is how to stay inboard of a keepout band at the rim (a seal rim, a
gasket land): the keep-in is the board's, so an item's reach would otherwise
go to it, and the band stops it short.

**A turn that follows the curve.** `rotations=Turns.TANGENT` turns an
item, at each spot a search tries, so its outward side (its
`faces(outward=)`, else local +Y, the same side `OnRim` turns out) points
away from a centre, and also tries the half turn. A rectangular cell whose
long side is across its outward side then lies tangent to the circle at the
bearing it lands on; `Tangent(quarters=True)` adds the two quarter turns, for
one whose long side is its local Y. The centre is, in order, `Tangent(about=)`,
the `about=` of the `Polar` the item is in, the board's centre.

```python
CENTRE = Location(26.5, 26.5)                                 # the middle of the round part of an outline
board.place(Cell("winding"), at=Polar((14.0, 21.0), None, about=CENTRE), rotations=Turns.TANGENT)
board.place(Cell("winding2"), at=Near(Location(10, 12), radius=4), rotations=Tangent(about=CENTRE, quarters=True))
```

**On a ring.** `Polar(r, None, about=centre)` is the ring: one freedom, the
item's body centre at exactly `r` from `centre`, sliding round. With
`rotations=Turns.TANGENT` it faces out at the bearing it lands on, turned
exactly (the ring tries one turn per bearing, not a bin's), and `Tangent(about=)`
measures that bearing from another point. A single radius is written `Polar(r,
None)`; `Polar((r, r), None)` is refused, as a band needs `r_min < r_max`.
`Tangent(quarters=True)` is refused on a ring.

```python
board.place(Part("led"), at=Polar(16.0, None, about=CENTRE), rotations=Turns.TANGENT)
```

It needs a searched spot - seeded from links, `Near`, a band or a ring; a decided
place, a point, a spoke, an edge, a rim, a `Beside`, a block and
`rotation=` are refused, with `board.outward_rotation(item,
bearing)[0]` for the turn at one bearing. The bearing of a spot is that of
the item's body centre, cut into bins of `place.tangent_bin` degrees (10.0): a
spot takes the turn of its bin's middle bearing, so the item lies within about
half a bin of the tangent, and a candidate costs two turns (four with
quarters), not a step's 72. Of equal cost the outward turn wins, then the
quarters, then the half turn; a link or a push that favours another turn still
wins it.

With `face=Face.EITHER` each face the search scans takes its own tangent turns.
A part on the back is mirrored about the vertical axis before it turns (a flip to the back,
above), so the turn that points its outward side away from the centre is
the back's own: a declared east or west side swaps, north and south do not,
and `board.outward_rotation(item, bearing, Face.BACK)[0]` is that turn. As seen
from the front the tangent line is the same, the half turn and quarters are
kept, and a spot is judged and scored as above, the back costing
`score.back_face`.

```python
board.place(Cell("c"), face=Face.EITHER, at=Polar((0.0, 19.0), None, about=CENTRE), rotations=Tangent(about=CENTRE, quarters=True))
```

The global solve, the cleanup pass and explore leave such an item where its scan puts it.

**A disc with cutouts is still a disc.** A slot in a round board does not make
it a shaped board: `OnRim`, `OnBore`, `ring()`, `board.radius` and
`board.bore` all still answer. Reach for `board.outline()` only when the
board's own EDGE is not a rectangle or a circle.

**A round verb needs a round board.** `OnRim`, `OnBore`, `ring(radius=None)`,
`board.radius` and `board.bore` are a disc's, and a shaped board refuses
them with the verb that does the same thing: `OnEdge(board.edge(facing=X))`
is where `OnRim(X)` would have put it, held at the keep-in and turned to
the edge the same way. `Polar` is a coordinate about `board.centre` by
default, so it works on any board; `about=` moves the centre - any point:
a `Location`, an (x, y) pair, a `Part` or `Cell` (its body centre), a
`PadRef`, a `Mid` of two points, or another `Polar` - resolved once the
Polar item itself is placed, the same as `ring(about=)`.

**The keep-in is radial.** The rim holds an item's furthest copper corner back
by `board.keep_in` and its furthest courtyard or body corner to the rim itself; a bore holds its nearest point out by the same, and that is
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

## Push

```python
board.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2),
           limit=0.3, why="field at the sensor")
```

Prices how far an item must stand from a source: `value(r) = v_ref *
(r_ref / r) ** falloff`, `reference=(r_ref, v_ref)` in the script's own
units - a dipole's field falls off as the cube (`falloff=3`), heat
spreading through a plane roughly linearly (`falloff=1`). `r` runs from
`from_` to `item`.

`item` is a `Part`, or a `PadRef` on one for where the sensing element is
on the part - not a member of a block, which a push never reaches (it is
searched as the block, and a member's own push would never be asked).
`item` may be a member of a stamped cell: the cell moves as one rigid
body, so the push still measures that member's own point as the cell's
candidate placement carries it, not the cell's aggregate box. `from_` is
a `Part` or a `Cell` (its body centre), a `PadRef`, a keepout by name, or
a `Location`, and may not be `item` itself. `item` must already have a
`board.place()` declaration of its own (a stamped cell's `board.place(
Cell(...))`, for a member); `push()` adds to it, the same as
`board.link()` adds a pull.

**Hard limit.** Where `value(r)` would exceed `limit`, the item may not
stand: a disc round the source of radius `r_ref * (v_ref / limit) ** (1 /
falloff)`, reserved against the part the push measures alone - the
member, when `item` is a member of a stamped cell (Reservation.owners /
occupancy.let_in). Every other part, the cell's other members too, is
still let in, so nothing else is fenced by it, and a source placed first
looks ahead for room for that member's body alone. Refused like any reservation, naming the push: `sits in the
reservation for push from m1 (limit 0.3 at 29.7 mm)`. `falloff`, `r_ref`,
`v_ref` and `limit` are each more than 0; a `falloff` too small for its
`reference` and `limit` (the disc that formula asks for has no finite
radius) is refused at the declaration, not left to fail inside `resolve`.

**Soft price.** Within what is legal, each candidate is priced
`score.push` (default 10) times `value(r) / limit`, in the search's own
cost alongside its links and crossings - so the item moves as far out as
its other terms allow, not to a hand-picked point. Several pushes on one
item add their prices. The cleanup pass that follows the search (`cleanup.
enabled`) does not weigh a push: it may move a pushed item to shorten
wire, inside what the hard limit still forbids, but never past it - the
reported value and distance are the search's, not necessarily the
item's final, cleaned-up position.

**Order.** The source is placed first: pushing from an item that is
itself searched waits for it, the same order dependency a position said
in terms of a pad already carries. A push naming a keepout by name waits
for it the same way; a firm (fixed-position) item can never wait for a
keepout that is itself searched, since every keepout settles after every
firm item - that combination is refused at `resolve()`.

**No position hint.** A pushed item with no `at=` is searched over the
whole board, not near a small default radius, whatever else seeds its
hint (a link, the global solve): a push's own disc can be far larger than
a hint's usual few millimetres, and "as far as the board allows" needs
the whole board to search, not just the neighbourhood of what else pulls
it.

**The report.** The item's step names each push's modelled value and
distance where it landed: `push from m1: 0.21 at 15.9 mm (limit 0.3)`.
`placemat check` does not re-judge it - the model is the script's own.

### Push, annotated

`board.push` is for a source no footprint carries (a point in the
enclosure). A source that is a footprint, and a part sensitive to it, are
said once in the capture (`references/capture.md`: `Pm.Emits`,
`Pm.EmitsAt`, `Pm.Limit`, `Pm.SensesAt`) and need no script line. At each
run placemat pairs every part carrying a `Pm.Limit` of a kind with every
part carrying a `Pm.Emits` of that kind, in cells and loose alike, and each
pair acts as a push with the same model, `value(r) = v_ref * (r_ref / r) **
falloff`, the same hard disc and the same soft price (`score.push`).

**Order.** A pair is judged by whichever of its two parts is placed second,
so nothing waits for anything and no cycle can form. When the sensitive
part is placed second it is `board.push(sensitive, from_=<the source's
emission point>)`. When the source is placed second the disc is round the
sensitive part's sensing point, and the source is measured from its own
emission point. All placed sources of a kind add at the part: a candidate
where the sum exceeds the limit is refused, whichever source is placed
second, and the price is the sum of each pair's `score.push * value /
limit`. The sum is asked on the search; a part placed by an edge, a run, a
line, a ring or a spoke is held by the discs alone. A limit the sources placed before already exceed is not enforced on
the source placed next (no place helps it); the price stays. Two parts that
each emit and limit one kind (heat) are judged the same way.

**Look-ahead.** A part searched while the other part of a pair is still to
be searched is not left a spot that leaves the other none. The search finds
the other part's legal spots once (its own search as it stands: its faces,
turns, band and `Near`, on a grid of `place.lookahead_step`, or its own
`step=` if that is coarser) and refuses a candidate with no spot of the
other at the distance its limit asks, less what sources already placed add
there, and a grid step to spare. A source's candidate is asked the distance
from its emission point to the partner's sense points and its body to the
partner's disc; a sensitive part's candidate, its sense point to the source's
emission points. Nothing is declared: a source held near the middle of a
small round board leaves its limit partner the far side of the board.
When no candidate leaves room the part is placed as before and the other
part then ends unplaced; the step's note says so, and so does a finding
(kind `setup`) at the first part's step, naming both parts and the best
spot's miss ("the best spot for M1 left U31 0.35 mm short of 25.1 mm"). The
other part's refusal then ends "see: no room was left for it when M1 was
placed". When the look-ahead did leave room and the part still has none, its
refusal says what was placed since took it. Only a
partner that is a loose part or a cell searched in the open, in a band or
`Near` is looked ahead for: a partner that is decided, on an edge, a run, a
ring, a spoke or a line, in a block, or carried by another item is not.
`place.lookahead = false` switches it off.

`board.push` on an annotated item adds to its annotated pushes. A part
placed to measure a source (a temperature sensor beside a converter)
carries no limit for that kind; keep it close with `Near` or a link.

A source that is a member of a cell is measured where the cell carries it.
A sensitive part inside a block is not judged while the block is placed
(a push never reaches a block's member); `placemat check` still reports it.
The cleanup pass leaves a source that has a sensitive partner, and a
sensitive part with several sources of one kind, where the search put them.

**Refused at the start of a run:** a value that does not parse, a `pad:N`
the part lacks, and a kind given in two units (a source's `mT` against a
limit's `uT`), naming both parts.

**The report.** The step of a part in a pair gives, per kind, the summed
value at the sensitive part where it landed, its limit and the nearest
source: `magnetic at U2: 0.21 mT of 0.3 mT limit, nearest source M1 at 15.9
mm`. `placemat check` reports each sensitive part's `exposure`, per kind,
at its final place (below).

## Faces (a cell's sides, declared once)

```python
board.faces(outward=Edge.NORTH, quiet=Edge.SOUTH, handoff=Edge.EAST, why="the plungers are pressed from the north")
```
In a fragment's own script: `outward` is the side that faces the board
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
you meant). A part always takes the generic rule, with no note. For an
item placed with `face=Face.BACK`, pass the same face,
`board.outward_rotation(item, edge, face=Face.BACK)`: a flip mirrors the
item before it turns, so a side declared east is its west until turned.
An edge, a run, a rim and a block turn a back-face item this way on their
own. `rotation=board.outward_rotation(item, Edge.WEST)[0]` is the computed
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

The router and the copper findings keep the rules as KiCad does. The
clearance between two items is that of the last rule declared that matches
them, whether it raises or lowers the net class figure, else the net class
pair's (the larger of the two classes'). `between=(a, b)` matches one item
on `a` and the other on `b`; `on=n` matches either item on `n`;
`within=cell` matches two items that are both the cell's members' pads or
its own copper (copper the script declares belongs to no cell). A track's
legs, `Past`, `Between`, `FreeSpot`, a via's spot and a fitted pour's
outline all read it, so a rule that holds a net off another needs no
waypoint. A copper finding under a rule names it: `(needs 0.30, rule: the
rule's why)`. A conflict reaches as far as the largest rule clearance, or
`[place] conflict_gap` where that is more: the setting is a floor, and a rule
needs no matching number in it. The CLI's queries on a read board have no
script and judge by net classes.

A cell's rules travel with it (see "A stamped cell brings its own"):
the parent's `layout.kicad_dru` holds the cell's rules scoped to it,
and the parent need not repeat them with `within=Cell(...)`.

## Accepting a check verdict

```python
board.accept("current-path", "VOUT", at_least=0.35,
             why="into pin 11, 0.5 mm from pins 10 and 12: the package's pitch sets it")
board.accept("heat", "U3", at_most=118.0, why="...")
```
A design check can fail where no layout does better, and `check.limits`,
`--rise` and `--keep-out` loosen a check on every board. `board.accept(check,
subject, *, at_least= | at_most=, why=)` takes the one verdict a check gives
`subject` as it is. `subject` is what the run prints: the net (`keep-out`,
`crossings-under`, `current-path`, `switch-node`), the part ref (`heat`),
"<ref> <kind>" (`exposure`) or the loop's name (`hot-loop`). Give one bound,
on the side the check judges: `at_least=` for `keep-out` and `current-path`,
`at_most=` for `crossings-under`, `heat`, `exposure`, `hot-loop` and
`switch-node`. `why` is required, and the same check and subject cannot be
accepted twice; each of these, and an unknown check name, raises.

After the checks run, a failed verdict inside its bound reads `accepted
(>= 0.35): <why>` instead of FAIL and counts as accepted, not failed
(`checks_accepted` in the metrics, beside `checks_failed`; the `checks` head
line counts it). Past the bound it fails as before and its note says "past its
acceptance of <bound>: <why>". The `checks` lines print every acceptance and
what it matched. `board.accept` is for a one-off verdict where the layout cannot
do better, with its reason. A datasheet fact about a part - how near its feedback
pin may stand to its switch node - is not a verdict to accept per net in each
script: it is `Pm.KeepOut` on the part (`references/capture.md`), cited, and holds
in every board and every cell stamped into one. `run.json` carries them under `acceptances` (`check`,
`subject`, `side`, `bound`, `why`, the verdict's `value`, and an `outcome` of
`accepted`, `past`, `unmatched` or `not needed`). An acceptance that matches
no verdict, or whose verdict passes or is not judged without it, is a `setup`
finding. An acceptance moves no part or copper and is in no reuse or lock
digest. `placemat check` has no script and judges as ever.

## A part's keep-out

```
Pm.KeepOut: 0.7mm pads=FB,COMP away=SW,BOOT; datasheet rev B, section 10.2, layout example
```
A datasheet's keep-out distance for a part's pins is a field on the part (the
capture writes it; `references/capture.md` has the form), not a rule in a
script. The part's pads on the nets named by `pads=` keep that distance from
the copper on the nets named by `away=` - both nets of the part's own pads,
named as the capture names them (a stamped cell's nets carry its path, and
the last part of the name matches: `BUCK1.SW` is `SW`). The default for `pads=`
is the part's `Pm.Sensitive` net; for `away=` the switch nodes the part is on. The
citation after `;` is required.

The plan holds it as a clearance, and the check judges by it:

- between each `away` net's copper and each of the part's `pads` net's pads: a
  fitted pour's outline and another part's pad keep the distance from that pad
  (`rules.Rule.of`, written to the `.kicad_dru` beside the board for KiCad's
  DRC, and in native), where the netclass or a script's `board.rule` for the
  pair would not ask for more - a datasheet distance never lowers a clearance;
- the part's own pads are exempt, whichever nets they are on: the footprint
  sets that gap, and nothing a layout does changes it (the check says when it
  is nearer than the verdict's pair);
- the tracks and vias of the `away` nets are exempt too. They are the part's
  own pad escapes, which leave the package where its pins are and stand nearer
  a neighbouring pin than the distance whenever the package's own gap does.
  KiCad's rule language cannot say "a track connected to this part's pad"
  (its conditions read an item's net, type, reference and layer, and whether
  it touches an area or a courtyard, not what it is joined to), and a
  courtyard test would hold the stretch of an escape just outside it, so the
  rule is written `A.Type != 'Track' && A.Type != 'Via'`: it holds pours and
  other parts' pads and never an escape. A track of an `away` net that is
  nobody's escape is not held by the planner; `keep-out` judges it (below);
- other copper on the same nets, and another part's pads on `pads=` nets,
  keep the netclass figure in the plan;
- only copper sharing a copper layer is judged (a through-hole pad or a via spans its layers), as KiCad's clearance
  is: a pair on different layers does not fail `keep-out`. One inside the distance with no plane on a layer between
  them covering both nearest points is a notice, not a failure (`checks.keep_out_notices`: kind, the two items, their
  layers, distance, limit), raised as a `keep_out.cross_layer` finding that `placemat run` records in `run.json` and
  `placemat check` prints, for a datasheet that cares about proximity through the board.
  A pair with a plane between is not reported;
- a `Pm.KeepOut` that does not read (no citation, a distance that does not
  parse or is not above zero, a net no pad of the part carries) refuses the
  run at `resolve()` naming the part, and `placemat check` reports it as a
  failed verdict.

`keep-out` judges the nets the annotation names as a pair, in the check
(`references/capture.md`): copper on an `away` net against copper on a `pads`
net, tracks, vias, pours and pads alike, at the cited distance, less the pairs
the plan leaves out: the part's own pads from each other, a track or via of an
`away` net joined to the part's own pad, and the nets of the part's other pads
that `away=` does not name.

`board.accept("keep-out", ...)` stays for a one-off verdict. A datasheet fact
about a part belongs on the part.

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
| pour | a filled graphic polygon on one layer, never a zone: drawn exactly as planned, and never cut afterwards. Given as points it is the shape given; with `swallow_pads=True` over pads it is fitted round the copper planned before it |
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

**Arc corners.** `bend=Bend.ARC` draws every corner of the track as a circular
arc tangent to both legs, written to KiCad as arc tracks joined end to end
with the legs: for a trace whose impedance matters, as an RF run. The legs are
planned as for an unset `bend` (octilinear, the fewest turns, then the
shortest); `bend=Bend.ARC_FREE` instead draws the straight line between each
pair of points at any angle, so `placemat measure --copper` flags those
legs as off 0/45/90 (the arcs are never flagged). The arc replaces the
chamfer, so `chamfer=` is refused with either, as is `bridge=True` (a bridge
cuts a straight leg) and a `Lane` as first point.

The arcs' radius is `radius=` mm on the call, a stated design fact such as a
stackup's bend rule, or else `copper.arc_radius_track_widths` (default 3) times the
track's width, so it scales with the trace. A radius not above half the
width is refused. An arc at a corner of turn `d` takes `radius * tan(d / 2)`
of each leg. A leg shorter than what the arcs at its two ends take is a corner
the arc does not fit: the track is not drawn, and a finding (kind `copper`)
names the leg, its length and what each arc takes of it, never a sharp
corner or a smaller radius in its place. A smaller `radius=`, points further
apart, or `Bend.ARC_FREE` where the octilinear legs made the short leg, fixes
it.

```python
board.track(Net("RF"), [PadRef(Part("j1"), 1), Location(30, 12), PadRef(Part("u2"), 3)],
            layer=CopperLayer.F, width=0.3, bend=Bend.ARC)              # corners of radius 1.2 mm
```

An arc is copper as KiCad has it: a conflict is judged at the arc's true
distance (its polygon stands no further than `geometry.arc_error_nm` outside
it), and a finding against one ends "; the arc of its corner (radius R mm) at
(x, y); a smaller radius= there keeps clear". `board.pair` keeps its 45
chamfers.

**Lane waypoints.** `Between(PadRef(a), PadRef(b))` is a point in the
middle of the gap between two pads - halfway between their facing edges,
centred across where they face each other - resolved once both are placed: the
gap must hold the track's own width plus its clearance to each pad's net,
or the declaration is a finding naming both pads. `Past(items, Edge.EAST, across=None)` is a point held off the `edge` side
of some items. `items` are pads (`PadRef`/`CellPadRef`), vias, tracks,
cutouts (the `Cutout` given to `holes=`, or `board.cutout(name)`),
stretches of the board edge or of a hole (`board.edge(facing=)`,
`board.cutout(name).edge(side=)`), parts and cells, and labels (the key
`board.label()` returns), in any mix. Each is read as its box. The point
stands half the track's width plus the pair's rule off each: the net-pair
clearance from copper, the board's copper-to-edge clearance from a hole or
the edge, nothing from a part's envelope (its pads keep their clearance)
or a label (a via keeps the silk clearance). Off a stretch of edge the
point is on the board's side of it. `across=` a pad, a via, a cutout, a
part or a cell puts the point on its centre line, an `Along` at that point
of the combined box's side. The point waits for what it names to be placed
or planned; copper past a label is planned after the search. A `CutoutEdge`
taken from another board is refused. A Past whose item found no place, or
whose point lands off the board or in a cutout, is not drawn, and the
finding says which; a module fragment's frame is not an edge, so a Past
there is not judged against it. Both are accepted wherever a track point
is.

`Past(items, Corner.NE)` holds a 45 off a corner of the same box (`Corner`
is `NE`, `NW`, `SE` or `SW`). The point is on the outward diagonal from
that corner, half the track's width plus the clearance from it, rounded
away from the items; a 45 through it across the diagonal (NW to SE for an
NE corner) passes the corner at the clearance. A corner fixes both axes, so
it takes no `across=`. The track's legs either side of the point take that
45 through it wherever the points either side allow one, ahead of `bend=`;
where they do not and the track passes the corner nearer than the
clearance, the finding names the corner. The finding judges a round
cutout or a curved stretch of edge from the quarter of its curve that
faces the corner, not from its box's corner; the point is still measured
off the box. With several items, each item's corner is passed at least at
its own stand-off: the point is on the diagonal from the combined box's
corner, as far out as the item that needs most.

```python
v = board.via(Net("SIG_N"), FreeSpot(near=PadRef(Part("j1"), 3)))
board.track(Net("SIG_P"), [PadRef(Part("j1"), 2), Past([v], Edge.SOUTH), PadRef(Part("j1"), 8)],
            layer=CopperLayer.F)                 # a U-turn a track's clearance under the via
board.track(Net("S_A"), [PadRef(Part("r_a"), 2), Past([PadRef(Part("r_b"), 2)], Corner.NE),
                         PadRef(Part("j1"), 1)], layer=CopperLayer.F)   # its 45 a clearance off r_b's pad corner
```

`PadRef(part, pad, edge=Edge.SOUTH, along=Along.END)` is a track point on
that side of the pad's copper box (board frame), touching it: half the
track's width outside the edge, less 0.005 mm, so the track's copper lies
against the edge and KiCad reads it as joined. `along=` says where on the
side: `Along.MID` (the default) the middle, `START` the west or north end,
`END` the other, a half width in from the corner so the copper ends flush
with the pad's side. It is for a sense track that must meet its pad at one
edge and nowhere else: a current shunt's Kelvin taps leave each pad's inner
edge, the one facing the other pad, away from the copper the load current
flows through. `Past(..., across=tap)` lies on the tap's line, so a lane
picks it up without a jog. An edge whose copper does not reach the point
(the end of a round pad's edge, or of one turned off the right angle) is
refused, naming the pad; so is `edge=` anywhere but a track point, a
`Past`'s `across=` or a `Pin`'s point (below).

```python
tap = PadRef(Part("r_shunt"), "V_HI", edge=Edge.SOUTH, along=Along.END)
board.track(Net("V_HI"), [tap, Past([PadRef(Part("r_shunt"), "V_HI")], Edge.EAST, across=tap),
                            PadRef(Part("r_sense"), "V_HI")], layer=CopperLayer.F)   # out of the gap, then away
```

**Copper near a hole or the edge.** Declared copper (a track, a via, a
pour, a finger) nearer the board's outline or a cutout than the board's
copper-to-edge clearance is a `copper.edge` finding when it is planned,
naming the declaration, the hole or the edge, the gap and the clearance.
Copper wholly inside a hole, or off the board, is a `copper.edge` finding
at gap 0: this is placemat's own check, which KiCad's DRC does not make.
Beside a curved edge the copper is judged per arc leg: a leg that bulges
toward the copper's nearest point is judged its own sagitta further (at
least `geometry.arc_sag`), a straight leg or one bulging away as it is.
One finding is raised per declaration and loop of the edge, the nearest.
Copper nearer a part's drilled hole, plated or not, than the hole
clearance is `copper.meets`, as a via's hole is. The copper is drawn
either way; a `Past` off the cutout or the edge is the usual way to move
it. A plane is not judged: KiCad's fill keeps its own clearance. A module
fragment's frame is not an edge: it is never written to Edge.Cuts, and
copper there is not judged against it. The run score counts `copper.edge`
as a copper finding. The suggestion is offered only for a track with no
waypoints and two ends in the script (not a lane alone), drawn past a named
cutout: a `Past` off the cutout on each side the track's run crosses.

```python
vent = Cutout(Circle(1.5), "vent", at=Near(PadRef(Part("q1"), 2)))
board.rect(40, 30, holes=[vent])
board.track(Net("VBUS"), [PadRef(Part("j1"), 1), Past([vent], Edge.WEST), PadRef(Part("q1"), 2)],
            layer=CopperLayer.B)          # half the width plus the copper-to-edge clearance west of the hole
```

**A part's pad on another pad's edge.** The same `PadRef` is accepted as
the point of a `Pin`, `Pin(key, point)` or `Pin(key, X(point), Y(point))`:
the item's own pad `key` lies against that edge of the target pad,
outside it, its copper reaching 0.005 mm over the edge so KiCad joins the
two. Its centre is half its own size across the edge outside the edge, less
that overlap; `along=Along.MID` centres it on the edge, `START` and `END`
put its side flush with the target pad's side. The size is the pad's as the
part stands at its rotation, so `rotation=Turned(...)` settles first. The
refusals are the track point's: an end of a round pad's edge, a pad off the
right angle, naming the target pad. A net tie at each inner edge of an
upright shunt's 0.76 mm gap (two 0.3 mm ties leave 0.17 mm between them)
lies under the shunt's body, pad 1 against the shunt's pad and pad 2 out
past its end, where the sense track starts:

```python
board.place(Part("nt_v_hi"), at=Pin(1, PadRef(Part("r_shunt"), "V_HI", edge=Edge.SOUTH, along=Along.END)),
            rotation=Turned(Part("r_shunt"), 90), why="the Kelvin junction at the shunt's inner edge")
```

**Who bridges.** Where two tracks of different nets cross on one layer, the
lower `priority` passes under; at equal priority the shorter one does; a
track planned before the search (every endpoint decided) never yields to
copper planned after it. Only a track declared `bridge=True` may pass
under; a crossing where the track that should yield may not is a finding,
and that track is not drawn (the other is). The order of the declarations never
enters into it. Fingers always yield to tracks.

**Never through another net's copper.** A track or a via that would run
through, or stand on, a pad, a via, a track or a pour of another net is left
out whole, and a finding names the copper it met; a track that ends on a via
left out is left out with it. Copper that stands nearer than its clearance
without touching is a finding and is drawn.

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
board.track(net, [p1, p2, ...], layer=CopperLayer.F, width=None, chamfer=None, bend=None, radius=None, priority=Priority.DEFAULT, bridge=False)
board.via(net, at, drill=None, size=None, layers=None)                # at= a point; the board's via size unless given; layers= a span
board.via(net, at=FreeSpot(near=PadRef(...), radius=2.0))            # the nearest legal spot to a pad, joined to it by its tail
board.via(net, at=Past([PadRef(...), ...], Edge.SOUTH, across=None)) # its radius plus its clearance off the items' side
board.vias(net, pad=PadRef(...), pitch=None, size=None, drill=None, inset=0, layers=None)  # a pad filled with a grid of vias, turned with its part
board.vias(net, along=PadRef(...), count=N, pitch=None, size=None, drill=None, layers=None)  # a row out from a pad, along its escape axis
board.stitch(net, region, pitch=None, size=None, drill=None, edge=False, outside=False, hole_to_edge=None, sides=None, layers=None)  # vias in a grid over a cell, a pour or a keepout
board.pour(net, [p1, p2, p3, ...], layer=..., swallow_pads=False, stroke=None)  # filled polygon; stroke= its outline's width (copper.pour_outline_width)
board.pour(net, [PadRef(a), PadRef(b), PadRef(c)], layer=..., swallow_pads=True)  # fitted round other nets' copper, holding the pads
board.pour(net, [via_a, vias_b, PadRef(c)], layer=..., swallow_pads=True)  # members may be vias as well as pads
board.pour(net, [PadRef(a), PadRef(b), PadRef(c)], layer=..., cover=Cover.HULL)  # declared: the hull of the pads' copper
board.pour(net, [PadRef(a), PadRef(b)], layer=..., width=None)  # the neck between two pads
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
with it: a via at a searched part's pad, as above, a via of a grid
`board.vias(net, pad)` fills a part's pad with (a part placed firmly or
searched; below), or one of a stamped cell's own. Its tail is the one track of the same owner and net that ends
at its centre. A via that two or more of the cell's tracks end on is a
routed via, which moves with its tracks (below); a via whose track runs on
to another of the cell's vias is part of a route and stays as drawn.
Where a carried via meets another net's copper, on either face, the search
does not refuse the spot at once. A keepout, or a rule area on the generated
board or one a placed cell brought, that excludes vias is met the same way:
KiCad's DRC flags a via whose ring on a layer the area covers overlaps it
(`items_not_allowed`), unless its net is in `allow=`, so such a via is held
out of the region, and a via placed earlier that a cell's own region of that
kind covers gives way to it when the cell lands. A via that no way below gets
out refuses the spot ("keepout 'name' forbids vias: the GND via at ... is
inside it; it cannot give way"). A via's own track, and a track giving way
draws, keeps the board's edge keep-in and the cutouts' as the item's own
copper does, and is written into the cell's group, so a clearance rule that
holds within the cell holds for it in KiCad too. The via tries, in turn:

- to share a via of its net from any other item, on either face, within
  `place.via_share_distance` (1.0 mm): the via is taken out and a straight tail at
  the net's width joins its pad (its old tail's far end, or where it stood)
  to that via on the via's own face. The tail must clear every other net's
  copper. A via of the net already on its spot needs no tail. The via
  shared then stays: where a later item meets it, it does not give way,
  and the refusal says which via shares it. When its own item is placed
  again, the vias that shared it go back as drawn;
- to move up to `place.via_move_distance` (0.5 mm), searched on a
  `place.via_move_step` (0.05 mm) grid nearest first, to a spot clear of
  every other net's copper on every layer and of every hole, its tail
  redrawn from its pad. A via inside its pad moves only within that pad;
- a routed via (two or more of the cell's tracks end on it) has this one
  step and no other: to move up to `place.via_route_distance` (0.5 mm), on the
  same grid, nearest first, with every track that ends on it rebuilt from
  its far end, which stays, to the new centre. Each is drawn as a declared
  track is: octilinear legs (0, 45 and 90 degrees, right angles chamfered
  by `copper.chamfer`), the fewest turns and then the shortest, on its own
  layer at its own width. The spot is used only when the ring, the hole
  and every rebuilt track are clear of every other net's copper, every
  hole and the item's own copper; a spot where one fails leaves the via and
  all its tracks as drawn, and the next is tried. The track that continues
  from a far end is not touched. A moved routed via is a routed via still,
  and gives way again from the same far ends. `place.via_route_distance` 0 leaves it
  as drawn. The refusal says "no spot within 0.50 mm is clear with its 2
  tracks rebuilt";
- a via of a field (the carried vias of one net inside one pad of that
  net: a stamped cell's own, a plane net's drops or an exposed pad's grid, or a part's
  `board.vias(net, pad)` grid),
  with no tail, when no spot inside the pad is clear for it alone: to have
  its field re-laid in the pad as a whole (`place.via_relay`, true; false
  never relays). Every via of the field that meets the item is handled at
  once, a row is one step. The layouts tried, each inside the pad, at least
  the closest hole-to-hole pitch apart, every new site judged as a move's
  is (the other face's copper, holes, the edge and the item's own copper):
  the vias that meet it moved to the free sites of the field's lattice; a
  row or column shifted to a free line; the line spacing closed toward one
  end; the lines on one side of a pivot shifted together (an uneven
  pitch); the rows or columns that meet it taken out whole; the vias that
  meet it taken out, which is what drop does and is left to it. Each is
  priced `score.via_relay` once, `score.via_drop` for each via fewer than
  the field was drawn with, `score.via_relay_moved` for each via moved or
  added, `score.via_relay_gap` for each empty site left in the field's
  grid beyond the drawn field's and `score.via_relay_pitch` per mm the
  line spacings depart from the drawn pitch; the cheapest legal one is
  taken. A plane net's field may end with fewer vias than drawn down to
  `place.drops_keep_share`'s floor; any other net's field keeps its count or is
  not re-laid. A field already short may be brought back up to the count
  it was drawn with. The finding says which way and the count: "m: GND
  field in U1 pad 1 re-laid by shift vias, 9 vias before, 9 after under
  R9", and a drop reports what the pad holds: "3 GND vias dropped under R9
  (U1 pad 1 holds 6 of 9)". Undoing one via of a relay, as placing its
  item again does, undoes the field. A grid declared with `inset=` keeps
  it at every site a relay chooses, and no two vias of a field come closer
  than the floor `pitch=` is refused under, `max(size, drill +
  hole-to-hole)`, so a grid declared at a wider pitch can be closed down to
  that floor and one declared at the floor cannot be closed;
- a via inside a pad of its own net with no tail, when no spot inside the
  pad is clear: to leave its pad, up to `place.via_leave_distance` (1.0 mm) from
  where it stood, to the nearest spot clear of every other net's copper
  and every hole. A new tail on the via's own face joins it to the pad,
  from where it stood, in the pad's copper: at the net's track width, or
  narrower in 0.05 mm steps down to the board's minimum track width where
  another net's copper or a hole needs it, the widest that is clear at
  that spot. The via keeps its net, size, drill and layer span. A pad with
  room inside still moves inside, with no tail;
- a plane net's carried drop only: to shorten, from its own face to the
  nearest layer of that plane between it and the far face (F-In1 for a
  GND drop from the front with GND on In1 and In4), when the fab profile's
  tier for the resulting via type (micro, blind or buried, by the span) is
  `"yes"`. With `"if-needed"` it is judged but never drawn: the refusal
  names the span it would have used and the fab-profile key, and never
  applies it whatever the spot. An item left with no spot that such a span
  would have cleared is a finding of kind `needs` ("m: no spot; one would
  clear with a micro via shortened to F-In1 (via.micro is if-needed in
  fab-profile.json)"): setting that type to `"yes"` is the user's call.
  With `"no"` it is not applied, and where it would have cleared the
  spot the refusal says so: "a blind via from B.Cu to In3.Cu would clear
  this; the fab profile does not allow blind vias";
- a drop only (a via of a net the board declares a `plane()` for): to be
  dropped, while each of the item's pads keeps at least `place.drops_keep_share`
  (0.5) of its drops, rounded up and never fewer than one. A shared drop
  counts as kept.

If none works the spot is refused, and the refusal names the via and why
each way failed: "via GND at (19.10, 21.90) is 0.00 mm from S copper on
B.Cu (needs 0.20); it cannot give way: no GND via within 1.00 mm to share,
no spot within 0.50 mm is clear, GND is not a plane net, so it is no drop".
Each way has a cost the search adds to the spot's score - `score.via_share`
(1), `score.via_move` (2), `score.via_route` (3), `score.via_relay` (3, once for the field, and `score.via_relay_moved` (0.5) for each via it moves or adds), `score.via_leave` (4), `score.via_shorten` (5), `score.via_drop` (10) -
so it prefers spots where the vias stay as drawn; a nearest-first search
takes a spot where they give way only when no spot has them as drawn. A via
already placed does the same for an item placed later whose own copper
meets it, its owner otherwise untouched and its keep share still held. A
firm item's carried vias, and a rider's, give way where it is put. An item
searched along an edge, a run or a rim takes the nearest slot where its
vias stay as drawn, and only when there is none the nearest where they
give way. A block's members are judged as drawn. The write moves or
removes a cell's via on the board and draws the tails, and for a routed
via deletes its old tracks and draws the rebuilt ones; a via declared at a
pad is drawn where it went. What gave way is a note on the owner's step
and a finding of kind `vias`, per owner and net: "m: 6 GND vias shared, 2
moved up to 0.25 mm, 1 dropped under R9" (a via that left its pad: "1 GND via
left its pad under R9"; a routed via: "1 SIG via re-routed 0.15 mm under R9").

A placement refused for a via that could not give way is counted in the
run's refusal tally as "vias that could not give way xN", apart from the
copper, through or hole counts of the sentences it ends.

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
radius plus the worst clearance, by net pair, to any of them: the items a track's `Past` takes (Lane waypoints), with the
silk clearance off a label. `across=` a pad
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

The grid is carried with its part, a part placed firmly or searched: its
sites are those above that clear the part's own copper and holes, laid with
the part, and what other items do is judged when each is placed, not when
the grid is drawn. Where another item's copper meets some of them they give
way as a stamped cell's field does (above): a via moves, the field is
re-laid, a via leaves its pad, and a plane net's vias are dropped down to
`place.drops_keep_share`; a net that is no plane keeps its count or refuses the
spot, and a firm item with no spot is a collision. The grid is drawn after
the search, as a via declared at a pad is, and each via is judged once more
against the copper planned before it, which is why a pour that names a grid
is planned after the search too. A part put on its host's pad by a pin is
not refused by the host's grid; the vias give way to it. The row form,
`vias(net, along=, count=)`, is not carried and is planned after its part
as before. A part's grid used to skip a site another item's copper met, or
refuse a searched item; it now gives way, so a spot that cost vias may keep
them, and one that was refused may be taken.

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

`edge=True, outside=True` rows them outside `region` instead, for a
datasheet's vias round an antenna's clearance. Each via's hole edge stands
`hole_to_edge` off the region's edge, its centre `hole_to_edge` plus half
its drill out along the edge's outward normal; by default the via's copper
touches the edge from outside. `pitch` is the most the vias stand apart
along an edge: a side `L` long gets `ceil(L / pitch) + 1` vias, evenly
spread from end to end. `sides=[Edge.EAST, Edge.SOUTH]` keeps only the
edges whose outward normal faces those sides as the region is turned (a
keepout placed with `rotation=Turned(part, 0)` reads its sides in the
part's frame); an edge counts for the side its normal is nearest, within 45
degrees, and the default is every edge. Where two kept edges meet, one via
stands at the corner's outside, shared by both rows. Each via is judged as a
stitching via is; one that cannot stand is left out and named in a finding,
and a row left with a gap over `pitch` is a finding naming its side and the
gap. `outside=True` without `edge=True`, and `hole_to_edge=`/`sides=`
without `outside=True`, are refused. A keepout that forbids vias needs no
`allow=` for an outside row.

```python
board.stitch(Net("GND"), "antenna clearance", edge=True, outside=True, hole_to_edge=0.35,
             pitch=2.0, sides=[Edge.EAST, Edge.SOUTH], why="the datasheet's vias outside the clearance")
```

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

These vias cost more, so each type takes a tier in `fab-profile.json`:
`"via": {"micro": "yes", "blind": "if-needed", "buried": "no"}`. `"yes"`:
the fab makes it and its cost is accepted, so a script may draw one
outright. `"no"` (a type the file does not name defaults to this): refused
when declared, naming the type and the key that allows it, and a stamped
fragment carrying such a via fails the run, naming its cell. `"if-needed"`:
preferred off - a script may not draw one either, refused the same way as
`"no"`, naming that the type is preferred off - but give way's shorten way
(below) may still use it where nothing else places an item, judged and
reported, never drawn without the user raising the tier to `"yes"`. The
0.57 keys `allow_micro`/`allow_blind`/`allow_buried` still read: `true` ->
`"yes"`, `false` or absent -> `"no"`. Look for another way first: a through
via moved, shared, shortened or dropped (the give-way above), or a field
thinned with `drops=`.

A `min` section in `fab-profile.json` (`track_mm`, `clearance_mm`,
`drill_mm`, `annular_mm`, `via_size_mm`) is checked against the board's net
classes at the start of every run; a class below one is a `fab` finding
naming the rule and both values.

```python
board.vias(Net("GND"), PadRef(Part("u3"), 17), layers=(CopperLayer.B, CopperLayer.IN4))
```

**A pour between two pads.** `board.pour(net, [PadRef(a), PadRef(b)])`
(or with `swallow_pads=True` and `width=`) with exactly two pads draws the neck between them - a rectangle along their
centreline, as wide as the narrower pad measured across the run, unless
`width=` says otherwise - instead of needing a third point. It is drawn as
declared. `swallow_pads=True` over two pads with no `width=` is a fitted pour
instead. A declared pour's copper is its outline plus half its stroke: another net's copper inside it is a
copper finding, and nothing is cut from it.

**No grown pour.** `board.pour` takes no `grow=` or `within=`: a pour is
fitted, never a KiCad zone grown from its pads. A pour that reaches past its
pads into the room round them is `board.pour(net, pads, layer=,
swallow_pads=True, reach=Reach.CURRENT)`, widened to its net's current need,
or, as an escape hatch the user approves, `reach=mm` (A fitted pour); for
ground or a plane net,
`board.plane(net, layers, over=[...])`. `board.stitch(net, pour)` over a
fitted pour places its vias inside the pour's outline as planned.

**What a pour over pads covers.** For a pour drawn as declared (no
`swallow_pads`), `cover=` (`Cover`) says what corners that name pads cover.
`Cover.HULL` is the convex hull of those pads' copper, every land's
corners; `Cover.BOX` is the box round it; `Cover.CENTRES`, the default, is
the polygon through the points as given, a pad at its centre - over three
pads in a row that is a line, and the pour is as thin as its stroke. A plain
point among the corners counts as given under HULL and BOX too. The pour is
written as given, a graphic polygon; another net's copper inside it is a
copper finding, and nothing is cut from it.

**A fitted pour.** `board.pour(net, pads, layer=, swallow_pads=True)` over
two or more pads (two with `width=` are the neck) (`PadRef`, `CellPadRef`), or
vias (below), draws one polygon fitted round
the copper planned before it: the shortest closed outline that holds all the
pads' copper (every land) and enters no other copper's clearance outline.
That is every other net's pad (at its real shape), track, via and pour on
the layer, every unplated hole and the board edge, each grown by the clearance the
pair needs plus half the pour's stroke. The clearance is the pair's class
figure or the `board.rule` one that matches it, as the router keeps it; a pad
with no net keeps the board's default. Every edge is straight. Where the
outline passes a pad's corner, a track's end or a via it follows the
clearance outline by straight edges that stay outside it: the nearest it
comes is the clearance plus `[geometry] arc_error_nm` (0.005 mm, the error
pads and tracks are read with), and no corner stands more than `[geometry]
arc_sag` (0.02 mm) past the clearance. With nothing in the way the outline is
the hull of the pads' copper. A pad that another net's clearance outline
reaches into (copper nearer than the clearance and half the stroke) is held
inside its edges by half the stroke plus the arc sag, so the stroke does not
reach the other copper. A pad that stands nearer another net's copper than the
clearance itself (its footprint sets the gap between two pins) is held as far
as it is clear: the pour holds the part of the pad outside that copper's
clearance outline, so its added copper keeps the full clearance, and the pad's
own copper is as the footprint has it. KiCad has no exemption for a polygon
whose edge is the pad's edge (a board graphic is judged against the
neighbouring pad like any copper), so the pour's edge never stands where the
pad's does on that side. Where the whole pad is inside the clearance outline,
the pour is not drawn and the finding names it.

**Reach.** `reach=mm` on a fitted pour grows its copper into the room round it:
the fitted outline grown by `reach` (arcs no more than `[geometry] arc_sag`
off), cut back by the clearance outline of every other net's copper planned
before it (the pieces the fit keeps clear of, the board edge included), and of
what is left the part joined to the members. It is written as graphic
polygon(s), never a zone; where copper cut across the reach leaves more than
one part joined to the members, each is a polygon. Copper that stands wholly
inside the grown ring leaves a hole, drawn as KiCad draws a zone fill's: one
polygon whose outline goes in to the hole and back by a bridge of no width.
Copper planned after the pour keeps clear of the grown copper as for any
fitted pour. `reach=` adds that much on every side the room allows, so a
hull 1.4 mm across with `reach=0.4` is 2.2 mm across where nothing is in the
way. **It is an escape hatch, as a coordinate is:** the distance stands in for
a fact the design does not hold yet (no current known for the net, a pour
wanted thick so tracks can be routed round it by hand), so a script uses it
only on the user's explicit yes for that one declaration (SKILL.md, "When no
form says it"). Where the net's current is known, the pour widened to its
current need is the form, `reach=Reach.CURRENT` (below), and it names no
distance. The narrow-neck finding is not made for a pour with `reach=`. It is
refused with `width=`, without `swallow_pads=True`, and for a distance of 0 or
less; it needs KiCad's pcbnew at plan time, whose polygon booleans it uses.

**Reach.CURRENT.** `board.pour(net, pads, layer=, swallow_pads=True,
reach=Reach.CURRENT)` grows the pour into the same room only as far as its
net's `current-path` width needs, so the script names no distance. The need
and the width are the check's own, `placemat check current-path`'s: the
current is the parts' `Pm.I`, the rise is `[check] rise_c`, the copper weight
the board's stackup (IPC-2221), and the pour is measured along the route
between the parts that carry the current, at `[check] zone_step`, as a
written board is. The reach is the smallest multiple of `[copper]
pour_reach_step` (0.05 mm) at which that reading passes, searched up to
`[copper] pour_reach_max` (5 mm); a hull that already passes is the fitted
outline unchanged. The grown copper is `reach=`'s: cut back by other nets'
clearance outlines, graphic polygon(s), never a zone. Only the pour's own
copper counts, so a track that also joins the parts is not credited.

Where the room runs out first (copper of another net stands at the neck) the
pour is drawn at the reach where its width stopped gaining and a finding
names the net, the current, the width reached, the width needed, the neck's
point and the copper standing there; `check current-path` reports the same
neck. It is refused at the declaration where fewer than two parts carry
current on the net (the check does not judge such a net either), and with
`width=` or without `swallow_pads=True`. Where the pour's pads belong to fewer
than two of the parts that carry current, it is not drawn and a finding says
so. It needs pcbnew at plan time, as `reach=mm` does.

It is written as a graphic copper polygon (a filled `PCB_SHAPE`), never as a
zone: nothing refills it round later copper, and nothing is cut from it once
it is planned. Copper of another net planned after it keeps its clearance
from it like any copper; a track declared across one is not drawn and
a finding says so, and the pour stays as it was fitted. A pour sees the copper planned before
it, so declare a pour after the tracks and vias it must go round.

Where other copper stands where the outline cannot go round it - between two
of the pads with no gap past it, or inside the pads' hull with no edge to
carve it from - or two pads cannot be joined at all, the pour is not drawn
and a copper finding names the copper and the pads it stands between. Where
the outline narrows, between its pads, to less than its net's track width, a
finding names where, and the pour is drawn. A pad that is on another net, or
has no copper on the pour's layer, is a finding and the pour is not drawn.

A fitted pour's members may be vias as well as pads: what `board.via()` and
`board.vias()` return (a `vias()` result counts as all its vias) and an
escape lane's `.via`. A via counts on the pour's layer when its span includes
that layer, as its copper ring there; a via that does not span the layer is a
finding naming it, and the pour is not drawn, as for a pad with no copper on
it. A pour of vias alone is allowed. The pour is planned after the vias it
joins (and after the parts they are found from), so the vias are held as
planned. On an inner layer this is how to join the vias dropped from a
part's pads:

```python
drops = board.vias(Net("VOUT"), along=PadRef(Part("c_out"), "VOUT"), count=3)
q1_drop = board.via(Net("VOUT"), FreeSpot(PadRef(Part("q1"), "VOUT")))
board.pour(Net("VOUT"), [drops, q1_drop], layer=CopperLayer.IN2, swallow_pads=True,
           why="the output area on In2, joining the drops")   # a front pad named here is refused on In2
```

A fitted pour is given by its pads and vias alone: `cover=` with `swallow_pads=True`
is refused, and so is any point that is not a pad or a via; a via is a member only
of a fitted pour. The pull-back this
replaces (`swallow_pads` over a hull, a box or points, cut back from other
copper when the board was written) is gone; see `migration.md`, "To 0.67.0".

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
`board.label()` returns the label's key, a `LabelKey` (a `str`; a list of
them for a list of items): a `Past` names it to pass the text.
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
its face is reserved: the box and the text's silk keep a firm item (and a
block or cell member) off it, and are not seen by a searched item (below). A
label is a user's
mark, not part of what makes the board work, so it gives way: where an
item would stand within the silk clearance of the text, or on its box, the
item stays where it is put and the label moves. A firm item (`Location`,
`Pin`, `Beside`, `OnEdge`, `row`) is judged with its labels already moved;
a searched item (`Near`, a run, a rim, a pocket) does not see labels at all
(other items' silk and pads still count), and the labels it lands on move once
it is down. The label moves first along the side it was
declared on (between that side's start and end, nearest its declared spot
first), then to the item's other sides, nearest first. It keeps its `gap`
off the item and clear of what is placed, so it still reads as that item's.
A label's spot is always on the board: inside its outline (a round or shaped
board's too), outside its cutouts, and the board's silk clearance from the
edge, which is what KiCad checks silk to the board edge against. A label
declared where that is not so moves the same way when first placed; with no
spot on the board a `label` finding says so (a line of labels is only
reported).
The step's note says so ("moved from north END to north MID: U20 was
there"). With no clear spot it stays, a `label` finding names it and what
is in the way, and a firm item's collision stops the run as before; a
searched item is placed all the same.
A line of labels (a list, or `line=`) gives way as one unit, by the same
rules: the whole line slides along its side, then moves to another side of
its items, its texts keeping their spacing and order and each staying beside
its own item (a text keeps overlapping its item's extent along the side).
Every text of the line must be clear. With no clear spot the line stays, and
one `label` finding names it and what is in the way; the item is placed all
the same. A step's note says "moved from north MID to south MID" or "north
MID, line shifted +0.50 mm". `label.slide_step` is the step along a side. `reserve=False` keeps the
label out of the way of placement and only reports what lands on it. Mark what a user handles:
every connector, jumper, switch and LED, by what it does, not its refdes.

## Layers and faces

A flip to `Face.BACK` is described under Placement ("A flip to the back").
`CopperLayer.F / IN1 .. IN30 / B` (the faces and every inner layer KiCad
allows; a board uses as many as its stackup has), `Face.FRONT / BACK`,
`Edge.NORTH / SOUTH / EAST / WEST`.

## Commands

```
placemat run <script | its directory> [--label L] [--fresh] [--no-reuse] [--no-resume] [--no-render] [--no-drc] [-v | -q] [--json] [--keep-going] [--route [--route-full] [--route-exclude NET ...]]
placemat route <layout.kicad_pcb | script> [--exclude NET ...] [--islands NET[=WIDTH] ...] [--layers L ...] [--full] [--iterations N] [--out DIR] [--no-resume] [--json]
               [--adopt NET ... | --adopt-all] [--partial] [--no-lock]
placemat routes <script> [--release NET ... | --release-all]
placemat impact <run> <run> [--board DIR]      # each a run id, a unique id prefix, a --label, or a run directory or run.json path
placemat drc <layout.kicad_pcb> [--json]
placemat measure <layout.kicad_pcb | script | footprint.kicad_mod> [cell-or-part ...] [--pads] [--envelope] [--models] [--copper [NET ...]] [--keepouts [NAME ...] [--near MM]] [--labels] [--outline] [--json]
placemat parts <layout.kicad_pcb | script> [--field NAME ...] [--fragments] [--json]
placemat nets <layout.kicad_pcb | script> [--sort COLUMN] [--net NET ...] [--inst] [--json]
placemat datasheet <pdf> [--show PAGE|TOPIC [--png | --out FILE.png|DIR]] [--read] [--no-ocr] [--dpi N] [--json]
placemat datasheet check <pdf> <footprint.kicad_mod> [--pitch F] [--pad WxH] [--pads N] [--span F] [--tol F] [--json]
placemat occupancy <layout.kicad_pcb | script> (--at X,Y | --box X0,Y0,X1,Y1 | --via-near PART.PAD | --corridor A B)
                   [--net N] [--size D] [--drill H] [--layer L] [--radius R] [--step S] [--in-pad] [--json]
                   [--width W] [--margin MM] [--ignore-kept]
placemat show <layout.kicad_pcb | script> <cell | part> [--out DIR]
placemat layer <layout.kicad_pcb | script> <LAYER> [--out FILE] [--json]
placemat faces <fragment layout.kicad_pcb> outward=N [quiet=S] [handoff=E]
placemat check <layout.kicad_pcb | script> [--ambient C] [--keep-out MM] [--rise C] [--limit CHECK=VALUE ...] [--json]
placemat facts <script> [--confirm] [--json]
placemat settings [<script-or-board-dir>] [--json]
placemat apply <id> [--script PATH] [--dry-run] [--json]
placemat apply <id> --search [--yes] [--script PATH] [--json]
placemat apply --undo [--script PATH] [--dry-run] [--json]
```

`facts` prints the board's own facts - each copper layer's role and
weight, the pair classes and their nets, each via type's tier, the fab
minimums and the rise - and whether they match the last confirmation. It
flags a `signal` layer carrying a `plane()` and a `power` (ground) layer
carrying none. `--confirm` records a digest of the printed facts in the
nearest placemat.toml that exists above the board (the one the run uses; a
new one is made beside the board only when there is none), under
`[facts.boards]` keyed by the script's path relative to that file:
`"modules/m/M_layout.py" = "<digest>"`. A board and its modules each keep
their own, since their facts differ; the script's path is the key because
the digest comes from that script's own `plane()` calls over the board it
declares, and a board's name is shared by its variants. A file's old single
`[facts] confirmed = "<digest>"` is read for any script with no entry of its
own, and the next `--confirm` of a script whose digest it holds moves it into
the table. This is placemat's own record, never part of a run's id, so
confirming never re-plans a board. A run whose
facts do not match says so on its own line
("facts: unconfirmed - placemat facts") and records a `facts` finding, but
still runs. A via type fab-profile.json's `via` does not name, or a missing
`min`, stays unconfirmed even after `--confirm`: name each type, `"no"`
included, since `"no"` for every type (through vias only) is a decision.

`drc` runs kicad-cli's DRC on a board and prints the counts by kind, the
airwires, and each violation that fails the board with where it is and the
items it is between (the first twenty; `--json` gives them all as
`violations`, each with its kind, severity, KiCad's description and its
items' descriptions and positions, and every open connection as
`unconnected_items`, by net). An item on a part carries the part's instance
path beside KiCad's refdes (`instance`; in the text, in brackets).

The counts fall in buckets: `real` (the headline: the `[drc] real_kinds`, whatever
their severity, and every other kind KiCad reports as an error), `outstanding`,
`footprint issues` and `other`; `--json` gives each kind's `severities`. A board
whose folder has no `fp-lib-table`, or one whose `${KIPRJMOD}` entries do not
resolve from there (a run folder's `layout.kicad_pcb` copied out of its
project tree), gets `lib_footprint_issues` for every footprint: the count is
kept, `libraries` (`state`, `unresolved`) records why, and the summary says those
issues come from where the board sits, not from the board.

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
and bearing, `off 0/45/90` on a leg at any other angle - then the vias, then
each graphic copper polygon of those nets (a `PCB_SHAPE` polygon on a copper
layer): net, layer, stroke width, filled, its vertices, and per edge the
nearest copper of another net on its layer (pad, track, via, polygon, zone
fill), the gap from the polygon's copper (its outline grown by half its
stroke; an unfilled polygon's copper is its stroke alone) to it, the
clearance the net class pair needs and `under` where the gap is less
(`--json`: `polygons`, each with `edges`). A board's `.kicad_dru` rules are
not read. Round pads are measured by their polygons, up to 0.005 mm outside
the circle.
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
each with its kind, face, cell, box and stroke. `--outline` lists the board's
edge instead: each Edge.Cuts item, the box round them and the board's thickness.

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
                 [--max-time S] [--step-warn S] [--step-limit S]
```

`--max-time`, `--step-warn` and `--step-limit` bound how long the placement takes (see "Bounding the time", under
"Exploring a placement"); `run` takes the same three. A preview that is stopped keeps its finished steps in
`<board>/.placemat/views/preview/reuse.partial.jsonl` (removed when the preview completes), and the next preview replays them
(`reused N of M steps from the interrupted preview`).

It writes `preview.svg` and, through `[preview] converter`, `preview.png` at
`[preview] px_per_mm`, under `<board>/.placemat/views/preview/`, and prints the
paths, the step counts, what it reused, the congestion line and the findings.
Each face is a panel, the back mirrored as seen from the front, on a
millimetre grid: the board, keepouts and reservations, each part's pads,
courtyard, fab body, silk and reference, planned copper, declared links
(green within their limit, red over it, with their lengths), parts that took
a pocket, the congestion heat map with its worst cell, and a column with the
parts not placed and why. `--zoom` and `--around` draw one region of each
face (`--margin MM` is the room round `--around`, 5 by default);
`--face front|back|both` picks the faces drawn; `--no-tags` leaves the annotation tags off the picture, which at a
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
ranking, so the ranking can be judged rather than trusted. `--show p7` prints
that page's text with positions; `--show land` (or `package`, `rules`, `pins`) resolves the topic
through the index first. It writes no file unless asked: `--png` also renders the page to
`<project>/.placemat/views/datasheet/<pdf>-p<N>.png` (the project is the
nearest directory up from the PDF holding `.placemat/` or `placemat.toml`, else
the PDF's own), and `--out FILE.png` renders it there; the path is printed, and
in `--json` it is `png`, beside `text`. Measured over 67 datasheets, a keyword list
alone names a land pattern on half of them, so the geometry counts too: a page
holding a row of identical rectangles is a pad row whether or not it says so.
A datasheet whose every dimension is an outlined curve carries no text at all,
and `--show --png` is the answer for those: look at the render.
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
`--net`, `--size`, `--drill` and `--layer` override the pad's net, the net class's via size and drill
and the tail's layer; `--radius` and `--step` set how far from the pad it looks and on what grid; `--in-pad`
lets the via stand in its own pad. `--via-near` searches outward from a pad, in a fixed order so the same board
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
verdict. `exposure` is each sensitive part's modelled value per kind at
its final place against its `Pm.Limit`, pass or fail, naming the sources
that contribute and their distances: `exposure  U2 magnetic  0.21 mT
(limit 0.3) ok - magnetic at the body centre: M1 0.21 mT at 15.9 mm`. A
kind no source emits passes at zero and says so; a `Pm.Emits` or `Pm.Limit`
that does not read is one unjudged verdict naming the part. The keep-out verdict judges what layout can change - a part's own
pins are its package, left out - against `check.keep_out_mm` (`--keep-out`),
or against the part's own limit where a pad of a part carrying `Pm.KeepOut`
is one of the pair: the limit is the datasheet distance the part cites, the
verdict's note says "limit 0.7 mm from U3's Pm.KeepOut (<citation>), not the
board-wide 2 mm", and a `Pm.KeepOut` that does not read is a failed
`<ref> Pm.KeepOut` verdict, the part judged at the board-wide limit. The
same distance is held in the plan (see "A part's keep-out" below). It names the two pieces of copper that
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
by more than a step. The search for the widest route reads a fill no wider
than the widest disc anywhere in it until it has measured the crossing;
where the route it found narrows in a fill, it searches again with that
crossing at its measured width, up to `check.route_tries` searches, so a
plane joining the same pads is taken over a sliver of another fill. Each two parts carrying `Pm.I` on the net
are judged at the lesser of their two currents - what can flow between
them - by the narrowest point of the widest route from any pad of one to
any pad of the other; the net's verdict is its worst pair, naming both ends
and the current, and its neck: the point along the route the width is
narrowest - "neck at (x, y)".

Copper on parallel layers shares the current. The route is cut at its
plated holes (vias and through-hole pads); between two of them it stays on
one layer. Where a fill or pour of the net on another layer touches the
same two holes, that layer carries the current alongside the route there:
it is measured between the two holes as the route's own fill is, and the
stretch is judged by the layers' widths added, each scaled to the route's
layer by the ratio of the two layers' IPC-2221 needs at that current (a
1 oz outer layer's millimetre counts as about 2.6 mm of a 1 oz inner
layer's). The route is judged at the stretch with the least added width
for its need. The note names the layers - "2.95 mm as In1.Cu copper, on
In1.Cu, In4.Cu in parallel: In1.Cu 1.47 mm, In4.Cu 1.47 mm" - and the
verdict's `facts` carry them: `layers`, each `{layer, width_mm, scale, at,
route}`, the route's own first. Parallel layers count only when the route
fails on its own copper. A layer joined to the stretch's ends through other
holes than the route's own two is not counted. A route's width is the widest to any pin of
the load on the net: a load with several pins on a net (a small pin and an
exposed pad) is judged by the route to whichever is joined widest.

A neck is the stretch of the route narrower than the width its current
needs, and its length is measured along the route: through tracks, the
run of consecutive track segments narrower than the need (an arc along the
arc); through a pour or a zone fill, from the raster the check builds, the
path distance between where the copper at the entry reaches fill the need
wide and where the copper at the exit does (the flare into a neck counts,
a disc the need wide no longer fitting there), read within a step or two.
IPC-2221's chart is for a long conductor; a short constriction between
wide copper loses heat by conduction into the copper either side (IPC-2152
has no length term; Brooks and Adam's simulation, 2015, shows a 1 in. neck
at two thirds of a 6 in. neck's rise). A neck narrower than its need is
credited as short when conduction to the copper at each end alone holds its
peak rise, `rho I^2 L^2 / (8 k (w t)^2)` (one-dimensional conduction,
uniform heat generation, no side loss), inside `1 - check.neck_end_share`
of `check.rise_c`; `L_max = (w t / I) sqrt(8 k (1 - end_share) rise_c / rho)`
is the longest neck of that width that passes. The note says width, length
and which: "a 0.40 mm long neck at 1.03 mm, credited as short: 0.01 C of its 4 C
share of the 10 C rise by conduction to the copper at each end (a 1.03 mm wide
neck passes up to 7.48 mm at 3.6 A)", or "too long: ..." and the verdict fails
as it did before lengths were weighed. The verdict's value is still the width and
its limit the need. The copper at each end is taken as wide (a pad is taken
as a sink, as the route search takes it as passing any width) and cool to the
extent of `check.neck_end_share`; a fill narrower than one raster step has
no measurable length and is not credited. `reach=Reach.CURRENT` on a fitted pour
keeps widening toward the full width: only the verdict credits a short neck. A net only one part carries is not judged: one carrier cannot
say where its load goes (the widest-joined other pad is as often a
capacitor carrying ripple), and the verdict asks for a `Pm.I` on the part
that takes the load. A part carries on a net only at a current above zero:
a per-net `Pm.I` that leaves a net out, or gives it 0, leaves a sense pin
out of the load. Two carriers no copper joins yet are said, not judged. A board with no facts reports nothing to check. **Every `placemat
run` runs the same checks on the board it wrote**, prints one `checks` line -
how many failed, were accepted (`board.accept`), passed and were not judged,
then each failure - and keeps the
verdicts in `run.json` under `verdicts`, with `checks_failed`,
`checks_accepted` and `checks_unjudged` in the metrics. A verdict is "not judged" when no limit is
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
up to the one holding the outermost `placemat.toml` (the project root),
innermost first, so a `placemat.toml` beside a module does not cut it off from
the folders above: geometry
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
  a declared escape lane that something blocks (`board.escape`), and a setup finding (the same every run, 0 by default);
- each ratsnest crossing, with a plane's or free net's crossing at
  `score.crossing_plane` of it;
- the airwire itself, a millimetre each;
- the carried vias that gave way, at the cost the search priced each action (`score.via_share`, `via_move`,
  `via_leave`, `via_route`, `via_shorten`, `via_drop`, and a field relay's `score.via_relay*` once);
- each push, `score.push` times the modelled value over its limit at the final placement, the whole value as the
  search prices it, not only what is past the limit;
- each item a `face=Face.EITHER` search put on the back, `score.back_face`.

A finding's severity does not enter the score. A run records these measures, not its score, so a weight changed in
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
KiCadRoutingTools at `[route] router_dir`, else `$KRT_DIR` (default `~/work/KRT-upstream`) with
its own venv; quick mode is one routing round with the router's post-route
smoothing off (a measurement: a small two-layer board routes in about 10 s), `--full`
is the router's whole run. The search budget per net is the router's own
unless `--iterations` caps it. Left to itself (no `--layers`), the router
gets every layer whose role in the board's stackup is `signal` or `mixed`,
F.Cu and B.Cu always among them - the route step prints which layers it
left out and their role, and the report's `plane_layers` names them too.
`placemat route --layers` overrides for one run; the board's own roles are
a .zen fact, not a placemat.toml setting. A net with a zone or a filled
copper pour on the board is
left to its pour and not routed, as `run --route` leaves the plan's plane
nets; `--exclude` adds to them. The router does not see copper zones when it routes other nets: it lays
tracks through a board-wide fill, and the refill carves round them, so a fill
need not be switched off for routing. A partial pour on an inner layer of a
net left out would be split that way, so the router's input copy keeps other
nets' tracks out of its outline (vias may pass) and the route step says how
many pours it kept (`pours_kept` in the report); a route through one is a
keepout breach naming the pour. Outer-layer pours are left open to it: other
nets' pads sit in them.

Every router pass (the pairs, the island nets, the class stages, the main pass) is given
`route.turn_cost` (20000 by default, where the router's own default is
1000: at that a 45-degree kink costs the router 0.05 mm of path, and its
routes stair-step along the line to their target) and runs the router's
own smoothing; `route.router_args` passes more of its flags through
(`route.pair_router_args` to the pair router). Routes
already kept stay as they were laid: `placemat routes <script>
--release-all` drops them, and the next `route --adopt-all` lays them again.

Which nets pair comes from the board's own net classes, not a setting: a
class other than Default that sets `diff_pair_width` and `diff_pair_gap`
groups its nets into pairs. Exactly two nets in the class pair outright,
whatever they are called; more than two pair by the router's own suffix
convention (`_P`/`_N`, `P`/`N`, `+`/`-`) within the class. The Default
class never makes pairs - KiCad gives it its own diff pair figures even
when nobody declared one. A class of two nets named otherwise, such as a
tank's two leads, is routed the same way a named pair used to be: the route
step renames the two in its own copy to `PMPAIR<i>_P`/`PMPAIR<i>_N`, a name
no board net has, routes that pair, and names them back in the routed copy
before its copper is read or kept. The renamed nets keep their net classes.
Placement weighs every pair's crossings the same way, by its net class.

The pair router routes every pair on the route's own layers unless
`[route] pair_layers` names the pair, by its two nets or by its net class:

```toml
[route]
pair_layers = {"USB_D_P/USB_D_N" = ["In2.Cu", "B.Cu"]}
```

A key is `"P/N"` (the pair's two nets, either order) or a net class name; a
pair's own nets win over its class. The router takes one layer list per
call, so the pair stage runs it once per distinct list, the named pairs
first, each call on the board the one before it wrote with that call's
copper fixed (`pairs.log`, then `pairs_1.log` and on). A layer left out is an
obstacle to the pair, not a layer it routes on: the router lays no track on
it and its vias clear that layer's copper. So a pair whose escape lanes end in
vias on F.Cu, given inner and back layers, starts from those vias and cannot
tap a lane on F.Cu. Its ends must reach one of its layers: from a pad on a
layer left out, with no via, the pair router cannot start. The router may also
fail to couple a pair from two vias further apart than its own pair pitch and
route each half on its own (its single-ended fallback, still on the pair's
layers); the report's `pairs` says which. A pair it leaves unrouted is routed
by the main pass on the route's own layers. The report's `pair_layers` holds
the lists applied (`{"P/N": [layer, ...]}`); an unknown layer name is refused
when the settings load, and a key that names no pair on the board or a layer
the board does not have is a `setup.pair_layers` finding (facts `key`,
`variant` `no_pair` or `layer_missing`, `layers`, `missing`, `board_layers`,
also in `pair_layers_refused`), the entry not used.

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

A net that should keep other nets' copper further off than its class
clearance, such as a switch node, gets a halo in `[route] net_halos`:

```toml
[route]
net_halos = {"SW" = 2.0}
```

The router takes a per-net clearance map and spaces two nets at the larger
of their two values; left to itself it builds the map from the board's net
classes. With a halo on the board the route writes the map instead
(`net_clearances.json` in its work folder, `pairs_net_clearances.json` for
the pair stage, whose nets it renames): the router's own class map, built by
the router's own function, with each halo net at the larger of its class
clearance and its halo. A `--clearance-ceiling` in `route.router_args` (or
`route.pair_router_args`) caps the class entries as the router caps its own,
not the halos. Every router pass gets the map, so other nets' new copper
keeps the halo from the halo net's copper, and the halo net's own new copper
keeps it from everything; `--net-clearances` in the router args is refused
when the settings load. The report has `net_halos` (the entries applied) and
the summary line ends `halos: SW 2 mm`. Before the first router call the
route judges every pad of another net that the route routes and that has
open connections, lying within a halo of the halo net's copper (its pads,
tracks, vias, drawn copper and pours, on a layer they share): the router can
lead it out only from an end of its own copper that is already past the
halo. The ends are the pad itself, each end of a track joined to it and each
via on that copper. Only a track or via end counts: drawn copper (a polygon)
joins the pad to its tracks and vias but is not an end, however far it
reaches. A track leaving an end keeps its edge the halo away, so an end
counts as led out only at the halo plus half the pad net's class track width
from the halo net's copper. If no end lies that far, the pad is trapped: a
`setup.net_halo` finding, said before the route starts, with facts `variant`
`trapped`, `net`, `halo_mm`, `ref`, `number`, `pad_net`, `gap_mm` (the pad's
own gap to the halo net's copper), `reach_mm` (how far its farthest end
lies from that copper), `needed_mm` (the halo plus half the class track
width) and `short_mm` (`needed_mm` less `reach_mm`); also in
`net_halo_trapped`. The cure is in the module that draws the pad: an escape
that runs out past the halo (a longer `run=` on its `board.escape`), or a
smaller halo for that node. A halo net with open connections routes in the
class stage of its halo (below), not in the main pass. A key that names no net on the board is a `setup.net_halo`
finding with `variant` `no_net` (`net_halos_missing` in the report), the entry
not used; a halo that is not a number above 0 is refused when the settings
load.

A wide route the router cannot lay is retried at its default track width (its "neck-down"), so a width asked for is not a width
delivered. The route reads the router's own measurement of the copper it shipped from each stage's summary (`power_widths`,
`design_rules.narrowed`, `power_trace_ampacity`; `power_widths` only in a stage given a width, so an island net's) and keeps `widths` in
`route.json`: per net and stage that delivered under the width asked, `net`, `stage` (`islands` or `main`), `requested_mm`,
`delivered_min_mm`, `length_under_mm`, `length_mm` and `share` (null where the router gave only the narrowing), `declared` (the net has a
width in `[route] islands`), and `max_a` and `bottleneck_mm` (the router's IPC-2152 current for the narrowest copper, when it gave
one). The route's summary line ends `UNDER WIDTH: NET 16.6 of 17.2 mm under 1.37 (min 0.16)`, `route_summary.json` has `under_width`
(the same records), `placemat watch` and the studio's stream get a `route_width` event per record, and each is a `route.width` finding
in the console, `run.json` and `placemat route --json` (`finding_details`). A net the router recorded as narrowed but the script gave no
width is not measured per length and has `length_mm` null. Net-class and pair widths are reported only where the router records a
narrowing of them: its pair router writes no summary.

The routed copy is cleaned as KiCad's own cleanup cleans a board, over the copper the router added only: its dangling tracks and vias
are deleted, again until none is left, and then the router's collinear pieces are merged. KiCad counts a segment whose ends both land
on one other item of its net (a copper polygon, another track's body) as connected at one end only, so the router's short tails there
are dangling. Copper the router was given is never touched: an item with a uuid or geometry of the input board's, and a router
segment lying on a given track of its net and layer (a given track written again). A net whose pads are not all joined in the routed
copy keeps its router copper, as progress a later route builds on; a floating fragment beside joined pads does not make a net
unjoined, and is removed. A net whose pads the deletion would part (a track KiCad calls dangling that another of the net's tracks
lands on) keeps all its router copper; the other nets are cleaned. `route.json` and the route record have `dangling_removed`:
`tracks`, `vias` and `merged` per net, `unconnected` (the board's count before and after), `kept_unrouted` (the unjoined nets whose
dangling router copper was kept) and `refused_nets` (the nets kept because the deletion would part their pads). The summary line says
`dangling router copper removed: N track(s), M via(s) on K net(s)`, `dangling router copper kept on N unrouted net(s): NET, ...` and
`dangling router copper kept on N net(s) whose pads it alone joins: NET, ...`.

A footprint's own copper graphics (a net-tie's winding, a copper logo) are
guarded in the router's input copy: a rule area over each, on its own layer,
forbidding tracks and vias (a route through one is a keepout breach naming
its footprint). The guards are deleted from the routed copy before its DRC
is run. The router keeps a footprint's copper graphics on every layer, so
nothing is put back.

**Class stages.** The router spaces every net of one call at the largest
clearance among the nets that call routes (its routing-side floor), and keeps
other nets' copper at the larger of that floor and the copper's own class
clearance. So a 0.2 mm class routed with the Default nets would space every
one of them at 0.2 mm. The route therefore takes each net it would leave to
the main pass whose clearance in the router's map (its class clearance, or its
halo) is above the Default class's, groups those nets by that clearance, and
routes each group in a router call of its own, widest first, after the islands
and before the main pass. Each routes at its own clearance; the main pass,
without them, at the Default's. A `--clearance` or `--clearance-ceiling` in
`route.router_args` is applied to both sides as the router applies it. A net a
class stage leaves open is not routed again by the main pass (there it would
space every net at its clearance again); it stays open in the report. The
report's `class_stages` lists them, widest first, each `clearance_mm` and
`nets` (`{net: [open items before, after]}`), and the summary line has
`class stages: 0.2 mm RF 1 -> 0`.

**Stages and resume.** A route works in four stages - the differential
pairs, the islands, the class stages, the main pass - and keeps each in its work folder
(`<run dir>/route/`, or `.placemat/route/`, or `--out`) as it finishes:
`state.json` has the stage, the digest of its inputs (the board and its
project files, the nets left out, the islands, the layers, `quick`, the
iteration caps, the router and its version, the `[route]` settings), chained
from the stage before, and the stage's result (its board, the pair outcome,
the breaches, the time). A rerun whose digests match takes those stages
(`took islands, main from an earlier route of the same inputs`;
`metrics.route.resumed`) and routes the rest; the first stage that does not
match is dropped with its files and every later stage, and routed. A stop
(`SIGTERM`, Ctrl-C) or a router failure leaves the finished stages and the
partial stage's log. `--no-resume` routes every stage again. The main pass is
one stage: nothing inside it is kept (the router's own `KICAD_STOP_AFTER` /
`KICAD_STOP_FILE` checkpoint stop, which writes the partial board, could be
used for that later). The router's raw output is `router_out.kicad_pcb`;
`routed.kicad_pcb` is made from it, then post-processed, every time.

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

## Live progress

A command that resolves a board (`run`, `preview`, an explore inside them, `check`, `route`, whoever started it) owns a Unix
socket for as long as it runs (Linux and macOS):

- `<project root>/.placemat/sockets/<pid>.sock` (the project root is the outermost folder above the board holding a
  `placemat.toml` or a workspace `pcb.toml`, so `placemat watch` finds the command from any folder of the project), with
  `<pid>.json` beside it: `pid`, `command`, `script`, `args`,
  `started`, `label` (from `--label`), `progress` (the trail's path) and `socket`. Both go when the command exits; a reader
  that finds an entry whose pid is gone removes it. A path too long for a socket address puts the socket under the
  temporary directory, named in the entry's `socket`.
- A reader connects and is sent a catch-up first, then live events: newline-delimited JSON, one object each, `ev` naming it.
  `hello` (the entry's fields), `resolve` (`n`: a new resolve; the board and steps before it are forgotten), `board`,
  `begin` (`kind` `total` with the counts, `begin` for the item now being worked on with its `what` and `rank`/`of`, or
  `phase`: what the item is doing now, as data. `stage` is one of `declared`, `seeding`, `scan` (with `face` `front`, `back` or `either`, `hint`
  and `radius`), `coarse`, `coarse_half` (the coarse pass again at half the stride), `fine`, `refine` (with `within`, `[k, n]`: the k-th of n
  spots being refined) and `give_way` (candidates refused only by carried vias judged again); with the `item` and `elapsed_s`, its seconds so
  far, when the phase is part of a step, and `firm_pass` when it is in one of the passes over the firm items (`place.firm_passes`). The
  words are made where the event is read, `placemat watch` and the studio's pill), `step_warn` and `step_limit` (a step past its
  `--step-warn` or `--step-limit` time: `item`, `elapsed_s`, `bound_s`, `pass` (`coarse`, `fine`, `refine`, `give-way`, ...; `firm pass k` before the step has reached a pass of its search),
  `stage`, `within`, `firm_pass`, `at`), `item` (a settled step: the item, its copper or cutout ops; the item carries `seconds` and, for a replayed step, `first_seconds`, `notes` and, for one with no place, `unplaced`), `plan` (`doc`: the whole
  plan as the studio draws it), for an explore `explore` (focus, the plain placement and order, the baseline score, jobs),
  `variant` (`seed`, `score`, the focused items' `placements` and `order`) and `explore_done` (`best`, `baseline`, `tried`,
  `kept`, `record`), for a route the `route_*` events below, then `done` (`record`: the run's `run.json` or the explore's record) or `error` (`kind`, `file`,
  `line` and the fields of its kind: `run_failure` has `failure` (the stage: `generation`, `script`, `placement`, `explore`, `escape`),
  `item` and the free text `detail`; `exception` has `type` and `detail`; `probe_refused` has `code` and its facts; `stopped` is the
  stop record). A command that dies sends neither: the connection closes.
- What is sent is records, never sentences: a step's `notes` are `{"kind", ...facts}` (`step_text.py`; units in the field's name, a refusal
  as `{"code", ...}`), an error is a `kind` and fields, and free text appears only where the data is free text (an exception's own message,
  a script's `why=`), as a field beside the structured ones. `placemat watch` and the studio's page turn them into words with the same
  renderers (`channel.describe`, `present.py`). `hello.format` is the version of this: 2 from this release, where format 1 (a `hello` with
  no `format`) had a sentence for an item's `note`, an error's `message`, a route's `why` and a probe's `text`. Plan JSON is `version` 3
  for the same reason. A reader outside the repository checks `format` and reads the fields above.
- Step durations. `Step.seconds` is how long the step took in this resolve, measured with `time.perf_counter` from the previous step's end (the
  work between two steps, such as give-way and settling, is in the step it was for), so the steps add up to the resolve less the passes after
  the last step. A replayed step's `seconds` is its replay; `Step.first_seconds` is what it took when it was first resolved, from the reuse
  record (`None` for a step that was resolved, or replayed from a record that has no times). `seconds` and `first_seconds` are in each `plan`
  doc step and each `item` event's item, rounded to a millisecond; the plan doc's `seconds` is the whole resolve's. `run.json` keeps
  `steps[i].seconds` and `first_seconds`, and `metrics.resolve_seconds`.
- A route (`placemat route`, or `run --route`) streams per-net events from the router's own process: `route_board` (`doc`: the
  board and its parts as the studio draws them; with a run's plan the run's plan is used instead), `route_stage` (`stage`: `pairs`,
  `islands`, `classes` or `main`, `resumed` when the stage was kept from an earlier route), `route_queue` (`nets`: the nets the stage will take, in
  order), `route_net_begin` / `route_net_end` (`net`, `ok`), `route_commit` (`net`, `how` `route` or `restore`, `seg` as
  `[x1, y1, x2, y2, layer, width]`, `via` as `[x, y, size, drill, layers]`: copper as it is laid), `route_rip` (the same shapes:
  copper taken up again), `route_queue_end`, and `route_off` (`reason`: `{"code": "no_function" | "no_parameter" | "no_field" |
  "import_failed" | "pipe_closed", ...}`) when the hooks could not be installed - the route then runs with no progress and says why. They come from a wrapper around the router's per-net functions (`kicad/route_events.py`, installed by
  `kicad/route_hooked.py` and `route_one_round.py`; each hook is anchored on the router's own function names, signatures and
  field names and installs nothing when one is missing), sent over a pipe the route opens for each stage
  (`PLACEMAT_ROUTE_EVENTS_FD` names its write end in the router's process; a full queue drops events, a closed pipe ends them), so no file
  and no router output is involved. `PLACEMAT_ROUTE_EVENTS=off` leaves the router unhooked. A pair stage names
  its nets by the board's names. A reader that attaches late is caught up on up to 60000 route events (a `route_truncated` event says
  when more were made).
- The route record, `route/route_record.json` (with `route_summary.json` beside it, a few counts, and `route_board.json`, the
  board the copper was laid on): `board` (`pcb`, `run`, `script`), `stages` (each with `stage`, `resumed`, `seconds` and its
  `events` in laid order: the same events without the `route_` prefix) and `report`. It is `report.record` in a run's route metrics
  and `run.json`. A run that routes also writes `plan.json` in its run folder, so the studio can replay placement and routing as one.
- The command never waits on a reader: each has a bounded queue and events that do not fit are dropped, a reader that goes
  away is dropped. A board resolved with no script (a bench, a test) listens on nothing, and `PLACEMAT_CHANNEL=off` turns
  it off.
- The trail: the events are also written, in short form (no drawings; an `item` keeps its `notes`), to an append-only `progress.jsonl`, flushed as it goes:
  `.placemat/runs/<id>/progress.jsonl` for a run, else `.placemat/views/<command>/progress-<pid>.jsonl`. When a command starts it
  deletes the trail files of its script that earlier commands left and that are no longer running. A trail is read for a
  command that ended or died, never as the live feed.
- An explore's record (`.placemat/views/explore/<time>-<pid>.json`) and a run's `run.json` are read after `done`.

```
placemat watch [<pid|label>] [--json]
```

follows one command or all of them in the project, a line per event (`--json`: the events as sent), and exits when they
end: 0 done, 1 error, 2 died (its last state is printed from its trail) or not found. A line reads `ble: searching, rank 3 of 12` when an item
begins, `ble: refining around the best spots, 2 of 3, 12.4 s` for a phase (the seconds are the step's so far), `ble part, 31.2 s: moved 0.4 mm`
when it settles and `ble: still working after 30.4 s (--step-warn 30 s) in the refine pass 2 of 3` for a slow step. Written for an agent that starts a long
job detached and then follows it; the studio's Runs view reads the same sockets.

## Studio

`placemat studio` shows a layout as it is made, in a browser, and keeps it
current as the script changes, whoever changes it: the user's editor or an
agent.

```
placemat studio [<script>] [--port N] [--no-open] [--host ADDR]
```

Each command that resolves a board listens on a Unix socket of its own (`<project root>/.placemat/sockets/<pid>.sock`,
with `<pid>.json` beside it) that the studio, `placemat watch [pid|label] [--json]` or an agent can read - see "The
live channel" in the studio spec; an explore's variants are kept in
`.placemat/views/explore/*.json`, and `GET /cmd/ID` and `GET /explore?f=PATH` serve a command's events and an
explore's record. `GET /routes` lists the recorded routes of the
script's board (`.placemat/route/` and each run's `route/`), `GET /route?f=PATH` serves a route's replay document (a step per
part, then a `copper` step per net in laid order) and `GET /build?run=ID` a run's placement and route as one document, with the run's
score. A route in the Runs view draws its tracks net by net as they are laid, with the net it is on and the routed and failed counts; a
finished one replays from its record. The router's copper is drawn hollow (the track in its layer's colour, its core in the board's), and
the legend's "Copper origin" rows count, hide and show (or show alone, "only") each kind: planned (the copper the script declares, as
the plan laid it), kept (a route kept beside the script by `placemat route --adopt`, laid again by the plan) and routed (the router's).
In a replay document the router's copper ops and its nets' steps carry `origin: "routed"`; a route's live events are tagged the same in
the page. A past run that routed (it has a route record and a `plan.json`) opens as its build, at the end of its replay: the board as
the router left it; one that did not route opens with the board it wrote.

With no `<script>` (and no `s=`, `run=` or `cmd=` in the address) the page follows the latest command of the project, the "Latest" mode:
the command that started last while one is running, else the command or record that ended last (a command, a past run, an explore or a
route), shown as the Runs tab's views show it. A command that starts anywhere in the project (the channel's `cmd` event, `state` "running")
takes over; one that ends stays shown until the next starts. The studio's own search probes (`kind` "apply") do not count. A switch is held
back, and the page offers it ("A newer run started", "Go to it"), when the viewer selected an item, opened a finding or moved the view in
the last `[studio] follow_hold_s` seconds (10; sent in `hello` as `follow_hold_s`; 0 never holds) or has the dialog open. The header shows a
"latest" chip beside the command's kind. A project with no command or run opens on the dialog below instead. The address's hash names the
mode as `latest`; `s=`, `run=` and `cmd=` pin as before.

The dialog, "Open", sits over the usual interface (Runs tab first; the findings layer on
the board is off until the Findings tab is open or the legend turns it on). Its first section, "Runs", holds "Follow latest", marked
"current" while that is the mode; choosing anything below it leaves Latest. The other choices: a command running now (followed live, as a
background run), a past run (`GET /projectruns` lists every board's `run.json` records; `GET /runview?run=ID` serves one as a plan
document - the run's `plan.json` when it has one, else the board it wrote with its findings placed from their facts - and resolves
nothing) or a layout script (`POST /switch`, the only choice that starts the studio's own preview). The header title opens it again.
The address's hash can name a script (`s=`), a past run (`run=ID`) or a running command (`cmd=ID`). Every command in a list says what it
is - preview, full run, explore or route - by a chip; a command summary carries `kind` (`channel.kind_of`: a run or preview given
`--explore`, or one that has sent `explore` events, is an explore) and `label`. Following an explore shows its focus, variants landed (of
its seeds when it has a fixed number), the seed that landed last, the baseline, the best so far and the time, and the board draws the best
variant so far; `GET /explores` lists the recorded explores. Under it, the pin map study of the best variants (the
record's and `explore_done`'s `pin_maps`, "The pin map study"), each beside its score. A `pins.remap` finding lists every pose its
study searched, and a row clicked draws that pose's airwires.

It prints an address (`http://127.0.0.1:PORT/?t=TOKEN`) and opens it unless
`--no-open`. By default the server listens on 127.0.0.1 only. Every request
needs the token in the address (and a `Host` header the studio listens on);
GET serves the page and its data, and POST only `/switch`, `/run`, `/resolve`, the builder's `/build/...` ("Studio builder") and
`/suggest/show`, `/suggest/try`, `/suggest/apply` and `/suggest/undo`. Stop it with Ctrl-C.
Suggestions (`finding.suggestions` in the plan) are shown on each finding row, the card and the step rows: the best one,
with "more (n)" for the other variants (up to `[studio] suggestions_per_lever` of one lever). Three buttons, each
`POST {resolve, id}` with the token (the page never sends source text; the studio finds the suggestion in that
resolve's findings). On a past run, explore, route or command opened in place of the studio's own plan the page sends
`{view: {kind, ref}, id}` instead (`kind` one of `run`, `build`, `route`, `explore`, `cmd`, `ref` the run id, record file
or command id it was opened by); the studio finds the suggestion in that view's plan, a try is compared with that plan,
and a script that changed since is refused (409, "this run's script has changed since; re-run to act on its suggestions").
A try or a search of a view of another script than the one watched is refused (409):

- Show, `POST /suggest/show`: the dry-run diff of every file the edit writes (unified diff, hunks, the lines changed, the
  declarations the edit names), opened in the script dialog with Apply and Cancel. Nothing is written.
- Try, `POST /suggest/try`: the edited text is resolved in the warm worker with the edited files read from an overlay
  (`placemat.context.overlay`: the layout script, the modules it imports and `placemat.toml`), the last record replayed from
  and none written. Only on a click, only when no resolve is running or pending, one at a time, at most
  `[studio] try_timeout_s`; a change to a watched file cancels it. The answer is compared with the resolve the suggestion
  was made on: `cleared` (the finding's `(kind, case, item)` is gone), findings `gained` and `lost`, items `moved`, the
  `score` change, the file diff and the try's plan. The page shows it as a compare marked "try, not written" and does not
  add it to the history; a try's own suggestions are never offered.
- Apply, `POST /suggest/apply`, Undo, `POST /suggest/undo` (the same call as `placemat apply --undo`) and Redo, `POST /suggest/redo`
  (makes again the apply the last undo took back; refused when a file has moved on since, or when nothing is left to redo): written
  atomically under the project root to files the studio watches, logged in `.placemat/applied.jsonl`; the watcher
  resolves again and the history row reads "applied from a suggestion: ...". A file that changed since the plan refuses
  (409, nothing written), as does an undo when a file is not as the apply left it. Allowed over `--host` (the token guards
  it); `[studio] apply = false` refuses writing (403) and hides the buttons. Refusals are `{"error": sentence}`: 404 no
  such resolve or suggestion, 409 stale, busy or nothing to undo, 422 the edit cannot be made.

One studio serves one script at a time. It needs the board's cached generation, as
`preview` does: `placemat run` the script once first.

`--host ADDR` listens on another address (`0.0.0.0` for every one), so a phone
or another machine on the network can open the page; the token is still
required. With it the terminal prints a QR code of the address under it, and
the page's "Share" button shows a QR code of the current view's address on the
studio's LAN address, with the address to copy (the view is kept in the
address's hash: script, face, visible box, selection, finding, tab). A studio
on 127.0.0.1 says to start it with `--host 0.0.0.0` instead. The QR code is
drawn by the studio itself at `GET /qr?u=ADDRESS`, for its own addresses only. A
port already in use ends the command with a message, naming another studio
when it is one; `--port 0` (the `[studio] port` default) takes any free port.

With no `<script>` the studio finds the layout scripts under the current
directory's project (the folder of the outermost `placemat.toml` above it, else
the current directory) and the page opens on a list of them, resolving nothing
until one is chosen; with none found it exits naming the folder it searched.
The board's name in the page's header is the same list as a menu, to switch
script in place.

**What it watches.** The script, every module it imports (the files
`script_fingerprint` reads), its `.lock.json` and `.routes.json`, every
`placemat.toml` above the board, the fab profile and the cached generation.
Modification times are polled (`[studio] poll_ms`). After `[studio]
debounce_ms` without another change it resolves; a change while a resolve
runs stops that one at its next step and starts again, so a plan that does
not match the files on disk is never shown as current: the page marks the
board stale the moment a file changes.

**What it resolves with.** A worker process that stays warm between resolves
(imports, the cached generation and the last record loaded) and resolves as
`placemat preview` does, replaying the steps the edit did not change from
its own previous resolve (`.placemat/views/studio/reuse.json`). It writes
nothing to the board and runs no DRC and no render. A script that fails is
shown as an error with its line, over the last good plan, marked stale.

**What the page shows.**

- The board from placemat's own model, the same one `preview` draws:
  outline, keepouts, parts by face (the back mirrored), copper, links,
  congestion. Pan and zoom, a toggle for each layer, a face switch.
- Each step as it settles, in placement order with its note; the slider
  replays the placement step by step, drawing each step's copper (tracks, vias,
  pours) from that step on, in 2D and 3D. Play runs the whole placement in
  about 8 seconds at 1x; the speed select beside the slider sets 0.1x to 4x of
  that pace, kept per browser. The buttons either side of Play, and the Left
  and Right arrow keys outside a field, pause play and move one step. A click
  on a step zooms to its item.
  The card of a cell that chose among arrangements lists each one tried,
  with its total, whether it was legal, and which was taken.
- The findings; a click zooms to the place a finding names.
- Hover a part: name, value, cell, face, rotation, how it was placed
  (decided, searched, pocket), its note and findings, its links with their
  lengths.
- The script beside the board, read only, with line numbers. Clicking a part
  marks the statement that declared it, and clicking a line selects the
  items that statement declares.
- Compare. After each resolve the page compares it with the one before (or
  any two of the last `[studio] keep`): the lines of the script and of each
  changed file (unified or side by side, changed lines marked), and the
  diagram - items that moved drawn at their old place with an arrow to the
  new one (a cell whose arrangement changed is listed with the change), items added and removed, copper that changed in both states,
  findings gained and lost, the run score's change. The two are linked:
  selecting a changed line marks the items it moved, and selecting a moved
  item marks the changed lines of its declaration. A moved item whose own
  declaration did not change was moved by something else the edit did; the
  page says so.

**Buttons.** The header has Run, Resolve, Share and Source (one menu button on a
phone); the board's name is a menu of the project's layout scripts. Resolve
cancels what is running and resolves again now, and its menu offers a full
resolve from scratch, as the strip shown during a resolve has "Again".

**Run.** The Run button runs `placemat run <script> --no-render` (the design
checks, KiCad's DRC and the score, a run record in `.placemat/runs`) and shows
its progress and result; the Compare panel lists the runs recorded for the
script, from here or elsewhere, each with its score (a module run's detail
lists its arrangements: offered, refused, or the same as another), DRC by
kind, failed checks and findings by severity, and compares the newest
resolve with one: items moved (a cell's changed arrangement included),
added and removed, findings gained and lost, the score. A run records no copper
or links, so those are not compared. `GET /runs`, `GET /runcompare?run=ID` and
`POST /run` and `POST /resolve` (`{"fresh": bool}`: cancel and resolve again now, with no replay of unchanged steps when fresh; token required) serve them; `run_started`, `run_line` and `run_done`
are its events.

**When the worker dies.** A worker stopped by a signal is reported by name; a
crash is reported with the signal and, from the Python traceback `faulthandler`
leaves in `worker.log`, the innermost frame in the script or a module it imports
(file, line, source line) as the `error` event's `file`, `line` and `source`.
A script's exception gives its type and message and the same innermost frame.

The compare is also the server's: `/diff?a=ID&b=ID`, `/resolve/ID` and
`/history` answer with JSON (token required), and `/events` is the stream
(Server-Sent Events: `started` with the changed files and their diffs, a
`step` per item, `copper`, `links`, `congestion`, `findings`, `items`,
`finished`, `compare`; `begin` as the engine starts an item or a copper batch
and says what a long step is doing; `changed`, `cancelled`, `superseded` and `error` as
they happen).

The script is read only in the page; edit it in an editor, or let an agent
edit it, and the page follows. An agent may tell the user to run `placemat
studio` to watch its work.

### The 3D view

A 2D | 3D switch in the board area replaces the drawing with the board built: its outline extruded to the stackup thickness with cutouts and
drills, each part drawn from its real 3D model at the pose the plan gave it, the rest of the page (legend, steps, cards, replay bar,
selection) shared. The replay slider shows the first k steps in 3D as it does in 2D, and a resolve under way adds its parts as their steps settle.
Orbit with one finger or the left button, pan with two fingers or the right button, zoom with the wheel or a pinch, double tap or Fit to fit,
Top, Bottom (mirrored, as the 2D back) and Iso; a click selects, as in 2D. A part with no usable model is a plate: its courtyard (else its
body, else the box of its shapes) 0.1 mm off its face, hatched, flagged with the reason ("no model declared", "model not found: <path>", "conversion failed: ...", "loading"); the legend
counts parts by state, lists the plates, retries failed conversions and can dim the parts that have a model.

The copper is drawn too, each copper layer at its height in the board: tracks as flat ribbons with round ends, planes and pours as their
filled outlines (the polygons the 2D view draws), pads and the parts' own copper on each layer they are on, vias as cylinders through the
layers they join. The colours are the 2D view's layer colours; copper the router laid is drawn lighter, as the 3D form of its hollow 2D
look. The replay shows copper as the 2D drawing does: each op from the step that lays it to the one that rips it up, if any, in a plan's replay and a route's.
Solid | See-through on the 3D bar draws the board body solid or translucent (in the 2D drawing's substrate colour), so the inner layers'
copper shows through it; the choice is kept while the page switches between 2D and 3D. The legend's switches are one set for both views:
a copper layer's row and its only button, a zone's row, the pads and vias rows and the Copper origin rows (planned, kept, routed) hide and
show the same copper in 3D as in 2D, and switching views keeps them.

The Marks rows act on 3D too. Each finding placed on the board (where it says, else at the pad or part it names) is a marker at its place
and on the copper layer its facts name, else on the face of the part it is about, in its severity's colour (`--sev-critical`,
`--sev-warning-mark`, `--sev-notice`: a warning is yellow in both themes, the fill token of the 2D finding areas and counts too, while warning text keeps `--sev-warning`); a click on a marker selects it as a click on a 2D finding area does (one finding is looked at: the
selection and the card follow; several on one spot are listed in the Findings tab), and hovering one lists what it says. Congestion is a
translucent sheet lying on the top layer, under its copper, cell by cell in the 2D overlay's colours with the most congested cell ringed:
the map is of every routing layer together, as 2D draws it under both faces. Both are hidden while a replay is under way, as in 2D.

Spread on the 3D bar pulls the stack apart, so each copper layer stands clear of the next and the inner ones can be told apart from an
angle: each layer moves `3d_spread_mm` (4) further from the next over `3d_spread_ms` (450), the middle of the stack staying where it is.
The vias stretch through the spread, the markers and the congestion sheet ride on their layers, front parts ride above the top layer and
back parts below the bottom one. The board body fades out while the layers part, and each layer gets the board's outline at its height,
edged, and filled solid or faintly as Solid | See-through says. Spread again closes the stack; the choice is kept across views.

- **Plan document** (`version` 2, all additive): each member of an item has `models`, one entry per model of the footprint: `{id, state, name,
  opacity, why, matrix}`. `state` is `ok`, `vrml` (a VRML model with no STEP beside it, read by placemat itself), `none`, `missing` (`why` says
  `model not found: <path as written>`) or `hidden`; `id` names the model by its content (32 hex of SHA-256, or `e-` and KiCad's checksum for an
  embedded model); `matrix` is the 16 numbers, column-major, millimetres, from the model's own frame (x right, y up the footprint's page, z up out
  of the board) to the scene frame (x = board x, y up, z = board y), composed in Python from the footprint as generated, the plan's move and the
  stackup (`model_place.py`, measured against `kicad-cli pcb export glb` to a micrometre). The plan has `stackup` (`thickness`, `copper`: layer ->
  mm, `layers`: each copper layer top to bottom as `{name, z, thickness}` with `z` the height of its middle in mm from the back face, read from
  the board file's stackup by walking down through its mask, copper and dielectric rows and scaled to `thickness`; `declared`: false when the
  file has no stackup that lists every copper layer, and the layers are spaced evenly through the thickness with the outer ones on the faces)
  and `models`, the table of distinct models seen. A plan from an older worker has none of it and still draws in 2D; in 3D its layers are
  spaced evenly.
- **Routes** (token required): `GET /3d/models` (the converter's status and every model's `{state, tris, message}`), `GET /3d/model/<id>.pmm` (the
  converted mesh, immutable; the id is validated), `GET /3d/lib/<token>/<file>` (the viewer script and the vendored three.js, MIT, from a fixed
  list; the token is in the path so the modules it imports come with it), `POST /3d/retry {id?}` (forget failed conversions and queue them
  again). `hello` has `models3d` (status) and `models`.
- **Events**: `model` `{id, state, tris, message}` as each conversion ends, `models` `{done, total, current}` while a batch runs, `models3d`
  (the converter is ready, its self-test) as it starts or stops.
- **Conversion** is a separate process (`python -m placemat.model_convert`, JSON lines) the studio keeps, at low priority: `kicad-cli pcb export
  glb` on a scratch board per batch of `studio_3d_batch` models, a VRML reader of placemat's own for a `.wrl` with no STEP, simplification of a mesh over
  `studio_3d_model_tris`, and a self-test at start that refuses a KiCad whose model planes are not where `model_place.py` says. A model is resolved
  as `models.resolve_model` does (embedded, absolute, `${KIPRJMOD}` after the write step's re-anchoring, other variables, relative, a STEP beside a
  `.wrl`). Meshes are cached by content in the user's cache folder, shared by every project: `~/.cache/placemat/models` (`studio_3d_cache_dir`),
  `studio_3d_cache_mb` (512) bound with the least recently used removed first, a converter version in each file name.
- **Settings** (`[studio]`): `3d_kicad_cli`, `3d_model_dirs`, `3d_cache_dir`, `3d_cache_mb`, `3d_batch`, `3d_batch_timeout_s`, `3d_model_tris`,
  `3d_max_tris` (past it the parts are drawn as plates and the view says so), `3d_appear_ms`, `3d_plate_mm`, `3d_spread_mm`, `3d_spread_ms`.
- Other commands' streamed `item` events carry the same `models` and an extra `model_jobs` (for the studio's converter, not the page), so a
  command opened in the Runs view can be watched in 3D.
- A record carries no models: `GET /runview`, `/build` and `/route` give each member the models of the board the run or route wrote (the
  run folder's `layout.kicad_pcb`, a route's `in.kicad_pcb`, matched by reference, `${KIPRJMOD}` read as the board's own folder from the
  run record), with the plan's `models` and `stackup`, and queue those models for the converter, so a past run is drawn in 3D as a live
  one is.

## Exploring a placement

Once the declarations are right, the placer can search its own choices for
the items it was left to place:

```
placemat run <script> --explore SECONDS [--focus ITEM ...] [--focus-after LINE]
                      [--focus-box X0,Y0,X1,Y1] [--jobs N] [--accept] [--resume | --no-resume]
placemat preview <script> --explore SECONDS [the same]
placemat lock <script> [--current [--partial] | --release ITEM ... | --release-all | --accept-seed N]
placemat freeze <script> ITEM ... | --all [--fixed]
```

**What varies.** Only the items in focus, and only what the search chooses
for them: a focused item draws among its better legal spots (within
`[explore] slack` of its best, the best the likeliest), rotation with the
spot, and, for a cell that offers arrangements, the arrangement with it:
the draw is over the legal spots of every arrangement pooled, on both faces
of an either-face item, each at its total as the search compares it, and
the margin is not asked. A variant's `placements` entry for each focused
item is `[x, y, rotation, face, arrangement]` (`""` for the module's own
layout; a record from before arrangements has four elements), so the
record carries each variant's arrangement. A move in the report names an
arrangement that changed (`arrangement default -> pair.upright`). Two focused items next in the
placement order sometimes trade turns (`[explore] swap`). Everything else is placed as the plain run places
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
With pin pools on the board, the best `pins.explore_top` variants by run score are studied (the pin map study) under the lock they were ranked under, before an accept; a line per studied group gives its weighted crossings now and after remapping (`pin map, seed 3 at 120.4 mm: U1 40 -> 22 weighted crossings after remapping`, with `, at 90 degrees` added when the best pose turns the part, or `, with cell logic turned to 90 degrees` when it turns the part's cell), and a last line gives the time the study took after the explore's own (`pin map study: 3 variants in 1.20 s, after the explore's time`). The report's `pin_maps` (per variant `seed`, `score`, `groups`, `seconds` for its resolve and study, or `error` when its study raised) sits beside the score and does not change the ranking.
Without `--accept` nothing persists.

**Stopping.** `run`, `preview` and `route` stop on SIGTERM, SIGHUP or Ctrl-C
(a second signal exits at once). A stopped explore prints `explore stopped by
SIGTERM after N variants in T s; best seed S: a -> b mm; nothing accepted;
accept it with: placemat lock <script> --accept-seed S`; the lock is never
written on a stop, even with `--accept`, and `placemat lock <script>
--accept-seed S` writes the best from `<board>/.placemat/explore/<script
stem>/best.json` (refused when the lock or the script changed since). A
stopped run's `run.json` has `status: "stopped"` and `failure: {kind:
"stopped", signal, stage, elapsed_s, explore}`, the layout folder is as the
last run left it, a final line names the stage and the signal, and the exit
status is 128 + the signal. While a run works its `run.json` says `status:
"running"` and its `pid`; a record whose pid is gone died without finishing.

**Bounding the time.** Three bounds, each a flag of `run` and `preview` and a `[run]` setting (a flag wins; 0 is off, the default):

```
placemat preview <script> --max-time 120 --step-warn 30 --step-limit 90
```

- `--max-time SECONDS` (`run.max_time_s`) stops the command through the stop path a SIGTERM takes, when the time since it began is up. It
  covers the placement: the generation, an explore and the resolve. Once the resolve is done it is lifted, because the write, DRC and render that
  follow are not safe to cut and have their `[timeout]`s. The stop is a SIGTERM raised by a watchdog thread, so it lands at the next point Python
  can run (between native calls), and everything a stop keeps is kept: a run is recorded `stopped`, an explore keeps its finished variants and its
  checkpoint, and the steps finished are in `reuse.partial.jsonl`. The exit status is 143 and the line says how far it got, e.g. `preview stopped
  at --max-time 120 s during resolve: 14 of 40 steps done, ble in progress (refine pass 2 of 3, 31 s), 3 finding(s) so far (1 critical, 2
  notice); run it again and it goes on from there (the 14 finished steps are replayed, not searched again), with a larger --max-time or
  none`. The record carries it as data: `run.json`'s `failure` (and the channel's `error` event) has `cause: "max_time"`, `limit_s`,
  `elapsed_s`, `steps_done`, `steps_of`, `steps_replayed`, `in_progress` (`item`, `elapsed_s`, `pass`, `stage`, `within`, `firm_pass`, or null
  between steps) and `findings` (`count`, `by_severity`). The steps it did are the placements an uncapped run makes for them; the rerun replays
  them and carries on, so repeated capped reruns of one command finish it.
- `--step-warn SECONDS` (`run.step_warn_s`): a step still working after that long sends a `step_warn` event and a console line, and
  ends with a finding of kind `time`, cause `time.step_slow` (notice): `item`, `elapsed_s`, `warn_s`, `pass`. The placement is what it
  would have been, and the step is replayed by a later run.
- `--step-limit SECONDS` (`run.step_limit_s`): a step past it gives up. The search checks at the points where it changes pass (before the
  coarse pass, before each refine spot, before a fine pass; `placer.scan`'s phases), not inside a native sweep, so a step is cut at its next pass
  boundary and a single long pass runs to its end. The step is left unplaced, or at the best legal spot its scan had found when the limit was
  reached, and the finding `time.step_limit` (`kept` `unplaced` or `best_so_far`, `elapsed_s`, `limit_s`, `pass`) says so; severity critical
  when unplaced, warning otherwise. The resolve goes on with the next item. A step that gave up is not replayed: its reuse key is never matched,
  so the next run searches it again (and the steps after it). A required item that gives up fails the run as any unplaced one.

Every one of these is wall-clock time and so depends on machine load: the same board on a busy machine cuts steps a quiet one finishes. A
bound that does not depend on load is a candidate budget (`place.step_budget`), counted in candidates judged. The bounds are not part of a
run's id or of what a record replays. An explore's variants are not timed (only the command's own resolve is); `--max-time` still stops the
explore.

**Checkpoint and resume.** An explore keeps its state in
`<board>/.placemat/explore/<script stem>/`. `checkpoint.jsonl` is a header (the
digest and the parts it is made of - script, generated board, settings, fab
profile, placemat version, lock, focus - the baseline's score and measures, the
budget), a line per finished variant `{"v": seed, "s": score, "t": seconds
spent in all}` (a variant better than every one before it also has `"m"`, its
measures), flushed as it goes, a `{"stop": signal}` line when it was stopped
and `{"done": true}` when it finished; a line cut short by a kill is ignored.
`best.json` holds the best variant's lock entries (replaced atomically at each
new best) and what `placemat lock <script> --accept-seed N` writes. A rerun
with the same digest continues: `resuming a saved explore: N variants in T s
so far`, the baseline from the header, the untried seeds only, `SECONDS` less
the time already spent (a fixed list of seeds: those not tried). `--resume`
refuses a checkpoint with another digest, naming what changed; with no flag it
is dropped with a note and the explore starts over; `--no-resume` starts over
always. The checkpoint is removed when the run that explored is recorded (a
`preview`, which records nothing, removes it when it has the result); a run
that fails or is stopped after a complete explore leaves it, and the rerun
takes the finished result without searching again. `best.json` stays until the
lock is written from it or the explore starts over. `[explore]
checkpoint_max_variants` bounds the lines.

**The curve and the stopping rules.** Each finished variant is a point
`{i, seed, t, score, best}` (`i` the order it finished in, plain placement 0;
`t` seconds since the explore began, over every session of a resumed one;
`best` true when it beat all before it). The report (`metrics.explore`, the
record in `.placemat/views/explore/`, the channel's `variant` events) keeps
`curve`, `found` (`{i, seed, t, score, of_variants, of_seconds}`, the last
improvement: the time-to-best) and `ended` (`{rule: "budget" | "stall_count" |
"stall_time" | "hard_clear" | "signal", ...}`). The console says `best found at
variant 7 of 34, 5 min 12 s in (of 43 min)` and, when a rule ended it, `ended
by a stall: 20 variants without improvement`. `[explore] stall_variants`,
`stall_seconds` and `stop_hard_clear` end an explore early (all off; the
workers finish the variant in hand); an explore so ended is complete, so
`--accept` applies. Hard terms: parts unplaced and critical-by-default findings
the plan measures (`fixed`, `copper`, `escape_walled`); the rule fires only when
the plain placement had some and a variant has none. Measured on four small
modules (one or two focused items), the last improvement came at variant 8, 8,
35 and never in 150: a count of 40 would have kept every best and ended after
about a third of those variants, but no large board was measured, so the
defaults stay off.

For a long explore run it detached (`setsid nohup placemat run ... >
explore.log 2>&1 &`) and do not chain it with `;`, which hides its exit
status.

**The lock.** `--accept` writes the best variant's decisions for the
focused items to `<script stem>.lock.json` beside the script, and the run
uses them. Each entry places its item off the placed pad it depends on
most, in that pad's part's frame (it follows the part when it moves or
turns), keeps its turn among the locked items, and carries a digest of the
item's declaration. Every later run applies the lock: `held by lock` when
the spot is legal, `lock: drifted N mm` when something now blocks it (the
nearest legal spot round it), `lock: released - why` when the declaration
changed or the anchor is gone, turned over or placed later. A cell's
entry also holds the arrangement it stood in (`"arrangement"`, left out of
the file for the default), and the cell is laid in it. Its digest then
covers that arrangement's member places, so an entry whose arrangement
now stands its members elsewhere is released as a changed declaration;
one whose arrangement the module no longer offers is released (`lock:
released - the module no longer offers arrangement <id>`) with an
`arrangement.missing` warning (`source: "lock"`). The cleanup
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
<score> mm, frozen <date>`). A cell whose entry holds an arrangement also
gains `arrangements="<id>"`, and its `why=` gains `; arrangement <id>`; a
cell locked in its default that offers arrangements gains
`arrangements="default"`, so the frozen call does not search them again.
`--fixed` writes a firm
`Location(X(...), Y(...))` instead, allowed when the anchor is fixed. Only
that call's arguments change - comments and every other line stay - and the
script and lock are written only when the edited script places every item
exactly as the lock did; otherwise freeze says what would have moved (an
entry that drifted is refused: accept it again where it now stands). A call inside a loop or a helper function
declares more than one item and is refused with its line.

## Studio builder

The studio's Build mode writes a layout script from clicks, as structured edits to the script and its facts, and never a
coordinate. It is for a board with a `.zen` and no layout script yet, and, afterwards, for a script that exists. A user can be pointed at
it: `placemat studio` with no script lists the project's layout scripts and, as a second group, "Boards with no layout" (each `.zen`
declaring a `Board`, `Project` or `Layout` with no `<Board>_layout.py` beside it and no listed script laid out for it). There is no command for
it: the flow is in the page.

1. **The board.** The page generates it (`pcb layout`, as a first `placemat run`; a cached generation is used where its inputs are
   unchanged) and reads it in a process of its own (`builder_worker`), with progress as `build` events. A failure shows the generator's log tail.
2. **Facts.** One form per fact, each written to its home: layer roles and copper weights and the pair net classes in the `.zen`
   (`Board(config=BoardConfig(stackup=Stackup(layers=[...])))`, `design_rules.netclasses`; minimal splices, a `load("@stdlib/board_config.zen", ...)`
   made or widened), via types and fab minimums in `fab-profile.json`, the rise in `placemat.toml` `[check] rise_c`. A weight is entered as oz or
   as a thickness and stored as a thickness in mm with the oz as a comment (1 oz/ft2 = 0.035 mm). `fab-profile.json` goes to the project root
   when there is none; a profile found above the board is left alone and a changed value writes a full copy beside the board; one beside the
   board is edited in place. A batch is one apply to the three files, then a regeneration and a read-back: a fact the generator did not take is
   reported. A row is decided, undecided (a default nobody wrote down), flagged (a plane mismatch: acknowledge it, or change the role) or
   changed (a fact edit after the confirmation). The confirmation is `facts.confirmed_text`'s, keyed to the script's path, so it needs the script.
   Placement and "Search the rest" wait for it. A `.zen` that `ast` cannot read, or declares its config through a name, is read only.
3. **The outline.** Rectangle (corners cut or rounded), circle (with a bore), slot, polygon (templates or a vertex list), holes. A size is a
   named constant with a comment saying where it came from: suggested from the parts' courtyard area (`area / (faces * fill)`, then the width
   from `[studio] builder_aspect`, rounded up to `builder_grid_mm`) or chosen in the builder. A typed size shows the fill it gives. A polygon's
   vertices are the one list of positions the builder writes: the board's own shape, a named constant. A hole on an edge is in its middle and
   needs a web (the engine refuses one that touches the outline). The script is created in one write (`create_file`, undoable: undo removes it).
4. **Placing.** Select what to place (the list, the tray of unplaced items, the board), say what a click picks (edge, part, pad, none), and
   choose among the relations the server offers. Each offer is a suggestion without a finding (id `b1`, ...): `POST /build/offer` returns it,
   `/suggest/show`, `/suggest/try` and `/suggest/apply` take it. Offers: on an edge (anywhere, start, middle, end; on a shaped board
   by `board.edge(facing=)`, bound once, `outermost=True` where several stretches face one way and one lies furthest out), on a disc's rim or
   bore, beside a part (a side, flush to an end), beside by a pad (its side, level with it), close to a pad (`board.link(...,
   weight=LinkWeight.SHORT)` and a bare `place`), near a pad (where no net joins them), in line with a pad (`Centre(X(pad), None)`), a row
   or ring of several, searched from its links. Modifiers: a quarter turn, a pad facing an edge, turned with another part, face, priority
   (with its reason), required, why. A gap (and a link's limit, a `Near`'s radius) is a typed number: a named constant
   (`C1_GAP_MM`) whose comment carries the user's reason. The suggested turn counts the ratsnest crossings of the four turns of a placed part
   (an estimate; Try is exact). Decided statements go in the decided part of the script in the order made (a move up or down reorders
   them); a bare `place` goes in the searched block under `# Searched from their links.`; changing a searched item to decided (or back) moves its
   statement. A hand-written script gets a statement after the one it names, in its own spelling of parts.
5. **Editing.** The parts list reads each placement back as a relation (`script_edit.read_intent`). A declaration it cannot read (a loop, a
   helper, a `Location`, a numeric `Centre`) is `by hand`: shown as written, and only replaced by a relation. Changing the outline's shape
   lists the placements it invalidates (an edge on a disc, a rim on a rectangle) and needs a choice for each.
6. **Undo and redo.** Every write is an entry of `.placemat/applied.jsonl` with source `builder`; the page's Undo and Redo are
   `/suggest/undo` and `/suggest/redo`.

Endpoints (the token as for the others; the body is a JSON record, never source; a refusal is `{"error": sentence, "rule"?}` with 404, 409,
422 or, while the facts are not confirmed, 423): `GET /build/state`, `/build/facts`, `/build/parts`; `POST /build/start`
`{id | current}`, `/build/reload`, `/build/close`, `/build/facts/apply` `{request}`, `/build/facts/confirm` `{acks}`, `/build/outline/suggest`,
`/build/outline/create` `{spec, description}`, `/build/offer` `{resolve, subject, target, params | kind: search|remove|move|row|item|outline}`,
`/build/turns`, `/build/turn`. Settings: `[studio] builder_grid_mm` (0.5), `builder_max_fill` (0.5; the one measured board is filled 0.33
per face), `builder_aspect` (1.0); none is part of a run's id.

## Studio notes

```
placemat studio note "<text>" [--at X,Y | --item NAME | --pad REF.N] [--from NAME] [--script PATH]
```

A note is a short remark left where the user is looking at the studio: "trying c_cpu further west". The command appends one record to
`<board>/.placemat/views/studio/notes.jsonl` and returns; any studio watching that script reads the file as it changes (so a note
reaches an open page within `[studio] poll_ms`, and a studio or page started later is given the ones that have not expired).
`--script` names the layout script; without it the one under the current folder, else the project's only one.

A record is `{"v": 1, "id", "at" (epoch s), "from", "script" (the script's file name), "description", "target"}` with `target` null or
`{"kind": "point", "x", "y"}` (mm on the board: a place to look at, never a placement), `{"kind": "item", "name"}` or
`{"kind": "pad", "ref", "pad"}`. `from` is `--from`, else `$PLACEMAT_FROM`, else the login name. The description is one line of at most
1000 characters. The file is bounded to the last `[studio] notes_keep` records.

The page draws each note as a pin at its target (an item or a pad is found in the plan every time, so the pin follows it when it
moves), a line in the Notes list (who, how long ago, where; it opens when there is a note, and a tap on the line or the pin goes to the
place), and a toast when one arrives. Dismiss hides a note in that browser only; a note is hidden after `[studio] note_age_s` seconds
(0 keeps it). Nothing here changes the layout: a note is read by the user, and the script stays the only way a position is set.

## The pin map study

For each part whose capture gives it a `Pm.PinPool` (capture.md, "Pin pools"),
placemat measures how much a better assignment of its movable nets to its pool
pins would save, at its present rotation and at each turn in `pins.rotations`
(and on the other face with `pins.faces`, where its declaration allows
`Face.EITHER`). It runs once at the end of every run and preview, on the
finished board, never inside the placement search, and writes nothing.
A part or cell standing off the axes (at 45 degrees, say) is studied in its own
frame: its body is its courtyard (or envelope) as turned, its pins face that
body's sides, and the turns are from where it stands.

**The score.** Built on placemat's ratsnest. The nets come from the pads alone:
a laid board's tracks, vias and pours are ignored, so a routed net keeps its
airwire and a first preview and a laid board are scored alike. A pin's airwire
leaves along its outward normal to a point `pins.exit_mm` past the courtyard's
box, then goes the shorter way round the box to its target; a net of several
pads is scored on its minimum spanning tree; a net through a two-pad series
part (a reference whose leading letters are one of `pins.follow_prefixes`, any case) is followed
to the far net (`pins.follow_series`). A crossing counts 1, `pins.pair_weight`
for a differential pair's airwire, `pins.impedance_weight` for a net whose
class names a KiCad tuning profile, `score.crossing_plane` for a plane's or a
free net's. The total is the weighted crossings against every other airwire and
among the studied nets, plus `pins.length_weight` times the airwire length in
mm, plus `pins.bend_weight` times the summed bend in degrees (the angle between
a pin's outward normal and the bearing to its target), plus the soft groups'
cohesion. A studied net whose class (or, for a net followed through a series
part, its far net's class) names a tuning profile counts its length
`pins.impedance_weight` times over, a differential pair's half too, whether its
pin may move or not: a turn that lengthens an RF net from a fixed pin or a cell
member weighs that. The cohesion is `pins.group_weight` times each soft group's spread: the mm its
neighbouring nets, in the group's written order, stand apart beyond the part's
pin pitch (the least distance between two of its pads) times the slots between
them. An intact group costs 0, reversed or not; a split across a corner or
across pins outside the pool costs the extra distance between the pads.

**Groups.** A `Pm.PinGroup` is soft unless its name ends in `!` (capture.md,
"Pin pools"). A soft group's nets move one by one and pay the cohesion; a hard
group moves as one block, in order, to a run of consecutive entries of the
pool as listed, or stays where it stands. A name ending in `!!` is a
`setup.pins` warning (`bad_marker`), as is a second group of one name
(`same_name`), and the study runs without that group.

**The search.** Per pose, a first map by minimum-cost matching (each group of
`Pm.PinGroup`, hard or soft, starting whole on the run of pins nearest its
targets), then `pins.seeds` local searches of `pins.anneal_moves` moves, swaps
and whole-group moves under annealing. The score and
the search run in the native module when it is in use, else in its Python
twin, which gives the same maps (`setup.native` says when it is not). Parts
whose movable nets meet are studied together, their poses in combination, at
most `pins.joint_combinations`. Seeds are fixed, so a board gives the same map twice. A study stops at `pins.budget_steps` a part
with the best found; the finding's facts say so (`budget_out`, with `searched`
of `of` poses and `steps` of `budget_steps`). A step is one move of a local
search, tried whether or not it is taken. The budget is a count, never a time,
so a board gives the same map on any machine, at any load, on either core; the
Python fallback takes longer to get there. A wall-clock guard,
`pins.guard_ms` a part (10000 ms, 0 is off; scaled with the budget for
`--search`), stops a runaway study: past it the study gives no map, and a
`setup.pins` warning with code `study_slow` (facts `refs`, `guard_ms`, `steps`,
`budget_steps`) says so, and the group gives no `no_legal_map` problem. A study
that tripped the guard is not kept for reuse, so a kept result is always
complete and the guard is not part of its digest.
What a study reads is digested and kept in
`.placemat/pinmap/<script>.json`; a run or a preview of an unchanged board
reuses it. A study that raises leaves the run standing: the error is on
`metrics.pin_study` and a `setup.pins` warning with code `study_failed` (facts
`type`, `message`) says so, and the run has no pin map findings.

**A part in a cell.** A studied part that is a member of a cell (a stamped
module instance) is studied as the cell: each pose turns the whole cell about
its centre, every member's pads with it, and the body its airwires go round is
the cell's envelope (its members' courtyards and its own copper), not the
part's courtyard. The turn is theoretical: the cell stays where it is and
nothing is checked for collisions or DRC; only the airwires are scored. The
part's pins leave by the envelope side their own courtyard side faces; the other
members' pads leave by the side they are nearest; a net with every pad inside
the cell and none that may move turns with the cell and is not studied. A pool
net whose other end is a series member of the cell (a reference with a prefix
of `pins.follow_prefixes`, two pads) is followed to that member's far net
outside the cell; any other pool net whose other ends are all members of the
cell keeps its pin (`held`, `why` `in_cell`; listed in `in_cell` as `{net,
ref}`): the module's own run places it. A cell is studied on the face it
stands on (`pins.faces` does not flip it). A turn is taken one of two ways: the
cell turned on the board to `cell_rotation_deg` (each stamp turns on its own),
or the cell kept and its module re-laid with the part at `module_rotation_deg`
in the module's frame, the cell's other parts placed round it, which re-lays
every stamp of the module; either one means the next run re-places the board.
For a cell standing in an arrangement other than the module's own layout
(`arrangement`), the rotation is in that arrangement's frame and the text says
so. The map is a change to the module's capture, which every stamp of the
module shares; when the stamps' best maps or their best `module_rotation_deg`
differ, each stamp's finding says so and lists them (`stamp_maps`). The
module's name comes from the generator's `layout.log` beside the board (the
folder of the module's layout path); without one it is null, and the stamps are
the cells whose members match. A cell with a member not placed is studied with
the members it has; the missing member is listed in `unplaced_ends`. A group
whose first part is loose and another in a cell carries that part's cell
facts.

**Parts not placed yet.** A studied net whose far end is on a part not placed
has nothing to pull it: it keeps its pin (`held`, `why` `unplaced`) and is
listed in `unplaced_ends`, as is a pad not placed on the far net a series part
takes a studied net on to (with `via` and `far`). When fewer than
`pins.placed_share_min` of a group's movable nets have a placed far end, the study gives no map or turn: the
`pins.remap` notice says how many ends are missing and that the study waits on
placement (`withheld`), with no suggestion.

**The record.** `run.json`'s `metrics.pin_study` is `{seconds, reused, groups,
parts}`, or `{error: {type, message}}` when the study raised. `reused` is true
when the last study's findings were kept, and `groups` is then null. Run and
preview print it as `pins  3 parts in 2 groups (0.41 s)`, `pins  3 parts, the
last study reused (0.02 s)` or `pins  the study failed with <type>: <message>`.

**`setup.pins`.** A warning, facts `ref`, `key`, `entry`, `code`, `name`
(and `held_net`, `held_pin`), by `code`:

| `code` | meaning |
|---|---|
| `no_pin`, `no_names` | an entry names a pin the part does not have, or names it by name where no pin names were read; the study runs without the entry |
| `no_net` | an entry names a net no pin of the part carries; the study runs without the entry |
| `unreadable` | a `Pm.PinAllow`, `Pm.PinDeny` or `Pm.PinGroup` entry is not `name:pins` |
| `not_in_pool`, `two_groups` | a group's pin is outside the pool or fixed, or already in an earlier group; the study runs without the group |
| `bad_marker` | a group's name ends in more than one `!` (`name` is the marker); the study runs without the group |
| `same_name` | a group is named as an earlier one (`entry` is both entries, `name` the name); the study runs without the later |
| `no_legal_pin`, `no_legal_map` | the constraints leave a net no pin (`held_net` and `held_pin` name the net holding its only pin); the part is not studied |
| `present_breaks` | the net `name` stands on pin `pin`, against its own `rule` (`Pm.PinAllow` or `Pm.PinDeny`). Raised whether or not a remap is reported: the capture breaks its own rule |
| `study_failed` | the study raised; `type` and `message` |
| `study_slow` | the study of the part's group ran past `pins.guard_ms` and gives no map; `refs`, `guard_ms`, `steps` taken and `budget_steps` |

**The finding.** `pins.remap`, a notice, when the best pose saves at least
`pins.gain_min` of the present total. Its sentence names what each pose saves
against the present map in the plainest term the pose wins on: weighted
crossings, else mm of airwire, else degrees of turning; and what it gives up on
weighted crossings or airwire to win: "U1: a pin map with 8 fewer weighted
crossings exists at its present rotation; at 90 degrees, 11 fewer weighted
crossings and 3.2 mm more airwire". A soft group the best map leaves split, 0.05 mm or more, is named with its
spread ("group lcd ends split, 0.7 mm beyond its pin pitch"), and a map that
closes a soft group up says so ("group lcd brought together", or "nearer
together"). A study given no steps (a budget of 0, which only a direct call of
the core can give) says so instead. Facts: `ref`, `refs`, `at`, `present` (the present
map's score), `rotations` (the best map at each pose, the present pose first:
`total`, `against`, `among` as crossing counts, `weighted`, `length_mm`,
`bend_deg`, `impedance_length_mm` (the controlled impedances' share of the
length), `spread_mm` and its term `cohesion`, `groups` (each
`Pm.PinGroup` where it lands: `name`, `ref`, `hard`, `spread_mm`, `cost`,
`nets` and `pins` in pin number order), `turns` with `ref`, `turn_deg`, `rotation_deg`, `face` and `flip`,
`map` as `ref`, `net`, `from` and `to` each `{pin, name}`, `routed`, `paths`
and `breaks`), `best` (the index of the best pose), `routed` (the best pose's
moved nets with copper on the board now: a remap means routing them again),
`before` (the airwires now), `present_groups` (the groups as they stand),
`held` (nets a constraint keeps, with `why` set to
`fixed`, `allow`, `unplaced` or `in_cell`), `unplaced_ends` (each studied
net's pad on a part not placed, as `{net, ref}`, with `via` and `far` when it is
on a series part's far net, and net `""` for a cell member not placed that
carries none), `in_cell` (`{net, ref}`), `present_breaks`, `searched`, `of`,
`budget_out`, `first_map` (false when the budget had no step for a first map),
`steps` (the steps taken) and `budget_steps`. A part in a cell adds `cell`, `module` (null when the board
does not name it), `stamps` and `arrangement`, and the best pose's
`cell_rotation_deg` and `module_rotation_deg`; each of its `turns` carries the
same six, and `stamp_maps` (`cell`, `ref`, `moves` as `{from, to}` pin
numbers, `module_rotation_deg`, by cell) when its module's stamps have
different best maps or module rotations. A study withheld for want
of placed ends has `withheld` (`placed`, `of`, `share_min`), `present` null and
no `rotations`.

**The suggestion** is advice (`how: "advice"`, lever `pins`, no edit): the best
map with the turn to declare when another pose wins (for a part in a cell, both
ways to take it), and the best at the present pose. `placemat apply <id>` refuses it: make the map in the `.zen` and
the turn in the script. In the studio an advice suggestion has only Try, which
draws the airwires before (dashed) and after (solid) and lists the map; it
resolves and writes nothing. The finding's panel lists every pose in `rotations`,
a row each: the turn (a part in a cell by its cell's turn), weighted crossings,
length in mm, bends, total and the saving against the present map, with the
best and the present pose marked. A row clicked draws that pose's airwires and
lists its map as Try does; a second click, a Try, or a change of selection or
run takes them away. In the studio's explore view each studied variant shows
its groups' weighted crossings now and after remapping beside its score, `slow`
for a group past its guard and `error` for a study that raised; on the variant
shown, Map draws a group's airwires and lists its map. Each group of an
explore's `pin_maps` carries `before` and `paths`, its airwires under the
present map and the best, as a finding's `before` and a rotation's `paths` do.

`placemat apply <id> --search` on a pins suggestion studies its parts again, on
the board as the last run placed it, with `pins.probe_budget_steps` a part. A
better map is kept as `<id>.1`, as advice, and `--json` gives `{id, study,
found}`. When the study raises, the command exits 1 with the error (`--json`:
`error` `{type, message}`, `study` and `found` null). When the parts are no
longer studied on the board, it exits 1, and `--json` carries `reason:
"not_studied"`. When the study runs past its wall-clock guard (`pins.guard_ms`
a part, scaled with the longer budget), it gives no map, says so with the steps
taken, exits 1 and keeps nothing; `--json` carries `reason: "slow"` and a
`study` of `{refs, slow, guard_ms, steps, budget_steps}`. In an explore's
report such a group's line says it ran past the guard, with no map.

## Findings and severities

A finding is one sentence saying what a resolve could not do as declared, with a `kind` (what sort of thing
it is, and what the score counts) and a `severity` (how much it matters to the board being built and routed):

| Severity | Means |
|---|---|
| `notice` | placemat did something by design that the user may want to know: a via shared or moved, an adopted route routed again |
| `warning` | a quality issue the board can live with, or one a person should judge: a link over its limit, a label on a part, a declared track not drawn |
| `critical` | the board cannot be built or fully routed as it is: an item unplaced, copper that conflicts, a pad walled in, a rule below the fab's minimum |

`run` and `preview` print each finding as `[severity] sentence`, the most serious first, and the line that counts
them says how many of each (`7 finding(s) (1 critical, 2 warning, 4 notice)`). `run.json` keeps `findings` (the
sentences) and `finding_details` (`kind`, `severity`, `text` per finding, in the same order); a record from before
severities has no `finding_details`, and its findings read as `warning`. `preview --format json` has the same
`finding_details`, and adds `reuse`, `png_failure` and a `data` record on each of `notes` (every value its `text` says, as fields), and the studio's plan JSON gives each of its `findings` a `severity` and has
`counts.severities`. The studio's Findings tab lists the most serious first.

A kind has one severity, listed below, except where the finding says its own at the place it is made. The
severity is a classification of what the finding means, kept in code (`findings.SEVERITY`), not a tunable and not
a scoring weight: `score.*` still weighs findings by kind, and a notice counts as much as any other finding of
its kind.

| Kind | Severity | Why |
|---|---|---|
| `unplaced` | critical | an item with no place is not on the board |
| `fixed` | critical | a decided item (fixed, a cutout, a keepout) is not legal where it was put |
| `copper` (conflicts: copper meets another net or a part's drilled hole, comes nearer a hole or the board edge than the copper-to-edge clearance (`copper.edge`), crosses a keepout, passes a corner inside the clearance, two tracks cross and neither may bridge) | critical | the copper as declared breaks a rule |
| `copper` (a declared track, via, pour or stitch not drawn) | warning | the copper the script declared is missing; a person decides whether the router can stand in |
| `copper` (a waypoint drawn pad to pad, stitch vias outside the region left out, the side a stitch row took) | notice | placemat's own choice, said |
| `escape_walled` | critical | a pad with no way out cannot be routed |
| `escape_closed` | warning | the way toward what a pad joins is closed; other ways out remain |
| `escape_crossed` | warning | two escapes cross near a pin row; the router can usually separate them |
| `escape_lane` | warning | a declared lane is blocked by another net's pad, hole or copper |
| `escape` (`escape.via_unneeded`) | warning | a module run only (a frame not drawn): a via on an escape lane, from `vias=` or a `board.via` on the lane's copper, whose lane reaches the frame's edge on its own layer without it; the lane can end there as a stub for the parent board's router, and the via takes room near the part. A plane or free net's via is not one. Facts: `ref`, `part`, `pin`, `net`, `layers`, `via` (`kind`: `lane` or `via`, `at`, `key`: the `board.via`'s copper key) |
| `escape` (`escape.pinched`) | warning | a pad's approach toward its nearest target, along its airwire out to `place.approach_reach`, has one way on the pad's layer (an SMD pad's face; a through-hole pad on every layer it is on), and it passes between copper of two other parts or nets (pads, planned tracks and vias; not the pad's own part, not the target's) closer than the net class's track width plus its clearance to each, by the board's clearance rules. One way: within `place.approach_detour` of the airwire, every other route is closed by copper or crosses another net's airwire on that layer, and widening that gap alone would open one. A wall with no such gap (a module's copper across the airwire) is no finding. The router needs a via pair past it, or room left there. Judged once on the finished board, not by the score. Facts: `net`, `pad` ([ref, number]), `toward` (the target's [ref, number]; ["", ""] for copper), `layer`, `neighbours` (two, each `kind`: `pad`, `track`, `via` or `lane`, `ref`, `cell`, `pin`, `net`, `lane`), `gap_mm`, `need_mm`, `track_mm`, `detour_mm`, `at` |
| `pair_crossed` | warning | a differential pair's halves cross |
| `link_over` | warning | a link longer than its limit |
| `label` | warning | a label with a part on it, or with no spot; a decided cell's label nearer the board edge than the silk clearance (`label.cell_edge`) |
| `label` (not drawn because its item found no place) | notice | the item's own `unplaced` finding is the fault |
| `split` | warning | a cell whose members form groups joined only by board-level nets |
| `keep_out` (`keep_out.cross_layer`) | notice | a `Pm.KeepOut` pair on different copper layers inside the distance with no plane between; KiCad judges clearance only on one layer, so `keep-out` does not fail it; facts: `net`, `distance_mm`, `limit_mm`, `layers`, `away` and `pads` (kind, owner, number, net, at) |
| `time` (`time.step_slow`) | notice | a step ran past `--step-warn` (or `--step-limit`, with no pass left to stop at); the placement is its own |
| `time` (`time.step_limit`) | critical when the item is left unplaced, warning when it kept the best spot found | a step gave up at `--step-limit`; the next run searches it again; for a cell, `arrangements` lists the ones it had not reached |
| `arrangement` (`arrangement.limit`, `arrangement.refused`, `arrangement.option_dead`, `arrangement.stale`) | warning | a module's alternatives over the limits, refused by the module's proof, an option refused in every combination, or ignored on the stamping board |
| `arrangement` (`arrangement.missing`) | critical; warning when `source` is `"lock"` | a cell's `arrangements=` names an id its module does not offer, and the cell is left unplaced; from the lock, an entry's arrangement is no longer offered, the entry is released and the cell is searched as its call says |
| `arrangement` (`arrangement.duplicate`, `arrangement.extent_fixed`) | notice | an arrangement dropped for laying out as another; a part that sets the module's extent and has no alternative |
| `facts` | warning | the board's facts differ from the last `placemat facts --confirm` |
| `fab` | critical | a net class's track, clearance or via is below the fab profile's minimum, so the fab would refuse it |
| `setup` (a web round a cutout under the minimum; a net class that does not fit the pads' pitch) | critical | the board cannot be milled, or the router cannot escape the pads |
| `setup` (an undeclared part, a lane reserved that no track uses, a part outside its frame's declared reach, an `accept` that matched no verdict, the native module not in use: `setup.native`, a `[route] pair_layers` entry that names no pair or a layer the board lacks: `setup.pair_layers`, a pin annotation the pin map study runs without or a present map that breaks its own rule: `setup.pins`) | warning | the script is incomplete or wrong |
| `setup` (a layer a keepout or rule names that the board lacks, a rule not carried to this board, a look-ahead dropped for want of room, an `accept` that was not needed, a search that spent its budget and took the best spot so far) | notice | placemat carried on without it |
| `setup` (`setup.net_halo`: a pad of another net inside a `[route] net_halos` halo whose own copper ends inside it, a key that names no net) | warning | the router cannot lead the pad out; the entry is not used |
| `route` (`route.dropped`) | notice | an adopted route dropped because a part it joins moved; the router routes it again |
| `route` (`route.width`: a net's copper delivered under the width asked) | critical when the net has a width in `[route] islands` (it carries current), or when the router's current for its narrowest copper is under the current the parts state for it (`Pm.I`); warning otherwise | the net is narrower than declared where it carries current; facts `net`, `stage`, `requested_mm`, `delivered_min_mm`, `length_under_mm`, `length_mm`, `share`, `declared`, `max_a`, `bottleneck_mm`, `stated_a` |
| `vias` (shared, moved, re-routed, left its pad, shortened, a field re-laid) | notice | carried vias gave way as designed |
| `vias` (a via dropped, or a field drawn with fewer vias than declared) | warning | fewer vias than were declared |
| `needs` | notice | an if-needed fab option would have cleared a spot; the item's `unplaced` finding is the fault |
| `pins` (`pins.remap`) | notice | the pin map study found an assignment of a part's nets to its pool pins that saves at least `pins.gain_min` of the present total, or it waits on placement (`pins.placed_share_min`); nothing is changed |
| `pins` (`pins.reversed`) | notice | two parts joined by `pins.reversed_min` or more lines (a net with only their two pads, or two such nets either side of a series part, as `pins.follow_series` follows them) where a run of lines next to each other along one part lands, on the other part or on the series parts on the way, in the reverse of their order, and mirroring that run on the part's pins leaves fewer crossings among the pair's straight airwires. Mirrored on the part whose `Pm.PinPool` holds the run's pins when that removes crossings. A part the pin map study gives a `pins.remap` for is left to that advice; where the study looked at the part and gave no map (a mirror that saves under `pins.gain_min` of the part's whole total), the sentence says so. Facts: `refs` (the part mirrored first), `mirror`, `mirror_also` (the other part when mirroring there is as good, else ""), `nets` (in the part's order and in the order they land), `pins`, `far` (each landing [ref, pad], in landing order), `crossings`, `crossings_mirrored`, `rules` (per part: `ref`, `pool`, `group`), `studied`, `at` |

`setup.native` (warning) is on every run, preview and explore where the native module is not in use, so the placement ran in pure Python:
the same results, 5-10x slower on a large board. Facts: `reason` (`version_mismatch`, `not_installed`, `import_error`),
`placemat_version`, `native_version` (null when none), `detail` (the import error). `PLACEMAT_NATIVE=0` is a deliberate switch and gives
no finding. The same record (`in_use`, `reason`, `placemat_version`, `native_version`, `detail`) is `native` in `run.json`, in the preview
JSON, in the channel's `hello` event and in the studio's hello.

A failed design check is a verdict, not a finding, and has its own severity in the checks output and in
`run.json`'s `verdicts`: `critical` for `keep-out` and `current-path`, `warning` for `crossings-under`, `heat`,
`exposure`, `hot-loop` and `switch-node`. A passing or accepted verdict has none.

### Suggestions

A finding is data: a `kind`, a `cause`, the `facts` its site measured and a `facts_v` naming the version of that cause's facts. Its sentence is rendered from the facts, in one place, so a record carries both and a reader that does not know a `facts_v` shows the sentence.

A finding may carry suggestions: changes to the layout script, worded in the board's own terms, that may clear it.
`run` and `preview` print the best one under each critical or warning finding and the ids of the rest:

```
[critical] j1: no legal location within 3.0 mm of (30.00, 30.00) (courtyard x41)
    try s2a: Place j1 beside r1, on its west side
    or s2b, s2c, s2d, s2e
```

`run.json`'s `finding_details[i]` and `preview --json` give a finding its `cause`, its `facts` (what the site measured; the sentence is
rendered from them) and its `suggestions`:

```
{"id": "s2a", "text": "Place j1 beside r1, on its west side", "rank": 1, "lever": "beside",
 "edit": {"op": "set_kwarg", "args": {"name": "at"},
          "target": {"kind": "place", "key": "j1", "file": "/abs/path/layout.py", "line": 12, "shared": 1, "digest": "..."},
          "value": {"form": "Beside", "args": [{"item": "r1"}, {"enum": "Edge.WEST"}]}},
 "digests": {"/abs/path/layout.py": "..."}}
```

`id` is `s<finding number><letter>` and belongs to the plan that made it. `rank` 1 is the best; `lever` groups variants
of one change (at most `[studio] suggestions_per_lever` of them). `edit` is data: the operation (`set_kwarg`,
`remove_kwarg`, `set_arg`, `edit_list`, `insert_statement`, `remove_statement`, `set_constant`, `toml_set`; and for
the studio's board builder `ensure_import`, `remove_constant`, `move_statement`, `create_file`, `confirm_facts`), the
declaration it changes by kind, key, file and line, and an intent expression for the value, never source and never a
coordinate. A number an edit writes is a named constant with a comment saying where it came from. A suggestion whose
declaration is made in a loop or a helper that runs for several items is not offered, since the edit would change
them all. `digests` is the digest of each file the edit writes, as the plan saw it.

`placemat apply <id> [--script PATH] [--dry-run] [--undo]` makes the edit. `--dry-run` prints the diff and writes
nothing. Without it the file is written (atomically, under the project root) and the apply is logged in
`.placemat/applied.jsonl`. If the script changed since the run that made the suggestion, nothing is written and the
command says so: run again for suggestions that fit. `--undo` puts back the last apply that has not been undone, if
the files are still as that apply left them. A suggestion is a candidate: the next run says whether the finding
cleared.

**Searched suggestions and the probe.** A suggestion's `how` is `"instant"` (its value is a number from a measurement, a name, an
enum or a relation: shown, tried, applied) or `"searched"`. A searched one is where a condition flips, so its edit has no value
and it has a `figure`:

```
{"name": "chamfer", "unit": "mm", "kind": "bisect", "edit": 0, "declared": 1.0, "far": 0.6, "lo": 0.6, "hi": 1.0,
 "direction": "lower clears", "of": "need_mm - near_mm", "times": 2, "resolution": 0.01, "what": "the chamfer of the A track",
 "const": "A_CHAMFER_MM", "finding": ["copper", "copper.corner", "A"], "severity": "critical"}
{"name": "bend", "kind": "set", "edit": 1, "enum": "Bend", "values": ["START", "END", "BOTH"], "what": "...", "finding": [...]}
```

`declared` is the value that does not clear (the finding says so); `far` is the end checked first, derived from a number the
finding records (`of`, `times`: here up to twice the shortfall), never from the board's extent, a pad's size or a factor. A lever
whose finding records no such number gets no searched suggestion. This release has the chamfer of a corner (`copper.corner`) and of
a cut that meets another net's copper (`copper.meets`), the arc radius of that cut, and `bend` (`copper.corner`). `edit` is the index
of the edit that takes the value (a bend's first edit is the `ensure_import` of `Bend`). Apply and Try refuse a searched suggestion;
it is worded as a question ("Changing ... might fix this: search options?").

`placemat apply <id> --search` runs the probe (`probe.py`). It prints what it will cost, and, where each candidate resolves the
whole board (every edit but a placement's), asks to go on unless `--yes` (without a terminal it refuses without `--yes`). The unedited
script is resolved once; then each candidate is the suggestion's edits with the value filled in, made as a dry run, and the script
resolved with those texts read in place of the files (as the studio's Try does), nothing written. A candidate is judged by the
finding cleared (`suggestions.cleared`) and the findings gained: it is acceptable when the finding cleared and nothing of a higher
severity than it was gained. Of the acceptable ones the best departs least from the declared value, ties by the run score; a set
is every member in order. A bisection checks `far` first (if it does not clear: "no value in the range clears it"), halves between
the last value that cleared and the last that did not until they are `resolution` apart, then reports the neighbour toward the
declared value; a figure that clears on both sides is reported as not monotone. At most `[studio] probe_candidates` (12) candidates and
`[studio] probe_budget_s` (120) seconds; one candidate is bounded by `try_timeout_s`. It ends with "found X", "no value in the range
clears it", "candidate limit reached"/"budget spent after n candidates: best so far X" or "stopped by you after n of m candidates:
best so far X" (Ctrl-C or SIGTERM; exit status 128 + the signal), each said at once. The best candidate is kept as an instant
suggestion `<id>.1`, in `.placemat/suggestions.json` beside the plan's own, so `placemat apply <id>.1` finds it; its value is a
named constant with a comment ("Found by a probe of the chamfer for copper.corner: 0.8 mm clears it; 0.81 mm does not."), and it is
applied the usual way, refused if the script changed since. Every candidate is appended to `.placemat/probes/<id>.<key>.jsonl` (the
key: the suggestion's edits, figure and the files' digests); a second `--search` of the same suggestion uses those results and
resolves no value again; a changed script or edit says so and starts fresh. `--json` prints `{"id", "result", "found"}`.

The probe reports on the live channel as the command's events: `probe` (the suggestion, the figure, the budget), `candidate` per resolve
(`value`, `cleared`, `gained`, `score`, `seconds`, `n`, `of`, `saved` for a result taken from the file) and `probe_done` (`state`:
`found`, `none`, `limit`, `budget`, `stopped`, `error`; `best`, `neighbour`, `monotone`, `candidates`). The candidates' own resolves
are not sent. The studio starts one with `POST /suggest/probe` `{"resolve", "id", "yes"}` (without `yes`, a probe that resolves the
whole board answers `{"state": "confirm", "estimate", "line"}` and starts nothing; `estimate` is `{board_wide, candidates, resolve_s,
budget_s, total_s}`, from the last run's resolve time) and stops it with `POST /suggest/probe/stop`; the command's summary has
`probe: {start, candidates, done}`. A found value is not in the plan: `GET /suggest/found?id=s3a.1` returns it (from the store `placemat apply`
reads, as a suggestion with `how: "instant"`), and `/suggest/show`, `/try` and `/apply` accept its id for a resolve whose plan holds `s3a`. The page's
"Search options" button posts `/suggest/probe`, asks to confirm with the estimate's `line` when it says so, draws each `candidate` on the figure's
range (a strip chart and a list: the value, cleared or not, findings gained, score, seconds, `saved`), offers Stop (`/suggest/probe/stop`), and when
`probe_done` arrives words the outcome from `state` and `best` and shows `s3a.1` with Show, Try and Apply. A stopped, budget-limited or
candidate-limited probe offers Continue, which posts again with `yes` and resumes from the saved results.

The same engine serves the board builder, which is not driven by findings. `suggestions.apply_edits(edits, digests,
dry_run, root=, log=, label=, source=)` is the body of `apply_suggestion`: the digest check (`""` for a file that
must not exist yet), the edits made together, the atomic write, one log entry carrying `label` as its text and
`source`. A file an edit creates (`create_file`, with the text `script_edit.skeleton(name, description, outline)`
gives) has `before: null` in its entry, and undoing it removes the file. `redo_last(log, root=)` makes the last undone
apply again when the files are as they were before it (`RedoRefused` otherwise); a new apply empties what could be
redone (`NothingToRedo`). `insert_statement` with no target takes `args={"after": {"region": R}}`, R one of `header`,
`constants`, `outline`, `decided`, `searched`, and an optional `args["bind"]` to write it as an assignment.
`ensure_import` takes `args={"names": [...]}`; `remove_constant` `args={"name": ...}` and refuses a constant
something reads; `move_statement` takes `args={"after" | "before": <target json>}`. `script_edit.read_intent(text,
target, name="at")` reads an argument back as the intent expression that writes it, `{"absent": true}` where the call
does not give it and None where it is not in the builder's vocabulary (a coordinate, arithmetic).

| Cause | Suggestions |
|---|---|
| `unplaced.search` | place it beside a part that pulls it, on a side measured free (up to `suggestions_per_lever`); before the parts that crowd it (`priority=`); on either face (`face=`); all four turns or any bearing (`rotations=`); into the keepout that refused it (`allow=`); without a label's reservation (`reserve=False`); judge parts by their courtyards (`place.envelope`); where the search spent its budget, a higher `budget=` for the item (searched) |
| `unplaced.pocket` | place it beside a part that pulls it; a `board.link` toward a part it shares a net with; either face |
| `unplaced.slide` | `at=OnEdge(...)` on each of the other edges |
| `unplaced.block` | the block may turn to any of its turns; the satellite that did not fit placed on its own (out of the block's list, a bare `board.place` after it) |
| `unplaced.bearing`, `unplaced.rides` | none |
| `fixed.part` | drop its `at=` so it is searched; the other face; a row's member taken out of the row and left to the search; a block's satellite placed on its own; an item at an intent `Centre` freed along one axis |
| `fixed.cutout` | for a web too thin: the board's `web=` lowered to the web it has, to the hundredth, as a named constant |
| `fixed.keepout` | none |
| `fixed.room`, `fixed.room_unsettled` | none |
| `copper.keepout` | `Net(...)` added to the keepout's `allow=`; the keepout kept off the layer the copper is on (`layers=`); the keepout forbidding only what the copper is not (`excludes=`) |
| `copper.cross` | `bridge=True` on the track that yields; `priority=Priority.HIGH` on it where the other track may bridge |
| `copper.meets` | the track's waypoints dropped (pad to pad, or from its lane to the pad for a track that begins with a lane); the other layer |
| `copper.edge` | for a track drawn pad to pad past a named cutout, a `Past` off the cutout as its one waypoint, on each side across the track's run, the side it lies toward first |
| `copper.not_drawn` | for an arc that did not fit, the radius that fits the leg (the radius times the leg's length over what its arcs take, a named constant saying so); for a track through an item, its waypoints dropped or the other layer |
| `copper.corner`, `copper.stitch` | none |
| `copper.note` | the waypoints dropped, for a waypoint that steers a track into a pad |
| `link_over` | place it beside the far part, on a free side; a heavier `weight=`; `priority=Priority.HIGH`; the limit raised to the measured length, as a named constant |
| `label.sits_on`, `label.no_spot` | the label on each of its other sides |
| `label.not_drawn`, `label.cell_edge` | none |
| `escape_walled`, `escape_closed` | a `board.fanout(part, sides=[...])` on the side the pad's way out points at; a `board.escape(...)` keeping the pin's lane clear |
| `escape_lane`, `escape_crossed`, `pair_crossed` | none |
| `setup.centre_flag_default` | the keyword removed |
| `setup.frame_reach` | the fit frame's declared width or height made the size that holds the item (not where the item reaches the origin side) |
| `setup.web` | the board's `web=` lowered to the web it has |
| `setup.step_budget` | a higher `budget=` for the item (searched) |
| `setup.native` | none: rebuild or reinstall the native module (`uv pip install -e ".[native]"`); results are right, only slower |
| `setup.undeclared` | a `board.place(Part(...))` for the part, after the script's last placement |
| `setup.lane_unused` | the pin taken out of the `board.escape(...)` |
| `escape.via_unneeded` | the pin taken out of the escape's `vias=`; or, for a `board.via`, the call removed (not offered where the via is assigned to a name) |
| `setup.accept` | the `board.accept(...)` removed |
| `vias.dropped` | none |
| `pins.remap` | advice, not an edit (`how: "advice"`, lever `pins`): the best map with the turn to declare when another pose wins, then the best map at the present pose when that saves anything; `advice` carries `refs`, `rotation` (the index into the finding's `rotations`), `turns`, `map`, `total` and `weighted` |

A suggestion's number is a figure the finding measured, or one derived from such a figure and said so in the constant's
comment; a lever with no measurement behind it (a wider radius, a finer step) is not offered.

A setting is written into the script's own `[scripts."<path>".<section>]` table of the nearest `placemat.toml`,
changing only that line.


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
| `run` | the run: `run.json`, `script.log`, a copy of the board, renders, `drc.json`, `impact.txt`, `reuse.json` (what the next run replays; `reuse.partial.jsonl` while resolving, left by a run that died), `run.json` with `status` `ok`, `failed`, `stopped`, or `running` with its `pid` while it works | `.placemat/runs/<id>/` |
| `run` (a module with alternatives) | `arrangements/<id>/` with `layout.kicad_pcb`, `drc.json`, `reuse.json` (and `reuse.partial.jsonl` while it runs) for each arrangement, and a render of each proven one with `--render` | the run's folder |
| `run` | `latest.json` (the last run of any board), `latest-<board>.json` (the last of each board: what a run compares with and reuses), `best.json`, and with `--label` an alias | `.placemat/runs/` |
| `preview` | `preview.svg`, `preview.png`, and `reuse.json` (what the next preview replays; `reuse.partial.jsonl` while resolving, left by a preview that was stopped) | `.placemat/views/preview/`, or `--out DIR` |
| `studio` | `reuse.json` (what the next resolve replays) and `worker.log` | `.placemat/views/studio/` |
| `run` / `preview` with `--explore --accept`, `lock --current`, `route --adopt` | the lock: accepted decisions | `<script stem>.lock.json` beside the script |
| `freeze` | the script's frozen `place()` calls, and the lock less those entries | the script, and its lock |
| `route --adopt` / `routes --release` | the kept routes | `<script stem>.routes.json` beside the script |
| `route` | the input and routed boards, the router's log, `route.json` | `.placemat/route/`, or `--out DIR` |
| `show` | the item's renders | `.placemat/views/show/`, or `--out DIR` |
| `layer` | the layer's SVG | `.placemat/views/layer/`, or `--out FILE` |
| `datasheet --show --png` | the page's render | `.placemat/views/datasheet/` in the PDF's project, or `--out FILE.png` |
| `faces` | the declared sides, into the fragment | the fragment named |

A module with alternatives gains `arrangements` in `run.json`, one entry per arrangement (see "Arrangements" under Placement).
A board's `placements` entry for a cell gains `arrangement` when the
cell stands in one other than the default.

`.placemat/` sits in the board's directory. `.placemat/views/` holds what a rerun
regenerates (the `preview`, `show`, `layer` and `datasheet` images); it has a
`.gitignore` of `*`, written when placemat first writes there, so a project
never tracks it. The other commands only read; `datasheet` and `drc` write
nothing unless asked.

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

placemat.toml is tuning only: it holds no fact about the board. A board fact
belongs in the .zen or fab-profile.json; placemat.toml refuses one that
strays in, naming where it moved.

```
built-in default  <  placemat.toml (nearest wins per key)  <  CLI flag
```

An unknown section or key, a wrong type or a value outside its range is an
error naming the file and the key. A setting that quietly did nothing would
read as though it were in force.

The resolved settings are part of a run's id, so changing one gives a new run
rather than replacing the last one.

`placemat settings [<script-or-dir>] [--json]` prints every resolved value and
the file it came from; given a script, it shows that script's overrides too.
`placemat settings --example [--output FILE]` writes a complete `placemat.toml`:
every section and setting with its default, unit and meaning, as valid TOML
that loads to the defaults (keep only the lines you change). The table below
is generated from the settings' own data (`placemat settings --markdown`
prints it; a test checks it). A setting renamed to say what it is still loads
under its old name for one release, with a `setup` notice naming the new one.

### Per-script settings

A project that keeps one `placemat.toml` for a board and its module scripts
sets a value for one script in a `scripts` table keyed by the script's path
relative to the file, the way `[facts.boards]` is, then the section:

```toml
[solve]
enabled = false

[scripts."modules/m/M_layout.py".solve]
enabled = true
```

Sections and keys are the base ones, checked the same way: an unknown key, a
wrong type, a path naming no script beside the file, or a `[facts]` section is
an error naming the file and the table, whichever script is running. The
override is applied over the base for that script only, after every file's base
values and before a CLI flag; `placemat settings <script>` gives its source as
`<file> [scripts."<path>"]`. The resolved settings include it, so the run id
and the reuse digest differ from another script's.

```toml
# electronics/placemat.toml
[place]
step = 0.1              # this board is laid out on a 0.1 grid

[drc]
real_kinds = ["clearance", "shorting_items", "hole_clearance"]
```

<!-- settings-table:begin -->
| key | default | unit | what it governs |
|---|---|---|---|
| `rank.area_weight` | `0.7` | weight | weight on courtyard area when ordering searched items |
| `rank.pins_weight` | `0.3` | weight | weight on pin count when ordering searched items |
| `place.radius` | `3.0` | mm | a search's default radius |
| `place.step` | `0.2` | mm | a search's default step |
| `place.envelope` | `"courtyard"` | choice | what a part claims against another: `courtyard` (its courtyard and pads), `physical` (its pads, mask openings, silk and body, each at the board's own gap), or `union` (both) One of: courtyard, physical, union. |
| `place.rotations` | `"all"` | choice | a searched part with no `rotation=` or `rotations=`: `all` four rotations, or only its `declared` one. One of: all, declared. |
| `place.bearing_step` | `5.0` | degrees | degrees between the turns of `rotations=Turns.ANY` |
| `place.tangent_bin` | `10.0` | degrees | degrees of bearing a `Turns.TANGENT` search turns as one: a spot takes its bin's turn |
| `place.order` | `"freedoms"` | choice | which searched item of a tier goes next: `freedoms` (the one with fewer freedoms left, then the rank) or `room` (the one with the fewest legal spots left, counted from its declaration, then the rank) One of: freedoms, room. |
| `place.room_pitch` | `1.0` | mm | the pitch `place.order = "room"` counts an item's legal spots at: a line's length over it, a region's area over its square |
| `place.room_ratio` | `2.0` | factor | `place.order = "room"`: items whose spot counts differ by less than this factor count as level and go by rank |
| `place.lookahead` | `true` | bool | a `Pm.Emits` / `Pm.Limit` part is placed where its still-unplaced partner keeps a legal spot at the limit distance |
| `place.lookahead_step` | `1.0` | mm | the grid the partner's legal spots are found on for that (its own step if coarser) |
| `place.coarse_stride` | `4` | count | how many steps apart a scored scan's first pass walks |
| `place.coarse_min_radius_steps` | `12.0` | steps | a scored scan does a coarse pass first when its radius is at least this many steps; below it one fine pass is cheaper |
| `place.refine_spots` | `3` | count | how many of the best coarse spots get a fine pass: this many by score, and, where the part's riders refuse some spots, this many of those they take |
| `place.block_gap_step` | `0.05` | mm | how finely a block's tightest gap is searched |
| `place.block_gap_reach` | `2.0` | mm | how far a satellite may stand off its pin |
| `place.copper_room` | `true` | bool | whether placement keeps room for the copper the script declares: a track or via declared between parts is planned provisionally, and a part standing Beside another moves out of its way. False places as before |
| `place.drc_epsilon` | `false` | bool | whether placement judges a copper, hole and hole-to-hole gap as KiCad's DRC does, a gap short of its rule by no more than the board's DRC epsilon (`BoardGeometry.drc_epsilon`, 0.0005 mm on a fresh board) counting as clear, and takes the net-tie exclusion's epsilon from the board. False keeps the nanometre it judged with and the fixed 500 nm. Findings and checks always take the epsilon |
| `place.step_budget` | `20000000` | count | the most candidates one searched item's step may judge, over all its passes, both faces and the carried vias' giving way; a step that spends it takes the best spot found so far, or leaves the item unplaced and says how much of the search area it covered. Counted, not timed: the result does not depend on how busy the machine is. A `place(budget=)` replaces it |
| `place.arrangements` | `true` | bool | whether a stamped cell's module arrangements (alternative layouts a module run proved) are searched; false lays every cell's default only, and a module run lays out its default only |
| `place.arrangement_options_max` | `4` | count | the most options one item or unit of a module may have, its default included; a module that declares more is not partly accepted: its run lays out the default only and says so |
| `place.arrangements_max` | `16` | count | the most arrangements a module may have, the default included: every combination of its items' and units' options, less those `board.exclude` leaves out |
| `place.arrangement_note_chars` | `4000` | count | the characters one arrangement note text holds before it is split into numbered texts (a note rides on a User.Comments text of the fragment) |
| `place.extent_notice_mm` | `1.0` | mm | how far a part may stand past the next part on a side of a module that declares no alternatives before `arrangement.extent_fixed` notes it as setting the module's extent |
| `place.arrangement_margin` | `0.5` | mm | how much better than the module's default a cell's other arrangement must score before a search takes it; within it the default stands and the step says so. It applies at a decided spot too, where a firm cell's arrangements are each scored once. Not asked when the default has no legal spot, of a cell whose `arrangements=` names its choices, or of an explore's draw |
| `place.firm_passes` | `8` | count | the most passes over the firm items, each placed against the copper the last pass planned (and, where a Beside part was refused by a firm part placed before it, with the two taken in the other order), the last one the settled run |
| `place.copper_room_tolerance` | `0.001` | mm | how far a declared track or via may move between two passes and count as settled |
| `place.beside_step` | `0.01` | mm | the step a part placed Beside is moved out at, when something already placed is in its way, until the collision rule lets it stand, then bisected back to the first spot that stands |
| `place.beside_reach` | `2.0` | mm | how far past its standoff from the item a part placed Beside may be moved out to clear what is in its way; past it the part stays at the standoff and the collision is reported |
| `place.escape_depth` | `1.0` | mm | how far each corridor out of a pad runs in the search: it weighs a candidate that crosses, closes or walls off a pad's corridors (`score.escape_*`); the run score measures them at `score.escape_depth` |
| `place.escape_min_pads` | `1` | count | a part's pads keep escapes when it has at least this many (3 leaves two-pad parts out) |
| `place.escape_via_step` | `0.05` | mm | the step a `board.escape` lane's via is searched along its lane at, from the row's end, before it is bisected back to the nearest nanometre |
| `place.escape_via_reach` | `5.0` | mm | how far along its lane, or its axis, a `board.escape` via is searched before it has no legal spot |
| `place.courtyard_touch` | `0.0` | mm | how far two courtyards may overlap at least; each pair may also overlap by the two parts' margins (how far KiCad's courtyard polygon lies inside the drawn box) less 0.001 mm, which keeps KiCad's courtyards apart - it counts touching as overlapping |
| `place.silk_margin` | `0.001` | mm | how much further than the board's silk clearance a place placement chooses keeps one part's silk from another's silk and mask openings. KiCad compares silk at the clearance itself, with no DRC epsilon, on geometry rounded to the nanometre, so silk placed at exactly the clearance and then turned off the quarter turns (a stamped cell, a tangent turn) can come out a nanometre short. A place the script decided, and a rider's place in its group, are judged at the board's own clearance |
| `place.courtyard_polygon_share` | `0.98` | share | a courtyard whose polygon covers less of the box round it than this (a slice of a disc, an L, a rectangle turned off the axes) is claimed as KiCad draws it, with no margin; one that covers more is claimed as its box |
| `place.conflict_reach` | `1.0` | mm | how far outside a box a conflict can still reach; a floor under the largest clearance a rule asks |
| `place.fit_room` | `10.0` | mm | on a fit frame, how far round the decided content a searched item may go |
| `place.via_share_distance` | `1.0` | mm | how near a via of its net a carried via that meets another net's copper may be to share it instead; 0 never shares |
| `place.via_move_distance` | `0.5` | mm | how far such a via may move to clear it; 0 never moves |
| `place.via_move_step` | `0.05` | mm | the grid a via's move, or its leaving its pad, is searched on |
| `place.via_leave_distance` | `1.0` | mm | how far a via inside its pad, with no spot clear inside it, may leave it, joined by a new tail; 0 never leaves |
| `place.via_relay` | `true` | bool | whether a via field a conflict meets is re-laid in its pad, as a whole, before its vias leave the pad or are dropped; false leaves each via to its own steps |
| `place.via_route_distance` | `0.5` | mm | how far a via that two or more of a cell's tracks end on may move, its tracks rebuilt from their far ends; 0 leaves it as drawn |
| `place.via_search_chunk` | `64` | count | how many of the nearest offsets a via's move or leave search judges first; each later window is twice the last, and the search ends at the first window that holds a spot; a speed setting, results are the same |
| `place.via_clear_cache` | `4096` | count | how many placed routed vias' clear moves a scan keeps, each searched once for every candidate that meets it; a speed setting, results are the same |
| `place.drops_keep_share` | `0.5` | share | the share of a pad's drops (vias of a `plane()` net in it) the pad keeps, rounded up and never fewer than one: what `drops=Drops.MIN` keeps of each field, and what a pad keeps when a carried drop is dropped to clear another net's copper (1 drops none there) |
| `place.edge_step` | `0.05` | mm | the step a part on a curved board edge is stepped in from the edge at until the keep-in holds it, before it is bisected back |
| `place.pocket_step` | `0.5` | mm | the least raster a free-rectangle search blocks the board at; an item's own step is used when coarser |
| `place.freedom_min_step` | `0.2` | mm | the least step a part's one-freedom search (along an edge, round a ring) walks at; an item's own step is used when coarser |
| `place.cutout_step` | `0.2` | mm | the step a cutout is slid along a free axis at |
| `place.cutout_angle_step` | `0.5` | degrees | the step a cutout is turned round its centre at |
| `place.escape_lane_via_exit` | `false` | bool | whether a via that fits at the end of a pad's own copper (an escape lane or a stub drawn from it) counts as that pad's way out. Off: a pad on a lane needs a track to get on, on the layer the lane is on, and is walled off when only a via would; on: a via spot is enough, as for a pad with no lane, which keeps the via rule either way |
| `place.escape_cell` | `0.05` | mm | the grid a pad's path out is searched on |
| `place.approach_reach` | `8.0` | mm | how far along a pad's airwire toward its nearest target the `escape.pinched` check looks for a gap between two other parts' copper that the pad's track does not fit through |
| `place.approach_detour` | `2.0` | mm | how far to either side of that airwire a track may go round such a gap, on the pad's layer and crossing no other net's airwire, and still count as a way: a pinch with a way round within it is no `escape.pinched` finding |
| `place.split_min_group` | `2` | count | the least members a group needs to count as one, in a cell's `split` finding |
| `copper.chamfer` | `1.0` | mm | how far a right angle is cut back into two 45s |
| `copper.arc_radius_track_widths` | `3.0` | track widths | the radius of a track's arc corners (`bend=Bend.ARC`), as a multiple of the track's width; `radius=` on the call is in mm and takes precedence |
| `copper.pair_chamfer` | `0.5` | mm | the same, for a differential pair |
| `copper.pair_via_offset` | `0.4` | mm | how far clear of its partner a pair's lead vias |
| `copper.bridge_half_gap` | `1.1` | mm | half the gap a bridge leaves round a crossed track |
| `copper.finger_bridge_width` | `1.0` | mm | the width of a finger's bridge under a track |
| `copper.finger_min_piece` | `0.05` | mm | a finger's piece between two bridges no longer than this is not drawn |
| `copper.plane_inset` | `0.4` | mm | how far a plane is inset from the board edge |
| `copper.plane_clearance` | `0.2` | mm | a zone's pullback from foreign copper |
| `copper.plane_min_width` | `0.2` | mm | a zone's minimum filled width |
| `copper.pour_outline_width` | `0.2` | mm | a pour's outline stroke |
| `copper.pour_reach_step` | `0.05` | mm | the step `reach=Reach.CURRENT` grows a fitted pour by, so the reach is a multiple of it |
| `copper.pour_reach_max` | `5.0` | mm | the furthest `reach=Reach.CURRENT` grows a fitted pour; where the need is not met by then a finding says so |
| `copper.cell_zones_under_planes` | `"drop"` | choice | a stamped cell's zone the board's own plane covers on its net and layer: `drop` merges it into the plane, `keep` keeps it. One of: drop, keep. |
| `copper.tap_overlap` | `0.005` | mm | how far a tap's copper reaches over its pad's edge; copper that only meets the pad along a line may not read as joined |
| `copper.microvia_drill` | `0.1` | mm | a micro via's drill (`layers=` one layer from an outer face) when the script gives none |
| `copper.straight_tolerance` | `0.002` | mm | a track leg whose ends differ by less than this on one axis is drawn straight between them; `measure --copper` judges 0/45/90 by it too |
| `write.split_groups` | `"lift"` | choice | the generator's nested groups: `lift` each cell's group out of its module sheet's to the top level (the sheet keeps its own parts), `split` also takes out of a group the parts the script places by steps of their own, `keep` writes them as generated; a group left empty is removed. One of: lift, split, keep. |
| `write.keepout_drawings` | `"admitting"` | choice | draw a keepout's outline and name (and its height limit) on its Fab layer, or `User.Comments` for one on both faces or on inner layers only: `admitting` (default) those that admit something, `all` every keepout, `none`. One of: admitting, all, none. |
| `write.keepout_line_width` | `0.1` | mm | a drawn keepout's outline stroke |
| `write.keepout_text_height` | `0.8` | mm | a drawn keepout's label height |
| `label.text_height` | `1.0` | mm | silkscreen text height |
| `label.thickness` | `0.15` | mm | silkscreen stroke width |
| `label.gap` | `0.0` | mm | a label's gap from what it names; never less than the board's silk clearance |
| `label.slide_step` | `0.25` | mm | the step a label slides by along its item's side when a firm part is placed beside it |
| `geometry.arc_sag` | `0.02` | mm | how far a flattened arc may cut the corner off the real one |
| `geometry.index_cells` | `16` | count | buckets across the longer side of the spatial index |
| `geometry.arc_error_nm` | `5000` | nm | arc approximation error when reading pad outlines |
| `geometry.cap_steps` | `8` | count | segments round each half-circle end of a track's polygon, in Python and in native |
| `check.ambient_c` | `100.0` | deg C | board temperature the junction estimate starts from (`--ambient`) |
| `check.keep_out_mm` | `2.0` | mm | how far sense copper stays from a switch node (`--keep-out`) |
| `check.rise_c` | `10.0` | deg C | the rise a current path is sized for (`--rise`) |
| `check.neck_end_share` | `0.6` | share | the share of `check.rise_c` the copper at a short neck's two ends is taken to have used (Brooks and Adam's simulated trace ends sit at 57.9 C of a 94.7 C peak); the neck is credited as short when its own conduction rise stays inside the rest. 1 turns the credit off |
| `check.neck_resistivity` | `2.2e-08` | ohm m | copper's resistivity at the working temperature, ohm m (1.68e-8 at 20 C, 4.04e-3 per K, at 100 C) |
| `check.neck_conductivity` | `384.0` | W/(m K) | copper's thermal conductivity, W/(m K) |
| `check.zone_step` | `0.05` | mm | the cell a zone fill is rasterised at to measure its width along a load's route; the width reads within one step |
| `check.route_tries` | `4` | count | how many times the load's route between two carriers is searched, each search after the first avoiding the zone fill crossings the earlier ones measured narrow |
| `check.limits` | `{}` | table | a bound per check, e.g. `"hot-loop" = 20.0` (`--limit`) |
| `parts.order_fields` | `["Lcsc", "LCSC", "Mpn", "MPN"]` | list | a footprint field naming an order code (an LCSC number, an MPN); `parts` warns when a placed part (not `dnp`) has none of them present and non-empty |
| `drc.real_kinds` | `["clearance", "shorting_items", "track_width", "annular_width", "hole_clearance", "hole_to_hole", "courtyards_overlap", "copper_edge_clearance"]` | list | which violations mean the board is not done, whatever their severity: the `real` bucket (every other kind KiCad reports as an error counts there too, except footprint issues and outstanding) |
| `drc.outstanding_kinds` | `["via_dangling", "track_dangling", "isolated_copper"]` | list | which violations are copper not yet joined: `outstanding` |
| `drc.footprint_kinds` | `["lib_footprint_issues", "lib_footprint_mismatch", "malformed_courtyard", "padstack"]` | list | which violations are defects in the footprints themselves: `footprint issues` |
| `drc.refill_zones` | `true` | bool | refill zones for the check |
| `explore.spot_slack` | `0.25` | fraction | an explored item draws among spots scoring within this fraction of its best |
| `explore.swap_chance` | `0.2` | probability | the chance two focused items next in the placement order trade turns |
| `explore.rank_power` | `1.0` | exponent | an explored item's spot at rank r among its candidates is drawn with weight 1 / r to this power: higher keeps it nearer its best |
| `explore.congestion_step` | `0.05` | fraction | variants are ranked by the run score, with the worst congestion cell counted in steps of this at `score.congestion` each (0 leaves it out) |
| `explore.jobs` | `0` | count | worker processes for `--explore`; 0 is the CPU count less one |
| `explore.stall_variants` | `0` | count | end an explore after this many finished variants without an improvement; 0 is off |
| `explore.stall_seconds` | `0.0` | seconds | end an explore this many seconds after its last improvement; 0 is off |
| `explore.stop_hard_clear` | `false` | bool | end an explore when a variant has none of the hard terms (unplaced parts, critical findings) the plain placement had |
| `explore.checkpoint_max_variants` | `100000` | count | finished variants an explore's checkpoint records; past it a resume tries those again |
| `pins.exit_mm` | `0.5` | mm | the pin map study: how far past its part's courtyard a pin's airwire leaves (its exit point) before it may turn |
| `pins.follow_series` | `true` | bool | the pin map study scores a net that reaches a pin through a two-pad series part (a termination resistor) on to the series part's far net, as one connection |
| `pins.pair_weight` | `5.0` | weight | the pin map study: what a crossing counts where either airwire is a differential pair's (any other counts 1) |
| `pins.impedance_weight` | `3.0` | weight | the pin map study: what a crossing counts where either airwire's net class names a tuning profile, a controlled impedance, and how many times over such a net's airwire length counts (a differential pair's half too) |
| `pins.length_weight` | `0.25` | weight | the pin map study: weighted crossings per mm of the studied nets' airwire (0.25: the run score's 4 mm a crossing) |
| `pins.bend_weight` | `0.005` | weight | the pin map study: weighted crossings per degree a studied net turns from its pin's outward normal toward its target |
| `pins.group_weight` | `4.0` | weight | the pin map study: weighted crossings per mm a soft `Pm.PinGroup`'s neighbouring nets stand apart beyond the part's pin pitch |
| `pins.follow_prefixes` | `["R", "L", "FB"]` | list | the pin map study follows a net on through a two-pad series part only when its reference's leading letters, in any case, equal one of these: a resistor, an inductor, a ferrite bead by default; RT1 is not followed for R, nor a two-pin connector |
| `pins.rotations` | `[0.0, 90.0, 180.0, 270.0]` | degrees | the turns from where a part stands that the pin map study tries besides its present one; add 45, 135, 225 and 315 for the diagonals |
| `pins.seeds` | `1` | count | local searches of the pin map study per pose, each with its own fixed random stream |
| `pins.anneal_moves` | `100` | count | moves each local search of the pin map study tries |
| `pins.anneal_start` | `1.0` | weight | the pin map study's annealing temperature at its first move, in weighted crossings: a move that costs this much is taken about one time in three (0: only moves that gain) |
| `pins.anneal_end` | `0.02` | weight | the pin map study's annealing temperature at its last move |
| `pins.budget_steps` | `3000` | steps | the pin map study's search for each studied part, in steps (one step is one move of a local search, tried whether or not it is taken): it stops there with the best map found and says so, so a board gives the same map at any speed |
| `pins.joint_combinations` | `64` | count | the most pose combinations the pin map study searches for parts it studies together, their present poses first |
| `pins.faces` | `false` | bool | the pin map study also turns a part on the other face where its declaration lets it stand there (`face=Face.EITHER`) |
| `pins.gain_min` | `0.05` | share | the share of the present total a better pin map must save for a `pins.remap` finding |
| `pins.reversed_min` | `3` | count | the fewest lines next to each other on a part whose airwires land, on the part they join or on the series parts on the way, in the reverse of their order, for a `pins.reversed` finding |
| `pins.placed_share_min` | `0.8` | share | the share of a studied group's movable nets that must have a placed far end for the pin map study to advise a map; below it the study says it waits on placement |
| `pins.explore_top` | `3` | count | the best variants of an explore, by run score, the pin map study runs on (0: none) |
| `pins.probe_budget_steps` | `150000` | steps | the pin map study's search for each part, in steps, when `placemat apply <id> --search` studies a `pins.remap` suggestion again |
| `pins.guard_ms` | `10000.0` | ms | a safety net on the pin map study's time for each studied part, scaled with its budget for a longer study: past it the study gives no map and says so in a `setup.pins` warning; 0 is off |
| `drc.severities` | `{}` | table | a table of KiCad rule names to `error`, `warning` or `ignore`, written into the board's .kicad_pro before DRC |
| `route.router_dir` | `""` | path | the KiCadRoutingTools checkout; empty: `$KRT_DIR`, else `~/work/KRT-upstream` |
| `route.quick` | `true` | bool | one routing round rather than the router's full run |
| `route.max_iterations` | `unset` | count | cap on the router's search per net; unset: the router's own default |
| `route.plane_share` | `0.9` | share | how much of the board's own outline a pour must cover to be guarded whole from other nets' tracks while routing (the router's default layers come from each layer's declared role, not this) |
| `route.turn_cost` | `20000` | cost | what the router charges a turn, per 90 degrees (a 45 half of it), against 1000 a straight grid step: the router's own default of 1000 makes a kink nearly free and its routes stair-step; 20000 measured best on a dense four-layer board (fewer than half the turns, 10% less copper, closure no worse); 1000 gives the router's own behaviour |
| `route.smoothing` | `true` | bool | the router's own octolinear smoothing, as it defaults; false skips it |
| `route.router_args` | `[]` | list | more of the router's own flags (`--direction-preference-cost`, `--heuristic-weight`, `--bus`, `--via-cost`, ...), each a string, appended to its route.py passes (the island nets, the class stages, the main pass); one placemat sets itself (`--nets`, `--layers`, `--escalation`, `--keep-input-copper`, `--turn-cost`, `--smoothing`, `--no-smoothing`, `--power-nets`, `--power-nets-widths`, `--max-iterations`, `--max-probe-iterations`, `--json-out`, `--net-clearances`) is refused |
| `route.pair_router_args` | `[]` | list | the same for the pair router (route_diff.py), which takes flags of its own (`--max-turn-angle`, `--min-turning-radius`, ...) and not all of route.py's |
| `route.pair_layers` | `{}` | table | the copper layers the pair router may route a differential pair on, for that pair only: a key is the pair's two nets `"P/N"` (either order) or a net class name, its value a list of layer names (`{"USB_D_P/USB_D_N" = ["In2.Cu", "B.Cu"]}`); a pair's own nets win over its class. Every other pair routes on the route's own layers. The pairs are routed in one call of the pair router per distinct list, the named ones first. A key that names no pair on the board, or a layer the board does not have, is a `setup.pair_layers` finding and the entry is not used |
| `route.net_halos` | `{}` | table | a net mapped to a halo in mm (`{"SW" = 2.0}`): every router pass keeps other nets' new copper that far from the net's copper, and the net's own new copper that far from everything, to keep coupling off a switch node. Each net is given the larger of its net class clearance and its halo in the clearance map placemat hands the router. Before the route, a pad of another net within the halo whose own copper (an escape, a via) ends inside it is a `setup.net_halo` finding: the router cannot leave it. A key that names no net on the board is a `setup.net_halo` finding and the entry is not used |
| `route.islands` | `[]` | list | nets with pours whose pads the pours do not reach (a pour net's small taps), `"NET"` or `"NET=WIDTH"` (mm): routed first and alone, joining only the pads and pieces the pours leave apart, at the netclass width or WIDTH; `placemat route --islands` adds to them |
| `route.diff_pair_gap` | `0.0` | mm | mm between a pair's tracks; 0 is the net class's diff pair gap (the router never goes below the class clearance) |
| `route.diff_pair_width` | `0.0` | mm | mm, a pair's track width; 0 is the net class's diff pair width |
| `route.adopt_tolerance` | `0.001` | mm | mm any kept pad may lie from where the parts' common motion puts it before the kept routes joining them are dropped |
| `run.max_time_s` | `0.0` | seconds | stop a `run` or `preview` after this many seconds of placing, at the next point it can be resumed from (its finished steps are kept and replayed by the rerun); 0 is no cap. `--max-time`. Wall-clock, so it depends on machine load |
| `run.step_warn_s` | `0.0` | seconds | a step still working after this many seconds sends a live event and gets a finding naming the item, its seconds and the pass it was in; 0 is never. `--step-warn` |
| `run.step_limit_s` | `0.0` | seconds | a step still working after this many seconds gives up: it is left unplaced, or at the best legal spot its scan had found, with a finding, and the resolve goes on with the next item; checked between a scan's passes; 0 is never. `--step-limit`. Wall-clock, so which steps give up depends on machine load, unlike a candidate budget; such a step is searched again by the next run |
| `timeout.generate` | `900` | seconds | seconds for `pcb layout` |
| `timeout.drc` | `600` | seconds | seconds for kicad-cli DRC |
| `timeout.route` | `3600` | seconds | seconds for the router |
| `timeout.render` | `300` | seconds | seconds for a render |
| `noise.patterns` | `[]` | list | extra KiCad stderr patterns to suppress, ADDED to the built-ins |
| `best.airwire_noise` | `0.01` | fraction | how far airwire may move, as a fraction, before a run counts as better or worse than its family's best: kicad-cli picks different ratsnest edges each run for a byte-identical board |
| `best.crossing_noise` | `0.02` | fraction | how far the crossings' term may move, as a fraction, before a score counts as better or worse: kicad-cli's ratsnest varies run to run |
| `score.unplaced` | `2000.0` | mm | mm a part left unplaced costs the run score, times its priority's multiplier |
| `score.unplaced_high` | `2.0` | multiplier | the unplaced multiplier for a part declared `priority=HIGH` |
| `score.unplaced_default` | `1.0` | multiplier | the unplaced multiplier for a part with no declared priority |
| `score.unplaced_low` | `0.5` | multiplier | the unplaced multiplier for a part declared `priority=LOW` |
| `score.drc` | `200.0` | mm | mm a real DRC violation costs |
| `score.link_over` | `20.0` | mm | mm per millimetre a link is past its limit, times the link's weight |
| `score.fixed` | `200.0` | mm | mm a decided item (fixed, a cutout, a keepout) not legal where it was put costs |
| `score.copper` | `200.0` | mm | mm planned copper that meets another net, crosses a keepout or cannot bridge costs |
| `score.label` | `50.0` | mm | mm a label with a part on it costs |
| `score.setup` | `0.0` | mm | mm a setup finding costs: the same every run of a script (an undeclared part, a layer the board lacks) |
| `score.crossing` | `4.0` | mm | mm a ratsnest crossing costs, in the run score and in the search |
| `score.crossing_plane` | `0.0` | share | a crossing with a plane's or free net's airwire, as a share of `score.crossing`: each of its pads drops to the plane by a via |
| `score.pair_crossing` | `100.0` | mm | mm a differential pair (a net class's own, board_pairs) crossing itself costs, in place of `score.crossing`: such a pair has to exchange sides to route coupled, so a swap of two identical parts or a turned part is worth wire |
| `score.escape_crossed` | `20.0` | mm | mm two escapes from one part's pins crossing near its pin row cost |
| `score.escape_depth` | `1.5` | mm | the corridor length the escape findings, and so the run score, are measured at, whatever `place.escape_depth` the search used, so runs at different search depths compare |
| `score.escape_closed` | `50.0` | mm | mm a pad whose last route toward what it connects to is closed costs |
| `score.escape_walled` | `400.0` | mm | mm a pad with no route out at all costs. A pad that copper of its own net already leaves with a way on (a track that reaches another pad of the net, a via in it, a pour over it) is not counted, closed or walled; a track or an escape's lane that ends in the air is the pad's way out only as far as it goes, and the pad is walled when no track or via gets on from where the copper ends. What walls a pad (pads on a layer the pad shares, a through-hole pad on every layer it spans, unplated holes, copper, and where a via is wanted the rule areas that forbid vias) is named by owner, "track NET", "via NET", "pour NET" or "the escape lane of U1 pin 53". A pad whose net has no other pad on the board (a pin the cell hands off to the board above it; not a no-connect net: `NC_...`, `unconnected-(...)`, or a net named under an instance, with a dot) is reported at the end of the run when no track or via gets out of it, from the end of its own net's copper on it (a stub, an escape's lane) where it has any: "no other pad is on the net, so it leaves the board here, and it is walled off by ...". Such a pin keeps no corridor in the placement search; `board.escape` names the pins whose routes out are to be kept |
| `score.escape_lane` | `400.0` | mm | mm a declared `board.escape` lane costs that another net's pad, hole or copper already placed blocks, or whose via has no legal spot: in the search at each candidate, and in the run score as the `escape_lane` finding |
| `score.congestion` | `10.0` | mm | explore: mm per `explore.congestion_step` of the worst RUDY cell |
| `score.via_share` | `1.0` | mm | mm the search adds to a spot for each carried via that shares a via of its net there |
| `score.via_move` | `2.0` | mm | mm for each carried via that moves there |
| `score.via_drop` | `10.0` | mm | mm for each plane drop dropped there |
| `score.back_face` | `2.0` | mm | mm the search adds to a spot on the back face of an item placed with `face=Face.EITHER`, so an equal spot is the front's; no item with a fixed face pays it |
| `score.arrangement` | `0.0` | mm | mm the search adds to a cell's non-default arrangement, so an equal score keeps the module's own layout; a project raises it to prefer the module's default by that much |
| `score.push` | `10.0` | mm | mm-equivalent: `score.push` times a push's modelled value over its limit, at the search |
| `score.via_leave` | `4.0` | mm | mm for each carried via that leaves its pad there, between move and shorten |
| `score.via_relay` | `3.0` | mm | mm for each via field re-laid there, once, between move and leave |
| `score.via_relay_moved` | `0.5` | mm | mm for each via a relay moves or adds |
| `score.via_relay_gap` | `1.0` | mm | mm for each empty site a relay leaves in the field's grid, beyond the drawn field's |
| `score.via_relay_pitch` | `4.0` | mm | mm for each mm the field's line spacings, summed, depart from the pitch it was drawn at |
| `score.via_route` | `3.0` | mm | mm for each routed via that moves with its tracks rebuilt there, between move and leave |
| `score.via_shorten` | `5.0` | mm | mm for each carried plane drop shortened to the plane's nearest layer instead of dropped, between move and drop |
| `solve.enabled` | `false` | bool | give the searched tier its hints from a global solve of the whole netlist, before any item is scanned |
| `solve.iterations` | `200` | count | the solve's conjugate-gradient cap per axis per round |
| `solve.tolerance` | `1e-06` | residual | the residual the solve stops at |
| `solve.rounds` | `8` | count | solve-then-spread rounds, the pull toward the spread rising by `solve.spread_growth` each round |
| `solve.centre_pull` | `0.01` | weight | the weak pull of every part toward the middle of the board, per unit spring |
| `solve.spread_pull` | `0.01` | weight | the first round's pull of each part toward its spread cell |
| `solve.spread_growth` | `2.0` | factor | the pull's growth each round after: round n pulls with `spread_pull * growth ** n` |
| `preview.converter` | `"rsvg-convert --width {width} -o {png} {svg}"` | command | the command `placemat preview` runs to turn its SVG into a PNG; `{svg}`, `{png}` and `{width}` are filled in |
| `preview.px_per_mm` | `40.0` | px/mm | the preview PNG's resolution, pixels per millimetre of the drawing |
| `preview.model_edge_px` | `1568` | pixels | the long edge, in pixels, an image is scaled to before the model reading it sees it - an assumption about that model, which placemat cannot know; the preview reports the resolution the model would then see. 0 reports nothing |
| `cleanup.enabled` | `true` | bool | after the searched tier, move and swap plain searched parts where that shortens their wire and declared links |
| `cleanup.passes` | `2` | count | passes over the movable parts; one that changes nothing ends it |
| `cleanup.search_radius` | `3.0` | mm | how far round its optimal region, and round where it stands, a part is searched |
| `cleanup.search_step` | `0.5` | mm | that search's step |
| `cleanup.swap_neighbours` | `4` | count | each part is offered a swap with this many of its nearest movable neighbours: both lifted, each searched round the other's old spot |
| `cleanup.swap_radius` | `1.0` | mm | how far round the other's old spot each part of a swap is searched |
| `studio.port` | `0` | port | the port `placemat studio` listens on, on 127.0.0.1 only; 0 is any free one. Not part of a run's id |
| `studio.debounce_ms` | `300` | ms | a change to a watched file starts a resolve after this long without another |
| `studio.open` | `true` | bool | open the browser on the page; `--no-open` overrides |
| `studio.keep` | `10` | count | resolves kept, so the page can compare any two |
| `studio.poll_ms` | `200` | ms | how often the watched files' modification times are read |
| `studio.explore_fps` | `2.0` | per second | how many times a second the board is redrawn for a live explore, to the best variant so far (above 0) |
| `studio.follow_hold_s` | `10.0` | seconds | while the studio follows the latest command, a newer one that starts is not shown for this long after the viewer selected an item, opened a finding or zoomed; the page offers it instead (0 shows it at once) |
| `studio.note_age_s` | `3600` | seconds | a note left in the studio is hidden after this long; 0 keeps it |
| `studio.notes_keep` | `100` | count | notes kept in a board's notes file |
| `studio.cancel_grace_ms` | `2000` | ms | a resolve asked to stop that has not stopped by then has its worker restarted |
| `studio.suggestions_per_lever` | `3` | count | a finding's suggestions for one lever (which side to place beside): the best this many |
| `studio.try_timeout_s` | `60` | seconds | a try of a suggestion (a resolve of the edited script) is stopped after this long |
| `studio.probe_budget_s` | `120` | seconds | a probe of a searched suggestion stops after this long in all, keeping the best candidate so far |
| `studio.probe_candidates` | `12` | count | the most candidates (resolves of the edited script) a probe tries, the first and the last check included |
| `studio.apply` | `true` | bool | false: the studio shows suggestions and diffs but refuses to write them |
| `studio.3d_kicad_cli` | `""` | path | the kicad-cli the 3D view converts models with; empty finds it on the PATH |
| `studio.3d_model_dirs` | `""` | path | more folders KiCad's own 3D model library may be in, separated by the platform's path separator, tried after the standard install places |
| `studio.3d_cache_dir` | `""` | path | where converted 3D models are kept, shared by every project; empty is placemat/models in the user's cache folder |
| `studio.3d_cache_mb` | `512` | count | megabytes the model cache may hold; over it the least recently used meshes are removed |
| `studio.3d_batch` | `8` | count | models converted per kicad-cli run (the progress granularity: each run costs about 0.3 s more than its export) |
| `studio.3d_batch_timeout_s` | `120` | seconds | a kicad-cli model conversion batch is stopped after this long, and its models are tried one by one |
| `studio.3d_model_tris` | `30000` | count | a model mesh over this many triangles is simplified (vertex clustering) once, when it is converted |
| `studio.3d_max_tris` | `4000000` | count | triangles the 3D view draws at most; past it the parts are drawn as plates and the view says so |
| `studio.3d_appear_ms` | `200` | ms | a part arriving in the 3D view drops in and fades over this long; 0 shows it at once |
| `studio.3d_plate_mm` | `0.1` | mm | how far the plate of a part with no 3D model stands off its face |
| `studio.3d_spread_mm` | `4.0` | mm | the 3D view's Spread: how much further apart each copper layer stands from the next when the stack is pulled apart |
| `studio.3d_spread_ms` | `450` | ms | the 3D view's Spread: how long the layers take to part and close; 0 moves them at once |
| `studio.builder_grid_mm` | `0.5` | mm | the board builder: a dragged outline dimension or vertex snaps to this step, and a suggested size is rounded up to it |
| `studio.builder_max_fill` | `0.5` | share | the board builder: the most of one face the parts' courtyards may fill in a suggested board size (above 0, at most 1); the outline dialog's fill field overrides it for one board. The one measured board is filled 0.33 per face on average |
| `studio.builder_aspect` | `1.0` | ratio | the board builder: the width over the height a suggested rectangle takes before the user changes it |
| `facts.confirmed` | `""` | text | the old single digest, read for any script with no entry in `facts.boards`; replaced by that table on the next `--confirm` |
| `facts.boards` | `{}` | table | `[facts.boards]`: a script's path relative to this placemat.toml -> the digest of its last `placemat facts --confirm`; placemat's own record, not part of a run's id |
<!-- settings-table:end -->

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
