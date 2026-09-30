"""Tracks planned after the copper whose every point was decided up front
are judged for crossings against that copper's tracks only: a bridge made
among the decided tracks leaves vias, which are not tracks."""
from placemat.copper import Track, Via
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Near, Net, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint

F = CopperLayer.F


def test_a_later_track_is_planned_after_a_decided_track_is_bridged():
    fps = [footprint("R1", 10, 10, w=4, h=2, inst="r1", nets=("A", "B")),
           footprint("R2", 30, 30, w=4, h=2, inst="r2", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=60, height=60, extra_nets=["X", "Y"]), edge_margin=1.0)
    b.track(Net("X"), [Location(20, 40), Location(30, 40)], layer=F)                  # decided, crossing
    b.track(Net("Y"), [Location(25, 35), Location(25, 45)], layer=F, priority=Priority.LOW, bridge=True)
    b.place(Part("r2"), at=Near(Location(30, 30), radius=3))                           # found by a search
    b.track(Net("A"), [PadRef(Part("r1"), 1), PadRef(Part("r2"), 1)], layer=F)
    plan = b.resolve()
    assert [op for op in plan.copper if isinstance(op, Via) and op.net == "Y"]         # Y passed under X
    assert any(isinstance(op, Track) and op.net == "A" for op in plan.copper)
