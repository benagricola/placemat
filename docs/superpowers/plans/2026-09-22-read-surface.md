# Read Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Print the geometry placemat already holds - a part's position, boxes and every pad's true copper - so nine gaps entries stop being answered by grepping a `.kicad_mod`.

**Architecture:** A new pure module `describe.py` turns a `Footprint` or a `BoardGeometry` into rows and dicts, so the formatting is unit-testable without KiCad and `cli.py` stays a thin dispatcher. `read.py` gains a standalone `.kicad_mod` reader and the board's true outline polygon. `geometry.py` gains distance-to-a-boundary, which is not `poly_distance`.

**Tech Stack:** Python 3.12, pytest, pcbnew (only under `src/placemat/kicad/`).

**Spec:** `docs/superpowers/specs/2026-09-22-read-surface-design.md`

## Global Constraints

- `pcbnew` may be imported only under `src/placemat/kicad/`. `describe.py` and `geometry.py` are pure Python and must be unit-testable without KiCad.
- A pad's size is the box round `outlines_of`, never `GetSize()`: for a custom pad the anchor is not the copper (TPS55288 corner pads read 0.005 x 0.005 against a real 0.920 x 0.720).
- A pad read with **no board** reports an attribute (`through`, `smd front`, `smd back`) and never a layer list. Verified: `SetCopperLayerCount(2)` does not restrict a pad's own layer set, so a standalone through-hole pad reports all 32 copper layers, which is true of no real board.
- `BoardGeometry.outline` is not changed. `board_polygon` is added beside it.
- Every part block prints all three boxes: `body`, `courtyard`, `physical`.
- `parts` carries courtyard area and pin count, and the pin count comes from `ranking.pin_count` so the listing cannot disagree with the placement rank.
- Purely additive: no script changes, no placement changes, no run-record changes.
- ASCII only in prose, comments and commit messages: no em dashes, no en dashes, no unicode arrows, straight quotes.
- Commit messages must contain no reference to Claude, Anthropic, or a session URL.
- Run the suite with `.venv/bin/python -m pytest -q`. It is 562 tests and green before this plan starts.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/placemat/describe.py` (create) | `Footprint`/`BoardGeometry` to rows and dicts; all formatting, no KiCad |
| `tests/test_describe.py` (create) | the formatter, on synthetic geometry |
| `src/placemat/geometry.py` (modify) | `distance_to_boundary` |
| `src/placemat/board_geometry.py` (modify) | `BoardGeometry.board_polygon` |
| `src/placemat/kicad/read.py` (modify) | read the board polygon; `read_footprint` for a bare `.kicad_mod` |
| `src/placemat/cli.py` (modify) | `measure` gains `--pads`/`--json`/`.kicad_mod`; `parts` is new |
| `tests/test_read_surface.py` (create) | the KiCad half: standalone reader, board polygon, agreement with the placer |
| `skills/placemat/references/api.md`, `SKILL.md`, `references/migration.md` (modify) | documentation |

---

## Task 1: Distance to a boundary, which is not poly_distance

**Files:**
- Modify: `src/placemat/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: `point_segment_distance`, `_edges` (both already in `geometry.py`).
- Produces: `distance_to_boundary(poly: Polygon, boundary: Polygon) -> float`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_geometry.py

def test_distance_to_a_boundary_is_not_zero_for_a_polygon_inside_it():
    """poly_distance returns 0 when two polygons overlap, and every pad on a
    board overlaps the board outline - so it would report every pad as 0 mm
    from the edge. The measure wanted is to the boundary itself."""
    from placemat.geometry import distance_to_boundary, poly_distance
    board = ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0))
    pad = ((10.0, 10.0), (12.0, 10.0), (12.0, 12.0), (10.0, 12.0))
    assert poly_distance(pad, board) == 0.0                 # the trap
    assert distance_to_boundary(pad, board) == pytest.approx(10.0)


def test_it_takes_the_nearest_edge():
    from placemat.geometry import distance_to_boundary
    board = ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0))
    pad = ((10.0, 46.0), (12.0, 46.0), (12.0, 48.0), (10.0, 48.0))
    assert distance_to_boundary(pad, board) == pytest.approx(2.0)   # the top edge, not the left


def test_a_polygon_straddling_the_boundary_is_zero_away_from_it():
    from placemat.geometry import distance_to_boundary
    board = ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0))
    pad = ((-1.0, 10.0), (1.0, 10.0), (1.0, 12.0), (-1.0, 12.0))
    assert distance_to_boundary(pad, board) == pytest.approx(0.0)
```

`pytest` is already imported in that file.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_geometry.py -q -k boundary`
Expected: FAIL with `ImportError: cannot import name 'distance_to_boundary'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/placemat/geometry.py`, beside `poly_distance`:

```python
def distance_to_boundary(poly: Polygon, boundary: Polygon) -> float:
    """The shortest distance from `poly` to the EDGE of `boundary`.

    Not `poly_distance`: that returns 0 for polygons that overlap, and a pad
    on a board overlaps the board outline, so it would call every pad 0 mm
    from the edge. This measures to the outline itself, whether the polygon
    is inside it, outside it or across it."""
    return min(point_segment_distance(p, a, b) for p in poly for a, b in _edges(boundary))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_geometry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/geometry.py tests/test_geometry.py
git commit -m "Distance to a boundary, which is not distance to a polygon"
```

