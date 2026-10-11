# Handover: step 2, one score

For a new session that builds step 2 of the 0.100 roadmap. Read this first, then `docs/superpowers/handover-0.100.md`,
which holds the shared rules: lanes, the shared machine, forks, release line. Its "Read, in order" list applies to you
too.

## Three sessions now

- **Consolidation:** 0.99.x bug fixes and releases until 0.100.0.
- **placemat-0.100:** step 1, routing phases. Its plan is `docs/superpowers/plans/2026-10-07-routing-phases.md` and its
  ledger is `.superpowers/sdd/2026-10-07-routing-phases/`. It owns the 0.100.x releases.
- **You:** step 2, one score.

You do not release. When step 2 is complete you merge it into main, after step 1 has merged and after your gate passes
(below). placemat-0.100 then releases it in its next 0.100.y. Tell that session, by message, when you merge.

## Your step

Spec: `docs/superpowers/specs/2026-10-06-one-score-design.md`. Also read the roadmap
(`docs/superpowers/specs/2026-10-06-roadmap-0.100.md`): the "Attribution" and "Gates" sections, and the removal-ledger
rows marked step 2. The research behind it is `docs/superpowers/research/2026-10-06/placement-inventory.md`, sections 1
and 3.

1. **Write the plan** with superpowers:writing-plans. The user chose subagent-driven execution. Give the user a short
   rundown, and ask about the plan as multiple-choice questions; they do not read long documents by hand.
2. **Build it** in a worktree under `.claude/worktrees/`, from main.
3. **Gate, in two parts:**
   - **Now:**
     - the incremental-against-whole tests for every term;
     - the bench in all three configurations;
     - the placement-only measures on the reference set: the run score, crossings, airwire, and area for fitted
       modules;
     - the speed limit of about 5 us per candidate, measured natively.
   - **After step 1 merges:** test (b) closure on the reference set, measured with step 1's routing. Until then no
     result of yours is compared on closure (roadmap "Attribution": placement is measured with the routing that ships).
     Rebase onto main, then run it.

   The search's switch from the clique to the MST change is adopted only if the gate passes. If it fails, the search
   keeps the clique as a documented divergence, and the numbers go to the user.

## Lessons from step 1

- **Decisions.** A plan's decisions that change what is built or measured are asked of the user, as multiple-choice
  questions, before they are applied. A list headed "to confirm" is never applied unconfirmed. Internal rulings are
  yours, recorded in the ledger.
- **Merge order.** The full suite (`pytest --full -n 2 -p no:cacheprovider`), the bench, the reference runners and the
  unused-code check all pass before the merge, never after.
- **Versions.** Results compare only like with like. Make sure the placemat commit is recorded, along with the router
  and toolchain builds by commit, not just version string. step 1 is fixing the pcb version; check that it has landed
  before you rely on it.
- **Removal ledger.** Every row marked step 2 is removed in step 2, with its migration entry. The reference scripts are
  migrated in the same change.

## Measured since the spec

`docs/superpowers/research/2026-10-07-refine-spike.md` measured the search's `Scorer` on the fairing core's cells at
136 us per legal candidate (the wire term alone 52 us). The one-score spec's speed limit of about 5 us per candidate
assumed the sweep's 1-2 us. Plan for that gap: measure where the time goes before setting the gate, and tell the user
if the limit is out of reach.

## Ask the user about

- The `score.area` default weight, and any other weight the plan sets. Tunables are settings with documented defaults.
- Anything the gate shows is worse.
