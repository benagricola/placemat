# Courtyard Polygons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A part whose courtyard is not a rectangle is claimed by KiCad's courtyard polygon instead of the box round it, in the occupancy (collisions, the keep-in by corners) and the native scan; rectangular courtyards are unchanged.

**Architecture:** `read.py` stores KiCad's courtyard polygon (`FOOTPRINT.GetCourtyard`, board frame, outline 0 of the part's own face) as `Footprint.courtyard_poly`. `occupancy._fp_shapes` uses it for the courtyard shape when it covers less than `place.courtyard_polygon_share` of its box, and such a part's courtyard margin is 0 (KiCad's polygon has no stroke to allow for). The native scan already takes a courtyard as a polygon and the margins from Python, so it needs no change; the parity tests cover the new shapes.

**Tech Stack:** Python 3.12, pcbnew, pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-courtyard-polygons-design.md` (approved 2026-09-27)

## Global Constraints

- `place.courtyard_polygon_share` (default 0.98) is a setting; a courtyard polygon covering at least that share of its box keeps the box and its margin.
- A polygon courtyard's margin is 0 in `Occupancy._margins` (and so in the native scan).
- The rank, pockets and cell boxes keep `courtyard_box`.
- Generic wording; plain ASCII; bench before the placement commit; no tool or session references in commits.

## Review Focus

1. Two polygon courtyards whose boxes overlap within the touch allowance but whose polygons overlap: refused (the depth shortcut must not pass them).
2. A flipped part's polygon: mirrored with the part (the occupancy transform covers every shape).
3. A footprint with courtyards on both faces, or several outlines: which is taken.
4. The physical envelope: a drawn part has no courtyard shape, so nothing changes there.
5. Bench: no module's placement moves unless it has a non-rectangular courtyard; any that does is named in the commit.

---

### Task 1: Read the courtyard polygon

**Files:** `src/placemat/board_geometry.py` (`Footprint.courtyard_poly: tuple = ()`), `src/placemat/kicad/read.py`; Test `tests/test_courtyard_polygons.py` (KiCad: a footprint with a triangular courtyard added reads back that triangle; a rectangular one reads a 4-point polygon covering its box).

- [ ] Failing test, implement, pass, **commit** "Read each part's courtyard polygon".

### Task 2: Claim a non-rectangular courtyard by its polygon

**Files:** `src/placemat/settings.py` (`place_courtyard_polygon_share`), `src/placemat/occupancy.py` (`_fp_shapes`, `_margins`); Tests `tests/test_courtyard_polygons.py` (pure: two sector parts about one centre 35 degrees apart legal, 5 apart refused; a sector turned 45 degrees at a disc's centre whose box corner is past the keep-in and polygon inside, fixed: no finding), `tests/test_native_conflict.py` (a sector courtyard among the fuzzed shapes).

- [ ] Failing tests, implement, pass; bench; full suite; docs (`api.md` placement rules, `migration.md` To 0.48, `BACKLOG.md`); **commit** "A courtyard that is not a rectangle is claimed by its polygon".
