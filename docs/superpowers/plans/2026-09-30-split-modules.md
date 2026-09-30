# Split modules for placement: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (chosen; inline, TDD) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report a `split` finding for a cell whose members form two or more
groups joined only by board-level nets, so a capture author learns a module
boundary does not fit this board.

**Architecture:** A new pure module `src/placemat/splits.py` groups a
`CellGeom`'s members by the nets local to the cell (union-find over shared
local nets) and renders the finding's text. `layout.py`'s `Board.resolve()`
calls it once per run, for each cell the plan places, appending a
`Finding("split", ...)` and noting the cell's step - the same pattern
`_give_way_copper` already uses for the `vias` finding. A new setting,
`place.split_min_group`, is the least members a group needs to count. The
finding carries no run-score weight, like `vias`.

**Tech Stack:** Python 3, pytest, the existing `tests/fixtures.py` synthetic
`BoardGeometry` builders (no KiCad needed for these tests).

**Spec:** `docs/superpowers/specs/2026-09-30-split-modules-for-placement-design.md`
(section 3, the circuit-capture skill, is done elsewhere and out of scope
here). The spec's own wording for the finding's text and for the skill/docs
has been superseded by the coordinator, live, after the spec was written;
this plan carries the current wording. Differences from the spec text as
written:
- SKILL.md's new bullet is the coordinator's replacement text below, not
  the spec's section 1 bullet.
- capture.md's new section states only placemat's own view (the finding,
  where a split or a move is made, and what an unjoined part is); it does
  not restate circuit-capture's module-boundary rule, and does not name
  that skill.
- The finding's own sentence never uses the word "loose". A member no
  local net joins to another is described as a part "no net inside the
  cell joins ... to the others", each "placed by the pin it serves or the
  part it senses, not a split candidate". Code identifiers use `unjoined`,
  not `loose`. A bypass capacitor always belongs in the module of the IC
  it serves; a bypass capacitor between a board-level supply and a plane
  has no net inside its cell, so the grouping shows it apart - it is
  never a split candidate, whatever the grouping shows, and the finding's
  text and capture.md both say so plainly.

## Global Constraints

- placemat is project-agnostic: no project, board, module or part name in
  source, docstrings, skill text, migration notes, the plan or commit
  messages. Use generic designators (`m`, `U3`, `C7`, ...), exactly as the
  spec's own example does.
- Tunables are settings with defaults, never literals: `place.split_min_group`
  (default 2, an integer, at least 2) in `settings.py`.
- Plain ASCII only: no em/en dashes, no unicode arrows, straight quotes.
- Skill and doc text: plain, measured, no marketing tone.
- Commits: `git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la
  commit ...`. No reference to Claude, Anthropic, AI, sessions or
  Co-Authored-By in any commit message; verify with `git log -1
  --format=%B | grep -iE "claude|anthropic|session|co-authored"` after
  every commit (must print nothing).
- Tests: targeted files only, never the full suite. Before running any
  test: `cp /home/ben/work/placemat/src/placemat/_version.py
  src/placemat/`. Then: `PYTHONPATH=$PWD/src
  /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider
  tests/<files>`.
- Bench once, at the end: `PYTHONPATH=$PWD/src
  /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2`.
  The finding carries no score weight, so every config must read "same
  32"; put the tally in the final commit message.
- Never touch `~/Documents` or anything outside this repository. Never run
  `uv pip install`. Never run the router.

## Review Focus

- A member whose only local net touches no other member in the cell (a
  local net used only by itself) is not "no local net", but its group has
  one member, which can never reach `place.split_min_group` (floor 2): it
  always ends up reported as unjoined, alongside true no-local-net
  members. Task 3's tests pin this.
- Net-name iteration must not depend on Python's randomised string hashing
  for the grouping or message order: `_groups` orders strictly by
  `cell.members` position, never by set/dict iteration over net names.
  Task 3's tests build a cell with several nets and assert the exact
  message text, which would flake under hash randomisation if this were
  wrong.
- A pad with an empty net (`p.net` falsy) must not be counted as a net
  named `""`: both the board-wide and the cell-local pad counts filter on
  `if p.net`. Task 3 covers a footprint with an unconnected pad.
- `place.split_min_group` must reject 0, 1 and negative values (the floor
  is 2, not "above zero" like most of `settings.py`'s numeric fields) and
  accept exactly 2 and above. Task 2's tests cover 1 (just under the
  floor) and 2 (exactly at it).
- The finding must attach to the right step when a cell's plan key differs
  from its `CellGeom.name` is not a real case here (`plan._items` is keyed
  by the same string the step carries, as `_give_way_copper` already
  relies on) - Task 4's integration test still asserts the note lands on
  the cell's own step, not merely that a finding was appended, so a wrong
  key lookup would be caught.
