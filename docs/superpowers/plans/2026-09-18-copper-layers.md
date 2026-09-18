# Copper Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let placemat name every copper layer KiCad can have, and make a layer it cannot name an error rather than something silently dropped.

**Architecture:** `CopperLayer` keeps its str-Enum behaviour and gains every inner layer KiCad supports. KiCad's maximum is 32 copper layers, named `F.Cu`, `In1.Cu` through `In30.Cu`, `B.Cu`, so the members are generated once from that known set rather than the type being restructured. The two places that read layers off a board stop swallowing names they do not recognise.

**Tech Stack:** Python 3.12+, `uv run python -m pytest`, pcbnew (KiCad 10), `uvx ruff`.

**Spec:** `docs/superpowers/specs/2026-09-18-keepouts-design.md`, section "What placemat does with more than four copper layers". This plan implements that section only; keepouts themselves are a separate plan.

## Global Constraints

- Punctuation is plain ASCII: no em dashes, en dashes, unicode arrows, curly quotes or ellipsis characters. Use `-` with spaces, and `->`.
- Docstrings follow the codebase's voice: say what a thing does and why it is that way. No defensive over-explanation.
- An error raised at a script's expense names what to use instead.
- `CopperLayer.F` and `CopperLayer.B` keep their names and their identity. They are the only members named anywhere in the code, and they are bound to faces.
- The full suite must stay green after every task: `uv run python -m pytest -q`. Baseline at the start of this plan is 365 passed.
- Lint on touched files stays clean: `uvx ruff check --select F401,F811,F821 src/placemat tests`.
- Commit after each task. Commit messages carry no reference to Claude, Anthropic or any session URL.

## File Structure

| file | change |
|---|---|
| `src/placemat/values.py` | `CopperLayer` gains every inner layer; its methods stop naming the class by its global name |
| `src/placemat/kicad/read.py` | stops discarding layers it cannot name, at both sites |
| `tests/test_layers.py` | new: what the type names, and what reading a board does with a deep stackup |
| `skills/placemat/references/api.md` | the documented layer set |

Nothing else changes. `write.py` uses `layer.value` through `_layer_id`, which is unaffected, and `occupancy.py` names only `F` and `B`.

---

### Task 1: The type names every layer KiCad can have

**Files:**
- Modify: `src/placemat/values.py` (the `CopperLayer` class)
- Test: `tests/test_layers.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `CopperLayer.F`, `CopperLayer.B` unchanged in name, value and identity
  - `CopperLayer.IN1` .. `CopperLayer.IN30`, values `"In1.Cu"` .. `"In30.Cu"`
  - `CopperLayer.of(name)` resolves any of those, and raises `ValueError` naming the layer for anything else
  - `.face` -> `Face.FRONT` / `Face.BACK` / `None`; `.other_face` unchanged
  - members remain `str` instances and remain hashable

- [ ] **Step 1: Write the failing test**

Create `tests/test_layers.py`:

```python
"""What copper layers placemat can name, and what it does with a board that
has more of them than it expects."""
import pytest

from placemat.values import CopperLayer, Face


def test_every_layer_kicad_can_have_is_nameable():
    """KiCad's maximum is 32 copper layers: the two faces and In1 to In30."""
    assert len(CopperLayer) == 32
    assert CopperLayer.of("In30.Cu").value == "In30.Cu"
    assert CopperLayer.of("In7.Cu") is CopperLayer.IN7


def test_the_faces_keep_their_names_and_their_faces():
    assert CopperLayer.F.value == "F.Cu" and CopperLayer.B.value == "B.Cu"
    assert CopperLayer.F.face is Face.FRONT and CopperLayer.B.face is Face.BACK
    assert CopperLayer.F.other_face is CopperLayer.B
    assert CopperLayer.B.other_face is CopperLayer.F


def test_an_inner_layer_has_no_face_and_no_opposite():
    assert CopperLayer.IN7.face is None
    with pytest.raises(ValueError, match="inner layer"):
        CopperLayer.IN7.other_face


def test_a_layer_that_is_not_copper_is_refused_by_name():
    with pytest.raises(ValueError, match="F.SilkS"):
        CopperLayer.of("F.SilkS")
    with pytest.raises(ValueError, match="In31.Cu"):
        CopperLayer.of("In31.Cu")          # past KiCad's own maximum


