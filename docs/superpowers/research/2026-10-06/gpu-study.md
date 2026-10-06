# GPU or CPU for placemat on two AMD BC-250 boards

Research only: no code changed, nothing committed. Placemat at d8ba8f8a (0.99.31), KRT at c98d38eb.
Measurements are on this machine (i5-1135G7, 4 cores / 8 threads, load 2.8-4.3), `nice -n 10`, one process at a time.
Scripts: `scratchpad/gpu/measure.py`, `scratchpad/gpu/variant.py`; profile `scratchpad/gpu/fixture.prof`.

## Short answer

1. **GPU compute would not bring a large gain to placemat as it is built today.** The only GPU-shaped kernel in the hot
   path is the native candidate sweep, and it is about 11% of a resolve (measured below). What dominates is sequential
   Python: settling, give-way, copper planning, arrangement bookkeeping, and the router's per-pass file and KiCad
   overhead. On top of that, ROCm does not support the BC-250's GPU (gfx1013); Vulkan through RADV is the only working
   compute path. Placemat's native code must also match its Python reference bit for bit in f64, and RDNA-class GPUs run
   f64 at 1/16 of f32.
2. **The algorithms that "become affordable on a GPU" are not limited by compute at placemat's size.** With 250
   footprints and 40 items, an ePlace/DREAMPlace-style global placement, a RUDY map, or a crossing count each takes
   milliseconds on one CPU core once it is native. They are worth having as CPU algorithms, but none of them needs a GPU.
3. **Plain CPU parallelism on the boards is the useful route.** Explore variants and quick routes are independent,
   deterministic jobs that take minutes each. Two boards add 12 Zen 2 cores (16 if the locked cores unlock), which is
   room for about 10 more variant or route workers. Today the core board's explore runs at `--jobs 2` on this laptop.
   Two CPU changes give more than any GPU port: explore pruning (R2 in the perf report) and native give-way (R3). Both
   attack the 250-450 s that one core variant takes now.

## The BC-250

