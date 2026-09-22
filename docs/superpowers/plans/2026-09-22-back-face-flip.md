# Back-Face Flip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a flip to the back one operation - mirror about the vertical axis, then turn by `rotation=` - so the planner and the writer agree, and a part and a cell flip the same way.

**Architecture:** Two lines. The planner adds the reference rotation instead of subtracting it when flipping, which removes the generated-rotation term; the writer stops discarding the orientation KiCad's own flip computed. A cell's reference rotation is always 0, so cells are untouched and no branch by kind is needed. The deliverable is the parity test, not the edit.

**Tech Stack:** Python 3.12, pytest, pcbnew (only under `src/placemat/kicad/`).

**Spec:** `docs/superpowers/specs/2026-09-22-back-face-flip-design.md`

**Depends on:** `docs/superpowers/plans/2026-09-22-keepouts-that-hold.md` should land first. Both change what boards look like; sequencing them means the next re-place has one cause.

## Global Constraints

- `pcbnew` may be imported only under `src/placemat/kicad/`.
- A flip to the back mirrors about the **vertical** axis (`FLIP_DIRECTION_LEFT_RIGHT`), for a part and a cell alike. This matches `editing.flip_left_right: true`, the shipped KiCad default in 7, 9 and 10.
- `rotation=` is applied AFTER the mirror. KiCad's orientation field therefore reads `rotation + 180` for a back-face part, which is what its own F key produces.
- `_move_cell` is not modified.
- The transform must not depend on the rotation the generator left a part at.
- ASCII only in prose, comments and commit messages: no em dashes, no en dashes, no unicode arrows, straight quotes.
- Commit messages must contain no reference to Claude, Anthropic, or a session URL.
- Run the suite with `.venv/bin/python -m pytest -q`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/placemat/occupancy.py` (modify) | `_transform`: add the reference rotation when flipping |
| `src/placemat/kicad/write.py` (modify) | `_place_footprint`: keep the flip's orientation |
| `tests/test_faces.py` (modify) | the transform, without KiCad |
| `tests/test_flip_parity.py` (create) | planner-against-writer parity, with KiCad |
| `skills/placemat/references/api.md`, `SKILL.md`, `references/migration.md` (modify) | documentation |

---

## Task 1: The planner's transform loses the generated-rotation term

**Files:**
- Modify: `src/placemat/occupancy.py:153-161`
- Test: `tests/test_faces.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Occupancy._transform` unchanged in signature; flipped placements now compose to `R(rotation) . mirror_x . relative pads`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_faces.py
import math


def _turned(fp, degrees):
    """The same footprint with its pads actually rotated to match a generated
    rotation. `tests.fixtures.footprint` writes the rotation into the
    Footprint field but lays its pads out at rotation 0 whatever it is given,
    which is fine for tests that never ask what the rotation MEANS - and no
    use at all here, where the whole question is whether the transform undoes
    the generator's rotation correctly."""
    import dataclasses
    from placemat.board_geometry import PadGeom
    from placemat.values import Box
    r = math.radians(degrees)
    cos, sin = math.cos(r), math.sin(r)
    o = fp.location

    def turn(x, y):
        dx, dy = x - o.x, y - o.y
        return (o.x + dx * cos + dy * sin, o.y - dx * sin + dy * cos)

    pads = []
    for p in fp.pads:
        outs = tuple(tuple(turn(x, y) for x, y in poly) for poly in p.outlines)
        pads.append(dataclasses.replace(p, outlines=outs,
                                        box=Box.of_points([q for po in outs for q in po])))
    return dataclasses.replace(fp, rotation=float(degrees), pads=tuple(pads))


def _pad_after_flip(generated_rotation, target_rotation):
    """Where the occupancy model puts an asymmetric pad when the part is
    flipped to the back, with the part's origin left where it was."""
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    fp = _turned(footprint("U1", 20.0, 20.0, w=6, h=2, inst="u1", nets=("A", "B")),
                 generated_rotation)
    occ = Occupancy(board_geometry([fp], width=60, height=60), edge_margin=0.0)
    occ.commit(fp, Placement(Location(20.0, 20.0), target_rotation, Face.BACK))
    return occ.pad_location("U1", "1")


def test_a_flip_does_not_depend_on_the_rotation_the_generator_left():
    """The same declaration must mean the same physical orientation whatever
    the generator happened to do, or a script cannot say what it means."""
    at_zero = _pad_after_flip(0.0, 0.0)
    for r in (90.0, 180.0, 270.0):
        moved = _pad_after_flip(r, 0.0)
        assert abs(moved.x - at_zero.x) < 1e-6 and abs(moved.y - at_zero.y) < 1e-6, r


def test_a_flip_mirrors_about_the_vertical_axis():
    """KiCad's F key, and what a cell already does. Pad 1 is on the west end
    at rotation 0, so after a left-right mirror about the origin it is east."""
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    fp = footprint("U1", 20.0, 20.0, w=6, h=2, inst="u1", nets=("A", "B"))
    occ = Occupancy(board_geometry([fp], width=60, height=60), edge_margin=0.0)
    front = occ.pad_location("U1", "1")
    assert front.x < 20.0                                   # west of the origin
    occ.commit(fp, Placement(Location(20.0, 20.0), 0.0, Face.BACK))
    back = occ.pad_location("U1", "1")
    assert back.x > 20.0                                    # mirrored to the east
    assert abs(back.y - front.y) < 1e-6                     # and not in y


def test_an_unflipped_placement_is_unchanged_at_every_generated_rotation():
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    for r in (0.0, 90.0, 180.0, 270.0):
        fp = _turned(footprint("U1", 20.0, 20.0, w=6, h=2, inst="u1", nets=("A", "B")), r)
        occ = Occupancy(board_geometry([fp], width=60, height=60), edge_margin=0.0)
        before = occ.pad_location("U1", "1")
        occ.commit(fp, Placement(Location(20.0, 20.0), r, Face.FRONT))    # same place, same face
        after = occ.pad_location("U1", "1")
        assert abs(after.x - before.x) < 1e-6 and abs(after.y - before.y) < 1e-6, r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_faces.py -q -k "flip"`
