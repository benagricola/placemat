# Fragment Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A keepout declared in a two-layer module fragment on every copper layer, or on an inner layer, holds on the four-layer board that stamps it, and a layer that cannot be honoured is a finding rather than a silent loss.

**Architecture:** The declaration travels in the zone name, the one thing that survives KiCad's save and `pcb layout`'s stamp. Pure helpers in `board_geometry.py` format and parse the marker and resolve it against a stackup. `read.py` resolves it into `RuleArea.layers`, so every consumer honours it unchanged; `write.py` writes it and widens a stamped zone to match; `layout.py` compares base names and raises the findings.

**Tech Stack:** Python 3.12 stdlib, pcbnew under `kicad/` only.

**Spec:** `docs/superpowers/specs/2026-09-22-fragment-layers-design.md`

## Global Constraints

- **Zero runtime dependencies.** `dependencies = []`.
- **pcbnew only under `src/placemat/kicad/`.** The marker helpers are pure.
- **Punctuation is plain ASCII.**
- **Commit messages carry no reference to Claude, Anthropic or a session.**
- **Widening only adds layers the declaration named.** A stamped zone is never narrowed and never deleted.
- **The marker is found anywhere in the name**, because `pcb layout` appends `_1` after it: `keepout antenna [*.Cu]_1`.

## File Structure

- `src/placemat/board_geometry.py` - `stackup_order`, `layer_marker`, `split_marker`, `resolve_marker`; `RuleArea.missing` and `RuleArea.base`.
- `src/placemat/kicad/read.py` - `_rule_areas` resolves the marker.
- `src/placemat/kicad/write.py` - `_draw_keepouts` writes the marker and widens stamped zones.
- `src/placemat/layout.py` - the clash check by base name, and the two findings.
- `tests/test_fragment_layers.py` - pure.
- `tests/test_fragment_layers_kicad.py` - against pcbnew.

---

## Task 1: The marker, pure

**Files:**
- Modify: `src/placemat/board_geometry.py`
- Test: `tests/test_fragment_layers.py` (create)

**Interfaces:**
- Produces: `stackup_order(layer) -> int`, `layer_marker(declared: tuple | None, board_layers) -> str`, `split_marker(name) -> tuple[str, object]` where the declaration is `"*"`, a tuple of `CopperLayer`, or `None`; `resolve_marker(declared, board_layers) -> tuple[frozenset, tuple]` giving (resolved, missing); `RuleArea.missing: tuple = ()`, `RuleArea.base -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fragment_layers.py
"""A module's keepout on layers its own two-layer board does not have. The
declaration travels in the zone name, the one thing that survives KiCad's save
and pcb's stamp. Pure: no KiCad."""
from placemat.board_geometry import (RuleArea, layer_marker, resolve_marker, split_marker,
                                     stackup_order)
from placemat.values import CopperLayer

F, B, IN1, IN2 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1, CopperLayer.IN2
TWO, FOUR = (F, B), (F, IN1, IN2, B)


def test_every_copper_layer_is_marked_as_such():
    assert layer_marker(None, TWO) == " [*.Cu]"


def test_explicit_layers_the_board_lacks_are_listed_in_stackup_order():
    assert layer_marker((B, IN2, F, IN1), TWO) == " [F.Cu,In1.Cu,In2.Cu,B.Cu]"


def test_explicit_layers_the_board_has_need_no_marker():
    assert layer_marker((F, B), TWO) == ""
    assert layer_marker((IN2,), FOUR) == ""


def test_a_stamped_name_splits_into_base_and_declaration():
    """pcb layout appends `_1` after the marker."""
    assert split_marker("keepout antenna [*.Cu]_1") == ("keepout antenna", "*")
    assert split_marker("keepout antenna_c [In2.Cu]_1") == ("keepout antenna_c", (IN2,))
    assert split_marker("keepout vent") == ("keepout vent", None)


def test_an_unmarked_name_keeps_its_digits():
    """Without a marker there is no telling pcb's `_1` from a name that ends
    in a number: `keepout rail_1_26` is a real keepout, not `rail_1` stamped."""
    assert split_marker("keepout rail_1_26") == ("keepout rail_1_26", None)
    assert split_marker("keepout antenna_1") == ("keepout antenna_1", None)


def test_a_declaration_resolves_against_the_board_it_is_on():
    assert resolve_marker("*", FOUR) == (frozenset(FOUR), ())
    assert resolve_marker((IN2,), FOUR) == (frozenset((IN2,)), ())
    assert resolve_marker((IN2,), TWO) == (frozenset(), (IN2,))


def test_stackup_order_runs_front_inner_back():
    assert sorted((B, IN2, F, IN1), key=stackup_order) == [F, IN1, IN2, B]


def test_a_rule_area_names_its_base_and_what_it_could_not_honour():
    ra = RuleArea("keepout antenna_c [In2.Cu]_1", "ant_rf", ((0, 0), (1, 0), (1, 1)),
                  frozenset(), frozenset(["fill"]), missing=(IN2,))
    assert ra.base == "keepout antenna_c" and ra.missing == (IN2,)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fragment_layers.py -q`
