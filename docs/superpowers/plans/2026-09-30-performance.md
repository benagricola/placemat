# Performance: zone width, give way, the sweep's Python - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the profiled cost of zone-width checks, give-way and the placement sweep's Python overhead, changing no result but the zone-width raster (at most one `check.zone_step`), with a new whole-board bench case to measure it all.

**Architecture:** Five ordered changes, each its own commit: (1) rasterise+distance-transform zone width in Python instead of an edge scan; (2) add a whole-board bench fixture and `bench.py --board`/`--checks`; (3) trim three Python hot spots in the native sweep path (`_decode`, `_grid`, the triples/seen loop); (4) give a placed via's move search a native offset search and drop redundant Python filtering; (5) port `_Fill` to Rust as `NativeFill`, Python keeping only the neck/sentence choice.

**Tech Stack:** Python 3.12, Rust (pyo3 0.29, abi3-py312), pytest, cargo test.

**Spec:** docs/superpowers/specs/2026-09-30-performance-zone-width-give-way-sweep-design.md

## Global Constraints

- Nothing changes a result except the zone-width raster: widths may differ by at most one `check.zone_step`, and every changed verdict on the whole-board checks case is listed in the commit message and the final report.
- Identical: plan digests, bench "same 32" tally on every config, check verdicts (outside the listed zone-width diffs), refusal sentences, give-way actions.
- `tests/test_vias_give_way.py`, `tests/test_vias_give_way_kicad.py`, `tests/test_native_sweep.py`, `tests/test_native_legal.py`, `tests/test_current_path_*.py` pass unchanged (no test edits unless a step explicitly adds a new test).
- No project/board/module/part names anywhere in source, docstrings, skill, references, migrations, plans or commit messages; the fixture is "the whole-board fixture" / "a six-layer test board", path `fixtures/fairing/core/` only.
- Tunables are settings in `src/placemat/settings.py` with defaults, documented in `skills/placemat/references/api.md`'s settings table - never bare literals. (Exception, matching existing precedent: private `functools.lru_cache(maxsize=N)` bounds on a pure implementation-detail cache, as `giveway._offsets` and `geometry._prepared_many` already do - not a placement/check behaviour knob.)
- Native module builds into this worktree only (`native/.native-dist`, `../.native-build`), never into the shared `.venv`. `.native-build/` and `.native-dist/` go in `.git/info/exclude` (git-dir: `/home/ben/work/placemat/.git/worktrees/agent-ac6b28de9d1ab4d11/info/exclude`), not `.gitignore`. Already done.
- Keep `giveway.py` `_give`'s share/move/drop decision logic itself untouched where possible; add the native offset search as a helper it calls, so a concurrent "shorten way" change merges cleanly.
- Commits: `git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit ...`; message has zero Claude/Anthropic/session/co-authored references (verify with the grep after every commit); plain ASCII only.
- Tests: targeted files only, run as `PYTHONPATH=<worktree>/.native-build:<worktree>/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/<files>` (copy `src/placemat/_version.py` from the main checkout first). Never the full suite, never the router.
- Bench: `fixtures/bench.py --jobs 2` (default 32-module tally) after each step touching placement, plus the whole-board timings once per step; never two heavy jobs at once. Tally and timings go in the step's commit message.
- Sandbox note (this worktree): shell substitution (`$PWD`, `$(...)`, globs) inside a command the isolation check treats as "too complex to verify" gets refused - use literal absolute paths in every command, one command per invocation rather than long `&&` chains where practical.

## Review Focus

- A copper item with zero-area or degenerate outlines (a single point, a line): `_raster`/the distance transform must not divide by zero or infinite-loop - covered by keeping the exact existing `_raster`/`_edt_line` helpers unchanged and reusing them (task 1).
- A fill whose entry/exit copper sits entirely outside the fill's own raster box (a thermal spoke's pad far from the pour): the per-copper-item cached transform must still cover it - covered by task 1's per-item box sized from the copper's own polygons, mirroring `_Fill.__init__`'s own margin.
- A via with no legal move offset at all (every offset conflicts): the native offset search must return "no clear offset" the same way the Python loop falls through to "no spot within ... mm is clear" - covered by task 4's parity test against the existing give-way tests.
- NativeFill on a fill with a slit to a hole (zero-width seam, exercised today by `test_a_fill_slit_to_a_hole_is_not_read_as_zero_and_goes_round_the_hole`): the raster's even-odd crossing rule must still treat the slit as no gap - covered by task 5's parity test reusing that exact fixture.
- The bench's whole-board case must not silently get skipped when the fixture boards are absent (e.g. a stale checkout) - covered by task 2's `--board`/`--checks` flags erroring clearly rather than reporting an empty pass.

---

## Task 1: Zone width in Python - raster and distance transform, not an edge scan

**Files:**
- Modify: `src/placemat/checks.py` (`_Fill.touching`, `_Fill.__init__` or a new cached helper on `_Fill`)
- Test: `tests/test_current_path_zone_width.py` (existing tests must keep passing unchanged); no new test file needed - `touching`'s contract is already fully pinned by the existing current-path tests plus the whole-board check.

**Interfaces:**
- Consumes: `_Fill.__init__(poly, step)`, `_Fill.radius(tau)`, `_Fill.centre(c)`, `_raster(polys, x0, y0, nx, ny, s)`, `_edt_line(f)` - all unchanged, reused verbatim.
- Produces: `_Fill.touching(polys, tau)` keeps its exact signature and return type (`set` of cell indices), same semantics to within the documented half-step tolerance.

- [ ] **Step 1: Read `_Fill.touching`'s current behaviour once more against the whole-board fixture path, to fix the raster's tolerance before writing code**

No code. `touching`'s docstring: "at least `tau` from its edge whose disc of that radius (`radius(tau)`) reaches `polys`, within half a step". The replacement must answer within the SAME half-step tolerance the current edge-exact test allows, not tighter or looser - a cell touches when its (rasterised, distance-transformed) distance to `polys`' own raster is at most `radius(tau) + s/2`.

- [ ] **Step 2: Add a per-`_Fill`, per-copper-item cached raster distance transform**

In `checks.py`, add a helper that rasterises a list of polygons (the same shape `touching` receives) onto the `_Fill`'s own grid (`self.x0, self.y0, self.nx, self.ny, self.s`) and takes the two-pass `_edt_line` transform of it - literally `_Fill.__init__`'s own two loops, factored so `_Fill.__init__` and this helper share the code:

```python
def _distance_transform(inside: bytearray, nx: int, ny: int) -> list:
    """The squared-distance-in-cells transform of a 0/1 raster (1 = inside):
    a two-pass exact Euclidean transform (Felzenszwalb and Huttenlocher),
    column-wise then row-wise - the same transform `_Fill.__init__` takes of
    its own polygon, reused here for an arbitrary raster (the copper
    `touching` is asked about)."""
    cols = [0.0] * (nx * ny)
    for q in range(nx):
        d = _edt_line([math.inf if inside[r * nx + q] else 0.0 for r in range(ny)])
        for r in range(ny):
            cols[r * nx + q] = d[r]
    sq = [0.0] * (nx * ny)
    for r in range(ny):
        sq[r * nx:(r + 1) * nx] = _edt_line(cols[r * nx:(r + 1) * nx])
    return sq
```

Change `_Fill.__init__`'s own two loops to call this instead of repeating them (behaviour-preserving refactor, no test depends on the internal duplication).

- [ ] **Step 3: Cache one transform per copper-item identity on the `_Fill`**

Add to `_Fill.__init__`: `self._copper_sq: dict = {}`. Add a method:

```python
def _copper_distance(self, polys) -> list:
    """The squared-distance-in-cells transform of `polys` rasterised on
    this fill's own grid, cached by `polys`'s identity: `width()`'s binary
    search over levels calls `touching` with the SAME `entry`/`exit_` tuple
    object at every level, so one raster and one transform per copper item
    serves the whole search, replacing a per-cell edge scan at every
    level."""
    key = id(polys)
    hit = self._copper_sq.get(key)
    if hit is None or hit[0] is not polys:
        inside = _raster(polys, self.x0, self.y0, self.nx, self.ny, self.s)
        hit = (polys, _distance_transform(inside, self.nx, self.ny))
        self._copper_sq[key] = hit
    return hit[1]
```

