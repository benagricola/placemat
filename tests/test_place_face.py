"""place(face=) takes a Face or the string it prints ("front"/"back"), and
refuses anything else at declaration rather than failing later when the
step tries to read .value off a plain string."""
import pytest

from placemat.layout import Board
from placemat.values import Face, Location, Part
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"))]
    return Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)


@pytest.mark.parametrize("face", [Face.BACK, "back"])
def test_place_accepts_a_face_or_its_string_value(face):
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20), face=face)
    plan = b.resolve()
    assert plan.placement("u1").face is Face.BACK


@pytest.mark.parametrize("face", ["BACK", "backwards", 0])
def test_place_refuses_an_unknown_face_at_declaration(face):
    b = make_board()
    with pytest.raises((TypeError, ValueError)):
        b.place(Part("u1"), at=Location(20, 20), face=face)
