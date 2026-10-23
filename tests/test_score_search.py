"""The one-score search ranks complete signed objectives: every candidate on the terms but the escape grades, the best
few in full."""
from dataclasses import replace
import math

import pytest

from placemat import geometry, placer, score
from placemat.layout import Board
from placemat.score_search import MSTScorer
from placemat.settings import Settings
from placemat.values import CopperLayer, Face, Location, Near, Net, Part
from tests.fixtures import board_geometry, footprint


def triangle(crossing=False):
    parts = [footprint('A', 10, 10, nets=('S', 'Q'), inst='a'),
             footprint('B', 40, 10, nets=('S', 'Q'), inst='b'),
             footprint('C', 25, 36, nets=('S', 'Q'), inst='c'),
             footprint('M', 25, 19, nets=('S', 'Q'), inst='m')]
    if crossing:
        parts[-1:-1] = [footprint('X', 25, 5, nets=('V', 'Q'), inst='x'),
                       footprint('Y', 25, 15, nets=('V', 'Q'), inst='y')]
    board = Board(board_geometry(parts, width=60, height=60), keep_going=True,
                  settings=replace(Settings(), cleanup_enabled=False))
    board.rect(width=60, height=60)
    board.plane(Net('Q'), [CopperLayer.B])
    for part in parts:
        board.place(Part(part.inst), at=part.location)
    return board, parts[-1], board.resolve()


@pytest.mark.parametrize('crossing', [False, True])
def test_native_common_score_has_exact_full_cost_wall_and_floor_parity(crossing):
    if not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    board, item, plan = triangle(crossing)
    occ = plan.occupancy
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan)
    native = scoring.native((0, 90), Face.FRONT)
    assert native is not None, scoring.refusals
    negative = False
    uncrossed = False
    for x, y, turn in [(25, 19, 0), (24.8, 19.2, 1), (20, 25, 0), (30, 25, 1)]:
        candidate = replace(occ._geometry(item).reference, location=Location(x, y), rotation=(0, 90)[turn])
        expected = scoring(candidate)
        negative |= scoring.delta(candidate).terms['airwire'] < 0
        uncrossed |= scoring.delta(candidate).terms['crossings'] < 0
        native.floor = math.inf
        cost, walls = native.evaluate(x, y, turn)
        assert (walls, cost) == expected
        assert native.floor == (cost if walls == 0 else math.inf)
    assert negative, 'a Steiner-like added vertex must exercise negative wire delta'
    if crossing:
        assert uncrossed, 'adding the central vertex must remove the old edge crossing'


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('draw', [False, True])
@pytest.mark.parametrize('crossing', [False, True])
def test_real_scan_matches_exhaustive_whole_objective_and_tie_policy(monkeypatch, native, draw, crossing):
    if native and not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    board, item, plan = triangle(crossing)
    occ = plan.occupancy
    hint = occ._geometry(item).reference
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan)
    baseline = score.whole(board, occ, plan)
    expected = []
    for distance, x, y in placer._grid(hint.location, 0.4, 0.2):
        for rotation in (0, 90):
            candidate = replace(hint, location=Location(x, y), rotation=rotation)
            if occ.legal(item, candidate, board.geometry.default_clearance) is not None:
                continue
            view, _, _ = scoring.delta._view(candidate)
            after = score.whole(board, view, plan)
            cost = sum(after[k] - baseline[k] for k in after)
            change = scoring.delta(candidate)
            assert cost == pytest.approx(change.total, abs=1e-9)
            expected.append(((change.walled, change.total), distance, rotation, candidate))
    expected.sort(key=lambda row: row[:3])
    assert expected
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    # A finite incumbent must not become a signed wire-only pruning bound.
    scoring.best[0] = -1e6
    picked = []
    def choose(rows):
        picked.extend(rows)
        return rows[0]
    result = placer.scan(occ, item, hint, 0.4, 0.2, rotations=(90, 0),
                        clearance=board.geometry.default_clearance, score=scoring,
                        pick=choose if draw else None)
    assert result.chosen == expected[0][3]
    assert (result.walled, result.score) == expected[0][0]
    if draw:
        assert [row[3] for row in picked] == [row[3] for row in expected]


