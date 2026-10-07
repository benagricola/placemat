# Handover: step 1 of 0.100, routing phases (in progress)

For the session that continues step 1. It updates docs/superpowers/handover-0.100.md, which still holds for the lanes,
the shared machine, the release line and the merge rules; read that first, then this, then the plan.

State as of 2026-10-07 evening. Step 0 (the reference set) is merged on main (175358af) and released with 0.99.35.

## Read, in order

1. ~/.claude/CLAUDE.md, this repo's CLAUDE.md, CHARTER.md and the memory index (loaded for you).
2. docs/superpowers/handover-0.100.md.
3. The plan: docs/superpowers/plans/2026-10-07-routing-phases.md, in particular "Decisions" (who decided each) and
   "Controller rulings". It is the source of truth for every task's content and has been amended four times today.
4. The spec: docs/superpowers/specs/2026-10-06-routing-phases-design.md (amended for structured `--connections` ends and
   `pairs` by net names).
5. Research: docs/superpowers/research/2026-10-07/ (zener-stage2-trace.md, krt-connections-design.md,
   krt-rebase-regressions.md).
6. The execution ledger, with every task's review findings, fix rounds, deferred minors and rulings:
   .superpowers/sdd/2026-10-07-routing-phases/progress.md (git-ignored, on this machine). The task briefs, reports
   and review diffs are in the same folder. constraints.md there is what every subagent brief carried.

All the 0.100 documents (roadmap, the step specs, plans, handovers and ledgers) are listed in
docs/superpowers/plan-0.100-index.md. The sibling step's handover is docs/superpowers/handover-0.100-step2.md and its
ledger is .superpowers/sdd/2026-10-07-one-score/progress.md.

Method: superpowers:subagent-driven-development, as the user chose. One implementer per task, a task review, fix
rounds with a scoped re-review, the ledger updated after every step.

## Branches and worktrees

| Repo | Worktree | Branch | Head | Pushed |
|---|---|---|---|---|
| placemat | /home/ben/work/placemat/.claude/worktrees/routing-phases | step1-routing-phases (from ec11d554) | 908feac3, plus Task 13's fix round in progress | no (local) |
| KRT fork | /home/ben/work/KRT-phases | placemat/connections | 6d50f0ed | `fork` |
| KRT fork base | /home/ben/work/KRT-base-10b | placemat/upstream-2026-10b | 78a16663 | `fork` |
| Zener fork | /home/ben/work/pcb-phases | feat/nets-layout-json | 318b4b0d | `origin` (benagricola/pcb) |

- The placemat branch is behind main: main has 0.99.35 and the consolidation session's fixes. Merge main into the branch
  before the gate. Until then three tests/test_version.py tests fail in the worktree for that reason alone. The worktree's
  src/placemat/_version.py is a copy of main's.
- Run placemat in the worktree as `PYTHONPATH=<worktree>/src /home/ben/work/placemat/.venv/bin/python`. Tests need
  `KRT_DIR` (now required, no default) and `MNB_ECOSYSTEM=/home/ben/Documents/Hardware/mnb-ecosystem`; use
  `KRT_DIR=/home/ben/work/KRT-phases` for the step's router.
- ~/work/KRT-upstream and ~/work/pcb are live for every session; they move to the fork commits only in Task 26.
  Other sessions own KRT-ab, KRT-agent, KRT-align, KRT-base, KRT-dev, KRT-escape, KRT-fan, KRT-t1base: never write there.
