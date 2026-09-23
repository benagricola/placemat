# The script surface

```python
from placemat import board, Net, Part, Cell, PadRef, CellPadRef, X, Y, Location, Centre, Pin, OnEdge, Near, Edge, Face, CopperLayer, Priority
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

The same answers from the command line, for when no script is running, are
`placemat parts <board>` and `placemat measure <board> <part> --pads`.

## Setup

`board.size(width, height, chamfer=0.0, radius=0.0, holes=(), web=0.0)` - the
outline, origin top-left, y down.
`board.disc(diameter, hole=0.0, holes=(), web=0.0)` - a round board at the origin, bored
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
board.place(item, at=Near(Location(x, y)), radius=3.0, step=0.2, rotations=(0, 90))  # searched round a hint
```
`item` is a `Part` (schematic instance), a `Cell` (module group) or a block
(below). One declaration per item. `why=` is recorded in the run. A FIXED
or EDGE item that lands on another is a script error: the run stops
there with the collisions, before anything is searched (`placemat run
--keep-going` records them as findings and carries on). A finding names
a cell member with its cell: `j_mot (edge): J5 courtyard overlaps cell
a1's R2 courtyard`.

**Degrees of freedom.** Each kind of place takes some away. `Location(x, y)`,
`Centre(x, y)` and `Pin(key, x, y)` fix both coordinates (the origin, the
body centre, or the item's own pad `key` (a number or a net), each axis a
number or a reference): a cap whose pad must sit on a pin's axis, a diode
whose pad faces another's, is a `Pin`. `Location(30, None)` or
`Centre(None, y)` fix one: the item slides along the line, at its middle
alone, sharing it evenly with the items pinned to the same value, aside
from what is there. `OnEdge(edge, along=)` fixes both: the reach at the
keep-in, and `along` the edge a number in mm, a reference, `Along.START`,
`MID` or `END`, or `Fraction(0.3)` of the usable length, the same on
every edge. `OnEdge(edge)` fixes one: it slides along the edge, midpoint
alone, the k-th of n at (k+1)/(n+1) with its fellows. `Near(location)` and
nothing fix none. Everything with a freedom left is searched, so it goes
down with the searched items in rank order, and an edge item's rotation
defaults to the cell's declared outward side (see Faces). Test points,
LEDs, buttons and a connector whose exact spot does not matter are
`OnEdge(edge)`, never `along=`. Whether a position is decided is
`Freedom` - `fixed` for a point, `edge` for a distance along an edge,
`searched` for anything with a freedom left - and it is DERIVED from
`at=`, never given.

**Rotation of a searched part.** A part searched from its links or round a
`Near()` hint, declared with neither `rotation=` nor `rotations=`, is tried
at 0, 90, 180 and 270, and the search keeps the turn that puts its pads
nearest what they connect to. `rotation=` keeps that one rotation;
`rotations=` the ones listed. An edge, a line or a ring decides its item's
rotation, and a cell or a block keeps its own. `[place] rotations =
"declared"` tries only the declared rotation, as before 0.28.

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

**A flip to the back** mirrors the item about the VERTICAL axis and then turns
it by `rotation=`. That is KiCad's own F key (`editing.flip_left_right`, its
default), and a part and a cell flip the same way. KiCad's orientation field
will read `rotation + 180` for a back-face part, which is exactly what you get
by drawing that part upright on the front and pressing F.

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
the run. A chain of small parts is the same thing repeated: each stage
linked to the stage before it and the two ends linked to the real pads
they terminate on, every stage a bare `place()`.

**`Near` is for what the netlist cannot say**: a thermal sensor that must
sit by the FETs it shares no net with, a test point wanted at the edge.
A `Location` constant that stands for "the power area" or "the CAN
corner" is a floorplan typed by hand; the placer floorplans from the
links, and a hint on a part that has a wired, placed neighbour is a
defect. Many parts hinted at one point compete for the same rectangle and
the last of them fails to place.

