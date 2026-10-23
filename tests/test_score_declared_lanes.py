"""Declared escape intent remains in the live common objective."""
from dataclasses import replace

import pytest

from placemat import score
from placemat.score_delta import Delta
from placemat.values import Location
from tests.test_escape_turned_lanes import _board


@pytest.mark.parametrize('weight', [0.0, 400.0])
def test_blocker_move_rechecks_other_parts_declared_lanes_without_global_mutation(monkeypatch, weight):
    # This test judges lane scoring, separately from the turn diagnostics.
    monkeypatch.setattr('placemat.layout.Board._report_turns', lambda *args: None)
    board, _ = _board([44, 45], bypass_at=(25.35, 28.0))
    board.settings = replace(board.settings, score_escape_lane=weight)
    plan = board.resolve()
    occ = plan.occupancy
    blocker = board.geometry.footprint('C1')
    original = occ._geometry(blocker).reference
    context = board.__dict__.get('_escape_ctx')
    fixed_copper = tuple(occ.copper)
    counts = []
    occ.lift({'C1'})
    try:
        base = score.whole(board, occ, plan)
        delta = Delta(board, occ, blocker, plan.links, plan=plan)
        for point in [(25.35, 28.0), (10.0, 10.0)]:
            candidate = replace(original, location=Location(*point))
            view, _, _ = delta._view(candidate)
            raw = score._incremental(board, view, plan)['findings']['escape_lane']
            counts.append(raw)
            change = delta(candidate)
            whole = score.whole(board, view, plan)
            assert change.terms['escape_lane'] == pytest.approx(whole['escape_lane'] - base['escape_lane'])
            assert whole['escape_lane'] == weight * raw
            candidate_plan = replace(plan, occupancy=view)
            measured = score.plan_measures(board, candidate_plan)
            assert measured['findings']['escape_lane'] == raw
            assert score.terms(measured, replace(board.settings, score_escape_lane=400.0))['escape_lane'] == 400.0 * raw
            assert board.__dict__.get('_escape_ctx') is context
            assert tuple(occ.copper) == fixed_copper
        assert counts[0] > counts[1], 'a blocker-only move must affect a different parts declared escape'
    finally:
        occ.unlift({'C1'})


def test_the_native_scorer_prices_declared_lanes_as_the_python_delta(monkeypatch):
    from placemat import geometry
    from placemat.score_search import MSTScorer
    if not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    monkeypatch.setattr('placemat.layout.Board._report_turns', lambda *args: None)
    board, _ = _board([44, 45], bypass_at=(25.35, 28.0))
    board.settings = replace(board.settings, score_escape_lane=400.0)
    plan = board.resolve()
    occ = plan.occupancy
    blocker = board.geometry.footprint('C1')
    original = occ._geometry(blocker).reference
    occ.lift({'C1'})
    try:
        scoring = MSTScorer(board, occ, blocker, plan=plan)
        native = scoring.native((original.rotation,), original.face)
        assert native is not None, scoring.refusals
        lanes = set()
        for point in [(25.35, 28.0), (25.0, 27.5), (10.0, 10.0), (40.0, 12.0)]:
            candidate = replace(original, location=Location(*point))
            asked = native.python_asked
            change = scoring.delta(candidate)
            lanes.add(change.terms['escape_lane'])
            assert native.full(*point, 0) == pytest.approx((change.total, change.walled), abs=1e-9)
            assert native.partial_cost(*point, 0) == pytest.approx(scoring.scan(candidate)[1], abs=1e-9)
            # the lanes are laid out again for a candidate near them only
            assert (native.python_asked > asked) == (point[1] > 20), point
        assert len(lanes) > 1, 'the points must include a move that blocks a lane and one that does not'
        assert scoring.delta.lanes_near((original.rotation,), original.face) is not None
    finally:
        occ.unlift({'C1'})
