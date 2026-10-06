# placemat performance scan, 2026-10-05

Research only: no product code changed, nothing committed. All timings are on this machine (8 cores),
which other sessions shared throughout; the load average is given beside each figure. CPU seconds
(process_time) are quoted where the load was high, since placemat's resolve is single-threaded.
"main" is the shared checkout at c4e49f22 (v0.99.18); five merges landed at 21:13-21:14, after all
main measurements except the last three previews in "Core board".

Raw data, scripts and profiles: `scratchpad/perf/` (bench/*.json per tag with per-module seconds,
prof/*.prof, run1.log, run2.log, variant_noprof.json, arr_main2.json).

## Short answer to "faster but also slower"

Both are true, and only part of it is added complexity.

- Placement itself got faster. The whole-board fixture's placement went from 8.4 s (v0.81) to 3.9 s
  (main). The module corpus, minus one module, is about 10% faster than at v0.97.
- Three things got slower or never got the speed they should have:
  1. Explore variants on the core board take 170-390 CPU s each against 37 s for a plain resolve.
     That is the arrangement scan running give-way on every candidate when an explore draws, with
     no pruning.
  2. Run and preview reuse almost never replays on the core board. Every one of the board lead's
     recorded runs replayed 0 of 60 steps, because the context key changes from read to read
     (a bug, see R1).
  3. Checks grew by about 1.3-1.5x from two correctness changes to the current-path check.
     They now take 36 s of each 83 s core run, and they run one after another with render and DRC.
- On the bench, a single module (fairing/ringsensor) accounts for the whole jump in the bench
  total at v0.99.x. It went from 0.24 s to 8 s when unplaced parts started being scanned over the
  whole face (eda4516c).

## 1. Release history: the module bench

Each tag's own `bench_module` code on the same corpus (main's fixtures/*/modules, 33 modules),
2 workers. Seconds are summed per-module CPU.

| tag (date) | default | solve | physical | load (start -> end) |
|---|---|---|---|---|
| v0.36.0 (09-25) | 11.3 | 10.6 | 17.7 | 5.5 -> 5.0 |
| v0.58.0 (09-30) | 11.1 | 11.1 | 17.6 | 5.0 -> 4.9 |
| v0.81.0 (10-02) | 11.6 | 11.2 | 16.0 | 4.9 -> 4.7 |
| v0.91.0 (10-03) | 11.4 | 11.3 | 16.3 | 4.7 -> 4.3 |
| v0.97.0 (10-04) | 12.2 | 12.0 | 18.2 | 4.3 -> 4.3 |
| v0.99.5 (10-04) | 18.3 | 18.7 | 15.3 | 4.3 -> 4.3 |
| v0.99.12 (10-05) | 18.1 | 18.8 | 15.4 | 4.3 -> 4.2 |
| main, first run | 19.3 | 20.0 | 16.3 | 6.1 -> 5.5 |
| main, repeat | 17.7 | 19.1 | 15.3 | 4.2 -> 3.9 |

Per-module changes that matter (CPU s, default config; placed count after the slash):

| module | v0.91.0 | v0.97.0 | v0.99.5 | main |
|---|---|---|---|---|
| fairing/ringsensor | 0.26/5 | 0.24/5 | 8.01/6 | 8.07-8.49/6 |
| mnb/MCU_RP2350B | 0.46/29 | 0.99/29 | 0.83/29 | 0.87-0.91/29 |
| fairing/Backlight | 0.32/6 | 0.41/6 | 0.42/6 | 0.10/6 |
| fairing/Display | 0.41/7 | 0.48/7 | 0.49/7 | 0.20/7 |
| everything else | 9.95 | 10.08 | 9.04 | 9.0-9.6 |

For ringsensor in solve the times are 0.56 -> 9.1-9.7 s. Every other module moved by less than
0.15 s. The per-module seconds for all three configurations are in bench/<tag>.json.

The baselines committed in bench.json (`git log -p fixtures/bench.json`) show the same shape. They
fell from 242.8/574.0 s (09-23) to 9.8/14.5/10.0 s (10-03). They rose to 18.1/24.7/18.0 at 88b13348
and to 31.9/30.2/34.1 at eda4516c, then settled at 22.0/17.5/21.4 at 7a00374f (10-04). Those numbers
were taken with `--jobs` at the CPU count under unknown load, so only the steps between them mean
anything.

