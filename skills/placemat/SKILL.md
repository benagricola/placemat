---
name: placemat
description: Author and refine PCB layouts as regenerable placement scripts (KiCad/pcbnew) - component placement, copper pours, plane hand-off, real DRC verification, and folding human hand-edits back into the script. Use for ANY request to lay out, place, pack, tighten, or improve a PCB module or board, to write or update a layout/placement script, to compare or fold in hand-edited .kicad_pcb changes, or to assess layout quality - even phrased casually ("make this module smaller", "apply my edits", "why is this layout bad").
---
# PCB layout as code

placemat lays a KiCad board out from a script that states constraints, and
works out the positions itself. The script is the artifact: re-run it after a
schematic change and you get a board, not a merge conflict.

The deliverable is the script, never a hand-placed board file: a hand edit is
upstream input to diff, understand and fold back in. A first layout is a
PROPOSAL - the loop is script, render, the owner looks or hand-tunes, diff,
extract the why, script again. Plan for iteration; do not present a first
attempt as final.

**Not for**: schematic capture, part selection, or electrical design decisions.
Layout constraints that COME FROM electrical intent - hot loops, isolation,
pair symmetry - are inputs here, decided elsewhere.

## Asked for nothing in particular

When the request names no board, no cell and no change - "use placemat here",
or just the skill invoked - do not guess and do not start laying anything out.
Find out where you are first:

    placemat status

It answers all of it: whether this is a project at all, whether the fab profile
is real, which boards are captured, which have a layout script, which have been
placed, and which cells are missing a script or a fragment. Do not work any of
that out by globbing - two agents globbing get two answers, and this is the one
the library itself uses.

Three outcomes, and each has one next move:

- **Not a project** (`status` says there is no `pcb.toml`, or the directory
  holds no `.zen` at all). Say so and stop. A directory with no captured
  schematic has nothing to lay out, and running `init` in someone's home
  directory is not a recovery.
- **A project, but placemat is not set up** (`.zen` files present, no
  `pcb.toml` or no fab profile). Bootstrap it: "Setting placemat up" below.
  Then say what `init` wrote, and that the fab profile it left is a TEMPLATE
  whose numbers are not this fab's.
- **Set up already.** Take the `unfinished` list from `status` and ASK which
  to work on, with the question tool - one option per candidate, the most
  obviously-next first: a captured board with no layout script, then a board
  with a script that was never placed, then a cell missing its fragment. Say
  what each would involve in a sentence. If `status` reports nothing
  unfinished, say that and ask what to change instead of inventing work.

Never pick for the owner. The list is short, the choices are not
interchangeable, and which board matters next is theirs to know.

## Setting placemat up

In the project you want to lay out:

    uv venv --python "$(which python3)" --system-site-packages
    uv add git+https://github.com/benagricola/placemat
    uv run placemat init

`pcbnew` ships with system KiCad and is not on PyPI, which is why that venv
inherits the system interpreter; an isolated `uv tool install` or `uvx` cannot
see it. `placemat init` checks that first and prints the remedy, writes a
TEMPLATE fab profile whose numbers are not the fab's, and creates the
directories a project needs.

Then `placemat --help` for the commands and the repo README for the shape of a
project. Do not restate either here - a command written down twice is a command
that goes stale in one of the two places.

## What to read, and when

This file is the process. The craft is in `references/`, and each one is read
at the point it is needed rather than up front:

| doing | read |
|---|---|
| placing anything | `references/placement.md` |
| drawing copper | `references/copper.md` |
| writing or changing a script | `references/api.md`, then `references/discipline.md` |
| running or reading a pass | `references/gates.md` |
| folding in a hand-edited board | `references/discipline.md` |
| changing placemat itself, or a surprise underneath it | `references/pcbnew.md` |


## Which job is this?

