# Backlog

Open work, newest source first. An item names where it came from; a report
from a board's `PLACEMAT_GAPS.md` is cited by file and date heading.

## In progress

## Open

## Housekeeping (left for Ben: outside this repository)

- `mnb-ecosystem/pyproject.toml` points placemat at the stale
  `~/work/placemat-greenfield`; the `placemat-check` and
  `placemat-greenfield` worktrees are stale.

## Done

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
