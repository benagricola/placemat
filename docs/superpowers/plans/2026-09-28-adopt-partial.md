# Keeping The Closed Parts Of An Open Net Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `route --adopt ... --partial` keeps, for a net the route left open, each island of new copper that joins two or more of the net's pads, or a pad and a plane of the net, as its own partial entry; later passes add entries.

**Architecture:** `routes.islands(placed, routed, net)` groups the net's new copper (`added_copper`) into islands by touch, a pad of the net joining what touches it, and names each island's terminals: the net's pads it touches, and its vias inside a zone of the net. `routes.adoptable(..., partial=True)` builds an entry per open net from the islands with two or more terminals (`RouteEntry.partial = True`). `routes.merged` appends a partial entry rather than replacing the net's. The CLI adds `--partial`; `routes` lists the flag; the summary counts islands.

**Tech Stack:** Python 3.12, pytest (pure, synthetic geometries), pcbnew for one KiCad test.

**Spec:** `docs/superpowers/specs/2026-09-28-adopt-partial-design.md` (approved 2026-09-28)

## Global Constraints

- Touch is overlap of copper outlines on a common layer (a via on every layer); a pad of the net joins what touches it.
- A terminal is a pad of the net, or a via of the net inside one of the net's zones (a plane) on some layer.
- A shorted net is never kept, partial or whole.
- A whole-net adoption still replaces the net's entries (partial ones included); a partial adoption appends.
- Generic wording; plain ASCII; no tool or session references in commits.

## Review Focus

1. Two islands joined only through a pad: one island (the pad joins them).
2. An island touching script copper of the net (a FreeSpot tail): the script copper is not new, and joins nothing for the count - it is a terminal only if it is a pad or plane via.
3. A partial entry and a later whole adoption of the same net: the whole one replaces all of them.
4. A partial entry's parts dropping on their own while another entry of the net holds.
5. `placemat routes --release NET` releases every entry of the net.

---

### Task 1: Islands and partial entries

**Files:** `src/placemat/routes.py` (`islands`, `RouteEntry.partial`, `adoptable(partial=)`, `merged`, `read`/`write`, `describe`, `release`); Test `tests/test_adopt_partial.py`.

- [ ] Failing tests (synthetic): the three-island case of the spec's verification; a second partial adoption appends; a whole adoption replaces; release drops all of a net's entries; a shorted net keeps nothing. Implement; pass; **commit** "Islands of an open net's new copper kept as partial entries".

### Task 2: The CLI, the report, docs

**Files:** `src/placemat/cli.py` (`--partial`, the adopt lines), `src/placemat/routes.py` (`summary` counts entries by net), docs (`api.md`, `SKILL.md`, `migration.md` To 0.50, `BACKLOG.md`); Tests: KiCad (the breakout, no router): a routed copy with one of a net's two new tracks removed keeps the other with `--partial` and none without.

- [ ] Failing test, implement, full suite, **commit** "route --adopt --partial".
