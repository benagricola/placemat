# Locking the placement a board stands in

Date: 2026-09-27
Status: approved 2026-09-27
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-27 "adopted routes move
the placement they were routed on"

## The problem

A board was routed and its nets adopted (`route --adopt-all`); on the next
run the searched parts stood elsewhere, 20 adopted routes were dropped and
the rest shorted against the moved parts. The adopted copper is drawn after
the search and the cleanup (`layout.resolve`), so it did not push the parts:
the next run did not reproduce the placement the route had been given (a run
that re-searches - new inputs, a new placemat - lands where its search now
lands). The lock holds a placement, but the only way to write it is
`--explore --accept`, which writes nothing unless a variant beats the
current placement. The board worked round it with a wrapper around
placemat's own lock API.

## The change

1. **`placemat lock <script> --current`** locks every searched item where
   the board stands: it resolves the script as the last run did (its
   generation, its replay record, the lock so far), checks that each
   searched item lands where the written board has it (within
   `route.adopt_tolerance`), and writes the lock entries for all of them
   (`lock.entries`, as `--accept` writes them). An item that lands
   elsewhere is not locked and is named ("U7 stands at (x, y) on the board
   and would be placed at (x', y') now: run the script, then lock"), and
   the command exits 1.
2. **`route --adopt` locks what it adopts**: after writing the routes file,
   it locks, as `--current` does, every searched item the adopted nets'
   parts belong to (a part, or the cell it is a member of), and says how
   many it locked. `--no-lock` leaves the lock alone. A route whose placement
   does not reproduce adopts nothing and says why, since the kept copper
   would be dropped on the next run.
3. `placemat lock <script> --release ...` / `--release-all` undo either.
4. **Docs:** api.md (the lock section and route's `--adopt`), SKILL.md's
   line on keeping routed nets, the migration note.

## Verification

- Pure tests: a board with two searched parts resolved, `--current`'s entries
  hold them on the next resolve after a change that would move them
  otherwise (a new part declared before them); an item whose resolve differs
  from the written position is refused and named.
- KiCad test through the runner (the breakout): run, `lock --current`, add a
  part that would push a searched one, run: the locked items stand.
- Bench unaffected (no bench board has a lock).

## Not in scope

- Locking fixed or edge items (they are declared, not searched).
- Moving a locked item: `--release`, then run.
