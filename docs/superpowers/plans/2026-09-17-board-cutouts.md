# Board Cutouts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a script declare a hole by what it is and what it relates to, place a part against that hole's boundary, and refuse a hole that would leave too little material to hold the board together.

**Architecture:** A cutout becomes a shape (`Slot`, `Circle`, `Path` - no position) plus a place (`at=`), resolved as a firm intent in the existing `place_ranked` queue so `PlaceIntent.needs` orders it against the parts it refers to. Its boundary is reached only through `board.cutout(name)`, which walks the hole loop with the winding sign flipped so normals point into the hole - the form `run_placement` already consumes. `board.web` is the least material that may remain, checked as the shortest distance between boundaries.

**Tech Stack:** Python 3.11+, `uv run python -m pytest`, pcbnew (KiCad 10) for the write path, `uvx ruff` for lint.

**Spec:** `docs/superpowers/specs/2026-09-17-board-cutouts-design.md`

## Global Constraints

- Punctuation is plain ASCII throughout: no em dashes, en dashes, unicode arrows, curly quotes or ellipsis characters. Use `-` with spaces, and `->`.
- Docstrings and comments follow the codebase's voice: say what a thing does and why it is that way; no defensive over-explanation, no praising the design.
- Every error raised at a script's expense names what to use instead. An `AttributeError` or `TypeError` escaping from inside the placer is a defect, not an error message.
- `board.web` defaults to `0.0`, meaning unchecked. No existing board gains a check it did not ask for.
- The full suite must stay green after every task: `uv run python -m pytest -q`. Baseline at the start of this plan is 316 passed.
- New lint must stay clean: `uvx ruff check --select F401,F811,F821 src/placemat tests`.
- Commit after each task. Commit messages carry no reference to Claude, Anthropic, or any session URL.

## File Structure

| file | responsibility after this work |
|---|---|
| `src/placemat/cutouts.py` | closed-path geometry with no placemat imports: `Arc`, flattening, the bucket index, `Cutouts`, the shape values (`Slot`, `Circle`, `Path`), and the loop-to-loop distance the web is measured with |
| `src/placemat/outline.py` | `Outline`, `Run`, and reading runs off any loop of it |
| `src/placemat/values.py` | `Cutout` value; `Disc` (already carries `holes`) |
| `src/placemat/layout.py` | `CutoutIntent`, the `board.cutout(name)` handle, `web` on the declarations, the legality probe and the web finding |
| `src/placemat/occupancy.py` | the board shape as cutouts land; a cutout may not overlap a placed item's reach |
| `tests/test_cutouts.py` | everything about holes: shapes, runs, placement, the web, ordering |

---

### Task 1: Shapes that carry no position

A shape is a closed outline about its own box centre. The two positional helpers go, because they answer "what is this hole" and "where is this hole" at once, which is the defect this whole plan exists to remove.

**Files:**
- Modify: `src/placemat/cutouts.py` (replace `circle()` at :111 and `slot()` at :126)
- Modify: `src/placemat/__init__.py` (exports)
- Modify: `tests/test_cutouts.py`, `tests/test_write_copper.py` (call sites)
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: `Arc`, `point`, `flatten_path`, `Cutouts`, `NM` from `cutouts.py`
- Produces:
  - `Slot(length: float, width: float)` - frozen dataclass, `.path_at(centre, rotation=0.0) -> list`
  - `Circle(diameter: float)` - frozen dataclass, `.path_at(centre, rotation=0.0) -> list`
  - `Path(points: tuple)` - frozen dataclass, `.path_at(centre, rotation=0.0) -> list`
  - all three expose `.box_at(centre, rotation)` -> `(left, top, right, bottom)` tuple and `.area`
  - `slot()` and `circle()` module functions no longer exist

- [ ] **Step 1: Write the failing tests**

Replace the `# ---- paths` block at the top of `tests/test_cutouts.py` with these. Delete `test_a_slot_is_its_centre_line_swept_by_a_circle`, `test_a_slot_of_no_length_is_a_round_hole`, `test_a_circle_path_closes_on_itself` and `test_a_slot_needs_a_positive_width`; they test the removed functions.

```python
def test_a_slot_is_measured_tip_to_tip():
    """What callipers measure: a 13 mm slot is 13 mm end to end, not a
    13 mm centre line."""
    s = Slot(13.0, 3.0)
    assert s.area == pytest.approx(10.0 * 3.0 + math.pi * 1.5 ** 2, rel=0.005)
    path = s.path_at(Location(20.0, 20.0))
    xs = [p[0] for p in Cutouts([path]).loops[0]]
    assert max(xs) - min(xs) == pytest.approx(13.0, abs=0.02)


def test_a_slot_as_wide_as_it_is_long_is_a_circle():
    assert Cutouts([Slot(6.0, 6.0).path_at(Location(0.0, 0.0))]).area == \
        pytest.approx(math.pi * 9.0, rel=0.01)


def test_a_slot_narrower_than_it_is_wide_is_refused():
    with pytest.raises(ValueError, match="tip to tip"):
        Slot(2.0, 3.0)
    with pytest.raises(ValueError, match="positive"):
        Slot(10.0, 0.0)


def test_a_shape_is_placed_about_its_box_centre():
    for shape in (Slot(13.0, 3.0), Circle(8.0),
                  Path([(100.0, 100.0), (110.0, 100.0), (110.0, 104.0), (100.0, 104.0)])):
        loop = Cutouts([shape.path_at(Location(20.0, 30.0))]).loops[0]
        xs, ys = [p[0] for p in loop], [p[1] for p in loop]
        assert (min(xs) + max(xs)) / 2.0 == pytest.approx(20.0, abs=0.02)
        assert (min(ys) + max(ys)) / 2.0 == pytest.approx(30.0, abs=0.02)


def test_a_rotated_slot_runs_on_its_bearing():
    """rotation is a bearing: 90 turns the slot's length to run north-south."""
    loop = Cutouts([Slot(13.0, 3.0).path_at(Location(20.0, 20.0), 90.0)]).loops[0]
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    assert max(ys) - min(ys) == pytest.approx(13.0, abs=0.02)
    assert max(xs) - min(xs) == pytest.approx(3.0, abs=0.02)


def test_a_circle_takes_no_rotation():
    with pytest.raises(ValueError, match="no direction"):
        Circle(8.0).path_at(Location(0.0, 0.0), 45.0)


def test_a_shape_knows_its_box_before_it_is_flattened():
    assert Slot(13.0, 3.0).box_at(Location(20.0, 20.0), 0.0) == \
        pytest.approx((13.5, 18.5, 26.5, 21.5), abs=0.02)
```

Update the file's imports to `from placemat.cutouts import Circle, Cutouts, Path, Slot` and change `SLOT = slot((13.0, 28.0), (27.0, 28.0), 3.0)` to `SLOT = Slot(17.0, 3.0).path_at(Location(20.0, 28.0))`, which is the same geometry (a 14 mm centre line, 3 mm across, centred at x=20).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run python -m pytest tests/test_cutouts.py -q`
Expected: FAIL with `ImportError: cannot import name 'Slot'`.

- [ ] **Step 3: Implement the shapes**

In `src/placemat/cutouts.py`, delete `circle()` and `slot()` and put this in their place:

