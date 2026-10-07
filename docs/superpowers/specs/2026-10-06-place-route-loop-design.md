# The place, route and score loop as one command

Status: draft for review, 2026-10-06; amended 2026-10-07 (the incumbent, escalation to the neighbourhood rebuild);
release line 0.100.x. Builds on 2026-10-06-routing-phases-design.md and 2026-10-06-refine-pass-design.md.

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
ever applied, and most advisory findings were ignored (docs/superpowers/research/2026-10-06/placement-inventory.md 3.4). The user wants one
command, or a few, that runs the loop the same way every time.

## The command

`placemat run <script>` runs the whole loop by default:

1. **Place:** the constructive search, starting from the last run's placement (the snapshot), with each item searched
   only where it is new or its declaration changed.
2. **Coarse refine:** poses and rough places of whole cells and every part, each pose tried with a short local refine. The
   pin study's remap advice comes from here.
2b. **Fine refine:** cell members freed (those not joined by module pours), and parts and members refined.
3. **Route** every phase in `placemat.toml`.
4. **Score:**
   - each phase's closure and width judgement;
   - the board-wide clean closure;
   - DRC;
   - the checks (current-path on the routed board among them);
   - the run score.
5. **Fine refine again,** from the incumbent with a fresh seed, with the open connections of each phase as a cost
   (refine spec, "Routing feedback"). Earlier phases weigh more. Between routes it uses the cheap routability proxies:
   crossings, congestion, and each open connection's straight line against the copper laid.
6. **Route again** if refine moved anything a phase depends on. The routed board replaces the incumbent only when
   `score.rank` puts it above; otherwise the incumbent is kept.
7. **Escalate** when step 5-6 rounds plateau with connections still open (see "Escalation"): the neighbourhood rebuild,
   then restarts.
8. **Stop** at full clean closure with no round improving, when every level has plateaued, when a budget runs out, or at
   `--rounds N` (default from settings).
9. **Route the final placement** once through every phase, as a fresh route, so the reported board follows the
   routing phases rule that a phase's copper lasts for one route of one placement. Rebuild proposals were judged on
   local reroutes; this route is the one reported (decided with the user, 2026-10-07).
10. **Write** the result: the board, the routed board, the snapshot, run.json, and one summary.

Both refine stages and the pin study (inside coarse refine) are part of every run, with no flag to ask for them. `refine.enabled = false` turns refine off,
for a measurement. The pin study runs only on a board with a part that has a pin pool.

Options:
- `--restarts N`: up to N fresh constructions (`--fresh`, different seeds) through the same loop, in parallel within
  `--jobs`, started only once the rebuild is exhausted with connections still open, and keep the best. This replaces `--explore SECONDS`.
- `--place-only`: steps 1-2 and the placement score, with no routing. This replaces `preview` for iterating placement.
- `--detach`: as now. `watch --summary` prints the loop's summary.

## The incumbent

The loop holds one incumbent: the best routed board so far by `score.rank` (one-score spec), with every item's pose,
every copper item's record by id (refine spec, "Copper: ownership, removal and rerouting"), the phase records and its
standing. Each round of refine and each rebuild proposal works on a copy. A routed board replaces the incumbent only
when `score.rank` puts it above (-1); a tie keeps the incumbent, and an invalid board never replaces a valid one. A
rejected or failed attempt restores the working state from the incumbent, poses and copper alike.

## Escalation

When routing stalls, the loop escalates in a fixed order, each level within the same `placemat run`:
1. **Board-wide fine refine** (steps 5-6): single moves over every movable item.
2. **Neighbourhood rebuild** (refine spec, "Neighbourhood rebuild"): a bounded group of items round one open
   connection, across module boundaries, lifted and rearranged together with the rest of the board held. Each
   arrangement is an atomic proposal, routed locally and judged by `score.rank`. After an accepted rebuild the loop goes
   back to level 1 from the new incumbent.
