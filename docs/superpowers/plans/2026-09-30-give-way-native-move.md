# Give way, native: a via's whole move judged in one call - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (inline, TDD). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Judge a via's whole move (the disc-in-pad test, the still-meets test, the ring and hole against the item's own copper, the redrawn tail) and a share's tail in one native call each, choosing the same offsets and verdicts as the Python loop.

**Architecture:** Two new methods on `NativeObstacles` (`first_move`, `tail_clear`) implemented in a new `native/src/giveway.rs`, reusing `shapes::conflict`, the grid, `exact::round9` and `exact::hypot`. `giveway._give` keeps the decision flow (share, move, shorten, drop, Action, cost, report) and calls the native methods where a native index is registered on the judge's obstacles; the per-scan cache of board-clear offsets (`_native_move_offsets`) stays and feeds `first_move`. The Python loop remains as the fallback (no native module, `_NATIVE_MOVE_SEARCH` off, or a board with net-tie footprints, which the native conflict rules do not model).

**Tech Stack:** Python 3.12, Rust (pyo3 0.29, maturin), pytest, cargo test.

**Spec:** docs/superpowers/specs/2026-09-30-give-way-native-move-design.md

## Global Constraints

- Project-agnostic: never name a project, board, module or part in source, docstrings, skill text, migration notes, plan or commit messages. The fixture path under fixtures/fairing/ is the only allowed mention; elsewhere it is "the whole-board fixture".
- Tunables are settings with defaults, never literals. No new settings; `place.via_clear_cache` bounds the offset cache as before.
- Plain ASCII only: no em/en dashes, no unicode arrows, straight quotes.
- `_disc_inside` and `still` are ported with the same tolerances (`r - 1e-5` for the disc, `d - r < clr - 1e-9` for still); chosen offsets are identical to the Python loop.
- In pcbnew code use `board.Delete(item)`, never `board.Remove(item)` (nothing here touches pcbnew).
- Targeted tests only, never the full suite; do not run the router.
- Commits: author "Ben Agricola <ben+git@agrico.la>", no trailers, no references to tooling or sessions.

## Review Focus

- A board with a net-tie footprint: native conflict rules omit KiCad's net-tie exclusion, so `first_move` must not be used there (test: the Python loop runs, result unchanged).
- A board with an edge margin: the via's ring is judged against the board edge per offset in Python (`_edge_why`); `first_move` returns the next candidate after an edge refusal (test: a via whose nearest clear offset is past the edge moves to the next).
- A via not inside a pad, with no tail, with no hole: each optional argument of `first_move` is None or absent (tests in task 2).
- The hidden set: a via also giving way to the same candidate must not block the move (covered by the existing native/Python equality test, extended in task 3).
- The cache bound `place.via_clear_cache` = 0: no caching, same answers (test in task 3).

---

### Task 1: Native `tail_clear` and `first_move`

**Files:**
- Create: `native/src/giveway.rs`
- Modify: `native/src/lib.rs` (mod, two `#[pymethods]` entries on `NativeObstacles`)
- Test: `native/src/giveway.rs` (`#[cfg(test)]`), `tests/test_native_give_way_move.py`

**Interfaces:**
- Produces (Rust, `giveway.rs`): `pub fn disc_inside(poly: &[Point], c: Point, r: f64) -> bool`; `pub fn still_meets(poly: &[Point], clr: f64, r: f64, c: Point) -> bool`; `pub fn segment_polygon(a: Point, b: Point, width: f64) -> Vec<Point>`.
- Produces (Python): `NativeObstacles.tail_clear(shapes: list[PyShape], mine: list[PyShape], clearance: float | None, skip: list[int]) -> bool` (True when none of `shapes` conflicts with the board index minus `skip`, nor with `mine`); `NativeObstacles.first_move(via, offsets, clearance, skip, mine, centre, first, pad, tail, start) -> int | None`:
  - `via`: `[ring, hole?]` as native shape tuples at their current place;
  - `offsets`: `[(dx, dy)]`, nearest first (already clear of the board for the ring and hole);
  - `mine`: native shape tuples, the item's own copper and holes plus the shapes earlier actions left;
  - `centre`: the via's centre `(x, y)`;
  - `first`: `None` or `(poly, clr, r)`: the copper first met, the clearance, the via radius;
  - `pad`: `None` or `(poly, r)`: the disc radius already reduced by 1e-5;
  - `tail`: `None` or `(proto_shape, far, width)`, the tail's native shape (its polygon is replaced per offset), the far end, the width;
  - `start`: index in `offsets` to begin from.
  - Returns the index of the first offset passing every test, or None.

