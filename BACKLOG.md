# Backlog

Open work, newest source first. An item names where it came from; a report
from a board's `PLACEMAT_GAPS.md` is cited by file and date heading.

## In progress

## Open

- **A part whose courtyard is not a rectangle, judged by its box**
  (PLACEMAT_GAPS 2026-09-27 "placement behaviour met on the ring test
  board"): sector windings fixed at a disc centre collide with each other by
  their courtyard boxes; judge by the courtyard polygon KiCad draws.
- **Placement behaviours from the ring test board** (same entry): a block
  satellite slides along its pin row over other pins; the link-wait rule
  outranks `priority=`; a part seeded deep inside a parts keepout searches
  only its own size from the seed.
- **`placemat impact` between a run and a KiCad file**, copper included
  (PLACEMAT_GAPS 2026-09-27 "folding a hand layout into a fragment's
  script").
- **A plug on another board against a receptacle here** (PLACEMAT_GAPS
  2026-09-27, twice): pad-to-pad nets across two board files and a turn.
- **Placing relative to a searched item** (PLACEMAT_GAPS 2026-09-26, twice):
  a `Pin` or a cutout on a searched item is refused ("only FIXED and EDGE
  items may be referred to"). Needs a spec.
- **Each part's clearance to each keepout** (PLACEMAT_GAPS 2026-09-26):
  physical, courtyard and maximum-package, as a report.
- **A plated lead against a neighbour's courtyard on the same face under
  physical envelopes** (PLACEMAT_GAPS 2026-09-26).
- **A re-laid cell that outgrows the room its parent gave it** (PLACEMAT_GAPS
  2026-09-25).
- **The run score ranks escape settings the wrong way round** (PLACEMAT_GAPS
  2026-09-25): it measures escapes at the search's own escape_depth.
- **A route report of each net's path, or a preview of the routed copy**
  (PLACEMAT_GAPS 2026-09-27).
- **`board.pair()` finding its own centreline; `route.diff_pairs` taking
  explicit net pairs** (PLACEMAT_GAPS 2026-09-27).

## Housekeeping (left for Ben: outside this repository)

- `mnb-ecosystem/pyproject.toml` points placemat at the stale
  `~/work/placemat-greenfield`; the `placemat-check` and
  `placemat-greenfield` worktrees are stale.

## Done

- **A custom pad's outline in `measure --pads`** (unreleased; PLACEMAT_GAPS
  2026-09-27 "a custom pad's outline").
- **`placemat drc` lists each violation** (unreleased; PLACEMAT_GAPS
  2026-09-27 "reading a routed board's layers and DRC items"): with its
  description, items and positions.
- **Footprint copper through the router** (0.46.0; PLACEMAT_GAPS
  2026-09-27 "the router moves a net-tie footprint's outer copper to silk"):
  rule areas keep the router off footprint copper graphics, and the routed
  copy gets them back before its DRC.
- **3D model paths that resolve from any project depth** (0.45.0; a
  board's layout work, 2026-09-27): the write re-anchors a model path that
  does not resolve to the nearest folder above that holds it
  (spec `2026-09-27-model-paths-design.md`).
- **Hole spacing when placing** (0.44.0; a board's layout work,
  2026-09-27): drilled holes of different owners keep hole_to_hole whatever
  their nets; copper keeps hole_clearance from an unplated hole; the via
  planner sees a stamped cell's vias (spec `2026-09-27-hole-spacing-design.md`).
- **Keeping routed copper** (0.43.0; PLACEMAT_GAPS 2026-09-27 "router
  output cannot be kept in the script"): `placemat route <script> --adopt
  NET ...` keeps the router's copper in `<script stem>.routes.json`,
  relative to its pads; runs draw it while its parts stand, and drop a net
  whose part moved. `placemat routes` lists and releases.
- **A script imports from the folders above it** (0.43.0; a board's
  layout work, 2026-09-27): up to the nearest placemat.toml, and those modules
  count in the run id.
- **A block that fits nowhere, found before the search** (0.43.0;
  PLACEMAT_GAPS 2026-09-26): a searched block is laid out alone at each of
  its rotations first.
- **A failed run leaves the last good board** (0.43.0; PLACEMAT_GAPS
  2026-09-26): a run that fails before writing the board puts the layout
  folder back as the last run left it.
- **A run keeps files it did not write; round track ends** (0.42.0; a
  board's layout work, 2026-09-27): the layout folder's other files and a
  hand-edited board survive a run; a track's end is round, so a clean
  board no longer reads 0.13 mm against a 0.16 rule.
- **A keepout by part height** (0.42.0; a board's layout work,
  2026-09-27): `Pm.Height` and `board.keepout(..., max_height=)`
  (spec `2026-09-27-part-height-design.md`).
- **`measure --labels` with text size, angle, mirroring and silk graphics**
  (0.42.0; PLACEMAT_GAPS 2026-09-27).
- **The 2026-09-27 evening gaps entries** (0.41.0): `placemat drc` takes a
  relative path; the routed copy is saved with its zones refilled; a
  footprint's copper graphics are copper to the placer; `placemat parts`
  lists each part's footprint and `--field NAME` columns; a part facing a
  curved edge gets a clean rotation.
- **Several vias in one pad** (0.41.0; PLACEMAT_GAPS 2026-09-27):
  `board.vias(net, PadRef(...), pitch=)` (spec `2026-09-27-pad-vias-design.md`).
- **A one-face parts keepout and a cell's vias** (0.41.0; a board's layout
  work, 2026-09-27): a cell's vias no longer make it two-faced to a parts
  keepout; plated leads and unplated holes still do.
- **`check current-path` judges the load's route** (0.41.0; PLACEMAT_GAPS
  2026-09-27; Ben chose dead-end branches skipped): the widest route between
  carrying parts, or from the one carrying part to another part.
- **A fragment's extent, and `measure --outline`** (0.41.0; PLACEMAT_GAPS
  2026-09-27): the run's extent line measures parts as the envelope claims
  them, so a physical-envelope fragment has one; `measure --outline` prints
  a board's Edge.Cuts items, box and thickness.
- **The 2026-09-27 afternoon gaps bugs and `board.parts()`** (0.41.0):
  FreeSpot and `--via-near` keep off unplated holes; the router runs with
  `--keep-input-copper` so declared copper survives its cleanup;
  `board.pair()` needs two centreline points and says so; a decided part
  turned near a round rim is judged by its corners; `board.parts(net=)`.
- **`board.envelope(item, rotation=)`** (0.41.0; a board's layout work,
  2026-09-27): what the placer keeps under `[place] envelope`, documented,
  so a hand-built row stops calling the internal `drawn_envelope`.
- **`pitch()` on split lands** (0.41.0; PLACEMAT_GAPS 2026-09-27): a
  pin drawn as several lands is one pin, and `pitch(part, pins=(a, b))`
  measures two named pins.
- **`reach()` smaller than the envelope** (PLACEMAT_GAPS 2026-09-27): not
  reproduced on 0.40 (0.88 mm, as the envelope); the board's layout work confirmed
  the reading came from before 0.39.
- **A frame sized to its content** (0.40.0; PLACEMAT_GAPS 2026-09-27):
  `board.size(fit=True, margin=)`, planes following the fitted frame
  (spec `2026-09-27-fit-frame-design.md`).
- **Freeze keeps intent** (0.40.0; spec
  `2026-09-27-freeze-intent-design.md`): freeze writes `PadRef.local` and
  `Turned` from the lock's own numbers, with a `why=` naming the explore
  run and score the lock now records.
- **A via found near a pad, joined to it** (0.39.0; PLACEMAT_GAPS
  2026-09-26 twice and 2026-09-27): a FreeSpot via draws its tail, and a
  via intent is a track end (spec `2026-09-27-via-tail-design.md`).
- **Route layers from the declared planes** (0.39.0; a board agent's
  router A/B, 2026-09-25): the route step used to give the router every
  copper layer unless `[route] layers` said otherwise, so on a board whose
  inner layers are planes the router ran signals (and a differential
  pair's reference side) through them, and KiCad flagged every such track
  and via against the plane zones. Left to itself, the default now leaves
  out an inner layer whose own outline a `board.plane()` zone covers at
  least `route.plane_share` of, never F.Cu or B.Cu; the route step prints
  what it left out and why.
- **Five PLACEMAT_GAPS bugs, 2026-09-26** (0.38.0): cleanup leaves a
  decided block's satellites alone (cf9f1cd); `--via-near` keeps out of
  every land of a split pin (7a299af); `datasheet` reads text with a
  character reference XML forbids (8ed7488); a run compares with and
  reuses its own board's last run (9278996); a searched `Near` on another
  searched item's pad waits for it (f55c17b).
- **A cell's zones under the board's own plane** (0.37.0, from Ben on
  2026-09-27; a core board had 17 cell zones on nets and layers its own
  planes cover): merged into the plane at write, `copper.cell_zones_under_planes`.
- **A class clearance that does not fit a pad pitch** (0.36.0, from a
  board agent's request): a setup finding naming the part, its tightest
  escape lane and the clearance that fits (32131a1).
- **Pair crossings weighed at placement** (0.36.0): a differential
  pair's own crossing costs `score.pair_crossing`; a crossed pair is a
  `pair_crossed` finding (spec `2026-09-25-pair-crossing-design.md`).

- **Explore, the lock and freeze** (0.32.0): `--explore SECONDS` on run and
  preview varies the focused items' spots, rotations and order in parallel
  variants and reports the best; `--accept` keeps it in a lock file of
  anchor-relative entries that later runs apply, drifting or releasing
  with a note; `placemat freeze` moves entries into the script. Measured
  with `bench.py --explore 64`: better on 26 of 32 modules, worse on none.
  Next: large neighbourhood search (spec
  `docs/superpowers/specs/2026-09-25-explore-design.md`, Phase two).
- **Packaging the native module** (0.31.0): the `native` extra builds it on
  install with the machine's Rust toolchain (uv, from `native/`); a tag
  `v*` runs `.github/workflows/release.yml`: the suite without and with
  native, abi3 wheels for Linux x86_64/aarch64 and Apple Silicon, and
  placemat's wheel and sdist, attached to the GitHub Release. A native
  module from another release is not used.
- **A native core** (0.30.0): an optional Rust module (`native/`, built with
  maturin; `PLACEMAT_NATIVE=0` forces Python) takes the geometry
  predicates, the near-obstacle conflict search inside `legal()` with each
  candidate's shapes held natively, and the pocket raster's largest
  rectangle; reasons are formatted once per rejection bucket. Sequential
  timing on the merged code, Python then native, CPU time, whole bench
  corpus: default 62.3 -> 25.0 s (2.49x), solve 59.3 -> 22.0 s (2.70x),
  physical 136.2 -> 30.6 s (4.45x); the fairing core's resolve 224.1 ->
  48.3 s (4.64x). All 102 bench results and all 174 core steps identical;
  the suite passes both ways. Spec:
  `docs/superpowers/specs/2026-09-24-native-core-design.md`. Open: how the
  compiled module is packaged for a release.
- **PLACEMAT_GAPS "placemat 0.28"** (after 0.29.0): item 1, a stamped keepout
  costing the parent: the cell's step now says how much board its regions
  take beyond its members, and `board.fanout()` is the band that follows
  the pad rows. Item 2, the via-in-pad chip on the back: fixed in 0.29.0
  (checked on the fairing core: the MCU's 9 exposed-pad vias read as vias,
  0 leads). Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`,
  "2026-09-23: placemat 0.28".
- **The solve's default: stays off** (decided 2026-09-24): re-measured on the
  current code (rotations, pockets, neighbour swaps), the solve against the
  sequential seed is 11 better, 17 worse, median HPWL x1.058. `[solve]
  enabled` remains opt-in.
- **Stdlib passive courtyards under a 0.2 mm silk clearance: not placemat's**
  (closed 2026-09-24): the library's courtyards are its own to fix. On the
  placemat side a courtyard-envelope run lists each footprint whose silk
  passes its courtyard (`metrics.footprints`), the physical envelope spaces
  by silk, and a label keeps the silk clearance. Source: fairing-instrument
  `electronics/PLACEMAT_GAPS.md`, "the bench panel cell", item 6.
- **A fanout band** (0.29.0): `board.fanout(part, depth=, sides=)` reserves
  the strip outside each pad row on the part's face for its satellites and
  SHORT-linked parts. Spec: `docs/superpowers/specs/2026-09-24-fanout-band-design.md`.
  Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "passive
  orientation", items 2 and 5.
- **Pin names for pads** (0.29.0): read from the symbols the .zen files
  use (through the component's footprint, else the netlist's name);
  `PadRef(part, pin=)` and pin names in `measure --pads`. 53 parts named on
  the fairing core, the MCU's 57 pins among them. Spec:
  `docs/superpowers/specs/2026-09-24-pin-names-design.md`. Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "2026-09-22: which pad
  is the supply pin", "the power cells" item 4.
- **Neighbours trade places in the cleanup pass** (0.29.0): two
  neighbouring two-pad parts of any size are tried in each other's places,
  in any rotation each may take. Bench: 6 better, 0 worse. Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "passive orientation",
  item 5.
- **A line item starts across from its links** (0.29.0): `Location(x, None)`
  and `Centre(None, y)` slide from the point across from what they connect
  to when that is placed. Source: fairing-instrument
  `electronics/PLACEMAT_GAPS.md`, "passive orientation", item 4.
- **Label boxes in `measure`; a fragment framed** (0.29.0): `measure
  --labels` gives every board silk text's drawn box; `placemat preview`
  frames on the board outline and the placed parts, so parts left at the
  generator's positions do not shrink the view. Source: fairing-instrument
  `electronics/PLACEMAT_GAPS.md`, "the MCU cell", item 5.
- **Per-net airwire and part coordinates** (0.29.0): `metrics.airwire_per_net`,
  the impact's `airwire by net:`, and origin, rotation and centre in `parts`.
  Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the bench panel
  cell", item 5.
- **`[drc.severities]`** (0.29.0): KiCad rule severities written into the
  board's project each run. Source: fairing-instrument
  `electronics/PLACEMAT_GAPS.md`, "the MCU cell", item 1.
- **A fragment laid out by default rules is named** (0.29.0): the rules
  come from the generator (`pcb`); a run notes a board whose silk clearance
  is 0 and the skill says to give a fragment the parent's config. Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the MCU cell", item 3.
- **Courtyards judged as KiCad judges them** (0.29.0): measured, KiCad's
  DRC counts touching courtyards as overlapping and its polygon lies inside
  the drawn box (by 0.03 for a 0.05 stroke). Each footprint's margin is
  read from KiCad's polygon; two courtyards may overlap by the two margins
  less 0.001. Bench: default 14 better, 4 worse, median 0.99. Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven things", item 6.
- **A stamped cell's labels are reserved in the parent** (0.29.0): each
  silk text in a cell's group is read as a parts-excluding region of the
  cell on its face. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`,
  "the bench panel cell", item 2.
- **A label keeps the silk clearance from its part** (0.29.0): the label
  gap is at least the board's silk clearance. Reproduced with the flag tab
  footprint and KiCad's DRC: at gap 0 every side touched the tab's silk on
  the front; on the back and with the fix, DRC is clean at every rotation.
  Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven
  things", item 7.
- **Rows in a drawn envelope keep the envelope's gaps** (0.29.0): a row's
  or ring's gap is at least the widest gap the envelope enforces. Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the MCU cell", item 4.
- **Parts a keepout allows are not DRC violations** (0.29.0): KiCad's
  `items_not_allowed` for an allowed part or net is counted as permitted.
  Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the power
  cells", item 3.
- **"Wholly off the board" by area** (0.29.0): a region is off the board
  only when it shares no area with it or lies inside a hole. Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven things", item 4.
- **The far face under a through-hole part** (0.29.0): only its holes
  claim it; a lead keeps courtyards off, a via in the part's own pad does
  not. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven
  things" item 5, "the power cells" item 1.
- **What a run is made from** (0.29.0): the cached generation records
  its inputs and regenerates when one changes; the script's directory is
  importable and its sibling modules count in the run id. Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven things" items
  2 and 3, "the bench panel cell" item 3.
- **Three gaps bugs** (0.28.0): the pocket search takes the largest room
  the item fits, and the check before a search rounds toward room; a parts
  keepout or stamped rule area keeps parts off only the faces its layers
  name; an undeclared part is a finding. Source: fairing-instrument
  `electronics/PLACEMAT_GAPS.md`, "the MCU cell" item 2, "the power cells"
  item 2, "seven things" item 1, "passive orientation" item 3, "the bench
  panel cell" item 4.
- **Rotations for searched parts** (0.28.0): all four for a part with none
  declared, in the search, the pocket fallback and the cleanup pass;
  `[place] rotations = "declared"` for the old behaviour. Bench: +13 placed,
  median HPWL 0.84 (default). Core board copy (its script already lists
  four rotations on searched parts): 126 placed either way, wire cost
  1385.1 -> 1383.7, 589 -> 676 CPU s under power save. Blocks keep one
  rotation (the bench has none to measure). Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`,
  "passive orientation", items 1 and 5.
- **legal() faster** (0.28.0): shapes turned once per rotation, rectangles
  by their boxes; the same placements, about a third less resolve time in
  the courtyard envelope.
- **Coinciding outlines** (0.28.0): `polys_overlap` finds shared
  interior when every vertex lies on the other's boundary; two satellites on
  one pad are refused with the reason, not stacked. Source: fairing-instrument
  `electronics/PLACEMAT_GAPS.md`, "the bench panel cell", item 1.
- **placemat preview** (0.27.0): the plan drawn without building the board,
  with links, pockets, unplaced parts, copper and a congestion heat map;
  core board unchanged preview 5.3 s. A part not yet placed no longer blocks
  pockets, copper checks or cutouts; RUDY without pad blockage.
- **Code quality pass** (0.26.x): dead code, helpers for repeated code,
  stale docstrings, reuse keys without memory addresses.

- **Run reuse** (0.26.0): replay up to the first changed step, exact. Core
  board: unchanged rerun 125 s -> 7 s; a late part changed 118 s -> 24 s.
- **Speed** (0.26.0): block satellites from cached shapes, a raster for
  reservations, links by pad pair: core resolve 298 s -> 106 s, placing the
  same.
- **RUDY reported** (0.26.0): worst cell per run. Validation strategy - many
  complete placement pairs routed by KRT (full run), >= 70% pairwise
  agreement on >= 100 pairs, the unrouted connections near the hot cell, a
  second router on a subset, then 5-10 core placements - is the next step
  before it steers placement.

- **Cleanup pass** (0.25.0): moves and swaps after the searched tier.
  Benchmark: 23 better, 0 worse in default and physical, 26 better with the
  solve; core board (mid-normalisation snapshot): findings 26 -> 22, link
  length 831 -> 774 mm.
- **Improving the solve** (measured 2026-09-23 as patches, not shipped).
  Against no solve, better / worse of 32, before the cleanup pass:
  - Bound2Bound net model (Kraftwerk2, SimPL) instead of the chain: 15 / 13,
    and 9 / 2 on the 11 largest modules.
  - SimPL anchor weights (linear growth, divided by distance to the spread
    cell): 16 / 11.
  - Bound2Bound and a re-solve every 3 placements with what is placed as
    anchors: 17 / 11.
  - The solve only for items nothing placed pulls yet: 16 / 10, 11 / 4 on the
    21 smaller modules.
  - Worse: hints from the spread positions (11 / 17 with Bound2Bound), and
    more rounds (10 / 18 at 16 or 30). The spread ignores fixed parts,
    keepouts and a non-rectangular outline, which is the likely reason; a
    spread into the free area is the untested next step.
  - With the cleanup prototype after each, none beat default plus cleanup
    (best 16 better / 10 worse).

- **PLACEMAT_GAPS 2026-09-23** (0.24.0): `measure` box edges, pad outlines,
  mask/paste layers and courtyard findings; a block satellite aimed at an
  anchor pad by number; the fab profile in the run id.

- **Placement envelopes** (0.23.0): `[place] envelope = "physical"` claims
  pads, mask openings, silk and body at the board's own gaps. On the core
  board (2026-09-23 snapshot, mid footprint normalisation): no silk items
  between different parts; resolve 284 s against 239 s in courtyard mode;
  221 placed against 224; 199 `courtyards_overlap` from KiCad's courtyard
  check, which the mode does not honour.

- **Three PLACEMAT_GAPS items** (0.22.0): `find_board` skips `layout =
  False`; `board.edge(facing, outermost=True)`; of two linked items neither
  placed, the one with less pull waits (on the core board's pre-block RF
  chain: one pocket fewer, 13.5 mm less link length; the current script is
  unchanged).

- **Run time on large boards** (0.21.1). A 220-part board's resolve went
  from 945-1167 s to 110 s with identical placements: prepared many-vertex
  outlines, bounding-box pruning in `polys_overlap`, a block's obstacles
  gathered once, a grid over a scan's obstacles, and the board raster mask
  kept. What remains is spread over transforms and box building.

- **Pocket fallback for a seeded item with no room**, and the module
  benchmark that measured it (0.21.0). Spec
  `docs/superpowers/specs/2026-09-22-bench-and-pocket-fallback-design.md`.

- **The solve crashed on a board with a keepout** (`51fd482`). Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "2026-09-22: `[solve]
  enabled = true` crashes on a board with a keepout".
