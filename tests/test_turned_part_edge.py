"""A part turned off the axes near a round rim is judged by what it is, not
the box round it: the box's corner can pass the keep-in while every corner
of the part is inside. Pure: synthetic boards."""
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _disc(y):
    b = Board(board_geometry([footprint("L1", 10, 10, w=4, h=1, inst="l1", excess=0.0)], width=20, height=20),
              edge_margin=0.5, keep_going=True)
    b.disc(20.0)
    b.place(Part("l1"), at=Location(10.0, y), rotation=45)
    return b.resolve()


def test_a_turned_part_whose_box_corner_passes_the_rim_but_it_does_not_is_placed():
    # 4 x 1 turned 45: its box reaches 1.77 each way, its own corners 1.77 along one axis and 1.06
    # along the other; 7.62 north of the centre, the box's corner is past a 9.5 keep-in and the part is not
    plan = _disc(10.0 - 7.62)
    assert not [f for f in plan.findings if "keep-in" in f or "board edge" in f], plan.findings


def test_a_turned_part_that_does_pass_the_rim_is_still_refused():
    plan = _disc(10.0 - 8.2)
    assert [f for f in plan.findings if "keep-in" in f or "outside" in f]
