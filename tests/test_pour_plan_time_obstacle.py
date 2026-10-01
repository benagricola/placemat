"""A pour is checked at plan time against the copper planned before it, and
is itself an obstacle for copper planned after it. A fitted pour
(swallow_pads over pads) is planned clear of the copper before it, so it
raises no clearance finding; a pour drawn as declared (no swallow_pads)
keeps exactly its given shape, so a clearance problem against that shape is
real and is reported. Pure."""
from placemat.board_geometry import Footprint
from placemat.copper import Pour
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Edge, Face, Location, Net, OnEdge, PadRef, Part
from tests.fixtures import board_geometry, declared_findings, pad


def _one_pad_part(ref, inst, net, cx, cy, w, h):
    p = pad(ref, inst, 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _a_parts():
    return [_one_pad_part("U%d" % i, "u%d" % i, "A", x, y, 1.0, 1.0) for i, (x, y) in enumerate(((5.0, 2.0), (5.0, 6.0), (9.0, 4.0)))]


def _a_pads():
    return [PadRef(Part("u%d" % i), 1) for i in range(3)]


def test_a_fitted_pour_is_planned_clear_of_a_foreign_pad_and_raises_no_finding():
    """U9's pad reaches into the hull of the three A pads from the south, inside the
    clearance: the pour is fitted round it, so nothing is reported."""
    u9 = _one_pad_part("U9", "u9", "B", 7.0, 6.0, 1.0, 1.0)
    b = Board(board_geometry(_a_parts() + [u9], width=60, height=60), edge_margin=1.0)
    b.pour(Net("A"), _a_pads(), layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    assert any(isinstance(c, Pour) and c.fitted for c in plan.copper)
    assert not any("copper A" in f and "from B copper" in f for f in declared_findings(plan)), plan.findings


def test_a_pour_without_swallow_pads_still_reports_the_conflict():
    """A plain pour keeps exactly its given shape - nothing is cut from it
    when it is written - so a clearance problem against its shape is real
    and reported."""
    u1 = _one_pad_part("U1", "u1", "A", 5.0, 2.0, 1.0, 1.0)
    u2 = _one_pad_part("U2", "u2", "B", 10.1, 2.0, 1.0, 1.0)
    b = Board(board_geometry([u1, u2], width=60, height=60), edge_margin=1.0)
    b.pour(Net("A"), [Location(0, 0), Location(10, 0), Location(10, 4), Location(0, 4)],
          layer=CopperLayer.F, swallow_pads=False)
    plan = b.resolve()
    assert any("copper A" in f and "from B copper" in f for f in declared_findings(plan)), plan.findings


def test_a_fitted_pour_still_blocks_copper_planned_after_it():
    """A track of a third net, planned once its part is placed (so it lands
    in a later copper batch than the pour's fixed one - `at=OnEdge(...)`
    alone is searched, not decided, so u3's track waits behind the whole
    placement search), is not drawn through the pour as planned."""
    u3 = _one_pad_part("U3", "u3", "C", 30.0, 4.0, 1.0, 1.0)
    b = Board(board_geometry(_a_parts() + [u3], width=60, height=60, extra_nets=["A"]), edge_margin=1.0)
    b.place(Part("u3"), at=OnEdge(Edge.EAST))
    b.pour(Net("A"), _a_pads(), layer=CopperLayer.F, swallow_pads=True)
    b.track(Net("C"), [PadRef(Part("u3"), 1), Location(7.0, 4.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    assert any("track C" in f and "not drawn" in f for f in declared_findings(plan)), plan.findings
