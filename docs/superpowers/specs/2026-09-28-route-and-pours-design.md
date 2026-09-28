# The router and the board's pours

Date: 2026-09-28
Status: draft
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-28 "which routed tracks
cross a pour's outline"; the board's report of 2026-09-28 that its outer
ground fills must be switched off for every routing run

## The problem

The router takes a zone's last fill as the obstacle, not its outline, which
cuts both ways:

- **A partial pour is cut apart.** An inner-layer power pour (VBIKE, VSHUNT,
  PP5V, VBUS on In2) is filled round what was there; the router lays other
  nets' tracks through its outline wherever the fill left room, and KiCad's
  refill then splits the pour round them. DRC passes, so nothing says so.
  The core routes on F.Cu and B.Cu only to avoid it.
- **A board-wide fill blocks the router.** An outer ground fill covers the
  whole layer, so the router finds no room on it; the board switches its
  F.Cu/B.Cu ground fills off in the script for every routing run and back
  on after.

## The change

Only the router's input copy changes; the board and the routed copy's zones
are placemat's as today.

1. **A partial pour keeps other nets' tracks out of its outline.** For each
   zone on a routed layer whose net the route leaves out (a plane net, as
   `plane_nets_of` finds them) and which covers less than
   `route.plane_share` of the board, the input copy gets a rule area on that
   layer over the zone's outline forbidding tracks (vias may pass: the pour
   is refilled round them), removed again from the routed copy as the
   footprint-copper guards are. A route through one is a keepout breach
   naming the pour.
2. **A board-wide fill does not block the router.** For each zone on a
   routed layer whose net the route leaves out and which covers at least
   `route.plane_share` of the board, the input copy's fill is cleared (its
   outline stays): the router routes as the refill will leave room, and the
   routed copy is filled again before its DRC, as today. The script need
   not switch its fills off.
3. **The route report** says how many pours it kept routes out of and how
   many fills it cleared, and the breaches name the pour.

## Verification

- KiCad tests (no router run): a copy with an In2-style partial pour of a
  plane net gets a track-forbidding rule area over its outline in the input
  copy, and none in the routed copy after the restore; a board-wide fill of
  a plane net has no filled polygons in the input copy and is filled again
  in the routed copy; a partial pour of a routed net is left alone.
- A router run (quick) on the breakout with a partial pour: no track of
  another net inside its outline.

## Not in scope

- Routing a plane net itself through its own pour.
- Pours on a layer the route does not use.
