# Placement improvement in placemat: an inventory

Read-only survey of placemat main (69cd5655), the turn-all worktree (uncommitted),
the fairing repos (fairing-instrument, fairing-instrument-fresh) and KRT-upstream.
Paths are under src/placemat/ unless given in full. Costs marked "measured" come
from run records or design docs; the rest are read from the code.

## 1. The scores

There are three objectives in play, and they differ.

| Score | Where | What it counts | Scope |
|---|---|---|---|
| Search score (`Scorer`) | layout.py:829-919 | weighted pad-to-pad distance to every placed pad on a pulling net (a clique: `_targets`, layout.py:4831) + `score.push` x push value/limit + `score.crossing` x crossings of the item's leaf airwires (each pad to its net's nearest placed anchor, `Ratsnest.leaf_costs`, ratsnest.py:255) + escape crossed/closed/walled weights + `score.escape_lane` per blocked lane | one item, against everything placed; prunes once the wire alone reaches the best seen (`prune=True`) |
| Native search score (`NativeScoring`) | native/src/lib.rs:802; built in `Scorer.native` layout.py:892 | the same formula, inside the native sweep | one item per candidate; not available when the item has a push or a declared lane |
| Cleanup score (`PartScore`) | cleanup.py:154-226; native `NativeCleanupScoring` lib.rs:909 | HPWL of the part's pulling nets + declared links weight x length + the same crossing and escape terms; `_OVER` past a link limit or satellite limit | one part (or a pair, for a swap) |
| Run score (`score.total` over `plan_measures`) | score.py:40-70, 112-172 | unplaced by priority, DRC, link excess, findings by kind, true ratsnest crossings (full MST of every net, `crossings`), airwire length, give-way costs, pushes, back-face items, RUDY steps (explore) | whole board, after a full resolve |
| Pin study score | native/src/pinmap.rs (Scorer 388, Tally::delta 573); weights in settings.py:329-337 | weighted crossings of the studied nets' routed airwires (pairs x5, impedance x3) + 0.25/mm length + bend + soft-group spread | the studied part's nets; incremental per move |

Notes:
- The search's wire term is a clique of pairwise distances, so with the item lifted,
  `Scorer(new) - Scorer(old)` is the exact change in the board's weighted wire sum.
  The crossing term is an estimate (leaf airwires to nearest anchor), not the change in
  the true MST crossings the run score counts.
- Cleanup does not use the search's wire term: HPWL instead of the clique, links only
  where declared. Its moves are therefore judged on a different objective from the
  one that placed the parts.

## 2. Features that move, re-place, re-turn or re-score placed items, or search alternatives

Columns: when it runs / does it change placement / cost per evaluation and whether
incremental / which score / file:line.

### Constructive resolve (the search)

**Step search: `place_ranked`, `_settle`, `placer.scan`**
- Runs: during the resolve, one item at a time, firm items then searched in rank order
  (`place_ranked` layout.py:8104; searched loop 8124-8140; `_next_to_place` 9981).
- Changes placement: yes; each item is placed once and never revisited by the search.
- Cost: `scan` (placer.py:236-660) coarse lattice, half lattice, fine grid, then
  refinement round the `place_refine_spots` best (3). Native sweep: about 1.1 us per
  candidate for legality and score (measured, docs/superpowers/specs/2026-09-25-native-
  sweep-design.md:241); a single Python `legal()` is about 30 us (same doc :61).
  Per searched item on the fairing core: about 0.85 s (36 items, 31 s; run 28770367).
- Incremental: yes, one item against the placed board.
- Score: `Scorer` (or native), plus give-way costs (placer.py:337) and per-arrangement
  extras (`_total_at` layout.py:11053).
- `_settle` (layout.py:10615) picks the hint: lock spot, then Near, solve hint, seed
  hint, band/tangent frame, push-wide, else a pocket (`_settle_in_pocket` 8644).
- Face.EITHER: both faces scanned (`_scan_faces` layout.py:11215), back face priced
  `score.back_face`. This is the only "flip" move.
- Cell arrangements: each arrangement scanned and the best total kept
  (`_scan_arrangements` layout.py:10934).