Expected: FAIL, `ImportError: cannot import name 'layer_marker'`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/board_geometry.py`, add `missing` to `RuleArea` and a `base` property:

```python
    excludes: frozenset[str]             # parts | fill | tracks | vias | pads
    # Declared layers this board does not have, from the name's marker. The
    # region holds on the rest; these are reported, never silently dropped.
    missing: tuple = ()

    @property
    def base(self) -> str:
        """The name without its layer marker or a stamping suffix."""
        return split_marker(self.name)[0]
```

and the helpers, after the class:

```python
import re as _re

# KiCad saves a zone on the layers its board has, so a two-layer module
# fragment cannot hold a keepout on In2 or on every layer of the board that
# will stamp it. The zone name survives both the save and pcb's stamp - which
# appends `_1` after it - so a declaration the layer set cannot hold travels
# there: ` [*.Cu]` for every copper layer, or the declared list.
# The marker, and the `_1` pcb appends directly after it. A trailing number is
# only taken for a stamp when it follows the marker: without one, `rail_1_26`
# is a real name and not `rail_1` stamped.
_MARKER = _re.compile(r"\s*\[([^\]]*)\](_\d+)?")


def stackup_order(layer) -> int:
    """F.Cu first, the inner layers in order, B.Cu last."""
    if layer is CopperLayer.F:
        return 0
    if layer is CopperLayer.B:
        return 31
    return int(layer.value[2:-3])


def layer_marker(declared, board_layers) -> str:
    """What a keepout's zone name must carry so its layers survive: nothing
    when the board holds them all, ` [*.Cu]` for every copper layer, or the
    declared list when the board lacks any of them."""
    if declared is None:
        return " [*.Cu]"
    if set(declared) <= set(board_layers):
        return ""
    return " [%s]" % ",".join(l.value for l in sorted(set(declared), key=stackup_order))


def split_marker(name: str) -> tuple:
    """(base name, declaration). The declaration is "*" for every copper
    layer, a tuple of layers, or None when the name carries no marker."""
    m = _MARKER.search(name)
    if not m:
        return name.strip(), None
    base = (name[:m.start()] + name[m.end():]).strip()
    body = m.group(1).strip()
    if body == "*.Cu":
        return base, "*"
    return base, tuple(CopperLayer.of(x.strip()) for x in body.split(",") if x.strip())


def resolve_marker(declared, board_layers) -> tuple:
    """(layers this board can honour, declared layers it lacks)."""
    if declared == "*":
        return frozenset(board_layers), ()
    have = frozenset(l for l in declared if l in set(board_layers))
    return have, tuple(sorted((l for l in declared if l not in have), key=stackup_order))