def test_a_layer_is_still_a_string_and_still_hashable():
    """Everything downstream treats a layer as its KiCad name."""
    assert isinstance(CopperLayer.IN7, str) and CopperLayer.IN7 == "In7.Cu"
    assert len(frozenset([CopperLayer.F, CopperLayer.IN7, CopperLayer.F])) == 2
    assert CopperLayer.of(CopperLayer.IN7) is CopperLayer.IN7
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_layers.py -q`
Expected: FAIL - `len(CopperLayer)` is 4, and `CopperLayer.of("In7.Cu")` raises.

- [ ] **Step 3: Implement**

In `src/placemat/values.py`, replace the whole `CopperLayer` class with:

```python
class _CopperLayerNames(str, Enum):
    """The behaviour of a copper layer, without its members: they are
    generated below, because there are thirty-two of them and writing them
    out would be thirty-two lines of noise."""

    @property
    def face(self) -> "Face | None":
        if self is type(self).F:
            return Face.FRONT
        if self is type(self).B:
            return Face.BACK
        return None

    @property
    def other_face(self) -> "CopperLayer":
        if self is type(self).F:
            return type(self).B
        if self is type(self).B:
            return type(self).F
        raise ValueError("%s is an inner layer; it has no opposite face" % self.value)

    @classmethod
    def of(cls, name: "str | CopperLayer") -> "CopperLayer":
        if isinstance(name, cls):
            return name
        for member in cls:
            if member.value == name:
                return member
        raise ValueError("unknown copper layer %r: the layers are F.Cu, In1.Cu to In30.Cu, and B.Cu"
                         % (name,))


# KiCad's maximum is 32 copper layers, and it names them F.Cu, In1.Cu upward,
# and B.Cu. Naming all of them is what stops a board with a deep stackup
# being read as though the layers placemat has no name for were not there.
_COPPER_LAYER_NAMES = {"F": "F.Cu", "B": "B.Cu"}
_COPPER_LAYER_NAMES.update({"IN%d" % n: "In%d.Cu" % n for n in range(1, 31)})

CopperLayer = _CopperLayerNames("CopperLayer", _COPPER_LAYER_NAMES)
```

`type(self)` rather than `CopperLayer` because the methods are defined before
the name exists.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest tests/test_layers.py -q && uv run python -m pytest -q`
Expected: the new tests pass and the whole suite stays green.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/values.py tests/test_layers.py
git commit -m "A copper layer can be any layer KiCad can have

F and B keep their names, their values and their identity; the inner
layers are generated because KiCad tops out at 32 of them and writing
them out is 32 lines of noise."
```

---

### Task 2: Reading a board no longer drops layers it cannot name

**Files:**
- Modify: `src/placemat/kicad/read.py:39-47` (`_copper_layers`), `src/placemat/kicad/read.py:269-270` (the layer tuple)
- Test: `tests/test_layers.py`

**Interfaces:**
- Consumes: `CopperLayer.of` from Task 1
- Produces: `read_board` on a board of any copper count returns `BoardGeometry.layers` with one entry per copper layer, in stack order, and copper items carry the layer they are actually on. A copper layer name that is not a copper layer at all raises `ValueError` from `CopperLayer.of`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_layers.py`:

```python
import pcbnew    # noqa: E402  (at the top of the file with the others)


def _board_with(tmp_path, copper_layers, tracks):
    """A board of `copper_layers` copper layers carrying a track on each of
    `tracks` (pcbnew layer ids), saved and handed back as a path."""
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(copper_layers)

    def vec(x, y):
        return pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6))

    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(vec(*a))
        s.SetEnd(vec(*c))
        b.Add(s)
    net = pcbnew.NETINFO_ITEM(b, "SIG")
    b.Add(net)
    for n, layer in enumerate(tracks):
        t = pcbnew.PCB_TRACK(b)
        t.SetLayer(layer)
        t.SetWidth(200000)
        t.SetStart(vec(5.0, 5.0 + n))
        t.SetEnd(vec(30.0, 5.0 + n))
        t.SetNetCode(net.GetNetCode())
        b.Add(t)
    path = tmp_path / "stack.kicad_pcb"
    b.Save(str(path))
    return path


def test_a_six_layer_board_reads_as_six_layers(tmp_path):
    """The defect this fixes: In3 and In4 used to be dropped on the floor,
    and an item on one of them came back belonging to no layer at all."""
    from placemat.kicad.read import read_board
    pcb = _board_with(tmp_path, 6, [pcbnew.In1_Cu, pcbnew.In3_Cu])
    g = read_board(pcb)
    assert [l.value for l in g.layers] == ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]
    on = sorted(sorted(x.value for x in c.layers) for c in g.copper if c.kind == "track")
    assert on == [["In1.Cu"], ["In3.Cu"]]


def test_a_thirty_two_layer_board_reads_as_thirty_two(tmp_path):
    from placemat.kicad.read import read_board
    pcb = _board_with(tmp_path, 32, [pcbnew.In30_Cu])
    g = read_board(pcb)
    assert len(g.layers) == 32
    assert g.layers[0] is CopperLayer.F and g.layers[-1] is CopperLayer.B
    (track,) = [c for c in g.copper if c.kind == "track"]
    assert track.layers == frozenset([CopperLayer.IN30])


def test_a_two_layer_board_is_unchanged(tmp_path):
    from placemat.kicad.read import read_board
    pcb = _board_with(tmp_path, 2, [pcbnew.F_Cu])
    g = read_board(pcb)
    assert [l.value for l in g.layers] == ["F.Cu", "B.Cu"]
```

