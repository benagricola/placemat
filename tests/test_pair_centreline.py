"""A pair's centreline is at least two points: fewer is a message when the
pair is declared, not an IndexError when it is planned. Pure."""
import pytest

from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def test_a_pair_with_one_centreline_point_is_refused_by_name():
    fps = [footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("D_P", "D_N")),
           footprint("J1", 30, 10, w=4, h=2, inst="j1", nets=("D_P", "D_N"))]
    b = Board(board_geometry(fps, width=40, height=20), edge_margin=0.5)
    ends = ((PadRef(Part("u1"), "D_P"), PadRef(Part("u1"), "D_N")), (PadRef(Part("j1"), "D_P"), PadRef(Part("j1"), "D_N")))
    with pytest.raises(ValueError, match="two centreline points"):
        b.pair(Net("D_P"), Net("D_N"), [ends[0], Location(20, 10), ends[1]], layer=CopperLayer.F)


def test_a_pair_given_only_its_two_pad_pairs_finds_its_own_centreline():
    """No centreline points: the pair runs from a pitch out of one pad pair
    to a pitch short of the other, octilinear as a track's leg, and each net
    joins its own two pads."""
    import math
    from placemat.copper import Track
    fps = [footprint("U1", 10, 10, w=3, h=2, inst="u1", nets=("D_P", "D_N")),      # pads at x 9.1 and 10.9
           footprint("J1", 16, 30, w=3, h=2, inst="j1", nets=("D_P", "D_N"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("j1"), at=Location(16, 30))
    b.pair(Net("D_P"), Net("D_N"), [(PadRef(Part("u1"), "D_P"), PadRef(Part("u1"), "D_N")),
                                    (PadRef(Part("j1"), "D_P"), PadRef(Part("j1"), "D_N"))], layer=CopperLayer.F)
    plan = b.resolve()
    for net, a, z in (("D_P", "U1", "J1"), ("D_N", "U1", "J1")):
        legs = [t for t in plan.copper if isinstance(t, Track) and t.net == net]
        assert legs, net
        ends = {(round(p.x, 3), round(p.y, 3)) for t in legs for p in (t.start, t.end)}
        num = "1" if net == "D_P" else "2"
        for ref in (a, z):
            pad = plan.occupancy.pad_location(ref, num)
            assert (round(pad.x, 3), round(pad.y, 3)) in ends, (net, ref)
    run = [t for t in plan.copper if isinstance(t, Track) and t.net == "D_P"]
    for t in run:
        ang = math.degrees(math.atan2(t.end.y - t.start.y, t.end.x - t.start.x)) % 45.0
        assert min(ang, 45.0 - ang) < 0.01, t
