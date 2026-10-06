# One score for every placement decision

Status: draft for review, 2026-10-06; release line 0.100.x. A prerequisite for 2026-10-06-refine-pass-design.md and
2026-10-06-place-route-loop-design.md. Decided with the user: refine, and everything else, use one consistent scoring
mechanism.

## Problem

placemat judges placements with five different objectives (scratchpad/placement-inventory.md section 1):

| Who | Objective | Wire | Crossings |
|---|---|---|---|
| The search (`Scorer`, layout.py:829; native lib.rs:802) | one item against the placed board | weighted pad-to-pad clique over pulling nets | each pad's airwire to its net's nearest placed anchor (`leaf_costs`), an estimate |
| Cleanup (`PartScore`, cleanup.py:154) | one part | HPWL plus declared links | the same estimate |
| The run score (`score.py`) | the whole board, after a resolve | the ratsnest's length (KiCad's MST) | KiCad's ratsnest crossings, whole board, priced by kind |
| Explore | variants | the run score plus congestion (RUDY) | as the run score |
| The pin study (pinmap.rs) | the studied nets | 0.25 per mm | its own weights (pairs x5, impedance x3) |

So the search places each item to lower one number, and the run is then judged, and variants ranked, on another. An
item can be placed well by the search's measure and badly by the run's. The turn check and the pin study each add a
third view. Refine, if built on the search's `Scorer` as specified, would inherit the gap.

## The rule

There is one board objective, the run score, defined in one module (`score.py`). Every placement decision lowers it:
the search's choice of a spot, refine's moves, a turn check, a restart's ranking, and the pin study's choice of map
and pose. A decision about one item uses that item's exact change in the run score, computed incrementally. It never
uses a different formula or an estimate standing in for it.

Routing results stay outside this score and rank above it. The loop ranks by the phases' closures in order, then the
clean closure, then the run score (loop spec). This is the one ordering used everywhere a board is compared.

## Each term, whole and incremental

Each run-score term is defined once, with two forms:
- the whole-board value the run score sums;
- the change from lifting a set of items and putting them at new places, computed from the touched nets and items only.

The search, refine and the turn check call the incremental form. A test checks that the incremental form equals the
difference of the whole-board values, across the bench fixtures.

| Term | Whole board | Incremental form |
|---|---|---|
| airwire | the ratsnest's MST length | refresh the MST of the touched nets only, which the occupancy's ratsnest already does on lift and commit (occupancy.py:1216-1245); the change is the touched nets' new length less their old |
| crossings | KiCad's ratsnest crossings, priced by kind | recount the crossings of the touched nets' MST edges against all edges, using the native ratsnest (ratsnest.rs:331) with a spatial index; the change is new less old |
| link_over | the sum over links past their limit | the touched items' links only |
| push | the sum of value/limit | the touched items' pushes, and the pushes on them |
| giveway | the carried vias' action costs | the actions the move causes |
| back_face, unplaced | counts | the touched items |
| escapes (`escape_*`) | finding counts | the touched items' escapes, re-judged |
| congestion (RUDY) | the worst cell | the touched items' nets' boxes re-added to the grid |
| findings by kind | counts | not incremental: rechecked once at the end of refine and of each construction |

The weights are the existing `[score]` settings, and the only weights. The search's own weights that duplicate them
(`score.crossing` in `Scorer`, the escape weights) read the same settings. The pin study's per-kind crossing weights
(pairs x5, impedance x3) move into `[score]` as the run score's pricing by net kind. So a pair crossing costs the same
in the pin study, the search and the run.

The search's wire term changes from a clique of pad-to-pad distances to the MST change. That is the main behavioural
change: it moves placements. It is measured on the bench before it is adopted (see Gate).

## Who changes

- **Search** (`Scorer` and the native scorer): it scores a candidate by the incremental run-score change of putting
  the item there. Pruning stays: a candidate whose wire change alone exceeds the best total seen is dropped.
- **Refine:** it scores a move by the same incremental change. It is built on this, never on its own formula.
- **The turn check** (turn.better): it reports a turn when the incremental change of turning is below zero by
  `place.turn_gain_*`. Its own wire and crossing terms are removed.
- **Restarts and explore:** they rank by the loop's ordering (phases, then the clean closure, then the run score).
  Congestion becomes a run-score term, no longer explore's addition.
- **The pin study:** its map search keeps its own incremental counter (pinmap.rs `Tally::delta`), but with the
  run-score crossing and wire definitions and weights. A pose it proposes is judged by the run-score change of turning
  the part, with the legality check the refine spec adds.
- **Cleanup's score:** removed with cleanup.

## Gate

Replacing the search's clique with the MST change moves every board. Before it is adopted:
1. Run the bench in all three configurations, plus the fairing core copy, with the old and the new search score.
2. Compare the run score, placed counts and quick-route closure.

It is adopted if no fixture's run score is worse by more than `bench` noise and the core's closure does not drop. If
it fails, the search keeps the clique as a documented divergence, and refine and the turn check still use the run-score
delta. The spec comes back for review with the numbers.

Speed: the incremental MST and crossing recount must keep a candidate under about 5 us natively (the sweep is 1-2 us
now). The native ratsnest and a spatial index of edges are the means. This is measured in the same gate.

## Testing

- **Incremental against whole:** per term and in total, on the bench fixtures and synthetic boards, including pairs,
  planes and pushes.
- **One set of weights:** a change to a `[score]` weight changes the search's choice, refine's choice, the turn
  check's verdict and the pin study's result in the same direction.
- **The ordering:** a board with a better earlier phase ranks above one with a better clean closure.
- **The gate,** as above.

## Out of scope

- New score terms. This is a unification, not a new objective.
- The routing score itself, which is the router's.