```

`board_geometry.py` must import `CopperLayer` from `.values` if it does not already.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_fragment_layers.py -q`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add src/placemat/board_geometry.py tests/test_fragment_layers.py
git commit -m "A keepout's layers, carried in its name where its board cannot hold them"
```

---

## Task 2: Reading a marked rule area

**Files:**
- Modify: `src/placemat/kicad/read.py`
- Test: `tests/test_fragment_layers_kicad.py` (create)

**Interfaces:**
- Consumes: Task 1.
- Produces: `read_board(...).rule_areas` whose `layers` are the resolved declaration and whose `missing` carries what the board lacks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fragment_layers_kicad.py
"""The marker against pcbnew: read, written, and widened on a stamped zone."""
import pytest

from placemat.values import CopperLayer
from tests.conftest import needs_kicad

pytestmark = [needs_kicad]
F, B, IN1, IN2 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1, CopperLayer.IN2


def _board(tmp_path, copper, zones, group=None):
    """A board of `copper` layers carrying rule areas (name, layer ids), the
    lot in one group when `group` is given - which is how a stamp looks."""
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(copper)
    g = None
    if group:
        g = pcbnew.PCB_GROUP(b)
        g.SetName(group)
        b.Add(g)
    for i, (name, layer_ids) in enumerate(zones):
        z = pcbnew.ZONE(b)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for l in layer_ids:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        z.SetDoNotAllowFootprints(False)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)
        o = z.Outline()
        o.NewOutline()
        x = 10.0 * i
        for px, py in ((x, 0), (x + 4, 0), (x + 4, 4), (x, 4)):
            o.Append(pcbnew.FromMM(px), pcbnew.FromMM(py))
        z.SetZoneName(name)
        b.Add(z)
        if g is not None:
            g.AddItem(z)
    path = tmp_path / "layout.kicad_pcb"
    b.Save(str(path))
    return path


def test_a_stamped_all_layer_keepout_reads_on_every_layer_of_the_parent(tmp_path):
    """The W3011 case: declared on every layer in a two-layer module, arriving
    in the four-layer parent on F and B only."""
    import pcbnew
    from placemat.kicad.read import read_board
    path = _board(tmp_path, 4, [("keepout antenna [*.Cu]_1", (pcbnew.F_Cu, pcbnew.B_Cu))],
                  group="ant_rf")
    (ra,) = read_board(path).rule_areas
    assert ra.layers == frozenset((F, IN1, IN2, B))
    assert ra.base == "keepout antenna" and ra.cell == "ant_rf" and ra.missing == ()


def test_a_declared_layer_the_board_lacks_is_kept_as_missing(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    path = _board(tmp_path, 2, [("keepout antenna_c [In2.Cu]", (pcbnew.In2_Cu,))])
    (ra,) = read_board(path).rule_areas
    assert ra.layers == frozenset() and ra.missing == (IN2,)


def test_an_unmarked_rule_area_reads_as_it_always_did(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    path = _board(tmp_path, 4, [("keepout vent", (pcbnew.F_Cu,))])
    (ra,) = read_board(path).rule_areas
    assert ra.layers == frozenset((F,)) and ra.missing == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fragment_layers_kicad.py -q`
Expected: FAIL on the first test: layers read as `{F, B}`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/kicad/read.py` `_rule_areas`, replace the `out.append(RuleArea(...))`:

```python
        excludes = frozenset(name for name, getter in _KEEPOUT_GETTERS if getattr(z, getter)())
        layers = _copper_layers(board, z.GetLayerSet())
        missing = ()
        declared = split_marker(z.GetZoneName())[1]
        if declared is not None:
            # the declaration in the name wins over the layer set KiCad saved:
            # a two-layer fragment could only save F and B
            stack = tuple(CopperLayer.of(board.GetLayerName(l))
                          for l in board.GetEnabledLayers().CuStack())
            layers, missing = resolve_marker(declared, stack)
        out.append(RuleArea(z.GetZoneName(), groups_of.get(_kiid(z)), poly, layers,
                            excludes, missing))
```

and import `resolve_marker, split_marker` from `..board_geometry`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_fragment_layers_kicad.py tests/test_fragment_layers.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/kicad/read.py tests/test_fragment_layers_kicad.py
git commit -m "A stamped keepout reads on the layers it declared, not the ones its module had"
```

---

## Task 3: Writing the marker, and widening a stamped zone

