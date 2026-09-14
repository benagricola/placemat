"""A HIGH priority searched item is critical: it goes down first in its
tier, and when it finds no place the run stops there, so the board as it
stood is what gets looked at, not a board where the furniture has since
taken the space it needed."""
import pytest

from placemat.layout import Board, CriticalUnplaced
from placemat.values import Cell, Location, Part, Priority
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("U1", 10, 10, w=30, h=30, cell="mcu", inst="mcu.u", nets=("A", "B")),
           footprint("J1", 50, 50, w=8, h=3, inst="j1", nets=("A", "C")),
           footprint("R1", 60, 60, inst="r1", nets=("B", "C")),
           footprint("R2", 62, 62, inst="r2", nets=("C", "D"))]
    return Board(board_geometry(fps, cells=["mcu"], width=40, height=40), edge_margin=1.0)


def test_a_critical_item_that_finds_no_place_stops_the_resolve_with_the_free_pockets():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))                  # in the middle of a 40 board: the 30 x 30 cell cannot fit
    b.place(Cell("mcu"), priority=Priority.HIGH)
    b.place(Part("r1"))
    b.place(Part("r2"))
    with pytest.raises(CriticalUnplaced) as e:
        b.resolve()
    err = e.value
    assert err.key == "mcu" and "30.0 x 30.0" in str(err) and "free" in str(err).lower()
    assert err.plan is not None and err.plan.placement("j1") is not None
    assert all(s.item not in ("r1", "r2") for s in err.plan.steps)     # nothing placed after it


def test_keep_going_records_the_critical_failure_as_a_finding_and_carries_on():
    fps = [footprint("U1", 10, 10, w=30, h=30, cell="mcu", inst="mcu.u", nets=("A", "B")),
           footprint("J1", 50, 50, w=8, h=3, inst="j1", nets=("A", "C")),
           footprint("R1", 60, 60, inst="r1", nets=("B", "C"))]
    b = Board(board_geometry(fps, cells=["mcu"], width=40, height=40), edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Cell("mcu"), priority=Priority.HIGH)
    b.place(Part("r1"))
    plan = b.resolve()
    assert any(f.startswith("mcu") for f in plan.findings) and plan.placement("r1") is not None