- The finding's text must never read as telling a reader to split out a
  part that is already correctly placed by a pin or by what it senses (a
  bypass capacitor between a board-level supply and a plane has no net
  local to its cell, so it is reported apart from the IC it serves, but
  it is never a split candidate). The unjoined clause says so explicitly
  ("not a split candidate"), in the finding text itself and in capture.md.
  Task 3's message-text test pins the exact wording.

---

## Task 1: The `split` finding kind

**Files:**
- Modify: `src/placemat/findings.py` (the `KINDS` tuple, after `"needs"`
  at line 23)
- Modify: `tests/test_finding_kinds.py:35-36` (the `set(KINDS)` assertion)

**Interfaces:**
- Produces: `findings.KINDS` includes `"split"`, so `Finding("split", text)`
  no longer raises.

- [ ] **Step 1: Extend the failing assertion**

In `tests/test_finding_kinds.py`, change:

```python
    assert set(KINDS) == {"unplaced", "link_over", "fixed", "copper", "label", "escape_crossed", "pair_crossed",
                          "escape_closed", "escape_walled", "setup", "route", "vias", "fab", "facts", "needs"}
```

to:

```python
    assert set(KINDS) == {"unplaced", "link_over", "fixed", "copper", "label", "escape_crossed", "pair_crossed",
                          "escape_closed", "escape_walled", "setup", "route", "vias", "fab", "facts", "needs",
                          "split"}
```

- [ ] **Step 2: Run it, confirm it fails for the right reason**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_finding_kinds.py::test_a_finding_is_its_text_and_carries_its_kind
```

Expected: FAIL, the two sets differ by `{"split"}` (KINDS lacks it).

- [ ] **Step 3: Add the kind**

In `src/placemat/findings.py`, in the `KINDS` tuple, after the `"needs"`
line add:

```python
    "split",            # a cell whose members form two or more groups joined only by board-level nets
```

- [ ] **Step 4: Run it again, confirm it passes**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la add src/placemat/findings.py tests/test_finding_kinds.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "Finding kind split: a cell whose parts form separate groups"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

The grep must print nothing.

---

## Task 2: `place.split_min_group`

**Files:**
- Modify: `src/placemat/settings.py` (a new field after `place_drops_keep`
  at line 66; a new floor set; `_validate`)
- Modify: `skills/placemat/references/api.md` (the settings table, after
  the `place.drops_keep` row at line 2192)
- Modify: `tests/test_settings.py` (default and floor tests)

**Interfaces:**
- Produces: `Settings.place_split_min_group: int` (default `2`); loading a
  value below 2 raises `SettingsError`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings.py`, add:

```python
def test_split_min_group_defaults_to_two():
    assert S.Settings().place_split_min_group == 2


def test_a_split_min_group_under_two_is_an_error(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nsplit_min_group = 1\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "place.split_min_group" in str(e.value) and "at least 2" in str(e.value)


def test_a_split_min_group_of_two_is_allowed(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nsplit_min_group = 2\n")
    assert S.load(tmp_path).place_split_min_group == 2
```

- [ ] **Step 2: Run them, confirm they fail for the right reason**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings.py -k split_min_group
```

Expected: FAIL - `test_split_min_group_defaults_to_two` with
`AttributeError: 'Settings' object has no attribute 'place_split_min_group'`;
the other two likewise (the key is unknown to `_flatten`, so they raise
"is not a setting placemat has" rather than the floor message - still a
failure, for the right reason: the setting does not exist yet).

- [ ] **Step 3: Add the field**

In `src/placemat/settings.py`, after line 66 (`place_drops_keep: float =
0.5  ...`), add:

```python
    place_split_min_group: int = 2      # the least members a group needs to count, in a cell's split finding (splits.py)
```

- [ ] **Step 4: Add the floor**

`settings.py` has `_ABOVE_ZERO` (must be `> 0`) and `_AT_LEAST_ZERO` (must
be `>= 0`); this setting's floor is 2, not 0. Add a new frozenset near
them (after the `_AT_LEAST_ZERO` block, before `_declared`):

```python
# A floor of 2: below it a "group" can never be more than one part, which
# is not a group at all.
_AT_LEAST_TWO = frozenset(("place_split_min_group",))
```

In `_validate`, after the `_AT_LEAST_ZERO` check
(`if name in _AT_LEAST_ZERO and value < 0: ...`), add:

```python
    if name in _AT_LEAST_TWO and value < 2:
        raise SettingsError("%s: %s must be at least 2, not %r" % (path, dotted, value))
```

- [ ] **Step 5: Run the settings tests, confirm they pass**

Same command as Step 2. Expected: PASS.

- [ ] **Step 6: Run the full settings and wiring files, confirm the doc-coverage test now fails**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings.py tests/test_settings_wiring.py
```

Expected: FAIL - `test_every_setting_is_documented_in_the_api_reference`
lists `place.split_min_group` as missing from api.md. Everything else
passes.