| what you have | where to start |
|---|---|
| a board `.zen` and no layout script | the round below, at step 1 |
| a board whose script exists, and a change to make | step 0 below, then step 5 |
| a module or cell fragment | the same round without the frame and the stamps: the cell's own `LAYOUT-INTENT.md` is the input, and it ends at a committed fragment plus renders |
| a board the owner hand-edited in KiCad | step 0, then "Iterating on feedback" for the fold-in, then re-enter at step 7 |

### Step 0: the script comes onto the standard first

**Every request to change an existing script begins by asking whether that
script is still on the standard, and the answer comes from the linter, not
from reading it.** Run `placemat lint`; where it names a hand-rolled helper,
a raw unit conversion or a missing piece of the scaffold's shape, the file
predates the current library and gets MIGRATED WHOLE first, as its own step,
before the change you came for. "Migrating a script onto the standard" has the
procedure and the order.

This is the mechanism by which a board picks up what the library learned since
it was placed. A script is only as good as the last session that touched it, so
a change made on top of an out-of-date file inherits every fix the file missed
and adds another local helper beside the library function that replaced it. The
board that gets edited is the board that gets improved - and it only works if
the upgrade is not optional. Editing just the lines you came for is what
produced the divergence in the first place.

A script that still runs top to bottom has not been migrated at all, whatever
the linter says about its helpers. Bring it onto the stage framework as its own
step, and the gate is the same as any migration: regenerate and confirm the
board does not move. A migration that moves a part is a bug in the migration.

Two things to confirm at the same time, both cheap: that the board is CURRENT
(a cell re-laid-out since the board was placed has not reached it, and a stale
board's first job is to take the new cells and re-verify, not to make the
change that was asked for), and that the tracked board and its renders are
committed, so a hand-edit round has a clean baseline to diff against.

Everything else about how a script is shaped - what a stage is, what the runner
owns, where the fab profile comes from - is in `references/api.md`. Read it
before writing or changing one.


## The board round

Eleven steps, and they are in this order because each one reads what the one
before it decided. A step skipped is not saved: it is paid for later, as a
board placed for the wrong problem or a number nobody can source.

1. **Read what the board is made of.** The board `.zen` - its parts, nets and
   net classes - every stamped cell's `LAYOUT-INTENT.md` and `io()` list, and
   the datasheet layout section for each active. Electrical intent first: hot
   loops, Kelvin sense, isolation gaps and pair symmetry are constraints, not
   suggestions. For every connector, open the footprint and the datasheet -
   the mating direction decides where the part may sit (tactic 7) and it is
   not guessable from the part name.