**Files:**
- Modify: `src/placemat/kicad/write.py`
- Test: `tests/test_fragment_layers_kicad.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `_draw_keepouts` names a zone `keepout <name><marker>` and sets a grouped marked zone's layer set to its resolved declaration.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_fragment_layers_kicad.py
def _plan_with(keepout_layers):
    """A resolved plan carrying one keepout, on a synthetic geometry."""
    from placemat.cutouts import Circle
    from placemat.layout import Board
    from placemat.values import Location
    from tests.fixtures import board_geometry
    b = Board(board_geometry([], width=40, height=40), edge_margin=0.0)
    b.keepout(Circle(4.0), "antenna", at=Location(20, 20), layers=keepout_layers,
              why="the antenna clearance")
    return b.resolve()


def test_an_every_layer_keepout_is_written_with_its_marker(tmp_path):
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    path = _board(tmp_path, 2, [])
    board = pcbnew.LoadBoard(str(path))
    _draw_keepouts(board, _plan_with(None))
    names = [z.GetZoneName() for z in board.Zones() if z.GetIsRuleArea()]
    assert names == ["keepout antenna [*.Cu]"]


def test_writing_widens_a_stamped_zone_to_what_it_declared(tmp_path):
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    path = _board(tmp_path, 4, [("keepout antenna [*.Cu]_1", (pcbnew.F_Cu, pcbnew.B_Cu)),
                                ("keepout plain_1", (pcbnew.F_Cu,))], group="ant_rf")
    board = pcbnew.LoadBoard(str(path))
    _draw_keepouts(board, _plan_with(None))
    layers = {z.GetZoneName(): sorted(board.GetLayerName(l) for l in z.GetLayerSet().CuStack())
              for z in board.Zones() if z.GetIsRuleArea()}
    assert layers["keepout antenna [*.Cu]_1"] == ["B.Cu", "F.Cu", "In1.Cu", "In2.Cu"]
    assert layers["keepout plain_1"] == ["F.Cu"]            # no marker: left alone
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fragment_layers_kicad.py -q -k "written_with or widens"`
Expected: FAIL: the name has no marker, and the stamped zone stays on F and B

- [ ] **Step 3: Write minimal implementation**

In `_draw_keepouts`, after deleting placemat's own zones, widen the grouped ones:

```python
    stack = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack())
    for z in board.Zones():
        if not (z.GetIsRuleArea() and _kiid(z) in grouped):
            continue
        declared = split_marker(z.GetZoneName())[1]
        if declared is None:
            continue
        want, _ = resolve_marker(declared, stack)
        have = {CopperLayer.of(board.GetLayerName(l)) for l in z.GetLayerSet().CuStack()}
        if want - have:                 # only ever widened, to what it declared
            z.SetLayerSet(_layer_set(board, tuple(sorted(want | have, key=stackup_order))))
```

and name each new zone with its marker:

```python
        z.SetZoneName("keepout %s%s" % (k.name, layer_marker(k.layers, stack)))
```

importing `layer_marker, resolve_marker, split_marker, stackup_order` from `..board_geometry` and `CopperLayer` from `..values`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/kicad/write.py tests/test_fragment_layers_kicad.py
git commit -m "Write the marker, and widen a stamped zone to the layers it declared"
```

---

## Task 4: Names and findings in the layout

**Files:**
- Modify: `src/placemat/layout.py`
- Test: `tests/test_fragment_layers.py`

**Interfaces:**
- Consumes: Task 1 and `RuleArea.missing`.
- Produces: the clash check compares base names; a script keepout on a missing layer and a stamped rule area with `missing` each add a finding.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_fragment_layers.py
import dataclasses

import pytest

from placemat.layout import Board
from placemat.values import Location
from tests.fixtures import board_geometry


def _shape():
    from placemat.cutouts import Circle
    return Circle(4.0)


def _geom(copper, rule_areas=()):
    g = board_geometry([], width=40, height=40)
    return dataclasses.replace(g, layers=tuple(copper), rule_areas=tuple(rule_areas))


def test_the_clash_check_sees_a_stamped_marked_name_as_the_same_keepout():
    stamped = RuleArea("keepout antenna [*.Cu]_1", "ant_rf", ((0, 0), (4, 0), (4, 4)),
                       frozenset(TWO), frozenset(["fill"]))
    b = Board(_geom(FOUR, [stamped]), edge_margin=0.0)
    with pytest.raises(ValueError):
        b.keepout(_shape(), "antenna", at=Location(20, 20), why="clearance")


def test_a_keepout_on_a_layer_the_board_lacks_is_a_finding():
    b = Board(_geom(TWO), edge_margin=0.0)
    b.keepout(_shape(), "antenna_c", at=Location(20, 20), layers=(IN2,), why="Detail C")
    plan = b.resolve()
    said = [f for f in plan.findings if "antenna_c" in f]
    assert said and "In2.Cu" in said[0] and "recorded in its name" in said[0]


def test_a_stamped_keepout_the_parent_cannot_honour_is_a_finding():
    stamped = RuleArea("keepout shield [In5.Cu]_1", "rf", ((0, 0), (4, 0), (4, 4)),
                       frozenset(), frozenset(["fill"]), missing=(CopperLayer.IN5,))
    plan = Board(_geom(FOUR, [stamped]), edge_margin=0.0).resolve()
    said = [f for f in plan.findings if "shield" in f]
    assert said and "In5.Cu" in said[0] and "rf" in said[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fragment_layers.py -q`