- [ ] **Step 7: Document it**

In `skills/placemat/references/api.md`, in the settings table, after the
`place.drops_keep` row (line 2192), add:

```
| `place.split_min_group` | 2 | the least members a group needs to count as one, in a cell's `split` finding |
```

- [ ] **Step 8: Run both files again, confirm everything passes**

Same command as Step 6. Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la add src/placemat/settings.py tests/test_settings.py skills/placemat/references/api.md
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "Setting place.split_min_group: the least members a group needs to count"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 3: `splits.py` - grouping and the finding's text

**Files:**
- Create: `src/placemat/splits.py`
- Create: `tests/test_splits.py`

**Interfaces:**
- Consumes: `placemat.board_geometry.BoardGeometry`, `.CellGeom`,
  `.Footprint` (all existing); `tests/fixtures.py`'s `board_geometry()` and
  `footprint()` (existing, read above).
- Produces:
  - `splits.cell_text(geometry: BoardGeometry, cell: CellGeom, plane_nets,
    min_group: int, board_counts: dict | None = None) -> str | None` - the
    finding's text for one cell, or `None` when it is not a finding.
  - `splits.report(geometry: BoardGeometry, cells, plane_nets, min_group:
    int) -> list[tuple[str, str]]` - `(cell.name, text)` for every cell in
    `cells` that is a finding. Task 4 calls this from `layout.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_splits.py`:

```python
"""A cell of several jobs: placemat groups a cell's members by the nets
local to it and reports a cell of two or more groups as a `split` finding
(docs/superpowers/specs/2026-09-30-split-modules-for-placement-design.md,
section 2).

Every fixture board here is small (only what one test needs), so a net
that is meant to read as "board-level" must genuinely have a pad outside
the cell, or a pad on every member of the SAME cell with no outside pad at
all is indistinguishable, by pad count alone, from a real local net - a
free-floating net name with no second pad anywhere is not a useful stand-in
for "shared with the rest of the board" on a board this small. Most tests
below use `GND` (excluded because it is a declared plane, whatever its
pads) as the only non-local net, which sidesteps this; the one test that
also wants a genuine non-plane board-level net gives it a pad outside the
cell explicitly."""
import dataclasses

from placemat import splits
from tests.fixtures import board_geometry, footprint, pad


def _cell(*fps, width=80.0, height=80.0):
    named = [dataclasses.replace(fp, cell="m") for fp in fps]
    g = board_geometry(named, cells=["m"], width=width, height=height)
    return g, g.cells["m"]


def _with_pad(fp, number, net, dx, dy):
    """`fp` with one more pad, `dx`/`dy` off its centre."""
    cx, cy = fp.location.x, fp.location.y
    return dataclasses.replace(fp, pads=fp.pads + (pad(fp.ref, fp.inst, number, net, cx + dx, cy + dy),))


def test_two_independent_pairs_joined_only_by_a_plane_and_a_board_level_net_is_a_split_finding():
    # U1-R1 share L1; U2-R2 share L2; all four also carry GND (a plane,
    # excluded whatever its pads) and BUS - genuinely a board-level net
    # here, since J1, outside the cell, carries it too: neither GND nor
    # BUS is local, so it is exactly the two pairs.
    u1 = _with_pad(footprint("U1", 10, 10, nets=("L1", "GND")), 3, "BUS", 0.0, -0.5)
    r1 = _with_pad(footprint("R1", 10, 20, nets=("L1", "GND")), 3, "BUS", 0.0, -0.5)
    u2 = _with_pad(footprint("U2", 30, 10, nets=("L2", "GND")), 3, "BUS", 0.0, -0.5)
    r2 = _with_pad(footprint("R2", 30, 20, nets=("L2", "GND")), 3, "BUS", 0.0, -0.5)
    j1 = footprint("J1", 60, 10, nets=("BUS", "X"), cell=None)    # outside the cell
    named = [dataclasses.replace(fp, cell="m") for fp in (u1, r1, u2, r2)] + [j1]
    g = board_geometry(named, cells=["m"], width=90.0, height=90.0)
    text = splits.cell_text(g, g.cells["m"], plane_nets={"GND"}, min_group=2)
    assert text == (
        "its parts form 2 groups joined only by board-level nets: U1, R1; U2, R2. "
        "Parts with no close placement requirement in common may be split into modules of their own.")


def test_one_group_and_two_unjoined_parts_is_not_reported():
    # U1-R1 share L1 (one group); C1 and C2 carry only GND, on both pads -
    # a plane net, so C1 and C2 have no local net at all: unjoined.
    u1 = footprint("U1", 10, 10, nets=("L1", "GND"))
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    c1 = footprint("C1", 30, 10, nets=("GND", "GND"))
    c2 = footprint("C2", 30, 20, nets=("GND", "GND"))
    g, cell = _cell(u1, r1, c1, c2)
    assert splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2) is None


def test_a_plane_net_shared_by_every_member_joins_nothing():
    # Every pad on the board is GND, declared a plane: no local net at
    # all, so there is nothing to group.
    u1 = footprint("U1", 10, 10, nets=("GND", "GND"))
    r1 = footprint("R1", 30, 10, nets=("GND", "GND"))
    g, cell = _cell(u1, r1)
    assert splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2) is None


def test_a_net_with_a_pad_outside_the_cell_joins_nothing():
    # U1 and R1 both carry L1, but so does an outside part: L1 is not
    # local, so U1 and R1 do not group on it.
    u1 = footprint("U1", 10, 10, nets=("L1", "X"))
    r1 = footprint("R1", 30, 10, nets=("L1", "Y"))
    outside = footprint("J1", 60, 60, nets=("L1", "Z"), cell=None)
    named = [dataclasses.replace(u1, cell="m"), dataclasses.replace(r1, cell="m"), outside]
    g = board_geometry(named, cells=["m"], width=80.0, height=80.0)
    assert splits.cell_text(g, g.cells["m"], plane_nets=set(), min_group=2) is None


def test_split_min_group_three_drops_a_finding_whose_groups_are_pairs():
    u1 = footprint("U1", 10, 10, nets=("L1", "GND"))
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    u2 = footprint("U2", 30, 10, nets=("L2", "GND"))
    r2 = footprint("R2", 30, 20, nets=("L2", "GND"))
    g, cell = _cell(u1, r1, u2, r2)
    assert splits.cell_text(g, cell, plane_nets={"GND"}, min_group=3) is None


def test_the_message_names_groups_in_cell_order_and_the_unjoined_parts():
    # Three groups (3, 2, 2 members): L1 joins U3/C7/R2, L2 joins U5/R4, L3
    # joins Q2/R9. C1, C2, C3, R1 carry only GND, on both pads, like a
    # bypass capacitor tied straight across the plane: no local net, so
    # unjoined. Matches the spec's own example text (section 2).
    u3 = footprint("U3", 10, 10, nets=("L1", "GND"))
    c7 = footprint("C7", 10, 20, nets=("L1", "GND"))
    r2 = footprint("R2", 10, 30, nets=("L1", "GND"))
    u5 = footprint("U5", 30, 10, nets=("L2", "GND"))
    r4 = footprint("R4", 30, 20, nets=("L2", "GND"))
    q2 = footprint("Q2", 50, 10, nets=("L3", "GND"))
    r9 = footprint("R9", 50, 20, nets=("L3", "GND"))
    c1 = footprint("C1", 70, 10, nets=("GND", "GND"))
    c2 = footprint("C2", 70, 20, nets=("GND", "GND"))
    c3 = footprint("C3", 70, 30, nets=("GND", "GND"))
    r1 = footprint("R1", 70, 40, nets=("GND", "GND"))
    g, cell = _cell(u3, c7, r2, u5, r4, q2, r9, c1, c2, c3, r1, width=100.0, height=100.0)
    text = splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2)
    assert text == (
        "its parts form 3 groups joined only by board-level nets: U3, C7, R2; U5, R4; Q2, R9 "
        "(and 4 parts no net inside the cell joins to the others: C1, C2, C3, R1, "
        "each placed by the pin it serves or the part it senses, not a split candidate). "
        "Parts with no close placement requirement in common may be split into modules of their own.")


def test_an_unconnected_pad_does_not_join_two_real_groups_via_an_empty_net():
    # U1 and U2 each carry a third, unconnected pad (net ""). If "" were
    # wrongly counted as a real, shared net, U1 and U2 would be joined
    # through it into one group of four, and this would report no finding
    # at all - so this pins that "" is filtered, not just that nothing
    # crashes.
    u1 = _with_pad(footprint("U1", 10, 10, nets=("L1", "GND")), 3, "", 0.0, -0.5)
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    u2 = _with_pad(footprint("U2", 30, 10, nets=("L2", "GND")), 3, "", 0.0, -0.5)
    r2 = footprint("R2", 30, 20, nets=("L2", "GND"))
    g, cell = _cell(u1, r1, u2, r2)
    text = splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2)
    assert text == (
        "its parts form 2 groups joined only by board-level nets: U1, R1; U2, R2. "
        "Parts with no close placement requirement in common may be split into modules of their own.")


def test_a_member_whose_only_local_net_touches_nobody_else_is_listed_with_the_unjoined_parts():
    # U1-R1 share L1 (group 1); U2-R2 share L2 (group 2): a real finding.
    # Q1's own net Q_ONLY has no other pad anywhere on the board, so it IS
    # local to the cell (every pad of Q_ONLY - there is one - sits on the
    # cell), but joins nobody: a group of one, always below the floor of
    # 2, so it is listed with the parts no local net joins to another, not
    # as a third group.
    u1 = footprint("U1", 10, 10, nets=("L1", "GND"))
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    u2 = footprint("U2", 30, 10, nets=("L2", "GND"))
    r2 = footprint("R2", 30, 20, nets=("L2", "GND"))
    q1 = footprint("Q1", 50, 10, nets=("Q_ONLY", "GND"))
    g, cell = _cell(u1, r1, u2, r2, q1)
    text = splits.cell_text(g, cell, plane_nets={"GND"}, min_group=2)
    assert text == (
        "its parts form 2 groups joined only by board-level nets: U1, R1; U2, R2 "
        "(and 1 part no net inside the cell joins to the others: Q1, "
        "each placed by the pin it serves or the part it senses, not a split candidate). "
        "Parts with no close placement requirement in common may be split into modules of their own.")


def test_report_lists_only_the_cells_that_are_findings():
    u1 = footprint("U1", 10, 10, nets=("L1", "GND"))
    r1 = footprint("R1", 10, 20, nets=("L1", "GND"))
    u2 = footprint("U2", 30, 10, nets=("L2", "GND"))
    r2 = footprint("R2", 30, 20, nets=("L2", "GND"))
    g, split_cell = _cell(u1, r1, u2, r2)
    plain = footprint("U1", 10, 10, nets=("A", "B"))    # a second, unrelated cell with one group only
    g2 = board_geometry([dataclasses.replace(plain, cell="k")], cells=["k"], width=40.0, height=40.0)
    out = splits.report(g, [split_cell], plane_nets={"GND"}, min_group=2)
    assert [name for name, _ in out] == ["m"]
    assert splits.report(g2, [g2.cells["k"]], plane_nets=set(), min_group=2) == []
```

