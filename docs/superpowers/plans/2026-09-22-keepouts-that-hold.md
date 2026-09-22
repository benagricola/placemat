# Keepouts That Hold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a declared region actually forbid: honour its `layers=`, keep it when it hangs off the board edge, and stop destroying the ones a stamped cell brings with it.

**Architecture:** Three independent fixes in `layout.py`, `read.py` and `write.py` plus one new `BoardGeometry.rule_areas` field. A rule area placemat did not write is identified by group membership, read into the geometry, and turned into an occupancy reservation - immediately for a board-level one, and at commit time for one owned by a cell, because its position is not known until the cell lands. Two reporting additions spend numbers that are already computed and thrown away.

**Tech Stack:** Python 3.12, pytest, pcbnew (only under `src/placemat/kicad/`).

**Spec:** `docs/superpowers/specs/2026-09-22-keepouts-that-hold-design.md`

## Global Constraints

- `pcbnew` may be imported only under `src/placemat/kicad/`. Everything else is pure Python and unit-testable without KiCad.
- No polygon clipping is performed anywhere in this plan. A region is used exactly as declared.
- A region **wholly** off the board raises `ValueError` from `settle_keepout`, and `--keep-going` does NOT suppress it.
- `k.layers is None` keeps meaning "every copper layer the board has".
- `_draw_keepouts` deletes a rule area if and only if it belongs to no group.
- ASCII only in prose, comments and commit messages: no em dashes, no en dashes, no unicode arrows, straight quotes.
- Commit messages must contain no reference to Claude, Anthropic, or a session URL.
- Run the suite with `.venv/bin/python -m pytest -q`. It is 481 tests and green before this plan starts.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/placemat/layout.py` (modify) | layer-aware copper check; region kept when partly off the board; name-collision refusal; blocking-owner finding; seeded-net tally |
| `src/placemat/occupancy.py` (modify) | `Blocker`, `legal(..., blame=)`, reservations from `BoardGeometry.rule_areas` |
| `src/placemat/placer.py` (modify) | `scan` tallies blockers by owner |
| `src/placemat/board_geometry.py` (modify) | `RuleArea` dataclass, `BoardGeometry.rule_areas` |
| `src/placemat/kicad/read.py` (modify) | read rule areas off the board |
| `src/placemat/kicad/write.py` (modify) | keep rule areas placemat did not write |
| `src/placemat/runner.py` (modify) | the `seeded` summary line and `metrics.seeded_by_net` |
| `tests/test_keepouts.py` (modify) | layers, off-board, collisions, cell rule areas |
| `tests/test_occupancy.py` (modify) | `blame` |
| `tests/test_order.py` (modify) | seeded tally |
| `skills/placemat/references/api.md`, `SKILL.md`, `references/migration.md` (modify) | documentation |

---

## Task 1: A keepout's layers narrow the copper check

**Files:**
- Modify: `src/placemat/layout.py:827-849`
- Test: `tests/test_keepouts.py`

**Interfaces:**
- Consumes: `PlacedKeepout.layers` (already exists: `tuple | None`).
- Produces: module function `layout._op_layers(op) -> frozenset[CopperLayer]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_keepouts.py

def test_a_track_on_another_layer_than_the_region_is_quiet():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), layers=(CopperLayer.F,),
              why="the clearance on F")
    b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=CopperLayer.B)
    assert not b.resolve().findings


def test_a_track_on_the_region_s_own_layer_is_still_a_finding():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), layers=(CopperLayer.F,),
              why="the clearance on F")
    b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=CopperLayer.F)
    assert any("antenna" in f for f in b.resolve().findings)


def test_a_region_with_no_layers_still_catches_every_layer():
    for layer in (CopperLayer.F, CopperLayer.B):
        b = make_board("u1", keep_going=True)
        b.size(width=40.0, height=40.0)
        b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), why="every layer")
        b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=layer)
        assert any("antenna" in f for f in b.resolve().findings), layer


