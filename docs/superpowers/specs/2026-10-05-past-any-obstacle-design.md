# Past any obstacle

Approved direction (2026-10-05), part 1: `Past(items, edge)` and
`Past(items, Corner.X)` accept a cutout, a stretch of the board edge, a
part's or a cell's envelope, and a label, as well as pads, vias and tracks.
The point stands off each item by the clearance the board's rules give that
pair. Declared copper that comes nearer a hole or the board edge than the
board's rules allow is a finding when the copper is planned.

## Goal

A board declared a 3 A track on B.Cu that had to pass a round vent,
`Cutout(Circle(1.5), "vent", at=Near(PadRef(...)))`. Past took only pads,
vias and tracks, so the script could not say "pass the vent on its west
side". The track was drawn across the hole, and only DRC reported it, as
`copper_edge_clearance` at 0.0 mm. With this change the script writes

```python
vent = Cutout(Circle(1.5), "vent", at=Near(PadRef(Part("q1"), 2)))
board.rect(40, 30, holes=[vent])
board.track(Net("VBUS"), [PadRef(Part("j1"), 1), Past([vent], Edge.WEST), PadRef(Part("q1"), 2)],
            layer=CopperLayer.B)
```

and the waypoint lands half the track's width plus the board's copper-to-edge
clearance west of the hole. The run that drew the track across the hole now
says so itself, as a `copper.edge` finding naming the track and the vent.

## What it is not

- Tracks do not route round obstacles on their own. A Past is a waypoint
  the script places; the legs between waypoints are drawn as today. A leg
  that cuts a hole or the edge is reported (`copper.edge`), not moved.
- Keepouts, rule areas and seal regions are not Past items.
- Past over pads, vias and tracks alone resolves to the same point as
  today, to the nanometre.
- No new settings. Every stand-off is a board rule already read
  (`BoardGeometry`) or zero.

## Today

`values.Past` (values.py 884-948) checks that its items are `PadRef`,
`CellPadRef` or a via or track `CopperIntent`. `Board._check_past`
(layout.py 5585) checks that they are this board's. A track point
(layout.py 5448, 5472) and a via's `at=` (5828, 5849) resolve through
`_past_point` (11494): `_past_reach` (11461) takes the union of the items'
copper boxes and `width/2` plus the worst clearance by net pair
(`_pad_clearance`, which is `Board._clearance`: a declared rule, else the
net-class pair, else the board default). The point is that far out from the
box's `edge` side (or along the outward diagonal from its corner), across it
where `across=` says, and rounded away by `_round_away`. Items on every
layer count for the point; only the corner verdict (`copper.corner`,
layout.py 5527) filters by the track's layer. `_refs_in` (11693) makes the
copper wait for the items' pads and vias' pads. In `Beside`'s align,
`_check_beside_past` (2415) allows pads only, since a placement is decided
before any copper is planned, and `Board._beside_placement` (2561, the
"past" branch at 2610) uses `_lane_distance` for the stand-off and `lane=`.

## Items

What a script passes, and what each one contributes.

| item | handle the script passes | box | stand-off from it |
|---|---|---|---|
| pad, via, track | as today | copper boxes, as today | the net-pair clearance, as today |
| cutout | the `Cutout` value given to `holes=`, or `board.cutout(name)` | the hole's loop | `geometry.edge_clearance` |
| board edge | a `Run`: `board.edge(facing=)` or one of `board.edges(facing=)` | the run's points | `geometry.edge_clearance` |
| a stretch of a hole | a `Run` from `board.cutout(name).edge(side=)` | the run's points | `geometry.edge_clearance` |
| part or cell | `Part(...)`, `Cell(...)` | its placed envelope, and its pads as copper | 0 from the envelope; its pads as if named |
| label | the key `board.label(...)` returns | the text's box | 0 for a track; `geometry.silk_clearance` for a via |