Expected: `test_a_flip_does_not_depend_on_the_rotation_the_generator_left` FAILS at `r=90` - the transform carries a `-2r` term. The other three pass already.

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/occupancy.py`, replace `_transform`:

```python
    @staticmethod
    def _transform(geom: ItemGeometry, placement: Placement) -> Transform:
        """Where an item's shapes go when it moves to `placement`.

        A flip to the back mirrors about the VERTICAL axis and then turns by
        the rotation asked for - KiCad's own F key, and what the writer does
        once it stops discarding the orientation the flip computed. Adding the
        reference rotation rather than subtracting it is what cancels the
        generator's own rotation out of the answer, so the same declaration
        means the same orientation whatever the generator happened to do.

        A cell's reference rotation is always 0, so this is identical to the
        unflipped arithmetic for a cell and nothing about cells changes."""
        ref = geom.reference
        t = Transform.translate(-ref.location.x, -ref.location.y)
        flip = placement.face != ref.face
        if flip:
            t = t.then(Transform.mirror_x(Location(0, 0)))
        turn = placement.rotation + ref.rotation if flip else placement.rotation - ref.rotation
        t = t.then(Transform.rotate(turn))
        return t.then(Transform.translate(placement.location.x, placement.location.y))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_faces.py tests/test_occupancy.py tests/test_pockets.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/occupancy.py tests/test_faces.py
