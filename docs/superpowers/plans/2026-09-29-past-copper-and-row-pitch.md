# Past over copper, row pitch, lane pads, planes over parts - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the four forms in the spec, so that module scripts can express
their lanes, a pitched pair and a bounded plane as intent, with no computed
coordinates.

**Architecture:**
- Part A (Tasks 1-3):
  - `Past` grows to hold vias and tracks, and gains `across=` and `lane=`.
  - Its point is resolved in one place, `_past_point`, from copper the plan
    already holds.
  - The resolved point is used in three places: as a track point, as a
    via's `at=`, and as a `Beside` pair-align target.
- Part B (Tasks 4-5):
  - `row(of=)` takes `centre=PadRef` and `pitch=`.
  - `plane()` takes `over=`, read from the same drawn envelope
    `keepout(item)` uses.
- The two parts touch different code and run in separate worktrees.

**Tech Stack:** Python, pcbnew (KiCad 9), pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-past-copper-and-row-pitch-design.md` (approved 2026-09-29)

## Global Constraints

- TDD: a failing test first for every behaviour, watched failing, then the code.
- Fixed sets are enums (`Edge`, `Along`), never strings. No coordinate
  arithmetic in examples, docs or migration tests beyond the hand-computed
  side of a migration comparison.
- Generic wording in source, tests, docstrings, skill docs and commit
  messages: no real module, part, board or component-type names (no USB,
  FET, pogo, TPS..., fairing). Use "a connector's contact row", "a
  driver's pin", "two pins at a mechanical pitch".
- Tunables are settings, never literals.
- Plain ASCII only.
- Reuse/lock digests: any new field on a value or intent that feeds
  `reuse.canonical` carries `metadata={"omit_default": True}` so existing
  digests are unchanged. `tests/test_copper_digest_parity.py` and
  `tests/test_enum_digest_parity.py` must still pass.
- Docs:
  - `skills/placemat/references/api.md`: the relevant paragraphs and the
    intent index table rows.
  - `skills/placemat/references/migration.md`: a `## Unreleased` section
    above `## To 0.54.1`.
- Commits:
  - `git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit`.
  - The message contains no Claude/Anthropic/session/Co-Authored-By
    reference; check it with
    `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`,
    which must print nothing.
- Tests: targeted files only, via
  `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/<files>`
  (after `cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/`).
  Never run the full suite, the bench or the router.

## Review Focus

- A `Past` naming a via or track declared after it: a finding naming both,
  not a KeyError. Same order rule as a track ending on a via.
- A `Past` naming a via that found no spot: the point is not drawn, and the
  note says which via; never a crash.
- `across=` a pad that is not among `items`: allowed, since it only sets the
  across line.
- `row(of=, pitch=)` with items of different sizes: the pitch is between
  centres, and the refusal names the pair that is too close.
- `plane(over=)` with one item placed by `Beside` and another in a cell: the
  outline covers both.

---

### Task 1: Past holds vias and tracks, with across=

**Files:**
- Modify: `src/placemat/values.py` (class `Past`, around line 524)
- Modify: `src/placemat/layout.py`:
  - `_past_point` (around line 5264);
  - `_refs_in` (around line 5349);
  - `_plan_copper` (around line 4059): record each intent's planned ops;
  - the copper context class (around line 5120): add `ops_at: dict`.
- Test: `tests/test_past_copper.py` (new)

**Interfaces:**
- `Past(items, edge, across=None, lane=None)`. `items` is a tuple of
  `PadRef`/`CellPadRef`/`CopperIntent` (what `board.via`, `board.vias` or
  `board.track` returns). `pads` stays readable as an alias property of the
  pad items, so existing code and digests keep working. `across` is `None`,
  a `PadRef`/`CellPadRef`, a via `CopperIntent`, or an `Along`. `lane` is
  `None` or a `Net` (used by Task 3).
- `ctx.ops_at[intent.index] -> list[CopperOp]`, filled in `_plan_copper`
  for every intent as it is planned.
- `_past_copper(board, ctx, p) -> list[(net, polygon, box)] | str`: the
  items' copper, or a reason string when an item is not planned yet or
  found no spot.

