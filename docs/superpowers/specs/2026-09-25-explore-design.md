# Exploring a layout: a time-boxed search the placer drives itself

Date: 2026-09-25
Status: design

placemat places greedily: items go down in rank order, each taking the best
legal spot the scorer finds. A good board then depends on the agent changing
declarations one run at a time. The freedom those declarations leave is
already known to the placer - every searched item has a place to find - so
the placer can vary its own choices, try many variants in parallel and keep
the best, with no alternatives listed by anyone.

## The command

```
placemat run <script> --explore SECONDS [--focus ITEM ...] [--focus-after LINE]
                      [--focus-box X0,Y0,X1,Y1] [--jobs N] [--seed N]
placemat preview <script> --explore SECONDS [the same focus flags]
```

`--explore` spends up to SECONDS of wall time trying variants, then carries
on as a run does (write, DRC, render) with the best one. `--seed N` replays
variant N exactly, with no search: the run record says which seed won, so a
result can always be reproduced.

## What varies

Only the focus varies; everything outside it is placed exactly as today.

- **Which spot.** A focused item takes one of its better legal spots rather
  than always the best: its scanned candidates, best first, are drawn from
  with a weight that falls with rank (the best is still the most likely),
  restricted to candidates whose score is within `[explore] slack` of the
  best (default 25 %). This is randomised greedy with restarts (GRASP, Feo
  and Resende, 1995).
- **The order.** Two focused items adjacent in the placement order swap
  with probability `[explore] swap` (default 0.2): the greedy order often
  decides which of two parts gets the good spot.
- **The rotation.** It comes with the spot: candidates at every rotation
  the item may take compete in the same draw.

Each variant is a seed; the draws for an item come from (seed, item key),
so a variant is the same whatever else ran. Seed 0 is today's placement
exactly, and is always one of the variants tried, so exploring never
returns a board the search scored worse than the plain run.

## The focus

A focused item is a searched item (a part, a cell or a block with freedom
left) named by any of:

- `--focus KEY`: an item's key (`logic.mcu`, a cell name, `block ldo`);
  repeatable. A cell or block focuses itself, not its members one by one.
- `--focus-after LINE`: every item declared at or after that line of the
  script - "the passives I placed at the end". Each declaration records the
  script line it came from.
- `--focus-box X0,Y0,X1,Y1`: every item whose plain-run placement lands in
  the box - "the corner round the MCU".

With no focus flag every searched item is in focus. Fixed and edge items,
rows and anything decided never vary.

## Scoring

A variant is judged as the benchmark judges a module: more items placed
first, then fewer findings, then a lower cost - the cleanup pass's cost
(half-perimeter wire of the nets that pull, plus each link's weight times
its length) plus `[explore] congestion` (default 0) times the worst RUDY
cell's utilisation. Nothing needs KiCad: DRC and the render run once, on
the winner.

## How it runs

- The script runs once per worker process; each worker resolves seeds
  until the deadline and reports (seed, score).
- A variant differs from the plain run only from its first focused item
  on, so each worker replays the steps before it (the run-reuse machinery,
  with the seed in the key of a focused step) and resolves only the rest.
  `--focus-after` near the end of a large board is therefore cheap.
- `--jobs` defaults to the machine's CPU count less one. The native module
  helps but is not required: the same budget tries fewer variants in pure
  Python.

## What the run says

A line `explore  N variants in S s over J jobs: best seed K, cost A -> B
(placed P -> Q, findings F -> G)`, and `metrics.explore` holds the seed,
the counts, the baseline and best scores, the focus as given and the ten
best variants. The steps of the winner are the run's steps, as always.

## Not in this

No choice points in the script; no search over fixed positions, rows or
declarations; no routing inside the search. A second phase - lifting a
focused cluster out of a finished board and re-placing it (large
neighbourhood search) - follows only if the measurements below say the
restarts leave improvement on the table.

## Measurement

`fixtures/bench.py --explore N` runs N fixed seeds per module (a count, not
a time, so the tally is reproducible) and reports the tally against the
baseline. The plan's acceptance: with 64 seeds the default config is better
on at least half the modules and worse on none (seed 0 guarantees none is
worse by the score). Time per variant is reported per module, native and
pure Python.

## Test plan

Seed 0 is today's placement exactly (the whole suite and bench unchanged);
a seed gives the same placement twice and in any process; a draw never
takes a candidate outside the slack; an unfocused item is placed exactly as
seed 0 places it; each focus flag selects the items it says; a variant's
steps before the first focused item are replayed, not resolved; the best of
several seeds is chosen by the lexicographic score; `--seed K` reproduces
the explored winner byte for byte.
