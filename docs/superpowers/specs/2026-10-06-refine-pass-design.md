# Refine: detailed placement after the search

Status: draft for review, 2026-10-06; amended 2026-10-07 (the resolved constraint record, routing feedback, the
neighbourhood rebuild); release line 0.100.x.

## Problem

Trying a placement change costs a full resolve: 10-45 s on the fairing core after one statement changes
(docs/superpowers/research/2026-10-06/core-preview-latency.md), and an explore variant costs 4-7 minutes there. There are far more positions, turns
and swaps worth trying than that allows. So agents nudge one thing, wait, judge, and nudge again, and the board keeps
the choices an early search or an old explore made.

Placement tools split the job into three steps: a global placement, legalization, and a detailed placement that makes
many small local moves on the finished board, each scored by what it changes. placemat has the first two in its
constructive search. It has a greedy start at the third, the cleanup pass, but that pass has several limits:

- it uses a different objective from the search (HPWL, `cleanup.py` 154-226);
- it never moves cells;
- it is switched off on every fairing core board (`[cleanup] enabled = false`), because of a bug fixed in cf9f1cd1 that
  the boards never switched back for.

The user does not want a new feature beside the ones that exist. This design upgrades the cleanup pass into the
detailed placement step and retires what it makes redundant, so the toolbox gets smaller.

## What exists, and what each becomes

From the inventory (docs/superpowers/research/2026-10-06/placement-inventory.md, file:line there):

| Feature | Today | After |
|---|---|---|
| Cleanup pass (`cleanup.py`, `_cleanup` layout.py:8596) | Greedy shift and swap on HPWL, parts only. Off on the fairing boards | **Replaced by refine.** Its shift-to-the-optimal-region move is kept as one of refine's moves |
| Search score `Scorer` (layout.py:829) and native `NativeScoring` (lib.rs:802) | Scores one item against the placed board | **Refine's score.** A move is judged by the score that placed the item |
| Incremental ratsnest, lift/unlift/commit (occupancy.py:1216-1245) | Refreshes only touched nets | **Used as is** by refine's moves |
| turn.better (`_report_turns`) | Reports a better turn and suggests the edit | For movable items, **refine takes the turn itself** and turn.better no longer reports it. It stays for turns the script or a stated constraint owns, where only the user can change it |
| Explore (`explore.py`) | Re-runs the construction with random choices and order. The best variant goes to the lock | **Kept, as restarts** (fresh constructions from a different seed, then refined): it reaches arrangements a local pass cannot. Each variant is refined before it is scored, so variants are compared at their refined best |
| Lock (`lock.py`) | Pins each searched item where an explore put it | **Removed.** Each run starts from the last run's placement, and the script's constraints hold what must not move (see Starting from the last run) |
| Pin study (`pinmap*`) | Pin remap and pose: advice, a capture change | **Split.** The pose (turn, face) is a placement move, and refine owns it. The remap is a capture change only the user can approve, so the study keeps it and runs inside coarse refine, for each pose tried (see The pin study, in coarse refine) |
| Give-way, settle, scan | Construction | **Kept.** Refine depends on them |
| Global solve (`solve.py`) | Optional hints, off by default; measured no better once cleanup runs | Unchanged. Revisit after refine is measured |
| Suggestions, probe | Script edits; never used on the fairing boards (no applied.jsonl, no probes) | Unchanged here. Refine moves placement where the script leaves it free, so fewer findings need an edit |

Agents ignored the advisory findings (escape_crossed, link_over, every suggestion) and acted on what changes the board
(explore accept, the lock, the pin remap with approval). Refine follows that: it applies improvements the script allows,
and reports only what it may not change.

## Two stages: coarse, then fine

Decided with the user. Refine runs in two stages.

**Coarse refine** runs once, after the constructive search and before any routing.
- **Items:** cells stay rigid, so the items are whole cells and standalone parts.
- **Poses:** for every cell and every part, two-pin parts included, it tries every turn and face the declaration allows.
  For each one it runs a short local refine: the item held at that pose, free to shift within its declaration, its
  neighbours free to make room. It keeps the best pose by the one score, on the pins as captured. This is the turn
  study, done by refine rather than reported afterwards.
- **Why every part:** a resistor turned end for end so its MCU-side pad faces away from the MCU is a pose error, like a
  turned IC. The display terminations were one, and only a per-pose check catches it reliably.
- **Which poses:** every turn the declaration's `rotations=` allows: eight, at 45-degree steps, by default, or whatever
  set of angles the script gives. Each is tried on each face the declaration allows. The cost is the number of poses
  times `refine.pose_moves` per pose, set by measurement. A two-pin part's local refine is small.
- **The pin study** runs inside this stage (see "The pin study, in coarse refine").
- **Annealing:** the moves below, over cells and parts.