- [ ] **Step 2: Run them, confirm they fail for the right reason**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_splits.py
```

Expected: FAIL - `ModuleNotFoundError: No module named 'placemat.splits'`
(or `ImportError`).

- [ ] **Step 3: Write `splits.py`**

Create `src/placemat/splits.py`:

```python
"""A cell of several jobs (docs/superpowers/specs/2026-09-30-split-modules-
for-placement-design.md, section 2).

A cell is placed as one rigid piece, so a module that holds two or more
jobs joined only through board-level nets carries every job to wherever its
tightest one lands. This finds those cells from the generated board's
geometry, once a run has it, and reports it back: the capture decides a
module's parts from what must sit close together; the layout can only say
that a cell, as captured, does not hold one job.

A net is local to a cell when every pad the whole board has on it sits on
the cell's own members; a `board.plane()` net is never local, whatever its
pads. Two members are in one group when a local net joins them, directly or
through other members. A member no local net joins to another is
unjoined: it is placed by the pin it serves or the part it senses, not by
a group, and takes no part in any group. A bypass capacitor between a
board-level supply and a plane is unjoined this way even though it
already sits at the pin it serves; it is never a split candidate, whatever
the grouping shows."""
from __future__ import annotations

from .board_geometry import BoardGeometry, CellGeom


def _board_net_counts(geometry: BoardGeometry) -> dict:
    counts: dict = {}
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.net:
                counts[p.net] = counts.get(p.net, 0) + 1
    return counts


def _local_nets(cell: CellGeom, board_counts: dict, plane_nets) -> set:
    """The nets on this cell's members whose every board-wide pad is on one
    of them, less any net the board declares a plane for."""
    cell_counts: dict = {}
    for fp in cell.members:
        for p in fp.pads:
            if p.net:
                cell_counts[p.net] = cell_counts.get(p.net, 0) + 1
    return {net for net, n in cell_counts.items() if net not in plane_nets and n == board_counts.get(net, 0)}


def _groups(cell: CellGeom, local_nets: set) -> list:
    """The cell's members that carry a local net, grouped by it - directly
    or through other members - in the order the first member of each group
    appears among `cell.members`. A member no local net joins to another is
    left out (unjoined)."""
    parent = {fp.ref: fp.ref for fp in cell.members}

    def find(ref):
        while parent[ref] != ref:
            parent[ref] = parent[parent[ref]]
            ref = parent[ref]
        return ref

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_net: dict = {}
    for fp in cell.members:
        for net in sorted({p.net for p in fp.pads if p.net in local_nets}):
            by_net.setdefault(net, []).append(fp.ref)
    joined = {ref for refs in by_net.values() for ref in refs}
    for refs in by_net.values():
        for a, b in zip(refs, refs[1:]):
            union(a, b)
    groups: dict = {}
    for fp in cell.members:
        if fp.ref in joined:
            groups.setdefault(find(fp.ref), []).append(fp)
    return list(groups.values())