## 2. Regressions found

| # | where | commit (tag) | size | bisected how |
|---|---|---|---|---|
| G1 | fairing/ringsensor placement | eda4516c "a part no pocket takes is scanned over the whole face" (v0.99.2) | 0.6 -> 8.0 s default, 0.5 -> 9.0 s solve; it places the 6th part it used to leave unplaced | eda4516c~1 vs eda4516c, that module alone |
| G2 | current-path check | 99305f2d "current-path takes the plane over a sliver of another fill" (v0.99.5) | core board checks 28.0 -> 35.7 s (+28%); the commit message itself says 34 -> 63 s on the GND pair | 99305f2d~1 vs 99305f2d, same written core board |
| G3 | current-path check | b47b9eb8 "copper on parallel layers shares the current" (v0.99.7) | fixture checks 20.4 -> 26.3 s; core board 37.1 -> 40.6 s (within its +-3 s noise) | b47b9eb8~1 vs b47b9eb8, load 3.5-4.4 |
| G4 | mnb/MCU_RP2350B placement | between v0.91.0 and v0.93.0. 88b13348 (escape walled findings) is the likely step: 0.9 -> 1.3 s there, at load 5-6 | +0.4-0.8 s on one module | bisect noisy; left at that |
| B1 | run/preview reuse (a bug, not a slowdown in code) | cell clearance rules read in KiCad group-item order, which varies (kicad/read.py:823). Present since cells carry rules (e35ae1d4, 10-02) | every recorded core run replayed 0/60 steps; a preview that replays costs 8-9 s, one that does not costs 16-17 s | see below |

G1-G3 bought correctness or a placed part. They are not accidents, but each has a cheaper
implementation (R4, R6).

Checks across tags on the same inputs (load 3.0-3.6):

| tag | whole-board fixture placement s | fixture checks s | core board checks s |
|---|---|---|---|
| v0.81.0 | 8.44 | 14.8 | 27.9 |
| v0.91.0 | 8.84 | 14.8 | 27.8 |
| v0.97.0 | 7.20 | 15.6 | 27.9 |
| v0.99.5 | 3.79 | 19.9 | 41.2 (load 3.3) |
| v0.99.12 | 3.86 | 23.1 | 34.6 (load 6.3) |
| main | 3.86-4.04 | 22.2 | 36.4 |