2. **State the stackup.** It decides what layout is even solving, so it is
   settled before any placement. Read the board's layer stack from the design
   (its intent doc and the board config, not the generated file) and state it
   at the TOP of the layout script: how many copper layers, what each one is FOR (signal, plane,
   or mixed), and which nets live on a plane. Everything downstream turns on
   it:
 - **A net with a plane is not routed.** On a board with a ground plane and
     a power layer, ground and the planed rails leave a signal layer entirely:
     each connection is a via into the plane, drawn as a drop, not a track.
     The signal layers are then for signals, and placement must not spend a
     corridor on a net the stackup already carries.
 - **Placement changes with it.** A cell's far-layer claim, the cost of a
     via, how far a rail may travel and which pockets are usable all differ
     between a two-layer board and one with planes. Placing first and reading
     the stackup later means placing for the wrong problem.
 - **A plane is a reference, not just copper.** A fast net that changes
     layers needs its return path continuous underneath: a split, a slot or a
     via field cutting the plane under it is a defect the DRC will not report.
 - **Draw or reserve the planes before judging routability.** Until they
     exist, the rails and returns they were meant to carry are still sitting
     on the signal layers, so any congestion or closure number describes a
     board the design does not propose - and hours spent closing that board
     are hours spent on the wrong one.
 - **Measure on the layers the stackup declares as signal layers.** Not
     more (handing a router a plane layer buys a number the design will not
     honour) and not fewer (a closure figure from the outer pair alone is not
     a four-layer board's figure). If a layer count is provisional - "four,
     six only if four cannot close" - that is a decision to take with a
     measurement, and the measurement only counts once the planes are real.

3. **Write the board's intent file before the script.** `BOARD-INTENT.md` is
   where the facts the schematic does not imply live, and the script's CONFIG
   block then reads from it ("Where things live"). Three of those facts have
   no default, and a board is not ready for a script until each is written
   down with the source that fixes it:
 - the **FRAME** - locked to a mechanical part, computed from the floorplan,
     or chosen outright; say which, because a dimension whose origin is
     unrecorded is one nobody can change later;
 - which nets a **PLANE** carries, layer by layer - this is step 2's answer
     committed to a file, and it decides what is routed at all;
 - each connector's **EDGE and entry direction**, from step 1's datasheet
     read.
   A board that arrives without this file gets it written as part of the
   round. Inventing these three silently is how a board ends up with a size
   nobody chose and a plane assignment nobody agreed to.

4. **Start the script from the scaffold**: `placemat new-board <Name>` writes
   it beside the `.zen`; fill its CONFIG block from step 3. The scaffold comes
   from the same version as the library that will run it, so the format and the
   API cannot drift apart - which is why it is emitted rather than copied from
   a file in this skill. The scaffold carries the stage
   bodies, the config/mechanism split, and a library call in every place a
   script is tempted to hand-roll one; every CONFIG value names its source.
   CONFIG stays module-level - neither object can exist until the frame and
   the plane nets are known, which is the one ordering the runner has to do for
   you. Steps 5 to 9 below are the bodies you fill in, one per stage; nothing
   in the file runs at import.
   Before writing any helper, read the library's API surface and match by
   CONCEPT ("Script discipline") - and let `placemat lint` say whether the
   file matches the current standard rather than judging that by eye.

5. **PLACE IN ORDER OF WHAT CANNOT MOVE.** Read `references/placement.md`
   first. Three kinds of thing get placed,
   and they are not interchangeable - mixing up their order is the most
   expensive ordinary mistake in a board script, because every collision it
   causes looks like a geometry problem rather than a sequencing one:
 - a **CELL** is a module fragment. It carries verified geometry AND its own
     routing, and some cells cannot go anywhere else at all (an enclosure fixes
     a connector's edge, a mating interface fixes an orientation). Cells go
     down first, most-constrained first - and "most constrained" is decided in
     this order, not argued each time:
     (i) **Position decided outside the layout**: a panel cutout, a
     board-to-board mate, a sensor whose position IS its function (an encoder
     over the shaft centre, a current sensor in the bus path, an antenna and
     its keepout). Transcribed, not placed. First, in declaration order.
     (ii) **One degree of freedom**: edge-bound cells that slide along their
     edge - field connectors, USB, an indicator behind a case window, a header
     a hand has to reach. After (i), which may already have eaten the edge
     they need.
     A cell in (iii) is SEEDED, not typed. It starts where its own nets are,
     then at the best-fitting free pocket for its own geometry, and only then
     at a coordinate - which is a FALLBACK and gets named as one when it is
     used. A coordinate says where there was room when somebody looked and
     nothing about where the cell's nets are, so a search seeded on one lands
     the cell in free board far from everything it connects to, and the result
     reads as deliberate because a human typed it. Two things make the pocket
     scan reach what a hand-written hint cannot. It slides the
     cell's OCCUPIED GEOMETRY, never a box round it: a rectangle round an
     irregular cell is mostly air, so fitting the rectangle demands board the
     cell never uses and reports "no room" on a face with plenty (tactic 5b,
     and measured on a real board cells fill 41-66% of their own rectangles).
     And it tries ALL FOUR right-angle poses, because an irregular cell often
     fits one way round and not another - a cell that scatters into loose
     members for want of a turn has thrown away its geometry and its routing
     for nothing. The scan is global where the ring search is local, which is
     the whole reason hints existed: a pocket in another quarter of the board
     is invisible from the seed.
     (iii) **Free in the plane**: ordered by what the placement is actually
     ALLOCATING, which is three scarce things, not one - area, adjacency, and
     the one that is invisible until it is gone, DISTANCE. A cell that must
     sit far from another (a high-impedance front end, a crystal, a reference
     or an ADC away from a switching regulator's di/dt loop and switch node)
     spends the board's remaining separation, so it is placed right after the
     aggressor it must avoid, while distance still exists. Two rules settle
     the rest: **fit dominates** - a cell needing a large fraction of the
     remaining free area goes next whatever it connects to, because "does this
     fit anywhere at all" outranks "is it near the thing it talks to", and a
     cell that dissipates counts the copper its heat needs, not just its
     courtyard; and **seed on difficulty** - when nothing placed yet connects
     to anything, start with the biggest and most awkwardly shaped cell, since
     a long thin cell needs a long thin hole and the pockets left between big
     cells are stubby. Otherwise take the cell with the heaviest declared
     links to cells ALREADY PLACED, which walks the order outward along the
     circuit from the fixed anchors. A cell none of whose partners are placed
     has nothing to aim at, and every cell seeded on it afterwards inherits
     that arbitrary spot (tactic 2c).
 - a **BLOCK** is a board-local group whose members' positions are DERIVED
     from an anchor part's own pads - a regulator with the capacitors that
     serve its pins. Its members cannot be placed one at a time, so it is not a
     set of loose parts; it has no fragment, so it is not a cell. It goes down
     after the cells, and it SEARCHES as a unit.
 - a **LOOSE PART** is placed individually - but never JUDGED in isolation.
     What counts as well-placed is set by its proximity class (tactic 2a), and
     the parts free to float are precisely what gives way when room runs short.
     They go down last, and AMONG THEMSELVES they go down in the order their
     links demand: a part holding a link that is short by function before one
     holding only preferences. Adjacency is scarce and goes to whoever asks
     first, so that sequence is an allocation, not a formality - place the
     preference first and the room the constrained link needed is gone, which
     reads as "the board is full" when it is really "the room went to the wrong
     connections".
     **THE FILE'S ORDER IS NOT THAT ORDER, and must not be.** A script is a set
     of DECLARATIONS - place this part, by this method, under these constraints
 - and working out the sequence from the constraints is the LIBRARY's job.
     If the order calls happen to appear in decides who gets the room, then the
     file is the allocator: moving two lines silently re-allocates the board,
     the priorities are advisory, and every author has to hold the whole
     sequence in their head to add one part. Collect the requests, hand them
     over once, and let the ordering fall out of the weights. Hoisting the
     constrained parts to the top of the file is the same bug wearing a
     disguise - it hard-codes one correct answer instead of deriving it, and it
     is wrong again as soon as a weight changes.
   The order is forced by what each can give up. A cell may be pinned by
   geometry nothing can change; a block can slide a few millimetres; a loose
   part can cross the board. Place the flexible thing first and it takes the
   spot the rigid thing needed, and then the rigid thing "does not fit" - a
   conclusion that is false and expensive. **A group written at a bare
   coordinate is the smell here**: a coordinate cannot give way, so whatever it
   is, it has been promoted above everything placed after it, usually by
   accident because no primitive existed for what it actually is.
   Within that: connectors first (tactic 7 - enclosure and field wiring fix
   their edges and orientation), then coarse by signal flow, IC as anchor; then
   an align/pack pass (tactics 1-6). Signal flow is measured, not felt: the
   ratsnest (airwire length and crossings, per net and per cell) is the
   placement's own score. Ask the oracle what a pose costs before settling
   it, let the free placer and the cell settler pick the clear pose with the
   shortest airwires when the choice is theirs, and read the airwire line of
   every pass record; `placemat trial` then confirms a placement instead of
   discovering it.

6. **Draw the copper - it is drawn, never autorouted.** Read
   `references/copper.md` first. The script draws
   pours for power and thin traces for signals (tactics 8-14), and the board
   round draws the rest. A router is only ever a measurement (the routing-trial gate scores
   how much of a placement a strict router can close); its copper is never
   kept, and no routing prep step spreads or re-places footprints. The netclass
   width is a FLOOR, not a target - use wider traces wherever room allows
   (manufacturing robustness), and give the layout's project file a user
   width-preset list so hand edits can pick real widths. A reusable cell
   ships with its complete layout AND its routing; whether a board keeps
   that routing is the board's call (see "Two freedoms").
   **Plane hand-off**: ground stitch + power drop vias. Nets that leave the
   module as signals (field pairs, MCU lines) END AT THE PAD, or at an
   escape via where the pad is unreachable on the surface (a fine-pitch pin
   boxed in under a body: pad, the shortest trace, a via, stop). **No edge
   stubs.** The handoff contract is the pad or via position and the side
   the net should leave on, recorded in the module's own layout-intent file; the board draws
   the trace from there. Why: a stub comb at package pitch (0.4-0.5 mm)
   cannot be picked up under 0.2/0.2 rules (foreign copper within 0.3 mm of
   every stub end), a stub fixes an exit order the board should choose per
   instance, and stubs hold the cell's envelope open (removing them from a
   cell typically re-packs it 1-2 mm tighter).
   Relief vias under a package (tactic 17) stay: they are structural
   escapes, and the far-layer lane from the via to the destination is the
   board's.

7. **Run the pass, and read it.** Read `references/gates.md` first. A placement pass is ONE command, in the
   foreground: a clean generation, the script, `placemat occupancy`, real DRC,
   the stamp contract, the declared links and the airwire line. That is the
   loop ("The fast loop") and a session makes many of them. Verify for real -
   run the actual DRC tool, never a bounding-box approximation - and judge
   each pass against the one before it rather than in isolation
   ("Verification gates"). The routing trial is a MEASUREMENT of the
   placement, not a deliverable: run it when the airwires say a move helped,
   and read WHY each net is still open before spending another pass on it.

8. **Show the human renders when you present the work** - a top-down view
   AND an isometric view, kept next to the board file (`layout.png`,
   `layout-iso.png`) overwritten each save: current state only, no history.
   That means at the end of a round, on a fold-in, or whenever asked - NOT
   every pass. Rendering is most of a script's run time, so a round iterates
   with renders off and pays for them once, when there is something to look
   at. Whole-board renders during board work; a multi-module contact sheet
   earns its keep. Invite correction.

9. **Inspect the iso render for model seating** - floating pins, bodies above/
   below the board, parts offset from their pads. These are 3D-model transform
   defects the top-down view hides. Fixing them is PART of the layout stage,
   not someone else's problem: replace the model + transform as a matched pair
   from a self-consistent source (a known-good library export), verify pad
   origins agree, re-render. Never mix a model file with a transform computed
   for a different export.

10. **Test, then publish.** A layout script is a Python program, so it is
    tested like one, and `uv run pytest` is the only entry point ("Testing
    and publishing"). The board under `layout/` is a RELEASE: a pass builds
    into its own directory and only `--publish` writes the tracked board,
    refusing when a gate failed. The order is: edit the script, run the
    tests, look at the renders, publish.

11. **Commit the generated artifacts when the work is done, not every pass.**
   The board file and renders are tracked so the next hand-edit session
   produces a clean diff to fold back, so they must be committed and current
   BEFORE anyone hand-edits or the baseline is lost - but that moment is the
   end of a round, a fold-in, or an instruction to commit, not each
   incremental improvement. A board file is tens of thousands of lines and
   its renders are megabytes: committing them per pass costs render time and
   buries the real diff, and every intermediate state is reproducible from
   the script anyway. Working autonomously, commit when finishing the turn.
