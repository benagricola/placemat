# Occupancy Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer "what copper is at this point", "what is in this box" and "where is the nearest legal via to this pad" from the command line, and let a script place a via at the nearest legal spot with `at=FreeSpot(...)`.

**Architecture:** A pure module, `queries.py`, judges a via candidate and its tail against a board's copper, holes, edge and rule areas, and searches outward from a pad. The command line feeds it a `BoardGeometry` read from a board file; the copper planner feeds the same search a judge built on the live occupancy, so a script's vias see the parts as placed and the copper planned before them.

**Tech Stack:** Python 3.12 stdlib, pcbnew under `kicad/` only.

**Spec:** `docs/superpowers/specs/2026-09-22-occupancy-queries-design.md`

## Global Constraints

- **Zero runtime dependencies**; **pcbnew only under `kicad/`**; **plain ASCII**; **no commit mentions Claude, Anthropic or a session**.
- **No module, part, board or component-type names** in the skill, migration notes or source. Measurements are stated generically.
- **Deterministic**: the search order is fixed - radius, then angle from east, anticlockwise - and no randomness enters.
- **A zone fill of another net is soft**: reported as giving way, never blocking.

## File Structure

- `src/placemat/board_geometry.py` - `CopperItem.drill_mm`; `BoardGeometry.hole_to_hole`, `hole_clearance`.
- `src/placemat/kicad/read.py` - reads both.
- `src/placemat/queries.py` (create) - `ViaVerdict`, `judge_via`, `judge_tail`, `free_spot`, `copper_at`, `copper_in`, and their line/row printers.
- `src/placemat/values.py` - `FreeSpot`.
- `src/placemat/layout.py` - `board.via` accepts `at=FreeSpot(...)`; `_refs_in` follows it.
- `src/placemat/cli.py` - `placemat occupancy`.
- `tests/test_queries.py` (create), `tests/test_queries_kicad.py` (create), `tests/test_free_spot_script.py` (create).

---

## Task 1: Holes and hole rules on the geometry

**Files:** Modify `src/placemat/board_geometry.py`, `src/placemat/kicad/read.py`. Test `tests/test_queries_kicad.py`.

**Interfaces:** Produces `CopperItem.drill_mm: float = 0.0` (vias), `BoardGeometry.hole_to_hole: float = 0.25`, `BoardGeometry.hole_clearance: float = 0.0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_queries_kicad.py
"""The occupancy queries against pcbnew: the rules they need, read off a real
board, and a spot the search chose that KiCad's DRC accepts."""
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad]


@needs_breakout
def test_the_board_hole_rules_are_read(breakout_pcb):
    import pcbnew
    from placemat.kicad.read import read_board
    ds = pcbnew.LoadBoard(str(breakout_pcb)).GetDesignSettings()
    g = read_board(breakout_pcb)
    assert abs(g.hole_to_hole - pcbnew.ToMM(ds.m_HoleToHoleMin)) < 1e-6
    assert abs(g.hole_clearance - pcbnew.ToMM(ds.m_HoleClearance)) < 1e-6


def test_a_via_reads_its_drill(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    b = pcbnew.CreateEmptyBoard()
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(10), pcbnew.FromMM(10)))
    v.SetWidth(pcbnew.FromMM(0.6))
    v.SetDrill(pcbnew.FromMM(0.3))
    b.Add(v)
    p = tmp_path / "v.kicad_pcb"
    b.Save(str(p))
    (via,) = [c for c in read_board(p).copper if c.kind == "via"]
    assert abs(via.drill_mm - 0.3) < 1e-6
```

- [ ] **Step 2: Run to verify it fails** - `.venv/bin/python -m pytest tests/test_queries_kicad.py -q`: FAIL, no attribute `hole_to_hole`.

- [ ] **Step 3: Implement.** Add the fields with defaults to the two dataclasses. In `read.py`, where a via's `CopperItem` is built pass `drill_mm=mm(obj.GetDrillValue())`; where `BoardGeometry` is built pass `hole_to_hole=mm(ds.m_HoleToHoleMin)` and `hole_clearance=mm(ds.m_HoleClearance)` from `board.GetDesignSettings()`.

- [ ] **Step 4: Run to verify it passes**, then the whole suite.

