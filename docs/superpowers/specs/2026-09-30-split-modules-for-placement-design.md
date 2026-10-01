# Modules split by placement requirement

Status: approved (2026-09-30).

Source: the owner, through a board's session (2026-09-30).

## Two sides of one rule

A module is placed as one piece, so its parts should share a placement
requirement. The rule has two sides.

- **Capture** decides modules from where each part must physically sit.
  A part goes in the module of what it must be near, not what it logically
  belongs to: a thermistor that measures a converter goes in the
  converter's module. Module boundaries fall at connections that tolerate
  distance: the thermistor's reader, on a slow analog signal, can be
  anywhere. This is the capture skill's to say (section 3).
- **Layout** finds out, from the board's constraints, that a module as
  captured cannot be placed. Its parts want different places: a job joined
  to the rest only through board-level nets, or a cell too large or the
  wrong shape for the room its tightest part needs. placemat reports it,
  and the change is made in the capture, not worked round in the layout
  script.

## 1. The skill

- **SKILL.md, "A fresh board", step 3 (the model).** A new bullet: a cell
  is placed as one rigid piece. When its parts want different places, the
  capture's module boundary is wrong for this board: say so, and propose
  the split, or the move of parts between modules, as a change to the
  capture. The `split` finding and a refused cell are the signals.
- **capture.md, a new section "Modules for placement"**, placemat's view
  only:
  - the `split` finding and how to read it;
  - a split or a move is made in the capture;
  - a member no net inside the cell joins to the others is placed by the pin
    it serves or the part it senses or shields, not by a group.

## 2. A finding: a cell of several jobs

At each run, placemat groups each cell's members by the nets local to the
cell:
- A net is **local** when every one of its pads is on the cell's members.
- Plane nets (`board.plane()`) are not local, whatever their pads.
- Two members are in one group when a local net joins them, directly or
  through other members.

A cell with two or more groups of two or more members is a finding of kind
`split`:

"m: its parts form 3 groups joined only by board-level nets: U3, C7, R2;
U5, R4; Q2, R9 (and 4 parts no net inside the cell joins to the others:
C1, C2, C3, R1, each placed by the pin it serves or the part it senses).
Parts with no close placement requirement in common may be split into
modules of their own."

- Some members have no local net: no net inside the cell joins them to the
  others. A bypass capacitor is placed at the pin it serves, and always
  belongs in the module of the IC it serves: never a split candidate,
  whatever the grouping shows. A thermistor is
  placed at the part whose temperature it measures: all its nets run
  elsewhere, but its position is defined by what it measures. Such members
  are listed and do not make a finding on their own.
- The finding carries no run-score weight, and it is noted on the cell's
  step.
- `place.split_min_group` (default 2) is the least members a group needs
  to count.

A cell whose members form one group, with or without members no local net
joins, is not reported.

## 3. The capture skill

circuit-capture is a separate skill, and the two skills stand alone. With
the owner's leave, the coordinator adds the capture side there: module
membership by physical placement need; boundaries at connections that
tolerate distance; the layout may come back with physical corrections.
It names neither placemat nor any project.

## Verification

- A cell of two independent pairs (U1-R1 on a local net, U2-R2 on another,
  joined only by a plane and a board-level net) is a `split` finding
  naming both groups.
- A cell with one group and two bypass capacitors (no local net) is not.
- A plane net shared by every member joins nothing.
- A net with a pad outside the cell joins nothing.
- `place.split_min_group = 3` drops a finding whose groups are pairs.
- The finding has no run-score weight: the run score is unchanged on the
  bench (the bench's modules place with their cells released, so the bench
  tally is "same 32").