```python
def _turned(points, centre, bearing: float) -> list:
    """`points`, about the origin, turned by a bearing and moved to `centre`.
    A bearing is degrees clockwise from the top, so it turns the same way
    everything else in placemat does."""
    cx, cy = point(centre)
    r = math.radians(bearing)
    cos_r, sin_r = math.cos(r), math.sin(r)

    def at(p):
        x, y = p
        return (round(cx + x * cos_r - y * sin_r, 6), round(cy + x * sin_r + y * cos_r, 6))

    out = []
    for piece in points:
        out.append(Arc(to=at(piece.to), via=at(piece.via)) if isinstance(piece, Arc) else at(piece))
    return out


@dataclass(frozen=True)
class Slot:
    """A rounded-end slot, `length` measured tip to tip and `width` across.
    It runs along +X until a bearing turns it. Tip to tip is what a drawing
    dimensions and what callipers measure, so a 12.5 mm cable wants a 13 mm
    slot, not a 13 mm centre line."""
    length: float
    width: float

    def __post_init__(self):
        if self.width <= 0 or self.length <= 0:
            raise ValueError("a slot's length and width are positive, not %r by %r" % (self.length, self.width))
        if self.length < self.width:
            raise ValueError("a slot is at least as long as it is wide: %r tip to tip is less than %r across"
                             % (self.length, self.width))

    @property
    def area(self) -> float:
        r = self.width / 2.0
        return (self.length - self.width) * self.width + math.pi * r * r

    def _local(self) -> list:
        r = self.width / 2.0
        h = max(self.length / 2.0 - r, 0.0)          # the centre line's half length
        if h < NM:
            return _circle_local(r)
        return [(-h, -r), (h, -r), Arc(to=(h, r), via=(h + r, 0.0)),
                (-h, r), Arc(to=(-h, -r), via=(-h - r, 0.0))]

    def path_at(self, centre, rotation: float = 0.0) -> list:
        return _turned(self._local(), centre, float(rotation))

    def box_at(self, centre, rotation: float = 0.0) -> tuple:
        return _box_of(self.path_at(centre, rotation))


@dataclass(frozen=True)
class Circle:
    """A round hole."""
    diameter: float

    def __post_init__(self):
        if self.diameter <= 0:
            raise ValueError("a circle's diameter is positive, not %r" % (self.diameter,))

    @property
    def area(self) -> float:
        return math.pi * (self.diameter / 2.0) ** 2

    def path_at(self, centre, rotation: float = 0.0) -> list:
        if abs(float(rotation)) > 1e-9:
            raise ValueError("a circle has no direction: drop the rotation, or use a Slot")
        return _turned(_circle_local(self.diameter / 2.0), centre, 0.0)

    def box_at(self, centre, rotation: float = 0.0) -> tuple:
        return _box_of(self.path_at(centre, rotation))


@dataclass(frozen=True)
class Path:
    """Any closed path, as declared. It is moved so its box centre lands
    where it is placed, so one constant can be cut in two places."""
    points: tuple

    def __init__(self, points):
        object.__setattr__(self, "points", tuple(points))
        if len(self.points) < 3:
            raise ValueError("a closed path needs at least three points")

    @property
    def area(self) -> float:
        return abs(signed_area(flatten_path(list(self.points))))

    def _local(self) -> list:
        lo_x, lo_y, hi_x, hi_y = _box_of(list(self.points))
        mx, my = (lo_x + hi_x) / 2.0, (lo_y + hi_y) / 2.0
        return _turned(list(self.points), (-mx, -my), 0.0)   # about its own box centre

    def path_at(self, centre, rotation: float = 0.0) -> list:
        return _turned(self._local(), centre, float(rotation))

    def box_at(self, centre, rotation: float = 0.0) -> tuple:
        return _box_of(self.path_at(centre, rotation))


def _circle_local(r: float) -> list:
    k = r * math.sqrt(0.5)
    return [(0.0, -r), Arc(to=(r, 0.0), via=(k, -k)), Arc(to=(0.0, r), via=(k, k)),
            Arc(to=(-r, 0.0), via=(-k, k)), Arc(to=(0.0, -r), via=(-k, -k))]


def _box_of(path) -> tuple:
    """The box round a declared path, flattening its arcs so a bulge counts."""
    loop = flatten_path(list(path))
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    return (min(xs), min(ys), max(xs), max(ys))
```

`Path.__init__` is written by hand rather than generated, because a frozen dataclass cannot coerce a list to a tuple in `__post_init__` and still hash.

- [ ] **Step 4: Update the exports and the remaining call sites**

In `src/placemat/__init__.py` replace `from .cutouts import circle, slot` with `from .cutouts import Circle, Path, Slot` and change `"circle", "slot"` in `__all__` to `"Circle", "Path", "Slot"`.

In `tests/test_write_copper.py`: change the import to `from placemat.cutouts import Circle, Slot`, replace `SLOT_LINE`/`SLOT_WIDE` with `SLOT_SHAPE = Slot(17.0, 3.0)` and `SLOT_AT = Location(21.0, 30.0)`, change `declare(b, [slot(*SLOT_LINE, SLOT_WIDE)])` to `declare(b, [SLOT_SHAPE.path_at(SLOT_AT)])`, change `b.outline(circle((21.0, 21.0), 42.0), ...)` to `b.outline(Circle(42.0).path_at(Location(21.0, 21.0)), ...)`, and compute `cut = SLOT_SHAPE.area`.

In `tests/test_cutouts.py`, replace every `circle((x, y), d)` with `Circle(d).path_at(Location(x, y))`.

- [ ] **Step 5: Run the suite**

Run: `uv run python -m pytest -q && uvx ruff check --select F401,F811,F821 src/placemat tests`
Expected: all pass, lint clean.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "A shape says what a hole is, never where it is

slot(start, end, width) and circle(centre, diameter) answered two
questions at once, so neither could be placed, referred to or left a
freedom. Slot(length, width) is measured tip to tip, the way a drawing
dimensions it, and takes its position from whoever places it."
```

---

### Task 2: How much material is left

The web is the shortest distance between two boundaries. For a hole inside a board that distance is the material between them, so nothing more elaborate is needed.

**Files:**
- Modify: `src/placemat/cutouts.py`
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: `point_segment` from `cutouts.py`
- Produces: `loop_gap(a, b) -> float` - the shortest distance between two flattened loops, 0.0 when they touch or cross; `Cutouts.web_against(loops) -> (float, int)` - the narrowest gap between any cutout and any of `loops`, and the index of the cutout it was measured on

- [ ] **Step 1: Write the failing test**

```python
def test_the_gap_between_two_loops_is_their_shortest_distance():
    from placemat.cutouts import loop_gap
    inner = Cutouts([Circle(10.0).path_at(Location(20.0, 20.0))]).loops[0]
    outer = Cutouts([Path([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)])
                     .path_at(Location(20.0, 20.0))]).loops[0]
    assert loop_gap(inner, outer) == pytest.approx(15.0, abs=0.02)   # 20 to the wall, less the 5 radius


def test_two_loops_that_cross_have_no_gap():
    from placemat.cutouts import loop_gap
    a = Cutouts([Circle(10.0).path_at(Location(20.0, 20.0))]).loops[0]
    b = Cutouts([Circle(10.0).path_at(Location(24.0, 20.0))]).loops[0]
    assert loop_gap(a, b) == 0.0