- [ ] **Step 5: Commit** - "Holes carry their drill, and the board its hole rules"

---

## Task 2: Judging a via

**Files:** Create `src/placemat/queries.py`. Test `tests/test_queries.py`.

**Interfaces:** Produces `ViaVerdict(hard: tuple[str,...], soft: tuple[str,...])` with `.clear -> bool`, and `judge_via(geometry, at: Location, net: str, size: float, drill: float) -> ViaVerdict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_queries.py
"""What is at a point, what is in a box, and where a via may stand. Pure:
synthetic geometry, no KiCad."""
import dataclasses

from placemat import queries
from placemat.board_geometry import CopperItem, RuleArea
from placemat.values import Box, CopperLayer, Location
from tests.fixtures import board_geometry, footprint, rect, track

F, B = CopperLayer.F, CopperLayer.B


def _zone(net, x0, y0, x1, y1, layer=F):
    poly = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    return CopperItem("zone", net, frozenset([layer]), (poly,), Box(x0, y0, x1, y1))


def _via(net, x, y, size=0.6, drill=0.3):
    ring = rect(x, y, size, size)
    return CopperItem("via", net, frozenset([F, B]), (ring,), Box.of_points(ring), drill_mm=drill)


def _geom(copper=(), fps=(), **kw):
    g = board_geometry(list(fps), copper=list(copper), width=40, height=40,
                       extra_nets=("GND", "SIG", "V3"))
    return dataclasses.replace(g, **kw) if kw else g


def test_a_via_within_clearance_of_another_nets_track_is_blocked():
    g = _geom([track("SIG", 20, 5, 20, 35)])
    v = queries.judge_via(g, Location(20.5, 20), "GND", 0.6, 0.3)
    assert not v.clear and any("SIG" in h and "track" in h for h in v.hard)


def test_copper_of_the_vias_own_net_does_not_block():
    g = _geom([track("GND", 20, 5, 20, 35)])
    assert queries.judge_via(g, Location(20.0, 20), "GND", 0.6, 0.3).clear


def test_another_nets_pour_gives_way_rather_than_blocking():
    g = _geom([_zone("V3", 10, 10, 30, 30)])
    v = queries.judge_via(g, Location(20, 20), "GND", 0.6, 0.3)
    assert v.clear and any("V3" in s for s in v.soft)


def test_a_hole_closer_than_hole_to_hole_blocks():
    g = _geom([_via("V3", 20.6, 20)], hole_to_hole=0.25)
    v = queries.judge_via(g, Location(20, 20), "V3", 0.6, 0.3)   # same net: only the hole rule applies
    assert not v.clear and any("hole" in h for h in v.hard)


def test_the_board_edge_closer_than_the_edge_clearance_blocks():
    v = queries.judge_via(_geom(), Location(0.5, 20), "GND", 0.6, 0.3)
    assert not v.clear and any("edge" in h for h in v.hard)


def test_a_rule_area_forbidding_vias_blocks_one_forbidding_tracks_does_not():
    box = ((15.0, 15.0), (25.0, 15.0), (25.0, 25.0), (15.0, 25.0))
    no_vias = RuleArea("keepout a", None, box, frozenset([F, B]), frozenset(["vias"]))
    no_tracks = RuleArea("keepout b", None, box, frozenset([F, B]), frozenset(["tracks"]))
    assert not queries.judge_via(_geom(rule_areas=(no_vias,)), Location(20, 20), "GND", 0.6, 0.3).clear
    assert queries.judge_via(_geom(rule_areas=(no_tracks,)), Location(20, 20), "GND", 0.6, 0.3).clear
```

- [ ] **Step 2: Run to verify it fails** - `ModuleNotFoundError: No module named 'placemat.queries'`.

- [ ] **Step 3: Implement**

