# Handover: step 1 of 0.100, routing phases (in progress)

For the session that continues step 1. It updates docs/superpowers/handover-0.100.md, which still holds for the lanes,
the shared machine, the release line and the merge rules; read that first, then this, then the plan.

State as of 2026-10-12. Step 0 (the reference set) is merged on main (175358af) and released with 0.99.35. Step 1 is
not merged, pushed or released. 0.100.0 is steps 1 and 2 together (the user, 2026-10-12): step 1's merge releases
nothing on its own; step 2's Task 17 starts when it merges.

## What happened on 2026-10-08 to 2026-10-11

Another agent continued step 1 from 5ec25683 to 9a9e0620. It did Tasks 14 to 25 largely as the plan says, then,
when its reference comparison found worse boards, built a second routing attempt for the last router call (a
"final-call escape candidate", with call replay and a second manufacturing grader) instead of reporting the numbers
and waiting. No user decision covered that work. The reviews of it are in
.superpowers/sdd/2026-10-07-routing-phases/continuation-review-{plan,subsystems,krt,gates}.md.

The user decided on 2026-10-11 to take it out of step 1:
- placemat: kicad/final_*, replay_*, manufacturing_*, issued_calls, pour_identity, board_forms,
  ordinary_route_authority, route_execution_scope, their hooks in route.py, phase_run.py and runner.py, their tests
  and the plan 2026-10-08-final-call-escape-candidate.md are removed (e371e315). The runner calls route_board
  directly again. placemat no longer sets KRT_ROUTE_DEADLINE_UTC; each router call is bounded by its own timeout.
- KRT fork: the proof and final-call code is removed (cleanup-krt-report.md in the ledger folder).
- The work is kept on branches: placemat `park/final-call-continuation` (9a9e0620, local only); KRT
  `park/final-call-continuation` (ef771bd7) and `park/final-call-continuation-base` (abd487bc), on `fork`.