---

## Task 2: The board's real outline

**Files:**
- Modify: `src/placemat/board_geometry.py`, `src/placemat/kicad/read.py`
- Test: `tests/test_read_surface.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `BoardGeometry.board_polygon: tuple` - the outline first, then its holes, each a `Polygon`; empty when the board has no closed outline. Read by `read._board_polygon(board)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_read_surface.py
"""The read surface against real boards: the standalone footprint reader, the
board's true outline, and the promise that this reader and the placer's agree."""
import pytest

from placemat.kicad.read import read_board
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad]

FAIRING = "/home/ben/Documents/Hardware/fairing-instrument/electronics/boards/main/kicad/layout.kicad_pcb"


@needs_breakout
def test_a_rectangular_board_reads_as_one_outline_with_no_holes(breakout_pcb):
    g = read_board(breakout_pcb)
    assert len(g.board_polygon) == 1
    assert len(g.board_polygon[0]) >= 4


@needs_breakout
def test_the_outline_box_agrees_with_the_polygon(breakout_pcb):
    """board_polygon is added beside outline, not instead of it; they must
    describe the same board."""
    from placemat.values import Box
    g = read_board(breakout_pcb)
    poly_box = Box.of_points(g.board_polygon[0])
    assert poly_box.width == pytest.approx(g.outline_box.width, abs=0.2)
    assert poly_box.height == pytest.approx(g.outline_box.height, abs=0.2)


@pytest.mark.skipif(not __import__("pathlib").Path(FAIRING).exists(),
                    reason="the fairing main board is not here")
def test_a_disc_with_a_bore_reads_as_a_curve_and_a_hole():
    """The case outline gets wrong: it holds one bounding box per Edge.Cuts
    drawing, so a disc reads as a square."""
    g = read_board(FAIRING)
    assert len(g.board_polygon) >= 2                 # the rim, and at least one hole
    assert len(g.board_polygon[0]) > 100             # a flattened curve, not a rectangle
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_read_surface.py -q`
Expected: FAIL with `AttributeError: 'BoardGeometry' object has no attribute 'board_polygon'`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/board_geometry.py`, on `BoardGeometry` after `rule_areas`:

```python
    board_polygon: tuple = ()             # the true outline, then its holes; outline is bounding boxes
```

In `src/placemat/kicad/read.py`, add:

```python
def _board_polygon(board) -> tuple:
    """The board's real edge as polygons: the outline first, then its holes.

    `_outline` above keeps one bounding box per Edge.Cuts drawing, which every
    placement path consumes and which reads a disc as a square. This is the
    shape itself, for measuring how near a thing is to the edge."""
    ps = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(ps, False) or not ps.OutlineCount():
        return ()
    out = []
    o = ps.Outline(0)
    out.append(tuple((mm(o.CPoint(i).x), mm(o.CPoint(i).y)) for i in range(o.PointCount())))
    for h in range(ps.HoleCount(0)):
        hole = ps.Hole(0, h)
        out.append(tuple((mm(hole.CPoint(i).x), mm(hole.CPoint(i).y))
                         for i in range(hole.PointCount())))
    return tuple(out)
```

and pass it in `board_geometry_of`'s construction:

```python
                    rule_areas=_rule_areas(board, groups_of),
                    board_polygon=_board_polygon(board))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_read_surface.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/board_geometry.py src/placemat/kicad/read.py tests/test_read_surface.py
git commit -m "The board's real outline, beside the bounding boxes that drive placement"
```

---

## Task 3: A footprint with no board

**Files:**
- Modify: `src/placemat/kicad/read.py`
- Test: `tests/test_read_surface.py`

**Interfaces:**
- Consumes: `courtyard_box`, `phys_box`, `body_box`, `outlines_of` (all in `read.py`).
- Produces: `read.read_footprint(path, courtyard_excess_mm=0.10) -> tuple[Footprint, str]` - the footprint in its own frame at the origin, and the file's SHA-256. A through-hole pad's `layers` is `frozenset()`, because no board means no stackup; an SMD pad's is the single face it is on.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_read_surface.py
import glob
import hashlib
import os

PARTS = "/home/ben/Documents/Hardware/fairing-instrument/electronics/parts"
needs_parts = pytest.mark.skipif(not os.path.isdir(PARTS), reason="the fairing parts are not here")


def _one(pattern):
    hits = glob.glob(os.path.join(PARTS, pattern, "*.kicad_mod"))
    if not hits:
        pytest.skip("no footprint matching %s" % pattern)
    return hits[0]


@needs_parts
def test_a_kicad_mod_reads_with_no_board_at_all():
    from placemat.kicad.read import read_footprint
    fp, digest = read_footprint(_one("*05A20L10P*"))
    assert fp.pads and fp.courtyard_box.width > 0
    assert len(digest) == 64


