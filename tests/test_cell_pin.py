"""Pin(key, x, y) on a cell: the cell lands so one of its members' pads -
named by a CellPadRef, or a PadRef on the member - is exactly on the point,
the cell carried rigidly round it. Pure: synthetic boards."""
import pytest

from placemat.layout import Board
from placemat.values import Cell, CellPadRef, Face, Freedom, Location, PadRef, Part, Pin, X, Y
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="pd.u1", nets=("A", "B"), cell="pd"),
           footprint("C1", 0, 3, w=2, h=1, inst="pd.c1", nets=("C", "GND"), cell="pd"),
           footprint("R1", 40, 40, w=3, h=1.3, inst="r1", nets=("A", "GND"))]
    return Board(board_geometry(fps, cells=["pd"], width=80, height=80), edge_margin=1.0, **kw)


def test_a_cell_lands_with_a_members_pad_by_cellpadref_on_the_reference():
    b = make_board()
    b.place(Cell("pd"), at=Pin(CellPadRef(Cell("pd"), net="A"), 20.0, 30.0))
    plan = b.resolve()
    assert plan.occupancy.pad_location("U1", "1") == Location(20.0, 30.0)


def test_a_cell_lands_with_a_padref_on_one_of_its_members():
    b = make_board()
    b.place(Cell("pd"), at=Pin(PadRef(Part("pd.c1"), "GND"), 25.0, 35.0))
    plan = b.resolve()
    assert plan.occupancy.pad_location("C1", "2") == Location(25.0, 35.0)


def test_a_cell_pin_may_take_a_reference_point():
    b = make_board()
    b.place(Part("r1"), at=Location(20, 20))
    b.place(Cell("pd"), at=Pin(CellPadRef(Cell("pd"), net="A"),
                               X(PadRef(Part("r1"), "A")), Y(PadRef(Part("r1"), "A"), 10.0)))
    plan = b.resolve()
    r1_a = plan.occupancy.pad_location("R1", "1")
    u1_a = plan.occupancy.pad_location("U1", "1")
    assert (u1_a.x, u1_a.y) == pytest.approx((r1_a.x, r1_a.y + 10.0))


def test_a_cell_pin_honours_a_padrefs_offset():
    """PadRef(...).offset(dx, dy) names a point off the pad, as it does
    everywhere else: that point, not the bare pad, lands on (x, y)."""
    b = make_board()
    b.place(Cell("pd"), at=Pin(PadRef(Part("pd.u1"), "A").offset(1.0, -2.0), 20.0, 30.0))
    plan = b.resolve()
    u1_a = plan.occupancy.pad_location("U1", "1")
    assert (u1_a.x + 1.0, u1_a.y - 2.0) == pytest.approx((20.0, 30.0))


def test_a_cell_pin_honours_a_padrefs_local_offset():
    """PadRef(...).local(dx, dy) names a point in the member's own frame, as
    a part's own Pin honours it: that point, not the bare pad, lands on
    (x, y), even before any turn is asked for."""
    b = make_board()
    b.place(Cell("pd"), at=Pin(PadRef(Part("pd.u1"), "A").local(1.0, -2.0), 20.0, 30.0))
    plan = b.resolve()
    u1_a = plan.occupancy.pad_location("U1", "1")
    assert (u1_a.x + 1.0, u1_a.y - 2.0) == pytest.approx((20.0, 30.0))


def test_a_cell_pins_local_offset_turns_with_the_cells_own_rotation():
    b = make_board()
    b.place(Cell("pd"), at=Pin(PadRef(Part("pd.u1"), "A").local(1.0, -2.0), 20.0, 30.0), rotation=90)
    plan = b.resolve()
    u1_a = plan.occupancy.pad_location("U1", "1")
    assert (u1_a.x, u1_a.y) == pytest.approx((22.0, 31.0))