def test_a_via_is_caught_by_a_region_on_any_single_layer():
    """A via joins every copper layer, so a region on one of them contains it."""
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), layers=(CopperLayer.B,),
              why="the clearance on B")
    b.via(Net("GND"), Location(20.0, 20.0))
    assert any("antenna" in f and "via" in f for f in b.resolve().findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py -q -k "another_layer or own_layer or no_layers or via_is_caught"`
Expected: `test_a_track_on_another_layer_than_the_region_is_quiet` FAILS (a finding is produced); the other three pass already.

- [ ] **Step 3: Write minimal implementation**

Add beside `_shape_of` at the bottom of `src/placemat/layout.py`:

```python
def _op_layers(op) -> frozenset:
    """The copper layers a drawn op occupies. A via joins the whole stack, so
    a region covering any one layer contains it."""
    if isinstance(op, Via):
        return frozenset(CopperLayer)
    return frozenset([op.layer])
```

and in `_check_keepouts`, after the `excluded not in k.excludes` guard:

```python
            for k in plan.keepouts.values():
                if excluded not in k.excludes or op.net in k.allow:
                    continue
                if k.layers is not None and not (_op_layers(op) & frozenset(k.layers)):
                    continue                        # the region does not cover this op's layer
                if not Box.of_points(k.poly).overlaps(op.box):
                    continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_keepouts.py
git commit -m "A keepout's layers= narrows what is checked, not just what is written"
```

---

## Task 2: A region that hangs off the board is used, not discarded

**Files:**
- Modify: `src/placemat/layout.py:772-779` (`_keepout_illegal`), `:1830-1858` (`settle_keepout`)
- Test: `tests/test_keepouts.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `Board._points_off_board(path) -> tuple[int, int]` returning `(outside, total)`; `settle_keepout` raises `ValueError` when `outside == total`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_keepouts.py
import pytest


def test_a_region_partly_off_the_board_is_still_enforced():
    """The fairing case: a fence whose outer boundary IS the board outline,
    sampled into chords, and a chord across an arc bulges past the true curve.
    The region must still fence the parts it was written to fence."""
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "seal", at=Location(38.0, 20.0), why="the gland")
    plan = b.resolve()
    assert "seal" in plan.keepouts
    assert any("seal" in r.why for r in plan.occupancy.reservations)


def test_that_region_s_step_counts_the_points_that_fell_outside():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "seal", at=Location(38.0, 20.0), why="the gland")
    note = b.resolve().step("keepout seal").note
    assert "off the board" in note and "of its" in note


def test_a_region_wholly_inside_says_nothing_about_the_board_edge():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "mid", at=Location(20.0, 20.0), why="the middle")
    assert "off the board" not in b.resolve().step("keepout mid").note


def test_a_region_wholly_off_the_board_raises():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "nowhere", at=Location(200.0, 200.0), why="forbids nothing")
    with pytest.raises(ValueError) as e:
        b.resolve()
    assert "nowhere" in str(e.value) and "off the board" in str(e.value)


def test_a_wholly_off_board_region_raises_even_with_keep_going():
    """A script error, of the same class as two keepouts sharing one name.
    --keep-going carries on past board conditions, not past those."""
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "nowhere", at=Location(200.0, 200.0), why="forbids nothing")
    with pytest.raises(ValueError):
        b.resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py -q -k "partly_off or points_that_fell or wholly"`
Expected: FAIL - the region is discarded, so `plan.keepouts` is empty and nothing raises.

- [ ] **Step 3: Write minimal implementation**

Replace `_keepout_illegal` (`layout.py:772-779`) with a counter:

```python
    def _points_off_board(self, path) -> tuple:
        """(points outside the board, points in all) for a region's boundary.

        A region is used exactly as declared: the part hanging off the board
        can refuse nothing, because `Occupancy.legal` rejects a part for
        crossing the keep-in before it ever tests a reservation, and KiCad
        clips a zone to Edge.Cuts itself. The count is reported so a region
        that is mostly off the board is visible; a point count, not an area,
        because a region whose boundary IS the outline has the board's own
        area and any area measure reads zero."""
        shape = self._shaped()
        loop = Cutouts([path]).loops[0]
        outside = sum(1 for x, y in loop
                      if shape.why_not(Box(x, y, x, y), 0.0) == "outside the board")
        return outside, len(loop)
```

and rewrite the tail of `settle_keepout`:

```python
        def settle_keepout(intent):
            """A region takes its place like a hole does, then forbids."""
            k = intent.keepout
            if self._cutout_free(k):
                try:
                    centre, turn = self._slide_cutout(occ, k)
                    why = None
                except ValueError as e:
                    centre, turn, why = self.centre, 0.0, str(e)
            else:
                centre = self._cutout_centre(occ, k)
                turn = float(k.rotation) if k.rotation is not None else self._implied_rotation(k, centre)
                why = None
            step = Step(intent.key, "keepout", None, why=intent.why)
            if why:
                plan.findings.append("%s (keepout): %s" % (k.name, why))
                step.note = why
            else:
                path = k.shape.path_at(centre, turn)
                outside, total = self._points_off_board(path)
                if outside == total:
                    raise ValueError(
                        "keepout %r is wholly off the board, so it forbids nothing: all %d of its "
                        "points are outside the outline. Move it, or remove the declaration."
                        % (k.name, total))
                poly = Cutouts([path]).loops[0]
                nets = frozenset(self.geometry.require_net(a) for a in k.allow if isinstance(a, Net))
                owners = frozenset(self._pad_ref(a)[0] for a in k.allow if isinstance(a, (Part, Cell)))
                if "parts" in k.excludes:
                    occ.reserve(poly, "keepout %r (%s)" % (k.name, k.why), allow=nets, owners=owners)
                plan.keepouts[k.name] = PlacedKeepout(k.name, poly, centre, turn, k.excludes,
                                                      k.layers, nets, owners, k.why)
                step.note = "kept clear at %.2f, %.2f" % (centre.x, centre.y)
                if outside:
                    step.note += "; %d of its %d points are off the board" % (outside, total)
            plan.steps.append(step)
            placed.add(cutout_token(k.name))
