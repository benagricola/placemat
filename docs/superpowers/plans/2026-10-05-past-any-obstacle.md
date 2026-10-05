# Past Any Obstacle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Past(items, edge)` and `Past(items, Corner.X)` take cutouts, stretches of the board edge or of a hole, parts' and cells' envelopes and labels as well as pads, vias and tracks; declared copper nearer the outline or a cutout than the copper-to-edge clearance is a `copper.edge` finding when it is planned; copper nearer a part's drilled hole than the hole clearance is `copper.meets`.

**Architecture:** A Past's items are read as groups (`_PastGroup`: a box, a stand-off, names): the pads, vias and tracks (a named part's pads included) are one group measured exactly as before; each cutout, stretch of edge, envelope and label is a group of its own. `_past_point` stands the point far enough off every group's box, on an Edge or along a Corner's diagonal, and refuses a point off the board. Beside's align reads the same groups. `_plan_copper_batch` judges each planned op against every loop of the board's edge (`_edge_hits`), and `Occupancy.copper_conflicts(check=True)` judges a part's `hole` and `npth` shapes as well.

**Tech Stack:** Python 3.12, pcbnew and kicad-cli (KiCad 10.0.6 in the checkout's venv), pytest with xdist.

**Spec:** docs/superpowers/specs/2026-10-05-past-any-obstacle-design.md (approved 2026-10-05; keepouts, rule areas and seal regions are not Past items).

## Global Constraints

- Required properties (spec): Past over pads, vias and tracks alone resolves to the same point as today, to the nanometre, on an Edge, at a Corner, as a via's `at=` and in Beside's align. No new settings: every stand-off is a board rule already read (`BoardGeometry.edge_clearance`, `hole_clearance`, `silk_clearance`, the net-pair clearance) or zero, and the arc allowance is the existing setting `geometry.arc_sag` (`Settings.geometry_arc_sag`). Tracks do not route round obstacles: a Past is a waypoint, and copper that cuts a hole or the edge is reported, not moved.
- Decisions this plan takes where the spec is silent or where main has moved are in "Spec gaps and resolutions" at the end. The two marked "needs a user decision" are confirmed before Task 6 is started.
- Findings carry structured facts; sentences are rendered only in `finding_text.py` (findings) and `refusals.py` (refusals). A function returns records, never a sentence another function parses. `tests/test_no_sentence_parsing.py` forbids `isinstance(at|where|reach|copper, str)` in layout.py: a reason is a `Refusal`.
- Tunables are settings with documented defaults, never literals. This change adds none.
- Docs, code comments, tests and commit messages are ASCII only (no em or en dashes, no unicode arrows, straight quotes, `...`), with generic wording: code, docs, skill and commit messages never name a project, board, module, part number or net that uses placemat. Fixture folders and their part names may appear in test code only.
- Commit messages carry no reference to Claude, Anthropic or a session, and no Co-Authored-By line. After every commit run `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`; it must print nothing.
- Tests run as `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 <tests>` from the repository (or worktree) root. Never run `uv run` or `uv sync`. Nothing here changes native code; if a worktree is used and native code did change, the worktree builds its own `.venv` instead of using the checkout's.
- Bench: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2 | tee /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/bench.out`, every case `same`, the tally lines (`grep -E "^(default|solve|physical):|^seconds:"`) in the gate's commit message. This plan expects no placement to change: the bench declares no copper but `b.plane` (a `Zone`, never judged), Past is not in the corpus, and `copper_conflicts` widens only for `check=True`. A case that is not `same` is a regression to find before going on.
- Real-board and real-fixture runs (the tests in `tests/test_past_obstacles_real.py`, any test that calls `tests/real_modules.run`, the `--full` suite, the core board copy) run one at a time under `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock <command>`. CPU light: bench `--jobs 2` at most; never `pkill`, `killall` or a grep-kill.
- pcbnew items are deleted with `board.Delete(item)` (after `group.RemoveItem(item)` when grouped), never `board.Remove(item)`. This plan writes no pcbnew code; the rule binds any that a step finds it needs.
- The board-lead's core board (`~/Documents/Hardware/fairing-instrument-stagger/electronics/boards/core`) is read-only: it is copied to the scratchpad and run there.
- Slow tests (over 2 s) are listed in `tests/slow_tests.txt` in the commit that adds them.

## Review Focus

1. Existing synthetic and real boards whose declared copper already stands within the copper-to-edge clearance of their outline (test fixtures default to 0.4 mm), and module fragments, whose frame is never written to Edge.Cuts. Expected: `copper.edge` exactly where KiCad would report `copper_edge_clearance` on a drawn board; nothing on a fragment's frame. Tests: Task 6 `test_a_module_frame_is_not_an_edge`, and Task 6 Step 5 (the whole default suite, each new finding in an existing test judged against the geometry, never by loosening the check).
2. A script that uses `board.label()`'s return as text (formats it, keys a dict with it, writes it to JSON, pickles it). Expected: unchanged behaviour; `LabelKey` is a `str`. Test: Task 2 `test_a_label_key_is_still_text`.
3. Past over pads, vias and tracks alone in every form that exists today (Edge, Corner, across a pad or a via, a via's `at=`, Beside with and without `lane=`, at a Corner). Expected: the same point to the nanometre. Tests: the existing `tests/test_past_copper.py`, `test_past_corner.py`, `test_past_corner_layer.py`, `test_beside_lane.py`, `test_track_lane_waypoints.py`, `test_escape_handles.py` pass unchanged after Tasks 1, 3 and 4 (each task's Step 4 runs them).
4. A pour declared by points that covers a whole hole without crossing its edge. Expected: `copper.edge` at gap 0 (KiCad collides the filled shape with the hole's Edge.Cuts shapes). Test: Task 6 `test_a_pour_over_a_whole_hole_is_0_from_it`.
5. A board whose rules give no copper-to-edge clearance (0). Expected: copper that touches or crosses the edge is still `copper.edge` (KiCad collides at `max(0, clearance - epsilon)`); copper clear of it is not. Test: Task 6 `test_with_no_edge_clearance_only_a_touch_is_a_finding`.

## File Structure

Modified (what changes in each):

- `src/placemat/values.py` - `LabelKey`; `_PAST_KINDS`, `_CORNER_BEARING`, `_past_keeps_to_the_board`; `Past.__post_init__` and its docstring take the new kinds.
- `src/placemat/layout.py` - `board.label()` returns `LabelKey`s (`_label_keys`); `_check_past`; `_edge_loop_info`, `_judges_edge`, `_past_off_board`, `_edge_hits`, `_beside_past_groups` (Board methods); `_PastGroup`, `_cutout_box`, `_run_box`, `_unplaced`, `_past_name`, `_past_groups`, `_corner_step`, `_copper_loop_gap`, `_nearest_on`, `_toward`, `_copper_point`, `_sides_past` (module functions); `_past_copper`, `_past_names`, `_past_point` rewritten; `_past_reach` and `_lane_distance` removed; the track's corner verdict; `track()`/`via()` plan copper past a label late; Beside's needs and its "past" branch; `_check_beside_past`; the `copper.edge` check in `_plan_copper_batch`.
- `src/placemat/occupancy.py` - `copper_conflicts(check=True)` judges a part's `hole` and `npth` shapes.
- `src/placemat/refusals.py` - `past_cutout_unplaced`, `past_item_unplaced`, `past_label_not_drawn`, `past_off_board`.
- `src/placemat/findings.py`, `src/placemat/finding_text.py` - `FindingCause.COPPER_EDGE` and its sentence.
- `src/placemat/suggestions.py`, `src/placemat/script_edit.py` - the `copper.edge` case; `edit_list` add takes `at=` (a position).
- `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, `skills/placemat/references/migration.md` - Task 8 (and the suggestions-table row, Task 6).

Tests: new `tests/test_past_obstacles.py` (Tasks 1-3, 8), `tests/test_beside_past_obstacles.py` (Task 4), `tests/test_copper_holes.py` (Task 5), `tests/test_copper_edge.py` (Task 6), `tests/test_past_obstacles_real.py` (Task 7); edits to `tests/test_finding_text.py` (a sample), `tests/test_script_edit_more.py` (`at=`), `tests/slow_tests.txt`.

## Where the spec's citations are now

Main has moved since the spec was written (units, soft pin groups, the route cleanup). The spec's line numbers, as the code stands at 0.99.18 (`c4e49f22`):

| spec | now |
|---|---|
| values.py 884-948 `Past` | values.py 884-951 (`_PAST_COPPER` 884, `class Past` 887, `pads` 948-951) |
| layout.py 5585 `_check_past` | layout.py 5808-5821 |
| track point 5448, 5472 | 5671-5672 (declaration), 5695-5703 (plan) |
| via `at=` 5828, 5849 | 6051-6052, 6072-6077 |
| `copper.corner` 5527 | 5750-5762 |
| `_past_reach` 11461, `_past_point` 11494 | 11697-11727, 11730-11765 (`_round_away` 11768) |
| `_refs_in` 11693 | 11898-11935 (its Past branch 11929-11934 already reads a Part or Cell as a ref and skips the other new kinds) |
| `_check_beside_past` 2415, `_beside_placement` 2561 / "past" 2610 | 2423-2443, 2569 / 2616-2654; Beside's needs 3373-3374 |
| `place_ranked(RANK_FIXED, RANK_EDGE)` 7405, holes first 7386 | 7629, 7608-7610 |
| `_plan_copper_batch` 8484, loop 8561-8597 | 8710, 8771-8815 |
| `_edge_loops` 11292 | 11528-11535 (not used by this plan: `_shaped()` keeps each loop's arcs and the cutout names, as `_report_cell_labels_at_edge` 5306-5355 reads them) |
| occupancy.py `_hole_conflict` 2396, NPTH 2355, filter 979 | 2465-2490, 2424-2434, 1001 |
| kicad/read.py 833 | 835 |
| settings.py 25 `DEFAULT_REAL_KINDS` | 25-28 |
| api.md 874 (Beside), rows 121, 122, 125 | api.md 876-889, rows 122, 123, 126 |

KiCad's edge rule, read from `drc_test_provider_edge_clearance.cpp` (a copy is at `/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/k10/`): `testAgainstEdge` (188-245) collides the copper's effective shape with each Edge.Cuts shape at `std::max( 0, minClearance - m_epsilon )` (206); the edges are the Edge.Cuts segments and arcs, a polygon or rectangle broken into segments (289-361); an NPTH whose drill is not round is an edge too (369-376); a castellated or connector pad is skipped (437-443).

---

### Task 1: Cutouts and stretches of edge as Past items

**Files:**
- Modify: `src/placemat/values.py:884-951` (`_PAST_COPPER`, `Past`)
- Modify: `src/placemat/layout.py:47` (import), `:5808-5821` (`_check_past`, and three Board methods after it), `:11664-11695` (`_past_names`, `_past_copper`), `:11730-11765` (`_past_point`), new module functions after `_round_away` (11768-11773)
- Modify: `src/placemat/refusals.py:106-109` (codes), `:869-886` (renderers)
- Test: `tests/test_past_obstacles.py` (new)

**Interfaces:**
- Consumes: `Run` (outline.py), `CutoutHandle`, `CutoutEdge`, `Cutout`, `Board._cutout_loop_of`, `Board._named_cutouts`, `Board._shaped()`, `Settings.geometry_arc_sag`, `BoardGeometry.edge_clearance`.
- Produces:
  - `values._PAST_KINDS: str`, `values._past_keeps_to_the_board(run, edge) -> None` (raises `ValueError`).
  - `Board._edge_loop_info() -> list[tuple[int, tuple, bool, str | None]]`: `(loop index, loop points, curved, cutout name or None)`, index 0 the outline.
  - `Board._judges_edge() -> bool`; `Board._past_off_board(at: Location) -> EdgeWhy | None`.
  - `@dataclass(frozen=True) _PastGroup(box: Box, standoff: float, names: tuple)`.
  - `_cutout_box(board, it) -> Box | None` (it a `Cutout`, `CutoutHandle` or `CutoutEdge`); `_run_box(board, run) -> Box`.
  - `_past_groups(board, ctx, net, p, what, current=None) -> list[_PastGroup] | Refusal`.
  - `_corner_step(groups, corner, c: Location, width: float) -> float`.
  - `_past_point(board, ctx, net, width, p, what, current=None) -> Location | Refusal` (same signature as today).
  - `Code.PAST_CUTOUT_UNPLACED` (facts `name`), `Code.PAST_OFF_BOARD` (facts `at`, `edge` an `EdgeWhy` value, `names`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_past_obstacles.py
"""Past(items, edge) over any obstacle: cutouts, stretches of the board edge or of a hole, parts' and cells'
envelopes, and labels, as well as pads, vias and tracks. Each item is read as its box; the point stands half the
track's width (a via's radius) plus the pair's rule off each: the net-pair clearance from copper, the copper-to-edge
clearance from a hole or the edge, nothing from an envelope or (for a track) a label. Pure: synthetic boards."""
import dataclasses
import json
import math
import pickle
from pathlib import Path

import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Track, Via
from placemat.cutouts import Circle, Slot
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import (Along, Beside, Box, Cell, Centre, CopperLayer, Corner, Cutout, Edge, Face, Location, Near,
                             Net, PadRef, Part, Past, X, Y)
from tests.fixtures import board_geometry, declared_findings, footprint, pad

W3A = 1.37          # a 3 A track on 1 oz outer copper at a 10 C rise (IPC-2221): the width the reported board used
SAG = 0.02          # the setting geometry.arc_sag's default
EDGE = 0.4          # tests.fixtures.board_geometry's copper-to-edge clearance


def _part(ref, inst, net, cx, cy, w=1.0, h=1.0, margin=0.0, face=Face.FRONT):
    """A one-pad part whose body is the pad grown by `margin`, its courtyard 0.1 mm further."""
    p = pad(ref, inst, 1, net, cx, cy, w, h, face=face)
    body = Box(cx - w / 2 - margin, cy - h / 2 - margin, cx + w / 2 + margin, cy + h / 2 + margin)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, face, body, body.inflate(0.1), body, (p,))


def _board(parts=(), holes=(), width=40.0, height=30.0, margin=EDGE, keep_going=False, draw=None, **geom):
    g = board_geometry(list(parts), width=width, height=height, extra_nets=["VBUS", "SIG", "GND"], **geom)
    b = Board(g, edge_margin=margin, keep_going=keep_going)
    b.rect(width=width, height=height, holes=list(holes), draw=draw)
    for fp in parts:
        b.place(Part(fp.inst), at=fp.location, face=fp.face)
    return b


def _points(plan, net):
    return [p for t in plan.copper if isinstance(t, Track) and t.net == net for p in ((t.start.x, t.start.y), (t.end.x, t.end.y))]


def _has(plan, net, x, y):
    return any(abs(px - x) < 1e-6 and abs(py - y) < 1e-6 for px, py in _points(plan, net))


def _vias(plan, net):
    return [op for op in plan.copper if isinstance(op, Via) and op.net == net]


def _away(v, sign):
    """placemat's rounding of a Past point: to 1e-6 mm, away from the items."""
    q = v * 1e6
    return (math.ceil(q - 1e-3) if sign > 0 else math.floor(q + 1e-3)) / 1e6


def _not_drawn(plan):
    return [f for f in plan.findings if f.cause.value == "copper.not_drawn"]


# ---------------------------------------------------------------- declarations
def test_past_takes_a_cutout_a_stretch_of_a_hole_and_a_stretch_of_the_board_edge():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    for items, edge in (([vent], Edge.WEST), ([b.cutout("vent")], Edge.NORTH),
                        ([b.cutout("vent").edge(side=Edge.WEST)], Edge.WEST), ([b.edge(facing=Edge.WEST)], Edge.EAST),
                        ([vent, b.edge(facing=Edge.NORTH)], Corner.SE)):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past(items, edge), Location(38.0, 2.0)], layer=CopperLayer.F)


def test_an_item_of_another_kind_is_refused_naming_the_kinds():
    with pytest.raises(TypeError, match="cutouts .*stretches of the board edge"):
        Past([Location(1.0, 2.0)], Edge.EAST)


def test_a_cutout_that_is_not_this_boards_is_refused():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    stray = Cutout(Circle(1.5), "stray", at=Location(5.0, 5.0))
    with pytest.raises(TypeError, match="'stray' is not one of this board's named cutouts"):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past([stray], Edge.WEST), Location(2.0, 28.0)], layer=CopperLayer.F)
    other = _board(holes=[Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))])
    with pytest.raises(TypeError, match="another board"):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past([other.cutout("vent")], Edge.WEST), Location(2.0, 28.0)],
                layer=CopperLayer.F)


def test_past_off_a_stretch_of_edge_keeps_to_the_boards_side():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    west = b.edge(facing=Edge.WEST)
    Past([west], Edge.EAST)
    Past([west], Corner.NE)                     # its diagonal is 45 degrees off EAST: still the board's side
    with pytest.raises(ValueError, match="its edge is EAST"):
        Past([west], Edge.WEST)
    with pytest.raises(ValueError, match="its edge is EAST"):
        Past([west], Corner.NW)
    with pytest.raises(ValueError, match="its edge is WEST"):
        Past([b.cutout("vent").edge(side=Edge.WEST)], Edge.EAST)      # east of the hole's west side is the hole


