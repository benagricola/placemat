# Footprint Copper Through The Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The router is kept off footprints' copper graphics by rule areas in its input copy, and the routed copy gets those graphics back (the router's writer moves outer-layer ones to silk), so DRC of the routed copy is of the real copper.

**Architecture:** Two pcbnew helpers in `src/placemat/kicad/route.py`: `guard_footprint_copper(pcb)` adds a named rule area (no tracks, no vias) over each footprint copper graphic on its layer; `restore_footprint_graphics(pcb_in, pcb_out)` puts each footprint's graphic shapes back from the input copy and deletes the guards. `route_board` calls the first after the before-DRC and the second before filling zones and the after-DRC; `RouteReport.restored_graphics` carries the count.

**Tech Stack:** Python 3.12, pcbnew, pytest (KiCad tests, no router run).

**Spec:** `docs/superpowers/specs/2026-09-27-routed-footprint-copper-design.md` (approved 2026-09-27)

## Global Constraints

- The router is not changed; only placemat's copies are.
- Guards are named `placemat footprint copper <ref>` so the restore step finds exactly its own.
- A guard's outline is the graphic's own copper outline (`read._copper_art`'s polygons, stroke included), on that graphic's layer only.
- Footprints are matched between the copies by UUID; only `PCB_SHAPE` graphics are replaced; pads, fields and texts are the routed copy's.
- Generic wording; plain ASCII; no tool or session references in commits.

## Review Focus

1. A footprint whose copper graphic touches its own pads: the guard must not stop the router reaching them (check on the KiCad test: the pad's own copper is outside the guard's forbidden items; report what the router does if the check shows otherwise).
2. A footprint flipped to the back: its graphics' layers after restore.
3. A board with no footprint copper: nothing added, nothing restored, the copy byte-identical in footprints.
4. `router_breaches` now sees the guards as rule areas: a crossing is reported as a breach naming the footprint.
5. The before-DRC is taken before the guards are added, so `valid` is unchanged.

---

### Task 1: The two helpers

**Files:** Modify `src/placemat/kicad/route.py`; Test `tests/test_route_footprint_copper.py`.

- [ ] **Step 1: Failing KiCad tests:** a copy of the breakout with a net-less F.Cu `fp_poly` added to one footprint (pcbnew); `guard_footprint_copper` gives one rule area named for it on F.Cu forbidding tracks and vias, and returns 1; a "routed" copy made from the guarded one with that graphic moved to F.SilkS and a track added across it; `restore_footprint_graphics(guarded, routed)` returns `{"footprints": 1, "items": 1}`, the graphic is on F.Cu again, no guard is left, and `run_drc` on the routed copy reports the track against the graphic. A board with no footprint copper: 0 guards, restore returns zeros.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_route_footprint_copper.py` - FAIL.
- [ ] **Step 3: Implement** both helpers.
- [ ] **Step 4: Run** - PASS. **Step 5: Commit** "route: guard footprint copper from the router and put it back after".

### Task 2: Wiring, report, docs

**Files:** Modify `src/placemat/kicad/route.py` (`route_board`, `RouteReport.restored_graphics`, `summary()`), `src/placemat/cli.py` (the route line); docs (`api.md` route paragraph, `migration.md` To 0.46, `BACKLOG.md` Done); Test `tests/test_route_footprint_copper.py` (append: `RouteReport.summary()` names restored graphics when non-zero, and `as_dict` carries them).

- [ ] **Step 1: Failing test**, **Step 2: implement**, **Step 3:** run the new tests, the route tests (they skip without the router) and the full suite. **Step 4: Commit** "The routed copy keeps footprint copper".
