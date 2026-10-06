"""A fitted pour's pad member with no copper on the pour's layer, and no via member joining it, takes the vias
already on the board that join it: vias of the pad's net that stand in a pad of its part on that net and reach
the pour's layer, whether a stamped cell's own layout placed them or the script did outside the pour call. They
are the pour's ends at that pad, and `reach=Reach.CURRENT` credits them with the pad's current. With none the pad
is refused as before.

The case: a reverse FET's back-side source pads, stitched to the inner layers by its cell's own vias, joined on
an inner layer to a connector's plated-through pin. Synthetic four-layer boards."""
import dataclasses

import pytest

from placemat.board_geometry import CopperItem, Footprint, PadGeom
from placemat.copper import Pour, Via
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.values import Box, Cell, CopperLayer, Face, Location, Net, PadRef, Part, Reach
from tests.fixtures import board_geometry, declared_findings, pad, rect
from tests.test_pour_current_vias import _board, _rows
from tests.test_pour_fitted import CLEARANCE

F, IN1, IN2, B = CopperLayer.F, CopperLayer.IN1, CopperLayer.IN2, CopperLayer.B
FOUR = frozenset((F, IN1, IN2, B))
VIA, DRILL = 0.45, 0.2
SOURCES = ((1, 20.0), (2, 20.65), (3, 21.3))       # the FET's source pads (number, x) as its module draws them
ROW_Y = 30.0


@pytest.fixture(autouse=True)
def _fab_makes_every_via(monkeypatch):
    monkeypatch.setattr(Board, "fab_via_tiers", {"micro": "yes", "blind": "yes", "buried": "yes"})


def _fet(amps="4A", cell="k"):
    """Q1 in cell k: three VB source pads 0.35 x 0.75 and a gate, on the front as the module draws them."""
    inst = "%s.q1" % cell if cell else "q1"
    pads = tuple(pad("Q1", inst, n, "VB", x, ROW_Y, 0.35, 0.75) for n, x in SOURCES)
    pads += (pad("Q1", inst, 4, "G", 21.95, ROW_Y, 0.35, 0.75),)
    body = Box(19.5, 29.0, 22.5, 33.0)
    return Footprint("Q1", inst, cell, "Q1", body.center, 0.0, Face.FRONT, body, body.inflate(0.1), body, pads,
                     fields={"Pm.I": amps} if amps else {})


def _pin(amps="4A"):
    """J1: a plated-through VB pin, on every layer, 10 mm west of the FET."""
    o = rect(8.0, ROW_Y, 1.7, 1.7)
    p = PadGeom("J1", "j1", "2", "VB", FOUR, (o,), Box.of_points(o), True, 1.0)
    body = p.box.inflate(0.5)
    return Footprint("J1", "j1", None, "J1", body.center, 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,),
                     fields={"Pm.I": amps} if amps else {})


def _via(x, y, net="VB", owner="k"):
    ring = circle_polygon(Location(x, y), VIA / 2.0)
    return CopperItem("via", net, FOUR, (ring,), Box.of_points(ring), owner, width_mm=VIA, drill_mm=DRILL,
                      anchors=((x, y),))


def _cell_board(stitched=(1, 2, 3), amps="4A"):
    """The cell's vias stand in the source pads `stitched`, and a pair more stands in the cell's own copper north of
    them, on no pad; the cell is placed on the back, where it lands where its module drew it, mirrored."""
    copper = [_via(x, ROW_Y + 0.1) for n, x in SOURCES if n in stitched] + [_via(20.0, ROW_Y - 1.2),
                                                                              _via(21.3, ROW_Y - 1.2)]
    fet = _fet(amps)
    g = board_geometry([_pin(amps), fet], cells=("k",), copper=copper, width=40, height=50, clearance=CLEARANCE,
                       extra_nets=("G",))
    g = dataclasses.replace(g, layers=(F, IN1, IN2, B))
    b = Board(g, edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(8.0, ROW_Y))
    centre = g.cells["k"].box.center
    b.place(Cell("k"), at=centre, face=Face.BACK)
    return b


