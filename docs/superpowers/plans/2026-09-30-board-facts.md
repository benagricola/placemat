# Board facts: fixed and preferred - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Board facts (stackup copper weight, layer roles, differential
pair classes) come from the generated board instead of placemat.toml;
fab-profile.json gains fixed/preferred via types and fab minimums; a new
`placemat facts` command tracks whether a project has confirmed them.

**Architecture:** Read new facts off the KiCad board (per-layer copper
thickness, already-read layer roles) and off fab-profile.json (via tiers,
fab minimums); retire the placemat.toml keys that named board facts;
thread the new facts through the current-path check, the router's default
layer list, differential-pair naming, and give-way's new "shorten" way;
add a `placemat facts` command that digests the printed facts and records
confirmation in placemat.toml, read at the start of every run.

**Tech Stack:** Python 3.11+, pcbnew 10 (KiCad's Python bindings), pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-board-facts-fixed-and-preferred-design.md`

## Global Constraints

- placemat is 100% project-agnostic: no project, board, module or part
  names in source, tests' prose, docstrings, skill, references, migration
  or commit messages; migration examples use placeholders (`<mm>`,
  `<NET>_P`).
- Tunables are settings with defaults, documented in api.md's settings
  table, never literals. Fixed sets are enums.
- Plain ASCII only: no em/en dashes, no unicode arrows, straight quotes.
- A new field that feeds a digest (`Settings.json()`, `FabProfile.json()`)
  carries `metadata={"omit_default": True}` only where the existing code
  already does that; `FabProfile.json()` for a profile with no new keys
  must byte-for-byte match what it produces today (digest parity tests
  pass unchanged).
- Commits: `git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la
  commit ...`; zero references to Claude, Anthropic, AI, sessions or
  Co-Authored-By; after each commit, `git log -1 --format=%B | grep -iE
  "claude|anthropic|session|co-authored"` must print nothing.
- Tests: targeted files only. Run with
  `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest
  -q -p no:cacheprovider tests/<files>` (after `cp
  /home/ben/work/placemat/src/placemat/_version.py src/placemat/`). Never
  `uv pip install`. Never run the router.
- `board.Delete(item)`, never `board.Remove(item)`, for any pcbnew item
  taken off a board for good (see the worktree's CLAUDE.md).
- Bench once at the end: `PYTHONPATH=$PWD/src
  /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2`,
  tally in the final commit message.

## Review Focus

- A board with no explicit stackup (KiCad writes no `(stackup ...)` block
  at all when `m_HasStackup` is false) must still get a sensible copper
  weight per layer (the old 1 oz fallback), not a crash or a silent 0 mm
  width requirement. Covered in Task 1.
- KiCad's Default net class always reports a non-zero
  `diff_pair_width`/`diff_pair_gap` (verified on a real generated board:
  0.2/0.2mm) even though nobody declared a pair on it; naive code that
  pairs on "diff_pair_width is not None" would wrongly pair Default nets.
  Covered in Task 5.
- A via type of tier `"if-needed"` must be refused exactly like `"no"`
  when a script asks for it directly (`board.via(..., layers=...)`), not
  silently allowed because give-way's shorten way can use it. Covered in
  Task 8.
- `placemat facts --confirm` must not perturb `run_id`/`Settings.json()`:
  a confirm that changes a script's next run id would re-plan a board for
  no placement reason. Covered in Task 3.
- A board whose `.kicad_pcb` has 6+ layers with mixed inner roles (signal,
  power, mixed) must route on exactly the signal/mixed ones plus F/B,
  independent of whether a zone happens to fill an inner layer - this is
  a real behaviour change from today's plane-coverage heuristic. Covered
  in Task 6, verified against the spec's example (F signal, In1 ground,
  In2 signal, In3 power, In4 ground, B signal -> routes on F, In2, B).

---

## File Structure

- `src/placemat/board_geometry.py` - `BoardGeometry` gains `copper_mm`.
- `src/placemat/kicad/read.py` - reads per-layer copper thickness from the
  board's stackup; `_layer_types` renamed to the public `layer_types`.
- `src/placemat/checks.py` - `ipc2221_width_mm` takes a `k` constant;
  `current_paths`/`_pairs`/`_neck`/`_fill_on` judge each layer by its own
  weight.
- `src/placemat/settings.py` - retires `check_copper_oz`, `route_layers`,
  `route_diff_pairs`; adds `score_via_shorten`, `facts_confirmed`.
- `src/placemat/pairs.py` - `class_pairs(netclasses)`: pairs from net
  classes instead of `route.diff_pairs` patterns.
- `src/placemat/score.py`, `src/placemat/occupancy.py`, `src/placemat/runner.py` -
  swap their `pairs_of(..., route_diff_pairs)` source for `class_pairs`.
- `src/placemat/kicad/route.py` - `resolved_layers` becomes role-based;
  `plane_layers`/`_plane_zones` (now unused) removed; `route_pairs`
  sourced from `class_pairs`.
- `src/placemat/project.py` - `FabProfile` gains via tiers and `min`;
  `fab_minimum_findings`.
- `src/placemat/layout.py` - `Board` gains `fab_vias_needed`, `fab_min`;
  via declaration refuses an if-needed type like a no; fab-minimum
  findings wired into `resolve()`.
- `src/placemat/findings.py` - `fab`, `facts`, `needs` kinds.
- `src/placemat/giveway.py` - the "shorten" way.
- `src/placemat/facts.py` (new) - the facts document and its digest.
- `src/placemat/cli.py` - `placemat facts` command; drops `--copper-oz`.
- `skills/placemat/SKILL.md`, `skills/placemat/references/api.md`,
  `skills/placemat/references/capture.md`,
  `skills/placemat/references/migration.md` - doc updates.

---

### Task 1: Per-layer copper weight from the board's stackup

**Files:**
- Modify: `src/placemat/board_geometry.py` (`BoardGeometry` dataclass)
- Modify: `src/placemat/kicad/read.py` (`board_geometry_of`, `_layer_types` -> `layer_types`)
- Test: `tests/test_board_geometry_read.py`, `tests/test_stackup_copper_mm.py` (new)

**Interfaces:**
- Produces: `BoardGeometry.copper_mm: dict[CopperLayer, float]` (compare=False,
  default `{}`); `placemat.kicad.read.stackup_copper_mm(path) -> dict[CopperLayer, float]`;
  `placemat.kicad.read.layer_types(board)` (renamed from `_layer_types`,
  same behaviour).

- [ ] **Step 1: Verify the KiCad Python API cannot read the stackup on this build, in a scratch script (not a test)**

  Already verified during planning: `board.GetDesignSettings().GetStackupDescriptor()`
  and `board.GetStackupOrDefault()` both return a bare `SwigPyObject` with
  no usable methods on this machine's pcbnew 10.0.6 (`BOARD_STACKUP` is not
  wrapped for Python). This is a documented divergence from the spec's
  suggested API: read the `(stackup ...)` block directly from the
  `.kicad_pcb` text instead. Re-run this check only if it's suspicious:

  ```
  /home/ben/work/placemat/.venv/bin/python -c "
  import pcbnew
  b = pcbnew.LoadBoard('/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/fairprof/electronics/boards/core/.placemat/generated/Core/layout.kicad_pcb')
  print(type(b.GetDesignSettings().GetStackupDescriptor()))
  " 2>&1 | grep -v assert
  ```

- [ ] **Step 2: Write the failing test for the text-parsed stackup reader**

  Create `tests/test_stackup_copper_mm.py`:

  ```python
  """Per-layer copper thickness, read from the .kicad_pcb's own (stackup
  ...) block: pcbnew's BOARD_STACKUP is not wrapped for Python on this
  build (GetStackupDescriptor()/GetStackupOrDefault() come back as a bare
  SwigPyObject with no methods), so this reads the board's own text."""
  from placemat.kicad.read import stackup_copper_mm
  from placemat.values import CopperLayer

  F, B, IN1, IN2 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1, CopperLayer.IN2

  _STACKUP_PCB = """(kicad_pcb
    (setup
      (stackup
        (layer "F.SilkS" (type "Top Silk Screen"))
        (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
        (layer "F.Cu" (type "copper") (thickness 0.035))
        (layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4"))
        (layer "In1.Cu" (type "copper") (thickness 0.0152))
        (layer "dielectric 2" (type "core") (thickness 1.51) (material "FR4"))
        (layer "B.Cu" (type "copper") (thickness 0.035))
      )
    )
  )
  """

  _NO_STACKUP_PCB = "(kicad_pcb (setup (pad_to_mask_clearance 0)))\n"


  def test_each_copper_layers_thickness_is_read_in_mm(tmp_path):
      p = tmp_path / "layout.kicad_pcb"
      p.write_text(_STACKUP_PCB)
      assert stackup_copper_mm(p) == {F: 0.035, IN1: 0.0152, B: 0.035}


  def test_a_board_with_no_stackup_block_gives_no_weights(tmp_path):
      """A board whose .zen declares no stackup: KiCad writes no (stackup
      ...) block at all (m_HasStackup is false), confirmed by saving a
      fresh CreateEmptyBoard() and reading it back."""
      p = tmp_path / "layout.kicad_pcb"
      p.write_text(_NO_STACKUP_PCB)
      assert stackup_copper_mm(p) == {}
  ```

- [ ] **Step 3: Run it, confirm it fails with ImportError/AttributeError**

  `cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/ &&
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest
  -q -p no:cacheprovider tests/test_stackup_copper_mm.py`

- [ ] **Step 4: Implement `stackup_copper_mm` in `src/placemat/kicad/read.py`**

  Add near the top-level helpers (after `mm()`), no pcbnew needed:

  ```python
  import re as _re

  _STACKUP_LAYER_RE = _re.compile(r'\(layer\s+"([^"]+\.Cu)"\s*\(type\s+"copper"\)\s*\(thickness\s+([-\d.eE]+)\)')


  def stackup_copper_mm(path) -> dict:
      """Each copper layer's thickness in mm, read from the board's own
      (stackup ...) block. pcbnew's BOARD_STACKUP class is not wrapped for
      Python on the installed build (GetStackupDescriptor() and
      GetStackupOrDefault() come back as opaque SwigPyObjects with no
      methods), so this reads the board's own text instead - the same file
      pcbnew itself wrote. {} when the board declares no stackup (KiCad
      omits the block entirely; the board's .zen gave it none)."""
      text = Path(path).read_text(errors="replace")
      start = text.find("(stackup")
      if start < 0:
          return {}
      depth, end = 0, len(text)
      for i in range(start, len(text)):
          if text[i] == "(":
              depth += 1
          elif text[i] == ")":
              depth -= 1
              if depth == 0:
                  end = i + 1
                  break
      block = text[start:end]
      return {CopperLayer.of(name): float(thickness) for name, thickness in _STACKUP_LAYER_RE.findall(block)}
  ```

- [ ] **Step 5: Run the test, confirm it passes**

- [ ] **Step 6: Wire it into `BoardGeometry` and `board_geometry_of`**

  In `src/placemat/board_geometry.py`, add to `BoardGeometry` right after
  `layer_types`:

  ```python
      copper_mm: dict = field(default_factory=dict, compare=False)   # CopperLayer -> thickness mm, from the board's stackup; {}: no stackup declared
  ```

  In `src/placemat/kicad/read.py`, rename `_layer_types` to `layer_types`
  (drop the leading underscore; it is now used from `kicad/route.py` too -
  Task 6) and update its one call site at the bottom of `board_geometry_of`:

  ```python
      return BoardGeometry(path=path, footprints=fps, cells=cells, copper=copper, outline=_outline(board),
                      nets=frozenset(classes), netclasses=classes, default_clearance=default_clr,
                      layers=layers, edge_clearance=mm(board.GetDesignSettings().m_CopperEdgeClearance),
                      hole_to_hole=mm(board.GetDesignSettings().m_HoleToHoleMin),
                      silk_clearance=mm(board.GetDesignSettings().m_SilkClearance),
                      hole_clearance=mm(board.GetDesignSettings().m_HoleClearance),
                      rule_areas=_rule_areas(board, groups_of),
                      board_polygon=_board_polygon(board), layer_types=layer_types(board),
                      copper_mm=stackup_copper_mm(path))
  ```

- [ ] **Step 7: Write a failing test that a real generated board's inner layer reads its actual (non-1oz) weight**

  Add to `tests/test_board_geometry_read.py` (it already reads real
  boards through pcbnew - follow its existing fixture conventions; grep
  the file first for how it builds/loads a board and what `needs_kicad`
  marker it uses). Write a small fixture board with `SetCopperLayerCount`
  and a hand-set stackup via direct file text (reuse the pattern from
  Step 2, since pcbnew cannot write BOARD_STACKUP either), or exercise
  `board_geometry_of` end to end through `read_board` on a temp file built
  the same way as Step 2's `_STACKUP_PCB` plus enough board scaffolding
  (`general`, `layers`, an empty footprint list) for `pcbnew.LoadBoard` to
  accept it - check `tests/test_via_span.py`'s `_six_layer_board` helper
  for the minimal valid board pattern (`pcbnew.CreateEmptyBoard()`,
  `SetCopperLayerCount(6)`, save, then patch the saved file's setup block
  to insert the stackup text before re-loading with `read_board`).

  ```python
  def test_read_board_carries_the_stackups_copper_weight(tmp_path):
      import pcbnew
      from placemat.kicad.read import read_board
      board = pcbnew.CreateEmptyBoard()
      board.SetCopperLayerCount(4)
      p = tmp_path / "layout.kicad_pcb"
      board.Save(str(p))
      text = p.read_text()
      stack = ('\t\t(stackup\n\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))\n'
               '\t\t\t(layer "In1.Cu" (type "copper") (thickness 0.0152))\n'
               '\t\t\t(layer "In2.Cu" (type "copper") (thickness 0.0152))\n'
               '\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))\n\t\t)\n')
      text = text.replace("\t\t(pad_to_mask_clearance", stack + "\t\t(pad_to_mask_clearance")
      p.write_text(text)
      g = read_board(p)
      from placemat.values import CopperLayer
      assert g.copper_mm[CopperLayer.IN1] == 0.0152
  ```

  Mark it `@needs_kicad` (see `tests/conftest.py`'s marker; grep other
  tests in the file for the exact decorator usage).

- [ ] **Step 8: Run it, confirm it fails (KeyError/AttributeError) then passes after Step 6's wiring**