**The edge is the board's.** Nothing in a script says how far from the
edge a thing sits. `board.keep_in` is the board's own copper-to-edge
rule; an edge item's reach (body, pads and silk together, `board.reach(item,
rotation)`) lands there. A face that must stand proud of the edge says
`OnEdge(edge, overhang=)` with a why. A row inboard of an edge row is `behind=` it.

**Rows.** Things along one edge, in order, `gap` apart (default 0:
courtyards touching), their outward
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
power = board.row(PD, Edge.WEST, gap=3.0, start=TOP, line="outer")                  # connectors edge-hard; gap= only with a reason (default 0: courtyards touch)
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

**How a searched item finds its place.** With `Near` it scans around the
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
ordered by the placer, re-measured after each. A cell, a block and a loose
part are ONE queue: a connector can be the most important thing on a board
and does not wait behind the cells for being a single part. The script's
`priority=` tier leads, then the rank - courtyard area and pin count, each
measured against this board's other searched items - then the strongest link
pull toward what is placed, which only separates items the rank cannot, then
the largest. The sentence that chose each is in its step. One exception to
the rank: of two items joined by a `board.link()` and neither placed, the one
with less pull toward what is placed waits for the other, so it is seeded on
the part the link joins it to; its step says "waited for" which. Two pulled
equally keep the rank's order.

**What a part claims.** `[place] envelope` says what one part may not share
with another. `courtyard` (the default) is its courtyard and its pads.
`physical` is what the part draws, each on the faces it occupies: its pads,
each pad's mask opening (the pad grown by its expansion), every silk graphic
as stroked (the footprint's text fields excluded - `board.label()` text stays
a reservation) and its body, the box of its fab graphics. A footprint that
draws neither silk nor fab keeps its courtyard. `union` is both. Between two
different parts, every gap is the board's own:

| | another part's copper | mask opening | silk | body |
|---|---|---|---|---|
| copper | netclass clearance | - | - | component spacing |
| silk | - | silk clearance | silk clearance | 0 |
| body | component spacing | - | 0 | component spacing |

**The far face.** A part's courtyard and body are on its own face. Its
plated pads and unplated holes reach both, so on the far face a part keeps
only those: another part's pads keep their clearance from them, and another
part's courtyard may not sit over a lead (it stands proud of the far face).
A via in one of the part's own surface pads (an exposed pad's thermal vias)
is not a lead: on the far face it claims its copper only.

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
stands, and identical parts (one courtyard, pad count and face) are tried in
each other's places, keeping a change only when the part's wire (the
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

**Where each is searched from.** An explicit `at=Near(...)` first. Otherwise
the item is centred on the placed pads it is wired to, and an item wired to
nothing placed yet takes the largest free rectangle that fits it. A centred
item with no legal spot within reach takes the free rectangle nearest where
it was centred, and its step says "took the pocket" and how far off that is;
one with an explicit `Near` does not, and is left unplaced. With
`[solve] enabled = true` a global solve comes between the two: at the first
searched item it works out where every unplaced searched part and cell would
sit if the whole netlist pulled at once - placed items as anchors, each pad at
its offset, plane and free nets pulling only through declared links, then an
even spread over the board that keeps their relative order - and each item is
searched from that point instead. A block keeps its own seeding. A solved hint
with nothing legal within reach is dropped for the path the item had without
it. It is off by default: on one measured 96-item board it matched the
sequential seed on items placed and findings and joined seven more
connections, but cost one more DRC violation and 1.6% more airwire, so the
best-run gate judged it worse. Try it on a board whose searched items scatter
or land in pockets with "nothing it connects to is placed", and let the `best`
line judge. On the module benchmark (`fixtures/bench.py`, 2026-09-22, 32
modules) the solve was better than the sequential seed on 13 and worse on 15:
better on 7 of the 11 with fourteen or more parts, worse on 11 of the 21
smaller ones.

## Cutouts

A hole in the board is a `Cutout` in `holes=`, and every board takes them: a
rectangle, a disc and a shaped board all say it the same way and all behave
the same way.

```python
from placemat import Cutout, Slot, Circle, Path

FFC = Cutout(Slot(13.0, 3.0), "ffc",
             at=Centre(X(Part("j_ffc")), Y(Part("j_ffc"), 4.0)),
             why="the FFC cable passes through to the panel behind")
