"""An offset from a pad in its part's own frame: it turns, and on the back
mirrors, with the part. Pure: synthetic boards."""
import pytest

from placemat.layout import Board, _locate
from placemat.values import Face, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _where(rotation, face=Face.FRONT):
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 20), rotation=rotation, face=face)
    b.place(Part("r1"), at=Location(30, 30))
    plan = b.resolve()
    occ = plan.occupancy
    pad2 = occ.pad_location("U1", "2")
    point = _locate(b, occ, PadRef(Part("u1"), 1).local(2.8, 0.0))   # pad 1 to pad 2 is +2.8 in the footprint
    return point, pad2


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_local_offset_turns_with_its_part(rotation):
    point, pad2 = _where(rotation)
    assert point.distance(pad2) < 1e-6


@pytest.mark.parametrize("rotation", [0, 90])
def test_a_local_offset_mirrors_with_a_part_on_the_back(rotation):
    point, pad2 = _where(rotation, Face.BACK)
    assert point.distance(pad2) < 1e-6


def test_local_and_offset_add():
    ref = PadRef(Part("u1"), 1).offset(1.0, 0.0).local(0.0, 2.0)
    assert (ref.dx, ref.dy, ref.lx, ref.ly) == (1.0, 0.0, 0.0, 2.0)
