"""A parts keepout that admits parts by height: `Pm.Height` on each part,
`max_height=` on the region. Pure: synthetic boards."""
import pytest

from placemat.cutouts import Circle
from placemat.describe import parts_rows
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _board(height, **kw):
    fields = {} if height is None else {"Pm.Height": height}
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields=fields)]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, keep_going=True)
    b.keepout(Circle(8.0), "ring", at=Location(20, 20), excludes=("parts",), max_height=1.9,
              why="the case leaves 1.9 mm here", **kw)
    b.place(Part("c1"), at=Location(20, 20))
    return b, b.resolve()


def test_a_part_no_taller_than_the_limit_is_admitted():
    b, plan = _board("1.1mm")
    assert not [f for f in plan.findings if "ring" in f], plan.findings
    assert "C1" in plan.keepouts["ring"].owners               # so KiCad's rule-area report sets it aside too


def test_a_taller_part_is_refused():
    b, plan = _board("2.5")
    assert [f for f in plan.findings if "ring" in f]


def test_a_part_of_unknown_height_is_refused_and_the_finding_says_why():
    b, plan = _board(None)
    assert [f for f in plan.findings if "ring" in f and "Pm.Height" in f]


def test_allow_still_admits_a_tall_part_by_name():
    b, plan = _board("2.5", allow=(Part("c1"),))
    assert not [f for f in plan.findings if "ring" in f]


def test_the_board_answers_a_parts_height_and_the_listing_shows_it():
    b, plan = _board("1.1mm")
    assert b.height_of(Part("c1")) == pytest.approx(1.1)
    (row,) = parts_rows(b.geometry)
    assert row["height"] == pytest.approx(1.1)
    b2, _ = _board(None)
    with pytest.raises(ValueError, match="Pm.Height"):
        b2.height_of(Part("c1"))


def test_max_height_is_for_a_parts_keepout():
    fps = [footprint("C1", 20, 20, inst="c1")]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    with pytest.raises(ValueError, match="parts"):
        b.keepout(Circle(8.0), "ring", at=Location(20, 20), excludes=("vias",), max_height=1.9, why="x")