VENT = Cutout(Slot(8.0, 2.0), "vent", at=Polar(14.0, Fraction(0.5)), why="airflow past the regulator")

board.disc(diameter=40.0, hole=6.0, web=1.5, holes=[FFC, VENT])
board.place(J, at=OnEdge(board.cutout("ffc").edge(side=Edge.NORTH), along=Along.MID))
```

**The shape says what, `at=` says where.** `Slot(length, width)` is measured
tip to tip, the way a drawing dimensions it, and runs along +X until a
`rotation=` bearing turns it. `Circle(diameter)` is a round hole and refuses a
rotation. `Path(points)` is any closed path, moved so its box centre lands
where it is placed; `anchor=` on any shape names the point of it that lands on
the place instead. `at=` takes `Location`, `Centre`, `Polar`, `OnEdge` or
`Near`, and a freedom left in it is settled against what is on the board: a
vent with `at=Centre(None, 20.0)` slides along that line to where there is
room. A raw path in `holes=` still works and means "already absolute, place
nothing".

**Which way it runs.** With no `rotation=`, a place that carries a direction
runs the shape tangentially: a vent on a ring follows the rim, a slot on an
edge runs along it. Everywhere else the shape is as declared, and a `Circle`
is never turned.

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
board.keepout(shape, name, *, at, rotation=None, excludes=None,
              allow=(), layers=None, why="")
```

```python
CLEARANCE = Path(DATASHEET_FIGURE, anchor=(0.0, 0.0))  # the datasheet's own coordinates

board.keepout(CLEARANCE, "antenna", at=PadRef(Part("ant"), "ANT_FEED"),
              allow=(Part("ant"), Part("r_ant_series"), Net("ANT_FEED")),
              why="datasheet p1 Layout: copper-free on every layer")
```

**The shape and the place** are a cutout's: `Slot`, `Circle`, `Path`, and `at=`
taking `Location`, `Centre`, `Polar`, `OnEdge`, `Near` or a `PadRef`. A freedom
left in `at=` settles against what is on the board. `anchor=` is the point of
the shape that lands on `at=`; without one it is the middle of the shape's box,
which is right for a slot and meaningless for a stepped clearance.

**What it forbids.** `excludes=` defaults to everything and narrows to any of
`"parts"`, `"fill"`, `"tracks"`, `"vias"`, `"pads"`. Each is one KiCad
rule-area flag, and `"parts"` is what the placer enforces itself, before
anything is written.

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
for label 'BOOT' from the debug cell`), so a parent need not declare them again. They are read from the generated board, so a keepout whose name would
collide with one is refused.

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
board.row([L1, L2, L3], top, align="center")               # a row that turns with the edge
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
`start=`, `align="center"`, `rotation=` and `overhang=`; the anchors that
only mean something on a straight side (`line=`, `behind=`, `before=`,
`after=`, `centre=`, `end=`) are refused for now. Claims on a curve are
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
the edge the same way. `Polar` is a coordinate about `board.centre`, so it
works on any board.

**The keep-in is radial.** The rim holds an item's furthest corner back by
`board.keep_in`; a bore holds its nearest point out by the same, and that is
an edge, not a corner, when the item straddles the bore. A plane inset from
the rim is a disc, and Edge.Cuts is written as a circle (two, with a bore),
so KiCad mills the arc and clips every fill to it.

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
ldo = board.block(Part("ldo"), satellites=[(Part("cin"), "VIN"), (Part("cout"), "VOUT")])   # gap= only with a reason (default: courtyards touch)
board.place(ldo)                                                    # seeds from the links of its members
```
A block is a part and the satellites that sit at its pins: each satellite's
pad on the named net lands on that pin's axis `gap` beyond it, body
outward. A net names the anchor's FIRST pad carrying it; when several do (a
supply, a ground with thermal vias numbered into an exposed pad), name the
anchor's pad by number instead - `(Part("cdec"), 20)` - and the satellite
sits by its own pad on that pad's net. A satellite with no spot says which
anchor pad it was aimed at. The block is laid out from the anchor's REAL pads at every
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
A pad is named by its number (an int) or by the net on it (a str). A net that
several of the part's pads carry names the first of them in pad order, the
same pad in a `PadRef`, a `Pin`, a link and `board.part(x).pad(net)`; a
placement on it says which pad that was. Name the number to pick another.

