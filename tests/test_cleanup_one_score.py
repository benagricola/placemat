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


class _Scanned:
    def __init__(self, walled, score, chosen):
        self.walled, self.score, self.chosen = walled, score, chosen


def _move(monkeypatch, now, found):
    """`_one_score_move` with the part's own spot standing at `now` and each hint's scan finding one of `found`
    ((walled, change, spot) each)."""
    from placemat import cleanup as c
    results = iter(_Scanned(*f) for f in found)
    monkeypatch.setattr(c, '_in_full', lambda scorer, placements, rotations=None: [now])
    monkeypatch.setattr(c, 'scan', lambda *a, **k: next(results))
    hints = list(range(len(found)))
    yes = lambda *a: True
    return c._one_score_move(None, None, 'k', 'cur', lambda fp: object(), hints, 1.0, 1.0, (0.0,), 0.1,
                             type('L', (), {'of': lambda self, k: False, '__call__': lambda self, *a: True})(), yes)


def test_a_move_that_walls_fewer_pads_is_taken_whatever_its_change(monkeypatch):
    # The part walls one pad beyond the board's floor where it stands. One spot walls none but costs 5 more; another
    # walls as many and costs 10 less. Validity ranks first (score.rank): the unwalling spot is the move.
    assert _move(monkeypatch, (1, 100.0), [(0, 105.0, 'unwalls'), (1, 90.0, 'cheaper')])[0] == 'unwalls'


def test_a_move_at_an_equal_walled_count_is_taken_only_when_it_lowers_the_score(monkeypatch):
    assert _move(monkeypatch, (1, 100.0), [(1, 90.0, 'cheaper')])[0] == 'cheaper'
    assert _move(monkeypatch, (1, 100.0), [(1, 100.0, 'same')]) is None


def test_a_move_that_walls_more_is_refused_whatever_its_change(monkeypatch):
    assert _move(monkeypatch, (1, 100.0), [(2, 10.0, 'walls')]) is None


def test_a_swap_that_walls_fewer_pads_is_taken_whatever_its_change(monkeypatch):
    from placemat import cleanup as c

    class Occ:
        pending = set()

        def lift(self, refs):
            pass

        def commit(self, fp, at):
            pass
    scores = iter([[(1, 0.0), (1, 2.0)], [(1, 2.0), (0, 9.0)]])      # a: spot, moved; b: spot, moved
    monkeypatch.setattr(c, '_in_full', lambda scorer, placements, rotations=None: next(scores))
    refs = {'a': 'A', 'b': 'B'}
    assert c._one_score_swap(Occ(), refs, refs, 'a', 'b', refs, refs, lambda fp: object())
    scores = iter([[(1, 0.0), (1, 2.0)], [(1, 2.0), (2, -50.0)]])
    assert not c._one_score_swap(Occ(), refs, refs, 'a', 'b', refs, refs, lambda fp: object())


def test_metrics_cleanup_reports_the_board_run_score_under_the_one_score_search():
    fps = [footprint("A1", 8, 18, w=2, h=1, inst="a1", nets=("S", "G1")),
           footprint("A2", 14, 26, w=2, h=1, inst="a2", nets=("S", "G2")),
           footprint("M", 50, 22, w=2, h=1, inst="m", nets=("S", "G3"))]
    cfg = dataclasses.replace(Settings(), score_congestion=0.0)
    board = Board(board_geometry(fps, width=60, height=44), edge_margin=0.5, settings=cfg)
    board.rect(width=60, height=44)
    board.place(Part("a1"), at=fps[0].location)
    board.place(Part("a2"), at=fps[1].location)
    board.place(Part("m"))
    plan = board.resolve()
    assert plan.cleanup and plan.cleanup["passes"] >= 1, plan.cleanup
    assert plan.cleanup["cost_after"] == round(sum(score.whole(board, plan.occupancy, plan).values()), 3)
    assert plan.cleanup["cost_after"] <= plan.cleanup["cost_before"]


class _Spot(str):
    """A spot by name, placement-like enough for `_best_first` (a rotation)."""
    rotation = 0.0


