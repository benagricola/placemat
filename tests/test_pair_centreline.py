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