def test_unscorable_legal_candidates_refuse_measured_search_instead_of_infinite_winner(monkeypatch):
    from placemat.score_search import ScoreDomainError
    from placemat.values import Box
    from placemat.outline import rect_outline
    board, item, plan = triangle()
    occ = plan.occupancy
    hint = occ._geometry(item).reference
    # Deliberately inconsistent diagnostic frame: the legal outline still
    # covers this placement, but the score domain cannot measure its pads.
    occ.board_box = Box(0, 0, 15, 15)
    occ.board_shape = rect_outline(Box(0, 0, 60, 60))
    occ.__dict__.pop('_congestion', None)
    occ.__dict__.pop('_congestion_pads', None)
    occ.lift({item.ref})
    assert occ.legal(item, hint, board.geometry.default_clearance) is None
    scoring = MSTScorer(board, occ, item, plan=plan)
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', False)
    with pytest.raises(ScoreDomainError, match='complete objective is unmeasured'):
        placer.scan(occ, item, hint, 0.4, 0.2, rotations=(0,), score=scoring)


@pytest.mark.parametrize('native', [False, True])
def test_actual_scan_spreads_dense_net_on_common_congestion_objective(monkeypatch, native):
    from tests.test_surface_escapes import _part_of
    from tests.fixtures import pad
    if native and not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    parts = [_part_of(ref, ref.lower(), [pad(ref, ref.lower(), 1, 'S', x, 10, 0.01, 0.01)], x, 10)
             for ref, x in [('P1', 10), ('P2', 10.21), ('M', 10.42)]]
    board = Board(board_geometry(parts, width=60, height=60), keep_going=True,
                  settings=replace(Settings(), cleanup_enabled=False,
                                   score_congestion_box=0.5))     # a one-cell box: three pads 0.2 mm apart crowd it
    board.rect(width=60, height=60)
    for part in parts:
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    occ, item = plan.occupancy, parts[-1]
    hint = occ._geometry(item).reference
    original = score.whole(board, occ, plan)['congestion']
    occ.lift({item.ref})
    baseline = score.whole(board, occ, plan)
    scoring = MSTScorer(board, occ, item, plan=plan)
    expected = []
    negative = False
    for distance, x, y in placer._grid(hint.location, 6.0, 1.0):
        candidate = replace(hint, location=Location(x, y))
        if occ.legal(item, candidate, board.geometry.default_clearance) is not None:
            continue
        view, _, _ = scoring.delta._view(candidate)
        whole = score.whole(board, view, plan)
        change = scoring.delta(candidate)
        negative |= change.terms['congestion'] < 0
        assert sum(whole[k] - baseline[k] for k in whole) == pytest.approx(change.total, abs=1e-9)
        expected.append(((change.walled, change.total), distance, 0, candidate))
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    result = placer.scan(occ, item, hint, 6.0, 1.0, rotations=(0,), score=scoring)
    expected.sort(key=lambda row: row[:3])
    assert result.chosen == expected[0][3]
    view, _, _ = scoring.delta._view(result.chosen)
    assert score.whole(board, view, plan)['congestion'] < original
    assert negative, 'spreading must exercise a negative signed congestion term'


def test_common_search_scores_linkless_area_against_the_fixed_hint():
    from tests.test_score_measures import _two_part_board
    plans = {}
    for searched in (False, True):
        board = _two_part_board(settings=replace(Settings(), cleanup_enabled=False))
        board.rect(fit=True)
        for net in ('VIN', 'GND'):
            board.plane(Net(net), [CopperLayer.B])
        board.place(Part('u1'), at=Location(10, 10))
        board.place(Part('c1'), at=Near(Location(20, 20)) if searched else Location(20, 20),
                    radius=1.0, rotations=(0,))
        plan = board.resolve()
        plans[searched] = plan.placement('c1'), score.whole(board, plan.occupancy, plan)
    assert plans[False][0].location == Location(20, 20)
    assert plans[True][1]['airwire'] == plans[False][1]['airwire'] == 0.0
    assert plans[True][1]['area'] < plans[False][1]['area']


