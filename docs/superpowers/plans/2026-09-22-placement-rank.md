# Placement Rank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Order searched items by a rank computed from courtyard area and pin count, move decidedness out of `Priority` into a derived `Freedom`, and give "failing to place this stops the run" its own keyword.

**Architecture:** `Priority` reduces to HIGH/DEFAULT/LOW and is only ever script-set. A new `Freedom` (FIXED/EDGE/SEARCHED) is derived - from `at=` for a placement, from the endpoints for copper - and drives the queue split that `Priority.FIXED`/`EDGE` drove. `_weigh` is replaced by a static rank, `0.7*z(ln courtyard_area) + 0.3*z(ln pins)` over the board's own searched items, which becomes the primary key in `_next_to_place` with link pull demoted to a tie-break.

**Tech Stack:** Python 3.12, pytest, dataclasses. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-22-placement-rank-design.md`

**Depends on:** `docs/superpowers/plans/2026-09-22-placemat-toml.md` must be complete - the rank weights are `[rank] area` and `[rank] pins`.

## Global Constraints

- `pcbnew` may be imported only under `src/placemat/kicad/`.
- The rank weights come from `Settings.rank_area` and `Settings.rank_pins`. No weight is hard-coded outside `settings.py`.
- No percentage of the board area appears anywhere. `_CRITICAL_SHARE` is deleted.
- `Freedom` is derived and a script never writes one. `Priority` is script-set and never auto-assigned.
- The words `fixed` and `edge` are kept in findings and step output, so `place_ranked`'s collision filter and the api.md table read as they do now.
- ASCII only: no em dashes, no en dashes, no unicode arrows, straight quotes.
- Commit messages must contain no reference to Claude, Anthropic, or a session URL.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/placemat/values.py` (modify) | `Freedom` enum; `Priority` reduced to HIGH/DEFAULT/LOW |
| `src/placemat/ranking.py` (create) | `pin_count`, `rank_scores` - pure, no Board, no Occupancy |
| `tests/test_ranking.py` (create) | The score's properties: bands, ties, invariance, pin counting |
| `src/placemat/layout.py` (modify) | `PlaceIntent.freedom`, `CopperIntent.freedom`, `_rank`, `_next_to_place`, `required=`, step notes |
| `src/placemat/report.py` (modify) | Step records gain `freedom` and `rank`; `priority` is null for a decided placement |
| `src/placemat/runner.py` (modify) | Write the new step fields |
| `tests/test_priority.py` (rewrite) | The rank, not the tier |
| `tests/test_critical.py` (rewrite) | `required=` rather than `Priority.HIGH` |
| `tests/test_freedom.py` (modify) | Assert `Freedom`, not `Priority` |
| `skills/placemat/references/api.md` (modify) | Freedom table, the rank, `required=`, the copper section |
| `skills/placemat/SKILL.md` (modify) | Stop recommending `priority=Priority.HIGH` to get a big part down early |

---

## Task 1: The rank score, as a pure function

**Files:**
- Create: `src/placemat/ranking.py`
- Test: `tests/test_ranking.py`

