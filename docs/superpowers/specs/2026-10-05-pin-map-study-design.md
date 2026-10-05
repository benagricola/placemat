# Pin map study

Approved direction (2026-10-05): a finding with a suggestion, quick enough to
run on every preview from the first, so the agent learns the best orientation
and pin map of a part before it lays the board round the wrong one.

## Goal

For a part whose pins the capture says may move (an MCU's general-purpose
pins), placemat measures how many weighted ratsnest crossings a better
assignment of nets to pins would save, at the part's present rotation and at
each other quarter turn. When the saving is worth having it raises a
`pins.remap` notice whose suggestion carries the map and the best rotation.
Nothing is written: a pin map is a capture change and a rotation a layout
change, both made by the agent or the user.

The same study runs on a first preview of a new board and on a laid run. At
the end of an explore it ranks the best variants by their crossings after
remapping.

## What it is not

- It does not move or turn a part. Rotations are theoretical: the part's
  pads turn about its centre and nothing else on the board moves.
- It does not judge DRC, escapes or routability, only the ratsnest.
- It does not write the .zen.
- It is not a new command; it is a finding, its suggestion, and an explore
  hook.

## Constraints: capture annotations

Annotations on the part in the .zen, each cited to its datasheet, as the
other `Pm.*` keys are (capture.md, "Annotations"). Pins are named by number
or by pin name, as `PadRef` names them; a range is `GPIO1-GPIO10` or `3-8`.

| key | value | meaning |
|---|---|---|
| `Pm.PinPool` | pins | the general-purpose pins: a net on one of them may move to another of them. A part with no pool is never studied. |
| `Pm.PinFixed` | pins | pins in the pool that keep their net (straps, USB, a crystal, in-package flash) |
| `Pm.PinAllow` | `NET:pins; NET:pins` | a net may only stand on these pins (an ADC input on the ADC1 pins) |
| `Pm.PinDeny` | `NET:pins; ...` | a net may not stand on these pins (an enable not on pins that reset pulled up) |
| `Pm.PinGroup` | `name:pins; ...` | pins that move as one block, keeping their order (a bus a datasheet ties to consecutive pins) |

A net on a pin outside the pool, or on a fixed pin, stays. A pool pin with no
net is free to take one. An annotation that names a pin the part does not
have, or a net it does not carry, is a `setup.pins` finding naming it, and
the study runs without that entry.

## The score

Built on `ratsnest.py`, placemat's port of KiCad's ratsnest.

- **Airwires round the body.** A studied part's body is an obstacle. A pin's
  airwire leaves along the pin's outward normal to a point just past the
  courtyard (`pins.exit_mm` beyond it), then takes the shortest way round the
  courtyard's box to its target. Crossings and length are counted on that
  path, so a net cannot leave the wrong side for free, and nets that leave
  neighbouring pins on one side in a different order from their targets
  cross where they leave.
- **Multi-pad nets** are scored on the minimum spanning tree of their pads,
  with the studied pins' ends taken at their exit points.
- **Series parts.** A net that reaches the part through a two-pad series
  part (a termination resistor) is scored on to the series part's far net,
  as one connection (`pins.follow_series`, default true).
- **Weights.** A crossing counts 1, `pins.pair_weight` where either airwire is
  a differential pair's, `pins.impedance_weight` where either is in a net
  class with a controlled impedance. Settings, not literals.
- **Bends.** For each studied net, the angle between its pin's outward
  normal and the bearing from the exit point to its target, in degrees: 0
  for a pin that faces its target, 180 for one that must turn back. This is
  what favours a 45 degree turn when targets lie on a diagonal: crossings do
  not change, but the tracks can leave straighter.
- **Total.** Weighted crossings against every other airwire plus crossings
  among the studied nets, plus `pins.length_weight` times the total airwire
  length in millimetres, plus `pins.bend_weight` times the summed bend
  angles.

## The search

Per studied part, per rotation in `pins.rotations` (default 0, 90, 180,
270; add 45, 135, 225, 315 for the diagonals), and on the other face when
`pins.faces` is true and the part may stand there:

1. A first map by assignment: each movable net to the free allowed pin whose
   exit point is nearest its target, solved as a minimum-cost matching that
   ignores crossings.
2. A local search over moves and swaps within the constraints (groups move
   whole), counting only the airwires a move touches, with a short annealing
   schedule and `pins.seeds` seeds.
3. Parts whose movable nets connect to each other's movable nets are studied
   jointly: their rotation combinations are searched together, with both ends
   of a shared net free.

Deterministic for a given board: seeds are fixed, ties broken by pin number.

## Speed

The study has to be quick because its value is early feedback.

- A per-part time budget, `pins.budget_ms` (default set by the bench, aimed
  at a few hundred ms), and a cap on the rotation combinations a joint study
  searches; the study stops at the budget with the best found, and says how
  many combinations it searched.
- It runs after a run's or preview's placement, once, on the final board,
  never inside the placement search.
- A digest of what the study reads (the studied parts' pads and nets, the
  annotations, the other airwires' end points) is kept; a run whose digest
  matches the last one's reuses its result.
- Incremental crossing counts: a move recounts only the airwires it changes,
  against a grid of the board's other airwires.
- If the bench shows the Python search over budget on the reference boards,
  the inner crossing update moves to the native module.

## The finding

`pins.remap`, severity notice, one per studied part (or joint group) when the
best map at any rotation saves at least `pins.gain_min` of the total.

Facts: the part(s); the present total and crossings; per rotation the best
total, crossings (against others, among studied nets, weighted), length, and
the map (net, from pin and name, to pin and name); which constraints held
nets in place; the combinations searched and whether the budget ran out.

Rendered at the edge (finding_text): "U1: a pin map with 88 fewer weighted
crossings exists at its present rotation; at 90 degrees, 112 fewer".

Its suggestion (lever `pins`) carries the best map and, when another rotation
wins, the rotation to declare. The studio draws the ratsnest before and after
for the selected rotation. `try` previews nothing (the map is a capture
change); it shows the map and the airwires. The probe can run the study with
a larger budget in the background.

## Explore

At the end of an explore the study runs on the best `pins.explore_top`
variants and their report gives each variant's crossings after remapping and
its map. The variants are ranked by run score as now; the remapped crossings
are reported beside it, not folded into the score.

## Errors

- A part with no `Pm.PinPool`: not studied, no finding.
- Constraints that leave no legal map (a net allowed nowhere free): a
  `setup.pins` finding naming the net and the rule; the part is not studied.
- A budget too short to finish the first map: the finding says so.

## Testing

- Synthetic boards with a known optimal map; each constraint form honoured;
  a group kept whole and in order; a joint study of two linked parts beats
  studying them one at a time on a case built for it.
- The body obstacle: a net whose target is behind the part is scored round
  the body, and the best map never sends it out the far side.
- Bends: with targets on a diagonal and crossings equal, a 45 degree
  rotation in `pins.rotations` wins on the bend term; with only quarter
  turns listed, no 45 degree result is reported.
- Determinism: the same board gives the same map and total twice.
- Speed: on the reference boards the study finishes inside `pins.budget_ms`,
  and a repeated run reuses its result.
- A real fixture board with an MCU: the study's best map beats the present
  one, and no board item moves.

## Settings

`pins.exit_mm`, `pins.follow_series`, `pins.pair_weight`,
`pins.impedance_weight`, `pins.length_weight`, `pins.bend_weight`,
`pins.rotations`, `pins.seeds`,
`pins.budget_ms`, `pins.faces`, `pins.gain_min`, `pins.explore_top`, each
with a default and a line in the settings table.
