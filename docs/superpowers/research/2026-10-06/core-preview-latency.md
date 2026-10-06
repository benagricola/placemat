# Core_layout.py preview latency, placemat 0.99.29

Setup: copy of the core board plus a skeleton of the surrounding tree (adapted, modules, docs, mechanical.toml, .pcb; parts and datasheets symlinked), because the script reads ../../.. paths. .placemat/runs/*/ and snapshots/ left out. `nice -n 10`, `--jobs 2`, under flock. Wall time is the whole command (includes python start, ~1 s).
Board: 250 footprints in the generated board, 40 placed items/cells in the script, 65 placement steps.

| # | Run | Wall s | Steps reused / replanned | First change |
|---|-----|--------|------|------|
| 1 | cold | 16.7 | 0 / 65 ("tool version changed since run 3f67fdf0", a run absent from the copy) | - |
| 2 | warm, no change | 5.8 | 65 / 0 | - |
| 3 | late change: usbpd.moisture Near(LD1 -> LD2) | 10.5 | 47 / 18 | usbpd.moisture |
| 4 | early change: light Beside align START -> END | 42.6 (earlier cumulative run with both edits: 46.9) | 33 / 32 | light |
| - | revert of the early edit (after run 4) | 25.7 | 33 / 32 | light |
| - | baseline again after early edit | 12.2 | 33 / 32 | light |

The early change replans 32 of 65 steps; 'light' is the 34th of 65 steps. Timing is noisy (other load on the machine): the same 18-step late change took 10.5 s unprofiled and 23.7 s under cProfile.

## Timing output of the preview
No per-step timing lines. It prints: pins study time, lock summary, `script N placed`, `reused X of Y steps (first change: ...)`, congestion line. reuse.json in .placemat/views/preview holds per-step seconds only for some steps (total 0.39 s, not informative).

## Where the time goes
Late-change case, cProfile (main process, 22.8 s total, 23.7 s wall):
- layout.resolve -> _resolve_once: 17.2 s (75%)
  - place_ranked / place_one: 9.6 s (65 calls to place_one, 9.15 s; of this _recorded_settle/_settle 5.3 s, placer.scan 4.6 s)
  - _scan_arrangements / _scan_faces: 4.1 s
  - _plan_copper_batch: 2.9 s (copper.octilinear/route_leg 3.5 s overlapping, copper_conflicts 3.1 s)
  - occupancy native_board / _raster: 2.5 s
- PNG conversion subprocess (convert_failure -> subprocess wait): 3.15 s
- remainder: startup, import, pins, lock, svg

Top 15 by cumulative time (below the cli/main/exec wrappers):
1. previewer.preview 22.9
2. previewer._resolved / _resolve 17.6
3. layout.resolve / _resolve / _resolve_run / _resolve_once 17.2
4. layout.place_ranked 9.6
5. layout.place_one 9.15
6. layout._recorded_settle / _settle 5.3
7. placer.scan 4.6
8. layout._scan_arrangements / _scan_one 4.06
9. layout.plan (5789) 3.7
10. copper.octilinear / route_leg 3.5
11. layout._scan_faces 3.4
12. previewer.convert_failure (PNG subprocess) 3.15
13. occupancy.copper_conflicts 3.07
14. layout._plan_copper_batch 2.9
15. occupancy.native_sweeper 2.7 / native_board 2.5 / _raster 2.5

Raw profile and run logs deleted with the scratch copy.
