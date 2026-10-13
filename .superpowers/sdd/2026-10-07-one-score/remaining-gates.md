# Remaining Step 2 gates

Historical evidence from 2026-10-08, not the current release gate. Later user
decisions D25, D28 and D30 supersede the pending choices and recommendations
below. Preserve the source-scoped receipts; use
[the 0.100 qualification record](../../../docs/superpowers/0.100-qualification.md)
for current integration status.

Reviewed ledger, 2026-10-08. Current combined review is `c780`/genuine dev254 after reviewed Step 1 staging, with no final gate on that source. Historical measured results retain their original source identities. No physical jobs are queued or authorized by this file.

| Gate or decision | Command / action | Proposed finite bound | Dependency and required result |
| --- | --- | --- | --- |
| D3 search fallback | User chooses documented clique divergence or another course from actual gate results | Human decision | Pending; MST 99-row gate failed/incomplete, no implicit waiver |
| D4 area price | User chooses 0.25 provisionally, 0.1 or 1.0 from fitted sweep | Human decision | Pending; nonresponsive sweep proves no optimum |
| Final feature whole suite | `.venv/bin/python -m pytest --full -n 2 -p no:cacheprovider` | 3600 s | Genuine final feature source/native/settings freeze after cleanup; retain every skip/failure |
| Final combined whole suite | Same command in isolated combined runtime | 3600 s | Final reviewed Step 1 repairs and Step 2 cleanup integrated; not yet launched |
| Complete MST bench decision | `fixtures/bench.py --jobs 2 --set place_search_wire=mst --out <scratch>/gate-mst.json` | Prior 1800 s exhausted | No repeat or extension authorized; require user/root ruling on failed coverage, never treat partial records as full |
| Task 16 cleanup | Removal-ledger checks, docs/settings migration, `vulture` with reviewed allow list; `RUSTFLAGS="-D dead_code" cargo build -j 2` | Review before launch | D3 choice first; preserve clique fallback if chosen; native build needs genuine hash receipt |
| Task 16 regression | Whole suite and benchmark tally on cleanup source | Review before launch | Actual final removal/migration source; earlier results do not substitute |
| Official Task 17 closure | `fixtures/reference/place_ref.py --set place_search_wire=<mode> --results <scratch>/route-<mode>.json`, boards and `--modules`, both modes | Proposed 3600 s each | Step 1 main merge then rebase per original plan, or explicit sequence amendment; actual routing, original stable asks/width/critical evidence and comparability required |
| Task 17 decision on failure | Present actual comparable closure deltas to user | Human decision | Incomparable/missing evidence is not measured zero or a pass |
| Final premerge reference/update checks | `route_ref.py`, `place_ref.py`, `place_ref.py --modules` with reviewed update protocol | Review before launch | After final source/choices; preserve old baseline receipts until authorized update |
| Final merge and notice | Merge gated source and send release-owner commit/migration/gate receipt | After gates | No merge yet; goal authorizes merge once required gates/decisions are satisfied |

Incremental 113-case, qualified 396-seed placement, clique 99-row, both-mode board/module placement and both incomplete core measurements are recorded in gate.md. They remain frozen historical source-scoped evidence. Supplemental controlled and actual-small-router logical gates are useful safety proof; they do not substitute for the prescribed routed reference gate.

Source coupling is explicit: the Step 1 repair consumes Step 2 Standing/rank, original critical context, bounded worker and preservation. Its physical grader alone is insufficient. Any proposed combined-before-main sequencing remains an amendment, not silent Task 17 completion. No scoring retuning, broader neighborhood work or additional physical runs are implied.