```

Note the `illegal=` argument is dropped from the `_slide_cutout` call: a free
region no longer has to find a spot that is wholly on the board.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_keepouts.py
git commit -m "A keepout that hangs off the board edge still forbids"
```

---

## Task 3: A keepout may not shadow a rule area already on the board

**Files:**
- Modify: `src/placemat/board_geometry.py`, `src/placemat/layout.py` (`keepout`)
- Test: `tests/test_keepouts.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `board_geometry.RuleArea` dataclass and `BoardGeometry.rule_areas: tuple[RuleArea, ...]` (default `()`), plus `BoardGeometry.rule_area_names() -> frozenset[str]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_keepouts.py

def test_a_keepout_may_not_take_a_name_a_rule_area_on_the_board_already_has():
    """A stamped cell brings its module's regions with it. A script that
    reuses one of their names would leave two regions and no way to say
    which won."""
    from placemat.board_geometry import RuleArea
    from placemat.values import CopperLayer as CL
    g = board_geometry([footprint("U1", 10, 10, inst="u1", nets=("A", "B"))], width=40, height=40)
    g = dataclasses.replace(g, rule_areas=(
        RuleArea("keepout antenna_1", "ant_rf", ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
                 frozenset([CL.F]), frozenset(["parts"])),))
    b = Board(g, edge_margin=1.0)
    b.size(width=40.0, height=40.0)
    with pytest.raises(ValueError) as e:
        b.keepout(Circle(4.0), "antenna_1", at=Location(20, 20), why="clashes")
    assert "antenna_1" in str(e.value) and "ant_rf" in str(e.value)


def test_an_unrelated_name_is_fine():
    from placemat.board_geometry import RuleArea
    from placemat.values import CopperLayer as CL
    g = board_geometry([footprint("U1", 10, 10, inst="u1", nets=("A", "B"))], width=40, height=40)
    g = dataclasses.replace(g, rule_areas=(
        RuleArea("keepout antenna_1", "ant_rf", ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
                 frozenset([CL.F]), frozenset(["parts"])),))
    b = Board(g, edge_margin=1.0)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "my_own", at=Location(20, 20), why="fine")     # no raise
```

Add `import dataclasses` to the test file's imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py -q -k "already_has or unrelated_name"`
Expected: FAIL with `ImportError: cannot import name 'RuleArea'`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/board_geometry.py`, beside `CopperItem`:

```python
@dataclass(frozen=True)
class RuleArea:
    """A KiCad rule area already on the generated board: the module fragments
    that were stamped bring theirs with them, inside the cell's group.

    placemat did not write these and must not destroy them. `cell` is the
    group that owns it, or None for one that belongs to the board itself."""
    name: str                            # the zone name, e.g. "keepout antenna_1"
    cell: str | None
    polygon: Polygon                     # in the generated board's coordinates
    layers: frozenset[CopperLayer]
    excludes: frozenset[str]             # parts | fill | tracks | vias | pads
```

and on `BoardGeometry`, after `edge_clearance`:

```python
    rule_areas: tuple[RuleArea, ...] = ()
```

plus a method:

```python
    def rule_area_names(self) -> frozenset[str]:
        return frozenset(r.name for r in self.rule_areas)
```

In `layout.py`'s `keepout`, after the existing duplicate-name check:

```python
        if name in self._keepouts:
            raise ValueError("there is already a keepout named %r on this board" % name)
        clash = [r for r in self.geometry.rule_areas if r.name == "keepout %s" % name]
        if clash:
            raise ValueError(
                "the generated board already carries a rule area called %r%s, so a keepout named "
                "%r would leave two regions and no way to say which one won; pick another name"
                % (clash[0].name, (" from the %s cell" % clash[0].cell) if clash[0].cell else "",
                   name))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/board_geometry.py src/placemat/layout.py tests/test_keepouts.py
