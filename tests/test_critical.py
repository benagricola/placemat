"""`required=True` says that failing to place this item stops the run. It is
independent of the rank and of whether the position is decided: placemat never
decides on its own that a failure is fatal."""
import pytest

from placemat.layout import Board, CriticalUnplaced, PlacementCollision
from placemat.values import Cell, Location, Part
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    fps = [footprint("U1", 10, 10, w=30, h=30, cell="mcu", inst="mcu.u", nets=("A", "B")),
           footprint("J1", 50, 50, w=8, h=3, inst="j1", nets=("A", "C")),
           footprint("R1", 60, 60, inst="r1", nets=("B", "C")),
           footprint("R2", 62, 62, inst="r2", nets=("C", "D"))]
    return Board(board_geometry(fps, cells=["mcu"], width=40, height=40), edge_margin=1.0, **kw)


def test_a_required_item_with_no_place_stops_the_resolve_with_the_free_pockets():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))       # mid-board: the 30 x 30 cell cannot fit
    b.place(Cell("mcu"), required=True)
    b.place(Part("r1"))
    b.place(Part("r2"))
    with pytest.raises(CriticalUnplaced) as e:
        b.resolve()
    err = e.value
    assert err.key == "mcu" and "30.0 x 30.0" in str(err) and "free" in str(err).lower()
    assert err.plan is not None and err.plan.placement("j1") is not None
    assert all(s.item not in ("r1", "r2") for s in err.plan.steps)


def test_an_item_that_is_not_required_is_left_off_and_the_run_carries_on():
    """placemat no longer decides for itself that a failure is fatal."""
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Cell("mcu"))                            # not required
    b.place(Part("r1"))
    plan = b.resolve()
    assert plan.placement("mcu") is None
    assert any(f.startswith("mcu") for f in plan.findings)
    assert plan.placement("r1") is not None


def test_keep_going_downgrades_a_required_searched_item_to_a_finding():
    b = make_board(keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Cell("mcu"), required=True)
    b.place(Part("r1"))
    plan = b.resolve()
    assert any(f.startswith("mcu") for f in plan.findings) and plan.placement("r1") is not None


def test_a_required_decided_item_that_collides_stops_even_under_keep_going():
    """A required item is not negotiable, and --keep-going does not make it so."""
    fps = [footprint("J1", 10, 10, w=8, h=8, inst="j1"), footprint("J2", 30, 10, w=8, h=8, inst="j2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("j2"), at=Location(20, 20), required=True)
    with pytest.raises(PlacementCollision) as e:
        b.resolve()
    assert any("j2" in c for c in e.value.collisions)


def test_a_decided_item_that_is_not_required_is_still_only_a_finding_under_keep_going():
    fps = [footprint("J1", 10, 10, w=8, h=8, inst="j1"), footprint("J2", 30, 10, w=8, h=8, inst="j2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("j2"), at=Location(20, 20))
    assert any("j2" in f for f in b.resolve().findings)


def test_the_step_says_an_item_is_required():
    b = make_board()
    b.place(Part("j1"), at=Location(35, 35))
    b.place(Part("r1"), required=True)
    assert "required" in b.resolve().step("r1").note
