# Rotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A searched part with no declared rotation is scanned at all four rotations, in the search, the pocket fallback and the cleanup pass.

**Architecture:** `PlaceIntent` records whether `rotation=` was given. One method, `Board._turns(i)`, answers which rotations an intent may take; every scan call that now reads `i.rotations or (i.rotation,)` asks it. The cleanup pass gets each movable part's rotations in a dict beside `movable`.

**Tech Stack:** Python 3 standard library.

**Spec:** `docs/superpowers/specs/2026-09-24-rotations-design.md`

## Global Constraints

- `[place] rotations`: `"all"` (default) or `"declared"`; anything else is a settings error naming both.
- Generic wording in src, skill and migrations; plain ASCII; no attribution lines.
- Every placement-affecting commit carries the bench tally and, when numbers change, the rewritten `fixtures/bench.json` from a whole-corpus run.

---

### Task 1: Which rotations an intent may take

**Files:** `src/placemat/layout.py` (`PlaceIntent.rotation_given`, `place()`, `_turns`, the calls at `_settle`, `_seeded_pocket`, `_no_pocket_note`, `_settle_in_pocket`), `src/placemat/settings.py` (`place_rotations`), tests `tests/test_rotations.py`.

- [ ] Failing tests: seeded two-pad part between two pins turns to 180 by default; `rotation=0`, `rotations=(0,)` and `"declared"` keep 0; a part that fits only at 90 places by default and is refused with `"declared"`; an `OnEdge` part, a `Centre(x, None)` part and a cell keep their rotation; a bad setting value is refused.
- [ ] Implement: `rotation_given = rotation is not None` recorded in `place()`; `_turns(i)` returns `i.rotations` if given, `(i.rotation,)` if `rotation_given`, a cell's or a non-searched item's `(i.rotation,)`, else the four rotations from `i.rotation` when the setting is `"all"`.
- [ ] Suite; bench; core board copy timed; commit with the tally and baseline.

### Task 2: Blocks

- [ ] Bench with `_turns` applied to a block's scan (`scan_block`). Include it only if the tally is better on balance and time stays within 1.5x; either way, the tally goes in the commit or the spec's measured section.

### Task 3: The cleanup pass turns parts

**Files:** `src/placemat/cleanup.py` (`cleanup(..., turns: dict)`), `src/placemat/layout.py` (`_cleanup` passes `turns`), `tests/test_cleanup.py`.

- [ ] Failing tests: a part whose pads are the wrong way round is turned by the pass; a part given `rotation=` is not.
- [ ] Implement: each move scans `turns[k]` instead of `(cur.rotation,)`; hints keep their location, the scan tries each rotation. Update the module docstring (rotation now changes; face does not).
- [ ] Suite; bench; commit with the tally and baseline.

### Task 4: Time, docs, release

- [ ] Core board copy: resolve time before and after. If over 1.5x, profile the scored scan and reduce (for example, the coarse pass at one rotation, the fine pass at all four) with the bench re-run.
- [ ] `api.md`, `SKILL.md`, `migration.md` (To 0.28), BACKLOG to Done; version bump to 0.28.0; commit.
