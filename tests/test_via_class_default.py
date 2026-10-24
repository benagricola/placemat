"""A via drawn with no size or drill takes its net's class via (the Default class's for a net with no class of its
own); the board's via_size and via_drill serve a net no class names or a class that sets none. An explicit size or
drill wins. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.board_geometry import NetClass
from placemat.copper import Track, Via, bridge_track, finger_ops, pair_ops
from placemat.layout import Board
from placemat.values import CopperLayer, Edge, Location, Net, PadRef, Part
from tests.escape_fixtures import PD_NETS, board_with, pd_board, qfn
from tests.fixtures import board_geometry, footprint

DEFAULT = (0.45, 0.20)      # (size, drill) of the Default class
FAST = (0.50, 0.25)         # of another class
BOARD = (0.60, 0.30)        # the board's own


def _classes(geom, **by_net):
    """`geom` with every net in the Default class, and `by_net` (net -> NetClass or None to drop it)."""
    classes = {n: NetClass("Default", 0.2, 0.2, *DEFAULT) for n in geom.nets}
    for n, c in by_net.items():
        if c is None:
            classes.pop(n, None)
        else:
            classes[n] = c
    return dataclasses.replace(geom, netclasses=classes)


FASTCLASS = NetClass("Fast", 0.2, 0.2, *FAST)


def _board(fps, **by_net):
    geom = _classes(board_geometry(fps, width=60, height=60, extra_nets=["X", "Y", "ORPHAN"]), **by_net)
    return Board(geom, edge_margin=1.0)       # the board's via_size and via_drill are 0.6 and 0.3


def _vias(plan):
    return {v.net: (v.size, v.drill) for v in plan.copper if isinstance(v, Via)}


def test_via_takes_its_nets_class_via():
    b = _board([], X=FASTCLASS, ORPHAN=None)
    b.via(Net("Y"), at=Location(10, 10))
    b.via(Net("X"), at=Location(20, 10))
    b.via(Net("ORPHAN"), at=Location(30, 10))
    assert _vias(b.resolve()) == {"Y": DEFAULT, "X": FAST, "ORPHAN": BOARD}


def test_a_class_that_sets_no_via_leaves_the_boards():
    b = _board([], X=NetClass("Bare", 0.2, 0.2, 0.0, 0.0))
    b.via(Net("X"), at=Location(10, 10))
    assert _vias(b.resolve()) == {"X": BOARD}


def test_an_explicit_size_or_drill_wins_and_the_other_stays_the_classs():
    b = _board([], X=FASTCLASS)
    b.via(Net("X"), at=Location(10, 10), size=0.8)
    b.via(Net("Y"), at=Location(20, 10), drill=0.35)
    got = _vias(b.resolve())
    assert got == {"X": (0.8, FAST[1]), "Y": (DEFAULT[0], 0.35)}


def test_vias_takes_its_nets_class_via_unless_told():
    fps = [footprint("U1", 20, 20, w=6, h=6, inst="u1", nets=("X", "Y"))]
    b = _board(fps, X=FASTCLASS)
    b.place(Part("u1"), at=Location(20, 20))
    b.vias(Net("X"), along=PadRef(Part("u1"), 1), count=1)
    b.vias(Net("Y"), along=PadRef(Part("u1"), 2), count=1, size=0.7, drill=0.35)
    got = _vias(b.resolve())
    assert got.get("X") == FAST and got.get("Y") == (0.7, 0.35), got


def test_escape_vias_each_take_their_own_nets_class_via():
    nets = {"SENSE": FASTCLASS}                 # the other nets: the fixture's Default class, 0.45 / 0.20
    b = board_with([qfn(nets=PD_NETS)], classes=nets)
    b.via_size, b.via_drill = BOARD                 # the board's own differ from every class's
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], chamfer=0.0, why="mixed classes")
    for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
        b.track(Net(net), [esc[pin]], layer=CopperLayer.F, why="its lane")
    got = _vias(b.resolve())
    assert got["SENSE"] == FAST and got["PGOOD"] == DEFAULT, got


def test_an_escape_with_an_explicit_via_size_applies_it_to_every_lane():
    nets = {"SENSE": NetClass("Fast", 0.2, 0.2, *FAST)}
    b = board_with([qfn(nets=PD_NETS)], classes=nets)
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], chamfer=0.0, via_size=0.5, via_drill=0.25,
                   why="explicit")
    for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
        b.track(Net(net), [esc[pin]], layer=CopperLayer.F, why="its lane")
    assert set(_vias(b.resolve()).values()) == {(0.5, 0.25)}


def test_an_escape_declares_no_via_size_of_its_own_by_default():
    b = pd_board()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31], why="the default")
    decl = b._escapes[esc.index]
    assert (decl.via_size, decl.via_drill) == (None, None)


def test_a_board_pairs_vias_take_each_nets_class():
    # surface pads and a pair on the far face: each lead goes over from a via of its own net
    fps = [footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("DP", "DN")),
           footprint("J1", 10, 40, w=4, h=2, inst="j1", nets=("DP", "DN"))]
    b = _board(fps, DP=FASTCLASS)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("j1"), at=Location(10, 40))
    ends = ((PadRef(Part("u1"), "DP"), PadRef(Part("u1"), "DN")), (PadRef(Part("j1"), "DP"), PadRef(Part("j1"), "DN")))
    b.pair(Net("DP"), Net("DN"), [ends[0], Location(10, 14), Location(10, 36), ends[1]], layer=CopperLayer.B,
           width=0.2, gap=0.35)
    got = _vias(b.resolve())
    assert got.get("DP") == FAST and got.get("DN") == DEFAULT, got


def test_copper_helpers_take_each_nets_via_from_via_of():
    def via_of(net):
        return (0.25, 0.5) if net == "P" else (0.2, 0.45)
    a, z = Location(0, 0), Location(10, 0)
    t = Track("P", CopperLayer.F, 0.2, a, z)
    ops = bridge_track(t, [(5, 0)], 0.3, 0.6, via_of=via_of)
    assert {(v.drill, v.size) for v in ops if isinstance(v, Via)} == {(0.25, 0.5)}
    ops = finger_ops("N", CopperLayer.F, a, z, 2.0, [((5.0, -3.0), (5.0, 3.0))], 0.3, 0.6, 0.2, 0.3, 0.1, via_of=via_of)
    assert {(v.drill, v.size) for v in ops if isinstance(v, Via)} == {(0.2, 0.45)}