- [ ] **Step 9: Run the targeted tests and commit**

  ```bash
  cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_stackup_copper_mm.py tests/test_board_geometry_read.py
  git add src/placemat/board_geometry.py src/placemat/kicad/read.py tests/test_stackup_copper_mm.py tests/test_board_geometry_read.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  Board geometry carries each copper layer's weight from the stackup

  pcbnew's BOARD_STACKUP is not wrapped for Python on the installed KiCad
  10 build, so the board's (stackup ...) block is read from its own text.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 2: The current-path check judges each layer by its own weight

**Files:**
- Modify: `src/placemat/checks.py`
- Test: `tests/test_current_path_neck.py`, `tests/test_current_path_pairs.py`, `tests/test_current_path_zone_width.py` (existing, must keep passing), `tests/test_current_path_inner_layer.py` (new)

**Interfaces:**
- Consumes: `BoardGeometry.copper_mm` (Task 1).
- Produces: `ipc2221_width_mm(current_a, rise_c=TRACK_RISE_C, copper_oz=COPPER_OZ, k=_IPC_K_OUTER)`
  (new optional `k` parameter, old calls unaffected); `_IPC_K_INNER = 0.024`
  module constant; `current_paths(geometry, rise_c=TRACK_RISE_C,
  copper_oz=COPPER_OZ, zone_step=ZONE_STEP)` (unchanged signature - `copper_oz`
  becomes the fallback for a layer `geometry.copper_mm` does not name).

- [ ] **Step 1: Write the failing test for the inner-layer constant**

  Create `tests/test_current_path_inner_layer.py`:

  ```python
  """The current-path check judges each piece of copper by its own layer's
  weight, read from the board's stackup: the inner-layer IPC-2221 constant
  (k = 0.024) on an inner layer, against 0.048 on an outer one, and the
  layer's own copper weight rather than a single [check] copper_oz."""
  import dataclasses

  import pytest

  from placemat.checks import current_paths, ipc2221_width_mm
  from placemat.values import CopperLayer
  from tests.fixtures import board_geometry, footprint, track


  def test_the_inner_constant_needs_a_wider_track_than_the_outer_one():
      """Same current, same rise, same weight: the inner-layer formula
      needs more copper than the outer one (a smaller k means a bigger
      area for the same current)."""
      outer = ipc2221_width_mm(3.0, rise_c=10.0, copper_oz=1.0, k=0.048)
      inner = ipc2221_width_mm(3.0, rise_c=10.0, copper_oz=1.0, k=0.024)
      assert inner > outer


  def test_a_track_on_an_inner_layer_is_judged_by_its_own_stackup_weight():
      """A 0.5 oz inner track (0.0175 mm, from the stackup) is judged with
      k = 0.024 and 0.5 oz - not the 1 oz outer default - so it needs a
      wider track than the same current would on F.Cu."""
      u = footprint("U1", 10, 10, nets=("VIN", "X"), fields={"Pm.I": "vin:3A"})
      c = footprint("C1", 30, 10, nets=("VIN", "GND"), fields={"Pm.I": "vin:3A"})
      wide = track("VIN", 8.6, 10, 28.6, 10, w=2.0, layer=CopperLayer.IN1)
      g = dataclasses.replace(board_geometry([u, c], copper=[wide]),
                               layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.B),
                               copper_mm={CopperLayer.IN1: 0.0175})
      v = {x.subject: x for x in current_paths(g)}["VIN"]
      need_inner = ipc2221_width_mm(3.0, 10.0, 0.0175 / 0.0350012, 0.024)
      assert v.limit == pytest.approx(need_inner, rel=1e-6)


  def test_a_layer_missing_from_the_stackup_falls_back_to_1_oz():
      """A board with no explicit stackup (copper_mm empty for that layer)
      still judges an inner track with the inner constant, at the 1 oz
      fallback."""
      u = footprint("U1", 10, 10, nets=("VIN", "X"), fields={"Pm.I": "vin:3A"})
      c = footprint("C1", 30, 10, nets=("VIN", "GND"), fields={"Pm.I": "vin:3A"})
      wide = track("VIN", 8.6, 10, 28.6, 10, w=2.0, layer=CopperLayer.IN1)
      g = dataclasses.replace(board_geometry([u, c], copper=[wide]),
                               layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.B))
      v = {x.subject: x for x in current_paths(g)}["VIN"]
      assert v.limit == pytest.approx(ipc2221_width_mm(3.0, 10.0, 1.0, 0.024), rel=1e-6)
  ```

- [ ] **Step 2: Run it, confirm `ipc2221_width_mm(..., k=...)` fails with a TypeError (unexpected keyword)**

- [ ] **Step 3: Add the `k` parameter and the inner constant**

  In `src/placemat/checks.py`:

  ```python
  _IPC_K_OUTER = 0.048            # IPC-2221 external layer constant
  _IPC_K_INNER = 0.024            # IPC-2221 internal layer constant
  _MIL_PER_OZ = 1.378             # copper thickness per ounce, in mil
  _MM_PER_MIL = 0.0254
  _MM_PER_OZ = _MIL_PER_OZ * _MM_PER_MIL   # ~0.035001 mm per copper ounce
  ```

  ```python
  def ipc2221_width_mm(current_a: float, rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ,
                       k: float = _IPC_K_OUTER) -> float:
      """IPC-2221 width for a current at a temperature rise, on a layer of
      this weight: k is 0.048 for an outer layer, 0.024 for an inner one."""
      area_milsq = (current_a / (k * rise_c ** 0.44)) ** (1 / 0.725)
      return area_milsq / (_MIL_PER_OZ * copper_oz) * _MM_PER_MIL
  ```

- [ ] **Step 4: Run the test, confirm the first two pass and the third (layer-aware `current_paths`) still fails**

- [ ] **Step 5: Thread the neck's own layer through `_neck` and `_fill_on`**

  `_neck` currently returns `(point, total, in_pour)`; extend it to
  return the neck node's own layers too, by grepping its current body
  (it already computes `neck_i`, whose `nodes[neck_i]` tuple's index 4 is
  `layers` per `_net_graph`'s node shape):

  ```python
  def _neck(nodes, best, end_i: int, w: float) -> tuple:
      ...
      return point, total, nodes[neck_i][0] == "poly", nodes[neck_i][4]
  ```

  `_fill_on` currently returns `worst` as `(width, point, one_step_or_less)`
  or `None`; extend the tuple it builds to carry the zone node's layers:

  ```python
  def _fill_on(nodes, path: list, fills: dict, measured: dict, step: float):
      worst = None
      for k in range(1, len(path) - 1):
          z = path[k]
          if nodes[z][0] != "zone":
              continue
          key = (z,) + tuple(sorted((path[k - 1], path[k + 1])))
          if key not in measured:
              if z not in fills:
                  fills[z] = _Fill(nodes[z][2][0], step)
              got = fills[z].width(nodes[path[k - 1]][2], nodes[path[k + 1]][2])
              measured[key] = None if got is None else got + (nodes[z][4],)
          got = measured[key]
          if got is not None and (worst is None or got[0] < worst[0]):
              worst = got
      return worst
  ```

- [ ] **Step 6: Add the per-layer need helper and use it in `_pairs`**

  ```python
  def _layer_oz(layer, copper_mm: dict, fallback_oz: float) -> float:
      mm_thickness = copper_mm.get(layer) if layer is not None else None
      return mm_thickness / _MM_PER_OZ if mm_thickness is not None else fallback_oz


  def _layer_k(layer) -> float:
      from .values import CopperLayer
      return _IPC_K_OUTER if layer is None or layer in (CopperLayer.F, CopperLayer.B) else _IPC_K_INNER


  def _need_mm(amps: float, rise_c: float, copper_oz: float, copper_mm: dict, layers) -> float:
      layer = next(iter(layers), None)
      return ipc2221_width_mm(amps, rise_c, _layer_oz(layer, copper_mm, copper_oz), _layer_k(layer))
  ```

  In `_pairs`, replace the single `need = ipc2221_width_mm(amps, rise_c,
  copper_oz)` computed before the neck is known with a per-branch
  computation after it, and update the unpacking of `_neck`'s and
  `_fill_on`'s new return shapes:

  ```python
      width, w, to, start, zoned, end_i, fill, narrows = max(reach, key=lambda r: r[0])   # the widest-joined end
      if math.isinf(width):
          unmeasured.append((start, to, "joined only through pads and vias" if not zoned
                             else "joined only through pads, vias and a zone fill where their copper meets"))
          continue
      amps = carriers[a] if b is None else min(carriers[a], carriers[b])
      if narrows:
          need = _need_mm(amps, rise_c, copper_oz, geometry.copper_mm, fill[3])
          judged.append((width, need, amps, start, to, (fill[0], fill[2], True), fill[1], None))
          continue
      point, length, in_pour, neck_layers = _neck(nodes, best, end_i, w)
      need = _need_mm(amps, rise_c, copper_oz, geometry.copper_mm, neck_layers)
      judged.append((w, need, amps, start, to, None if fill is None else (fill[0], fill[2], False), point,
                     None if in_pour else length))
  ```

  Note `reach.append(...)`'s `fill` element (built earlier in `_pairs`
  from `_fill_on(...)`) is now `None` or a 4-tuple; its existing use
  (`fill[0] if narrows else w`, `fill is not None`) is unaffected since it
  only reads indices 0-2 before this step and index 3 is new.

- [ ] **Step 7: Run the full test file plus the two existing current-path files it must not break**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_current_path_inner_layer.py tests/test_current_path_neck.py \
    tests/test_current_path_pairs.py tests/test_current_path_zone_width.py tests/test_checks.py
  ```

- [ ] **Step 8: `kwargs_from` stops sourcing `copper_oz` from settings (prepares Task 3)**

  Leave `kwargs_from` as-is for this task (it still reads
  `settings.check_copper_oz`, which still exists until Task 3 retires it);
  Task 3's Step 4 removes that line. Do not change it here - keeps this
  task's commit buildable on its own.

- [ ] **Step 9: Commit**

  ```bash
  git add src/placemat/checks.py tests/test_current_path_inner_layer.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  The current-path check judges each layer by its own stackup weight

  IPC-2221's inner constant on an inner layer, outer on F.Cu/B.Cu, and the
  layer's own copper weight from the board's stackup when it has one.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 3: Retire the three placemat.toml board-fact keys; add `score.via_shorten` and `[facts] confirmed`

**Files:**
- Modify: `src/placemat/settings.py`
- Modify: `src/placemat/checks.py` (`kwargs_from` drops `copper_oz`)
- Modify: `src/placemat/cli.py` (`check` command drops `--copper-oz`)
- Test: `tests/test_settings.py`, `tests/test_settings_wiring.py`

**Interfaces:**
- Produces: `Settings.score_via_shorten: float = 5.0`;
  `Settings.facts_confirmed: str = ""`; `Settings.keys()` excludes
  `facts_confirmed` from the digest the same way it excludes `sources`.
  `[check] copper_oz`, `[route] layers`, `[route] diff_pairs` raise
  `SettingsError` naming the .zen field that replaces each.

- [ ] **Step 1: Write the failing tests for the three refusals and the two additions**

  Add to `tests/test_settings.py` (follow the file's existing
  `_toml(tmp_path / "placemat.toml", "...")` + `pytest.raises(S.SettingsError)`
  convention seen at the top of the file):

  ```python
  def test_check_copper_oz_is_retired_naming_the_stackup(tmp_path):
      _toml(tmp_path / "placemat.toml", "[check]\ncopper_oz = 1.0\n")
      with pytest.raises(S.SettingsError) as e:
          S.load(tmp_path)
      assert "check.copper_oz" in str(e.value) and "stackup" in str(e.value)


  def test_route_layers_is_retired_naming_layer_roles(tmp_path):
      _toml(tmp_path / "placemat.toml", '[route]\nlayers = ["F.Cu", "B.Cu"]\n')
      with pytest.raises(S.SettingsError) as e:
          S.load(tmp_path)
      assert "route.layers" in str(e.value) and "role" in str(e.value)


  def test_route_diff_pairs_is_retired_naming_net_classes(tmp_path):
      _toml(tmp_path / "placemat.toml", '[route]\ndiff_pairs = ["*"]\n')
      with pytest.raises(S.SettingsError) as e:
          S.load(tmp_path)
      assert "route.diff_pairs" in str(e.value) and "net class" in str(e.value)


  def test_score_via_shorten_has_a_default_and_is_settable(tmp_path):
      assert S.Settings().score_via_shorten == 5.0
      _toml(tmp_path / "placemat.toml", "[score]\nvia_shorten = 8.0\n")
      assert S.load(tmp_path).score_via_shorten == 8.0


  def test_facts_confirmed_does_not_feed_the_digest(tmp_path):
      plain = S.Settings()
      _toml(tmp_path / "placemat.toml", '[facts]\nconfirmed = "abc123"\n')
      confirmed = S.load(tmp_path)
      assert confirmed.facts_confirmed == "abc123"
      assert confirmed.json() == plain.json()
      assert "facts_confirmed" not in S.Settings.keys()
  ```

- [ ] **Step 2: Run it, confirm all five fail**

- [ ] **Step 3: Retire the three keys and add the two new ones in `Settings`**

  Remove `check_copper_oz: float = 1.0` from the dataclass body and from
  `_ABOVE_ZERO`'s tuple. Remove `route_layers: tuple | None = None` and
  `route_diff_pairs: tuple = ("*",)` from the dataclass body (also remove
  the `if name == "route_diff_pairs": ... explicit_pairs(value) ...`
  validation block in `_validate`, now dead).

  Add, in the `[score]` section group:

  ```python
      score_via_shorten: float = 5.0      # a carried drop shortened to the plane's nearest layer instead of dropped: between move and drop
  ```

  and add `"score_via_shorten"` to `_AT_LEAST_ZERO`.

  Add a new `[facts]` field, at the end of the dataclass body just before
  `sources`:

  ```python
      # [facts] - placemat's own record, not a board fact: never part of a run's id
      facts_confirmed: str = ""           # a digest of the facts last confirmed with `placemat facts --confirm`
  ```

  Update `Settings.keys()` to exclude it from the digest the same way
  `sources` is excluded:

  ```python
      @staticmethod
      def keys() -> tuple:
          return tuple(f.name for f in fields(Settings) if f.name not in ("sources", "facts_confirmed"))
  ```

- [ ] **Step 4: Add the retirement messages to `_flatten`**

  In `src/placemat/settings.py`, add a module-level table above `_flatten`:

  ```python
  # Keys retired because they named a board fact: placemat.toml holds no
  # board fact, and a project that still sets one is told where it moved.
  _RETIRED = {
      "check_copper_oz": "the board's own copper weight, read per layer from its stackup",
      "route_layers": "each layer's role in the board's stackup (signal/mixed routes, F.Cu and B.Cu always)",
      "route_diff_pairs": "a net class's diff_pair_width/diff_pair_gap in the board's .zen",
  }
  ```

  In `_flatten`, before the `if name not in known:` check that raises
  "is not a setting placemat has", add:

  ```python
          name = join_key(section, key)
          if name in _RETIRED:
              raise SettingsError("%s: %s.%s is retired; it named a board fact, now read from %s"
                                  % (path, section, key, _RETIRED[name]))
          if name not in known:
  ```

  (adjust variable names to fit around the existing `full`/`name`
  bindings already in `_flatten` - read the function body first.)

- [ ] **Step 5: `checks.kwargs_from` drops `copper_oz`**

  In `src/placemat/checks.py`:

  ```python
  def kwargs_from(settings) -> dict:
      """The arguments `run_checks` takes, from the resolved settings. One home,
      so `placemat check` and `placemat run` judge a board by the same numbers."""
      return {"ambient_c": settings.check_ambient_c, "keep_out_mm": settings.check_keep_out_mm,
              "rise_c": settings.check_rise_c, "limits": dict(settings.check_limits),
              "zone_step": settings.check_zone_step}
  ```

- [ ] **Step 6: `cli.py`'s `check` command drops `--copper-oz`**

  Remove the `ck.add_argument("--copper-oz", ...)` line and its
  `("copper_oz", "check_copper_oz")` pair from `overrides_from`'s tuple.

- [ ] **Step 7: Run the settings tests, checks tests and cli smoke test**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_settings.py tests/test_settings_wiring.py tests/test_checks.py tests/test_checks_wiring.py \
    tests/test_cli_output.py
  ```