**Fine refine** starts from the coarse result.
- It frees cell members (see "Cells: placed whole, refined as members").
- It anneals over parts and members.
- It is the stage the routing loop repeats, with each phase's open connections as a cost (see "Routing feedback").
- When board-wide fine refine stops improving the routed board, it escalates to the neighbourhood rebuild: it lifts a
  bounded group of items round a failed connection, across module boundaries, and tries other arrangements of them
  together, with the rest of the board held (see "Neighbourhood rebuild"). Nudges, turns and swaps move one or two
  items at a time; some crowded areas need several items moved together, with no legal sequence of single moves
  between the old arrangement and the new.

A restart runs both stages from its own fresh construction.

## What refine does

After the searched tier and before the late copper (where cleanup runs now), refine:

1. **Holds the board** as the search left it. Firm items, decided items and declared copper stay as they are.
2. **The movable set** is read from each item's resolved constraint record (see "The resolved constraint record"),
   in place of the `_cleanup_movable` rule (layout.py:8543). An item is movable when its record leaves it more than one
   pose: every searched part and cell, every decided item whose relation gives it room (see "Each relation's room"),
   and the refinable members of cells (see "Cells: placed whole, refined as members").
   - **Place and turn are held separately.** `rotation=`, `Facing`, `Turned` or a `why=` that names a turn holds the
     turn and leaves the place its room. A `Near` with a radius moves within the radius, which stays a hard bound.
   - **Units:** a row or block, a group of members a module pour joins, and a cell set `rigid=True` move only as one
     unit.
   - **Targets move with their dependants.** An item another declaration is placed against (a `Beside` target, a
     row's reference) is movable. When it moves, each dependant is re-placed within its own room against the target's
     new pose, and the move is legal only if every dependant has a legal pose there (see "Moves are checked whole").
   - **Held outright:** a fixed point, a `Pin` on a pad, a fixed `Location` or a datum; an item `--pin` holds for the
     run; an item the native judge cannot score yet (a push, a declared lane), while that limit stands.

   An item placed from the snapshot is movable like any other. The run reports how many items and members are movable,
   and for each held one the reason (see "What is reported").
3. **Proposes small moves** at random, from a seeded deterministic stream:
   - nudge: one item a grid step or a few in any direction, within its declared bounds;
   - turn: one item to another turn its declaration allows, at the same centre;
   - flip: one `Face.EITHER` item to the other face;
   - swap: two items with the same footprint, or two neighbours;
   - arrangement: a cell to another arrangement its module offers;
   - shift: one item to the best spot within a small radius of the median of its nets' other pins (cleanup's move).
4. **Scores each move** by the change in the search's score for the items it moves. With them lifted, this is the
   score of their new spots against the board minus their old one. The wire term is an exact delta (inventory 3.1); the
   crossing and escape terms are the search's own estimates.
5. **Accepts** a move that lowers the score, and one that raises it with the simulated-annealing probability at the
   current temperature. The temperature falls from `refine.start_temp` to `refine.end_temp` over the budget. The
   budget is `refine.moves`, counted in moves so a run is reproducible, never wall time.
6. **Checks legality** for every move with the occupancy queries the search uses. Carried vias give way as at a commit.
7. **Ends** at the best legal state it visited by the move score, not the last one, and scores that board whole with
   the run score. If the run score is worse than before refine (the move score is an estimate of it), the board before
   refine is kept and a notice says so.
8. **Records** the accepted moves in the reuse record, as `_recorded_cleanup` does, so an unchanged rerun replays them.

## The script's constraints bound every move

Refine adds no constraint form of its own. Each item's freedom comes from its declaration, read the way the search
reads it: the same freedom model (`Freedom`, the one-axis `Location`/`Centre`, `rotations=`), and the same legality the
search applies. A move refine proposes is one the search could itself have chosen for that item at that point:
- **place:**
  - a fixed or edge place does not move;
  - an item with one free axis moves only along it, for example a `Centre` on a line;
  - a `Near` keeps its radius;
  - an `OnEdge` stays on its edge and slides along it;
  - a row or block member moves with its row or block;
- **turn:** only among the turns `rotation=` or `rotations=` allows, and a `Facing` or `Turned` is kept;
- **face:** a fixed face is kept; only a `Face.EITHER` item flips;
- **arrangement:** only among those the cell's module offers, and the alternatives the script names;
- **regions and keepouts:** every keepout, rule area and region the script or the capture declares;
- **links:** a link's limit is a hard bound, as in the search; its length is a cost;
- **pushes:** a push's limit is a hard bound, as in the search;
- **declared copper:** stays legal; an item whose move would break a declared track's plan is not moved.