git commit -m "A flip means the same thing whatever rotation the generator left"
```

---

## Task 2: The writer keeps the orientation the flip computed

**Files:**
- Modify: `src/placemat/kicad/write.py:39-43`
- Create: `tests/test_flip_parity.py`

**Interfaces:**
- Consumes: the transform from Task 1.
- Produces: `_place_footprint` sets `target.rotation + 180` after a flip.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_flip_parity.py
"""The planner and the writer must agree about a back-face part.

The occupancy model decides legality, clearance and copper endpoints from one
answer and KiCad gets another, so a disagreement here is not a cosmetic one:
every via-in-pad, every Pin() placement and every clearance the model judged
inherits it. These tests write a real board and read it back, because the only
authority on what KiCad did is KiCad."""
import shutil

import pytest

from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Cell, Face, Location, Part
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]

ROTATIONS = (0.0, 90.0, 180.0, 270.0)


def _copy(src, tmp_path):
    dst = tmp_path / "layout.kicad_pcb"
    shutil.copy(src, dst)
    pro = src.with_suffix(".kicad_pro")
    if pro.exists():
        shutil.copy(pro, tmp_path / "layout.kicad_pro")
    return dst


def _by_generated_rotation(geometry):
    """One multi-pad front footprint at each generated rotation. On the
    committed Breakout these are U7 at 0, U2 at 90, U8 at 180 and U5 at 270."""
    out = {}
    for fp in geometry.footprints:
        if len(fp.pads) >= 3 and fp.face is Face.FRONT:
            out.setdefault(fp.rotation % 360, fp)
    return out


def _parity(pcb, inst, rotation, face):
    """Place one part, write, read back, and return the worst disagreement in
    mm between what the occupancy model planned and what the file holds."""
    before = read_board(pcb)
    fp = before.footprint(inst)
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.place(Part(inst), at=Location(fp.location.x, fp.location.y), rotation=rotation, face=face)
    plan = b.resolve()
    planned = {p.number: plan.occupancy.pad_location(fp.ref, p.number) for p in fp.pads}
    apply_plan(pcb, plan)
    after = read_board(pcb).footprint(inst)
    return max(abs(p.box.center.x - planned[p.number].x) + abs(p.box.center.y - planned[p.number].y)
               for p in after.pads)


@pytest.mark.parametrize("generated", ROTATIONS)
@pytest.mark.parametrize("target", ROTATIONS)
def test_a_back_face_part_lands_where_the_planner_said(breakout_pcb, tmp_path, generated, target):
    pcb = _copy(breakout_pcb, tmp_path)
    cands = _by_generated_rotation(read_board(pcb))
    if generated not in cands:
        pytest.skip("the Breakout has no multi-pad front part at rotation %g" % generated)
    worst = _parity(pcb, cands[generated].inst, target, Face.BACK)
    assert worst < 1e-5, "generated %g, target %g: worst pad error %.6f mm" % (generated, target, worst)


@pytest.mark.parametrize("generated", ROTATIONS)
@pytest.mark.parametrize("target", ROTATIONS)
def test_a_front_face_part_is_undisturbed(breakout_pcb, tmp_path, generated, target):
    pcb = _copy(breakout_pcb, tmp_path)
    cands = _by_generated_rotation(read_board(pcb))
    if generated not in cands:
        pytest.skip("the Breakout has no multi-pad front part at rotation %g" % generated)
    worst = _parity(pcb, cands[generated].inst, target, Face.FRONT)
    assert worst < 1e-5, "generated %g, target %g: worst pad error %.6f mm" % (generated, target, worst)


@pytest.mark.parametrize("target", ROTATIONS)
def test_a_cell_flipped_to_the_back_lands_where_the_planner_said(breakout_pcb, tmp_path, target):
    """Cells were already right. This is here so that is checked, not assumed:
    if it fails, the cell path needs its own fix."""
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    cell = before.cell("power_drop0")
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.place(Cell("power_drop0"), at=Centre(cell.box.center.x, cell.box.center.y),
            rotation=target, face=Face.BACK)
    plan = b.resolve()
    planned = {(fp.ref, p.number): plan.occupancy.pad_location(fp.ref, p.number)
               for fp in cell.members for p in fp.pads}
    apply_plan(pcb, plan)
    after = read_board(pcb).cell("power_drop0")
    worst = max(abs(p.box.center.x - planned[(fp.ref, p.number)].x)
                + abs(p.box.center.y - planned[(fp.ref, p.number)].y)
                for fp in after.members for p in fp.pads)
    assert worst < 1e-5, "target %g: worst pad error %.6f mm" % (target, worst)
```

Add `Centre` to the `placemat.values` import line in that file.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_flip_parity.py -q`
Expected: the back-face cases FAIL. After Task 1 the planner mirrors x and turns
by `t + r`, while the writer still turns by `t` after a y-mirror, so every
back-face combination is wrong by 180.

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/kicad/write.py`:

```python
def _place_footprint(fp, current: Placement, target: Placement):
    """Move one footprint. A flip to the back mirrors about the VERTICAL axis,
    which is what KiCad's own F key does (`editing.flip_left_right`, true by
    default in KiCad 7, 9 and 10) and what `_move_cell` already does to a
    cell's items.

    `Flip` computes the orientation that mirror implies - 180 for a part that
    was upright - and the rotation asked for is applied on top of it. Setting
    the orientation to `target.rotation` alone would discard the flip's half
    turn and quietly mirror the part top-to-bottom instead."""
    if target.face != current.face:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(target.rotation + 180)
    else:
        fp.SetOrientationDegrees(target.rotation)
    fp.SetPosition(vec(target.location.x, target.location.y))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_flip_parity.py -q`
Expected: PASS - 36 cases (16 back, 16 front, 4 cell), none skipped on the
committed Breakout.

Then the whole suite: `.venv/bin/python -m pytest -q`

- [ ] **Step 5: Commit**

```bash
git add src/placemat/kicad/write.py tests/test_flip_parity.py
git commit -m "The writer keeps the orientation KiCad's flip computed"
```

---

## Task 3: A part and a cell containing it flip the same way

**Files:**
- Modify: `tests/test_flip_parity.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: no new code interface. This task is a test; it is expected to pass once Tasks 1 and 2 are in, and it exists because it is the test that would have caught the asymmetry.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_flip_parity.py

def test_a_part_and_a_cell_holding_it_flip_the_same_way(breakout_pcb, tmp_path):
    """The asymmetry this work removed: a lone part used to mirror
    top-to-bottom and the same part inside a cell left-to-right, so the two
    differed by half a turn and nothing said so."""
    from placemat.geometry import Transform
    from placemat.values import Location as L
    pcb = _copy(breakout_pcb, tmp_path)
    geometry = read_board(pcb)
    fp = _by_generated_rotation(geometry)[0.0]
    cell = geometry.cell("power_drop0")

    def offsets(occ, ref, pads, origin):
        return sorted((round(occ.pad_location(ref, p.number).x - origin.x, 6),
                       round(occ.pad_location(ref, p.number).y - origin.y, 6)) for p in pads)

    # the part alone, flipped to the back at its own origin
    alone = Occupancy(geometry, edge_margin=0.0)
    alone.commit(fp, Placement(L(30.0, 30.0), 0.0, Face.BACK))
    part_offsets = offsets(alone, fp.ref, fp.pads, L(30.0, 30.0))

    # the same part's shapes, mirrored left-right about a point by hand
    t = (Transform.translate(-fp.location.x, -fp.location.y)
         .then(Transform.mirror_x(L(0, 0)))
         .then(Transform.rotate(fp.rotation))
         .then(Transform.translate(30.0, 30.0)))
    by_hand = sorted((round(t.apply_location(p.box.center).x - 30.0, 6),
                      round(t.apply_location(p.box.center).y - 30.0, 6)) for p in fp.pads)
    assert part_offsets == by_hand, "a lone part does not mirror about the vertical axis"

    # and a cell mirrors the same way: its members' offsets from the cell centre
    # are the left-right mirror of what they were
    before = {m.ref: [(round(p.box.center.x - cell.box.center.x, 6),
                       round(p.box.center.y - cell.box.center.y, 6)) for p in m.pads]
              for m in cell.members}
    occ = Occupancy(geometry, edge_margin=0.0)
    occ.commit(cell, Placement(cell.box.center, 0.0, Face.BACK))
    for m in cell.members:
        after = sorted((round(occ.pad_location(m.ref, p.number).x - cell.box.center.x, 6),
                        round(occ.pad_location(m.ref, p.number).y - cell.box.center.y, 6))
                       for p in m.pads)
        expect = sorted((round(-x, 6), y) for x, y in before[m.ref])
        assert after == expect, "%s: a cell does not mirror about the vertical axis" % m.ref
```

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash && .venv/bin/python -m pytest tests/test_flip_parity.py -q -k "same_way"; git stash pop`
Expected: FAIL on the old code with "a lone part does not mirror about the
vertical axis". This step proves the test has teeth; it passes on the new code.

- [ ] **Step 3: Write minimal implementation**

None. Tasks 1 and 2 satisfy this test. If it fails after them, stop: the cell
path needs its own fix and that is a finding, not something to patch here.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_flip_parity.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_flip_parity.py
git commit -m "A part and a cell holding it flip about the same axis"
```

---

## Task 4: Documentation