- [ ] **Step 8: Commit**

  ```bash
  git add src/placemat/settings.py src/placemat/checks.py src/placemat/cli.py tests/test_settings.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  placemat.toml refuses the three keys that named a board fact

  check.copper_oz, route.layers and route.diff_pairs are retired, each
  refusal naming the .zen field that replaces it; score.via_shorten and
  facts.confirmed are added, the latter excluded from a run's digest.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 4: Verify the Default net class on a real board (grounding for Task 5)

This is a verification step, not a code change - the finding feeds Task
5's design directly.

- [ ] **Step 1: Confirm on the real generated board that Default reports non-zero diff pair values**

  Already done during planning (`layout.kicad_pro`'s `net_settings.classes`
  for "Default": `diff_pair_gap: 0.2, diff_pair_width: 0.2`), so
  `NetClass.diff_pair_width is not None` is NOT sufficient to say "this
  class makes pairs" - the class's *name* must be checked and "Default"
  excluded outright, exactly as the spec says. Re-run only if in doubt:

  ```bash
  python3 -c "
  import json
  d = json.load(open('/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/fairprof/electronics/boards/core/.placemat/generated/Core/layout.kicad_pro'))
  print([c for c in d['net_settings']['classes'] if c['name'] == 'Default'])
  "
  ```

- [ ] **Step 2: No commit for this task.**

---

### Task 5: Differential pairs from net classes, not `route.diff_pairs`

**Files:**
- Modify: `src/placemat/pairs.py`
- Modify: `src/placemat/score.py` (~line 126), `src/placemat/occupancy.py` (~line 905),
  `src/placemat/runner.py` (~line 510)
- Test: `tests/test_pairs.py`, `tests/test_explicit_pairs.py`, `tests/test_current_path_pairs.py` (must not regress)

**Interfaces:**
- Consumes: `BoardGeometry.netclasses: dict[str, NetClass]` (already
  exists; `NetClass.diff_pair_width`/`diff_pair_gap`).
- Produces: `pairs.class_pairs(netclasses: dict) -> tuple[str, ...]` - the
  same shape `route.diff_pairs` used to be (literal net names for a
  same-style suffix pairing within one class, `"NET_A/NET_B"` for a
  class of exactly two nets), so every existing consumer of
  `pairs_of(nets, patterns)` keeps its signature; only the source of
  `patterns` changes at each call site.

- [ ] **Step 1: Write the failing tests for `class_pairs`**

  Add to `tests/test_pairs.py` (check its existing imports/helpers first -
  it likely already builds `NetClass` instances by hand; follow that
  convention):

  ```python
  def test_a_two_net_class_pairs_outright_whatever_its_names():
      from placemat.board_geometry import NetClass
      from placemat.pairs import class_pairs
      classes = {"CLK_MAIN": NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1),
                 "CLK_RETURN": NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1)}
      assert class_pairs(classes) == ("CLK_MAIN/CLK_RETURN",)


  def test_a_four_net_class_pairs_by_pair_key():
      from placemat.board_geometry import NetClass
      from placemat.pairs import class_pairs, pairs_of
      cls = NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1)
      classes = {n: cls for n in ("USB_D_P", "USB_D_N", "SPARE_P", "SPARE_N")}
      patterns = class_pairs(classes)
      assert set(patterns) == {"USB_D_P", "USB_D_N", "SPARE_P", "SPARE_N"}
      assert pairs_of(set(classes), patterns) == {
          "USB_D_P": "USB_D_N", "USB_D_N": "USB_D_P", "SPARE_P": "SPARE_N", "SPARE_N": "SPARE_P"}


  def test_the_default_class_never_makes_pairs():
      from placemat.board_geometry import NetClass
      from placemat.pairs import class_pairs
      classes = {"A": NetClass("Default", 0.16, 0.16, 0.45, 0.2, 0.2, 0.2),
                 "B": NetClass("Default", 0.16, 0.16, 0.45, 0.2, 0.2, 0.2)}
      assert class_pairs(classes) == ()


  def test_a_class_with_no_diff_pair_values_makes_no_pairs():
      from placemat.board_geometry import NetClass
      from placemat.pairs import class_pairs
      classes = {"A": NetClass("50Ohm SE", 0.14, 0.2, 0.45, 0.2), "B": NetClass("50Ohm SE", 0.14, 0.2, 0.45, 0.2)}
      assert class_pairs(classes) == ()


  def test_no_pair_class_at_all_makes_no_pairs():
      from placemat.pairs import class_pairs
      assert class_pairs({}) == ()
  ```

- [ ] **Step 2: Run it, confirm ImportError (no `class_pairs`)**

- [ ] **Step 3: Implement `class_pairs` in `src/placemat/pairs.py`**

  Add after `pairs_of`:

  ```python
  def class_pairs(netclasses: dict) -> tuple:
      """The pair-bearing net classes' nets, in the shape a route.diff_pairs
      list used to take: literal net names for a class of more than two
      (paired within the class by pair_key, the router's suffix
      convention), "NET_A/NET_B" for a class of exactly two (one pair,
      whatever the two are called). The Default class never makes pairs -
      KiCad gives it its own non-zero diff_pair_width/diff_pair_gap even
      when nobody declared a pair class, so its name is excluded outright,
      not just its diff pair values checked."""
      by_class: dict = {}
      for net, nc in netclasses.items():
          if nc.name == "Default" or nc.diff_pair_width is None or nc.diff_pair_gap is None:
              continue
          by_class.setdefault(nc.name, []).append(net)
      out = []
      for name in sorted(by_class):
          nets = sorted(by_class[name])
          if len(nets) == 2:
              out.append("%s/%s" % (nets[0], nets[1]))
          else:
              out += nets
      return tuple(out)
  ```

- [ ] **Step 4: Run the pairs tests, confirm they pass**

- [ ] **Step 5: Swap the three placement/scoring call sites**

  In `src/placemat/score.py` (~line 126-128):

  ```python
      from .pairs import class_pairs, pairs_of
      partners = {n: m for n, m in pairs_of(by_net, class_pairs(board.geometry.netclasses)).items()
                  if n not in quiet and m not in quiet}
  ```

  In `src/placemat/occupancy.py` (~line 905-912), inside `Occupancy.ratsnest`:

  ```python
              from .pairs import class_pairs, pairs_of
              from .ratsnest import Ratsnest
              weights = {n: self.settings.score_crossing_plane for n in self.quiet_nets}
              nets = {s.net for g in self.items.values() for s in g.shapes if s.net}
              partners = {n: m for n, m in pairs_of(nets, class_pairs(self.geometry.netclasses)).items()
                          if n not in self.quiet_nets and m not in self.quiet_nets}
  ```

  In `src/placemat/runner.py` (~line 508-510):

  ```python
              quiet = set(board._plane_nets()) | set(board._free_nets)
              from .pairs import class_pairs
              aw = airwires_from_drc(json.loads((run_dir / "drc.json").read_text()), quiet,
                                     class_pairs(board.geometry.netclasses))
  ```

  Leave `cli.py`'s `cmd_drc` call to `airwires_from_drc(data)` (default
  `pair_patterns=("*",)`) untouched: it is not in the spec's list of
  `pair_key`/pairing callers to change and has no board geometry in scope
  at that point.

- [ ] **Step 6: Run the wider affected test set**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_pairs.py tests/test_explicit_pairs.py tests/test_current_path_pairs.py \
    tests/test_crossing_cost.py tests/test_congestion.py
  ```

  (Grep first for any other test that passes `route_diff_pairs=` to
  `Settings(...)` expecting it to drive pairing in score/occupancy/runner
  paths - `grep -rn "route_diff_pairs" tests/` - and update any such test
  to build its `BoardGeometry` with the right net classes instead, since
  the setting is retired as of Task 3.)

- [ ] **Step 7: Commit**

  ```bash
  git add src/placemat/pairs.py src/placemat/score.py src/placemat/occupancy.py src/placemat/runner.py tests/test_pairs.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  Differential pairs come from the board's net classes, not a setting

  A class of two nets pairs outright; more than two pair by the router's
  own suffix convention (pairs.pair_key) within the class. The Default
  class never makes pairs, since KiCad gives it its own diff pair values.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 6: Route layers default from each layer's role

**Files:**
- Modify: `src/placemat/kicad/route.py`
- Test: `tests/test_route_plane_layers.py`

**Interfaces:**
- Consumes: `placemat.kicad.read.layer_types(board)` (Task 1's rename).
- Produces: `resolved_layers(explicit, all_layers, layer_types: dict) ->
  (layers: list, dropped: dict[str, str])` - **signature change** from
  `(explicit, all_layers, zones, board_area, share)`; `dropped` now maps
  a left-out layer name to its role ("power", "jumper"), not a net name.
  `plane_layers`/`_plane_zones` (coverage-based, now unused) are removed.

- [ ] **Step 1: Rewrite `tests/test_route_plane_layers.py`'s `resolved_layers` tests (its `plane_layers` tests for pour-guarding are untouched by this task and stay as they are elsewhere - see Step 6)**

  Replace the file's last two tests
  (`test_an_explicit_list_overrides_the_plane_search`,
  `test_with_nothing_explicit_the_planes_own_layers_drop_out`) with:

  ```python
  def test_an_explicit_list_overrides_the_role_based_default():
      layer_types = {"In1.Cu": "power"}
      layers, dropped = resolved_layers(["F.Cu", "In1.Cu", "B.Cu"], ["F.Cu", "In1.Cu", "B.Cu"], layer_types)
      assert layers == ["F.Cu", "In1.Cu", "B.Cu"] and dropped == {}


  def test_with_nothing_explicit_only_signal_and_mixed_layers_route():
      """F signal, In1 ground (power), In2 signal, In3 power, In4 ground
      (power), B signal: routes on F, In2 and B."""
      all_layers = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]
      layer_types = {"F.Cu": "signal", "In1.Cu": "power", "In2.Cu": "signal",
                     "In3.Cu": "power", "In4.Cu": "power", "B.Cu": "signal"}
      layers, dropped = resolved_layers(None, all_layers, layer_types)
      assert layers == ["F.Cu", "In2.Cu", "B.Cu"]
      assert dropped == {"In1.Cu": "power", "In3.Cu": "power", "In4.Cu": "power"}


  def test_a_mixed_layer_routes_too():
      all_layers = ["F.Cu", "In1.Cu", "B.Cu"]
      layer_types = {"F.Cu": "signal", "In1.Cu": "mixed", "B.Cu": "signal"}
      layers, dropped = resolved_layers(None, all_layers, layer_types)
      assert layers == ["F.Cu", "In1.Cu", "B.Cu"] and dropped == {}


  def test_f_and_b_route_whatever_their_role():
      all_layers = ["F.Cu", "In1.Cu", "B.Cu"]
      layer_types = {"F.Cu": "jumper", "In1.Cu": "power", "B.Cu": "jumper"}
      layers, dropped = resolved_layers(None, all_layers, layer_types)
      assert layers == ["F.Cu", "B.Cu"] and dropped == {"In1.Cu": "power"}


  def test_a_layer_with_no_declared_role_defaults_to_signal():
      all_layers = ["F.Cu", "In1.Cu", "B.Cu"]
      layers, dropped = resolved_layers(None, all_layers, {})
      assert layers == all_layers and dropped == {}
  ```

  Update the file's import line to drop `plane_layers` (it is removed in
  Step 6, still tested by its own first five tests until then).

- [ ] **Step 2: Run it, confirm the rewritten tests fail (old signature)**

- [ ] **Step 3: Rewrite `resolved_layers`**

  In `src/placemat/kicad/route.py`, replace `resolved_layers`:

  ```python
  def resolved_layers(explicit, all_layers, layer_types: dict) -> tuple:
      """The layers to route on, and what was left out of the default and
      why, as (layers, {layer: role}). An explicit list (an argument or a
      one-run --layers) is used as given. Left to itself: every layer
      whose role is signal or mixed, F.Cu and B.Cu always among them - a
      real board's floor of two layers, so this never routes on fewer than
      that either. A layer with no declared role reads as signal (the
      board's own stackup, or its stdlib default, gives every layer one)."""
      if explicit:
          return list(explicit), {}
      dropped = {l: layer_types.get(l, "signal") for l in all_layers
                if l not in ("F.Cu", "B.Cu") and layer_types.get(l, "signal") not in ("signal", "mixed")}
      kept = [l for l in all_layers if l not in dropped]
      return kept, dropped
  ```

- [ ] **Step 4: Run the rewritten tests, confirm they pass**

- [ ] **Step 5: Update `plane_note` and `route_board`'s call site**

  `plane_note` currently groups `dropped` by net name and says "the %s
  plane fills it/them"; rewrite it to group by role:

  ```python
  def plane_note(dropped: dict) -> str:
      """The route step's line for what a layer's role took off the
      default layer list, and how to override it. `dropped` groups by
      role, so several layers of one role read as one clause."""
      if not dropped:
          return ""
      groups: dict = {}
      for layer in sorted(dropped):
          groups.setdefault(dropped[layer], []).append(layer)
      parts = ["%s left out, role %s" % (", ".join(layers), role) for role, layers in sorted(groups.items())]
      return "route layers: " + "; ".join(parts) + "; [route] layers to override"
  ```

  In `route_board`, replace the `zones`/`board_area`/`_plane_zones` branch:

  ```python
      if layers:
          all_layers, roles = [], {}
      else:
          all_layers = _copper_layers(str(pcb_in))
          from .read import layer_types as _layer_types_of
          board_roles = _layer_types_of(_loaded_board(str(pcb_in)))
          roles = {l.value: r for l, r in board_roles.items()}
      layers, plane_dropped = resolved_layers(layers, all_layers, roles)
  ```

  Since there is no existing "load a board and return it" one-liner
  reused elsewhere in `route.py` beyond inline `with quiet_stderr():
  board = pcbnew.LoadBoard(...)` blocks, write it inline instead of
  inventing a `_loaded_board` helper (keep the diff small):

  ```python
      if layers:
          all_layers, roles = [], {}
      else:
          all_layers = _copper_layers(str(pcb_in))
          from .quiet import import_pcbnew, quiet_stderr
          from .read import layer_types as _board_layer_types
          pcbnew = import_pcbnew()
          with quiet_stderr():
              roled_board = pcbnew.LoadBoard(str(pcb_in))
          roles = {l.value: r for l, r in _board_layer_types(roled_board).items()}
      layers, plane_dropped = resolved_layers(layers, all_layers, roles)
  ```

  Remove the now-unused `cfg.route_plane_share` argument from this call
  (it stops being read for this purpose - `guard_partial_pours`'s own
  `cfg.route_plane_share` argument, passed separately later in the same
  function, is untouched and keeps working for pour-guarding).

- [ ] **Step 6: Remove the now-dead `plane_layers`/`_plane_zones` and their tests**

  Grep confirms `plane_layers`/`_plane_zones` have no other callers after
  Step 5 (`grep -rn "plane_layers\|_plane_zones" src/`). Delete both
  functions from `route.py`. Delete `test_route_plane_layers.py`'s first
  five tests (the ones exercising `plane_layers` directly:
  `test_an_inner_plane_at_95_percent_is_dropped` through
  `test_several_qualifying_layers_come_back_sorted`), keeping only the
  `resolved_layers` tests from Step 1. Update the file's docstring and
  import line accordingly.

- [ ] **Step 7: Run the route tests**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_route_plane_layers.py tests/test_route_settings.py
  ```

  (`route_board` itself is not run here - never run the router in this
  worktree per the global constraints; this only exercises the pure
  functions.)

