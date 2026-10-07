# Step 1 amendment: a bounded escape candidate for the final copper call

Status: reviewer-authorized design and proof plumbing; document review and all
implementation/physical gates remain required before merge. This amends Task 26
of `2026-10-07-routing-phases.md`. It does not authorize another routing budget,
a third router candidate, wider repair scope, or weaker width certification.

## Evidence and problem

The PicProgrammer B comparison used identical original input geometry and project
rules. Under one selected-pad/effective-width contract the old saved board joins
86 signal obligations and the new board joins 85. Both have no real errors under
the original project. Old paths remain conservatively width-unproved; they are
not full required-width certificates.

An owned observer replay captured the actual rescue decisions. Both old and new
calls consider JP1.2 bare and invoke its tap. The old tap creates a nominal via;
both new candidates report the via blocked. New rescue-time copper from another
signal overlaps the old successful via site. This establishes an ordering/terrain
interaction, not impossibility of every alternative site. The earlier suspected
proximity eligibility defect is disproved for this case. The old replay uses the
captured historical source but its exact historical B native hash is unavailable;
that limitation remains in its evidence. No reference coordinates, net names,
pad names, or geometry changes belong in the implementation.

## Narrow scope

The executor must provide explicit proof that the eligible call is the final
copper-changing call of a complete board route. A last phase name alone is not
proof: subsequent pair, connection, deferred connection, pour, bus, tuning,
cleanup, or other copper-changing work counts. A partial `--phase` run, unknown
remaining work, unsupported finalization, or unavailable final-board checker
withholds this candidate. Physical finalization is included in the comparison.

Only an active single-ended call is eligible. Ordinary/rest calls may seed only
their actual selected nets; explicit connection/current calls may seed only their
declared physical endpoints. A bus must bind its call/group endpoint boundary;
unsupported or unproved group scope withholds the candidate. Pair calls
and pair-owned nets inherited by default REST do not acquire single-ended escape
semantics. Earlier phase copper stays fixed. Nothing is borrowed from later
phases or unrelated same-net terminals. Numeric, current-task and raw-argument
width precedence remains the router-authoritative policy already implemented.

## Two slots, one shared budget

The existing legacy slot remains the incumbent. After its actual failure evidence
is available, one escape-first slot may replace the existing pocket slot. It must
never supplement it. Without validated eligibility evidence, existing legacy plus
pocket behavior remains unchanged. All children, probes, grading and finalization
share the existing absolute deadline and owned-process cleanup contract. If the
remaining budget cannot produce and grade the candidate, retain the incumbent
and record exhausted/unproved evidence. No retry receives another budget.

Eligibility must bind the actual incumbent failure to the immutable incoming PCB,
project/custom rules, selected terminal, effective nominal policy and router
source. Require an authoritative graph showing that the selected surface
terminal's component lacks a join to its required peer, and an actual nominal
tap failure with a blocked via. This does not require a copper-free pad, and an
unrelated fragmented same-net component is not eligibility evidence. A stale report,
unbound terminal, inferred failure category, graph uncertainty or already
connected terminal does not trigger replacement. Keep individual rescue epochs
and candidate contexts; do not deduplicate away their order.

## Candidate execution

Start from the same immutable incoming PCB as the incumbent. Reuse the existing
overlap-aware connectivity graph and the initial nominal `try_tap_pad` operation.
Do not call the escalation ladder: required tracks, clearance, via/drill limits,
per-layer widths, neck policy and original manufacturing constraints remain
unchanged. Attempt at most one local seed operation per eligible endpoint and at
most the existing four escape successes per net. Reuse existing bounded local
search/radius and cancellation/deadline facilities rather than inventing an
unbounded alternative-site search or an undocumented tuning constant.

Preserve all fixed input copper and held placement. A seed is topology evidence,
not a joined-obligation or width certificate. Run ordinary routing after the seed
with the original scope and flags. Preserve failed/partial candidate artifacts,
but never publish them as the successful incumbent output.

## Complete-board adoption

Retain the complete incumbent artifact and its report. Finalize and independently
grade both complete boards under the same original project/custom rules, all
stable earlier and final phase connectivity obligations, effective required
widths, captured intent, and critical electrical/current checks. The integrated
full-board Standing comparison is the adoption authority; per-net local grading
cannot substitute for it. If that authority is unavailable, candidate adoption
is withheld rather than replaced with a permissive local comparator.

Adopt only a strictly better comparable complete-board result. Ties, missing
proof, worse manufacturing legality, worse required-width evidence, earlier-phase
regression, or unmeasured final critical checks retain the incumbent. Restored
connectivity whose required width remains unknown is diagnostic-only when the
full comparison cannot adopt it. No width proof, reference pin or legal closure
is weakened to make the new strategy succeed.

## Implementation and review gates

1. Review this amendment and the concrete planner/proof/receipt interfaces before
   physical validation. Keep the final-board comparison dependency on Step 2
   explicit; merge integration must not enable an unavailable authority.
2. Add structured actual escape failure evidence and stale-proof validation in
   the router. Keep failure categories tied to observed branches, not guessed
   geometry. Add an explicit receipt for pocket-slot replacement or refusal.
3. Add final-copper-call proof in the executor, including later/deferred calls and
   finalization. Bind input, rule, policy and scope identities; retain incumbent
   outputs while the candidate runs.
4. Test later copper-changing calls, partial runs, task endpoint scope, bus/pair
   ownership, already-connected terminals, nominal-only tapping, missing/stale
   failure proof, deadline/owned process cleanup, and final earlier-phase/width/
   critical-check regression. Verify no third candidate and no deadline extension.
5. Review concrete implementation and scoped tests before one bounded actual
   Pic comparison. Grade original rules and full contracts, record conservative
   width outcomes and individual candidate epochs, and retain unchanged input.
6. Resolve the merge blocker through the accepted final comparison or report the
   remaining limitation explicitly. Then finish the finite reference/common-audit
   and latest whole-full checklist. No repin or broader search is implied.
