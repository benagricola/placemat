# The placemat API

What a layout script calls. The command line is `placemat --help`; this is the
Python surface a stage body works with.

Read it before writing or changing a script.

## How a script is shaped

**A script DECLARES; the library SCHEDULES.** A layout script is not a program
that runs top to bottom. It is CONFIG plus stage BODIES, and a body runs when
its stage runs, not where it is written:

    layout, board = context()

    @stage("cells")
    def _cells():
        board.settle_all([dict(inst="buck"), dict(inst="can")])

The stages are fixed and in dependency order - frame, anchors, cells, loose,
copper, drops, repair, silk, report - because each reads what the one before it
left. THE RUNNER OWNS THE ENVIRONMENT: it resolves the board, prepares the
interpreter, reads the config, builds layout and board and saves, so a script carries
no path arithmetic, no `sys.path` insert, no board-path-off-argv and no
construction of either. `context()` at the top of the script names the two the runner
builds - `layout` puts artwork down, `board` is the board - and the raw pcbnew board is `board.b` with
the stamped cells in `board.cells`. Run a script with
`placemat round <board>.zen --label <name>`; it calls the layout runner itself.

**The runner also resolves the PROJECT, and the library is GIVEN it.** Where the
fab profile is, which directories hold the cells and the parts, which boards
exist, where the root is: the runner settles all of it once and the library asks
for it. So nothing climbs the filesystem looking for a `pcb.toml`, and what a
call does no longer depends on where the file making it happens to sit. Two
rules follow, and they apply to a tool you write as much as to a board script:

- **Never go looking for the project.** Do not walk up for a root, do not glob
  for the boards or the cells, do not read the fab profile off a path you
  computed. Ask - the project answers where the root is, which boards there are,
  which directory a cell lives in, and what the fab can do. A second way of
  answering one of those questions is a second answer, and two answers to one
  question in a codebase is how they drift apart.
- **A warning about the fab profile is a RESULT, not noise.** A project with no
  profile says so every time it is asked for a number, and what it hands back
  are somebody's defaults - not this fab's via sizes, via-in-pad minimum or
  courtyard excess. A board laid out through that warning is laid out to rules
  nobody chose. Stop and fix the profile; never render the warning away.

