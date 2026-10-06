# The place, route and score loop as one command

Status: draft for review, 2026-10-06; release line 0.100.x. Builds on 2026-10-06-routing-phases-design.md and 2026-10-06-refine-pass-design.md.

## Problem

Getting a board from a script to a routed, judged layout takes many commands in an order only the skill knows:
1. preview;
2. run;
3. explore with `--accept`;
4. route;
5. adopt;
6. check;
7. read the findings;
8. lock, release, or freeze.

Agents follow it unevenly. In the fairing repos, explore and accept were used often, cleanup was off, no suggestion was
ever applied, and most advisory findings were ignored (scratchpad/placement-inventory.md 3.4). The user wants one
command, or a few, that runs the loop the same way every time.

## The command

`placemat run <script>` runs the whole loop by default:

1. **Place:** the constructive search, starting from the last run's placement (the snapshot), with each item searched
   only where it is new or its declaration changed.
2. **Coarse refine:** poses and rough places of whole cells and parts, each pose tried with a short local refine. The
   pin study's remap advice comes from here.
2b. **Fine refine:** cell members freed (those not joined by module pours), and parts and members refined.
3. **Route** every phase in `placemat.toml`.
4. **Score:**
   - each phase's closure and width judgement;
   - the board-wide clean closure;
   - DRC;
   - the checks (current-path on the routed board among them);
   - the run score.
5. **Fine refine again,** with the open connections of each phase as a cost. Earlier phases weigh more. Between routes it
   uses the cheap routability proxies: crossings, congestion, and each open connection's straight line against the
   copper laid.
6. **Route again** if refine moved anything a phase depends on. Keep the result only if the phases' closures improve,
   in phase order, then the clean closure. Otherwise go back to the result before.
7. **Repeat** steps 5-6 until an iteration improves nothing, or `--rounds N` (default from settings) is reached.
8. **Write** the board, the routed board, the snapshot, run.json, and one summary.

Both refine stages and the pin study (inside coarse refine) are part of every run, with no flag to ask for them. `refine.enabled = false` turns refine off,
for a measurement. The pin study runs only on a board with a part that has a pin pool.

Options:
- `--restarts N`: run N fresh constructions (`--fresh`, different seeds) through the same loop, in parallel within
  `--jobs`, and keep the best. This replaces `--explore SECONDS`.
- `--place-only`: steps 1-2 and the placement score, with no routing. This replaces `preview` for iterating placement.
- `--detach`: as now. `watch --summary` prints the loop's summary.

## The summary

One summary, the same on the console, in run.json and in `watch --summary`, says:

- the board state: per phase, closure and open connections; the clean closure; DRC; checks failed;
- what limits it: the open connections by phase, and for each, the items whose placement most affects it (from refine's
  feedback term);
- what the loop changed this time: placements moved, phases improved, rounds run;
- what only the user can change: findings about script-owned constraints (a turn the script fixes, a fixed item in the
  way, a capture change such as a pin remap), each with its suggestion.

An agent reads this one summary instead of several logs and finding lists.

## Commands that remain

- `placemat route <script> --phase NAME` / `--only`: routing one phase (routing phases spec).
- `placemat check`, `placemat apply`, `placemat watch`, `placemat studio`: as now.
- Retired:
  - `preview` (becomes `run --place-only`);
  - `--explore` (becomes `--restarts`);
  - `lock` and `freeze` (the snapshot replaces them);
  - `route --adopt` stays for keeping copper deliberately.

## The skill

SKILL.md teaches one loop:
1. state the constraints in the script and the capture, each with its reason;
2. state the routing phases;
3. run `placemat run --detach`, and follow it with `watch --summary`;
4. act on the summary's "what only the user can change";
5. repeat.

The command list moves to the references.

## Cost and budget

A quick route of the fairing core takes about 5 minutes. A loop of three rounds is therefore about 15-20 minutes,
plus the restarts in parallel. The defaults are set from measurement once phases and refine exist:
- `loop.rounds`;
- `loop.route_when`: the threshold on moved items or proxy change that triggers a re-route.

The loop is recoverable: a stopped run keeps its rounds and resumes.

## Testing

- **Loop order and stopping:** on a small fixture with a stand-in router, the loop stops when a round improves nothing,
  and keeps the better of two rounds.
- **Phase-first ranking:** a round that improves a later phase and worsens an earlier one is undone.
- **Restarts:** `--restarts` with fixed seeds is reproducible, and keeps the best.
- **The summary:** its records and its text, produced at the edge.
- **Real-board gate:** the fairing core from a clean script with phases. The loop's result is compared with the
  organic script's best routed board.

## Out of scope

- Routing with the full (non-quick) route inside the loop. The final route can be a full one, with `--final full`.
- Changing the capture, such as pin remaps. These are reported for the user.
