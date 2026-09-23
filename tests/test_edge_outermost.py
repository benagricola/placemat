"""board.edge(facing, outermost=True): of several runs facing one way, the
one lying furthest out that way."""
import pytest

from placemat.layout import Board
from placemat.values import Edge
from tests.fixtures import board_geometry, footprint

# A tab on the north side: three runs face north - the two shoulders at
# y 10 and the tab's top at y 0 (y grows downward).
TAB = [(0.0, 10.0), (10.0, 10.0), (10.0, 0.0), (20.0, 0.0), (20.0, 10.0), (30.0, 10.0), (30.0, 30.0), (0.0, 30.0)]


def _board():
    b = Board(board_geometry([footprint("R1", 5, 20)], width=30, height=30), edge_margin=0.5)
    b.outline(TAB)
    return b


def test_several_runs_face_north_and_edge_still_asks_which():
    b = _board()
    assert len(b.edges(Edge.NORTH)) == 3
    with pytest.raises(ValueError, match="outermost=True"):
        b.edge(Edge.NORTH)


def test_outermost_takes_the_run_furthest_out():
    run = _board().edge(Edge.NORTH, outermost=True)
    assert all(p[1] == pytest.approx(0.0) for p in run.points)
    assert run.length == pytest.approx(10.0)


def test_outermost_on_a_tie_is_still_a_question():
    """A notch in the north side leaves two tops level at y 0: neither is
    further out, so the script still says which."""
    b = Board(board_geometry([footprint("R1", 15, 20)], width=30, height=30), edge_margin=0.5)
    b.outline([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (20.0, 10.0), (20.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)])
    assert len(b.edges(Edge.NORTH)) == 3          # two tops level at y 0, the notch floor at y 10
    with pytest.raises(ValueError, match="level"):
        b.edge(Edge.NORTH, outermost=True)