Why it is built this way: left to itself, the order a script's statements
appear in decides which candidate gets scarce room and what board state a
validation is asked about. That is one file doing two jobs - the constraint
list AND the scheduler - and it is where ordering faults come from. So
every order-sensitive operation is either DERIVED from constraints (a
stage's own order) or SCHEDULED by the library at a point defined by its
dependencies. Anything still imperative at a script's top level is a scheduling
decision the file is making by accident.

**A plane drop's legality is decided against the FINISHED board**, and not by
anything a script calls. `purge()` removes the doomed copper, which has to
happen early because a doomed item reads as absent to every geometry test after
it; whether a stripped plane via may STAY needs all the copper drawn, so it is
settled at save. Between the two the via is live, so nothing settles on top of
it. The consequence to recognise: a via that the finished board makes illegal is
REMOVED and reported as an unlanded drop, where the old order left it in place
and the short turned up in DRC with nothing naming its cause. An unlanded drop
is outstanding work with an address; a short is a puzzle. Neither the removal
nor the decision is yours to call - do not add a `drops` body to do it by hand.

Two consequences worth stating because they are easy to get wrong. Within a
stage the order bodies run in MUST NOT MATTER, and that is tested rather than
promised: the shuffle gate permutes registration and requires the same board. A
stage whose bodies do not commute is a stage boundary in the wrong place, and
the answer is another stage, not a convention about where to write things. And
a stage body is NOT a hand-rolled helper - it is the format, so the script
linter passes it by; what it still flags is a genuine local mechanic inside a
body.


## Layout-script shape

**`references/scaffold_layout.py` is the shape.** Copy it to start a script,
and migrate an existing script to it (SKILL step 0). It carries the
config/mechanism split, the section order, and a library call wherever a script
is tempted to hand-roll one; the sketch below is the same shape in miniature.
When the format changes, change the scaffold first - a format that lives only
in the last script somebody touched is not a format.

A layout script is idempotent against a freshly generated board file: it sets
every placement, then adds every piece of copper. Structure it as data + intent:

```python
# STACKUP (from the board's design, restated here because it decides the rest):
#   4 copper layers - F.Cu signal, In1 ground plane, In2 rails, B.Cu signal.
#   Ground and the planed rails are drops into their plane, never tracks.
layout = ModuleLayout(path)            # the drawing layer (see pattern below)
for ref, x, y, rot in PLACEMENTS:    # per-line comment = the constraint, not the history
    layout.place(ref, x, y, rot)          # grid=0.05 when a pin axis demands it
layout.poly(net, PTS)                     # power pours; pad_margin_mm=None if hand-final
for seg in TRACKS: layout.track(*seg)     # width by net role
layout.stitch("gnd", refs=[...])          # plane hand-off
layout.drop_via(ref, pad, net)
layout.refs_to_fab(); layout.save()
```

If the project has a layout-helper module, use it. Otherwise implement the
pattern: `place` (grid-snapped, default 0.1mm), `poly` (filled gr_poly carrying
a net; by default swallow any same-net pad the outline touches, grown by a small
margin, so no pad edge pokes out; `pad_margin_mm=None` applies the outline raw
for hand-final shapes), `track`, `via` (defaults from a fab profile),
`drop_via` (via-in-pad if the pad's smaller dimension clears the fab minimum,
else a short stub to a via in open copper), `stitch` (drop_via on every pad of a
net), `refs_to_fab` (move refdes text to the fab layer, nudged clear of pads).

Fab capabilities reach the library through the PROJECT (`placemat.project`):
the runner resolves it once and calls `project.use()`, and every via default,
via-in-pad minimum and courtyard excess is read from it at the point of use. It
is never discovered by climbing the filesystem and never read at import, so the
same call means the same thing wherever it is made. A project with no profile
reports that fact on every request rather than substituting quietly.

Fab capabilities (via sizes, via-in-pad minimum pad size) belong in a project
fab-profile file, not hardcoded.

The header docstring states what the cell or board IS and the structure that
makes it work: the anchor, the blocks and why they sit where they do, the
copper contract, the floors, and the regeneration command. It is not a
changelog - see the comment rule in SKILL.md's script discipline. A line
comment answers "why is this value this value": name the pad, courtyard,
lane, package pitch or datasheet rule that fixes it. `x = 21.35` needs
"on the VIN pin's axis, so the serve is one straight trace"; it does not
need "moved 0.7 east last round".


## Board-level primitives

A board script stamps cells, threads loose parts between them and re-drops the
plane vias the cells gave up. Those primitives are a shared library, never
private code in a board script: in this project `placemat.board_layout`
(`BoardLayout`), on REAL geometry. Stamp a cell with `stamp(name, x, y, rot,
bottom=, anchor=, strip_plane_vias=)`; settle a turned cell by translation
with `settle_shift` (the rotation fallback of `settle_cell` can return the
un-turned cell); thread a loose part with `place_free` (far-face holes by
their land radius, courtyards, silk, live copper, the outline keep-in);
`compact` slides a cell until real geometry stops it; `purge` removes the
doomed copper and keeps every stripped plane via whose spot is clear on both
faces.

**A group whose members derive from an anchor gets `place_block`, never a
coordinate.** Pass `build(anchor_footprint)`, which positions the satellites off
the anchor's REAL pads and returns them; it is called at every candidate pose,
so it must derive everything and assume nothing. Legality is each member against
the board with the block's own members excluded, and the score is the whole
group's airwire. The trap it removes: with no primitive for a block, it gets
written at a fixed x/y - and a coordinate cannot give way, so it silently
outranks every cell settled after it and they read as "no fit" while in fact
being displaced. Order is cells, then blocks, then loose parts (SKILL.md round
step 5).

**Copper the script draws AFTER placement is invisible to placement**, and there
is more of it than there looks: the cells' escape fans, the rails and bars, and
the plane drops - including a via-in-pad on a cell pad, which is a hole that has
not been drilled yet. Three answers, chosen by WHEN the copper's position is
decided, not by what it is: known before placement -> `reserve(x0,y0,x1,y1,
layer=, why=, allow=)` a band, naming the nets it carries so the rail's own bulk
cap is still allowed onto the bar that feeds it; decided by where the parts
landed -> a repair pass (`resettle_free`) that re-runs the same legality test and
moves only what actually broke; decided after that -> it has to be seen by the
check, not repaired around. Repair passes are not free: run one after the plane
drops and it strands the drops of anything it moves, and carrying those vias
along moves HOLES, which need hole-to-hole clearance the pad test never
validated. Prefer making the copper visible.

**`purge()` empties the doomed list.** A kept re-drop is live copper; leaving its
UUID on the list makes it invisible to `_doomed_uu()`, which every later geometry
test consults - `_through_points`, `_face_copper`, `drop_ok`, `stub_ok`,
`redrop_ok`, the repair pass. A part settled on top of one reads legal until DRC.
If a guard you have proved correct says a pose is illegal and the placer put a
part there anyway, suspect what the guard could SEE at the time, not its logic. `cell_clash(name)` names the first real touch (courtyard, hole on a
foreign pad, copper within clearance); a bounding-box overlap is not one.
Before writing any collision test in a board script, look here and in the
geometry oracle; a placer built on bounding boxes and via centres reports
"clear" for placements the gates then fail by the dozen.

The same library carries the rest of a board round, so a board script never
grows a private version: the outline (`outline_chamfered`, `outline_rounded`,
`edge`, `arc`), edge placement (`hard_edge`, `group_hard_edge`, `edge_align`,
`mounting_keepout`, `content_extent`), rows (`place_row`, `row_clear_of`,
`tp_row`), knockout labels (`label`, `label_at_part`) and board pours with
their foreign-pad check (`pour`, `assert_pour_clear`). The cell-level class
adds the 45-degree drawers (`l45`, `route45`), the two-pin placer that derives
rotation from real pad geometry (`place_two_pin`) and the pad lookups
(`pad_box`, `pad_of`, `pad_net_xy`); cross-cutting geometry (`overlap_depth`,
`clip_segment`) lives in the geometry module. Call these directly - no
local alias, no wrapper that only renames. Construct the board object where
the board size is known (a locked frame is known up front; a computed size
is known after its pass).


## The small verbs

These exist because every board was writing them by hand, differently. Each is
one line at the call site and none of them decides anything - they measure, or
they layout what the script tells them to.

- **`board.pad_xy(inst, key)`** - a pad's (x, y) on an INSTANCE, by pad number or
  net name. Reach for it whenever a script has an instance path and wants a
  coordinate: everything else on the board addresses parts by instance, because
  that is what survives a schematic edit, so converting to a refdes to ask about
  a pad is a step backwards.
- **`board.label(..., align="bottom"|"top")`** - what the given y MEANS for a
  label. Use it for any ROW of labels: centring a vertical label starts a long
  marking lower than a short one, so a row of centred labels does not line up.
- **`board.clear_of(item, box, gap=, side=)`** - move a placed label or marking out
  of a box it landed in, or say it was already clear. This is a REPAIR after
  both things are down, which is the only time the collision is knowable; force
  `side` when the direction is a decision (a label belongs west of the block it
  names), leave it out for the shortest escape.
- **`board.silk_line(...)`** / **`board.note_rect(...)`** - a line or rectangle on a
  non-copper layer: an isolation barrier a person must see on silk, a shadow or
  a reserved volume on a documentation layer. Draw a region as a note when the
  reader needs to know WHY it is empty; layout it as a `rule_area` when the board
  must be stopped from filling it. They answer different questions and a region
  often wants both.
- **`board.mockup(ref, model, x, y)`** - a render-only footprint carrying only a 3D
  model, marked board-only and out of the BOM and position file. For a part the
  board must make room for and a reviewer must SEE in the iso render, that no
  netlist carries: a plugged module, a mating connector, a case boss.
- **`chain_by_nets(board, nodes)`** - the parts of a series chain, resolved by
  the nodes between them (`["24V", "LED_MID", "LED_A", "GND"]` -> ballast, LED,
  return). A chain's parts are ordinary passives whose refdes churn; the nodes
  do not.
- **`lay_along(seq, start)`** - one-dimensional packing: `[(name, width,
  gap_after), ...]` in, centres and the end position out. Any row or column of
  parts, labels or blocks. Written by hand this is where an off-by-a-half-width
  lands.
- **`point_in_rects(x, y, rects)`** - is a point inside any of these regions? The
  list form, because a region a board cares about is usually several rectangles.


## Placement by link weight

A proximity constraint belongs to a connection (SKILL tactic 2a), so the
harness records connections. `layout.link(a_ref, a_pad, b_ref, b_pad, weight, why=,
limit_mm=)` declares one. It annotates connectivity the netlist already has:
it creates no net, changes no pad and draws no copper, it only says what a
millimetre on that connection costs the placement search.

`weight` is that cost, a `LinkWeight` member or a number. The enum is a float
enum - `LinkWeight.SHORT` (10: the link IS the behaviour), `PREFER` (1: shorter
is tidier, nothing degrades) and `FIXED` (0: mechanics decided an endpoint, so
the connection asks for no adjacency) - so a member IS its number and the named
and numeric forms take one code path. The scale is relative to PREFER = 1: 3
means this connection is worth three ordinary ones per millimetre, for a case
between two names (a serve that should beat the ordinary pull without
outbidding a hot loop). Anything that is not a member or a finite number >= 0
is rejected at the declaration. Undeclared links weigh 1, which is what every
link weighed before weights existed - declaring nothing changes nothing.

The declaration lives in the layout script rather than the `.zen`, because as
of pcbc 0.4.47 nothing in the language can carry it to layout: `Net()` takes
only name/voltage/impedance, NetClass carries width/clearance/diff-pair rules
and not adjacency, and a `properties` dict passed to a module INSTANCE reaches
neither the netlist nor the board (verified on a stdlib generic). Only a
property set inside `Component()` survives, as a footprint field with the key
normalised (`LinkNote` -> `Linknote`) - and that is the shared part wrapper,
which is the wrong scope for "this instance serves that pin". A layout-side
call also resolves both endpoints against real pads and raises on a typo,
which a property string cannot.

Each end's net is recorded with the declaration. A mistyped pad number almost
always lands on a different net, and a link that legitimately spans one (a
Kelvin tap across a sense resistor) then still reads as deliberate.

Endpoints are recorded against each footprint's instance path, not its refdes,
and a cell's declarations are written beside its fragment as `links.json`. A
board picks them up with `adopt_links(cell)`, which maps the fragment's paths
through `<instance>.<path>` the way the derived clearance floors do, so a cell
carries its own constraints onto every board that stamps it.

Three things then use them. The objective prices a declared link PAD TO PAD and
multiplies by its weight, instead of pricing every shared net alike -
`_net_anchors`' existing plane-net exclusion is the same idea (a net reachable
from anywhere by a via constrains nothing) and now reads as the zero-weight case
of the general rule. `by_link_priority(insts)` returns the instances holding the
heaviest links first, for the loose-part stage. And every save writes
`links-achieved.json` beside the board: each link with the length placement
actually reached, heaviest first and worst first within a weight, and
`over_limit` where a declared `limit_mm` was missed. The pass runner reports the
heaviest tier and fails on a missed limit.