@pytest.mark.parametrize('native', [False, True])
def test_actual_scan_counts_distant_same_net_escape_improvement(monkeypatch, native):
    from placemat.escapes import Way, judging
    from tests.test_escape_findings import _walled_in
    from tests.test_surface_escapes import _via_only_board
    if native and not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    parts = _walled_in(0.1)
    ring = parts[1]
    parts[1] = replace(ring, pads=tuple(p for p in ring.pads
        if not (p.box.center.x > 30.5 and abs(p.box.center.y - 30) < 0.1)))
    parts[2] = footprint('T1', 10, 30, inst='t1', nets=('IN', 'Z'))
    item = footprint('N1', 50, 50, inst='n1', nets=('IN', 'Z'))
    board = _via_only_board(parts + [item])
    for y in (29.25, 30.75):
        board.track(Net('Z'), [Location(31.9, y), Location(34, y)], layer=CopperLayer.F,
                    width=0.2, why='fixture gap walls')
    plan = board.resolve()
    occ = plan.occupancy
    occ.lift({'N1'})
    assert judging(occ).judge('U9', '1') is Way.AWAY
    baseline = score.whole(board, occ, plan)
    scoring = MSTScorer(board, occ, item, plan=plan)
    hint = replace(occ._geometry(item).reference, location=Location(35, 30))
    expected = []
    improved = False
    for distance, x, y in placer._grid(hint.location, 11, 5):
        candidate = replace(hint, location=Location(x, y))
        if occ.legal(item, candidate, board.geometry.default_clearance) is not None:
            continue
        view, _, _ = scoring.delta._view(candidate)
        whole = score.whole(board, view, plan)
        change = scoring.delta(candidate)
        improved |= change.terms['escape_closed'] < 0 and judging(view).judge('U9', '1') is Way.SURFACE
        assert sum(whole[k] - baseline[k] for k in whole) == pytest.approx(change.total, abs=1e-9)
        expected.append(((change.walled, change.total), distance, 0, candidate))
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    result = placer.scan(occ, item, hint, 11, 5, rotations=(0,), score=scoring)
    expected.sort(key=lambda row: row[:3])
    assert result.chosen == expected[0][3]
    assert (result.walled, result.score) == expected[0][0]
    assert improved, 'the scan must score a remote original pad finding an escape'


def test_a_native_scan_on_a_board_with_declared_lanes_ranks_as_the_python_objective(monkeypatch):
    from tests.test_escape_turned_lanes import _board
    if not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    monkeypatch.setattr(Board, '_report_turns', lambda *args: None)
    board, _ = _board([44, 45], bypass_at=(25.35, 28.0))
    plan = board.resolve()
    occ, item = plan.occupancy, board.geometry.footprint('C1')
    hint = occ._geometry(item).reference
    occ.lift({'C1'})
    baseline = score.whole(board, occ, plan)
    scoring = MSTScorer(board, occ, item, plan=plan)
    native = scoring.native((hint.rotation,), hint.face)
    assert native is not None, scoring.refusals
    expected, lane_counts = [], set()
    for distance, x, y in placer._grid(hint.location, 0.6, 0.2):
        candidate = replace(hint, location=Location(x, y))
        if occ.legal(item, candidate, board.geometry.default_clearance) is not None:
            continue
        view, _, _ = scoring.delta._view(candidate)
        whole = score.whole(board, view, plan)
        change = scoring.delta(candidate)
        lane_counts.add(board._declared_lanes_blocked(view, plan))
        assert sum(whole[k] - baseline[k] for k in whole) == pytest.approx(change.total, abs=1e-9)
        expected.append(((change.walled, change.total), distance, hint.rotation, candidate))
    assert len(lane_counts) > 1, 'legal blocker moves must change a different parts lane obligation'
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', True)
    result = placer.scan(occ, item, hint, 0.6, 0.2, rotations=(hint.rotation,), score=scoring)
    expected.sort(key=lambda row: row[:3])
    assert result.chosen == expected[0][3]
    assert (result.walled, result.score) == expected[0][0]
    assert native.python_asked > 0


