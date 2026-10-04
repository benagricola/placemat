"""Centre(x, None, toward=Edge.SOUTH): an item on a line, as far toward the
named end as it is legal. A cell is judged member by member, so a height
band stops its tall member and lets its low one in."""
import pytest

from placemat.cutouts import Path
from placemat.layout import Board
from placemat.values import Cell, Centre, CopperLayer, Edge, Location
from tests.fixtures import board_geometry, footprint


def _board():
    """Cell m: S1 (1.75 mm tall) with P1 (0.5 mm) 4 mm south of it. A band
    from y 30 down to the board's south edge admits parts up to 1.5 mm."""
    fps = [footprint("S1", 20, 10, w=2, h=1, inst="m.s1", cell="m", nets=("A", "B"), fields={"Pm.Height": "1.75mm"}),
           footprint("P1", 20, 14, w=2, h=1, inst="m.p1", cell="m", nets=("C", "D"), fields={"Pm.Height": "0.5mm"})]
    b = Board(board_geometry(fps, cells=["m"], width=40, height=50), edge_margin=0.5, keep_going=True)
    b.keepout(Path([(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (0.0, 20.0)]), "band", at=Location(20, 40),
              excludes=("parts",), max_height=1.5, layers=[CopperLayer.F], why="low parts only")
    return b


def test_toward_takes_the_farthest_legal_spot_and_a_low_member_may_cross_into_the_band():
    b = _board()
    b.place(Cell("m"), at=Centre(20, None, toward=Edge.SOUTH, coordinates=True))
    occ = b.resolve().occupancy
    s1, p1 = occ.items["S1"], occ.items["P1"]
    assert s1.body.bottom <= 30.0 + 1e-6            # the tall member stays out of the band
    assert s1.body.bottom > 30.0 - 0.5              # and no further north than a step
    assert p1.body.top > 30.0                       # the low member stands in it


def test_toward_names_what_stopped_it():
    b = _board()
    b.place(Cell("m"), at=Centre(20, None, toward=Edge.SOUTH, coordinates=True))
    note = b.resolve().step("m").note
    assert "south" in note and "band" in note, note


def test_toward_must_name_an_end_of_the_free_axis():
    with pytest.raises(ValueError, match="toward"):
        Centre(20, None, toward=Edge.EAST, coordinates=True)
