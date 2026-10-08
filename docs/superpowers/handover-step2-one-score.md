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

## Continuation status, 2026-10-08

Step 2 remains in its feature worktree. Scoped common-score, native delta,
final critical checks, pin finalist and placement comparison changes have been
reviewed; this is not completion of the full comparative or integration gates.
The area weight 0.25 remains provisional, the search defaults to the clique,
and the user has not chosen the performance gate or an area default.

Contact-index commit `9f291834` is bound to genuine editable version
`0.99.35.post1.dev88+g9f2918340.d20261008` and native SHA-256
`197f9e2699c4f8204f63f4dcbc99d3923802514da4113fe8246e98f814297119`.
The owned corpus job passed both cases in 632.34 seconds, with unchanged
runtime/input identities: 4,000 synthetic candidates, then 153 native part
candidates across six actual modules. The written core has zero native cell
coverage and twelve documented invalid fixed-frame fallbacks. A separate
122.16-second job proved exactly four distinct actual free-core cell poses,
with 789 independent Python/native pad judgments per pose, raw/whole parity
and source restoration. Receipts, wrappers, hashes and logs are in the
task-owned `placemat-review-scratch-20261007/step2` directory. These are
correctness proofs, not performance measurements.

Earlier bounded timing at native `c200` showed substantial measured regressions:
generated free-core resolve 355.91 seconds versus clique 32.06, and the third measured module
29.32 seconds versus 2.37. The 600-second diagnostic timed out before complete
instrumented core counters; its external end-identity audit is recorded. No
native `197f` speed improvement or adoption decision has been established.

The shared rank helper now supports the settled per-run named phase order:
all original phase contracts are validated, requested phase closures compare
in the supplied order, then whole closure and normal quality/score tiers.
Omitted phases are not inserted before whole closure. Default comparisons,
including final-call acceptance, retain the full configured order. Step 1's
`Routing.rank` plumbing belongs to the root-owned combined review checkout.

The exact pin writer/readback work is still under review. Reserved artifact
names and refused-readback preservation have pure coverage; saved pose gates,
manufacturing/footprint identity checks and routed logical-role projection
remain open. The retained full-board authority must independently bind the
actual original selection and resolved width receipt, preserve held geometry
and fixed copper, rejudge final critical checks, and withhold adoption for
unknown required-width evidence. A descriptor alone cannot enable it.
Root owns combined integration; no main merge or optional routing activation
has occurred.

The earlier timing counter interpretation is corrected: `common_python_evaluation_share=0`
means no Python fallback, not no native scoring. At native c200, the first/second/third instrumented module rows ran
224/1855/4913 legal NativeDeltaScoring candidates
respectively, with no Python common calls. The generated-core instrumented row
was absent after timeout, so actual production free-core native coverage remains
open. Direct four-pose native197f correctness does not fill that production gap.

Final-check context and worker composition are narrow, unactivated transports.
The owned process supervisor, original selection/width binding, private evidence
import and retained full authority remain required. The writer physical gate now
contains nine saved cases: fixed copper/project/capture plus part/cell front/back
poses at 90 and 37 degrees. A 37-degree serialization mismatch must explicitly
refuse without publication; no tolerance is authorized. These saved tests have
not yet run. D3 comparative performance and D4 responsive area weighting remain
open, default clique and area 0.25 remain provisional, and no user decision has
been inferred.

At frozen 767/dev93/native197f, a bounded actual free-core production scan
used one legal complete NativeDeltaScoring candidate with no refusal. The
wall tier, complete total and six raw terms matched forced Python; source and
all runtime/input identities were restored/unchanged. This is one-pose usage
evidence, not whole-core throughput. Receipt: task scratch
`step2/free-core-production-receipt.json`.

The first nine-case saved writer gate failed before useful proof: eight cases
used a nonexistent KiCad footprint-shape class, and the map fixture attempted to swap a singleton unused pool net as a
logical role. The fixes use the existing PCB_SHAPE footprint API and give
every permuted role a real external test-point endpoint before the initial
immutable fixture snapshot. No evaluator/writer
contract is relaxed. The original failed receipt/log remains preserved;
a fresh saved gate is still required.
