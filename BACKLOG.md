# Backlog

Open work, newest source first. An item names where it came from; a report
from a board's `PLACEMAT_GAPS.md` is cited by file and date heading.

## In progress

- **The solve's default.** With the pocket fallback in, the module benchmark
  has the solve better than the sequential seed on 13 modules and worse on
  15: better on 7 of the 11 with fourteen or more parts, worse on 11 of the 21
  smaller. Whether to turn it on, or on above some size, is the user's call.

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
- **`find_board` ignores `layout = False`** (`project.py:41-81`). A `.zen`
  that declares a board with layout turned off is still taken as the board,
  so a script's `.zen` has to declare `Board()` first. Source: same file,
  "2026-09-22: the upgrade from 0.5 to 0.20 on the modular core".
- **Choosing one run of `board.edge(facing=...)`.** On an outline with
  several runs facing one way it returns all of them; a script wanting the
  outermost filtered `board.edges()` by hand. Worth asking whether an
  `outermost` choice (or the runs sorted by how far out they lie) belongs in
  the API. Source: same entry.
- **The rank can place a part before the part its link was written against.**
  Ordering by size and pin count put a small shunt down before its inductor;
  it seeded toward the wrong end and found no legal spot. The pocket fallback
  places it, but far off. Worth measuring whether a linked item should wait
  for its link target. Source: same entry.

## Housekeeping

- `mnb-ecosystem/pyproject.toml` points placemat at the stale
  `~/work/placemat-greenfield`; the `placemat-check` and
  `placemat-greenfield` worktrees are stale.

## Done

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