def cell_text(geometry: BoardGeometry, cell: CellGeom, plane_nets, min_group: int,
              board_counts: dict | None = None) -> str | None:
    """The `split` finding's text for `cell`, or None when it is not one:
    two or more groups of `min_group` members or more, joined only by nets
    that are not local to the cell."""
    board_counts = _board_net_counts(geometry) if board_counts is None else board_counts
    groups = _groups(cell, _local_nets(cell, board_counts, plane_nets))
    counted = [g for g in groups if len(g) >= min_group]
    if len(counted) < 2:
        return None
    counted_refs = {fp.ref for g in counted for fp in g}
    unjoined = [fp for fp in cell.members if fp.ref not in counted_refs]
    tail = ""
    if unjoined:
        tail = (" (and %d part%s no net inside the cell joins to the others: %s, each placed by the pin it "
                "serves or the part it senses, not a split candidate)" % (
                    len(unjoined), "" if len(unjoined) == 1 else "s", ", ".join(fp.ref for fp in unjoined)))
    return ("its parts form %d groups joined only by board-level nets: %s%s. Parts with no close placement "
            "requirement in common may be split into modules of their own." % (
                len(counted), "; ".join(", ".join(fp.ref for fp in g) for g in counted), tail))


def report(geometry: BoardGeometry, cells, plane_nets, min_group: int) -> list:
    """(cell name, text) for each cell in `cells` that is a `split`
    finding."""
    board_counts = _board_net_counts(geometry)
    out = []
    for cell in cells:
        text = cell_text(geometry, cell, plane_nets, min_group, board_counts)
        if text is not None:
            out.append((cell.name, text))
    return out
```

- [ ] **Step 4: Run the tests again, confirm they pass**

Same command as Step 2. Expected: PASS, all of them.

- [ ] **Step 5: Commit**

```bash
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la add src/placemat/splits.py tests/test_splits.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "splits.py: group a cell's members by the nets local to it"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 4: Wire the finding into a run, and confirm it carries no score weight

**Files:**
- Modify: `src/placemat/layout.py` (a new `_report_splits` method; one new
  call in `resolve()` at line 4149, after `self._report_undeclared(plan)`)
- Modify: `tests/test_splits.py` (append integration tests)
- Modify: `tests/test_run_score.py` (append a score-weight test)

**Interfaces:**
- Consumes: `splits.report` (Task 3); `Board._planes_declared: list[tuple[str,
  tuple]]` (existing, `layout.py`); `Board.settings.place_split_min_group`
  (Task 2); `Board.geometry` (existing); `plan._items: dict[str,
  CellGeom | Footprint]` (existing); `plan.steps: list[Step]` (existing,
  `Step.item` is the same key as `plan._items`, `Step.note: str`,
  existing); `findings.Finding` (existing).
- Produces: after `Board.resolve()`, `plan.findings` holds a
  `Finding("split", "<cell.name>: <text>")` per finding cell, and that
  cell's `Step.note` ends with `"split: <text>"`.

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/test_splits.py`:

```python
def test_board_resolve_reports_a_split_finding_and_notes_the_cells_step():
    """Without the plane() declaration, GND's pads all sit on this cell (the
    only cell on this small board) and would wrongly count as local,
    joining every member into one group - board.plane() is what keeps a
    board-level net from ever counting as local, whatever its pads."""
    from placemat.layout import Board
    from placemat.values import CopperLayer, Location, Net, Cell

    u1 = footprint("U1", 0.0, 0.0, w=2.0, h=1.0, nets=("L1", "GND"))
    r1 = footprint("R1", 0.0, 3.0, w=2.0, h=1.0, nets=("L1", "GND"))
    u2 = footprint("U2", 5.0, 0.0, w=2.0, h=1.0, nets=("L2", "GND"))
    r2 = footprint("R2", 5.0, 3.0, w=2.0, h=1.0, nets=("L2", "GND"))
    named = [dataclasses.replace(fp, cell="m") for fp in (u1, r1, u2, r2)]
    g = board_geometry(named, cells=["m"], width=60.0, height=60.0)
    b = Board(g, edge_margin=1.0)
    b.plane(Net("GND"), [CopperLayer.F])
    b.place(Cell("m"), at=Location(30, 30))
    plan = b.resolve()
    found = [f for f in plan.findings if f.kind == "split"]
    assert len(found) == 1
    assert found[0] == ("m: its parts form 2 groups joined only by board-level nets: U1, R1; U2, R2. "
                        "Parts with no close placement requirement in common may be split into modules "
                        "of their own.")
    step = next(s for s in plan.steps if s.item == "m")
    assert "split: its parts form 2 groups" in step.note


