---
name: placemat
description: Use when laying out a KiCad board or module with placemat - writing or changing a layout script, placing parts, declaring tracks, vias, pours or planes, reading a run's DRC, findings, score or impact, routing, or bringing an older layout script to the current placemat. Also use for circuit design or capture (.zen, Pm.* annotations) of a board placemat lays out.
---

# placemat

**Doing circuit design or capture, not layout?** Read
`references/capture.md` (the `Pm.*` annotations a capture carries, how part
wrappers forward them, and what `placemat check` reads from them) and skip
the rest of this file: it is about writing layout scripts.

placemat lays out a KiCad board from a Python script. `placemat run
<script>` generates the board, runs the script, writes the KiCad file, runs
DRC and renders, and records what happened. A run takes seconds once the
board is cached, and its record and its impact against the previous run are
how a change is judged, so try placement decisions and measure them.

## References

- `references/api.md` - the script surface and the commands. Start from its
  two indexes: "Say it by intent" (what you mean -> the form that says it)
  and "Read the board" (a question -> the command that answers it), then
  read the section the index names. The file is too long to read whole.
- `references/migration.md` - what changed for a script, per release,
  newest first.
- `references/capture.md` - the `Pm.*` annotations placemat's checks read.

## Declare by intent

A script says where each part and each piece of copper goes relative to
what it stands against - a board edge, a row, the pin it serves, a lane
past other pads, a pin row's lanes and vias (`board.escape`), a keepout,
another part - and placemat works out the coordinate. A script that
computes its own positions is a coordinate file that placemat happens to
read.

A script must not:
- do arithmetic on a coordinate to decide where a part, a via or a track
  goes: `X(ref, computed_offset)`, `Y(ref, computed_offset)`, a `Location`
  or a `Centre` built from a sum or a difference;
- read a pad's box, a part's envelope or its claim (`board.pad(...).box`,
  `board.envelope(...)`, `board.claim(...)`) into a number and place
  against it. Those answer questions: a check, an `assert`, a constant that
  states a mechanical fact;
- keep a helper whose job is turning a pad position into a placement
  number (a `beside()`, a `put()`, a frame that tracks where things will
  land). The same arithmetic written twice means the form has not been
  found yet.

A number from outside the board - an outline dimension, a connector's pin
pitch, a datasheet clearance - is a fact: name it once as a constant with a
one-line source. Arithmetic that combines facts into another fact (a total
width from two datasheet numbers) is fine. A number that says where a part,
a via or a track goes is a decision typed by hand: nobody can re-check it,
it goes stale when a part, a footprint or the board changes, and the next
session copies it.

### Finding the form

placemat's forms compose, and the relations a board needs are usually one
form or two together. Before deciding a relation cannot be said:

1. Say it in words: what the item stands against (a board edge, a part's
   side, a pad, a lane, other copper, a keepout) and what fixes each axis.
2. Find it in api.md's "Say it by intent" index, then read the section the
   index names, parameters included. Grep api.md for the words of the
   relation as well (`lane`, `pitch`, `across`, `over=`, `cover`, `fit`).
3. Compose: one form for the side, another for the other axis; the value
   one call returns as a point or an item of the next.
4. Read the newest sections of `references/migration.md`. Each release's
   section has **New** (forms and tools it adds), **Migration steps** (each
   with the old coordinate or hand-computed form beside the intent form that
   replaces it, as code) and **Fixed**. When upgrading, apply every
   migration step that matches the script, and look through New for forms
   that replace a coordinate or a computed number in it.

The forms that most often answer "placemat can't say this":

