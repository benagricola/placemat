# Copper tactics

Pours, traces, planes and the vias between them. Read before drawing copper -
round step 6.

## Copper tactics

8. **Polygons, not zones, for power** - hand-shaped filled polygons give full
   shape control with no clearance cut-outs. A pour must fully swallow every
   pad it joins; a pad edge poking out of its pour is wrong even when electrically
   fine. Outline stroke 0.2mm standard (the stroke is part of the copper -
   account for it in the vertices); thinner only where a tight pool needs it.
   **Every section of a pour carries the net's current**: the narrowest
   neck of a polygon must be at least the net's class width, and as wide as
   the current needs; a pour pinched to a 0.16 mm neck is worse than a
   trace because it reads as copper. Audit necks with the polygon audit
   tool before calling a cell done.
   No gratuitous small features: adjacent aligned pads get ONE covering edge,
   not per-pad wrapping - but a notch that steers around a foreign pad or via
   between pool members is functional, not clutter. Never delete a notch
   without checking what it clears.
9. **45 degrees everything** - chamfer right-angle jogs on traces AND polygon
   outlines. Corners belong at pads, not mid-field: exit a pad on the 45 when
   lengths are equal, and let the final segment into a pad ride the pad's AXIS
   to its centre (no off-axis skims). Keep 45s in round grid sizes.
   *Caveat*: two neighbouring nets' final approaches drawn at the SAME angle
   are parallel - the corridor between them has constant width everywhere, so
   if a via must land between them no via position (and no source-component
   translation) can ever fit; free the entry angles or bow one approach to
   open a wedge. Search placements and angles jointly, not vias alone.
10. **Neck pours to the job** - pad-width where a pour only serves a pin (a
   switch node radiates by area), full width where current is shared.
10b. **A sense line round the outside reserves the whole edge.** A feedback or
    sense trace hugging a cell's perimeter is the obvious route and it is
    expensive in a way the cell's own DRC cannot show: it makes the cell's
    far edge occupied for every board that ever stamps it, and boards
    discover that as a neighbour they cannot place. Look INWARD first. On a
    package with an exposed pad the annulus between that pad and the lead
    row is free board on the same layer (tactic 17's nuance), and a run
    through it is both shorter and hidden - the exposed pad is usually
    ground, so it references the run for most of its length. The rule
    generalises past sense lines: prefer the path that keeps a cell's
    OUTLINE clear, because the outline is the only part of a cell its
    consumers have to negotiate with.
11. **High-Z tiny, low-Z may travel** - keep high-impedance nodes (FB taps)
    microscopic at their pin; spend route length on low-impedance lines (a
    sense trace off a stiff pour), which may hug edges and pass near switching
    nets for a few mm.
12. **Every plane via sits on its pad** - via-in-pad above the fab's minimum
    pad size; below it, stub away to a via in open copper. A drop via floating
    in space is a defect. **Exception, the EP-grounded package:** an IC
    whose exposed pad is ground needs no via or stub on its other ground
    PINS. The EP takes the vias (one near each ground pin, more along a long
    EP), and the board's ground fill on that face joins each ground pin's
    pad to the EP across the sub-millimetre gap. A stub or a via per pin
    only crowds the pad corridor. In the cell's own DRC those pins read as
    unconnected; that is the accepted bucket, not a defect.
13. **Nothing routes what a plane carries, and modules do not route
    distributed power/ground.** The rule is the same at both levels: where the
    stackup gives a net a plane, the plane is drawn, every connection to it is
    a via drop, and no signal-layer corridor is spent on that net - the BOARD's
    own script included, not just its cells. For a module that means: drop vias as plane
    landing points and stitch ground pads; the board draws the planes. **A
    module never pours ground**: the board's fill or plane is the ground,
    a ground pad takes a via, and a ground polygon in a fragment only
    blocks the board's own copper (a local floating reference net that is
    part of the cell's function, e.g. the sense ground of an ORing
    controller, is a different net and may pour). A series
    pass path (ORing FET, filter) is the module's *function*, not distribution -
    that copper belongs in-module as wide pours. Power may enter its plane
    right where it is generated (via-in-pad on the source pad, e.g. an
    inductor output) - and a regulator's sense then taps that injection point,
    so the regulated potential is the plane's, which is what the load sees.
14. **Module-local nets stay on the module's own layer** - a net that exists
    only inside the module never claims another layer; other layers belong to
    the board. Vias on a local net are legitimate only as documented landing
    points for an optional board-level strap.
