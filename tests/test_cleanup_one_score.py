"""Under the one-score search the cleanup pass takes a move only when the run score's change, as the search computes
it, is below zero (D26). Synthetic boards."""
import dataclasses

from placemat import score
from placemat.cleanup import cleanup
from placemat.layout import Board
from placemat.score_search import MSTScorer
from placemat.settings import Settings
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _board(congestion):
    """m is pulled by net S to a1 and a2, which stand in a crowd of crossing nets (N1, N2): drawn in, its wire falls,
    and the worst congestion cell rises."""
    fps = [footprint("A1", 8, 18, w=2, h=1, inst="a1", nets=("S", "G1")),
           footprint("A2", 8, 26, w=2, h=1, inst="a2", nets=("S", "G2")),
           footprint("X1", 4, 14, w=2, h=1, inst="x1", nets=("N1", "G4")),
           footprint("X2", 16, 30, w=2, h=1, inst="x2", nets=("N1", "G5")),
           footprint("X3", 16, 14, w=2, h=1, inst="x3", nets=("N2", "G6")),
           footprint("X4", 4, 30, w=2, h=1, inst="x4", nets=("N2", "G7")),
           footprint("M", 50, 22, w=2, h=1, inst="m", nets=("S", "G3"))]
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False, score_congestion=congestion)
    board = Board(board_geometry(fps, width=60, height=44), edge_margin=0.5, settings=cfg)
    board.rect(width=60, height=44)
    for fp in fps:
        board.place(Part(fp.inst), at=fp.location)
    return board, board.resolve()


def _clean(board, plan, one):
    occ = plan.occupancy
    m = next(fp for fp in board.geometry.footprints if fp.ref == "M")
    pins = {"S": [("A1", "1"), ("A2", "1"), ("M", "1")]}
    one_score = (lambda fp: MSTScorer(board, occ, fp, plan=plan, prune=True)) if one else None
    before = sum(score.whole(board, occ, plan).values())
    result = cleanup(occ, {"m": m}, pins, [], board.clearance, 2, 40.0, 1.0, settings=board.settings,
                     one_score=one_score)
    return result, occ.items["M"].reference.location, before, sum(score.whole(board, occ, plan).values())


def test_a_move_that_lowers_wire_but_raises_the_one_score_is_refused():
    board, plan = _board(1000.0)
    _, old_spot, before, old_after = _clean(board, plan, one=False)
    assert old_after > before, 'fixture: the old objective takes a move the one score prices higher'
    board, plan = _board(1000.0)
    _, spot, before, after = _clean(board, plan, one=True)
    assert spot != old_spot
    assert after <= before


def test_a_move_that_lowers_the_one_score_is_taken():
    board, plan = _board(0.0)
    result, spot, before, after = _clean(board, plan, one=True)
    assert "m" in result.moves and spot != Location(50, 22)
    assert after < before


def test_a_swap_is_judged_by_the_one_score_change_in_two_lifts():
    """Two like parts, each wired across the board to the other's side: swapped, the run score falls by what the two
    lifts' changes add to, which is the whole board's change."""
    import pytest
    from placemat.cleanup import _one_score_swap
    fps = [footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("A", "G1")),
           footprint("J2", 55, 20, w=2, h=2, inst="j2", nets=("C", "G2")),
           footprint("R1", 50, 20, w=2, h=1, inst="r1", nets=("A", "G3")),
           footprint("R2", 10, 20, w=2, h=1, inst="r2", nets=("C", "G4"))]
    board = Board(board_geometry(fps, width=60, height=40), edge_margin=0.5,
                  settings=dataclasses.replace(Settings(), cleanup_enabled=False))
    board.rect(width=60, height=40)
    for fp in fps:
        board.place(Part(fp.inst), at=fp.location)
    plan = board.resolve()
    occ = plan.occupancy
    movable = {fp.inst: next(g for g in board.geometry.footprints if g.ref == fp.ref) for fp in fps[2:]}
    ref_of = {k: fp.ref for k, fp in movable.items()}
    spot = {k: occ.items[ref_of[k]].reference for k in movable}
    moved = {"r1": spot["r2"], "r2": spot["r1"]}
    before = sum(score.whole(board, occ, plan).values())
    for k in movable:
        occ.lift([ref_of[k]])
        occ.commit(movable[k], moved[k])
    after = sum(score.whole(board, occ, plan).values())
    one_score = lambda fp: MSTScorer(board, occ, fp, plan=plan, prune=True)       # noqa: E731
    assert after < before
    assert _one_score_swap(occ, movable, ref_of, "r1", "r2", spot, moved, one_score)
    assert not occ.pending & {"R1", "R2"}
    assert {k: occ.items[ref_of[k]].reference for k in movable} == moved
    assert sum(score.whole(board, occ, plan).values()) == pytest.approx(after)
    # back again raises the score: refused (both stand at the swap's new spots first, as cleanup leaves them)
    for k in movable:
        occ.lift([ref_of[k]])
        occ.commit(movable[k], spot[k])
    assert not _one_score_swap(occ, movable, ref_of, "r1", "r2", moved, spot, one_score)
