# Past any obstacle

Approved direction (2026-10-05), part 1: `Past(items, edge)` and
`Past(items, Corner.X)` accept, as well as pads, vias and tracks, a cutout,
a keepout or rule area, a part's or a cell's envelope, a stretch of the
board edge, and a label. The point stands off each item by the clearance the
board's rules give that pair.

## Goal

A board declared a 3 A track on B.Cu that had to pass a round vent,
`Cutout(Circle(1.5), "vent", at=Near(PadRef(...)))`. Past took only pads,
vias and tracks, so the script could not say "pass the vent on its west
side", the track was drawn across the hole, and DRC reported
`copper_edge_clearance` at 0.0 mm. With this change the script writes

```python
vent = Cutout(Circle(1.5), "vent", at=Near(PadRef(Part("q1"), 2)))
board.rect(40, 30, holes=[vent])
board.track(Net("VBUS"), [PadRef(Part("j1"), 1), Past([vent], Edge.WEST), PadRef(Part("q1"), 2)],
            layer=CopperLayer.B)
```

and the waypoint lands half the track's width plus the board's copper-to-edge
clearance west of the hole.

## What it is not

- Tracks do not route round obstacles on their own. A Past is a waypoint
  the script places; the legs between waypoints are drawn as today and are
  judged by DRC.
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
before any copper is planned, and `Board._beside_placement` (2561, the "past" branch at 2610) uses
`_lane_distance` for the stand-off and `lane=`.

## Items

What a script passes, and what each one contributes.

| item | handle the script passes | box | stand-off from it |
|---|---|---|---|
| pad, via, track | as today | copper boxes, as today | the net-pair clearance, as today |
| cutout | the `Cutout` value given to `holes=`, or `board.cutout(name)` | the hole's loop | `geometry.edge_clearance` |
| board edge | a `Run`: `board.edge(facing=)` or one of `board.edges(facing=)` | the run's points | `geometry.edge_clearance` |
| a stretch of a hole | a `Run` from `board.cutout(name).edge(side=)` | the run's points | `geometry.edge_clearance` |
| keepout | what `board.keepout(...)` returns (`KeepoutIntent`) | its settled polygon | 0 |
| rule area | `board.rule_area(name, cell=)`, new | its polygon as placed | 0 |
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
- *A keepout or rule area.* A KiCad rule area has no clearance: copper it
  excludes may not overlap it (`drc_test_provider_disallow.cpp`;
  `Board._check_keepouts` reads it the same way, `polys_overlap`). So the
  copper's edge stands on the region's outline, held off it by
  `_round_away`. A keepout that does not exclude the copper's kind, or lets
  its net through, has no rule at all; its stand-off is also 0, so the
  point is the same whichever it excludes.
- *An envelope.* No copper rule touches a courtyard. The envelope stands
  off at 0, and the part's pads join the copper items, so they keep their
  net-pair clearance as if the script had named them.
- *A label.* KiCad has no rule between copper and silk. A track stands off
  at 0. A via's ring is a mask opening, and silk keeps
  `geometry.silk_clearance` from a mask opening, so a via's `at=` stands off
  by that.

A seal region is not a kind of its own: placemat has no seal declaration. A
seal land is declared as a keepout, or arrives as a stamped cell's rule area,
and is covered as one. A band round the rim has a box as large as the board,
so a whole-region Past over it lands off the board (see Errors); it is
passed by a stretch of its inner side (see Open question).

**Runs.** A `Run` is a stretch of a boundary with the bearing
(`facing`) of the side the obstacle is on: for the board edge and a hole,
the void. Past keeps to the other side: its `Edge`, or its `Corner`'s
outward diagonal, must point within 45 degrees of `facing + 180`.
`Past([board.edge(facing=Edge.WEST)], Edge.EAST)` is the clearance inboard
of the west edge; `Edge.WEST` there is a declaration error. A straight run's
box is a line, so `across=` slides along it as along any side.

The whole outline is not an item. Its box's sides are the board's extreme
stretches, which `board.edge(facing=)` already names, and inboard of
"the outline" says no side.

## Mixed items

Items fall into groups. Pads, vias and tracks (a part's pads included) are
one group, measured exactly as today: their combined box and the worst
net-pair clearance. Every other item is a group of its own: its box and its
stand-off.

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
keepout, a rule area, a `Part` or a `Cell`: the point lies on the centre
line of that item's box. A `Run` and a label take none (a run's middle is
`Along.MID` of its box already; a label has no axis worth naming). A
`Corner` still takes no `across=`.

`lane=` stays Beside's alone. In `Beside`'s align a Past takes pads (as
today), cutouts, keepouts, board-edge runs, parts and cells. The own pad
stands past them by the same per-group rule with the own pad's net in the
track's place: copper to a cutout or a run is `edge_clearance`, to a
keepout or an envelope 0. With `lane=` a net, each group's distance is
`stand-off(group, lane) + lane width + clearance(lane, own pad)`, the form
`_lane_distance` uses for pads; the Corner form in that branch takes the
same per-group reach. Vias, tracks, rule areas and labels stay refused in
Beside's align: copper is not planned yet, a cell's rule area moves with a
cell that may be searched, and a label gives way to parts placed after it.

