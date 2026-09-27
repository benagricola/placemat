# Freeze Intent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `placemat freeze` writes a lock entry into the script in the lock's own frame (an offset and a rotation relative to the anchor part) with a `why=` naming the explore run and score.

**Architecture:** Two new script values: `PadRef.local(dx, dy)` (an offset in the pad's part's frame) and `Turned(Part, degrees)` (a rotation relative to a part, settled when the item is placed, after that part). The lock records the explore run id and score at `--accept`; freeze writes `Near(PadRef(...).local(dx, dy), radius=0)`, `rotation=Turned(...)` and the `why=`.

**Tech Stack:** Python 3.12, pytest; the freeze tests use pcbnew and a short explore (existing `tests/test_freeze.py` pattern).

**Spec:** `docs/superpowers/specs/2026-09-27-freeze-intent-design.md` (approved 2026-09-27)

## Global Constraints

- `PadRef.offset` keeps its meaning (board directions); `local` is new.
- The part frame is the lock's: `lock._turn(dx, dy, rotation)` maps a local vector to the board; on the back face the part's own pads are mirrored, and a local vector is mirrored the same way (its x negated before the turn).
- `Turned` names a `Part`; the item waits for that part to be placed (it joins the item's needs).
- `--fixed` output is unchanged.
- Generic wording in src, skill and migrations; plain ASCII; commits carry no tool or session reference.
- Every placement change runs `fixtures/bench.py`; the tally goes in the commit message.

## Review Focus

1. A local offset on a part on the back face: the point is where the part's own mirrored frame puts it (a pad's neighbour in footprint terms is still its neighbour). Test in Task 1.
2. `Turned` naming a part that is searched later in the order: the item waits for it, whatever the tiers. Test in Task 2.
3. A lock written before this change (no run, no score): read, held, and frozen with the short `why`. Test in Task 3.
4. Freezing an item whose call already has `why=`: the new text is appended, the old kept. Test in Task 4.
5. The frozen script re-resolves to the locked placements, and after the anchor is turned 90 degrees in the script the frozen item turns with it exactly as the locked one does. Test in Task 4.

---

### Task 1: `PadRef.local`

