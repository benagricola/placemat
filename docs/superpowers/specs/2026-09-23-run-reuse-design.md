# Reuse the previous run up to the first changed placement

Date: 2026-09-23
Status: design

An agent iterating on a board changes one or two declarations and runs
again, and every run resolves the whole board from the start. On the
220-part board a resolve is 106 s. A run that changes nothing before a given
step places everything up to that step exactly as the previous run did, so
those steps can be replayed instead of searched.

## Measured

The core board's 107 pairs of consecutive runs, compared by item and
placement step by step:

- 19 pairs placed everything identically (copper, label or document edits).
- The first differing placement is a median 7% of the way through the
  steps, but the early steps hold the time: on the current script the first
  10% of steps are 44% of the resolve, the large blocks among them.
- Weighted by the step times of a current run, a reuse up to the first
  changed step would have saved a median 39% of the resolve (mean 38%), more
  than half on 45 of the 107.

The step times come from a snapshot whose MCU block fails, which is slow;
the saving is an estimate, and the implementation measures it.

## What makes a step reusable

A step's result is decided by: the generated board, the tool version, the
resolved settings and the fab profile; every declaration that shapes the
occupancy before the searched tier or feeds every item's search (copper,
planes, free nets, keepouts, cutouts, labels, rules, the board's outline and
size); the steps before it; and its own item's declaration and the links on
that item's pads.

So each step gets a **key**: a hash chained from the previous step's key,
over the item placed and a canonical form of its declaration and of the
links on its pads. The first step's chain starts from a **context** hash
over everything global above. The order in which items go down is still
worked out live - it is cheap, and it depends on every pending item - and
the item it chooses is part of the key, so a changed order breaks the chain
at the step where it changes.

With `[solve] enabled`, the global solve reads every searched item, so the
context includes every placement declaration and every link: reuse then
holds only when nothing changed.

## Replay

A run records, per step: its key, the Step (placement, moved, note,
priority, rank), and what settling it did beyond the Step - findings
appended, nets it was seeded on, whether it took a pocket, and every
occupancy commit made inside it (a block commits its satellites there). The
record is `reuse.json` in the run directory.

The next run of the same board reads the latest run's record. While a
step's key matches the recorded key at the same position, the step is
replayed: its commits are re-applied, its findings, seed counts and pocket
flag restored, and its Step appended, instead of searching. Labels placed
after each item are worked out live as now, from the occupancy the replay
restored. At the first key that differs - or when the record runs out -
every later step is resolved as today.

The cleanup pass is replayed too when every searched step was replayed and
its inputs match; otherwise it runs.

A replayed run is byte-identical to a fresh run of the same inputs: same
steps, notes, findings, copper and written board.

## Saying what happened

The run prints `reused  N of M steps from <run id> (first change: <item>)`
and records `metrics.reused`. `placemat run --no-reuse` resolves from the
start. A run whose context differs says which part of the context changed:
`reused 0: the generated board changed`.

## What this does NOT do

It does not re-place only what a change touches and keep the rest: a
change early in the order still re-resolves everything after it, because in
a sequential placement everything after a change can move. A mode that keeps
unchanged parts where they were and re-places only the changed ones would
be faster on an early change but give a different board from a fresh run;
it is a separate decision.

## Test plan

1. A second run with nothing changed replays every step and writes the same
   board, byte for byte.
2. Changing one searched item's declaration replays every step before it
   and matches a fresh run exactly from there on.
3. Changing a link on an item's pads re-resolves from that item.
4. Changing a global declaration (a keepout, a plane, a setting, the fab
   profile, the generated board) replays nothing, and the run says which.
5. A changed placement order breaks the chain where it changes.
6. With the solve on, any placement change replays nothing.
7. A replayed block restores its satellites' commits.
8. `--no-reuse` resolves from the start.
9. On the fixture modules and the core board, for a sequence of single edits,
   the reusing run equals the fresh run and its time is reported.

## Documentation

- `api.md`: what reuse keeps, what breaks it, `--no-reuse`, `metrics.reused`.
- `SKILL.md`: iterate on late items cheaply; an early or global change
  re-runs the board.
- `migration.md`: nothing to change.