**Box, not outline.** Each item gives its box, as a pad does today, for
three reasons. On an `Edge` the box's side is the shape's own extreme on that
axis (the west side of a round hole's box is the hole's westmost point), so
the point is the same as it would be off the real outline. A combined box is
how `edge` already reads several items, and a mix of kinds must read the
same way. And `across=`'s `Along` is a fraction of the box's side. The cost
is at a `Corner` of a round or rounded item: the box's corner stands outside
the curve, so a 45 through the point passes the curve further out than it
must, by `r * (sqrt(2) - 1)` for a circle of radius `r` (0.31 mm for the
1.5 mm vent).

A cutout's loop and a curved run are flattened into chords that cut up to
`geometry.arc_sag` inside the true arc, and KiCad judges the arc. Their box
is grown by `geometry.arc_sag` where the loop or run has an arc, as
`_cutout_silk` already holds silk off a hole.

**Stand-offs.** The pair's rule as KiCad judges it:

- *A cutout and the board edge.* Copper to Edge.Cuts is
  `EDGE_CLEARANCE_CONSTRAINT` (KiCad
  `drc_test_provider_edge_clearance.cpp`, `testAgainstEdge`), whose value on a
  placemat board is the design setting `m_CopperEdgeClearance`, read into
  `geometry.edge_clearance` (kicad/read.py 833). A cutout is an Edge.Cuts
  loop, so the same figure applies. placemat writes no custom edge rule
  (rules.py has clearance rules only) and the fab profile carries no edge
  figure, so this one number is the rule.
- *Copper.* The net-pair clearance, as today.
- *An envelope.* No copper rule touches a courtyard. The envelope stands
  off at 0, and the part's pads join the copper items, so they keep their
  net-pair clearance as if the script had named them.
- *A label.* KiCad has no rule between copper and silk. A track stands off
  at 0. A via's ring is a mask opening, and silk keeps
  `geometry.silk_clearance` from a mask opening, so a via's `at=` stands off
  by that.

**Runs.** A `Run` is a stretch of a boundary with the bearing
(`facing`) of the side the void is on. Past keeps to the other side: its
`Edge`, or its `Corner`'s outward diagonal, must point within 45 degrees of
`facing + 180`. `Past([board.edge(facing=Edge.WEST)], Edge.EAST)` is the
clearance inboard of the west edge; `Edge.WEST` there is a declaration
error. A straight run's box is a line, so `across=` slides along it as along
any side.

The whole outline is not an item. Its box's sides are the board's extreme
stretches, which `board.edge(facing=)` already names, and inboard of
"the outline" says no side.

## Mixed items