- [ ] **Step 1: Rust unit tests** in `giveway.rs`: `disc_inside` (centre outside is false; a disc touching a side at exactly r is true; one tighter is false), `still_meets` (centre inside true; near enough true; far false), `segment_polygon` (34 points for 8 cap steps, symmetric about the centre line for a horizontal segment, zero-length segment uses the +x axis).
- [ ] **Step 2:** `cargo test --manifest-path native/Cargo.toml giveway` - expect compile failure (module missing).
- [ ] **Step 3: Implement** the three helpers, `fn tail_clear` and `fn first_move` on `ShapeGrid` in `giveway.rs` exactly as the Python `_disc_inside`, `still`, `_segment_polygon`, `hit` define them:
  - `to = (round9(cx + dx), round9(cy + dy))` as `round(c + d, 9)`;
  - per offset, in order: `disc_inside(pad, to, r)`, `still_meets(first, to)` skip, the via shapes shifted by `(dx, dy)` against `mine` (box overlap with `cfg.gap_for`, `may_meet`, `conflict`), then the tail: `segment_polygon(far, to, width)`, bbox from its points, against the grid minus `skip` and against `mine`;
  - `segment_polygon` uses `exact::hypot` for the length and `f64::atan2`, `cos`, `sin` in the operation order of `copper._segment_polygon`.
- [ ] **Step 4:** add the two methods to `lib.rs`, delegating to the grid. `cargo test` passes.
- [ ] **Step 5: Python parity tests** (`tests/test_native_give_way_move.py`, skipped without the native module): build a `NativeObstacles` from the give-way test board helpers and random shapes; 1,000 random `first_move` cases against a pure-Python reference written from `_give`'s loop (using `_disc_inside`, `_still_meets`, `_shift`, `_tail_shape`, `_Judge.hit`); and 1,000 `tail_clear` cases against `_Judge.hit`. Run: fails first (attribute missing), passes after the build.
- [ ] **Step 6:** build into the worktree, run the new tests, commit ("Native first_move and tail_clear: a via's move judged whole").

### Task 2: `_give` judges a via's move with `first_move`

**Files:**
- Modify: `src/placemat/giveway.py` (`_give`, new helper `_native_first_move`, `_nettied`)
- Test: `tests/test_vias_give_way.py`

**Interfaces:**
- Consumes: `NativeObstacles.first_move` from task 1; `_native_move_offsets(judge, ring, hole, offsets)` (unchanged).
- Produces: `giveway._NATIVE_FIRST_MOVE` (bool switch, default True) for tests; `_native_first_move(occ, g, judge, own, first, inside_pad, r, limit_offsets) -> tuple[bool, tuple | None]` returning `(used, (dx, dy) | None)`; `used` False means the Python loop must run.

- [ ] **Step 1: Failing test** `test_a_via_move_is_the_same_with_first_move_or_the_loop`: the existing `_later_board` scenario run with `_NATIVE_FIRST_MOVE` True and False, asserting equal actions, placement and note, and that `first_move` was called (monkeypatch-wrapped counter) on the True run. Run: fails (no `_NATIVE_FIRST_MOVE` attribute).
- [ ] **Step 2: Implement** `_native_first_move`: returns `(False, None)` when `_NATIVE_FIRST_MOVE` is off, `judge.others` has no `_native`, the offset cache gave None, or the board has a net-tie footprint (`any(fp.net_tie_pads ...)`, cached on `occ`). Otherwise converts the via shapes, `own` plus `judge.extra` (those overlapping the move span), the tail prototype, `first` as `(poly, clr, r)` from `_still_meets`'s own quantities, and the pad as `(poly, r - 1e-5)`; loops `start` past offsets whose ring the board edge refuses (`occ.edge_margin is not None and occ._edge_why(shifted ring box)`). In `_give`, when `used`, build the move Action for the returned offset exactly as the loop does after its `break`; when `used` and None, fall to "no spot".
- [ ] **Step 3:** run `tests/test_vias_give_way.py` and `tests/test_vias_give_way_kicad.py`; all pass, including the new test.
- [ ] **Step 4: Edge test** `test_a_via_move_past_the_board_edge_takes_the_next_spot` (a via whose nearest clear spot is within the edge margin), run with `first_move` on and off, equal.
- [ ] **Step 5: Net-tie test** `test_first_move_is_not_used_on_a_board_with_a_net_tie_footprint`: a footprint with `net_tie_pads`; the counter shows zero calls and the result equals the loop's.
- [ ] **Step 6:** commit ("Give way: a via's move is judged by one native call").

### Task 3: Whole-board parity sweep and cache bound

**Files:**
- Test: `tests/test_native_give_way_move.py`