- [ ] **Step 1: Write the failing tests.** In `tests/test_past_copper.py`,
  on synthetic boards (see `tests/test_track_lane_waypoints.py` for the
  `_one_pad_part` helper pattern):
  - a track waypoint `Past([via_intent], Edge.SOUTH)`: the leg passes at
    the via's box bottom + clearance(track net, via net) + width/2;
  - `Past([track_intent], Edge.EAST)`: off the track's box;
  - a mixed `Past([pad, via])` taking the worst clearance by net pair;
  - `across=PadRef(...)`: the point lies on that pad's centre line;
  - `across=Along.START`: on the box side's start;
  - a `Past` naming a via declared after the track: a finding naming both
    keys and "declared after", no exception;
  - a `Past` naming a via that found no spot: a finding, and the track is
    not drawn.
- [ ] **Step 2: Run them.** Expect failures: `Past` rejects the intent, and
  no `across` exists.
- [ ] **Step 3: Implement.**
  - Store `items` on `Past`, and keep `pads` as a property.
  - `_refs_in` collects the refs of each pad item and of each copper
    intent's `refs`.
  - `_plan_copper` records `ctx.ops_at[c.index] = ops`.
  - `_past_point` reads pad shapes as now, and via/track ops from
    `ctx.ops_at`. For an intent whose index is not in `ops_at`, it returns
    the reason: "declared after" when `intent.index > current index`,
    otherwise "found no spot".
  - `across` picks the across coordinate.
- [ ] **Step 4: Run** `tests/test_past_copper.py`,
  `tests/test_track_lane_waypoints.py`,
  `tests/test_copper_digest_parity.py` and
  `tests/test_enum_digest_parity.py`. Expect PASS.
- [ ] **Step 5: Commit** "Past holds vias and tracks, and across= sets its
  line".

### Task 2: A via at a Past point

**Files:**
- Modify: `src/placemat/layout.py`: `via()` (around line 2826); a `Past`
  in `at=` resolves with the via's radius in place of half a track's width.
- Test: `tests/test_past_copper.py`

- [ ] **Step 1: Failing tests:**
  - `board.via(net, at=Past(tips, Edge.SOUTH, across=PadRef(...)))` lands
    at tips' bottom + clearance + via size/2, on the pad's axis;
  - a track then ends on it, and `Past([that via], Edge.SOUTH)` takes a
    second track's U-turn past it;
  - a migration test: a connector's contact row, the hand-computed
    `TIP + clearance + via/2` against the intent form, within 0.01 mm.
- [ ] **Step 2: Run.** FAIL (a `Past` is not a via `at=`).
- [ ] **Step 3: Implement.** In `via()`'s plan, `at` may be a `Past`: call
  `_past_point` with `width = size`. Register `ctx.via_at[intent.index]`
  as for any via. If `_past_point` gives a reason, add a note and plan
  nothing.
- [ ] **Step 4: Run** the task's test file plus
  `tests/test_vias_along_and_stitch.py`. Expect PASS.
- [ ] **Step 5: Commit** "A via may stand at a Past point".

### Task 3: Beside aligns a pad a lane past pads

**Files:**
- Modify: `src/placemat/layout.py`: `_beside_spec` (around line 1679) and
  `_beside_placement` (around line 1752).
- Test: `tests/test_beside_lane.py` (new)

**Ruling on the spec:** a `Beside` is decided in the placement pass, before
copper is planned. Its `Past` therefore takes pads only. A via or track
item is refused at declaration: "a placement is decided before copper is
planned; Past in Beside's align takes pads". This is recorded for the
owner.

- [ ] **Step 1: Failing tests:**
  - `Beside(item, Edge.SOUTH, align=(own_pad, Past([PadRef(c, 1)],
    Edge.WEST, lane=Net("L"))))`: own_pad's east edge lies at c's pad west
    edge minus (clearance(c net, L) + track_width(L) + clearance(L, own
    net)), and the y comes from Beside;
  - the same without `lane=`: at clearance(own net, c net);
  - the refusal for a via item;
  - a migration test: a part whose pad is a lane past another part's pad,
    hand-computed against the intent form, within 0.01 mm.