def _pours(plan):
    return [c for c in plan.copper if isinstance(c, Pour)]


def _refused(plan) -> list:
    return [f for f in plan.findings if f.facts.get("variant") == "pour_pad_layer"]


def _joined(plan) -> list:
    return [f for f in plan.findings if f.facts.get("variant") == "pour_pad_vias"]


def _holds(points, x, y) -> bool:
    from placemat.geometry import point_in_polygon
    return point_in_polygon((x, y), points)


def test_a_cells_vias_in_its_parts_pads_join_a_back_pad_to_an_inner_pour():
    b = _cell_board()
    b.pour(Net("VB"), [PadRef(Part("j1"), 2), PadRef(Part("k.q1"), 2)], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not _refused(plan), plan.findings
    (p,) = _pours(plan)
    assert p.layer is IN2
    (x, y) = _in_pad_2(plan)
    assert _holds(p.points, x, y)
    (f,) = _joined(plan)
    assert f.severity == "notice"
    assert f.facts["member"] == ["pad", "Q1", "2"] and f.facts["layer"] == IN2.value
    assert f.facts["vias"] == [pytest.approx([x, y])]
    assert str(f).startswith("pour VB: pad Q1.2 has no copper on In2.Cu; the pour ends on the via that joins it there")


def _in_pad_2(plan):
    """The centre of the cell's via that stands in source pad 2, as placed."""
    (pad2,) = plan.occupancy.pad_shapes("Q1", "2")
    (at,) = [_centre(s) for s in plan.occupancy.copper if s.owner == "k" and s.kind == "through"
             and pad2.box.left < _centre(s)[0] < pad2.box.right]
    return at


def _centre(s):
    return (round(s.box.center.x, 6), round(s.box.center.y, 6))


@pytest.mark.parametrize("stitched", [(), (1, 3)], ids=["none", "siblings"])
def test_without_a_via_in_the_pad_the_back_pad_is_refused(stitched):
    """A via in another of the part's pads on the net does not join the pad: the via-member rule's test."""
    b = _cell_board(stitched=stitched)
    b.pour(Net("VB"), [PadRef(Part("j1"), 2), PadRef(Part("k.q1"), 2)], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not _pours(plan)
    assert any("pad Q1.2 has no copper on In2.Cu" in f for f in declared_findings(plan)), plan.findings


def test_a_pour_to_current_ends_on_the_cells_vias_and_is_sized_for_the_pads_current():
    from placemat import checks, pourfit
    from placemat.settings import Settings
    b = _cell_board()
    b.pour(Net("VB"), [PadRef(Part("j1"), 2), PadRef(Part("k.q1"), 2)], layer=IN2, swallow_pads=True,
           reach=Reach.CURRENT)
    plan = b.resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour") and "join" not in f], plan.findings
    (p,) = _pours(plan)
    s = Settings()
    x, y = _in_pad_2(plan)
    rings = [s_.poly for s_ in plan.occupancy.copper if s_.owner == "k" and s_.kind == "through"
             and _centre(s_) == (x, y)]
    (pin,) = [sh.poly for sh in plan.occupancy.pad_shapes("J1", "2")]
    reading = checks.pour_current("VB", IN2, [("J1", "2", pin)] + [("Q1", "2", r) for r in rings], [],
                                  [pourfit.offset(p.points, p.stroke / 2.0)], {"J1": 4.0, "Q1": 4.0}, {},
                                  s.check_rise_c, checks.COPPER_OZ, s.check_zone_step)
    assert reading.amps == pytest.approx(4.0)
    assert reading.width >= reading.need - 1e-6, reading


def _west_row(b):
    return b.vias(Net("VBUS"), along=PadRef(Part("j1"), "B4A9"), count=3, size=0.6, drill=0.3)


def test_a_via_the_script_placed_outside_the_pour_joins_the_pad():
    b = _board()
    west = _west_row(b)
    j = Part("j1")
    b.via(Net("VBUS"), PadRef(j, "A4B9"), size=0.5, drill=0.25)
    b.pour(Net("VBUS"), [west, PadRef(j, "A4B9")], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not _refused(plan), plan.findings
    (p,) = _pours(plan)
    (v,) = [c for c in plan.copper if isinstance(c, Via) and c.size == 0.5]
    assert _holds(p.points, v.at.x, v.at.y)
    (f,) = _joined(plan)
    assert f.facts["vias"] == [pytest.approx([v.at.x, v.at.y])]


def test_a_via_row_the_script_drew_out_of_the_pad_joins_it():
    """A `vias(along=)` row out of the pad joins it as it joins a via member: it stands beside the pad."""
    b = _board()
    west = _west_row(b)
    j = Part("j1")
    b.vias(Net("VBUS"), along=PadRef(j, "A4B9"), count=3, size=0.6, drill=0.3)
    b.pour(Net("VBUS"), [west, PadRef(j, "A4B9")], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not _refused(plan), plan.findings
    (p,) = _pours(plan)
    east = [c for c in plan.copper if isinstance(c, Via) and c.at.x > 12.5]
    assert len(east) == 3
    for v in east:
        assert _holds(p.points, v.at.x, v.at.y)
    (f,) = _joined(plan)
    assert sorted(map(tuple, f.facts["vias"])) == pytest.approx(sorted((v.at.x, v.at.y) for v in east))


def test_a_cells_via_standing_in_the_pours_way_is_named_as_that_cells_via_at_its_place():
    """A via another cell's layout placed, of another net, wholly inside the hull: the finding names it as that cell's
    via, where it stands, not as a pad with no number."""
    other = dataclasses.replace(_fet(cell="m"), ref="Q2", pads=tuple(
        dataclasses.replace(p, owner="Q2", net="G") for p in _fet(cell="m").pads))
    other = dataclasses.replace(other, location=Location(30.0, 42.0), body_box=Box(28.5, 41.0, 31.5, 43.0),
                                courtyard_box=Box(28.4, 40.9, 31.6, 43.1), phys_box=Box(28.5, 41.0, 31.5, 43.0),
                                pads=tuple(dataclasses.replace(p, outlines=(rect(28.9 + 0.65 * i, 42.0, 0.35, 0.75),),
                                                               box=Box.of_points(rect(28.9 + 0.65 * i, 42.0, 0.35, 0.75)))
                                           for i, p in enumerate(other.pads)))
    o = rect(8.0, ROW_Y, 1.7, 1.3)            # so low that a hole round the via would cut the pour in two
    pin2 = PadGeom("J1", "j1", "3", "VB", FOUR, (rect(14.0, ROW_Y, 1.7, 1.3),), Box.of_points(rect(14.0, ROW_Y, 1.7, 1.3)),
                   True, 1.0)
    pin = dataclasses.replace(_pin(), pads=(PadGeom("J1", "j1", "2", "VB", FOUR, (o,), Box.of_points(o), True, 1.0), pin2),
                              body_box=Box(6.5, 28.5, 15.5, 31.5))
    g = board_geometry([pin, other], cells=("m",), copper=[_via(11.0, ROW_Y, net="G", owner="m")], width=40, height=50,
                       clearance=CLEARANCE)
    g = dataclasses.replace(g, layers=(F, IN1, IN2, B))
    b = Board(g, edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=pin.location)
    b.place(Cell("m"), at=g.cells["m"].box.center)
    b.pour(Net("VB"), [PadRef(Part("j1"), 2), PadRef(Part("j1"), 3)], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not _pours(plan)
    (f,) = [f for f in plan.findings if f.facts.get("variant") == "pour_hole"]
    what = f.facts["what"]
    assert what["form"] == "via" and what["net"] == "G" and what["at"] == pytest.approx([11.0, ROW_Y])
    assert "the m cell's via G at (11.00, 30.00)" in str(f), str(f)
