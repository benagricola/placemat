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
| ratsnest crossing | each, on counted nets | `score_crossing` (the search's too) | 4 mm (task 4) |
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

### The crossing weight (task 4)

The bench (32 modules, three configurations) at each weight: signal
crossings / HPWL mm / findings / parts placed / seconds.

| Weight | default | solve | physical |
|---|---|---|---|
| 0 | 257 / 1424 / 5 / 423 / 65 | 227 / 1501 / 4 / 424 / 55 | 206 / 1292 / 3 / 425 / 55 |
| 0.5 | 233 / 1441 / 5 / 423 / 76 | 221 / 1525 / 4 / 424 / 56 | 176 / 1293 / 3 / 425 / 63 |
| 1 | 249 / 1442 / 5 / 423 / 76 | 240 / 1534 / 4 / 424 / 57 | 163 / 1289 / 3 / 425 / 60 |
| 2 | 227 / 1438 / 5 / 423 / 77 | 222 / 1538 / 4 / 424 / 56 | 160 / 1296 / 3 / 425 / 56 |
| 4 | 226 / 1456 / 5 / 423 / 74 | 219 / 1506 / 4 / 424 / 54 | 156 / 1282 / 3 / 425 / 59 |
| 8 | 233 / 1524 / 5 / 423 / 75 | 210 / 1512 / 4 / 424 / 55 | 247 / 1412 / 3 / 425 / 60 |
| 16 | 242 / 1514 / 5 / 423 / 76 | 204 / 1509 / 4 / 424 / 53 | 248 / 1406 / 3 / 425 / 59 |

4 mm is the default: crossings 690 -> 601 over the three configurations
(-13%), HPWL +2.3%, +0.3% and -0.8%, nothing placed or found differently,
default resolve time +14%. From 8 up the search moves parts away to dodge
crossings and the physical configuration loses: 247 crossings, HPWL +9%.
The ranking replay at 4 keeps one more family's run differently, within
the noise band.

## Escape room

Every placed pad on a net with another pad to join keeps short escape
corridors (escapes.py):

- a pad of a part with more than two pads has one, along its row's normal
  (`placer._pin_normal`); a pad of a two-pad part one outward along the
  axis and one to either side;
- each is the net's track width plus its clearance on both sides wide and
  `place.escape_depth` long (1 mm);
- each direction also has a via spot: a via touching the pad's edge that
  way, with its clearance.

A corridor is closed by copper of another net, or an unconnected pad, that
shares a copper layer with the pad; a via spot by such copper on any layer.
A part's body closes neither, since a track can run under it, and neither
does the pad's own part. (The first design had bodies closing corridors and
no via spots; measured, it called 287 pads walled across the bench of which
the path search below confirmed 75, and the search over-reacted to them.)