**Seed hints: `_seed_hint`** (layout.py:4933)
- Runs: during the resolve, before a scan. Weighted centroid of the placed pads the item
  connects to. A hint only; the scan decides. Cost: trivial.

**Global solve: `_global_hints`, `solve.global_solve`** (layout.py:4873; solve.py:170)
- Runs: once per resolve at the first searched item, when `solve.enabled` (default off,
  settings.py:485).
- Changes placement: only as hints; a hint that finds nothing legal is dropped and the
  item re-settled without it (layout.py:10712-10719).
- Cost: conjugate-gradient quadratic placement with bisection spreading, whole netlist,
  once. Score: spring energy (wire), not the search score.
- Measured: no better than the sequential seed once cleanup runs (BACKLOG.md:1215-1232).
  The fairing MCU module uses it (fairing 3c445576).

**Firm passes / redo: `_resolve`, `_redo_check`** (layout.py:7678; 2783)
- Re-runs the whole resolve up to `place.firm_passes` times when declared copper or a
  Beside part does not match where firm items went. Whole-board, automatic, expensive.
  Not a local-move mechanism.

**Give-way: `giveway.py`, `giveway_field.py`**
- Runs: inside every scan (placer.py:337 `gave_way`, `giveway.for_scan` giveway.py:1230)
  and at each commit (`giveway.resolve` 1095, `apply` 1257).
- Moves carried vias (share, move, relay a field, leave the pad, shorten, drop), not
  items. Changes the board automatically; reported as `vias.gave_way`/`vias.dropped`.
- Cost: priced per candidate the item-as-is test refuses; native ring/hole checks.
- Score: `score.via_*` costs added to the search score.
- Labels give way the same way (`_labels_give_way` layout.py:9045).

**Push** (`Board.push` layout.py:4660; `Push` 506; `_push_at` 11679)
- A declared physical effect: illegal past its limit, else a cost term `score.push x
  value/limit` in the Scorer. Does not move anything itself. Breaks the native scorer
  (`Scorer.native` returns None when the item carries a push).

### After the search, inside the resolve

**Cleanup pass** (cleanup.py:54-283; `_cleanup` layout.py:8596; movable set 8543)
- Runs: after the searched tier, before the late copper, when `cleanup.enabled` (default
  on, settings.py:505). Replayed from the reuse record when nothing before it changed
  (layout.py:8170-8177).
- Changes placement: yes, greedy. FastPlace-DP: per part a scored `scan` (radius 3 mm,
  step 0.5 mm) round the median of its nets' other pins and round where it stands, taken
  only when cost falls; then swaps with the 4 nearest movable neighbours and any
  identical part (`_swaps` cleanup.py:286). 2 passes; a pass with no change ends it.
- Moves: plain searched parts and block satellites only. Not cells, not Near/edge/line/
  rim items, not anything a label/row/escape/needs refers to, not locked or explore-
  focused items. Rotation may change among the part's allowed turns; face never.
- Cost: one scan per hint per part per pass; native `NativeCleanupScoring`.
  Prototype: 44 s more on a 220-part board (2026-09-23-cleanup-pass-design.md).
- Incremental: yes, one part (or pair) lifted and scored.
- Score: HPWL + declared links + crossings + escapes (cleanup score above), not the
  search score.
- Measured: 23 of 32 modules better, none worse (BACKLOG.md:1214).
- Uptake: disabled on every fairing core board (placemat.toml `[cleanup] enabled =
  false`, "Cleanup currently moves block satellites after fixed copper is planned").
  placemat fixed that in cf9f1cd1 (2026-09-27); the boards were never switched back.
  The fairing core has 22 searched cells and 9 searched parts, so cleanup could move at
  most the 9 parts there.

**turn.better** (`_report_turns` layout.py:5530-5634; turn-all worktree adds
`_turn_choices`, `_turn_held_by`)
- Runs: once at the end of a resolve (layout.py:8205), not inside an explore variant.
- Changes placement: no. A `turn.better` notice with a suggestion that edits
  `rotations=`/`rotation=` (suggestions.py:1246 `turn_better`).