git commit -m "RuleArea: what the generated board already forbids, and a name that may not clash"
```

---

## Task 4: A rule area on the board becomes a reservation

**Files:**
- Modify: `src/placemat/occupancy.py`
- Test: `tests/test_keepouts.py`

**Interfaces:**
- Consumes: `RuleArea` from Task 3.
- Produces: `Occupancy` reserves board-level rule areas in `__init__` and cell-owned ones in `commit`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_keepouts.py

def _with_rule_area(cell, poly):
    from placemat.board_geometry import RuleArea
    from placemat.values import CopperLayer as CL
    fps = [footprint("U1", 10, 10, w=4, h=2, cell="ant_rf", inst="ant_rf.u", nets=("A", "B")),
           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("B", "C"))]
    g = board_geometry(fps, cells=["ant_rf"], width=60, height=60)
    return dataclasses.replace(g, rule_areas=(
        RuleArea("keepout antenna_1", cell, poly, frozenset([CL.F]), frozenset(["parts"])),))


def test_a_board_level_rule_area_is_reserved_from_the_start():
    from placemat.occupancy import Occupancy
    poly = ((25.0, 25.0), (35.0, 25.0), (35.0, 35.0), (25.0, 35.0))
    occ = Occupancy(_with_rule_area(None, poly), edge_margin=0.0)
    assert any("antenna_1" in r.why for r in occ.reservations)


def test_a_cell_owned_rule_area_waits_for_its_cell():
    """Its position is not known until the cell lands, exactly as the cell's
    own courtyard is not."""
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    poly = ((8.0, 8.0), (14.0, 8.0), (14.0, 14.0), (8.0, 14.0))
    g = _with_rule_area("ant_rf", poly)
    occ = Occupancy(g, edge_margin=0.0)
    assert not occ.reservations
    occ.commit(g.cell("ant_rf"), Placement(Location(40.0, 40.0), 0.0, Face.FRONT))
    (r,) = occ.reservations
    assert "antenna_1" in r.why
    # the region travelled with the cell: its box centre moved with the cell's
    assert r.box.center.x > 20.0 and r.box.center.y > 20.0


def test_a_part_is_refused_for_sitting_in_a_cell_s_stamped_region():
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    poly = ((8.0, 8.0), (14.0, 8.0), (14.0, 14.0), (8.0, 14.0))
    g = _with_rule_area("ant_rf", poly)
    occ = Occupancy(g, edge_margin=0.0)
    occ.commit(g.cell("ant_rf"), Placement(g.cell("ant_rf").box.center, 0.0, Face.FRONT))
    why = occ.legal(g.footprint("R1"), Placement(Location(11.0, 11.0), 0.0, Face.FRONT))
    assert why is not None and "antenna_1" in why


def test_a_rule_area_that_does_not_forbid_parts_reserves_nothing():
    from placemat.board_geometry import RuleArea
    from placemat.occupancy import Occupancy
    from placemat.values import CopperLayer as CL
    g = board_geometry([footprint("U1", 10, 10, inst="u1", nets=("A", "B"))], width=40, height=40)
    g = dataclasses.replace(g, rule_areas=(
        RuleArea("keepout fill_only", None, ((5.0, 5.0), (9.0, 5.0), (9.0, 9.0)),
                 frozenset([CL.F]), frozenset(["fill"])),))
    assert not Occupancy(g, edge_margin=0.0).reservations
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py -q -k "rule_area_is_reserved or waits_for_its_cell or stamped_region or does_not_forbid"`
Expected: FAIL - `occ.reservations` is empty in every case.

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/occupancy.py`, at the end of `Occupancy.__init__`:

```python
        # Rule areas the generated board already carries: a stamped cell brings
        # its module's with it. One that belongs to the board is reserved now;
        # one a cell owns has no position until that cell lands, so it waits
        # for commit(), exactly as the cell's own courtyard does.
        self._cell_rule_areas: dict = {}
        for ra in geometry.rule_areas:
            if "parts" not in ra.excludes:
                continue
            if ra.cell is None:
                self.reserve(ra.polygon, "rule area %r on the generated board" % ra.name)
            else:
                self._cell_rule_areas.setdefault(ra.cell, []).append(ra)
```

and in `commit`, in the cell branch, after the member loop and before the
`own = by_owner.get(...)` line:

```python
        for ra in self._cell_rule_areas.get(item.name, ()):
            self.reserve(tuple(t.apply((x, y)) for x, y in ra.polygon),
                         "rule area %r from the %s cell" % (ra.name, ra.cell))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py tests/test_occupancy.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/occupancy.py tests/test_keepouts.py