**Interfaces:**
- Consumes: nothing from placemat except `board_geometry.Footprint`/`CellGeom` shapes (duck-typed).
- Produces: `pin_count(fp) -> int`, `rank_scores(items, area_weight, pins_weight) -> dict`, where `items` is `{key: (area, pins)}` and the result is `{key: score}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ranking.py
"""A searched item's place in the queue is what it IS: how much board its
courtyard needs, and how many pins it has, both against the rest of this
board. No threshold, no share of the board area."""
import math

from placemat.ranking import pin_count, rank_scores
from tests.fixtures import footprint, pad


def _score(items, area=0.7, pins=0.3):
    return rank_scores(items, area, pins)


def test_the_four_bands_come_out_in_order():
    """Large and many pins, then large and few, then small and many, then
    small and few. The band boundaries are nowhere in the code: the weights
    produce this ordering on their own."""
    s = _score({"large_many": (50.0, 56), "large_few": (50.0, 2),
                "small_many": (1.0, 56), "small_few": (1.0, 2)})
    assert s["large_many"] > s["large_few"] > s["small_many"] > s["small_few"]


def test_identical_items_tie_exactly():
    """The passive tail must tie so that link pull decides between them."""
    s = _score({"a": (0.5, 2), "b": (0.5, 2), "c": (0.5, 2)})
    assert s["a"] == s["b"] == s["c"]


def test_the_order_survives_a_change_of_units():
    """Standardising in log space makes the score scale-free: measuring the
    same board in um2 must not reorder it."""
    mm = _score({"a": (50.0, 56), "b": (8.0, 4), "c": (0.5, 2)})
    um = _score({"a": (50.0e6, 56), "b": (8.0e6, 4), "c": (0.5e6, 2)})
    assert sorted(mm, key=lambda k: -mm[k]) == sorted(um, key=lambda k: -um[k])


def test_one_huge_outlier_does_not_collapse_the_rest():
    """Dividing by the maximum compresses everything else toward zero and
    lets pins decide by accident. Standardising does not."""
    without = _score({"a": (8.0, 4), "b": (4.0, 4), "c": (0.5, 2)})
    with_outlier = _score({"huge": (5000.0, 8), "a": (8.0, 4), "b": (4.0, 4), "c": (0.5, 2)})
    assert without["a"] > without["b"] > without["c"]
    assert with_outlier["a"] > with_outlier["b"] > with_outlier["c"]
    assert with_outlier["huge"] > with_outlier["a"]


def test_a_single_item_scores_zero_rather_than_dividing_by_nothing():
    assert _score({"only": (12.0, 9)}) == {"only": 0.0}


def test_all_items_alike_score_zero_and_tie():
    s = _score({"a": (2.0, 2), "b": (2.0, 2)})
    assert s == {"a": 0.0, "b": 0.0}


def test_weighting_pins_at_nothing_ranks_by_area_alone():
    s = _score({"big_few": (50.0, 2), "small_many": (1.0, 56)}, area=1.0, pins=0.0)
    assert s["big_few"] > s["small_many"]


def test_pin_count_is_distinct_non_empty_pad_numbers():
    """The datasheet's pin count, not the pad count. The Keystone 1285 numbers
    BOTH of its legs 1, so it is one pin; the 1287 numbers them 1 and 2."""
    k1285 = footprint("J1", 0, 0, inst="j1")
    object.__setattr__(k1285, "pads", (pad("J1", "j1", 1, "VBIKE", -2.5, 0),
                                       pad("J1", "j1", 1, "VBIKE", 2.5, 0)))
    k1287 = footprint("J2", 0, 0, inst="j2")
    object.__setattr__(k1287, "pads", (pad("J2", "j2", 1, "VBIKE", -2.5, 0),
                                       pad("J2", "j2", 2, "VBIKE", 2.5, 0)))
    assert pin_count(k1285) == 1
    assert pin_count(k1287) == 2


def test_unnamed_netless_pads_are_not_pins():
    """The TPS16630's four unnamed through-hole pads were not thermal vias and
    are not pins either."""
    fp = footprint("U1", 0, 0, inst="u1")
    object.__setattr__(fp, "pads", (pad("U1", "u1", 1, "VIN", -1, 0),
                                    pad("U1", "u1", 2, "VOUT", 1, 0),
                                    pad("U1", "u1", "", "", 0, 1),
                                    pad("U1", "u1", "", "", 0, 2)))
    assert pin_count(fp) == 2


def test_a_footprint_with_no_numbered_pads_still_counts_as_one():
    """log(0) is not a number; a pinless part is the least complex thing there
    is, not an error."""
    fp = footprint("MH1", 0, 0, inst="mh1")
    object.__setattr__(fp, "pads", ())
    assert pin_count(fp) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ranking.py -x -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.ranking'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/placemat/ranking.py
"""What a searched item IS, as one number: how much board its courtyard needs
and how many pins it has, both measured against the rest of this board.

PCB placement is big and complex things first, then the small ones fitted
round them. The score says which is which without a threshold anywhere: each
dimension is standardised in log space over this board's own searched items,
and the two are weighted. Log space because the range is wide - a real board
runs from an 0402 at 0.7 mm2 to a module at 116 mm2, and from 1 pin to 57 -
and standardising because it is what makes the weights mean what they say
rather than inheriting whatever spread the board happens to have.

Nothing here knows about a Board, an Occupancy or a placement. It takes
measurements and returns scores.
"""
from __future__ import annotations

import math


def pin_count(fp) -> int:
    """A footprint's pins: distinct non-empty pad NUMBERS, floored at 1.

    The datasheet's count, not the pad count. A terminal whose two legs are
    both numbered `1` is one pin; one numbered `1` and `2` is two. Pads with
    no number are mechanical or thermal and are not pins. A part with no
    numbered pads is the least complex thing on the board, not an error, and
    the floor keeps it out of log(0)."""
    return len({p.number for p in fp.pads if p.number and p.number != "?"}) or 1


def _standardise(values: list) -> list:
    """Log values as z-scores. An all-alike board has no spread, and every
    item is equally typical of it: they all score 0."""
    logs = [math.log(max(v, 1e-9)) for v in values]
    n = len(logs)
    mean = sum(logs) / n
    var = sum((x - mean) ** 2 for x in logs) / n
    sd = math.sqrt(var)
    if sd <= 1e-12:
        return [0.0] * n
    return [(x - mean) / sd for x in logs]


def rank_scores(items: dict, area_weight: float, pins_weight: float) -> dict:
    """{key: (courtyard area mm2, pin count)} -> {key: score}, highest first
    in the queue. Ties are exact, so equal items fall through to whatever
    orders them next."""
    if not items:
        return {}
    keys = list(items)
    za = _standardise([items[k][0] for k in keys])
    zp = _standardise([items[k][1] for k in keys])
    return {k: area_weight * za[i] + pins_weight * zp[i] for i, k in enumerate(keys)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ranking.py -x -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/placemat/ranking.py tests/test_ranking.py
git commit -m "A rank score from courtyard area and pin count, in log space"
```

---

## Task 2: Freedom, derived from at=

**Files:**
- Modify: `src/placemat/values.py:162-179`, `src/placemat/layout.py:166-210,1074-1226,1735-1900`
- Test: `tests/test_freedom.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `values.Freedom` with `FIXED`/`EDGE`/`SEARCHED` and a `.decided` property; `PlaceIntent.freedom`; `PlaceIntent.rank` and `place_ranked` keyed on it. `Priority` still has FIXED/EDGE at this point - Task 4 removes them.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_freedom.py
from placemat.values import Freedom


def test_a_point_is_fixed_and_a_distance_along_an_edge_is_edge():
    fps = [footprint("J1", 10, 10, inst="j1"), footprint("J2", 30, 10, inst="j2"),
           footprint("R1", 50, 10, inst="r1")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    a = b.place(Part("j1"), at=Location(20, 20))
    e = b.place(Part("j2"), at=OnEdge(Edge.NORTH, along=30.0))
    s = b.place(Part("r1"))
    assert a.freedom is Freedom.FIXED and a.freedom.decided
    assert e.freedom is Freedom.EDGE and e.freedom.decided
    assert s.freedom is Freedom.SEARCHED and not s.freedom.decided


def test_a_freedom_left_in_the_place_makes_it_searched():
    fps = [footprint("J1", 10, 10, inst="j1"), footprint("J2", 30, 10, inst="j2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    slide = b.place(Part("j1"), at=OnEdge(Edge.NORTH))          # no along=
    line = b.place(Part("j2"), at=Location(30, None))           # one axis pinned
    assert slide.freedom is Freedom.SEARCHED
    assert line.freedom is Freedom.SEARCHED


def test_decided_items_still_go_down_before_searched_ones():
    fps = [footprint("U1", 10, 10, w=6, h=6, inst="u1", nets=("A", "B")),
           footprint("J1", 40, 40, inst="j1", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"))                                          # searched
    b.place(Part("j1"), at=Location(20, 20))                     # decided, declared second
    order = [s.item for s in b.resolve().steps if s.kind == "part"]
    assert order.index("j1") < order.index("u1")


def test_a_finding_still_names_the_freedom_the_way_it_always_did():
    fps = [footprint("J1", 10, 10, w=8, h=8, inst="j1"), footprint("J2", 30, 10, w=8, h=8, inst="j2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("j2"), at=Location(20, 20))                      # right on top
    plan = b.resolve()
    assert any(f.split(" ")[1] == "(fixed):" for f in plan.findings), plan.findings
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_freedom.py -x -q`
Expected: FAIL with `ImportError: cannot import name 'Freedom' from 'placemat.values'`

