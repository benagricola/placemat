# A keepout that names what it bars: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (chosen; inline, TDD) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `board.keepout(..., bars=(Part(...), Cell(...)))` keeps out the named parts and lets every other part in, including parts added to the board later.

**Architecture:** `Keepout` gains `bars` (omit_default). At settle time `layout.settle_keepout` turns it into the reservation's existing `admitted` set: every footprint ref on the board minus the barred refs (and, with `max_height=`, minus the parts too tall). `PlacedKeepout` gains `barred` so the KiCad side and the label can name them. The rule area already allows footprints when a keepout has `owners` (owners includes admitted); the `.kicad_dru` rule already forbids refs not in `owners`, which for `bars=` is exactly the barred refs.

**Tech Stack:** Python, pytest, tests/fixtures.py synthetic boards, pcbnew + kicad-cli for the DRC test.

**Spec:** `docs/superpowers/specs/2026-09-30-keepout-bars-design.md`

## Global Constraints

- Project-agnostic wording everywhere (M1, J1, "a part mounted off the board").
- Tunables are settings: the label's ref limit is `write_keepout_label_refs` (default 3).
- Plain ASCII. No X/Y arithmetic in doc examples.
- New digest-fed fields carry `metadata={"omit_default": True}`; digest parity tests pass unchanged.
- Delete board items with `board.Delete`, never `board.Remove`.
- Tests: targeted files only.

## Review Focus

- A `Cell` in `bars=` bars every member: tested in task 2.
- A part with no `Pm.Height` under `bars=` + `max_height=`: barred or too tall either way, refused: task 2.
- The refusal sentence for a barred part names it as barred, not as "N mm": task 2.
- `bars=` naming a net or a non-part: refused at declaration: task 1.
- A label for more than 3 barred refs is just the name: task 4.

---

### Task 1: The declaration

**Files:** `src/placemat/values.py` (`Keepout`), `src/placemat/layout.py` (`Board.keepout`), test `tests/test_keepout_bars.py`.

- [ ] Write failing tests: `bars=(Part("m1"),)` is stored on the `Keepout`; `bars=` with `allow=(Part(..),)` or a `Cell` in allow raises ValueError; `bars=` with `allow=(Net(..),)` is accepted; `bars=(Net(..),)` raises TypeError; empty `bars=()` is the default.
- [ ] Run, expect failure (unexpected keyword `bars`).
- [ ] Add `bars: tuple = field(default=(), metadata={"omit_default": True})` to `Keepout`; `Board.keepout(..., bars=())` validates and passes it.
- [ ] Run, expect pass. Commit.

### Task 2: Placement

**Files:** `src/placemat/layout.py` (`settle_keepout`, `PlacedKeepout.barred`), `src/placemat/occupancy.py` (`Reservation.barred`, `refusal`), test `tests/test_keepout_bars.py`.

**Interfaces:** Produces `PlacedKeepout.barred: frozenset` (refs), `Reservation.barred: frozenset`.

- [ ] Failing tests on a small synthetic board: the barred part is refused and every other part placed in the region; a part added to the footprints after the script is written is admitted with no script change (same script, a board with one more footprint); a `Cell` bar refuses each member; with `max_height=`: a short barred part refused, a short other part admitted, a tall other part and one with no height refused; the refusal text says the part is barred.
- [ ] Run, expect failure.
- [ ] In `settle_keepout`: barred = refs of `members_of(self._item(a)[0])` for each a in `k.bars`; admitted = (all footprint refs, or those within `max_height`) minus barred; `owners` stays the `allow=` names; pass `barred` to `occ.reserve` and `PlacedKeepout`. `refusal` and `reservation_hit` say `"M1 is barred"` for a ref in `r.barred`.
- [ ] Run, expect pass. Commit.

### Task 3: KiCad rule area and rule

**Files:** `src/placemat/kicad/write.py`, test `tests/test_keepout_bars_rule.py` (same shape as `tests/test_keepout_admits_rule.py`).

- [ ] Failing tests: `keepout_rules` for a `bars=` keepout gives a rule whose refs are exactly the barred refs; the rule area allows footprints; KiCad's own DRC on a small real board reports the barred part inside and not the other.
- [ ] Run, expect failure (or already passing where the existing machinery covers it; then the test stays as the pin and the gap is noted).
- [ ] Fix `_admits_parts` if the failing test shows a gap.
- [ ] Run, expect pass. Commit.

### Task 4: Label

**Files:** `src/placemat/settings.py` (`write_keepout_label_refs: int = 3`), `src/placemat/kicad/write.py` (`_keepout_admits_text`, `_keepout_admits`), test `tests/test_keepout_drawings.py`-style in `tests/test_keepout_bars_rule.py`.

- [ ] Failing tests: 2 barred refs -> `cup: bars J1, M1`; 4 barred -> `cup`; with `max_height=` -> `cup: bars M1; parts <= 2.00 mm`; a bars keepout is drawn under the default `admitting` mode; the limit is a setting.
- [ ] Run, expect failure. Implement. Run, expect pass. Commit.

### Task 5: Docs, parity, bench

**Files:** `skills/placemat/references/api.md`, `skills/placemat/references/migration.md`.

- [ ] Keepouts section and intent index entry in api.md; `## Unreleased` entry at the top of migration.md (a script listing every other part in `allow=` uses `bars=`).
- [ ] Run digest parity tests, keepout tests, and the docs tests; then the bench once. Commit with the tally.