@needs_parts
def test_the_hold_down_tabs_are_real_pads():
    """The question gaps entry 2026-09-19 answered by grepping: are P_11 and
    P_12 real mechanical pads or symbol pins with nothing behind them."""
    from placemat.kicad.read import read_footprint
    fp, _ = read_footprint(_one("*05A20L10P*"))
    tabs = [p for p in fp.pads if p.number in ("11", "12")]
    assert len(tabs) == 2
    assert all(p.box.width == pytest.approx(2.0, abs=0.01) for p in tabs)


@needs_parts
def test_a_custom_pad_reports_its_copper_and_not_its_anchor():
    """The TPS55288's four corner pads report GetSize() as 0.005 x 0.005."""
    from placemat.kicad.read import read_footprint
    fp, _ = read_footprint(_one("*TPS55288*"))
    odd = [p for p in fp.pads if p.box.width > 0.5 and p.box.width < 1.5
           and p.box.height > 0.5 and p.box.height < 1.0]
    assert odd, [(p.number, p.box.width, p.box.height) for p in fp.pads][:6]


@needs_parts
def test_a_standalone_through_pad_reports_no_layers_and_an_smd_pad_reports_one():
    """An empty board has all 32 copper layers enabled, so a through pad read
    with no board would otherwise claim In1..In30 - true of no real board."""
    from placemat.kicad.read import read_footprint
    fp, _ = read_footprint(_one("*TYPE_C*"))
    through = [p for p in fp.pads if p.through]
    smd = [p for p in fp.pads if not p.through]
    assert through and all(p.layers == frozenset() for p in through)
    assert all(len(p.layers) == 1 for p in smd)


