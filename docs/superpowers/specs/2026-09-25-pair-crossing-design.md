# A differential pair's own crossing, weighed at placement

Date: 2026-09-25
Status: proposal, from the user's direction (pairs uncrossed by placement first)

## The problem

When a pair's P and N sit on opposite sides at its two ends, the pair
cannot be routed coupled without exchanging sides: a loop, or (router
change, docs/pair-via-crossover-design.md in the router) a via crossover.
Most of the time the better fix is at placement:

- two interchangeable 2-pin parts on the pair (series resistors, AC
  coupling caps) trade places;
- a part whose pinout is mirrored about its middle (an ESD array with its
  ground pin in the middle of one side and the two protected lines either
  side of it on the other) turns 180 degrees: the protected pads are the
  right way round, slightly further away, which is almost always fine.

placemat already offers both moves: the search tries each part's declared
rotations, and cleanup offers each part a swap with every part identical to
it (`cleanup._swaps`). But a pair's P airwire crossing its own N airwire
counts as one ordinary crossing (`score.crossing`, 4 mm of wire), too cheap
to decide a swap or a turn against wire length, and nothing tells the
designer about a crossed pair when the parts are placed by the script.

## The change

- **Pairs**: nets pair as the router pairs them. `placemat/pairs.py` ports
  the router's `net_queries.extract_diff_pair_base` (KiCadRoutingTools, the
  same conventions: `_P`/`_N`, `P`/`N`, `+`/`-`, `DP`/`DM`, true/complement,
  KiCad's auto-names), cited, so the two never disagree about what a pair is.
- **Weight**: a crossing between the two nets of one pair counts
  `score.pair_crossing` (a setting, default 100, in millimetres of wire like
  every score term) instead of `score.crossing`. Everywhere crossings are
  counted: the run score (`score.py`), the ratsnest the search and cleanup
  ask (`ratsnest.crossings`, `Ratsnest`), and its native mirror.
- **Finding**: every pair crossing on the placed board is reported, naming
  the pair and the two parts whose airwires cross, with the fixes in the
  designer's terms: "USB crosses itself between R2 and R3: swap them, or turn
  the part with the mirrored pinout 180 degrees". Decided (script-placed)
  parts are reported the same way; placemat moves nothing that is decided.
- **Skill**: one line under crossings: a crossed pair is fixed by a swap or
  a turn before routing; the router's crossover is the fallback.

## Verification

- Unit: the pair rule on the router's own examples (the port's tests).
- Unit: two identical 0402s in series on a pair, placed crossed: the run
  score carries `score.pair_crossing`; cleanup swaps them and the crossing is
  gone.
- Unit: a 6-pin part with a mirrored pinout searched with rotations 0 and
  180, the pair crossed at 0: the search picks 180.
- Unit: a decided crossed pair: the finding names the pair and both parts.
- The bench (`fixtures/bench.py`): no placement worse; the tally in the
  commit with the baseline.

## Not in scope

Pin swaps inside a part (changing which pin is P), which change the
schematic.