- [ ] **Step 3: Write minimal implementation**

In `values.py`, above `Priority`:

```python
class Freedom(str, Enum):
    """Whether a position is decided before the search runs.

    Derived, never chosen: from `at=` for a placement, and from the endpoints
    for copper. A decided item goes down first and nothing may move it; a
    searched one takes its turn in the queue by rank."""
    FIXED = "fixed"          # a point: Location(x, y), Centre(x, y), Pin(k, x, y), Polar(r, a)
    EDGE = "edge"            # a distance along an edge, a run or a rim
    SEARCHED = "searched"    # anything with a freedom left

    @property
    def decided(self) -> bool:
        return self is not Freedom.SEARCHED
```

In `layout.py`, add `freedom: Freedom = Freedom.SEARCHED` to `PlaceIntent`
(import it from `.values`), and set it in `place()` where `priority` is derived:

```python
        if decided:
            freedom = Freedom.FIXED if (at is not None or center is not None) else Freedom.EDGE
        else:
            freedom = Freedom.SEARCHED
```

Pass `freedom=freedom` into the `PlaceIntent(...)` construction.

Change `PlaceIntent.rank` and the queue predicate to ask the freedom:

```python
    @property
    def rank(self):
        if self.freedom is Freedom.FIXED:
            return (RANK_FIXED, self.index)
        if self.freedom is Freedom.EDGE:
            return (RANK_EDGE, self.index)
        return ({"cell": RANK_CELL, "block": RANK_BLOCK}.get(self.kind, RANK_LOOSE), self.index)
```

In `place_ranked`, replace both `obj.priority in (Priority.FIXED, Priority.EDGE)`
tests with `getattr(obj, "freedom", Freedom.FIXED).decided` - `CutoutIntent` and
`KeepoutIntent` have no freedom, and a cutout with a decided place must stay in
the firm queue, so give both intents `freedom: Freedom = Freedom.FIXED` and set
it to `Freedom.SEARCHED` where they are built with `firm = Priority.DEFAULT`:

```python
        firm = Priority.FIXED if not self._cutout_free(k) else Priority.DEFAULT
        intent = KeepoutIntent("keepout %s" % name, k, why, len(self._intents), needs, firm,
                               Freedom.FIXED if not self._cutout_free(k) else Freedom.SEARCHED)
```

and the same for `CutoutIntent`. Then `place_ranked` reads:

```python
            firm = [obj for obj in placements if lo <= obj.rank[0] <= hi and obj.freedom.decided]
            ...
            pending = [obj for obj in placements if lo <= obj.rank[0] <= hi and not obj.freedom.decided]
```

In `_settle`, replace `if i.priority in (Priority.FIXED, Priority.EDGE):` with
`if i.freedom.decided:` and the findings line with:

```python
                plan.findings.append("%s (%s): %s" % (i.key, i.freedom.value, why))
```