- [ ] **Step 8: Commit**

  ```bash
  git add src/placemat/kicad/route.py tests/test_route_plane_layers.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  Route layers default to each layer's declared role

  Signal and mixed layers route, plus F.Cu and B.Cu always; a board whose
  plane happens to fill an inner layer no longer decides this by itself.
  plane_layers/_plane_zones (the old coverage-based default) are unused.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 7: `route_pairs` sourced from net classes, not `route.diff_pairs`

**Files:**
- Modify: `src/placemat/kicad/route.py` (`route_board`'s call to `route_pairs`)
- Test: `tests/test_route_pairs.py`

**Interfaces:**
- Consumes: `pairs.class_pairs` (Task 5).

- [ ] **Step 1: Grep `tests/test_route_pairs.py` for how it currently drives `route_pairs`/`route_board` and whether it passes `cfg.route_diff_pairs` directly or through a `Settings(...)`**

  `route_pairs(rpy, router_dir_path, pcb_in, work, patterns, layers, cfg,
  iterations, probe, timeout, env)` already takes `patterns` as a plain
  argument, not `cfg.route_diff_pairs` - only its ONE caller
  (`route_board`) currently sources `patterns` from the retired setting.
  If the test file calls `route_pairs` directly with an explicit
  `patterns` argument, it is unaffected by this task; if it drives it
  through `route_board`/`Settings(route_diff_pairs=...)`, update it to
  build a `NetClass`-bearing board (or monkeypatch `class_pairs`) instead,
  matching Task 5's new source. Read the file before writing new
  assertions.

- [ ] **Step 2: Update `route_board`'s call site**

  In `src/placemat/kicad/route.py`'s `route_board`, replace:

  ```python
      board, pairs = route_pairs(rpy, router_dir_path, pcb_in, work, tuple(cfg.route_diff_pairs), layers, cfg,
                                 iterations, probe, timeout, env)
  ```

  with a call that reads the pcb's own net classes:

  ```python
      from ..pairs import class_pairs
      from .read import read_board as _read_board_for_pairs
      board_netclasses = _read_board_for_pairs(pcb_in).netclasses
      board, pairs = route_pairs(rpy, router_dir_path, pcb_in, work, class_pairs(board_netclasses), layers, cfg,
                                 iterations, probe, timeout, env)
  ```

  (`read_board` is already imported elsewhere in the codebase as the
  standard way to get `BoardGeometry.netclasses` off a `.kicad_pcb`; name
  the import `_read_board_for_pairs` only if `read_board` is not already
  imported in this module under its own name - grep the top of the file
  first and reuse an existing import if there is one.)

- [ ] **Step 3: Run the route pairs tests**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_route_pairs.py
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add src/placemat/kicad/route.py tests/test_route_pairs.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  The pair route step reads which nets pair from the board's net classes
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 8: fab-profile.json's via types take yes/no/if-needed; fab minimums

**Files:**
- Modify: `src/placemat/project.py`
- Test: `tests/test_project.py`, `tests/test_via_types_allowed.py` (must not regress)

**Interfaces:**
- Produces: `FabProfile.via_types: frozenset` (unchanged meaning: "yes"
  types); `FabProfile.via_needed: frozenset` (new: "if-needed" types);
  `FabProfile.min: dict` (new: fab minimums, keyed `track_mm`,
  `clearance_mm`, `drill_mm`, `annular_mm`, `via_size_mm`);
  `fab_minimum_findings(geometry, min_rules: dict) -> list[str]`.

- [ ] **Step 1: Write the failing tests for via tiers and digest parity**

  Add to `tests/test_project.py`:

  ```python
  def test_via_types_read_yes_no_if_needed(tmp_path):
      import json
      from placemat.project import fab_profile
      (tmp_path / "fab-profile.json").write_text(json.dumps(
          {"via": {"micro": "no", "blind": "if-needed", "buried": "yes"}}))
      fab = fab_profile(tmp_path)
      assert fab.via_types == frozenset({"buried"})
      assert fab.via_needed == frozenset({"blind"})


  def test_the_057_allow_keys_still_read_as_yes_and_no(tmp_path):
      import json
      from placemat.project import fab_profile
      (tmp_path / "fab-profile.json").write_text(json.dumps(
          {"via": {"allow_micro": True, "allow_blind": False}}))
      fab = fab_profile(tmp_path)
      assert fab.via_types == frozenset({"micro"}) and fab.via_needed == frozenset()


  def test_an_unnamed_type_is_no(tmp_path):
      import json
      from placemat.project import fab_profile
      (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {}}))
      fab = fab_profile(tmp_path)
      assert fab.via_types == frozenset() and fab.via_needed == frozenset()


  def test_the_digest_stays_as_today_for_a_profile_with_no_new_keys(tmp_path):
      import json
      from placemat.project import fab_profile
      (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {"allow_blind": True}}))
      fab = fab_profile(tmp_path)
      assert "needed" not in fab.json() and "min" not in fab.json()
      other = tmp_path / "plain"
      other.mkdir()
      (other / "fab-profile.json").write_text(json.dumps({"via": {"blind": "if-needed"}}))
      fab2 = fab_profile(other)
      assert fab2.via_needed == frozenset({"blind"})
      assert "needed_vias" in fab2.json() and json.loads(fab2.json())["needed_vias"] == ["blind"]


  def test_min_is_read_and_digested_when_the_fab_names_it(tmp_path):
      import json
      from placemat.project import fab_profile
      (tmp_path / "fab-profile.json").write_text(json.dumps({"min": {"track_mm": 0.09, "clearance_mm": 0.09}}))
      fab = fab_profile(tmp_path)
      assert fab.min == {"track_mm": 0.09, "clearance_mm": 0.09}
      assert json.loads(fab.json())["min"] == {"track_mm": 0.09, "clearance_mm": 0.09}


  def test_a_net_class_below_the_fab_minimum_is_a_finding():
      from placemat.board_geometry import NetClass
      from placemat.project import fab_minimum_findings
      geometry_netclasses = {"A": NetClass("Fast", 0.08, 0.2, 0.45, 0.2)}
      out = fab_minimum_findings(SimpleGeometry(geometry_netclasses), {"track_mm": 0.09})
      assert len(out) == 1 and "Fast" in out[0] and "track width" in out[0] and "0.090" in out[0]


  def test_a_net_class_at_or_above_the_minimum_is_not_a_finding():
      from placemat.board_geometry import NetClass
      from placemat.project import fab_minimum_findings
      geometry_netclasses = {"A": NetClass("Fast", 0.09, 0.2, 0.45, 0.2)}
      assert fab_minimum_findings(SimpleGeometry(geometry_netclasses), {"track_mm": 0.09}) == []
  ```

  Add a tiny local helper at the top of the test file (`fab_minimum_findings`
  only reads `.netclasses`, so a bare namespace is enough - do not build a
  full synthetic `BoardGeometry` for this):

  ```python
  class SimpleGeometry:
      def __init__(self, netclasses):
          self.netclasses = netclasses
  ```

- [ ] **Step 2: Run it, confirm failures (no `via_needed`/`min`/`fab_minimum_findings`)**

- [ ] **Step 3: Implement the via tier reading and `min` in `FabProfile`/`fab_profile`**

  In `src/placemat/project.py`, extend `FabProfile`:

  ```python
  @dataclass(frozen=True)
  class FabProfile:
      via_drill: float = 0.3
      via_size: float = 0.6
      courtyard_excess: float = 0.10
      track_widths: tuple = tuple(round(0.15 + 0.05 * i, 2) for i in range(18))
      path: Path | None = None
      component_spacing: float = 0.2
      via_types: frozenset = frozenset()      # "yes": placemat draws it where a script asks
      via_needed: frozenset = frozenset()     # "if-needed": preferred off; give way may still use it
      min: dict = field(default_factory=dict)  # fab minimums: track_mm, clearance_mm, drill_mm, annular_mm, via_size_mm

      def json(self) -> str:
          import json as _json
          doc = {"via_drill": self.via_drill, "via_size": self.via_size,
                 "courtyard_excess": self.courtyard_excess, "track_widths": list(self.track_widths),
                 "component_spacing": self.component_spacing}
          if self.via_types:
              doc["allow_vias"] = sorted(self.via_types)
          if self.via_needed:
              doc["needed_vias"] = sorted(self.via_needed)
          if self.min:
              doc["min"] = dict(sorted(self.min.items()))
          return _json.dumps(doc, sort_keys=True)
  ```

  Add a `dataclasses.field` import if not already present (`field` is
  used elsewhere - check the existing `from dataclasses import dataclass`
  line and extend it to `from dataclasses import dataclass, field`).

  Add the tier-reading helper and wire it into `fab_profile`:

  ```python
  _VIA_KINDS = ("micro", "blind", "buried")


  def _via_tier(via: dict, kind: str) -> str:
      """"yes"/"no"/"if-needed" for one via kind: the new string form when
      given, else the 0.57 allow_<kind> boolean (true -> yes, false or
      absent -> no), else "no"."""
      value = via.get(kind)
      if value in ("yes", "no", "if-needed"):
          return value
      return "yes" if via.get("allow_" + kind) else "no"
  ```

  In `fab_profile(start)`, after `via = data.get("via", {})`, replace the
  `types = frozenset(...)` line with:

  ```python
          tiers = {kind: _via_tier(via, kind) for kind in _VIA_KINDS}
          types = frozenset(k for k, t in tiers.items() if t == "yes")
          needed = frozenset(k for k, t in tiers.items() if t == "if-needed")
          min_rules = {k: float(v) for k, v in (data.get("min") or {}).items()}
  ```

  and extend the `return FabProfile(...)` call with `via_needed=needed,
  min=min_rules` (keep every existing positional argument in place).

- [ ] **Step 4: Implement `fab_minimum_findings`**

  Add near the bottom of `src/placemat/project.py`:

  ```python
  _MIN_CHECKS = (
      ("track_mm", lambda nc: nc.track_width, "track width"),
      ("clearance_mm", lambda nc: nc.clearance, "clearance"),
      ("drill_mm", lambda nc: nc.via_drill, "via drill"),
      ("via_size_mm", lambda nc: nc.via_diameter, "via diameter"),
      ("annular_mm", lambda nc: (nc.via_diameter - nc.via_drill) / 2.0, "via annular ring"),
  )


  def fab_minimum_findings(geometry, min_rules: dict) -> list:
      """A sentence for each of the board's net classes that falls below
      one of the fab's minimums (fab-profile.json's min section), naming
      the class, the rule and both values. Empty when min_rules says
      nothing, or every class clears it."""
      out = []
      classes = {nc.name: nc for nc in geometry.netclasses.values()}
      for key, get, label in _MIN_CHECKS:
          floor = min_rules.get(key)
          if floor is None:
              continue
          for name in sorted(classes):
              value = get(classes[name])
              if value < floor:
                  out.append("net class %s: %s %.3f mm is below the fab's minimum %.3f mm (fab-profile.json min.%s)"
                              % (name, label, value, floor, key))
      return out
  ```

- [ ] **Step 5: Run the project tests and the existing via-types test (must be unaffected)**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_project.py tests/test_via_types_allowed.py
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add src/placemat/project.py tests/test_project.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  fab-profile.json's via types take yes/no/if-needed, and a min section

  The 0.57 allow_* keys still read as before; a profile naming neither
  digests exactly as today. fab_minimum_findings judges the board's net
  classes against the fab's minimums.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 9: `Board` carries the if-needed via tier and fab minimums; if-needed is refused like no at declare time

**Files:**
- Modify: `src/placemat/layout.py`
- Test: `tests/test_via_types_allowed.py`, `tests/test_finding_kinds.py` (kind added in Task 10, do not break it here)

**Interfaces:**
- Produces: `Board.__init__` gains `fab_vias_needed: frozenset = frozenset()`
  and `fab_min: dict | None = None` keyword parameters, stored as
  `self.fab_vias_needed`/`self.fab_min`; `Board.resolve()` appends a
  `Finding("fab", ...)` per `fab_minimum_findings(self.geometry, self.fab_min)`.

- [ ] **Step 1: Grep for `_allow_via_type`'s call sites and `Board.__init__`'s body to place the new parameters correctly**

  ```bash
  grep -n "_allow_via_type(\|def __init__" src/placemat/layout.py | head -20
  ```

- [ ] **Step 2: Write the failing test for if-needed refusal**

  Add to `tests/test_via_types_allowed.py`:

  ```python
  def test_an_if_needed_via_is_refused_like_a_no_when_asked_for_directly():
      b = _board(fab_vias_needed=frozenset({"blind"}))
      with pytest.raises(ValueError, match="preferred off"):
          b.via(Net("GND"), Location(10, 10), layers=(B, IN2))
  ```

  (`_board` in this file already builds a `Board` with `**kw` passed
  through - confirm this by reading the file's `_board` helper before
  writing the test; it is defined near the top.)

- [ ] **Step 3: Run it, confirm TypeError (unexpected keyword `fab_vias_needed`)**

- [ ] **Step 4: Add the two new `Board` parameters and wire the refusal**

  In `Board.__init__`'s signature, add `fab_vias_needed=None, fab_min=None`
  after the existing `fab_vias=None, fab_source: str = ""`:

  ```python
      def __init__(self, geometry: BoardGeometry, edge_margin: float | None = None, clearance: float | None = None,
                   via_drill: float = 0.3, via_size: float = 0.6, keep_going: bool = False,
                   courtyard_excess: float = 0.1, settings: Settings | None = None,
                   component_spacing: float | None = None, fab_vias=None, fab_source: str = "",
                   fab_vias_needed=None, fab_min=None):
  ```

  Add, beside the existing `self.fab_vias = frozenset(fab_vias) if
  fab_vias is not None else type(self).fab_vias` line:

  ```python
          self.fab_vias_needed = frozenset(fab_vias_needed) if fab_vias_needed is not None else frozenset()
          self.fab_min = dict(fab_min or {})
  ```

  In `_allow_via_type` (around line 3414), change the refusal to
  distinguish "no" from "if-needed":

  ```python
      def _allow_via_type(self, name: str, span: tuple) -> None:
          """Refuse a via type the fab profile does not allow outright, or
          prefers off: a micro, blind or buried via costs more, and a
          script may not draw one unless the profile says "yes" for a fab
          that makes it and the cost is accepted. "if-needed" is refused
          here too - a script may not ask for it directly - but give way
          may still use it (giveway.py's shorten way)."""
          kind = _via_kind(span)
          if kind in self.fab_vias:
              return
          if kind in self.fab_vias_needed:
              raise ValueError(
                  "%s: a %s via (%s) is preferred off by the fab profile%s: via.%s is \"if-needed\", so "
                  "a script may not draw one; give way may still use it where an item cannot otherwise place"
                  % (name, kind, _span_text(span), " (%s)" % self.fab_source if self.fab_source else "", kind))
          raise ValueError(
              "%s: a %s via (%s) is not allowed by the fab profile%s; they cost more, so a board keeps to "
              "through vias unless fab-profile.json says \"via\": {\"%s\": \"yes\"} for a fab that makes "
              "them" % (name, kind, _span_text(span), " (%s)" % self.fab_source if self.fab_source else "",
                        kind))
  ```

- [ ] **Step 5: Run the test, confirm it passes; run the whole file to confirm no regressions**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_via_types_allowed.py
  ```