- Judges each searched part or cell (turn-all: every placed part and cell) at its other
  allowed turns (turn-all: every 90, or 45 when a diagonal is declared, for a fixed turn),
  held at the same body centre, legal by `occ.legal` (turn-all: decided items judged as
  KiCad will, `silk_as_drawn`, `by_corners`).
- Cost: up to 3 (or 7) turns per item x (pad positions + `leaf_costs` + one Python legal
  check). Milliseconds per item.
- Score: the search's wire and crossing terms only (no escapes, pushes or lanes);
  thresholds `place.turn_gain_mm`, `turn_gain_share`, `turn_crossings_min`.
- Skips parts the pin study turns. turn-all marks lock-held turns `held_by: "lock"`
  with release advice, and `Facing`/`Turned`/`Parallel` or a why= naming a turn with no
  suggestion.

**Pin map study** (`_report_pin_maps` layout.py:5636; pinmap.py:386 `plan_findings`;
pinmap_core.py:172 `poses_of`, 268 `study_group`; native/src/pinmap.rs)
- Runs: once per resolve on the finished board (cached by digest), on an explore's top
  `pins.explore_top` variants (explore.py:1080), and longer from `placemat apply <id>
  --search`.
- Changes placement: no. `pins.remap` advice (capture change + optional pose turn).
- Search: for each pose (present, then each of `pins.rotations`, optionally flipped), a
  first map then annealing over pin moves/swaps/group moves (`pins.anneal_moves` 100,
  temperature 1.0 -> 0.02), step budget `pins.budget_steps` 3000 per part, deterministic
  SplitMix64 stream. This is the only annealing loop in placemat, and it is over pin
  assignment, not placement; poses are enumerated, not annealed.
- Incremental: yes (`Tally::delta`, pinmap.rs:573): a move recounts only the nets it
  touches.
- Score: its own (pin study score above).
- Legality of a turned pose: I found no check that the turned body is legal on the board
  (pinmap_geom models the body as its courtyard box for pin exits only). The fairing MCU
  45-degree turn needed the coin moved off the board after the fact (fairing b94c002f,
  core-placement-mcu-45-2026-10-05.md "What the turn needed").
- Measured: 0.075 s for the fairing core's one group (run 28770367 metrics.pin_study).

**Ratsnest crossings** (ratsnest.py; occupancy.py:1260-1305; native ratsnest.rs:331)
- A port of KiCad's RN_NET. Kept incrementally: `commit`, `lift` and `unlift`
  (occupancy.py:1216-1245) refresh only the nets of the refs touched
  (`_ratsnest_refresh` 1283). `leaf_costs` is the per-candidate crossing query (native
  mirror when built). `crossings(edges)` (ratsnest.py:161) is the whole-board count the
  run score and `plan_measures` use.

### On demand, whole resolves

**Explore** (explore.py; `search` 909, `_work` 654, `draw` 68, `measure` 82;
layout hooks `_pick` 9928, order swap 8135)
- Runs: `placemat run/preview --explore SECONDS`, in worker processes.
- What varies: for focused explorable items, each scan's chosen spot is drawn among
  candidates within `explore.spot_slack` (25%) of the best, weight 1/rank^power;
  neighbouring focused items trade order with `explore.swap_chance` (0.2). Seed 0 is the
  plain placement.
- Changes placement: not the board; the best variant is reported; `--accept` writes it
  to the lock (`accept_best` 1147).
- Cost: one resolve of everything from the first focused item on per variant (steps
  before it replayed). Measured 0.15 s per variant on modules (explore design doc :172);
  on the fairing core 13 variants in 900 s (core-placement-mcu-45 doc). Whole board.
- Score: candidates by the search score; variants by the run score (with RUDY), or the
  run score less the best pin remap's saving when `explore.rank_remapped`.
- The design's "phase two" - lift a focused cluster out of the best board and re-place
  it (large neighbourhood search) - was proposed (explore design doc, "Phase two") and
  never built.

**Lock** (lock.py; `_locked` layout.py:9831, `_lock_spot` 9876, `_settle_locked` 9903,
locked order 8128-8132; `lock --current` cli.py:334, `_lock_where_it_stands` 503,
`lock.current` lock.py:207)
- Each entry places one searched item relative to the placed pad it depends on most
  (offset, rotation in that part's frame, face, declaration digest, order `turn`,
  arrangement).