**Files:**
- Modify: `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, `skills/placemat/references/migration.md`
- Test: `tests/test_flip_parity.py`

**Interfaces:** no new code interface.

- [ ] **Step 1: Write the failing test**

Put this one in `tests/test_faces.py`, which has no module-level skip marks,
so it runs without KiCad:

```python
# append to tests/test_faces.py

def test_the_docs_say_what_a_flip_means():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "vertical axis" in api and "rotation + 180" in api
    skill = Path("skills/placemat/SKILL.md").read_text()
    assert "vertical axis" in skill
    assert "Occupancy\\._transform" in skill or "_transform" in skill    # the detection grep
    mig = Path("skills/placemat/references/migration.md").read_text()
    assert "0.8" in mig and "flip" in mig.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_faces.py -q -k "docs_say"`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `api.md`, under Placement, after the degrees-of-freedom paragraph:

> **A flip to the back** mirrors the item about the VERTICAL axis and then
> turns it by `rotation=`. That is KiCad's own F key
> (`editing.flip_left_right`, its default), and a part and a cell flip the same
> way. KiCad's orientation field will read `rotation + 180` for a back-face
> part, which is exactly what you get by drawing that part upright on the front
> and pressing F.

and the same sentence in the Layers and faces section.

In `SKILL.md`, in Placement tactics:

> A flip to the back mirrors about the vertical axis - KiCad's F key - and
> `rotation=` is applied after it. A part and a cell flip the same way. KiCad's
> own orientation field will read `rotation + 180`.

and extend the legacy-detection line near the top:

```sh
grep -nE "Priority\.(FIXED|EDGE)|priority=Priority\.(HIGH|LOW)|Occupancy\._transform" <script>
```

with the surrounding sentence gaining: "a monkeypatch of
`Occupancy._transform` is a 0.7-or-earlier workaround for the back-face flip
and must come out."

In `references/migration.md`, a new section above `## To 0.7`:

````markdown
## To 0.8

**Back-face parts move. Cells do not.**

A flip to the back now mirrors about the vertical axis - KiCad's F key - for a
part and a cell alike, and `rotation=` is applied after it. Before, a lone part
mirrored top-to-bottom and the planner and the writer disagreed about where its
pads landed by `180 + 2r`, where `r` is the rotation the generator left the part
at.

**Drop any monkeypatch of `Occupancy._transform`.** It was masking the bug for
parts at generated rotation 0 and 180 and creating it for those at 90 and 270.
`grep -n "Occupancy._transform" <script>` finds it.

**A script that compensated by hand cannot be grepped for.** If a back-face part
carries `rotation=180` where the board wanted it upright, it will now be upside
down. Look for back-face parts whose rotation was chosen by trial rather than
from the mechanics, and read the render.

**KiCad's orientation field now reads `rotation + 180`** for a back-face part.
Nothing is wrong: that is what its own flip produces.

A board with no back-face parts is unaffected.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Bump the version and commit**

```bash
sed -i 's/__version__ = "0.7.0"/__version__ = "0.8.0"/' src/placemat/__init__.py
sed -i 's/"version": "0.7.0"/"version": "0.8.0"/' .claude-plugin/plugin.json .claude-plugin/marketplace.json
uv pip install -q -e .
.venv/bin/python -m pytest -q
git add -A
git commit -m "Plugin 0.8.0: one flip, and it is KiCad's"
```

---

## Acceptance criteria

1. `.venv/bin/python -m pytest -q` passes in full.
2. `tests/test_flip_parity.py` passes all 36 parametrised cases with no skips
   against the committed Breakout: 16 back-face, 16 front-face, 4 cell.
3. The occupancy model's answer for a flipped part does not depend on the
   rotation the generator left it at.
4. A flip mirrors about the vertical axis for a lone part and for a cell, and
   `test_a_part_and_a_cell_holding_it_flip_the_same_way` proves it.
5. `_move_cell` is unmodified.
6. `test_write_roundtrip`'s identical-plan-twice byte test still passes.
7. `api.md`, `SKILL.md` and `references/migration.md` are updated, the detection
   grep catches `Occupancy._transform`, and `migration.md` has a `## To 0.8`
   section.
8. `git log --format=%B <base>..HEAD | grep -iE "claude|anthropic|session|co-authored"`
   returns nothing.
