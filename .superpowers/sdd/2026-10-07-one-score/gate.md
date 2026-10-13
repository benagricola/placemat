# Step 2 gate: measured status, 2026-10-08

Historical evidence from 2026-10-08, not the current release gate. Later user
decisions D25, D28 and D30 supersede the pending choices and recommendations
below. Preserve the source-scoped receipts; use
[the 0.100 qualification record](../../../docs/superpowers/0.100-qualification.md)
for current integration status.

This is a review draft for Task 15 step 7. Step 2 is not complete. Search remains clique; area price 0.25 is provisional. D3 and D4 await the user's decisions. No API removal, default switch or merge follows from this record.

## Provenance and interpretation

The historical reference and core measurements use isolated combined commit `f4851a6a3e2811d4757b37d518fdedcbeea0e784`, genuine distribution `0.99.35.post1.dev250+gf4851a6a3`, and native SHA-256 `6aaee5b59778a103cd01eae00de738cd53db3d8f845cd82d0380b7855c0741ce`. Board reference measurements precede the outline-free turn correction: combined `f4e779722839f3b0358e1214b8c5a1e798f933e1`, genuine dev249, same native binary. Earlier corpus gates used combined `0901b588`/genuine dev245 with the same native binary; receipts retain full hashes. Current combined review is `c780`/genuine dev254 after reviewed Step 1 staging; no final gate has run on that current source.

Tools were frozen at routing commit `1c9de25d20757894b874b59c98499896ef35809d` (native `261c181679d68c02cdc0a5290fb8a3f928f54af813e38d3668c512b923a460f1`) and generator-tool commit `318b4b0d19ce55bc032c70941a2559b9b7728404` (binary `9464bb2aa1fccbd945e90e7cf984da8d657633967c1b6dd069c1916a491d097f`). Owned supervisors serialized the shared lock, isolated the generation cache and retained source/input/tool/runtime hashes. No timeout was extended.

Common Measures below are placement diagnostics. Alternate-search run scores are retained in raw rows but are not a common-quality comparison. These runs did not route reference boards. New historical rows are not a no-worse certificate. Raw failure receipts are retained even when a later pure schema correction qualifies a measurement.

## Criterion verdicts

| Task 15 criterion | Actual evidence | Verdict |
| --- | --- | --- |
| Whole suite on final source | Final feature and combined whole suites not run | Open |
| Incremental against whole | 113 passed, zero skips/failures, 636.548 s, at 0901 | Passed for that frozen source; final coherent freeze still required |
| Bench, 33 inputs × 3 configurations, clique | 99 measured; all 99 same/no-worse, 69.772 s, at 0901 | Passed scoped comparison |
| Same complete bench, MST | Original run failed at 1754.432 s on blank-net delta; corrected run expired at 1800.0569 s with no 99-row coverage or child end | Failed/incomplete; no corpus median or no-worse claim |
| Placement explore | 99 configurations × four successful seeds; raw RC1 from ending-marker validator, independently qualified | Qualified placement coverage, not routing |
| Placement reference boards, both modes | Two measured rows in each mode; historical comparisons new/new | Measurement coverage complete, historical comparability absent |
| Placement reference modules, both modes | 29 measured rows in each mode after narrow outline-free turn fix | Measurement coverage complete, historical comparability absent |
| Candidate speed | Bounded measurements show regressions and incomplete coverage | Speed gate not passed; D3 pending |
| Actual generated free core, both modes | One measured row each; 46/56 unplaced | Measurements qualified; complete placement failed |

The complete raw tables and verdicts remain in task-owned receipts; links below are part of this ledger. Fixture identities are kept in those fixture receipts rather than source documentation.

## Board placement measurements

| Receipt row | Clique seconds | MST seconds | Placed clique/MST | Airwire mm clique/MST | Critical checks clique/MST | Crossings clique/MST |
| --- | ---: | ---: | --- | --- | --- | --- |
| 1 | 53.886 | 939.760 | 63/63 | 1497.032/1595.766 | 0/1 | {"plain+plain": 50} / {"plain+plain": 70} |
| 2 | 49.166 | 721.786 | 122/122 | 562.096/554.629 | 5/4 | {"plain+plain": 111, "plane": 121} / {"plain+plain": 106, "plane": 118} |