Mark the file so it skips without KiCad, matching the other tests: add
`from tests.conftest import needs_kicad` and put
`@needs_kicad` on the three board tests (the four type tests in Task 1 need no
KiCad and must keep running without it).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_layers.py -q -k "six_layer or thirty_two"`
Expected: FAIL - the six-layer board reads four layers, and the In3 track has an empty layer set.

- [ ] **Step 3: Implement**

In `src/placemat/kicad/read.py`, `_copper_layers` currently swallows the error:

```python
def _copper_layers(board, layer_set) -> frozenset[CopperLayer]:
    out = set()
    for name in _layer_names(board, layer_set):
        try:
            out.add(CopperLayer.of(name))
        except ValueError:
            continue
    return frozenset(out)
```

becomes

```python
def _copper_layers(board, layer_set) -> frozenset[CopperLayer]:
    """The copper layers of a layer set. A set names the non-copper layers an
    item is on too - silk, mask, paste - and those are skipped by name; a
    copper layer that cannot be named is a defect, not something to drop."""
    out = set()
    for name in _layer_names(board, layer_set):
        if not name.endswith(".Cu"):
            continue                       # silk, mask, paste: not this function's business
        out.add(CopperLayer.of(name))
    return frozenset(out)
```

and the layer tuple at line 269 stops filtering:

```python
    layers = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack())
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest -q`
Expected: all pass, including the breakout board tests, which read a real
four-layer board through both of these paths.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/kicad/read.py tests/test_layers.py
git commit -m "Reading a board no longer drops the layers it cannot name

Both sites discarded a copper layer whose name placemat had no member
for. A six-layer board read as four, and a track on In3 came back
belonging to no layer at all: the board loaded, placed and reported
clean while two layers of copper were invisible.

Non-copper layers are still skipped, by name rather than by failing to
parse. A copper layer that cannot be named is now an error."
```

---

### Task 3: The documented layer set

**Files:**
- Modify: `skills/placemat/references/api.md:536`
- Test: none; this is prose. The suite must still pass.

**Interfaces:**
- Consumes: Task 1
- Produces: nothing code depends on

- [ ] **Step 1: Correct the documented set**

`api.md:536` currently reads:

```
`CopperLayer.F / IN1 / IN2 / B`, `Face.FRONT / BACK`, `Edge.NORTH / SOUTH / EAST / WEST`.
```

Replace with:

```
`CopperLayer.F / IN1 .. IN30 / B` (the faces and every inner layer KiCad
allows; a board uses as many as its stackup has), `Face.FRONT / BACK`,
`Edge.NORTH / SOUTH / EAST / WEST`.
```

- [ ] **Step 2: Check nothing else claims four layers**

Run: `grep -rniE "IN1 / IN2|four.layer|4.layer" skills/ src/ README.md`
Expected: no hit that describes the layer set as four. Fix any that appear.

- [ ] **Step 3: Run the suite and lint**

Run: `uv run python -m pytest -q && uvx ruff check --select F401,F811,F821 src/placemat tests`
Expected: all pass; lint reports only the findings that predate this work
(`CopperOp`, `polygon_box`, `Net`, `field`, `sys`).

- [ ] **Step 4: Commit**

```bash
git add skills/placemat/references/api.md
git commit -m "The documented layer set is every layer, not four"
```

---

## Self-review notes

**Spec coverage.** The spec section names two defects - `read.py:39` swallowing
the `ValueError` and `read.py:269` filtering by the enum's values - and both
are Task 2. It names the type's four members as the cause, which is Task 1. It
says `F` and `B` are the only members named in code and must stay, which Task 1
preserves and `tests/test_layers.py` asserts.

**Not in this plan, deliberately.** The spec's recommendation is scoped to
naming and reading. It does not ask for a way to *declare* a stackup, or for
`board.plane(layers=)` to accept anything new - it already takes whatever
`CopperLayer` members exist, so it gains the new layers for free.

**One risk.** `_copper_layers` is called with layer sets that include non-copper
layers, so Task 2 replaces a `try/except` with an explicit `.endswith(".Cu")`
test. If any copper layer in a real board is named something that does not end
`.Cu`, the new code raises where the old one continued. The breakout board test
in the suite reads a real four-layer board through this path and is the check
on that.
