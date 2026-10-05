# Pin map study

Approved direction (2026-10-05): a finding with a suggestion, quick enough to
run on every preview from the first, so the agent learns the best orientation
and pin map of a part before it lays the board round the wrong one.

Built: 2026-10-05

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
  pads turn about its centre (a part in a cell: the cell's pads about the
  cell's centre) and nothing else on the board moves.
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

- **Scored as unrouted.** The ratsnest joins pads already connected by
  copper into one cluster with no airwire between them (`board_nets`), so on
  a laid board a routed net has no airwire to move and crossings against
  routed nets read as none. The study therefore builds its ratsnest from the
  pads alone (`board_nets(pads, copper=())`): tracks, vias and pours are not
  torn up, only ignored, and a first preview and a laid board are scored on
  the same terms. The finding says how many of the moved nets have copper
  today, since a remap means routing them again.

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

## A part in a cell

Approved 2026-10-05. A cell is a stamped module instance on a board. A
studied part that is a member of a cell is studied as the cell: turning the
part alone would leave out the crossings of its satellites (bypass
capacitors, a crystal), which turn with it.

- **The poses** turn the whole cell about the centre of its envelope: every
  member's pads turn, and only the part's own pool pins move. The turn is
  theoretical: the cell stays where it is, nothing is checked for collisions
  or DRC, and only the airwires are scored.
- **The body** the airwires go round is the cell's envelope (the box round
  its members' courtyards and its own copper, as the occupancy holds them;
  an arranged cell's members at their arranged places), not the part's
  courtyard. The part's pins keep the outward normals of its own courtyard
  and leave by that side of the envelope; the other members' pads leave by
  the envelope side they are nearest.
- **Nets inside the cell.** A net with every pad on the cell's members and
  none that may move turns with the cell as a posed net of the background,
  its airwires straight between its pads. A pool net whose one other pad is
  on a series member of the cell (two pads, a prefix of
  `pins.follow_prefixes`) is followed to that member's far net, when the far
  net has pads outside the cell, none on a part with a pool, and no other pad
  on the cell: its pull is those outside pads. Any other pool net whose other
  pads are all on the cell's members keeps its pin (`held`, `why: in_cell`,
  listed in `in_cell` as `{net, ref}`), since the module's own run places it;
  it does not count in `pins.placed_share_min`.
- **Members not placed.** A cell with a member not placed is studied with
  the members it has, and the missing member is listed in `unplaced_ends`
  (with net `""` when it carries none of the part's nets); the share rule
  decides whether the advice is withheld.
- **A group led by a loose part** carries the cell facts, the capture
  sentence and `stamp_maps` of its first part that is in a cell.
- **The core** takes the cell as one posed body: a part whose centre and
  box are the envelope's and whose pins are every member's pads. No change
  to the native core or its twin. Two studied parts in one cell are two
  bodies on the same envelope, studied together with one pose.
- **Faces.** A cell is studied on the face it stands on; `pins.faces` does
  not flip it. Whether a cell may stand on the back depends on its own
  flip rules, which the study does not read.
- **Two levers.** A winning turn is taken either way: (1) turn the cell on
  the board to `cell_rotation_deg`, the cell's present rotation plus the
  turn (each stamp turns on its own); (2) keep the cell and re-lay the
  module with the part at `module_rotation_deg` in the module's frame (its
  rotation in the cell, plus the turn; minus it for a cell on the other face
  from its stamp), its satellites re-placed round it. Lever 2 re-lays every
  stamp of the module, and its text says so. Either one means the next run
  re-places the board.