```python
board.track(net, [p1, p2, ...], layer=CopperLayer.F, width=None, priority=Priority.DEFAULT, bridge=False)
board.via(net, point)
board.via(net, FreeSpot(near=PadRef(...), radius=2.0))               # the nearest legal spot to a pad
board.pour(net, [p1, p2, p3, ...], layer=..., swallow_pads=False)     # filled polygon
board.plane(net, layers=(CopperLayer.IN1,), outline=None, inset=0.4)  # zone(s), whole board or outline
board.finger(net, layer=, from_=point, to=point, width=)               # pour along a centreline, cut and bridged at tracks
```
All take `priority=`, which decides only who passes under where two tracks
of different nets cross. WHEN a piece of copper is planned is derived, not
declared: copper whose every endpoint belongs to something nothing will move
- a fixed or edge part, or plain coordinates - is planned before the search
and becomes an obstacle to it, so `board.via(net, Location(x, y))` reserves
its spot with nothing to remember. Copper naming a searched part is planned
after the search, once its shape is known.

**A via where one fits.** `FreeSpot(near=PadRef(...), radius=2.0, step=0.05,
layer=None, in_pad=False)` is the nearest point to the pad where a via clears
every other net's copper, every drilled hole, every keepout that forbids vias
and the board edge, and where a straight tail on `layer` (the pad's own by
default) reaches it. It is found when the pad's part is placed, against the
copper planned before it, so a second via near the same pad lands clear of the
first. The via stays out of its own pad unless `in_pad=True`: an SMD pad's
centre passes every other rule, and a via in a pad needs plugging. A search
with nowhere to go is a finding carrying why every nearer spot failed, and no
via is drawn.

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
board.label(Part("j_mot"), "MOTOR", side=Edge.SOUTH, knockout=True)              # gap= only with a reason (default 0)
board.label(Cell("power"), "POWER", side=Edge.NORTH, align="start", size=1.2)
board.label(PadRef(Part("jp1"), 1), "1", side=Edge.WEST, gap=0.3, size=0.6)
board.label(Part("j_bus"), "CAN", side=Edge.EAST, rotation=90, why="reads along the edge it plugs into")
board.label([SW_BOOT, SW_RUN, LED], ["BOOT", "RUN", "MCU"], side=Edge.SOUTH, knockout=True)   # one line for a row
board.label([PadRef(J, 1), PadRef(J, 2)], ["GND", "CLK"], side=Edge.NORTH, line=J)           # pin labels clear of the part
```
Text `gap` off `side` of the item's reach (or of one pad), on the item's
own face (mirrored on the back), aligned `centre`, `start` (the west or
north end of that side) or `end`; `rotation=90` runs it up the page.
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

A flip to `Face.BACK` mirrors about the vertical axis and then applies
`rotation=`, the same for a part and for a cell; KiCad shows the part's
orientation as `rotation + 180`.

`CopperLayer.F / IN1 .. IN30 / B` (the faces and every inner layer KiCad
allows; a board uses as many as its stackup has), `Face.FRONT / BACK`,
`Edge.NORTH / SOUTH / EAST / WEST`.

## Commands

```
placemat run <script> [--label L] [--fresh] [--no-render] [--no-drc] [-v] [--json] [--keep-going] [--route [--route-full] [--route-exclude NET ...]]
placemat route <layout.kicad_pcb | script> [--exclude NET ...] [--layers L ...] [--full] [--iterations N] [--out DIR] [--json]
placemat impact <run-dir-or-json> <run-dir-or-json>
placemat drc <layout.kicad_pcb> [--json]
placemat measure <layout.kicad_pcb | script | footprint.kicad_mod> [cell-or-part ...] [--pads] [--json]
placemat parts <layout.kicad_pcb | script> [--json]
placemat datasheet <pdf> [--show PAGE|TOPIC] [--read] [--no-ocr] [--out DIR] [--dpi N] [--json]
placemat datasheet check <pdf> <footprint.kicad_mod> [--pitch F] [--pad WxH] [--pads N] [--span F] [--tol F] [--json]
placemat occupancy <layout.kicad_pcb | script> (--at X,Y | --box X0,Y0,X1,Y1 | --via-near PART.PAD)
                   [--net N] [--size D] [--drill H] [--layer L] [--radius R] [--step S] [--in-pad] [--json]