def test_across_takes_a_cutout_and_not_a_stretch_of_edge():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    Past([vent], Edge.WEST, across=vent)
    Past([vent], Edge.WEST, across=b.cutout("vent"))
    with pytest.raises(TypeError, match="across"):
        Past([vent], Edge.WEST, across=b.edge(facing=Edge.WEST))


# ---------------------------------------------------------------- cutouts
def test_past_a_round_cutout_stands_the_edge_clearance_and_the_arc_allowance_off_its_box():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))      # box x 19.25..20.75, y 14.25..15.75
    b = _board(holes=[vent])
    b.track(Net("VBUS"), [Location(20.0, 5.0), Past([vent], Edge.WEST), Location(20.0, 25.0)], layer=CopperLayer.B,
            width=W3A)
    plan = b.resolve()
    # 19.25 - 0.02 (the arc's chords) - 0.4 (copper to edge) - 0.685 (half the track) = 18.145, on the hole's centre line
    assert _has(plan, "VBUS", 18.145, 15.0), _points(plan, "VBUS")
    assert not declared_findings(plan), plan.findings


def test_board_cutout_and_a_stretch_of_the_hole_name_the_hole():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    b.track(Net("VBUS"), [Location(20.0, 5.0), Past([b.cutout("vent")], Edge.WEST), Location(20.0, 25.0)],
            layer=CopperLayer.B, width=W3A)
    b.via(Net("SIG"), at=Past([b.cutout("vent").edge(side=Edge.EAST)], Edge.EAST), size=0.6)
    plan = b.resolve()
    assert _has(plan, "VBUS", 18.145, 15.0), _points(plan, "VBUS")
    (v,) = _vias(plan, "SIG")
    # the east stretch's box: its eastmost point 20.75 grown by 0.02; 0.4 + the via's 0.3 radius; centred, as the arc is
    assert (v.at.x, v.at.y) == (pytest.approx(21.47, abs=1e-9), pytest.approx(15.0, abs=1e-6))


def test_past_a_slot_north_of_it():
    slot = Cutout(Slot(4.0, 1.5), "slot", at=Location(20.0, 15.0))     # box x 18..22, y 14.25..15.75
    b = _board(holes=[slot])
    b.track(Net("VBUS"), [Location(10.0, 13.145), Past([slot], Edge.NORTH), Location(30.0, 13.145)],
            layer=CopperLayer.B, width=W3A)
    plan = b.resolve()
    assert _has(plan, "VBUS", 20.0, 13.145), _points(plan, "VBUS")       # 14.25 - 0.02 - 0.4 - 0.685


def test_past_a_cutout_with_a_freedom_resolves_where_it_settled():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, None), why="air")   # free in y: the board slides it
    b = _board(holes=[vent])
    b.via(Net("SIG"), at=Past([vent], Edge.NORTH), size=0.6)
    b.via(Net("VBUS"), at=Past([b.cutout("vent").edge(side=Edge.SOUTH)], Edge.SOUTH), size=0.6)  # a promise until it settles
    plan = b.resolve()
    c = plan.cutouts_placed["vent"].centre
    (v,), (w,) = _vias(plan, "SIG"), _vias(plan, "VBUS")
    assert v.at.x == pytest.approx(c.x, abs=1e-6) and v.at.y == pytest.approx(_away(c.y - 0.75 - SAG - EDGE - 0.3, -1), abs=1e-6)
    assert w.at.x == pytest.approx(c.x, abs=1e-6) and w.at.y == pytest.approx(_away(c.y + 0.75 + SAG + EDGE + 0.3, 1), abs=1e-6)


# ---------------------------------------------------------------- the board edge
def test_past_the_board_edge_stands_inboard_by_the_edge_clearance():
    b = _board()
    b.track(Net("SIG"), [Location(0.5, 2.0), Past([b.edge(facing=Edge.WEST)], Edge.EAST), Location(0.5, 28.0)],
            layer=CopperLayer.F)
    plan = b.resolve()
    assert _has(plan, "SIG", 0.5, 15.0), _points(plan, "SIG")             # 0 + 0.4 + 0.1, the middle of the west side


def test_past_a_curved_stretch_of_a_round_board_takes_its_box_grown_by_the_arc_allowance():
    b = Board(board_geometry([], width=40.0, height=40.0, extra_nets=["SIG"]), edge_margin=EDGE)
    b.disc(30.0)
    rim = b.edge(facing=Edge.WEST)
    box = Box.of_points(rim.points)
    b.via(Net("SIG"), at=Past([rim], Edge.EAST), size=0.6)
    (v,) = _vias(b.resolve(), "SIG")
    assert v.at.x == pytest.approx(_away(box.right + SAG + EDGE + 0.3, 1), abs=1e-9)
    assert v.at.y == pytest.approx(box.top + 0.5 * (box.bottom - box.top), abs=1e-6)


# ---------------------------------------------------------------- items mixed
def test_on_an_edge_the_outer_group_sets_the_point_and_across_a_cutout_its_centre_line():
    def plan_of(across):
        pa = _part("PA", "pa", "GND", 20.0, 10.0)                         # pad box 19.5..20.5, 9.5..10.5
        b = _board([pa], holes=[Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))])
        vent = b._named_cutouts["vent"]
        b.via(Net("SIG"), at=Past([PadRef(Part("pa"), 1), vent], Edge.WEST, across=vent if across else None), size=0.6)
        (v,) = _vias(b.resolve(), "SIG")
        return v.at
    # the pad: 19.5 - 0.2 - 0.3 = 19.0; the hole: 19.25 - 0.02 - 0.4 - 0.3 = 18.53, further out
    on_hole = plan_of(True)
    assert (on_hole.x, on_hole.y) == (pytest.approx(18.53, abs=1e-9), pytest.approx(15.0, abs=1e-6))
    middle = plan_of(False)                                               # the middle of the union, 9.5..15.77
    assert (middle.x, middle.y) == (pytest.approx(18.53, abs=1e-9), pytest.approx(12.635, abs=1e-6))


def test_at_a_corner_each_groups_corner_is_passed_at_least_at_its_own_stand_off():
    pa = _part("PA", "pa", "GND", 20.0, 15.0)                             # pad NE corner (20.5, 14.5), reach 0.3 + 0.2
    vent = Cutout(Circle(1.5), "vent", at=Location(24.0, 15.0))          # grown box NE corner (24.77, 14.23), reach 0.3 + 0.4
    b = _board([pa], holes=[vent])
    b.via(Net("SIG"), at=Past([PadRef(Part("pa"), 1), vent], Corner.NE), size=0.6)
    (v,) = _vias(b.resolve(), "SIG")
    # the union's NE corner is the hole's; the pad's corner stands 4.54 mm behind it along the diagonal, so the
    # hole's reach sets the point: 0.7 / sqrt(2) out on each axis
    d = 0.7 / math.sqrt(2.0)
    assert (v.at.x, v.at.y) == (pytest.approx(_away(24.77 + d, 1), abs=1e-9), pytest.approx(_away(14.23 - d, -1), abs=1e-9))
    for cx, cy, reach in ((20.5, 14.5, 0.5), (24.77, 14.23, 0.7)):        # a 45 through it passes each corner at its reach
        assert ((v.at.x - cx) - (v.at.y - cy)) / math.sqrt(2.0) >= reach - 1e-6


# ---------------------------------------------------------------- not drawn
def test_a_past_off_a_cutout_that_found_no_place_is_not_drawn():
    pa = _part("PA", "pa", "GND", 20.0, 15.0)
    # placed over the part it is placed by: refused (it would mill the part), so it has no place
    vent = Cutout(Circle(1.5), "vent", at=Centre(X(Part("pa")), Y(Part("pa"))), why="air")
    b = _board([pa], holes=[vent], keep_going=True)
    b.track(Net("SIG"), [Location(5.0, 2.0), Past([vent], Edge.NORTH), Location(35.0, 2.0)], layer=CopperLayer.F)
    plan = b.resolve()
    (f,) = _not_drawn(plan)
    assert f.facts["variant"] == "past" and f.facts["names"] == ["cutout vent"]
    assert f.facts["why"] == {"code": "past_cutout_unplaced", "name": "vent"}
    assert "cutout vent found no place" in str(f)
    assert not _points(plan, "SIG")


def test_a_past_whose_point_lands_off_the_board_is_not_drawn():
    pa = _part("PA", "pa", "GND", 0.6, 15.0)                              # pad west side at x = 0.1
    b = _board([pa], margin=0.0)
    b.track(Net("SIG"), [Location(5.0, 10.0), Past([PadRef(Part("pa"), 1)], Edge.WEST), Location(5.0, 20.0)],
            layer=CopperLayer.F)
    plan = b.resolve()
    (f,) = _not_drawn(plan)
    assert f.facts["why"] == {"code": "past_off_board", "at": [-0.2, 15.0], "edge": "outside", "names": ["PA.1"]}
    assert "(-0.20, 15.00) lies off the board" in str(f)
    assert not _points(plan, "SIG")


def test_a_fragments_frame_is_no_edge_for_a_past():
    pa = _part("PA", "pa", "GND", 0.6, 15.0)
    b = _board([pa], margin=0.0, draw=False)                              # a module's frame: never written to Edge.Cuts
    b.via(Net("SIG"), at=Past([PadRef(Part("pa"), 1)], Edge.WEST), size=0.6)
    (v,) = _vias(b.resolve(), "SIG")
    assert v.at.x == pytest.approx(-0.4, abs=1e-9)                        # 0.1 - 0.2 - 0.3, past the frame, drawn
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles.py -q`
Expected: FAIL on `TypeError: Past's items are pads (PadRef, CellPadRef), vias and tracks, not Cutout(...)` (the side and kinds tests fail on their messages; `Past([west], ...)` on `not Run(...)`).

- [ ] **Step 3: Implement**

`values.py`: after `_PAST_COPPER` (line 884) add:

```python
_PAST_KINDS = ("pads (PadRef, CellPadRef), vias, tracks, cutouts (the Cutout given to holes=, or board.cutout(name)), "
               "and stretches of the board edge or of a hole (board.edge(facing=), board.cutout(name).edge(side=))")
_CORNER_BEARING = {"NE": 45.0, "SE": 135.0, "SW": 225.0, "NW": 315.0}     # a Corner's outward diagonal, as a bearing


def _past_keeps_to_the_board(run, edge) -> None:
    """A Past off a stretch of edge stands on the board's side of it: its Edge, or its Corner's outward diagonal, points
    within 45 degrees of the bearing away from the stretch's void (a Run's `facing` plus 180; a CutoutEdge's `side`,
    since its run faces back into the hole). Raises ValueError naming the sides that would."""
    away = bearing(run.side) if isinstance(run, CutoutEdge) else (float(run.facing) + 180.0) % 360.0
    toward = bearing(edge) if isinstance(edge, Edge) else _CORNER_BEARING[edge.value]
    if abs((toward - away + 180.0) % 360.0 - 180.0) <= 45.0 + 1e-9:
        return
    sides = [e.name for e in Edge if abs((bearing(e) - away + 180.0) % 360.0 - 180.0) <= 45.0 + 1e-9]
    raise ValueError("Past off a stretch of edge stands on the board's side of it: this stretch's void lies at bearing %g, "
                     "so its edge is %s (or a Corner within 45 degrees of that), not %s"
                     % ((away + 180.0) % 360.0, " or ".join(sides), edge.name))
```

Replace `Past`'s docstring and `__post_init__` (lines 888-946) with:

```python
    """A point held off the `edge` side of some items: `Past([PadRef(a), vent], Edge.EAST)`. `items` are pads
    (`PadRef`/`CellPadRef`), vias (what `board.via()` or `board.vias()` returns), tracks (what `board.track()` returns),
    cutouts (the `Cutout` given to `holes=`, or `board.cutout(name)`) and stretches of the board edge or of a hole
    (`board.edge(facing=)`, `board.cutout(name).edge(side=)`), in any mix. Each is read as its box; the point stands far
    enough out to keep the pair's rule from each: the worst clearance by net pair from the pads, vias and tracks together,
    the board's copper-to-edge clearance from a hole or the edge. Off a stretch of edge the point is on the board's side
    of it.

    `across` sets where the point lies across `edge`: on a pad's, a via's or a cutout's centre line, or at an `Along` of
    the combined box's side (default the middle).

    `edge` may be a `Corner` instead: the point is on the outward diagonal from that corner of the combined box, far
    enough out that a 45 through it across the diagonal passes each item's corner at least at its rule. A corner fixes
    the point on both axes, so it takes no `across`.

    As a track waypoint the point is half the track's width further out; as a via's `at=`, the via's radius. In
    `Beside`'s align pair, `lane=` a net leaves room for one track of it between the items and the part's pad, `width=`
    wide (default the net's track width): the copper its current needs.

    Resolved when every pad is placed, every via and track planned and every cutout cut."""
    items: tuple
    edge: object
    across: object = field(default=None, metadata={"omit_default": True})
    lane: object = field(default=None, metadata={"omit_default": True})
    width: float | None = field(default=None, metadata={"omit_default": True})

    def __post_init__(self):
        from .layout import CopperIntent, CutoutHandle
        from .outline import Run
        object.__setattr__(self, "items", tuple(self.items))
        if not self.items:
            raise ValueError("Past needs at least one item: %s" % _PAST_KINDS)
        if not isinstance(self.edge, (Edge, Corner)):
            raise TypeError("Past's edge is an Edge or a Corner, not %r" % (self.edge,))
        if isinstance(self.edge, Corner) and self.across is not None:
            raise TypeError("Past at a corner is fixed on both axes by it; it takes no across=")
        for it in self.items:
            if isinstance(it, CopperIntent):
                if it.key.split(" ")[0] not in _PAST_COPPER:
                    raise TypeError("Past's items are %s; %s is neither a via nor a track" % (_PAST_KINDS, it.key))
            elif isinstance(it, (Run, CutoutEdge)):
                _past_keeps_to_the_board(it, self.edge)
            elif not isinstance(it, (PadRef, CellPadRef, Cutout, CutoutHandle)):
                raise TypeError("Past's items are %s, not %r" % (_PAST_KINDS, it))
        a = self.across
        if isinstance(a, (Run, CutoutEdge)):
            raise TypeError("Past's across= is a centre line to lie on, and a stretch of edge has none (its middle is "
                            "Along.MID); give a pad, a via, a cutout or an Along")
        if not (a is None or isinstance(a, (PadRef, CellPadRef, Along, Cutout, CutoutHandle))
                or (isinstance(a, CopperIntent) and a.key.split(" ")[0] == "via")):
            raise TypeError("Past's across is a PadRef, a via, a cutout or Along.START/MID/END, not %r" % (a,))
        if self.lane is not None and not isinstance(self.lane, Net):
            raise TypeError("Past's lane is a Net, not %r" % (self.lane,))
        if self.width is not None and self.lane is None:
            raise TypeError("Past's width= is a lane's width: give it with lane=Net(...)")
```

(`bearing` and `CutoutEdge` are defined further down values.py; both are read when a Past is made, by which time the module is loaded.)

`refusals.py`: after `PAST_NO_TRACK = "past_no_track"` (line 109) add

```python
    PAST_CUTOUT_UNPLACED = "past_cutout_unplaced"
    PAST_OFF_BOARD = "past_off_board"
```

and after `_past_no_track` (line 886):

```python
@renders(Code.PAST_CUTOUT_UNPLACED, "copper")
def _past_cutout_unplaced(f):
    return "cutout %s found no place" % f["name"]


@renders(Code.PAST_OFF_BOARD, "copper")
def _past_off_board(f):
    return "its point (%.2f, %.2f) lies %s" % (f["at"][0], f["at"][1],
                                               "in a cutout" if f["edge"] == "in_cutout" else "off the board")
```

`layout.py` line 47: `CutoutEdge` is already imported; nothing to add for this task.

Replace `_check_past` (5808-5821) with the following, and add the three methods after it:

```python
    def _check_past(self, p: Past, what: str, lane: bool = False):
        """A Past's items are this board's: its vias and tracks, its named cutouts; `lane=` only where `lane` says it
        means something (Beside's align)."""
        for it in p.items + (p.across,):
            if isinstance(it, CopperIntent) and not any(it is c for c in self._copper):
                raise TypeError("%s: %s is copper of another board" % (what, it.key))
            if isinstance(it, CutoutHandle) and it._board is not self:
                raise TypeError("%s: cutout %r is another board's" % (what, it.name))
            if isinstance(it, (Cutout, CutoutEdge)) and (
                    it.name not in self._named_cutouts or (isinstance(it, Cutout) and self._named_cutouts[it.name] != it)):
                raise TypeError("%s: cutout %r is not one of this board's named cutouts (the Cutout given to holes=, or "
                                "board.cutout(name)); declare the board's holes before the copper that passes them"
                                % (what, it.name))
        for it in p.items:
            if getattr(it, "edge", None) is not None and isinstance(it, (PadRef, CellPadRef)):
                raise TypeError("%s: Past's items are the copper it is held off; a PadRef's edge= is a track "
                                "point on that edge, so name the pad without it" % what)
        if p.lane is not None and not lane:
            raise TypeError("%s: Past's lane= is for Beside's align, where it leaves room for a track "
                            "between a part's pad and the items; a Past here keeps its own clearance" % what)

    def _edge_loop_info(self) -> list:
        """[(index, loop, curved, name)] for each loop of the board's edge: 0 the outline (name None), then each hole,
        named by its cutout's name, or None for a raw path. `curved`: the loop is drawn from arcs (a disc's rim or bore,
        or a path with an Arc leg), so its chords stand up to `geometry.arc_sag` inside the curve KiCad judges, as
        `_report_cell_labels_at_edge` reads it."""
        shape = self._shaped()
        disc = isinstance(self._shape, Disc)
        names = {k: n for n, k in self._cutout_loop_of.items()}
        out = []
        for k, loop in enumerate(shape.loops):
            curved = (disc and (k == 0 or (k == 1 and bool(self._shape.bore)))) or \
                any(isinstance(leg, Arc) for leg in shape.paths[k])
            out.append((k, loop, curved, names.get(k)))
        return out

    def _judges_edge(self) -> bool:
        """Whether copper is judged against this board's edge: its outline is known and is drawn. A fragment's frame
        (`draw=False`, a module run) is never written to Edge.Cuts and its DRC judges no edge, so it is not one."""
        return self._draw_outline and (self._shape is not None or self._outline is not None)

    def _past_off_board(self, at: Location):
        """Why a Past's point is not on the board, `EdgeWhy.OUTSIDE` or `EdgeWhy.IN_CUTOUT`, or None; None too where the
        edge is not judged (`_judges_edge`)."""
        if not self._judges_edge():
            return None
        why = self._shaped().why_not(Box(at.x, at.y, at.x, at.y), 0.0)
        return why if why in (EdgeWhy.OUTSIDE, EdgeWhy.IN_CUTOUT) else None
```

