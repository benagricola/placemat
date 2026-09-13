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
      snapshot.py    neutral geometry read ONCE from a .kicad_pcb: footprints,
                     pads (net, layer, polygon), courtyards, bodies, through
                     features, groups (cells), existing copper, outline, netclass
                     clearances. Immutable. Every query the scripts make
                     (bbox, pad by net, group pad, clearance) answers from here.
      occupancy.py   two-face raster + exact polygon occupancy over a snapshot,
                     with reservations. Legality checks: courtyard, through,
                     copper clearance, keepout, edge margin.
      placer.py      the offline placer: candidate enumeration for a part,
                     group or cell over an occupancy, hard legality first, then
                     score (free area, airwire, links, separation), deterministic
                     tie-break, rejection counts. Search kinds: fixed, edge,
                     ring/scan, pocket (free-rectangle), slide (compact).
      copper.py      path(), plane(), via(), drop(): geometry planning against
                     the snapshot (clearance corridors, lane, crossing, finger,
                     notch-around-vias, plane serve) producing copper intents
      lifecycle.py   the runner: collects declarations from phase blocks,
                     executes frame -> anchors -> cells -> groups -> loose ->
                     copper -> repair -> drops -> silk -> report, refreshing the
                     snapshot at each phase boundary
      kicad/
        read.py      pcbnew -> snapshot (the port of oracle.collect, geometry
                     outlines_of/pad_items, fp_*_box, group_items)
        write.py     apply resolved locations/rotations/faces, tracks, vias,
                     polys, zones + fill, rule areas, Edge.Cuts, labels,
                     refs_to_fab, stackup colours, save, render
        drc.py       kicad-cli drc + the accepted-violation filter (from round.py)
      report.py      run record (JSON) + impact vs baseline + provenance
      cli.py         run, impact, scan/query commands

Rule: `pcbnew` is imported only under `kicad/`. Everything else is pure
Python over the snapshot and is unit-testable without KiCad.

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
may reference measured cell extents from the snapshot.

## Build order (each slice has a test that runs without KiCad where possible)

1. values + snapshot + kicad/read against the committed Breakout board;
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