## When each kind is resolved

A Past is resolved inside the plan of the copper that holds it. Fixed
copper is planned once the firm pass (`place_ranked(RANK_FIXED, RANK_EDGE)`,
layout.py 7405) has put down every decided item and then every hole and
keepout with a freedom ("holes first", layout.py 7386); copper whose owners
include a searched part is planned after the search. The copper rooms the
search keeps (`_rooms_after`) run the same plan, so they see the same point.

| kind | known | the copper waits by |
|---|---|---|
| cutout at a decided place | at declaration (`_settled_cutouts`) | nothing |
| cutout with a freedom (`Near`, a free axis) | in the firm pass, before any copper | nothing: every hole is down before copper is planned |
| board-edge run | at declaration | nothing |
| keepout | in the firm pass; one shaped from a part (`region_of`) when that part is | the part, through `_refs_in` |
| rule area of the generated board | at declaration | nothing |
| rule area of a cell | when the cell is placed | the cell's members, as owners |
| part or cell envelope | when it is placed | the item, through `_refs_in` (it already treats a Part or Cell as a ref) |
| label | when its item is placed, and again whenever it gives way | the copper is planned after the search (`_late_copper`) |

Copper naming a label is planned late because a label gives way to every
part placed after it (`_labels_give_way`), so only after the search is its
place final. Such copper is no obstacle to the search; a label is silk, and
nothing needs that copper to be.

A cell's rule area is read where it stands: occupancy keeps a placed
polygon only for rule areas that exclude parts (`_cell_rule_areas`,
occupancy.py 573 and 1376). It must keep one for every rule area of the
cell, moved by the same transform in `_commit_cell`.

## Layers

The point is taken off every item named, whatever layer or face it is on,
as it is today for pads: a script that names an item wants to pass it.
What the layer changes is the corner verdict (`copper.corner`), which
judges only the groups whose rule applies on the track's layer:

- a cutout and the board edge cut every layer, so always;
- a keepout or rule area on the layers it covers (`layers=None`: all), and
  only where it excludes the copper's kind and its net is not let through;
- an envelope and a label never (their stand-off is 0 and no rule judges
  them against copper);
- copper as today.

So a B.Cu track past a keepout that covers F.Cu alone takes its point off
the keepout's outline and draws no corner finding against it. A B.Cu track
past a part on the front takes its point off the part's envelope and its
pads' clearance, and the corner verdict judges only the pads on B.Cu (a
through-hole pad's copper is on both).

## Errors

Declaration errors (`TypeError`/`ValueError`, raised by `Past` or by
`_check_past`), each naming the item:

- an item of another kind: the message lists the kinds;
- a `Cutout` that is not one of this board's named cutouts, a keepout or a
  label of another board, a rule area name the board does not carry (the
  message lists the names, by cell);
- a `Run` whose `Edge` or `Corner` points into its void, with the side that
  would stay on the board;
- `across=` a run or a label;
- in `Beside`'s align, a via, a track, a rule area or a label; and a
  cutout or keepout with a freedom, since a `Beside` placement is firm and
  goes down before the board slides its holes.

Findings at plan time: the copper is not drawn, with
`copper.not_drawn` variant `past` as today, and its `why` a new refusal:

| code | when | facts |
|---|---|---|
| `past_cutout_unplaced` | the cutout found no place (`fixed.cutout`) | `name` |
| `past_keepout_unplaced` | the keepout has no place | `name` |
| `past_item_unplaced` | the part or cell found no place | `item` |
| `past_label_not_drawn` | the label was not drawn (`label.not_drawn`) | `key` |
| `past_off_board` | the point lies off the board or in a hole | `at`, `edge`, `names` |

`past_off_board` is new for every Past, copper alone included, and is what
a whole-region Past over a band at the rim gives. Each refusal is rendered
in refusals.py beside the four `past_*` codes there now.

## Testing

Synthetic boards (`tests/fixtures.board_geometry`), one file
`tests/test_past_obstacles.py`, each case asserting the exact point:

- **Cutout.** A round hole and a slot: `Past([hole], Edge.WEST)` is
  `box.left - arc_sag - edge_clearance - w/2`, rounded away, centred on the
  hole; the same with `board.cutout(name)`; a hole with a freedom
  (`at=Near(...)`) resolves where it settled.
- **Board edge.** `Past([board.edge(facing=Edge.WEST)], Edge.EAST)` is
  `edge_clearance + w/2` inboard; `Edge.WEST` there is refused; a run of a
  round board's rim takes the grown box.
