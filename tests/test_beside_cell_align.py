"""Beside(...)'s align= for a cell being placed: a member's pad stands for the cell's own pad
(a pair, or a bare PadRef on a net), and a bare point lines the envelope's centre up. Pure:
synthetic boards."""
import pytest

from placemat.layout import Board
from placemat.values import (Beside, Cell, Edge, Location, Mid, Origin, Past, PadRef, Part, X, Y)
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="terms.u1", nets=("A", "B"), cell="terms"),
           footprint("U2", 10, 0, w=4, h=2, inst="terms.u2", nets=("C", "D"), cell="terms"),
           footprint("U3", 0, 0, w=4, h=2, inst="disp.u3", nets=("E", "F"), cell="disp"),
           footprint("U4", 0, 0, w=4, h=2, inst="other.u4", nets=("G", "H"), cell="other"),
           footprint("U5", 20, 70, w=4, h=2, inst="mcu", nets=("A", "C")),
           footprint("R6", 80, 80, w=3, h=1.3, inst="lone", nets=("A", "C"))]
    b = Board(board_geometry(fps, cells=["terms", "disp", "other"], width=100, height=100), edge_margin=1.0)
    b.place(Part("mcu"), at=Location(20, 70))
    b.place(Cell("disp"), at=Location(50, 20))
    return b


def _pad_x(plan, ref, number):
    return plan.occupancy.pad_location(ref, number).x


def test_a_members_pad_lines_up_with_their_pad():
    b = make_board()
    b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH,
                                     align=(PadRef(Part("terms.u2"), 2), PadRef(Part("mcu"), 1))))
    plan = b.resolve()
    assert _pad_x(plan, "U2", "2") == pytest.approx(_pad_x(plan, "U5", "1"))
    assert plan.box("terms").top > plan.box("disp").bottom


def test_a_members_pad_lines_up_with_a_point():
    b = make_board()
    b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH,
                                     align=(PadRef(Part("terms.u1"), 1),
                                            Mid(PadRef(Part("mcu"), 1), PadRef(Part("mcu"), 2)))))
    plan = b.resolve()
    mid = (_pad_x(plan, "U5", "1") + _pad_x(plan, "U5", "2")) / 2.0
    assert _pad_x(plan, "U1", "1") == pytest.approx(mid)


def test_a_members_pad_lines_up_with_a_y_on_the_east_side():
    b = make_board()
    b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.EAST,
                                     align=(PadRef(Part("terms.u1"), 1), Y(PadRef(Part("mcu"), 2), 1.0))))
    plan = b.resolve()
    assert plan.occupancy.pad_location("U1", "1").y == pytest.approx(
        plan.occupancy.pad_location("U5", "2").y + 1.0)


def test_a_bare_pad_takes_the_members_pad_on_its_net():
    b = make_board()
    b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH, align=PadRef(Part("mcu"), 2)))
    plan = b.resolve()                      # mcu pad 2 is on net C, which terms.u2 pad 1 carries
    assert _pad_x(plan, "U2", "1") == pytest.approx(_pad_x(plan, "U5", "2"))


def test_a_bare_point_centres_the_envelope_on_it():
    b = make_board()
    b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH,
                                     align=Mid(PadRef(Part("mcu"), 1), PadRef(Part("mcu"), 2))))
    plan = b.resolve()
    mid = (_pad_x(plan, "U5", "1") + _pad_x(plan, "U5", "2")) / 2.0
    assert plan.box("terms").center.x == pytest.approx(mid)


def test_a_bare_x_and_an_origin_centre_the_envelope_too():
    for point in (X(PadRef(Part("mcu"), 1), 2.0), Origin(Part("mcu"))):
        b = make_board()
        b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH, align=point))
        plan = b.resolve()
        want = _pad_x(plan, "U5", "1") + 2.0 if isinstance(point, X) else 20.0
        assert plan.box("terms").center.x == pytest.approx(want)


def test_a_bare_y_centres_the_envelope_on_the_east_side():
    b = make_board()
    b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.EAST, align=Y(PadRef(Part("mcu"), 1))))
    plan = b.resolve()
    assert plan.box("terms").center.y == pytest.approx(plan.occupancy.pad_location("U5", "1").y)


def test_a_pad_of_another_cells_member_is_refused_naming_it():
    b = make_board()
    with pytest.raises(TypeError, match="other.u4.*not a member of cell terms"):
        b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH,
                                         align=(PadRef(Part("other.u4"), 1), PadRef(Part("mcu"), 1))))


def test_a_pad_of_a_part_that_is_no_member_is_refused():
    b = make_board()
    with pytest.raises(TypeError, match="mcu.*not a member of cell terms"):
        b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH,
                                         align=(PadRef(Part("mcu"), 1), PadRef(Part("mcu"), 2))))


def test_a_net_no_member_carries_is_refused():
    b = make_board()
    with pytest.raises(ValueError, match="no member of cell terms carries a pad on net E"):
        b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH, align=PadRef(Part("disp.u3"), 1)))


def test_an_x_on_an_east_side_and_a_y_on_a_south_side_are_refused():
    b = make_board()
    with pytest.raises(ValueError, match="decides the part's x"):
        b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.EAST, align=X(PadRef(Part("mcu"), 1))))
    with pytest.raises(ValueError, match="decides the part's y"):
        b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH, align=Y(PadRef(Part("mcu"), 1))))
    with pytest.raises(ValueError, match="decides the part's x"):
        b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.EAST,
                                         align=(PadRef(Part("terms.u1"), 1), X(PadRef(Part("mcu"), 1)))))


def test_past_and_a_lane_are_refused_for_a_cell():
    b = make_board()
    with pytest.raises(TypeError, match="Past.*a cell"):
        b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH,
                                         align=(PadRef(Part("terms.u1"), 1),
                                                Past([PadRef(Part("mcu"), 1)], Edge.EAST))))


def test_a_bare_point_is_refused_for_a_part():
    b = make_board()
    with pytest.raises(TypeError, match="needs the placed item's own pad"):
        b.place(Part("lone"), at=Beside(Cell("disp"), Edge.SOUTH, align=Origin(Part("mcu"))))


def test_a_taken_spot_is_stepped_out_along_the_side_with_the_alignment_kept():
    """As for a part: something already standing at the standoff moves the cell out along the side's axis;
    the axis the pad decides stays level with the point."""
    free = make_board()
    free.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH, align=PadRef(Part("mcu"), 2)))
    was = free.resolve()
    b = make_board()
    b.place(Part("lone"), at=Location(22.8, 22.2))      # on its second member
    b.place(Cell("terms"), at=Beside(Cell("disp"), Edge.SOUTH, align=PadRef(Part("mcu"), 2)))
    plan = b.resolve()
    assert plan.box("terms").top > was.box("terms").top + 1.0
    assert _pad_x(plan, "U2", "1") == pytest.approx(_pad_x(plan, "U5", "2"))