@needs_parts
def test_the_digest_tells_two_files_apart():
    from placemat.kicad.read import read_footprint
    a = _one("*05A20L10P*")
    b = _one("*TYPE_C*")
    _, da = read_footprint(a)
    _, db = read_footprint(b)
    assert da != db
    assert da == hashlib.sha256(open(a, "rb").read()).hexdigest()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_read_surface.py -q -k "no_board or hold_down or custom_pad or standalone_through or digest"`
Expected: FAIL with `ImportError: cannot import name 'read_footprint'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/placemat/kicad/read.py`:

```python
def read_footprint(path, courtyard_excess_mm: float = 0.10) -> tuple:
    """A `.kicad_mod` read on its own, with no board: the footprint in its own
    frame at the origin, and the file's SHA-256 so two variants of a part can
    be told apart.

    A through-hole pad gets NO layers. An empty scratch board has all 32
    copper layers enabled and `SetCopperLayerCount` does not restrict a pad's
    own layer set, so a through pad read this way would claim In1 through
    In30 - true of the scratch board and of no real one. `PadGeom.through`
    already says what it is; an SMD pad's single face is read normally."""
    import hashlib
    from pathlib import Path as _Path
    p = _Path(path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    with quiet_stderr():
        fp = pcbnew.FootprintLoad(str(p.parent), p.stem)
    if fp is None:
        raise ValueError("pcbnew could not load a footprint from %s" % p)
    scratch = pcbnew.CreateEmptyBoard()
    name = fp.GetValue() or p.stem
    pads = []
    for pad in fp.Pads():
        attr = pad.GetAttribute()
        if attr == pcbnew.PAD_ATTRIB_NPTH:
            continue
        cu = [l for l in pad.GetLayerSet().CuStack()]
        if not cu:
            continue
        outs = outlines_of(pad, cu[0])
        if not outs:
            continue
        through = attr == pcbnew.PAD_ATTRIB_PTH
        pads.append(PadGeom(owner=p.stem, inst=p.stem, number=pad.GetNumber() or "?",
                            net="", layers=frozenset() if through else _copper_layers(scratch, pad.GetLayerSet()),
                            outlines=outs, box=Box.of_points([q for o in outs for q in o]),
                            through=through,
                            drill_mm=mm(pad.GetDrillSize().x) if through else 0.0))
    geom = Footprint(ref=p.stem, inst=p.stem, cell=None, value=name,
                     location=Location(0.0, 0.0), rotation=0.0, face=Face.FRONT,
                     body_box=body_box(fp, courtyard_excess_mm), courtyard_box=courtyard_box(fp),
                     phys_box=phys_box(fp), pads=tuple(pads), npth=_npth(fp),
                     fields={f.GetName(): f.GetText() for f in fp.GetFields()})
    return geom, digest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_read_surface.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/kicad/read.py tests/test_read_surface.py
git commit -m "read_footprint: a .kicad_mod measured before it is ever placed"
```

---

## Task 4: describe.py, the formatter

**Files:**
- Create: `src/placemat/describe.py`
- Test: `tests/test_describe.py`

**Interfaces:**
- Consumes: `distance_to_boundary` (Task 1), `BoardGeometry.board_polygon` (Task 2), `ranking.pin_count`.
- Produces:
  - `part_facts(fp, geometry=None) -> dict` - one part as data.
  - `pad_facts(fp, pad, geometry=None) -> dict` - one pad as data.
  - `part_lines(fp, geometry=None, pads=False, digest="") -> list[str]` - the block a human reads.
  - `parts_rows(geometry) -> list[dict]` and `parts_lines(geometry) -> list[str]` - the listing.
  - `nearest_edge(poly, geometry) -> float | None` - None when the board has no polygon.
  - `copper_on(fp, geometry) -> dict` - `{"track": n, "via": n}` for copper touching this part's pads.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_describe.py
"""What a part and a pad look like when placemat says them out loud. Pure:
no KiCad, so the formatting is pinned by tests that run anywhere."""
import dataclasses

import pytest

from placemat import describe
from placemat.values import Box, CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint, pad


def _geom():
    fps = [footprint("U1", 10.0, 10.0, w=4.0, h=2.0, inst="mcu.u", nets=("A", "GND"), cell="mcu"),
           footprint("R1", 30.0, 30.0, w=2.0, h=1.0, inst="r1", nets=("GND", "C"))]
    return board_geometry(fps, cells=["mcu"], width=60, height=60)


def test_a_part_carries_its_identity_position_and_three_boxes():
    g = _geom()
    f = describe.part_facts(g.footprint("U1"), g)
    assert f["instance"] == "mcu.u" and f["ref"] == "U1" and f["cell"] == "mcu"
    assert f["face"] == "front" and f["rotation"] == 0.0
    assert f["origin"] == [10.0, 10.0]
    for name in ("body", "courtyard", "physical"):
        assert name in f and len(f[name]) == 2, name
    assert f["body"] == [4.0, 2.0]


def test_a_pad_reports_the_box_round_its_copper_not_its_anchor():
    """A custom pad's anchor size is not its copper. The formatter is given
    outlines and must measure them."""
    g = _geom()
    fp = g.footprint("U1")
    p = fp.pads[0]
    f = describe.pad_facts(fp, p, g)
    assert f["number"] == p.number and f["net"] == p.net
    assert f["size"] == [pytest.approx(p.box.width), pytest.approx(p.box.height)]
    assert f["at"] == [pytest.approx(p.box.center.x), pytest.approx(p.box.center.y)]


def test_a_part_block_names_all_three_boxes():
    g = _geom()
    text = "\n".join(describe.part_lines(g.footprint("U1"), g))
    for word in ("body", "courtyard", "physical", "U1", "mcu.u", "front"):
        assert word in text, word


def test_pads_are_only_printed_when_asked_for():
    g = _geom()
    assert not any("pad" in l for l in describe.part_lines(g.footprint("U1"), g))
    assert any("pad" in l for l in describe.part_lines(g.footprint("U1"), g, pads=True))


def test_copper_touching_a_pad_is_counted_by_kind():
    """The question is "is anything wired to this pad", not "what is at this
    coordinate" - that one belongs to the occupancy surface."""
    from tests.fixtures import track
    fps = [footprint("U1", 10.0, 10.0, w=4.0, h=2.0, inst="u1", nets=("A", "GND"))]
    g = board_geometry(fps, copper=(track("A", 8.4, 10.0, 20.0, 10.0),), width=60, height=60)
    assert describe.copper_on(g.footprint("U1"), g) == {"track": 1, "via": 0}


def test_copper_on_another_net_is_not_counted():
    from tests.fixtures import track
    fps = [footprint("U1", 10.0, 10.0, w=4.0, h=2.0, inst="u1", nets=("A", "GND"))]
    g = board_geometry(fps, copper=(track("ELSEWHERE", 8.4, 10.0, 20.0, 10.0),),
                       width=60, height=60, extra_nets=("ELSEWHERE",))
    assert describe.copper_on(g.footprint("U1"), g) == {"track": 0, "via": 0}


def test_the_listing_carries_cell_area_and_pin_count():
    g = _geom()
    rows = {r["instance"]: r for r in describe.parts_rows(g)}
    assert rows["mcu.u"]["cell"] == "mcu"
    assert rows["r1"]["cell"] is None
    assert rows["mcu.u"]["mm2"] == pytest.approx(g.footprint("U1").courtyard_box.area, abs=0.01)
    assert rows["mcu.u"]["pins"] == 2


def test_the_listing_s_pin_count_is_the_rank_s_pin_count():
    """Two counts of the same thing would drift. The listing exists partly to
    explain the placement order, so it must not disagree with it."""
    from placemat.ranking import pin_count
    g = _geom()
    for row in describe.parts_rows(g):
        assert row["pins"] == pin_count(g.footprint(row["ref"]))


def test_a_part_with_no_cell_prints_a_dash_rather_than_a_blank():
    g = _geom()
    line = [l for l in describe.parts_lines(g) if "r1" in l][0]
    assert " - " in line


def test_the_nearest_edge_is_none_when_the_board_has_no_polygon():
    """A synthetic geometry has no board_polygon, and the formatter must not
    invent one."""
    g = _geom()
    assert describe.nearest_edge(((1.0, 1.0), (2.0, 1.0), (2.0, 2.0)), g) is None
    assert "nearest board edge" not in "\n".join(describe.part_lines(g.footprint("U1"), g))


def test_the_nearest_edge_is_measured_when_there_is_one():
    g = dataclasses.replace(_geom(),
                            board_polygon=(((0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)),))
    f = describe.part_facts(g.footprint("U1"), g)
    assert f["nearest_edge_courtyard"] == pytest.approx(7.9, abs=0.2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_describe.py -q`
Expected: FAIL with `ImportError: cannot import name 'describe'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/placemat/describe.py
"""What placemat knows about a part, said out loud.

Everything here is already in the BoardGeometry; none of it was ever printed,
which is why nine entries in PLACEMAT_GAPS.md were answered by grepping a
.kicad_mod or loading pcbnew in a scratch script. Pure: the formatting is
pinned by tests that run without KiCad, and `cli.py` stays a dispatcher.
"""
from __future__ import annotations

from .geometry import distance_to_boundary
from .ranking import pin_count
from .values import Box, CopperLayer


def _xy(p) -> list:
    return [round(p.x, 3), round(p.y, 3)]


def _wh(b: Box) -> list:
    return [round(b.width, 3), round(b.height, 3)]


def nearest_edge(poly, geometry) -> float | None:
    """How near a polygon comes to the board's edge, counting its holes: a
    cutout's edge is a board edge. None when the geometry carries no outline
    polygon, because inventing one would be worse than saying nothing."""
    rings = getattr(geometry, "board_polygon", ()) or ()
    if not rings:
        return None
    return round(min(distance_to_boundary(tuple(poly), r) for r in rings), 3)


def pad_facts(fp, pad, geometry=None) -> dict:
    """One pad. `size` is the box round its copper outlines, never the anchor
    size: for a custom pad the anchor is not the copper."""
    if pad.through:
        attribute = "through"
    elif len(pad.layers) == 1:
        attribute = "smd %s" % ("front" if next(iter(pad.layers)) is CopperLayer.F else "back")
    else:
        attribute = "smd"
    return {"number": pad.number, "net": pad.net, "at": _xy(pad.box.center),
            "size": _wh(pad.box), "through": pad.through, "attribute": attribute,
            "drill": round(pad.drill_mm, 3) if pad.through else None,
            "layers": sorted(l.value for l in pad.layers)}


def part_facts(fp, geometry=None) -> dict:
    out = {"instance": fp.inst, "ref": fp.ref, "value": fp.value, "cell": fp.cell,
           "face": fp.face.value, "rotation": fp.rotation, "origin": _xy(fp.location),
           "body": _wh(fp.body_box), "courtyard": _wh(fp.courtyard_box),
           "physical": _wh(fp.phys_box), "pins": pin_count(fp),
           "mm2": round(fp.courtyard_box.area, 3)}
    court = nearest_edge(_box_poly(fp.courtyard_box), geometry) if geometry is not None else None
    if court is not None:
        out["nearest_edge_courtyard"] = court
        copper = [q for p in fp.pads for o in p.outlines for q in o]
        if copper:
            out["nearest_edge_copper"] = nearest_edge(tuple(copper), geometry)
    return out


def _box_poly(b: Box):
    return ((b.left, b.top), (b.right, b.top), (b.right, b.bottom), (b.left, b.bottom))


def part_lines(fp, geometry=None, pads: bool = False, digest: str = "") -> list:
    f = part_facts(fp, geometry)
    lines = ["part  %-24s %-6s %s" % (f["instance"], f["ref"], f["value"])]
    lines.append("  face %-6s rotation %-6g origin (%.2f, %.2f)%s" % (
        f["face"], f["rotation"], f["origin"][0], f["origin"][1],
        "  cell %s" % f["cell"] if f["cell"] else ""))
    lines.append("  body %.2f x %.2f   courtyard %.2f x %.2f   physical %.2f x %.2f" % (
        *f["body"], *f["courtyard"], *f["physical"]))
    if "nearest_edge_courtyard" in f:
        lines.append("  nearest board edge: courtyard %.2f mm%s" % (
            f["nearest_edge_courtyard"],
            "" if f.get("nearest_edge_copper") is None else
            ", copper %.2f mm" % f["nearest_edge_copper"]))
    if digest:
        lines.append("  sha256 %s" % digest)
    if pads and geometry is not None and getattr(geometry, "copper", None):
        c = copper_on(fp, geometry)
        if c["track"] or c["via"]:
            lines.append("  copper on its pads: %d track(s), %d via(s)" % (c["track"], c["via"]))
    if pads:
        for p in fp.pads:
            d = pad_facts(fp, p, geometry)
            where = "/".join(d["layers"]) if d["layers"] else d["attribute"]
            lines.append("  pad %-5s %-14s %-12s %s at (%.3f, %.3f)  %.3f x %.3f" % (
                d["number"], d["net"] or "-", where,
                "drill %.2f " % d["drill"] if d["drill"] else "          ",
                d["at"][0], d["at"][1], d["size"][0], d["size"][1]))
    return lines


def copper_on(fp, geometry) -> dict:
    """The tracks and vias whose copper touches one of this part's pads, by
    kind. A count rather than a list, because the question this answers is
    "is anything wired to it" - what is AT a coordinate is the occupancy
    surface's question, not this one."""
    from .geometry import polys_overlap
    nets = {p.net for p in fp.pads if p.net}
    hits = {"track": 0, "via": 0}
    for c in geometry.copper:
        if c.kind not in hits or c.net not in nets:
            continue
        for p in fp.pads:
            if p.net != c.net or not c.box.overlaps(p.box):
                continue
            if any(polys_overlap(o, q) for o in c.outlines for q in p.outlines):
                hits[c.kind] += 1
                break
    return hits


def parts_rows(geometry) -> list:
    return [{"instance": fp.inst, "ref": fp.ref, "face": fp.face.value, "cell": fp.cell,
             "mm2": round(fp.courtyard_box.area, 3), "pins": pin_count(fp),
             "value": fp.value, "nets": sorted({p.net for p in fp.pads if p.net})}
            for fp in sorted(geometry.footprints, key=lambda f: f.inst)]


def parts_lines(geometry) -> list:
    rows = parts_rows(geometry)
    if not rows:
        return ["no footprints on this board"]
    out = ["%-26s %-6s %-6s %-12s %8s %5s  %s" % (
        "instance", "ref", "face", "cell", "mm2", "pins", "value")]
    for r in rows:
        out.append("%-26s %-6s %-6s %-12s %8.2f %5d  %s" % (
            r["instance"][:26], r["ref"], r["face"], (r["cell"] or "-")[:12],
            r["mm2"], r["pins"], r["value"][:28]))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_describe.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/describe.py tests/test_describe.py
git commit -m "describe: a part and a pad, as rows and as facts"
```

---

## Task 5: measure grows up

**Files:**
- Modify: `src/placemat/cli.py` (`parser`, `cmd_measure`)
- Test: `tests/test_read_surface.py`

**Interfaces:**
- Consumes: `describe.part_lines`, `describe.part_facts`, `describe.pad_facts` (Task 4); `read.read_footprint` (Task 3).
- Produces: `placemat measure <pcb | script | footprint.kicad_mod> [item ...] [--pads] [--json]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_read_surface.py

@needs_parts
def test_measure_reads_a_kicad_mod_from_the_command_line(capsys):
    import argparse
    from placemat import cli
    args = argparse.Namespace(pcb=_one("*05A20L10P*"), items=[], pads=True, json=False)
    assert cli.cmd_measure(args) == 0
    out = capsys.readouterr().out
    assert "pad" in out and "sha256" in out and "courtyard" in out


@needs_breakout
def test_measure_on_a_board_prints_position_and_boxes(breakout_pcb, capsys):
    import argparse
    from placemat import cli
    g = read_board(breakout_pcb)
    inst = g.footprints[0].inst
    args = argparse.Namespace(pcb=str(breakout_pcb), items=[inst], pads=False, json=False)
    assert cli.cmd_measure(args) == 0
    out = capsys.readouterr().out
    assert "body" in out and "courtyard" in out and "physical" in out and "origin" in out


@needs_breakout
def test_measure_json_carries_the_same_numbers(breakout_pcb, capsys):
    import argparse
    import json as _json
    from placemat import cli
    g = read_board(breakout_pcb)
    fp = g.footprints[0]
    args = argparse.Namespace(pcb=str(breakout_pcb), items=[fp.inst], pads=True, json=True)
    assert cli.cmd_measure(args) == 0
    doc = _json.loads(capsys.readouterr().out)
    (one,) = doc["parts"]
    assert one["ref"] == fp.ref
    assert one["body"] == [round(fp.body_box.width, 3), round(fp.body_box.height, 3)]
    assert len(one["pads"]) == len(fp.pads)


@needs_breakout
def test_the_measured_pad_centres_are_the_placer_s_pad_locations(breakout_pcb):
    """Two readers of the same board must agree, or a script and a review of
    that script are measuring different things."""
    from placemat import describe
    from placemat.occupancy import Occupancy
    g = read_board(breakout_pcb)
    occ = Occupancy(g, edge_margin=0.0)
    fp = [f for f in g.footprints if len(f.pads) >= 3][0]
    for p in fp.pads:
        said = describe.pad_facts(fp, p, g)["at"]
        placed = occ.pad_location(fp.ref, p.number)
        assert said == [pytest.approx(placed.x, abs=1e-6), pytest.approx(placed.y, abs=1e-6)]


@needs_breakout
def test_an_unknown_item_says_what_the_parts_are_called(breakout_pcb):
    import argparse
    from placemat import cli
    args = argparse.Namespace(pcb=str(breakout_pcb), items=["no_such_part"], pads=False, json=False)
    with pytest.raises(SystemExit) as e:
        cli.cmd_measure(args)
    assert "no_such_part" in str(e.value) and "placemat parts" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_read_surface.py -q -k "measure or placer_s_pad or unknown_item"`
Expected: FAIL - `cmd_measure` takes no `pads`/`json` and cannot read a `.kicad_mod`.

- [ ] **Step 3: Write minimal implementation**

In `parser()`, replace the `measure` block:

```python
    m = sub.add_parser("measure", help="what a part or a cell measures: position, boxes and every pad's "
                                       "real copper, on a board or on a bare .kicad_mod")
    m.add_argument("pcb", help="a layout.kicad_pcb, a layout script, or a footprint.kicad_mod")
    m.add_argument("items", nargs="*", help="cell names or part instances (default: every cell)")
    m.add_argument("--pads", action="store_true", help="every pad's number, net, layers, centre and copper box")
    m.add_argument("--json", action="store_true")
```

and rewrite `cmd_measure`:

```python
def cmd_measure(args) -> int:
    from . import describe
    from .kicad.read import read_board, read_footprint
    from .project import find_board
    p = Path(args.pcb)
    if p.suffix == ".kicad_mod":
        fp, digest = read_footprint(p)
        if args.json:
            doc = describe.part_facts(fp)
            doc["sha256"] = digest
            doc["pads"] = [describe.pad_facts(fp, q) for q in fp.pads]
            console.data(json.dumps({"parts": [doc]}, indent=2))
        else:
            console.lines("measure", "\n".join(describe.part_lines(fp, pads=args.pads, digest=digest)))
        return 0
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    snap = read_board(pcb)
    items = args.items or sorted(snap.cells)
    docs, lines = [], []
    for name in items:
        if name in snap.cells:
            c = snap.cell(name)
            docs.append({"cell": name, "size": [round(c.box.width, 3), round(c.box.height, 3)],
                         "members": [fp.ref for fp in c.members]})
            lines.append("cell %-16s %.3f x %.3f  members %s" % (
                name, c.box.width, c.box.height, " ".join(fp.ref for fp in c.members)))
            continue
        try:
            fp = snap.footprint(name)
        except KeyError:
            raise SystemExit(
                "no cell or part called %r on %s. `placemat parts %s` lists them%s"
                % (name, pcb, args.pcb, _near(name, snap)))
        doc = describe.part_facts(fp, snap)
        if args.pads:
            doc["pads"] = [describe.pad_facts(fp, q, snap) for q in fp.pads]
            doc["copper_on_pads"] = describe.copper_on(fp, snap)
        docs.append(doc)
        lines += describe.part_lines(fp, snap, pads=args.pads)
    if args.json:
        console.data(json.dumps({"parts": docs}, indent=2))
    else:
        console.lines("measure", "\n".join(lines))
    return 0


def _near(name: str, snap) -> str:
    """The closest few names, because not knowing what the parts are called is
    the usual reason for getting one wrong."""
    import difflib
    known = [fp.inst for fp in snap.footprints] + list(snap.cells)
    close = difflib.get_close_matches(name, known, n=3, cutoff=0.4)
    return ("; did you mean %s?" % ", ".join(close)) if close else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_read_surface.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/cli.py tests/test_read_surface.py
git commit -m "measure: position, three boxes, and every pad's real copper"
```

---

## Task 6: placemat parts

**Files:**
- Modify: `src/placemat/cli.py`
- Test: `tests/test_read_surface.py`

**Interfaces:**
- Consumes: `describe.parts_rows`, `describe.parts_lines` (Task 4).
- Produces: `placemat parts <pcb | script> [--json]`; `cli.cmd_parts(args) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_read_surface.py

@needs_breakout
def test_parts_lists_every_footprint_with_its_area_and_pins(breakout_pcb, capsys):
    import argparse
    from placemat import cli
    args = argparse.Namespace(pcb=str(breakout_pcb), json=False)
    assert cli.cmd_parts(args) == 0
    out = capsys.readouterr().out
    g = read_board(breakout_pcb)
    assert "instance" in out and "pins" in out and "mm2" in out
    assert out.count("\n") >= len(g.footprints)


@needs_breakout
def test_parts_json_is_one_row_per_footprint(breakout_pcb, capsys):
    import argparse
    import json as _json
    from placemat import cli
    args = argparse.Namespace(pcb=str(breakout_pcb), json=True)
    assert cli.cmd_parts(args) == 0
    doc = _json.loads(capsys.readouterr().out)
    g = read_board(breakout_pcb)
    assert len(doc["parts"]) == len(g.footprints)
    assert {r["ref"] for r in doc["parts"]} == {fp.ref for fp in g.footprints}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_read_surface.py -q -k parts`
Expected: FAIL with `AttributeError: module 'placemat.cli' has no attribute 'cmd_parts'`

- [ ] **Step 3: Write minimal implementation**

In `parser()`, after the `measure` block:

```python
    pl = sub.add_parser("parts", help="every part on the board: instance, refdes, face, cell, "
                                      "courtyard area, pin count and value")
    pl.add_argument("pcb", help="a layout.kicad_pcb, or a layout script (its board)")
    pl.add_argument("--json", action="store_true")
```

register `"parts": cmd_parts` in `main`'s dispatch table, and add:

```python
def cmd_parts(args) -> int:
    from . import describe
    from .kicad.read import read_board
    from .project import find_board
    p = Path(args.pcb)
    pcb = p if p.suffix == ".kicad_pcb" else find_board(p).pcb
    snap = read_board(pcb)
    if args.json:
        console.data(json.dumps({"parts": describe.parts_rows(snap)}, indent=2))
        return 0
    console.lines("parts", "\n".join(describe.parts_lines(snap)))
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/cli.py tests/test_read_surface.py
git commit -m "placemat parts: what the parts are called, and what they need"
```

---

## Task 7: Documentation

**Files:**
- Modify: `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, `skills/placemat/references/migration.md`
- Test: `tests/test_describe.py`

**Interfaces:** no new code interface.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_describe.py

def test_the_docs_tell_an_agent_to_measure_rather_than_grep():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "placemat parts" in api and "--pads" in api
    skill = Path("skills/placemat/SKILL.md").read_text()
    assert "placemat parts" in skill and "kicad_mod" in skill
    mig = Path("skills/placemat/references/migration.md").read_text()
    assert "0.10" in mig
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_describe.py -q -k docs`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `api.md`, replace the two `measure` lines in the Commands block with:

```
placemat measure <layout.kicad_pcb | script | footprint.kicad_mod> [cell-or-part ...] [--pads] [--json]
placemat parts <layout.kicad_pcb | script> [--json]
```

and add after that block:

````markdown
`measure` is the geometry query. Given a board it prints, per part, the
instance, refdes, value, face, rotation and origin, the `body`, `courtyard` and
`physical` boxes, and how near its courtyard and copper come to the board's
edge. `--pads` adds every pad's number, net, layers, drill, centre in the board
frame and **the box round its copper** - not the anchor size, which for a
custom pad is not the copper. Given a path ending `.kicad_mod` it reads that
footprint with no board at all, in the footprint's own frame, and prints the
file's SHA-256 so two variants of a part can be told apart; a pad read that way
reports an attribute rather than layers, because a footprint has no stackup.

`parts` answers "what are the parts called": one line per footprint with its
cell, courtyard area, pin count and value. The area and the pin count are what
the placement rank is worked out from, so the listing also explains the order
things went down in.

Both take `--json`. Reach for these before grepping a `.kicad_mod`.
````

In `SKILL.md`, in Placement tactics:

> Before grepping a `.kicad_mod` or reaching for pcbnew, run `placemat parts` to
> see what the parts are called and `placemat measure <part> --pads` to get a
> pad's real copper box, its net and its position. A footprint that is not on a
> board yet is `placemat measure <path>.kicad_mod`. Every number those print is
> one placemat already holds; going to the file by hand is how the wrong one
> gets used.

In `references/migration.md`, above `## To 0.9`:

````markdown
## To 0.10

Nothing to change. Two commands are new and one has grown, and an agent that
does not know about them will keep grepping footprints by hand.

`placemat parts <board>` lists every part: instance, refdes, face, cell,
courtyard area, pin count, value.

`placemat measure <board> <part> --pads` prints its position, its `body`,
`courtyard` and `physical` boxes, how near it comes to the board edge, and
every pad's number, net, layers, drill, centre and **copper box**. The copper
box is the box round the pad's outlines: for a custom pad the anchor size is
not the copper, and reading the anchor is how a via ends up inside a pad.

`placemat measure <path>.kicad_mod` does the same for a footprint that is not
on a board, with its SHA-256.

Both take `--json`.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Bump the version and commit**

```bash
sed -i 's/__version__ = "0.9.0"/__version__ = "0.10.0"/' src/placemat/__init__.py
sed -i 's/"version": "0.9.0"/"version": "0.10.0"/' .claude-plugin/plugin.json .claude-plugin/marketplace.json
uv pip install -q -e .
.venv/bin/python -m pytest -q
git add -A
git commit -m "Plugin 0.10.0: the read surface"
```

---

## Acceptance criteria

1. `.venv/bin/python -m pytest -q` passes in full.
2. `placemat parts <board>` lists every footprint with cell, courtyard area,
   pin count and value, and its pin count equals `ranking.pin_count`.
3. `placemat measure <board> <part> --pads` prints instance, refdes, value,
   face, rotation, origin, all three boxes, distance to the board edge, and per
   pad the number, net, layers, drill, centre and copper box.
4. `placemat measure <path>.kicad_mod` reads a footprint with no board and
   prints its SHA-256; a through-hole pad reports an attribute and no layers.
5. A custom pad reports its copper box, not its `0.005 x 0.005` anchor.
6. `describe.pad_facts(...)["at"]` equals `Occupancy.pad_location` for the same
   pad on the committed Breakout.
7. `--pads` counts the tracks and vias touching that part's pads, and ignores
   copper on other nets.
8. `distance_to_boundary` returns the distance to the edge, not 0, for a
   polygon inside another, and `BoardGeometry.board_polygon` reads a disc as a
   curve with a hole.
9. `--json` on both commands carries the same numbers as the tables.
10. An unknown item name exits naming `placemat parts` and the nearest names.
11. `api.md`, `SKILL.md` and `references/migration.md` are updated with a
    `## To 0.10` section.
12. `git log --format=%B <base>..HEAD | grep -iE "claude|anthropic|session|co-authored"`
    returns nothing.
