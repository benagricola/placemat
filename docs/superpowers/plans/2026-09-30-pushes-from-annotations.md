# Pushes from part annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pairs of parts (a source carrying `Pm.Emits`, a sensitive part carrying `Pm.Limit`) hold each other apart through the machinery `board.push` already uses, and `placemat check` reports the exposure.

**Architecture:** A new pure module `src/placemat/exposure.py` parses the four `Pm.*` keys off footprint fields and does the frame arithmetic. At each `_settle`, `Board` turns the pairs the item is in (the other part already placed) into `Push` objects and hands them to the existing `_reserve_pushes` (hard disc), `Scorer` (soft price), the wide scan and the step note. A summed hard check across several sources goes through the scan's `accept` hook. `checks.run_checks` gains an `exposure` check built on the same module.

**Tech Stack:** Python, pytest, pcbnew-free fixtures (`tests/fixtures.py`).

**Spec:** docs/superpowers/specs/2026-09-30-pushes-from-annotations-design.md

## Global Constraints

- Project-agnostic: no project, board, module, part or part number named anywhere. Examples use a magnet, a field sensor, a converter, a crystal, U1, M1.
- Tunables are settings with defaults, never literals. Plain ASCII only.
- New fields on declarations that feed reuse/lock digests carry `metadata={"omit_default": True}`; the digest parity tests pass unchanged.
- Delete board items with `board.Delete`, never `board.Remove`.
- Tests: targeted files only, never the full suite.
- Commits carry no reference to any assistant, session or co-author.

## Review Focus

- A part carrying both `Pm.Emits` and `Pm.Limit` of one kind (heat both ways): judged by whichever is placed second, no cycle (Task 6).
- A sensitive part already over its limit from sources placed before the new one: the new source's hard disc is skipped, the soft price stays (Task 5).
- A source inside a cell, turned and flipped with the cell: the emission point follows (Task 5).
- Sensitive and source members in the same cell: no pair (Task 4).
- Unit mismatch between a source and a limit of one kind, or within one part: refused at run start naming both parts (Task 2).
- A `pad:N` naming a pad the part lacks: refused, naming the part (Task 1).

---

### Task 1: Parse the four keys

**Files:**
- Create: `src/placemat/exposure.py`
- Test: `tests/test_exposure.py`

**Interfaces:**
- Produces: `Emission(kind, value, unit, r_ref, falloff)` with `.at(r)` and `.radius(limit)`; `Source(ref, emissions, at)` where `at` is None, `("xy", x, y)` or `("pad", number)`; `Sensitive(ref, limits, senses)` where `limits` is a tuple of `(kind, value, unit)` and `senses` is a pad number or None; `Annotations(sources, sensitives)` dicts keyed by refdes; `read(geometry) -> Annotations`, raising `ValueError`.

- [ ] Write failing tests: two-kind `Pm.Emits`; `Pm.EmitsAt` as a point and as a pad; two-kind `Pm.Limit`; `Pm.SensesAt`; keys read case-insensitively (`Pm.Emitsat`); a malformed value and a missing pad raise `ValueError` naming the part.
- [ ] Run, watch them fail (no module).
- [ ] Implement `exposure.py`.
- [ ] Run, pass. Commit.

### Task 2: Unit mismatch refused at run start

**Files:**
- Modify: `src/placemat/exposure.py` (`read`), `src/placemat/layout.py` (`Board.resolve` calls `read` and keeps `self._annotations`)
- Test: `tests/test_exposure.py`, `tests/test_annotated_push.py`

- [ ] Failing tests: `read` raises naming both refs and both units when a source's unit and a limit's unit differ for one kind (also two sources); `board.resolve()` raises the same.
- [ ] Implement: first-seen unit per kind, then compare.
- [ ] Pass. Commit.

### Task 3: Frame arithmetic

**Files:**
- Modify: `src/placemat/exposure.py` (`local_to_board(location, rotation, face, x, y)`)
- Test: `tests/test_exposure.py`