- [ ] **Step 4: Rewrite `touching` to test cells against the cached copper transform instead of walking edges**

Replace the body from `diag = math.hypot(...)` onward (the edge-walk) with a lookup against `self._copper_distance(polys)`, keeping every line before it (the cell-gathering via `self.deep`/bisect or full box scan) unchanged:

```python
def touching(self, polys, tau: float) -> set:
    """... (docstring unchanged, plus:) The test is against `polys`
    rasterised and distance-transformed on the fill's own grid (cached per
    copper item, `_copper_distance`), not a per-cell scan of every edge:
    exact to half a cell rather than to the edge, the tolerance `radius`
    already documents. A width may differ from the edge-exact answer by at
    most one `check.zone_step`; see docs/superpowers/specs/
    2026-09-30-performance-zone-width-give-way-sweep-design.md section 1."""
    s, nx, ny, sq, inside = self.s, self.nx, self.ny, self.sq, self.inside
    box = Box.union([Box.of_points(p) for p in polys])
    far = self.radius(tau) + s / 2.0
    q0 = max(0, int((box.left - far - self.x0) / s))
    r0 = max(0, int((box.top - far - self.y0) / s))
    q1 = min(nx, int(math.ceil((box.right + far - self.x0) / s)) + 1)
    r1 = min(ny, int(math.ceil((box.bottom + far - self.y0) / s)) + 1)
    deep = bisect.bisect_right(self.depths, -tau)
    if deep < max(0, q1 - q0) * max(0, r1 - r0):
        cells = [c for c in self.deep[:deep] if q0 <= c % nx < q1 and r0 <= c // nx < r1]
    else:
        cells = [r * nx + q for r in range(r0, r1) for q in range(q0, q1)
                 if inside[r * nx + q] and sq[r * nx + q] >= tau]
    copper_sq = self._copper_distance(polys)
    limit = (far / s) ** 2
    return {c for c in cells if copper_sq[c] <= limit}
```

Note: `copper_sq[c]` is the squared cell-distance from cell `c` to the nearest cell that IS copper (1 in the `polys` raster); a cell whose own centre lies inside `polys` has `copper_sq[c] == 0`, matching the old code's `point_in_polygon` short-circuit. `limit = (far/s)**2` converts the world-mm tolerance `far` into the same squared-cell units `_edt_line` produces (its transform is over integer cell offsets, unit step).

- [ ] **Step 5: Run the current-path and cell-zone tests**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_current_path_neck.py tests/test_current_path_pairs.py tests/test_current_path_zone_width.py tests/test_cell_zones.py tests/test_merged_zones_text.py
```
Expected: all pass, unchanged, byte for byte (no test file edits in this task).

- [ ] **Step 6: Run `run_checks` on the whole-board fixture's written board (once it exists - see Task 2) is deferred to Task 2's commit; for THIS commit, run the bench's default 32-module tally to confirm no placement-affecting change (zone width does not feed placement) and time `run_checks` by hand against a temporary copy of the written board named only descriptively**

Since the whole-board fixture is not committed until Task 2, verify this task in isolation two ways: (a) the pytest run above; (b) a scratch timing using the source written board directly from its `/tmp` path (read-only, not committed), comparing `checks.run_checks` wall time and verdicts before/after this change, to catch a gross regression or crash early. Record the before/after numbers and any verdict differences (expected: none yet, since NativeFill and the raster tolerance both matter at the whole-board scale - the real comparison is Task 2's commit, once the fixture is in the repo and both the "before this task" and "after" trees can run `bench.py --checks` against it).

- [ ] **Step 7: Commit**

```
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "..."
```
Message states: the change (raster+transform replaces the edge scan in `_Fill.touching`), the pytest result, and that whole-board timing/verdict comparison is deferred to the next commit (which adds the fixture). Then:
```
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
must print nothing.

---

## Task 2: The whole-board bench case

**Files:**
- Create: `fixtures/fairing/core/layout/layout.kicad_pcb`, `fixtures/fairing/core/layout/layout.kicad_pro` (the written, placed board with zone fills - copied from the source path read-only)
- Create: `fixtures/fairing/core/generated/layout.kicad_pcb`, `fixtures/fairing/core/generated/layout.kicad_pro` (the generated, unplaced board)
- Modify: `fixtures/bench.py` (add `--board`, `--checks`)
- Test: none new (bench is not pytest-driven); its own run IS the verification.

**Interfaces:**
- Consumes: `placemat.kicad.read.read_board`, `placemat.layout.Board`, `placemat.checks.run_checks`, `placemat.values.Part` - all existing.
- Produces: `bench.py --board` and `bench.py --checks`, timed and printed separately from the default tally, not folded into it.

- [ ] **Step 1: Check the source boards' size before copying**

```
ls -la /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/fairprof/electronics/boards/core/.placemat/generated/Core/layout.kicad_pcb /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/fairprof/electronics/boards/core/layout/layout.kicad_pcb
```
If either exceeds ~5 MB, stop and report it in the final report instead of committing (per the task's instructions) - do not proceed with this task's remaining steps for that file; note the gap.

- [ ] **Step 2: Copy the boards into the fixture directory**

```
mkdir -p /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/fixtures/fairing/core/generated
mkdir -p /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/fixtures/fairing/core/layout
cp /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/fairprof/electronics/boards/core/.placemat/generated/Core/layout.kicad_pcb /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/fixtures/fairing/core/generated/layout.kicad_pcb
cp /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/fairprof/electronics/boards/core/.placemat/generated/Core/layout.kicad_pro /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/fixtures/fairing/core/generated/layout.kicad_pro
cp /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/fairprof/electronics/boards/core/layout/layout.kicad_pcb /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/fixtures/fairing/core/layout/layout.kicad_pcb
cp /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/fairprof/electronics/boards/core/layout/layout.kicad_pro /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/fixtures/fairing/core/layout/layout.kicad_pro
```
Before adding to git, `grep` both `.kicad_pcb` files for the source project's own name (whatever it is - checked against the real filenames encountered) and for any comment/script path leaking the source repo, to satisfy "commit no layout script or prose from the source project"; a `.kicad_pcb` is KiCad's own binary-ish s-expression format with no placemat script embedded, but footprint library/sheet paths can leak a source repo path - inspect for `(sheetfile ...)`, `(sheetname ...)`, `(property "Sheetfile" ...)` and any absolute path under the source checkout, and strip/generalise any found (matching the project-agnostic rule) before staging.

- [ ] **Step 3: Add `--board` and `--checks` to `fixtures/bench.py`**

Add two functions and wire them into `main`:

```python
BOARD_FIXTURE = ROOT / "fairing" / "core"


def bench_board() -> tuple[float, dict]:
    """The whole-board fixture's generated board, every cell and loose part
    released to a bare place() (as ModuleBoard does for a module) and
    resolved. Returns (seconds, {placed, findings})."""
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.values import Part
    g = read_board(BOARD_FIXTURE / "generated" / "layout.kicad_pcb")
    b = Board(g, keep_going=True)
    for fp in sorted(g.footprints, key=lambda f: f.inst):
        b.place(Part(fp.inst))
    t0 = time.perf_counter()
    plan = b.resolve()
    dt = time.perf_counter() - t0
    placed = sum(1 for s in plan.steps if s.placement is not None and s.kind == "part")
    return dt, {"placed": placed, "findings": len(plan.findings)}


def bench_checks() -> tuple[float, dict]:
    """The whole-board fixture's written, placed board (with its zone
    fills), `run_checks` timed alone."""
    from placemat.checks import kwargs_from, run_checks
    from placemat.kicad.read import read_board
    from placemat.settings import Settings
    g = read_board(BOARD_FIXTURE / "layout" / "layout.kicad_pcb")
    t0 = time.perf_counter()
    verdicts = run_checks(g, **kwargs_from(Settings()))
    dt = time.perf_counter() - t0
    return dt, {"verdicts": len(verdicts), "failing": sum(1 for v in verdicts if v.ok is False)}
```

In `main`, after argument parsing and before the module tally, handle the new flags and return early (so `--board`/`--checks` never mix into the default 32-module tally or its `--update`d baseline):
```python
    ap.add_argument("--board", action="store_true", help="the whole-board fixture's placement, timed alone")
    ap.add_argument("--checks", action="store_true", help="the whole-board fixture's checks, timed alone")
    ...
    a = ap.parse_args(argv)
    if a.board or a.checks:
        if a.board:
            dt, row = bench_board()
            print("board: %.1f s, placed %d, findings %d" % (dt, row["placed"], row["findings"]))
        if a.checks:
            dt, row = bench_checks()
            print("checks: %.1f s, %d verdicts, %d failing" % (dt, row["verdicts"], row["failing"]))
        return 0
```
Place this block right after `a = ap.parse_args(argv)`, before the existing `a.update` validation, since `--board`/`--checks` are their own mode (like `--explore`) and share nothing with the tally path.

- [ ] **Step 4: Run both new bench modes once to get baseline numbers**

```
cd /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --board
```
```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --checks
```
These are the "after Task 1, before Task 3" numbers - the `checks` one is the first real signal of Task 1's raster change on the actual whole-board case (compare informally against an unprofiled run of the pre-Task-1 tree if time allows, e.g. by stashing Task 1's diff in a WIP commit and re-running - not required to block this commit, but do it if cheap, and report both numbers either way).