def test_board_resolve_reports_no_split_finding_for_one_group():
    from placemat.layout import Board
    from placemat.values import Location, Cell

    u1 = footprint("U1", 0.0, 0.0, w=2.0, h=1.0, nets=("L1", "L2"))
    r1 = footprint("R1", 0.0, 3.0, w=2.0, h=1.0, nets=("L1", "L2"))
    named = [dataclasses.replace(fp, cell="m") for fp in (u1, r1)]
    g = board_geometry(named, cells=["m"], width=60.0, height=60.0)
    b = Board(g, edge_margin=1.0)
    b.place(Cell("m"), at=Location(30, 30))
    plan = b.resolve()
    assert [f for f in plan.findings if f.kind == "split"] == []
```

Append to `tests/test_run_score.py`:

```python
def test_the_split_finding_carries_no_run_score_weight():
    """Like vias, a split finding is not one of score.py's weighted finding
    kinds: it never appears as a term, whatever the weights are."""
    heavier = dataclasses.replace(CFG, score_setup=1000.0, score_label=1000.0)
    plain = score.terms(M(findings={}), heavier)
    with_split = score.terms(M(findings={"split": 5}), heavier)
    assert plain == with_split
```

- [ ] **Step 2: Run them, confirm they fail for the right reason**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_splits.py tests/test_run_score.py
```

Expected: the two new `test_splits.py` integration tests FAIL (no `split`
finding is produced yet: `len(found) == 1` fails with `0`, or the
second's `== []` already passes trivially - check it reads correctly
against the first failing). `test_the_split_finding_carries_no_run_score_weight`
already PASSES (nothing in `score.py` weighs `"split"` yet, by
construction) - that is expected; it is a regression pin, not a red/green
step for new code.

- [ ] **Step 3: Add `_report_splits` and wire it in**

In `src/placemat/layout.py`, add a new method near `_report_undeclared`
(directly after it, before `_report_escapes`, keeping the existing
`_report_*` methods together):

```python
    def _report_splits(self, plan: Plan) -> None:
        """A cell whose members form two or more groups of
        `place.split_min_group` members or more, joined only by nets not
        local to the cell (splits.py): a finding, and a note on the cell's
        step."""
        from . import splits
        cells = [it for it in plan._items.values() if isinstance(it, CellGeom)]
        plane_nets = {net for net, _ in self._planes_declared}
        for name, text in splits.report(self.geometry, cells, plane_nets, self.settings.place_split_min_group):
            plan.findings.append(Finding("split", "%s: %s" % (name, text)))
            step = next((s for s in plan.steps if s.item == name), None)
            if step is not None:
                step.note = (step.note + "; " if step.note else "") + "split: " + text
```

At line 4149 (`self._report_undeclared(plan)`), add the call right after
it:

```python
        self._report_undeclared(plan)
        self._report_splits(plan)
```

- [ ] **Step 4: Run the same tests again, confirm they pass**

Same command as Step 2. Expected: PASS, all of them.

- [ ] **Step 5: Run the wider finding-kinds and settings-wiring files once more**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_finding_kinds.py tests/test_settings.py tests/test_settings_wiring.py tests/test_splits.py tests/test_run_score.py
```

Expected: PASS throughout.

- [ ] **Step 6: Commit**

```bash
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la add src/placemat/layout.py tests/test_splits.py tests/test_run_score.py
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "A run reports a cell of several jobs as a split finding"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 5: Skill and reference text