```python
# src/placemat/queries.py
"""What is at a point, what is in a box, and where a via may stand.

Pure: a board is a `BoardGeometry`, whichever way it was read. A via joins
every copper layer at one point, so it is judged against every layer; a zone
fill of another net is not an obstacle, because KiCad refills a zone and pulls
it back round a new via, and is reported as giving way instead."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

from .geometry import (circle_polygon, distance_to_boundary, point_in_polygon, point_segment_distance,
                       poly_distance, polys_overlap)
from .values import Box, Location

_HARD = ("pad", "track", "via", "poly")


@dataclass(frozen=True)
class ViaVerdict:
    hard: tuple = ()        # what stops a via standing here
    soft: tuple = ()        # what would give way to it: another net's pour

    @property
    def clear(self) -> bool:
        return not self.hard


def _holes(geometry):
    """Every drilled hole on the board as (centre, diameter, what)."""
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.through and p.drill_mm:
                yield p.box.center, p.drill_mm, "%s pad %s" % (fp.ref, p.number)
        for at, dia in fp.npth:
            yield at, dia, "%s hole" % fp.ref
    for c in geometry.copper:
        if c.kind == "via" and c.drill_mm:
            yield c.box.center, c.drill_mm, "via %s" % c.net


def _edge_rings(geometry):
    return tuple(geometry.board_polygon) or tuple(geometry.outline)


def judge_via(geometry, at: Location, net: str, size: float, drill: float) -> ViaVerdict:
    poly = circle_polygon(at, size / 2.0)
    box = Box(at.x - size / 2.0, at.y - size / 2.0, at.x + size / 2.0, at.y + size / 2.0)
    hard, soft = [], []
    rings = _edge_rings(geometry)
    if rings and not point_in_polygon((at.x, at.y), rings[0]):
        hard.append("off the board")
    elif rings:
        gap = min(distance_to_boundary(poly, r) for r in rings)
        if gap < geometry.edge_clearance - 1e-9:
            hard.append("%.2f mm from the board edge (needs %.2f)" % (gap, geometry.edge_clearance))
    for c in geometry.copper:
        if c.net == net or not c.outlines:
            continue
        reach = geometry.clearance(net, c.net) if (net in geometry.nets and c.net in geometry.nets) \\
            else geometry.default_clearance
        if not box.overlaps(c.box, gap=reach):
            continue
        gap = min(poly_distance(poly, o) for o in c.outlines)
        if gap >= reach - 1e-9:
            continue
        where = "/".join(sorted(l.value for l in c.layers))
        if c.kind == "zone":
            soft.append("the %s pour on %s would give way" % (c.net, where))
        elif c.kind in _HARD:
            hard.append("%.2f mm from %s %s on %s (needs %.2f)" % (gap, c.net or "-", c.kind, where, reach))
    for centre, dia, what in _holes(geometry):
        gap = at.distance(centre) - (drill + dia) / 2.0
        if gap < geometry.hole_to_hole - 1e-9 and gap > -(drill + dia):
            hard.append("hole %.2f mm from the %s hole (needs %.2f)" % (max(gap, 0.0), what, geometry.hole_to_hole))
    for ra in geometry.rule_areas:
        if "vias" in ra.excludes and ra.layers and polys_overlap(poly, ra.polygon):
            hard.append("inside %s, which forbids vias" % ra.base)
    return ViaVerdict(tuple(hard), tuple(dict.fromkeys(soft)))
```

`geometry.circle_polygon` exists; `distance_to_boundary`, `point_in_polygon`, `poly_distance` and `polys_overlap` exist. `BoardGeometry.clearance(a, b)` exists.

- [ ] **Step 4: Run to verify it passes**, then the suite.

- [ ] **Step 5: Commit** - "Where a via may stand: judged against copper, holes, edge and keepouts"

---

## Task 3: The tail, and the search

**Files:** Modify `src/placemat/queries.py`. Test `tests/test_queries.py`.

**Interfaces:** Produces `judge_tail(geometry, start, end, net, width, layer, skip=()) -> tuple[str, ...]`, `Spot(at, distance, tail_layer, tail_mm, soft)`, `free_spot(start: Location, judge, radius=2.0, step=0.05) -> tuple[Spot | None, Counter, int]` where `judge(candidate) -> (reason | None, soft)`, and `via_judge(geometry, start, net, size, drill, width, layer, skip)` building that callable.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_queries.py
def test_a_tail_crossing_another_nets_track_on_its_layer_is_blocked():
    g = _geom([track("SIG", 20, 5, 20, 35)])
    said = queries.judge_tail(g, Location(15, 20), Location(25, 20), "GND", 0.2, F)
    assert said and "SIG" in said[0]
    assert queries.judge_tail(g, Location(15, 20), Location(25, 20), "GND", 0.2, B) == ()


