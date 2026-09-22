# Backlog

Open work, newest source first. An item names where it came from; a report
from a board's `PLACEMAT_GAPS.md` is cited by file and date heading.

## In progress

- **Pocket fallback for a seeded item with no room** - spec
  `docs/superpowers/specs/2026-09-22-bench-and-pocket-fallback-design.md`,
  plan `docs/superpowers/plans/2026-09-22-bench-and-pocket-fallback.md`.
  Tasks 1-2 (the benchmark and its baseline) are done.
- **The solve's default** - compare `solve` with `default` on the benchmark
  once the fallback is in; turning it on is a decision for the user.

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

- **The solve crashed on a board with a keepout** (`51fd482`). Source:
  fairing-instrument `electronics/PLACEMAT_GAPS.md`, "2026-09-22: `[solve]
  enabled = true` crashes on a board with a keepout".
