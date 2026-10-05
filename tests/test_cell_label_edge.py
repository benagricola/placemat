"""A searched cell's stamped labels - the silk texts in its group - keep the board's silk clearance from Edge.Cuts: the
outline and every cutout, as KiCad judges silk against the edge (drc_test_provider_edge_clearance.cpp testAgainstEdge,
SILK_CLEARANCE_CONSTRAINT, DRCE_SILK_EDGE_CLEARANCE). Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.board_geometry import RuleArea
from placemat.cutouts import Circle
from placemat.findings import FindingCause as C
from placemat.geometry import point_segment_distance
from placemat.layout import Board
from placemat.values import Cell, CopperLayer, Cutout, Face, Location, Near
from tests.conftest import needs_native
from tests.fixtures import board_geometry, footprint

SILK = 0.2
SIZE = 40.0


def _geometry(label_layer):
    """The panel cell: U1 at (8, 10) and U2 at (12, 10), each 3 x 2, and its label 'BOOT', a 2 x 1 box from (9, 12)
    to (11, 13), 1 mm south of their bodies."""
    fps = [footprint("U1", 8, 10, w=3, h=2, cell="panel", inst="panel.u1", nets=("A", "B")),
           footprint("U2", 12, 10, w=3, h=2, cell="panel", inst="panel.u2", nets=("B", "C"))]
    g = board_geometry(fps, cells=["panel"], width=SIZE, height=SIZE, silk_clearance=SILK)
    return dataclasses.replace(g, rule_areas=(
        RuleArea("label BOOT", "panel", ((9.0, 12.0), (11.0, 12.0), (11.0, 13.0), (9.0, 13.0)),
                 frozenset([label_layer]), frozenset(["parts"])),))


def _label(plan):
    """The label's polygon where the cell landed."""
    shapes = [s for s in plan.occupancy.copper if s.kind == "silk" and s.owner == "panel"]
    assert len(shapes) == 1, shapes
    return shapes[0].poly


def _gap_to_circle(centre, radius, poly) -> float:
    n = len(poly)
    return min(point_segment_distance(centre, poly[i], poly[(i + 1) % n]) for i in range(n)) - radius


FACES = [(Face.FRONT, CopperLayer.F), (Face.BACK, CopperLayer.B)]


@pytest.mark.parametrize("face,layer", FACES, ids=["front", "back"])
def test_a_searched_cell_keeps_its_label_the_silk_clearance_off_a_cutout(face, layer):
    """The hole stands 1 mm south of where the hint puts the parts' bodies: they clear it, the label would lie over it."""
    b = Board(_geometry(layer), edge_margin=0.5)
    b.rect(width=SIZE, height=SIZE, holes=[Cutout(Circle(3.0), "vent", at=Location(20.0, 23.5), why="air")])
    b.place(Cell("panel"), at=Near(Location(20.0, 20.0), radius=8.0), face=face)
    plan = b.resolve()
    assert {"U1", "U2"} <= set(plan.occupancy.items)
    vent = plan.cutouts_placed["vent"].centre
    gap = _gap_to_circle((vent.x, vent.y), 1.5, _label(plan))
    assert gap >= SILK - 1e-9, gap


@pytest.mark.parametrize("face,layer", FACES, ids=["front", "back"])
def test_a_searched_cell_keeps_its_label_the_silk_clearance_inside_the_outline(face, layer):
    """The hint puts the parts 2 mm off the south edge and the label on it."""
    b = Board(_geometry(layer), edge_margin=0.5)
    b.rect(width=SIZE, height=SIZE)
    b.place(Cell("panel"), at=Near(Location(20.0, 37.0), radius=8.0), face=face)
    plan = b.resolve()
    assert {"U1", "U2"} <= set(plan.occupancy.items)
    poly = _label(plan)
    gap = min(min(x, y, SIZE - x, SIZE - y) for x, y in poly)
    assert gap >= SILK - 1e-9, gap


def _record(monkeypatch):
    from placemat import placer
    seen = []

    class Recorded(placer.ScanResult):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            seen.append(self)
    monkeypatch.setattr(placer, "ScanResult", Recorded)
    return seen