Expected: FAIL on all three

- [ ] **Step 3: Write minimal implementation**

In `Board.keepout`, compare base names:

```python
        clash = [r for r in self.geometry.rule_areas if r.base == "keepout %s" % name]
```

In `Board.resolve`, where findings for keepouts are gathered (the keepout loop near `plan.findings.append("%s (keepout): %s" ...)`), add, once per resolve:

```python
        board_layers = set(self.geometry.layers)
        for k in self._keepouts.values():
            lost = [l for l in (k.layers or ()) if l not in board_layers]
            if lost:
                plan.findings.append(
                    "keepout %s declares %s, which this %d-layer board does not have: recorded in "
                    "its name, and honoured by a board that has it"
                    % (k.name, ", ".join(l.value for l in sorted(lost, key=stackup_order)),
                       len(self.geometry.layers)))
        for r in self.geometry.rule_areas:
            if r.missing:
                plan.findings.append(
                    "%s from the %s cell declares %s, which this board does not have either"
                    % (r.base, r.cell or "board", ", ".join(l.value for l in r.missing)))
```

importing `stackup_order` from `.board_geometry`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_fragment_layers.py
git commit -m "A keepout's lost layer is a finding, and a stamped name clashes by its base"
```

---

## Task 5: Documentation and version

**Files:**
- Modify: `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, `skills/placemat/references/migration.md`, `src/placemat/__init__.py`, `.claude-plugin/*.json`
- Test: `tests/test_fragment_layers.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_fragment_layers.py
def test_the_docs_describe_the_marker():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "[*.Cu]" in api
    assert "## To 0.17" in Path("skills/placemat/references/migration.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fragment_layers.py -q -k docs`
Expected: FAIL

- [ ] **Step 3: Write the docs**

`api.md`, Keepouts section, a paragraph: a keepout declared on every copper
layer is written as `keepout <name> [*.Cu]`, and one on layers its board lacks
lists them; the name carries what the layer set cannot, because KiCad saves a
zone on the layers its board has and a module fragment has two. A board that
stamps the module reads the declaration and widens the zone to match. A layer
that still cannot be honoured is a finding.

`SKILL.md`, in the keepout bullet: a module's keepout needs no restating in
the parent; run the module's script once so its keepouts carry the marker.

`migration.md`, `## To 0.17`: keepout names gain a marker; re-run each module's
script, then regenerate and re-run the boards that stamp it; a parent's hand
copy of a module's keepout can come out.

- [ ] **Step 4: Bump and run everything**

```bash
sed -i 's/__version__ = "0.16.0"/__version__ = "0.17.0"/' src/placemat/__init__.py
sed -i 's/"version": "0.16.0"/"version": "0.17.0"/' .claude-plugin/plugin.json .claude-plugin/marketplace.json
uv pip install -q -e .
.venv/bin/python -m pytest -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Plugin 0.17.0: a module's keepout holds on the parent's inner layers"
```

---

## Acceptance criteria

1. `.venv/bin/python -m pytest -q` passes in full.
2. `layers=None` writes `keepout <name> [*.Cu]`; explicit layers the board lacks
   write the declared list in stackup order; explicit layers it has write none.
3. A name with a marker and a `_1` suffix splits into base and declaration.
4. A stamped `keepout antenna [*.Cu]_1` on F and B reads on all four layers of
   a four-layer board.
5. Writing a four-layer board widens that grouped zone to all four layers, and
   leaves an unmarked grouped zone and every unmarked layer set alone.
6. A declared layer the board lacks is `RuleArea.missing`, never silently
   dropped.
7. A script keepout on a layer its board lacks is a finding saying it is
   recorded in its name.
8. A stamped rule area the parent cannot honour is a finding naming the cell.
9. The clash check matches a stamped marked name against the plain one.
10. Against the real Breakout generation, a marked zone planted in the
    PowerDrop fragment arrives marked in all three power-drop cells (already
    verified during design; re-verified at the end).
11. `api.md`, `SKILL.md` and `migration.md` carry the marker and `## To 0.17`.
12. No commit mentions Claude, Anthropic or a session.