**Files:**
- Modify: `src/placemat/values.py` (`PadRef`: `lx`, `ly` fields and `local()`)
- Modify: `src/placemat/layout.py` (`_locate`'s pad branch)
- Test: `tests/test_pad_local.py` (create)

**Interfaces:**
- Produces: `PadRef.local(dx: float = 0.0, dy: float = 0.0) -> PadRef`; `PadRef.lx`, `PadRef.ly` (default 0.0); `_locate` resolves them.

- [ ] **Step 1: Write the failing tests** (`tests/test_pad_local.py`)

```python
"""An offset from a pad in its part's own frame: it turns, and on the back
mirrors, with the part. Pure: synthetic boards."""
import pytest

from placemat.layout import Board, _locate
from placemat.values import Face, Location, Near, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _where(rotation, face=Face.FRONT):
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 20), rotation=rotation, face=face)
    b.place(Part("r1"), at=Location(30, 30))
    plan = b.resolve()
    occ = plan.occupancy
    pad1, pad2 = occ.pad_location("U1", "1"), occ.pad_location("U1", "2")
    point = _locate(b, occ, PadRef(Part("u1"), 1).local(2.8, 0.0))   # pad 1 to pad 2 is +2.8 in the footprint
    return point, pad2


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_local_offset_turns_with_its_part(rotation):
    point, pad2 = _where(rotation)
    assert point.distance(pad2) < 1e-6


@pytest.mark.parametrize("rotation", [0, 90])
def test_a_local_offset_mirrors_with_a_part_on_the_back(rotation):
    point, pad2 = _where(rotation, Face.BACK)
    assert point.distance(pad2) < 1e-6


def test_local_and_offset_add():
    ref = PadRef(Part("u1"), 1).offset(1.0, 0.0).local(0.0, 2.0)
    assert (ref.dx, ref.dy, ref.lx, ref.ly) == (1.0, 0.0, 0.0, 2.0)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q tests/test_pad_local.py`
Expected: FAIL, `AttributeError: 'PadRef' object has no attribute 'local'`.

- [ ] **Step 3: Implement** (`src/placemat/values.py`, class `PadRef`)

```python
    part: Part
    key: object = None
    dx: float = 0.0
    dy: float = 0.0
    pin: str | None = None
    lx: float = 0.0            # an offset in the part's own frame: turned, and on the back mirrored, with it
    ly: float = 0.0
```

and replace `offset`, adding `local`:

```python
    def offset(self, dx: float = 0.0, dy: float = 0.0) -> "PadRef":
        """The point moved in board directions."""
        return PadRef(self.part, self.key, self.dx + dx, self.dy + dy, None, self.lx, self.ly)

    def local(self, dx: float = 0.0, dy: float = 0.0) -> "PadRef":
        """The point moved in the part's own frame, as its footprint is
        drawn: the move turns with the part, and on the back mirrors."""
        return PadRef(self.part, self.key, self.dx, self.dy, None, self.lx + dx, self.ly + dy)
```

(The positional `None` is `pin`: `__post_init__` has already turned a `pin=` into `key`.)

In `src/placemat/layout.py`, `_locate`'s last two lines become:

```python
    owner, number, dx, dy = board._pad_ref(ref)
    at = occ.pad_location(owner, number).offset(dx, dy)
    lx, ly = getattr(ref, "lx", 0.0), getattr(ref, "ly", 0.0)
    if lx or ly:
        from .lock import _turn
        g = occ.items[owner].reference
        vx, vy = _turn(-lx if g.face is Face.BACK else lx, ly, g.rotation)
        at = at.offset(vx, vy)
    return at
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_pad_local.py tests/test_values.py`
Expected: PASS. If the back-face cases fail, the mirror is on the other axis: print `pad1`, `pad2` for `Face.BACK` at rotation 0 and match the footprint's own flip (the spec's rule: mirrored as the part's own pads are); record the change as a ruling.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/values.py src/placemat/layout.py tests/test_pad_local.py
git commit -m "PadRef.local: an offset in the part's own frame"
```

### Task 2: `Turned`

**Files:**
- Modify: `src/placemat/values.py` (new `Turned`), `src/placemat/__init__.py` (export)
- Modify: `src/placemat/layout.py` (`PlaceIntent.turned`, `Board.place`, the place-time hook near the `obj.rotation is None` run branch, about line 2446)
- Test: `tests/test_turned.py` (create)

**Interfaces:**
- Produces: `Turned(part: Part, degrees: float = 0.0)`; `PlaceIntent.turned: Turned | None = None`.

- [ ] **Step 1: Write the failing tests** (`tests/test_turned.py`)

```python
"""A rotation relative to a part: settled when the item is placed, after
that part. Pure: synthetic boards."""
from placemat import Turned
from placemat.layout import Board
from placemat.values import Location, Near, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("C1", 30, 30, w=2, h=1, inst="c1", nets=("A", "GND")),
           footprint("J1", 5, 5, w=2, h=2, inst="j1", nets=("B", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("j1"), at=Location(5, 5))
    return b


def test_a_turned_rotation_follows_its_part():
    for turn in (0, 90, 270):
        b = _board()
        b.place(Part("u1"), at=Location(20, 20), rotation=turn)
        b.place(Part("c1"), at=Near(PadRef(Part("u1"), 1).local(0.0, -2.5), radius=0),
                rotation=Turned(Part("u1"), 90))
        plan = b.resolve()
        assert plan.placement("c1").rotation == (turn + 90) % 360


def test_an_item_turned_by_a_searched_part_waits_for_it():
    b = _board()
    b.place(Part("c1"), at=Near(PadRef(Part("u1"), 1).local(0.0, -2.5), radius=0),
            rotation=Turned(Part("u1"), 0), priority=Priority.HIGH)
    b.place(Part("u1"), rotations=(90,))
    plan = b.resolve()
    order = [s.item for s in plan.steps]
    assert order.index("u1") < order.index("c1")
    assert plan.placement("c1").rotation == 90
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q tests/test_turned.py`
Expected: FAIL, `ImportError: cannot import name 'Turned'`.

- [ ] **Step 3: Implement**

`src/placemat/values.py`, after `PadRef`:

```python
@dataclass(frozen=True)
class Turned:
    """A rotation relative to a part: its placed rotation plus `degrees`,
    settled when the item is placed, which waits for that part."""
    part: Part
    degrees: float = 0.0
```

Export it in `src/placemat/__init__.py` (the `from .values import (...)` line and `__all__`).

`src/placemat/layout.py`:
- import `Turned` with the other values;
- `PlaceIntent` gains, after `rotation_given`: `turned: object = None           # a Turned: the rotation is its part's plus its degrees, settled at placement`;
- in `Board.place`, before `rotation_given = rotation is not None`:

```python
        turned = rotation if isinstance(rotation, Turned) else None
        if turned is not None:
            rotation = float(turned.degrees)        # provisional: the ranking measures by it until the part is down
```

- after the `needs = {...}` line: `if turned is not None: needs.add(self._pad_ref(turned.part)[0])`;
- pass `turned=turned` to the `PlaceIntent(...)` call as a keyword;
- in `place_one`, just before `if isinstance(obj.run, CutoutEdge):` (about line 2442):

```python
            if getattr(obj, "turned", None) is not None:    # its part is placed by now: needs said so
                ref = self._pad_ref(obj.turned.part)[0]
                obj.rotation = (occ.items[ref].reference.rotation + obj.turned.degrees) % 360.0
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_turned.py tests/test_pad_local.py tests/test_searched_needs.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/values.py src/placemat/__init__.py src/placemat/layout.py tests/test_turned.py
git commit -m "Turned: a rotation relative to a part, settled after it is placed"
```

### Task 3: The lock records the explore run and its score

**Files:**
- Modify: `src/placemat/lock.py` (`LockEntry.run`, `LockEntry.score`, `read`, `entries`)
- Modify: `src/placemat/explore.py` (`search`, `before_resolve`: a `run_id` argument)
- Modify: `src/placemat/runner.py` (pass `rid`), `src/placemat/previewer.py` (pass `""`)
- Test: `tests/test_lock.py` (append)

**Interfaces:**
- Produces: `LockEntry.run: str = ""`, `LockEntry.score: float | None = None`; `lock.entries(board, plan, keys, release="", run="", score=None)`; `explore.before_resolve(script, board, make_board, options, say, run_id="")`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_lock.py`)

```python
def test_an_entry_keeps_the_run_and_score_that_accepted_it(tmp_path):
    from placemat import lock
    e = lock.LockEntry("c1", ("U1", "1"), "front", (0.1, -2.5), 90.0, "front", "abc", 0, "0.40.0",
                       run="1a2b3c4d", score=812.5)
    p = tmp_path / "x.lock.json"
    lock.write(p, [e])
    (back,) = lock.read(p)
    assert (back.run, back.score) == ("1a2b3c4d", 812.5)


def test_an_entry_from_before_has_no_run_or_score(tmp_path):
    import json
    from placemat import lock
    p = tmp_path / "x.lock.json"
    p.write_text(json.dumps({"format": 1, "entries": [{"key": "c1", "anchor": ["U1", "1"], "anchor_face": "front",
                 "offset": [0.1, -2.5], "rotation": 90.0, "face": "front", "declaration": "abc"}]}))
    (e,) = lock.read(p)
    assert (e.run, e.score) == ("", None)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q tests/test_lock.py -k "run_and_score or from_before"`
Expected: FAIL, `TypeError: LockEntry.__init__() got an unexpected keyword argument 'run'`.

- [ ] **Step 3: Implement**

`lock.py`: add to `LockEntry` after `release`:

```python
    run: str = ""                   # the run whose explore accepted it
    score: float | None = None      # that explore's best run score, mm
```

In `read`, pass `e.get("run", ""), e.get("score")` after `e.get("release", "")`. `entries(board, plan, keys, release: str = "", run: str = "", score: float | None = None)` builds each entry with `LockEntry(**{**asdict(e), "turn": len(out), "run": run, "score": score})`.

`explore.py`: `search(..., release="", run_id="")` calls `_lock.entries(board, best, placed, release, run_id, round(result.best, 1))`; `before_resolve(script, board, make_board, options, say, run_id="")` passes `run_id=run_id` to `search`.

`runner.py`: the `explore_mod.before_resolve(...)` call adds `run_id=rid`. `previewer.py`'s call is unchanged (default `""`).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_lock.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/lock.py src/placemat/explore.py src/placemat/runner.py tests/test_lock.py
git commit -m "The lock records the run and score that accepted each entry"
```

### Task 4: Freeze writes the lock's frame and why

**Files:**
- Modify: `src/placemat/freeze.py` (`frozen_args`, `freeze`)
- Test: `tests/test_freeze.py` (update and append), `tests/test_freeze_edit.py` (the `AT` constant if a test depends on the old form)

**Interfaces:**
- Consumes: `PadRef.local`, `Turned` (Tasks 1-2), `LockEntry.run`, `LockEntry.score` (Task 3).
- Produces: `frozen_args(board, key, turn, fixed, entry=None, why="") -> dict` with keys `at`, `rotation`, `why`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_freeze.py`; in the first test replace `assert "radius=0" in src and src != before_src` with the lines below)

```python
    assert ".local(" in src and "Turned(Part(" in src and src != before_src
    assert "explore " in src and "frozen " in src
```

```python
def test_a_frozen_item_turns_with_its_anchor_as_the_locked_one_does(tmp_path):
    mod, script = _accepted(tmp_path)
    rc, out = _cli("freeze", script, "--all")
    assert rc == 0, out
    import re
    src = script.read_text()
    anchor = re.search(r'\.local\([^)]*\), radius=0\), rotation=Turned\(Part\("([a-z0-9_]+)"\)', src).group(1)
    before = _placements(script)
    frozen = [k for k in before if k != anchor and k in src]
    turned = re.sub(r'(place\(Part\("%s"\)[^\n]*?)\)' % anchor, r'\1, rotation=90)', src, count=1)
    script.write_text(turned)
    after = _placements(script)
    a0, a1 = before[anchor].location, after[anchor].location
    for key in frozen:
        # the same distance from the anchor, a quarter turn further round
        assert abs(after[key].location.distance(a1) - before[key].location.distance(a0)) < 1e-6
        assert (after[key].rotation - before[key].rotation) % 360 == (after[anchor].rotation - before[anchor].rotation) % 360


def test_freezing_keeps_a_why_the_call_had(tmp_path):
    mod, script = _accepted(tmp_path)
    src = script.read_text()
    first = src.index("board.place(R_CC2")
    close = src.index(")", src.index("(", first + len("board.place(")))
    script.write_text(src[:close] + ', why="the pull-down sits by its pin"' + src[close:])
    rc, out = _cli("freeze", script, "--all")
    assert rc == 0, out
    assert re.search(r'why="the pull-down sits by its pin; explore ', script.read_text())
```

(Import `re` at the top of the file.) Read `tests/test_explore_cli.py::_module` first: if the anchor part in that module is fixed, the turn test applies `rotation=90` to it through its own `place()` call as written above; if the module declares it differently, adapt the regex to that call and note it in the ledger.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q tests/test_freeze.py tests/test_freeze_edit.py`
Expected: FAIL on the new asserts (`.local(` not in the script).

- [ ] **Step 3: Implement** (`src/placemat/freeze.py`)

`frozen_args` gains `entry=None, why: str = ""`; for an anchored item, not `--fixed`, with an entry:

```python
    if entry is not None and entry.anchor is not None and not fixed:
        dx, dy = entry.offset
        if entry.anchor_face == "back":
            dx = -dx                     # the lock's frame is turned only; local() mirrors a back part
        at = "Near(%s.local(%s, %s), radius=0)" % (pad, _n(dx), _n(dy))
        return {"at": at, "rotation": "Turned(Part(%r), %s)" % (fp.inst, _n(entry.rotation)), "why": why}
```

(`pad` and `fp` are computed as today, above this branch.) Every other return adds `"why": why`.

In `freeze`, for each entry build the why text from the intent's own:

```python
                stamp = "explore %s: %s mm, frozen %s" % (e.run, e.score, date) if e.run and e.score is not None \
                    else "explore: frozen %s" % date
                why = "%s; %s" % (i.why, stamp) if i.why else stamp
                edits.append((i.line, e.key, frozen_args(board, e.key, turn, fixed, entry=e, why=repr(why))))
```

with `date = time.strftime("%Y-%m-%d")` computed once. `ensure_imports` gains `"Turned"` in the non-fixed case.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_freeze.py tests/test_freeze_edit.py tests/test_lock.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/freeze.py tests/test_freeze.py tests/test_freeze_edit.py
git commit -m "Freeze writes the lock's frame, a relative rotation and where the spot came from"
```

### Task 5: Docs, bench and suite

**Files:**
- Modify: `skills/placemat/references/api.md` (the Freeze paragraph; the PadRef and rotation lines of the verb reference), `skills/placemat/SKILL.md` (the explore bullet), `skills/placemat/references/migration.md` (`## To 0.40`), `BACKLOG.md` (Freeze keeps intent: Open to Done)

- [ ] **Step 1: Docs**

api.md Freeze paragraph becomes:

```
**Freeze.** `placemat freeze <script> ITEM` (or `--all`) writes entries
into the script in the lock's own terms: the item's `place()` call gains
`at=Near(PadRef(<anchor>).local(dx, dy), radius=0)` - an offset in the
anchor part's own frame - and `rotation=Turned(Part(<anchor>), r)`, so it
turns with its anchor exactly as the lock held it, and a `why=` naming the
explore run and its score. `--fixed` writes a firm `Location(X(...), Y(...))`
instead, allowed when the anchor is fixed. Only that call's arguments change -
comments and every other line stay - and the script and lock are written only
when the edited script places every item exactly as the lock did; otherwise
freeze says what would have moved. A call inside a loop or a helper function
declares more than one item and is refused with its line.
```

Add to the verb reference near `PadRef`: `PadRef(part, n).local(dx, dy)   # an offset in the part's own frame: turns (and on the back mirrors) with it` and `rotation=Turned(Part("u1"), 90)   # the part's placed rotation plus 90; the item waits for it`.

migration.md:

```
## To 0.40

Nothing to change in a script. `placemat freeze` now writes an entry as
`Near(PadRef(...).local(dx, dy), radius=0)` with `rotation=Turned(Part(...),
r)`, in the anchor's own frame, and a `why=` naming the explore run and its
score; a frozen item turns with its anchor. Entries frozen by 0.39 or earlier
wrote `.offset(...)` in board directions and an absolute rotation: they stay
where they are while the anchor keeps its rotation.
```

BACKLOG.md: move "Freeze keeps intent" to Done as `(unreleased; spec 2026-09-27-freeze-intent-design.md)`.

- [ ] **Step 2: Bench and the full suite**

Run: `.venv/bin/python fixtures/bench.py` and `uv run pytest -q`
Expected: bench `same 32` on default, physical and solve; no FAILED lines other than the known intermittent `tests/test_runner_breakout.py::test_the_cli_runs_and_prints_a_one_line_verdict`.

- [ ] **Step 3: Commit**

```bash
git add skills/placemat/references/api.md skills/placemat/SKILL.md skills/placemat/references/migration.md BACKLOG.md
git commit -m "Freeze in the lock's frame: docs and the 0.40 migration note"
```