placemat show <layout.kicad_pcb | script> <cell | part> [--out DIR]
placemat faces <module layout.kicad_pcb> outward=N [quiet=S] [handoff=E]
placemat check <layout.kicad_pcb | script> [--ambient C] [--keep-out MM] [--rise C] [--copper-oz OZ] [--limit CHECK=VALUE ...] [--json]
placemat settings [<script-or-board-dir>] [--json]
```

`measure` is the geometry query. Given a board it prints, per part, the
instance, refdes, value, face, rotation and origin, the `body`, `courtyard` and
`physical` boxes, its drawn envelope and the layer setting each side, how near
its courtyard and copper come to the board's edge, and a `footprint:` line
when its courtyard lies inside its own silk or equals its fab body. `--json`
gives each box by its edges too, as `boxes` (left, top, right, bottom). `--pads`
adds every pad's number, net, layers, drill, centre in the board frame, **the
box round its copper** - not the anchor size, which for a custom pad is not the
copper - and the mask and paste layers it opens; `--json` gives each pad's
copper outline as polygons. Given a path ending `.kicad_mod` it reads that
footprint with no board at all, in the footprint's own frame, and prints the
file's SHA-256 so two variants of a part can be told apart; a pad read that way
reports an attribute rather than layers, because a footprint has no stackup.

`preview` places the board as a run does - the cached generation, the
previous run's steps replayed - and draws it, without writing the board,
running DRC or rendering it:

```
placemat preview <script> [--svg] [--face front|back|both] [--out DIR]
                 [--zoom X0,Y0,X1,Y1 | --around PART [--margin MM]]
                 [--no-heat] [--no-links] [--no-copper]
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
face. A preview writes no run record; `placemat run` is still what checks the
board. It also prints the resolution a model reading the PNG sees: an
image's long edge is scaled to about 1568 px before a model reads it, so a
whole board comes through at a few pixels a millimetre.

`parts` answers "what are the parts called, and where are they": one line per
footprint with its cell, origin (x, y), rotation, courtyard area, pin count and
value (`--json` adds the body centre and the nets). The area and the pin count are what
the placement rank is worked out from, so the listing also explains the order
things went down in.

Both take `--json`. Reach for these before grepping a `.kicad_mod`.

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

A page carrying almost no text of its own is read off its render with
`tesseract` when it is installed; `--no-ocr` turns that off. It costs about a
second and a half a page and only runs on pages under 200 characters.