git commit -m "A rule area the board already carries fences the placer too"
```

---

## Task 5: read.py reads rule areas, write.py keeps the ones it did not write

**Files:**
- Modify: `src/placemat/kicad/read.py`, `src/placemat/kicad/write.py:106-127`
- Test: `tests/test_write_roundtrip.py`

**Interfaces:**
- Consumes: `RuleArea` from Task 3.
- Produces: `read._rule_areas(board, groups_of) -> tuple[RuleArea, ...]`; `_draw_keepouts` deletes only group-less rule areas.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_write_roundtrip.py

def _add_rule_area(pcb, name, group_name=None):
    """Put a rule area on a board file, optionally inside a group, the way
    `pcb layout` stamps a module fragment's own."""
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetLayerSet(pcbnew.LSET.AllCuMask(board.GetCopperLayerCount()))
    z.SetDoNotAllowFootprints(True)
    o = z.Outline(); o.NewOutline()
    for x, y in ((10.0, 10.0), (14.0, 10.0), (14.0, 14.0), (10.0, 14.0)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    z.SetZoneName(name)
    board.Add(z)
    if group_name:
        g = pcbnew.PCB_GROUP(board)
        g.SetName(group_name)
        g.AddItem(z)
        board.Add(g)
    board.Save(str(pcb))


def test_a_rule_area_in_a_group_survives_a_write(breakout_pcb, tmp_path):
    """A stamped cell's regions are group members. placemat did not write them
    and must not destroy them."""
    pcb = _copy(breakout_pcb, tmp_path)
    _add_rule_area(pcb, "keepout antenna_1", group_name="ant_rf")
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    apply_plan(pcb, b.resolve())
    assert "keepout antenna_1" in [r.name for r in read_board(pcb).rule_areas]


def test_a_group_less_rule_area_is_replaced_on_a_write(breakout_pcb, tmp_path):
    """placemat's own, from a previous run: deleted and rewritten, so a
    declaration removed from the script does not leak."""
    pcb = _copy(breakout_pcb, tmp_path)
    _add_rule_area(pcb, "keepout stale")
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    apply_plan(pcb, b.resolve())
    assert "keepout stale" not in [r.name for r in read_board(pcb).rule_areas]


def test_reading_a_rule_area_gives_its_name_cell_layers_and_excludes(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    _add_rule_area(pcb, "keepout antenna_1", group_name="ant_rf")
    (ra,) = [r for r in read_board(pcb).rule_areas if r.name == "keepout antenna_1"]
    assert ra.cell == "ant_rf"
    assert ra.excludes == frozenset(["parts"])
    assert len(ra.layers) >= 2 and len(ra.polygon) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_write_roundtrip.py -q -k "rule_area"`
Expected: FAIL with `AttributeError: 'BoardGeometry' object has no attribute 'rule_areas'` or the group-owned area being deleted.

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/kicad/read.py`, add:

```python
_KEEPOUT_GETTERS = (("parts", "GetDoNotAllowFootprints"), ("fill", "GetDoNotAllowZoneFills"),
                    ("tracks", "GetDoNotAllowTracks"), ("vias", "GetDoNotAllowVias"),
                    ("pads", "GetDoNotAllowPads"))


def _rule_areas(board, groups_of) -> tuple:
    """Every rule area on the board. A stamped module fragment's are members
    of the cell's group, which is how placemat tells them from its own."""
    out = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if not z.GetIsRuleArea():
            continue
        o = z.Outline().Outline(0) if z.Outline().OutlineCount() else None
        if o is None:
            continue
        poly = tuple((mm(o.CPoint(j).x), mm(o.CPoint(j).y)) for j in range(o.PointCount()))
        excludes = frozenset(name for name, getter in _KEEPOUT_GETTERS if getattr(z, getter)())
        out.append(RuleArea(z.GetZoneName(), groups_of.get(_kiid(z)), poly,
                            _copper_layers(board, z.GetLayerSet()), excludes))
    return tuple(out)
```

import `RuleArea` alongside the other `board_geometry` names, and pass it in
`board_geometry_of`'s final construction:

```python
    return BoardGeometry(path=path, footprints=fps, cells=cells, copper=copper, outline=_outline(board),
                    nets=frozenset(classes), netclasses=classes, default_clearance=default_clr,
                    layers=layers, edge_clearance=mm(board.GetDesignSettings().m_CopperEdgeClearance),
                    rule_areas=_rule_areas(board, groups_of))
```

In `src/placemat/kicad/write.py`, `_draw_keepouts`:

```python
def _draw_keepouts(board, plan):
    """A KiCad rule area per keepout. KiCad's own filler keeps a zone out of
    one, and DRC and the router judge by it, so a region declared once is
    honoured by everything downstream without placemat clipping anything.

    Only rule areas placemat itself wrote are replaced, and those belong to no
    group. A stamped module fragment's are members of the cell's group and are
    left alone: `_move_cell` carries them with the cell, and deleting them
    would silently drop a clearance the module declared."""
    grouped = {_kiid(it) for g in board.Groups() for it in g.GetItems()}
    for z in list(board.Zones()):
        if z.GetIsRuleArea() and _kiid(z) not in grouped:
            board.Delete(z)                 # placemat's own: a rerun replaces them, never doubles them
    for k in plan.keepouts.values():
        ...                                 # the rest of the function is unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_write_roundtrip.py tests/test_keepouts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/kicad tests/test_write_roundtrip.py