15. **Decoupling completes on one layer** - a bypass cap serves its pin only
    if cap and pin share a board side and the serve trace runs entirely on
    that layer; a via in the serve path (cap -> plane -> pin) demotes bypass
    to bulk and defeats the cap. Vias belong on the rail side (distribution
    in) and on the gnd pad (return out) - never between cap and served pin.
    Corollaries: (a) never exile caps from a dense fan-out - the cap sits
    point-blank ON its pin's own axis and the FAN accommodates the cap,
    not the reverse; the cap's BODY ORIENTS PARALLEL TO THE LOCAL LANE
    FLOW (45-tilted in a diagonal field, vertical in a column strip,
    horizontal where exits run straight out) so it occupies a lane-shaped
    slot instead of damming the fan. An axis-aligned cap crosswise to a
    diagonal field fails the intent even when its serve is short.
    (b) Identical-value caps individually named for specific pins
    are a per-PIN coverage contract - keep an explicit instance->served-pin
    map in the layout script and audit distances against it; refdes+net
    alone cannot reveal a mis-pairing. In hand-edit rounds the owner
    places by position, not name (editors show refdes+net only) - fold-in
    remaps instances to placements, never "corrects" placements to names.
    The service map is schematic-level intent the netlist cannot see
    (same-net caps are interchangeable to DRC and ratsnest) - layout
    matches the documented map, and changing the map is a schematic
    decision, never a layout convenience. Two traps when tempted: value
    placement follows the reference circuit's NODES, not part counts (a
    bulk cap on the wrong sibling pin can leave the supervision-critical
    node 47x under spec while the cap total "exceeds minimum"); and two
    loads that burst simultaneously (the two ends of one bus) never share
    one bypass - the shared cap halves at exactly the moment both need
    it and couples their noise.
16. **Silent rails: every cap is its own plane tap** - where board planes
    (or a supply layer) exist, a rail's consumers do not get routed to
    each other. ONE pour covers exactly what it can physically swallow -
    an adjacent group of same-net pins plus the caps beside them - and
    every consumer outside that region takes its own via to the plane
    instead of a bridge back to the pool. A bar or a spur linking two
    distant taps of the same rail is the thing this replaces: it claims
    a lane, fixes one destination where the board wanted several, and
    buys no impedance the plane does not already give. A decoupling cap
    needs zero rail routing:
    the rail arrives via-in-pad in the supply pad, ground leaves
    via-in-pad from the gnd pad, and the pin-serve trace is the only
    component-side copper the cap owns. The entire component side then
    belongs to signals. This is tactic 13 taken to its limit - not even
    local rail runs; a module-local rail (e.g. an on-cell LDO output)
    distributes on the other layer as supply copper.
16b. **Caps sit beside a forced escape bundle, never across it** - where
    pad pitch forces an escape bundle into a fixed corridor (fine-pitch
    rows leave no between-pad entries, so the exit columns are
    pin-determined), a cap placed IN that corridor costs package
    movement to clear; the same cap placed BESIDE the bundle costs
    nothing. When a cluster will not close, move the caps out of the
    forced corridor before moving any package. And when a two-pillar
    gate blocks every path shape (jogged or detoured - prove it with a
    flood fill, not intuition), move a pillar: a sub-millimetre slide of
    the blocking cluster out-values drill-class changes, footprint
    shaves, and layer detours. Placement concessions are cheaper than
    fabrication concessions, in that order.
17. **Under-package relief columns** - on a dense package, signals whose
    pin position would force fan detours (mid-face pins boxed by
    neighbours, cross-face travellers like a diff pair or a debug group)
    drop vias in the ring between the EP and the pad row and exit on the
    other layer, resurfacing at their destination. Choose the relief set
    by asking "who would otherwise force a comb, a climb, or a crossing";
    the face fans then carry only clean same-face exits and stay shallow.
    Relief vias form ALIGNED COLUMNS, MIRROR-SYMMETRIC about the package
    axis - symmetry is not cosmetic: it compresses the placement search,
    makes the pattern read as designed, and the mirrored halves
    cross-check each other. The same preference applies to any
    electrically-equivalent choice (EP via fields, flanking cap pairs):
    take the mirrored arrangement. Package-class nuance: relief COLUMNS
    are an EP-package pattern. A lead-frame package with no EP has its
    whole under-package annulus reachable on the surface layer without
    any via - ground leads with no outboard room can serve INTO the
    annulus directly, and relief needs a via only where a net must
    change layer. Via capacity in an annulus is adjacent-lead-limited
    (two standard vias want ~0.8mm where 0.5mm-pitch leads give 0.5) -
    an in-annulus via fan runs at >= via-pair pitch, not lead pitch.
    Cap-body caution both ways: a cap spanning wider than its pin pitch
    (e.g. one cap laid tangentially across a supply-pin PAIR) blacks
    out its neighbouring lead's escape - check every shadowed
    neighbour's exit before accepting a tangential or oversize body.
