# After 0.100: refine and the automatic loop

Status inspected 2026-10-13. Release integration is on
`release/0.100-integration`, outside the active implementation worktrees.
The user chose to ship steps 1 and 2 first and test them on a working board.
Do not restart the superseded October 8 scratch qualification programme.

## Step 3: finish the existing refine implementation

Worktree: `.claude/worktrees/refine`, branch `step3-refine`.
Plan: `docs/superpowers/plans/2026-10-11-refine.md` in that worktree.
The current ignored progress ledger is in the main checkout at
`.superpowers/sdd/2026-10-11-refine/progress.md`. Older handovers describe
earlier states; use the ledger and actual source changes together.

The implementation includes the native held-board judge, coarse and fine
refine, member constraints and cell arrangements. The ledger records tasks
through 11b and task 13 complete. Task 12 was dispatched and has uncommitted
implementation work; preserve it and finish its review before rebasing.

Remaining work:

- Finish task 12: integrate refine into resolve, replace cleanup's call,
  refresh findings after moves, and handle replay/settings/seed correctly.
- Task 11c: re-plan module-declared tracks and vias when members move,
  refuse a move whose copper cannot be rebuilt, and use a separate module
  budget (D17/D18, provisional 2,000 moves).
- Task 14: measure the provisional budgets and alternative margin; keep
  the accepted provisional speed decision D16 rather than reopening the
  old throughput requirement before implementation can continue.
- Task 15: explore using refine and confirm changed pin-study rankings
  against the common score.
- Task 16: remove the superseded APIs and migrate their callers, including
  cleanup, locks/freeze, declared alternatives and units as the plan says.
- Task 17: run the final correctness and placement/routing gates once on
  coherent source and report actual regressions without repeatedly tuning
  the whole corpus.
- Task 18: pass the routing obligations of lifted module tracks to phases,
  preserving width, layer and ownership requirements.
- Task 19: consume per-connection routing failures as refinement feedback.
- Task 20: integrate current main, review the whole change, and merge.

After finishing the active task, rebase onto the released steps 1 and 2.
Reconcile scorer/settings retirements, cleanup removal, planned-join layer
metadata, final routed validity/quality, and current-width/rip obligations.
Preserve focused exploration's compatible plain-standing reuse and its
declaration/version authority checks when wiring refine into replay.
Retain the existing retry.attempt implementation for step 4 reconstruction;
do not build a second retry engine. Restore released migration sections
exactly from their tags.

Refine may ship before the automatic loop. At that point the skill must
name its actual supported interface and instruct agents to propose a local
refine trial, route it, compare final boards, and restore rejected trials.

## Step 4: implement the automatic loop

Spec: `docs/superpowers/specs/2026-10-06-place-route-loop-design.md`.
There is no implementation plan or completed step 4 branch yet. Write the
plan against the released phase engine and the completed refine interfaces.

The work is a controller that places/refines, routes and judges trials;
holds one incumbent by score.rank; and restores poses and copper together
on rejection, failure or cancellation. A placement-score improvement is
only a proposal until the routed final board is judged.

Add routing feedback rounds, bounded plateaus, selective phase rerouting,
and a fresh final route. Then add atomic neighbourhood reconstruction:
select a failed connection, lift a bounded cluster across module boundaries,
hold the rest of the board, try different arrangements, route them, and keep
only improvements. Preserve fixed and single-axis constraints, module pour
groups, copper ownership and electrical reasons. Exhaust these local trials
before paying for fresh restarts. Record router facts separately from
placement inferences and expose outcomes in run.json, watch and the studio.

Until this controller ships, the Placemat skill's manual loop is the agent's
workflow. Its checkpoint and acceptance rules remain necessary when refine
ships on its own.
