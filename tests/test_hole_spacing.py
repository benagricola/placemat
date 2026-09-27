"""Drilled holes keep the board's hole-to-hole rule from another owner's
holes whatever their nets, and copper keeps the hole clearance from an
unplated hole."""
import dataclasses

from placemat.board_geometry import CopperItem
from placemat.geometry import circle_polygon
from placemat.occupancy import Occupancy, Shape
from placemat.placement import Placement
from placemat.values import Box, CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint, track

F, B = CopperLayer.F, CopperLayer.B


def _via(net, x, y, owner=None, size=0.6, drill=0.3):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", net, frozenset([F, B]), (ring,), Box.of_points(ring), owner, 0.0, drill, ((x, y),))


def _occ(fps, copper=(), cells=(), hole_to_hole=0.3, hole_clearance=0.25):
    g = board_geometry(fps, cells=cells, copper=copper, width=50, height=50, extra_nets=("GND",))
    return Occupancy(dataclasses.replace(g, hole_to_hole=hole_to_hole, hole_clearance=hole_clearance), edge_margin=0.0)


def _cells():
    """Cell a: a part with a GND via 2.5 mm east of it. Cell b: a part with a
    GND via 2 mm north of it."""
    fps = [footprint("A1", 10, 10, w=2, h=1, cell="a", inst="a.r"),
           footprint("B1", 30, 30, w=2, h=1, cell="b", inst="b.r")]
    return _occ(fps, copper=[_via("GND", 12.5, 10, owner="a"), _via("GND", 30, 28, owner="b")], cells=["a", "b"])


def _b_with_its_via_at(occ, x, y):
    b = occ.geometry.cell("b")
    ref = occ._geometry(b).reference
    return b, Placement(Location(ref.location.x + x - 30, ref.location.y + y - 28), ref.rotation, ref.face)


def test_two_cells_vias_of_one_net_keep_the_hole_to_hole_rule():
    occ = _cells()
    b, at = _b_with_its_via_at(occ, 12.5 + 0.55, 10)          # centres 0.55 apart: holes 0.25
    why = occ.legal(b, at)
    assert why is not None and "hole" in why and "0.25" in why and "0.30" in why


def test_two_cells_vias_the_rule_apart_may_stand():
    occ = _cells()
    b, at = _b_with_its_via_at(occ, 12.5 + 0.65, 10)          # holes 0.35 apart
    assert occ.legal(b, at) is None


def test_a_through_pad_keeps_the_rule_from_a_via_of_its_own_net():
    part = footprint("P1", 30, 30, w=4, h=2, nets=("GND", "X"), through=True)   # 0.5 mm drills
    occ = _occ([part], copper=[_via("GND", 20, 20)])
    # pad 1 sits 1.4 west of the part's centre: its hole 0.1 mm from the via's
    why = occ.legal(part, Placement(Location(20 + 1.4 + 0.5, 20), 0, Face.FRONT))
    assert why is not None and "hole" in why and "0.10" in why


def test_copper_keeps_the_hole_clearance_from_an_unplated_hole():
    peg = dataclasses.replace(footprint("J1", 30, 30, w=6, h=4, nets=("C", "D")), npth=((Location(30, 30), 1.0),))
    # a track of net A along y = 19.25 (edges 19.1..19.4): 0.1 mm from the hole when J1's centre is at y 20
    occ = _occ([peg], copper=[track("A", 19, 19.25, 21, 19.25)])
    why = occ.legal(peg, Placement(Location(20, 20), 0, Face.FRONT))
    assert why is not None and "hole" in why
    assert occ.legal(peg, Placement(Location(20, 20.2), 0, Face.FRONT)) is None     # 0.3 mm


def test_a_parts_own_holes_are_its_own():
    part = footprint("P1", 30, 30, w=1.8, h=2, nets=("GND", "GND"), through=True)  # its holes 0.1 mm apart
    occ = _occ([part])
    assert occ.legal(part, Placement(Location(20, 20), 0, Face.FRONT)) is None


def test_a_hole_is_not_copper_to_the_copper_checks():
    occ = _occ([footprint("R1", 40, 40)], copper=[_via("GND", 20, 20)])
    ring = circle_polygon(Location(20.85, 20), 0.3)                   # rings 0.25 apart, holes 0.55
    assert occ.copper_conflicts(Shape("", "through", frozenset([Face.FRONT, Face.BACK]), frozenset([F, B]), "X",
                                      ring, Box.of_points(ring))) == []


def test_a_searched_part_keeps_its_holes_clear_of_a_via_the_script_declared():
    from placemat.layout import Board
    from placemat.values import Near, Net, Part
    part = footprint("P1", 40, 40, w=4, h=2, nets=("GND", "X"), through=True, inst="p1")
    g = dataclasses.replace(board_geometry([part], width=50, height=50, extra_nets=("GND",)), hole_to_hole=0.3)
    b = Board(g, edge_margin=0.5)
    b.via(Net("GND"), Location(20, 20))
    b.place(Part("p1"), at=Near(Location(21.9, 20), radius=3))      # there, pad 1's hole is 0.1 mm from the via's
    plan = b.resolve()
    pad1 = plan.occupancy.pad_location("P1", "1")
    assert pad1.distance(Location(20, 20)) >= 0.25 + 0.15 + 0.3 - 1e-6


def test_a_pad_over_an_unplated_hole_conflicts_whichever_moves():
    """A block lays its satellites by `_conflict` against its anchor's
    shapes, the satellite's first: a pad over the anchor's peg hole was
    let through."""
    occ = _occ([footprint("R1", 40, 40)])
    hole = circle_polygon(Location(20, 20), 0.5)
    peg = Shape("J1", "npth", frozenset([Face.FRONT, Face.BACK]), frozenset(CopperLayer), "", hole, Box.of_points(hole))
    land = ((19.8, 19.8), (20.8, 19.8), (20.8, 20.8), (19.8, 20.8))
    pad = Shape("D1", "pad", frozenset([Face.FRONT]), frozenset([F]), "USB_P", land, Box.of_points(land), "3")
    assert occ._conflict(pad, peg, None) is not None and occ._conflict(peg, pad, None) is not None


def test_vias_filling_a_pad_keep_clear_of_a_via_already_on_the_board():
    """The via planner judged its sites against the parts' holes only: a
    via the board already carried, or a stamped cell's, was not a hole to it."""
    from placemat.copper import Via
    from placemat.layout import Board
    from placemat.values import Net, PadRef, Part
    from tests.fixtures import pad
    from tests.test_pad_vias import _part
    lands = [pad("U1", "u1", 1, "GND", 20, 20, 3.0, 3.0), pad("U1", "u1", 2, "SIG", 20, 23, 1, 1)]
    g = board_geometry([_part(lands)], copper=[_via("GND", 20.3, 20.3)], width=40, height=40, extra_nets=("GND",))
    g = dataclasses.replace(g, hole_to_hole=0.25)
    b = Board(g, edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 21.5))
    b.vias(Net("GND"), PadRef(Part("u1"), 1), size=0.6, drill=0.3)
    plan = b.resolve()
    vias = [c for c in plan.copper if isinstance(c, Via)]
    assert vias
    assert all(v.at.distance(Location(20.3, 20.3)) - 0.3 >= 0.25 - 1e-6 for v in vias)