- [ ] **Step 1: Test** `test_random_resolutions_on_the_whole_board_fixture_match`: place the whole-board fixture once (module-scoped fixture), then for 1,000 random (item, location, rotation) near carried vias, `giveway.resolve` with `_NATIVE_FIRST_MOVE` True and False; assert equal actions (kind, via, at, to, tail, cost), cost and `why`; assert `first_move` was called at least once (the sweep exercises the path). Mark it `slow` if the repository has that marker; otherwise keep the case count as a named constant.
- [ ] **Step 2:** run it; expected to pass if task 2 is faithful. A mismatch is a bug in tasks 1-2: fix there.
- [ ] **Step 3: Test** `place.via_clear_cache = 0` gives the same answers as the default on the scenario board.
- [ ] **Step 4:** commit ("Parity sweep of give way's native move on the whole-board fixture").

### Task 4: Share tails judged natively

**Files:**
- Modify: `src/placemat/giveway.py` (`_give`, share branch; new helper `_tail_hit`)
- Test: `tests/test_vias_give_way.py`, `tests/test_native_give_way_move.py`

**Interfaces:**
- Produces: `_tail_hit(occ, judge, shape, own) -> bool`, equal to `judge.hit([shape], judge.near(shape.box, occ.gap_for(shape)), own, say=False) is not None`, natively when available.

- [ ] **Step 1: Failing test** `test_a_share_tail_is_judged_the_same_native_or_not`: the crossing-track share scenario, with the native switch on and off, equal note; and `tail_clear` is called once per target on the native run.
- [ ] **Step 2: Implement** `_tail_hit`; use it for both the on-the-spot tail (`left`) and the drawn tail. `skip` is the hidden vias' indices (as `_native_move_offsets` builds it); `mine` is `own` plus `judge.extra`.
- [ ] **Step 3:** run the give-way files; pass.
- [ ] **Step 4:** commit ("Give way: a share's tail is judged natively").

### Task 5: Nearest-first scans stop at the first resolved spot

**Files:**
- Test: `tests/test_vias_give_way.py`

- [ ] **Step 1: Test** `test_a_nearest_first_scan_stops_at_the_first_spot_that_resolves`: wrap `giveway.resolve` with a recorder; an unscored search (nearest first) in the cell scenario; assert the last recorded call is the only one with `why is None` and no call follows it in that scan.
- [ ] **Step 2:** run; expected to pass (behaviour already true, per the spec). If it fails, the failing reason is the finding.
- [ ] **Step 3:** commit with task 6.

### Task 6: Refusal cache (spec section 3, first cut)

**Files:** none unless exact.

- [ ] **Step 1:** Analyse what a refusal depends on: the via, the static board, `judge.hidden`, `judge.extra`, the item's own shapes near the via in absolute coordinates, `drops_now`, the owner's drop counts, `first`. The candidate's shapes at another candidate differ by a translation, and a translated float polygon is not bit-equal to the original, so a relative key is not exact; an absolute key hits only a repeated identical placement. No exact key with a useful hit rate exists, so the cache is left out. Record this in the commit message and the report.
- [ ] **Step 2:** api.md: `place.via_clear_cache` row is unchanged in meaning (it bounds the clear-offset cache only).

### Task 7: Docs, whole-board and bench

**Files:**
- Modify: `skills/placemat/references/migration.md` (`## Unreleased`), `docs/` nothing else.

- [ ] **Step 1:** migration note: a speed change, same results.
- [ ] **Step 2:** whole-board before/after dump (placements, steps, findings, give-way actions, check verdicts) with `PYTHONHASHSEED=0`: identical. `fixtures/bench.py --board` and `--checks` timings before and after.
- [ ] **Step 3:** targeted tests: `tests/test_vias_give_way.py tests/test_vias_give_way_kicad.py tests/test_native_sweep.py tests/test_native_legal.py tests/test_native_conflict.py tests/test_copper_digest_parity.py tests/test_enum_digest_parity.py tests/test_native_give_way_move.py`.
- [ ] **Step 4:** `fixtures/bench.py --jobs 2`: "same 32" on every config.
- [ ] **Step 5:** final commit with the bench tally and the `--board` timings in the message; run the attribution grep on every commit.

## As executed

Where the plan was silent or wrong, and what was done:
- Task 1's Python tests check the native call's marshalling only; the 1,000-case parity is at the level `_give` decides (tests/test_give_way_native_parity.py), which covers `first_move` and `tail_clear` together, plus a separate 1,000-case test of share tails.
- Net ties: the plan's whole-board fallback disabled the native calls on the whole-board fixture, which has net ties. The fallback is instead local: Python judges where a net tie's copper lies within a conflict's reach of the move (`_meets_net_tie`).
- `first_move` takes a `start` index; the board edge is judged in Python per spot and the native call is asked again from the next offset.
- `tail_clear` takes the tail's native shape list, not a track.
- `_still_meets` is a speed-up only: dropping it changes no result, so parity tests cannot see it; it is covered by Rust unit tests.
- The refusal cache (task 6) is left out: no exact key with a useful hit rate exists.
- The per-scan set-aside-via index and a hoisted group-shape list in `resolve` were added after profiling.
