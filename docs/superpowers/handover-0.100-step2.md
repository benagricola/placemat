# Handover: step 2, one score (in progress)

For the agent that takes over step 2 of the 0.100 roadmap. Read `docs/superpowers/handover-0.100.md` first (lanes,
shared machine, forks, release line), then `docs/superpowers/handover-step2-one-score.md` (the original brief for this
step), then this. The sibling handover for step 1 is `docs/superpowers/handover-0.100-step1.md`; every step's
documents are indexed in `docs/superpowers/plan-0.100-index.md`.

## Where things are

- **Plan:** `docs/superpowers/plans/2026-10-07-one-score.md`. 17 tasks in three phases: A (definition, Tasks 1-6),
  B (incremental forms, 7-10), C (users, gate, removal, 11-17). Its "Decisions" (D1-D18) and "Controller rulings"
  (R1-R15) sections are binding; read them before any task.
- **Specs:** `docs/superpowers/specs/2026-10-06-one-score-design.md` (with its 2026-10-07 amendments at the end and
  the rewritten "Ranking order"), and `docs/superpowers/specs/2026-10-07-surface-escapes-design.md` (written for this
  step; its final "Amendment" section overrides earlier parts).
- **Worktree:** `/home/ben/work/placemat/.claude/worktrees/one-score`, branch `step2-one-score`, cut from main at
  b4c3db39. It has its own `.venv` with the native module built (`include-system-site-packages = true` is needed for
  pcbnew). Run Python there as `.venv/bin/python`; rebuild native with
  `cd native && CARGO_BUILD_JOBS=2 ../.venv/bin/maturin develop -r`.
- **Execution ledger:** `.superpowers/sdd/2026-10-07-one-score/` in the main checkout (git-ignored):
  `progress.md` is the ledger, `constraints.md` the binding block for briefs, `task-N-brief.md` / `task-N-report.md`
  per task, `review-*.diff` packages. Method: superpowers:subagent-driven-development, as the user chose.
- **Versions measured with:** placemat b4c3db39 at the start; KRT `~/work/KRT-upstream` c98d38eb; pcb `~/work/pcb`
  d2b9f749 (`route_ref.current_versions()` still gives "pcbc 0.4.52" until step 1's Task 5b merges).

## Done (on `step2-one-score`)

| Task | Commits | What |
|---|---|---|
| 1 | - | worktree, versions, baseline suite green |
| 2 | b4c3db39..fe368d06 | ratsnest crossings priced by net kind (pair net x5, impedance x3, the dearer of the two), Python and Rust |
| 3 | fe368d06..ee26a098 | run score terms: airwire on signal nets (+ impedance part), declared-link term, congestion every run, fitted frame area, weight-free versioned measures (`"v": 2`), crossings keyed by kind, `prices_of`, `score.whole` |
| 4 | ee26a098..15f46afa | escapes judged by the exact path search with surface lanes as a strict-subset first check; new `escape_via` finding; give-way refreshes the escapes; `fixtures/escape_agreement.py` (801/801 pads agree on 35 bench modules) |

## In flight

- **Task 5** (score.rank, the validity tier as the hard terms' only home, KRT's quality key, `Standing.of_route`),
  dispatched at BASE 15f46afa to an implementer agent of this session. If that agent is gone when you start, check
  `git log` in the worktree for a Task 5 commit and `task-5-report.md`; if there is none, re-dispatch from
  `task-5-brief.md`. If there is a commit, review it (the ledger's review pattern) before Task 6.

## Left

Tasks 6-17 as the plan has them. Points to know:
- **Task 6** re-records `fixtures/bench.json` (still in the old measures format: bench.py reports those rows "new")
  and the reference placement baselines on the new score, then sweeps `score.area` (0.1 / 0.25 / 1.0 per mm2) on the
  fitted reference modules and **asks the user to pick** (D4). The via sweep was dropped (D17).
- **Task 9** carries one item from Task 4: a pad number whose centre lies on none of its outlines (split pads, pin
  plus tab) gets via spots off the box union, which can stand off its copper, so it can read VIA where the search says
  WALLED. Keep only spots that touch an outline.
- **Task 10** sends the speed numbers to the user before the gate's limit is fixed (D3, R15: end to end, not only per
  candidate). **Stop and ask** there.
- **Task 15** is the gate now; **Task 17** waits for step 1 to merge, then measures test (b) closure, merges and tells
  placemat-0.100. Step 2 does not release.

## Decisions the user made (summary; the plan has the full text)

- D1 airwire on signal nets only. D2 a declared-link term. D3 speed gate by kind (parts ~5 us; cells no slower than
  today). D4 `score.area` from a sweep. D5/D8/D10 crossing prices by kind at the pin study's values (pair net 5,
  impedance 3, one setting `score.impedance` also multiplies an impedance net's airwire), a mixed crossing at the
  dearer kind. D6/D9/D18 escapes: a new judgement, defined by the exact path search, lanes only a first check, reach
  3 mm, via-only pad 10 mm, plane pads judged for walled. D7 gate on the new score (definition first, baselines
  re-recorded, then clique vs MST).
- Ranking (D11-D17): validity first (unplaced, DRC *errors* beyond the baseline - warnings never count, failed
  required widths, critical findings), then phase closures (final board, fixed asked sets), clean closure, KRT's
  quality key (vias, copper mm, segments; only when both boards are valid and fully routed), then the run score. Ties
  keep the incumbent; an invalid board never replaces a valid one. The hard terms leave the run score. Area is a
  run-score term, not a tier.

## Divergences from the specs as first written (all chosen by the user, recorded in the specs' amendments)

- New score terms (link, area, kind prices, impedance length) although the one-score spec put new terms out of scope.
- The ranking order, rewritten as above.
- Escapes: a new judgement in place of corridors and confirmed findings.
- Signed incremental changes and pruning only on proved lower bounds (from an outside review): R13.
- Named exceptions to the one objective (pin study bend/group terms, finished-board findings, scan-added costs,
  Python items), and pin-study finalists rescored by the run score: R14.

## Controller rulings to know (all in the ledger with their cost if wrong)

- Measures stay weight-free; weights apply only in `terms()`.
- Another net's script pour blocks an escape (charter, "Fitted, never zones").
- Lanes use the net-class clearance, so they stay a subset of `path_out`, which ignores script clearance rules
  (pre-existing; deferred).
- Give-way apply/undo refresh the escapes for the owners they change.

## Agreed with step 1

Step 1's `RouteReport` supplies `score.rank`'s inputs: `phases[i]["final_closure_clean"]`, `widths_failed`, `drc_new`
(real errors beyond the baseline, None when no DRC ran), `closure_clean`, `vias`, `track_mm` (mapped to the quality
key's copper_mm) and `segments`. Step 1 builds no second comparison.

## Rules that bit

- An implementer once ran `pkill`; every brief now forbids pattern kills (kill only PIDs you started).
- The machine is shared: real-board, bench and reference runs take the realboard lock; pytest `-n 2`; bench `--jobs 2`.
  Bench seconds taken under other sessions' load are not a measure of a change.
- Disk was 63 GB free on 2026-10-07; below 20 GB, stop and ask.
