"""A stamped cell's own copper keeps the shapes a copper finding measures
when the cell is placed: a pour its drawn polygon (`Shape.drawn`), a
straight track its segment, a via its circle, moved and mirrored with the
cell. Without them a finding falls back to the copper's polygon, whose
outline, read from the board, lies a few micrometres outside the copper.

fixtures/fairing/flipped_pour is a run's board cut down to a cell's fitted
pour on the back (a filled polygon with a 0.2 mm stroke and filleted
corners) and a 1.06 mm track of another net beside it. KiCad's DRC measures
them 0.132001 mm apart, clear of the 0.127 mm rule; measured by the pour's
read outline they were 0.125123 mm apart, a finding."""
import dataclasses
import json
import pathlib
import shutil
import subprocess

import pytest

from placemat.board_geometry import CopperItem
from placemat.layout import Board
from placemat.values import Box, Cell, CopperLayer, Face, Location, Net
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint, rect

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/flipped_pour"
KICAD_GAP = 0.132001          # kicad-cli: clear; 7 um closer it reports "actual 0.1250 mm"
RULE = 0.127


def _read():
    from placemat.kicad.read import read_board
    g = read_board(str(FIXTURE / "layout.kicad_pcb"))
    (pour,) = [c for c in g.copper if c.kind == "poly"]
    (track,) = [c for c in g.copper if c.kind == "track"]
    return pour, track


def _mirrored(pour: CopperItem, cx: float) -> CopperItem:
    """The pour as its cell draws it on the front: mirrored about x = cx."""
    m = lambda poly: tuple((2 * cx - x, y) for x, y in poly)
    outlines = tuple(m(p) for p in pour.outlines)
    return dataclasses.replace(pour, layers=frozenset([CopperLayer.F]), outlines=outlines,
                               box=Box.of_points([p for o in outlines for p in o]), owner="k",
                               vertices=tuple(m(v) for v in pour.vertices))


def _placed(track_dy: float = 0.0):
    """The cell placed on the back so its pour lands where the fixture has it, and the track declared beside it."""
    pour, track = _read()
    c = pour.box.center
    member = footprint("U1", c.x, c.y, inst="k.u1", cell="k", nets=("N2", "N2"))    # a cell has a part
    g = board_geometry([member], cells=("k",), copper=[_mirrored(pour, c.x)], width=80, height=80, clearance=RULE,
                       extra_nets=("N1",))
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Cell("k"), at=Location(c.x, c.y), face=Face.BACK)
    (ax, ay), (bx, by) = track.anchors
    b.track(Net("N1"), [Location(ax, ay + track_dy), Location(bx, by + track_dy)], layer=CopperLayer.B,
            width=track.width_mm)
    return b.resolve(), pour


def _gap(facts):
    """A copper finding's measured gap, wherever its facts hold it."""
    if isinstance(facts, dict):
        if "gap_mm" in facts:
            return facts["gap_mm"]
        return next((g for v in facts.values() if (g := _gap(v)) is not None), None)
    return None


def _copper_findings(plan) -> list:
    return [f for f in plan.findings if f.startswith("copper N1")]


@needs_kicad
def test_a_flipped_cells_pour_is_measured_as_kicad_measures_it():
    plan, pour = _placed()
    assert _copper_findings(plan) == []
    (s,) = [s for s in plan.occupancy.copper if s.owner == "k"]
    assert s.layers == frozenset([CopperLayer.B])
    (outline,), width, filled = s.drawn
    assert (width, filled) == (pour.width_mm, pour.filled)
    (want,) = pour.vertices
    assert max(abs(a - b) for p, q in zip(outline, want) for a, b in zip(p, q)) < 1e-6


@needs_kicad
def test_the_same_pour_seven_micrometres_nearer_is_found_at_kicads_gap():
    plan, _ = _placed(track_dy=0.007)
    (f,) = _copper_findings(plan)
    assert abs(_gap(f.facts) - (KICAD_GAP - 0.007)) < 1e-6, f.facts


@needs_kicad
@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")
def test_kicads_drc_passes_the_fixture_and_finds_it_seven_micrometres_nearer(tmp_path):
    text = (FIXTURE / "layout.kicad_pcb").read_text()
    _, track = _read()
    y = "%g" % track.anchors[0][1]
    assert text.count(y) == 2

    def clearance(dy):
        pcb = tmp_path / "layout.kicad_pcb"
        pcb.write_text(text.replace(y, "%.6f" % (track.anchors[0][1] + dy)))
        shutil.copy(FIXTURE / "layout.kicad_pro", tmp_path / "layout.kicad_pro")
        out = tmp_path / "drc.json"
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out), str(pcb)],
                       check=True, capture_output=True, cwd=str(tmp_path))
        return [v["description"] for v in json.loads(out.read_text())["violations"] if v["type"] == "clearance"]
    assert clearance(0.0) == []
    (v,) = clearance(0.007)
    assert "actual 0.1250 mm" in v, v


def test_a_flipped_cells_track_and_vias_keep_their_segment_and_circles():
    """A cell's own straight track between two of its vias (a route, so
    neither via is carried), moved and mirrored with the cell: the track's
    segment still runs between the vias' circles."""
    from placemat.geometry import circle_polygon
    t = rect(10.0, 10.0, 2.3, 0.3)
    track = CopperItem("track", "A", frozenset([CopperLayer.F]), (t,), Box.of_points(t), "k", 0.3,
                       anchors=((9.0, 10.0), (11.0, 10.0)), length_mm=2.0)

    def via(x):
        ring = circle_polygon(Location(x, 10.0), 0.3)
        return CopperItem("via", "A", frozenset([CopperLayer.F, CopperLayer.B]), (ring,), Box.of_points(ring), "k",
                          width_mm=0.6, drill_mm=0.3, anchors=((x, 10.0),))
    fps = [footprint("U1", 10, 14, inst="k.u1", cell="k", nets=("A", "B"))]
    g = board_geometry(fps, cells=("k",), copper=[track, via(9.0), via(11.0)], width=60, height=60)
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Cell("k"), at=Location(30.3, 30.7), face=Face.BACK, rotation=90)
    plan = b.resolve()
    (ts,) = [s for s in plan.occupancy.copper if s.owner == "k" and s.kind == "copper"]
    circles = sorted(s.circle for s in plan.occupancy.copper if s.owner == "k" and s.kind == "through")
    ax, ay, bx, by, w = ts.segment
    assert w == 0.3
    assert sorted([(ax, ay), (bx, by)]) == pytest.approx([c[:2] for c in circles], abs=1e-9)
    assert [c[2] for c in circles] == [0.3, 0.3]
    for x, y, _ in circles:
        assert ts.box.left < x < ts.box.right and ts.box.top < y < ts.box.bottom