git commit -m "A stamped cell's rule areas are read, and are no longer deleted"
```

---

## Task 6: legal() can say who blocked, and the finding names them

**Files:**
- Modify: `src/placemat/occupancy.py` (`legal`), `src/placemat/placer.py` (`scan`, `ScanResult`), `src/placemat/layout.py` (`_settle`'s no-legal-location finding)
- Test: `tests/test_occupancy.py`, `tests/test_placer.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `occupancy.Blocker(kind: str, owner: str, faces: frozenset[Face])`; `Occupancy.legal(item, placement, clearance=None, others=None, past_edge=False, blame=None)`; `ScanResult.blockers: Counter` keyed by `(kind, owner, face_label)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_occupancy.py

def test_legal_can_name_who_blocked_and_on_which_face():
    from placemat.occupancy import Blocker, Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    g = board_geometry([footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("A", "B")),
                        footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("B", "C"))],
                       width=60, height=60)
    occ = Occupancy(g, edge_margin=0.0)
    blame = []
    why = occ.legal(g.footprint("U1"), Placement(Location(30.0, 30.0), 0.0, Face.FRONT), blame=blame)
    assert why is not None                                   # the return value is unchanged
    assert blame and isinstance(blame[0], Blocker)
    assert blame[0].owner == "R1" and Face.FRONT in blame[0].faces


def test_legal_without_blame_behaves_exactly_as_before():
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    g = board_geometry([footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("A", "B"))],
                       width=60, height=60)
    occ = Occupancy(g, edge_margin=0.0)
    assert occ.legal(g.footprint("U1"),
                     Placement(Location(10.0, 10.0), 0.0, Face.FRONT)) is None
```

```python
# append to tests/test_placer.py

def test_a_failed_scan_tallies_who_blocked_it():
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.placer import scan
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("BIG", 20, 20, w=18, h=18, inst="big", nets=("A", "B")),
           footprint("SMALL", 50, 50, w=4, h=4, inst="small", nets=("B", "C"))]
    g = board_geometry(fps, width=60, height=60)
    occ = Occupancy(g, edge_margin=0.0)
    result = scan(occ, g.footprint("SMALL"),
                  Placement(Location(20.0, 20.0), 0.0, Face.FRONT), radius=1.0, step=0.5)
    assert result.chosen is None
    assert any(owner == "BIG" for (_, owner, _) in result.blockers)
```

```python
# append to tests/test_order.py

def test_a_no_legal_location_finding_names_the_top_blocking_owners():
    fps = [footprint("BIG", 25, 25, w=22, h=22, inst="big", nets=("A", "B")),
           footprint("SMALL", 50, 50, w=6, h=6, inst="small", nets=("B", "C"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0, keep_going=True)
    b.place(Part("big"), at=Location(25, 25))
    b.place(Part("small"), at=Near(Location(25, 25), radius=1.0, step=0.5))
    (finding,) = [f for f in b.resolve().findings if f.startswith("small")]
    assert "BIG" in finding and "front" in finding
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_occupancy.py tests/test_placer.py tests/test_order.py -q -k "blame or blocked or blocking"`
Expected: FAIL with `ImportError: cannot import name 'Blocker'`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/occupancy.py`, beside `Shape`:

```python
@dataclass(frozen=True)
class Blocker:
    """Why one candidate placement was refused, in parts rather than prose:
    what kind of conflict, whose shape it was, and which faces it holds. The
    sentence `legal` returns is for a human; this is for counting."""
    kind: str                       # courtyard | pad | through | copper | npth | edge | reservation
    owner: str                      # as `who()` formats it: a cell member carries its cell
    faces: frozenset
```

and give `legal` the parameter, recording at each of its three exits:

```python
    def legal(self, item, placement: Placement, clearance: float | None = None, others=None,
              past_edge: bool = False, blame: list | None = None) -> str | None:
```

- at the edge-margin rejections: `if blame is not None: blame.append(Blocker("edge", "", frozenset()))`
  before each `return`.
- at the reservation rejection:
  `if blame is not None: blame.append(Blocker("reservation", r.why, frozenset()))`.
- at the shape conflict: replace `return why` with

```python
                if why:
                    if blame is not None:
                        blame.append(Blocker(o.kind, self.who(o.owner), frozenset(o.faces)))
                    return why
```

In `src/placemat/placer.py`, add `blockers: Counter = field(default_factory=Counter)`
to `ScanResult`, and in `scan`'s `sweep`:

```python
                blame = []
                why = occ.legal(item, cand, clearance, others=others, blame=blame)
                ...
                key = _reason_key(why)
                rejected[key] += 1
                reasons.setdefault(key, why)
                for b in blame:
                    blockers[(b.kind, b.owner, "/".join(sorted(f.value for f in b.faces)))] += 1