- `at=Beside(item, side, align=)` stands a part a gap off another part, a
  cell or a keepout; `align=` fixes the other axis: an `Along`, a pad of
  any firmly placed part (level with a third part's pin), or
  `(own_pad, Past(pads, edge, lane=Net(...), width=))` - its pad a lane
  past other pads, as wide as the lane's current needs.
- `board.row(items, edge, of=Part(...), centre=PadRef(...), pitch=)`:
  items along a part's side, at a mechanical pitch, centred on a pad.
- `Between(pad, pad)` and `Past([pads, vias, tracks], edge, across=)` are
  track waypoints: through a gap, or the clearance off copper on a pad's or
  via's centre line; `Past(items, Corner.NE)` holds a 45 the clearance off
  a corner. `board.via(net, at=Past(...))` stands a via there.
  What `board.via()` and `board.vias(net, along=PadRef(...), count=N)`
  return is a track point (a row's farthest via); those and what
  `board.track()` returns are `Past` items in later copper.
- Copper over pads and parts: `board.pour(net, [pads], swallow_pads=True)`
  is fitted round other nets' copper, holding the pads' copper, written as
  a graphic polygon (`cover=` and plain points are refused); a pour of
  points or `cover=Cover.HULL`/`BOX` is drawn as declared; two pads make a
  neck (`width=`); `board.finger(..., width=PadRef(...))`;
  `board.plane(net, layers, over=[parts])`; `board.stitch(net, region,
  edge=True)`; `board.keepout(Part(...), name, margin=)`.
- `at=Pin(key, x, y)` or `Pin(key, point)` stands a part's own pad `key` on a
  point; the point may be a `PadRef(..., edge=)`, which puts the pad against
  that pad's edge (a cell takes a member's pad as `key` too);
  `rotation=Turned(part, deg)`; `bend=Bend.START`;
  `board.rect(fit=Axis.X, height=)`;
  `board.pair(p, n, [(pP, pN), (pP2, pN2)])`.

### When no form says it

When that search finds no form and no composition that says the relation,
do not hand-compute it. Send it as a request to the agent working on
placemat itself (the session in placemat's own repository), which files it
in placemat's `BACKLOG.md` and replies. The request gives:
- what was needed;
- the forms looked at, and why each does not fit;
- what placemat could offer.

A request that names no forms searched is not finished. Do not keep a gaps
file of your own; if no placemat session is running, tell the user.

A coordinate is an escape hatch, and only the user opens it. Before writing
one, ask with AskUserQuestion:
- name the request and the forms searched;
- give the number you would write and what it pins;
- offer the alternatives: leave the item searched as declared, or leave it
  unplaced until placemat can say it.

Write the coordinate only on the user's explicit yes. That yes covers that
one declaration, not the next one, and not the same gap on another item.
Then name the request (its backlog title) in a comment beside it, and use the smallest number that
works.

A coordinate with no comment naming a gap, or with no approval behind it,
is what this section forbids. Being unable to say a relation is not
approval, and neither is an earlier approval for something else.

`board.figure` is allowed without that approval only for a datasheet's
dimensioned layout, its `why=` citing the figure; any other use is a
coordinate escape hatch under this rule.

`reach=mm` on a fitted pour is a distance in place of a fact (the net's
current), so it is an escape hatch under this rule too: ask, name the
request, and write it only on the user's yes for that one pour. Where the
net's current is known (`Pm.I` on the parts that carry it), the form is
`reach=Reach.CURRENT`: the pour grows only as far as that current needs.

`placemat freeze` writes coordinates into a script, and that is placemat
recording its own result: `--explore`/`--accept` and `freeze` write what a
search decided - `Near(PadRef(...).local(dx, dy), radius=0)`,
`rotation=Turned(...)` - in the anchor's frame, with a `why=` naming the
run. Never copy the shape of a frozen line into a new declaration: a
`Near(..., radius=0)` you write yourself pins a spot nothing searched for.

## An existing script

Check it against the current API before touching it:
`grep -nE "Priority\.(FIXED|EDGE)|priority=Priority\.(HIGH|LOW)|Occupancy\._transform|board\.size\(" <script>`.
Any hit, or `AttributeError: type object 'Priority' has no attribute
'FIXED'` at import, means it was written for an earlier placemat: fix those
lines first. A monkeypatch of `Occupancy._transform` comes out, and
`board.size(` becomes `board.rect(` (same arguments; the old name still works
and raises a `setup` notice). Read
`references/migration.md` from the script's version up; its last section,
"Patterns in older scripts", names the section for each hand-written pattern
a newer form replaces. A script with no hits still re-places on a newer
placemat; migration.md says what moves.

Then count its typed positions, and read its module-level numeric
constants:

```
grep -cP "\.local\(|\.offset\(|radius=0\b|\b[XY]\((?:[^(),]|\((?:[^()]|\([^()]*\))*\))+,\s*[^)]+\)|Location\(\s*[-\d]|Centre\(\s*[-\d]|board\.(claim|extent|envelope|reach|pad)\((?:[^()]|\([^()]*\))*\)[.\w]*\s*[-+*/]" <script>
```

It counts `.local(`/`.offset(`, a frozen `radius=0`, an `X()`/`Y()` with an
offset (`X(Part("u1"), 3.4)`, nested in a `Location` or not), a literal
`Location`/`Centre`, and a measurement feeding arithmetic on the same line. A measurement assigned to a variable
and used further down does not show, so read the file for that too.
Working in such a script:

- Write every new declaration by intent, whatever the lines round it do.
- Convert the coordinates you touch. A part placed by numbers becomes a
  searched part with its links; `--explore` finds its spot and `--accept`
  keeps it in the lock. Copy nothing from `measure`, `occupancy`, a lock or
  a routed board into the script.
- A frozen line or a logged gap already there is a record, not a license:
  convert what you can, and add to a gap only while it is still needed.
- Migrate the escape hatches:
  - For every coordinate that carries a gap comment, read the gap's entry
    and the sections of `references/migration.md` newer than the entry.
  - Where a form now says the relation, replace the coordinate with it,
    and mark the gap entry resolved with the placemat version.
  - A coordinate whose gap is still open stays only with the approval it
    was written under; one with no approval behind it goes back to the
    user as a question.

## A fresh board

Do this before writing a line of the script; the script translates this
model into declarations.

1. **Read the board `.zen`**: every instance, every net, the net classes,
   which nets are planes, each cell's `io()` ports, which parts are
   connectors and which edge or face their mating side needs.
2. **Read each cell's layout script**: its docstring is the cell's intent
   (what it is, which side is outward, what continues at board level).
   Read the datasheet layout section of every active part that has one.
3. **Build the electrical model.** Classify every relationship:
   - high-current paths, source to consumer: short, wide copper, no vias
     in the path;
   - switching loops (the switch, its return, its decoupling): small area;
   - sense and Kelvin paths: at the pin, nothing between;
   - length-sensitive signals: matched or tuned pairs, clocks, fast buses;
   - isolation boundaries: what may not cross what;
   - ordinary signals whose off-board length dwarfs the board: an
     isolated input's connector need not sit at its isolator;
   - mechanical facts: mounting patterns, case windows, a sensor whose
     position is its function;
   - field and heat sources (a magnet, an inductor, a hot converter) and
     the parts sensitive to them (a field sensor, a crystal, a thermistor):
     add the annotations to the schematic capture (the `.zen`) as the
     board is modelled - `Pm.Emits` and `Pm.EmitsAt` on each source,
     `Pm.Limit` and `Pm.SensesAt` on each sensitive part
     (`references/capture.md`, "Sources and limits") - and placemat pairs
     them with no script line. `board.push` is for a source no footprint
     carries (a point in the enclosure). A part placed to measure a source
     (a temperature sensor beside a converter) carries no limit for that
     kind; keep it close with `Near` or a link;
   - a cell is placed as one rigid piece; when its parts want different
     places, the capture's cell boundary is wrong for this board - a
     job joined to the rest only through board-level nets, or a cell too
     large or the wrong shape for the room its tightest part needs. Say
     so, and propose the split, or the move of parts between cells, as
     a change to the capture; do not work round it in the script. The
     `split` finding lists cells whose parts form separate groups; a
     refused cell is the other signal.
4. **Write the proposal as the script's opening comment**: which edge each
   connector takes and why, which positions are mechanical points (`fixed`)
   and which a distance along an edge (`edge`), which cells cluster with
   what, which items must place (`required=True`, with the reason), where
   the corridors are, and which constraint outranks which. Say which
   relationships are about current and heat and which about signal
   integrity. Copper order follows from its endpoints; do not plan it.
5. Only then declare.

## The loop

1. **Before any placement on a board, establish the facts.** Run
   `placemat facts <script>`. For each fact it marks unconfirmed or
   flags, ask the user with AskUserQuestion: layer roles and copper
   weights, pair nets, via types and their tier, fab minimums, the rise.
   Write each answer in its home (see "Where a change goes" below): the
   stackup and pair classes in the .zen, fab facts in fab-profile.json,
   the rise in placemat.toml. Regenerate, then run `placemat facts
   --confirm`. Never proceed on a default, and never write a fact the
   user did not give.
2. **Run** `placemat run boards/<x>/<X>_layout.py`. Read the stream:
   placed/copper/findings, one DRC line, the impact, a `score` line and a
   `best` line (`-v` prints every step). **A run that exits 1 having placed
   everything came out worse than the best earlier run of the same parts**:
   the `best` line and the finding name the term. The best arrangement is
   in `.placemat/runs/best.json`; the edit just made is the one that lost
   ground.
   Under a critical or warning finding a `try <id>: ...` line is a suggested
   change to the script (`run.json`'s `finding_details[i].suggestions` has
   them all, with the edit as data). `placemat apply <id> --dry-run` prints
   its diff, `placemat apply <id>` writes it, `placemat apply --undo` puts
   the last one back. A number a suggestion writes is a named constant with
   a comment saying where it came from: keep the comment. The run after it
   says whether the finding cleared (`api.md`, "Findings and severities"). In the studio each finding row
   shows its best suggestion with Show (the diff), Try (the edited script resolved and compared, nothing written:
   did the finding clear, what else moved) and Apply; to check a suggestion without writing it, ask the user to Try
   it there, or `POST /suggest/try` (`api.md`, "Studio").
3. **Between runs, look with `placemat preview`**: the same placement in
   seconds, drawn, without the write, DRC and render. A whole board
   answers layout questions (free space, a cluster, a red over-limit link,
   the congestion hot spot, what did not place) but comes through at a few
   pixels a millimetre; for small passives draw `--around <part>` or
   `--zoom` and aim for 20 px/mm (40 for 0201s; set `[preview] model_edge`
   to what your model sees). Gaps are numbers - `measure`, `occupancy`, the
   findings - not pixels. To let the user watch a series of edits live, tell
   them to run `placemat studio <script>` (or `placemat studio` alone, to pick
   a layout script in the page); it re-resolves as the script changes and has a
   Run button for a checked run (`api.md`, "Studio").
4. **Before reading a board's numbers, run `placemat settings`**: a
   `placemat.toml` anywhere from the board's directory up can change any
   value, and the command says which file each came from.
5. **Read the numbers before the picture.** `real` DRC buckets and
   `unconnected` are the gate; `outstanding` is copper not yet drawn;
   `footprint issues` are defects in the fetched footprints (they do not
   block a board, but placemat's extent for those parts is then
   untrusted). Each finding prints as `[critical]`, `[warning]` or `[notice]`,
   most serious first: critical means the board cannot be built or fully routed
   as it is (an unplaced item, conflicting copper, a pad walled in); a warning
   is a quality issue to fix or judge; a notice is something placemat did by
   design (a via shared or moved) that you may want to know. `airwires`, `crossings`, `crossings by net` and `congestion`
   say how hard the board will be to route before any routing: keep the
   change that cuts crossings and congestion, and move the parts on the
   nets with most crossings. The `score` line weighs everything in
   millimetres of wire against the best run; the term that moved most is
   where to look. Two firm placements that collide stop the run: fix the
   declaration. A crossed or walled escape left after the search is a
   placement to change by hand (a swap, a satellite's pin,
   `board.fanout()`, or `board.escape()` to keep named pins' lanes). An
   `escape_lane` finding names what blocks a declared lane. A
   `pair_crossed` differential pair must exchange sides to route coupled:
   swap two interchangeable parts on it, or turn a part whose pinout is
   mirrored, before routing. A net class whose
   clearance does not fit a part's pad pitch is a setup finding: fix the
   class, or give those nets their own, before routing. A `facts:
   unconfirmed` line and a `facts` finding mean step 1 was skipped or the
   board changed since: go back to it.
6. **Read the `seeded` line**: which nets pulled how many items into place.
   One net seeding most of the board is a missing `board.plane()`: an
   undeclared plane net pulls every part on it to one centroid.
7. **Look** at `layout/<X>/layout.png` (and `layout-bottom.png`) only after
   the numbers say the change did what you meant.
8. **Change one thing, run again.** The impact says what moved and which
   numbers changed (`placemat impact <run> <run>` compares any two). "Nothing
   moved" when you expected movement means the change was not where you
   thought.
9. **Route only when the placement has settled** - crossings and
   congestion no longer falling, big parts no longer moving:
   `placemat run ... --route` or `placemat route <board>`. It routes a copy
   and reports closure; `still open` names the next placement problem. The
   routed copy is evidence, not the layout: never paste its coordinates
   into the script as `board.track()` calls. To keep what the router found,
   `placemat route <script> --adopt NET ...` stores it relative to its pads
   (api.md, "Keeping routed copper").

**Where a change goes:**

| To change | Edit |
|---|---|
| A fact about the board (stackup, layer roles and weights, net classes, pair nets, design rules) | The .zen (`BoardConfig`) |
| What the fab can make, and what the price allows (via types, fab minimums, courtyard excess) | fab-profile.json |
| How placemat searches, scores, cleans up, grades DRC or tunes the router | placemat.toml |
| What the layout intends (placement, copper, planes) | The layout script |

A run's full record is `.placemat/runs/<id>/`: `run.json`, `script.log`,
`drc.json`, `generate.log`, `layout.kicad_pcb`, and `route/`. Read a log's
tail, not the whole file. Never edit `layout.kicad_pcb` by hand as the fix:
the script is the layout, and a hand edit is a measurement to fold back into
the script.

### Watching a long command

`run`, `preview` (an `--explore` especially) and `check` can take minutes. Each listens, while it works, on a
socket in the project (`.placemat/sockets/<pid>.sock`) and streams what it is doing: the step it is on, the plan so
far, each explore variant's score. To run one without blocking yourself, start it detached (a background shell with
its output to a file) and follow it:

```
placemat watch                # every command running in this project, a line per step or variant
placemat watch <pid|label>    # one of them; --json prints the events as sent
```

`watch` can be started before, during or after the command's first steps (it is caught up on what has happened) and
returns when the command ends: exit 0 done, 1 an error (the message and line are printed), 2 died or no such command.
A command that dies leaves `progress.jsonl` (in `.placemat/runs/<id>/` for a run, else
`.placemat/views/<command>/progress-<pid>.jsonl`) with its last steps; `watch <pid>` prints them. Do not tail a
command's printed output to learn where it is. The studio's Runs view shows the same commands for the user. Event
shapes and files: `references/api.md`, "Live progress".

## Script standard

- The script is the only intent document. Its docstring says what the
  board is, which edge carries what and why, what is fixed and what
  outranks what; requirements are comments beside the declaration that
  implements them, and `assert`s where a number can be checked.
- Name it `<Board>_layout.py` after the `Board(name=)`, `Project(name=)`
  or `Layout(name=)` in the `.zen` beside it. A declaration with
  `layout = False` is not a board.
- As tight as physically possible, then loosen where a reason says. The
  defaults are the fab's own spacing: rows, blocks and labels pack with
  courtyards touching, tracks are their class width, edge items sit at the
  keep-in. Every larger gap, clearance or width names what needs it (a pin
  through a wall, a light pipe, a current, a creepage). A cell's run
  prints its extent and how much of it is empty.
- Declarations, not procedures: one `place()` per item, one copper call
  per net feature, written out where a reader must see what it does. A
  short function called once per thing is fine when its name says what it
  lays out. No globals, no helpers defined inside a phase.
- Measure, do not type, for a check or an `assert`: `board.extent()`,
  `board.pitch()`, `board.pad(...).box` read the generated board, so a part
  swapped in the `.zen` leaves no stale number.
- Freedom is derived from `at=`, never declared, and file order never
  decides execution. The placer ranks searched items by courtyard area and
  pin count (every step prints `rank 4/64 (31.5 mm2, 12th of 64; 2 pins,
  41st)`): read it before reaching for `priority=Priority.HIGH`/`LOW`, and
  give a reason beside one.
  Within a tier an item with one freedom left (a slide: `Centre(x, None,
  toward=)`, `OnEdge(edge)`, a ring or spoke) goes before one searched in two.
- `required=True` is the only thing that stops a run for a placement; use
  it for an item with nowhere else to go. Firm only what is mechanical.
  Furniture (test points, LEDs, buttons) is `OnEdge(edge)` alone and
  slides to the room left; `along=` is a mechanical fact, never spacing.
- Leave a searched part's rotation out unless its turn is a fact (a
  polarised part read by assembly, a connector's mouth): the search tries
  all four.
- Cells are rigid: place them, never their members. A cell that
  does not fit is a capture question.
- A cell drops a via only for ground and a rail it owns. A net the board
  chooses and a signal that leaves the cell end at their part; the board
  routes them.
- A module fragment is generated by its own board's rules: give its `.zen`
  the parent's `Board(..., config=)`, or it lays out at the stdlib defaults
  (a run says so when the silk clearance it reads is 0). Size its frame
  with `board.rect(fit=True)`, or `fit=Axis.X`/`Axis.Y` with the other
  side a number, unless a row must meet its edge.
- Explore once the declarations are right: `placemat run <script> --explore
  60 --focus <cluster>` (or `--focus-after LINE`), read what would move and
  why, then `--accept`. The lock beside the script keeps it; commit the
  lock with the script. `placemat freeze` moves an entry into the script
  once the spot is part of the design.
- A board of any shape is `board.outline(path, holes=)`, its sides chosen
  by `board.edge(facing=)`; a round one is `board.disc()` placed in
  bearings (`OnRim`, `OnBore`, `Polar`, `ring()`). A hole is a `Cutout` in
  `holes=` on any board, placed from what it serves (a cable slot from its
  connector); never reshape a board to give it a hole. A region that stays
  board but forbids is `board.keepout()`.

## Placement and copper practice

- Before grepping a `.kicad_mod` or reaching for pcbnew, run
  `placemat parts` (what the parts are called) and
  `placemat measure <board> <part> --pads` (a pad's copper box, net and
  position; a footprint not on a board is `placemat measure
  <path>.kicad_mod`). Before extracting a datasheet's images or text, run
  `placemat datasheet <pdf>` to find the page with the land pattern,
  dimensions, layout rules or pin map, then `--show` it for its text, and
  `--show ... --png` for the render (written under `.placemat/views/datasheet/`,
  and the command prints the path).
- Say what is a mechanical point and what is a distance along an edge;
  leave the rest a bare `place(item)`. The placer seeds each searched item
  from the placed pads it is wired to and says why in its step. When
  searched items land in pockets ("nothing it connects to is placed"), try
  `[solve] enabled = true` and let the `best` line judge. A step that "took
  the pocket" had no room by what it connects to: make room there, or give
  it a `Near`. A `cleanup:` step was moved after its turn; a part that must
  stay where the search put it takes a `Near`.
- A run replays the previous run up to the first changed step: a change to
  a late part costs seconds, a change to a fixed part, a large early part
  or anything board-wide re-runs the board. Batch those.
- No floorplan by coordinate: a `Location` meaning "the power area" is the
  placer's job typed by hand. `Near` is for a requirement the netlist
  cannot say (a thermal sensor by FETs it shares no net with) when a
  point, not a distance, is what is known; when the requirement IS a
  distance a field or a temperature falls off over, `board.push()` prices
  it instead of a hand-picked point. A part with a wired neighbour is
  linked and left bare.
- Price the connections, not the parts: a bypass capacitor is a SHORT link
  with a limit at its pin; a series part between two distant parts is
  PREFER on both links; a net whose off-board cable dwarfs the board is
  `free_net`. A plane's connections never pull, but a link you declare on a
  plane net does: that keeps together two parts whose only shared net is a
  plane.
- A part with satellites at its pins (a regulator and its caps) is a
  `board.block()`. A cell faces its partner: handoff pads toward the cell
  they join, its quiet side away from the aggressor. `placemat show <board>
  <cell>` renders a cell before you choose its turn; a step saying "no
  faces declared" means the cell needs `board.faces()`, not a rotation in
  the board script.
- Rows and references before numbers: things along an edge are a `row`
  (connectors `line=Line.OUTER`); a row inboard of another is `behind=` it;
  a part between two pads sits at `Mid()` of them. The edge is the
  board's: no script carries an edge standoff. Two firm things that must
  sit together are placed relative to each other, never by independent
  numbers from opposite edges.
- When DRC reports `silk_overlap` or `silk_over_copper` between parts, or
  the `footprints` line names courtyards that understate their parts, try
  `[place] envelope = "physical"`. It re-places the whole board, and KiCad
  then reports `courtyards_overlap` where courtyards meet.
- A flip to the back mirrors about the vertical axis (KiCad's F key), then
  applies `rotation=`; KiCad's orientation field reads `rotation + 180`.
  Unlike KiCad's flip, a flipped cell keeps its inner copper on its layers
  (F and B swap, In1..In4 stay), so a cell keeps its layer roles; a via
  reaching a face and a footprint's own copper mirror as KiCad does.
- A clearance that differs in one place is `board.rule(clearance=,
  within=|between=|on=, why=)`, never a hand edit of the project file.
- Keepouts: what a region is for is said in `allow=` - parts that may sit
  in it, nets that may run through it. A keepout's `layers=` narrows what
  is checked, so **do not widen `allow=` to silence a complaint about
  copper on another layer**. A stamped cell brings its regions,
  and findings against them are real: do not restate a cell's keepout in
  the parent. A datasheet clearance is transcribed in the datasheet's
  coordinates with `anchor=`, placed on the real pad
  (`at=PadRef(...)`), turned with `rotation=Turned(part, 0)`. Keep tall
  parts out of a low region with `excludes=(Forbid.PARTS,),
  max_height=` and `Pm.Height` on the parts, never a list of short parts.
- Vias: do not place one by coordinate and wait for DRC. Ask `placemat
  occupancy <board> --via-near <part>.<pad>`, or declare
  `board.via(net, FreeSpot(near=PadRef(...)))`; a track may end on the via
  it returns. Fill a power or exposed pad with `board.vias(net,
  PadRef(...))`, never a typed grid.
- A high-current path is copper you draw (a pour over its pads, a finger or
  a wide track). Copper whose every endpoint is decided is planned before
  the search, so loose parts go round it. A plane serves what it reaches
  by a via; a bypass capacitor served through a via is a bulk capacitor.
- A plane net (ground on a face, an inner plane) is a zone: `board.plane`,
  which later copper and vias cut through. A power or hot-loop join is a
  fitted pour, `board.pour(net, members, layer=, swallow_pads=True)`: it is
  drawn as planned, and copper planned after it keeps clear. Never draw a
  plane net as a pour, and never stand a plane in for a join.
- A low-current sense line that leaves power copper (a current shunt's
  Kelvin tap, the top or bottom of a feedback divider) is its own net in
  the capture, joined to the power net by a net tie at the tap point. On
  the power net, a sense track can run along its own pad or pour and merge
  with it, and DRC says nothing; on its own net, DRC keeps it clear
  everywhere but the tie. The tie's power pad sits on the tap point
  (`Pin(key, PadRef(..., edge=))`), its stub enters the power pad where
  the sense is taken rather than running alongside it, and the sense pad
  stands a clearance off the power copper with `Beside(..., copper=True)`,
  since KiCad exempts a tie's own nets from clearance.
- A layout decision that rests on a datasheet or other primary source
  names it in the declaration's `why=` (document, page, figure), so the run
  record carries the evidence beside the decision.
- Tracks are octilinear and every right angle is chamfered; the tool picks
  the route with the fewest turns. Give a track its ends and only the
  waypoints where it must go. A daisy chain is a chain, not a bus with
  stubs. A bus is one long track per net and a short track per pad into
  it; where two same-layer nets cross, the lower `priority` passes under
  if it is `bridge=True`, else it is a finding.
- Label what a user touches: every connector, jumper, switch and LED gets
  a `board.label()` saying what it does, on the face it is used from, a
  pin 1 mark on every keyed connector. A refdes is not a label. Declare
  labels with their items, before the loose parts are searched.
- Use placemat's words in comments, and define any word of your own (a
  "corridor", a "bank") where it first appears, in terms of what is on the
  board.

## When a track or a placement fails

- A finding may carry suggestions: `finding_details[i].suggestions` in `run.json` (and the `try s3a: ...` line under
  a critical or warning finding). Read the finding as a claim about the script first, then the suggestions as
  candidates: `placemat apply s3a --dry-run` shows the diff, `placemat apply s3a` writes it (`--undo` puts back the
  last one), and the next run decides whether the finding cleared. A suggestion that writes a number names it as a
  constant with a comment; keep the comment. `api.md`, "Findings and severities", has the cases.
- Read the finding as a claim about the script first. A track that hits a
  pad may have a waypoint steering it there (the run says so when pad to
  pad would clear), or its ends may be placed so no clean route exists, or
  the tool may have no candidate that fits. Take them in that order:
  remove the waypoint, then look at the placement, then at the tool.
- Never call a route impossible from one run. Draw it the plain way (pad
  to pad, no waypoints, no offsets), run, and read the numbers.
- `placemat layer <board> <LAYER>` draws one copper layer by net and lists
  tracks inside another net's zone; `placemat measure --copper [NET]` lists
  each track segment and what its ends land on, and each graphic copper
  polygon with its edges' gaps; `placemat drc` names each
  violation's parts by instance path. api.md's "Read the board" index has
  the rest.
- A refusal ending "cannot give way" is a via question: a carried via (one
  at a searched part's pad, a part's `board.vias()` grid, or a stamped cell's own) met another net's
  copper and none of its steps worked. The steps, in order, are share a
  same-net via, move, re-lay its field (the vias of one net in one pad of
  a stamped cell or a part's grid: moved, a row shifted, the pitch closed or uneven, a row
  out, keeping the count where the pad allows), leave its pad (a via in
  its pad, joined by a new tail), shorten (a plane drop) and drop. A via that two or more of a
  cell's tracks end on has one step: it moves with its tracks rebuilt
  from their far ends ("no spot within 0.50 mm is clear with its 2 tracks
  rebuilt"; `place.via_route` sets the reach, 0 leaves it as drawn). The
  sentence names each step and why it failed. `place.via_move` and
  `place.via_share` set the reaches,
  `place.via_leave` how far a via may leave its pad, `place.drops_keep` what
  share of a pad's drops must stay, `place.via_relay` turns the re-lay off, and `drops=` on a cell thins its drops
  before the search. Shorten runs only when the fab profile's micro, blind
  or buried tier for the shorter via is "yes"; the refusal says when one
  would have cleared it. api.md, "Carried vias give way", has the rest.
- A number chosen to dodge something is a workaround for a rule the tool
  should carry: say so in the run notes.
- A design check that fails where no layout does better is accepted only on
  the user's reason: declare it with `board.accept(..., why=)`, not by
  loosening a board-wide limit (`check.limits`, `--rise`, `--keep-out`). A
  keep-out distance a part's datasheet draws is a fact about the part, not an
  acceptance: it is `Pm.KeepOut` on the part with the datasheet cited
  (`references/capture.md`).

## Gates, in order

`real` DRC buckets empty; `unconnected` 0 (or only the nets not drawn yet,
by name); no critical findings, and every warning fixed or judged; `outstanding` explained (a cell's frontier stubs
dangle until the board picks them up); the render reads as intended. A run
that regenerated the board is compared against the committed board, not
against the previous run.
