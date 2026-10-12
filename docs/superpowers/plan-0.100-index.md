# The 0.100 work: where everything is

An index of the documents behind the 0.100 release line, step by step, and where each step stands. The overarching plan
is the roadmap; each step has a spec, a plan and a handover. Read the roadmap first.

As of 2026-10-12.

## The overarching plan

- **Roadmap:** `docs/superpowers/specs/2026-10-06-roadmap-0.100.md`. It sets the steps and their order, the work
  outside placemat (the router and Zener forks, the circuit-capture skill), the reference set, attribution, the gates,
  the removal ledger, keeping dead code out, and the release line (0.100.y per step; the user cuts 1.0 after step 4).
- **Shared handover:** `docs/superpowers/handover-0.100.md`. It covers the lanes (two 0.100 sessions plus the
  consolidation session that releases 0.99.x), the shared machine (realboard lock, CPU, disk), the forks and the release
  steps. It applies to every step.

## The steps

| Step | What | Spec | Plan | Handover | Ledger (git-ignored, main checkout) | State |
|---|---|---|---|---|---|---|
| 0 | The reference set: eight human-routed open boards, test (a) route and test (b) place-and-route runners, the baseline | the roadmap, "The reference set" | `docs/superpowers/plans/2026-10-06-reference-set.md` | done; see the step 1 handover | deleted after merge (a copy of the step 0 ledger is in the 2026-10-06 session scratchpad) | merged 175358af; released in 0.99.35 |
| 1 | Routing phases | `docs/superpowers/specs/2026-10-06-routing-phases-design.md` | `docs/superpowers/plans/2026-10-07-routing-phases.md` | `docs/superpowers/handover-0.100-step1.md` | `.superpowers/sdd/2026-10-07-routing-phases/progress.md` | merged 28d22451 (2026-10-12); not released: 0.100.0 is steps 1 and 2 together. Next on its own branch: rip-and-reroute of earlier-phase copper |
| 2 | One score | `docs/superpowers/specs/2026-10-06-one-score-design.md`, with `docs/superpowers/specs/2026-10-07-surface-escapes-design.md` (the escape judgement, built in step 2) | `docs/superpowers/plans/2026-10-07-one-score.md` | `docs/superpowers/handover-0.100-step2.md` (and the original brief `docs/superpowers/handover-step2-one-score.md`) | `.superpowers/sdd/2026-10-07-one-score/progress.md` | in progress; branch step2-one-score; Task 17 starts now that step 1 is merged |
| 3 | Refine | `docs/superpowers/specs/2026-10-06-refine-pass-design.md` | `docs/superpowers/plans/2026-10-11-refine.md` (being written) | `docs/superpowers/handover-0.100-step3.md` | `.superpowers/sdd/2026-10-11-refine/progress.md` | started 2026-10-11 from step2-one-score; branch step3-refine; routing feedback waits for step 1 |
| 4 | The loop | `docs/superpowers/specs/2026-10-06-place-route-loop-design.md` | not written | not written | none | not started |

The four original designs are steps 1-4 (routing phases, one score, refine, the loop). Step 0 was added to measure
them. The neighbourhood rebuild (lift a cluster and rebuild it) was added to the refine and loop specs on 2026-10-07
(972c5e72, bdfa0ac3); it is built with the loop in step 4.

## Releases while 0.100 is in progress

From the step 1 merge until 0.100.0 ships, 0.99.x releases are cut from `release/0.99`, which branches at main's
958a4b84 (the commit before step 1 merged); fixes are cherry-picked onto it (the user, 2026-10-12).

## Research

- `docs/superpowers/research/2026-10-06/`: the evidence the original specs cite (route stages, class stage, boxed
  routes, placement inventory, perf, GPU study, studio audit, Zener net export, the reference corpus).
- `docs/superpowers/research/2026-10-07/`: Zener stage 2 trace, the KRT `--connections` design, why the router
  rebase made two reference boards worse.
- `docs/superpowers/research/2026-10-07-refine-spike.md`: refine's spike (declarations carried with a cell; move speed).

## Outside reviews

An outside reviewer's notes on the 0.100 specs (2026-10-07) were forwarded by the user; there is no file of them in
the repo. They led to: signed deltas and proved lower bounds for pruning, and escape invalidation by target change (step
2, applied); one final-board comparison, `score.rank` (step 2, with step 1 supplying its inputs); failure evidence per
connection and an obstructed-route fixture (step 1); one constraint representation, copper ownership for member moves,
plateaus and the neighbourhood rebuild (steps 3-4, in the specs).

## Forks

- Router (KiCadRoutingTools): https://github.com/benagricola/KiCadRoutingTools, remote `fork`. Step 1's branches:
  `placemat/upstream-2026-10b` (rebased onto upstream 364b4572, deterministic; 075c9166) and `placemat/connections`
  (96e0422f at the merge). The shared ~/work/KRT-upstream and ~/work/pcb move to them at the 0.100.0 release. Never push
  upstream; never open issues or PRs there. Divergences are listed in `docs/fork-divergences.md` on
  `placemat/connections`.
- Zener (pcb): https://github.com/benagricola/pcb, remote `origin`. Step 1's branch: `feat/nets-layout-json`.
  Upstream's AGENTS.md was removed from the fork; snapshots are updated when a change explains them, and an
  unexplained snapshot change goes to the user.
