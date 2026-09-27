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