Kept and simplified (1dfdfab2): the width query. Before routing, `kicad/width_policy.py` asks the router
(py_router/nominal_width_policy.py, on the fork's placemat/upstream-2026-10b and so on placemat/connections) which
width it will draw each selected net at, per phase and layer, and each join is judged against that width. It runs
through the same helper as every router call (route.run_router), keeps no hashes of router or board files, and
returns failures as {code, facts}. A query that gives no answer refuses the route: `width_policy_unavailable`
when the router has no such script, `width_policy_failed` for a timeout, a non-zero exit or a malformed answer.

Also fixed (b079eaf5): the plan, spec and test for `run --route-rank` are back to Task 20's design, which the code
follows; the retired-setting refusal no longer reads "set set"; migration.md has the `[route] islands` example.

## What happened on 2026-10-12

- Rulings S13-S23 and decisions D29-D31 are in the plan and the ledger. In short:
  - there are no default phases: `placemat settings --example` writes example phases, ending with a `pours` phase;
  - a pour net named in a phase is joined by the router's via drops (repair_planes.py), then tracked by tasks for the
    pad groups still apart (kicad/pour_join.py), all judged in KiCad's view;
  - an obligation is violated only by a DRC error its phase's input board did not have (S15).
- KRT fork:
  - the pocket-wall rip rule (rounds 1-4);
  - `fp` on `--connections` ends;
  - plane repair for a caller that tracks;
  - the via hole floor (S18);
  - the `apart` task field (S22, S23);
  - diff-pair GND return vias kept clear of the pair (b19e9a51).
  Authors were rewritten to Ben Agricola, so older KRT hashes in this file are stale.
- Main (0.99.36) is merged in (29d49e40). The worktree's _version.py must be main's copy, or the native module is
  not used and routing runs about 4x slower (the first gate run was measured that way).
- Reference runners: a board is worse when closure_clean falls, open connections (pour and non-pour, reported apart)
  rise, or new DRC rises (378733a4).
- The user's gate decisions:
  - pour-net opens now counted are accepted into the baseline, since the old baseline never joined or counted pour
    nets;
  - the esp-rust-board USB short is fixed in the fork's return vias;
  - pic_programmer (b) VCC_PIC and usb-c (b), blocked by earlier-phase copper, are recorded as known.
  Rip-and-reroute is built after the merge and before 0.100.0: a later call may rip earlier-phase copper that blocks
  it, rerouting those connections in the same call at their own phase's settings.

## Read, in order

1. ~/.claude/CLAUDE.md, this repo's CLAUDE.md, CHARTER.md and the memory index (loaded for you).
2. docs/superpowers/handover-0.100.md.
3. The plan: docs/superpowers/plans/2026-10-07-routing-phases.md, in particular "Decisions" (who decided each) and
   "Controller rulings". It is the source of truth for every task's content.
4. The spec: docs/superpowers/specs/2026-10-06-routing-phases-design.md.
5. Research: docs/superpowers/research/2026-10-07/ (zener-stage2-trace.md, krt-connections-design.md,
   krt-rebase-regressions.md, splitflap-pin10/).
6. The ledger: .superpowers/sdd/2026-10-07-routing-phases/progress.md (git-ignored, on this machine), with the task
   briefs, reports, review diffs and the 2026-10-11 reviews in the same folder. constraints.md there is what every
   agent brief carries.

All the 0.100 documents are listed in docs/superpowers/plan-0.100-index.md. The sibling step's handover is
docs/superpowers/handover-0.100-step2.md and its ledger is .superpowers/sdd/2026-10-07-one-score/progress.md.

Method: superpowers:subagent-driven-development, as the user chose. One implementer per task, a task review, fix
rounds with a scoped re-review, the ledger updated after every step. Anything the plan does not cover, and any
result worse than the recorded baseline, goes to the user before work on it starts.

## Branches and worktrees

| Repo | Worktree | Branch | Pushed |
|---|---|---|---|
| placemat | /home/ben/work/placemat/.claude/worktrees/routing-phases | step1-routing-phases (main merged in at 9b4f8be4) | no (local) |
| KRT fork | /home/ben/work/KRT-phases | placemat/connections (b19e9a51) | `fork` |
| KRT fork base | /home/ben/work/KRT-base-10b | placemat/upstream-2026-10b (075c9166) | `fork` |
| Zener fork | /home/ben/work/pcb-phases | feat/nets-layout-json (318b4b0d) | `origin` (benagricola/pcb) |

- Run placemat in the worktree as `PYTHONPATH=<worktree>/src /home/ben/work/placemat/.venv/bin/python`. Tests need
  `KRT_DIR=/home/ben/work/KRT-phases` and `MNB_ECOSYSTEM=/home/ben/Documents/Hardware/mnb-ecosystem`. The worktree's
  src/placemat/_version.py is a copy of main's.
- ~/work/KRT-upstream and ~/work/pcb are live for every session; they move to the fork commits only in Task 26.
  Other sessions own the other KRT-* worktrees: never write there.
- Real-board runs go straight away on a lock of your own: set REALBOARD_LOCK to a path in your scratchpad
  (fixtures/reference/lock.py reads it); never flock the shared lock. Use -j2 at most, and give the load average with
  every timing. Stop and ask below 20 GB free disk.
- Tests (the user, 2026-10-12): no whole-suite runs, not even the fast suite, and not KRT's run_all.py, until the
  merge gate. Run only the named test files covering a change. The full suite runs once, at Task 26.

## Done

| Task | What | Commits |
|---|---|---|
| 1 | Zener branch pushed; worktrees | - |
| 2, 3 | Zener: `clearance` on stdlib net types; nets.layout.json stage 1 | 0d906642, 15c8857c, 10b389aa |
| 21 | Zener stage 2: interface instances and DiffPair pairs in the sidecar | e1c8958e |
| 4, 5 | KRT: clearance and neck floors; `--connections` | on placemat/connections |
| 5a (part) | KRT fork rebased onto upstream 364b4572; router made deterministic | on the base |
| 6, 6a | KRT: `--bus-nets`; per-connection failure evidence (6a's later regression 61235acc reverted in the KRT cleanup) | on placemat/connections |
| 7 | Surface tests, vulture, native dead-code build | 12fc44a5, 25f1fba6 |
| 8-13 | Phase form, sidecar, selection, calls, kept-result chain, phase engine | through 5ec25683 |
| 14 | A failed or stopped route keeps the placed board | 0eea60d3 |
| 15, 16, 18, 18a, 19, 20 | Widths judged per phase; net clearance from the capture; `route --phase/--only`; studio phase report; default phases; `--route-rank` | 10f86d83, e675b3fd, 0d0a5d77, e2d5fb91 |
| 17, 17a | Fixtures and reference set on phases; the obstructed-route fixture | 46536594 .. 5dc3930f |
| 22 | Pairs and interfaces from the capture | e2d5fb91, 0d0a5d77 |
| 23, 24 | circuit-capture rules (local 1efad41, 1475634: 0.1.7, 0.1.8, not pushed); skill gaps | e2d5fb91, 33d09a61 |
| 25 | Fixed stages, `[route] islands`, `pair_layers`, `net_halos`, `route --islands`, class-pattern pairs removed and refused | e2d5fb91, b079eaf5 |

A change in that work that the user has not approved, and should know about (b677898a, which made a join through a
pour or a pad `width_unknown` and never clean, was replaced on 2026-10-11 by measuring the filled copper's width along
the join: fix rounds A and 2, 71b47e65 and e53e49fd):
- Fixture changes on the reference set: the obstructed-route board is 13 mm high, not 12 (the plan's geometry broke
  its own edge rule), and routes with `KICAD_NET_RESCUE=0`; the hand modules had a fitted-pour migration.

## Reference results so far

The baselines were re-recorded on 2026-10-12 (rerecord-report.md and gate2-report.md in the ledger folder):
- test (a) on main with the base router (b0d3bcb2);
- test (b) and the modules at the step's head, with the 11 hand-placed modules new;
- test (a) at the step's head.
The causes of the worse lines are in gate-diagnosis.md. The run after the fixes and the user's decisions is
gate2-report.md.

## Next, in order

1. gate2: write the accepted lines and take any line still worse to the user.
2. Task 26: the full suite (`pytest --full -n 2`) once, then fix rounds; vulture and the native dead-code build;
   merge into main; tell the consolidation session and the step 2 session. No release: 0.100.0 waits for step 2.
3. After the merge, on a branch of its own: rip-and-reroute of earlier-phase copper (the user, 2026-10-12), and the
   router-call cost (each call re-reads the whole board 5-12 times, 3.8 s per read on usb-c).
4. Parked lows, in the ledger:
   - usb-c N1-N3;
   - the fix round A nits and fix round B minors;
   - pour reviews P3-P6;
   - lora-v3's run-to-run variance;
   - spimux's starved_thermal re-matched as new after a refill.

## Decisions the user made (all recorded in the plan or the ledger)

- Step 0 follow-ups pulled into step 1: corner holes held with `overhang=`; a courtyard over a hole follows the board's
  severity (both shipped in 0.99.35); test (b) compares with the regenerated board; the 11 hand-placed modules join test
  (b); results record the pcb fork's commit.
- KRT: keep the floors (D6); rebase onto upstream first (D9); keep upstream 8013c817 and accept esp's +1 DRC; find and
  fix nondeterminism (done: random item uuids).
- `pairs = [["P","N"], ...]` by net names for boards without a capture (D18 replaced); test (a) exercises it on
  esp-rust-board's USB pair (usb-c-power-adapter has no USB data pair; it gets an I2C bus phase).
- D14 every pad of both carrier parts; D19 placement pairs stay for step 1.
- Studio shows the per-phase report; the default-phases test has pairs; stated buses skip detection; a numeric width is
  ignored on current_paths.
- Failure evidence filled in step 1 (Task 6a); an obstructed-route fixture (Task 17a).
- The final-board comparison is step 2's `score.rank`; step 1 supplies its inputs (Ruling S6): phases[i]
  ["final_closure_clean"] over the phase's fixed pad-pair obligations judged again on the final board, widths_failed
  (joined_narrow included), drc_new, vias, track_mm, segments. A width-failed join is never a clean join (S7); widths
  are judged on each obligation's joining path (S8).
- The neck allowance covers copper within neck_mm of each pad only up to half the path's length from each end, so a
  short connection keeps full width in its middle.
- splitflap: when a pin is boxed in, rip the nets whose copper bounds its reachable pocket first (2026-10-07; see
  Next for the open question on esp-rust-board).
- No machine paths in code, tests, fixtures or docs. Zener fork snapshots are updated without asking when a change
  explains them; an unexplained snapshot change goes to the user with its diff.
- 2026-10-11: the four decisions above (machinery removed and parked; pocket rule investigation; pour width measured;
  current-first kept and its starvation fixed).

## Working notes

- Run the touched test files with `--full` before handing back: slow tests hid regressions before.
- Agents in a shared worktree commit only their own paths; tasks that write results.json or edit kicad/route.py run one
  at a time.
- The one-score session (step 2) consumes step 1's RouteReport fields; tell it if a field name changes. Step 2's
  `final_authority` and `final_check_worker` belong to the parked work and should not be merged without the user.
- The consolidation session releases 0.99.x from main and knows the close-via fix ships with step 1.
- The last whole-suite pass (`pytest --full -n 2`) was at b593226e and does not stand for the current head. Task 26
  runs it once.