- [ ] **Step 5: Run the default bench tally to confirm nothing else moved**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2
```
Expected: `same 32` on every config (Task 1 touches only `checks.py`, never placement).

- [ ] **Step 6: Commit the fixture and the bench flags together**

```
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "..."
```
Message states: the fixture added (generic wording only - "the whole-board fixture", "a six-layer test board"), the `--board`/`--checks` flags, the bench tally ("same 32" x3), and the `--board`/`--checks` timings measured. If Task 1's before/after `--checks` comparison was obtained, state the checks-verdict diff (if any: at most one `check.zone_step` per changed width, each changed verdict listed) here - since this is the first commit where the fixture exists to measure against. If no before-comparison was obtained, say so plainly rather than asserting "unchanged" without having checked.
Then verify:
```
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 3: The sweep's Python - `_decode`, `_grid`, the native_sweep triples loop

**Files:**
- Modify: `src/placemat/occupancy.py` (`NativeSweeper._decode`)
- Modify: `src/placemat/placer.py` (`_grid`, the `native_sweep` closure inside `scan`)
- Modify: `native/src/lib.rs` (a small `NativeSweepSeen` pyclass)
- Test: no behaviour changes visible to any existing test's assertions (these are pure hot-path refactors); `tests/test_native_sweep.py` and `tests/test_native_legal.py` are the regression gate.

**Interfaces:**
- Consumes (Rust): existing `NativeObstacles`/`ShapeGrid` machinery, untouched.
- Produces (Rust): `placemat_native.NativeSweepSeen`, a pyclass with `__new__()` and `.expand(points: list[tuple[float, float]], n_rots: int) -> list[tuple[float, float, int]]`.
- Produces (Python): `NativeSweeper._decode` unchanged signature/return; `placer._grid` unchanged signature/return; `native_sweep`'s own triples-building loop replaced, `seen` (the Python set in `scan()`) no longer touched by the native path (still used, unchanged, by the pure-Python `sweep` path when `native is None`).

- [ ] **Step 1: `_decode` - look up the cache before building the moved shape**

In `src/placemat/occupancy.py`, `NativeSweeper._decode`, replace the `kind not in (0, 1)` branch (currently builds `moved` unconditionally, then checks the cache) with a version that looks the cache up from `s` (the origin, unmoved shape - same `.kind`/`.owner` as `moved`, since a shift changes only coordinates) and defers building `moved` into the `reason` closure:

```python
    turn_of, si = a >> 32, a & 0xffffffff
    s, o = self.origin[turn_of][si], self.shapes[b]
    key = ("conflict", a, b)
    hit = self._decoded.get(key)
    if hit is None:
        hit = (occ._native_bucket(s, o), (_blocker_kind(o.kind), occ.blame_owner(o),
                                          "/".join(sorted(f.value for f in o.faces))))
        self._decoded[key] = hit
    clearance = self.clearance

    def reason(s=s, o=o, x=x, y=y, clearance=clearance):
        moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((px + x, py + y) for px, py in s.poly),
                      s.box.moved(x, y), s.label)
        why = occ._conflict(moved, o, clearance)
        if why is None:
            raise AssertionError("native found a conflict between a %s and a %s that _conflict disagrees with; "
                                 "this is a native/Python mismatch, not a placement question" % (moved.kind, o.kind))
        return why
    return hit[0], hit[1], reason
```
`occ._native_bucket(s, o)` is correct unshifted: `_native_bucket` reads only `.kind`/`.owner`, never `.poly`/`.box` (verified by reading its body), so it gives the identical answer for `s` (origin) as for `moved` (shifted) - the cache key and its content are unchanged, only WHEN the polygon-shift work happens moves from "always" to "only inside `reason()`, which is only invoked when a sentence is actually wanted" (mirrors `tally()`'s existing `if key not in reasons: reasons[key] = get_reason()`).

- [ ] **Step 2: Run the native-legal test to confirm `_decode`'s change is invisible**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_native_legal.py tests/test_native_sweep.py
```
Expected: pass, unchanged (needs pcbnew/native; if either `needs_kicad`/`needs_native` skips, note the skip and rely on `bench.py`'s own run as the practical check).

- [ ] **Step 3: `_grid` - cache the (radius, step) offsets, translate to each centre**

In `src/placemat/placer.py`, add (near `_grid`, following `giveway._offsets`'s own pattern):

```python
@functools.lru_cache(maxsize=16)
def _grid_offsets(radius: float, step: float) -> tuple:
    """(d, dx, dy) within `radius` on a `step` grid, nearest first, cached
    by (radius, step): `_grid` is called with the same handful of
    (radius, step) pairs many times over a run (one scan's several passes,
    many scans of the same kind of item), so the O(n^2) walk-and-sort
    happens once per pair, not once per call."""
    n = int(math.floor(radius / step + 1e-9))
    pts = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            d = math.hypot(i * step, j * step)
            if d <= radius + 1e-9:
                pts.append((d, i * step, j * step))
    pts.sort()
    return tuple(pts)


def _grid(center: Location, radius: float, step: float):
    return [(d, round(center.x + dx, 6), round(center.y + dy, 6)) for d, dx, dy in _grid_offsets(radius, step)]
```
Add `import functools` to placer.py's imports if not already present (it is not, per the file read earlier). This keeps `_grid`'s signature, return shape and float values bit-identical: `dx = i * step` computed exactly as before, `round(center.x + dx, 6)` in the same order of operations as the original `round(x, 6)` where `x = center.x + i * step`.

- [ ] **Step 4: Run a placement-touching test to confirm `_grid`'s change is invisible**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vias_give_way.py tests/test_native_sweep.py
```
Expected: pass, unchanged.

- [ ] **Step 5: Add `NativeSweepSeen` to the native module**

In `native/src/lib.rs`, add (near `NativeObstacles`):

```rust
/// The (x, y, turn) triples `placer.scan`'s own `seen` Python set used to
/// dedupe across a scan's several passes (coarse, half-coarse, fine round
/// each refined candidate) - kept here instead, one instance per scan
/// (`Occupancy.native_sweeper` builds one `NativeSweeper` per `scan()`
/// call, which owns one of these), so the loop that builds triples from
/// `points x rots` runs in Rust once per pass instead of once per
/// (point, rotation) pair in Python. Coordinates are compared by exact
/// bit pattern (`f64::to_bits`), matching Python's own `(x, y, rot) in
/// seen` set-membership exactly: `placer._grid`'s `round(v, 6)` is
/// deterministic, so the same conceptual point always produces the same
/// bits, from whichever pass reaches it first.
#[pyclass]
#[derive(Default)]
struct NativeSweepSeen {
    seen: std::collections::HashSet<(u64, u64, usize)>,
}

#[pymethods]
impl NativeSweepSeen {
    #[new]
    fn new() -> Self {
        NativeSweepSeen::default()
    }

    /// (x, y, turn) triples for every (x, y) in `points` at every turn in
    /// 0..n_rots not already returned by an earlier call on this instance.
    fn expand(&mut self, points: Vec<(f64, f64)>, n_rots: usize) -> Vec<(f64, f64, usize)> {
        let mut out = Vec::new();
        for (x, y) in points {
            let kx = x.to_bits();
            let ky = y.to_bits();
            for turn in 0..n_rots {
                if self.seen.insert((kx, ky, turn)) {
                    out.push((x, y, turn));
                }
            }
        }
        out
    }
}
```
Register it in `placemat_native`'s module function (`fn placemat_native`, near the other `m.add_class::<...>()` calls).

- [ ] **Step 6: Add a Rust unit test for `NativeSweepSeen::expand`**

In `native/src/lib.rs`, add a `#[cfg(test)] mod tests` block (or extend one if it already exists at file scope) - check first with `grep -n "mod tests" native/src/lib.rs`; if none exists at file scope, add one near the bottom:

```rust
#[cfg(test)]
mod sweep_seen_tests {
    use super::*;

    #[test]
    fn expand_skips_what_was_already_returned() {
        let mut s = NativeSweepSeen::default();
        let first = s.expand(vec![(1.0, 2.0), (3.0, 4.0)], 2);
        assert_eq!(first, vec![(1.0, 2.0, 0), (1.0, 2.0, 1), (3.0, 4.0, 0), (3.0, 4.0, 1)]);
        let second = s.expand(vec![(1.0, 2.0), (5.0, 6.0)], 2);
        // (1.0, 2.0) at both turns already seen; (5.0, 6.0) is new.
        assert_eq!(second, vec![(5.0, 6.0, 0), (5.0, 6.0, 1)]);
    }
}
```

- [ ] **Step 7: Build and test the native module**

```
cd /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/native
cargo test
```
Expected: pass, including the new test.

- [ ] **Step 8: Rebuild the native wheel and reinstall it into `.native-build`**

```
/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/maturin-venv/bin/maturin build --release --manifest-path /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/native/Cargo.toml -o /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-dist
```
Then remove the stale install and reinstall (exact wheel filename - check with `ls` first, since `maturin`'s output name is deterministic given the same Cargo.toml version/target but confirm before using it literally, no globs):
```
ls /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-dist
```
```
/home/ben/work/placemat/.venv/bin/python -m pip install --no-deps --force-reinstall --target /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-dist/<wheel-filename>
```
Verify:
```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -c "import placemat_native; print(hasattr(placemat_native, 'NativeSweepSeen'))"
```
Expected: `True`.

- [ ] **Step 9: `NativeSweeper` gets its own `NativeSweepSeen`, and `native_sweep` uses `.expand`**

In `src/placemat/occupancy.py`, `NativeSweeper.__init__`, add:
```python
        self._seen = native.NativeSweepSeen()
```
(`native = _geometry_module._native` needs to be bound in `__init__` - add `native = _geometry_module._native` near its top, alongside the existing inline imports, since `_geometry_module` is already imported at module scope in occupancy.py - confirm with `grep -n "^from \. import geometry\|^import.*geometry" src/placemat/occupancy.py` before writing this line, matching whatever the existing import alias is.)

Add a method:
```python
    def expand(self, points, n_rots: int) -> list:
        """(x, y, turn) triples for `points` at each of `n_rots` turns not
        already produced by an earlier call on this scan: the seen-set
        `placer.native_sweep` used to keep as a Python set, moved to Rust
        (`NativeSweepSeen`) so the whole points-x-rotations loop and its
        membership test run once per pass in Rust, not once per
        (point, rotation) pair in Python."""
        return self._seen.expand(points, n_rots)
```

In `src/placemat/placer.py`, in the `native_sweep` closure inside `scan`, replace:
```python
        triples = []
        for x, y in points:
            for k, rot in enumerate(rots):
                if (x, y, rot) in seen:
                    continue
                seen.add((x, y, rot))
                triples.append((x, y, k))
```
with:
```python
        triples = native.expand(list(points), len(rots))
```
`points` is a generator in every caller; `list(points)` materialises it once, matching what the old loop did implicitly by iterating it once. `seen` (the outer Python set in `scan()`) is left completely alone - it still exists and still governs the pure-Python `sweep` branch (reached only when `native is None`), never touched by `native_sweep` after this change.

- [ ] **Step 10: Run the give-way "native or not" parity test and the native sweep test**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vias_give_way.py tests/test_vias_give_way_kicad.py tests/test_native_sweep.py tests/test_native_legal.py
```
Expected: all pass, unchanged (this is the step most likely to reveal a triples-order or dedup mistake - `test_a_native_sweep_is_the_python_sweep` and `test_a_sweep_whose_vias_give_way_is_the_same_native_or_not` both replay the exact same scan twice, toggling `NATIVE_SWEEP`, and assert byte-identical `ScanResult`s).

- [ ] **Step 11: Bench - default tally and the whole-board case, profiled AND unprofiled**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2
```
Expected: `same 32` on every config.
```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --board
```
```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -c "
import cProfile, pstats, sys
sys.path.insert(0, 'fixtures')
import bench
p = cProfile.Profile()
p.enable()
bench.bench_module(str(bench.boards()[0]), bench.CONFIGS)
p.disable()
pstats.Stats(p).sort_stats('cumulative').print_stats(15)
" 2>&1 | tail -30
```
(A single representative module under cProfile, matching how the spec's own baseline was taken, to compare `_decode`/`_grid`/native_sweep-loop/`_native_obstacle_index` self-times against the spec's "~45 s -> under 15 s profiled" target - the exact module chosen does not matter, consistency across before/after does; if time allows, profile the FULL bench corpus the way the spec's own baseline was taken, since a single module may not be representative.)

- [ ] **Step 12: Commit**

Message states: what changed in each of the three spots, the pytest results (step 10), the bench tally (step 11), the profiled before/after for the sweep's Python (against the spec's <15s target, or the honest gap if not met), and the unprofiled whole-board `--board` timing before/after.
```
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "..."
```
```
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 4: Give way - a native offset search for a via's move

**Files:**
- Modify: `native/src/lib.rs` (`NativeObstacles::first_clear_offset`)
- Modify: `src/placemat/giveway.py` (`_give`'s move branch: a helper it calls)
- Test: `tests/test_vias_give_way.py`, `tests/test_vias_give_way_kicad.py` (must pass unchanged); add a small new parity test comparing the native-assisted and pure-Python move searches on an existing give-way fixture.

**Interfaces:**
- Consumes: `NativeObstacles` (already exists), `ShapeGrid::first_conflict_shifted` (already exists, reused as-is).
- Produces (Rust): `NativeObstacles.first_clear_offset(shapes: list[PyShape], offsets: list[tuple[float,float]], clearance: float|None, stop_at_first: bool) -> list[int]` - indices into `offsets`, in the order tested, of every offset at which `shapes` (registered at dx=dy=0, shifted per offset) meet nothing in the grid; with `stop_at_first`, at most one index (the first).
- Produces (Python): a new `giveway._native_move_offsets(occ, judge, g, offsets, clearance)` helper, called from `_give`'s existing move branch in place of its own per-offset `judge.hit(moved, pool, mine, say=False)` loop for the ring/hole test (the tail's own `judge.hit([shape], pool, mine, say=False)` test is UNCHANGED, still Python, still per the one winning offset only - never was the per-offset cost, since it only runs once the ring/hole already cleared).

- [ ] **Step 1: Confirm which shapes in `_give`'s move branch are rigid translations**

Re-read `src/placemat/giveway.py:354-391` (`_give`'s `if s.place_via_move > 0:` block) once more before editing. `ring = _shift(g.ring, dx, dy)` and (when present) `_shift(g.hole, dx, dy)` are exact rigid translations of `g.ring`/`g.hole` by `(dx, dy)` - native-friendly. The tail (`_tail_shape(...)`, built from the FIXED far end `g.far` to the MOVING point `to`) is NOT a rigid translation of the current tail - it is excluded from the native call, tested in Python exactly as today, but only for the one offset the native search already cleared (so its cost drops from "per rejected offset" to "per accepted one").

- [ ] **Step 2: Add `first_clear_offset` to `NativeObstacles` in `native/src/lib.rs`**

```rust
    /// give_way's own move search (`giveway.py` `_give`): every offset of
    /// `offsets`, nearest first, at which `shapes` (registered once, at
    /// their CURRENT position - the offsets are relative to it, dx = dy = 0
    /// meaning "stay put") meet nothing in the grid when shifted by it,
    /// tested with `first_conflict_shifted` (already exact against
    /// Python's own `_conflict`, see that function's own tests). With
    /// `stop_at_first`, the search stops at the first clear offset (a via's
    /// own vias, whose ring position moves with the candidate being placed,
    /// so nothing here is worth caching); without it, every clear offset is
    /// found in one call (a placed via's move search, whose ring position
    /// is fixed for the whole scan - the Python side caches this list per
    /// via and reuses it across every candidate the scan tries against it).
    fn first_clear_offset(
        &self,
        shapes: Vec<PyShape>,
        offsets: Vec<(f64, f64)>,
        clearance: Option<f64>,
        stop_at_first: bool,
    ) -> PyResult<Vec<usize>> {
        let built: Vec<shapes::Shape> = shapes.iter().map(build_shape).collect::<PyResult<_>>()?;
        let mut out = Vec::new();
        for (i, &(dx, dy)) in offsets.iter().enumerate() {
            if self.grid.first_conflict_shifted(&built, dx, dy, clearance, &self.cfg).is_none() {
                out.push(i);
                if stop_at_first {
                    break;
                }
            }
        }
        Ok(out)
    }
```
Register nothing extra (it is a method on the already-registered `NativeObstacles` pyclass).

- [ ] **Step 3: Add a Rust unit test**

In `native/src/shapes.rs` or `native/src/lib.rs` (wherever `NativeObstacles` itself is more naturally tested - check `grep -n "mod tests" native/src/lib.rs` first; `NativeObstacles` is a pyclass, awkward to unit test directly without a Python interpreter, so instead add a `ShapeGrid`-level test in `native/src/shapes.rs` that exercises the SAME loop `first_clear_offset` wraps, since the pyclass itself is a thin loop with no independent logic to miss):

```rust
    #[test]
    fn first_clear_offset_style_loop_finds_the_first_unblocked_shift() {
        let blocker = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "NET", true);
        let grid = ShapeGrid::new(vec![blocker]);
        let via = shape(Kind::Pad, "V1", rect(0.0, 0.0, 0.4, 0.4), 1, 1, "OTHER", true);
        let origin = vec![via];
        let c = cfg();
        let offsets = [(0.0, 0.0), (0.3, 0.0), (1.0, 0.0)];
        let mut found = None;
        for (i, &(dx, dy)) in offsets.iter().enumerate() {
            if grid.first_conflict_shifted(&origin, dx, dy, None, &c).is_none() {
                found = Some(i);
                break;
            }
        }
        assert_eq!(found, Some(2)); // 1.0 mm clears a 1.0 mm pad's clearance from a 0.4 mm via
    }
```

- [ ] **Step 4: `cargo test`, then rebuild and reinstall the wheel**

```
cd /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/native
cargo test
```
Rebuild/reinstall exactly as Task 3 Step 8.

- [ ] **Step 5: Write the failing parity test in Python first**

Add to `tests/test_vias_give_way.py` (find its existing helpers - `_later_board`, `_via`, etc. - by reading the file's top ~100 lines first, and match its style exactly):

```python
def test_a_via_move_is_the_same_native_or_not(monkeypatch):
    """The native offset search (giveway._native_move_offsets) picks the
    same spot the pure-Python per-offset loop would, on a via that must
    move to give way."""
    import pytest
    from placemat import geometry
    if geometry._native is None:
        pytest.skip("no native module")
    # ... build a board whose via must MOVE (not share, not drop) to give
    # way, using the file's existing helpers, reading a couple of the
    # existing "moves" tests nearby for the pattern (e.g. whatever test
    # already exercises place_via_move > 0 with place_via_share = 0) ...
    runs = {}
    for native_on in (False, True):
        monkeypatch.setattr(giveway, "_NATIVE_MOVE_SEARCH", native_on)  # exact flag name set in Step 6
        plan = board().resolve()  # whatever the file's existing pattern is
        runs[native_on] = [(a.kind, a.via, a.to) for a in plan.occupancy.given_way.values()]
    assert runs[True] == runs[False]
```
(This step's exact test body depends on reading the existing file's fixtures - the important, fixed part is the shape: a module-level toggle flag gated the same way `placer.NATIVE_SWEEP` gates the sweep, so both code paths can be run and compared inside one test, on a board picked from the file's existing "a via moves" cases.)

- [ ] **Step 6: Run it, confirm it fails (no such flag/helper yet)**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vias_give_way.py::test_a_via_move_is_the_same_native_or_not
```
Expected: FAIL (`AttributeError` on the missing flag).

- [ ] **Step 7: Implement the helper and wire it into `_give`'s move branch**

In `src/placemat/giveway.py`, add a module flag (mirroring `placer.NATIVE_SWEEP`):
```python
_NATIVE_MOVE_SEARCH = True
"""Whether a via's move search uses the native offset search when it can:
switched off to compare against the pure-Python per-offset loop
(tests/test_vias_give_way.py)."""
```

Add the helper:
```python
def _native_move_offsets(judge: "_Judge", ring, hole, offsets: tuple) -> list | None:
    """The `offsets` (as `_offsets` gives them) at which `ring` and `hole`
    (a via's own, at dx=dy=0), shifted, meet nothing on the board `judge`
    was built against - every one, nearest first - or None when no native
    index is registered on `judge.others` (no native module, or this
    `resolve()` was not given a native-backed obstacle list). Python still
    judges each candidate's own copper (`mine`) and the tail separately;
    this replaces only the per-offset scan of the board itself."""
    if not _NATIVE_MOVE_SEARCH:
        return None
    entry = getattr(judge.others, "_native", None)
    if entry is None:
        return None
    index, shapes = entry
    from .occupancy import _to_native_shape
    py_shapes = [_to_native_shape(s, judge.occ._footprint_refs, judge.occ._leads, judge.occ._margins)
                for s in ((ring,) if hole is None else (ring, hole))]
    clear = index.first_clear_offset(py_shapes, [(dx, dy) for dx, dy in offsets], judge.clearance, False)
    return [offsets[i] for i in clear]
```

Replace the offset loop in `_give`'s move branch. Current code (`src/placemat/giveway.py`, inside `if s.place_via_move > 0:`):
```python
        found = None
        for dx, dy in _offsets(limit, s.place_via_move_step):
            to = (round(g.centre[0] + dx, 9), round(g.centre[1] + dy, 9))
            if inside and not _disc_inside(pad.poly, to, r - 1e-5):
                continue
            if still is not None and still(to):
                continue
            ring = _shift(g.ring, dx, dy)
            if first is not None and first.box.overlaps(ring.box, gap=occ._gap) \
                    and occ._conflict(ring, first, judge.clearance, say=False):
                continue                    # still on what it met: most spots near it are
            moved = [replace(ring, given=g.id)]
            if g.hole is not None:
                moved.append(replace(_shift(g.hole, dx, dy), given=g.id))
            if judge.hit(moved, pool, mine, say=False):
                continue
            track = None
            if g.tail is not None:
                track, shape = _tail_shape(g.owner, g.net, next(iter(g.tail.layers)), width, g.far, to,
                                           carried=g.id, given=g.id)
                if judge.hit([shape], pool, mine, say=False):
                    continue
                moved.append(shape)
            found = Action("move", g.id, g.owner, g.home, g.net, g.centre, to, track, old, pad_key, met,
                           s.score_via_move, tuple(moved))
            break
```
New code: precompute `native_clear = _native_move_offsets(judge, g.ring, g.hole, _offsets(limit, s.place_via_move_step))`; when it is not `None`, drive the loop from it (already board-clear, nearest first - the `first is not None and ...` shortcut is dropped, since `first` is always among `judge.others` and so already excluded by `native_clear` whenever it truly conflicts - see Task 4 Step 1's re-read); when it IS `None` (no native), fall back to the existing per-offset `_shift`+`judge.hit` loop UNCHANGED (byte-identical to today, including the `first is not None` shortcut, so the no-native path's behaviour and cost are exactly what they are today):

```python
        found = None
        all_offsets = _offsets(limit, s.place_via_move_step)
        native_clear = _native_move_offsets(judge, g.ring, g.hole, all_offsets)
        candidates = native_clear if native_clear is not None else all_offsets
        for dx, dy in candidates:
            to = (round(g.centre[0] + dx, 9), round(g.centre[1] + dy, 9))
            if inside and not _disc_inside(pad.poly, to, r - 1e-5):
                continue
            if still is not None and still(to):
                continue
            ring = _shift(g.ring, dx, dy)
            if native_clear is None and first is not None and first.box.overlaps(ring.box, gap=occ._gap) \
                    and occ._conflict(ring, first, judge.clearance, say=False):
                continue                    # still on what it met: most spots near it are (no-native path only)
            moved = [replace(ring, given=g.id)]
            if g.hole is not None:
                moved.append(replace(_shift(g.hole, dx, dy), given=g.id))
            if native_clear is None and judge.hit(moved, pool, mine, say=False):
                continue
            elif native_clear is not None and judge.hit(moved, [], mine, say=False):
                continue                    # native already cleared the board; only the candidate's own copper remains
            track = None
            if g.tail is not None:
                track, shape = _tail_shape(g.owner, g.net, next(iter(g.tail.layers)), width, g.far, to,
                                           carried=g.id, given=g.id)
                if judge.hit([shape], pool, mine, say=False):
                    continue
                moved.append(shape)
            found = Action("move", g.id, g.owner, g.home, g.net, g.centre, to, track, old, pad_key, met,
                           s.score_via_move, tuple(moved))
            break
```
Note `inside`/`still` are STILL applied per candidate offset in BOTH branches - they are candidate/pad-specific filters unrelated to the board scan, unchanged from today; only the "does this offset meet the BOARD" test is swapped for the native-cleared set. The tail's own `judge.hit([shape], pool, mine, ...)` is UNCHANGED in both branches - `pool` is passed to it unchanged, since only the RING/HOLE board-scan was replaced (the tail's shape and its conflict test were never precomputed by `_native_move_offsets`, per Step 1's ruling); this differs slightly from "one call per via" for a via that HAS a tail (a second, Python-side, `pool`-scanning test still runs once per accepted-into-tail-stage offset - which is now rare, since ring/hole already narrowed the field to native-clear ones) - note this in the final report as the actual shape of "one call" (one native call covers ring+hole against the whole board; the tail, not a rigid translation, is not part of it).

- [ ] **Step 8: Run the new parity test, confirm it passes**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vias_give_way.py::test_a_via_move_is_the_same_native_or_not
```
Expected: PASS.

- [ ] **Step 9: Run the full give-way test files and the native-sweep-with-give-way parity test**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vias_give_way.py tests/test_vias_give_way_kicad.py tests/test_native_sweep.py tests/test_native_legal.py
```
Expected: all pass unchanged, including `test_a_sweep_whose_vias_give_way_is_the_same_native_or_not`.

- [ ] **Step 10: Bench - default tally, whole-board placement, unprofiled and profiled give-way share**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2
```
Expected: `same 32`.
```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --board
```
Then a cProfile run of `bench_board()` to measure give way's share of placement time against the "under 15%" target:
```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -c "
import cProfile, pstats, sys
sys.path.insert(0, 'fixtures')
import bench
p = cProfile.Profile()
p.enable()
bench.bench_board()
p.disable()
st = pstats.Stats(p)
st.sort_stats('cumulative').print_stats(20)
"
```
Read `giveway.resolve`'s cumulative time as a share of the whole run's cumulative time from the same profile; report both the absolute number and the percentage, against the spec's "under 15%, down from 76%" target - honestly, including if it is not met.

- [ ] **Step 11: Commit**

Message states: the native `first_clear_offset` addition, the Python-side helper and its fallback, the ruling on the tail (still Python, still per-winning-offset), pytest results, bench tally, and the give-way share before/after against the 15% target.
```
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "..."
```
```
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 5: `NativeFill` - the Rust port of `_Fill`

**Files:**
- Create: `native/src/fill.rs`
- Modify: `native/src/lib.rs` (register `NativeFill`, or a set of free functions - decide in Step 1 based on what state must persist across calls)
- Modify: `src/placemat/checks.py` (`_Fill` gains a native-backed path; `width`'s neck/sentence choice stays Python, calling into `NativeFill` for rasterisation, the transform, `touching` and `_reach`)
- Test: a new parity test file `tests/test_native_fill.py` comparing `NativeFill` against `_Fill` on every `tests/test_current_path_*.py` fill and a slit fill.

**Interfaces:**
- Consumes: `native/src/geometry.rs` (`point_in_polygon`, `point_segment_distance` if needed - check what is already there before duplicating).
- Produces (Rust): a `NativeFill` pyclass: `__new__(poly: list[(f64,f64)], step: f64)`, plus methods mirroring `_Fill`'s own public surface closely enough for `checks.py` to delegate to it: `touching(polys, tau) -> set[int]`, `reach(start, goal, tau) -> (int|None, dict[int,int|None])`, `centre(c) -> (f64,f64)`, `radius(tau) -> f64`, and whatever `width`'s level search (`self.levels`, `self.depths`, `self.deep`) needs exposed to stay in Python OR a `search_levels`-style method if the whole binary search also moves - decide based on Step 1's read.
- Produces (Python): `_Fill` either wraps `NativeFill` internally when available (falling back to the current pure-Python implementation otherwise, exactly as `Occupancy.native_sweeper`/`NATIVE_SWEEP` do) or is replaced by a thin Python class over `NativeFill` plus the neck/sentence code from `width`. Its EXTERNAL callers (`_fill_on`, `width`'s own callers in `current_paths`) see no signature change.

- [ ] **Step 1: Decide the Python/Rust boundary by re-reading `_Fill.width` end to end**

Before writing Rust: `width()` (checks.py:619-681) does a binary search over `self.levels` calling `self.touching`/`self._reach` at each level (native-eligible: pure geometry, no Python business logic), THEN, once `found` is set, walks `path`/`from_entry`/`from_exit` to choose the NECK point and whether it registers as "one step or less" (`w <= self.s + 1e-9`) - the spec says "Python keeps the choice of the neck point and the sentence", so: `touching`, the level search (the `attempt`/binary-search loop), and `_reach` all move to Rust; the neck-selection code after `found is not None` (from `path = []` through the final `return w, self.centre(neck), ...`) STAYS in Python, operating on plain Python lists/sets Rust hands back (`hit`, `parent`, `start`, `goal` from `_reach`; `sq[c]` values). Confirm this boundary reads as buildable (no step needs something only the OTHER side has) before Step 2; if it does not, note the actual boundary chosen and why in the final report (a defensible small deviation from "Python keeps ONLY the neck/sentence choice" is acceptable if the binary search's `attempt()` closure genuinely needs a Python callback - it should not, since `touching`/`_reach` are both already pure geometry, but confirm).

- [ ] **Step 2: Write `native/src/fill.rs` - rasterisation and the two-pass distance transform**

Port `_raster` and `_edt_line` (checks.py:457-513) verbatim in structure (same algorithm - even-odd raster with the half-open row/column scan, then Felzenszwalb-Huttenlocher lower envelope):

```rust
//! `NativeFill`: the Rust port of `checks.py`'s `_Fill` - rasterising a
//! zone fill polygon and, per copper item asked about, the copper's own
//! polygons, both on the fill's grid; the exact two-pass Euclidean
//! distance transform of each (Felzenszwalb and Huttenlocher); `touching`
//! and the breadth-first `_reach` over the fill's cells. The neck point and
//! the "one step or less" sentence stay in Python (`checks.py` `_Fill.width`),
//! which calls `touching`/`reach` here the same number of times, in the
//! same order, as the pure-Python version - see
//! docs/superpowers/specs/2026-09-30-performance-zone-width-give-way-sweep-design.md
//! section 1.

use crate::geometry::Point;
use std::collections::{HashMap, VecDeque};

pub fn raster(polys: &[Vec<Point>], x0: f64, y0: f64, nx: usize, ny: usize, s: f64) -> Vec<bool> {
    let mut inside = vec![false; nx * ny];
    for poly in polys {
        let mut rows: HashMap<i64, Vec<f64>> = HashMap::new();
        let n = poly.len();
        for k in 0..n {
            let (ax, ay) = poly[k];
            let (bx, by) = poly[(k + 1) % n];
            if ay == by {
                continue;
            }
            let (lo, hi) = if ay < by { (ay, by) } else { (by, ay) };
            let r_lo = (((lo - y0) / s - 0.5).ceil()).max(0.0) as i64;
            let r_hi = ((((hi - y0) / s - 0.5).ceil()) as i64).min(ny as i64);
            for r in r_lo..r_hi {
                let y = y0 + (r as f64 + 0.5) * s;
                let x = ax + (y - ay) * (bx - ax) / (by - ay);
                rows.entry(r).or_default().push(x);
            }
        }
        for (r, mut xs) in rows {
            xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let base = (r as usize) * nx;
            let mut it = xs.chunks_exact(2);
            for pair in &mut it {
                let (a, b) = (pair[0], pair[1]);
                let c0 = (((a - x0) / s - 0.5).ceil().max(0.0)) as usize;
                let c1 = ((((b - x0) / s - 0.5).ceil()) as i64).clamp(0, nx as i64) as usize;
                if c1 > c0 {
                    for c in c0..c1 {
                        inside[base + c] = true;
                    }
                }
            }
        }
    }
    inside
}

pub fn edt_line(f: &[f64]) -> Vec<f64> {
    let n = f.len();
    let finite: Vec<usize> = (0..n).filter(|&q| f[q].is_finite()).collect();
    if finite.is_empty() {
        return vec![f64::INFINITY; n];
    }
    let mut v = vec![finite[0]];
    let mut z = vec![f64::NEG_INFINITY, f64::INFINITY];
    for &q in &finite[1..] {
        loop {
            let p = *v.last().unwrap();
            let cut = ((f[q] + (q * q) as f64) - (f[p] + (p * p) as f64)) / (2.0 * (q as f64 - p as f64));
            if cut > z[z.len() - 2] {
                break;
            }
            v.pop();
            z.pop();
        }
        v.push(q);
        *z.last_mut().unwrap() = {
            let p = v[v.len() - 2];
            ((f[q] + (q * q) as f64) - (f[p] + (p * p) as f64)) / (2.0 * (q as f64 - p as f64))
        };
        z.push(f64::INFINITY);
    }
    let mut d = vec![0.0; n];
    let mut k = 0;
    for q in 0..n {
        while z[k + 1] < q as f64 {
            k += 1;
        }
        let p = v[k];
        let dq = q as f64 - p as f64;
        d[q] = dq * dq + f[p];
    }
    d
}

pub fn distance_transform(inside: &[bool], nx: usize, ny: usize) -> Vec<f64> {
    let mut cols = vec![0.0; nx * ny];
    for q in 0..nx {
        let col: Vec<f64> = (0..ny).map(|r| if inside[r * nx + q] { f64::INFINITY } else { 0.0 }).collect();
        let d = edt_line(&col);
        for r in 0..ny {
            cols[r * nx + q] = d[r];
        }
    }
    let mut sq = vec![0.0; nx * ny];
    for r in 0..ny {
        let d = edt_line(&cols[r * nx..(r + 1) * nx]);
        sq[r * nx..(r + 1) * nx].copy_from_slice(&d);
    }
    sq
}
```
Re-check the `edt_line` port's `z[-1] = cut` bookkeeping against the Python once written (the Python mutates `z[-1]` AFTER `v.append(q)`, i.e., it sets the boundary for the JUST-pushed parabola, then pushes a new `math.inf` sentinel) - the Rust above recomputes `cut` a second time after the loop to match that exactly rather than trying to reuse the loop-local `cut` (which is out of scope after the `loop{}` - a deliberate small inefficiency, acceptable, OR restructure to carry `cut` out of the loop via a `let cut = loop { ... break cut; };` - prefer this cleaner form when actually writing the file, re-deriving `cut` a second time above is a plan-writing shortcut, not a requirement).

- [ ] **Step 3: Add `touching` and `reach` to `fill.rs`, and a `NativeFill` struct**

```rust
pub struct NativeFill {
    pub x0: f64,
    pub y0: f64,
    pub s: f64,
    pub nx: usize,
    pub ny: usize,
    pub inside: Vec<bool>,
    pub sq: Vec<f64>,
    pub deep: Vec<usize>,      // cells, deepest first
    pub depths: Vec<f64>,      // -sq[c], parallel to `deep`, for a bisect-style prefix count
    pub levels: Vec<f64>,      // sorted distinct sq values among `deep`
    copper_cache: std::cell::RefCell<HashMap<usize, Vec<f64>>>,  // keyed by the Python side's polys identity (passed in)
}

impl NativeFill {
    pub fn new(poly: &[Point], step: f64) -> Self {
        // box, x0/y0/nx/ny exactly as _Fill.__init__: box.left - step etc.
        // (port Box::of_points equivalent from geometry.rs; use whatever
        // this crate already has - check native/src/geometry.rs before
        // adding a duplicate).
        todo!("port _Fill.__init__'s box/grid sizing, then raster+distance_transform, then deep/depths/levels")
    }

    pub fn radius(&self, tau: f64) -> f64 {
        self.s * (tau.sqrt() - 0.5)
    }

    pub fn centre(&self, c: usize) -> Point {
        let (r, q) = (c / self.nx, c % self.nx);
        (self.x0 + (q as f64 + 0.5) * self.s, self.y0 + (r as f64 + 0.5) * self.s)
    }

    /// `_Fill.touching`, against a copper transform computed fresh each
    /// call (the Python side caches by polys identity across `width`'s
    /// binary search - see checks.py's `_copper_distance`; here it is
    /// cached too, keyed by a small integer id the Python side assigns per
    /// distinct `polys` object for one `NativeFill`'s lifetime, passed in
    /// alongside the polygons on the FIRST call for that id and omitted on
    /// later ones - mirrors `_native_origin_shapes`'s "register once,
    /// reuse by handle" pattern).
    pub fn touching(&self, copper_sq: &[f64], tau: f64, box_: (f64, f64, f64, f64)) -> Vec<usize> {
        todo!("port _Fill.touching's cell-gathering (deep/depths bisect OR full box scan) plus the copper_sq[c] <= limit test - see checks.py Task 1 Step 4's ported Python for the exact formula")
    }

    pub fn reach(&self, start: &[usize], goal: &[usize], tau: f64) -> (Option<usize>, HashMap<usize, Option<usize>>) {
        let goal_set: std::collections::HashSet<usize> = goal.iter().copied().collect();
        let mut parent: HashMap<usize, Option<usize>> = start.iter().map(|&c| (c, None)).collect();
        let mut todo: VecDeque<usize> = start.iter().copied().collect();
        while let Some(c) = todo.pop_front() {
            if goal_set.contains(&c) {
                return (Some(c), parent);
            }
            let (r, q) = (c / self.nx, c % self.nx);
            for rr in r.saturating_sub(1)..=(r + 1).min(self.ny - 1) {
                for qq in q.saturating_sub(1)..=(q + 1).min(self.nx - 1) {
                    let n = rr * self.nx + qq;
                    if parent.contains_key(&n) || !self.inside[n] {
                        continue;
                    }
                    if self.sq[n] >= tau || goal_set.contains(&n) {
                        parent.insert(n, Some(c));
                        todo.push_back(n);
                    }
                }
            }
        }
        (None, parent)
    }
}
```
Note the `todo!()` markers above are PLAN TEXT ONLY, marking exactly what must be transcribed from the already-ported Python (Task 1's `_Fill.touching`, and `_Fill.__init__`'s box/grid sizing) - when actually writing `fill.rs`, replace every `todo!()` with the real port; no `todo!()` may reach a commit (a panic-on-call stub fails "No Placeholders" and, worse, fails at runtime the first time any test calls it - `cargo test`/pytest will catch a leftover one immediately).

- [ ] **Step 4: Expose `NativeFill` as a pyclass in `native/src/lib.rs`**

```rust
#[pyclass]
struct NativeFill {
    inner: fill::NativeFill,
    copper: std::collections::HashMap<usize, Vec<f64>>,
}

#[pymethods]
impl NativeFill {
    #[new]
    fn new(poly: Vec<Point>, step: f64) -> Self {
        NativeFill { inner: fill::NativeFill::new(&poly, step), copper: std::collections::HashMap::new() }
    }

    fn radius(&self, tau: f64) -> f64 {
        self.inner.radius(tau)
    }

    fn centre(&self, c: usize) -> Point {
        self.inner.centre(c)
    }

    /// `polys_id`: an integer the Python `_Fill` assigns per distinct
    /// `entry`/`exit_` tuple it calls `touching` with (their `id()`, same
    /// as `checks.py`'s own `_copper_distance` cache key) - `polys` is only
    /// needed (and only rasterised) the FIRST time a given id is seen by
    /// this `NativeFill` instance.
    fn touching(&mut self, polys_id: usize, polys: Option<Vec<Vec<Point>>>, tau: f64,
               box_: (f64, f64, f64, f64)) -> PyResult<Vec<usize>> {
        if !self.copper.contains_key(&polys_id) {
            let polys = polys.ok_or_else(|| PyValueError::new_err(
                "touching: polys_id not cached yet and no polys given to build it"))?;
            let inside = fill::raster(&polys, self.inner.x0, self.inner.y0, self.inner.nx, self.inner.ny, self.inner.s);
            self.copper.insert(polys_id, fill::distance_transform(&inside, self.inner.nx, self.inner.ny));
        }
        Ok(self.inner.touching(&self.copper[&polys_id], tau, box_))
    }

    fn reach(&self, start: Vec<usize>, goal: Vec<usize>, tau: f64) -> (Option<usize>, HashMap<usize, Option<usize>>) {
        self.inner.reach(&start, &goal, tau)
    }

    #[getter]
    fn levels(&self) -> Vec<f64> {
        self.inner.levels.clone()
    }
}
```
Register `m.add_class::<NativeFill>()?;` in `fn placemat_native`. Add `mod fill;` near the top of `lib.rs`'s other `mod` declarations.

- [ ] **Step 5: Write the Rust unit tests for `fill.rs` before wiring Python**

In `native/src/fill.rs`, `#[cfg(test)] mod tests`: a small rectangle poly, assert `raster`'s inside-count matches a hand count; assert `distance_transform`'s centre cell has the largest `sq`; assert `reach` finds a path across a simple 5x5 all-inside grid and returns `None` when `goal` is unreachable (an isolated inside region separated by an all-outside band, `tau` set so the band is impassable). Run:
```
cd /home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/native
cargo test
```
Fix until green before proceeding (this is the TDD gate for the Rust side - Python parity in Step 8 is the SECOND gate, not a substitute for this one).

- [ ] **Step 6: Rebuild and reinstall the wheel**

Exactly as Task 3 Step 8 / Task 4 Step 4.

- [ ] **Step 7: Write the failing parity test in Python**

Create `tests/test_native_fill.py`:
```python
"""NativeFill against the Python `_Fill`: the same widths and neck cells on
every current-path test fill, and on a slit fill (a zero-width seam to a
hole, KiCad's own way of drawing a thermal void inside a pour)."""
import pytest

native = pytest.importorskip("placemat_native")

from placemat.checks import _Fill
from tests.test_current_path_zone_width import _zone  # reuse its exact fixtures


def _fills():
    lane = [(11, 9.4), (19, 9.4), (19, 10.6), (11, 10.6)]
    slit = ((11, 8), (19, 8), (19, 12), (15, 12), (15, 10.5),
            (14.5, 10.5), (14.5, 9.5), (15.5, 9.5), (15.5, 10.5), (15, 10.5),
            (15, 12), (11, 12))
    return [lane, slit]


@pytest.mark.parametrize("poly", _fills())
def test_native_fill_matches_python_fill_width(poly):
    entry = [[(11, 9.4), (11, 10.6), (11.5, 10.6), (11.5, 9.4)]]
    exit_ = [[(18.5, 9.4), (18.5, 10.6), (19, 10.6), (19, 9.4)]]
    py = _Fill(poly, 0.05)
    got_py = py.width(entry, exit_)
    # ... construct the same answer through NativeFill's touching/reach,
    # driven by the SAME width() neck-selection code (extracted in Task 5
    # Step 1's Python-side refactor so both paths share it) ...
    assert got_native == got_py
```
(The exact wiring in the `...` depends on Task 5 Step 8's `_Fill` refactor - write this test's assertion shape now, fill in the call once `_Fill` has a native-backed constructor path, e.g. `_Fill(poly, step, native=True)` or a module-level toggle `checks._NATIVE_FILL` mirroring `placer.NATIVE_SWEEP` - PICK ONE naming convention consistent with `NATIVE_SWEEP`/`_NATIVE_MOVE_SEARCH` before writing this test, and use it in both this test and Step 8.)

- [ ] **Step 8: Wire `_Fill` to use `NativeFill` when available**

In `src/placemat/checks.py`, add:
```python
_NATIVE_FILL = True
"""Whether a zone fill's width search uses NativeFill when it can:
switched off to compare against the pure-Python `_Fill` (tests/test_native_fill.py)."""
```
Give `_Fill.__init__` a native-backed path: when `_geometry_module._native is not None and hasattr(_native, "NativeFill") and _NATIVE_FILL`, build `self._native = _native.NativeFill(poly, step)` and set `self.x0, self.y0, self.nx, self.ny, self.s` from it (needed by `centre`/`width`'s own remaining Python), skip the Python raster/transform/deep/depths/levels work entirely; `touching`, `radius`, `_reach` each check `self._native is not None` first and delegate (passing `id(polys)` and, on a cache miss inside Rust - which the pyclass method itself detects and asks for - the actual polygons); when `self._native is None`, run exactly the current Python bodies unchanged. `width()` itself needs NO change beyond reading `self.levels` from whichever source built it (native's `.levels` getter matches the Python attribute name, so `self.levels = fill_native.levels if self._native else sorted(...)` keeps `width()`'s own code untouched).

- [ ] **Step 9: Run the parity test, iterate to green**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_native_fill.py
```
Then extend `_fills()` (or add a second parametrised test) to cover every fill literal already used across `tests/test_current_path_neck.py`, `tests/test_current_path_pairs.py`, `tests/test_current_path_zone_width.py` (read each file, pull out every zone polygon a test builds, run it through both paths) - this is the "every current-path test fill" the spec requires, not just the two illustrative ones above.

- [ ] **Step 10: Run the full current-path and cell-zone test files with `_NATIVE_FILL` on (default) and confirm identical results with it off**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_current_path_neck.py tests/test_current_path_pairs.py tests/test_current_path_zone_width.py tests/test_cell_zones.py tests/test_merged_zones_text.py tests/test_native_fill.py
```
Then re-run with the flag forced off (a small monkeypatch in a throwaway invocation, or temporarily flip the module default and re-run, reverting after) to confirm the pure-Python path is untouched and still green.

- [ ] **Step 11: Run `run_checks` on the whole-board fixture's written board, both paths, compare verdicts**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --checks
```
This is the number to compare against Task 1's (Python-only raster) and Task 2's baseline `--checks` timings, and against the spec's "under 30 s, unprofiled" target. List every verdict that differs from Task 2's baseline run (should be none beyond what Task 1 already introduced and listed, since Task 5 is a pure speed port of the SAME algorithm Task 1 already put in place - NativeFill's parity tests are exactly what guarantee this).

- [ ] **Step 12: Bench - default tally and both whole-board numbers**

```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2
```
Expected: `same 32`.
```
PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/.native-build:/home/ben/work/placemat/.claude/worktrees/agent-ac6b28de9d1ab4d11/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --board
```

- [ ] **Step 13: Commit**

Message states: the `NativeFill` port and its Python-side toggle, the parity test coverage (every current-path fixture fill plus a slit fill), pytest results, the whole-board `--checks` timing against the "under 30 s" target, the bench tally, and the `--board` timing (should be unchanged from Task 4, since NativeFill affects checks only).
```
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "..."
```
```
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Final report

After Task 5's commit, gather: `git log` for the five (or more) commit hashes/subjects on this branch; the before/after timings collected at each task's Step (bench --board, --checks, --jobs 2 tallies, and the profiled numbers from Tasks 3 and 4) against the spec's four targets (checks <30s, give-way <15% of placement time, sweep's Python <15s profiled, and the overall shape of the change); the zone-width verdict diff list from Task 2/Task 5; every ruling made (documented already, per task, above - collect them: Task 1's tolerance formula, Task 3's `NativeSweepSeen` bit-identity argument and the `_native_obstacle_index` "already optimal, not touched further" ruling if it holds up, Task 4's tail-stays-Python ruling and the dropped `first`-shortcut, Task 5's Python/Rust boundary and any Step 3 sizing deviations); anything left undone (in particular: confirm whether `_native_obstacle_index`'s already-existing per-skip-set cache needed any change at all - Task 3 Step 11's profiling is the evidence either way, and if it turns out untouched, say so plainly rather than silently skipping the spec's mention of it).