@needs_native
@pytest.mark.parametrize("face,layer", FACES, ids=["front", "back"])
def test_the_native_sweep_judges_the_label_as_the_python_sweep_does(face, layer, monkeypatch):
    """The same scan natively and in Python: the spot chosen, the refusals counted and their first sentences."""
    from placemat import placer
    runs = {}
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        seen = _record(monkeypatch)
        b = Board(_geometry(layer), edge_margin=0.5)
        b.rect(width=SIZE, height=SIZE, holes=[Cutout(Circle(3.0), "vent", at=Location(20.0, 23.5), why="air")])
        b.place(Cell("panel"), at=Near(Location(20.0, 20.0), radius=8.0), face=face)
        b.resolve()
        runs[on] = [(r.chosen, r.tried, list(r.rejected.items()), [(k, str(v)) for k, v in r.reasons.items()])
                    for r in seen]
    assert runs[True] == runs[False]
    reasons = [why for _c, _t, _r, said in runs[True] for _k, why in said]
    assert any(why.startswith("label silk to edge") for why in reasons), reasons


def _edge_findings(plan):
    return [f for f in plan.findings if f.cause is C.LABEL_CELL_EDGE]


@pytest.mark.parametrize("face,layer", FACES, ids=["front", "back"])
def test_a_decided_cell_stands_where_the_script_put_it_and_its_label_by_a_cutout_is_a_warning(face, layer):
    """A place the script decided keeps its labels where they fall, as a decided cutout is cut whatever silk stands by
    it; a label nearer the cutout than the silk clearance is a warning naming the cell, the text, the cutout, the gap and
    the clearance."""
    b = Board(_geometry(layer), edge_margin=0.5)
    b.rect(width=SIZE, height=SIZE, holes=[Cutout(Circle(3.0), "vent", at=Location(20.0, 23.5), why="air")])
    b.place(Cell("panel"), at=Location(20.0, 20.0), face=face)
    plan = b.resolve()
    assert plan.occupancy.items["U1" if face is Face.FRONT else "U2"].reference.location == Location(18.0, 20.0)
    found = _edge_findings(plan)
    assert len(found) == 1, plan.findings
    f = found[0]
    assert f.severity == "warning"
    assert f.facts == {"cell": "panel", "text": "BOOT", "edge": "cutout", "cutout": "vent", "gap_mm": 0.0,
                       "need_mm": SILK}
    assert str(f) == "cell panel label BOOT: 0.00 mm from cutout vent, under the 0.20 mm silk clearance"


def test_a_decided_cell_whose_label_is_by_the_outline_is_a_warning():
    b = Board(_geometry(CopperLayer.F), edge_margin=0.5)
    b.rect(width=SIZE, height=SIZE)
    b.place(Cell("panel"), at=Location(20.0, 36.9))      # the label's south edge 0.1 mm off the outline
    plan = b.resolve()
    (f,) = _edge_findings(plan)
    assert f.facts["edge"] == "outline" and f.facts["cutout"] is None
    assert f.facts["gap_mm"] == pytest.approx(0.1, abs=1e-6)
    assert str(f) == "cell panel label BOOT: 0.10 mm from the board outline, under the 0.20 mm silk clearance"


def test_a_decided_cell_whose_label_keeps_the_clearance_has_no_warning():
    b = Board(_geometry(CopperLayer.F), edge_margin=0.5)
    b.rect(width=SIZE, height=SIZE, holes=[Cutout(Circle(3.0), "vent", at=Location(20.0, 26.0), why="air")])
    b.place(Cell("panel"), at=Location(20.0, 20.0))       # the label ends 1.5 mm north of the hole
    assert not _edge_findings(b.resolve())


def test_a_searched_cell_has_no_such_warning():
    b = Board(_geometry(CopperLayer.F), edge_margin=0.5)
    b.rect(width=SIZE, height=SIZE, holes=[Cutout(Circle(3.0), "vent", at=Location(20.0, 23.5), why="air")])
    b.place(Cell("panel"), at=Near(Location(20.0, 20.0), radius=8.0))
    assert not _edge_findings(b.resolve())
