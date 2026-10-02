# Vias held out of keepouts; copper a via draws held to the edge and the cell's rules

Follows `2026-10-02-keepout-courtyard-design.md`. Placing a real board with that change moved a few cells, and
three things the old arrangement had hidden came out in KiCad's DRC.

## A keepout that forbids vias

A keepout was reserved against parts only (`Reservation`), and a script's own vias were checked against one
(`_check_keepouts`, `_via_site_why`), but a carried via - one a part or a stamped cell brings - never was. KiCad
flags a via whose ring on a layer a rule area covers overlaps it (`pcbexpr_functions.cpp` `collidesWithArea`,
the via branch: the area's outline, deflated by the DRC epsilon, against the via's effective shape on each
common layer; `drc_test_provider_disallow.cpp` `checkDisallow` reports `items_not_allowed`), unless its net is
let through.

A rule area that forbids vias is an obstacle, a shape of kind `viaban` (`occupancy.ban_shape`) that only a via
ring (a `through` shape no footprint owns) meets: on a layer the area covers (none listed: every layer) and
whose net is not among the nets the shape lets through (its `net`, joined by `\x1f`). It lives in
`Occupancy.copper`, so the native and Python searches, the give-way's move search and the item's own shapes all
see it, with `Occupancy._conflict` and `native/src/shapes.rs` `conflict` as the one rule:

- a keepout declared to exclude vias adds one when it is placed;
- a rule area on the generated board that forbids vias adds one at the start;
- a stamped cell's rule area is copper of that cell (owner: the cell, label: its name), so it moves with the
  cell and is an obstacle from when the cell lands; the cell's own `parts` lists leave it out. A cell's region
  is met by a via placed earlier through the first step of the give-way, which now includes the cell's `viaban`
  shapes among the shapes its placement stands on.

A via in one gives way as for any other conflict (share, move, leave, shorten, drop); where none clears it the
spot is refused: "keepout 'name' forbids vias: the GND via at (x, y) is inside it; it cannot give way". A hole in
a rule area is not modelled: the area's outline is used whole, which refuses a via in the hole that KiCad would
accept.

## Copper a via draws keeps the edge

The search judges an item less its carried vias, and `_Judge.hit` held a via's ring to the board's edge but
never its track, so a cell's carried track could cross a cutout or lie inside the keep-in. `hit` and `_tail_hit`
now judge a carried via's track, and a track giving way draws (`given`), against `Occupancy._edge_why` as the
item's own copper is. A move whose narrowest tail the native search found clear was taken at the narrowest
width even when `_widest` found no width clear; it now goes on to the next offset.

## A tail joins the cell's group

A cell's clearance rule is written `A.memberOf('cell') && B.memberOf('cell')`. A tail drawn by a via's giving
way was added to the board with no group, so placemat judged it against the cell's rule and KiCad's DRC against
the netclass. `kicad.write._group_given_way_tracks` puts the tails and rebuilt tracks in the group of the cell
the via belongs to.

## Run time

On the board that exposed these, the cell placed after the arrangement moved took about 1500 s in the via give-way
against 22 s: 1400 distinct candidates in the first 900 s at about 0.55 s each (a search of up to 314 offsets per
via, Python-judged where a net tie is near), none repeated; a harder placement, not a repeated search.
`_courtyard_hit` rejects by box before building a polygon, which was a tenth of that time.

## Verification

`tests/test_via_keepout_give_way.py` (a via moves out, stays where the region does not reach or lets its net
through, is refused where it cannot, the generated-board and stamped forms, a via placed earlier, native and
Python agree, and kicad-cli's `items_not_allowed` agrees with the ring test at three distances; a carried track
across a cutout refuses the spot) and `tests/test_vias_give_way_kicad.py` (the tail is in the group).
