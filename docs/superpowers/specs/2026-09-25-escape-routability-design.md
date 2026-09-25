# Escape routability: measure first, then rework escape depth

Date: 2026-09-25
Status: approved 2026-09-25; the lab runs cases 1, 2 and 5 first

## Why

`place.escape_depth` is meant to say whether a pin can be routed out of its
part. Three findings say it does not:

- The MCU session's tuning (fairing, 0.33, full routes): the run score ranks
  the depth variants in the opposite order to the router. Depth 0.3-0.4
  scores best and routes worst; 1.5 routes best (100% on the MCU cell) and
  scores worse; 2.0 routes worse again.
- Fewer crossings did not predict better routing either: across eight
  finalists the core's crossings ran 927-1106 with no ordering in closure.
- Drawn to scale (scratch figures, 2026-09-25), depth controls three
  unrelated things:
  1. the length of each pin's straight strip, which rarely matters at
     1.0 mm because the pin's 1.0 mm via spot covers all but the strip's
     last 0.2 mm, and an open via spot keeps the pin open;
  2. the radius round each pin inside which two of the part's airwires
     crossing cost `score.escape_crossed` (20 mm, five times an ordinary
     crossing);
  3. the window the findings' path search must get out of.

  None of them is "a track of this net class can get from this pin to open
  board". At 20 mm, (2) would charge nearly every crossing near a chip and
  (3) would almost never fire.

So before changing the model we need to know what makes a pin escapable
for a given net class, and what blocks it, measured against a router.

## Ground truth

Two sources, both independent of placemat's own measures:

- **The router placemat is judged by.** KiCadRoutingTools (0.22.0, the
  router `--route` drives). Its full run is the reference; its QFN fan-out
  tool (`qfn_fanout.py`, stub and under-pad via-drop methods) shows what a
  fan-out generator can and cannot escape, and `blocking_analysis.py` names
  what blocked a failed net.
- **A hand-routed layout.** `mnb-ecosystem/modules/MCU_RP2350B`
  (QFN-80, 0.4 mm pitch; 123 tracks and 59 vias round the chip). Its
  `LAYOUT-INTENT.md` records rules found by routing it, which a model has to
  reproduce:
  - a 0402 cap on a pin's axis leaves its +/-0.4 mm neighbours no straight
    lane at any track width (a lane needs 0.61 mm off a cap axis); those
    pins dive to vias;
  - relief via columns under the package, between the exposed pad and the
    pad row, take the pins the face cannot fan; a column has fixed capacity
    (three rows on one side), and no signal passes a column via into the
    pocket behind it;
  - caps lie parallel to the local lane flow (radial on the west face,
    45 degrees in the diagonal field, vertical in the column strips);
  - fans run at one lane pitch (track + clearance, 0.4 mm there).

## The lab

A script, `fixtures/escape_lab.py`, that builds each case as a placemat
board (fixed placements through `Board.place(at=...)`), writes it, routes a
copy with `placemat.kicad.route.route_board`, and records per pin:

- **escaped**: the router connected the pin to its sink, and how: on the
  pin's layer (the goal), or through a via (allowed, but counted), with the
  via's distance from the pad and which neighbours' lanes its clearance
  took;
- **vias**: how many the escapes used, per case;
- **detour**: the routed length against the straight distance;
- **blocker**: for a failed pin, what `blocking_analysis` names;
- **placemat's view** of the same board: the crossed, closed and walled
  counts and the findings' path search, at depths 0.3, 0.6, 1.0, 1.5, 2.0,
  3.0.

Every case keeps the far side of the problem easy, so a failure is the
escape and not the rest of the route: each signal pin nets to its own sink
pad on a ring well outside the chip, and supplies go to planes.

Cases, all to scale and drawn as SVG/PNG from the board itself:

1. **Bare chip.** The RP2350B footprint alone, at the net classes in use
   (0.2/0.2, 0.15/0.15, 0.1/0.1 track/clearance; via 0.6/0.3 and
   0.45/0.25). The baseline: everything should escape.
2. **One cap at a pin.** A 0402 (then 0603) on one supply pin mid-row, over
   a grid of positions and turns: on the pin's axis radial, tangential and
   45 degrees; offset along the row by 0-1.2 mm; 0.2-2.0 mm out; with and
   without via-in-pad. Which neighbours still escape, and how.
3. **Two caps on neighbouring pins.** The satellite case that failed in
   0.33 (two 0805s 1.29 mm apart) and the hand layout's mirrored pairs.
4. **A crowded face.** Caps at every supply pin of one face as the hand
   layout has them, then placemat's own placement of the same parts.
5. **The hand layout itself.** The module's placement with its tracks
   removed, routed; and placemat's measures on the hand-routed board.
6. **Board cases.** The MCU session's fairing variants (their `t-<variant>`
   runs), per pin where the router reports it.

A case takes seconds to route quick; the grid in case 2 is some 200
boards. The first run is cases 1, 2 and 5, which decide the model.

## What the data should tell us

For each candidate model below: does it say escaped where the router
escaped and blocked where it failed, per pin, and does its count rank the
cases as the router's closure does? A model is good enough when it agrees
with the router on at least 90% of pins in cases 1-4 (escaped on the layer,
escaped by a via, or not at all), ranks the case 6 variants in the
router's order, and reproduces the hand layout's rules.

Candidates, from simplest:

- **A. Corridors, fixed.** Keep one lane per pin, but make it a lane the
  net class decides (track + 2 x clearance wide), long enough to clear the
  pin's own row, and stop counting the via spot as an escape: a via is a
  costed fallback (below), not an open lane. Separate the crossed-escape radius from the lane
  length (its own setting, or none).
- **B. Row capacity.** Treat a pin row as a flow: at rings 0.5, 1.0, 2.0 mm
  off the row, count the gaps between foreign copper and how many lanes
  each passes (floor((gap - clearance) / (track + clearance))), plus the
  via sites within reach; blocked pins = demand past capacity at the
  tightest ring. This is how BGA escape is usually judged, and it explains
  the +/-0.4 mm neighbour rule and the relief column's capacity.
- **C. A lane search.** Per part, route the pins' escapes one after another
  on a grid at the net class (each committed lane blocks the next) out to a
  ring or a via; blocked pins are the ones that find no way. The most
  faithful and the slowest; possibly only for findings and cleanup, with A
  or B in the search.

In every candidate an escape on the pin's own layer is the goal. A via
escape is still an escape, and may be the only one a fine-pitch part has,
but each via costs: it has electrical effects, and a via and its clearance
(often larger than a track's) take more room than the lane it replaces and
can block the neighbours' lanes. So a model counts a pin that escapes by a
via as escaped, charges the via, and counts the room the via takes against
its neighbours. The aim is fewest vias, not none. Today an open via spot
makes a pin cost nothing and costs its neighbours nothing.

The depth setting then goes the way the data says: likely replaced by
lengths derived from the net class and the package, with a separate
setting only for what the data shows needs tuning.

## Not in this proposal

The model's implementation, its native port, and new weights. Those follow
from the lab's result as their own spec. The score-depth change (findings
measured at a fixed `score.escape_depth`) is on hold in `git stash`; it only
made scores comparable across depths and would be superseded.

## Layers

Every case runs twice: F.Cu signal with B.Cu ground (as the fairing boards
are, where a via only serves a plane pin), and both layers signal (as the
RP2350 module is, where relief vias carry signals on B.Cu). That shows
whether the model has to know the stack-up.