(`Disc` is imported from values on line 47; `Arc` on line 37; `EdgeWhy` on line 32.)

Replace `_past_names` and `_past_copper` (11664-11694) with:

```python
def _past_name(board: "Board", it) -> str:
    """What one of a Past's items is called in a finding: a via's or track's key, a pad's refdes and number, "cutout
    NAME", a stretch of edge by the bearing its void faces."""
    if isinstance(it, CopperIntent):
        return it.key
    if isinstance(it, (PadRef, CellPadRef)):
        return "%s.%s" % board._pad_ref(it)[:2]
    if isinstance(it, (Cutout, CutoutHandle, CutoutEdge)):
        return "cutout %s" % it.name
    return "edge facing %g" % it.facing                                     # a Run


def _past_names(board: "Board", p: Past) -> list:
    """What a Past's items are called in a finding, in the order given."""
    return [_past_name(board, it) for it in p.items]


def _past_copper(board: "Board", occ: Occupancy, ops_at: dict, p: Past, what: str,
                 current: int | None = None, layer: CopperLayer | None = None):
    """(net, box, owner, name) for every piece of copper `p.items` names: each pad's
    shapes, each via's ring and each track's segments, as the polygons the
    clearance check measures. With `layer`, only the copper on that layer: a
    pad's own layers, a via's span, a track's layer. A Refusal instead when a
    via or track has no copper (see `_past_unplanned`). Items that are not
    copper (a cutout, a stretch of edge) give none."""
    out = []
    for it, name in zip(p.items, _past_names(board, p)):
        if isinstance(it, CopperIntent):
            why = _past_unplanned(ops_at, it, what, current)
            if why is not None:
                return why
            for op in ops_at[it.index]:
                if isinstance(op, (Via, Track)):
                    if layer is not None and (op.layer is not layer if isinstance(op, Track)
                                              else op.layers and layer not in op.layers):
                        continue
                    # its polygon's box: the copper the clearance check measures, a via's ring a
                    # little outside the true circle
                    out.append((op.net, op.box, "", name))
        elif isinstance(it, (PadRef, CellPadRef)):
            out += [(sh.net, sh.box, sh.owner, name) for sh in _pad_shapes(board, occ, it)
                    if layer is None or layer in sh.layers]
    return out
```

Keep `_past_reach` and `_box_corner`, `_lane_dirs` as they are (the corner verdict still calls `_past_reach` until Task 3). Replace `_past_point` (11730-11765) with:

```python
def _past_point(board: "Board", ctx: "_CopperContext", net: str, width: float, p: Past, what: str,
                current: int | None = None):
    """Past(items, edge)'s point for copper of `net`, `width` across (a via's size): measured off the groups of its
    items (`_past_groups`). On an Edge, far enough out of the union of their boxes' `edge` side that it stands half
    `width` plus each group's stand-off off that group's own side; across it where `across` says (default the middle of
    the union's side). At a Corner, on the outward diagonal from the union's corner, far enough that a 45 through it
    passes each group's own corner at half `width` plus its stand-off (`_corner_step`). Rounded away from the items.
    With copper alone this is the clearance off its combined box, as it always was. A Refusal instead, the reason: a
    via or track it names has no copper, a cutout has no place, or the point lands off the board or in a hole."""
    groups = _past_groups(board, ctx, net, p, what, current)
    if isinstance(groups, Refusal):
        return groups
    box = Box.union([g.box for g in groups])
    if isinstance(p.edge, Corner):
        sx, sy = p.edge.signs
        c = _box_corner(box, p.edge)
        d = _corner_step(groups, p.edge, c, width)
        point = Location(_round_away(c.x + sx * d, sx), _round_away(c.y + sy * d, sy))
    else:
        upright = p.edge in (Edge.EAST, Edge.WEST)          # the side runs north-south: across is y
        lo, hi = (box.top, box.bottom) if upright else (box.left, box.right)
        a = p.across
        if a is None or isinstance(a, Along):
            across = lo + (Along.MID if a is None else a).fraction * (hi - lo)
        elif isinstance(a, (Cutout, CutoutHandle)):
            hole = _cutout_box(board, a)
            if hole is None:
                return Refusal(Code.PAST_CUTOUT_UNPLACED, name=a.name)
            across = hole.center.y if upright else hole.center.x
        else:
            if isinstance(a, CopperIntent):
                why = _past_unplanned(ctx.ops_at, a, what, current)
                if why is not None:
                    return why
            at = _edge_point(board, ctx.occ, width, a) if getattr(a, "edge", None) is not None else ctx.locate(a)
            across = at.y if upright else at.x
        reach = [(g.box, width / 2.0 + g.standoff) for g in groups]
        if p.edge is Edge.EAST:
            point = Location(_round_away(max(b.right + r for b, r in reach), 1), round(across, 6))
        elif p.edge is Edge.WEST:
            point = Location(_round_away(min(b.left - r for b, r in reach), -1), round(across, 6))
        elif p.edge is Edge.NORTH:
            point = Location(round(across, 6), _round_away(min(b.top - r for b, r in reach), -1))
        else:                                                                       # SOUTH
            point = Location(round(across, 6), _round_away(max(b.bottom + r for b, r in reach), 1))
    off = board._past_off_board(point)
    if off is not None:
        return Refusal(Code.PAST_OFF_BOARD, at=[point.x, point.y], edge=off.value, names=_past_names(board, p))
    return point
```

After `_round_away` (11768-11773) add:

```python
@dataclass(frozen=True)
class _PastGroup:
    """One group of a Past's items, as its point is measured off it: its box, its stand-off from the copper passing it
    (beyond half that copper's width), and what a finding calls its items."""
    box: Box
    standoff: float
    names: tuple


def _run_box(board: "Board", run: Run) -> Box:
    """A stretch of edge's box: its points', grown by `geometry.arc_sag` where it is curved, since its chords stand up to
    that far inside the curve KiCad judges."""
    box = Box.of_points(run.points)
    return box if run.straight else box.inflate(board.settings.geometry_arc_sag)


def _cutout_box(board: "Board", it) -> Box | None:
    """The box a Past reads off a cutout (a `Cutout` or `CutoutHandle`) or a stretch of one (a `CutoutEdge` promise):
    its loop's points, grown by `geometry.arc_sag` where the loop is drawn from arcs, as `_cutout_silk` holds silk off a
    hole; a stretch's as `_run_box` reads it. None while the cutout has no place."""
    k = board._cutout_loop_of.get(it.name)
    if k is None:
        return None
    if isinstance(it, CutoutEdge):
        return _run_box(board, CutoutHandle(board, it.name).edge(it.side, it.within))
    _, loop, curved, _ = board._edge_loop_info()[k]
    box = Box.of_points(loop)
    return box.inflate(board.settings.geometry_arc_sag) if curved else box


def _past_groups(board: "Board", ctx: "_CopperContext", net: str, p: Past, what: str, current: int | None = None):
    """The groups a Past's point is measured off, or a Refusal, the reason there are none. The pads, vias and tracks are
    one group: their copper's combined box, and the worst clearance by net pair from `net` to them, as Past has always
    measured. Each cutout and each stretch of edge is a group of its own: its box (`_cutout_box`, `_run_box`) and the
    board's copper-to-edge clearance (KiCad's EDGE_CLEARANCE_CONSTRAINT, `geometry.edge_clearance`: a cutout is an
    Edge.Cuts loop as the outline is)."""
    copper = _past_copper(board, ctx.occ, ctx.ops_at, p, what, current)
    if isinstance(copper, Refusal):
        return copper
    groups = []
    if copper:
        groups.append(_PastGroup(Box.union([c[1] for c in copper]),
                                 max(_pad_clearance(board, net, c[0], c[2]) for c in copper),
                                 tuple(dict.fromkeys(c[3] for c in copper))))
    edge_rule = board.geometry.edge_clearance
    for it, name in zip(p.items, _past_names(board, p)):
        if isinstance(it, (Cutout, CutoutHandle, CutoutEdge)):
            box = _cutout_box(board, it)
            if box is None:
                return Refusal(Code.PAST_CUTOUT_UNPLACED, name=it.name)
            groups.append(_PastGroup(box, edge_rule, (name,)))
        elif isinstance(it, Run):
            groups.append(_PastGroup(_run_box(board, it), edge_rule, (name,)))
    return groups


def _corner_step(groups, corner: Corner, c: Location, width: float) -> float:
    """How far out along each axis from `c`, the corner of the groups' union box, a point on the outward diagonal stands
    so that a 45 through it across the diagonal passes each group's own corner at half `width` plus that group's
    stand-off: over the groups, the most of half the group corner's offset behind `c` along the diagonal plus that reach
    over sqrt(2). With one group its corner is `c` and this is the reach over sqrt(2), as it always was."""
    sx, sy = corner.signs
    out = -math.inf
    for g in groups:
        gc = _box_corner(g.box, corner)
        out = max(out, (sx * (gc.x - c.x) + sy * (gc.y - c.y)) / 2.0 + (width / 2.0 + g.standoff) / math.sqrt(2.0))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles.py tests/test_past_copper.py tests/test_past_corner.py tests/test_past_corner_layer.py tests/test_beside_lane.py tests/test_track_lane_waypoints.py tests/test_escape_handles.py tests/test_pad_edge_tap.py tests/test_pad_land.py tests/test_clearance_rules.py tests/test_no_sentence_parsing.py -q`
Expected: PASS. The existing Past files pass unchanged (Review Focus 3).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/values.py src/placemat/layout.py src/placemat/refusals.py tests/test_past_obstacles.py
git commit -m "Past: a cutout and a stretch of the board edge or of a hole are items, held off at the copper-to-edge clearance; a point off the board is not drawn"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 2: Parts, cells and labels as Past items

**Files:**
- Modify: `src/placemat/values.py` (`_PAST_KINDS`, `LabelKey`, `Past.__post_init__` from Task 1)
- Modify: `src/placemat/layout.py:47` (import `LabelKey`), `Board.__init__` near 997-998 (`_label_keys`), `label()` 5561-5609, `_check_past` (Task 1), `track()` after its `_copper_intent` (5765), `via()` 6051-6077 and after its `_copper_intent` (6089), `_past_name`, `_past_copper`, `_past_groups`, `_past_point` (Task 1)
- Modify: `src/placemat/refusals.py` (two codes and renderers)
- Test: `tests/test_past_obstacles.py` (append)

**Interfaces:**
- Consumes: Task 1's `_PastGroup`, `_past_groups`, `_past_point`, `_past_names`, `_cutout_box`; `Board._placed_envelope_box(occ, item) -> Box` (layout.py 2446); `plan._labelled[key] = (op, own, face)` (layout.py 8418).
- Produces:
  - `values.LabelKey(str)`; `board.label()` returns a `LabelKey` (a list of them for a list of items).
  - `Board._label_keys: dict[str, LabelKey]`.
  - `_unplaced(board, occ, item) -> bool`.
  - `_past_groups(board, ctx, net, p, what, current=None, via=False)`; `_past_point(board, ctx, net, width, p, what, current=None, via=False)`.
  - `Code.PAST_ITEM_UNPLACED` (facts `item`), `Code.PAST_LABEL_NOT_DRAWN` (facts `key`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_past_obstacles.py` add `LabelKey` to the `placemat.values` import, and append:

```python
# ---------------------------------------------------------------- parts, cells and labels
def test_past_takes_a_part_a_cell_and_a_label_and_refuses_text():
    b = _board([_part("PA", "pa", "SIG", 10.0, 10.0)])
    key = b.label(Part("pa"), "PA")
    for items, edge in (([Part("pa")], Edge.SOUTH), ([key], Edge.NORTH), ([PadRef(Part("pa"), 1), Part("pa"), key], Corner.NE)):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past(items, edge), Location(38.0, 2.0)], layer=CopperLayer.F)
    with pytest.raises(TypeError, match="Past's items are .*labels"):
        Past(["label pa PA"], Edge.EAST)          # text is not a label: what board.label() returns is
    with pytest.raises(TypeError, match="across"):
        Past([Part("pa")], Edge.WEST, across=key)
    Past([key], Edge.WEST, across=Part("pa"))


def test_a_label_key_is_still_text():
    b = _board([_part("PA", "pa", "SIG", 10.0, 10.0)])
    keys = b.label([Part("pa")], ["PA"])
    assert keys == ["label pa PA"] and all(type(k) is LabelKey for k in keys)
    k = keys[0]
    assert "%s!" % k == "label pa PA!" and {k: 1}["label pa PA"] == 1
    assert json.dumps({k: k}) == '{"label pa PA": "label pa PA"}' and pickle.loads(pickle.dumps(k)) == k


def test_a_label_of_another_board_is_refused():
    a = _board([_part("PA", "pa", "SIG", 10.0, 10.0)])
    b = _board([_part("PA", "pa", "SIG", 10.0, 10.0)])
    key = a.label(Part("pa"), "PA")
    b.label(Part("pa"), "PA")                     # the same text on b: still a's key
    with pytest.raises(TypeError, match="not a label of this board"):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past([key], Edge.NORTH), Location(38.0, 2.0)], layer=CopperLayer.F)


def test_past_a_part_the_pads_clearance_wins_where_the_pad_reaches_nearer_its_courtyard_than_that():
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0, margin=0.0)])        # courtyard west side 19.4, pad west side 19.5
    b.track(Net("SIG"), [Location(19.2, 5.0), Past([Part("pa")], Edge.WEST), Location(19.2, 25.0)], layer=CopperLayer.F)
    plan = b.resolve()
    assert _has(plan, "SIG", 19.2, 15.0), _points(plan, "SIG")             # the pad: 19.5 - 0.2 - 0.1; the courtyard 19.3
    assert not declared_findings(plan), plan.findings


def test_past_a_part_whose_courtyard_reaches_further_stands_on_its_envelope():
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0, margin=0.5)])        # courtyard west side 18.9
    b.track(Net("SIG"), [Location(18.8, 5.0), Past([Part("pa")], Edge.WEST), Location(18.8, 25.0)], layer=CopperLayer.F)
    assert _has(b.resolve(), "SIG", 18.8, 15.0)                           # 18.9 - 0.1, outside the pad's 19.2


def test_a_past_off_a_searched_part_waits_for_it():
    pa = _part("PA", "pa", "GND", 20.0, 15.0, margin=0.5)
    b = Board(board_geometry([pa], width=40, height=30, extra_nets=["SIG"]), edge_margin=EDGE)
    b.rect(width=40.0, height=30.0)
    b.place(Part("pa"))                           # searched: the via is planned after the search, off where pa lands
    b.via(Net("SIG"), at=Past([Part("pa")], Edge.NORTH), size=0.6)
    plan = b.resolve()
    env = b._placed_envelope_box(plan.occupancy, Part("pa"))
    (v,) = _vias(plan, "SIG")
    assert (v.at.x, v.at.y) == (pytest.approx(env.left + 0.5 * (env.right - env.left), abs=1e-6),
                                pytest.approx(_away(env.top - 0.3, -1), abs=1e-9))


def test_across_a_part_puts_the_point_on_its_envelopes_centre_line():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board([_part("PA", "pa", "GND", 10.0, 10.0)], holes=[vent])
    b.via(Net("SIG"), at=Past([vent], Edge.WEST, across=Part("pa")), size=0.6)
    (v,) = _vias(b.resolve(), "SIG")
    assert (v.at.x, v.at.y) == (pytest.approx(18.53, abs=1e-9), pytest.approx(10.0, abs=1e-6))   # 19.25 - 0.02 - 0.4 - 0.3


def _labelled_board():
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0)], silk_clearance=0.2)
    return b, b.label(Part("pa"), "PA", side=Edge.NORTH)