3. **Restarts:** fresh constructions (`--restarts N`) run through the same loop, levels 1 and 2 included. They begin
   only after the rebuild is exhausted with connections still open (decided with the user, 2026-10-07); a board that
   closes never pays for them. They reach arrangements a local change cannot.

**Plateau.** Each level is counted in unsuccessful routed proposals: an attempt that reached routing and did not rank
above the incumbent. An attempt the constraint check refuses, a duplicate of an earlier one, or one screened out
before routing is not counted. Counts reset when the incumbent improves.
- Level 1 has plateaued after `loop.plateau` unsuccessful routed rounds in a row, or a round whose refine moves
  nothing a phase depends on.
- Level 2 is exhausted when every seed's neighbourhood is exhausted (after `refine.rebuild_plateau` unsuccessful routed
  proposals each), or `refine.rebuild_neighbourhoods` have been tried.

The loop never enters level 2 on a board at full clean closure: the rebuild is for open connections.

## The summary

One summary, the same on the console, in run.json and in `watch --summary`, says:

- the board state: per phase, closure and open connections; the clean closure; DRC; checks failed;
- what limits it: the open connections by phase, and for each, the items whose placement most affects it (from refine's
  feedback term);
- what the loop changed this time: placements moved, phases improved, rounds run, and the escalation reached;
- each neighbourhood rebuilt: its seed connection, what was lifted and why (router facts and placemat's inferences
  named apart), what was held in its region and why, the arrangements tried and each one's outcome;
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
- `loop.route_when`: the threshold on moved items or proxy change that triggers a re-route;
- `loop.plateau`: unsuccessful routed rounds of board-wide fine refine before the loop escalates. 1 (decided with the
  user, 2026-10-07: a round that improves nothing escalates), tuned with the bench;
- `loop.route_calls`: every route call in one run (board-wide rounds and rebuild proposals together), a budget apart
  from the rounds. Provisional 24.

A rebuild proposal's route is local: only the obligations its copper removal broke, so it costs a fraction of a full
route. The rebuild's own bounds (`refine.rebuild_*`) are in the refine spec. Every default is marked provisional in the
settings table until chosen by measurement (roadmap, "Gates").

The loop is recoverable: a stopped run keeps its rounds and resumes.

## Testing

- **Loop order and stopping:** on a small fixture with a stand-in router, the loop stops when a round improves nothing,
  and keeps the better of two rounds.
- **Ranking by `score.rank`:** a round that improves a later phase and worsens an earlier one is undone; a round that
  routes more but leaves the board invalid is undone; a tie keeps the incumbent.
- **Escalation order,** with a stand-in router: board-wide refine, then the rebuild after `loop.plateau` unsuccessful
  routed rounds, then restarts, which start only once the rebuild is exhausted with connections open; back to
  board-wide refine after an accepted rebuild; no rebuild or restart at full clean closure; the final placement is
  routed once through every phase before the result is written;
  route calls never exceed `loop.route_calls`.
- **Rollback:** a rejected round or proposal, and one whose route call fails, leaves the incumbent's poses, copper ids
  and records unchanged; a run stopped mid-proposal resumes from the incumbent.
- **Coordinated rearrangement:** the refine spec's rebuild fixture, run through `placemat run`, reaches full clean
  closure through the rebuild where board-wide refine plateaus.
- **Restarts:** `--restarts` with fixed seeds is reproducible, and keeps the best.
- **The summary:** its records and its text, produced at the edge.
- **Real-board gate:** the fairing core from a clean script with phases. The loop's result is compared with the
  organic script's best routed board.
- **Rebuild gate** (roadmap, "Gates"): measured as useful optimisation, not proposal throughput: end-to-end time and the
  final board's rank, legal proposals, distinct items lifted, proposals accepted, and the rank gained per minute, with
  `refine.rebuild` on and off.

## Out of scope

- Routing with the full (non-quick) route inside the loop. The final route can be a full one, with `--final full`.
- Changing the capture, such as pin remaps. These are reported for the user.
- Another command or flag for the neighbourhood rebuild: it is a level of the loop.

