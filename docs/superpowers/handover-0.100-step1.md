# Handover: step 1 of 0.100, routing phases (in progress)

For the session that continues step 1. It updates docs/superpowers/handover-0.100.md, which still holds for the lanes,
the shared machine, the release line and the merge rules; read that first, then this, then the plan.

State as of 2026-10-07 evening. Step 0 (the reference set) is merged on main (175358af) and released with 0.99.35.

## Reviewer-led continuation on 2026-10-07

The historical task state below is superseded by this continuation and the worktree's ignored execution ledger.
The reviewer assigned step 1 to one agent and the router/reference lane to its child, with independent review before
merging to main. Main was merged into the feature branch at 9b4f8be4; step 1 has not been merged, pushed or released.

- Parent scoped review accepted the Placemat changes through 45dbfd89 and the repeated-current-alias correction
  f57d94fa. Tasks 15/16/18/18a/19/20/22/25 now have implementation and targeted validation. Required-width proof
  explicitly fails closed when geometry cannot establish it; final phase comparisons use stable electrical intent.
- Task 24's current-name correction handles qualified names and repeated aliases conservatively. Circuit-capture
  documentation changes are local commits 1efad41 and 1475634 (versions 0.1.7 and 0.1.8), awaiting reviewed publication.
- Router changes and Tasks 5a/5b/5c/17/17a reference work remain in the child lane. A bounded legacy-first fallback
  is undergoing router gates because unconditional pocket recovery regressed previously complete ESP routes.
  No unexplained reference regression may be accepted or repinned.
- Task 26 remains open: final whole-suite, reference comparisons, slow-test list, and release gates. The earlier
  broad run omitted KRT_DIR and lacked local socket access; it is diagnostic evidence, not a successful gate.
  The unchanged main OCR confidence test also failed independently; see /tmp/placemat-main-ocr-baseline.log.
  Its assertion contradicted the documented line-admission/weakest-word confidence contract. The reviewer's exact
  approved test-only correction from step 2 c18d0f81 is cherry-picked as 4a9140b2; 53 PDF/datasheet tests pass with
  OCR implementation and thresholds unchanged.
- Use /tmp/placemat-step1-venv/bin/python for branch validation. It has genuine editable branch metadata and a
  locally built native extension, with read-only dependency paths shared from main. Reinstall the editable package
  after commits so installed metadata matches the checkout. Always set PYTHONPATH to this branch and KRT_DIR to
  the finalized connections worktree, and use approved local socket access for server tests.
- Isolated targeted gates passed: version/phase commands/capture selectors 41 tests; full width/selector/settings/
  capture/check/studio/resume scope 345 passed, 4 skipped; socket-capable studio/CLI scope 50 passed. Vulture is clean.
  These support scoped review and do not replace the final whole-suite or real-board gates.
- Step 2 owns final routed-board electrical judgments and the common Standing/report adapter in its Task 17 after
  consuming reviewed step 1. The final integrated review must check that routed results supersede placement checks.

Required-width proof was tightened in b677898a after review found false certificates through filled copper and
intermediate pads. Each polygon/layer is separate. A required-width track path may certify a connection; filled
regions and intermediate pad interiors cannot currently certify corridor width. Endpoint pads certify only a track
node at their actual anchor: an offset entry through the pad interior is also unmeasured. Unrestricted diagnostic
paths retain measured narrow track spans and explicitly set width_unknown for those interiors. This limitation can
make a physically adequate pour or offset pad entry unproven; it must not be hidden by repinning a reference result.
The focused graph/width regressions and independent reviewer gate passed; physical/reference gates remain pending.

