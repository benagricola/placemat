# Lock The Current Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A placement can be locked as it stands (`placemat lock <script> --current`), `route --adopt` locks what it adopts, and both the lock's anchors and adopted routes name parts by instance path, so a refdes renumbering elsewhere moves nothing.

**Architecture:** `routes.py` and `lock.py` store a part as its instance path and look it up through the geometry (a refdes stored by 0.43-0.46 still resolves). `previewer.resolve_like_last_run(script)` resolves as the last run did (its generation, its replay record, the lock); `lock.current(...)` checks each searched item against the written board and writes the entries; the CLI adds `lock --current` and makes `route --adopt` lock the searched items its nets join.

**Tech Stack:** Python 3.12, pytest; pcbnew for the written board.

**Spec:** `docs/superpowers/specs/2026-09-27-lock-current-design.md` (approved 2026-09-27); the instance keys are the bug of PLACEMAT_GAPS 2026-09-27 "adopted routes are keyed by reference designator".

## Global Constraints

- A stored part is its instance path (`Footprint.inst`); on reading, a name that is no instance but is a refdes on the board is taken as that refdes.
- `lock --current` locks only searched items (those with a turn in the plan), and only when each lands within `route.adopt_tolerance` of where the written board has it.
- `route --adopt` locks the searched item of each part its adopted nets join (the part, or the cell it is a member of); `--no-lock` leaves the lock alone.
- Generic wording; plain ASCII; no tool or session references in commits.

## Review Focus

1. A lock written by 0.46 (refdes anchors) still holds on 0.47.
2. A cell member's part in an adopted net locks the cell, not the member.
3. `lock --current` on a board with no run yet: a plain refusal, not a traceback.
4. Two parts swapping refdes between runs (the gap's case): nothing drifts.
5. The lock merged, not replaced: entries for items not in this `--current`/adopt keep theirs.

---

### Task 1: Instance paths in the lock and the routes file

**Files:** `src/placemat/lock.py` (`entry_from_turn` via the plan's turn, `placement_of`), `src/placemat/layout.py` (`_turn_of` records the anchor's instance), `src/placemat/routes.py` (`entries_from`, `resolve`); Tests `tests/test_routes.py`, `tests/test_lock*.py` (append).

- [ ] **Step 1: Failing tests:** an entry adopted with parts U1/R1 resolves on a board whose refdes are swapped with other parts' (same instances) to the same copper; a lock entry anchored on an instance holds after the anchor's refdes changes; an old entry naming a refdes still resolves.
- [ ] **Step 2-4:** implement, run, **commit** "The lock and adopted routes name parts by instance".

### Task 2: `placemat lock <script> --current`

**Files:** `src/placemat/previewer.py` (`resolve_like_last_run`), `src/placemat/lock.py` (`current`), `src/placemat/cli.py`; Tests `tests/test_lock_current.py`.

- [ ] **Step 1: Failing tests:** pure: `lock.current(board, plan, written, existing)` returns entries for every searched item standing where `written` has it, merges them over `existing`, and names an item that stands elsewhere; KiCad through the runner on the breakout: run, `lock --current`, a new searched part declared first, run: the locked items stand.
- [ ] **Step 2-4:** implement, run, **commit** "placemat lock --current".

### Task 3: `route --adopt` locks what it adopts; docs

**Files:** `src/placemat/cli.py` (`_adopt`), docs (`api.md`, `SKILL.md`, `migration.md` To 0.47, `BACKLOG.md`); Test `tests/test_routes.py` (the item keys an entry's parts belong to: `routes.items_of(entries, geometry)`).

- [ ] **Step 1: Failing test**, **Step 2:** implement, **Step 3:** full suite, **Step 4: commit** "route --adopt locks the items its nets join".