def test_the_web_is_the_narrowest_gap_to_anything():
    board = Cutouts([Path([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)])
                     .path_at(Location(20.0, 20.0))]).loops[0]
    holes = Cutouts([Circle(6.0).path_at(Location(20.0, 20.0)),       # 17 from the wall
                     Circle(4.0).path_at(Location(4.0, 20.0))])       # 2 from the wall
    web, which = holes.web_against([board])
    assert web == pytest.approx(2.0, abs=0.02) and which == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_cutouts.py -q -k "gap or web"`
Expected: FAIL with `ImportError: cannot import name 'loop_gap'`.

- [ ] **Step 3: Implement**

Append to `src/placemat/cutouts.py`:

```python
def loop_gap(a, b) -> float:
    """The shortest distance between two closed loops; 0.0 when they touch
    or cross. Between a cutout and the board that distance is the material
    left between them."""
    best = math.inf
    for (ax, ay), (bx, by) in zip(a, a[1:] + a[:1]):
        for (cx, cy), (dx, dy) in zip(b, b[1:] + b[:1]):
            if crosses(ax, ay, bx, by, cx, cy, dx, dy):
                return 0.0
            best = min(best, point_segment(ax, ay, cx, cy, dx, dy),
                       point_segment(cx, cy, ax, ay, bx, by))
    return 0.0 if best is math.inf else best
```

and as a method on `Cutouts`:

```python
    def web_against(self, loops) -> tuple:
        """The narrowest material between any cutout and any of `loops` (the
        board's own outline, and the cutouts already down), and which cutout
        it was measured on. (inf, -1) when there is nothing to measure."""
        best, which = math.inf, -1
        for n, hole in enumerate(self.loops):
            for other in loops:
                gap = loop_gap(hole, other)
                if gap < best:
                    best, which = gap, n
        for n, hole in enumerate(self.loops):
            for m in range(n + 1, len(self.loops)):
                gap = loop_gap(hole, self.loops[m])
                if gap < best:
                    best, which = gap, n
        return best, which
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest tests/test_cutouts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "The web: how much board is left between two cut features"
```

---

### Task 3: Runs off a cutout's boundary

A hole loop winds opposite to the board's. Walking it with the sign flipped gives normals that point into the hole, which is the direction `run_placement` walks back from.

**Files:**
- Modify: `src/placemat/outline.py` (`Outline.runs` and `Outline.polygon`'s sibling helpers are untouched)
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: `Outline.loops`, `_run_of`, `_normal`, `_area`
- Produces: `Outline.runs(facing, within=45.0, loop=0) -> list[Run]`. `loop=0` is the board and behaves exactly as today; `loop=n` for n >= 1 walks that hole with the winding sign negated, so a returned `Run.facing` is the bearing an item placed there points, which is into the hole.

- [ ] **Step 1: Write the failing test**

```python
def test_a_hole_is_walked_so_its_normals_point_into_it():
    """An item against a slot's northern boundary faces south, into the
    slot: the same turn OnBore makes at a bore."""
    o = Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], holes=[SLOT])
    (run,) = o.runs(Edge.SOUTH, within=20.0, loop=1)
    point, out = run.at(run.length / 2.0)
    assert point.y == pytest.approx(26.5, abs=0.02)      # the slot's TOP edge
    assert out == pytest.approx(180.0, abs=1.0)          # facing down, into the slot


def test_the_board_is_still_loop_zero():
    o = Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], holes=[SLOT])
    (north,) = o.runs(Edge.NORTH)
    assert north.length == pytest.approx(40.0) and north.at(0.0)[0].y == 0.0
    assert o.runs(Edge.NORTH) == o.runs(Edge.NORTH, loop=0)


