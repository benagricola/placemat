# The router and the board's pours

Date: 2026-09-28
Status: approved 2026-09-28
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-28 "which routed tracks
cross a pour's outline"; the board's report of 2026-09-28 that its outer
ground fills are switched off for every routing run

## The problem

The router does not see copper zones when it routes other nets: its
obstacle map takes rule areas, not zones or their fills
(KiCadRoutingTools `py_router/obstacle_map.py:392`; a zone's fill is read
only for its own net's pour launch, `single_ended_routing.py:3235`).
Measured on the breakout (2026-09-28): a quick route with a filled GND zone
over the whole of B.Cu lays the same tracks as without it (12 segments,
54 mm on B.Cu, 12 vias, 78.6% closure both times).

- **A partial inner-layer pour is cut apart.** A power pour on an inner
  layer (a net's pour on In2 covering part of the board) gets other nets'
  tracks laid through its outline, and KiCad's refill splits the pour round
  them. DRC passes, so nothing says so. The board routes on F.Cu and B.Cu
  only to avoid it.
- **A board-wide fill does not block the router**, so switching a fill off
  for routing changes nothing the router does.

## The change

Only the router's input copy changes.

1. **A partial inner-layer pour keeps other nets' tracks out of its
   outline.** For each zone on a routed inner layer whose net the route
   leaves out (a plane net, as `plane_nets_of` finds them) and whose outline
   covers less than `[route] plane_share` of the board, the input copy gets
   a rule area on that layer over the zone's outline that forbids tracks
   (vias may pass: the pour is refilled round them). The rule area is named
   after the pour ("pour <net> <layer>"), and the routed copy has it
   removed again, as the footprint-copper guards are.
2. **A route through one is a keepout breach naming the pour**, through
   `router_breaches` as today.
3. **The route report** says how many pours it kept other nets' tracks out
   of.
4. **Docs**: api.md's route paragraph: inner-layer pours of excluded nets
   are kept clear of other nets' tracks; the router lays tracks through a
   board-wide fill and the refill carves round them, so fills need not be
   switched off for routing.

## Verification

- KiCad tests (no router run): an input copy with a partial In2 pour of a
  plane net gets a track-forbidding rule area over its outline on In2; the
  routed copy has none after the restore; a pour of a routed net, a pour
  covering at least the plane share, and a partial pour on F.Cu or B.Cu are
  left alone.
- A quick router run on the breakout with a partial inner-layer pour of an
  excluded net: no track of another net inside its outline.

## Not in scope

- Partial pours on F.Cu and B.Cu: other nets' surface pads sit inside them,
  and a track-forbidding area over a pad leaves the pad unroutable.
- Routing a plane net itself through its own pour.