def test_the_search_returns_the_nearest_clear_spot_and_a_tally_of_the_rest():
    blocked = lambda c: ("copper", ()) if c.x < 20.9 else (None, ())
    spot, tally, tried = queries.free_spot(Location(20, 20), blocked, radius=2.0, step=0.1)
    assert spot is not None and spot.at.x >= 20.9
    assert tally["copper"] >= 1 and tried > tally["copper"]


def test_the_search_is_identical_run_twice():
    judge = lambda c: ("edge", ()) if (c.x + c.y) % 0.7 < 0.3 else (None, ())
    a = queries.free_spot(Location(20, 20), judge, radius=1.0, step=0.1)
    b = queries.free_spot(Location(20, 20), judge, radius=1.0, step=0.1)
    assert a[0] == b[0] and a[1] == b[1]


def test_nowhere_within_the_radius_returns_no_spot_and_the_whole_tally():
    spot, tally, tried = queries.free_spot(Location(20, 20), lambda c: ("edge", ()), radius=0.5, step=0.1)
    assert spot is None and tally["edge"] == tried


def test_a_real_search_clears_a_blocking_track():
    g = _geom([track("SIG", 20.5, 5, 20.5, 35, w=0.3)])
    judge = queries.via_judge(g, Location(20, 20), "GND", 0.6, 0.3, 0.2, F)
    spot, tally, _ = queries.free_spot(Location(20, 20), judge, radius=3.0, step=0.1)
    assert spot is not None
    assert queries.judge_via(g, spot.at, "GND", 0.6, 0.3).clear
    assert tally                                # the nearer spots failed, and it says why
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# append to src/placemat/queries.py
def _segment(a: Location, b: Location, width: float):
    """A straight track as a polygon: a rectangle along the segment, capped."""
    dx, dy = b.x - a.x, b.y - a.y
    n = math.hypot(dx, dy) or 1.0
    ox, oy = -dy / n * width / 2.0, dx / n * width / 2.0
    return ((a.x + ox, a.y + oy), (b.x + ox, b.y + oy), (b.x - ox, b.y - oy), (a.x - ox, a.y - oy))


def judge_tail(geometry, start: Location, end: Location, net: str, width: float, layer,
               skip=()) -> tuple:
    """What a straight track from the pad to the via would touch on its layer.
    `skip` names owners whose copper the tail may run over: the source pad."""
    poly = _segment(start, end, width)
    box = Box.of_points(poly)
    out = []
    for c in geometry.copper:
        if c.net == net or layer not in c.layers or c.kind not in _HARD or c.owner in skip:
            continue
        reach = geometry.clearance(net, c.net) if (net in geometry.nets and c.net in geometry.nets) \\
            else geometry.default_clearance
        if not box.overlaps(c.box, gap=reach):
            continue
        gap = min(poly_distance(poly, o) for o in c.outlines)
        if gap < reach - 1e-9:
            out.append("tail %.2f mm from %s %s on %s (needs %.2f)" % (gap, c.net or "-", c.kind, layer.value, reach))
    return tuple(out)


@dataclass(frozen=True)
class Spot:
    at: Location
    distance: float
    soft: tuple = ()


def _kind(reason: str) -> str:
    """A reason's tally bucket: its first word that names a kind of obstacle."""
    for word in ("edge", "board", "hole", "pour", "tail", "forbids", "pad", "track", "via", "poly"):
        if word in reason:
            return {"board": "edge", "forbids": "keepout"}.get(word, word)
    return reason.split()[0]


def free_spot(start: Location, judge, radius: float = 2.0, step: float = 0.05) -> tuple:
    """The nearest candidate the judge passes, walking rings outward from
    `start`: radius first, then angle from east, anticlockwise, so the same
    board always gives the same spot. Returns (spot, tally, tried)."""
    tally, tried = Counter(), 0
    rings = int(round(radius / step))
    for i in range(0, rings + 1):
        r = i * step
        count = 1 if r == 0 else max(8, int(math.ceil(2 * math.pi * r / step)))
        for k in range(count):
            a = 2 * math.pi * k / count
            c = Location(round(start.x + r * math.cos(a), 4), round(start.y - r * math.sin(a), 4))
            tried += 1
            why, soft = judge(c)
            if why is None:
                return Spot(c, round(r, 4), tuple(soft)), tally, tried
            tally[_kind(why)] += 1
    return None, tally, tried