A pad's escape toward its target is open while a corridor pointing at a
ratsnest neighbour (a positive dot product), or any via spot, is open; a
quiet net's pad, or one with nothing placed to join, takes any way out as
toward. The search charges a candidate `score.escape_closed` for each pad
whose last way out toward its target it takes, `score.escape_walled` for
each pad it leaves no way out at all (its neighbours' pads and its own),
and `score.escape_crossed` for each of its airwires crossing another net's
airwire from the same neighbouring part within `escape_depth` of that
part's pads.

**Confirmed for the score.** The run score counts only what a grid path
search confirms (Ben, 2026-09-24): for each pad the corridors call closed
or walled, a path at the net's track width and clearance from other nets'
copper, in 0.05 mm cells over a window `escape_depth` round the pad, to the
window's edge (facing the target, for closed) or to a spot where a via fits
clear of every other net's copper. Obstacles are taken as their boxes.

`place.escape_pads` (1: every part) limits escapes to parts with at least
that many pads.

### Measurements (task 5)

The bench, confirmed counts: walled pads, signal crossings, HPWL.

| | default | solve | physical |
|---|---|---|---|
| escapes off | 75, 226, 1456 | 60, 219, 1506 | 75, 156, 1282 |
| on, every part | 47, 226, 1428 | 53, 200, 1549 | 51, 175, 1314 |
| on, parts of 3+ pads | 40, 229, 1431 | 48, 201, 1548 | 57, 185, 1318 |

Every part is the default: walled pads -29%, crossings 601 -> 601, HPWL
about +1%, default resolve 87 s against 0.32.2's 65 s. The depth stays
1 mm without a sweep: the confirmed count is measured within that window,
so counts at different depths do not compare.

The router, quick mode, on the fairing MCU cell: escapes off 93.6% closure
with 5 nets open, on 94.9% with 4 (crossings 42 and 48); with the first
design, the core went from 75.3% (55 open) to 76.6% raw (52 open).

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

A cleanup step after the moves. Each movable part is offered a swap with
its `cleanup.swap_neighbours` (4) nearest movable neighbours on its face,
and with every part identical to it (courtyard size and pad count) at any
distance, as the pass always swapped identical parts. Movable: searched
parts, and block satellites within their limit. Fixed, edge, lock-held and
explore-focused items do not move. (Cells as units are not in this stage:
see "Not yet".)

For a pair:

1. A first look, neither part lifted: the two exchanged centre on centre in
   their own turns, on wire, links and crossings. Only a pair that gains
   there goes on.
2. Lift both: their room is free, the ratsnest and the escapes forget
   their pads.
3. Search the larger (by body area) round the smaller's old spot, within
   `cleanup.swap_radius` (1 mm), in every rotation it may take, scored by
   the cost, legal against everything else.
4. Search the smaller round the larger's old spot, in what is left.
5. Keep the swap only when the cost of the two falls and no limit is
   broken. Otherwise put both back.

Moves and swaps alike weigh a part lifted, so where it stands and where it
might go are judged the same way. A spot whose wire alone reaches the best
cost seen is not weighed further (crossings and escapes can only add), in
the search as in the cleanup; outside explore, which draws among spots near
the best and needs every one weighed.

**Deferred.** Pushing small neighbours aside to make room for the larger
part is not in this stage. It needs chains of moves, each judged.

### Measurements (task 6)

The bench, against task 5 (walled, crossings, crossed escapes, HPWL, s):

| | default | solve | physical |
|---|---|---|---|
| task 5 | 47, 226, 127, 1428, 87 | 53, 200, 116, 1549, 66 | 51, 175, 78, 1314, 67 |
| cleanup, first cut | 0, 164, 46, 1825, 447 | 0, 165, 40, 1939, 324 | 0, 114, 37, 1577, 341 |
| + swap radius, first look, pruning | 0, 172, 56, 1672, 78 | 4, 154, 55, 1833, 63 | 8, 124, 43, 1451, 60 |

HPWL rises 8-17% as the pass trades wire for crossings and escapes at the
chosen weights. The router, quick mode, on the fairing core (scratch copy):
the MCU cell 94.9% closure and 4 nets open at task 5, 97.4% and 2 open now,
with 48 -> 37 crossings; the core 76.1% raw (53 open) against 75.2% (55
open), crossings 1,120 -> 1,083, within what one quick route varies.

## Findings

- **Crossed escapes.** Two ratsnest edges of different nets that start at
  pads of the same part and cross within `escape_depth` of that part's
  pads. For example: "U2 pins 3/4: L2 VDD_RF crosses C2 MCU_EN".
- **Walled-off pads.** A pad the path search confirms has no way out. For
  example: "U2 pin 6 (VDD_RF): walled off by L2, C2".

## Preview

`preview --no-tags` draws the view without annotation tags, with `--zoom`,
`--around` or the whole board. The notes are still printed.

## Not yet

- Cells as units in the cleanup pass and its swaps.
- Pushing neighbours aside for a swap (above).

## Where it stands (task 9)

The fairing core at 1492f4d, a fresh scratch copy of each run, 0.32.2 (the
fairing's own install) against this code, quick routing:

| | 0.32.2 | now |
|---|---|---|
| MCU cell: crossings, airwire | 43, 191.4 mm | 37, 195.5 mm |
| MCU cell: route closure, nets open | 98.7%, 1 | 97.4%, 2 |
| MCU cell: findings | 5 link | 6 link, 5 crossed escapes, 0 walled |
| Core: crossings, airwire | 1,035, 2,055 mm | 1,106, 2,367 mm |
| Core: route closure, nets open | 74.3%, 57 | 78.8%, 47 |
| Core: resolve | 174 s | 72 s |

Against "Done when" below: no pad is walled off and every satellite is on
its normal or within its limit; the MCU cell's crossings fall 43 -> 37,
short of 34; five crossed escapes remain at the flash bus's pins (29-34);
one bypass link (C8-L2) ends 0.11 mm past its limit. On the core the
router closes more nets but the crossings and the airwire rise. The one
quick route per case varies by a net or two run to run, so the MCU cell's
difference is within it; the core's ten nets are likely not.

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