- [ ] **Step 2: Run.** FAIL.
- [ ] **Step 3: Implement.**
  - `_beside_spec` accepts `(own_key, Past)` and normalises it to
    `("past", own_key, past)`. It records the Past's pad owners in the
    intent's needs, so a searched owner is refused as usual.
  - `_beside_placement` finds own_pad's half-extent across the side (from
    `pad_anchored_placement`, as the pad form does), then sets the across
    coordinate so the pad's facing edge stands the computed distance past
    the pads' box on `edge`.
- [ ] **Step 4: Run** `tests/test_beside_lane.py`, `tests/test_beside.py`
  and `tests/test_beside_migration.py`. Expect PASS.
- [ ] **Step 5: Commit** "Beside aligns a pad a lane past other pads".

### Task 4: row(of=) centred on a pad, at a pitch

**Files:**
- Modify: `src/placemat/layout.py`:
  - `row()` (around line 2028): accept `centre=` a `PadRef` with `of=`, and
    `pitch=`;
  - the Row anchor for `of=`;
  - where `_row_of_placement`'s `along` is computed (around line 4901).
- Test: `tests/test_row_of_pitch.py` (new)

- [ ] **Step 1: Failing tests:**
  - two parts north of a part, `centre=PadRef(u1, 8)`, `pitch=2.7`: their
    body centres are 2.7 apart and their midpoint lies on pad 8's x;
  - `pitch=` below the envelope gap is refused, naming both items and the
    pitch needed;
  - `pitch=` with `gap=` is refused; `centre=` with `align=` is refused;
  - `centre=` a third part's pad works;
  - a migration test: a pair at a mechanical pitch centred on a pin,
    hand-computed against the intent form, within 0.01 mm.
- [ ] **Step 2: Run.** FAIL.
- [ ] **Step 3: Implement.**
  - `row()` drops `centre` from the `of=` refusal list.
  - With `pitch=`, the row's spacing is centre to centre: each item's
    along-position is the previous one's plus `pitch`. Check it against
    the envelope claims.
  - The Row anchor `("of", (of, align))` becomes
    `("of", (of, align, centre))`, and the along computation centres the
    row's middle on `_locate(centre)`.
  - Add `centre`'s pad owner to `row.needs`.
- [ ] **Step 4: Run** `tests/test_row_of_pitch.py`, `tests/test_row_of.py`,
  `tests/test_row_of_migration.py`, `tests/test_rows.py`,
  `tests/test_lock.py` and `tests/test_reuse_keys.py`. Expect PASS.
- [ ] **Step 5: Commit** "A row along a part centred on a pad, at a pitch".

### Task 5: plane(over=)

**Files:**
- Modify: `src/placemat/layout.py`: `plane()` (around line 3117). Reuse
  `_item_envelope_shape`'s box logic, read at the item's placed position
  (the placed drawn-envelope box).
- Test: `tests/test_plane_over.py` (new)

- [ ] **Step 1: Failing tests:**
  - a plane `over=[Part(a), Part(b)]`, with b placed by `Beside` outside
    a's box: the zone outline's box is the union of both envelopes plus
    `margin`, clipped to the frame;
  - `over=` with `outline=` is refused;
  - `over=` a cell covers its members;
  - a footprint's copper graphics are inside the outline.
- [ ] **Step 2: Run.** FAIL.
- [ ] **Step 3: Implement.**
  - `plane(..., over=None, margin=0.0)`.
  - In plan: the union box of each item's placed drawn envelope (the same
    kinds `_item_envelope_shape` reads, at the item's placement), inflated
    by margin and intersected with the frame box. The result goes to
    `box_polygon`.
  - The refs are the items (`_refs_in(over)`), so the plane waits for them.
- [ ] **Step 4: Run** `tests/test_plane_over.py` and any existing plane
  tests (`grep -l "plane(" tests/*.py`). Expect PASS.
- [ ] **Step 5: Commit** "A plane over named parts".

### Finish

- The implementer reports its commits and any rulings.
- The coordinator merges both branches, then runs the full suite and the
  bench (placement changes: Tasks 3 and 4), with the tally in the merge
  commit message.