def via_judge(geometry, start: Location, net: str, size: float, drill: float, width: float,
              layer, skip=()):
    """The judge `free_spot` calls for a via of `net` fed from `start` by a
    straight tail on `layer`."""
    def judge(c):
        v = judge_via(geometry, c, net, size, drill)
        if not v.clear:
            return v.hard[0], v.soft
        tail = judge_tail(geometry, start, c, net, width, layer, skip) if c.distance(start) > 1e-9 else ()
        if tail:
            return tail[0], v.soft
        return None, v.soft
    return judge
```

- [ ] **Step 4: Run to verify it passes**, then the suite.

- [ ] **Step 5: Commit** - "The nearest spot a via can stand and be reached, and why the nearer ones failed"

---

## Task 4: What is at a point, and in a box

**Files:** Modify `src/placemat/queries.py`. Test `tests/test_queries.py`.

**Interfaces:** Produces `copper_at(geometry, at) -> dict[layer, list[CopperItem]]`, `nearest_foreign(geometry, at, layer, net) -> float | None`, `copper_in(geometry, box) -> dict[layer, Counter[(net, kind)]]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_queries.py
def test_the_copper_under_a_point_is_named_per_layer():
    g = _geom([_zone("GND", 0, 0, 40, 40, layer=B), track("SIG", 20, 5, 20, 35)])
    at = queries.copper_at(g, Location(20, 20))
    assert [c.net for c in at[F]] == ["SIG"] and [c.net for c in at[B]] == ["GND"]


def test_the_copper_in_a_box_is_counted_by_net_and_kind():
    g = _geom([track("SIG", 20, 5, 20, 35), track("SIG", 22, 5, 22, 35), _via("GND", 21, 20)])
    got = queries.copper_in(g, Box(18, 18, 24, 22))
    assert got[F][("SIG", "track")] == 2 and got[F][("GND", "via")] == 1
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# append to src/placemat/queries.py
def copper_at(geometry, at: Location) -> dict:
    """The copper covering a point, per layer."""
    out = {l: [] for l in geometry.layers}
    for c in geometry.copper:
        b = c.box
        if not (b.left <= at.x <= b.right and b.top <= at.y <= b.bottom):
            continue
        if any(point_in_polygon((at.x, at.y), o) for o in c.outlines):
            for l in c.layers:
                out.setdefault(l, []).append(c)
    return out


def _point_to_polygon(at: Location, poly) -> float:
    """0 inside the polygon, else the distance to its nearest edge."""
    if point_in_polygon((at.x, at.y), poly):
        return 0.0
    n = len(poly)
    return min(point_segment_distance((at.x, at.y), poly[i], poly[(i + 1) % n]) for i in range(n))


def nearest_foreign(geometry, at: Location, layer, net: str):
    """How far the nearest copper of another net is from the point on a layer."""
    best = None
    for c in geometry.copper:
        if c.net == net or layer not in c.layers or not c.outlines:
            continue
        d = min(_point_to_polygon(at, o) for o in c.outlines)
        best = d if best is None or d < best else best
    return best


def copper_in(geometry, box: Box) -> dict:
    """The copper inside a box, counted by (net, kind) per layer."""
    out = {l: Counter() for l in geometry.layers}
    region = ((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom))
    for c in geometry.copper:
        if not c.box.overlaps(box):
            continue
        if any(polys_overlap(region, o) for o in c.outlines):
            for l in c.layers:
                out.setdefault(l, Counter())[(c.net, c.kind)] += 1
    return out
