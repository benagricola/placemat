"""A lock entry for a cell holds only while the cell's members stand where they stood inside it when it was accepted: a
module re-laid out (its members moved or reordered) releases the entry, and says so."""
import dataclasses

from placemat import lock as L
from placemat.layout import Board
from placemat.values import Cell, Location, Near, Part
from tests.fixtures import board_geometry, footprint


def geometry(swapped=False):
    """J1 to the west; the cell `col` of two resistors one above the other, R1 north (south when `swapped`)."""
    j1 = footprint("J1", 10, 25, w=2, h=4, inst="j1", nets=("A", "B"))
    y1, y2 = (26, 24) if swapped else (24, 26)
    r1 = footprint("R1", 30, y1, w=2.2, h=0.8, nets=("A", "X"), cell="col", inst="col.r1")
    r2 = footprint("R2", 30, y2, w=2.2, h=0.8, nets=("B", "Y"), cell="col", inst="col.r2")
    return board_geometry([j1, r1, r2], cells=["col"], width=50, height=50)


def board(g):
    b = Board(g, edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(10, 25))
    b.place(Cell("col"), at=Near(Location(25, 25)), radius=5.0)
    return b


def accepted():
    b = board(geometry())
    (e,) = L.entries(b, b.resolve(), ["col"])
    return e


def test_an_entry_records_where_the_cells_members_stand_inside_it():
    e = accepted()
    assert e.members and e.members == L.members_digest(board(geometry()), next(
        i for i in board(geometry())._placements() if i.key == "col"))


def test_the_same_module_holds_the_entry():
    assert board(geometry()).resolve(lock=[accepted()]).step("col").lock == "held"


def test_a_module_whose_members_moved_inside_the_cell_releases_the_entry_and_says_why():
    """The same parts, the same links, the same shapes: only which resistor stands north changed, which the declaration
    digest does not see."""
    e = accepted()
    again = board(geometry(swapped=True)).resolve(lock=[e])
    step = again.step("col")
    assert step.lock == "released"
    assert any(n.get("reason", {}).get("form") == "members_moved" for n in step.notes if isinstance(n, dict))
    from placemat import step_text
    assert step_text.render({"kind": "lock_released", "reason": {"form": "members_moved"}}) == \
        "lock: released - the cell's members moved inside it since it was accepted"


def test_an_entry_written_before_members_were_recorded_still_holds():
    e = dataclasses.replace(accepted(), members="")
    assert board(geometry()).resolve(lock=[e]).step("col").lock == "held"


def test_an_entry_with_no_members_reads_and_digests_as_it_always_did():
    e = dataclasses.replace(accepted(), members="")
    assert "members" not in L._doc(e)