@pytest.mark.parametrize('native', [False, True])
def test_actual_scan_rejects_cheaper_walled_candidate_before_scalar(monkeypatch, native):
    from placemat.occupancy import ban_shape
    from tests.fixtures import pad, track
    from tests.test_surface_escapes import _part_of, _round_pad
    if native and not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    item = _part_of('P1', 'p1', [_round_pad('P1', 'p1', 1, 'S', 30, 30, 0.5)], 30, 30)
    target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, 30, 0.5, 0.5)], 10, 30)
    ring = []
    for index in range(96):
        angle = 2 * math.pi * index / 96
        x, y = 30 + 1.3 * math.cos(angle), 30 + 1.3 * math.sin(angle)
        ring.append(track('Z', x, y, x + 0.001, y, w=0.1))
    cfg = replace(Settings(), cleanup_enabled=False, score_escape_closed=0.0, score_escape_via=0.0,
                  score_escape_crossed=0.0, score_congestion=0.0)
    board = Board(board_geometry([item, target], width=60, height=60, copper=ring), keep_going=True, settings=cfg)
    board.rect(width=60, height=60)
    for part in [item, target]:
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    occ = plan.occupancy
    occ.add_copper([ban_shape('via exclusion', ((28, 28), (32, 28), (32, 32), (28, 32)), None, ('Z',))])
    hint = occ._geometry(item).reference
    occ.lift({'P1'})
    scoring = MSTScorer(board, occ, item, plan=plan)
    inside = scoring(hint)
    outside = scoring(replace(hint, location=Location(34, 30)))
    assert inside[0] > outside[0] == 0
    assert inside[1] < outside[1], 'fixture must make the walled pose cheaper'
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    result = placer.scan(occ, item, hint, 4, 2, rotations=(0,), score=scoring,
                        within=lambda x, y: x >= 30 and y == 30)
    assert result.chosen.location == Location(34, 30)
    assert result.walled == 0


@pytest.mark.parametrize('native', [False, True])
def test_mst_back_face_action_is_preserved_in_actual_resolve(monkeypatch, native):
    from tests.test_score_measures import _either_board
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    board = _either_board(Face.EITHER)
    board.settings = replace(board.settings, cleanup_enabled=False)
    plan = board.resolve()
    assert plan.placement('r1').face is Face.BACK
    assert next(step for step in plan.steps if step.item == 'r1').back_face
    measures = score.plan_measures(board, plan)
    assert measures['back_face'] == 1
    assert score.terms(measures, board.settings)['back_face'] == board.settings.score_back_face


def test_mst_snapshot_refuses_reuse_after_commit_and_rebuilds_for_next_lift():
    board, item, plan = triangle()
    occ = plan.occupancy
    hint = occ._geometry(item).reference
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan)
    scoring(hint)
    scoring.native((0,), Face.FRONT)
    occ.commit(item, hint)
    with pytest.raises(ValueError, match='snapshot'):
        scoring(hint)
    with pytest.raises(ValueError, match='snapshot'):
        scoring.native((0,), Face.FRONT)
    occ.lift({item.ref})
    fresh = MSTScorer(board, occ, item, plan=plan)
    assert fresh(hint)[0] == 0


@pytest.mark.parametrize('native', [False, True])
def test_fitted_board_search_expands_content_within_source_search_domain(monkeypatch, native):
    from tests.test_score_measures import _two_part_board
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    board = _two_part_board(settings=replace(Settings(), cleanup_enabled=False))
    board.rect(fit=True)
    for net in ('VIN', 'GND'):
        board.plane(Net(net), [CopperLayer.B])
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Near(Location(20, 20)), radius=1.0, rotations=(0,))
    plan = board.resolve()
    assert plan.placement('c1') is not None
    assert plan.placement('c1').location.x > 14.1
    assert plan.outline.right > 14.1
    assert not any('unmeasured' in str(f) for f in plan.findings)


def test_mixed_score_domain_keeps_explicit_scan_refusal_policy():
    from placemat.score_search import ScoreDomainError
    from placemat.values import Box
    board, item, plan = triangle()
    occ = plan.occupancy
    occ.board_box = Box(0, 0, 25, 60)
    from placemat.outline import rect_outline
    occ.board_shape = rect_outline(Box(0, 0, 60, 60))
    occ.__dict__.pop('_congestion', None)
    occ.__dict__.pop('_congestion_pads', None)
    hint = occ._geometry(item).reference
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan)
    inside = replace(hint, location=Location(24, 19))
    outside = replace(hint, location=Location(28, 19))
    assert occ.legal(item, inside, board.geometry.default_clearance) is None
    assert occ.legal(item, outside, board.geometry.default_clearance) is None
    scoring(inside)
    with pytest.raises(ScoreDomainError) as caught:
        scoring(outside)
    assert caught.value.code == 'score_domain_unmeasured'
    assert caught.value.facts == {'placement': outside, 'policy': 'abort_scan'}