- Real-board runs: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock`
  (the reference runners take it themselves). Disk is 97% full (61 GB free); stop and ask below 20 GB.

## Done (reviewed, fix rounds closed)

| Task | What | Commits |
|---|---|---|
| 1 | Zener branch pushed; worktrees | - |
| 2, 3 | Zener: `clearance` on stdlib net types; nets.layout.json stage 1 (types, fields, generator, netlist sha256; only `clearance` parsed as a length; Ohm labelled) | 0d906642, 15c8857c, 10b389aa |
| 21 | Zener stage 2: interface instances and DiffPair pairs in the sidecar (a pair appears once per instance path; placemat dedupes by (p, n)) | e1c8958e |
| - | Zener: upstream's AGENTS.md removed; 4 release snapshots updated (d2b9f749's annotations parameter) | 7ffeab17, 318b4b0d |
| 4 | KRT: clearance floored at the board's min_clearance; every neck at min_track_width (fork divergences) | rebased; see docs/fork-divergences.md on connections |
| 5 | KRT: `--connections` (structured ends, per-layer widths, statuses incl. joined_narrow fallback, refusal reasons incl. layer_width_missing; unknown nets give records) | rebased |
| 5a (part) | KRT fork rebased onto upstream 364b4572; router made deterministic (item uuids derived from content and a board seed); pic_programmer's dogbone-guard regression fixed | 5a629cfa, 321049bc, 78a16663 on the base |
| 7 | Surface tests (CLI, settings, removed forms), vulture, native dead-code build | 12fc44a5, 25f1fba6 |
| 8 | `[[route.phase]]` form | bacba130, 84679b6d |
| 9 | Reading nets.layout.json (stale sidecar refused) | 1077daee |
| 10, 10a | Phase selection; pairs by net names | 4bf119f5, d2e9bce3, ce70e2fc, b508b06d |
| 11 | A phase's router calls (glob characters escaped per flag) | 6f9f1c2a, 624e65b4 |
| 12 | Kept-result chain over phases | d8769e5b, 8d0713e4 |
| - | placemat determinism: KIIDs seeded per load (write.load_board); close-via merge by geometric rank; no machine paths (router from `[route] router_dir` or `$KRT_DIR`, else refused; tests env-only) | 76f4b774, 3a79ddf6, 1cc97938, f2e8c9a4 |

## In flight when this was written

- **Task 13 (phase engine):** built (83d70735, 908feac3). Its review found 4 Important and 7 Minor items, and the fix
  round was dispatched to the implementer. The ledger lists all 11 items. If the fix round has no commit on the branch,
  re-dispatch it from the ledger. The user decided the neck rule there: the neck allowance covers copper within neck_mm of
  each pad only up to half the path's length from each end, so a short connection keeps full width in its middle.
- **splitflap_driver regression (KRT test test_run23_summary_min):** decided by the user after seeing annotated
  pictures (scratchpad splitflap-pics/out/): fix the router's rip-up so that, when a pin is boxed in, it first rips the
  nets whose copper bounds the pin's reachable pocket. An agent is building it on placemat/upstream-2026-10b
  (KRT-base-10b); report task-ripwall-report.md in the ledger folder. After it and Task 6a land, rebase
  placemat/connections onto the base.
- **Task 6 (`--bus-nets`)** is done (e0870e1c, 3a818aae on placemat/connections; a net in two stated groups stays in
  the first). **Task 6a (failure evidence)** is being built on placemat/connections.
- **Task 13** fix round committed (f5a3e38f); its re-review was running.

## Next, in order

1. Close Task 13's fix round (re-review), then Task 14 (a failed or stopped route keeps the placed board).
2. Finish Task 5a: after the splitflap decision, re-record test (a) on the rebased base (KRT_DIR at a worktree of the
   base without the step's commits, `route_ref.py --changing krt --update`). The user accepted esp-rust-board's one
   extra starved_thermal from upstream 8013c817 into the new baseline: record its cause in the manifest notes. Watchy is
   84.3% with placemat's via merge. Then Tasks 5b (test (b) against the regenerated board; the pcb fork's git commit in
   results) and 5c (the 11 hand-placed modules from the user's project, copying approved), in sequence: all three write
   results.json.
3. KRT Task 6 (`--bus-nets`; must accept the `\!` escape) and 6a (per-connection failure evidence: reliable router
   facts first, diagnosis optional with unknown valid, router facts kept apart from placemat inferences). The router-old
   refusal currently requires `--bus-nets` only when a phase has buses or interfaces.
4. Tasks 15-20, 17a, 18a, 22-24 per the plan; then 25 (Remove, including the dead stage code route_islands,
   route_class_stages, islands_on_board, island_layers_on_board, joined_ends) and 26 (merge main, full suite, gates,
   `--update` runs, vulture, then merge and release 0.100.0; the user cuts 1.0, never you).

## Decisions the user made today (all recorded in the plan)

- Step 0 follow-ups pulled into step 1: corner holes held with `overhang=`; a courtyard over a hole follows the board's
  severity (both shipped in 0.99.35); test (b) compares with the regenerated board; the 11 hand-placed modules join test
  (b) now; results record the pcb fork's commit.
- KRT: keep the floors (D6); rebase onto upstream first (D9); keep upstream 8013c817 and accept esp's +1 DRC; find and
  fix nondeterminism (done: random item uuids).
- `pairs = [["P","N"], ...]` by net names for boards without a capture (D18 replaced); test (a) exercises it on
  esp-rust-board's USB pair (usb-c-power-adapter has no USB data pair; it gets an I2C bus phase).
- D14 every pad of both carrier parts; D19 placement pairs stay for step 1.
- Studio shows the per-phase report; the default-phases test has pairs; stated buses skip detection; a numeric width is
  ignored on current_paths.
- Failure evidence filled in step 1 (Task 6a), shaped by the reviewer's answer; an obstructed-route fixture (Task 17a).
- The final-board comparison is step 2's `score.rank`; step 1 supplies its inputs (Ruling S6): phases[i]
  ["final_closure_clean"] over the phase's fixed pad-pair obligations re-judged on the final board, widths_failed
  (joined_narrow included), drc_new (real errors beyond the unrouted baseline), vias, track_mm (straight segments as
  KRT's quality key), segments. A width-failed join is never a clean join (S7); widths are judged on each obligation's
  joining path (S8).
- Short connections keep full width mid-path (see Task 13 above).
- No machine paths anywhere (memory: no-machine-paths). Zener fork snapshots are updated without asking when a change
  explains them; an unexplained snapshot change goes to the user with its diff (memory: zener-fork).
- Refine and loop specs: coordinated neighbourhood rebuilding added (972c5e72, bdfa0ac3) - steps 3-4, not step 1.

## Working notes

- Run touched test files with `--full` before handing back: slow tests hid two regressions today.
- Agents in a shared worktree commit only their own paths; tasks that write results.json or edit kicad/route.py run one
  at a time.
- The one-score session (step 2) consumes step 1's RouteReport fields; tell it if a field name changes.
- The consolidation session (`placemat`) releases 0.99.x from main and knows the close-via fix ships with step 1.
