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

## Saved writer and remaining finite gates (2026-10-08)

The corrected nine-case saved writer gate at `997fa5ae` / genuine dev95 /
unchanged native `197f9e26` failed: seven failures and two arbitrary-angle
refusals passed. The later five-case exact diagnostic reproduced all five
selected failures in 2.269 seconds, with unchanged runtime/input identities.
Its receipt and retained before/after boards are in
`/home/ben/work/placemat-review-scratch-20261007/step2/writer-exact-diagnostic-receipt.json`
and `writer-exact-diagnostics/` beside it. These are failure evidence, not
writer approval.

The exact differences separate three causes. A fixed track actually changes
net after a connected pad permutation; publication must continue to refuse
that change. A compatible positive map must keep fixed electrical items away
from reassigned pads; the attached-track scene is also a useful refusal test.
Quarter-turn physical pad and nanometre collision geometry agree, but polygons
use different starting vertices/winding. The exact comparison now canonicalizes
only those enumeration choices, retaining every coordinate and all other
shape fields. The cell fixture grouped its external endpoint internally,
leaving no movable logical role; its replacement retains a genuine external
endpoint and two moved members. Saved physical gates must be rerun after review;
27 default writer/timing cases passing does not replace them.

The next finite gates are: five-case diagnosis (completed), reviewed nine-case
writer proof (180 seconds), current fixture-separated complete candidate and
fresh resolve timings (bounded 600-second batches), responsive area search and
actual representative weight sweep (120 / 600 seconds), routed explore
integration (300 seconds) and prescribed regression bench (1200 seconds), then
latest feature and combined whole suites (3600 seconds each). Exact wrappers,
coverage assertions, frozen genuine installs and serialized lock handoffs are
required for each launch. Missing coverage or timeout can establish a failed
speed gate; it cannot become a successful corpus median. Task 15's prescribed
full correctness/reference coverage remains required independently of the D3
performance choice.

A simple actual MST placement responds to area price: weight zero keeps area
244.24 square millimetres, while positive tested prices choose area 222.44.
That linkless scene proves responsiveness, not a tradeoff between competing
objectives or a justification for the provisional 0.25 default. D4 remains
open. Timing now distinguishes the first evaluation after preparation from
warmed corpus medians; shared libraries/process state may already be warm.
D3 remains open, with prior slower actual resolves and incomplete instrumented
core receipt retained.

The optional final-call copper-only retained authority and routed pin logical
role projection are separate gates. Neither a physical public grader object
nor its hash descriptor proves original execution custody. Optional adoption
still needs bounded original-baseline verification, retained original settings,
private worker evidence import and fixed/held physical preservation. It cannot
certify pin reassignment. Routed pin comparison additionally requires validated
complete pool bijections, exact emitted readback, fresh physical phase/width
receipts and the reviewed logical-role projection. All authority drafts remain
inactive; generic Standing comparability remains strict.

### Current saved-writer and owned-worker status

The saved ten-case gate at `d4a0ccff` completed with seven passes and three
failures, with identical start/end runtime and input identities. Compatible
fixed track/via/zone preservation, attached-copper refusal and the four part
pose cases passed. The remaining cell cases exposed test-domain mistakes:
external footprints must remain unchanged, and the existing pin study holds
cells on their current face. Commit `329fe7cc` corrects those assertions and
requires explicit `pose_not_allowed` refusal before publication for cell flips.
The corrected ten-case physical gate at `2f25538f` passed all ten cases in
3.104 seconds with unchanged source, runtime, inputs and supervisor. Earlier
failed XML and receipts remain preserved. The later shared canonical readback
refactor at `956decf5` still requires its final saved gate.

Fixed electrical geometry now compares exact structured multisets, preserving
all Shape fields and duplicate counts while ignoring serializer iteration
order. The writer restores original project/rule/capture bytes after native
Save and before readback, then checks them again before publication. A native
Save that retags an attached original track remains a refusal. Cell assignment
recognizes only declared physical slot endpoints as movable and retains every
other carried member endpoint exactly.

The owned critical worker now transports retained source physical manifests,
original verification and actual implementation start/end identities alongside
final judgments. Its preservation reads use the original settings. The
retained factory and original-selector/width verifier are concrete source.
The small combined owned-worker gate at `60050fdf` proved private executor
custody, original baseline remeasurement, held/static copper and zone intent
preservation, and independent parent import: valid, new DRC zero, required
width failures zero, unknown evidence empty and complete clean closure.
Optional router strategy activation remains withheld. Exact serialized lock metadata is
still part of preservation; no operational lock changes are silently ignored.

The prescribed fitted reference sweep has now completed: five existing fitted
intent scripts at 0.1, 0.25 and 1.0, all fifteen placements successful, 125.648
seconds. It used clean combined `60050fdf`, genuine dev217 and native SHA
`6aaee5b5`, unchanged default clique, original cached generations and constraints.
Every runtime/input/helper/supervisor identity and the original PCB cache remained
unchanged. The fifteen-row receipt and compact table are in the task scratch
folder as `fitted-area-current-receipt.json` and `fitted-area-summary.json`.

The five fitted areas were 202.079692, 107.658884, 256.290888, 35.269938 and
234.325451 square millimetres, with 23, 12, 22, 7 and 27 placed components.
Within each reference, all three weights produced identical placement measures;
only the area contribution to common score changed. This is a real, complete
measurement, but does not establish a unique best area weight. D4 user choice
remains pending and 0.25 provisional. The earlier 99-row table compared scoring
configurations, not area weights. The eighteen direct-glob intent scripts were
found ineligible for this sweep because none declares a fitted frame; no
irrelevant fifty-four-row run was launched.

Commit `956decf5` adds sealed logical endpoint roles and shared canonical saved
readback values. Same-net roles remain whole-net connectivity obligations, and
explicit tasks touching reassigned parts or unmeasured critical contexts refuse.
Every minted physical identity is independently retained and checked before use,
including nested mutable fields; weak lifetime cleanup prevents registry leaks.
Fresh hash-seed processes produce identical typed readback records. Parent
review and 39 default cases passed, with ten saved cases explicitly omitted.
This endpoint/readback evidence does not authorize routed comparisons. The
separate logical routed authority, original-baseline custody, fresh physical
phase/width receipts, final saved readback and broad integrated gates remain
required. Generic Standing still refuses different physical contracts. Current
bounded comparative timing batches remain incomplete speed-gate failures; D3
user decision and Task 15 full correctness/reference coverage remain open.
