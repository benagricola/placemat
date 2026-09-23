# A cleanup pass after the searched tier

Date: 2026-09-23
Status: design

The searched tier places one item at a time, each against what is already
down, and never revisits one. A part placed early is not moved when its
neighbours arrive, so the board ends with parts that a small move or a swap
with an identical part would bring closer to what they connect to. Chip
placers finish with a detailed placement pass for this (FastPlace-DP, Pan,
Viswanathan and Chu, ICCAD 2005: global moves toward each cell's optimal
region, then swaps and local moves). This ports its moves at the size of a
board.

## Measured

A prototype run as a post-pass (3 passes, 3 mm
radius, 0.25 mm step):

- **Module benchmark**, against placemat today: better on 23 of 32, worse on
  none, the same on 9; better on all 11 modules of fourteen or more parts;
  median HPWL 0.946 of today's where as many are placed.
- **The 220-part core board**: HPWL 2528.5 -> 2376.3 mm (0.940), declared link
  length 247.1 -> 226.7 mm, links over their limit 28 -> 26. Resolve 111 s,
  the pass 44 s more.
- A first version scoring plain HPWL shortened the wire but lengthened the
  declared links by 50 mm and put 3 more over their limit. The objective
  below prices links, and a move may not push one over its limit.
- With the pass in, the global solve is no better than the sequential seed
  (16 better, 10 worse of 32 in its best variant), so the solve is unchanged
  and stays off.

## What moves

A **movable** part is a searched part (`Freedom.SEARCHED`, kind `part`) that:

- was placed by the plain search: no `Near`, no edge, run, rim, ring, spoke or
  line (the fields `_solvable` already tests), not a block or cell member;
- has no other declaration positioned against it: no label on it, no
  `Near`/`At`/`Centre`/`FreeSpot` whose reference names one of its pads or
  the part, no row or ring containing it, no keepout placed relative to it.

Its rotation and face do not change: those were chosen by the scan among the
rotations the script allowed, and the pass keeps it simple.

## The objective

For a part, the cost of a placement is the HPWL of its nets that pull (not a
plane or a free net, only placed pins, at least two of them) plus, for each
declared link on one of its pads, the link's weight times its length. A
move is taken only when it lowers that cost by more than 1e-6 mm, and only
when no link with a limit ends over its limit and longer than it was.

## The moves

Each pass, in sorted item order:

1. **Global move.** The optimal region of a part is the median of the
   bounding-box edges of its nets' other pins (FastPlace). A scored `scan()`
   around the part's origin shifted there, and another around where the part
   is, each within `radius` at `step`, at the part's rotation and face; the
   cheaper legal answer is taken if it lowers the cost.
2. **Swap.** Parts of one signature - courtyard width and height to the
   micron, pad count, face - are tried in pairs in sorted order: each takes
   the other's placement (location and rotation) if both are legal there and
   the pair's cost drops.

Passes repeat until one changes nothing or `passes` is reached. Every
placement taken is legal by `occ.legal`, as a scan's is. No randomness.

## Where it runs

In `resolve()`, after the searched tier and before the copper that joins
searched items and the final label pass, so copper and labels see the parts
where they end. A moved step's placement is replaced, and its note gains
`cleanup: moved D mm, cost C0 -> C1` or `cleanup: swapped with K`.
`plan.cleanup` holds moves, swaps, passes run and the cost before and after,
and the run records it as `metrics.cleanup`.

## Settings

`[cleanup]`: `enabled` (default **true**), `passes` (3), `radius` (3.0),
`step` (0.25).

## Test plan

Pure, over synthetic boards:

1. a part placed early and left far from the parts it connects to moves
   toward them, legally, and its note says so;
2. two identical parts whose connections cross swap;
3. a move that would lengthen a link past its limit is refused;
4. a part with a `Near`, a label, or a reference from another declaration
   does not move; nor does a fixed or edge part, or a block or cell member;
5. the pass is identical run twice;
6. with `cleanup.enabled` false, placement is byte-identical to before;
7. `plan.cleanup` and `metrics.cleanup` record what it did;
8. copper planned after the pass reaches the pads where they ended.

Against the fixtures: the benchmark tally goes in the commit.

## Documentation

- `api.md`: the `[cleanup]` settings and a paragraph on what it moves.
- `SKILL.md`: a step noting `cleanup:` was moved after its turn; a part that
  must stay where the search put it takes a `Near`.
- `migration.md`, `## To 0.25`: searched parts may move after placement;
  `[cleanup] enabled = false` restores the old placement.