- [ ] Failing tests: front at rotation 0 is a translation; rotation 90 turns as `Transform.rotate`; back face mirrors x before turning.
- [ ] Implement with `geometry.Transform`. Pass. Commit.

### Task 4: A sensitive part placed second is an equivalent board.push

**Files:**
- Modify: `src/placemat/layout.py` (`Push` gains `label`, `kind`, `unit`, `hard_limit`, `target_local`, all `omit_default`; `Board._annotated_pushes`; `_settle` and `_replay_settle` reserve them with `i.pushes`; `_push_at` shared by the scorer and the note)
- Test: `tests/test_annotated_push.py`

**Interfaces:**
- Produces: `Board._annotated_pushes(occ, i) -> list[Push]`; `_reserve_pushes` returns the same (source point, Push) pairs for declared and annotated pushes.

- [ ] Failing tests: a placed source and a searched sensitive part reserve the same disc as the equivalent `board.push` (same radius in the reservation's `why`), refuse a firm spot inside it, and land at the same place as the equivalent `board.push`; a source and a limit of different kinds do not pair; members of one cell do not pair.
- [ ] Implement.
- [ ] Pass. Commit.

### Task 5: A source placed second, several sources add, the source point

**Files:**
- Modify: `src/placemat/layout.py` (`_annotated_pushes` case for the item as source; baseline of other placed sources; `_exposure_accept` joined to the rider `accept`, prune off while it is set)
- Test: `tests/test_annotated_push.py`

- [ ] Failing tests: two placed sources of a kind whose values each pass but whose sum exceeds the limit refuse a spot (hard sum); a source placed after the sensitive part stays outside the disc of its own emission point; a source whose `Pm.EmitsAt` is off its origin pushes from that point, turned and flipped with the footprint; a source in a cell turned by the cell; a sensitive part already over its limit from earlier sources does not make the new source unplaceable.
- [ ] Implement.
- [ ] Pass. Commit.

### Task 6: Order

**Files:**
- Test: `tests/test_annotated_push.py`; code from Tasks 4 and 5

- [ ] Failing tests: the part placed second carries the disc whichever it is (both declaration orders); two parts that both emit and limit heat resolve and no cycle is raised; no `needs` is added to either intent.
- [ ] Fix whatever fails. Commit.

### Task 7: Step notes and board.push adding

**Files:**
- Modify: `src/placemat/layout.py` (`_exposure_notes`, appended to the step note)
- Test: `tests/test_annotated_push.py`

- [ ] Failing tests: the pushed item's step note gives each kind's value where it landed, the limit, and the nearest source; a `board.push` on an annotated item adds to the annotated pushes (both discs reserved, the soft price of both counted).
- [ ] Implement. Pass. Commit.

### Task 8: The exposure check

**Files:**
- Modify: `src/placemat/checks.py` (`exposure(geometry)`, called from `run_checks`)
- Test: `tests/test_checks_exposure.py`

- [ ] Failing tests: pass and fail verdicts per sensitive part and kind, naming the contributing sources; no source of a kind is a pass at 0; a parse error is an unjudged verdict, not a crash; a board with no annotations adds no verdict.
- [ ] Implement. Pass. Commit.

### Task 9: Docs

**Files:**
- Modify: `skills/placemat/references/capture.md`, `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, the migration notes

- [ ] capture.md: the four keys in the annotations table and a short section on sources and limits, with examples.
- [ ] api.md: annotated pushes beside `board.push`; the exposure check.
- [ ] SKILL.md: a line in "A fresh board" step 3: add `Pm.Emits`/`Pm.EmitsAt` to each source and `Pm.Limit`/`Pm.SensesAt` to each sensitive part in the capture; `board.push` is for a source no footprint carries; a part placed to measure a source carries no limit for that kind.
- [ ] migration.md: `## Unreleased` at the top.
- [ ] Commit.

### Task 10: Targeted regression and bench

- [ ] Run tests/test_push.py, tests/test_annotated_push.py, tests/test_exposure.py, tests/test_checks_exposure.py, the digest parity tests, the checks tests.
- [ ] Run `fixtures/bench.py --jobs 2` once; put the tally in the final commit's message.