def test_a_cell_pins_local_offset_mirrors_on_the_back():
    b = make_board()
    b.place(Cell("pd"), at=Pin(PadRef(Part("pd.u1"), "A").local(1.0, -2.0), 20.0, 30.0), face=Face.BACK)
    plan = b.resolve()
    u1_a = plan.occupancy.pad_location("U1", "1")
    assert (u1_a.x, u1_a.y) == pytest.approx((21.0, 32.0))


def test_a_cell_pins_local_offset_turns_with_the_members_own_generated_rotation():
    """A member drawn at its own rotation within the cell (independent of
    the cell's own placement, which is 0 here) still turns .local()'s offset
    by that own rotation, not just the cell's."""
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="pd.u1", nets=("A", "B"), cell="pd", rotation=90),
           footprint("C1", 0, 3, w=2, h=1, inst="pd.c1", nets=("C", "GND"), cell="pd")]
    b = Board(board_geometry(fps, cells=["pd"], width=80, height=80), edge_margin=1.0)
    b.place(Cell("pd"), at=Pin(PadRef(Part("pd.u1"), "A").local(1.0, -2.0), 20.0, 30.0))
    plan = b.resolve()
    u1_a = plan.occupancy.pad_location("U1", "1")
    assert (u1_a.x, u1_a.y) == pytest.approx((22.0, 31.0))


def test_a_cell_pin_is_a_firm_placement():
    b = make_board()
    b.place(Cell("pd"), at=Pin(CellPadRef(Cell("pd"), net="A"), 20.0, 30.0))
    plan = b.resolve()
    assert plan.step("pd").freedom is Freedom.FIXED


def test_pin_refuses_a_bare_pad_key_on_a_cell():
    b = make_board()
    with pytest.raises(TypeError, match="CellPadRef"):
        b.place(Cell("pd"), at=Pin(1, 20.0, 30.0))


def test_pin_refuses_a_padref_naming_a_part_outside_the_cell():
    b = make_board()
    with pytest.raises(TypeError, match="not a pad of one of cell pd's members"):
        b.place(Cell("pd"), at=Pin(PadRef(Part("r1"), "A"), 20.0, 30.0))


def test_pin_refuses_a_cellpadref_naming_another_cell():
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="pd.u1", nets=("A", "B"), cell="pd"),
           footprint("U2", 0, 0, w=4, h=2, inst="qd.u2", nets=("A", "B"), cell="qd")]
    b = Board(board_geometry(fps, cells=["pd", "qd"], width=80, height=80), edge_margin=1.0)
    with pytest.raises(TypeError, match="not a pad of one of cell pd's members"):
        b.place(Cell("pd"), at=Pin(CellPadRef(Cell("qd"), net="A"), 20.0, 30.0))


def test_a_pin_still_places_a_part_by_its_own_pad():
    """The cell path does not disturb a plain part's Pin."""
    b = make_board()
    b.place(Part("r1"), at=Pin("A", 20.0, 30.0))
    plan = b.resolve()
    assert plan.occupancy.pad_location("R1", "1") == Location(20.0, 30.0)


@pytest.mark.parametrize("rotation", [0, 90])
def test_a_cell_placed_by_a_members_footprint_origin(rotation):
    """A member's footprint origin that is not a pad (a winding's arc
    centre): Pin(Part(member), x, y) puts that origin on the point, at the
    cell's rotation."""
    b = make_board()
    b.place(Cell("pd"), at=Pin(Part("pd.c1"), 30.0, 40.0), rotation=rotation)
    plan = b.resolve()
    at = plan.occupancy.items["C1"].reference.location
    assert (at.x, at.y) == pytest.approx((30.0, 40.0), abs=1e-6)


def test_a_cell_pin_by_a_part_that_is_not_its_member_is_refused():
    b = make_board()
    with pytest.raises(TypeError, match="member"):
        b.place(Cell("pd"), at=Pin(Part("r1"), 30.0, 40.0))