def test_a_loop_that_is_not_there_is_refused():
    o = Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], holes=[SLOT])
    with pytest.raises(ValueError, match="1 cutout"):
        o.runs(Edge.NORTH, loop=2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_cutouts.py -q -k "hole_is_walked or loop_zero or not_there"`
Expected: FAIL with `TypeError: runs() got an unexpected keyword argument 'loop'`.

- [ ] **Step 3: Implement**

In `src/placemat/outline.py`, change `runs` to take the loop and flip the sign for a hole:

```python
    def runs(self, facing, within: float = 45.0, loop: int = 0) -> list:
        """The stretches of one of this outline's loops whose outward side
        points within `within` degrees of `facing`, in path order. `loop=0`
        is the board: a rectangle's north side is one, a rounded top is one,
        a rim gives the arc facing that way. `loop=n` is the n-th cutout,
        walked so that its normals point INTO the hole - the direction an
        item placed against it faces, and the one run_placement walks back
        from."""
        if not 0 <= loop < len(self.loops):
            raise ValueError("this board has %d cutout(s); there is no loop %d" % (len(self.loops) - 1, loop))
        want = bearing(facing)
        ring = self.loops[loop]
        sign = 1.0 if _area(ring) > 0 else -1.0
        if loop:
            sign = -sign                    # a hole's material is outside it, so its outward side is inward
        legs = list(zip(ring, ring[1:] + ring[:1]))
        keep = []
        for (a, b) in legs:
            nx, ny = _normal(b[0] - a[0], b[1] - a[1], sign)
            keep.append(abs(_angle_gap(bearing_of(nx, ny), want)) <= within + 1e-9)
        if not any(keep):
            return []
        if all(keep):
            pts = tuple(p for p, _ in legs)
            return [Run(pts, want, closed=True, _sign=sign)]
        start = next(i for i in range(len(legs)) if keep[i] and not keep[i - 1])
        runs, current = [], []
        for k in range(len(legs)):
            i = (start + k) % len(legs)
            if keep[i]:
                if not current:
                    current = [legs[i][0]]
                current.append(legs[i][1])
            elif current:
                runs.append(_run_of(current, sign))
                current = []
        if current:
            runs.append(_run_of(current, sign))
        return runs
```

Only three lines differ from today: the guard, `ring = self.loops[loop]`, and the `if loop: sign = -sign`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest -q`
Expected: all pass. The board's own runs are unchanged, so nothing else moves.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "Runs can be read off a cutout, walked so they face into it"
```

---

### Task 4: A named cutout, declared with a shape and a place

This task gets a `Cutout` value end to end with the simplest possible place - an absolute `Location`, resolved at declaration. References and freedoms come in Task 7.

**Files:**
- Modify: `src/placemat/values.py` (the `Cutout` value)
- Modify: `src/placemat/layout.py` (`size`/`disc`/`outline` accept `Cutout` in `holes=`)
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: `Slot`/`Circle`/`Path` from Task 1
- Produces: `Cutout(shape, name, at=None, rotation=None, why="")` - frozen dataclass. `.shape`, `.name`, `.at`, `.rotation`, `.why`. `holes=` on `size()`, `disc()` and `outline()` accepts a `Cutout` or a raw path, told apart by `isinstance(h, Cutout)`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_named_cutout_is_declared_with_a_shape_and_a_place():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc", at=Location(20.0, 28.0),
                         why="the cable passes through here")])
    plan = b.resolve()
    assert plan.cutouts.area == pytest.approx(Slot(17.0, 3.0).area, rel=0.005)


def test_a_cutout_needs_a_name_and_a_place():
    with pytest.raises(ValueError, match="name"):
        Cutout(Slot(10.0, 3.0), "", at=Location(0.0, 0.0))
    with pytest.raises(ValueError, match="at="):
        Cutout(Slot(10.0, 3.0), "ffc")


def test_two_cutouts_may_not_share_a_name():
    b = make_board()
    with pytest.raises(ValueError, match="already a cutout named"):
        b.size(width=40.0, height=40.0,
               holes=[Cutout(Circle(3.0), "vent", at=Location(10.0, 10.0)),
                      Cutout(Circle(3.0), "vent", at=Location(30.0, 10.0))])


def test_a_raw_path_and_a_named_cutout_live_side_by_side():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[SLOT, Cutout(Circle(4.0), "vent", at=Location(10.0, 10.0))])
    plan = b.resolve()
    assert plan.cutouts.area == pytest.approx(Slot(17.0, 3.0).area + math.pi * 4.0, rel=0.01)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_cutouts.py -q -k "named_cutout or needs_a_name or share_a_name or side_by_side"`
Expected: FAIL with `ImportError: cannot import name 'Cutout'`.

- [ ] **Step 3: Implement the value**

In `src/placemat/values.py`, after `Disc`:

```python
@dataclass(frozen=True)
class Cutout:
    """A hole in the board: what it is (a shape), where it goes (`at`, the
    same places a part takes), and which way it runs. `name` is how the
    script refers to it later, to place something against its edge."""
    shape: object
    name: str
    at: object = None
    rotation: float | None = None
    why: str = ""

    def __post_init__(self):
        if not self.name or not str(self.name).strip():
            raise ValueError("a cutout needs a name: it is how a script refers to its edge")
        if self.at is None:
            raise ValueError("a cutout needs at=: where a hole goes is not a guess. "
                             "at=Location(x, y), Centre(...), Polar(...) or OnEdge(...)")
```

Export it: add `Cutout` to `src/placemat/__init__.py`'s import from `.values` and to `__all__`.

- [ ] **Step 4: Accept it in the declarations**

In `src/placemat/layout.py`, add a helper beside `_circle` and call it from all three declarations:

```python
    def _cutout_paths(self, holes) -> tuple:
        """`holes` as absolute paths, and the named cutouts among them kept
        by name. A raw path is already where it goes; a Cutout is a shape
        and a place, and only an absolute place can be resolved here - the
        rest are intents, settled when the board is resolved."""
        paths, named = [], {}
        for h in holes:
            if not isinstance(h, Cutout):
                paths.append(list(h))
                continue
            if h.name in named:
                raise ValueError("there is already a cutout named %r on this board" % h.name)
            named[h.name] = h
            paths.append(None)                  # its place is settled at resolve
        self._named_cutouts = named
        return tuple(paths)
```

For this task only, an absolute `Location` resolves immediately so the feature is demonstrable end to end. Task 7 replaces this branch with the intent queue. In place of the `paths.append(None)` line above:

```python
            if isinstance(h.at, Location) and isinstance(h.at.x, (int, float)) and isinstance(h.at.y, (int, float)):
                paths.append(h.shape.path_at(h.at, h.rotation or 0.0))
            else:
                raise ValueError("cutout %r: only at=Location(x, y) is settled yet" % h.name)
```

Named cutouts must come first in the returned tuple, in declaration order, so that `loop=index+1` in Task 5 lands on the right one. Collect them in two lists and concatenate:

```python
        paths, raw, named = [], [], {}
        for h in holes:
            if not isinstance(h, Cutout):
                raw.append(list(h))
                continue
            if h.name in named:
                raise ValueError("there is already a cutout named %r on this board" % h.name)
            named[h.name] = h
            if isinstance(h.at, Location) and isinstance(h.at.x, (int, float)) and isinstance(h.at.y, (int, float)):
                paths.append(h.shape.path_at(h.at, h.rotation or 0.0))
            else:
                raise ValueError("cutout %r: only at=Location(x, y) is settled yet" % h.name)
        self._named_cutouts = named
        return tuple(paths) + tuple(raw)
```

Wire it into `size()`, `disc()` and `outline()` in place of the bare `holes` they pass today, initialise `self._named_cutouts = {}` in `Board.__init__`, and import `Cutout` from `.values` at the top of `layout.py`.

Add `keep_going` to the test helper so later tasks can use it:

```python
def make_board(*insts, margin=0.5, keep_going=False):
    fps = [footprint(i.upper(), 50.0, 3.0 + n * 6.0, w=4.0, h=4.0, inst=i, nets=("M", "GND"))
           for n, i in enumerate(insts)]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=margin, keep_going=keep_going)
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "A cutout is a shape, a place and a name"
```

---

### Task 5: Placing against a cutout's edge

**Files:**
- Modify: `src/placemat/layout.py` (`board.cutout(name)`, the handle, the deferred reference)
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: `Outline.runs(..., loop=)` from Task 3, `self._named_cutouts` from Task 4
- Produces:
  - `board.cutout(name) -> CutoutHandle`
  - `CutoutHandle.edge(side, within=45.0) -> Run`, `.edges(side, within=45.0) -> list[Run]`, `.box`, `.centre`, `.area`, `.name`
  - `CutoutHandle.edge(facing=...)` raises, naming `side=`

- [ ] **Step 1: Write the failing test**

```python
def _with_slot():
    b = make_board("u1")
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc", at=Location(20.0, 28.0), why="the cable")])
    return b


def test_a_part_sits_against_the_side_of_a_cutout_it_was_given():
    """side=NORTH is the hole's northern boundary, so the part sits above
    the slot, held off it by the keep-in, turned to face down into it."""
    b = _with_slot()
    b.place(Part("u1"), at=OnEdge(b.cutout("ffc").edge(side=Edge.NORTH), along=Along.MID))
    plan = b.resolve()
    body = plan.box("u1")
    assert body.bottom == pytest.approx(26.5 - 0.5, abs=0.05)     # keep_in off the slot's top face
    assert plan.placements["u1"].rotation == pytest.approx(180.0, abs=1.0)


def test_a_cutout_takes_side_and_refuses_facing():
    b = _with_slot()
    with pytest.raises(TypeError, match="side="):
        b.cutout("ffc").edge(facing=Edge.NORTH)


def test_a_cutout_that_was_never_declared_says_which_there_are():
    b = _with_slot()
    with pytest.raises(ValueError, match="ffc"):
        b.cutout("usb")


def test_the_boards_own_edge_never_returns_a_cutouts():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc", at=Location(20.0, 28.0), why="a"),
                  Cutout(Circle(4.0), "vent", at=Location(10.0, 10.0), why="b")])
    for facing in (Edge.NORTH, Edge.SOUTH, Edge.EAST, Edge.WEST):
        (run,) = b.edges(facing)
        assert run.length == pytest.approx(40.0)          # the board's side, whole


def test_a_raw_path_board_says_only_a_named_cutout_can_be_referred_to():
    b = make_board()
    b.size(width=40.0, height=40.0, holes=[SLOT])
    with pytest.raises(ValueError, match="named Cutout"):
        b.cutout("ffc")


def test_each_cutout_offers_only_its_own_edges():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc", at=Location(20.0, 28.0), why="a"),
                  Cutout(Circle(8.0), "vent", at=Location(10.0, 10.0), why="b")])
    assert b.cutout("vent").edge(side=Edge.NORTH).length < math.pi * 8.0
    assert b.cutout("ffc").centre.y == pytest.approx(28.0, abs=0.02)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_cutouts.py -q -k "against_the_side or refuses_facing or never_declared or own_edge or only_its_own"`
Expected: FAIL with `AttributeError: 'Board' object has no attribute 'cutout'`.

Add `-k` terms for the new test too, or just run the file.

- [ ] **Step 3: Implement**

In `src/placemat/layout.py`, add the handle near the `Run` helpers:

```python
class CutoutHandle:
    """One named cutout, and the stretches of its boundary. The only route
    to a cutout's runs: board.edge() reads the board's own outline, so a
    script asking for the board's edge can never be handed a hole's."""
    __slots__ = ("_board", "name", "_index")

    def __init__(self, board, name: str, index: int):
        self._board, self.name, self._index = board, name, index

    def edges(self, side=None, within: float = 45.0, **kw) -> list:
        """The stretches of this cutout's boundary on that SIDE of it: the
        northern side is the boundary an item above the hole sits against,
        facing south into it."""
        if "facing" in kw:
            raise TypeError("a cutout takes side=, not facing=: side=Edge.NORTH is the hole's northern "
                            "boundary, which an item sits above and faces south into. "
                            "facing= is the board's word, for which way an item points")
        if kw:
            raise TypeError("unexpected argument(s): %s" % ", ".join(sorted(kw)))
        if side is None:
            raise TypeError("which side of the cutout: side=Edge.NORTH, a bearing, or Fraction(f)")
        return self._board._shaped().runs((bearing(side) + 180.0) % 360.0, within, loop=self._index + 1)

    def edge(self, side=None, within: float = 45.0, **kw):
        runs = self.edges(side, within, **kw)
        if len(runs) == 1:
            return runs[0]
        if not runs:
            raise ValueError("no part of cutout %r faces %r within %g degrees" % (self.name, side, within))
        raise ValueError("%d stretches of cutout %r are on the %r side within %g degrees (%s): "
                         "narrow within=, or pick from .edges()"
                         % (len(runs), self.name, side, within, ", ".join("%.2f mm" % r.length for r in runs)))

    @property
    def _loop(self):
        return self._board._shaped().loops[self._index + 1]

    @property
    def box(self) -> Box:
        xs, ys = [p[0] for p in self._loop], [p[1] for p in self._loop]
        return Box(min(xs), min(ys), max(xs), max(ys))

    @property
    def centre(self) -> Location:
        return self.box.center

    @property
    def area(self) -> float:
        from .cutouts import signed_area
        return abs(signed_area(self._loop))
```

`(bearing(side) + 180.0) % 360.0` is the whole of the `side`/`facing` inversion: the caller says which side of the hole, and the run wanted is the one whose normal points the other way, into it.

And on `Board`:

```python
    def cutout(self, name: str) -> CutoutHandle:
        """A named cutout, so something can be placed against its boundary."""
        order = list(self._named_cutouts)
        if name not in self._named_cutouts:
            raise ValueError("no cutout named %r on this board%s" % (
                name, (": there is " + ", ".join(repr(n) for n in order)) if order
                else ". Only a named Cutout(shape, name, at=) can be referred to, not a raw path"))
        return CutoutHandle(self, name, order.index(name))
```

The handle's index is its position among the named cutouts. Make `_cutout_paths` put named cutouts' paths first, in declaration order, followed by the raw paths, so `loop=index+1` lands on the right one.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "board.cutout(name).edge(side=) places a part against a hole

side= is the hole's own side, not the bearing an item points: an item on
a slot's northern boundary faces south into it, so facing= would hand
back the opposite stretch. A cutout refuses facing= rather than answer
the wrong question."
```

---

### Task 6: The web, declared and checked

**Files:**
- Modify: `src/placemat/layout.py` (`web=` on the declarations, the finding)
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: `Cutouts.web_against` from Task 2
- Produces: `board.web` (float, default 0.0), settable by `board.web = x` or `web=` on `size()`/`disc()`/`outline()`; a finding `"web 1.12 mm between cutout 'ffc' and the board outline is under the 1.50 mm minimum"` when violated

- [ ] **Step 1: Write the failing test**

```python
def test_a_cutout_too_near_the_edge_is_a_finding():
    b = make_board(keep_going=True)
    b.size(width=40.0, height=40.0, web=1.5,
           holes=[Cutout(Circle(4.0), "vent", at=Location(2.5, 20.0), why="a")])
    plan = b.resolve()
    assert any("web" in f and "vent" in f for f in plan.findings)


def test_a_cutout_with_room_round_it_is_not():
    b = make_board()
    b.size(width=40.0, height=40.0, web=1.5,
           holes=[Cutout(Circle(4.0), "vent", at=Location(20.0, 20.0), why="a")])
    assert not b.resolve().findings


def test_no_web_declared_is_no_web_check():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Circle(4.0), "vent", at=Location(2.1, 20.0), why="a")])
    assert not b.resolve().findings
    assert b.web == 0.0


