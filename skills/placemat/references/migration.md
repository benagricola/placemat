# Migrating a layout script

Sections are per release, newest first. Read the ones between the version a
script was written against and the version in use; `SKILL.md`'s check line says
whether any of it applies. "Patterns in older scripts", at the end, names the
section for each hand-written pattern a newer form replaces.

## Unreleased

A keepout that admits something (`allow=` or `max_height=`) is now also
drawn on the board: its outline and a label naming what it admits, on the
Fab layer of its face or `User.Comments`, in its own group `keepout
drawings`. `write.keepout_drawings = "none"` turns it off; `"all"` draws
every keepout, admitting or not.

A keepout that admits parts (`allow=` parts or cells, or `max_height=`) is
written as a KiCad rule area that allows footprints, with a `.kicad_dru`
rule forbidding the parts it does not admit. Parts it admits are no longer
KiCad DRC errors when placed by hand; a part it would refuse still is.

`board.push(item, from_=, falloff=, reference=(r_ref, v_ref), limit=)`
holds an item back from a source by a physical falloff model: illegal
inside a disc round the source, priced by how close it stands within
that. Where a script used `Near` on a hand-picked far point for a
requirement the netlist cannot say, and the real requirement is a
distance a field or a temperature falls off over, `push` replaces the
hand-picked point with the physics.

## To 0.60.0

`board.outward_rotation(item, edge, face=Face.BACK)` answers for an item on
the back. A flip mirrors the item before it turns, so the front's answer
turned a cell's declared east or west side the wrong way. An edge, a run,
a rim and a block now turn a back-face cell from its mirrored side on
their own. A script that negated the turn for the back by hand passes
`face=` instead.

**A cell of several jobs.** `placemat run` now reports a `split` finding
for a cell whose members form two or more groups
(`place.split_min_group`, default 2) joined only by nets that are not
local to it - a board-level net, or any `board.plane()` net whatever its
pads - and names the parts no net inside the cell joins to another, to be
judged each by what places it: a bypass capacitor stays with the IC it
serves, a sensing part at what it senses. It carries no run-score weight.

A net class makes pairs only when it sets its own `diff_pair_width` and
`diff_pair_gap`. In 0.58 every class but Default did, because KiCad reports
its default pair figures on every class: a two-net class of control lines
at their own width was paired and routed coupled.

`placemat facts` reads a `via` section naming every type `"no"` as decided
(through vias only), where 0.58 read it as missing. A section that leaves a
type out stays unconfirmed, and the reason names the types.

## To 0.59.1

`placemat facts` reads the board as generated, as `run` does. It failed on
a board run before whose script names a keepout, reading the last run's
written layout and its rule areas.

## To 0.59.0

Faster, with the same results:
- `check current-path` measures a zone fill's width from rasters in the
  native module. It is about six times faster on a whole six-layer board.
- The search's own bookkeeping round the native sweep is lighter.
- A carried via's move is searched natively.

No verdict, placement or refusal sentence changes. Nothing to do in a
script.

## To 0.58.0

Board facts come from the board, not placemat.toml. Three keys are
retired: `[check] copper_oz`, `[route] layers`, `[route] diff_pairs`. A
placemat.toml still setting one is refused, naming its replacement.

**The stackup.** Give the board's `BoardConfig` a `stackup`, with a
`CopperLayer` for each copper layer, top to bottom, and a `DielectricLayer`
between each pair:

```python
load("@stdlib/board_config.zen", "BoardConfig", "CopperLayer", "DielectricLayer",
     "Material", "Stackup")

STACKUP = Stackup(
    thickness = <board mm>,
    materials = [<the fab's prepreg and core, as Material(...)>],
    layers = [
        CopperLayer(thickness = <mm>, role = "<signal|mixed|power|ground>"),   # F.Cu
        DielectricLayer(thickness = <mm>, material = "<name>", form = "<prepreg|core>"),
        # ... each inner copper layer, with a dielectric after it ...
        CopperLayer(thickness = <mm>, role = "<signal|mixed|power|ground>"),   # B.Cu
    ],
)
CONFIG = BoardConfig(stackup = STACKUP, design_rules = ...)
```