- [ ] **Step 6: Wire `fab_minimum_findings` into `Board.resolve()`, with a failing test first**

  Add to `tests/test_via_types_allowed.py` (or a small new
  `tests/test_fab_minimum_findings.py` if that reads more clearly - match
  the file naming convention already used for kind-specific finding
  tests such as `test_chamfer_clearance_finding.py`):

  ```python
  def test_a_net_class_below_the_fab_minimum_is_a_fab_finding():
      g = board_geometry([footprint("U1", 10, 10, inst="u1", nets=("A", "B"))], width=30, height=30)
      import dataclasses
      from placemat.board_geometry import NetClass
      classes = {n: dataclasses.replace(nc, track_width=0.05) for n, nc in g.netclasses.items()}
      g = dataclasses.replace(g, netclasses=classes)
      b = Board(g, edge_margin=0.5, keep_going=True, fab_min={"track_mm": 0.09})
      b.place(Part("u1"), at=Location(10, 10))
      plan = b.resolve()
      fab = [f for f in plan.findings if f.kind == "fab"]
      assert fab and "track width" in fab[0]
  ```

  This test needs the `fab` finding kind, added in Task 10 - if Task 10
  has not run yet, `Finding("fab", ...)` raises `ValueError` (kind not in
  `KINDS`). Order this step AFTER Task 10 in execution even though it is
  written here as part of Task 9's file; **execute Task 10 before this
  step**, or write the wiring now and defer only this specific test to
  immediately after Task 10 (call out clearly in the session log which
  you did).

  Wire the check into `resolve()`: find where `_check_stamped_via_types()`
  is called from (`grep -n "_check_stamped_via_types()" src/placemat/layout.py`
  - it is invoked once, inside the resolve pipeline). Add, right beside
  that call:

  ```python
          for msg in fab_minimum_findings(self.geometry, self.fab_min):
              plan.findings.append(Finding("fab", msg))
  ```

  Add the import at the top of `layout.py`: `from .project import
  fab_minimum_findings` (check for an import cycle first -
  `project.py` does not import `layout.py`, so this is safe; confirm with
  `grep -n "^from\|^import" src/placemat/project.py`).

- [ ] **Step 7: Run the fab-minimum test (after Task 10) and the full via/finding test files**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_via_types_allowed.py tests/test_finding_kinds.py
  ```

- [ ] **Step 8: Commit**

  ```bash
  git add src/placemat/layout.py tests/test_via_types_allowed.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  A script may not draw an if-needed via type directly; fab minimums are a
  run-start finding

  fab_vias_needed refuses like fab_vias' absence, naming that it is
  preferred off rather than disallowed; give way (a later task) is the
  only path that may still use it.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 10: New finding kinds `fab`, `facts`, `needs`

**Files:**
- Modify: `src/placemat/findings.py`
- Modify: `tests/test_finding_kinds.py`

**Interfaces:**
- Produces: `KINDS` includes `"fab"`, `"facts"`, `"needs"`.

- [ ] **Step 1: Update the failing assertion in `test_finding_kinds.py`**

  In `test_a_finding_is_its_text_and_carries_its_kind`, change:

  ```python
      assert set(KINDS) == {"unplaced", "link_over", "fixed", "copper", "label", "escape_crossed", "pair_crossed",
                            "escape_closed", "escape_walled", "setup", "route", "vias"}
  ```

  to:

  ```python
      assert set(KINDS) == {"unplaced", "link_over", "fixed", "copper", "label", "escape_crossed", "pair_crossed",
                            "escape_closed", "escape_walled", "setup", "route", "vias", "fab", "facts", "needs"}
  ```

- [ ] **Step 2: Run it, confirm it fails (KINDS does not yet include the three)**

- [ ] **Step 3: Add the three kinds to `findings.py`**

  ```python
  KINDS = (
      "unplaced",         # a part, cell or block the resolve could not place
      "link_over",        # a link longer than its limit
      "fixed",            # a decided item (fixed, a cutout, a keepout) not legal where it was put
      "copper",           # planned copper that meets another net, crosses a keepout, or cannot bridge
      "label",             # a label with a part on it
      "escape_crossed",   # two escapes from one part's pins cross near its pin row
      "escape_closed",    # a pad's last route toward what it connects to is closed
      "escape_walled",    # a pad with no route out at all
      "pair_crossed",     # a differential pair's two halves cross: a swap or a turn uncrosses it
      "setup",            # the same every run of the script: an undeclared part, a layer the board lacks
      "route",            # an adopted route dropped because a part it joins moved: the router routes it again
      "vias",             # carried vias that gave way: shared, moved or dropped (giveway.py)
      "fab",              # a board rule or net class below the fab's minimum (fab-profile.json's min)
      "facts",            # the board's facts do not match the last `placemat facts --confirm`
      "needs",            # give way would place with an if-needed via type the fab profile prefers off
  )
  ```

- [ ] **Step 4: Run the finding kinds test, confirm it passes**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_finding_kinds.py
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add src/placemat/findings.py tests/test_finding_kinds.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  Three new finding kinds: fab, facts, needs
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

  (Now go back and finish Task 9 Step 6's deferred test, since `fab` exists now.)

---

### Task 11: Give way's fourth way, "shorten"

This is the highest-uncertainty task in the plan (see the report's
rulings). Another agent may be concurrently touching giveway.py's move
search in a separate worktree - keep this change to one new code block
plus the `Action`/report additions, not a rewrite of `_give`'s existing
share/move/drop blocks.

**Files:**
- Modify: `src/placemat/giveway.py`
- Test: `tests/test_vias_give_way.py`

**Interfaces:**
- Consumes: `Settings.score_via_shorten` (Task 3); `Board.fab_vias`/`Board.fab_vias_needed`
  (Task 9), reachable from `_give` via `occ.settings`/`occ.geometry` and a
  new `occ.fab_vias`/`occ.fab_vias_needed` (added in Step 3 below, since
  `_give` currently has no via-type awareness at all - it draws whatever
  span a shorten needs without checking the fab profile, exactly the gap
  this task closes).
- Produces: `Action.kind` gains `"shorten"`; `report()` gains a "shortened"
  clause; a `Finding("needs", ...)` when the type is if-needed.

- [ ] **Step 1: Read `_give`'s current structure and `Occupancy`'s constructor once more to place the new code precisely**

  ```bash
  grep -n "class Occupancy\|def __init__" src/placemat/occupancy.py | head -5
  grep -n "def _give(" -A 5 src/placemat/giveway.py
  ```

  Confirm `Occupancy` is constructed from a `Board` (it already reads
  `occ.settings`/`occ.geometry` elsewhere in giveway.py) and find where
  `Board`'s `fab_vias`/`fab_vias_needed` would need to reach it - likely
  `Occupancy.__init__` already takes the `Board` or its settings/geometry
  directly; if it does not already carry a via-type reference, add
  `self.fab_vias = getattr(board, "fab_vias", frozenset())` and
  `self.fab_vias_needed = getattr(board, "fab_vias_needed", frozenset())`
  to `Occupancy.__init__` (or wherever it already copies `board.*`
  attributes - follow the existing pattern for `plane_nets`/`quiet_nets`,
  which are set post-construction from `Board.resolve()` per
  `layout.py:3817-3818`; add `occ.fab_vias = self.fab_vias` and
  `occ.fab_vias_needed = self.fab_vias_needed` right beside those two
  lines instead, if that is the established wiring point).

- [ ] **Step 2: Write the failing test for a plain shorten (type "yes")**

  Add to `tests/test_vias_give_way.py`, modelling the shape of the file's
  existing `_cell_board` helper (front-face pad with a GND via/tail whose
  spot, when searched, lands over a back-face pad on the same net -
  today's tests use this pattern to force give-way). The exact geometry
  needs a board whose stackup gives GND a plane on two inner layers
  (In1, In4) and a through via that would otherwise conflict, landing
  over a far-face pad; build it with `dataclasses.replace(board_geometry(...),
  layers=SIX_LAYER_TUPLE, layer_types={IN1: "power", IN4: "power", ...})`
  the same way `test_via_types_allowed.py`'s `_board` helper extends
  `board_geometry`. Write the test to assert:

  ```python
  def test_a_drop_shortens_to_the_planes_nearest_layer_when_yes():
      plan = _cell_board_with_plane(fab_vias=frozenset({"blind"})).resolve()
      assert plan.step("m").placement is not None, plan.step("m").note
      [a] = plan.occupancy.given_way.values()
      assert a.kind == "shorten"
      assert a.cost == plan.occupancy.settings.score_via_shorten
  ```

  Since the exact fixture geometry needed to force a plane-spanning
  conflict is intricate (six layers, GND plane on specific inner layers,
  a stamped cell whose via would otherwise meet a far-face pad), build it
  incrementally: start from `test_via_span.py`'s `_six`/`SIX` pattern
  (six-layer `board_geometry`) crossed with
  `test_vias_give_way.py`'s `_cell_board` (a cell via meeting a
  far-face pad forces give-way); write the smallest test that forces
  `_give` to reach the new code path and iterate on the fixture until the
  assertion is meaningful, rather than guessing the full fixture up
  front.

- [ ] **Step 3: Run it, confirm it fails (kind is "drop" or the placement is refused, not "shorten")**

- [ ] **Step 4: Implement "shorten" in `_give`**

  Add a helper above `_give` that finds the plane's nearest layer between
  a via's face and the far face:

  ```python
  def _shorten_span(occ, g: Group, layer: CopperLayer) -> tuple | None:
      """The layers a shortened via would span: from `layer` (the via's
      own face) to the nearest layer that carries a plane of `g.net`
      between it and the far face - None when no such layer exists (the
      net has no plane there, or the via already reaches no further than
      its own face's inner neighbour)."""
      from .board_geometry import stackup_order
      stack = sorted(occ.geometry.layers, key=stackup_order)
      if layer not in stack:
          return None
      start = stack.index(layer)
      step = 1 if start == 0 else -1 if start == len(stack) - 1 else (1 if layer.face is not None else 0)
      # a via's own face is always an end of the stack (F or B); walk inward
      rng = range(start + 1, len(stack)) if start == 0 else range(start - 1, -1, -1)
      for i in rng:
          candidate = stack[i]
          if occ.geometry.layer_types.get(candidate) in ("power", "mixed") and \
                  occ.geometry.copper_on(candidate, net=g.net):
              return tuple(stack[min(start, i):max(start, i) + 1])
      return None
  ```

  (`layer.face` is `Face.FRONT`/`Face.BACK`/`None` per `values.py`'s
  `CopperLayer.face`; a via's own face is always F or B, i.e. `start` is
  always `0` or `len(stack) - 1`, so the `step`/ternary above can be
  simplified once the real code is in front of you - keep whichever reads
  clearest, the test in Step 2 is the source of truth.)

  Insert the new attempt in `_give`, after the `if s.place_via_move > 0:
  ... said.append(...)` block and before the final `if g.net not in
  occ.plane_nets:` plane/drop block (see the report's ruling: tried
  between move and drop by cost, added textually after move so the
  concurrent move-search optimisation work is untouched):

  ```python
      if g.net in occ.plane_nets and pad_key is not None:
          span = _shorten_span(occ, g, layer)
          if span is not None and len(span) >= 2:
              kind = _via_kind(span) if "_via_kind" in dir() else None  # see note below
              tier = "yes" if kind in occ.fab_vias else "if-needed" if kind in occ.fab_vias_needed else "no"
              if tier == "yes":
                  drill = occ.settings.copper_microvia_drill if len(span) == 2 and layer.face is not None else g.hole.circle[2] if g.hole is not None else 0.0
                  ring = replace(g.ring, layers=frozenset(span))
                  hole = replace(g.hole, layers=frozenset(span)) if g.hole is not None else None
                  shapes = tuple(x for x in (ring, hole) if x is not None)
                  if not judge.hit(shapes, judge.near(ring.box, occ.gap_for(ring)), own, say=False):
                      return Action("shorten", g.id, g.owner, g.home, g.net, g.centre, g.centre, None, old,
                                    pad_key, met, s.score_via_shorten, shapes), None
              elif tier == "if-needed":
                  said.append("no spot; it places with a %s via shortened to %s (via.%s is if-needed in "
                              "fab-profile.json)" % (_via_kind(span), "-".join(l.value for l in span), _via_kind(span)))
      if g.net not in occ.plane_nets:
  ```

  This references `_via_kind`, which lives in `layout.py` today (used by
  `_allow_via_type`) - import it in `giveway.py`:
  `from .layout import _via_kind` would create a circular import
  (`layout.py` already imports from `giveway.py`). Move `_via_kind`
  (and its sibling `_is_micro`/`_span_text` if they are small pure
  functions with no `Board` dependency - grep their bodies first) to
  `values.py` or a new tiny module both `layout.py` and `giveway.py` can
  import without a cycle; update `layout.py`'s imports of them
  accordingly. Do this as a preparatory sub-step before wiring `_give`,
  with its own quick test run (`grep -n "_via_kind\|_is_micro\|_span_text"
  src/placemat/layout.py` first to see every call site to update).

  The `if-needed` branch above only *notes* the shorten in `said` (the
  refusal reasons collected for this via) - it does not return an
  Action. `_give` then continues to the plane/drop block as it does
  today, so the pad still gives way by dropping if it can, and the
  `said` sentence naming the if-needed possibility is folded into the
  eventual refusal text `_give` returns when nothing else works either.
  Whether the exact wording lands in the final refusal or needs a
  dedicated place to surface as a `Finding("needs", ...)` depends on how
  `resolve()`'s caller (layout.py, where `_refused`'s message becomes a
  `ValueError` today under `keep_going=False`, or where `apply()`'s
  `Action`s become a finding under `keep_going=True`/report()) is wired -
  read `giveway.py`'s `report()` and layout.py's call site of
  `giveway.resolve`/`giveway.apply` (`grep -n "giveway\." src/placemat/layout.py`)
  to find where a `Finding("vias", ...)` is currently raised from
  give-way's outcome, and add the `Finding("needs", ...)` right beside
  it, only when an if-needed shorten was the road not taken for an item
  that ended up refused or dropped.

