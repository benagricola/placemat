"""A fragment's frame sized to what is placed in it. Pure: synthetic boards."""
import pytest

from placemat.layout import Board
from placemat.values import Edge, Location, OnEdge, Part, PadRef, Pin, X, Y
from tests.fixtures import board_geometry, footprint


def _board(**kw):
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("C1", 30, 30, w=2, h=1, inst="c1", nets=("A", "GND")),
           footprint("R1", 34, 34, w=2, h=1, inst="r1", nets=("B", "GND"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=0.5)
    b.size(fit=True, draw=False, **kw)
    return b


def test_fit_is_for_a_fragments_frame_only():
    b = Board(board_geometry([footprint("U1", 20, 20, inst="u1")], width=60, height=60))
    with pytest.raises(ValueError, match="fit"):
        b.size(fit=True, draw=True)


def test_what_needs_the_frame_is_refused_on_a_fit_board():
    b = _board()
    for ask in (lambda: b.width, lambda: b.height, lambda: b.centre,
                lambda: b.place(Part("c1"), at=OnEdge(Edge.NORTH)),
                lambda: b.row([Part("c1"), Part("r1")], Edge.SOUTH),
                lambda: b.edge(Edge.NORTH)):
        with pytest.raises(ValueError, match="fit"):
            ask()


def test_a_searched_part_goes_round_the_decided_content():
    b = _board()
    b.place(Part("u1"), at=Location(0, 0))
    b.place(Part("c1"))
    plan = b.resolve()
    p = plan.placement("c1")
    assert p is not None and p.location.distance(Location(0, 0)) < b.settings.place_fit_room + 5


def test_with_nothing_decided_the_first_part_is_at_the_origin():
    b = _board()
    b.place(Part("u1"))
    plan = b.resolve()
    assert plan.placement("u1").location.distance(Location(0, 0)) < 1e-6
