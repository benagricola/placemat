"""A swallow pour's shape at plan time is its own raw declared outline, not
the pulled-back result the writer draws (kicad/write.py's `_draw_pour`):
placemat's geometry (geometry.py) and its native module have no polygon
subtract, so the plan cannot compute what the writer will draw. Reporting a
plan-time clearance finding against the raw shape would flag a clearance
problem the written board never has - the writer's pull-back guarantees it.
So a swallow pour's clearance to other nets is left out of the plan-time
conflict check; the pour is still added to the occupancy, so it remains an
obstacle for copper planned after it. Pure."""
import pytest

from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Edge, Face, Location, Net, OnEdge, PadRef, Part
from tests.fixtures import board_geometry, declared_findings, pad


def _one_pad_part(ref, inst, net, cx, cy, w, h):
    p = pad(ref, inst, 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def test_a_swallow_pours_plan_time_conflict_to_a_foreign_pad_is_not_reported():
    """U2's pad box reaches to x=9.6, inside the pour's raw declared outline
    (x <= 10): a plan-time finding measured against that raw shape would
    report a clearance problem the writer's pull-back always avoids."""
    u1 = _one_pad_part("U1", "u1", "A", 5.0, 2.0, 1.0, 1.0)
    u2 = _one_pad_part("U2", "u2", "B", 10.1, 2.0, 1.0, 1.0)
    b = Board(board_geometry([u1, u2], width=60, height=60), edge_margin=1.0)
    b.pour(Net("A"), [Location(0, 0), Location(10, 0), Location(10, 4), Location(0, 4)],
          layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    assert not any("copper A" in f and "from B copper" in f for f in declared_findings(plan)), plan.findings


def test_a_swallow_pour_without_swallow_pads_still_reports_the_conflict():
    """Documented and unchanged: a plain pour (no swallow_pads) keeps
    exactly its given shape - the writer never pulls it back - so a
    clearance problem against its raw shape is real and still reported."""
    u1 = _one_pad_part("U1", "u1", "A", 5.0, 2.0, 1.0, 1.0)
    u2 = _one_pad_part("U2", "u2", "B", 10.1, 2.0, 1.0, 1.0)
    b = Board(board_geometry([u1, u2], width=60, height=60), edge_margin=1.0)
    b.pour(Net("A"), [Location(0, 0), Location(10, 0), Location(10, 4), Location(0, 4)],
          layer=CopperLayer.F, swallow_pads=False)
    plan = b.resolve()
    assert any("copper A" in f and "from B copper" in f for f in declared_findings(plan)), plan.findings


def test_a_swallow_pour_still_blocks_copper_planned_after_it():
    """Not reporting the pour's own clearance is not the same as dropping it
    from the occupancy: a track of a third net, planned once its part is
    placed (so it lands in a later copper batch than the pour's fixed one -
    `at=OnEdge(...)` alone is searched, not decided, so u3's track waits
    behind the whole placement search), still conflicts with the pour's
    declared shape."""
    u3 = _one_pad_part("U3", "u3", "C", 20.0, 2.0, 1.0, 1.0)
    b = Board(board_geometry([u3], width=60, height=60, extra_nets=["A"]), edge_margin=1.0)
    b.place(Part("u3"), at=OnEdge(Edge.EAST))
    b.pour(Net("A"), [Location(0, 0), Location(10, 0), Location(10, 4), Location(0, 4)],
          layer=CopperLayer.F, swallow_pads=True)
    b.track(Net("C"), [PadRef(Part("u3"), 1), Location(10.05, 2.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert any("copper C" in f for f in declared_findings(plan)), plan.findings
