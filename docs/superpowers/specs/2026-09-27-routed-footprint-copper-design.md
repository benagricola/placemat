# Footprint copper through the router

Date: 2026-09-27
Status: approved 2026-09-27
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-27 "the router moves a
net-tie footprint's outer copper to silk"

## The problem

A footprint can carry copper graphics of no net: a net-tie footprint's
winding drawn as `fp_poly` on every copper layer, a copper logo. The router
(KiCadRoutingTools) does two things with them:

- It does not see them. Its parser reads a footprint's graphics only on
  Edge.Cuts (`kicad_parser.py`, the `fp_poly` scan near line 1640), so it
  routes through a winding's copper as if it were not there.
- Its writer moves every net-less graphic on F.Cu or B.Cu to F.SilkS or
  B.SilkS (`kicad_writer.move_copper_graphics_to_silkscreen`, from
  `output_writer.py:83`), footprint graphics included. Inner layers keep
  theirs.

So the routed copy has lost the windings' outer-layer copper, and placemat's
DRC of that copy is clean because the copper it would have met is gone. On
the ring test board every winding lost L1 and L6.

placemat does not change the router (it is used as is); it owns the copy it
hands the router and the copy it reads back.

## The change

1. **Before routing, keep the router off footprint copper.** For each
   net-less copper graphic of a footprint on a layer the route uses, the
   router's input copy gains a rule area on that layer forbidding tracks and
   vias, drawn as the graphic's own outline (placemat reads these already:
   `Footprint.copper`). The router honours rule areas; placemat already
   checks that it did (`router_breaches`).
2. **After routing, put the copper back.** Each footprint's graphics in the
   routed copy are replaced by the input's (matched by footprint UUID, the
   graphic items only: pads and fields are the router's copy's), and the
   rule areas step 1 added are removed. The routed copy is then the router's
   copper beside the footprints as they were.
3. **DRC after routing is of that copy**, so a route that did cross footprint
   copper (on a layer step 1 did not cover, or where the rule area was
   breached) shows as the clearance or short it is.
4. **The route report counts it:** `restored_graphics` (footprints and
   items put back) in `route.json`, and a line in the route step when it is
   not zero.

## Verification

- KiCad test (no router run): a copy of the breakout with a net-less F.Cu
  `fp_poly` added to one footprint; the input-copy step gives a rule area
  over it on F.Cu; a "routed" copy made by moving that graphic to F.SilkS
  (as the router's writer does) and adding one track across it; after the
  restore step the graphic is on F.Cu again, the rule area is gone, and DRC
  reports the track against it.
- The existing route tests pass (they run the router where it is present).

## Not in scope

- Changing the router, or asking its maintainers to.
- Net-tied copper graphics: the router leaves those in place and models
  them.
