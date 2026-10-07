# Refine: detailed placement after the search

Status: draft for review, 2026-10-06; release line 0.100.x.

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

A restart runs both stages from its own fresh construction.

## What refine does

After the searched tier and before the late copper (where cleanup runs now), refine:

1. **Holds the board** as the search left it. Firm items, decided items and declared copper stay as they are.
2. **The movable set** is every searched part and cell, and the refinable members of cells (see "Cells: placed whole,
   refined as members"), using the `_cleanup_movable` rule (layout.py:8543) widened to cells, less:
   - an item another declaration is placed against, such as a `Beside` target or a row member;
   - an item whose turn or place a stated constraint owns: `rotation=` set, `Facing`, `Turned`, a `why=` that names a
     turn, `Near` with a radius, which stays a hard bound.
   An item placed from the snapshot is movable like any other.
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
7. **Ends** by scoring the whole board with the run score. If the run score is worse than before refine (the move
   score is an estimate of it), the board before refine is kept and a notice says so.
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

So the display FFC connector, declared on the board's N-S centre line with `rotations=(0, 180)`, is only nudged along
that line and only turned between 0 and 180, because that is what its declaration leaves free. Nothing is added to the
script for refine.

The check: for each accepted move, the item's new place, turn and face must be in the set the search's own scan would
accept for that item. A test asserts this over the bench fixtures.

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
  the routing phases to be routed again, keeping the width the module declared for them.

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
core, 192 of 198 cell members are decided by their module (166 `Beside`, 26 fixed points), so a member bound only to its
exact declared place could not move. A decided member therefore has room within what its declaration means:
- a `Beside` slides along its side, and its gap may grow up to `refine.member_slack_mm`, a setting with a documented
  default, set by measurement;
- other relations keep their own meaning: a member placed at a pin stays on that pin's side;
- turns stay as declared;
- a fixed datum point stays fixed.

The module scripts do not change. The module run writes a note of its resolved constraints, carried with the stamp like
the arrangement note:
- the rigid groups;
- each decided member's relation and its room;
- the links;
- the bands dropped;
- the pads each module track touches.

The parent's refine checks members against that note, in board coordinates.

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

## Routing feedback (after routing phases)

Once routing phases exist, refine can take the last route's failures as a cost: each connection a phase left open
adds a term pulling its ends' items toward a placement where it routes, such as a shorter straight line or fewer
crossings with the phase's copper. That makes "route, see what failed, nudge" one step: `placemat run --route --refine`
routes, refines with the route's failures, and routes again, up to a count.

This needs the phases' per-connection outcomes. It is a second phase of this design, specified once routing phases
are built.

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

`[cleanup]` settings are removed, with a migration entry. A `placemat.toml` that sets `cleanup.enabled = false` is told
that refine replaces cleanup, and that `refine.enabled = false` turns it off.

## What is reported

- **Run line:** "refine: 20000 moves, 312 kept, score 5574 -> 5210, 4.1 s", plus the items it moved and how far.
- **run.json:** `refine` with those numbers and the per-item moves.
- **Studio:** the refine moves shown as one step, with each moved item marked.
- **turn.better:** a notice only for turns refine may not take.

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

## Out of scope

- Moving firm or decided items, and changing the script. Refine changes only where the script leaves an item free.
- Pin remaps (capture changes).
- Large neighbourhood search: lift a cluster and rebuild it, explore's unbuilt "phase two". Revisit after refine is
  measured.
- GPU acceleration (docs/superpowers/research/2026-10-06/gpu-study.md: not worth it at this board size).

## Decided with the user

- Refine replaces the cleanup pass.
- The lock is removed. A run starts from the last run's placement, and the script's constraints say what is fixed.
- One command runs the whole loop: see 2026-10-06-place-route-loop-design.md.