```

declaring `blockers: Counter = Counter()` beside `rejected`, and passing it into
both `ScanResult(...)` constructions.

In `src/placemat/layout.py`'s `_settle`, replace the no-legal-location finding:

```python
        if result.chosen is None:
            plan.findings.append("%s: no legal location within %.1f mm of %s (%s)" % (
                i.key, radius, _loc(hint.location), _blame_text(result)))
```

with a module helper beside `_ordinal`:

```python
def _blame_text(result) -> str:
    """The rejection counts, and for each kind the owners that caused most of
    them. The owner and the faces are computed for every candidate the scan
    refuses and were being thrown away; three owners, because a crowded board
    has forty and a reader needs one."""
    parts = []
    for kind, n in result.rejected.most_common(3):
        owners = sorted(((owner, faces, count)
                         for (k, owner, faces), count in result.blockers.items()
                         if k == kind and owner),
                        key=lambda t: -t[2])[:3]
        detail = "" if not owners else ": " + ", ".join(
            "%s%s x%d" % (owner, (" %s face" % faces) if faces else "", count)
            for owner, faces, count in owners)
        parts.append("%s x%d%s" % (kind, n, detail))
    return "; ".join(parts)
```

The blocker key keeps the face label, so an owner that holds both faces (a
through-hole part) is counted separately from one that holds a single face,
and reads as `cell logic's U18 back/front face x1204`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat tests
git commit -m "A finding names who blocked a placement, and on which face"
```

---

## Task 7: The run says which nets seeded what

**Files:**
- Modify: `src/placemat/layout.py` (`_settle`, `Board.__init__`, `Plan`), `src/placemat/runner.py`
- Test: `tests/test_order.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Plan.seeded_by_net: Counter`; `runner` prints a `seeded` line and records `metrics.seeded_by_net`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_order.py

def test_the_plan_counts_which_nets_seeded_which_items():
    """A board with no plane declared pulls every part sharing a net to one
    centroid. The counts say so without placemat deciding a threshold."""
    fps = [footprint("J1", 5, 5, w=6, h=3, inst="j1", nets=("BUS", "GND"))]
    fps += [footprint("C%d" % i, 20 + i * 3, 20, w=1, h=0.5, inst="c%d" % i, nets=("BUS", "GND"))
            for i in range(4)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("j1"), at=Location(10, 10))
    for i in range(4):
        b.place(Part("c%d" % i))
    plan = b.resolve()
    assert plan.seeded_by_net["BUS"] == 4


def test_a_declared_plane_net_never_seeds_anything():
    from placemat.values import CopperLayer, Net
    fps = [footprint("J1", 5, 5, w=6, h=3, inst="j1", nets=("BUS", "GND"))]
    fps += [footprint("C%d" % i, 20 + i * 3, 20, w=1, h=0.5, inst="c%d" % i, nets=("BUS", "GND"))
            for i in range(4)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.size(width=60, height=60)
    b.plane(Net("GND"), layers=(CopperLayer.B,))
    b.place(Part("j1"), at=Location(10, 10))
    for i in range(4):
        b.place(Part("c%d" % i))
    plan = b.resolve()
    assert "GND" not in plan.seeded_by_net and plan.seeded_by_net["BUS"] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_order.py -q -k "seeded"`
Expected: FAIL with `AttributeError: 'Plan' object has no attribute 'seeded_by_net'`

- [ ] **Step 3: Write minimal implementation**

Add to `Plan` (`layout.py`, beside `findings`):

```python
    seeded_by_net: Counter = field(default_factory=Counter)
```

`Counter` is already imported at the top of `layout.py`.

In `_settle`, where `seeded` is built, tally into the plan:

```python
            seeded = "seeded on %s" % ", ".join(nets)
            for n in nets:
                plan.seeded_by_net[n] += 1
```

In `src/placemat/runner.py`, after the `say("script", ...)` extent line:

```python
        if plan.seeded_by_net:
            top = plan.seeded_by_net.most_common(4)
            more = len(plan.seeded_by_net) - len(top)
            say("seeded", ", ".join("%s %d" % kv for kv in top) + (", +%d more" % more if more else ""))
            metrics_seeded = dict(plan.seeded_by_net)
        else:
            metrics_seeded = {}
```

and include it in the metrics dict:

```python
        metrics = {"board": ..., "findings": len(plan.findings), "placed": n_place,
                   "copper_ops": n_copper, "seeded_by_net": metrics_seeded, **extent_metrics}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat tests
git commit -m "The run says which nets seeded what, so a missing plane is visible"
```

---

## Task 8: Documentation

**Files:**
- Modify: `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, `skills/placemat/references/migration.md`
- Test: `tests/test_keepouts.py`

**Interfaces:** no new code interface.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_keepouts.py

def test_the_docs_say_what_a_keepout_now_holds():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "layers=` narrows what is CHECKED" in api or "narrows what is checked" in api
    assert "seeded_by_net" in api
    skill = Path("skills/placemat/SKILL.md").read_text()
    assert "seeded" in skill
    assert "allow=" in skill                      # the do-not-widen instruction
    mig = Path("skills/placemat/references/migration.md").read_text()
    assert "0.7" in mig and "0.6" in mig          # a section per release, both present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_keepouts.py -q -k "docs_say"`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `api.md`, Keepouts section, replace the `layers=` and "What it costs"