and the returned `Step` keeps `i.priority` for now.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_freedom.py tests/test_at.py tests/test_order.py tests/test_relative.py tests/test_round.py tests/test_shaped.py tests/test_cutouts.py tests/test_keepouts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/values.py src/placemat/layout.py tests/test_freedom.py
git commit -m "Freedom: whether a position is decided, derived from the place given"
```

---

## Task 3: Copper freedom, derived from the endpoints

**Files:**
- Modify: `src/placemat/layout.py:275-290,1517-1528,1735-1760`
- Test: `tests/test_copper.py`

**Interfaces:**
- Consumes: `Freedom` from Task 2.
- Produces: `CopperIntent.freedom`, `CopperIntent.owners`; `Board._derive_copper_freedom()` called at the top of `resolve()`; `_copper_intent` no longer raises on a searched reference.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_copper.py
from placemat.values import Freedom


def _two_parts(width=60, height=60):
    return board_geometry([footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("A", "GND")),
                           footprint("R1", 30, 10, w=2, h=1, inst="r1", nets=("GND", "C"))],
                          width=width, height=height)


def test_copper_between_decided_parts_is_fixed():
    b = Board(_two_parts(), edge_margin=1.0)
    b.size(width=60, height=60)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"), at=Location(30, 10))
    c = b.track(Net("GND"), [PadRef(Part("u1"), "GND"), PadRef(Part("r1"), "GND")], layer=CopperLayer.F)
    b.resolve()
    assert c.freedom is Freedom.FIXED


def test_copper_naming_a_searched_part_is_searched():
    b = Board(_two_parts(), edge_margin=1.0)
    b.size(width=60, height=60)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"))                                       # searched
    c = b.track(Net("GND"), [PadRef(Part("u1"), "GND"), PadRef(Part("r1"), "GND")], layer=CopperLayer.F)
    b.resolve()
    assert c.freedom is Freedom.SEARCHED


def test_copper_declared_before_its_part_is_still_judged_correctly():
    """The old check ran at declaration time and could not see a placement
    declared later, so it judged against an incomplete list."""
    b = Board(_two_parts(), edge_margin=1.0)
    b.size(width=60, height=60)
    c = b.track(Net("GND"), [PadRef(Part("u1"), "GND"), PadRef(Part("r1"), "GND")], layer=CopperLayer.F)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"))                                       # declared AFTER the copper
    b.resolve()
    assert c.freedom is Freedom.SEARCHED


def test_copper_at_literal_coordinates_is_fixed_and_becomes_an_obstacle():
    """board.via(net, Location(x, y)) reserves its spot with nothing to
    remember: a searched part's pad must clear it."""
    g = _two_parts()
    b = Board(g, edge_margin=1.0)
    b.size(width=60, height=60)
    v = b.via(Net("GND"), Location(30.0, 30.0))
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"))
    plan = b.resolve()
    assert v.freedom is Freedom.FIXED
    placed = plan.placement("r1")
    assert placed is not None
    # the via is copper on the board by the time r1 is searched
    assert any(c.net == "GND" and c.kind == "through" for c in plan.occupancy.copper)


def test_naming_a_searched_part_no_longer_raises():
    b = Board(_two_parts(), edge_margin=1.0)
    b.size(width=60, height=60)
    b.place(Part("r1"))
    b.track(Net("GND"), [PadRef(Part("r1"), "GND"), Location(40, 40)], layer=CopperLayer.F)
    b.resolve()          # no ValueError
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_copper.py -x -q -k "freedom or literal or no_longer_raises"`
Expected: FAIL with `AttributeError: 'CopperIntent' object has no attribute 'freedom'`

- [ ] **Step 3: Write minimal implementation**

In `layout.py`, extend `CopperIntent`:

```python
@dataclass
class CopperIntent:
    key: str
    net: str
    priority: Priority
    plan: object
    refs: tuple = ()
    why: str = ""
    index: int = 0
    bridge: bool = False
    owners: frozenset = frozenset()          # refdes its endpoints belong to
    freedom: Freedom = Freedom.FIXED         # derived in resolve(), once every declaration is in

    @property
    def rank(self):
        return (RANK_FIXED_COPPER if self.freedom.decided else RANK_COPPER, self.index)
```

`_copper_intent` records the owners and stops raising:

```python
    def _copper_intent(self, key, net, priority, plan, refs, why, bridge=False):
        name = self.geometry.require_net(net)
        pads = tuple(self._pad_ref(r) for r in refs)
        ci = CopperIntent(key, name, priority, plan, tuple(refs), why, len(self._copper), bridge,
                          frozenset(owner for owner, *_ in pads))
        self._copper.append(ci)
        return ci
```

Add the derivation and call it first in `resolve()`:

```python
    def _derive_copper_freedom(self):
        """Copper whose every endpoint belongs to an item nothing will move is
        planned before the search and becomes an obstacle to it. Derived here,
        once every declaration is in: at declaration time a placement made
        later is invisible."""
        searched = set()
        for i in self._placements():
            if i.freedom.decided:
                continue
            fps = i.item.members if i.kind == "cell" else (
                [i.item.anchor] + [fp for fp, _ in i.item.satellites] if i.kind == "block" else [i.item])
            searched |= {fp.ref for fp in fps}
        for c in self._copper:
            c.freedom = Freedom.SEARCHED if (c.owners & searched) else Freedom.FIXED
```

and in `resolve()`, immediately after `plan = Plan(...)`:

```python
        self._derive_copper_freedom()
        fixed_copper = [c for c in self._copper if c.freedom.decided]
        other_copper = [c for c in self._copper if not c.freedom.decided]
```

replacing the two `c.priority is Priority.FIXED` comprehensions. In
`_plan_copper`, the `ctx.fixed_tracks` guard becomes:

```python
        if any(c.freedom.decided for c in intents):
            ctx.fixed_tracks += [op for op in ops]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_copper.py tests/test_bridging.py tests/test_write_copper.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_copper.py
git commit -m "Copper freedom is derived from its endpoints, not declared"
```

---

## Task 4: Priority loses FIXED and EDGE

**Files:**
- Modify: `src/placemat/values.py:162-179`, `src/placemat/layout.py`, `src/placemat/copper.py:206-216`
- Test: `tests/test_priority.py`, and every test that names `Priority.FIXED`/`EDGE`

**Interfaces:**
- Consumes: `Freedom` from Tasks 2-3.
- Produces: `Priority` with HIGH/DEFAULT/LOW only, `rank` = `{high: 2, default: 1, low: 0}`; `place()` raises a named error for `Priority.FIXED`.

- [ ] **Step 1: Write the failing test**

```python
# rewrite tests/test_priority.py's header tests; add:
import pytest

from placemat.values import Freedom, Priority


def test_priority_holds_only_what_a_script_may_say():
    assert [p.value for p in Priority] == ["high", "default", "low"]
    assert Priority.HIGH.rank > Priority.DEFAULT.rank > Priority.LOW.rank


def test_freedom_is_not_a_priority():
    assert not hasattr(Priority, "FIXED") and not hasattr(Priority, "EDGE")
    assert Freedom.FIXED.value == "fixed" and Freedom.EDGE.value == "edge"


def test_a_priority_on_a_decided_position_is_still_refused():
    fps = [footprint("J1", 10, 10, inst="j1")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    with pytest.raises(ValueError) as e:
        b.place(Part("j1"), at=Location(20, 20), priority=Priority.HIGH)
    assert "has nothing to order" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_priority.py -x -q -k "holds_only or not_a_priority"`