@pytest.mark.parametrize('native', [False, True])
def test_mst_actual_giveway_scan_prices_action_on_top_of_common_objective(monkeypatch, native):
    from tests.test_vias_give_way import _moving_board
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    board = _moving_board((39.1, 42.2), True, (19.5, 23.0))
    board.settings = replace(board.settings, cleanup_enabled=False)
    plan = board.resolve()
    occ = Occupancy(board.geometry, 0.5, settings=board.settings)
    item = board.geometry.cells['m']
    centre = occ._geometry(item).reference.location
    hint = Placement(Location(round(centre.x - 20, 9), round(centre.y - 20, 9)), 0.0, Face.FRONT)
    occ.lift({fp.ref for fp in item.members})
    scoring = MSTScorer(board, occ, item, plan=plan)
    expected = scoring(hint)
    scoring.best[0] = math.inf
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    result = placer.scan(occ, item, hint, 0.0, 0.2, (0.0,), score=scoring)
    assert result.chosen == hint
    assert result.walled == expected[0]
    assert result.score == pytest.approx(expected[1] + board.settings.score_via_move)


@pytest.mark.parametrize('native', [False, True])
def test_backface_action_weight_changes_actual_mst_winner(monkeypatch, native):
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    faces = []
    for cost in (0.0, 100.0):
        parts = [footprint('B1', 20, 20, w=12, h=12, inst='b1', nets=('S', 'M')),
                 footprint('R1', 5, 5, inst='r1', nets=('S', 'Y'))]
        board = Board(board_geometry(parts, width=40, height=40), edge_margin=0.5,
                      settings=replace(Settings(), place_step=2,
                                       score_back_face=cost, cleanup_enabled=False))
        for net in ('M', 'Y'):
            board.plane(Net(net), [CopperLayer.B])
        board.place(Part('b1'), at=Location(20, 20))
        board.place(Part('r1'), at=Near(Location(20, 20)), radius=12,
                    rotations=(0,), face=Face.EITHER)
        plan = board.resolve()
        faces.append(plan.placement('r1').face)
    assert faces == [Face.BACK, Face.FRONT]


def test_native_common_adapter_refuses_malformed_inputs_before_scoring():
    from placemat.prepared_escape import prepare
    if not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    board, item, plan = triangle()
    occ = plan.occupancy
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan)
    prepared, reason = prepare(scoring.delta, (0,), Face.FRONT)
    assert prepared is not None, reason
    for weights, floor in [((-1, 0, 0), math.inf), ((math.inf, 0, 0), math.inf),
                           ((0, math.nan, 0), math.inf), ((0, 0, 0), math.nan)]:
        with pytest.raises(ValueError, match='weights or floor'):
            geometry._native.NativeDeltaScoring(prepared.candidate, prepared.scoring,
                                                prepared.surface, weights, (0, 0), floor)
    native = scoring.native((0,), Face.FRONT)
    for x, y, turn in [(math.nan, 19, 0), (25, math.inf, 0), (1e300, 19, 0), (25, 19, 1)]:
        with pytest.raises(ValueError):
            native.evaluate(x, y, turn)


@pytest.mark.parametrize('native', [False, True])
def test_giveway_action_weight_changes_actual_mst_winner(monkeypatch, native):
    from tests.test_vias_give_way import _moving_board
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    chosen = []
    for cost in (0, 100):
        board = _moving_board((39.1, 42.2), True, (19.5, 23.0),
                             settings=replace(Settings(), score_via_move=cost, cleanup_enabled=False))
        plan = board.resolve()
        occ = Occupancy(board.geometry, 0.5, settings=board.settings)
        item = board.geometry.cells['m']
        centre = occ._geometry(item).reference.location
        hint = Placement(Location(round(centre.x - 20, 9), round(centre.y - 20, 9)), 0, Face.FRONT)
        occ.lift({fp.ref for fp in item.members})
        scoring = MSTScorer(board, occ, item, plan=plan)
        result = placer.scan(occ, item, hint, 0.2, 0.2, (0,), score=scoring)
        assert result.chosen is not None
        assert scoring.best[0] == result.score
        chosen.append(result.chosen)
    assert chosen[0].location == hint.location
    assert chosen[1].location == Location(hint.location.x, round(hint.location.y - 0.2, 9))


