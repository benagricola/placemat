# Pad Vias In The Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A part (or the cell or block holding it) carries, during its search, the vias the script declares at its pads, so it lands where they clear the other face; a planned via's copper finding names it as a via.

**Architecture:** `Board.via(net, PadRef)` (a via at a pad, not a `FreeSpot`) records the pad, its local offset and the via's size, drill and net. When `resolve` builds the occupancy, each such via becomes a `through` ring and a `hole` on the pad's part's `ItemGeometry`, in the part's generated frame, so every transform, scan and cell geometry carries it as it carries the part's pads. `Occupancy._conflict` names a planned via (a `through` shape with no owner) as "via NET at (x, y)".

**Tech Stack:** Python 3.12, pytest (pure).

**Spec:** `docs/superpowers/specs/2026-09-27-pad-vias-in-search-design.md` (approved 2026-09-28)

## Global Constraints

- Only a via at a pad with no board-frame offset (`PadRef`, `PadRef.local(...)`) is carried: a board-frame offset does not turn with the part.
- The carried shapes are the via's own: net, `via_ring(size)`, `hole_shape(drill)`, owned by the pad's part.
- A carried via and the planned one are the same copper: the carried shapes add nothing a later copper check reports twice.
- Generic wording; plain ASCII; bench before the commit; no tool or session references in commits.

## Review Focus

1. A fixed part's carried via and its planned via (planned before the search) at one spot: no hole-to-hole finding between them, no double counting.
2. A cell member's pad via: the cell carries it (the cell geometry is built from its members' shapes).
3. A back-face part: the carried via flips with it.
4. The native scan: the carried shapes are ordinary `through`/`hole` shapes it already judges.
5. A via at a pad by net name or pin name, not number.

---

### Task 1: Carry declared pad vias

**Files:** `src/placemat/layout.py` (`via`, `resolve` after the occupancy is built), `src/placemat/occupancy.py` (`carry(ref, shapes)`); Test `tests/test_pad_vias_carried.py`.

- [ ] **Step 1: Failing tests:** a front part searched `Near` a fixed back part whose pads sit under the hint, a GND via declared at the front part's GND pad: the front part lands where the via's ring clears the back pads by the clearance (and without the via declaration it lands over them - the test shows the difference); a back-face searched part with a via at its pad, the same; a cell member's pad via held off another part by the cell's search.
- [ ] **Steps 2-4:** implement, run, **commit** "A part carries the vias declared at its pads through its search".

### Task 2: A planned via named as a via; docs; bench

**Files:** `src/placemat/occupancy.py` (`_conflict` wording), docs (`api.md` the via paragraph, `migration.md` To 0.48, `BACKLOG.md`); Test (append): a planned via over another net's pad is a copper finding that says "via GND at (".

- [ ] Failing test, implement, bench, full suite, **commit** "A planned via is named as a via".
