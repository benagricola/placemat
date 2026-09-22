# A global pre-solve for the searched tier's hints

Date: 2026-09-22
Status: design

The searched tier places one item at a time. `_targets` (`layout.py`) collects
only the pads *already placed* that an item connects to, and `_seed_hint`
centres the item on them. So the first searched item has nothing to seed from
and is dropped into a free rectangle by `_settle_in_pocket` - whose note reads
"nothing it connects to is placed" - and every later item is pulled toward
incumbents that cannot move. A global solve gives every searched item a
starting point from the whole netlist at once, before any of them is scanned.

This is slice 1 of the external global-placement proposal. Its diagnosis is
verified against the code; its claims that the checks were dead code and that
the baseline was overwritten unconditionally were not, and were dealt with in
0.15 and 0.16.

## What does not change

- **Ordering belongs to the placer.** The solve produces hints only. Items are
  still scanned in rank order, `scan()` still legalises, and the link score
  still judges candidates against placed pads.
- **An explicit hint wins.** `at=Near(...)` beats the solve; the solve beats
  `_seed_hint`; `_seed_hint` beats the pocket scan. An item the solve cannot
  seed - no connection that pulls - falls through as today.
- **Determinism.** No randomness; fixed iteration caps; every loop in sorted
  order; results rounded before they reach a placement. The same inputs give
  the same bytes.
- **No dependencies.** Pure Python. numpy is importable on the development
  machine but `dependencies = []` means users do not have it.

## The model

**Unknowns** are the origins of the searched items not yet placed: parts and
cells. **Anchors** are items already committed - the fixed and edge tier -
at their placed pad positions. A part the script never places pulls nothing,
exactly as in `_targets`.

**Pins** are pads, at their offset from the item origin at the item's first
rotation and face, so a component is pulled toward the pin side that connects.

**Springs**, per net that pulls, per axis, sorted by pin position: consecutive
pins are joined, each spring weighted `(2 / k) / span` for a net of `k` pins
spanning `span` on that axis, times the link weight between the two pads. A
plane or free net pulls only through links the script declared on it, as since
0.14. A declared link is also its own two-pin spring at its weight. A spring
whose pads carry a `FREE` link is dropped.

**Starting positions.** The generator leaves unplaced items in a scatter off
the board, whose spans mean nothing, so the first solve uses unit spans and
later rounds re-weight from the previous round's positions.

**Regularisation.** A weak pull (0.01 of a unit spring) toward the centre of
the placeable area makes the system solvable when a group of items connects to
no anchor, and keeps it from drifting.

**The solver** is conjugate gradient on a symmetric sparse matrix held as
dictionaries, x and y independently, to a fixed tolerance with a fixed cap.

## Spreading

A raw solve piles items on each other. The spreading step divides the
placeable area by recursive bisection: the items are sorted along the longer
axis of the region and split into two groups of equal body area, the region is
split in the same proportion, and each half is divided again until each item
has a cell of its own. The centre of that cell is the item's spread position.
It keeps the solve's relative order - what was left of something stays left of
it - and gives an even density.

SimPL alternation: after each spread, the solve is repeated with a spring from
each item to its spread position, of weight rising round by round, so the
positions move from the wirelength optimum toward an even spread. The final
solve's positions, clamped inside the placeable area, are the hints.

This departs from the reference implementation the proposal points to, which
arranges the items of an overfull bin on a circle; that scrambles the relative
order the solve found. Bisection is simpler and keeps it.

## Settings

`[solve]`: `enabled` (default **false** until measured to help), `iterations`
(200), `tolerance` (1e-6), `rounds` (8). The proposal's acceptance test decides
the default: on a real board the solve earns `enabled = true` only if it beats
the solve-off run on the best-run objective.

## Saying what happened

A step seeded by the solve says "seeded by the global solve" instead of
"seeded on <nets>". The run records under `metrics.solve`: how many items it
seeded, the rounds run, and the last solve's iterations and residual.

## What this does NOT do

**Rotation and face.** The solve places origins; which rotation fits is still
the scan's choice among the rotations the item allows.

**Blocks.** A block keeps its own layout and its existing seeding.

**Legalise.** Hints may overlap each other or fixed items; `scan()` resolves
that as it always has.

## Test plan

Pure, over synthetic geometry:

1. one item between two anchors lands at the weighted midpoint;
2. a SHORT link pulls harder than a default one;
3. a chain of three items between two anchors spreads evenly;
4. the same input solves to the same numbers twice;
5. a solve that hits its iteration cap says so;
6. a plane net pulls only through a declared link;
7. bisection gives every item its own cell and keeps their left-to-right order;
8. spread positions stay inside the placeable area;
9. an anchored item never moves;
10. with `solve.enabled`, a searched item is seeded by the solve and its step
    says so; the first searched item is seeded from the netlist rather than
    dropped in a pocket;
11. an explicit `Near` beats the solve;
12. an item with nothing that pulls still falls through to the pocket scan;
13. with `solve.enabled` false, placement is byte-identical to before.

Against a real board: the proposal's acceptance - run the board with the solve
off and on, and compare on the best-run objective. The result decides the
default and is recorded either way.

## Documentation

- `api.md`: the `[solve]` settings rows and a paragraph on what the solve does.
- `SKILL.md`: when a board's searched items scatter or land in pockets with
  "nothing it connects to is placed", try `[solve] enabled = true` and compare.
- `migration.md`, `## To 0.20`: nothing changes unless it is enabled.