**Files:**
- Modify: `skills/placemat/SKILL.md` (a new bullet in "A fresh board" step
  3's list, at line 171)
- Modify: `skills/placemat/references/capture.md` (a new section, appended
  at the end of the file)
- Modify: `skills/placemat/references/api.md` (a new paragraph in the
  `## Placement` section, after line 210)
- Modify: `skills/placemat/references/migration.md` (a new paragraph under
  the existing `## Unreleased` heading, before `## To 0.57.2` at line 64)

No new automated test exercises prose; Step 4 below re-runs the doc-coverage
test that Task 2 already made pass, as a regression check that this task's
edits did not disturb it.

- [ ] **Step 1: SKILL.md**

In `skills/placemat/SKILL.md`, the step-3 list currently ends (line
169-171):

```
   - mechanical facts: mounting patterns, case windows, a sensor whose
     position is its function.
```

Change the trailing period to a semicolon and add a new bullet after it:

```
   - mechanical facts: mounting patterns, case windows, a sensor whose
     position is its function;
   - a cell is placed as one rigid piece; when its parts want different
     places, the capture's module boundary is wrong for this board - a
     job joined to the rest only through board-level nets, or a cell too
     large or the wrong shape for the room its tightest part needs. Say
     so, and propose the split, or the move of parts between modules, as
     a change to the capture; do not work round it in the script. The
     `split` finding lists cells whose parts form separate groups; a
     refused cell is the other signal.
```

- [ ] **Step 2: capture.md**

Append to the end of `skills/placemat/references/capture.md` (after its
last line, "3. After `pcb build -D warnings` passes, `placemat check` on
the generated board reads the annotations and the classes."):

```markdown

## Modules for placement

A cell is placed by placemat as one rigid piece: every member goes
together, wherever the cell's tightest job needs to sit. A cell that
holds two or more jobs joined only through board-level nets - a shared
bus, status lines, pull-ups, a plane - carries every other job's part to
wherever the tightest one goes.

`placemat run` reports this back as a `split` finding, naming the groups
it found among a cell's parts:

    m: its parts form 3 groups joined only by board-level nets: U3, C7,
    R2; U5, R4; Q2, R9 (and 4 parts no net inside the cell joins to the
    others: C1, C2, C3, R1, each placed by the pin it serves or the part
    it senses, not a split candidate). Parts with no close placement
    requirement in common may be split into modules of their own.

A cell the search refuses to place at all is the other signal that its
module does not fit the board.

Fix a `split` finding, or a refused cell, in the capture: split the
module, or move a part into another one. A layout script cannot fix a
module the capture drew wrong; it only places what the capture gives it.

A part the finding does not group carries no net local to its cell. A
bypass capacitor is one: it always belongs in the module of the IC it
serves, and a bypass capacitor between a board-level supply and a plane
has no net inside its own cell, so the grouping shows it apart from that
IC - it is never a split candidate, whatever the grouping shows. A part
placed by what it senses or shields is the same: a thermistor sits at the
part whose temperature it measures, even though all its nets run
elsewhere. Neither is a split candidate; each is placed by that physical
need, not by a group.
```

- [ ] **Step 3: api.md**

In `skills/placemat/references/api.md`, `## Placement` section, after
line 210 ("...`j_out (edge): J5 courtyard overlaps cell a1's R2
courtyard`.") and before the "**Degrees of freedom.**" paragraph, insert:

```markdown

**A cell of several jobs.** At each run, placemat groups a cell's members
by the nets local to it: a net every one of whose pads, board-wide, sits
on this cell's own members; a `board.plane()` net is never local,
whatever its pads. Two members are in one group when a local net joins
them, directly or through others; `place.split_min_group` (2) is the
least members a group needs to count. A cell with two or more such groups
is a finding of kind `split`, naming each group and the parts no net
inside the cell joins to another: "m: its parts form 3 groups joined only
by board-level nets: U3, C7, R2; U5, R4; Q2, R9 (and 4 parts no net
inside the cell joins to the others: C1, C2, C3, R1, each placed by the
pin it serves or the part it senses, not a split candidate). Parts with
no close placement requirement in common may be split into modules of
their own." It carries no run-score weight (score.py), and the same text
is a note on the cell's step.
```

- [ ] **Step 4: migration.md**

In `skills/placemat/references/migration.md`, under the existing `##
Unreleased` heading, after its last paragraph (ending "...says so on its
own line and records a finding, but still runs.", line 62) and before
`## To 0.57.2` (line 64), insert:

```markdown

**A cell of several jobs.** `placemat run` now reports a `split` finding
for a cell whose members form two or more groups
(`place.split_min_group`, default 2) joined only by nets that are not
local to it - a board-level net, or any `board.plane()` net whatever its
pads - and names the parts no net inside the cell joins to another (each
already placed by the pin it serves or the part it senses, never a split
candidate). It carries no run-score weight.
```

- [ ] **Step 5: Run the doc-coverage regression check**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_settings_wiring.py tests/test_finding_kinds.py tests/test_fragment_layers.py tests/test_route_keepouts.py tests/test_queries.py tests/test_best_run.py tests/test_checks_wiring.py tests/test_describe.py tests/test_faces.py tests/test_solve_wiring.py
```

Expected: PASS throughout (these are the files that read
`migration.md`/`api.md` text for other, older sections; confirms this
task's edits did not break any of them).

- [ ] **Step 6: Commit**

```bash
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la add skills/placemat/SKILL.md skills/placemat/references/capture.md skills/placemat/references/api.md skills/placemat/references/migration.md
git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit -m "Skill and docs: modules for placement, and the split finding"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 6: Bench and wrap-up

**Files:** none modified unless `fixtures/bench.json` changes.

- [ ] **Step 1: Run the full set of targeted test files from this plan once more**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_finding_kinds.py tests/test_settings.py tests/test_settings_wiring.py tests/test_splits.py tests/test_run_score.py
```

Expected: PASS throughout.

- [ ] **Step 2: Bench**

```
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2
```

Expected: "same 32" on every config (`default`, `solve`, `physical`) -
the finding carries no run-score weight, so no placement or score can
move. If `fixtures/bench.json` changed anyway, treat that as a bug in
this plan (something moved a placement or a score) rather than update the
baseline; stop and report it instead of committing.

- [ ] **Step 3: Report the tally**

Note the exact tally line(s) `bench.py` printed, for the final report
back to the coordinator. No commit is needed here unless
`fixtures/bench.json` genuinely changed (it should not).