Two more queries answer the questions that otherwise get hand-written per
session. `in_region(x1, y1, x2, y2, layer=, net=)` returns every copper item
meeting a rectangle - what is in this corridor, what would a part here collide
with, which cells own copper in this band - each as name, net, owning
footprint, layers and box. `outside_outline(margin=)` returns copper sitting
outside the board edge, worst first: a stamped cell whose fragment origin never
moved, a via a purge left behind. Both are ordinary items to DRC, which has no
opinion about the outline, and both are invisible in a render framed on the
board.

Modules and boards share this: a fragment is a board file, so the oracle,
the airwire measure and the pack/settle machinery all run on it. The one
thing a module knows that a board does not is its boundary: the nets it
declares as `io()` are the board's, everything else is the module's to
close. `ModuleLayout.io_nets()` reads that list from the .zen beside the
fragment, `ModuleLayout.airwires()` splits the open nets by it, and a cell
script may assert that its internal open list is empty before it saves
(`check(allow_open=io nets + the plane drops)`). On a board, the oracle
derives the same boundary from the stamped group: a net with items both
inside and outside the cell is external.


## The ratsnest as a number

The oracle's `airwires()` is the ratsnest measured (KiCad's own edges are
not readable from Python): per net, a minimum spanning tree over the net's
copper clusters, each edge the shortest gap between two clusters. It returns
the count (KiCad's unconnected count), the total length, the crossings
between airwires of different nets, the per-net lengths and a per-owner
table - a stamped cell or a loose part - split into INTERNAL edges (both
ends in the owner: the cell has not closed its own net) and EXTERNAL edges
(what the board must layout). `cell_nets(cell)` gives the same split at the
net level. `placemat airwires` prints it for any board or fragment, and the
placement pass records count, length, crossings and the top external cells
every run, so a move shows its effect before the trial is spent on it.

The scoring option: `place_free(..., score="airwire")` and
`settle_shift(..., score="airwire")` search the whole radius and take the
clear pose whose airwires are shortest (the part's pads, or the cell's
external nets, to the nearest same-net copper outside it), ties to the
smallest move; both print the hint's cost and the chosen cost. Without the
option they still take the nearest clear pose. `facing(cell, x, y)` is the
side test on the same handoff points.


## Diff pairs

KiCad pairs nets by name (`BOARD::MatchDpSuffix`): scanning backwards it skips
digits/underscores, then requires `P`/`N` (uppercase) or `+`/`-`; the complement
net (same string, token flipped) must exist. `FOO_P`/`FOO_N` pairs; `FOOH/FOOL`
or lowercase does not. Hierarchical prefixes are fine (`mod.BUS_P` pairs with
`mod.BUS_N`). Set diff-pair width/gap via a net class. A termination's internal
nets are series bridges across the pair - single-ended by topology; give them
the pair's net class so trace widths match at the seam.


## Placement search on two-sided boards

- A hole's far-face reach is its LAND, not a via's: an M3 mounting pad is
  6.4 mm across, a connector shell post 1.2 x 2.0, an NPTH peg its drill. A
  loose-part search that treats every hole as via-sized settles parts onto
  annuli. Carry the land radius with each through-point.
- Place every fixed anchor (connectors, probe rows, mounting holes) BEFORE
  any cell search runs: a search cannot avoid what does not exist yet.
- A settle helper that retries a failed ring search at +90 per turn hands a
  rot-180 hint back UN-turned after two failures (180 + 180 = 0), silently.
  Stamp turned cells at an exact, measured position and print the clash
  reason instead of searching.
- Check foreign holes against the cell's pads as well as the cell's holes
  against foreign pads; the asymmetric check misses an M3 annulus under a
  cell's jumper pads.