| | | source |
|---|---|---|
| CPU | 6 Zen 2 cores / 12 threads enabled (8 on the die, 2 fused off, sometimes unlockable), about 3.5 GHz. The FPU has a halved 256-bit datapath compared with desktop Zen 2. AVX2 is present. | [elektricm docs](https://elektricm.github.io/amd-bc250-docs/getting-started/introduction/), [Tom's Hardware](https://www.tomshardware.com/pc-components/cpus/benchmarking-amds-bc-250-offering-steam-machine-like-performance-at-half-the-price-unlocking-40-cus-eight-zen-2-cores-on-the-repurposed-ps5-apu) |
| CPU speed | One public Geekbench 6 run gives 1214 single-core and 3678 multi-core. In Geekbench 3, Stream Copy measured 13.6 GB/s on one core and 25.5 GB/s on all cores. | [GB6 result](https://browser.geekbench.com/v6/cpu/19268394), [GB3 result](https://browser.geekbench.com/v3/cpu/9123710) |
| GPU | "Cyan Skillfish", gfx1013 ("RDNA 1.5"). 24 CUs stock, 40 on the die (some boards unlock 36-40). The only working clock control caps the core at 1500 MHz. | [akandr/bc250](https://github.com/akandr/bc250), [elektricm docs](https://elektricm.github.io/amd-bc250-docs/) |
| Memory | 16 GB GDDR6 shared by CPU and GPU, 256-bit at 14 Gbps. The GTT cap defaults to about 7.4 GiB and needs `ttm.pages_limit` raised to reach the full pool. | [akandr/bc250](https://github.com/akandr/bc250), [GB search summary](https://browser.geekbench.com/v3/cpu/9123710) |
| GPU compute stack | ROCm userspace ships no gfx1013 libraries, so it is "effectively unusable". `HSA_OVERRIDE_GFX_VERSION=10.3.0` is advised against: it is a different ISA, which risks silent errors. One repo reports ROCm working after kernel patches. Vulkan (RADV, Mesa 25.1.5+ recommended) is the working path. OpenCL (rusticl) is reported not usable. | [akandr/bc250](https://github.com/akandr/bc250), [TechMakesArt llama.cpp-bc250](https://github.com/TechMakesArt/llama.cpp-bc250), [elektricm env](https://elektricm.github.io/amd-bc250-docs/drivers/environment/) |
| f64 | Consumer RDNA 2 runs FP64 at 1/16 of FP32. I did not find a figure for gfx1013 itself and assume it is the same. | [geeks3d table / RX 6000 figures](https://www.geeks3d.com/20140305/amd-radeon-and-nvidia-geforce-fp32-fp64-gflops-table-computing/) |
| I/O, power | 1 GbE, one M.2 slot. 220 W TDP, 50-80 W at idle untuned, about 100-116 W under a GPU inference load. | [elektricm docs](https://elektricm.github.io/amd-bc250-docs/getting-started/introduction/), [akandr/bc250](https://github.com/akandr/bc250) |

Rough peak figures, my arithmetic from the above:
- GPU: 24 CU x 64 lanes x 2 x 1.5 GHz = 4.6 TFLOPS f32, and about 0.29 TFLOPS f64.
- CPU: 6 cores x 3.5 GHz x 8 f64 flops per cycle with the halved FPU = about 0.17 TFLOPS f64.

For f64 work the GPU is therefore under 2x the board's own CPU at peak. Placemat's kernels are branch- and memory-bound
anyway, not flop-bound.

## Where the time goes

### Measured here, whole-board fixture (fixtures/fairing/core: 258 footprints, 30 steps, `bench.bench_board` setup)

| operation | time | detail |
|---|---|---|
| whole resolve, plain | 3.59 s wall, 3.59 s CPU | single-threaded |
| all scans (`layout -> placer.scan`) | 1.21 s of 3.59 (34%) | 47 scans |
| native candidate sweep (`NativeSweeper._sweep`) | **0.41 s (11%)** | 245 calls, 212,250 candidates, **1.9 us a candidate** including the PyO3 hand-over |
| native refusals decoded to Python | 0.02 s | 4,269 calls |
| give-way resolves | 0.34 s | 26 calls (this fixture carries few vias) |
| settle (`_recorded_settle`/`_settle`) | 3.27 s profiled of 6.8 s profiled resolve | sequential 1-D slides and bisections |
| next item to place (`_next_to_place`) | 1.0 s profiled | re-measures every pending item each step |
| explore variants, seeds 1-3 | 3.75, 3.61, 3.43 s | same cost as plain on this fixture: few carried vias, so no give-way blow-up |
| run score of a plan (`explore.measure`) | **86-88 ms** | 89% in pure-Python `ratsnest.crossings` (5.6 of 6.3 s over 70 calls; 1,046 crossings) |

### Core board, from the earlier reports and records

| operation | time | source |
|---|---|---|
| preview, warm, no change | 5.8 s | latency/report.md |
| preview, late change (18 of 65 steps replanned) | 10.5 s | latency/report.md |
| preview, early change (32 of 65 steps replanned) | 42.6 s | latency/report.md |
| of a late-change preview (profiled 22.8 s) | place_ranked 9.6 s: settle 5.3, `placer.scan` 4.6; arrangement/face scans 4.1; copper planning 2.9; native board setup 2.5; PNG subprocess 3.15 | latency/report.md |
| one explore variant | 170-390 s CPU (perf report). **Live today (0.99.30, another session's `--explore 1200 --jobs 2`): variants finished at 457, 836, 1107 and 1359 s, about 250-450 s each, and all four scored worse than the plain placement (9043 against 10565-16326).** | perf-report.md; `scratchpad/exp/clean/.../runs/eec33ba8/progress.jsonl` |
| inside a variant | 257 of 266 s in `_scan_arrangements -> scan -> gave_way`: 13,253 Python give-way resolves at about 17 ms each | perf-report.md |
| pin study | 0.03-0.4 s a part (native). A long search improves the best by 0.4% (1252.5 -> 1247.2) | scratchpad/pinmap-bench-run3.txt |
| checks in `run` | 36-54 s, of which `current_paths` BFS is about 31 s | perf-report.md; run records |
| quick route | **289 s** (explore seed 0 today, closure 0.91) and 247 s (its route.json). A full route takes 395-700 s over 24 core runs. | eec33ba8/progress.jsonl; core `.placemat/runs/*/route/route.json` |
| inside a full route (run f1bbb59e) | KRT's A* totals **23.9 s** of 395 s (9.4 M iterations). Each of 6 island passes routes for under 1 s but takes 17-27 s of process time: KiCad load, refill, write and DRC. Every net costs at least about 0.12 s even at 5 iterations. Three rescue passes took 73, 28 and 22 s. | router_summary.json, islands*_summary.json, router.log, file mtimes |

My pin-bench run queued behind another session's real-board lock. I stopped it (my own PIDs) and used the 10-05
results.

## Classification of each operation

| operation | code | shape of the work | GPU fit |
|---|---|---|---|
| candidate sweep (edge, reservations, obstacle grid, score) | `native/src/lib.rs:1084`, loop at `:1167`; `shapes.rs:664` `first_conflict_shifted_in`; scoring `lib.rs:858` | Many independent candidates, the same steps per candidate. It is order-dependent in three places: the first legal index (`stop_at_first`), refusal tallies keyed by first index, and a pruning floor that each candidate lowers (`lib.rs:887-888`). Per candidate it does polygon and clearance tests against a spatial grid, with variable-length loops. | **Data-parallel but branchy.** Could run on a GPU with an ordered merge afterwards. It is 11% of a resolve, so a GPU caps the gain at about 1.12x. |
| candidate score: wire, ratsnest leaf crossings, escapes | `lib.rs:858-899`, `ratsnest.rs:331` `leaf_costs` | per candidate: a small sum plus grid-bucket segment tests | data-parallel, but already inside the sweep's 1.9 us |
| Python around the sweep: lattice passes, refine seeds, `accept`, riders | `placer.py:236-660` | sequential passes, each depending on the last pass's best | poor |
| give-way | `placer.py:334-376` (`bounded` false whenever `pick` is set); `giveway.py:978` `_give`, `:1095` `resolve`; native `first_move` `giveway.rs:184` | per candidate a search over via moves, shares and drops with recursion and Python objects | **poor**: branchy and pointer-chasing |
| settle (slides, locked, along line) | `layout.py:10524`, `:9812`, `:9585`, `:9418` | 1-D bisection and slides, each step depending on the last | poor |
| arrangements and faces | `layout.py:10843`, `:11124` | k arrangements x 2 faces of the scan above, the floor carried between them | parallel across arrangements is possible on the CPU; the floor makes it order-dependent |
| next item ranking | `layout.py:9890` | small per-item sums | trivial on the CPU |
| copper planning | `layout.py:9219`; `occupancy.py:1014` `copper_conflicts` (linear scan); `kicad_collide.py` | Python geometry with no spatial index | poor; a CPU index and native code fix it (perf R8) |
| run score: crossings, airwire, RUDY | `score.py:111`; `ratsnest.py:161` `crossings` (pure Python) | grid-binned all-pairs segment tests | data-parallel. A Rust port (the kernel `ratsnest.rs:79` `cross_nm` exists) brings it to milliseconds on one core. |
| explore variant | `explore.py:233` (multiprocessing workers, `:654` `_work`); draw `explore.py:68` | a whole sequential resolve per seed; seeds are independent | **ideal for a CPU worker pool**, useless on a GPU |
| pin study | `pinmap.rs:1122` `search`, `:1064` `anneal`; streams `pinmap.rs:120` | annealing per (pose combination, seed), independent SplitMix64 streams, incremental deltas in BTreeMaps | parallel across combinations on the CPU (rayon); poor on a GPU. Already 0.03-0.4 s. |
| current-path check | `checks.py:1139` `width` (binary search over BFS levels), `:1108`; `fill.rs:301` `reach` | about 9.7 grid BFS per width | a frontier BFS can run on a GPU, but one widest-path (bottleneck) search replaces the binary search on the CPU (perf R4) |
| router A* | KRT `rust_router/src/router.rs:410` (`BinaryHeap` open set), `:596` `step` | priority-queue A* with rip-up, per net in order | **poor**. GPU maze routing (GAMER) reaches 16x only in coarse global routing on large grids, with a different algorithm. Here A* is 6% of the route anyway. |
| router overhead | KRT `py_router/*`, KiCad load, refill and DRC per pass | process and file I/O | none |

## Question 2: algorithms that cost too much today

- **Population or annealing placement over thousands of candidates.** The limit is not compute but the placement model.
  - Legality in placemat is the whole rule set: clearance rules, keep-ins, reservations, net-tie exclusions, riders,
    give-way, pockets, arrangements, lanes and escapes. Porting all of it to a GPU means a second copy that must match the
    Python reference, which `lib.rs:1-4` makes the source of truth.
  - A cheaper model (body boxes, HPWL, crossings, RUDY) can score a full placement in about 1 ms on one core once
    crossings are native. That is roughly 6,000 per second on one BC-250's CPU, my estimate. That is enough to pre-screen
    thousands of permutations before each full resolve.
  - What explore needs first is a better search, not more compute: today's live run drew four variants in 23 minutes and
    all were worse than the plain placement.
- **ePlace/DREAMPlace global placement.** DREAMPlace's 35-43x GPU speedups are on designs of a million cells and more;
  one million cells takes about a minute ([DAC 2019 paper](https://yibolin.com/publications/papers/PLACE_DAC2019_Lin.pdf)).
  At 40-250 objects, an electrostatic density term with Nesterov steps is milliseconds per iteration in numpy or Rust.
  Placemat already has a quadratic pre-solve, off by default (`solve.py:24` CG in pure Python; `settings.py:479`
  `solve_enabled`). Adding density there is an algorithm choice to make on the CPU.
- **Batched ratsnest and crossing evaluation.** It is already batched natively per candidate (`lib.rs:858`). The
  remaining cost is the plan-level score at 86 ms in Python. Port it to Rust.
- **Congestion maps and rip-up estimates.** RUDY on a 0.5 mm grid for a 60 mm board is about 10^4 cells, which is
  trivial on the CPU. A quick-route proxy that predicts closure would be worth more than any speed-up, because closure is
  the objective. That is modelling work, not GPU work.
- **Batched DRC and clearance.** KiCad DRC is an external 5 s. The 31 s current-path check is an algorithm problem (R4).
- **Pin study.** It is fast and near its optimum: 25x more search gives 0.4%. More compute adds little here.

## Question 3: CPU parallelism against GPU

| | expected gain to the user's loop | effort | risk |
|---|---|---|---|
| more variants at once (boards as workers) | Explore throughput rises in proportion to workers. Now: 1 search worker plus 1 route worker. With 2 boards: about +10 workers (6 cores each; a worker held about 1.1 GB RSS here, and 16 GB is shared with the GPU). A Zen 2 core at 3.5 GHz on GDDR6 is probably no faster per thread than this laptop's; measure it with `fixtures/bench.py` on the board. | M | low |
| more routes at once | A quick route is 250-290 s, and closure is the objective. Routing the top N variants together cuts wall time by N. | M | low |
| rayon in the native sweep | at most about 10% of a resolve (Amdahl with the sweep at 11%) | S-M | Needs an ordered merge to keep `stop_at_first`, the first-index tallies and the pruning floor identical. |
| GPU sweep (Vulkan compute) | at most about 11% of a resolve; less after transfer and launch costs per scan (245 sweeps of about 870 candidates each) | L | **high**: f64 parity with the Python reference (`exact::clean9`, `PySum` compensated sums `exact.rs:140,149`, Python's `hypot`, no FMA contraction); a compiled shader per kernel; RADV only |

## Ranking

Expected speed-up times weight in the try-a-change loop, with effort and risk.

| rank | what | gain | weight in the loop | effort | risk | determinism |
|---|---|---|---|---|---|---|
| 1 | **Prune give-way in explore draws** (perf R2): pass `best*(1+slack)` as the bound when `pick` is set (`placer.py:334`, `layout.py` `_scan_one` `prune=`) | estimate 3-5x per core variant, 250-450 s toward 40-100 s; not measured | high: explore is the user's permutation search | M | Must not prune what `draw` could take (`explore.py:68`). The slack band is exact, so it is safe if done to it. | unchanged: seed-driven |
| 2 | **Remote worker pool on the BC-250s** for explore variants, quick routes and parallel what-ifs (e.g. the MCU's 4 turns x 2 faces x arrangements resolved at once) | Throughput: roughly 5-6x more workers than today's 2, about 12x with this laptop too. A what-if batch of 8 finishes in the time of one. | high: "try a change and see" becomes "try 8 and see" | M: explore already runs workers over `make_board` (`explore.py:294`, `:654`); needs transport, a job queue and an identical container (Python, glibc, KiCad, placemat wheel, KRT) on each board | Low. Verify that one seed gives byte-identical placements on the laptop and on a board before trusting remote results: libm can differ across glibc builds and CPUs. | Same seed gives the same variant only with the same stack; pin the image |
| 3 | **Native give-way** (perf R3) | estimate 3-5x on the 230 s that give-way takes in a variant; stacks with 1 | high | L | medium: a large port | parity tests, as for the other native code |
| 4 | **Native run score** (`ratsnest.crossings` to Rust) | 86 ms to a few ms (estimate) per plan | low today, needed for any population pre-screen | S | low | integer nm crossing tests already exist in Rust |
| 5 | **Incremental what-if estimate**: score one item's alternatives with the others held, from the native scorer that already exists, before paying for a full resolve | milliseconds against 10-43 s; a pre-screen only, since dependents replan | medium | S-M | It is an estimate; a full resolve still decides. | deterministic |
| 6 | Current-path widest-path search (perf R4) | `run` checks 37 s to about 10 s (estimate) | `run` only, not preview | M | low | deterministic |
| 7 | rayon in the sweep and the pin study | up to about 10% of a resolve; pin study already sub-second | low | S-M | ordered merge needed | keep it by merging in index order |
| 8 | GPU anything | 11% ceiling on resolves; nothing on give-way, settle, copper or the router | low | L | high (stack, f64 parity) | needs ordered reductions; FMA must be off |

## What would not benefit from a GPU

- settle, slides and locked settles
- give-way
- arrangement and face bookkeeping
- the riders' and look-ahead `accept`
- copper planning and `kicad_collide`
- explore's draw
- the pin study
- `_next_to_place`
- script execution, read and write of KiCad files, PNG and render
- every part of KRT: A* is 6% of a route, and the rest is per-pass process and KiCad time

## Two ways to use the boards

- **Remote worker pool (recommended).** Explore variants, quick routes, and batches of what-if resolves farmed out over
  1 GbE. A job is a script plus a seed plus a lock, with a few MB of board files; a result is placements and measures as
  JSON. Each board runs about 5-6 workers within its 16 GB with the GPU's carve-out kept small. It scales with no
  algorithm change and keeps determinism if the software image is pinned. The cost is running two 220 W boards (50-80 W
  each at idle).
- **Local GPU acceleration (not recommended now).** ROCm is unsupported on gfx1013, so it would be Vulkan compute shaders
  through RADV. The only fitting kernel is the candidate sweep, at 11% of a resolve. It would duplicate the f64-exact
  geometry in shader code. Revisit only if placemat adopts a population search with a simplified model, and only after
  rows 1-5 above, which give more on the CPU.

## Not measured

- The BC-250's own per-thread speed on placemat.
- The pruning ratio of R2.
- Cross-machine bit-identity of a variant.
- GPU kernel timings: no BC-250 or ROCm/Vulkan compute device here.
- All gains marked "estimate" are unimplemented.
