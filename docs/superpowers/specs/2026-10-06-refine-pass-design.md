# Refine: detailed placement after the search

Status: draft for review, 2026-10-06.

## Problem

Trying a placement change costs a full resolve: 10-45 s on the fairing core after one statement changes
(scratchpad/latency/report.md), and an explore variant costs 4-7 minutes there. There are far more positions, turns
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

From the inventory (scratchpad/placement-inventory.md, file:line there):

| Feature | Today | After |
|---|---|---|
| Cleanup pass (`cleanup.py`, `_cleanup` layout.py:8596) | Greedy shift and swap on HPWL, parts only. Off on the fairing boards | **Replaced by refine.** Its shift-to-the-optimal-region move is kept as one of refine's moves |
| Search score `Scorer` (layout.py:829) and native `NativeScoring` (lib.rs:802) | Scores one item against the placed board | **Refine's score.** A move is judged by the score that placed the item |
| Incremental ratsnest, lift/unlift/commit (occupancy.py:1216-1245) | Refreshes only touched nets | **Used as is** by refine's moves |
| turn.better (`_report_turns`) | Reports a better turn and suggests the edit | For movable items, **refine takes the turn itself** and turn.better no longer reports it. It stays for turns the script or a stated constraint owns, where only the user can change it |
| Explore (`explore.py`) | Re-runs the construction with random choices and order. The best variant goes to the lock | **Kept, as restarts** (fresh constructions from a different seed, then refined): it reaches arrangements a local pass cannot. Each variant is refined before it is scored, so variants are compared at their refined best |
| Lock (`lock.py`) | Pins each searched item where an explore put it | **Removed.** Each run starts from the last run's placement, and the script's constraints hold what must not move (see Starting from the last run) |
| Pin study (`pinmap*`) | Pin remap and pose: advice, a capture change | **Kept.** A remap is a capture change refine cannot make. Its pose turn gains the legality check it lacks: the MCU's 45-degree turn needed the coin moved afterwards |
| Give-way, settle, scan | Construction | **Kept.** Refine depends on them |
| Global solve (`solve.py`) | Optional hints, off by default; measured no better once cleanup runs | Unchanged. Revisit after refine is measured |
| Suggestions, probe | Script edits; never used on the fairing boards (no applied.jsonl, no probes) | Unchanged here. Refine moves placement where the script leaves it free, so fewer findings need an edit |

Agents ignored the advisory findings (escape_crossed, link_over, every suggestion) and acted on what changes the board
(explore accept, the lock, the pin remap with approval). Refine follows that: it applies improvements the script allows,
and reports only what it may not change.

## What refine does

After the searched tier and before the late copper (where cleanup runs now), refine:

1. **Holds the board** as the search left it. Firm items, decided items and declared copper stay as they are.
2. **The movable set** is every searched part and cell, using the `_cleanup_movable` rule (layout.py:8543) widened to
   cells, less:
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
- **Pins live in the script.** An item that must not move is placed by its constraint. The forms already exist:
  - a fixed or edge place;
  - one free axis, for example `Centre` on a line, so the item slides only along it;
  - a stated turn, or `rotations=` narrowed to the allowed turns, for example `(0, 180)`;
  - `Near` with a radius.

  Refine moves an item only within what its declaration leaves free. An item that may slide only along the Y axis
  between turns 0 and 180 is nudged only along Y, and turned only between those two.
- **Removed:**
  - `placemat lock` and its subcommands;
  - `<stem>.lock.json`;
  - `freeze`, which wrote lock entries into the script.

  Explore `--accept` writes the chosen variant as the snapshot. `route --adopt` keeps its routes, and no longer locks the
  items they join: a kept route that no longer fits its pads is dropped with a reason, as today.
- **Migration.** On its first run, a script with a `.lock.json` converts the entries into the snapshot, and says so. The
  migration entry tells the user to state as constraints any item that was held on purpose.

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
- GPU acceleration (scratchpad/gpu-study.md: not worth it at this board size).

## Decided with the user

- Refine replaces the cleanup pass.
- The lock is removed. A run starts from the last run's placement, and the script's constraints say what is fixed.
- One command runs the whole loop: see 2026-10-06-place-route-loop-design.md.