- [ ] **Step 5: Run the shorten test, iterate on the fixture and the implementation together until it passes**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_vias_give_way.py -k shorten
  ```

- [ ] **Step 6: Write the failing test for if-needed (judged, not applied, with the `needs` finding)**

  ```python
  def test_an_if_needed_type_is_judged_but_never_applied():
      plan = _cell_board_with_plane(fab_vias_needed=frozenset({"blind"})).resolve()
      needs = [f for f in plan.findings if f.kind == "needs"]
      assert needs and "if-needed" in needs[0] and "blind" in needs[0]
      assert plan.step("m").placement is None or "drop" in (plan.occupancy.given_way.get("m via 0") or Action("", "", "", "", "", ())).kind
  ```

  Adjust the assertion once the actual refusal/finding shape from Step 4
  is in front of you - the spec's own wording is the source of truth:
  "with 'if-needed', the same cell is refused, with the step note and a
  needs finding naming the count, net, span and fab-profile key."

- [ ] **Step 7: Run it, iterate until it passes; then run the full give-way file**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vias_give_way.py
  ```

- [ ] **Step 8: Add the "shortened" clause to `report()`**

  In `giveway.py`'s `report()`, extend the `for kind, verb in (("share",
  "shared"), ("move", "moved"), ("drop", "dropped")):` tuple with
  `("shorten", "shortened")`.

- [ ] **Step 9: Add `score.via_shorten` to `api.md`'s settings table (done fully in Task 14; just confirm here it is not forgotten)**

- [ ] **Step 10: Commit**

  ```bash
  git add src/placemat/giveway.py src/placemat/layout.py tests/test_vias_give_way.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  Give way's fourth way: shorten a plane drop to the plane's nearest layer

  Priced at score.via_shorten, between move and drop. An if-needed via
  type is judged but never applied: the step says what it would have
  taken, and a needs finding records it.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 12: The facts document and its digest

**Files:**
- Create: `src/placemat/facts.py`
- Test: `tests/test_facts.py` (new)

**Interfaces:**
- Produces: `FactsDocument` (frozen dataclass: `layers: dict`, `pairs:
  dict`, `via_types: dict`, `fab_min: dict`, `rise_c: float`,
  `plane_mismatches: tuple = ()`); `facts_of(geometry, fab: FabProfile,
  rise_c: float, plane_layers: frozenset = frozenset()) -> FactsDocument`;
  `FactsDocument.digest() -> str`; `unconfirmed_reasons(doc, confirmed_digest:
  str) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

  Create `tests/test_facts.py`:

  ```python
  """The facts document placemat facts prints, and its digest: what
  placemat facts --confirm records in placemat.toml's [facts] confirmed."""
  import dataclasses

  from placemat.board_geometry import NetClass
  from placemat.facts import facts_of, unconfirmed_reasons
  from placemat.project import FabProfile
  from placemat.values import CopperLayer
  from tests.fixtures import board_geometry, footprint

  F, B, IN1 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1


  def _geometry():
      g = board_geometry([footprint("U1", 10, 10, inst="u1")], width=30, height=30)
      return dataclasses.replace(g, layers=(F, IN1, B), layer_types={F: "signal", IN1: "power", B: "signal"},
                                 copper_mm={F: 0.035, IN1: 0.0152, B: 0.035},
                                 netclasses={**g.netclasses, "CLK_P": NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1),
                                            "CLK_N": NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1)})


  def test_layers_carry_role_and_weight():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      assert doc.layers["F.Cu"] == {"role": "signal", "copper_mm": 0.035}
      assert doc.layers["In1.Cu"] == {"role": "power", "copper_mm": 0.0152}


  def test_pair_classes_and_their_nets():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      assert doc.pairs == {"Fast": ["CLK_N", "CLK_P"]}


  def test_via_types_by_tier():
      fab = FabProfile(via_types=frozenset({"buried"}), via_needed=frozenset({"blind"}))
      doc = facts_of(_geometry(), fab, rise_c=10.0)
      assert doc.via_types == {"micro": "no", "blind": "if-needed", "buried": "yes"}


  def test_the_digest_is_stable_for_the_same_facts():
      doc1 = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      doc2 = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      assert doc1.digest() == doc2.digest()


  def test_the_digest_changes_when_a_copper_weight_changes():
      doc1 = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      changed = dataclasses.replace(_geometry(), copper_mm={F: 0.070, IN1: 0.0152, B: 0.035})
      doc2 = facts_of(changed, FabProfile(), rise_c=10.0)
      assert doc1.digest() != doc2.digest()


  def test_a_board_never_confirmed_is_unconfirmed():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      assert unconfirmed_reasons(doc, "") == ["no confirmation record yet"]


  def test_a_matching_digest_is_confirmed():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      assert unconfirmed_reasons(doc, doc.digest()) == []


  def test_a_changed_digest_is_unconfirmed():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      assert unconfirmed_reasons(doc, "not" + doc.digest()) == ["the facts have changed since they were last confirmed"]


  def test_no_via_section_at_all_is_unconfirmed():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0, fab_has_via_section=False)
      assert "fab-profile.json has no via section" in unconfirmed_reasons(doc, doc.digest())


  def test_a_signal_layer_carrying_a_plane_is_flagged():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0, plane_layers=frozenset({F}))
      assert any("F.Cu" in m and "signal" in m for m in doc.plane_mismatches)


  def test_a_power_layer_with_no_plane_is_flagged():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0, plane_layers=frozenset())
      assert any("In1.Cu" in m for m in doc.plane_mismatches)
  ```

  (`test_no_via_section_at_all_is_unconfirmed` implies `facts_of` needs a
  `fab_has_via_section: bool` argument, since `FabProfile` alone cannot
  distinguish "no via section in the file" from "a via section present
  but naming nothing" - both currently read as `via_types=frozenset(),
  via_needed=frozenset()`. Confirm this is genuinely needed once you
  write `fab_profile()`'s reading logic: if it is simpler to have
  `fab_profile()` itself expose whether the file had a `"via"` key at
  all, thread that through instead - either approach satisfies the
  spec's "fab-profile.json has no via or min" unconfirmed reason; pick
  whichever keeps `facts_of`'s signature cleanest and adjust the test
  along with it.)

- [ ] **Step 2: Run it, confirm ImportError**

- [ ] **Step 3: Implement `src/placemat/facts.py`**

  ```python
  """The facts a board carries, from the board's own stackup and net
  classes and from fab-profile.json, and whether they match the last
  `placemat facts --confirm`. Each fact's home is docs/superpowers/specs/
  2026-09-30-board-facts-fixed-and-preferred-design.md's rule: placemat.toml
  holds none of this."""
  from __future__ import annotations

  from dataclasses import dataclass, field
  import hashlib
  import json

  from .board_geometry import BoardGeometry, stackup_order
  from .project import FabProfile
  from .values import CopperLayer

  _VIA_KINDS = ("micro", "blind", "buried")


  @dataclass(frozen=True)
  class FactsDocument:
      layers: dict                     # {layer name: {"role": str, "copper_mm": float|None}}
      pairs: dict                      # {net class name: [nets], sorted}
      via_types: dict                  # {"micro"/"blind"/"buried": "yes"/"no"/"if-needed"}
      fab_min: dict                    # fab.min, as given
      rise_c: float
      fab_has_via_section: bool = True   # False: fab-profile.json names no via section at all
      plane_mismatches: tuple = ()     # sentences: a signal layer with a plane, or a power layer without one

      def _digest_doc(self) -> dict:
          return {"layers": self.layers, "pairs": self.pairs, "via_types": self.via_types,
                  "fab_min": self.fab_min, "rise_c": self.rise_c}

      def digest(self) -> str:
          return hashlib.sha256(json.dumps(self._digest_doc(), sort_keys=True).encode()).hexdigest()


  def facts_of(geometry: BoardGeometry, fab: FabProfile, rise_c: float,
              plane_layers: frozenset = frozenset(), fab_has_via_section: bool = True) -> FactsDocument:
      stack = sorted(geometry.layers, key=stackup_order)
      layers = {l.value: {"role": geometry.layer_types.get(l, "signal"), "copper_mm": geometry.copper_mm.get(l)}
               for l in stack}
      by_class: dict = {}
      for net, nc in geometry.netclasses.items():
          if nc.name == "Default" or nc.diff_pair_width is None or nc.diff_pair_gap is None:
              continue
          by_class.setdefault(nc.name, []).append(net)
      pairs = {name: sorted(nets) for name, nets in by_class.items()}
      via_types = {}
      for kind in _VIA_KINDS:
          via_types[kind] = "yes" if kind in fab.via_types else "if-needed" if kind in fab.via_needed else "no"
      mismatches = []
      for l in stack:
          role = geometry.layer_types.get(l, "signal")
          has_plane = l in plane_layers
          if role == "signal" and has_plane:
              mismatches.append("%s is signal but carries a plane()" % l.value)
          elif role == "power" and not has_plane:
              mismatches.append("%s is power (ground) but carries no plane()" % l.value)
      return FactsDocument(layers, pairs, via_types, dict(fab.min), rise_c, fab_has_via_section, tuple(mismatches))


  def unconfirmed_reasons(doc: FactsDocument, confirmed_digest: str) -> list:
      """Why `doc` is unconfirmed, or [] when it matches the last
      `placemat facts --confirm`."""
      out = []
      if not confirmed_digest:
          out.append("no confirmation record yet")
          return out
      if not doc.fab_has_via_section:
          out.append("fab-profile.json has no via section")
      if not doc.fab_min:
          out.append("fab-profile.json has no min section")
      if doc.digest() != confirmed_digest:
          out.append("the facts have changed since they were last confirmed")
      return out
  ```

  (`test_a_board_never_confirmed_is_unconfirmed` expects exactly `["no
  confirmation record yet"]` with no other reasons piled on - the early
  `return out` after that append satisfies it; the other tests supply a
  real `confirmed_digest` so the function falls through to the
  `via`/`min`/digest checks. Re-check each test's exact expected list
  once written and adjust ordering/wording to match - the tests are the
  source of truth, not this sketch.)

- [ ] **Step 4: Run the facts tests, iterate to green**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_facts.py
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add src/placemat/facts.py tests/test_facts.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  The facts document: layer roles and weights, pair classes, via tiers,
  fab minimums, and whether they match the last confirmation
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 13: `placemat facts` command, `--confirm`, and the run-start unconfirmed check

**Files:**
- Modify: `src/placemat/cli.py`
- Modify: `src/placemat/runner.py`
- Test: `tests/test_cli_output.py`, a new `tests/test_facts_cli.py` if `test_cli_output.py`'s
  conventions do not fit a full command test (check first)

**Interfaces:**
- Produces: `placemat facts <script> [--confirm] [--json]` (`cmd_facts` in
  cli.py); `facts.write_confirmed(placemat_toml_path, digest) -> None`
  (small text-editing helper, no TOML-writer dependency available); a
  `Finding("facts", ...)` and a `say("facts", ...)` console line early in
  `runner._run()`.

