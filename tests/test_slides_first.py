"""Within a priority tier an item with one freedom left (a slide along a line,
an edge, a ring, a spoke) goes down before an item searched in two, and the
rank orders items with the same number of freedoms. Tiers keep their order."""
import pytest

from placemat.layout import Board
from placemat.values import (Centre, Edge, Location, Near, OnEdge, OnRim, PadRef, Part, Polar,
                             Priority)
from tests.fixtures import board_geometry, footprint


def _board():
    """A large part, a small one and a smaller one, on a board 40 wide and 50 tall."""
    fps = [footprint("BIG", 20, 25, w=10, h=10, inst="big", nets=("A", "B")),
           footprint("SML", 20, 25, w=3, h=2, inst="sml", nets=("C", "D")),
           footprint("T1", 20, 25, w=2, h=1, inst="t1", nets=("E", "F"))]
    return Board(board_geometry(fps, width=40, height=50), edge_margin=0.5, keep_going=True)


def _order(plan, *keys):
    return [s.item for s in plan.steps if s.item in keys]


def test_a_slide_goes_before_a_larger_fully_searched_item_of_its_tier():
    b = _board()
    b.place(Part("big"), priority=Priority.HIGH)
    b.place(Part("sml"), at=Centre(20, None, toward=Edge.SOUTH), priority=Priority.HIGH)
    assert _order(b.resolve(), "big", "sml") == ["sml", "big"]


def test_the_slide_reaches_its_end_when_the_larger_item_is_searched_there():
    b = _board()
    b.place(Part("big"), at=Near(Location(20, 44), radius=6.0), priority=Priority.HIGH)
    b.place(Part("sml"), at=Centre(20, None, toward=Edge.SOUTH), priority=Priority.HIGH)
    occ = b.resolve().occupancy
    assert occ.items["SML"].body.bottom > 50 - 0.5 - 1.0, occ.items["SML"].body
    assert "BIG" in occ.items


def test_items_of_different_tiers_keep_the_tier_order():
    b = _board()
    b.place(Part("big"), priority=Priority.HIGH)
    b.place(Part("sml"), at=Centre(20, None, toward=Edge.SOUTH))              # a slide, but DEFAULT
    assert _order(b.resolve(), "big", "sml") == ["big", "sml"]
    b2 = _board()
    b2.place(Part("big"))
    b2.place(Part("sml"), at=Centre(20, None, toward=Edge.SOUTH), priority=Priority.LOW)
    assert _order(b2.resolve(), "big", "sml") == ["big", "sml"]


def test_slides_of_one_tier_go_by_rank():
    b = _board()
    b.place(Part("sml"), at=Centre(10, None, toward=Edge.SOUTH))
    b.place(Part("big"), at=Centre(30, None, toward=Edge.SOUTH))
    assert _order(b.resolve(), "big", "sml") == ["big", "sml"]


def test_with_no_slide_the_order_is_the_rank():
    b = _board()
    b.place(Part("sml"))
    b.place(Part("big"))
    b.place(Part("t1"))
    assert _order(b.resolve(), "big", "sml", "t1") == ["big", "sml", "t1"]


def test_a_linked_slide_does_not_wait_for_a_partner_searched_in_two():
    b = _board()
    b.link(PadRef(Part("big"), "A"), PadRef(Part("sml"), "C"))
    b.place(Part("big"))
    b.place(Part("sml"), at=Centre(20, None, toward=Edge.SOUTH))
    assert _order(b.resolve(), "big", "sml") == ["sml", "big"]


def _freedoms(b, key):
    return next(i for i in b._placements() if i.key == key).freedoms


@pytest.mark.parametrize("at,expected", [
    (Location(None, 20), 1),
    (Centre(None, 20, toward=Edge.WEST), 1),
    (OnEdge(Edge.WEST), 1),
    (Polar(10.0), 1),                                   # a ring: the bearing is free
    (Polar(None, 90.0), 1),                             # a spoke: the radius is free
    (Polar((5.0, 12.0), 90.0), 1),                      # a spoke segment
    (Polar((5.0, 12.0), None), 2),                      # a band
    (Near(Location(20, 20)), 2),
    (None, 2),
    (Location(20, 20), 0),
    (OnEdge(Edge.WEST, along=5.0), 0),
])
def test_freedoms_by_declaration(at, expected):
    b = _board()
    b.place(Part("sml"), **({} if at is None else {"at": at}))
    assert _freedoms(b, "sml") == expected


def test_a_run_and_a_rim_slide_in_one_freedom():
    fps = [footprint("S1", 20, 20, w=3, h=2, inst="s1", nets=("A", "B")),
           footprint("S2", 20, 20, w=3, h=2, inst="s2", nets=("C", "D"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, keep_going=True)
    b.disc(diameter=38.0)
    b.place(Part("s1"), at=OnRim())
    b.place(Part("s2"), at=OnEdge(b.edge(facing=Edge.NORTH)))
    assert _freedoms(b, "s1") == 1
    assert _freedoms(b, "s2") == 1