`check` reads the `Pm.*` facts the capture put on its parts (the
placemat-design skill says which) and reports hot loop area, switch node
copper, keep-out distance, crossings under sense tracks, current path
width against IPC-2221 and junction temperature; exit 1 on a failed
verdict. A board with no facts reports nothing to check. **Every `placemat
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
the script and the modules it imports from beside it, the generated board,
the tool, the settings and the fab profile; `--label` adds a symlink
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

A script runs with its own directory importable: geometry several scripts
share can live in a module beside them (`import core_geometry`), and a
change to it changes the run id.

Every finished run is judged against the best earlier run of the same parts -
its **family**, the runs whose script asked to place the same items - and
`.placemat/runs/best.json` keeps one best per family. Better means, in order:
more items placed, fewer real DRC violations, fewer findings, shorter airwire.
Completeness leads because DRC means nothing without it: a run that placed 29
of 101 items has little copper and so few violations. Airwire within
`best.airwire_noise` (1%) is a tie, because kicad-cli picks different
ratsnest edges each run for a byte-identical board. A run made with
`--no-drc` measured neither, so it is not judged and never becomes a best.
The run prints one `best` line - first of its family, matches, better than,
worse than, or not judged. **A run
that comes out worse is a finding naming the metric, and `placemat run` exits
1**, so a regression cannot pass unnoticed in a loop. Adding or removing a
part starts a new family. Routing needs
KiCadRoutingTools at `$KRT_DIR` (default `~/work/KiCadRoutingTools`) with
its own venv; quick mode is one routing round with the router's post-route
smoothing off (a measurement: a small two-layer board routes in about 10 s), `--full`
is the router's whole run. The search budget per net is the router's own
unless `--iterations` caps it.

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
| `run` | `latest.json`, `best.json`, and with `--label` an alias | `.placemat/runs/` |
| `preview` | `preview.svg`, `preview.png`, and `reuse.json` (what the next preview replays) | `.placemat/preview/`, or `--out DIR` |
| `route` | the input and routed boards, the router's log, `route.json` | `.placemat/route/`, or `--out DIR` |
| `show` | the item's renders | `.placemat/show/`, or `--out DIR` |
| `datasheet --show` | the page's render | beside the PDF, or `--out DIR` |
| `faces` | the declared sides, into the fragment | the fragment named |

`.placemat/` sits in the board's directory. The other commands only read.

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
| `place.courtyard_touch` | 0.0 | how far two courtyards may overlap at least; each pair may also overlap by the two parts' margins (how far KiCad's courtyard polygon lies inside the drawn box) less 0.001 mm, which keeps KiCad's courtyards apart - it counts touching as overlapping |
| `place.conflict_gap` | 1.0 | how far outside a box a conflict can still reach |
| `copper.chamfer` | 1.0 | how far a right angle is cut back into two 45s |
| `copper.pair_chamfer` | 0.5 | the same, for a differential pair |
| `copper.pair_via_step` | 0.4 | how far clear of its partner a pair's lead vias |
| `copper.bridge_half` | 1.1 | half the gap a bridge leaves round a crossed track |
| `copper.finger_bridge_width` | 1.0 | the width of a finger's bridge under a track |
| `copper.plane_inset` | 0.4 | how far a plane is inset from the board edge |
| `copper.plane_clearance` | 0.2 | a zone's pullback from foreign copper |
| `copper.plane_min_thickness` | 0.2 | a zone's minimum filled width |
| `copper.pour_stroke` | 0.2 | a pour's outline stroke |
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
| `check.limits` | none | a bound per check, e.g. `"hot-loop" = 20.0` (`--limit`) |
| `drc.severities` | none | a table of KiCad rule names to `error`, `warning` or `ignore`, written into the board's .kicad_pro before DRC |
| `drc.real_kinds` | eight classes | which violations mean the board is not done |
| `drc.outstanding_kinds` | three classes | which violations are copper not yet joined |
| `drc.footprint_kinds` | four classes | which violations are defects in the footprints themselves |
| `drc.refill_zones` | true | refill zones for the check |
| `route.router_dir` | `$KRT_DIR`, else `~/work/KiCadRoutingTools` | the KiCadRoutingTools checkout |
| `route.quick` | true | one routing round rather than the router's full run |
| `route.iterations` | the router's own | cap on the router's search per net |
| `route.layers` | every copper layer | which layers the router may use |
| `timeout.generate` | 900 | seconds for `pcb layout` |
| `timeout.drc` | 600 | seconds for kicad-cli DRC |
| `timeout.route` | 3600 | seconds for the router |
| `timeout.render` | 300 | seconds for a render |
| `noise.patterns` | none | extra KiCad stderr patterns to suppress, ADDED to the built-ins |
| `best.airwire_noise` | 0.01 | how far airwire may move, as a fraction, before a run counts as better or worse than its family's best: kicad-cli picks different ratsnest edges each run for a byte-identical board |
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
three times in four); it is reported, not yet steered by.

Every verb whose default appears here takes an explicit argument that still
wins: `board.plane(..., inset=1.0)` beats `copper.plane_inset`.

Three kinds of constant are NOT settable, because they are not behaviour: the
grid epsilons (ten KiCad units, the file format's resolution), the physical
constants (IPC-2221 and unit conversions), and the tables that map placemat's
words onto KiCad's layers and flags.
