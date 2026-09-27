# Keeping Routed Copper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `placemat route <script> --adopt NET ...` keeps the router's new copper on those nets in `<script stem>.routes.json`, relative to pads; every run draws it while the parts it joins stand as they did, and drops a net with a finding when one has moved.

**Architecture:** A new module `src/placemat/routes.py` holds the entry model, the diff of a placed and a routed board into entries, the file, and the check-and-resolve of an entry against an occupancy. `Board.resolve(routes=)` draws held entries as one copper batch after the other copper; the runner and preview read the file as they read the lock; the CLI adopts and lists. The route itself needs no change: adopted copper is locked input copper on the written board, which the router keeps (`--keep-input-copper`), so the net arrives connected and counts as closed.

**Tech Stack:** Python 3.12, pytest; pcbnew for reading boards (no router run in the tests).

**Spec:** `docs/superpowers/specs/2026-09-27-adopt-routes-design.md` (approved 2026-09-27)

## Global Constraints

- A point on a pad of its net is stored as that pad; any other point, and a via, as an offset from the net's nearest pad in that pad's part's frame (`lock._turn`, x mirrored on the back as `PadRef.local` does).
- The file is `<script stem>.routes.json`, format 1, entries by net; a net is adopted whole.
- A net's entry is dropped when a part it joins has moved or turned relative to the others, or changed face, beyond `route.adopt_tolerance` (a setting, default 0.001 mm and 0.01 degree); the finding names the part.
- The script fingerprint (run id) includes the routes file, as it includes the lock.
- Generic wording; plain ASCII; no tool or session references in commits; bench before placement commits.

## Review Focus

1. A track end exactly on a pad's edge, and a pad of another net under a point: the point binds to its own net's pad only.
2. A part on the back face: offsets resolve to the same board points after a turn.
3. A net adopted twice: the new entry replaces the old.
4. An entry whose part is missing from the board (removed from the capture): dropped with a finding, not an exception.
5. The adopted copper crossing copper the script declares: reported as a copper finding, as any copper is.

---

### Task 1: `routes.py`: entries, adoption, file, resolution

**Files:** Create `src/placemat/routes.py`; Test `tests/test_routes.py`.

**Interfaces (Produces):**
- `RoutePoint = dict` either `{"pad": [ref, number]}` or `{"anchor": [ref, number], "offset": [dx, dy]}`.
- `RouteEntry(net: str, tracks: tuple, vias: tuple, parts: dict, adopted: str)`: `tracks` of `{"layer", "width", "a": RoutePoint, "b": RoutePoint}`, `vias` of `{"at": RoutePoint, "size", "drill"}`, `parts` `{ref: [x, y, rotation, face]}`.
- `entries_from(placed: BoardGeometry, routed: BoardGeometry, nets) -> list[RouteEntry]`.
- `path_for(script) -> Path`; `read(path) -> list[RouteEntry]`; `write(path, entries)`; `merged(old, new) -> list` (new replaces a net).
- `resolve(entry, occ, tolerance) -> (list[Track], list[Via]) | str` (a string is why it was dropped).

