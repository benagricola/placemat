# Pad Edge Tap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `PadRef(part, pad, edge=Edge.X, along=Along.Y)`, a track waypoint touching that edge of the pad.

**Architecture:** `PadRef` gains `edge` and `along` (digest-omitted when unset). The track planner resolves such a point with the track's width (`_edge_point`), as it resolves `Past`; `_past_point` does the same for `across=`. `_locate`, which every other consumer of a point goes through, refuses one.

**Tech Stack:** Python, pytest, pcbnew and kicad-cli for the DRC test.

**Spec:** docs/superpowers/specs/2026-09-30-pad-edge-tap-design.md

## Global Constraints

- `edge` is named in the board frame, as `Past`'s is.
- `along`: along a north or south edge `START` is the west end, along an east or west edge the north end; default `MID`.
- As a track waypoint the point is half the track's width outside the edge; at `START`/`END` also half a track in from the corner.
- `edge`/`along` are left out of the digest when unset; `along` without `edge` is refused.
- Project-agnostic wording in code, tests and docs.

## Review Focus

- A pad whose edge carries copper only at a point (round, oval, or turned off the right angle): `MID` touches that point, `START`/`END` are refused with the pad named.
- A track and pad that only touch at a line may read as unconnected to KiCad: the point sits a few microns inside touching, so the copper overlaps (`_EDGE_OVERLAP`, 0.005 mm), and the DRC test checks connection.
- A tapped PadRef reaching `_locate` from any other API (a via's `at=`, a pair's end, a placement) is refused, not silently read as the pad's centre.
- A tapped PadRef among a `Past`'s items is refused at declaration.
- `.offset()`/`.local()` on a tapped PadRef keep the edge.

---

### Task 1: PadRef edge and along

**Files:** Modify `src/placemat/values.py` (PadRef). Test: `tests/test_pad_edge_tap.py`.

- [ ] Failing tests: `along` without `edge` refused; `edge` not an Edge refused; `along` not an Along refused; `reuse.canonical` of a plain PadRef has no `edge`/`along`; `.offset()` keeps `edge`/`along`.
- [ ] Fields `edge: object = field(default=None, metadata={"omit_default": True})`, `along` the same; validation in `__post_init__`; `offset`/`local` pass them on.
- [ ] Run, commit.

### Task 2: The point, in tracks and Past's across

**Files:** Modify `src/placemat/layout.py` (`track`'s plan, `_past_point`, `_locate`, `_check_past`, new `_edge_point`). Test: `tests/test_pad_edge_tap.py`.

- [ ] Failing tests on a two-pad part R1 at (20, 20), pads 1x1 at x 18.1..19.1 and 20.9..21.9:
  - a track from `PadRef(R1, 1, edge=EAST)` south through the gap: its first point is (19.1 + w/2 - overlap, 20); its copper meets pad 1 only in a strip at x 19.1;
  - `along=Along.END` on the south edge: the copper ends flush with the pad's east side;
  - the part turned 90: the edge is the board frame's;
  - `Past([pad], EAST, across=tap)` is level with the tap;
  - a round pad at `END` refused; `MID` on it touches;
  - a via `at=` a tapped PadRef refused; a tapped PadRef among Past's items refused.
- [ ] `_edge_point(board, occ, width, ref)`: the pad's copper polygons; the box; the copper span along the named edge (points within 1e-3 of it); the point; the refusals. Track plan: a tapped PadRef resolves through it and is not a pad end for `octilinear`. `_past_point`: `across` through it. `_locate`: refuses. `_check_past`: refuses one among the items.
- [ ] Run the new tests and the track, Past and label tests; commit.

### Task 3: KiCad DRC on a shunt's taps, docs

**Files:** Test `tests/test_pad_edge_tap.py`; modify `skills/placemat/references/api.md`, `skills/placemat/references/migration.md`.

- [ ] A test board: an upright shunt with a 0.76 mm gap, both taps in it at `MID`, each out to a sense pad; drawn into a pcbnew board with the same pads and nets; `kicad-cli pcb drc` reports no clearance violation and no unconnected item on either sense net.
- [ ] api.md: `PadRef`'s `edge=`/`along=` beside `Past`. migration.md: Unreleased note.
- [ ] Run, commit.
