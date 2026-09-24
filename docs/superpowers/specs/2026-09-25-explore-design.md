# Exploring a layout: a time-boxed search the placer drives itself

Date: 2026-09-25
Status: design

placemat places greedily: items go down in rank order, each taking the best
legal spot the scorer finds. A good board then depends on the agent changing
declarations one run at a time. The freedom those declarations leave is
already known to the placer - every searched item has a place to find - so
the placer can vary its own choices, try many variants in parallel and keep
the best, with no alternatives listed by anyone.

## The commands

```
placemat run <script> --explore SECONDS [--focus ITEM ...] [--focus-after LINE]
                      [--focus-box X0,Y0,X1,Y1] [--jobs N] [--accept]
placemat preview <script> --explore SECONDS [the same focus flags]
placemat lock <script> --release ITEM ... | --release-all
placemat freeze <script> ITEM ... | --all [--fixed]
```

`--explore` spends up to SECONDS of wall time trying variants and reports
which focused items the best one would move and by how much. With
`--accept` it writes those decisions to the board's lock file and the run
carries on (write, DRC, render) with them; without it nothing persistent
changes and the run is the plain one. Seeds are the search's own business:
none is recorded or replayed.

## The lock file

`<Board>_layout.lock.json`, beside the script and committed with it: the
resolved decisions, as `uv.lock` is to `pyproject.toml`. One entry per
locked item:

- `anchor`: the placed pad the item depends on - the target its strongest
  link or pulling net draws it to (refdes and pad number);
- `offset` and `rotation` in the anchor part's own frame (so when the anchor
  part moves or turns, the item goes with it), and `face`;
- `declaration`: a digest of the item's declaration (its `place()`, its
  links, its footprint), so the entry knows when the script has changed
  under it;
- the score the accepted variant had, and the placemat release, for the
  record.

A run applies the lock at each locked item's turn in the order:

- the locked spot is legal: taken; the step says `held by lock`;
- it is not: the item is searched from the locked spot, as from a seed
  hint, and the step says how far it drifted and why;
- the declaration digest differs, or the anchor is gone: the entry is
  released and the item searched as usual; the run says so.

Given the script, the lock and the generated board, a run is deterministic.
Order swaps need no record: with each locked item's spot fixed, order no
longer decides it. An edit above an item moves its anchor and the item with
it, or shows as drift or a release; an edit below cannot reach it, because
later items go down after it.

## Freeze

`placemat freeze <script> ITEM` moves lock entries into the script: the
item's `place()` call gains `at=Near(PadRef(<anchor>).offset(dx, dy),
radius=0)` and `rotation=`, which keeps it in the same tier and turn of
the order and puts it exactly where the lock did (`--fixed` writes a FIXED
`Pin(...)` instead: a hard constraint, which goes down before everything
searched). Offsets are in board directions, as a person writes them; a
frozen line is the script's decision and no longer follows its anchor's
turn. The entry leaves the lock.

The edit changes that one call's arguments and nothing else in the file.
It is accepted only when the edited script parses and resolves to exactly
the placements the locked run had; otherwise the script is left as it was
and the command says what would have moved. A call that declares several
items (a helper, a loop) is refused with its line: that item's declaration
is moved out by hand. Each declaration records the script line of its
call, which is how freeze finds it.

How the call is edited is Ben's decision: LibCST (a format-preserving
syntax tree, an optional `placemat[freeze]` extra; about 62,000 lines and a
compiled parser, pulling in pyyaml; our code 40-60 lines) or the standard
library's `ast` positions with exact range splicing (no dependency; our
code 120-170 lines, owning the edge cases: byte columns, inserting into a
multi-line call in its own layout, trailing commas, comments inside the
argument list).

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
exactly (or, with a lock, the locked placement), and is always one of the
variants tried, so exploring never proposes a board the search scored
worse than the current one.

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

A line `explore  N variants in S s over J jobs: cost A -> B (placed P -> Q,
findings F -> G); K items would move`, then one line per item that would
move (`logic.c_vdd_1u: 1.20 mm, rotation 0 -> 90`). `metrics.explore`
holds the counts, the baseline and best scores and the focus as given.
With `--accept`: `lock  K entries written`, and the steps of the locked
placement are the run's.

## Not in this

No choice points in the script; no search over fixed positions, rows or
declarations; no routing inside the search; no automatic freeze. A second phase - lifting a
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

Explore: seed 0 is today's placement exactly (suite and bench unchanged); a
seed gives the same placement twice and in any process; a draw never takes
a candidate outside the slack; an unfocused item is placed exactly as seed
0 places it; each focus flag selects the items it says; steps before the
first focused item are replayed; the best is chosen by the lexicographic
score.

Lock: accepting writes one entry per moved item; a run with the lock
reproduces the accepted placements exactly; moving the anchor part moves a
locked item with it; a blocked spot drifts and says so; a changed
declaration releases its entry and says so; an edit to a later declaration
leaves a locked item where it was; `lock --release` drops entries.

Freeze: the edited call parses; the frozen script resolves to the locked
placements with the entry gone from the lock; comments, blank lines and
every other line are byte-identical; a call split over several lines, one
with a trailing comma, one with a comment in its argument list and one on
a line with non-ASCII text are each edited correctly; a helper or loop
call site is refused with its line; a freeze that would change any
placement leaves the script untouched and reports the difference.