- **An arranged cell.** A cell standing in one of its module's offered
  arrangements has its members where that arrangement puts them, so
  `module_rotation_deg` is in that arrangement's frame: the module's own
  frame is not recovered from it. The facts carry `arrangement` (`default`
  for the module's own layout) and the text names the frame when it is not
  the default.
- **One capture, several stamps.** The map is a change to the module's
  capture, shared by every stamp of it. When the stamps of one module have
  different best maps (by pin moves; a stamp with no map worth having keeps
  its pins) or different best `module_rotation_deg` (a stamp with no map at
  its present one), each stamp's finding says so and lists each
  (`stamp_maps`, with each stamp's rotation).
- **The module** is named by the generator's `layout.log` beside the board:
  the folder of the cell's module layout path. One reader of that log
  (describe.py `layout_log`) serves this and `placemat parts --fragments`. Without a log the name is
  null and the stamps are the cells whose members match (instance path in
  the cell and footprint).
- **Facts.** `cell`, `module`, `stamps`, and the best pose's
  `cell_rotation_deg` and `module_rotation_deg`; each turn record of a part
  in a cell carries the five. finding_text and the suggestion's advice text
  render the two levers. Parts not in a cell keep their facts and behaviour.
- **A laid board read from disk** (the bench, the real-board tests) does not
  say how its cells were turned from their stamps: `placed_from_geometry`
  takes them as given (`cell_rotations`), else 0. A cell's face is that of
  its member with the most pads, and a cell on the back is taken as flipped
  from its stamp.

## Parts not placed yet

Approved 2026-10-05. A part the placement has not placed has no position, so
a net whose only far end is on one has nothing pulling it, and the study
would move it for free.

- A studied net with no placed pad but the part's own is held on its present
  pin (`held`, `why: unplaced`) and never moved.
- `unplaced_ends`: `{net, ref}` for every pad of a studied part's net on a
  part not placed, and `{net, ref, via, far}` for one on the far net a placed
  series part takes the net on to.
- `pins.placed_share_min` (default 0.8): when fewer than that share of a
  group's movable nets have a placed far end, the study gives no map or
  rotation. The `pins.remap` notice is still raised, with `withheld`
  (`placed`, `of`, `share_min`), so the agent knows the study waits on
  placement; it has no suggestion. The setting is in the study's digest.

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

Facts: the part(s); the present total and crossings; the moved nets that
have copper on the board now; per rotation the best
total, crossings (against others, among studied nets, weighted), length, the
summed bend angle, and the map (net, from pin and name, to pin and name); which constraints held
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
- A routed board: a net joined by copper still gets its airwire in the
  study, and the score matches the same board with its copper removed.
- A real fixture board with an MCU: the study's best map beats the present
  one, and no board item moves.

## Settings

`pins.exit_mm`, `pins.follow_series`, `pins.pair_weight`,
`pins.impedance_weight`, `pins.length_weight`, `pins.bend_weight`,
`pins.rotations`, `pins.seeds`,
`pins.budget_ms`, `pins.faces`, `pins.gain_min`, `pins.placed_share_min`,
`pins.explore_top`, each with a default and a line in the settings table.

## Build notes

Measured on the final branch, native core built into the worktree venv.

Study time per part on the real reference board (one MCU, 56-pin QFN;
`fixtures/pinmap_bench.py --repeat 3`, median), against `pins.budget_ms` of
100 ms:

| core   | time per part | clock ran out | present total | best total |
|--------|---------------|---------------|---------------|------------|
| native | 0.024 s       | no            | 1437.918      | 1271.863   |
| Python | 0.109 s       | yes           | 1437.918      | 1271.863   |

The best map saves 166.055 (11.5 percent) of the present total at the present
rotation. The Python fallback runs out of its budget part way and still finds
the same best.

Those figures turn the MCU alone. The MCU is a member of the board's cell
`logic` (27 members), so with "A part in a cell" it is studied as the cell,
taken as standing as stamped:

| core   | time per part | clock ran out | present total | best total |
|--------|---------------|---------------|---------------|------------|
| native | 0.017 s       | no            | 1479.429      | 1218.404   |
| Python | 0.111 s       | yes           | 1479.429      | 1218.404   |

The best is the cell turned 90 degrees, 17.6 percent below the present total;
at the present rotation the best map saves 204.112 (13.8 percent).

With in-cell nets followed or held (a pool net through a series member of
the cell, R12, is followed to its far net outside), the present total is
1469.776, the best at the present rotation 1231.755 and the best overall
1205.606, the cell turned 90 degrees (18.0 percent below the present).

Preview hook (`_report_pin_maps` inside `Board.resolve`, native core, one
annotated part on the whole-board fixture, three cold and warm pairs under
load): cold 0.07-0.12 s, warm 0.03-0.04 s with one 0.10 s outlier. A warm
cache hit saves about half, because the build and the digest are still paid.

Real-board tests (`tests/test_pinmap_real.py --full`): both pass. The full
suite passed (5693 passed, 22 skipped), and `fixtures/bench.py --jobs 2`
matched `bench.json` in every case (33 same in each configuration).