- Runs: during the resolve, at the item's turn. `_settle_locked` scans radius 0 at the
  locked spot (one candidate); when that is illegal it drifts: a scan of radius
  max(declared radius, body size) at the locked rotation. A changed declaration, a gone
  anchor or no spot releases the entry with a note.
- Changes placement: yes (it is applied). Locked items keep their accepted order among
  themselves and are excluded from cleanup (`_lock_held`).
- Cost (measured, fairing-instrument-fresh runs): held item 0.05-0.2 s, searched item
  about 0.85 s. Drifted items can cost more than a search: 9 drifted took 30.7 s in run
  ab45a740 and 32.0 s in 83b8734c, because the core declares `radius=WHOLE_BOARD` and
  the drift radius takes the declared radius.
- Fed by: explore `--accept`, `lock --current` (resolves like the last run, locks every
  searched item that lands within `route.adopt_tolerance` of the written board, then
  resolves again with the lock to check they come back; `--partial` drops the ones that
  do not and loops), and `route --adopt` (locks the items kept nets join).

**Freeze** (freeze.py:161)
- Moves lock entries into the script's `place()` calls (splicing edit), accepted only if
  the edited script resolves to the locked placements. One or two full resolves.

**Arrangements and alternatives** (arrangements.py; arrangement_run.py;
`Board.alternative` layout.py:3506; `_scan_arrangements` 10934; `_settle_firm_arranged` 10829)
- A module run lays every arrangement (full resolve each, own DRC and checks) and
  offers the ones that pass. On the parent board a searched cell's arrangements are
  scanned like turns, scored by the search score plus arrangement cost; a firm cell's by
  trials. Automatic, during the resolve.

**Suggestions and Try** (suggestions.py; `apply_suggestion` 512; studio.py:1255
`suggest_try`; studio_worker.py:129)
- Suggestions are script edits built from finding facts (`bind` 387), shown and applied
  by `placemat apply` or the studio. Try resolves the edited script in place of the file
  (one full resolve, `studio.try_timeout_s`). No placement change until applied.
- Score: the finding clears or not; Try reports the run.

**Probe** (probe.py; `search` 479, `Probe` 214)
- For a searched suggestion with a `figure`: one full resolve per candidate value
  (`overlay_resolver` 446), judged by whether the finding clears, what it gains, and the
  run score. On the core that is 25-40 s per candidate. Finds a value; changes nothing
  until the found suggestion is applied.

## 3. Answers

### 3.1 What could form a detailed-placement pass

Pieces that exist:
- Hold the board: the resolve's occupancy after the searched tier, with lift / unlift /
  commit that refresh the ratsnest and escapes per touched net (occupancy.py:1216-1245).
  Cleanup already runs at this point and writes its moves back to the steps
  (layout.py:8596-8640) and into the reuse record (`_recorded_cleanup` 8425).
- An incremental delta score: `Scorer` evaluated on a lifted item is the item's
  contribution to the search's objective. Its wire term gives an exact delta of the
  board's weighted clique wire; its crossing and escape terms are the search's own
  estimates. It is already evaluated per candidate natively (`NativeScoring`), and
  cleanup has a parallel per-part scorer (`PartScore`/`NativeCleanupScoring`).
- Legality of one candidate: `scan(occ, item, spot, 0.0, ...)` (as the lock uses) or
  `occ.legal` / `legal_bucket` / `legal_giving_way` (occupancy.py:1866, 1996, 1967).
  Give-way for carried vias is resolved at each commit.