B1 detail. A context check with no profiler shows that `board._rules` comes out in a different
order on the second and third read of the same generated board in one process. Across processes
the first read was the same four times out of four. The differing rules are a cell's fragment
rules ("the 0201 match inductor's own lands [logic]" against "the 0201 RF_50 shunt's own lands
[logic]"). `kicad/read.py` builds each cell's `rules` tuple in `g.GetItems()` order. The comment
two lines above says KiCad returns a group's items in no fixed order, and sorts the members for
that reason. The rules are not sorted.

`reuse.context_key` digests `board._rules` (reuse.py:117), so the key changes and the record is
refused with "the script's board-wide declarations changed".

Observed:
- all 30 recorded core runs from 10-05 replayed 0 of 60 or 61 steps;
- my two identical runs: the second said "board-wide declarations changed since run a4b1cb99";
- three identical CLI previews at 21:14 replayed 0 each, where two earlier ones replayed all 60.

`rules.stamped_rules` documents that the fragment's declared order matters, since the last
matching rule decides. So the same order problem may also change which rule KiCad applies. Not
verified.

## 3. Current workloads, main

### Core board (scratch copy of fairing-instrument-stagger/electronics/boards/core)

| workload | wall s | detail | load |
|---|---|---|---|
| preview, nothing replayed | 14.7, 15.0, 16.3, 17.1 | CPU 14.4-16.7 s | 2.6-4.2 |
| preview, all 60 steps replayed | 8.4, 9.4, 8.0 | | 3.3-3.8 |
| resolve only, fresh, in-process | 11.9 | | 4.2 |
| run, no route (`placemat run`) | 83.4, 83.6 | resolve 11.3/11.8, checks 36.5/35.9, render 24.5/24.7, DRC 5.4/5.3, write 4.0/4.1, generate 0.3; user CPU 202 s (render is multi-threaded) | 2.5-6.2 |
| pin map study | 0.02-0.07 s inside each resolve (cached digest); `fixtures/pinmap_bench.py` 0.040 s a part | | 14 |
| plain resolve, no lock, no replay (what an explore's baseline would be without a lock) | 37.3 (CPU 36.9) | | 8.2 |
| one explore variant (seed 1, 19 items in focus) | 177.5 (CPU 172.1) | | 8 -> 15 |
| one explore variant (seed 2) | 484.1 (CPU 388.5) | | rising to 15 |
| board lead's explores, 7 workers (run records) | 1229-1715 s for 14-25 variants, first variant done at 237 s | about 400 s of CPU per variant | not recorded |

Where a fresh core preview goes (cProfile, 26.7 s profiled, roughly 1.8x the real time):
- `place_ranked` 16.5 s:
  - `_settle` 12.2 s, of which `_settle_locked` 6.5, `_settle_along_line` / `_slide` 3.8;
  - the native sweeper's setup (`native_board` / `_raster`) 2.9;
- copper planning (`copper.route_leg` / `octilinear`) 3.7 s, through `occupancy.copper_conflicts`
  (2.9 s, a linear scan of every item's shapes, occupancy.py:994) and `kicad_collide` (1.8 s, pure
  Python nm geometry);
- the board-edge test `outline.why_not` 1.9 s over 146 k calls;
- `scripted_board` 2.7 s;
- `generator_inputs` 1.8 s (hashing every generator input on each preview, project.py:252);
- the PNG converter 1.5 s.

Where a fully replayed resolve in the studio worker goes (cProfile 11.3 s):
- `place_ranked` 4.2 s, which still plans copper (`plan` 3.9 s of `route_leg`);
- `_plan_copper` 2.4;
- `_report_escapes` 1.2;
- `suggestions.bind` 1.0 (re-applying script edits to check suggestions);
- `stale_record` / `generator_inputs` 0.95;
- `plan_json` 0.5.

Where an explore variant goes (cProfile, 266 s): 257 s in `_scan_arrangements` -> `_scan_faces` ->
`scan` -> `native_sweep` -> `gave_way` (placer.py:343). That is 13,253 calls to
`giveway.resolve` (giveway.py:1095) at about 17 ms each. Inside them:
- `_give` 190 s;
- `giveway_field.relay` 71 s;
- `_find_move` / native `first_move` 57 s / 25 s;
- `occupancy._conflict` 35 s over 3.5 M calls;
- `_shift` 20 s over 1.3 M calls.

In an explore draw the scorer is built with `prune=self._pick(j) is None` (layout.py, `_scan_one`).
`gave_way`'s bound needs `pick is None` too (`bounded = best is not None and pick is None and
accept is None`, placer.py:338). So with a pick, every candidate of every arrangement on both faces
pays a give-way resolve. The plain resolve of the same board with nothing locked takes 37 s.

Checks on the core board (cProfile 37.6 s; unprofiled 36.4 s, so nearly all native time):
`current_paths` 37.3 s. Of that, `NativeFill.reach` is 30.7 s over 894 calls. `_Fill.width`
(checks.py:1132) binary-searches the disc level and runs a full BFS (`_reach`) at each level, about
9.7 BFS per width over 92 widths. `_net_graph` takes 3.7 s and `polys_overlap` 3.3 s.

### Module arrangements (`fixtures/bench.py --arrangements`, load 5.5 -> 4.3)

| case | plain s | arrangements off s | on s | baseline on/off |
|---|---|---|---|---|
| module run, 1 layout vs k=4 | 2.5 | | 6.5 | 2.4 / 6.9 |
| stamped x4 | 1.13 | 1.25 | 2.75 | 1.40 / 3.01 |
| whole board | 4.97 | 4.33 | 5.25 | 7.18 / 6.98 |
| firm cells | 1.59 | 1.58 | 2.23 | 1.73 / 3.17 |

All are within the budgets in the bench docstring: a module at most about k times, a board at most
+25%, with the firm case at +41%. The arrangement cost that matters is the explore case above,
which this bench does not cover.

### Bench modules

In profiles of fairing/SlotControl and fairing/Mcu (physical), the native sweep is about 8% of
self time. Next to it, `NativeSweeper._decode` (occupancy.py:3151; 56,590 calls, 1.8 s of 10.8 s
cumulative on SlotControl) turns each native refusal back into Python. `_native_obstacle_index`
(occupancy.py:1471) is rebuilt 547 times, 0.8 s. ringsensor's 8 s: `_scan_whole_face`
(layout.py:8178) -> `NativeSweeper.run` (occupancy.py:3049). The sweep has net ties to recheck in
Python, so for each candidate the native pass accepts and Python refuses, it slices `triples[start:]`
and calls the native sweep again. That is 775 native calls (5.3 s) plus 1.8 s of self time spent
mostly copying the slice.

## 4. Studio and sockets

Measured on the core board by driving `studio_worker.Session` and `Studio._on_worker` in-process
(load 4.4):
- Per resolve the worker sends about 1.85 MB of JSON:
  - `done` 0.94 MB;
  - 46 `item` events, 0.75 MB;
  - 2 `board` events, 0.14 MB;
  - 30 `model_jobs` events;
  - 63-83 `begin` events.

  Encoding takes 0.06 s.
- The server spends 1.45-1.59 s (profiled) per finished resolve:
  - `with_spans` 1.06 s. `declaration_span` (studio_diff.py:150) runs `ast.parse` on a whole file
    once per item, 73 parses for 34 items, and the doc is `copy.deepcopy`-ed (0.39 s);
  - `json.loads` 0.17 s;
  - `dumps` for the emits 0.12 s.
- A page that connects gets `hello` + `state`, 1.10 MB. `_hello_data` re-parses every layout
  script's docstring for the list (`script_titles`, 39 scripts, 0.19 s).
- Polling: `studio_watch.Poller` stats the watched files every 200 ms (`studio_poll_ms`), a few dozen
  files: negligible. The page has no server polling, only local timers (studio_page.html:1162, 3680,
  3963). `/runs` caches by mtime. `/explores` re-reads up to 40 small JSON files per request (160 KB
  on this board).
- The full plan crosses the pipe once and goes out to the page in sections. That is reasonable at
  this size. The per-resolve server cost is mostly `with_spans`, not JSON.
- On a resolve where the generation did not change, the worker keeps the read geometry
  (`cache["generation"]`), so B1 does not hit studio re-resolves. It does hit the first studio
  resolve after a run and every CLI preview and run.

## 5. Old code in the hot path

By last commit: `kicad_collide.py` (10-01, one commit, 547 lines) is pure-Python nm-integer
geometry and is on the copper path (`_copper_gap`: 1.8 s in a fresh core preview profile, 107 k
`sq_distance` calls). `cleanup.py` (09-24), `congestion.py` (09-23) and `ranking.py` (09-22) did
not show in any profile. `occupancy.copper_conflicts` (occupancy.py:994) scans every item's shapes
with a box test per shape and has no spatial index (910 calls, 0.6 s self, 2.9 s cumulative in the
preview).

## 6. Opportunities, ranked

The estimates come from the profiles above. None is implemented or measured after a change.

| rank | what | label | effort | estimated gain | evidence |
|---|---|---|---|---|---|
| R1 | Read a cell's fragment rules in a fixed order. A stable sort is not enough, because the declared order decides which rule wins. The note needs its index, or the reader must sort on something the writer controls. | cache (a bug fix) | S | Core preview with no change: 16-17 s -> 8-9 s. Core run resolve: 11 s -> roughly 5-7 s (estimate from the preview replay). It also makes the previous run's record usable by the studio and by explores. | kicad/read.py:823; reuse.py:117; 30/30 board-lead runs replayed 0 steps |
| R2 | Explore draws: prune give-way the way `draw` already prunes. A candidate whose score before give-way, plus `least`, exceeds best*(1+slack) can never be drawn, since give-way only adds cost. Pass that bound into the scorer and `gave_way` when pick is set. | algorithm | M | A variant does 13 k give-way resolves at about 17 ms each, 230 of 266 s. Pruning to the slack band could bring a variant from 170-390 s toward the 37 s plain resolve, perhaps 3-5x. How many candidates fall outside the band is not measured. | placer.py:338-376; layout.py `_scan_one` (prune=...); explore.py:68 `draw` |
| R3 | Port `giveway.resolve` / `_give` / `giveway_field` to native. Today it is a Python loop around native `first_move` and `hit`. | native | L | 230 s of a 266 s variant profile, and a share of every scan near carried vias. Probably 3-5x on that part. Stacks with R2. | giveway.py:978, 1095; giveway_field.py:171, 518 |
| R4 | Current-path width: one widest-path (bottleneck) search per crossing instead of a binary search of BFS runs. Use a bucket-queue flood over `sq` levels, with each start or goal cell seeded at the largest level at which it touches the copper. | native + algorithm | M | 30.7 of 36 s of core checks are in `reach`; about 9.7 BFS per width. Estimate 36 -> 8-10 s a core run, about 25 s saved. Fixture checks about 22 -> 6-8 s. Recovers G2 and G3. | checks.py:1101, 1132; native fill.rs `reach` |
| R5 | Run stages concurrently. Start the kicad-cli renders (24.5 s, two sequential processes at `--quality high`) and DRC (5.4 s) as subprocesses right after the write, then run checks (36 s) while they work. | other (concurrency) | S-M | Core run 83 s -> about 55 s. The renders could also run in parallel with each other. | kicad/write.py:907-929; runner.py:551, 649, 674, 738 |
| R6 | Whole-face scan with net ties: ask the native pass for a batch of accepted candidates (stop_at_first off over a window) and judge them in order, instead of re-calling it from the next index with a sliced list. Or judge the ties natively. | algorithm | S | ringsensor 8.0 s -> under 1 s; bench default/solve totals -40% (about 18 -> 11 s). Any unplaced part on a real board pays the same. | occupancy.py:3049-3100; layout.py:8178 |
| R7 | Studio and preview fixed costs:<br>(a) cache `generator_inputs` file hashes by (path, mtime_ns, size), project.py:252;<br>(b) `with_spans`: parse each file once per resolve, no deepcopy, studio_diff.py:150-180;<br>(c) on a full replay, carry the planned copper ops in the reuse record instead of routing them again;<br>(d) cache `script_titles` by mtime. | cache | S each, (c) M | (a) 0.5-1 s per preview or studio resolve;<br>(b) 0.5-1 s server CPU per studio resolve;<br>(c) the 2.4 s `_plan_copper` plus about 3.7 s of `route_leg` in a replay profile, so a replayed core preview about 8 s -> about 4-5 s;<br>(d) 0.2 s per page connect | profiles in section 3 and 4 |
| R8 | Copper clearance: a grid index over placed shapes and copper in `copper_conflicts`, and `kicad_collide`'s segment and polygon distance in native. | native + algorithm | M | About 2.9 s of a profiled fresh core preview (1.5 s real), plus the 35 s of `_conflict` inside an explore variant's give-way | occupancy.py:994, 2302, 2650/2892; kicad_collide.py:128-498 |
| R9 | Native refusal tallies: return (bucket key, count, first index) aggregated per bucket from the sweep, and decode only the first of each into Python. | native | S-M | About 15% of a module's placement (1.8 of 10.8 s profiled on SlotControl) | occupancy.py:3151; placer.py:317 |
| R10 | Cache `_native_obstacle_index` per occupancy version instead of per scan | cache | S | About 0.8 of 10.8 s on SlotControl | occupancy.py:1471 |

Smaller notes:
- `outline.why_not` has 146 k calls (1.9 s profiled) in a preview. The native sweep already judges
  the edge, but `_edge_or_reservation_conflict` -> `_item_edge_why` re-judges it in Python for 738
  candidates.
- `stale_record` runs on every studio resolve even when nothing changed (R7a).

## 7. What I could not measure

- Older tags on the core board. The current Core_layout.py fails under v0.97.0, v0.99.5 and
  v0.99.12 ("Layout script failed") even with [pins] and route.net_halos taken out of
  placemat.toml. The board history comes from the board lead's own run records instead
  (10-04..10-05). Typical non-explore resolve times there were 7-8 s on 0.99.7 and 21-46 s on
  0.99.14-0.99.17, with the script changing between them, so per-feature cost and regression cannot
  be told apart.
- A full explore end to end through my harness. My first attempt spawned workers from a script
  without a `__main__` guard and hung; I killed it (my own PID). Explore cost is given from
  single in-process variants and the board lead's records.
- Route: KiCadRoutingTools, 396-659 s per core run in the records; external, not profiled.
- The studio page's own rendering cost in the browser.
- R2's real pruning ratio, and all gains in section 6, which are unimplemented estimates.
- Timings between 20:35 and 21:03 were taken at load 8-22: the variant timings, the first
  arrangement bench, and the first whole-board pass. Those benches were repeated at load 3-5 and
  the repeats are what is quoted. The variant timings were not repeated.