**Each relation's room.** This applies to every decided item, standalone parts and cell members alike. A decided
item's room is the set of places its relation describes, not the one point the search chose within it. There is no
global slack setting. How far an item may move follows from what was declared:
- **`Beside(target, ...)`:** along the target's facing side, over that side's extent, at the declared gap. `Beside` a
  whole IC slides along the IC's whole side. `Beside` a pad slides only along that pad's edge, so much less. An `align=`
  that was stated holds the alignment. One left at its default does not.
- **`OnEdge(edge, ...)`:** along that edge, within any `along=` range the script gives.
- **`Centre` on a line or one free axis:** along that line or axis.
- **`Near(target, radius)`:** within the radius.
- **`Pin` on a pad, a fixed `Location` or a datum point:** no room.
- **Turns:** within the turns `rotation=` or `rotations=` allows.

Moving within that room never blocks another pin's escape or copper the script declares: the search's legality and
escape terms judge each move, as they judged the item's first place.

So the display FFC connector, declared on the board's N-S centre line with `rotations=(0, 180)`, is only nudged along
that line and only turned between 0 and 180, because that is what its declaration leaves free. Nothing is added to the
script for refine.

The check: for each accepted move, the item's new place, turn and face must be in the set the search's own scan would
accept for that item. A test asserts this over the bench fixtures.

### The resolved constraint record

Each item's declarations are resolved once per run into one record: the board script's declarations, and for a cell
member its module's members note (see "Cells: placed whole, refined as members"). The search's legality for a resolved
item, refine's moves, the neighbourhood rebuild and the final check all read this record, and none reads the
declarations a second way. The record is structured data in board coordinates and holds:
- **place:** fixed, or its room: free within the outline, one axis or line, an edge and its `along=` range, a `Near`
  disc, or a relation's room (a `Beside` side's extent and gap, a stated `align=`);
- **turns and faces** allowed;
- **unit:** the rigid unit it belongs to (a row, a block, a pour-joined group of members, a `rigid=True` cell), with its
  pose in the unit's frame;
- **depends on and dependants:** the items its relation refers to, and the items whose relations refer to it;
- **links and pushes,** each with its limit;
- **areas:** the keepouts, rule areas and regions that apply to it;
- **declared copper:** a declared track or pour whose plan names one of its pads.

### Moves are checked whole

A move moves one or more units. It is legal only when, with every moved unit at its new pose and each dependant
re-placed within its room against them, every moved item satisfies its record and the board's legality (occupancy,
keepouts, link and push limits, declared copper). The check runs on the whole move at once: a move with one failing
item is refused whole, never applied in part. A nudge is the one-unit case; a neighbourhood rebuild's proposal is the
largest.

## The speed needed, and the native call

Each move needs one legality check and one score. In Python a `legal()` is about 30 us. Each scan call carries setup
(obstacle query, sweeper, give-way), so it is too heavy per move. The native sweep judges and scores a candidate in
about 1-2 us.

Refine therefore needs one new native entry point: judge and score a batch of (item, spot, turn, face) candidates
against the held board, and return legality and the score per candidate. It reuses `NativeScoring` and the sweep's
legality.

- **Target:** at least 10,000 moves a second on the fairing core.
- **Default budget:** about 20,000 moves, so refine adds a few seconds per resolve.
- **Gate:** before the full build, a prototype measures moves a second and the score gained on the core and the bench
  fixtures. If it cannot reach 2,000 moves a second, the design comes back for review.

The items the native scorer does not cover today (an item with a push, a declared lane: `Scorer.native` returns None)
are scored in Python, or left out of the movable set while the native scorer lacks them. This is a stated limit.

## Starting from the last run (the lock is removed)

Decided with the user: the lock goes. Its job, starting from a snapshot instead of from nothing (inventory 3.3), is
done by starting each run from the last run's placement. What must stay fixed is stated in the script, so the script's
constraints are the only thing that holds an item.

- **The snapshot.** `<script stem>.placement.json` beside the script holds each searched item's last place, anchored
  to the pad it depends on most and stored in that part's frame, as a lock entry is today. It also holds the item's turn,
  its face, its arrangement and a digest of its declaration. Every run writes it. It is committed with the script, so a
  run is reproducible on another machine.
- **A run** places each searched item at its snapshot place when that is legal and its declaration is unchanged, then
  refines. A changed declaration, a gone anchor, or no legal spot near it means the item is searched from nothing, with a
  note, as a released lock entry is today. Items new to the script are searched.
