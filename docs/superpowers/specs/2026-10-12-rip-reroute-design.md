# Rip and reroute of earlier copper

Status: draft for review, 2026-10-12; ships in 0.100.0 with step 2 (docs/superpowers/plan-0.100-index.md).

## Problem

A routing phase's router calls each lock their copper before the next call reads the board (kicad/phase_run.py
`route_calls`, `lock_copper` after every call; kicad/route.py:474-490). The router never rips a net with locked copper:
KRT reads it as protected `locked`, which no flag lifts (KRT py_router/protected_nets.py:297-305, :412-437). So a later
call that is blocked by an earlier call's copper leaves its connection open, and the run says so only as a hint.

Two reference cases show it:

- pic_programmer (b): the signals phase makes two calls, `--nets VCC` (the POWER class, clearance 0.28) then
  `--nets * !GND !VCC`. The second leaves /pic_sockets/VCC_PIC JP1.2 to U6.1 / Q3.1 open; the router names VCC as the
  pre-existing net it may not rip (gate-diagnosis.md section 6). The blocking copper is from the same phase's first
  call.
- usb-c-power-adapter (b): about 4 connections at U1 and U2 are walled by the current phase's outer copper
  (Net-(U2-V_{CIN}) at 2.39 mm, +12V at 3.76 mm, Net-(L1-Pad1)), which the signals phase may not rip
  (usbc-starvation-report.md, "Open points").

Both are in `.superpowers/sdd/2026-10-07-routing-phases/`, with the code map in `rip-reroute-research.md` there.

## Decisions taken with the user (2026-10-12)

- Scope: any later router call may rip copper an earlier call laid, in the same phase or an earlier phase, when that
  copper blocks a connection the later call leaves open.