```


- [ ] **Step 4: Run to verify it passes**, then the suite.

- [ ] **Step 5: Commit** - "What copper is at a point and in a box, per layer"

---

## Task 5: `placemat occupancy`

**Files:** Modify `src/placemat/cli.py`, `src/placemat/queries.py` (printers). Test `tests/test_queries_kicad.py`.

**Interfaces:** `placemat occupancy <board|script> (--at X,Y | --box X0,Y0,X1,Y1 | --via-near PART.PAD) [--net] [--size] [--drill] [--layer] [--radius] [--step] [--json]`. Exit 1 when `--via-near` finds nothing.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_queries_kicad.py
@needs_breakout
def test_via_near_returns_a_spot_kicads_drc_accepts(breakout_pcb, tmp_path):
    """The search's answer is only worth having if KiCad agrees with it."""
    import json
    import shutil
    import pcbnew
    from placemat.cli import main
    from placemat.kicad.drc import run_drc
    from placemat.kicad.read import read_board
    pcb = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, pcb)
    shutil.copy(breakout_pcb.with_suffix(".kicad_pro"), tmp_path / "layout.kicad_pro")
    g = read_board(pcb)
    fp = next(f for f in g.footprints if f.pads and any(p.net == "GND" for p in f.pads))
    pad = next(p for p in fp.pads if p.net == "GND")
    import io, contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["occupancy", str(pcb), "--via-near", "%s.%s" % (fp.inst, pad.number), "--json"]) == 0
    spot = json.loads(out.getvalue())["spot"]
    before = run_drc(pcb, tmp_path / "before.json").real
    b = pcbnew.LoadBoard(str(pcb))
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(spot["at"][0]), pcbnew.FromMM(spot["at"][1])))
    v.SetWidth(pcbnew.FromMM(g.netclasses["GND"].via_diameter))
    v.SetDrill(pcbnew.FromMM(g.netclasses["GND"].via_drill))
    v.SetNet(b.FindNet("GND"))
    b.Add(v)
    b.Save(str(pcb))
    after = run_drc(pcb, tmp_path / "after.json").real
    assert after == before, "the via the search chose broke a rule: %s -> %s" % (before, after)


@needs_breakout
def test_at_names_what_is_under_a_point(breakout_pcb, capsys):
    from placemat.cli import main
    from placemat.kicad.read import read_board
    g = read_board(breakout_pcb)
    pad = next(p for fp in g.footprints for p in fp.pads if p.net)
    c = pad.box.center
    assert main(["occupancy", str(breakout_pcb), "--at", "%.3f,%.3f" % (c.x, c.y)]) == 0
    assert pad.net in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails** - argparse rejects `occupancy`.

- [ ] **Step 3: Implement** the parser block and `cmd_occupancy`: read the board (`find_board` for a script), bind its settings, then

- `--at`: for each layer in stackup order print the copper there (`kind net owner`) or `nothing`, the nearest foreign copper, then the verdict of `judge_via` for the net found there (or the default class) with each hard and soft line.
- `--box`: per layer, `net kind count` lines, largest first.
- `--via-near PART.PAD`: find the footprint by instance or refdes and the pad by number; net = `--net` or the pad's; size/drill = the flags or the net's class; layer = `--layer` or the pad's first layer; run `free_spot(pad centre, via_judge(..., skip={footprint ref}), radius, step)`; print the spot, its distance, the tail length, the soft lines and the tally; `--json` prints `{"spot": {"at": [x, y], "distance": d, "soft": [...]}, "tally": {...}, "tried": n}` with `spot` null when none. Exit 1 when none.

- [ ] **Step 4: Run to verify it passes**, then the suite.

- [ ] **Step 5: Commit** - "placemat occupancy: what is here, and where a via can go"

---

## Task 6: `FreeSpot` in a script

**Files:** Modify `src/placemat/values.py`, `src/placemat/layout.py`, `src/placemat/__init__.py` (export). Test `tests/test_free_spot_script.py`.

**Interfaces:** Produces `FreeSpot(near, radius=2.0, step=0.05, layer=None)`; `board.via(net, at=FreeSpot(...))` resolves it in copper planning.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_free_spot_script.py
"""A via written at the nearest legal spot to a pad, resolved when the pad's
part is placed, against the copper planned before it. Pure."""
from placemat import FreeSpot
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("GND", "SIG")),
           footprint("R1", 20, 26, w=2, h=1, inst="r1", nets=("SIG", "V3"))]
    return Board(board_geometry(fps, width=40, height=40, extra_nets=("GND",)), edge_margin=0.5)


def test_a_free_spot_resolves_to_a_clear_position_near_its_pad():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    (via,) = [c for c in plan.copper if type(c).__name__ == "Via"]
    pad = plan.occupancy.pad_location("U1", "1")
    assert via.at.distance(pad) <= 2.0 + 1e-6
    assert not any("via" in f and "nowhere" in f for f in plan.findings)


def test_a_second_via_near_the_same_pad_lands_clear_of_the_first():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    ref = PadRef(Part("u1"), "GND")
    b.via(Net("GND"), at=FreeSpot(near=ref), why="tap one")
    b.via(Net("SIG"), at=FreeSpot(near=PadRef(Part("u1"), "SIG")), why="tap two")
    plan = b.resolve()
    vias = [c for c in plan.copper if type(c).__name__ == "Via"]
    assert len(vias) == 2
    gap = vias[0].at.distance(vias[1].at) - (vias[0].size + vias[1].size) / 2.0
    assert gap >= 0.2 - 1e-6                       # the class clearance between the two nets


def test_a_free_spot_with_nowhere_to_go_is_a_finding_and_draws_nothing():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND"), radius=0.05), why="tap")
    plan = b.resolve()
    assert not [c for c in plan.copper if type(c).__name__ == "Via"]
    assert any("nowhere" in f for f in plan.findings)
```