Items fall into groups. Pads, vias and tracks (a part's pads included) are
one group, measured exactly as today: their combined box and the worst
net-pair clearance. Every other item (a cutout, a run, an envelope, a label)
is a group of its own: its box and its stand-off.

- `across=`'s `Along` reads the union of every group's box.
- On an `Edge` the point stands far enough out to clear every group. On
  `Edge.WEST`, `x = min over groups (box.left - w/2 - stand-off)`; the
  others in kind. With copper alone this is today's formula.
- At a `Corner` the point is on the outward diagonal from the corner of the
  union box, at the least distance for which, for every group `g`,
  `sx*x + sy*y >= sx*cx_g + sy*cy_g + (w/2 + stand-off_g) * sqrt(2)`, with
  `(cx_g, cy_g)` the group's own corner. A 45 through the point then passes
  every group's corner at least at its stand-off. With copper alone this is
  today's point.

`w` is the track's width, or a via's size (`_past_point` is already given
the via's size for that).

## across= and lane=

`across=` takes, as well as a `PadRef`, a via and an `Along`, a cutout, a
`Part` or a `Cell`: the point lies on the centre line of that item's box. A
`Run` and a label take none (a run's middle is `Along.MID` of its box
already; a label has no axis worth naming). A `Corner` still takes no
`across=`.

`lane=` stays Beside's alone. In `Beside`'s align a Past takes pads (as
today), cutouts, board-edge runs, parts and cells. The own pad stands past
them by the same per-group rule with the own pad's net in the track's
place: copper to a cutout or a run is `edge_clearance`, to an envelope 0.
With `lane=` a net, each group's distance is
`stand-off(group, lane) + lane width + clearance(lane, own pad)`, the form
`_lane_distance` uses for pads; the Corner form in that branch takes the
same per-group reach. Vias, tracks and labels stay refused in Beside's
align: copper is not planned yet, and a label gives way to parts placed
after it.

## When each kind is resolved

A Past is resolved inside the plan of the copper that holds it. Fixed
copper is planned once the firm pass (`place_ranked(RANK_FIXED, RANK_EDGE)`,
layout.py 7405) has put down every decided item and then every hole with a
freedom ("holes first", layout.py 7386); copper whose owners include a
searched part is planned after the search. The copper rooms the search
keeps (`_rooms_after`) run the same plan, so they see the same point.

| kind | known | the copper waits by |
|---|---|---|
| cutout at a decided place | at declaration (`_settled_cutouts`) | nothing |
| cutout with a freedom (`Near`, a free axis) | in the firm pass, before any copper | nothing: every hole is down before copper is planned |
| board-edge run | at declaration | nothing |
| part or cell envelope | when it is placed | the item, through `_refs_in` (it already treats a Part or Cell as a ref) |
| label | when its item is placed, and again whenever it gives way | the copper is planned after the search (`_late_copper`) |

Copper naming a label is planned late because a label gives way to every
part placed after it (`_labels_give_way`), so only after the search is its
place final. Such copper is no obstacle to the search; a label is silk, and
nothing needs that copper to be.

## Layers

The point is taken off every item named, whatever layer or face it is on,
as it is today for pads: a script that names an item wants to pass it.
What the layer changes is the corner verdict (`copper.corner`), which
judges only the groups whose rule applies on the track's layer:

- a cutout and the board edge cut every layer, so always;
- an envelope and a label never (their stand-off is 0 and no rule judges
  them against copper);
- copper as today.

So a B.Cu track past a part on the front takes its point off the part's
envelope and its pads' clearance, and the corner verdict judges only the
pads on B.Cu (a through-hole pad's copper is on both).

## Copper near a hole or the edge

Declared copper that comes nearer the board's outline, a cutout or a
drilled hole than the board's rules allow is a finding when the copper is
planned. Today only DRC reports it, after the board is written. The copper
is still drawn, as it is for `copper.meets` and `copper.keepout`: the
finding names the declaration, and the script moves it.

**What is judged.** Every op `_plan_copper_batch` lays (layout.py 8484):
a track's pieces after bridging, a via, a pour (fitted or not), and a
finger's pieces. A `Zone` (a plane) is skipped, as the loop already skips
it for `copper.meets`: KiCad's filler pulls a zone back from the edge and
from holes itself. The copper an adopted route draws, and the tails of
vias that gave way, are not declared copper and are not judged here.

**Where it sits.** In the loop over `all_ops` in `_plan_copper_batch`
(layout.py 8561-8597), beside the `occ.copper_conflicts(shape, check=True)`
call, on the same `shape = _shape_of(op)`: the copper's real outline,
width included (a track's polygon, a via's ring, a pour's polygon grown by
half its stroke). It runs only in that batch, so the copper rooms the
search plans dry raise nothing.

**The edge.** Each loop of `_edge_loops(occ)` (layout.py 11292): the
outline and every cutout, named or raw. The gap is `loop_gap(shape.poly,
loop)` (cutouts.py 312), the shortest distance between the copper's outline
and the loop; copper that crosses the loop has gap 0, and so does copper
wholly inside a hole or outside the outline (tested by `cutouts.inside` on
one of its points). The rule is `EDGE_CLEARANCE_CONSTRAINT`, KiCad's
`copper_edge_clearance`, `geometry.edge_clearance`
(`drc_test_provider_edge_clearance.cpp`, `testAgainstEdge`, which collides
the copper's shape with each Edge.Cuts shape at the clearance less
`m_epsilon`). A loop's chords stand up to `geometry.arc_sag` inside its
arcs, so where the loop has arcs the need is the clearance plus
`geometry.arc_sag`, as `_cutout_silk` holds silk. The gap is compared with
`occ.clear_limit(need, check=True)`, which takes KiCad's DRC epsilon off as
the other copper findings do.

**Drilled holes.** A part's plated holes (`hole_shape`, kind `hole`) and
its unplated holes (kind `npth`) are already in the occupancy, and
`Occupancy._conflict` already judges them against copper:
`_hole_conflict` (occupancy.py 2396) at `HOLE_CLEARANCE_CONSTRAINT`,
KiCad's `hole_clearance` (`geometry.hole_clearance`), skipping a plated
hole of the copper's own net; and the NPTH branch (occupancy.py 2355),
`npth_cuts` where they overlap and `npth_near` under the hole clearance.
What leaves them out of the finding is `copper_conflicts`'s filter to pads
and copper (occupancy.py 979). The check passes a part's `hole` and `npth`
shapes as well when `check=True`; placement's own calls keep the filter.
A via's hole is in `occ.copper` already and is judged there today. These
hits are `copper.meets`, the cause a via's hole against copper already
gives, with their refusal (`hole_copper`, `npth_near`, `npth_cuts`), which
carries the hole, the gap and the need. placemat reads an NPTH as round
(`Footprint.npth`, a centre and a drill), so KiCad's edge rule for an oval
NPTH (`drc_test_provider_edge_clearance.cpp` 388-393, an NPTH whose drill is
not round is an edge) does not apply here.

**The finding.** `copper.edge` (`FindingCause.COPPER_EDGE`, kind
`copper`), one per op and loop.

Severity: critical, the copper kind's default. Recommended because
`copper_edge_clearance` is one of the DRC kinds a board is judged by
(`DEFAULT_REAL_KINDS`, settings.py 25), so the board fails on it whatever
placemat says; the finding says so earlier and names the declaration.

Facts:

| fact | value |
|---|---|
| `key` | the declaration's `copper_id`, as `copper.meets` finds it |
| `net` | the copper's net |
| `word` | `track`, `via`, `pour` or `finger` |
| `layer` | the op's layer name, `""` for a via |
| `obstacle` | `{"form": "outline"}` or `{"form": "cutout", "name": ...}`, the name `None` for a raw hole |
| `inside` | true when the copper lies wholly inside a hole or outside the outline |
| `at` | the copper point nearest the loop, (x, y) |
| `gap_mm` | the gap measured |
| `need_mm` | `geometry.edge_clearance` |
| `rule` | `copper_edge_clearance` |

Rendered in finding_text.py beside `copper.meets`:

> track VBUS on B.Cu: 0.00 mm from cutout "vent" at (18.62, 12.40), under
> the board's 0.50 mm copper-to-edge clearance

with "the board's edge" for the outline, and "lies inside cutout "vent""
or "lies off the board" when `inside` is true. Its suggestion, like
`copper.meets`'s, points at the declaration; for a track whose script
names no Past for that cutout, it offers one (`Past([vent], Edge.X)` on the
side the track's nearest point lies).

## Errors

Declaration errors (`TypeError`/`ValueError`, raised by `Past` or by
`_check_past`), each naming the item:

- an item of another kind: the message lists the kinds;
- a `Cutout` that is not one of this board's named cutouts, a label of
  another board;
- a `Run` whose `Edge` or `Corner` points into its void, with the side that
  would stay on the board;
- `across=` a run or a label;
- in `Beside`'s align, a via, a track or a label; and a cutout with a
  freedom, since a `Beside` placement is firm and goes down before the
  board slides its holes.

Findings at plan time: the copper is not drawn, with `copper.not_drawn`
variant `past` as today, and its `why` a new refusal:

| code | when | facts |
|---|---|---|
| `past_cutout_unplaced` | the cutout found no place (`fixed.cutout`) | `name` |
| `past_item_unplaced` | the part or cell found no place | `item` |
| `past_label_not_drawn` | the label was not drawn (`label.not_drawn`) | `key` |
| `past_off_board` | the point lies off the board or in a hole | `at`, `edge`, `names` |

`past_off_board` is new for every Past, copper alone included. Each
refusal is rendered in refusals.py beside the four `past_*` codes there
now.

## Testing

Synthetic boards (`tests/fixtures.board_geometry`). Past in
`tests/test_past_obstacles.py`, each case asserting the exact point:

- **Cutout.** A round hole and a slot: `Past([hole], Edge.WEST)` is
  `box.left - arc_sag - edge_clearance - w/2`, rounded away, centred on the
  hole; the same with `board.cutout(name)`; a hole with a freedom
  (`at=Near(...)`) resolves where it settled.
- **Board edge.** `Past([board.edge(facing=Edge.WEST)], Edge.EAST)` is
  `edge_clearance + w/2` inboard; `Edge.WEST` there is refused; a run of a
  round board's rim takes the grown box.
- **Envelope.** A part whose pad reaches nearer its courtyard than the
  clearance: the pad's clearance wins; a searched part makes the copper
  wait for it.
- **Label.** A track and a via past a label, with the via held
  `silk_clearance` off; a label that gives way during the search is passed
  where it ends.
- **Mixed.** A pad and a cutout: on an edge the outer group sets the point;
  at a corner each group's corner is passed at least at its stand-off, and
  the `copper.corner` verdict names the group a short chamfer passes too
  near.
- **Unchanged.** Every case in `test_past_copper.py`, `test_past_corner.py`,
  `test_past_corner_layer.py` and `test_beside_lane.py` passes unchanged,
  and the bench tallies match the baseline.
- **Layers.** A B.Cu track past a front part: the point off its envelope
  and its pads; the B.Cu pads alone judged at the corner.
- **across=.** On a cutout's centre line, in a mix with a pad.
- **Beside.** `align=(own_pad, Past([cutout], Edge.WEST, lane=Net(...)))`
  stands the own pad `edge_clearance + lane width + clearance` off the hole;
  a cutout with a freedom there is refused.
- **Errors.** Each declaration error and each refusal above, by its code
  and facts.
- **The reported case.** A 3 A track on B.Cu from a pad west of a 1.5 mm
  round vent placed `Near` a pad, `Past([vent], Edge.WEST)`: the point is
  where the formula says, no `copper.edge` finding, and KiCad's DRC on the
  written board reports no `copper_edge_clearance`. Then on the module that
  reported it, as a fixture, before release.

The edge check in `tests/test_copper_edge.py`:

- **The reported case.** The same board with the track drawn straight
  across the vent: one `copper.edge` finding, critical, with `key` the
  track's, `layer` `B`, `obstacle` the cutout `vent`, `gap_mm` 0.0 and
  `need_mm` the board's `edge_clearance`; the track is in `plan.copper`.
- A track 0.1 mm inside the clearance from a straight outline side gives
  the finding with that gap; one exactly at the clearance gives none.
- A via wholly inside a cutout: `inside` true, gap 0.
- A track near a round cutout at the clearance plus half `arc_sag`: a
  finding (the arc's allowance), and none at the clearance plus `arc_sag`.
- A pour, fitted and declared by points, against the outline; a plane gives
  none.
- A track under `hole_clearance` from a part's NPTH, and from a plated hole
  of another net: `copper.meets` with `npth_near` and `hole_copper`; a
  plated hole of the track's own net gives none.
- Placement unchanged: the bench tallies match the baseline, since only the
  checking path widens `copper_conflicts`.

## Docs

**api.md, "Lane waypoints".** The paragraph beginning "`Past(items,
Edge.EAST, across=None)`" becomes:

> `Past(items, Edge.EAST, across=None)` is a point held off the `edge` side
> of some items. `items` are pads (`PadRef`/`CellPadRef`), vias, tracks,
> cutouts (the `Cutout` given to `holes=`, or `board.cutout(name)`),
> stretches of the board edge or of a hole (`board.edge(facing=)`,
> `board.cutout(name).edge(side=)`), parts and cells, and labels (the key
> `board.label()` returns), in any mix. Each is read as its box. The point
> stands half the track's width plus the pair's rule off each: the net-pair
> clearance from copper, the board's copper-to-edge clearance from a hole or
> the edge, nothing from a part's envelope (its pads keep their clearance)
> or a label (a via keeps the silk clearance). Off a stretch of edge the
> point is on the board's side of it. `across=` a pad, a via, a cutout, a
> part or a cell puts the point on its centre line, an `Along` at that point
> of the combined box's side. The point waits for what it names to be
> placed or planned; copper past a label is planned after the search. A
> Past whose item found no place, or whose point lands off the board, is
> not drawn, and the finding says which.

The Corner paragraph adds that each item's corner is passed at least at its
own stand-off. The Beside paragraph at api.md 874 replaces "the Past takes
pads only" with the kinds Beside's align takes and why the others are
refused. The quick-reference rows at api.md 121, 122 and 125 add
`Past([vent], Edge.WEST)` and `Past([board.edge(facing=Edge.WEST)],
Edge.EAST)`.

A paragraph after "Lane waypoints", **Copper near a hole or the edge**:

> Declared copper (a track, a via, a pour, a finger) nearer the board's
> outline or a cutout than the board's copper-to-edge clearance is a
> `copper.edge` finding when it is planned, naming the declaration, the
> hole or the edge, the gap and the clearance. Copper nearer a part's
> drilled hole than the hole clearance is `copper.meets`, as a via's hole
> is. The copper is drawn either way; a `Past` off the cutout or the edge
> is the usual way to move it. A plane is not judged: KiCad's fill keeps
> its own clearance.

`copper.edge` gets its row in the findings table beside `copper.meets`.

**migration.md, under "Unreleased", "New":**

> - **Past passes any obstacle.** `Past(items, edge)` and `Past(items,
>   Corner.X)` take cutouts, stretches of the board edge, parts and cells,
>   and labels, as well as pads, vias and tracks. The point keeps the
>   board's copper-to-edge clearance off a hole or the edge, and stands on
>   an envelope's or a label's outline. A track that had to pass a cutout
>   with a hand-placed point can name the cutout. A Past whose point lands
>   off the board is now a `copper.not_drawn` finding (`past_off_board`).
>   Past over pads, vias and tracks alone resolves as before.
>   `board.label()` returns a `LabelKey`, a `str`, so scripts that use the
>   key as text need no change.
> - **Copper near a hole or the edge is a finding.** Declared copper nearer
>   the outline or a cutout than the board's copper-to-edge clearance is a
>   critical `copper.edge` finding when it is planned, and copper nearer a
>   part's drilled hole than the hole clearance is `copper.meets`. Both
>   were DRC failures before and still are; a run now reports them itself,
>   naming the declaration, so a board that passed its findings may now
>   show these. The copper is still drawn.

## API changes

- `values.Past.__post_init__` accepts the new kinds; its error lists them.
- `board.label()` returns `LabelKey`, a `str` subclass, so a label can be
  told from any other string in `Past`.
- `Run` gains nothing: its `facing` already says which side the void is
  on.
- `FindingCause.COPPER_EDGE`, `copper.edge`.
- `Occupancy.copper_conflicts(check=True)` judges a part's `hole` and
  `npth` shapes as well.