paragraphs with:

````markdown
**Where.** `layers=` defaults to every copper layer the board has, whatever the
count. Narrow it with a list of `CopperLayer`. It narrows what is CHECKED as
well as what is written: a track on a layer the region does not cover is not a
finding. A via joins the whole stack, so a region on any one layer contains it.

**The board edge.** A region may hang off it. Only the on-board part does
anything - a part is refused for crossing the keep-in before any reservation is
tested, and KiCad clips a zone to Edge.Cuts itself - and the step counts the
points that fell outside. A region WHOLLY off the board is an error: it forbids
nothing, and the script says otherwise.

**A stamped cell brings its own.** A module fragment's regions arrive with the
cell, inside its group, and are honoured: they move with the cell and fence the
placer. They are read from the generated board, so a keepout whose name would
collide with one is refused.

**What it costs.** `board.plane()` is untouched: the rule area keeps the fill
out, and DRC and the router judge by it. A `pour`, `track` or `via` crossing a
keepout ON A LAYER IT COVERS is a finding, because each keeps exactly the shape
or the position it was given.
````

Add to the run-record list in `api.md`: `metrics.seeded_by_net` - how many
searched items each net seeded.

In `SKILL.md`, in the loop after the DRC bullet:

> Read the `seeded` line. It says which nets pulled how many items into place.
> One net seeding most of the board is a missing `board.plane()`, not a
> placement problem: an undeclared plane net pulls every part that shares it to
> one centroid.

and in Placement tactics:

> A keepout's `layers=` narrows what is checked as well as what is written, so
> **do not widen `allow=` to silence a complaint about copper on another
> layer** - that admits the net on the layers that do matter. A stamped cell
> brings its module's regions with it, so a parent may report parts or copper
> inside a clearance it never declared; those findings are real.

Restructure `references/migration.md` into sections per release, newest first.
Retitle it `# Migrating a layout script`, keep the existing body under
`## To 0.6`, and add above it:

````markdown
## To 0.7

Nothing to change in a script. Three things get stricter, and one report is new.

**A keepout's `layers=` is now honoured when copper is checked.** A board that
widened `allow=` to silence a complaint about copper on a layer the region does
not cover should take those nets back out: the `allow=` admits them on the
layers that DO matter. `boards/main/Main_layout.py` is the known case.

**A region that hangs off the board edge now forbids.** It used to be discarded
whole, silently. Expect new findings from a region that was never in force -
they are the point. A region wholly off the board is now an error.

**A stamped cell's rule areas are no longer deleted.** A parent board that
stamps a module declaring a clearance will newly report parts and copper inside
it. On a board that filled a ground pour under an antenna, that is the finding
that was missing.

**New: the `seeded` line.** It says which nets pulled how many items into
place. One net seeding most of the board means a missing `board.plane()`.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Bump the version and commit**

```bash
# __init__.py and both .claude-plugin manifests move together; test_version.py enforces it
sed -i 's/__version__ = "0.6.0"/__version__ = "0.7.0"/' src/placemat/__init__.py
sed -i 's/"version": "0.6.0"/"version": "0.7.0"/' .claude-plugin/plugin.json .claude-plugin/marketplace.json
uv pip install -q -e .
.venv/bin/python -m pytest -q
git add -A
git commit -m "Plugin 0.7.0: keepouts that hold"
```

---

## Acceptance criteria

1. `.venv/bin/python -m pytest -q` passes in full.
2. A keepout declared `layers=(F,)` is silent about a track on B and still
   reports one on F; a via is caught by a region on any single layer.
3. A region partly off the board appears in `plan.keepouts` AND in
   `occupancy.reservations`, and its step counts the points that fell outside.
4. A region wholly off the board raises `ValueError` naming it, including under
   `keep_going=True`.
5. A rule area in a group survives `apply_plan`; a group-less one is replaced.
6. `BoardGeometry.rule_areas` carries name, cell, polygon, layers and excludes.
7. A part is refused for sitting in a cell's stamped region after that cell is
   committed, and the region moved with the cell.
8. A `no legal location` finding names up to three blocking owners with faces.
9. `plan.seeded_by_net` counts seeding nets, a declared plane net never appears,
   and the run prints a `seeded` line.
10. `api.md`, `SKILL.md` and `references/migration.md` are updated, and the
    migration file has a section per release with both 0.6 and 0.7 present.
11. `git log --format=%B <base>..HEAD | grep -iE "claude|anthropic|session|co-authored"`
    returns nothing.