- **Keepout.** A rectangle keepout: the copper's edge on its outline; one
  shaped from a part follows the part; one not excluding tracks gives the
  same point.
- **Rule area.** A generated-board rule area, and a cell's rule area after
  the cell is turned and placed.
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
- **Layers.** A B.Cu track past an F.Cu-only keepout: the point off the
  keepout, no corner finding; past a front part: the B.Cu pads alone judged
  at the corner.
- **across=.** On a cutout's centre line, in a mix with a pad.
- **Beside.** `align=(own_pad, Past([cutout], Edge.WEST, lane=Net(...)))`
  stands the own pad `edge_clearance + lane width + clearance` off the hole;
  a cutout with a freedom there is refused.
- **Errors.** Each declaration error and each refusal above, by its code
  and facts.
- **The reported case.** A 3 A track on B.Cu from a pad west of a 1.5 mm
  round vent placed `Near` a pad, `Past([vent], Edge.WEST)`: the point is
  where the formula says, and KiCad's DRC on the written board reports no
  `copper_edge_clearance`. Then on the module that reported it, as a
  fixture, before release.

## Docs

**api.md, "Lane waypoints".** The paragraph beginning "`Past(items,
Edge.EAST, across=None)`" becomes:

> `Past(items, Edge.EAST, across=None)` is a point held off the `edge` side
> of some items. `items` are pads (`PadRef`/`CellPadRef`), vias, tracks,
> cutouts (the `Cutout` given to `holes=`, or `board.cutout(name)`),
> stretches of the board edge or of a hole (`board.edge(facing=)`,
> `board.cutout(name).edge(side=)`), keepouts, rule areas
> (`board.rule_area(name, cell=)`), parts and cells, and labels (the key
> `board.label()` returns), in any mix. Each is read as its box. The point
> stands half the track's width plus the pair's rule off each: the net-pair
> clearance from copper, the board's copper-to-edge clearance from a hole or
> the edge, nothing from a keepout's or a part's outline (a part's pads keep
> their clearance) or a label's (a via keeps the silk clearance). Off a
> stretch of edge the point is on the board's side of it. `across=` a pad, a
> via, a cutout, a keepout, a rule area, a part or a cell puts the point on
> its centre line, an `Along` at that point of the combined box's side. The
> point waits for what it names to be placed or planned; copper past a label
> is planned after the search. A Past whose item found no place, or whose
> point lands off the board, is not drawn, and the finding says which.

The Corner paragraph adds that each item's corner is passed at least at its
own stand-off. The Beside paragraph at api.md 874 replaces "the Past takes
pads only" with the kinds Beside's align takes and why the others are
refused. The quick-reference rows at api.md 121, 122 and 125 add
`Past([vent], Edge.WEST)` and `Past([board.edge(facing=Edge.WEST)],
Edge.EAST)`. `board.rule_area(name, cell=)` gets its entry under the
keepout section.

**migration.md, under "Unreleased", "New":**

> - **Past passes any obstacle.** `Past(items, edge)` and `Past(items,
>   Corner.X)` take cutouts, stretches of the board edge, keepouts, rule
>   areas (`board.rule_area(name, cell=)`, new), parts and cells, and
>   labels, as well as pads, vias and tracks. The point keeps the board's
>   copper-to-edge clearance off a hole or the edge, and stands on a
>   keepout's, an envelope's or a label's outline. A track that had to pass
>   a cutout with a hand-placed point can name the cutout. A Past whose point
>   lands off the board is now a `copper.not_drawn` finding
>   (`past_off_board`). Past over pads, vias and tracks alone resolves as
>   before. `board.label()` returns a `LabelKey`, a `str`, so scripts that
>   use the key as text need no change.

## API changes

- `values.Past.__post_init__` accepts the new kinds; its error lists them.
- `Board.rule_area(name, cell=None) -> RuleAreaHandle`, matched on
  `RuleArea.base` and `RuleArea.cell`.
- `board.label()` returns `LabelKey`, a `str` subclass, so a label can be
  told from any other string in `Past`.
- `Run` gains nothing: its `facing` already says which side the void is
  on.

## Open question

**A band region's inner side.** A seal land round the rim is a keepout (or
rule area) whose box is the board's, so a whole-region Past over it is
useless. Recommended: in this part, add `.edge(side=)` and `.edges(side=)`
to keepout handles and `RuleAreaHandle`, returning `Run`s of the region's
boundary as `CutoutHandle.edge(side=)` does (a promise when the region has
no place yet, settled before any copper), with `facing` into the region,
so `Past([seal.edge(side=Edge.EAST)], Edge.EAST)` keeps a track inboard
of the band. Without it a band can only be passed with a `Location`.

**A track's legs against a hole.** Today only DRC reports a declared track
that comes nearer a hole or the edge than the copper-to-edge clearance;
the planner checks legs against other copper only. Recommended: a
separate, small change that makes it a plan-time finding, since a Past
fixes the waypoint but not the legs either side of it.
