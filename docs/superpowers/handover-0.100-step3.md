# Handover: step 3, refine

For the agent that plans and builds step 3 of the 0.100 roadmap. Read this first, then the shared rules in
`docs/superpowers/handover-0.100.md` and the index `docs/superpowers/plan-0.100-index.md`.

## Your reporting line

You report to the consolidation session, which dispatched you. It monitors your work, relays the user's decisions, and
keeps you current with steps 1 and 2. Do not message the step 1 or step 2 sessions. Questions for them go through your
reports.

## The state of steps 1 and 2 (2026-10-11)

- **Step 2, one score** (branch `step2-one-score`, worktree `.claude/worktrees/one-score`, handover
  `docs/superpowers/handover-0.100-step2.md`, ledger `.superpowers/sdd/2026-10-07-one-score/progress.md`):
  - done through Task 14 and 15a, including `score.rank`, the run-score terms (area, congestion, links), crossings priced
    by kind, and escapes by exact path search;
  - in its gate (Tasks 15b-d, 16);
  - Task 17 waits for step 1 to merge.
  - Its score interface is what refine is built on.
- **Step 1, routing phases** (branch `step1-routing-phases`, worktree `.claude/worktrees/routing-phases`, handover
  `docs/superpowers/handover-0.100-step1.md`, ledger `.superpowers/sdd/2026-10-07-routing-phases/progress.md`):
  - about half done;
  - per-connection failure evidence (KRT Task 6a) is in flight. Refine's routing feedback reads it.

## Your step

**Spec:** `docs/superpowers/specs/2026-10-06-refine-pass-design.md`, with every amendment through bdfa0ac3. Also:
- `docs/superpowers/specs/2026-10-06-one-score-design.md` and step 2's amendments to it;
- the roadmap's "Attribution", "Gates" and removal-ledger rows marked step 3;
- the research: `docs/superpowers/research/2026-10-07-refine-spike.md` and
  `docs/superpowers/research/2026-10-06/placement-inventory.md`.

**Scope of this step:**
- coarse refine: every allowed pose of every cell and part, each with a short local refine, and the pin study inside it,
  with its legality check;
- fine refine: annealing moves scored by the one score's incremental change;
- each relation's room: a `Beside` slides along its target's side, so `Beside` a pad much less than `Beside` an IC. This
  applies to every decided item;
- cells refined as members:
  - members joined by module pours stay grouped;
  - the module tracks of moved members are re-routed;
  - `rigid=True`;
  - the constraints note each module run writes, carried with the stamp (the spike's option (c));
- the snapshot (`<stem>.placement.json`) replacing the lock, with `--pin` for one run and the `.lock.json` conversion;
- the native batched judge, and native lift and commit. The spike measured that the Python loop around the judge, not
  the judge, limits speed;
- the removal-ledger rows marked step 3: cleanup, the lock, `freeze`, alternatives and units, `--rank-remapped`, turn
  advice on items refine may move;
- migrating the reference scripts and fixtures in the same change.

**Not in this step:**
- **Routing feedback** (spec, "Routing feedback"): it needs step 1's per-connection failure records. Plan it as the last
  task, and build it only once step 1's Task 6a and its placemat reader have landed.
- **The neighbourhood rebuild:** built with the loop in step 4 (index), although its spec text sits in the refine spec.
  Keep your interfaces open for it: a lifted group, scored and re-placed.

## Working with steps 1 and 2 still moving

- **Base.** Branch `step3-refine` from the head of `step2-one-score`, in a worktree `.claude/worktrees/refine`. Copy
  `src/placemat/_version.py` in. For native work, give it its own `.venv`.
- **Before each task:**
  - check `git log step2-one-score` and `git log step1-routing-phases` since your last check;
  - rebase onto `step2-one-score` when it has moved, and note in your ledger what changed in an interface you use;
  - once step 2 merges into main, rebase onto main.
- **The plan** is written against the score interface as it is on `step2-one-score`, citing file:line. If step 2's gate
  changes that interface, revise the affected tasks before building them.
- **Measurement (attribution).**
  - Placement-only measures can be taken now: the run score, crossings, airwire, area, and the bench.
  - Test (b) closure is measured only after step 1 has merged, using its routing.
  - Every result records component versions by commit.

## How to work

1. **Write the plan** with superpowers:writing-plans, saved as `docs/superpowers/plans/2026-10-11-refine.md`.
   - List the decisions it needs that change what is built or measured. Mark each as a question for the user, with
     options, and do not apply any of them.
   - Internal rulings are yours. Record them.
   - Report the plan and the questions, then stop. The consolidation session puts the questions to the user and sends
     you the answers.
2. **Then build** with superpowers:subagent-driven-development, the user's chosen method. Keep a ledger at
   `.superpowers/sdd/2026-10-11-refine/progress.md`. Each task needs a review before the next.
3. **Gates:**
   - speed: at least 2,000 moves a second on the fairing core, with a target of 10,000. Take the spike's measurements
     as the baseline;
   - the bench in all three configurations: no fixture worse;
   - the reference set's placement-only measures: no board or module worse without the user's approval.

   A failed gate goes to the user with the numbers.
4. **Merge** only after steps 1 and 2 have merged, with:
   - the full suite (`pytest --full -n 2 -p no:cacheprovider`) green;
   - the bench, both reference runners and the unused-code check passing;
   - every step 3 ledger row removed, with its migration entry.

   Run all of that before the merge, never after. You do not release; placemat-0.100 releases.

## Rules that bit steps 1 and 2

- **Decisions:** a decision that changes what is built or measured is the user's, asked as a multiple-choice question.
  A list headed "to confirm" is never applied unconfirmed.
- **Versions:** compare only like with like, by recorded commits.
- **The shared machine:**
  - real-board runs go one at a time under
    `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock`;
  - `-n 2` at most;
  - kill only your own PIDs;
  - when disk space runs short, stop and ask.

  Steps 1 and 2 also run on this machine, so your runs will wait for the lock.
- **Commit messages:** no "claude", "anthropic", "session" or "co-authored". Check with
  `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`, which must print nothing.
- **Plain ASCII** everywhere.
- **Structured data inside, text at the edge.** Tunables are settings with documented defaults.
