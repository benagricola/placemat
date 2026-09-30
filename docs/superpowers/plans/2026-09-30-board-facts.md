# Board facts: fixed and preferred - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move board facts (stackup, layer roles, pair classes, fab capability) to their one home - the board's .zen for board facts, fab-profile.json for what the fab allows, placemat.toml for tuning only - and give a session a `placemat facts` command to establish and confirm them.

**Architecture:** placemat already reads the generated `.kicad_pcb` through pcbnew into an immutable `BoardGeometry` (`src/placemat/kicad/read.py`, `src/placemat/board_geometry.py`). This plan adds a `copper_mm` per-layer field to that geometry (read by parsing the board's stackup text directly, since this KiCad 10 pcbnew build does not wrap `BOARD_STACKUP` in Python - verified below), teaches the current-path check and the route step's default layer list to use per-layer facts instead of a single `placemat.toml` number, moves differential-pair discovery from a glob setting to the board's own net classes, gives `fab-profile.json` a three-state via-type model (yes/no/if-needed) and a `min` section checked at run start, adds a fourth give-way ("shorten"), and adds the `placemat facts` command plus its confirmation record.

**Tech Stack:** Python 3, pcbnew (KiCad 10 Python bindings), pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-board-facts-fixed-and-preferred-design.md`

## Verified facts that change the plan from the spec's literal wording

- **`BOARD_STACKUP` is not wrapped in this pcbnew build.** `board.GetDesignSettings().GetStackupDescriptor()` returns a bare `SwigPyObject` with no usable methods; `pcbnew.BOARD_STACKUP` and `pcbnew.BOARD_STACKUP_ITEM` are both `None` in the generated `pcbnew.py`. **Task 1 reads the stackup by parsing the `.kicad_pcb` file's own `(setup (stackup ...))` S-expression text**, not the object API the spec named. Verified against the real six-layer board's file: each copper layer is `(layer "F.Cu" (type "copper") (thickness 0.035))`, thickness already in mm.
- **`board.GetLayerType()` does confirm the ground->power mapping's *destination*.** On the real board, three inner layers report `LT_POWER` (read as `"power"` by the existing `_layer_types`); none report a KiCad-native "ground". (Whether the .zen's stdlib actually writes `role="ground"` as `LT_POWER` is a generator-side fact outside this repo; not independently confirmed here, per the task's scope.)
- **The Default net class's `diff_pair_width`/`diff_pair_gap` are *not* reliably zero.** On the real board they read 0.2/0.2 mm - the *same* value every other class shows except the one genuine differential-pair class ("90Ohm Diff", which alone has different, user-set values). This means "a pair class sets `diff_pair_width`/`diff_pair_gap`" cannot be told apart from "this class never touched those fields" by nullness alone; only the class *name* ("Default") reliably excludes the non-pair default. **Task 5 implements the spec exactly as written** (exclude by name "Default" only) since that is what the spec says and what the task asked to verify; the residual risk (a coincidental 2-net non-Default, non-pair class, e.g. a connector's two same-purpose pins, getting treated as a pair) is called out in the final report, not silently "fixed" beyond the spec.

## Global Constraints

- placemat is 100% project-agnostic: no project, board, module or part names anywhere in source, tests' prose, docstrings, skill, references, migration or commit messages. Migration examples use `<mm>`, `<NET>_P` placeholders.
- Tunables are settings with defaults, documented in api.md's settings table, never literals. Fixed sets are enums.
- Plain ASCII only: no em/en dashes, no unicode arrows, straight quotes.
- A new field that feeds a run's digest carries `metadata={"omit_default": True}` where existing code does that, so old scripts digest as before (`Settings` fields already follow this convention where relevant; `FabProfile.json()` must stay byte-identical for a profile with no new keys).
- Never use `board.Remove(item)` in pcbnew code; always `board.Delete(item)`.
- Commits: `git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit ...`. No Claude/Anthropic/session/AI/Co-Authored-By references anywhere in a commit message; verify with `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"` after every commit (must print nothing).
- Tests: targeted files only. `cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/; PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/<files>`. Never run the full suite, never run the router, never `uv pip install`.
- Bench once, at the end: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2`; its tally lines go in the final commit message.

## Review Focus

- **A board with no stackup section at all** (an older board, or a hand-built test fixture): every copper-weight computation must fall back to a sane default (1 oz = 0.035 mm) rather than crashing on a missing dict key. Pinned in Task 1 and Task 2's tests.
- **A `route_diff_pairs`/`route_layers`/`check_copper_oz` key left in an *old* placemat.toml by a script that has not been migrated**: must be refused with a message naming the .zen replacement, not a generic "not a setting" error that leaves the operator guessing. Pinned in Task 3.
- **A fab-profile.json that mixes the 0.57 `allow_*` booleans with the new string tiers** for different via types (a project migrating gradually): both forms must resolve correctly per type. Pinned in Task 8.
- **An if-needed via type at a spot where share/move/drop *also* fail**: the refusal must name the if-needed possibility once, not loop or double-count via `_give`'s multiple call sites (it is called once for "already placed" vias and once for "its own" vias per candidate). Pinned in Task 11.
- **`placemat facts --confirm` must not change the run id.** A round trip (`run`, `facts --confirm`, `run` again) must produce the *same* run id when nothing else changed. Pinned in Task 12.

---

## Task 1: Per-layer copper thickness from the board's stackup

**Files:**
- Modify: `src/placemat/kicad/read.py` (add `_sexpr_tokens`, `_sexpr_parse`, `_find`, `_paren_block`, `_stackup_copper_mm`; wire into `board_geometry_of`; add public `read_layer_types`)
- Modify: `src/placemat/board_geometry.py` (add `BoardGeometry.copper_mm` field)
- Test: `tests/test_stackup_copper_mm.py` (new)

**Interfaces:**
- Produces: `BoardGeometry.copper_mm: dict[CopperLayer, float]` (mm; `{}` when the board declares no stackup) - consumed by Task 2.
- Produces: `read.read_layer_types(path) -> dict[str, str]` (KiCad layer name -> role: "signal"/"power"/"mixed"/"jumper") - consumed by Task 4.

- [ ] **Step 1: Write the failing test for the text-parsing helper**

```python
# tests/test_stackup_copper_mm.py
from placemat.kicad.read import _stackup_copper_mm
from placemat.values import CopperLayer

_STACKUP_TEXT = """(kicad_pcb (version 20240108)
  (setup
    (stackup
      (layer "F.SilkS" (type "Top Silk Screen"))
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "prepreg") (thickness 0.0994) (material "3313"))
      (layer "In1.Cu" (type "copper") (thickness 0.0152))
      (layer "dielectric 2" (type "core") (thickness 0.55) (material "FR4-Core"))
      (layer "B.Cu" (type "copper") (thickness 0.035))
      (layer "B.SilkS" (type "Bottom Silk Screen"))
      (copper_finish "ENIG")
    )
    (pad_to_mask_clearance 0)
  )
)
"""


def test_reads_each_copper_layers_thickness_in_mm(tmp_path):
    p = tmp_path / "board.kicad_pcb"
    p.write_text(_STACKUP_TEXT)
    assert _stackup_copper_mm(p) == {CopperLayer.F: 0.035, CopperLayer.IN1: 0.0152, CopperLayer.B: 0.035}


def test_a_board_with_no_stackup_section_gives_nothing(tmp_path):
    p = tmp_path / "board.kicad_pcb"
    p.write_text('(kicad_pcb (version 20240108) (setup (pad_to_mask_clearance 0)))\n')
    assert _stackup_copper_mm(p) == {}


def test_a_board_with_no_setup_section_gives_nothing(tmp_path):
    p = tmp_path / "board.kicad_pcb"
    p.write_text('(kicad_pcb (version 20240108))\n')
    assert _stackup_copper_mm(p) == {}
```

- [ ] **Step 2: Run it, confirm it fails on import**

Run: `cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/; PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_stackup_copper_mm.py`
Expected: FAIL - `ImportError: cannot import name '_stackup_copper_mm'`

- [ ] **Step 3: Implement the S-expression slice-and-parse in `src/placemat/kicad/read.py`**

Add near the top of the file, after the existing imports and before `mm()`:

```python
def _paren_block(text: str, start: int) -> str:
    """The balanced-parenthesis block of `text` beginning at index `start`
    ('('), respecting quoted strings so a stray paren in a name or comment
    does not end it early."""
    depth, i, n, in_str = 0, start, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:]


def _sexpr_tokens(text: str) -> list:
    import re
    return re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)


def _sexpr_parse(tokens: list):
    """One S-expression from the front of `tokens` (consumed in place): a
    list for a parenthesised form, a bare string for a quoted token (quotes
    stripped), else the raw token text."""
    tok = tokens.pop(0)
    if tok == "(":
        items = []
        while tokens[0] != ")":
            items.append(_sexpr_parse(tokens))
        tokens.pop(0)
        return items
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1]
    return tok


def _find(node, name: str):
    """The first sub-list of `node` whose head is `name`, depth first, or
    None. `node` itself counts."""
    if isinstance(node, list) and node and node[0] == name:
        return node
    if isinstance(node, list):
        for child in node:
            found = _find(child, name)
            if found is not None:
                return found
    return None


def _stackup_copper_mm(path) -> dict:
    """Each copper layer's thickness in mm, from the board's own stackup
    (the .kicad_pcb's `(setup (stackup ...))`), read from the file's text:
    this KiCad 10 pcbnew build does not wrap BOARD_STACKUP in Python
    (verified: GetStackupDescriptor() returns a bare SwigPyObject with no
    usable methods, and pcbnew.BOARD_STACKUP is None). {} when the file
    declares no stackup - an older board, or one the .zen gave the stdlib's
    default for."""
    text = Path(path).read_text(errors="replace")
    m = re.search(r"\(setup\b", text)
    if not m:
        return {}
    setup_text = _paren_block(text, m.start())
    sm = re.search(r"\(stackup\b", setup_text)
    if not sm:
        return {}
    stackup_text = _paren_block(setup_text, sm.start())
    tree = _sexpr_parse(_sexpr_tokens(stackup_text))
    out = {}
    for item in tree[1:]:
        if not (isinstance(item, list) and len(item) >= 2 and item[0] == "layer"):
            continue
        kind = _find(item, "type")
        if kind is None or len(kind) < 2 or kind[1] != "copper":
            continue
        thickness = _find(item, "thickness")
        if thickness is None or len(thickness) < 2:
            continue
        try:
            layer = CopperLayer.of(item[1])
        except ValueError:
            continue
        try:
            out[layer] = float(thickness[1])
        except ValueError:
            continue
    return out
```

Add `import re` to the top-level imports (the file currently imports `Path` only from stdlib at module scope - add `import re` beside it).

- [ ] **Step 4: Run the test, confirm it passes**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_stackup_copper_mm.py`
Expected: PASS (3 tests)

- [ ] **Step 5: Add `copper_mm` to `BoardGeometry` and wire the reader in**

In `src/placemat/board_geometry.py`, add a field next to `layer_types` (around line 244):

```python
    copper_mm: dict = field(default_factory=dict, compare=False)  # CopperLayer -> the board's own stackup thickness, mm; {} when the board declares none
```

In `src/placemat/kicad/read.py`'s `board_geometry_of`, add `copper_mm=_stackup_copper_mm(path)` to the final `BoardGeometry(...)` constructor call (the one ending in `layer_types=_layer_types(board))`).

- [ ] **Step 6: Add `read_layer_types` (a light read, no full geometry) for Task 4**

Add after `read_outline` in `src/placemat/kicad/read.py`:

```python
def read_layer_types(path) -> dict:
    """Each enabled copper layer's role (signal, power, mixed, jumper), by
    its KiCad name - a light read for a caller that wants only the roles,
    not the whole board geometry."""
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(path))
    if board is None:
        return {}
    return {layer.value: role for layer, role in _layer_types(board).items()}
```

- [ ] **Step 7: Write a failing test that a real read picks up `copper_mm` (using the existing board-geometry-read test pattern)**

Read `tests/test_board_geometry_read.py` first to match its existing fixture-board pattern (how it builds or loads a `.kicad_pcb` for `read_board`/`board_geometry_of`). Add a test in that file (or a new `tests/test_layer_types_read.py` if the existing file does not build boards through pcbnew directly - check first) asserting that a board built with a `(setup (stackup ...))` block (reuse the KiCad-write path already used by other kicad-backed tests to produce a real `.kicad_pcb`, or write one via pcbnew's `BOARD.GetDesignSettings().GetStackupDescriptor()`-free route by hand-writing the stackup text into a board pcbnew otherwise wrote) round-trips through `read_board(path).copper_mm`. Since the existing test suite already has real-pcbnew-backed fixtures for `layer_types` (see any test importing `read_board` and asserting on `.layer_types`), follow that exact pattern for `.copper_mm` instead. Keep the test board synthetic (no project names): a 2-4 layer board.

- [ ] **Step 8: Run, confirm it fails for the right reason (no `copper_mm` populated), then confirm `board_geometry_of` change makes it pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_stackup_copper_mm.py tests/test_board_geometry_read.py`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/placemat/kicad/read.py src/placemat/board_geometry.py tests/test_stackup_copper_mm.py tests/test_board_geometry_read.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Board geometry reads each copper layer's own stackup weight

Parsed from the .kicad_pcb's own setup/stackup text, since this KiCad
10 pcbnew build does not wrap BOARD_STACKUP in Python. read_layer_types
gives a caller the layer roles alone, for the route step's default.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

## Task 2: Current-path check judges copper by its own layer's weight

**Files:**
- Modify: `src/placemat/checks.py`
- Test: `tests/test_checks.py`, `tests/test_current_path_pairs.py` (add cases; do not break existing ones)

**Interfaces:**
- Consumes: `BoardGeometry.copper_mm` (Task 1).
- Produces: `ipc2221_width_mm(current_a, rise_c=TRACK_RISE_C, copper_oz=COPPER_OZ, k=_IPC_K_OUTER)` - the `k` parameter is new and optional; every existing call keeps working unchanged.
- Produces: `current_paths(geometry, rise_c=TRACK_RISE_C, zone_step=ZONE_STEP)` - **drops `copper_oz`**, reads `geometry.copper_mm` per bottleneck layer instead.
- Produces: `run_checks(geometry, ambient_c=AMBIENT_C, keep_out_mm=KEEP_OUT_MM, rise_c=TRACK_RISE_C, limits=None, zone_step=ZONE_STEP)` - **drops `copper_oz`**.
- Produces: `kwargs_from(settings)` - **drops the `"copper_oz"` key**.

- [ ] **Step 1: Write the failing test for the inner-layer constant**

Add to `tests/test_checks.py` (near the existing `ipc2221_width_mm` tests around line 91):

```python
def test_ipc2221_width_mm_takes_the_inner_constant():
    from placemat.checks import _IPC_K_INNER, _IPC_K_OUTER
    outer = ipc2221_width_mm(3.0, rise_c=10.0, copper_oz=1.0)
    inner = ipc2221_width_mm(3.0, rise_c=10.0, copper_oz=1.0, k=_IPC_K_INNER)
    assert inner > outer          # the inner constant (0.024) needs more area than the outer (0.048) for the same current
    assert _IPC_K_INNER == 0.024 and _IPC_K_OUTER == 0.048
```

Add to `tests/test_current_path_pairs.py` (read the file first for its exact `footprint`/`track`/`board_geometry` fixture helpers and its `_v`/`_sw`-style local helper that calls `current_paths`, matching its style precisely) a test that a bottleneck track on an inner layer is judged with the inner constant and that inner layer's own thickness:

```python
def test_an_inner_layers_bottleneck_uses_its_own_weight_and_the_inner_constant():
    import dataclasses
    from placemat.checks import ipc2221_width_mm, _IPC_K_INNER
    from placemat.values import CopperLayer
    u = footprint("U1", 10, 10, w=2, h=2, nets=("SW", "SW"))
    q = footprint("Q1", 30, 10, w=2, h=2, nets=("SW", "SW"))
    narrow = track("SW", 12, 10, 28, 10, w=0.3, layer=CopperLayer.IN1, owner="Q1")
    g = dataclasses.replace(board_geometry([u, q], copper=[narrow]),
                            layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.B),
                            copper_mm={CopperLayer.IN1: 0.0152})
    u_fields = dataclasses.replace(u, fields={"Pm.I": "vin:3A", "Pm.Role": "source"})
    # give both parts current so the pair is judged: reuse the module's existing
    # current-facts convention (Pm.I on each) rather than inventing a new one
    verdicts = {v.subject: v for v in current_paths(g)} if False else None  # placeholder removed below
