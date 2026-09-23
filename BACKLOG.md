# Backlog

Open work, newest source first. An item names where it came from; a report
from a board's `PLACEMAT_GAPS.md` is cited by file and date heading.

## In progress

- **The solve's default.** With the pocket fallback and the cleanup pass in,
  the module benchmark has the solve better than the sequential seed on 16
  modules and worse on 11. It stays off; the measured variants are under
  Done.

## Open

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
