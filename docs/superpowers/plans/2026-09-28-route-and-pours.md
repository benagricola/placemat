# The router and the board's pours - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The router's input copy keeps other nets' tracks out of each partial inner-layer pour of a net the route leaves out; the routed copy has the guard removed.

**Architecture:** A second guard beside `guard_footprint_copper` in `src/placemat/kicad/route.py`: `guard_partial_pours` adds a track-forbidding rule area (vias, pads and fills allowed) over each such zone's outline on its inner layer, named `placemat pour <net> <layer>`. `restore_footprint_graphics` deletes it with the footprint guards. `route_board` calls it after the placement DRC, and the report counts the pours.

**Tech Stack:** Python, pcbnew, KiCadRoutingTools (read-only; its obstacle map honours rule areas per layer, `py_router/obstacle_map.py:873`).

**Spec:** docs/superpowers/specs/2026-09-28-route-and-pours-design.md

## Global Constraints

- Generic wording; plain ASCII; never modify ~/work/KiCadRoutingTools.
- Commit with `git -c user.name="<owner name>"`; no Claude/Anthropic/session reference.
- No placement change: no bench run needed (the router's input copy only).

## Review Focus

1. A zone on several layers (F.Cu and In2.Cu): only its inner layers get a guard.
2. A pour of a net that is routed (not excluded): no guard.
3. A pour covering at least `route.plane_share`: no guard (its layer is dropped from the default list, or is routed as the script asked).
4. The routed copy after restore: no `placemat pour` rule area left, the pour itself untouched.
5. A zone with holes in its outline: the guard carries the holes.

---

### Task 1: The guard and its removal

**Files:**
- Modify: `src/placemat/kicad/route.py` (`POUR_GUARD`, `guard_partial_pours`, `restore_footprint_graphics`, `route_board`, `RouteReport`)
- Test: `tests/test_route_pours.py`

**Interfaces:**
- Produces: `guard_partial_pours(pcb_path: str, nets, layers, share: float) -> list[str]` ("NET on LAYER" per guard); `RouteReport.pours_kept: list`.

- [ ] **Step 1: failing tests** (needs_kicad, needs_breakout; no router): a copy of the breakout made four-layer, with a zone of net N on In2.Cu covering a 10 x 10 mm square:
  - `guard_partial_pours(pcb, {N}, ["F.Cu", "In2.Cu", "B.Cu"], 0.9)` returns `["N on In2.Cu"]`, and the saved board has a rule area on In2.Cu only, named `placemat pour N In2.Cu`, forbidding tracks and allowing vias, pads and zone fills, with the zone's outline;
  - N not in the nets: none; In2.Cu not in the layers: none; a zone on F.Cu: none; a zone covering the whole board: none;
  - `restore_footprint_graphics(pcb_in, pcb_out)` on a guarded copy leaves no `placemat pour` rule area and keeps the zone.
- [ ] **Step 2:** run -> FAIL (no `guard_partial_pours`).
- [ ] **Step 3:** implement `guard_partial_pours` (board outline area from `GetBoardPolygonOutlines`, as `_plane_zones`; each non-rule-area zone whose net is in `nets`, per copper layer in its layer set that is inner and named in `layers`, outline area under `share` of the board's), the restore's deletion of `POUR_GUARD` zones, the call in `route_board` after `guard_footprint_copper` with `excluded` and the resolved `layers`, and `pours_kept` in the report, its summary ("other nets kept out of N pour(s)") and `as_dict`.
- [ ] **Step 4:** tests PASS; `uv run pytest -q tests/test_route_footprint_copper.py tests/test_route_settings.py` PASS.
- [ ] **Step 5:** commit "The router keeps other nets' tracks out of a partial inner-layer pour".

### Task 2: A router run over a partial pour

- [ ] **Step 1: test** (needs_router, in tests/test_route_breakout.py style): the four-layer breakout copy with a partial In2 pour of an excluded net, routed quick on F.Cu, In2.Cu, B.Cu: no track of another net on In2.Cu inside the pour's outline, and `report.pours_kept == ["N on In2.Cu"]`.
- [ ] **Step 2:** run; if it passes on the first run it confirms the router honours the guard (Task 1's tests were the failing ones); record the numbers.
- [ ] **Step 3:** api.md route paragraph (inner-layer pours of excluded nets kept clear; fills need not be switched off for routing); migration "To 0.50" line; BACKLOG entry to Done. Commit "Docs: the router and the board's pours".
