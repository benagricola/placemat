# Crossings and escape room in every placement judgement

Date: 2026-09-24
Status: design
Source: the brief from the fairing-instrument MCU session (PLACEMAT_GAPS.md,
"2026-09-24: placemat 0.32", entry 4), and the decisions taken with Ben on
2026-09-24.

## Why

Ratsnest crossings are the most direct measure placemat has of how hard a
board will be to route, and today it only reports them after DRC. Nothing
that chooses a placement looks at them:

- the search scores a candidate on wire plus links (`Board._scorer`);
- the cleanup pass on HPWL plus links (`cleanup.py`);
- explore on placed, findings, the worst RUDY cell, then wire
  (`explore.score`);
- the best-run ranking on placed, DRC, findings, airwire
  (`report.objective`).

Placemat also has no rule that a part must not wall off another part's pad
from what that pad connects to. In the MCU cell of the fairing core, the EN
capacitor sits under pins 3-4 and the RF supply inductor under pin 6, so
VDD_RF from pins 2-3 crosses MCU_EN from pin 4. Swapping the two removes the
crossing, but cleanup never tries it: it skips satellites, swaps only
identical parts or two-pad neighbours, and has no crossing term.

The satellite axis bug in the same brief is fixed separately (87d15ed): a
satellite sits on its pin row's normal.

## The measure: placemat's ratsnest

KiCad's ratsnest (`pcbnew/ratsnest/ratsnest_data.cpp`, master, fetched
2026-09-24):

- per net, the nodes are the item anchors: a pad's anchor is its position;
- items already joined by copper form a cluster, whose members are joined
  by zero-weight edges that are united first and never become ratsnest
  lines (`RN_NET::AddCluster`, `kruskalMST` lines 49-127);
- candidate edges come from a Delaunay triangulation of the anchor points
  (lines 228-243), weighted by the distance between anchors (`addEdge`,
  line 177), with a sorted walk for collinear points (lines 218-225);
- Kruskal takes the minimum spanning tree over them, ties ordered by
  (weight, position, tag) (lines 92-121);
- zone anchors are then moved to the nearest zone outline point
  (`OptimizeRNEdges`).

The Euclidean minimum spanning tree is a subgraph of the Delaunay
triangulation, so a Kruskal over every pair of anchors gives KiCad's tree,
up to ties. placemat computes it the same way:

- nodes are pad anchors (the pad's position, not its shape's centre, where
  they differ);
- pads joined by planned or existing copper are clustered;
- Kruskal uses KiCad's tie order.

Two edges of different nets cross when their segments properly intersect,
which is the test `report.airwires_from_drc` already applies to KiCad's
edges.

**Nets not counted.** Plane nets (`board.plane()`) and free nets pull
nothing today, because each pad drops to its plane by a via. Their crossings
are counted at a weight, `[place] crossing_plane_weight`, default 0. On the
core, GND and V3V3 are 417 of 1,041 crossings.