Expected: FAIL - `Priority` still has five members

- [ ] **Step 3: Write minimal implementation**

`values.py`:

```python
class Priority(str, Enum):
    """How firm a declaration is, as the SCRIPT says it. Never derived and
    never auto-assigned.

    For a placement it orders the searched items above the rank the placer
    works out: HIGH goes before the rest, LOW after them. Whether a position
    is decided is a different question, answered by `Freedom`.

    For copper it decides who passes under at a crossing: the lower priority
    track bridges. When a track is planned - before the search or after it -
    is `Freedom` again, derived from its endpoints."""
    HIGH = "high"
    DEFAULT = "default"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"high": 2, "default": 1, "low": 0}[self.value]
```

In `layout.py`, remove every remaining `Priority.FIXED` / `Priority.EDGE`:

- `CutoutIntent`/`KeepoutIntent`: drop the `priority` field entirely, keep `freedom`.
- `settle_cutout`/`settle_keepout`: `Step(intent.key, "cutout", ...)` takes no
  priority; give `Step.priority` a default of `None`.
- `place()`: the `decided`/`priority` block becomes

```python
        source = "auto" if priority is None else "script"
        if decided:
            freedom = Freedom.FIXED if (at is not None or center is not None) else Freedom.EDGE
        else:
            freedom = Freedom.SEARCHED
        if priority is not None and decided:
            raise ValueError("%s: the declaration decided this position, so the item goes down "
                             "before anything searched and priority=%s has nothing to order; drop "
                             "the priority, or drop the position to have it searched"
                             % (key, priority.value))
        priority = priority or Priority.DEFAULT
```

  and the three "an edge item with no distance along it is free to slide"
  guards are deleted: a script can no longer ask for FIXED or EDGE at all.
- `_plan_copper`'s `entries` keep `c.priority.rank`.
- `_settle`'s decided branch already keys on `i.freedom.decided`.

`copper.py`'s `resolve_bridges` docstring stops saying "FIXED"; the
`fixed_tracks` finding becomes:

```python
                findings.append("%s crosses %s on %s at (%.2f, %.2f), which was planned before the "
                                "search, and may not bridge" % (entries[i][0].net, ft.net,
                                                                ft.layer.value, pt[0], pt[1]))
```

Update every test that names `Priority.FIXED` or `Priority.EDGE` to use
`Freedom` (or to drop the argument, since a decided position derives it).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS except the pre-existing `test_version.py` editable-metadata failure

- [ ] **Step 5: Commit**

```bash
git add src/placemat tests
git commit -m "Priority holds only what a script may say"
```

---

## Task 5: The rank replaces the tier

**Files:**
- Modify: `src/placemat/layout.py:34,2054-2091,2272-2296`
- Test: `tests/test_priority.py`

**Interfaces:**
- Consumes: `ranking.rank_scores`, `ranking.pin_count` from Task 1; `Board.settings` from the placemat.toml plan.
- Produces: `Board._rank(occ)` setting `self._rank_score: dict`, `self._rank_of: dict` (key -> 1-based position), `self._rank_note: dict`; `_next_to_place` sorted by `(-script_tier, -score, -pull, -area, key)`. `_CRITICAL_SHARE` and `_weigh` are gone.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_priority.py - the body, rewritten
"""A searched item's place in the queue is worked out from what it is: how
much board its courtyard needs and how many pins it has, against the rest of
this board. The script may say otherwise. Either way the step says the rank
and the numbers behind it."""
import pytest

from placemat.layout import Board
from placemat.values import Cell, Freedom, Location, Part, Priority
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    nets = ["N%d" % i for i in range(40)]
    fps = [footprint("U1", 10, 10, w=14, h=14, cell="mcu", inst="mcu.u", nets=("N0", "N1"))]
    fps += [footprint("C%d" % i, 30 + i, 10, w=1, h=0.5, cell="mcu", inst="mcu.c%d" % i,
                      nets=("N%d" % (2 + i), "GND")) for i in range(8)]
    fps += [footprint("J1", 60, 60, w=8, h=3, inst="j1", nets=("N0", "N2")),
            footprint("J2", 60, 70, w=8, h=3, inst="j2", nets=("N1", "N3")),
            footprint("R1", 80, 80, w=2, h=1, inst="r1", nets=("N9", "GND")),
            footprint("R2", 80, 85, w=2, h=1, inst="r2", nets=("N9", "N30"))]
    return Board(board_geometry(fps, cells=["mcu"], width=80, height=80), edge_margin=1.0, **kw)


def test_the_big_complex_cell_goes_first_and_the_lone_passive_goes_last():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Part("j2"), at=Location(40, 75))
    b.place(Cell("mcu"))
    b.place(Part("r1"))
    b.place(Part("r2"))
    plan = b.resolve()
    order = [s.item for s in plan.steps if s.item in ("mcu", "r1", "r2")]
    assert order[0] == "mcu"


def test_the_step_says_the_rank_and_the_two_measurements():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Cell("mcu"))
    b.place(Part("r1"))
    note = b.resolve().step("mcu").note
    assert "rank 1/" in note and "mm2" in note and "pins" in note


def test_no_percentage_of_the_board_appears_in_a_step():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Cell("mcu"))
    b.place(Part("r1"))
    for s in b.resolve().steps:
        assert "of the board" not in s.note


