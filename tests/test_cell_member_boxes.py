"""A cell is judged against keepouts and the board's edge by its members,
not by the rectangle round them: an L-shaped cell's empty corner may sit in
a keepout or past a round board's rim."""
import pytest

from placemat.cutouts import Circle
from placemat.layout import Board, PlacementCollision
from placemat.values import Cell, Location
from tests.fixtures import board_geometry, footprint


def _l_cell(**kw):
    """Cell `mod`: a member at the box's top left, one at its bottom right,
    and the top right corner empty. Its box is 10 x 8, centred on (13, 13)."""
    fps = [footprint("U1", 10, 10, w=4, h=2, cell="mod", inst="mod.a", nets=("A", "B")),
           footprint("C1", 16, 16, w=4, h=2, cell="mod", inst="mod.b", nets=("A", "C"))]
    return Board(board_geometry(fps, cells=["mod"], **kw), edge_margin=1.0)


def test_a_keepout_in_a_cells_empty_corner_does_not_refuse_it():
    b = _l_cell(width=60, height=60)
    b.keepout(Circle(2.0), "hole", at=Location(33, 28), why="hole")       # in the empty corner at (30, 30)
    b.place(Cell("mod"), at=Location(30, 30))
    assert b.resolve().placement("mod").location == Location(30, 30)


def test_a_keepout_over_a_member_still_refuses_the_cell():
    b = _l_cell(width=60, height=60)
    b.keepout(Circle(2.0), "hole", at=Location(27, 27), why="hole")       # on the top left member
    b.place(Cell("mod"), at=Location(30, 30))
    with pytest.raises(PlacementCollision, match="sits in the reservation for keepout 'hole'"):
        b.resolve()


def test_a_cells_empty_corner_may_sit_past_a_round_boards_rim():
    b = _l_cell(width=60, height=60)
    b.outline(Circle(60.0))                     # centre (30, 30), radius 30
    b.place(Cell("mod"), at=Location(47, 13))   # only the box's empty corner (52, 9) is past the rim
    assert b.resolve().placement("mod").location == Location(47, 13)


def test_a_searched_cell_by_the_rim_and_a_keepout_is_the_same_native_and_python(monkeypatch):
    """The native sweep judges a cell's members as Python does: the same
    spot, tries and refusals, and the spot is one its box alone would lose."""
    from placemat import geometry, placer
    from placemat.values import Near
    if geometry._native is None:
        pytest.skip("no native module")
    runs = {}
    base = placer.ScanResult
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        seen = []

        class Recorded(base):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                seen.append(self)
        monkeypatch.setattr(placer, "ScanResult", Recorded)
        b = _l_cell(width=60, height=60)
        b.outline(Circle(60.0))
        b.keepout(Circle(2.0), "hole", at=Location(44, 20), why="hole")
        b.place(Cell("mod"), at=Near(Location(47, 13), radius=3.0, step=0.5, rotations=(0,)))
        plan = b.resolve()
        runs[on] = ([(r.chosen, r.tried, dict(r.rejected), dict(r.reasons)) for r in seen],
                    plan.placement("mod"))
    assert runs[True] == runs[False]
    at = runs[True][1].location
    assert (at.x - 47) ** 2 + (at.y - 13) ** 2 < 1.0          # close to the hint: past the rim by its box alone
