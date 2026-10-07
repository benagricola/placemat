import math

import pytest


def test_nudge_corpus_has_exact_count_four_turns_and_bounded_offsets():
    from fixtures.score_speed import candidates
    from placemat.placement import Placement
    from placemat.values import Location
    original = Placement(Location(10, 20), 37)
    rotations, rows = candidates(original)
    assert rotations == (37, 127, 217, 307)
    assert len(rows) == 2000
    assert {turn for _, turn in rows} == {0, 1, 2, 3}
    assert all(abs(p.location.x - 10) <= 1 and abs(p.location.y - 20) <= 1 for p, _ in rows)
    assert all(p.rotation == rotations[turn] for p, turn in rows)


def test_old_native_inspection_matches_exact_python_score_and_refuses_bad_candidates():
    from placemat import geometry
    from placemat.layout import Scorer
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    if geometry._native is None or not hasattr(geometry._native.NativeScoring, 'evaluate'):
        pytest.skip('native timing entry point unavailable')
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    original = plan.placement('c1')
    occ.lift({'C1'})
    try:
        scorer = Scorer(board.settings, item, occ, board._targets(item, occ, set(occ.items) - occ.pending), False)
        native = scorer.native([original.rotation], original.face)
        assert native is not None
        cost, walls = native.evaluate(original.location.x, original.location.y, 0)
        expected_walls, expected_cost = scorer(original)
        assert walls == expected_walls
        assert cost == pytest.approx(expected_cost, abs=1e-9)
        for x, y, turn in [(math.nan, 0, 0), (0, math.inf, 0), (1e300, 0, 0), (0, 0, 1)]:
            with pytest.raises(ValueError):
                native.evaluate(x, y, turn)
    finally:
        occ.commit(item, original)


def test_timing_rotated_cell_restores_geometry_copper_and_score():
    from fixtures.score_speed import measure
    from placemat import geometry, score
    from placemat.layout import Board
    from placemat.values import Cell, Location
    from tests.test_cell_drops import _geom
    if geometry._native is None or not hasattr(geometry._native.NativeScoring, 'evaluate'):
        pytest.skip('native timing entry point unavailable')
    b = Board(_geom(), keep_going=True)
    b.rect(width=80, height=80)
    b.place(Cell('m'), at=Location(20, 20), rotation=90)
    plan = b.resolve()
    step = next(s for s in plan.steps if s.item == 'm')
    occ = plan.occupancy
    before = (dict(occ.items), tuple(occ.copper), frozenset(occ.pending), score.whole(b, occ, plan))
    row = measure(b, plan, step, count=4, repeats=1)
    assert row['legal'] > 0
    assert (dict(occ.items), tuple(occ.copper), frozenset(occ.pending), score.whole(b, occ, plan)) == before


def test_actual_resolve_timing_records_commits_and_restores_observers():
    from fixtures.score_speed import resolve_measure
    from placemat.layout import Board, Scorer
    from placemat.occupancy import Occupancy, NativeSweeper
    from placemat.score_search import MSTScorer
    from placemat.values import Location, Near, Part
    from dataclasses import replace
    from tests.test_score_measures import _two_part_board
    methods = (Occupancy.commit, NativeSweeper.run, Board._scorer, Scorer.native, MSTScorer.native)
    for mode in ('clique', 'mst'):
        board = _two_part_board()
        board.settings = replace(board.settings, place_search_wire=mode, cleanup_enabled=False)
        board.place(Part('u1'), at=Location(10, 10))
        board.place(Part('c1'), at=Near(Location(20, 20)), radius=0.4, rotations=(0,))
        plan, stats = resolve_measure(board)
        assert plan.placement('c1') is not None
        assert stats['commit_calls'] >= 2 and stats['commit_us'] > 0
        assert stats['scorer_setup_calls'] > 0 and stats['scorer_setup_us'] > 0
        assert stats['seconds'] > 0
        assert (Occupancy.commit, NativeSweeper.run, Board._scorer, Scorer.native, MSTScorer.native) == methods


def test_failed_resolve_timing_restores_all_observers(monkeypatch):
    from fixtures.score_speed import resolve_measure
    from placemat.layout import Board, Scorer
    from placemat.occupancy import Occupancy, NativeSweeper
    from placemat.score_search import MSTScorer
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    def fail(*args, **kwargs):
        raise RuntimeError('injected adoption failure')
    monkeypatch.setattr(Occupancy, 'commit', fail)
    methods = (Occupancy.commit, NativeSweeper.run, Board._scorer, Scorer.native, MSTScorer.native)
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    with pytest.raises(RuntimeError, match='injected adoption failure'):
        resolve_measure(board)
    assert (Occupancy.commit, NativeSweeper.run, Board._scorer, Scorer.native, MSTScorer.native) == methods


def test_paired_resolve_timing_uses_fresh_boards_and_labels_nudge_origin(capsys):
    from fixtures.score_speed import run_fixture
    from placemat.values import Location, Near, Part
    from tests.test_score_measures import _two_part_board
    from types import SimpleNamespace
    import json
    made = []
    def make():
        board = _two_part_board()
        board.place(Part('u1'), at=Location(10, 10))
        board.place(Part('c1'), at=Near(Location(20, 20)), radius=0.4, rotations=(0,))
        made.append(board)
        return board
    rows = run_fixture('synthetic', make, SimpleNamespace(items=1, candidates=4, repeats=1), 'mst')
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    resolves = [row for row in output if row['type'] == 'resolve']
    assert len(made) == 2 and made[0] is not made[1]
    assert [row['instrumented'] for row in resolves] == [False, True]
    assert resolves[0]['score'] == resolves[1]['score']
    assert all(row['search'] == 'mst' for row in resolves)
    assert rows and all(row['measurement_board_search'] == 'mst' for row in rows)