Keep the real-board lock and two-worker limits below. Reference runners acquire the lock internally: do not wrap
them in another flock on the same file. The reviewer must approve concrete final changes before merge or release.

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
- **splitflap_driver regression (KRT test test_run23_summary_min), fix decided, not yet confirmed done.**
  - The problem: on the rebased router, U7 pin 10 (+3V3) stays open on 3 of 6 order-jitter seeds (6/6 before the
    rebase).
  - The pictures and their captions are in docs/superpowers/research/2026-10-07/splitflap-pin10/ (passing.png,
    failing.png, mechanism.png, captions.md).
  - What happens: upstream 39dd0327 stops treating finished nets as stub-proximity sources. That changes costs
    elsewhere on the board. Earlier routes shift, and CLOCK_IN's bottom-layer tap to U7 pin 11 ends up across the space
    +3V3 used to escape through.
  - Pin 10 is then walled into a closed 4.7 mm2 pocket. Four taps fail, and the router's rip ladder rips Net-(U5-Pad9),
    /SENSOR_D and /LATCH_IN, never the copper walling pin 10. It accepts the result with pin 10 open.
  - In the passing run one tap fails, and the ladder rips MOTOR_F_PHASE_A (the net under the pad), so the retry joins.
  - The fix (the user's choice after seeing the pictures): in the fork's rip ladder, when a failed tap's endpoint is boxed
    in, first rip the nets whose copper bounds that endpoint's reachable region. Find the region with a flood from the
    endpoint on the router's grid at the task's width and clearance, and order the nets by how much of the boundary
    each owns. Then fall back to the ladder's existing choices, keeping its attempt limits and acceptance rule. Mark it
    as a FORK DIVERGENCE.
  - It may share the pocket code with Task 6a's `blocked_by`.
  - Rejected alternatives: re-pinning the test, and undoing 39dd0327's one line as a divergence.
  - Done means:
    - test_run23_summary_min passes on all of seeds 0-5;
    - KRT `--fast` shows only the known failure (test_887_iso_render);
    - placemat's test (a) is no worse on any of the eight boards, before against after.
  - Status at handover: an agent was building it on placemat/upstream-2026-10b (worktree /home/ben/work/KRT-base-10b,
    from 78a16663). Its report goes to task-ripwall-report.md in the ledger folder. If there is no commit after 78a16663
    on that branch, build it from this description. After it and Task 6a land, rebase placemat/connections onto the
    base. Then re-record test (a) (Task 5a).
- **Task 6 (`--bus-nets`)** is done (e0870e1c, 3a818aae on placemat/connections; a net in two stated groups stays in
  the first). **Task 6a (failure evidence)** is being built on placemat/connections.
- **Task 13** is complete (83d70735, 908feac3, f5a3e38f, 0e4fbe7b, 5ec25683). Release gate: the clearance docs
  (api.md, SKILL.md, migration) already describe Task 16's behaviour, so Task 16 must land before 0.100.0.
- **Task 14** (a failed or stopped route keeps the placed board) was dispatched next.

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

## Reviewer completion gates (2026-10-07, latest)

- Whole repository `pytest --full -n2` at clean `b6cc86b0` passed: 6,707 passed, 22 skipped, no failures or errors,
  1,216.29 seconds. The genuine isolated editable install reported `0.99.35.post1.dev69+gb6cc86b0f`; its actual
  native library and PCB executable hashes were recorded. `step1-final-full.xml`, `.log` and start/end provenance
  artifacts are retained in the review scratch directory. All five recorded checkout HEAD/status identities matched
  before and after the run, and the PCB executable hash was unchanged. Parent independently read and accepted the gate.
- Skipped coverage: 14 track/via airwire-end oracle cases, two optional `FIT_REFERENCE` cases, two optional disc-board
  cases, one antenna-datasheet case and three connector-datasheet cases. The required reference, current core comparison,
  generated USB-C and partly joined pair physical checks remain separate completion requirements.
- `tests/slow_tests.txt` was refreshed only from that completed XML: 230 cases exceeded the two-second threshold.
  This is a measured scheduling list, not evidence that any skipped optional case passed.
- The legal obstruction fixture record `4550801d` came from the actual run, with original manufacturing rules retained.
  Its focused physical reproduction plus reference/local tests passed 43 cases, no skips or failures. The earlier broad
  default run's sole missing-record failure is resolved by this actual record and focused gate. The old illegal fixture
  observations remain diagnostic only.
- The frozen full gate used PCB executable SHA256 `902f2d6327459fde16e425a4b68012166b8d68725f6237a607f0f3bdc16a1e99`.
  Actual generated sidecars embedded Git `10b389aa12c1` despite the checkout being `318b4b0d`; build metadata was stale.
  Exact original build source is not claimed. A controlled clean tracked-source rebuild and independent actual interface
  capture proof are required before the remaining generation/comparison runs; the executable was not replaced during
  the full gate.
- Remaining: common-contract grading of saved baseline/candidate copper, historical hand-module matching and C/M
  references, final A/B/M gates, generated USB-C and partly joined pair physical integration, and the scratch-only D28
  comparison. No main merge, fork push or release is authorized by this gate alone.

- Post-gate runtime correction `f6ad747a`/`7570b3d9`: a fresh generated export wins over a saved same-name or blocked
  ancestor path; the original remains in `kept/` and collision notes are logged. The generation-level regression
  reproduced a stale sidecar before the fix. Fresh/cached exports, saved handwritten files and generated file/symlink
  prefixes pass 38 focused full tests; parent independently repeated and accepted them. The same old helper exists on
  main, so this was preexisting. A final whole full suite must cover this latest production code after batching.
- Controlled PCB rebuild completed from clean tracked `318b4b0d` source with offline two-job Cargo: executable SHA256
  `9464bb2aa1fccbd945e90e7cf984da8d657633967c1b6dd069c1916a491d097f`, correct embedded `318b4b0d19ce`, actual independent
  DiffPair/member capture proof passed. Old executable and clean source digest/archive remain in review scratch.
  `BACKLOG.md` records the permanent linked-worktree build-metadata follow-up; no PCB build-script source change landed.
- Both scratch core variants passed fresh official capture generation with the controlled PCB executable: identical
  board/sidecar bytes, qualified switch-net clearance and actual effective class-map floor 2 mm, resolved stdlib hashes
  identical to the finalized fork. The exact local sibling part closure was added identically after the first missing-file
  refusal. Original project inputs were untouched. Actual per-phase map provenance and the two full routing comparisons
  remain required; no project-specific metrics are recorded here.