- Moves already written: shift by scan (cleanup global move), swap (cleanup `_swaps`),
  turn among allowed turns (cleanup `turns=`, turn.better's same-centre turn), flip
  (`_scan_faces` for Face.EITHER items), arrangement choice (`_scan_arrangements`).
- A seeded deterministic RNG pattern (`explore.draw`, `_order_rng`) and a step-budget
  pattern (`SearchBudget` placer.py:25; pins study budget steps).
- The movable-set rule (`_cleanup_movable` layout.py:8543): what nothing else was placed
  against.

Missing:
- The loop: no annealing over placement exists. The only annealing is the pin study's,
  in Rust, over pin maps. Cleanup is greedy and deterministic.
- A move generator for small random moves: nudge by a grid step, turn, flip, swap,
  arrangement change, picked at random with a temperature. Cleanup's moves are full
  scans (radius 3 mm), not single perturbations.
- A cheap single-candidate evaluation path from Python: a radius-0 `scan` goes through
  the native sweep but carries per-call setup (obstacle query, sweeper, give-way setup);
  `occ.legal` is about 30 us in Python. A batched native "judge these N (item, spot)
  pairs and score them" call would be the hot path for annealing.
- Cells in the movable set: cleanup moves parts and block satellites only; the fairing
  core is mostly cells (22 of 31 searched items).
- One objective: cleanup's HPWL differs from the search's clique wire; the pass should
  use `Scorer`'s terms so a move is judged as the search judged the spot. Pushes on an
  item that is another item's push source, and declared lanes, are not in the native
  scorer.
- A final check against the run score (whole board) before keeping the result.
- Replay: the pass's commits recorded like `_recorded_cleanup` so an unchanged rerun
  replays it.

### 3.2 Overlap with such a pass

| Feature | Overlap | What it does that a pass would not |
|---|---|---|
| Cleanup | Same stage, same lift/score/commit mechanics; a pass would replace it | Nothing beyond a pass with shift/swap/turn moves; its global move to the FastPlace optimal region is a large jump a local pass may want as one move kind |
| Explore draw / order swap | Both seek a better placement than the greedy one | Varies the constructive order and early choices, so later items are placed against a different board (restarts); a local pass cannot reach those basins. Judges by the run score. LNS ("phase two") would sit between the two |
| turn.better | A pass with turn moves would apply the same turns | Reports turns of items a pass must not move: decided items, `rotation=` fixed by the script, lock-held turns (turn-all). Keeps value as advice on script-owned turns |
| Pin study turn | Pose part only | Changes the pin map, a capture change a placement pass cannot make; its own objective |
| Give-way | None: it is a dependency | Moves vias so items can stand; a pass's commits use it |
| Settle / scan | None: the pass refines what settle built | Places from nothing; the pass reuses scan for its legality checks |
| Lock | Partly (see 3.3) | Keeps placement across script edits, anchored to a pad; hand-off format for explore, route adopt, freeze |

### 3.3 The lock

What it gives:
- Placement that survives script edits: each entry is relative to its anchor pad and
  has its own declaration digest, so editing one item releases only that entry
  (and moving the anchor moves the item with it).
- Held turns and order: rotation in the anchor's frame; locked items go in their
  accepted order.
- Exclusion from cleanup (locked items stay put).
- The common record that explore `--accept`, `route --adopt` and `freeze` read and
  write.

What it costs: a run with a lock still runs the whole resolve - firm items, every
unlocked searched item, copper planning, reports, pin study, checks. Each held item is
one legality check (0.05-0.2 s on the core) instead of a scan (0.85 s); a drifted item
scans at its declared radius and can cost more than a plain search (about 3.4 s each on
the core with WHOLE_BOARD radius). An unchanged rerun is cheap because of run reuse
(the step replay: 125 s -> 7 s on the whole test board, BACKLOG.md:1203), not because of
the lock.

Would "start from the last placement, then refine" replace it? Reuse already starts
from the last placement, but its chain key is broken by the first changed step, and
everything after is searched again. The lock is the per-item, edit-tolerant snapshot that
reuse is not. A refine model needs that same per-item snapshot, so it would keep the
lock's data and change its meaning: today an entry pins the item (and keeps it out of
cleanup); for refinement it would be a starting point the pass may move. That is a
decision for the user: either a second kind of entry ("start here") or a flag on the
pass to treat held items as movable.

### 3.4 Uptake in the fairing repos

Acted on:
- Explore + `--accept` (lock): repeatedly. fairing a7c7065f (2026-09-24, MCU crystal and
  RF), 2ee7deac (10-02, "the core keeps explore's fit", score 12806), b94c002f (10-05,
  explored 900 s, best of 13 seeds), 6620a0ac (explored round the remap), fresh 1444d5f6
  (10-06, "explore seed 8"). The ring-test board: `--explore 240` found nothing better.