Full common Measures and input/source scope: [reference-boards-paired-f4e-measurements.json](/home/ben/work/placemat-review-scratch-20261007/step2/reference-boards-paired-f4e-measurements.json). Both baselines are new; no historical no-worse or routed-closure certification.

## Module placement measurements

27 of 29 complete common Measures records are identical across modes. The two changed records are shown by their order in the complete paired receipt. All 29 rows, run scores, placed counts, crossings, airwire, area and score prices remain in [reference-modules-paired-f485-measures.json](/home/ben/work/placemat-review-scratch-20261007/step2/reference-modules-paired-f485-measures.json).

| Paired receipt row | Clique seconds | MST seconds | Airwire mm clique/MST | Crossings clique/MST |
| --- | ---: | ---: | --- | --- |
| 20 | 5.318 | 5.276 | 133.014/132.248 | {"plain+plain": 7} / {"plain+plain": 6} |
| 21 | 1.843 | 1.687 | 5.842/6.326 | {} / {} |

The earlier module clique gate measured only 14 of 29 rows and failed 15 on outline-free turn evaluation. Its failure is historical evidence, not successful coverage. The accepted narrow four-file correction at own commit `04d5fc2a33ba9c2d3a76b60cf80d02261e4e912e` preserves congestion and a fixed comparison domain; 32 turn controls passed independently and in combined. Corrected clique and planned MST gates completed 29 rows each, with new historical baselines.

## Generated free-core measurements

Placed counts are part/cell declaration items from `bench_board`; unplaced counts are footprint members from `plan_measures`. These are different units: they cannot be added into a total or used to calculate a completion percentage.

| Mode | Resolve seconds | Placed declarations | Unplaced footprints | Airwire mm | Plain crossings | Plain/pair crossings | Weighted giveway | Rudy steps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clique | 29.629 | 24 | 46 | 2284.185 | 981 | 65 | 3.0 | 6 |
| mst | 247.825 | 23 | 56 | 2553.475 | 966 | 22 | 0 | 4 |

[free-core-paired-f485-qualified-measures-v4.json](/home/ben/work/placemat-review-scratch-20261007/step2/free-core-paired-f485-qualified-measures-v4.json) retains every common Measure and raw row. Both supervisors returned RC1 while the actual bench calls returned RC0. The live validator incorrectly rejected concrete `FindingKind` enum keys; clique also exposed weighted giveway 3.0 being treated as an integer count. Reviewed v4 pure controls pass 51/51. Posthoc qualification retains the raw failures and independently verifies unchanged runtime/cache/artifact hashes. It qualifies measurement completeness, never complete placement. No rerun was needed for these schema-only defects.

## D3, D4 and historical performance evidence

D3 is pending. Clique remains the recommendation given failed/incomplete MST corpus coverage, substantial board resolve regressions and incomplete core placements. Core elapsed times compare different resulting placements and cannot establish adoption. Earlier 600-second candidate timing batches were incomplete; direct prepared parity and one proved production native candidate do not establish throughput. No new optimization is authorized by this ledger.

D4 is pending. The meaningful fitted reference sweep measured five genuine fitted intents at 0.1, 0.25 and 1.0 (15 runs, 125.648 s, historical combined 60050/dev217/native6aa). Each intent was nonresponsive across those weights; this does not establish a best price. A synthetic responsive tradeoff is limited mechanism evidence. The direct-glob 18-fragment proposal was ineligible because it had no fitted intent; 99 definition rows were never a measured sweep. Area 0.25 remains provisional.

## Remaining gates and decisions

See [remaining-gates.md](remaining-gates.md) for commands, finite bounds and dependencies. Task 16 removal is pending the D3 decision and prescribed both-mode evidence; do not remove the comparison setting prematurely. Task 17 retains its stated after-Step-1-merge/rebase order. A fully gated integrated atomic merge would amend that order and requires an explicit ruling; combined review evidence is not official completion.