- [ ] **Step 1: Failing tests** (pure, synthetic `BoardGeometry` from `tests.fixtures`):
  - two parts U1 (net X on pad 2) and R1 (net X on pad 1); a "routed" geometry equal to the placed one plus two X tracks (pad U1.2 to a bend point, bend point to pad R1.1) and one X via at the bend: `entries_from` gives one entry, its track ends bound as pads and the bend point as an anchor offset from the nearer pad, the via likewise, `parts` holding U1 and R1;
  - `write` then `read` gives equal entries; `merged` replaces the X entry;
  - `resolve` against an occupancy with both parts where they were gives the same two tracks and via to 1e-6 mm; with both parts moved together by (+5, +3) and turned 90 about U1, the tracks are the originals moved and turned; with R1 alone moved 1 mm, a string naming R1; with R1 absent from the board, a string naming it;
  - a bend point over a pad of another net Y binds as an anchor offset, not to the Y pad.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_routes.py` - FAIL (no module).
- [ ] **Step 3: Implement** `routes.py` per the interfaces. New copper is routed copper of the named nets whose (kind, layer, rounded ends or centre, width or size) is not in the placed board's copper. Binding a point: the pads of the entry's net whose outline contains it (`geometry.point_in_polygon`, within 1e-6); else the nearest pad of the net by centre distance, offset = `_turn(p - pad_centre, -rotation)` with x negated for a back-face part. Relative check: the entry's first part (sorted refs) is the reference; each other part's location relative to it, turned by minus its rotation, and its rotation relative to it, compared with what was stored within the tolerance; a changed face drops.
- [ ] **Step 4: Run** - PASS. **Step 5: Commit** "routes: routed copper kept relative to its pads".

### Task 2: `Board.resolve(routes=)` draws held entries

**Files:** Modify `src/placemat/layout.py` (`resolve` signature and the copper batches), `src/placemat/project.py` (`script_fingerprint` hashes the routes file), `src/placemat/settings.py` (`route_adopt_tolerance`); Test `tests/test_routes.py` (append).

- [ ] **Step 1: Failing tests:** a board with the two parts placed as in Task 1 and `resolve(routes=[entry])` gives the entry's tracks and via in `plan.copper` and `plan.adopted == {"X": "held"}`; with R1 placed 1 mm away, no X copper, `plan.adopted["X"]` names R1, and a finding "adopted route X dropped: ..."; the fingerprint of a script changes when its routes file changes.
- [ ] **Step 2: Run** - FAIL.
- [ ] **Step 3: Implement:** `resolve(..., routes=None)`; after `self._plan_copper(occ, ctx, other_copper, ...)`, for each entry `routes.resolve(entry, occ, tol)`; held entries' ops go through one more `_plan_copper` batch as a copper intent per net (key `"adopted <net>"`), so conflicts are findings; dropped ones become `Finding("route", "adopted route %s dropped: %s; the router routes it again")`. `plan.adopted` records each. The fingerprint appends `routes\0<file text>` when the file exists.
- [ ] **Step 4: Run** - PASS. **Step 5: Commit** "A run draws adopted routes while their parts stand as they did".

### Task 3: The CLI, the runner, docs and a KiCad check

**Files:** Modify `src/placemat/cli.py` (`route --adopt NET ... | --adopt-all`, `routes <script> [--release NET ...]`), `src/placemat/runner.py` and `src/placemat/previewer.py` (read the routes file and pass it to `resolve`, as the lock is), docs (`api.md`, `SKILL.md`, `migration.md` To 0.43, `BACKLOG.md`); Test `tests/test_routes_kicad.py`.

- [ ] **Step 1: KiCad test (no router run):** copy the breakout, make a "routed" copy by adding one track on a net between two of its pads with pcbnew, call the adopt path (`routes.entries_from(read_board(placed), read_board(routed), [net])`), write the file beside a scratch script path, resolve the board with it and `apply_plan`: the written board carries the track, and DRC's real violations are unchanged.
- [ ] **Step 2: CLI:** `placemat route <script> --adopt NET ...` routes as today, then writes the entries for the named nets (from the routed copy against the routed input) merged into the file, and prints how many tracks and vias each net kept; `--adopt-all` takes every net the route closed. `placemat routes <script>` lists entries (net, tracks, vias, parts, adopted) and `--release NET ...` removes them.
- [ ] **Step 3: Runner and preview:** read `routes.path_for(script)` and pass `routes=` to `resolve`; the run's `adopted` line lists held and dropped nets.
- [ ] **Step 4: Docs:** api.md (route's `--adopt`, the `routes` command, the file in "the files placemat writes", a paragraph on held and dropped); SKILL.md (keep a fragment's routed nets with `route --adopt`; never paste routed coordinates into a script); migration.md `## To 0.43` (a hand-written fold-back of routed copper can go); BACKLOG.md Done.
- [ ] **Step 5:** bench, full suite. **Step 6: Commit** "route --adopt and placemat routes; the runner draws the routes file".
