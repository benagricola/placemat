"""Declared escape intent remains in the live common objective."""
from dataclasses import replace

import pytest

from placemat import score
from placemat.prepared_escape import prepare
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
        assert prepare(delta, [original.rotation], original.face) == (
            None, 'declared escape lanes require the exact Python objective')
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
