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


def test_the_placed_keepout_carries_its_height_admission_separately():
    b, plan = _board("1.1mm")
    k = plan.keepouts["ring"]
    assert k.max_height == 1.9
    assert k.admitted == {"C1"}
    assert k.owners == {"C1"}                      # unchanged: still the union, for runner.py


def test_a_part_named_in_allow_is_not_counted_as_height_admitted():
    b, plan = _board("2.5", allow=(Part("c1"),))
    k = plan.keepouts["ring"]
    assert k.admitted == frozenset()
    assert k.owners == {"C1"}


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


def _cell_board(heights):
    fps = [footprint("R1", 20, 20, w=1, h=0.5, inst="mod.r1", cell="mod", nets=("A", "B"),
                     fields={"Pm.Height": heights[0]} if heights[0] else {}),
           footprint("L1", 22, 20, w=2, h=2, inst="mod.l1", cell="mod", nets=("B", "C"),
                     fields={"Pm.Height": heights[1]} if heights[1] else {})]
    b = Board(board_geometry(fps, cells=["mod"], width=40, height=40), edge_margin=0.5, keep_going=True)
    b.keepout(Circle(12.0), "ring", at=Location(21, 20), excludes=("parts",), max_height=1.9, why="the case")
    from placemat.values import Cell
    b.place(Cell("mod"), at=Location(21, 20))
    return b.resolve()


def test_a_cell_with_one_tall_member_is_refused_and_the_finding_names_it():
    plan = _cell_board(("0.4mm", "3.0mm"))
    hits = [f for f in plan.findings if "ring" in f]
    assert hits and any("L1" in f and "3" in f for f in hits), plan.findings


def test_a_cell_whose_members_are_all_short_is_admitted():
    plan = _cell_board(("0.4mm", "1.2mm"))
    assert not [f for f in plan.findings if "ring" in f], plan.findings


def test_a_member_with_no_height_is_named_in_the_finding():
    plan = _cell_board(("0.4mm", None))
    assert any("L1" in f and "no Pm.Height" in f for f in plan.findings), plan.findings


def test_a_bad_height_shows_in_the_listing_and_a_negative_one_is_refused():
    from placemat.describe import parts_lines
    bad = footprint("C1", 20, 20, inst="c1", fields={"Pm.Height": "1,1mm"})
    neg = footprint("C2", 25, 20, inst="c2", fields={"Pm.Height": "-1"})
    g = board_geometry([bad, neg], width=40, height=40)
    text = "\n".join(parts_lines(g))
    assert "?" in text
    with pytest.raises(ValueError, match="negative"):
        Board(g, edge_margin=0.5).height_of(Part("c2"))
