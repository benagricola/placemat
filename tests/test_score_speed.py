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