- [ ] **Step 1: Grep `previewer.py`/`runner.py` for the lightest existing way to run a script against a fresh `Board` without a full resolve, to reuse for reading `board._planes_declared`**

  ```bash
  grep -n "_planes_declared\|def run_script\|def scripted_board" src/placemat/layout.py src/placemat/context.py src/placemat/runner.py
  ```

  Confirm `Board._planes_declared` is a list of `(net_name, layers:
  tuple[CopperLayer, ...])` populated as soon as `board.plane(...)` runs
  (verified during planning at `layout.py:3691`,
  `self._planes_declared.append((name, layers))`), and that
  `context.run_script(script, board)` is the existing entry point that
  executes a layout script against a `Board` object (used inside
  `runner.scripted_board`).

- [ ] **Step 2: Write the failing test for `write_confirmed`**

  Add to `tests/test_facts.py`:

  ```python
  def test_write_confirmed_adds_a_facts_section(tmp_path):
      from placemat.facts import write_confirmed
      p = tmp_path / "placemat.toml"
      p.write_text("[place]\nstep = 0.1\n")
      write_confirmed(p, "abc123")
      text = p.read_text()
      assert "[facts]" in text and 'confirmed = "abc123"' in text
      assert "[place]" in text and "step = 0.1" in text


  def test_write_confirmed_replaces_an_existing_value(tmp_path):
      from placemat.facts import write_confirmed
      p = tmp_path / "placemat.toml"
      p.write_text('[facts]\nconfirmed = "old"\n')
      write_confirmed(p, "new")
      text = p.read_text()
      assert text.count("[facts]") == 1 and 'confirmed = "new"' in text and "old" not in text


  def test_write_confirmed_creates_the_file_when_it_does_not_exist(tmp_path):
      from placemat.facts import write_confirmed
      p = tmp_path / "placemat.toml"
      write_confirmed(p, "abc123")
      assert 'confirmed = "abc123"' in p.read_text()
  ```

- [ ] **Step 3: Run it, confirm ImportError**

- [ ] **Step 4: Implement `write_confirmed` in `src/placemat/facts.py`**

  ```python
  import re as _re

  _FACTS_SECTION_RE = _re.compile(r"^\[facts\]\s*$", _re.M)
  _CONFIRMED_LINE_RE = _re.compile(r'^confirmed\s*=\s*"[^"]*"\s*$', _re.M)


  def write_confirmed(path, digest: str) -> None:
      """Write [facts] confirmed = "<digest>" into a placemat.toml,
      replacing an existing value in place or adding a new [facts]
      section - the only part of the file this touches. Never fed into a
      run's id: this is placemat's own record, not a board fact."""
      from pathlib import Path
      p = Path(path)
      text = p.read_text() if p.exists() else ""
      m = _FACTS_SECTION_RE.search(text)
      if m is None:
          if text and not text.endswith("\n"):
              text += "\n"
          text += "%s[facts]\nconfirmed = \"%s\"\n" % ("\n" if text else "", digest)
      else:
          section_start = m.end()
          next_section = _re.search(r"^\[", text[section_start:], _re.M)
          section_end = section_start + next_section.start() if next_section else len(text)
          section = text[section_start:section_end]
          line = 'confirmed = "%s"\n' % digest
          if _CONFIRMED_LINE_RE.search(section):
              section = _CONFIRMED_LINE_RE.sub(line.rstrip("\n"), section, count=1)
          else:
              section = "\n" + line + section.lstrip("\n")
          text = text[:section_start] + section + text[section_end:]
      p.write_text(text)
  ```

  Iterate on the exact regex/splicing against the three tests above until
  they pass - text-splicing edge cases (blank lines, trailing newline)
  are easiest to get right by running the tests, not by reasoning ahead.

- [ ] **Step 5: Run the write_confirmed tests**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_facts.py
  ```

- [ ] **Step 6: Write the failing test for `cmd_facts`**

  Check `tests/test_cli_output.py`'s conventions first (grep for how it
  invokes `cli.main([...])` or a `cmd_*` function directly, and how it
  captures stdout - reuse that exact pattern). A representative shape:

  ```python
  def test_facts_prints_layers_and_marks_unconfirmed(tmp_path, capsys):
      # build a minimal .zen + script the same way test_project.py's
      # find_board tests do, generate no real board - instead point
      # facts at a hand-built layout.kicad_pcb the way test_via_span.py's
      # _six_layer_board does, and a script that declares Board(...) and
      # calls board.plane(...). Follow test_cli_output.py's existing
      # end-to-end fixture (it must already do something similar for
      # `placemat check`/`placemat settings`) rather than inventing a new
      # scaffold from scratch.
      ...
  ```

  Given the scaffolding cost, prefer testing `cmd_facts`'s pure logic
  (formatting, `--confirm`'s write, the unconfirmed reasons surfaced) via
  a small helper `facts.render(doc, reasons) -> list[str]` that `cmd_facts`
  calls, tested directly in `tests/test_facts.py` without going through
  argparse/a real board at all, and cover only argument wiring
  (`--confirm`, `--json`) at the CLI layer with one thin end-to-end test
  once the render helper is solid. Add `render` to `facts.py`:

  ```python
  def render(doc: FactsDocument, reasons: list) -> list:
      """The lines `placemat facts` prints."""
      lines = []
      for name, info in sorted(doc.layers.items(), key=lambda kv: stackup_order(CopperLayer.of(kv[0]))):
          weight = "%.4f mm" % info["copper_mm"] if info["copper_mm"] is not None else "unknown (no stackup declared)"
          lines.append("layer      %-8s role %-6s weight %s" % (name, info["role"], weight))
      for name, nets in sorted(doc.pairs.items()):
          lines.append("pair class %-12s %s" % (name, ", ".join(nets)))
      for kind, tier in sorted(doc.via_types.items()):
          lines.append("via        %-8s %s" % (kind, tier))
      for key, value in sorted(doc.fab_min.items()):
          lines.append("fab min    %-12s %g mm" % (key, value))
      lines.append("rise       %g C" % doc.rise_c)
      for m in doc.plane_mismatches:
          lines.append("flagged    %s" % m)
      if reasons:
          lines.append("unconfirmed: " + "; ".join(reasons))
      else:
          lines.append("confirmed")
      return lines
  ```

  Test it directly:

  ```python
  def test_render_lists_every_fact_and_says_unconfirmed():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      lines = render(doc, unconfirmed_reasons(doc, ""))
      assert any(l.startswith("layer      F.Cu") for l in lines)
      assert any(l.startswith("pair class Fast") for l in lines)
      assert any(l.startswith("via        micro") for l in lines)
      assert lines[-1] == "unconfirmed: no confirmation record yet"


  def test_render_says_confirmed_when_the_digest_matches():
      doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
      lines = render(doc, unconfirmed_reasons(doc, doc.digest()))
      assert lines[-1] == "confirmed"
  ```

- [ ] **Step 7: Run those two, confirm they pass; run the whole facts test file**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_facts.py
  ```

- [ ] **Step 8: Wire `cmd_facts` into `cli.py`**

  Add a subparser (beside `ck = sub.add_parser("check", ...)`):

  ```python
      fa = sub.add_parser("facts", help="the board's facts (stackup weight and roles, pair classes, via tiers, "
                                        "fab minimums) and whether they match the last confirmation")
      fa.add_argument("script", help="the board's layout script")
      fa.add_argument("--confirm", action="store_true",
                      help="record the printed facts' digest in placemat.toml's [facts] confirmed")
      fa.add_argument("--json", action="store_true")
  ```

  Add `cmd_facts`:

  ```python
  def cmd_facts(args) -> int:
      from . import facts as facts_mod
      from .context import run_script
      from .kicad.read import read_board
      from .layout import Board
      from .project import fab_profile, find_board
      from .settings import bind, load
      script = Path(args.script).resolve()
      src = find_board(script)
      cfg = load(src.board_dir)
      fab = fab_profile(src.board_dir)
      with bind(cfg):
          geometry = read_board(src.pcb, courtyard_excess_mm=fab.courtyard_excess)
          board = Board(geometry, settings=cfg, fab_vias=fab.via_types, fab_vias_needed=fab.via_needed,
                       fab_source=str(fab.path) if fab.path else "")
          run_script(script, board)
      plane_layers = frozenset(l for _, layers in board._planes_declared for l in layers)
      doc = facts_mod.facts_of(geometry, fab, cfg.check_rise_c, plane_layers, fab_has_via_section=bool(fab.via_types or fab.via_needed) or "via" in _raw_fab_json(src.board_dir))
      reasons = facts_mod.unconfirmed_reasons(doc, cfg.facts_confirmed)
      if args.confirm:
          facts_mod.write_confirmed(src.board_dir / "placemat.toml", doc.digest())
          console.say("facts", "confirmed: %s" % doc.digest())
          return 0
      if args.json:
          console.data(json.dumps({"layers": doc.layers, "pairs": doc.pairs, "via_types": doc.via_types,
                                   "fab_min": doc.fab_min, "rise_c": doc.rise_c,
                                   "plane_mismatches": list(doc.plane_mismatches), "unconfirmed": reasons}, indent=2))
          return 0
      for line in facts_mod.render(doc, reasons):
          console.say("facts", line)
      return 1 if reasons else 0
  ```

  `_raw_fab_json` (a tiny local helper to distinguish "no via key" from
  "a via key naming nothing") - simplify this once you have Task 12's
  final `fab_profile()`/`facts_of()` shape in hand; if Task 12 already
  threads `fab_has_via_section` out of `fab_profile()` itself (the
  alternative noted in Task 12 Step 1), use that instead of re-reading
  the JSON file here. Pick whichever is true at this point in
  implementation and keep `cmd_facts` simple - do not maintain two ways
  of answering the same question.

  Register `"facts": cmd_facts` in `_dispatch`'s dict.