- [ ] **Step 2: Run to verify it fails** - cannot import `FreeSpot`.

- [ ] **Step 3: Implement.** In `values.py`:

```python
@dataclass(frozen=True)
class FreeSpot:
    """The nearest point to a pad where a via can stand and be reached by a
    straight tail, resolved when the pad's part is placed, against the copper
    planned before it."""
    near: object
    radius: float = 2.0
    step: float = 0.05
    layer: object = None
```

Export it from `placemat/__init__.py`. In `layout.py`, `_refs_in` follows `FreeSpot.near`; in `board.via`'s plan closure, when `at` is a `FreeSpot`, build a judge from the live occupancy - a candidate via `Shape` of kind `"through"` on every board layer, judged by `occ.copper_conflicts`, the board edge keep-in, rule areas forbidding vias and hole-to-hole against every through pad and every via planned so far - run `queries.free_spot` from the pad's location, and either return `[Via(name, spot.at, d, s)]` or append a finding `"via %s: nowhere within %.2f mm of %s ..." ` with the tally to `ctx.notes` and return `[]`. Add each planned via's shape to the occupancy (`occ.add_copper`) so the next search sees it.

- [ ] **Step 4: Run to verify it passes**, then the suite.

- [ ] **Step 5: Commit** - "A script's via at the nearest legal spot to a pad"

---

## Task 7: Documentation and version

- [ ] `api.md`: the `occupancy` command block and a paragraph; `FreeSpot` beside `board.via`.
- [ ] `SKILL.md`: before placing a via by coordinate, ask `placemat occupancy --via-near`, or write it with `at=FreeSpot(...)`.
- [ ] `migration.md`: `## To 0.19` - new command and reference; nothing to change.
- [ ] A test pinning the docs; bump to 0.19.0; full suite; commit "Plugin 0.19.0: is this spot legal, and which spot is".

---

## Acceptance criteria

1. The suite passes in full.
2. A via is blocked by another net's pad, track, via or graphic copper within clearance, by a hole within hole-to-hole, by the edge within the edge clearance, and by a rule area forbidding vias; not by its own net, not by a courtyard.
3. Another net's pour is reported as giving way and does not block.
4. A tail crossing another net's copper on its layer blocks the candidate.
5. The search returns the nearest clear candidate, the same one every time, and a tally of every nearer rejection; with nothing in range it returns none and the whole tally.
6. `--at` names the copper under a point per layer; `--box` counts copper by net and kind per layer.
7. On a real board, a via added where `--via-near` says leaves KiCad's real DRC counts unchanged.
8. `FreeSpot` resolves in a script against placed pads and earlier copper; a second via lands clear of the first; nowhere to go is a finding and draws nothing.
9. Docs carry the command, `FreeSpot` and `## To 0.19`, with no module, part or board names.
10. No commit mentions Claude, Anthropic or a session.