**Checked against KiCad.** On every fixture board written and checked with
kicad-cli, placemat's count for the counted nets equals `airwires_from_drc`'s,
within the variation KiCad itself shows between runs of the same board
(report.py's AIRWIRE_NOISE note).

## The cost

One cost everywhere, in millimetres of wire:

```
cost = wire + links + crossing_cost * crossings
     + escape_crossed * crossed + escape_closed * closed + escape_walled * walled
```

- `wire` and `links` are as today: the search's pad-to-target sum, and
  cleanup's HPWL plus each link's weight times its length.
- `crossings` is the number of crossings the change adds, between the
  item's own ratsnest edges and those of every other net already placed,
  and among its own edges of different nets.
- `crossed`, `closed` and `walled` are the three escape levels, defined
  under Escape room.
- `[place] crossing_cost` (mm per crossing) and the three escape weights
  are settings with documented defaults. The same settings weigh the same
  things in the run score, so placement and ranking agree. The defaults are
  checked by bench measurement (plan tasks 4 and 5) and by the replay (task
  3).

| Setting | Level | Starting weight |
|---|---|---|
| `escape_crossed` | two escapes from one part's pins cross near its pin row: a via or a detour | 20 mm |
| `escape_closed` | a pad's last route toward its target is closed, other directions still open: the track goes the long way round | 50 mm |
| `escape_walled` | a pad has no route out at all: nothing reaches it until something moves | 400 mm, just under an unplaced part |

For one candidate, the item's new edges are approximated by joining each
of its counted pads to the nearest placed pad on the same net: the leaf
edge an MST would add. The placed nets' trees are recomputed only when a
part commits, and only for the nets that part touches. An index over edge
boxes keeps the per-candidate test local.

Where the cost is used:

- **Search.** `Board._scorer` adds the crossing and escape terms. The
  targets, radius and grid are unchanged.
- **Cleanup.** Every move and swap is kept only when the cost falls. No
  limited link may end over its limit and longer than it was (today's
  rule, kept).
- **Explore and ranking.** Both use the run score below.

## The run score

Runs, explore variants and bench results are judged by one weighted score
instead of a fixed order (Ben, 2026-09-24). Every term is a count times a
weight, in millimetres of wire, and lower is better:

| Term | Counted as | Weight setting | Default |
|---|---|---|---|
| unplaced part | each part not placed, times its declared priority's multiplier | `score_unplaced`; `score_priority_high`, `_default`, `_low` | 2000 mm; x2, x1, x0.5 |
| DRC violation | each real DRC violation (runs only) | `score_drc` | 200 mm |
| link over its limit | mm over the limit, times the link's weight (SHORT 8, PREFER 2, DEFAULT 1) | `score_link_over` | 20 mm per mm |
| fixed item not legal where put | each | `score_fixed` | 200 mm |
| copper conflict or uncrossable tracks | each | `score_copper` | 200 mm |
| label on a part | each | `score_label` | 50 mm |
| crossed escape | each | `escape_crossed` (shared with the search) | 20 mm |
| escape closed toward its target (corridors, at the end of the resolve) | each | `escape_closed` (shared) | 50 mm |
| walled-off pad (confirmed by the path search) | each | `escape_walled` (shared) | 400 mm |
| setup finding (undeclared part, missing layer, web) | each | `score_setup` | 0 |
| ratsnest crossing | each, on counted nets | `crossing_cost` (the search's) | from task 4's measurement |
| airwire | mm | 1 (the unit) | - |
| worst RUDY cell (explore only) | steps of `explore_congestion_step` | `score_congestion` | from measurement |

The defaults were checked by task 3's replay (`fixtures/rank_replay.py`)
against the fairing core's recorded runs, 45 families of two or more runs,
walked in order and the best kept as best.json keeps it:

| Weights | Families keeping a different run than 0.32's order | Of those, a run with fewer parts placed |
|---|---|---|
| unplaced 500, link 20 | 7 | 3 |
| unplaced 2000 | 5 | 1 |
| link 5 | 6 | 1 |
| unplaced 2000, link 5 | 6 | 1 |

Where the same parts were placed, the score took the run with fewer
crossings and less link excess, even with one more finding: a link a hair
past its limit while the others got shorter. At unplaced 500, two core
families kept a run with a part fewer for halving the link excess. The one
run with fewer parts kept at 2000 is Backlight's, whose 0.32 best placed
every part with its links 1,391 mm x weight past their limits. Ben chose
unplaced 2000 and link 20 x the link's weight (2026-09-24).

- **Findings get a kind.** A finding becomes `Finding(kind, text)`, with
  the kinds in the table. Every site that emits one names its kind. The
  text is unchanged, so what a run prints and the reuse replay stay as
  they are.
- **No double count.** An unplaced part is one term. Its finding text is
  still printed, but it is scored only as unplaced.
- **Stored as measurements.** A run records its counts by kind and its
  measures, not its score. The score is computed when runs are compared,
  so a weight changed in `placemat.toml` re-ranks at once, including
  against the stored best run.
- **Noise.** KiCad gives different ratsnests for identical boards
  (report.py's AIRWIRE_NOISE note). Two scores tie when they differ by
  less than `best_airwire_noise` x airwire plus `best_crossing_noise` x
  crossings x `crossing_cost`. The crossing band is measured from repeat
  runs of identical inputs, as the airwire one was.
- **Where it is used:**
  - the best-run ranking, replacing `report.objective`'s order;
  - explore, replacing `explore.score`'s order: no DRC term, and
    placemat's own crossing count;
  - the bench verdict: a module is better or worse when its score moves
    beyond the noise band.
- **Reported.** A run prints its score by term against the best run, so
  the term that decided is visible.

## Escape room

Every placed pad on a counted net keeps short escape corridors:

- one per free side of the pad: a side that does not face its own part's
  body or its neighbours in the same pad row;
- each corridor is as wide as the net's track width plus its clearance on
  both sides, and `[place] escape_depth` long (a setting with a documented
  default, chosen by measurement);
- a pad in a row of a many-pin part has one corridor, along the row's
  normal (`placer._pin_normal`);
- a two-pad part's pad has up to three: outward along its axis and to
  either side.

A corridor is open while no foreign copper, pad or body (anything not on
the pad's net and not the pad's own part) overlaps it.

A pad's **escape toward its target** is open while at least one of its open
corridors points toward what it connects to. That is its ratsnest
neighbour, or for a plane net any open corridor (a via can go at its end).
Pointing toward means a positive dot product with the direction to the
target. A candidate closes an escape when it takes that last open corridor.
Each escape closed adds `escape_closed`.

A pad with no open corridor at all is **walled off**. Each pad a candidate
walls off adds `escape_walled` (instead of `escape_closed`). At 400 mm the
search walls a pad off only when the alternative is no spot at all.

A candidate whose own ratsnest edges cross another edge from the same
neighbouring part within `escape_depth` of that part's pads adds
`escape_crossed` (on top of the crossing's own `crossing_cost`).

At the end of a resolve a grid path search checks every pad the corridors
call walled off or closed. It searches at the net's track width and
clearance, in a window of `escape_depth` round the pad, for a path to the
window's edge or to a via spot. Only pads it confirms become findings.

`board.fanout()` stays the explicit way to reserve a band at a part that
needs more than this.

## Satellites

The search places a block's satellites on their pins' normals (87d15ed).
The cleanup pass may then move a satellite:

- shift it along the pin row, away from pins that need a path;
- step it further out, staggering neighbours so a track passes between;
- turn it;
- swap it with another part.

Each move is judged on the cost above. A move is allowed only while the
satellite's pad stays within its limit of its pin, measured pad edge to pad
edge: the declared link's limit when a link joins them, else
`[place] block_gap_reach` (today 2.0 mm, the reach a block already allows).

## Swaps between any parts

A cleanup step after the moves, for every pair of movable items on the same
face whose bodies are within `cleanup_radius` plus their sizes of each
other. Movable items:

- searched parts;
- satellites, within their limit;
- parts linked to the same anchor;
- cells.

Fixed, edge and lock-held items do not move, nor do focused items inside an
explore variant.

For a pair:

1. Lift both: mark them pending, so their room is free.
2. Search the larger (by body area) round the smaller's old spot, within
   `cleanup_radius`, in every rotation its declaration allows, scored by
   the cost, legal against everything else.
3. Search the smaller round the larger's old spot, in what is left.
4. Keep the swap only when the cost of the two falls and no limited link
   ends over its limit. Otherwise put both back where they were.

These swaps replace today's identical-part and two-pad-neighbour swaps,
which are special cases of them.

**Deferred.** Pushing small neighbours aside to make room for the larger
part is not in this stage. It needs chains of moves, each judged. It is
measured after plain swaps: if the MCU cell reaches its target without it,
it stays out.

## Findings

- **Crossed escapes.** Two ratsnest edges of different nets that start at
  pads of the same part and cross within `escape_depth` of that part's
  pads. For example: "U2 pins 3/4: L2 VDD_RF crosses C2 MCU_EN".
- **Walled-off pads.** A pad the path search confirms has no way out. For
  example: "U2 pin 6 (VDD_RF): walled off by L2, C2".

## Preview

`preview --no-tags` draws the view without annotation tags, with `--zoom`,
`--around` or the whole board. The notes are still printed.

## Done when

The brief's own targets:

- MCU cell of the fairing core:
  - no pad walled off;
  - no crossed escape at its pin rows;
  - cell crossings 34 or fewer (43 at 0.32.2, run 1e7c2133; 41 after
    87d15ed);
  - every satellite on its normal or offset within its limit;
  - every bypass link limit met.
- Core: crossings below 1,041 (run 985825a5) with no new findings; plane
  nets weighted by `crossing_plane_weight`; runs ranked by the run score,
  with its defaults checked by the replay.
- Bench:
  - it records crossings (placemat's count) and HPWL;
  - the default, solve and physical configurations have no module worse on
    placed or findings;
  - the tally and the new baseline are in the commit.
- Suite green with and without the native module.

## Performance

The crossing and escape terms run for every legal candidate. The budget:
the benchmark corpus's default resolve at most 1.5x its 0.32.2 time,
measured sequentially in CPU time. The native sweep (its spec is on hold)
will take these terms into account when it is revised.
