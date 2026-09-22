# A benchmark over the module fixtures, and a pocket for a seeded part with nowhere to go

Date: 2026-09-22
Status: design

Two pieces. The first is a benchmark that measures what a code change does to
placement across the module fixtures, against a committed baseline, so every
change that can move a part says how many modules it made better and how many
worse. The second is the first change measured with it: a seeded part whose
scan finds no legal spot takes the nearest free pocket instead of being left
off the board.

## What exists

- `fixtures/mnb/` and `fixtures/fairing/`: 34 modules, 32 with two or more
  footprints, each with its board (`modules/<name>/layout/layout.kicad_pcb`,
  or `kicad/` for one) and the libraries that build it. 17 carry a layout
  script, so their board is a hand placement.
- `fixtures/presolve_bench.py`: releases every part of a module to a bare
  `place()`, resolves, and scores by parts placed then half-perimeter
  wirelength (HPWL). Four modes, one of them a monkeypatched pocket fallback.
  It prints a table and keeps nothing, so a later change cannot be compared
  with it without re-running the old code.
- `_settle` (`layout.py:2640`): a searched part with placed connections is
  seeded on them (`_seed_hint`) and scanned once, within
  `max(radius, body width, body height)`. A scan that finds nothing leaves the
  part UNPLACED with a finding. `_settle_in_pocket` is reached only by a part
  with nothing placed to pull it.

Measured on the fixtures with the monkeypatched fallback (`seed` is placemat
today, `seed+pocket` adds the fallback, taking the biggest pocket first):

| | better than seed | worse | same |
|---|---|---|---|
| seed+pocket | 20 | 2 | 10 |
| solve | 16 | 11 | 5 |
| solve+pocket | 22 | 7 | 3 |

Today's placer places 20 of 51 parts on one module and 30 of 50 on another.

## The benchmark

`fixtures/bench.py` replaces `presolve_bench.py`.

**Corpus.** Every `fixtures/*/modules/*/{layout,kicad}/layout.kicad_pcb` with
two or more footprints. A module added under `fixtures/` joins the corpus with
no change to the script.

**Setup per module**, as `presolve_bench.py` does it today:

- every footprint is released to `place(Part(inst), rotation=<its rotation
  on the fixture board>)`, in sorted instance order;
- a module with a layout script runs on a board the size of its hand
  courtyard extent plus 10% a side; one without runs on a square board at a
  third fill;
- in a module of six or more parts, a net touching at least half of them is
  declared a plane on the back copper;
- `edge_margin=0.2`, `keep_going=True`.

**Configurations.** A named list in the script, each a set of `Settings`
overrides: `default` (no overrides) and `solve` (`solve_enabled=True`). A
setting under trial is measured by adding a row.

**What is recorded**, per module and configuration: parts, placed, findings
(`len(plan.findings)`), and HPWL over the nets that are not planes, to 0.1 mm.
Per module, once: the HPWL of the hand placement where there is one. Per
configuration: total seconds.

**Verdict** of a result against its baseline, in order: more parts placed is
better; then fewer findings; then HPWL more than 1% shorter. Anything else is
the same. The 1% is `AIRWIRE_NOISE`'s value; HPWL itself is deterministic.

**Baseline.** `fixtures/bench.json`, committed: sorted keys, one module per
line, no timestamps, so the same code writes the same bytes and a diff shows
exactly which modules moved. Seconds are stored per configuration only.

**Output** of a run (the numbers are illustrative):

```
fixtures/bench.py [name ...] [--config NAME] [--jobs N] [--update]

default  mnb/UsbC          placed 1 -> 5 of 5, findings 4 -> 0, hpwl 3.1 -> 24.0   better
default  fairing/Backlight placed 9 of 9, findings 0, hpwl 20.1 -> 56.9            worse
...
default: better 20, worse 2, same 10; placed +143; median hpwl ratio 1.04 over 12 equal-placed
solve:   better 18, worse 6, same 8;  placed +131; median hpwl ratio 0.92 over 14 equal-placed
seconds: default 41.2 (baseline 38.9), solve 63.0 (baseline 60.1)
```