- [ ] **Step 9: Run cli smoke tests**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_cli_output.py
  ```

- [ ] **Step 10: Write the failing test for the run-start unconfirmed check**

  Check `tests/test_checks_wiring.py` or a runner-level test file for the
  established pattern of driving `runner._run`/`runner.run` end to end
  with a temp board (grep `def run(` callers in tests/ for the lightest
  existing fixture); add a test asserting:
  - a run whose `cfg.facts_confirmed` does not match the board's current
    facts digest prints a `say("facts", ...)` line containing "facts:
    unconfirmed - placemat facts" and the run record's findings include
    one of kind `"facts"`;
  - the run still completes (`status == "ok"`), not blocked.

  Given the cost of a full `runner.run()` fixture (real board generation),
  prefer testing the pure computation first - add to `tests/test_facts.py`:

  ```python
  def test_the_unconfirmed_line_names_the_command():
      from placemat.facts import unconfirmed_line
      assert unconfirmed_line(["no confirmation record yet"]) == "facts: unconfirmed - placemat facts"
  ```

  and only then add one thin runner-level test if an existing fixture
  makes it cheap; if it does not, note in the final report that the
  run-start wiring is verified by the bench run at the end (Task 15)
  instead of a dedicated unit test, and say so explicitly rather than
  silently skipping coverage.

- [ ] **Step 11: Implement `unconfirmed_line` and wire the run-start check into `runner._run`**

  In `src/placemat/facts.py`:

  ```python
  def unconfirmed_line(reasons: list) -> str:
      return "facts: unconfirmed - placemat facts"
  ```

  In `src/placemat/runner.py`'s `_run`, right after `generated =
  generate(src, run_dir, fresh, quiet, cfg.timeout_generate)` succeeds
  (before the script runs), add the facts check:

  ```python
          from . import facts as facts_mod
          from .kicad.read import read_board as _read_board_for_facts
          fab = fab_profile(src.board_dir)
          facts_geometry = _read_board_for_facts(src.pcb, courtyard_excess_mm=fab.courtyard_excess)
          # planes are read from the script's own declarations once it has run; until then this
          # checks everything but the plane/role mismatch, which the script phase below covers
          facts_doc = facts_mod.facts_of(facts_geometry, fab, cfg.check_rise_c)
          facts_reasons = facts_mod.unconfirmed_reasons(facts_doc, cfg.facts_confirmed)
          if facts_reasons:
              say("facts", facts_mod.unconfirmed_line(facts_reasons))
  ```

  and, once `plan` exists later in the function (after the script has run
  and `board._planes_declared` is populated), append the finding:

  ```python
          if facts_reasons:
              plan.findings.append(Finding("facts", "; ".join(facts_reasons)))
  ```

  placed right before `rec.findings = list(plan.findings)`. Import
  `Finding` at the top of `runner.py` if not already imported
  (`from .findings import Finding`).

  This computes `facts_doc` without the plane-mismatch information (no
  script has run yet at that point in the function) - accept that gap for
  the run-start check specifically (it still catches every other
  unconfirmed reason: stackup, pairs, via tiers, fab minimums) and note
  it as a documented limitation in the final report, rather than
  reordering `_run`'s generate/script phases to chase full parity with
  `placemat facts`'s own script-aware reading.

- [ ] **Step 12: Run the facts tests and a runner smoke test if one exists cheaply; otherwise defer to Task 15's bench**

  ```bash
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_facts.py
  ```

- [ ] **Step 13: Commit**

  ```bash
  git add src/placemat/facts.py src/placemat/cli.py src/placemat/runner.py tests/test_facts.py tests/test_cli_output.py
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  placemat facts prints the board's facts and tracks their confirmation

  --confirm records a digest in placemat.toml's [facts] confirmed, never
  fed into a run's id. An unconfirmed run says so on its own line and
  records a facts finding, but still runs.
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 14: Skill and reference docs

**Files:**
- Modify: `skills/placemat/SKILL.md`
- Modify: `skills/placemat/references/api.md`
- Modify: `skills/placemat/references/capture.md`
- Modify: `skills/placemat/references/migration.md`

No tests (documentation); read each file's exact current text before
editing (already read in full during planning - reuse those line
numbers, but re-grep before editing since earlier tasks in this plan
touch none of these files, so line numbers are stable).

- [ ] **Step 1: SKILL.md - add "Establish the facts" as the new first step of "## The loop"**

  Insert before the existing `1. **Run** \`placemat run ...\`` line (which
  becomes step 2, and every subsequent step's number shifts by one - renumber
  them all):

  ```markdown
  1. **Before any placement on a board, establish the facts.** Run
     `placemat facts <script>`. For each fact it marks unconfirmed or
     flags, ask the user with AskUserQuestion: layer roles and copper
     weights, pair nets, via types and their tier, fab minimums, the
     rise. Write each answer in its home (see "Where a change goes"
     below): the stackup and pair classes in the .zen, fab facts in
     fab-profile.json, the rise in placemat.toml. Regenerate, then run
     `placemat facts --confirm`. Never proceed on a default, and never
     write a fact the user did not give.
  ```

- [ ] **Step 2: SKILL.md - add "Where a change goes" as a new subsection right after it**

  ```markdown
  **Where a change goes:**

  | To change | Edit |
  |---|---|
  | A fact about the board (stackup, layer roles and weights, net classes, pair nets, design rules) | The .zen (`BoardConfig`) |
  | What the fab can make, and what the price allows (via types, fab minimums, courtyard excess) | fab-profile.json |
  | How placemat searches, scores, cleans up, grades DRC or tunes the router | placemat.toml |
  | What the layout intends (placement, copper, planes) | The layout script |
  ```

- [ ] **Step 3: Run a plain grep sanity check that no stray project/board name was introduced**

  ```bash
  grep -n "outward=N\|Widget\|Gauge\|fairprof" skills/placemat/SKILL.md
  ```

  (Should show only pre-existing generic examples already in the file,
  e.g. the `outward=N` from `cmd_faces`'s own help text quoted verbatim
  above - confirm none of Step 1/2's new text names a real project.)

- [ ] **Step 4: api.md - remove the three retired settings rows, add two new ones**

  Delete the three table rows:
  ```
  | `check.copper_oz` | 1.0 | outer copper weight the widths are sized for (`--copper-oz`) |
  | `route.layers` | every copper layer, minus an inner one the board's own plane fills whole | which layers the router may use |
  | `route.diff_pairs` | `["*"]` | net patterns naming the differential pairs: ... |
  ```

  Add, in the `[score]` group (right after the `score.via_drop` row):
  ```
  | `score.via_shorten` | 5 | mm a carried plane drop shortened to the plane's nearest layer costs, in place of a full drop |
  ```

  Add a new `[facts]` row after the `[score]` group (or its own small
  group beside `[route]` - place it wherever the table's existing section
  ordering reads most naturally, following the file's own grouping by
  bracket-section):
  ```
  | `facts.confirmed` | none | a digest of the last `placemat facts --confirm`; placemat's own record, not part of a run's id |
  ```

  Reword the `route.plane_share` row (it no longer decides the default
  layer list, only whether a pour counts as filling a layer whole for the
  purposes of guarding it from other nets' tracks during routing):
  ```
  | `route.plane_share` | 0.9 | how much of the board's own outline a pour must cover to be guarded whole from other nets' tracks while routing (it no longer decides the router's default layers - those come from each layer's declared role) |
  ```

  Add one line just above the settings table's opening paragraph (after
  "`placemat.toml` holds every behavioural constant."):
  ```
  placemat.toml is tuning only: it holds no fact about the board. A board
  fact belongs in the .zen or fab-profile.json; placemat.toml refuses one
  that strays in, naming where it moved.
  ```

- [ ] **Step 5: api.md - add fab-profile.json's new keys and the `placemat facts` command**

  Near wherever api.md currently documents fab-profile.json's shape
  (grep `fab-profile.json` in the file first - likely in "Setup" or
  "Boards of any shape" given the file's index), add:

  ```markdown
  fab-profile.json's `via` section takes each type (`micro`, `blind`,
  `buried`) as `"yes"` (placemat draws it), `"no"` (refused), or
  `"if-needed"` (preferred off: never drawn for a script's own `layers=`,
  but give way's shorten way may still use it, judged and reported, never
  applied). The 0.57 `allow_micro`/`allow_blind`/`allow_buried` booleans
  still read: `true` -> `"yes"`, `false` or absent -> `"no"`.

  A `min` section (`track_mm`, `clearance_mm`, `drill_mm`, `annular_mm`,
  `via_size_mm`) is checked against the board's net classes at the start
  of every run; a class below one is a `fab` finding naming the rule and
  both values.
  ```

  Add `placemat facts` to the Commands synopsis block:
  ```
  placemat facts <script> [--confirm] [--json]
  ```

  and a short paragraph after the `check` paragraph:
  ```markdown
  `facts` prints the board's own facts - each copper layer's role and
  weight, the pair classes and their nets, each via type's tier, the fab
  minimums and the rise - and whether they match the last confirmation.
  It flags a `signal` layer carrying a `plane()` and a `power` (ground)
  layer carrying none. `--confirm` records a digest of the printed facts
  in placemat.toml's `[facts] confirmed`; this is placemat's own record,
  never part of a run's id, so confirming never re-plans a board. A run
  whose facts do not match says so on its own line
  ("facts: unconfirmed - placemat facts") and records a finding, but
  still runs.
  ```

- [ ] **Step 6: capture.md - reword the current-path bullet**

  Change:
  ```
  - `current-path`: per net a `Pm.I` names, each two parts carrying on it
    judged at the lesser of their currents by the narrowest point of the
    widest route between them (tracks, vias, pours, and zone fills, each
    measured along the route at `check.zone_step`) against the IPC-2221
    outer-layer width at
    `--rise` (default 10 C) on `--copper-oz` (default 1 oz), with the neck's
    point and length; carriers no copper joins yet are reported, not judged,
    and so is a net only one part carries: give the part that takes the load
    (an input connector's load, a switch's inductor, a supply's output) its
    own `Pm.I` so the route between them is judged
  ```

  to:
  ```
  - `current-path`: per net a `Pm.I` names, each two parts carrying on it
    judged at the lesser of their currents by the narrowest point of the
    widest route between them (tracks, vias, pours, and zone fills, each
    measured along the route at `check.zone_step`) against the IPC-2221
    width at `--rise` (default 10 C), on the copper weight the board's own
    stackup gives that layer (the IPC-2221 inner-layer constant on an
    inner layer, outer on F.Cu/B.Cu; a layer the stackup does not weigh
    falls back to 1 oz), with the neck's point and length; carriers no
    copper joins yet are reported, not judged, and so is a net only one
    part carries: give the part that takes the load (an input connector's
    load, a switch's inductor, a supply's output) its own `Pm.I` so the
    route between them is judged
  ```

- [ ] **Step 7: migration.md - add an "## Unreleased" section at the top**

  Insert before `## To 0.57.2`:

  ```markdown
  ## Unreleased

  Board facts come from the board, not placemat.toml. Three keys are
  retired: `[check] copper_oz`, `[route] layers`, `[route] diff_pairs`. A
  placemat.toml still setting one is refused, naming its replacement.

  **The stackup.** Give the board's `BoardConfig` a `stackup`, with a
  `CopperLayer` for each copper layer, top to bottom, and a
  `DielectricLayer` between each pair:

  ```python
  load("@stdlib/board_config.zen", "BoardConfig", "CopperLayer", "DielectricLayer",
       "Material", "Stackup")

  STACKUP = Stackup(
      thickness = <board mm>,
      materials = [<the fab's prepreg and core, as Material(...)>],
      layers = [
          CopperLayer(thickness = <mm>, role = "<signal|mixed|power|ground>"),   # F.Cu
          DielectricLayer(thickness = <mm>, material = "<name>", form = "<prepreg|core>"),
          # ... each inner copper layer, with a dielectric after it ...
          CopperLayer(thickness = <mm>, role = "<signal|mixed|power|ground>"),   # B.Cu
      ],
  )
  CONFIG = BoardConfig(stackup = STACKUP, design_rules = ...)
  ```

  A layer's role is what it carries: `signal` tracks, `ground` or `power`
  a plane, `mixed` both. The route step now routes on `signal` and
  `mixed` layers (was: every layer minus one a plane happened to fill
  whole); inner-layer current paths are now judged by the inner IPC-2221
  constant and the layer's own weight (was: every layer as outer copper
  of `[check] copper_oz`). A board's route and current-path verdicts can
  change on this release.

  **Pair classes.** A differential pair class takes `nets = ["<NET>_P",
  "<NET>_N"]` (names or KiCad wildcard patterns), with its
  `diff_pair_width` and `diff_pair_gap`. A class of exactly two nets pairs
  them whatever they are called; more than two pair by the router's own
  suffix convention within the class. The Default class never makes
  pairs. Pairs now come from net classes (was: `[route] diff_pairs`,
  default every net named like a pair).

  **fab-profile.json.** `via`'s types take `"yes"`, `"no"` or
  `"if-needed"` (the 0.57 `allow_*` booleans still read: `true` ->
  `"yes"`, `false` or absent -> `"no"`). An `"if-needed"` type is never
  drawn for a script's own `layers=`; give way's new "shorten" way may
  still use it, judged but never applied, reported as a `needs` finding.
  A `min` section (`track_mm`, `clearance_mm`, `drill_mm`, `annular_mm`,
  `via_size_mm`) is checked against the board's net classes at the start
  of every run.

  **`placemat facts`.** Run it, then `placemat facts --confirm` once the
  printed facts are right. A run whose facts do not match the last
  confirmation says so on its own line and records a finding, but still
  runs.
  ```

- [ ] **Step 8: Grep every doc file for stray project/board names introduced by this task**

  ```bash
  grep -n "fairprof\|Core\b" skills/placemat/SKILL.md skills/placemat/references/api.md \
    skills/placemat/references/capture.md skills/placemat/references/migration.md
  ```

  (Expect no hits from this task's own additions; `Core` may appear as a
  pre-existing generic word - read any hit in context before treating it
  as a problem.)

- [ ] **Step 9: Commit**

  ```bash
  git add skills/placemat/SKILL.md skills/placemat/references/api.md \
    skills/placemat/references/capture.md skills/placemat/references/migration.md
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  Skill and docs: establish the facts before placement, placemat facts,
  fab-profile.json's via tiers and min, the Unreleased migration section
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 15: Whole-plan sweep - retired-setting fallout, any test still referencing old names

**Files:** any test file grep turns up.

- [ ] **Step 1: Grep the whole test suite for the retired settings and old function names, fix any straggler**

  ```bash
  grep -rln "check_copper_oz\|route_layers\b\|route_diff_pairs\b\|copper_oz=\|--copper-oz" tests/ | sort
  grep -rln "plane_layers\|_plane_zones" tests/
  grep -rln "_layer_types\b" src/ tests/
  ```

  For each hit not already updated by an earlier task, update it: a test
  building `Settings(route_diff_pairs=...)` or `Settings(check_copper_oz=...)`
  directly (not through a `placemat.toml`) will fail at `Settings(...)`
  construction once the fields are removed (`TypeError: unexpected keyword
  argument`) - fix by removing the argument and, where the test's intent
  was to drive pairing/route-layer behaviour, rebuilding its
  `BoardGeometry` with the right net classes / layer types instead
  (Task 5/6's new sources).

- [ ] **Step 2: Run the full set of files touched across every task in one pass**

  ```bash
  cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_stackup_copper_mm.py tests/test_board_geometry_read.py \
    tests/test_current_path_inner_layer.py tests/test_current_path_neck.py \
    tests/test_current_path_pairs.py tests/test_current_path_zone_width.py tests/test_checks.py \
    tests/test_checks_wiring.py tests/test_settings.py tests/test_settings_wiring.py \
    tests/test_pairs.py tests/test_explicit_pairs.py tests/test_crossing_cost.py tests/test_congestion.py \
    tests/test_route_plane_layers.py tests/test_route_settings.py tests/test_route_pairs.py \
    tests/test_project.py tests/test_via_types_allowed.py tests/test_via_span.py \
    tests/test_finding_kinds.py tests/test_vias_give_way.py tests/test_facts.py tests/test_cli_output.py
  ```

- [ ] **Step 3: Fix any remaining failure; re-run until green**

- [ ] **Step 4: Commit any fixes made in this sweep (skip if Step 1 found nothing to change)**

  ```bash
  git add -A
  git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
  Fix stragglers left over from retiring check.copper_oz, route.layers
  and route.diff_pairs
  EOF
  )"
  git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored" && echo "FIX ME" || echo "clean"
  ```

---

### Task 16: Bench

**Files:** none (measurement only, plus the final commit message).

- [ ] **Step 1: Run the bench**

  ```bash
  cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/
  PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2
  ```

- [ ] **Step 2: Read the tally, and compare against the worktree's baseline if `fixtures/bench.py --jobs 2` was run before this plan started (it was not, per the task's instructions - this is the first and only bench run)**

- [ ] **Step 3: Record the full tally output in the final commit message (an empty or near-empty diff commit is fine if Task 15 left nothing uncommitted - if so, note the tally in the session's final report instead of forcing an empty commit)**

  ```bash
  git status --short
  ```

  If there are uncommitted doc/test fixes from bench-driven discoveries,
  commit them with the tally in the message body. If the tree is already
  clean, do not create an empty commit - report the tally directly.

---

## Self-Review Notes

**Spec coverage:** Section 1 (copper weight, route layers, diff pairs) ->
Tasks 1, 2, 6, 7. Section 2 (fab-profile min) -> Task 8. Section 3 (fixed
vs preferred, shorten) -> Tasks 8, 9, 11. Section 4 (placemat facts) ->
Tasks 12, 13. Section 5 (skill changes) -> Task 14. Section 6 (migration)
-> Task 14 Step 7. Verification's bullet list is covered test-by-test
across Tasks 1-13; the skill pressure test is explicitly out of scope
(coordinator runs it after merge, per the task brief).

**Placeholder scan:** every step carries real code or an exact grep/test
command; the few steps that say "iterate on the fixture" (Task 11, the
highest-uncertainty task) name the exact assertion to converge on rather
than deferring the behaviour itself.

**Type consistency:** `FabProfile.via_types`/`via_needed` (frozenset),
`FabProfile.min` (dict) used consistently from Task 8 through Tasks 9, 12,
13. `resolved_layers`'s new `(explicit, all_layers, layer_types)` shape
used consistently in Tasks 6 and 7. `class_pairs(netclasses) -> tuple`
used consistently in Tasks 5 and 7.

**Review Focus:** the five items above each map to an explicit test:
no-stackup fallback (Task 1 Step 2/7), Default net class (Task 4, applied
in Task 5 Step 1), if-needed refused at declare time (Task 9 Step 2),
facts.confirmed excluded from the digest (Task 3 Step 1), role-based
route layers on the spec's own six-layer example (Task 6 Step 1).
