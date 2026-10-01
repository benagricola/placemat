# Keepout drawings and push implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (chosen: inline, this session) together with superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every behaviour gets a failing test first, watched failing for the right reason, before the code that makes it pass.

**Goal:** Draw what a keepout admits (height, named parts, nets) on the board so KiCad's view shows it, and add `board.push()`, a search intent that holds an item back from a source by a physical falloff model instead of a hand-picked point.

**Architecture:** Keepout drawings are a write-time-only addition: `write._draw_keepouts` gains a sibling that draws an outline and a label per admitting keepout into placemat's own `keepout drawings` group, replaced whole every run, reading three new `[write]` settings. Push is a new declaration, `Board.push()`, that attaches a `Push` record to the target's existing `PlaceIntent` (mirroring how a keepout's `at=` or a row's `of=` already add to `PlaceIntent.needs`): the source is added to `needs` so it settles first; a hard-limit disc is reserved against the target item alone (every other part is named in `owners`, so nothing else is fenced by it) using the existing `Reservation`/`let_in` mechanism unmodified; the soft price is folded into `Scorer`'s existing candidate cost, bypassing the Rust native scorer for a pushed item so `NativeScoring` (owned by the performance work in flight elsewhere) is untouched.

**Tech Stack:** Python 3, pytest, pcbnew (KiCad's Python bindings, via `tests.conftest.needs_kicad`).

**Spec:** `docs/superpowers/specs/2026-09-30-keepout-labels-and-push-design.md`

## Global Constraints

- No project, board, module or part name anywhere in source, docstrings, skill text, references, migration notes or commit messages. Test fixtures and doc examples use generic names (`m`, `u1`, `u2`).
- Every tunable is a setting with a default in `Settings`, never a literal in the code that uses it: `write.keepout_drawings`, `write.keepout_line`, `write.keepout_text`, `score.push`.
- Fixed sets of values are validated choices (`settings._CHOICES`), not free strings.
- Plain ASCII only: no em/en dashes, no unicode arrows, straight quotes.
- Placemat is intent-driven: no X/Y arithmetic in doc examples; a script says what it means (a push's `from_=`, `falloff=`, `reference=`) and the placer works out the coordinate.
- Commits: `git -c user.name="<owner name>" -c user.email="<owner email>" commit ...`, zero mentions of Claude/Anthropic/AI/sessions/Co-Authored-By; verify with `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"` (must print nothing) after every commit.
- Tests: run only the targeted files named in each task, via `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/<files>`. Never run the full suite. Never `uv pip install` or `maturin develop`. Never the router.
- New fields on dataclasses that already feed `reuse.canonical()` digests (`PlaceIntent`) carry `metadata={"omit_default": True}` at their empty default, so a script that never calls `push()` digests exactly as before.
- Additive to scoring/search: no changes to `giveway.py`, `checks.py`, the native Rust scorer (`NativeScoring`), or `explore.py`/`cleanup` - two other agents are working there concurrently.
- Bench once at the end: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2`, its tally lines go in the final commit message.

## Review Focus

- A keepout with BOTH `max_height=` and `allow=` parts: the drawn label must show both clauses ("parts <= H mm; U3, U4"), not just one - a reader who only sees the height clause would place a named part expecting it excluded when it is in fact admitted twice over. Covered in Task 3.
- A push whose `limit=` is at or below the modelled value AT `r_ref` (the hard-limit radius comes out at or under `r_ref` itself, or even zero/undefined at `falloff` close to 0): the radius formula `r_ref * (v_ref/limit) ** (1/falloff)` must not raise (division by a tiny falloff, or a negative base) for any value the validation lets through - covered by validating `falloff`, `r_ref`, `v_ref`, `limit` all strictly positive in Task 4, and a formula test in Task 5.
- Two pushes on the same item whose sources coincide (declared twice from the same part): each gets its OWN hard-limit reservation with a distinct `source=` tag, so retrying the settle (the `solved is not None` drop-the-hint retry in `_settle`) does not accumulate duplicate reservations across attempts - covered by the `source="push:%s:%d"` tagging and pre-clear in Task 5.
- A pushed item that never finds a legal spot (its whole search radius is inside every push's hard-limit disc): must fail the same way any other unplaced searched item does (an `unplaced` finding naming it), not crash on a `None` from `scan()` - covered by a dedicated test in Task 6, since the wide-radius branch is new code on that path.
- A keepout drawn on a face that is ALSO the whole board's default `write.keepout_drawings = "admitting"`, re-run twice: the group must hold exactly the drawings of the CURRENT keepouts, not the previous run's stale set if a keepout was removed from the script between runs - covered by the "replaced whole" test in Task 3, which reruns after removing a keepout from the plan (not just re-running the same plan).

---

## Task 1: Settings for keepout drawings and push

**Files:**
- Modify: `src/placemat/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.write_keepout_drawings: str` ("admitting"/"all"/"none", default "admitting"), `Settings.write_keepout_line: float` (default 0.1), `Settings.write_keepout_text: float` (default 0.8), `Settings.score_push: float` (default 10.0). Consumed by Task 3 (write.py) and Task 6 (Scorer).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py`:

```python
def test_keepout_drawing_and_push_defaults():
    s = S.Settings()
    assert s.write_keepout_drawings == "admitting"
    assert s.write_keepout_line == 0.1
    assert s.write_keepout_text == 0.8
    assert s.score_push == 10.0


def test_keepout_drawings_is_a_validated_choice(tmp_path):
    _toml(tmp_path / "placemat.toml", '[write]\nkeepout_drawings = "sometimes"\n')
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "write.keepout_drawings" in str(e.value) and "admitting" in str(e.value)


def test_keepout_line_and_text_have_a_floor(tmp_path):
    _toml(tmp_path / "placemat.toml", "[write]\nkeepout_line = 0.0\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "write.keepout_line" in str(e.value) and "greater than 0" in str(e.value)


def test_score_push_may_be_zero_but_not_negative(tmp_path):
    _toml(tmp_path / "placemat.toml", "[score]\npush = 0.0\n")
    assert S.load(tmp_path).score_push == 0.0
    _toml(tmp_path / "placemat.toml", "[score]\npush = -1.0\n")
    with pytest.raises(S.SettingsError):
        S.load(tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings.py -k "keepout_drawing_and_push_defaults or keepout_drawings_is_a_validated_choice or keepout_line_and_text_have_a_floor or score_push_may_be_zero"`
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'write_keepout_drawings'`, or the SettingsError never raised).

- [ ] **Step 3: Add the settings**

In `src/placemat/settings.py`, right after the `write_split_groups` line in the `# [write]` block:

```python
    write_keepout_drawings: str = "admitting"   # a keepout that admits something drawn on its Fab layer (or User.Comments): "admitting" (default), "all" every keepout, "none"
    write_keepout_line: float = 0.1    # a drawn keepout's outline stroke
    write_keepout_text: float = 0.8    # a drawn keepout's label height
```

Right after the `score_via_drop` line in the `# [score]` block:

```python
    score_push: float = 10.0            # a push: score.push times the modelled value over its limit, at the search
```

In `_CHOICES`, add an entry:

```python
_CHOICES = {"place_envelope": ("courtyard", "physical", "union"), "place_rotations": ("all", "declared"),
            "copper_cell_zones_under_planes": ("drop", "keep"), "write_split_groups": ("lift", "split", "keep"),
            "write_keepout_drawings": ("admitting", "all", "none")}
```

In `_ABOVE_ZERO`, add `"write_keepout_line", "write_keepout_text"` to the frozenset.

In `_AT_LEAST_ZERO`, add `"score_push"` to the frozenset.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings.py`
Expected: PASS, whole file.

- [ ] **Step 5: Document the settings in api.md**

In `skills/placemat/references/api.md`'s settings table, add a row right after the `write.split_groups` row:

```
| `write.keepout_drawings` | "admitting" | draw a keepout's outline and what it admits, on its Fab layer (or `User.Comments` for one on both faces or on inner layers only): `admitting` (default) those that admit something (`allow=` or `max_height=`), `all` every keepout, `none` |
| `write.keepout_line` | 0.1 | a drawn keepout's outline stroke |
| `write.keepout_text` | 0.8 | a drawn keepout's label height |
```

And a row right after the `score.via_drop` row:

```
| `score.push` | 10 | mm-equivalent: `score.push` times a push's modelled value over its limit, at the search |
```

- [ ] **Step 6: Commit**

```bash
git add src/placemat/settings.py tests/test_settings.py skills/placemat/references/api.md
git -c user.name="<owner name>" -c user.email="<owner email>" commit -m "Settings for keepout drawings and a push's price"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
The grep must print nothing.

---

## Task 2: PlacedKeepout carries its height admission

**Files:**
- Modify: `src/placemat/layout.py` (`PlacedKeepout` class, `~line 306`; `settle_keepout`'s `plan.keepouts[k.name] = ...` line, `~line 3952`)
- Test: `tests/test_part_height.py`

**Interfaces:**
- Produces: `PlacedKeepout.max_height: float | None` (the keepout's own `max_height=`, `None` when it has none), `PlacedKeepout.admitted: frozenset` (the parts admitted by height alone, a subset of `.owners`). `.owners` is unchanged (still the union of named and height-admitted parts, for `runner.py`'s DRC-permitted matching). Consumed by Task 3.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_part_height.py`:

```python
def test_the_placed_keepout_carries_its_height_admission_separately():
    b, plan = _board("1.1mm")
    k = plan.keepouts["ring"]
    assert k.max_height == 1.9
    assert k.admitted == {"C1"}
    assert k.owners == {"C1"}                      # unchanged: still the union, for runner.py


def test_a_part_named_in_allow_is_not_counted_as_height_admitted():
    b, plan = _board("2.5", allow=(Part("c1"),))
    k = plan.keepouts["ring"]
    assert k.admitted == frozenset()
    assert k.owners == {"C1"}
```

`Part` is already imported at the top of `tests/test_part_height.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_part_height.py -k "carries_its_height_admission_separately or not_counted_as_height_admitted"`
Expected: FAIL (`AttributeError: 'PlacedKeepout' object has no attribute 'max_height'`).

- [ ] **Step 3: Add the fields and pass them through**

In `src/placemat/layout.py`, `PlacedKeepout`'s class body, add two fields at the end:

```python
@dataclass(frozen=True)
class PlacedKeepout:
    """A region once it has a position: what it forbids, where, and to whom."""
    name: str
    poly: tuple
    centre: Location
    rotation: float
    excludes: tuple
    layers: tuple | None
    allow: frozenset
    owners: frozenset
    why: str
    max_height: float | None = None     # the keepout's own max_height=, for its drawn label
    admitted: frozenset = frozenset()   # the parts owners admits by height alone, a subset of owners
```

In `settle_keepout` (inside `resolve()`), change the construction call:

```python
                plan.keepouts[k.name] = PlacedKeepout(k.name, poly, centre, turn, k.excludes,
                                                      k.layers, nets, owners | (admitted or frozenset()), k.why,
                                                      k.max_height, admitted or frozenset())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_part_height.py tests/test_keepouts.py tests/test_keepout_faces.py tests/test_keepout_inside.py`
Expected: PASS, all four files (the last three are unaffected by this change but confirm nothing else reads `PlacedKeepout`'s old positional shape).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_part_height.py
git -c user.name="<owner name>" -c user.email="<owner email>" commit -m "A placed keepout carries its own height admission, for its drawn label"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 3: Draw a keepout's outline and what it admits

**Files:**
- Modify: `src/placemat/kicad/write.py` (add `_draw_keepout_drawings`, call it from `apply_plan`)
- Test: create `tests/test_keepout_drawings.py`
- Docs: `skills/placemat/references/api.md` (Keepouts section), `skills/placemat/references/migration.md` (new `## Unreleased` section)

**Interfaces:**
- Consumes: `PlacedKeepout.max_height`, `.admitted`, `.owners`, `.allow`, `.layers`, `.poly`, `.name` (Task 2); `Settings.write_keepout_drawings/line/text` (Task 1).
- Produces: `_draw_keepout_drawings(board, plan)` in `src/placemat/kicad/write.py`, called from `apply_plan` right after `_draw_keepouts(board, plan)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keepout_drawings.py`:

```python
"""What a keepout's own drawing says on the board: its outline and what it
admits, on the Fab layer of its face (or User.Comments), in placemat's own
`keepout drawings` group, replaced whole on every write."""
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint


def _height_board(**kw):
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"})]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, **kw)
    b.keepout(Circle(8.0), "ring", at=Location(20, 20), excludes=("parts",), max_height=1.9,
              why="the case leaves 1.9 mm here")
    b.place(Part("c1"), at=Location(20, 20))
    return b


def _drawn(plan, copper_layers=2):
    import pcbnew
    from placemat.kicad.write import _draw_keepout_drawings
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(copper_layers)
    _draw_keepout_drawings(board, plan)
    return board


@needs_kicad
def test_an_admitting_keepout_draws_an_outline_and_a_label():
    import pcbnew
    plan = _height_board().resolve()
    board = _drawn(plan)
    shapes = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE)]
    texts = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    assert len(shapes) == 1 and len(texts) == 1
    assert texts[0].GetText() == "ring: parts <= 1.90 mm"
    assert shapes[0].GetLayer() == pcbnew.F_Fab and texts[0].GetLayer() == pcbnew.F_Fab


@needs_kicad
def test_a_keepout_admitting_by_name_and_by_height_shows_both_clauses():
    import pcbnew
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"}),
           footprint("C2", 25, 20, w=2, h=1, inst="c2", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.keepout(Circle(10.0), "ring", at=Location(21, 20), excludes=("parts",), max_height=1.9,
              allow=(Part("c2"),), why="the case, and c2 is bolted through it")
    b.place(Part("c1"), at=Location(20, 20))
    b.place(Part("c2"), at=Location(25, 20))
    plan = b.resolve()
    board = _drawn(plan)
    text = next(d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT))
    assert text.GetText() == "ring: parts <= 1.90 mm; C2"


@needs_kicad
def test_they_share_one_group_replaced_whole_on_a_rerun_with_fewer_keepouts():
    import pcbnew
    from placemat.kicad.write import _draw_keepout_drawings
    plan = _height_board().resolve()
    board = _drawn(plan)
    groups = [g for g in board.Groups() if g.GetName() == "keepout drawings"]
    assert len(groups) == 1 and len(list(groups[0].GetItems())) == 2
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"})]
    b2 = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)   # no keepout this time
    b2.place(Part("c1"), at=Location(20, 20))
    _draw_keepout_drawings(board, b2.resolve())
    groups = [g for g in board.Groups() if g.GetName() == "keepout drawings"]
    assert groups == [] or len(list(groups[0].GetItems())) == 0
    assert not [d for d in board.GetDrawings() if isinstance(d, (pcbnew.PCB_SHAPE, pcbnew.PCB_TEXT))]


@needs_kicad
def test_a_keepout_admitting_nothing_is_not_drawn_by_default_and_is_drawn_under_all():
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.keepout(Circle(8.0), "quiet", at=Location(20, 20), why="clearance")
    plan = b.resolve()
    board = _drawn(plan)
    assert not list(board.GetDrawings())
    b_all = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5,
                  settings=Settings(write_keepout_drawings="all"))
    b_all.keepout(Circle(8.0), "quiet", at=Location(20, 20), why="clearance")
    plan_all = b_all.resolve()
    board_all = _drawn(plan_all)
    assert len(list(board_all.GetDrawings())) == 2


@needs_kicad
def test_write_keepout_drawings_none_draws_nothing():
    b = _height_board(settings=Settings(write_keepout_drawings="none"))
    plan = b.resolve()
    board = _drawn(plan)
    assert not list(board.GetDrawings())


@needs_kicad
def test_both_face_keepouts_go_on_user_comments():
    import pcbnew
    plan = _height_board().resolve()          # layers=None: every copper layer the 2-layer board has -> both faces
    board = _drawn(plan, copper_layers=2)
    shape = next(d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE))
    assert shape.GetLayer() == pcbnew.Cmts_User


@needs_kicad
def test_a_stamped_fragments_own_nested_group_is_left_alone():
    """A stamped fragment's own keepout drawing, still nested in its cell's
    group at this point in the write (before _write_groups lifts nested
    groups), is not placemat's `keepout drawings` group to replace: only a
    TOP-LEVEL group by that name is ours."""
    import pcbnew
    from placemat.kicad.write import _draw_keepout_drawings
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(2)
    cell = pcbnew.PCB_GROUP(board)
    cell.SetName("m")
    board.Add(cell)
    nested = pcbnew.PCB_GROUP(board)
    nested.SetName("keepout drawings")
    board.Add(nested)
    cell.AddItem(nested)
    fragment_text = pcbnew.PCB_TEXT(board)
    fragment_text.SetText("shield: GND copper")
    fragment_text.SetLayer(pcbnew.F_Fab)
    board.Add(fragment_text)
    nested.AddItem(fragment_text)

    plan = _height_board().resolve()
    _draw_keepout_drawings(board, plan)

    assert fragment_text.GetText() == "shield: GND copper"       # untouched
    groups = {g.GetName(): g for g in board.Groups() if g.GetParentGroup() is None}
    assert "keepout drawings" in groups
    assert list(groups["keepout drawings"].GetItems())           # placemat's own, top-level, holds the new drawing
    still_nested = [g for g in board.Groups() if g.GetParentGroup() is cell]
    assert len(still_nested) == 1 and still_nested[0].GetName() == "keepout drawings"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_keepout_drawings.py`
Expected: FAIL (`ImportError: cannot import name '_draw_keepout_drawings'`).

Note: `_height_board()`'s default (no `layers=` on the keepout) covers every copper layer on a 2-layer board, i.e. both F.Cu and B.Cu, so its drawing goes on `User.Comments`, not `F.Fab`. Fix `test_an_admitting_keepout_draws_an_outline_and_a_label` and `test_a_keepout_admitting_by_name_and_by_height_shows_both_clauses` to declare `layers=[CopperLayer.F]` on their keepouts before running, so they land on `F.Fab` as asserted; add `CopperLayer` to the `from placemat.values import ...` line. Re-run this step after that fix and confirm the failure is now the same `ImportError` for all six tests (not an assertion error from a wrongly-designed fixture) before moving on.

- [ ] **Step 3: Implement the drawing**

In `src/placemat/kicad/write.py`, change the import line:

```python
from ..values import Box, CopperLayer, Face
```

Add, right after `_draw_keepouts` (after its closing line, before `_draw_outline`):

```python
_KEEPOUT_DRAWINGS_GROUP = "keepout drawings"


def _keepout_drawing_layer(layers):
    """The Fab layer a keepout's outline and label are drawn on: F.Fab or
    B.Fab when every one of its copper layers is on one face, else
    User.Comments (both faces, layers=None, or inner layers only)."""
    if layers is None:
        return pcbnew.Cmts_User
    faces = {l.face for l in layers if l.face is not None}
    if len(faces) != 1:
        return pcbnew.Cmts_User
    return pcbnew.F_Fab if next(iter(faces)) is Face.FRONT else pcbnew.B_Fab


def _keepout_admits_text(k) -> str:
    """`<name>: parts <= H mm` for a height, `<name>: U3, U4` for parts
    named by allow=, `<name>: GND copper` for nets, joined with '; ' when
    a keepout admits more than one kind."""
    clauses = []
    if k.max_height is not None:
        clauses.append("parts <= %.2f mm" % k.max_height)
    named = sorted(k.owners - k.admitted)
    if named:
        clauses.append(", ".join(named))
    if k.allow:
        clauses.append(", ".join(sorted(k.allow)) + " copper")
    return "%s: %s" % (k.name, "; ".join(clauses))


def _keepout_admits(k) -> bool:
    return k.max_height is not None or bool(k.owners - k.admitted) or bool(k.allow)


def _draw_keepout_drawings(board, plan):
    """Each keepout that admits something (write.keepout_drawings), drawn as
    its outline and a label naming what it admits, in placemat's own group
    `keepout drawings`, replaced whole every run. A stamped fragment's own
    (still nested in its cell's group at this point in the write, before
    _write_groups lifts nested groups) is left alone: only the top-level
    group by this name is ours."""
    for g in list(board.Groups()):
        if g.GetName() == _KEEPOUT_DRAWINGS_GROUP and g.GetParentGroup() is None:
            for it in list(g.GetItems()):
                g.RemoveItem(it)
                board.Delete(it)
            board.Delete(g)
    mode = plan.occupancy.settings.write_keepout_drawings
    if mode == "none":
        return
    line = plan.occupancy.settings.write_keepout_line
    size = plan.occupancy.settings.write_keepout_text
    drawn = []
    for k in plan.keepouts.values():
        if mode == "admitting" and not _keepout_admits(k):
            continue
        layer = _keepout_drawing_layer(k.layers)
        sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
        sh.SetLayer(layer)
        sh.SetFilled(False)
        sh.SetWidth(nm(line))
        ps = pcbnew.SHAPE_POLY_SET()
        ps.NewOutline()
        for x, y in k.poly:
            ps.Append(nm(x), nm(y))
        sh.SetPolyShape(ps)
        board.Add(sh)
        drawn.append(sh)
        centre = Box.of_points(k.poly).center
        t = pcbnew.PCB_TEXT(board)
        t.SetText(_keepout_admits_text(k))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(nm(size), nm(size)))
        t.SetTextThickness(nm(line))
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        t.SetPosition(vec(centre.x, centre.y))
        board.Add(t)
        drawn.append(t)
    if drawn:
        g = pcbnew.PCB_GROUP(board)
        g.SetName(_KEEPOUT_DRAWINGS_GROUP)
        for it in drawn:
            g.AddItem(it)
        board.Add(g)
```

`Box.of_points` already exists (used throughout `write.py`'s callers via `values.Box`); confirm it is exported from `..values` (it is: `board_geometry.py` imports `Box` the same way).

In `apply_plan`, right after the existing `_draw_keepouts(board, plan)` line, add:

```python
    _draw_keepout_drawings(board, plan)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_keepout_drawings.py tests/test_keepouts.py tests/test_part_height.py tests/test_write_roundtrip.py`
Expected: PASS, all four files.

- [ ] **Step 5: Document in api.md and migration.md**

In `skills/placemat/references/api.md`'s Keepouts section, add a new paragraph right after the "**What KiCad reports.**" paragraph (before "**The board edge.**"):

```
**Drawn on the board.** A rule area is a hatch on a copper layer with
nothing saying what it admits, so alongside it, a keepout that admits
something (`allow=` or `max_height=`) is drawn as its own outline and a
label naming what it admits - `ring: parts <= 1.90 mm`, `antenna: R_ANT
copper`, joined with `; ` when it admits more than one kind - on the Fab
layer of its face (`F.Fab` for a keepout on `F.Cu`), or `User.Comments`
for one on both faces or on inner layers only. `write.keepout_drawings`
chooses which: `admitting` (the default), `all`, or `none`. These
drawings are placemat's own, in one group, `keepout drawings`, replaced
whole on every write; a stamped fragment's own belong to its cell's group
and move with it, as its rule areas do.
```

In `skills/placemat/references/migration.md`, add a new section at the very top, above `## To 0.57.2`:

```markdown
## Unreleased

A keepout that admits something (`allow=` or `max_height=`) is now also
drawn on the board: its outline and a label naming what it admits, on the
Fab layer of its face or `User.Comments`, in its own group `keepout
drawings`. `write.keepout_drawings = "none"` turns it off; `"all"` draws
every keepout, admitting or not.

```

- [ ] **Step 6: Commit**

```bash
git add src/placemat/kicad/write.py tests/test_keepout_drawings.py skills/placemat/references/api.md skills/placemat/references/migration.md
git -c user.name="<owner name>" -c user.email="<owner email>" commit -m "Draw what a keepout admits on its Fab layer"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 4: Declare a push, and its order dependency

**Files:**
- Modify: `src/placemat/layout.py` (`Link` class area for the new `Push` dataclass; `PlaceIntent` class; `Board.link` area for the new `Board.push` method; `Plan` class for `pushes` field)
- Test: create `tests/test_push.py`

**Interfaces:**
- Produces: `Push` dataclass (`source`, `falloff`, `r_ref`, `v_ref`, `limit`, `target_pad_key`, `why`, `achieved_value`, `achieved_mm`); `PlaceIntent.pushes: tuple` (new field, `metadata={"omit_default": True}`); `Board.push(item, *, from_, falloff, reference, limit, why="") -> Push`; `Plan.pushes: list`.
- Consumes: `Board._pad_ref`, `Board._item`, `layout._refs_in` (existing).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_push.py`:

```python
"""board.push(): an item held back from a source by a physical falloff
model, not a hand-picked point. Pure declaration and ordering here; the
hard limit, the soft price and the step note are later tasks."""
import pytest

from placemat.layout import Board
from placemat.values import Location, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("M1", 10, 10, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 30, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def test_push_needs_a_place_declaration_first():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    with pytest.raises(ValueError, match="place"):
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)


def test_push_validates_its_numbers():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    with pytest.raises(ValueError):
        b.push(Part("u2"), from_=Part("m1"), falloff=0, reference=(13.5, 3.2), limit=0.3)
    with pytest.raises(ValueError):
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(0, 3.2), limit=0.3)
    with pytest.raises(ValueError):
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0)
    with pytest.raises(ValueError):
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 0), limit=0.3)


def test_push_from_an_unknown_keepout_name_is_refused():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    with pytest.raises(ValueError, match="keepout"):
        b.push(Part("u2"), from_="nope", falloff=3, reference=(13.5, 3.2), limit=0.3)


def test_a_push_attaches_to_the_items_own_intent():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    intent = b.place(Part("u2"))
    p = b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3, why="field at the sensor")
    assert intent.pushes == (p,)
    assert p.falloff == 3 and p.r_ref == 13.5 and p.v_ref == 3.2 and p.limit == 0.3
    assert p.why == "field at the sensor"
    assert p.target_pad_key is None


def test_a_push_on_a_padref_records_which_pad():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    p = b.push(PadRef(Part("u2"), "SIG"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    assert p.target_pad_key == ("U2", "1")


def test_a_pushed_item_waits_for_its_source_when_both_are_searched():
    b = _board()
    b.place(Part("m1"))
    b.place(Part("u2"))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    m1_intent = next(i for i in b._intents if i.key == "m1")
    assert m1_intent.needs == frozenset()
    u2_intent = next(i for i in b._intents if i.key == "u2")
    assert u2_intent.needs == frozenset({"M1"})
```

`PadRef(Part("u2"), "SIG")` resolves to `("U2", "1")` because `footprint()`'s fixture builder puts the first-listed net (here "SIG") on pad 1 (see `tests/fixtures.py`'s `footprint()`: `pads = (pad(ref, inst, 1, nets[0], ...), pad(ref, inst, 2, nets[1], ...))`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py`
Expected: FAIL (`AttributeError: 'Board' object has no attribute 'push'`).

- [ ] **Step 3: Add the Push dataclass, the PlaceIntent field, Plan.pushes, and Board.push**

In `src/placemat/layout.py`, right after the `Link` class (after its `within_limit` property, before `class Step:`):

```python
@dataclass
class Push:
    """One physical effect holding an item back from a source: value(r) =
    v_ref * (r_ref / r) ** falloff, in the script's own units. Illegal
    where value(r) exceeds limit; within that, the search prices each
    candidate score.push * value(r) / limit."""
    source: object                        # Part, Cell, PadRef, a keepout's name (str), or a Location
    falloff: float
    r_ref: float
    v_ref: float
    limit: float
    target_pad_key: tuple | None = None   # (refdes, pad number): where on the item to measure from; None: its body centre
    why: str = field(default="", metadata={"reuse": False})
    achieved_value: float | None = field(default=None, metadata={"reuse": False})   # measured by a resolve, not declared
    achieved_mm: float | None = field(default=None, metadata={"reuse": False})
```

In `PlaceIntent`'s class body, add one field alongside the other `omit_default` ones (right after `drops`):

```python
    pushes: tuple = field(default=(), metadata={"omit_default": True})   # Push declarations on this item, from board.push()
```

In `Plan`'s class body, add one field alongside `links`:

```python
    pushes: list = field(default_factory=list)                    # every push, once its item has a place (Push)
```

In `Board`, right after the `link` method (before `free_net`):

```python
    def push(self, item, *, from_, falloff: float, reference: tuple, limit: float, why: str = "") -> Push:
        """Price how far `item` must stand from `from_`: value(r) = v_ref *
        (r_ref / r) ** falloff, `reference=(r_ref, v_ref)` in the script's
        own units. Illegal where value(r) exceeds `limit`; within that,
        each candidate is priced `score.push * value(r) / limit`, so the
        search moves the item as far out as its other terms allow.

        `item` is a `Part`, or a `PadRef` on one for where the sensing
        element is. `from_` is a `Part` or a `Cell` (its body centre), a
        `PadRef`, a keepout's name, or a `Location`. The source is placed
        first, the same order dependency a position said in terms of a pad
        already carries."""
        if isinstance(item, PadRef):
            owner, number, _, _ = self._pad_ref(item)
            target_pad_key = (owner, number)
        else:
            geom, owner, kind = self._item(item)
            if kind != "part":
                raise TypeError("push: item is a Part or a PadRef on one, not %r" % (item,))
            target_pad_key = None
        intent = next((i for i in self._intents if i.key == owner), None)
        if intent is None:
            raise ValueError("%s: push needs a place() declaration for this item before board.push()" % owner)
        if isinstance(falloff, bool) or not isinstance(falloff, (int, float)) or not falloff > 0:
            raise ValueError("push: falloff is more than 0, not %r" % (falloff,))
        if not (isinstance(reference, tuple) and len(reference) == 2):
            raise TypeError("push: reference is (r_ref, v_ref), not %r" % (reference,))
        r_ref, v_ref = reference
        if isinstance(r_ref, bool) or not isinstance(r_ref, (int, float)) or not r_ref > 0:
            raise ValueError("push: reference's radius (r_ref) is more than 0, not %r" % (r_ref,))
        if isinstance(v_ref, bool) or not isinstance(v_ref, (int, float)) or not v_ref > 0:
            raise ValueError("push: reference's value (v_ref) is more than 0, not %r" % (v_ref,))
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not limit > 0:
            raise ValueError("push: limit is more than 0, not %r" % (limit,))
        if isinstance(from_, str) and from_ not in self._keepouts:
            raise ValueError("push: %r is not a keepout on this board" % (from_,))
        p = Push(from_, float(falloff), float(r_ref), float(v_ref), float(limit), target_pad_key, why)
        intent.pushes = intent.pushes + (p,)
        intent.needs = intent.needs | {self._pad_ref(r)[0] for r in _refs_in([from_])}
        return p
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py`
Expected: PASS, all seven tests.

- [ ] **Step 5: Digest parity**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_copper_digest_parity.py tests/test_enum_digest_parity.py tests/test_lock.py tests/test_lock_digest.py tests/test_instance_keys.py`
Expected: PASS, unchanged - `PlaceIntent.pushes` defaults to `()` and carries `omit_default`, so a declaration that never calls `push()` digests exactly as before.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/layout.py tests/test_push.py
git -c user.name="<owner name>" -c user.email="<owner email>" commit -m "board.push(): a push declaration, and its source placed first"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 5: The hard limit - a disc reserved against the item alone

**Files:**
- Modify: `src/placemat/layout.py` (new module-level `_circle` usage via a new `Board._reserve_pushes` method and `_push_source_point`/`_push_source_label` module functions; `_settle`'s top)
- Test: append to `tests/test_push.py`

**Interfaces:**
- Consumes: `Push` (Task 4), `occ.reserve`, `occ._footprint_refs`-equivalent via `self.geometry.footprints` (existing), `_circle` (existing module function), `_locate` (existing module function), `plan.keepouts[name].centre` (Task 2/existing).
- Produces: `Board._reserve_pushes(occ, plan, i) -> list[(Location, Push)]`, called from `_settle`. Consumed by Task 6 (the same resolved list feeds the Scorer and the step note).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_push.py`:

```python
from placemat.values import Face
from placemat.placement import Placement


def test_a_firm_spot_inside_the_hard_limit_is_refused():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    # the disc's radius: 13.5 * (3.2 / 0.3) ** (1/3) ~= 13.5 * 2.213 ~= 29.9 mm - anywhere on this
    # 60x60 board is inside it, so a firm spot a few mm from m1 is refused
    b.place(Part("u2"), at=Location(14, 10))
    plan = b.resolve()
    findings = [f for f in plan.findings if "u2" in f]
    assert any("push from m1" in f and "limit 0.3" in f for f in findings), findings


def test_the_disc_radius_follows_the_formula():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(11, 10))     # 1 mm from m1: inside any sane disc
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    plan = b.resolve()
    import math
    radius = 13.5 * (3.2 / 0.3) ** (1.0 / 3.0)
    assert radius == pytest.approx(29.86, rel=0.01)
    findings = [f for f in plan.findings if "u2" in f]
    assert any("29.9" in f or "29.8" in f for f in findings), findings


def test_falloff_changes_the_disc_radius():
    b3 = _board()
    b3.place(Part("m1"), at=Location(10, 10))
    b3.place(Part("u2"), at=Location(15, 10))
    b3.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    plan3 = b3.resolve()
    b1 = _board()
    b1.place(Part("m1"), at=Location(10, 10))
    b1.place(Part("u2"), at=Location(15, 10))
    b1.push(Part("u2"), from_=Part("m1"), falloff=1, reference=(13.5, 3.2), limit=0.3)
    plan1 = b1.resolve()
    r1 = next(f for f in plan1.findings if "u2" in f)
    r3 = next(f for f in plan3.findings if "u2" in f)
    assert r1 != r3    # different formula, different radius, different sentence


def test_every_other_part_is_still_let_in():
    """The disc is reserved against the pushed item alone: a different part
    may stand inside it, right beside the source."""
    fps = [footprint("M1", 10, 10, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 30, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("R1", 12, 10, w=1, h=1, inst="r1", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    b.place(Part("r1"), at=Location(12, 10))     # 2 mm from m1: well inside u2's disc
    plan = b.resolve()
    assert not any("r1" in f for f in plan.findings), plan.findings
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py -k "hard_limit or disc_radius or falloff_changes or every_other_part"`
Expected: FAIL - either no finding names `u2` at all (nothing reserves the disc yet), or an unrelated error, since `_reserve_pushes` does not exist yet and `i.pushes` is never consulted by `_settle`.

- [ ] **Step 3: Implement the reservation**

In `src/placemat/layout.py`, add two module-level functions right after `_circle` (which already exists at `~line 5983`):

```python
def _push_source_label(source) -> str:
    if isinstance(source, str):
        return "keepout %r" % source
    if isinstance(source, PadRef):
        return "%s pad %s" % (source.part, source.key)
    if isinstance(source, Location):
        return _loc(source)
    return str(source)          # Part or Cell: their own __str__ is their key


def _push_value(source_point: Location, point: Location, push: "Push") -> tuple:
    """(value, r) for a push at distance r from its source to `point`."""
    r = max(source_point.distance(point), 1e-6)
    return push.v_ref * (push.r_ref / r) ** push.falloff, r
```

Add a method to `Board`, right after `_scorer` (`~line 2734`):

```python
    def _push_source_point(self, occ: Occupancy, plan: Plan, source) -> Location:
        """Where a push's source sits, once it is placed: a keepout's own
        centre for a name, else wherever _locate finds a Part, Cell, PadRef
        or Location."""
        if isinstance(source, str):
            return plan.keepouts[source].centre
        return _locate(self, occ, source)

    def _reserve_pushes(self, occ: Occupancy, plan: Plan, i: PlaceIntent) -> list:
        """Each push's source point, resolved now (it is placed by then,
        `needs` sees to that), and its hard-limit disc reserved against
        this item alone: every OTHER part is named in owners, so nothing
        else is fenced by it (Reservation.owners / let_in, occupancy.py)."""
        own = {fp.ref for fp in members_of(i.item)}
        others = frozenset(fp.ref for fp in self.geometry.footprints) - own
        tag_prefix = "push:%s:" % i.key
        occ.reservations = [r for r in occ.reservations if not r.source.startswith(tag_prefix)]
        resolved = []
        for n, p in enumerate(i.pushes):
            point = self._push_source_point(occ, plan, p.source)
            radius = p.r_ref * (p.v_ref / p.limit) ** (1.0 / p.falloff)
            why = "push from %s (limit %.3g at %.3g mm)%s" % (
                _push_source_label(p.source), p.limit, radius, (": %s" % p.why) if p.why else "")
            occ.reserve(_circle(point, radius), why, owners=others, copper=False, source=tag_prefix + str(n))
            resolved.append((point, p))
        return resolved
```

In `_settle`, right after `clr = self.clearance` (before `if i.freedom.decided:`):

```python
        clr = self.clearance
        push_sources = self._reserve_pushes(occ, plan, i) if i.pushes else []
```

(Leave the rest of `_settle` untouched for this task; `push_sources` is unused past this point until Task 6, which is fine - Python does not complain about an unused local.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py`
Expected: PASS, all eleven tests.

- [ ] **Step 5: Run the wider placement suite for regressions**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_links.py tests/test_link_order.py tests/test_keepouts.py tests/test_part_height.py`
Expected: PASS, unaffected by this task (no script in these files calls `push()`).

- [ ] **Step 6: Commit**

```bash
git add src/placemat/layout.py tests/test_push.py
git -c user.name="<owner name>" -c user.email="<owner email>" commit -m "A push's hard limit: a disc reserved against the item alone"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 6: The soft price and the wide scan

**Files:**
- Modify: `src/placemat/layout.py` (`Scorer` class, `_scorer` method, `_settle`'s searched branch)
- Test: append to `tests/test_push.py`

**Interfaces:**
- Consumes: `push_sources` (Task 5's `_reserve_pushes` return), `Settings.score_push` (Task 1).
- Produces: `Scorer(settings, item, occ, targets, prune, pushes=())` (new optional param); `Scorer.native()` returns `None` when `self.pushes`, so a pushed item's candidates are scored in pure Python and the Rust `NativeScoring` module is never asked about a push.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_push.py`:

```python
def test_a_pushed_item_lands_at_or_under_the_limit_and_farther_than_unpushed():
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("J1", 55, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
    without = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    without.place(Part("m1"), at=Location(10, 30))
    without.place(Part("j1"), at=Location(55, 30))
    without.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    without.place(Part("u2"), radius=25.0, step=1.0)
    plan_without = without.resolve()
    d_without = plan_without.box("u2").center.distance(Location(10, 30))

    pushed = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    pushed.place(Part("m1"), at=Location(10, 30))
    pushed.place(Part("j1"), at=Location(55, 30))
    pushed.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    u2 = pushed.place(Part("u2"), radius=25.0, step=1.0)
    pushed.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3, why="field at the sensor")
    plan_pushed = pushed.resolve()
    d_pushed = plan_pushed.box("u2").center.distance(Location(10, 30))

    value = 3.2 * (2.0 / d_pushed) ** 3
    assert value <= 0.3 + 1e-6
    assert d_pushed > d_without


def test_two_pushes_add_and_push_the_item_farther_than_one():
    def _run(n_pushes):
        fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
               footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
               footprint("J1", 55, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
        b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
        b.place(Part("m1"), at=Location(10, 30))
        b.place(Part("j1"), at=Location(55, 30))
        b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"), weight=1)
        b.place(Part("u2"), radius=25.0, step=1.0)
        for _ in range(n_pushes):
            b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.9,
                   why="field at the sensor")
        plan = b.resolve()
        return plan.box("u2").center.distance(Location(10, 30))

    assert _run(2) >= _run(1)


def test_native_scoring_is_bypassed_for_a_pushed_item():
    from placemat.layout import Push, Scorer
    from placemat.occupancy import Occupancy
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"))]
    g = board_geometry(fps, width=60, height=60)
    occ = Occupancy(g, edge_margin=1.0)
    u2 = g.footprint("U2")
    push = Push(Location(10, 30), 3.0, 2.0, 3.2, 0.3)
    scorer = Scorer(occ.settings, u2, occ, [], False, pushes=[(Location(10, 30), push)])
    assert scorer.native((0.0,), Face.FRONT) is None


def test_a_pushed_item_with_nowhere_legal_is_unplaced_not_a_crash():
    """Every candidate anywhere on this tiny board is inside the hard-limit
    disc (a huge v_ref against a tiny limit): the wide scan finds nothing,
    and that is an ordinary unplaced finding, not an exception."""
    fps = [footprint("M1", 5, 5, w=2, h=2, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 15, w=2, h=2, inst="u2", nets=("SIG", "GND"))]
    b = Board(board_geometry(fps, width=20, height=20), edge_margin=0.5)
    b.place(Part("m1"), at=Location(5, 5))
    b.place(Part("u2"))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(1.0, 1000.0), limit=0.01)
    plan = b.resolve()
    assert plan.step("u2").placement is None
    assert any("u2" in f for f in plan.findings)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py -k "lands_at_or_under or two_pushes_add or native_scoring_is_bypassed or nowhere_legal"`
Expected: FAIL - `d_pushed` equals `d_without` (or the item stays at the pocket/seed spot: push has no effect on the score yet), `Scorer(...)` raises `TypeError: __init__() got an unexpected keyword argument 'pushes'`, and the nowhere-legal case currently PLACES the item anyway (nothing reserves its disc yet, so every candidate is legal).

- [ ] **Step 3: Implement the score term and the wide scan**

In `src/placemat/layout.py`, change `Scorer.__init__`:

```python
    def __init__(self, settings, item, occ: Occupancy, targets: list, prune: bool, pushes=()):
        s = settings
        self.s, self.item, self.occ, self.targets, self.prune = s, item, occ, targets, prune
        self.pushes = tuple(pushes)
        self.crossing = s.score_crossing
        self.rn = occ.ratsnest() if self.crossing > 0 else None
        self.escaping = s.score_escape_crossed > 0 or s.score_escape_closed > 0 or s.score_escape_walled > 0
        self.esc = occ.escapes() if self.escaping else None
        self.own = frozenset(fp.ref for fp in members_of(item))
        self.depth = s.place_escape_depth
        self.best = [math.inf]
        self._native = {}
```

Change `Scorer.__call__`, right after `cost = sum(...)`:

```python
    def __call__(self, placement: Placement) -> float:
        occ, s = self.occ, self.s
        pads = occ.candidate_pad_locations(self.item, placement)
        cost = sum(w * pads[key].distance(target) for key, target, w in self.targets if key in pads)
        if self.pushes:
            body_centre = None
            for source_point, push in self.pushes:
                if push.target_pad_key is not None:
                    point = pads.get(push.target_pad_key)
                    if point is None:
                        continue
                else:
                    if body_centre is None:
                        body_centre = occ.body_box(self.item, placement).center
                    point = body_centre
                value, _ = _push_value(source_point, point, push)
                cost += s.score_push * value / push.limit
        if self.prune and cost >= self.best[0]:
            return cost + PRUNED        # its crossings and escapes can only add: it cannot be the best
```

(the rest of `__call__` is unchanged)

Change `Scorer.native`'s opening lines to bypass when pushes are present:

```python
    def native(self, rots, face):
        """The same cost for the native sweep over these turns, or None when
        the native mirrors it needs are not there, or the item carries a
        push (the Rust NativeScoring module has no formula for one)."""
        if self.pushes:
            return None
        occ, s = self.occ, self.s
```

(the rest of `native` is unchanged)

Change `_scorer`:

```python
    def _scorer(self, item, occ: Occupancy, targets: list, prune: bool = True, pushes=()):
        """A candidate's cost: each connection's weight times its length,
        `score.crossing` for each ratsnest crossing its airwires would add,
        the escape weights, and (Task 6) score.push times each push's
        modelled value over its limit. See `Scorer`."""
        return Scorer(self.settings, item, occ, targets, prune, pushes)
```

In `_settle`, find:

```python
        else:
            return self._settle_in_pocket(occ, i, plan, clr)
        # riders refuse candidates after they are scored: a refused one must not prune the rest
        body = occ._geometry(i.item).body
        radius = i.radius if i.near is not None else max(i.radius, body.width, body.height)
```

and the `score = self._scorer(...)` line just above it. Replace this whole block (from the `elif targets:` branch's end through the `radius = ...` line) with:

```python
        elif push_sources:
            hint = Placement(self.centre, i.rotation, i.face)
            seeded = "searched wide for its push" if len(push_sources) == 1 else "searched wide for its pushes"
        else:
            return self._settle_in_pocket(occ, i, plan, clr)
        # riders refuse candidates after they are scored: a refused one must not prune the rest
        score = self._scorer(i.item, occ, targets, prune=self._pick(i) is None and self._accept(i) is None,
                             pushes=push_sources) if targets or push_sources else None
        body = occ._geometry(i.item).body
        if i.near is not None:
            radius = i.radius
        elif push_sources and not targets and solved is None and self._outline is not None:
            radius = math.hypot(self._outline.width, self._outline.height)
        else:
            radius = max(i.radius, body.width, body.height)
```

Note the ORIGINAL `score = self._scorer(i.item, occ, targets, prune=...) if targets else None` line, which sat right after the `elif targets:` branch, is REMOVED (its replacement above now covers both the targets-only and the push cases in one place, and runs whether the hint came from `targets`, `push_sources`, `solved`, or `near`, so a part with BOTH links and a push still gets the push term).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py`
Expected: PASS, all fifteen tests. If `test_a_pushed_item_lands_at_or_under_the_limit_and_farther_than_unpushed` or `test_two_pushes_add_and_push_the_item_farther_than_one` is flaky at the geometry chosen (a 60x60 board, 25 mm radius, 1 mm step), widen `radius=` or move `m1`/`j1` further apart and re-run before treating a failure as a code bug - these two are the only steps in the whole plan whose exact fixture numbers are provisional; everything else is load-bearing as written.

- [ ] **Step 5: Run the wider search-path suite for regressions**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_links.py tests/test_link_order.py tests/test_native_sweep.py tests/test_scoring.py 2>&1 | tail -60`
(if `test_scoring.py` does not exist, drop it from the command)
Expected: PASS - `Scorer`'s new `pushes` parameter defaults to `()` everywhere else, so no existing caller's behaviour changes.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/layout.py tests/test_push.py
git -c user.name="<owner name>" -c user.email="<owner email>" commit -m "A push's soft price in the search, and a wide scan with no other hint"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 7: The step note and plan.pushes

**Files:**
- Modify: `src/placemat/layout.py` (`_settle`'s success path)
- Test: append to `tests/test_push.py`

**Interfaces:**
- Consumes: `push_sources`, `_push_value` (Task 5/6).
- Produces: each placed push's `Push.achieved_value`/`.achieved_mm` set; `plan.pushes` populated; the step's `.note` names each push's landing value, distance and limit.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_push.py`:

```python
def test_the_step_note_gives_the_value_and_the_distance():
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("J1", 55, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("m1"), at=Location(10, 30))
    b.place(Part("j1"), at=Location(55, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    b.place(Part("u2"), radius=25.0, step=1.0)
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3, why="field at the sensor")
    plan = b.resolve()
    note = plan.step("u2").note
    assert "push from m1:" in note and "limit 0.3" in note and "mm" in note
    assert len(plan.pushes) == 1
    p = plan.pushes[0]
    assert p.achieved_value is not None and p.achieved_value <= 0.3 + 1e-6
    assert p.achieved_mm is not None and p.achieved_mm > 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py -k step_note_gives`
Expected: FAIL (`"push from m1:" not in note` - `plan.pushes` empty, `note` has no push text).

- [ ] **Step 3: Implement the note and the reporting**

In `_settle`, find the existing block:

```python
        note = seeded
        if result.moved_mm > 0:
            first = next(iter(result.reasons.values()), "")
            moved = "moved %.2f mm off the hint" % result.moved_mm
            if first:
                moved += ": " + first
            elif score:
                moved += " for a better link score"
            note = (note + "; " if note else "") + moved
        return self._step(i, result.chosen, result.moved_mm, note)
```

Insert a new block between the `if result.moved_mm > 0:` block and the final `return`:

```python
        note = seeded
        if result.moved_mm > 0:
            first = next(iter(result.reasons.values()), "")
            moved = "moved %.2f mm off the hint" % result.moved_mm
            if first:
                moved += ": " + first
            elif score:
                moved += " for a better link score"
            note = (note + "; " if note else "") + moved
        if push_sources:
            body_centre = None
            bits = []
            for source_point, p in push_sources:
                if p.target_pad_key is not None:
                    at = occ.candidate_pad_locations(i.item, result.chosen).get(
                        p.target_pad_key, result.chosen.location)
                else:
                    if body_centre is None:
                        body_centre = occ.body_box(i.item, result.chosen).center
                    at = body_centre
                value, r = _push_value(source_point, at, p)
                p.achieved_value, p.achieved_mm = round(value, 4), round(r, 3)
                bits.append("push from %s: %.2g at %.1f mm (limit %.2g)" % (
                    _push_source_label(p.source), value, r, p.limit))
                plan.pushes.append(p)
            note = (note + "; " if note else "") + "; ".join(bits)
        return self._step(i, result.chosen, result.moved_mm, note)
```

This sits after the `if result.chosen is None:` unplaced-handling returns (both of them, higher up in the function), so `result.chosen` is never `None` here.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py`
Expected: PASS, all sixteen tests.

- [ ] **Step 5: Full push and keepout regression pass**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_push.py tests/test_keepout_drawings.py tests/test_keepouts.py tests/test_part_height.py tests/test_keepout_faces.py tests/test_keepout_inside.py tests/test_links.py tests/test_link_order.py tests/test_settings.py tests/test_settings_wiring.py tests/test_copper_digest_parity.py tests/test_enum_digest_parity.py tests/test_lock.py tests/test_lock_digest.py tests/test_instance_keys.py`
Expected: PASS, every file.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/layout.py tests/test_push.py
git -c user.name="<owner name>" -c user.email="<owner email>" commit -m "A push's step note gives its landing value and distance"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 8: Document push

**Files:**
- Modify: `skills/placemat/references/api.md` (intent index, new `## Push` section), `skills/placemat/references/migration.md` (`## Unreleased`), `skills/placemat/SKILL.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Intent index row**

In `skills/placemat/references/api.md`'s "Say it by intent" table, in the "**what pulls parts together**" block, add a row right after the `board.link(...)` row:

```
| a part held back from a source by physics, not a hand-picked point (a field sensor from a magnet, a heat-sensitive part from a heat source) | `board.push(item, from_=, falloff=, reference=(r_ref, v_ref), limit=)` | Push |
```

- [ ] **Step 2: A Push section**

In `skills/placemat/references/api.md`, add a new `## Push` section right after `## Links` (before `## Faces (a module's sides, declared once)`):

```markdown
## Push

```python
board.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2),
           limit=0.3, why="field at the sensor")
```

Prices how far an item must stand from a source: `value(r) = v_ref *
(r_ref / r) ** falloff`, `reference=(r_ref, v_ref)` in the script's own
units - a dipole's field falls off as the cube (`falloff=3`), heat
spreading through a plane roughly linearly (`falloff=1`). `r` runs from
`from_` to `item`.

`item` is a `Part`, or a `PadRef` on one for where the sensing element is
on the part. `from_` is a `Part` or a `Cell` (its body centre), a `PadRef`,
a keepout by name, or a `Location`. `item` must already have a
`board.place()` declaration of its own; `push()` adds to it, the same as
`board.link()` adds a pull.

**Hard limit.** Where `value(r)` would exceed `limit`, the item may not
stand: a disc round the source of radius `r_ref * (v_ref / limit) ** (1 /
falloff)`, reserved against the item alone (Reservation.owners /
occupancy.let_in) - every other part is still let in, so nothing else is
fenced by it. Refused like any reservation, naming the push: `sits in the
reservation for push from m1 (limit 0.3 at 29.9 mm)`.

**Soft price.** Within what is legal, each candidate is priced
`score.push` (default 10) times `value(r) / limit`, in the search's own
cost alongside its links and crossings - so the item moves as far out as
its other terms allow, not to a hand-picked point. Several pushes on one
item add their prices.

**Order.** The source is placed first: pushing from an item that is
itself searched waits for it, the same order dependency a position said
in terms of a pad already carries.

**No position hint.** A pushed item with no `at=` and nothing pulling it
is searched over the whole board, not near a small default radius: that
is what "as far as the board allows" needs.

**The report.** The item's step names each push's modelled value and
distance where it landed: `push from m1: 0.21 at 15.9 mm (limit 0.3)`.
`placemat check` does not re-judge it - the model is the script's own.
```

- [ ] **Step 3: migration.md**

In `skills/placemat/references/migration.md`, append to the `## Unreleased` section added in Task 3 (do not create a second one):

```markdown
`board.push(item, from_=, falloff=, reference=(r_ref, v_ref), limit=)`
holds an item back from a source by a physical falloff model: illegal
inside a disc round the source, priced by how close it stands within
that. Where a script used `Near` on a hand-picked far point for a
requirement the netlist cannot say, and the real requirement is a
distance a field or a temperature falls off over, `push` replaces the
hand-picked point with the physics.
```

- [ ] **Step 4: SKILL.md**

In `skills/placemat/SKILL.md`, in the "Placement and copper practice" bullet list, change:

```
- No floorplan by coordinate: a `Location` meaning "the power area" is the
  placer's job typed by hand. `Near` is for a requirement the netlist
  cannot say (a thermal sensor by FETs it shares no net with); a part with
  a wired neighbour is linked and left bare.
```

to:

```
- No floorplan by coordinate: a `Location` meaning "the power area" is the
  placer's job typed by hand. `Near` is for a requirement the netlist
  cannot say (a thermal sensor by FETs it shares no net with) when a
  point, not a distance, is what is known; when the requirement IS a
  distance a field or a temperature falls off over, `board.push()` prices
  it instead of a hand-picked point. A part with a wired neighbour is
  linked and left bare.
```

- [ ] **Step 5: Verify the docs build no broken cross references**

Run: `grep -n "## Push" skills/placemat/references/api.md` and confirm exactly one match; `grep -n "board.push" skills/placemat/SKILL.md skills/placemat/references/api.md skills/placemat/references/migration.md` and confirm each file has at least one match.

- [ ] **Step 6: Commit**

```bash
git add skills/placemat/references/api.md skills/placemat/references/migration.md skills/placemat/SKILL.md
git -c user.name="<owner name>" -c user.email="<owner email>" commit -m "Document board.push()"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 9: Full targeted verification and bench

**Files:** none (verification only).

- [ ] **Step 1: Run every targeted test file touched by this plan, together**

Run:
```bash
cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_settings.py tests/test_settings_wiring.py \
  tests/test_part_height.py tests/test_keepouts.py tests/test_keepout_faces.py tests/test_keepout_inside.py \
  tests/test_keepout_drawings.py tests/test_write_roundtrip.py \
  tests/test_push.py tests/test_links.py tests/test_link_order.py \
  tests/test_copper_digest_parity.py tests/test_enum_digest_parity.py tests/test_lock.py tests/test_lock_digest.py \
  tests/test_instance_keys.py
```
Expected: PASS, every file. Fix any failure before proceeding (do not weaken an assertion to make it pass; if a genuine design gap surfaces, fix the code).

- [ ] **Step 2: Bench**

Run: `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2`

This is a placement-scoring change (a new score term, a new wide-scan branch), so it runs once here even though no bench module declares a `push`. Record the tally lines it prints.

- [ ] **Step 3: Final report**

Gather: every commit hash and subject from this plan's task commits (`git log --oneline` since the branch point); the full test run's pass/fail counts; the bench tally; and every place this plan's own design differed from the spec's silence (documented in each task's steps and in the plan's Review Focus) - hand these to the report the calling instructions ask for.
