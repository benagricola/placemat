# Placemat rewrite plan

Basis: this worktree. The original `~/work/placemat` is a quarry for pcbnew
mechanics only, read one function at a time when porting, never as an API
reference. The current 600 lines here are discarded except `values.py` and
the CLI shape (argparse subparsers, progress to terminal, logs to files).

Done means: a new `breakout/Breakout_layout.py` written against the new API
runs end to end (`placemat run breakout`), regenerates the KiCad board from a
clean `pcb layout`, passes kicad-cli DRC with the same accepted classes as
today, and the impact report against the committed Breakout board explains
every difference. The skill is rewritten alongside and is what the Breakout
script is written from.

## Package layout

    placemat/
      values.py      Net, Part, Pad, Location, Rotation, Face, CopperLayer, Edge
      board_geometry.py  the generated board's geometry read ONCE from a .kicad_pcb: footprints,
                     pads (net, layer, polygon), courtyards, bodies, through
                     features, groups (cells), existing copper, outline, netclass
                     clearances. Immutable. Every query the scripts make
                     (bbox, pad by net, group pad, clearance) answers from here.
      occupancy.py   two-face raster + exact polygon occupancy over the board geometry,
                     with reservations. Legality checks: courtyard, through,
                     copper clearance, keepout, edge margin.
      placer.py      the offline placer: candidate enumeration for a part,
                     group or cell over an occupancy, hard legality first, then
                     score (free area, airwire, links, separation), deterministic
                     tie-break, rejection counts. Search kinds: fixed, edge,
                     ring/scan, pocket (free-rectangle), slide (compact).
      copper.py      path(), plane(), via(), drop(): geometry planning against
                     the board geometry (clearance corridors, lane, crossing, finger,
                     notch-around-vias, plane serve) producing copper intents
      lifecycle.py   the runner: collects declarations from phase blocks,
                     executes frame -> anchors -> cells -> groups -> loose ->
                     copper -> repair -> drops -> silk -> report, refreshing the
                     board geometry at each phase boundary
      kicad/
        read.py      pcbnew -> BoardGeometry (the port of oracle.collect, geometry
                     outlines_of/pad_items, fp_*_box, group_items)
        write.py     apply resolved locations/rotations/faces, tracks, vias,
                     polys, zones + fill, rule areas, Edge.Cuts, labels,
                     refs_to_fab, stackup colours, save, render
        drc.py       kicad-cli drc + the accepted-violation filter (from round.py)
      report.py      run record (JSON) + impact vs baseline + provenance
      cli.py         run, impact, scan/query commands

Rule: `pcbnew` is imported only under `kicad/`. Everything else is pure
Python over the BoardGeometry and is unit-testable without KiCad.

## What is ported from the original (mechanics, ~1/6 of it)

- `geometry.py` polygon/polyset math and `collect`/`outlines_of`/`pad_items`
- `layout_oracle.py` `refresh`/`occ`/`SpatialIndex`/`fits` legality logic
- `layout_helpers.py` group ops (`group_*`), `fp_*_box_mm`, `refs_to_fab`,
  `patch_stackup_colors`, `knockout_label`, `save`, `render`
- `board_layout.py` `plane`, `plane_serve`, `drop_ok`, `stub_ok`, `spine`,
  `band_with_notches`, `rule_area`, `design_rule`, `cell_clearance`
- `tools/round.py` DRC invocation and accepted-class filter;
  `tools/board_occupancy.py` the occupancy report
- `tools/route_trial.py` later, as an optional diagnostic

Not ported: the stage registry, `require_nets`, batch APIs, the six track
verbs, `reserve` as a public primitive, `purge`, `BOARD-INTENT` reading, the
lint, the scaffold, the skill text.

## Public API (what a script sees)

    from placemat import layout, board, Net, Part, Location, Edge, Face, CopperLayer

    with layout.setup():    board.outline(chamfer=CHAMFER); board.fix(mh1, at=Location(..))
    with layout.anchors():  board.place(cn1, edge=Edge.NORTH, rotation=180, ...)
    with layout.cells():    board.place(power_drop[0], edge=Edge.EAST, rotation=90, after=...)
    with layout.groups():   board.place(group(...), ...)
    with layout.loose():    board.place(r15, near=cn1, ...)
    with layout.copper():   board.plane(V48P, layers=(F,)); board.path(CANH, ...)
    with layout.silk():     board.label(...)

One `place()`; the item kind (part, cell, group) and the keyword set select
the search. `path()` shapes: straight, polyline, lane, crossing, finger.
`Net`/`Part` are typed references; numeric pads are ints. Board width and
height may be derived: `board.frame(width=expr, height=expr)` inside frame
may reference measured cell extents read off the generated board.

## Status

Slices 1-6 are built and green (81 tests; the end-to-end test builds a
scratch workspace and runs the pcb toolchain). The new
`breakout/Breakout_layout.py` in the ecosystem regenerates the Breakout to
the committed board's gate state: DRC clean, unconnected 0, the same 36
dangling module stubs, zero crossings, 126.5 x 229.89. Crossings per net, congestion and routing (`placemat run --route`,
`placemat route`, explicit and never default) are in. Next: STOP and plan
the placer search kinds (pocket scan, net-seeded search, compaction,
blocks) before building them against the Middleweight. The ecosystem's dependency still points at the old placemat
checkout.