- placemat does it, with no router change (the research's option B):
  1. a call leaves a connection open, and the router names earlier-call copper blocking it;
  2. placemat removes that blocking copper (its connections: the obligations the earlier call joined with it);
  3. placemat reroutes the blocked connection;
  4. placemat reroutes the removed connections as `--connections` tasks, each at its own phase's width, layers and
     clearance;
  5. the result is kept only if the blocked connection joins clean and every earlier connection is judged clean
     again (DRC plus `judge_obligations`, as ruling S6 and `recheck_final_phases` do); otherwise the board is
     restored to what it was before the attempt.
- Earlier calls keep their priority: their copper is moved, never dropped. Copper the script declares is never
  ripped.

This changes one rule of the routing-phases spec (docs/superpowers/specs/2026-10-06-routing-phases-design.md, "Goal":
"its copper is fixed for the phases after it"; "Running": "A phase's copper is locked (`lock_copper`) before the next
phase runs"). Copper stays locked for the router; placemat itself may move it under the rules below.

## Terms

- **Call**: one router call of a phase, as `phase_run.plan_calls` plans it (kinds `pairs`, `pour`, `bus`,
  `bus_tasks`, `tasks`, `nets`, `rest`). A task call's deferral sub-calls (`route_tasks`) count as one call.
- **Script copper**: every track, arc and via on the route's input board (`work/in.kicad_pcb`), keyed as
  `route.routed_copper` keys copper: (kind, net, layer, ends rounded to 0.1 um). With `--only`, everything on the given
  board is script copper.
- **Router copper**: every track, arc and via on a board that is not script copper.
- **Blocked unit**: one net's connections that one call left open, with the nets the router named for that net.
- **Victim**: a named net whose router copper an attempt removes.
- **Owner** of a removed connection: the phase whose settings it is rerouted at.
- **Attempt**: steps 2-5 for one blocked unit.

## What triggers an attempt

After each call of a phase, before the next call reads its board, placemat reads the call's blocker evidence. Only
structured fields are read; the router's prose hints are not parsed.

| Call kind | Blocked units | Named nets |
|---|---|---|
| `tasks`, `bus_tasks`, `pour` (its task stage) | each net with a `failed` record in the call's `--connections` records (`TaskRun.records`), its failed tasks as the unit's connections | each record's `evidence.blocked_by` entry with `found_by == "preexisting"`, or with `found_by == "static"` and `kind == "track"` (KRT docs/connections.md, "Failure evidence") |
| `nets`, `rest`, `bus` | each net in the summary's `net_evidence` (nets still failed at the end of the call) | that net's `net_evidence[net].blocked_by` entries as above, and every `blocked_by[*].net` of the summary's `blockers` entries with `net == net` and `stage == "preexisting"` (KRT route.py:4615-4625) |
| `pairs` | none: the pair router writes no per-connection evidence | - |

Both the `blockers` list and `net_evidence` are read for whole-net calls because pic_programmer's case is recorded
only in `blockers` (`{"net": "VCC", "preexisting": true}`); its `net_evidence` record was replaced by the reconcile
pass's, with `blocked_by` empty (gate-diagnosis.md section 6). Named nets are kept in the router's order, each once.

A whole-net unit's connections are the open connections on that net on the call's output board, read from a DRC of
that board (`open_connections`), each with the widths phase i asks for that pad pair (phase i's obligation with the
same pad pair) or, when phase i does not ask that pair, phase i's width answer for the net (`width_policy` receipt,
the phase's entry for the net). A unit whose widths are unknown, or with an end that is not a pad, is not attempted.

A named net is a victim when all of these hold, otherwise it is listed as not ripped with the reason:

| Reason when it fails | Rule |
|---|---|
| `own_net` | it is not the blocked unit's own net |
| `no_router_copper` | it has router copper on the call's output board |
| `routed_by_call` | the failing call laid no copper on it: all of its router copper is on the call's input board |
| `pour_net` | it is not a pour net of the route (`ctx.pour_nets`) |
| `pair_net` | it is not a member of a pair any phase selects |
| `excluded` | it is not excluded from the route |

A unit with no victim is skipped (`no_victim`). A unit with more victims than `[route] rip_max_nets` is skipped
(`too_many_victims`), not trimmed.

## Which copper is removed

Every track, arc and via of each victim net that is router copper on the failing call's output board. Script copper
on the same net stays, and the reroute may use it. Copper of other nets, pads, zones, fills and graphics are not
touched. Items are taken off with `board.Delete(item)`, after `group.RemoveItem(item)` when grouped (CLAUDE.md). The
removal writes a new board (`p<i>_<k>_rip<a>_ripped.kicad_pcb`); the failing call's output is left as it was.

Since the failing call laid no copper on a victim, all of the victim's router copper was laid by earlier calls.

## The removed connections and their settings

The removed connections are of two sorts. Each is rerouted as one `--connections` task.

1. **Asked**: every obligation of phases 0..i (`RouteReport.asked`, after `width_policy.apply`) on a victim net
   whose two ends are joined on the failing call's output board (KiCad connectivity, `joined_pairs`). A pad pair two
   phases ask is rerouted once. Its owner is the earliest phase that asks it, and its widths are that obligation's.
   An obligation with no widths (`width_policy_unknown`) or with an end that is not a pad makes the unit skipped
   (`victim_width_unknown`, `victim_end_not_pad`).
2. **Unasked**: every open connection of a victim net on the route's input board (`open_connections` of
   `in.kicad_pcb`, computed once per route) that is joined on the failing call's output board and is not the pad pair
   of an asked one. These are joins a call made that no phase asks, such as the rest call's joins of a net an earlier
   `current_paths` phase named. Its owner is the first phase whose output board joins its two ends (phase i: the
   failing call's output board). Its widths are the owner's width answer for the net (the receipt's entry for that
   phase and net); with none, the unit is skipped (`victim_width_unknown`).

Each owner's settings are the ones its own calls used:

| Setting | Source |
|---|---|
| widths per layer | the obligation's widths (asked) or the owner's width answer (unasked) |
| layers | the owner's `Selection.layers` |
| clearance | the owner's clearance map: `net_clearance.merged(class, stated, ceiling(route router_args + the owner's router_args))` and its base clearance `routing_clearance(...)`, as `route_calls` builds them; one file per owner when the capture states clearances |
| neck-down, router flags | the owner's `neckdown` and `router_args`, after `[route] router_args` |
| bus | an owner's bus whose nets include victims routes those victims' tasks as a `bus_tasks` call with those nets |

The calls for one owner are planned by `plan_calls` from a Selection holding only that owner's tasks (and buses), so
tasks are grouped by (clearance, widths), widest clearance first, as a phase's own task calls are.

## The order of calls

For one attempt on the failing call's output board B:

1. Write R: B with the victims' router copper removed.
2. Reroute the blocked unit on R at phase i's settings:
   - a `tasks`, `bus_tasks`, `nets`, `rest` or `bus` call: the unit's connections as `--connections` tasks
     (`route_tasks`), phase i's layers, clearance map, neck-down and router flags;
   - a `pour` call: `pour_join.join_pour` again for the unit's net on R (drops, then a task for each group still
     apart), as ruling S22's rejoin does.
3. Reroute the removed connections, owner by owner in phase order, each owner's calls in `plan_calls` order, each on
   the board the one before it left (`route_tasks`, its deferral loop and copper locking as for any task call).
4. Judge the candidate C (the last board) and decide (next section).

Attempts run straight after the failing call, before the next call of the phase. After a kept attempt the next call,
and the next attempt, start from C.

## The keep or restore test

Placemat judges two boards with the same rules: B, the failing call's output (judged once per call, then each kept
candidate takes its place), and C. Each judgement is a DRC of a copy with guards off and zones filled (as
`judge_phase` does), `judge_obligations` for every obligation of phases 0..i with each phase's own input DRC as the
baseline (`phase_input_drc`, ruling S15), each outcome read from the phase's records as superseded by earlier kept
attempts, and the DRC's open items per net.

Each obligation has a rank: 2 clean (`is_clean`), 1 joined but not clean, 0 open. C is kept when all of these hold,
checked in this order; the first that fails is the attempt's `reason`:

| Reason | Check |
|---|---|
| `blocked_not_clean` | every connection of the blocked unit is clean on C (judged as an obligation with its widths) |
| `obligation_worse` | no obligation of phases 0..i has a lower rank on C than on B |
| `net_open_rose` | no net has more open items in C's DRC than in B's (this covers joins no obligation asks, and a pour split by a reroute) |
| `drc_new` | C's DRC has no real error (`drc.real_errors`, `[drc] real_kinds`) that B's lacks (`drc.new_errors`) |
| `off_layer` | every track the attempt laid lies on its owner's layers (phase i's for the blocked unit); vias are exempt |

A router failure inside an attempt (non-zero exit, a refused task, a timeout) restores too, with `router_failed`,
`router_refused` or `router_timeout` and the router's facts.

Restore means the phase goes on from B. Nothing is undone on disk: B was never written to.

The `off_layer` check covers the gap in `phase_run.width_shortfall` (copper on a layer the obligation has no width
for reads clean, phase_run.py:806-807) for the copper this work lays. The general judgement is unchanged.

## Limits

- `[route] rip_attempts` (default 4): attempts per call, kept or restored. 0 turns rip and reroute off.
- `[route] rip_max_nets` (default 3): victims per attempt.
- After a restored attempt, a later unit of the same call whose victim set is the same is skipped (`tried`).
- After a router failure, refusal or timeout in an attempt, the call makes no more attempts (`stopped`).
- Units past the attempt limit are skipped (`limit`).
- A unit whose connections an earlier kept attempt of the same call has joined is skipped (`joined_since`).

Units are taken in the order the router reports them (record order for tasks, `net_evidence` order for whole-net
calls).

## Cost

An attempt costs one board write, one router call for the blocked unit (more if the router defers tasks), one call
per owner group plus deferrals, one DRC and one obligation judgement of C. The first attempt of a call also costs
B's DRC and judgement. The judgement covers every obligation of phases 0..i, as `recheck_final_phases` does; on a large
board that is the main cost after the router calls.

## What is recorded

The phase record (route.json `phases[i]`, and the kept result's routed record) gains `rip`:

```
"rip": {
  "attempts": [
    {"call": 1, "attempt": 0,
     "blocked": [{"net": "N", "from": {"ref", "pad"}, "to": {"ref", "pad"}, "widths": {layer: mm}}],
     "named": [{"net": "V", "found_by": "preexisting" | "static"}],
     "victims": ["V"],
     "not_ripped": [{"net": "W", "reason": "pour_net"}],
     "removed": {"tracks": 39, "arcs": 0, "vias": 2, "track_mm": 81.4},
     "rerouted": [{"phase": "signals", "index": 1, "asked": true, ...the router's record of the task}],
     "blocked_records": [...the router's records of the blocked unit's tasks],
     "kept": true,
     "reason": null | "blocked_not_clean" | "obligation_worse" | "net_open_rose" | "drc_new" | "off_layer"
               | "router_failed" | "router_refused" | "router_timeout",
     "worse": [{"phase": "current", "net", "from", "to", "before": "clean" | "joined", "after": "joined" | "open"}],
     "open_rose": {"N": [before, after]},
     "drc_new": 0,
     "off_layer": 0,
     "router": null | {"code", "exit_code", "log"},
     "widths": [...route.width rows of the rerouted copper],
     "seconds": 12.3}],
  "skipped": [{"call": 1, "net": "N", "named": [...], "not_ripped": [...],
               "reason": "no_victim" | "too_many_victims" | "victim_width_unknown" | "victim_end_not_pad"
                         | "blocked_width_unknown" | "blocked_end_not_pad" | "joined_since" | "tried" | "limit"
                         | "stopped"}]}
```

Every field is a value or a record; no field is a sentence.

A kept attempt also changes:

- Phase i's `connections`: the blocked unit's records and phase i's own rerouted records supersede the earlier ones
  (`phase_run.superseded`).
- An earlier phase k's records are not rewritten (its kept result stays as it was routed). The final re-judgement
  (`recheck_final_phases`) reads phase k's outcomes from its records superseded by every kept attempt's `rerouted`
  records with `index == k`, so a stale outcome (a `joined_narrow` that was moved) is not carried over.
- Width rows (`RouteReport.widths`, the `route.width` findings) describe the final board: rows of a victim net from
  the calls that laid the removed copper are dropped, and the reroute calls' rows are added under the owner phase's
  name.

`RouteReport` gains no top-level field: everything is in `phases[i]["rip"]`. The kept-result digest moves to
`phase-judgement-v10`, and the two settings enter it through the `route_*` settings the digest already reads.

## Console

`route.phase_lines` renders the records:

- On phase i's line, each kept attempt: `; moved earlier copper: VCC_PIC JP1.2-U6.1 joined after moving VCC (signals,
  6 connections)`.
- Each restored attempt: `; restored: N A.1-B.2 after moving V: V C.1-D.2 would be open` (the first `worse` entry),
  `... N left with more open items`, `... 2 new DRC errors`, `... copper off its phase's layers`, `... not joined
  clean`, `... the router failed`.
- Skipped units with a reason other than `no_victim`: `; not moved for N: too many nets named (4)`, `... attempt limit`,
  `... same nets restored before`, `... width unknown`.
- On an earlier phase k's line, when a later kept attempt moved its connections: `; moved by phase signals: VCC`.

The studio's route view and the route record's replay are unchanged in this step.

## Interactions

- **Pour joins.** Pour nets are never victims. A `pour` call's failed task names its blocker like any task, and its
  step 2 is `join_pour` again on R for that net. A reroute that splits a pour raises the pour net's open items, and the
  attempt is restored (`net_open_rose`). Ruling S22's re-check of pour nets runs after the phase's last call, so it
  sees every kept attempt.
- **Pair phases.** Pair calls start no attempt, and pair nets are never victims: they are routed by the pair router
  (route_diff.py), with its gap and coupling, which a `--connections` task cannot state. A pair call's own failures
  stay as today.
- **current_paths phases.** Their tasks carry per-layer widths from the current, and their layers (the example
  phase's outer layers, D29). A removed connection owned by such a phase is rerouted at those widths and layers, and
  `neckdown = false` reaches the reroute call (`--no-power-tap-neckdown`). Its `pour_served` connections are on pour
  nets and are never moved. A current net's joins that only the rest call made are rerouted as unasked connections
  at the rest phase's width answer.
- **The kept-result chain.** A phase's saved board includes its kept attempts. A rerun that reuses phase i reuses
  them; one that reroutes phase i makes them again. Earlier phases' saved results are not touched.
- **`--only`.** All copper on the given board is script copper and is never ripped. The phase's own earlier calls'
  copper can still be moved by its later calls.
- **Buses.** A victim that belongs to an owner's bus is rerouted in a `bus_tasks` call with that bus's victim nets.

## Settings

| Key | Default | Unit | Meaning |
|---|---|---|---|
| `[route] rip_attempts` | 4 | count | attempts per router call to move earlier calls' copper that blocks a connection the call left open; 0 is off |
| `[route] rip_max_nets` | 3 | count | the most nets one attempt moves; a blocked connection whose router names more is not attempted |

## Changes to the routing-phases documents

- Spec, "Goal": a phase's copper is fixed for the router in later phases; placemat may move it when it blocks a later
  call (this spec).
- Spec, "Running": copper is locked before the next call, and may be moved by rip and reroute.
- Spec, "Testing": "copper locked between phases" stays; rip and reroute has its own tests (this spec's plan).
- Plan 2026-10-07-routing-phases.md, "Decisions": D32 records the user's decision of 2026-10-12 and points here.

## Testing

- Pure: blocker evidence per call kind; victim rules and their reasons; asked and unasked connections, owners and
  duplicates; each owner's calls (widths, layers, clearance, neck-down, bus); the verdict for every reason; the record
  shape; the console lines.
- Engine (real pcbnew and DRC, a stand-in router that lays straight or detoured tracks and names the copper it
  crosses as pre-existing): a kept attempt across phases; a kept attempt inside one phase (pic_programmer's shape); a
  restored attempt, with the phase's board equal to the failing call's output; script copper never ripped; a
  `current_paths` owner rerouted at its widths, layers and neck-down; limits; `--only`; the final re-judgement reading
  the reroute records.
- Real boards: pic_programmer (b) and usb-c-power-adapter (b) at a fixed placement against results.json, under a
  private realboard lock.

## Review Focus inputs

- A victim net with script copper and router copper: only the router copper goes; the reroute starts from the
  script copper.
- A victim whose joins belong to two phases (a `current_paths` task at its current widths, and the rest call's joins
  at the class width): each is rerouted at its own owner's settings.
- An obligation of a later call of phase i that is open on B: open on C is not `obligation_worse`.
- A restored attempt: phase i's next call reads B's file, unchanged (compare digests).
- The final re-judgement of an earlier phase after a kept attempt: it reads the reroute record, not the original
  (`joined_narrow` before, `routed` after).
- A reroute that splits a pour net: restored with `net_open_rose`.
- A named net that has only script copper: not ripped, `no_router_copper`.
- usb-c-power-adapter: its blockers may be named only in the router's prose sentence about protected nets within 3 mm
  (KRT routing_diagnostics.py:509-545), which carries no structured names. If no structured field names them, no
  attempt starts there; the measurement task reports that to the user rather than reading the prose.
- A stop during an attempt, then a rerun: phase i routes again from its input (the attempt is not resumed half-way).

## Out of scope

- A router change (protection instead of locking, `--rip-existing-nets`, per-net layer masks): options A and C of the
  research.
- Ripping pair or pour copper.
- Showing attempts in the studio's route view.