def test_a_large_sparse_part_outranks_a_small_well_connected_one():
    """The case that stranded two power inductors, a flag tab and a TVS: a
    big part with two pins must not wait behind a shelf of passives that
    happen to sit on a busy net."""
    fps = [footprint("L1", 10, 10, w=6, h=5, inst="l1", nets=("SW", "VOUT"))]
    fps += [footprint("C%d" % i, 30 + i * 2, 40, w=1, h=0.5, inst="c%d" % i, nets=("BUS", "GND"))
            for i in range(10)]
    fps += [footprint("U1", 50, 10, w=4, h=4, inst="u1", nets=("SW", "BUS"))]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=1.0)
    b.place(Part("u1"), at=Location(50, 10))
    b.place(Part("l1"))
    for i in range(10):
        b.place(Part("c%d" % i))
    plan = b.resolve()
    order = [s.item for s in plan.steps if s.kind == "part" and s.item != "u1"]
    assert order[0] == "l1", order


def test_the_script_may_say_otherwise_and_the_step_says_so():
    b = make_board()
    b.place(Part("j1"), at=Location(40, 5))
    b.place(Cell("mcu"), priority=Priority.LOW)
    b.place(Part("r1"), priority=Priority.HIGH)
    plan = b.resolve()
    assert plan.step("mcu").priority is Priority.LOW and "script: low" in plan.step("mcu").note
    assert plan.step("r1").priority is Priority.HIGH and "script: high" in plan.step("r1").note
    order = [s.item for s in plan.steps if s.item in ("mcu", "r1")]
    assert order[0] == "r1"


def test_the_rank_weights_come_from_the_settings():
    from placemat.settings import Settings
    fps = [footprint("BIG", 10, 10, w=8, h=8, inst="big", nets=("A", "B")),
           footprint("MANY", 40, 10, w=2, h=2, inst="many",
                     nets=tuple("N%d" % i for i in range(2))),
           footprint("J1", 60, 60, inst="j1", nets=("A", "N0"))]
    area_only = Board(board_geometry(fps, width=80, height=80), edge_margin=1.0,
                      settings=Settings(rank_area=1.0, rank_pins=0.0))
    area_only.place(Part("j1"), at=Location(40, 5))
    area_only.place(Part("big"))
    area_only.place(Part("many"))
    order = [s.item for s in area_only.resolve().steps if s.item in ("big", "many")]
    assert order[0] == "big"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_priority.py -x -q`
Expected: FAIL - the step note still says `priority default (auto: ... of the board ...)`

- [ ] **Step 3: Write minimal implementation**

Delete `_CRITICAL_SHARE` (`layout.py:34`) and replace `_weigh` with `_rank`:

```python
    def _rank(self, occ: Occupancy):
        """Every searched item's place in the queue, from what it is: the
        courtyard area it needs and its pin count, both against the rest of
        this board's searched items. Static - a rank says what a part is, not
        what the board looks like at the moment it is reached."""
        from .ranking import pin_count, rank_scores
        self._rank_score, self._rank_of, self._rank_note = {}, {}, {}
        searched = [i for i in self._placements() if not i.freedom.decided]
        if not searched:
            return

        def measure(i):
            if i.kind == "cell":
                area = i.item.courtyard_box.area
                parts = list(i.item.members)
            elif i.kind == "block":
                parts = [i.item.anchor] + [fp for fp, _ in i.item.satellites]
                area = sum(fp.courtyard_box.area for fp in parts)
            else:
                parts = [i.item]
                area = i.item.courtyard_box.area
            return area, sum(pin_count(fp) for fp in parts)

        m = {i.key: measure(i) for i in searched}
        scores = rank_scores(m, self.settings.rank_area, self.settings.rank_pins)
        order = sorted(scores, key=lambda k: (-scores[k], k))
        n = len(order)
        by_area = sorted(m, key=lambda k: -m[k][0])
        by_pins = sorted(m, key=lambda k: -m[k][1])
        for position, key in enumerate(order, start=1):
            area, pins = m[key]
            self._rank_score[key] = scores[key]
            self._rank_of[key] = position
            self._rank_note[key] = "rank %d/%d (%.1f mm2, %s of %d; %d pins, %s)" % (
                position, n, area, _ordinal(by_area.index(key) + 1), n,
                pins, _ordinal(by_pins.index(key) + 1))
```

with a small helper beside `_fmt`:

```python
def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))
```

In `resolve()`, `self._weigh(occ)` becomes `self._rank(occ)`.

`place_one`'s note block becomes:

```python
            if not obj.freedom.decided:
                tag = self._rank_note.get(obj.key, "")
                if obj.priority_source == "script":
                    tag += " (script: %s)" % obj.priority.value
                if obj.required:
                    tag += ", required"
                step.note = (tag + "; " + step.note) if step.note else tag
