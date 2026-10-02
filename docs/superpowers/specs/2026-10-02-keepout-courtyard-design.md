# A keepout judges the courtyard KiCad tests

From one board's session on 0.79.0.

## Problem

A keepout that excludes parts passed two parts that KiCad's DRC flagged as
`items_not_allowed`, under `[place] envelope = "physical"`. placemat judged
the part's body box (`Footprint.body_box`: the courtyard less
`courtyard_excess`, with the pads), whatever the envelope.

## KiCad's rule

KiCad 10.0.0, pcbnew:

- `drc/drc_engine.cpp` 584-645 (`addKeepoutZoneRule`): a rule area becomes an
  implicit rule `A.intersectsArea('<uuid>')`, with the disallow flags of the
  area (`GetDoNotAllowFootprints` -> `DRC_DISALLOW_FOOTPRINTS`, line 640).
- `drc/drc_test_provider_disallow.cpp` 228-249 (`checkDisallow`): every item
  that matches the rule is `DRCE_ALLOWED_ITEMS` (`items_not_allowed`).
- `pcbexpr_functions.cpp` 502-571 (`collidesWithArea`): for a footprint
  (line 533), the area outline, deflated by the DRC epsilon, collides with
  `footprint->GetCourtyard( F_CrtYd )` (line 547) when the area is on a front
  layer, and with `GetCourtyard( B_CrtYd )` (line 562) when it is on a back
  layer; only `Outline( 0 )` is tested. A footprint with no courtyard is not
  tested (the code reports "Footprint has no front courtyard." to the rule
  editor and returns false).

So the shape is the courtyard polygon, never the body, pads or silk, and the
envelope has no part in it.

## Design

`Reservation.courtyard` marks a KiCad rule area: a `keepout()` that excludes
parts, a rule area the generated board carries, and one a stamped cell brings
(not a cell's label box, which is placemat's). Such a reservation judges each
footprint by its courtyard polygon, turned and placed as the item is
(`Occupancy._courtyard_hit`, `origin_yards`), against the region by polygon
overlap; a cell's own copper, which has no courtyard, is judged by its box as
before. The native sweep carries the flag and the per-turn polygons
(`NativeBoard.add_reservation(..., courtyard)`, `sweep(..., yards=)`) and tests
the same polygons.

A footprint that draws no courtyard is not tested by KiCad. placemat keeps it
out with its claimed courtyard box (as the lead check already does), which is
stricter than KiCad for that case only. The face rule is unchanged: a region on
one face keeps out the parts standing on that face and a part whose lead goes
through; KiCad tests a through-hole part's courtyard on its own face only.

## Verification

`tests/test_keepout_courtyard.py`: a part whose body is clear and whose
courtyard is 0.05 mm inside is refused, and one with its courtyard clear is
placed, under every envelope; kicad-cli's DRC agrees on both; the native and
Python sweeps place a searched part at the same spot. Full suite and the bench
for placement drift.