A layer's role is what it carries: `signal` tracks, `ground` or `power` a
plane, `mixed` both. The route step now routes on `signal` and `mixed`
layers (was: every layer minus one a plane happened to fill whole);
inner-layer current paths are now judged by the inner IPC-2221 constant
and the layer's own weight (was: every layer as outer copper of `[check]
copper_oz`). A board's route and current-path verdicts can change on this
release.

**Pair classes.** A differential pair class takes `nets = ["<NET>_P",
"<NET>_N"]` (names or KiCad wildcard patterns), with its `diff_pair_width`
and `diff_pair_gap`. A class of exactly two nets pairs them whatever they
are called; more than two pair by the router's own suffix convention
within the class. The Default class never makes pairs. Pairs now come
from net classes (was: `[route] diff_pairs`, default every net named like
a pair).

**fab-profile.json.** `via`'s types take `"yes"`, `"no"` or `"if-needed"`
(the 0.57 `allow_*` booleans still read: `true` -> `"yes"`, `false` or
absent -> `"no"`). An `"if-needed"` type is never drawn for a script's own
`layers=`; give way's new "shorten" way may still use it, judged but never
applied, and an item it would have placed is a `needs` finding. A `min` section (`track_mm`, `clearance_mm`, `drill_mm`,
`annular_mm`, `via_size_mm`) is checked against the board's net classes at
the start of every run.

**`placemat facts`.** Run it, then `placemat facts --confirm` once the
printed facts are right. A run whose facts do not match the last
confirmation says so on its own line and records a finding, but still
runs.

## To 0.57.2

A keepout that excludes parts only no longer judges a cell's own tracks
and pours: a cell whose members are let in or stand outside it, with its
own copper inside, is placed where it was refused.

## To 0.57.1

A carried via shares only another item's via, and a via another shares
no longer gives way itself: in 0.57.0 a cell's vias could share one
another in a chain until none was left where the tails ended. A spot where
a later item meets a shared via is refused, naming the via that shares it.

The write no longer fails with "'SwigPyObject' object has no attribute
'Cast'" (or "... no attribute 'x'") where a cell's vias gave way.

## To 0.57.0

A cell flipped to the other face keeps its own inner copper on the layer
it was drawn on: F and B swap, In1..In4 stay, where 0.56.2 mirrored them
through the stack as KiCad does. The writer puts them back after KiCad's
flip. A via that reaches a face still mirrors (F-In1 becomes B-In4), and the
cell's step says when its inner end may no longer join its net. A
footprint's own copper mirrors as before. A script that kept a cell on its
own face to hold its inner layers' roles may flip it.

A micro, blind or buried via (`layers=` on a via) is refused unless
`fab-profile.json` allows its type (`"via": {"allow_micro": true}` and
so on); a stamped fragment carrying one fails the run the same way.

`placemat measure --models` says when a part's 3D model sits off its pads
or looks turned 90 against its fab outline.

`placemat parts --fragments` names the fragment each part was stamped from.

`board.place(Cell(...), at=Pin(Part(member), x, y))` puts a member's
footprint origin on the point: a cell placed by a point that is no pad (a
winding's arc centre on a disc's centre), not by an offset worked out in
its own frame.

`check current-path` no longer judges a net only one part carries: it
judged the route to the widest-joined other pad at the full current, often
a capacitor carrying ripple, and failed it. Give the part that takes the
load its own `Pm.I` and the route between the two is judged.

`Past(items, Corner.NE)` is a waypoint for a 45 held the clearance off a
corner of the items' copper box, and `(own_pad, Past(pads, Corner.NE,
lane=Net(...)))` in `Beside`'s align stands a pad off that 45. A waypoint
on a 45 worked out by hand - a constant x - y (or x + y) from the pad's
corner plus the clearance and half the width times root 2 - can be said
this way; the drawn 45 lies on the same line.

`check current-path` measures a zone fill's width along the load's route,
at `check.zone_step` (default 0.05 mm): two carriers only a fill joins are
judged, where they read "not judged", and a route through a fill names the
fill's narrowest point when that is its neck. A verdict can newly fail on
a fill lane that is narrower than the current needs.

A linked item never waits for a partner of a lower `priority=` tier: a
`HIGH` item linked to a `DEFAULT` one goes down with the `HIGH` tier, where
it waited for its partner and its step said its priority was set aside for
the link. Between items of one tier the wait is unchanged. Placements where
such a link crossed tiers can move.

A carried via - one at a searched part's pad, or a stamped cell's own - that
meets another net's copper no longer refuses the spot outright: it shares a
same-net via within `place.via_share`, moves up to `place.via_move`, or, a
plane drop, is dropped while its pad keeps `place.drops_keep` of its drops
(api.md, "Carried vias give way"). The search prices each at
`score.via_share`, `score.via_move` and `score.via_drop`. A via already
placed gives way to a later item on the other face the same way. A cell
that found no spot on a face under another's vias may now place; what gave
way is a `vias` finding and a note on the owner's step. `place.via_share =
0`, `place.via_move = 0` and `place.drops_keep = 1` turn each off.

## To 0.56.2

`layers=(CopperLayer.B, CopperLayer.IN4)` on `board.via()`, `board.vias()`
and `board.stitch()`: a via of that span only, judged on its layers alone
and written as KiCad's micro via (one layer from an outer face, drill
`copper.microvia_drill`) or a blind or buried one. Without `layers=` a via
is a through via, as before.

A cell flipped to the other face is judged with its inner-layer copper
mirrored through the stack, In1 with the last inner layer, which is where
KiCad's flip writes it: a track on In1 of a six-layer cell placed on the
back is judged on In4. It was judged on In1. Copper on every layer (a
through via, a plated pad) is unchanged.

`board.place(Cell(...), drops=Drops.HALF)` or `Drops.MIN` thins the
cell's via fields where it is placed: the vias of a `plane()` net inside
one of its members' pads. HALF keeps a checkerboard of each field; MIN
keeps `place.drops_keep` of it (0.5, rounded up, at least one). The
default, `Drops.ALL`, keeps them as stamped, and a script that does not
say `drops=` digests as before.

A copper finding measures a via as the circle it is, as KiCad's DRC does:
a via just over the clearance from a track read as just under it ("0.16 mm
... needs 0.16") from its polygon, a few microns outside the circle. The
placement search still judges the polygon.

A refusal's copper count names whose copper it met and its net ("copper
x363: cell logic's U3 GND front face x120, via GND ..."); a copper finding
names only the layers the board has.

An item `OnEdge(run, overhang=)` on a stretch of a shaped board's edge
overhangs it by exactly `overhang`, as on a named edge; it stood with its
centre on the edge whatever the overhang.

## To 0.56.1

A cutout or keepout `OnEdge` an east or west edge is held back by half its
depth as turned along the edge, not half its length: a long slot there
stood off the edge by the difference, and now sits flush as on the north
and south edges.

`PadRef(part, n, land=Land.LARGEST)` or `land=2`: one land of a pin drawn
as several. A track or via that had to end at hand-typed coordinates on the
exposed land can name the land instead.

`board.keepout(Inside(Part(...), margin=), name, ...)`: the box inside a
part's pads, between its two pad columns or inside its pad ring, moving and
turning with the part. A region worked out by hand from pad coordinates can
be declared this way.

`route.diff_pairs` takes an entry `"NET_A/NET_B"` naming two nets as a
differential pair (P first), for nets without a `_P`/`_N`, `P`/`N` or
`+`/`-` suffix. The route step routes them under a suffix name in its copy
and names them back; placement weighs their crossings as a pair's. An
existing entry with one `/` that is not leading and has no glob character
now reads as a pair.

The skill no longer keeps a list of relations placemat cannot say. A session
looks for the form first - api.md's intent index, the relations, a
composition of forms, the newest sections here - and writes a relation up in
the board's `PLACEMAT_GAPS.md` only when that search finds none. api.md gains
a "Read the board" index from a question to the command that answers it.
`references/capture.md` no longer lists `Pm.Role` or `Pm.Creepage`: no check
reads them, and a capture that carries them is unaffected.

A firm placement (`Pin`, `Beside`, `row(of=)`, a point said in pads) whose
reference is a searched part or cell rides it, where it used to be refused
with "only FIXED and EDGE items may be referred to". The reference is
searched with its riders placed at each candidate, and they commit together;
each rider's step says `rides <key>`. A part fixed only so another could be
placed off its pads can be searched again. A rider keeps the rotation it
declares: `rotation=Turned(Part(...))` and a `.local()` offset turn it with
its reference. A relation to a second searched item, and a keepout or
cutout at a searched part's pad, are still refused.

## To 0.56.0

`Past(pads, Edge.X, lane=Net(...), width=)` in `Beside`'s align: the lane
as wide as the copper its current needs, so a part stands clear of a power
pour's width rather than a track's.

A `swallow_pads` pour whose corners are all pads (three or more) covers the
convex hull of the pads' copper, not the polygon through their centres,
which over pads in a row was as thin as its stroke and failed a
current-path check. `cover=Cover.BOX` takes the box round the pads' copper;
`cover=Cover.CENTRES` keeps the old shape. A power pour drawn by hand from
pad edges can be declared over its pads.

`placemat layer <board> <LAYER>` draws one copper layer by net and lists
tracks inside another net's zone outline.

`board.pair(p, n, [(padP, padN), (padP2, padN2)], layer=)` - the two pad
pairs alone - finds its own centreline; a centreline typed as coordinates
between two placed parts can go.

`placemat measure --keepouts [NAME ...] [--near MM]` reports each part's
physical and courtyard gap to each rule area near it.

Escape findings, and so the run score, are measured at `score.escape_depth`
(1.5 mm), not at the search's `place.escape_depth` (still 1.0 mm): a
shallower search depth no longer scores better by checking less. A best run
recorded by 0.55.0 or earlier may give way to the next run.

## To 0.55.0

A block satellite that slid along its anchor's pin row says so in its step:
how far off its pin's axis, and which of the anchor's pins its body now
stands in front of.

A `FreeSpot` via's tail runs at 0, 45 or 90 degrees - a 45 from the pad,
then straight - not as one leg at whatever angle the spot lay; a spot that
tail cannot reach is passed over for the next. A script that drew its own
track to a `FreeSpot` via with `tail=False` for that reason can drop it.

Copper planned in one batch is judged against the rest of that batch too,
not only against what was on the board before it: a track of one net run
through a via of another, both with nothing to wait on, is a finding now
(it was a DRC failure behind a clean report).

`board.row(items, Edge.X, of=Part(...))` takes `centre=PadRef(...)` and
`pitch=`: the row's middle on a pad's centre line (a pad of `of` or of any
firmly placed part), its items' centres `pitch` apart. Two parts at a
mechanical pitch centred on a driver's pin no longer need their positions
worked out from the pin by hand.

`board.plane(net, layers, over=[Part(...), Cell(...)], margin=)` bounds a
plane to the box round those items' drawn envelopes, where they were
placed, clipped to the frame. A plane outline built by hand from a group's
box, which left off a part placed by `Beside` outside that box, can go.

`placemat measure` prints each 3D model's file, offset, rotation and scale,
and `--envelope` names the item that sets each side of a part's drawn
envelope; `--json` adds `models`, `envelope_items` and a `fab` box.
`measure --copper [NET ...]` lists the track segments a board carries, what
each end lands on and any leg off 0/45/90.
`placemat parts` ends with the board's part, pad and solder-joint counts;
`placemat drc` names each item's part by instance path beside its refdes.

A cell nested in another cell's group (a module sheet's child) is written
where the plan puts it: placing the parent moved the child group with it,
after the child had been placed, off its spot with no finding. The parent
carries only its own parts and copper, as the plan already judged it; a
child that should travel with its parent is placed relative to it.

A net-tie footprint's own copper (a winding joined to its pads) no longer
reads as a conflict with a track or pad of one of its net-tie pads' nets
where the two meet inside that pad, as KiCad's DRC allows: a track ending on
a winding's terminal pad was reported 0.00 mm from the footprint's copper.

`Past(items, Edge.X)` takes vias (what `board.via()` or `board.vias()`
returns) and tracks (what `board.track()` returns) as well as pads, in any
mix, each held off by the clearance of its own net. `across=` puts the
point on a pad's or a via's centre line, or at an `Along` of the items'
side, in place of the middle. A track waypoint computed by hand from a
via's centre, its size and the clearance - a track's U-turn under a row of
vias - is `Past([vias], Edge.SOUTH)`.

`board.via(net, at=Past(items, Edge.X, across=PadRef(...)))` stands a via
its radius plus its clearance off the items' side, on the pad's axis. A via
placed at a pad tip's coordinate plus the clearance plus half the via's
size, computed by hand, can be said this way.

`Beside(item, Edge.X, align=(own_pad, Past(pads, Edge.Y, lane=Net(...))))`
stands a part's pad a lane past other pads - the clearance to the lane's
net, its track width, and the clearance to the pad - while `Beside` decides
the other axis. Without `lane=` the pad stands the clearance off. A part
placed with its pad offset by hand from another part's pad by half pad
widths and a lane can be said this way. The Past takes pads only: a
placement is decided before copper is planned.

## To 0.54.1

Two `swallow_pads` pours of different nets now keep the netclass clearance
from each other as written, not only from each other's declared outline:
two pours over the two ends of a small part no longer meet. They settle as
KiCad's zone priority does: the pour the plan draws first (the one declared
first, when both wait on the same placements) keeps its fill and the later one pulls back
from it, so pours over neighbouring fine-pitch pins each keep a piece over
their own pin. A script that dropped one of two neighbouring pours, or swapped it
for a plain pour and a track, can declare both again.

A swallowed or named pad counts as joined when the pour's copper (its fill
and half its stroke) overlaps the pad, not only when the fill covers the
pad's centre: a pull-back that cut a pour short of a pad's centre reported
"joined to nothing" for a pad KiCad's connectivity saw joined.

`board.vias(net, along=PadRef(...), count=N)` now draws a tail at the net's
width from the pad to the farthest via: a via standing just clear of the
pad's tip was unconnected. A track may end on the value it returns (the
farthest via); a hand-drawn track joining the row to its pad can go.

`Beside(item, Edge.X, align=PadRef(...))` takes any firmly placed part's
pad, not only `item`'s: a part beside one part, level with another part's
pin, no longer needs its position from that pin by hand.

A keepout shaped by a part (`board.keepout(Part(...), name)`) now covers the
part's own copper graphics too, not only its pads, mask, silk and body: a
fill it excludes stays off a winding drawn as copper past the pads.

## To 0.54.0

The capture material - the `Pm.*` annotations, how wrappers forward them,
what `placemat check` reads - is `references/capture.md`, signposted at the
top of SKILL.md.

Nothing to change in a script that works. New intent forms replace the
coordinates the scripts audit found (see SKILL.md's "Declare by intent" and
the intent index): `at=Beside(item, Edge.X, align=...)` for a part beside
another part, a cell or a keepout at the envelope's own gap;
`board.row(items, Edge.X, of=Part(...))` for a row along a part's side
(also in a fit frame); `Pin` with a cell's member pad; `board.keepout(item,
name, margin=)` for a region shaped by a part's or a cell's drawn envelope,
moving and turning with it; `board.size(fit=Axis.X, height=...)` (or
`Axis.Y`) for a frame fitted in one axis. For copper: `Between(pad, pad)`
and `Past([pads], Edge.X)` as track waypoints (a lane through the gap
between two pads, or held off their side); `board.track(..., bend=Bend.START
| Bend.END | Bend.BOTH)` for the end of a leg that takes its 45;
`board.pour(net, [pad, pad], swallow_pads=True)` for a neck between two
pads; `board.finger(..., width=PadRef(...))` as wide as a pad;
`board.vias(net, along=PadRef(...), count=N)` for a row of vias out from a
pad; `board.stitch(net, region)`. A helper that computed any of these from
pad boxes or envelopes can go.

A pour grown over pads (`swallow_pads=True`) now pulls back from every other
net's copper on its layer to the netclass clearance, as a zone fill does,
and keeps only the pieces touching its pads: one that came within clearance
of a pad beside the pads it covers is clean now. The pull-back now also
reaches a pad with no net, or on a net this board's geometry does not know
(the board's own default clearance for either), reads each pad's real
shape rather than its bounding box, and reaches copper already on the
board before this run (a stamped cell's own tracks, vias and pours), not
only what this run itself plans; a piece the pull-back splits off keeps
every one now, not just the first, once the board is saved and reloaded.
Only a same-net pad among a pour's declared
points is one of its own pads - a corner given as another net's pad shapes
the outline near it and is never swallowed or checked as joined. The plan
report does not check a `swallow_pads` pour's clearance to other nets
either (placemat has no polygon subtract to compute the write-time
pull-back at plan time, so a finding there would be wrong once the pour is
written); the pour still occupies the board at its declared shape, so it
remains an obstacle for copper planned after it.

`board.stitch(net, region, pitch=None, size=None, drill=None, edge=False)`
now refuses at declaration, rather than planning nothing and saying no via
fit: a keepout region whose `excludes` forbids vias (the default) and does
not `allow` the stitching net; a pour region of a different net.
`edge=True` rows the vias along the region's own outline instead of
filling its inside.

`Between`/`Past` no longer raise a `KeyError` naming an empty net when the
gap or the side they measure sits next to a pad with no net; they fall
back to the board's default clearance for it, as the occupancy's own
conflict check already did.

A keepout or cutout with `rotation=Turned(part, degrees)` now turns the
way its part does: an asymmetric one turned the opposite way at 90 and 270
(a symmetric one, a slot or a circle, is unchanged). `degrees` turns the
same way a part's own rotation does - anticlockwise on screen - not as a
bare bearing would; the region's stored rotation is still its own bearing,
clockwise from the top, so a quarter turn with the part (`degrees=0`)
reads 270.

## To 0.53.0

Read `SKILL.md`'s "Declare by intent" section first: a script says where a
part goes relative to what, and placemat computes the numbers. The check
line now counts `X()`/`Y()` with offsets, `.local(`/`.offset(` and
measurements read into numbers; each is a place to use an intent form (the
index at the top of api.md) or, where none fits, a gap to record.

Documented forms that were broken now work: a block placed on an edge, a
run, a rim or a bore, or with one axis given, lands there (it was centred);
`OnEdge(..., along=<reference>)` on a board's or a cutout's edge; a cutout
or keepout `at=Near(...)`; `Polar(about=)` and `ring(about=)` a part or a
pad; a keepout or cutout `rotation=Turned(...)`, one at fixed numbers
included. `row(align=)` and `label(align=)` take `Along` (the strings still
work, and `row(align="centre")`/`"end"` now do what they say: they acted as
"start"). `row(align=..., centre=/end=/start=<reference>)` now refuses,
whatever align's spelling: the two say different things about where the row
starts, and only `"center"` with one of them was refused before. `row(line=)`
takes `Line`; `keepout(excludes=)` takes `Forbid`;
`place(face=)` refuses anything but a `Face` or its name. A finger's copper
is exactly `width` wide (it was 0.2 mm wider): a script that narrowed its
width to make up for it can use the width it means.

A keepout's `allow=Net(...)` lets that net's copper through and no longer
admits the parts that carry it, as the docs always said: a part that stood
in a keepout only because it carried an allowed net is refused there now
(the finding names the keepout); name it with `Part(...)` or `Cell(...)`.

Each stamped cell's KiCad group is lifted out of its module sheet's group to
the top level on the written board (groups are one level), so moving a
sub-module by hand in pcbnew no longer drags its module; a module keeps its
own parts. `[write] split_groups = "split"` also takes the parts a script
places one by one out of their module's group; `"keep"` writes the groups as
generated. `board.group(name, parts)` writes a top-level group of the parts
named: a script that rewrote the board's groups with pcbnew afterwards can
declare them instead.

New reports: `placemat nets` (each net's pads, span, routed length, detour,
vias, layers); `placemat parts` warns for a placed part with no order number
(`[parts] order_fields`); `placemat occupancy --corridor A B --layer L
--width W` gives the clear paths on one layer between two pads, or the
blockers. The keep-out verdict names the copper it measured (a part's own
pins, which it does not judge, said after it when nearer), a current-path
verdict gives its neck's point and length, and a copper finding against a
declared track names its segment, and its chamfer when that is what came
within clearance.

## To 0.52.0

Nothing to change in a script. Every route is laid with the router's turn
cost at 20000 (`[route] turn_cost`; the router's own default is 1000) and
its smoothing on: routes come out with fewer than half the kinks and less
copper, closure no worse on the boards measured. Routes already kept stay as
they were laid; to lay them again, `placemat routes <script> --release-all`
then `placemat route <script> --adopt-all` (with `--partial` if wanted).
`[route] router_args` passes more of the router's own flags through.

A cell meets a keepout member by member: a member named in `allow=`, or
carrying a net it names, no longer admits the rest of its cell, and one tall
member no longer keeps the low ones out of a height band. A cell that stood
in a keepout because one member was named may be refused there now (the
finding names the member); name the others, or `Cell(...)`, to admit it.
The same goes for a fanout's band, which admits the parts it names: a cell
with one of them no longer enters it whole. A cell's own tracks have no
height, so a height band leaves them be.

## To 0.51.1

A keepout whose shape has no area (a computed rectangle whose two sides
came out equal) is refused where it is declared: it kept nothing out, and
KiCad reads its rule area as malformed. Fix the shape or drop the keepout.

## To 0.51.0

Nothing to change in a script. `placemat lock <script> --current --partial`
locks the items that stand and lists the rest, where `--current` alone
writes nothing unless every item stands.

A pour net with pads its pours do not reach (a rail's taps behind a cell)
can be routed for those: `[route] islands = ["VSENSE", "VRAIL=0.5"]` in
`placemat.toml`, or `placemat route --islands NET[=WIDTH]`. Hand-drawn
track legs kept only because 0.50 left such nets unrouted can go.

## To 0.50.0

Nothing to change in a script. Under the `physical` envelope a part's
courtyard keeps off another part's plated lead, both ways, as KiCad's DRC
judges it: a part that stood with its courtyard over a lead moves clear, and
a refusal names the pad (in every envelope). A stamped cell's zone whose pads
join otherwise than the board's plane is kept (it was merged, and its pads
lost their solid connection); one reaching nearer the board edge than the
plane's keep-in merges. `placemat route` leaves nets with a zone or a filled
pour to their pours, as `run --route` did, and keeps other nets' tracks
out of a partial inner-layer pour of those nets (the refill split it round
them); a board-wide fill need not be switched off for routing, the router
routes through it and the refill carves round the tracks. "No legal location" names the
parts whose silk, mask or body were in the way under a drawn envelope (a
round board's rim or a cutout is counted as the edge), and a link's wait
says when it set the item's `priority=` aside. A cell placed on the back
with a member read at 90 or 270 degrees records that member's turn as its
shapes stand: its airwire ends, a via declared at its pad, a part `turned=`
from it and a lock entry anchored on it followed the mirror image before; a
lock entry so anchored may land elsewhere; `placemat lock <script>
--current` writes it again. `placemat route` leaves a stamped cell's own zone net to the
router (only the board's own pours are left out, as `run --route` does).

## To 0.49.2

Nothing to change in a script. A later `route --adopt` keeps the entries of
a net that held on the board it routed (it replaced them all, and the new
islands resting on their copper dropped on the next run), and says which
it replaced. `check current-path` judges each pair of
parts carrying a net's current at the lesser of their two currents, through
zone fills as well as tracks and pours (a fill's own width is not measured:
a route through a fill alone is not judged), and does not judge carriers no
copper joins yet. A controller that senses a load's net should give that
net its own current in a per-net `Pm.I`, or leave it out: its sense pin is
then judged at what it draws. Verdicts that were a pin lead, a boot track or
a sense line become the load's own route.

## To 0.49.1

Nothing to change in a script. `placemat route` routes with the board's own
settings (`[route] layers` was ignored). A kept route whose end rests on a
zone of its net no longer drops on every run; entries kept by 0.49 with
such an end are replaced by the next `route --adopt`.

## To 0.49

Nothing to change in a script. A via declared at a searched part's pad
travels with the part through its search, so plane drops at pads
(`board.via(net, PadRef(...))`) no longer land over the other face's pads;
a part with such drops may land a little further from where it did. A
copper finding against a via says "via NET at (x, y)" rather than "pad".
A stroked pour reads as one piece of copper again (0.48 read its strokes
apart, and `check current-path` took a pour for a 0.3 mm strip). A cell's
lock entry no longer releases when its fragment is stamped again; entries
0.48 released are written again by `placemat lock <script> --current`.

`route --adopt ... --partial` keeps the closed parts of a net the route
left open (each island joining two pads, or a pad and a plane), so a plane
net the router never finishes keeps its drops and joins from pass to pass.

## To 0.48

Nothing to change in a script. A courtyard that is not a rectangle (a
slice of a disc, a part generated at a turn off the axes) is claimed as
KiCad draws it rather than as the box round it: parts that collided by
their boxes, or crossed a round board's keep-in by a box corner, may now
stand. A via's copper is judged as the whole circle, so a via planned a
hair inside a clearance (0.1575 against 0.16) moves off, and a stroked
copper polygon (a pour) is read with its stroke along every edge, which a
polygon that doubles back on itself had partly lost. `placemat lock
--current` works on a board a `--keep-going` run wrote.

## To 0.47

Nothing to change in a script. `placemat lock <script> --current` locks
every searched item where the board stands (a hand-written wrapper round
the lock API can go); `route --adopt` locks the items the kept nets join,
and adopts nothing when the placement it was given would not come back.
The lock and the routes file name parts by instance path: a refdes
renumbering no longer releases lock entries or drops kept routes once they
are written by 0.47 (`lock --current` rewrites a lock; routing again
rewrites the routes file). Files written by 0.43-0.46 still read, by
refdes. `placemat drc` names each failing violation
and where it is; `--json` lists every violation and open connection with
its items' positions. `measure --pads` prints a custom pad's outline.

## To 0.46

Nothing to change in a script. Routing keeps off footprint copper graphics
(a winding drawn on copper layers) and the routed copy keeps them on their
copper layers: a routed copy judged clean while its windings' outer copper
had been moved to silk is now judged with it.

## To 0.45

Nothing to change in a script. A written board's 3D model paths that did
not resolve from its own folder are re-anchored to where the file is, so a
module deeper in the tree renders with its bodies; a fixed-depth
`${KIPRJMOD}/../..` prefix no longer needs a per-depth copy.

## To 0.44

Nothing to change in a script. Placing keeps the board's hole-to-hole rule
between the drilled holes of different parts and cells whatever their nets
(two cells' ground vias could land closer than the rule), and copper keeps
the hole clearance from an unplated hole whichever of the two moved (a
block could lay a pad over its anchor's peg hole). A searched part or cell
that stood too close before now lands a little further off; a fixed one
that does is refused as any collision is, naming the two holes.

## To 0.43

Nothing to change in a script. A run that fails before it writes the board
(the generator, the script, a firm-placement collision) now leaves the
layout folder as the last run left it, not the unplaced generation; a
critical part left unplaced still writes the board as it stood.

A script can import modules from the folders above it, up to the nearest
`placemat.toml`, and a change to one is a new run. A `sys.path.insert(...)`
a script added to reach shared geometry above it can go.

Routed copper can be kept: `placemat route <script> --adopt NET ...` (or
`--adopt-all`) stores the router's copper on those nets in `<script
stem>.routes.json`, relative to their pads, and every run draws it while the
parts it joins stand as they did. A hand-written fold-back that turns a
routed board into `board.track()` / `board.via()` calls with board
coordinates can go: delete those calls, route, and adopt the nets instead.

## To 0.42

Nothing to change in a script. A parts keepout whose `allow=` names the
parts short enough for the room a case leaves over it can say
`max_height=` instead, once the capture gives each part `Pm.Height`.

`placemat run` no longer deletes files in the layout folder that it did
not write, and copies a board edited in KiCad since its last run to the
run's `kept/` before writing over it. A track's end is now round, as KiCad
draws it, so a clearance finding between a track's end and a pad corner
that KiCad did not report goes away.

## To 0.41

Nothing to change in a script. A grid of vias typed into a pad (offsets from
its centre at a pitch) can become `board.vias(net, PadRef(...), pitch=)`.
`board.pitch()` now measures between pins, a pin drawn as several lands
counting once, so on such a part it answers the row's pitch where it gave the
gap between two lands of one pin. `check current-path` judges the route the
load takes, so a power net that failed on a thin sense or bootstrap branch
can pass. FreeSpot and `--via-near` now keep off unplated holes, and a route
keeps the script's own copper (the router's `--keep-input-copper`).

## To 0.40

Nothing to change in a script. `placemat freeze` now writes an entry as
`Near(PadRef(...).local(dx, dy), radius=0)` with `rotation=Turned(Part(...),
r)`, in the anchor's own frame, and adds to its `why=` the explore run and
score it came from; a frozen item turns with its anchor. Entries frozen by
0.39 or earlier wrote `.offset(...)` in board directions and an absolute
rotation: they stay put only while the anchor keeps its rotation. To move
one to the new form, remove its frozen `at=` and `rotation=` (a `radius=0`
spot gives explore nothing to try), let the search place it with its links,
then `--explore ... --accept` and freeze it again. A lock accepted by 0.39
still holds.

Optional: a fragment that computes its frame from its parts - a helper
that adds up where each body lands when its pad sits at a point, then sizes
the frame and places the main part at the numbers - can use
`board.size(fit=True)`: place the main part at the origin and the rest from
its pads, and drop the arithmetic. Planes with no `outline=` follow the
fitted frame.

## To 0.39

Scripts that place by typed positions - `Location(...)` of numbers or of
named constants, `PadRef(...).offset(...)` copied from a query, `radius=0` -
move to intent as they are touched: a part with its links, searched, its
spot found by `--explore` and kept in the lock; a via by `FreeSpot`, joined
by its tail; a track ending on the via `board.via()` returns. A number from
outside the board (an enclosure or datasheet dimension) stays, as a named
constant citing its source. A position placemat cannot say any other way is
a placemat gap: keep the number with a `why=` naming the gap, and report
it. SKILL.md's check line counts them.

Every `FreeSpot` via now draws its tail to the pad; say `tail=False` for a
via that should stand alone. A via typed as
a pad offset copied from `occupancy --via-near` can become
`board.via(net, FreeSpot(near=PadRef(...)))`, and a track that ran on from it
can end on the via `board.via()` returns. The tail is judged as the drawn
track is, round ends included, and is no wider than its pad (a wide power
class necks down to it), so `--via-near` and a FreeSpot can answer a little
differently from 0.38 beside small pads.

Routing (`placemat route`, `run --route`) left to itself (no `--layers` and
no `route.layers`) no longer hands the router every copper layer: an inner
layer whose own outline a `board.plane()` zone covers at least
`route.plane_share` (0.9) of is left out, so a signal, or a differential
pair's reference side, stops running straight through a plane and getting
flagged against it in DRC. A stamped cell's own zone never counts toward
this, and F.Cu and B.Cu are never left out. The route step prints which
layers it left out and why, and `route.json`'s `plane_layers` names them
too. A board that wants the old behaviour back sets `route.layers` to the
board's full copper stack.

## To 0.38

Nothing to change in a script. A FIXED or EDGE block's satellites no longer
move in the cleanup pass, so a board with such a block can place them where
the block put them rather than where cleanup moved them; copper planned
against them now meets their pads. A board that turned `[cleanup] enabled`
off for this can turn it back on.

A searched item whose `Near` names another searched item's pad is now
placed after that item, block members included, whatever
their tiers: it used to be able to go first and search round the pad's
parked position off the board. A script that gave such items tiers or a
link to force the order can drop them.

Boards run from one directory now each compare with, and reuse, their own
last run: `.placemat/runs/latest-<board>.json` beside `latest.json`, which
still names the last run of any board.

## To 0.37

Nothing to change in a script; placements are the same as 0.36's. A board
that stamps a cell with its own copper zone, on a net and layer the board's
`board.plane()` covers, is written without that zone: the plane fills the
area, and the run prints a `zones` line per cell. Set
`copper.cell_zones_under_planes = "keep"` for 0.36's board.

## To 0.36

Nothing to change in a script. Placements with a differential pair (nets
named as KiCad pairs them, among those `route.diff_pairs` selects; name
only the real pairs there, e.g. `["DATA_*"]`, so a crystal's `XTAL_P`/`XTAL_N`
is not weighed as one) can change: a crossing between a pair's two
halves now costs `score.pair_crossing` (100 mm) instead of `score.crossing`,
so the search and cleanup uncross a pair by a swap or a turn where they
can, and each crossed pair left is a `pair_crossed` finding. Set
`score.pair_crossing` to the value of `score.crossing` for 0.35's weighting.

A net class whose clearance does not fit the pitch of pads its nets land on
(the lane out of a pad, past the next pad of another net, under the
clearance) is a new setup finding, naming the part and the clearance that
fits. It is the same on every run of a board.

## To 0.35

Nothing to change in a script; placements are the same as 0.34's, but for
the first point below.

- A cell is judged against keepouts and the board's edge by its members'
  bodies, not by the box round the whole cell, so a cell whose box crosses a
  keepout or the edge while its parts do not can now be placed there.
- Routing (`placemat route`, `run --route`) routes differential pairs as
  pairs: the router's pair router routes every pair named as KiCad pairs them
  (`_P`/`_N`, `P`/`N`, `+`/`-`) first, at the net class's diff pair width and
  gap, then the router routes the rest around them. Give a pair its class in
  the board's project (a pattern in `netclass_patterns` does), or set
  `route.diff_pair_gap` and `route.diff_pair_width`. A pair the pair router
  cannot route coupled is routed single-ended and listed in the report's
  `pairs`. `route.diff_pairs = []` in `placemat.toml` routes as 0.34 did.

## To 0.34

0.34.0 was tagged but never published (its release checks failed); 0.34.1 is
the release.

Nothing to change; placements are the same as 0.33's, but for the block
below. With the native module, the candidate search weighs whole sweeps
natively (legality, wire, crossings and escapes), so runs and explore are
several times faster. Rebuild the native module after upgrading.

- A block's satellite that has no legal spot on its pin's normal slides
  along the pin row, up to `place.block_gap_reach`, instead of failing the
  block: 0.33 left a block unplaced where two satellites wider than the
  pitch sat on neighbouring pins. Blocks that placed under 0.33 place the
  same.

## To 0.33

Nothing to change in a script. Placements move, and lock entries can
drift: accept again (`--explore ... --accept`) where the lock reports
entries drifted, and check the run's link findings.

- Runs are judged by the run score, one weighted number in millimetres (the
  `[score]` settings), in place of the fixed order placed, DRC, findings,
  airwire. A best recorded by 0.32 has no score and gives way to the next
  run. Explore variants and the bench are judged by it too. Each run prints
  a `score` line by term.
- The search weighs the ratsnest crossings a spot would add
  (`score.crossing`, 4 mm each) and keeps pads' escapes open
  (`score.escape_*`, `place.escape_depth`).
- A block's satellite sits on the normal of its pin's pad row; before, it
  sat on the ray from the anchor's centre through the pin, which near a
  corner put it in front of the next pins.
- The cleanup pass weighs crossings and escapes, may move a satellite off
  its pin's normal within its link's limit or `place.block_gap_reach`, and
  swaps any two neighbouring parts (`cleanup.swap_neighbours`,
  `cleanup.swap_radius`).
- New findings: escapes crossed at a pin row, closed toward what a pad
  joins, and walled off.
- New: `preview --no-tags`.

## To 0.32.2

Nothing to change. With `envelope = "physical"` or `"union"`, a reserved
label is silk to parts placed after it: their silk keeps the board's silk
clearance from the label's box, so a part packed against a label may move
by up to that clearance.

## To 0.32.1

Nothing to change. A lock written by 0.32.0 released every linked item on
the next run; accept again (`--explore ... --accept`) to rewrite it.

## To 0.32

Nothing to change. New: `--explore` on `run` and `preview`, the lock file
beside the script (`<script stem>.lock.json`, commit it with the script),
`placemat lock` and `placemat freeze`. A declaration's script line is
recorded; comments added above a declaration still replay.

## To 0.31

Nothing to change. placemat's version is its git tag now; an install from
a checkout needs the tags (`git fetch --tags`) to report it. The native module installs with placemat's `native`
extra (a Rust toolchain on the machine), and a native module built for
another placemat release is no longer used: rebuild it after upgrading.

## To 0.30

Nothing to change. An optional native module (`native/`, see its README)
makes placement 2.5-4.6x faster with identical results; placemat runs
without it, and `PLACEMAT_NATIVE=0` turns it off.

## To 0.29

- An item on a line (`Location(x, None)`, `Centre(None, y)`) with parts it
  connects to already placed now starts across from them rather than at an
  even share of the line; one with nothing placed to pull it is as before.
- `[place] courtyard_touch` defaults to 0 (was 0.02): each pair of parts may
  overlap by the margins read from KiCad's own courtyards instead, so
  placements pack as tightly as KiCad's DRC allows and no tighter. A part
  whose courtyard stroke is thin no longer produces a `courtyards_overlap`.
- A label stands at least the board's silk clearance off what it names,
  whatever `gap=` or `[label] gap` says; labels move out by that much.
- In the `physical` and `union` envelopes a row or ring gap below the widest
  gap the envelope enforces is raised to it; a script that set the netclass
  clearance as its row gap can drop it.
- A through-hole part no longer claims its whole courtyard on the far face:
  only its holes, and another part's courtyard may not sit over a lead. A
  chip with vias in its exposed pad claims only their copper on the far
  face. Parts can now sit on the back under through-hole parts.
- The first run after upgrading generates the board again: the cached
  generation has no record of its inputs yet. From then on a changed .zen,
  footprint, symbol or stamped fragment regenerates by itself; `--fresh`
  is only needed for something outside those (a toolchain update).
- A script may import a module beside it without touching `sys.path`; drop
  any `sys.path.insert` added for that. Such a module now counts in the run
  id, so the first run after upgrading has a new id.

## To 0.28

- A keepout (or a stamped cell's rule area) with `"parts"` and `layers=`
  naming one face keeps parts off that face only; before, it kept them off
  both. A script that relied on that should list both faces.
- A part in the netlist that no declaration places is now a finding.
- A part searched from its links or round a `Near()` hint, with neither
  `rotation=` nor `rotations=`, is now tried at all four rotations, so parts
  turn and a board re-runs to a different placement. A part whose turn
  matters says `rotation=`; `[place] rotations = "declared"` in
  `placemat.toml` keeps the old behaviour for the whole board. The
  pocket fallback follows the same rule.
- Two satellites aimed at the same anchor pad no longer both take the one
  spot on its axis: the second is refused, naming the first. Aim it at
  another pad carrying the net, or link it to the pad instead.
- Overlap tests catch outlines that coincide (the same courtyard twice, or
  one slid along a side), which some checks read as clear before.

## To 0.27

Nothing to change. `placemat preview` is new: the placement drawn in
seconds, without building the board (see the API reference). Pads no longer
take capacity in the congestion measure, so `metrics.rudy` reads lower where
large pads were; a part not yet placed no longer blocks a pocket, a planned
track or a cutout, which can let a board place parts it could not before.

## To 0.26

- The cleanup pass defaults to 2 passes at a 0.5 mm step (was 3 at 0.25): a
  board re-runs to a slightly different placement, about 1% more wire at the
  median, in about a third of the pass's time.
- A run replays the previous run up to the first changed step
  (`--no-reuse` to resolve everything); the board written is the same.
- Every run prints its most congested cell by RUDY (`congestion`,
  `metrics.rudy`). Nothing steers by it yet.
- Large boards resolve faster, placing the same.

## To 0.25

Searched parts may move after placement: a cleanup pass moves and swaps the
plain searched parts where that shortens their wire and declared links, so a
board re-runs to a different, shorter placement. Parts with a place of their
own, labelled parts and parts another declaration refers to stay where they
were. `[cleanup] enabled = false` gives the placement of 0.24.

## To 0.24

- A block satellite may name the anchor's pad by number - `(Part(...), 20)` -
  where a net would pick the first of several pads carrying it.
- The run id includes the fab profile's values, so every board's next run
  has a new id; the best-run gate goes by the parts, so it is unaffected.
- `measure` adds box edges, pad outlines and mask/paste layers, and flags a
  courtyard inside its own silk or equal to its body.

## To 0.23

Nothing changes in the default `[place] envelope = "courtyard"`, apart from a
new `footprints` line naming each footprint whose silk or pads pass its
courtyard (not a finding). `physical` and `union` are new; switching the mode
re-places every board. fab-profile.json may set
`courtyard.component_spacing_mm`.

## To 0.22

- A declaration with `layout = False` beside the board is no longer taken for
  a board, so a `.zen` with sub-circuits no longer needs the board declared
  first.
- `board.edge(facing, outermost=True)` takes the run lying furthest out that
  way when several face it; a script filtering `board.edges()` for that can
  use it.
- Of two linked items neither placed, the one with less pull toward what is
  placed now waits for the other, so a part is seeded on the one its link
  joins it to. A script whose linked items were each already pulled to placed
  parts is unchanged; a block made only to force that order can go back to
  links.

## To 0.21.1

Nothing to change. Placement is faster on large boards - a 220-part board's
resolve went from about 16 minutes to under 2 - and lands every part where
0.21 did. Two polygons whose bounding boxes only touch are never counted as
overlapping; before, a vertex lying exactly on the other's boundary could
make them so.

## To 0.21

A part or cell that was UNPLACED because its seeded scan found no legal spot
now takes the free pocket nearest what it connects to, and parts placed after
it can move. A board that placed every part is unchanged. `metrics.pocketed`
counts these, and the run prints them. A searched step's note gives its rank
once instead of twice.

The solve no longer crashes on a board that declares a keepout.

## To 0.20

Nothing changes unless you turn it on. `[solve] enabled = true` gives the
searched tier its starting points from a global solve of the whole netlist
instead of from the pads already placed. Off by default: on the board it was
measured on it did not beat the sequential seed on the best-run objective.

The API reference's account of the placement order was out of date: it still
described an item needing more than a quarter of the free board going first,
a rule the rank replaced in 0.6. It now says what the order is.

## To 0.19

Nothing to change. `placemat occupancy` is new: what copper is at a point or in
a box on each layer, and the nearest spot a via can stand and be reached near a
pad, with why every nearer spot failed. `FreeSpot` is new too: a via written as
`board.via(net, FreeSpot(near=PadRef(...)))` lands at the nearest legal spot
once its part is placed.

`polys_overlap` now finds one polygon inside another even when the first vertex
it tests lies on the other's edge. It could miss that case before; edges that
merely touch still do not count. A run that placed cleanly may, rarely, report
an overlap it used to miss - it is real.

## To 0.18

Nothing to change. Every route now checks the copper the router laid against
the keepouts on the board it was given, prints anything inside a region that
forbids it, and keeps it in `route.json` under `keepout_breaches`. The router
honours KiCad rule areas; this makes that a checked fact on every run, so a
region it ignored would be named instead of appearing as one more
`items_not_allowed` among the ones that are there by permission.

## To 0.17

**Keepout zone names gain a layer marker, and a module's keepout now holds on
the parent's inner layers.** A keepout on every copper layer is written
`keepout <name> [*.Cu]`, and one on layers its board lacks lists them. KiCad
saves a zone on the layers its board has, so a two-layer module could never
carry a keepout onto a four-layer parent's inner pours: one declared on every
layer arrived on F and B, and the parent's pours filled under it on the inner
layers.

To pick it up: re-run each module's placemat script so its keepouts carry the
marker, then regenerate and re-run the boards that stamp it. A parent that
restated a module's clearance by hand still works, and now duplicates a region
the module brings; the copy can come out.

A keepout on a layer its board does not have is now a finding rather than a
region that silently holds nothing.

## To 0.16

Nothing to change in a script. Two additions to every run, and a fix to 0.15:

**The design checks run on every board.** `placemat check` was the only way to
get hot-loop, switch-node, keep-out, crossing, current-path and heat verdicts;
`placemat run` now runs them on the board it wrote and prints a `checks` line.
`run.json` gains `verdicts`, and the metrics gain `checks_failed` and
`checks_unjudged`. A board with no `Pm.*` facts says so on that line. A failed
check does not change the exit code, as a DRC violation does not.

**A run made with `--no-drc` is not judged against the best.** 0.15.0 read its
missing airwire and violations as zeros, so such a run became the best
possible one and every measured run after it failed as a regression against
airwire 0. It now reads "not judged", and a `best.json` that already holds
such a run ignores it: the next measured run takes its place.

## To 0.15

**`placemat run` can now exit 1 on a board that placed.** Every finished run
is judged against the best earlier run of the same parts, and a run that comes
out worse is a finding naming the metric and a non-zero exit. A loop or a CI
job that treated exit 0 as "placed" should read the `best` line: exit 1 with
everything placed means worse than before, not broken.

Nothing in a script changes. The first run after upgrading is the first of its
family, so it becomes the best and passes. `best.json` sits beside
`latest.json` in `.placemat/runs/`; delete it to start the comparison afresh.

`[best] airwire_noise` (default 0.01) is how far airwire may move before it
counts. kicad-cli reports a different set of ratsnest edges each run for a
byte-identical board - four runs of the same inputs gave 2868.87 to 2873.11 mm
- so `airwire_mm` and `crossings` wobble slightly between
identical runs. Neither is exact; compare them across runs with that in mind.

## To 0.14

**A `board.link` on a plane net now pulls, so parts move.** It always measured
the distance and reported it against `limit_mm`; it just never contributed to
where the part went. A limit that is measured and reported reads as a
constraint in force and losing to something, not as one that never ran.

Planes stay excluded from seeding for everything nobody declared - a net with
two hundred pads gives a centroid that means nothing - but a declared link
names two specific pads, so that reason does not apply to it. A link is how
to say two parts belong together when the only net they share is a plane.

If a script worked around this with `at=Near(Part(<the other part>))`, the workaround
still wins - an explicit hint beats a seed - so nothing breaks, but the `Near`
is now redundant and can come out. Re-run and expect the parts that were
reported over their limits to have moved toward the pins they serve.

## To 0.13

Nothing to change. `placemat datasheet` gains `--read`, which lists the facts a
sheet could be made to yield with the page, position, channel and confidence
behind each, and `check`, which compares a `.kicad_mod` against values you
supply and says whether the sheet mentions them at all.

A page with almost no text of its own is now read off its render with
`tesseract` when that is installed. It is optional; `--no-ocr` turns it off.
OCR reads wrong as well as right - on one measured sheet it returns 4.95 for a
dimension the drawing gives as 4.55, at confidence 78 against 86 to 96 for its
correct neighbours - so a confidence travels with every sourced number and
`check` against a real footprint is what catches the rest.

placemat does not recover pad geometry from a drawing. On that same sheet the
pads are drawn as hatching: 276 of the land-pattern view's 453 paths are
two-point line segments, and the largest group of equal boxes on the page is
outlined text. Pad values are supplied, corroborated and compared, not parsed.

## To 0.12

Nothing to change. `placemat datasheet <pdf>` is new: it ranks the pages
against land pattern, package dimensions, layout rules and pin map, prints the
evidence behind each ranking, and `--show` renders the page you should look at.
It shells out to mupdf and poppler, which join kicad-cli as tools placemat
expects to find; `tesseract` is used when installed and skipped with a note
when not.

## To 0.11

**Re-run every board and expect it to move.** A footprint that draws no
courtyard now claims its physical extent - pads, silk and fab together -
where it used to claim exactly its pads. Nothing in a script changes, but the
layout a script produces does, and a script that placed cleanly on 0.10 can
report a collision on 0.11.

The old answer understated any part whose body overhangs its pads by the whole
of the overhang. On one measured board, 13 of 43 footprints draw no courtyard,
and the worst claimed 70 mm2 of the 334 mm2 they stand on: the body overhangs
the pads by about 9 mm on one side. Two things read that number, so two things
change:

- **The placement rank.** Searched items are ordered by courtyard area, so a
  large part with no courtyard used to rank as a small one and go down last,
  among the parts it should have been placed before. Expect a different order, and
  read the printed rank rather than reaching for `priority=`.
- **The collision check.** A part under such a body is now a finding rather
  than silence. Those findings are real: a part under another part's body
  does not assemble. Move the part; do not widen a clearance to silence it.

A collision on the first 0.11 run is therefore a defect the old envelope was
hiding, not a regression. `placemat measure <board> <part>` prints the
`courtyard` box a part now claims beside its `body` and `physical` boxes, which
is the quickest way to see what changed for one part.

## To 0.10

Nothing to change. Two commands are new and one has grown, and an agent that
does not know about them will keep grepping footprints by hand.

`placemat parts <board>` lists every part: instance, refdes, face, cell,
courtyard area, pin count, value.

`placemat measure <board> <part> --pads` prints its position, its `body`,
`courtyard` and `physical` boxes, how near it comes to the board edge, and
every pad's number, net, layers, drill, centre and **copper box**. The copper
box is the box round the pad's outlines: for a custom pad the anchor size is
not the copper, and reading the anchor is how a via ends up inside a pad.

`placemat measure <path>.kicad_mod` does the same for a footprint that is not
on a board, with its SHA-256.

Both take `--json`.

## To 0.9

Nothing to change in a script. Two behaviours are stricter and two reports say
more.

**`placemat drc` now refuses a board with no `.kicad_pro` beside it.** kicad-cli
substitutes its own design rules for a board without one, so the report
measured KiCad rather than the board: on a real four-layer board that is 1263
violations against a true 313, including 199 `track_width` items that do not
exist. If you review a board by copying it somewhere, copy the `.kicad_pro` and
any `.kicad_dru` with it.

**A rerun no longer destroys the previous run's route.** A run directory is
named by a hash of its inputs, so a rerun landing on the same id writes a
byte-identical board and the route taken on the old one is still a route of it.
It used to be deleted silently. A run that routes replaces it, as before.

**Footprint defects have their own bucket.** `lib_footprint_issues`,
`lib_footprint_mismatch`, `malformed_courtyard` and `padstack` now read as
`footprint issues N (extents for those parts are unreliable)` instead of going
into `other`. They do not block a board, but placemat's extent for an affected
part cannot be trusted. A reader of `run.json` will find them gone from
`other`; `[drc] footprint_kinds` sets the list.

**A cross-face courtyard finding says why.** `U9 courtyard overlaps R31
courtyard (U9 holds both faces: 4 through-hole pads, none with a net)`. A pad
with no net is usually a footprint defect rather than a real via field.

## To 0.8

**Back-face parts move. Cells do not.**

A flip to the back now mirrors about the vertical axis - KiCad's F key - for a
part and a cell alike, and `rotation=` is applied after it. Before, a lone part
mirrored top-to-bottom while a cell mirrored left-to-right, and the planner and
the writer disagreed about where a part's pads landed by `180 + 2r`, where `r`
is the rotation the generator left the part at.

**Drop any monkeypatch of `Occupancy._transform`.** It was masking the bug for
parts at generated rotation 0 and 180 and creating it for those at 90 and 270.
`grep -n "Occupancy._transform" <script>` finds it.

**A script that compensated by hand cannot be grepped for.** If a back-face
part carries `rotation=180` where the board wanted it upright, it will now be
upside down. Look for back-face parts whose rotation was chosen by trial rather
than from the mechanics, and read the render.

**KiCad's orientation field now reads `rotation + 180`** for a back-face part.
Nothing is wrong: that is what its own flip produces.

A board with no back-face parts is unaffected.

## To 0.7

Nothing to change in a script. Three things get stricter, and one report is new.

**A keepout's `layers=` is now honoured when copper is checked.** A board that
widened `allow=` to silence a complaint about copper on a layer the region does
not cover should take those nets back out: the `allow=` admits them on the
layers that DO matter. `boards/main/Main_layout.py` is the known case.

**A region that hangs off the board edge now forbids.** It used to be discarded
whole, silently, so a script could read as though a rule were in force when it
was not. Expect new findings from a region that was never being applied - they
are the point. A region WHOLLY off the board is now an error, because it
forbids nothing while the script says otherwise.

**A stamped cell's rule areas are no longer deleted.** `pcb layout` copies a
module fragment's regions into the parent, inside the cell's group; placemat
used to delete every rule area on the board before writing its own. A parent
that stamps a module declaring a clearance will newly report parts and copper
inside it. On a board that filled a ground pour under an antenna, that is the
finding that was missing.

**New: the `seeded` line.** It says which nets pulled how many items into
place. One net seeding most of the board means a missing `board.plane()`.

## To 0.6

Read this only if the check in `SKILL.md` matched, or a script fails at import
with `AttributeError: type object 'Priority' has no attribute 'FIXED'`.

### What changed, in one paragraph

`Priority` used to carry four unrelated facts. It now carries one. Whether a
position is decided is `Freedom`, derived from the place you gave it and never
written by hand. Which searched item goes next is a **rank**, worked out from
the item's courtyard area and pin count. Whether failing to place something
stops the run is `required=`. `Priority` is left with `HIGH`, `DEFAULT` and
`LOW`, which a script sets and nothing else does.

### Find the script's legacy use

```sh
grep -nE "Priority\.(FIXED|EDGE)|priority=Priority\.HIGH|priority=Priority\.LOW" <script>
```

Each hit is one of the four cases below. A script with no hits needs no source
change, but read "What moves without you touching anything" at the end.

### 1. `Priority.FIXED` or `Priority.EDGE` on copper

```python
board.via(GND, Location(12.0, 30.0), priority=Priority.FIXED)
board.track(V48, [pad_a, pad_b], layer=F, priority=Priority.FIXED)
```

**Delete the argument.** When a piece of copper is planned is now derived from
its endpoints: copper whose every endpoint belongs to something nothing will
move - a decided part, a cell already down, or plain coordinates - is planned
before the search and becomes an obstacle to it. Copper naming a searched part
is planned after the search.

```python
board.via(GND, Location(12.0, 30.0))
board.track(V48, [pad_a, pad_b], layer=F)
```

The derivation gives the same answer wherever the endpoints were already
decided, which is every case that used to be legal: `priority=Priority.FIXED`
on copper naming a searched part was refused before, so no script has one.

If the intent was "this track wins at a crossing", that is still a priority and
still spelt the same way, but with a level that exists:
`priority=Priority.HIGH`.

### 2. `Priority.FIXED` or `Priority.EDGE` on a placement

```python
board.place(Part("j1"), at=Location(20, 20), priority=Priority.FIXED)
```

**Delete the argument.** This was already refused at declaration time ("the
declaration decided this position, so ... priority=fixed has nothing to
order"), so a working script cannot contain one. If you find one, the script
was never run.

### 3. `priority=Priority.HIGH` to get a big part down early

```python
board.place(Part("l_vbus"), priority=Priority.HIGH)   # a big inductor that kept getting stranded
```

**Delete the argument and run.** This is the workaround the rank exists to
remove. A large, sparsely connected part now goes down early on its own: the
rank scores courtyard area and pin count, so a 31 mm2 two-pin inductor outranks
a shelf of 0402s whatever their net fan-out.

Read the step line before deciding you still need the override:

```
power.l_in   part   rank 19/220   at (32.01, 18.37) rot 0 face back
```

Keep `priority=Priority.HIGH` only if the rank is demonstrably wrong for that
board, and write the reason beside it. It is now a tier **above** the rank,
not a replacement for it.

### 4. `priority=Priority.HIGH` to make a failure fatal

```python
board.place(Cell("mcu"), priority=Priority.HIGH)   # this MUST be placed
```

**Use `required=True`.**

```python
board.place(Cell("mcu"), required=True, why="the MCU has nowhere else it can go")
```

HIGH used to mean two things at once: go first, and stop the run if there is
nowhere to go. It now means only the first. `required=True` means only the
second, works on a decided placement as well as a searched one, and holds even
under `--keep-going`.

**placemat no longer decides on its own that a failure is fatal.** If a script
relied on the old auto-HIGH stopping a run, nothing stops it now: the item is
left off the board, reported as a finding, and the run carries on. Mark the
items that genuinely cannot be left off.

### What moves without you touching anything

**Every board re-places.** The rank replaces the tier, and link pull drops from
the primary sort key to a tie-break, so the order searched items go down in
changes on every board. Expect a large `impact` diff on the first run. Read the
DRC and crossing numbers, not the diff size.

**Copper at literal coordinates becomes an early obstacle.** A track or via
given plain coordinates is now planned before the search, so a searched part's
pads must clear it. This is the intended behaviour and the most likely source
of new findings on the first run. A part that can no longer find a spot is
telling you the copper was always in its way.

**Every run id changes**, because the tool version moved and the resolved
settings joined the hash. The first run after upgrading has nothing to compare
against; `placemat impact <old> <new>` across the boundary still works.

**A run record reader needs updating.** In `run.json`, a step's `priority` is
now `null` for a decided placement, because it has none:

| was | is |
|---|---|
| `steps[].priority == "fixed"` | `steps[].freedom == "fixed"` |
| `steps[].priority == "edge"` | `steps[].freedom == "edge"` |
| `steps[].priority == "high"` | `steps[].priority == "high"` (unchanged: a script said so) |
| nothing | `steps[].rank`, `steps[].rank_of` on a searched placement |
| nothing | `steps[].freedom` on a copper step: which batch planned it |

**A script that monkeypatched the placer.** `_weigh` and `_CRITICAL_SHARE` are
gone, replaced by `Board._rank` and `placemat.ranking`. A patch against either
name fails loudly rather than silently doing nothing.

### While you are here: placemat.toml

Nothing to migrate - a project with no `placemat.toml` behaves exactly as it
did. But the constants a script used to work around by editing placemat, or by
passing a flag every time, now have a home:

```toml
# electronics/placemat.toml
[place]
step = 0.1              # this board is laid out on a 0.1 grid

[check]
ambient_c = 85.0        # was --ambient 85 on every invocation

[drc]
real_kinds = ["clearance", "shorting_items", "hole_clearance"]
```

`placemat settings` prints every resolved value and the file it came from. The
full table is in `api.md`.

## Patterns in older scripts

What a script written for an earlier placemat may carry, and the section
that says what replaces it.

| found in the script | section |
|---|---|
| `priority=Priority.FIXED` or `EDGE`; `priority=Priority.HIGH` to go first or to make a failure fatal | To 0.6 |
| a monkeypatch of `Occupancy._transform` | To 0.8 |
| a `sys.path.insert` to import geometry beside the script | To 0.29, To 0.43 |
| a `Location` of typed numbers, a `.offset()` copied from a query, a via offset from `occupancy --via-near` | To 0.39 |
| a frozen `Near(PadRef(...).offset(...), radius=0)` with an absolute rotation | To 0.40 |
| a fragment frame or main-part position added up from its parts | To 0.40 |
| a grid of vias typed into a pad | To 0.41 |
| `board.track()`/`board.via()` calls with board coordinates folded back from a routed board | To 0.43 |
| a wrapper round the lock API to lock the current placement | To 0.47 |
| a helper computing a position from pad boxes or envelopes; `X()`/`Y()` with offsets | To 0.53.0, To 0.54.0 |
| a part's position worked out from a third part's pin | To 0.54.1 |
| a hand-drawn track from a via row to its pad | To 0.54.1 |
| a via or a waypoint at a pad tip plus the clearance plus half a via | To 0.55.0 |
| a pad offset from another part's pad by half pad widths and a lane | To 0.55.0 |
| a plane outline built from a group's box | To 0.55.0 |
| two parts' positions worked out from a driver's pin at a mechanical pitch | To 0.55.0 |
| `tail=False` on a `FreeSpot` via whose track the script draws itself | To 0.55.0 |
| a pair centreline typed as coordinates | Unreleased |
| a power pour polygon built from pad edges | Unreleased |
| a waypoint on a 45 worked out as x - y or x + y off a pad's corner | Unreleased |