```

`_next_to_place`:

```python
    def _next_to_place(self, pending: list, occ: Occupancy, placed: set):
        """Which searched item goes next: the script's tier first, then the
        rank (what the item IS), then the strongest pull toward what is
        already placed, then the largest. Pull is a TIE-BREAK: it measures
        net fan-out, which tracks pin count and bus membership rather than
        how hard an item is to place, so it decides between items the rank
        cannot separate - the shelf of identical passives - and nothing
        else."""
        def measure(obj):
            parts = obj.item.members if obj.kind == "block" else (obj.item,)
            area = sum(s.box.area for it in parts for s in occ._geometry(it).shapes
                       if s.kind == "courtyard")
            pull = sum(w for it in parts for _, _, w in self._targets(it, occ, placed))
            return self._rank_score.get(obj.key, 0.0), pull, area

        scored = sorted(((measure(o), o) for o in pending),
                        key=lambda m: (-m[1].priority.rank, -m[0][0], -m[0][1], -m[0][2], m[1].key))
        (score, pull, area), obj = scored[0]
        why = "next: %s" % self._rank_note.get(obj.key, "largest (%.0f mm2)" % area)
        return obj, why
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_priority.py tests/test_order.py tests/test_pockets.py tests/test_blocks.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_priority.py
git commit -m "A rank orders the searched items; _CRITICAL_SHARE is gone"
```

---

## Task 6: required=

**Files:**
- Modify: `src/placemat/layout.py:1074-1226,1812-1850,2259-2270`
- Test: `tests/test_critical.py`

**Interfaces:**
- Consumes: `Freedom` from Task 2.
- Produces: `place(..., required: bool = False)`; `PlaceIntent.required`; `CriticalUnplaced` raised for a required searched item; a required decided item's collision raises `PlacementCollision` even under `keep_going`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_critical.py - rewritten
"""`required=True` says that failing to place this item stops the run. It is
independent of the rank and of whether the position is decided: placemat never
decides on its own that a failure is fatal."""
import pytest

from placemat.layout import Board, CriticalUnplaced, PlacementCollision
from placemat.values import Cell, Location, Part
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    fps = [footprint("U1", 10, 10, w=30, h=30, cell="mcu", inst="mcu.u", nets=("A", "B")),
           footprint("J1", 50, 50, w=8, h=3, inst="j1", nets=("A", "C")),
           footprint("R1", 60, 60, inst="r1", nets=("B", "C")),
           footprint("R2", 62, 62, inst="r2", nets=("C", "D"))]
    return Board(board_geometry(fps, cells=["mcu"], width=40, height=40), edge_margin=1.0, **kw)


def test_a_required_item_with_no_place_stops_the_resolve_with_the_free_pockets():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))       # mid-board: the 30 x 30 cell cannot fit
    b.place(Cell("mcu"), required=True)
    b.place(Part("r1"))
    b.place(Part("r2"))
    with pytest.raises(CriticalUnplaced) as e:
        b.resolve()
    err = e.value
    assert err.key == "mcu" and "30.0 x 30.0" in str(err) and "free" in str(err).lower()
    assert err.plan is not None and err.plan.placement("j1") is not None
    assert all(s.item not in ("r1", "r2") for s in err.plan.steps)


def test_an_item_that_is_not_required_is_left_off_and_the_run_carries_on():
    """placemat no longer decides for itself that a failure is fatal."""
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Cell("mcu"))                            # not required
    b.place(Part("r1"))
    plan = b.resolve()
    assert plan.placement("mcu") is None
    assert any(f.startswith("mcu") for f in plan.findings)
    assert plan.placement("r1") is not None


def test_keep_going_downgrades_a_required_searched_item_to_a_finding():
    b = make_board(keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Cell("mcu"), required=True)
    b.place(Part("r1"))
    plan = b.resolve()
    assert any(f.startswith("mcu") for f in plan.findings) and plan.placement("r1") is not None


def test_a_required_decided_item_that_collides_stops_even_under_keep_going():
    """A required item is not negotiable, and --keep-going does not make it so."""
    fps = [footprint("J1", 10, 10, w=8, h=8, inst="j1"), footprint("J2", 30, 10, w=8, h=8, inst="j2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("j2"), at=Location(20, 20), required=True)
    with pytest.raises(PlacementCollision) as e:
        b.resolve()
    assert any("j2" in c for c in e.value.collisions)


def test_a_decided_item_that_is_not_required_is_still_only_a_finding_under_keep_going():
    fps = [footprint("J1", 10, 10, w=8, h=8, inst="j1"), footprint("J2", 30, 10, w=8, h=8, inst="j2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("j2"), at=Location(20, 20))
    assert any("j2" in f for f in b.resolve().findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_critical.py -x -q`
Expected: FAIL with `TypeError: Board.place() got an unexpected keyword argument 'required'`

- [ ] **Step 3: Write minimal implementation**

Add `required: bool = False` to `PlaceIntent` and to `place()`'s signature
(keyword-only, beside `why=`), pass it through, and document it in the
docstring. Then in `place_one`:

```python
            if step.placement is None and obj.required and not self.keep_going:
                raise CriticalUnplaced(obj.key, self._no_place_report(occ, obj, step), plan)
```

and in `place_ranked`, after the firm loop:

```python
            collisions = [f for f in plan.findings
                          if f.split(" ")[1] in ("(fixed):", "(edge):", "(cutout):", "(keepout):")]
            required_keys = {o.key for o in placements if getattr(o, "required", False)}
            demanded = [c for c in collisions if c.split(" ")[0] in required_keys]
            if demanded or (collisions and not self.keep_going):
                raise PlacementCollision(demanded or collisions)
```

`_no_place_report`'s first line changes from "(HIGH priority)" to "(required)":

```python
        return ("%s (required) found no place for its %.1f x %.1f envelope on the %s face: %s. "
                ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_critical.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_critical.py
git commit -m "required=: the script says when a failure to place is fatal"
```

---

## Task 7: What the step line and run.json say

**Files:**
- Modify: `src/placemat/layout.py:308-318,2622-2634`, `src/placemat/runner.py:247-255`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: Tasks 2-6.
- Produces: `Step.freedom`, `Step.rank`, `Step.rank_of`; `STEP_HEADER` with a `place` column; `rec.steps` entries carrying `freedom`, `priority` (null when decided) and `rank`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_report.py