def test_two_cutouts_too_near_each_other_is_a_finding():
    b = make_board(keep_going=True)
    b.size(width=40.0, height=40.0, web=2.0,
           holes=[Cutout(Circle(4.0), "a", at=Location(18.0, 20.0), why="x"),
                  Cutout(Circle(4.0), "b", at=Location(23.0, 20.0), why="y")])
    plan = b.resolve()
    assert any("web" in f for f in plan.findings)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_cutouts.py -q -k web`
Expected: FAIL with `TypeError: size() got an unexpected keyword argument 'web'`.

- [ ] **Step 3: Implement**

Add `self.web = 0.0` to `Board.__init__`, a `web: float = 0.0` keyword on `size()`, `disc()` and `outline()` that assigns `self.web = float(web)`, and in `resolve()`, after every cutout is down:

```python
    def _check_web(self, plan: Plan):
        """How much board is left round every hole. A web under the declared
        minimum is a sliver: it snaps in depanelling or in the hand."""
        if self.web <= 0.0:
            return
        shape = self._shaped()                  # always an Outline, whatever the board was declared as
        holes = Cutouts(shape.paths[1:])
        if not holes:
            return
        gap, which = holes.web_against([shape.loops[0]])
        if gap < self.web - 1e-9:
            plan.findings.append("web %.2f mm round %s is under the %.2f mm minimum"
                                 % (gap, self._cutout_label(which), self.web))

    def _cutout_label(self, n: int) -> str:
        """Which hole a measurement was taken on. Named cutouts come first,
        in declaration order, so the index names one directly."""
        order = list(self._named_cutouts)
        return "cutout %r" % order[n] if 0 <= n < len(order) else "an unnamed cutout"
```

`_shaped()` returns an `Outline` for every board type, so `paths[1:]` is always the holes. On a disc that includes the bore, which is right: a bore too near the rim is the same defect as a slot too near it.

Call `self._check_web(plan)` from `resolve()` once every cutout is down - after `place_ranked(RANK_FIXED, RANK_EDGE)`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "board.web: the least material a hole may leave

keep_in is copper to edge and says where a part may sit. web is material
to material and says where a hole may sit. A board that never declares
one is unchanged."
```

---

### Task 7: Cutouts placed by reference, in the firm queue