_CUR = _Spot('cur')


class _Board:
    """An occupancy stand-in for `_best_first`: it records the commits, and the parts moved so far."""
    pending = set()

    def __init__(self):
        self.moved = []

    def lift(self, refs):
        pass

    def unlift(self, refs):
        pass

    def commit(self, fp, at):
        if at != _CUR:
            self.moved.append((fp, at))


def _best_first(monkeypatch, moves):
    """`_best_first` over parts 'a' and 'b' (in that order) with no swaps offered; `moves(occ, k)` is the move part `k`
    finds on the board as it stands ((spot, now, there) or None). The moves made, in order."""
    from types import SimpleNamespace
    from placemat import cleanup as c
    occ = _Board()
    monkeypatch.setattr(c, '_one_score_move', lambda occ_, fp, k, cur, *a: moves(occ, k))
    keys = ['a', 'b']
    result = c.CleanupResult()
    c._best_first(occ, {k: k for k in keys}, keys, {k: _CUR for k in keys}, {k: k for k in keys},
                  {k: ['S'] for k in keys}, {k: [] for k in keys}, None, None, None, {k: (0.0,) for k in keys}, lambda k, cur, nets: [cur],
                  1.0, 0.5, 0.1, SimpleNamespace(cleanup_swap_radius=1.0, cleanup_swap_neighbours=0), None, 0.0, 2,
                  result, None)
    return occ.moved, result


def test_best_first_takes_the_cheaper_unwalling_move_that_part_order_would_wall_out(monkeypatch):
    # Both a and b can unwall the board's one walled pad; a, first in part order, at +10, b at -5. Part by part, a
    # moves first, and b's move then unwalls nothing (no move left that ranks above the board). Best first takes b's.
    def moves(occ, k):
        if occ.moved:
            return None
        return {'a': (_Spot('a there'), (1, 0.0), (0, 10.0)), 'b': (_Spot('b there'), (1, 0.0), (0, -5.0))}[k]
    moved, result = _best_first(monkeypatch, moves)
    assert moved == [('b', 'b there')]
    assert list(result.moves) == ['b'] and result.moves['b'][3] == -5.0


def test_best_first_ties_go_to_the_earlier_part(monkeypatch):
    def moves(occ, k):
        return None if occ.moved else (_Spot(k + ' there'), (0, 0.0), (0, -1.0))
    assert _best_first(monkeypatch, moves)[0] == [('a', 'a there')]


def test_best_first_never_makes_a_move_that_ranks_below_the_board(monkeypatch):
    """A real board, every part movable: at the start of each round the board ranks strictly above the round
    before (fewer walled pads, or as many and a lower run score), and the last round finds nothing to make."""
    from placemat import cleanup as c, escapes
    board, plan = _board(0.0)
    occ = plan.occupancy
    movable = {fp.inst: fp for fp in board.geometry.footprints}
    pins = {}
    for fp in board.geometry.footprints:
        for p in fp.pads:
            pins.setdefault(p.net, []).append((fp.ref, p.number))
    pins = {n: v for n, v in pins.items() if len(v) > 1}
    standings = []
    real = c._swap_pairs

    def pairs(occ_, *a, **kw):
        standings.append((escapes.Escapes(occ).counts()['escape_walled'],
                          sum(score.whole(board, occ, plan).values())))
        return real(occ_, *a, **kw)
    monkeypatch.setattr(c, '_swap_pairs', pairs)
    one_score = lambda fp: MSTScorer(board, occ, fp, plan=plan, prune=True)      # noqa: E731
    result = cleanup(occ, movable, pins, [], board.clearance, 2, 3.0, 0.5, settings=board.settings,
                     one_score=one_score)
    assert len(result.moves) + len(result.swaps) >= 1, 'fixture: cleanup makes a move'
    assert len(standings) == result.passes
    for before, after in zip(standings, standings[1:]):
        assert after[0] < before[0] or (after[0] == before[0] and after[1] < before[1] - 1e-6), standings
    assert result.cost_after < result.cost_before