- **`--fresh`** ignores the snapshot and searches everything, for a new construction. Explore's restarts use this.
- **Pins live in the script.** An item that must not move, or may move only so far, is held by its declaration (see "The
  script's constraints bound every move"). The forms already exist:
  - a fixed or edge place;
  - one free axis, for example `Centre` on a line, so the item slides only along it;
  - a stated turn, or `rotations=` narrowed to the allowed turns, for example `(0, 180)`;
  - `Near` with a radius.

  Refine moves an item only within what its declaration leaves free. An item that may slide only along the Y axis
  between turns 0 and 180 is nudged only along Y, and turned only between those two.
- **A temporary pin** (decided with the user): `placemat run --pin ITEM` (repeatable) holds an item at its snapshot place
  and turn for that run only, for a quick experiment. It is not written anywhere. The next run without `--pin` treats
  the item as usual. Anything meant to stay is stated in the script.
- **Removed:**
  - `placemat lock` and its subcommands;
  - `<stem>.lock.json`;
  - `freeze`, which wrote lock entries into the script.

  Explore `--accept` writes the chosen variant as the snapshot. `route --adopt` keeps its routes, and no longer locks the
  items they join: a kept route that no longer fits its pads is dropped with a reason, as today.
- **Migration.** On its first run, a script with a `.lock.json` converts the entries into the snapshot, and says so. The
  migration entry tells the user to state as constraints any item that was held on purpose.

## Cells: placed whole, refined as members

Decided with the user. A cell is placed as one piece by the constructive search, as now. Refine then works on its
members, so routing can make a part give way or turn inside a cell. This replaces fixed cell designs and their
designed-ahead variations: `board.alternative`, `board.unit` and arrangement alternatives are removed, with migration
entries. Neither fairing tree uses them.

**Which members refine may move.**
- **Joined by the module's pours:** members the module's own pours join are one rigid group. They move and turn only
  together, as the cell does today. Re-planning a pour around moved members comes later. Module pours are mostly stated
  by their members' pads, so they can follow their members once that step is built.
- **Unconnected, or joined only by tracks:** every other member is refinable on its own.
- **Module tracks:** when refine moves a member, the module tracks that touch it are deleted. Their connections go to
  the routing phases to be routed again, keeping the width the module declared for them. On a routed board this
  follows the copper rules of the neighbourhood rebuild (see "Copper: ownership, removal and rerouting").
- **In a neighbourhood rebuild:** a pour-joined group is lifted only whole, and keeps its members' relative poses.

**The module's constraints go with its members.** Each member stays bound by what its module script declares,
evaluated on the board:
- `Beside` and pin-relative places;
- link limits;
- turns and faces;
- keepouts and regions;
- pushes.

The module's declarations are carried with the stamped cell as data, the same terms the module's own resolve used, so
the board's refine judges a member exactly as the module's search did. A member moves only within what both its module
and the board allow.

**Room for decided members** (decided with the user, 2026-10-07; research/2026-10-07-refine-spike.md). On the fairing
core, 192 of 198 cell members are decided by their module (166 `Beside`, 26 fixed points), so a member bound to the
exact point its search picked could not move. A decided member, like any decided item, has the room its relation
describes: see "Each relation's room" below. The module scripts do not change. The module run writes a note of its
resolved constraints, carried with the stamp like the arrangement note:
- the rigid groups;
- each decided member's relation, with its target and its terms;
- the links;
- the bands dropped;
- the pads each module track touches.

The parent's refine reads each member's room from that note, in board coordinates.

**Identical cells.** Several cells stamped from one module may end up laid out differently. A module script can set
`rigid=True` on the stamp, or the board on the cell, to keep that cell as stamped, for example for channels that must
match.

**Scoring.** Members are scored by the one score like every other item.

## The pin study's pose check

A turned part carries its cell with it: an MCU turns its crystal, its bypass capacitors and its fanout. The same spot
may not be legal after the turn, though a spot nearby would be. For each pose the study judges, it therefore runs a
short refine with the part held at that turn and free to move within its declaration. It then finds the best map on
that board. The advice comes with the board the turn and remap need, and its score change.

## The pin study, in coarse refine

Decided with the user: refine places and turns every item with the pins as the capture has them. A part with a pin
pool is turned by refine like any other item, within what its declaration allows.

In coarse refine, for a part with a pin pool, the pin study runs on the one score (one-score spec):
- **at refine's pose:** the best map for the part where refine left it;
- **at the other poses its declaration allows:** for each, the part turned there and refined around the turn (see "The
  pin study's pose check"), with the best map for that pose. This catches a turn that pays only with a
  remap, which refine on the captured pins never takes.

It reports one piece of advice per part: the remap, and the turn if one is needed, with the score change of the two
together. It also writes the board that would result, so the user can see it before changing the capture. Nothing is
applied: a remap changes the capture and the firmware's pin assignments. When the user applies it in the capture, the
next run starts from the new pins, and refine works from there.

`--rank-remapped` and the separate pose search in the study are removed: refine owns poses, and restarts rank on the
captured pins.

## Routing feedback

Between routes, fine refine takes the last route's open connections as a cost, and the neighbourhood rebuild takes
them as its seeds. An open connection is an obligation (a pad pair in a phase's fixed asked set) that is not a clean
join on the final board: `failed`, `joined_narrow`, joined under its width, or on a net with a DRC violation. Its
inputs come in two kinds, kept apart in the records and the report:
- **Router facts,** from the phase records (routing phases plan, Tasks 6a and 13): the obligation's ends (ref and pad),
  net, phase, asked widths and routed layers; whether it is joined on the final board and its delivered width; the
  router's outcome; and the router's failure evidence where it has any: the failed search per direction, `blocked_by`
  (pads by ref and pad, earlier tracks and routed copper by net), KRT's verdicts, and a `diagnosis` that may be
  `unknown`.
- **placemat's inferences,** from its own geometry on the routed board: the items whose bodies block an end's escape
  (2026-10-07-surface-escapes-design.md), and the items inside the obligation's corridor, the band of half-width
  `refine.rebuild_corridor_mm` round the straight line between its ends.

An inference is a candidate move target, never a cause: it is not written as a diagnosis, and the report names its
source.

**The cost term.** Each open obligation adds a term pulling its end items toward a placement where it routes: its
straight line's length, and its crossings with the copper earlier phases laid. Earlier phases weigh more. The weight
is `refine.feedback_weight`, in score units.

`placemat run` routes, refines with this term, and routes again, as the loop spec describes. There is no separate
command or flag.

## Neighbourhood rebuild

Fine refine's escalation, inside the same `placemat run` loop (loop spec, "Escalation"). Board-wide fine refine stays
and runs first. When its rounds stop improving the routed board (a plateau, below), the loop lifts a bounded group of
items round one open connection, tries arrangements of them that single moves cannot reach, and routes each one.
Restarts come after it, and begin only once it is exhausted with connections still open.

### Seeds

A neighbourhood is built round one open obligation, the seed. The seeds are taken in order:
1. by phase, earliest first;
2. within a phase, `failed` before `joined_narrow` and width failures, then by the router's evidence count (more
   blockers named first);
3. obligations whose corridors overlap are one seed.

A seed whose neighbourhood was exhausted (see "Plateaus") is not taken again until the incumbent changes.

### Selection and expansion

The neighbourhood starts from the seed's items and grows in rings until a bound stops it. Each lifted item carries the
reason it was taken.
1. **Ends:** the items holding the seed's end pads.
2. **Router blockers:** each `blocked_by` entry that names a pad (ref and pad) gives its item. An entry that names a
   net only (routed copper, an earlier track) gives the items with that net's pads inside the corridor.
3. **placemat's candidates:** items blocking an end's escape, then items inside the corridor, nearest the straight
   line first.
4. **Nearby:** other movable items within `refine.rebuild_radius_mm` of the corridor, nearest first.

Each item taken brings its closure:
- **its unit:** the whole row, block, pour-joined group or `rigid=True` cell it belongs to;
- **its dependants:** the items whose relations refer to it, which are re-placed within their rooms (see "Moves are
  checked whole");
- **its module:** for a cell member, the other refinable members of its cell that lie inside the region.

The neighbourhood crosses module boundaries: members of several cells and standalone parts may be lifted together, each
bound by its own record. Held items (see "What refine does", item 2) are never lifted; they stay as obstacles, and the
report names those inside the region with the reason each is held.

**Bounds.** At most `refine.rebuild_items` items are lifted. Rings 1 and 2 and their closures are taken first; rings 3
and 4 fill what remains. A closure is taken whole or not at all. If rings 1 and 2 with their closures exceed the bound,
the seed is skipped and the report says which closure was too large.

**The region.** The lifted items' current courtyards and the seed's corridor, grown by `refine.rebuild_margin_mm`.
Lifted items are placed only inside the region, within their records. Everything outside it, and every held item
inside it, stays where it is.

### Arrangements tried

Each strategy produces whole arrangements of the lifted items, from a seeded stream. Strategies alternate between
proposals, so consecutive proposals for one neighbourhood differ in kind:
- **reconstruct:** the search's own construction re-places the lifted items in the region, one at a time, by the one
  score plus the feedback term, in an order drawn from the stream (the seed's end items first in half the draws);
- **reorder:** the lifted items' slots permuted as a set (a cycle or a reversal of a row of items), each item then
  settled in its slot within its record;
- **turn together:** the seed's end items set to a combination of their allowed turns and faces, with the rest of the
  neighbourhood reconstructed round them;
- **anneal:** a short anneal confined to the neighbourhood, at `refine.rebuild_temp`, starting from one of the above.
  It returns the best legal state it visited.

**Distinct proposals.** A proposal's signature is the set of (item, place rounded to `refine.rebuild_distinct_mm`,
turn, face). A proposal whose signature matches the incumbent's or an earlier proposal of the same neighbourhood is
dropped before routing.

**Screening.** `refine.rebuild_candidates` legal, distinct arrangements are generated per neighbourhood and ordered by
the run score plus the feedback term. They are routed best first, until the neighbourhood plateaus or a budget runs
out.

### Constraints

Every proposal is checked whole against the lifted items' records before it is routed (see "Moves are checked
whole"): fixed places, one-axis and edge movement, relations and their rooms, link and push limits, allowed turns and
faces, keepouts, rule areas and regions, rigid units and pour-joined groups, and declared copper. A proposal that
fails is refused whole, is not routed and does not count towards a plateau. The same check runs again on the routed
board before a proposal can be accepted.

### Copper: ownership, removal and rerouting

Every copper item on the routed board has a stable id (its KiCad uuid) and a record: kind (track, arc, via, pour), net,
layer, width, owner, and the obligations whose joining path it lies on. The owner is one of:
- **declared:** copper the board script declares. Never removed by a rebuild. An item whose move would break a
  declared plan is held (see "The script's constraints bound every move").
- **module:** a cell's own copper (`owner` = the cell, kicad/read.py `_copper`). Its obligations are the pad pairs the
  members note records for each module track, at the module's widths.
- **phase:** copper a routing phase laid, owned by that phase and by the obligations whose path it carries.
- **plane:** plane and fill zones. Never removed; refilled on the proposal's board before its DRC.

A proposal removes, from a copy of the incumbent's board:
1. module and phase copper with an end on a lifted item's pad;
2. module and phase copper whose shape meets the region;
3. then copper left with no path to a pad of its net (a dangling stub).

The obligations to reroute are then every obligation, in any phase, that is not a clean join on the remaining copper
and either was a clean join on the incumbent (the removal broke it) or has an end on a lifted item (the seed among
them), together with the obligations of each removed module track. Each keeps its phase, its
asked widths and its layers. Obligations the removal did not break keep their copper, with the same ids.

The proposal is routed with the router's `--connections` on those obligations only, phase by phase in phase order, with
the kept copper fixed (locked as a phase's copper is between phases). This local reroute is used to judge proposals;
the loop routes the final placement once through every phase before it reports (loop spec, step 9). Deleting copper from a pcbnew board uses
`board.Delete` (project rule).

**One obligation set for the comparison.** A module track's obligation is not in any phase's asked set, since its pads
were joined on the input board. Both the proposal and the incumbent are therefore judged on the same set: each phase's
asked set plus the removed module tracks' obligations, which join the phase that selects their net (the first phase
when none does). The incumbent's final board is re-judged on that set, so it is not penalised by obligations it carries
already.

### Judging and rollback

The loop holds the incumbent, the best routed board so far, apart from the working state: every item's pose, every
copper item's record by id, the phase records and its `score.rank` standing. A proposal is built and routed on a copy;
the incumbent's files are never edited in place.

A routed proposal is judged on its final board: DRC against the baseline, each phase's obligations re-judged, widths
on each obligation's path, the checks, and the run score, as for any routed board. It replaces the incumbent only
when `score.rank` puts it above (-1). A tie keeps the incumbent, and an invalid board never replaces a valid one.

A proposal that ranks lower, ties, fails the constraint check, or whose route call fails (a router error, a timeout, a
stop) is discarded, and the working state is restored from the incumbent: every pose, and every copper item with its
id, geometry, net, layer and width. A stopped run resumes from the incumbent (see the loop spec, "Cost and budget").

### Plateaus

Two levels, each counted in unsuccessful routed proposals: a proposal that reached routing and did not rank above the
incumbent. Proposals refused by the constraint check, dropped as duplicates, or screened out are not counted. Every
count resets when the incumbent improves.
- **Board-wide fine refine** has plateaued after `loop.plateau` unsuccessful routed rounds in a row, each refined from
  the incumbent with a fresh seed, or after a round whose refine moves nothing a phase depends on.
- **A neighbourhood** is exhausted after `refine.rebuild_plateau` unsuccessful routed proposals, or when its candidates
  run out. The loop then takes the next seed. On a second visit to a seed after the incumbent changed, the
  neighbourhood grows by one ring.

After an accepted rebuild the loop goes back to board-wide fine refine from the new incumbent, since single moves may
now improve it.

### Budgets

- `refine.rebuild_items`: the most items lifted at once.
- `refine.rebuild_neighbourhoods`: the most neighbourhoods tried in one run.
- `refine.rebuild_candidates`: arrangements generated per neighbourhood.
- `refine.rebuild_plateau`: unsuccessful routed proposals before a neighbourhood is exhausted.
- `loop.route_calls`: every route call in the run, board-wide rounds and proposals together, a budget apart from the
  others.

Defaults are chosen by measurement on the bench and the reference set (see "Settings"); until measured, each is marked
provisional in the settings table.

## Explore with refine

Each explore variant is refined before it is scored, so variants are compared at their refined best. A variant then
costs its resolve plus refine's few seconds. Explore keeps its role of reaching different constructions: a restart searches every item again
from nothing (`--fresh`), with different random choices of spot and order, so it can land in an arrangement that
moving items one at a time from the current board would never reach. The chosen variant becomes the snapshot.

## Settings

- `refine.enabled`: on by default.
- `refine.moves`: the budget.
- `refine.start_temp` and `refine.end_temp`: in score units.
- `refine.nudge_steps`: how far a nudge goes.
- `refine.move_weights`: the share of each move kind.
- `refine.seed`.
- `refine.feedback_weight`: the weight of an open connection's term, in score units.

The neighbourhood rebuild's settings. The defaults below are provisional, and each is marked so in the settings table
until a sweep on the bench and the reference set chooses it (see the roadmap's rebuild gate):
- `refine.rebuild`: on by default; off turns the escalation off, for a measurement.
- `refine.rebuild_items`: the most items lifted at once. Provisional 12.
- `refine.rebuild_radius_mm`: how far from the corridor nearby items are taken. Provisional 3.0.
- `refine.rebuild_corridor_mm`: the corridor's half-width round an open connection's straight line. Provisional 0.5.
- `refine.rebuild_margin_mm`: how far the region extends past the lifted courtyards and the corridor. Provisional 1.0.
- `refine.rebuild_candidates`: legal, distinct arrangements generated per neighbourhood. Provisional 16.
- `refine.rebuild_plateau`: unsuccessful routed proposals before a neighbourhood is exhausted. Provisional 3.
- `refine.rebuild_neighbourhoods`: the most neighbourhoods tried in one run. Provisional 8.
- `refine.rebuild_distinct_mm`: the rounding of a proposal's signature. Provisional 0.25.
- `refine.rebuild_temp`: the confined anneal's temperature, in score units. Provisional: `refine.start_temp`.

The loop's budgets (`loop.plateau`, `loop.route_calls`) are in the loop spec.

`[cleanup]` settings are removed, with a migration entry. A `placemat.toml` that sets `cleanup.enabled = false` is told
that refine replaces cleanup, and that `refine.enabled = false` turns it off.

## What is reported

- **Run line:** "refine: 20000 moves, 312 kept, score 5574 -> 5210, 4.1 s", plus the items it moved and how far.
- **run.json:** `refine` with those numbers and the per-item moves.
- **Studio:** the refine moves shown as one step, with each moved item marked.
- **turn.better:** a notice only for turns refine may not take.
- **The movable set:** the count of movable items and members, and of held ones by reason (fixed point, `Pin`, rigid
  cell, pour-joined group, `--pin`, push or lane outside the native judge). Measured first on the reference set and the
  bench before the rebuild is built: research found 121 of 258 members of one large board touching a module pour, and
  a pour-joined group moves only whole.
- **The neighbourhood rebuild,** in run.json `refine.rebuild`, one record per neighbourhood:
  - the seed: phase, net, ends, the router's outcome and diagnosis;
  - each lifted item with its reason (`end`, `router_blocker` with the evidence entry, `escape_blocked`, `corridor`,
    `nearby`, `unit_of`, `dependant_of`, `module_of`), router facts and placemat's inferences named apart;
  - the held items inside the region, each with its reason;
  - the copper removed (ids by owner) and the obligations rerouted;
  - each proposal: strategy, signature, refused or dropped and why, routed or not, its standing, its rank against the
    incumbent, and the outcome (`accepted`, `ranked_lower`, `tie`, `route_failed`, `refused`, `duplicate`);
  - route calls and time.

  The run line and `watch --summary` render it at the edge, for example "rebuild: 3 neighbourhoods, 9 routed, 1
  accepted, first phase 14/15 -> 15/15".

## Testing

- **Determinism:** the same seed and board give the same moves, in parallel tests too.
- **Delta score:** a move's delta equals the change in the board's search score, computed whole, on synthetic boards.
- **Bounds:** no move breaks a hard constraint (fixed place, stated turn, `Near` radius, keepouts), and no move is
  illegal.
- **Run score:** a refine that would worsen the run score is undone.
- **Snapshot:**
  - a run starts at the last run's places and refines from there;
  - a changed declaration searches that item afresh;
  - `--fresh` ignores the snapshot;
  - an item with one free axis and narrowed turns moves only along that axis and between those turns;
  - a `.lock.json` is converted on the first run.
- **Bench:** run fixtures/bench.py in all three configs. Refine must not worsen any fixture's run score. The tally goes
  in the commit.
- **Fairing core:** the core copy, with and without refine, compared on run score, crossings, quick-route closure and
  time.
- **The speed gate,** before the full build.
- **The constraint record:** the search, refine and the final check agree on every item's legal poses, on the bench
  fixtures; a relation target's move re-places its dependants, and is refused whole when one has no legal pose.
- **Refine's best state:** refine ends at the best legal state it visited, not its last.

### The neighbourhood rebuild

- **Coordinated fixture** (`fixtures/rebuild/`, synthetic, project-agnostic). A routing phase restricted to one layer;
  two fixed connectors with their pins in the same order; between them a channel, bounded at its sides by placement
  keepouts that let tracks through and at its ends by the board edge so no track can pass round it, holding three two-pin parts of different lengths, packed end to end along the channel at minimum clearance,
  each lying across it with one pin toward each connector. Each part joins one pin of each connector, and the start
  order of the parts along the channel is a cycle of the connectors' order, so on one layer the nets must cross. The
  channel is narrower than any part is long, so no part can turn; the parts differ in length, so exchanging two parts'
  centres overlaps a neighbour; packed, no part can nudge or shift. The test asserts:
  - every single move in refine's move set from the start (each nudge, turn, flip, swap, shift) is refused, or routes
    to a board that does not rank above the start: enumerated, and routed with the real router;
  - board-wide fine refine plateaus with the connections still open;
  - the rebuild lifts the three parts, a reorder proposal puts them in the connectors' order, and the board routes to
    full clean closure and is accepted.
- **Rollback.** A proposal that ranks lower, a tie, and a proposal whose route call fails (a stand-in router that
  errors, and one that times out) each leave the working state equal to the incumbent: every pose; every copper item
  by id with its geometry, net, layer and width; the phase records and the standing. A run stopped during a proposal
  resumes from the incumbent.
- **Copper.** On a routed fixture: copper with an end on a lifted pad or meeting the region is removed, dangling stubs
  with it; declared copper and planes are never removed; an obligation the removal did not break keeps its copper ids;
  a rerouted obligation keeps its phase and widths; a removed module track's obligation is judged on both boards.
- **Constraint preservation.** A fixture with each kind inside one neighbourhood (a fixed point, a one-axis item, a
  `Near`, a `Beside` target with dependants, a link with a limit, a narrowed turn set, a fixed face, a keepout, a
  `rigid=True` cell, a pour-joined group, members of two cells): every proposal routed and the accepted board keep
  every lifted item within its record, held items unmoved, and rigid units and pour-joined groups at their relative
  poses. A generator forced to emit a violating arrangement is refused before routing, and nothing is applied.
- **Selection.** Seeds in phase order; ends and router blockers before placemat's candidates; closures taken whole; a
  seed whose closure exceeds `refine.rebuild_items` is skipped and reported; a neighbourhood spanning two cells.
- **Plateaus and budgets,** with a stand-in router: refused, duplicate and screened proposals do not count; counts reset
  when the incumbent improves; the loop escalates from board-wide refine to the rebuild to restarts, and goes back to
  board-wide refine after an accepted rebuild; route calls never exceed `loop.route_calls`.
- **Determinism:** the same seed and board give the same neighbourhoods and proposals.

## Out of scope

- Moving an item outside the room its record gives it, and changing the script. Refine changes only what the script
  leaves free.
- Pin remaps (capture changes).
- Re-planning a module pour round moved members: a pour-joined group still moves only whole, in refine and in the
  rebuild.
- GPU acceleration (docs/superpowers/research/2026-10-06/gpu-study.md: not worth it at this board size).

## Decided with the user

- Refine replaces the cleanup pass.
- The lock is removed. A run starts from the last run's placement, and the script's constraints say what is fixed.
- One command runs the whole loop: see 2026-10-06-place-route-loop-design.md.
- The neighbourhood rebuild is part of fine refine, as an escalation of the run loop, not a command (2026-10-07). It
  brings explore's unbuilt "phase two" (lift a cluster and rebuild it) into this design.
- A rebuild proposal reroutes only the obligations its removal broke. Before the loop reports its result, the final
  placement is routed once through every phase, so the reported board follows the routing phases rule that a phase's
  copper lasts for one route of one placement (2026-10-07).
- `loop.plateau` stays 1: a board-wide round that improves nothing escalates. It is tuned with the bench (2026-10-07).
- Whole-board restarts begin only after the rebuild is exhausted with connections still open: refine, then the
  rebuild, then restarts (2026-10-07).