```

Replace that last incomplete block: read `tests/test_current_path_pairs.py`'s actual working example (e.g. its `_sw` helper near the top of the file) and copy its exact pattern for giving two parts current on a shared net, then assert:

```python
    v = _sw([u, q], [narrow])   # using the file's own helper, substituting the inner track above
    assert v.limit == pytest.approx(ipc2221_width_mm(v_amps_used_by_helper, 10.0, _copper_mm_default_oz, k=_IPC_K_INNER))
```

(This step's exact assertion values depend on the file's existing helper's default current and rise - read it first and match precisely; the fixed points are: (a) the bottleneck is drawn on `CopperLayer.IN1`, (b) `g.copper_mm = {CopperLayer.IN1: 0.0152}`, (c) `v.limit` must come out larger than the outer-constant limit for the same current, since the inner constant is smaller and the required cross-section is inversely related to it.)

- [ ] **Step 2: Run, confirm both new tests fail for the right reason**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_checks.py::test_ipc2221_width_mm_takes_the_inner_constant tests/test_current_path_pairs.py::test_an_inner_layers_bottleneck_uses_its_own_weight_and_the_inner_constant`
Expected: FAIL - `TypeError: ipc2221_width_mm() got an unexpected keyword argument 'k'` for the first; `AttributeError`/`TypeError` for the second (no `copper_mm` field/kwarg yet, or wrong required-width value).

- [ ] **Step 3: Implement in `src/placemat/checks.py`**

Add the inner constant and a default-thickness constant near `_IPC_K_OUTER`:

```python
_IPC_K_OUTER = 0.048            # IPC-2221 external layer constant
_IPC_K_INNER = 0.024            # IPC-2221 internal layer constant
DEFAULT_COPPER_MM = 0.035
"""1 oz copper, mm: what a piece of copper on a layer the board's stackup
does not name is judged as (a board with no declared stackup, or a layer
missing from it)."""
```

Update `ipc2221_width_mm`:

```python
def ipc2221_width_mm(current_a: float, rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ,
                     k: float = _IPC_K_OUTER) -> float:
    """IPC-2221 width for a current at a temperature rise, on copper of the
    given weight: the outer constant unless `k` names the inner one."""
    area_milsq = (current_a / (k * rise_c ** 0.44)) ** (1 / 0.725)
    return area_milsq / (_MIL_PER_OZ * copper_oz) * _MM_PER_MIL
```

Add `CopperLayer` to the `.values` import at the top of the file: `from .values import Box, CopperLayer`.

Add a layer-weight helper after `ipc2221_width_mm`:

```python
def _layer_weight(layers: frozenset, copper_mm: dict) -> tuple:
    """(k, copper_oz) IPC-2221 judges copper on `layers` by: the outer
    constant and the thicker of F/B's own weight when an outer face is
    among them (a pad or a through node may claim both faces), else the
    inner constant and that inner layer's own weight. A layer missing from
    the board's stackup defaults to 1 oz (DEFAULT_COPPER_MM)."""
    outer = layers & {CopperLayer.F, CopperLayer.B}
    if outer:
        thickness_mm = max(copper_mm.get(l, DEFAULT_COPPER_MM) for l in outer)
        return _IPC_K_OUTER, thickness_mm / (_MIL_PER_OZ * _MM_PER_MIL)
    if not layers:
        return _IPC_K_OUTER, DEFAULT_COPPER_MM / (_MIL_PER_OZ * _MM_PER_MIL)
    layer = next(iter(layers))
    thickness_mm = copper_mm.get(layer, DEFAULT_COPPER_MM)
    return _IPC_K_INNER, thickness_mm / (_MIL_PER_OZ * _MM_PER_MIL)
```

Add a small helper next to `_neck` that finds only the bottleneck node's layers (used before `_neck` itself is called, since `need` must be known to rank judged candidates):

```python
def _neck_layers(nodes, path: list, w: float) -> frozenset:
    """The layers of the node on `path` (source to target, as `_route`
    gives it) whose own width is `w`: the same node `_neck` will later
    name as the bottleneck."""
    idx = next(n for n in path if abs(nodes[n][1] - w) < 1e-6)
    return nodes[idx][4]
```

Change `_pairs`'s signature and its tail (replace the `copper_oz: float` parameter with `copper_mm: dict`, and move the `need` computation after `layers` is known):

```python
def _pairs(geometry: BoardGeometry, net: str, carriers: dict, rise_c: float, copper_mm: dict,
           zone_step: float = ZONE_STEP):
```

Inside the loop, replace:
```python
        amps = carriers[a] if b is None else min(carriers[a], carriers[b])
        need = ipc2221_width_mm(amps, rise_c, copper_oz)
        if narrows:
            judged.append((width, need, amps, start, to, (fill[0], fill[2], True), fill[1], None))
            continue
        point, length, in_pour = _neck(nodes, best, end_i, w)
        judged.append((w, need, amps, start, to, None if fill is None else (fill[0], fill[2], False), point,
                       None if in_pour else length))
```
with:
```python
        amps = carriers[a] if b is None else min(carriers[a], carriers[b])
        layers = fill[3] if narrows else _neck_layers(nodes, _route(best, end_i), w)
        k, oz = _layer_weight(layers, copper_mm)
        need = ipc2221_width_mm(amps, rise_c, oz, k)
        weight_note = "%.3g oz %s" % (oz, "inner" if k == _IPC_K_INNER else "outer")
        if narrows:
            judged.append((width, need, amps, start, to, (fill[0], fill[2], True), fill[1], None, weight_note))
            continue
        point, length, in_pour = _neck(nodes, best, end_i, w)
        judged.append((w, need, amps, start, to, None if fill is None else (fill[0], fill[2], False), point,
                       None if in_pour else length, weight_note))
```

`_fill_on` must also return the zone's layers as a 4th element:

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

Update `current_paths` to drop `copper_oz`, pass `geometry.copper_mm`, and unpack the widened judged tuple:

```python
def current_paths(geometry: BoardGeometry, rise_c: float = TRACK_RISE_C,
                  zone_step: float = ZONE_STEP) -> list[Verdict]:
    f = facts(geometry)
    carriers: dict[str, dict] = {}
    for fp in geometry.footprints:
        fact = f[fp.ref]
        for p in fp.pads:
            amps = fact.current_a if fact.currents is None else fact.currents.get(p.net.lower())
            if amps is not None and amps > 0:
                on = carriers.setdefault(p.net, {})
                on[fp.ref] = max(on.get(fp.ref, 0.0), amps)
    out = []
    for net, on in sorted(carriers.items()):
        if len(on) == 1:
            (ref, amps), = on.items()
            out.append(Verdict("current-path", net, 0.0, "mm", ipc2221_width_mm(amps, rise_c), None,
                               "not judged (%g A): only %s carries current on %s, so where its load goes is "
                               "not known; give the part that takes the load its Pm.I" % (amps, ref, net)))
            continue
        judged, unmeasured, apart = _pairs(geometry, net, on, rise_c, geometry.copper_mm, zone_step)
        said = ["no copper joins %s %s on %s yet" % (a, "and %s" % b if b else "to another part", net)
                for a, b in apart]
        said += ["%s to %s: %s" % (a, b, why) for a, b, why in unmeasured]
        if not judged:
            amps = max(on.values())
            out.append(Verdict("current-path", net, 0.0, "mm", ipc2221_width_mm(amps, rise_c), None,
                               "not judged (%g A): %s" % (amps, "; ".join(said))))
            continue
        w, need, amps, a, b, fill, point, length, weight_note = min(judged, key=lambda j: j[0] / j[1])
        note = "narrowest point of the load's widest route, %s to %s, for %g A at %g C rise, %s" % (
            a, b, amps, rise_c, weight_note)
        if fill is not None and fill[2]:
            note += "; neck at (%.2f, %.2f), the fill's narrowest point" % point
            if fill[1]:
                note += " (one %g mm step or less wide there, read as one step)" % zone_step
        else:
            note += "; neck at (%.2f, %.2f), %s" % (point[0], point[1], "the pour's narrowest point" if length is None
                                                    else "%.2f mm long" % length)
            if fill is not None:
                note += "; through a zone fill %.2f mm wide at its narrowest" % fill[0]
        out.append(Verdict("current-path", net, w, "mm", need, w >= need, note + ("; " + "; ".join(said) if said else "")))
    return out
```

Update `run_checks` and `kwargs_from` to drop `copper_oz`:

```python
def run_checks(geometry: BoardGeometry, ambient_c: float = AMBIENT_C, keep_out_mm: float = KEEP_OUT_MM,
               rise_c: float = TRACK_RISE_C, limits: dict[str, float] | None = None,
               zone_step: float = ZONE_STEP) -> list[Verdict]:
    limits = limits or {}
    out = []
    for loop in hot_loops(geometry):
        ...   # unchanged
    for node in switch_nodes(geometry):
        ...   # unchanged
    out += keep_out(geometry, keep_out_mm)
    out += crossings_under(geometry)
    out += current_paths(geometry, rise_c, zone_step)
    out += heat(geometry, ambient_c)
    return out


def kwargs_from(settings) -> dict:
    return {"ambient_c": settings.check_ambient_c, "keep_out_mm": settings.check_keep_out_mm,
            "rise_c": settings.check_rise_c, "limits": dict(settings.check_limits), "zone_step": settings.check_zone_step}
```

