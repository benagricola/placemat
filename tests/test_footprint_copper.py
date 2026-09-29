"""A footprint's own copper graphics - a net-tie's winding, an antenna's
trace - are copper to the placer: another net's pad keeps its clearance
from them. Pure: synthetic boards."""
import dataclasses

from placemat.layout import Board
from placemat.values import CopperLayer, Location, Part
from tests.fixtures import board_geometry, footprint, rect


def _board(y):
    coil = footprint("L1", 20, 20, w=2, h=1, inst="l1", nets=("COIL_A", "COIL_B"))
    art = rect(20.0, 23.0, 6.0, 0.5)                 # a winding's trace below the part, on the back
    coil = dataclasses.replace(coil, copper=((CopperLayer.B, art),))
    cap = footprint("C1", 20, y, w=2, h=1, inst="c1", nets=("TANK", "GND"), through=True)
    b = Board(board_geometry([coil, cap], width=40, height=40), edge_margin=0.5, keep_going=True)
    b.place(Part("l1"), at=Location(20, 20))
    b.place(Part("c1"), at=Location(20, y))
    return b.resolve()


def test_a_pad_on_a_footprints_copper_trace_is_refused():
    plan = _board(23.6)                                # the cap's pads 0.1 mm off the trace's edge
    assert [f for f in plan.findings if "c1" in f and ("copper" in f or "L1" in f)], plan.findings


def test_a_pad_clear_of_the_trace_is_placed():
    plan = _board(25.0)
    assert not [f for f in plan.findings if "c1" in f], plan.findings


def test_a_via_on_a_footprints_copper_trace_is_a_conflict():
    """Script copper and vias see a footprint's copper too, not only the
    placer: a ground drop may not land on a winding."""
    from placemat.geometry import circle_polygon
    from placemat.occupancy import Shape
    from placemat.values import Box
    plan = _board(30.0)
    ring = circle_polygon(Location(20.0, 23.0), 0.3)
    via = Shape("", "copper", frozenset(), frozenset([CopperLayer.F, CopperLayer.B]), "GND", ring, Box.of_points(ring))
    assert plan.occupancy.copper_conflicts(via)


def _tank_board(net_tie_pads, track_net="COIL_A"):
    """A winding that leaves pad 1 southward, drawn as the footprint's own
    net-less copper; a track that ends on pad 1's centre from the west. They
    meet only inside pad 1."""
    from placemat.values import Net, PadRef
    coil = footprint("L1", 20, 20, w=2, h=1, inst="l1", nets=("COIL_A", "COIL_B"))   # pad 1 box (19.1, 19.5)-(20.1, 20.5)
    art = rect(19.6, 21.5, 0.2, 3.0)                                                 # (19.5, 20.0)-(19.7, 23.0)
    coil = dataclasses.replace(coil, copper=((CopperLayer.F, art),), net_tie_pads=frozenset(net_tie_pads))
    b = Board(board_geometry([coil], width=40, height=40, extra_nets=["OTHER"]), edge_margin=0.5, keep_going=True)
    b.place(Part("l1"), at=Location(20, 20))
    b.track(Net(track_net), [Location(15.0, 20.0), PadRef(Part("l1"), 1)], layer=CopperLayer.F, chamfer=0)
    return b.resolve()


def test_a_track_meeting_a_net_tie_winding_inside_its_own_pad_is_not_a_conflict():
    """KiCad's DRC_ENGINE::IsNetTieExclusion: a track of a net-tie pad's net
    colliding with that footprint's copper inside that pad is allowed."""
    plan = _tank_board({"1", "2"})
    assert not [f for f in plan.findings if "L1 copper" in f], plan.findings


def test_the_same_meeting_on_a_footprint_that_is_no_net_tie_is_a_conflict():
    plan = _tank_board(())
    assert [f for f in plan.findings if "L1 copper" in f], plan.findings
