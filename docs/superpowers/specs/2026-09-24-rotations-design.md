# Rotations for searched parts

Date: 2026-09-24
Status: design

A searched part is scanned only at its `rotation` (0 unless the script says
otherwise) unless the script lists `rotations=`. The scorer already sums each
pad's distance to what it connects to, so it would turn a two-pad part to put
the right pad toward its pin, but it is never offered the turn. The cleanup
pass keeps every rotation. Source: fairing-instrument
`electronics/PLACEMAT_GAPS.md`, "passive orientation and the MCU's fanout",
items 1 and 5. On their core board, `rotations=(0, 90, 180, 270)` on every
searched part took ratsnest crossings from 1,318 to 1,124.

## Measured

A spike (four rotations for every searched part with none declared, nothing
else changed) on `fixtures/bench.py`, against the baseline:

| config   | better | worse | same | placed | median HPWL ratio | seconds    |
|----------|--------|-------|------|--------|-------------------|------------|
| default  | 27     | 1     | 4    | +14    | 0.87              | 80 -> 184  |
| physical | 27     | 3     | 2    | +15    | 0.83              | 88 -> 176  |
| solve    | 20     | 8     | 4    | +15    | 0.98              | 52 -> 90   |

More parts place because a part refused at 0 fits at 90. The cost is time:
about 2.2x on the corpus.

## Behaviour

**Which items.** A part searched from its links or round a `Near()` hint,
declared with neither `rotation=` nor `rotations=`, is scanned at 0, 90, 180
and 270. A part given `rotation=` keeps that rotation alone; `rotations=`
keeps the list given. Unchanged: a fixed part, a part on an edge, a rim or a
line (`Centre(x, None)`), whose rotation the edge or the line decides; a
cell, whose sides are declared (`faces`); a block, measured separately in
the plan and included only if the bench says so.

**The setting.** `[place] rotations = "all"` (default) or `"declared"`, which
is today's behaviour. It is a placement setting, so a change replays
nothing.

**The pocket fallback** uses the same rotations; today it tries the rotation
and the one 90 from it when none are declared.

**The cleanup pass** scans each moved part at the rotations its declaration
allows, so a turn in place, or a turn and a shift, is a move like any other,
taken only when it lowers the cost. A part given one rotation is only
shifted, as now.

**Time.** The scan is 4x the candidates for the affected parts: about
2.1x the resolve time on the corpus. Decided 2026-09-24: accepted for the
gain, in place of the 1.5x limit this spec first set.

## What does not change

The scorer, the swap in the cleanup pass, the reuse key's shape (the
setting and the declaration are already in it), the output format. The
crossing-swap and fanout-band items stay in the backlog.

## Test plan

Pure:
- a two-pad part seeded between two pins, with the pin its pad 1 must reach
  on its east: default settings turn it (180); `rotation=0` keeps 0;
  `rotations=(0,)` keeps 0; `"declared"` keeps 0;
- a part that fits a gap only at 90 places with the default and is refused
  with `"declared"`;
- an edge part, a line part and a cell keep their rotation;
- the cleanup pass turns a part whose flipped pads lower the cost, and does
  not turn one given `rotation=`;
- reuse: changing `[place] rotations` changes the context key.

Bench: the whole corpus with the tally in the commit; the core board copy
timed before and after.

## Documentation

`api.md` (`rotations=` and the default, `[place] rotations`), `SKILL.md`
(give `rotation=` when a part's turn matters), `migration.md` (placements
change: parts turn; `"declared"` or `rotation=` for the old behaviour).