Only rows whose numbers changed are printed. A module or configuration present
in one of run and baseline but not the other is listed as new or gone. With
`--update` the run is written to `bench.json`. Modules run in a process pool
(`--jobs`, default the CPU count) and are reported in sorted order.

**Exit status** is 0 whenever the run completes. A trade of three better for
one worse can be the right change, so the benchmark reports and the author
decides.

**The practice.** A change under `src/placemat/` that can move a placement
runs `fixtures/bench.py` before it is committed. The commit message carries
the tally lines, and if any number changed the same commit updates
`bench.json`. The README says so, beside `uv run pytest`.

The four modes of `presolve_bench.py` take 32 s over the corpus on one
process; two configurations in a pool should take well under that.

## The pocket fallback

In `_settle`, a part or cell seeded on its placed connections whose scan finds
no legal spot is tried in the free pockets before it is given up (the same two
kinds `_settle_in_pocket` already serves):

1. `pockets(occ, w, h, face)` for its envelope at each rotation the seeded scan
   tried (`i.rotations or (i.rotation,)`).
2. The pockets are ordered by distance from the seed hint to the pocket's box
   (0 when the hint is inside it), ties in `pockets()` order.
3. Each is scanned from its centre within half its longer side, with the same
   link score the seeded scan used, so the part lands at the end of the
   pocket nearest what it connects to.
4. The first pocket with a legal spot wins. The step's note reads:
   `no legal spot within R mm of the seed on NETS (REASONS); took the pocket
   W x H at (X, Y), D mm from the seed`.

When no pocket yields, the part is UNPLACED with the finding it has today,
followed by `; no pocket took it (N tried)`.

Placing the part is not a finding. The run counts these steps as `pocketed`
in `metrics`, and prints one line naming them, because a part far from its
connections is worth the author's look: its neighbours need room, or it needs
a `Near`.

**Unchanged:**

- A part with an explicit `Near` whose scan fails is still UNPLACED. The
  script said where it goes, and a pocket elsewhere would overrule it.
- A solve hint that fails still falls back to the seeded path, which now has
  this fallback after it.
- A part the seeded scan places lands exactly where it does today, so a board
  whose parts all place is unchanged byte for byte.

**Nearest pocket against biggest pocket.** The experiment took the biggest
pocket first. The implementation plan measures both on the benchmark and ships
the nearest-first order unless biggest-first beats it; the result goes in the
commit message.

## The solve's default

Once the fallback is in, the `solve` configuration is compared with `default`
on the benchmark. The result is recorded in `api.md` next to the
`[solve]` settings. Changing the default is a separate change, brought back
for a decision.

## Test plan

The benchmark's logic, pure (no KiCad):

1. the verdict orders placed, then findings, then HPWL outside 1%;
2. HPWL within 1% is the same;
3. the tally counts better, worse and same per configuration;
4. a row only in the run is new, a row only in the baseline is gone;
5. writing a baseline twice from the same results gives the same bytes;
6. HPWL of a hand-made set of pads sums each net's box and skips planes.

The fallback, over synthetic geometry:

7. a seeded part whose scan radius is full takes a pocket, legally, and the
   note names the pocket and its distance from the seed;
8. of two pockets, the one nearer the seed is taken even when it is smaller;
9. a part with a `Near` whose scan fails stays UNPLACED with today's finding;
10. with no pocket that fits, the part is UNPLACED and the finding says how
    many pockets were tried;
11. with the solve on, a failed solve hint then a failed seed scan ends in a
    pocket, and the note carries both;
12. `metrics["pocketed"]` counts the pocketed steps;
13. the existing suite passes unchanged: its boards place every seeded part.

Against the fixtures: the benchmark before the change is committed as the
baseline; after it, the tally is in the commit message.

## Documentation

- `migration.md`, `## To 0.21`: a part that was UNPLACED because its seeded
  scan failed now lands in the nearest pocket, and parts placed after it can
  move. A board that placed every part is unchanged.
- `SKILL.md`: a step noting "took the pocket" means the part's connections have
  no room beside them - make room, or give the part a `Near`.
- `api.md`: the `pocketed` metric; the solve comparison next to `[solve]`.
- README: running the benchmark and the commit practice.