- Lock from route adopt: 2656f9dc ("lock the 23 items they join"), 9c4f84bc, f7912309.
- `pins.remap`: acted on three times, each with Ben's approval or standing approval:
  b94c002f (MCU turned 45 degrees with the study's map), 6620a0ac (remap at the 45-degree
  pose, 33 weighted crossings saved; routed 89.3% vs 86.4%), fresh 9f666f62 (remap for
  the cell at 315). Two more are pending now: fresh s95a/s95b (cell to 225, 24 nets),
  main s75a/s75b (cell to 270).

Not acted on, or not used:
- No suggestion has ever been applied through `placemat apply` or the studio, and no
  probe has run: there is no `.placemat/applied.jsonl` or `.placemat/probes` in any repo
  under ~/Documents/Hardware. Pending instant suggestions sit in suggestions.json
  (main: s11a/b RF_50 track, s12a/b raise CC limit, s76a remove an accept; fresh: s96a).
- `link_over` stayed at 4-8 per run across about 20 fresh runs until the links were
  rewritten by hand (a4bdfd84); not through the suggestion.
- `escape_crossed`: 75 notices on the latest fresh run (83b8734c), no sign of action.
- turn.better is newer than the boards' placemat (0.99.30/.31). The fresh agent turned
  the display terminations by hand (e0b8c46f) with a comment that the search had turned
  the column backwards - the case turn.better and the cell-turn fix address.
- Cleanup: disabled on all five core checkouts (see above).

### 3.5 KRT bus routing

KRT-upstream, branch placemat/upstream-2026-10 (c98d38eb):
- `--bus` is one global switch (py_router/route.py:7139-7148, passed at 7812-7816):
  buses are auto-detected (`detect_bus_groups`, py_router/bus_detection.py:37; strict
  geometric filter `filter_bus_groups_geometric` 316), with one detection radius,
  attraction radius/bonus and min nets for all of them. Detected groups are ordered first
  and get corridors (py_router/single_ended_loop.py:463-560). `--ordering bus`
  (route.py:7011) orders without attraction.
- Global env knobs only (py_router/env_knobs.py:69, 479-480, 516-522).
- No way to name buses, no per-bus flag. `--group BLOCK` (route.py:6970-7000) scopes a
  run to one placement block's nets, one block per call; it is not bus routing.
- placemat passes `--bus` only through `route.router_args`, to every pass alike
  (settings.py:383-384).

Fork branch bus622-take5 (fetched as remotes/fork/bus622-take5, 249d5252):
- awx/route_bus.py is a standalone research tool (`KRT_TOOL kind 'actor'`), not called
  from route.py. Without `--src/--dest` it routes every bus it finds in one call, in turn,
  each on the board the last handed on (`route_buses` :149); `find_buses` (:551) takes
  part pairs sharing `MIN_BUS_NETS` = 8 nets (:533) with a ball array at both ends; a pair
  with a row part at one end is left to the router. With `--src/--dest` (:688-690) it
  routes one bus. The Python function takes `buses=[(src, dest), ...]`, the command line
  does not. No per-bus options; sizes are per call.

## 4. Route stages in kicad/route.py

| Stage | Code | What it is | Name it could take |
|---|---|---|---|
| pairs | `route_pairs` :636; stage :1091-1131 | differential pairs from the net classes (`pairs.board_pair_list`), routed by KRT's route_diff.py, one call per pair-layer group, copper locked after | diff pairs |
| islands | `route_islands` :909; stage :1132-1162 | the nets in `[route] islands`: pour nets whose pours leave pads or pieces apart, each routed alone at its width (or the class's), on its own layers if given, its pours shown to the router as zones. Not width or power nets in general - only the listed pour nets' leftover joins | pour joins |
| classes | `class_stages` :967, `route_class_stages` :983; stage :1163-1203 | nets whose clearance (net class or net halo, from the router's clearance map) is above the Default class's, one router call per clearance value, widest first | wide clearance |
| main | stage :1204-1230 | every other signal net: not excluded (planes, islands), not routed as a pair, not in a class stage | the rest |