The cutout stops being resolved at declaration and becomes an intent, so `PlaceIntent.needs` orders it against whatever it refers to.

**Files:**
- Modify: `src/placemat/layout.py` (`CutoutIntent`, `place_ranked`, `_cutout_paths`)
- Modify: `src/placemat/occupancy.py` (the shape grows as cutouts land)
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: `_locate(board, occ, ref)`, `_refs_in(points)`, `PlaceIntent.needs`, `place_ranked`
- Produces: `CutoutIntent(key, cutout, priority, why, index, needs)` with `.rank` returning `(RANK_FIXED, index)`; `Occupancy.add_cutout(path)` which replaces `board_shape`/`board_cutouts` with a value carrying the extra hole and drops the cached index

- [ ] **Step 1: Write the failing test**

```python
def test_a_cutout_is_placed_relative_to_the_part_it_serves():
    """Move the connector and the slot moves with it: the script says what
    the hole is for, not where it is."""
    for y in (12.0, 24.0):
        b = make_board("u1")
        b.size(width=40.0, height=40.0)
        b.place(Part("u1"), at=Location(20.0, y))
        b.size(width=40.0, height=40.0,
               holes=[Cutout(Slot(17.0, 3.0), "ffc",
                             at=Centre(X(Part("u1")), Y(Part("u1"), 6.0)), why="the cable")])
        plan = b.resolve()
        assert plan.cutouts_placed["ffc"].centre.y == pytest.approx(y + 6.0, abs=0.05)


def test_a_part_placed_against_a_cutout_waits_for_it():
    b = make_board("u1", "d1")
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc",
                         at=Centre(X(Part("u1")), Y(Part("u1"), 6.0)), why="the cable")])
    b.place(Part("u1"), at=Location(20.0, 12.0))
    b.place(Part("d1"), at=OnEdge(b.cutout("ffc").edge(side=Edge.SOUTH), along=Along.MID))
    plan = b.resolve()
    assert plan.box("d1").top > plan.box("u1").bottom       # below the slot, which is below u1


def test_a_cutout_may_not_be_placed_against_a_searched_part():
    b = make_board("u1")
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Circle(4.0), "vent", at=Centre(X(Part("u1")), Y(Part("u1"), 6.0)), why="a")])
    b.place(Part("u1"))                                      # searched: no position yet
    with pytest.raises(ValueError, match="only FIXED and EDGE"):
        b.resolve()


def test_a_cutout_that_would_break_the_web_is_refused():
    b = make_board()
    b.size(width=40.0, height=40.0, web=2.0,
           holes=[Cutout(Circle(4.0), "vent", at=Location(2.5, 20.0), why="a")])
    with pytest.raises(PlacementCollision, match="web"):
        b.resolve()


def test_a_cutout_may_not_be_milled_through_a_part():
    b = make_board("u1")
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Circle(6.0), "vent", at=Location(20.0, 20.0), why="a")])
    b.place(Part("u1"), at=Location(20.0, 20.0))
    with pytest.raises(PlacementCollision, match="u1"):
        b.resolve()


def test_a_cutout_that_touches_the_outline_is_a_notch_not_a_hole():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Circle(6.0), "notch", at=Location(1.0, 20.0), why="a")])
    with pytest.raises(PlacementCollision, match="notch"):
        b.resolve()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_cutouts.py -q -k "relative_to_the_part or waits_for_it or searched_part or break_the_web or through_a_part or notch"`
Expected: FAIL - `plan.cutouts_placed` does not exist and a referenced `at=` is refused by Task 4's "not yet".

- [ ] **Step 3: Implement the intent**

Add to `layout.py`:

```python
@dataclass
class CutoutIntent:
    """A hole waiting for its place. It sits in the firm queue with the
    parts, so `needs` orders it against whatever its place refers to: a
    cutout inboard of a connector waits for the connector, and a part
    against a cutout's edge waits for the cutout."""
    key: str
    cutout: object
    why: str = ""
    index: int = 0
    needs: frozenset = frozenset()
    priority: Priority = Priority.FIXED

    @property
    def rank(self):
        return (RANK_FIXED, self.index)
```

In `_cutout_paths`, build a `CutoutIntent` for each named cutout instead of resolving it, with
`needs = frozenset(self._pad_ref(ref)[0] for ref in _refs_in([h.at]))`, and append it to `self._intents`.

In `place_ranked`'s firm loop, when `ready[0]` is a `CutoutIntent`, resolve it rather than placing a part:

```python
        def settle_cutout(intent):
            c = intent.cutout
            centre = _locate(self, occ, c.at)
            turn = c.rotation if c.rotation is not None else self._implied_rotation(c, centre)
            path = c.shape.path_at(centre, turn)
            why = self._cutout_illegal(occ, path, c.name)
            if why:
                plan.findings.append("%s (cutout): %s" % (c.name, why))
                if not self.keep_going:
                    return
            occ.add_cutout(path)
            self._cached_outline = None
            plan.cutouts_placed[c.name] = PlacedCutout(c.name, path, centre, turn)
            placed.add(c.name)
```

`_cutout_illegal(occ, path, name)` applies the four rules in the spec's order and returns a sentence or None:

```python
    def _cutout_illegal(self, occ, path, name: str) -> str | None:
        from .cutouts import Cutouts, loop_gap
        shape = self._shaped()
        loop = Cutouts([path]).loops[0]
        board = shape.loops[0]
        for x, y in loop:
            if shape.why_not(Box(x, y, x, y), 0.0) == "outside the board":
                return "reaches outside the board"
        if loop_gap(loop, board) <= 0.0:
            return ("touches the board outline: that is a notch, not a hole, and it belongs in the "
                    "board's own outline path")
        if self.web > 0.0:
            gap = min([loop_gap(loop, board)] + [loop_gap(loop, h) for h in shape.loops[1:]])
            if gap < self.web - 1e-9:
                return "would leave a %.2f mm web, under the %.2f mm minimum" % (gap, self.web)
        box = Box(min(p[0] for p in loop), min(p[1] for p in loop),
                  max(p[0] for p in loop), max(p[1] for p in loop))
        for owner, g in occ.items.items():
            reach = g.reach or g.body
            if reach.overlaps(box):
                return "would be milled through %s" % owner
        return None
```

```python
    def _implied_rotation(self, cutout, centre: Location) -> float:
        """Which way a shape runs when the script did not say. A place that
        carries a direction - round a circle, along an edge - runs the shape
        TANGENTIALLY: a vent follows the rim, a cable slot runs parallel to
        the connector it serves. Everywhere else the shape is as declared."""
        if isinstance(cutout.at, Polar):
            out = bearing_of(centre.x - self.centre.x, centre.y - self.centre.y)
            return (out + 90.0) % 360.0                  # across the radius, not along it
        if isinstance(cutout.at, OnEdge):
            run = cutout.at.edge if isinstance(cutout.at.edge, Run) else self.edge(facing=cutout.at.edge)
            return (run.at(run.project(centre))[1] + 90.0) % 360.0
        return 0.0
```

Add `PlacedCutout` (a frozen `name, path, centre, rotation` record), `Plan.cutouts_placed: dict`, and on `Occupancy`:

```python
    def add_cutout(self, path):
        """A hole that has just been placed. Every legality test after this
        one sees it, so a part cannot be put where the board will be milled
        away."""
        import dataclasses
        if self.board_shape is not None:
            holes = tuple(self.board_shape.holes) + (tuple(path),) if hasattr(self.board_shape, "holes") \
                else None
            if holes is not None:
                self.board_shape = dataclasses.replace(self.board_shape, holes=holes)
            else:
                self.board_shape = type(self.board_shape).of(self.board_shape.paths[0],
                                                             list(self.board_shape.paths[1:]) + [path])
        else:
            self.board_cutouts = Cutouts(list(self.board_cutouts.paths) + [path])
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "A cutout is placed by what it serves, not by typed coordinates

It joins the firm queue, so needs orders it against whatever its place
refers to: a slot inboard of a connector waits for the connector, and a
part against that slot waits for the slot. A hole that would reach
outside the board, leave too thin a web, or be milled through a part is
refused before it is cut."
```

---

### Task 8: A cutout with a freedom

**Files:**
- Modify: `src/placemat/layout.py` (the searched branch of `settle_cutout`)
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: `Board._cutout_illegal` and `settle_cutout` from Task 7
- Produces: `Board._slide_cutout(occ, intent) -> (Location, float)` - the first legal centre and rotation along the cutout's one freedom, or a `ValueError` naming what stopped it

`placer.py` is NOT touched. The spec's file table said a searched cutout would need a probe there; it does not, because `_cutout_illegal` lives on `Board`, where the web and the named cutouts already are, and a candidate is tested by calling it. `run_placement` is likewise untouched: a part placed against a cutout's edge consumes a `Run` like any other.

- [ ] **Step 1: Write the failing test**

```python
def test_a_cutout_with_one_freedom_slides_to_where_there_is_room():
    b = make_board("u1")
    b.size(width=40.0, height=40.0, web=1.0,
           holes=[Cutout(Circle(6.0), "vent", at=Centre(None, 20.0), why="airflow")])
    b.place(Part("u1"), at=Location(20.0, 20.0))
    plan = b.resolve()
    got = plan.cutouts_placed["vent"].centre
    assert got.y == pytest.approx(20.0)
    assert abs(got.x - 20.0) > 5.0                 # it moved off the part


def test_a_cutout_with_nowhere_legal_says_so():
    b = make_board()
    b.size(width=10.0, height=10.0, web=2.0,
           holes=[Cutout(Circle(9.0), "vent", at=Centre(None, 5.0), why="airflow")])
    with pytest.raises(PlacementCollision, match="vent"):
        b.resolve()


def test_a_slot_on_a_ring_runs_tangentially_unless_told():
    b = make_board()
    b.disc(diameter=40.0, web=1.0,
           holes=[Cutout(Slot(10.0, 2.0), "vent", at=Polar(14.0, Fraction(0.5)), why="airflow")])
    plan = b.resolve()
    placed = plan.cutouts_placed["vent"]
    assert placed.centre.y == pytest.approx(34.0, abs=0.05)     # due south of a centre at (20, 20)
    assert placed.rotation % 180.0 == pytest.approx(90.0, abs=1.0)   # across the radius
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_cutouts.py -q -k "one_freedom or nowhere_legal or tangentially"`
Expected: FAIL - a `Centre` with a free axis is not yet handled for a cutout.

- [ ] **Step 3: Implement**

Give `CutoutIntent` a `priority` of `Priority.DEFAULT` when its `at=` leaves a freedom, so it falls into the `pending` half of `place_ranked(RANK_FIXED, RANK_EDGE)` - after every firm item, before any searched part. Then:

```python
    def _cutout_candidates(self, intent):
        """Every centre the cutout's one freedom allows, nearest its ideal
        first, with the rotation each implies."""
        c, box = intent.cutout, self._outline
        if isinstance(c.at, Polar) and c.at.angle is None:
            r = float(c.at.radius)
            for k in range(0, 360):
                step = (k + 1) // 2 * (1 if k % 2 else -1)       # outward from the start, both ways
                centre = polar_point(self.centre, step, r)
                yield centre, (c.rotation if c.rotation is not None
                               else (bearing_of(centre.x - self.centre.x, centre.y - self.centre.y) + 90.0) % 360.0)
            return
        if isinstance(c.at, Polar) and c.at.radius is None:
            lo, hi = 0.0, max(box.width, box.height) / 2.0
            n = int((hi - lo) / 0.2) + 1
            for k in range(n):
                centre = polar_point(self.centre, c.at.angle, lo + k * 0.2)
                yield centre, (c.rotation if c.rotation is not None else bearing(c.at.angle))
            return
        axis = "x" if c.at.x is None else "y"                    # a Centre with one axis free
        fixed = _coord(self, None, c.at.y if axis == "x" else c.at.x, "y" if axis == "x" else "x")
        lo, hi = (box.left, box.right) if axis == "x" else (box.top, box.bottom)
        mid = (lo + hi) / 2.0
        n = int((hi - lo) / 0.2) + 1
        for k in range(n):                                       # from the middle outward, both ways
            d = (k + 1) // 2 * 0.2 * (1 if k % 2 else -1)
            v = mid + d
            if not lo <= v <= hi:
                continue
            centre = Location(v, fixed) if axis == "x" else Location(fixed, v)
            yield centre, (c.rotation or 0.0)

    def _slide_cutout(self, occ, intent):
        """The first place its freedom allows where the hole is legal."""
        last = "nowhere on the board"
        for centre, turn in self._cutout_candidates(intent):
            why = self._cutout_illegal(occ, intent.cutout.shape.path_at(centre, turn), intent.cutout.name)
            if why is None:
                return centre, turn
            last = why
        raise ValueError("cutout %r has nowhere legal to go: %s" % (intent.cutout.name, last))
```

In `settle_cutout`, when the intent carries a freedom, take `centre, turn` from `_slide_cutout` instead of `_locate`. A `ValueError` from it becomes a finding and, unless `keep_going`, a `PlacementCollision` - the same as an unplaceable part.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "A cutout may be left a freedom and slide to where there is room"
```

---

### Task 9: board.outline takes a shape, and the documentation

**Files:**
- Modify: `src/placemat/layout.py` (`outline` accepts a shape)
- Modify: `skills/placemat/SKILL.md`, `skills/placemat/references/api.md`
- Test: `tests/test_cutouts.py`

**Interfaces:**
- Consumes: everything above
- Produces: `board.outline(shape_or_path, holes=(), web=0.0, draw=True)` - a shape is centred on the board origin

- [ ] **Step 1: Write the failing test**

```python
def test_a_round_board_can_be_said_as_a_shape():
    b = make_board()
    b.outline(Circle(40.0))
    assert b.width == pytest.approx(40.0) and b.height == pytest.approx(40.0)
    assert b.resolve().shape.area == pytest.approx(math.pi * 400.0, rel=0.005)