## Build order (each slice has a test that runs without KiCad where possible)

1. values + board geometry + kicad/read against the committed Breakout board;
   test: extents of power_drop0 match the 28.600 x 40.250 the old script asserts
2. occupancy + placer fixed/edge/scan; test: Breakout stations re-place
   deterministically, second run byte-identical record
3. lifecycle runner + kicad/write of locations only; test: regenerate Breakout
   placement, occupancy report clean
4. copper: path (lane/crossing/finger), plane, via, drops, plane serve;
   test: Breakout corridor drawn, DRC accepted-only
5. report + impact + CLI; test: one-line change in the script yields an
   attributed delta
6. skill rewrite (fresh-board workflow, electrical model first, the new API,
   the gates), then the Breakout script is rewritten from the skill alone
7. Middleweight is the second consumer; anything it needs that the API lacks
   is a proposal, not a local helper

## Rulings (Ben, 2026-09-13)

- Purpose, kept in front of every decision: the tool exists so an LLM can
  iterate on placement FAST, test thousands of candidates offline, and see at
  once what a decision did to DRC, connectivity, occupancy and airwires.
- No fluent handles. No author-controlled sub-phases. TDD throughout.
- The first phase is `setup`, not `frame`. Board size is derived there.
- Copper has no lane object. A bus is one long track per net and a short
  track per pad into it; where two tracks of different nets cross on a
  layer, priority (FIXED > HIGH > DEFAULT > LOW, then the shorter) decides
  who passes under, only a track declared bridge=True may, and a crossing
  nobody may bridge is a finding. "Lane" is reserved for a future bundle
  object (several nets at a pitch, pin-order sorting, length per net),
  backlog with the Middleweight.
- Ordering is PRIORITY, not authoring order. A declaration says how firm it
  is; the runner decides when it runs and what may yield to it:
    placement  FIXED (mechanical fact, first, never moved)
               EDGE (one degree of freedom, after FIXED)
               default (searched; a cell before a group before a loose part)
    copper     FIXED (planned as soon as every endpoint is placed, becomes
               occupancy, nothing later may cut into it or move it)
               default (drawn after loose placement; loose parts sitting on
               it are nudged in repair, nothing else moves)
  Runner schedule: setup -> fixed/edge placements -> cells -> FIXED copper
  -> groups -> loose -> copper -> repair (nudge loose only) -> drops -> silk
  -> report. A FIXED copper intent whose endpoint is a loose part is an
  error at declaration time, not a surprise at run time.

## The placer: plan before code (agreed 2026-09-13, not built)

What the placer has: an occupancy model over the generated board's geometry
that checks member courtyards, holes and pad clearance (so two cells may
overlap by box when their parts do not), and a grid scan around a hint.
What it lacks is everything that chooses the hint and the order.

1. **Links price the search.** `board.link(pad_a, pad_b, weight, limit_mm=,
   why=)`. Weight is an enum with a default (SHORT, PREFER, DEFAULT, FREE)
   or any integer; 0 means the link adds nothing to the score. A candidate
   scores the sum over the part's links of weight times distance; SHORT with
   a limit is a hard bound, reported against the achieved length. A net
   whose off-board run dwarfs the board (an endstop, a motor phase) is FREE:
   nothing is pulled toward its connector. A bypass cap is SHORT at its pin.
   A series resistor between two far parts is PREFER on both links and lands
   wherever there is room between them.
2. **Net-seeded search.** The hint is where the part's non-FREE nets already
   are (the link-weighted centroid of the placed pads it connects to), then
   the grid scan, scored by links, not only legality.
3. **Pocket scan.** For a cell or part with no placed partner: enumerate the
   free rectangles that fit its envelope and take the best by score. This is
   the case the old scripts hand-typed hints for.
4. **Blocks.** A part with satellites placed by rule off its real pads (the
   input cap on the input pin's axis, one courtyard step out). The rules
   are declared once; the placer lays the block out at every candidate from
   real pad geometry, so its envelope is exact. No inflation factor.
5. **Order is the placer's, derived, never the script's.** Tiers first:
   FIXED, then EDGE (a cell containing an edge-bound connector inherits the
   edge: connector outward, pins inboard), then free cells, then blocks,
   then loose parts. Within a tier: the largest and most awkward first
   (fit = area over remaining free area, shape), then by link pull toward
   what is already placed, then declared separation. Each choice is logged
   with the sentence that made it.
6. **Rotation** is only interesting off the 90-degree grid, and then the
   thing to measure is the occupied polygon (union of member courtyards),
   not the bounding box. Not built until a board needs it.
7. **Separation scoring** (keep power, analogue, digital and noisy regions
   apart, by classifying nets and parts): an idea to develop after the
   above works on the Middleweight, not part of this round.
8. **Routing config per board**: the router's grid and clearance must be
   chosen per board (the Breakout at 0.1 mm grid is 12M cells a layer and
   every net fails "boxed in" in 220 s); an open question alongside the
   placer, not a placer feature.
