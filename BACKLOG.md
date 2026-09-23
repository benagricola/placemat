# Backlog

Open work, newest source first. An item names where it came from; a report
from a board's `PLACEMAT_GAPS.md` is cited by file and date heading.

## In progress

- **The solve's default.** With the pocket fallback and the cleanup pass in,
  the module benchmark has the solve better than the sequential seed on 16
  modules and worse on 11. It stays off; the measured variants are under
  Done.

## Open

Bugs, each checked against the code on 2026-09-23 (reproduced where it says so):

- **`polys_overlap` misses overlaps whose boundaries coincide.** Two identical
  courtyard rectangles, or the same one shifted 0.3 mm along its long side,
  read as not overlapping when the first vertex is one the half-open
  point-in-polygon test excludes: every vertex lies on the other's boundary
  and no edge crosses properly. Reproduced. `legal()` still refuses a stacked
  part (its distance test catches it); the direct boolean callers do not -
  a block's member-vs-member check (`placer.py:472,480`), the far-face and
  cutout checks in `occupancy.py`, `checks.py:314`, the keepout tests in
  `layout.py` and `queries.py`. This is why two satellites aimed at one pad
  land on one spot: reproduced with two capacitors on one anchor pin, both
  at (24.8, 40.0) in either envelope. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the bench panel cell", item 1.
- **The pocket search refuses room that is not one rectangle.** `pockets()`
  offers the largest free rectangle and stops when the item does not fit it,
  and `_no_pocket_note` declares the item hopeless from that one rectangle,
  so an item that fits an L- or T-shaped space is refused. Four cells on the
  fairing core, and on the core board copy `inputpower.j_gnd` and
  `logic.c_vdda_1u`. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the MCU cell" item 2 and "the power cells" item 2.
- **A keepout's `layers=` does not narrow its parts reservation.** The
  reservation in `layout.py` (`occ.reserve(poly, "keepout ...", allow=,
  owners=)`) passes no `layer`, though `Occupancy.reserve` takes one, so a
  front-only keepout blocks the back. Blocks a fanout band declared as a
  keepout. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven things" item 1 and "passive orientation" item 3.
- **A through-hole pad claims the whole part on both faces.** `through =
  any(p.through for p in fp.pads) or bool(fp.npth)` (`occupancy.py`) sends
  the courtyard and body to the far face; only the holes reach it. Vias in
  an exposed pad are plated pads, so an SMD chip with a via-in-pad claims
  its body on the back as well. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven things" item 5 and "the power
  cells" item 1.
- **A part with no declaration gets no finding.** It stays where the
  generator put it, with no step and nothing in `findings` (reproduced).
  Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the bench panel cell", item 4.
- **The cached generation is never invalidated.** `generate()` restores
  `.placemat/generated/` whenever it exists; a changed `.zen` or fragment is
  only picked up with `--fresh`. Wanted: a key over the generator's inputs
  (the `.zen` files and fragments it reads), or at least a warning. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`,
  "the bench panel cell", item 3.
- **The run id ignores modules the script imports**, and the script's
  directory is not on `sys.path` (`context.run_script` loads the file by
  path only), so a shared geometry module needs `sys.path.insert` in every
  script and changing it keeps the run id. The fab profile is in the id
  now. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven things" items 2 and 3.
- **"Wholly off the board" counts a region's vertices.** A strip whose
  corners sit on or past the outline is refused though it covers board
  (`_keepout_unusable`). Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven things", item 4.
- **KiCad reports parts a keepout allows as `items_not_allowed`.** The
  written rule area has no allow list and placemat does not filter those
  from the DRC report. 9 of 17 on the fairing core. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the power cells",
  item 3.
- **A row in the physical envelope lets different-net pads meet.** Two
  buttons came out with pads 0.05 mm apart (0.16 needed). Not reproduced
  yet. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the MCU cell", item 4.
- **A label on a back-face part at rotation 90 lands on the part's own
  silk**, whichever side is asked for. Not reproduced yet. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven
  things", item 7.
- **A stamped cell's labels are not reserved in the parent.** Not
  reproduced yet. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the bench panel cell", item 2.
- **`place.courtyard_touch` and KiCad disagree** on courtyards within
  0.02 mm once KiCad does not round them out. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "seven things", item 6.
- **A `Layout()` fragment gets default rules** (silk clearance 0, stdlib
  netclass) unless it declares a board config. Probably a generator
  (`pcb`) matter; to confirm. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the MCU cell", item 3.

Features:

- **All four rotations for a searched part by default**, and rotation (and a
  180 flip) in the cleanup pass. Now a searched part is scanned only at its
  `rotation` unless `rotations=` is given (`layout.py`, the `scan` call).
  The fairing agent measured crossings 1,318 -> 1,124 on the core with all
  four. Needs a bench run for time and HPWL. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "passive orientation",
  items 1 and 5.
- **`[drc] severities`**: a table placemat writes into the generated
  project's `rule_severities`, so KiCad and placemat judge the board alike
  (the project file is regenerated on every fresh generation). Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the MCU
  cell", item 1.
- **Per-net airwire in the run record, and coordinates in `parts`.** Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`,
  "the bench panel cell", item 5.
- **Label boxes in `measure`, and a fragment preview framed on its
  `board.size()` frame.** `preview --zoom` covers the framing if the frame
  is offered as a region. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the MCU cell", item 5.
- **A fanout band for a fine-pitch part**: a band round its pads, per side,
  that only satellites and parts linked SHORT to a pin may enter. Depends on
  the per-face keepout fix above. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "passive orientation", item 5.
- **A crossing swap in the cleanup pass**: two neighbouring two-pad parts
  whose ratsnest lines cross are swapped or turned. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "passive
  orientation", item 5.
- **`Centre(x, None)` seeds each item by its links** rather than sharing a
  line evenly. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "passive orientation", item 4.
- **Stdlib passive courtyards smaller than a 0.2 mm silk clearance.** A
  library matter (`fetch_parts.py` does not normalise courtyards); noted,
  not placemat's. Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "the bench panel cell", item 6.

- **Pin names for pads.** `measure --pads` prints pad number and net only, so
  a script linking bypass capacitors to supply pins had to read pin names from
  an exported KiCad netlist, and an IC with several pads on one rail (a strap
  pin beside the supply pin) cannot be told apart. Wanted: the pin name beside
  the pad number in `measure --pads`, and `PadRef(part, pin="VDD")`. The
  generated board and the `pcb` netlist (`layout/default.net`) carry no pin
  names; the symbols (`.kicad_sym`) or a KiCad-exported netlist do, so the
  first question is where placemat reads them from. Needs a spec.
  Source: fairing-instrument `electronics/PLACEMAT_GAPS.md`, "2026-09-22:
  which pad is the supply pin".

## Housekeeping

- `mnb-ecosystem/pyproject.toml` points placemat at the stale
  `~/work/placemat-greenfield`; the `placemat-check` and
  `placemat-greenfield` worktrees are stale.

## Done

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