@pytest.mark.parametrize('native', [False, True])
def test_a_scan_of_a_pushed_item_ranks_as_the_python_objective(monkeypatch, native):
    board, item, plan = triangle()
    board.push(Part('m'), from_=Part('a'), falloff=3, reference=(20, 3.2), limit=0.3)
    occ = plan.occupancy
    hint = occ._geometry(item).reference
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan)
    prepared = scoring.native((0,), Face.FRONT)
    assert scoring.delta.push_judged
    assert prepared is not None or not hasattr(geometry._native, 'NativeDeltaScoring'), scoring.refusals
    baseline = score.whole(board, occ, plan)
    expected = []
    for distance, x, y in placer._grid(hint.location, 0.4, 0.2):
        candidate = replace(hint, location=Location(x, y), rotation=0)
        if occ.legal(item, candidate, board.geometry.default_clearance) is not None:
            continue
        change = scoring.delta(candidate)
        view, _, _ = scoring.delta._view(candidate)
        after = score.whole(board, view, plan)
        assert change.terms['push'] == after['push'] - baseline['push']
        expected.append(((change.walled, change.total), distance, candidate))
    expected.sort(key=lambda row: row[:2])
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    result = placer.scan(occ, item, hint, 0.4, 0.2, (0,), score=scoring)
    assert result.chosen == expected[0][2]
    assert (result.walled, result.score) == expected[0][0]
    assert scoring.best[0] == result.score
    if native and prepared is not None:
        assert prepared.python_asked > 0


def test_an_item_no_push_judges_is_scored_natively_without_asking_for_the_push_term():
    if not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    board, _, plan = triangle()
    board.push(Part('m'), from_=Part('a'), falloff=3, reference=(20, 3.2), limit=0.3)
    occ = plan.occupancy
    item = board.geometry.footprint('C')
    hint = occ._geometry(item).reference
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan)
    prepared = scoring.native((hint.rotation,), hint.face)
    assert not scoring.delta.push_judged
    assert prepared is not None, scoring.refusals
    for dx, dy in [(0, 0), (3, -2), (-4, 1)]:
        candidate = replace(hint, location=Location(hint.location.x + dx, hint.location.y + dy))
        change = scoring.delta(candidate)
        assert change.terms['push'] == 0.0
        assert prepared.full(candidate.location.x, candidate.location.y, 0) == pytest.approx(
            (change.total, change.walled), abs=1e-9)
    assert prepared.python_asked == 0


@pytest.mark.parametrize('native', [False, True])
def test_arrangement_action_cost_changes_mst_winner_without_pruning_signed_objective(monkeypatch, native):
    from tests.test_arrangement_search import board as arrangement_board, _consistent
    from placemat.values import Cell
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    arrangements = []
    for cost in (0, 100):
        board = arrangement_board((60, 30), replace(Settings(), score_arrangement=cost, cleanup_enabled=False))
        board.place(Cell('mod'), at=Near(Location(40, 30), radius=0.5, step=0.5))
        plan = board.resolve()
        arrangements.append(plan.placement('mod').arrangement)
        note = next(n for n in plan.step('mod').notes if n['kind'] == 'arrangement')
        _consistent(note)
        rows = {row['id']: row for row in note['tried']}
        assert rows['c_in.east']['score'] - cost < rows['default']['score']
    assert arrangements == ['c_in.east', '']