def test_the_whole_thing():
    """A round board with a bore, a slot derived from the connector it
    serves, and a vent on a ring."""
    b = make_board("u1", "d1")
    b.disc(diameter=40.0, hole=6.0, web=1.0,
           holes=[Cutout(Slot(13.0, 3.0), "ffc", at=Centre(X(Part("u1")), Y(Part("u1"), 5.0)),
                         why="the cable passes through behind the connector"),
                  Cutout(Slot(8.0, 2.0), "vent", at=Polar(15.0, Fraction(0.5)), why="airflow")])
    b.place(Part("u1"), at=OnRim(Edge.NORTH))
    b.place(Part("d1"), at=OnEdge(b.cutout("ffc").edge(side=Edge.SOUTH), along=Along.MID))
    plan = b.resolve()
    assert not plan.findings
    assert b.radius == 20.0 and b.bore == 3.0                 # still a disc
    assert plan.cutouts_placed["ffc"].centre.y == pytest.approx(plan.box("u1").center.y + 5.0, abs=0.1)
    assert plan.box("d1").top > plan.cutouts_placed["ffc"].centre.y
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/test_cutouts.py -q -k "as_a_shape or whole_thing"`
Expected: FAIL.

- [ ] **Step 3: Implement**

At the top of `outline()`, before `Outline.of`:

```python
        if hasattr(path, "path_at"):            # a shape, not a path: the board sits at the origin
            lo_x, lo_y, hi_x, hi_y = path.box_at(Location(0.0, 0.0), 0.0)
            path = path.path_at(Location((hi_x - lo_x) / 2.0, (hi_y - lo_y) / 2.0), 0.0)
```

That puts the board's box top-left on the origin, which is where `size()` and `disc()` both put it.

- [ ] **Step 4: Write the documentation**

In `skills/placemat/SKILL.md`, replace the two cutout bullets added earlier with exactly these three:

```markdown
- A hole in the board is `Cutout(shape, name, at=, rotation=, why=)` in
  `holes=`, and **every board takes it**: `size()`, `disc()` and `outline()`
  all say it the same way. The shape says what the hole is - `Slot(length,
  width)` measured tip to tip, `Circle(diameter)`, `Path(points)` - and `at=`
  says where, in the same places a part takes: `Location`, `Centre` (with a
  free axis), `Polar`, `OnEdge`, `Near`. A slot that exists so a cable can
  reach a connector is placed FROM that connector, never at typed
  coordinates, so it follows when the connector moves. **Never reshape a
  board to give it a hole**: a slot in a round board is
  `board.disc(diameter=, hole=, holes=[...])`, still a disc, still answering
  `OnRim`, `OnBore`, `ring()`, `board.radius` and `board.bore`.
- `board.cutout(name).edge(side=)` is the only way to reach a hole's
  boundary, so `board.edge(facing=)` can never hand you one by accident.
  **`side=` is the hole's own side and reads the opposite way to the board's
  `facing=`**: an item against a slot's NORTHERN side sits above the hole and
  faces SOUTH into it, the same turn `OnBore` makes at a bore. That is why a
  cutout refuses `facing=` - it would answer with the opposite stretch. You
  place inside a board and around a hole, which is the whole of the
  difference.
- `board.web` is the least material that may remain between a hole and the
  board edge, or between two holes: material to material, where
  `board.keep_in` is copper to edge. A cutout that would leave less is
  refused before it is cut. A cutout is also a real board edge, so route and
  pour clear of it - KiCad's DRC reports copper-to-edge and silk-to-edge
  against it like any other edge.
```

In `skills/placemat/references/api.md`, replace the body of `## Cutouts` with:

```markdown
A hole in the board is a `Cutout` in `holes=`, and every board takes them: a
rectangle, a disc and a shaped board all say it the same way and all behave
the same way.

```python
from placemat import Cutout, Slot, Circle, Path

FFC = Cutout(Slot(13.0, 3.0), "ffc",
             at=Centre(X(Part("j_ffc")), Y(Part("j_ffc"), 4.0)),
             why="the FFC cable passes through to the panel behind")
VENT = Cutout(Slot(8.0, 2.0), "vent", at=Polar(14.0, Fraction(0.5)), why="airflow past the regulator")

board.disc(diameter=40.0, hole=6.0, web=1.5, holes=[FFC, VENT])

board.place(J, at=OnEdge(board.cutout("ffc").edge(side=Edge.NORTH), along=Along.MID))
```

**The shape says what, `at=` says where.** `Slot(length, width)` is measured
tip to tip, the way a drawing dimensions it, and runs along +X until a
`rotation=` bearing turns it. `Circle(diameter)` is a round hole and refuses a
rotation. `Path(points)` is any closed path, moved so its box centre lands
where it is placed. `at=` takes `Location`, `Centre`, `Polar`, `OnEdge` or
`Near`, and a freedom left in it is settled against what is on the board -
a vent with `at=Centre(None, 20.0)` slides along that line to where there is
room.

**Which way it runs.** With no `rotation=`, a place that carries a direction
runs the shape tangentially: a vent on a ring follows the rim, a slot on an
edge runs along it. Everywhere else the shape is as declared.

**When it is settled.** A cutout resolves with the firm items, after
everything whose position is decided and before anything searched, so every
part is placed against a board that already has its holes. It may be placed
from any decided item; a cutout placed from a searched part is refused,
naming it.

**`side=`, not `facing=`.** `board.cutout(name).edge(side=)` is the only route
to a hole's runs. `side=Edge.NORTH` is the hole's northern boundary, which an
item sits above and faces SOUTH into - the same turn `OnBore` makes. The
board's `facing=` means which way the item points, and on a hole those two
read opposite, so a cutout refuses `facing=` rather than hand back the wrong
stretch. Several stretches on one side raises from `.edge()` and comes back as
a list from `.edges()`.

**What a cutout is not.** It is not a stretch of the board's edge:
`board.edge(facing=)` reads the outline only. It is not a copper keepout: it
is a real board edge, so tracks and zones must clear it themselves.

**The web.** `board.web` is the least material that may remain round a hole.
`board.keep_in` is copper to edge and says where a part may sit; `board.web`
is material to material and says where a hole may sit. A cutout that would
leave less is refused. The default is 0.0, which means unchecked.
```

Add `web=0.0` to the three declarations in `## Setup`, and to the round-board
section add one line: a disc with cutouts is still a disc, and `OnRim`,
`OnBore`, `ring()`, `board.radius` and `board.bore` all still answer.

- [ ] **Step 5: Run everything**

Run: `uv run python -m pytest -q && uvx ruff check --select F401,F811,F821 src/placemat tests`
Expected: all pass, lint clean.

- [ ] **Step 6: Verify the fab output by hand**

Run a board with a slot through `apply_plan` and confirm with pcbnew that `GetBoardPolygonOutlines` returns one outline with the expected hole count, the slot's caps are 180-degree arcs, and there are no zero-length segments on Edge.Cuts. Add the assertion to `tests/test_write_copper.py`'s parametrised slot test using `Cutout` rather than a raw path.

- [ ] **Step 7: Commit**

```bash
git add -A src tests skills
git commit -m "board.outline takes a shape, and the skill says how holes work

The one inconsistency worth documenting: a board takes facing= and a
cutout takes side=, because you place inside a board and around a hole."
```

---

## Deviation from the spec

The spec put the web check in `checks.py` as a `Verdict`. That is wrong: `run_checks(geometry)` reads a written `.kicad_pcb` through `BoardGeometry`, which carries `outline_box` and no cutout paths, and it has no notion of `board.web`, which is a script's declaration. The web is therefore checked in `resolve()` and reported as a plan finding, which is the existing mechanism for "the script asserted something that does not hold". Task 6 implements it that way.