Update the `COPPER_OZ` module docstring (it currently says "The default for `[check] copper_oz` and `--copper-oz`." - both retire in Task 3): change to "The default weight for a layer the board's stackup does not name (`DEFAULT_COPPER_MM`); kept for `ipc2221_width_mm`'s own default." Leave the `COPPER_OZ` constant itself in place (still the pure function's default `copper_oz` value, and existing tests pass `copper_oz=1.0` explicitly).

- [ ] **Step 4: Run the two new tests, then the whole current-path test files**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_checks.py tests/test_current_path_neck.py tests/test_current_path_pairs.py tests/test_current_path_zone_width.py`
Expected: PASS, all of them (existing tests must keep passing unmodified in behavior - a 2-layer, all-outer-copper fixture always resolves `_layer_weight` to the outer constant and 1 oz by default, matching every existing expectation).

If any existing test fails: it is almost certainly a call site still passing `copper_oz=` to `current_paths`/`run_checks`/`kwargs_from` - grep `tests/` for `current_paths(.*copper_oz` and `run_checks(.*copper_oz` and fix each call site to drop the argument (its correctness is unaffected: 1 oz outer is still the default for an all-outer-copper board).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/checks.py tests/test_checks.py tests/test_current_path_pairs.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Current-path check judges each piece of copper by its own layer's weight

Inner copper is sized by IPC-2221's inner constant against the board's
own stackup thickness for that layer; check.copper_oz is no longer read
here (retired in a later commit). A layer the stackup does not name
defaults to 1 oz.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 3: Retire `[check] copper_oz`, `[route] layers`, `[route] diff_pairs`; add `score.via_shorten`

**Files:**
- Modify: `src/placemat/settings.py`
- Modify: `src/placemat/cli.py` (`overrides_from`, remove `ck.add_argument("--copper-oz", ...)`)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` with `check_copper_oz`, `route_layers`, `route_diff_pairs` fields **removed**, `score_via_shorten: float = 5.0` **added**.
- Produces: a placemat.toml setting either of the three retired keys raises `SettingsError` naming its .zen replacement.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_settings.py` first for its existing "a placemat.toml with a bad key is refused" test pattern (it will use `tmp_path`, write a `placemat.toml`, and call `load(tmp_path)` expecting `pytest.raises(SettingsError, match=...)`). Add, matching that pattern exactly:

```python
def test_retired_keys_name_their_zen_replacement(tmp_path):
    from placemat.settings import SettingsError, load
    (tmp_path / "placemat.toml").write_text('[check]\ncopper_oz = 1.0\n')
    with pytest.raises(SettingsError, match="stackup"):
        load(tmp_path)
    (tmp_path / "placemat.toml").write_text('[route]\nlayers = ["F.Cu", "B.Cu"]\n')
    with pytest.raises(SettingsError, match="role"):
        load(tmp_path)
    (tmp_path / "placemat.toml").write_text('[route]\ndiff_pairs = ["*"]\n')
    with pytest.raises(SettingsError, match="net class"):
        load(tmp_path)


def test_via_shorten_has_a_default_and_a_floor(tmp_path):
    from placemat.settings import Settings, SettingsError, load
    assert Settings().score_via_shorten == 5.0
    (tmp_path / "placemat.toml").write_text('[score]\nvia_shorten = -1.0\n')
    with pytest.raises(SettingsError, match="via_shorten"):
        load(tmp_path)
```

- [ ] **Step 2: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings.py::test_retired_keys_name_their_zen_replacement tests/test_settings.py::test_via_shorten_has_a_default_and_a_floor`
Expected: FAIL (both keys still accepted today; `score_via_shorten` does not exist).

- [ ] **Step 3: Implement in `src/placemat/settings.py`**

Remove these three lines from the `Settings` dataclass:
```python
    check_copper_oz: float = 1.0
```
(from the `[check]` block) and
```python
    route_layers: tuple | None = None
```
and
```python
    route_diff_pairs: tuple = ("*",)    # nets the router's pair router routes first, as pairs; "NET_A/NET_B" names one pair (P first); (): none
```
(both from the `[route]` block).

Add, in the `[score]` block next to `score_via_share`/`score_via_move`/`score_via_drop`:
```python
    score_via_shorten: float = 5.0      # a drop reshaped face-to-nearest-plane-layer, between move and drop
```

Remove `"check_copper_oz"` from the `_ABOVE_ZERO` frozenset. Add `"score_via_shorten"` to the `_AT_LEAST_ZERO` frozenset (beside `"score_via_drop"`).

Remove the whole `if name == "route_diff_pairs":` validation block from `_validate` (it called `pairs.explicit_pairs`, now unused there - Task 6 removes the underlying call from `pairs.py`'s public surface for this purpose, but `explicit_pairs` itself stays, used elsewhere; do not touch `pairs.py` in this task).

Add a retirement table above `_flatten` and check it inside `_flatten`, before the "not a setting placemat has" branch:

```python
# A key .zen board facts replaced: refused by name, with what replaced it,
# rather than the generic "not a setting" error - a project migrating from
# 0.57 needs to be told where the fact moved to, not just that it is gone.
_RETIRED = {
    "check_copper_oz": "copper weight now comes from the board's own stackup "
                       "(BoardConfig's CopperLayer weight in the .zen)",
    "route_layers": "route layers now come from each layer's own role "
                    "(BoardConfig's CopperLayer role in the .zen); "
                    "`placemat route --layers` still overrides for one run",
    "route_diff_pairs": "differential pairs now come from the board's net classes "
                        "(a NetClass's diff_pair_width, diff_pair_gap and nets in the .zen)",
}
```

In `_flatten`, inside the `for key, value in body.items():` loop, right after `name = join_key(section, key)` and before the `if name not in known:` check:

```python
            if name in _RETIRED:
                raise SettingsError("%s: %s.%s is retired; %s" % (path, section, key, _RETIRED[name]))
```

- [ ] **Step 4: Update `src/placemat/cli.py`**

In `overrides_from` (around line 262-277), remove the `("copper_oz", "check_copper_oz")` tuple from the loop over flag/name pairs, leaving `("ambient", "check_ambient_c"), ("keep_out", "check_keep_out_mm"), ("rise", "check_rise_c")`.

In the `check` subparser definition, remove:
```python
    ck.add_argument("--copper-oz", type=float, default=None, help="outer copper weight the widths are sized for")
```

- [ ] **Step 5: Run the settings tests and the check-command tests**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings.py tests/test_settings_wiring.py tests/test_checks_wiring.py tests/test_cli_output.py`
Expected: PASS. If `test_checks_wiring.py` or another file calls `overrides_from`/passes `--copper-oz` on the CLI, update that call site to remove it (the flag no longer exists).

- [ ] **Step 6: Commit**

```bash
git add src/placemat/settings.py src/placemat/cli.py tests/test_settings.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Retire check.copper_oz, route.layers and route.diff_pairs from placemat.toml

Each is refused by name, citing the .zen field that replaces it.
score.via_shorten prices give way's new fourth way.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 4: Route step's default layer list comes from each layer's role

**Files:**
- Modify: `src/placemat/kicad/route.py`
- Test: `tests/test_route_plane_layers.py`, `tests/test_route_settings.py`

**Interfaces:**
- Consumes: `read.read_layer_types(path)` (Task 1).
- Produces: `resolved_layers(explicit, board_layers, layer_types) -> (list[str], dict[str, str])` - **signature changed** from `(explicit, all_layers, zones, board_area, share)`.
- Produces: `plane_note(dropped: dict) -> str` - same signature, new wording (role, not net).

- [ ] **Step 1: Read the existing tests to match fixture style**

Read `tests/test_route_plane_layers.py` in full (it is the test file for `resolved_layers`/`plane_layers`/`plane_note` today) and `tests/test_route_settings.py` for any `route.layers`/`route_layers` references that will now fail to parse (Task 3 already refuses `[route] layers` in placemat.toml - any test writing that key to a `placemat.toml` fixture must be updated to use the `layers=` explicit-argument path or removed if it specifically tested the now-retired setting).

- [ ] **Step 2: Write the failing test for role-based defaults**

Add to `tests/test_route_plane_layers.py`:

```python
def test_the_default_routes_signal_and_mixed_layers_f_and_b_always():
    from placemat.kicad.route import resolved_layers
    board_layers = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]
    types = {"F.Cu": "signal", "In1.Cu": "power", "In2.Cu": "signal", "In3.Cu": "power",
            "In4.Cu": "power", "B.Cu": "signal"}
    layers, dropped = resolved_layers(None, board_layers, types)
    assert layers == ["F.Cu", "In2.Cu", "B.Cu"]
    assert dropped == {"In1.Cu": "power", "In3.Cu": "power", "In4.Cu": "power"}


def test_an_explicit_list_is_used_as_given():
    from placemat.kicad.route import resolved_layers
    layers, dropped = resolved_layers(["In1.Cu"], ["F.Cu", "In1.Cu", "B.Cu"], {"In1.Cu": "power"})
    assert layers == ["In1.Cu"] and dropped == {}


def test_plane_note_names_the_role():
    from placemat.kicad.route import plane_note
    text = plane_note({"In1.Cu": "power", "In4.Cu": "power"})
    assert "In1.Cu, In4.Cu" in text and "power" in text and "placemat route --layers" in text
    assert plane_note({}) == ""
```

- [ ] **Step 3: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_route_plane_layers.py -k "role_based or explicit_list or plane_note_names"`
Expected: FAIL (`resolved_layers` still takes the old 5-argument signature; `TypeError`).

- [ ] **Step 4: Implement in `src/placemat/kicad/route.py`**

Replace `resolved_layers`:

```python
def resolved_layers(explicit, board_layers, layer_types) -> tuple:
    """The layers to route on, and what the default left out and why
    ({layer: role}). An explicit list (an argument only now - `[route]
    layers` is retired; `placemat route --layers` is the sole override) is
    used as given. Left to itself, every layer whose role is signal or
    mixed, F.Cu and B.Cu always among them - a real board's floor of two
    layers, so this never routes on fewer than that either."""
    if explicit:
        return list(explicit), {}
    kept, dropped = [], {}
    for l in board_layers:
        role = layer_types.get(l, "signal")
        if l in ("F.Cu", "B.Cu") or role in ("signal", "mixed"):
            kept.append(l)
        else:
            dropped[l] = role
    return kept, dropped
```

Replace `plane_note`:

```python
def plane_note(dropped: dict) -> str:
    """The route step's line for what the default layer list left out and
    why (its role), and how to override it."""
    if not dropped:
        return ""
    groups: dict = {}
    for layer in sorted(dropped):
        groups.setdefault(dropped[layer], []).append(layer)
    parts = []
    for role, layers in sorted(groups.items()):
        pronoun = "it" if len(layers) == 1 else "them"
        parts.append("%s left out, role %s" % (", ".join(layers), role))
    return "route layers: " + "; ".join(parts) + "; placemat route --layers to override"
```

In `route_board`, remove the line that fell back to the retired setting:
```python
    layers = layers if layers is not None else (list(cfg.route_layers) if cfg.route_layers else None)
```
(delete it entirely - `layers` is already the function's own parameter, explicit-only now).

Change the block that decides `all_layers`/`zones`/`board_area` (used by `resolved_layers` today) to also fetch layer types when `layers` is not given, and pass them to `resolved_layers` instead of `zones, board_area, share`:

```python
    if layers:
        all_layers, zones, board_area, layer_types = [], (), 0.0, {}
    else:
        all_layers = _copper_layers(str(pcb_in))
        zones, board_area = _plane_zones(str(pcb_in))
        from .read import read_layer_types
        layer_types = read_layer_types(str(pcb_in))
    layers, plane_dropped = resolved_layers(layers, all_layers, layer_types)
```

Leave every other use of `zones`, `board_area`, `cfg.route_plane_share` untouched (`guard_partial_pours` still uses them for pour-guarding, a separate concern from the default layer list - `[route] plane_share` is not retired).

- [ ] **Step 5: Run the full route-layers/route-settings test files**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_route_plane_layers.py tests/test_route_settings.py tests/test_route_command.py`
Expected: PASS. Fix any remaining call site in these files still using `resolved_layers`'s old signature or asserting the old "the X plane fills it" wording from `plane_note`.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/kicad/route.py tests/test_route_plane_layers.py tests/test_route_settings.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Route layers default to each layer's own role, not plane coverage

Every signal or mixed layer, F.Cu and B.Cu always; placemat route
--layers still overrides for one run. Pour-guarding by plane coverage
(route.plane_share) is unchanged - a separate concern.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 5: `pairs.board_pairs` - differential pairs from the board's net classes

**Files:**
- Modify: `src/placemat/pairs.py`
- Test: `tests/test_pairs.py`

**Interfaces:**
- Consumes: `board_geometry.NetClass` (existing: `name`, `diff_pair_width`, `diff_pair_gap`).
- Produces: `board_pairs(netclasses: dict[str, NetClass]) -> dict[str, str]` (both directions, like `pairs_of`).
- Produces: `board_pair_list(netclasses: dict[str, NetClass]) -> list[tuple[str, str]]` (each pair once, P first where `pair_key` says which half is positive).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pairs.py`:

```python
from placemat.board_geometry import NetClass
from placemat.pairs import board_pairs, board_pair_list

_DEFAULT = NetClass("Default", 0.2, 0.2, 0.6, 0.3, 0.2, 0.2)   # a real board's Default: diff pair fields are NOT null


def _cls(name, nets, width=0.1, gap=0.1):
    return {n: NetClass(name, 0.2, 0.2, 0.6, 0.3, width, gap) for n in nets}


def test_a_two_net_class_pairs_whatever_they_are_called():
    classes = {**_cls("Tank", ["LX", "LY"])}
    assert board_pairs(classes) == {"LX": "LY", "LY": "LX"}


def test_a_four_net_class_pairs_by_pair_key():
    classes = {**_cls("HighSpeed", ["CLK_P", "CLK_N", "DAT_P", "DAT_N"])}
    assert board_pairs(classes) == {"CLK_P": "CLK_N", "CLK_N": "CLK_P", "DAT_P": "DAT_N", "DAT_N": "DAT_P"}


def test_the_default_class_never_makes_pairs():
    classes = {"A": _DEFAULT, "B": NetClass("Default", 0.2, 0.2, 0.6, 0.3, 0.2, 0.2)}
    assert board_pairs(classes) == {}


def test_a_board_with_no_pair_class_has_none():
    classes = {"A": NetClass("Default", 0.2, 0.2, 0.6, 0.3), "B": NetClass("Power", 0.3, 0.2, 0.6, 0.3)}
    assert board_pairs(classes) == {}


def test_board_pair_list_gives_each_pair_once_p_first():
    classes = {**_cls("HighSpeed", ["CLK_P", "CLK_N"])}
    assert board_pair_list(classes) == [("CLK_P", "CLK_N")]
    tank = {**_cls("Tank", ["LX", "LY"])}
    assert board_pair_list(tank) == [("LX", "LY")]   # no suffix meaning: alphabetically first is P
```

- [ ] **Step 2: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_pairs.py -k board_pairs`
Expected: FAIL - `ImportError: cannot import name 'board_pairs'`.

- [ ] **Step 3: Implement in `src/placemat/pairs.py`**

Add at the end of the file:

```python
def board_pairs(netclasses: dict) -> dict:
    """{net: its partner} from the board's own net classes: a class other
    than "Default" that sets diff_pair_width and diff_pair_gap groups its
    nets into pairs - exactly two nets pair whatever they are named; more
    than two pair within the class by pair_key, the same rule a suffix pair
    uses elsewhere. A board whose classes declare no pair class has none.

    A net class's diff_pair_width/gap are not reliably null for a class
    that was never meant as a pair (KiCad's own default netclass and an
    untouched one both report the project's default diff-pair figure, not
    None) - only the class name "Default" is excluded here, per the design
    this ports."""
    by_class: dict = {}
    for net, nc in netclasses.items():
        if nc.name == "Default" or nc.diff_pair_width is None or nc.diff_pair_gap is None:
            continue
        by_class.setdefault(nc.name, []).append(net)
    out = {}
    for nets in by_class.values():
        if len(nets) == 2:
            a, b = sorted(nets)
            out[a], out[b] = b, a
        elif len(nets) > 2:
            out.update(pairs_of(nets))
    return out


def board_pair_list(netclasses: dict) -> list:
    """[(p_net, n_net), ...] from board_pairs(), each pair once: P first
    when pair_key says which half is positive, else the alphabetically
    first net (a two-net class with no suffix meaning has no real P/N)."""
    d = board_pairs(netclasses)
    seen, out = set(), []
    for net in sorted(d):
        if net in seen:
            continue
        other = d[net]
        seen.add(net)
        seen.add(other)
        k = pair_key(net)
        out.append((net, other) if k is None or k[1] else (other, net))
    return out
```

- [ ] **Step 4: Run, confirm all pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_pairs.py`
Expected: PASS (all tests in the file, old and new).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pairs.py tests/test_pairs.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Differential pairs come from the board's own net classes

A class of exactly two nets pairs them whatever they are named; more
pair by pair_key within the class. The Default class never makes pairs.
Not yet wired to any caller - the next commit retires route.diff_pairs
from the four call sites that used it.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 6: Rewire the four pair-discovery call sites onto `board_pairs`

**Files:**
- Modify: `src/placemat/score.py`, `src/placemat/occupancy.py`, `src/placemat/report.py`, `src/placemat/runner.py`, `src/placemat/cli.py`, `src/placemat/kicad/route.py`
- Test: `tests/test_route_pairs.py`, `tests/test_pair_crossing.py`, `tests/test_explicit_pairs.py`

**Interfaces:**
- Consumes: `pairs.board_pairs`, `pairs.board_pair_list` (Task 5).
- Produces: `report.airwires_from_drc(drc, quiet=(), partners: dict | None = None)` - **`pair_patterns` parameter removed**, replaced by a precomputed `partners` dict.
- Produces: `kicad.route.route_pairs(rpy, router_dir_path, pcb_in, work, pairs, layers, cfg, iterations, probe, timeout, env)` - **`patterns` parameter renamed to `pairs`, now a `list[(p_net, n_net)]` directly** (no more glob strings, no `explicit_pairs`/`globs` split inside it).

- [ ] **Step 1: Read the three affected test files first**

Read `tests/test_route_pairs.py`, `tests/test_pair_crossing.py`, `tests/test_explicit_pairs.py` in full before writing anything, since this task's tests are edits to existing files whose exact fixture-building helpers must be matched.

- [ ] **Step 2: Write/adjust the failing tests for `score.py`/`occupancy.py`/`report.py`**

In `tests/test_pair_crossing.py` (or wherever `plan_measures`'s pair-crossing weighting is tested today - confirm by reading the file), change any placemat.toml or `Settings(route_diff_pairs=...)` construction that supplied pair patterns to instead build a `BoardGeometry` whose `netclasses` declare the pair (using `NetClass(name, ..., diff_pair_width=..., diff_pair_gap=...)` on the two nets, via `dataclasses.replace` on the fixture's `board_geometry(...)` result, mirroring Task 5's test style). Add one test that the crossing-pair weighting only fires when the board's net classes declare the pair (not from any setting):

```python
def test_pair_crossing_weight_comes_from_the_boards_net_classes(...):
    ...   # follow the file's existing fixture pattern; assert the same
          # crossing weight the file's other tests check for, but reached
          # via netclasses with diff_pair_width/gap set, not via a setting
```

- [ ] **Step 3: Implement `score.py`, `occupancy.py`, `report.py`, `runner.py`, `cli.py`**

In `src/placemat/score.py`, replace:
```python
    from .pairs import pairs_of
    partners = {n: m for n, m in pairs_of(by_net, tuple(board.settings.route_diff_pairs)).items()
                if n not in quiet and m not in quiet}
```
with:
```python
    from .pairs import board_pairs
    partners = {n: m for n, m in board_pairs(board.geometry.netclasses).items()
                if n not in quiet and m not in quiet}
```

In `src/placemat/occupancy.py`'s `ratsnest()` (around line 899-923), replace:
```python
            from .pairs import pairs_of
            from .ratsnest import Ratsnest
            weights = {n: self.settings.score_crossing_plane for n in self.quiet_nets}
            nets = {s.net for g in self.items.values() for s in g.shapes if s.net}
            partners = {n: m for n, m in pairs_of(nets, tuple(self.settings.route_diff_pairs)).items()
                        if n not in self.quiet_nets and m not in self.quiet_nets}
```
with:
```python
            from .pairs import board_pairs
            from .ratsnest import Ratsnest
            weights = {n: self.settings.score_crossing_plane for n in self.quiet_nets}
            partners = {n: m for n, m in board_pairs(self.geometry.netclasses).items()
                        if n not in self.quiet_nets and m not in self.quiet_nets}
```

In `src/placemat/report.py`, change `airwires_from_drc`'s signature and drop its internal `pairs_of` call:
```python
def airwires_from_drc(drc: dict, quiet=(), partners: dict | None = None) -> dict:
    """... `partners` ({net: its pair partner}, from pairs.board_pairs) ..."""
    edges = []
    for u in drc.get("unconnected_items", []):
        items = u.get("items", [])
        if len(items) < 2:
            continue
        a, b = items[0].get("pos", {}), items[1].get("pos", {})
        m = re.search(r"\[([^\]]+)\]", items[0].get("description", ""))
        net = m.group(1) if m else "?"
        edges.append((net, (a.get("x", 0.0), a.get("y", 0.0)), (b.get("x", 0.0), b.get("y", 0.0))))

    def cross(e, f):
        return segments_cross(e[1], e[2], f[1], f[2])

    crossings = quiet_crossings = pair_crossings = 0
    quiet = set(quiet)
    partners = partners or {}
    crossings_per_net: dict = {}
```
(delete the old `partners = pairs_of({e[0] for e in edges}, tuple(pair_patterns))` line; the rest of the function is unchanged).

In `src/placemat/runner.py` (around line 503-510), replace:
```python
            aw = airwires_from_drc(json.loads((run_dir / "drc.json").read_text()), quiet,
                                   tuple(board.settings.route_diff_pairs))
```
with:
```python
            from .pairs import board_pairs
            aw = airwires_from_drc(json.loads((run_dir / "drc.json").read_text()), quiet,
                                   board_pairs(board.geometry.netclasses))
```

In `src/placemat/cli.py`'s `cmd_drc`, reorder so the board is read once and its pairs computed before `airwires_from_drc`:
```python
def cmd_drc(args) -> int:
    from .kicad.drc import run_drc, unconnected_items, violation_items
    from .report import airwires_from_drc
    from .kicad.read import read_board
    from .pairs import board_pairs
    pcb = Path(args.pcb)
    out = pcb.parent / "drc.json"
    report = run_drc(pcb, out)
    data = json.loads(out.read_text())
    try:
        snap = read_board(pcb)
        insts = {fp.ref: fp.inst for fp in snap.footprints}
        partners = board_pairs(snap.netclasses)
    except Exception:                               # a board pcbnew cannot read has no instances or classes
        insts, partners = {}, {}
    aw = airwires_from_drc(data, partners=partners)
    items = violation_items(data, {}, insts)
```
(remove the old, now-duplicate `from .kicad.read import read_board` and `insts = ...` block further down that this replaces).

In `src/placemat/kicad/route.py`, replace `route_pairs`'s signature and body (the `patterns`/`explicit_pairs`/`globs` split):
```python
def route_pairs(rpy, router_dir_path, pcb_in: Path, work: Path, pairs, layers, cfg, iterations, probe,
                timeout, env) -> tuple:
    """Route the differential pairs `pairs` ([(p_net, n_net), ...], from
    pairs.board_pair_list): returns (the board to route the rest on,
    Pairs). No pairs comes back as it went in.

    The router pairs nets by their suffix alone, so every pair is routed in
    a copy where its nets are renamed to a suffix pair
    (pairs.pair_aliases), whatever they were called, and renamed back in
    the routed board before anything reads it."""
    from ..pairs import pair_aliases
    if not pairs:
        return pcb_in, Pairs()
    names = _net_names(pcb_in)
    missing = [n for pair in pairs for n in pair if n not in names]
    if missing:
        raise ValueError("the board's net classes name %s for a differential pair, which it has no net called"
                         % ", ".join(missing))
    aliases = pair_aliases(pairs, names)
    script = Path(router_dir_path) / "py_router/route_diff.py"
    if not script.exists():
        return pcb_in, Pairs()
    renames = {old: base + suffix for base, p, n in aliases for old, suffix in ((p, "_P"), (n, "_N"))}
    router_in = work / "pairs_in.kicad_pcb"
    shutil.copy(pcb_in, router_in)
    _copy_project(pcb_in, router_in)
    rename_nets(str(router_in), renames)
    back = {new: old for old, new in renames.items()}
    back.update({base: "%s/%s" % (p, n) for base, p, n in aliases})
    pcb_out = work / "pairs.kicad_pcb"
    cmd = pair_command(rpy, script, router_in, pcb_out, tuple(a[0] for a in aliases), layers,
                       cfg.route_diff_pair_gap, cfg.route_diff_pair_width, iterations, probe)
    log = work / "pairs.log"
    with open(log, "w") as f:
        f.write("$ %s\n\n" % " ".join(str(c) for c in cmd))
        f.flush()
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir_path), env=env,
                            timeout=timeout).returncode
    text = log.read_text(errors="replace")
    result_pairs = read_pairs(text).renamed(back)
    if rc != 0 or not pcb_out.exists():
        if "matched no differential pair" in text or "No differential pairs" in text:
            return pcb_in, Pairs()
        tail = "\n".join(text.splitlines()[-8:])
        raise RuntimeError("the pair router exited %d without a routed board; log %s\n%s" % (rc, log, tail))
    rename_nets(str(pcb_out), {new: old for old, new in renames.items()})
    for ext in (".kicad_pro", ".kicad_dru"):
        if (work / ("in" + ext)).exists():
            shutil.copy(work / ("in" + ext), work / ("pairs" + ext))
    lock_copper(str(pcb_out))
    return pcb_out, result_pairs
```

In `route_board`, replace the call:
```python
    board, pairs = route_pairs(rpy, router_dir_path, pcb_in, work, tuple(cfg.route_diff_pairs), layers, cfg,
                               iterations, probe, timeout, env)
```
with:
```python
    from .read import read_board
    from ..pairs import board_pair_list
    pair_list = board_pair_list(read_board(str(pcb_in)).netclasses)
    board, pairs = route_pairs(rpy, router_dir_path, pcb_in, work, pair_list, layers, cfg,
                               iterations, probe, timeout, env)
```

- [ ] **Step 4: Run every test file this task touches or could affect**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_route_pairs.py tests/test_pair_crossing.py tests/test_explicit_pairs.py tests/test_report.py tests/test_run_score.py tests/test_route_command.py tests/test_route_settings.py`
Expected: PASS. Fix any remaining call site still passing the old `patterns`/`pair_patterns` argument shape (grep `tests/` for `route_diff_pairs`, `pairs_of(`, `airwires_from_drc(` to find them all).

- [ ] **Step 5: Grep the whole source tree for any remaining `route_diff_pairs` reference and remove it**

Run: `grep -rn "route_diff_pairs" src/placemat/`
Expected: no hits outside `route_diff_pair_gap`/`route_diff_pair_width` (which stay - only the pair-selection setting retires, not the pair's track tuning). If any hit remains in `pairs.py`'s docstrings (the module docstring and `explicit_pairs`/`_names_pair`/`globs`/`pair_aliases` docstrings reference `route.diff_pairs` as their origin), update the wording to say these functions are now used only by the route step's own pair-to-suffix renaming, not by a placemat.toml setting.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/score.py src/placemat/occupancy.py src/placemat/report.py src/placemat/runner.py src/placemat/cli.py src/placemat/kicad/route.py src/placemat/pairs.py tests/test_route_pairs.py tests/test_pair_crossing.py tests/test_explicit_pairs.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Score, occupancy, drc reporting and the route step read pairs off the
board's net classes, not route.diff_pairs

route_pairs takes the pairs directly ([(p_net, n_net), ...]) and always
renames to a suffix pair before the external router sees them - the
named/pattern split it used for route.diff_pairs entries is gone with
the setting.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 7: New finding kinds - `fab`, `facts`, `needs`

**Files:**
- Modify: `src/placemat/findings.py`
- Modify: `tests/test_finding_kinds.py`

**Interfaces:**
- Produces: `findings.KINDS` including `"fab"`, `"facts"`, `"needs"`.

- [ ] **Step 1: Write the failing test**

Modify the existing assertion in `tests/test_finding_kinds.py` (`test_a_finding_is_its_text_and_carries_its_kind`, around line 35):

```python
    assert set(KINDS) == {"unplaced", "link_over", "fixed", "copper", "label", "escape_crossed", "pair_crossed",
                          "escape_closed", "escape_walled", "setup", "route", "vias", "fab", "facts", "needs"}
```

- [ ] **Step 2: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_finding_kinds.py::test_a_finding_is_its_text_and_carries_its_kind`
Expected: FAIL - the sets differ.

- [ ] **Step 3: Implement in `src/placemat/findings.py`**

Add to the `KINDS` tuple:

```python
    "fab",              # a board rule (a net class's track, clearance or via) below the fab profile's minimum
    "facts",            # the board's facts do not match what `placemat facts --confirm` last confirmed
    "needs",            # a spot placemat would have used an if-needed fab option for, and did not
```

- [ ] **Step 4: Run the full finding-kinds test file**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_finding_kinds.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/findings.py tests/test_finding_kinds.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Finding kinds fab, facts and needs

fab: a board rule below the fab profile's minimum. facts: unconfirmed
board facts. needs: an if-needed fab option that was judged but not used.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 8: `fab-profile.json` - fixed/preferred via types and a `min` section

**Files:**
- Modify: `src/placemat/project.py`
- Test: `tests/test_project.py`, `tests/test_via_types_allowed.py`

**Interfaces:**
- Produces: `FabProfile.via_tiers: dict[str, str]` ("micro"/"blind"/"buried" -> "yes"/"no"/"if-needed"; `FabProfile.tier(kind) -> str`, default `"no"`).
- Produces: `FabProfile.min: dict[str, float]` (`track_mm`, `clearance_mm`, `drill_mm`, `annular_mm`, `via_size_mm`; `{}` when the file declares none).
- Produces: `FabProfile.via_types` **stays** (now a computed property: the tiers at `"yes"`), so `FabProfile.json()`'s digest is unaffected for an old-style profile.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_project.py`:

```python
def test_via_tiers_read_the_new_string_form(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps(
        {"via": {"micro": "no", "blind": "if-needed", "buried": "no"}}))
    fab = fab_profile(tmp_path)
    assert fab.tier("micro") == "no" and fab.tier("blind") == "if-needed" and fab.tier("buried") == "no"
    assert fab.via_types == frozenset()          # no type is "yes"


def test_via_tiers_read_the_057_allow_booleans(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {"allow_blind": True, "allow_micro": False}}))
    fab = fab_profile(tmp_path)
    assert fab.tier("blind") == "yes" and fab.tier("micro") == "no" and fab.tier("buried") == "no"


def test_a_type_the_file_does_not_name_is_no(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {}}))
    fab = fab_profile(tmp_path)
    assert fab.tier("micro") == "no" and fab.tier("blind") == "no" and fab.tier("buried") == "no"


def test_min_is_read_and_defaults_to_empty(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps(
        {"min": {"track_mm": 0.09, "clearance_mm": 0.09, "drill_mm": 0.15, "annular_mm": 0.075, "via_size_mm": 0.25}}))
    fab = fab_profile(tmp_path)
    assert fab.min == {"track_mm": 0.09, "clearance_mm": 0.09, "drill_mm": 0.15, "annular_mm": 0.075, "via_size_mm": 0.25}
    assert fab_profile(Path("/")).min == {}


def test_new_style_profile_with_no_new_keys_digests_as_before(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {"micro": "no"}}))
    fab = fab_profile(tmp_path)
    old = fab_profile(Path("/"))
    assert fab.json() == old.json()        # a profile with no "yes" via and no min digests exactly as the default
```

- [ ] **Step 2: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_project.py -k "via_tiers or min_is_read or digests_as_before"`
Expected: FAIL - `AttributeError: 'FabProfile' object has no attribute 'tier'`.

- [ ] **Step 3: Implement in `src/placemat/project.py`**

Replace the `FabProfile` dataclass and `fab_profile` function:

```python
_VIA_KINDS = ("micro", "blind", "buried")
_TIERS = ("yes", "no", "if-needed")


@dataclass(frozen=True)
class FabProfile:
    via_drill: float = 0.3
    via_size: float = 0.6
    courtyard_excess: float = 0.10
    track_widths: tuple = tuple(round(0.15 + 0.05 * i, 2) for i in range(18))
    path: Path | None = None
    component_spacing: float = 0.2     # body to body, and body to another part's pad: twice the excess unless the fab says
    # "micro" / "blind" / "buried" -> "yes" (fixed on), "no" (fixed off) or "if-needed" (preferred off); a type
    # the file does not name is "no". The 0.57 keys allow_micro/allow_blind/allow_buried read as "yes"/"no".
    via_tiers: dict = field(default_factory=dict)
    # The fab's minimums, checked against the board's net classes at run start: track_mm, clearance_mm, drill_mm,
    # annular_mm, via_size_mm. {} when the file declares none.
    min: dict = field(default_factory=dict)

    def tier(self, kind: str) -> str:
        return self.via_tiers.get(kind, "no")

    @property
    def via_types(self) -> frozenset:
        """The types at "yes": what a script may draw outright, and what
        give way may use as a real way."""
        return frozenset(k for k in _VIA_KINDS if self.tier(k) == "yes")

    def json(self) -> str:
        """The values that decide a run, not the file they came from. A
        profile with no "yes" via, no if-needed via and no min digests
        exactly as one with none of these keys at all."""
        import json as _json
        doc = {"via_drill": self.via_drill, "via_size": self.via_size,
               "courtyard_excess": self.courtyard_excess, "track_widths": list(self.track_widths),
               "component_spacing": self.component_spacing}
        if self.via_types:                  # only when allowed, so a profile allowing none digests as before
            doc["allow_vias"] = sorted(self.via_types)
        needed = sorted(k for k in _VIA_KINDS if self.tier(k) == "if-needed")
        if needed:
            doc["if_needed_vias"] = needed
        if self.min:
            doc["min"] = dict(sorted(self.min.items()))
        return _json.dumps(doc, sort_keys=True)


def fab_profile(start) -> FabProfile:
    d = Path(start).resolve()
    for parent in (d, *d.parents):
        f = parent / "fab-profile.json"
        if f.exists():
            try:
                data = json.loads(f.read_text())
            except json.JSONDecodeError as e:
                raise ValueError("%s is not valid JSON: %s" % (f, e))
            via = data.get("via", {})
            tw = data.get("track_width_presets_mm")
            widths = FabProfile.track_widths
            if tw:
                n = int(round((tw["max"] - tw["min"]) / tw["step"])) + 1
                widths = tuple(round(tw["min"] + i * tw["step"], 2) for i in range(n))
            court = data.get("courtyard", {})
            excess = court.get("excess_mm", 0.10)
            tiers = {}
            for kind in _VIA_KINDS:
                if kind in via and via[kind] in _TIERS:
                    tiers[kind] = via[kind]
                elif ("allow_" + kind) in via:
                    tiers[kind] = "yes" if via["allow_" + kind] else "no"
            return FabProfile(via.get("default_drill_mm", 0.3), via.get("default_size_mm", 0.6),
                              excess, widths, f, court.get("component_spacing_mm", 2 * excess),
                              tiers, dict(data.get("min", {})))
    return FabProfile()
```

Add `from dataclasses import dataclass, field` if `field` is not already imported at the top of `project.py` (the existing `FabProfile` already uses `@dataclass`, confirm the import line and add `field` if missing).

- [ ] **Step 4: Run `test_project.py` and `test_via_types_allowed.py`**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_project.py tests/test_via_types_allowed.py`
Expected: `test_project.py` PASS. `test_via_types_allowed.py` will fail here - it is fixed in Task 9 (its `Board(fab_vias=...)` construction and error-message `match=` patterns change there). Confirm the failures are exactly the `fab_vias`/`allow_micro`-style ones, nothing else.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/project.py tests/test_project.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
fab-profile.json: via types take yes/no/if-needed, and a min section

The 0.57 allow_micro/allow_blind/allow_buried keys still read as
yes/no. FabProfile.json() is unchanged for a profile with none of the
new keys.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 9: `Board` reads via tiers, not a flat allow-set

**Files:**
- Modify: `src/placemat/layout.py`
- Modify: `src/placemat/runner.py` (construction site)
- Test: `tests/test_via_types_allowed.py`, `tests/test_flip_keeps_inner_layers.py`, `tests/test_via_span.py`

**Interfaces:**
- Consumes: `FabProfile.via_tiers` (Task 8).
- Produces: `Board.fab_via_tiers: dict` (class attribute, replaces `Board.fab_vias: frozenset`); `Board(..., fab_via_tiers={...})` constructor parameter replaces `fab_vias=`.

- [ ] **Step 1: Update the three existing tests to the new parameter/attribute name**

In `tests/test_via_types_allowed.py`:
- Replace `_board(**kw)`'s pass-through (`Board(g, edge_margin=0.5, keep_going=True, **kw)`) call sites: `_board(fab_vias=frozenset({"micro"}))` -> `_board(fab_via_tiers={"micro": "yes"})`.
- `Board(g, edge_margin=0.5, keep_going=True, fab_vias=frozenset({"blind"})).resolve()` -> `fab_via_tiers={"blind": "yes"}`.
- The `pytest.raises(ValueError, match="allow_micro")` / `"allow_blind"` / `"allow_buried"` assertions: change to `match='"micro"'`, `match='"blind"'`, `match='"buried"'` (the new message cites the JSON key by its tier name, not the retired `allow_*` key - see Step 3).

In `tests/test_flip_keeps_inner_layers.py` and `tests/test_via_span.py`, replace:
```python
    monkeypatch.setattr(Board, "fab_vias", frozenset({"micro", "blind", "buried"}))
```
with:
```python
    monkeypatch.setattr(Board, "fab_via_tiers", {"micro": "yes", "blind": "yes", "buried": "yes"})
```

- [ ] **Step 2: Run, confirm the expected failures**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_via_types_allowed.py tests/test_flip_keeps_inner_layers.py tests/test_via_span.py`
Expected: FAIL - `Board.__init__() got an unexpected keyword argument 'fab_via_tiers'` (or `TypeError` from `monkeypatch.setattr` finding no such attribute, depending on pytest's monkeypatch strictness).

- [ ] **Step 3: Implement in `src/placemat/layout.py`**

Change the class attribute (around line 723):
```python
    fab_via_tiers: dict = {}       # "micro"/"blind"/"buried" -> "yes"/"no"/"if-needed"; a type not named is "no"
```

Change the `__init__` parameter (around line 766, 769):
```python
                 component_spacing: float | None = None, fab_via_tiers=None, fab_source: str = ""):
```
```python
        self.fab_via_tiers = dict(fab_via_tiers) if fab_via_tiers is not None else type(self).fab_via_tiers
```

Change `_allow_via_type` (around line 3414-3424):
```python
    def _allow_via_type(self, name: str, span: tuple) -> None:
        """Refuse a via type the fab profile does not allow outright: a
        micro, blind or buried via costs more, and a preferred-off type is
        never drawn by a script even where it would clear."""
        kind = _via_kind(span)
        tier = self.fab_via_tiers.get(kind, "no")
        if tier == "yes":
            return
        why = "is not allowed by the fab profile" if tier == "no" else \
              "is preferred off by the fab profile (\"if-needed\")"
        raise ValueError(
            "%s: a %s via (%s) %s%s; they cost more, so a board keeps to through vias unless "
            "fab-profile.json says \"via\": {\"%s\": \"yes\"} for a fab that makes them" % (
                name, kind, _span_text(span), why, " (%s)" % self.fab_source if self.fab_source else "", kind))
```

- [ ] **Step 4: Update `src/placemat/runner.py`'s `Board(...)` construction**

Change (around line 300-302):
```python
    board = Board(geometry, via_drill=fab.via_drill, via_size=fab.via_size, keep_going=keep_going,
                  ...
                  fab_via_tiers=fab.via_tiers, fab_source=str(fab.path) if fab.path else "")
```
(replace only the `fab_vias=fab.via_types` keyword with `fab_via_tiers=fab.via_tiers` - every other argument on that call is unchanged; read the surrounding lines first to keep the rest verbatim).

- [ ] **Step 5: Run the three test files, then a broader sweep for any other `fab_vias` reference**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_via_types_allowed.py tests/test_flip_keeps_inner_layers.py tests/test_via_span.py`
Expected: PASS.

Run: `grep -rn "fab_vias" src/placemat/ tests/`
Expected: no hits.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/layout.py src/placemat/runner.py tests/test_via_types_allowed.py tests/test_flip_keeps_inner_layers.py tests/test_via_span.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Board takes fab_via_tiers, not a flat allow-set

A script's via type is refused for a reason that says which: not
allowed at all, or preferred off (if-needed).
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 10: `fab` findings - the fab profile's minimums against the board's net classes

**Files:**
- Modify: `src/placemat/project.py` (add `fab_min_findings`)
- Modify: `src/placemat/runner.py` (wire the call in at run start)
- Test: `tests/test_project.py`, and a targeted read of `tests/test_runner.py` for the run-start wiring

**Interfaces:**
- Consumes: `FabProfile.min`, `BoardGeometry.netclasses` (existing).
- Produces: `project.fab_min_findings(netclasses: dict, fab: FabProfile) -> list[Finding]` (kind `"fab"`).

- [ ] **Step 1: Write the failing test for the pure function**

Add to `tests/test_project.py`:

```python
def test_a_net_class_below_the_fabs_minimum_is_a_fab_finding():
    from placemat.board_geometry import NetClass
    from placemat.project import FabProfile, fab_min_findings
    fab = FabProfile(min={"track_mm": 0.12, "clearance_mm": 0.09, "drill_mm": 0.15,
                          "annular_mm": 0.075, "via_size_mm": 0.25})
    classes = {"A": NetClass("Default", 0.10, 0.2, 0.6, 0.3), "B": NetClass("Default", 0.10, 0.2, 0.6, 0.3)}
    findings = fab_min_findings(classes, fab)
    assert len(findings) == 1 and findings[0].kind == "fab"
    assert "track width" in findings[0] and "0.1" in findings[0] and "0.12" in findings[0]


def test_a_net_class_at_or_above_the_minimum_gets_no_finding():
    from placemat.board_geometry import NetClass
    from placemat.project import FabProfile, fab_min_findings
    fab = FabProfile(min={"track_mm": 0.09})
    classes = {"A": NetClass("Default", 0.09, 0.2, 0.6, 0.3)}
    assert fab_min_findings(classes, fab) == []


def test_no_min_section_gives_no_findings():
    from placemat.board_geometry import NetClass
    from placemat.project import FabProfile, fab_min_findings
    classes = {"A": NetClass("Default", 0.01, 0.01, 0.01, 0.01)}
    assert fab_min_findings(classes, FabProfile()) == []


def test_each_class_is_checked_once_not_per_net():
    from placemat.board_geometry import NetClass
    from placemat.project import FabProfile, fab_min_findings
    fab = FabProfile(min={"track_mm": 0.5})
    classes = {"A": NetClass("Thin", 0.1, 0.2, 0.6, 0.3), "B": NetClass("Thin", 0.1, 0.2, 0.6, 0.3)}
    assert len(fab_min_findings(classes, fab)) == 1
```

- [ ] **Step 2: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_project.py -k fab_min or fab_findings`
Expected: FAIL - `ImportError: cannot import name 'fab_min_findings'`.

- [ ] **Step 3: Implement in `src/placemat/project.py`**

Add near the bottom of the `FabProfile` section (after `fab_profile`):

```python
def fab_min_findings(netclasses: dict, fab: "FabProfile") -> list:
    """A `fab` Finding for each of the board's net classes with a track
    width, clearance, via diameter, via drill or annular ring (diameter
    less drill, halved) below fab-profile.json's `min`. Each class checked
    once, by name, not once per net on it."""
    from .findings import Finding
    mn = fab.min
    if not mn:
        return []
    out, seen = [], set()
    for nc in netclasses.values():
        if nc.name in seen:
            continue
        seen.add(nc.name)
        checks = [("track_mm", nc.track_width, "track width"), ("clearance_mm", nc.clearance, "clearance"),
                 ("via_size_mm", nc.via_diameter, "via diameter"), ("drill_mm", nc.via_drill, "via drill")]
        if nc.via_diameter and nc.via_drill:
            checks.append(("annular_mm", (nc.via_diameter - nc.via_drill) / 2.0, "annular ring"))
        for key, value, label in checks:
            floor = mn.get(key)
            if floor is not None and value < floor - 1e-9:
                out.append(Finding("fab", "net class %s: %s %.3g mm is below the fab's minimum %.3g mm "
                                   "(fab-profile.json min.%s)" % (nc.name, label, value, floor, key)))
    return out
```

- [ ] **Step 4: Run the pure-function tests**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_project.py`
Expected: PASS.

- [ ] **Step 5: Wire it into `runner.py`'s run start**

Read `src/placemat/runner.py`'s `run()` function in full to find: (a) where `fab = fab_profile(...)` and `geometry = read_board(...)`/`board = Board(...)` are both already in scope, and (b) where `plan = board.resolve(...)` returns and `plan.findings` is available before the run record is finalized (the same place metrics/findings get assembled - search for the first `plan.findings` read or `Findings` append after `resolve()` returns). Add, right after `plan` is available:

```python
    from .project import fab_min_findings
    plan.findings += fab_min_findings(board.geometry.netclasses, fab)
```

(`fab` and `board` are already local names in `run()` per the existing `Board(..., fab_via_tiers=fab.via_tiers, ...)` construction from Task 9 - confirm the exact variable names at the point you insert this and match them.)

- [ ] **Step 6: Write an integration test that a run surfaces the fab finding**

Read `tests/test_runner.py` first for its existing pattern of building a minimal board + running it end to end (it will use `tmp_path`, a synthetic `.zen`/script pair or a direct `Board`/`runner.run` call - match whichever pattern the file already uses for a "run records a finding of kind X" style test). Add:

```python
def test_a_net_class_below_the_fab_minimum_is_a_run_finding(tmp_path):
    ...   # follow the file's own end-to-end run pattern; write a fab-profile.json
          # with a min.track_mm above the board's default net class track width;
          # assert {f.kind for f in <the run's findings>} includes "fab"
```

- [ ] **Step 7: Run, confirm pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_project.py tests/test_runner.py`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/placemat/project.py src/placemat/runner.py tests/test_project.py tests/test_runner.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
A board rule below the fab profile's minimum is a fab finding

Checked against each of the board's net classes at run start: track
width, clearance, via diameter, via drill and annular ring.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 11: Give way's fourth way - "shorten"

**Files:**
- Modify: `src/placemat/giveway.py` (additive: `_shorten_kind`, `_shorten`, the new branch in `_give`, `Action`/`report()` wording)
- Modify: `src/placemat/layout.py` (expose `occ.fab_via_tiers`, and the "needs" note -> Finding hook)
- Modify: `src/placemat/occupancy.py` (class-level default `fab_via_tiers = {}`, `Resolution.needs` plumbing if not already carried by `giveway.Resolution`)
- Test: `tests/test_vias_give_way.py`, `tests/test_vias_give_way_kicad.py`

**Interfaces:**
- Consumes: `Board.fab_via_tiers` (Task 9), `Settings.score_via_shorten` (Task 3), `Finding("needs", ...)` (Task 7).
- Produces: `giveway.Resolution.needs: str | None = None` (a sentence when an if-needed shorten would have cleared this candidate, else `None`).
- Produces: `Action(kind="shorten", ...)` alongside the existing `"share"`/`"move"`/`"drop"` kinds.

Read `docs/superpowers/specs/2026-09-30-plane-drops-and-the-far-face-design.md` again before starting (already read during planning) - it defines `Group`, `Action`, `_give`, `_Judge`, `resolve()`, `apply()`, which this task extends, not restructures. Another agent may be changing `_give`'s share/move logic concurrently; touch only the new shorten branch and the pieces named above.

- [ ] **Step 1: Read the current test files to match fixture style**

Read `tests/test_vias_give_way.py` in full (the synthetic-geometry test file for share/move/drop) - this task's tests follow its exact `board_geometry`/`footprint`/via-declaration style.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_vias_give_way.py` (adapting net names/coordinates to whatever pattern the file's existing drop tests use for a plane net with a field of through vias meeting far-face copper - match that pattern exactly rather than inventing new fixture shapes; the fixed points below are what must hold):

```python
def test_a_drop_shortens_to_the_nearest_plane_layer_when_blind_is_yes():
    """A through GND drop under a part whose far-face pad it meets becomes
    a blind via from its own face to the nearest In-layer that carries a
    GND plane, when fab-profile.json's via.blind is "yes"."""
    # build (or adapt from an existing drop test in this file): a 4-layer
    # board (F, In1, In2, B), a GND plane zone on In1 (kind="zone", owner=None,
    # layers={IN1}), a front-side part with a through GND drop via whose ring
    # spans F..B, and a back-side part whose pad meets that via's ring on B.
    # Resolve with occ.fab_via_tiers = {"blind": "yes"}.
    ...
    action = <the Action of kind "shorten" from the resolution/board.given_way>
    assert action.kind == "shorten"
    assert action.cost == pytest.approx(<board.settings.score_via_shorten>)
    # the via now occupies F and In1 only, not B
    ...


def test_an_if_needed_blind_is_judged_but_not_applied():
    """The same board, but via.blind is "if-needed": the candidate is
    refused (shorten never draws), and the resolution names the shortened
    span it would have used."""
    ...
    res = <the failed Resolution>
    assert res.why is not None and "blind" in res.why
    assert res.needs is not None and "if-needed" in res.needs


def test_no_tier_refuses_as_today():
    """via.blind absent (defaults to "no"): the candidate is refused, and
    the refusal is the same as before this feature (no mention of shorten
    or if-needed)."""
    ...
    res = <the failed Resolution>
    assert res.needs is None
```

- [ ] **Step 3: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vias_give_way.py -k shorten`
Expected: FAIL (no `"shorten"` action kind exists yet; `Resolution` has no `needs` attribute).

- [ ] **Step 4: Implement in `src/placemat/giveway.py`**

Add `needs: str | None = None` to `Resolution`:
```python
@dataclass
class Resolution:
    actions: list = field(default_factory=list)
    cost: float = 0.0
    why: str | None = None
    blocker: object = None
    needs: str | None = None    # a sentence naming the if-needed fab option that would have cleared this spot, judged but not applied
```

Add a local via-kind classifier (no import from `layout.py`, to avoid a circular import - giveway.py is imported by occupancy.py, which layout.py imports):

```python
def _shorten_kind(span: tuple) -> str:
    """micro (exactly two adjacent layers with an outer face), buried
    (neither end an outer face) or blind, for a via's board-layer span -
    the same convention layout.py's own via-kind classifier uses."""
    from .board_geometry import stackup_order
    ordered = sorted(span, key=stackup_order)
    outer = {ordered[0], ordered[-1]} & {CopperLayer.F, CopperLayer.B}
    if len(ordered) == 2 and outer:
        return "micro"
    return "blind" if outer else "buried"
```

Add the `_shorten` helper, after `_give`:

```python
def _shorten(occ, g: Group, judge: "_Judge", own, layer, met: str):
    """(Action, note) for a drop reshaped to its own face and the nearest
    layer of its own plane, when the fab profile allows drawing it for
    real; (None, note) when it is only judged (if-needed) or not possible
    at all - `note` names the span an if-needed tier would have used, else
    None."""
    from .board_geometry import stackup_order
    s, geo = occ.settings, occ.geometry
    board = sorted(geo.layers, key=stackup_order)
    if layer not in board:
        return None, None
    plane_layers = sorted({l for c in geo.copper if c.kind == "zone" and c.net == g.net for l in c.layers},
                          key=stackup_order)
    own_i = board.index(layer)
    reach = sorted((l for l in plane_layers if l != layer), key=lambda l: abs(board.index(l) - own_i))
    if not reach:
        return None, None
    nearest = reach[0]
    lo, hi = sorted((own_i, board.index(nearest)))
    span = tuple(board[lo:hi + 1])
    if len(span) < 2 or len(span) == len(board):
        return None, None                  # already this short, or no shorter than a through via
    kind = _shorten_kind(span)
    tier = occ.fab_via_tiers.get(kind, "no")
    if tier == "no":
        return None, None
    layers = frozenset(span)
    ring = replace(g.ring, layers=layers, given=g.id)
    shapes = (ring,) if g.hole is None else (ring, replace(g.hole, layers=layers, given=g.id))
    pool = judge.near(Box.union([x.box for x in shapes]), occ._gap)
    would_clear = judge.hit(shapes, pool, own, say=False) is None
    note = "%s via %s-%s (via.%s is if-needed in fab-profile.json)" % (
        g.net, span[0].value, span[-1].value, kind) if would_clear else None
    if tier == "yes" and would_clear:
        return Action("shorten", g.id, g.owner, g.home, g.net, g.centre, g.centre, None, None, None, met,
                      s.score_via_shorten, shapes), None
    return None, note
```

In `_give`, replace the tail (the `if g.net not in occ.plane_nets: ... return None, ", ".join(said)` block) so shorten is tried last, after drop, and its if-needed note is threaded out:

```python
    needs_note = None
    if g.net not in occ.plane_nets:
        said.append("%s is not a plane net, so it is no drop" % g.net)
    elif pad_key is None:
        said.append("it serves no pad of its own")
    else:
        n, keep = who.keeps(pad_key)
        gone = who.dropped.get(pad_key, 0) + drops_now.get(pad_key, 0)
        if n - gone - 1 >= keep:
            drops_now[pad_key] = drops_now.get(pad_key, 0) + 1
            return Action("drop", g.id, g.owner, g.home, g.net, g.centre, None, None, old, pad_key, met,
                          s.score_via_drop, ()), None
        said.append("%s pad %s keeps %d of its %d drops, and must keep %d" % (pad_key[0], pad_key[1], n - gone,
                                                                              n, keep))
    if g.net in occ.plane_nets:
        action, needs_note = _shorten(occ, g, judge, own, layer, met)
        if action is not None:
            return action, None
        if needs_note is not None:
            said.append("it places as a %s" % needs_note)
    why_not = ", ".join(said)
    if needs_note is not None:
        occ.__dict__.setdefault("_last_needs", [None])[0] = "%s: %s" % (name_of_g(g), needs_note) if False else needs_note
    return None, why_not
```

Simplify that last bit - do not invent a global side channel; instead thread `needs_note` back through the function's return value directly, since `_give`'s only current return shape is `(action_or_None, why_not_string)`. Change `_give`'s return type to a 3-tuple `(action_or_None, why_not, needs_note)` and update **every** call site inside `resolve()` (both the "already placed" loop and the "its own vias" loop) to unpack three values instead of two, and to set `res.needs = needs_note` on the `Resolution` returned by `_refused()` when a refusal carries one. Concretely:

Change `_give`'s final lines to:
```python
    return None, why_not, needs_note
```
and every earlier `return Action(...), None` inside `_give` to `return Action(...), None, None` (a successful give-way never needs the if-needed note).

Change `_refused` to accept and store a needs note:
```python
def _refused(occ, res: Resolution, why: str, o, needs: str | None = None) -> Resolution:
    from .occupancy import Blocker, _blocker_kind
    res.why = why
    res.needs = needs
    res.blocker = Blocker("edge", "", frozenset()) if o is None else \
        Blocker(_blocker_kind(o.kind), occ.blame_owner(o), frozenset(o.faces))
    return res
```

In `resolve()`, both call sites that do:
```python
            action, why_not = _give(occ, g, judge, ..., hit[1])
            if action is None:
                return _refused(occ, res, "%s; ... cannot give way: %s" % (..., why_not), g.ring)
```
become:
```python
            action, why_not, needs_note = _give(occ, g, judge, ..., hit[1])
            if action is None:
                return _refused(occ, res, "%s; ... cannot give way: %s" % (..., why_not), g.ring, needs_note)
```
(match the exact surrounding text of each of the two existing `_refused(...)` calls in `resolve()` - read them again before editing, they differ slightly in their message format between the "already placed" and "its own vias" loops).

Update `report()`'s kind/verb table to include shorten:
```python
            for kind, verb in (("share", "shared"), ("move", "moved"), ("drop", "dropped"), ("shorten", "shortened")):
```

- [ ] **Step 5: Expose `fab_via_tiers` on `Occupancy` (default `{}`) and set it from `Board.resolve()`**

In `src/placemat/occupancy.py`, add a class-level default next to `plane_nets`/`quiet_nets` (around line 896-897):
```python
    fab_via_tiers: dict = {}        # "micro"/"blind"/"buried" -> "yes"/"no"/"if-needed" (giveway.py's shorten)
```

In `src/placemat/layout.py`'s `resolve()` method, right after the existing line `occ.plane_nets = frozenset(c.net for c in self._copper if c.key.split(" ")[0] == "plane")`, add:
```python
        occ.fab_via_tiers = dict(self.fab_via_tiers)
```

- [ ] **Step 6: Wire a `needs` Finding when an item's search exhausts with an if-needed near-miss**

Read `src/placemat/placer.py` around line 160-180 (`_reason_key`, the code that turns `res.why` into a candidate's rejection reason during a search) and the code in `layout.py` that builds the final "this item did not place" `Finding` (search for where `Finding("unplaced", ...)` or `Finding("fixed", ...)` is constructed from a search's aggregated blocker/why - this is the point every failed candidate's reason converges to one message). At that point, thread the *first* non-`None` `needs` seen across the item's tried candidates (the search already carries `res`/the reason objects that far - extend whatever collection already holds "the reason nothing worked" to also hold "the first needs note seen", a parallel piece of data, not a new collection mechanism) into a companion `Finding("needs", "<item note>: <needs_note>")` appended to `plan.findings` alongside the existing failure finding.

Write the test first:

```python
def test_a_needs_finding_is_recorded_when_only_an_if_needed_via_would_have_placed_it():
    ...   # same board as test_an_if_needed_blind_is_judged_but_not_applied, but resolved
          # through Board.resolve() end to end (not giveway.resolve() directly), with
          # keep_going=True so the run continues; assert {f.kind for f in plan.findings}
          # includes "needs" and that finding's text names the net and the blind span
```

- [ ] **Step 7: Run, confirm pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vias_give_way.py tests/test_vias_give_way_kicad.py tests/test_finding_kinds.py`
Expected: PASS. If Step 6's plan.findings wiring proves substantially more invasive than described (a search-loop restructuring beyond a small, additive hook), stop, keep Tasks 11's Steps 1-5 (shorten itself, fully working and tested at the `giveway.resolve()` level, including the if-needed refusal note in `res.why`/`res.needs`) committed, and record the `needs`-Finding integration as explicitly left undone in the final report rather than force a deep, risky change into a file shared with a concurrent agent.

- [ ] **Step 8: Commit**

```bash
git add src/placemat/giveway.py src/placemat/layout.py src/placemat/occupancy.py src/placemat/placer.py tests/test_vias_give_way.py tests/test_vias_give_way_kicad.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Give way's fourth way: shorten a drop to its own face and its plane's
nearest layer

Priced at score.via_shorten. An if-needed via type is judged but never
drawn: the refusal names the span it would have used, and a needs
finding records it.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 12: `placemat facts` command and its confirmation record

**Files:**
- Create: `src/placemat/facts.py`
- Modify: `src/placemat/settings.py` (`facts_confirmed` field, excluded from the run digest; `write_confirmed`)
- Modify: `src/placemat/cli.py` (new `facts` subcommand)
- Modify: `src/placemat/runner.py` (unconfirmed-facts first line + `facts` finding)
- Test: `tests/test_facts.py` (new), `tests/test_settings.py`, a targeted addition to `tests/test_runner.py`

**Interfaces:**
- Produces: `facts.board_facts(geometry, fab, settings) -> dict`
- Produces: `facts.facts_digest(doc: dict) -> str`
- Produces: `facts.unconfirmed_reasons(doc: dict, confirmed: str, digest: str) -> list[str]`
- Produces: `facts.role_flags(doc: dict) -> list[str]`
- Produces: `facts.facts_lines(doc: dict, reasons: list, flags: list) -> list[str]`
- Produces: `Settings.facts_confirmed: str = ""`, excluded from `Settings.json()`.
- Produces: `settings.write_confirmed(board_dir, digest: str) -> Path`

- [ ] **Step 1: Write the failing tests for the pure `facts.py` functions**

```python
# tests/test_facts.py
import dataclasses

from placemat.board_geometry import NetClass
from placemat.facts import board_facts, facts_digest, facts_lines, role_flags, unconfirmed_reasons
from placemat.project import FabProfile
from placemat.settings import Settings
from placemat.values import CopperLayer
from tests.fixtures import board_geometry


def _g(**kw):
    g = board_geometry([], width=20, height=20)
    return dataclasses.replace(g, **kw)


def test_board_facts_lists_each_layers_role_and_weight():
    g = _g(layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.B),
           layer_types={CopperLayer.F: "signal", CopperLayer.IN1: "power", CopperLayer.B: "signal"},
           copper_mm={CopperLayer.F: 0.035, CopperLayer.IN1: 0.0152, CopperLayer.B: 0.035})
    doc = board_facts(g, FabProfile(), Settings())
    by_layer = {l["layer"]: l for l in doc["layers"]}
    assert by_layer["In1.Cu"]["role"] == "power" and by_layer["In1.Cu"]["copper_mm"] == 0.0152


def test_board_facts_lists_pair_classes_and_excludes_default():
    classes = {"CLK_P": NetClass("HS", 0.1, 0.1, 0.5, 0.3, 0.1, 0.1),
              "CLK_N": NetClass("HS", 0.1, 0.1, 0.5, 0.3, 0.1, 0.1),
              "GND": NetClass("Default", 0.2, 0.2, 0.6, 0.3, 0.2, 0.2)}
    g = _g(netclasses=classes, nets=frozenset(classes))
    doc = board_facts(g, FabProfile(), Settings())
    assert doc["pair_classes"] == {"HS": ["CLK_N", "CLK_P"]}


def test_board_facts_reports_via_types_and_fab_min():
    fab = FabProfile(via_tiers={"blind": "if-needed"}, min={"track_mm": 0.09})
    doc = board_facts(_g(), fab, Settings())
    assert doc["via_types"] == {"micro": "no", "blind": "if-needed", "buried": "no"}
    assert doc["fab_min"] == {"track_mm": 0.09}
    assert doc["fab_declared"] == {"via": True, "min": True}


def test_board_facts_reports_the_rise():
    doc = board_facts(_g(), FabProfile(), Settings(check_rise_c=15.0))
    assert doc["rise_c"] == 15.0


def test_unconfirmed_reasons_with_no_record_and_no_fab_sections():
    doc = board_facts(_g(), FabProfile(), Settings())
    digest = facts_digest(doc)
    reasons = unconfirmed_reasons(doc, "", digest)
    assert "no confirmation record" in " ".join(reasons)
    assert any("via" in r for r in reasons) and any("min" in r for r in reasons)


def test_unconfirmed_reasons_when_the_digest_matches():
    doc = board_facts(_g(), FabProfile(via_tiers={"micro": "yes"}, min={"track_mm": 0.09}), Settings())
    digest = facts_digest(doc)
    reasons = unconfirmed_reasons(doc, digest, digest)
    assert reasons == []


def test_unconfirmed_reasons_when_the_facts_changed_since_confirmation():
    doc = board_facts(_g(), FabProfile(via_tiers={"micro": "yes"}, min={"track_mm": 0.09}), Settings())
    digest = facts_digest(doc)
    assert unconfirmed_reasons(doc, "not-the-digest", digest) == ["the facts have changed since they were last confirmed"]


def test_role_flags_a_signal_layer_carrying_a_plane_and_a_power_layer_carrying_none():
    poly = ((0, 0), (1, 0), (1, 1), (0, 1))
    from placemat.board_geometry import CopperItem
    from placemat.values import Box
    zone = CopperItem("zone", "GND", frozenset({CopperLayer.F}), (poly,), Box.of_points(poly))
    g = _g(layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.B),
          layer_types={CopperLayer.F: "signal", CopperLayer.IN1: "power", CopperLayer.B: "signal"},
          copper=(zone,))
    doc = board_facts(g, FabProfile(), Settings())
    flags = role_flags(doc)
    assert any("F.Cu" in f and "signal" in f for f in flags)
    assert any("In1.Cu" in f and "power" in f for f in flags)


def test_facts_lines_reads_as_text():
    doc = board_facts(_g(), FabProfile(), Settings())
    lines = facts_lines(doc, ["no confirmation record yet"], [])
    assert any("unconfirmed" in l for l in lines)
```

- [ ] **Step 2: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_facts.py`
Expected: FAIL - `ModuleNotFoundError: No module named 'placemat.facts'`.

- [ ] **Step 3: Implement `src/placemat/facts.py`**

```python
"""What `placemat facts` prints: each fact placemat can establish about a
board, its home (docs/superpowers/specs/2026-09-30-board-facts-fixed-and-
preferred-design.md, "The rule"), and whether it is confirmed."""
from __future__ import annotations

import hashlib
import json

from .board_geometry import stackup_order

_VIA_KINDS = ("micro", "blind", "buried")


def board_facts(geometry, fab, settings) -> dict:
    """Every printable fact: each copper layer's role and weight, the pair
    classes and their nets, the board's own planes, via types with their
    tier, the fab minimums, and the rise the current-path check judges by."""
    layers = [{"layer": l.value, "role": geometry.layer_types.get(l, "signal"),
              "copper_mm": geometry.copper_mm.get(l)} for l in sorted(geometry.layers, key=stackup_order)]
    by_class: dict = {}
    for net, nc in geometry.netclasses.items():
        by_class.setdefault(nc.name, {"nets": [], "diff_pair_width": nc.diff_pair_width,
                                      "diff_pair_gap": nc.diff_pair_gap})
        by_class[nc.name]["nets"].append(net)
    pair_classes = {name: sorted(c["nets"]) for name, c in by_class.items()
                    if name != "Default" and c["diff_pair_width"] is not None and c["diff_pair_gap"] is not None}
    planes = sorted({(l.value, c.net) for c in geometry.copper if c.kind == "zone" and not c.owner for l in c.layers})
    return {"layers": layers, "pair_classes": pair_classes,
            "planes": [{"layer": l, "net": n} for l, n in planes],
            "via_types": {kind: fab.tier(kind) for kind in _VIA_KINDS}, "fab_min": dict(fab.min),
            "fab_declared": {"via": bool(fab.via_tiers), "min": bool(fab.min)}, "rise_c": settings.check_rise_c}


def facts_digest(doc: dict) -> str:
    """A stable digest of the printed facts, for `placemat facts --confirm`
    to record and a later run to check itself against."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def unconfirmed_reasons(doc: dict, confirmed: str, digest: str) -> list:
    """Why the printed facts are unconfirmed: no record yet, fab-profile.json
    missing its via or min section, or the facts changed since they were
    last confirmed."""
    reasons = []
    if not confirmed:
        reasons.append("no confirmation record yet")
    elif confirmed != digest:
        reasons.append("the facts have changed since they were last confirmed")
    fd = doc.get("fab_declared", {})
    if not fd.get("via"):
        reasons.append("fab-profile.json has no via section")
    if not fd.get("min"):
        reasons.append("fab-profile.json has no min section")
    return reasons


def role_flags(doc: dict) -> list:
    """A layer whose role disagrees with what the board's own copper
    carries: a signal layer with a plane(), or a power layer with none."""
    planed = {p["layer"] for p in doc["planes"]}
    out = []
    for l in doc["layers"]:
        name, role = l["layer"], l["role"]
        if role == "signal" and name in planed:
            out.append("%s is signal but carries a plane()" % name)
        elif role == "power" and name not in planed:
            out.append("%s is power but carries no plane()" % name)
    return out


def facts_lines(doc: dict, reasons: list, flags: list | None = None) -> list:
    """The command's text report, one fact a line."""
    out = []
    for l in doc["layers"]:
        w = "%.4g mm" % l["copper_mm"] if l["copper_mm"] is not None else "no stackup weight"
        out.append("layer %-8s role %-7s %s" % (l["layer"], l["role"], w))
    for name, nets in sorted(doc["pair_classes"].items()):
        out.append("pair class %-12s %s" % (name, ", ".join(nets)))
    if not doc["pair_classes"]:
        out.append("no pair classes")
    for p in doc["planes"]:
        out.append("plane %-8s %s" % (p["layer"], p["net"]))
    for kind, tier in doc["via_types"].items():
        out.append("via %-8s %s" % (kind, tier))
    for key, value in sorted(doc["fab_min"].items()):
        out.append("fab min %-12s %.4g mm" % (key, value))
    out.append("rise %g C" % doc["rise_c"])
    for flag in flags or []:
        out.append("flagged: %s" % flag)
    if reasons:
        out.append("unconfirmed: %s" % "; ".join(reasons))
    else:
        out.append("confirmed")
    return out
```

- [ ] **Step 4: Run `test_facts.py`**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_facts.py`
Expected: PASS.

- [ ] **Step 5: Write the failing test for `Settings.facts_confirmed` and its digest exclusion**

Add to `tests/test_settings.py`:

```python
def test_facts_confirmed_is_a_setting_excluded_from_the_run_digest():
    from placemat.settings import Settings
    a = Settings()
    b = Settings(facts_confirmed="abc123", sources={})
    assert a.facts_confirmed == "" and b.facts_confirmed == "abc123"
    assert a.json() == b.json()      # the confirmation does not feed the digest a run id hashes


def test_write_confirmed_upserts_the_facts_section(tmp_path):
    from placemat.settings import load, write_confirmed
    (tmp_path / "placemat.toml").write_text("[place]\nstep = 0.1\n")
    write_confirmed(tmp_path, "abc123")
    text = (tmp_path / "placemat.toml").read_text()
    assert "[place]" in text and "step = 0.1" in text        # the rest of the file survives
    assert load(tmp_path).facts_confirmed == "abc123"
    write_confirmed(tmp_path, "def456")                       # a second confirm replaces, not duplicates
    assert load(tmp_path).facts_confirmed == "def456"
    assert (tmp_path / "placemat.toml").read_text().count("[facts]") == 1
```

- [ ] **Step 6: Run, confirm failure**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings.py -k facts_confirmed or write_confirmed`
Expected: FAIL - `TypeError: __init__() got an unexpected keyword argument 'facts_confirmed'`.

- [ ] **Step 7: Implement in `src/placemat/settings.py`**

Add the field to `Settings` (a natural new `[facts]` section - place it after `[route]`'s fields, before `[timeout]`):
```python
    # [facts]
    facts_confirmed: str = ""   # a digest from `placemat facts --confirm`: placemat's own record, not a board fact
```

In `Settings.json()`, skip it explicitly:
```python
    def json(self) -> str:
        """Canonical, for the run id: the values only, sorted, stable across
        dict ordering. facts_confirmed is left out: confirming the facts
        must not re-plan a board."""
        out = {}
        for name in self.keys():
            if name == "facts_confirmed":
                continue
            v = getattr(self, name)
            out[name] = sorted(v.items()) if isinstance(v, dict) else (
                list(v) if isinstance(v, tuple) else v)
        return json.dumps(out, sort_keys=True, separators=(",", ":"))
```

Add `write_confirmed` near `load`/`FILENAME`:
```python
_FACTS_SECTION_RE = re.compile(r"^\[facts\]\s*$.*?(?=^\[|\Z)", re.M | re.S)
_CONFIRMED_LINE_RE = re.compile(r'^confirmed\s*=.*$', re.M)


def write_confirmed(board_dir, digest: str) -> Path:
    """Write `[facts] confirmed = "<digest>"` into board_dir/placemat.toml,
    replacing an existing value or adding the section: the rest of the file
    is left exactly as it was. This is placemat's own confirmation record,
    excluded from Settings.json() so it never changes a run's id."""
    import re as _re
    path = Path(board_dir) / FILENAME
    text = path.read_text() if path.exists() else ""
    line = 'confirmed = "%s"' % digest
    m = _FACTS_SECTION_RE.search(text)
    if m:
        block = m.group(0)
        new_block = _CONFIRMED_LINE_RE.sub(line, block) if _CONFIRMED_LINE_RE.search(block) \
            else block.rstrip("\n") + "\n" + line + "\n"
        text = text[:m.start()] + new_block + text[m.end():]
    else:
        if text and not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n" if text else text
        text += "[facts]\n" + line + "\n"
    path.write_text(text)
    return path
```

(Add `import re` at the top of `settings.py` if not already present - it is not, per the file's current imports; add it beside the existing `import tomllib`.)

- [ ] **Step 8: Run the settings tests**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings.py`
Expected: PASS.

- [ ] **Step 9: Add the `facts` CLI subcommand**

Write the failing test first. Read `tests/test_cli_output.py` (or the nearest existing CLI-integration test file for a simple read-only command like `settings`) for its pattern of invoking `cli.main([...])` against a small built board, then add a test in that style:

```python
def test_facts_command_prints_and_confirm_writes_the_digest(tmp_path, capsys):
    ...   # follow the file's existing pattern for building a minimal generated
          # board (or reuse a fixture .kicad_pcb this test file already has access
          # to) and invoking `cli.main(["facts", str(pcb)])`; assert the output
          # contains "unconfirmed"; then run `cli.main(["facts", str(pcb), "--confirm"])`
          # and assert placemat.toml under the board directory now has [facts] confirmed
```

Add to `src/placemat/cli.py`'s `parser()`, alongside the `check` subparser:
```python
    fa = sub.add_parser("facts", help="the board's facts, their home, and whether they are confirmed")
    fa.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    fa.add_argument("--confirm", action="store_true",
                    help="record the printed facts as confirmed in placemat.toml's [facts] confirmed")
    fa.add_argument("--json", action="store_true")
```

Add `cmd_facts`:
```python
def cmd_facts(args) -> int:
    from . import facts as facts_mod
    from .kicad.read import read_board
    from .project import find_board, fab_profile
    from .settings import bind, load, write_confirmed
    p = Path(args.pcb)
    src = None if p.suffix == ".kicad_pcb" else find_board(p)
    pcb = p if src is None else src.pcb
    board_dir = src.board_dir if src is not None else pcb.parent
    cfg = load(board_dir)
    fab = fab_profile(board_dir)
    with bind(cfg):
        geometry = read_board(pcb)
    doc = facts_mod.board_facts(geometry, fab, cfg)
    digest = facts_mod.facts_digest(doc)
    reasons = facts_mod.unconfirmed_reasons(doc, cfg.facts_confirmed, digest)
    flags = facts_mod.role_flags(doc)
    if args.confirm:
        out = write_confirmed(board_dir, digest)
        console.say("facts", "confirmed %s in %s" % (digest, out))
        return 0
    if args.json:
        console.data(json.dumps({"facts": doc, "digest": digest, "unconfirmed": reasons, "flags": flags}, indent=2))
        return 0
    for line in facts_mod.facts_lines(doc, reasons, flags):
        console.say("facts", line)
    return 1 if reasons else 0
```

Register it in `_dispatch`'s dict: add `"facts": cmd_facts,`.

- [ ] **Step 10: Run, confirm pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_facts.py tests/test_settings.py tests/test_cli_output.py`
Expected: PASS.

- [ ] **Step 11: Unconfirmed-facts run finding and first-line note**

Write the failing test first (extending Task 10's `test_runner.py` addition or a new function in the same file):

```python
def test_an_unconfirmed_run_says_so_first_and_records_a_facts_finding(tmp_path, capsys):
    ...   # run a minimal board with no [facts] confirmed at all; assert the
          # run's first printed line contains "facts: unconfirmed - placemat facts";
          # assert {f.kind for f in <the run's findings>} includes "facts"
```

Read `src/placemat/runner.py`'s `run()` function in full to find its very first `console.say(...)`/`say(...)` call (the run's first printed line today) and the point `fab`/`board`/`plan` are all in scope (the same point Task 10 used). Right after `fab = fab_profile(...)` and before the first existing print, insert:

```python
    from . import facts as facts_mod
    from .kicad.read import read_board as _read_board_for_facts
    facts_doc = facts_mod.board_facts(_read_board_for_facts(src.pcb), fab, cfg)   # match cfg/src's actual local names
    facts_digest_now = facts_mod.facts_digest(facts_doc)
    facts_unconfirmed = facts_mod.unconfirmed_reasons(facts_doc, cfg.facts_confirmed, facts_digest_now)
    if facts_unconfirmed:
        say("facts", "unconfirmed - placemat facts")
```
(match `say`'s exact existing call convention in this file - it may be a local closure over `console.say` with a level/quiet flag; use whatever the file's other first-line prints use verbatim). Then, once `plan` exists:
```python
    if facts_unconfirmed:
        plan.findings.append(Finding("facts", "facts: unconfirmed (%s) - placemat facts" % "; ".join(facts_unconfirmed)))
```
(import `Finding` from `.findings` at the top of the block if not already imported in this file - check first, `runner.py` likely already imports `Finding`/`Findings` given it builds run records from a plan's findings).

- [ ] **Step 12: Run, confirm pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_runner.py tests/test_finding_kinds.py`
Expected: PASS.

- [ ] **Step 13: Verify a confirm does not change the run id (Review Focus item)**

Write and run this test explicitly:

```python
def test_confirming_facts_does_not_change_the_run_id(tmp_path):
    ...   # run the same minimal board twice, calling `placemat facts --confirm`
          # (or settings.write_confirmed directly) between the two runs, with
          # nothing else changed; assert the two runs' ids are equal
```

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_runner.py -k confirming_facts_does_not_change`
Expected: PASS (this is exactly what Step 7's `Settings.json()` exclusion guarantees; this test pins the guarantee at the run-id level, not just the `Settings.json()` level).

- [ ] **Step 14: Commit**

```bash
git add src/placemat/facts.py src/placemat/settings.py src/placemat/cli.py src/placemat/runner.py tests/test_facts.py tests/test_settings.py tests/test_runner.py tests/test_cli_output.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
placemat facts: print the board's facts and their home; --confirm records them

An unconfirmed run says so on its first line and records a facts
finding. The confirmation digest is excluded from the run id: a
confirm never re-plans a board.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 13: Skill and reference docs

**Files:**
- Modify: `skills/placemat/SKILL.md`
- Modify: `skills/placemat/references/api.md`
- Modify: `skills/placemat/references/capture.md`
- Modify: `skills/placemat/references/migration.md`

No tests (documentation only), but every claim in the new text must match the behaviour Tasks 1-12 actually implement - re-read the relevant source after each edit, do not describe intended-but-undone behaviour (check Task 11's Step 7 outcome before writing about the `needs` finding - if that integration was left undone, say only what shorten and its refusal note actually do, not that a `needs` Finding is always recorded).

- [ ] **Step 1: SKILL.md - "establish the facts" step**

In `skills/placemat/SKILL.md`, add a new subsection right after "## A fresh board"'s numbered list (before "## The loop"), and reference it from "## An existing script" too since both paths place on a board:

```markdown
## Establish the facts, before any placement

Run `placemat facts <board or script>`. For each fact it marks
unconfirmed or flags:
- ask the user with AskUserQuestion: layer roles and copper weights,
  pair nets, via types and their tier, fab minimums, the rise;
- write the answer in its home (the table above): the stackup and pair
  classes in the .zen, fab facts in fab-profile.json, the rise in
  placemat.toml;
- regenerate the board, then run `placemat facts --confirm`.

Never proceed on a default, and never write a fact the user did not
give. A board carrying the stdlib's default stackup is asked about like
any other - `placemat facts` marks every fact unconfirmed until the
board has a confirmation record at all.
```

Add a "where a change goes" table right after "The rule"'s prose in the same section (or, if "The rule" itself lives outside SKILL.md - confirm during this step by grepping SKILL.md for "The rule"; if it is only in the spec, add the table fresh here):

```markdown
| To change | Edit |
|---|---|
| a board fact (stackup, layer roles, pair nets) | the .zen |
| what the fab allows | fab-profile.json |
| placement, scoring or the router | placemat.toml |
| what the layout does | the script |
```

- [ ] **Step 2: api.md - settings table**

In `skills/placemat/references/api.md`'s settings table (around line 2172-2202):
- Remove the `check.copper_oz` row (line ~2175).
- Remove the `route.layers` row (line ~2192).
- Remove the `route.diff_pairs` row (line ~2199).
- Add, next to `score.via_drop`:
```markdown
| `score.via_shorten` | 5 | mm for a drop reshaped to its own face and its plane's nearest layer there (give way's fourth way, between move and drop) |
```
- Add, in a `[facts]` group after `route.adopt_tolerance`'s row:
```markdown
| `facts.confirmed` | none | a digest `placemat facts --confirm` wrote; placemat's own record, excluded from a run's id |
```
- Add one line near the top of "## Settings" (after the precedence diagram): "placemat.toml is tuning only: search, scoring, cleanup, DRC grading and router tuning. A board fact belongs in the .zen; what the fab allows belongs in fab-profile.json."

Update the two prose paragraphs that described the retired behaviour (around lines 1886-1890 and 1911-1923, quoted during planning): rewrite "Left to itself (no `--layers` and no route.layers), the router gets every copper layer except an inner one whose own outline a `board.plane()` zone covers..." to describe the new role-based default (every layer whose role is signal or mixed, F.Cu/B.Cu always; `placemat route --layers` the only override), and rewrite the differential-pairs paragraph to describe pairs coming from the board's net classes (`board_pairs`) rather than `route.diff_pairs` patterns - re-read `src/placemat/kicad/route.py`'s final Task 6 state and `src/placemat/pairs.py`'s `board_pairs`/`board_pair_list` docstrings before writing this, so the prose matches the shipped mechanics exactly (the suffix-rename-to-the-router trick still happens, unconditionally now, not just for "named" pairs).

Add fab-profile.json's keys (via tiers, min, courtyard) to api.md if genuinely undocumented there today (confirmed absent during planning - grep found none): add a short subsection near "## Copper vocabulary" or wherever via types are otherwise discussed:

```markdown
### fab-profile.json

The fab's capability and price: what a script may draw, what placemat's
give way may use, and the fab's minimums, checked against the board's
net classes at run start.

```json
{
  "via": {"micro": "no", "blind": "if-needed", "buried": "no",
          "default_drill_mm": 0.3, "default_size_mm": 0.6},
  "min": {"track_mm": 0.09, "clearance_mm": 0.09, "drill_mm": 0.15,
          "annular_mm": 0.075, "via_size_mm": 0.25},
  "courtyard": {"excess_mm": 0.1}
}
```

Each via type is `"yes"` (fixed on), `"no"` (fixed off) or `"if-needed"`
(preferred off: never drawn, judged only). A type the file does not name
is `"no"`. The 0.57 keys `allow_micro`/`allow_blind`/`allow_buried`
still read as `"yes"`/`"no"`. A net class rule below `min` is a `fab`
finding.
```

Add `placemat facts` to the "## Commands" section, matching the format of the neighbouring `check` command's entry:

```markdown
### `placemat facts`

`placemat facts <board or script>` prints each fact placemat can
establish, its value and its home, and whether it is confirmed.
`--confirm` records the printed facts as a digest in placemat.toml's
`[facts] confirmed` - placemat's own record, excluded from a run's id.
A run whose facts do not match that digest says so on its first line
and records a `facts` finding; it still runs.
```

- [ ] **Step 3: capture.md - current-path copper weight**

In `skills/placemat/references/capture.md`, find the bullet(s) about the current-path check (grep for "current" or "Pm.I" first) and add or amend a sentence: "The current-path check reads each layer's own copper weight from the board's stackup (the .zen's `BoardConfig`), an inner layer judged against IPC-2221's inner constant; a layer the stackup does not name defaults to 1 oz."

- [ ] **Step 4: migration.md - Unreleased section**

Read `skills/placemat/references/migration.md`'s first ~40 lines and its most recent full section (already read during planning) to match the exact heading/voice convention, then add a new section at the **top** of the file (newest first, per SKILL.md's own description of this file), headed `## Unreleased`, using the spec's section 6 content in the general form (no project names, `<mm>`/`<NET>_P` placeholders):

```markdown
## Unreleased

**Board facts move to the .zen; placemat.toml is tuning only.**

1. **Declare the stackup in the .zen.** Give the board's `BoardConfig` a
   `stackup`, with a `CopperLayer` for each copper layer, top to bottom,
   and a `DielectricLayer` between each pair:

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

   A layer's role is what it carries: `signal` tracks, `ground`/`power` a
   plane, `mixed` both. The route step routes on `signal` and `mixed`
   layers.

2. **Name the pair nets in their class.** A differential pair class takes
   `nets = ["<NET>_P", "<NET>_N"]`, with `diff_pair_width` and
   `diff_pair_gap`.

3. **Delete the retired keys from placemat.toml:** `[check] copper_oz`,
   `[route] layers`, `[route] diff_pairs`. A run refuses them, naming
   what replaces each.

4. **Set fab-profile.json's `via` and `min`** from the fab's capability
   page: each via type `"yes"`, `"no"` or `"if-needed"`.

5. **Regenerate the board and run `placemat facts`.** Check each layer's
   role and weight and the pairs, then `placemat facts --confirm`.

What moves: the route step's default layers come from the roles; the
pairs come from the classes; inner-layer current paths are judged by the
inner constant and the layer's own weight. A board's route and
current-path verdicts can change on this release.
```

- [ ] **Step 5: Commit**

```bash
git add skills/placemat/SKILL.md skills/placemat/references/api.md skills/placemat/references/capture.md skills/placemat/references/migration.md
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "$(cat <<'EOF'
Skill and reference docs: establish the facts, where a change goes,
fab-profile.json's keys, placemat facts, migration

The skill's pressure test (a session given a board with no fab-profile
via section) is run by the coordinator after merge, not here.
EOF
)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 14: Bench and wrap-up

**Files:** none (verification only)

- [ ] **Step 1: Run the full targeted test sweep across every file this plan touched or added**

Run:
```bash
cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_stackup_copper_mm.py tests/test_board_geometry_read.py tests/test_checks.py \
  tests/test_current_path_neck.py tests/test_current_path_pairs.py tests/test_current_path_zone_width.py \
  tests/test_settings.py tests/test_settings_wiring.py tests/test_checks_wiring.py tests/test_cli_output.py \
  tests/test_route_plane_layers.py tests/test_route_settings.py tests/test_route_command.py \
  tests/test_pairs.py tests/test_route_pairs.py tests/test_pair_crossing.py tests/test_explicit_pairs.py \
  tests/test_report.py tests/test_run_score.py tests/test_finding_kinds.py \
  tests/test_project.py tests/test_via_types_allowed.py tests/test_flip_keeps_inner_layers.py tests/test_via_span.py \
  tests/test_runner.py tests/test_vias_give_way.py tests/test_vias_give_way_kicad.py tests/test_facts.py \
  tests/test_copper_digest_parity.py
```
Expected: PASS, every file. `test_copper_digest_parity.py` specifically pins the "FabProfile.json() digest-compatible" constraint end to end - it must pass unmodified.

- [ ] **Step 2: Run the bench**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2`

- [ ] **Step 3: Record the tally and do a final review pass**

Read the bench output's tally lines. Read the diff of every file this plan touched once more (`git diff main...HEAD --stat` and a skim of the largest files) for: any leftover reference to `route_diff_pairs`, `check_copper_oz`, `route.layers`, `fab_vias`, or `allow_micro`-style matching in a test that Task 9 should have updated; any project/board/part name accidentally introduced; any `em dash`/unicode arrow.

- [ ] **Step 4: Final commit with the bench tally**

If Step 3 finds nothing to fix, this task needs no code commit of its own - the bench tally goes into the final report, not a new commit, since there is no uncommitted change to carry it. If Step 3 finds a fix, make it, re-run the affected targeted tests, commit it normally (per the Global Constraints), then re-run the bench once more and use that tally.

```bash
git status
```
Expected: clean (nothing to commit) once every task's own commit has landed.