def test_a_step_records_its_freedom_and_a_decided_placement_has_no_priority():
    from placemat.layout import Board
    from placemat.values import Location, Part
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("J1", 10, 10, inst="j1", nets=("A", "B")),
           footprint("R1", 30, 10, inst="r1", nets=("B", "C"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("r1"))
    plan = b.resolve()
    assert plan.step("j1").freedom.value == "fixed"
    assert plan.step("j1").priority is None
    assert plan.step("r1").freedom.value == "searched"
    assert plan.step("r1").priority is not None and plan.step("r1").rank == 1


def test_the_step_header_names_the_place_column():
    from placemat.layout import STEP_HEADER
    assert "place" in STEP_HEADER and "priority" not in STEP_HEADER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_report.py -x -q -k "freedom or header"`
Expected: FAIL with `AttributeError: 'Step' object has no attribute 'freedom'`

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass
class Step:
    item: str
    kind: str
    priority: Priority | None = None      # None for a decided placement: it has none
    placement: Placement | None = None
    moved_mm: float = 0.0
    note: str = ""
    why: str = ""
    ops: int = 0
    freedom: Freedom | None = None        # None for copper steps and notes
    rank: int | None = None
    rank_of: int | None = None
```

`_settle` builds the decided step with `priority=None, freedom=i.freedom` and
the searched one with `priority=i.priority, freedom=Freedom.SEARCHED,
rank=self._rank_of.get(i.key), rank_of=len(self._rank_of)`.

```python
STEP_HEADER = "%-28s %-6s %-11s %s" % ("item", "kind", "place", "result")


def _fmt(s: Step) -> str:
    place = s.freedom.value if (s.freedom and s.freedom.decided) else (
        "rank %d/%d" % (s.rank, s.rank_of) if s.rank else (s.priority.value if s.priority else ""))
    if s.placement is None:
        return "%-28s %-6s %-11s %s" % (s.item, s.kind, place, s.note)
    out = "%-28s %-6s %-11s at %s rot %g face %s" % (s.item, s.kind, place,
                                                     _loc(s.placement.location),
                                                     s.placement.rotation, s.placement.face.value)
    return out + ("  " + s.note if s.note else "")
```

`runner.py`'s record:

```python
        rec.steps = [{"item": s.item, "kind": s.kind,
                      "freedom": s.freedom.value if s.freedom else None,
                      "priority": s.priority.value if s.priority else None,
                      "rank": s.rank, "rank_of": s.rank_of,
                      "note": s.note, "why": s.why,
                      "moved_mm": round(s.moved_mm, 3), "ops": s.ops} for s in plan.steps]
```

Copper steps pass `freedom=c.freedom` so the record says which batch planned
each one.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS except the pre-existing `test_version.py` failure

- [ ] **Step 5: Commit**

```bash
git add src/placemat tests
git commit -m "A step says its freedom and its rank, and copper says its batch"
```

---

## Task 8: Documentation

**Files:**
- Modify: `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`
- Test: `tests/test_ranking.py`

**Interfaces:** no new code interface.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ranking.py
from pathlib import Path


def test_the_api_reference_documents_the_rank_and_required():
    doc = Path("skills/placemat/references/api.md").read_text()
    for phrase in ("required=", "rank", "Freedom"):
        assert phrase in doc, phrase
    assert "HIGH also needs a real share of the board" not in doc
    assert "Priority.FIXED` copper is planned" not in doc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ranking.py -x -q -k "api_reference"`
Expected: FAIL - the removed sentences are still there

- [ ] **Step 3: Write minimal implementation**

In `api.md`:

- Replace the paragraph ending "HIGH also needs a real share of the board" with:

  > Unless the script says, a searched item's place in the queue is a **rank**:
  > how much board its courtyard needs and how many pins it has, both against
  > the rest of this board's searched items, weighted by `[rank] area` and
  > `[rank] pins`. Big and complex things go down first and the small ones are
  > fitted round them. Every step prints `rank 4/64 (31.5 mm2, 12th of 64; 2
  > pins, 41st)`. `priority=Priority.HIGH` or `LOW` is a tier above the rank,
  > for when the rank is wrong.

- Add, under Placement:

  > **`required=True`** says that failing to place this item stops the run,
  > with the board as it stood and the biggest free rectangles on its face. It
  > is independent of the rank and of whether the position is decided, and a
  > required item is not negotiable even under `--keep-going`. Nothing else
  > stops a run by itself.

- In the copper section, replace "All take `priority=`. `Priority.FIXED` copper
  is planned before everything searched parts and becomes an obstacle to them,
  and may not reference a searched part." with:

  > All take `priority=`, which decides only who passes under where two tracks
  > of different nets cross. WHEN a piece of copper is planned is derived, not
  > declared: copper whose every endpoint belongs to something nothing will
  > move - a FIXED or EDGE part, a cell already down, or plain coordinates - is
  > planned before the search and becomes an obstacle to it, so
  > `board.via(net, Location(x, y))` reserves its spot with nothing to
  > remember. Copper naming a searched part is planned after the search.

- In the degrees-of-freedom paragraph, add: "A place with no freedom left is
  `fixed` or `edge` and a place with one is searched; that is `Freedom`, and it
  is derived from `at=`, never given."

In `SKILL.md`, replace any instruction to reach for `priority=Priority.HIGH` to
get a big part down early with: "The rank already puts the big, complex items
first. Reach for `priority=` only when the rank is demonstrably wrong, and say
why beside it."

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS except the pre-existing `test_version.py` failure

- [ ] **Step 5: Commit**

```bash
git add skills tests
git commit -m "The API text says rank, Freedom and required"
```

---

## Acceptance criteria

1. `.venv/bin/python -m pytest -q` passes, except the pre-existing
   `test_the_installed_package_reports_that_version_too` failure.
2. `Priority` has exactly HIGH, DEFAULT and LOW; `Freedom` has FIXED, EDGE and
   SEARCHED and is never written by a script.
3. `_CRITICAL_SHARE` does not appear in the source, and no step note contains
   "of the board".
4. A large, sparsely connected part outranks a shelf of small well-connected
   ones (`test_a_large_sparse_part_outranks_a_small_well_connected_one`).
5. Identical passives tie exactly on score, so pull decides between them.
6. `required=True` is the only thing that stops a run for a placement.
7. Copper freedom is derived, including for copper declared before its part.
8. `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`
   returns nothing for every commit made.