def test_a_track_stands_on_a_labels_box_and_a_via_keeps_the_silk_clearance():
    b, key = _labelled_board()
    b.track(Net("SIG"), [Location(2.0, 2.0), Past([key], Edge.NORTH), Location(38.0, 2.0)], layer=CopperLayer.F)
    plan = b.resolve()
    box = plan._labelled[key][0].box
    assert _has(plan, "SIG", round(box.left + 0.5 * (box.right - box.left), 6), _away(box.top - 0.1, -1)), (box, _points(plan, "SIG"))
    b, key = _labelled_board()
    b.via(Net("VBUS"), at=Past([key], Edge.EAST), size=0.6)
    plan = b.resolve()
    box = plan._labelled[key][0].box
    (v,) = _vias(plan, "VBUS")
    assert (v.at.x, v.at.y) == (pytest.approx(_away(box.right + 0.3 + 0.2, 1), abs=1e-9),
                                pytest.approx(box.top + 0.5 * (box.bottom - box.top), abs=1e-6))


def _label_board(other: bool):
    """tests/test_label_gives_way.py's board: a labelled connector in cell conn, and cell other placed beside it,
    whose silk the label slides away from."""
    size = (4.4 - 0.15) / (5 * 0.914 + 2 / 9)
    fps = [footprint("J1", 30, 30, w=4, h=2, inst="conn.j1", nets=("A", "B"), cell="conn"),
           footprint("P1", 25, 28, w=4, h=6, inst="conn.p1", nets=("C", "D"), cell="conn"),
           footprint("U2", 0, 0, w=3, h=5, inst="other.u2", nets=("E", "F"), cell="other", silk_boxes=((-1.5, -2.5, 1.5, 2.5),))]
    b = Board(board_geometry(fps, cells=["conn", "other"], width=80, height=80, silk_clearance=0.2, extra_nets=["SIG"]),
              edge_margin=1.0, settings=dataclasses.replace(Settings(), place_envelope="physical"))
    b.place(Cell("conn"), at=Location(27, 28))
    key = b.label(Part("conn.j1"), "USB-C", side=Edge.NORTH, align=Along.START, knockout=True, size=size)
    if other:
        b.place(Cell("other"), at=Beside(Cell("conn"), Edge.EAST, align=Along.START))
    b.via(Net("SIG"), at=Past([key], Edge.NORTH), size=0.6)
    return b, key


def test_a_past_off_a_label_that_gave_way_is_where_the_label_ended():
    still, key = _label_board(other=False)
    moved, _ = _label_board(other=True)
    before = still.resolve()._labelled[key][0].box
    plan = moved.resolve()
    box = plan._labelled[key][0].box
    assert box != before                                                   # the label slid for the other cell's silk
    (v,) = _vias(plan, "SIG")
    assert v.at.y == pytest.approx(_away(box.top - 0.3 - 0.2, -1), abs=1e-9)


def test_a_past_off_a_part_that_found_no_place_or_its_label_is_not_drawn():
    big = _part("BIG", "big", "GND", 20.0, 15.0, w=60.0, h=60.0)          # larger than the board: no place
    b = Board(board_geometry([big], width=40, height=30, extra_nets=["SIG"]), edge_margin=EDGE)
    b.rect(width=40.0, height=30.0)
    b.place(Part("big"))
    key = b.label(Part("big"), "BIG")
    b.via(Net("SIG"), at=Past([Part("big")], Edge.WEST), size=0.6)
    b.via(Net("SIG"), at=Past([key], Edge.WEST), size=0.6)
    whys = sorted((f.facts["why"]["code"], f.facts["names"][0]) for f in _not_drawn(b.resolve()))
    assert whys == [("past_item_unplaced", "big"), ("past_label_not_drawn", "label big BIG")], whys
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles.py -q`
Expected: FAIL at collection, `ImportError: cannot import name 'LabelKey'`.

- [ ] **Step 3: Implement**

`values.py`: replace `_PAST_KINDS` and add `LabelKey` after it:

```python
_PAST_KINDS = ("pads (PadRef, CellPadRef), vias, tracks, cutouts (the Cutout given to holes=, or board.cutout(name)), "
               "stretches of the board edge or of a hole (board.edge(facing=), board.cutout(name).edge(side=)), parts "
               "and cells (Part, Cell), and labels (what board.label() returns)")


class LabelKey(str):
    """What `board.label()` returns: the label's key. A `str`, so a script that used it as text still can; a type of
    its own, so a `Past` can tell a label from any other string."""
    __slots__ = ()
```

In `Past.__post_init__` (Task 1): the item test becomes `elif not isinstance(it, (PadRef, CellPadRef, Cutout, CutoutHandle, Part, Cell, LabelKey)):`; the across tests become

```python
        if isinstance(a, (Run, CutoutEdge, LabelKey)):
            raise TypeError("Past's across= is a centre line to lie on: a stretch of edge has none (its middle is "
                            "Along.MID) and a label none worth naming; give a pad, a via, a cutout, a Part, a Cell or an Along")
        if not (a is None or isinstance(a, (PadRef, CellPadRef, Along, Cutout, CutoutHandle, Part, Cell))
                or (isinstance(a, CopperIntent) and a.key.split(" ")[0] == "via")):
            raise TypeError("Past's across is a PadRef, a via, a cutout, a Part, a Cell or Along.START/MID/END, not %r" % (a,))
```

In the docstring, the items sentence adds "parts and cells (`Part`, `Cell`: their envelope, and their pads as copper), and labels (what `board.label()` returns)", and the stand-off sentence adds "nothing from a part's or a cell's envelope (its pads keep their clearance) or, for a track, from a label (a via keeps the silk clearance)"; the across sentence adds "a part's or a cell's" centre line; the last line adds "every part, cell and label named placed (copper past a label is planned after the search)".

`refusals.py`, after Task 1's codes:

```python
    PAST_ITEM_UNPLACED = "past_item_unplaced"
    PAST_LABEL_NOT_DRAWN = "past_label_not_drawn"
```

```python
@renders(Code.PAST_ITEM_UNPLACED, "copper")
def _past_item_unplaced(f):
    return "%s found no place" % f["item"]


@renders(Code.PAST_LABEL_NOT_DRAWN, "copper")
def _past_label_not_drawn(f):
    return "%s is not drawn" % f["key"]
```

`layout.py`:
- line 47: add `LabelKey` to the `from .values import (...)` list.
- `Board.__init__`, after `self._label_ids: dict = {}` (998): `self._label_keys: dict = {}       # label key text -> the LabelKey board.label() returned: a Past names this board's`
- `label()` (5598-5609): the two `key = "label %s %s" % (...)` become `key = LabelKey("label %s %s" % (...))`, and after `self._label_ids[key] = (...)` add `self._label_keys[str(key)] = key`.
- `_check_past` (Task 1): in the first loop add

```python
            if isinstance(it, LabelKey) and self._label_keys.get(str(it)) is not it:
                raise TypeError("%s: %s is not a label of this board; name what this board's board.label() returned"
                                % (what, it))
            if isinstance(it, (Part, Cell)):
                self._item(it)                          # a real part or cell, checked now
```

  and its docstring says "its vias and tracks, its named cutouts, its labels, real parts and cells".
- `track()`: after `intent = self._copper_intent("track %s" % name, ...)` (5765) add

```python
        if any(isinstance(it, LabelKey) for p in points if isinstance(p, Past) for it in p.items):
            self._late_copper.add(intent.index)     # a label gives way to every part placed after it: planned after the search
```

- `via()`: in `plan`, `where = _past_point(self, ctx, name, s, at, intent.key, intent.index, via=True)     # s: the via's radius out`; after `intent = self._copper_intent("via %s" % name, ...)` (6089) add

```python
        if isinstance(at, Past) and any(isinstance(it, LabelKey) for it in at.items):
            self._late_copper.add(intent.index)     # a label gives way to every part placed after it: planned after the search
```

- `_past_name`: before the final `return` add

```python
    if isinstance(it, (Part, Cell)):
        return board._item(it)[1]
    if isinstance(it, LabelKey):
        return str(it)
```

- after `_round_away`, add:

```python
def _unplaced(board: "Board", occ: Occupancy, item) -> bool:
    """Whether a Part or a Cell has no place: a member not on the occupancy, or still pending (the search found none)."""
    return any(fp.ref not in occ.items or fp.ref in occ.pending for fp in members_of(board._item(item)[0]))
```

- `_past_copper`: before the `elif isinstance(it, (PadRef, CellPadRef)):` branch add

```python
        elif isinstance(it, (Part, Cell)):
            if _unplaced(board, occ, it):
                return Refusal(Code.PAST_ITEM_UNPLACED, item=name)
            out += [(sh.net, sh.box, sh.owner, "%s.%s" % (sh.owner, sh.label))
                    for fp in members_of(board._item(it)[0]) for sh in occ.items[fp.ref].shapes
                    if sh.kind in ("pad", "through") and (layer is None or layer in sh.layers)]
```

  and its docstring: "each pad's shapes (a named part's or cell's pads included), ... A Refusal instead when a via or track has no copper or a part or cell has no place."
- `_past_groups`: the signature becomes `(board, ctx, net, p, what, current=None, via=False)`; after the `elif isinstance(it, Run):` branch add

```python
        elif isinstance(it, (Part, Cell)):
            # no copper rule touches a courtyard: the envelope stands off at 0, its pads keep their clearance above
            groups.append(_PastGroup(board._placed_envelope_box(ctx.occ, it), 0.0, (name,)))
        elif isinstance(it, LabelKey):
            done = ctx.plan.__dict__.get("_labelled", {}) if ctx.plan is not None else {}
            if it not in done:
                return Refusal(Code.PAST_LABEL_NOT_DRAWN, key=str(it))
            # no rule between copper and silk: a track stands on the text's box; a via's ring is a mask opening, which
            # silk keeps the silk clearance from
            groups.append(_PastGroup(done[it][0].box, board.geometry.silk_clearance if via else 0.0, (name,)))
```

  and its docstring adds "A named part's or cell's pads join the copper group, and its placed envelope is a group of its own at 0. A label is a group of its own: its text's box, at 0 for a track and the silk clearance for a via (`via`)."
- `_past_point`: the signature becomes `(board, ctx, net, width, p, what, current=None, via=False)`, its first line `groups = _past_groups(board, ctx, net, p, what, current, via)`, and before the final `else:` of the across chain add

```python
        elif isinstance(a, (Part, Cell)):
            if _unplaced(board, ctx.occ, a):
                return Refusal(Code.PAST_ITEM_UNPLACED, item=board._item(a)[1])
            centre = board._placed_envelope_box(ctx.occ, a).center
            across = centre.y if upright else centre.x
```

`_refs_in` (11929-11934) needs no change: it already makes copper wait for a Part or Cell it names and reads nothing from a label's key.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles.py tests/test_past_copper.py tests/test_past_corner.py tests/test_past_corner_layer.py tests/test_labels.py tests/test_label_gives_way.py tests/test_label_line_gives_way.py tests/test_label_unplaced.py tests/test_label_on_board.py tests/test_label_yields_to_search.py tests/test_suggestions_copper_label.py tests/test_no_sentence_parsing.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/values.py src/placemat/layout.py src/placemat/refusals.py tests/test_past_obstacles.py
git commit -m "Past: a part's or a cell's envelope and a label are items; board.label() returns a LabelKey, a str"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 3: The corner verdict judges each group on the track's layer

