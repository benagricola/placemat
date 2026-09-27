# Vias filling a pad

Date: 2026-09-27
Status: proposal, awaiting approval
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-27 "several vias in one pad"

## The problem

A power or ground pad, and an exposed pad under a package, wants as many vias
as fit: heat and current go down through them (the datasheets' layout figures
show a grid). `board.via(net, PadRef(...))` puts one via at the pad's centre,
and `FreeSpot` finds one spot and keeps out of the pad unless `in_pad=True`.
So the board's scripts type the grid: `Location(MCU_X +/- EP_VIA_PITCH, ...)`
nine times, or a helper (`fragment_frame.pad_vias()`) that offsets a grid from
the pad's centre sized from its placed box. Both are coordinates that go stale
when the part moves, turns or its footprint is corrected.

## The change

1. **`board.vias(net, pad, *, pitch=None, size=None, drill=None, inset=None,
   why="")`**: a grid of vias of `net` inside the pad `pad` (a `PadRef`),
   resolved when the pad's part is placed. It returns the intent, as
   `board.via()` does.
   - **The grid** is square, in the part's own frame (it turns with the
     part), centred on the pad, `pitch` apart. A point is kept when the whole
     via, grown by `inset`, lies inside the pad's copper, so a round, rounded
     or custom pad fills as its shape allows.
   - **Defaults:** `size` and `drill` are the net class's via; `pitch` is the
     least centre spacing the board's hole-to-hole rule allows,
     `drill + geometry.hole_to_hole`, and never less than `size`; `inset` is
     0 (a via's copper may reach the pad's edge, but not past it).
   - **A pad no via fits in** is a finding naming the pad and the via, and
     draws nothing.
   - **A pin of several lands** fills each land.
2. **The via-in-pad note.** A via in a pad needs filling or plugging at the
   fab: the run's step note says how many were placed and that they are in
   the pad, as `FreeSpot(in_pad=True)` implies today.
3. **Docs:** api.md's copper verb table and the via paragraph; a SKILL.md
   line (fill a pad with `board.vias`, never type a grid); the migration
   note, which points at hand-typed grids.

## Verification

- Pure tests (synthetic boards):
  - a 3 x 3 mm pad with 0.3 / 0.6 mm vias and a 0.25 mm hole-to-hole: the
    grid's pitch, count and that every via is inside the pad;
  - the part turned 90 degrees: the same vias relative to the pad;
  - a round pad: only the points whose via is wholly inside;
  - a pad smaller than one via: a finding, no vias;
  - an explicit pitch smaller than the hole-to-hole rule allows: refused at
    declaration, naming the rule.
- KiCad: a filled exposed pad on the breakout board passes DRC with no new
  violation (hole-to-hole included).
- Bench, as a copper change (no bench board uses it: same 32).

## Not in scope

- Vias in a grid that is not square, staggered, or following a pattern a
  datasheet draws: the square grid at the rule's pitch is the default a
  designer then adjusts with `pitch=`.
- Tenting, plugging or filling as fab outputs: placemat notes the via-in-pad;
  the fab profile decides.