@pytest.mark.parametrize('native', [False, True])
def test_shared_pair_net_price_changes_actual_scan_winner(monkeypatch, native):
    from placemat.board_geometry import NetClass
    if native and not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    winners = []
    for price in (0.1, 80.0):
        parts = [footprint(ref, x, y, nets=(net, 'Q'), inst=ref.lower())
                 for ref, x, y, net in [('A', 10, 10, 'S'), ('B', 40, 10, 'S'),
                                       ('C', 25, 36, 'S'), ('X', 10, 16, 'V'),
                                       ('Y', 40, 16, 'V'), ('M', 25, 19, 'S')]]
        physical = board_geometry(parts, width=60, height=60)
        pair = NetClass('Pair', 0.2, 0.2, 0.6, 0.3, 0.2, 0.2)
        physical.netclasses.update({'S': pair, 'OTHER': pair})
        board = Board(physical, keep_going=True, settings=replace(
            Settings(), cleanup_enabled=False,
            score_crossing_pair_net=price, score_crossing=0.01, score_congestion=0.0,
            score_escape_crossed=0.0, score_escape_closed=0.0, score_escape_via=0.0))
        board.rect(width=60, height=60)
        board.plane(Net('Q'), [CopperLayer.B])
        for part in parts:
            board.place(Part(part.inst), at=part.location)
        plan = board.resolve()
        occ, item = plan.occupancy, parts[-1]
        hint = occ._geometry(item).reference
        occ.lift({item.ref})
        scoring = MSTScorer(board, occ, item, plan=plan)
        result = placer.scan(occ, item, hint, 12.0, 2.0, rotations=(0,), score=scoring)
        winners.append((result.chosen, scoring.delta(result.chosen).terms))
    assert winners[0][0].location == Location(25.0, 19.0)
    assert winners[1][0].location == Location(25.0, 15.0)
    assert winners[0][1]['airwire'] < winners[1][1]['airwire']
    assert winners[0][1]['crossings'] > winners[1][1]['crossings'] == 0.0


def test_actual_area_prices_trade_fitted_size_for_wire_length():
    rows = []
    for weight in (0, .1, .25):
        cfg = replace(Settings(), cleanup_enabled=False,
                      score_area=weight, score_congestion=0)
        parts = (footprint('H', 3, 20, nets=('Q', 'Q')),
                 footprint('A', 20, 20, nets=('S', 'Q')),
                 footprint('M', 25, 24, w=20, nets=('S', 'Q')))
        board = Board(board_geometry(parts, width=70, height=60), keep_going=True, settings=cfg)
        board.rect(fit=True)
        board.plane(Net('Q'), [CopperLayer.B])
        board.place(Part('h'), at=Location(3, 20))
        board.place(Part('a'), at=Location(20, 20))
        board.place(Part('m'), at=Near(Location(25, 24)), radius=5, rotations=(0,))
        plan = board.resolve()
        measures = score.plan_measures(board, plan)
        rows.append((plan.placement('m'), measures['area_mm2'], measures['airwire_mm']))
    assert len({pose for pose, _, _ in rows}) == 3
    assert rows[0][1] > rows[1][1] > rows[2][1]
    assert rows[0][2] < rows[1][2] < rows[2][2]


@pytest.mark.parametrize('crossing', [False, True])
def test_pruned_native_scan_keeps_the_exhaustive_seeds_and_winner(monkeypatch, crossing):
    """R13: the native sweep prunes partial costs on proved bounds only past the `place.escape_spots`-th best, and the
    scan's walk weighs a pruned candidate it reaches, so its seeds, and so its winner and standing, are the
    unpruned scan's."""
    if not hasattr(geometry._native, 'NativeDeltaScoring'):
        pytest.skip('complete native sweep scorer unavailable')
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', True)
    runs = {}
    for prune in (False, True):
        board, item, plan = triangle(crossing)
        board.settings = replace(board.settings, place_escape_spots=2)
        occ = plan.occupancy
        hint = occ._geometry(item).reference
        occ.lift({item.ref})
        scoring = MSTScorer(board, occ, item, plan=plan, prune=prune)
        result = placer.scan(occ, item, hint, 8.0, 0.25, rotations=(0, 90), clearance=board.geometry.default_clearance,
                             score=scoring)
        native = scoring.native((0, 90), Face.FRONT)
        runs[prune] = (result.chosen, result.walled, result.score, native.pruned)
    assert runs[True][:3] == runs[False][:3]
    assert runs[False][3] == 0 and runs[True][3] > 0, runs