**Files:**
- Modify: `src/placemat/layout.py:5750-5762` (the track's corner verdict), `_past_groups` (Tasks 1-2), remove `_past_reach` (11697-11727)
- Test: `tests/test_past_obstacles.py` (append)

**Interfaces:**
- Consumes: `_past_groups`, `_PastGroup`, `_box_corner`, `_point_seg` (copper.py 605, already imported in layout.py).
- Produces: `_past_groups(board, ctx, net, p, what, current=None, via=False, layer=None)`: with `layer`, the groups a rule judges against copper on that layer (the copper on it; every cutout and stretch of edge; no envelope, no label). `copper.corner` facts unchanged in shape: `names` are the names of every group passed too near, `near_mm`/`need_mm` those of the group with the largest shortfall.

- [ ] **Step 1: Write the failing tests**

```python
# ---------------------------------------------------------------- the corner verdict
def test_the_corner_verdict_names_the_group_a_leg_passes_too_near():
    pa = _part("PA", "pa", "GND", 10.0, 20.0)                             # pad SE corner (10.5, 20.5), reach 0.3
    vent = Cutout(Circle(1.5), "vent", at=Location(10.0, 23.0))          # grown box SE corner (10.77, 23.77), reach 0.5
    b = _board([pa], holes=[vent])
    px = _away(10.77 + 0.5 / math.sqrt(2.0), 1)
    # due north through the point: the leg passes the hole's corner 0.354 mm off, under its 0.5; the pad's 0.62 off
    b.track(Net("SIG"), [Location(px, 29.0), Past([PadRef(Part("pa"), 1), vent], Corner.SE), Location(px, 5.0)],
            layer=CopperLayer.F, chamfer=0)
    found = [f for f in b.resolve().findings if f.cause.value == "copper.corner"]
    assert len(found) == 1 and found[0].facts["names"] == ["cutout vent"], found
    assert found[0].facts["need_mm"] == pytest.approx(EDGE)


@pytest.mark.parametrize("layer, names", [(CopperLayer.F, [["PA.1"]]), (CopperLayer.B, [])], ids=["front", "back"])
def test_a_track_past_a_front_part_takes_its_point_off_the_part_and_is_judged_on_its_own_layer(layer, names):
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0)])                    # front only: pad SE (20.5, 15.5), courtyard SE (20.6, 15.6)
    # the courtyard's corner is the union's; the pad's reach sets the step: (20.5 - 20.6 + 15.5 - 15.6) / 2 + 0.3 / sqrt(2)
    d = max(0.1 / math.sqrt(2.0), -0.1 + 0.3 / math.sqrt(2.0))
    px, py = _away(20.6 + d, 1), _away(15.6 + d, 1)
    b.track(Net("SIG"), [Location(px, 29.0), Past([Part("pa")], Corner.SE), Location(px, 5.0)], layer=layer, chamfer=0)
    plan = b.resolve()
    assert _has(plan, "SIG", px, py), _points(plan, "SIG")               # the same point on either layer
    assert [f.facts["names"] for f in plan.findings if f.cause.value == "copper.corner"] == names
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles.py -q -k "corner_verdict or own_layer"`
Expected: `test_the_corner_verdict_names_the_group_a_leg_passes_too_near` FAILs (no finding: `_past_reach` reads copper only, so the hole's corner is not judged). The layer test already passes after Task 2 (a Part's pads are copper in `_past_copper`, filtered by layer); it pins that this task keeps it so.

- [ ] **Step 3: Implement**

`_past_groups` takes `layer=None` (signature `(board, ctx, net, p, what, current=None, via=False, layer=None)`); its first line passes it on, `copper = _past_copper(board, ctx.occ, ctx.ops_at, p, what, current, layer)`; and before `elif isinstance(it, (Part, Cell)):` add

```python
        elif layer is not None:
            continue                # an envelope or a label: no rule judges copper against it, so no verdict does
```

Its docstring adds: "With `layer`, the groups a corner verdict judges for copper on that layer: the copper on it, and every cutout and stretch of edge, which cut every layer."

Replace the corner verdict (5750-5762) with:

```python
            for p in corners:
                # the lane runs past every item named; the verdict judges the groups a rule judges this track's
                # layer against: the copper on it, every hole and stretch of edge
                groups = _past_groups(self, ctx, name, p, intent.key, intent.index, layer=layer)
                if isinstance(groups, Refusal):
                    continue
                short = []
                for g in groups:
                    c = _box_corner(g.box, p.edge)
                    reach = w / 2.0 + g.standoff
                    near = min((_point_seg(c, Location(*a), Location(*b))[0] for t in ops for a, b in t.chords()),
                               default=math.inf)
                    if near < reach - 1e-6:
                        short.append((reach - near, near, reach, g.names))
                if short:
                    _, near, reach, _ = max(short, key=lambda s: s[0])
                    names = list(dict.fromkeys(n for *_, ns in short for n in ns))
                    ctx.notes.append(Finding(C.COPPER_CORNER, {
                        "key": copper_id(intent), "net": name, "edge": p.edge.value, "names": names,
                        "near_mm": near - w / 2.0, "need_mm": reach - w / 2.0, "chamfer_mm": chamfer}, "critical"))
```

With copper alone there is one group, the same box, reach and names `_past_reach` gave, so the verdict is unchanged. Delete `_past_reach` (11697-11727); nothing else calls it (`grep -n "_past_reach" src/placemat/*.py` prints only the docstring of `tests/test_no_sentence_parsing.py:80`, which names it as a past example and needs no edit).

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles.py tests/test_past_corner.py tests/test_past_corner_layer.py tests/test_past_copper.py tests/test_suggestion_cases.py tests/test_finding_suggestions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_past_obstacles.py
git commit -m "Past at a corner: the verdict judges each group on the track's layer, holes and the edge on every layer, and names the one passed too near"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 4: Beside's align stands its pad past cutouts, the edge, parts and cells

**Files:**
- Modify: `src/placemat/layout.py:2423-2443` (`_check_beside_past`), `:2616-2654` (the "past" branch of `_beside_placement`), `:3373-3374` (Beside's needs), a new Board method `_beside_past_groups` after `_check_beside_past`; remove `_lane_distance` (11610-11621)
- Test: `tests/test_beside_past_obstacles.py` (new)

**Interfaces:**
- Consumes: `_cutout_box`, `_run_box` (Task 1), `Board._check_past` (Tasks 1-2), `cutout_token`, `Board._settled_cutouts`, `Board._cutout_free`, `_pad_shapes`, `Board._placed_envelope_box`.
- Produces: `Board._beside_past_groups(occ, past, own_net, own_owner) -> list[tuple[Box, float, float]]`: `(box, stand-off from the own pad's net, stand-off from the lane's net)` per group.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_beside_past_obstacles.py
"""Beside(item, side, align=(own_pad, Past(items, edge, lane=))) over a cutout, a stretch of the board edge, a part or
a cell: the own pad's facing edge stands past each, by the copper-to-edge clearance from a hole or the edge and by
nothing from an envelope (its pads keep their clearance); with `lane=`, by that plus the lane's width and its clearance
to the own pad. A via, a track, a label and a cutout with a freedom are refused: none has its place when a firm part is
placed. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import Beside, Box, Cutout, Edge, Face, Location, Near, Net, PadRef, Part, Past
from tests.fixtures import board_geometry, footprint, pad
from tests.test_beside_lane import CLASSES, G_C, LANE_C, LANE_W, _pad_box

SAG = 0.02
EDGE = 0.4


def _one_pad_part(ref, inst, net, cx, cy):
    p = pad(ref, inst, 1, net, cx, cy, 1.0, 1.0)
    body = Box(cx - 1.0, cy - 1.0, cx + 1.0, cy + 1.0)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board(holes=(), margin=1.0, with_c_in=False):
    fps = [footprint("CV", 20, 20, w=4, h=2, inst="c_vdd", nets=("VDD", "GND")),
           footprint("Q", 40, 40, w=3, h=1.5, inst="q", nets=("G", "OUT"))]
    if with_c_in:
        fps.append(_one_pad_part("CI", "c_in", "VIN", 26.0, 26.0))        # pad west side 25.5, courtyard 24.9
    geom = board_geometry(fps, width=60, height=60, extra_nets=["L"])
    classes = dict(geom.netclasses)
    classes.update(CLASSES)
    b = Board(dataclasses.replace(geom, netclasses=classes), edge_margin=margin)
    b.rect(width=60.0, height=60.0, holes=list(holes))
    b.place(Part("c_vdd"), at=Location(20, 20))
    if with_c_in:
        b.place(Part("c_in"), at=Location(26.0, 26.0))
    return b


VENT = Cutout(Circle(1.5), "vent", at=Location(26.0, 26.0))              # grown box west side 25.25 - 0.02


def test_beside_stands_its_pad_the_edge_clearance_past_a_cutout():
    b = _board([VENT])
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([VENT], Edge.WEST))))
    assert _pad_box(b.resolve(), "Q", 1).right == pytest.approx(26.0 - 0.75 - SAG - EDGE)


def test_beside_stands_its_pad_a_lane_past_a_cutout():
    b = _board([VENT])
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([VENT], Edge.WEST, lane=Net("L")))))
    # the hole to the lane, the lane's width, the lane to pad 1's net G
    assert _pad_box(b.resolve(), "Q", 1).right == pytest.approx(26.0 - 0.75 - SAG - (EDGE + LANE_W + max(LANE_C, G_C)))


def test_beside_stands_its_pad_on_an_envelope_where_its_courtyard_reaches_past_its_pads_clearance():
    b = _board(with_c_in=True)
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([Part("c_in")], Edge.WEST))))
    # the courtyard's west side 24.9 by 0; the pad's 25.5 by G to VIN, 0.25: 25.25; the outer is the courtyard's
    assert _pad_box(b.resolve(), "Q", 1).right == pytest.approx(24.9)


def test_beside_stands_its_pad_past_the_board_edge():
    b = _board(margin=0.0)
    b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([b.edge(facing=Edge.WEST)], Edge.EAST))))
    assert _pad_box(b.resolve(), "Q", 1).left == pytest.approx(EDGE)


def test_a_cutout_with_a_freedom_and_a_label_in_besides_past_are_refused():
    b = _board([Cutout(Circle(1.5), "vent", at=Near(PadRef(Part("c_vdd"), 1)), why="air")])
    with pytest.raises(ValueError, match="freedom"):
        b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([b.cutout("vent")], Edge.WEST))))
    key = b.label(Part("c_vdd"), "VDD")
    with pytest.raises(TypeError, match="gives way"):
        b.place(Part("q"), at=Beside(Part("c_vdd"), Edge.SOUTH, align=(1, Past([key], Edge.WEST))))
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_beside_past_obstacles.py -q`
Expected: FAIL (`_check_beside_past` calls `self._pad_ref(it)` on a Cutout).

- [ ] **Step 3: Implement**

Replace `_check_beside_past` (2423-2443) with:

```python
    def _check_beside_past(self, key: str, side: Edge, p: Past):
        """A Past in Beside's align: over pads, cutouts, stretches of edge, parts and cells - what has its place before
        the part is placed. Vias and tracks are planned after every placement, a label gives way to parts placed after
        it, and a cutout with a freedom is slid only once every firm item is down, so they are refused. No `across=`,
        since `side` decides that axis; and an edge on the other axis."""
        self._check_past(p, key, lane=True)
        for it in p.items:
            if isinstance(it, CopperIntent):
                raise TypeError("%s: a placement is decided before copper is planned; Past in Beside's align "
                                "takes pads, cutouts, stretches of edge, parts and cells, not %s" % (key, it.key))
            if isinstance(it, LabelKey):
                raise TypeError("%s: a label gives way to the parts placed after it, so its place is not known when this "
                                "part is placed; Past in Beside's align takes pads, cutouts, stretches of edge, parts "
                                "and cells, not %s" % (key, it))
            if isinstance(it, (Cutout, CutoutHandle, CutoutEdge)):
                if self._cutout_free(self._named_cutouts[it.name]):
                    raise ValueError("%s: cutout %r has a freedom, and the board slides such a hole only once every firm "
                                     "item is down; a Beside placement is firm, so give the cutout a decided place to "
                                     "stand this part past it" % (key, it.name))
            elif isinstance(it, (PadRef, CellPadRef)):
                self._pad_ref(it)                       # a real pad, checked now
        if p.across is not None:
            raise TypeError("%s: Beside's side decides where the part stands along the pads; Past in its "
                            "align takes no across=" % key)
        upright = side in (Edge.EAST, Edge.WEST)
        if isinstance(p.edge, Edge) and (p.edge in (Edge.EAST, Edge.WEST)) == upright:
            raise ValueError("%s: Beside on the %s side decides the part's %s; the Past in its align decides "
                             "the other axis, so its edge is %s, not %s" % (
                key, side.name, "x" if upright else "y",
                "NORTH or SOUTH" if upright else "EAST or WEST", p.edge.name))
        if p.lane is not None:
            self.geometry.require_net(p.lane)

    def _beside_past_groups(self, occ: Occupancy, past: Past, own_net: str, own_owner) -> list:
        """[(box, to own, to lane)] for each group of a Past in Beside's align: what the own pad's facing edge stands
        past. The pads (a named part's or cell's included) are one group: their box, the worst clearance from the own
        pad's net to theirs, and from theirs to the lane's net. A cutout or a stretch of edge: its box (as a track's Past
        reads it) and the copper-to-edge clearance either way. A part's or a cell's envelope: its box, and 0."""
        lane = self.geometry.require_net(past.lane) if past.lane is not None else None
        edge_rule = self.geometry.edge_clearance
        shapes, out = [], []
        for it in past.items:
            if isinstance(it, (PadRef, CellPadRef)):
                shapes += _pad_shapes(self, occ, it)
            elif isinstance(it, (Part, Cell)):
                shapes += [sh for fp in members_of(self._item(it)[0]) for sh in occ.items[fp.ref].shapes
                           if sh.kind in ("pad", "through")]
                out.append((self._placed_envelope_box(occ, it), 0.0, 0.0))
            elif isinstance(it, (Cutout, CutoutHandle, CutoutEdge)):
                out.append((_cutout_box(self, it), edge_rule, edge_rule))
            elif isinstance(it, Run):
                out.append((_run_box(self, it), edge_rule, edge_rule))
        if shapes:
            to_own = max(self._clearance(own_net, sh.net, own_owner, sh.owner) for sh in shapes)
            to_lane = max(self._clearance(sh.net, lane, sh.owner) for sh in shapes) if lane is not None else 0.0
            out.insert(0, (Box.union([sh.box for sh in shapes]), to_own, to_lane))
        return out
```

Beside's needs (3373-3374) become:

```python
            elif beside.align[0] == "past":
                for it in beside.align[2].items:
                    if isinstance(it, (Cutout, CutoutHandle, CutoutEdge)):
                        if it.name not in self._settled_cutouts:
                            needs.add(cutout_token(it.name))    # cut in the firm pass, before this part stands past it
                    elif not isinstance(it, Run):
                        needs.add(self._pad_ref(it)[0])         # a pad's part, a part, a cell: placed before this
```

In `_beside_placement`, replace the "past" branch from `shapes = [sh for ref in past.items ...]` (2624) to the end of the SOUTH/NORTH Edge branches (2654) with:

```python
            groups = self._beside_past_groups(occ, past, own_pad.net, own_pad.owner)
            box = Box.union([gb for gb, _, _ in groups])
            if past.lane is None:
                dists = [(gb, to_own) for gb, to_own, _ in groups]
            else:
                lane = self.geometry.require_net(past.lane)
                lw = self._width(lane, past.width)
                c_own = self._clearance(lane, own_pad.net, None, own_pad.owner)
                dists = [(gb, to_lane + lw + c_own) for gb, _, to_lane in groups]
            if isinstance(past.edge, Corner):
                # the own pad's corner that faces back across the 45 stands out along the diagonal from the union's
                # corner far enough to pass each group's corner at its distance; the side has decided one axis, this
                # the other
                sx, sy = past.edge.signs
                c = _box_corner(box, past.edge)
                qx = own.left if sx > 0 else own.right
                qy = own.top if sy > 0 else own.bottom

                def behind(gb):         # how far a group's corner stands behind the union's along the outward diagonal
                    gc = _box_corner(gb, past.edge)
                    return sx * (gc.x - c.x) + sy * (gc.y - c.y)
                reach = max(behind(gb) + dist * math.sqrt(2.0) for gb, dist in dists)
                if past.lane is not None:
                    # off the lane's own point as a track's Past takes it, rounded away from the items,
                    # so that rounding cannot put the lane's track nearer the own pad than its clearance
                    d = max(behind(gb) / 2.0 + (lw / 2.0 + to_lane) / math.sqrt(2.0) for gb, _, to_lane in groups)
                    px, py = _round_away(c.x + sx * d, sx), _round_away(c.y + sy * d, sy)
                    reach = (sx * (px - c.x) + sy * (py - c.y)
                             + (lw / 2.0 + self._clearance(lane, own_pad.net)) * math.sqrt(2.0))
                if ox is None:
                    ox = _round_away(c.x - qx + sx * (reach - sy * (qy + oy - c.y)), sx)
                else:
                    oy = _round_away(c.y - qy + sy * (reach - sx * (qx + ox - c.x)), sy)
            elif past.edge is Edge.EAST:
                ox = max(gb.right + dist for gb, dist in dists) - own.left
            elif past.edge is Edge.WEST:
                ox = min(gb.left - dist for gb, dist in dists) - own.right
            elif past.edge is Edge.SOUTH:
                oy = max(gb.bottom + dist for gb, dist in dists) - own.top
            else:
                oy = min(gb.top - dist for gb, dist in dists) - own.bottom
```

Over pads alone there is one group and each figure is `_lane_distance`'s, added in the same order, so the place is unchanged. Delete `_lane_distance` (11610-11621), which has no other caller. In `_BesideSpec`'s docstring (431) "a Past over pads" becomes "a Past over pads, cutouts, stretches of edge, parts and cells".

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_beside_past_obstacles.py tests/test_beside_lane.py tests/test_beside.py tests/test_beside_copper.py tests/test_beside_shapes.py tests/test_beside_migration.py tests/test_escape_past_part.py tests/test_past_obstacles.py -q`
Expected: PASS; `test_beside_lane.py` unchanged (its via refusal still says "decided before copper is planned").

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_beside_past_obstacles.py
git commit -m "Beside: a Past in its align stands the own pad past a decided cutout, the board edge, a part or a cell"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 5: Copper near a part's drilled hole is copper.meets

**Files:**
- Modify: `src/placemat/occupancy.py:994-1013` (`copper_conflicts`)
- Test: `tests/test_copper_holes.py` (new)

**Interfaces:**
- Consumes: `Occupancy._conflict` (2302), whose hole branch (`_hole_conflict`, 2465) and NPTH branch (2424-2434) already judge a hole against copper.
- Produces: `Occupancy.copper_conflicts(shape, check=True)` also returns `hole_copper`, `npth_near` and `npth_cuts` refusals against placed parts' `hole` and `npth` shapes; with `check=False` (placement) it is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_copper_holes.py
"""Declared copper nearer a part's drilled hole than the hole clearance is copper.meets, as a via's hole against copper
already is: a plated hole of another net (hole_copper, KiCad's HOLE_CLEARANCE_CONSTRAINT, the copper's own net
waived) and an unplated hole (npth_near under the clearance, npth_cuts over it). Placement asks what it asked before.
Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Track
from placemat.layout import Board, _shape_of
from placemat.values import Box, CopperLayer, Face, Location, Net, Part
from tests.fixtures import board_geometry, pad


def _through_part(net, cx=30.0, cy=15.0):
    """A 1 mm ring with a 0.5 mm drill: the drill's edge 0.25 from the centre, the ring's 0.5."""
    p = pad("H1", "h1", 1, net, cx, cy, 1.0, 1.0, through=True)
    body = Box(cx - 0.5, cy - 0.5, cx + 0.5, cy + 0.5)
    return Footprint("H1", "h1", None, "H1", Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _npth_part(cx=20.0, cy=15.0, drill=1.0):
    body = Box(cx - 1.0, cy - 1.0, cx + 1.0, cy + 1.0)
    return Footprint("M1", "m1", None, "M1", Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (),
                     npth=((Location(cx, cy), drill),))


def _board(fps, hole_clearance):
    g = dataclasses.replace(board_geometry(fps, width=40, height=30, extra_nets=["SIG", "A"]), hole_clearance=hole_clearance)
    b = Board(g, edge_margin=0.4)
    b.rect(width=40.0, height=30.0)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b


def _meets(plan):
    return [f.facts["hit"] for f in plan.findings if f.cause.value == "copper.meets"]


def test_a_track_under_the_hole_clearance_from_an_npth_is_copper_meets():
    b = _board([_npth_part()], hole_clearance=0.3)
    # the hole's edge at x = 19.5; the 0.2 mm track's east edge at 19.3: 0.2 from it, under 0.3
    b.track(Net("SIG"), [Location(19.2, 5.0), Location(19.2, 25.0)], layer=CopperLayer.F)
    (hit,) = _meets(b.resolve())
    assert hit["code"] == "npth_near" and hit["gap_mm"] == pytest.approx(0.2, abs=0.01) and hit["need_mm"] == 0.3


def test_a_track_over_an_npth_is_copper_meets_npth_cuts():
    b = _board([_npth_part()], hole_clearance=0.3)
    b.track(Net("SIG"), [Location(20.0, 5.0), Location(20.0, 25.0)], layer=CopperLayer.F)
    assert [h["code"] for h in _meets(b.resolve())] == ["npth_cuts"]


@pytest.mark.parametrize("net, codes", [("A", ["hole_copper"]), ("SIG", [])], ids=["another net", "its own net"])
def test_a_track_under_the_hole_clearance_from_a_plated_hole(net, codes):
    b = _board([_through_part(net)], hole_clearance=0.6)
    # the ring's west edge at 29.5, the drill's at 29.75; the track's east edge at 29.2: 0.3 from the ring (the 0.2
    # copper clearance holds) and 0.55 from the drill, under 0.6
    b.track(Net("SIG"), [Location(29.1, 5.0), Location(29.1, 25.0)], layer=CopperLayer.F)
    assert [h["code"] for h in _meets(b.resolve())] == codes


def test_placement_asks_what_it_asked_before():
    b = _board([_npth_part()], hole_clearance=0.3)
    occ = b.resolve().occupancy
    shape = _shape_of(Track("SIG", CopperLayer.F, 0.2, Location(19.2, 5.0), Location(19.2, 25.0)))
    assert occ.copper_conflicts(shape) == []
    assert [r.code.value for r in occ.copper_conflicts(shape, check=True)] == ["npth_near"]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_copper_holes.py -q`
Expected: FAIL: no `copper.meets` for the holes (the "its own net" case and the placement case pass already).

- [ ] **Step 3: Implement**

In `copper_conflicts` (994-1013), replace the docstring and the filter line (1001):

```python
    def copper_conflicts(self, shape: Shape, check: bool = False) -> list[Refusal]:
        """Every pad or copper of another net within clearance of `shape`. With `check` it is a finding's measure, which
        takes KiCad's DRC epsilon off a clearance whatever `[place] drc_epsilon` says, and judges the placed parts'
        drilled holes as well: a plated hole of another net at the hole clearance (`_hole_conflict`) and an unplated one
        (the NPTH branch of `_conflict`), as KiCad's DRC does. Placement's own questions keep to pads and copper."""
        kinds = ("pad", "through", "copper", "hole", "npth") if check else ("pad", "through", "copper")
        out = []
        for owner, g in self.items.items():
            if owner in self.pending:
                continue                        # not placed yet: its pads are nowhere
            for o in g.shapes:                  # its pads, its own copper graphics (a net-tie's winding), and with check its holes
                if o.kind not in kinds or not shape.box.overlaps(o.box, gap=self._copper_reach):
                    continue
```

(the rest of the function unchanged). The box test's `_copper_reach` already covers the hole clearance: `Occupancy.__init__` refuses a `[place] conflict_reach` under it (occupancy.py 501-505), and `_copper_reach` is at least that.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_copper_holes.py tests/test_hole_clearance.py tests/test_hole_spacing.py tests/test_occupancy.py tests/test_vias_give_way.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/occupancy.py tests/test_copper_holes.py
git commit -m "copper.meets: declared copper nearer a part's plated or unplated hole than the hole clearance, as KiCad judges it"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 6: copper.edge

Confirm the two "needs a user decision" gaps (6 and 7 below) before starting this task; the code below is written for the recommended resolutions.

**Files:**
- Modify: `src/placemat/findings.py:81-83` (a cause), `src/placemat/finding_text.py:750-758` (a renderer after `copper.meets`)
- Modify: `src/placemat/layout.py:8766-8815` (`_plan_copper_batch`'s loop), a new Board method `_edge_hits` after `_past_off_board` (Task 1), module functions `_nearest_on`, `_toward`, `_copper_point`, `_copper_loop_gap`, `_sides_past` after `_corner_step`, `from .cutouts import inside as _in_loop, crosses as _crosses`
- Modify: `src/placemat/suggestions.py:1091-1107` (a case after `copper_meets`), `src/placemat/script_edit.py:924-933` (`edit_list` add takes `at`)
- Modify: `skills/placemat/references/api.md:4822` (a row of the suggestions table)
- Test: `tests/test_copper_edge.py` (new), `tests/test_finding_text.py:62-74` (a sample), `tests/test_script_edit_more.py` (append)

**Interfaces:**
- Consumes: `Board._edge_loop_info()`, `Board._judges_edge()` (Task 1); `Occupancy.clear_limit(need, check=True)`; `Shape.circle`, `Shape.segment`, `Shape.poly`, `Shape.box`; `cutouts.inside`, `cutouts.crosses`; `copper_id`.
- Produces:
  - `FindingCause.COPPER_EDGE = (FindingKind.COPPER, "copper.edge")`, severity critical (the kind's default).
  - Facts: `key` (copper_id or ""), `net`, `word` (`track`, `via`, `pour`, `finger`), `layer` (the op layer's name, `""` for a via), `obstacle` (`{"form": "outline"}` or `{"form": "cutout", "name": str | None}`), `inside` (bool), `at` ([x, y]), `gap_mm`, `need_mm` (`geometry.edge_clearance`), `sag_mm` (the arc allowance judged with, 0 for a straight loop), `rule` (`"copper_edge_clearance"`), `sides` (Edge names a Past off the cutout could take, nearest first; `[]` for the outline), `waypoints` (the track's declared waypoints, else 0).
  - `Board._edge_hits(occ, shape, loops) -> list[dict]` (the facts above less `key`, `net`, `word`, `layer`, `waypoints`).
  - `suggestions.copper_edge(f, settings) -> list[Pick]`; `script_edit` `edit_list` with `{"action": "add", "at": int}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_copper_edge.py
"""Declared copper nearer the board's outline or a cutout than the copper-to-edge clearance is a copper.edge finding
when it is planned: KiCad's copper_edge_clearance (drc_test_provider_edge_clearance.cpp testAgainstEdge collides the
copper's shape with each Edge.Cuts shape at the clearance less the DRC epsilon, a touch at a clearance of 0). A loop
drawn from arcs is judged geometry.arc_sag further. The copper is drawn either way. Pure: synthetic boards."""
import re

import pytest

from placemat.copper import Track
from placemat.cutouts import Circle
from placemat.layout import Board, copper_id
from placemat.values import CopperLayer, Cutout, Edge, Location, Net, PadRef, Part, Past
from tests.fixtures import board_geometry
from tests.suggest_support import apply_and_resolve, resolve
from tests.test_past_obstacles import EDGE, SAG, W3A, _board, _part

VENT = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))              # box x 19.25..20.75, y 14.25..15.75


def _edge(plan):
    return [f for f in plan.findings if f.cause.value == "copper.edge"]


def test_the_reported_case_a_3a_track_drawn_across_the_vent():
    b = _board(holes=[VENT])
    t = b.track(Net("VBUS"), [Location(20.0, 5.0), Location(20.0, 25.0)], layer=CopperLayer.B, width=W3A)
    plan = b.resolve()
    (f,) = _edge(plan)
    assert f.severity == "critical" and f.facts["key"] == copper_id(t)
    assert (f.facts["word"], f.facts["layer"], f.facts["net"]) == ("track", "B", "VBUS")
    assert f.facts["obstacle"] == {"form": "cutout", "name": "vent"} and f.facts["inside"] is False
    assert f.facts["gap_mm"] == 0.0 and f.facts["need_mm"] == EDGE and f.facts["sag_mm"] == SAG
    assert f.facts["rule"] == "copper_edge_clearance" and f.facts["sides"] == ["WEST", "EAST"]
    assert f.facts["at"][0] == pytest.approx(20.0) and f.facts["at"][1] in (pytest.approx(14.25), pytest.approx(15.75))
    assert re.fullmatch(r'track VBUS on B\.Cu: 0\.00 mm from cutout "vent" at \(20\.00, 1[45]\.[27]5\), under the '
                        r"board's 0\.40 mm copper-to-edge clearance", str(f)), str(f)
    assert any(isinstance(op, Track) and op.net == "VBUS" for op in plan.copper)          # drawn all the same


def test_the_reported_case_passed_with_past_is_clear():
    b = _board(holes=[VENT])
    b.track(Net("VBUS"), [Location(20.0, 5.0), Past([VENT], Edge.WEST), Location(20.0, 25.0)], layer=CopperLayer.B,
            width=W3A)
    assert _edge(b.resolve()) == []


@pytest.mark.parametrize("x, gap", [(0.4, 0.3), (0.5, None)], ids=["inside the clearance", "at it"])
def test_a_track_by_a_straight_outline_side(x, gap):
    b = _board()
    b.track(Net("SIG"), [Location(x, 5.0), Location(x, 25.0)], layer=CopperLayer.F)
    found = _edge(b.resolve())
    if gap is None:
        assert found == []
    else:
        (f,) = found
        assert f.facts["obstacle"] == {"form": "outline"} and f.facts["gap_mm"] == pytest.approx(gap)
        assert f.facts["sag_mm"] == 0.0 and f.facts["sides"] == [] and "the board's edge" in str(f)


@pytest.mark.parametrize("x, found", [(19.25 - EDGE - SAG / 2 - 0.1, 1), (19.25 - EDGE - SAG - 0.1, 0)],
                         ids=["within the arc allowance", "past it"])
def test_a_round_cutout_is_judged_with_the_arc_allowance(x, found):
    b = _board(holes=[VENT])
    b.track(Net("SIG"), [Location(x, 5.0), Location(x, 25.0)], layer=CopperLayer.F)
    assert len(_edge(b.resolve())) == found


def test_a_via_wholly_inside_a_cutout_lies_inside_it():
    b = _board(holes=[Cutout(Circle(3.0), "well", at=Location(20.0, 15.0))])
    b.via(Net("SIG"), at=Location(20.0, 15.0), size=0.6)
    (f,) = _edge(b.resolve())
    assert (f.facts["inside"], f.facts["gap_mm"], f.facts["word"], f.facts["layer"]) == (True, 0.0, "via", "")
    assert str(f) == 'via SIG: lies inside cutout "well"'


def test_a_pour_by_points_over_the_outline_is_a_finding_and_a_plane_is_not():
    b = _board()
    b.pour(Net("SIG"), [Location(-1.0, 5.0), Location(5.0, 5.0), Location(5.0, 10.0), Location(-1.0, 10.0)],
           layer=CopperLayer.F)
    b.plane(Net("GND"), [CopperLayer.B])
    found = _edge(b.resolve())
    assert [(f.facts["word"], f.facts["obstacle"]["form"], f.facts["gap_mm"]) for f in found] == [("pour", "outline", 0.0)]


def test_a_fitted_pour_by_the_edge_keeps_its_own_clearance():
    pads = [_part("PA", "pa", "SIG", 1.9, 10.0), _part("PB", "pb", "SIG", 1.9, 20.0)]
    b = _board(pads)
    b.pour(Net("SIG"), [PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], layer=CopperLayer.F, swallow_pads=True)
    assert _edge(b.resolve()) == []


def test_a_pour_over_a_whole_hole_is_0_from_it():
    """Review focus 4: KiCad collides the filled shape with the hole's Edge.Cuts shapes."""
    b = _board(holes=[VENT])
    b.pour(Net("SIG"), [Location(15.0, 10.0), Location(25.0, 10.0), Location(25.0, 20.0), Location(15.0, 20.0)],
           layer=CopperLayer.F)
    (f,) = _edge(b.resolve())
    assert f.facts["obstacle"] == {"form": "cutout", "name": "vent"} and f.facts["gap_mm"] == 0.0
    assert f.facts["inside"] is False


def test_with_no_edge_clearance_only_a_touch_is_a_finding():
    """Review focus 5: a clearance of 0 still reports copper on the edge (KiCad collides at max(0, clearance - eps))."""
    b = _board(holes=[VENT], edge_clearance=0.0, margin=0.0)
    b.track(Net("SIG"), [Location(19.1, 5.0), Location(19.1, 25.0)], layer=CopperLayer.F)   # 0.05 mm clear of the hole
    b.track(Net("VBUS"), [Location(20.0, 5.0), Location(20.0, 25.0)], layer=CopperLayer.B)  # across it
    assert [f.facts["net"] for f in _edge(b.resolve())] == ["VBUS"]


def test_a_module_frame_is_not_an_edge():
    """Review focus 1: a fragment's frame is never written to Edge.Cuts."""
    b = _board(draw=False)
    b.track(Net("SIG"), [Location(0.0, 5.0), Location(0.0, 25.0)], layer=CopperLayer.F)
    assert _edge(b.resolve()) == []


IMPORTS = "from placemat import board, CopperLayer, Cutout, Edge, Location, Net, Past\nfrom placemat.cutouts import Circle\n"
ACROSS = '''board.rect(width=60, height=60, holes=[Cutout(Circle(1.5), "vent", at=Location(30, 30))])
board.track(Net("OUT"), [Location(30, 20), Location(30, 40)], layer=CopperLayer.B, width=1.37)
'''


def test_a_track_across_a_cutout_is_offered_a_past_off_it_on_each_side_and_the_first_clears_it(tmp_path):
    board, plan, path = resolve(tmp_path, ACROSS, imports=IMPORTS)
    (f,) = _edge(plan)
    texts = [s.text for s in f.suggestions]
    assert texts == ["Pass cutout `vent` on its west side with a Past waypoint",
                     "Pass cutout `vent` on its east side with a Past waypoint"], texts
    board2, plan2 = apply_and_resolve(tmp_path, plan, f.suggestions[0].id, path)
    assert 'Past([board.cutout("vent")], Edge.WEST)' in path.read_text()
    assert _edge(plan2) == []
```

Append to `tests/test_script_edit_more.py`:

```python
HEAD_PAST = "from placemat import board, Edge, PadRef, Part, Past\n\n"


def test_edit_list_adds_an_element_at_a_position():
    text = HEAD_PAST + 'board.track("A", [PadRef(Part("u1"), 1), PadRef(Part("u2"), 2)], layer=1)\n'
    out = run("edit_list", text, "board.track", kind="track", key="A", args={"arg": "points", "action": "add", "at": 1},
              value={"form": "Past", "args": [{"list": [{"form": "board.cutout", "args": [{"str": "vent"}]}]},
                                              {"enum": "Edge.WEST"}]})
    assert out.endswith('board.track("A", [PadRef(Part("u1"), 1), Past([board.cutout("vent")], Edge.WEST), '
                        'PadRef(Part("u2"), 2)], layer=1)\n')
```

(`run` is already imported there from `tests.test_script_edit`; the shared `HEAD` imports neither `Past` nor `PadRef`, so this test has its own.)

In `tests/test_finding_text.py`, after the `C.COPPER_MEETS` sample (62-64), add:

```python
    (C.COPPER_EDGE, {"key": "track VBUS#3", "net": "VBUS", "word": "track", "layer": "B",
                     "obstacle": {"form": "cutout", "name": "vent"}, "inside": False, "at": [18.62, 12.4], "gap_mm": 0.0,
                     "need_mm": 0.5, "sag_mm": 0.02, "rule": "copper_edge_clearance", "sides": ["WEST", "EAST"],
                     "waypoints": 0},
     'track VBUS on B.Cu: 0.00 mm from cutout "vent" at (18.62, 12.40), under the board\'s 0.50 mm copper-to-edge clearance'),
    (C.COPPER_EDGE, {"key": "via SIG#1", "net": "SIG", "word": "via", "layer": "", "obstacle": {"form": "outline"},
                     "inside": False, "at": [0.71, 3.0], "gap_mm": 0.41, "need_mm": 0.4, "sag_mm": 0.02,
                     "rule": "copper_edge_clearance", "sides": [], "waypoints": 0},
     "via SIG: 0.41 mm from the board's edge at (0.71, 3.00), under the board's 0.40 mm copper-to-edge clearance with "
     "0.02 mm for its curve"),
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_copper_edge.py tests/test_finding_text.py tests/test_script_edit_more.py -q`
Expected: FAIL (`AttributeError: COPPER_EDGE`, no `copper.edge` findings, `EditRefused` on an unknown `at`).

- [ ] **Step 3: Implement**

`findings.py`, after `COPPER_MEETS` (81): `COPPER_EDGE = (FindingKind.COPPER, "copper.edge")`. The `COPPER` kind comment (19) becomes `# planned copper that meets another net, a hole or the edge, crosses a keepout, or cannot bridge`.

`finding_text.py`, after `_copper_meets` (750-758):

```python
@renders(C.COPPER_EDGE, "net", "word", "layer", "obstacle", "inside", "at", "gap_mm", "need_mm")
def _copper_edge(f):
    """Declared copper nearer the board's outline or a cutout than the copper-to-edge clearance. The curve's allowance
    (`sag_mm`) is said only where the gap is the clearance or more, so the sentence never reads as a gap over its rule."""
    from .values import CopperLayer
    who = "%s %s" % (f["word"], f["net"] or "-") + (" on %s" % CopperLayer[f["layer"]].value if f["layer"] else "")
    ob = f["obstacle"]
    if ob["form"] == "outline":
        where, inside = "the board's edge", "lies off the board"
    else:
        where = 'cutout "%s"' % ob["name"] if ob.get("name") else "a cutout"
        inside = "lies inside " + where
    if f["inside"]:
        return "%s: %s" % (who, inside)
    tail = " with %.2f mm for its curve" % f["sag_mm"] if f.get("sag_mm") and f["gap_mm"] >= f["need_mm"] else ""
    return "%s: %.2f mm from %s at (%.2f, %.2f), under the board's %.2f mm copper-to-edge clearance%s" % (
        who, f["gap_mm"], where, f["at"][0], f["at"][1], f["need_mm"], tail)
```

`layout.py`, line 37: `from .cutouts import Arc, Cutouts, Path, _turned, crosses as _crosses, inside as _in_loop, loop_gap, signed_area`.

After `_past_off_board` (Task 1) add:

```python
    def _edge_hits(self, occ: Occupancy, shape: Shape, loops: list) -> list:
        """The loops of the board's edge `shape` (planned copper's real outline) comes nearer than the copper-to-edge
        clearance, as a copper.edge finding's facts each, less the declaration's own. KiCad's EDGE_CLEARANCE_CONSTRAINT,
        `geometry.edge_clearance` (drc_test_provider_edge_clearance.cpp testAgainstEdge collides the copper's shape with
        each Edge.Cuts shape at the clearance less the DRC epsilon, at 0 a touch): `clear_limit(check=True)`, and a gap of
        0 whatever the clearance. A loop drawn from arcs is judged `geometry.arc_sag` further, since its chords stand that
        far inside the curve KiCad judges. Copper wholly inside a hole or off the board is 0 from it, `inside`."""
        need = self.geometry.edge_clearance
        sag = self.settings.geometry_arc_sag
        if self._shaped().why_not(shape.box, need + sag) is None:
            return []                       # on the board, and every loop further off than the most any loop asks
        out = []
        for k, loop, curved, name in loops:
            allow = sag if curved else 0.0
            limit = occ.clear_limit(need + allow, check=True)
            if k > 0 and not Box.of_points(loop).overlaps(shape.box, gap=max(limit, 0.0) + 1e-6):
                continue
            gap, at = _copper_loop_gap(shape, loop)
            inside = False
            probe = _copper_point(shape)
            if gap > 0.0 and (k == 0) != _in_loop(loop, Location(*probe)):
                gap, inside, at = 0.0, True, probe          # off the board, or in a hole, touching neither edge
            if gap > 0.0 and gap >= limit:
                continue
            out.append({"obstacle": {"form": "outline"} if k == 0 else {"form": "cutout", "name": name},
                        "inside": inside, "at": [round(at[0], 6), round(at[1], 6)], "gap_mm": round(gap, 6),
                        "need_mm": need, "sag_mm": allow, "rule": "copper_edge_clearance",
                        "sides": [] if k == 0 else _sides_past(shape, Box.of_points(loop))})
        return out
```

After `_corner_step` add:

```python
def _seg_nearest(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple:
    """The point of segment a-b nearest p."""
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-18 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return ax + t * dx, ay + t * dy


def _nearest_on(pts: list, loop) -> tuple:
    """(the least distance between the polyline `pts` (one point, two, or a polygon given closed) and the closed `loop`,
    the point of `pts` where it is reached, the point of `loop`). Where a leg crosses the loop: 0 and the crossing, twice.
    The least distance between two polylines is reached at a vertex of one of them, so the vertices of each are taken
    against the legs of the other."""
    ring = list(loop) + [loop[0]]
    loop_legs = list(zip(ring, ring[1:]))
    legs = list(zip(pts, pts[1:])) or [(pts[0], pts[0])]
    best = (math.inf, pts[0], ring[0])
    for (ax, ay), (bx, by) in legs:
        for (cx, cy), (dx, dy) in loop_legs:
            if _crosses(ax, ay, bx, by, cx, cy, dx, dy):
                den = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
                t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / den
                hit = (ax + t * (bx - ax), ay + t * (by - ay))
                return 0.0, hit, hit
            for p in ((ax, ay), (bx, by)):
                q = _seg_nearest(p[0], p[1], cx, cy, dx, dy)
                d = math.hypot(p[0] - q[0], p[1] - q[1])
                if d < best[0]:
                    best = (d, p, q)
            for q in ((cx, cy), (dx, dy)):
                p = _seg_nearest(q[0], q[1], ax, ay, bx, by)
                d = math.hypot(p[0] - q[0], p[1] - q[1])
                if d < best[0]:
                    best = (d, p, q)
    return best


def _toward(p, q, r: float) -> tuple:
    """`p` moved `r` toward `q`, no further than `q`: the copper's own edge on the way to the loop."""
    d = math.hypot(q[0] - p[0], q[1] - p[1])
    if d <= r or d < 1e-12:
        return (q[0], q[1])
    return (p[0] + (q[0] - p[0]) * r / d, p[1] + (q[1] - p[1]) * r / d)


def _copper_point(shape: Shape) -> tuple:
    """A point of planned copper, to ask which side of a loop it lies on: a via's centre, a track's start, a polygon's
    first vertex."""
    if shape.circle:
        return (shape.circle[0], shape.circle[1])
    if shape.segment:
        return (shape.segment[0], shape.segment[1])
    return (shape.poly[0][0], shape.poly[0][1])


def _copper_loop_gap(shape: Shape, loop) -> tuple:
    """(gap, the copper's point nearest `loop`) between planned copper and one loop of the board's edge. A via is its
    circle and a straight track its centreline less half its width, as KiCad's shapes are; anything else (a pour, an arc
    track) its polygon, which is 0 from a loop it covers whole (KiCad collides the filled shape with the loop's edges)."""
    if shape.circle:
        cx, cy, r = shape.circle
        d, _, q = _nearest_on([(cx, cy)], loop)
        return max(0.0, d - r), _toward((cx, cy), q, r)
    if shape.segment:
        x1, y1, x2, y2, w = shape.segment
        d, p, q = _nearest_on([(x1, y1), (x2, y2)], loop)
        return max(0.0, d - w / 2.0), _toward(p, q, w / 2.0)
    poly = [tuple(v) for v in shape.poly]
    if point_in_polygon(tuple(loop[0]), poly):
        return 0.0, (loop[0][0], loop[0][1])
    d, p, _ = _nearest_on(poly + poly[:1], loop)
    return d, p


def _sides_past(shape: Shape, box: Box) -> list:
    """The sides of a cutout's box a Past could pass it on to clear `shape`, as Edge names: across a straight track's
    run, the side its centreline lies toward first (WEST before EAST, NORTH before SOUTH where it runs through the
    middle); for other copper, the side its box's centre lies toward."""
    c = box.center
    if shape.segment:
        x1, y1, x2, y2, _ = shape.segment
        px, py = _seg_nearest(c.x, c.y, x1, y1, x2, y2)
        if abs(x2 - x1) >= abs(y2 - y1):                 # it runs east-west: pass the hole north or south of it
            return ["SOUTH", "NORTH"] if py > c.y else ["NORTH", "SOUTH"]
        return ["EAST", "WEST"] if px > c.x else ["WEST", "EAST"]
    m = shape.box.center
    if abs(m.x - c.x) >= abs(m.y - c.y):
        return ["EAST" if m.x > c.x else "WEST"]
    return ["SOUTH" if m.y > c.y else "NORTH"]
```

In `_plan_copper_batch`, before `laid = {}` (8771) add `edge_loops = self._edge_loop_info() if self._judges_edge() else None     # the loops copper.edge judges`. Replace the body of `if not skip_findings:` (8784-8813) with:

```python
            if not skip_findings:
                which = owner_id.get(id(op)) or (next(iter(track_ids[op.net])) if len(track_ids.get(op.net, ())) == 1 else None)
                declared = next((c.declared for c in intents if which and copper_id(c) == which), {})
                layer = getattr(op, "layer", None)
                hits = occ.copper_conflicts(shape, check=True)       # a finding: KiCad's DRC epsilon, whatever placement uses
                # and this batch's own copper planned before it, which reaches the occupancy only
                # once the batch is done: a track of one net through a via of another, both planned
                # together. Tracks that cross are the bridging's to settle.
                for earlier, o in batch:
                    if o.net == shape.net or not shape.box.overlaps(o.box, gap=occ._copper_reach):
                        continue
                    if isinstance(op, Track) and isinstance(earlier, Track) and any(
                            segments_intersect(p1, p2, q1, q2) for p1, p2 in op.chords() for q1, q2 in earlier.chords()):
                        continue
                    why = occ._conflict(shape, o, None, exact=True, check=True)
                    if why:
                        hits.append(why)
                for hit in hits:
                    extra = {}
                    if isinstance(op, Track) and op.chamfer_cut:
                        extra["chamfer_at"] = [(op.start.x + op.end.x) / 2.0, (op.start.y + op.end.y) / 2.0]
                    elif isinstance(op, Track) and op.mid is not None:
                        extra["arc_radius_mm"] = arc_circle(op.start, op.mid, op.end)[2]
                        extra["arc_at"] = [op.mid.x, op.mid.y]
                    facts = {"key": which or "", "net": op.net, "word": type(op).__name__.lower(),
                             "layer": layer.name if layer is not None else "", "waypoints": declared.get("waypoints", 0),
                             "chamfer_hit": isinstance(op, Track) and bool(op.chamfer_cut),
                             "arc_hit": isinstance(op, Track) and op.mid is not None,
                             "chamfer_mm": declared.get("chamfer"), "radius_mm": declared.get("radius"),
                             "hit": hit.to_json(), **extra}
                    plan.findings.append(self._finding(C.COPPER_MEETS, facts))
                if edge_loops is not None:
                    word = "finger" if key.startswith("finger") else type(op).__name__.lower()
                    for facts in self._edge_hits(occ, shape, edge_loops):
                        plan.findings.append(self._finding(C.COPPER_EDGE, dict(
                            facts, key=which or "", net=op.net, word=word,
                            layer=layer.name if layer is not None else "", waypoints=declared.get("waypoints", 0))))
```

(`key` is the loop's own `key = owner.get(id(op)) or ...` from 8774; the `copper.meets` facts are as before, `which`, `declared` and `layer` computed once per op instead of once per hit.)

`script_edit.py`, in `_edit_list`'s `if action == "add":` (924-933), before `if edit.args.get("before") is not None:` add

```python
        if edit.args.get("at") is not None:
            k = int(edit.args["at"])
            if not 0 <= k <= len(sources):
                raise EditRefused("the list has no place %d" % k)
        elif edit.args.get("before") is not None:
```

(the existing `if ... before` becomes that `elif`, and `k = len(sources)` stays above as the default).

`suggestions.py`, after `copper_meets` (1091-1107):

```python
@case(C.COPPER_EDGE)
def copper_edge(f, settings):
    """A track drawn pad to pad past a named cutout: a Past off the cutout as its one waypoint, on each side across the
    track's run that the finding names (`sides`), the side it lies toward first. A track with waypoints already has
    its way said, so it is offered none; nor is copper inside the hole, or near the outline."""
    ob = f.get("obstacle") or {}
    if f.get("word") != "track" or not f.get("key") or f.get("inside") or ob.get("form") != "cutout" \
            or not ob.get("name") or f.get("waypoints", 0) != 0:
        return []
    out = []
    for side in f.get("sides") or ():
        value = _form("Past", {"list": [_form("board.cutout", {"str": ob["name"]})]}, _enum("Edge.%s" % side))
        edits = (Edit("ensure_import", None, {"names": ["Edge", "Past"]}),
                 Edit("edit_list", Target("track", f["key"]), {"arg": "points", "action": "add", "at": 1}, value,
                      _refs_of(value)))
        out.append(Pick("Pass cutout `%s` on its %s side with a Past waypoint" % (ob["name"], side.lower()), edits, "past"))
    return out
```

`api.md`, the suggestions table: after the `copper.meets` row (4822) add

```markdown
| `copper.edge` | for a track drawn pad to pad past a named cutout, a `Past` off the cutout as its one waypoint, on each side across the track's run, the side it lies toward first |
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_copper_edge.py tests/test_finding_text.py tests/test_script_edit_more.py tests/test_suggestion_cases.py tests/test_no_sentence_parsing.py tests/test_past_obstacles.py tests/test_copper_holes.py -q`
Expected: PASS.

- [ ] **Step 5: The default suite, and what the check now finds in it**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests -q 2>&1 | tee /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/suite-task6.out | tail -20`
Expected: PASS. A test that fails because a plan now carries `copper.edge` (or a hole `copper.meets`) is judged against its geometry: if its copper really is within the fixture's copper-to-edge clearance of its outline (`tests/fixtures.board_geometry` uses 0.4 mm) or of a hole, the finding is right; move that test's copper inboard, or give that test's board the edge clearance it means, without changing what the test is about. Never narrow `_edge_hits` or `_judges_edge` to make a test pass. List each test changed, and why, in the commit message. Keep CPU light: `-n 2`.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/findings.py src/placemat/finding_text.py src/placemat/layout.py src/placemat/suggestions.py src/placemat/script_edit.py skills/placemat/references/api.md tests/test_copper_edge.py tests/test_finding_text.py tests/test_script_edit_more.py
git commit -m "copper.edge: declared copper nearer the outline or a cutout than the copper-to-edge clearance, raised when it is planned; a Past off the cutout is offered"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
(add any test files Step 5 changed). Expected: the grep prints nothing.

---

### Task 7: The reported case on a real board, judged by KiCad

**Files:**
- Test: `tests/test_past_obstacles_real.py` (new); `tests/slow_tests.txt`

**Interfaces:**
- Consumes: `fixtures/fairing/vent_silk` (one back-face two-pin through-hole connector J1, both pads on GND; copper-to-edge clearance 0.4 mm, as `tests/test_cutout_silk_real.py` uses it), `placemat.kicad.write.apply_plan`, `placemat.kicad.drc.run_drc`.
- Produces: nothing new; proof that `copper.edge` agrees with KiCad's `copper_edge_clearance` and that `Past([vent], Edge.WEST)` satisfies it.

- [ ] **Step 1: Write the test**

```python
# tests/test_past_obstacles_real.py
"""The reported case on a real board (fixtures/fairing/vent_silk: the connector a 1.5 mm vent is cut beside, as a run
wrote it). A 3 A track on B.Cu drawn straight across the vent gave KiCad's copper_edge_clearance at 0.0 mm and nothing in
the run's own findings. The run now says so itself, as copper.edge, and `Past([vent], Edge.WEST)` takes the track past
the vent at the copper-to-edge clearance, which KiCad's DRC accepts. The vent is cut where `Near(PadRef(J1, 2))` cuts it
on this board (tests/test_cutout_silk_real.py), as a decided place, so the track's ends can be said."""
import json
import pathlib
import shutil

import pytest

from tests.conftest import needs_kicad

pytestmark = [needs_kicad, pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")]

pytest.importorskip("pcbnew")

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/vent_silk"
W3A = 1.37                  # 3 A on 1 oz outer copper at a 10 C rise (IPC-2221)
VENT_AT = (14.4, 31.16)     # its box x 13.65..15.15


def _run(tmp_path, past: bool):
    from placemat.cutouts import Circle
    from placemat.kicad.drc import run_drc
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    from placemat.layout import Board
    from placemat.values import CopperLayer, Cutout, Edge, Face, Location, Net, Part, Past
    shutil.copytree(FIXTURE, tmp_path / "board")
    pcb = tmp_path / "board/layout.kicad_pcb"
    b = Board(read_board(str(pcb)))
    vent = Cutout(Circle(1.5), "vent", at=Location(*VENT_AT), why="equalises two sealed chambers")
    b.rect(width=40.0, height=50.0, holes=[vent])
    b.place(Part("J1"), at=Location(17.0, 33.7), rotation=90.0, face=Face.BACK)
    middle = [Past([vent], Edge.WEST)] if past else []
    b.track(Net("GND"), [Location(14.4, 24.0)] + middle + [Location(14.4, 38.0)], layer=CopperLayer.B, width=W3A)
    plan = b.resolve()
    apply_plan(pcb, plan)
    run_drc(pcb, tmp_path / "drc.json", refill_zones=False)
    kicad = [v for v in json.loads((tmp_path / "drc.json").read_text())["violations"]
             if v["type"] == "copper_edge_clearance"]
    return plan, kicad


def test_a_3a_track_drawn_across_the_vent_is_copper_edge_as_kicad_says(tmp_path):
    plan, kicad = _run(tmp_path, past=False)
    found = [f for f in plan.findings if f.cause.value == "copper.edge"]
    assert len(found) == 1, plan.findings
    assert found[0].facts["obstacle"] == {"form": "cutout", "name": "vent"} and found[0].facts["gap_mm"] == 0.0
    assert kicad, "KiCad reports the track across the vent"


def test_past_the_vent_on_its_west_side_kicad_accepts(tmp_path):
    from placemat.copper import Track
    plan, kicad = _run(tmp_path, past=True)
    assert not [f for f in plan.findings if f.cause.value == "copper.edge"], plan.findings
    # 13.65 - 0.02 (the arc's chords) - 0.4 (this board's copper to edge) - 0.685 (half the track) = 12.545
    ends = {(round(p.x, 6), round(p.y, 6)) for t in plan.copper if isinstance(t, Track) for p in (t.start, t.end)}
    assert (12.545, 31.16) in ends, ends
    assert kicad == [], [v["description"] for v in kicad]
```

- [ ] **Step 2: Run it**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock env PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles_real.py -q --durations=0`
Expected: PASS (both). If the first fails because KiCad reports nothing, read the drc.json first: the comparison is the point of the test, not the finding. A test over 2 s goes into `tests/slow_tests.txt` (keep the file's sort order).

- [ ] **Step 3: Commit**

```bash
git add tests/test_past_obstacles_real.py tests/slow_tests.txt
git commit -m "Test: on a real board, a 3 A track across the vent is copper.edge as KiCad says, and a Past west of it passes DRC"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 8: api.md, SKILL.md and the migration entry

**Files:**
- Modify: `skills/placemat/references/api.md:122-126` (quick reference), `:876-889` (Beside), `:2555-2580` (Lane waypoints, Corner), after the Lane waypoints examples (2611), `:2859-2863` (A via past copper), `:3176` (Labels), `:4665` (severities)
- Modify: `skills/placemat/SKILL.md:84-97`
- Modify: `skills/placemat/references/migration.md:7` (a new "## Unreleased" above "## To 0.99.18")
- Test: `tests/test_past_obstacles.py` (append)

**Interfaces:**
- Consumes: the forms, facts and refusals of Tasks 1-6, as built.
- Produces: documentation only.

- [ ] **Step 1: Write the failing test**

```python
# ---------------------------------------------------------------- the docs
_SKILLS = Path(__file__).resolve().parents[1] / "skills/placemat"


def test_the_skill_api_and_migration_teach_past_over_obstacles_and_copper_edge():
    api = (_SKILLS / "references/api.md").read_text()
    skill = (_SKILLS / "SKILL.md").read_text()
    lane = api.split("**Lane waypoints.**", 1)[1].split("**A part's pad on another pad's edge.**", 1)[0]
    for word in ("cutouts (the `Cutout` given to `holes=`", "board.edge(facing=)", "board.cutout(name).edge(side=)",
                 "parts and cells", "labels", "copper-to-edge clearance", "silk clearance", "lands off the board",
                 "**Copper near a hole or the edge.**", "`copper.edge`", "`copper.meets`"):
        assert word in lane, word
    assert "Past([vent], Edge.WEST)" in api and "Past([board.edge(facing=Edge.WEST)], Edge.EAST)" in api
    assert "the Past takes pads only" not in api
    assert "LabelKey" in api and "copper.edge" in skill and "Past([vent], Edge.WEST)" in skill
    unreleased = (_SKILLS / "references/migration.md").read_text().split("## Unreleased", 1)[1].split("\n## To ", 1)[0]
    for word in ("Past passes any obstacle", "past_off_board", "LabelKey", "copper.edge", "copper.meets", "run score"):
        assert word in unreleased, word
    assert all(ord(c) < 128 for c in api + skill + unreleased), "ASCII only"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles.py -q -k docs`
Expected: FAIL on `cutouts (the \`Cutout\` given to \`holes=\``.

- [ ] **Step 3: Write the docs**

`api.md`, quick reference: row 122 becomes

```markdown
| a track held the clearance off pads, vias, tracks, a cutout, the board edge, a part or a label | `Past([PadRef(...), via, track], Edge.EAST, across=)`, `Past([vent], Edge.WEST)`, `Past([board.edge(facing=Edge.WEST)], Edge.EAST)` as a track point | Copper vocabulary (Lane waypoints) |
```

row 123: "a track's 45 held the clearance off a pad's corner" becomes "a track's 45 held the clearance off a corner of pads or a cutout"; row 126: "a via its clearance past pads, vias or tracks, on a pad's axis" becomes "a via its clearance past pads, vias, tracks, a cutout or a label, on a pad's axis".

`api.md`, Beside (876-889): replace "A placement is decided before\nany copper is planned, so the Past takes pads only - a via or a track is\nrefused - and takes no `across=`. The pads' parts are placed firmly first,\nas for any firm placement." with

```markdown
The Past takes pads, cutouts with a decided place, stretches of the board
edge or of a hole, and parts and cells: what has its place before the part
does. A cutout or a stretch of edge holds the own pad the board's
copper-to-edge clearance off (with `lane=`, that plus the lane's width and
its clearance to the own pad); a part's or a cell's envelope holds it
nothing off, and the part's pads their clearance. A via or a track is
refused (a placement is decided before any copper is planned), a label too
(it gives way to the parts placed after it), and a cutout with a freedom
(the board slides it once every firm item is down). The Past takes no
`across=`. What it names is placed or cut first, as for any firm placement.
```

`api.md`, Lane waypoints (2559-2570): replace from "`Past(items, Edge.EAST,\nacross=None)` is a point the clearance off" through "not drawn, and the finding names both." with the spec's paragraph, wrapped at 72 columns:

```markdown
`Past(items, Edge.EAST, across=None)` is a point held off the `edge` side
of some items. `items` are pads (`PadRef`/`CellPadRef`), vias, tracks,
cutouts (the `Cutout` given to `holes=`, or `board.cutout(name)`),
stretches of the board edge or of a hole (`board.edge(facing=)`,
`board.cutout(name).edge(side=)`), parts and cells, and labels (the key
`board.label()` returns), in any mix. Each is read as its box. The point
stands half the track's width plus the pair's rule off each: the net-pair
clearance from copper, the board's copper-to-edge clearance from a hole or
the edge, nothing from a part's envelope (its pads keep their clearance)
or a label (a via keeps the silk clearance). Off a stretch of edge the
point is on the board's side of it. `across=` a pad, a via, a cutout, a
part or a cell puts the point on its centre line, an `Along` at that point
of the combined box's side. The point waits for what it names to be
placed or planned; copper past a label is planned after the search. A
Past whose item found no place, or whose point lands off the board, is
not drawn, and the finding says which.
```

and keep "Both are accepted wherever a track point is." after it. The Corner paragraph (2573-2580): after "passes the corner at the clearance." add "With several items, each item's corner is passed at least at its own stand-off: the point is on the diagonal from the combined box's corner, as far out as the item that needs most." After the two examples that follow (2584-2589) add

~~~markdown
**Copper near a hole or the edge.** Declared copper (a track, a via, a
pour, a finger) nearer the board's outline or a cutout than the board's
copper-to-edge clearance is a `copper.edge` finding when it is planned,
naming the declaration, the hole or the edge, the gap and the clearance.
Copper nearer a part's drilled hole than the hole clearance is
`copper.meets`, as a via's hole is. The copper is drawn either way; a
`Past` off the cutout or the edge is the usual way to move it. A plane is
not judged: KiCad's fill keeps its own clearance. A module's frame is not
an edge: it is never written to Edge.Cuts.

```python
vent = Cutout(Circle(1.5), "vent", at=Near(PadRef(Part("q1"), 2)))
board.rect(40, 30, holes=[vent])
board.track(Net("VBUS"), [PadRef(Part("j1"), 1), Past([vent], Edge.WEST), PadRef(Part("q1"), 2)],
            layer=CopperLayer.B)          # half the width plus the copper-to-edge clearance west of the hole
```
~~~

(Check `grep -n "Lane waypoints" skills/placemat/references/api.md` again: the test reads up to "**A part's pad on another pad's edge.**", so the new paragraph must sit before that heading.)

`api.md`, A via past copper (2861-2862): "to any of them: pads, vias\nand tracks, as a track's `Past` takes (Lane waypoints)" becomes "to any of them: the items a track's `Past` takes (Lane waypoints), with the silk clearance off a label".

`api.md`, Labels: after the paragraph that ends at 3176's code block ("...pin labels clear of the part"), add the sentence "`board.label()` returns the label's key, a `LabelKey` (a `str`; a list of them for a list of items): a `Past` names it to pass the text." at the start of the paragraph that follows the code block.

`api.md`, severities (4665): the conflicts list becomes "(conflicts: copper meets another net or a part's drilled hole, comes nearer a hole or the board edge than the copper-to-edge clearance (`copper.edge`), crosses a keepout, passes a corner inside the clearance, two tracks cross and neither may bridge)".

`SKILL.md` (87-88 and 91-94): the Beside bullet's "`(own_pad, Past(pads, edge, lane=Net(...), width=))` - its pad a lane\n  past other pads, as wide as the lane's current needs." becomes "`(own_pad, Past(items, edge, lane=Net(...), width=))` - its pad a lane\n  past other pads, a cutout, the board edge or a part, as wide as the\n  lane's current needs."; the waypoint bullet becomes

```markdown
- `Between(pad, pad)` and `Past(items, edge, across=)` are track
  waypoints: through a gap, or past what `items` name - pads, vias, tracks,
  a cutout (`Past([vent], Edge.WEST)`), a stretch of the board edge
  (`board.edge(facing=)`), a part or a cell, a label - each by the rule
  between it and copper. `Past(items, Corner.NE)` holds a 45 off a corner.
  `board.via(net, at=Past(...))` stands a via there. Copper drawn across a
  hole or the edge is a `copper.edge` finding; a `Past` off the cutout
  moves it.
```

(keep the next three lines, "What `board.via()` and ..." as they are).

`migration.md`: above "## To 0.99.18" (line 8) add

```markdown
## Unreleased

### New

- **Past passes any obstacle.** `Past(items, edge)` and `Past(items,
  Corner.X)` take cutouts, stretches of the board edge, parts and cells,
  and labels, as well as pads, vias and tracks. The point keeps the
  board's copper-to-edge clearance off a hole or the edge, and stands on
  an envelope's or a label's outline. A track that had to pass a cutout
  with a hand-placed point can name the cutout. A Past whose point lands
  off the board is now a `copper.not_drawn` finding (`past_off_board`).
  Past over pads, vias and tracks alone resolves as before.
  `board.label()` returns a `LabelKey`, a `str`, so scripts that use the
  key as text need no change.
- **Copper near a hole or the edge is a finding.** Declared copper nearer
  the outline or a cutout than the board's copper-to-edge clearance is a
  critical `copper.edge` finding when it is planned, and copper nearer a
  part's drilled hole than the hole clearance is `copper.meets`. Both
  were DRC failures before and still are; a run now reports them itself,
  naming the declaration, so a board that passed its findings may now
  show these, and they count in the run score as copper findings do. The
  copper is still drawn. A module's frame is not judged.

```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -n 2 tests/test_past_obstacles.py tests/test_suggestion_cases.py tests/test_arrangement_declarations.py tests/test_skill_check.py -q`
Expected: PASS (the files that read api.md and migration.md, and the new docs test). Then `grep -nP "[^\x00-\x7F]" skills/placemat/SKILL.md skills/placemat/references/api.md skills/placemat/references/migration.md` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add skills/placemat/SKILL.md skills/placemat/references/api.md skills/placemat/references/migration.md tests/test_past_obstacles.py
git commit -m "Docs: Past over cutouts, the board edge, parts and labels; copper.edge; the migration entry under Unreleased"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 9: Final gate

**Files:**
- Modify: `docs/superpowers/specs/2026-10-05-past-any-obstacle-design.md` (a "## Build notes" section at the end)
- Create (scratch only, not committed): `/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/core-gate/`

**Interfaces:**
- Consumes: everything above.
- Produces: the bench tally, the full suite's result and the core board's counts, in the build notes and the gate's commit.

- [ ] **Step 1: Bench**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2 | tee /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/bench.out`
Expected: every case `same` on every config. Any `better` or `worse` is a regression: find it with `git bisect` over this plan's commits before going on.

- [ ] **Step 2: The full suite, once, alone**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock env PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests --full -n 2 -p no:cacheprovider -q 2>&1 | tee /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/suite.out | tail -15`
Expected: PASS. A test the run names as over 2 s and not in `tests/slow_tests.txt` is added to it (`tests/update_slow_tests.py`). A real-module test that now carries `copper.edge` or a hole `copper.meets` is judged as Task 6 Step 5 says.

- [ ] **Step 3: The core board, on a copy**

The board is read-only. Its script reads two files outside its folder (`../../docs/decisions/layout/core-part-heights-2026-09-27.json`, and `mechanical.toml` at the repository root), so the copy keeps that layout. Run as one shell script:

```bash
S=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad
ROOT=~/Documents/Hardware/fairing-instrument-stagger
G=$S/core-gate
rm -rf "$G" && mkdir -p "$G/electronics/boards" "$G/electronics/docs/decisions/layout"
rsync -a --exclude '.placemat/runs/' --exclude '.placemat/views/' --exclude '.placemat/explore/' --exclude 'snapshots/' \
      "$ROOT/electronics/boards/core/" "$G/electronics/boards/core/"
cp "$ROOT/electronics/docs/decisions/layout/core-part-heights-2026-09-27.json" "$G/electronics/docs/decisions/layout/"
cp "$ROOT/mechanical.toml" "$G/"
cp "$ROOT/electronics/pcb.toml" "$ROOT/electronics/fab-profile.json" "$G/electronics/" 2>/dev/null
du -sh "$G"
cd "$G/electronics/boards/core" && flock "$S/realboard.lock" env PYTHONPATH=/home/ben/work/placemat/src \
    /home/ben/work/placemat/.venv/bin/python -m placemat run Core_layout.py --no-render --label past-gate 2>&1 | tail -25
```

The run uses the cached generation in `.placemat/generated` (no `--fresh`). If it stops for a file outside the copy, copy that one file into the same relative place under `$G` and run again, noting it; if it asks to regenerate the board, stop and report rather than regenerate. Never write into `$ROOT`. Then count:

```bash
S=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad
/home/ben/work/placemat/.venv/bin/python - "$S/core-gate/electronics/boards/core/.placemat/runs/past-gate" <<'EOF'
import json, pathlib, sys
d = pathlib.Path(sys.argv[1])
found = json.loads((d / "run.json").read_text()).get("finding_details", [])
edge = [f for f in found if f.get("cause") == "copper.edge"]
holes = [f for f in found if f.get("cause") == "copper.meets" and f["facts"]["hit"]["code"] in ("hole_copper", "npth_near", "npth_cuts")]
drc = json.loads((d / "drc.json").read_text()) if (d / "drc.json").exists() else {"violations": []}
kicad = [v for v in drc["violations"] if v.get("type") == "copper_edge_clearance"]
print("copper.edge:", len(edge), " hole copper.meets:", len(holes), " KiCad copper_edge_clearance:", len(kicad))
for f in edge:
    print("  ", f["text"])
EOF
```

Expected: the three counts and the `copper.edge` sentences. Each `copper.edge` should match a KiCad `copper_edge_clearance` on the same declaration's copper (a track across the vent among them, if the board still declares one); one KiCad reports that placemat does not, or the other way round, is read before the gate is called done: an `inside` finding (gap 6 below) is the expected difference. Remove `$G` afterwards (`rm -rf "$G"`).

- [ ] **Step 4: Build notes and the gate's commit**

Append to the spec:

```markdown
## Build notes

Built <date>. The bench (`fixtures/bench.py --jobs 2`) is the same in every case on every config. The full suite
(`--full`) passed. On a copy of the board that reported the vent case, the run gives <n> `copper.edge`, <m> hole
`copper.meets`, and KiCad <k> `copper_edge_clearance`; <how they correspond>.
```

with the date and the numbers from Steps 1-3. Then:

```bash
git add docs/superpowers/specs/2026-10-05-past-any-obstacle-design.md
{ echo "Spec: build notes for Past over any obstacle and copper.edge"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing; `git status --short` shows nothing of this plan's left uncommitted.

- [ ] **Step 5: Release**

Follow the release procedure (suite, skill docs current, release with the migration and whats-new entries and the gaps file pruned, notify the sessions that use placemat, then the bench). The migration entry is written in Task 8.

---

## Spec gaps and resolutions

Recommended resolutions are built into the tasks. Gaps 6 and 7 need a user decision before Task 6.

1. **Line numbers.** The spec's citations predate units, the soft pin groups and the route cleanup; "Where the spec's citations are now" maps each one. The behaviour they describe is unchanged.
2. **`geometry.arc_sag` is a setting.** The spec names it as if it were a board rule; it is `Settings.geometry_arc_sag` (`[geometry] arc_sag`, default 0.02 mm). The plan uses it as `_cutout_silk` and `_report_cell_labels_at_edge` do; no setting is added.
3. **The reported case's size.** The request describes a "1.5 mm radius vent"; the board and the spec declare `Circle(1.5)`, which is a 1.5 mm diameter (radius 0.75; the spec's own 0.31 mm corner cost assumes it). The tests use `Circle(1.5)`, as on the board.
4. **A stretch of a hole not yet cut.** `board.cutout(name).edge(side=)` on a hole with a freedom returns a `CutoutEdge` promise; the spec lists only `Run`s. The plan takes the promise too, checks its side at declaration (its board side is `side`) and resolves it when the copper is planned, with `past_cutout_unplaced` if the hole found no place.
5. **Beside and a cutout placed relative to a part.** The spec refuses a cutout with a freedom; one with a decided place relative to a part is cut in the firm pass. The plan accepts it and makes the Beside part wait for it (`cutout_token`), as `OnEdge(CutoutEdge)` does; a cutout settled at declaration needs no wait.
6. **Needs a user decision: copper wholly inside a hole or off the board.** The spec reports it (`inside`, gap 0). KiCad does not: `testAgainstEdge` collides copper with the Edge.Cuts segments and arcs (drc_test_provider_edge_clearance.cpp 188-245, 289-361), so copper that touches no edge gives no `copper_edge_clearance`. Recommended: keep it as the spec says (the copper is milled away or off the board, which no DRC rule then catches), and say in the docs that this one is placemat's own. The alternative is to drop `inside` and match KiCad exactly.
7. **Needs a user decision: a module's frame.** The spec judges every declared copper. A fragment's frame (`board.rect(..., draw=False)`, and every `fit=` frame) is never written to Edge.Cuts, and a module run's DRC is `frame_only`; lanes and copper legitimately run to it. Recommended: neither `copper.edge` nor `past_off_board` is judged on a fragment (`Board._judges_edge`). The alternative is to judge a fragment's cutouts only.
8. **Edge clearance 0.** KiCad collides at `max(0, clearance - epsilon)` (line 206), so copper touching the edge is reported even at 0; `clear_limit` alone would miss it. The plan reports any gap of 0.
9. **A pour over a whole hole.** KiCad collides the filled shape with the hole's edges; the plan gives 0 where the hole's first point lies in the pour.
10. **Facts beyond the spec's table.** `copper.edge` also carries `sag_mm` (the curve's allowance it was judged with), `sides` (for the suggestion) and `waypoints`. The sentence adds "with N mm for its curve" only where the gap is the clearance or more, so it never reads as a gap over its rule.
11. **The suggestion.** "Offers a Past on the side the track's nearest point lies" is taken as: for a track with no waypoints (the insert position is then unambiguous), one Past per side across the track's run, the side its centreline lies toward first; a track through the middle gets WEST then EAST (or NORTH then SOUTH). This needs `edit_list`'s add to take a position (`at=`), added to script_edit.py.
12. **`past_off_board`'s `edge` fact** is the `EdgeWhy` value, `outside` or `in_cutout`; the spec names the fact only.
13. **The corner verdict with several groups** names every group passed too near and reports the largest shortfall's `near_mm` and `need_mm`; with copper alone it is the finding it was.
14. **The run score.** `copper.edge` and the new hole `copper.meets` are copper findings, so they count in the run score and an explore weighs them; the migration entry says so.
15. **Seen while reading, not in scope:** on a disc with a bore, `_cutout_paths` (layout.py 2096-2098) numbers a named cutout settled at declaration from loop 1, but `_shaped()` puts the bore at loop 1, so `_cutout_loop_of` likely points one loop short there; `board.cutout(name)`, `label.cell_edge` and this plan's `_cutout_box` would read the bore. Worth its own test and fix; the core board is an `outline()` board and is not affected.
